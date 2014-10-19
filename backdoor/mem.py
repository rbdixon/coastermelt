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
    # with an arbitrary SVC we'll use to enter our ISR.
    #
    # Right now we use an arbitrary number as the only SVC code
    # and never check this in the handler. This could be used
    # to identify one of several hooks in the future.

    svc_instruction_number = 99  # Make it seem very arbitrary

    svc = chr(svc_instruction_number) + chr(0xdf)
    return_address = ovl_asm_lines[1].address
    svc_field = (return_address - hook_address) / len(svc) * svc

    patched_ovl_data = (
        ovl_data[:hook_address - ovl_address] +
        svc_field +
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
    #   - A relocated copy of the instruction we replaced with the SVC
    #   - Returning to the right address after the hook

    isr_address = (handler_address + handler_len + 0x1f) & ~0x1f
    isr_len = code.assemble(d, isr_address, """

        push    {r0-r12, lr}            @ Save everything except {sp, pc}
        push    {r0-r15}                @ Now make a flat regs[16] array on the stack below that
        mrs     r1, spsr                @ Save cpsr
        push    {r0-r1}                 @ Store cpsr to regs[-1], and 8-byte align
                                        @ Stack is now { _, cpsr, regs[], r0-r12, lr }
        
        add     r0, sp, #8              @ r0 = regs[]
        adr     lr, from_handler        @ Long call to C++ handler
        ldr     r1, =handler_address+1
        bx      r1
    from_handler:

        add     r0, sp, #8+16*4
        ldm     r0, {r0-r12}            @ Restore GPRs so we can run the relocated instruction
        %(reloc)s                       @ Relocated instruction from the hook location
        stm     r0, {r0-r12}            @ Save GPRs again

        pop     {r0-r1}                 @ Take cpsr off the stack
        msr     SPSR_cxsf, r1           @ Put saved cpsr in spsr, ready to restore
        add     sp, #4*16               @ Skip regs[]
        ldmfd   sp!, {r0-r12, pc}^      @ Return from SVC, and restore cpsr

        """ % locals(), defines=locals(), thumb=False)

    # Install the ISR, then finally the code overlay. Now our hook is active!

    svc_vector = 0x8
    ivt_set(d, svc_vector, isr_address)
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

