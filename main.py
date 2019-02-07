import logging
import talib
import numpy

import threading

from misc import *

curr_market = None

# Свой класс исключений
class ScriptError(Exception):
    pass

error_log = log.get_logger("error")

# Бесконечный цикл процесса - основная логика


def process_market(market):
    while True:
        try:
            market_log = log.get_logger(market)
            market_log = logging.LoggerAdapter(market_log, extra={'log_name': market})

            market_log.debug("Получаем все неисполненные ордера по БД")
            try:
                lock.acquire()
                orders_q = """
                                       SELECT
                                         o.order_id, 
                                         o.order_type, 
                                         o.order_price, 
                                         o.order_amount,
                                         o.order_filled,
                                         o.order_created
                                       FROM
                                         orders o
                                       WHERE
                                            o.order_pair='%s' 
                                            AND (    
                                                    (o.order_type = 'buy' and o.order_filled IS NULL)
                                                    OR 
                                                    (o.order_type = 'buy' AND order_filled IS NOT NULL AND NOT EXISTS (
                                                        SELECT 1 FROM orders o2 WHERE o2.from_order_id = o.order_id
                                                        )
                                                    )
                                                    OR (
                                                        o.order_type = 'sell' and o.order_filled IS NULL
                                                    )
                                                ) 
                                            AND o.order_cancelled IS NULL
                                   """ % market
            finally:
                lock.release()
            # Проходим по всем сохраненным ордерам в локальной базе
            orders_info = {}
            try:
                lock.acquire()
                for row in cursor.execute(orders_q):
                    orders_info[str(row[0])] = {'order_id': row[0], 'order_type': row[1], 'order_price': row[2],
                                                'order_amount': row[3], 'order_filled': row[4], 'order_created': row[5]
                                                }
            finally:
                lock.release()

            if orders_info:
                # Проверяем, были ли выполнены ранее созданные ордера, и помечаем в БД.
                market_log.debug("Получены неисполненные ордера из БД", orders_info)
                for order in orders_info:
                    if not orders_info[order]['order_filled']:
                        market_log.debug("Проверяем состояние ордера %s" % order)
                        order_info = call_api(method="/account/getorder", uuid=orders_info[order]['order_id'])['result']

                        if order_info['Closed'] and not order_info['CancelInitiated']:
                            market_log.debug('Ордер %s уже выполнен!' % order)
                            try:
                                lock.acquire()
                                cursor.execute(
                                    """
                                      UPDATE orders
                                      SET
                                        order_filled=datetime(),
                                        order_price=:order_price,
                                        order_amount=:order_amount,
                                        order_spent=order_spent + :fee
                                      WHERE
                                        order_id = :order_id
    
                                    """, {
                                        'order_id': order,
                                        'order_price': order_info['Price'],
                                        'order_amount': order_info['Quantity'],
                                        'fee': float(order_info["CommissionPaid"])
                                    }
                                )
                                conn.commit()
                            finally:
                                lock.release()
                            market_log.debug("Ордер %s помечен выполненным в БД" % order)
                            orders_info[order]['order_filled'] = datetime.now()
                        elif order_info['Closed'] and order_info['CancelInitiated']:
                            market_log.debug('Ордер %s отменен!' % order)

                            try:
                                lock.acquire()
                                cursor.execute(
                                    """
                                      UPDATE orders
                                      SET
                                        order_cancelled=datetime(),
                                        order_price=:order_price,
                                        order_amount=:order_amount,
                                        order_spent=order_spent + :fee
                                      WHERE
                                        order_id = :order_id
    
                                    """, {
                                        'order_id': order,
                                        'order_price': order_info['Price'],
                                        'order_amount': order_info['Quantity'],
                                        'fee': float(order_info["CommissionPaid"])
                                    }
                                )
                                conn.commit()
                            finally:
                                lock.release()

                            market_log.debug("Ордер %s помечен отмененным в БД" % order)
                            orders_info[order]['order_cancelled'] = datetime.now()

                        else:
                            market_log.debug("Ордер %s еще не выполнен" % order)
                            if order_info['QuantityRemaining'] != order_info['Quantity']:
                                orders_info[order]['partially_filled'] = True

                for order in orders_info:
                    if orders_info[order]['order_type'] == 'buy':
                        if orders_info[order]['order_filled']:  # если ордер на покупку был выполнен

                            if Config.USE_MACD_SELL or Config.USE_RSI_SELL:
                                sell_signal = 0

                                MACD_ALLOWS = 1
                                RSI_ALLOWS = 2

                                if Config.USE_MACD_SELL:
                                    macd_advice = get_macd_advice(
                                        chart_data=get_ticks(market, period=Config.MACD_TICK_INTERVAL))  # проверяем, можно ли создать sell
                                    if macd_advice['trand'] == 'BEAR' or (
                                            macd_advice['trand'] == 'BULL' and macd_advice['growing']):
                                        market_log.debug(
                                            'Для ордера %s не создаем ордер на продажу, т.к. ситуация на рынке неподходящая' % order)
                                    else:
                                        market_log.debug("MACD допускает выставление ордера на продажу")
                                        sell_signal = sell_signal | MACD_ALLOWS

                                if Config.USE_RSI_SELL and (
                                            (not Config.USE_MACD_SELL) or (
                                            Config.USE_MACD_SELL and sell_signal & MACD_ALLOWS == MACD_ALLOWS)
                                ):
                                    chart_data = get_ticks(market, period=Config.RSI_TICK_INTERVAL)
                                    rsi_perc = talib.RSI(
                                        numpy.asarray([chart_data[item]['close'] for item in sorted(chart_data)]),
                                        Config.RSI_TIMEPERIOD
                                    )[-1]
                                    if rsi_perc and (Config.RSI_SELL_MIN_PERC <= rsi_perc <= Config.RSI_SELL_MAX_PERC):
                                        market_log.debug('RSI допускает уход с рынка')
                                        sell_signal = sell_signal | RSI_ALLOWS
                                    else:
                                        market_log.debug(
                                            "Условия рынка RSI не подходят для ухода с рынка (rsi={r:0.4f})".format(
                                                r=rsi_perc))
                                else:
                                    market_log.debug(
                                        'Пропускаем проверку RSI, т.к. MACD не позволяет выставлять продажу')
                                if (
                                                ((not Config.USE_MACD_SELL) or (
                                                            Config.USE_MACD_SELL and sell_signal & MACD_ALLOWS == MACD_ALLOWS))
                                            and ((not Config.USE_RSI_SELL) or (
                                                        Config.USE_RSI_SELL and sell_signal & RSI_ALLOWS == RSI_ALLOWS))
                                    ):
                                    market_log.debug("Для выполненного ордера на покупку выставляем ордер на продажу")
                                    create_sell(from_order=orders_info[order]['order_id'], market=market)

                            else:  # создаем sell если тенденция рынка позволяет
                                market_log.debug("Для выполненного ордера на покупку выставляем ордер на продажу")
                                create_sell(from_order=orders_info[order]['order_id'], market=market)
                        else:  # Если buy не был исполнен, и прошло достаточно времени для отмены ордера, отменяем
                            if not orders_info[order]['partially_filled'] and not orders_info[order]['order_cancelled']:
                                time_passed = time.time() - int(orders_info[order]['order_created'])
                                if time_passed > Config.ORDER_LIFE_TIME * 60:
                                    market_log.debug('Пора отменять ордер %s' % order)
                                    cancel_res = call_api(method="/market/cancel", uuid=order)
                                    if cancel_res['success']:
                                        try:
                                            lock.acquire()
                                            cursor.execute(
                                                """
                                                  UPDATE orders
                                                  SET
                                                    order_cancelled=datetime()
                                                  WHERE
                                                    order_id = :order_id
    
                                                """, {
                                                    'order_id': order
                                                }
                                            )
                                            conn.commit()
                                        finally:
                                            lock.release()
                                        market_log.debug("Ордер %s помечен отмененным в БД" % order)
                    else:  # ордер на продажу
                        pass
            else:
                market_log.debug("Неисполненных ордеров в БД нет, пора ли создать новый?")
                # Проверяем MACD, если рынок в нужном состоянии, выставляем ордер на покупку
                if Config.USE_MACD_BUY or Config.USE_RSI:

                    buy_signal = 0

                    MACD_ALLOWS = 1
                    RSI_ALLOWS = 2

                    # Используются индикаторы
                    if Config.USE_MACD_BUY:
                        macd_advice = get_macd_advice(chart_data=get_ticks(market, period=Config.MACD_TICK_INTERVAL))
                        if macd_advice['trand'] == 'BEAR' and macd_advice['growing']:
                            buy_signal = buy_signal | MACD_ALLOWS
                            market_log.debug('MACD позволяет войти на рынок')
                        else:
                            market_log.debug("Условия рынка MACD не подходят для торговли", macd_advice)
                    if Config.USE_RSI_BUY and (
                            (not Config.USE_MACD_BUY) or (Config.USE_MACD_BUY and buy_signal & MACD_ALLOWS == MACD_ALLOWS)
                    ):
                        chart_data = get_ticks(market, period=Config.RSI_TICK_INTERVAL)
                        rsi_perc = talib.RSI(
                            numpy.asarray([chart_data[item]['close'] for item in sorted(chart_data)]),
                            Config.RSI_TIMEPERIOD
                        )[-1]
                        if rsi_perc and (Config.RSI_BUY_MIN_PERC <= rsi_perc <= Config.RSI_BUY_MAX_PERC):
                            market_log.debug('RSI позволяет войти на рынок')
                            buy_signal = buy_signal | RSI_ALLOWS
                        else:
                            market_log.debug("Условия рынка RSI не подходят для торговли (rsi={r:0.4f})".format(r=rsi_perc))
                    else:
                        market_log.debug('Пропускаем проверку RSI, т.к. MACD не позволяет выставлять покупку')

                    if (
                            ((not Config.USE_MACD_BUY) or (
                                Config.USE_MACD_BUY and buy_signal & MACD_ALLOWS == MACD_ALLOWS))
                            and ((not Config.USE_RSI_BUY) or (
                                Config.USE_RSI_BUY and buy_signal & RSI_ALLOWS == RSI_ALLOWS))
                    ):
                        market_log.debug("Создаем ордер на покупку")
                        create_buy(market=market)
                else:
                    market_log.debug("Создаем ордер на покупку")
                    create_buy(market=market)

        except:
            market_log.exception('Error!!!!')
            error_log.exception('Error!!!!')

        time.sleep(Config.MARKET_WAIT_TIME)
