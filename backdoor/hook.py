# You have entered the super weird part of the debugger, folks! Beware all ye icache.

__all__ = [ 'overlay_hook' ]

from code import *
from dump import *
from mem import *


def overlay_hook(d, hook_address, handler,
    includes = includes, defines = defines,
    handler_address = pad, va = 0x500000, verbose = False,
    replace_one_instruction = False
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

    handler_len = compile(d, handler_address, """{
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

    ovl_data = read_block(d, ovl_address, ovl_size)
    ovl_asm = disassemble_string(ovl_data[hook_address - ovl_address:], address=hook_address)
    ovl_asm_lines = disassembly_lines(ovl_asm)

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
    hook_instruction_size = return_address - hook_address

    patched_ovl_data = (
        ovl_data[:hook_address - ovl_address] +
        '\xbe' * hook_instruction_size +
        ovl_data[return_address - ovl_address:]
    )

    # Our overlay is complete, store it to RAM while it's mapped to our temp VA

    poke_words(d, va, words_from_string(patched_ovl_data))

    # Now back to the instruction we're replacing...
    # PC-relative loads are common enough that we try to fix them up. A lot of things
    # are too much trouble to relocate, though, and we'll throw up a NotImplementedError.

    reloc = ovl_asm_lines[0]

    if replace_one_instruction:
        # We want to replace one instruction with the C++ function, which it turns
        # out is exactly what we do if we replace the relocation with a nop.
        reloc.op = 'nop'
        reloc.args = ''

    word = ldrpc_source_word(d, reloc)
    if word is not None:
        # Relocate to the assembler's automatic constant pool
        reloc.args = reloc.args.split(',')[0] + ', =0x%08x' % word

    if reloc.op != 'bl' and reloc.op.startswith('b'):
        raise NotImplementedError("Can't hook branches yet: %s" % reloc)
    if reloc.args.find('pc') > 0:
        raise NotImplementedError("Can't hook instructions that read or write pc: %s" % reloc)

    # The ISR lives just after the handler, in RAM. It includes:
    #
    #   - Register save/restore
    #   - Invoking the C++ hook function with a nice flat regs[] array
    #   - A relocated copy of the instruction we replaced with the bkpt
    #   - Returning to the right address after the hook

    isr_address = (handler_address + handler_len + 0x1f) & ~0x1f
    isr_len = assemble(d, isr_address, """

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
        @   [sp, #0]          regs[-2] / breakpoint_psr
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
        @
        @ For r15, there's some vestigial ARM weirdness happening.
        @ The hardware always sets lr = faulting_instruction + 4,
        @ which would make sense as a return address in 32-bit ARM
        @ mode. But with Thumb, now we need to care about the width
        @ of the instruction just to calculate a return address.
        @
        @ But actually, we don't want the return address just yet.
        @ The hook should see PC pointing to the breakpoint, then
        @ we should advance past that instruction when we execute
        @ the relocated code.

        sub     r0, lr, #4         @ After data abort, lr is faulting_instruction+4
        str     r0, [sp, #8+4*15]  @ Store to regs[15]

        @ For r13-r14, we need to take a quick trip into the saved processor
        @ mode to retrieve them. If we came from user mode, we'll need to use
        @ system mode to read the registers so we don't get ourselves stuck.
        
        bic     r8, r10, #0xf      @ Transfer low 4 mode bits
        ands    r9, r11, #0xf
        orreq   r9, r9, #0x1f      @ If user mode, switch to system mode
        orr     r8, r9

        msr     cpsr_c, r8         @ Quick trip...
        mov     r4, r13
        mov     r5, r14
        msr     cpsr_c, r10        @ Back to the handler's original mode

        str     r4, [sp, #8+4*13]
        str     r5, [sp, #8+4*14]

        @ Now our regs[] should be consistent with the state the system was in
        @ before hitting our breakpoint. Call the C++ handler! (Preserves r8-r13)

        add     r0, sp, #8              @ r0 = regs[]
        adr     lr, from_handler        @ Long call to C++ handler
        ldr     r1, =handler_address+1
        bx      r1
    from_handler:

        @ The C++ handler may have modified any of regs[-1] through regs[15].
        @
        @ We need to run the relocated instruction before leaving too.
        @ Our approach will be to load as much of this state back into the CPU
        @ as we care to, run the relocated instruction, then move the state back
        @ where it needs to go so we can return from the ISR.

        ldr     r11, [sp, #4]           @ Refresh r11 from regs[-1]

        ldr     r0, [sp, #8+4*15]       @ Load hook pc from regs[15]
        add     r0, #hook_instruction_size+1
        str     r0, [sp, #72+4*13]      @ Correct Thumb return address goes in ISR frame

        ldr     r12, =0xf000000f        @ Transfer condition code and mode bits
        bic     r8, r10, r12            @ Insert into handler cpsr (keep interrupt state)
        and     r9, r11, r12
        tst     r9, #0xf                @ If low nybble is zero, user mode
        orreq   r9, r9, #0x1f           @ If user mode, switch to system mode
        orr     r8, r9

        ldr     r4, [sp, #8+4*13]       @ Prepare r13
        ldr     r5, [sp, #8+4*14]       @ Prepare r14
        add     r12, sp, #8             @ Use r12 to hold regs[] while we're on the user stack

        msr     cpsr_c, r8              @ Back to the saved mode & condition codes
        mov     r13, r4                 @ Replace saved r13-14 with those from our stack
        mov     r14, r5
        ldm     r12, {r0-r11}           @ Restore r0-r11 temporarily

        %(reloc)s                       @ Relocated and reassembled code from the hook location
                                        @ We only rely on it preserving pc and r12.

        add     r12, #4*16              @ When we save, switch from the regs[] copy to the return frame
        stm     r12, {r0-r11}           @ Save r0-r11, capturing modifications
        mrs     r11, cpsr               @ Save cpsr from relocated code

        sub     r12, #8+4*16            @ Calculate our abort-mode sp from r12
        ldr     r10, [r12]              @ Reload breakpoint_psr from abort-mode stack
        msr     cpsr_c, r10             @ Back to abort-mode, and to our familiar stack

        ldr     r1, [sp, #4]            @ Load saved cpsr from regs[-1] again
        ldr     r0, =0xf0000000         @ Mask for condition codes
        bic     r1, r0
        and     r0, r11                 @ Condition codes from after relocated instruction
        orr     r0, r1                  @ Combine new condition codes with regs[-1]
        msr     spsr_cxsf, r0           @ Into spsr, ready to restore in ldm below

        add     sp, #8+4*16             @ Skip back to return frame
        ldmfd   sp!, {r0-r12, pc}^      @ Return from SVC, and restore cpsr

        """ % locals(), defines=locals(), thumb=False)

    # Install the ISR, then finally the code overlay. Now our hook is active!

    bkpt_prefetch_abort_vector = 0xc
    ivt_set(d, bkpt_prefetch_abort_vector, isr_address)
    overlay_set(d, ovl_address, ovl_size/4)

    # Look at our handiwork in the disassembler

    verify_asm = disassemble_context(d, hook_address)
    asm_diff = side_by_side_disassembly(
        disassembly_lines(ovl_asm),       # Original unpatched hook on the left
        disassembly_lines(verify_asm),    # Fresh context disassembly on the right
    )

    if verbose:
        print "* Handler compiled to 0x%x bytes, loaded at 0x%x" % (handler_len, handler_address)
        print "* ISR assembled to 0x%x bytes, loaded at 0x%x" % (isr_len, isr_address)
        print "* Hook at 0x%x, returning to 0x%x" % (hook_address, return_address)
        print "* RAM overlay, 0x%x bytes, loaded at 0x%x" % (ovl_size, ovl_address)
        print asm_diff

    # Most common failure mode I'm seeing now is that the overlay gets stolen or
    # the truncation bug just breaks things and the patch doesn't install.
    assert verify_asm.find('bkpt') >= 0

