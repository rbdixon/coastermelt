#!/usr/bin/env python
import remote, sys

# Set us up a trap for testing whether some code or data in Flash gets used.
# This sets up some memory mapping hardware to create a virtual region over
# the area we're trying to trap.
#
# This CANT CONTROL THE CONTENTS of the trap mapping yet! So anything could
# happen. Most likely, if the trapped area is in use, the firmware will crash.
# But really, anything.
#
# (It'd be great to find a better way to do this. Or to understand the mapping
# (hardware.)

__all__ = [
    'trap_set',
]


def trap_set(d, first_address, last_address):
    control = 0x4011f04
    d.poke(control, d.peek(control) & ~0x200)
    d.poke(control, d.peek(control) & ~0x2000)
    d.poke(0x4011f10, first_address)
    d.poke(0x4011f14, last_address)
    d.poke(control, d.peek(control) | 0x200)
    d.poke(control, d.peek(control) | 0x2000)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print "usage: %s first_address last_address" % sys.argv[0]
        sys.exit(1)
    trap_set(remote.Device(),
        int(sys.argv[1].replace('_',''), 16), 
        int(sys.argv[2].replace('_',''), 16))
