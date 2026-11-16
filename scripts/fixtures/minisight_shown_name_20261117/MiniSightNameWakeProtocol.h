#ifndef MINISIGHT_NAME_WAKE_PROTOCOL_H
#define MINISIGHT_NAME_WAKE_PROTOCOL_H
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <math.h>
/* Boot-relative clocks only. Future, NaN and a previous boot fail closed. */
static inline bool MSNWClockFresh(double now, double clock, double limit) {
    return isfinite(now) && isfinite(clock) && now >= 0 && clock >= 0 &&
        clock <= now && now - clock <= limit;
}
/* Canonical hyphenated UUID; preserve the caller's exact case on the wire. */
static inline bool MSNWUUID(const char *s, size_t n) {
    if (!s || n != 36) return false;
    for (size_t i = 0; i < n; ++i) {
        if (i == 8 || i == 13 || i == 18 || i == 23) { if (s[i] != '-') return false; }
        else if (!((s[i] >= '0' && s[i] <= '9') || (s[i] >= 'a' && s[i] <= 'f') ||
                   (s[i] >= 'A' && s[i] <= 'F'))) return false;
    }
    return true;
}
/* Call mode's idle-hidden overlay is deliberately NOT a safety input: a hit
   may show it briefly. User-hidden, unknown screen and renderer ownership are. */
static inline bool MSNWAllowed(bool enabled, bool shown, bool petStyle, bool resources,
    bool container, bool revision, bool known, bool blanked, bool unlocked, bool appRenderer, bool appFront) {
    return enabled && shown && petStyle && resources && container && revision &&
        known && !blanked && unlocked && !(appRenderer && appFront);
}
static inline bool MSNWBusy(bool approval, bool dragging, bool burst, bool activity,
    bool capture, bool recording, bool region, bool hostModal, bool sending, bool panelOtherOwner) {
    return approval || dragging || burst || activity || capture || recording || region ||
        hostModal || sending || panelOtherOwner;
}
static inline bool MSNWReadyMayConsume(bool sameToken, bool consumed, uint64_t response,
    bool currentLifecycle, bool safe, bool busyOtherOwner) {
    return sameToken && !consumed && response != 0 && currentLifecycle && safe && !busyOtherOwner;
}
#endif
