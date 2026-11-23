#ifndef MINISIGHT_PET_MUSIC_MOTION_H
#define MINISIGHT_PET_MUSIC_MOTION_H
// UI-free target policy only. The host's existing roam timer and motion link
// own scheduling, eased real-center interpolation, cancellation and safe clamps.
#include "MiniSightPetBehavior.h"

typedef struct { MSPoint target; bool jump, valid; } MSPetMusicTravel;
static inline MSPetMusicTravel MSPetMusicTravelAt(MSRect bounds, MSPoint current,
                                                 unsigned step) {
    bounds.x = MSClamp(MSFinite(bounds.x, 0.), -1000000., 1000000.);
    bounds.y = MSClamp(MSFinite(bounds.y, 0.), -1000000., 1000000.);
    bounds.w = MSClamp(MSFinite(bounds.w, 0.), 0., 1000000.);
    bounds.h = MSClamp(MSFinite(bounds.h, 0.), 0., 1000000.);
    current = MSClampCenter(bounds, current);
    MSPetMusicTravel travel = {current, false, false};
    if (bounds.w < 1. && bounds.h < 1.) return travel;
    // Two neighboring moves per direction, then turn. Alternate a real walk
    // and a travelling hop; do not randomly starve either action indefinitely.
    bool hop = (step & 1u) != 0;
    double horizontal = ((step / 2u) & 1u) ? .1 : .9;
    travel.target = MSPetNearbyTarget(bounds, current, horizontal, .8, hop);
    // Near the top, first walk to a lane with arc clearance. Never claim an
    // in-place jump or push an arc outside the host-provided feasible centers.
    if (hop) {
        double clearance = fmin(26., bounds.h * .5);
        if (clearance >= 6.) travel.target.y = fmax(travel.target.y, bounds.y + clearance);
    }
    if (hypot(travel.target.x - current.x, travel.target.y - current.y) < 1.) {
        if (bounds.w >= 1.) travel.target.x = current.x - bounds.x < bounds.w * .5
            ? bounds.x + bounds.w : bounds.x;
        else travel.target.y = current.y - bounds.y < bounds.h * .5
            ? bounds.y + bounds.h : bounds.y;
    }
    travel.target = MSClampCenter(bounds, travel.target);
    travel.valid = hypot(travel.target.x - current.x, travel.target.y - current.y) >= 1.;
    travel.jump = travel.valid && hop && MSPetSafeJumpHeight(bounds, current, travel.target, 26.) >= 6.;
    return travel;
}
#endif
