#ifndef MINISIGHT_PET_RHYTHM_POLICY_H
#define MINISIGHT_PET_RHYTHM_POLICY_H
/* UI-free measured-input policy. Beat is the producer's estimated grid event,
 * NOT an acoustic ground-truth guarantee. No timers generate/advance beats. */
#include "MiniSightRhythmFrame.h"
#include "MiniSightPetMusicMotion.h"
#define MS_PET_RHYTHM_MAX_AGE .40
#define MS_PET_RHYTHM_MIN_CONFIDENCE .68

typedef struct {
    uint64_t epoch, sequence;
    uint64_t retiredEpochs[8];
    unsigned retiredCount, retiredNext;
    bool seen, anchored, hasSample, hasBeat, hasHop;
    double sampleAnchor, receiptAnchor, lastSample, lastReceipt, lastNow;
    double lastBeat, lastHop, previousRMS, previousPeak;
    unsigned step;
} MSPetRhythmPolicy;
typedef struct {
    bool accepted, beat, jump, valid;
    MSPoint target;
    double duration, height, strength, pulse;
} MSPetRhythmAction;

/* Keep watermarks across attention/track clears: a captured old callback must
 * not become a new beat after unlock. New producers MUST change epoch. */
static inline void MSPetRhythmClear(MSPetRhythmPolicy *s) {
    if (!s) return;
    s->anchored = false; // Beat/hop/sample high watermarks survive owner clears.
    s->lastReceipt = 0.; s->previousRMS = s->previousPeak = 0.;
    s->step = 0;
}
static inline bool MSPetRhythmFresh(const MSPetRhythmPolicy *s, double now) {
    return s && s->anchored && isfinite(now) && now >= s->lastNow &&
        now >= s->lastReceipt && now - s->lastReceipt <= MS_PET_RHYTHM_MAX_AGE;
}
static inline MSPetRhythmAction MSPetRhythmConsume(MSPetRhythmPolicy *s,
    MSRhythmFrame f, double receivedAt, double now, MSRect bounds,
    MSPoint current, bool available) {
    MSPetRhythmAction a = {0}; a.target = current;
    if (!s) return a;
    const uint32_t known = MSRhythmFlagValid | MSRhythmFlagBeat | MSRhythmFlagSilence |
        MSRhythmFlagDiscontinuity | MSRhythmFlagClipping;
    if (!isfinite(now) || !isfinite(receivedAt) || receivedAt < 0. ||
        receivedAt > now || now - receivedAt > .15 || (s->seen && now < s->lastNow)) {
        MSPetRhythmClear(s); return a;
    }
    s->lastNow = now;
    if (!f.epoch || !f.sequence || (s->seen &&
        f.epoch == s->epoch && f.sequence <= s->sequence)) {
        MSPetRhythmClear(s); return a;
    }
    bool newEpoch = !s->seen || f.epoch != s->epoch;
    if (newEpoch) {
        for (unsigned i = 0; i < s->retiredCount; ++i) {
            if (f.epoch == s->retiredEpochs[i]) { MSPetRhythmClear(s); return a; }
        }
        if (s->seen) {
            s->retiredEpochs[s->retiredNext] = s->epoch;
            s->retiredNext = (s->retiredNext + 1u) % 8u;
            if (s->retiredCount < 8u) ++s->retiredCount;
        }
        MSPetRhythmClear(s);
        s->hasSample = s->hasBeat = s->hasHop = false;
    }
    s->seen = true; s->epoch = f.epoch; s->sequence = f.sequence;
    if ((f.flags & ~known) || !(f.flags & MSRhythmFlagValid) ||
        (f.flags & (MSRhythmFlagSilence | MSRhythmFlagDiscontinuity | MSRhythmFlagClipping)) ||
        !isfinite(f.sampleTime) || f.sampleTime < 0. ||
        !isfinite(f.period) || f.period < .25 || f.period > 1.5 ||
        !isfinite(f.phase) || f.phase < 0. || f.phase >= 1. ||
        !isfinite(f.confidence) || f.confidence < MS_PET_RHYTHM_MIN_CONFIDENCE || f.confidence > 1. ||
        !isfinite(f.rms) || !isfinite(f.peak) || f.rms < 0. || f.rms > 1. ||
        f.peak < 0. || f.peak < f.rms || f.peak > 1.) {
        MSPetRhythmClear(s); return a;
    }
    bool anchored = s->anchored;
    if ((anchored && receivedAt < s->lastReceipt) ||
        (s->hasSample && f.sampleTime <= s->lastSample)) {
        MSPetRhythmClear(s); return a;
    }
    /* Compare clock DELTAS after anchoring. Never subtract audio-clock time
     * directly from CACurrentMediaTime (they have unrelated origins). */
    if (anchored && (now - s->lastReceipt > MS_PET_RHYTHM_MAX_AGE ||
        fabs((f.sampleTime - s->sampleAnchor) - (receivedAt - s->receiptAnchor)) > .18)) {
        MSPetRhythmClear(s); return a;
    }
    if (!anchored) {
        s->sampleAnchor = f.sampleTime; s->receiptAnchor = receivedAt;
        s->anchored = true;
    }
    s->hasSample = true;
    s->lastSample = f.sampleTime; s->lastReceipt = receivedAt;
    double rise = fmax(0., f.rms - s->previousRMS);
    double crest = fmax(0., f.peak - s->previousPeak);
    s->previousRMS = f.rms; s->previousPeak = f.peak;
    a.accepted = true;
    a.strength = MSClamp(f.rms * 2.4 + f.peak * .45, 0., 1.);
    a.pulse = MSClamp((.5 + .5 * cos(6.2831853071795864769 * f.phase)) * a.strength, 0., 1.);
    /* First input after stream/ownership/stale reset only anchors, even if its
     * beat bit is set. Busy beats are consumed, never queued for later. */
    if (!anchored || !(f.flags & MSRhythmFlagBeat)) return a;
    // A quiet inter-beat frame is not a stream reset. Keep the clock anchor,
    // but do not start travel from inaudible observations.
    if (f.rms < .008 || f.peak < .015) return a;
    if (s->hasBeat && f.sampleTime - s->lastBeat < fmax(.20, f.period * .70)) return a;
    s->lastBeat = f.sampleTime; s->hasBeat = true; a.beat = true;
    if (!available) return a;
    // Normalize against actual onset amplitudes, not an arbitrary near-full
    // scale hit. A confident Beat plus a measured RMS/crest rise is required;
    // the refractory gate below still prevents a hop on every beat.
    bool strong = a.strength >= .20 && (rise >= .020 || crest >= .15);
    a.jump = strong && (!s->hasHop || f.sampleTime - s->lastHop >= fmax(.85, f.period * 2.));
    MSPetMusicTravel route = MSPetMusicTravelAt(bounds, current, s->step & ~1u);
    double distance = (9. + 39. * a.strength) * MSClamp(.50 / f.period, .7, 1.4);
    double dx = route.target.x - current.x, dy = route.target.y - current.y;
    double length = hypot(dx, dy);
    if (!route.valid || length < 1.) return a;
    double fraction = fmin(1., distance / length);
    a.target = MSClampCenter(bounds, (MSPoint){current.x + dx * fraction, current.y + dy * fraction});
    a.height = a.jump ? MSPetSafeJumpHeight(bounds, current, a.target, 8. + 22. * a.strength) : 0.;
    if (a.height < 6.) { a.height = 0.; a.jump = false; }
    a.duration = a.jump ? MSClamp(f.period * .78, .22, .85) : MSClamp(f.period * .84, .22, 1.10);
    a.valid = hypot(a.target.x - current.x, a.target.y - current.y) >= 1.;
    if (a.valid) {
        ++s->step;
        if (a.jump) { s->lastHop = f.sampleTime; s->hasHop = true; }
    }
    return a;
}
#endif
