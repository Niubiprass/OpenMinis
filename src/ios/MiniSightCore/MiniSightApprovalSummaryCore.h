/* Bounded approval descriptions. Pure C11; never executes or expands input.
 * This production header is byte-identical in the App and plugin. Swift uses
 * an NSString/NSDictionary bridge; tests/approval exercises this same core.
 * Supported: literal shell words, quotes/escapes, ; && || |, simple redirects,
 * sh -c, sudo, mcp-root, minis-mcp-cli call (key=value / scalar --input JSON).
 * Expansion, scripts, control flow and budget overflow remain UNKNOWN, even
 * when a readable step was recognized. This is display policy, not authority.
 */
#ifndef MINISIGHT_APPROVAL_SUMMARY_CORE_H
#define MINISIGHT_APPROVAL_SUMMARY_CORE_H
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <stdio.h>
#include <ctype.h>

/* The same bounded parser is compiled as strict C11 in host tests and as
 * Objective-C++ through Tweak.xm.  Keep zero-initializers and calloc typed in
 * both languages without weakening the warning policy. */
#ifdef __cplusplus
#define MSA_ZERO_INIT {}
#define MSA_TOKEN_INIT(TEXT, KIND, DYNAMIC) MSAToken{(TEXT), (KIND), (DYNAMIC)}
#define MSA_CALLOC(TYPE, COUNT) static_cast<TYPE *>(calloc((COUNT), sizeof(TYPE)))
#define MSA_STATIC_ASSERT static_assert
#else
#define MSA_ZERO_INIT {0}
#define MSA_TOKEN_INIT(TEXT, KIND, DYNAMIC) (MSAToken){(TEXT), (KIND), (DYNAMIC)}
#define MSA_CALLOC(TYPE, COUNT) calloc((COUNT), sizeof(TYPE))
#define MSA_STATIC_ASSERT _Static_assert
#endif

#define MSA_INPUT_LIMIT 65536
#define MSA_WORD_LIMIT 8192
#define MSA_TOKEN_LIMIT 256
#define MSA_STEP_LIMIT 64
#define MSA_DEPTH_LIMIT 4
#define MSA_PATH_LIMIT 1024
#define MSA_COPY_LIMIT 16

typedef enum {
    MSA_SCREENSHOT, MSA_TAP, MSA_SWIPE, MSA_RECORD, MSA_LAUNCH,
    MSA_KEY, MSA_MUTE, MSA_SETTING, MSA_INSTALL, MSA_UNINSTALL,
    MSA_USERSPACE, MSA_RESPRING, MSA_REBOOT, MSA_LOG, MSA_APPINFO,
    MSA_DIR, MSA_READ, MSA_UI, MSA_CLIPREAD, MSA_CLIPWRITE,
    MSA_COPY, MSA_MOVE, MSA_DELETE, MSA_EDIT, MSA_WRITE, MSA_NETWORK, MSA_OUTPUT,
    MSA_SEARCH, MSA_EXEC, MSA_DEVICE, MSA_INPUT, MSA_PROCESS, MSA_NOOP, MSA_EFFECT_COUNT
} MSAEffect;
typedef struct { const char *title, *purpose; int write; } MSARule;
static const MSARule msa_rules[] = {
    {"允许截屏？", "读取当前屏幕画面并返回截图。", 0},
    {"允许点击屏幕？", "模拟点击，可能触发界面上的按钮。", 1},
    {"允许滑动屏幕？", "模拟一次屏幕滑动。", 1},
    {"允许录屏？", "录制屏幕画面，可能生成录像文件。", 1},
    {"允许打开 App？", "把指定应用切到前台。", 1},
    {"允许模拟按键？", "触发指定的系统按键操作。", 1},
    {"允许切换静音？", "更改设备静音状态。", 1},
    {"允许修改系统设置？", "调整屏幕亮度或音量。", 1},
    {"允许安装 App 或软件包？", "安装指定应用或软件包；DEB 安装还可能重启 SpringBoard。", 1},
    {"允许卸载 App 或软件包？", "移除指定应用或软件包；DEB 卸载还可能重启 SpringBoard。", 1},
    {"允许重启用户空间？", "重启用户空间，当前界面和插件会暂时中断。", 1},
    {"允许重启桌面？", "重启 SpringBoard，当前界面和插件会暂时中断。", 1},
    {"允许重启设备？", "重启设备，当前任务会中断。", 1},
    {"允许读取日志？", "读取系统日志或崩溃报告。", 0},
    {"允许读取 App 信息？", "查看已安装应用的列表或详情。", 0},
    {"允许查看目录？", "列出指定文件夹中的项目。", 0},
    {"允许读取文件或文本？", "读取或筛选文件及文本内容。", 0},
    {"允许读取界面信息？", "读取当前界面元素或屏幕信息。", 0},
    {"允许读取剪贴板？", "读取当前剪贴板内容。", 0},
    {"允许写入剪贴板？", "替换当前剪贴板内容。", 1},
    {"允许复制文件？", "把文件复制到目标路径，可能覆盖已有文件。", 1},
    {"允许移动或重命名文件？", "移动或重命名文件，可能覆盖目标文件。", 1},
    {"允许删除文件？", "移除指定文件或目录。", 1},
    {"允许修改文件内容？", "修改指定目标文件的内容。", 1},
    {"允许写入文件？", "创建、覆盖或追加写入目标文件。", 1},
    {"允许发起网络请求？", "连接网络，可能发送数据或下载并写入文件。", 1},
    {"允许输出文本？", "向命令输出通道返回文本或状态信息。", 0},
    {"允许查找文件或内容？", "在指定路径中搜索文件、目录或符合条件的文本。", 0},
    {"允许执行命令？", "运行命令指定的程序；无法确认的部分按可能产生影响处理。", 1},
    {"允许读取设备信息？", "读取设备、前台应用或运行状态。", 0},
    {"允许输入或控制界面？", "输入文字、按键或执行长按、拖动等界面操作。", 1},
    {"允许管理运行中的 App？", "结束指定应用进程，可能导致该应用关闭。", 1},
    {"允许处理辅助命令？", "处理命令的成功或失败状态，不读取或修改设备数据。", 0}
};
MSA_STATIC_ASSERT(sizeof(msa_rules) / sizeof(msa_rules[0]) == MSA_EFFECT_COUNT,
                  "approval rule table must stay aligned with MSAEffect");
/* Canonical effect order and exact tool names are shared with the Swift port. */
typedef struct { const char *name; MSAEffect effect; } MSATool;
static const MSATool msa_tools[] = {
    {"screenshot", MSA_SCREENSHOT}, {"tap_screen", MSA_TAP}, {"tap_element", MSA_TAP},
    {"swipe_screen", MSA_SWIPE}, {"record_screen", MSA_RECORD}, {"start_recording", MSA_RECORD},
    {"stop_recording", MSA_RECORD}, {"launch_app", MSA_LAUNCH}, {"open_url", MSA_LAUNCH},
    {"press_home", MSA_KEY}, {"press_power", MSA_KEY}, {"press_volume_up", MSA_KEY},
    {"press_volume_down", MSA_KEY}, {"wake_and_home", MSA_KEY}, {"press_key", MSA_INPUT},
    {"toggle_mute", MSA_MUTE}, {"set_brightness", MSA_SETTING}, {"set_volume", MSA_SETTING},
    {"install_app", MSA_INSTALL}, {"uninstall_app", MSA_UNINSTALL},
    {"get_syslog", MSA_LOG}, {"get_crash_logs", MSA_LOG}, {"read_crash_log", MSA_LOG},
    {"get_app_info", MSA_APPINFO}, {"list_apps", MSA_APPINFO}, {"list_running_apps", MSA_DEVICE},
    {"list_dir", MSA_DIR}, {"read_file", MSA_READ}, {"write_file", MSA_WRITE}, {"edit_file", MSA_EDIT},
    {"get_ui_elements", MSA_UI}, {"get_screen_info", MSA_DEVICE}, {"get_device_info", MSA_DEVICE},
    {"get_frontmost_app", MSA_DEVICE}, {"get_element_at_point", MSA_UI},
    {"wait_for_element", MSA_UI}, {"wait_for_disappear", MSA_UI},
    {"ocr_screen", MSA_UI}, {"describe_screen", MSA_UI},
    {"get_brightness", MSA_DEVICE}, {"get_volume", MSA_DEVICE},
    {"get_clipboard", MSA_CLIPREAD}, {"set_clipboard", MSA_CLIPWRITE},
    {"kill_app", MSA_PROCESS}, {"input_text", MSA_INPUT}, {"type_text", MSA_INPUT},
    {"long_press", MSA_INPUT}, {"double_tap", MSA_INPUT}, {"drag_and_drop", MSA_INPUT}
};
typedef struct {
    uint64_t effects;
    int unknown, is_write, temp_copy_edit, original_write;
    const char *title, *risk;
    char purpose[4096];
} MSApprovalSummary;
typedef struct { char source[MSA_PATH_LIMIT], dest[MSA_PATH_LIMIT]; } MSACopy;
typedef struct {
    uint64_t effects;
    int unknown, steps, copies, edits, only_temp, original;
    int text_filter, result_sorted, result_dedup, file_search;
    MSACopy copy[MSA_COPY_LIMIT];
} MSAState;
typedef struct { char *text; int kind, dynamic; } MSAToken;
enum { MSA_WORD, MSA_BREAK, MSA_PIPE, MSA_AND, MSA_COND, MSA_IN, MSA_OUT, MSA_APPEND, MSA_DUP };
/* strnlen is not C11. Never scan beyond the display budget. */
static int msa_fits(const char *s) {
    if (!s) return 0;
    for (size_t i = 0; i <= MSA_INPUT_LIMIT; i++) if (!s[i]) return 1;
    return 0;
}
static int msa_eq(const char *a, const char *b) { return strcmp(a, b) == 0; }
static int msa_prefix(const char *s, const char *prefix) { return strncmp(s, prefix, strlen(prefix)) == 0; }
static const char *msa_base(const char *s) { const char *p = strrchr(s, '/'); return p ? p + 1 : s; }
static void msa_effect(MSAState *s, MSAEffect e) { s->effects |= UINT64_C(1) << e; }
static int msa_has(const MSAState *s, MSAEffect e) { return (s->effects & (UINT64_C(1) << e)) != 0; }
static int msa_temp(const char *p) {
    return msa_prefix(p, "/tmp/") || msa_prefix(p, "/var/tmp/") ||
        msa_prefix(p, "/private/tmp/") || msa_prefix(p, "/private/var/tmp/");
}
static int msa_path(const char *p) {
    size_t n = strlen(p);
    return n > 1 && n < MSA_PATH_LIMIT && p[0] == '/' && p[n-1] != '/' &&
        !strstr(p, "//") && !strstr(p, "/../") && !strstr(p, "/./") &&
        !msa_eq(msa_base(p), "..") && !msa_eq(msa_base(p), ".");
}
static int msa_original(const char *p) {
    return !msa_temp(p) && msa_eq(msa_base(p), "cn.zgbb.inject.system.plist");
}
static void msa_destination(MSAState *s, const char *p, int edit) {
    if (msa_original(p)) s->original = 1;
    if (!edit && p[0] && p[strlen(p)-1] == '/') s->only_temp = 0;
    if (!msa_path(p)) s->only_temp = 0;
    if (!edit) { if (!msa_temp(p)) s->only_temp = 0; return; }
    int found = 0;
    for (int i = 0; i < s->copies; i++) if (msa_eq(p, s->copy[i].dest)) found = 1;
    if (!found) s->only_temp = 0;
    s->edits++;
}
static void msa_shell(MSAState *s, const char *input, int depth);

/* On failure retain complete tokens, but the unfinished step is never trusted.
 * Each token's NUL is budgeted separately: many empty quotes can expand storage. */
static int msa_lex(const char *input, MSAToken *tokens, char *storage, int *failed) {
    size_t i = 0, used = 0; int count = 0;
    *failed = 0;
#define MSA_LEX_FAIL() do { *failed = 1; return count; } while (0)
    while (input[i]) {
        if (input[i] == ' ' || input[i] == '\t' || input[i] == '\r') { i++; continue; }
        if (count == MSA_TOKEN_LIMIT) MSA_LEX_FAIL();
        char c = input[i]; int kind = MSA_WORD;
        if (c == '#') { while (input[i] && input[i] != '\n') i++; continue; }
        if (c == '`' || c == '(' || c == ')' || c == '{' || c == '}') MSA_LEX_FAIL();
        if (c == '&' && input[i+1] != '&') MSA_LEX_FAIL();
        if (c == ';' || c == '\n' || c == '&' || c == '|') {
            kind = c == '|' ? MSA_PIPE : MSA_BREAK;
            if ((c == '&' || c == '|') && input[i+1] == c) { kind = c == '&' ? MSA_AND : MSA_COND; i++; }
            i++; tokens[count++] = MSA_TOKEN_INIT(NULL, kind, 0); continue;
        }
        /* Optional literal fd, e.g. 2>/tmp/log or 2>&1. */
        size_t op = i; while (isdigit((unsigned char)input[op])) op++;
        if (input[op] == '<' || input[op] == '>') {
            char r = input[op++]; kind = r == '<' ? MSA_IN : MSA_OUT;
            if (input[op] == r) { if (r == '<') MSA_LEX_FAIL(); op++; kind = MSA_APPEND; }
            if (input[op] == '&') { op++; kind = MSA_DUP; }
            if (input[op] == '|' || input[op] == '<' || input[op] == '>') MSA_LEX_FAIL();
            i = op; tokens[count++] = MSA_TOKEN_INIT(NULL, kind, 0); continue;
        }
        size_t start = used; int quote = 0, dynamic = 0, touched = 0;
        while ((c = input[i])) {
            if (!quote && (c == ' ' || c == '\t' || c == '\r' || c == '\n' || c == ';' ||
                c == '&' || c == '|' || c == '<' || c == '>')) break;
            if (!quote && (c == '(' || c == ')' || c == '{' || c == '}')) MSA_LEX_FAIL();
            touched = 1;
            if (c == '\'' && quote != '"') { quote = quote == '\'' ? 0 : '\''; i++; continue; }
            if (c == '"' && quote != '\'') { quote = quote == '"' ? 0 : '"'; i++; continue; }
            if (c == '\\' && quote != '\'') {
                char next = input[i+1]; if (!next) MSA_LEX_FAIL();
                if (next == '\n') { i += 2; continue; }
                if (!quote || next == '$' || next == '`' || next == '"' || next == '\\') {
                    c = next; i += 2;
                } else { i++; }
            } else {
                if (quote != '\'' && (c == '$' || c == '`')) dynamic = 1;
                if (!quote && (c == '*' || c == '?' || c == '[' || c == '~')) dynamic = 1;
                i++;
            }
            if (used - start >= MSA_WORD_LIMIT || used >= MSA_INPUT_LIMIT) MSA_LEX_FAIL();
            storage[used++] = c;
        }
        if (quote || !touched || used > MSA_INPUT_LIMIT) MSA_LEX_FAIL();
        storage[used++] = 0;
        tokens[count++] = MSA_TOKEN_INIT(storage + start, MSA_WORD, dynamic);
    }
#undef MSA_LEX_FAIL
    return count;
}

typedef struct { const char *keys[32], *values[32]; int count; } MSAPairs;
static int msa_pair(MSAPairs *p, const char *key, const char *value) {
    for (int i = 0; i < p->count; i++) if (msa_eq(key, p->keys[i])) return 0;
    if (p->count == 32) return 0;
    p->keys[p->count] = key; p->values[p->count++] = value; return 1;
}
static const char *msa_value(const MSAPairs *p, const char *key) {
    for (int i = 0; i < p->count; i++) if (msa_eq(key, p->keys[i])) return p->values[i];
    return NULL;
}
static void msa_space(const char **p) { while (**p == ' ' || **p == '\t' || **p == '\n' || **p == '\r') (*p)++; }
static int msa_hex(unsigned char c) {
    if (c >= '0' && c <= '9') return c - '0';
    if (c >= 'a' && c <= 'f') return c - 'a' + 10;
    if (c >= 'A' && c <= 'F') return c - 'A' + 10;
    return -1;
}
static int msa_hex4(const char **p, unsigned *value) {
    *value = 0;
    for (int i = 0; i < 4; i++) {
        int h = msa_hex((unsigned char)**p);
        if (h < 0) return 0;
        *value = (*value << 4) | (unsigned)h; (*p)++;
    }
    return 1;
}
/* Exact JSON grammar, not locale-dependent strtod (which accepts 01/1./hex). */
static int msa_number(const char *p) {
    if (*p == '-') p++;
    if (*p == '0') p++;
    else { if (*p < '1' || *p > '9') return 0; while (isdigit((unsigned char)*p)) p++; }
    if (*p == '.') { p++; if (!isdigit((unsigned char)*p)) return 0; while (isdigit((unsigned char)*p)) p++; }
    if (*p == 'e' || *p == 'E') {
        p++; if (*p == '+' || *p == '-') p++;
        if (!isdigit((unsigned char)*p)) return 0;
        while (isdigit((unsigned char)*p)) p++;
    }
    return !*p;
}
/* Flat scalar objects only; decoded bytes cannot exceed the source length. */
static char *msa_json_string(const char **p, char **out) {
    if (*(*p)++ != '"') return NULL;
    char *start = *out;
    while (**p && **p != '"') {
        unsigned char c = (unsigned char)*(*p)++;
        if (c < 32) return NULL;
        if (c == '\\') {
            c = (unsigned char)*(*p)++;
            switch (c) {
                case '"': case '\\': case '/': break;
                case 'n': c = '\n'; break; case 'r': c = '\r'; break;
                case 't': c = '\t'; break; case 'b': c = '\b'; break; case 'f': c = '\f'; break;
                case 'u': {
                    unsigned u;
                    if (!msa_hex4(p, &u) || u == 0) return NULL;
                    if (u >= 0xd800 && u <= 0xdbff) {
                        if (**p != '\\') return NULL;
                        (*p)++; if (**p != 'u') return NULL; (*p)++;
                        unsigned lo; if (!msa_hex4(p, &lo) || lo < 0xdc00 || lo > 0xdfff) return NULL;
                        u = 0x10000 + ((u - 0xd800) << 10) + lo - 0xdc00;
                    } else if (u >= 0xdc00 && u <= 0xdfff) return NULL;
                    if (u < 0x80) *(*out)++ = (char)u;
                    else if (u < 0x800) { *(*out)++ = (char)(0xc0 | (u >> 6)); *(*out)++ = (char)(0x80 | (u & 63)); }
                    else if (u < 0x10000) {
                        *(*out)++ = (char)(0xe0 | (u >> 12)); *(*out)++ = (char)(0x80 | ((u >> 6) & 63)); *(*out)++ = (char)(0x80 | (u & 63));
                    } else {
                        *(*out)++ = (char)(0xf0 | (u >> 18)); *(*out)++ = (char)(0x80 | ((u >> 12) & 63));
                        *(*out)++ = (char)(0x80 | ((u >> 6) & 63)); *(*out)++ = (char)(0x80 | (u & 63));
                    }
                    continue;
                }
                default: return NULL;
            }
        }
        *(*out)++ = (char)c;
    }
    if (*(*p)++ != '"') return NULL;
    *(*out)++ = 0; return start;
}
static int msa_json(const char *input, MSAPairs *pairs, char *storage) {
    const char *p = input; char *out = storage;
    msa_space(&p); if (*p++ != '{') return 0;
    msa_space(&p); if (*p == '}') { p++; msa_space(&p); return !*p; }
    for (int n = 0; n < 32; n++) {
        msa_space(&p); if (*p != '"') return 0;
        char *key = msa_json_string(&p, &out); if (!key) return 0;
        msa_space(&p); if (*p++ != ':') return 0; msa_space(&p);
        char *value;
        if (*p == '"') { value = msa_json_string(&p, &out); if (!value) return 0; }
        else {
            value = out; const char *start = p;
            while (*p && *p != ',' && *p != '}' && !isspace((unsigned char)*p)) *out++ = *p++;
            if (p == start) return 0;
            *out++ = 0;
            if (!msa_eq(value, "true") && !msa_eq(value, "false") && !msa_eq(value, "null") && !msa_number(value)) return 0;
        }
        if (!msa_pair(pairs, key, value)) return 0;
        msa_space(&p); if (*p == '}') { p++; msa_space(&p); return !*p; }
        if (*p++ != ',') return 0;
    }
    return 0;
}
static int msa_tool(MSAState *s, const char *tool, const MSAPairs *p, int depth) {
    if (msa_eq(tool, "run_command")) {
        const char *cmd = msa_value(p, "command");
        if (cmd) msa_shell(s, cmd, depth + 1); else s->unknown = 1;
        return 1;
    }
    for (size_t i = 0; i < sizeof(msa_tools)/sizeof(msa_tools[0]); i++) {
        if (!msa_eq(tool, msa_tools[i].name)) continue;
        MSAEffect e = msa_tools[i].effect; msa_effect(s, e);
        if (e == MSA_WRITE || e == MSA_EDIT) {
            const char *dest = msa_value(p, "path");
            if (dest) msa_destination(s, dest, e == MSA_EDIT); else s->only_temp = 0;
        }
        if (msa_rules[e].write && e != MSA_WRITE && e != MSA_EDIT) s->only_temp = 0;
        return 1;
    }
    return 0;
}
static void msa_cli(MSAState *s, char **a, int n, int depth) {
    if (n < 4 || !msa_eq(a[1], "call")) { s->unknown = 1; return; }
    MSAPairs p = MSA_ZERO_INIT; char *json = MSA_CALLOC(char, MSA_INPUT_LIMIT + 1); int saw_json = 0, valid = json != NULL;
    for (int i = 4; i < n && valid; i++) {
        if (msa_eq(a[i], "--pretty")) continue;
        if (msa_eq(a[i], "--input")) {
            if (++i == n || saw_json++) { valid = 0; break; }
            valid = msa_json(a[i], &p, json); continue;
        }
        char *eq = strchr(a[i], '=');
        if (!eq || eq == a[i] || a[i][0] == '-') { valid = 0; break; }
        *eq = 0; valid = msa_pair(&p, a[i], eq + 1);
    }
    if (!valid) s->unknown = 1;
    else if (!msa_tool(s, a[3], &p, depth)) s->unknown = 1;
    free(json);
}
/* Literal mode flags only. Side-effecting grep options (e.g. --pre) and
 * unknown options fall back to unknown instead of asserting read-only. */
static int msa_read_flags(char **a, int n, const char *letters) {
    for (int i = 1; i < n; i++) {
        if (msa_eq(a[i], "--")) break;
        if (a[i][0] != '-' || !a[i][1]) continue;
        if (a[i][1] == '-') return 0;
        for (int k = 1; a[i][k]; k++) if (!strchr(letters, a[i][k]) && !isdigit((unsigned char)a[i][k])) return 0;
    }
    return 1;
}
static int msa_literals(char **a, int n, const char *flags, char **paths) {
    int count = 0, options = 1;
    for (int i = 1; i < n; i++) {
        if (options && msa_eq(a[i], "--")) { options = 0; continue; }
        if (options && a[i][0] == '-' && a[i][1]) {
            for (int k = 1; a[i][k]; k++) if (!strchr(flags, a[i][k])) return -1;
            continue;
        }
        paths[count++] = a[i];
    }
    return count;
}
static void msa_copy_move(MSAState *s, char **a, int n, int moving) {
    msa_effect(s, moving ? MSA_MOVE : MSA_COPY);
    char *paths[MSA_TOKEN_LIMIT]; int count = msa_literals(a, n, moving ? "finv" : "afinpRv", paths);
    if (count < 2) { s->unknown = 1; s->only_temp = 0; return; }
    const char *dest = paths[count-1]; msa_destination(s, dest, 0);
    if (moving) for (int i = 0; i < count-1; i++) if (msa_original(paths[i])) s->original = 1;
    /* Copying a temp file back to a directory may overwrite the named plist. */
    if (!msa_temp(dest) && msa_base(dest)[0] == 0) {
        for (int i = 0; i < count-1; i++) if (msa_original(paths[i]) || msa_eq(msa_base(paths[i]), "cn.zgbb.inject.system.plist")) s->original = 1;
    }
    /* A simple non-recursive copy of the named plist to an explicit temp
     * filename is the only provenance claim. Existing symlinks aren't known. */
    int recursive = 0;
    for (int i = 1; i < n; i++) if (a[i][0] == '-' && (strchr(a[i], 'R') || strchr(a[i], 'a'))) recursive = 1;
    if (!moving && count == 2 && !recursive && msa_path(paths[0]) && msa_original(paths[0]) && msa_path(dest) && msa_temp(dest)) {
        if (s->copies < MSA_COPY_LIMIT) {
            snprintf(s->copy[s->copies].source, MSA_PATH_LIMIT, "%s", paths[0]);
            snprintf(s->copy[s->copies++].dest, MSA_PATH_LIMIT, "%s", dest);
        } else { s->unknown = 1; s->only_temp = 0; }
    } else s->only_temp = 0;
}
static int msa_sed_script(const char *v) {
    /* Literal insert/append/change text. Do not interpret text as shell code. */
    if ((v[0] == 'a' || v[0] == 'i' || v[0] == 'c') && v[1] == '\\' && v[2] == '\n') return 1;
    if (msa_eq(v, "p") || msa_eq(v, "d")) return 1;
    if (v[0] != 's' || !v[1] || isalnum((unsigned char)v[1]) || v[1] == '\\') return 0;
    char delim = v[1]; int separators = 0; size_t k = 2;
    for (; v[k]; k++) {
        if (v[k] == '\\' && v[k+1]) { k++; continue; }
        if (v[k] == delim && ++separators == 2) { k++; break; }
    }
    if (separators != 2) return 0;
    for (; v[k]; k++) if (!strchr("gIp0123456789", v[k])) return 0;
    return 1;
}
static void msa_sed(MSAState *s, char **a, int n) {
    int in_place = 0, script = 0, files = 0, options = 1, valid = 1;
    char *paths[MSA_TOKEN_LIMIT];
    for (int i = 1; i < n; i++) {
        const char *v = a[i];
        if (options && msa_eq(v, "--")) { options = 0; continue; }
        if (options && (msa_eq(v, "-i") || msa_prefix(v, "-i") || msa_prefix(v, "--in-place"))) {
            in_place = 1;
            if (msa_eq(v, "-i") && i+1 < n && !a[i+1][0]) i++; /* BSD -i '' */
            if (!msa_eq(v, "-i") && !msa_prefix(v, "-i.") && !msa_eq(v, "--in-place")) valid = 0;
            continue;
        }
        if (options && msa_eq(v, "-e")) {
            if (++i == n) { valid = 0; break; }
            if (!msa_sed_script(a[i])) valid = 0;
            script++; continue;
        }
        if (options && (msa_eq(v, "-n") || msa_eq(v, "-E") || msa_eq(v, "-r"))) continue;
        if (options && v[0] == '-') { valid = 0; continue; }
        if (!script) { script = 1; if (!msa_sed_script(v)) valid = 0; }
        else paths[files++] = a[i];
    }
    if (in_place) {
        msa_effect(s, MSA_EDIT);
        if (script && files) for (int i = 0; i < files; i++) msa_destination(s, paths[i], 1);
        else { s->unknown = 1; s->only_temp = 0; }
    } else msa_effect(s, MSA_READ);
    /* sed e/w and arbitrary programs can execute or write additional paths. */
    if (!valid || !script) { s->unknown = 1; s->only_temp = 0; }
}

static int msa_assignment(const char *v) {
    if (!isalpha((unsigned char)*v) && *v != '_') return 0;
    for (v++; isalnum((unsigned char)*v) || *v == '_'; v++) {}
    return *v == '=';
}
static int msa_control(const char *v) {
    static const char *const words[] = {"if", "then", "elif", "else", "fi", "for", "while", "until", "do", "done", "case", "esac", "function", "!", "time"};
    for (size_t i = 0; i < sizeof(words)/sizeof(words[0]); i++) if (msa_eq(v, words[i])) return 1;
    return 0;
}
static void msa_step(MSAState *s, char **a, int n, int depth) {
    if (!n) return;
    if (++s->steps > MSA_STEP_LIMIT) { s->unknown = 1; return; }
    while (n && msa_assignment(a[0])) { s->unknown = 1; s->only_temp = 0; a++; n--; }
    if (!n) return;
    /* A preceding control word makes execution conditional/unknown, but a
     * literal simple action after if/then is still useful to the reader. */
    while (n && msa_control(a[0])) { s->unknown = 1; s->only_temp = 0; a++; n--; }
    if (!n) return;
    const char *exe = msa_base(a[0]);
    if (msa_eq(exe, "env")) {
        s->unknown = 1; s->only_temp = 0;
        if (n > 1 && a[1][0] != '-') msa_step(s, a+1, n-1, depth);
        return;
    }
    if (msa_eq(exe, "minis-mcp-cli")) { msa_cli(s, a, n, depth); return; }
    if (msa_eq(exe, "mcp-root") || msa_eq(exe, "sudo")) {
        if (n > 1 && a[1][0] != '-') msa_step(s, a+1, n-1, depth);
        else s->unknown = 1;
        return;
    }
    if (msa_eq(exe, "sh") || msa_eq(exe, "bash") || msa_eq(exe, "zsh")) {
        if (n == 3 && msa_eq(a[1], "-c")) msa_shell(s, a[2], depth+1);
        else s->unknown = 1;
        return;
    }
    if (msa_eq(exe, "mcp-logreader")) { msa_effect(s, MSA_LOG); return; }
    if (msa_eq(exe, "find")) {
        int deleting = 0, executing = 0, file_output = 0;
        s->file_search = 1;
        for (int i = 1; i < n; i++) {
            if (msa_eq(a[i], "-delete")) deleting = 1;
            if (msa_eq(a[i], "-exec") || msa_eq(a[i], "-execdir") || msa_eq(a[i], "-ok") || msa_eq(a[i], "-okdir")) executing = 1;
            if (msa_eq(a[i], "-fprint") || msa_eq(a[i], "-fprint0") || msa_eq(a[i], "-fprintf")) file_output = 1;
        }
        if (executing) { msa_effect(s, MSA_EXEC); s->only_temp = 0; }
        else if (deleting) { msa_effect(s, MSA_DELETE); s->only_temp = 0; }
        else if (file_output) { msa_effect(s, MSA_WRITE); s->only_temp = 0; }
        else msa_effect(s, MSA_SEARCH);
        return;
    }
    if (msa_eq(exe, "sort") || msa_eq(exe, "uniq")) {
        int valid = 1, output_path = -1, is_sort = msa_eq(exe, "sort"), unique = 0;
        const char *short_flags = is_sort ? "bdfgiMhnorRscuVz" : "cdiu";
        for (int i = 1; i < n; i++) {
            if (msa_eq(a[i], "-o") || msa_eq(a[i], "--output")) {
                if (++i >= n) { valid = 0; break; }
                output_path = i;
            } else if (msa_prefix(a[i], "--output=")) {
                output_path = i;
            } else if (a[i][0] == '-' && a[i][1] == '-') {
                if (msa_eq(a[i], "--unique")) unique = 1;
                else if (!msa_eq(a[i], "--reverse") && !msa_eq(a[i], "--numeric-sort")) valid = 0;
            } else if (a[i][0] == '-' && a[i][1]) {
                for (int k = 1; a[i][k]; k++) {
                    if (!strchr(short_flags, a[i][k])) valid = 0;
                    if (!is_sort && a[i][k] == 'u') unique = 1;
                    if (is_sort && a[i][k] == 'u') unique = 1;
                }
            }
        }
        if (!valid) { s->unknown = 1; s->only_temp = 0; return; }
        if (output_path >= 0) {
            const char *dest = a[output_path];
            if (msa_prefix(dest, "--output=")) dest += 9;
            msa_effect(s, MSA_WRITE); msa_destination(s, dest, 0); s->only_temp = 0;
        } else {
            s->result_sorted = is_sort ? 1 : 0;
            s->result_dedup = is_sort ? unique : 1;
            msa_effect(s, MSA_READ);
        }
        return;
    }
    if (msa_eq(exe, "cp") || msa_eq(exe, "mv")) { msa_copy_move(s, a, n, msa_eq(exe, "mv")); return; }
    if (msa_eq(exe, "sed")) { msa_sed(s, a, n); return; }
    if (msa_eq(exe, "rm")) {
        msa_effect(s, MSA_DELETE); s->only_temp = 0;
        if (!msa_read_flags(a, n, "dfirvRIPW")) s->unknown = 1;
        return;
    }
    if (msa_eq(exe, "plutil")) {
        if (n >= 3 && (msa_eq(a[1], "-p") || msa_eq(a[1], "-lint"))) {
            msa_effect(s, MSA_READ);
            for (int i = 2; i < n; i++) if (a[i][0] == '-') s->unknown = 1;
        } else if (n >= 4 && (msa_eq(a[1], "-replace") || msa_eq(a[1], "-insert") || msa_eq(a[1], "-remove"))) {
            msa_effect(s, MSA_EDIT);
            const char *dest = a[n-1];
            for (int i = 2; i < n; i++) if (msa_eq(a[i], "-o")) { s->unknown = 1; s->only_temp = 0; return; }
            msa_destination(s, dest, 1);
        } else s->unknown = 1;
        return;
    }
    if (msa_eq(exe, "defaults")) {
        if (n >= 3 && (msa_eq(a[1], "read") || msa_eq(a[1], "read-type"))) msa_effect(s, MSA_READ);
        else if (n >= 3 && (msa_eq(a[1], "write") || msa_eq(a[1], "delete"))) {
            msa_effect(s, MSA_EDIT); msa_destination(s, a[2], 1);
        } else s->unknown = 1;
        return;
    }
    if (msa_eq(exe, "reboot")) {
        msa_effect(s, n == 2 && msa_eq(a[1], "userspace") ? MSA_USERSPACE : MSA_REBOOT);
        s->only_temp = 0; return;
    }
    if (msa_eq(exe, "launchctl") && n == 3 && msa_eq(a[1], "reboot")) {
        if (msa_eq(a[2], "userspace")) msa_effect(s, MSA_USERSPACE);
        else if (msa_eq(a[2], "system")) msa_effect(s, MSA_REBOOT);
        else s->unknown = 1;
        s->only_temp = 0; return;
    }
    if (msa_eq(exe, "sbreload")) { msa_effect(s, MSA_RESPRING); s->only_temp = 0; return; }
    if (msa_eq(exe, "killall") && n >= 2 && msa_eq(a[n-1], "SpringBoard")) {
        int valid = 1;
        for (int i = 1; i < n-1; i++) if (!msa_eq(a[i], "-9") && !msa_eq(a[i], "-TERM") && !msa_eq(a[i], "-KILL")) valid = 0;
        if (!valid) s->unknown = 1;
        msa_effect(s, MSA_RESPRING); s->only_temp = 0; return;
    }
    if (msa_eq(exe, "dpkg")) {
        if (n >= 3 && (msa_eq(a[1], "-i") || msa_eq(a[1], "--install"))) msa_effect(s, MSA_INSTALL);
        else if (n >= 3 && (msa_eq(a[1], "-r") || msa_eq(a[1], "-P") || msa_eq(a[1], "--remove") || msa_eq(a[1], "--purge"))) msa_effect(s, MSA_UNINSTALL);
        else s->unknown = 1;
        s->only_temp = 0; return;
    }
    if (msa_eq(exe, "tee") || msa_eq(exe, "touch") || msa_eq(exe, "mkdir")) {
        msa_effect(s, MSA_WRITE); s->only_temp = 0;
        char *paths[MSA_TOKEN_LIMIT]; int count = msa_literals(a, n, msa_eq(exe, "tee") ? "ai" : msa_eq(exe, "mkdir") ? "pv" : "acm", paths);
        if (count < 1) s->unknown = 1;
        else for (int i = 0; i < count; i++) msa_destination(s, paths[i], 0);
        return;
    }
    if (msa_eq(exe, "curl") || msa_eq(exe, "wget")) { msa_effect(s, MSA_NETWORK); s->only_temp = 0; return; }
    const char *flags = NULL; MSAEffect e = MSA_READ;
    if (msa_eq(exe, "cat")) flags = "benstuvAET";
    else if (msa_eq(exe, "grep")) flags = "EFGivnrlLhHsSoqwxcabeABCm";
    else if (msa_eq(exe, "head")) flags = "ncvq";
    else if (msa_eq(exe, "tail")) flags = "ncfFqvr";
    else if (msa_eq(exe, "ls")) { flags = "laAdhHiknprRstux1FGLTU@eO"; e = MSA_DIR; }
    else if (msa_eq(exe, "wc")) flags = "clmwL";
    else if (msa_eq(exe, "uname")) flags = "amnprsv";
    if (flags) {
        msa_effect(s, e);
        if (msa_eq(exe, "grep")) s->text_filter = 1;
        if (!msa_read_flags(a, n, flags)) s->unknown = 1;
        return;
    }
    if (msa_eq(exe, "log") && n >= 2 && (msa_eq(a[1], "show") || msa_eq(a[1], "stream"))) {
        msa_effect(s, MSA_LOG);
        for (int i = 2; i < n; i++) if (msa_eq(a[i], "--output") || msa_prefix(a[i], "--output=")) { msa_effect(s, MSA_WRITE); s->only_temp = 0; }
        return;
    }
    if (msa_eq(exe, "echo") || msa_eq(exe, "printf")) {
        msa_effect(s, MSA_OUTPUT); return;
    }
    if (msa_eq(exe, "pwd") || msa_eq(exe, "true") || msa_eq(exe, "false") || msa_eq(exe, ":")) {
        msa_effect(s, MSA_NOOP); return;
    }
    s->unknown = 1;
}
/* Dynamic arguments cannot establish destination provenance. A literal
 * executable can still identify a possible effect (e.g. cp "$src" "$dst"). */
static void msa_dynamic_step(MSAState *s, char **a, int n, int depth) {
    s->unknown = 1; s->only_temp = 0;
    while (n && msa_assignment(a[0])) { a++; n--; }
    if (!n) return;
    const char *exe = msa_base(a[0]);
    if (msa_eq(exe, "sudo") || msa_eq(exe, "mcp-root") || msa_eq(exe, "env")) {
        if (n > 1 && a[1][0] != '-') msa_dynamic_step(s, a+1, n-1, depth);
        return;
    }
    if (msa_eq(exe, "minis-mcp-cli") && n >= 4 && msa_eq(a[1], "call")) {
        MSAPairs empty = MSA_ZERO_INIT;
        if (!msa_eq(a[3], "run_command")) (void)msa_tool(s, a[3], &empty, depth);
        return;
    }
    MSAState *possible = MSA_CALLOC(MSAState, 1);
    if (!possible) return;
    msa_step(possible, a, n, depth);
    s->effects |= possible->effects; /* no path/copy/original claims */
    free(possible);
}
static void msa_shell(MSAState *s, const char *input, int depth) {
    if (depth > MSA_DEPTH_LIMIT || !msa_fits(input)) { s->unknown = 1; return; }
    MSAToken *tokens = MSA_CALLOC(MSAToken, MSA_TOKEN_LIMIT);
    char *storage = MSA_CALLOC(char, MSA_INPUT_LIMIT + 1);
    if (!tokens || !storage) { s->unknown = 1; free(tokens); free(storage); return; }
    int failed = 0, count = msa_lex(input, tokens, storage, &failed);
    if (failed) { s->unknown = 1; s->only_temp = 0; }
    char *args[MSA_TOKEN_LIMIT]; int n = 0, pending = 0, dynamic = 0, dynamic_exe = 0, step_tokens = 0;
    for (int i = 0; i <= count; i++) {
        int kind = i < count ? tokens[i].kind : MSA_BREAK;
        if (i == count || kind == MSA_BREAK || kind == MSA_PIPE || kind == MSA_AND || kind == MSA_COND) {
            if (!(i == count && failed)) {
                if (n && !dynamic_exe) {
                    if (dynamic) msa_dynamic_step(s, args, n, depth);
                    else msa_step(s, args, n, depth);
                } else if (pending || (i < count && (kind == MSA_PIPE || kind == MSA_AND || kind == MSA_COND))) s->unknown = 1;
            }
            if (i == count && pending && !step_tokens) s->unknown = 1;
            if (kind == MSA_COND || kind == MSA_PIPE) {
                /* OR/pipeline provenance depends on branch/process selection.
                 * A successful && chain is deterministic: a later edit is
                 * allowed to inherit the preceding literal temp copy. */
                s->copies = 0; s->only_temp = 0;
            }
            n = 0; dynamic = 0; dynamic_exe = 0; step_tokens = 0;
            pending = i < count && (kind == MSA_PIPE || kind == MSA_AND || kind == MSA_COND);
            continue;
        }
        MSAToken t = tokens[i]; step_tokens++;
        if (t.kind != MSA_WORD) {
            if (++i == count || tokens[i].kind != MSA_WORD) { s->unknown = 1; s->only_temp = 0; break; }
            MSAToken target = tokens[i];
            if (target.dynamic) { s->unknown = 1; s->only_temp = 0; }
            if (t.kind == MSA_DUP) {
                if (!msa_eq(target.text, "1") && !msa_eq(target.text, "2") && !msa_eq(target.text, "-")) s->unknown = 1;
            } else if (t.kind == MSA_OUT || t.kind == MSA_APPEND) {
                if (!msa_eq(target.text, "/dev/null")) {
                    msa_effect(s, MSA_WRITE);
                    if (!target.dynamic) msa_destination(s, target.text, 0);
                    else s->only_temp = 0;
                    /* Redirection may replace a previously tracked copy. */
                    s->copies = 0;
                }
            }
            continue;
        }
        if (t.dynamic) {
            s->unknown = 1; s->only_temp = 0; dynamic = 1;
            if (!n && !msa_assignment(t.text)) dynamic_exe = 1;
        }
        args[n++] = t.text;
    }
    free(tokens); free(storage);
}
static void msa_append(char *out, size_t capacity, const char *text) {
    size_t n = strlen(out); if (n < capacity) snprintf(out+n, capacity-n, "%s", text);
}
static MSApprovalSummary MSApprovalDescribe(const char *command) {
    MSApprovalSummary out = MSA_ZERO_INIT; MSAState state = MSA_ZERO_INIT; state.only_temp = 1;
    if (!msa_fits(command) || !command[0]) state.unknown = 1;
    else msa_shell(&state, command, 0);
    if (!state.effects) state.unknown = 1;
    out.effects = state.effects; out.unknown = state.unknown;
    out.original_write = state.original;
    out.temp_copy_edit = state.copies > 0 && state.edits > 0 && state.only_temp && !state.original && !state.unknown;
    int effects = 0;
    for (int i = 0; i < MSA_EFFECT_COUNT; i++) if (i != MSA_NOOP && msa_has(&state, (MSAEffect)i)) {
        effects++; if (msa_rules[i].write) out.is_write = 1;
    }
    out.is_write |= state.unknown;
    out.title = "允许执行设备命令？";
    if (out.temp_copy_edit) {
        out.title = "允许修改临时配置副本？";
        snprintf(out.purpose, sizeof(out.purpose), "按命令中的目标路径，将 RootHide 配置复制到临时文件并编辑该副本；未发现写回原路径的步骤。目标若为符号链接或目录，实际影响可能不同；执行结果仍需确认。");
        for (int i = 0; i < MSA_EFFECT_COUNT; i++) if (i != MSA_NOOP && i != MSA_COPY && i != MSA_EDIT && msa_has(&state, (MSAEffect)i)) {
            msa_append(out.purpose, sizeof(out.purpose), "\n");
            msa_append(out.purpose, sizeof(out.purpose), msa_rules[i].purpose);
        }
    } else {
        if (state.unknown) out.title = "允许执行需进一步确认的设备操作？";
        else if (state.original) out.title = "允许写入 RootHide 配置路径？";
        else if (effects > 1) out.title = "允许执行这些设备操作？";
        else if (effects == 0 && msa_has(&state, MSA_NOOP)) out.title = msa_rules[MSA_NOOP].title;
        else for (int i = 0; i < MSA_EFFECT_COUNT; i++)
            if (i != MSA_NOOP && msa_has(&state, (MSAEffect)i)) out.title = msa_rules[i].title;
        if (state.original) msa_append(out.purpose, sizeof(out.purpose), "已识别的写入目标包含 RootHide 配置路径，可能改变插件的加载行为。");
        int has_mutation = msa_has(&state, MSA_DELETE) || msa_has(&state, MSA_WRITE) ||
            msa_has(&state, MSA_EDIT) || msa_has(&state, MSA_EXEC);
        if (!has_mutation && state.text_filter && state.result_sorted && state.result_dedup) {
            msa_append(out.purpose, sizeof(out.purpose), "读取指定文件中的文本，筛选符合条件的内容，并对结果排序去重；不会修改原文件。");
        } else if (!has_mutation && state.text_filter && state.result_sorted) {
            msa_append(out.purpose, sizeof(out.purpose), "读取指定文件中的文本，筛选符合条件的内容并排序；不会修改原文件。");
        } else if (!has_mutation && state.text_filter && state.result_dedup) {
            msa_append(out.purpose, sizeof(out.purpose), "读取指定文件中的文本，筛选符合条件的内容并去重；不会修改原文件。");
        } else if (!has_mutation && state.text_filter) {
            msa_append(out.purpose, sizeof(out.purpose), "读取指定文件并筛选符合条件的文本；不会修改原文件。");
        } else if (state.result_sorted && state.result_dedup && !has_mutation) {
            msa_append(out.purpose, sizeof(out.purpose), "读取文本并排序去重；不会修改原文件。");
        } else if (state.result_sorted && !has_mutation) {
            msa_append(out.purpose, sizeof(out.purpose), "读取文本并排序；不会修改原文件。");
        } else if (state.result_dedup && !has_mutation) {
            msa_append(out.purpose, sizeof(out.purpose), "读取文本并去重；不会修改原文件。");
        } else if (state.file_search && !state.unknown && !has_mutation) {
            msa_append(out.purpose, sizeof(out.purpose), "在指定路径下查找符合条件的文件或目录；不会修改文件。");
        } else for (int i = 0; i < MSA_EFFECT_COUNT; i++) if (i != MSA_NOOP && msa_has(&state, (MSAEffect)i)) {
            if (out.purpose[0]) msa_append(out.purpose, sizeof(out.purpose), "\n");
            msa_append(out.purpose, sizeof(out.purpose), msa_rules[i].purpose);
        }
        if (!out.purpose[0] && msa_has(&state, MSA_NOOP) && !state.unknown)
            msa_append(out.purpose, sizeof(out.purpose), msa_rules[MSA_NOOP].purpose);
        if (state.unknown) {
            if (out.purpose[0]) msa_append(out.purpose, sizeof(out.purpose), "\n");
            msa_append(out.purpose, sizeof(out.purpose), "部分操作无法自动确认，可能会读取、修改或控制设备。请核对操作来源与内容后再决定。");
        }
    }
    out.risk = state.unknown ? "有未确认的操作 · 请仔细核对后决定" : out.is_write ?
        "会改变文件、界面或系统状态" : "只读取信息，不修改文件或系统设置";
    return out;
}
#endif
