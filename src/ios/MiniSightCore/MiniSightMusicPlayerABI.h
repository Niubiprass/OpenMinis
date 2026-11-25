#ifndef MINISIGHT_MUSIC_PLAYER_ABI_H
#define MINISIGHT_MUSIC_PLAYER_ABI_H
#include <stddef.h>
#include <string.h>

/* Runtime encodings, not a guessed private header, select the call width.
 * pid_t is int on the supported Apple targets. No coercion of other ABIs. */
typedef enum {
    MSMusicPIDABIRejected = 0,
    MSMusicPIDABIInt,
    MSMusicPIDABINSInteger
} MSMusicPIDABI;
static inline MSMusicPIDABI MSMusicPIDABIForTypes(const char *result, size_t count,
    const char *receiver, const char *selector, const char *pid, const char *integer) {
    if (!result || strcmp(result, "@") || count != 3 || !receiver || strcmp(receiver, "@") ||
        !selector || strcmp(selector, ":") || !pid || !integer) return MSMusicPIDABIRejected;
    if (!strcmp(pid, "i")) return MSMusicPIDABIInt;
    if ((!strcmp(integer, "q") || !strcmp(integer, "l")) && !strcmp(pid, integer))
        return MSMusicPIDABINSInteger;
    return MSMusicPIDABIRejected;
}
#endif
