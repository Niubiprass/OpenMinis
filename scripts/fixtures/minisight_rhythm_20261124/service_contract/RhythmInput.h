#pragma once
#include <cmath>
#include <cstddef>
#include <cstdint>

// Control-queue-only. A continuity epoch is NOT the ring's byte/sample offset.
// The clock counts only complete, successfully drained source samples. Unknown
// lost time is never fabricated: any drop/gap starts a new continuity epoch.
// Masks without rhythm retain upstream streamEpoch; rhythm masks use this
// stricter continuity epoch in both the prefix and the appended frame.
// The epoch also changes on silence/stale/reset.
namespace MiniSightRhythmCapture {
inline bool NewRhythmSubscriber(bool newClient, uint32_t mask) {
    return newClient && (mask & 4u); // 5s lease renewal is NOT a reset
}
struct SampleClock {
    uint64_t epoch = 1;
    uint64_t sequence = 1;
    uint64_t sourceEpoch = 0;
    uint64_t samples = 0;
    uint64_t consumedSamples = 0;
    uint64_t expectedRingSample = 0;
    double sampleRate = 0;
    bool haveSource = false;
    bool discontinuity = true;
    bool invalid = true;
    bool pendingReset = true;

    void Break() {
        if (!discontinuity) { ++epoch; ++sequence; }
        samples = consumedSamples = 0;
        haveSource = false;
        discontinuity = invalid = pendingReset = true;
    }
    bool Observe(uint64_t streamEpoch, uint64_t ringStart,
                 uint32_t frameCount, double rate) {
        if (!frameCount || !std::isfinite(rate) || rate <= 0 ||
            UINT64_MAX - ringStart < frameCount) {
            Break();
            return false;
        }
        if (haveSource && (streamEpoch != sourceEpoch || rate != sampleRate ||
                           ringStart != expectedRingSample)) Break();
        haveSource = true;
        sourceEpoch = streamEpoch;
        sampleRate = rate;
        expectedRingSample = ringStart + frameCount;
        if (UINT64_MAX - samples < frameCount) Break();
        samples += frameCount;
        return true;
    }
    bool Fresh() const { return haveSource && samples != consumedSamples; }
    double Time() const { return sampleRate > 0 ? double(samples) / sampleRate : 0; }
    // No polling can create a sequence or advance sampleTime by itself.
    void Consume() {
        if (Fresh()) ++sequence;
        consumedSamples = samples;
    }
    void ClearDiscontinuity() { discontinuity = false; }
};
} // namespace MiniSightRhythmCapture
