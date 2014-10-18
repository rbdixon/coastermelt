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
          ovl, wrf
          peek, poke, read_block

Disassemble, assemble, and invoke ARM assembly:

    dis 3100
    asm _4 mov r3, #0x14
    dis _4 10
    ea mrs r0, cpsr; ldr r1, =0xaa000000; orr r0, r1
    ALSO: asmf, assemble, disassemble, blx, evalasm

Or compile and invoke C++ code:

    ec 0x42
    ec ((uint16_t*)pad)[40]++
    ALSO: compile, evalc, hook

You can use integer globals in C++ and ASM snippets, or
define/replace a named C++ function:

    fc uint32_t* words = (uint32_t*) buffer
    buffer = pad + 0x100
    ec words[0] += 0x50
    asm _ ldr r0, =buffer; bx lr
    ALSO: includes, %%fc

You can script the device's SCSI interface too:

    sc c ac              # Backdoor signature
    sc 8 ff 00 ff        # Undocumented firmware version
    ALSO: reset, eject, sc_sense, sc_read, scsi_in, scsi_out

Happy hacking!         -- Type 'thing?' for info on 'thing'
~MeS`14                   or '?' to learn about IPython
"""

# This module becomes the shell namespace.
# Put some useful things in it.

import struct, sys, os, re

import shell_functions
from shell_functions import *

import shell_magics
from shell_magics import *

import dump
from dump import *

import code
from code import *

import mem
from mem import *

from watch import *
from hilbert import hilbert

import remote
from remote import Device

import IPython
import IPython.terminal.embed

import binascii
from binascii import a2b_hex, b2a_hex

import random
from random import randint


if __name__ == '__main__':
    # Create the global device (required by our 'magic' commands)
    shell_magics.d = Device()

    # Make a customized IPython shell
    ipy = IPython.terminal.embed.InteractiveShellEmbed()
    setup_hexoutput(ipy)
    ipy.register_magics(ShellMagics)

    # Also set up some more aliases :)
    ipy.alias_manager.define_alias('git', 'git')
    ipy.alias_manager.define_alias('make', 'make')

    ipy.mainloop(display_banner = __doc__)
