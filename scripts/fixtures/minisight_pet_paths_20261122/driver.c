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
static double MSPetRandomUnit(void) {return .5;}
static double MSPetRandomRange(double a,double b) {return (a+b)*.5;}
static double MSPetClampUnit(double x) {return MSPetFiniteClamp(x,-1,1);}
static double Now=100.;
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
 bool activityActive,interactionActive,lyricsSuppressed,roamingPaused,physicsMotion,motionActive,dragging,reducedWork,gravityEnabled,geometryReady;
 double alpha,poseBegan,lastMotionTick,lastSpriteTime,stateHoldUntil,landingRecoveryBegan,jumpHeight;
 double flingSpin,flingSpinVelocity,flingSquash,gravityRoll,gravityStrength;
 double gravityImpulseAngle,gravityImpulseBegan,gravityImpulseDuration,motionBegan,motionDuration;
 double roamInterval,roamPace,restAfterMotion;
 unsigned activeMotionGeneration,motionGeneration,loggedFloorGeneration,motionLockReasons;
 int column,state,spriteLayout,variantIndex,landingRecoveryStage,motionLink,frameTimer,roamTimer,gravityLink,hostContents;
 void (*onGeometryChanged)(void);
} P;
static struct {
 bool running,busy,ownsSprite,dragging,flying,musicPlaying,waking,starsExists,hasLand,hasTap,manifestPresent,framePending;
 bool bubbleHidden;
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
static FILE *Trace;
static double ContactAt;
static int CGImageGetWidth(int image) {(void)image;return (int)SheetWidth;}
static int CGImageGetHeight(int image) {(void)image;return (int)SheetHeight;}
static int CGImageCreateWithImageInRect(int image,CGRect r) {(void)image;LastCrop=r;++Crops;return 1;}
static void CGImageRelease(int image) {(void)image;}
static bool FixtureRole(const char*a,const char*b) {return a&&b&&!strcmp(a,b);}
static bool FixtureTransient(const char*r) {return FixtureRole(r,"tap")||FixtureRole(r,"idleAlt")||FixtureRole(r,"land")||FixtureRole(r,"shakeSoft")||FixtureRole(r,"shakeHard")||FixtureRole(r,"wake");}
static bool FixtureVisible(void) {return P.hasPet&&P.windowExists&&!P.windowHidden&&!P.hidden&&P.alpha>.01;}
static bool FixtureBlocked(void) {return E.busy||Chat;}
static void FixtureSetCenter(CGPoint);
static void FixtureWake(void);
static void FixtureInvalidateRoam(void) {P.roamTimer=0;}
static void FixtureInvalidateFrame(void) {P.frameTimer=0;}
static void FixtureInvalidateMotion(void) {P.motionLink=0;}
static void FixtureEnsureFrame(void);
static void FixtureEnsureMotion(void) {if(P.motionActive)P.motionLink=1;}
static void FixtureCancelGravity(void) {P.gravityLink=0;P.gravityImpulseDuration=0;}
static void FixtureUpdateResident(double t) {(void)t;}
static void FixtureConsumeAttention(double t) {(void)t;}
static void FixtureClearResident(void) {MSPetResidentReset(&P.resident);}
static void FixtureArmRoam(double t) {(void)t;P.roamTimer=4;++RoamArms;}
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
static void FixtureEnsureFrame(void) {if(!P.frameTimer&&!P.motionActive&&P_shouldAnimate())P.frameTimer=2;}
static void FixtureWake(void) {if(P_shouldAnimate())MSPetResidentTouch(&P.resident,Now);}
static void FixtureRestorePoster(void) {E.ownsSprite=false;P_restorePosterFrame();}
static void FixtureChooseRole(void) {
 if(!E.manifestPresent||!E.running)return;
 const char*w=E_currentRole();
 const char*actual=(FixtureRole(w,"land")&&E.hasLand)||(FixtureRole(w,"tap")&&E.hasTap)?w:"idle";
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
 Now=100.;ContactAt=0.;ObservedImpact=0.;Reduce=Chat=CancelOnCenter=false;
 CenterWrites=Crops=RoamArms=Purges=EffectTicks=ContactTicks=0;
 P.center=(CGPoint){180,300};P.bounds=CGRectMake(0,0,80,90);Viewport.bounds=CGRectMake(0,0,360,780);
 MSRect b=MSBodyCenterBounds(360,780,(MSSize){80,90},2);
 P.centerBounds=CGRectMake(b.x,b.y,b.w,b.h);P.hasCenterBounds=true;
 P.sheetExists=P.layerExists=P.hasPet=P.windowExists=P.wantsPlaying=true;P.alpha=1.;P.roamPace=1.;
 P.lastSpriteRect=CGRectNull;P.transform=S.transform=CGAffineTransformIdentity;
 E.scaleX.value=E.scaleY.value=1.;E.displayedFrame=NSNotFound;E.manifestPresent=actions;
 E.hasLand=land;E.clipDuration=3.;MSPetResidentTouch(&P.resident,Now);
 P_reconcilePlaybackOnce();if(actions)FinishFrame();P_applySpriteFrame();
 CHECK(S.contents&&P.frameTimer==2&&E.running&&E.link); /* production setRunning: creates a live CADisplayLink (fixture id 9), not the old magic 3 */
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
 Now+=dt;if(P.motionLink)P_motionTick(P.motionLink);if(P.frameTimer)P_frameTick(P.frameTimer);
 if(P.landingRecoveryStage&&!ContactAt)ContactAt=Now;
 if(E.link){E_tick(E.link);++EffectTicks;}AssertPicture();Record(tag);
}
static void DragThrow(double speed) {
 P_beginDraggingAtPoint((CGPoint){40,18});CHECK(P.dragging&&E.dragging);
 double y=P.center.y;
 for(int i=1;i<=4;i++) {Now+=.02;P_updateDraggingTarget((CGPoint){P.center.x,y+speed*i*.02});E_tick(E.link);AssertPicture();Record("drag");}
 Now+=.001;P_endDraggingCancelled(false);
 CHECK(!P.dragging&&!E.dragging&&P.physicsMotion&&P.motionActive&&P.motionLink==1&&E.flying);
}
static void Heavy(bool actions) {
 Fresh(actions,false);Case=actions?"heavy-with-idle-action-ownership":"heavy-atlas-actual-drag-to-recovery";
 DragThrow(1450.);unsigned loops=0;while(P.motionActive&&loops++<480)Tick(1./60.,"flight");
 CHECK(!P.motionActive&&P.landingRecoveryStage==1&&P.frameTimer==2&&!E.flying);
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
static void MusicInPlace(void) {
 Case="music-swings-in-place-never-walks";
 Fresh(false,false);
 P_setMusicPlaying(true);
 CHECK(E.musicPlaying&&!P.roamTimer);
 CGPoint fixed=P.center;
 Tick(1./60.,"music");
 CHECK(P.state==MiniSightPetStateMusic);   /* advanceSpriteAtTime promotes Idle->Music when pose-free */
 double swayLo=1e9,swayHi=-1e9,bobLo=1e9,bobHi=-1e9;
 for(int i=0;i<600;i++) {
  Tick(1./60.,"music");
  CHECK(P.center.x==fixed.x&&P.center.y==fixed.y);
  CHECK(!P.physicsMotion&&!P.motionActive&&!P.roamTimer);
  CHECK(P.landingRecoveryStage==0);
  double a=fabs(S.transform.b);
  if(a<swayLo)swayLo=a; if(a>swayHi)swayHi=a;
  double ty=S.transform.ty;
  if(ty<bobLo)bobLo=ty; if(ty>bobHi)bobHi=ty;
 }
 CHECK(E.musicPlaying);
 CHECK(swayHi-swayLo>.01);   /* visible sway, not frozen */
 CHECK(bobHi-bobLo>.05);     /* visible bob */
 puts("C PATH PASS: music stays in place with continuous sway and bob");
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
 MusicInPlace();
 InvisibleGate();
 if(Trace){fclose(Trace);Trace=NULL;}
 puts("PET PATH SUITE PASS: 5 production scenarios");
 return 0;
}
