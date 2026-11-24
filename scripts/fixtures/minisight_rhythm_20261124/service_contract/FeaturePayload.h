#pragma once
#include "MSHFProtocol.h"
#include "MiniSightRhythmWire.h"
namespace MSHFServer {
template <typename Frame>
inline void EncodeFeaturePayload(uint8_t *payload, uint32_t mask,
                          const Frame &frame) {
    uint8_t *cursor = payload;
    // Legacy masks 1/2/3 retain their exact prefix. New rhythm masks use
    // the stricter continuity epoch and UNSMOOTHED RMS/peak from the frame.
    const bool rhythm = (mask & MSHFFeatureMaskRhythm) != 0;
    MSHFWriteU64(cursor, rhythm ? frame.rhythm.epoch : frame.streamEpoch);
    cursor += sizeof(uint64_t);
    MSHFWriteU32(cursor, mask);
    cursor += sizeof(uint32_t);
    MSHFWriteU32(cursor, frame.status);
    cursor += sizeof(uint32_t);
    MSHFWriteF32(cursor, frame.sampleRate);
    cursor += sizeof(float);
    MSHFWriteF32(cursor, rhythm ? (float)frame.rhythm.rms : frame.rms);
    cursor += sizeof(float);
    MSHFWriteF32(cursor, rhythm ? (float)frame.rhythm.peak : frame.peak);
    cursor += sizeof(float);

    if (mask & MSHFFeatureMaskWaveform) {
        for (float value : frame.waveform) {
            MSHFWriteF32(cursor, value);
            cursor += sizeof(float);
        }
    }
    if (mask & MSHFFeatureMaskSpectrum) {
        for (float value : frame.spectrum) {
            MSHFWriteF32(cursor, value);
            cursor += sizeof(float);
        }
    }
    if (rhythm) MSRhythmEncodeFrame(cursor, &frame.rhythm);
}

} // namespace MSHFServer
