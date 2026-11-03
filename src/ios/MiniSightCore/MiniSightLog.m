#import "MiniSightLog.h"
#include <stdatomic.h>

static atomic_bool MSDiagEnabled;
static NSLock *MSDiagConfigLock;
static NSString *MSDiagContainer;
static dispatch_queue_t MSDiagQueue;

static void MSDiagSetup(void) {
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        MSDiagConfigLock = [NSLock new];
        MSDiagQueue = dispatch_queue_create("com.openminis.minisight.diagnostic", DISPATCH_QUEUE_SERIAL);
        atomic_init(&MSDiagEnabled, false);
    });
}

void MSDiagConfigure(BOOL enabled, NSString *container) {
    MSDiagSetup();
    [MSDiagConfigLock lock];
    MSDiagContainer = [container copy];
    [MSDiagConfigLock unlock];
    atomic_store(&MSDiagEnabled, enabled && container.length > 0);
}

void MSDiag(NSString *format, ...) {
    MSDiagSetup();
    if (!atomic_load(&MSDiagEnabled)) return;
    va_list args;
    va_start(args, format);
    NSString *body = [[NSString alloc] initWithFormat:format arguments:args];
    va_end(args);
    if (body.length > 2048) body = [body substringToIndex:2048];

    dispatch_async(MSDiagQueue, ^{
        [MSDiagConfigLock lock];
        NSString *container = [MSDiagContainer copy];
        [MSDiagConfigLock unlock];
        if (!container.length) return;
        NSString *dir = [container stringByAppendingPathComponent:@"Documents/MiniSight"];
        NSFileManager *fm = NSFileManager.defaultManager;
        [fm createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *path = [dir stringByAppendingPathComponent:@"diagnostic.log"];
        NSString *old = [dir stringByAppendingPathComponent:@"diagnostic.log.1"];
        NSDictionary *attrs = [fm attributesOfItemAtPath:path error:nil];
        if ([attrs[NSFileSize] unsignedLongLongValue] > 200 * 1024) {
            [fm removeItemAtPath:old error:nil];
            [fm moveItemAtPath:path toPath:old error:nil];
        }
        NSDateFormatter *df = [NSDateFormatter new];
        df.dateFormat = @"MM-dd HH:mm:ss.SSS";
        NSString *line = [NSString stringWithFormat:@"%@ %@\n", [df stringFromDate:NSDate.date], body];
        NSData *data = [line dataUsingEncoding:NSUTF8StringEncoding];
        if (![fm fileExistsAtPath:path]) {
            [data writeToFile:path options:NSDataWritingAtomic error:nil];
            [fm setAttributes:@{NSFilePosixPermissions: @0600} ofItemAtPath:path error:nil];
            return;
        }
        NSFileHandle *fh = [NSFileHandle fileHandleForWritingAtPath:path];
        @try {
            [fh seekToEndOfFile];
            [fh writeData:data];
        } @catch (__unused NSException *e) {}
        [fh closeFile];
    });
}
