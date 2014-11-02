// Half baked, works in progress...

#pragma once
#include <stdint.h>
#include "console.h"
#include "ts01_defs.h"
#include "tiniest_stdlib.h"
#include "mt1939_arm.h"


int ipc_send_4206000(unsigned op0, unsigned op1)
{
	auto& reg_op1    = *(volatile uint32_t*) 0x4206000;
	auto& reg_status = *(volatile uint32_t*) 0x4206004;
	auto& reg_op0    = *(volatile uint32_t*) 0x4206010;

	reg_op0 = op0;
	reg_op1 = op1;

	int loops = 0;
	while (reg_status & 0x80000000);
		loops++;
	return loops;
}


int ipc_eject_4200000()
{
	// Thought this IPC-looking port was part of Eject, doesn't seem to
	// be necessary for the solenoid but it seems important for control
	// flow in timing the eject command, or maybe blocking SCSI traffic
	// during the operation.

	return ipc_send_4206000(0x22b, 0x7fff);
}


auto& reg_tray_mmio = *(volatile uint32_t*) 0x4002088;

void set_led(bool on)
{
	if (on)
		reg_tray_mmio &= ~0x2000000;
	else
		reg_tray_mmio |= 0x2000000;
}

void set_solenoid(bool on)
{
	if (on) {
		reg_tray_mmio |= 0x20000;
		reg_tray_mmio |= 2;
		reg_tray_mmio &= ~0x200;
	} else {
		reg_tray_mmio &= ~2;
		reg_tray_mmio |= 0x200;
	}
}

void blink_led(unsigned count = 4)
{
	// Seems to work at any time during normal firmware
	critical_section c;
	while (count--) {
		set_led(1);
		MT1939::SysTime::wait_ms(100);
		set_led(0);
		MT1939::SysTime::wait_ms(250);
	}
}

void buzz_solenoid()
{
	// Prereqs:
	//   - Drive opened
	//   - Drive closed half-way and taped
	//   - Eject run, tray doesn't actually move, 4 clicks audible
	//
	// Now when this runs, the solenoid rattles.

	critical_section c;
	unsigned count = 50;
	while (count--) {
		set_solenoid(1);
		MT1939::SysTime::wait_ms(4);
		set_solenoid(0);
		MT1939::SysTime::wait_ms(4);
	}
}


void speed_test()
{
	// Toggle the LED output as fast as we can. The actual LED driver
	// can't switch off this fast, but if we probe the signal at pin
	// 10 of the TPIC1391 chip (which has a handy via right by it) we
	// can get this signal at full rate. Let's find out what that rate is,
	// and also maybe how fast our CPU might be.

	uint32_t off = reg_tray_mmio | 0x2000000;
	uint32_t on = reg_tray_mmio & ~0x2000000;
	while (1) {

		// Just I/O
		reg_tray_mmio = on;
		reg_tray_mmio = off;
		reg_tray_mmio = on;
		reg_tray_mmio = off;
		reg_tray_mmio = on;
		reg_tray_mmio = off;
		reg_tray_mmio = on;
		reg_tray_mmio = off;

		// 100 nops, running from RAM
		asm volatile (".rept 100; nop; .endr");

		// Just I/O
		reg_tray_mmio = on;
		reg_tray_mmio = off;
		reg_tray_mmio = on;
		reg_tray_mmio = off;
		reg_tray_mmio = on;
		reg_tray_mmio = off;
		reg_tray_mmio = on;
		reg_tray_mmio = off;

		// Long sleep
		MT1939::SysTime::wait_ms(1);
	}
}


void crypto_hexdump(uint32_t address, uint32_t wordcount)
{
	// These registers are used to set up decryption overlay regions for running
	// encrypted functions. Trying to see if we can hexdump plaintext.

	critical_section c;

	auto& reg_control = *(volatile uint32_t*) 0x4011064;
	auto& reg_begin = *(volatile uint32_t*) 0x4011068;
	auto& reg_end = *(volatile uint32_t*) 0x401106c;

	reg_control &= ~4;
	reg_begin = address;
	reg_end = address + (wordcount * 4) - 1;
	reg_control |= 4;

	console_array((const uint32_t*) address, wordcount);

	reg_control &= ~4;
}


uint32_t invoke_encrypted_11000(uint32_t x = 0)
{
	// Function f5024 is a dispatcher for encrypted functions.
	// 11000 is the primary encrypted handler function, and the first one we hit in simulation.
	// This experiment attempts to pare f5024 down to the very minimum necessary to invoke and return from 11000

	uint32_t op = 0;
	uint32_t arg = 0;

	//critical_section c;

	auto& reg_sys = *(volatile uint32_t*) 0x4000000;
	auto& reg_control = *(volatile uint32_t*) 0x4011064;
	auto& reg_begin = *(volatile uint32_t*) 0x4011068;
	auto& reg_end = *(volatile uint32_t*) 0x401106c;
	auto fn = (uint32_t(*)(uint32_t, uint32_t)) 0x11000;

	// What is this? Disabling cache? It's the very first register.
	reg_sys &= ~0x10;

	reg_begin = 0x11080;
	reg_end = 0x13720;
	reg_control |= 4;

	uint32_t result = fn(op, arg);

	// If we leave this on, something hangs later!?
	reg_control &= ~4;

	return result;
}
