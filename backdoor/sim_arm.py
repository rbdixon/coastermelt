# The jankiest simulator for our janky debugger.
#
# Designed for tracing firmware execution, and untangling code flow while
# talking to actual in-system hardware. The ARM CPU runs (very slowly) in
# simulation in Python, proxying its I/O over a debug port. We need a debug
# port that owns its own main loop, so this doesn't work with the default
# SCSI/USB port, it requires the hardware hack %bitbang interface.
#
# CPU state is implemented as a flat regs[] array, with a few special indices.
# This can be small because it doesn't understand machine code, just assembly
# language. This is really more of an ARM assembly interpreter than a CPU
# simulator, but it'll be close enough.

__all__ = [ 'simulate_arm' ]

from code import *
from sim_arm_core import *

includes['sim_arm'] = '#include "sim_arm.h"'


def simulate_arm(device):
    """Create a new ARM simulator, backed by the provided remote device
    Returns a SimARM object with regs[], memory, and step().
    """
    m = SimARMMemory(device)

    # These only exist during boot; after we hit the main loop, all skips are cleared.
    m.skip(0x04001000, "Reset control?")
    m.skip(0x04002088, "LED / Solenoid GPIOs, breaks bitbang backdoor")
    m.skip(0x04030f04, "Memory region control flags")
    m.skip(0x04030f20, "DRAM memory region, contains backdoor code")
    m.skip(0x04030f24, "DRAM memory region, contains backdoor code")
    m.skip(0x04030f40, "Stack memory region")
    m.skip(0x04030f44, "Stack memory region")

    m.local_ram(0x1c00000, 0x1c2ffff)
    m.local_ram(0x1f00000, 0x200ffff)

    # Test the HLE subsystem early
    m.patch(0x168530, 'nop', thumb=False, hle='println("----==== W H O A ====----")')

    # Stub out a loop during init that seems to be spinning with a register read inside (performance)
    m.patch(0x0007bc3c, 'nop; nop')

    # Stub out encrypted functions related to DRM. Hopefully we don't need to bother supporting them.
    m.patch(0x11080, '''
        mov     r0, #0
        bx      lr
    ''', thumb=False, hle='''
        println("Stubbed DRM functions at 0x11000");
    ''')

    # This routine overlays another function from flash with a chunk of RAM, presumably for speed.
    # It just makes things slower here; stub it out, and log that it's happening.
    m.patch(0xcfce8, '''
        bx      lr
    ''', hle='''
        console("overlay_flash_with_ram", r0);
        println(" (stub)");
    ''')

    # Low level read from 8051
    m.patch(0x4b6a8, '''
        bx      lr
    ''', hle='''
        console("CPU8051::cr_read ", r0);
        r0 = CPU8051::cr_read(r0);
        println(" ->", r0);
    ''')

    # Low level write to 8051. Pack args into r0 to keep this down to one round-trip
    m.patch(0x4b6d4, '''
        lsls    r0, #8
        lsrs    r0, #8
        lsls    r1, #24
        eors    r0, r1
        pop     {r4-r6, pc}
    ''', hle='''
        uint32_t reg = 0x04000000 | ((r0 << 8) >> 8);
        uint8_t value = r0 >> 24;
        console("CPU8051::cr_write", reg);
        println(" <-", value);
        CPU8051::cr_write(reg, value);
    ''')

    # Don't bother copying 8051 firmware to DRAM (performance)
    m.patch(0xd7608, '''
        pop     {r4,pc}
    ''', hle='''
        println("Skipped copying 8051 firmware to DRAM");
    ''')

    # Install 8051 firmware directly from the TS01 image in flash memory
    # The original function here calculates a checksum along the way.
    m.patch(0xd764c, '''
        nop
        nop
    ''', hle='''
        println("CPU8051::firmware_install");
        CPU8051::firmware_install((const uint8_t*) 0x17f800, 0x2000);
    ''')

    # This function checksums the 8051 firmware, verifies it, and writes to d51
    m.patch(0x4cfc0, '''
        pop     {r3-r7, pc}
    ''', hle='''
        println("Firmware checksum = ", CPU8051::firmware_checksum());
        CPU8051::cr_write(0x41f4d51, 6);
        r0 = 0;  // success
    ''')

    # Autostep through the firmware decompression code; it's very slow with tracing on.
    m.hook(0x168928, autostep_until(0x168d04, 'firmware decompression function'))

    # Use some hook functions to multiplex the main loop and IRQ handlers, to
    # make this easier to follow (and avoid implementing real interrupts

    def fn(arm):
        # Clear all our skips when we hit the main loop
        arm.memory.skip_stores.clear()

        # First ISR, 0x18
        print "SIM: isr_18"
        arm.irq_saved = arm.state
        arm.regs[15] = 0x158
        arm.regs[13] = 0x20009d0
        arm.thumb = False
    m.hook(0x18cc8, fn)

    def fn(arm):
        # Next ISR
        print "SIM: isr_1c"
        arm.regs[15] = 0x22114
        arm.regs[13] = 0x20009d0
        arm.thumb = False
    m.hook(0x190, fn)

    def fn(arm):
        # Return to the main loop
        print "SIM: main loop"
        arm.state = arm.irq_saved
    m.hook(0x2203e, fn)
    m.hook(0x22138, fn)

    # Our simulation goes way too slow to use the real timer directly; for the
    # low-level code this doesn't seem to be a problem, but it throws the
    # higher-level functions into an infinite loop if the timer advances too
    # quickly. The higher level functions use a routine at 8519c to read a
    # 16-bit timer at a selected frequency. To help simulation coverage, this
    # returns an integer that advances by 1 every time it's read.

    sim_clock = [0]
    rates = ('512*1024 Hz', '16*1024 Hz', '1024 Hz')
    def fn(arm):
        sim_clock[0] = (sim_clock[0] + 1) & 0xffff
        print "SIM: Fake clock %04x (requested rate %s)" % (sim_clock[0], rates[arm.regs[0]])
        arm.regs[0] = sim_clock[0]
    m.patch(0x8519c, 'bx lr')
    m.hook(0x8519c, fn)

    # Thought that would fix this function at c045e which I'm calling
    # fancy_delay() for now. It reads some data structures to calculate a
    # delay, but it does some fancy things with compensating for 16-bit timer
    # rollover and it generally seems like it won't work right at all in
    # simulation. Stub it.
    m.patch(0xc0460, 'pop {r3-r7, pc}')

    return SimARM(m)


def autostep_until(breakpoint, message):
    """Return a hook function that continuously steps until the breakpoint"""
    def fn(arm):
        print "SIM: autostep until %08x, %s" % (breakpoint, message)
        while arm.regs[15] != breakpoint:
            arm.step(repeat=1000000, breakpoint=breakpoint)
            print "SIM: still autostepping..."
        print "SIM: autostep breakpoint reached"
    return fn

