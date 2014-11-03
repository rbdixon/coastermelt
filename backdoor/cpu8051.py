#!/usr/bin/env python

# Tools for working with the 8051 coprocessor on the MT1939. This includes a
# simple 'backdoor' firmware for the 8051 that lets us remote- control its I/O
# devices.

__all__ = [
    'cpu8051_boot', 'cpu8051_evalasm',
    'cpu8051_backdoor',
]

from code import *
from dump import *
import target_memory


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


class BackdoorDevice:
    """Python interface to the 8051 CPU backdoor.
    Communicates via an ARM function library 'lib', assumed to already be installed.
    """
    def __init__(self, d, lib):
        self.d = d
        self.lib = lib

    def start(self):
        status, _ = self.d.blx(self.lib['start'], 0)
        if status != 1:
            raise IOError("Failed to boot 8051 processor, status 0x%02x" % status)

        # Test memory interface and ping the backdoor
        # (Assumes 8051 code runs much faster than remote Python code)
        self.cr_write(0x4b50, 0x55)
        assert self.cr_read(0x4b50) == 0x55
        self.cr_write(0x4b50, 0xAA)
        assert self.cr_read(0x4b50) == 0xAA
        self.cr_write(0x4b50, 0x01)
        assert self.cr_read(0x4b50) == 0x00

    def stop(self):
        self.d.blx(self.lib['stop'], 0)

    def status(self):
        return self.d.blx(self.lib['status'], 0)[0]

    def cr_read(self, addr):
        return self.d.blx(self.lib['cr_read'], addr)[0]

    def cr_write(self, addr, data):
        self.d.blx(self.lib['cr_write'], (addr & 0xffff) | ((data & 0xff) << 16))

    def xpeek(self, addr):
        return self.d.blx(self.lib['xpeek'], addr & 0xffff)[0]

    def xpoke(self, addr, data):
        self.d.blx(self.lib['xpoke'], (addr & 0xffff) | ((data & 0xff) << 16))


# Command buffer is at [41f4b50]. First byte must be written last. Results
# are written immediately after command, and first byte is zeroed.
#
#  01 <address low> <address high> -> <data>       XDATA read
#  02 <address low> <address high> <data>          XDATA write

backdoor_8051 = '''
    // This is an 8051 program to run on the MCU, compiled with SDCC.
    // We read commands via shared memory and run them here in a loop.

    __sbit __at (0xaf) global_interrupt_enable;
    volatile __xdata __at (0x4d91) unsigned char boot_status;
    volatile __xdata __at (0x4b50) unsigned char cmd[0x10];

    void start()
    {
        global_interrupt_enable = 0;
        boot_status = 1;
        while (1) {
            switch (cmd[0]) {

                // Nop
                case 1:
                    cmd[0] = 0;
                    break;

                // XDATA read
                case 2:
                    cmd[3] = *(__xdata unsigned char *)( cmd[1] | (cmd[2] << 8) );
                    cmd[0] = 0;
                    break;

                // XDATA write
                case 3:
                    *(__xdata unsigned char *)( cmd[1] | (cmd[2] << 8) ) = cmd[3];
                    cmd[0] = 0;
                    break;
            }
        }
    }
    '''

backdoor_arm_lib = '''
    // A library of C++ functions running on the ARM, to talk to the 8051 backdoor above.

    using namespace MT1939;

    int xpeek(uint16_t addr)
    {
        CPU8051::cr_write(0x41f4b51, addr);
        CPU8051::cr_write(0x41f4b52, addr >> 8);
        CPU8051::cr_write(0x41f4b50, 2);

        SysTime deadline = SysTime::now() + (SysTime::hz/4);

        while (CPU8051::cr_read(0x41f4b00) != 0) {
            if (SysTime::is_past(deadline)) {
                return -1;
            }
        }

        CPU8051::cr_read(0x41f4b53);
    }

    int xpoke(uint16_t addr, uint8_t data)
    {
        CPU8051::cr_write(0x41f4b51, addr);
        CPU8051::cr_write(0x41f4b52, addr >> 8);
        CPU8051::cr_write(0x41f4b53, data);
        CPU8051::cr_write(0x41f4b50, 3);

        SysTime deadline = SysTime::now() + (SysTime::hz/4);

        while (CPU8051::cr_read(0x41f4b00) != 0) {
            if (SysTime::is_past(deadline)) {
                return -1;
            }
        }

        return 0;
    }

    int start_backdoor()
    {
        CPU8051::firmware_install((uint8_t*) backdoor_firmware);
        return CPU8051::start();
    }
    '''

backdoor_arm_funcs = dict(
    # Expressions to export as functions in the ARM C++ library

    start = 'start_backdoor()',
    stop = 'CPU8051::stop(), 0',
    status = 'CPU8051::status()',
    cr_read = 'CPU8051::cr_read(0x041f0000 | (arg & 0xffff))',
    cr_write = 'CPU8051::cr_write(0x041f0000 | (arg & 0xffff), arg >> 16)',
    xpeek = 'xpeek(arg)',
    xpoke = 'xpoke(arg, arg >> 16)',
    )


def cpu8051_backdoor(d, address = target_memory.cpu8051_backdoor,
    verbose = True, show_listing = False):
    """Run a backdoor stub on the 8051 so we can control it remotely.

    Returns a library of ARM C++ functions for interacting with the stub. Does
    not modify the 8051 CPU state unless directed. Install the 8051 debug stub
    with the start() method.
    """
    # Compile 8051 firmware backdoor
    bd51string = compile51_string(0, backdoor_8051, show_listing=show_listing)
    words = words_from_string(bd51string)

    # Compile library, place it after the 8051 firmware in RAM.
    code_address = address + 4 * len(words)
    libstring, lib = compile_library_string(code_address,
        backdoor_arm_funcs,
        includes = dict(includes, backdoor = backdoor_arm_lib),
        defines = dict(defines, backdoor_firmware = address))
    words += words_from_string(libstring)

    # Upload data to the device and start the CPU
    poke_words(d, address, words)

    if verbose:
        print "* 8051 backdoor is 0x%x bytes, loaded at 0x%x" % (len(bd51string), address)
        print "* ARM library is 0x%x bytes, loaded at 0x%x" % (len(libstring), code_address)

    # Python access to the C++ ARM library
    return BackdoorDevice(d, lib)

