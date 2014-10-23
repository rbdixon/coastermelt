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
 *       TX:  For transmit, uses the eject button. The signal is harder to
 *            get to- it's pin 50 on the flex cable, or you can find a via
 *            at the top-right corner of the SoC that connects here too.
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


uint8_t bitbang_read()
{
	// Blocking read! Disables interrupts and waits for one serial character.
	// This reads from port [4002084], which seems to be the thing we've found
	// that's most directly connected to the eject button.

	critical_section crit;
	auto& timer = *(volatile uint32_t*) 0x4002078;
	auto& reg = *(volatile uint32_t*) 0x4002084;
	uint32_t rx_mask = 0x10000000;

	uint32_t shift, bitcount, t;

	do {
		while (reg & rx_mask);	 // Wait for start bit

		shift = 0;
		bitcount = 9;
		t = timer;

		while (bitcount) {
			if (reg & rx_mask) {
				shift |= 0x100;
			}
			shift >>= 1;
			bitcount--;

			t += 9;
			while ((int32_t)(timer - t) < 0);
		}

	} while (shift & ~0xFF);	// Verify stop bit
	return shift;
}


void bitbang32(uint32_t word)
{
	// Write one little-endian 32-bit word
	bitbang(word);
	bitbang(word >> 8);
	bitbang(word >> 16);
	bitbang(word >> 24);
}


uint32_t bitbang_read32()
{
	// Blocking read of one little-endian 32-bit word
	uint32_t r = bitbang_read32();
	r |= bitbang_read32() << 8;
	r |= bitbang_read32() << 16;
	r |= bitbang_read32() << 24;
	return r;
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
}


void bitbang_backdoor()
{
	/*
	 * A debug backdoor based on the bitbang serial port. Commands:
	 *
	 * Peek         55 00 F0 word(address)                                -> word(data) word(data ^ address)
	 * Poke         55 00 E1 word(address) word(data)                     -> word(data ^ address)
	 * Peek byte    55 00 D2 word(address)                                -> byte(data) word(data ^ address)
	 * Poke byte    55 00 C3 word(address) byte(data)                     -> word(data ^ address)
	 * BLX          55 00 B4 word(address) word(r0)                       -> word(r0) word(r1) word(address ^ r0)
	 * Read block   55 00 A5 word(address) word(wordcount)                -> word(data) * wordcount word(last_data ^ (4+last_address))
	 * Fill words   55 00 96 word(address) word(pattern) word(wordcount)  -> word(pattern ^ (4+last_address)
	 * Exit         55 00 87                                              -> 55
	 * Signature    (other)                                               -> (text line)
     */

	uint32_t address, data, aux;

	// Header states
	s_sig:
		bitbang("~MeS`14 [bitbang]\r\n");

	s_55:
    	switch (bitbang_read()) {
    		case 0x55:	break;
    		default:	goto s_sig;
    	}

    s_00:
    	switch (bitbang_read()) {
    		case 0x00:	break;
    		case 0x55:  goto s_55;
    		default:	goto s_sig;
    	}

    // Opcode
    switch (bitbang_read()) {

    	case 0xF0:		// Peek
    		address = bitbang_read32();
    		data = *(uint32_t*) address;
    		bitbang32(data);
    		goto s_check;

    	case 0xE1:		// Poke
    		address = bitbang_read32();
    		data = bitbang_read32();
    		*(uint32_t*)address = data;
    		goto s_check;

    	case 0xD2:		// Peek byte
    		address = bitbang_read32();
    		data = *(uint8_t*) address;
    		bitbang(data);
    		goto s_check;

    	case 0xC3:		// Poke byte
    		address = bitbang_read32();
    		data = bitbang_read32();
    		*(uint32_t*)address = data;
    		goto s_check;

    	case 0xB4:		// BLX (call)
    		address = bitbang_read32();
    		data = bitbang_read32();
    		asm ("  mov r0, %0; "
    			 "  mov r3, %2; "
                 "  .word 0x4798; "  // blx r3
    			 "  mov %0, r0; "
    			 "  mov %1, r1; "
    			: "+r"(data), "=r"(aux)
    			: "r"(address)
    			: "memory", "r0", "r1", "r2", "r3" );
    		bitbang32(data);
    		bitbang32(aux);
    		goto s_check;

    	case 0xA5:		// Read block
    		address = bitbang_read32();
    		aux = bitbang_read32();
    		while (aux) {
    			data = *(uint32_t*)address;
    			bitbang32(data);
    			address += 4;
    			aux--;
    		}
    		goto s_check;

    	case 0x96:		// Fill words
    		address = bitbang_read32();
    		data = bitbang_read32();
    		aux = bitbang_read32();
    		while (aux) {
    			*(uint32_t*)address = data;
    			address += 4;
    			aux--;
    		}
    		goto s_check;

    	case 0x87:      // Exit
    		bitbang(0x55);
	    	return;

    	default:
    		goto s_sig;
    }

    // Common data ^ address
    s_check:
    	bitbang32(data ^ address);
    	goto s_55;
}
