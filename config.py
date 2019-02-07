import os
import logging

class Config(object):
    API_KEY = ''
    # обратите внимание, что добавлена 'b' перед строкой
    API_SECRET = b''

    # Список пар, на которые торгуем
    MARKETS = [
        'USD-BTC', 'USD-XRP', 'USD-ETH',
        'USD-LTC', 'USD-BCH', 'USD-ZEC', 'USD-TRX',
        'USD-ETC', 'USD-ADA', 'USD-SC',  'USD-TUSD',

        'USDT-BTC', 'USDT-XRP', 'USDT-ETH', 'USDT-XMR',
        'USDT-TRX', 'USDT-BCH', 'USDT-LTC', 'USDT-NEO',
        'USDT-ADA', 'USDT-ZEC', 'USDT-DCR', 'USDT-ZRX',
        'USDT-DOGE',  'USDT-ETC', 'USDT-XVG', 'USDT-RVN',
        'USDT-OMG', 'USDT-DASH',  'USDT-DGB', 'USDT-BAT',
        'USDT-SC', 'USDT-NXT', 'USDT-TUSD', 'USDT-PAX',


    ]

    CAN_SPEND = 4  # Сколько USDT|BTC и т.п. готовы вложить в бай
    MARKUP = 0.001  # 0.001 = 0.1% - Какой навар со сделки хотим получать

    STOCK_FEE = 0.0025  # Какую комиссию берет биржа

    ORDER_LIFE_TIME = 0.5  # Через сколько минут отменять неисполненный ордер на покупку 0.5 = 30 сек.

    MARKET_WAIT_TIME = 1  # Сколько секунд перерыва в каждой паре на каждой итерации

    ##################
    #  MACD SETTINGS
    ##################
    USE_MACD_BUY = True  # True - оценивать вход на рынок по MACD, False - входить без анализа MACD
    USE_MACD_SELL = False  # True - оценивать выход с рынка по MACD, False - продавать без анализа

    MACD_FASTPERIOD = 12
    MACD_SLOWPERIOD = 26
    MACD_SIGNALPERIOD = 9

    MACD_TICK_INTERVAL = 'fiveMin'  # Какие свечи брать для MACD, допускается ['oneMin', 'fiveMin', 'thirtyMin', 'hour', 'day']

    BEAR_PERC = 70  # % что считаем поворотом при медведе (подробности - https://bablofil.ru/macd-python-stock-bot/
    BULL_PERC = 98  # % что считаем поворотом при быке

    #################
    # RSI SETTINGS
    #################
    USE_RSI_BUY = True # True - оценивать вход на рынок по RSI, False - входить без анализа RSI
    USE_RSI_SELL = False # True - оценивать вход на рынок по RSI, False - входить без анализа RSI
    RSI_TICK_INTERVAL = 'fiveMin'  # Какие свечи брать для RSI, допускается ['oneMin', 'fiveMin', 'thirtyMin', 'hour', 'day']
    RSI_TIMEPERIOD = 14

    RSI_BUY_MIN_PERC = 0
    RSI_BUY_MAX_PERC = 45 # Если rsi внутри диапазона, можно покупать


    RSI_SELL_MIN_PERC = 60
    RSI_SELL_MAX_PERC = 100 # Если rsi внутри диапазона, можно продавать

    API_URL = 'bittrex.com'
    API_VERSION = 'v1.1'

    SECURE = True

    # Настройки логирования
    LOG_LEVEL = logging.DEBUG
    CURR_DIR = os.path.dirname(os.path.abspath(__file__))

    LOG_DIR = CURR_DIR + '/logs/'
    MAX_LOG_SIZE = 5 * 1024 * 1024  # Максимальный размер каждого лога 0 - не архивировать
    MAX_LOG_CNT = 20  # Максимальное кол-во архивных логов в каждой группе. 0 - не архивировать