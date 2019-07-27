from setuptools import setup, find_packages

setup(
    name         = 'modem',
    version      = '1.0',
    author       = 'Wijnand Modderman-Lenstra',
    author_email = 'maze@pyth0n.org',
    url          = 'https://maze.io/',
    description  = ('Modem implementations for XMODEM, YMODEM and ZMODEM'),
    long_description = open('doc/source/about.rst').read(),
    license      = 'MIT',
    keywords     = 'xmodem ymodem zmodem protocol',
	package_dir  = {'modem.protocol' : 'modem/protocol' },
    packages     = ['modem', 'modem.protocol'],
    package_data = {'': ['doc/*.TXT']},
)

