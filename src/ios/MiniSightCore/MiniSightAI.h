// MiniSight multi-turn AI client.
//
// Reads the same App-written Documents/MiniSight/ai.json as the 0.3.5 speak
// line (url / key / model). The key never leaves this class except as the
// Authorization header, and is never logged.
//
// Every method is main-thread only. Completions are delivered on the main
// queue and are dropped when the client was cancelled, superseded, or its App
// container went away. There is deliberately no streaming: one request, one
// reply, so the panel stays maintainable.
#ifndef MINISIGHT_AI_H
#define MINISIGHT_AI_H

#import <Foundation/Foundation.h>
#import "tools/chat/ChatCore.h"

NS_ASSUME_NONNULL_BEGIN

typedef NS_ENUM(NSInteger, MiniSightAIIssue) {
    MiniSightAIIssueNone = MSChatIssueNone,
    MiniSightAIIssueConfig = MSChatIssueConfig,
    MiniSightAIIssueURL = MSChatIssueURL,
    MiniSightAIIssueTimeout = MSChatIssueTimeout,
    MiniSightAIIssueNetwork = MSChatIssueNetwork,
    MiniSightAIIssueHTTP = MSChatIssueHTTP,
    MiniSightAIIssueEmpty = MSChatIssueEmpty,
    MiniSightAIIssueCancelled = MSChatIssueCancelled
};

/// One finished exchange result. `displayText` is always a Chinese sentence
/// suitable for a bubble; `text` is the model reply for a success.
@interface MiniSightAIReply : NSObject
@property (nonatomic, readonly) MiniSightAIIssue issue;
@property (nonatomic, readonly) long status;
@property (nonatomic, readonly, copy) NSString *text;
@property (nonatomic, readonly, copy) NSString *displayText;
@property (nonatomic, readonly, getter=isSuccess) BOOL success;
@end

@interface MiniSightAI : NSObject
+ (instancetype)new NS_UNAVAILABLE;
- (instancetype)init NS_UNAVAILABLE;

/// `container` is the Minis App container, i.e. the parent of Documents/.
- (instancetype)initWithContainer:(nullable NSString *)container NS_DESIGNATED_INITIALIZER;

@property (nonatomic, copy, nullable) NSString *containerPath;
/// Replaces the system persona while preserving the existing conversation turns.
@property (nonatomic, copy) NSString *systemPrompt;

@property (nonatomic, readonly, getter=isSending) BOOL sending;
/// Number of stored messages incl. the system prompt (for diagnostics/tests).
@property (nonatomic, readonly) NSUInteger messageCount;

/// Appends the user turn and starts one chat/completions request.
/// While a request is in flight the call is ignored (no duplicate request).
/// A completed call always finishes with a reply, including on empty input.
- (void)sendUserText:(NSString *)text
          completion:(void (^)(MiniSightAIReply *reply))completion;

/// Cancels the in-flight request and answers it with MiniSightAIIssueCancelled.
- (void)cancel;

/// Forgets every turn, keeping only the system prompt.
- (void)resetConversation;
@end

NS_ASSUME_NONNULL_END
#endif
