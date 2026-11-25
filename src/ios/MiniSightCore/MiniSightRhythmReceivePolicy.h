#ifndef MINISIGHT_RHYTHM_RECEIVE_POLICY_H
#define MINISIGHT_RHYTHM_RECEIVE_POLICY_H
#include "MiniSightRhythmWire.h"
/* Inbound packet clock mapping only; no audio generation or beat extrapolation.
 * A new server/stream uses its first frame only as a clock baseline. A packet
 * can advance this state once; old sessions/sequence numbers never replay beats.
 * Arrival freshness is not proof of zero acoustic latency. */
typedef struct { uint64_t server,epoch,packetSequence,frameSequence,retiredServers[4]; unsigned retiredCount,retiredNext; double sampleTime,receivedAt; bool initialized; } MSRhythmReceiveState;
enum { MSRhythmReceiveReject=0,MSRhythmReceiveReset=1,MSRhythmReceiveUpdate=2 };
static inline void MSRhythmReceiveResetState(MSRhythmReceiveState*s){if(s)memset(s,0,sizeof(*s));}
static inline int MSRhythmReceive(MSRhythmReceiveState*s,const MSRhythmEnvelope*e,const MSRhythmFrame*f,double now){
 if(!s||!e||!MSRhythmFrameSane(f)||!isfinite(now)||now<0||!e->server||!e->sequence)return MSRhythmReceiveReject;
 if(s->initialized&&e->server==s->server&&e->sequence<=s->packetSequence)return MSRhythmReceiveReject;
 if(s->initialized&&now<s->receivedAt)return MSRhythmReceiveReject;
 if(s->initialized&&e->server!=s->server){
  for(unsigned i=0;i<s->retiredCount;++i)if(e->server==s->retiredServers[i])return MSRhythmReceiveReject;
  s->retiredServers[s->retiredNext]=s->server;s->retiredNext=(s->retiredNext+1u)%4u;if(s->retiredCount<4)++s->retiredCount;
 }
 bool boundary=!s->initialized||e->server!=s->server||f->epoch!=s->epoch;
 if(!boundary&&f->sequence<=s->frameSequence)return MSRhythmReceiveReject;
 if(!boundary){
  double sampleDelta=f->sampleTime-s->sampleTime,arrivalDelta=now-s->receivedAt;
  // A frozen/reset/jumping sample clock must not synthesize beat events.
  if(sampleDelta<=0||sampleDelta>.4||arrivalDelta>.4||fabs(sampleDelta-arrivalDelta)>.25)boundary=true;
 }
 s->initialized=true;s->server=e->server;s->epoch=f->epoch;s->packetSequence=e->sequence;
 s->frameSequence=f->sequence;s->sampleTime=f->sampleTime;s->receivedAt=now;
 if(boundary||(f->flags&(MSRhythmFlagSilence|MSRhythmFlagDiscontinuity))||!(f->flags&MSRhythmFlagValid))return MSRhythmReceiveReset;
 return MSRhythmReceiveUpdate;
}
static inline bool MSRhythmReceiveFresh(const MSRhythmReceiveState*s,double now){return s&&s->initialized&&isfinite(now)&&now>=s->receivedAt&&now-s->receivedAt<=.35;}
#endif
