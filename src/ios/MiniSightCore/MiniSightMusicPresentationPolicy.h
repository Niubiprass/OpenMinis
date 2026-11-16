#ifndef MINISIGHT_MUSIC_PRESENTATION_POLICY_H
#define MINISIGHT_MUSIC_PRESENTATION_POLICY_H
#include <stdbool.h>
#include <stdint.h>
#include <math.h>
/* Shared production gate. No timer, media API, I/O or inferred App visibility. */
typedef struct {
    bool shownKnown, shown, lyrics, motion, petStyle, appOwned, appFrontmost;
    bool windowExists, windowHidden, petExists, petHidden, frameVisible;
    double windowAlpha, renderedAlpha, petAlpha;
    bool screenKnown, screenBlanked, lockKnown, unlocked, containerKnown;
} MSMusicPresentation;
typedef enum {
    MSMusicGateOpen, MSMusicGateDisabled, MSMusicGateShownUnknown, MSMusicGateUserHidden,
    MSMusicGateStyle, MSMusicGateAppUnverified, MSMusicGateWindowMissing,
    MSMusicGateWindowHidden, MSMusicGatePetMissing, MSMusicGatePetHidden,
    MSMusicGateTransparent, MSMusicGateOffscreen, MSMusicGateScreenUnknown,
    MSMusicGateScreenBlanked, MSMusicGateLockUnknown, MSMusicGateLocked,
    MSMusicGateContainerMissing
} MSMusicGateReason;
static inline MSMusicGateReason MSMusicPresentationReason(MSMusicPresentation s) {
    if (!s.lyrics && !s.motion) return MSMusicGateDisabled;
    if (!s.shownKnown) return MSMusicGateShownUnknown;
    if (!s.shown) return MSMusicGateUserHidden;
    if (!s.petStyle) return MSMusicGateStyle;
    if (s.appOwned) {
        // Supply the current snapshot only while the selected App renderer is
        // frontmost. The App's existing visible-only bridge verifies its actual
        // pet/window. This is NOT proof that SpringBoard has painted a window.
        if (!s.appFrontmost) return MSMusicGateAppUnverified;
    } else {
        if (!s.windowExists) return MSMusicGateWindowMissing;
        if (s.windowHidden) return MSMusicGateWindowHidden;
        if (!s.petExists) return MSMusicGatePetMissing;
        if (s.petHidden) return MSMusicGatePetHidden;
        if (!isfinite(s.windowAlpha) || !isfinite(s.renderedAlpha) || !isfinite(s.petAlpha) ||
            s.windowAlpha <= .01 || s.renderedAlpha <= .01 || s.petAlpha <= .01) return MSMusicGateTransparent;
        if (!s.frameVisible) return MSMusicGateOffscreen;
    }
    if (!s.screenKnown) return MSMusicGateScreenUnknown;
    if (s.screenBlanked) return MSMusicGateScreenBlanked;
    if (!s.lockKnown) return MSMusicGateLockUnknown;
    if (!s.unlocked) return MSMusicGateLocked;
    if (!s.containerKnown) return MSMusicGateContainerMissing;
    return MSMusicGateOpen;
}
static inline const char *MSMusicGateReasonName(MSMusicGateReason r) {
    static const char *const names[] = {"eligible", "settings_disabled", "shown_state_unknown", "user_hidden",
        "not_pet_style", "app_presentation_unverified", "window_missing", "window_hidden", "pet_missing", "pet_hidden",
        "renderer_transparent", "frame_offscreen", "screen_state_unknown", "screen_blanked", "lock_state_unknown",
        "device_locked", "container_missing"};
    return (unsigned)r < sizeof(names)/sizeof(*names) ? names[r] : "unknown_gate";
}
/* Main-thread epochs fence delayed resource/settings and fade completions.
   Advancing on explicit hide ensures a captured old ON cannot reopen it. */
static inline uint64_t MSMusicNextEpoch(uint64_t *epoch) { return ++*epoch; }
static inline bool MSMusicEpochIsCurrent(uint64_t current, uint64_t captured) { return current == captured; }
static inline bool MSMusicShownMayReleaseHidden(bool known, bool shown, bool writePending,
                                                bool observedOff, bool priorIdentityKnown, bool identityChanged) {
    return known && shown && !writePending && (observedOff || (priorIdentityKnown && identityChanged));
}
#endif
