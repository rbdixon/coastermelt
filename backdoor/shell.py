#!/usr/bin/env python
#
# Interactive reverse engineering shell using IPython, with lots of terse
# "magic" functions to give a more debugger-like interface.
#

from IPython import embed
from IPython.core.magic import Magics, magics_class, line_magic, line_cell_magic
from IPython.core.magic_arguments import magic_arguments, argument, parse_argstring
from IPython.terminal.embed import InteractiveShellEmbed

from remote import Device
from hilbert import hilbert
from dump import *
from code import *

d = Device()

def hexint(s):
    return int(s.replace('_',''), 16)

@magics_class
class ShellMagics(Magics):

    @line_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('size', type=hexint, nargs='?', default=0x100,
        help='Address to read from. Hexadecimal. Not necessarily aligned.')
    def rd(self, line):
        """Read ARM memory block"""
        args = parse_argstring(self.rd, line)
        dump(d, args.address, args.size)

    @line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address')
    @argument('word', type=hexint, help='Hex word')
    def po(self, line):
        """Poke one word into ARM memory"""
        args = parse_argstring(self.po, line)
        d.poke(args.address, args.word)

    @line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address, word aligned')
    @argument('word', type=hexint, help='Hex word')
    @argument('count', type=hexint, help='Hex wordcount')
    def fill(self, line):
        """Fill contiguous words in ARM memory with the same value"""
        args = parse_argstring(self.fill, line)
        for i in range(args.count):
            d.poke(args.address + i*4, args.word)

    @line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address')
    @argument('size', type=hexint, nargs='?', default=0x100,
        help='Hex byte count')
    def dis(self, line):
        """Disassemble ARM instructions"""
        args = parse_argstring(self.dis, line)
        print disassemble(d, args.address, args.size)

    @line_cell_magic
    @magic_arguments()
    @argument('-b', '--base', type=int, default=0,
        help='First address in map')
    @argument('-s', '--scale', type=int, default=256,
        help='Scale in bytes per pixel')
    @argument('-w', '--width', type=int, default=4096,
        help='Size of square hilbert map, in pixels')
    @argument('x', type=int)
    @argument('y', type=int)
    def msl(self, line, cell=''):
        """Memsquare lookup"""
        args = parse_argstring(self.msl, line)
        print args.base, args.scale, args.width
        addr = args.base + args.scale * hilbert(args.x, args.y, args.width) 
        print "%08x" % addr

    @line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('code', nargs='*')
    def asm(self, line, cell=''):
        """Assemble one or more ARM instructions

        NOTE that the assembled instructions will be padded to the
        nearest 32-bit word.

        Use with line or cell mode:

            %asm address line

            %%asm address
            line..
            line..

        """
        args = parse_argstring(self.asm, line)
        assert 0 == (args.address & 3)
        code = ' '.join(args.code) + '\n' + cell
        assemble(d, args.address, code)

    @line_magic
    def ec(self, line):
        """Evaluate a 32-bit C++ expression on the target"""
        print "0x%08x" % evalc(d, line)


if __name__ == '__main__':
    shell = InteractiveShellEmbed()
    shell.register_magics(ShellMagics)
    shell()
