#!/usr/bin/env python
"""
                        __                             __ __   
.----.-----.---.-.-----|  |_.-----.----.--------.-----|  |  |_ 
|  __|  _  |  _  |__ --|   _|  -__|   _|        |  -__|  |   _|
|____|_____|___._|_____|____|_____|__| |__|__|__|_____|__|____|
--IPython Shell for Interactive Exploration--------------------

Read, write, or fill ARM memory. Numbers are hex. Trailing _ is
short for 0000, leading _ adds 'pad' scratchpad RAM offset.
Internal _ are ignored so you can use them as separators.

    rd 1ff_ 100
    wr _ 1febb
    ALSO: rdw, orr, bic, fill, watch, find
          ovl, wrf, peek, poke, read_block

Disassemble, assemble, and invoke ARM assembly:

    dis 3100
    asm _4 mov r3, #0x14
    dis _4 10
    ea mrs r0, cpsr; ldr r1, =0xaa000000; orr r0, r1
    ALSO: asmf, tea, blx
          assemble, disassemble, evalasm

Or compile and invoke C++ code:

    ec 0x42
    ec ((uint16_t*)pad)[40]++
    ALSO: console, ecc, hook, compile, evalc

You can use integer globals in C++ and ASM snippets,
or define/replace a named C++ function:

    fc uint32_t* words = (uint32_t*) buffer
    buffer = pad + 0x100
    ec words[0] += 0x50
    asm _ ldr r0, =buffer; bx lr

You can script the device's SCSI interface too:

    sc c ac              # Backdoor signature
    sc 8 ff 00 ff        # Undocumented firmware version
    ALSO: reset, eject, sc_sense, sc_read, scsi_in, scsi_out

Happy hacking!    -- Type 'thing?' for help on 'thing' or
~MeS`14              '?' for IPython, '%h' for this again.
"""

from IPython.terminal.embed import InteractiveShellEmbed
from shell_magics import ShellMagics
from remote import Device
import shell_namespace

# Make a global device, but only give it to the user namespace
shell_namespace.d = Device()

# Make a shell that feels like a debugger
ipy = InteractiveShellEmbed(user_ns = shell_namespace.__dict__)
shell_namespace.ipy = ipy
ipy.register_magics(ShellMagics)
ipy.register_magic_function(lambda _: ipy.write(__doc__), magic_name='h')
ipy.alias_manager.define_alias('git', 'git')
ipy.alias_manager.define_alias('make', 'make')

# Hello, tiny world
ipy.mainloop(display_banner = __doc__)
