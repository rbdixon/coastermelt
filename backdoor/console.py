#!/usr/bin/env python

# Let's have something like printf,
# but based on a ring buffer in some memory that's not ours.
#
# This is the Python counterpart to the C++ console.h module.
# It can run stand-alone, or via the %console shell command.

__all__ = [
    'console_mainloop', 'console_read',
    'console_address', 'ConsoleOverflowError'
]

import sys
from code import *
from dump import *


# Our ring buffer is 64 KiB. The default location comes from
# more guesswork and memsquares. It's 1MB above the default
# pad, still in an area of DRAM that seems very lightly used.

console_address = 0x1e50000


class ConsoleOverflowError(Exception):
    """Raised by console_read() in case of FIFO buffer overflow"""

    def __init__(self, next_write, next_read):
        self.next_write = next_write
        self.next_read = next_read
        self.byte_count = (next_write - next_read) & 0xffffffff
        Exception.__init__(self, "Buffer overflow, %d bytes lost" % self.byte_count)


def console_read(d, buffer = console_address):
    """Read all the data we can get from the console immediately.
    If a buffer overflow occurred, raises a ConsoleOverflowError.
    """

    next_write = d.peek(buffer + 0x10000)
    next_read = d.peek(buffer + 0x10004)
    byte_count = (next_write - next_read) & 0xffffffff

    if byte_count > 0xffff:
        d.poke(buffer + 0x10004, next_write)
        raise ConsoleOverflowError(next_write, next_read)

    wr16 = next_write & 0xffff
    rd16 = next_read & 0xffff

    if wr16 > rd16:
        # More data available, and the buffer didn't wrap
        data = read_block(d, buffer + rd16, wr16 - rd16)

    elif wr16 < rd16:
        # Buffer wrapped; get it in two pieces
        data = read_block(d, buffer + rd16, 0x10000 - rd16)
        data += read_block(d, buffer, wr16)

    else:
        # No change; return without updating next_read
        assert byte_count == 0
        return ''

    # Follow the full 32-bit virtual ring position
    assert len(data) == byte_count
    d.poke(buffer + 0x10004, next_write)
    return data


def console_mainloop(d, buffer = console_address, stdout = sys.stdout, log_filename = None):
    """Main loop to forward data from the console buffer to stdout """

    log_file = log_filename and open(log_filename, 'a')
    try:
        while True:
            try:
                data = console_read(d, buffer)

                if data:
                    stdout.write(data)
                    stdout.flush()

                if log_file and data:
                    log_file.write(data)
                    log_file.flush()

            except ConsoleOverflowError, e:
                print '\n\n======== %s ========' % e

    except KeyboardInterrupt:
        return

    finally:
        if log_file:
            log_file.close()


if __name__ == "__main__":
    import remote

    if len(sys.argv) != 1:
        print "usage: %s" % sys.argv[0]
        sys.exit(1)

    console_mainloop(remote.Device())
