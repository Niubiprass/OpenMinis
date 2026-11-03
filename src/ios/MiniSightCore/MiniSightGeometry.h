// Pure-C geometry shared by the tweak, the pet, and host-side regression tests.
// All coordinates are in the FIXED overlay root view, never a moved UIWindow.
#ifndef MINISIGHT_GEOMETRY_H
#define MINISIGHT_GEOMETRY_H
#include <math.h>
typedef struct { double x, y; } MSPoint;
typedef struct { double w, h; } MSSize;
typedef struct { double x, y, w, h; } MSRect;
static inline double MSFinite(double v, double fallback) { return isfinite(v) ? v : fallback; }
static inline double MSClamp(double v, double lo, double hi) {
    return fmin(fmax(MSFinite(v, (lo + hi) * .5), lo), hi);
}
static inline MSRect MSSafeRect(double w, double h, double top, double bottom, double left, double right) {
    w = fmax(1., MSFinite(w, 1.)); h = fmax(1., MSFinite(h, 1.));
    left = MSClamp(left, 0., w * .45); right = MSClamp(right, 0., w * .45);
    top = MSClamp(top, 0., h * .45); bottom = MSClamp(bottom, 0., h * .45);
    return (MSRect){left, top, fmax(1., w-left-right), fmax(1., h-top-bottom)};
}
// Reserve headroom ABOVE the entire body, so speech never flips below its feet.
// If the viewport is too small, return a collapsed center range; callers scale
// the pet/bubble down or hide speech rather than overflowing or swapping sides.
static inline MSRect MSCenterBounds(MSRect safe, MSSize body, double headroom) {
    double hw = fmax(0., MSFinite(body.w, 0.))*.5;
    double hh = fmax(0., MSFinite(body.h, 0.))*.5;
    headroom = fmax(0., MSFinite(headroom, 0.));
    double l=safe.x+hw, r=safe.x+safe.w-hw;
    double t=safe.y+hh+headroom, b=safe.y+safe.h-hh;
    if (r<l) l=r=safe.x+safe.w*.5;
    if (b<t) t=b=safe.y+safe.h-hh;
    return (MSRect){l,t,fmax(0.,r-l),fmax(0.,b-t)};
}
static inline MSPoint MSClampCenter(MSRect centers, MSPoint p) {
    return (MSPoint){MSClamp(p.x,centers.x,centers.x+centers.w),
                     MSClamp(p.y,centers.y,centers.y+centers.h)};
}
static inline MSRect MSBubbleAbove(MSRect safe, MSPoint center, MSSize body, MSSize bubble, double gap) {
    double w=fmin(fmax(1.,bubble.w),safe.w);
    double h=fmin(fmax(1.,bubble.h),safe.h);
    double x=MSClamp(center.x-w*.5,safe.x,safe.x+safe.w-w);
    // No below-body fallback. Center bounds must already include headroom.
    return (MSRect){x,center.y-body.h*.5-fmax(0.,gap)-h,w,h};
}
static inline double MSJumpHeight(MSRect centers, MSPoint origin, double desired) {
    return fmax(0.,fmin(fmax(0.,desired),origin.y-centers.y));
}
static inline double MSSmooth(double t) { t=MSClamp(t,0.,1.); return t*t*(3.-2.*t); }
static inline MSPoint MSMotionPoint(MSPoint start, MSPoint end, double t) {
    double e=MSSmooth(t);
    return (MSPoint){start.x+(end.x-start.x)*e,start.y+(end.y-start.y)*e};
}
#endif
