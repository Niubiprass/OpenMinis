#import "MiniSightAI.h"
#import "MiniSightLog.h"
#import "MiniSightBridgeIO.h"

#import <UIKit/UIKit.h>

static NSString *const kMiniSightAISystemPrompt =
    @"你是 iPhone 桌宠 MiniSight，用简洁、自然的中文回答；不确定就直说，不要编造。";
static const NSTimeInterval kMiniSightAITimeout = 30.0;
static const NSInteger kMiniSightAIMaxTokens = 512;
static const NSUInteger kMiniSightAIMaxJSONDepth = 10;
static const unsigned long long kMiniSightAIMaxConfigBytes = 64 * 1024;
static const NSUInteger kMiniSightAIMaxResponseBytes = 2 * 1024 * 1024;

#pragma mark - Reply

@interface MiniSightAIReply ()
@property (nonatomic, readwrite) MiniSightAIIssue issue;
@property (nonatomic, readwrite) long status;
@property (nonatomic, copy, readwrite) NSString *text;
@property (nonatomic, copy, readwrite) NSString *displayText;
@end

@implementation MiniSightAIReply
- (BOOL)isSuccess { return self.issue == MiniSightAIIssueNone && self.text.length > 0; }
@end

#pragma mark - JSON bridge

/// NSJSONSerialization result -> ChatCore value tree. Shape is all the parser
/// needs; scalars other than strings become null leaves.
static MSChatValue *MiniSightAIValueFromObject(id object, NSUInteger depth) {
    if (depth > kMiniSightAIMaxJSONDepth) return MSChatValueNewNull();
    if ([object isKindOfClass:NSString.class]) {
        return MSChatValueNewString([(NSString *)object UTF8String]);
    }
    if ([object isKindOfClass:NSArray.class]) {
        NSArray *array = object;
        MSChatValue *value = MSChatValueNewArray(array.count);
        if (!value) return NULL;
        for (id item in array) {
            MSChatValue *child = MiniSightAIValueFromObject(item, depth + 1);
            if (!child || !MSChatArrayAppend(value, child)) MSChatValueFree(child);
        }
        return value;
    }
    if ([object isKindOfClass:NSDictionary.class]) {
        NSDictionary *dictionary = object;
        MSChatValue *value = MSChatValueNewDict(dictionary.count);
        if (!value) return NULL;
        for (id key in dictionary) {
            if (![key isKindOfClass:NSString.class]) continue;
            MSChatValue *child = MiniSightAIValueFromObject(dictionary[key], depth + 1);
            if (!child || !MSChatDictSet(value, [(NSString *)key UTF8String], child)) {
                MSChatValueFree(child);
            }
        }
        return value;
    }
    return MSChatValueNewNull();
}

static MSChatValue *MiniSightAIValueFromJSONData(NSData *data) {
    if (!data.length) return NULL;
    id object = [NSJSONSerialization JSONObjectWithData:data options:0 error:nil];
    if (!object) return NULL;
    return MiniSightAIValueFromObject(object, 0);
}

#pragma mark - AI

@interface MiniSightAI ()
@property (nonatomic, strong, nullable) NSURLSession *session;
@property (nonatomic, strong, nullable) NSURLSessionDataTask *task;
@property (nonatomic, copy, nullable) void (^pendingCompletion)(MiniSightAIReply *reply);
@property (nonatomic, assign, readwrite) MSChatContext history;
@property (nonatomic, assign, readwrite) MSChatRequestState requestState;
@property (nonatomic, copy) NSString *systemPrompt;
@end

@implementation MiniSightAI

- (instancetype)initWithContainer:(NSString *)container {
    self = [super init];
    if (!self) return nil;
    _containerPath = [container copy];
    _systemPrompt = [kMiniSightAISystemPrompt copy];
    _session = [NSURLSession sessionWithConfiguration:
        [NSURLSessionConfiguration ephemeralSessionConfiguration]];
    _session.configuration.timeoutIntervalForRequest = kMiniSightAITimeout;
    _session.configuration.timeoutIntervalForResource = kMiniSightAITimeout;
    MSChatContextInit(&_history);
    MSChatStateInit(&_requestState);
    MSChatContextAdd(&_history, MSChatRoleSystem, _systemPrompt.UTF8String);
    return self;
}

- (void)setSystemPrompt:(NSString *)systemPrompt {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    NSString *clean = [systemPrompt stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (!clean.length) clean = kMiniSightAISystemPrompt;
    if (clean.length > 2000) clean = [clean substringToIndex:2000];
    if ([_systemPrompt isEqualToString:clean]) return;
    _systemPrompt = [clean copy];
    NSUInteger count = _history.count;
    MSChatContext replacement;
    MSChatContextInit(&replacement);
    MSChatContextAdd(&replacement, MSChatRoleSystem, _systemPrompt.UTF8String);
    for (size_t i = 1; i < count; ++i) {
        const MSChatMessage *item = &_history.items[i];
        MSChatContextAdd(&replacement, item->role, item->content);
    }
    _history = replacement;
}

- (void)setContainerPath:(NSString *)containerPath {
    _containerPath = [containerPath copy];
    NSDictionary *config = _containerPath.length ? MSBridgeRead(_containerPath, @"ai.json", kMiniSightAIMaxConfigBytes) : nil;
    NSString *prompt = [config[@"system_prompt"] isKindOfClass:NSString.class] ? config[@"system_prompt"] : kMiniSightAISystemPrompt;
    self.systemPrompt = prompt;
}

- (BOOL)isSending { return _requestState.sending != 0; }
- (NSUInteger)messageCount { return _history.count; }

- (void)resetConversation {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    [self cancel];
    MSChatContextInit(&_history);
    MSChatContextAdd(&_history, MSChatRoleSystem, _systemPrompt.UTF8String);
}

#pragma mark Configuration

/// Reads ai.json defensively. Returns nil and sets `issue` for a missing,
/// unreadable, or incomplete file; never surfaces the key itself.
- (nullable NSDictionary *)loadConfigurationWithIssue:(MiniSightAIIssue *)issue {
    NSString *container = [self.containerPath copy];
    if (!container.length || ![[NSFileManager defaultManager] fileExistsAtPath:container]) {
        if (issue) *issue = MiniSightAIIssueConfig;
        return nil;
    }
    NSDictionary *config = MSBridgeRead(container, @"ai.json", kMiniSightAIMaxConfigBytes);
    if (![config isKindOfClass:NSDictionary.class]) {
        if (issue) *issue = MiniSightAIIssueConfig;
        return nil;
    }
    for (NSString *field in @[@"url", @"key", @"model"]) {
        id value = config[field];
        if (![value isKindOfClass:NSString.class] ||
            ![value stringByTrimmingCharactersInSet:
                [NSCharacterSet whitespaceAndNewlineCharacterSet]].length) {
            if (issue) *issue = MiniSightAIIssueConfig;
            return nil;
        }
    }
    return config;
}

#pragma mark Send

- (void)sendUserText:(NSString *)text
          completion:(void (^)(MiniSightAIReply *reply))completion {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    if (!MSChatBeginRequest(&_requestState)) return;      // duplicate tap: keep current send
    const unsigned long generation = _requestState.generation;

    NSString *trimmed = [(text ?: @"") stringByTrimmingCharactersInSet:
        [NSCharacterSet whitespaceAndNewlineCharacterSet]];
    if (!trimmed.length) {
        [self finishIssue:MiniSightAIIssueConfig
                   status:0
                     text:@"请先输入内容再发送"
               generation:generation
               completion:completion];
        return;
    }

    MiniSightAIIssue configIssue = MiniSightAIIssueNone;
    NSDictionary *config = [self loadConfigurationWithIssue:&configIssue];
    if (!config) {
        [self answerIssue:configIssue status:0 generation:generation completion:completion];
        return;
    }

    NSString *base = [config[@"url"] stringByTrimmingCharactersInSet:
        [NSCharacterSet whitespaceAndNewlineCharacterSet]];
    NSString *key = config[@"key"];
    NSString *model = config[@"model"];
    char endpoint[MSCHAT_ENDPOINT_MAX];
    if (MSChatBuildEndpoint(base.UTF8String, endpoint, sizeof endpoint) != MSChatURLOK) {
        [self answerIssue:MiniSightAIIssueURL status:0 generation:generation completion:completion];
        return;
    }
    NSURL *url = [NSURL URLWithString:[NSString stringWithUTF8String:endpoint]];
    if (!url) {
        [self answerIssue:MiniSightAIIssueURL status:0 generation:generation completion:completion];
        return;
    }

    MSChatContextAdd(&_history, MSChatRoleUser, trimmed.UTF8String);

    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    request.HTTPMethod = @"POST";
    request.timeoutInterval = kMiniSightAITimeout;
    [request setValue:[@"Bearer " stringByAppendingString:key] forHTTPHeaderField:@"Authorization"];
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    request.HTTPBody = [NSJSONSerialization dataWithJSONObject:
        [self requestBodyWithModel:model] options:0 error:nil];

    NSString *container = [self.containerPath copy];
    __weak typeof(self) weakSelf = self;
    self.pendingCompletion = completion;
    self.task = [self.session dataTaskWithRequest:request
        completionHandler:^(NSData *data, NSURLResponse *response, NSError *error) {
        dispatch_async(dispatch_get_main_queue(), ^{
            [weakSelf handleData:data response:response error:error
                      container:container generation:generation];
        });
    }];
    [self.task resume];
}

- (NSDictionary *)requestBodyWithModel:(NSString *)model {
    NSMutableArray *messages = [NSMutableArray arrayWithCapacity:self.history.count];
    for (size_t i = 0; i < self.history.count; ++i) {
        const MSChatMessage *item = &self.history.items[i];
        [messages addObject:@{
            @"role": [NSString stringWithUTF8String:MSChatRoleName(item->role)],
            @"content": [NSString stringWithUTF8String:item->content]
        }];
    }
    return @{ @"model": model, @"max_tokens": @(kMiniSightAIMaxTokens), @"messages": messages };
}

#pragma mark Completion

- (void)handleData:(NSData *)data
          response:(NSURLResponse *)response
             error:(NSError *)error
         container:(NSString *)container
        generation:(unsigned long)generation {
    if (!MSChatAcceptsReply(&_requestState, generation)) return;
    if (![container isEqualToString:self.containerPath ?: @""] ||
        ![[NSFileManager defaultManager] fileExistsAtPath:container]) {
        [self answerIssue:MiniSightAIIssueCancelled status:0 generation:generation completion:nil];
        return;
    }

    long status = [response isKindOfClass:NSHTTPURLResponse.class]
        ? (long)((NSHTTPURLResponse *)response).statusCode : 0;
    if (error) {
        MiniSightAIIssue issue = MiniSightAIIssueNetwork;
        if (error.code == NSURLErrorCancelled) issue = MiniSightAIIssueCancelled;
        else if (error.code == NSURLErrorTimedOut) issue = MiniSightAIIssueTimeout;
        [self answerIssue:issue status:status generation:generation completion:nil];
        return;
    }
    if (status < 200 || status >= 300) {
        [self answerIssue:MiniSightAIIssueHTTP status:status generation:generation completion:nil];
        return;
    }
    if (data.length > kMiniSightAIMaxResponseBytes) {
        [self answerIssue:MiniSightAIIssueEmpty status:status generation:generation completion:nil];
        return;
    }

    MSChatValue *root = MiniSightAIValueFromJSONData(data);
    char text[MSCHAT_TEXT_MAX];
    MSChatExtractResult extract = MSChatExtractReplyText(root, text, sizeof text);
    if (root) MSChatValueFree(root);
    if (extract != MSChatExtractOK || !text[0]) {
        // 2xx with an empty/unparseable body is a real failure, not a silent success.
        [self answerIssue:MiniSightAIIssueEmpty status:status generation:generation completion:nil];
        return;
    }

    NSString *reply = [NSString stringWithUTF8String:text] ?: @"";
    MSChatContextAdd(&_history, MSChatRoleAssistant, reply.UTF8String);
    [self finishIssue:MiniSightAIIssueNone status:status text:reply
           generation:generation completion:nil];
}

/// Finishes the request and delivers `displayText` for `issue`.
- (void)answerIssue:(MiniSightAIIssue)issue
             status:(long)status
         generation:(unsigned long)generation
         completion:(void (^)(MiniSightAIReply *reply))completion {
    NSString *message = [NSString stringWithUTF8String:MSChatMessageForIssue((MSChatIssue)issue, status)];
    [self finishIssue:issue status:status text:message ?: @"AI 这次没回话"
           generation:generation completion:completion];
}

- (void)finishIssue:(MiniSightAIIssue)issue
             status:(long)status
               text:(NSString *)text
         generation:(unsigned long)generation
         completion:(void (^)(MiniSightAIReply *reply))completion {
    if (generation != 0 && !MSChatAcceptsReply(&_requestState, generation)) return;
    MSChatFinishRequest(&_requestState, generation);
    self.task = nil;

    MiniSightAIReply *reply = [[MiniSightAIReply alloc] init];
    reply.issue = issue;
    reply.status = status;
    reply.text = issue == MiniSightAIIssueNone ? (text ?: @"") : @"";
    reply.displayText = text.length ? text : @"AI 这次没回话";
    MSDiag(@"ai issue=%ld status=%ld text_len=%lu", (long)issue, status, (unsigned long)reply.text.length);

    void (^handler)(MiniSightAIReply *) = completion ?: self.pendingCompletion;
    self.pendingCompletion = nil;
    if (handler) handler(reply);
}

#pragma mark Cancel / lifecycle

- (void)cancel {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    if (!MSChatCancelRequest(&_requestState)) return;
    [_task cancel];
    self.task = nil;
    void (^handler)(MiniSightAIReply *) = self.pendingCompletion;
    self.pendingCompletion = nil;
    if (!handler) return;

    MiniSightAIReply *reply = [[MiniSightAIReply alloc] init];
    reply.issue = MiniSightAIIssueCancelled;
    reply.displayText = [NSString stringWithUTF8String:
        MSChatMessageForIssue(MSChatIssueCancelled, 0)] ?: @"已取消";
    reply.text = @"";
    handler(reply);
}

- (void)dealloc {
    [_task cancel];
    _pendingCompletion = nil;
}

@end
