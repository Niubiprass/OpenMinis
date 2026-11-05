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
 * Messages remain above the composer in both placements. Defaults: composer
 * width 230, height 40; message height <= min(200, usableHeight * .35), a 6pt
 * inter-view gap, and 10pt from the pet. Nonpositive/nonfinite widths use 230;
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

static inline MSChatFloatingFrames MSChatFloatingLayout(
    MSRect safe, MSRect pet, MSSize messagesWanted,
    double composerWantedWidth, double keyboardTop) {
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
                                      ? composerWantedWidth : 230.);
    const double mw = fmin(safe.w, messagesWanted.w > 0. && isfinite(messagesWanted.w)
                                      ? messagesWanted.w : 230.);
    const double ch = fmin(40., safe.h);
    double mh = mw > 0. ? fmin(MSChatLayoutLength(messagesWanted.h, 0.),
                               fmin(200., safe.h * .35)) : 0.;
    const double wantedHeight = ch + (mh > 0. ? gap + mh : 0.);
    const double aboveBottom = fmin(bottom, pet.y - petGap);
    const double belowTop = fmax(safe.y, pet.y + pet.h + petGap);
    const double aboveRoom = fmax(0., fmin(safe.h, aboveBottom - safe.y));
    const double belowRoom = fmax(0., fmin(safe.h, bottom - belowTop));
    double room;

    f.placedBelow = 0;
    if (aboveRoom >= wantedHeight) {
        room = aboveRoom;
    } else if (belowRoom >= wantedHeight) {
        f.placedBelow = 1;
        room = belowRoom;
    } else if (aboveRoom >= ch) {
        room = aboveRoom;
    } else if (belowRoom >= ch) {
        f.placedBelow = 1;
        room = belowRoom;
    } else {
        // Neither side fits even the input bar: keep input in safe and report
        // actual pet overlap below. Messages may disappear; input wins.
        room = safe.h;
    }
    mh = fmin(mh, fmax(0., room - ch - gap));
    const double totalHeight = ch + (mh > 0. ? gap + mh : 0.);
    const double y = MSClamp(f.placedBelow ? belowTop : aboveBottom - totalHeight,
                            safe.y, bottom - totalHeight);
    f.messages = (MSRect){MSClamp(centerX - mw * .5, safe.x, safe.x + safe.w - mw),
                          y, mw, mh};
    f.composer = (MSRect){MSClamp(centerX - cw * .5, safe.x, safe.x + safe.w - cw),
                          y + (mh > 0. ? mh + gap : 0.), cw, ch};
    const MSRect nearest = f.placedBelow && mh > 0. ? f.messages : f.composer;
    const double inset = fmin(12., nearest.w * .5);
    f.tailX = MSClamp(centerX - nearest.x, inset, nearest.w - inset);
    f.petAvoidance = MSChatLayoutIntersects(f.messages, pet) ||
                     MSChatLayoutIntersects(f.composer, pet);
    return f;
}
#endif
