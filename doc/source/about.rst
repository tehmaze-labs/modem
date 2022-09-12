🎊🎉 This fork is target to run `modem` on Python3

=============
 About modem
=============

This package ports the XMODEM, YMODEM and ZMODEM protocols to Python. We try to
implement the protocols as minimalistic as possible without breaking the
protocol specifications.

The interface to most modem classes are pretty similair. Keep in mind though,
that the XMODEM protocol can send one file (stream) at a time, whereas the
YMODEM and ZMODEM protocols can send multiple.

All modem implementations must be given a ``getc`` callback to retrieve
character data from the remote end and a ``putc`` callback to send character
data.


Examples
========

An example using ``STDIN``/``STDOUT`` may read::

    >>> import select
    >>> import sys
    >>> def getc(size, timeout=5):
    ...     r, w, e = select.select([sys.stdin.fileno()], [], [], timeout)
    ...     if r: return sys.stdin.read(size)
    ...
    >>> def putc(data, timeout):
    ...     r, w, e = select.select([], [sys.stdout.fileno()], [], timeout)
    ...     if w: return sys.stdout.write(data)
    ...


Now we can send a stream using ``XMODEM``::

    >>> from modem import XMODEM
    >>> xmodem = XMODEM(getc, putc)
    >>> stream = file(__file__)
    >>> xmodem.send(stream)
    ...


Or send one or more files using ``YMODEM`` or ``ZMODEM``::

    >>> from modem import ZMODEM
    >>> zmodem = ZMODEM(getc, putc)
    >>> zmodem.send([__file__])


Acknowledgements
================

About the protocols:

:``XMODEM``: |copy| 1977 Ward Christensen
:``YMODEM``: |copy| 1985 Chunk Forsberg, Omen Technology Inc.
:``ZMODEM``: |copy| 1986 Chunk Forsberg, Omen Technology Inc.


Thanks to:

* Paolo Perfetti, wrote most of the ``YMODEM`` implementation

.. |copy| unicode:: U+00A9 .. COPYRIGHT SIGN

