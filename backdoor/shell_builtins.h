/*
 * This C++ header file is available by default in code compiled
 * for the coastermelt backdoor. Put useful hardware definitions
 * and shortcuts here!
 */

#pragma once
#include "ts01_defs.h"


// Aliases for the pad
static uint32_t *wordp = (uint32_t *) pad;
static uint16_t *halfp = (uint16_t *) pad;
static uint8_t  *bytep = (uint8_t *) pad;


// Default handler for %hook, saves hexdump-readable state to the pad
inline void default_hook(uint32_t* regs)
{
	wordp[0] = 'H';
}
