#ifndef MINISIGHT_RHYTHM_FRAME_H
#define MINISIGHT_RHYTHM_FRAME_H
#include <stdint.h>
#ifdef __cplusplus
extern "C" {
#endif
/* In-process C ABI, NOT a wire-format/endian specification.
 * sampleTime: monotonic audio sample-clock seconds, not a UI clock.
 * period: seconds/beat. phase: [0,1) estimate, NOT ground-truth alignment.
 * confidence: [0,1] conservative quality/stability score, NOT a probability.
 * Silence/Discontinuity frames invalidate all prior tempo/phase/beat state. */
enum {
    MSRhythmFlagValid = 1u << 0,
    MSRhythmFlagBeat = 1u << 1,
    MSRhythmFlagSilence = 1u << 2,
    MSRhythmFlagDiscontinuity = 1u << 3,
    MSRhythmFlagClipping = 1u << 4
};
typedef struct MSRhythmFrame {
    uint64_t epoch;
    uint64_t sequence;
    double sampleTime;
    double period;
    double phase;
    double confidence;
    double rms;
    double peak;
    uint32_t flags;
} MSRhythmFrame;
#ifdef __cplusplus
}
#endif
#endif
