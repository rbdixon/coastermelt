/*
 * This C++ header file is available by default in code compiled
 * for the coastermelt backdoor. Put useful hardware definitions
 * and shortcuts here!
 */

#pragma once
#include "console.h"
#include "ts01_defs.h"

#include "../lib/tiniest_stdlib.h"
#include "../lib/mt1939_regs.h"
using namespace MT1939;


// Aliases for the pad
static uint32_t *wordp = (uint32_t *) pad;
static uint16_t *halfp = (uint16_t *) pad;
static uint8_t  *bytep = (uint8_t *) pad;


// Default handler for %hook, log plenty of system state to the console
void default_hook(uint32_t regs[16], const char *message)
{
	println("\n :::: ", message);

	// Registers and timestamp
	console("cpsr=", regs[-1]); println(" systime=", SysTime::now());
	console("  r0= "); console_array(regs, 8);   println(" =r7");
	console("  r8= "); console_array(regs+8, 8); println(" =r15");

	// Tiny stack dump
	uint32_t *stack = (uint32_t*)regs[13];
	const char *heading1 = "sp >> ";
	const char *heading2 = "      ";
	for (unsigned lines = 8; lines; lines--) {
		console(heading1); console_array(stack, 8);
		console(" ("); console((uint32_t) stack); println(")");
		heading1 = heading2;
		stack += 8;
	}
}
