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

import sys, time, code, dump


# Our ring buffer is 64 KiB. The default location comes from
# more guesswork and memsquares. It's 1MB above the default
# pad, still in an area of DRAM that seems very lightly used.

console_address = 0x1e50000

# If console.h appears in shell_builtins.h, we should be sure
# the console_address is always available even in code compiled
# without the whole shell namespace.

code.defines['console_address'] = console_address


class ConsoleOverflowError(Exception):
    """Raised by console_read() in case of FIFO buffer overflow"""
    def __init__(self, next_write, next_read):
        self.next_write = next_write
        self.next_read = next_read
        self.byte_count = (next_write - next_read) & 0xffffffff
        self.unsynchronized = self.byte_count > 0x1000000
        if self.unsynchronized:
            Exception.__init__(self, "Console wasn't synchronized. Previous data lost")
        else:
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
        data = dump.read_block(d, buffer + rd16, wr16 - rd16)

    elif wr16 < rd16:
        # Buffer wrapped; get it in two pieces
        data = dump.read_block(d, buffer + rd16, 0x10000 - rd16)
        data += dump.read_block(d, buffer, wr16)

    else:
        # No change; return without updating next_read
        assert byte_count == 0
        return ''

    # Follow the full 32-bit virtual ring position
    assert len(data) == byte_count
    d.poke(buffer + 0x10004, next_write)
    return data


def console_mainloop(d,
    buffer = console_address,
    stdout = sys.stdout,
    log_filename = None,
    spinner_interval = 1.0 / 8
    ):
    """Main loop to forward data from the console buffer to stdout.
    Supports appending to a text log file.
    Also draws a small ASCII spinner to let you know the poll loop is running.
    If it stops, something's crashed.
    """

    log_file = log_filename and open(log_filename, 'a')
    output_timestamp = time.time()
    spinner_chars = '-\\|/'
    spinner_count = 0
    spinner_visible = False

    try:
        while True:
            try:
                data = console_read(d, buffer)
                now = time.time()

                if data:
                    if spinner_visible:
                        stdout.write('\b')
                        spinner_visible = False
                    stdout.write(data)
                    stdout.flush()
                    output_timestamp = now

                    if log_file:
                        log_file.write(data)
                        log_file.flush()

                elif spinner_interval and now > output_timestamp + spinner_interval:

                    if spinner_visible:
                        stdout.write('\b')

                    spinner_visible = True
                    spinner_count = (spinner_count + 1) % len(spinner_chars)
                    stdout.write(spinner_chars[spinner_count])
                    stdout.flush()
                    output_timestamp = now

            except IOError:
                # The device layer will already complain for us.
                # Wait a tiny bit to let the device cool off...
                time.sleep(0.1)
                continue

            except ConsoleOverflowError, e:
                # Warn loudly that we missed some data
                sys.stderr.write('\n\n======== %s ========\n\n' % e)

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
