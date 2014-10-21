// Half baked, works in progress...

#pragma once


int ipc_eject()
{
	/*
	 * Setup:
	 * 
	 *    1. Push in tray completely, no disc
	 *    2. Eject completely
	 *    3. Press in slowly, until light begins blinking but before mechanical latch
	 *    4. Tape tray at this position
	 *    5. Verify that %eject can be repeatedly issued.
	 *       Each time, you should hear 4 audible clicks from the eject solenoid.
	 *       Taping the tray just right will make this click much louder.
	 *
	 * After this, "%ec ipc_eject()" will call this function and cause 1
	 * click. This function on its own isn't enough to set up the eject or to
	 * actually make the tray eject when it's all the way in, but it's a
	 * start.
	 *
	 * I'm calling this "IPC" because it seems extremely likely this is a
	 * command to another CPU rather than a direct hardware operation, though
	 * now that I've produced 1 click rather than 4 I'm not so sure.
	 */

	auto& reg_frob1 = *(volatile uint32_t*) 0x4002088;
	auto& reg_frob2 = *(volatile uint32_t*) 0x4002010;

	reg_frob1 |= 0x20000;
	reg_frob1 |= 2;
	reg_frob1 &= ~0x200;
	reg_frob2 = (reg_frob2 & ~3) | 0xff00;

	auto& reg_op1    = *(volatile uint32_t*) 0x4206000;
	auto& reg_status = *(volatile uint32_t*) 0x4206004;
	auto& reg_op0    = *(volatile uint32_t*) 0x4206010;

	reg_op0 = 0x22b;
	reg_op1 = 0x7fff;

	int loops = 0;
	while (reg_status & 0x80000000)
		loops++;

	SysTime::wait_ms(500);

	return loops;
}
