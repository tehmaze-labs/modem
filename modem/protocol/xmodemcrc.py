import time

from modem import error
from modem import const
from modem.tools import log
from modem.protocol.xmodem import XMODEM


class XMODEMCRC(XMODEM):
    '''
    XMODEMCRC protocol implementation, expects an object to read from and an
    object to write to.
    '''

    # Protocol identifier
    protocol = const.PROTOCOL_XMODEMCRC

    def send(self, stream, retry=16, timeout=60):
        '''
        Send a stream via the XMODEMCRC protocol.

            >>> stream = file('/etc/issue', 'rb')
            >>> print modem.send(stream)
            True

        Returns ``True`` upon succesful transmission or ``False`` in case of
        failure.
        '''

        # initialize protocol
        error_count = 0
        crc_mode = 0
        cancel = 0
        while True:
            byte = self.getc(1)
            if byte:
                if byte == const.NAK:
                    crc_mode = 0
                    break
                elif byte == const.CRC:
                    crc_mode = 1
                    break
                elif byte == const.CAN:
                    if cancel:
                        log.error(error.ABORT_RECV_CAN_CAN)
                        return False
                    else:
                        log.debug(error.DEBUG_RECV_CAN)
                        cancel = 1
                else:
                    log.error(error.ABORT_EXPECT_NAK_CRC % byte.hex())

            error_count += 1
            if error_count >= retry:
                self.abort(timeout=timeout)
                return False

        if not self._send_stream(stream, crc_mode, retry, timeout):
            log.error(error.ABORT_SEND_STREAM)
            return False
        return True

    def recv(self, stream, crc_mode=1, retry=16, timeout=60, delay=1):
        '''
        Receive a stream via the XMODEMCRC protocol.

            >>> stream = file('/etc/issue', 'wb')
            >>> print modem.recv(stream)
            2342

        Returns the number of bytes received on success or ``None`` in case of
        failure.
        '''

        # initiate protocol
        error_count = 0
        byte = 0
        cancel = 0
        while True:
            # first try CRC mode, if this fails,
            # fall back to checksum mode
            if error_count >= retry:
                log.error(error.ABORT_ERROR_LIMIT)
                self.abort(timeout=timeout)
                return None
            elif crc_mode and error_count < (retry / 2):
                if not self.putc(const.CRC):
                    time.sleep(delay)
                    error_count += 1
            else:
                crc_mode = 0
                if not self.putc(const.NAK):
                    time.sleep(delay)
                    error_count += 1

            byte = self.getc(1, timeout)
            if byte is None:
                error_count += 1
                continue
            elif byte == const.SOH:
                break
            elif byte == const.CAN:
                if cancel:
                    return None
                else:
                    cancel = 1
            else:
                error_count += 1

        # read data
        error_count = 0
        income_size = 0
        packet_size = 128
        sequence = 1
        cancel = 0
        while True:
            while True:
                if byte == const.SOH:
                    break
                elif byte == const.EOT:
                    # SEND LAST <ACK>
                    self.putc(const.ACK)
                    return income_size
                elif byte == const.CAN:
                    # Cancel at two consecutive <CAN> bytes
                    if cancel:
                        return None
                    else:
                        cancel = 1
                else:
                    log.error(error.ABORT_EXPECT_SOH_EOT % byte.hex())
                    error_count += 1
                    if error_count >= retry:
                        self.abort()
                        return None

            # read sequence
            error_count = 0
            cancel = 0
            seq1 = ord(self.getc(1))
            seq2 = 0xff - ord(self.getc(1))
            if seq1 == sequence and seq2 == sequence:
                # Sequence is ok, read packet
                # packet_size + checksum
                data = self.getc(packet_size + 1 + crc_mode)
                data = self._check_crc(data, crc_mode)
                # valid data, append chunk
                if data:
                    income_size += len(data)
                    stream.write(data)
                    self.putc(const.ACK)
                    sequence = (sequence + 1) % 0x100
                    byte = self.getc(1, timeout)
                    continue
            else:
                # consume data
                self.getc(packet_size + 1 + crc_mode)
                log.error(error.ABORT_INVALID_SEQ)

            # something went wrong, request retransmission
            self.putc(const.NAK)
