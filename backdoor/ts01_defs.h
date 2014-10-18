/*
 * Things we've noticed in the TS01 firmware
 */

#pragma once
#include <stdint.h>

auto eject = (void(*)()) 0xd3df1;

auto memcpy = (void(*)(void *dst, const void *src, unsigned byte_count)) 0x16558c;
auto bzero = (void(*)(void *dst, unsigned byte_count)) 0x1655f8;
