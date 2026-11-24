#include "MiniSightRhythmAnalyzer.h"
#include "vendor/BeatDetektor/BeatDetektor.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <memory>
#include <new>
#include <vector>

namespace {
const double kMaxGap = 0.075; // BD_DETECTION_RATE*dt must remain below 1.
const double kMinPeriod = 60.0 / 199.0;
const double kMaxPeriod = 60.0 / 80.0;
double unit(double v) { return std::max(0.0, std::min(1.0, v)); }
bool msFinite(double v) { return std::isfinite(v); }
}

struct MSRhythmAnalyzer {
    std::unique_ptr<BeatDetektor> detector, fastDetector;
    std::vector<float> bins, previous;
    bool haveStream = false;
    bool modelDirty = false;
    uint64_t epoch = 0, sequence = 0;
    double time = 0, rate = 0, origin = 0;
    size_t count = 0;
    double previousRMS = 0, stable = 0, candidate = 0;
    double onsetTimes[8] = {};
    size_t onsetCount = 0;
    double lastBeat = -1;

    MSRhythmAnalyzer() : detector(new BeatDetektor(80.0f,159.0f)),
        fastDetector(new BeatDetektor(100.0f,199.0f)) {
        bins.reserve(4096); previous.reserve(4096);
    }
    void clearModel() {
        // Vendor reset() does not reset all contest/counter/average fields.
        // Reconstruct it instead of patching any upstream source bytes.
        detector.reset(new BeatDetektor(80.0f,159.0f));
        fastDetector.reset(new BeatDetektor(100.0f,199.0f));
        bins.clear(); previous.clear();
        modelDirty = false; previousRMS = stable = candidate = 0;
        onsetCount = 0; lastBeat = -1;
    }
    void reset() {
        clearModel(); haveStream = false;
        epoch = sequence = 0; time = rate = origin = 0; count = 0;
    }
};

extern "C" MSRhythmAnalyzer *MSRhythmAnalyzerCreate(void) {
    try { return new MSRhythmAnalyzer; } catch (...) { return NULL; }
}
extern "C" void MSRhythmAnalyzerDestroy(MSRhythmAnalyzer *a) { delete a; }
extern "C" void MSRhythmAnalyzerReset(MSRhythmAnalyzer *a) {
    if (!a) return;
    try { a->reset(); } catch (...) { a->detector.reset(); a->fastDetector.reset(); a->haveStream = false; }
}

extern "C" bool MSRhythmAnalyzerProcess(MSRhythmAnalyzer *a,
    const float *magnitude, size_t count, uint64_t epoch, uint64_t sequence,
    double sampleTime, double sampleRate, double rms, double peak,
    MSRhythmFrame *out) {
    MSRhythmFrame f = {};
    f.epoch = epoch; f.sequence = sequence;
    f.sampleTime = msFinite(sampleTime) ? sampleTime : 0;
    f.rms = msFinite(rms) && rms >= 0 ? rms : 0;
    f.peak = msFinite(peak) && peak >= 0 ? peak : 0;
    if (msFinite(peak) && peak >= 0.999) f.flags |= MSRhythmFlagClipping;
    if (out) *out = f;
    if (!a) { if (out) out->flags |= MSRhythmFlagDiscontinuity; return false; }
    try {
        // Validate shape before reading anything, preventing vendor range_step=0
        // or its fixed 128-range arrays from being indexed out of bounds.
        bool good = out && magnitude && epoch && sequence && count >= 128 && count <= 4096 &&
            count % 128 == 0 && msFinite(sampleTime) && sampleTime >= 0 &&
            msFinite(sampleRate) && sampleRate >= 8000 && sampleRate <= 192000 &&
            msFinite(rms) && msFinite(peak) && rms >= 0 && peak >= rms && peak <= 8 &&
            ((rms == 0) == (peak == 0));
        double sum = 0;
        if (good) {
            const double bound = 2.0 * double(count) * peak + 1e-6;
            for (size_t i=0; i<count; ++i) {
                double v = magnitude[i];
                if (!msFinite(v) || v < 0 || v > bound) { good=false; break; }
                sum += v;
            }
            if ((peak == 0 && sum != 0) || (rms > 0 && sum == 0)) good=false;
        }
        if (!good) {
            a->clearModel();
            f.flags |= MSRhythmFlagDiscontinuity;
            if (out) *out = f;
            return false;
        }
        const bool sameEpoch = a->haveStream && a->epoch == epoch;
        if (sameEpoch && (sequence <= a->sequence || sampleTime <= a->time)) {
            // Preserve the accepted sequence/time watermark after rejection.
            a->clearModel(); f.flags |= MSRhythmFlagDiscontinuity;
            *out = f; return false;
        }
        bool boundary = !sameEpoch || !a->detector || !a->fastDetector || count != a->count ||
            std::fabs(sampleRate-a->rate) > 1e-6 ||
            (sameEpoch && sampleTime-a->time > kMaxGap) ||
            (sameEpoch && sampleTime-a->origin > 1800.0);
        double dt = sameEpoch ? sampleTime-a->time : 0;
        if (boundary) { a->clearModel(); a->origin = sampleTime; }
        a->haveStream = true; a->epoch = epoch; a->sequence = sequence;
        a->time = sampleTime; a->rate = sampleRate; a->count = count;
        if (boundary) f.flags |= MSRhythmFlagDiscontinuity;
        if (rms < 1e-5 || peak < 5e-5) {
            if (a->modelDirty) a->clearModel();
            a->origin = sampleTime;
            f.flags |= MSRhythmFlagSilence;
            *out = f; return true;
        }
        // Origin+1 avoids the vendor's special zero-start timestamp and keeps
        // its float clock precise even when the host sample clock is large.
        if (!a->modelDirty) a->origin = sampleTime;
        a->bins.assign(magnitude, magnitude+count);
        double flux = 0, oldSum = 0;
        if (a->previous.size() == count) {
            for (size_t i=0; i<count; ++i) {
                flux += std::max(0.0, double(magnitude[i])-a->previous[i]);
                oldSum += a->previous[i];
            }
        }
        bool onset = !a->previous.empty() && rms > a->previousRMS*1.15+0.00003 &&
            flux / std::max(1e-9, sum+oldSum) > 0.10 &&
            (a->onsetCount == 0 || sampleTime-a->onsetTimes[a->onsetCount-1] > 0.18);
        if (onset) {
            if (a->onsetCount == 8) {
                for (size_t i=1; i<8; ++i) a->onsetTimes[i-1]=a->onsetTimes[i];
                --a->onsetCount;
            }
            a->onsetTimes[a->onsetCount++] = sampleTime;
        }
        a->previous.assign(magnitude,magnitude+count); a->previousRMS = rms;
        a->modelDirty = true;
        a->detector->process(float(sampleTime-a->origin+1.0), a->bins);
        a->fastDetector->process(float(sampleTime-a->origin+1.0), a->bins);
        // Vendor octave windows can settle on a mismatching local contest
        // (observed 150bpm -> 118bpm in 80..159). Evaluate a second unchanged
        // vendor instance, never replace its estimate with a hardcoded tempo.
        // Only periods corroborated by actual audio onsets may become Valid.
        BeatDetektor *chosen = NULL; size_t matching = 0;
        for (BeatDetektor *model : {a->detector.get(),a->fastDetector.get()}) {
            const double p = model->winning_bpm, c = model->current_bpm;
            bool qualified = msFinite(c) && msFinite(p) && p >= kMinPeriod &&
                p <= kMaxPeriod && model->win_val >= 25.0f && std::fabs(c-p)/p <= .03;
            size_t matches = 0;
            if (qualified && a->onsetCount >= 6)
                for (size_t i=1;i<a->onsetCount;++i)
                    if (std::fabs((a->onsetTimes[i]-a->onsetTimes[i-1])-p) <=
                        .10*p+std::min(dt,.025)) ++matches;
            if (qualified && (!chosen || matches > matching ||
                (matches==matching && model->win_val > chosen->win_val))) {
                chosen=model; matching=matches;
            }
        }
        const double period = chosen ? chosen->winning_bpm : 0; // seconds/beat
        bool quality = chosen != NULL;
        if (quality) {
            if (a->candidate > 0 && std::fabs(period-a->candidate)/period <= 0.025)
                a->stable += dt;
            else a->stable = 0;
            a->candidate = period;
        } else { a->candidate = a->stable = 0; }
        const double age = a->onsetCount ? sampleTime-a->onsetTimes[a->onsetCount-1] : 1e9;
        const double confidence = quality ? unit(chosen->win_val/60.0)*
            unit(a->stable/4.0)*unit(double(matching)/6.0) : 0;
        if (!boundary && quality && a->stable >= 2.0 && matching >= 5 &&
            age <= 1.7*period && confidence >= 0.5) {
            f.flags |= MSRhythmFlagValid;
            f.period = period; f.confidence = confidence;
            f.phase = unit(std::fmod(std::max(0.0,age),period)/period);
            if (onset && (a->lastBeat < 0 || sampleTime-a->lastBeat >= 0.65*period)) {
                f.flags |= MSRhythmFlagBeat; a->lastBeat = sampleTime;
            }
        }
        *out = f; return true;
    } catch (...) {
        // Never let C callers observe a C++ exception. Next accepted frame is
        // an explicit discontinuity even if reconstruction failed for memory.
        a->detector.reset(); a->fastDetector.reset(); a->haveStream = false;
        a->modelDirty = false; a->previous.clear(); a->bins.clear();
        a->onsetCount=0; a->stable=a->candidate=0; a->lastBeat=-1;
        f.flags = (f.flags & MSRhythmFlagClipping) | MSRhythmFlagDiscontinuity;
        if (out) *out=f;
        return false;
    }
}
