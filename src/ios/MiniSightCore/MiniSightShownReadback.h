#ifndef MINISIGHT_SHOWN_READBACK_H
#define MINISIGHT_SHOWN_READBACK_H
#import <Foundation/Foundation.h>
#import <math.h>
#import <sys/stat.h>
#import <fcntl.h>
#import <unistd.h>
#import <errno.h>
#import <string.h>
/* Shared existing 0/1 transport. No inference from runtime ON over a file hide.
   Foundation-only so fixtures execute this exact read/write, not a cloned model. */
static inline NSString *MSMusicShownPath(NSString *container) {
    if (![container isKindOfClass:NSString.class] || !container.length || !container.isAbsolutePath) return nil;
    return [container stringByAppendingPathComponent:@"Documents/MiniSight/shown"];
}
static inline NSDictionary *MSMusicShownEvidence(NSString *container, id runtimeShown) {
    NSString *path = MSMusicShownPath(container);
    BOOL known = NO, shown = NO;
    NSString *identity = @"";
    int fd = path ? open(path.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC) : -1;
    if (fd >= 0) {
        struct stat before, after;
        memset(&before, 0, sizeof(before)); memset(&after, 0, sizeof(after));
        char bytes[2] = {0}; ssize_t count = -1;
        if (fstat(fd, &before) == 0 && S_ISREG(before.st_mode) && before.st_size == 1) {
            do { count = read(fd, bytes, sizeof(bytes)); } while (count < 0 && errno == EINTR);
            if (fstat(fd, &after) == 0) {
#if defined(__APPLE__)
                long nanos = after.st_mtimespec.tv_nsec;
                BOOL sameTime = before.st_mtimespec.tv_sec == after.st_mtimespec.tv_sec && before.st_mtimespec.tv_nsec == nanos;
#else
                long nanos = after.st_mtim.tv_nsec;
                BOOL sameTime = before.st_mtim.tv_sec == after.st_mtim.tv_sec && before.st_mtim.tv_nsec == nanos;
#endif
                known = count == 1 && (bytes[0] == '0' || bytes[0] == '1') && after.st_size == 1 &&
                    S_ISREG(after.st_mode) && before.st_dev == after.st_dev && before.st_ino == after.st_ino && sameTime;
                shown = known && bytes[0] == '1';
                if (known) identity = [NSString stringWithFormat:@"%llu:%llu:%lld:%ld",
                    (unsigned long long)after.st_dev, (unsigned long long)after.st_ino, (long long)after.st_mtime, nanos];
            }
        }
        close(fd);
    }
    double value = [runtimeShown isKindOfClass:NSNumber.class] ? [runtimeShown doubleValue] : NAN;
    BOOL runtimeKnown = isfinite(value) && (value == 0 || value == 1);
    return @{@"_minisightShownKnown": @((BOOL)known), @"_minisightShown": @((BOOL)(known && shown)),
        @"_minisightShownIdentity": identity,
        @"_minisightRuntimeShownKnown": @((BOOL)runtimeKnown), @"_minisightRuntimeShown": @((BOOL)(runtimeKnown && value == 1))};
}
static inline BOOL MSMusicWriteShownVerified(BOOL shown, NSString *container) {
    NSString *path = MSMusicShownPath(container);
    if (!path) return NO;
    if (![NSFileManager.defaultManager createDirectoryAtPath:path.stringByDeletingLastPathComponent
        withIntermediateDirectories:YES attributes:nil error:nil]) return NO;
    NSString *value = shown ? @"1" : @"0";
    if (![[value dataUsingEncoding:NSUTF8StringEncoding] writeToFile:path atomically:YES]) return NO;
    NSDictionary *readback = MSMusicShownEvidence(container, @((BOOL)shown));
    return [readback[@"_minisightShownKnown"] boolValue] && [readback[@"_minisightShown"] boolValue] == shown;
}
#endif
