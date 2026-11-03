#ifndef MINISIGHT_RECORDER_FILE_H
#define MINISIGHT_RECORDER_FILE_H
/* Production POSIX artifact operations, also compiled by the native C tests. */
#include <errno.h>
#include <fcntl.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>
#if defined(__APPLE__)
#include <stdio.h>
#endif

static inline bool MSRLeaf(const char *name) {
    return name && *name && !strchr(name, '/') && strcmp(name, ".") && strcmp(name, "..");
}
static inline bool MSRFileCopy(const char *source, const char *directory,
        const char *temporary, atomic_bool *cancelled, uint64_t *bytes, int *dirOut) {
    *dirOut = -1; *bytes = 0;
    if (!source || !directory || !MSRLeaf(temporary)) return false;
    int dir = open(directory, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
    if (dir < 0) return false;
    int in = open(source, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    struct stat before, after;
    if (in < 0 || fstat(in, &before) || !S_ISREG(before.st_mode) || before.st_size < 1024) {
        if (in >= 0) close(in);
        close(dir); return false;
    }
    int out = openat(dir, temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (out < 0) { close(in); close(dir); return false; }
    bool ok = true;
    uint64_t count = 0;
    char buf[65536];
    for (;;) {
        if (atomic_load(cancelled)) { ok = false; break; }
        ssize_t n = read(in, buf, sizeof(buf));
        if (n < 0) { if (errno == EINTR) continue; ok = false; break; }
        if (!n) break;
        if ((uint64_t)n > (uint64_t)before.st_size - count) { ok = false; break; }
        ssize_t p = 0;
        while (p < n) {
            ssize_t w = write(out, buf + p, (size_t)(n - p));
            if (w < 0 && errno == EINTR) continue;
            if (w <= 0) { ok = false; break; }
            p += w;
        }
        if (!ok) break;
        count += (uint64_t)n;
    }
    if (count != (uint64_t)before.st_size || fstat(in, &after) ||
        after.st_size != before.st_size || atomic_load(cancelled)) ok = false;
    if (ok && fsync(out)) ok = false;
    if (close(out)) ok = false;
    close(in);
    if (!ok) { unlinkat(dir, temporary, 0); close(dir); return false; }
    *bytes = count; *dirOut = dir;
    return true;
}
static inline bool MSRFilePublishWithError(int dir, const char *temporary, const char *final,
        uint64_t bytes, atomic_bool *cancelled, bool *published, int *errorOut) {
    *published = false;
    if (errorOut) *errorOut = 0;
    if (dir < 0 || !MSRLeaf(temporary) || !MSRLeaf(final) || bytes < 1024 ||
        atomic_load(cancelled)) { if (errorOut) *errorOut = EINVAL; return false; }
    int fd = openat(dir, temporary, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    struct stat a, b;
    bool ok = fd >= 0 && !fstat(fd, &a) && S_ISREG(a.st_mode) &&
              (uint64_t)a.st_size == bytes;
    if (fd >= 0) close(fd);
    if (!ok || atomic_load(cancelled)) { if (errorOut) *errorOut = ok ? ECANCELED : (errno ? errno : EIO); return false; }
    bool linked = false;
    if (linkat(dir, temporary, dir, final, 0) == 0) {
        *published = true; linked = true;
    } else {
        int linkError = errno;
#if defined(__APPLE__)
        /* APFS normally supports same-directory hard links. If the app container
           rejects them, exclusive same-directory rename is still atomic and will
           never replace an older recording. */
        if (linkError == EPERM || linkError == EOPNOTSUPP || linkError == ENOTSUP) {
            if (renameatx_np(dir, temporary, dir, final, RENAME_EXCL) == 0) {
                *published = true;
            } else {
                if (errorOut) *errorOut = errno;
                return false;
            }
        } else {
            if (errorOut) *errorOut = linkError;
            return false;
        }
#else
        if (errorOut) *errorOut = linkError;
        return false;
#endif
    }
    fd = openat(dir, final, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    ok = fd >= 0 && !fstat(fd, &b) && S_ISREG(b.st_mode) &&
         a.st_dev == b.st_dev && a.st_ino == b.st_ino && (uint64_t)b.st_size == bytes;
    if (fd >= 0) close(fd);
    if (atomic_load(cancelled)) ok = false;
    if (ok && linked && unlinkat(dir, temporary, 0)) ok = false;
    if (ok && fsync(dir) && errno != EINVAL && errno != ENOTSUP) ok = false;
    if (!ok && errorOut) *errorOut = errno ? errno : EIO;
    return ok;
}
static inline bool MSRFilePublish(int dir, const char *temporary, const char *final,
        uint64_t bytes, atomic_bool *cancelled, bool *published) {
    return MSRFilePublishWithError(dir, temporary, final, bytes, cancelled, published, NULL);
}
static inline void MSRFileCleanup(int dir, const char *temporary, const char *final,
        bool removePublished) {
    if (dir < 0) return;
    if (MSRLeaf(temporary)) unlinkat(dir, temporary, 0);
    if (removePublished && MSRLeaf(final)) unlinkat(dir, final, 0);
    close(dir);
}
#endif
