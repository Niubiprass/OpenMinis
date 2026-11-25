static void DailyFallbackSuite(void) {
 Case="daily-safe-atlas-without-package-independent-roam-and-owner-scoped-off";
 for(unsigned action=0;action<3;++action){
  Fresh(false,false);P.spriteLayout=3;P.roamPace=0.;P.roamingPaused=true;
  P.dailyActionDue=Now-1.;RandomRoll=action;CGPoint old=P.center;
  P_tryDailyActionAt(Now);CHECK(P.dailyFallback!=MSPetDailyNone&&P.dailyActionHoldUntil>Now&&!P.motionActive&&!P.roamTimer);
  for(unsigned j=0;j<12;++j){Now+=.05;P_advanceSpriteAtTime(Now);CHECK(P.column>=0&&P.column<(P.state==3?4:6));CHECK(P.center.x==old.x&&P.center.y==old.y);CHECK(S.transform.a==1&&S.transform.d==1);}
  P_setDailyActionsEnabled(false);CHECK(!P.dailyFallback&&P.dailyActionDue==0&&P.dailyActionHoldUntil==0&&P.state==0);
  P_tryDailyActionAt(Now+100);CHECK(!P.dailyFallback&&P.dailyActionDue==0);
 }
 Fresh(false,false);P.spriteLayout=1;P.dailyActionDue=Now-1.;P_tryDailyActionAt(Now);CHECK(!P.dailyFallback&&P.dailyActionHoldUntil==0); // genuine poster: no fabricated poses
 Fresh(false,false);P.spriteLayout=3;P.dailyActionDue=Now-1.;P_tryDailyActionAt(Now);
 P.stateHoldUntil=Now+3;P.state=3;P_setDailyActionsEnabled(false);CHECK(P.state==3&&P.stateHoldUntil==Now+3); // manual attention wave survives
 Fresh(false,false);P.spriteLayout=3;P.dailyActionDue=Now-1.;P_tryDailyActionAt(Now);
 P_beginDraggingAtPoint((CGPoint){20,20});CHECK(!P.dailyFallback&&P.dragging);P_setDailyActionsEnabled(false);CHECK(P.dragging&&E.dragging);
 Fresh(false,false);E.dailyActionOwned=true;E.role="tap";E.transientRole="tap";E.transientUntil=Now+2;unsigned req=E.frameRequest;
 E_cancelDailyAction();CHECK(FixtureRole(E.role,"tap")&&E.transientUntil==Now+2&&E.frameRequest==req);
 puts("DAILY FALLBACK PASS: no package layout3/verified 0+3 rows, no movement/squash, OFF, static art, manual wave/drag ownership");
}
