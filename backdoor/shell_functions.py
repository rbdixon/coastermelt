#
# Utility functions for use in the shell.
#
# Many of these are trivial wrappers for functionality available elsewhere,
# like on the Device object, in order to regularize syntax.
#

__all__ = [
    'hexstr', 'hexint', 'hexint_tuple',
    'get_signature',
    'scsi_out', 'scsi_in',
    'peek', 'poke', 'peek_byte', 'poke_byte', 'blx',
    'setup_hexoutput', 'usage_error_from_code', 'all_defines',
]

from IPython.core.error import UsageError
from code import *


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

def scsi_out(d, cdb, data):
    """Send a low-level SCSI packet with outgoing data."""
    cdb = (cdb + chr(0)*12)[:12]
    return d.scsi_out(cdb, data)

def scsi_in(d, cdb, size=0x20):
    """Send a low-level SCSI packet that expects incoming data."""
    cdb = (cdb + chr(0)*12)[:12]
    return d.scsi_in(cdb, size)

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

def setup_hexoutput(ipy):
    """Configure an IPython shell to display integers in hex by default.
       You can convert to decimal with str() still.
       """
    def handler(n, p, cycle):
        if n < 0:
            return p.text("-0x%x" % -n)
        else :
            return p.text("0x%x" % n)

    formatter = ipy.display_formatter.formatters['text/plain']
    formatter.for_type(int, handler)
    formatter.for_type(long, handler)

def all_defines():
    """Return a merged dictionary of all defines.

    - First the implicit environment of the shell's globals
    - Then the explicit environment of the code.defines dict
    """
    import shell, code
    d = dict(shell.__dict__)
    d.update(code.defines)
    return d

def usage_error_from_code(code_error):
    """Wrap a coastermelt CodeError in an IPython UsageError
    This is appropriate for cases where we're accepting code on the shell
    and reporting code compilation errors as an error in command usage.
    """
    raise UsageError("Code compilation errors\n\n%s\n%s" % (
        code_error.dump_files(),
        code_error.text))
