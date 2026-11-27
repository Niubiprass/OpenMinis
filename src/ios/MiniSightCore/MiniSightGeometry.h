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
// Pet movement bounds keep the full body on-screen but do not reserve bubble
// space or the device safe area. A small visual inset still lets the pet reach
// the screen edges; callers position or hide bubbles independently.
static inline MSRect MSBodyCenterBounds(double width, double height, MSSize body, double inset) {
    width = fmax(1., MSFinite(width, 1.));
    height = fmax(1., MSFinite(height, 1.));
    double halfW = fmax(0., MSFinite(body.w, 0.)) * .5;
    double halfH = fmax(0., MSFinite(body.h, 0.)) * .5;
    double edge = MSClamp(inset, 0., 2.);
    double left = edge + halfW, right = width - edge - halfW;
    double top = edge + halfH, bottom = height - edge - halfH;
    if (right < left) left = right = width * .5;
    if (bottom < top) top = bottom = height * .5;
    return (MSRect){left, top, fmax(0., right - left), fmax(0., bottom - top)};
}
// Constrain only the rendered sprite at an edge, without shrinking its roam
// range or moving its untransformed hit target. Interior transforms are unchanged.
typedef struct { double a, b, c, d, tx, ty; } MSVisualTransform;
static inline MSVisualTransform MSPetFitVisualTransform(MSRect viewport, MSPoint center,
                                                       MSSize body, MSVisualTransform t) {
    viewport.x = MSFinite(viewport.x, 0.); viewport.y = MSFinite(viewport.y, 0.);
    viewport.w = fmax(1., MSFinite(viewport.w, 1.));
    viewport.h = fmax(1., MSFinite(viewport.h, 1.));
    center.x = MSFinite(center.x, viewport.x + viewport.w * .5);
    center.y = MSFinite(center.y, viewport.y + viewport.h * .5);
    body.w = fmax(1., MSFinite(body.w, 1.)); body.h = fmax(1., MSFinite(body.h, 1.));
    if (!isfinite(t.a) || !isfinite(t.b) || !isfinite(t.c) || !isfinite(t.d) ||
        !isfinite(t.tx) || !isfinite(t.ty)) t = (MSVisualTransform){1,0,0,1,0,0};
    double edge = fmin(2., fmin(viewport.w, viewport.h) * .1);
    double width = fabs(t.a) * body.w + fabs(t.c) * body.h;
    double height = fabs(t.b) * body.w + fabs(t.d) * body.h;
    double scale = fmin(1., fmin((viewport.w - 2. * edge) / fmax(1., width),
                                (viewport.h - 2. * edge) / fmax(1., height)));
    t.a *= scale; t.b *= scale; t.c *= scale; t.d *= scale;
    t.tx *= scale; t.ty *= scale; width *= scale; height *= scale;
    t.tx = MSClamp(center.x + t.tx, viewport.x + edge + width * .5,
        viewport.x + viewport.w - edge - width * .5) - center.x;
    t.ty = MSClamp(center.y + t.ty, viewport.y + edge + height * .5,
        viewport.y + viewport.h - edge - height * .5) - center.y;
    return t;
}
// Bubble placement may temporarily move the pet down, but ordinary roaming
// never reserves bubble headroom.
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
// Contract the roam rectangle, so drag, walk, hop and physics share one guard.
// Reserve space above the keyboard for the host's input bar. A negative height
// denotes no safe room; the owner temporarily suppresses only the pet.
static inline MSRect MSPetKeyboardCenters(MSRect base, MSSize body, MSRect keyboard) {
    if (!isfinite(keyboard.x) || !isfinite(keyboard.y) || !isfinite(keyboard.w) ||
        !isfinite(keyboard.h) || keyboard.w <= 0. || keyboard.h <= 0.) return base;
    double bottom = keyboard.y - 76. - body.h * .5;
    base.h = fmin(base.h, bottom - base.y);
    return base;
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
