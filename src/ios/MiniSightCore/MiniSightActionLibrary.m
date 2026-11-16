#import "MiniSightActionLibrary.h"
#import <UIKit/UIKit.h>
#import <ImageIO/ImageIO.h>
#import <fcntl.h>
#import <sys/stat.h>
#import <unistd.h>
#import <errno.h>
#import <math.h>
#import <stdlib.h>
#import <stdint.h>

NS_ASSUME_NONNULL_BEGIN

// Original implementation; no third-party animation/runtime code or artwork.
// ImageIO performs bounded thumbnail decoding. Only the MAIN delivery boundary
// creates UIImage; metadata, worker jobs and NSCache own Foundation/CG objects.
static const NSUInteger MSALManifestBytes = 1024 * 1024;
static const NSUInteger MSALSourceBytes = 24 * 1024 * 1024;
static const NSUInteger MSALInputBytes = 128 * 1024 * 1024;
static const NSUInteger MSALCacheBytes = 8 * 1024 * 1024;
static const NSUInteger MSALCacheFrames = 32;
static const NSUInteger MSALDecodeSide = 384;
static const NSUInteger MSALMaxPixels = 8000000;

static dispatch_queue_t MSALQueue(void) {
    static dispatch_queue_t queue; static dispatch_once_t once;
    dispatch_once(&once, ^{
        queue = dispatch_queue_create("com.openminis.minisight.action-library", DISPATCH_QUEUE_SERIAL);
        dispatch_set_target_queue(queue, dispatch_get_global_queue(QOS_CLASS_USER_INITIATED, 0));
    });
    return queue;
}
static NSError *MSALError(NSInteger code, NSString *reason) {
    // Constant bounded diagnostics: never include user paths, JSON or credentials.
    return [NSError errorWithDomain:@"MiniSightActionLibrary" code:code
                           userInfo:@{NSLocalizedDescriptionKey: reason}];
}
static BOOL MSALFail(NSError * _Nullable * _Nullable error, NSInteger code, NSString *reason) {
    if (error) *error = MSALError(code, reason);
    return NO;
}
static BOOL MSALNumber(id _Nullable value, double minimum, double maximum, BOOL integer) {
    if (![value isKindOfClass:NSNumber.class] ||
        CFGetTypeID((__bridge CFTypeRef)value) == CFBooleanGetTypeID()) return NO;
    double n = [value doubleValue];
    return isfinite(n) && n >= minimum && n <= maximum && (!integer || floor(n) == n);
}
static BOOL MSALKeys(id _Nullable value, NSArray<NSString *> *required, NSArray<NSString *> *optional) {
    if (![value isKindOfClass:NSDictionary.class]) return NO;
    for (NSString *key in required) if (!value[key]) return NO;
    for (id key in value) if (![required containsObject:key] && ![optional containsObject:key]) return NO;
    return YES;
}
static BOOL MSALSafeID(id _Nullable value) {
    if (![value isKindOfClass:NSString.class] || ![value length] || [value length] > 64) return NO;
    for (NSUInteger i = 0; i < [value length]; i++) {
        unichar c = [value characterAtIndex:i];
        BOOL alnum = (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
        if (!alnum && (i == 0 || (c != '_' && c != '-'))) return NO;
    }
    return YES;
}
static BOOL MSALRelativePath(id _Nullable value) {
    if (![value isKindOfClass:NSString.class] || ![value length] ||
        ![value canBeConvertedToEncoding:NSUTF8StringEncoding] ||
        [value lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 512 || [value hasPrefix:@"/"]) return NO;
    for (NSUInteger i = 0; i < [value length]; i++) {
        unichar c = [value characterAtIndex:i];
        if (c < 32 || c == 127 || c == '\\' || c == ':') return NO;
    }
    for (NSString *part in [value componentsSeparatedByString:@"/"]) {
        if (!part.length || [part isEqual:@"."] || [part isEqual:@".."] ||
            [part lengthOfBytesUsingEncoding:NSUTF8StringEncoding] > 255) return NO;
    }
    return YES;
}

// NSJSONSerialization otherwise silently overwrites duplicate object keys.
// Preflight also bounds parser nesting, without interpreting numbers/schema.
static BOOL MSALJSONEnvelope(NSData *data) {
    const uint8_t *b = data.bytes; NSUInteger n = data.length, depth = 0;
    uint8_t stack[8] = {0}; NSMutableSet *keys[8] = {nil};
    for (NSUInteger i = 0; i < n; i++) {
        uint8_t c = b[i];
        if (c == '"') {
            NSUInteger start = i++;
            while (i < n && b[i] != '"') {
                if (b[i] == '\\') { if (++i == n) return NO; }
                i++;
            }
            if (i == n) return NO;
            NSUInteger after = i + 1;
            while (after < n && (b[after] == ' ' || b[after] == '\t' || b[after] == '\r' || b[after] == '\n')) after++;
            if (depth && stack[depth - 1] == '{' && after < n && b[after] == ':') {
                NSData *literal = [data subdataWithRange:NSMakeRange(start, i - start + 1)];
                id key = [NSJSONSerialization JSONObjectWithData:literal options:NSJSONReadingFragmentsAllowed error:NULL];
                if (![key isKindOfClass:NSString.class] || [keys[depth - 1] containsObject:key]) return NO;
                [keys[depth - 1] addObject:key];
            }
        } else if (c == '{' || c == '[') {
            if (depth == 8) return NO;
            stack[depth] = c; keys[depth] = c == '{' ? [NSMutableSet set] : nil; depth++;
        } else if (c == '}' || c == ']') {
            if (!depth || stack[depth - 1] != (c == '}' ? '{' : '[')) return NO;
            keys[--depth] = nil;
        }
    }
    return depth == 0;
}

static BOOL MSALSameFile(struct stat a, struct stat b) {
    return a.st_dev == b.st_dev && a.st_ino == b.st_ino && a.st_size == b.st_size &&
        a.st_mtimespec.tv_sec == b.st_mtimespec.tv_sec && a.st_mtimespec.tv_nsec == b.st_mtimespec.tv_nsec &&
        a.st_ctimespec.tv_sec == b.st_ctimespec.tv_sec && a.st_ctimespec.tv_nsec == b.st_ctimespec.tv_nsec;
}

// Darwin's two standard root aliases are expanded lexically, not by following
// arbitrary links. Every other directory component (including pack ancestors)
// is opened descriptor-relatively with NOFOLLOW, closing the root-path loophole.
static int MSALOpenDirectory(NSString *path) {
    NSCAssert(!NSThread.isMainThread, @"Directory I/O must stay off main.");
    if ([path hasPrefix:@"/var/"] || [path isEqual:@"/var"]) path = [@"/private" stringByAppendingString:path];
    else if ([path hasPrefix:@"/tmp/"] || [path isEqual:@"/tmp"]) path = [@"/private" stringByAppendingString:path];
    int directory = open("/", O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW);
    if (directory < 0 || [path isEqual:@"/"]) return directory;
    for (NSString *part in [[path substringFromIndex:1] componentsSeparatedByString:@"/"]) {
        int next = openat(directory, part.fileSystemRepresentation, O_RDONLY | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
        close(directory);
        if (next < 0) return -1;
        directory = next;
    }
    return directory;
}
// Descriptor-relative traversal rejects ALL symlinks inside a pack, including
// benign ones. O_NONBLOCK avoids hanging on FIFOs before the regular-file test.
static NSData * _Nullable MSALRead(int root, NSString *relative, NSUInteger limit,
                       const struct stat * _Nullable expected, struct stat * _Nullable identity, NSError * _Nullable * _Nullable error) {
    NSCAssert(!NSThread.isMainThread, @"File I/O must stay off main.");
    if (!MSALRelativePath(relative)) { MSALFail(error, 3, @"Unsafe relative source path."); return nil; }
    NSArray<NSString *> *parts = [relative componentsSeparatedByString:@"/"];
    int directory = root, fd = -1;
    for (NSUInteger i = 0; i < parts.count; i++) {
        BOOL last = i + 1 == parts.count;
        int next = openat(directory, parts[i].fileSystemRepresentation,
            O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK | (last ? 0 : O_DIRECTORY));
        if (directory != root) close(directory);
        directory = root;
        if (next < 0) break;
        if (last) fd = next; else directory = next;
    }
    if (directory != root) close(directory);
    if (fd < 0) { MSALFail(error, 3, @"Source is missing or has an unsafe path."); return nil; }
    struct stat before = {0}, after = {0};
    if (fstat(fd, &before) || !S_ISREG(before.st_mode) || before.st_size <= 0 ||
        (uint64_t)before.st_size > limit || (expected && !MSALSameFile(before, *expected))) {
        close(fd); MSALFail(error, 4, @"Source type, size or identity is invalid."); return nil;
    }
    size_t length = (size_t)before.st_size, used = 0;
    uint8_t *bytes = malloc(length);
    if (!bytes) { close(fd); MSALFail(error, 4, @"Source buffer unavailable."); return nil; }
    while (used < length) {
        ssize_t count = read(fd, bytes + used, length - used);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) break;
        used += (size_t)count;
    }
    uint8_t extra; ssize_t tail;
    do { tail = read(fd, &extra, 1); } while (tail < 0 && errno == EINTR);
    BOOL stable = used == length && tail == 0 && fstat(fd, &after) == 0 && MSALSameFile(before, after);
    close(fd);
    if (!stable) { free(bytes); MSALFail(error, 4, @"Source changed while reading."); return nil; }
    if (identity) *identity = before;
    return [NSData dataWithBytesNoCopy:bytes length:length freeWhenDone:YES];
}

@interface MSALSource : NSObject {
@public
    NSString *file;
    NSString *type;
    struct stat identity;
    NSArray<NSValue *> *sizes;
    NSArray<NSNumber *> *orientations;
}
@end
@implementation MSALSource
@end

@interface MSALFrame : NSObject {
@public
    MSALSource *source;
    NSUInteger index;
    NSTimeInterval seconds;
    CGRect rect;
}
@end
@implementation MSALFrame
@end

@interface MiniSightActionClip ()
@property(nonatomic, copy, readonly) NSArray<MSALFrame *> *frames;
- (instancetype)initWithID:(NSString *)identifier role:(NSString *)role frames:(NSArray<MSALFrame *> *)frames;
@end
@implementation MiniSightActionClip
- (instancetype)initWithID:(NSString *)identifier role:(NSString *)role frames:(NSArray<MSALFrame *> *)frames {
    if ((self = [super init])) {
        _identifier = [identifier copy]; _role = [role copy]; _frames = [frames copy];
        NSMutableArray *durations = [NSMutableArray arrayWithCapacity:frames.count];
        for (MSALFrame *frame in frames) { [durations addObject:@(frame->seconds)]; _duration += frame->seconds; }
        _durations = [durations copy]; _frameCount = frames.count;
    }
    return self;
}
@end

@interface MSALBitmap : NSObject {
@public
    CGImageRef image;
    NSUInteger cost;
}
- (nullable instancetype)initTakingImage:(CGImageRef)value;
@end
@implementation MSALBitmap
- (nullable instancetype)initTakingImage:(CGImageRef)value {
    if ((self = [super init])) {
        image = value; cost = CGImageGetBytesPerRow(value) * CGImageGetHeight(value);
    } else if (value) {
        CGImageRelease(value); // Taking ownership also covers initializer failure.
    }
    return self;
}
- (void)dealloc { if (image) CGImageRelease(image); }
@end

// One process-wide pixel budget, including old/new libraries during a switch.
// State epochs and cache accounting share this short-held lock (never disk I/O).
static NSLock *MSALCacheLock;
static NSCache<NSString *, MSALBitmap *> *MSALCacheImages;
static NSMutableOrderedSet<NSString *> *MSALCacheLRU;
static NSMutableDictionary<NSString *, NSNumber *> *MSALCacheCosts;
static NSUInteger MSALCacheCost;

@interface MSALState : NSObject {
@public
    NSString *rootPath;
    struct stat rootIdentity;
    NSDictionary<NSString *, MiniSightActionClip *> *clips;
    NSDictionary<NSString *, NSArray<MiniSightActionClip *> *> *roles;
    NSUInteger canvasWidth, canvasHeight;
@private
    NSLock *_lock;
    uint64_t _epoch;
    NSCache<NSString *, MSALBitmap *> *_cache;
    NSMutableOrderedSet<NSString *> *_lru;
    NSMutableDictionary<NSString *, NSNumber *> *_costs;
    NSString *_cachePrefix;
}
- (uint64_t)advancePurging:(BOOL)purge;
- (BOOL)isCurrent:(uint64_t)epoch;
- (nullable MSALBitmap *)cached:(NSString *)key epoch:(uint64_t)epoch;
- (void)store:(MSALBitmap *)bitmap key:(NSString *)key epoch:(uint64_t)epoch;
@end
@implementation MSALState
- (instancetype)init {
    if ((self = [super init])) {
        static dispatch_once_t once;
        dispatch_once(&once, ^{
            MSALCacheLock = [NSLock new]; MSALCacheImages = [NSCache new];
            MSALCacheImages.totalCostLimit = MSALCacheBytes; MSALCacheImages.countLimit = MSALCacheFrames;
            MSALCacheLRU = [NSMutableOrderedSet orderedSet]; MSALCacheCosts = [NSMutableDictionary dictionary];
        });
        _lock = MSALCacheLock; _cache = MSALCacheImages; _lru = MSALCacheLRU; _costs = MSALCacheCosts;
        _cachePrefix = [NSUUID.UUID.UUIDString stringByAppendingString:@"/"];
    }
    return self;
}
- (uint64_t)advancePurging:(BOOL)purge {
    // No I/O or UIKit objects under this lock. Epoch changes and insertion are
    // mutually exclusive: purge/cancel cannot be followed by a late cache write.
    [_lock lock]; uint64_t value = ++_epoch;
    if (purge) for (NSString *key in [[_lru array] copy]) {
        if (![key hasPrefix:_cachePrefix]) continue;
        MSALCacheCost -= _costs[key].unsignedIntegerValue;
        [_cache removeObjectForKey:key]; [_lru removeObject:key]; [_costs removeObjectForKey:key];
    }
    [_lock unlock]; return value;
}
- (BOOL)isCurrent:(uint64_t)epoch {
    [_lock lock]; BOOL result = epoch == _epoch; [_lock unlock]; return result;
}
- (nullable MSALBitmap *)cached:(NSString *)key epoch:(uint64_t)epoch {
    key = [_cachePrefix stringByAppendingString:key];
    [_lock lock]; MSALBitmap *bitmap = nil;
    if (epoch == _epoch) {
        bitmap = [_cache objectForKey:key];
        if (bitmap) { [_lru removeObject:key]; [_lru addObject:key]; }
        else if (_costs[key]) {
            MSALCacheCost -= _costs[key].unsignedIntegerValue; [_costs removeObjectForKey:key]; [_lru removeObject:key];
        }
    }
    [_lock unlock]; return bitmap;
}
- (void)store:(MSALBitmap *)bitmap key:(NSString *)key epoch:(uint64_t)epoch {
    if (!bitmap || bitmap->cost > MSALCacheBytes) return;
    key = [_cachePrefix stringByAppendingString:key];
    [_lock lock];
    if (epoch == _epoch) {
        if (_costs[key]) {
            MSALCacheCost -= _costs[key].unsignedIntegerValue; [_cache removeObjectForKey:key];
            [_lru removeObject:key]; [_costs removeObjectForKey:key];
        }
        // NSCache's limits are advisory. Explicit accounting is a HARD bound;
        // automatic evictions may overcount, never undercount retained pixels.
        while (_lru.count && (MSALCacheCost + bitmap->cost > MSALCacheBytes || _lru.count >= MSALCacheFrames)) {
            NSString *oldest = _lru.firstObject;
            MSALCacheCost -= _costs[oldest].unsignedIntegerValue;
            [_cache removeObjectForKey:oldest]; [_costs removeObjectForKey:oldest]; [_lru removeObject:oldest];
        }
        [_cache setObject:bitmap forKey:key cost:bitmap->cost];
        _costs[key] = @(bitmap->cost); [_lru addObject:key]; MSALCacheCost += bitmap->cost;
    }
    [_lock unlock];
}
- (NSUInteger)cost {
    [_lock lock]; NSUInteger result = MSALCacheCost; [_lock unlock]; return result;
}
- (void)dealloc { [self advancePurging:YES]; }
@end

static NSString *MSALKey(MiniSightActionClip *clip, NSUInteger index) {
    return [NSString stringWithFormat:@"%@#%lu", clip.identifier, (unsigned long)index];
}
static NSDictionary *MSALSourceOptions(void) {
    return @{(id)kCGImageSourceShouldCache: @NO, (id)kCGImageSourceShouldAllowFloat: @NO};
}
static BOOL MSALAllowedType(CFStringRef _Nullable type) {
    return type && (CFEqual(type, CFSTR("public.png")) || CFEqual(type, CFSTR("public.jpeg")) ||
                    CFEqual(type, CFSTR("com.compuserve.gif")));
}
static BOOL MSALInspectSource(MSALSource *info, NSData *data, NSUInteger *totalFrames, NSError * _Nullable * _Nullable error) {
    CGImageSourceRef source = CGImageSourceCreateWithData((__bridge CFDataRef)data,
        (__bridge CFDictionaryRef)MSALSourceOptions());
    if (!source) return MSALFail(error, 4, @"Image source cannot be opened.");
    BOOL valid = NO;
    do {
        CFStringRef type = CGImageSourceGetType(source);
        NSUInteger count = CGImageSourceGetCount(source);
        if (!MSALAllowedType(type) || !count || count > 600 || *totalFrames + count > 6000 ||
            CGImageSourceGetStatus(source) != kCGImageStatusComplete ||
            (CFEqual(type, CFSTR("public.jpeg")) && count != 1)) break;
        NSMutableArray *sizes = [NSMutableArray arrayWithCapacity:count];
        NSMutableArray *orientations = [NSMutableArray arrayWithCapacity:count];
        for (NSUInteger i = 0; i < count; i++) {
            @autoreleasepool {
                NSDictionary *p = CFBridgingRelease(CGImageSourceCopyPropertiesAtIndex(source, i,
                    (__bridge CFDictionaryRef)MSALSourceOptions()));
                id w = p[(id)kCGImagePropertyPixelWidth], h = p[(id)kCGImagePropertyPixelHeight];
                id orientation = p[(id)kCGImagePropertyOrientation] ?: @1;
                if (!MSALNumber(w, 1, 4096, YES) || !MSALNumber(h, 1, 4096, YES) ||
                    [w doubleValue] * [h doubleValue] > MSALMaxPixels ||
                    !MSALNumber(orientation, 1, 8, YES) || CGImageSourceGetStatusAtIndex(source, i) != kCGImageStatusComplete) break;
                CGSize size = CGSizeMake([w doubleValue], [h doubleValue]);
                [sizes addObject:[NSValue valueWithBytes:&size objCType:@encode(CGSize)]];
                [orientations addObject:orientation];
            }
        }
        if (sizes.count != count) break;
        info->sizes = [sizes copy]; info->orientations = [orientations copy];
        info->type = [(__bridge NSString *)type copy]; *totalFrames += count; valid = YES;
    } while (NO);
    CFRelease(source);
    return valid || MSALFail(error, 4, @"Unsupported, incomplete or oversized image source.");
}

static CGSize MSALSize(MSALSource *source, NSUInteger index) {
    CGSize size = CGSizeZero;
    [source->sizes[index] getValue:&size size:sizeof(size)];
    return size;
}
static int MSALOpenRoot(MSALState *state, NSError * _Nullable * _Nullable error) {
    int fd = MSALOpenDirectory(state->rootPath);
    struct stat identity = {0};
    if (fd < 0 || fstat(fd, &identity) || !S_ISDIR(identity.st_mode) ||
        identity.st_dev != state->rootIdentity.st_dev || identity.st_ino != state->rootIdentity.st_ino) {
        if (fd >= 0) close(fd);
        MSALFail(error, 3, @"Action pack directory is unavailable or replaced."); return -1;
    }
    return fd;
}
static CGRect MSALOrientedRect(CGRect r, NSUInteger orientation) {
    CGFloat x = r.origin.x, y = r.origin.y, w = r.size.width, h = r.size.height;
    switch (orientation) {
        case 2: return CGRectMake(1-x-w, y, w, h);
        case 3: return CGRectMake(1-x-w, 1-y-h, w, h);
        case 4: return CGRectMake(x, 1-y-h, w, h);
        case 5: return CGRectMake(y, x, h, w);
        case 6: return CGRectMake(1-y-h, x, h, w);
        case 7: return CGRectMake(1-y-h, 1-x-w, h, w);
        case 8: return CGRectMake(y, 1-x-w, h, w);
        default: return r;
    }
}
static MSALBitmap * _Nullable MSALDecode(MSALState *state, MSALFrame *frame, uint64_t epoch, NSError * _Nullable * _Nullable error) {
    NSCAssert(!NSThread.isMainThread, @"Image decoding must stay off main.");
    if (![state isCurrent:epoch]) return nil;
    int root = MSALOpenRoot(state, error);
    if (root < 0) return nil;
    NSData *data = MSALRead(root, frame->source->file, MSALSourceBytes, &frame->source->identity, NULL, error);
    close(root);
    if (!data || ![state isCurrent:epoch]) return nil;
    CGImageSourceRef source = CGImageSourceCreateWithData((__bridge CFDataRef)data,
        (__bridge CFDictionaryRef)MSALSourceOptions());
    if (!source) { MSALFail(error, 4, @"Image source cannot be decoded."); return nil; }
    NSDictionary *options = @{
        (id)kCGImageSourceCreateThumbnailFromImageAlways: @YES,
        (id)kCGImageSourceCreateThumbnailWithTransform: @YES,
        (id)kCGImageSourceShouldCache: @NO,
        (id)kCGImageSourceShouldCacheImmediately: @YES,
        (id)kCGImageSourceThumbnailMaxPixelSize: @(MSALDecodeSide)
    };
    CGImageRef thumbnail = NULL;
    CFStringRef type = CGImageSourceGetType(source);
    if (type && CFEqual(type, (__bridge CFStringRef)frame->source->type) &&
        CGImageSourceGetCount(source) == frame->source->sizes.count && [state isCurrent:epoch]) {
        thumbnail = CGImageSourceCreateThumbnailAtIndex(source, frame->index, (__bridge CFDictionaryRef)options);
    }
    CFRelease(source);
    if (!thumbnail || !CGImageGetWidth(thumbnail) || !CGImageGetHeight(thumbnail) ||
        CGImageGetWidth(thumbnail) > MSALDecodeSide || CGImageGetHeight(thumbnail) > MSALDecodeSide) {
        if (thumbnail) CGImageRelease(thumbnail);
        MSALFail(error, 4, @"Bounded thumbnail decoding failed."); return nil;
    }
    NSUInteger orientation = frame->source->orientations[frame->index].unsignedIntegerValue;
    CGSize size = MSALSize(frame->source, frame->index);
    double aspect = size.width * frame->rect.size.width / (size.height * frame->rect.size.height);
    if (orientation >= 5) aspect = 1.0 / aspect;
    CGRect crop = MSALOrientedRect(frame->rect, orientation);
    CGFloat cw = state->canvasWidth, ch = state->canvasHeight;
    CGFloat fitW = MIN(cw, ch * aspect), fitH = fitW / aspect;
    CGRect fit = CGRectMake((cw - fitW) * .5, (ch - fitH) * .5, fitW, fitH);
    CGColorSpaceRef color = CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef context = color ? CGBitmapContextCreate(NULL, state->canvasWidth, state->canvasHeight,
        8, state->canvasWidth * 4, color, kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big) : NULL;
    if (color) CGColorSpaceRelease(color);
    if (!context) { CGImageRelease(thumbnail); MSALFail(error, 4, @"RGBA canvas unavailable."); return nil; }
    CGContextClearRect(context, CGRectMake(0, 0, cw, ch));
    CGContextSetInterpolationQuality(context, kCGInterpolationHigh);
    CGContextClipToRect(context, fit);
    // Continuous crop (NOT integer-rounded subimages) preserves a stable logical
    // canvas even for fractional normalized cells. Manifest rect is raw-source
    // top-left; ImageIO applies EXIF, then we map that rect to Quartz bottom-left.
    CGFloat fullW = fitW / crop.size.width, fullH = fitH / crop.size.height;
    CGRect draw = CGRectMake(fit.origin.x - crop.origin.x * fullW,
        fit.origin.y - (1 - CGRectGetMaxY(crop)) * fullH, fullW, fullH);
    CGContextDrawImage(context, draw, thumbnail);
    CGImageRef image = CGBitmapContextCreateImage(context);
    CGContextRelease(context); CGImageRelease(thumbnail);
    if (!image) { MSALFail(error, 4, @"RGBA image unavailable."); return nil; }
    return [[MSALBitmap alloc] initTakingImage:image];
}

typedef void (^MSALLoadCompletion)(MiniSightActionLibrary * _Nullable, NSError * _Nullable);
typedef void (^MSALFrameCompletion)(UIImage * _Nullable);
@interface MiniSightActionLibrary () {
    MSALState *_state;
    BOOL _busy;
    MSALFrame * _Nullable _pendingFrame;
    NSString * _Nullable _pendingKey;
    uint64_t _pendingEpoch;
    MSALFrameCompletion _Nullable _pendingCompletion;
    MSALFrameCompletion _Nullable _activeCompletion;
}
- (instancetype)initWithState:(MSALState *)state;
- (void)startNextFrame;
- (void)finishFrame:(MSALBitmap * _Nullable)bitmap epoch:(uint64_t)epoch;
@end

static MSALState * _Nullable MSALParse(NSDictionary *json, NSError * _Nullable * _Nullable error) {
    id packID = json[@"id"], records = json[@"clips"];
    NSUUID *uuid = [packID isKindOfClass:NSString.class] && [packID length] == 36 ?
        [[NSUUID alloc] initWithUUIDString:packID] : nil;
    if (!MSALKeys(json, @[@"schema", @"id", @"clips"], @[]) || !MSALNumber(json[@"schema"], 1, 1, YES) ||
        !uuid || [uuid.UUIDString caseInsensitiveCompare:packID] != NSOrderedSame ||
        ![records isKindOfClass:NSArray.class] || ![records count] || [records count] > 64) {
        MSALFail(error, 1, @"Invalid action manifest schema or identity."); return nil;
    }
    NSSet *allowed = [NSSet setWithArray:@[@"idle", @"idleAlt", @"tap", @"drag", @"shakeSoft", @"shakeHard",
        @"flight", @"land", @"walkLeft", @"walkRight", @"jump", @"sleep", @"wake", @"music"]];
    NSMutableDictionary *clips = [NSMutableDictionary dictionary], *roles = [NSMutableDictionary dictionary];
    NSMutableDictionary<NSString *, MSALSource *> *sources = [NSMutableDictionary dictionary];
    NSUInteger total = 0;
    for (id record in records) {
        if (!MSALKeys(record, @[@"id", @"role", @"frames"], @[])) {
            MSALFail(error, 1, @"Invalid clip fields."); return nil;
        }
        id identifier = record[@"id"], role = record[@"role"], entries = record[@"frames"];
        if (!MSALSafeID(identifier) || clips[identifier] || ![allowed containsObject:role] ||
            ![entries isKindOfClass:NSArray.class] || ![entries count] || [entries count] > 600 ||
            (total += [entries count]) > 6000) {
            MSALFail(error, 1, @"Invalid clip ID, role or frame count."); return nil;
        }
        NSMutableArray *frames = [NSMutableArray array]; double duration = 0;
        for (id entry in entries) {
            if (!MSALKeys(entry, @[@"file", @"index", @"duration"], @[@"rect"]) ||
                !MSALRelativePath(entry[@"file"]) || !MSALNumber(entry[@"index"], 0, 599, YES) ||
                !MSALNumber(entry[@"duration"], .02, 10, NO)) {
                MSALFail(error, 1, @"Invalid frame fields, path, index or duration."); return nil;
            }
            duration += [entry[@"duration"] doubleValue];
            if (duration > 120.0 + 1e-9) { MSALFail(error, 2, @"Clip duration exceeds 120 seconds."); return nil; }
            CGRect rect = CGRectMake(0, 0, 1, 1); id r = entry[@"rect"];
            if (r) {
                if (![r isKindOfClass:NSArray.class] || [r count] != 4 ||
                    !MSALNumber(r[0], 0, 1, NO) || !MSALNumber(r[1], 0, 1, NO) ||
                    !MSALNumber(r[2], 0, 1, NO) || !MSALNumber(r[3], 0, 1, NO)) {
                    MSALFail(error, 1, @"Invalid normalized frame rectangle."); return nil;
                }
                rect = CGRectMake([r[0] doubleValue], [r[1] doubleValue], [r[2] doubleValue], [r[3] doubleValue]);
                if (rect.size.width <= 0 || rect.size.height <= 0 || CGRectGetMaxX(rect) > 1 || CGRectGetMaxY(rect) > 1) {
                    MSALFail(error, 1, @"Frame rectangle leaves the source canvas."); return nil;
                }
            }
            NSString *file = entry[@"file"];
            MSALSource *source = sources[file];
            if (!source) { source = [MSALSource new]; source->file = [file copy]; sources[file] = source; }
            MSALFrame *frame = [MSALFrame new]; frame->source = source; frame->rect = rect;
            frame->index = [entry[@"index"] unsignedIntegerValue]; frame->seconds = [entry[@"duration"] doubleValue];
            [frames addObject:frame];
        }
        MiniSightActionClip *clip = [[MiniSightActionClip alloc] initWithID:identifier role:role frames:frames];
        clips[identifier] = clip;
        if (!roles[role]) roles[role] = [NSMutableArray array];
        [roles[role] addObject:clip];
    }
    if (![roles[@"idle"] count]) { MSALFail(error, 1, @"An explicit idle clip is required."); return nil; }
    MSALState *state = [MSALState new]; state->clips = [clips copy];
    NSMutableDictionary *immutableRoles = [NSMutableDictionary dictionary];
    for (NSString *role in roles) immutableRoles[role] = [roles[role] copy];
    state->roles = [immutableRoles copy];
    return state;
}

static double MSALFrameAspect(MSALFrame *frame) {
    if (frame->index >= frame->source->sizes.count) return 0;
    CGSize s = MSALSize(frame->source, frame->index);
    double w = s.width * frame->rect.size.width, h = s.height * frame->rect.size.height;
    if (w < 1 || h < 1) return 0;
    return frame->source->orientations[frame->index].unsignedIntegerValue >= 5 ? h / w : w / h;
}
static MSALState * _Nullable MSALLoadState(NSString * _Nullable path, NSError * _Nullable * _Nullable error) {
    if (![path isKindOfClass:NSString.class] || ![path hasPrefix:@"/"] ||
        ![path.lastPathComponent isEqual:@"actions.json"] ||
        !MSALRelativePath([path substringFromIndex:1])) {
        MSALFail(error, 3, @"Expected an absolute local actions.json path."); return nil;
    }
    NSString *rootPath = path.stringByDeletingLastPathComponent;
    int root = MSALOpenDirectory(rootPath);
    struct stat rootIdentity = {0};
    if (root < 0 || fstat(root, &rootIdentity) || !S_ISDIR(rootIdentity.st_mode)) {
        if (root >= 0) close(root);
        MSALFail(error, 3, @"Action pack root is not a regular directory."); return nil;
    }
    NSData *data = MSALRead(root, @"actions.json", MSALManifestBytes, NULL, NULL, error);
    if (!data) { close(root); return nil; }
    id json = MSALJSONEnvelope(data) ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
    if (![json isKindOfClass:NSDictionary.class]) {
        close(root); MSALFail(error, 1, @"Malformed or ambiguous action JSON."); return nil;
    }
    MSALState *state = MSALParse(json, error);
    if (!state) { close(root); return nil; }
    state->rootPath = [rootPath copy]; state->rootIdentity = rootIdentity;
    NSMutableSet<MSALSource *> *sources = [NSMutableSet set];
    for (MiniSightActionClip *clip in state->clips.allValues)
        for (MSALFrame *frame in clip.frames) [sources addObject:frame->source];
    NSUInteger totalBytes = data.length, sourceFrames = 0;
    for (MSALSource *source in sources) {
        // NSError ** is autoreleasing. A strong owner OUTSIDE this inner pool
        // must retain failures before its drain, then forward them afterwards.
        NSError *sourceError = nil;
        BOOL sourceOK = NO;
        @autoreleasepool {
            NSUInteger remaining = MSALInputBytes - totalBytes;
            NSData *input = MSALRead(root, source->file, MIN(MSALSourceBytes, remaining), NULL, &source->identity, &sourceError);
            sourceOK = input && MSALInspectSource(source, input, &sourceFrames, &sourceError);
            if (sourceOK) totalBytes += input.length;
        }
        if (!sourceOK) {
            close(root);
            if (error) *error = sourceError;
            return nil;
        }
    }
    close(root);
    MiniSightActionClip *idle = state->roles[@"idle"].firstObject;
    double aspect = MSALFrameAspect(idle.frames.firstObject);
    if (!aspect) { MSALFail(error, 1, @"Frame index or crop has no source pixels."); return nil; }
    for (MiniSightActionClip *clip in state->clips.allValues) {
        for (MSALFrame *frame in clip.frames) {
            double candidate = MSALFrameAspect(frame);
            if (!candidate || fabs(candidate / aspect - 1) > 1e-6) {
                MSALFail(error, 1, @"All cropped frames must share one logical canvas aspect."); return nil;
            }
        }
    }
    state->canvasWidth = MAX(1, (NSUInteger)llround(MSALDecodeSide * MIN(1.0, aspect)));
    state->canvasHeight = MAX(1, (NSUInteger)llround(MSALDecodeSide * MIN(1.0, 1.0 / aspect)));
    MSALBitmap *first = MSALDecode(state, idle.frames.firstObject, 0, error);
    if (!first) return nil;
    [state store:first key:MSALKey(idle, 0) epoch:0];
    return state;
}

@implementation MiniSightActionLibrary
- (instancetype)initWithState:(MSALState *)state {
    if ((self = [super init])) _state = state;
    return self;
}
- (NSDictionary<NSString *, NSArray<MiniSightActionClip *> *> *)roles { return _state->roles; }
+ (void)loadManifestAtPath:(NSString *)path completion:(MSALLoadCompletion)completion {
    NSAssert(NSThread.isMainThread, @"Action-library calls belong on main.");
    if (!completion) return;
    // Callback holders live ONLY on main. Worker captures metadata, not a block
    // that might retain a view. Library itself is also constructed only on main.
    static NSMutableDictionary<NSNumber *, id> *callbacks;
    static uint64_t nextTicket = 0;
    if (!callbacks) callbacks = [NSMutableDictionary dictionary];
    if (callbacks.count >= 2) {
        dispatch_async(dispatch_get_main_queue(), ^{ completion(nil, MSALError(5, @"Action manifest loader is busy.")); });
        return;
    }
    NSNumber *ticket = @(++nextTicket); callbacks[ticket] = [completion copy];
    NSString *input = [path isKindOfClass:NSString.class] ? [path copy] : nil;
    dispatch_async(MSALQueue(), ^{
        @autoreleasepool {
            NSError *error = nil; MSALState *state = MSALLoadState(input, &error);
            dispatch_async(dispatch_get_main_queue(), ^{
                MSALLoadCompletion callback = callbacks[ticket];
                [callbacks removeObjectForKey:ticket];
                MiniSightActionLibrary *library = state ? [[MiniSightActionLibrary alloc] initWithState:state] : nil;
                if (callback) callback(library, error ?: (library ? nil : MSALError(4, @"Action library unavailable.")));
            });
        }
    });
}
- (void)requestFrameForClip:(MiniSightActionClip *)clip index:(NSUInteger)index completion:(MSALFrameCompletion)completion {
    NSAssert(NSThread.isMainThread, @"Action-library calls belong on main.");
    uint64_t epoch = [_state advancePurging:NO];
    _activeCompletion = nil; _pendingCompletion = [completion copy]; _pendingEpoch = epoch;
    BOOL valid = [clip isKindOfClass:MiniSightActionClip.class] && _state->clips[clip.identifier] == clip && index < clip.frameCount;
    _pendingFrame = valid ? clip.frames[index] : nil;
    _pendingKey = valid ? MSALKey(clip, index) : nil;
    [self startNextFrame];
}
- (void)startNextFrame {
    if (_busy || !_pendingCompletion) return;
    _busy = YES; uint64_t epoch = _pendingEpoch;
    MSALFrame *frame = _pendingFrame; NSString *key = _pendingKey;
    _activeCompletion = _pendingCompletion; _pendingCompletion = nil; _pendingFrame = nil; _pendingKey = nil;
    MSALState *state = _state; __weak MiniSightActionLibrary *weakSelf = self;
    MSALBitmap *cached = key ? [state cached:key epoch:epoch] : nil;
    if (cached || !frame) {
        dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf finishFrame:cached epoch:epoch]; });
        return;
    }
    dispatch_async(MSALQueue(), ^{
        @autoreleasepool {
            MSALBitmap *bitmap = MSALDecode(state, frame, epoch, NULL);
            if (bitmap) [state store:bitmap key:key epoch:epoch];
            dispatch_async(dispatch_get_main_queue(), ^{ [weakSelf finishFrame:bitmap epoch:epoch]; });
        }
    });
}
- (void)finishFrame:(MSALBitmap * _Nullable)bitmap epoch:(uint64_t)epoch {
    NSAssert(NSThread.isMainThread, @"Frame delivery belongs on main.");
    MSALFrameCompletion completion = [_state isCurrent:epoch] ? _activeCompletion : nil;
    _activeCompletion = nil; _busy = NO;
    if (completion) {
        UIImage *image = bitmap ? [UIImage imageWithCGImage:bitmap->image scale:1 orientation:UIImageOrientationUp] : nil;
        completion(image);
    }
    [self startNextFrame];
}
- (void)cancelPendingFrameRequests {
    NSAssert(NSThread.isMainThread, @"Action-library calls belong on main.");
    [_state advancePurging:NO];
    _activeCompletion = nil; _pendingCompletion = nil; _pendingFrame = nil; _pendingKey = nil;
}
- (void)purgeFrames {
    NSAssert(NSThread.isMainThread, @"Action-library calls belong on main.");
    [_state advancePurging:YES];
    _activeCompletion = nil; _pendingCompletion = nil; _pendingFrame = nil; _pendingKey = nil;
}
- (void)dealloc {
    // Workers hold state + a weak library, never this main-owned callback holder.
    [_state advancePurging:YES];
}
@end

NS_ASSUME_NONNULL_END
