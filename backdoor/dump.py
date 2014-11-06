#!/usr/bin/env python
import sys, struct, time

# Use on the command line to interactively dump regions of memory.
# Or import as a library for higher level dumping functions.

__all__ = [
    'words_from_string',
    'poke_words', 'poke_words_from_string', 'poke_bytes',
    'read_block', 'scsi_read_buffer',
    'hexdump', 'hexdump_words',
    'dump', 'dump_words',
    'search_block'
]


class progress_reporter:
    """A simple console progress reporter for memory operations.

    Totally invisible unless the operation is taking longer than the
    reporting interval. At that point, we'll update the status at
    most that often. Always writes a final status at completion if
    we had any status output at all before that point.
    """
    def __init__(self, message, reporting_interval = 0.2, enabled = True):
        self.message = message
        self.reporting_interval = reporting_interval
        self.enabled = enabled
        self.first_timestamp = time.time()
        self.output_timestamp = None

    def mandatory_update(self, current, total):
        sys.stdout.write("\r %d / %d %s " % (current, total, self.message))
        sys.stdout.flush()
        self.output_timestamp = time.time()

    def update(self, current, total):
        if self.enabled:
            latest = self.output_timestamp or self.first_timestamp
            if time.time() > latest + self.reporting_interval:
                # Enough time has passed
                self.mandatory_update(current, total)

    def complete(self, current, total):
        # Write a final status if we had any output
        if self.output_timestamp:
            self.mandatory_update(current, total)
            sys.stdout.write('\n')
            sys.stdout.flush()


def words_from_string(s, padding_byte = chr(255)):
    """A common conversion to give a list of integers from a little endian string.
    Uses the indicated padding byte if the string isn't a word multiple.
    """
    residual = len(s) & 3
    if residual:
        s += padding_byte * (4 - residual)
    return struct.unpack('<%dI' % (len(s)/4), s)


def poke_words_from_string(d, address, s):
    poke_words(d, address, words_from_string(s))


def poke_words(d, address, words, verbose = True, reporting_interval = 0.1):
    """Send a block of words (slowly)"""
    progress = progress_reporter('words sent',
        enabled=verbose, reporting_interval=reporting_interval)
    l = len(words)
    for i, w in enumerate(words):
        d.poke(address + 4*i, w)
        progress.update(i+1, l)
    progress.complete(l, l)


def poke_bytes(d, address, bytes, verbose = True, reporting_interval = 0.1):
    """Send a block of bytes (VERY slowly)"""
    progress = progress_reporter('bytes sent',
        enabled=verbose, reporting_interval=reporting_interval)
    l = len(bytes)
    for i, w in enumerate(bytes):
        d.poke_byte(address + i, w)
        progress.update(i+1, l)
    progress.complete(l, l)


def scsi_read_buffer(d, mode, address, size):
    """Use the SCSI 'Read Buffer' command to grab a block of data quickly.

    The bootloader and TS01 firmware implement a version of this command
    with mode 6 mapped to ARM memory (low 16MB only) and mode 2 mapped
    to something we'll call DMA memory.
    """
    return d.scsi_in(''.join(map(chr, [
        0x3c, mode, 0,
        (address >> 16) & 0xff,
        (address >> 8) & 0xff,
        (address >> 0) & 0xff,
        (size >> 16) & 0xff,
        (size >> 8) & 0xff,
        (size >> 0) & 0xff,
        0,0,0 ])), size)


def read_word_aligned_block(d, address, size,
    verbose = True, reporting_interval = 0.2,
    max_round_trips = None, fast = False, addr_space = 'arm'):
    # Implementation detail for read_block

    assert (address & 3) == 0
    assert (size & 3) == 0
    i = 0
    parts = []

    progress = progress_reporter('bytes read',
        enabled=verbose, reporting_interval=reporting_interval)

    while i < size:
        wordcount = min(size - i, 64*1024) / 4
        dram_address = (address - 0x1c08000) & 0xffffffff

        if addr_space == 'dma' and hasattr(d, 'scsi_in'):
            # Undocumented SCSI command that reads some kind of DMA memory space.
            # Begins with DRAM, but starts doing other things around 0x368500.

            part = scsi_read_buffer(d, 2, address + i, wordcount * 4)

        elif fast and hasattr(d, 'scsi_in') and addr_space == 'arm' and dram_address + i <= 0x368000:
            # Use the DMA reads, where we can, to implement fast DRAM reads.

            part = scsi_read_buffer(d, 2, address - 0x1c08000 + i, wordcount * 4)

        elif fast and hasattr(d, 'scsi_in') and addr_space == 'arm' and address + i <= 0x200000:
            # Undocumented SCSI command that copies data from flash addresses
            # via the ARM to DRAM and DMA's it out to SCSI. Very fast, handles
            # addreses (including RAM mappings) below 2MB.

            wordcount = min(wordcount, 64 * 1024 / 4)
            part = scsi_read_buffer(d, 6, address + i, wordcount * 4)

        elif addr_space == 'arm':
            part = d.read_block(address + i, wordcount)

        else:
            raise ValueError("Don't know how to read address %08x in %r memory" % (address, addr_space))

        assert (len(part) & 3) == 0
        i += len(part)
        parts.append(part)
        if max_round_trips and len(parts) >= max_round_trips:
            break

        progress.update(i, size)

    progress.complete(i, size)
    return ''.join(parts)


def read_block(d, address, size, max_round_trips = None, fast = False, addr_space = 'arm'):
    """Read a block of memory, return it as a string.

    Reads using LDR (word-aligned) reads only. The requested block
    does not need to be aligned.

    If max_round_trips is set, we stop after that many round-trip
    commands to the device. This can be used for real-time applications
    where it may be better to have some data soon than all the data later.

    If 'fast' is set, this uses a much faster DMA-based approach that probably
    doesn't work in all cases.
    """

    # Convert to half-open interval [address, end)
    # Round beginning of interval down to nearest word
    # Round end of interval up to nearest word
    end = address + size
    word_address = address & ~3
    word_end = (end + 3) & ~3
    word_size = word_end - word_address

    # Where in the larger interval is our original block?
    sub_begin = address - word_address
    sub_end = sub_begin + size

    return read_word_aligned_block(d, word_address, word_size,
        max_round_trips=max_round_trips, fast=fast, addr_space=addr_space
        )[sub_begin:sub_end]


def search_block(d, address, size, substring,
    context_length = 16, fast = False, addr_space = 'arm'):
    """Read a block of ARM memory, and search for all occurrences of a byte string.

    Yields tuples every time a match is found:
    (address, context_before, context_after) 
    """

    # We may have a way to do this gradually later, but for now we read all at once
    # then search all at once.
    block = read_block(d, address, size, fast=fast, addr_space=addr_space)

    offset = 0
    while True:
        offset = block.find(substring, offset)
        if offset < 0:
            break
        yield (
            address + offset,
            block[max(0, offset - context_length):offset],
            block[offset + len(substring):offset + len(substring) + context_length]
        )
        offset += len(substring)


def hexdump(src, length = 16, address = 0, log_file = None):
    if log_file:
        f = open(log_file, 'wb')
        f.write(src)
        f.close()

    # Based on https://gist.github.com/sbz/1080258
    FILTER = ''.join([(len(repr(chr(x))) == 3) and chr(x) or '.' for x in range(256)])
    lines = []
    for c in xrange(0, len(src), length):
        chars = src[c:c+length]
        hex = ' '.join(["%02x" % ord(x) for x in chars])
        printable = ''.join(["%s" % ((ord(x) <= 127 and FILTER[ord(x)]) or '.') for x in chars])
        lines.append("%08x  %-*s  %s\n" % (address + c, length*3, hex, printable))
    return ''.join(lines)


def hexdump_words(src, words_per_line = 8, address = 0, log_file = None):
    if log_file:
        f = open(log_file, 'wb')
        f.write(src)
        f.close()

    assert (address & 3) == 0
    assert (len(src) & 3) == 0
    words = words_from_string(src)
    lines = []
    for c in xrange(0, len(words), words_per_line):
        w = words[c:c+words_per_line]
        hex = ' '.join(["%08x" % i for i in w])
        lines.append("%08x  %-*s\n" % (address + c*4, words_per_line*9, hex))
    return ''.join(lines)


def dump(d, address, size, log_file = 'result.log', fast = False, check_fast = False, addr_space = 'arm'):
    data = read_block(d, address, size, fast=fast, addr_space=addr_space)
    if check_fast:
        assert read_block(d, address, size, fast=not fast, addr_space=addr_space) == data
    sys.stdout.write(hexdump(data, 16, address, log_file))

def dump_words(d, address, wordcount, log_file = 'result.log', fast = False, addr_space = 'arm'):
    data = read_block(d, address, wordcount * 4, fast=fast, addr_space=addr_space)
    sys.stdout.write(hexdump_words(data, 8, address, log_file))


if __name__ == "__main__":
    import remote
    if len(sys.argv) != 3:
        print "usage: %s address size" % sys.argv[0]
        sys.exit(1)
    dump(remote.Device(),
        int(sys.argv[1].replace('_',''), 16), 
        int(sys.argv[2].replace('_',''), 16))
