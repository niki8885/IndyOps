/* strndup shim. Static libgfortran on MSYS2/UCRT64 references POSIX strndup,
 * which Microsoft's Universal CRT does not provide — so a fully static link
 * (for a dependency-free, portable engine binary) fails to resolve it. This
 * supplies it on top of UCRT's strnlen.
 *
 * Only needed on MinGW: glibc/musl already provide strndup, so on Linux/macOS
 * this is an empty translation unit (the build still links it, harmlessly). */
#if defined(__MINGW32__)
#include <stdlib.h>
#include <string.h>

char *strndup(const char *s, size_t n)
{
    size_t len = strnlen(s, n);
    char *p = (char *)malloc(len + 1);
    if (p == NULL)
        return NULL;
    memcpy(p, s, len);
    p[len] = '\0';
    return p;
}
#endif
