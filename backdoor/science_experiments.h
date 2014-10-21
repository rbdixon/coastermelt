// Half baked, works in progress...

#pragma once
#include <stdint.h>
#include "ts01_defs.h"


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
		SysTime::wait_ms(100);
		set_led(0);
		SysTime::wait_ms(250);
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
		SysTime::wait_ms(4);
		set_solenoid(0);
		SysTime::wait_ms(4);
	}
}


