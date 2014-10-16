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
# What does it do right now? It seems to pull up to 0x1000 bytes from 0xcfbe4
# in flash. If the mapping is longer, the region repeats. The mapping can go
# anywhere in the low 8MB of virtual address space.
#
# With the minimum length, you get a pop {r3-r7, pc} instruction you can put
# anywhere in flash. You can use it to crash some functions. Others, it will
# return early.

__all__ = [
    'trap_set',
]


def trap_set(d, address, wordcount = 1):
    # pulling from cfbe4

    control = 0x4011f04
    d.poke(control, d.peek(control) & ~0x200)
    d.poke(control, d.peek(control) & ~0x2000)
    d.poke(control + 0x0c, address)
    d.poke(control + 0x10, address + wordcount*4 - 1)
    d.poke(control, d.peek(control) | 0x200)
    d.poke(control, d.peek(control) | 0x2000)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print "usage: %s address wordcount" % sys.argv[0]
        sys.exit(1)
    trap_set(remote.Device(),
        int(sys.argv[1].replace('_',''), 16), 
        int(sys.argv[2].replace('_',''), 16))
