/*
 * This C++ header file is available by default in code compiled
 * for the coastermelt backdoor. Put useful hardware definitions
 * and shortcuts here!
 */

#pragma once
#include "console.h"
#include "ts01_defs.h"

// Aliases for the pad
static uint32_t *wordp = (uint32_t *) pad;
static uint16_t *halfp = (uint16_t *) pad;
static uint8_t  *bytep = (uint8_t *) pad;


// ------------------------------------------------------------------------


// Slow and steady; there are faster ones in ts01_defs.h
void memcpy(void *dst, const void *src, unsigned count)
{
	auto dst_p = (uint8_t*) dst;
	auto src_p = (const uint8_t*) src;
	while (count--) {
		*dst_p = *src_p;
		src_p++;
		dst_p++;
	}
}

// Slow and steady; there are faster ones in ts01_defs.h
void memset(void *dst, unsigned c, unsigned count)
{
	auto dst_p = (uint8_t*) dst;
	while (count--) {
		*dst_p = c;
		dst_p++;
	}
}

char *strcpy(char *dst, const char *src)
{
	auto dst_p = dst;
	while (*dst_p = *src) {
		src++;
		dst_p++;
	}
	return dst;
}


// ------------------------------------------------------------------------


// Default handler for %hook, logs to the console
void default_hook(uint32_t* regs)
{
	console("Hello World\n");
}
