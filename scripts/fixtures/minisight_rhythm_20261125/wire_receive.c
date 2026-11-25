#include "MiniSightRhythmReceivePolicy.h"
#include <stdio.h>
#include <stdlib.h>
static unsigned checks;
#define CHECK(c) do{++checks;if(!(c)){fprintf(stderr,"FAIL wire/policy line%d: %s\n",__LINE__,#c);return 1;}}while(0)
static void wf(uint8_t*p,float x){uint32_t u;memcpy(&u,&x,4);MSRWrite32(p,u);}
static void packet(uint8_t*p,const MSRhythmFrame*f){
 memset(p,0,MS_RHYTHM_PACKET_BYTES);memcpy(p,"MSH2",4);MSRWrite16(p+4,3);MSRWrite16(p+6,96);
 MSRWrite64(p+8,7);MSRWrite64(p+16,9);MSRWrite64(p+24,10);p+=32;
 MSRWrite64(p,f->epoch);MSRWrite32(p+8,4);MSRWrite32(p+12,16);wf(p+16,48000);wf(p+20,(float)f->rms);wf(p+24,(float)f->peak);MSRhythmEncodeFrame(p+28,f);
}
int main(void){
 uint8_t p[1025],bad[1025],request[40];MSRhythmFrame f={3,11,1,.5,.2,.9,.1,.8,MSRhythmFlagValid|MSRhythmFlagBeat};
 MSRhythmFrame out={0};MSRhythmEnvelope e={0};packet(p,&f);
 CHECK(MSRRead64((uint8_t[]){1,2,3,4,5,6,7,8})==UINT64_C(0x0807060504030201));
 CHECK(MSRhythmDecodePacket(p,MS_RHYTHM_PACKET_BYTES,7,&e,&out));CHECK(out.period==.5&&out.sequence==11&&e.server==9&&out.flags&MSRhythmFlagBeat);
 for(size_t n=0;n<1025;++n){if(n==MS_RHYTHM_PACKET_BYTES)continue;CHECK(!MSRhythmDecodePacket(p,n,7,&e,&out));}
 CHECK(!MSRhythmDecodePacket(NULL,MS_RHYTHM_PACKET_BYTES,7,&e,&out));CHECK(!MSRhythmDecodePacket(p,128,8,&e,&out));
 const size_t offsets[]={0,4,6,8,16,24,32,40,51};
 for(unsigned i=0;i<sizeof(offsets)/sizeof(offsets[0]);++i){memcpy(bad,p,128);bad[offsets[i]]=0;CHECK(!MSRhythmDecodePacket(bad,128,7,&e,&out));}
 memcpy(bad,p,128);wf(bad+48,NAN);CHECK(!MSRhythmDecodePacket(bad,128,7,&e,&out));
 for(unsigned k=0;k<6;++k){MSRhythmFrame wrong=f;switch(k){case 0:wrong.period=NAN;break;case 1:wrong.phase=1;break;case 2:wrong.confidence=2;break;case 3:wrong.flags|=MSRhythmFlagSilence;break;case 4:wrong.rms=2;break;case 5:wrong.flags=1024;break;}packet(bad,&wrong);CHECK(!MSRhythmDecodePacket(bad,128,7,&e,&out));}
 CHECK(MSRhythmRequest(request,40,true,7,0,1)==40);CHECK(!memcmp(request,"MSH2",4)&&MSRRead16(request+4)==1&&MSRRead32(request+32)==4&&MSRRead16(request+36)==60);
 CHECK(MSRhythmRequest(request,32,false,7,9,2)==32&&MSRRead16(request+4)==2&&MSRRead16(request+6)==0);CHECK(MSRhythmRequest(request,31,true,7,0,1)==0);
 MSRhythmReceiveState state={0};e.session=7;e.server=9;e.sequence=10;
 CHECK(MSRhythmReceive(&state,&e,&f,100)==MSRhythmReceiveReset);CHECK(MSRhythmReceive(&state,&e,&f,100)==MSRhythmReceiveReject);
 e.sequence++;f.sequence++;f.sampleTime+=.016;CHECK(MSRhythmReceive(&state,&e,&f,100.016)==MSRhythmReceiveUpdate);
 CHECK(MSRhythmReceiveFresh(&state,100.1));CHECK(!MSRhythmReceiveFresh(&state,100.5));CHECK(!MSRhythmReceiveFresh(&state,99));
 MSRhythmReceiveState copy=state;e.sequence--;f.sequence++;f.sampleTime+=.016;CHECK(MSRhythmReceive(&state,&e,&f,100.032)==MSRhythmReceiveReject);CHECK(!memcmp(&copy,&state,sizeof(state)));e.sequence+=2;f.sequence++;
 f.sampleTime+=1;CHECK(MSRhythmReceive(&state,&e,&f,100.03)==MSRhythmReceiveReset);
 e.sequence++;f.sequence++;f.sampleTime+=.016;CHECK(MSRhythmReceive(&state,&e,&f,100.046)==MSRhythmReceiveUpdate);
 e.sequence++;f.sequence++;f.epoch++;CHECK(MSRhythmReceive(&state,&e,&f,100.062)==MSRhythmReceiveReset);
 e.sequence++;f.sequence++;f.sampleTime+=.016;f.flags=MSRhythmFlagDiscontinuity;f.period=f.phase=f.confidence=0;CHECK(MSRhythmReceive(&state,&e,&f,100.078)==MSRhythmReceiveReset);
 e.server++;e.sequence=1;f.sequence=1;CHECK(MSRhythmReceive(&state,&e,&f,100.08)==MSRhythmReceiveReset);
 MSRhythmReceiveState newServer=state;e.server--;e.sequence=999;f.sequence=999;CHECK(MSRhythmReceive(&state,&e,&f,100.09)==MSRhythmReceiveReject);CHECK(!memcmp(&state,&newServer,sizeof(state)));
 MSRhythmReceiveResetState(&state);CHECK(!MSRhythmReceiveFresh(&state,100));
 printf("PASS rhythm wire/freshness: %u checks; no socket/capture/UI executed\n",checks);return 0;
}
