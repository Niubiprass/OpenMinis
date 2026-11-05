// MiniSight multi-turn AI client.
//
// Reads the same App-written Documents/MiniSight/ai.json as the 0.3.5 speak
// line (url / key / model). The key never leaves this class except as the
// Authorization header, and is never logged.
//
// Every method is main-thread only. Each accepted request delivers at most
// one completion on the main queue, including cancellation, configuration
// failure, or a vanished/replaced App container. Duplicate sends are ignored.
// There is deliberately no streaming: one bounded response, one reply.
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
/// Random client nonce plus generation; metadata only, never contains prompts or credentials.
@property (nonatomic, readonly, copy) NSString *requestID;
/// 429 Retry-After in seconds (integer / HTTP-date; default 30, cap 300).
/// Zero for non-429 results. Informational only: the client never auto-retries.
@property (nonatomic, readonly) NSTimeInterval retryAfterSeconds;
@property (nonatomic, readonly, getter=isSuccess) BOOL success;
@end

@interface MiniSightAI : NSObject
+ (instancetype)new NS_UNAVAILABLE;
- (instancetype)init NS_UNAVAILABLE;

/// `container` is the Minis App container, i.e. the parent of Documents/.
- (instancetype)initWithContainer:(nullable NSString *)container
    NS_SWIFT_NAME(init(container:)) NS_DESIGNATED_INITIALIZER;

@property (nonatomic, copy, nullable) NSString *containerPath;
/// Explicit persona override. Nil reads ai.json's optional system_prompt;
/// blank uses the built-in prompt. Request prompts are capped at 2000 composed characters.
@property (nonatomic, copy, nullable) NSString *systemPrompt;

@property (nonatomic, readonly, getter=isSending) BOOL sending;
/// Number of stored messages incl. the system prompt (for diagnostics/tests).
@property (nonatomic, readonly) NSUInteger messageCount;
/// Main-thread metadata for correlating UI entry before a synchronous preflight failure.
@property (nonatomic, readonly, copy) NSString *nextRequestID;

/// Appends the user turn and starts one chat/completions request (2048 tokens).
/// Chat and Settings tests use this same non-streaming path.
/// While a request is in flight the call is ignored (no duplicate request).
/// An accepted call finishes with a reply, including on empty input.
- (void)sendUserText:(NSString *)text
          completion:(void (^)(MiniSightAIReply *reply))completion
    NS_SWIFT_NAME(send(_:completion:));

/// Cancels the in-flight request and answers it with MiniSightAIIssueCancelled.
- (void)cancel;

/// Forgets every turn, keeping only the system prompt.
- (void)resetConversation;
@end

NS_ASSUME_NONNULL_END
#endif
