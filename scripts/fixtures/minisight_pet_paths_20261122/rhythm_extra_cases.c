static void RhythmExtra(void) {
 Case="explicit-opt-in-default-invalid-no-grid-is-quiet";
 Fresh(false,false);RhythmSeq=0;RhythmEpoch=3;P_setRhythmFollowing(true);P_setMusicPlaying(true);
 CGPoint center=P.center;
 for(unsigned i=0;i<500;i++) {
  Tick(.02,"default-invalid-no-grid");
  MSRhythmFrame f={0};
  if(i&1u) {f.epoch=3;f.sequence=++RhythmSeq;f.sampleTime=700.+Now;f.flags=MSRhythmFlagValid;f.rms=.1;f.peak=.3;}
  P_applyRhythmFrame(f,Now);
  CHECK(!P.musicMotion); // ordinary roam is intentionally independent of absent/invalid input
 }
 CHECK(fabs(E.angle.value)<.0001&&fabs(E.offsetY.value)<.0001);
 puts("RHYTHM PASS: actual Pet/Effects explicit mode + default/invalid/no-grid 500 frames quiet");
 Case="opaque-epoch-server-restarts-low-and-retired-replay";
 RhythmFresh();Tick(.02,"epoch-100");SendMeasured(.5,.3,.8,3);CHECK(P.motionActive);
 P_clearRhythm();RhythmEpoch=1;RhythmSeq=0;Tick(.02,"new-server-low-epoch");
 SendMeasured(.5,.012,.025,1);CHECK(!P.motionActive&&P.rhythmPolicy.epoch==1);
 Tick(.02,"new-server-next-estimated-beat");SendMeasured(.5,.3,.8,3);CHECK(P.motionActive);
 MSRhythmFrame replay=Measured(.5,.3,.8,3);replay.epoch=100;replay.sequence=999;
 Tick(.02,"retired-epoch-replay");P_applyRhythmFrame(replay,Now);CHECK(!P.motionActive&&P.rhythmPolicy.epoch==1);
 P_resetRhythmForSession(0);CHECK(P.rhythmPolicy.seen);
 P_resetRhythmForSession(88);CHECK(!P.rhythmPolicy.seen&&!P.motionActive);
 RhythmEpoch=100;RhythmSeq=0;Tick(.02,"fenced-owner-epoch-reuse");SendMeasured(.5,.012,.025,1);
 uint64_t seq=P.rhythmPolicy.sequence;P_resetRhythmForSession(88);CHECK(P.rhythmPolicy.sequence==seq);
 Tick(.02,"fenced-owner-fresh-beat");SendMeasured(.5,.3,.8,3);CHECK(P.motionActive);
 puts("RHYTHM PASS: opaque epoch 100 -> new server 1 recovers, retired 100 rejected, fenced new-owner permits reuse");
 Case="measured-strength-phase-presentation-no-free-running-oscillator";
 double bob[2],angle[2];
 for(unsigned energy=0;energy<2;energy++) {
  RhythmFresh();P_setSpriteState(8);center=P.center;
  for(unsigned i=0;i<10;i++) {Now+=.01;E_applyRhythmStrength(energy?.8:.15,.8);E_tick(E.link);}
  bob[energy]=fabs(E.offsetY.value);angle[energy]=fabs(E.angle.value);
  CHECK(hypot(P.center.x-center.x,P.center.y-center.y)<.0001);
  for(unsigned i=0;i<100;i++){Now+=.02;E_tick(E.link);}
  CHECK(fabs(E.offsetY.value)<.00001&&fabs(E.angle.value)<.00001);
 }
 CHECK(bob[1]>bob[0]*4.&&angle[1]>.001);
 Case="independent-daily-and-signed-measured-music-roles";
 RhythmFresh();P_clearRhythm();P_setSpriteState(8);center=P.center;
 CHECK(FixtureRole(E_currentRole(),"idle")); // No input is not a claimed beat.
 MSPetRhythmPolicy phasePolicy={0};
 for(unsigned side=0;side<3;side++) {
  bool left=side==1;
  for(unsigned i=0;i<30;i++) {
   Now+=.01;MSRhythmFrame frame=Measured(.5,.3,.8,MSRhythmFlagValid);
   frame.phase=left?.5:0.;
   MSPetRhythmAction sample=MSPetRhythmConsume(&phasePolicy,frame,Now,Now,
      P_feasibleCenters(),P.center,false);
   CHECK(sample.accepted&&!sample.valid&&!sample.beat);
   CHECK(left?sample.pulse<-.2:sample.pulse>.2);
   E_applyRhythmStrength(sample.strength,sample.pulse);E_tick(E.link);
  }
  CHECK(left?E.angle.value<-.02:E.angle.value>.02);
  CHECK(FixtureRole(E_currentRole(),"music"));
  CHECK(hypot(P.center.x-center.x,P.center.y-center.y)<.0001);
 }
 for(unsigned i=0;i<100;i++){Now+=.02;E_tick(E.link);}
 CHECK(FixtureRole(E_currentRole(),"idle")&&fabs(E.angle.value)<.00001);
 P_setMusicPlaying(false);P_setSpriteState(0);CHECK(FixtureRole(E_currentRole(),"idle")&&P.dailyActionsEnabled);
 printf("RHYTHM PASS: measured sprite-only spring bob %.5f -> %.5f, signed producer phase left/right, distinct music/ordinary roles, no center/hit geometry write, settles without fresh input\n",bob[0],bob[1]);
}
