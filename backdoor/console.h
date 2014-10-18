/*
 * Let's have something like printf,
 * but based on a ring buffer in some memory that's not ours.
 *
 * Also this doesn't use printf format strings, because they're actually kind
 * of terrible for a small highly optimized snippet of code like this. So
 * instead, we'll make some compile time abstraction happen.
 *
 * There's just one entry point, console(). It knows how to print lots of things.
 * If it doesn't know what you want, try adding it.
 *
 * The output goes into RAM where it's hopefully picked up by the
 * corresponding watcher program, console.py (also available as %console in
 * the shell).
 */

#pragma once
#include <stdint.h>

struct console_buffer_t {
	uint8_t bytes[0x10000];
	unsigned next_write;	// Updated continuously
	unsigned next_read;		// Just for the client's benefit, we don't touch it
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

void console(int number)
{
	for (int digit = 0; digit < 8; digit++) {
		console("0123456789abcdef"[(unsigned)number >> 28]);
		number <<= 4;
	}
}

// Up to four numbers, space separated
void console(int a, int b) { console(a); console(' '); console(b); }
void console(int a, int b, int c) { console(a, b); console(' '); console(c); }
void console(int a, int b, int c, int d) { console(a, b); console(' '); console(c, d); }

// With string prefixes and space separators
void console(const char* s, int a) { console(s); console(' '); console(a); }
void console(const char* s, int a, int b) { console(s); console(' '); console(a, b); }
void console(const char* s, int a, int b, int c) { console(s); console(' '); console(a, b, c); }
void console(const char* s, int a, int b, int c, int d) { console(s); console(' '); console(a, b, c, d); }

// With newline
void println() { console('\n'); }
void println(const char* s) { console(s); println(); }
void println(int a) { console(a); println(); }
void println(int a, int b) { console(a, b); println(); }
void println(int a, int b, int c) { console(a, b, c); println(); }
void println(int a, int b, int c, int d) { console(a, b, c, d); println(); }
void println(const char* s, int a) { console(s, a); println(); }
void println(const char* s, int a, int b) { console(s, a, b); println(); }
void println(const char* s, int a, int b, int c) { console(s, a, b, c); println(); }
void println(const char* s, int a, int b, int c, int d) { console(s, a, b, c, d); println(); }
