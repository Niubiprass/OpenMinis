// One synthetic offline FFT shape smoke, no audio I/O. The behavioral tests
// for tempo/quality belong to the analyzer's independent test suite.
#include "MiniSightRhythmAnalyzer.h"
#include "MiniSightRhythmWire.h"
#include <cassert>
#include <cmath>
#include <complex>
#include <cstdio>
#include <vector>
int main(){
 const unsigned N=2048,half=N/2;const double pi=3.141592653589793;
 std::vector<std::complex<double>> x(N);std::vector<float> mag(half);
 double sum=0,peak=0;
 for(unsigned i=0;i<N;++i){double s=.3*std::sin(2*pi*1500*i/48000)+.1*std::sin(2*pi*3000*i/48000);sum+=s*s;peak=std::fmax(peak,std::fabs(s));x[i]=s*(.5-.5*std::cos(2*pi*i/N));}
 for(unsigned i=1,j=0;i<N;++i){unsigned b=N>>1;for(;j&b;b>>=1)j^=b;j^=b;if(i<j)std::swap(x[i],x[j]);}
 for(unsigned len=2;len<=N;len<<=1){auto wlen=std::polar(1.,-2*pi/len);for(unsigned i=0;i<N;i+=len){std::complex<double>w(1);for(unsigned j=0;j<len/2;++j){auto u=x[i+j],v=x[i+j+len/2]*w;x[i+j]=u+v;x[i+j+len/2]=u-v;w*=wlen;}}}
 for(unsigned i=0;i<half;++i)mag[i]=float(std::abs(x[i])/N);
 MSRhythmAnalyzer*a=MSRhythmAnalyzerCreate();assert(a);MSRhythmFrame f;
 for(unsigned seq=1;seq<=40;++seq){bool ok=MSRhythmAnalyzerProcess(a,mag.data(),mag.size(),1,seq,double(N)/48000+(seq-1)/60.,48000,std::sqrt(sum/N),peak,&f);assert(ok);assert(MSRhythmFrameSane(&f));assert(!(f.flags&MSRhythmFlagBeat));}
 // No padded 64 bands: exact raw1024-bin shape is accepted,1025 is rejected.
 mag.push_back(0);assert(!MSRhythmAnalyzerProcess(a,mag.data(),mag.size(),1,41,.8,48000,std::sqrt(sum/N),peak,&f));assert(f.flags&MSRhythmFlagDiscontinuity);
 MSRhythmAnalyzerDestroy(a);puts("Synthetic2048-point FFT -> genuine1024 bins -> real wrapper/BeatDetektor PASS (tone remains no Beat)");
}
