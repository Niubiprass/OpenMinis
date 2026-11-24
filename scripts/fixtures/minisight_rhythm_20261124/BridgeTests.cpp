// Portable mocks only; never includes/loads Tweak.cpp, AudioToolbox or sockets.
#include "RhythmInput.h"
#include "MiniSightRhythmAnalyzer.h"
#include "MiniSightRhythmWire.h"
#include "FeaturePayload.h"
#include <cassert>
#include <cmath>
#include <cstdio>
#include <cstring>
#include <limits>
struct MSRhythmAnalyzer {};
static int calls=0, resets=0;
static MSRhythmAnalyzer mock;
extern "C" MSRhythmAnalyzer *MSRhythmAnalyzerCreate(void) { return &mock; }
extern "C" void MSRhythmAnalyzerDestroy(MSRhythmAnalyzer*) {}
extern "C" void MSRhythmAnalyzerReset(MSRhythmAnalyzer*) { ++resets; }
extern "C" bool MSRhythmAnalyzerProcess(MSRhythmAnalyzer*,const float *mag,
    size_t count,uint64_t e,uint64_t s,double t,double rate,double r,double p,
    MSRhythmFrame *f) {
    assert(count==1024 && mag && rate==48000);
    ++calls; *f={e,s,t,.5,.25,.9,r,p,MSRhythmFlagValid|MSRhythmFlagBeat};
    return true;
}
namespace MSHFServer {
constexpr uint32_t kAnalysisFrames=2048,kRhythmBinCount=1024;
struct MockState {
    MiniSightRhythmCapture::SampleClock rhythmClock;
    MSRhythmAnalyzer *rhythmAnalyzer=nullptr;
    float rhythmMagnitude[1025]{};
    uint32_t rollingCount=2048;
    bool nonFiniteInputPending=false;
} gAnalyzer;
#include "RhythmBridge.inc"
}
struct Frame {
    uint64_t streamEpoch=72; uint32_t status=16;
    float sampleRate=48000,rms=.125f,peak=.75f;
    float waveform[64]{},spectrum[64]{}; MSRhythmFrame rhythm{};
};
int main() {
    using namespace MSHFServer;
    static_assert(MSHF_PROTOCOL_PORT==44334);
    static_assert(MSHFFeatureMaskRhythm==4 && MSHFFeatureMaskAll==7);
    assert(MiniSightRhythmCapture::NewRhythmSubscriber(true,4));
    assert(MiniSightRhythmCapture::NewRhythmSubscriber(true,7));
    assert(!MiniSightRhythmCapture::NewRhythmSubscriber(false,4));
    assert(!MiniSightRhythmCapture::NewRhythmSubscriber(true,3));
    auto &c=gAnalyzer.rhythmClock;
    assert(c.Observe(72,0,2048,48000));
    MSRhythmFrame f{};
    ProduceRhythmFrame(true,false,.2f,.4f,&f);
    assert(calls==1 && f.sequence>0 && (f.flags&MSRhythmFlagDiscontinuity));
    assert(!(f.flags&(MSRhythmFlagValid|MSRhythmFlagBeat)) && f.period==0);
    assert(std::fabs(f.sampleTime-2048./48000)<1e-12);
    auto seq=c.sequence;auto epoch=c.epoch;double time=f.sampleTime;
    for(int i=0;i<1000;++i) {
        ProduceRhythmFrame(true,false,.2f,.4f,&f);
        assert(calls==1 && c.sequence==seq && f.sampleTime==time);
        assert(!(f.flags&(MSRhythmFlagValid|MSRhythmFlagBeat)));
    }
    assert(c.Observe(72,2048,800,48000));
    ProduceRhythmFrame(true,false,.2f,.4f,&f);
    assert(calls==2 && (f.flags&MSRhythmFlagBeat) && f.epoch==epoch);
    assert(std::fabs(f.sampleTime-2848./48000)<1e-12);
    Frame frame;frame.rhythm=f;
    for(int i=0;i<64;++i){frame.waveform[i]=float(i)/64;frame.spectrum[i]=float(i)/128;}
    const uint16_t sizes[]={0,284,284,540,96,352,352,608};
    for(uint32_t mask=1;mask<=7;++mask) {
        uint8_t packet[1024];memset(packet,0xa5,sizeof(packet));
        assert(MSHFFeaturePayloadLength(mask)==sizes[mask]);
        EncodeFeaturePayload(packet+32,mask,frame);
        uint8_t *p=packet+32;
        assert(MSHFReadU32(p+8)==mask && MSHFReadU32(p+12)==16);
        assert(MSHFReadF32(p+16)==48000);
        bool rhythm=mask&4;
        assert(MSHFReadU64(p)==(rhythm?f.epoch:72));
        assert(MSHFReadF32(p+20)==(rhythm?float(f.rms):frame.rms));
        assert(MSHFReadF32(p+24)==(rhythm?float(f.peak):frame.peak));
        size_t offset=28;
        if(mask&1){for(int i=0;i<64;++i)assert(MSHFReadF32(p+offset+4*i)==frame.waveform[i]);offset+=256;}
        if(mask&2){for(int i=0;i<64;++i)assert(MSHFReadF32(p+offset+4*i)==frame.spectrum[i]);offset+=256;}
        if(rhythm){MSRhythmFrame decoded;assert(MSRhythmDecodeFrame(p+offset,68,&decoded));assert(decoded.epoch==f.epoch && decoded.sequence==f.sequence && decoded.period==f.period);offset+=68;}
        assert(offset==sizes[mask] && p[offset]==0xa5);
        MSHFEncodeHeader(packet,3,sizes[mask],21,22,23);
        MSHFPacketHeader h;assert(MSHFDecodeHeader(packet,32+sizes[mask],&h));
        if(mask==4){MSRhythmEnvelope env;MSRhythmFrame decoded;assert(MSRhythmDecodePacket(packet,128,21,&env,&decoded));assert(env.server==22 && decoded.sequence==f.sequence);}
    }
    assert(MSHFFeaturePayloadLength(0)==0 && MSHFFeaturePayloadLength(8)==0);
    int before=calls;
    assert(c.Observe(72,2848,800,48000));
    ProduceRhythmFrame(true,false,0,0,&f);
    assert(calls==before && f.epoch!=epoch && (f.flags&MSRhythmFlagSilence));
    assert(!(f.flags&(MSRhythmFlagValid|MSRhythmFlagBeat)) && MSRhythmFrameSane(&f));
    epoch=f.epoch;seq=f.sequence;
    for(int i=0;i<100;++i) ProduceRhythmFrame(false,true,0,0,&f);
    assert(calls==before && f.epoch==epoch && f.sequence==seq);
    assert(c.Observe(72,3648,2048,48000));
    ProduceRhythmFrame(true,false,.2f,.4f,&f);
    assert(calls==before+1 && (f.flags&MSRhythmFlagDiscontinuity));
    epoch=f.epoch;
    assert(c.Observe(72,99999,2048,48000)); // missing descriptor breaks clock
    ProduceRhythmFrame(true,false,.2f,.4f,&f);
    assert(f.epoch!=epoch && f.sampleTime==2048./48000 && !(f.flags&MSRhythmFlagBeat));
    ResetRhythmState(); assert(!c.Fresh() && c.Time()==0);
    assert(c.Observe(99,0,2048,48000));
    gAnalyzer.nonFiniteInputPending=true;
    before=calls;ProduceRhythmFrame(true,false,.2f,.4f,&f);
    assert(calls==before && (f.flags&MSRhythmFlagDiscontinuity) && MSRhythmFrameSane(&f));
    gAnalyzer.nonFiniteInputPending=false;
    assert(!c.Observe(99,0,256,std::numeric_limits<double>::quiet_NaN()));
    assert(!c.Fresh());
    DestroyRhythmState();assert(gAnalyzer.rhythmAnalyzer==nullptr && resets>0);
    puts("Capture adapter: masks1..7, exactLE, parent decoder, fresh-only bridge, silence/drop/nonfinite/epoch PASS");
}
