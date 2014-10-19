/*
 * The tiniest standard library.
 * Stuff you wish was included in C++,
 * but usually isn't because operating systems.
 */

#pragma once
#ifdef __cplusplus
extern "C" {
#endif


// Slow and steady; there are faster ones in ts01_defs.h
void memcpy(void *dst, const void *src, unsigned count)
{
	auto dst_p = (uint8_t*) dst;
	auto src_p = (const uint8_t*) src;
	while (count--) {
		*dst_p = *src_p;
		src_p++;
		dst_p++;
	}
}

// Slow and steady; there are faster ones in ts01_defs.h
void memset(void *dst, unsigned c, unsigned count)
{
	auto dst_p = (uint8_t*) dst;
	while (count--) {
		*dst_p = c;
		dst_p++;
	}
}

void bzero(void *dst, unsigned count)
{
	memset(dst, 0, count);
}

char *strcpy(char *dst, const char *src)
{
	auto dst_p = dst;
	while (*dst_p = *src) {
		src++;
		dst_p++;
	}
	return dst;
}


#ifdef __cplusplus
}  // extern "C"
#endif
