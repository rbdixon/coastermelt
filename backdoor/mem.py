#!/usr/bin/env python
import remote

# Functions for poking at the MT1939's memory management hardware.

__all__ = [
    'overlay_set', 'overlay_get'
]


def overlay_set(d, address, wordcount = 1):
    """Set up a RAM overlay region, up to 4kB, mappable anywhere in the low 8MB."""

    if address & 3:
        raise ValueError("Overlay mapping address must be word aligned")

    control = 0x4011f04

    d.poke(control, d.peek(control) & ~0x200)
    d.poke(control, d.peek(control) & ~0x2000)
    d.poke(control + 0x0c, address)
    d.poke(control + 0x10, address + wordcount*4 - 1)
    d.poke(control, d.peek(control) | 0x200)
    d.poke(control, d.peek(control) | 0x2000)


def overlay_get(d):
    """Get the current extent of the RAM overlay"""

    control = 0x4011f04
    address = d.peek(control + 0x0c)
    limit = d.peek(control + 0x10)

    return (address, (limit - address + 3) / 4)
