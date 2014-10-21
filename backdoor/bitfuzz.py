#!/usr/bin/env python

import time, sys

__all__ = [ 'bitfuzz_rounds', 'word_bits' ]


def word_bits(word):
    """Convert a 32-bit word to a human-legible bitstring with separators"""
    return '_'.join(bin(int(digit,16))[2:].zfill(4) for digit in ('%08x' % word))


def bitfuzz_rounds(d, address, wordcount = 1, period = 8, delay = 0.05):
    """Iterates a sequence of bitfuzz rounds, returning text lines for each.
    
    This applies alternating sequences of ones and zeroes to a word and
    takes apart the reads we get back. It's designed for reverse engineering
    registers that have bits each with different usages, or bits that might
    be modified asynchronously.
    """

    # Initial value
    yield '\n'.join([
        bitfuzz_heading(address, wordcount),
        bitfuzz_round(d, address, wordcount, None),
    ])

    waveform = ( [0x00000000] * (period//2) +
                 [0xffffffff] * (period - period//2) )

    while True:
        for pattern in waveform:
            yield bitfuzz_round(d, address, wordcount, pattern)
            if delay:
                time.sleep(delay)


def bitfuzz_round(d, address, wordcount, pattern):
    values = []
    pattern_str = pattern is not None and hex(pattern)[-1:] or ' '

    for word in range(wordcount):
        if pattern is not None:
            d.poke(address + word*4, pattern)
        values.append(d.peek(address + word*4))

    return "%s %s" % (pattern_str, '  '.join(word_bits(w) for w in values))


def bitfuzz_heading(address, wordcount):
    return '  ' + ''.join(['%-37s' % '%08x' % (address + i*4) for i in range(wordcount)])



if __name__ == "__main__":
    import remote
    if len(sys.argv) != 3:
        print "usage: %s address wordcount" % sys.argv[0]
        sys.exit(1)
    for line in bitfuzz_rounds(remote.Device(),
            int(sys.argv[1].replace('_',''), 16), 
            int(sys.argv[2].replace('_',''), 16)):
        print line
