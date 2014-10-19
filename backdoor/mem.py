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
    return code.ldrpc_source_address(code.disassembly_lines(text)[0])


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
    handler_address = code.pad, va = 0x500000, verbose = False,
    ):
    """Inject a C++ hook into Thumb code executing from Flash memory.
    All registers are bridged bi-directionally to C++ variables in the hook.
    """

    if hook_address & 1:
        raise ValueError("Hook address must be halfword aligned")

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
        uint32_t* regs = (uint32_t*) arg;

        %s                     // Alias array to r0-15
        uint32_t& ip = r12;    // Additional names for r12-r15
        uint32_t& sp = r13;
        uint32_t& lr = r14;
        uint32_t& pc = r15;
        uint32_t& cpsr = regs[-1];

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

    overlay_set(d, va, ovl_size)

    ovl_data = dump.read_block(d, ovl_address, ovl_size)
    ovl_asm = code.disassemble_string(ovl_data[hook_address - ovl_address:], address=hook_address)
    ovl_asm_lines = code.disassembly_lines(ovl_asm)

    # The next instruction is where we return from the hook.
    # Fill the entire instruction we're replacing (2 or 4 bytes)
    # with an arbitrary breakpoint we'll use to enter our ISR.
    #
    # We use a bkpt instead of svc for a subtle but critical
    # reason- most of the code here seems to be in svc mode
    # already, and this architecture requires software support
    # for nesting svc's. Our hook would need to be much bigger
    # to include push/pop instructions, yuck.
    #
    # Right now we use an arbitrary number as the only bkpt code
    # and never check this in the handler. This could be used
    # to identify one of several hooks in the future.

    return_address = ovl_asm_lines[1].address

    patched_ovl_data = (
        ovl_data[:hook_address - ovl_address] +
        '\xbe' * (return_address - hook_address) +
        ovl_data[return_address - ovl_address:]
    )

    # Our overlay is complete, store it to RAM while it's mapped to our temp VA

    dump.poke_words(d, va, dump.words_from_string(patched_ovl_data))

    # Now back to the instruction we're replacing...
    # PC-relative loads are common enough that we try to fix them up. A lot of things
    # are too much trouble to relocate, though, and we'll throw up a NotImplementedError.

    reloc = ovl_asm_lines[0]

    word = code.ldrpc_source_word(d, reloc)
    if word is not None:
        # Relocate to the assembler's automatic constant pool
        reloc.args = reloc.args.split(',')[0] + ', =0x%08x' % word

    if reloc.op != 'bl' and reloc.op.startswith('b'):
        raise NotImplementedError("Can't hook branches yet: %s" % reloc)
    if reloc.args.find('pc') > 0:
        raise NotImplementedError("Can't hook instructions that read or write pc: %s" % reloc)
    if reloc.args.find('sp') == 0 or reloc.op in ('push', 'pop'):
        raise NotImplementedError("Can't hook instructions that modify sp: %s" % reloc)

    # The ISR lives just after the handler, in RAM. It includes:
    #
    #   - Register save/restore
    #   - Invoking the C++ hook function with a nice flat regs[] array
    #   - A relocated copy of the instruction we replaced with the bkpt
    #   - Returning to the right address after the hook

    isr_address = (handler_address + handler_len + 0x1f) & ~0x1f
    isr_len = code.assemble(d, isr_address, """

        @ Save state and lay out the stack:
        @
        @   [sp, #72+4*13]    pc
        @   [sp, #72+4*12]    r12
        @   ...               ...
        @   [sp, #72+4*1]     r1
        @   [sp, #72+4*0]     r0
        @   [sp, #8+4*15]     regs[15] / r15 (pc)
        @   [sp, #8+4*14]     regs[14] / r14 (lr)
        @   [sp, #8+4*13]     regs[13] / r13 (sp)
        @   [sp, #8+4*12]     regs[12] / r12
        @   ...               ...
        @   [sp, #8+4*2]      regs[ 2] / r2
        @   [sp, #8+4*1]      regs[ 1] / r1
        @   [sp, #8+4*0]      regs[ 0] / r0
        @   [sp, #4]          regs[-1] / cpsr
        @   [sp, #0]          (padding)
        @
        @ This is a little wasteful of stack RAM, but it makes the layout as
        @ convenient as possible for the C++ code by keeping its registers in
        @ order.

        push    {r0-r12, lr}      @ Save everything except {sp, pc}
        push    {r0-r2}           @ Placeholders for regs[13] through regs[15]
        push    {r0-r12}          @ Initial value for regs[0] through regs[12]
        mrs     r11, spsr         @ Saved psr, becomes regs[-1]
        mrs     r10, cpsr         @ Also save handler's cpsr to regs[-2]
        push    {r10-r11}         @ (we needed 8-byte alignment anyway)

        @ Patch correct values into regs[].
        @
        @ At this point r0-r12 are fine (assuming we don't care about r8-r12
        @ in FIQ mode) and CPSR is fine, but all of r13-r15 need work.

        @ For r15, we know the return pointer but pc should actually point to
        @ the previous instruction, the one we hooked. Bake that at compile
        @ time for now. If we implement support for multiple hooks, this
        @ should tell the handler which one was hit.

        ldr     r0, =hook_address
        str     r0, [sp, #8+4*15]

        @ For r13-r14, we need to take a quick trip into the saved processor
        @ mode to retrieve them. If we came from user mode, we'll need to use
        @ system mode to read the registers so we don't get ourselves stuck.

        bic     r8, r10, #0xf     @ CPSR, without the low 4 mode bits
        ands    r9, r11, #0xf     @ Look at the saved processor mode, low 4 bits, set Z
        orreq   r9, r9, #0xf      @ if (r9==0) r9 = 0xf; (user mode -> system mode)
        orr     r8, r9            @ Same cpsr, new mode

        msr     cpsr_c, r8        @ Quick trip...
        mov     r4, r13
        mov     r5, r14
        msr     cpsr_c, r10       @ Back to the handler's original mode

        str     r4, [sp, #8+4*13]
        str     r5, [sp, #8+4*14]

        @ Now our regs[] should be consistent with the state the system was in
        @ before hitting our breakpoint. Call the C++ handler.

        add     r0, sp, #8              @ r0 = regs[]
        adr     lr, from_handler        @ Long call to C++ handler
        ldr     r1, =handler_address+1
        bx      r1
    from_handler:





        add     r0, sp, #8+16*4
        ldm     r0, {r0-r12}            @ Restore GPRs so we can run the relocated instruction
        %(reloc)s                       @ Relocated instruction from the hook location
        stm     r0, {r0-r12}            @ Save GPRs again

        pop     {r10-r11}               @ Take cpsr off the stack
        msr     spsr_cxsf, r11          @ Put saved cpsr in spsr, ready to restore
        add     sp, #4*16               @ Skip regs[]
        ldmfd   sp!, {r0-r12, pc}^      @ Return from SVC, and restore cpsr

        """ % locals(), defines=locals(), thumb=False)

    # Install the ISR, then finally the code overlay. Now our hook is active!

    bkpt_prefetch_abort_vector = 0xc
    ivt_set(d, bkpt_prefetch_abort_vector, isr_address)
    overlay_set(d, ovl_address, ovl_size/4)
 
    if verbose:
        print "* Handler compiled to 0x%x bytes, loaded at 0x%x" % (handler_len, handler_address)
        print "* ISR assembled to 0x%x bytes, loaded at 0x%x" % (isr_len, isr_address)
        print "* Hook at 0x%x, returning to 0x%x" % (hook_address, return_address)
        print "* RAM overlay, 0x%x bytes, loaded at 0x%x" % (ovl_size, ovl_address)

        # Show a before-and-after view of the patched region
        print code.side_by_side_disassembly(
            code.disassembly_lines(ovl_asm),   # Original unpatched disassembly on the left
            code.disassembly_lines(            # Fresh disassembly on the right
                code.disassemble(d, ovl_address, ovl_size)))

