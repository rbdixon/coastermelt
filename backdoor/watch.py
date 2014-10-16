#!/usr/bin/env python
import remote, sys, time, random, struct, cStringIO, binascii

# Scan regions of memory for changes, and display those changes in real-time.
# It's like My First Temporal Hex Dump. Great for kids!

__all__ = ['watch', 'watch_tabulator']


def break_up_addresses(device, addrs, block_wordcount):
    """Break up addresses into packet-sized pieces.

    We do this to give all scanning regions about the same probability per
    word. We can also use this opportunity to randomly offset the packet
    boundaries, to reduce correlation with effects of SCSI packet boundaries
    when scanning large blocks.
    
    The erturned list contains (address, fn) tuples. When the function is
    called, it returns a string of data starting at 'address'. Length is
    implied by the function results.

    Order of results and offset of blocks are both randomized.
    """

    parts = []
    block_bytecount = block_wordcount * 4

    for addr in addrs:

        if len(addr) == 1:
            # Single word.
            # Looks just like a tiny block, but we read it with peek()

            def fn(device = device,
                   ptr = addr[0]
                   ):
                return struct.pack('<I', device.peek(ptr))

            parts.append(( addr[0], fn ))

        elif len(addr) == 2:
            # Range. First, pad it out to word alignment.

            first, last = addr
            first &= ~3
            last = (last + 3) & ~3

            if last <= first:
                raise ValueError('Empty range ' + repr(addr))

            # The first read address will be randomized to include up to one
            # full block of padding before the range we care about. This will
            # randomize the alignment of packet boundaries with respect to the
            # regions we're scanning.

            block_offset = random.randint(0, block_wordcount) * 4
            ptr = first - block_offset

            while ptr < last:

                def fn(device = device,
                       count = block_wordcount,
                       ptr = ptr,
                       start = block_offset,
                       end = min(block_bytecount, last + 1 - ptr)
                       ):
                    return device.read_block(ptr, count)[start:end]

                parts.append(( ptr + block_offset, fn ))
                block_offset = 0
                ptr += block_bytecount

        else:
            raise ValueError('Unrecognized address format ' + repr(addr))

    random.shuffle(parts)
    return parts


def watch(d, addrs, verbose = True, block_wordcount = 0x1c, memo_filename = None):
    """Repeatedly scan memory, in randomized order, looking for changes.

    When a change is found, we yield:
       (timestamp, address, new_value, old_value).

    Timestamps are as reported by time.time(). It's the first time we noticed
    this change, timestamped as soon as possible.

    Addresses are a list of things to watch:

       (addr,)
         Single numbers are the address of a word to watch. This guarantees
         that the address is only read as that one single word. We won't read
         anything nearby, and each read will be a single peek.

       (a, b)
         Two elements indicate a range of addresses from a to b, including
         both endpoints. These are broken into randomized sections of exactly
         block_wordcount words. To reduce unwanted statistical correlations,
         we end up scanning a little past the beginning and end, but any
         addresses outside the range is not reported.
    """

    now = time.time()
    start_timestamp = now
    output_timestamp = now
    round_number = 0

    # We can use a file on disk as memo for debugging or if we need something
    # that handles large sparse address spaces, but usually cStringIO is fine.
    if memo_filename:
        memo = open(memo_filename, 'w+b')
    else:
        memo = cStringIO.StringIO()

    # Initialize the memo with current memory contents
    for addr, fn in break_up_addresses(d, addrs, block_wordcount):
        memo.seek(addr)
        memo.write(fn())

    # Scan in an endless series of shuffled rounds
    while True:
        round_number += 1
        for addr, fn in break_up_addresses(d, addrs, block_wordcount):

            # Timestamp as soon as the block read comes back
            block = fn()
            timestamp = time.time()

            # Keep track of differences with our memo buffer
            memo.seek(addr)
            memo_block = memo.read(len(block))
            if block == memo_block:
                continue
            
            # If the block has changed, memoize it and report word-by-word diffs
            memo.seek(addr)
            memo.write(block)

            block_wordcount = len(block) / 4
            block_words = struct.unpack('<%dI' % block_wordcount, block)
            memo_words = struct.unpack('<%dI' % block_wordcount, memo_block)

            for i in range(block_wordcount):
                old_value = memo_words[i]
                new_value = block_words[i]
                if new_value != old_value:
                    yield (timestamp, addr + i*4, new_value, old_value)

        # Report status
        now = time.time()
        if verbose and now > output_timestamp + 1.0:
            output_timestamp = now
            print "[ round %6d ] avg %.03f / second" % (round_number, round_number / (now - start_timestamp))


def watch_tabulator(change_iterator, legend_interval = 40):
    """A tabular console interface for watch(). Yields lines of text.

    Every time we see a new address change, it gets added as a column.
    When this happens, we print a new legend immediately.
    """

    column_to_address = []
    address_to_column = {}
    legend_countdown = 0
    start_time = time.time()

    for timestamp, address, new_value, old_value in change_iterator:

        timestamp_str = '%10.03f  ' % (timestamp - start_time)
        timestamp_blank = ' ' * len(timestamp_str)

        # Allocate new columns first-come-first-serve
        if address not in address_to_column:
            address_to_column[address] = len(column_to_address)
            column_to_address.append(address)
            legend_countdown = 0

        # Print the legend when we get new columns, or every 'legend_interval' lines
        if legend_countdown == 0:
            yield timestamp_blank + '-'.join(['=' * 8 for a in column_to_address])
            yield timestamp_blank + ' '.join(['%08x' % a for a in column_to_address])
            yield timestamp_blank + '-'.join(['=' * 8 for a in column_to_address])
            legend_countdown = legend_interval

        # Put this change in the right column
        yield timestamp_str + ' ' * (9 * address_to_column[address]) + '%08x' % new_value
        legend_countdown -= 1


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print "usage: %s address [addresses ...]" % sys.argv[0]
        print "  Each address can be a single word or a range a:b including both ends"
        sys.exit(1)

    d = remote.Device()      
    addrs = [tuple(int(n.replace('_',''), 16) for n in arg.split(':')) for arg in sys.argv[1:]]
    changes = watch(d, addrs)
    for line in watch_tabulator(changes):
        print line
