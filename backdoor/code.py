#!/usr/bin/env python

# Tools for working with code on the backdoored target machine.
# Assemble, disassemble, and compile. Requires an ARM cross-compiler.

CC      = 'arm-none-eabi-gcc'
OBJCOPY = 'arm-none-eabi-objcopy'
OBJDUMP = 'arm-none-eabi-objdump'

__all__ = [
    # Code globals
    'pad', 'defines', 'includes',

    # Compiler
    'assemble_string', 'assemble', 'evalasm',
    'compile_string', 'compile', 'evalc',
    'compile_library_string', 'compile_library',
    'CodeError',

    # Disassembler
    'disassemble_string', 'disassemble',
    'disassembly_lines', 'disassemble_context',
    'side_by_side_disassembly',

    # Instruction set
    'ldrpc_source_address', 'ldrpc_source_word',
]

import os, random, re, struct, collections, subprocess
from dump import *

# Global scratchpad memory. This is the address of the biggest safest area of
# read-write-execute RAM we can guesstimate about. This is provided as a
# default location for the backdoor commands here to hastily bludgeon data
# into. How did we find it? Guesswork! Also, staring at memsquares!
#
# This is halfway through DRAM, in a spot that seems to exhibit uninitialized
# memory patterns even after quite a lot of time running memsquare.py
# Hopefully our code won't get trashed by a SCSI packet!

pad = 0x1e00000

# Default global defines for C++ and assembly code we compile

defines = collections.OrderedDict()
defines['pad'] = pad

# Default dictionary of named C++ snippets. The names are ignored by the
# compiler, but they can help identify code in the shell. Individual
# Python modules can add their corresponding C++ headers at import time.

includes = collections.OrderedDict()

# Low-level includes
includes['stdlib'] = '#include "../lib/tiniest_stdlib.h"'
includes['mt1939'] = '#include "../lib/mt1939_regs.h"'
includes['firmware'] = '#include "ts01_defs.h"'


class CodeError(Exception):
    """An error occurred while compiling or assembling code dynamically.

    This class keeps a saved copy of the compiler error text as well as all
    text files in use during the compile. We can do a little work to try and
    correlate line numbers in errors with line numbers in the sources.
    """
    def __init__(self, text, files):
        self.text = text.rstrip()
        self.files = files
        self.flagged_lines = {}

        # Look for references of the form filename:number: in the error text
        name_re = '|'.join([re.escape(name) for name, content in self.files])
        name_and_number_re = r'(%s):(\d+):' % name_re
        for m in re.finditer(name_and_number_re, self.text):
            name = m.group(1)
            number = int(m.group(2))
            self.flagged_lines[(name, number)] = True

    def __str__(self):
        return "Code compilation errors\n\n%s\n%s" % (
            self.dump_files(), self.text )

    def dump_files(self, heading_width = 79, margin = 10):
        output = []
        for name, content in self.files:

            # Wide fixed-length filename header
            header = '%s %s ' % ('='*margin, name)
            header += '='*max(0, heading_width - len(header))
            output.append(header)

            # Format source code with line numbers
            lines = content.rstrip().expandtabs(8).split('\n')
            for num, line in enumerate(lines):
                line = '%6d  %s' % (num+1, line.rstrip())

                # >>>> Flagged lines
                if (name, num+1) in self.flagged_lines:
                    s = max(0, len(re.match('^ *', line).group(0)) - 1)
                    line = '>'*s + line[s:]
                    line += ' '*max(0, heading_width - s - len(line)) + '<'*s

                output.append(line)
            output.append('')
        return '\n'.join(output)


class temp_file_names:
    """Automatic temporary file names with a list of suffixes.
    For Python's "with" construct. Files are always cleaned up.
    """
    def __init__(self, suffixes):
        self.base = 'temp-coastermelt-%s.' % random.randint(100000, 999999)
        self.directory = os.getcwd()
        self.names = []

        for s in suffixes.split():
            self.names.append(self.base + s)
            setattr(self, s, self.base + s)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.cleanup()

    def cleanup(self):
        assert self.directory == os.getcwd()
        for f in self.names:
            try:
                os.remove(f)
            except OSError:
                pass

    def collect_text(self):
        """Return a list of (name, text) tuples for text files.
        Skips binary files and missing files.
        """
        tuples = []
        for name in self.names:
            try:
                with open(name, 'r') as f:
                    tuples.append(( name, f.read().decode('utf8') ))
            except (IOError, UnicodeDecodeError):
                continue
        return tuples


def prepare_defines(defines, fmt, excluded = None):
    """Prepare defines for a C++ or Assembly program.
    """
    lines = []
    for name, value in defines.items():
        if excluded and re.match(excluded + '$', name):
            continue
        try:
            lines.append(fmt % (name, value))
        except TypeError:
            pass
    return '\n'.join(lines)


def disassemble_string(data, address = 0, thumb = True):
    """Disassemble code from a string buffer.

    Returns a string made of up multiple lines, each with the address in hex,
    a tab, then the disassembled code.
    """
    with temp_file_names('bin') as temp:
        with open(temp.bin, 'wb') as f:
            f.write(data)

        text = subprocess.check_output([
            OBJDUMP, '-D', '-w', '-z',
            '-b', 'binary', '-m', 'armv5t', 
            '--prefix-addresses',
            '--adjust-vma', '0x%08x' % address,
            '-M', ('force-thumb', 'no-force-thumb')[not thumb],
            temp.bin])

        return '\n'.join([
            '%s\t%s' % (l[2:10], l[11:])
            for l in text.split('\n')
            if l.startswith('0x')
        ])


def disassemble(d, address, size, thumb = True):
    """Read some bytes of ARM memory and try to disassemble it as code.
    
    Returns a string made of up multiple lines, each with the address in hex,
    a tab, then the disassembled code.
    """
    return disassemble_string(read_block(d, address, size), address, thumb=thumb)


def assemble_string(address, text, defines = defines, thumb = True):
    """Assemble some instructions for the ARM and return them in a string.

    Address must be word aligned.
    Multiple instructions can be separated by semicolons.
    """
    if address & 3:
        raise ValueError("Address needs to be word aligned")

    set_instruction_mode = ('.arm', '.thumb')[thumb]

    define_string = prepare_defines(defines,
        '\t.equ %s, 0x%08x',
        excluded = r'(r\d+|ip|lr|sp|pc)')

    with temp_file_names('s o bin ld') as temp:

        # Linker script
        with open(temp.ld, 'w') as f: f.write('''\
MEMORY { PATCH (rwx) : ORIGIN = 0x%(address)08x, LENGTH = 2M }
SECTIONS { .text : { *(.text) } > PATCH }
        ''' % locals())

        # Assembly source
        with open(temp.s, 'w') as f: f.write('''\
.text
.syntax unified
.global _start 
%(set_instruction_mode)s
%(define_string)s
_start:
%(text)s
        ''' % locals())

        compiler = subprocess.Popen([
            CC, '-nostdlib', '-nostdinc', '-o', temp.o, temp.s, '-T', temp.ld
            ],
            stderr = subprocess.STDOUT,
            stdout = subprocess.PIPE)

        output = compiler.communicate()[0]
        if compiler.returncode != 0:
            raise CodeError(output, temp.collect_text())

        subprocess.check_call([
            OBJCOPY, temp.o, '-O', 'binary', temp.bin
            ])
        with open(temp.bin, 'rb') as f:
            return f.read()


def assemble(d, address, text, defines = defines, thumb = True):
    """Assemble some instructions for the ARM and place them in memory.

       Address must be word aligned. Multiple instructions can be separated by
       semicolons. Returns the length of the assembled code, in bytes.
       """
    data = assemble_string(address, text, defines=defines, thumb=thumb)
    poke_words_from_string(d, address, data)
    return len(data)


def prepare_ldfile(temp, address):
    """Create a linker script for C++ compilation"""

    if address & 3:
        raise ValueError("Address needs to be word aligned")

    # Linker script
    with open(temp.ld, 'w') as f: f.write('''\
MEMORY { PATCH (rwx) : ORIGIN = 0x%(address)08x, LENGTH = 2M }
SECTIONS { .text : { *(.first) *(.text) *(.rodata) *(.bss) } > PATCH }
    ''' % locals())


def prepare_cppfile(temp, includes, defines, body):
    """Create a .cpp file for C++ compilation"""

    define_string = prepare_defines(defines, 'const uint32_t %s = 0x%08x;')
    include_string = '\n'.join(includes.values())

    with open(temp.cpp, 'w') as f: f.write('''\
#include <stdint.h>
%(define_string)s
%(include_string)s
%(body)s
    ''' % locals())


def compile_objfile(temp, thumb):
    """Compile a C++ expression to an object file"""

    compiler = subprocess.Popen([
        CC,
        '-o', temp.o, temp.cpp, '-T', temp.ld,    # Ins and outs
        '-Os', '-fwhole-program', '-nostdlib',    # Important to keep this as tiny as possible
        '-fpermissive', '-Wno-multichar',         # Relax, this is a debugger.            
        '-fno-exceptions',                        # Lol, no
        '-std=gnu++11',                           # But compile-time abstraction is awesome
        '-lgcc',                                  # Runtime support for multiply, divide, switch...
        ('-mthumb', '-mno-thumb')[not thumb]      # Thumb or not?
        ],
        stderr = subprocess.STDOUT,
        stdout = subprocess.PIPE)

    output = compiler.communicate()[0]
    if compiler.returncode != 0:
        raise CodeError(output, temp.collect_text())


def compile_string(address, expression, includes = includes, defines = defines, thumb = True):
    """Compile a C++ expression to a stand-alone patch installed starting at the supplied address.

    The 'includes' list is a dictionary of C++ definitions and declarations
    that go above the function containing our expression. (Key names are
    ignored by the compiler)

    The 'defines' dictionary can define uint32_t constants that are
    available even prior to the includes. To seamlessly bridge with Python
    namespaces, things that aren't integers are ignored here.
    """
    with temp_file_names('cpp o bin ld') as temp:

        prepare_ldfile(temp, address)
        prepare_cppfile(temp, includes, defines, '''\
extern "C"
unsigned __attribute__ ((externally_visible, section(".first")))
start(unsigned arg)
{
return ( %(expression)s );
}
        ''' % locals())

        compile_objfile(temp, thumb)
        subprocess.check_call([ OBJCOPY, temp.o, '-O', 'binary', temp.bin ])
        with open(temp.bin, 'rb') as f:
            return f.read()


def compile(d, address, expression, includes = includes, defines = defines, thumb = True):
    """Compile a C++ expression to a stand-alone patch installed starting at the supplied address.

       The 'includes' list is a dictionary of C++ definitions and declarations
       that go above the function containing our expression. (Key names are
       ignored by the compiler)

       The 'defines' dictionary can define uint32_t constants that are
       available even prior to the includes. To seamlessly bridge with Python
       namespaces, things that aren't integers are ignored here.

       Returns the length of the compiled code, in bytes.
       """

    data = compile_string(address, expression, includes=includes, defines=defines, thumb=thumb)
    poke_words_from_string(d, address, data)
    return len(data)


def compile_library_string(base_address, code_dict, includes = includes, defines = defines, thumb = True):
    """Compile a dictionary of C++ expressions to a library starting at the supplied address

    Returns a (string, dict) tuple, where the string is compiled code and the
    tuple is an absolute symbol table.
    """
    with temp_file_names('cpp o bin ld') as temp:

        prepare_ldfile(temp, base_address)
        prepare_cppfile(temp, includes, defines, '\n'.join([
            '''\
extern "C"
unsigned __attribute__ ((externally_visible))
%s(unsigned arg)
{
return ( %s );
}
            ''' % (name, code)
            for name, code in code_dict.iteritems()]))

        compile_objfile(temp, thumb)

        symbols = {}
        sym_text = subprocess.check_output([ OBJDUMP, '-t', '-w', temp.o ])
        for line in sym_text.split('\n'):
            tokens = line.split()
            if len(tokens) >= 6 and tokens[2] == 'F' and tokens[3] == '.text':
                symbols[tokens[5]] = int(tokens[0], 16) | thumb

        subprocess.check_call([ OBJCOPY, temp.o, '-O', 'binary', temp.bin ])
        with open(temp.bin, 'rb') as f:
            return (f.read(), symbols)


def compile_library(d, base_address, code_dict, includes = includes, defines = defines, thumb = True):
    """Compile and load a dictionary of C++ expressions to a library starting at the supplied address

    Returns a symbol table dictionary.
    """
    data, syms = compile_library_string(base_address, code_dict, includes=includes, defines=defines, thumb=thumb)
    poke_words_from_string(d, base_address, data)
    return syms


def compile_with_automatic_return_type(d, address, expression, includes = includes, defines = defines, thumb = True):
    """Figure out whether the expression is integer or void, and compile it.

    Returns (code_size, retval_func).
    Call retval_func() on the return value of blx() to convert the return value.
    """
    try:
        # Try integer first
        return (
            compile(d, address, '(uint32_t)(%s)' % expression,
                        includes=includes, defines=defines, thumb=thumb),
            lambda (r0, r1): r0
        )
    except CodeError:
        # Now assume void, wrap it in a block expression
        return (
            compile(d, address, '{ %s; 0; }' % expression,
                        includes=includes, defines=defines, thumb=thumb),
            lambda (r0, r1): None
        )


def evalc(d, expression, arg = 0, includes = includes, defines = defines, address = pad, verbose = False):
    """Compile and remotely execute a C++ expression.
    Void expressions (like statements) return None.
    Expressions that can be cast to (uint32_t) return an int.
    """
    code_size, retval_func = compile_with_automatic_return_type(
        d, address, expression,
        includes=includes, defines=defines)
    if verbose:
        print "* compiled to 0x%x bytes, loaded at 0x%x" % (code_size, address)
    return retval_func(d.blx(address | 1, arg))


def evalasm(d, text, r0 = 0, defines = defines, address = pad, thumb = False):
    """Compile and remotely execute an assembly snippet.

       32-bit ARM instruction set by default.
       Saves and restores r2-r12 and lr.
       Returns (r0, r1).
       """

    if thumb:
        # In Thumb mode, we still use ARM code to save/restore registers.
        assemble(d, address, '''\
            push    { r2-r12, lr }
            adr     lr, link
            adr     r8, text+1
            bx      r8
link:
            pop     { r2-r12, pc }
            .pool
            .thumb
            .align  5
text:
%(text)s
            bx      lr
        ''' % locals(), defines=defines, thumb=False)
        return d.blx(address, r0)

    else:
        # ARM mode (default)
        assemble(d, address, '''\
            push    { r2-r12, lr }
%(text)s
            pop     { r2-r12, pc }
        ''' % locals(), defines=defines, thumb=False)
        return d.blx(address, r0)


def disassembly_lines(text):
    """Convert disassembly text to a sequence of objects

    Each object has attributes:
        - address
        - op
        - args
        - comment
    """
    class disassembly_line:
        def __str__(self):
            return '\t%s\t%s' % (self.op, self.args)
        def __repr__(self):
            return 'disassembly_line(address=%08x, op=%r, args=%r, comment=%r)' % (
                self.address, self.op, self.args, self.comment)

    lines = []
    line_re = re.compile(r'^([^\t]+)\t([^\t]+)?([^;]*)(.*)')
    for line in text.split('\n'):

        obj = disassembly_line()
        m = line_re.match(line)
        if not m:
            raise ValueError('Bad disassembly,\n%s' % line)

        obj.address = int(m.group(1), 16)
        obj.op = m.group(2) or '<unknown>'
        obj.args = m.group(3).strip()
        obj.comment = m.group(4)[1:].strip()

        if obj.op.find('out of bounds') > 0:
            continue
        lines.append(obj)
    return lines


def disassemble_context(d, address, size = 16, thumb = True):
    """Disassemble a region 'size' bytes before and after 'address'.
    """
    address &= ~1           # Round down to halfword (strip T bit)
    size = (size + 3) & ~3  # Round up to word
    block = read_block(d, address - size, size * 2)

    asm = disassemble_string(block, address - size, thumb=thumb)
    for line in disassembly_lines(asm):
        if line.address == address:
            return asm

    if thumb:
        # Didn't resync on its own... offset by a half-word
        asm = disassemble_string(block[2:-2], address - size + 2, thumb=thumb)
        for line in disassembly_lines(asm):
            if line.address == address:
                return asm

    raise ValueError("Can't find a proper context disassembly for address %08x,\n%s" % (address, asm))


def side_by_side_disassembly(lines1, lines2):
    """Given two sets of disassembly lines, format them for display side-by-side.
    Returns a string with one line per input line.
    Addresses are synchronized, in case each side includes different instruction sizes.
    """
    output = []
    index1 = 0
    index2 = 0
    fmt = lambda l: str(l).expandtabs(8)
    column_width = reduce(max, map(len, map(fmt, lines1)))
    while True:

        line1 = index1 < len(lines1) and lines1[index1]
        line2 = index2 < len(lines2) and lines2[index2]

        if line1 and line2:
            # We still have lines on both sides, align their addresses

            if line1.address < line2.address:
                # Left side first
                left, right = True, False
                address = line1.address

            elif line2.address < line1.address:
                # Right side first
                left, right = False, True
                address = line2.address

            else:
                # Synchronized
                left, right = True, True
                address = line1.address

        elif line1:
            # Only the left side
            left, right = True, False
            address = line1.address

        elif line2:
            # Only the right side
            left, right = False, True
            address = line2.address

        else:
            # Done
            break

        output.append("%08x %-*s %s" % (
            address, column_width,
            left and fmt(line1) or '',
            right and fmt(line2) or ''
        ))

        index1 += left
        index2 += right

    return '\n'.join(output)


def ldrpc_source_address(line):
    """Calculate the absolute source address of a PC-relative load.

    'line' is a line returned by disassembly_lines().
    If it doesn't look like the right kind of instruction, returns None.
    """    
    # Example:  ldr r2, [pc, #900]  ; (0x000034b4)
    if line.op == 'ldr' and line.args.find('[pc') > 0:
        return int(line.comment.strip(';( )'), 0)


def ldrpc_source_word(d, line):
    """Load the source data from a PC-relative load instruction.

    'line' is a line returned by disassembly_lines().
    If it doesn't look like the right kind of instruction, returns None.
    """    
    address = ldrpc_source_address(line)
    if address is not None:
        return d.peek(address)

