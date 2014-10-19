/*
 * Let's have something like printf,
 * but based on a ring buffer in some memory that's not ours.
 *
 * This doesn't use printf format strings, because they're actually kind of
 * terrible for a small highly optimized snippet of code like this. So
 * instead, we'll make some compile time function composition and optimization
 * happen.
 *
 * There's one main entry point, console(). It knows how to print lots of
 * things. If it doesn't know what you want, try adding it. Any function named
 * console() prints its arguments in sequence, sometimes with separators if
 * applicable.
 *
 * For more specific cases where you need more control, there are variant
 * functions like console_dec().
 *
 * The output goes into RAM where it can be found by console.py when it polls.
 * (also available as %console in the shell, and as part of %ecc and %hook)
 */

#pragma once
#include <stdint.h>
#include "../lib/mt1939_regs.h"		// For printing chipset datatypes


struct console_buffer_t {
	uint8_t bytes[0x10000];
	unsigned next_write;	// Updated continuously
	unsigned next_read;		// Just for console.py to use
};

auto& console_buffer = *(console_buffer_t*) console_address;

void console(char c)
{
	unsigned index = console_buffer.next_write;
	console_buffer.bytes[index & 0xffff] = c;
	console_buffer.next_write = index + 1;
}

void console(const char* str)
{
	char c;
	while ((c = *str)) {
		console(c);
		str++;
	}
}

// (uint32_t) -> %08x
void console(uint32_t number)
{
	for (int digit = 0; digit < 8; digit++) {
		console("0123456789abcdef"[number >> 28]);
		number <<= 4;
	}
}

// One decimal digit; part of console_dec()
void console_dec_digit(uint32_t number, char &leading, uint32_t place)
{
	unsigned digit = (number / place) % 10;
	if (digit) {
		leading = '0';
		console((char)('0' + digit));
	} else {
		console(leading);
	}
}

// (uint32_t) -> dec, with width and padding specifiers
void console_dec(uint32_t number, unsigned width, char leading)
{
	switch (width) {
	default:  console_dec_digit(number, leading, 1000000000UL);
	case  9:  console_dec_digit(number, leading,  100000000UL);
	case  8:  console_dec_digit(number, leading,   10000000UL);
	case  7:  console_dec_digit(number, leading,    1000000UL);
	case  6:  console_dec_digit(number, leading,     100000UL);
	case  5:  console_dec_digit(number, leading,      10000UL);
	case  4:  console_dec_digit(number, leading,       1000UL);
	case  3:  console_dec_digit(number, leading,        100UL);
	case  2:  console_dec_digit(number, leading,         10UL);
	case  1:  console_dec_digit(number, leading,          1UL);
	case  0:  return;
	}
}

// Default width and padding
void console_dec(uint32_t n) { console_dec(n, 10, 0); }
void console_dec(unsigned int n) { console_dec(n, 10, 0); }

// (int) -> decimal
void console_dec(int number)
{
	if (number < 0) {
		console('-');
		console_dec((uint32_t) -number);
	} else {
		console_dec((uint32_t) number);
	}
}

// (SysTime) -> %d.%3d, seconds
void console(MT1939::SysTime st)
{
	console_dec(st.seconds());
	console_dec(st.milliseconds() % 1000, 3, '0');
}

// (int) -> (uint32_t), to avoid ambiguity
void console(int a) { console((uint32_t) a); }

// Up to four strings, no separator
void console(const char* a, const char* b) { console(a); console(b); }
void console(const char* a, const char* b, const char* c) { console(a, b); console(c); }
void console(const char* a, const char* b, const char* c, const char* d) { console(a, b); console(c, d); }

// Up to four numbers, space separated
void console(uint32_t a, uint32_t b) { console(a); console(' '); console(b); }
void console(uint32_t a, uint32_t b, uint32_t c) { console(a, b); console(' '); console(c); }
void console(uint32_t a, uint32_t b, uint32_t c, uint32_t d) { console(a, b); console(' '); console(c, d); }

// With string prefix
void console(const char* s, MT1939::SysTime a) { console(s); console(' '); console(a); }
void console(const char* s, uint32_t a) { console(s); console(' '); console(a); }
void console(const char* s, uint32_t a, uint32_t b) { console(s); console(' '); console(a, b); }
void console(const char* s, uint32_t a, uint32_t b, uint32_t c) { console(s); console(' '); console(a, b, c); }
void console(const char* s, uint32_t a, uint32_t b, uint32_t c, uint32_t d) { console(s); console(' '); console(a, b, c, d); }

// With newline
void println() { console('\n'); }
void println(const char* a) { console(a); println(); }
void println(const char* a, const char* b) { console(a, b); println(); }
void println(const char* a, const char* b, const char* c) { console(a, b, c); println(); }
void println(const char* a, const char* b, const char* c, const char* d) { console(a, b, c, d); println(); }
void println(uint32_t a) { console(a); println(); }
void println(uint32_t a, uint32_t b) { console(a, b); println(); }
void println(uint32_t a, uint32_t b, uint32_t c) { console(a, b, c); println(); }
void println(uint32_t a, uint32_t b, uint32_t c, uint32_t d) { console(a, b, c, d); println(); }
void println(const char* s, uint32_t a) { console(s, a); println(); }
void println(const char* s, uint32_t a, uint32_t b) { console(s, a, b); println(); }
void println(const char* s, uint32_t a, uint32_t b, uint32_t c) { console(s, a, b, c); println(); }
void println(const char* s, uint32_t a, uint32_t b, uint32_t c, uint32_t d) { console(s, a, b, c, d); println(); }
void println(MT1939::SysTime a) { console(a); println(); }
void println(const char* a, MT1939::SysTime b) { console(a, b); println(); }

// Decimal numbers with newline
void println_dec(int n) { console_dec(n); println(); }
void println_dec(unsigned int n) { console_dec(n); println(); }
