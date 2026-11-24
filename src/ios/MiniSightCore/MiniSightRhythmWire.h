#ifndef MINISIGHT_RHYTHM_WIRE_H
#define MINISIGHT_RHYTHM_WIRE_H
/* Optional rhythm-only extension of AudioSnapshotServer2 MSH2, source pin in
 * vendor provenance. Only localhost:44334, never original visualizer port44333.
 * Serialize LE integers/IEEE754 explicitly, never overlay a native structure.
 * No PCM, title, artist, cookies or network credentials belong in this packet. */
#include "MiniSightRhythmFrame.h"
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <string.h>
#include <math.h>
#define MS_RHYTHM_PORT 44334
#define MS_RHYTHM_HEADER 32u
#define MS_RHYTHM_PREFIX 28u
#define MS_RHYTHM_FRAME_BYTES 68u
#define MS_RHYTHM_MASK 4u
#define MS_RHYTHM_PACKET_BYTES (MS_RHYTHM_HEADER+MS_RHYTHM_PREFIX+MS_RHYTHM_FRAME_BYTES)
typedef struct { uint64_t session,server,sequence; } MSRhythmEnvelope;
static inline uint16_t MSRRead16(const uint8_t *p){return (uint16_t)p[0]|(uint16_t)p[1]<<8;}
static inline uint32_t MSRRead32(const uint8_t *p){return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24;}
static inline uint64_t MSRRead64(const uint8_t *p){return (uint64_t)MSRRead32(p)|(uint64_t)MSRRead32(p+4)<<32;}
static inline void MSRWrite16(uint8_t*p,uint16_t x){p[0]=(uint8_t)x;p[1]=(uint8_t)(x>>8);}
static inline void MSRWrite32(uint8_t*p,uint32_t x){for(unsigned i=0;i<4;++i)p[i]=(uint8_t)(x>>(8*i));}
static inline void MSRWrite64(uint8_t*p,uint64_t x){for(unsigned i=0;i<8;++i)p[i]=(uint8_t)(x>>(8*i));}
static inline double MSRReadDouble(const uint8_t*p){uint64_t x=MSRRead64(p);double f;memcpy(&f,&x,8);return f;}
static inline void MSRWriteDouble(uint8_t*p,double f){uint64_t x;memcpy(&x,&f,8);MSRWrite64(p,x);}
static inline float MSRReadFloat(const uint8_t*p){uint32_t x=MSRRead32(p);float f;memcpy(&f,&x,4);return f;}
static inline bool MSRhythmFrameSane(const MSRhythmFrame*f){
 const uint32_t known=MSRhythmFlagValid|MSRhythmFlagBeat|MSRhythmFlagSilence|MSRhythmFlagDiscontinuity|MSRhythmFlagClipping;
 if(!f||!f->epoch||!f->sequence||(f->flags&~known)||!isfinite(f->sampleTime)||f->sampleTime<0||f->sampleTime>1e9||
 !isfinite(f->period)||!isfinite(f->phase)||!isfinite(f->confidence)||!isfinite(f->rms)||!isfinite(f->peak)||
 f->rms<0||f->peak<0||f->rms>f->peak+1e-5||f->peak>8||f->confidence<0||f->confidence>1)return false;
 if((f->flags&MSRhythmFlagBeat)&&!(f->flags&MSRhythmFlagValid))return false;
 if((f->flags&MSRhythmFlagSilence)&&(f->flags&(MSRhythmFlagValid|MSRhythmFlagBeat)))return false;
 if(f->flags&MSRhythmFlagValid)return f->period>=.2&&f->period<=2&&f->phase>=0&&f->phase<1;
 return f->period==0&&f->phase==0&&f->confidence==0;
}
static inline void MSRhythmEncodeFrame(uint8_t *p,const MSRhythmFrame*f){
 MSRWrite64(p,f->epoch);MSRWrite64(p+8,f->sequence);
 const double v[6]={f->sampleTime,f->period,f->phase,f->confidence,f->rms,f->peak};
 for(unsigned i=0;i<6;++i)MSRWriteDouble(p+16+8*i,v[i]);MSRWrite32(p+64,f->flags);
}
static inline bool MSRhythmDecodeFrame(const uint8_t*p,size_t n,MSRhythmFrame*f){
 if(!p||!f||n!=MS_RHYTHM_FRAME_BYTES)return false;
 MSRhythmFrame v;memset(&v,0,sizeof(v));v.epoch=MSRRead64(p);v.sequence=MSRRead64(p+8);
 v.sampleTime=MSRReadDouble(p+16);v.period=MSRReadDouble(p+24);v.phase=MSRReadDouble(p+32);
 v.confidence=MSRReadDouble(p+40);v.rms=MSRReadDouble(p+48);v.peak=MSRReadDouble(p+56);v.flags=MSRRead32(p+64);
 if(!MSRhythmFrameSane(&v))return false;*f=v;return true;
}
static inline bool MSRhythmDecodePacket(const uint8_t*p,size_t n,uint64_t session,MSRhythmEnvelope*e,MSRhythmFrame*f){
 if(!p||!e||!f||!session||n!=MS_RHYTHM_PACKET_BYTES||memcmp(p,"MSH2",4)||MSRRead16(p+4)!=3||
 MSRRead16(p+6)!=MS_RHYTHM_PREFIX+MS_RHYTHM_FRAME_BYTES||MSRRead64(p+8)!=session||
 !MSRRead64(p+16)||!MSRRead64(p+24))return false;
 const uint8_t*q=p+MS_RHYTHM_HEADER;float rate=MSRReadFloat(q+16),rms=MSRReadFloat(q+20),peak=MSRReadFloat(q+24);
 if(MSRRead32(q+8)!=MS_RHYTHM_MASK||!isfinite(rate)||rate<8000||rate>192000||!isfinite(rms)||!isfinite(peak)||
 !MSRhythmDecodeFrame(q+MS_RHYTHM_PREFIX,MS_RHYTHM_FRAME_BYTES,f)||MSRRead64(q)!=f->epoch||
 fabs((double)rms-f->rms)>.0001||fabs((double)peak-f->peak)>.0001)return false;
 e->session=session;e->server=MSRRead64(p+16);e->sequence=MSRRead64(p+24);return true;
}
static inline size_t MSRhythmRequest(uint8_t*p,size_t n,bool subscribe,uint64_t session,uint64_t server,uint64_t seq){
 size_t length=MS_RHYTHM_HEADER+(subscribe?8u:0u);if(!p||n<length||!session||!seq)return 0;
 memset(p,0,length);memcpy(p,"MSH2",4);MSRWrite16(p+4,subscribe?1:2);MSRWrite16(p+6,subscribe?8:0);
 MSRWrite64(p+8,session);MSRWrite64(p+16,server);MSRWrite64(p+24,seq);
 if(subscribe){MSRWrite32(p+32,MS_RHYTHM_MASK);MSRWrite16(p+36,60);MSRWrite16(p+38,0);}return length;
}
#endif
