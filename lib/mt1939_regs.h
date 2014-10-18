/*
 * A place for definitions related to the registers on MT1939 System-on-chip hardware
 */

#pragma once
#include <stdint.h>

auto& ticks = *(uint32_t*) 0x4002078;
