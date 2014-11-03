/*
 * High level emulation (HLE) support for the simulator.
 */

#pragma once
#include "console.h"
#include "mt1939_arm.h"

using namespace MT1939;

/*

%%ecc
cpu8051_sync_write_to(0x41f4dcc, 0x08);   // Reset control?
cpu8051_sync_write_to(0x41f4d91, 0x00);

cpu8051_sync_write_to(0x41f4d51, 0x01);   // Set address
cpu8051_sync_write_to(0x41f4d51, 0x00);                                       
cpu8051_sync_hexdump_from(0x41f4d52);

*/

//  (0, 1, 0) -> firmware + 0
//  (0, 2, 0) -> firmware, continued

void cpu8051_sync_hexdump_from(uint8_t ctrl1, uint8_t addr1, uint8_t addr2)
{
	critical_section C;

	MT1939::CPU8051::cr_write(0x41f4d91, ctrl1);
	MT1939::CPU8051::cr_write(0x41f4d51, addr1);
	MT1939::CPU8051::cr_write(0x41f4d51, addr2);  

	for (unsigned y = 0; y < 32; y++) {
		uint8_t row[16];

		for (unsigned x = 0; x < 16; x++) {
			row[x] = MT1939::CPU8051::firmware_read();
		}

		console((uint32_t)( y << 4 ));
		console(':');

		for (unsigned x = 0; x < 16; x++) {
			console(' ');
			console(row[x]);
		}

		console(' ');
		console(' ');

		for (unsigned x = 0; x < 16; x++) {
			char c = row[x];
			if (c < ' ' || c > '~') {
				c = '.';
			}
			console(c);
		}

		println();
	}
}
