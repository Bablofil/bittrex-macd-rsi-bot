import time

import numpy
import talib
import os
import sqlite3
import logging

import requests
import urllib, http.client
import hmac, hashlib

from datetime import datetime
from config import Config
from logs import BaseLog

import threading

lock = threading.Lock()

numpy.seterr(all='ignore')

log = BaseLog(
            log_level=Config.LOG_LEVEL,
            log_path=Config.LOG_DIR,
            max_log_cnt=Config.MAX_LOG_CNT,
            max_log_size=Config.MAX_LOG_SIZE
)

if not os.path.exists(Config.LOG_DIR):  os.makedirs(Config.LOG_DIR)

conn = sqlite3.connect('local.db',  check_same_thread=False)
cursor = conn.cursor()


# Если не существует таблиц sqlite3, их нужно создать (первый запуск)
orders_q = """
  create table if not exists
    orders (
      order_id TEXT,
      order_type TEXT,
      order_pair TEXT,
      order_created DATETIME,
      order_filled DATETIME,
      order_cancelled DATETIME,
      from_order_id TEXT,
      order_price REAL,
      order_amount REAL,
      order_spent REAL
    );
"""
cursor.execute(orders_q)


# все обращения к API проходят через эту функцию
def call_api(**kwargs):
    market_log = log.get_logger(kwargs.get('market', ' --- '))
    market_log = logging.LoggerAdapter(market_log, extra={'log_name': kwargs.get('market', ' --- ')})

    http_method = kwargs.get('http_method') if kwargs.get('http_method', '') else 'GET'
    method = kwargs.get('method')

    nonce = str(int(round(time.time())))
    payload = {
        'nonce': nonce
    }

    if kwargs:
        payload.update(kwargs)

    uri = "https://" + Config.API_URL + "/api/" + Config.API_VERSION + method + '?apikey=' + Config.API_KEY + '&nonce=' + nonce
    uri += urllib.parse.urlencode(payload)

    payload = urllib.parse.urlencode(payload)

    apisign = hmac.new(Config.API_SECRET,
                       uri.encode(),
                       hashlib.sha512).hexdigest()

    headers = {"Content-type": "application/x-www-form-urlencoded",
               "Key": Config.API_KEY,
               "apisign": apisign}

    market_log.debug("API requested: " + str(kwargs))
    market_log.debug("URL: " + str(uri))

    res = requests.request(
        method=http_method,
        url=uri,
        params=payload if http_method == 'POST' else [],
        headers=headers,
        verify=Config.SECURE
    ).json()

    market_log.debug("API returned: " + str(res))

    return res

# Получаем с биржи данные, необходимые для построения индикаторов
def get_ticks(market, period):
    chart_data = {}
    # Получаем готовые данные свечей
    res = requests.get("https://bittrex.com/Api/v2.0/pub/market/GetTicks?marketName=" + market + "&tickInterval="+period, verify=Config.SECURE).json()
    if not res['success']:
        market_log = log.get_logger(market)
        market_log = logging.LoggerAdapter(market_log, extra={'log_name': market})
        market_log.warning(str(res))
        if res['message'] == 'INVALID_MARKET':
            market_log.warning(
                """
                   *******************************************************
                   * НЕПРАВИЛЬНАЯ ПАРА {pair}                            *
                   *******************************************************
                """.format(
                    pair=market
                ))
        return []

    for item in res['result']:
        dt_obj = datetime.strptime(item['T'], '%Y-%m-%dT%H:%M:%S')
        ts = int(time.mktime(dt_obj.timetuple()))
        if not ts in chart_data:
            chart_data[ts] = {'open': float(item['O']), 'close': float(item['C']), 'high': float(item['H']), 'low': float(item['L'])}

    # Добираем недостающее
    res = requests.get("https://bittrex.com/api/v1.1/public/getmarkethistory?market=" + market, verify=Config.SECURE).json()

    for trade in reversed(res['result']):
        try:
            dt_obj = datetime.strptime(trade['TimeStamp'], '%Y-%m-%dT%H:%M:%S.%f')
        except ValueError:
            dt_obj = datetime.strptime(trade['TimeStamp'], '%Y-%m-%dT%H:%M:%S')
        ts = int((time.mktime(dt_obj.timetuple())/1800))*1800 # округляем до 30 минут
        if not ts in chart_data:
            chart_data[ts] = {'open': 0, 'close': 0, 'high': 0,'low': 0}

        chart_data[ts]['close'] = float(trade['Price'])

        if not chart_data[ts]['open']:
            chart_data[ts]['open'] = float(trade['Price'])

        if not chart_data[ts]['high'] or chart_data[ts]['high'] < float(trade['Price']):
            chart_data[ts]['high'] = float(trade['Price'])

        if not chart_data[ts]['low'] or chart_data[ts]['low'] > float(trade['Price']):
            chart_data[ts]['low'] = float(trade['Price'])

    return chart_data

# С помощью MACD делаем вывод о целесообразности торговли в данный момент (https://bablofil.ru/macd-python-stock-bot/)
def get_macd_advice(chart_data):
    if not chart_data:
        return ({'trand': 'UNKNOWN', 'growing': False})
    macd, macdsignal, macdhist = talib.MACD(numpy.asarray([chart_data[item]['close'] for item in sorted(chart_data)]),
                                            fastperiod=Config.MACD_FASTPERIOD,
                                            slowperiod=Config.MACD_SLOWPERIOD,
                                            signalperiod=Config.MACD_SIGNALPERIOD
                                            )
    try:
        numpy.seterr(all='ignore')
        idx = numpy.argwhere(numpy.diff(numpy.sign(macd - macdsignal)) != 0).reshape(-1) + 0
    except RuntimeWarning:
        idx = []
        pass
    trand = 'BULL' if macd[-1] > macdsignal[-1] else 'BEAR'

    max_v = 0

    activity_time = False
    growing = False

    for offset, elem in enumerate(macdhist):

        growing = False

        curr_v = macd[offset] - macdsignal[offset]
        if abs(curr_v) > abs(max_v):
            max_v = curr_v
        perc = curr_v / max_v

        if ((macd[offset] > macdsignal[offset] and perc * 100 > Config.BULL_PERC)  # восходящий тренд
            or (
                macd[offset] < macdsignal[offset] and perc * 100 < (100 - Config.BEAR_PERC)
            )
            ):
            activity_time = True

            growing = True

        if offset in idx and not numpy.isnan(elem):
            # тренд изменился
            max_v = curr_v = 0  # обнуляем пик спреда между линиями

    return ({'trand':trand, 'growing':growing})


# Ф-ция для создания ордера на покупку
def create_buy(market):
    market_log = log.get_logger(market)
    market_log = logging.LoggerAdapter(market_log, extra={'log_name': market})

    market_log.debug('Создаем ордер на покупку')
    market_log.debug('Получаем текущие курсы')

    # Получаем публичные данные тикера
    ticker_data = call_api(method="/public/getticker", market=market)
    # Берем цену, по которой кто-то продает - стоимость комиссии заложим в цену продажи
    current_rate = float(ticker_data['result']['Ask'])
    can_buy = Config.CAN_SPEND / current_rate
    pair = market.split('-')

    market_log.info("""
        Текущая цена - %0.8f
        На сумму %0.8f %s можно купить %0.8f %s
        Создаю ордер на покупку
        """ % (current_rate, Config.CAN_SPEND, pair[0], can_buy, pair[1])
        )

    order_res = call_api(method="/market/buylimit",
                         market=market,
                         quantity=can_buy,
                         rate=current_rate if pair[0] != 'USD' else "{r:0.4f}".format(r=int((current_rate*10000)/5)/10000*5)
    )
    if order_res['success']:
        try:
            lock.acquire()
            cursor.execute(
                """
                  INSERT INTO orders(
                      order_id,
                      order_type,
                      order_pair,
                      order_created,
                      order_price,
                      order_amount,
                      order_spent
                  ) Values (
                    :order_id,
                    'buy',
                    :order_pair,
                    datetime(),
                    :order_price,
                    :order_amount,
                    :order_spent
                  )
                """, {
                    'order_id': order_res['result']['uuid'],
                    'order_pair': market,
                    'order_price': current_rate,
                    'order_amount': can_buy,
                    'order_spent': Config.CAN_SPEND

                })
            conn.commit()
        finally:
            lock.release()

        market_log.info("Создан ордер на покупку %s" % order_res['result']['uuid'])
    else:
        market_log.warning("""
            Не удалось создать ордер: %s
        """ % order_res['message'])

# Ф-ция для создания ордера на продажу
def create_sell(from_order, market):
    market_log = log.get_logger(market)
    market_log = logging.LoggerAdapter(market_log, extra={'log_name': market})

    pair = market.split('-')

    try:
        lock.acquire()
        buy_order_q = """
            SELECT order_spent, order_amount FROM orders WHERE order_id='%s'
        """ % from_order
        cursor.execute(buy_order_q)
        order_spent, order_amount = cursor.fetchone()
        new_rate = (order_spent + order_spent * Config.MARKUP) / order_amount

        new_rate_fee = new_rate + (new_rate * Config.STOCK_FEE) / (1 - Config.STOCK_FEE)

        ticker_data = call_api(method="/public/getticker", market=market)
        # Берем цену, по которой кто-то покупает
        current_rate = float(ticker_data['result']['Bid'])

        choosen_rate = current_rate if current_rate > new_rate_fee else new_rate_fee

        market_log.info("""
            Итого на этот ордер было потрачено %0.8f %s, получено %0.8f %s
            Что бы выйти в плюс, необходимо продать купленную валюту по курсу %0.8f
            Тогда, после вычета комиссии %0.4f останется сумма %0.8f %s
            Итоговая прибыль составит %0.8f %s
            Текущий курс продажи %0.8f
            Создаю ордер на продажу по курсу %0.8f
        """
            % (
                order_spent, pair[0], order_amount, pair[1],
                new_rate_fee,
                Config.STOCK_FEE, (new_rate_fee * order_amount - new_rate_fee * order_amount * Config.STOCK_FEE), pair[0],
                (new_rate_fee * order_amount - new_rate_fee * order_amount * Config.STOCK_FEE) - order_spent, pair[0],
                current_rate,
                choosen_rate,
            )
            )
        order_res = call_api(method="/market/selllimit", market=market,
                             quantity=order_amount,
                             rate=choosen_rate if pair[0] != 'USD' else "{r:0.4f}".format(r=int((choosen_rate*10000)/5)/10000*5)
                             )
        if order_res['success']:
            cursor.execute(
                """
                  INSERT INTO orders(
                      order_id,
                      order_type,
                      order_pair,
                      order_created,
                      order_price,
                      order_amount,
                      from_order_id
                  ) Values (
                    :order_id,
                    'sell',
                    :order_pair,
                    datetime(),
                    :order_price,
                    :order_amount,
                    :from_order_id
                  )
                """, {
                    'order_id': order_res['result']['uuid'],
                    'order_pair': market,
                    'order_price': choosen_rate,
                    'order_amount': order_amount,
                    'from_order_id': from_order

                })
            conn.commit()
            market_log.info("Создан ордер на продажу %s" % order_res['result']['uuid'])

    finally:
        lock.release()