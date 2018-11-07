import datetime
import os
import time
from modem.base import Modem
from modem import const
from modem.tools import log


class ZMODEM(Modem):
    '''
    ZMODEM protocol implementation, expects an object to read from and an
    object to write to.
    '''

    def recv(self, basedir, retry=16, timeout=60, delay=1):
        '''
        Receive some files via the ZMODEM protocol and place them under
        ``basedir``::

            >>> print modem.recv(basedir)
            3

        Returns the number of files received on success or ``None`` in case of
        failure.

        N.B.: currently there are no control on the existence of files, so they
        will be silently overwritten.
        '''
        # Loop until we established a connection, we expect to receive a
        # different packet than ZRQINIT
        kind = const.TIMEOUT
        while kind in [const.TIMEOUT, const.ZRQINIT]:
            self._send_zrinit(timeout)
            kind = self._recv_header(timeout)[0]

        log.info('ZMODEM connection established')

        # Receive files
        while kind != const.ZFIN:
            if kind == const.ZFILE:
                self._recv_file(basedir, timeout, retry)
                kind = const.TIMEOUT
            elif kind == const.ZFIN:
                continue
            else:
                log.info('Did not get a file offer? Sending position header')
                self._send_pos_header(const.ZCOMPL, 0, timeout)
                kind = const.TIMEOUT

            while kind is const.TIMEOUT:
                self._send_zrinit(timeout)
                kind = self._recv_header(timeout)[0]

        # Acknowledge the ZFIN
        log.info('Received ZFIN, done receiving files')
        self._send_hex_header([const.ZFIN, 0, 0, 0, 0], timeout)

        # Wait for the over and out sequence
        while kind not in [ord('O'), const.TIMEOUT]:
            kind = self._recv(timeout)

        if kind is not const.TIMEOUT:
            while kind not in [ord('O'), const.TIMEOUT]:
                kind = self._recv(timeout)

    def _recv(self, timeout):
        # Outer loop
        while True:
            while True:
                char = self._recv_raw(timeout)
                if char is const.TIMEOUT:
                    return const.TIMEOUT

                if char == const.ZDLE:
                    break
                elif char in [0x11, 0x91, 0x13, 0x93]:
                    continue
                else:
                    # Regular character
                    return char

            # ZDLE encoded sequence or session abort
            char = self._recv_raw(timeout)
            if char is const.TIMEOUT:
                return const.TIMEOUT

            if char in [0x11, 0x91, 0x13, 0x93, const.ZDLE]:
                # Drop
                continue

            # Special cases
            if char in [const.ZCRCE, const.ZCRCG, const.ZCRCQ, const.ZCRCW]:
                return char | const.ZDLEESC
            elif char == const.ZRUB0:
                return 0x7f
            elif char == const.ZRUB1:
                return 0xff
            else:
                # Escape sequence
                if char & 0x60 == 0x40:
                    return char ^ 0x40
                break

    def _recv_raw(self, timeout):
        char = self.getc(1, timeout)
        if char == '':
            return const.TIMEOUT
        if char is not const.TIMEOUT:
            char = ord(char)
        return char

    def _recv_data(self, ack_file_pos, timeout):
        # zack_header = [const.ZACK, 0, 0, 0, 0]
        pos = ack_file_pos

        if self._recv_bits == 16:
            sub_frame_kind, data = self._recv_16_data(timeout)
        elif self._recv_bits == 32:
            sub_frame_kind, data = self._recv_32_data(timeout)
        else:
            raise TypeError('Invalid _recv_bits size')

        # Update file positions
        if sub_frame_kind is const.TIMEOUT:
            return const.TIMEOUT, None
        else:
            pos += len(data)

        # Frame continues non-stop
        if sub_frame_kind == const.ZCRCG:
            return const.FRAMEOK, data
        # Frame ends
        elif sub_frame_kind == const.ZCRCE:
            return const.ENDOFFRAME, data
        # Frame continues; ZACK expected
        elif sub_frame_kind == const.ZCRCQ:
            self._send_pos_header(const.ZACK, pos, timeout)
            return const.FRAMEOK, data
        # Frame ends; ZACK expected
        elif sub_frame_kind == const.ZCRCW:
            self._send_pos_header(const.ZACK, pos, timeout)
            return const.ENDOFFRAME, data
        else:
            return False, data

    def _recv_16_data(self, timeout):
        char = 0
        data = []
        mine = 0
        while char < 0x100:
            char = self._recv(timeout)
            if char is const.TIMEOUT:
                return const.TIMEOUT, ''
            elif char < 0x100:
                mine = self.calc_crc16(chr(char & 0xff), mine)
                data.append(chr(char))

        # Calculate our crc, unescape the sub_frame_kind
        sub_frame_kind = char ^ const.ZDLEESC
        mine = self.calc_crc16(chr(sub_frame_kind), mine)

        # Read their crc
        rcrc = self._recv(timeout) << 0x08
        rcrc |= self._recv(timeout)

        log.debug('My CRC = %08x, theirs = %08x' % (mine, rcrc))
        if mine != rcrc:
            log.error('Invalid CRC32')
            return timeout, ''
        else:
            return sub_frame_kind, ''.join(data)

    def _recv_32_data(self, timeout):
        char = 0
        data = []
        mine = 0
        while char < 0x100:
            char = self._recv(timeout)
            if char is const.TIMEOUT:
                return const.TIMEOUT, ''
            elif char < 0x100:
                mine = self.calc_crc32(chr(char & 0xff), mine)
                data.append(chr(char))

        # Calculate our crc, unescape the sub_frame_kind
        sub_frame_kind = char ^ const.ZDLEESC
        mine = self.calc_crc32(chr(sub_frame_kind), mine)

        # Read their crc
        rcrc = self._recv(timeout)
        rcrc |= self._recv(timeout) << 0x08
        rcrc |= self._recv(timeout) << 0x10
        rcrc |= self._recv(timeout) << 0x18

        log.debug('My CRC = %08x, theirs = %08x' % (mine, rcrc))
        if mine != rcrc:
            log.error('Invalid CRC32')
            return timeout, ''
        else:
            return sub_frame_kind, ''.join(data)

    def _recv_header(self, timeout, errors=10):
        header_length = 0
        error_count = 0
        char = None
        while header_length == 0:
            # Frist ZPAD
            while char != const.ZPAD:
                char = self._recv_raw(timeout)
                if char is const.TIMEOUT:
                    return const.TIMEOUT

            # Second ZPAD
            char = self._recv_raw(timeout)
            if char == const.ZPAD:
                # Get raw character
                char = self._recv_raw(timeout)
                if char is const.TIMEOUT:
                    return const.TIMEOUT

            # Spurious ZPAD check
            if char != const.ZDLE:
                continue

            # Read header style
            char = self._recv_raw(timeout)
            if char is const.TIMEOUT:
                return const.TIMEOUT

            if char == const.ZBIN:
                header_length, header = self._recv_bin16_header(timeout)
                self._recv_bits = 16
            elif char == const.ZHEX:
                header_length, header = self._recv_hex_header(timeout)
                self._recv_bits = 16
            elif char == const.ZBIN32:
                header_length, header = self._recv_bin32_header(timeout)
                self._recv_bits = 32
            else:
                error_count += 1
                if error_count > errors:
                    return const.TIMEOUT
                continue

        # We received a valid header
        # if header[0] == const.ZDATA:
        #     ack_file_pos = \
        #         header[const.ZP0] | \
        #         header[const.ZP1] << 0x08 | \
        #         header[const.ZP2] << 0x10 | \
        #         header[const.ZP3] << 0x20

        # elif header[0] == const.ZFILE:
        #     # ack_file_pos = 0
        #     pass

        return header

    def _recv_bin16_header(self, timeout):
        '''
        Recieve a header with 16 bit CRC.
        '''
        header = []
        mine = 0
        for x in range(0, 5):
            char = self._recv(timeout)
            if char is const.TIMEOUT:
                return 0, False
            else:
                mine = self.calc_crc16(chr(char), mine)
                header.append(char)

        rcrc = self._recv(timeout) << 0x08
        rcrc |= self._recv(timeout)

        if mine != rcrc:
            log.error('Invalid CRC16 in header')
            return 0, False
        else:
            return 5, header

    def _recv_bin32_header(self, timeout):
        '''
        Receive a header with 32 bit CRC.
        '''
        header = []
        mine = 0
        for x in range(0, 5):
            char = self._recv(timeout)
            if char is const.TIMEOUT:
                return 0, False
            else:
                mine = self.calc_crc32(chr(char), mine)
                header.append(char)

        # Read their crc
        rcrc = self._recv(timeout)
        rcrc |= self._recv(timeout) << 0x08
        rcrc |= self._recv(timeout) << 0x10
        rcrc |= self._recv(timeout) << 0x18

        log.debug('My CRC = %08x, theirs = %08x' % (mine, rcrc))
        if mine != rcrc:
            log.error('Invalid CRC32 in header')
            return 0, False
        else:
            return 5, header

    def _recv_hex_header(self, timeout):
        '''
        Receive a header with HEX encoding.
        '''
        header = []
        mine = 0
        for x in range(0, 5):
            char = self._recv_hex(timeout)
            if char is const.TIMEOUT:
                return const.TIMEOUT
            mine = self.calc_crc16(chr(char), mine)
            header.append(char)

        # Read their crc
        char = self._recv_hex(timeout)
        if char is const.TIMEOUT:
            return const.TIMEOUT
        rcrc = char << 0x08
        char = self._recv_hex(timeout)
        if char is const.TIMEOUT:
            return const.TIMEOUT
        rcrc |= char

        log.debug('My CRC = %04x, theirs = %04x' % (mine, rcrc))
        if mine != rcrc:
            log.error('Invalid CRC16 in receiving HEX header')
            return 0, False

        # Read to see if we receive a carriage return
        char = self.getc(1, timeout)
        if char == '\r':
            # Expect a second one (which we discard)
            self.getc(1, timeout)

        return 5, header

    def _recv_hex(self, timeout):
        n1 = self._recv_hex_nibble(timeout)
        if n1 is const.TIMEOUT:
            return const.TIMEOUT
        n0 = self._recv_hex_nibble(timeout)
        if n0 is const.TIMEOUT:
            return const.TIMEOUT
        return (n1 << 0x04) | n0

    def _recv_hex_nibble(self, timeout):
        char = self.getc(1, timeout)
        if char is const.TIMEOUT:
            return const.TIMEOUT

        if char > '9':
            if char < 'a' or char > 'f':
                # Illegal character
                return const.TIMEOUT
            return ord(char) - ord('a') + 10
        else:
            if char < '0':
                # Illegal character
                return const.TIMEOUT
            return ord(char) - ord('0')

    def _recv_file(self, basedir, timeout, retry):
        log.info('Abort to receive a file in %s' % (basedir,))
        pos = 0

        # Read the data subpacket containing the file information
        kind, data = self._recv_data(pos, timeout)
        pos += len(data)
        if kind not in [const.FRAMEOK, const.ENDOFFRAME]:
            if kind is not const.TIMEOUT:
                # File info metadata corrupted
                self._send_znak(pos, timeout)
            return False

        # We got the file name
        part = data.split('\x00')
        filename = part[0]
        filepath = os.path.join(basedir, os.path.basename(filename))
        fp = open(filepath, 'wb')
        part = part[1].split(' ')
        log.info('Meta %r' % (part,))
        size = int(part[0])
        # Date is octal (!?)
        date = datetime.datetime.fromtimestamp(int(part[1], 8))
        # We ignore mode and serial number, whatever, dude :-)

        log.info('Receiving file "%s" with size %d, mtime %s' %
                 (filename, size, date))

        # Receive contents
        start = time.time()
        kind = None
        total_size = 0
        while total_size < size:
            kind, chunk_size = self._recv_file_data(fp.tell(), fp, timeout)
            total_size += chunk_size
            if kind == const.ZEOF:
                break

        # End of file
        speed = (total_size / (time.time() - start))
        log.info('Receiving file "%s" done at %.02f bps' % (filename, speed))

        # Update file metadata
        fp.close()
        mtime = time.mktime(date.timetuple())
        os.utime(filepath, (mtime, mtime))

    def _recv_file_data(self, pos, fp, timeout):
        self._send_pos_header(const.ZRPOS, pos, timeout)
        kind = 0
        dpos = -1
        while dpos != pos:
            while kind != const.ZDATA:
                if kind is const.TIMEOUT:
                    return const.TIMEOUT, ''
                else:
                    header = self._recv_header(timeout)
                    kind = header[0]

            # Read until we are at the correct block
            dpos = \
                header[const.ZP0] | \
                header[const.ZP1] << 0x08 | \
                header[const.ZP2] << 0x10 | \
                header[const.ZP3] << 0x18

        # TODO: stream to file handle directly
        kind = const.FRAMEOK
        size = 0
        while kind == const.FRAMEOK:
            kind, chunk = self._recv_data(pos, timeout)
            if kind in [const.ENDOFFRAME, const.FRAMEOK]:
                fp.write(chunk)
                size += len(chunk)

        return kind, size

    def _send(self, char, timeout, esc=True):
        if char == const.ZDLE:
            self._send_esc(char, timeout)
        elif char in ['\x8d', '\x0d'] or not esc:
            self.putc(chr(char), timeout)
        elif char in ['\x10', '\x90', '\x11', '\x91', '\x13', '\x93']:
            self._send_esc(char, timeout)
        else:
            self.putc(chr(char), timeout)

    def _send_esc(self, char, timeout):
        self.putc(chr(const.ZDLE), timeout)
        self.putc(chr(char ^ 0x40), timeout)

    def _send_znak(self, pos, timeout):
        self._send_pos_header(const.ZNAK, pos, timeout)

    def _send_pos_header(self, kind, pos, timeout):
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
        self.putc(chr(const.ZPAD), timeout)
        self.putc(chr(const.ZPAD), timeout)
        self.putc(chr(const.ZDLE), timeout)
        self.putc(chr(const.ZHEX), timeout)
        mine = 0

        # Update CRC
        for char in header:
            mine = self.calc_crc16(chr(char), mine)
            self._send_hex(char, timeout)

        # Transmit the CRC
        self._send_hex(mine >> 0x08, timeout)
        self._send_hex(mine, timeout)

        self.putc('\r', timeout)
        self.putc('\n', timeout)
        self.putc(const.XON, timeout)

    def _send_zrinit(self, timeout):
        log.debug('Sending ZRINIT header')
        header = [const.ZRINIT, 0, 0, 0, 4 | const.ZF0_CANFDX |
                  const.ZF0_CANOVIO | const.ZF0_CANFC32]
        self._send_hex_header(header, timeout)
