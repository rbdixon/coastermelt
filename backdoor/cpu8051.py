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
    code = 'MT1939::CPU8051::start((uint8_t*) 0x%08x' % address
    return evalc(d, code, address=code_address)


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


def cpu8051_backdoor(d,
    address = target_memory.cpu8051_backdoor,
    verbose = True, show_listing = False, start_cpu = True):

    """Run a backdoor stub on the 8051 so we can control it remotely.

    Returns a library of ARM C++ functions for interacting with the stub.
    If start_cpu is True, we restart the 8051 running the debug stub firmware.
    If it's false, we leave the 8051 as-is.
    """
    # Compile 8051 firmware backdoor
    bd51string = compile51_string(0, backdoor_8051, show_listing=show_listing)
    words = words_from_string(bd51string)

    # Compile library, place it after the 8051 firmware in RAM.
    code_address = address + 4 * len(words)
    libstring, lib = compile_library_string(code_address,
        backdoor_arm_funcs,
        includes = dict(includes,
            backdoor = backdoor_arm_lib
        ),
        defines = dict(defines,
            backdoor_firmware = address,
            bounce_buffer_address = target_memory.bounce_buffer
        ))
    words += words_from_string(libstring)

    # Upload data to the device and start the CPU
    poke_words(d, address, words)
    bd = BackdoorDevice(d, lib)

    if verbose:
        print "* 8051 backdoor is 0x%x bytes, loaded at 0x%x" % (len(bd51string), address)
        print "* ARM library is 0x%x bytes, loaded at 0x%x" % (len(libstring), code_address)

    if start_cpu:
        bd.start()
        if verbose:
            print "* 8051 backdoor running"

    # Device object for interacting with the 8051 via Python
    return bd


# This is an 8051 program to run on the MCU, compiled with SDCC. We read
# commands via shared memory and run them here in a loop. At this point it
# isn't obvious what memory is safe, so we restrict the interface to use only
# the boot_status byte for communication back to the ARM, turning it into a
# tiny state machine.
#
# Status bytes:
#
#    00        CPU off
#    01        Idle
#
#    02        addr_low = data
#    03        addr_low = data | 0x80
#    04        addr_high = data
#    05        addr_high = data | 0x80
#    06        XDATA[addr] = data
#    07        XDATA[addr] = data | 0x80
#
#    40        data = XDATA[addr]
#
#    70        complete, high data bit = 0
#    71        complete, high data bit = 1
#
#    80..ff    Store low 7 data bits
#
backdoor_8051 = '''\
    typedef unsigned char uint8_t;
    #define XADDR ((__xdata unsigned char *)( addr_low | (addr_high << 8) ))
    __sbit __at (0xaf) irq_enable;
    __xdata __at (0x4d91) volatile uint8_t status;

    void start()
    {
        uint8_t addr_low;
        uint8_t addr_high;
        uint8_t data;
        uint8_t s;

        irq_enable = 0;
        status = 1;

        while (1) {
            s = status;

            if (s & 0x80) {
                // Store data
                data = s & 0x7f;
                status = 1;
                continue;
            }

            switch (s) {

            case 2:  addr_low  = data;         status = 1; break;
            case 3:  addr_low  = data | 0x80;  status = 1; break;
            case 4:  addr_high = data;         status = 1; break;
            case 5:  addr_high = data | 0x80;  status = 1; break;
            case 6:  *XADDR = data;            status = 1; break;
            case 7:  *XADDR = data | 0x80;     status = 1; break;

            case 0x40:
                data = *XADDR;                      // Peek
                status = 0x70 | (data >> 7);        // High bit
                while (status != 1);                //   wait for ARM to ack
                status = 0x80 | data;               // Low 7 bits
                while (status != 1);                //   wait for ARM to ack
                break;

            }
        }
    }
'''


# A library of C++ functions running on the ARM, to talk to the 8051 backdoor above.
backdoor_arm_lib = '''\
    namespace backdoor {
    using namespace MT1939::CPU8051;
    auto bounce_buffer = (uint8_t*) bounce_buffer_address;

    bool set_status(uint8_t s, SysTime deadline)
    {
        return cr_write(0x41f4d91, s, deadline) >= 0;
    }

    bool get_status(uint8_t &s, SysTime deadline)
    {
        int r = cr_read(0x41f4d91, deadline);
        s = r;
        return r >= 0;
    }

    bool wait_idle(SysTime deadline)
    {
        uint8_t s;
        while (get_status(s, deadline)) {
            if (s == 1) {
                return true;
            }
        }
        return false;
    }

    bool wait_response(uint8_t exclude, uint8_t &result, SysTime deadline)
    {
        while (get_status(result, deadline)) {
            if (result != exclude) {
                return true;
            }
        }
        return false;
    }

    bool set_address(uint16_t addr, SysTime deadline)
    {
        return
            set_status(0x80 | (0x7f & (addr >> 8)), deadline) &&
            wait_idle(deadline) &&
            set_status(0x04 | (0x01 & (addr >> 15)), deadline) &&
            wait_idle(deadline) &&
            set_status(0x80 | (0x7f & addr), deadline) &&
            wait_idle(deadline) &&
            set_status(0x02 | (0x01 & (addr >> 7)), deadline) &&
            wait_idle(deadline);
    }

    bool xpoke(uint16_t addr, uint8_t data)
    {
        SysTime deadline = SysTime::future(0.25);
        return
            set_address(addr, deadline) &&
            set_status(0x80 | (0x7f & data), deadline) &&
            wait_idle(deadline) &&
            set_status(0x06 | (0x01 & (data >> 7)), deadline) &&
            wait_idle(deadline);
    }

    int xpeek(uint16_t addr)
    {
        SysTime deadline = SysTime::future(0.25);
        uint8_t r1, r2;
        return (
            set_address(addr, deadline) &&
            set_status(0x40, deadline) &&
            wait_response(0x40, r1, deadline) &&
            set_status(1, deadline) &&
            wait_response(1, r2, deadline) &&
            set_status(1, deadline)
        ) ? ( ((r1 << 7) & 0x80) | (r2 & 0x7F) ) : -1;
    }

    uint8_t *xpeek_block(uint16_t addr, unsigned length)
    {
        for (unsigned i = 0; i != length; i++) {
            int v = xpeek(addr + i);
            if (v < 0) {
                return 0;
            }
            bounce_buffer[i] = v;
        }
        return bounce_buffer;
    }
}'''


# Expressions to export as functions in the ARM C++ library
backdoor_arm_funcs = dict(
    start = 'CPU8051::start( (uint8_t*) backdoor_firmware )',
    stop = 'CPU8051::stop(), 0',
    status = 'CPU8051::status()',
    cr_read = 'CPU8051::cr_read(0x041f0000 | (arg & 0xffff))',
    cr_write = 'CPU8051::cr_write(0x041f0000 | (arg & 0xffff), arg >> 16)',
    xpeek = 'backdoor::xpeek(arg)',
    xpoke = 'backdoor::xpoke(arg, arg >> 16) ? 0 : -1',
    xpeek_block = '(uint32_t) backdoor::xpeek_block(arg, arg >> 16)'
)


class BackdoorDevice:
    """Python interface to the 8051 CPU backdoor.
    Communicates via an ARM function library 'lib', assumed to already be installed.
    """
    def __init__(self, d, lib):
        self.d = d
        self.lib = lib

    def _timeout(self):
        raise IOError('Timeout waiting on 8051 backdoor\n\n' +
            '--> You can (re)start the backdoor firmware with d8.start()')

    def _call_with_timeout(self, name, arg):
        v, _ = self.d.blx(self.lib[name], arg)
        if (v & 0xff) != v:
            self._timeout()
        return v

    def start(self):
        status, _ = self.d.blx(self.lib['start'], 0)
        if status != 1:
            raise IOError("Failed to boot 8051 processor, status 0x%02x" % status)

    def stop(self):
        self.d.blx(self.lib['stop'], 0)

    def status(self):
        return self.d.blx(self.lib['status'], 0)[0]

    def cr_read(self, addr):
        return self._call_with_timeout('cr_read', addr)

    def cr_write(self, addr, data):
        self._call_with_timeout('cr_write', (addr & 0xffff) | ((data & 0xff) << 16))

    def xpeek(self, addr):
        return self._call_with_timeout('xpeek', addr & 0xffff)

    def xpoke(self, addr, data):
        self._call_with_timeout('xpoke', (addr & 0xffff) | ((data & 0xff) << 16))

    def xpoke_bytes(self, addr, bytes):
        for i, b in enumerate(bytes):
            self.xpoke(addr + i, b)

    def xpeek_block(self, addr, length = 0x100):
        assert length <= target_memory.bounce_buffer_size
        addr, _ = self.d.blx(self.lib['xpeek_block'], (addr & 0xffff) | (length << 16))
        if addr == 0:
            self._timeout()
        return read_block(self.d, addr, length)
