// macOS/CoreGraphics behavior of literal Pet methods; NOT real UIKit repaint.
// Unrelated host geometry/notifications are outside this fixture.
static BOOL FailNextCrop;
static NSUInteger CropCalls;
CGImageRef MSFixtureCrop(CGImageRef image, CGRect rect) {
    ++CropCalls;
    if (FailNextCrop) { FailNextCrop = NO; return NULL; }
    return CGImageCreateWithImageInRect(image, rect);
}
static NSData *Pixels(CGImageRef image) {
    if (!image) return nil;
    size_t w = CGImageGetWidth(image), h = CGImageGetHeight(image);
    NSMutableData *data = [NSMutableData dataWithLength:w * h * 4];
    CGColorSpaceRef color = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(data.mutableBytes, w, h, 8, w * 4, color,
        kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(color); CHECK(context);
    CGContextDrawImage(context, CGRectMake(0, 0, w, h), image); CGContextRelease(context);
    return data;
}
static BOOL SameImage(CGImageRef a, CGImageRef b) {
    return a && b && CGImageGetWidth(a) == CGImageGetWidth(b) && CGImageGetHeight(a) == CGImageGetHeight(b)
        && [Pixels(a) isEqual:Pixels(b)];
}
static BOOL MatchesPoster(MSRig *r) {
    return SameImage((__bridge CGImageRef)r.sprite.contents, r.poster.CGImage);
}
static UIImage *Atlas(size_t w, size_t h) {
    NSMutableData *data = [NSMutableData dataWithLength:w * h * 4];
    unsigned char *p = data.mutableBytes;
    for (size_t y = 0; y < h; ++y) for (size_t x = 0; x < w; ++x) {
        size_t i = (y * w + x) * 4;
        p[i] = (unsigned char)(x % 251); p[i+1] = (unsigned char)(y % 239);
        p[i+2] = (unsigned char)((x / 8 + y / 9) % 233); p[i+3] = 255;
    }
    CGColorSpaceRef color = CGColorSpaceCreateDeviceRGB();
    CGContextRef context = CGBitmapContextCreate(p, w, h, 8, w * 4, color,
        kCGImageAlphaPremultipliedLast | kCGBitmapByteOrder32Big);
    CGColorSpaceRelease(color); CHECK(context);
    CGImageRef cg = CGBitmapContextCreateImage(context); CGContextRelease(context);
    UIImage *image = [UIImage imageWithCGImage:cg]; CGImageRelease(cg); return image;
}
static void EmptyHost(MiniSightPetView *pet) {
    CHECK(pet.image == nil && pet.layer.contents == nil);
    // Model only the risky getter consumer, not UIKit internals.
    pet.layer.contents = (__bridge id)pet.image.CGImage;
    CHECK(pet.layer.contents == nil);
}
static void ExpectCrop(MiniSightPetView *pet, UIImage *source, CGRect rect) {
    EmptyHost(pet);
    CALayer *sprite = [pet valueForKey:@"gravityLayer"];
    CGImageRef expected = CGImageCreateWithImageInRect(source.CGImage, rect);
    CHECK(expected && SameImage((__bridge CGImageRef)sprite.contents, expected));
    CHECK(CGRectEqualToRect(sprite.contentsRect, CGRectMake(0, 0, 1, 1)));
    CGImageRelease(expected);
}
static MiniSightPetView *Pet(UIImage *source) {
    return [[MiniSightPetView alloc] initWithSprite:source displaySize:CGSizeMake(80, 90)];
}
static void AtlasLayouts(void) {
    UIImage *image = Atlas(768, 936); MiniSightPetView *pet = Pet(image);
    ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104)); // First frame, metadata absent.
    pet.spriteLayout = 3; [pet setValue:@3 forKey:@"state"]; [pet setValue:@2 forKey:@"column"];
    [pet applySpriteFrame]; ExpectCrop(pet, image, CGRectMake(192, 312, 96, 104));
    // One position anchor, two real atlas crops; a seek replaces the anchor immediately.
    MiniSightPetEffects *effects = [pet valueForKey:@"effects"];
    [pet setValue:@8 forKey:@"state"]; effects.musicPosition = .08; effects.musicPlaying = YES;
    // Music stays on the neutral row and only blinks occasionally; there is no
    // verified dance asset, so no row switching is choreographed.
    [pet applySpriteFrame]; ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
    Now += .70; [pet applySpriteFrame]; ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
    effects.musicPosition = 1.52; [pet applySpriteFrame]; ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
    // The default measured-input mode must stay neutral without measured input,
    // even when a playback cursor passes the old legacy blink threshold.
    CHECK(pet.rhythmFollowing && effects.rhythmFollowing);
    effects.musicPosition = 3.8; [pet applySpriteFrame]; ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
    // Explicit legacy-only regression: column 1 of row 0, never a dance row.
    // This excerpt fixture stores mode directly; it does not emulate host wiring.
    pet.rhythmFollowing = NO; effects.rhythmFollowing = NO;
    CHECK(!pet.rhythmFollowing && !effects.rhythmFollowing);
    [pet applySpriteFrame]; ExpectCrop(pet, image, CGRectMake(96, 0, 96, 104));
    effects.musicPlaying = NO; [pet setValue:@3 forKey:@"state"];
    pet.spriteLayout = 2; pet.variantIndex = 10; ExpectCrop(pet, image, CGRectMake(192, 104, 96, 104));
    pet.spriteLayout = 4; pet.variantIndex = 71; ExpectCrop(pet, image, CGRectMake(672, 832, 96, 104));
    image = Atlas(640, 810); pet.image = image; pet.spriteLayout = 0; pet.variantIndex = 10;
    ExpectCrop(pet, image, CGRectMake(180, 120, 10, 10)); // v10 + row3/col2, 64x81 legacy pack.
    pet.spriteLayout = 1; ExpectCrop(pet, image, CGRectMake(0, 0, 640, 810));
}
static void AtlasRepaintAndSameImage(void) {
    UIImage *image = Atlas(768, 936); MiniSightPetView *pet = Pet(image);
    CALayer *sprite = [pet valueForKey:@"gravityLayer"];
    pet.layer.contents = (__bridge id)image.CGImage; sprite.contents = (__bridge id)image.CGImage;
    pet.image = image; ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
    sprite.contents = nil; NSUInteger count = CropCalls; [pet applySpriteFrame];
    CHECK(CropCalls > count); ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
    // Unchanged cached rect cannot prevent restoring after an action replaced contents.
    sprite.contents = (__bridge id)Pixel(200).CGImage;
    [pet restorePosterFrame]; ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
    count = CropCalls; [pet applySpriteFrame]; CHECK(CropCalls == count);
    pet.image = nil; ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104)); // Invalid source preserves old.
    UIImage *next = Atlas(800, 900); pet.image = next; pet.spriteLayout = 3;
    ExpectCrop(pet, next, CGRectMake(0, 0, 100, 100));
}
static void AtlasCropFailureRetry(void) {
    UIImage *image = Atlas(768, 936); MiniSightPetView *pet = Pet(image);
    FailNextCrop = YES; [pet restorePosterFrame];
    CHECK([[pet valueForKey:@"gravityLayer"] contents] == nil);
    NSUInteger count = CropCalls; [pet applySpriteFrame]; CHECK(CropCalls > count);
    ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
}
static void AtlasActionPosterMetadata(void) {
    CHECK(!Loads.count); UIImage *image = Atlas(768, 936); MiniSightPetView *pet = Pet(image);
    pet.spriteLayout = 1; pet.actionManifestPath = @"fixture-poster-near-atlas-ratio";
    Load(Loads.lastObject, nil); // Invalid/missing clip still leaves the metadata-declared poster.
    ExpectCrop(pet, image, CGRectMake(0, 0, 768, 936));
    [pet restorePosterFrame]; ExpectCrop(pet, image, CGRectMake(0, 0, 768, 936));
    pet.spriteLayout = 3; ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104));
    pet.spriteLayout = 4; pet.variantIndex = 10; ExpectCrop(pet, image, CGRectMake(192, 104, 96, 104));
    pet.spriteLayout = 1; pet.actionManifestPath = nil;
    ExpectCrop(pet, image, CGRectMake(0, 0, 96, 104)); // Existing no-metadata aspect fallback unchanged.
    image = Atlas(768, 832); pet.image = image; pet.actionManifestPath = @"fixture-12-to-13-poster";
    Load(Loads.lastObject, nil); ExpectCrop(pet, image, CGRectMake(0, 0, 768, 832));
    image = Atlas(640, 810); pet.image = image; pet.spriteLayout = 0; pet.variantIndex = 10;
    ExpectCrop(pet, image, CGRectMake(160, 90, 10, 10)); // Stale manifest cannot flatten a pack.
}
static MSRig *AtlasRig(void) {
    MSRig *r = Rig(@{@"idle": Clip(@"idle", @[@.1, @5.])});
    r.poster = Atlas(768, 936); r.pet.spriteLayout = 3; r.pet.image = r.poster;
    ExpectCrop(r.pet, r.poster, CGRectMake(0, 0, 96, 104));
    return r;
}
static void AtlasEffectsFailureStop(void) {
    MSRig *r = AtlasRig(); UIImage *ready = Pixel(222); Finish(r.library, ready);
    CHECK(r.effects.hasActions && r.sprite.contents == (__bridge id)ready.CGImage);
    r.pet.image = r.poster; CHECK(r.sprite.contents == (__bridge id)ready.CGImage); EmptyHost(r.pet);
    Tick(r.effects, 100.2); Finish(r.library, nil);
    Tick(r.effects, 100.71); Finish(r.library, nil);
    Tick(r.effects, 101.72); Finish(r.library, nil);
    CHECK(!r.effects.hasActions); ExpectCrop(r.pet, r.poster, CGRectMake(0, 0, 96, 104));
    r = AtlasRig(); Finish(r.library, ready); Tick(r.effects, 100.2);
    FrameReply late = [r.library.pending.reply copy]; NSUInteger purges = r.library.purges;
    [r.effects setRunning:NO]; CHECK(r.library.purges > purges && !r.effects.hasActions);
    ExpectCrop(r.pet, r.poster, CGRectMake(0, 0, 96, 104));
    OnMain(^{ late(ready); }); ExpectCrop(r.pet, r.poster, CGRectMake(0, 0, 96, 104));
    [r.effects setRunning:YES]; CHECK(Pending(r.effects)); Finish(r.library, ready);
    [r.effects invalidate]; ExpectCrop(r.pet, r.poster, CGRectMake(0, 0, 96, 104));
}
static void AtlasManifestSwap(void) {
    MSRig *r = AtlasRig(); Finish(r.library, Pixel(222)); Tick(r.effects, 100.2);
    FrameReply stale = [r.library.pending.reply copy];
    r.pet.actionManifestPath = @"fixture-swapped-invalid";
    ExpectCrop(r.pet, r.poster, CGRectMake(0, 0, 96, 104));
    Load(Loads.lastObject, nil); OnMain(^{ stale(Pixel(99)); });
    ExpectCrop(r.pet, r.poster, CGRectMake(0, 0, 96, 104));
    r.pet.actionManifestPath = nil; r.pet.spriteLayout = 4; r.pet.variantIndex = 71;
    ExpectCrop(r.pet, r.poster, CGRectMake(672, 832, 96, 104));
    UIImage *next = Atlas(640, 810); r.pet.spriteLayout = 0; r.pet.image = next;
    ExpectCrop(r.pet, next, CGRectMake(560, 720, 10, 10));
    [r.pet restorePosterFrame]; ExpectCrop(r.pet, next, CGRectMake(560, 720, 10, 10));
}
