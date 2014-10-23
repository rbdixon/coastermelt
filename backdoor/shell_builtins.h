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

// SoC namespace for interactive use
using namespace MT1939;

// Experimental tests and toys!
#include "science_experiments.h"

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

// SysTime is a good default time source for the shell
SysTime now() { return SysTime::now(); }
void wait_ms(unsigned ms = 1) { return SysTime::wait_ms(ms); }
void wait_sec(unsigned s = 1) { wait_ms(s * 1000); }
