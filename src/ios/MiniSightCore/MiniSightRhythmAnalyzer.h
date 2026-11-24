#ifndef MINISIGHT_RHYTHM_ANALYZER_H
#define MINISIGHT_RHYTHM_ANALYZER_H
#include <stdbool.h>
#include <stddef.h>
#include "MiniSightRhythmFrame.h"
#ifdef __cplusplus
extern "C" {
#endif

typedef struct MSRhythmAnalyzer MSRhythmAnalyzer;
/* Single-owner, non-render/control queue only; vendor uses allocating maps.
 * Create returns NULL on allocation failure. Destroy(NULL) is safe.
 * Reset MUST be called on stop/interruption; it forgets the stream identity.
 * No timer, worker, playback, UI clock or automatic updates exist here. */
MSRhythmAnalyzer *MSRhythmAnalyzerCreate(void);
void MSRhythmAnalyzerDestroy(MSRhythmAnalyzer *analyzer);
void MSRhythmAnalyzerReset(MSRhythmAnalyzer *analyzer);
/* magnitude: genuine nonnegative LINEAR raw FFT magnitudes, not log/dB,
 * shaped bands, normalized features, or zero-padded 64-band substitutes.
 * count: [128,4096], divisible by 128. The vendor groups these bins itself.
 * sampleTime: audio sample-clock seconds (sample position / sampleRate),
 * finite and >=0. sampleRate: [8000,192000]. rms/peak: finite normalized PCM
 * amplitudes, 0<=rms<=peak<=8; raw magnitudes <=2*count*peak (+roundoff).
 * Consecutive inputs must have increasing sequence/time in the same epoch,
 * same count/rate, and 0<dt<=0.075 s. Any violation invalidates old tempo.
 * Epoch/count/rate changes or gaps are accepted boundary frames but invalid.
 * Bad input/stale/reversed frames return false and invalidate old tempo.
 * true means accepted input, NOT a valid tempo; inspect flags instead.
 * out is fully initialized on every call if non-NULL. NULL analyzer/out is
 * rejected. Invalid/silent/boundary output has zero period/phase/confidence.
 * Valid uses two unmodified BeatDetektor octave windows (80..159 and
 * 100..199 BPM), contest quality,
 * stable period agreement and repeated independent audio onset evidence.
 * confidence is a bounded heuristic quality score, NOT a probability.
 * Beat is an OBSERVED spectral/RMS rise, never a free-running vendor tick;
 * phase is an onset-relative estimate, NOT a guaranteed drum timestamp.
 * Parent owns freshness gates, UI motion and any cross-thread transport. */
bool MSRhythmAnalyzerProcess(MSRhythmAnalyzer *analyzer,
                            const float *magnitude, size_t count,
                            uint64_t epoch, uint64_t sequence,
                            double sampleTime, double sampleRate,
                            double rms, double peak, MSRhythmFrame *out);
#ifdef __cplusplus
}
#endif
#endif
