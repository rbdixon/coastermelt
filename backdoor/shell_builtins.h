/*
 * This C++ header file is available by default in code compiled
 * for the coastermelt backdoor. Put useful hardware definitions
 * and shortcuts here!
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
