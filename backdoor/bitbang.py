# This is an alternate Device backend for the debugger, implemented using a
# bit-bang serial port via the LED and Eject button. The hardware and bitbang
# side are described in bitbang.h; this file implements a debugger interface
# compatible with the 'remote' module.

__all__ = [ 'bitbang_backdoor', 'BitbangDevice' ]

import struct, time
from hook import *
from code import *

includes['bitbang'] = '#include "bitbang.h"'


def bitbang_backdoor(d, handler_address, hook_address = 0x18ccc, verbose = False):
    """Invoke the bitbang_backdoor() main loop using another debug interface.

    To avoid putting the original debug interface into a stuck state, this
    installs the bitbang_backdoor as a mainloop hook on a counter, to spin
    the mainloop for a particular number of iterations before we start.

    (Why the hook instead of a SCSI timeout? Running the backdoor directly
    from a SCSI handler seems to break things so badly that even with a timeout
    set, the driver hangs.)

    The hook overlay doesn't have to keep working once we launch the backdoor.
    """
    overlay_hook(d, hook_address, '''

        static int counter = 0;
        const int ticks_per_loop = 100;
        const int loops = 1000;

        MT1939::SysTime::wait_ticks(ticks_per_loop);

        if (counter == loops) {
            bitbang_backdoor();
        }
        if (counter <= loops) {
            counter++;
        }

    ''', handler_address=handler_address, verbose=verbose)


class BitbangDevice:
    """Device implemented using the commands provided by bitbang_backdoor()
    To switch to this device in cmshell, you can use the %bitbang command.
    """

    def __init__(self, serial_port):
        # Only require pyserial if we're using BitbangDevice
        import serial
        self.port = serial.Serial(port=serial_port, baudrate=57600, timeout=0.25)
        self.synchronized = False
        self.sync()

    def _write(self, s, delay = 2):
        # Write framed bytes to the bitbang serial port
        # Low-level write. Since it's a janky bit-bang serial port, go really slowly.
        self.port.write(''.join(['\xff' * delay + '\x00' + c for c in s]))

    def _delay(self, n):
        # Insert a timed delay into the output buffer, to account for time taken
        # by the backdoor code between packets.
        self.port.write('\xff' * n)

    def _check(self, check, data, address):
        if check != data ^ address:
            raise IOError("Check word incorrect, %08x != %08x (%08x ^ %08x)"
                % (check, data ^ address, data, address))

    def _auto_retry(f):
        # Decorator to automatically retry when a communications error happens
        def wrapper(self, *arg, **kw):
            retries = 20
            while True:
                try:

                    try:
                        return f(self, *arg, **kw)
                    except struct.error:
                        # Consolidate this in with other I/O errors
                        raise IOError("The device was quiet when we expected a reply :(")

                except IOError, e:
                    if retries:
                        retries -= 1
                        continue
                    else:
                        raise IOError("Error communicating with bitbang backdoor, out of retries.\n%s" % e)
                        raise
        return wrapper

    def _maintain_sync(f):
        # Decorator to automatically resync on error
        def wrapper(self, *arg, **kw):
            if not self.synchronized:
                self.sync()
            self.synchronized = False
            result = f(self, *arg, **kw)
            self.synchronized = True
            return result
        return wrapper

    @_auto_retry
    def sync(self):
        # Gross delay-based synchronization, but it keeps the part on the slow CPU simple.
        self.synchronized = False
        expected_signature = '~MeS`14 [bitbang]\r\n'    
        self.port.flushInput()
        self._write('\n' * 32)
        self._delay(100)

        if self.port.read(len(expected_signature)) == expected_signature:
            # Make sure we're synchronized, cuz the dumb protocol is dumb.
            # This discards input until timeout, so we know there's no buffered
            # data anywhere in the system.
            self.port.read(0x10000)
            self.synchronized = True
        else:
            raise IOError("Can't establish contact with bitbang_backdoor()")

    @_auto_retry
    @_maintain_sync
    def peek(self, address):
        self._write(struct.pack('<BI', 0xf0, address))
        data, check = struct.unpack('<II', self.port.read(8))
        self._check(check, data, address)
        return data

    @_auto_retry
    @_maintain_sync
    def poke(self, address, data):
        self._write(struct.pack('<BII', 0xe1, address, data))
        check, = struct.unpack('<I', self.port.read(4))
        self._check(check, data, address)

    @_auto_retry
    @_maintain_sync
    def peek_byte(self, address):
        self._write(struct.pack('<BI', 0xd2, address))
        data, check = struct.unpack('<BI', self.port.read(5))
        self._check(check, data, address)
        return data

    @_auto_retry
    @_maintain_sync
    def poke_byte(self, address, data):
        self._write(struct.pack('<BIB', 0xc3, address, data))
        check, = struct.unpack('<I', self.port.read(4))
        self._check(check, data, address)

    @_auto_retry
    @_maintain_sync
    def blx(self, address, r0 = 0, timeout = 30):
        savedTimeout = self.port.timeout
        self.port.timeout = timeout
        try:
            self._write(struct.pack('<BII', 0xb4, address, r0))
            r0, r1, check = struct.unpack('<III', self.port.read(12))
            self._check(check, r0, address)
            return (r0, r1)
        finally:
            self.port.timeout = savedTimeout

    @_auto_retry
    @_maintain_sync
    def read_block(self, address, wordcount):
        wordcount = min(wordcount, 0x100)
        self._write(struct.pack('<BII', 0xa5, address, wordcount))
        data = self.port.read(4 * (1 + wordcount))
        last_word, check = struct.unpack('<II', data[-8:])
        self._check(check, last_word, address + 4 * wordcount)
        return data[:-4]

    @_auto_retry
    @_maintain_sync
    def fill_words(self, address, word, wordcount):
        self._write(struct.pack('<BIII', 0x96, address, word, wordcount))
        check = struct.unpack('<I', self.port.read(4))[0]
        self._check(check, word, address + 4 * wordcount)

    @_auto_retry
    @_maintain_sync
    def fill_bytes(self, address, byte, bytecount):
        self._write(struct.pack('<BIBI', 0x78, address, byte, bytecount))
        check = struct.unpack('<I', self.port.read(4))[0]
        self._check(check, byte, address + bytecount)

    @_auto_retry
    @_maintain_sync
    def exit(self):
        self._write(chr(0x87))
        if self.port.read() != chr(0x55):
            raise IOError("Response byte incorrect")
        self.port.close()

