import logging

logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', 
    datefmt='%m/%d/%Y %I:%M:%S %p',
    level=logging.DEBUG)
log = logging.getLogger('XMODEM')
