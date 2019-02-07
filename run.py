import threading
from config import Config
from main import process_market

if __name__ == '__main__':
    threads = []
    for market in Config.MARKETS:
        threads.append(threading.Thread(target=process_market, args=(market,)))

    for thread in threads:
        thread.start()

    for thread in threads:
        thread.join()

