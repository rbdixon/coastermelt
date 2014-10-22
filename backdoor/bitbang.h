/*
 * We have %console, and it's great when USB works. But really we'd like
 * to have our own pipe instead of stealing one from TS01, so we can
 * debug USB.
 *
 * This file is about a low-level bitbang serial port that tries to work
 * anywhere. You'll need to attach the serial port to the drive's PCB:
 *
 *      GND:  Many options. I used the 0-ohm resistor on the left edge.
 *
 *       RX:  We're using the LED signal prior to its slow driver.
 *            Tap this from the via adjacent to (and connected to)
 *            pin 10 on the TPIC1391 motor controller chip.
 *
 *       TX:  You can't transmit to the bitbang port yet. I'd like to
 *            try this with the tray eject button if we need it.
 *
 * The output format is 57600/8-N-1.
 *
 * Probably doesn't yet work from a cold start- there's likely some
 * init needed for the LED GPIO and the system timer.
 */

#pragma once
#include <stdint.h>
#include "console.h"


void bitbang(char c)
{
	// Bitbang 57600/8-N-1 serial from the LED output. The actual LED drive
	// transistor is slow, but you can pull a clean 3.3v serial signal from
	// pin 10 on the TPIC1391 motor driver chip.

	critical_section crit;
	auto& timer = *(volatile uint32_t*) 0x4002078;
	auto& reg = *(volatile uint32_t*) 0x4002088;

	uint32_t mark = reg | 0x2000000;
	uint32_t space = reg & ~0x2000000;

	uint32_t shift = (0x100 | c) << 1;
	unsigned bitcount = 10;
	uint32_t t = timer;

	while (bitcount) {
		reg = (shift & 1) ? mark : space;
		shift >>= 1;
		bitcount--;

		t += 9;
		while ((int32_t)(timer - t) < 0);
	}
}

void bitbang(const char *str)
{
	char c;
	while ((c = *str)) {
		bitbang(c);
		str++;
	}
}

void bitbang_console()
{
	// Dump any unread data from the console buffer to the bitbang port

	uint16_t wr16 = console_buffer.next_write;
	unsigned next_read = console_buffer.next_read;

	while (wr16 != (uint16_t)next_read) {
		char c = console_buffer.bytes[(uint16_t)next_read];
		if (c == '\n') {
			bitbang('\r');
		}
		bitbang(c);
		next_read++;
	}

	console_buffer.next_read = next_read;
};
