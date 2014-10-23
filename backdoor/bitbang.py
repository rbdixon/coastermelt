# This is an alternate Device backend for the debugger, implemented using a
# bit-bang serial port via the LED and Eject button. The hardware and bitbang
# side are described in bitbang.h; this file implements a debugger interface
# compatible with the 'remote' module.


class BitbangDevice:
    """Device implemented using the commands provided by bitbang_backdoor()
    To switch to this device in cmshell, you can use the %bitbang command.
    """

    def __init__(self, serial_port):
        # Only require pyserial to use BitbangDevice
        import serial
        self.port = serial.Serial(port=serial_port, baudrate=57600, timeout=1)
        self.ping()

    def ping(self):
        self.port.write('\n')   # Any byte except 0x55 will do
        self.signature = self.port.read(1024)
        print self.signature
