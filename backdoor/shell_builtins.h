/*
 * This C++ header file is available by default in code compiled for the
 * coastermelt backdoor. Put useful hardware definitions and shortcuts here!
 *
 * Things in this file should generally only be used interactively. It's bad
 * form to write code that depends on these definitions, there's usually a
 * slightly longer way to do the same thing that's more maintainable and more
 * readable.
 */

#pragma once
#include "hook.h"
#include "console.h"
#include "ts01_defs.h"

#include "../lib/tiniest_stdlib.h"
#include "../lib/mt1939_regs.h"
using namespace MT1939;

// Aliases for the pad
static uint32_t *wordp = (uint32_t *) pad;
static uint16_t *halfp = (uint16_t *) pad;
static uint8_t  *bytep = (uint8_t *) pad;

// Terse type names for interactive use
typedef uint8_t  u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int8_t   i8;
typedef int16_t  i16;
typedef int32_t  i32;
typedef int64_t  i64;
typedef volatile uint8_t  vu8;
typedef volatile uint16_t vu16;
typedef volatile uint32_t vu32;
typedef volatile uint64_t vu64;
typedef volatile int8_t   vi8;
typedef volatile int16_t  vi16;
typedef volatile int32_t  vi32;
typedef volatile int64_t  vi64;


//// Half-baked things that don't have a good home yet

void ipc_send_4206000(unsigned op0, unsigned op1)
{
	// Send some kind of inter-processor message. ARM sends (0x22b, 0x7fff) to
	// eject the disc, and another processor taps the solenoid 4 times in a loop.
	// Sending this command on its own, however, doesn't produce the eject.

	auto& reg_op1    = *(volatile uint32_t*) 0x4206000;
	auto& reg_status = *(volatile uint32_t*) 0x4206004;
	auto& reg_op0    = *(volatile uint32_t*) 0x4206010;

	reg_op0 = op0;
	reg_op1 = op1;

	while (reg_status & 0x80000000);
}
