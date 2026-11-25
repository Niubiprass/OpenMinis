#ifndef MINISIGHT_PET_DAILY_POLICY_H
#define MINISIGHT_PET_DAILY_POLICY_H
/* No new art, motion, transforms or clocks. Only already-verified post-loader
 * atlas row 0 (six neutral/blink/breath poses) and row 3 (four wave poses).
 * Explicit layout 3 is a sheet even when sourceKind is singleImage. Static
 * images/outer-pose sheets and a separately-owned action sprite are excluded. */
#include <stdbool.h>
#include <math.h>
typedef enum {
    MSPetDailyNone = 0, MSPetDailyObserve = 1,
    MSPetDailyBreathe = 2, MSPetDailyWave = 3
} MSPetDailyFallback;
static inline MSPetDailyFallback MSPetDailyChooseFallback(int layout,
    bool hasSheet, bool actionSpriteOwned, unsigned previous, unsigned randomChoice) {
    if (!hasSheet || actionSpriteOwned || (layout != 0 && layout != 3)) return MSPetDailyNone;
    unsigned choice = 1u + randomChoice % 3u;
    if (choice == previous) choice = choice % 3u + 1u;
    return (MSPetDailyFallback)choice;
}
/* Existing verified atlas clips, with a neutral tail before returning to idle.
 * These are small blink/look/wave gestures, not invented stretch/yawn artwork. */
static inline double MSPetDailyFallbackDuration(MSPetDailyFallback action) {
    return action == MSPetDailyBreathe ? 2.40 : action == MSPetDailyWave ? 1.80 :
        action == MSPetDailyObserve ? 2.10 : 0.;
}
static inline int MSPetDailyFallbackPose(MSPetDailyFallback action) {
    return action == MSPetDailyWave ? 3 : 0;
}
static inline int MSPetDailyFallbackColumn(MSPetDailyFallback action, double elapsed) {
    double t = isfinite(elapsed) ? fmax(0., elapsed) : 0.;
    if (action == MSPetDailyWave) {
        static const int wave[] = {0,1,2,3,2,1,0};
        return wave[(int)fmin(6., floor(t / .24))];
    }
    if (action == MSPetDailyBreathe) {
        static const int neutral[] = {0,1,2,3,4,5,0};
        return neutral[(int)fmin(6., floor(t / .32))];
    }
    if (action == MSPetDailyObserve) {
        static const int look[] = {0,1,2,3,4,5,0};
        return look[(int)fmin(6., floor(t / .28))];
    }
    return 0;
}
#endif
