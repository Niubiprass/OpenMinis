#ifndef MINISIGHT_MUSIC_ANIMATION_CLOCK_H
#define MINISIGHT_MUSIC_ANIMATION_CLOCK_H
#include <math.h>
#include <stdbool.h>
/* Artwork elapsed time only. Does not estimate/advance beats, tempo or phase.
 * Observe ONLY already-admitted producer samples. No UI/track clock is used. */
typedef struct { bool anchored; double lastSample, elapsed; } MSMusicAnimationClock;
static inline void MSMusicAnimationReset(MSMusicAnimationClock *s) {
    if (s) *s = (MSMusicAnimationClock){0};
}
static inline bool MSMusicAnimationObserve(MSMusicAnimationClock *s, double sample) {
    if (!s) return false;
    if (!isfinite(sample) || sample < 0.) { MSMusicAnimationReset(s); return false; }
    if (!s->anchored) {
        s->anchored = true; s->lastSample = sample; s->elapsed = 0.; return true;
    }
    double delta = sample - s->lastSample;
    if (!isfinite(delta) || delta <= 0. || delta > .40 || !isfinite(s->elapsed + delta)) {
        MSMusicAnimationReset(s); return false;
    }
    s->lastSample = sample; s->elapsed += delta;
    return true;
}
/* First decoded frame starts the artwork; decode latency is not played back. */
static inline void MSMusicAnimationRestart(MSMusicAnimationClock *s) {
    if (s) s->elapsed = 0.;
}
static inline double MSMusicAnimationElapsed(const MSMusicAnimationClock *s) {
    return s && s->anchored && isfinite(s->elapsed) && s->elapsed >= 0. ? s->elapsed : 0.;
}
#endif
