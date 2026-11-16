#ifndef MINISIGHT_NAME_WAKE_GATE_H
#define MINISIGHT_NAME_WAKE_GATE_H
#include <stdbool.h>
#include <stdint.h>
/// Real production gate: a closed/reopened/manual-owned panel is never the
/// original name response, even when it is visible again.
static inline bool MSNameWakeMayStartInput(uint64_t expected, uint64_t identity,
    uint64_t lifecycle, bool pending, bool visible, bool sending, bool editing,
    bool voicePending, bool voiceListening) {
    return expected != 0 && expected == identity && expected == lifecycle &&
        pending && visible && !sending && !editing && !voicePending && !voiceListening;
}
#endif
