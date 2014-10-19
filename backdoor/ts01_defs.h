/*
 * Things we've noticed in the TS01 firmware
 */

#pragma once
#include <stdint.h>

auto aligned_memcpy = (void(*)(void *dst, const void *src, unsigned byte_count)) 0x16558c;
auto aligned_bzero = (void(*)(void *dst, unsigned byte_count)) 0x1655f8;
auto aligned_fill = (void(*)(void *dst, unsigned byte_count, unsigned word_pattern)) 0x1655fc;

// One of the higher-level eject functions. Can be called from the shell.
auto eject = (void(*)()) 0xd3df1;

// This is called ALL over the place with distinctive coded constants in r0.
// Either a debug logging or inter-processor comms mechnism; either way very interesting
auto ipc_logging_message = (void(*)(uint32_t code)) 0xf6025;
