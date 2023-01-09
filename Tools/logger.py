import logging


class CustomFormatter(logging.Formatter):
    grey = "\x1b[38;20m"
    green = "\x1b[32m"
    yellow = "\x1b[33;20m"
    red = "\x1b[31;20m"
    bold_red = "\x1b[31;1m"
    reset = "\x1b[0m"
    format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)"

    FORMATS = {
        logging.DEBUG: grey + format + reset,
        logging.INFO: green + format + reset,
        logging.WARNING: yellow + format + reset,
        logging.ERROR: red + format + reset,
        logging.CRITICAL: bold_red + format + reset
    }

    def format(self, record):
        log_fmt = self.FORMATS.get(record.levelno)
        formatter = logging.Formatter(log_fmt)
        return formatter.format(record)


class Logger:

    def __init__(self, name):
        logging.basicConfig(filename='../log.txt', format="%(asctime)s - %(name)s - %(levelname)s - %(message)s (%(filename)s:%(lineno)d)")

        logger = logging.getLogger(name)
        logger.setLevel(logging.DEBUG)

        logger_handler = logging.StreamHandler()
        logger_handler.setLevel(logging.DEBUG)

        logger_handler.setFormatter(CustomFormatter())

        logger.addHandler(logger_handler)
        self.logger = logger
        self.logger.info('Logging set up finnished')
