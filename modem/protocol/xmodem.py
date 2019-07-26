import time
from modem import error
from modem.base import Modem
from modem import const
from modem.tools import log


class XMODEM(Modem):
    '''
    XMODEM protocol implementation, expects an object to read from and an
    object to write to.

    >>> def getc(size, timeout=1):
    ...     return data or None
    ...
    >>> def putc(data, timeout=1):
    ...     return size or None
    ...
    >>> modem = XMODEM(getc, putc)

    '''

    # Protocol identifier
    protocol = const.PROTOCOL_XMODEM

    def abort(self, count=2, timeout=60):
        '''
        Send an abort sequence using CAN bytes.
        '''
        for counter in range(0, count):
            self.putc(const.CAN, timeout)

    def send(self, stream, retry=16, timeout=60, quiet=0):
        '''
        Send a stream via the XMODEM protocol.

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
                    # We abort if we receive two consecutive <CAN> bytes
                    if cancel:
                        return False
                    else:
                        cancel = 1
                else:
                    log.error(error.ERROR_EXPECT_NAK_CRC % ord(byte))

            error_count += 1
            if error_count >= retry:
                log.error(error.ABORT_ERROR_LIMIT)
                self.abort(timeout=timeout)
                return False

        # Start sending the stream
        return self._send_stream(stream, crc_mode, retry, timeout)

    def recv(self, stream, crc_mode=1, retry=16, timeout=60, delay=1, quiet=0):
        '''
        Receive a stream via the XMODEM protocol.

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
                log.debug(error.DEBUG_TRY_CRC)
                if not self.putc(const.CRC):
                    time.sleep(delay)
                    error_count += 1
            else:
                log.debug(error.DEBUG_TRY_CHECKSUM)
                crc_mode = 0
                if not self.putc(const.NAK):
                    time.sleep(delay)
                    error_count += 1

            byte = self.getc(1, timeout)
            if byte is None:
                error_count += 1
                continue
            elif byte in [const.SOH, const.STX]:
                break
            elif byte == const.CAN:
                if cancel:
                    log.error(error.ABORT_RECV_CAN_CAN)
                    return None
                else:
                    log.debug(error.DEBUG_RECV_CAN)
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
                    packet_size = 128
                    break
                elif byte == const.EOT:
                    # Acknowledge end of transmission
                    self.putc(const.ACK)
                    return income_size
                elif byte == const.CAN:
                    # We abort if we receive two consecutive <CAN> bytes
                    if cancel:
                        return None
                    else:
                        cancel = 1
                else:
                    log.debug(error.DEBUG_EXPECT_SOH_EOT % ord(byte))
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
                # sequence is ok, read packet
                # packet_size + checksum
                data = self._check_crc(
                    self.getc(packet_size + 1 + crc_mode),
                    crc_mode
                )

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
                log.warning(error.WARNS_SEQUENCE % (sequence, seq1, seq2))

            # something went wrong, request retransmission
            self.putc(const.NAK)

    def _send_stream(self, stream, crc_mode,
                     retry=16, timeout=0, filesize=0.0):
        '''
        Sends a stream according to the given protocol dialect:

            >>> stream = file('/etc/issue', 'rb')
            >>> print modem.send(stream)
            True

        Return ``True`` on success, ``False`` in case of failure.
        '''

        # Get packet size for current protocol
        packet_size = const.PACKET_SIZE.get(self.protocol, 128)

        # ASSUME THAT I'VE ALREADY RECEIVED THE INITIAL <CRC> OR <NAK>
        # SO START DIRECTLY WITH STREAM TRANSMISSION
        sequence = 1
        error_count = 0
        total_sent = 0

        while True:
            data = stream.read(packet_size)
            # Check if we're done sending
            if not data:
                break

            # Select optimal packet size when using YMODEM
            if self.protocol == const.PROTOCOL_YMODEM:
                packet_size = (len(data) <= 128) and 128 or 1024

            # Align the packet
            data = data.ljust(packet_size, b'\x00')

            # Calculate CRC or checksum
            crc = crc_mode and self.calc_crc16(data) or \
                self.calc_checksum(data)

            # SENDS PACKET WITH CRC
            if not self._send_packet(
                  sequence, data, packet_size, crc_mode,
                  crc, error_count, retry, timeout):
                log.error(error.ERROR_SEND_PACKET)
                return False

            # Next sequence
            sequence = (sequence + 1) % 0x100
            if filesize > 0:
                total_sent += packet_size
                progress = total_sent/filesize
                remain = (filesize - total_sent)/filesize
                print(error.DEBUG_SEND_PROGRESS.format(
                        int(50 * progress) * '=',
                        progress * 100,
                        int(50 * remain) * ' ',
                    ), end='\r', flush=True
                )

        # STREAM FINISHED, SEND EOT
        log.debug(error.DEBUG_SEND_EOT)
        if self._send_eot(error_count, retry, timeout):
            return True
        else:
            log.error(error.ERROR_SEND_EOT)
            return False

    def _send_packet(self, sequence, data, packet_size, crc_mode, crc,
                     error_count, retry, timeout, debug=False):
        '''
        Sends one single packet of data, appending the checksum/CRC. It retries
        in case of errors and wait for the <ACK>.

        Return ``True`` on success, ``False`` in case of failure.
        '''
        start_byte = const.SOH if packet_size == 128 else const.STX
        while True:
            self.putc(start_byte, debug=debug)
            self.putc(bytes([sequence]), debug=debug)
            self.putc(bytes([0xff - sequence]), debug=debug)
            self.putc(data, debug=debug)
            if crc_mode:
                self.putc(bytes([crc >> 8]), debug=debug)
                self.putc(bytes([crc & 0xff]), debug=debug)
            else:
                # Send CRC or checksum
                self.putc(bytes([crc]), debug=debug)

            # Wait for the <ACK>
            byte = self.getc(1, timeout, debug=debug)
            if byte == const.ACK:
                # Transmission of the character was successful
                return True

            if byte in [b'', const.NAK]:
                error_count += 1
                if error_count >= retry:
                    # Excessive amounts of retransmissions requested
                    self.error(error.ABORT_ERROR_LIMIT)
                    self.abort(timeout=timeout)
                    return False
                continue

            # Protocol error
            log.error(error.ERROR_PROTOCOL)
            error_count += 1
            if error_count >= retry:
                log.error(error.ABORT_ERROR_LIMIT)
                self.abort(timeout=timeout)
                return False

    def _send_eot(self, error_count, retry, timeout):
        '''
        Sends an <EOT> code. It retries in case of errors and wait for the
        <ACK>.

        Return ``True`` on success, ``False`` in case of failure.
        '''
        while True:
            self.putc(const.EOT)
            # Wait for <ACK>
            byte = self.getc(1, timeout)
            if byte == const.ACK:
                # <EOT> confirmed
                return True
            else:
                error_count += 1
                if error_count >= retry:
                    # Excessive amounts of retransmissions requested,
                    # abort transfer
                    log.error(error.ABORT_ERROR_LIMIT)
                    return False

    def _wait_recv(self, error_count, timeout):
        '''
        Waits for a <NAK> or <CRC> before starting the transmission.

        Return <NAK> or <CRC> on success, ``False`` in case of failure
        '''
        # Initialize protocol
        cancel = 0
        retry = 2
        # Loop until the first character is a control character (NAK, CRC) or
        # we reach the retry limit
        while True:
            byte = self.getc(1)
            if byte:
                if byte in [const.NAK, const.CRC]:
                    return byte
                elif byte == const.CAN:
                    # Cancel at two consecutive cancels
                    if cancel:
                        log.error(error.ABORT_RECV_CAN_CAN)
                        self.abort(timeout=timeout)
                        return None
                    else:
                        log.debug(error.DEBUG_RECV_CAN)
                        cancel = 1
                else:
                    # Ignore the rest
                    pass

            error_count += 1
            if error_count >= retry:
                self.abort(timeout=timeout)
                return None

    def _recv_stream(self, stream, crc_mode, retry, timeout, delay):
        '''
        Receives data and write it on a stream. It assumes the protocol has
        already been initialized (<CRC> or <NAK> sent and optional packet 0
        received).

        On success it exits after an <EOT> and returns the number of bytes
        received. In case of failure returns ``False``.
        '''
        # IN CASE OF YMODEM THE FILE IS ALREADY OPEN AND THE PACKET 0 RECEIVED

        error_count = 0
        cancel = 0
        sequence = 1
        income_size = 0
        self.putc(const.CRC)

        byte = self.getc(1, timeout)
        while True:
            if byte is None:
                error_count += 1
                if error_count >= retry:
                    log.error(error.ABORT_ERROR_LIMIT)
                    self.abort(timeout=timeout)
                    return None
                else:
                    continue
            elif byte == const.CAN:
                if cancel:
                    return None
                else:
                    cancel = 1
            elif byte in [const.SOH, const.STX]:
                packet_size = 128 if byte == const.SOH else 1024
                # Check the requested packet size, only YMODEM has a variable
                # size
                if self.protocol != const.PROTOCOL_YMODEM and \
                        const.PACKET_SIZE.get(self.protocol) != packet_size:
                    log.error(error.ABORT_PACKET_SIZE)
                    self.abort(timeout=timeout)
                    return False

                seq1 = ord(self.getc(1))
                seq2 = 0xff - ord(self.getc(1))

                if seq1 == sequence and seq2 == sequence:
                    data = self.getc(packet_size + 1 + crc_mode)
                    data = self._check_crc(data, crc_mode)

                    if data:
                        # Append data to the stream
                        income_size += len(data)
                        stream.write(data)
                        self.putc(const.ACK)
                        sequence = (sequence + 1) % 0x100

                        # Waiting for new packet
                        byte = self.getc(1, timeout)
                        continue

                # Sequence numbering is off or CRC is incorrect, request new
                # packet
                self.getc(packet_size + 1 + crc_mode)
                self.putc(const.NAK)
            elif byte == const.EOT:
                # We are done, acknowledge <EOT>
                self.putc(const.ACK)
                return income_size
            elif byte == const.CAN:
                # Cancel at two consecutive cancels
                if cancel:
                    return False
                else:
                    cancel = 1
                    self.putc(const.ACK)
                    byte = self.getc(1, timeout)
                    continue
            else:
                log.debug(error.DEBUG_EXPECT_SOH_EOT % byte.hex())
                error_count += 1
                if error_count >= retry:
                    log.error(error.ABORT_ERROR_LIMIT)
                    self.abort()
                    return False
