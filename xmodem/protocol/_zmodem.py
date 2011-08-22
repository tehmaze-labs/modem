from xmodem.base import MODEM
from xmodem.const import *

NORMAL     = '\x1b[0m'
RED        = '\x1b[1;31m'
GREEN      = '\x1b[1;32m'
BLUE       = '\x1b[1;34m'

def global_str(value):
    if value is None:
        return 'TIMEOUT'
    for item in [item for item in globals() if item.startswith('Z')]:
        if globals()[item] == value:
            return item

class ZMODEM(MODEM):
    def recv(self, basedir, timeout=5, retry=10):
        # Loop until we established a connection, we expect to receive a
        # different packet than ZRQINIT
        kind = TIMEOUT
        while kind in [TIMEOUT, ZRQINIT]:
            self._send_zrinit(timeout)
            kind = self._recv_header(timeout)[0]
            print 'Received a', global_str(kind), repr(kind), 'header'

        print 'Connection established'

        # Receive files
        while kind != ZFIN:
            if kind == ZFILE:
                self._recv_file(basedir, timeout, retry)
                kind = TIMEOUT
            elif kind == ZFIN:
                continue
            else:
                self._send_pos_header(ZCOMPL, 0, timeout)
                kind = TIMEOUT

            while kind is TIMEOUT:
                self._send_zrinit(timeout)
                kind = self._recv_header(timeout)[0]
                print 'Received a', global_str(kind), 'header'

        print 'Received ZFIN'
        # Wait for the over and out sequence
        while kind not in [ord('O'), TIMEOUT]:
            kind = self._recv(timeout)

        if kind is not TIMEOUT:
            while kind not in [ord('O'), TIMEOUT]:
                kind = self._recv(timeout)

    def _recv(self, timeout):
        # Outer loop
        while True:
            while True:
                char = self._recv_raw(timeout)
                if char is TIMEOUT:
                    return TIMEOUT

                print 'recv 0x%02x' % (char,)
                if char == ZDLE:
                    break
                elif char in [0x11, 0x91, 0x13, 0x93]:
                    continue
                else:
                    # Regular character
                    return char

            print 'got ZDLE escape', global_str(char),
            # ZDLE encoded sequence or session abort
            char = self._recv_raw(timeout)
            if char is TIMEOUT:
                return TIMEOUT

            print 'next', char, '=', global_str(char)
            if char in [0x11, 0x91, 0x13, 0x93, ZDLE]:
                # Drop
                continue

            # Special cases
            if char in [ZCRCE, ZCRCG, ZCRCQ, ZCRCW]:
                print 'special case', global_str(char)
                return char | ZDLEESC
            elif char == ZRUB0:
                return 0x7f
            elif char == ZRUB1:
                return 0xff
            else:
                # Escape sequence
                if char & 0x60 == 0x40:
                    return char ^ 0x40
                break

    def _recv_raw(self, timeout):
        char = self.getc(1, timeout)
        if char is not TIMEOUT:
            char = ord(char)
        return char

    def _recv_data(self, ack_file_pos, timeout):
        zack_header = ''.join([ZACK, '\x00', '\x00', '\x00', '\x00'])
        pos = ack_file_pos

        if self._recv_bits == 16:
            sub_frame_kind, data = self._recv_16_data(timeout)
        elif self._recv_bits == 32:
            sub_frame_kind, data = self._recv_32_data(timeout)
        else:
            raise TypeError('Invalid _recv_bits size')

        print 'Recieved sub frame kind in _recv_data', global_str(sub_frame_kind)

        # Update file positions
        if sub_frame_kind is TIMEOUT:
            return TIMEOUT, None
        else:
            pos += len(data)

        # Frame continues non-stop
        if sub_frame_kind == ZCRCG:
            return FRAMEOK, data
        # Frame ends
        elif sub_frame_kind == ZCRCE:
            return ENDOFFRAME, data
        # Frame continues; ZACK expected
        elif sub_frame_kind == ZCRCQ:
            self._send_pos_header(ZACK, pos, timeout)
            return FRAMEOK, data
        # Frame ends; ZACK expected
        elif sub_frame_kind == ZCRCW:
            self._send_pos_header(ZACK, pos, timeout)
            return ENDOFFRAME, data
        else:
            return False, data

    def _recv_16_data(self, timeout):
        pass

    def _recv_32_data(self, timeout):
        char = 0
        data = []
        mine = 0
        while char < 0x100:
            char = self._recv(timeout)
            print 'recv char %04x %s' % (char, global_str(char))
            if char is TIMEOUT:
                return TIMEOUT, ''
            elif char < 0x100:
                mine = self.calc_crc32(chr(char & 0xff), mine)
                data.append(chr(char))

        # Calculate our crc, unescape the sub_frame_kind
        sub_frame_kind = char ^ ZDLEESC
        mine = self.calc_crc32(chr(sub_frame_kind), mine)

        # Read their crc
        rcrc = self._recv(timeout)
        rcrc |= self._recv(timeout) << 0x08
        rcrc |= self._recv(timeout) << 0x10
        rcrc |= self._recv(timeout) << 0x18

        print 'My crc = %08x, theirs = %08x' % (mine, rcrc)
        if mine != rcrc:
            print 'Invalid crc 32'
            return TIMEOUT, ''

        return chr(sub_frame_kind), ''.join(data)

    def _recv_header(self, timeout, errors=10):
        header_length = 0
        error_count = 0
        char = None
        while header_length == 0:
            # Frist ZPAD
            while char != ZPAD:
                char = self._recv_raw(timeout)
                if char is TIMEOUT:
                    return TIMEOUT
            print 'Got first ZPAD'

            # Second ZPAD
            char = self._recv_raw(timeout)
            if char == ZPAD:
                print 'Got second ZPAD'
                # Get raw character
                char = self._recv_raw(timeout)
                if char is TIMEOUT:
                    return TIMEOUT
            else:
                print 'Got no second ZPAD'
                continue

            # Spurious ZPAD check
            if char != ZDLE:
                print 'Did not get ZDLE %02x, but %s' % (char, global_str(char))
                continue
            print 'Got ZDLE'

            # Read header style
            char = self._recv_raw(timeout)
            if char is TIMEOUT:
                return TIMEOUT

            styles = {ZBIN: 'ZBIN', ZHEX: 'ZHEX', ZBIN32: 'ZBIN32'}
            print 'Got header style %s: %02x' % (styles.get(char, None), char)

            if char == ZBIN:
                header_length, header = self._recv_bin16_header(timeout)
                self._recv_bits = 16
            elif char == ZHEX:
                header_length, header = self._recv_hex_header(timeout)
                self._recv_bits = 16
            elif char == ZBIN32:
                header_length, header = self._recv_bin32_header(timeout)
                self._recv_bits = 32
            else:
                print 'Unknown header style?'
                error_count += 1
                if error_count > errors:
                    return TIMEOUT
                continue

        print 'Got header', header

        # We received a valid header
        if header[0] == ZDATA:
            ack_file_pos = \
                (ord(header[ZP0])) | \
                (ord(header[ZP1]) << 0x08) | \
                (ord(header[ZP2]) << 0x10) | \
                (ord(header[ZP3]) << 0x20)

        elif header[0] == ZFILE:
            ack_file_pos = 0

        return header

    def _recv_bin16_header(self, timeout):
        '''
        Recieve a header with 16 bit CRC.
        '''
        print '_recv_bin16_header'
        header = []
        mine = 0
        for x in xrange(0, 5):
            char = self._recv(timeout)
            if char is TIMEOUT:
                return 0, False
            else:
                mine = self.calc_crc16(chr(char), mine)
                header.append(char)

        mine = self.calc_crc16(0, mine)
        mine = self.calc_crc16(0, mine)
        rcrc = ord(self.getc(1, timeout)) << 8
        rcrc |= ord(self.getc(1, timeout))

        if mine != rcrc:
            print 'Invalid crc 16'
            return 0, False

        return 5, header

    def _recv_bin32_header(self, timeout):
        '''
        Receive a header with 32 bit CRC.
        '''
        print '_recv_bin32_header'
        header = []
        mine = 0
        for x in xrange(0, 5):
            char = self._recv(timeout)
            if char is TIMEOUT:
                return 0, False
            else:
                mine = self.calc_crc32(chr(char), mine)
                header.append(char)

        # Read their crc
        rcrc  = self._recv(timeout)
        rcrc |= self._recv(timeout) << 0x08
        rcrc |= self._recv(timeout) << 0x10
        rcrc |= self._recv(timeout) << 0x18

        print 'My crc = %08x, theirs = %08x' % (mine, rcrc)

        if mine != rcrc:
            print 'Invalid crc 32'
            return 0, False

        return 5, header

    def _recv_hex_header(self, timeout):
        '''
        Receive a header with HEX encoding.
        '''
        header = []
        mine = 0
        for x in xrange(0, 5):
            char = self._recv_hex(timeout)
            print 'recv_hex gave me', char
            if char is TIMEOUT:
                return TIMEOUT
            char = chr(char)
            mine = self.calc_crc16(char, mine)
            header.append(char)

        # Read their crc
        char = self._recv_hex(timeout)
        if char is TIMEOUT:
            return TIMEOUT
        rcrc = char << 0x08
        char = self._recv_hex(timeout)
        if char is TIMEOUT:
            return TIMEOUT
        rcrc |= char

        print 'My crc = %04x, theirs = %04x' % (mine, rcrc)

        if mine != rcrc:
            print 'Invalid crc 16'
            return 0, False

        # Read to see if we receive a carriage return
        char = self.getc(1, timeout)
        if char == '\r':
            # Expect a second one (which we discard)
            self.getc(1, timeout)

        return 5, header

    def _recv_hex(self, timeout):
        n1 = self._recv_hex_nibble(timeout)
        if n1 is TIMEOUT:
            return TIMEOUT
        n0 = self._recv_hex_nibble(timeout)
        if n0 is TIMEOUT:
            return TIMEOUT
        return (n1 << 0x04) | n0

    def _recv_hex_nibble(self, timeout):
        char = self.getc(1, timeout)
        if char is TIMEOUT:
            return TIMEOUT

        if char > '9':
            if char < 'a' or char > 'f':
                # Illegal character
                return TIMEOUT
            return ord(char) - ord('a') + 10
        else:
            if char < '0':
                # Illegal character
                return TIMEOUT
            return ord(char) - ord('0')

    def _recv_file(self, basedir, timeout, retry):
        print 'Receiving a file in', basedir
        pos = 0

        # Read the data subpacket containing the file information
        kind, data = self._recv_data(pos, timeout)
        pos += len(data)
        print 'Recieved a', global_str(kind), 'sub frame'
        if kind not in [FRAMEOK, ENDOFFRAME]:
            if not kind is TIMEOUT:
                # File info metadata corrupted
                self._send_znak(pos, timeout)
            return False

        # We got the file name
        part = data.split('\x00')
        filename = part[0]
        part = part[1].split(' ')
        size = int(part[0])
        date = int(part[1])
        print RED, 'Receving file %s with size %d' % (filename, size), NORMAL

        # Transfer the file
        #self._send_pos_header(ZSKIP, 0, timeout)
        # Receive contents
        kind = None
        data = ''
        while len(data) != size:
            kind, chunk = self._recv_file_data(len(data), filename, timeout)
            data += chunk
            if kind == ZEOF:
                break

        # End of file
        print RED, 'Done receiving file', NORMAL
        print data

    def _recv_file_data(self, pos, filename, timeout):
        self._send_pos_header(ZRPOS, pos, timeout)
        kind = 0
        dpos = -1
        while dpos != pos:
            while kind != ZDATA:
                if kind is TIMEOUT:
                    return TIMEOUT, ''
                else:
                    header = self._recv_header(timeout)
                    kind = header[0]
                    print BLUE, global_str(kind), NORMAL

            # Read until we are at the correct block
            dpos = ord(header[ZP0]) | \
                ord(header[ZP1]) << 0x08 | \
                ord(header[ZP2]) << 0x10 | \
                ord(header[ZP3]) << 0x18
            print 'dpos %d, pos %d' % (dpos, pos)

        # TODO: stream to file handle directly
        kind = FRAMEOK
        data = []
        while kind == FRAMEOK:
            kind, chunk = self._recv_data(pos, timeout)
            if kind in [ENDOFFRAME, FRAMEOK]:
                data.append(chunk)

        return kind, ''.join(data)

    def _send(self, char, timeout, esc=True):
        if char == ZDLE:
            self._send_esc(char, timeout)
        elif char in ['\x8d', '\x0d'] or not esc:
            self.putc(chr(char), timeout)
        elif char in ['\x10', '\x90', '\x11', '\x91', '\x13', '\x93']:
            self._send_esc(char, timeout)
        else:
            self.putc(chr(char), timeout)

    def _send_esc(self, char, timeout):
        self.putc(chr(ZDLE), timeout)
        self.putc(chr(char ^ 0x40), timeout)

    def _send_znak(self, pos, timeout):
        self._send_pos_header(ZNAK, pos, timeout)

    def _send_pos_header(self, kind, pos, timeout):
        print GREEN, 'Send pos header', global_str(kind), 'for', pos, NORMAL
        header = []
        header.append(kind)
        header.append(pos & 0xff)
        header.append((pos >> 0x08) & 0xff)
        header.append((pos >> 0x10) & 0xff)
        header.append((pos >> 0x20) & 0xff)
        self._send_hex_header(header, timeout)

    def _send_hex(self, char, timeout):
        char = char & 0xff
        self._send_hex_nibble(char >> 0x04, timeout)
        self._send_hex_nibble(char >> 0x00, timeout)

    def _send_hex_nibble(self, nibble, timeout):
        nibble &= 0x0f
        self.putc('%x' % nibble, timeout)

    def _send_hex_header(self, header, timeout):
        self.putc(chr(ZPAD), timeout)
        self.putc(chr(ZPAD), timeout)
        self.putc(chr(ZDLE), timeout)
        self.putc(chr(ZHEX), timeout)
        mine = 0

        print 'send_hex_header', repr(header)

        # Update CRC
        for char in header:
            mine = self.calc_crc16(chr(char), mine)
            self._send_hex(char, timeout)

        # Transmit the CRC
        self._send_hex(mine >> 0x08, timeout)
        self._send_hex(mine, timeout)

        self.putc('\r', timeout)
        self.putc('\n', timeout)
        self.putc(XON, timeout)

    def _send_zrinit(self, timeout):
        header = [ZRINIT, 0, 0, 0, 4 | ZF0_CANFDX | ZF0_CANOVIO | ZF0_CANFC32]
        print 'zrqinit', header
        self._send_hex_header(header, timeout)
