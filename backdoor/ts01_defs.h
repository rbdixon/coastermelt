/*
 * Things we've noticed in the TS01 firmware
 */

#pragma once
#include <stdint.h>

auto eject = (void(*)()) 0xd3df1;

auto aligned_memcpy = (void(*)(void *dst, const void *src, unsigned byte_count)) 0x16558c;
auto aligned_bzero = (void(*)(void *dst, unsigned byte_count)) 0x1655f8;
auto aligned_fill = (void(*)(void *dst, unsigned byte_count, unsigned word_pattern)) 0x1655fc;
