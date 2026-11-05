#import "MiniSightBlip.h"
#import <AVFoundation/AVFoundation.h>
#import <math.h>

static AVAudioPlayer *gPlayer;
static CFTimeInterval gLast;
static BOOL gFailed;

@implementation MiniSightBlip
+ (void)playIfEnabled:(BOOL)enabled {
    if (!enabled || gFailed) return;
    CFTimeInterval now = CACurrentMediaTime();
    if (now - gLast < 0.045) return; // 22 blips/s is plenty next to the sprite
    gLast = now;
    static dispatch_once_t once;
    dispatch_once(&once, ^{
        const int rate = 22050, frames = 900;      // ~40 ms
        NSMutableData *wav = [NSMutableData data];
        uint32_t chunk = 36 + frames * 2, sub = frames * 2, sr = rate, br = rate * 2;
        uint16_t pcm = 1, ch = 1, align = 2, bits = 16;
        [wav appendBytes:"RIFF" length:4]; [wav appendBytes:&chunk length:4];
        [wav appendBytes:"WAVEfmt " length:8]; [wav appendBytes:&sub length:4];
        [wav appendBytes:&pcm length:2]; [wav appendBytes:&ch length:2];
        [wav appendBytes:&sr length:4]; [wav appendBytes:&br length:4];
        [wav appendBytes:&align length:2]; [wav appendBytes:&bits length:2];
        [wav appendBytes:"data" length:4]; [wav appendBytes:&sub length:4];
        for (int i = 0; i < frames; i++) {
            double t = (double)i / rate;
            int16_t v = (int16_t)(9000.0 * exp(-t * 90.0) * sin(2.0 * M_PI * 1400.0 * t));
            [wav appendBytes:&v length:2];
        }
        gPlayer = [[AVAudioPlayer alloc] initWithData:wav error:NULL];
        gPlayer.volume = 0.22f;
        if (!gPlayer) gFailed = YES;
    });
    if (!gPlayer.playing) { gPlayer.currentTime = 0; [gPlayer play]; }
}
@end
