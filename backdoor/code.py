#!/usr/bin/env python

# Tools for working with code on the backdoored target machine.
# Assemble, disassemble, and compile. Requires an ARM cross-compiler.

CC      = 'arm-none-eabi-gcc'
OBJCOPY = 'arm-none-eabi-objcopy'
OBJDUMP = 'arm-none-eabi-objdump'

__all__ = [
    'CodeError',
    'pad', 'defines', 'includes',
    'disassemble_string', 'disassemble',
    'assemble_string', 'assemble',
    'compile_string', 'compile',
    'evalc', 'evalasm',
    'disassemble_for_relocation',
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

# Default dictionary of named C++ snippets.
# The names are ignored by the compiler, but they help the shell manage.

includes = collections.OrderedDict()
includes['builtins'] = '#include "shell_builtins.h"'


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


def prepare_defines(defines, fmt, excluded = ''):
    """Prepare defines for a C++ or Assembly program.
    """
    excluded_re = re.compile(excluded + '$')
    lines = []
    for name, value in defines.items():
        if excluded_re.match(name):
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
    if address & 3:
        raise ValueError("Address needs to be word aligned")

    with temp_file_names('bin') as temp:
        with open(temp.bin, 'wb') as f:
            f.write(data)

        text = subprocess.check_output([
            OBJDUMP, '-D', '-w', '-z',
            '-b', 'binary', '-m', 'arm7tdmi', 
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


def assemble_string(address, text, defines = defines):
    """Assemble some instructions for the ARM and return them in a string.

    Address must be word aligned. By default assembles thumb instructions,
    but you can use the '.arm' assembly directive to change this.
    Multiple instructions can be separated by semicolons.
    """
    if address & 3:
        raise ValueError("Address needs to be word aligned")

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
.thumb
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


def assemble(d, address, text, defines = defines):
    """Assemble some instructions for the ARM and place them in memory.
       Address must be word aligned. By default assembles thumb instructions,
       but you can use the '.arm' assembly directive to change this.
       Multiple instructions can be separated by semicolons.

       Returns the length of the assembled code, in bytes.
       """

    data = assemble_string(address, text, defines=defines)
    poke_words_from_string(d, address, data)
    return len(data)


def compile_string(address, expression, includes = includes, defines = defines, thumb = True):
    """Compile a C++ expression to a stand-alone patch installed starting at the supplied address.

       The 'includes' list is a dictionary of C++ definitions and declarations
       that go above the function containing our expression. (Key names are
       ignored by the compiler)

       The 'defines' dictionary can define uint32_t constants that are
       available even prior to the includes. To seamlessly bridge with Python
       namespaces, things that aren't integers are ignored here.
       """

    if address & 3:
        raise ValueError("Address needs to be word aligned")

    define_string = prepare_defines(defines, 'static const uint32_t %s = 0x%08x;')
    include_string = '\n'.join(includes.values())

    with temp_file_names('cpp o bin ld') as temp:

        # Linker script
        with open(temp.ld, 'w') as f: f.write('''\
MEMORY { PATCH (rwx) : ORIGIN = 0x%(address)08x, LENGTH = 2M }
SECTIONS { .text : { *(.first) *(.text) *(.rodata) } > PATCH }
        ''' % locals())

        # C+ source
        with open(temp.cpp, 'w') as f: f.write('''\
#include <stdint.h>
%(define_string)s
%(include_string)s
unsigned __attribute__ ((externally_visible, section(".first")))
start(unsigned arg)
{
    return ( %(expression)s );
}
        ''' % locals())

        compiler = subprocess.Popen([
            CC,
            '-o', temp.o, temp.cpp, '-T', temp.ld,    # Ins and outs
            '-Os', '-fwhole-program', '-nostdlib',    # Important to keep this as tiny as possible
            '-fpermissive', '-Wno-multichar',         # Relax, this is a debugger.            
            ('-mthumb', '-mno-thumb')[not thumb]      # Thumb or not?
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


def evalc(d, expression, arg = 0, includes = includes, defines = defines, address = pad):
    """Compile and remotely execute a C++ expression.
       Void expressions (like statements) return None.
       """
    try:
        # First try, see if it's something we can cast to integer.
        # If that fails, try again using a block-expression to wrap a void expression.
        compile(d, address, '(uint32_t)(%s)' % expression, includes=includes, defines=defines)
        return d.blx(address + 1, arg)[0]
    except CodeError:
        compile(d, address, '{ %s; 0; }' % expression)
        d.blx(address + 1, arg)


def evalasm(d, text, r0 = 0, defines = defines, address = pad):
    """Compile and remotely execute an assembly snippet.
       32-bit ARM instruction set.
       Saves and restores r1-r12 and lr. Returns (r0, r1).
       """
    assemble(d, address, '''\
        .arm
        push    {r2-r12, lr}
%(text)s
        pop     {r2-r12, pc}
    ''' % locals(), defines=defines)
    return d.blx(address, r0)


def disassemble_for_relocation(d, address, size, thumb = True):
    """Disassemble instructions from ARM memory and prepare them for assembly elsewhere.

    PC-relative references are detected and fixed, usually requiring
    additional data to be placed near those fixed instructions.

    Returns a tuple of (disassembled_code, relocation_data).
    Both strings are assembly source.
    """

    print "TODO: Relocation not implemented yet"

    lines = []
    reloc = []
    for line in disassemble(d, address, size, thumb).split('\n'):
        address_str, asm = line.split('\t', 1)
        asm, comment = (asm + ';').split(';', 1)

        lines.append( asm )

    return ( '\n'.join(lines), '\n'.join(reloc) )


