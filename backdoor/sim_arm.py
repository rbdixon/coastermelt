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

from sim_arm_core import *


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

    # Test the HLE subsystem early    
    m.patch(0x168530, 'nop', thumb=False, hle='println("----==== W H O A ====----")')

    # Stub out a loop during init that seems to be spinning with a register read inside (performance)
    m.patch(0x0007bc3c, 'nop; nop')

    # Stub out encrypted functions related to DRM. Hopefully we don't need to bother supporting them.
    m.patch(0x00011080, 'mov r0, #0; bx lr', thumb=False, hle='println("Stubbed DRM functions at 0x11000")')

    # Try stubbing out the whole 8051 firmware download, assume it's already loaded (performance)
    m.patch(0xd764c, 'nop; nop', hle='println("Skipping 8051 firmware install")')
    m.patch(0xd7658, 'mov r0, #0; nop', hle='println("Skipping 8051 firmware checksum")')

    # Try keeping some of the RAM local (performance)
    m.local_ram(0x1c00000, 0x1c1ffff)
    m.local_ram(0x1f57000, 0x1ffffff)
    m.local_ram(0x2000600, 0x2000fff)

    return SimARM(m)
