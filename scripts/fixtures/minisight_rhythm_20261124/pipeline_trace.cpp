// Offline integration only. Replays REAL producer frames captured from local
// synthesized PCM/FFT test, through actual service encoder, wire decoder,
// receiver clock guard and pet production policy. No sockets/real sound/UIKit.
#include "FeaturePayload.h"
#include "MiniSightRhythmReceivePolicy.h"
#include "MiniSightPetRhythmPolicy.h"
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <cmath>
struct FeatureFrame { uint64_t streamEpoch;uint32_t status;float sampleRate,rms,peak;float waveform[64],spectrum[64];MSRhythmFrame rhythm; };
int main(int argc,char**argv){
 if(argc<2)return 2;FILE*fp=std::fopen(argv[1],"r");if(!fp)return 2;
 char line[1024];unsigned frames=0,beats=0,accepted=0,walk=0,hop=0,resets=0;
 MSRhythmReceiveState receiver={};MSPetRhythmPolicy policy={};MSRect bounds={0,0,300,600};MSPoint center={150,300};double until=0,total=0;uint64_t packetSeq=0;
 while(std::fgets(line,sizeof(line),fp)){
  unsigned long long epoch=0,sequence=0;MSRhythmFrame f={};double rate=0,now=0;unsigned flags=0;
  int n=std::sscanf(line,"{\"epoch\":%llu,\"sequence\":%llu,\"sampleTime\":%lf,\"period\":%lf,\"phase\":%lf,\"confidence\":%lf,\"rms\":%lf,\"peak\":%lf,\"flags\":%u,\"rate\":%lf,\"now\":%lf}",&epoch,&sequence,&f.sampleTime,&f.period,&f.phase,&f.confidence,&f.rms,&f.peak,&flags,&rate,&now);
  if(n!=11){std::fprintf(stderr,"FAIL trace parsing\n");return 1;}f.epoch=epoch;f.sequence=sequence;f.flags=flags;++frames;if(flags&MSRhythmFlagBeat)++beats;
  FeatureFrame raw={};raw.streamEpoch=919;raw.status=16;raw.sampleRate=rate;raw.rms=.0001f;raw.peak=.0002f;raw.rhythm=f;
  uint8_t packet[128]={};MSHFServer::EncodeFeaturePayload(packet+32,4,raw);MSHFEncodeHeader(packet,3,96,7,9,++packetSeq);
  MSRhythmFrame decoded={};MSRhythmEnvelope envelope={};
  if(!MSRhythmDecodePacket(packet,sizeof(packet),7,&envelope,&decoded)){std::fprintf(stderr,"FAIL real producer frame rejected at wire,seq%llu flags%u\n",sequence,flags);return 1;}
  int decision=MSRhythmReceive(&receiver,&envelope,&decoded,now);
  if(decision==MSRhythmReceiveReject){std::fprintf(stderr,"FAIL good trace rejected receiver\n");return 1;}
  if(decision==MSRhythmReceiveReset){MSPetRhythmClear(&policy);++resets;continue;}
  MSPetRhythmAction action=MSPetRhythmConsume(&policy,decoded,now,now,bounds,center,now>=until);
  if(action.accepted)++accepted;
  if(action.valid){double distance=std::hypot(action.target.x-center.x,action.target.y-center.y);total+=distance;center=action.target;until=now+action.duration;if(action.jump)++hop;else ++walk;}
 }
 std::fclose(fp);std::printf("PIPELINE actual PCM/FFT/analyzer trace: frames=%u beats=%u policyAccepted=%u resets=%u walks=%u hops=%u targetPath=%.3f\n",frames,beats,accepted,resets,walk,hop,total);
 if(!frames||beats<3||accepted<frames/2||walk<2||hop<1||total<10){std::fprintf(stderr,"FAIL complete pipeline no adequate measured-input actions\n");return 1;}
 return 0;
}
