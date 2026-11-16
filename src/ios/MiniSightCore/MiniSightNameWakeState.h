#ifndef MINISIGHT_NAME_WAKE_STATE_H
#define MINISIGHT_NAME_WAKE_STATE_H
#import <Foundation/Foundation.h>
/* This exact builder is used by the companion writer and the native wire
   roundtrip fixture. No microphone, persistent preference or transport I/O. */
static inline NSDictionary *MSNameWakeStateMessage(NSString *host, NSString *revision,
        BOOL unlocked, BOOL allowed, BOOL busy, NSTimeInterval clock) {
    return @{ @"schema": @1, @"clock": @(clock), @"host": host, @"revision": revision,
        @"unlocked": @((BOOL)unlocked),
        @"allowed": @((BOOL)(allowed && unlocked && revision.length > 0 && revision.length <= 128)),
        @"busy": @((BOOL)busy) };
}
#endif
