#import "support.h"
#include "MiniSightLayout.h"
static CGSize Fit = {136,36}; // Deterministic font measurement dependency, not UIKit typography.
@implementation UIView {
    CGRect _frame, _bounds; CGPoint _center; CALayer *_layer;
    __weak UIView *_superview; NSMutableArray<UIView *> *_children;
}
- (instancetype)init { if ((self=[super init])) { _alpha=1.; _layer=[CALayer layer]; _children=[NSMutableArray new]; } return self; }
- (CGRect)frame { return _frame; }
- (void)setFrame:(CGRect)v { _frame=v; _bounds.size=v.size; _center=CGPointMake(CGRectGetMidX(v),CGRectGetMidY(v)); }
- (CGRect)bounds { return _bounds; }
- (void)setBounds:(CGRect)v { _bounds=v; _frame.size=v.size; self.center=_center; }
- (CGPoint)center { return _center; }
- (void)setCenter:(CGPoint)v { _center=v; _frame.origin=CGPointMake(v.x-_bounds.size.width/2,v.y-_bounds.size.height/2); }
- (CALayer *)layer { return _layer; }
- (UIView *)superview { return _superview; }
- (void)addSubview:(UIView *)v { [v removeFromSuperview]; v->_superview=self; [_children addObject:v]; }
- (void)removeFromSuperview { UIView *parent=_superview; if (parent) [parent->_children removeObject:self]; _superview=nil; }
- (void)addGestureRecognizer:(id)r { (void)r; }
- (void)bringSubviewToFront:(UIView *)v { (void)v; }
- (void)setNeedsLayout {}
- (void)layoutIfNeeded {}
@end
@implementation UIViewController @end
@implementation UIWindow @end
@implementation FixturePet
- (void)setMotionLocked:(BOOL)v forReason:(NSInteger)reason { (void)reason; self.motionLocked=v; }
@end
@implementation UIScrollView @end
@implementation UILabel
- (CGSize)sizeThatFits:(CGSize)v { return CGSizeMake(fmin(v.width,Fit.width),fmin(v.height,Fit.height)); }
@end
@implementation UIFont
+ (instancetype)systemFontOfSize:(CGFloat)s { UIFont *f=[self new]; f.lineHeight=s; return f; }
@end
@implementation UIColor { CGColorRef _color; }
- (instancetype)init { if ((self=[super init])) _color=CGColorCreateGenericRGB(1,1,1,1); return self; }
+ (instancetype)systemBackgroundColor { return [self new]; }
+ (instancetype)separatorColor { return [self new]; }
+ (instancetype)clearColor { return [self new]; }
+ (instancetype)labelColor { return [self new]; }
- (CGColorRef)CGColor { return _color; }
- (void)dealloc { CGColorRelease(_color); }
@end
@implementation UIBezierPath { CGMutablePathRef _path; }
- (instancetype)init { if ((self=[super init])) _path=CGPathCreateMutable(); return self; }
+ (instancetype)bezierPath { return [self new]; }
- (void)moveToPoint:(CGPoint)p { CGPathMoveToPoint(_path,NULL,p.x,p.y); }
- (void)addQuadCurveToPoint:(CGPoint)p controlPoint:(CGPoint)c { CGPathAddQuadCurveToPoint(_path,NULL,c.x,c.y,p.x,p.y); }
- (void)closePath { CGPathCloseSubpath(_path); }
- (CGPathRef)CGPath { return _path; }
- (void)dealloc { CGPathRelease(_path); }
@end
@implementation UIStackView
- (void)layoutIfNeeded { self.layoutCalls++; }
@end
@implementation UIButton @end
@implementation UITapGestureRecognizer
- (instancetype)initWithTarget:(id)t action:(SEL)a { (void)t; (void)a; return [super init]; }
@end
@implementation MiniSightChatPanel
+ (instancetype)existingPanel { return nil; }
@end

static UIWindow *gMiniSightWindow;
static FixturePet *gMiniSightPet;
static UIView *gMiniSightPill;
static BOOL gMiniSightBurst=NO, gMiniSightDragging=NO;
static CGPoint gMiniSightAnchor;
static int Writes, Allows, AnchorRestores;
static BOOL LastAllow;
static CGRect MiniSightScreenRect(void) { return gMiniSightWindow.rootViewController.view.bounds; }
static CGFloat MiniSightTopInset(void) { return gMiniSightWindow.safeAreaInsets.top; }
static CGFloat MiniSightBottomInset(void) { return gMiniSightWindow.safeAreaInsets.bottom; }
static void MiniSightUpdateMusic(void) {}
static BOOL MiniSightAlwaysShow(void) { return YES; }
static void MiniSightHide(void) {}
static void MiniSightSetAnchor(CGPoint p, BOOL save) { (void)p; (void)save; AnchorRestores++; }
static void MiniSightWriteConfirmResult(BOOL allow) { Writes++; Allows+=allow; LastAllow=allow; }
static void MSDiagEvent(NSString *a,NSString *b,NSString *c,NSDictionary *d) { (void)a; (void)b; (void)c; (void)d; }
static void MiniSightAnswerConfirm(BOOL allow);
static void MiniSightShowBubbleWidth(NSString *raw, CGFloat maxW, NSUInteger cap);
// PRODUCTION_EXCERPT

static const char *Case="setup";
static int Checks;
#define CHECK(x) do { Checks++; if (!(x)) { fprintf(stderr,"FAIL native bubble: %s line %d: %s\n",Case,__LINE__,#x); exit(1); } } while(0)
static BOOL Near(double a,double b) { return fabs(a-b)<.001; }
static void Reset(void) {
    [gMiniSightBubble removeFromSuperview];
    gMiniSightConfirming=NO; gMiniSightConfirmId=nil; gMiniSightConfirmTimeout=nil;
    FixtureResetBubble(); // Exact reset statements extracted from DestroyUI.
    gMiniSightWindow=[UIWindow new]; gMiniSightWindow.rootViewController=[UIViewController new];
    gMiniSightWindow.rootViewController.view=[UIView new];
    gMiniSightWindow.rootViewController.view.bounds=CGRectMake(0,0,390,844);
    gMiniSightWindow.safeAreaInsets=(UIEdgeInsets){47,0,34,0};
    gMiniSightPet=[FixturePet new]; gMiniSightPet.bounds=CGRectMake(0,0,56,61);
    gMiniSightPet.center=CGPointMake(30,32.5); gMiniSightPill=nil;
    gMiniSightDragging=NO; gMiniSightAnchor=gMiniSightPet.center;
    Writes=Allows=AnchorRestores=0; Fit=CGSizeMake(136,36);
}
static void Show(CGSize fit) { Fit=fit; MiniSightShowBubbleWidth(@"fixture text",260,600); }
static void CheckSize(double w,double h) { CHECK(Near(gMiniSightBubble.bounds.size.width,w)); CHECK(Near(gMiniSightBubble.bounds.size.height,h)); }
static void CheckHidden(void) { CHECK(gMiniSightBubbleShown && !gMiniSightBubble.hidden); CHECK(gMiniSightBubble.alpha==0); CHECK(!gMiniSightBubble.userInteractionEnabled); }
static void CheckVisible(void) { CHECK(gMiniSightBubble.alpha==1); CHECK(gMiniSightBubble.userInteractionEnabled); }

int main(void) { @autoreleasepool {
    Reset(); Case="first top 160x52 then middle";
    Show(CGSizeMake(136,36)); CheckHidden(); CheckSize(160,52);
    CHECK(CGPointEqualToPoint(gMiniSightPet.center,CGPointMake(30,32.5)));
    MSLayout before=MiniSightLayoutNow();
    gMiniSightPet.center=CGPointMake(30,400); MiniSightFollowBubble();
    CheckVisible(); CheckSize(160,52); CHECK(Near(gMiniSightBubbleScroll.frame.size.height,38));
    CHECK(Near(MiniSightLayoutNow().centers.y,before.centers.y)); CHECK(Allows==0 && Writes==0);

    Case="hidden long then short text";
    gMiniSightPet.center=CGPointMake(30,32.5); MiniSightFollowBubble(); CheckHidden();
    Show(CGSizeMake(236,200)); CheckHidden();
    gMiniSightPet.center=CGPointMake(30,500); MiniSightFollowBubble(); CheckVisible(); CheckSize(260,216);
    gMiniSightPet.center=CGPointMake(30,32.5); MiniSightFollowBubble();
    Show(CGSizeMake(80,18)); CheckHidden();
    gMiniSightPet.center=CGPointMake(30,400); MiniSightFollowBubble(); CheckVisible(); CheckSize(104,34);
    CHECK(Near(gMiniSightBubbleTail.frame.size.height,34));

    Case="stationary viewport clipped then restored";
    Show(CGSizeMake(236,200)); MiniSightFollowBubble();
    CGPoint center=gMiniSightPet.center;
    gMiniSightWindow.rootViewController.view.bounds=CGRectMake(0,0,200,844);
    MiniSightFollowBubble(); CHECK(gMiniSightBubble.bounds.size.width<260);
    CHECK(CGPointEqualToPoint(gMiniSightPet.center,center));
    gMiniSightWindow.rootViewController.view.bounds=CGRectMake(0,0,390,844);
    MiniSightFollowBubble(); CheckSize(260,216); // Must not persist clipped bounds.

    Case="stationary rotation and body resize";
    Show(CGSizeMake(136,36)); gMiniSightPet.center=CGPointMake(130,200); MiniSightFollowBubble();
    gMiniSightWindow.rootViewController.view.bounds=CGRectMake(0,0,844,390);
    MiniSightFollowBubble(); CheckVisible();
    gMiniSightWindow.safeAreaInsets=(UIEdgeInsets){180,0,34,0};
    MiniSightFollowBubble(); CheckHidden();
    gMiniSightWindow.safeAreaInsets=(UIEdgeInsets){47,0,34,0};
    MiniSightFollowBubble(); CheckVisible();
    CGFloat y=gMiniSightBubble.frame.origin.y;
    gMiniSightPet.bounds=CGRectMake(0,0,56,161); MiniSightFollowBubble();
    CHECK(Near(gMiniSightBubble.frame.origin.y,y-50)); CHECK(Near(gMiniSightPet.center.y,200));

    Case="hide show rebuild same dimensions";
    Reset(); gMiniSightPet.center=CGPointMake(30,400); Show(CGSizeMake(136,36));
    MiniSightHideBubble(); CHECK(gMiniSightBubble.hidden && !gMiniSightBubbleShown);
    MiniSightFollowBubble(); CHECK(gMiniSightBubble.hidden);
    Show(CGSizeMake(136,36)); CheckVisible();
    Reset(); CHECK(CGSizeEqualToSize(gMiniSightBubbleDesiredSize,CGSizeZero));
    CHECK(!gMiniSightBubbleLayoutValid && gMiniSightBubbleTailX==-1);
    gMiniSightPet.center=CGPointMake(30,400); Show(CGSizeMake(136,36));
    CHECK(gMiniSightBubbleScroll.frame.size.height>0); CHECK(gMiniSightBubbleTail.path!=NULL);

    Case="capsule keeps legacy relocation";
    Reset(); gMiniSightPet=nil; gMiniSightPill=[UIView new];
    gMiniSightPill.bounds=CGRectMake(0,0,132,36); gMiniSightPill.center=CGPointMake(80,32.5);
    Show(CGSizeMake(136,36)); CheckVisible(); CHECK(gMiniSightPill.center.y>32.5);
    CHECK(MiniSightLayoutNow().centers.y>100); CHECK(Writes==0);

    Case="approval headroom second pass buttons and cancellation";
    Reset(); gMiniSightConfirming=YES; gMiniSightConfirmId=@"fixture-id";
    gMiniSightPet.motionLocked=YES;
    Show(CGSizeMake(156,88)); CheckVisible(); CheckSize(180,140);
    CHECK(gMiniSightPet.center.y>32.5); CHECK(MiniSightLayoutNow().centers.y>200);
    CHECK(MSLayoutBubbleFits(MiniSightLayoutNow(),(MSPoint){gMiniSightPet.center.x,gMiniSightPet.center.y},
        (MSRect){gMiniSightBubble.frame.origin.x,gMiniSightBubble.frame.origin.y,180,140}));
    gMiniSightConfirmBar=[UIStackView new]; [gMiniSightBubble addSubview:gMiniSightConfirmBar];
    MiniSightPlaceBubble(gMiniSightBubble.bounds.size.width,gMiniSightBubble.bounds.size.height);
    CHECK(!gMiniSightConfirmBar.hidden); CHECK(Near(gMiniSightConfirmBar.frame.size.height,30));
    CHECK(Near(gMiniSightConfirmBar.frame.size.width,160)); CHECK(gMiniSightConfirmBar.layoutCalls>0);
    MiniSightHideBubble(); CHECK(!gMiniSightBubble.hidden && gMiniSightConfirming);
    MiniSightFollowBubble(); CHECK(Allows==0 && Writes==0);
    MiniSightCancelConfirm(); CHECK(Writes==1 && Allows==0 && !LastAllow);
    CHECK(!gMiniSightConfirming && !gMiniSightPet.motionLocked && gMiniSightConfirmId==nil);
    CHECK(gMiniSightBubble.hidden && !gMiniSightBubble.userInteractionEnabled && !gMiniSightBubbleShown);
    CHECK(AnchorRestores==1 && Near(MiniSightLayoutNow().centers.y,32.5));
    MiniSightCancelConfirm(); CHECK(Writes==1);

    Case="explicit deny allow and timeout never auto allow";
    MiniSightConfirmTarget *target=[MiniSightConfirmTarget new];
    gMiniSightConfirming=YES; [target deny:nil]; CHECK(Writes==2 && Allows==0);
    gMiniSightConfirming=YES; FixtureArmConfirmTimeout();
    dispatch_block_t timeout=gMiniSightConfirmTimeout; timeout(); CHECK(Writes==3 && Allows==0);
    gMiniSightConfirming=YES; [target allow:nil]; CHECK(Writes==4 && Allows==1 && LastAllow);
    printf("PASS native exact bubble functions: %d assertions; dependency mocks, NOT UIKit/device\n",Checks);
} return 0; }
