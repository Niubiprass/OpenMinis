// Offline tests only: deterministic synthesized PCM -> radix-2 FFT -> production API.
#include "MiniSightRhythmAnalyzer.h"
#include <algorithm>
#include <cmath>
#include <complex>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <limits>
#include <string>
#include <vector>

#ifndef MS_TEST_N
#define MS_TEST_N 1024
#endif
#ifndef MS_TEST_H
#define MS_TEST_H 256
#endif
#ifndef MS_TEST_FS
#define MS_TEST_FS 16000
#endif
static const int N=MS_TEST_N, H=MS_TEST_H, FS=MS_TEST_FS;
static const double PI=3.14159265358979323846;
static int failures=0;
static FILE *traceFile=NULL;
static void check(bool ok,const char *name) {
    std::printf("{\"check\":\"%s\",\"pass\":%s}\n",name,ok?"true":"false");
    if (!ok) ++failures;
}
struct Synth {
    std::string kind;
    double bpm;
    uint32_t rng=0x1ad71;
    Synth(const char *k,double b):kind(k),bpm(b) {}
    double sample(int64_t n) {
        const double t=double(n)/FS;
        rng=rng*1664525u+1013904223u;
        const double noise=(double(rng>>8)/8388608.0-1.0);
        if (kind=="silence") return 0;
        if (kind=="noise") return .12*noise;
        if (kind=="tone") return .23*std::sin(2*PI*997*t);
        double age=std::fmod(t,60.0/bpm);
        double env=age<.06 ? std::pow(std::sin(PI*age/.06),2) : 0;
        double amplitude=.65+.30*std::sin(2*PI*t/13.0);
        if (int(t/7)%2) amplitude*=.62;
        // Integer-Hz carriers repeat after one second. Cache exact PCM
        // samples to bound iSH test runtime, without bypassing FFT or vendor.
        static const std::vector<double> carriers=[]() {
            std::vector<double> c(FS,0);
            const double hz[]={220,440,660,880,1100,1320,1710,2190,2750,3430,4190,5270,6810};
            for (int n=0;n<FS;++n)
                for(int i=0;i<13;++i) c[n]+=std::sin(2*PI*hz[i]*n/FS+.31*i)/13;
            return c;
        }();
        double carrier=carriers[size_t(n%FS)];
        double bed=kind=="barepulse" ? 0 : .025;
        return (.9*env*amplitude+bed)*carrier;
    }
};
static void fft(std::vector<std::complex<double> > &x) {
    for (size_t i=1,j=0;i<x.size();++i) {
        size_t bit=x.size()>>1;
        for (;j&bit;bit>>=1) j^=bit;
        j^=bit;
        if(i<j) std::swap(x[i],x[j]);
    }
    for(size_t len=2;len<=x.size();len*=2) {
        std::complex<double> wlen=std::polar(1.0,-2*PI/len);
        for(size_t i=0;i<x.size();i+=len) {
            std::complex<double> w(1,0);
            for(size_t j=0;j<len/2;++j) {
                auto u=x[i+j],v=x[i+j+len/2]*w;
                x[i+j]=u+v;x[i+j+len/2]=u-v;w*=wlen;
            }
        }
    }
}
struct Feeder {
    Synth synth;
    MSRhythmAnalyzer *a;
    std::vector<double> pcm;
    std::vector<std::complex<double> > spectrum;
    std::vector<float> mag;
    uint64_t sequence=0,epoch=1;
    int frame=0;
    double rms=0,peak=0,time=0;
    Feeder(const char *kind,double bpm):synth(kind,bpm),a(MSRhythmAnalyzerCreate()),spectrum(N),mag(N/2) {}
    ~Feeder(){MSRhythmAnalyzerDestroy(a);}
    bool step(MSRhythmFrame &out) {
        int required=N+frame*H;
        while(int(pcm.size())<required) pcm.push_back(synth.sample(pcm.size()));
        static const std::vector<double> hann=[]() {
            std::vector<double> h(N);
            for(int i=0;i<N;++i) h[i]=.5-.5*std::cos(2*PI*i/(N-1));
            return h;
        }();
        rms=peak=0;
        double mean=0;
#ifdef MS_TEST_NORMALIZED_POWER
        for(int i=0;i<N;++i)mean+=pcm[frame*H+i]/N;
#endif
        for(int i=0;i<N;++i) {
            double v=pcm[frame*H+i]; rms+=v*v;peak=std::max(peak,std::fabs(v));
            spectrum[i]=(v-mean)*hann[i];
        }
        rms=std::sqrt(rms/N);fft(spectrum);
        double magnitudeScale=1;
#ifdef MS_TEST_NORMALIZED_POWER
        double windowGain=0;for(double w:hann)windowGain+=w*w/N;
        // vDSP real FFT power normalization in the service, expressed for
        // the ordinary complex FFT used only by this portable test.
        magnitudeScale=std::sqrt(2./windowGain)/N;
#endif
        for(int i=0;i<N/2;++i)mag[i]=std::abs(spectrum[i])*magnitudeScale;
#ifdef MS_TEST_NORMALIZED_POWER
        mag[0]/=std::sqrt(2.);
#endif
        time=double(required)/FS;
        ++frame;++sequence;
        return MSRhythmAnalyzerProcess(a,mag.data(),mag.size(),epoch,sequence,time,FS,rms,peak,&out);
    }
};
static double median(std::vector<double> v) {
    if(v.empty()) return 0;
    std::sort(v.begin(),v.end());return v[v.size()/2];
}
static void scenario(const char *kind,double bpm,bool strict) {
    Feeder feed(kind,bpm);MSRhythmFrame f={};
    std::vector<double> tempos,errors,beatErrors,conf;
    int valid=0,beats=0,total=0,late=0,bad=0;
    double first=-1;
    const double duration=std::string(kind)=="pulse"||std::string(kind)=="barepulse"?72:32;
    while(feed.time<duration) {
        if(!feed.step(f))++bad;
        if(traceFile && feed.time>=68.0) std::fprintf(traceFile,"{\"epoch\":%llu,\"sequence\":%llu,\"sampleTime\":%.9f,\"period\":%.9f,\"phase\":%.9f,\"confidence\":%.9f,\"rms\":%.9f,\"peak\":%.9f,\"flags\":%u,\"rate\":%d,\"now\":%.9f}\n",(unsigned long long)f.epoch,(unsigned long long)f.sequence,f.sampleTime,f.period,f.phase,f.confidence,f.rms,f.peak,f.flags,FS,f.sampleTime+100.0);
        ++total;
        if(f.flags&MSRhythmFlagValid) { ++valid;if(first<0)first=feed.time; }
        if(feed.time>=30) {
            ++late;
            if(f.flags&MSRhythmFlagValid) {tempos.push_back(60/f.period);errors.push_back(std::fabs(60/f.period-bpm)/bpm);conf.push_back(f.confidence);}
        }
        if(f.flags&MSRhythmFlagBeat) {
            ++beats;
            if(bpm>0){double d=std::fmod(feed.time,60/bpm);beatErrors.push_back(std::min(d,60/bpm-d));}
        }
        if((f.flags&MSRhythmFlagBeat)&&!(f.flags&MSRhythmFlagValid))++bad;
        if(!std::isfinite(f.confidence)||f.confidence<0||f.confidence>1||f.phase<0||f.phase>=1)++bad;
    }
    std::sort(errors.begin(),errors.end());
    double p95=errors.empty()?1:errors[size_t(.95*(errors.size()-1))];
    double coverage=late?double(tempos.size())/late:0;
    bool rhythmic=std::string(kind)=="pulse";
    bool ok=bad==0 && (rhythmic ? (!tempos.empty() && std::fabs(median(tempos)-bpm)/bpm<=.04 && p95<=.06 && coverage>=.70 && beats>=20) : (std::string(kind)=="barepulse" || (valid==0&&beats==0)));
    std::printf("{\"scenario\":\"%s\",\"target_bpm\":%.6f,\"seconds\":%.3f,\"frames\":%d,\"valid_frames\":%d,\"beats\":%d,\"first_valid_seconds\":%.4f,\"late_tempo_median_bpm\":%.6f,\"late_error_p95_fraction\":%.6f,\"late_valid_fraction\":%.6f,\"confidence_median\":%.6f,\"beat_grid_distance_median_seconds\":%.6f,\"rejected_or_bad\":%d,\"required\":%s,\"pass\":%s}\n",kind,bpm,duration,total,valid,beats,first,median(tempos),p95,coverage,median(conf),median(beatErrors),bad,strict?"true":"false",ok?"true":"false");
    if(strict&&!ok)++failures;
}
static bool empty(const MSRhythmFrame &f) {
    return !(f.flags&(MSRhythmFlagValid|MSRhythmFlagBeat))&&f.period==0&&f.phase==0&&f.confidence==0;
}
static void guards() {
    Feeder q("pulse",120);MSRhythmFrame f={};
    while(q.time<50)q.step(f);
    check((f.flags&MSRhythmFlagValid)!=0,"guard_precondition_valid_tempo");
    const MSRhythmFrame saved=f;
    // No call => no output mutation. No UI/timer API exists.
    check(std::memcmp(&f,&saved,sizeof(f))==0,"no_call_no_update");
    std::vector<float> z(N/2,0);
    bool r=MSRhythmAnalyzerProcess(q.a,z.data(),z.size(),1,++q.sequence,q.time+.016,FS,0,0,&f);
    check(r&&empty(f)&&(f.flags&MSRhythmFlagSilence),"silence_invalidates_no_free_beat");
    q.step(f);check(empty(f),"silence_removes_old_tempo");
    while(q.time<90)q.step(f);
    check((f.flags&MSRhythmFlagValid)!=0,"epoch_precondition_valid_tempo");
    r=MSRhythmAnalyzerProcess(q.a,q.mag.data(),q.mag.size(),2,1,q.time+.016,FS,q.rms,q.peak,&f);
    check(r&&empty(f)&&(f.flags&MSRhythmFlagDiscontinuity),"epoch_switch_resets");
    // Each bad case starts with a populated analyzer/stream watermark.
    auto reject=[&](const char *name,const float *p,size_t n,uint64_t seq,double t,double rate,double rms,double peak) {
        bool accepted=MSRhythmAnalyzerProcess(q.a,p,n,2,seq,t,rate,rms,peak,&f);
        check(!accepted&&empty(f)&&(f.flags&MSRhythmFlagDiscontinuity),name);
    };
    const double t=q.time+.032;
    reject("bad_64_count",q.mag.data(),64,2,t,FS,q.rms,q.peak);
    reject("bad_count_not_multiple",q.mag.data(),129,2,t,FS,q.rms,q.peak);
    reject("overflow_count",q.mag.data(),std::numeric_limits<size_t>::max(),2,t,FS,q.rms,q.peak);
    reject("zero_count",q.mag.data(),0,2,t,FS,q.rms,q.peak);
    reject("null_magnitudes",NULL,N/2,2,t,FS,q.rms,q.peak);
    float v=q.mag[7];q.mag[7]=std::numeric_limits<float>::quiet_NaN();
    reject("nan_bin",q.mag.data(),q.mag.size(),2,t,FS,q.rms,q.peak);
    q.mag[7]=std::numeric_limits<float>::infinity();
    reject("infinite_bin",q.mag.data(),q.mag.size(),2,t,FS,q.rms,q.peak);
    q.mag[7]=std::numeric_limits<float>::max();
    reject("magnitude_overflow",q.mag.data(),q.mag.size(),2,t,FS,q.rms,q.peak);
    q.mag[7]=-1;reject("negative_bin",q.mag.data(),q.mag.size(),2,t,FS,q.rms,q.peak);q.mag[7]=v;
    reject("nan_time",q.mag.data(),q.mag.size(),2,std::numeric_limits<double>::quiet_NaN(),FS,q.rms,q.peak);
    reject("infinite_rate",q.mag.data(),q.mag.size(),2,t,std::numeric_limits<double>::infinity(),q.rms,q.peak);
    reject("unreasonable_rate",q.mag.data(),q.mag.size(),2,t,100,q.rms,q.peak);
    reject("inconsistent_rms_peak",q.mag.data(),q.mag.size(),2,t,FS,.5,.1);
    reject("nonfinite_rms",q.mag.data(),q.mag.size(),2,t,FS,std::numeric_limits<double>::quiet_NaN(),q.peak);
    reject("stale_sequence",q.mag.data(),q.mag.size(),1,t,FS,q.rms,q.peak);
    reject("reverse_time",q.mag.data(),q.mag.size(),2,q.time,FS,q.rms,q.peak);
    r=MSRhythmAnalyzerProcess(q.a,q.mag.data(),q.mag.size(),2,2,t+1,FS,q.rms,q.peak,&f);
    check(r&&empty(f)&&(f.flags&MSRhythmFlagDiscontinuity),"gap_resets");
    r=MSRhythmAnalyzerProcess(q.a,q.mag.data(),q.mag.size(),2,3,t+1.016,44100,q.rms,q.peak,&f);
    check(r&&empty(f)&&(f.flags&MSRhythmFlagDiscontinuity),"rate_change_resets");
    std::vector<float> small(128,.01);
    r=MSRhythmAnalyzerProcess(q.a,small.data(),small.size(),2,4,t+1.032,44100,.01,.02,&f);
    check(r&&empty(f)&&(f.flags&MSRhythmFlagDiscontinuity),"count_change_resets");
    MSRhythmAnalyzerReset(q.a);
    r=MSRhythmAnalyzerProcess(q.a,q.mag.data(),q.mag.size(),2,1,0,FS,q.rms,q.peak,&f);
    check(r&&empty(f)&&(f.flags&MSRhythmFlagDiscontinuity),"explicit_stop_reset");
    MSRhythmAnalyzerReset(NULL);MSRhythmAnalyzerDestroy(NULL);
    r=MSRhythmAnalyzerProcess(NULL,q.mag.data(),q.mag.size(),1,1,0,FS,q.rms,q.peak,&f);
    check(!r&&empty(f)&&(f.flags&MSRhythmFlagDiscontinuity),"null_analyzer");
    check(!MSRhythmAnalyzerProcess(q.a,q.mag.data(),q.mag.size(),2,2,.016,FS,q.rms,q.peak,NULL),"null_output");
}
int main(int argc,char **argv) {
    std::setvbuf(stdout,NULL,_IONBF,0);
    if(argc>2&&std::string(argv[1])=="--trace-120") {
        traceFile=std::fopen(argv[2],"w"); if(!traceFile)return 2;
        scenario("pulse",120,true); std::fclose(traceFile);
    } else if(argc>2&&std::string(argv[1])=="--pulse")scenario("pulse",std::atof(argv[2]),true);
    else if(argc>1&&std::string(argv[1])=="--guards")guards();
    else {
        scenario("pulse",90,true);scenario("pulse",120,true);scenario("pulse",150,true);
        scenario("tone",0,true);scenario("noise",0,true);scenario("silence",0,true);
        scenario("barepulse",120,false);guards();
    }
    std::printf("{\"test_failures\":%d}\n",failures);
    return failures?1:0;
}
