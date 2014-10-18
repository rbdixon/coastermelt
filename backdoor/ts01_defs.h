/*
 * Things we've noticed in the TS01 firmware
 */

#pragma once
#include <stdint.h>

void (*eject)(void) = (void(*)()) 0xd3df0;
