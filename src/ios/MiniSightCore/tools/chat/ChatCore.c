#define _POSIX_C_SOURCE 200809L
#include "ChatCore.h"

#include <ctype.h>
#include <stdlib.h>
#include <string.h>

#define MSCHAT_MAX_DEPTH 8


static int msc_is_space(char c) {
    return c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == '\f' || c == '\v';
}

static const char *msc_skip_space(const char *s) {
    while (s && *s && msc_is_space(*s)) ++s;
    return s;
}

static size_t msc_trimmed_length(const char *s, const char **start) {
    const char *first = msc_skip_space(s);
    const char *last = first + strlen(first);
    while (last > first && msc_is_space(last[-1])) --last;
    *start = first;
    return (size_t)(last - first);
}

static int msc_equal_nocase(const char *a, const char *b, size_t length) {
    size_t i;
    for (i = 0; i < length; ++i) {
        if (tolower((unsigned char)a[i]) != tolower((unsigned char)b[i])) return 0;
    }
    return 1;
}

// Copy at most capacity-1 bytes, backing off to a UTF-8 code point boundary so
// a long Chinese reply cannot end in a broken lead byte.
static size_t msc_copy_utf8(char *dst, size_t capacity, const char *src) {
    size_t length;
    if (!dst || capacity == 0) return 0;
    if (!src) src = "";
    length = strlen(src);
    if (length >= capacity) {
        length = capacity - 1;
        while (length > 0 && ((unsigned char)src[length] & 0xC0) == 0x80) --length;
    }
    memcpy(dst, src, length);
    dst[length] = '\0';
    return length;
}

static int msc_append(char *out, size_t capacity, size_t *used, const char *text) {
    size_t length;
    if (!out || !used || !text) return 0;
    length = strlen(text);
    if (*used >= capacity - 1) return 0;
    if (length > capacity - 1 - *used) {
        length = capacity - 1 - *used;
        while (length > 0 && ((unsigned char)text[length] & 0xC0) == 0x80) --length;
    }
    memcpy(out + *used, text, length);
    *used += length;
    out[*used] = '\0';
    return length > 0;
}


MSChatURLError MSChatBuildEndpoint(const char *base, char *out, size_t capacity) {
    const char *start = NULL;
    const char *scheme_end;
    const char *authority;
    const char *authority_end;
    const char *query;
    size_t length;
    size_t scheme_length;
    size_t prefix_length;
    size_t path_length;
    size_t used = 0;
    size_t i;

    if (!out || capacity == 0) return MSChatURLMalformed;
    out[0] = '\0';
    if (!base) return MSChatURLEmpty;
    length = msc_trimmed_length(base, &start);
    if (length == 0) return MSChatURLEmpty;
    if (length >= capacity) return MSChatURLTooLong;

    for (i = 0; i < length; ++i) {
        unsigned char c = (unsigned char)start[i];
        if (c <= 0x20 || c == 0x7F) return MSChatURLBadChars;
    }
    if (memchr(start, '#', length)) return MSChatURLFragment;

    scheme_end = NULL;
    for (i = 0; i + 2 < length; ++i) {
        if (start[i] == ':' && start[i + 1] == '/' && start[i + 2] == '/') {
            scheme_end = start + i;
            break;
        }
    }
    if (!scheme_end) return MSChatURLMalformed;
    scheme_length = (size_t)(scheme_end - start);
    if (!(scheme_length == 4 && msc_equal_nocase(start, "http", 4)) &&
        !(scheme_length == 5 && msc_equal_nocase(start, "https", 5))) {
        return MSChatURLBadScheme;
    }

    authority = scheme_end + 3;
    authority_end = authority;
    while (authority_end < start + length && *authority_end != '/' && *authority_end != '?') {
        ++authority_end;
    }
    if (authority_end == authority) return MSChatURLNoHost;
    if (memchr(authority, '@', (size_t)(authority_end - authority))) return MSChatURLUserInfo;

    {
        const char *host = authority;
        const char *colon = memchr(authority, ':', (size_t)(authority_end - authority));
        if (colon && colon == host) return MSChatURLNoHost;
        if (colon && colon + 1 == authority_end) return MSChatURLNoHost;
    }

    // Reserved characters must survive verbatim: copy the scheme lowercase,
    // the authority as written, then the normalized path and the query.
    prefix_length = (size_t)(authority_end - start);
    if (prefix_length + 32 >= capacity) return MSChatURLTooLong;
    for (i = 0; i < scheme_length; ++i) out[used++] = (char)tolower((unsigned char)start[i]);
    memcpy(out + used, "://", 3);
    used += 3;
    memcpy(out + used, authority, (size_t)(authority_end - authority));
    used += (size_t)(authority_end - authority);
    out[used] = '\0';

    query = NULL;
    path_length = 0;
    if (*authority_end == '/') {
        const char *path_end = authority_end;
        while (path_end < start + length && *path_end != '?') ++path_end;
        if (path_end < start + length && *path_end == '?') query = path_end;
        path_length = (size_t)(path_end - authority_end);
    } else if (*authority_end == '?') {
        query = authority_end;
    }
    while (path_length > 0 && authority_end[path_length - 1] == '/') --path_length;

    if (path_length == 0) {
        if (!msc_append(out, capacity, &used, "/v1/chat/completions")) return MSChatURLTooLong;
    } else {
        if (used + path_length + 20 >= capacity) return MSChatURLTooLong;
        memcpy(out + used, authority_end, path_length);
        used += path_length;
        out[used] = '\0';
        if (path_length < 17 || strcmp(out + used - 17, "/chat/completions") != 0) {
            if (!msc_append(out, capacity, &used, "/chat/completions")) return MSChatURLTooLong;
        }
    }
    if (query) {
        if (!msc_append(out, capacity, &used, query)) return MSChatURLTooLong;
    }
    return MSChatURLOK;
}


void MSChatContextInit(MSChatContext *ctx) {
    if (!ctx) return;
    memset(ctx, 0, sizeof(*ctx));
}

const char *MSChatRoleName(MSChatRole role) {
    switch (role) {
        case MSChatRoleSystem: return "system";
        case MSChatRoleAssistant: return "assistant";
        case MSChatRoleUser:
        default: return "user";
    }
}

static void msc_context_remove(MSChatContext *ctx, size_t index) {
    if (!ctx || index >= ctx->count) return;
    ctx->chars -= strlen(ctx->items[index].content);
    memmove(&ctx->items[index], &ctx->items[index + 1],
            (ctx->count - index - 1) * sizeof(ctx->items[0]));
    --ctx->count;
    memset(&ctx->items[ctx->count], 0, sizeof(ctx->items[0]));
}

// Drop the oldest non-system message that is not `protected_index`.
static int msc_context_drop_oldest(MSChatContext *ctx, size_t protected_index) {
    size_t i;
    for (i = 0; i < ctx->count; ++i) {
        if (i == protected_index) continue;
        if (ctx->items[i].role == MSChatRoleSystem) continue;
        msc_context_remove(ctx, i);
        return 1;
    }
    return 0;
}

int MSChatContextAdd(MSChatContext *ctx, MSChatRole role, const char *content) {
    const char *start = NULL;
    size_t length;
    size_t index;

    if (!ctx || !content) return 0;
    length = msc_trimmed_length(content, &start);
    if (length == 0) return 0;

    if (role == MSChatRoleSystem) {
        if (ctx->count == MSCHAT_MAX_MESSAGES) {
            msc_context_remove(ctx, ctx->count - 1);
        }
        memmove(&ctx->items[1], &ctx->items[0], ctx->count * sizeof(ctx->items[0]));
        index = 0;
        ++ctx->count;
    } else {
        if (ctx->count >= MSCHAT_MAX_MESSAGES && !msc_context_drop_oldest(ctx, (size_t)-1)) return 0;
        index = ctx->count++;
    }

    memset(&ctx->items[index], 0, sizeof(ctx->items[index]));
    ctx->items[index].role = role;
    ctx->chars += msc_copy_utf8(ctx->items[index].content,
                                sizeof(ctx->items[index].content), start);

    while (ctx->chars > MSCHAT_MAX_CHARS && msc_context_drop_oldest(ctx, index)) {
        if (index > 0) --index;
    }
    return 1;
}


MSChatValue *MSChatValueNewString(const char *text) {
    MSChatValue *value = calloc(1, sizeof(*value));
    if (!value) return NULL;
    value->type = MSChatValueString;
    value->string = strdup(text ? text : "");
    if (!value->string) { free(value); return NULL; }
    return value;
}

MSChatValue *MSChatValueNewNull(void) {
    MSChatValue *value = calloc(1, sizeof(*value));
    if (value) value->type = MSChatValueNull;
    return value;
}

MSChatValue *MSChatValueNewArray(size_t capacity) {
    MSChatValue *value = calloc(1, sizeof(*value));
    if (!value) return NULL;
    value->type = MSChatValueArray;
    value->item_capacity = capacity ? capacity : 4;
    value->items = calloc(value->item_capacity, sizeof(*value->items));
    if (!value->items) { free(value); return NULL; }
    return value;
}

MSChatValue *MSChatValueNewDict(size_t capacity) {
    MSChatValue *value = calloc(1, sizeof(*value));
    if (!value) return NULL;
    value->type = MSChatValueDict;
    value->pair_capacity = capacity ? capacity : 4;
    value->keys = calloc(value->pair_capacity, sizeof(*value->keys));
    value->values = calloc(value->pair_capacity, sizeof(*value->values));
    if (!value->keys || !value->values) {
        free(value->keys); free(value->values); free(value);
        return NULL;
    }
    return value;
}

int MSChatArrayAppend(MSChatValue *array, MSChatValue *value) {
    if (!array || array->type != MSChatValueArray || !value) return 0;
    if (array->count == array->item_capacity) {
        size_t next = array->item_capacity * 2 + 1;
        MSChatValue **grown = realloc(array->items, next * sizeof(*grown));
        if (!grown) return 0;
        array->items = grown;
        array->item_capacity = next;
    }
    array->items[array->count++] = value;
    return 1;
}

int MSChatDictSet(MSChatValue *dict, const char *key, MSChatValue *value) {
    char *copy;
    if (!dict || dict->type != MSChatValueDict || !key || !value) return 0;
    copy = strdup(key);
    if (!copy) return 0;
    if (dict->pair_count == dict->pair_capacity) {
        size_t next = dict->pair_capacity * 2 + 1;
        char **keys = realloc(dict->keys, next * sizeof(*keys));
        MSChatValue **values;
        if (!keys) { free(copy); return 0; }
        dict->keys = keys;
        values = realloc(dict->values, next * sizeof(*values));
        if (!values) { free(copy); return 0; }
        dict->values = values;
        dict->pair_capacity = next;
    }
    dict->keys[dict->pair_count] = copy;
    dict->values[dict->pair_count] = value;
    ++dict->pair_count;
    return 1;
}

void MSChatValueFree(MSChatValue *value) {
    size_t i;
    if (!value) return;
    for (i = 0; i < value->count; ++i) MSChatValueFree(value->items[i]);
    for (i = 0; i < value->pair_count; ++i) {
        free(value->keys[i]);
        MSChatValueFree(value->values[i]);
    }
    free(value->string);
    free(value->items);
    free(value->keys);
    free(value->values);
    free(value);
}


static const MSChatValue *msc_dict_get(const MSChatValue *dict, const char *key) {
    size_t i;
    if (!dict || dict->type != MSChatValueDict || !key) return NULL;
    for (i = 0; i < dict->pair_count; ++i) {
        if (strcmp(dict->keys[i], key) == 0) return dict->values[i];
    }
    return NULL;
}

static void msc_append_trimmed(char *out, size_t capacity, size_t *used, const char *text) {
    const char *start = NULL;
    size_t length = msc_trimmed_length(text ? text : "", &start);
    char *block;
    if (length == 0) return;
    block = malloc(length + 1);
    if (!block) return;
    memcpy(block, start, length);
    block[length] = '\0';
    if (*used > 0) msc_append(out, capacity, used, "\n");
    msc_append(out, capacity, used, block);
    free(block);
}

static void msc_append_text(const MSChatValue *value, char *out, size_t capacity,
                            size_t *used, int depth) {
    size_t i;
    if (!value || depth > MSCHAT_MAX_DEPTH || *used >= capacity - 1) return;
    switch (value->type) {
        case MSChatValueString:
            msc_append_trimmed(out, capacity, used, value->string);
            break;
        case MSChatValueArray:
            for (i = 0; i < value->count; ++i) {
                msc_append_text(value->items[i], out, capacity, used, depth + 1);
            }
            break;
        case MSChatValueDict: {
            const MSChatValue *direct = msc_dict_get(value, "text");
            if (!direct) direct = msc_dict_get(value, "output_text");
            if (direct) msc_append_text(direct, out, capacity, used, depth + 1);
            if (*used > 0) break;
            direct = msc_dict_get(value, "content");
            if (direct) msc_append_text(direct, out, capacity, used, depth + 1);
            if (*used > 0) break;
            direct = msc_dict_get(value, "parts");
            if (direct) msc_append_text(direct, out, capacity, used, depth + 1);
            break;
        }
        case MSChatValueNull:
        default:
            break;
    }
}

MSChatExtractResult MSChatExtractReplyText(const MSChatValue *root,
                                           char *out, size_t capacity) {
    const MSChatValue *choices;
    const MSChatValue *first;
    const MSChatValue *candidate;
    const MSChatValue *text;
    size_t used = 0;

    if (!out || capacity == 0) return MSChatExtractShape;
    out[0] = '\0';
    if (!root || root->type != MSChatValueDict) return MSChatExtractShape;

    choices = msc_dict_get(root, "choices");
    if (choices && choices->type == MSChatValueArray && choices->count > 0) {
        first = choices->items[0];
        if (first && first->type == MSChatValueDict) {
            candidate = msc_dict_get(first, "message");
            if (candidate) msc_append_text(candidate, out, capacity, &used, 0);
            if (used == 0) {
                candidate = msc_dict_get(first, "text");
                if (candidate) msc_append_text(candidate, out, capacity, &used, 0);
            }
        } else {
            msc_append_text(first, out, capacity, &used, 0);
        }
        if (used > 0) return MSChatExtractOK;
    }

    text = msc_dict_get(root, "output_text");
    if (!text) text = msc_dict_get(root, "output");
    if (text) msc_append_text(text, out, capacity, &used, 0);
    if (used > 0) return MSChatExtractOK;

    candidate = msc_dict_get(root, "candidates");
    if (candidate && candidate->type == MSChatValueArray && candidate->count > 0) {
        msc_append_text(candidate->items[0], out, capacity, &used, 0);
    }
    return used > 0 ? MSChatExtractOK : MSChatExtractEmpty;
}


MSChatStatusClass MSChatClassifyStatus(long status) {
    if (status >= 200 && status < 300) return MSChatStatusOK;
    if (status == 401 || status == 403) return MSChatStatusAuth;
    if (status == 404) return MSChatStatusNotFound;
    if (status == 429) return MSChatStatusRateLimited;
    if (status == 400 || status == 409 || status == 422) return MSChatStatusBadRequest;
    if (status >= 500 && status < 600) return MSChatStatusServer;
    if (status > 0) return MSChatStatusOther;
    return MSChatStatusNone;
}

MSChatIssue MSChatIssueForStatus(long status) {
    if (status == 0) return MSChatIssueNetwork;
    return MSChatClassifyStatus(status) == MSChatStatusOK ? MSChatIssueNone : MSChatIssueHTTP;
}

const char *MSChatMessageForIssue(MSChatIssue issue, long status) {
    switch (issue) {
        case MSChatIssueNone:
            return "";
        case MSChatIssueConfig:
            return "AI 配置不完整：请在 MiniSight 设置里填写地址、Key 和模型";
        case MSChatIssueURL:
            return "AI 地址不合法：需要 http(s) 地址，且不能带用户名、密码或 # 片段";
        case MSChatIssueTimeout:
            return "AI 超时了（30 秒没回），请检查网络后重试";
        case MSChatIssueNetwork:
            return "连不上 AI 服务，请检查网络或代理";
        case MSChatIssueEmpty:
            return "AI 返回了空回复，请重试";
        case MSChatIssueCancelled:
            return "已取消";
        case MSChatIssueHTTP:
            switch (MSChatClassifyStatus(status)) {
                case MSChatStatusOK:
                    return "";
                case MSChatStatusAuth:
                    return "AI 鉴权失败（HTTP 401/403），请检查 Key";
                case MSChatStatusNotFound:
                    return "AI 地址不对（HTTP 404），请检查设置里的地址";
                case MSChatStatusRateLimited:
                    return "AI 被限流（HTTP 429），等一会儿再试";
                case MSChatStatusBadRequest:
                    return "AI 说请求不合法（HTTP 400/409/422），请检查模型名";
                case MSChatStatusServer:
                    return "AI 服务出错（HTTP 500/5xx），过会儿再试";
                case MSChatStatusNone:
                    return "AI 这次没回话";
                case MSChatStatusOther:
                default:
                    return "AI 报错（HTTP 状态异常）";
            }
        default:
            return "AI 这次没回话";
    }
}


void MSChatStateInit(MSChatRequestState *state) {
    if (!state) return;
    memset(state, 0, sizeof(*state));
}

int MSChatBeginRequest(MSChatRequestState *state) {
    if (!state || state->sending) return 0;
    state->sending = 1;
    state->cancelled = 0;
    ++state->generation;
    return 1;
}

int MSChatCancelRequest(MSChatRequestState *state) {
    if (!state || !state->sending) return 0;
    state->sending = 0;
    state->cancelled = 1;
    ++state->generation;
    return 1;
}

int MSChatAcceptsReply(const MSChatRequestState *state, unsigned long generation) {
    return state && state->sending && !state->cancelled && state->generation == generation;
}

void MSChatFinishRequest(MSChatRequestState *state, unsigned long generation) {
    if (!state) return;
    if (state->generation != generation) return;
    state->sending = 0;
}
