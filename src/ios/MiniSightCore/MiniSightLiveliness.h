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
// Heavy floor contact only: topple, dizzy pause, collect, rise, release.
// These are presentation phases, NOT a claim of four real atlas animations.
static inline int MSPetLandingStageAt(double elapsed) {
    if (!isfinite(elapsed) || elapsed < 0.) return 0;
    return elapsed < .38 ? 1 : elapsed < .94 ? 2 : elapsed < 1.48 ? 3 : elapsed < 2.16 ? 4 : 0;
}
static inline int MSPetLandingColumn(int stage, double age) {
    // No verified prone/dizzy/rise frames in the accessible user asset.
    // Keep the neutral frame rather than mislabeling sleep as a fall.
    (void)stage; (void)age; return 0;
}
// Playback-linked, in-place sway; never claims to detect the audio beat.
// Only idle/blink frames are safe without a separately verified dance asset.
static inline MSPetMusicCue MSPetMusicCueAt(double position) {
    MSPetMusicCue cue = {MSPetPoseIdle, 0u, 0.};
    if (!isfinite(position) || position < 0.) return cue;
    double phase = 2. * 3.141592653589793 * fmod(position, 1.2) / 1.2;
    cue.cue = (unsigned)(fmod(position, 1.2) >= .6);
    cue.pulse = .5 - .5 * cos(2. * phase);
    return cue;
}
typedef struct { double angle, bob; } MSPetMusicPresentation;
static inline MSPetMusicPresentation MSPetMusicPresentationAt(double position) {
    MSPetMusicPresentation p = {0., 0.};
    if (!isfinite(position) || position < 0.) return p;
    double phase = 2. * 3.141592653589793 * fmod(position, 1.2) / 1.2;
    // Slow side sway + a distinct twice-per-cycle whole-body nod cue. No new head art.
    p.angle = .085 * sin(phase) + .045 * sin(2. * phase);
    p.bob = -.018 * (.5 - .5 * cos(2. * phase)); // <=1.8% height, in place; not a jump.
    return p;
}
static inline double MSPetSmoothUnit(double t) {
    t = MSPetFiniteClamp(t, 0., 1.); return t * t * (3. - 2. * t);
}
typedef struct { double angle, dizzy; } MSPetLandingPresentation;
// Honest rigid-sprite fallback, not new prone/seated/get-up artwork.
// A continuous topple, pause with stars, then recovery; NO anisotropic squash.
static inline MSPetLandingPresentation MSPetLandingPresentationAt(double age) {
    MSPetLandingPresentation p = {0., 0.};
    if (!isfinite(age) || age < 0. || age >= 2.16) return p;
    if (age < .38) p.angle = 1.18 * MSPetSmoothUnit(age / .27);
    else if (age < .94) p.angle = 1.18;
    else if (age < 1.48) p.angle = 1.18 - .76 * MSPetSmoothUnit((age - .94) / .54);
    else p.angle = .42 * (1. - MSPetSmoothUnit((age - 1.48) / .68));
    p.dizzy = MSPetSmoothUnit((age - .32) / .12) * (1. - MSPetSmoothUnit((age - 1.06) / .24));
    return p;
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
    // One occasional neutral-row blink, not incessant row switching.
    double blink = fmod(t, 4.2);
    return blink < 3.6 ? 0 : (int)fmin(5., floor((blink - 3.6) / .1));
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
