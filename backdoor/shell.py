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
    ALSO: rdw, orr, bic, fill, watch, find
          ovl, wrf
          peek, poke, read_block

Assemble and disassemble ARM instructions:

    dis 3100
    asm _4 mov r3, #0x14
    dis _4 10
    ALSO: asmf, assemble, disassemble, blx

Or compile and invoke C++ code:

    ec 0x42
    ec ((uint16_t*)pad)[40]++
    ALSO: compile, evalc

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

Happy hacking!
~MeS`14
"""

from IPython import embed
from IPython.core import magic
from IPython.core.magic_arguments import magic_arguments, argument, parse_argstring
from IPython.terminal.embed import InteractiveShellEmbed

# Stuff we need, but also keep the shell namespace in mind here
import remote, struct, sys, subprocess
from hilbert import hilbert
from dump import *
from code import *
from watch import *
from mem import *

# These are super handy in the shell
import binascii, random
from binascii import a2b_hex, b2a_hex
from random import randint

__all__ = ['hexint', 'ShellMagics', 'peek', 'poke', 'setup_hexoutput']

# Placeholder for global Device in the IPython shell.
# Our Python code uses the convention of taking a device as a first argument,
# which we'll need to support multiple devices or to do weird proxy things.
# But here in the shell it's handy to have the concept of a global device.
d = None


def setup_hexoutput(ipy):
    """Configure an IPython shell to display integers in hex by default.
       You can convert to decimal with str() still.
       """
    def handler(n, p, cycle):
        return p.text("0x%x" % n)

    formatter = ipy.display_formatter.formatters['text/plain']
    formatter.for_type(int, handler)

def hexstr(s):
    """Compact inline hexdump"""
    return ' '.join(['%02x' % ord(b) for b in s])

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

def all_defines():
    """Return a merged dictionary of all defines: First the implicit environment
    of the shell's globals, then the explicit environment of the 'defines' dict.
    """
    d = dict(globals())
    d.update(defines)
    return d


@magic.magics_class
class ShellMagics(magic.Magics):


    ############################################################ Memory


    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Address to read from. Hexadecimal. Not necessarily aligned')
    @argument('size', type=hexint, nargs='?', default=0x100, help='Number of bytes to read')
    def rd(self, line):
        """Read ARM memory block"""
        args = parse_argstring(self.rd, line)
        dump(d, args.address, args.size)

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Address to read from')
    @argument('wordcount', type=hexint, nargs='?', default=0x100, help='Number of words to read')
    def rdw(self, line):
        """Read ARM memory block, displaying the result as words"""
        args = parse_argstring(self.rdw, line)
        dump_words(d, args.address, args.wordcount)

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address')
    @argument('word', type=hexint, nargs='*', help='Hex words')
    def wrf(self, line, cell=''):
        """Write hex words into the RAM overlay region, then instantly move the overlay into place.
           It's a sneaky trick that looks like a temporary way to write to Flash.

           For example, this patches the signature as it appears in the
           current version of the Backdoor patch itself. Normally this can't
           be modified, since it's in flash:

            : rd c9720 50
            000c9720  ac 42 4c 58 ac 6c 6f 63 ac 65 65 42 ac 6f 6b 42   .BLX.loc.eeB.okB
            000c9730  e6 0c 00 02 a8 00 04 04 c0 46 c0 46 c0 46 c0 46   .........F.F.F.F
            000c9740  7e 4d 65 53 60 31 34 20 76 2e 30 32 20 20 20 20   ~MeS`14 v.02    
            000c9750  53 1c 0b 60 16 70 0a 68 53 1c 0b 60 16 70 0a 68   S..`.p.hS..`.p.h
            000c9760  53 1c 0b 60 16 70 0a 68 53 1c 0b 60 16 70 29 88   S..`.p.hS..`.p).

            : wrf c9740 55555555

            : rd c9720 50
            000c9720  ac 42 4c 58 ac 6c 6f 63 ac 65 65 42 ac 6f 6b 42   .BLX.loc.eeB.okB
            000c9730  e6 0c 00 02 a8 00 04 04 c0 46 c0 46 c0 46 c0 46   .........F.F.F.F
            000c9740  55 55 55 55 60 31 34 20 76 2e 30 32 20 20 20 20   UUUU`14 v.02    
            000c9750  53 1c 0b 60 16 70 0a 68 53 1c 0b 60 16 70 0a 68   S..`.p.hS..`.p.h
            000c9760  53 1c 0b 60 16 70 0a 68 53 1c 0b 60 16 70 29 88   S..`.p.hS..`.p).

            : sc c ac
            00000000  55 55 55 55 60 31 34 20 76 2e 30 32               UUUU`14 v.02

           """
        va = 0x500000
        args = parse_argstring(self.wr, line)
        args.word.extend(map(hexint, cell.split()))
        overlay_set(d, va, len(args.word))
        for i, w in enumerate(args.word):
            d.poke(va + i*4, w)
        overlay_set(d, args.address, len(args.word))

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

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address')
    @argument('word', type=hexint, nargs='*', help='Hex words')
    def orr(self, line, cell=''):
        """Read/modify/write hex words into ARM memory, [mem] |= arg"""
        args = parse_argstring(self.orr, line)
        args.word.extend(map(hexint, cell.split()))
        for i, w in enumerate(args.word):
            a = args.address + i*4
            d.poke(a, d.peek(a) | w)

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address')
    @argument('word', type=hexint, nargs='*', help='Hex words')
    def bic(self, line, cell=''):
        """Read/modify/write hex words into ARM memory, [mem] &= ~arg"""
        args = parse_argstring(self.bic, line)
        args.word.extend(map(hexint, cell.split()))
        for i, w in enumerate(args.word):
            a = args.address + i*4
            d.poke(a, d.peek(a) | w)

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
    @argument('address', type=hexint_tuple, nargs='+', help='Single hex address, or a range start:end including both endpoints')
    def watch(self, line):
        """Watch memory for changes, shows the results in an ASCII data table.

        To use the results programmatically, see the watch_scanner() and
        watch_tabulator() functions.

        Keeps running until you kill it with a KeyboardInterrupt.
        """
        args = parse_argstring(self.watch, line)
        changes = watch_scanner(d, args.address)
        try:
            for line in watch_tabulator(changes):
                print line
        except KeyboardInterrupt:
            pass

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='First address to search')
    @argument('size', type=hexint, help='Size of region to search')
    @argument('byte', type=hexint, nargs='+', help='List of bytes to search for, at any alignment')
    def find(self, line):
        """Read ARM memory block, and look for all occurrences of a byte sequence"""
        args = parse_argstring(self.find, line)
        substr = ''.join(map(chr, args.byte))
        for address, before, after in search_block(d, args.address, args.size, substr):
            print "%08x %52s [ %s ] %s" % (address, hexstr(before), hexstr(substr), hexstr(after))


    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, nargs='?')
    @argument('wordcount', type=hexint, nargs='?', default=1, help='Number of words to remap')
    def ovl(self, line):
        """Position a movable RAM overlay at the indicated virtual address range.
        With no parameters, shows the current location of the RAM.

        It can go anywhere in the first 8MB. So, put it between 20_ and 80_, fill it with
        tasty data, then move it overtop of flash. Or see the wrf / asmf commands to do this
        quickly in one step.
        """
        args = parse_argstring(self.ovl, line)
        if args.address is None:
            print "overlay: base = %x, wordcount = %x" % overlay_get(d)
        else:
            overlay_set(d, args.address, args.wordcount)


    ############################################################ Code


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
        code = ' '.join(args.code) + '\n' + cell

        try:
            assemble(d, args.address, code, defines=all_defines())

        except subprocess.CalledProcessError:
            # The errors can be overwhelming from both python and the assembler,
            # so quiet the python errors and just let gcc talk.
            pass

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint)
    @argument('code', nargs='*')
    def asmf(self, line, cell=''):
        """Assemble ARM instructions into a patch we instantly overlay onto Flash.
        Combines the 'asm' and 'wrf' commands.
        """

        va = 0x500000
        args = parse_argstring(self.asmf, line)
        code = ' '.join(args.code) + '\n' + cell

        try:
            data = assemble_string(d, args.address, code, defines=all_defines())
        except subprocess.CalledProcessError:
            return

        # Write assembled code to the virtual apping
        words = struct.unpack('<%dI' % (len(data)/4), data)
        overlay_set(d, va, len(words))
        for i, word in enumerate(words):
            d.poke(va + 4*i, word)
        overlay_set(d, args.address, len(words))

    @magic.line_magic
    def ec(self, line):
        """Evaluate a 32-bit C++ expresdesion on the target"""

        try:
            print "0x%08x" % evalc(d, line, defines=all_defines())

        except subprocess.CalledProcessError:
            # The errors can be overwhelming from both python and the compiler,
            # so quiet the python errors and just let gcc talk.
            pass

    @magic.line_cell_magic
    def fc(self, line, cell=None):
        """Define or replace a C++ include definition

        - Without any argument, lists all existing definitions
        - In line mode, stores a one-line function, variable, or structure definition
        - In block mode, stores a multiline function, struct, or class definition

        The key for the includes ditcionary is automatically chosen. In cell mode,
        it's a whitespace-normalized version of the header line. In line mode, it
        extends until the first '{' or '=' character.

        Example:

            fill _100 1 100
            wr _100 abcdef
            rd _100

            fc uint32_t* words = (uint32_t*) buffer
            buffer = pad + 0x100
            ec words[0]

            %%fc uint32_t sum(uint32_t* values, int count)
            uint32_t result = 0;
            while (count--) {
                result += *(values++);
            }
            return result;

            ec sum(words, 10)

        It's also worth noting that include files are re-read every time you evaluate
        a C++ expression, so a command like this will allow you to edit code in one
        window and interactively run expressions in another:

            fc #include "my_functions.h"


        """
        if cell:
            dict_key = ' '.join(line.split())
            body = "%s {\n%s\n;};\n" % (line, cell)
            includes[dict_key] = body

        elif not line.strip():
            for key, value in includes.items():
                print ' '.join([
                    '=' * 10,
                    key,
                    '=' * max(0, 70 - len(key))
                ])
                print value
                print

        else:
            dict_key = ' '.join(line.split()).split('{')[0].split('=')[0]
            body = line + '\n;'
            includes[dict_key] = body


    ############################################################ SCSI


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
    def reset(self, line):
        """Reset and reopen the device."""
        d.reset()

    @magic.line_magic
    def eject(self, line):
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
