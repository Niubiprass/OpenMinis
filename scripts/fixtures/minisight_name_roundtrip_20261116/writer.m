#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#include <stdio.h>
#include <stdlib.h>
#import "MiniSightNameWakeState.h"

/* Calls the production inline builder, never a fixture implementation. Only
 * synthetic values and files in the runner's temporary directory are used. */
static NSUInteger assertions = 0;
static void Check(BOOL value, NSString *label) {
    ++assertions;
    if (!value) {
        fprintf(stderr, "FAIL assertion: %s\n", label.UTF8String);
        exit(1);
    }
}
static void Write(NSString *directory, NSString *name, NSDictionary *message,
                  BOOL unlocked, BOOL allowed, BOOL busy) {
    for (NSString *field in @[@"unlocked", @"allowed", @"busy"]) {
        Check(CFGetTypeID((__bridge CFTypeRef)message[field]) == CFBooleanGetTypeID(),
              [@"writer CFBoolean " stringByAppendingString:field]);
    }
    Check([message[@"unlocked"] boolValue] == unlocked, @"writer unlocked");
    Check([message[@"allowed"] boolValue] == allowed, @"writer allowed revision/lock gate");
    Check([message[@"busy"] boolValue] == busy, @"writer busy");
    NSError *error = nil;
    NSData *wire = [NSJSONSerialization dataWithJSONObject:message options:NSJSONWritingSortedKeys error:&error];
    Check(wire != nil && error == nil, @"writer Foundation serialization");
    Check([wire writeToFile:[directory stringByAppendingPathComponent:name]
                   options:NSDataWritingAtomic error:&error], @"writer temporary file");
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        Check(argc == 2, @"writer output directory argument");
        NSString *directory = [NSString stringWithUTF8String:argv[1]];
        NSString *host = @"11111111-2222-4333-8444-555555555555";
        NSString *revision = @"SYNTHETIC-NAME-ROUNDTRIP-REV-1";
        NSError *error = nil;
        Check([[NSFileManager defaultManager] createDirectoryAtPath:directory
              withIntermediateDirectories:YES attributes:nil error:&error], @"writer temporary directory");
        /* Expected allowed values are literal, not a second copy of the builder. */
        const BOOL expectedAllowed[8] = { NO, NO, NO, NO, NO, NO, YES, YES };
        for (NSUInteger mask = 0; mask < 8; ++mask) {
            BOOL unlocked = (BOOL)((mask & 4) != 0);
            BOOL allowed = (BOOL)((mask & 2) != 0);
            BOOL busy = (BOOL)((mask & 1) != 0);
            NSDictionary *entry = MSNameWakeStateMessage(host, revision, unlocked, allowed, busy, 1000.);
            Write(directory, [NSString stringWithFormat:@"flags-%lu.json", (unsigned long)mask],
                  entry, unlocked, expectedAllowed[mask], busy);
        }
        NSArray<NSString *> *revisions = @[@"", @"R", [@"R" stringByPaddingToLength:128 withString:@"R" startingAtIndex:0],
            [@"R" stringByPaddingToLength:129 withString:@"R" startingAtIndex:0]];
        const BOOL revisionAllowed[4] = { NO, YES, YES, NO };
        for (NSUInteger i = 0; i < revisions.count; ++i) {
            Write(directory, [NSString stringWithFormat:@"revision-%lu.json", (unsigned long)i],
                  MSNameWakeStateMessage(host, revisions[i], YES, YES, NO, 1000.),
                  YES, revisionAllowed[i], NO);
            Write(directory, [NSString stringWithFormat:@"revision-locked-%lu.json", (unsigned long)i],
                  MSNameWakeStateMessage(host, revisions[i], NO, YES, NO, 1000.), NO, NO, NO);
        }
        Write(directory, @"clock-stale.json", MSNameWakeStateMessage(host, revision, YES, YES, NO, 995.999), YES, YES, NO);
        Write(directory, @"clock-boundary.json", MSNameWakeStateMessage(host, revision, YES, YES, NO, 996.), YES, YES, NO);
        Write(directory, @"clock-future.json", MSNameWakeStateMessage(host, revision, YES, YES, NO, 1000.001), YES, YES, NO);
        Write(directory, @"clock-negative.json", MSNameWakeStateMessage(host, revision, YES, YES, NO, -1.), YES, YES, NO);
        fprintf(stdout, "PASS native ObjC writer: %lu assertions; 20 production messages serialized to temporary files\n",
                (unsigned long)assertions);
    }
    return 0;
}
