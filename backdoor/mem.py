# Functions for poking at the MT1939's memory management hardware, and using
# that to do weird debuggy things. You have entered the super weird part of
# the debugger, folks! Beware all ye icache.

__all__ = [
    'poke_orr', 'poke_bic',
    'ivt_find_target', 'ivt_set', 'ivt_get',
    'overlay_set', 'overlay_get', 'overlay_hook',
]

import code, dump, re


def poke_orr(d, address, word):
    """Read-modify-write sequence to bitwise OR, named after the ARM instruction"""
    d.poke(address, d.peek(address) | word)


def poke_bic(d, address, word):
    """Read-modify-write to bitwise AND with the inverse, named after the ARM instruction"""
    d.poke(address, d.peek(address) & ~word)


def ivt_find_target(d, address):
    """Disassemble an instruction in the IVT to locate the jump target
    The interrupt vector table has shim instructions of the form:

       ldr pc, [pc, #n]    ; 0xNNNNNN

    These have a nearby literal pool with the actual handler addresses.
    If we're going to patch interrupt vectors, we need the latter addresses.
    This uses the disassembly to find out.
    """
    text = code.disassemble(d, address, 4, thumb=False)
    m = re.search(r'\tldr\t[^;]*; *0x(.*)', text)
    return int(m.group(1), 16)


def ivt_get(d, address):
    """Read the target address of a long jump in the interrupt vector table"""
    return d.peek(ivt_find_target(d, address))


def ivt_set(d, address, handler):
    """Change the target address of a jump in the interrupt vector table.
    Assumes the table is in RAM.
    """
    d.poke(ivt_find_target(d, address), handler)


def overlay_set(d, address, wordcount = 1):
    """Set up a RAM overlay region, up to 4kB, mappable anywhere in the low 8MB.
    If address is None, disables the overlay.
    """
    control = 0x4011f04
    poke_bic(d, control, 0x200)
    poke_bic(d, control, 0x2000)
    if address is None:
        d.poke(control + 0x0c, 0xffffffff)
        d.poke(control + 0x10, 0x00000000)
    else:
        if address & 3:
            raise ValueError("Overlay mapping address must be word aligned")
        d.poke(control + 0x0c, address)
        d.poke(control + 0x10, address + wordcount*4 - 1)
        poke_orr(d, control, 0x200)
        poke_orr(d, control, 0x2000)


def overlay_get(d):
    """Get the current extent of the RAM overlay.
    Returns an (address, wordcount) tuple.
    """
    control = 0x4011f04
    address = d.peek(control + 0x0c)
    limit = d.peek(control + 0x10)
    return (address, (limit - address + 3) / 4)


def overlay_hook(d, hook_address, handler,
    includes = code.includes, defines = code.defines,
    handler_address = code.pad, va = 0x500000, verbose = False
    ):
    """Inject a C++ hook into Thumb code executing from Flash memory.
    All registers are bridged bi-directionally to C++ variables in the hook.
    """

    # Steps to make this crazy thing work:
    #
    #   - Map some movable RAM over the part of flash we're hooking
    #   - That RAM is has a software interrupt instruction in it
    #   - We have our own handler in RAM, patched into the vector table
    #   - That handler cleans up the mess from our hook, and calls C++ code
    #   - The C++ code accesses its registers via a saved copy on the stack
    #   - The handler returns, and the hooked code continues on its way.
    #
    # Actually, we do this in a slightly different order.
    #
    #   - Compile the C++ code first, since we want to report errors quickly
    #   - Actually we'll set this all up behind the scenes then instantly
    #     turn on the overlay mapping. That should make it relatively save
    #     to use this on live code, which we will be.

    handler_len = code.compile(d, handler_address, """{

        // Registers saved on the stack by our asm trampoline
        uint32_t* regs = (uint32_t*) arg;

        %s                     // Alias array to r0-15
        uint32_t& ip = r12;    // Additional names for r12-r15
        uint32_t& sp = r13;
        uint32_t& lr = r14;
        uint32_t& pc = r15;

        { %s; }   // Handler block, with one free semicolon
        0;        // Unused return value for r0

        }""" % (
            ''.join( 'uint32_t& r%d = regs[%d];\n' % (i,i) for i in range(16) ),
            handler
        ),

        # This compile inherits variables and blocks from the shell
        includes = includes, defines = defines)

    # The hook location doesn't have to be word aligned, but the overlay
    # does. So, keep track of where the ovl starts. For simplicity, we
    # always make the overlay the same size, 8 bytes.

    ovl_address = hook_address & ~3
    ovl_size = 8

    # That overlay is mostly a copy of the data we're covering up.
    # Position the overlay away from flash, so we get a clean copy.
    # Then read and disassemble it, starting the disassembly at the hook address.

    overlay_set(d, va)
    ovl_data = dump.read_block(d, ovl_address, ovl_size)
    ovl_asm = code.disassemble_string(ovl_data[hook_address - ovl_address:], address=hook_address)
    ovl_asm_lines = code.disassembly_lines(ovl_asm)

    print ovl_asm_lines
    return

    # We have a small assembly-language 'trampoline' to bridge the differences
    # in calling convention between the unary C++ function above and... a weird
    # block of mapped SRAM we jammed into a compiled function's program flow.
    #
    # For starters, it puts all the registers on the stack and passes a pointer
    # to this block as the arg to C++, via r0. This same block is restored on
    # exit, so it's easy to inspect and modify any register including the
    # return address.
    #
    # The other big job we have is to hold a relocated copy of those 8 bytes
    # we patched over. This might require relocating constants from the
    # original code to appear near enough (in the trampoline constant pool)

    trampoline_address = (handler_address + handler_len + 0xf) & ~0xf
    trampoline_len = code.assemble(d, trampoline_address, """

        @ Patched version of the original instructions we replaced to get here

        %(replaced_code)s

    ldr pc, =hook_address+8



        @ Trampoline to run the hook and return to the original code

        push    {r0}                   @ Allocate stack placeholder for pc
        push    {lr}                   @ Saved lr

        mov     lr, sp                 @ Calculate the original sp, and save it
        add     lr, #8
        push    {lr}

        push    {r0-r12}               @ Save all GPRs

        mov     r0, sp                 @ Leave sp in C++ arg (r0)

        ldr     r1, =hook_address+8    @ Return address from hook
        str     r1, [r0, 15*4]         @ Store where "pop {pc}" will find it

        ldr     r1, =handler_address   @ Call C++ code
        blx     r1

        pop     {r0-r12}               @ Restore GPRs
        pop     {lr}                   @ Discard restored stack pointer
        pop     {lr}                   @ Restore lr and pc separately (ARM limit)
        pop     {pc}

        @ Relocation pool for the replaced code

        %(reloc)s                      

        """ % locals(), defines=locals())
 
    # Assemble a long jump onto our overlay, then move it into place.
    # Now the new patch is active!

    overlay_set(d, va, 2)
    code.assemble(d, va, "ldr pc, =trampoline_address", defines=locals())
    overlay_set(d, hook_address, 2)

    if verbose:
        print "* Handler compiled to %x bytes, loaded at %x" % (handler_len, handler_address)
        print "* Trampoline assembled to %x bytes, loaded at %x" % (trampoline_len, trampoline_address)
        print code.disassemble(d, trampoline_address, trampoline_len)
        print "* Hook inserted at %x" % hook_address
        print code.disassemble(d, hook_address, 8)
