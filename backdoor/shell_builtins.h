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


// Default handler for %hook
void default_hook(uint32_t regs[16], const char *message)
{
	console("\nt=", SysTime::now()); println(" s :: ", message);
	console("r0= "); console_array(regs, 8); println(" =r7");
	console("r8= "); console_array(regs+8, 8); println(" =r15");
	console("   cpsr= ", regs[-1]); println(" stack=[");
	uint32_t *stack = (uint32_t*)regs[13];
	println_array(stack, 8);
	println_array(stack+8, 8);
}
