#ifndef MINISIGHT_PET_BEHAVIOR_H
#define MINISIGHT_PET_BEHAVIOR_H

// UIKit-free production policy. The view supplies its EXISTING sprite/motion
// clock and monotonic time; this helper creates no timers or motion of its own.
#include <stdbool.h>
#include <math.h>
#include <string.h>
#include "MiniSightGeometry.h"

#define MS_PET_SLEEP_AFTER 18.0
#define MS_PET_SLEEP_DURATION 12.0
#define MS_PET_WAKE_DURATION 0.60
#define MS_PET_ATTENTION_LIFETIME 3.0
#define MS_PET_IDLE_FRAME_INTERVAL 0.25
#define MS_PET_SLEEP_FRAME_INTERVAL (1.0 / 3.0)

typedef struct {
    bool running, sleeping, waking, blinking;
    double idleBegan, sleepBegan, wakeBegan, blinkBegan, nextBlinkAt;
    double attentionUntil, roamResumeAt;
} MSPetResident;

typedef struct {
    bool running, activity, interaction, paused, moving, holding;
    unsigned locks;
} MSPetResidentContext;

typedef enum {
    MSPetResidentUnchanged,
    MSPetResidentFellAsleep,
    MSPetResidentWoke,
    MSPetResidentFinishedWaking
} MSPetResidentTransition;

static inline double MSPetResidentTime(double now) {
    return isfinite(now) ? fmax(0.0, now) : 0.0;
}

static inline void MSPetResidentReset(MSPetResident *resident) {
    memset(resident, 0, sizeof(*resident));
}

static inline void MSPetResidentResetBlink(MSPetResident *resident) {
    resident->blinking = false;
    resident->nextBlinkAt = 0.0;
}

// A real interaction/activity boundary resets inactivity. Autonomous motions,
// frame-clock rearming, state holds and settings refreshes must NOT call this.
// Preserve an in-progress wake transition rather than restarting it per event.
static inline bool MSPetResidentTouch(MSPetResident *resident, double now) {
    now = MSPetResidentTime(now);
    bool wasSleeping = resident->sleeping;
    resident->running = true;
    resident->sleeping = false;
    resident->idleBegan = now;
    if (wasSleeping) {
        resident->waking = true;
        resident->wakeBegan = now;
    }
    MSPetResidentResetBlink(resident);
    return wasSleeping;
}

static inline bool MSPetResidentBlocked(MSPetResidentContext context) {
    return context.activity || context.interaction || context.paused || context.locks != 0;
}

static inline bool MSPetResidentTrySleep(MSPetResident *resident, double now,
                                         MSPetResidentContext context) {
    if (!context.running || MSPetResidentBlocked(context) || context.moving ||
        context.holding || resident->sleeping || resident->waking) return false;
    resident->running = true;
    resident->sleeping = true;
    resident->sleepBegan = MSPetResidentTime(now);
    resident->attentionUntil = 0.0;
    MSPetResidentResetBlink(resident);
    return true;
}

static inline MSPetResidentTransition MSPetResidentAdvance(MSPetResident *resident,
                                                            double now,
                                                            MSPetResidentContext context) {
    now = MSPetResidentTime(now);
    if (!context.running) {
        MSPetResidentReset(resident);
        return MSPetResidentUnchanged;
    }
    if (!resident->running) MSPetResidentTouch(resident, now);
    if (MSPetResidentBlocked(context)) {
        if (resident->sleeping && MSPetResidentTouch(resident, now)) return MSPetResidentWoke;
        resident->idleBegan = now; // A held activity/owner gate is not inactivity.
    }
    if (resident->waking) {
        if (now - resident->wakeBegan < MS_PET_WAKE_DURATION) return MSPetResidentUnchanged;
        resident->waking = false;
        return MSPetResidentFinishedWaking;
    }
    if (resident->sleeping) {
        if (now - resident->sleepBegan < MS_PET_SLEEP_DURATION) return MSPetResidentUnchanged;
        MSPetResidentTouch(resident, now);
        return MSPetResidentWoke;
    }
    if (now - resident->idleBegan >= MS_PET_SLEEP_AFTER &&
        MSPetResidentTrySleep(resident, now, context)) return MSPetResidentFellAsleep;
    return MSPetResidentUnchanged;
}

static inline void MSPetResidentCancelWakePose(MSPetResident *resident) {
    resident->waking = false;
}

static inline void MSPetResidentRequestAttention(MSPetResident *resident, double now) {
    MSPetResidentTouch(resident, now);
    resident->attentionUntil = MSPetResidentTime(now) + MS_PET_ATTENTION_LIFETIME;
}

// A single, bounded queued response waits for a drag/jump/fling/wake pose. It
// never takes ownership of a running motion and never creates a deferred timer.
static inline bool MSPetResidentTakeAttention(MSPetResident *resident, double now,
                                              bool poseAvailable) {
    if (resident->attentionUntil <= 0.0) return false;
    if (MSPetResidentTime(now) > resident->attentionUntil) {
        resident->attentionUntil = 0.0;
        return false;
    }
    if (!poseAvailable || resident->sleeping || resident->waking) return false;
    resident->attentionUntil = 0.0;
    return true;
}

// Keep the original absolute roam deadline across a bounded nap. Quiet/custom
// intervals longer than 18 seconds must still eventually get their old turn.
static inline void MSPetResidentSaveRoam(MSPetResident *resident, double now, double remaining) {
    if (isfinite(remaining)) resident->roamResumeAt = MSPetResidentTime(now) + fmax(0.05, remaining);
}

static inline double MSPetResidentTakeRoamDelay(MSPetResident *resident, double now) {
    if (resident->roamResumeAt <= 0.0 || resident->sleeping || resident->waking) return -1.0;
    double delay = fmax(0.05, resident->roamResumeAt - MSPetResidentTime(now));
    resident->roamResumeAt = 0.0;
    return delay;
}

// Row 0 has six verified poses: hold its original awake cell between randomly
// spaced blinks, then play the old blink/breathing clip once at its old 4 fps.
static inline int MSPetResidentIdleColumn(MSPetResident *resident, double now, double randomUnit) {
    static const int sequence[] = {1, 2, 3, 4, 5, 0};
    now = MSPetResidentTime(now);
    double unit = isfinite(randomUnit) ? fmin(1.0, fmax(0.0, randomUnit)) : 0.5;
    if (resident->nextBlinkAt <= 0.0) resident->nextBlinkAt = now + 3.0 + 4.0 * unit;
    if (!resident->blinking && now >= resident->nextBlinkAt) {
        resident->blinking = true;
        resident->blinkBegan = now;
    }
    if (!resident->blinking) return 0;
    double step = floor(fmax(0.0, now - resident->blinkBegan) / MS_PET_IDLE_FRAME_INTERVAL);
    if (step < (double)(sizeof(sequence) / sizeof(sequence[0]))) return sequence[(int)step];
    resident->blinking = false;
    resident->nextBlinkAt = now + 3.0 + 4.0 * unit;
    return 0;
}

// Verified post-loader row 5: enter 0/1/2; only seated 3/4/5 breathe in the
// loop. Standing 6/7 belong to wake, never the sleeping modulo cycle.
static inline int MSPetResidentSleepColumn(double elapsed) {
    static const int seated[] = {3, 4, 5, 4};
    double step = floor(fmax(0.0, MSPetResidentTime(elapsed)) / MS_PET_SLEEP_FRAME_INTERVAL);
    if (step < 3.0) return (int)step;
    return seated[(int)fmod(step - 3.0, 4.0)];
}

static inline int MSPetResidentWakeColumn(double elapsed) {
    static const int sequence[] = {5, 6, 7};
    double step = floor(fmax(0.0, MSPetResidentTime(elapsed)) / (MS_PET_WAKE_DURATION / 3.0));
    return sequence[step < 3.0 ? (int)step : 2];
}

// Explicit delay policy: lively mode may shorten a user's configured interval;
// quiet mode lengthens it, while disabled mode schedules no roaming at all.
static inline double MSPetRoamDelay(double base, double pace, double interval,
                                    bool reducedWork, bool activity, double jitter) {
    if (!isfinite(pace) || pace <= 0.0) return 0.0;
    double unit = isfinite(jitter) ? fmin(1.0, fmax(0.0, jitter)) : 0.5;
    double delay = interval > 0.0 && isfinite(interval)
        ? interval * (0.75 + 0.5 * unit) : fmax(0.0, MSPetResidentTime(base));
    delay *= pace;
    if (reducedWork && !activity) delay *= 1.5;
    return fmax(0.05, fmin(delay, 300.0));
}

// Walk/jump between neighboring screen-space "perches" instead of choosing a
// random point anywhere on screen. The view still clamps every sample against
// its live safe bounds; the helper only proposes the next small destination.
static inline MSPoint MSPetNearbyTarget(MSRect bounds, MSPoint current,
                                        double horizontalChoice, double verticalChoice,
                                        bool jumping) {
    bounds.x = MSClamp(MSFinite(bounds.x, 0.0), -1000000.0, 1000000.0);
    bounds.y = MSClamp(MSFinite(bounds.y, 0.0), -1000000.0, 1000000.0);
    bounds.w = MSClamp(MSFinite(bounds.w, 0.0), 0.0, 1000000.0);
    bounds.h = MSClamp(MSFinite(bounds.h, 0.0), 0.0, 1000000.0);
    current = MSClampCenter(bounds, current);
    double hx = isfinite(horizontalChoice) ? fmin(1.0, fmax(0.0, horizontalChoice)) : 0.5;
    double vy = isfinite(verticalChoice) ? fmin(1.0, fmax(0.0, verticalChoice)) : 0.5;
    double direction = hx < 0.5 ? -1.0 : 1.0;
    if (current.x <= bounds.x + 8.0) direction = 1.0;
    if (current.x >= bounds.x + bounds.w - 8.0) direction = -1.0;
    double span = bounds.w * (0.18 + 0.24 * fabs(hx - 0.5) * 2.0);
    double x = MSClamp(current.x + direction * span,
                       bounds.x, bounds.x + bounds.w);
    if (bounds.h <= 1.0) return (MSPoint){x, current.y};
    int lanes = (int)floor(bounds.h / 56.0) + 1;
    if (lanes < 2) lanes = 2;
    if (lanes > 9) lanes = 9;
    int lane = (int)floor(((current.y - bounds.y) / bounds.h) * (lanes - 1) + 0.5);
    int step = (jumping || vy < 0.32 || vy > 0.68) ? 1 : 0;
    if (step && vy < 0.5) lane--;
    else if (step) lane++;
    if (lane < 0) lane = 1;
    if (lane >= lanes) lane = lanes - 2;
    double y = bounds.y + bounds.h * (double)lane / (double)(lanes - 1);
    return (MSPoint){x, MSClamp(y, bounds.y, bounds.y + bounds.h)};
}

static inline double MSPetSafeJumpHeight(MSRect bounds, MSPoint start,
                                         MSPoint end, double desired) {
    bounds.x = MSClamp(MSFinite(bounds.x, 0.0), -1000000.0, 1000000.0);
    bounds.y = MSClamp(MSFinite(bounds.y, 0.0), -1000000.0, 1000000.0);
    bounds.w = MSClamp(MSFinite(bounds.w, 0.0), 0.0, 1000000.0);
    bounds.h = MSClamp(MSFinite(bounds.h, 0.0), 0.0, 1000000.0);
    start = MSClampCenter(bounds, start);
    end = MSClampCenter(bounds, end);
    double clearance = fmin(start.y - bounds.y, end.y - bounds.y);
    return fmax(0.0, fmin(fmax(0.0, MSPetResidentTime(desired)), clearance));
}

#endif
