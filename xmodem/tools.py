import logging
from xmodem.const import CRC16_MAP, CRC32_MAP
from zlib import crc32 as _crc32


logging.basicConfig(format='%(asctime)s [%(levelname)s] %(message)s', 
    datefmt='%m/%d/%Y %I:%M:%S %p',
    level=logging.DEBUG)
log = logging.getLogger('XMODEM')


def crc16(data, crc=0):
    for char in data:
        crc = (crc << 8) ^ CRC16_MAP[((crc >> 0x08) ^ ord(char)) & 0xff]
    return crc & 0xffff

def crc32(data, crc=0):
    return _crc32(data, crc) & 0xffffffff
