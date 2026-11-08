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
        const int rate = 22050, frames = 900;       // ~41 ms
        NSMutableData *wav = [NSMutableData data];
        // WAV: fmt chunk is exactly 16 bytes; only the data chunk is frames*2.
        // The old code put frames*2 in BOTH length fields, so every parser
        // jumped past the real data marker looking for a 2800-byte fmt block.
        uint32_t chunk = 36 + frames * 2, dataLen = frames * 2, sr = rate, br = rate * 2, fmtLen = 16;
        uint16_t pcm = 1, ch = 1, align = 2, bits = 16;
        [wav appendBytes:"RIFF" length:4]; [wav appendBytes:&chunk length:4];
        [wav appendBytes:"WAVEfmt " length:8]; [wav appendBytes:&fmtLen length:4];
        [wav appendBytes:&pcm length:2]; [wav appendBytes:&ch length:2];
        [wav appendBytes:&sr length:4]; [wav appendBytes:&br length:4];
        [wav appendBytes:&align length:2]; [wav appendBytes:&bits length:2];
        [wav appendBytes:"data" length:4]; [wav appendBytes:&dataLen length:4];
        for (int i = 0; i < frames; i++) {
            double t = (double)i / rate;
            double envelope = exp(-t * 55.0);
            double tone = sin(2.0 * M_PI * 760.0 * t) * 0.80
                        + sin(2.0 * M_PI * 1140.0 * t) * 0.20;
            int16_t v = (int16_t)(8200.0 * envelope * tone);
            [wav appendBytes:&v length:2];
        }
        NSError *error = nil;
        gPlayer = [[AVAudioPlayer alloc] initWithData:wav error:&error];
        if (!gPlayer) { gLast = 0; return; }
        gPlayer.volume = 0.24f;
        if (![gPlayer prepareToPlay]) { gPlayer = nil; gLast = 0; return; }
    }
    if (gPlayer) {
        gPlayer.currentTime = 0;
        if (![gPlayer play]) { gPlayer = nil; gLast = 0; }
    }
}
@end
