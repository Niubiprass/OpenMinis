#import "MiniSightChatPanel.h"
#import "MiniSightLog.h"
#import "MiniSightChatLayout.h"
#import <QuartzCore/QuartzCore.h>
#import <AVFoundation/AVFoundation.h>

static const CGFloat kMSChatMaxMessages = 30.0;

typedef NS_ENUM(NSInteger, MiniSightChatRole) {
    MiniSightChatRoleAssistant = 0,
    MiniSightChatRoleUser,
    MiniSightChatRoleNotice
};

static UIColor *MSChatColor(UIColor *light, UIColor *dark) {
    return [UIColor colorWithDynamicProvider:^UIColor *(UITraitCollection *traits) {
        return traits.userInterfaceStyle == UIUserInterfaceStyleDark ? dark : light;
    }];
}

static CGRect MSChatScreenRect(UIWindowScene *scene) {
    CGRect bounds = UIScreen.mainScreen.bounds;
    UIInterfaceOrientation orientation = scene.interfaceOrientation;
    if (orientation == UIInterfaceOrientationUnknown) {
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wdeprecated-declarations"
        orientation = UIApplication.sharedApplication.statusBarOrientation;
#pragma clang diagnostic pop
    }
    if (UIInterfaceOrientationIsLandscape(orientation)) {
        return CGRectMake(0, 0, MAX(bounds.size.width, bounds.size.height),
                          MIN(bounds.size.width, bounds.size.height));
    }
    return CGRectMake(0, 0, MIN(bounds.size.width, bounds.size.height),
                      MAX(bounds.size.width, bounds.size.height));
}

#pragma mark - Key-capable window

/// Separate from MiniSightWindow on purpose: the pet window must stay non-key
/// so the desktop keeps focus, while the chat needs the keyboard.
/// Transparent outside the composer/message stack; never block desktop taps.
@interface MiniSightChatWindow : UIWindow
@property (nonatomic, copy) NSArray<UIView *> *interactiveViews;
@end

@implementation MiniSightChatWindow
- (BOOL)canBecomeKeyWindow { return NO; }
- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent *)event {
    if (self.hidden || self.alpha < 0.01) return NO;
    for (UIView *view in self.interactiveViews) {
        if (view.hidden || view.alpha < 0.01) continue;
        CGPoint local = [view convertPoint:point fromView:self];
        // The docked bar gets 8pt horizontal slack so a near miss still hits.
        CGRect generous = CGRectInset(view.bounds, -8, -4);
        if (CGRectContainsPoint(generous, local) && (view.pointInside(local, event) || !view.clipsToBounds)) return YES;
    }
    return NO;
}
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
    return [self pointInside:point withEvent:event] ? [super hitTest:point withEvent:event] : nil;
}
@end

/// Content-hugging message, with a curved tail only on the latest pet reply.
@interface MiniSightChatBubble : UIView
@property (nonatomic, strong) UILabel *label;
@property (nonatomic, assign) BOOL petTail;
@property (nonatomic, assign) CGFloat tailX;
@property (nonatomic, assign) BOOL tailAbove;
@property (nonatomic, assign) BOOL userMessage;
- (instancetype)initWithText:(NSString *)text user:(BOOL)user;
@end

@implementation MiniSightChatBubble
- (instancetype)initWithText:(NSString *)text user:(BOOL)user {
    if (!(self = [super initWithFrame:CGRectZero])) return nil;
    self.backgroundColor = UIColor.clearColor;
    self.opaque = NO;
    self.userMessage = user;
    self.translatesAutoresizingMaskIntoConstraints = NO;
    UILabel *label = [UILabel new];
    label.translatesAutoresizingMaskIntoConstraints = NO;
    label.numberOfLines = 0;
    label.font = [UIFont systemFontOfSize:12.5];
    label.textColor = UIColor.labelColor;
    label.text = text;
    label.preferredMaxLayoutWidth = 232;
    [label setContentCompressionResistancePriority:UILayoutPriorityRequired forAxis:UILayoutConstraintAxisVertical];
    [self addSubview:label];
    self.label = label;
    [NSLayoutConstraint activateConstraints:@[
        [label.leadingAnchor constraintEqualToAnchor:self.leadingAnchor constant:12],
        [label.trailingAnchor constraintEqualToAnchor:self.trailingAnchor constant:-12],
        [label.topAnchor constraintEqualToAnchor:self.topAnchor constant:11],
        [label.bottomAnchor constraintEqualToAnchor:self.bottomAnchor constant:-14],
        [self.widthAnchor constraintGreaterThanOrEqualToConstant:36]
    ]];
    self.isAccessibilityElement = NO;
    label.isAccessibilityElement = YES;
    return self;
}
- (void)setPetTail:(BOOL)petTail { _petTail = petTail; [self setNeedsDisplay]; }
- (void)setTailX:(CGFloat)tailX { _tailX = tailX; [self setNeedsDisplay]; }
- (void)setTailAbove:(BOOL)tailAbove { _tailAbove = tailAbove; [self setNeedsDisplay]; }
- (void)traitCollectionDidChange:(UITraitCollection *)previous {
    [super traitCollectionDidChange:previous]; [self setNeedsDisplay];
}
- (void)drawRect:(CGRect)rect {
    (void)rect;
    CGRect body = CGRectInset(self.bounds, 0.6, 7.5);
    CGFloat radius = MIN(16, body.size.height * 0.5);
    UIBezierPath *path = [UIBezierPath bezierPathWithRoundedRect:body cornerRadius:radius];
    UIColor *fill = self.userMessage ? MSChatColor([UIColor colorWithWhite:0.98 alpha:0.96], [UIColor colorWithWhite:0.20 alpha:0.97]) : MSChatColor([UIColor colorWithWhite:1 alpha:0.98], [UIColor colorWithWhite:0.12 alpha:0.98]);
    UIColor *stroke = MSChatColor([UIColor colorWithWhite:0.20 alpha:0.70], [UIColor colorWithWhite:0.85 alpha:0.65]);
    if (self.petTail && body.size.width >= 40) {
        CGFloat x = MIN(CGRectGetMaxX(body) - radius - 7, MAX(CGRectGetMinX(body) + radius + 7, self.tailX));
        CGFloat y = self.tailAbove ? CGRectGetMinY(body) : CGRectGetMaxY(body);
        CGFloat sign = self.tailAbove ? -1 : 1;
        UIBezierPath *tail = [UIBezierPath bezierPath];
        [tail moveToPoint:CGPointMake(x - 6, y - sign * 1.0)];
        [tail addQuadCurveToPoint:CGPointMake(x, y + sign * 6.5) controlPoint:CGPointMake(x - 4, y + sign * 2)];
        [tail addQuadCurveToPoint:CGPointMake(x + 6, y - sign * 1.0) controlPoint:CGPointMake(x + 2, y + sign * 4)];
        [tail closePath];
        [path appendPath:tail];
        [fill setFill]; [path fill];
        // Stroke separately to avoid a horizontal seam through the tail.
        [stroke setStroke]; path.lineWidth = 1.05; [path stroke];
        [fill setStroke];
        UIBezierPath *seam = [UIBezierPath bezierPath];
        [seam moveToPoint:CGPointMake(x - 4.7, y)];
        [seam addLineToPoint:CGPointMake(x + 4.7, y)];
        seam.lineWidth = 2; [seam stroke];
    } else {
        [fill setFill]; [path fill];
        [MSChatColor([UIColor colorWithWhite:0 alpha:0.06], [UIColor colorWithWhite:1 alpha:0.10]) setStroke];
        path.lineWidth = 0.65; [path stroke];
    }
}
@end

/// The overlay itself remains non-key. This tiny independent window owns the
/// first responder only while the user is editing chat text.
@interface MiniSightChatEditorWindow : UIWindow
@property (nonatomic, weak) UITextField *editorField;
@end

@implementation MiniSightChatEditorWindow
- (BOOL)canBecomeKeyWindow { return YES; }
- (BOOL)pointInside:(CGPoint)point withEvent:(UIEvent *)event {
    UITextField *field = self.editorField;
    if (self.hidden || !field || field.hidden || field.alpha < 0.01) return NO;
    CGRect frame = [field convertRect:field.bounds toView:self];
    return CGRectContainsPoint(frame, point);
}
- (UIView *)hitTest:(CGPoint)point withEvent:(UIEvent *)event {
    if (![self pointInside:point withEvent:event]) return nil;
    return [super hitTest:point withEvent:event];
}
@end

/// The visible field is passive inside the non-key chat window. Tapping it
/// activates the separate editor window instead of attempting to make the
/// full chat overlay key.
@interface MiniSightPassiveTextField : UITextField
@end

@implementation MiniSightPassiveTextField
- (BOOL)canBecomeFirstResponder { return NO; }
@end

#pragma mark - Panel

@interface MiniSightChatPanel () <UITextFieldDelegate>
@property (nonatomic, strong, nullable) MiniSightChatWindow *window;
@property (nonatomic, strong, nullable) UIView *cardView;
@property (nonatomic, strong, nullable) UIVisualEffectView *cardBlurView;
@property (nonatomic, strong, nullable) UIView *cardTintView;
@property (nonatomic, strong, nullable) UIScrollView *scrollView;
@property (nonatomic, strong, nullable) UIStackView *messageStack;
@property (nonatomic, strong, nullable) UITextField *inputField;
@property (nonatomic, strong, nullable) UIButton *sendButton;
@property (nonatomic, strong, nullable) UIButton *cancelButton;
@property (nonatomic, strong, nullable) UIButton *moreButton;
@property (nonatomic, strong, nullable) UIButton *micButton;
@property (nonatomic, strong, nullable) UIStackView *actionBar;
@property (nonatomic, strong, nullable) UIScrollView *quickScroll;
@property (nonatomic, strong, nullable) UIStackView *quickRow;
@property (nonatomic, copy, nullable) void (^quickHandler)(NSString *action);
@property (nonatomic, assign) BOOL menuOpen;
@property (nonatomic, assign) CGPoint chatOffset;
@property (nonatomic, assign) CGRect lastAnchorRect;
@property (nonatomic, assign) CFTimeInterval lastAnchorTime;
@property (nonatomic, assign) NSUInteger voiceGeneration;
@property (nonatomic, copy, nullable) dispatch_block_t voiceWaiter;
@property (nonatomic, strong, nullable) UITapGestureRecognizer *editorTap;
@property (nonatomic, strong, nullable) NSLayoutConstraint *messageWidthConstraint;
@property (nonatomic, strong, nullable) MiniSightChatBubble *pendingBubble;
@property (nonatomic, assign) BOOL layingOut;
@property (nonatomic, assign) BOOL composerVisible;
@property (nonatomic, assign) BOOL messagesDirty;
@property (nonatomic, assign) BOOL lastLayoutBelow;
@property (nonatomic, assign) CGFloat measuredWidth;
@property (nonatomic, assign) CGFloat measuredMessageHeight;
@property (nonatomic, assign) CGFloat keyboardTop;
@property (nonatomic, assign) CGFloat lastKeyboardTop;
@property (nonatomic, assign) CFTimeInterval layoutLogTime;
@property (nonatomic, strong, nullable) NSMutableArray<UIView *> *rows;
@property (nonatomic, strong, nullable) MiniSightAI *ai;
@property (nonatomic, strong, nullable) MiniSightChatEditorWindow *editorWindow;
@property (nonatomic, strong, nullable) UITextField *editorField;
@property (nonatomic, assign) BOOL built;
@property (nonatomic, assign) BOOL visible;
@property (nonatomic, assign) BOOL closing;
@property (nonatomic, assign) BOOL sending;
@property (nonatomic, assign) BOOL editorActive;
@property (nonatomic, assign) NSUInteger lifecycleGeneration;
@property (nonatomic, assign) NSUInteger requestGeneration;
@property (nonatomic, assign) CGFloat keyboardOverlap;
- (void)performCloseForGeneration:(NSUInteger)generation;
- (void)hideWithoutKey;
- (void)activateEditor;
- (void)deactivateEditor;
- (void)deactivateEditorWithoutKey;
- (void)layoutEditorWindow;
- (void)editorInputChanged;
@end

static MiniSightChatPanel *gMiniSightExistingChatPanel;
static void MiniSightVoiceResult(CFNotificationCenterRef center, void *observer,
                                 CFNotificationName name, const void *object,
                                 CFDictionaryRef userInfo);

static void MiniSightVoiceResult(CFNotificationCenterRef center, void *observer,
                                 CFNotificationName name, const void *object,
                                 CFDictionaryRef userInfo) {
    MiniSightChatPanel *panel = (__bridge MiniSightChatPanel *)observer;
    dispatch_async(dispatch_get_main_queue(), ^{ [panel voiceResultArrived]; });
}

@implementation MiniSightChatPanel

+ (instancetype)sharedPanel {
    static dispatch_once_t once;
    dispatch_once(&once, ^{ gMiniSightExistingChatPanel = [[MiniSightChatPanel alloc] init]; });
    return gMiniSightExistingChatPanel;
}

+ (instancetype)existingPanel {
    return gMiniSightExistingChatPanel;
}

- (instancetype)init {
    self = [super init];
    if (!self) return nil;
    _rows = [NSMutableArray array];
    _appearancePreferences = @{};
    _ai = [[MiniSightAI alloc] initWithContainer:nil];
    return self;
}

- (CGFloat)configuredHeight {
    id value = self.appearancePreferences[@"minisight.chat.height"];
    CGFloat height = [value respondsToSelector:@selector(doubleValue)] ? [value doubleValue] : 160.0;
    return MIN(MAX(80.0, height), 200.0);
}

- (UIColor *)configuredTint {
    NSString *hex = self.appearancePreferences[@"minisight.chat.tintHex"];
    if (![hex isKindOfClass:NSString.class] || hex.length != 6) hex = @"8B5CF6";
    unsigned int rgb = 0;
    NSScanner *scanner = [NSScanner scannerWithString:hex];
    if (![scanner scanHexInt:&rgb]) rgb = 0x8B5CF6;
    id alphaValue = self.appearancePreferences[@"minisight.chat.tintAlpha"];
    CGFloat alpha = [alphaValue respondsToSelector:@selector(doubleValue)] ? [alphaValue doubleValue] : 0.22;
    alpha = MIN(0.14, MAX(0.02, alpha * 0.25));
    return [UIColor colorWithRed:((rgb >> 16) & 0xff) / 255.0
                           green:((rgb >> 8) & 0xff) / 255.0
                            blue:(rgb & 0xff) / 255.0 alpha:alpha];
}

- (CGFloat)scaleFor:(NSString *)key fallback:(CGFloat)fallback {
    id v = self.appearancePreferences[key];
    CGFloat n = [v respondsToSelector:@selector(doubleValue)] ? [v doubleValue] : fallback;
    return n > 0.2 ? n : fallback;
}

- (void)updateAppearance {
    if (!self.cardBlurView || !self.cardTintView) return;
    NSInteger theme = [self.appearancePreferences[@"minisight.chat.theme"] respondsToSelector:@selector(integerValue)]
        ? [self.appearancePreferences[@"minisight.chat.theme"] integerValue] : 0;
    UIBlurEffectStyle style = theme == 1 ? UIBlurEffectStyleRegular :
        (theme == 2 ? UIBlurEffectStyleProminent : UIBlurEffectStyleSystemMaterial);
    self.cardBlurView.effect = [UIBlurEffect effectWithStyle:style];
    self.cardTintView.backgroundColor = self.configuredTint;
    self.cardView.layer.borderColor = [UIColor.separatorColor colorWithAlphaComponent:0.26].CGColor;
    NSString *mode = self.appearancePreferences[@"darkMode"];
    self.window.overrideUserInterfaceStyle = [mode isEqualToString:@"light"] ? UIUserInterfaceStyleLight
        : ([mode isEqualToString:@"dark"] ? UIUserInterfaceStyleDark : UIUserInterfaceStyleUnspecified);
    if (self.visible) {
        for (NSString *key in @[@"minisight.chat.height", @"minisight.chat.theme", @"minisight.chat.tintHex", @"minisight.chat.tintAlpha"]) {
            NSMutableDictionary *fields = [@{@"setting": key, @"reason": @"appearance_assigned", @"visible": @YES} mutableCopy];
            if (_appearancePreferences[@"minisight.settings.revision"]) fields[@"revision"] = _appearancePreferences[@"minisight.settings.revision"];
            MSDiagEvent(@"settings", @"configure", @"ok", fields);
        }
    }
}

- (void)setAppearancePreferences:(NSDictionary<NSString *,id> *)appearancePreferences {
    _appearancePreferences = [appearancePreferences copy] ?: @{};
    [self updateAppearance];
    [self rebuildQuickRow];
    self.quickScroll.hidden = ![self.appearancePreferences[@"quick"] boolValue];
    self.messagesDirty = YES;
    if (self.built) [self layoutForCurrentScreen];
}

- (BOOL)isVisible { return _visible; }
- (BOOL)isSending { return _sending; }

- (void)setContainerPath:(NSString *)containerPath {
    NSCAssert([NSThread isMainThread], @"chat panel is main-thread only");
    if (_containerPath == containerPath || [_containerPath isEqualToString:containerPath]) return;
    if (self.sending) {
        ++self.requestGeneration;
        [self endSendingUI];
        [self.ai cancel];
        if (self.visible) [self appendNotice:@"配置容器已切换，请重新发送"];
    }
    _containerPath = [containerPath copy];
    self.ai.containerPath = _containerPath;
    MSDiag(@"chat container changed hasContainer=%d", _containerPath.length > 0);
}

#pragma mark Build

- (void)buildUI {
    NSCAssert([NSThread isMainThread], @"chat panel UI is main-thread owned");
    if (self.built) return;
    self.built = YES;
    CGRect screen = MSChatScreenRect(nil);
    MiniSightChatWindow *window = [[MiniSightChatWindow alloc] initWithFrame:screen];
    window.windowLevel = UIWindowLevelAlert + 2.0;
    window.backgroundColor = UIColor.clearColor;
    window.opaque = NO;
    window.hidden = YES;
    window.overrideUserInterfaceStyle = UIUserInterfaceStyleUnspecified;
    UIViewController *controller = [UIViewController new];
    controller.view = [[UIView alloc] initWithFrame:screen];
    controller.view.backgroundColor = UIColor.clearColor;
    window.rootViewController = controller;
    self.window = window;

    // No dimmer or full-screen touch catcher: only the little floating controls
    // consume input; the pet and the rest of the screen stay interactive.
    UIScrollView *scroll = [UIScrollView new];
    scroll.backgroundColor = UIColor.clearColor;
    scroll.alwaysBounceVertical = NO;
    scroll.showsVerticalScrollIndicator = NO;
    scroll.keyboardDismissMode = UIScrollViewKeyboardDismissModeOnDrag;
    [controller.view addSubview:scroll];
    self.scrollView = scroll;
    UITapGestureRecognizer *reveal = [[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(revealComposer)];
    reveal.cancelsTouchesInView = NO;
    [scroll addGestureRecognizer:reveal];
    UIStackView *stack = [UIStackView new];
    stack.translatesAutoresizingMaskIntoConstraints = NO;
    stack.axis = UILayoutConstraintAxisVertical;
    stack.spacing = 6;
    stack.alignment = UIStackViewAlignmentCenter;
    [scroll addSubview:stack];
    self.messageStack = stack;
    self.messageWidthConstraint = [stack.widthAnchor constraintEqualToConstant:272];
    self.messageWidthConstraint.active = YES;
    [NSLayoutConstraint activateConstraints:@[
        [stack.leadingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.leadingAnchor],
        [stack.trailingAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.trailingAnchor],
        [stack.topAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.topAnchor constant:2],
        [stack.bottomAnchor constraintEqualToAnchor:scroll.contentLayoutGuide.bottomAnchor constant:-7]
    ]];

    UIView *composer = [UIView new];
    composer.layer.cornerRadius = 15;
    composer.layer.cornerCurve = kCACornerCurveContinuous;
    composer.layer.borderWidth = 1.0 / UIScreen.mainScreen.scale;
    composer.layer.shadowColor = UIColor.blackColor.CGColor;
    composer.layer.shadowOpacity = 0.12;
    composer.layer.shadowRadius = 7;
    composer.layer.shadowOffset = CGSizeMake(0, 2);
    [controller.view addSubview:composer];
    self.cardView = composer;
    UIVisualEffectView *blur = [[UIVisualEffectView alloc] initWithEffect:nil];
    blur.layer.cornerRadius = 15;
    blur.clipsToBounds = YES;
    blur.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [composer addSubview:blur];
    UIPanGestureRecognizer *pan = [[UIPanGestureRecognizer alloc] initWithTarget:self action:@selector(composerPanned:)];
    pan.maximumNumberOfTouches = 1;
    [composer addGestureRecognizer:pan];
    UITapGestureRecognizer *openEditor = [[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(activateEditor)];
    openEditor.cancelsTouchesInView = NO;
    openEditor.delegate = self;
    self.editorTap = openEditor;
    [composer addGestureRecognizer:openEditor];
    self.cardBlurView = blur;
    UIView *tint = [UIView new];
    tint.autoresizingMask = UIViewAutoresizingFlexibleWidth | UIViewAutoresizingFlexibleHeight;
    [blur.contentView addSubview:tint];
    self.cardTintView = tint;

    UITextField *field = [MiniSightPassiveTextField new];
    field.delegate = self;
    field.returnKeyType = UIReturnKeySend;
    field.borderStyle = UITextBorderStyleNone;
    field.font = [UIFont systemFontOfSize:12.5];
    field.textColor = MSChatColor(UIColor.labelColor, UIColor.labelColor);
    field.backgroundColor = UIColor.clearColor;
    field.placeholder = @"和我说点什么…";
    field.autocapitalizationType = UITextAutocapitalizationTypeSentences;
    field.textContentType = nil;
    [field addTarget:self action:@selector(inputChanged) forControlEvents:UIControlEventEditingChanged];
    [composer addSubview:field];
    self.inputField = field;

    UIButton *send = [UIButton buttonWithType:UIButtonTypeSystem];
    [send setTitle:@"发送" forState:UIControlStateNormal];
    [send setTitleColor:UIColor.whiteColor forState:UIControlStateNormal];
    send.titleLabel.font = [UIFont systemFontOfSize:11 weight:UIFontWeightSemibold];
    send.backgroundColor = [UIColor colorWithRed:0.26 green:0.25 blue:0.33 alpha:1];
    send.layer.cornerRadius = 8;
    send.enabled = NO;
    send.alpha = 0.45;
    [send addTarget:self action:@selector(sendTapped) forControlEvents:UIControlEventTouchUpInside];
    [composer addSubview:send];
    self.sendButton = send;

    UIButton *cancel = [UIButton buttonWithType:UIButtonTypeSystem];
    [cancel setImage:[UIImage systemImageNamed:@"stop.fill"] forState:UIControlStateNormal];
    cancel.tintColor = UIColor.secondaryLabelColor;
    cancel.accessibilityLabel = @"取消回复";
    [cancel addTarget:self action:@selector(cancelSend) forControlEvents:UIControlEventTouchUpInside];
    cancel.hidden = YES;
    [composer addSubview:cancel];
    self.cancelButton = cancel;

    UIButton *mic = [UIButton buttonWithType:UIButtonTypeSystem];
    [mic setImage:[UIImage systemImageNamed:@"mic.fill"] forState:UIControlStateNormal];
    mic.tintColor = UIColor.secondaryLabelColor;
    mic.accessibilityLabel = @"语音输入";
    [mic addTarget:self action:@selector(voiceTapped) forControlEvents:UIControlEventTouchUpInside];
    [composer addSubview:mic];
    self.micButton = mic;

    UIButton *more = [UIButton buttonWithType:UIButtonTypeSystem];
    [more setImage:[UIImage systemImageNamed:@"ellipsis"] forState:UIControlStateNormal];
    more.tintColor = UIColor.secondaryLabelColor;
    more.accessibilityLabel = @"对话菜单";
    __weak typeof(self) weakSelf = self;
    [more addTarget:self action:@selector(toggleMenu) forControlEvents:UIControlEventTouchUpInside];

    [composer addSubview:more];
    self.moreButton = more;
    UIStackView *actions = [[UIStackView alloc] init];
    actions.axis = UILayoutConstraintAxisHorizontal;
    actions.spacing = 4;
    actions.distribution = UIStackViewDistributionFillEqually;
    actions.hidden = YES;
    actions.backgroundColor = [UIColor colorWithDynamicProvider:^UIColor *(UITraitCollection *t) {
        return t.userInterfaceStyle == UIUserInterfaceStyleDark
            ? [UIColor colorWithWhite:0.16 alpha:0.96] : [UIColor colorWithWhite:0.99 alpha:0.96];
    }];
    actions.layer.cornerRadius = 11;
    actions.layer.cornerCurve = kCACornerCurveContinuous;
    actions.layer.borderWidth = 1.0 / UIScreen.mainScreen.scale;
    actions.layer.borderColor = UIColor.separatorColor.CGColor;
    [controller.view addSubview:actions];
    self.actionBar = actions;
    for (NSArray *item in @[@[@"mic", @"听写"], @[@"trash", @"清空"], @[@"eye.slash", @"隐藏"], @[@"xmark", @"收起"]]) {
        UIButton *button = [UIButton buttonWithType:UIButtonTypeSystem];
        [button setImage:[UIImage systemImageNamed:item[0]] forState:UIControlStateNormal];
        [button setTitle:item[1] forState:UIControlStateNormal];
        button.titleLabel.font = [UIFont systemFontOfSize:10];
        [button setTitleColor:UIColor.secondaryLabelColor forState:UIControlStateNormal];
        button.tintColor = UIColor.secondaryLabelColor;
        button.tag = [@[@"mic", @"trash", @"eye.slash", @"xmark"] indexOfObject:item[0]];
        [button addTarget:self action:@selector(actionTapped:) forControlEvents:UIControlEventTouchUpInside];
        [actions addArrangedSubview:button];
    }
    UIScrollView *quickScroll = [UIScrollView new];
    quickScroll.showsHorizontalScrollIndicator = NO;
    quickScroll.hidden = YES;
    [controller.view addSubview:quickScroll];
    self.quickScroll = quickScroll;
    UIStackView *quickRow = [UIStackView new];
    quickRow.axis = UILayoutConstraintAxisHorizontal;
    quickRow.spacing = 6;
    [quickScroll addSubview:quickRow];
    self.quickRow = quickRow;
    window.interactiveViews = @[scroll, composer, actions, quickScroll];

    MiniSightChatEditorWindow *editorWindow = [[MiniSightChatEditorWindow alloc] initWithFrame:screen];
    editorWindow.windowLevel = UIWindowLevelAlert + 3.0;
    editorWindow.backgroundColor = UIColor.clearColor;
    editorWindow.opaque = NO;
    editorWindow.hidden = YES;
    UIViewController *editorController = [UIViewController new];
    editorController.view = [[UIView alloc] initWithFrame:screen];
    editorController.view.backgroundColor = UIColor.clearColor;
    editorWindow.rootViewController = editorController;
    UITextField *editor = [UITextField new];
    editor.borderStyle = UITextBorderStyleNone;
    editor.font = field.font;
    editor.textColor = field.textColor;
    editor.backgroundColor = UIColor.clearColor; // the bar blur is the visible surface
    editor.adjustsFontSizeToFitWidth = NO;
    editor.minimumFontSize = 11;
    editor.placeholder = field.placeholder;
    editor.returnKeyType = UIReturnKeySend;
    editor.delegate = self;
    [editor addTarget:self action:@selector(editorInputChanged) forControlEvents:UIControlEventEditingChanged];
    [editorController.view addSubview:editor];
    self.editorWindow = editorWindow;
    self.editorField = editor;
    editorWindow.editorField = editor;
    [field addGestureRecognizer:[[UITapGestureRecognizer alloc] initWithTarget:self action:@selector(activateEditor)]];
    [self updateAppearance];
    MSDiagEvent(@"chat", @"build", @"ok", @{ @"source": @"floating_bubbles" });
}

#pragma mark Presentation

+ (BOOL)showInWindowScene:(UIWindowScene *)scene {
    return [[self sharedPanel] showInWindowScene:scene];
}

- (BOOL)showInWindowScene:(UIWindowScene *)scene {
    NSCAssert([NSThread isMainThread], @"chat panel is main-thread only");
    if (!self.built) [self buildUI];
    if (!self.window || !self.editorWindow) return NO;
    UIWindow *hostWindow = self.anchorView.window;
    UIWindowScene *target = hostWindow.windowScene ?: scene;
    if (!hostWindow || hostWindow.hidden || !target || (scene && scene != target)) {
        MSDiagEvent(@"chat", @"show", @"failed", @{ @"reason": @"missing_host_scene" });
        return NO;
    }
    if (self.window.windowScene != target) self.window.windowScene = target;
    if (self.editorWindow.windowScene != target) self.editorWindow.windowScene = target;
    if (self.closing) {
        ++self.requestGeneration;
        [self endSendingUI];
        [self.ai cancel];
    }
    ++self.lifecycleGeneration;
    self.closing = NO;
    self.composerVisible = NO;
    self.visible = YES;
    [self updateAppearance];
    self.keyboardOverlap = 0;
    self.keyboardTop = 0;
    self.messagesDirty = YES;
    [self layoutForCurrentScreen];
    if (!self.visible) return NO;
    self.window.hidden = NO;
    self.editorWindow.hidden = !self.editorActive;
    [self observeKeyboard:YES];
    if (self.editorActive) {
        [self.editorWindow makeKeyWindow];
        [self.editorField becomeFirstResponder];
    }
    if (self.visibilityHandler) self.visibilityHandler(YES);
    MSDiagEvent(@"chat", @"show", @"ok", @{ @"generation": @(self.lifecycleGeneration), @"visible": @YES });
    return YES;
}

- (void)showLocalText:(NSString *)text inWindowScene:(UIWindowScene *)scene {
    NSCAssert([NSThread isMainThread], @"chat panel is main-thread only");
    if (!text.length) return;
    if (self.visible) {
        MSDiagEvent(@"bubble", @"skip", @"skipped", @{ @"reason": @"chat_already_visible" });
        return;
    }
    if (![self showInWindowScene:scene]) return;
    self.composerVisible = NO;
    [self appendMessage:text role:MiniSightChatRoleAssistant];
    NSUInteger generation = self.lifecycleGeneration;
    MSDiagEvent(@"bubble", @"show", @"ok", @{ @"source": @"app_local", @"chars": @(text.length) });
    NSTimeInterval dwell = 3.0 * [self scaleFor:@"dwell" fallback:1];
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(dwell * NSEC_PER_SEC)), dispatch_get_main_queue(), ^{
        if (self.visible && !self.composerVisible && !self.sending && self.lifecycleGeneration == generation) [self close];
    });
}

- (void)layoutEditorWindow {
    if (!self.window || !self.editorWindow || !self.inputField || !self.editorField) return;
    CGRect rect = [self.inputField convertRect:self.inputField.bounds toView:self.editorWindow];
    self.editorField.frame = rect;
}

- (void)activateEditor {
    NSCAssert([NSThread isMainThread], @"chat editor is main-thread only");
    if (!self.visible || !self.editorWindow || !self.editorField || self.editorActive) return;
    self.editorField.text = self.inputField.text;
    [self layoutEditorWindow];
    self.editorActive = YES;
    self.inputField.alpha = 0.01;
    self.editorWindow.hidden = NO;
    [self.editorWindow makeKeyWindow];
    BOOL accepted = [self.editorField becomeFirstResponder];
    MSDiagEvent(@"chat", @"editor", accepted ? @"ok" : @"failed", @{ @"reason": @"first_responder" });
    if (!accepted) { [self deactivateEditor]; [self appendNotice:@"键盘暂不可用，请重新点击输入条"]; }
}

- (void)deactivateEditorWithoutKey {
    if (!self.editorActive) return;
    self.inputField.text = self.editorField.text;
    self.inputField.alpha = 1.0;
    // Drop first responder so a hidden editor cannot keep the keyboard alive;
    // deliberately do not call resignKeyWindow on the teardown path.
    [self.editorField resignFirstResponder];
    self.editorActive = NO;
    self.editorWindow.hidden = YES;
}

- (void)deactivateEditor {
    if (!self.editorActive) return;
    self.inputField.text = self.editorField.text;
    self.inputField.alpha = 1.0;
    self.editorActive = NO;
    [self.editorField resignFirstResponder];
    [self.editorWindow resignKeyWindow];
    self.editorWindow.hidden = YES;
}

- (void)editorInputChanged {
    if (!self.visible || !self.editorActive) return;
    self.inputField.text = self.editorField.text;
    [self inputChanged];
}

- (void)hideWithoutKey {
    NSCAssert([NSThread isMainThread], @"chat panel is main-thread only");
    if (!self.built) return;
    BOOL wasVisible = self.visible;
    ++self.lifecycleGeneration;
    ++self.requestGeneration;
    self.visible = NO;
    self.closing = NO;
    [self observeKeyboard:NO];
    [self deactivateEditorWithoutKey];
    [self.ai cancel];
    [self endSendingUI];
    self.window.hidden = YES;
    self.editorWindow.hidden = YES;
    self.keyboardOverlap = 0;
    self.keyboardTop = 0;
    if (wasVisible && self.visibilityHandler) self.visibilityHandler(NO);
    if (wasVisible) MSDiagEvent(@"chat", @"close", @"ok", @{ @"reason": @"host_teardown" });
}

- (void)close {
    NSCAssert([NSThread isMainThread], @"chat panel is main-thread only");
    MSDiag(@"chat close visible=%d sending=%d generation=%lu", self.visible, self.sending,
           (unsigned long)self.requestGeneration);
    if (!self.visible || self.closing) return;
    self.visible = NO;
    self.closing = YES;
    ++self.requestGeneration;
    [self endSendingUI];
    NSUInteger generation = ++self.lifecycleGeneration;
    dispatch_async(dispatch_get_main_queue(), ^{
        [self performCloseForGeneration:generation];
    });
}

- (void)performCloseForGeneration:(NSUInteger)generation {
    NSCAssert([NSThread isMainThread], @"chat panel is main-thread only");
    if (generation != self.lifecycleGeneration || self.visible || !self.closing) return;
    [self.ai cancel];
    [self observeKeyboard:NO];
    [self deactivateEditor];
    self.window.hidden = YES;
    self.editorWindow.hidden = YES;
    self.keyboardOverlap = 0;
    self.closing = NO;
    self.keyboardTop = 0;
    if (self.visibilityHandler) self.visibilityHandler(NO);
    MSDiagEvent(@"chat", @"close", @"ok", @{ @"reason": @"user" });
}

- (void)hidePetFromMenu {
    if (self.hidePetHandler) self.hidePetHandler();
}

/// Direct voice: ask the App to listen. The plug-in never opens the keyboard
/// for this path; if the App cannot answer, fall back to keyboard dictation.
- (void)voiceTapped {
    if (self.sending) return;
    self.voiceWaiter = dispatch_block_create((dispatch_block_flags_t)0, ^{
        MSDiagEvent(@"voice", @"start", @"failed", @{ @"source": @"plugin", @"reason": @"no_app_reply" });
        [self activateEditor];
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, (int64_t)(0.9 * NSEC_PER_SEC)), dispatch_get_main_queue(), self.voiceWaiter);
    MSDiagEvent(@"voice", @"start", @"pending", @{ @"source": @"plugin", @"reason": @"request_app" });
    if (!MSBridgeWrite(self.containerPath, @"voice.json", @{@"action": @"start", @"generation": @(++self.voiceGeneration)}))
        MSDiagEvent(@"voice", @"start", @"failed", @{ @"source": @"plugin", @"reason": @"write_request" });
    MSBridgePost(@"com.openminis.minisight.voice");
}

- (void)voiceResultArrived {
    NSDictionary *payload = MSBridgeRead(self.containerPath, @"voice-result.json", 8192);
    NSString *text = [payload[@"text"] isKindOfClass:NSString.class] ? payload[@"text"] : @"";
    BOOL final = [payload[@"final"] boolValue];
    if (payload[@"reason"]) {
        MSDiagEvent(@"voice", @"finish", @"failed", @{ @"source": @"app", @"reason": payload[@"reason"] });
        if (!text.length) { [self appendNotice:@"语音没有结果，可改用键盘输入"]; }
    }
    [self voiceText:text final:final];
}

- (void)voiceTokenArrived {
    if (self.voiceWaiter) { dispatch_block_cancel(self.voiceWaiter); self.voiceWaiter = nil; }
    if (!self.visible || self.editorActive) return;
}

/// App pushes a partial or final transcript. Nothing auto-sends.
- (void)voiceText:(NSString *)text final:(BOOL)final {
    if (!self.visible || !text.length) return;
    if (self.voiceWaiter) { dispatch_block_cancel(self.voiceWaiter); self.voiceWaiter = nil; }
    self.inputField.text = text;
    [self editorInputChanged];
    if (final) {
        MSDiagEvent(@"voice", @"finish", @"ok", @{ @"source": @"app", @"chars": @(text.length) });
        [self inputChanged];
    }
}

- (BOOL)gestureRecognizer:(UIGestureRecognizer *)gesture shouldReceiveTouch:(UITouch *)touch {
    if (gesture == self.editorTap) {
        UIView *hit = [self.cardView hitTest:[touch locationInView:self.cardView] withEvent:nil];
        if (hit == self.micButton || hit == self.sendButton || hit == self.moreButton || hit == self.cancelButton) return NO;
    }
    return YES;
}

/// Second tap on the pet (or any bubble) reveals the bar.
- (void)revealComposerIfNeeded {
    if (self.composerVisible) return;
    self.composerVisible = YES;
    [self layoutForCurrentScreen];
    [self activateEditor];
    MSDiagEvent(@"chat", @"composer", @"ok", @{ @"source": @"pet_second_tap" });
}

- (void)revealComposer {
    self.composerVisible = YES;
    [self layoutForCurrentScreen];
    MSDiagEvent(@"chat", @"composer", @"ok", @{ @"source": @"bubble_tap", @"sending": @(self.sending) });
}

- (void)rebuildQuickRow {
    if (!self.quickRow) return;
    for (UIView *v in [self.quickRow.arrangedSubviews copy]) { [self.quickRow removeArrangedSubview:v]; [v removeFromSuperview]; }
    NSString *order = self.appearancePreferences[@"quickOrder"];
    NSDictionary *lines = self.appearancePreferences[@"quickLines"];
    NSArray *names = order.length ? [order componentsSeparatedByString:@","] : @[];
    NSDictionary *titles = @{@"greet": @"打招呼", @"wave": @"挥手", @"jump": @"跳一下",
                             @"pat": @"摸摸", @"walk": @"走一下"};
    for (NSString *key in names) {
        NSString *title = lines[key] ?: titles[key];
        if (!title.length) title = key;
        UIButton *b = [UIButton buttonWithType:UIButtonTypeSystem];
        [b setTitle:[title substringToIndex:MIN(title.length, 10)] forState:UIControlStateNormal];
        b.titleLabel.font = [UIFont systemFontOfSize:11];
        [b setTitleColor:UIColor.secondaryLabelColor forState:UIControlStateNormal];
        b.backgroundColor = MSChatColor([UIColor colorWithWhite:1 alpha:0.94], [UIColor colorWithWhite:0.18 alpha:0.94]);
        b.layer.cornerRadius = 12;
        b.contentEdgeInsets = UIEdgeInsetsMake(4, 10, 4, 10);
        b.accessibilityIdentifier = key;
        [b addTarget:self action:@selector(quickTapped:) forControlEvents:UIControlEventTouchUpInside];
        [self.quickRow addArrangedSubview:b];
    }
    self.quickScroll.hidden = names.count == 0;
}

- (void)quickTapped:(UIButton *)sender {
    NSString *key = sender.accessibilityIdentifier;
    if (!key.length) return;
    [MiniSightBlip playIfEnabled:[self.appearancePreferences[@"sound"] boolValue]];
    if (self.quickHandler) self.quickHandler(key);
    else {
        NSDictionary *lines = self.appearancePreferences[@"quickLines"];
        NSString *line = lines[key] ?: @"";
        if (line.length) [self showLocalText:line inWindowScene:self.window.windowScene];
    }
    MSDiagEvent(@"chat", @"apply", @"ok", @{ @"setting": @"minisight.quick.enabled", @"field": key });
}

- (void)toggleMenu {
    self.menuOpen = !self.menuOpen;
    [self.window.rootViewController.view bringSubviewToFront:self.actionBar];
    [self.window.rootViewController.view bringSubviewToFront:self.cardView];
    self.actionBar.hidden = !self.menuOpen;
    [self layoutForCurrentScreen];
    MSDiagEvent(@"chat", @"composer", @"ok", @{ @"source": @"menu_toggle", @"reason": self.menuOpen ? @"open" : @"closed" });
}

- (void)menuDismiss {
    if (!self.menuOpen) return;
    self.menuOpen = NO;
    self.actionBar.hidden = YES;
}

- (void)actionTapped:(UIButton *)sender {
    [self menuDismiss];
    switch (sender.tag) {
        case 0:
            [self activateEditor];
            MSDiagEvent(@"voice", @"entry", @"pending", @{ @"source": @"keyboard_dictation" });
            break;
        case 1: [self clearConversation]; break;
        case 2: [self hidePetFromMenu]; break;
        default: [self close]; break;
    }
}

- (void)composerPanned:(UIPanGestureRecognizer *)pan {
    UIView *window = self.window;
    if (!window || pan.state == UIGestureRecognizerStateBegan) {
        self.chatOffset = CGPointMake(
            [self.appearancePreferences[@"minisight.chat.dx"] doubleValue],
            [self.appearancePreferences[@"minisight.chat.dy"] doubleValue]);
    }
    CGPoint delta = [pan translationInView:window];
    self.chatOffset = CGPointMake(self.chatOffset.x + delta.x, self.chatOffset.y + delta.y);
    [pan setTranslation:CGPointZero inView:window];
    self.layingOut = NO;
    [self layoutForCurrentScreen];
    if (pan.state == UIGestureRecognizerStateEnded) {
        UserDefaults *defaults = [NSUserDefaults standardUserDefaults];
        [defaults setDouble:self.chatOffset.x forKey:@"minisight.chat.dx"];
        [defaults setDouble:self.chatOffset.y forKey:@"minisight.chat.dy"];
        MSDiagEvent(@"chat", @"layout", @"ok", @{ @"source": @"user_drag", @"x": @(self.chatOffset.x), @"y": @(self.chatOffset.y) });
    }
}

- (void)backgroundTapped {
    [self close];
}

#pragma mark Layout

- (UIWindowScene *)findScene {
    if (@available(iOS 13.0, *)) {
        for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
            if ([scene isKindOfClass:UIWindowScene.class] &&
                scene.activationState == UISceneActivationStateForegroundActive) {
                return (UIWindowScene *)scene;
            }
        }
        for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
            if ([scene isKindOfClass:UIWindowScene.class]) return (UIWindowScene *)scene;
        }
    }
    return nil;
}

- (void)refreshAnchorLocation {
    // Geometry callbacks must never instantiate an overlay or resurrect one.
    if (!self.visible || !self.built) return;
    UIView *anchor = self.anchorView;
    if (!anchor) return;
    CGRect now = [anchor convertRect:anchor.bounds toView:self.window];
    CGFloat dx = fabs(CGRectGetMidX(now) - CGRectGetMidX(self.lastAnchorRect));
    CGFloat dy = fabs(CGRectGetMidY(now) - CGRectGetMidY(self.lastAnchorRect));
    CFTimeInterval t = CACurrentMediaTime();
    // Gravity sway is continuous; 3pt / 120ms hysteresis keeps the bar still
    // enough to tap while still following a real drag.
    if (dy < 3 && dx < 3) return;
    if (t - self.lastAnchorTime < 0.12) return;
    self.lastAnchorRect = now;
    self.lastAnchorTime = t;
    [self layoutForCurrentScreen];
}

- (void)layoutForCurrentScreen {
    if (!self.visible || !self.window || self.layingOut) return;
    UIView *anchor = self.anchorView;
    UIWindow *source = anchor.window;
    if (!anchor || !source || source.hidden) {
        MSDiagEvent(@"chat", @"layout", @"skipped", @{ @"reason": @"missing_anchor" });
        [self hideWithoutKey];
        return;
    }
    if (source.windowScene != self.window.windowScene) {
        MSDiagEvent(@"chat", @"layout", @"skipped", @{ @"reason": @"scene_mismatch" });
        [self hideWithoutKey];
        return;
    }
    self.layingOut = YES;
    CGRect screen = MSChatScreenRect(self.window.windowScene);
    self.window.frame = screen;
    self.editorWindow.frame = screen;
    self.window.rootViewController.view.frame = self.window.bounds;
    self.editorWindow.rootViewController.view.frame = self.editorWindow.bounds;
    CGRect pet = [anchor convertRect:anchor.bounds toView:self.window];
    self.lastAnchorRect = pet;
    self.lastAnchorTime = CACurrentMediaTime();
    UIEdgeInsets insets = source.safeAreaInsets;
    CGRect safe = UIEdgeInsetsInsetRect(self.window.bounds, UIEdgeInsetsMake(MAX(8, insets.top + 6), MAX(10, insets.left + 8), MAX(8, insets.bottom + 6), MAX(10, insets.right + 8)));
    BOOL messagesChanged = self.messagesDirty;
    CGFloat maxWidth = MIN(210, MAX(1, safe.size.width));
    if (fabs(self.measuredWidth - maxWidth) > 0.5 || self.messagesDirty) {
        self.measuredWidth = maxWidth;
        self.messagesDirty = NO;
        self.messageWidthConstraint.constant = maxWidth;
        for (MiniSightChatBubble *row in self.rows) row.label.preferredMaxLayoutWidth = MAX(1, maxWidth - 24);
        [self.messageStack setNeedsLayout];
        CGFloat content = 0;
        for (UIView *row in self.rows) {
            CGFloat rowHeight = [(MiniSightChatBubble *)row systemLayoutSizeFittingSize:CGSizeMake(maxWidth, UILayoutFittingCompressedSize.height) withHorizontalFittingPriority:UILayoutPriorityRequired verticalFittingPriority:UILayoutPriorityFittingSizeLevel].height;
            content += MAX(20, rowHeight);
        }
        content += MAX(0, self.rows.count - 1) * 6 + 8;
        self.measuredMessageHeight = MIN(content, [self configuredHeight]);
    }
    CGFloat barHeight = 30;
    CGFloat barWidth = MIN(274 * [self scaleFor:@"bubbleScale" fallback:1], MAX(200, safe.size.width - 16));
    CGFloat centerX = CGRectGetMidX(pet) + self.chatOffset.x;
    CGFloat barX = MIN(MAX(CGRectGetMinX(safe), centerX - barWidth * .5), CGRectGetMaxX(safe) - barWidth);
    CGFloat keyboardLimit = self.keyboardTop > 0 ? self.keyboardTop - 6 : CGRectGetMaxY(safe);
    CGFloat barY = CGRectGetMinY(pet) - 8 - barHeight + self.chatOffset.y;
    // Only flip under the feet when the head really has no 44pt; otherwise keep
    // the bar on one side so the text never appears to hop between sides.
    if (barY < CGRectGetMinY(safe) && CGRectGetMinY(pet) < CGRectGetMinY(safe) + 44)
        barY = CGRectGetMaxY(pet) + 8;
    barY = MIN(MAX(CGRectGetMinY(safe), barY),
               MAX(CGRectGetMinY(safe), keyboardLimit - barHeight));
    MSChatFloatingFrames frames;
    memset(&frames, 0, sizeof frames);
    frames.composer = (MSRect){barX, barY, barWidth, barHeight};

    // Bubbles share the same anchor, directly above (or below when cramped).
    CGFloat bubbleWidth = MIN(210 * [self scaleFor:@"bubbleScale" fallback:1], safe.size.width);
    CGFloat bubbleX = MIN(MAX(CGRectGetMinX(safe), centerX - bubbleWidth * .5), CGRectGetMaxX(safe) - bubbleWidth);
    CGFloat bubbleBottom = barY - 6;
    BOOL below = bubbleBottom - self.measuredMessageHeight < CGRectGetMinY(safe);
    CGFloat bubbleY = below ? CGRectGetMaxY(pet) + 8 : bubbleBottom - self.measuredMessageHeight;
    bubbleY = MIN(MAX(CGRectGetMinY(safe), bubbleY), MAX(CGRectGetMinY(safe), keyboardLimit - self.measuredMessageHeight));
    frames.messages = (MSRect){bubbleX, bubbleY, bubbleWidth, self.measuredMessageHeight};
    frames.placedBelow = below ? 1 : 0;
    self.actionBar.hidden = !self.menuOpen;
    if (messagesChanged || self.lastLayoutBelow != (BOOL)frames.placedBelow) {
        // Keep the newest reply nearest the pet even when the group is below it.
        NSArray *ordered = frames.placedBelow ? self.rows.reverseObjectEnumerator.allObjects : self.rows;
        for (UIView *row in [self.messageStack.arrangedSubviews copy]) [self.messageStack removeArrangedSubview:row];
        for (UIView *row in ordered) [self.messageStack addArrangedSubview:row];
    }
    self.scrollView.frame = CGRectMake(frames.messages.x, frames.messages.y, frames.messages.w, frames.messages.h);
    self.scrollView.hidden = self.rows.count == 0 || frames.messages.h < 1;
    self.scrollView.frame = CGRectInset(self.scrollView.frame, 0, 0);
    self.cardView.hidden = !self.composerVisible;
    self.cardView.frame = CGRectMake(frames.composer.x, frames.composer.y, frames.composer.w, frames.composer.h);
    self.cardBlurView.frame = self.cardView.bounds;
    self.cardTintView.frame = self.cardBlurView.contentView.bounds;
    CGFloat width = self.cardView.bounds.size.width;
    CGFloat height = self.cardView.bounds.size.height;
    self.moreButton.frame = CGRectMake(0, 0, 34, height);
    self.micButton.frame = CGRectMake(MAX(0, width - 62), 0, 28, height);
    self.micButton.hidden = self.sending || width < 170;
    self.sendButton.frame = CGRectMake(MAX(0, width - 34), MAX(0, (height - 24) / 2), 30, MIN(24, height));
    self.cancelButton.frame = self.sendButton.frame;
    self.inputField.frame = CGRectMake(30, 3, MAX(1, width - 96), MAX(1, height - 6));
    self.inputField.hidden = width < 100;
    self.moreButton.hidden = width < 150;
    CGFloat quickH = (self.quickScroll && !self.quickScroll.hidden) ? 28 : 0;
    if (quickH > 0) {
        self.quickScroll.frame = CGRectMake(CGRectGetMinX(self.cardView), CGRectGetMinY(self.cardView) - 34,
                                            MIN(width, self.quickRow.intrinsicContentSize.width), 28);
        self.quickRow.frame = CGRectMake(0, 0, self.quickRow.intrinsicContentSize.width, 28);
    }
    if (self.menuOpen) {
        self.actionBar.frame = CGRectMake(CGRectGetMinX(self.cardView),
                                          MAX(CGRectGetMinY(safe), CGRectGetMinY(self.cardView) - 36),
                                          width, 30);
    }
    [self.scrollView layoutIfNeeded];
    MiniSightChatBubble *latest = (MiniSightChatBubble *)self.rows.lastObject;
    for (MiniSightChatBubble *row in self.rows) row.petTail = row == latest && !row.userMessage;
    if (latest.petTail) {
        CGPoint point = [self.window convertPoint:CGPointMake(CGRectGetMidX(pet), CGRectGetMinY(pet)) toView:latest];
        latest.tailX = point.x;
        latest.tailAbove = frames.placedBelow != 0;
    }
    [self layoutEditorWindow];
    // Do not measure/log glyphs on every motion sample. Only branch changes,
    // keyboard changes or a one-second position summary reach diagnostics.
    CFTimeInterval now = CACurrentMediaTime();
    BOOL branchChanged = self.lastLayoutBelow != (BOOL)frames.placedBelow || self.lastKeyboardTop != self.keyboardTop;
    if (self.layoutLogTime == 0 || branchChanged || now - self.layoutLogTime > 1.0) {
        self.layoutLogTime = now;
        self.lastLayoutBelow = frames.placedBelow != 0;
        self.lastKeyboardTop = self.keyboardTop;
        MSDiagEvent(@"chat", @"layout", @"ok", @{ @"below": @(frames.placedBelow), @"keyboard": @(self.keyboardTop > 0), @"count": @(self.rows.count), @"x": @(frames.composer.x), @"y": @(frames.composer.y), @"w": @(frames.composer.w), @"h": @(frames.composer.h) });
    }
    self.lastLayoutBelow = frames.placedBelow != 0;
    self.layingOut = NO;
}

- (void)updateCardBottomAnimated:(BOOL)animated {
    if (!animated) { [self layoutForCurrentScreen]; return; }
    [UIView animateWithDuration:0.24 delay:0 options:UIViewAnimationOptionBeginFromCurrentState | UIViewAnimationOptionAllowUserInteraction animations:^{ [self layoutForCurrentScreen]; } completion:nil];
}

#pragma mark Keyboard

- (void)observeKeyboard:(BOOL)observe {
    NSNotificationCenter *center = NSNotificationCenter.defaultCenter;
    [center removeObserver:self name:UIKeyboardWillChangeFrameNotification object:nil];
    [center removeObserver:self name:UIKeyboardWillHideNotification object:nil];
    [center removeObserver:self name:UIDeviceOrientationDidChangeNotification object:nil];
    [center removeObserver:self name:UIApplicationDidChangeStatusBarOrientationNotification object:nil];
    if (!observe) return;
    [center addObserver:self selector:@selector(keyboardWillChangeFrame:)
                   name:UIKeyboardWillChangeFrameNotification object:nil];
    [center addObserver:self selector:@selector(keyboardWillHide:)
                   name:UIKeyboardWillHideNotification object:nil];
    [center addObserver:self selector:@selector(orientationChanged)
                   name:UIDeviceOrientationDidChangeNotification object:nil];
    [center addObserver:self selector:@selector(orientationChanged)
                   name:UIApplicationDidChangeStatusBarOrientationNotification object:nil];
    CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(),
        (__bridge const void *)self, MiniSightVoiceResult,
        CFSTR("com.openminis.minisight.voice.result"), NULL,
        CFNotificationSuspensionBehaviorDeliverImmediately);
}

- (void)keyboardWillChangeFrame:(NSNotification *)note {
    if (!self.visible || !self.editorActive || !self.window) return;
    CGRect end = [note.userInfo[UIKeyboardFrameEndUserInfoKey] CGRectValue];
    CGRect local = [self.window convertRect:end fromWindow:nil];
    CGFloat overlap = MAX(0.0, CGRectGetMaxY(self.window.bounds) - CGRectGetMinY(local));
    if (CGRectGetMinY(local) >= CGRectGetMaxY(self.window.bounds) - 0.5) overlap = 0.0;
    self.keyboardOverlap = overlap;
    CGRect intersection = CGRectIntersection(self.window.bounds, local);
    self.keyboardTop = CGRectIsNull(intersection) || CGRectIsEmpty(intersection) ? 0 : CGRectGetMinY(intersection);
    MSDiagEvent(@"chat", @"keyboard", @"ok", @{ @"keyboard": @(self.keyboardTop > 0) });
    [self updateCardBottomAnimated:YES];
}

- (void)keyboardWillHide:(NSNotification *)note {
    if (!self.visible) return;
    self.keyboardOverlap = 0;
    self.keyboardTop = 0;
    [self updateCardBottomAnimated:YES];
}

- (void)orientationChanged {
    NSUInteger generation = self.lifecycleGeneration;
    dispatch_async(dispatch_get_main_queue(), ^{
        if (generation == self.lifecycleGeneration && self.visible) [self layoutForCurrentScreen];
    });
}

#pragma mark Messages

- (void)appendMessage:(NSString *)text role:(MiniSightChatRole)role {
    if (!text.length || !self.messageStack) return;
    MiniSightChatBubble *bubble = [[MiniSightChatBubble alloc] initWithText:text user:role == MiniSightChatRoleUser];
    CGFloat textScale = [self scaleFor:@"textScale" fallback:1];
    if (fabs(textScale - 1) > 0.01) bubble.label.font = [UIFont systemFontOfSize:12.5 * textScale];
    if (role == MiniSightChatRoleNotice) bubble.label.textColor = UIColor.secondaryLabelColor;
    NSLayoutConstraint *width = [bubble.widthAnchor constraintLessThanOrEqualToAnchor:self.messageStack.widthAnchor];
    [self.messageStack addArrangedSubview:bubble];
    width.active = YES; // Activate only after a common ancestor exists.
    [self.rows addObject:bubble];
    self.messagesDirty = YES;
    [self trimMessages];
    [self layoutForCurrentScreen];
    [self scrollToBottom];
}

- (void)appendNotice:(NSString *)text {
    [self appendMessage:text role:MiniSightChatRoleNotice];
}

- (void)appendError:(NSString *)text {
    [self appendMessage:[@"⚠︎ " stringByAppendingString:text] role:MiniSightChatRoleAssistant];
}

- (void)trimMessages {
    while (self.rows.count > MIN((NSUInteger)kMSChatMaxMessages, (NSUInteger)4)) {
        UIView *oldest = self.rows.firstObject;
        [self.rows removeObjectAtIndex:0];
        [self.messageStack removeArrangedSubview:oldest];
        [oldest removeFromSuperview];
    }
}

- (void)scrollToBottom {
    [self.scrollView layoutIfNeeded];
    CGFloat bottom = MAX(0.0, self.scrollView.contentSize.height -
                         self.scrollView.bounds.size.height + self.scrollView.contentInset.bottom);
    [self.scrollView setContentOffset:CGPointMake(0, self.lastLayoutBelow ? 0 : bottom) animated:YES];
}

#pragma mark Composer

- (void)inputChanged {
    BOOL hasText = [self.inputField.text stringByTrimmingCharactersInSet:
        [NSCharacterSet whitespaceAndNewlineCharacterSet]].length > 0;
    self.sendButton.enabled = hasText && !self.sending;
    self.sendButton.alpha = self.sendButton.enabled ? 1.0 : 0.45;
    self.sendButton.hidden = self.sending;
}

- (BOOL)textFieldShouldReturn:(UITextField *)textField {
    if ([self.appearancePreferences[@"returnKey"] isEqualToString:@"newline"]) {
        UITextField *target = textField == self.editorField ? self.editorField : self.inputField;
        target.text = [target.text stringByAppendingString:@"\n"];
        [self editorInputChanged];
        return NO;
    }
    if (textField == self.editorField) self.inputField.text = self.editorField.text;
    [self sendTapped];
    return NO;
}

- (void)sendTapped {
    NSCAssert([NSThread isMainThread], @"chat panel is main-thread only");
    MSDiag(@"chat send-entry visible=%d sending=%d hasClient=%d", self.visible, self.sending, self.ai != nil);
    if (self.sending || !self.visible) {
        MSDiagEvent(@"chat", @"skip", @"skipped", @{ @"reason": self.sending ? @"busy" : @"not_visible" });
        return;
    }
    if (!self.ai) self.ai = [[MiniSightAI alloc] initWithContainer:self.containerPath];
    if (!self.ai) {
        [self appendError:@"AI 客户端暂不可用，请重新打开聊天"];
        return;
    }
    // Repair a stale client/UI mismatch before accepting a new user turn.
    if (self.ai.isSending) {
        ++self.requestGeneration;
        [self.ai cancel];
    }
    UITextField *sourceField = self.editorActive ? self.editorField : self.inputField;
    NSString *text = [sourceField.text stringByTrimmingCharactersInSet:
        [NSCharacterSet whitespaceAndNewlineCharacterSet]];
    if (!text.length) {
        MSDiagEvent(@"chat", @"skip", @"skipped", @{ @"reason": @"empty_input" });
        return;
    }
    NSString *requestID = self.ai.nextRequestID;
    MSDiagEvent(@"chat", @"send", @"pending", @{ @"request": requestID, @"generation": @(self.requestGeneration + 1), @"chars": @(text.length) });
    [self deactivateEditor];

    [self appendMessage:text role:MiniSightChatRoleUser];
    self.inputField.text = @"";
    self.editorField.text = @"";
    [self beginSendingUI];
    NSUInteger generation = ++self.requestGeneration;
    self.ai.containerPath = self.containerPath;
    __weak typeof(self) weakSelf = self;
    [self.ai sendUserText:text completion:^(MiniSightAIReply *reply) {
        MiniSightChatPanel *strongSelf = weakSelf;
        MSDiag(@"chat receive request=%@ ui_generation=%lu hasPanel=%d current=%d",
               reply.requestID, (unsigned long)generation, strongSelf != nil,
               strongSelf && generation == strongSelf.requestGeneration);
        if (!strongSelf || generation != strongSelf.requestGeneration) {
            MSDiagEvent(@"chat", @"receive", @"skipped", @{ @"request": reply.requestID, @"reason": @"stale_generation" });
            return;
        }
        [strongSelf handleReply:reply];
    }];
}

- (void)beginSendingUI {
    self.sending = YES;
    self.composerVisible = NO;
    self.sendButton.enabled = NO;
    self.sendButton.alpha = 0.45;
    self.cancelButton.hidden = NO;
    self.sendButton.hidden = YES;
    [self appendNotice:@"⋯"];
    self.pendingBubble = (MiniSightChatBubble *)self.rows.lastObject;
}

- (void)endSendingUI {
    self.sending = NO;
    self.cancelButton.hidden = YES;
    if (self.pendingBubble) {
        [self.messageStack removeArrangedSubview:self.pendingBubble];
        [self.rows removeObject:self.pendingBubble];
        [self.pendingBubble removeFromSuperview];
        self.pendingBubble = nil;
        self.messagesDirty = YES;
    }
    [self layoutForCurrentScreen];
    [self inputChanged];
}

/// The model may end a reply with [[ms:{"petSize":108,...}]]. Only whitelisted
/// keys apply, and only when that permission is granted; otherwise the bubble
/// says it is waiting for consent.
- (NSString *)applyAdjustmentsFrom:(NSString *)raw {
    NSRange open = [raw rangeOfString:@"[[ms:"];
    NSRange close = [raw rangeOfString:@"]]" options:NSBackwardsSearch];
    if (open.location == NSNotFound || close.location == NSNotFound || close.location < open.location) return raw;
    NSString *json = [raw substringWithRange:NSMakeRange(open.location + 5, close.location - open.location - 5)];
    NSDictionary *object = [NSJSONSerialization JSONObjectWithData:[json dataUsingEncoding:NSUTF8StringEncoding] options:0 error:NULL];
    if (![object isKindOfClass:NSDictionary.class]) return raw;
    NSDictionary *map = @{@"petSize": @"minisight.petSize", @"bubbleScale": @"minisight.dialogue.scale",
                          @"textScale": @"minisight.dialogue.textScale", @"darkMode": @"minisight.darkMode",
                          @"sound": @"minisight.petSound", @"nickname": @"minisight.ai.nickname",
                          @"tint": @"minisight.pet.tint"};
    NSDictionary *needs = @{@"petSize": @"petSize", @"bubbleScale": @"bubbleScale",
                            @"textScale": @"textScale", @"darkMode": @"darkMode",
                            @"sound": @"sound", @"nickname": @"nickname", @"tint": @"appearance"};
    NSString *allowed = self.appearancePreferences[@"aiPermissions"];
    BOOL allAllowed = allowed == nil;
    NSArray *granted = [allowed isKindOfClass:NSString.class] ? [allowed componentsSeparatedByString:@","] : @[];
    NSMutableArray *applied = [NSMutableArray array];
    for (NSString *key in object) {
        NSString *defaultKey = map[key];
        if (!defaultKey) continue;
        BOOL permitted = allAllowed || [granted containsObject:needs[key] ?: key];
        if (!permitted) { [applied addObject:[NSString stringWithFormat:@"%@ 待允许", key]]; continue; }
        [[NSUserDefaults standardUserDefaults] set:object[key] forKey:defaultKey];
        [applied addObject:key];
    }
    CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
        CFNotificationName("com.openminis.minisight.settings" as CFString), nil, nil, true);
    MSDiagEvent(@"settings", @"apply", @"ok", @{ @"setting": @"ai_adjust", @"count": @(applied.count), @"reason": @"model_request" });
    NSString *clean = [[raw substringToIndex:open.location] stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    return clean.length ? clean : raw;
}

- (void)speakIfEnabled:(NSString *)text {
    if (![self.appearancePreferences[@"voiceReply"] boolValue] || !text.length) return;
    AVSpeechUtterance *u = [AVSpeechUtterance speechUtteranceWithString:[text substringToIndex:MIN(text.length, 160)]];
    u.voice = [AVSpeechSynthesisVoice voiceWithLanguage:@"zh-CN"];
    u.rate = 0.5;
    [[AVSpeechSynthesizer new] speakUtterance:u];
    MSDiagEvent(@"voice", @"apply", @"ok", @{ @"source": @"plugin", @"setting": @"minisight.voice.reply" });
}

- (void)cancelSend {
    if (!self.sending) return;
    MSDiagEvent(@"chat", @"cancel", @"cancelled", @{ @"generation": @(self.requestGeneration), @"reason": @"user" });
    MSDiag(@"chat cancel generation=%lu", (unsigned long)self.requestGeneration);
    [self endSendingUI];
    ++self.requestGeneration;
    [self.ai cancel];
    [self appendNotice:@"已取消"];
}

- (void)handleReply:(MiniSightAIReply *)reply {
    NSCAssert([NSThread isMainThread], @"chat panel is main-thread only");
    MSDiag(@"chat handle request=%@ visible=%d sending=%d success=%d issue=%ld",
           reply.requestID, self.visible, self.sending, reply.isSuccess, (long)reply.issue);
    if (!self.visible || !self.sending) {
        MSDiagEvent(@"chat", @"reply", @"skipped", @{ @"request": reply.requestID, @"reason": @"not_visible_or_sending" });
        return;
    }
    MSDiagEvent(@"chat", @"reply", reply.isSuccess ? @"ok" : @"failed", @{ @"request": reply.requestID ?: @"none", @"issue": @(reply.issue), @"chars": @(reply.text.length) });
    [self endSendingUI];
    if (reply.isSuccess) {
        NSString *visible = [self applyAdjustmentsFrom:reply.text];
        [self appendMessage:visible role:MiniSightChatRoleAssistant];
        [self speakIfEnabled:visible];
        MSDiag(@"chat display request=%@ kind=answer chars=%lu rows=%lu", reply.requestID,
               (unsigned long)reply.text.length, (unsigned long)self.rows.count);
        BOOL attached = self.visible && !self.window.hidden && !self.scrollView.hidden && self.scrollView.bounds.size.height > 1;
        MSDiagEvent(@"chat", @"display", attached ? @"ok" : @"skipped", @{ @"request": reply.requestID ?: @"none", @"count": @(self.rows.count), @"reason": attached ? @"view_attached" : @"no_visible_space" });
        if (self.replyHandler) self.replyHandler(reply.text);
        return;
    }
    if (reply.issue == MiniSightAIIssueCancelled) {
        [self appendNotice:reply.displayText];
        MSDiagEvent(@"chat", @"display", @"cancelled", @{ @"request": reply.requestID, @"issue": @(reply.issue) });
        MSDiag(@"chat display request=%@ kind=cancelled", reply.requestID);
        return;
    }
    [self appendError:reply.displayText];
    MSDiagEvent(@"chat", @"display", @"failed", @{ @"request": reply.requestID ?: @"none", @"issue": @(reply.issue) });
    MSDiag(@"chat display request=%@ kind=error issue=%ld", reply.requestID, (long)reply.issue);
    if (self.errorHandler) self.errorHandler(reply.displayText, reply.issue);
}

#pragma mark Clear

- (void)clearConversation {
    if (self.sending) {
        ++self.requestGeneration;
        [self endSendingUI];
        [self.ai cancel];
    }
    [self.ai resetConversation];
    for (UIView *row in self.rows) { [self.messageStack removeArrangedSubview:row]; [row removeFromSuperview]; }
    self.messagesDirty = YES;
    MSDiagEvent(@"chat", @"configure", @"ok", @{ @"reason": @"clear_conversation" });
    [self.rows removeAllObjects];
    [self appendNotice:@"对话已清空，重新开始吧"];
}

- (void)dealloc {
    [NSNotificationCenter.defaultCenter removeObserver:self];
}

@end
