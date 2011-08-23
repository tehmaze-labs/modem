import datetime
import glob
import os
import select
import shutil
import subprocess
import sys
import StringIO
import tempfile
from modem import *

def run(modem='xmodem'):

    if modem.lower().startswith('xmodem'):
        pipe   = subprocess.Popen(['sz', '--xmodem', '--quiet', __file__],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        si, so = (pipe.stdin, pipe.stdout)

        stream = StringIO.StringIO()

    elif modem.lower() == 'ymodem':
        pipe   = subprocess.Popen(['sz', '--ymodem', '--quiet', __file__],
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        si, so = (pipe.stdin, pipe.stdout)

        stream = StringIO.StringIO()

    elif modem.lower() == 'zmodem':
        if len(sys.argv) > 2:
            files = sys.argv[2:]
        else:
            files = [__file__]
        #pipe   = subprocess.Popen(['zmtx', '-d', '-v'] + files,
        pipe   = subprocess.Popen(['sz', '--zmodem', '--try-8k'] + files,
                     stdin=subprocess.PIPE, stdout=subprocess.PIPE)
        si, so = (pipe.stdin, pipe.stdout)

        stream = StringIO.StringIO()

    def getc(size, timeout=3):
        w,t,f = select.select([so], [], [], timeout)
        if w:
            data = so.read(size)
        else:
            data = None

        #print datetime.datetime.now(), 'getc(', repr(data), ')'
        return data

    def putc(data, timeout=3):
        w,t,f = select.select([], [si], [], timeout)
        if t:
            si.write(data)
            si.flush()
            size = len(data)
        else:
            size = None

        #print datetime.datetime.now(), 'putc(', repr(data), repr(size), ')'
        return size

    if modem.lower().startswith('xmodem'):
        xmodem = globals()[modem.upper()](getc, putc)
        nbytes = xmodem.recv(stream, retry=8)
        print >> sys.stderr, 'received', nbytes, 'bytes'
        print >> sys.stderr, stream.getvalue()

    elif modem.lower() == 'ymodem':
        ymodem = globals()[modem.upper()](getc, putc)
        basedr = tempfile.mkdtemp()
        nfiles = ymodem.recv(basedr, retry=8)
        print >> sys.stderr, 'received', nfiles, 'files in', basedr
        print >> sys.stderr, subprocess.Popen(['ls', '-al', basedr],
            stdout=subprocess.PIPE).communicate()[0]
        shutil.rmtree(basedr)

    elif modem.lower() == 'zmodem':
        ymodem = globals()[modem.upper()](getc, putc)
        basedr = tempfile.mkdtemp()
        nfiles = ymodem.recv(basedr, retry=8)
        print >> sys.stderr, 'received', nfiles, 'files in', basedr
        print >> sys.stderr, subprocess.Popen(['ls', '-al', basedr],
            stdout=subprocess.PIPE).communicate()[0]
        print >> sys.stderr, subprocess.Popen(['md5'] + glob.glob(basedr+'/*'),
            stdout=subprocess.PIPE).communicate()[0]
        shutil.rmtree(basedr)


if __name__ == '__main__':
    if len(sys.argv) > 1:
        for modem in sys.argv[1:]:
            run(modem.upper())
    else:
        for modem in ['XMODEM', 'YMODEM']:
            run(modem)
