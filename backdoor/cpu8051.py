#!/usr/bin/env python

# Tools for working with the 8051 coprocessor on the MT1939

__all__ = [
    'cpu8051_boot', 'cpu8051_evalasm',
    'cpu8051_backdoor',
]

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


def cpu8051_evalasm(d, code):
    """Run a snippet of assembly code on the 8051
    Returns the value of 'a'
    """
    return cpu8051_boot(d, assemble51_string(0, '''\
        %(code)s
        mov     dptr, #0x4d91
        movx    @dptr, a
        sjmp    .
    ''' % locals()))


def cpu8051_backdoor(d, address = pad):
    """Run a backdoor stub on the 8051 so we can control it remotely.
    Returns a library of ARM C++ functions for interacting with the stub.
    """

    # Command buffer is at [41f4b00]. First byte must be written last. Results
    # are written immediately after command, and first byte is zeroed.
    #
    #  01 <address low> <address high> -> <data>       XDATA read
    #  02 <address low> <address high> <data>          XDATA write

    assert 1 == cpu8051_boot(d, compile51_string(0, '''\

        __xdata __at (0x4d91) unsigned char boot_status;
        __xdata __at (0x4b00) unsigned char command[0x10];

        void start()
        {
            boot_status = 1;

            while (1) {
                switch (command[0]) {

                    // XDATA read
                    case 1:
                        command[3] = *(__xdata unsigned char *)( command[1] | (command[2] << 8) );
                        break;

                    // XDATA write
                    case 2:
                        *(__xdata unsigned char *)( command[1] | (command[2] << 8) ) = command[3];
                        break;

                }
                command[0] = 0;
            }
        }

        '''), address=address)

    return compile_library(d, address, dict(

        # peek(address) -> data
        # On timeout, returns ffffffff
        peek = '''{
            MT1939::CPU8051::cr_write(0x41f4b01, arg);
            MT1939::CPU8051::cr_write(0x41f4b02, arg >> 8);
            MT1939::CPU8051::cr_write(0x41f4b00, 1);

            SysTime deadline = SysTime::now() + (SysTime::hz/4);
            uint32_t result = 0xffffffff;   // Timeout from 8051

            do {
                if (MT1939::CPU8051::cr_read(0x41f4b00) == 0) {
                    result = MT1939::CPU8051::cr_read(0x41f4b03);
                    break;
                }
            } while (SysTime::now().difference(deadline) < 0);
            result;
        }''',

        # poke( address | (data << 24) ) -> 0
        # On timeout, returns ffffffff
        poke = '''{
            MT1939::CPU8051::cr_write(0x41f4b01, arg);
            MT1939::CPU8051::cr_write(0x41f4b02, arg >> 8);
            MT1939::CPU8051::cr_write(0x41f4b03, arg >> 24);
            MT1939::CPU8051::cr_write(0x41f4b00, 2);

            SysTime deadline = SysTime::now() + (SysTime::hz/4);
            uint32_t result = 0xffffffff;   // Timeout from 8051

            do {
                if (MT1939::CPU8051::cr_read(0x41f4b00) == 0) {
                    result = 0;
                    break;
                }
            } while (SysTime::now().difference(deadline) < 0);
            result;
        }''',

        ))
