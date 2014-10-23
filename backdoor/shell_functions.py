#
# Utility functions for use in the shell.
#
# Many of these are trivial wrappers for functionality available elsewhere,
# like on the Device object, in order to regularize syntax.
#

__all__ = [
    'hexstr', 'hexint', 'hexint_tuple', 'hexint_aligned',
    'get_signature',
    'scsi_out', 'scsi_in', 'scsi_read',
    'peek', 'poke', 'peek_byte', 'poke_byte',
    'blx',
    'all_defines', 'all_includes'
]

from IPython.core.error import UsageError
import code, struct


def hexstr(s):
    """Compact inline hexdump"""
    return ' '.join(['%02x' % ord(b) for b in s])

def hexint(s):
    """This takes a bunch of weird number formats, as explained in the module docs"""
    if s.startswith('_'):
        base = code.pad
    else:
        base = 0
    if s.endswith('_'):
        s += '0000'
    return base + int(s.replace('_',''), 16)

def hexint_tuple(s):
    """A tuple of colon-separated hexints"""
    return tuple(hexint(i) for i in s.split(':'))

def hexint_aligned(s):
    """A hexint() that must be word aligned"""
    i = hexint(s)
    if i & 3:
        raise UsageError("Value must be word aligned: %x" % i)
    return i

def pad_cdb(cdb):
    """Pad a SCSI CDB to the required 12 bytes"""
    return (cdb + chr(0)*12)[:12]

def scsi_out(d, cdb, data):
    """Send a low-level SCSI packet with outgoing data."""
    return d.scsi_out(pad_cdb(cdb), data)

def scsi_in(d, cdb, size=0x20):
    """Send a low-level SCSI packet that expects incoming data."""
    return d.scsi_in(pad_cdb(cdb), size)

def scsi_read(d, lba, blockcount=1):
    cdb = struct.pack('>BBII', 0xA8, 0, lba, blockcount)
    return scsi_in(d, cdb, blockcount * 2048)

def get_signature(d):
    """Return a 12-byte signature identifying the firmware patch."""
    return d.get_signature()

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
    """Return a merged dictionary of all defines.

    - First the implicit environment of the shell's globals
    - Then the explicit environment of the code.defines dict
    """
    import shell_namespace
    d = dict(shell_namespace.__dict__)
    d.update(code.defines)
    return d

def all_includes():
    """Returns a dictionary of standard code includes plus our shell includes"""
    return dict(code.includes,
        shell_builtins = '#include "shell_builtins.h"')

