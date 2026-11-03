// Bounded visible gravity treatment, shared with portable regression tests.
#ifndef MINISIGHT_GRAVITY_H
#define MINISIGHT_GRAVITY_H
#include "MiniSightGeometry.h"
#define MS_GRAVITY_MAX_ANGLE (3.14159265358979323846 / 6.0)
#define MS_GRAVITY_TILT_ANGLE (3.14159265358979323846 / 10.0)

static inline double MSGravitySway(double width) {
    return MSClamp(MSFinite(width, 56.) * .12, 4., 12.);
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
#endif
