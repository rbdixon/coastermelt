#
# Implementation of IPython "magics", the cute shell-like
# functions you can use in the debugger shell.
#

__all__ = [ 'ShellMagics' ]

from IPython.core import magic
from IPython.core.magic_arguments import magic_arguments, argument, parse_argstring
from IPython.core.display import display
from IPython.core.error import UsageError

import struct, sys, json
from hilbert import hilbert

from shell_functions import *
from code import *
from dump import *
from mem import *
from watch import *
from console import *
from hook import *


@magic.magics_class
class ShellMagics(magic.Magics):

    def __init__(self, shell, *kw):
        magic.Magics.__init__(self, shell, *kw)

        # Hex output mode
        self.hex_mode = True
        formatter = self.shell.display_formatter.formatters['text/plain']
        formatter.for_type(int, self.int_formatter)
        formatter.for_type(long, self.int_formatter)

    def int_formatter(self, n, p, cycle):
        if not self.hex_mode:
            return p.text(str(n))
        elif n < 0:
            return p.text("-0x%x" % -n)
        else:
            return p.text("0x%x" % n)

    @magic.line_magic
    @magic_arguments()
    @argument('enabled', type=int, help='(0 | 1)')
    def hex(self, line):
        """Enable or disable hexadecimal number output mode."""
        args = parse_argstring(self.hex, line)
        self.hex_mode = args.enabled

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Address to read from')
    @argument('size', type=hexint, nargs='?', default=0x100, help='Number of bytes to read')
    def rd(self, line):
        """Read ARM memory block"""
        args = parse_argstring(self.rd, line)
        d = self.shell.user_ns['d']
        dump(d, args.address, args.size)

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Address to read from')
    @argument('wordcount', type=hexint, nargs='?', default=0x100, help='Number of words to read')
    def rdw(self, line):
        """Read ARM memory block, displaying the result as words"""
        args = parse_argstring(self.rdw, line)
        d = self.shell.user_ns['d']
        dump_words(d, args.address, args.wordcount)

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint_aligned, help='Hex address')
    @argument('word', type=hexint, nargs='*', help='Hex words')
    def wrf(self, line, cell='', va=0x500000):
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
        args = parse_argstring(self.wr, line)
        d = self.shell.user_ns['d']
        args.word.extend(map(hexint, cell.split()))
        overlay_set(d, va, len(args.word))
        poke_words(d, va, args.word)
        overlay_set(d, args.address, len(args.word))

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint_aligned, help='Hex address')
    @argument('word', type=hexint, nargs='*', help='Hex words')
    def wr(self, line, cell=''):
        """Write hex words into ARM memory"""
        args = parse_argstring(self.wr, line)
        d = self.shell.user_ns['d']
        args.word.extend(map(hexint, cell.split()))
        poke_words(d, args.address, args.word)

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint_aligned, help='Hex address')
    @argument('word', type=hexint, nargs='*', help='Hex words')
    def orr(self, line, cell=''):
        """Read/modify/write hex words into ARM memory, [mem] |= arg"""
        args = parse_argstring(self.orr, line)
        d = self.shell.user_ns['d']
        args.word.extend(map(hexint, cell.split()))
        for i, w in enumerate(args.word):
            poke_orr(d, args.address + i*4, w)

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint_aligned, help='Hex address')
    @argument('word', type=hexint, nargs='*', help='Hex words')
    def bic(self, line, cell=''):
        """Read/modify/write hex words into ARM memory, [mem] &= ~arg"""
        args = parse_argstring(self.bic, line)
        d = self.shell.user_ns['d']
        args.word.extend(map(hexint, cell.split()))
        for i, w in enumerate(args.word):
            poke_bic(d, args.address + i*4, w)

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint_aligned, help='Hex address, word aligned')
    @argument('word', type=hexint, help='Hex word')
    @argument('count', type=hexint, help='Hex wordcount')
    def fill(self, line):
        """Fill contiguous words in ARM memory with the same value.

        The current impementation uses many poke()s for a general case,
        but values which can be made of a repeating one-byte pattern
        can be filled orders of magnitude faster by using a Backdoor
        command.
        """
        args = parse_argstring(self.fill, line)
        d = self.shell.user_ns['d']
        d.fill(args.address, args.word, args.count)

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
        d = self.shell.user_ns['d']
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
        d = self.shell.user_ns['d']
        substr = ''.join(map(chr, args.byte))
        for address, before, after in search_block(d, args.address, args.size, substr):
            print "%08x %52s [ %s ] %s" % (address, hexstr(before), hexstr(substr), hexstr(after))

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint_aligned, nargs='?')
    @argument('wordcount', type=hexint, nargs='?', default=1, help='Number of words to remap')
    def ovl(self, line):
        """Position a movable RAM overlay at the indicated virtual address range.
        With no parameters, shows the current location of the RAM.

        It can go anywhere in the first 8MB. So, put it between 20_ and 80_, fill it with
        tasty data, then move it overtop of flash. Or see the wrf / asmf commands to do this
        quickly in one step.
        """
        args = parse_argstring(self.ovl, line)
        d = self.shell.user_ns['d']
        if args.address is None:
            print "overlay: base = %x, wordcount = %x" % overlay_get(d)
        else:
            overlay_set(d, args.address, args.wordcount)

    @magic.line_magic
    @magic_arguments()
    @argument('address', type=hexint, help='Hex address')
    @argument('size', type=hexint, nargs='?', default=0x40, help='Hex byte count')
    @argument('-a', '--arm', action='store_true', help='Use 32-bit ARM mode instead of the default Thumb')
    def dis(self, line):
        """Disassemble ARM instructions"""
        args = parse_argstring(self.dis, line)
        d = self.shell.user_ns['d']
        print disassemble(d, args.address, args.size, thumb = not args.arm)

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
        return int(args.base + args.scale * hilbert(args.x, args.y, args.width))

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint_aligned)
    @argument('code', nargs='*')
    def asm(self, line, cell=''):
        """Assemble one or more ARM instructions"""
        args = parse_argstring(self.asm, line)
        d = self.shell.user_ns['d']
        code = ' '.join(args.code) + '\n' + cell
        try:
            assemble(d, args.address, code, defines=all_defines())
        except CodeError, e:
            raise UsageError(str(e))

    @magic.line_cell_magic
    @magic_arguments()
    @argument('address', type=hexint_aligned)
    @argument('code', nargs='*')
    def asmf(self, line, cell='', va=0x500000):
        """Assemble ARM instructions into a patch we instantly overlay onto Flash.
        Combines the 'asm' and 'wrf' commands.
        """
        args = parse_argstring(self.asmf, line)
        d = self.shell.user_ns['d']
        code = ' '.join(args.code) + '\n' + cell
        data = assemble_string(args.address, code, defines=all_defines())

        # Write assembled code to the virtual apping
        words = words_from_string(data)
        overlay_set(d, va, len(words))
        poke_words(d, va, words)
        overlay_set(d, args.address, len(words))

    @magic.line_cell_magic
    def ec(self, line, cell='', address=pad+0x100):
        """Evaluate a 32-bit C++ expression on the target"""
        d = self.shell.user_ns['d']
        try:
            return evalc(d, line + cell, defines=all_defines(), address=address, verbose=True)
        except CodeError, e:
            raise UsageError(str(e))

    @magic.line_cell_magic
    def ecc(self, line, cell='', address=pad+0x100):
        """Evaluate a 32-bit C++ expression on the target, and immediately start a console"""
        d = self.shell.user_ns['d']
        try:
            return_value = evalc(d, line + cell, defines=all_defines(), address=address, verbose=True)
        except CodeError, e:
            raise UsageError(str(e))

        if return_value is not None:
            display(return_value)
        console_mainloop(d)

    @magic.line_magic
    def ea(self, line, address=pad+0x100, thumb=False):
        """Evaluate an assembly one-liner

        This is an even more reduced and simplified counterpart to %asm,
        like the %ec for assembly.

        - We default to ARM instead of Thumb, since code density is
          not important and we want access to all instructions.
          For thumb, see the %tea variant.

        - Automatically adds a function preamble that saves all registers
          except r0 and r1, which are available for returns.

        - Bridges shell variable r0 on input, and r0-r1 on output.

        - Calls the routine.
        """
        d = self.shell.user_ns['d']
        r0 = int(self.shell.user_ns.get('r0') or 0)

        try:
            r0, r1 = evalasm(d, line, r0, defines=all_defines(), address=address, thumb=thumb)
        except CodeError, e:
            raise UsageError(str(e))

        self.shell.user_ns['r0'] = r0
        self.shell.user_ns['r1'] = r1
        print "  r0 = 0x%08x, r1 = 0x%08x" % (r0, r1)

    @magic.line_magic
    def tea(self, line, address=pad+0x100):
        """Evaluate an assembly one-liner in Thumb mode
        This is a Thumb-mode variant of %ea
        """
        return self.ea(line, address, thumb=True)

    @magic.line_cell_magic
    @magic_arguments()
    @argument('hook_address', type=hexint)
    @argument('handler_address', nargs='?', type=hexint_aligned, default=pad+0x100)
    @argument('-q', '--quiet', action='store_true', help="Just install the hook, don't talk about it")
    @argument('-r', '--reset', action='store_true', help="Do a %%reset before starting")
    @argument('-c', '--console', action='store_true', help='Immediately launch into a %%console after installing')
    @argument('-f', '--console_file', type=str, default=None, metavar='FILE', help='Append console output to a text file')
    @argument('-b', '--console_buffer', type=hexint_aligned, metavar='HEX', default=console_address, help='Specify a different address for the console_buffer_t data structure')
    @argument('-d', '--delay', type=float, default=None, metavar='SEC', help='Add a delay loop to the default hook')
    @argument('-m', '--message', type=str, default=None, help='Message to log in the default hook')
    def hook(self, line, cell=None):
        """Inject a C++ hook into Thumb code executing from Flash memory.
 
        In line mode, this uses the "default hook" which logs to the console.

        In cell mode, you can write C++ statements that interact with the
        machine state at just prior to executing the hooked instruction. All
        ARM registers are available to read and write, both as named C++
        variables and as a regs[] array.

        The hook and a corresponding interrupt handler are installed at
        handler_address, defaulting to _100.  This command uses the %overlay
        to position an "svc" instruction at the hook location, and the
        generated svc interrupt handler includes a relocated copy of the
        hooked instruction and the necessary glue to get in and out of C++ code.
        """
        args = parse_argstring(self.hook, line)
        d = self.shell.user_ns['d']

        if not cell:
            # Default hook, including our command line as a trace message
            message = args.message or ('%%hook %x' % args.hook_address)
            cell = 'default_hook(regs, %s)' % json.dumps(message)
            if args.delay:
                cell = '%s; SysTime::wait_ms(%d)' % (cell, args.delay * 1000)

        else:
            if args.message:
                raise UsageError('--message only applies when using the default hook')
            if args.delay:
                raise UsageError('--delay only applies when using the default hook')

        if args.reset:
            d.reset()
        try:
            overlay_hook(d, args.hook_address, cell,
                defines = all_defines(),
                handler_address = args.handler_address,
                verbose = not args.quiet)
        except CodeError, e:
            raise UsageError(str(e))

        if args.console:
            console_mainloop(d, buffer=args.console_buffer, log_filename=args.console_file)

    @magic.line_magic
    @magic_arguments()
    @argument('buffer_address', type=hexint_aligned, nargs='?', default=console_address, help='Specify a different address for the console_buffer_t data structure')
    @argument('-f', type=str, default=None, metavar='FILE', help='Append output to a text file')
    def console(self, line):
        """Read console output until KeyboardInterrupt.
        Optionally append the output to a file also.
        To write to this console from C++, use the functions in console.h
        """
        args = parse_argstring(self.console, line)
        d = self.shell.user_ns['d']
        console_mainloop(d, buffer=args.buffer_address, log_filename=args.f)

    @magic.line_cell_magic
    def fc(self, line, cell=None):
        """Define or replace a C++ include definition

        - Without any argument, lists all existing definitions
        - In line mode, stores a one-line function, variable, or structure definition
        - In block mode, stores a multiline function, struct, or class definition

        The key for the includes ditcionary is automatically chosen. In cell mode,
        it's a whitespace-normalized version of the header line. In line mode, it
        extends until the first '{' or '=' character.

        The underlying dictionary is 'includes'. You can remove all includes with:

            includes.clear()

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
            body = "%s {\n%s;\n};\n" % (line, cell)
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
            includes[dict_key] = line + ';'

    @magic.line_magic
    @magic_arguments()
    @argument('len', type=hexint, help='Length of input transfer')
    @argument('cdb', type=hexint, nargs='*', help='Up to 12 SCSI CDB bytes')
    def sc(self, line, cell=''):
        """Send a low-level SCSI command with a 12-byte CDB"""
        args = parse_argstring(self.sc, line)
        d = self.shell.user_ns['d']
        cdb = ''.join(map(chr, args.cdb))
        data = scsi_in(d, cdb, args.len)
        sys.stdout.write(hexdump(data))

    @magic.line_magic
    @magic_arguments()
    @argument('-a', '--arm', action='store_true', help='Try to reset the ARM CPU as well')
    def reset(self, line=''):
        """Reset and reopen the USB interface."""
        args = parse_argstring(self.reset, line)
        d = self.shell.user_ns['d']
        d.reset()
        if args.arm:
            reset_arm(d)

    @magic.line_magic
    def eject(self, line=''):
        """Ask the drive to eject its disc."""
        self.sc('0 1b 0 0 0 2')

    @magic.line_magic
    def sc_sense(self, line=''):
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
        d = self.shell.user_ns['d']
        cdb = struct.pack('>BBII', 0xA8, 0, args.lba, args.length)
        data = scsi_in(d, cdb, args.length * 2048)
        sys.stdout.write(hexdump(data, log_file=args.f))
