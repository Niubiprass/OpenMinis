/* Host C dependency surface; production control flow lives in production-paths.h.
 * No UIKit/ObjC ABI is compiled here. Drawing records the actual production star
 * vertices and affine commands; ActionLibrary delivery and timer scheduling are
 * explicitly mocked. All 40 current method bodies are generated on every run.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <stdbool.h>
#include <math.h>
#include <float.h>
#include <limits.h>
#include "MiniSightGeometry.h"
#include "MiniSightGravity.h"
#include "MiniSightLiveliness.h"
#include "MiniSightPetBehavior.h"
#include "MiniSightPetMusicMotion.h"
#ifndef M_PI
#define M_PI 3.14159265358979323846
#define M_PI_2 (M_PI/2.)
#endif
#define YES true
#define NO false
#define NSNotFound UINT32_MAX
#define MIN(a,b) fmin((a),(b))
#define MAX(a,b) fmax((a),(b))
typedef MSPoint CGPoint;
typedef struct { double width,height; } CGSize;
typedef struct { CGPoint origin; CGSize size; } CGRect;
typedef MSVisualTransform CGAffineTransform;
typedef int CGImageRef;
#define CGPointZero ((CGPoint){0,0})
#define CGAffineTransformIdentity ((CGAffineTransform){1,0,0,1,0,0})
#define CGRectNull ((CGRect){{INFINITY,INFINITY},{0,0}})
static CGPoint CGPointMake(double x,double y) {return (CGPoint){x,y};}
static CGRect CGRectMake(double x,double y,double w,double h) {return (CGRect){{x,y},{w,h}};}
static bool CGRectEqualToRect(CGRect a,CGRect b) {return a.origin.x==b.origin.x&&a.origin.y==b.origin.y&&a.size.width==b.size.width&&a.size.height==b.size.height;}
static CGAffineTransform CGAffineTransformMake(double a,double b,double c,double d,double tx,double ty) {return (CGAffineTransform){a,b,c,d,tx,ty};}
static CGAffineTransform CGAffineTransformMakeTranslation(double x,double y) {return CGAffineTransformMake(1,0,0,1,x,y);}
static CGAffineTransform CGAffineTransformRotate(CGAffineTransform t,double angle) {
 double c=cos(angle),s=sin(angle);return CGAffineTransformMake(t.a*c+t.c*s,t.b*c+t.d*s,t.c*c-t.a*s,t.d*c-t.b*s,t.tx,t.ty);
}
static CGAffineTransform CGAffineTransformScale(CGAffineTransform t,double sx,double sy) {t.a*=sx;t.b*=sx;t.c*=sy;t.d*=sy;return t;}
static CGAffineTransform CGAffineTransformTranslate(CGAffineTransform t,double x,double y) {t.tx+=t.a*x+t.c*y;t.ty+=t.b*x+t.d*y;return t;}
static bool CGAffineTransformEqualToTransform(CGAffineTransform a,CGAffineTransform b) {return !memcmp(&a,&b,sizeof(a));}
static MSPoint MSPetPoint(CGPoint p) {return p;}
static CGPoint MSPetCGPoint(MSPoint p) {return p;}
static unsigned RandomRoll=25;
/* Fixture-only name: never redeclare the SDK's external arc4random_uniform. */
#define arc4random_uniform MSPetFixtureRandomUniform
static unsigned MSPetFixtureRandomUniform(unsigned n) {return n?RandomRoll%n:0;}
static double MSPetRandomUnit(void) {return .5;}
static double MSPetRandomRange(double a,double b) {return (a+b)*.5;}
static double MSPetClampUnit(double x) {return MSPetFiniteClamp(x,-1,1);}
static double Now=100.;
static int NextMotionID,NextRoamID,NextFrameID;
static bool Reduce,Chat;
static double CACurrentMediaTime(void) {return Now;}
static bool UIAccessibilityIsReduceMotionEnabled(void) {return Reduce;}
static const char *Case="setup";
#define CHECK(x) do {if(!(x)){fprintf(stderr,"FAIL: %s line %d: %s\n",Case,__LINE__,#x);exit(1);}}while(0)
static struct {
 CGPoint center,motionStart,motionEnd;
 CGRect bounds,centerBounds,lastSpriteRect;
 CGAffineTransform transform;
 MSPetResident resident;
 MSGravityBody gravityBody;
 bool wantsPlaying,suspended,hasCenterBounds,hasPet,hidden,windowExists,windowHidden,layerExists,sheetExists;
 bool activityActive,interactionActive,lyricsSuppressed,roamingPaused,physicsMotion,motionActive,dragging,reducedWork,gravityEnabled,geometryReady,musicMotion;
 unsigned musicMotionStep,roamGeneration;
 double alpha,poseBegan,lastMotionTick,lastSpriteTime,stateHoldUntil,dailyActionDue,dailyActionHoldUntil,landingRecoveryBegan,jumpHeight;
 double flingSpin,flingSpinVelocity,flingSquash,gravityRoll,gravityStrength;
 double gravityImpulseAngle,gravityImpulseBegan,gravityImpulseDuration,motionBegan,motionDuration;
 double roamInterval,roamPace,restAfterMotion;
 unsigned activeMotionGeneration,motionGeneration,loggedFloorGeneration,motionLockReasons;
 int column,state,spriteLayout,variantIndex,landingRecoveryStage,motionLink,frameTimer,roamTimer,gravityLink,hostContents;
 void (*onGeometryChanged)(void);
} P;
static struct {
 bool running,busy,ownsSprite,dragging,flying,musicPlaying,waking,starsExists,hasLand,hasTap,manifestPresent,framePending;
 bool bubbleHidden,hasWalk,hasJump,hasDailyActionPool;
 int link,state,clip,recoveryStage,preferredFPS,linkFPS;
 unsigned displayedFrame,frameRequest,frameFailures,musicEvidenceBudget,lastMusicCue;
 double frameRetryAt;
 const char *role,*wantedRole,*transientRole;
 double clipDuration,clipStart,selectionBegan,lastTime,landBegan,landUntil,landImpact;
 double musicAnchor,musicAnchorAt,musicAmplitude,recoveryBegan,transientUntil,shakeUntil,shakeBegan;
 double tilt,sway,flightAngle,impact,grabX,grabY,shakeDirection,shakeStrength;
 MSPetDamped angle,offsetX,offsetY,scaleX,scaleY,pivotX,pivotY,dragX,dragY;
 MSPetDragTrail trail;
 CGPoint visualOffset,dragTarget;
} E;
typedef struct {CGPoint vertices[96];unsigned count,subpaths;} FixturePathData;
static struct {CGRect frame;FixturePathData *path;double opacity,lineWidth;int fillColor,strokeColor;bool hidden;} D;
static struct {CGAffineTransform transform;CGRect contentsRect;int contents;} S;
typedef struct {CGRect bounds;} FixtureViewport;
static FixtureViewport Viewport;
static FixturePathData StarPath;
static CGRect LastCrop;
static double SheetWidth=768.,SheetHeight=936.,ObservedImpact;
static unsigned CenterWrites,Crops,RoamArms,Purges,EffectTicks,ContactTicks;
static bool CancelOnCenter;
static bool DailyAvailable;
static unsigned DailyCalls;
static FILE *Trace;
static double ContactAt,RoamDeadline;
static int CGImageGetWidth(int image) {(void)image;return (int)SheetWidth;}
static int CGImageGetHeight(int image) {(void)image;return (int)SheetHeight;}
static int CGImageCreateWithImageInRect(int image,CGRect r) {(void)image;LastCrop=r;++Crops;return 1;}
static void CGImageRelease(int image) {(void)image;}
static bool FixtureRole(const char*a,const char*b) {return a&&b&&!strcmp(a,b);}
static bool FixtureTransient(const char*r) {return FixtureRole(r,"tap")||FixtureRole(r,"idleAlt")||FixtureRole(r,"land")||FixtureRole(r,"shakeSoft")||FixtureRole(r,"shakeHard")||FixtureRole(r,"wake");}
static bool FixtureVisible(void) {return P.hasPet&&P.windowExists&&!P.windowHidden&&!P.hidden&&P.alpha>.01;}
static bool FixtureBlocked(void) {return E.busy||Chat;}
static bool FixtureHasDailyActions(void) {return E.hasDailyActionPool;}
static void FixtureSetCenter(CGPoint);
static void FixtureWake(void);
static void FixtureInvalidateRoam(void) {++P.roamGeneration;P.roamTimer=0;RoamDeadline=0.;}
static void FixtureInvalidateFrame(void) {P.frameTimer=0;}
static void FixtureInvalidateMotion(void) {P.motionLink=0;}
static void FixtureEnsureFrame(void);
static void FixtureEnsureMotion(void) {if(P.motionActive&&!P.motionLink)P.motionLink=++NextMotionID;}
static void FixtureCancelGravity(void) {P.gravityLink=0;P.gravityImpulseDuration=0;}
static void FixtureUpdateResident(double t) {(void)t;}
static bool FixtureConsumeAttention(double t) {(void)t;return false;}
static void FixtureClearResident(void) {MSPetResidentReset(&P.resident);}
static void FixtureArmRoam(double t) {CHECK(t>=.05);FixtureInvalidateRoam();P.roamTimer=++NextRoamID;RoamDeadline=Now+t;++RoamArms;}
static double FixtureDailyActionDuration(void) {++DailyCalls;return DailyAvailable?2.:0.;}
static double FixtureIdleAction(void) {return 0.;}
static void FixtureChooseRole(void);
static void FixtureAdvanceActions(double);
static void FixtureSetRunning(bool);
static void FixtureRestorePoster(void);
static void FixtureLyrics(bool blocked) {(void)blocked;}
static void FixtureTilt(double angle,double sway) {E.tilt=angle;E.sway=sway;}
static void FixturePurgeFrames(void) {++Purges;E.framePending=false;}
/* CADisplayLink / NSTimer plumbing for MiniSightPetEffects: QuartzCore boundary. */
static int FixtureEffectLinkCreate(void) {return 9;}
static void FixtureEffectLinkStart(void) {E.link=9;}
static void FixtureEffectLinkStop(void) {E.link=0;}
/* ActionLibrary image delivery: the async decode completion is fixture-owned. */
static void FixtureRequestFrame(unsigned index) {
 (void)index;
 if(E.running&&E.clip&&!E.framePending){E.framePending=true;++E.frameRequest;}
}
static void FixtureClearHostImage(void) {P.hostContents=0;}
static FixturePathData *FixturePath(void) {memset(&StarPath,0,sizeof(StarPath));return &StarPath;}
static void FixtureMove(FixturePathData *p,CGPoint v) {CHECK(p->count<96);p->vertices[p->count++]=v;++p->subpaths;}
static void FixtureLine(FixturePathData *p,CGPoint v) {CHECK(p->count<96);p->vertices[p->count++]=v;}
static void FixtureClose(FixturePathData *p) {(void)p;}
#include "production-paths.h"

/* Dependency callbacks; none supplies the landing/music policy being tested. */
static void FixtureSetCenter(CGPoint p) {
 P.center=P_clampedCenter(p);++CenterWrites;
 if(CancelOnCenter){CancelOnCenter=false;P.hidden=true;P_cancelMotion();}
}
static void FixtureEnsureFrame(void) {if(!P.frameTimer&&!P.motionActive&&P_shouldAnimate())P.frameTimer=++NextFrameID;}
static void FixtureWake(void) {if(P_shouldAnimate())MSPetResidentTouch(&P.resident,Now);}
static void FixtureRestorePoster(void) {E.ownsSprite=false;P_restorePosterFrame();}
static void FixtureChooseRole(void) {
 if(!E.manifestPresent||!E.running)return;
 const char*w=E_currentRole();
 const char*actual=(FixtureRole(w,"land")&&E.hasLand)||(FixtureRole(w,"tap")&&E.hasTap)||
  ((FixtureRole(w,"walkLeft")||FixtureRole(w,"walkRight"))&&E.hasWalk)||(FixtureRole(w,"jump")&&E.hasJump)?w:"idle";
 E.wantedRole=w;
 if(FixtureRole(E.role,actual)&&E.clip)return;
 E.role=actual;E.clip=1;E.clipStart=0.;E.selectionBegan=Now;
 E.displayedFrame=NSNotFound;++E.frameRequest;E.framePending=true;
}
static void FixtureAdvanceActions(double now) {(void)now;FixtureChooseRole();}
static void FixtureSetRunning(bool running) {
 if(E.running==running)return;E.running=running;
 if(!running){
  ++E.frameRequest;E.framePending=false;E.link=0;E.dragging=false;E.flying=false;E.waking=false;
  E.state=0;E.transientRole=NULL;E.shakeUntil=0;E.landUntil=0;E.musicAmplitude=0;E.recoveryStage=0;
  memset(&E.trail,0,sizeof(E.trail));FixturePurgeFrames();FixtureRestorePoster();
  E.angle=(MSPetDamped){0,0};E.offsetX=(MSPetDamped){0,0};E.offsetY=(MSPetDamped){0,0};
  E.scaleX=(MSPetDamped){1,0};E.scaleY=(MSPetDamped){1,0};E.visualOffset=CGPointZero;
  S.transform=CGAffineTransformIdentity;D.hidden=true;D.path=NULL;return;
 }
 E.lastTime=Now;E.clipStart=0;E.displayedFrame=NSNotFound;E.link=3;FixtureChooseRole();
}
static void FinishFrame(void) {
 CHECK(E.framePending&&E.clip);E.framePending=false;E.ownsSprite=true;E.displayedFrame=0;E.clipStart=Now;S.contents=2;
}
static void Fresh(bool actions,bool land) {
 memset(&P,0,sizeof(P));memset(&E,0,sizeof(E));memset(&S,0,sizeof(S));memset(&D,0,sizeof(D));
 Now=100.;ContactAt=RoamDeadline=0.;ObservedImpact=0.;Reduce=Chat=CancelOnCenter=false;RandomRoll=25;
 DailyAvailable=false;DailyCalls=0;
 CenterWrites=Crops=RoamArms=Purges=EffectTicks=ContactTicks=0;NextMotionID=NextRoamID=0;NextFrameID=1;
 P.center=(CGPoint){180,300};P.bounds=CGRectMake(0,0,80,90);Viewport.bounds=CGRectMake(0,0,360,780);
 MSRect b=MSBodyCenterBounds(360,780,(MSSize){80,90},2);
 P.centerBounds=CGRectMake(b.x,b.y,b.w,b.h);P.hasCenterBounds=true;
 P.sheetExists=P.layerExists=P.hasPet=P.windowExists=P.wantsPlaying=true;P.alpha=1.;P.roamPace=1.;
 P.lastSpriteRect=CGRectNull;P.transform=S.transform=CGAffineTransformIdentity;
 E.scaleX.value=E.scaleY.value=1.;E.displayedFrame=NSNotFound;E.manifestPresent=actions;
 E.hasLand=land;E.clipDuration=3.;MSPetResidentTouch(&P.resident,Now);
 P_reconcilePlaybackOnce();if(actions)FinishFrame();P_applySpriteFrame();
 CHECK(S.contents&&P.frameTimer>0&&E.running&&E.link); /* production setRunning: creates a live CADisplayLink (fixture id 9), not the old magic 3 */
}
static void AssertPicture(void) {
 CGAffineTransform t=S.transform;double sx=hypot(t.a,t.b),sy=hypot(t.c,t.d);
 CHECK(isfinite(sx)&&isfinite(sy)&&sx>.80&&sy>.80&&sx/sy>.85&&sx/sy<1.18);
 double w=fabs(t.a)*P.bounds.size.width+fabs(t.c)*P.bounds.size.height;
 double h=fabs(t.b)*P.bounds.size.width+fabs(t.d)*P.bounds.size.height;
 CHECK(P.center.x+t.tx-w*.5>=1.999&&P.center.x+t.tx+w*.5<=358.001);
 CHECK(P.center.y+t.ty-h*.5>=1.999&&P.center.y+t.ty+h*.5<=778.001);
 CHECK(P.transform.a==1&&P.transform.d==1&&P.transform.b==0&&P.transform.c==0);
 if(E.recoveryStage)CHECK(fabs(sx-sy)<1e-8);
}
static void Record(const char*tag) {
 if(!Trace)return;CGAffineTransform t=S.transform;
 fprintf(Trace,"{\"tag\":\"%s\",\"time\":%.9f,\"age\":%.9f,\"center\":[%.9f,%.9f],\"size\":[80,90],\"state\":%d,\"stage\":%d,\"impact\":%.9f,\"angle\":%.9f,\"bob\":%.9f,\"transform\":[%.9f,%.9f,%.9f,%.9f,%.9f,%.9f],\"stars\":%s,\"opacity\":%.9f,\"vertices\":[",
 tag,Now,ContactAt?Now-ContactAt:Now-100.,P.center.x,P.center.y,P.state,P.landingRecoveryStage,ObservedImpact,E.angle.value,E.offsetY.value,t.a,t.b,t.c,t.d,t.tx,t.ty,(!D.hidden&&D.path)?"true":"false",D.opacity);
 if(!D.hidden&&D.path)for(unsigned j=0;j<D.path->count;j++)fprintf(Trace,"%s[%.9f,%.9f]",j?",":"",D.path->vertices[j].x,D.path->vertices[j].y);
 fputs("]}\n",Trace);
}
static void Tick(double dt,const char*tag) {
 Now+=dt;if(P.roamTimer&&Now>=RoamDeadline)FixtureRoamCallback(true,P.roamGeneration,P.roamTimer);
 if(P.motionLink)P_motionTick(P.motionLink);if(P.frameTimer)P_frameTick(P.frameTimer);
 if(P.landingRecoveryStage&&!ContactAt)ContactAt=Now;
 if(E.link){E_tick(E.link);++EffectTicks;}AssertPicture();Record(tag);
}
static void DragThrow(double speed) {
 P_beginDraggingAtPoint((CGPoint){40,18});CHECK(P.dragging&&E.dragging);
 double y=P.center.y;
 for(int i=1;i<=4;i++) {Now+=.02;P_updateDraggingTarget((CGPoint){P.center.x,y+speed*i*.02});E_tick(E.link);AssertPicture();Record("drag");}
 Now+=.001;P_endDraggingCancelled(false);
 CHECK(!P.dragging&&!E.dragging&&P.physicsMotion&&P.motionActive&&P.motionLink>0&&E.flying);
}
static void Heavy(bool actions) {
 Fresh(actions,false);Case=actions?"heavy-with-idle-action-ownership":"heavy-atlas-actual-drag-to-recovery";
 DragThrow(1450.);unsigned loops=0;while(P.motionActive&&loops++<480)Tick(1./60.,"flight");
 CHECK(!P.motionActive&&P.landingRecoveryStage==1&&P.frameTimer>0&&!E.flying);
 CHECK(ObservedImpact>=720.&&P.gravityBody.floorImpactVelocity==0.); // saved BEFORE solver cancellation
 double peak=0.;unsigned dizzy=0;bool stages[5]={0};bool ownedDuring=false;CGPoint fixed=P.center;
 for(int i=0;i<150;i++) {
  Tick(1./60.,actions?"heavy-actions":"heavy");int stage=P.landingRecoveryStage;stages[stage]=true;
  peak=fmax(peak,fabs(S.transform.b));if(!D.hidden&&D.path){++dizzy;CHECK(D.path->count==24&&D.path->subpaths==3);}
  CHECK(P.center.x==fixed.x&&P.center.y==fixed.y);
  if(actions&&E.ownsSprite&&E.clip)ownedDuring=true;
  if(stage)CHECK(P.state==MiniSightPetStateIdle);
 }
 CHECK(stages[2]&&stages[3]&&stages[4]&&stages[0]&&peak>.85&&dizzy>30);
 CHECK(!P.landingRecoveryStage&&D.hidden&&fabs(S.transform.b)<.003);
 /* stage 0 legitimately restores the poster before re-choosing idle; the fixture
    never auto-delivers the next clip frame, so ownership is asserted across recovery. */
 CHECK(actions?ownedDuring:Crops>1);printf("C PATH PASS: %s / peak %.3f / dizzy %u frames / impact %.2f\n",Case,peak,dizzy,ObservedImpact);
}
static void GentleAndCancel(void) {
 Case="light-placement-after-heavy-does-not-reuse-impact";Fresh(false,false);E.landImpact=1.;
 P_beginDraggingAtPoint((CGPoint){40,18});Now+=.025;P_endDraggingCancelled(false);
 CHECK(!P.physicsMotion&&!P.motionLink&&!P.landingRecoveryStage&&!E.flying);
 CHECK(E.landImpact==0.&&fabs(E.landUntil-Now-.5)<1e-9);
 for(int i=0;i<50;i++){Tick(1./60.,"gentle");CHECK(D.hidden&&fabs(S.transform.b)<.08);}
 puts("C PATH PASS: gentle set-down distinct from heavy, no historical impact");
 Case="cancel-drag-with-large-current-trail-is-not-a-throw";Fresh(false,false);
 P_beginDraggingAtPoint((CGPoint){40,18});Now+=.02;P_updateDraggingTarget((CGPoint){200,330});
 Now+=.02;P_updateDraggingTarget((CGPoint){230,370});E_tick(E.link);Now+=.001;P_endDraggingCancelled(true);
 CHECK(!P.physicsMotion&&!P.motionLink&&!P.landingRecoveryStage&&E.landUntil==0.);
 CHECK(P.gravityBody.floorImpactVelocity==0.&&D.hidden);puts("C PATH PASS: actual cancelled gesture never launches or lands");
}
/* This exercises the production timer entry, real center-motion start, each
 * production motionTick, finishMotion and frameTick, not just target policy. */
static void MusicTravel(bool actions) {
 Case=actions?"music-real-walk-and-travelling-hop-actions":"music-real-walk-and-travelling-hop-atlas";
 Fresh(actions,false);E.hasWalk=E.hasJump=true;P_setMusicPlaying(true);
 CHECK(E.musicPlaying&&P.roamTimer&&RoamDeadline>Now);
 CGPoint original=P.center,previous=P.center;double excursion=0.,walkNet=0.,hopNet=0.;
 unsigned walks=0,hops=0;bool wasMoving=false,wasHop=false;CGPoint began=original;
 for(int i=0;i<1440;i++) {
  Tick(1./60.,actions?"music-travel-actions":"music-travel-atlas");
  CHECK(!P.physicsMotion&&!P.landingRecoveryStage);
  CHECK(hypot(P.center.x-previous.x,P.center.y-previous.y)<18.); // no teleport, including landing
  previous=P.center;excursion=fmax(excursion,hypot(P.center.x-original.x,P.center.y-original.y));
  if(P.motionActive&&!wasMoving) {
   began=P.center;wasHop=P.jumpHeight>0.;
   double distance=hypot(P.motionEnd.x-P.motionStart.x,P.motionEnd.y-P.motionStart.y);
   CHECK(P.musicMotion&&distance>20.);
   if(wasHop){++hops;CHECK(P.state==MiniSightPetStateJumping&&P.jumpHeight>=6.);CHECK(FixtureRole(E_currentRole(),"jump"));}
   else {++walks;CHECK(P.state==(P.motionEnd.x>P.motionStart.x?MiniSightPetStateRunRight:MiniSightPetStateRunLeft));
    CHECK(FixtureRole(E_currentRole(),P.motionEnd.x>P.motionStart.x?"walkRight":"walkLeft"));}
  }
  if(!P.motionActive&&wasMoving) {
   double net=hypot(P.center.x-began.x,P.center.y-began.y);
   if(wasHop)hopNet=fmax(hopNet,net);else walkNet=fmax(walkNet,net);
  }
  wasMoving=P.motionActive;
 }
 CHECK(walks>=2&&hops>=2&&walkNet>40.&&hopNet>40.&&excursion>80.);
 P_setMusicPlaying(false);CHECK(!P.musicMotion&&!P.motionActive&&!P.motionLink&&P.roamTimer);
 printf("C PATH PASS: %s / walk %u net %.2f / hop %u net %.2f / excursion %.2f\n",Case,walks,walkNet,hops,hopNet,excursion);
}
static void StartMusicRoute(void) {
 Fresh(false,false);P_setMusicPlaying(true);P_roamOnce();CHECK(P.musicMotion&&P.motionActive&&P.motionLink);
 Tick(.15,"music-before-gate");
}
static void MusicGates(void) {
 for(unsigned gate=0;gate<12;gate++) {
  Case="music-cancel-gate-and-resume";StartMusicRoute();CGPoint at=P.center;int stale=P.motionLink;
  switch(gate) {
   case 0:P_setRoamingPaused(true);break;case 1:P_setInteractionActive(true);break;
   case 2:P_setMotionLocked(true,1);break;case 3:P_setMotionLocked(true,2);break;
   case 4:P_setSuspended(true);break;case 5:P.hidden=true;P_reconcilePlaybackOnce();break;
   case 6:Chat=true;break;case 7:P_setLyricsSuppressed(true);break;
   case 8:P_setActivityActive(true);break;case 9:Reduce=true;break;
   case 10:P_setRoamPace(0.);break;case 11:P_stopPlaying();break;
  }
  Tick(1./60.,"music-gated");P_motionTick(stale);
  CHECK(!P.musicMotion&&!P.motionActive&&!P.motionLink&&!P.roamTimer);
  CHECK(P.center.x==at.x&&P.center.y==at.y);
  for(int i=0;i<30;i++)Tick(1./60.,"music-gated");
  CHECK(!P.motionLink&&!P.roamTimer);
  P_setRoamingPaused(false);P_setInteractionActive(false);P_setMotionLocked(false,1);P_setMotionLocked(false,2);
  P_setSuspended(false);P.hidden=false;Chat=Reduce=false;P_setLyricsSuppressed(false);P_setActivityActive(false);P_setRoamPace(1.);
  if(gate==11)P_startPlaying();P_reconcilePlaybackOnce();Tick(.02,"music-resumed");
  CHECK(P.roamTimer&&E.musicPlaying);P_roamOnce();CHECK(P.musicMotion&&P.motionActive);
 }
 Case="music-stop-freezes-current-center-restores-normal-roam";StartMusicRoute();CGPoint at=P.center;
 P_setMusicPlaying(false);CHECK(!P.motionActive&&!P.motionLink&&!P.musicMotion&&P.roamTimer);
 CHECK(P.center.x==at.x&&P.center.y==at.y);CHECK(RoamDeadline-Now>5.);
 RandomRoll=25;P_roamOnce();CHECK(P.motionActive&&!P.musicMotion);
 Case="music-toggle-never-cancels-manual-drag-fling";Fresh(false,false);P_beginDraggingAtPoint((CGPoint){40,18});
 P_setMusicPlaying(true);CHECK(P.dragging&&E.dragging&&!P.motionActive&&!P.roamTimer);
 P_endDraggingCancelled(true);CHECK(!P.physicsMotion&&!P.motionLink);
 Fresh(false,false);DragThrow(1450.);P_setMusicPlaying(true);CHECK(P.physicsMotion&&P.motionActive&&!P.musicMotion);
 P_setMusicPlaying(false);CHECK(P.physicsMotion&&P.motionActive); // user trajectory owns completion
 puts("C PATH PASS: music 12 cancellation/resume gates, stale tick, stop, drag and manual fling priority");
}
static void MusicDragFlingLoop(void) {
 for(unsigned hop=0;hop<2;hop++) {
  Case=hop?"music-hop-to-drag-fling-recovery-and-resume":"music-walk-to-drag-fling-recovery-and-resume";
  Fresh(false,false);P_setMusicPlaying(true);P.musicMotionStep=hop;P_roamOnce();Tick(.08,"music-before-drag");
  CHECK(P.musicMotion&&P.motionActive&&(P.jumpHeight>0.)==(hop!=0));
  CGPoint beforeDrag=P.center;DragThrow(1450.);CHECK(!P.musicMotion&&hypot(P.center.x-beforeDrag.x,P.center.y-beforeDrag.y)>1.);
  CGPoint previous=P.center;double travelled=0.;
  for(unsigned i=0;i<6;i++) {
   if(i==1)P_setMusicPlaying(false);if(i==3)P_setMusicPlaying(true);
   CHECK(P.physicsMotion&&P.motionActive&&!P.musicMotion);
   Tick(1./60.,"music-manual-flight-toggle");
   double delta=hypot(P.center.x-previous.x,P.center.y-previous.y);CHECK(delta>1.);travelled+=delta;previous=P.center;
  }
  unsigned limit=0;while(P.motionActive&&limit++<480)Tick(1./60.,"music-manual-heavy-flight");
  CHECK(!P.motionActive&&P.landingRecoveryStage==1&&ObservedImpact>=720.&&travelled>20.);
  bool stages[5]={0},dizzy=false;unsigned resumed=0;CGPoint landed=P.center;
  for(unsigned i=0;i<500;i++) {
   Tick(1./60.,"music-heavy-recover-resume");stages[P.landingRecoveryStage]=true;
   if(!D.hidden&&D.path)dizzy=true;if(P.musicMotion&&P.motionActive)++resumed;
  }
  CHECK(stages[1]&&stages[2]&&stages[3]&&stages[4]&&stages[0]&&dizzy&&resumed>0);
  CHECK(hypot(P.center.x-landed.x,P.center.y-landed.y)>20.&&E.musicPlaying);
  printf("C PATH PASS: %s / manual-flight net path %.2f / music resumed %u frames\n",Case,travelled,resumed);
 }
 Case="stale-timer-link-and-frame-after-new-action-rebuilt";Fresh(false,false);P_setMusicPlaying(true);
 int oldTimer=P.roamTimer;unsigned oldGeneration=P.roamGeneration;P_roamOnce();int oldLink=P.motionLink;
 Tick(.08,"late-before-rebuild");P_setMusicPlaying(false);P_setMusicPlaying(true);
 int newTimer=P.roamTimer;CHECK(newTimer&&newTimer!=oldTimer);CGPoint frozen=P.center;
 unsigned generation=P.motionGeneration;double deadline=RoamDeadline;
 FixtureRoamCallback(true,oldGeneration,oldTimer);CHECK(P.roamTimer==newTimer&&P.motionGeneration==generation&&RoamDeadline==deadline);
 FixtureRoamCallback(false,P.roamGeneration,newTimer);CHECK(P.roamTimer==newTimer);
 FixtureRoamCallback(true,P.roamGeneration,oldTimer);CHECK(P.roamTimer==newTimer); // pointer fence independently
 FixtureRoamCallback(true,oldGeneration,newTimer);CHECK(P.roamTimer==newTimer); // generation fence independently
 P_roamOnce();CHECK(P.motionLink&&P.motionLink!=oldLink);generation=P.motionGeneration;
 P_motionTick(oldLink);CHECK(P.motionGeneration==generation&&P.center.x==frozen.x&&P.center.y==frozen.y);
 Tick(.08,"late-new-action-advances");CHECK(hypot(P.center.x-frozen.x,P.center.y-frozen.y)>1.);
 puts("C PATH PASS: old captured roam owner/generation/timer and old motion link cannot mutate rebuilt action");
}
static void MusicBoundsAndNormal(void) {
 const MSPoint corners[]={{42,47},{318,47},{42,733},{318,733}};
 for(unsigned k=0;k<4;k++) {
  Case="music-at-safe-corners";Fresh(false,false);FixtureSetCenter(corners[k]);P_setMusicPlaying(true);
  unsigned hop=0;CGPoint previous=P.center;
  for(int i=0;i<900;i++){Tick(1./60.,"music-corner");if(P.jumpHeight>=6.&&P.motionActive)hop++;
   CHECK(hypot(P.center.x-previous.x,P.center.y-previous.y)<18.);previous=P.center;}
  CHECK(hop>0);
 }
 for(unsigned k=0;k<4;k++) {
  Case="music-collapsed-or-tiny-centers";Fresh(false,false);
  P_setCenterBounds(CGRectMake(179,299,k==0?0:k==1?.3:k==2?0:1.2,k==0?0:k==1?.2:2.));
  P_setMusicPlaying(true);for(int i=0;i<480;i++){Tick(1./60.,"music-tiny");CHECK(!P.physicsMotion);}
  CHECK(k?E.musicPlaying:!P.motionActive);P_setCenterBounds(CGRectMake(42,47,276,686));
  P_roamOnce();CHECK(P.motionActive&&P.musicMotion);
 }
 Case="ordinary-roam-preserves-walk-hop-wave-and-rest";
 for(unsigned k=0;k<4;k++) {
  Fresh(false,false);RandomRoll=k==0?25:k==1?65:k==2?85:95;
  if(k==2)E.ownsSprite=true; // An old/one-GIF import still has no daily role pool.
  P_roamOnce();
  if(k<2){CHECK(P.motionActive&&!P.musicMotion);CHECK((P.jumpHeight>0.)==(k==1));}
  else if(k==2)CHECK(P.state==MiniSightPetStateWaving&&P.stateHoldUntil>Now);
  else CHECK(!P.motionActive&&P.roamTimer);
 }
 Fresh(false,false);E.hasDailyActionPool=true;RandomRoll=85;P_roamOnce();
 CHECK(P.state!=MiniSightPetStateWaving&&!P.motionActive&&P.roamTimer);
 puts("C PATH PASS: music safe corners, collapsed/tiny bounds, geometry recovery, old single-GIF fallback and weighted roam");
}
static void DailyActionIndependentOfRoam(void) {
 Case="daily-pose-runs-with-roaming-disabled-and-yields-to-priority-owners";
 Fresh(false,false);P.roamingPaused=true;P.roamPace=0.;CHECK(!P_mayRoam());
 CGPoint fixed=P.center;DailyAvailable=true;P.dailyActionDue=Now-1.;P_tryDailyActionAt(Now);
 CHECK(DailyCalls==1&&P.dailyActionHoldUntil>Now&&P.dailyActionDue==0.&&!P.roamTimer&&!P.motionActive);
 CHECK(P.center.x==fixed.x&&P.center.y==fixed.y);
 double hold=P.dailyActionHoldUntil;Now+=1.;P_tryDailyActionAt(Now);
 CHECK(DailyCalls==1&&P.dailyActionHoldUntil==hold&&P.center.x==fixed.x&&P.center.y==fixed.y);
 Now=hold+.1;P_tryDailyActionAt(Now);
 CHECK(DailyCalls==1&&fabs(P.dailyActionDue-Now-19.5)<1e-9); // Finish, then a real quiet interval.
 E.musicPlaying=true;P.dailyActionDue=Now-1.;P_tryDailyActionAt(Now);
 CHECK(DailyCalls==1&&P.dailyActionDue==0.&&P.dailyActionHoldUntil==0.);
 E.musicPlaying=false;P.activityActive=true;P_tryDailyActionAt(Now);CHECK(DailyCalls==1&&P.dailyActionDue==0.);
 P.activityActive=false;P.resident.sleeping=true;P_tryDailyActionAt(Now);CHECK(DailyCalls==1&&P.dailyActionDue==0.);
 P.resident.sleeping=false;Chat=true;P_tryDailyActionAt(Now);CHECK(DailyCalls==1&&P.dailyActionDue==0.);Chat=false;
 DailyAvailable=false;P.dailyActionDue=Now-1.;P_tryDailyActionAt(Now);
 CHECK(DailyCalls==2&&P.dailyActionHoldUntil==0.&&fabs(P.dailyActionDue-Now-30.)<1e-9);
 CHECK(P.center.x==fixed.x&&P.center.y==fixed.y&&!P.motionActive);
 puts("C PATH PASS: daily pose timer independent of roam, finishes before retry, preserves music/sleep/chat priority");
}
static void InvisibleGate(void) {
 Case="hidden-or-locked-host-stops-frame-roam-and-music";
 Fresh(false,false);
 P.hidden=true;
 CHECK(!P_shouldAnimate());
 P_scheduleRoam();
 CHECK(!P.roamTimer);        /* mayRoam false -> roam timer cleared */
 P_frameTick(2);
 CHECK(!P.motionActive&&!P.motionLink&&!P.landingRecoveryStage);
 P_setMusicPlaying(true);
 for(int i=0;i<120;i++){Now+=1./60.;if(E.link)E_tick(E.link);}
 CHECK(!E.running);          /* effects tick retires itself when host invisible */
 puts("C PATH PASS: hidden/locked host stops frame, roam and music loops");
}
int main(int argc,char**argv) {
 for(int i=1;i<argc;i++) {
  if(!strcmp(argv[i],"--trace")&&i+1<argc){Trace=fopen(argv[++i],"w");CHECK(Trace);}
 }
 Heavy(false);
 Heavy(true);
 GentleAndCancel();
 MusicTravel(false);
 MusicTravel(true);
 MusicGates();
 MusicDragFlingLoop();
 MusicBoundsAndNormal();
 DailyActionIndependentOfRoam();
 InvisibleGate();
 if(Trace){fclose(Trace);Trace=NULL;}
 puts("PET PATH SUITE PASS: daily pose/roam independence, blockers, heavy, gentle/cancel, music travel, 12 gates, corners/tiny and ordinary roaming");
 return 0;
}
