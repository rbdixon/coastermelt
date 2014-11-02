/*
 * High level emulation (HLE) support for the simulator.
 */

#pragma once
#include "console.h"
#include "mt1939_arm.h"


uint8_t cpu8051_sync_read_from(uint32_t reg_addr)
{
	auto trigger_reg = (volatile uint8_t*) reg_addr; 
	auto& flags_reg = *(volatile uint8_t*) 0x41f5c0c;
	auto& data_reg = *(volatile uint8_t*) 0x41f5c08;

	while (flags_reg & 0xC);
	flags_reg = 0;

	(void) trigger_reg[0];

	while (!(flags_reg & 1));
	flags_reg = 0;

	return data_reg;
}


void cpu8051_sync_write_to(uint32_t reg_addr, uint8_t value)
{
	auto data_reg = (volatile uint8_t*) reg_addr; 
	auto& flags_reg = *(volatile uint8_t*) 0x41f5c0c;

	while (flags_reg & 0xC);
	flags_reg = 0;

	data_reg[0] = value;

	while (!(flags_reg & 1));
	flags_reg = 0;
}


void cpu8051_install_firmware(const uint8_t *data, uint32_t length)
{
	cpu8051_sync_write_to(0x41f4dcc, 0x08);
 	cpu8051_sync_write_to(0x41f4d91, 0x00);
 	cpu8051_sync_write_to(0x41f4d51, 0x01);
 	cpu8051_sync_write_to(0x41f4d51, 0x00);

 	while (length--) {
	 	cpu8051_sync_write_to(0x41f4d50, *data);
	 	data++;
	}
}


uint16_t cpu8051_checksum_firmware()
{
	cpu8051_sync_write_to(0x41f4dcc, 0x08);
 	cpu8051_sync_write_to(0x41f4d91, 0x00);
 	cpu8051_sync_write_to(0x41f4d51, 0x01);
 	cpu8051_sync_write_to(0x41f4d51, 0x00);

 	uint16_t sum = 0;
 	for (unsigned length = 0x2000; length; length--) {
 		sum += cpu8051_sync_read_from(0x41f4d52);
 	}
 	return sum;
}


void cpu8051_sync_hexdump_from(uint32_t reg_addr)
{
	for (unsigned y = 0; y < 8; y++) {
		uint8_t row[16];
		for (unsigned x = 0; x < 16; x++) {
			row[x] = cpu8051_sync_read_from(reg_addr);
		}
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
