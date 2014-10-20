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

// Shorter type names for interactive use
typedef uint8_t  u8;
typedef uint16_t u16;
typedef uint32_t u32;
typedef uint64_t u64;
typedef int8_t   i8;
typedef int16_t  i16;
typedef int32_t  i32;
typedef int64_t  i64;
