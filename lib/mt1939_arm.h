/*
 * Interface to functionality accessible from the ARM processor core on the
 * Mediatek MT1939 Blu-Ray SoC.
 *
 * Copyright (c) 2014 Micah Elizabeth Scott
 * 
 * Permission is hereby granted, free of charge, to any person obtaining a copy of
 * this software and associated documentation files (the "Software"), to deal in
 * the Software without restriction, including without limitation the rights to
 * use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of
 * the Software, and to permit persons to whom the Software is furnished to do so,
 * subject to the following conditions:
 * 
 * The above copyright notice and this permission notice shall be included in all
 * copies or substantial portions of the Software.
 * 
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 * IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS
 * FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR
 * COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER
 * IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
 * CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
 */

#pragma once
#include <stdint.h>

namespace MT1939 {


struct SysTime
{
	SysTime(uint32_t t) : ticks(t) {}
	operator uint32_t() { return ticks; }
	uint32_t ticks;

	// Rollover once per 8192 seconds
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

	unsigned microseconds() const {
		// Support fractional number of ticks per microsecond
		return (uint64_t)ticks * 1000000 / hz;
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
