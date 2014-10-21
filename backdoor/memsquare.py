#!/usr/bin/env python

# Make a big square map of the ARM processor's view of memory. Each pixel will
# represent 256 bytes of memory. 16 million pixels and we have the whole
# 32-bit address space. We can fit this in a 4096x4096 image. Maybe some neat
# patterns emerge. It's kinda slow! Maybe it will crash!

__all__ = ['categorize_block', 'categorize_block_array', 'memsquare']

from dump import *
from math import log
from hilbert import hilbert
import remote, sys, png, struct, time


def categorize_block(d, address, size, addr_space='arm'):
    # Look at everything we can get in one round trip.
    # Returns scaled red and green values, but raw blue values;
    # they can't be calculated until the whole image is known.

    t1 = time.time()
    try:
        head = read_block(d, address, size, max_round_trips=1, addr_space=addr_space)
    except IOError, e:
        print e
        head = None
    t2 = time.time()

    if head is None:
        # Error marker
        return [0xFF, 0x00, t2-t1]

    # Red/green channels: Statistics. Red is mean,
    # green is mod-256 sum of squared differences between
    # consecutive bytes. Blue encodes the access time.
    # The amount of time it takes to read is a good
    # indicator of the bus type or cache settings!

    red = 0
    green = 0
    prev = '\x00'

    for b in head:
        signed_diff = struct.unpack('b', struct.pack('B', 0xFF & (ord(b) - ord(prev))))[0]
        red += ord(b)
        green += signed_diff * signed_diff
        prev = b

    return [
        min(0xFF, max(0, int(red / len(head)))),   # Divide by total to finish calculating the mean
        green & 0xFF,                              # Modulo diff from above
        t2 - t1                                    # Blue is in floating point seconds. We post-process below.
    ]


def categorize_block_array(d, base_address, blocksize, pixelsize, addr_space = 'arm'):
    print 'Categorizing blocks in memory, following a 2D Hilbert curve'

    a = []
    timestamp = time.time()
    first_time = timestamp

    for y in xrange(pixelsize):
        row = []
        for x in xrange(pixelsize):
            addr = base_address + blocksize * hilbert(x, y, pixelsize)
            row.extend(categorize_block(d, addr, blocksize, addr_space=addr_space))

            # Keep the crowd informed!
            now = time.time()
            if now > timestamp + 0.5:

                # Estimate time
                completion = (x + y*pixelsize) / float(pixelsize*pixelsize)
                elapsed = now - first_time
                remaining = 0
                if completion > 0.00001:
                    total = elapsed / completion
                    if total > elapsed:
                        remaining = total - elapsed

                print 'block %08x - (%4d,%4d) of %d, %6.2f%% -- %2d:%02d:%02d elapsed, %2d:%02d:%02d est. remaining' % (
                    addr, x, y, pixelsize, 100 * completion,
                    elapsed / (60 * 60), (elapsed / 60) % 60, elapsed % 60,
                    remaining / (60 * 60), (remaining / 60) % 60, remaining % 60)
                timestamp = now
    
        a.append(row)

    print 'Calculating global scaling for blue channel'

    # The blue channel still has raw time deltas. Calculate pecentiles so we can scale them.

    times = []
    for row in a:
        for x in xrange(pixelsize):
            times.append(row[2 + 3*x])
    times.sort()

    percentile_low  = log(times[int( len(times) * 0.05 )])
    percentile_high = log(times[int( len(times) * 0.95 )])
    percentile_s    = 256.0 / (percentile_high - percentile_low)

    for row in a:
        for x in xrange(pixelsize):
            row[2+3*x] = min(255, max(0, int(0.5 + (log(row[2+3*x]) - percentile_low) * percentile_s)))

    print 'Done scaling'
    return a


def memsquare(d, filename, base_address, blocksize, pixelsize = 4096, addr_space = 'arm'):
    b = categorize_block_array(d, base_address, blocksize, pixelsize, addr_space=addr_space)
    w = png.Writer(len(b[0])/3, len(b))
    f = open(filename, 'wb')
    w.write(f, b)
    f.close()
    print 'Wrote %s' % filename


def survey():
    # Survey of all address space, each pixel is 0x100 bytes
    memsquare(remote.Device(), 'memsquare-00000000-ffffffff.png', 0, 0x100)

def low64():
    # Just the active region in the low 64MB of address space.
    # Each pixel is 4 bytes, so this is about as much resolution as we could want.
    memsquare(remote.Device(), 'memsquare-00000000-3fffffff.png', 0, 4)

def mmio():
    # Map every byte in 4MB of MMIO space
    memsquare(remote.Device(), 'memsquare-04000000-043fffff.png', 0x04000000, 1, 2048)

def dram():
    # Fast dump of DRAM. 512x512, 16 byte scale.
    # Runs in a few minutes, okay for differential testing.
    memsquare(remote.Device(), 'memsquare-01c00000-01ffffff.png', 0x01c00000, 16, 512)

def sram():
    # Small 8kB mapping, looks like SRAM. 2-byte scale.
    memsquare(remote.Device(), 'memsquare-02000000-02001fff.png', 0x02000000, 2, 64)

def dma():
    # DMA memory space, starting with DRAM. 
    memsquare(remote.Device(), 'memsquare-dma-000000-ffffff.png', 0, 16, 1024, 'dma')


if __name__ == '__main__':
    modes = ['survey', 'low64', 'mmio', 'dram', 'sram', 'dma']
    if len(sys.argv) == 2 and sys.argv[1] in modes:
        globals()[sys.argv[1]]()
    else:
        print 'usage: %s (%s)' % (sys.argv[0], ' | '.join(modes))
