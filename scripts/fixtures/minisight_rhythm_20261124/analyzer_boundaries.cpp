// Production wrapper boundaries only; no guessed tempo or audio playback.
#include "MiniSightRhythmAnalyzer.h"
#include <cstdio>
#include <cmath>
#define CHECK(c) do{if(!(c)){std::fprintf(stderr,"FAIL analyzer boundary line%d: %s\n",__LINE__,#c);return 1;}}while(0)
static bool invalid(const MSRhythmFrame &f){return !(f.flags&(MSRhythmFlagValid|MSRhythmFlagBeat))&&f.period==0&&f.phase==0&&f.confidence==0;}
int main(){
 MSRhythmAnalyzer*a=MSRhythmAnalyzerCreate();CHECK(a);float bins[128];for(float &x:bins)x=.01f;MSRhythmFrame f={};
 CHECK(MSRhythmAnalyzerProcess(a,bins,128,1,1,.1,48000,.01,.02,&f));CHECK(invalid(f));
 CHECK(!MSRhythmAnalyzerProcess(a,bins,128,1,1,.12,48000,.01,.02,&f));CHECK(invalid(f));
 CHECK(!MSRhythmAnalyzerProcess(a,bins,128,0,2,.14,48000,.01,.02,&f));CHECK(invalid(f));
 CHECK(!MSRhythmAnalyzerProcess(a,bins,128,1,0,.14,48000,.01,.02,&f));CHECK(invalid(f));
 CHECK(!MSRhythmAnalyzerProcess(a,bins,64,1,2,.14,48000,.01,.02,&f));CHECK(invalid(f));
 for(float &x:bins)x=0;
 CHECK(MSRhythmAnalyzerProcess(a,bins,128,1,2,.14,48000,0,0,&f));CHECK(invalid(f)&&(f.flags&MSRhythmFlagSilence));
 MSRhythmAnalyzerDestroy(a);std::puts("PASS analyzer input/identity/silence boundaries; no FFT/musical accuracy claim");return 0;
}
