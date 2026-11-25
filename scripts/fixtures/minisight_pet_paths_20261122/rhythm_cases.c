/* Host fixture inputs only, never a production beat generator. */
static uint64_t RhythmSeq, RhythmEpoch;
static MSRhythmFrame Measured(double period,double rms,double peak,unsigned flags) {
 MSRhythmFrame f={RhythmEpoch,++RhythmSeq,500.+Now-100.,period,.02,.92,rms,peak,flags};return f;
}
static void SendMeasured(double period,double rms,double peak,unsigned flags) {
 P_applyRhythmFrame(Measured(period,rms,peak,flags),Now);
}
static void RhythmFresh(void) {
 Fresh(false,false);RhythmSeq=0;RhythmEpoch=100;
 P_setRhythmFollowing(true);P_setMusicPlaying(true);
 CHECK(P.rhythmFollowing&&E.rhythmFollowing&&P.roamTimer&&!P.motionActive);
 SendMeasured(.5,.012,.025,MSRhythmFlagValid);
}
static void ContinueInput(double seconds) {
 unsigned n=(unsigned)ceil(seconds/.02);
 for(unsigned i=0;i<n;i++) {Tick(.02,"rhythm-real-input");SendMeasured(.5,.012,.025,MSRhythmFlagValid);}
}
static void RhythmPolicyRejects(void) {
 Case="production-pure-C-rejects-and-clock-anchors";
 MSRect bounds={42,47,276,686};MSPoint center={180,300};
 for(unsigned kind=0;kind<15;kind++) {
  MSPetRhythmPolicy s={0};MSRhythmFrame f={7,1,9000.,.5,.02,.93,.015,.03,MSRhythmFlagValid};
  CHECK(MSPetRhythmConsume(&s,f,100.,100.,bounds,center,true).accepted);
  f.sequence=2;f.sampleTime+=.02;f.rms=.25;f.peak=.8;f.flags|=MSRhythmFlagBeat;
  double receipt=100.02,now=100.02;
  switch(kind) {
   case 0:f.period=NAN;break;case 1:f.rms=NAN;break;case 2:f.flags|=128;break;
   case 3:f.confidence=.3;break;case 4:f.period=.1;break;case 5:f.sampleTime=8999.;break;
   case 6:f.phase=1.;break;case 7:f.flags|=MSRhythmFlagSilence;break;
   case 8:receipt=99.;break;case 9:receipt=100.03;break;case 10:f.sequence=1;break;
   case 11:f.epoch=6;s.retiredEpochs[0]=6;s.retiredCount=1;break;case 12:f.flags|=MSRhythmFlagDiscontinuity;break;
   case 13:f.peak=1.1;break;case 14:now=receipt=99.99;break;
  }
  MSPetRhythmAction a=MSPetRhythmConsume(&s,f,receipt,now,bounds,center,true);
  CHECK(!a.valid&&!a.accepted&&!MSPetRhythmFresh(&s,now));
 }
 MSPetRhythmPolicy s={0};MSRhythmFrame f={8,1,7000.,.5,.02,.92,.01,.02,MSRhythmFlagValid|MSRhythmFlagBeat};
 CHECK(!MSPetRhythmConsume(&s,f,100.,100.,bounds,center,true).valid); // unrelated clock origin
 f.sequence++;f.sampleTime+=.02;f.rms=.3;f.peak=.85;
 CHECK(MSPetRhythmConsume(&s,f,100.02,100.02,bounds,center,true).valid);
 MSPetRhythmClear(&s);CHECK(!MSPetRhythmConsume(&s,f,100.02,100.02,bounds,center,true).valid);
 f.epoch++;f.sequence=1;f.sampleTime=0.;
 CHECK(!MSPetRhythmConsume(&s,f,100.04,100.04,bounds,center,true).valid);
 puts("RHYTHM PASS: 15 invalid/NaN/flags/clock/epoch/sequence cases; first event anchors, no replay");
}
typedef struct {double distance,duration,height;} RhythmMetric;
static RhythmMetric RhythmImpulse(double period,double rms,double peak,bool hop) {
 Case=hop?"rhythm-measured-strong-hop":"rhythm-measured-soft-walk";
 RhythmFresh();Tick(.02,"rhythm-anchor");
 SendMeasured(period,rms,peak,MSRhythmFlagValid|MSRhythmFlagBeat);
 CHECK(P.motionActive&&P.musicMotion&&!P.physicsMotion&&!P.roamTimer);
 CHECK((P.jumpHeight>0.)==hop);CGPoint start=P.center;
 RhythmMetric m={hypot(P.motionEnd.x-start.x,P.motionEnd.y-start.y),P.motionDuration,P.jumpHeight};
 ContinueInput(m.duration*.5);CHECK(hypot(P.center.x-start.x,P.center.y-start.y)>1.);
 ContinueInput(m.duration+.1);CHECK(!P.motionActive&&!P.roamTimer);
 CHECK(fabs(hypot(P.center.x-start.x,P.center.y-start.y)-m.distance)<.1);
 printf("RHYTHM METRIC: period %.3f rms %.3f peak %.3f target %.3f duration %.3f hop %.3f center-net %.3f\n",period,rms,peak,m.distance,m.duration,m.height,hypot(P.center.x-start.x,P.center.y-start.y));
 return m;
}
static void RhythmQuietAndStale(void) {
 Case="rhythm-no-input-no-cyclic-travel";RhythmFresh();CGPoint start=P.center;
 for(int i=0;i<240;i++)Tick(.02,"rhythm-no-input");
 CHECK(!P.musicMotion&&P.roamTimer); // ordinary life is now allowed; never a synthetic beat
 for(unsigned mode=0;mode<3;mode++) for(int i=0;i<150;i++) {
  Tick(.02,"rhythm-untrusted-tone-silence");
  MSRhythmFrame f=Measured(.5,mode==1?0.:.1,mode==1?0.:.3,MSRhythmFlagValid|MSRhythmFlagBeat);
  if(mode==0)f.confidence=.15;if(mode==1)f.flags|=MSRhythmFlagSilence;if(mode==2)f.flags=0;
  P_applyRhythmFrame(f,Now);CHECK(!P.musicMotion);
 }
 RhythmImpulse(.8,.25,.8,true); // start a separate route, then test stale callback
 RhythmFresh();Tick(.02,"stale-before-hop");SendMeasured(.8,.3,.8,3);
 Tick(.12,"stale-moving");start=P.center;int old=P.motionLink;
 for(int i=0;i<40;i++)Tick(.02,"stale-cancel");
 CHECK(!P.musicMotion&&P.roamTimer);CGPoint stopped=P.center;P_motionTick(old);
 CHECK(hypot(P.center.x-stopped.x,P.center.y-stopped.y)<.001);
 CHECK(hypot(P.center.x-start.x,P.center.y-start.y)<60.);
 MSRhythmFrame late=Measured(.5,.3,.8,3);P_applyRhythmFrame(late,Now-.3);CHECK(!P.motionActive);
 SendMeasured(.5,.3,.8,3);CHECK(!P.motionActive); // anchor, not remembered beat
 Tick(.02,"stale-reanchor");SendMeasured(.5,.03,.06,3);CHECK(P.motionActive);
 P_clearRhythm();CHECK(!P.motionActive&&!P.musicMotion);
 puts("RHYTHM PASS: silence/tone/unknown/no input quiet; stale route freezes current center, stale tick rejected");
}
static void RhythmGates(void) {
 for(unsigned gate=0;gate<12;gate++) {
  Case="rhythm-owner-gates-need-next-new-beat";RhythmFresh();Tick(.02,"gate-start");SendMeasured(.8,.3,.8,3);
  CHECK(P.motionActive);Tick(.10,"gate-mid-route");CGPoint before=P.center;
  switch(gate) {
   case 0:P_setRoamPace(0);break;case 1:P_setLyricsSuppressed(true);break;
   case 2:P_setActivityActive(true);break;case 3:Chat=true;break;
   case 4:Reduce=true;break;case 5:P_setMotionLocked(true,1);break;
   case 6:P_setRoamingPaused(true);break;case 7:P_setInteractionActive(true);break;
   case 8:P.hidden=true;break;case 9:P_setSuspended(true);break;
   case 10:P_stopPlaying();break;case 11:P_setCenterBounds(CGRectMake(43,48,270,680));break;
  }
  P_reconcilePlaybackOnce();Tick(.02,"gate-cancel");CHECK(!P.motionActive&&!P.musicMotion);
  CHECK(hypot(P.center.x-before.x,P.center.y-before.y)<.001);
  SendMeasured(.8,.3,.8,3);CHECK(!P.motionActive);
  P_setRoamPace(1);P_setLyricsSuppressed(false);P_setActivityActive(false);Chat=Reduce=false;
  P_setMotionLocked(false,1);P_setRoamingPaused(false);P_setInteractionActive(false);P.hidden=false;
  P_setSuspended(false);P_startPlaying();P_reconcilePlaybackOnce();
  ContinueInput(.04);CHECK(!P.motionActive&&!P.roamTimer);
  Tick(.8,"gate-no-remembered-beat");CHECK(!P.motionActive);
  SendMeasured(.5,.012,.025,1);Tick(.02,"gate-reanchor");SendMeasured(.5,.03,.06,3);
  if(!P.motionActive){Tick(.02,"gate-next-fresh-beat");SendMeasured(.5,.04,.08,3);}
  CHECK(P.motionActive&&P.musicMotion);
 }
 puts("RHYTHM PASS: 12 ownership/geometry/accessibility/visibility gates, no queued late beat");
}
static void RhythmManualLoop(void) {
 for(unsigned hop=0;hop<2;hop++) {
  Case="rhythm-route-to-manual-fling-landing-fresh-beat-resume";RhythmFresh();Tick(.02,"manual-anchor");
  SendMeasured(.5,hop?.3:.03,hop?.8:.06,3);CHECK(P.motionActive&&(P.jumpHeight>0.)==(hop!=0));
  Tick(.08,"manual-pre-drag");DragThrow(1450.);CHECK(P.physicsMotion&&!P.musicMotion&&!P.rhythmStarting);
  unsigned generation=P.motionGeneration;P_clearRhythm();P_setRhythmFollowing(false);P_setRhythmFollowing(true);
  P_setMusicPlaying(false);P_setMusicPlaying(true);
  CHECK(P.physicsMotion&&P.motionGeneration==generation);
  double travelled=0.;CGPoint previous=P.center;unsigned limit=0;
  while(P.motionActive&&limit++<500) {
   Tick(.02,"rhythm-manual-flight");SendMeasured(.5,.3,.8,3);
   travelled+=hypot(P.center.x-previous.x,P.center.y-previous.y);previous=P.center;
  }
  CHECK(limit<500&&travelled>50.);CHECK(!P.physicsMotion);
  ContinueInput(4.);CHECK(!P.motionActive&&!P.musicMotion);
  Tick(.02,"manual-resume-fresh-beat");SendMeasured(.5,.03,.06,3);
  CHECK(P.motionActive&&P.musicMotion&&!P.physicsMotion);
  P_clearRhythm();CHECK(!P.motionActive);
  printf("RHYTHM PASS: %s -> drag -> manual flight %.2f -> landing -> fresh beat resumes\n",hop?"hop":"walk",travelled);
 }
}
static void RhythmSuite(void) {
 RhythmPolicyRejects();
 RhythmMetric slow=RhythmImpulse(.8,.03,.06,false),fast=RhythmImpulse(.3,.03,.06,false);
 RhythmMetric soft=RhythmImpulse(.5,.03,.06,false),hard=RhythmImpulse(.5,.3,.8,true);
 CHECK(slow.duration>fast.duration&&fast.distance>slow.distance);
 CHECK(hard.distance>soft.distance&&hard.height>soft.height);
 RhythmQuietAndStale();RhythmGates();RhythmManualLoop();
 puts("RHYTHM SUITE PASS: production policy + actual Pet/Effects extracted bodies, legacy cases retained");
}
