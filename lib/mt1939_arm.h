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


namespace CPU8051
{
    // Read a coprocessor control register
    uint8_t cr_read(uint32_t reg_addr)
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

    // Write to a coprocessor control register
    void cr_write(uint32_t reg_addr, uint8_t value)
    {
        auto data_reg = (volatile uint8_t*) reg_addr; 
        auto& flags_reg = *(volatile uint8_t*) 0x41f5c0c;

        while (flags_reg & 0xC);
        flags_reg = 0;

        data_reg[0] = value;

        while (!(flags_reg & 1));
        flags_reg = 0;
    }

    uint8_t status()
    {
        if (cr_read(0x41f4dcc) != 0) {
            // CPU off
            return 0;
        } else {
            // Status register, set by firmware
            return cr_read(0x41f4d91);
        }
    }

    void stop()
    {
        cr_write(0x41f4dcc, 8);     // Stop CPU
        cr_write(0x41f4d91, 0);     // Clear boot status indicator
    }

    uint8_t start()
    {
        cr_write(0x41f4d51, 6);     // Turn off memory interface?
        cr_write(0x41f4dcc, 0);     // Start CPU

        // Wait for boot, with a short timeout
        SysTime deadline = SysTime::now() + (SysTime::hz / 4);
        uint8_t result;
        do {
            result = status();
        } while (result != 1 && SysTime::now().difference(deadline) < 0);
        return result;
    }

    void firmware_write(uint8_t byte)
    {
        cr_write(0x41f4d50, byte);
    }

    uint8_t firmware_read()
    {
        return cr_read(0x41f4d52);
    }

    void firmware_rewind()
    {
        cr_write(0x41f4d51, 1);     // Reset to address 0
        cr_write(0x41f4d51, 0);     // Release address reset        
    }

    void firmware_install(const uint8_t *data, uint32_t length = 0x2000)
    {
        stop();
        firmware_rewind();
        while (length--) {
            firmware_write(*(data++));
        }
    }

    uint16_t firmware_checksum()
    {
        unsigned sum = 0;
        firmware_rewind();
        for (unsigned length = 0x2000; length; length--) {
            sum += firmware_read();
        }
        return sum;
    }
};


} // end namespace MT1939
