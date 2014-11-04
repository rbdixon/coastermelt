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

    return SimARM(m)
