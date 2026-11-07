// Bounded visible gravity treatment, shared with portable regression tests.
#ifndef MINISIGHT_GRAVITY_H
#define MINISIGHT_GRAVITY_H
#include "MiniSightGeometry.h"
#define MS_GRAVITY_MAX_ANGLE (2.0 * 3.14159265358979323846 / 9.0)
#define MS_GRAVITY_TILT_ANGLE (8.0 * 3.14159265358979323846 / 45.0)
#define MS_GRAVITY_INPUT_GAIN (1.0 / 0.55)

static inline double MSGravityRollFromProjected(double lateral) {
    double value = MSFinite(lateral, 0.) * MS_GRAVITY_INPUT_GAIN;
    if (fabs(value) < .025) value = 0.;
    return MSClamp(value, -1., 1.);
}

static inline double MSGravitySway(double width) {
    return MSClamp(MSFinite(width, 56.) * .16, 8., 18.);
}
static inline double MSGravityAngle(double roll, double impulse, double progress) {
    double base = MSClamp(roll, -1., 1.) * MS_GRAVITY_TILT_ANGLE;
    double p = MSFinite(progress, 1.);
    double kick = (p > 0. && p < 1.) ? MSFinite(impulse, 0.) * sin(3.14159265358979323846 * p) * exp(-2. * p) : 0.;
    return MSClamp(base + kick, -MS_GRAVITY_MAX_ANGLE, MS_GRAVITY_MAX_ANGLE);
}
// Maximum rotated axis-aligned extents over the ENTIRE angle interval, rather
// than assuming the extreme angle is always the largest rectangle.
static inline MSSize MSGravityEnvelope(MSSize body) {
    double w = fmax(1., MSFinite(body.w, 1.));
    double h = fmax(1., MSFinite(body.h, 1.));
    double aw = fmin(MS_GRAVITY_MAX_ANGLE, atan2(h, w));
    double ah = fmin(MS_GRAVITY_MAX_ANGLE, atan2(w, h));
    return (MSSize){w * cos(aw) + h * sin(aw) + 2. * MSGravitySway(w),
                    w * sin(ah) + h * cos(ah)};
}
// CoreMotion gravity axes projected into UIKit's current interface direction.
// orientation uses UIInterfaceOrientation: portrait1, upside-down2, left3,right4.
static inline MSPoint MSGravityProject(double x, double y, int orientation) {
    x = MSClamp(x, -1., 1.); y = MSClamp(y, -1., 1.);
    switch (orientation) {
        case 2: return (MSPoint){-x, y};
        case 3: return (MSPoint){y, x};
        case 4: return (MSPoint){-y, -x};
        default: return (MSPoint){x, -y};
    }
}
static inline double MSGravityFilter(double previous, double sample, double dt) {
    double alpha = 1. - exp(-MSClamp(dt, .001, .2) / .12);
    return MSClamp(previous + (sample - previous) * alpha, -1., 1.);
}
// CoreMotion userAcceleration is expressed in g. Hysteresis makes shaking
// responsive without retriggering on every sample.
#define MS_GRAVITY_SHAKE_ON_G 0.75
#define MS_GRAVITY_SHAKE_OFF_G 0.35
static inline int MSGravityShakeShouldTrigger(double magnitude, int latched) {
    return !latched && isfinite(magnitude) && magnitude >= MS_GRAVITY_SHAKE_ON_G;
}
static inline int MSGravityShakeShouldReset(double magnitude, int latched) {
    return latched && isfinite(magnitude) && magnitude <= MS_GRAVITY_SHAKE_OFF_G;
}
static inline double MSGravityShakeStrength(double magnitude) {
    double value = isfinite(magnitude) ? magnitude : 0.;
    return MSClamp((value - MS_GRAVITY_SHAKE_OFF_G) / 1.5, .2, 1.);
}

/* Shared, role-independent fling solver: center-space pt/s integration. */
#include <stdint.h>
enum { MSGravityHitLeft=1, MSGravityHitRight=2, MSGravityHitCeiling=4, MSGravityHitFloor=8 };
typedef struct {
    MSPoint position, velocity;
    double age;
    uint64_t generation, activeGeneration;
    unsigned impacts;
    int active;
} MSGravityBody;
static inline int MSGravityMotionAllowed(int playing, int suspended, int visible,
                                         int paused, int interacting, unsigned locks) {
    return playing && !suspended && visible && !paused && !interacting && !locks;
}
static inline MSRect MSGravityCenterRange(MSRect b) {
    return (MSRect){MSClamp(b.x, -1e6, 1e6), MSClamp(b.y, -1e6, 1e6),
                    MSClamp(MSFinite(b.w, 0.), 0., 1e6),
                    MSClamp(MSFinite(b.h, 0.), 0., 1e6)};
}
static inline uint64_t MSGravityNextGeneration(uint64_t generation) {
    return generation == UINT64_MAX ? UINT64_C(1) : generation + 1;
}
static inline void MSGravityBodyCancel(MSGravityBody *b) {
    b->generation = MSGravityNextGeneration(b->generation);
    b->activeGeneration = 0;
    b->active = 0;
    b->velocity = (MSPoint){0., 0.};
}
static inline uint64_t MSGravityBodyLaunch(MSGravityBody *b, MSRect range,
                                          MSPoint position, MSPoint velocity) {
    MSGravityBodyCancel(b);
    range = MSGravityCenterRange(range);
    b->position = MSClampCenter(range, position);
    b->velocity = (MSPoint){range.w > 0. ? MSClamp(velocity.x, -1800., 1800.) : 0.,
                            range.h > 0. ? MSClamp(velocity.y, -1800., 1800.) : 0.};
    b->age = 0.;
    b->impacts = 0;
    b->active = range.w > 0. || range.h > 0.;
    b->activeGeneration = b->active ? b->generation : 0;
    return b->activeGeneration;
}
static inline MSPoint MSGravityLaunchVelocity(double direction, double strength) {
    double s = MSClamp(MSFinite(strength, 0.), 0., 1.);
    double d = MSClamp(MSFinite(direction, 0.), -1., 1.);
    return (MSPoint){d * (480. + 760. * s), -(300. + 410. * s)};
}
static inline double MSGravityImpactVelocity(double incoming, unsigned impacts, int floor) {
    double loss = (floor ? .68 : .74) * pow(.93, fmin(impacts, 8));
    double outgoing = fabs(MSFinite(incoming, 0.)) * loss;
    return outgoing < (floor ? 34. : 14.) ? 0. : outgoing;
}
static inline unsigned MSGravityBodyStep(MSGravityBody *b, MSRect range, double roll,
                                        double elapsed, uint64_t token) {
    if (!b->active || !token || token != b->generation || token != b->activeGeneration) return 0;
    range = MSGravityCenterRange(range);
    b->position = MSClampCenter(range, b->position);
    double dt = MSClamp(MSFinite(elapsed, 0.), 0., .1);
    if (dt <= 0.) return 0;
    int count = (int)ceil(dt * 240.);
    double h = dt / count;
    unsigned hits = 0;
    for (int i=0; i<count && b->active; ++i) {
        int grounded = b->position.y >= range.y + range.h - 1e-7 && b->velocity.y == 0.;
        b->velocity.x = MSClamp(MSFinite(b->velocity.x, 0.), -1800., 1800.);
        b->velocity.y = MSClamp(MSFinite(b->velocity.y, 0.), -1800., 1800.);
        b->velocity.x *= exp(-(grounded ? 9. : .65) * h);
        if (!grounded) {
            b->velocity.x += MSClamp(roll, -1., 1.) * 110. * h;
            b->velocity.y = (b->velocity.y + 1050. * h) * exp(-.24 * h);
        }
        b->position.x += b->velocity.x * h;
        b->position.y += b->velocity.y * h;
        if (range.w <= 0.) { b->position.x = range.x; b->velocity.x = 0.; }
        else if (b->position.x < range.x && b->velocity.x < 0.) {
            b->position.x = range.x; b->velocity.x = MSGravityImpactVelocity(b->velocity.x, b->impacts++, 0); hits |= MSGravityHitLeft;
        } else if (b->position.x > range.x + range.w && b->velocity.x > 0.) {
            b->position.x = range.x + range.w; b->velocity.x = -MSGravityImpactVelocity(b->velocity.x, b->impacts++, 0); hits |= MSGravityHitRight;
        }
        if (range.h <= 0.) { b->position.y = range.y; b->velocity.y = 0.; }
        else if (b->position.y < range.y && b->velocity.y < 0.) {
            b->position.y = range.y; b->velocity.y = MSGravityImpactVelocity(b->velocity.y, b->impacts++, 0); hits |= MSGravityHitCeiling;
        } else if (b->position.y >= range.y + range.h && b->velocity.y > 0.) {
            b->position.y = range.y + range.h; b->velocity.y = -MSGravityImpactVelocity(b->velocity.y, b->impacts++, 1); b->velocity.x *= .92; hits |= MSGravityHitFloor;
        }
        b->position = MSClampCenter(range, b->position);
        b->age += h;
        if ((b->position.y >= range.y + range.h - 1e-7 && b->velocity.y == 0. && fabs(b->velocity.x) < 9.) || b->age >= 8.) {
            b->active = 0; b->velocity = (MSPoint){0., 0.};
        }
    }
    return hits;
}
#endif
