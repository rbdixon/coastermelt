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
from dump import *
from code import *
from hilbert import *

d = Device()

def hexint(s):
    return int(s.replace('_',''), 16)

@magics_class
class ShellMagics(Magics):

    @line_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('size', type=hexint, nargs='?', default=0x100)
    def rd(self, line):
        """Read ARM memory block

        Usage:
          %rd address [size]

        Output is hex dumped and saved as "result.log" on disk.
        All parameters in hexadecimal.
        """

        args = parse_argstring(self.rd, line)
        dump(d, args.address, args.size)

    @line_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('word', type=hexint)
    def po(self, line):
        """Poke one word into ARM memory

        Usage:
          %po address word
        """
        args = parse_argstring(self.po, line)
        d.poke(args.address, args.word)

    @line_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('word', type=hexint)
    @argument('count', type=hexint)
    def fill(self, line):
        """Fill contiguous words in ARM memory with the same value

        Usage:
          %fill address word count
        """
        args = parse_argstring(self.fill, line)
        for i in range(args.count):
            d.poke(args.address + i*4, args.word)

    @line_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('size', type=hexint, nargs='?', default=0x100)
    def dis(self, line):
        """Disassemble ARM instructions

        Usage:
          %dis address [size]
        """
        args = parse_argstring(self.dis, line)
        print disassemble(d, args.address, args.size)

    @line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('code', nargs='*')
    def asm(self, line, cell=''):
        """Assemble one or more ARM instructions

        NOTE that the assembled instructions will be padded to the
        nearest 32-bit word.

        Usage:
          %asm address code

        Or in cell mode:
          %%asm address
          code...
          code...

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
