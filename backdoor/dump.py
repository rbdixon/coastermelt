#!/usr/bin/env python
import sys, struct, time

# Use on the command line to interactively dump regions of memory.
# Or import as a library for higher level dumping functions.

__all__ = [
    'words_from_string', 'poke_words', 'poke_words_from_string',
    'read_block',
    'hexdump', 'hexdump_words',
    'dump', 'dump_words',
    'search_block'
]


def words_from_string(s):
    """A common conversion to give a list of integers from a little endian string.
       Assumes the string is a multiple of 4 bytes in length.
       """
    return struct.unpack('<%dI' % (len(s)/4), s)

def poke_words(d, address, words):
    for i, w in enumerate(words):
        d.poke(address + 4*i, w)

def poke_words_from_string(d, address, s):
    poke_words(d, address, words_from_string(s))


def read_word_aligned_block(d, address, size, verbose = True, reporting_interval = 0.2):
    # Implementation detail for read_block

    assert (address & 3) == 0
    assert (size & 3) == 0
    i = 0
    parts = []
    timestamp = time.time()
    first_timestamp = timestamp
    num_reports = 0

    while i < size:
        wordcount = min((size - i) / 4, 0x1c)
        parts.append(d.read_block(address + i, wordcount))
        i += 4 * wordcount

        now = time.time()
        if ( verbose
             and now > first_timestamp + reporting_interval
             and ( i >= size or now > timestamp + reporting_interval )
             ):
                print "%d / %d bytes read" % (i, size)
                timestamp = now
                num_reports += 1

    return ''.join(parts)


def read_block(d, address, size):
    """Read a block of ARM memory, return it as a string.

    Reads using LDR (word-aligned) reads only. The requested block
    does not need to be aligned.
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

    return read_word_aligned_block(d, word_address, word_size)[sub_begin:sub_end]


def search_block(d, address, size, substring, context_length = 16):
    """Read a block of ARM memory, and search for all occurrences of a byte string.

    Yields tuples every time a match is found:
    (address, context_before, context_after) 
    """

    # We may have a way to do this gradually later, but for now we read all at once
    # then search all at once.
    block = read_block(d, address, size)

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


def dump(d, address, size, log_file = 'result.log'):
    data = read_block(d, address, size)
    sys.stdout.write(hexdump(data, 16, address, log_file))

def dump_words(d, address, wordcount, log_file = 'result.log'):
    data = read_block(d, address, wordcount * 4)
    sys.stdout.write(hexdump_words(data, 8, address, log_file))


if __name__ == "__main__":
    import remote
    if len(sys.argv) != 3:
        print "usage: %s address size" % sys.argv[0]
        sys.exit(1)
    dump(remote.Device(),
        int(sys.argv[1].replace('_',''), 16), 
        int(sys.argv[2].replace('_',''), 16))
