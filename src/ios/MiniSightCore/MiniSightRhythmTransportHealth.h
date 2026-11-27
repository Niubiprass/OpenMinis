#ifndef MINISIGHT_RHYTHM_TRANSPORT_HEALTH_H
#define MINISIGHT_RHYTHM_TRANSPORT_HEALTH_H
#include "MiniSightRhythmFrame.h"
#include "MiniSightPetRhythmPolicy.h"
#include <limits.h>
/* Diagnostics only: qualified transport frames are NOT proof of rendered motion.
 * No retry, audio production, clock extrapolation or relaxed acceptance here. */
typedef enum {
    MSRhythmHealthWaiting = 1, MSRhythmHealthSocketError,
    MSRhythmHealthNoPackets, MSRhythmHealthRejected,
    MSRhythmHealthReset, MSRhythmHealthSilence,
    MSRhythmHealthUnqualified, MSRhythmHealthQualified,
    MSRhythmHealthStale, MSRhythmHealthSendError, MSRhythmHealthReceiveError
} MSRhythmHealthCode;
typedef struct {
    double now, startedAt;
    unsigned datagrams, decoded;
    bool fresh, hasUpdate;
    MSRhythmFrame frame;
} MSRhythmHealthSample;
typedef struct { MSRhythmHealthCode code; double lastAt; unsigned count; } MSRhythmHealthLimiter;
static inline void MSRhythmHealthIncrement(unsigned *n) {
    if (*n < UINT_MAX) ++*n;
}
static inline bool MSRhythmHealthQualifiedFrame(MSRhythmFrame f) {
    return (f.flags & MSRhythmFlagValid) &&
        !(f.flags & (MSRhythmFlagDiscontinuity | MSRhythmFlagClipping | MSRhythmFlagSilence)) &&
        isfinite(f.confidence) && f.confidence >= MS_PET_RHYTHM_MIN_CONFIDENCE &&
        isfinite(f.period) && f.period >= .25 && f.period <= 1.5;
}
static inline MSRhythmHealthCode MSRhythmHealthClassify(MSRhythmHealthSample s) {
    if (!isfinite(s.now) || !isfinite(s.startedAt) || s.now < s.startedAt || s.now-s.startedAt < 2.) return MSRhythmHealthWaiting;
    if (!s.datagrams) return MSRhythmHealthNoPackets;
    if (!s.decoded) return MSRhythmHealthRejected;
    if (!s.fresh) return MSRhythmHealthStale;
    if (!s.hasUpdate) return MSRhythmHealthReset;
    if (s.frame.flags & MSRhythmFlagSilence) return MSRhythmHealthSilence;
    return MSRhythmHealthQualifiedFrame(s.frame) ? MSRhythmHealthQualified : MSRhythmHealthUnqualified;
}
static inline bool MSRhythmHealthShouldLog(MSRhythmHealthLimiter *s, MSRhythmHealthCode code, double now) {
    if (!s || !isfinite(now) || s->count >= 16) return false;
    bool changed=s->code != code;
    if (s->count && (!changed || now-s->lastAt < .5)) return false;
    s->code=code; s->lastAt=now; ++s->count; return true;
}
static inline const char *MSRhythmHealthReason(MSRhythmHealthCode code) {
    switch(code) {
        case MSRhythmHealthWaiting: return "rhythm_waiting";
        case MSRhythmHealthSocketError: return "rhythm_socket_error";
        case MSRhythmHealthNoPackets: return "rhythm_no_packets";
        case MSRhythmHealthRejected: return "rhythm_packet_rejected";
        case MSRhythmHealthReset: return "rhythm_server_reset";
        case MSRhythmHealthSilence: return "rhythm_silent_frame";
        case MSRhythmHealthUnqualified: return "rhythm_frame_unqualified";
        case MSRhythmHealthQualified: return "rhythm_frame_qualified";
        case MSRhythmHealthStale: return "rhythm_stream_stale";
        case MSRhythmHealthSendError: return "rhythm_send_error";
        case MSRhythmHealthReceiveError: return "rhythm_receive_error";
    }
    return "rhythm_unknown";
}
#endif
