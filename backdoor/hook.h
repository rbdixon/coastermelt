/*
 * Default handler for %hook.
 *
 * This logs plenty of system state to the console,
 * and you can customize its output with shell variables
 *
 * hook_stack_lines, hook_show_stack, hook_show_registers,
 * hook_show_timestamp, hook_show_message
 *
 * The options can give you more stack trace, or they can
 * make the hook smaller and faster.
 */

#pragma once
#include "console.h"
#include "../lib/mt1939_regs.h"

void default_hook(uint32_t regs[16], const char *message = "default_hook()")
{
	if (hook_show_message) {
		// Message, customizable with %hook -m
		println("\n:::: ", message);
	}

	if (hook_show_timestamp) {
		// Timestamp using the monotonic system clock
		console("time", MT1939::SysTime::now());

		// Saved xPSR registers, first from the hook location itself,
		// then from inside the breakpoint handler
		console("        cpsr=", regs[-1]);
		println(" bkptpsr=", regs[-2]);
	}

	if (hook_show_registers) {
		console(" r0= "); console_array(regs, 8);   println(" =r7");
		console(" r8= "); console_array(regs+8, 8); println(" =r15");
	}

	if (hook_show_stack) {
		uint32_t *stack = (uint32_t*)regs[13];
		const char *heading1 = "sp>> ";
		const char *heading2 = "     ";
		for (unsigned lines = hook_stack_lines; lines; lines--) {
			console(heading1); console_array(stack, 8);
			console(" ("); console((uint32_t) stack); println(")");
			heading1 = heading2;
			stack += 8;
		}
	}
}
