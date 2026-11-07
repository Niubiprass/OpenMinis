// Portable floating chat geometry; no UIKit, allocation or persistent state.
#ifndef MINISIGHT_CHAT_LAYOUT_H
#define MINISIGHT_CHAT_LAYOUT_H
#include "MiniSightGeometry.h"
#include <float.h>

/* Coordinate/content contract:
 * safe and pet are WORLD rectangles in the SAME fixed, screen-sized overlay
 * root (points). safe already excludes safeAreaInsets. keyboardTop is a world
 * Y; a finite value > 0 clips safe's bottom to keyboardTop - 8. Other values
 * mean no keyboard. A keyboard covering all of safe collapses usable height.
 *
 * messagesWanted is the measured OUTER bubble size, including its padding.
 * Returned messages/composer are outer WORLD frames, never content rectangles.
 * Their local content bounds start at (0,0); inset those for text/controls.
 * Preserve the full measured scroll content height when messages.h is clipped.
 * Convert frames to a wrapper's coordinates only at the UIKit boundary; never
 * subtract the safe origin twice or move the overlay window to follow the pet.
 *
 * Messages always remain ABOVE the composer and the pet; NEVER flip below.
 * Defaults: composer width 216, height 38; message height <= min(200,
 * usableHeight * .35), a 6pt inter-view gap and 10pt from the pet. Small/invalid
 * input uses compact controls and a scroll viewport, never a new pet position.
 * Host should reserve MSChatMinimumHeadroom() when deriving center bounds,
 * independently of measured text. Nonpositive/nonfinite widths use 216;
 * nonpositive/nonfinite message height hides messages. Missing/invalid pet
 * coordinates fall back to bottom-center of usable safe. Invalid safe origins
 * become 0 and invalid/negative safe sizes collapse to 0. Finite magnitudes
 * beyond DBL_MAX/16 saturate to avoid arithmetic overflow on corrupt input.
 *
 * Physically impossible bounds: composer height shrinks ONLY if usable height
 * is below 40 (possibly to zero); no positive-sized frame leaves usable safe.
 */
typedef struct {
    MSRect messages;
    MSRect composer;
    // Relative to the nearest outer frame: above => composer bottom edge;
    // below => messages top edge, or composer top when messages are hidden.
    // Kept 12pt from rounded corners (half-width for widths below 24pt).
    double tailX;
    int placedBelow;
    // Visible frames overlap pet because neither side can fit the composer.
    // Advisory only: host may reanchor the pet, rerun layout, or hide the tail.
    // This function never moves the pet; no relocation/animation state is kept.
    int petAvoidance;
} MSChatFloatingFrames;

static inline double MSChatMinimumHeadroom(double composerHeight) {
    return fmax(0., MSFinite(composerHeight, 38.)) + 16.;
}

static inline double MSChatLayoutCoordinate(double value, double fallback) {
    const double limit = DBL_MAX / 16.;
    return MSClamp(MSFinite(value, fallback), -limit, limit);
}

static inline double MSChatLayoutLength(double value, double fallback) {
    return fmin(DBL_MAX / 16., fmax(0., MSFinite(value, fallback)));
}

static inline int MSChatLayoutIntersects(MSRect a, MSRect b) {
    return a.w > 0. && a.h > 0. && b.w > 0. && b.h > 0. &&
           a.x < b.x + b.w && b.x < a.x + a.w &&
           a.y < b.y + b.h && b.y < a.y + a.h;
}

static inline MSChatFloatingFrames MSChatFloatingLayoutWithComposer(
    MSRect safe, MSRect pet, MSSize messagesWanted,
    double composerWantedWidth, double keyboardTop, int composerVisible) {
    const double gap = 6., petGap = 10.;
    MSChatFloatingFrames f;
    safe.x = MSChatLayoutCoordinate(safe.x, 0.);
    safe.y = MSChatLayoutCoordinate(safe.y, 0.);
    safe.w = MSChatLayoutLength(safe.w, 0.);
    safe.h = MSChatLayoutLength(safe.h, 0.);
    if (isfinite(keyboardTop) && keyboardTop > 0.)
        safe.h = fmax(0., fmin(safe.h, keyboardTop - 8. - safe.y));
    const double bottom = safe.y + safe.h;

    pet.w = MSChatLayoutLength(pet.w, 0.);
    pet.h = MSChatLayoutLength(pet.h, 0.);
    pet.x = MSChatLayoutCoordinate(pet.x, safe.x + safe.w * .5 - pet.w * .5);
    pet.y = MSChatLayoutCoordinate(pet.y, bottom - pet.h);
    const double centerX = pet.x + pet.w * .5;
    const double cw = fmin(safe.w, composerWantedWidth > 0. && isfinite(composerWantedWidth)
                                      ? composerWantedWidth : 216.);
    const double mw = fmin(safe.w, messagesWanted.w > 0. && isfinite(messagesWanted.w)
                                      ? messagesWanted.w : 216.);
    const double ch = composerVisible ? fmin(38., safe.h) : 0.;
    double mh = mw > 0. ? fmin(MSChatLayoutLength(messagesWanted.h, 0.),
                               fmin(200., safe.h * .35)) : 0.;
    const double aboveBottom = fmin(bottom, pet.y - petGap);
    const double aboveRoom = fmax(0., fmin(safe.h, aboveBottom - safe.y));
    double room;

    f.placedBelow = 0;
    // Composer remains above the pet; only its message viewport can shrink or
    // scroll. Never move/flip the pet in response to a layout measurement.
    room = aboveRoom;
    if (room < ch) room = ch; // impossible headroom: input wins, never flip below feet
    const double interGap = composerVisible ? gap : 0.;
    mh = fmin(mh, fmax(0., room - ch - interGap));
    const double totalHeight = ch + (mh > 0. ? interGap + mh : 0.);
    const double y = MSClamp(aboveBottom - totalHeight, safe.y, bottom - totalHeight);
    f.messages = (MSRect){MSClamp(centerX - mw * .5, safe.x, safe.x + safe.w - mw),
                          y, mw, mh};
    f.composer = (MSRect){MSClamp(centerX - cw * .5, safe.x, safe.x + safe.w - cw),
                          y + (mh > 0. ? mh + interGap : 0.), cw, ch};
    const MSRect nearest = composerVisible ? f.composer : f.messages;
    const double inset = fmin(12., nearest.w * .5);
    f.tailX = MSClamp(centerX - nearest.x, inset, nearest.w - inset);
    f.petAvoidance = MSChatLayoutIntersects(f.messages, pet) ||
                     MSChatLayoutIntersects(f.composer, pet);
    return f;
}
/* All controls are in LOCAL composer coordinates, including zero-sized/tiny
 * bounds. Accessories yield before text; no hit rect can exceed the capsule. */
typedef struct { MSRect field, more, mic, send; int hasMore, hasMic; } MSChatComposerFrames;
static inline MSChatComposerFrames MSChatComposerLayout(double width, double height, int sending) {
    double w = fmax(0., MSFinite(width, 0.)), h = fmax(0., MSFinite(height, 0.));
    MSChatComposerFrames f = {0};
    double edge = fmin(5., w * .04), right = fmax(edge, w - edge);
    double sendW = fmin(34., fmax(0., right - edge));
    double sendH = fmin(26., h);
    f.send = (MSRect){right - sendW, (h - sendH) * .5, sendW, sendH};
    right -= sendW;
    f.hasMic = !sending && w >= 176.;
    f.hasMore = w >= 132.;
    if (f.hasMic) { f.mic = (MSRect){right - 28., 0., 28., h}; right -= 28.; }
    double left = edge;
    if (f.hasMore) { f.more = (MSRect){edge, 0., 28., h}; left += 28.; }
    double gap = fmin(3., fmax(0., right - left) * .1);
    f.field = (MSRect){left, fmin(3., h * .1), fmax(0., right - gap - left), fmax(0., h - fmin(6., h * .2))};
    return f;
}
static inline MSChatFloatingFrames MSChatFloatingLayout(
    MSRect safe, MSRect pet, MSSize messagesWanted,
    double composerWantedWidth, double keyboardTop) {
    return MSChatFloatingLayoutWithComposer(safe, pet, messagesWanted,
                                            composerWantedWidth, keyboardTop, 1);
}
#endif
