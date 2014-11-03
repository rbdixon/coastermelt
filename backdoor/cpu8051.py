#!/usr/bin/env python

# Tools for working with the 8051 coprocessor on the MT1939

__all__ = [ 'cpu8051_boot' ]

from code import *
from dump import *


def cpu8051_boot(d, firmware, address = pad):
    """Transmit a firmware image to the 8051 and boot it.
    Returns the status code, or 0 if booting timed out.
    """

    poke_words_from_string(d, address, firmware)
    code_address = (address + len(firmware) + 7) & ~7

    return evalc(d, ''' {
        MT1939::CPU8051::firmware_install((uint8_t*) 0x%08x);
        MT1939::CPU8051::start();
    } ''' % address, address=code_address)
