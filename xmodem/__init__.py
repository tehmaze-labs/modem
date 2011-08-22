__author__    = 'Wijnand Modderman <maze@pyth0n.org>'
__copyright__ = [
                    'Copyright (c) 2010 Wijnand Modderman-Lenstra',
                    'Copyright (c) 1981 Chuck Forsberg'
                ]
__license__   = 'MIT'
__version__   = '0.2.4'

import gettext
from xmodem.protocol._xmodem import XMODEM
from xmodem.protocol._xmodem1k import XMODEM1K
from xmodem.protocol._xmodemcrc import XMODEMCRC
from xmodem.protocol._ymodem import YMODEM
from xmodem.protocol._zmodem import ZMODEM

gettext.install('xmodem')

# To satisfy import *
__all__ = [
    'XMODEM',
    'XMODEM1K',
    'XMODEMCRC',
    'YMODEM',
    'ZMODEM',
]

