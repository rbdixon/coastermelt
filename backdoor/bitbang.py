# This is an alternate Device backend for the debugger, implemented using a
# bit-bang serial port via the LED and Eject button. The hardware and bitbang
# side are described in bitbang.h; this file implements a debugger interface
# compatible with the 'remote' module.

__all__ = [ 'bitbang_backdoor', 'BitbangDevice' ]

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

        static uint32_t counter = 0;
        const uint32_t loops = 150;

        MT1939::SysTime::wait_ms(1);
        if (counter == loops) {
//            bitbang_backdoor();
        }
        counter++;
        println(counter);

    ''', handler_address=handler_address, verbose=verbose)


class BitbangDevice:
    """Device implemented using the commands provided by bitbang_backdoor()
    To switch to this device in cmshell, you can use the %bitbang command.
    """
    def __init__(self, serial_port):
        # Only require pyserial if we're using BitbangDevice
        import serial
        self.port = serial.Serial(port=serial_port, baudrate=57600, timeout=1)
        self.ping()

    def ping(self):
        self.port.write('\n')   # Any byte except 0x55 will do
        self.signature = self.port.read(1024)
        print self.signature
