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
# What does it do right now? It seems to pull 0x1000 bytes from 0xcfbe4 in flash.
# If the mapping is longer, the region repeats. The mapping can go anywhere in
# the low 8MB of virtual address space.
#
# Right now, here's what you get:
#    
#    In []: trap 7f_ 100
#    
#    In []: dis 7f_
#    007f0000    pop {r3, r4, r5, r6, r7, pc}
#    007f0002    push    {r0, r1, r4, r5, r6, r7, lr}
#    007f0004    movs    r7, r0
#    007f0006    movs    r0, #192    ; 0xc0
#    007f0008    sub sp, #4
#    007f000a    blx 0x007206d8
#    007f000e    ldr r2, [pc, #964]  ; (0x007f03d4)
#    007f0010    ldr r1, [r2, #4]
#    007f0012    asrs    r3, r2, #18
#    007f0014    orrs    r1, r3
#    007f0016    str r1, [r2, #4]
#    007f0018    ldr r1, [r2, #4]
#    007f001a    asrs    r3, r2, #17
#    007f001c    orrs    r1, r3
#
# So, in short, right now the "trap" implementation replaces any instruction
# you like with an instruction that copies:
#
#    r3 = [sp + 0]
#    r4 = [sp + 4]
#    r5 = [sp + 8]
#    r6 = [sp + c]
#    r7 = [sp + 10]
#    pc = [sp + 14]
#
# How about that sp+14?
#

__all__ = [
    'trap_set',
]


def trap_set(d, address, wordcount):
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
