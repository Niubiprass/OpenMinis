#ifndef MINISIGHT_LIVELINESS_H
#define MINISIGHT_LIVELINESS_H
#include <math.h>
#include <stdbool.h>
#include <string.h>
// UI-free policy: exact critically damped integration, no Euler explosions.
// Inspired by dsh-pet's separate follow/release responsibilities, not its code.
typedef struct { double value, velocity; } MSPetDamped;
static inline double MSPetFiniteClamp(double x, double lo, double hi) {
    return fmin(hi, fmax(lo, isfinite(x) ? x : 0.));
}
static inline void MSPetDampedStep(MSPetDamped *s, double target, double dt, double omega) {
    if (!s) return;
    dt = MSPetFiniteClamp(dt, 0., .05); omega = MSPetFiniteClamp(omega, 1., 80.);
    if (!isfinite(target)) target = 0.;
    if (!isfinite(s->value) || !isfinite(s->velocity)) { s->value = target; s->velocity = 0.; }
    double d = s->value - target, c = s->velocity + omega * d, e = exp(-omega * dt);
    s->value = target + (d + c * dt) * e;
    s->velocity = (s->velocity - omega * c * dt) * e;
}
typedef struct { double t, x, y; } MSPetDragSample;
typedef struct { MSPetDragSample samples[16]; unsigned count; } MSPetDragTrail;
static inline void MSPetDragRemember(MSPetDragTrail *trail, double t, double x, double y) {
    if (!trail || !isfinite(t) || !isfinite(x) || !isfinite(y)) return;
    if (trail->count > 16) trail->count = 0;
    if (trail->count && t <= trail->samples[trail->count - 1].t) return;
    if (trail->count >= 16) { memmove(trail->samples, trail->samples + 1, 15 * sizeof(MSPetDragSample)); trail->count = 15; }
    MSPetDragSample sample = {t,x,y}; trail->samples[trail->count++] = sample;
}
static inline bool MSPetReleaseVelocity(const MSPetDragTrail *trail, double now, double *vx, double *vy) {
    if (!vx || !vy) return false;
    *vx = 0.; *vy = 0.;
    if (!trail || trail->count < 2 || trail->count > 16 || !isfinite(now)) return false;
    MSPetDragSample last = trail->samples[trail->count - 1];
    if (now < last.t || now - last.t > .11) return false;
    unsigned first = trail->count - 1;
    while (first && now - trail->samples[first - 1].t <= .14) first--;
    MSPetDragSample begin = trail->samples[first];
    double dt = last.t - begin.t;
    if (dt < .018) return false;
    double x = (last.x - begin.x) / dt, y = (last.y - begin.y) / dt;
    double speed = hypot(x, y);
    if (!isfinite(speed) || speed < 160.) return false;
    double limit = fmin(speed, 1800.);
    *vx = x * limit / speed; *vy = y * limit / speed;
    return true;
}
static inline double MSPetMusicAmplitude(double previous, bool playing, double dt) {
    double value = MSPetFiniteClamp(previous, 0., 1.);
    double alpha = 1. - exp(-MSPetFiniteClamp(dt, 0., .05) / (playing ? .35 : .25));
    return value + ((playing ? 1. : 0.) - value) * alpha;
}
#endif
