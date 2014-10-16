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
    wr _ fe00
    fill _10 55aa_55aa 4
    ALSO: peek, poke, read_block, watch

Assemble and disassemble ARM instructions:

    dis 3100
    asm _4 mov r3, #0x14
    dis _4 10
    ALSO: assemble, disassemble,

Or compile and invoke C++ code:

    ec 0x42
    ec ((uint16_t*)pad)[40]++
    ALSO: compile, evalc

The 'defines' and 'includes' dicts keep things you can define
in Python but use when compiling C++ and ASM snippets:

    defines['buffer'] = pad + 0x10000
    includes += ['int slide(int x) { return x << 8; }']
    ec slide(buffer)
    asm _ ldr r0, =buffer; bx lr

You can script the device's SCSI interface too:

    sc c ac              # Backdoor signature
    sc 8 ff 00 ff        # Undocumented firmware version
    ALSO: sc_eject, sc_sense, sc_read, scsi_in, scsi_out

Happy hacking!
~MeS`14
"""

from IPython import embed
from IPython.core import magic
from IPython.core.magic_arguments import magic_arguments, argument, parse_argstring
from IPython.terminal.embed import InteractiveShellEmbed

import remote, struct, sys
from hilbert import hilbert
from dump import *
from code import *
from watch import *

from binascii import a2b_hex, b2a_hex

__all__ = ['hexint', 'ShellMagics', 'peek', 'poke', 'setup_hexoutput']

# Placeholder for global Device in the IPython shell
d = None


def setup_hexoutput(ipy):
    """Configure an IPython shell to display integers in hex by default.
       You can convert to decimal with str() still.
       """
    def handler(n, p, cycle):
        return p.text("0x%x" % n)

    formatter = ipy.display_formatter.formatters['text/plain']
    formatter.for_type(int, handler)

def hexint(s):
    """This takes a bunch of weird number formats, as explained in the module docs"""
    if s.startswith('_'):
        base = pad
    else:
        base = 0
    if s.endswith('_'):
        s += '0000'
    return base + int(s.replace('_',''), 16)

def hexint_tuple(s):
    """A tuple of colon-separated hexints"""
    return tuple(hexint(i) for i in s.split(':'))

def get_signature(d):
    """Return a 12-byte signature identifying the firmware patch."""
    return d.get_signature()

def scsi_out(d, cdb, data):
    """Send a low-level SCSI packet with outgoing data."""
    return d.scsi_out(cdb, data)

def scsi_in(d, cdb, size):
    """Send a low-level SCSI packet that expects incoming data."""
    return d.scsi_in(cdb, size)

def peek(d, address):
    """Read one 32-bit word from ARM memory. Return it as an unsigned integer."""
    return d.peek(address)

def poke(d, address, word):
    """Write one 32-bit word to ARM memory."""
    return d.poke(address, word);

def peek_byte(d, address):
    """Read one 8-bit byte from ARM memory. Return it as an unsigned integer."""
    return d.peek(address)

def poke_byte(d, address, byte):
    """Write one 8-bit byte to ARM memory."""
    return d.poke(address, byte);

def blx(d, address, r0=0):
    """Invoke a function with one argument word and two return words."""
    return d.blx(address, r0)


@magic.magics_class
class ShellMagics(magic.Magics):

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('size', type=hexint, nargs='?', default=0x100, help='Address to read from. Hexadecimal. Not necessarily aligned.')

    def rd(self, line):
        """Read ARM memory block"""
        args = parse_argstring(self.rd, line)
        dump(d, args.address, args.size)

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address')
    @argument('word', type=hexint, nargs='*', help='Hex words')

    def wr(self, line, cell=''):
        """Write hex words into ARM memory"""
        args = parse_argstring(self.wr, line)
        args.word.extend(map(hexint, cell.split()))
        for i, w in enumerate(args.word):
            d.poke(args.address + i*4, w)

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address, word aligned')
    @argument('word', type=hexint, help='Hex word')
    @argument('count', type=hexint, help='Hex wordcount')

    def fill(self, line):
        """Fill contiguous words in ARM memory with the same value"""
        args = parse_argstring(self.fill, line)
        for i in range(args.count):
            d.poke(args.address + i*4, args.word)

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint_tuple, nargs='*', help='Single hex address, or a range start:end including both endpoints')

    def watch(self, line):
        """Watch memory for changes"""
        args = parse_argstring(self.watch, line)
        changes = watch_scanner(d, args.address)
        try:
            for line in watch_tabulator(changes):
                print line
        except KeyboardInterrupt:
            pass

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address')
    @argument('size', type=hexint, nargs='?', default=0x40, help='Hex byte count')

    def dis(self, line):
        """Disassemble ARM instructions"""
        args = parse_argstring(self.dis, line)
        print disassemble(d, args.address, args.size)

    @magic.line_cell_magic
    @magic_arguments()
    @argument('-b', '--base', type=int, default=0, help='First address in map')
    @argument('-s', '--scale', type=int, default=256, help='Scale in bytes per pixel')
    @argument('-w', '--width', type=int, default=4096, help='Size of square hilbert map, in pixels')
    @argument('x', type=int)
    @argument('y', type=int)

    def msl(self, line, cell=''):
        """Memsquare lookup"""
        args = parse_argstring(self.msl, line)
        print args.base, args.scale, args.width
        addr = args.base + args.scale * hilbert(args.x, args.y, args.width) 
        print "%08x" % addr

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('code', nargs='*')

    def asm(self, line, cell=''):
        """Assemble one or more ARM instructions

        NOTE that the assembled instructions will be padded to the
        nearest 32-bit word.

        Use with line or cell mode:

            %asm address op; op; op

            %%asm address
            op
            op
            op
        """
        args = parse_argstring(self.asm, line)
        assert 0 == (args.address & 3)
        code = ' '.join(args.code) + '\n' + cell
        assemble(d, args.address, code)

    @magic.line_magic
    def ec(self, line):
        """Evaluate a 32-bit C++ expression on the target"""
        print "0x%08x" % evalc(d, line)

    @magic.line_magic
    @magic_arguments()
    @argument('len', type=hexint, help='Length of input transfer')
    @argument('cdb', type=hexint, nargs='*', help='Up to 12 SCSI CDB bytes')

    def sc(self, line, cell=''):
        """Send a low-level SCSI command with a 12-byte CDB"""
        args = parse_argstring(self.sc, line)
        cdb = struct.pack('12B', *(args.cdb + [0]*12)[:12])
        data = d.scsi_in(cdb, args.len)
        sys.stdout.write(hexdump(data))

    @magic.line_magic
    def sc_eject(self, line):
        """Ask the drive to eject its disc."""
        self.sc('0 1b 0 0 0 2')

    @magic.line_magic
    def sc_sense(self, line):
        """Send a Request Sense command."""
        self.sc('20 3 0 0 0 20')

    @magic.line_magic
    @magic_arguments()
    @argument('lba', type=hexint, help='Logical Block Address')
    @argument('length', type=hexint, nargs='?', default=1, help='Transfer length, in 2kb blocks')
    @argument('-f', type=str, default=None, metavar='FILE', help='Log binary data to a file also')

    def sc_read(self, line, cell=''):
        """Read blocks from the SCSI device."""
        args = parse_argstring(self.sc_read, line)
        cdb = struct.pack('>BBIIBB', 0xA8, 0, args.lba, args.length, 0, 0)
        data = d.scsi_in(cdb, args.length * 2048)
        sys.stdout.write(hexdump(data, log_file=args.f))


if __name__ == '__main__':
    d = remote.Device()
    shell = InteractiveShellEmbed()
    setup_hexoutput(shell)
    shell.register_magics(ShellMagics)
    shell.mainloop(display_banner = __doc__)
