#import "MiniSightAI.h"
#import "MiniSightLog.h"
#import "MiniSightBridgeIO.h"

#import <dispatch/dispatch.h>
#include <math.h>
#include <stdarg.h>

static NSString *const kMiniSightAISystemPrompt =
    @"你是 iPhone 桌宠 MiniSight，用简洁、自然的中文回答；不确定就直说，不要编造。";
static const NSTimeInterval kMiniSightAIRequestTimeout = 45.0;
static const NSTimeInterval kMiniSightAIResourceTimeout = 60.0;
static const NSTimeInterval kMiniSightAIHardDeadline = 65.0;
static const NSTimeInterval kMiniSightAIRetryAfterDefault = 30.0;
static const NSTimeInterval kMiniSightAIRetryAfterMax = 300.0;
static const NSInteger kMiniSightAIMaxTokens = 2048;
static const NSUInteger kMiniSightAIMaxPromptLength = 2000;
static const NSUInteger kMiniSightAIMaxJSONDepth = 10;
static const unsigned long long kMiniSightAIMaxConfigBytes = 64 * 1024;
static const NSUInteger kMiniSightAIMaxResponseBytes = 2 * 1024 * 1024;
static const NSUInteger kMiniSightAIMaxJSONNodes = 4096;

/// The random client id is stable across generations so late callbacks retain their identity.
static void MiniSightAIDiag(NSString *clientID, NSString *format, ...) NS_FORMAT_FUNCTION(2, 3);
static void MiniSightAIDiag(NSString *clientID, NSString *format, ...) {
    va_list args;
    va_start(args, format);
    NSString *message = [[NSString alloc] initWithFormat:format arguments:args];
    va_end(args);
    MSDiag(@"client=%@ %@", clientID, message);
}

#pragma mark - Reply

@interface MiniSightAIReply ()
@property (nonatomic, readwrite) MiniSightAIIssue issue;
@property (nonatomic, readwrite) long status;
@property (nonatomic, copy, readwrite) NSString *text;
@property (nonatomic, copy, readwrite) NSString *displayText;
@property (nonatomic, copy, readwrite) NSString *requestID;
@property (nonatomic, readwrite) NSTimeInterval retryAfterSeconds;
@end

@implementation MiniSightAIReply
- (BOOL)isSuccess { return self.issue == MiniSightAIIssueNone && self.text.length > 0; }
@end

#pragma mark - Safe response metadata

static BOOL MiniSightAIHasValue(id value) {
    if (!value || value == NSNull.null) return NO;
    if ([value isKindOfClass:NSString.class]) return [(NSString *)value length] > 0;
    if ([value isKindOfClass:NSArray.class]) return [(NSArray *)value count] > 0;
    if ([value isKindOfClass:NSDictionary.class]) return [(NSDictionary *)value count] > 0;
    return YES;
}

static BOOL MiniSightAIIsReasoningObject(NSDictionary *object) {
    for (NSString *key in @[@"type", @"channel"]) {
        id tag = object[key];
        if ([tag isKindOfClass:NSString.class] &&
            ([tag hasPrefix:@"reasoning"] || [tag isEqualToString:@"analysis"] ||
             [tag isEqualToString:@"thinking"])) return YES;
    }
    return NO;
}

static BOOL MiniSightAIHasReasoning(id object, NSUInteger depth) {
    if (depth > kMiniSightAIMaxJSONDepth) return NO;
    if ([object isKindOfClass:NSArray.class]) {
        for (id item in (NSArray *)object) {
            if (MiniSightAIHasReasoning(item, depth + 1)) return YES;
        }
    } else if ([object isKindOfClass:NSDictionary.class]) {
        NSDictionary *dictionary = object;
        if (MiniSightAIIsReasoningObject(dictionary)) return YES;
        for (NSString *key in @[@"reasoning", @"reasoning_content", @"reasoning_details", @"thinking"]) {
            if (MiniSightAIHasValue(dictionary[key])) return YES;
        }
        for (NSString *key in @[@"choices", @"message", @"content", @"output", @"candidates", @"parts"]) {
            if (MiniSightAIHasReasoning(dictionary[key], depth + 1)) return YES;
        }
    }
    return NO;
}

/// Never interpolate the provider's arbitrary finish_reason into a log.
static NSString *MiniSightAISafeFinishReason(id value) {
    if (!value || value == NSNull.null) return @"missing";
    for (NSString *allowed in @[@"stop", @"length", @"tool_calls", @"function_call", @"content_filter"]) {
        if ([value isKindOfClass:NSString.class] && [value isEqualToString:allowed]) return allowed;
    }
    return @"other";
}

static NSTimeInterval MiniSightAIRetryAfterSeconds(NSURLResponse *response) {
    if (![response isKindOfClass:NSHTTPURLResponse.class] ||
        ((NSHTTPURLResponse *)response).statusCode != 429) return 0;
    NSDictionary *headers = ((NSHTTPURLResponse *)response).allHeaderFields;
    NSString *raw = nil;
    for (id key in headers) {
        if ([key isKindOfClass:NSString.class] &&
            [key caseInsensitiveCompare:@"Retry-After"] == NSOrderedSame &&
            [headers[key] isKindOfClass:NSString.class]) {
            raw = [headers[key] stringByTrimmingCharactersInSet:
                NSCharacterSet.whitespaceAndNewlineCharacterSet];
            break;
        }
    }
    if (!raw.length || raw.length > 128) return kMiniSightAIRetryAfterDefault;
    BOOL integer = YES;
    NSTimeInterval seconds = 0;
    for (NSUInteger i = 0; i < raw.length; ++i) {
        unichar c = [raw characterAtIndex:i];
        if (c < '0' || c > '9') { integer = NO; break; }
        seconds = MIN(kMiniSightAIRetryAfterMax, seconds * 10 + (c - '0'));
    }
    if (integer) return MAX(1.0, seconds);
    NSDateFormatter *formatter = [[NSDateFormatter alloc] init];
    formatter.locale = [[NSLocale alloc] initWithLocaleIdentifier:@"en_US_POSIX"];
    formatter.timeZone = [NSTimeZone timeZoneForSecondsFromGMT:0];
    formatter.lenient = NO;
    for (NSString *format in @[@"EEE, dd MMM yyyy HH:mm:ss 'GMT'",
                               @"EEEE, dd-MMM-yy HH:mm:ss 'GMT'",
                               @"EEE MMM d HH:mm:ss yyyy"]) {
        formatter.dateFormat = format;
        NSDate *date = [formatter dateFromString:raw];
        if (date) return MIN(kMiniSightAIRetryAfterMax, MAX(1.0, ceil(date.timeIntervalSinceNow)));
    }
    return kMiniSightAIRetryAfterDefault;
}

#pragma mark - JSON bridge

/// NSJSONSerialization result -> ChatCore value tree. Shape is all the parser
/// needs; scalars other than strings become null leaves.
static MSChatValue *MiniSightAIValueFromObject(id object, NSUInteger depth, NSUInteger *nodesLeft) {
    if (depth > kMiniSightAIMaxJSONDepth || !*nodesLeft) return NULL;
    --*nodesLeft;
    if ([object isKindOfClass:NSString.class]) {
        return MSChatValueNewString([(NSString *)object UTF8String]);
    }
    if ([object isKindOfClass:NSArray.class]) {
        NSArray *array = object;
        if (array.count > *nodesLeft) return NULL;
        MSChatValue *value = MSChatValueNewArray(array.count);
        if (!value) return NULL;
        for (id item in array) {
            MSChatValue *child = MiniSightAIValueFromObject(item, depth + 1, nodesLeft);
            if (!child || !MSChatArrayAppend(value, child)) {
                MSChatValueFree(child);
                MSChatValueFree(value);
                return NULL; // Never report partial conversion as a successful answer.
            }
        }
        return value;
    }
    if ([object isKindOfClass:NSDictionary.class]) {
        NSDictionary *dictionary = object;
        if (MiniSightAIIsReasoningObject(dictionary)) return MSChatValueNewNull();
        if (dictionary.count > *nodesLeft) return NULL;
        MSChatValue *value = MSChatValueNewDict(dictionary.count);
        if (!value) return NULL;
        for (id key in dictionary) {
            if (![key isKindOfClass:NSString.class] || [key hasPrefix:@"reasoning"] ||
                [key isEqualToString:@"thinking"]) continue;
            MSChatValue *child = MiniSightAIValueFromObject(dictionary[key], depth + 1, nodesLeft);
            if (!child || !MSChatDictSet(value, [(NSString *)key UTF8String], child)) {
                MSChatValueFree(child);
                MSChatValueFree(value);
                return NULL;
            }
        }
        return value;
    }
    return MSChatValueNewNull();
}

/// An explicit chat message must have visible content. Do not let an empty
/// message.content fall back to a sibling text/output/reasoning field.
static id MiniSightAIContentObject(id object) {
    if (![object isKindOfClass:NSDictionary.class]) return object;
    id choices = object[@"choices"];
    id first = [choices isKindOfClass:NSArray.class] && [choices count] ? choices[0] : nil;
    id message = [first isKindOfClass:NSDictionary.class] ? first[@"message"] : nil;
    if (![message isKindOfClass:NSDictionary.class]) return object;
    id content = MiniSightAIIsReasoningObject(message) ? NSNull.null : message[@"content"];
    return @{@"choices": @[@{@"message": @{@"content": content ?: NSNull.null}}]};
}

#pragma mark - Bounded non-streaming transport

/// Each request owns an ephemeral session. Delegates run on the main queue;
/// the buffer never appends a chunk that would exceed the 2 MiB budget.
@interface MiniSightAITransport : NSObject <NSURLSessionDataDelegate>
@property (nonatomic, strong, nullable) NSURLSession *session;
@property (nonatomic, strong, nullable) NSURLSessionDataTask *task;
@property (nonatomic, strong, nullable) NSMutableData *buffer;
@property (nonatomic, strong, nullable) NSURLResponse *response;
@property (nonatomic, copy, nullable) void (^completion)(NSData *, NSURLResponse *, NSError *);
@property (nonatomic, assign) BOOL completed;
- (BOOL)startWithRequest:(nullable NSURLRequest *)request
             completion:(void (^)(NSData *, NSURLResponse *, NSError *))completion;
- (void)invalidate;
- (void)completeWithError:(nullable NSError *)error;
@end

@implementation MiniSightAITransport

- (BOOL)startWithRequest:(NSURLRequest *)request
             completion:(void (^)(NSData *, NSURLResponse *, NSError *))completion {
    if (!request || !completion || self.completed || self.session) return NO;
    NSURLSessionConfiguration *configuration = [NSURLSessionConfiguration ephemeralSessionConfiguration];
    // NSURLSession.configuration is a copy: set these BEFORE creating it.
    configuration.timeoutIntervalForRequest = kMiniSightAIRequestTimeout;
    configuration.timeoutIntervalForResource = kMiniSightAIResourceTimeout;
    self.buffer = [NSMutableData dataWithCapacity:kMiniSightAIMaxResponseBytes];
    self.completion = completion;
    self.session = [NSURLSession sessionWithConfiguration:configuration delegate:self
        delegateQueue:NSOperationQueue.mainQueue];
    self.task = [self.session dataTaskWithRequest:request];
    if (!self.task) { [self invalidate]; return NO; }
    [self.task resume];
    return YES;
}

- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
        willPerformHTTPRedirection:(NSHTTPURLResponse *)response
        newRequest:(NSURLRequest *)request
        completionHandler:(void (^)(NSURLRequest *))completionHandler {
    // Reject ALL redirects, including same-host redirects. Never forward the
    // Authorization header from chat or a Settings credential test.
    if (!self.completed) self.response = response;
    completionHandler(nil);
}

- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)dataTask
        didReceiveResponse:(NSURLResponse *)response
        completionHandler:(void (^)(NSURLSessionResponseDisposition))completionHandler {
    if (self.completed) { completionHandler(NSURLSessionResponseCancel); return; }
    self.response = response;
    if (response.expectedContentLength > (int64_t)kMiniSightAIMaxResponseBytes) {
        completionHandler(NSURLSessionResponseCancel);
        [self completeWithError:[NSError errorWithDomain:NSURLErrorDomain
            code:NSURLErrorDataLengthExceedsMaximum userInfo:nil]];
        return;
    }
    completionHandler(NSURLSessionResponseAllow);
}

- (void)URLSession:(NSURLSession *)session dataTask:(NSURLSessionDataTask *)dataTask
        didReceiveData:(NSData *)data {
    if (self.completed) return;
    if (data.length > kMiniSightAIMaxResponseBytes - self.buffer.length) {
        [self completeWithError:[NSError errorWithDomain:NSURLErrorDomain
            code:NSURLErrorDataLengthExceedsMaximum userInfo:nil]];
        return;
    }
    [self.buffer appendData:data];
}

- (void)URLSession:(NSURLSession *)session task:(NSURLSessionTask *)task
        didCompleteWithError:(NSError *)error {
    if (self.completed) return;
    if (!self.response) self.response = task.response;
    [self completeWithError:error];
}

- (void)completeWithError:(NSError *)error {
    if (self.completed) return;
    NSData *data = self.buffer;
    NSURLResponse *response = self.response;
    void (^completion)(NSData *, NSURLResponse *, NSError *) = self.completion;
    [self invalidate];  // clear the delegate/session cycle BEFORE delivering
    if (completion) completion(data, response, error);
}

- (void)invalidate {
    if (self.completed) return;
    self.completed = YES;
    self.completion = nil;
    [self.task cancel];
    self.task = nil;
    [self.session invalidateAndCancel];
    self.session = nil;
    self.buffer = nil;
    self.response = nil;
}

@end

#pragma mark - AI

@interface MiniSightAI ()
@property (nonatomic, copy) NSString *diagnosticClientID;
@property (nonatomic, strong, nullable) MiniSightAITransport *transport;
@property (nonatomic, copy, nullable) dispatch_block_t timeoutBlock;
@property (nonatomic, copy, nullable) void (^pendingCompletion)(MiniSightAIReply *reply);
@property (nonatomic, assign, readwrite) MSChatContext history;
@property (nonatomic, assign, readwrite) MSChatRequestState requestState;
- (void)handleData:(NSData *)data response:(NSURLResponse *)response error:(NSError *)error
         container:(NSString *)container generation:(unsigned long)generation;
- (void)answerIssue:(MiniSightAIIssue)issue status:(long)status
    retryAfterSeconds:(NSTimeInterval)retryAfterSeconds generation:(unsigned long)generation;
- (void)finishIssue:(MiniSightAIIssue)issue status:(long)status text:(NSString *)text
    retryAfterSeconds:(NSTimeInterval)retryAfterSeconds generation:(unsigned long)generation;
@end

@implementation MiniSightAI

- (instancetype)initWithContainer:(NSString *)container {
    self = [super init];
    if (!self) return nil;
    _containerPath = [container copy];
    _diagnosticClientID = NSUUID.UUID.UUIDString;
    MSChatContextInit(&_history);
    MSChatStateInit(&_requestState);
    MSChatContextAdd(&_history, MSChatRoleSystem, kMiniSightAISystemPrompt.UTF8String);
    return self;
}

- (void)setContainerPath:(NSString *)containerPath {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    if (_containerPath == containerPath || [_containerPath isEqualToString:containerPath]) return;
    // Publish the new container before cancellation calls user code: a
    // re-entrant send must not read the old container's credentials.
    _containerPath = [containerPath copy];
    [self cancel];
}

- (BOOL)isSending { return _requestState.sending != 0; }
- (NSUInteger)messageCount { return _history.count; }

- (void)resetConversation {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    MSChatContextInit(&_history);
    MSChatContextAdd(&_history, MSChatRoleSystem, kMiniSightAISystemPrompt.UTF8String);
    [self cancel];  // nothing may clear a new conversation after its callback
}

- (void)clearRequestResources {
    if (self.timeoutBlock) dispatch_block_cancel(self.timeoutBlock);
    self.timeoutBlock = nil;
    MiniSightAITransport *transport = self.transport;
    self.transport = nil;
    [transport invalidate];
}

- (void)armDeadlineForGeneration:(unsigned long)generation {
    __weak typeof(self) weakSelf = self;
    self.timeoutBlock = dispatch_block_create(0, ^{
        typeof(self) strongSelf = weakSelf;
        if (!strongSelf || !MSChatAcceptsReply(&strongSelf->_requestState, generation)) return;
        MiniSightAIDiag(strongSelf.diagnosticClientID, @"ai deadline generation=%lu", generation);
        MSDiagEvent(@"ai", @"error", @"failed", @{ @"request": [NSString stringWithFormat:@"%@/%lu", strongSelf.diagnosticClientID, generation], @"reason": @"hard_deadline" });
        [strongSelf answerIssue:MiniSightAIIssueTimeout status:0
            retryAfterSeconds:0 generation:generation];
    });
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW,
        (int64_t)(kMiniSightAIHardDeadline * NSEC_PER_SEC)),
        dispatch_get_main_queue(), self.timeoutBlock);
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

- (NSString *)nextRequestID {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    return [NSString stringWithFormat:@"%@/%lu", self.diagnosticClientID, _requestState.generation + 1];
}

- (void)sendUserText:(NSString *)text
          completion:(void (^)(MiniSightAIReply *reply))completion {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    if (!MSChatBeginRequest(&_requestState)) {
        MSDiagEvent(@"ai", @"skip", @"skipped", @{ @"reason": @"already_sending" });
        return;
    }
    const unsigned long generation = _requestState.generation;
    NSString *requestID = [NSString stringWithFormat:@"%@/%lu", self.diagnosticClientID, generation];
    MSDiagEvent(@"ai", @"send", @"pending", @{ @"request": requestID, @"generation": @(generation) });
    self.pendingCompletion = completion;  // even preflight failures must answer
    [self armDeadlineForGeneration:generation];
    MiniSightAIDiag(self.diagnosticClientID, @"ai begin generation=%lu", generation);

    NSString *container = [self.containerPath copy] ?: @"";
    NSString *trimmed = [(text ?: @"") stringByTrimmingCharactersInSet:
        NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (!trimmed.length) {
        MiniSightAIDiag(self.diagnosticClientID, @"ai config generation=%lu stage=input result=%ld", generation, (long)MiniSightAIIssueConfig);
        [self finishIssue:MiniSightAIIssueConfig status:0 text:@"请先输入内容再发送"
            retryAfterSeconds:0 generation:generation];
        return;
    }

    MiniSightAIIssue configIssue = MiniSightAIIssueNone;
    NSDictionary *config = [self loadConfigurationWithIssue:&configIssue];
    MiniSightAIDiag(self.diagnosticClientID, @"ai config generation=%lu stage=fields result=%ld", generation, (long)configIssue);
    MSDiagEvent(@"ai", @"config", config ? @"ok" : @"failed", @{ @"request": requestID, @"issue": @(configIssue), @"field": @"connection" });
    if (!config) {
        [self answerIssue:configIssue status:0 retryAfterSeconds:0 generation:generation];
        return;
    }

    NSString *base = [config[@"url"] stringByTrimmingCharactersInSet:
        NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSString *key = [config[@"key"] stringByTrimmingCharactersInSet:
        NSCharacterSet.whitespaceAndNewlineCharacterSet];
    NSString *model = [config[@"model"] stringByTrimmingCharactersInSet:
        NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if ([key rangeOfCharacterFromSet:NSCharacterSet.newlineCharacterSet].location != NSNotFound) {
        MiniSightAIDiag(self.diagnosticClientID, @"ai config generation=%lu stage=header result=%ld", generation, (long)MiniSightAIIssueConfig);
        [self answerIssue:MiniSightAIIssueConfig status:0 retryAfterSeconds:0 generation:generation];
        return;
    }
    char endpoint[MSCHAT_ENDPOINT_MAX];
    MSChatURLError urlIssue = MSChatBuildEndpoint(base.UTF8String, endpoint, sizeof endpoint);
    MiniSightAIDiag(self.diagnosticClientID, @"ai config generation=%lu stage=endpoint result=%ld", generation, (long)urlIssue);
    MSDiagEvent(@"ai", @"config", urlIssue == MSChatURLOK ? @"ok" : @"failed", @{ @"request": requestID, @"field": @"endpoint", @"code": @(urlIssue) });
    if (urlIssue != MSChatURLOK) {
        [self answerIssue:MiniSightAIIssueURL status:0 retryAfterSeconds:0 generation:generation];
        return;
    }
    NSURL *url = [NSURL URLWithString:[NSString stringWithUTF8String:endpoint]];
    if (!url) {
        MiniSightAIDiag(self.diagnosticClientID, @"ai config generation=%lu stage=url result=0", generation);
        [self answerIssue:MiniSightAIIssueURL status:0 retryAfterSeconds:0 generation:generation];
        return;
    }

    NSMutableURLRequest *request = [NSMutableURLRequest requestWithURL:url];
    if (!request) {
        MiniSightAIDiag(self.diagnosticClientID, @"ai network generation=%lu started=0", generation);
        [self answerIssue:MiniSightAIIssueNetwork status:0 retryAfterSeconds:0 generation:generation];
        return;
    }
    request.HTTPMethod = @"POST";
    request.timeoutInterval = kMiniSightAIRequestTimeout;
    [request setValue:[@"Bearer " stringByAppendingString:key] forHTTPHeaderField:@"Authorization"];
    [request setValue:@"application/json" forHTTPHeaderField:@"Content-Type"];
    NSString *systemPrompt = self.systemPrompt;
    if (!systemPrompt) {
        systemPrompt = [config[@"system_prompt"] isKindOfClass:NSString.class] ? config[@"system_prompt"] : @"";
    }
    systemPrompt = [systemPrompt stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (systemPrompt.length > kMiniSightAIMaxPromptLength) {
        __block NSUInteger characters = 0;
        __block NSUInteger end = 0;
        [systemPrompt enumerateSubstringsInRange:NSMakeRange(0, systemPrompt.length)
            options:NSStringEnumerationByComposedCharacterSequences
            usingBlock:^(NSString *part, NSRange range, NSRange enclosingRange, BOOL *stop) {
                (void)part; (void)enclosingRange;
                end = NSMaxRange(range);
                if (++characters == kMiniSightAIMaxPromptLength) *stop = YES;
            }];
        systemPrompt = [systemPrompt substringToIndex:end];
    }
    MSDiagEvent(@"ai", @"configure", @"ok", @{ @"request": requestID, @"setting": @"ai_persona", @"enabled": @(systemPrompt.length > 0), @"chars": @(systemPrompt.length) });
    MSChatContextAdd(&_history, MSChatRoleUser, trimmed.UTF8String);
    request.HTTPBody = [NSJSONSerialization dataWithJSONObject:
        [self requestBodyWithModel:model systemPrompt:systemPrompt] options:0 error:NULL];
    MiniSightAIDiag(self.diagnosticClientID, @"ai config generation=%lu stage=body result=%d", generation, request.HTTPBody != nil);
    if (!request.HTTPBody) {
        [self answerIssue:MiniSightAIIssueConfig status:0 retryAfterSeconds:0 generation:generation];
        return;
    }

    __weak typeof(self) weakSelf = self;
    MiniSightAITransport *transport = [[MiniSightAITransport alloc] init];
    self.transport = transport;
    BOOL started = [transport startWithRequest:request
        completion:^(NSData *data, NSURLResponse *response, NSError *error) {
            [weakSelf handleData:data response:response error:error container:container generation:generation];
        }];
    MiniSightAIDiag(self.diagnosticClientID, @"ai network generation=%lu started=%d max_tokens=%ld request_s=%.0f resource_s=%.0f deadline_s=%.0f cap_bytes=%lu",
        generation, started, (long)kMiniSightAIMaxTokens, kMiniSightAIRequestTimeout,
        kMiniSightAIResourceTimeout, kMiniSightAIHardDeadline, (unsigned long)kMiniSightAIMaxResponseBytes);
    MSDiagEvent(@"ai", @"network", started ? @"pending" : @"failed", @{ @"request": requestID, @"reason": started ? @"transport_started" : @"transport_rejected" });
    if (!started) {
        [self answerIssue:MiniSightAIIssueNetwork status:0 retryAfterSeconds:0 generation:generation];
    }
}

- (NSDictionary *)requestBodyWithModel:(NSString *)model systemPrompt:(NSString *)systemPrompt {
    NSMutableArray *messages = [NSMutableArray arrayWithCapacity:_history.count];
    BOOL insertedSystem = NO;
    for (size_t i = 0; i < _history.count; ++i) {
        const MSChatMessage *item = &_history.items[i];
        if (item->role == MSChatRoleSystem) {
            if (!insertedSystem) {
                NSString *prompt = systemPrompt.length ? systemPrompt : kMiniSightAISystemPrompt;
                [messages addObject:@{@"role": @"system", @"content": prompt}];
                insertedSystem = YES;
            }
            continue;
        }
        [messages addObject:@{
            @"role": [NSString stringWithUTF8String:MSChatRoleName(item->role)],
            @"content": [NSString stringWithUTF8String:item->content] ?: @""
        }];
    }
    if (!insertedSystem) {
        NSString *prompt = systemPrompt.length ? systemPrompt : kMiniSightAISystemPrompt;
        [messages insertObject:@{@"role": @"system", @"content": prompt} atIndex:0];
    }
    return @{@"model": model, @"max_tokens": @(kMiniSightAIMaxTokens), @"messages": messages};
}

#pragma mark Completion

- (void)handleData:(NSData *)data
          response:(NSURLResponse *)response
             error:(NSError *)error
         container:(NSString *)container
        generation:(unsigned long)generation {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    long status = [response isKindOfClass:NSHTTPURLResponse.class]
        ? (long)((NSHTTPURLResponse *)response).statusCode : 0;
    BOOL accepted = MSChatAcceptsReply(&_requestState, generation) != 0;
    MiniSightAIDiag(self.diagnosticClientID, @"ai callback generation=%lu http=%ld bytes=%lu errorCode=%ld accepted=%d",
        generation, status, (unsigned long)data.length, (long)error.code, accepted);
    NSString *requestID = [NSString stringWithFormat:@"%@/%lu", self.diagnosticClientID, generation];
    MSDiagEvent(@"ai", @"callback", accepted ? @"pending" : @"skipped", @{ @"request": requestID, @"http": @(status), @"bytes": @(data.length), @"code": @(error.code), @"reason": accepted ? @"current_generation" : @"stale_generation" });
    if (!accepted) return;  // an old packet must not finish/cancel a newer send
    if (![container isEqualToString:self.containerPath ?: @""] ||
        ![[NSFileManager defaultManager] fileExistsAtPath:container]) {
        [self answerIssue:MiniSightAIIssueCancelled status:0 retryAfterSeconds:0 generation:generation];
        return;
    }

    NSTimeInterval retryAfter = MiniSightAIRetryAfterSeconds(response);
    if (error) {
        if ([error.domain isEqualToString:NSURLErrorDomain] &&
            error.code == NSURLErrorDataLengthExceedsMaximum) {
            [self finishIssue:MiniSightAIIssueEmpty status:status text:@"AI 回复超过 2 MiB，已停止接收"
                retryAfterSeconds:retryAfter generation:generation];
            return;
        }
        MiniSightAIIssue issue = MiniSightAIIssueNetwork;
        if (error.code == NSURLErrorCancelled) issue = MiniSightAIIssueCancelled;
        else if (error.code == NSURLErrorTimedOut) issue = MiniSightAIIssueTimeout;
        [self answerIssue:issue status:status retryAfterSeconds:retryAfter generation:generation];
        return;
    }
    if (status < 200 || status >= 300) {
        [self answerIssue:MiniSightAIIssueHTTP status:status retryAfterSeconds:retryAfter generation:generation];
        return;
    }
    // Defence in depth; the transport already enforces this during receipt.
    if (data.length > kMiniSightAIMaxResponseBytes) {
        [self finishIssue:MiniSightAIIssueEmpty status:status text:@"AI 回复超过 2 MiB，已停止接收"
            retryAfterSeconds:0 generation:generation];
        return;
    }

    id object = data.length ? [NSJSONSerialization JSONObjectWithData:data options:0 error:NULL] : nil;
    id choices = [object isKindOfClass:NSDictionary.class] ? object[@"choices"] : nil;
    id first = [choices isKindOfClass:NSArray.class] && [choices count] ? choices[0] : nil;
    id reason = [first isKindOfClass:NSDictionary.class] ? first[@"finish_reason"] : nil;
    NSString *safeReason = MiniSightAISafeFinishReason(reason);
    BOOL hasReasoning = MiniSightAIHasReasoning(object, 0);
    NSUInteger nodesLeft = kMiniSightAIMaxJSONNodes;
    MSChatValue *root = object ? MiniSightAIValueFromObject(MiniSightAIContentObject(object), 0, &nodesLeft) : NULL;
    char text[MSCHAT_TEXT_MAX] = {0};
    MSChatExtractResult extract = MSChatExtractReplyText(root, text, sizeof text);
    if (root) MSChatValueFree(root);
    NSString *reply = [NSString stringWithUTF8String:text] ?: @"";
    reply = [reply stringByTrimmingCharactersInSet:NSCharacterSet.whitespaceAndNewlineCharacterSet];
    if (extract == MSChatExtractOK && !reply.length) extract = MSChatExtractEmpty;
    MiniSightAIDiag(self.diagnosticClientID, @"ai parse generation=%lu result=%ld contentlen=%lu finish_reason=%@ reasoning=%d",
        generation, (long)extract, (unsigned long)reply.length, safeReason, hasReasoning);
    MSDiagEvent(@"ai", @"parse", extract == MSChatExtractOK && reply.length ? @"ok" : @"failed", @{ @"request": requestID, @"issue": @(extract), @"chars": @(reply.length), @"reasoning": @(hasReasoning), @"finish": safeReason });
    if (extract != MSChatExtractOK || !reply.length) {
        if ([safeReason isEqualToString:@"length"]) {
            [self finishIssue:MiniSightAIIssueEmpty status:status text:@"回复额度用完但未生成正文"
                retryAfterSeconds:0 generation:generation];
        } else {
            [self answerIssue:MiniSightAIIssueEmpty status:status retryAfterSeconds:0 generation:generation];
        }
        return;
    }

    MSChatContextAdd(&_history, MSChatRoleAssistant, reply.UTF8String);
    [self finishIssue:MiniSightAIIssueNone status:status text:reply
        retryAfterSeconds:0 generation:generation];
}

/// One terminal path for preflight, network, deadline and explicit cancel.
- (void)answerIssue:(MiniSightAIIssue)issue
             status:(long)status
    retryAfterSeconds:(NSTimeInterval)retryAfterSeconds
         generation:(unsigned long)generation {
    NSString *message = [NSString stringWithUTF8String:MSChatMessageForIssue((MSChatIssue)issue, status)];
    [self finishIssue:issue status:status text:message ?: @"AI 这次没回话"
        retryAfterSeconds:retryAfterSeconds generation:generation];
}

- (void)finishIssue:(MiniSightAIIssue)issue
             status:(long)status
               text:(NSString *)text
    retryAfterSeconds:(NSTimeInterval)retryAfterSeconds
         generation:(unsigned long)generation {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    if (!MSChatAcceptsReply(&_requestState, generation)) return;
    void (^handler)(MiniSightAIReply *) = self.pendingCompletion;
    self.pendingCompletion = nil;
    if (issue == MiniSightAIIssueCancelled) MSChatCancelRequest(&_requestState);
    else MSChatFinishRequest(&_requestState, generation);
    [self clearRequestResources];

    MiniSightAIReply *reply = [[MiniSightAIReply alloc] init];
    reply.issue = issue;
    reply.status = status;
    reply.requestID = [NSString stringWithFormat:@"%@/%lu", self.diagnosticClientID, generation];
    reply.text = issue == MiniSightAIIssueNone ? (text ?: @"") : @"";
    reply.displayText = text.length ? text : @"AI 这次没回话";
    reply.retryAfterSeconds = status == 429
        ? MIN(kMiniSightAIRetryAfterMax, MAX(0.0, retryAfterSeconds)) : 0;
    MiniSightAIDiag(self.diagnosticClientID, @"ai finish generation=%lu issue=%ld status=%ld text_len=%lu retry_s=%.0f callback=%d",
        generation, (long)issue, status, (unsigned long)reply.text.length,
        reply.retryAfterSeconds, handler != nil);
    MSDiagEvent(@"ai", @"finish", issue == MiniSightAIIssueNone ? @"ok" : (issue == MiniSightAIIssueCancelled ? @"cancelled" : @"failed"), @{ @"request": reply.requestID, @"issue": @(issue), @"http": @(status), @"chars": @(reply.text.length), @"enabled": @(handler != nil) });
    // State, timer, transport and the old completion are cleared first. A
    // handler may immediately send again without a late packet killing it.
    if (handler) handler(reply);
}

#pragma mark Cancel / lifecycle

- (void)cancel {
    NSCAssert([NSThread isMainThread], @"MiniSightAI is main-thread only");
    if (!self.sending) {
        self.pendingCompletion = nil;
        [self clearRequestResources];
        return;
    }
    const unsigned long generation = _requestState.generation;
    [self answerIssue:MiniSightAIIssueCancelled status:0 retryAfterSeconds:0 generation:generation];
}

- (void)dealloc {
    if (_timeoutBlock) dispatch_block_cancel(_timeoutBlock);
    [_transport invalidate];
    _pendingCompletion = nil;
}

@end
