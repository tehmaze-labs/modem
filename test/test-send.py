import os
import select
import shutil
import subprocess
import sys
import StringIO
import tempfile
from xmodem import *

def run(modem='XMODEM'):
    print 'Testing', modem.upper(), 'modem'

    fn = None
    if modem.lower().startswith('xmodem'):
        fd, fn = tempfile.mkstemp()
        flag   = '--xmodem'
        print 'Calling rz %s %s' % (flag, fn)
        pipe   = subprocess.Popen(['rz', '--errors', '1200', '-p', flag, fn],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        si, so = (pipe.stdin, pipe.stdout)

    elif modem.lower() == 'ymodem':
        flag   = '--ymodem'
        print 'Calling rz %s' % (flag,)
        pipe   = subprocess.Popen(['rz', '--errors', '1200', '-p', flag],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        si, so = (pipe.stdin, pipe.stdout)

    def getc(size, timeout=3):
        w,t,f = select.select([so], [], [], timeout)
        if w:
            data = so.read(size)
        else:
            data = None

        print 'getc(', repr(data), ')'
        return data

    def putc(data, timeout=3):
        w,t,f = select.select([], [si], [], timeout)
        if t:
            si.write(data)
            si.flush()
            size = len(data)
        else:
            size = None

        print 'putc(', repr(data), repr(size), ')'
        return size

    if modem.lower().startswith('xmodem'):
        stream = open(__file__, 'rb')
        xmodem = globals()[modem.upper()](getc, putc)
        print 'Modem instance', xmodem
        status = xmodem.send(stream, retry=8)
        stream.close()

    elif modem.lower() == 'ymodem':
        fd, fn = tempfile.mkstemp()
        shutil.copy(__file__, fn)
        ymodem = YMODEM(getc, putc)
        print 'Modem instance', ymodem
        status = ymodem.send(fn, retry=8)

    print >> sys.stderr, 'sent', status
    print >> sys.stderr, file(fn).read()

    if fn: os.unlink(fn)

    return int(not status)

if __name__ == '__main__':
    if len(sys.argv) > 1:
        for modem in sys.argv[1:]:
            run(modem.upper())
    else:
        for modem in ['XMODEM', 'YMODEM']:
            run(modem)
