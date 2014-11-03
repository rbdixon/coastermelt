# Arbitrary allocations in target memory.
# This module should be included by the module that 'owns' the allocation only.


# Global scratchpad memory. This is the address of the biggest safest area of
# read-write-execute RAM we can guesstimate about. This is provided as a
# default location for the backdoor commands here to hastily bludgeon data
# into. How did we find it? Guesswork! Also, staring at memsquares!
#
# This is halfway through DRAM, in a spot that seems to exhibit uninitialized
# memory patterns even after quite a lot of time running memsquare.py
# Hopefully our code won't get trashed by a SCSI packet!

pad = 0x1e00000

# Buffer used for code, e.g. %ec, %ecc, %ea, %tea

shell_code = 0x1e40000

# Backdoor stubs

bitbang_backdoor = 0x1e48000
cpu8051_backdoor = 0x1e49000

# Our ring buffer is 64 KiB. The default location comes from
# more guesswork and memsquares. It's 1MB above the default
# pad, still in an area of DRAM that seems very lightly used.

console_address = 0x1e50000
