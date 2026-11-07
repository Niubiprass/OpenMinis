#import "MiniSightResources.h"
#import "MiniSightBridgeIO.h"
#import <ImageIO/ImageIO.h>
#import <math.h>

@implementation MiniSightResources
static NSString *MSResourceContainer;
static NSString *MSAtlasIdentity;
static UIImage *MSAtlas;
+ (NSDictionary<NSString *, NSString *> *)runtimeFields {
    static NSDictionary *fields; static dispatch_once_t once;
    dispatch_once(&once, ^{ fields = @{
        @"minisight.style": @"style", @"minisight.renderer": @"renderer",
        @"minisight.mode": @"mode", @"minisight.petSize": @"petSize",
        @"minisight.gravity": @"gravity", @"minisight.gravity.strength": @"gravityStrength",
        @"minisight.gravity.shake": @"gravityShake", @"minisight.interaction": @"interaction",
        @"minisight.gesture.single": @"singleTap", @"minisight.gesture.double": @"doubleTap",
        @"minisight.gesture.long": @"longPress", @"minisight.activity": @"activity",
        @"minisight.activity.interval": @"activityInterval", @"minisight.frameLimit": @"frameLimit",
        @"minisight.dragResponse": @"dragResponse", @"minisight.petSound": @"sound",
        @"minisight.bottomGap": @"bottomGap", @"minisight.pet.tint": @"tint",
        @"minisight.pet.costume": @"costume", @"minisight.ai.supplier": @"supplier",
        @"minisight.asset.source": @"downloadSource", @"minisight.darkMode": @"darkMode",
        @"minisight.ai.persona": @"persona", @"minisight.ai.nickname": @"nickname",
        @"minisight.ai.adjust": @"aiAdjust", @"minisight.ai.permissions": @"aiPermissions",
        @"minisight.ai.adjustments": @"adjustments", @"minisight.proactive": @"proactive",
        @"minisight.proactive.interval": @"proactiveInterval", @"minisight.dialogue.scale": @"bubbleScale",
        @"minisight.dialogue.textScale": @"textScale", @"minisight.dialogue.dwell": @"dwell",
        @"minisight.dialogue.return": @"returnKey", @"minisight.voice.reply": @"voiceReply",
        @"minisight.voice.input": @"voiceInput", @"minisight.voice.snore": @"snore",
        @"minisight.quick.enabled": @"quick", @"minisight.quick.position": @"quickPosition",
        @"minisight.quick.lines": @"quickLines", @"minisight.quick.order": @"quickOrder",
        @"minisight.record": @"record", @"minisight.longPress": @"longPressRecord",
        @"minisight.diagnostics": @"diagnostics", @"minisight.shown": @"shown",
        @"minisight.settings.revision": @"revision"
    }; });
    return fields;
}
+ (NSDictionary<NSString *, id> *)mergedPreferencesWithContainer:(NSString *)container
                                                  preferences:(NSDictionary<NSString *,id> *)preferences {
    NSMutableDictionary *merged = [NSMutableDictionary dictionary];
    if ([preferences isKindOfClass:NSDictionary.class]) {
        for (NSString *key in preferences) if ([key isKindOfClass:NSString.class] &&
            [key hasPrefix:@"minisight."]) merged[key] = preferences[key];
    }
    NSDictionary *snapshot = container.length ? MSBridgeRead(container, @"runtime.json", 1024 * 1024) : nil;
    NSDictionary *fields = self.runtimeFields;
    // v1 snapshots used runtime aliases; accept them only for known fields.
    for (NSString *key in fields) {
        id value = snapshot[fields[key]];
        if (value && ![value isKindOfClass:NSNull.class]) merged[key] = value;
    }
    NSDictionary *canonical = [snapshot isKindOfClass:NSDictionary.class] ? snapshot[@"preferences"] : nil;
    if ([canonical isKindOfClass:NSDictionary.class]) {
        for (NSString *key in canonical) if ([self.runtimeFields objectForKey:key] &&
            ![canonical[key] isKindOfClass:NSNull.class]) merged[key] = canonical[key];
    }
    return [merged copy];
}
static dispatch_queue_t MSResourceQueue(void) {
    static dispatch_queue_t q; static dispatch_once_t once;
    dispatch_once(&once, ^{ q = dispatch_queue_create("com.openminis.minisight.resources", DISPATCH_QUEUE_SERIAL); });
    return q;
}
static NSString *MSFindContainer(void) {
    NSFileManager *fm = NSFileManager.defaultManager;
    if (MSResourceContainer) {
        NSString *meta = [MSResourceContainer stringByAppendingPathComponent:@".com.apple.mobile_container_manager.metadata.plist"];
        NSDictionary *value = [NSDictionary dictionaryWithContentsOfFile:meta];
        if ([value[@"MCMMetadataIdentifier"] isEqual:@"com.openminis.app"]) return MSResourceContainer;
    }
    MSResourceContainer = nil;
    NSString *base = @"/var/mobile/Containers/Data/Application";
    for (NSString *name in [fm contentsOfDirectoryAtPath:base error:nil]) {
        NSString *dir = [base stringByAppendingPathComponent:name];
        NSDictionary *meta = [NSDictionary dictionaryWithContentsOfFile:
            [dir stringByAppendingPathComponent:@".com.apple.mobile_container_manager.metadata.plist"]];
        if ([meta[@"MCMMetadataIdentifier"] isEqual:@"com.openminis.app"]) { MSResourceContainer = dir; break; }
    }
    return MSResourceContainer;
}
/// Some exported sheets bake a black rectangle behind every frame. Flood
/// near-black pixels connected to the atlas border, then clear their alpha.
/// This keeps interior black eyes/outlines, and runs only on the resource queue.
static void MSKeyOutBlackBackground(uint8_t *pixels, size_t w, size_t h) {
    if (!pixels || w < 2 || h < 2 || w * h > 2000000) return;
    uint8_t *seen = calloc(w * h, 1);
    size_t *queue = malloc(sizeof(size_t) * w * h * 4);
    if (!seen || !queue) { free(seen); free(queue); return; }
    size_t head = 0, tail = 0;
    #define MSDARK(px,py) (pixels[((py) * w + (px)) * 4 + 3] > 0 && \
        pixels[((py) * w + (px)) * 4] < 32 && pixels[((py) * w + (px)) * 4 + 1] < 32 && \
        pixels[((py) * w + (px)) * 4 + 2] < 32)
    for (size_t x = 0; x < w; x++) {
        if (MSDARK(x, 0)) queue[tail++] = x;
        if (MSDARK(x, h - 1)) queue[tail++] = (h - 1) * w + x;
    }
    for (size_t y = 0; y < h; y++) {
        if (MSDARK(0, y)) queue[tail++] = y * w;
        if (MSDARK(w - 1, y)) queue[tail++] = y * w + w - 1;
    }
    while (head < tail) {
        size_t p = queue[head++];
        if (seen[p]) continue;
        seen[p] = 1;
        size_t x = p % w, y = p / w;
        if (!MSDARK(x, y)) continue;
        pixels[p * 4 + 3] = 0;
        if (x) queue[tail++] = p - 1;
        if (x + 1 < w) queue[tail++] = p + 1;
        if (y) queue[tail++] = p - w;
        if (y + 1 < h) queue[tail++] = p + w;
    }
    #undef MSDARK
    free(seen); free(queue);
}

static UIImage *MSLoadAtlas(NSString *path) {
    NSDictionary *attrs = [NSFileManager.defaultManager attributesOfItemAtPath:path error:nil];
    if (!attrs || ![attrs[NSFileType] isEqual:NSFileTypeRegular] ||
        [attrs[NSFileSize] unsignedLongLongValue] > 16 * 1024 * 1024) return nil;
    NSString *identity = [NSString stringWithFormat:@"%@|%@|%@", path, attrs[NSFileSize], attrs[NSFileModificationDate]];
    if ([identity isEqual:MSAtlasIdentity]) return MSAtlas;
    CGImageSourceRef source = CGImageSourceCreateWithURL((__bridge CFURLRef)[NSURL fileURLWithPath:path], NULL);
    if (!source) return nil;
    NSDictionary *props = CFBridgingRelease(CGImageSourceCopyPropertiesAtIndex(source, 0, NULL));
    double w = [props[(id)kCGImagePropertyPixelWidth] doubleValue];
    double h = [props[(id)kCGImagePropertyPixelHeight] doubleValue];
    if (w < 8. || h < 9. || w > 16384. || h > 16384. || fabs(w/h-768./936.) > .025) {
        CFRelease(source); return nil;
    }
    // The atlas never needs a Retina-sized 2304x2808 backing. Decode at most
    // 768x936 pixels once on this queue (roughly 2.75 MiB), not on a swipe frame.
    size_t targetW = (size_t)(MIN(w, 768.) / 8.) * 8;
    size_t targetH = (size_t)llround((double)targetW * 936. / 768. / 9.) * 9;
    NSDictionary *opts = @{(id)kCGImageSourceCreateThumbnailFromImageAlways:@YES,
        (id)kCGImageSourceCreateThumbnailWithTransform:@YES,
        (id)kCGImageSourceShouldCacheImmediately:@YES,
        (id)kCGImageSourceThumbnailMaxPixelSize:@(MAX(targetW, targetH))};
    CGImageRef thumb = CGImageSourceCreateThumbnailAtIndex(source, 0, (__bridge CFDictionaryRef)opts);
    CFRelease(source);
    if (!thumb) return nil;
    CGColorSpaceRef cs = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(NULL, targetW, targetH, 8, targetW*4, cs,
        kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(cs);
    if (!context) { CGImageRelease(thumb); return nil; }
    CGContextDrawImage(context, CGRectMake(0, 0, targetW, targetH), thumb);
    MSKeyOutBlackBackground(CGBitmapContextGetData(context), targetW, targetH);
    CGImageRef decoded = CGBitmapContextCreateImage(context);
    CGContextRelease(context); CGImageRelease(thumb);
    UIImage *image = decoded ? [UIImage imageWithCGImage:decoded scale:1. orientation:UIImageOrientationUp] : nil;
    if (decoded) CGImageRelease(decoded);
    MSAtlasIdentity = identity; MSAtlas = image;
    return image;
}
+ (void)refreshPreferences:(void (^)(NSString *, NSDictionary *))completion {
    dispatch_async(MSResourceQueue(), ^{
        @autoreleasepool {
            NSString *container = MSFindContainer();
            NSString *path = container ? [container stringByAppendingPathComponent:@"Library/Preferences/com.openminis.app.plist"] : nil;
            NSDictionary *prefs = path ? [NSDictionary dictionaryWithContentsOfFile:path] : nil;
            if (![prefs isKindOfClass:NSDictionary.class]) prefs = @{};
            NSMutableDictionary *filtered = [NSMutableDictionary dictionary];
            for (NSString *key in prefs) {
                if ([key isKindOfClass:NSString.class] && [key hasPrefix:@"minisight."]) filtered[key] = prefs[key];
            }
            NSDictionary *snapshot = [self mergedPreferencesWithContainer:container preferences:filtered];
            dispatch_async(dispatch_get_main_queue(), ^{ if (completion) completion(container, snapshot); });
        }
    });
}
+ (void)refresh:(void (^)(NSString *, NSDictionary *, BOOL, UIImage *))completion {
    dispatch_async(MSResourceQueue(), ^{
        @autoreleasepool {
            NSString *container = MSFindContainer();
            NSString *path = [container stringByAppendingPathComponent:@"Library/Preferences/com.openminis.app.plist"];
            NSDictionary *prefs = path ? [NSDictionary dictionaryWithContentsOfFile:path] : nil;
            if (![prefs isKindOfClass:NSDictionary.class]) prefs = @{};
            NSMutableDictionary *filtered = [NSMutableDictionary dictionary];
            for (NSString *key in prefs) {
                if ([key isKindOfClass:NSString.class] && [key hasPrefix:@"minisight."]) filtered[key] = prefs[key];
            }
            NSString *shownPath = [container stringByAppendingPathComponent:@"Documents/MiniSight/shown"];
            NSString *shown = shownPath ? [NSString stringWithContentsOfFile:shownPath encoding:NSUTF8StringEncoding error:nil] : nil;
            NSString *petPath = [container stringByAppendingPathComponent:@"Documents/MiniSight/pet.png"];
            UIImage *atlas = petPath ? MSLoadAtlas(petPath) : nil;
            NSDictionary *snapshot = [self mergedPreferencesWithContainer:container preferences:filtered];
            dispatch_async(dispatch_get_main_queue(), ^{ if (completion) completion(container, snapshot, ![shown isEqual:@"0"], atlas); });
        }
    });
}
+ (void)writeShown:(BOOL)shown container:(NSString *)container {
    if (!container) return;
    dispatch_async(MSResourceQueue(), ^{
        NSString *dir = [container stringByAppendingPathComponent:@"Documents/MiniSight"];
        [NSFileManager.defaultManager createDirectoryAtPath:dir withIntermediateDirectories:YES attributes:nil error:nil];
        NSString *value = shown ? @"1" : @"0";
        [[value dataUsingEncoding:NSUTF8StringEncoding]
            writeToFile:[dir stringByAppendingPathComponent:@"shown"] atomically:YES];
    });
}
+ (void)releaseCachedAtlas { dispatch_async(MSResourceQueue(), ^{ MSAtlas = nil; MSAtlasIdentity = nil; }); }
@end
