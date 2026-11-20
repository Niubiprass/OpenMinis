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
static inline double MSPetMusicAmplitude(double previous, double target, double dt) {
    double value = MSPetFiniteClamp(previous, 0., 1.);
    target = MSPetFiniteClamp(target, 0., 1.);
    double timeConstant = target > value ? .12 : .25;
    double alpha = 1. - exp(-MSPetFiniteClamp(dt, 0., .05) / timeConstant);
    return value + (target - value) * alpha;
}

typedef enum {
    MSPetPoseIdle=0, MSPetPoseWalkRight=1, MSPetPoseWalkLeft=2,
    MSPetPoseWave=3, MSPetPoseJump=4, MSPetPoseSleep=5,
    MSPetPoseWake=6, MSPetPoseDrag=7, MSPetPoseMusic=8
} MSPetPose;
static inline unsigned MSPetPoseRoleCode(MSPetPose pose) {
    return pose >= MSPetPoseIdle && pose <= MSPetPoseMusic ? (unsigned)pose : 0u;
}
static inline int MSPetPoseAtlasRow(int pose) {
    static const int rows[9] = {0,1,2,3,4,5,5,3,0};
    return rows[MSPetPoseRoleCode((MSPetPose)pose)];
}
typedef struct { MSPetPose pose; unsigned cue; double pulse; } MSPetMusicCue;

// Between snapshot deliveries only the monotonic render clock advances.
static inline double MSPetMusicInterpolate(double position, double age, bool playing) {
    return fmax(0., isfinite(position) ? position : 0.) + (playing ? MSPetFiniteClamp(age, 0., 5.) : 0.);
}
// Heavy floor contact only: collapsed, dizzy, seated, rise, release.
static inline int MSPetLandingStageAt(double elapsed) {
    if (!isfinite(elapsed) || elapsed < 0.) return 0;
    return elapsed < .38 ? 1 : elapsed < .94 ? 2 : elapsed < 1.48 ? 3 : elapsed < 2.16 ? 4 : 0;
}
static inline int MSPetLandingColumn(int stage, double age) {
    double t = MSPetFiniteClamp(age, 0., 2.16);
    if (stage == 1) return 1;
    if (stage == 2) return 4 + (int)fmod(floor(t * 9.), 2.);
    if (stage == 3) return 3;
    return 5 + (int)MSPetFiniteClamp(floor((t - 1.48) / .22), 0., 2.);
}
// Repeatable playback-position choreography. This is not audio beat detection.
static inline MSPetMusicCue MSPetMusicCueAt(double position) {
    MSPetMusicCue cue = {MSPetPoseIdle, 0u, 0.};
    if (!isfinite(position) || position < 0.) return cue;
    static const MSPetPose poses[8] = {
        MSPetPoseWave, MSPetPoseWalkRight, MSPetPoseJump, MSPetPoseWalkLeft,
        MSPetPoseIdle, MSPetPoseJump, MSPetPoseWalkLeft, MSPetPoseWalkRight
    };
    double cycle = fmod(position, 4.8);
    cue.cue = (unsigned)fmin(7., floor(cycle / .6));
    cue.pose = poses[cue.cue];
    cue.pulse = MSPetFiniteClamp(exp(-6.5 * fmod(cycle, .6) / .6), 0., 1.);
    return cue;
}

static inline int MSPetPoseAtlasRowAt(int pose, double elapsed) {
    if (pose != MSPetPoseMusic) return MSPetPoseAtlasRow(pose);
    MSPetMusicCue cue = MSPetMusicCueAt(elapsed);
    return MSPetPoseAtlasRow((int)cue.pose);
}
static inline int MSPetPoseColumnAt(int pose, double elapsed) {
    double t = fmax(0., isfinite(elapsed) ? elapsed : 0.);
    if (pose == MSPetPoseDrag) return (int)fmod(floor(t / .12), 4.);
    if (pose != MSPetPoseMusic) return 0;
    MSPetMusicCue cue = MSPetMusicCueAt(t);
    if (cue.pose == MSPetPoseWave) return (int)fmin(3., floor(fmod(t, .6) / .15));
    if (cue.pose == MSPetPoseWalkLeft || cue.pose == MSPetPoseWalkRight) return (int)fmod(floor(t / .075), 8.);
    if (cue.pose == MSPetPoseJump) return (int)fmin(4., floor(fmod(t, .6) / .12));
    return (int)fmod(floor(t / .1), 6.);
}
static inline bool MSPetPoseIsTransient(MSPetPose pose) {
    return pose == MSPetPoseWave || pose == MSPetPoseJump || pose == MSPetPoseWake;
}
static inline MSPetPose MSPetPoseRestore(MSPetPose previous, bool music, bool sleeping, bool waking) {
    if (sleeping) return MSPetPoseSleep;
    if (waking) return MSPetPoseWake;
    if (music) return MSPetPoseMusic;
    if (previous == MSPetPoseDrag || previous == MSPetPoseMusic || MSPetPoseIsTransient(previous)) return MSPetPoseIdle;
    return (MSPetPose)MSPetPoseRoleCode(previous);
}
#endif
