// Fixed-name local transport. No final-component symlinks, FIFOs or large reads.
#ifndef MINISIGHT_BRIDGE_IO_H
#define MINISIGHT_BRIDGE_IO_H
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <fcntl.h>
#import <sys/stat.h>
#import <unistd.h>
#import <errno.h>
static inline int MSBridgeDirectory(NSString *container) {
    if (!container.length) return -1;
    NSString *dir = [container stringByAppendingPathComponent:@"Documents/MiniSight"];
    return open(dir.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC);
}
static inline BOOL MSBridgeName(NSString *name) {
    return name.length && [name rangeOfString:@"/"].location == NSNotFound && ![name hasPrefix:@"."];
}
static inline NSDictionary *MSBridgeRead(NSString *container, NSString *name, NSUInteger limit) {
    if (!MSBridgeName(name)) return nil;
    int dir = MSBridgeDirectory(container); if (dir < 0) return nil;
    int fd = openat(dir, name.fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC);
    close(dir); if (fd < 0) return nil;
    struct stat st;
    if (fstat(fd, &st) != 0 || !S_ISREG(st.st_mode) || st.st_size < 0 || (uint64_t)st.st_size > limit) { close(fd); return nil; }
    NSMutableData *data = [NSMutableData dataWithLength:limit+1];
    size_t count = 0;
    while (count <= limit) {
        ssize_t n = read(fd, (char *)data.mutableBytes+count, limit+1-count);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0) { close(fd); return nil; }
        if (n == 0) break;
        count += (size_t)n;
    }
    close(fd); if (count > limit) return nil; data.length = count;
    id object = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    return [object isKindOfClass:NSDictionary.class] ? object : nil;
}
static inline BOOL MSBridgeWrite(NSString *container, NSString *name, NSDictionary *value) {
    if (!MSBridgeName(name)) return NO;
    NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nil];
    if (!data || data.length > 131072) return NO;
    int dir = MSBridgeDirectory(container); if (dir < 0) return NO;
    NSString *temporary = [name stringByAppendingFormat:@".%@.tmp", NSUUID.UUID.UUIDString];
    int fd = openat(dir, temporary.fileSystemRepresentation, O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW|O_CLOEXEC, 0600);
    if (fd < 0) { close(dir); return NO; }
    size_t count = 0;
    while (count < data.length) {
        ssize_t n = write(fd, (const char *)data.bytes+count, data.length-count);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break;
        count += (size_t)n;
    }
    close(fd);
    BOOL success = count == data.length && renameat(dir, temporary.fileSystemRepresentation, dir, name.fileSystemRepresentation) == 0;
    unlinkat(dir, temporary.fileSystemRepresentation, 0); close(dir);
    return success;
}
static inline void MSBridgePost(NSString *name) {
    CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
        (__bridge CFStringRef)name, NULL, NULL, true);
}
#endif
