#ifndef MINISIGHT_NAME_WAKE_STATE_H
#define MINISIGHT_NAME_WAKE_STATE_H
#import <Foundation/Foundation.h>
/* This exact builder is used by the companion writer and the native wire
   roundtrip fixture. No microphone, persistent preference or transport I/O. */
static inline NSDictionary *MSNameWakeStateMessage(NSString *host, NSString *revision,
        BOOL lockKnown, BOOL unlocked, BOOL screenKnown, BOOL screenOff,
        BOOL allowed, BOOL busy, NSTimeInterval clock) {
    // Schema 2 separates lock facts from screen readiness. Unknown/off remain
    // closed, but never manufacture a trusted lock. All wire flags are BOOL.
    return @{ @"schema": @2, @"clock": @(clock), @"host": host, @"revision": revision,
        @"lockKnown": @((BOOL)lockKnown), @"unlocked": @((BOOL)(lockKnown && unlocked)),
        @"screenKnown": @((BOOL)screenKnown), @"screenOff": @((BOOL)screenOff),
        @"allowed": @((BOOL)(allowed && lockKnown && unlocked && screenKnown && !screenOff && revision.length > 0 && revision.length <= 128)),
        @"busy": @((BOOL)busy) };
}
#endif
