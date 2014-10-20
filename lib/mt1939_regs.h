/*
 * A place for definitions related to the registers on MT1939 System-on-chip hardware
 */

#pragma once
#include <stdint.h>

namespace MT1939 {


struct SysTime
{
	SysTime(uint32_t t) : ticks(t) {}
	operator uint32_t() { return ticks; }
	uint32_t ticks;
	static const unsigned hz = 512 * 1024;

	int difference(SysTime b) const {
		return (int32_t) (ticks - b.ticks);
	}

	unsigned seconds() const {
		return ticks / hz;
	}

	unsigned milliseconds() const {
		// Support fractional number of ticks per millisecond
		return (uint64_t)ticks * 1000 / hz;
	}

	static SysTime now() {
		return *(volatile uint32_t*) 0x4002078;
	}

	static void wait_ticks(unsigned n) {
		SysTime ref = now();
		while (now().difference(ref) < n+1);
	}

	static void wait_ms(unsigned n) {
		wait_ticks((uint64_t)n * hz / 1000);
	}
};


} // end namespace MT1939
