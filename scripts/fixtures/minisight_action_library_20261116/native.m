// Compiles the ACTUAL production parser/reader/decoder/cache/scheduler on macOS.
// Only UIImage's final delivery wrapper is substituted; iOS UIKit is separately
// typechecked with the real iPhoneOS SDK. This is not an iOS visual/runtime test.
#import "MiniSightActionLibrary.m"
#import <stdio.h>
#import <stdlib.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "FAIL line %d: %s\n", __LINE__, #x); exit(1); } } while (0)
@implementation UIImage {
    CGImageRef _backing;
}
+ (instancetype)imageWithCGImage:(CGImageRef)image scale:(CGFloat)scale orientation:(UIImageOrientation)orientation {
    CHECK(NSThread.isMainThread && image && scale == 1 && orientation == UIImageOrientationUp);
    UIImage *result = [self new]; result->_backing = CGImageRetain(image); return result;
}
- (CGImageRef)CGImage { CHECK(NSThread.isMainThread); return _backing; }
- (void)dealloc { CHECK(NSThread.isMainThread); CGImageRelease(_backing); }
@end

static void Wait(BOOL (^ready)(void)) {
    CFAbsoluteTime deadline = CFAbsoluteTimeGetCurrent() + 20;
    while (!ready() && CFAbsoluteTimeGetCurrent() < deadline)
        CFRunLoopRunInMode(kCFRunLoopDefaultMode, .005, true);
    CHECK(ready());
}
static void DrainWorker(void) {
    __block BOOL done = NO;
    dispatch_async(MSALQueue(), ^{ dispatch_async(dispatch_get_main_queue(), ^{ done = YES; }); });
    Wait(^BOOL { return done; });
}
static MiniSightActionLibrary *Load(NSString *path, NSError **error) {
    __block MiniSightActionLibrary *result; __block NSError *failure;
    __block BOOL done = NO, returned = NO;
    [MiniSightActionLibrary loadManifestAtPath:path completion:^(MiniSightActionLibrary *library, NSError *e) {
        CHECK(returned && NSThread.isMainThread); result = library; failure = e; done = YES;
    }];
    returned = YES; Wait(^BOOL { return done; });
    if (error) *error = failure; return result;
}
static UIImage *Frame(MiniSightActionLibrary *library, MiniSightActionClip *clip, NSUInteger index) {
    __block UIImage *result; __block BOOL done = NO, returned = NO;
    [library requestFrameForClip:clip index:index completion:^(UIImage *image) {
        CHECK(returned && NSThread.isMainThread); result = image; done = YES;
    }];
    returned = YES; Wait(^BOOL { return done; }); return result;
}
static void CheckImage(UIImage *image, NSArray *canvas, NSArray *rgb, BOOL alpha) {
    CHECK(image); CGImageRef cg = image.CGImage;
    size_t w = CGImageGetWidth(cg), h = CGImageGetHeight(cg), row = CGImageGetBytesPerRow(cg);
    CHECK(w > 0 && h > 0 && w <= 384 && h <= 384 && CGImageGetBitsPerPixel(cg) == 32);
    CHECK(CGImageGetAlphaInfo(cg) == kCGImageAlphaPremultipliedLast);
    if (canvas) CHECK(w == [canvas[0] unsignedIntegerValue] && h == [canvas[1] unsignedIntegerValue]);
    CFDataRef data = CGDataProviderCopyData(CGImageGetDataProvider(cg)); CHECK(data);
    const UInt8 *bytes = CFDataGetBytePtr(data);
    if (rgb) {
        const UInt8 *center = bytes + (h / 2) * row + (w / 2) * 4;
        for (NSUInteger channel = 0; channel < 3; channel++) CHECK(abs(center[channel] - [rgb[channel] intValue]) < 36);
        CHECK(center[3] == 255);
    }
    if (alpha) {
        BOOL clear = NO, opaque = NO;
        for (size_t y = 0; y < h; y++) for (size_t x = 0; x < w; x++) {
            UInt8 a = bytes[y * row + x * 4 + 3]; clear |= a == 0; opaque |= a == 255;
        }
        CHECK(clear && opaque);
    }
    CFRelease(data);
}
static void Prepare(NSDictionary *entry) {
    NSString *kind = entry[@"prepare"]; if (!kind) return;
    NSString *directory = [entry[@"path"] stringByDeletingLastPathComponent];
    NSURL *sourceURL = [NSURL fileURLWithPath:[directory stringByAppendingPathComponent:@"pixels.png"]];
    CGImageSourceRef source = CGImageSourceCreateWithURL((__bridge CFURLRef)sourceURL, NULL); CHECK(source);
    CGImageRef image = CGImageSourceCreateImageAtIndex(source, 0, NULL); CHECK(image); CFRelease(source);
    BOOL tiff = [kind isEqual:@"tiff"];
    NSURL *targetURL = [NSURL fileURLWithPath:[directory stringByAppendingPathComponent:tiff ? @"native.tiff" : @"native.jpg"]];
    CGImageDestinationRef destination = CGImageDestinationCreateWithURL((__bridge CFURLRef)targetURL,
        tiff ? CFSTR("public.tiff") : CFSTR("public.jpeg"), 1, NULL); CHECK(destination);
    NSDictionary *properties = @{(id)kCGImagePropertyOrientation: [kind isEqual:@"exif"] ? @6 : @1,
                                 (id)kCGImageDestinationLossyCompressionQuality: @1};
    CGImageDestinationAddImage(destination, image, (__bridge CFDictionaryRef)properties);
    CHECK(CGImageDestinationFinalize(destination)); CFRelease(destination); CGImageRelease(image);
}
static void Fixture(NSDictionary *entry) {
    @autoreleasepool {
        Prepare(entry);
        NSError *error = nil; MiniSightActionLibrary *library = Load(entry[@"path"], &error);
        BOOL expected = [entry[@"valid"] boolValue];
        if ((library != nil) != expected) fprintf(stderr, "case: %s\n", [entry[@"name"] UTF8String]);
        CHECK((library != nil) == expected);
        if (!expected) { CHECK(error && error.localizedDescription.length < 128); return; }
        CHECK(!error && library.roles[@"idle"].count);
        for (NSArray<MiniSightActionClip *> *clips in library.roles.allValues) for (MiniSightActionClip *clip in clips) {
            CHECK(clip.frameCount > 0 && clip.durations.count == clip.frameCount && clip.duration <= 120.000001);
        }
        MiniSightActionClip *idle = library.roles[@"idle"].firstObject;
        NSArray *colors = entry[@"colors"];
        NSUInteger count = colors ? colors.count : MIN(idle.frameCount, 2);
        for (NSUInteger i = 0; i < count; i++)
            CheckImage(Frame(library, idle, i), entry[@"canvas"], colors ? colors[i] : nil, [entry[@"alpha"] boolValue]);
        CHECK(!Frame(library, idle, NSUIntegerMax));
        [library purgeFrames];
    }
}

static MSALBitmap *TestBitmap(void) {
    CGColorSpaceRef color = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(NULL, 384, 384, 8, 384 * 4, color,
        kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(color); CHECK(context);
    CGImageRef cg = CGBitmapContextCreateImage(context); CGContextRelease(context); CHECK(cg);
    return [[MSALBitmap alloc] initTakingImage:cg];
}
static void CacheTests(void) {
    MSALState *state = [MSALState new]; MSALBitmap *bitmap = TestBitmap();
    uint64_t epoch = [state advancePurging:NO];
    for (NSUInteger i = 0; i < 100; i++) {
        NSString *key = [NSString stringWithFormat:@"%lu", (unsigned long)i];
        [state store:bitmap key:key epoch:epoch];
        CHECK([[state valueForKey:@"cost"] unsignedIntegerValue] <= 8 * 1024 * 1024);
        CHECK([[state valueForKey:@"lru"] count] <= 32);
    }
    CHECK(![state cached:@"0" epoch:epoch] && [state cached:@"99" epoch:epoch]);
    uint64_t fresh = [state advancePurging:YES];
    [state store:bitmap key:@"late" epoch:epoch];
    CHECK(![state cached:@"late" epoch:fresh] && [[state valueForKey:@"cost"] unsignedIntegerValue] == 0);
    [state store:bitmap key:@"new" epoch:fresh]; CHECK([state cached:@"new" epoch:fresh]);
    uint64_t cancelled = [state advancePurging:NO];
    [state store:bitmap key:@"cancelled" epoch:fresh]; CHECK(![state cached:@"cancelled" epoch:cancelled]);
    // Two instances must share one hard budget, without purging each other.
    MSALState *other = [MSALState new]; uint64_t otherEpoch = [other advancePurging:NO];
    for (NSUInteger i = 0; i < 100; i++) {
        MSALState *target = i % 2 ? state : other;
        [target store:bitmap key:[NSString stringWithFormat:@"shared-%lu", (unsigned long)i]
                   epoch:i % 2 ? cancelled : otherEpoch];
        CHECK([[state valueForKey:@"cost"] unsignedIntegerValue] <= 8 * 1024 * 1024);
        CHECK([[state valueForKey:@"lru"] count] <= 32);
        CHECK([[state valueForKey:@"cost"] isEqual:[other valueForKey:@"cost"]]);
    }
    [other store:bitmap key:@"survivor" epoch:otherEpoch];
    [state advancePurging:YES]; CHECK([other cached:@"survivor" epoch:otherEpoch]);
    [other advancePurging:YES]; CHECK([[state valueForKey:@"cost"] unsignedIntegerValue] == 0);
    // With no delivery/worker owner, purging releases the bitmap/CGImage owner.
    __weak MSALBitmap *weakBitmap; uint64_t releaseEpoch = [state advancePurging:NO];
    @autoreleasepool {
        MSALBitmap *owned = TestBitmap(); weakBitmap = owned;
        [state store:owned key:@"release" epoch:releaseEpoch];
    }
    // A weak read can autorelease a temporary strong owner. Drain that probe
    // BEFORE testing production's immediate release; keep the same assertions.
    @autoreleasepool { CHECK(weakBitmap); }
    [state advancePurging:YES]; CHECK(!weakBitmap);
}

// Exact weak** rejects a mistakenly strong probe (the second declarator of
// '__weak NSObject *a, *b' is STRONG). Give the caller's object/block ownership
// precise lifetimes in a non-inlined call; after return only production's
// callback slots retain the owner. No worker is drained before release checks.
__attribute__((noinline))
static void RequestOwnedFrame(MiniSightActionLibrary *library, MiniSightActionClip *clip,
                              NSUInteger index, NSObject * __weak *probe,
                              MSALFrameCompletion completion) {
    @autoreleasepool {
        __attribute__((objc_precise_lifetime)) NSObject *owner = [NSObject new];
        *probe = owner;
        __attribute__((objc_precise_lifetime)) MSALFrameCompletion callback = ^(UIImage *image) {
            CHECK(owner); completion(image);
        };
        [library requestFrameForClip:clip index:index completion:callback];
    }
}

static void SchedulerTests(NSString *path) {
    NSError *error = nil; MiniSightActionLibrary *library = Load(path, &error); CHECK(library && !error);
    MiniSightActionClip *idle = library.roles[@"idle"].firstObject;
    MSALState *state = [library valueForKey:@"state"];
    MiniSightActionLibrary *other = Load(path, &error); CHECK(other);
    CHECK(!Frame(library, other.roles[@"idle"].firstObject, 0));
    // Shared accounting includes other libraries; isolate scheduler assertions.
    [other purgeFrames]; other = nil;
    [library purgeFrames];
    dispatch_semaphore_t gate = dispatch_semaphore_create(0);
    dispatch_async(MSALQueue(), ^{ dispatch_semaphore_wait(gate, DISPATCH_TIME_FOREVER); });
    __block NSUInteger delivered = 0;
    for (NSUInteger i = 0; i < 100; i++) {
        [library requestFrameForClip:idle index:i % 2 completion:^(UIImage *image) {
            CHECK(i == 99); CheckImage(image, @[@384,@192], @[@0,@0,@255], NO); delivered++;
        }];
    }
    dispatch_semaphore_signal(gate); Wait(^BOOL { return delivered != 0; }); DrainWorker(); CHECK(delivered == 1);
    CHECK([[state valueForKey:@"lru"] count] <= 1);

    for (NSUInteger purge = 0; purge < 2; purge++) {
        [library purgeFrames]; gate = dispatch_semaphore_create(0);
        dispatch_semaphore_t capturedGate = gate;
        dispatch_async(MSALQueue(), ^{ dispatch_semaphore_wait(capturedGate, DISPATCH_TIME_FOREVER); });
        __weak NSObject *weakActive;
        __weak NSObject *weakPending;
        RequestOwnedFrame(library, idle, 1, &weakActive, ^(UIImage *image) {
            (void)image; delivered++;
        });
        @autoreleasepool { CHECK(weakActive); }
        RequestOwnedFrame(library, idle, 1, &weakPending, ^(UIImage *image) {
            (void)image; delivered++;
        });
        @autoreleasepool { CHECK(!weakActive && weakPending); } // Drain weak-load temporary ownership.
        if (purge) [library purgeFrames]; else [library cancelPendingFrameRequests];
        CHECK(!weakPending); // Cancellation drops the retained callback immediately.
        dispatch_semaphore_signal(gate); DrainWorker();
        CHECK(delivered == 1 && [[state valueForKey:@"cost"] unsignedIntegerValue] == 0);
    }
    // Cancel an active worker, then admit a new request before its stale finish.
    // The stale finish must neither deliver the old callback nor erase the new one.
    [library purgeFrames]; gate = dispatch_semaphore_create(0);
    dispatch_semaphore_t restartGate = gate;
    dispatch_async(MSALQueue(), ^{ dispatch_semaphore_wait(restartGate, DISPATCH_TIME_FOREVER); });
    __weak NSObject *weakRestart;
    RequestOwnedFrame(library, idle, 1, &weakRestart, ^(UIImage *image) {
        (void)image; CHECK(NO);
    });
    @autoreleasepool { CHECK(weakRestart); }
    [library cancelPendingFrameRequests]; CHECK(!weakRestart);
    __block BOOL restarted = NO;
    [library requestFrameForClip:idle index:1 completion:^(UIImage *image) {
        CheckImage(image, @[@384,@192], @[@0,@0,@255], NO); restarted = YES;
    }];
    CHECK(!restarted); dispatch_semaphore_signal(gate);
    Wait(^BOOL { return restarted; }); DrainWorker();
    CHECK(delivered == 1 && [[state valueForKey:@"lru"] count] <= 1);
    fprintf(stderr, "NATIVE PASS ownership: isolated caller, cancel/purge pending, active cancel + new job\n");
    // Primed first frame is independent of subsequent filesystem availability.
    library = Load(path, &error); CHECK(library); idle = library.roles[@"idle"].firstObject;
    NSString *file = [path.stringByDeletingLastPathComponent stringByAppendingPathComponent:@"pixels.png"];
    NSString *parked = [file stringByAppendingString:@".parked"];
    CHECK(rename(file.fileSystemRepresentation, parked.fileSystemRepresentation) == 0);
    CHECK(Frame(library, idle, 0)); CHECK(!Frame(library, idle, 1));
    [library purgeFrames]; CHECK(!Frame(library, idle, 0));
    CHECK(rename(parked.fileSystemRepresentation, file.fileSystemRepresentation) == 0);
    // Same path, different inode: old metadata must never decode replacement data.
    library = Load(path, &error); CHECK(library); idle = library.roles[@"idle"].firstObject;
    NSData *saved = [NSData dataWithContentsOfFile:file]; CHECK(saved);
    CHECK([saved writeToFile:file options:NSDataWritingAtomic error:NULL]);
    CHECK(!Frame(library, idle, 1));
    [library purgeFrames]; CHECK(!Frame(library, idle, 0));
}
static void LoadAdmissionTests(NSString *path) {
    dispatch_semaphore_t gate = dispatch_semaphore_create(0);
    dispatch_async(MSALQueue(), ^{ dispatch_semaphore_wait(gate, DISPATCH_TIME_FOREVER); });
    __block NSUInteger delivered = 0; __block BOOL busy = NO;
    for (NSUInteger i = 0; i < 3; i++) {
        [MiniSightActionLibrary loadManifestAtPath:path completion:^(MiniSightActionLibrary *library, NSError *error) {
            CHECK(NSThread.isMainThread);
            if (i == 2) { CHECK(!library && error.code == 5); busy = YES; }
            else CHECK(library && !error);
            delivered++;
        }];
    }
    Wait(^BOOL { return busy; }); dispatch_semaphore_signal(gate);
    Wait(^BOOL { return delivered == 3; });
}
int main(int argc, const char *argv[]) {
    @autoreleasepool {
        CHECK(argc == 2 && NSThread.isMainThread);
        NSData *data = [NSData dataWithContentsOfFile:[NSString stringWithUTF8String:argv[1]]]; CHECK(data);
        NSDictionary *plan = [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL]; CHECK(plan);
        for (NSDictionary *entry in plan[@"cases"]) Fixture(entry);
        CacheTests(); SchedulerTests(plan[@"runtime"]); LoadAdmissionTests(plan[@"runtime"]);
        printf("PASS native: %lu real parser/source fixtures + cache/epoch/coalescing/admission/lifetime assertions\n",
               (unsigned long)[plan[@"cases"] count]);
    }
    return 0;
}
