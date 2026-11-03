// Pure C chat policy shared by the tweak and the Linux regression test.
// No Foundation, no UIKit, no private frameworks: this file must compile with
// `cc -std=c11` on the host so the networking/parsing decisions stay testable.
//
// It owns four things and nothing else:
//   1. endpoint construction/validation from the App-written ai.json URL;
//   2. bounded conversation context (system message + newest turns, 12 / 6000);
//   3. a tiny JSON value tree plus content extraction (string / text parts);
//   4. issue classification, Chinese display text and the send/cancel state.
#ifndef MINISIGHT_CHAT_CORE_H
#define MINISIGHT_CHAT_CORE_H

#include <stddef.h>

#define MSCHAT_MAX_MESSAGES 12
#define MSCHAT_MAX_CHARS 6000
#define MSCHAT_CONTENT_MAX 4096
#define MSCHAT_ENDPOINT_MAX 1024
#define MSCHAT_TEXT_MAX 8192


typedef enum {
    MSChatURLOK = 0,
    MSChatURLEmpty,
    MSChatURLBadScheme,
    MSChatURLNoHost,
    MSChatURLUserInfo,
    MSChatURLFragment,
    MSChatURLBadChars,
    MSChatURLTooLong,
    MSChatURLMalformed
} MSChatURLError;

// Trim, validate, and normalize an App-written base URL.
// Rules mirror the 0.3.5 speak-line builder: http(s) only, a host is required,
// user/password and fragments are rejected, trailing slashes are removed, an
// empty path becomes /v1/chat/completions, an existing path is kept and gets
// /chat/completions appended unless it already ends with it. Query is kept.
// Returns MSChatURLOK and a NUL-terminated endpoint in `out` on success.
MSChatURLError MSChatBuildEndpoint(const char *base, char *out, size_t capacity);


typedef enum {
    MSChatRoleSystem = 0,
    MSChatRoleUser,
    MSChatRoleAssistant
} MSChatRole;

typedef struct {
    MSChatRole role;
    char content[MSCHAT_CONTENT_MAX];
} MSChatMessage;

typedef struct {
    MSChatMessage items[MSCHAT_MAX_MESSAGES];
    size_t count;
    size_t chars;
} MSChatContext;

void MSChatContextInit(MSChatContext *ctx);
// Append a message (UTF-8, NUL-terminated, trimmed). The oldest non-system
// message is dropped first when either the 12-message or 6000-character budget
// is exceeded; the system message(s) and the newest turn are always kept.
// Returns 1 when stored, 0 on bad arguments.
int MSChatContextAdd(MSChatContext *ctx, MSChatRole role, const char *content);
// Role name used in the JSON body.
const char *MSChatRoleName(MSChatRole role);


typedef enum {
    MSChatValueNull = 0,
    MSChatValueString,
    MSChatValueArray,
    MSChatValueDict
} MSChatValueType;

typedef struct MSChatValue MSChatValue;

struct MSChatValue {
    MSChatValueType type;
    char *string;                 // MSChatValueString
    MSChatValue **items;          // MSChatValueArray
    size_t count;
    size_t item_capacity;
    char **keys;                  // MSChatValueDict
    MSChatValue **values;
    size_t pair_count;
    size_t pair_capacity;
};

MSChatValue *MSChatValueNewString(const char *text);
MSChatValue *MSChatValueNewArray(size_t capacity);
MSChatValue *MSChatValueNewDict(size_t capacity);
MSChatValue *MSChatValueNewNull(void);
int MSChatArrayAppend(MSChatValue *array, MSChatValue *value);
int MSChatDictSet(MSChatValue *dict, const char *key, MSChatValue *value);
void MSChatValueFree(MSChatValue *value);


typedef enum {
    MSChatExtractOK = 0,
    MSChatExtractEmpty,
    MSChatExtractShape
} MSChatExtractResult;

// Extract choices[0].message.content (also accepts choices[0].text,
// output_text/output and candidates[0]). String content is copied, array
// content joins every text part with a newline, dictionary content recurses
// through text / content / parts exactly like MiniSightAITextFromObject did.
MSChatExtractResult MSChatExtractReplyText(const MSChatValue *root,
                                           char *out, size_t capacity);


typedef enum {
    MSChatIssueNone = 0,
    MSChatIssueConfig,
    MSChatIssueURL,
    MSChatIssueTimeout,
    MSChatIssueNetwork,
    MSChatIssueHTTP,
    MSChatIssueEmpty,
    MSChatIssueCancelled
} MSChatIssue;

typedef enum {
    MSChatStatusNone = 0,
    MSChatStatusOK,
    MSChatStatusAuth,
    MSChatStatusNotFound,
    MSChatStatusRateLimited,
    MSChatStatusBadRequest,
    MSChatStatusServer,
    MSChatStatusOther
} MSChatStatusClass;

MSChatStatusClass MSChatClassifyStatus(long status);
MSChatIssue MSChatIssueForStatus(long status);
// A displayable Simplified-Chinese sentence; never contains the API key.
const char *MSChatMessageForIssue(MSChatIssue issue, long status);


typedef struct {
    unsigned long generation;
    int sending;
    int cancelled;
} MSChatRequestState;

void MSChatStateInit(MSChatRequestState *state);
// Returns 1 when a request may start, 0 when one is already in flight.
int MSChatBeginRequest(MSChatRequestState *state);
// Returns 1 when an in-flight request existed and was cancelled.
int MSChatCancelRequest(MSChatRequestState *state);
// True only for the newest, non-cancelled generation.
int MSChatAcceptsReply(const MSChatRequestState *state, unsigned long generation);
void MSChatFinishRequest(MSChatRequestState *state, unsigned long generation);

#endif
