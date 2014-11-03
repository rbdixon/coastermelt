/*
 * Things we've noticed in the TS01 firmware
 */

#pragma once
#include <stdint.h>


// These simple ARM functions are both near the IVT, probably part of the OS ABI.
auto cpsr_mov_on_exit = (void(*)(uint32_t saved_cpsr)) 0x2b4;
auto cpsr_orr_on_enter = (uint32_t (*)(uint32_t bits_to_or)) 0x2bc;

// Common usage pattern for critical sections (IRQs disabled)
struct critical_section {
	unsigned saved;
	critical_section() : saved(cpsr_orr_on_enter(0xC0)) {}
	~critical_section() { cpsr_mov_on_exit(saved); }
};

// Some fast but nonstandard memory functions
auto aligned_memcpy = (void(*)(void *dst, const void *src, unsigned byte_count)) 0x16558c;
auto aligned_bzero = (void(*)(void *dst, unsigned byte_count)) 0x1655f8;
auto aligned_fill = (void(*)(void *dst, unsigned byte_count, unsigned word_pattern)) 0x1655fc;

// One of the higher-level eject functions. Can be called from the shell.
auto eject = (void(*)()) 0xd3df1;

// Low byte is an atomic flag indicating a release was detected and is pending handling.
// Other bytes appear to be part of debounce state. This is read by the main loop on the ARM,
// which calls a handler at 18eb4 if the flag is set. Not yet sure where this flag is set.
// It's in memory that may be accessible to other processors, and I don't see any code in the
// ARM firmware to set it. The ARM wouldn't need another processor to proxy this state, the
// button status also appears in 4002004. Unless it was another CPU that put it there...
auto& button_release_debounce_state = *(volatile uint32_t*) 0x1ffb288;

// This is called ALL over the place with distinctive coded constants in r0.
// Either a debug logging or inter-processor comms mechnism; either way very interesting
auto ipc_logging_message = (void(*)(uint32_t code)) 0xf6025;

// Firmware images
auto ts01_8051 = (const uint8_t*) 0x17f800;
