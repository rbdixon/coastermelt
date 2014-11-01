# Functions for poking at the MT1939's miscellaneous memory-mapped hardware
# and memory-mapped memory-mapping hardware.

__all__ = [
    'poke_orr', 'poke_bic', 'poke_bit',
    'ivt_find_target', 'ivt_set', 'ivt_get',
    'overlay_set', 'overlay_get', 'overlay_assemble',
    'reset_arm',
]

from code import *
from dump import *


def poke_orr(d, address, word):
    """Read-modify-write sequence to bitwise OR, named after the ARM instruction"""
    word = d.peek(address) | word
    d.poke(address, word)
    return word


def poke_bic(d, address, word):
    """Read-modify-write to bitwise AND with the inverse, named after the ARM instruction"""
    word = d.peek(address) & ~word
    d.poke(address, word)
    return word


def poke_bit(d, address, mask, bit):
    """Read-modify-write, bic/orr based on 'bit'"""
    return (poke_orr, poke_bic)[not bit](d, address, mask)


def ivt_find_target(d, address):
    """Disassemble an instruction in the IVT to locate the jump target.
    Returns None if there's no corresponding IVT target
    """
    text = disassemble(d, address, 4, thumb=False)
    return ldrpc_source_address(disassembly_lines(text)[0])


def ivt_get(d, address):
    """Read the target address of a long jump in the interrupt vector table
    Returns None if there's no corresponding IVT target
    """
    addr = ivt_find_target(d, address)
    if addr:
        return d.peek(addr)


def ivt_set(d, address, handler):
    """Change the target address of a jump in the interrupt vector table.
    Assumes the table is in RAM.
    """
    d.poke(ivt_find_target(d, address), handler)


def overlay_set(d, address, wordcount = 1):
    """Set up a RAM overlay region, up to 4kB, mappable anywhere in the low 8MB.
    If address is None, disables the overlay.
    """
    control = 0x4011f04
    poke_bic(d, control, 0x200)
    poke_bic(d, control, 0x2000)
    if address is None:
        d.poke(control + 0x0c, 0xffffffff)
        d.poke(control + 0x10, 0x00000000)
    else:
        if address & 3:
            raise ValueError("Overlay mapping address must be word aligned")
        d.poke(control + 0x0c, address)
        d.poke(control + 0x10, address + wordcount*4 - 1)
        poke_orr(d, control, 0x200)
        poke_orr(d, control, 0x2000)


def overlay_get(d):
    """Get the current extent of the RAM overlay.
    Returns an (address, wordcount) tuple.
    """
    control = 0x4011f04
    address = d.peek(control + 0x0c)
    limit = d.peek(control + 0x10)
    return (address, (limit - address + 3) / 4)


def overlay_assemble(d, address, code, defines=defines, va=0x500000):
    """Assemble some code and patch it into memory using an overlay.
    Returns the length of the assembled code, in bytes.
    """

    data = assemble_string(address, code, defines=defines)

    # Write assembled code to the virtual apping
    words = words_from_string(data)
    overlay_set(d, va, len(words))
    poke_words(d, va, words)
    overlay_set(d, address, len(words))

    return len(words)


def reset_arm(d):
    """Provoke a system reset by calling the reset vector"""
    try:
        d.blx(0)
    except IOError:
        # Expect that SCSI command to fail. Reconnect.
        d.reset()
