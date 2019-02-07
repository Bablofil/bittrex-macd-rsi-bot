import logging
import logging.handlers

class BaseLog(object):

    def __init__(self, log_path, log_level=logging.DEBUG, max_log_size=10 * 1024*1024, max_log_cnt=10):
        self.log_level = log_level
        self.log_path = log_path
        self.max_log_size = max_log_size
        self.max_log_cnt = max_log_cnt

    def setup_logger(self, log_name):


        logger_name = log_name
        l = logging.getLogger(logger_name)
        formatter = logging.Formatter('%(asctime)s %(log_name)s: %(message)s<br/>')

        fileHandler = logging.handlers.RotatingFileHandler(
            self.log_path + logger_name + '.log',
            mode='a',
            encoding='utf-8',
            maxBytes=self.max_log_size,
            backupCount=self.max_log_cnt
        )

        fileHandler.setFormatter(formatter)
        streamHandler = logging.StreamHandler()
        streamHandler.setFormatter(formatter)

        l.setLevel(self.log_level)
        l.addHandler(fileHandler)
        l.addHandler(streamHandler)


    def get_logger(self, log_name, allowed=True):
        logger = logging.getLogger(log_name)
        if not logger.hasHandlers() and allowed:
            self.setup_logger(log_name)
            logger = logging.getLogger(log_name)
        return logger
