// MiniSight chat panel: a self-contained, key-capable overlay window.
//
// It owns its own UIWindow (MiniSightWindow stays non-key), builds every view
// from UIKit only, and reports replies/errors through host callbacks without
// touching the existing pet bubble. All methods are main-thread only.
#ifndef MINISIGHT_CHAT_PANEL_H
#define MINISIGHT_CHAT_PANEL_H

#import <UIKit/UIKit.h>
#import "MiniSightAI.h"

NS_ASSUME_NONNULL_BEGIN

@interface MiniSightChatPanel : NSObject
+ (instancetype)new NS_UNAVAILABLE;
- (instancetype)init NS_UNAVAILABLE;

+ (instancetype)sharedPanel;
/// Returns nil unless sharedPanel was already created by an explicit chat open.
+ (nullable instancetype)existingPanel;

/// Minis App container; required before the built-in client can read ai.json.
@property (nonatomic, copy, nullable) NSString *containerPath;
/// Shared MiniSight AppStorage appearance snapshot (bubble height/theme/tint).
@property (nonatomic, copy) NSDictionary<NSString *, id> *appearancePreferences;
/// Actual pet/pill view. Weak: geometry updates never retain or recreate a host.
@property (nonatomic, weak, nullable) UIView *anchorView;
/// Relayouts only an already-visible presentation; never builds or opens UI.
- (void)refreshAnchorLocation;

@property (nonatomic, readonly, getter=isVisible) BOOL visible;
@property (nonatomic, readonly, getter=isSending) BOOL sending;

/// Observation only: the panel already appended the reply/error itself.
@property (nonatomic, copy, nullable) void (^replyHandler)(NSString *text);
@property (nonatomic, copy, nullable) void (^errorHandler)(NSString *displayText, MiniSightAIIssue issue);
@property (nonatomic, copy, nullable) void (^visibilityHandler)(BOOL visible);
/// Invoked by the chat menu to hide the pet/indicator through the host lifecycle.
@property (nonatomic, copy, nullable) void (^hidePetHandler)(void);

/// Shows (or re-keys) the panel. Returns NO only when no window scene exists.
+ (BOOL)showInWindowScene:(nullable UIWindowScene *)scene;
- (BOOL)showInWindowScene:(nullable UIWindowScene *)scene;

/// Local-only speech/status; never sends a network request or steals an editor.
- (void)showLocalText:(NSString *)text inWindowScene:(nullable UIWindowScene *)scene
    NS_SWIFT_NAME(showLocalText(_:in:));

/// Cancels an in-flight request, resigns key, hides the window.
- (void)close;
/// Hides without key-window transitions for host teardown paths.
- (void)hideWithoutKey;
/// Cancels an in-flight request and forgets the whole conversation.
- (void)clearConversation;
@end

NS_ASSUME_NONNULL_END
#endif
