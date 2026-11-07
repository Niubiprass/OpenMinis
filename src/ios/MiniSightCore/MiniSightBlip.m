#import "MiniSightBlip.h"
#import <AVFoundation/AVFoundation.h>
#import <math.h>

static AVAudioPlayer *gPlayer;
static CFTimeInterval gLast;

@implementation MiniSightBlip
+ (void)playIfEnabled:(BOOL)enabled {
    if (!enabled) return;
    CFTimeInterval now = CACurrentMediaTime();
    if (now - gLast < 0.10) return; // one blip per gesture, not per frame
    gLast = now;
    if (!gPlayer) {
        // Do not touch the shared session: a pet tap while the app is
        // recording or speaking must not switch it to Ambient.
        const int rate = 22050, frames = 1400;      // ~63 ms
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
            double envelope = exp(-t * 42.0);
            double tone = sin(2.0 * M_PI * 1180.0 * t) * 0.72
                        + sin(2.0 * M_PI * 1760.0 * t) * 0.28;
            int16_t v = (int16_t)(10500.0 * envelope * tone);
            [wav appendBytes:&v length:2];
        }
        gPlayer = [[AVAudioPlayer alloc] initWithData:wav error:NULL];
        gPlayer.volume = 0.36f;
        [gPlayer prepareToPlay];
    }
    if (gPlayer) { gPlayer.currentTime = 0; [gPlayer play]; }
}
@end
