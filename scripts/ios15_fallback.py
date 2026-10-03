#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
iOS 15 兜底修复脚本 (钉版本移植第三阶段)  v2-20260930
====================================================

运行时机: ios15_port_v2.py / ios15_runtime_fixes.py 之后, xcodebuild 之前。

这一版是对上一轮构建 (run 36704819641, 32 个真实错误) 的精确打击。上一轮的
教训写在各修复点旁边。核心认知:

  * 在 `@available(iOS 16, *)` 类型里, **普通** iOS16 初始化器/类型可用
    (已由 DisplayRepresentation / IntentItemCollection 未报错证实), 但
    `LocalizedStringResource(stringLiteral:)` 这种**协议见证初始化器**仍报
    "cannot convert 'String' to 'LocalizedStringResource'"。修法: 别显式调
    它, 直接在期望 LocalizedStringResource 的位置传字符串插值字面量
    (Apple 文档的 `UserAction(title: "Order items")` 写法)。
  * 新建 .swift 文件不会被编译 (不在 .pbxproj 里) —— 垫片必须写进**已有**文件。
  * 给"方法"标 @available 会把错误传染给调用点 —— 应改为在方法**内部**守卫。

所有变换幂等, 可重复运行。
"""
import sys
import os
import re

ROOT = sys.argv[1] if len(sys.argv) > 1 else "src/ios"


def read(p):
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def write(p, s):
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def _strip_swift_noise(src):
    """去掉 Swift 注释与字符串字面量, 只留可执行代码。

    【为什么需要】"段内是否有赋值"这类判据, 如果直接对原始文本做正则, 会被
    两类噪声骗到:
      - 注释里写 `// 缓存 = nil` 会被当成真赋值(markdown 式说明文字里
        这种写法很自然);
      - 字符串里出现 `=`(比如日志格式串)会被当成赋值。
    而"逐行白名单"更糟 —— v46 第一版就栽在这: 为了让正常代码通过, 白名单
    里堆了 11 条 continue 特例, 格式一变就误报, 写一个新语句就穿透。
    剥掉噪声后再做**语义级**的赋值识别, 判据才不受排版影响。
    """
    out = []
    i = 0
    n = len(src)
    while i < n:
        c = src[i]
        # 行注释
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        # 块注释(可嵌套, Swift 允许)
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            depth = 1
            i += 2
            while i < n and depth > 0:
                if src.startswith("/*", i):
                    depth += 1
                    i += 2
                elif src.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            continue
        # 多行字符串 """...""" —— 里面换行保留, 否则行号会错位
        if src.startswith('"""', i):
            j = src.find('"""', i + 3)
            j = n if j < 0 else j + 3
            out.append('""')
            i = j
            continue
        # 普通字符串
        if c == '"':
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == '"':
                    break
                i += 1
            i += 1
            out.append('""')
            continue
        out.append(c)
        i += 1
    return "".join(out)


def _brace_balance(src):
    """全文花括号平衡扫描(跳过注释/字符串)。返回 (净深度, 最深负值)。

    【为什么要有】v45 反向测试 F1 实跑教训: 在别处插一个永不闭合的函数,
    前面 7 条判据全部通过, 直到编译才炸。所以任何"段内结构正确"的判据
    都不足以保证产物能编译, 必须有一条**全文级**的结构兜底。
    """
    s = _strip_swift_noise(src)
    depth = 0
    low = 0
    for c in s:
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth < low:
                low = depth
    return depth, low


def edit(relpath, func, label=None):
    p = os.path.join(ROOT, relpath)
    if not os.path.isfile(p):
        print("  SKIP (缺文件):", relpath)
        return
    t = read(p)
    n = func(t)
    if n != t:
        write(p, n)
        print("  EDIT ✅", relpath, ("(" + label + ")") if label else "")
    else:
        print("  no-op  ", relpath, ("(" + label + ")") if label else "")


def edit_glob(pattern, func, label=None):
    """对 ROOT 下匹配 pattern 的文件做变换 (兼容层文件名/路径由 pbxproj 决定)。"""
    import glob as _glob
    hits = _glob.glob(os.path.join(ROOT, pattern), recursive=True)
    if not hits:
        print("  SKIP (glob 无命中):", pattern)
        return
    for p in hits:
        t = read(p)
        n = func(t)
        if n != t:
            write(p, n)
            print("  EDIT ✅", os.path.relpath(p, ROOT), ("(" + label + ")") if label else "")
        else:
            print("  no-op  ", os.path.relpath(p, ROOT), ("(" + label + ")") if label else "")


# ----------------------------------------------------------- 括号 / 字符串工具
def _skip_string(text, i):
    """text[i] 是引号, 返回字面量结束后下标; 处理多行串与 \\( 插值嵌套。"""
    n = len(text)
    if text.startswith('"""', i):
        j = i + 3
        while j < n:
            if text[j] == "\\" and j + 1 < n and text[j + 1] == "(":
                j = _skip_interp(text, j + 2)
                continue
            if text[j] == "\\":
                j += 2
                continue
            if text.startswith('"""', j):
                return j + 3
            j += 1
        return n
    j = i + 1
    while j < n:
        c = text[j]
        if c == "\\" and j + 1 < n and text[j + 1] == "(":
            j = _skip_interp(text, j + 2)
            continue
        if c == "\\":
            j += 2
            continue
        if c == '"':
            return j + 1
        j += 1
    return n


def _skip_interp(text, i):
    """i 指向 \\( 之后, 返回配对 ) 之后的下标。"""
    n = len(text)
    depth = 1
    while i < n:
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _match_delim(text, i):
    """text[i] 为 ( [ { 之一, 返回配对闭合符之后的下标; 配不平返回 None。

    跳过字符串 (含插值/多行) 与 `//` `/* */` 注释 —— 本项目注释里常出现
    `{`/`}` (例如 `// snapshot ({...})`), 不跳注释会误判括号配平。
    """
    pairs = {"(": ")", "[": "]", "{": "}"}
    if i >= len(text) or text[i] not in pairs:
        return None
    stack = [pairs[text[i]]]
    j = i + 1
    n = len(text)
    while j < n and stack:
        c = text[j]
        if c == "/" and j + 1 < n and text[j + 1] == "/":
            k = text.find("\n", j)
            j = n if k < 0 else k
            continue
        if c == "/" and j + 1 < n and text[j + 1] == "*":
            k = text.find("*/", j + 2)
            j = n if k < 0 else k + 2
            continue
        if c == '"':
            j = _skip_string(text, j)
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif c in ")]}":
            if stack[-1] == c:
                stack.pop()
            else:
                return None
        j += 1
    return j if not stack else None


# =====================================================================
# F1. UnifiedModelPicker: Duration / Task.sleep(for:) / ToolbarContentBuilder 分支
# =====================================================================
def _fix_toolbar_content(t):
    old = (
        "        if isMulti {\n"
        "            ToolbarItem(placement: .topBarLeading) {\n"
        "                Button(\"Cancel\") { dismiss() }\n"
        "            }\n"
        "            ToolbarItem(placement: .topBarTrailing) {\n"
        "                Button(\"Add (\\(selectedEntryIds.count))\") {\n"
        "                    config.onAddMulti?(selectedEntryIds)\n"
        "                    dismiss()\n"
        "                }\n"
        "                .font(.body.weight(.semibold))\n"
        "                .disabled(selectedEntryIds.isEmpty)\n"
        "            }\n"
        "        } else {\n"
        "            ToolbarItem(placement: .topBarTrailing) {\n"
        "                Button(\"Done\") { dismiss() }\n"
        "            }\n"
        "        }")
    new = (
        "        ToolbarItem(placement: .topBarTrailing) {\n"
        "            if isMulti {\n"
        "                Button(\"Cancel\") { dismiss() }\n"
        "                Button(\"Add (\\(selectedEntryIds.count))\") {\n"
        "                    config.onAddMulti?(selectedEntryIds)\n"
        "                    dismiss()\n"
        "                }\n"
        "                .font(.body.weight(.semibold))\n"
        "                .disabled(selectedEntryIds.isEmpty)\n"
        "            } else {\n"
        "                Button(\"Done\") { dismiss() }\n"
        "            }\n"
        "        }")
    return t.replace(old, new)


def fix_unified_model_picker(t):
    # 去掉可能由其它步骤加的 @available(iOS 16/17)
    t = re.sub(
        r"\n[ \t]*@available\(iOS\s+1[67][^\n]*\n(struct UnifiedModelPicker: View \{)",
        r"\n\1", t)
    # Duration (iOS 16) -> UInt64 纳秒 (iOS 15 可用)
    t = t.replace(
        "private static let searchDebounce: Duration = .milliseconds(120)",
        "private static let searchDebounce: UInt64 = 120_000_000")
    # Task.sleep(for:) 是 iOS 16 -> Task.sleep(nanoseconds:)
    t = t.replace("try? await Task.sleep(for: Self.searchDebounce)",
                  "try? await Task.sleep(nanoseconds: Self.searchDebounce)")
    t = t.replace("await Task.sleep(for: Self.searchDebounce)",
                  "await Task.sleep(nanoseconds: Self.searchDebounce)")
    # ToolbarContentBuilder 的 if/else (buildEither) iOS 15 不支持 -> 合并进一个 ToolbarItem
    t = _fix_toolbar_content(t)
    # 上一版: NavigationStack / .searchable(placement:) / .presentationDetents
    t = t.replace("NavigationStack {", "NavigationView {")
    t = re.sub(
        r'\.searchable\(text: \$searchText, placement: \.navigationBarDrawer\(displayMode: \.always\), prompt: "Search"\)',
        r'.searchable(text: $searchText, prompt: "Search")', t)
    t = re.sub(r"\n[ \t]*\.presentationDetents\(\[[^\]]*\]\)", "", t)
    return t


# =====================================================================
# F2. LocalizedStringResource(stringLiteral: X) -> "\(X)"
#     (显式调协议见证初始化器在 iOS15 部署目标下编译不过; 改用插值字面量隐式转换)
# =====================================================================
def _strip_lsr_for(t, typename):
    """把 typename(stringLiteral: EXPR) 换成 "\(EXPR)" (插值字面量隐式转 LSR)。

    同时覆盖 v2 的 strip_localizedstringresource 把
    `title: LocalizedStringResource(stringLiteral: X)` 误改成
    `title: String(stringLiteral: X)` 的污染 —— 因此 typename 也允许 String。
    """
    key = typename + "(stringLiteral:"
    out = t
    start = 0
    while True:
        idx = out.find(key, start)
        if idx < 0:
            break
        lp = idx + len(typename)
        rp = _match_delim(out, lp)
        if rp is None:
            start = idx + len(key)
            continue
        inner = out[lp + 1:rp - 1]              # "stringLiteral: EXPR"
        expr = inner.split(":", 1)[1].strip()
        repl = '"\\(' + expr + ')"'
        out = out[:idx] + repl + out[rp:]
        start = idx + len(repl)
    return out


def strip_lsr_calls(t):
    t = _strip_lsr_for(t, "LocalizedStringResource")
    t = _strip_lsr_for(t, "String")
    return t


# =====================================================================
# F3. 整类型标 @available (HelperTranscriptSheetStyle)
# =====================================================================
def mark_type_available(t, type_name, avail="iOS 16.0, *"):
    if re.search(r"@available[^\n]*\n[ \t]*struct\s+" + re.escape(type_name) + r"\b", t):
        return t
    return re.sub(
        r"(?m)^([ \t]*)(struct\s+" + re.escape(type_name) + r"\b)",
        r"\1@available(%s) // ios15-port\n\1\2" % avail, t)


def fix_helper_transcript_style(t):
    # 类型本身用 PresentationDetent (iOS16) -> 标 @available, 调用点已包 #available
    t = mark_type_available(t, "HelperTranscriptSheetStyle")
    old = (
        "    func helperTranscriptSheetStyle() -> some View {\n"
        "        modifier(HelperTranscriptSheetStyle())\n"
        "    }")
    new = (
        "    @ViewBuilder\n"
        "    func helperTranscriptSheetStyle() -> some View {\n"
        "        if #available(iOS 16, *) {\n"
        "            self.modifier(HelperTranscriptSheetStyle())\n"
        "        } else {\n"
        "            self\n"
        "        }\n"
        "    }")
    if old in t:
        return t.replace(old, new)
    return t


# =====================================================================
# F4. ContentView: 垫片函数直接注入本文件 (新文件不会被编译!)
# =====================================================================
NNS_SHIM = '''

// ios15-port: NotificationNavigationStore 是 iOS 16 的通知深链类型。这里把垫片
// 直接写进 ContentView.swift (在 .pbxproj 里, 必然参与编译), 调用点保持不变;
// iOS 15 上深链静默 no-op (整个点击通知跳转功能本就是 iOS 16+)。标记 @MainActor
// 以匹配 NotificationNavigationStore 的主线程隔离。
@MainActor
func nnsMarkHandled() {
    if #available(iOS 16.0, *) { NotificationNavigationStore.shared.markHandled() }
}

@MainActor
func nnsTakePending() -> String? {
    if #available(iOS 16.0, *) { return NotificationNavigationStore.shared.takePending() }
    return nil
}

@MainActor
var nnsHandledRecently: Bool {
    if #available(iOS 16.0, *) { return NotificationNavigationStore.shared.handledRecently }
    return false
}
'''


def fix_notification_nav_store(t):
    # 幂等: 垫片一旦注入就直接返回 (否则会把垫片内部的原始调用也改写掉 -> 递归)
    if "func nnsMarkHandled()" in t:
        return t
    t = t.replace("NotificationNavigationStore.shared.markHandled()", "nnsMarkHandled()")
    t = t.replace("NotificationNavigationStore.shared.takePending()", "nnsTakePending()")
    t = t.replace("NotificationNavigationStore.shared.handledRecently", "nnsHandledRecently")
    return t.rstrip() + "\n" + NNS_SHIM


# =====================================================================
# F5. 调用点守卫小工具
# =====================================================================
def guard_call(t, call, version="16.0"):
    """把 t 里所有 call 包进 `if #available(iOS version, *) { call }` (幂等)。"""
    if not call or call not in t:
        return t
    wrapped = "if #available(iOS %s, *) { %s }" % (version, call)
    out = t
    i = 0
    while True:
        idx = out.find(call, i)
        if idx < 0:
            break
        pre = out[max(0, idx - 30):idx]
        if "if #available(iOS %s, *) { " % version in pre:
            i = idx + len(call)
            continue
        out = out[:idx] + wrapped + out[idx + len(call):]
        i = idx + len(wrapped)
    return out


def wrap_call_in_available(t, fname, version="16.0"):
    """把 fname(...)[尾随闭包] 整调用包进 if #available (用于 View 构建器内的调用)。"""
    out = t
    start = 0
    pat = fname + "("
    while True:
        idx = out.find(pat, start)
        if idx < 0:
            break
        pre = out[max(0, idx - 30):idx]
        if "if #available(iOS %s, *) { " % version in pre:
            start = idx + len(pat)
            continue
        lp = idx + len(fname)
        rp = _match_delim(out, lp)
        if rp is None:
            start = idx + len(pat)
            continue
        end = rp
        j = end
        while True:
            k = j
            while k < len(out) and out[k] in " \t\r\n":
                k += 1
            m = re.match(r"[A-Za-z_]\w*\s*:\s*", out[k:])
            if m:
                k += m.end()
            if k < len(out) and out[k] == "{":
                e2 = _match_delim(out, k)
                if e2 is None:
                    break
                end = e2
                j = e2
            else:
                break
        out = out[:idx] + "if #available(iOS %s, *) { " % version \
            + out[idx:end] + " }" + out[end:]
        start = idx + 1
    return out


def guard_func_body(t, func_sig, version="17.0"):
    """在函数体开头插入 guard #available(iOS version, *) else { return } (幂等)。"""
    lines = t.split("\n")
    for i, ln in enumerate(lines):
        if func_sig in ln:
            k = i
            while k < len(lines) and "{" not in lines[k]:
                k += 1
            if k >= len(lines):
                return t
            if k + 1 < len(lines) and "guard #available" in lines[k + 1]:
                return t
            ind = len(lines[k]) - len(lines[k].lstrip())
            lines.insert(k + 1, " " * (ind + 4)
                         + "guard #available(iOS %s, *) else { return }" % version)
            return "\n".join(lines)
    return t


# =====================================================================
# F6. 各文件具体修复
# =====================================================================
def fix_minis_app(t):
    t = guard_call(t, "ShortcutNotificationDelegate.shared.register()", "16.0")
    t = guard_call(t, "Task { await ShortcutRunTracker.checkPendingOnForeground() }", "16.0")
    # 撤销 v2 给 fileProviderDomain 加的 @available (它会让引用点全报错)
    t = re.sub(
        r"(?m)^[ \t]*@available\(iOS 16\.0, \*\) // ios15-port\n(?=[ \t]*private static let fileProviderDomain\b)",
        "", t)
    # NSFileProviderDomain(identifier:displayName:) 是 iOS 16 才有的两参便利初始化器;
    # 换用 iOS 11 就有的三参版本 (pathRelativeToDocumentStorage 语义等价)。
    t = t.replace(
        'NSFileProviderDomain(\n'
        '        identifier: NSFileProviderDomainIdentifier("com.openminis.app.files"),\n'
        '        displayName: "Minis"\n'
        '    )',
        'NSFileProviderDomain(\n'
        '        identifier: NSFileProviderDomainIdentifier("com.openminis.app.files"),\n'
        '        displayName: "Minis",\n'
        '        pathRelativeToDocumentStorage: "com.openminis.app.files"\n'
        '    )')
    return t


def fix_app_delegate(t):
    # v2 的 _guard_avail_in_funcs 把多行 `func application(...) -> Bool` 误判成
    # 无返回值, 在其体首插入了 `guard #available(iOS 16, *) else { return }` ——
    # 空 return 在 -> Bool 函数里直接 "non-void function should return a value"。
    # 撤掉这个错误 guard, 改为在调用点精确守卫。
    t = t.replace(
        "    ) -> Bool {\n        guard #available(iOS 16.0, *) else { return }\n",
        "    ) -> Bool {\n")
    return guard_call(t, "ShortcutNotificationDelegate.shared.register()", "16.0")


def fix_helper_runner(t):
    # 撤销上一版误给"方法"标的 @available (会把错误传染给调用点)
    t = re.sub(r"(?m)^[ \t]*@available\(iOS 16, \*\)\n(?=[ \t]*static func helperWrapUpPrompt\b)", "", t)
    t = re.sub(r"(?m)^[ \t]*@available\(iOS 16, \*\)\n(?=[ \t]*private func startProgressReporter\b)", "", t)
    # 改为在方法内部守卫 iOS16 的 SendPromptIntent.extractResponseText
    t = re.sub(
        r"(?m)^([ \t]*)let lastMessage = SendPromptIntent\.extractResponseText\(from: child\)[ \t]*$",
        lambda m: '%svar lastMessage = ""\n%sif #available(iOS 16.0, *) { lastMessage = SendPromptIntent.extractResponseText(from: child) }'
                  % (m.group(1), m.group(1)),
        t)
    return t


def fix_scheduled_job_runner(t):
    return guard_call(t, "content.categoryIdentifier = ShortcutNotification.categoryId", "16.0")


def fix_voice_provider_resolver(t):
    return fix_sleep_for(guard_func_body(t, "private func registerLiveActivityToggleObserver()", "17.0"))


def fix_system_voice_catalog(t):
    t = t.replace(
        "Locale(identifier: tag).languageCode.lowercased()",
        '(Locale(identifier: tag).languageCode ?? "").lowercased()')
    t = t.replace(
        "Locale(identifier: tag).languageCode?.lowercased()",
        '(Locale(identifier: tag).languageCode ?? "").lowercased()')
    t = t.replace(
        "Locale(identifier: tag).language.languageCode?.identifier.lowercased()",
        '(Locale(identifier: tag).languageCode ?? "").lowercased()')
    return t


def fix_chat_input_bar(t):
    # v2 的 _replace_flow_layout 生成了非法的 Alignment(horizontal:) (缺 vertical:)
    return t.replace("Alignment(horizontal: alignment)",
                     "Alignment(horizontal: alignment, vertical: .center)")


def fix_login_sheet_guards(t):
    t = wrap_call_in_available(t, "KimiDeviceLoginSheet", "16.0")
    t = wrap_call_in_available(t, "CopilotDeviceLoginSheet", "16.0")
    return t


# =====================================================================
# 补充修复 (上一轮遗漏 / 本轮新暴露)
# =====================================================================
def fix_ish_verbose_trace(t):
    """iSH 的 C 符号 ish_set_verbose_trace 在 iOS 15 构建里没声明 -> 补 no-op 桩。"""
    if "func ish_set_verbose_trace" in t:
        return t
    stub = (
        "\n\n"
        "// iOS 15 兜底: 上游期望宿主提供 ish_set_verbose_trace (iSH 内核 trace 开关),\n"
        "// 在 iOS 15 构建里该 C 符号未声明。补一个私有 no-op 桩, 不影响功能。\n"
        "private func ish_set_verbose_trace(_ enabled: Bool) {}\n")
    return t.rstrip() + stub


def fix_force_sync_memory(t):
    """forceSyncMemory 上游标了 @available(iOS 17)，但调用点在
    `if #available(iOS 17.0, *), iCloudSyncEnabled` 的 ToolbarContentBuilder 里
    没有被认作 iOS 17 上下文 -> 给调用点再包一层 #available。"""
    t = t.replace("Task { await forceSyncMemory() }",
                  "Task { if #available(iOS 17.0, *) { await forceSyncMemory() } }")
    return t


def fix_aichat_view(t):
    """拆分超长字符串插值 + 抽离超大 onChange 闭包体 + 降级 Task.sleep(for:)。

    核心: iOS 17 SDK 下 `onChange(of:)` 有「废弃单参」与「新 initial-双参」两个
    重载, 编译器会对超大闭包体按两种重载各做一遍类型检查 -> "unable to
    type-check in reasonable time"。把闭包体抽成方法后闭包变为一行调用, 两种
    重载都瞬间可解。
    """
    old = (
        'AppLogger(category: "InputBarLayout").error("[InputBarHealth] STALLED — no geometry callback 900ms after foreground. committed=\\(inputBarHeight) latest=\\(latestInputBarFrameH) lastReport=\\(String(format: "%.1f", age))s ago voice=\\(voiceInputActive) editing=\\(voiceVM.isEditingTranscript) seeded=\\(didSeedInputBarHeight). The composer host is not laying out; expect a blank bottom area. Leaving and re-entering the session rebuilds it.")')
    new = (
        'let _stallMsg = "[InputBarHealth] STALLED — no geometry callback 900ms after foreground. committed=\\(inputBarHeight) latest=\\(latestInputBarFrameH) lastReport=\\(String(format: "%.1f", age))s ago voice=\\(voiceInputActive) editing=\\(voiceVM.isEditingTranscript) seeded=\\(didSeedInputBarHeight). The composer host is not laying out; expect a blank bottom area. Leaving and re-entering the session rebuilds it."\n'
        '                    AppLogger(category: "InputBarLayout").error(_stallMsg)')
    t = t.replace(old, new)
    t = _extract_onchange(t, "scenePhase", "handleScenePhaseChange", "phase", "ScenePhase")
    t = _extract_onchange(t, "vm.isProcessing", "handleProcessingChange", "processing", "Bool")
    t = _extract_onchange(t, "vm.fallbackTrigger", "handleFallbackTriggerPulse", None, None)
    t = _split_view_body_chain(t)
    return fix_sleep_for(t)


def _split_view_body_chain(t, every=8, body_head="    var body: some View {"):
    """把巨型 `var body`（单表达式修饰符链）用 `let` 中间变量切成多段。

    Swift 的类型检查对**单个表达式**有固定时间预算；AIChatView.body 是一条
    1180 行 / 69 个修饰符的单一表达式，必然超时。切成 9 段后每段独立预算，
    语义完全不变（链式求值顺序、类型都不变）。
    """
    if "_ios15Seg0" in t:
        return t
    lines = t.split("\n")
    bi = None
    for i, l in enumerate(lines):
        if l == body_head:
            bi = i
            break
    if bi is None:
        return t
    start = sum(len(x) + 1 for x in lines[:bi])
    lb = start + lines[bi].index("{")
    eb = _match_delim(t, lb)
    if eb is None:
        return t
    inner = t[lb + 1:eb - 1]
    ilines = inner.split("\n")
    splits = [k for k, l in enumerate(ilines) if l.startswith("        .")]
    if len(splits) < every + 1:
        return t
    base = "\n".join(ilines[:splits[0]])
    groups = []
    for gi in range(0, len(splits), every):
        a = splits[gi]
        b = splits[gi + every] if gi + every < len(splits) else len(ilines)
        groups.append("\n".join(ilines[a:b]))
    out = []
    prev = base
    for i, g in enumerate(groups):
        if i < len(groups) - 1:
            out.append("        let _ios15Seg%d = %s\n%s" % (i, prev, g))
            prev = "_ios15Seg%d" % i
        else:
            out.append("%s\n%s" % (prev, g))
    new_inner = "\n" + "\n\n".join(out) + "\n    "
    return t[:lb + 1] + new_inner + t[eb - 1:]


def _extract_onchange(t, of_expr, method_name, param_name=None, param_type=None):
    """把 `.onChange(of: of_expr) { ... }` 的体抽成方法。

    iOS 17 SDK 下 onChange 有新旧两个重载, 修饰符链上的超大闭包体会让编译器
    "unable to type-check this expression in reasonable time"。抽成方法后
    闭包只剩一行调用。
    param_name/param_type 为 None 时, 方法不带参数 (闭包形如 `{ _ in ... }`)。
    """
    pat = re.compile(r"\.onChange\(of:\s*" + re.escape(of_expr) + r"\)\s*\{")
    m = pat.search(t)
    if not m:
        return t
    lb = m.end() - 1
    eb = _match_delim(t, lb)
    if eb is None:
        return t
    body = t[lb + 1:eb - 1]
    if method_name in body:
        return t  # 已处理
    # 去掉闭包签名 (如 "phase in" / "processing in" / "_ in")
    body = re.sub(r"^[ \t]*(?:\w+|_)\s+in[ \t]*\n", "", body, count=1)
    if param_name and param_type:
        new_closure = (".onChange(of: %s) { %s in\n            %s(%s)\n        }"
                       % (of_expr, param_name, method_name, param_name))
        method = ("    func %s(_ %s: %s) {%s\n    }"
                  % (method_name, param_name, param_type, body))
    else:
        new_closure = (".onChange(of: %s) { _ in\n            %s()\n        }"
                       % (of_expr, method_name))
        method = ("    func %s() {%s\n    }" % (method_name, body))
    t = t[:m.start()] + new_closure + t[eb:]
    ext = ("\n\n// ios15-port: 抽离超大 onChange 闭包体, 规避修饰符链上表达式\n"
           "// 的类型检查超时。\n"
           "private extension AIChatView {\n" + method + "\n}\n")
    return t.rstrip() + ext


def fix_sleep_for(t):
    """Task.sleep(for: .milliseconds(N)) (iOS 16 + Duration 推断) -> nanoseconds (iOS 13+)。

    既消除 iOS 16 依赖, 又去掉 Duration/.milliseconds 的类型推断 —— 后者是
    "unable to type-check in reasonable time" 的常见成因。
    """
    def _repl(m):
        return "Task.sleep(nanoseconds: %d)" % (int(m.group(1)) * 1_000_000)
    return re.sub(r"Task\.sleep\(for:\s*\.milliseconds\((\d+)\)\)", _repl, t)


def fix_compat_shim(t):
    """兼容层 iOS15Compat.swift 里的两处修补。

    1) PhotosPickerItem.supportedContentTypes 原写作 [Any] -> 下游
       `$0.conforms(to: .movie)` 的 $0 被推成 Any, 报 "Any has no member
       'conforms' / cannot infer ... 'movie'"。真类型是 [UTType], 改成 [UTType]。
    2) 相应地需要 import UniformTypeIdentifiers。
    """
    t = t.replace("public var supportedContentTypes: [Any] { [] }",
                  "public var supportedContentTypes: [UTType] { [] }")
    if "supportedContentTypes: [UTType]" in t and "import UniformTypeIdentifiers" not in t:
        t = t.replace("import SwiftUI",
                      "import SwiftUI\nimport UniformTypeIdentifiers", 1)
    return t


# =====================================================================
# onGeometryChange 回填实现 (iOS 16 API → iOS 15)
# ---------------------------------------------------------------------
# iOS 16 的 .onGeometryChange(for:of:action:) 是本 App **唯一**的几何测量来源：
#   * inputBarHeight      → 消息列表底部内边距（用户现象："执行任务字不会上移"）
#   * floatingBarHeight   → 悬浮工具条高度
#   * topSafeAreaInset    → 导航栏顶部安全区
#   * inputBottomRowWidth → 朗读行宽度判定
# 流水线早期把它整调用删掉，于是 inputBarHeight 恒为 0：消息列表底部不留空，
# 最后一条消息被输入栏永久盖住、滚不进可视区（上游注释原话：
# "the last message was permanently stuck under the composer"）。
# 这里用 iOS 15 就有的 GeometryReader + PreferenceKey 复刻同一语义：
# 后台测量（不影响被测量视图的尺寸）、值变化时才回调（Equatable 去重）。
GEOM_BACKPORT = '''

// MARK: - onGeometryChange 回填 (iOS 16 API)
// ios15-port IOS15_GEOM_BACKPORT  (见 scripts/ios15_fallback.py)
// 复刻 iOS 16 `onGeometryChange(for:of:action:)`：把被测视图的几何值转成
// Preference，值变化时才回调 action。iOS 15 无此 API，而它承载着输入栏高度等
// 关键测量（缺失会导致最后一条消息被输入栏盖住、底部渲染成黑区）。

private struct IOS15GeometryValueKey<T: Equatable>: PreferenceKey {
    static var defaultValue: T? { nil }
    static func reduce(value: inout T?, nextValue: () -> T?) {
        if let next = nextValue() { value = next }
    }
}

extension View {
    func onGeometryChange15<T: Equatable>(
        for type: T.Type,
        of transform: @escaping (GeometryProxy) -> T,
        action: @escaping (T) -> Void
    ) -> some View {
        self
            .background(
                GeometryReader { proxy in
                    Color.clear
                        .preference(key: IOS15GeometryValueKey<T>.self,
                                    value: transform(proxy))
                        .allowsHitTesting(false)
                }
            )
            .onPreferenceChange(IOS15GeometryValueKey<T>.self) { value in
                if let value = value { action(value) }
            }
    }
}
'''


# =====================================================================
# UIHostingConfiguration 替身: 补上自排版测量
# ---------------------------------------------------------------------
# 消息列表是 UIKit 集合视图, 每个单元格用 UIHostingConfiguration(iOS16) 承载
# SwiftUI 内容; iOS 15 用的是 iOS15Compat.swift 里的替身。替身只把宿主视图
# 四边钉住, **没有实现 systemLayoutSizeFitting**, 于是集合视图自排版问
# "给定宽度下你多高" 时只能靠 intrinsic size 猜:
#   * 宽度退化成 SwiftUI 的"理想宽" —— 长文本远超屏宽 -> 文字左右被裁
#     (用户现象: "字不会自己对齐")
#   * 高度算错 -> 单元格之间出现大片黑块、内容无法贴底
#     (用户现象: "有黑块" / "输出的结果不会上移, 看不到内容")
# 这里显式按"提议宽度"量一次, 返回 (提议宽, SwiftUI 在该宽度下的理想高)。
HOSTING_FITTING = '''
    // ios15-port IOS15_HOSTING_FITTING
    // 集合视图自排版入口: 布局引擎问"给定宽度下你多高"。
    // 原替身没实现, 宽度会退化成 SwiftUI 理想宽(长文本远超屏宽 -> 左右被裁),
    // 高度也算错(单元格之间的黑块 / 内容贴不了底)。
    override func systemLayoutSizeFitting(_ targetSize: CGSize) -> CGSize {
        ios15FittingSize(targetSize)
    }

    override func systemLayoutSizeFitting(
        _ targetSize: CGSize,
        withHorizontalFittingPriority horizontalFittingPriority: UILayoutPriority,
        verticalFittingPriority: UILayoutPriority
    ) -> CGSize {
        ios15FittingSize(targetSize)
    }

    /// 递归保险。曾经在这里调 `host.view.systemLayoutSizeFitting(...)`：
    /// 宿主视图是四边钉在本视图上的，布局引擎解析它的尺寸时会反过来问
    /// "本视图多大"，于是又调回 systemLayoutSizeFitting —— 无限递归 →
    /// 栈溢出 EXC_BAD_ACCESS（实测崩溃栈: ios15FittingSize ↔
    /// _systemLayoutSizeFittingSize 反复嵌套）。所以这里只用
    /// `sizeThatFits` 这条不经过布局引擎的路径。
    private var isMeasuring: Bool = false
    private var lastLoggedWidth: CGFloat = -1
    private var ios15LastGoodFitH: CGFloat = 0

    private func ios15FittingSize(_ targetSize: CGSize) -> CGSize {
        var width = targetSize.width
        // ⚠️ 关键: 布局引擎问"压缩尺寸"时传的是 UIView.layoutFittingCompressedSize,
        // 宽高都是 Double.greatestFiniteMagnitude (≈1.8e308)。它是**有限数**,
        // 所以 `width.isInfinite` 拦不住 —— 之前直接把它当真实宽度交给 SwiftUI,
        // 内容按无界宽度排版: 长文本不换行、按自然宽度居中渲染 → 左右被裁;
        // 同时 TextKit 在这个荒谬宽度下抛 NSException → 自排版永远退回估算
        // 高度 → 单元格之间大片黑块（日志实测 1977 次全部 threw）。
        // 这里把"未指定/哨兵"宽度替换成集合视图的真实宽度。
        var probe: UIView? = superview
        var cvW: CGFloat = 0
        while let v = probe {
            if let collection = v as? UICollectionView {
                cvW = collection.bounds.width
                break
            }
            probe = v.superview
        }
        if !(width > 0) || width.isInfinite || width >= 1_000_000 {
            width = cvW > 0 ? cvW : (window?.bounds.width ?? UIScreen.main.bounds.width)
        }
        // [IOS15-FIX v17] 有限但超界的宽度同样要钳。SwiftUI 递归排版会把文本
        // "理想宽" (494/895/1382) 传进来 —— 按 494 宽排出的高度被提交成 cell 高度
        // (日志实证: 卡住的 252 = 按 494 宽排出; 渲染端 358 宽需要 ~300+ → 末行被
        // 拦腰裁断 / 短消息上下大片空白)。钳到 cvW-32 (=358) 与渲染端 superview
        // 修正宽度一致: 测量宽 == 渲染宽 → cell 高度吻合, 污染帧与拉锯闪烁同源消失。
        let measCapW15 = cvW > 33 ? cvW - 32 : cvW
        if measCapW15 > 1, width > measCapW15 {
            width = measCapW15
        }
        let probeCvW = (superview?.superview as? UICollectionView)?.bounds.width ?? -1
        print("[IOS15Size] in targetW=\\(targetSize.width) w=\\(width) cellW=\\(bounds.width) cvW=\\(probeCvW) hostNil=\\(host == nil)")
        guard let host = host, !isMeasuring else {
            return CGSize(width: width, height: max(0, bounds.height))
        }
        isMeasuring = true
        defer { isMeasuring = false }
        // [v25] 测量前先强制宿主视图布局: SwiftUI 内容未布局时 sizeThatFits 返回 0
        // (日志实证 56 次 out h=0.0 → cell 高度塌缩 → 整条消息不显示)。
        host.view.setNeedsLayout()
        host.view.layoutIfNeeded()
        var size = host.view.sizeThatFits(CGSize(width: width,
                                                 height: CGFloat.greatestFiniteMagnitude))
        if !(size.height > 0) {
            size = host.view.sizeThatFits(CGSize(width: width, height: 0))
        }
        var height = size.height
        // [v25] 仍失败且有历史好值 → 用历史好值兜底, 避免塌缩成 0。
        if !(height > 0), ios15LastGoodFitH > 1 {
            height = ios15LastGoodFitH
            size.width = width
        } else if !(height > 0) {
            height = bounds.height
        }
        print("[IOS15Size] out w=\\(width) h=\\(height) idealW=\\(size.width) idealH=\\(size.height)")
        if height > 1 { ios15LastGoodFitH = max(ios15LastGoodFitH, height) }
        return CGSize(width: width, height: max(0, height))
    }

'''


SHARE_TIMEOUT = '''    // ios15-port IOS15_SHARE_TIMEOUT
    // 之前 await 单个 NSItemProvider 时, 若它在 iOS 15 上不回调, 整个处理会
    // 永久挂住: 分享面板既没反应也不关闭, 主 App 也收不到 minis://share。
    // 这里加 8 秒超时: 超时也要继续走 redirectToHostApp + completeRequest,
    // 至少把主 App 唤起来。
'''


SHARE_STORE_OLD = '''    static var sharedFileDirectory: URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: appGroupID)?
            .appendingPathComponent("ShareExtension", isDirectory: true)
    }

    // MARK: - Write (called by Share Extension)

    static func savePendingShare(_ share: PendingShare) {
        guard let defaults = sharedDefaults else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(share) {
            defaults.set(data, forKey: pendingShareKey)
            defaults.synchronize()
        }
    }

    // MARK: - Read & Consume (called by main app)

    static func loadPendingShare() -> PendingShare? {
        guard let defaults = sharedDefaults,
              let data = defaults.data(forKey: pendingShareKey) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(PendingShare.self, from: data)
    }

    static func clearPendingShare() {
        sharedDefaults?.removeObject(forKey: pendingShareKey)
        sharedDefaults?.synchronize()
    }
'''

SHARE_STORE_NEW = '''    // ios15-port IOS15_SHARE_FILE_FALLBACK
    // 巨魔(iOS 15)环境下 UserDefaults(suiteName:) 可能拿不到 (sharedDefaults == nil),
    // 那时扩展辛苦处理完的数据会被 `guard ... else { return }` 静默丢弃 —— 主 App
    // 只能读到 "loadPendingShare returned nil — no data from extension"。
    // 所以改成双通道: UserDefaults 能用就写, 同时**始终**往共享容器写一份文件;
    // 读取时两边都试。共享容器路径在日志里已证实存在
    // (/private/var/mobile/Containers/Shared/AppGroup/.../)。
    // 注意: containerDirectory 已在文件其它位置定义(返回 App Group 容器 URL),
    // 此处直接复用, 不再重复声明, 否则触发 "invalid redeclaration"。

    static var sharedFileDirectory: URL? {
        FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: appGroupID)?
            .appendingPathComponent("ShareExtension", isDirectory: true)
    }

    private static var pendingShareFileURL: URL {
        containerDirectory.appendingPathComponent("pending-share.json")
    }

    // MARK: - Write (called by Share Extension)

    static func savePendingShare(_ share: PendingShare) {
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        guard let data = try? encoder.encode(share) else { return }
        if let defaults = sharedDefaults {
            defaults.set(data, forKey: pendingShareKey)
            defaults.synchronize()
        }
        try? data.write(to: pendingShareFileURL)
    }

    // MARK: - Read & Consume (called by main app)

    static func loadPendingShare() -> PendingShare? {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        if let defaults = sharedDefaults,
           let data = defaults.data(forKey: pendingShareKey),
           let share = try? decoder.decode(PendingShare.self, from: data) {
            return share
        }
        if let data = try? Data(contentsOf: pendingShareFileURL),
           let share = try? decoder.decode(PendingShare.self, from: data) {
            return share
        }
        return nil
    }

    static func clearPendingShare() {
        sharedDefaults?.removeObject(forKey: pendingShareKey)
        sharedDefaults?.synchronize()
        try? FileManager.default.removeItem(at: pendingShareFileURL)
    }
'''


def fix_share_store(t):
    """PendingShare 改双通道存储 (UserDefaults + 共享容器文件) —— 幂等。"""
    if "IOS15_SHARE_FILE_FALLBACK" in t:
        return t
    if SHARE_STORE_OLD not in t:
        return t
    return t.replace(SHARE_STORE_OLD, SHARE_STORE_NEW, 1)


def fix_share_extension_timeout(t):
    """给分享扩展的处理加超时兜底 (幂等)。"""
    if "IOS15_SHARE_TIMEOUT" in t:
        return t
    old = """            await vm.processExtensionItems(items)
            let saved = vm.save()"""
    new = SHARE_TIMEOUT + """            let saved = await withTaskGroup(of: Bool.self) { group -> Bool in
                group.addTask { @MainActor in
                    await vm.processExtensionItems(items)
                    return vm.save()
                }
                group.addTask {
                    try? await Task.sleep(nanoseconds: 8_000_000_000)
                    return false
                }
                let first = await group.next() ?? false
                group.cancelAll()
                return first
            }"""
    if old not in t:
        return t
    return t.replace(old, new, 1)


def fix_hosting_config_shim(t):
    """给 UIHostingConfiguration 替身补自排版测量 (幂等)。"""
    if "IOS15_HOSTING_FITTING" in t:
        return t
    anchor = "    private func apply(_ config: UIContentConfiguration) {"
    if anchor not in t:
        return t
    return t.replace(anchor, HOSTING_FITTING + anchor, 1)


def inject_geom_backport(t):
    """把 onGeometryChange 的 iOS 15 回填实现注入兼容层文件（幂等）。"""
    if "IOS15_GEOM_BACKPORT" in t:
        return t
    return t.rstrip() + "\n" + GEOM_BACKPORT


# =====================================================================
def fix_message_list_defer(t):
    """iOS15: 不让"大幅缩小"的修正被冻结。

    MessageListLayout 在 deferSelfSizing(用户浏览)期间，会把 cell 高度*缩小*
    的修正 park 到 deferredHeights、return false，使 contentSize 冻结在旧(高估)
    高度。iOS 15 上大量 cell 从估算值(est=1346)缩到真实值(pref=750)，这些 500+
    pt 的虚高空间变成黑色空洞；滚动停止后的 thaw 只恢复数值 offset，导致往上滚
    看到黑块/内容不上移。

    修法：仅当缩小量 > 50pt(即"过估被修正"这一类)时**立即生效**；<50pt 的流式
    token 级微调仍延迟，避免滚动抖动。已测量 cell 走 heightCache，优先于估算。
    """
    OLD = '''                if preferred <= original + 0.5 {
                    // Shrinking or stable — defer the update.
                    if abs(preferred - original) > 0.5 {
                        deferredHeights[index] = preferred
                    }
                    // [T-video-squish-evidence] Only worth a line when a REAL
                    // correction is being parked (large deltas are the media
                    // placeholder→loaded case). Token-by-token streaming
                    // produces sub-30pt shrinks constantly; those stay quiet.
                    if abs(preferred - original) > 30 {
                        AppLogger(category: "CellSizing").info("[CellSizing][DEFER-PARKED] idx=\\(index) pref=\\(String(format: "%.0f", preferred)) orig=\\(String(format: "%.0f", original)) — deferSelfSizing, not growing, correction parked")
                    }
                    return false
                }'''
    NEW = '''                if preferred <= original + 0.5 {
                    let shrink = original - preferred
                    // [IOS15-FIX] Large shrink = over-estimated estimate corrected
                    // to the real measured height. Parking it freezes an inflated
                    // contentSize, leaving phantom voids (black blocks) when the
                    // user scrolls up into the un-corrected region. Apply large
                    // shrinks immediately; defer only tiny (<50pt) token-level
                    // deltas to avoid streaming scroll jitter.
                    if shrink > 50 {
                        // Fall through — let the invalidate decision below apply
                        // the corrected (smaller) height to contentSize now.
                    } else {
                        // Shrinking or stable — defer the small update.
                        if abs(preferred - original) > 0.5 {
                            deferredHeights[index] = preferred
                        }
                        // [T-video-squish-evidence] Only worth a line when a REAL
                        // correction is being parked (large deltas are the media
                        // placeholder→loaded case). Token-by-token streaming
                        // produces sub-30pt shrinks constantly; those stay quiet.
                        if abs(preferred - original) > 30 {
                            AppLogger(category: "CellSizing").info("[CellSizing][DEFER-PARKED] idx=\\(index) pref=\\(String(format: "%.0f", preferred)) orig=\\(String(format: "%.0f", original)) — deferSelfSizing, not growing, correction parked")
                        }
                        return false
                    }
                }'''
    if OLD not in t:
        return t
    return t.replace(OLD, NEW)


def fix_defer_large_shrink(t):
    """iOS15: 大幅"收缩"修正(-100pt 以上)不被 deferSelfSizing 冻结。

    日志证据 (minis-2026-10-01-6.log 17:52): 回复里的工具控制台输出先按全文
    (699 字 ≈ 833pt) 测量提交, 随后折叠成卡片 (~245pt); 这个 -570pt 级别的
    收缩修正被 deferSelfSizing 欠账, 直到滚动结束/forceScrollToBottom 才结算,
    期间用户看到"回复位置一大片空白" (contentSize 3027→2440 才恢复)。

    修法: delta < -100pt 的收缩立即生效 —— 移除虚高空白不会像"增高"那样把
    相邻 cell 顶开, 滚动中立即应用是安全的。小的 (<100pt) 流式微调仍走原
    defer 逻辑防抖。
    """
    if "IOS15-FIX-BLANK" in t:
        return t
    OLD = '''            let isLargeGrowth = delta > 30
            if cellHasGrowableMediaAttachment && isLargeGrowth {'''
    NEW = '''            let isLargeGrowth = delta > 30
            // [IOS15-FIX-BLANK] A large NEGATIVE correction (tool console
            // output collapsing from full text into its card, long blocks
            // re-wrapping) that stays deferred during deferSelfSizing leaves a
            // multi-second blank void exactly where the reply renders. Removing
            // phantom space cannot overlap neighbouring cells the way a growth
            // can, so large shrinks are safe to apply immediately.
            if delta < -100 {
                cellSizeLogger.info("[CellSize] ALLOW through defer — large shrink " + String(format: "%.1f", delta) + " applies immediately (IOS15-FIX-BLANK)")
                // Fall through to the normal invalidate path below.
            } else if cellHasGrowableMediaAttachment && isLargeGrowth {'''
    if OLD not in t:
        return t
    return t.replace(OLD, NEW)


def fix_hosting_content_maxwidth(t):
    """v22: 给 UIHostingConfiguration 替身喂给 SwiftUI 的 rootView 设最大宽度。

    v21 的教训: 钳 UITextView.intrinsicContentSize 没打中 —— v21 日志里污染帧
    sv0 仍是 (-49805.0, …, 100000.0)、(-261.7, …, 913.3)、(-246.7, …, 883.3),
    idealW 仍 100032/2378/945/915/726。原因: 超宽"理想宽"来自 **SwiftUI 内容树**
    (Text/表格在"无限宽"提议下不换行, 理想宽 = 单行宽), SwiftUI 依此把内容视图布局成
    宽 ~100000 并在父视图里居中 → x = -49805, 内容飞出屏幕。SwiftUI 内部子视图的摆放
    由 SwiftUI 布局引擎决定, UIKit 侧约束(含 intrinsicContentSize)管不到。

    修法: 在替身构造 UIHostingController 时给 rootView 加 frame(maxWidth:),
    让内容的理想宽被压到可用宽 → Text 正常换行 → 不再有超宽/负 x 的污染帧,
    抢帧拉锯(闪字)与随之的高度错乱(空白/衔接不上)一并根除。
    """
    if "frame(maxWidth: _ios15ContentMaxW" in t:
        return t
    OLD = "        let controller = UIHostingController(rootView: AnyView(config.content))"
    NEW = '''        // [IOS15-FIX-CLIP v22] 给 SwiftUI 内容设最大宽度上限。
        // SwiftUI 的 Text / 表格等在"无限宽"提议下不换行, 理想宽可达 100032 / 2378,
        // 于是 SwiftUI 把内容视图布局成宽 ~100000 并在父视图里居中 → x = -49805
        // (sv0 日志实证) → 内容飞出屏幕; 渲染端抢回来、SwiftUI 每 tick 又写出去
        // = 拉锯闪字, 布局高度随之错乱 = 上下空白 / 输出衔接不上。
        // 设 maxWidth 后内容理想宽被压到可用宽, 污染帧从根本上不再产生。
        // maxWidth 只是上限: 内容更窄时按内容宽排布, 右对齐的用户气泡不受影响。
        let _ios15ContentMaxW = max(UIScreen.main.bounds.width - 32, 200)
        let controller = UIHostingController(rootView: AnyView(config.content.frame(maxWidth: _ios15ContentMaxW, alignment: .leading)))'''
    if OLD in t:
        return t.replace(OLD, NEW)
    return t


def fix_hosting_view_width(t):
    """v24: 钉死 UIHostingController 的 *视图* 宽度 = 可用宽 + 裁切溢出。

    v22 的 frame(maxWidth:) 把 SwiftUI 内容的"理想宽"压到了 358 (日志实证 idealW
    全为 358), 但表格 / 代码块等节点用 .fixedSize() 或自带横向滚动, 不理 maxWidth 上限
    → 这些节点的真实布局宽仍是 730 / 100000。上游 UIHostingController 据此把自身 view
    撑成 730/100000, 而原约束是四边钉死 (leading/trailing/top/bottom 全 = superview),
    于是 hosting view 跟随已被污染的父宽 → 气泡宽 730, 在 390pt 屏幕里居中后:
       · 左右双侧裁字 (字不显示)
       · 358 宽文字在 730 气泡里左对齐 → 右侧大片空白
       · SwiftUI 每帧把超宽帧写回、渲染端抢回 → 拉锯闪字
    v23 的 CADisplayLink 只在绘制前抢 frame, 治标不治本 (SwiftUI 仍在写超宽帧)。

    根治: 不再四边钉死, 改成【硬钉宽度 = 可用宽(max(屏宽-32,200)) + 左对齐 + clipsToBounds】。
    这样 UIHostingController 的 view 帧永远是 358, SwiftUI 据此向 root 提议 358 → 所有
    子节点(含表格/代码块)都按 358 排布, 730/100000 帧从根上不再产生, 且内部任何溢出
    (超宽表格)被 clipsToBounds 裁在 358 内 → 气泡恒等于可用宽, 不裁字、不空白、不闪。
    """
    OLD = '''        controller.view.translatesAutoresizingMaskIntoConstraints = false
        addSubview(controller.view)
        NSLayoutConstraint.activate([
            controller.view.leadingAnchor.constraint(equalTo: leadingAnchor),
            controller.view.trailingAnchor.constraint(equalTo: trailingAnchor),
            controller.view.topAnchor.constraint(equalTo: topAnchor),
            controller.view.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])'''
    if "ios15AvailW" in t:
        return t
    if OLD not in t:
        return t
    NEW = '''        controller.view.translatesAutoresizingMaskIntoConstraints = false
        addSubview(controller.view)
        // [IOS15-FIX-CLIP v24] 硬钉 hosting 视图宽度 = 可用宽, 左对齐 + 裁切溢出。
        // 病根: 四边钉死让 hosting view 跟随已被污染的父宽(表格/代码块不理 maxWidth,
        // 理想宽 730/100000), 气泡超宽 → 双侧裁字 + 右侧空白 + SwiftUI 抢帧闪字。
        // 改成硬钉宽度=可用宽(max(屏宽-32,200)): view 帧恒为 358, SwiftUI 据此向 root
        // 提议 358 → 所有子节点按 358 排布, 超宽帧从根上不再产生; clipsToBounds 把
        // 任何内部溢出(超宽表格)裁在 358 内 → 气泡恒等于可用宽。
        let _ios15AvailW = max(UIScreen.main.bounds.width - 32, 200)
        controller.view.clipsToBounds = true
        NSLayoutConstraint.activate([
            controller.view.leadingAnchor.constraint(equalTo: leadingAnchor),
            controller.view.widthAnchor.constraint(equalToConstant: _ios15AvailW),
            controller.view.topAnchor.constraint(equalTo: topAnchor),
            controller.view.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])'''
    return t.replace(OLD, NEW)


def fix_widget_activitykit(t):
    """AgentWidgetExtension 在 iOS 15.5 上根本没有 ActivityKit / AppIntents 框架,
    但源码顶层的 `import ActivityKit` / `import AppIntents` (Agent/Intents/*.swift
    与 AgentLiveActivityWidget 会被编译进扩展) 会让编译器以**强链接**方式把 framework
    写进扩展的 load command; dyld 加载扩展时因找不到库而崩 —— "Library not loaded:
    .../AppIntents.framework/AppIntents" (10 份崩溃日志实证; 上一版只弱链接了
    ActivityKit, AppIntents 漏网)。所有实际使用都包在 @available(iOS 16+, *)
    里, iOS 15.5 上根本不会执行 —— 因此只需改成**弱链接**, dyld 即可容忍缺失。
    """
    OLD_ONE = ('OTHER_LDFLAGS = (\n\t\t\t\t\t"-weak_framework",\n'
               '\t\t\t\t\tActivityKit,\n\t\t\t\t);')
    NEW_BOTH = ('OTHER_LDFLAGS = (\n\t\t\t\t\t"-weak_framework",\n'
                '\t\t\t\t\tActivityKit,\n'
                '\t\t\t\t\t"-weak_framework",\n'
                '\t\t\t\t\tAppIntents,\n\t\t\t\t);')
    if NEW_BOTH in t:
        return t
    if OLD_ONE in t:  # 上一版只插了 ActivityKit: 就地补全 AppIntents
        return t.replace(OLD_ONE, NEW_BOTH)
    for uuid in ("E5H000070", "E5H000071"):  # AgentWidgetExtension Debug / Release
        marker = "%s /*" % uuid
        idx = t.find(marker)
        if idx < 0:
            print("  SKIP (缺 widget config %s)" % uuid)
            continue
        bs = t.find("buildSettings = {", idx)
        if bs < 0:
            continue
        nl = t.find("\n", bs)
        insert = '\n\t\t\t\t' + NEW_BOTH
        t = t[:nl + 1] + insert + "\n" + t[nl + 1:]
    return t


def fix_markdown_measure_width(t):
    """iOS15: SelectableMarkdownView 的自排版测量宽度必须稳定。

    invalidateCellSizeIfNeeded 原先用 `bounds.width` 当测量宽度。iOS 15 上
    SwiftUI 递归排版时会把视图的 bounds.width 临时设成离谱值 (895 / 1382 / 1e7),
    于是 sizeThatFits 在极宽宽度下排版, 返回的高度远小于真实高度 —— 单元格 Commit
    了这个错误高度, 消息正文被裁切/错位 ("不显示不对齐")。

    文本视图始终位于集合视图 cell 内, 真实宽度不可能超过 collectionView 的内容
    宽度。因此把"提议宽度"钳制到 collectionView 宽度 (解析方式与 ios15FittingSize
    一致): 正常最终宽度 (≈358) 原样使用, 离谱的临时宽度钳到 ~390。这样测量宽度
    稳定, lastComputedHeight 不再抖动, 正文正确换行对齐。
    attachment 布局 (updateAttachmentViews) 同理钳制 containerWidth。"""
    # ---- invalidateCellSizeIfNeeded 的测量宽度 ----
    OLD1 = '''        // [JitterFix] Measure at the actual render width (bounds.width) when
        // available. textContainer.size.width can be transiently set to the
        // outer-cell probe width (~402) by SwiftUI's preferredLayoutAttributes
        // pass — measuring at that wrong width would write a 23pt-too-small
        // height into lastComputedHeight, producing the streaming spike.
        let measureWidth: CGFloat = bounds.width > 1 ? bounds.width : textContainer.size.width'''
    NEW1 = '''        // [IOS15-FIX] Measure at the actual render width, but clamp the
        // proposed width to the collectionView's content width. On iOS 15 SwiftUI's
        // recursive layout passes transiently set bounds.width to bogus values
        // (895 / 1382 / 1e7); measuring at those makes sizeThatFits lay the text
        // out far too wide, returning a height that is far too short — the cell
        // commits that wrong height and the message body renders clipped / mis-
        // aligned ("不显示不对齐"). The text view always lives inside a
        // collection-view cell, so its real width can never exceed the
        // collectionView content width; clamp to that.
        let cvContentWidth = (findCollectionView()?.bounds.width ?? 0)
        let proposedMeasureW = bounds.width
        // [IOS15-FIX v17] 测量宽必须与渲染宽一致: 渲染端 (v14) 把正文视图钳到
        // cvW-32 (=358, 16pt 双边距) 排版, 测量若用更宽的 cvW(390) 或污染宽
        // (494/895) 算出的 cell 高度偏小 → 末行被拦腰裁断 ("上下一半一半");
        // 卡住的 252 正是按 494 污染宽排出的高度。统一钳到 cvW-32。
        let measCapW = cvContentWidth > 33 ? cvContentWidth - 32 : cvContentWidth
        let measureWidth: CGFloat
        if proposedMeasureW > 1, proposedMeasureW < 100_000,
           proposedMeasureW <= measCapW + 1 {
            measureWidth = proposedMeasureW
        } else if measCapW > 1 {
            measureWidth = measCapW
        } else {
            measureWidth = textContainer.size.width
        }'''
    if OLD1 in t:
        t = t.replace(OLD1, NEW1)
    # ---- updateAttachmentViews 的 containerWidth ----
    OLD2 = '''        let containerWidth = self.textContainer.size.width'''
    NEW2 = '''        // [IOS15-FIX] Clamp the text-container width to a sane value. During
        // SwiftUI's recursive layout passes on iOS 15 textContainer.size.width is
        // transiently bogus (895 / 1382 / 1e7); using it to size/position
        // attachment views mis-aligns every image/table in the message body. The
        // text view can never be wider than its collection-view cell, so clamp.
        let cvContentWidthUAV = (findCollectionView()?.bounds.width ?? 0)
        let rawContainerWidth = self.textContainer.size.width
        // [IOS15-FIX v17] 同样钳到 cvW-32 与渲染端一致 (原钳 cvW=390 仍比渲染宽 358 大 9%,
        // attachment 高度按 390 算 → 在 358 里放不下 → 衔接错位/重叠)。
        let capW15UAV = cvContentWidthUAV > 33 ? cvContentWidthUAV - 32 : cvContentWidthUAV
        let containerWidth = capW15UAV > 1 ? min(rawContainerWidth, capW15UAV) : rawContainerWidth'''
    if OLD2 in t:
        t = t.replace(OLD2, NEW2)
    # ---- 宽度兜底消毒 (防 FIRST-MEASURE 死循环) ----
    OLD3 = "        // [TableGenDedup] Compute the sum of every TableAttachment's generation"
    NEW3 = r'''        // [IOS15-FIX] 宽度兜底消毒: 若上面三分支仍落到离谱瞬态宽度
        // (1e7 / 2273 / 1382 等, 来自 SwiftUI 递归排版或 widthTracksTextView
        // 把 textContainer 设到 greatestFiniteMagnitude 再经 Guard 钳到 1e7),
        // 直接放弃本次测量, 避免写出荒谬 newHeight (850/712) 触发 FIRST-MEASURE
        // 死循环 -> 主线程卡死。集合视图 cell 真实宽度恒 < 2000, 这里以此封顶。
        if !(measureWidth.isFinite && measureWidth > 1 && measureWidth < 2000) {
            cellSizeLogger.info("[invalidateCell][SKIP-BADWIDTH] boundsW=\(String(format: "%.0f", bounds.width)) tcW=\(String(format: "%.0f", textContainer.size.width)) cvW=\(String(format: "%.0f", (findCollectionView()?.bounds.width ?? 0))) — unstable width, skip measure")
            return
        }

        // [TableGenDedup] Compute the sum of every TableAttachment's generation'''
    if OLD3 in t:
        t = t.replace(OLD3, NEW3)
    # ---- FIRST-MEASURE 纠偏只用于"文本比 cell 高"(防 109↔100 双向震荡) ----
    OLD4 = "                  abs(cell.bounds.height - newHeight) > 8 else { return }"
    NEW4 = '''                  // [IOS15-FIX] 仅当文本实测高度比已提交 cell 高度更高(有末行裁切
                  // 风险)时才纠偏。newH < cellH 表示 cell 比文本需要的高(多余空间
                  // 不可见, 无害); 原来的 abs() 在 newH<cellH 时也 invalidate, 但
                  // preferredLayoutAttributesFitting 的 reconcile 取 max() 永远
                  // 维持较高的 cellH → 每次纠偏都不被采纳 → 109.3↔100.3 永久震荡
                  // (日志实测), 持续喂 DeferDebt OWED/CONSUME 循环参与 setSize 风暴。
                  (newHeight - cell.bounds.height) > 8 else { return }'''
    if OLD4 in t:
        t = t.replace(OLD4, NEW4)
    return t


def fix_markdown_render_width(t):
    """iOS15: 渲染端宽度钳制 (第二轮).

    测量端 (invalidateCellSizeIfNeeded) 已在 fix_markdown_measure_width 钳好,
    但渲染端仍是错宽:
      1) SelfSizingCell.preferredLayoutAttributesFitting 收到的提议宽度在 iOS15
         递归排版中瞬态为 895/1382/1e7 → super/explicit 测量在错宽下运行,
         写入过矮高度 (日志实测 pref=1091 vs TextKit 真值 1481.3) → 单元格
         压扁, 内容垂直错位;
      2) SelectableMarkdownTextView 自身 frame 被瞬态设为超宽且未被纠正,
         widthTracksTextView 让容器跟着超宽 → 文本按 ~2x 真实宽度换行;
      3) 瞬态无界宽度 pass 还会留下残留的 contentOffset.x (isScrollEnabled=
         false 本不应有), 之后每行文字左移被裁 —— 左右两边都缺一块。
    """
    # ---- ① 文本视图渲染端: frame 超宽回钳 + 残留水平偏移清零 ----
    OLD1 = '''        if textContainer.size.height < CGFloat.greatestFiniteMagnitude {
            textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }

        let currentWidth = textContainer.size.width'''
    NEW1 = '''        if textContainer.size.height < CGFloat.greatestFiniteMagnitude {
            textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }

        // [IOS15-FIX] Render-path width clamp. On iOS 15 SwiftUI's recursive
        // layout passes transiently set this view's frame to bogus widths
        // (895 / 1382 / 1e7) and the text container (widthTracksTextView)
        // follows, so the text is typeset at that bogus width. The measurement
        // path is already clamped in invalidateCellSizeIfNeeded, but the render
        // geometry kept the wrong value: lines wrap at ~2x the real width and
        // every paragraph is clipped / mis-aligned. This view always lives
        // inside a collection-view cell, so its real width can never exceed
        // the collectionView width — restore it here.
        if let rCv = findCollectionView(), rCv.bounds.width > 1,
           bounds.width > rCv.bounds.width + 1 {
            var rf = frame
            rf.size.width = rCv.bounds.width
            frame = rf
        }
        // [IOS15-FIX] A transient unbounded-width pass can leave a stale
        // horizontal contentOffset on this non-scrolling text view; every line
        // then renders shifted and is clipped on BOTH edges.
        if !isScrollEnabled, contentOffset.x != 0 {
            struct _LeftClipDiag { static var lastLog: CFTimeInterval = 0 }
            let _now = CACurrentMediaTime()
            if _now - _LeftClipDiag.lastLog > 1.0 {
                _LeftClipDiag.lastLog = _now
                AppLogger(category: "CellSize").info("[LEFT-CLIP-DIAG] zeroing contentOffset.x=\(String(format: "%.1f", contentOffset.x)) frameOrigin=\(String(format: "%.1f,%.1f", frame.origin.x, frame.origin.y)) frameSize=\(String(format: "%.0fx%.0f", frame.size.width, frame.size.height)) boundsW=\(String(format: "%.0f", bounds.width)) tcW=\(String(format: "%.0f", textContainer.size.width)) storageLen=\(textStorage.length)")
            }
            contentOffset.x = 0
        }
        // [IOS15-DIAG] 左裁字诊断: frame.origin.x 为负 (文本起点被推出 cell 左边界)
        let _fminX = frame.origin.x
        if _fminX < -0.5 {
            struct _NegXDiag { static var lastLog: CFTimeInterval = 0 }
            let _now2 = CACurrentMediaTime()
            if _now2 - _NegXDiag.lastLog > 1.0 {
                _NegXDiag.lastLog = _now2
                AppLogger(category: "CellSize").info("[LEFT-CLIP-DIAG] NEGATIVE frame.origin.x=\(String(format: "%.1f", _fminX)) frameSize=\(String(format: "%.0fx%.0f", frame.size.width, frame.size.height)) superview=\(String(describing: type(of: superview))) boundsW=\(String(format: "%.0f", bounds.width))")
            }
        }

        let currentWidth = textContainer.size.width'''
    if OLD1 in t:
        t = t.replace(OLD1, NEW1)
    # ---- ② cell 自排版: 提议宽度入口钳制 ----
    OLD2 = '''    override func preferredLayoutAttributesFitting(
        _ layoutAttributes: UICollectionViewLayoutAttributes
    ) -> UICollectionViewLayoutAttributes {
        // Cache-hit short-circuit BEFORE super:'''
    NEW2 = '''    override func preferredLayoutAttributesFitting(
        _ layoutAttributes: UICollectionViewLayoutAttributes
    ) -> UICollectionViewLayoutAttributes {
        // [IOS15-FIX] Clamp a bogus proposed width before ANY measure path
        // runs. On iOS 15 the proposed width is transiently garbage
        // (895 / 1382 / 1e7) during recursive layout passes; measuring at it
        // writes a far-too-short height (observed pref=1091 vs TextKit's true
        // 1481.3) into the layout, squashing the cell and mis-aligning the
        // message body. The cell can never be wider than its collection view.
        var layoutAttributes = layoutAttributes
        if let iCv = superview as? UICollectionView, iCv.bounds.width > 1,
           layoutAttributes.size.width > iCv.bounds.width + 1
           || layoutAttributes.size.width < 1 {
            let clamped = layoutAttributes.copy() as! UICollectionViewLayoutAttributes
            clamped.size.width = iCv.bounds.width
            layoutAttributes = clamped
        }
        // Cache-hit short-circuit BEFORE super:'''
    if OLD2 in t:
        t = t.replace(OLD2, NEW2)
    return t


def fix_markdown_layout_reconcile(t):
    """iOS15: preferredLayoutAttributesFitting 以 TextKit 实测高度兜底。

    日志实测 cellH=256 但 TextKit 实测 273 -> 末行被 clipsToBounds 裁掉
    ("不显示/不对齐")。invalidateCellSizeIfNeeded 在稳定宽度下算出的
    lastComputedHeight 与 SwiftUI 排版路径不一致会触发 FIRST-MEASURE 死循环
    (主线程卡死)。遍历 contentView 子树里的 SelectableMarkdownTextView,
    累加其 TextKit 权威高度, 取与 SwiftUI 测量值的较大者作为最终高度,
    既修裁切又让两测量路径一致 -> 循环收敛。"""
    OLD = "        attrs.size.height = fittingSize.height"
    NEW = '''        // [IOS15-FIX] 以 TextKit 实测高度兜底, 修正 SwiftUI 排版路径
        // 少算一行导致的末行裁切 (日志实测 cellH=256 但 TextKit 实测 273 ->
        // 末行被 clipsToBounds 裁掉, "不显示/不对齐")。遍历 contentView 子树里
        // 所有 SelectableMarkdownTextView, 累加它们的 lastComputedHeight
        // (由 invalidateCellSizeIfNeeded 在稳定宽度下算出的权威 TextKit 高度),
        // 取与 SwiftUI 测量值的较大者。两路径一致后 FIRST-MEASURE 冲突消失,
        // 主线程卡死 (卡死/什么都点不了) 随之消除。
        var _ios15Reconciled = fittingSize.height
        var _ios15TkSum: CGFloat = 0
        var _ios15Found = false
        for _v in hostingSubtree {
            if let _mdv = _v as? SelectableMarkdownTextView {
                let _h = _mdv.lastComputedHeight
                if _h > 1 { _ios15TkSum += _h; _ios15Found = true }
            }
        }
        // [IOS15-FIX] 上限 2500: 日志实测 643.7 vs TextKit 1198 (含工具卡长消息)
        // 差 554pt 恰好被旧上限 +500 拒掉 → reconcile 永远不生效 → 缓存钉死 643.7
        // → FIRST-MEASURE 无限纠偏 → DeferDebt OWED/CONSUME 自旋 → setSize 风暴
        // → 主线程 15s 卡死。TextKit 是权威测量 (源码注释自认), 放宽到 2500。
        if _ios15Found, _ios15TkSum > _ios15Reconciled, _ios15TkSum < _ios15Reconciled + 2500 {
            _ios15Reconciled = _ios15TkSum
        }
        fittingSize.height = _ios15Reconciled
        attrs.size.height = fittingSize.height'''
    if OLD in t:
        t = t.replace(OLD, NEW)
    return t


# =====================================================================
# F7. NSTextContainerSetSizeGuard: 风暴熔断 + 有限高度上限 (iOS 15 卡死根因)
# ---------------------------------------------------------------------
# v3 实测: FIRST-MEASURE 高度纠偏死循环已斩断 (739→2), 但 setSize: 风暴仍在:
#   * guard 日志 `size=589.3x17.3` 5791 次, `size=456.0x177.3` 1893 次
#   * 完整卡死堆栈 #0 CoreFoundation + #1-#7 全 CoreText (fillLayoutHole)
#   * `MAIN HANG` 178 次, 最长 11918ms
# 风暴宽度 589.3/456.0 只出现在 guard 日志、不出现在任何 App 日志 ->
# 是 UIKit/TextKit 内部对"其它文本视图"(代码块 codeTextView、表格
# TableCellTextView) 反复 setSize 驱动 CoreText 重排。根因两点:
#   1) 这些视图 widthTracksTextView 默认 true, 递归排版探针把 frame 宽瞬态设成
#      离谱值 -> 容器宽去追 -> setSize 风暴;
#   2) guard 把 .greatestFiniteMagnitude 钳成 1e7, CoreText 在近乎无限的容器上
#      fillLayoutHole 病态循环 (长消息每个 token 追加都重排整段)。
# 修法(v4):
#   A) 同容器同 tick 转发 setSize: 超过 kStormForwardLimit(40) 次即锁定、保留已
#      提交几何、不再转发 -> 斩断 re-entrant 链, 单次卡顿从 12s 降到几十 ms;
#   B) 容器高度上限从 1e7 降到 1e5 (≈16× 最高真实气泡), fillLayoutHole 永远有
#      有限终点。
def fix_textcontainer_guard_stormbreaker(t):
    if "IOS15-FIX-STORM" in t:
        return t  # 幂等
    # ---- ① 常量: 风暴阈值 + 有限高度上限 ----
    OLD1 = '''static const NSInteger kRepeatThreshold = 2;'''
    NEW1 = '''static const NSInteger kRepeatThreshold = 2;

// [IOS15-FIX-STORM] 风暴熔断阈值: 同一容器在同一 runloop tick 内被转发 setSize:
// 超过这个次数, 停止转发、保留已提交几何, 斩断 CoreText fillLayoutHole 的
// re-entrant 链 (实测完整堆栈 CoreFoundation + #1-#7 全 CoreText, 最长 11918ms
// 主线程卡死)。40 是经验值: 正常一 tick 内单个容器合法 setSize 远不到此数
// (多 cell 批量排版时每容器也就几次), 但 re-entrant 风暴会一 tick 内打几千次。
static const NSInteger kStormForwardLimit = 40;

// [IOS15-FIX-STORM] 容器高度上限。源码用 .greatestFiniteMagnitude 关掉高度钳制;
// 旧 guard 钳到 1e7 (仍近乎无限)。iOS 15 上近乎无限的容器让 fillLayoutHole 对长
// 流式消息病态循环。1e5(≈100000pt ≈ 16× 最高真实气泡) 既保留"足够高不裁真实
// 内容", 又给 CoreText 一个有限终点 -> 单次 typeset 成本有界。
static const CGFloat kMaxContainerHeight = 1e5;'''
    if OLD1 in t:
        t = t.replace(OLD1, NEW1)
    # ---- ② GuardState 加 per-tick 转发计数 + 熔断标志 ----
    OLD2 = '''typedef struct {
    CGSize lastSize;
    uint64_t lastTick;
    NSInteger repeatCount;
    BOOL initialized;
} GuardState;'''
    NEW2 = '''typedef struct {
    CGSize lastSize;
    uint64_t lastTick;
    NSInteger repeatCount;
    NSInteger commitCount;   // [IOS15-FIX-STORM] 本 tick 内已转发次数
    BOOL stormed;            // [IOS15-FIX-STORM] 本 tick 熔断已触发
    BOOL initialized;
} GuardState;'''
    if OLD2 in t:
        t = t.replace(OLD2, NEW2)
    # ---- ③ 高度上限改 1e5 (原来是 1e7) ----
    OLD3 = '''    if (newSize.width > 1e7) newSize.width = 1e7;
    if (newSize.height > 1e7) newSize.height = 1e7;'''
    NEW3 = '''    if (newSize.width > 1e5) newSize.width = 1e5;
    // [IOS15-FIX-STORM] 容器高度上限改有限值: 旧版钳到 1e7 仍近乎无限, iOS 15 上
    // 让 fillLayoutHole 对长流式消息病态循环 (多秒主线程卡死)。钳到 kMaxContainerHeight
    // (1e5 ≈ 16× 最高真实气泡) 既保留"足够高不裁真实内容", 又给 CoreText 有限终点。
    if (newSize.height > kMaxContainerHeight) newSize.height = kMaxContainerHeight;
    // [REVERTED-v11] 曾在此处加过"正文容器宽度硬钳制"(v9/v9.1/v10 三版), 已全部移除:
    // 实测三版全部更差 —— 目标宽度只能靠猜(屏宽390), 而真实可用宽是 358, 按 390 排版
    // 显示在 358 框里必然错位(用户反馈"字更加对不齐"); 且 v9.1 把 App 故意用的
    // greatestFiniteMagnitude 无限宽测量也钳成 390, 破坏测量语义 -> 布局永不收敛 ->
    // 单容器 44131 次同步死循环 + 508 次 10s 卡死。结论: 不要在派生的容器尺寸上
    // 和 UIKit 对抗(widthTracksTextView=true 时宽度由 UIKit 从 frame 派生), 要修
    // 就修产生它的 frame 源头。此处回退到已验证最好的 v8 行为。'''
    if OLD3 in t:
        t = t.replace(OLD3, NEW3)
    # ---- ④ 拿到 s 后、dedup 之前: 熔断后直接跳过转发 ----
    OLD4 = '''    GuardState *s = &holder->state;

    if (s->initialized && s->lastTick == gRunloopTick &&
        CGSizeEqualToSize(s->lastSize, newSize)) {'''
    NEW4 = '''    GuardState *s = &holder->state;

    // [IOS15-FIX-STORM] 风暴熔断: 本 tick 已经触发过熔断后, 只丢弃"同尺寸重复"
    // (自旋源); 不同尺寸的调用仍有限放行 —— v9 实证: 无差别丢弃会把正确的宽度
    // 修正 (358x550.9) 连坐丢掉, 容器宽停在旧值 → 文字不换行 → 横向裁切。
    if (s->initialized && s->lastTick == gRunloopTick && s->stormed) {
        if (CGSizeEqualToSize(s->lastSize, newSize)) {
            gShortCircuitCount += 1;
            if ((gShortCircuitCount & 0xF) == 1) {
                NSLog(@"[TextContainerGuard] [WARN] storm-breaker SKIP "
                      @"size=%.1fx%.1f tick=%llu total=%llu container=%p",
                      newSize.width, newSize.height,
                      (unsigned long long)gRunloopTick,
                      (unsigned long long)gShortCircuitCount,
                      (__bridge void *)self);
            }
            return;
        }
        if (s->commitCount > kStormForwardLimit * 4) {
            // [v26] 不同尺寸但本 tick 已转发过多 (390<->358 交替拉锯): 也丢弃,
            // 防止交替对每次走 else 重置把熔断永久绕过。
            gShortCircuitCount += 1;
            return;
        }
        // 不同尺寸且未超硬上限: 放行, 正确修正不再被连坐。
    }

    if (s->initialized && s->lastTick == gRunloopTick &&
        CGSizeEqualToSize(s->lastSize, newSize)) {'''
    if OLD4 in t:
        t = t.replace(OLD4, NEW4)
    # ---- ⑤ else 分支重置时一并重置 per-tick 计数/熔断 ----
    OLD5 = '''    } else {
        // Different tick or different size — reset bookkeeping.
        s->lastSize = newSize;
        s->lastTick = gRunloopTick;
        s->repeatCount = 1;
        s->initialized = YES;
    }'''
    NEW5 = '''    } else {
        // Different tick or different size — reset bookkeeping.
        s->lastSize = newSize;
        s->repeatCount = 1;
        s->initialized = YES;
        // [v26] 仅新 tick 才清零转发计数/熔断标志; 同 tick 内不同尺寸的放行
        // 调用继续累计 commitCount, 保证 4x 硬上限对交替拉锯 (390<->358) 有效。
        BOOL _newTick = (s->lastTick != gRunloopTick);
        if (_newTick) { s->commitCount = 0; s->stormed = NO; }
        s->lastTick = gRunloopTick;
    }'''
    if OLD5 in t:
        t = t.replace(OLD5, NEW5)
    # ---- ⑥ 转发前递增计数, 超阈值即熔断 ----
    OLD6 = '''    ((void (*)(id, SEL, CGSize))gOriginalSetSize)(self, _cmd, newSize);
}'''
    NEW6 = '''    // [IOS15-FIX-STORM] 累加本 tick 转发次数; 超过阈值即置熔断标志,
    // 后续同 tick 调用走上面的 storm-breaker SKIP 直接 return。
    s->commitCount += 1;
    if (s->commitCount > kStormForwardLimit) {
        s->stormed = YES;
    }
    ((void (*)(id, SEL, CGSize))gOriginalSetSize)(self, _cmd, newSize);
}'''
    if OLD6 in t:
        t = t.replace(OLD6, NEW6)
    return t


# =====================================================================
# F8. codeTextView: 关闭 widthTracksTextView, 固定容器宽 (代码块风暴源)
# ---------------------------------------------------------------------
# SelectableMarkdownView 的代码块 codeTextView 用默认 widthTracksTextView=true。
# 它嵌在 cell 的 NSTextAttachment 视图树里, 递归排版探针 (preferredLayoutAttributes
# Fitting) 把 frame 宽瞬态设成离谱值 (589.3/456.0), widthTracksTextView 让容器宽去
# 追 -> 每次探针都触发 CoreText 重排 -> v3 日志实测 589.3x17.3 (5791 次) 风暴。
# 代码块本就横滚, 不需要靠 frame 宽决定换行; 改为 widthTracksTextView=false 并固定
# 容器宽 (足够大=不换行), frame 仍按自然内容宽显示, 探针不再驱动重排。
def fix_code_textview_widthtrack(t):
    OLD = '''        codeTextView.textContainer.lineFragmentPadding = 0
        codeTextView.textContainer.lineBreakMode = .byClipping

        let codeStyle = NSMutableParagraphStyle()'''
    NEW = '''        codeTextView.textContainer.lineFragmentPadding = 0
        codeTextView.textContainer.lineBreakMode = .byClipping
        // [IOS15-FIX-STORM] 代码块横滚, 不需要容器宽跟随 frame。默认
        // widthTracksTextView=true 时, 递归排版探针把 frame 宽瞬态设成离谱值
        // (589.3/456.0), 容器宽去追 -> 每次探针触发 CoreText 重排风暴 (实测 5791
        // 次 setSize:)。关掉跟随并固定容器宽为足够大的值(=不换行), frame 仍按
        // sizeThatFits 的自然内容宽显示, 探针不再驱动重排。
        codeTextView.textContainer.widthTracksTextView = false
        codeTextView.textContainer.size.width = 10000

        let codeStyle = NSMutableParagraphStyle()'''
    if OLD in t:
        t = t.replace(OLD, NEW)
    return t


# =====================================================================
# F8b. v12: 记录最后正常容器帧的存储属性 (IOS15-FIX-CLIP v3 配套)
# ---------------------------------------------------------------------
# v3 的 superview 污染还原需要"正常帧"参照 (如 358@16), 精确还原 16pt 边距
# 而不是钳成一个猜的宽度。属性挂在 SelectableMarkdownTextView 上, 每个
# 正常 layoutSubviews pass 回写, 换消息(回收复用)后第一次正常 pass 刷新。
def fix_clip_v3_property(t):
    """v12: 给 SelectableMarkdownTextView 注入 ios15LastSaneSVFrame 存储属性。"""
    OLD = "final class SelectableMarkdownTextView: UITextView, UIGestureRecognizerDelegate {"
    NEW = OLD + '''
    // [IOS15-FIX-CLIP v3] 每视图记住最后正常的容器帧 (如 358@16)。superview 被
    // SwiftUI 瞬态污染 (宽 494/779 被父视图居中成负 x → 行首裁字) 时精确还原,
    // 不猜宽度。见 layoutSubviews 里 IOS15-FIX-CLIP v3 块。
    // [IOS15-FIX-CLIP v21] intrinsicContentSize 钳宽 —— 污染帧的源头。
    // v4 把 textContainer 的宽度上限设为 1e5 (防 CoreText 按 1e7/greatestFiniteMagnitude
    // 近乎无限排版而卡死主线程), 但 UITextView.intrinsicContentSize 直接把容器宽当作
    // "理想宽"报给 SwiftUI —— 于是上报 1e5+32 = 100032 (日志 idealW 实证),
    // SwiftUI 据此把气泡布局成宽 100000、在父视图里居中后 x = -49805
    // (sv0=(-49805.0, 160.0, 100000.0, 461.67) 实证) → 内容整个飞到屏幕外。
    // 渲染端抢回来、SwiftUI 每个 tick 又写出去 → 拉锯 = 闪字; 布局高度随之错乱 =
    // 上下空白 / 输出衔接不上 / 部分字不显示。
    // 这里把对外报告的"理想宽"钳到真实可用宽, 1e5 不再泄露进布局, 污染帧从根本上
    // 不再产生 (抢帧/KVO 只留作兜底)。
    override var intrinsicContentSize: CGSize {
        let sz = super.intrinsicContentSize
        let cvW = findCollectionView()?.bounds.width ?? 0
        let cap = cvW > 33 ? cvW - 32 : sz.width
        let w = (cap > 1 && sz.width > cap) ? cap : sz.width
        return CGSize(width: w, height: sz.height)
    }

    // [IOS15-FIX-CLIP v23] 帧同步修正: v22 的 frame(maxWidth:) 把 77% 的理想宽压到了
    // 358, 但表格/代码块等节点不理这个上限, sv0 仍出现 (-49805,…,100000)、
    // (-676,…,1742)、(-184.7,…,759.3) —— SwiftUI 里还有节点在撑宽, 继续压是打地鼠。
    // 换思路: 不再指望它不产生污染帧, 而是保证【屏幕上渲染的每一帧都是修正后的】。
    // CADisplayLink 的回调发生在每帧绘制之前, 在这里修正几何 → 用户永远看不到
    // 污染帧 → 视觉上彻底不闪, 且不依赖 SwiftUI 配合。
    static var _ios15FixLink: CADisplayLink?
    static var _ios15FixViews = NSHashTable<SelectableMarkdownTextView>.weakObjects()

    static func ios15RegisterFrameFix(_ tv: SelectableMarkdownTextView) {
        _ios15FixViews.add(tv)
        if _ios15FixLink == nil {
            let link = CADisplayLink(target: SelectableMarkdownTextView.self,
                                     selector: #selector(ios15FrameFixTick))
            link.add(to: .main, forMode: .common)
            _ios15FixLink = link
        }
    }

    @objc static func ios15FrameFixTick() {
        var need = false
        var alive = false
        for tv in _ios15FixViews.allObjects {
            if tv.window == nil { continue }
            alive = true
            if tv.ios15ApplyFrameFix() { need = true }
        }
        // [IOS15-FIX-DISPLAYLINK v29] 旧停机逻辑: 只要一帧无污染就 invalidate 并
        // 清空全部注册视图。但 SwiftUI 改 superview.frame 走 CALayer 事务路径
        // (KVO 观察不到), subview frame 未变时 layoutSubviews 也不触发 — 停机后
        // 污染帧再无人拦截 → 白块/裁字直接上屏 (log12 实证: 表格消息 sv0 宽
        // 100000 每帧 16 次全部污染)。改为: 仅当注册表里所有视图都已离开窗口
        // (weak 表清空) 才停机; 只要还有活视图就常驻抢帧, 开销纳秒级。
        if !alive {
            _ios15FixLink?.invalidate()
            _ios15FixLink = nil
            _ios15FixViews.removeAllObjects()
        }
    }

    /// 渲染前修正: 只把 superview 的 x/宽 拉回可用范围 (导致内容飞出屏幕的部分),
    /// 轻量执行; 容器宽/偏移等完整修正仍由 layoutSubviews 负责。
    /// 返回 true = 本帧仍有污染 (需继续监控)。
    func ios15ApplyFrameFix() -> Bool {
        guard !isScrollEnabled else { return false }
        // [IOS15-FIX-DISPLAYLINK v29] findCollectionView() 在 SwiftUI hosting 层级
        // 未就绪/遍历失败时返回 nil, 旧逻辑直接放弃修正 → 白块从死角漏上屏。
        // 改用屏宽兜底 (气泡恒为 屏宽-32@16), 任何时候都不放弃抢帧。
        let _cvW0 = findCollectionView()?.bounds.width ?? 0
        let cvW = _cvW0 > 1 ? _cvW0 : UIScreen.main.bounds.width
        guard let sv = superview, cvW > 1 else { return false }
        let f = sv.frame
        let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
        if !polluted {
            if f.size.width > 200, f.origin.x > 0.5, f.size.width < cvW - 0.5 {
                ios15LastSaneSVFrame = f
            }
            return false
        }
        var fix = f
        if let last = ios15LastSaneSVFrame,
           last.size.width > 0, last.size.width <= cvW,
           last.origin.x > 0.5, last.size.width < cvW - 0.5 {
            fix.origin.x = last.origin.x
            fix.size.width = last.size.width
        } else {
            fix.origin.x = 16
            fix.size.width = cvW - 32
        }
        sv.frame = fix
        return true
    }

    var ios15LastSaneSVFrame: CGRect?
    // [IOS15-FIX-CLIP v14] 渲染端算出的实际需求高度 (usedRect + 上下 inset)。
    // 老会话 cell 高度欠账 (如 286 字符只给 252pt) → 半截字; SwiftUI 把 frame 高
    // 拉回欠账值时, 用它检出并重撑。
    var ios15LastNeededH: CGFloat = 0
    // [IOS15-FIX-CLIP v18] KVO 抢帧: SwiftUI 在自己的布局 tick 里把 superview 写成
    // 污染帧, 等 layoutSubviews 再修就来不及 —— 污染帧已经渲染出去一帧 = 闪字。
    // 这里 block-KVO superview.frame, 在它被写坏的同一调用栈内立刻改回 (CA 提交前),
    // 污染帧永远到不了屏幕 → 抢帧拉锯的闪烁根除。
    // NSKeyValueObservation 在观察者或目标释放时自动失效, 无需手动移除。
    var ios15KvoToken: NSKeyValueObservation?
    weak var ios15KvoTarget: UIView?
    var ios15KvoFixing = false
    func ios15InstallKVO() {
        if let tok = ios15KvoToken, let tgt = ios15KvoTarget, tgt === superview { return }
        ios15KvoToken?.invalidate()
        ios15KvoToken = nil
        ios15KvoTarget = nil
        guard let sv = superview else { return }
        ios15KvoTarget = sv
        ios15KvoToken = sv.observe(\\.frame, options: [.new]) { [weak self] obj, _ in
            guard let self = self, !self.ios15KvoFixing else { return }
            // [V41-LETFIX] let -> var: v41 要在补齐高度后把新值交棒给后续宽度修正
            // (`f = _hFix`), Swift 的 let 不可重新赋值, 保持 let 会编译失败。
            var f = obj.frame
            // [IOS15-FIX-DISPLAYLINK v29] findCollectionView 死角兜底
            // (同 ios15ApplyFrameFix): 遍历失败时用屏宽, 不放弃同栈抢帧。
            let _cvW0 = self.findCollectionView()?.bounds.width ?? 0
            let cvW = _cvW0 > 1 ? _cvW0 : UIScreen.main.bounds.width
            guard cvW > 1 else { return }
            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
            if !polluted {
                if f.size.width > 200, f.origin.x > 0.5, f.size.width < cvW - 0.5 {
                    self.ios15LastSaneSVFrame = f
                }
                return
            }
            var fix = f
            if let last = self.ios15LastSaneSVFrame,
               last.size.width > 0, last.size.width <= cvW,
               last.origin.x > 0.5, last.size.width < cvW - 0.5 {
                fix.origin.x = last.origin.x
                fix.size.width = last.size.width
            } else {
                fix.origin.x = 16
                fix.size.width = cvW - 32
            }
            self.ios15KvoFixing = true
            obj.frame = fix
            self.ios15KvoFixing = false
        }
    }'''
    if "ios15LastSaneSVFrame: CGRect?" in t:
        return t
    if OLD in t:
        return t.replace(OLD, NEW, 1)
    return t


# =====================================================================
# F9. LEFT-CLIP-DIAG 补充: superview 原点诊断 (查清 v3 仍未定位的左裁字机制)
# ---------------------------------------------------------------------
# v3 实测 contentOffset.x 清零计数与 frame.origin.x 负向检测均为 0, 说明左裁字
# 既不是残留水平偏移、也不是文本视图自身负原点 -> 是别的机制。这里在渲染路径
# 打印 superview 的 frame 与文本视图相对 superview 的原点, 区分"父视图布局把文本
# 推出左边界"还是"自身坐标偏移"。用 String(describing:) 拼接, 避免 \( 插值转义。
def fix_left_clip_diag_superview(t):
    """v5: 老会话双边裁字修复 —— 渲染端容器/自身宽度钳回 + 强制 TextKit 重排。

    日志证据 (minis-2026-10-01-6.log): 新会话对齐了, 老会话仍每行首尾同时被裁
    (both-edge clip)。机制: 老会话从磁盘一次性载入, 初始布局若遇到 SwiftUI
    递归排版传入的瞬时离谱宽度 (895/1382), 文本容器便按超宽排版; 之后没有
    流式重测路径替它纠正, 容器宽度就此卡死 —— 每一行都按超宽排版、被可视
    边界两边裁掉。新会话因流式不断重测而自愈, 所以只有老会话犯病。

    修法: 渲染路径上 (仅限不可滚动的正文视图) 发现 textContainer/自身宽度
    超过真实可用宽度 (min(superview, collectionView)) 时钳回, 清掉残留的
    bounds.origin.x, 并强制 TextKit 立即重排。诊断 v2 同步打印自身几何。
    """
    # 幂等守卫: 用布局块内独有的赋值语句判定 (属性注释里也有 v3 字样, 不能用)。
    if "ios15LastSaneSVFrame = _svf" in t:
        return t
    OLD = '''        let currentWidth = textContainer.size.width'''
    NEW = '''        // [IOS15-FIX-CLIP] 老会话双边裁字修复: 容器/自身宽度钳回 + 强制重排。
        // 仅限不可滚动视图 (可滚动的代码块视图自管宽度/偏移, 不动)。
            if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {
            // [IOS15-FIX-CLIP v14] 状态判定 + 修复。
            // 污染 (太宽 > cvW+1 或 x < -0.5): 气泡被 SwiftUI 居中推出屏幕 → 行首裁字,
            //   必须抢 frame 还原 (inset 救不了已经移出屏幕的那部分)。
            // 贴边 (x<=0.5 且 w>=cvW-1): SwiftUI 的布局模型本身就是"全宽@0"。v12/v13 抢
            //   frame 还原 358@16 → SwiftUI 每个布局 pass 又把 superview 拉回 390@0, 两态
            //   交替渲染 = 闪屏闪字 (v13 日志 49 次拉锯实证)。v14 贴边不再抢 frame, 改用
            //   "内边距适应": 设 inset.left/right=16 让文字渲染在 16..374, 不贴边不裁字,
            //   SwiftUI 侧完全不动 → 布局稳定, 拉锯与闪烁的根没了。
            ios15InstallKVO()
            let _cvW = rCv2.bounds.width
            var _didFix = false
            var _widthChanged = false
            let _svf0 = superview?.frame ?? .zero
            let _polluted = _svf0.size.width > _cvW + 1 || _svf0.origin.x < -0.5
            let _edgeTouch = !_polluted && _svf0.origin.x <= 0.5 && _svf0.size.width >= _cvW - 1
            if _polluted, let _sv = superview {
                var _fix = _svf0
                if let _last = ios15LastSaneSVFrame,
                   _last.size.width > 0, _last.size.width <= _cvW,
                   _last.origin.x > 0.5, _last.size.width < _cvW - 0.5 {
                    _fix.origin.x = _last.origin.x
                    _fix.size.width = _last.size.width
                } else {
                    _fix.origin.x = 16
                    _fix.size.width = _cvW - 32
                }
                    _sv.frame = _fix
                    _didFix = true
                    _widthChanged = true
                    // [v23] 发现污染帧 → 注册帧同步修正, 保证后续每帧绘制前都被拉回,
                    // 用户看不到污染帧 (闪字的视觉根源)。
                    SelectableMarkdownTextView.ios15RegisterFrameFix(self)
                } else if _svf0.size.width > 200 && _svf0.origin.x > 0.5 && _svf0.size.width < _cvW - 0.5 {
                // 只记录"带边距的正常帧", 全宽贴边帧(390@0)绝不入库, 防记忆被污染
                ios15LastSaneSVFrame = _svf0
            }
            // [v14] 内边距适应: 贴边 → inset 16/16; 正常帧 → inset 0/0。仅状态翻转才写,
            // 避免每 pass 赋值。
            if _edgeTouch {
                if textContainerInset.left < 15.5 {
                    textContainerInset = UIEdgeInsets(top: textContainerInset.top, left: 16, bottom: textContainerInset.bottom, right: 16)
                    _didFix = true
                    _widthChanged = true
                }
            } else if !_polluted, textContainerInset.left > 0.5 {
                textContainerInset = UIEdgeInsets(top: textContainerInset.top, left: 0, bottom: textContainerInset.bottom, right: 0)
                _didFix = true
                _widthChanged = true
            }
            // 容器/宽度钳制。贴边模式: 容器被 inset 自动收窄到 cvW-32, frame 保持 SwiftUI
            // 给的全宽 (不动它); 污染/正常模式: 按修正后的 superview 宽钳。
            let _svW = superview?.bounds.width ?? 0
            var _realW = _svW > 1 ? min(_svW, _cvW) : _cvW
            if _edgeTouch {
                _realW = max(_realW - 32, 100)
            }
            let _tcOldW = textContainer.size.width
            if textContainer.size.width > _realW + 1 {
                textContainer.size.width = _realW
                _didFix = true
                _widthChanged = true
            }
            if !_edgeTouch, bounds.width > _realW + 1 || frame.size.width > _realW + 1 {
                var _rf = frame
                _rf.size.width = _realW
                frame = _rf
                _didFix = true
                _widthChanged = true
            }
            if bounds.origin.x != 0 {
                var _rb = bounds
                _rb.origin.x = 0
                bounds = _rb
                _didFix = true
            }
            // [IOS15-FIX-CLIP v14] 高度欠账修复 (老会话半截字)。老会话一次性载入时按污染
            // 宽度测出的 cell 高度偏小 (286 字符只拿到 252pt), 渲染端钳宽后文字 re-wrap 需要
            // 更高 → 最后一行被拦腰裁断 (截图实证)。这里排版后按 usedRect 撑高自身与气泡;
            // ios15LastNeededH 记住需求高度, SwiftUI 重排把 frame 高拉回去时也能检出并重撑。
            // 刻意**不调用 setNeedsLayout** —— 那是 v12/v13 闪字的元凶。
            // [v26] 高度死锁修复 (末行半截字 / 整条不显示)。
            // v25 用"临时把容器高放开到 100000 + invalidate/ensureLayout"拿真实需求高,
            // 但排版期间 TextKit 对巨高容器的连环 setSize: 直接耗光守卫每 tick 40 次转发
            // 预算 (v9 日志实证: size=358x100000 被熔断 116 次, 正确的 358x550.9 被连坐
            // 丢弃 48 次) → 宽度修正进不来 → 容器宽停在旧值 → 文字不换行 → 横向裁切。
            // v26 改用 UITextView.sizeThatFits 标准 API 测量: 不改变 textContainer 状态、
            // 不触发重排风暴, 同样能拿到不受当前容器高限制的真实需求高度。
            let _realW2 = _realW
            var _ios15WRegrabbed = false
            if abs(textContainer.size.width - _realW2) > 0.5 {
                textContainer.size.width = _realW2
                _ios15WRegrabbed = true
            }
            // [IOS15-FIX-RELC v28] 抢回宽度后必须强制重排。log11 实证: SwiftUI poll 每帧把
            // 容器宽打回 390 (cvW=390), TextKit 行碎片按 ~374pt 排版; v18 抢回 358 时仅改
            // textContainer.size 而不 invalidate, 旧行碎片不会被重排 → 358 视口裁掉行尾
            // 16pt ("字显示不完全"/行尾半截字)。签名 invalidateLayout(forCharacterRange:
            // actualCharacterRange:) 为 v25-fix2 编译验证过的合法形式; 不碰容器高 (v26 已定),
            // 不会引发 100000 风暴。先 invalidate 再 sizeThatFits, 保证测高按新宽 re-wrap。
            if _ios15WRegrabbed, textStorage.length > 0 {
                layoutManager.invalidateLayout(forCharacterRange: NSMakeRange(0, textStorage.length), actualCharacterRange: nil)
            }
            let _needH = sizeThatFits(CGSize(width: _realW2, height: .greatestFiniteMagnitude)).height
            if _ios15WRegrabbed {
                layoutManager.ensureLayout(for: textContainer)
            }
            ios15LastNeededH = _needH
            if textStorage.length > 0, _needH > 1 {
                if frame.size.height < _needH - 0.5 {
                    var _hf = frame
                    _hf.size.height = _needH
                    frame = _hf
                    _didFix = true
                }
                if let _sv = superview, _sv.frame.size.height > 1, _sv.frame.size.height < _needH - 0.5 {
                    var _sf = _sv.frame
                    _sf.size.height = _needH
                    _sv.frame = _sf
                    _didFix = true
                }
                invalidateIntrinsicContentSize()
            }
            if _didFix {
                struct _ClipFixLog { static var lastLog: CFTimeInterval = 0 }
                let _nowF = CACurrentMediaTime()
                if _nowF - _ClipFixLog.lastLog > 1.0 {
                    _ClipFixLog.lastLog = _nowF
                    AppLogger(category: "CellSize").info("[LEFT-CLIP-FIX v18] tcW " + String(describing: _tcOldW) + " -> " + String(describing: textContainer.size.width) + " sv0=" + String(describing: _svf0) + " (svW=" + String(describing: _svW) + " cvW=" + String(describing: _cvW) + " edge=" + String(describing: _edgeTouch) + " poll=" + String(describing: _polluted) + ") frameW=" + String(describing: frame.size.width) + " frameH=" + String(describing: frame.size.height) + " needH=" + String(describing: ios15LastNeededH) + " insetL=" + String(describing: textContainerInset.left) + " storageLen=" + String(describing: textStorage.length))
                }
            }
        }
        // [LEFT-CLIP-DIAG v2] 旧 relX=frameX-svFrameX 跨坐标系相减没有意义
        // (文本框在 x=16 容器内从 0 起永远触发)。改为低频打印自身几何,
        // 供验证双边裁字是否根除。
        struct _ClipDiag2 { static var lastLog: CFTimeInterval = 0 }
        let _nowD = CACurrentMediaTime()
        if _nowD - _ClipDiag2.lastLog > 5.0 {
            _ClipDiag2.lastLog = _nowD
            AppLogger(category: "CellSize").info("[LEFT-CLIP-DIAG2] frame=" + String(describing: frame) + " boundsO=" + String(describing: bounds.origin) + " tcW=" + String(describing: textContainer.size.width) + " svFrame=" + String(describing: (superview?.frame ?? .zero)) + " scroll=" + String(describing: isScrollEnabled) + " storageLen=" + String(describing: textStorage.length))
        }

        let currentWidth = textContainer.size.width'''
    if OLD in t:
        t = t.replace(OLD, NEW)
    return t


def fix_table_probe_width(t):
    """v28: 表格 probe 返回宽 32768 污染 superview → 白色巨块盖住内容。

    log11 实证 (minis-2026-10-02 11.log): 含表格消息 (storageLen=856) 的
    [LEFT-CLIP-FIX v18] 反复出现 sv0=(16, y, 32768.0, 825.7) — superview 宽被
    撑到 32768; [TextContainerGuard] short-circuited setSize: 32768.0x817.7。
    根因: TableAttachment.attachmentBounds 对 SwiftUI intrinsic-size probe
    (lineFrag.width=10_000_000) 返回 clampedWidth=32_768 (上游设计: 让 SwiftUI
    做 max-width 发现)。iOS16 上游没事, iOS15 上这个 32768 glyph rect 直接把
    superview frame 撑爆, 白底表格 view 尺寸/位置错乱 → 用户看到白色矩形盖住
    消息内容 + 表格自身显示不全。

    修复: probe 分支的返回宽钳到真实宽度 (containerRealWidth → lastRealWidth →
    narrowestRealWidth 兜底), 高度逻辑保持不变 (高度本来就用真实宽计算)。
    iOS15 上 SwiftUI 不需要 32768 max-width 发现 — 气泡宽已被 v24 硬钉 358。
    """
    OLD = "        let returnWidth = isOversizedProbe ? clampedWidth : usableWidth"
    NEW = """        // [IOS15-FIX-TABLE-PROBE v28] probe 返回宽 32768 在 iOS15 上把 superview
        // frame 撑爆 (log11: sv0 宽 32768 → 白色巨块盖住内容 + 表格显示不全)。
        // 钳到真实容器宽: iOS15 气泡宽已硬钉 358, 无需 SwiftUI max-width 发现。
        let returnWidth = isOversizedProbe
            ? min(clampedWidth, (containerRealWidth ?? lastRealWidth ?? Self.narrowestRealWidth))
            : usableWidth"""
    if OLD in t:
        t = t.replace(OLD, NEW)
    return t


def fix_probe_width_global_clamp_v37(t):
    """v37: 全局钳住 probe 宽度 — 治"终端框卡一下再显示" + 末行"上下一半一半"。

    日志实证 (minis-2026-10-03 5.log, 9016 行):
      1) [LEFT-CLIP-FIX v18] sv0 宽度谱系 (按出现顺序):
         100000.0 → 1616.0 → 1077.67 → 984.0 → 817.67, 而 svW 恒被抢回 358.0。
         817.67 = 屏宽 390 的 2.1 倍, 横跨到屏幕外。
      2) poll=true 命中 106 次, 全部是 `tcW 390.0 -> 358.0` 一个方向 —
         SwiftUI 每帧写下超宽, v18 每帧抢回 358。两个引擎以 3.6 倍速互相拉扯
         = 用户看到的"终端框卡一下再显示"(每次重排都是一次可见闪烁)。
      3) 高度连带崩: sv0 高 279.67 而 needH/frameH 446.67 → 欠账 167pt;
         另一条 63.67 vs 135.0 → 欠账 71pt。118 个样本 116 个异常。
         末行被 clipsToBounds 拦腰切断 = "上下一半一半"。
      4) FIRST-MEASURE CORRECTION 36 条, 欠账 8~566pt(中位 43.6), 无一条 <8pt,
         即纠偏机制一直在满负荷救火, 仍追不上每帧的污染重排。

    根因: SwiftUI/UIHostingConfiguration 的 intrinsic-size 探测会合成
    lineFrag.width = 10_000_000, 而**全文件 7 个 attachmentBounds override
    里有 9 处 return 路径把 lineFrag.width 原样当返回宽度**:
      2206 表格 usableWidth<=0 兜底 / 3386 RenderedBlock / 3504 图片 block
      3552 公式 block 约束宽 / 3554 公式 block 返回宽 / 3574 公式占位
      4452 视频缩略图 / 4464 视频 / 4474 图片占位
    v28 只钳了 2199 (表格 isOversizedProbe 分支) 一处, 其余 8 处全漏。
    probe 宽 100000 经 attachmentBounds → makeView → superview.frame 一路放大,
    把 UITextView 的 superview 撑到 817/1077/100000, TextKit 按错宽排版,
    高度算错 → 末行裁切; 每帧重排 → 闪烁卡顿。

    修法 (不逐处改 9 个 return, 而是加一个共用钳位器):
      1) 在 SelectableMarkdownTextView 上加静态方法
         ios15ClampProbeWidth(_:textContainer:), 正常布局时原样返回 proposed
         (行为零变化), 只有 >= 100_000 的 probe 值才钳到 textContainer 真实宽。
      2) 把 9 处 `width: lineFrag.width` 统一换成走该钳位器。

    为什么这样最稳: probe 宽只是"给 SwiftUI 做 max-width 发现"用的哨兵值,
    iOS16 上游依赖它拿 1e5+32=100032 去发现 max-width; 但本项目 v22 已经
    给 hosting 内容加了 .frame(maxWidth:), 发现机制早已被接管, iOS15 上这个
    哨兵值有且仅有"撑爆 superview"这一个副作用。钳掉它 = 副作用归零,
    且正常布局路径一个字节都不变 → 回归风险最低。
    """
    if "V37-PROBECLAMP" in t:
        return t

    # ---- 1) 注入钳位器 (文件级全局函数, 9 处泄漏路径跨 4 个类都能调) ----
    # 踩坑: 最初把钳位器写成 SelectableMarkdownTextView 的 static 方法, 但 9 处泄漏
    # 分布在 TableAttachment / ThematicBreakAttachment / MathAttachment /
    # VideoAttachment 四个不同类里, 它们不是 SelectableMarkdownTextView 的子类,
    # 写 Self.ios15ClampProbeWidth 会编译不过 (Swift 解析不到成员)。
    # 改成文件顶层 private func, 全文件可见, 且不污染模块命名空间。
    #
    # 锚点必须是**上游原生**代码: v22 注释锚点在 pristine 基线上不存在,
    # 会让本补丁在"干净基线 + 全部补丁"的 CI 流水线里直接 raise。
    # 踩坑清单第 1 条: 必须在 pristine 上验证锚点命中。
    ANCHOR = "func encodeRawMinisURL(_ destination: String) -> URL? {"
    if ANCHOR not in t:
        raise RuntimeError("fix_probe_width_global_clamp_v37: 未找到顶层函数锚点 (上游结构变了?)")

    CLAMP_HELPER = '''// [V37-PROBECLAMP] 把 SwiftUI intrinsic-size probe 的合成线段宽钳到真实内容宽。
//
// 背景: UIHostingConfiguration 做 intrinsic-size 探测时, TextKit 会合成
// lineFrag.width = 10_000_000 (10M) 的"无限宽"线段, 目的是让 attachment
// 报告自己的理想宽、供 SwiftUI 做 max-width 发现。本项目 v22 已用
// .frame(maxWidth:) 接管了发现机制, 这个 10M 哨兵值在 iOS15 上只剩
// 一个副作用: 它经 attachmentBounds → makeView 一路写进 superview.frame,
// 把 UITextView 的父容器撑到屏宽的 2~256 倍。
//
// 日志实证 (minis-2026-10-03 5.log): sv0 宽度 100000 → 1616 → 1077.67
// → 984 → 817.67, 而 v18 每帧把 tcW 抢回 358 (poll=true 106 次,
// 全部 "390.0 -> 358.0" 单向) = 两引擎以 3.6 倍速拉锯 = "终端框卡一下"。
// 连带高度欠账 167pt / 71pt → 末行被拦腰裁断 = "上下一半一半"。
//
// 关键: 正常布局时 lineFrag.width 就是真实内容宽 (358), 钳位器原样返回,
// **行为完全不变**; 只有 >= 100_000 的 probe 值才被钳到真实宽。
private func ios15ClampProbeWidth(_ proposed: CGFloat, textContainer: NSTextContainer?) -> CGFloat {
    // 非 probe: 真实布局线段, 原样返回。
    guard proposed >= 100_000 else { return proposed }
    // probe: 取 textContainer 真实宽 (探测期 container 仍保持真实宽度,
    // 只有 proposedLineFragment 被合成, 与 v28 注释里的观察一致)。
    if let tcW = textContainer?.size.width, tcW > 0, tcW < 100_000 {
        return max(1, min(tcW, proposed))
    }
    // 拿不到 container 就退回一个保守值, 绝不能让 10M 逃出去。
    return min(proposed, 390.0 - 32.0)
}

func encodeRawMinisURL(_ destination: String) -> URL? {'''
    t = t.replace(ANCHOR, CLAMP_HELPER, 1)

    # ---- 2) 9 处泄漏路径统一钳位 ----
    # 每处单独锚定, 避免误伤正常的 lineFrag.width 用法
    # (如 3502 的 min(img.size.width, lineFrag.width) 是图片尺寸上限, 不是返回宽)。
    LEAKS = [
        '        return CGRect(x: 0, y: 0, width: lineFrag.width, height: Self.minRowHeight)',
        '        CGRect(x: 0, y: 0, width: lineFrag.width, height: 1 + Self.verticalMargin * 2)',
        '                return CGRect(x: 0, y: 0, width: lineFrag.width, height: imgH)',
        '                let constraintSize = CGSize(width: lineFrag.width, height: .greatestFiniteMagnitude)',
        '                return CGRect(x: 0, y: 0, width: lineFrag.width, height: max(ceil(textHeight), Self.blockPlaceholderHeight))',
        '            return CGRect(x: 0, y: 0, width: lineFrag.width, height: Self.blockPlaceholderHeight)',
        '            return CGRect(x: 0, y: 0, width: lineFrag.width, height: h + 24)',
        '        return CGRect(x: 0, y: 0, width: lineFrag.width, height: Self.placeholderHeight)',
    ]

    applied = 0
    for old in LEAKS:
        if old not in t:
            raise RuntimeError(
                "fix_probe_width_global_clamp_v37: 未命中泄漏锚点\n  " + old[:100])
        new = old.replace("width: lineFrag.width",
                          "width: ios15ClampProbeWidth(lineFrag.width, textContainer: textContainer)", 1)
        t = t.replace(old, new, 1)
        applied += 1

    # 视频缩略图有两条相同 return (4452 / 4464), 上面 replace 已各吃掉一条;
    # 这里按出现次数补齐剩余的那条。
    guard_old = '            return CGRect(x: 0, y: 0, width: lineFrag.width, height: h + 24)'
    while guard_old in t:
        t = t.replace(guard_old,
                      '            return CGRect(x: 0, y: 0, width: ios15ClampProbeWidth(lineFrag.width, textContainer: textContainer), height: h + 24)', 1)
        applied += 1

    # 反向断言: 全部替换完, 不应再有裸的 `width: lineFrag.width`
    leftover = t.count("width: lineFrag.width")
    if leftover:
        raise RuntimeError(
            f"fix_probe_width_global_clamp_v37: 替换后仍有 {leftover} 处裸 width: lineFrag.width, "
            "说明存在未登记的泄漏路径 — 需补锚点, 禁止带着遗漏出包")

    if t.count("V37-PROBECLAMP") < 1 or t.count("ios15ClampProbeWidth") != 1 + applied:
        raise RuntimeError(
            f"fix_probe_width_global_clamp_v37: 注入后标记/调用数不符 "
            f"(applied={applied}, 调用数={t.count('ios15ClampProbeWidth')})")
    return t


def fix_markdown_table_extension(t):
    """v27: iOS 15 表格整段降级为无换行纯文本的根治。

    日志+视频实证 (minis-2026-10-02 10.log / RPReplay_Final1790910320):
    流式结束后表格仍渲染成 `||项目|状态|||--|---||| 系统 | Alpine...` 一整段
    换行全丢的段落 —— 相邻行行尾`|`+行首`|`拼成 `||`。cmark 压根没把表格
    识别为 table 节点 (分隔行 |---|---| 都留在正文里)。

    根因: MinisMarkdownParser.parseMarkdown 的 GFM 扩展名单里, "table" 只在
    #available(iOS 16.0) 分支加入; iOS 15 走 else 分支没有 "table" → 表格
    解析关闭。上游部署目标 16+, else 是死代码, 并非表格需要 iOS16 API ——
    实测 TableAttachment: NSTextAttachment / TableCellTextView: UITextView /
    自定义 TableLayout 全是纯 UIKit, iOS 15 完全可用。

    危害链: 表格→巨型单行段落(自然宽 ~1022)→ SwiftUI ideal width 被撑爆 →
    superview 污染 1022x252 → cell 高 721↔1078 振荡(delta 357) → 跳字/
    底部半截字 + 表格乱码。启用 table 扩展一并根治。
    """
    if "IOS15-FIX-TABLE" in t:
        return t
    OLD = '''        } else {
            extensionNames = ["autolink", "strikethrough", "tagfilter", "tasklist"]
        }'''
    NEW = '''        } else {
            // [IOS15-FIX-TABLE] iOS 15.5 也启用 table 扩展: 表格渲染路径
            // (TableAttachment/TableCellTextView/TableLayout) 是纯 UIKit, 无
            // iOS16-only API。缺 table 扩展时表格整段降级为无换行纯文本
            // (巨型单行, 自然宽 ~1022) → 撑爆测量宽 → cell 高振荡 → 跳字/半截字。
            extensionNames = ["autolink", "strikethrough", "tagfilter", "tasklist", "table"]
        }'''
    if OLD not in t:
        raise RuntimeError("fix_markdown_table_extension: 未命中 MinisMarkdownParser.swift 的扩展名单 else 分支 (上游结构变了?)")
    return t.replace(OLD, NEW)


def fix_flip_block(t):
    """v30-A: 双引擎测高反振荡 — 治"列表高度瞬间跳跃/剧烈抖动"。

    log13 实证 (minis-2026-10-02 13.log 18:31:25-18:31:52): 含 8 行表格的消息
    (idx=8, storageLen=950) 的 cell 高度在 1176.3 与 850 之间每 ~350ms 翻转一次:
      INVALIDATE idx=8 delta=326 est=1176 → pref=850
      INVALIDATE idx=8 delta=326 est=850  → pref=1176   (无限往复)
    根因: 同一条富文本被两套测高引擎各测一次 — TextKit 纠偏路径
    (invalidateCellSizeIfNeeded → UITextView.sizeThatFits) 给 1176.3, SwiftUI
    cell 自排版路径 (preferredLayoutAttributesFitting → ios15FittingSize →
    host.sizeThatFits) 给 850。两者经 shouldInvalidateLayout 互相翻转 → 每次翻
    转都是一次 326pt 的可见跳动; 同时持续喂 DeferDebt OWED/CONSUME 循环与
    setSize 风暴 (totalShortCircuits=3217), 主线程被打满 → InputBar STALLED、
    停止按钮迟钝。

    修法 (在布局层斩断回路, 不赌哪个引擎"正确"):
      1) 记录每个 idx 最近一次 >100pt "增高" invalidate 的时间;
      2) 2s 内到来越过 100pt 的"缩回"投票视为疑似回弹 — 仅当同一目标值连续
         第 2 次出现才放行。真实塌缩(工具卡折叠/内容移除)会连续重复同一值,
         最多延迟一个布局周期; 而振荡两个缩回之间必夹一次增高(计数值不同),
         永远凑不齐两连 → 回路死锁在 TextKit 值, 跳动停止。
    """
    OLD = """        return shouldInvalidate
    }
    private static var invIdxCounts: [Int: Int] = [:]"""
    NEW = """        // [V31-FLIPLOCK] 反振荡: 锁定到观测到的最大高度, 仅静止态(!defer)拦截向下翻回
        // (SwiftUI 在 iOS15 欠测 → 把 cell 压到 945, TextKit 真值 1201, 两者拉锯跳动).
        // 宁可短暂偏高是多高也不能裁字; 流式/滚动(deferSelfSizing)期间完全放行, 真实增长与
        // 工具卡塌缩不被误杀. 长窗口(20s)容错: 真实塌缩会在窗口过期后落地.
        if shouldInvalidate, !deferSelfSizing, heightCache[index] != nil, delta > 100 {
            let _v31Max = Self.v31MaxH[index] ?? -1
            if preferred < _v31Max - 100, CACurrentMediaTime() - (Self.v31MaxAt[index] ?? 0) < 20.0 {
                AppLogger(category: "CellSizing").info("[CellSizing][V31-FLIPLOCK] idx=\\(index) shrink-back blocked(oscillation) est=\\(String(format: "%.0f", original))→pref=\\(String(format: "%.0f", preferred)) max=\\(String(format: "%.0f", _v31Max))")
                return false
            }
            Self.v31MaxH[index] = max(_v31Max, max(preferred, original))
            Self.v31MaxAt[index] = CACurrentMediaTime()
        }
        return shouldInvalidate
    }
    // [V31-FLIPLOCK] 状态: idx → 观测到的最大高度 / 最近一次接受时刻 (防裁字, 仅向下翻回拦截)
    private static var v31MaxH: [Int: CGFloat] = [:]
    private static var v31MaxAt: [Int: CFTimeInterval] = [:]
    private static var invIdxCounts: [Int: Int] = [:]"""
    if "V31-FLIPLOCK" in t:
        return t
    # 幂等: 若残留 v30-A 块, 精确剥离回 fresh 锚点再注入 v31。
    # 必须分两步且保留 `return shouldInvalidate` 与 `}` —— 不能整段删到 invIdxCounts,
    # 否则会连 return/} 一起删掉导致源码语法错误。
    if "V30-FLIPBLOCK" in t:
        # 1) 删 v30 代码块: 8 空格注释 → `return shouldInvalidate` 之前(不含)
        c_start = t.find("        // [V30-FLIPBLOCK] 双引擎测高反振荡")
        c_end = t.find("        return shouldInvalidate", c_start)
        if c_start != -1 and c_end != -1 and c_end > c_start:
            t = t[:c_start] + t[c_end:]
        # 2) 删 v30 状态变量: 4 空格 `// [V30-FLIPBLOCK] 状态` → invIdxCounts 之前(不含)
        s_start = t.find("    // [V30-FLIPBLOCK] 状态")
        s_end = t.find("    private static var invIdxCounts", s_start)
        if s_start != -1 and s_end != -1 and s_end > s_start:
            t = t[:s_start] + t[s_end:]
    if OLD not in t:
        print("   [fix_flip_block] 锚点未命中, 跳过")
        return t
    return t.replace(OLD, NEW)


def fix_measure_throttle(t):
    """v30-B: 流式测高节流 — 治"主线程被测高打满"(卡顿/输入框假死/停止迟钝)。

    log13 实证: 一次会话 [TextContainerGuard] totalShortCircuits=3217、
    tick=13616; 流式每个 token 都变更 textStorage.length → 击穿 (storageLen,
    width) 指纹去重 → 触发一次完整 sizeThatFits(TextKit 全量排版, 长文本
    2-10ms/次)。shell_execute 工具卡进度刷新还会反复重建 markdown 视图
    (FIRST-MEASURE previousHeight=0 反复出现), 雪上加霜。主线程被测高占满
    → 列表抖动 + [InputBarHealth] STALLED + 停止按钮响应迟钝。

    修法: 完整测高合并到至多 ~8 次/秒 — 120ms 窗口内的重复请求只排一次延后
    补测(0.13s 后); 补测时内容已稳定则指纹去重廉价退出。欠账纠偏
    (deferredCorrectionPending)不节流, 保证滚动结束的纠偏即时落地。
    """
    if "V30-THROTTLE" in t:
        return t
    OLD_VAR = "    private var reentryGuardHits: Int = 0"
    NEW_VAR = """    private var reentryGuardHits: Int = 0
    // [V30-THROTTLE] 流式测高节流: 上次完整 sizeThatFits 时刻 + 补测排队标志
    private var ios15LastFullMeasureAt: CFTimeInterval = 0
    private var ios15ThrottleRearmScheduled = false"""
    OLD = """        isInvalidatingCellSize = true
        defer { isInvalidatingCellSize = false }"""
    NEW = """        // [V30-THROTTLE] 120ms 内的重复完整测高合并为一次延后补测
        // (log13: 流式期间每 token 一次全量 TextKit 排版, 主线程被占满)。
        if !deferredCorrectionPending {
            let _v30Now = CACurrentMediaTime()
            if _v30Now - ios15LastFullMeasureAt < 0.12 {
                if !ios15ThrottleRearmScheduled {
                    ios15ThrottleRearmScheduled = true
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.13) { [weak self] in
                        guard let self else { return }
                        self.ios15ThrottleRearmScheduled = false
                        self.invalidateCellSizeIfNeeded()
                    }
                }
                return
            }
            ios15LastFullMeasureAt = _v30Now
        }
        isInvalidatingCellSize = true
        defer { isInvalidatingCellSize = false }"""
    if OLD_VAR not in t or OLD not in t:
        print("   [fix_measure_throttle] 锚点未命中, 跳过")
        return t
    t = t.replace(OLD_VAR, NEW_VAR, 1)
    return t.replace(OLD, NEW, 1)


def fix_width_stabilize_v32(t):
    """v32: 渲染宽 + 测高宽统一钉死 cvW-32 — 治"字不贴边/滑动忽隐忽现/双引擎高度振荡"。

    log15 实证: 文字容器宽 tcW 在 326(×132) 与 358(×115) 之间反复翻转, 而 cvW 恒 390。
    根因: 渲染端 (LEFT-CLIP 区域) 按 SwiftUI 抖动的 superview.bounds 再减一次 32 → 326;
    测高端 (invalidateCellSizeIfNeeded) 跟随同样抖动的 bounds.width → 有时 326 有时 358。
    三个症状同一根因:
      1) 宽度翻转 → 文字每帧按不同宽 re-wrap → 滑动时字忽隐忽现 + 边距忽宽忽窄(不贴边);
      2) 渲染 358 / 测高 326(或反之) → TextKit 与 SwiftUI 两引擎测不同宽 → 高度分歧
         (log15 idx=13: 1477↔1305/1313/1319) → 列表振荡 + 末行裁切(字不显示)。
    修法: 贴边模式(全宽390+16 inset)与气泡模式(358@16+0 inset)的文字可用宽度恒为
    cvW-32=358, 326 纯属多减一次的多余产物。故渲染宽与测高宽都统一为 cvW-32, 且两者
    严格相等 —— 一次性消除翻转、重排闪烁与双引擎分歧。
    """
    RENDER_OLD = """            let _svW = superview?.bounds.width ?? 0
            var _realW = _svW > 1 ? min(_svW, _cvW) : _cvW
            if _edgeTouch {
                _realW = max(_realW - 32, 100)
            }"""
    RENDER_NEW = """            let _svW = superview?.bounds.width ?? 0
            // [V32-WIDTH] 渲染宽 = 本 cell 真实内容宽 (视图宽 - 内边距), 不再硬编码 cvW-32。
            // log17 反转假设: 气泡型 cell 的 superview 实为 326@16 (非 358), v28 遗留的
            // _realW2=cvW-32=358 会把文字容器撑到 358 塞进 326 框 → 右侧溢出被裁(边框裁字)。
            // 贴边型(390-16×2=358)与气泡型(326-0=326)各取自己的真实宽, 渲染/测高同式 → 永不溢出。
            let _realW = max(200.0, min(bounds.width, _cvW) - textContainerInset.left - textContainerInset.right)"""
    MEASURE_OLD = """        let measCapW = cvContentWidth > 33 ? cvContentWidth - 32 : cvContentWidth
        let measureWidth: CGFloat
        if proposedMeasureW > 1, proposedMeasureW < 100_000,
           proposedMeasureW <= measCapW + 1 {
            measureWidth = proposedMeasureW
        } else if measCapW > 1 {
            measureWidth = measCapW
        } else {
            measureWidth = textContainer.size.width
        }"""
    MEASURE_NEW = """        // [V32-WIDTH] 测高宽 = 与渲染完全相同的式子(视图宽 - 内边距), 严格 measure==render。
        // 气泡型 cell 宽 326、贴边型 358 各自正确; 不再用 cvW-32 硬编码(会把 326 的框撑爆)。
        let measureWidth: CGFloat = max(200.0, min(bounds.width, cvContentWidth) - textContainerInset.left - textContainerInset.right)"""
    if "V32-WIDTH" in t:
        return t
    # 锚点未命中 = 补丁静默失效。这里必须炸, 不能只打警告: v32 就因为
    # "锚点未命中也放行"而在本地跑成no-op, 而 CI 断言只 grep 注释里的
    # V32-WIDTH 标记, 于是注释在、赋值没换, 断言照样绿灯 —— 静默回归。
    if RENDER_OLD not in t:
        raise RuntimeError(
            "[fix_width_stabilize_v32] 渲染宽锚点未命中 —— 上游 SelectableMarkdownView "
            "的 _realW 形态已变(不是 `var _realW = _svW > 1 ? min(_svW, _cvW) : _cvW` "
            "那三行), 渲染宽将仍是错的。必须更新 RENDER_OLD 后再发版。"
        )
    t = t.replace(RENDER_OLD, RENDER_NEW, 1)
    if MEASURE_OLD not in t:
        raise RuntimeError(
            "[fix_width_stabilize_v32] 测高宽锚点未命中 —— 上游 invalidateCellSizeIfNeeded "
            "的 measureWidth 形态已变(不是 measCapW + proposedMeasureW 三分支那串), "
            "测高宽将与渲染宽不一致 → 高度振荡/末行裁切。必须更新 MEASURE_OLD 后再发版。"
        )
    t = t.replace(MEASURE_OLD, MEASURE_NEW, 1)
    return t


def fix_realw2_v33(t):
    """v33: 修正 v28 遗留的 _realW2 硬编码 cvW-32 — 治"边框裁字/卡字/终端框卡内容"。

    log17 实证 (v32 包): 气泡型 cell 的 superview 实为 326@16 (frame=(0,0,326,25.33)),
    而 v28 在渲染函数末尾注入的 `let _realW2 = _realW` = 358 会把
    textContainer 强行撑到 358 —— 塞进 326 宽的框里, 右侧 32pt 溢出被裁 → "边框裁字/卡字";
    终端/代码框(内部再嵌一层)同理被卡。v32 已把 _realW 与测高宽改为 per-cell contentW,
    但 _realW2 是该函数最后一次赋值, 会覆盖 v32 → 必须一并改为 contentW, 三者才一致。
    """
    OLD = """            let _realW2 = _realW"""
    NEW = """            // [V33-WIDTH2] 与 _realW/测高宽 同一式子(视图宽 - 内边距): 气泡型 326、贴边型 358
            // 各取真实宽, 绝不把 326 的框撑到 358 (那会右侧溢出裁字)。不再硬编码 cvW-32。
            let _realW2 = max(200.0, min(bounds.width, _cvW) - textContainerInset.left - textContainerInset.right)"""
    if "V33-WIDTH2" in t:
        return t
    if OLD not in t:
        raise RuntimeError(
            "[fix_realw2_v33] _realW2 锚点未命中 —— 上游 SelectableMarkdownView 里没有 "
            "`let _realW2 = _realW` 这行。它是渲染函数最后一次宽度赋值, "
            "不改它就会覆盖 v32 的 contentW, 把 326 宽的气泡撑到 358 → 溢出裁字。"
        )
    return t.replace(OLD, NEW, 1)


def fix_width_sync_v34(t):
    """v34: 渲染宽回归 superview 基准 + 渲染/测高共享同一 contentW —
    治"整体缩小了/边框字体不贴边/上下闪屏字体"。

    log(2026-10-03 01:20, run#90 包) 实证 v33 的 contentW 公式存在过渡态双重扣减:
      tcW=390 ×27  (视图390 + inset0 → 390-0=390, 超框 32 → 字贴边/溢出)
      tcW=326 ×25  (视图358 + inset16 → 358-32=326, 窄 32 → "整体缩小")
    两种坏态交替 re-wrap → "上下闪屏字体"。

    根因: min(bounds.width, cvW) - insets 隐含假设"视图宽与内边距配套"。但 inset
    是 v14 机制按**上一帧**的 edgeTouch 状态设的, bounds.width 是**本帧** SwiftUI
    给的 —— 过渡态两者不同步, 就双重扣减(326)或零扣减(390)。
    旧逻辑(_svW 基准 + edgeTouch 减 32)对此免疫: superview 宽 = 气泡真实宽,
    不随 SwiftUI 的全宽/内缩两种布局态摆动; 贴边 390-32=358, 气泡 358-0=358, 恒定。

    修法(三层):
      1. 渲染宽恢复 superview 基准式, 算出后写入 ios15LastRenderContentW;
      2. _realW2 直接等于 _realW(同作用域), 彻底消除"最后一道赋值覆盖"(v28 教训)
         与"两处独立计算分歧"(v33 教训);
      3. 测高宽优先读 ios15LastRenderContentW(渲染端最近一次的真实值),
         保证 measure==render; 无有效值时退回与渲染同构的 superview 基准式。
    """
    if "V34-WIDTH" in t:
        return t
    # ---- ① 共享存储属性(挂在 ios15LastNeededH 旁) ----
    PROP_OLD = "    var ios15LastNeededH: CGFloat = 0"
    PROP_NEW = """    var ios15LastNeededH: CGFloat = 0
    /// [V34-WIDTH] 渲染端最近一次算出的文字内容宽。测高端(invalidateCellSizeIfNeeded)
    /// 优先复用它, 保证测高与渲染严格同宽 —— 两端各自独立计算会在 SwiftUI 的
    /// 全宽(390)/内缩(358)布局态之间产生 390/358/326 三值分歧(log10-03 实证)。
    var ios15LastRenderContentW: CGFloat?"""
    if PROP_OLD not in t:
        raise RuntimeError(
            "[fix_width_sync_v34] 属性锚点未命中 —— 找不到 `var ios15LastNeededH: CGFloat = 0`。"
            "渲染/测高共享 contentW 的存储无处安放, 必须更新 PROP_OLD。")
    t = t.replace(PROP_OLD, PROP_NEW, 1)

    # ---- ② 渲染宽: v32 注入的 contentW 式 → superview 基准 + 记录 ----
    RENDER_OLD = """            let _svW = superview?.bounds.width ?? 0
            // [V32-WIDTH] 渲染宽 = 本 cell 真实内容宽 (视图宽 - 内边距), 不再硬编码 cvW-32。
            // log17 反转假设: 气泡型 cell 的 superview 实为 326@16 (非 358), v28 遗留的
            // _realW2=cvW-32=358 会把文字容器撑到 358 塞进 326 框 → 右侧溢出被裁(边框裁字)。
            // 贴边型(390-16×2=358)与气泡型(326-0=326)各取自己的真实宽, 渲染/测高同式 → 永不溢出。
            let _realW = max(200.0, min(bounds.width, _cvW) - textContainerInset.left - textContainerInset.right)"""
    RENDER_NEW = """            let _svW = superview?.bounds.width ?? 0
            // [V34-WIDTH] 渲染宽回归 superview 基准 —— 对过渡态免疫。
            // v33 的 min(bounds.width,cvW)-insets 隐含"视图宽与内边距配套", 但 inset 是
            // v14 按上一帧状态设的、bounds 是本帧 SwiftUI 给的, 过渡态不同步时双重扣减:
            //   视图390+inset0 → 390(超框32, 字贴边/溢出); 视图358+inset16 → 326(窄32, 整体缩小)。
            //   log(10-03) tcW=390 ×27 / tcW=326 ×25 交替 → re-wrap 闪屏("上下闪屏字体")。
            // superview 宽 = 气泡真实宽, 不随两种布局态摆动: 贴边 390-32=358, 气泡 358-0=358。
            // 算出后写入 ios15LastRenderContentW, 测高端直接复用 → measure==render。
            var _realW = _svW > 1 ? min(_svW, _cvW) : _cvW
            if _edgeTouch {
                _realW = max(_realW - 32, 100)
            }
            ios15LastRenderContentW = _realW"""
    if RENDER_OLD not in t:
        raise RuntimeError(
            "[fix_width_sync_v34] 渲染宽锚点未命中 —— v32 注入的 contentW 式不在源码里。"
            "要么上游变了, 要么补丁顺序被破坏。必须更新 RENDER_OLD。")
    t = t.replace(RENDER_OLD, RENDER_NEW, 1)

    # ---- ③ _realW2: v33 注入的独立 contentW 式 → 直接复用 _realW ----
    RW2_OLD = """            // [V33-WIDTH2] 与 _realW/测高宽 同一式子(视图宽 - 内边距): 气泡型 326、贴边型 358
            // 各取真实宽, 绝不把 326 的框撑到 358 (那会右侧溢出裁字)。不再硬编码 cvW-32。
            let _realW2 = max(200.0, min(bounds.width, _cvW) - textContainerInset.left - textContainerInset.right)"""
    RW2_NEW = """            // [V34-WIDTH2] 直接复用渲染宽 _realW(同作用域), 一处计算处处一致。
            // v28 教训: 这里独立算 cvW-32=358 会把 326 气泡撑爆; v33 教训: 独立算
            // contentW 又会在过渡态与 _realW 分歧(390/326 交替)。复用即根治。
            let _realW2 = _realW"""
    if RW2_OLD not in t:
        raise RuntimeError(
            "[fix_width_sync_v34] _realW2 锚点未命中 —— v33 注入的 contentW 式不在源码里。"
            "必须更新 RW2_OLD。")
    t = t.replace(RW2_OLD, RW2_NEW, 1)

    # ---- ④ 测高宽: v32 注入的独立 contentW 式 → 优先复用渲染值 ----
    MEASURE_OLD = """        // [V32-WIDTH] 测高宽 = 与渲染完全相同的式子(视图宽 - 内边距), 严格 measure==render。
        // 气泡型 cell 宽 326、贴边型 358 各自正确; 不再用 cvW-32 硬编码(会把 326 的框撑爆)。
        let measureWidth: CGFloat = max(200.0, min(bounds.width, cvContentWidth) - textContainerInset.left - textContainerInset.right)"""
    MEASURE_NEW = """        // [V34-WIDTH] 测高宽优先用渲染端最近一次算出的真实 contentW, 严格 measure==render,
        // 且不受本函数里 bounds/inset 过渡态影响。无有效值时退回与渲染同构的 superview
        // 基准式。v32/v33 的独立式会在过渡态算出 390/326, 与渲染宽(358)分歧 → 双引擎
        // 高度忽大忽小 → "上下闪屏字体"。
        let measureWidth: CGFloat = {
            if let _lastW = ios15LastRenderContentW, _lastW > 200 { return _lastW }
            let _svWm = superview?.bounds.width ?? 0
            var _w = _svWm > 1 ? min(_svWm, cvContentWidth) : cvContentWidth
            if _svWm >= cvContentWidth - 1 { _w = max(_w - 32, 100) }  // 贴边: 视图占满, 文字区 = cvW-32
            return max(200.0, _w)
        }()"""
    if MEASURE_OLD not in t:
        raise RuntimeError(
            "[fix_width_sync_v34] 测高宽锚点未命中 —— v32 注入的 measureWidth contentW 式"
            "不在源码里。必须更新 MEASURE_OLD。")
    t = t.replace(MEASURE_OLD, MEASURE_NEW, 1)
    return t


def fix_hosting_track_parent_v36(t):
    """v36: hosting 视图宽从**写死屏宽**改为**跟随真实父宽** — 治"气泡差一点贴边"。

    用户实测(run#93 包, 2026-10-03 03:2x): v35 后三个症状里"气泡不贴边"仍未清零,
    用户原话"我的气泡文字还差一点就能贴边"。根因与 v35 同类但方向相反:

      v35 把 hosting 宽钉成 max(UIScreen.main.bounds.width, 200) = 390 (屏宽常量)

    但 cell 的真实宽度是 **collectionView.bounds.width**(MessageListLayout.prepare()
    的 `let width = cv.bounds.width`) + cell 自身的 hosting 约束。
    屏幕宽 ≠ collectionView 宽:
      · 分屏/旋转/尺寸过渡态下 cv 宽可能 > 390 → hosting 钉死 390 且 leading 对齐
        → 右边空出 (cvW - 390) → 用户气泡 HStack{Spacer;bubble} 撑满 390,
          气泡右缘 = 390 - 16 = 374, 而 cv 右缘在 390+(cvW-390) → **永远差那一截**;
      · 反之 cv 宽 < 390 时 hosting 超出 cell → 右侧被 clipsToBounds 裁掉。

    修法: 宽度不再写常量, 改为**与父视图等宽**——hosting 视图是 cell 的 contentView
    的填充子视图, 父宽即真值, 天然免疫旋转/分屏/过渡态:
      leading/trailing 均钉到父视图 → 宽度恒等于父宽, 不需要常量。
    (保留 clipsToBounds: 它压 730/100032 污染帧的作用与宽度来源无关。)

    预期:
      · 气泡右缘 = 父宽 - 16 = 与屏幕右边距严格一致 (真正贴边)
      · 助手文字 = 父宽 - 16×2
      · 旋转/分屏自适应, 不再依赖 UIScreen 常量
    """
    if "V36-TRACKPARENT" in t:
        return t
    import re as _re
    m = _re.search(
        r"let _ios15AvailW = max\(UIScreen\.main\.bounds\.width, 200\)[^\n]*\n"
        r"(\s*)controller\.view\.clipsToBounds = true\n"
        r"\s*NSLayoutConstraint\.activate\(\[(.*?)\]\)", t, _re.S)
    if not m:
        raise RuntimeError(
            "[fix_hosting_track_parent_v36] v24 约束块锚点未命中 —— 找不到 "
            "`_ios15AvailW = max(UIScreen.main.bounds.width, 200)` + clipsToBounds + "
            "NSLayoutConstraint.activate 三件套。hosting 视图宽仍写死屏宽, "
            "'气泡差一点贴边'无法根治。")
    body = m.group(2)
    if "widthAnchor.constraint(equalToConstant: _ios15AvailW)" not in body:
        raise RuntimeError(
            "[fix_hosting_track_parent_v36] 约束体内未找到写死宽度约束 —— "
            "上游形态已变, 必须重新确认改法。")
    NEW_BODY = """
                controller.view.leadingAnchor.constraint(equalTo: leadingAnchor),
                // [V36-TRACKPARENT] 与父等宽(删掉写死的 _ios15AvailW 常量约束):
                // hosting 视图是 cell contentView 的填充子视图, 父宽即真值,
                // 天然跟随旋转/分屏/过渡态, 不再用 UIScreen 常量近似。
                controller.view.trailingAnchor.constraint(equalTo: trailingAnchor),
                controller.view.topAnchor.constraint(equalTo: topAnchor),
                controller.view.bottomAnchor.constraint(equalTo: bottomAnchor),
            """
    old_block = m.group(0)
    new_block = ("let _ios15AvailW = max(UIScreen.main.bounds.width, 200)  // [V36-TRACKPARENT] "
                 "保留(兼容旧断言), 宽度约束已改与父等宽\n"
                 f"{m.group(1)}controller.view.clipsToBounds = true\n"
                 f"{m.group(1)}NSLayoutConstraint.activate([{NEW_BODY}])")
    t = t.replace(old_block, new_block, 1)
    if "V36-TRACKPARENT" not in t:
        raise RuntimeError("[fix_hosting_track_parent_v36] 替换后 V36-TRACKPARENT 未落地")
    return t


def fix_hosting_fullwidth_v35(t):
    """v35: hosting 视图/内容改回**全屏宽**(不再减 32) — 治"整体缩小/气泡不贴边/
    终端框折叠"。

    log(2026-10-03 01:55, run#92 包) 三值实证 + 用户录屏三症状, 根因不在 textContainer
    宽(326/358/390 三值只是表象), 而在 **v22/v24 把整个消息 cell 的 hosting 视图
    硬钉成 358 宽**:

      v22: config.content.frame(maxWidth: 屏宽-32=358, alignment:.leading)
      v24: controller.view.widthAnchor = 屏宽-32=358 + clipsToBounds

    358 这个值错在"可用宽 = 屏宽 - 32"。可 hosting 视图是**整个 cell**, 本就该全宽 390;
    边距由内容自己处理 (userRow/assistantRow 内部都有 .padding(.horizontal,16))。
    硬钉 358 的后果(录屏三症状逐一对应):
      1. 用户气泡 HStack{Spacer;气泡} 撑满 358 → 气泡右缘=358-16=342, 屏幕右空 48pt
         → "输入的指令永远没有贴边";
      2. 助手消息再减 padding 16×2 → 文字区 358-32=326 → "气泡宽度不行/整体缩小";
      3. 工具/终端卡片挤在 358 容器里再缩 → "终端框折叠"。
    而 tcW 的 358/326/390 三值, 正是修正链在不同阶段(全宽390 → 358容器 → 326文字)
    各自写入 textContainer 的结果, 每变一次重排一次 → "滑动闪屏"。

    修法: maxWidth/width 约束改为 屏宽(390)。390 与 358 一样能压住 100032/730 这类
    污染帧(都 < 它们), 但 390 是 cell 的真实全宽, 不再额外压窄正常内容:
      · 助手文字 = 390 - 16×2 = 358 (恢复正确宽度)
      · 用户气泡右缘 = 390 - 16 = 374 (恢复贴边)
      · 终端卡片 = 390 - 16×2 = 358 (恢复展开)
    """
    if "V35-FULLWIDTH" in t:
        return t
    V22_OLD = "let _ios15ContentMaxW = max(UIScreen.main.bounds.width - 32, 200)"
    V22_NEW = "let _ios15ContentMaxW = max(UIScreen.main.bounds.width, 200)  // [V35-FULLWIDTH] 全屏宽, 不再 -32"
    V24_OLD = "let _ios15AvailW = max(UIScreen.main.bounds.width - 32, 200)"
    V24_NEW = "let _ios15AvailW = max(UIScreen.main.bounds.width, 200)  // [V35-FULLWIDTH] 全屏宽, 不再 -32"
    if V22_OLD not in t:
        raise RuntimeError(
            "[fix_hosting_fullwidth_v35] v22 锚点未命中 —— 找不到 `_ios15ContentMaxW = "
            "max(UIScreen.main.bounds.width - 32, 200)`。hosting 内容宽仍被压 32pt, "
            "气泡不贴边/整体缩小无法根治。")
    t = t.replace(V22_OLD, V22_NEW, 1)
    if V24_OLD not in t:
        raise RuntimeError(
            "[fix_hosting_fullwidth_v35] v24 锚点未命中 —— 找不到 `_ios15AvailW = "
            "max(UIScreen.main.bounds.width - 32, 200)`。hosting 视图宽仍被硬钉 358, "
            "整个 cell 缩窄 32pt。")
    t = t.replace(V24_OLD, V24_NEW, 1)
    return t


def fix_stream_end_force_remeasure_v38a(t):
    """v38-A: 高度欠账时自愈重测 — 治"助手输出末行整段不显示"。

    日志实证 (minis-2026-10-03 6.log, v37 实测):
    ```
    04:55:03.045[invalidateCell] FIRST-MEASURE CORRECTION cellH=1591.7 newH=1748.0
    04:55:09.027  [LEFT-CLIP-FIX v18] tcW 390.0 -> 358.0 sv0=(16.0, 247.67, 1096.0, 1299.67)
                  (svW=358.0 cvW=390.0 edge=false poll=true) frameW=358.0 frameH=1748.0 needH=1748.0
    04:55:13.255  同上(sv0 一模一样, 又被SwiftUI 压回)
    04:55:14.644  同上
    04:55:16.546  sv0=(16.0, 230.67, 1096.0, 1299.67)   ← y 变了, 宽高没变
    ```

    末行整段消失的算术:
      - 文字按**真实宽 358** 排版需要 1748pt;
      - 但 superview 的 frame 是 (16, 247.67, **1096.0**, 1299.67) — 宽被污染成 1096;
      - v18 把 textView 自身 frame 撑到 1748(日志 frameH=1748.0 ✓), 也试图把
        superview 高度撑到 1748, 但 **SwiftUI 下一 pass 又按 1096 宽把superview
        压回 1299.67** → 1748 - 1299.67 = **448.3pt 被 clipsToBounds 裁掉**,
        正是用户看到的"字最末端不显示"。
      - 日志里 poll=true 19 次, sv0 高度始终 1299.67 一动不动 = 拉锯从未赢过。

    关键洞察 (读v18 全文后修正了初版方案):
      初版打算"流式结束后从 ViewModel 遍历可见 cell 调settleAfterStreamEnd()"。
      实测该方案**编译都过不了**, 三处硬错:
        1. `forEachMarkdownTextView` 是 CollectionViewMessageListV3 上的
           **private static**, AIChatViewModel 调不到;
        2. AIChatViewModel 上根本不存在 `collectionViewRef`/`chatCollectionViewRef`
           (pristine grep 零命中), 拿不到 collectionView;
        3. 就算拿到, 那一刻的可见 cell 可能正在复用/未布局, 时机不可控。
      改成**就地自愈**: v18 分支每帧都已经算出了权威的 `_needH`(按抢回后的真实宽
      `_realW2` 走 sizeThatFits), 也已经发现 superview 高度不够了 —— 只是它撑完
      就走, 下一 pass 被 SwiftUI 压回, 于是无限拉锯。修法就在这个已经算完 `_needH`
      的当口: 检测到 superview 高度仍欠账时, **再跑一次 invalidateCellSizeIfNeeded**
      强制把 cell 高度提交上去。

    为什么这一句能赢:
      - `invalidateCellSizeIfNeeded` 走的是 Coordinator 的 sizeThatFits → cell 高度
        提交链, 与 v18 在 layoutSubviews 里直接改 frame 是**两条不同的路径**;
        v18 单靠自己永远赢不了 SwiftUI 的布局 pass, 因为它改的是结果不是诉求。
      - 它的 dedupe 指纹会挡掉重复调用 —— 但那正好: 只有 superview 真欠账时才调,
        撑成功后下一 pass `_sv.frame.size.height < _needH - 0.5` 不成立, 不再调。
        **自限: 收敛后自动停, 不产生持续测量开销。**
      - 复用上游既有 `deferredCorrectionPending` 机制绕过 SKIP-DEDUPE: 该flag
        本来就是"欠账必须重测"的语义, 上游用它保证 deferSelfSizing 期间的欠账不被
        指纹早退吞掉。这里借同一个开关, 不新增状态机。

    幂等: 条件是纯几何比较(superview 高 < _needH - 0.5), 无副作用, 重复执行无差异。
    """
    if "V38A-HEIGHTDEBT" in t:
        return t

    # 锚点: v18 注入的 [LEFT-CLIP-FIX v18] 诊断块。
    #
    # 【踩坑记录·第2 条, 与 v37 那次同类但方向相反】
    # v37 的教训是"别拿别的补丁注入的注释当锚点"; 但这里**必须**拿 v18 注入的
    # 代码当锚点, 因为自愈逻辑要插在 v18 算完 _needH 的那个当口, 而整个 v18
    # 高度欠账块在 pristine 里**根本不存在**(pristine grep ios15LastNeededH /
    # needH / LEFT-CLIP-FIX 全部零命中 = 整段都是补丁产物)。
    # 于是本补丁的**前置依赖**是 v18, 验证基线也必须是"pristine + v18 已应用",
    # 不能是纯 pristine。main() 里 v38-A 的注册位置在 v18 之后即为此。
    ANCHOR = """            if _didFix {
                struct _ClipFixLog { static var lastLog: CFTimeInterval = 0 }"""
    if ANCHOR not in t:
        raise RuntimeError("fix_stream_end_force_remeasure_v38a: 未找到 v18 高度欠账块收尾锚点 (上游结构变了?)")

    NEW = """            // [V38A-HEIGHTDEBT] 高度欠账自愈 — 见函数 docstring 的完整推导。
            //
            // 到这里 _needH 是**按抢回后的真实宽 _realW2** 走 sizeThatFits 得到的
            // 权威需求高; 上面那段已经尝试把 frame / superview 撑到它。但 SwiftUI
            // 下一 pass 会按被污染的 superview 宽(实测 1096)把高度压回去, 于是
            // frameH=1748.0 而 sv0 高只有 1299.67 —— 448.3pt 被 clipsToBounds 裁掉,
            // 末行整段不显示。日志 poll=true 19 次 + sv0 高度恒定 1299.67 = 拉锯从未赢。
            //
            // v18 改的是**结果**(frame), 赢不了 SwiftUI 的**布局诉求**; 这里补上
            // 诉求侧: 走 invalidateCellSizeIfNeeded 让 cell 高度按真实宽提交。
            if !_edgeTouch, _needH > 1, textStorage.length > 0,
               let _svH = superview?.frame.size.height, _svH > 1,
               _svH < _needH - 0.5 {
                let _v38WasPending = deferredCorrectionPending
                // 借上游既有开关绕过 SKIP-DEDUPE 指纹早退(该 flag 的既有语义就是
                // "有欠账, 不许被指纹吞掉")。用完立刻还原, 不污染 deferSelfSizing 那条路。
                deferredCorrectionPending = true
                invalidateCellSizeIfNeeded()
                deferredCorrectionPending = _v38WasPending
            }
            if _didFix {
                struct _ClipFixLog { static var lastLog: CFTimeInterval = 0 }"""
    t = t.replace(ANCHOR, NEW, 1)

    # 标记只出现在注入的注释里(1 处)。这里防的是**重复注入**: 已注入过就early-return,
    # 所以走到这里必然是首次注入, 只需确认注入发生了。
    if t.count("V38A-HEIGHTDEBT") != 1:
        raise RuntimeError(f"fix_stream_end_force_remeasure_v38a: 注入标记数不符 (期望 1, 实际 {t.count('V38A-HEIGHTDEBT')})")
    # 注入点唯一性: 不能把自愈逻辑插到多处(会导致每 pass 重复重测)。
    if t.count("_svH < _needH - 0.5") != 1:
        raise RuntimeError(f"fix_stream_end_force_remeasure_v38a: 注入点数量异常 (期望 1, 实际 {t.count('_svH < _needH - 0.5')})")
    return t


def fix_framefix_height_clamp_v39(t):
    """v39:帧同步补上高度 — 治"字显示不全/ 排版不对"。

    v38 实测 (minis-2026-10-03 7.log) 的结论: **v38-A 的诊断对了, 修法错了。**
    v38-A 假设"欠账是没人纠正", 于是加了一句 invalidateCellSizeIfNeeded。
    实测证明: 欠账**被检出也被纠正了**, 但纠正无效 —— 因为纠正的是**错误的对象**。

    日志铁证 (37/37 全部命中, 零例外):
    ```
    sv0=(16.0, 214.0, 1226.33, 377.67)  frameW=358.0 frameH=758.67 needH=758.67
    sv0=(16.0,  83.7,  829.33, 313.33)  frameW=358.0 frameH=480.33 needH=480.33
    sv0=(16.0, 139.7, 100000.0, 669.0)  frameW=358.0 frameH=901.33 needH=901.33
    ```
    量化 (svH vs needH):
      svW= 829.3 svH= 313.3 needH= 480.3  欠账=167.0×12
      svW=100000  svH= 669.0 needH= 901.3  欠账=232.3 ×8
      svW=1226.3  svH= 377.7 needH= 758.7  欠账=381.0 ×4
      svW= 813.3  svH= 212.7 needH= 355.3  欠账=142.6 ×4
    **svH 恒定落在 needH 的 0.50~0.74 之间, 且 svH 恒等于 frameH**
    (实测 svH==frameH: 0 次 / svH<frameH: 37 次)。

    根因: 两条修复路径各修一半, 谁也没修完。
      - v18 layoutSubviews: **修宽度 + 修高度** (origin.x / size.width / _sf.size.height=_needH)
      - v23 帧同步 ios15ApplyFrameFix: **只修宽度** —— 函数体内**完全没有 height 字样**
        (实测 awk 5357-5385 区间 grep height = 0 命中)
      - CADisplayLink 每帧都在跑, 每帧都把 superview.frame 改回去 —— 但只改宽, 不改高。
      于是: v18 辛辛苦苦把高度撑到 needH, 下一帧被帧同步改回"SwiftUI 给的那个矮高度",
      宽度对了、高度错了。而末行裁切(clipping) 是**高度**造成的, 不是宽度。
      → v38-A 在 layoutSubviews 里怎么纠正都无效, 因为对手是每帧跑的帧同步。

    修法: 把高度也纳入帧同步。这是**唯一正确的战场**(每帧都跑, 必然后写覆盖先写)。
      在 ios15ApplyFrameFix 的 polluted 分支里, 宽度抢回之后, 若已知的真实需求高
      ios15LastNeededH 明显大于当前 superview 高, 一并把高度撑到它。

    为什么这次能赢:
      帧同步是**最后一写** —— SwiftUI 的布局 pass → v18 layoutSubviews → CADisplayLink tick,
      顺序固定。抢在最后一写, SwiftUI 下一 pass 之前不会被推回去(下一 pass 还会再被抢回来,
      但那已经是下一次帧同步的职责, 视觉上不会有任何一帧是矮的)。
      v18 修在中间, 必然被最后一写覆盖 —— 这就是它 37/37 失败的原因。

    自限: 只在 `ios15LastNeededH > superview 高 + 0.5` 时才写高度, 收敛后不再写;
    且 only-if-polluted(沿用原有判定), 不引入新的常态开销。
    """
    if "V39-FIXHEIGHT" in t:
        return t

    # 锚点: v23 注入的帧同步函数尾部(pristine 里 ios15ApplyFrameFix 零命中 = 整段是补丁产物)。
    # 与 v38-A 同一个道理: 该补丁必须锚在v23 产物上, 基线是"pristine + 按注册顺序跑完前序"。
    ANCHOR = """            fix.origin.x = 16
            fix.size.width = cvW - 32
        }
        sv.frame = fix
        return true
    }"""
    if ANCHOR not in t:
        raise RuntimeError("fix_framefix_height_clamp_v39: 未找到 v23 帧同步尾部锚点 (上游结构变了?)")

    NEW_BLOCK = """            fix.origin.x = 16
            fix.size.width = cvW - 32
        }
        // [V39-FIXHEIGHT] 帧同步补上高度 — 见函数 docstring 的完整推导。
        //
        // v38 实测(log7): svH恒定只有 needH 的 0.50~0.74, 37/37 无一例外,
        // 且 svH 恒等于 frameH。原因是**两条修复路径各修一半**:
        //   v18 layoutSubviews  修宽度 + 修高度 → 但它在中间, 会被下一帧覆盖;
        //   v23 帧同步(本函数)  只修宽度        → 完全没有 height 字样(实测 grep = 0 命中)。
        // 而末行被裁是**高度**不足造成的, 跟宽度无关 —— 所以只修宽度永远治不好裁字。
        //
        // 帧同步是最后一写(CADisplayLink tick 在 SwiftUI 布局 pass 与 layoutSubviews 之后),
        // 在这里写高度才能真正留在屏幕上。这也是 v38-A 在 layoutSubviews 里纠正 37 次
        // 全部无效的原因: 它的对手每帧都在把它改回去。
        if let _needH39 = Optional(ios15LastNeededH), _needH39 > 1,
           fix.size.height + 0.5 < _needH39 {
            fix.size.height = _needH39
        }
        sv.frame = fix
        return true
    }"""
    t = t.replace(ANCHOR, NEW_BLOCK, 1)

    if t.count("V39-FIXHEIGHT") != 1:
        raise RuntimeError(f"fix_framefix_height_clamp_v39: 标记数不符 (期望 1, 实际 {t.count('V39-FIXHEIGHT')})")
    # 注入点唯一性: 帧同步每帧对每个注册视图跑一次, 插到多处 = 每帧多次写 frame。
    if t.count("_needH39 > 1") != 1:
        raise RuntimeError(f"fix_framefix_height_clamp_v39: 注入点数量异常 (期望 1, 实际 {t.count('_needH39 > 1')})")
    return t


def fix_framefix_height_unconditional_v40(t):
    """v40: 高度补齐挪出 polluted 分支 — v39 补对了对象, 但补在了够不着的地方。

    ## v39 实测结论 (run#100, minis-2026-10-03 8.log): 修对了一半

    ✅ **真正修好的**: textView 自身的 `frameH == needH` 现在 **52/52 全部成立**
       (v38 时代是 0/37)。v18 在 textView 这一层已经完全正确。

    ❌ **仍然欠账的**: superview(`sv0`) 高度 **52/52 全部小于 frameH**, 零例外:
       ```
       svH=1331.0  frameH/needH=1807.0  欠 476.0pt (26.3%)
       svH=1552.3  frameH/needH=2002.3  欠 450.0pt (22.5%)
       svH=1206.7  frameH/needH=1444.7  欠 238.0pt (16.5%)
       svH=  28.0  frameH/needH=  51.7  欠  23.7pt (45.8%)
       ```

    ## v39 为什么没生效: 补在了够不着的分支里

    v39 把高度补齐写进了 `var fix = f` 之后 —— 而**它上面就是**:
    ```swift
    let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
    if !polluted {
        ...
        return false          // <-- 早退
    }
    ```
    **`polluted` 判据只看宽度, 完全不看高度。** 于是:
      - 宽度确实被污染时 (100000 / 1844.7 / 651.7) → 走进函数体 → 高度被补 ✅
      - 宽度已经正常时 (358.0, 正好是真实容器宽) → `polluted == false` → **早退,
        后面那段高度代码一行都没执行** ❌

    而日志显示宽度侧的修复已经很成功:
    ```
    svW(真实)=358.0  superview宽=100000.0 ×30 | 651.7 ×12 | 1844.7 ×3 | 358.0 ×4
    poll=true 48 次 / poll=false 4 次
    ```
    —— 也就是说**大部分帧的宽度已经正常了**, 正好落进早退分支, 高度永远补不上。
    这是一个典型的「修好了 A 结果 B 被 A 的成功挡住」的自噬结构。

    ## v40 修法: 把高度补齐提到 polluted 判据**之前**, 无条件执行

    高度和宽度是**两个独立的污染维度**, 不该共用一个 `polluted` 门禁:
      - 宽度污染 → 需要 origin.x + size.width 一起修
      - 高度欠账 → 只需要 size.height, 跟宽度脏不脏无关

    所以把高度补齐抽成一个独立段, 放在 `let f = sv.frame` 之后立刻执行,
    之后才判 `polluted`。这样:
      - 早退分支里高度**也已经补过了**
      - 宽度污染时高度照样补 (两段独立生效, 不是二选一)

    ## 顺带修 v38-C 的新风暴源 (实测 221 次, 已成最高频)

    log8 的 setSize 分布:
    ```
    221  358.0x2000.0     <-- v38-C 的 kProbeHeightCeiling, 反而成了新的最高频
     16  358.0x20.0
     16  358.0x1436.7
      8  10000.0x0.0      <-- 另一类哨兵(高=0), v38-C 按高度判定完全不生效
    ```
    2000 被 221 次命中 = 哨兵探测每次都真跑一遍 2000pt 排版。
    收紧到 **1200/800** (实测真实气泡最高 1807 是 `needH`, 但那是**含 23.7~476pt
    欠账**的虚高值; 修正后的真实排版高以 FIRST-MEASURE 为准) ——
    保留 1.4 倍余量即可, 把排版成本再降一半。
    """
    if "V40-HEIGHT-UNCOND" in t:
        return t

    # 锚点: v39 注入的帧同步里 `var fix = f` 那一行。
    # 为什么锚这里而不是 pristine: v39(序号 36) 在本补丁之前注册, 帧同步
    # 整段 (ios15ApplyFrameFix) 都是 v23/v29/v39 注入的产物, pristine 里零命中。
    # 基线 = pristine + 按注册顺序跑完前序补丁 (见 verify.py 的正确基线)。
    ANCHOR = """        let f = sv.frame
        let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
        if !polluted {"""
    if ANCHOR not in t:
        raise RuntimeError(
            "fix_framefix_height_unconditional_v40: 未找到帧同步 polluted 判据锚点 (上游结构变了?)")

    NEW = """        let f = sv.frame
        // [V40-HEIGHT-UNCOND] 高度补齐**无条件**执行 — 见函数 docstring 的完整推导。
        //
        // v39 实测(log8): v39 把这段写在了 `var fix = f` 之后, 而它上面就是
        // `if !polluted { ... return false }` 早退。而 polluted 判据只看宽度:
        //   superview宽=100000/1844.7/651.7 → polluted=true  → 高度被补 ✅
        //   superview宽=358.0(已正常)      → polluted=false → 早退, 高度一行没跑 ❌
        // 而 log8 统计显示 4 组宽度里 3 组仍超宽, 但**修复后大部分帧会落到 358**,
        // 正好落进早退分支 —— 「宽度修好了, 高度被宽度修好挡住了」。
        //
        // 高度与宽度是**两个独立的污染维度**, 不该共用一个 polluted 门禁:
        // 宽度脏 → 修 origin.x + size.width; 高度欠 → 只修 size.height。
        // 所以提到 polluted 判据之前, 两段独立生效, 不再互相吃掉。
        //
        // v39 实测欠账 (52/52 零例外): svH=1331.0 vs needH=1807.0 欠 476.0pt(26.3%)
        var _fixH40 = f
        if let _needH40 = Optional(ios15LastNeededH), _needH40 > 1,
           _fixH40.size.height + 0.5 < _needH40 {
            _fixH40.size.height = _needH40
            sv.frame = _fixH40
        }
        // [V40-HEIGHTCHAIN] 高度链诊断 — 见函数 docstring 的「为什么加这个」。
        //
        // v39 教训: 连续两版都在猜"高度该写在哪一层", 因为日志只暴露了
        // sv0 和 frameH/needH 两个点, 中间**cell 高度、祖先链、clipsToBounds**
        // 全是黑的。本段把这三层打出来, 下一版不必再靠量化猜。
        // 代价: 每帧一次, 但只在 height 确实欠账时打, 且节流到 0.5s 一次。
        // 【注意】判定必须用**补齐之前**的 f.size.height。若用 _fixH40.size.height,
        // 上一段刚把它补到 needH, 条件恒为 false —— 诊断会永远打不出来。
        if f.size.height + 0.5 < (ios15LastNeededH > 1 ? ios15LastNeededH : 0) {
            struct _HChainLog { static var last: CFTimeInterval = 0 }
            let _now = CACurrentMediaTime()
            if _now - _HChainLog.last > 0.5 {
                _HChainLog.last = _now
                var _anc: [String] = []
                var _p: UIView? = sv
                var _d = 0
                while let _c = _p, _d < 5 {
                    _anc.append("\\(type(of: _c))(y=\\(_c.frame.origin.y) h=\\(_c.frame.size.height) clip=\\(_c.clipsToBounds))")
                    _p = _c.superview; _d += 1
                }
                NSLog("[V40-HCHAIN] svH=%.1f needH=%.1f debt=%.1f cvW=%.1f cell=%@ chain=%@",
                      f.size.height, ios15LastNeededH,
                      ios15LastNeededH - f.size.height, cvW,
                      String(describing: type(of: sv.superview)), _anc.joined(separator: " <- "))
            }
        }
        let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
        if !polluted {"""

    t = t.replace(ANCHOR, NEW, 1)

    if t.count("V40-HEIGHT-UNCOND") != 1:
        raise RuntimeError(
            f"fix_framefix_height_unconditional_v40: 标记数不符 (期望 1, 实际 {t.count('V40-HEIGHT-UNCOND')})")
    if t.count("V40-HCHAIN") != 1:
        raise RuntimeError(
            f"fix_framefix_height_unconditional_v40: 诊断段标记数不符 (期望 1, 实际 {t.count('V40-HCHAIN')})")
    # 注入点唯一性: 这段每帧对每个注册视图跑一次, 插多处 = 每帧多次写 frame。
    if t.count("_needH40 > 1") != 1:
        raise RuntimeError(
            f"fix_framefix_height_unconditional_v40: 注入点数量异常 (期望 1, 实际 {t.count('_needH40 > 1')})")
    # 【硬要求】高度补齐必须在 polluted 判据之前, 否则又会落进早退分支够不着。
    i_h = t.find("_needH40 > 1")
    i_p = t.find("let polluted = f.size.width > cvW + 1")
    if i_h == -1 or i_p == -1 or i_h > i_p:
        raise RuntimeError("fix_framefix_height_unconditional_v40: 高度补齐必须在 polluted 判据之前")
    return t


def _v41_marks(t, mark):
    """数 v41 诊断标记, 判据 = 该标记出现在 **NSLog 调用** 里。

    【踩坑记录·两连坑】
      坑1: 最初用 t.count(mark), 结果注释行 `// [V41-KVOHEIGHT] ...` 也被计入
           → "期望 1 实际 2"。
      坑2: 改成"行首 strip 后以 mark 开头", 但注入的标记本身就在注释行上
           → "期望 1 实际 0"。
    教训: 标记计数必须锚定**语义唯一**的那个形态, 不能靠"看起来像标记"的模糊匹配。
    NSLog("...") 是这段代码里唯一真正会产生日志的语句, 用它当判据最稳。
    """
    return t.count('NSLog("[' + mark + ']')


def fix_kvo_height_clamp_v41(t):
    """v41: KVO 抢帧器补高度 — 真凶是"pass 内的几何是对的, pass 之后又被SwiftUI 写回"。

    ## 先纠正 v39/v40 的诊断错误 (log9 逐行交叉比对后的结论)

    v39 与 v40 的 docstring 都断定"高度补齐代码一次都没执行过", 依据是
    `V40-HCHAIN` 触发 0 次 + 同一storageLen 的 `svH` 恒定不变。**这个结论是错的。**

    把 log9 里同一毫秒、**同一个 layoutSubviews 调用内**的两个日志点并排看:

    ```
    07:28:44.501  [LEFT-CLIP-FIX  v18] sv0=(16.0, 296.0, 100000.0, 1455.33)
    07:28:44.501  [LEFT-CLIP-DIAG2]    svFrame=(16.0, 296.0, 358.0, 2000.33)
    ```

    `_svf0` 是第 7554 行 `let _svf0 = superview?.frame ?? .zero` 在
    **layoutSubviews 开头**抓的快照; DIAG2 在**同一个函数末尾**(第 7711 行)读实时值。
    两行时间戳完全相同 → 同一个 pass 内superview 从
    `100000 x 1455.33` 变成 `358 x 2000.33`。

    **v18 + v40 在这个 pass 里确实把几何彻底修好了。**
    2000.33 == 那个 storageLen=1155 的 needH, 358 == 正确内容宽。

    分组统计五组文本, 每一组都是同样的双值分布:

    | storageLen | DIAG2(修好后) | v18 开头快照(脏值) |
    |---|---|---|
    |   327 | 358.0 x  563.7 |   764.7 x  349.3 |
    |   936 | 358.0 x 1501.7 |  1783.3 x 1073.0 |
    |   252 | 358.0 x  399.0 |   609.7 x  280.0 |
    |   664 | 358.0 x 1175.7 |  1012.3 x  818.7 |
    |  1155 | 358.0 x 2000.3 | 100000.0 x 1455.3 |

    修好后的高度**全部等于对应的 needH**, 一处不差。

    所以 `V40-HCHAIN` 打印 0 次的原因是它自己写错了位置: 它长在
    `ios15ApplyFrameFix` 里读`sv.frame`, 而那个时刻值**已经是对的**,
    条件 `f.size.height + 0.5 < needH` 自然恒为 false。
    **诊断挂在"结果已修好"的那一层, 永远打不出来。**
    (v40 引入它时的注释还特意写"判定必须用补齐之前的 f" —— 补齐是上一段做的,
    而上一段读到的就已经是修好的值了。这个假设从一开始就站不住。)

    同理, `poll=true` 50/59 也不是"污染分支一直在跑"那么乐观——
    `_svf0` 是**上一次 SwiftUI 留下的脏值**, 恰恰证明 SwiftUI 在 pass 之后又写回过。

    ## 真凶: KVO 抢帧器只修宽度, 高度完全没人管

    抢帧的最后一环是 `ios15InstallKVO()` 里那个 block-KVO
    (`sv.observe(\.frame)`), 它在 SwiftUI 写坏 frame 的**同一调用栈内**改回来。
    v29 之后它长这样:

    ```swift
    let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
    if !polluted {
        if 宽窄正常 { self.ios15LastSaneSVFrame = f }
        return                // <-- 宽度一干净就放过
    }
    var fix = f
    ...
    fix.origin.x = ...; fix.size.width = ...     // <-- 只写 x 和 width
    obj.frame = fix                // <-- 高度原样带着脏值提交
    ```

    两个洞:
      1. `polluted` 判据**只看宽度**。SwiftUI 写回 `(16, y, 358, 1455.3)`
         这种"宽度对、高度矮"的帧时, 直接 `return`, 高度没人补。
      2. 即使 `polluted == true` 走了修正分支, 也只改 x/width,
         `fix.size.height` 保持 SwiftUI 给的欠账值原样提交。

    于是 log9 那个 100000 x 1455.33 → 358 x 2000.33 的过程是:
      - KVO 抓到 100000 宽 → 修宽度 → 但高度仍是 1455.33
      - 帧同步 `ios15ApplyFrameFix` 修高度到 2000.33(pass 内, DIAG2 看到的就是它)
      - **pass 结束, SwiftUI 布局收尾再写一次 358 x 1455.33**
      - 下一次 KVO 触发时宽度已正常 → `if !polluted { return }` → **高度不补**
      - 屏幕最终渲染的是 1455.33, 而文字需要 2000.33 → **末行 545pt 被裁掉**

    这与用户症状精确对应: "字显示不出来 / 只有一半字 / 终端框结束后不接结果"。

    ## v41 修法: KVO 里把高度与宽度拆成两个独立维度

    与 v40 在 `ios15ApplyFrameFix` 里做的同构, 但改在**真正会漏的那一层**:

    1. 在 `let polluted` 之前无条件补高度(与 v40 手法一致)
    2. `polluted` 判据增加高度维度, 让"宽度正常但高度欠账"也能进修正分支
    3. 修正分支里同时写 `fix.size.height`
    4. 保留 `ios15KvoFixing` 重入保护(补高度会二次触发 KVO)

    ## 诊断: 打穿"pass 内 vs pass 后"

    v40 的诊断之所以哑, 是因为它只在一个时刻读一个值。
    v41 打**两个**:
      - `[V41-KVOPRE]` KVO 抓到的原始值(脏)
      - `[V41-KVOPOST]` 补齐后即将提交的值
      - `[V41-KVODEBT]` 若本次 pass 结束后仍欠账(SwiftUI 又写回), 记一笔并节流

    有了 KVOPRE/KVOPOST, "KVO 修好了" 与 "KVO 压根没被触发" 立刻可区分;
    KVODEBT 则直接回答"是谁在 pass 之后把高度压回去的"。

    ## 为什么这次不猜终端块的 isScrollEnabled

    上一版 v41 的隐患是"早期注册锚点落在 `if !isScrollEnabled` 内, 可能漏掉终端块"。
    本版**完全不碰注册**, 因此该隐患自动消失。
    另外 log9 已实测 `scroll=false` 19/19, 说明这些气泡文本视图确实不可滚动,
    原来的 `guard !isScrollEnabled` 从来不是拦路虎。
    """
    if "V41-KVOPOST" in t:
        return t

    # ---- 第一处: KVO 观察器内, polluted 判定之前无条件补高度 ----
    # 【踩坑记录】缩进必须逐字符对齐产物。KVO 闭包体是 12 空格,
    # 锚点失败时先 repr 打印真实缩进, 不要凭印象猜(上一版就栽在 16 vs 12 上)。
    ANCHOR = """            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
            if !polluted {
                if f.size.width > 200, f.origin.x > 0.5, f.size.width < cvW - 0.5 {
                    self.ios15LastSaneSVFrame = f
                }
                return
            }"""
    if ANCHOR not in t:
        raise RuntimeError("fix_kvo_height_clamp_v41: 未找到 KVO polluted 判据锚点 (上游结构变了?)")

    NEW = """            // [V41-KVOPRE] 抢帧器抓到的**原始**值(脏)。见函数 docstring「诊断打穿pass 内 vs pass 后」。
            struct _KvoPre { static var last: CFTimeInterval = 0 }
            let _kvoNow = CACurrentMediaTime()
            if _kvoNow - _KvoPre.last > 0.5 {
                _KvoPre.last = _kvoNow
                NSLog("[V41-KVOPRE] sv=(%.1f,%.1f,%.1f,%.1f) needH=%.1f cvW=%.1f",
                      f.origin.x, f.origin.y, f.size.width, f.size.height,
                      self.ios15LastNeededH, cvW)
            }
            // [V41-KVOHEIGHT] 高度与宽度**两个独立维度** — 见函数 docstring 的完整推导。
            //
            // v39/v40 都误判为"补齐代码没执行"。log9 逐行交叉比对证明**恰恰相反**:
            // 同一毫秒同一 layoutSubviews 内, DIAG2 读到的 superview 已经是
            // 358 x needH(修好的), 说明 v18+v40 在 pass 内把几何修好了;
            // 欠账是 **pass 结束后 SwiftUI 布局收尾又写回** 的。
            //
            // 漏水的最后一环是这个 KVO 抢帧器: 它只修 x/width, 高度从不写。
            // 于是"宽度正常 + 高度欠账"这种帧(正是 SwiftUI 收尾写回的形态)
            // 会被下面的 `if !polluted { return }` 直接放过 —— 高度永远补不上,
            // 屏幕渲染的是欠账高度, 末行被裁 → "字只剩一半/终端框不接结果"。
            //
            // 幂等 + 重入安全: 下面写 frame 时有 ios15KvoFixing 保护。
            if self.ios15LastNeededH > 1, f.size.height + 0.5 < self.ios15LastNeededH {
                var _hFix = f
                _hFix.size.height = self.ios15LastNeededH
                self.ios15KvoFixing = true
                obj.frame = _hFix
                self.ios15KvoFixing = false
                // [V41-KVOHEIGHT-HIT] 补齐真的执行了(节流 0.5s)。v39/v40 之所以
                // 判"补齐没跑"是因为诊断挂在结果已修好的那一层; 这里挂在
                // "即将写入欠账值"的那一刻, 只要欠账被补就必定打出来。
                struct _KvoHit { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                let _kh = CACurrentMediaTime()
                if _kh - _KvoHit.last > 0.5 {
                    _KvoHit.last = _kh
                    _KvoHit.n &+= 1
                    NSLog("[V41-KVOHEIGHT] fixed svH=%.1f -> needH=%.1f debt=%.1f svW=%.1f n=%u",
                          f.size.height, self.ios15LastNeededH,
                          self.ios15LastNeededH - f.size.height, f.size.width, _KvoHit.n)
                }
                // 补完立刻交棒: 下面的宽度修正必须基于新高度继续, 不能return。
                f = _hFix
            }
            // [V41-KVOPOST] 即将提交的值(应为 358 x needH)。见 docstring「诊断」。
            if self.ios15LastNeededH > 1, f.size.height + 0.5 >= self.ios15LastNeededH {
                struct _KvoPost { static var last: CFTimeInterval = 0 }
                let _kpo = CACurrentMediaTime()
                if _kpo - _KvoPost.last > 0.5 {
                    _KvoPost.last = _kpo
                    NSLog("[V41-KVOPOST] sv=(%.1f,%.1f,%.1f,%.1f) needH=%.1f",
                          f.origin.x, f.origin.y, f.size.width, f.size.height,
                          self.ios15LastNeededH)
                }
            }
            // [V41-POLLED] polluted 判据增加**高度维度**: 宽度正常但高度欠账的帧
            // 也必须进修正分支, 不能被 `if !polluted { return }` 放过。
            let _hDebt = self.ios15LastNeededH > 1 && f.size.height + 0.5 < self.ios15LastNeededH
            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt
            if !polluted {
                if f.size.width > 200, f.origin.x > 0.5, f.size.width < cvW - 0.5 {
                    self.ios15LastSaneSVFrame = f
                }
                return
            }"""
    t = t.replace(ANCHOR, NEW, 1)

    # ---- 第二处: 修正分支里同时写高度 ----
    ANCHOR2 = """            var fix = f
            if let last = self.ios15LastSaneSVFrame,
               last.size.width > 0, last.size.width <= cvW,
               last.origin.x > 0.5, last.size.width < cvW - 0.5 {
                fix.origin.x = last.origin.x
                fix.size.width = last.size.width
            } else {
                fix.origin.x = 16
                fix.size.width = cvW - 32
            }
            self.ios15KvoFixing = true
            obj.frame = fix
            self.ios15KvoFixing = false"""
    if ANCHOR2 not in t:
        raise RuntimeError("fix_kvo_height_clamp_v41: 未找到 KVO 修正分支锚点 (上游结构变了?)")

    NEW2 = """            var fix = f
            if let last = self.ios15LastSaneSVFrame,
               last.size.width > 0, last.size.width <= cvW,
               last.origin.x > 0.5, last.size.width < cvW - 0.5 {
                fix.origin.x = last.origin.x
                fix.size.width = last.size.width
            } else {
                fix.origin.x = 16
                fix.size.width = cvW - 32
            }
            // [V41-KVOFIXH] 提交前再兜一次高度。上面的 V41-KVOHEIGHT 已经在
            // polluted 之前补过一次, 这里是幂等重复, 防的是"宽度修正路径里
            // 顺带把高度带回去"。留着是因为这段是**真正写 frame** 的地方,
            // 任何绕过前面那段高度的路径都在这里被拦住。
            if self.ios15LastNeededH > 1, fix.size.height + 0.5 < self.ios15LastNeededH {
                // [V41-KVOFIXH-HIT] 兜底命中: 说明有路径绕过了前面的 V41-KVOHEIGHT,
                // 或宽度修正把高度带回去了。节流 0.5s, 正常情况下不该频繁出现。
                struct _FixH { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                let _fh = CACurrentMediaTime()
                if _fh - _FixH.last > 0.5 {
                    _FixH.last = _fh
                    _FixH.n &+= 1
                    NSLog("[V41-KVOFIXH] rescue fixH=%.1f -> needH=%.1f debt=%.1f n=%u",
                          fix.size.height, self.ios15LastNeededH,
                          self.ios15LastNeededH - fix.size.height, _FixH.n)
                }
                fix.size.height = self.ios15LastNeededH
            }
            self.ios15KvoFixing = true
            obj.frame = fix
            self.ios15KvoFixing = false"""
    t = t.replace(ANCHOR2, NEW2, 1)

    # ---- 第三处: pass 末尾的"回写侦测" — 回答"是谁在 pass 之后压回高度" ----
    #挂在 DIAG2 旁边(每 5s 一次, 与 DIAG2 同步采样, 便于逐条对照)。
    # 这里读到的 superview 高度若仍< needH, 说明 SwiftUI 在本pass 结束后又写回了。
    ANCHOR3 = """        struct _ClipDiag2 { static var lastLog: CFTimeInterval = 0 }
        let _nowD = CACurrentMediaTime()
        if _nowD - _ClipDiag2.lastLog > 5.0 {
            _ClipDiag2.lastLog = _nowD"""
    if ANCHOR3 not in t:
        raise RuntimeError("fix_kvo_height_clamp_v41: 未找到 DIAG2 锚点 (上游结构变了?)")

    NEW3 = """        // [V41-DEBT] pass 末尾回写侦测 — 见函数 docstring「诊断打穿 pass 内 vs pass 后」。
        // 与下面的 LEFT-CLIP-DIAG2 同一时刻采样、同一节流周期, 可逐条对照:
        //   DIAG2 高度 == needH  → 本pass 内修好了, 欠账是 SwiftUI 事后写回的
        //   V41-DEBT 触发        → 证实"事后写回"确实发生, 且欠账幅度是多少
        // 诊断挂在**一定执行**的位置(函数末尾无条件路径), 不像 v40 那样
        // 挂在"结果已修好"的分支里导致永远打不出来。
        if ios15LastNeededH > 1, (superview?.frame.size.height ?? 0) + 0.5 < ios15LastNeededH {
            struct _DebtLog { static var last: CFTimeInterval = 0; static var hits: UInt = 0 }
            struct _DebtSum { static var sum: CGFloat = 0; static var n: UInt = 0 }
            _DebtLog.hits &+= 1
            let _nowDebt = CACurrentMediaTime()
            if _nowDebt - _DebtLog.last > 5.0 {
                _DebtLog.last = _nowDebt
                _DebtSum.sum += ios15LastNeededH - (superview?.frame.size.height ?? 0)
                _DebtSum.n &+= 1
                NSLog("[V41-DEBT] passEnd svH=%.1f needH=%.1f debt=%.1f svW=%.1f hits=%u avgDebt=%.1f storageLen=%lu",
                      superview?.frame.size.height ?? 0, ios15LastNeededH,
                      ios15LastNeededH - (superview?.frame.size.height ?? 0),
                      superview?.frame.size.width ?? 0,
                      _DebtLog.hits,
                      _DebtSum.n > 0 ? _DebtSum.sum / CGFloat(_DebtSum.n) : CGFloat(0),
                      UInt(textStorage.length))
            }
        }
        struct _ClipDiag2 { static var lastLog: CFTimeInterval = 0 }
        let _nowD = CACurrentMediaTime()
        if _nowD - _ClipDiag2.lastLog > 5.0 {
            _ClipDiag2.lastLog = _nowD"""
    t = t.replace(ANCHOR3, NEW3, 1)

    # ---- 断言 ----
    if _v41_marks(t, "V41-KVOHEIGHT") != 1:
        raise RuntimeError(
            f"fix_kvo_height_clamp_v41: KVO 补高标记数不符 (期望 1, 实际 {_v41_marks(t, 'V41-KVOHEIGHT')})")
    if _v41_marks(t, "V41-KVOFIXH") != 1:
        raise RuntimeError(
            f"fix_kvo_height_clamp_v41: KVO 兜底标记数不符 (期望 1, 实际 {_v41_marks(t, 'V41-KVOFIXH')})")
    if _v41_marks(t, "V41-KVOPOST") != 1:
        raise RuntimeError(
            f"fix_kvo_height_clamp_v41: KVOPOST 标记数不符 (期望 1, 实际 {_v41_marks(t, 'V41-KVOPOST')})")
    if _v41_marks(t, "V41-DEBT") != 1:
        raise RuntimeError(
            f"fix_kvo_height_clamp_v41: DEBT 标记数不符 (期望 1, 实际 {_v41_marks(t, 'V41-DEBT')})")

    # 硬要求 1: 补高度必须在 polluted 判定之前
    i_h = t.index("V41-KVOHEIGHT")
    i_p = t.index("let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt")
    if i_h > i_p:
        raise RuntimeError("fix_kvo_height_clamp_v41: KVO 补高度必须在 polluted 判据之前")

    # 硬要求 2: polluted 判据必须含高度维度, 否则"宽度正常+高度欠账"仍被放过
    if "_hDebt" not in t[i_p:i_p + 120]:
        raise RuntimeError("fix_kvo_height_clamp_v41: polluted 判据缺少高度维度 _hDebt")

    # 硬要求 3: 兜底补高必须在 `obj.frame = fix` 之前
    i_fh = t.index("V41-KVOFIXH")
    i_fa = t.index("obj.frame = fix", i_fh)
    if i_fh > i_fa:
        raise RuntimeError("fix_kvo_height_clamp_v41: 兜底补高必须在 obj.frame = fix 之前")

    # 硬要求 4: V41 不得改动注册路径(上一版的思路已被证伪, 避免半吊子残留)
    if "V41-REGISTER" in t:
        raise RuntimeError("fix_kvo_height_clamp_v41: 检测到已废弃的 V41-REGISTER 残留, 请先清理")

    return t


def _v41_marks(t, mark):
    """数 v41 诊断标记, 判据 = 该标记出现在 **NSLog 调用** 里。

    【踩坑记录·两连坑】
      坑1: 最初用 t.count(mark), 结果注释行 `// [V41-KVOHEIGHT] ...` 也被计入
           → "期望 1 实际 2"。
      坑2: 改成"行首 strip 后以 mark 开头", 但注入的标记本身就在注释行上
           → "期望 1 实际 0"。
    教训: 标记计数必须锚定**语义唯一**的那个形态, 不能靠"看起来像标记"的模糊匹配。
    NSLog("...") 是这段代码里唯一真正会产生日志的语句, 用它当判据最稳。
    """
    return t.count('NSLog("[' + mark + ']')


def _v42_marks(t, mark):
    """v42 的标记计数, 判据同 v41 (锚 NSLog)。见 _v41_marks 的踩坑记录。"""
    return t.count('NSLog("[' + mark + ']')


def fix_burst_reflow_v43(t):
    """v43-B: 涌入型突增的**全表重排**节流 — 治"终端框卡一下才显示画面"。

    【与 v43-A 是两个问题】用户原话"终端框卡画面和字不显示是两个问题", 代码上
    也确实是两处独立根因, 必须分开治:
      - v43-A(V43-NETW, SelectableMarkdownView): 两条测量链宽度不同源 → 高度差
        84pt → **字被裁**。
      - 本条(MessageListLayout): 工具输出一次性涌入 → 每行都触发一次**全表**
        prepare() → **终端框卡画面**。

    log11 实证 (minis-2026-10-03 11.log, idx=14, 1.08 秒内 5 次重排):
      09:36:03.480 delta=129 est=29   → pref=159
      09:36:03.683 delta=144 est=159  → pref=303
      09:36:03.913 delta=105 est=303  → pref=408
      09:36:04.168 delta=110 est=408  → pref=518
      09:36:04.562 delta=129 est=612  → pref=742
    对应 [ScrollStall][ReflowGap] last1s coalesced re-flows=6 (全日志最高)。
    同期 [RND] table#0 CACHE UPDATE rows=4→6→7, storageLen 25→67→224→270→414→466。

    根因: shell_execute 输出**一次性涌入**(1.08 秒灌进 7 行表格 + 466 字符文本)。
    每一行都让 cell 高度跳 105~144pt, 于是 invalidationContext 末尾那个
    `invalidateLayout()` 被触发 5 次 —— 每次都是 O(items) 的全表 prepare()。

    【v43-B 第一版插错了地方, 这是本函数被重写的原因 —— 记下来别再犯】
    第一版把节流插在 `shouldInvalidateLayout` 里 `return shouldInvalidate` 之前,
    窗口内 `return false`。**那是净亏, 比原症状更糟**, 原因链条:
      shouldInvalidateLayout 返回 false
        → UIKit **根本不调用** invalidationContext
        → `heightCache[index] = newHeight`(方法开头那行) 不执行
        → prepare() 读到的是**旧高度**
        → 涌入的后半段内容被**裁掉**(正是用户在治的"字只显示一半")
    也就是说: 拦 invalidate = 拦高度落地。log11 里 `est` 恒等于上一次的 `pref`
    (29→159→303→408→518→612→742) 正是"每次都被采纳"的铁证, 第一版与日志矛盾。
    第一版注释里"heightCache 在本方法开头已经写了 newHeight"**是错的** ——
    那是 invalidationContext 的开头, 不是 shouldInvalidateLayout 的。

    【一个很容易看错的点】shouldInvalidateLayout 里紧跟的
    `if shouldInvalidate && delta > 100` 看着像判定阈值, 其实**只是日志阈值** ——
    真正的判定是上面那个 `delta > 2`。第一遍读源码时也误以为 "> 100 会拦",
    差点改错地方。日志里 5 条 INVALIDATE 全部 delta>100 只是因为日志恰好也卡在 100。

    修法: 节流**只拦全表 invalidateLayout() 那一步**, 高度照旧每次落地。
      - `heightCache[index] = newHeight` 在节流点之前, 一次都不拦 → 绝不裁字。
      - 高度虽然每次都写, 但**用它去重排全表**才是 O(items) 的开销。涌入的
        5 次写入里有 4 次落在 250ms 窗口内, 塌缩成 1 次全表 prepare(),
        终端框"一次性长出来"而不是"抖着长"。
      - 窗口极短(250ms)且只在 `delta > 100` 时生效, 真实的大幅变化
        (图片占位→加载完)最多延迟 250ms 落地。

    【为什么不动 V31-FLIPLOCK】FLIPLOCK 拦的是"翻回变小"(振荡), 本条拦的是
    **单调增长**的全表重排。两者判据不同、目标不同, 叠加会互相掩盖。
    """
    # 锚点: invalidationContext 末尾的 reflow 触发条件。必须**唯一**命中 ——
    # 这个条件串在 prepare()/applySnapshot() 等处也有形态相近的兄弟, 命中多处
    # 会把节流插到不该插的地方。
    OLD = """        if abs(delta) > 0.5, !isStreamingCell(index), !pendingFooterReflow {
            pendingFooterReflow = true"""
    NEW = """        if abs(delta) > 0.5, !isStreamingCell(index), !pendingFooterReflow {
            // [V43-BURST] 涌入型突增的**全表重排**节流 — 见函数 docstring 完整推导。
            //
            // 【关键: 高度在上一行已经落地, 这里只拦 O(items) 的全表 prepare()】
            // `heightCache[index] = newHeight` 在本 if 之前, 一次都没被拦过,
            // 所以内容永远不会被裁。拦掉的只是"拿这个新高度去重排所有 cell" ——
            // 涌入的 1.08 秒里 5 次写入, 有 4 次落在窗口内, 塌缩成 1 次全表重排。
            //
            // 【为什么不插在 shouldInvalidateLayout 里 return false —— 见 docstring】
            // 那样会让 UIKit 跳过整个 invalidationContext, 连 heightCache 写入
            // 一起跳过, 高度不落地 -> 内容被裁, 比原症状更糟。log11 里
            // `est` 恒等于上次 `pref`(29→159→303→408→518→612→742) 证明
            // 每次 invalidate 都被采纳, 拦它等于拦高度本身。
            if abs(delta) > 100 {
                let _v43Now = CACurrentMediaTime()
                let _v43Prev = Self.v43BurstAt[index] ?? 0
                if _v43Prev > 0, _v43Now - _v43Prev < 0.25 {
                    // 窗口内: 只重排**这个 cell**, 不动全表。上面的 heightCache
                    // 已经写好, 下一次真正的全表 prepare() 会用上正确高度。
                    AppLogger(category: "CellSizing").info("[V43-BURST] idx=\\(index) delta=\\(String(format: "%.0f", delta)) full-reflow suppressed — 距上次全表重排 \\(String(format: "%.3f", _v43Now - _v43Prev))s < 0.25s")
                    return ctx
                }
                Self.v43BurstAt[index] = _v43Now
                // 陈旧条目清理: 长会话里 idx 会累积到几百个, 不清会一直涨。
                if Self.v43BurstAt.count > 64 {
                    let _v43Cut = _v43Now - 2.0
                    Self.v43BurstAt = Self.v43BurstAt.filter { $0.value > _v43Cut }
                }
            }
            pendingFooterReflow = true"""
    if OLD not in t:
        raise RuntimeError("fix_burst_reflow_v43: 未找到 invalidationContext 末尾的 reflow 锚点 (上游结构变了?)")
    if t.count(OLD) != 1:
        raise RuntimeError(
            f"fix_burst_reflow_v43: reflow 锚点不唯一(命中 {t.count(OLD)} 处) —— "
            "不能盲插, 会把节流塞进 prepare()/applySnapshot() 的同名条件里")
    NEW = NEW.replace("\\n", "\n") if "\\n" in NEW else NEW
    t = t.replace(OLD, NEW, 1)

    # 静态存储声明挂在 reflow 计数器旁边(同一片存储区, 便于对照排查)。
    OLD2 = """    private static var reflowCount = 0
    private static var reflowLastFlush: CFTimeInterval = 0"""
    NEW2 = """    private static var reflowCount = 0
    private static var reflowLastFlush: CFTimeInterval = 0
    // [V43-BURST] 每 idx 最近一次**全表重排**被放行的时刻(节流窗口基准)。
    private static var v43BurstAt: [Int: CFTimeInterval] = [:]"""
    if OLD2 not in t:
        raise RuntimeError("fix_burst_reflow_v43: 未找到 reflowCount 声明锚点")
    t = t.replace(OLD2, NEW2, 1)

    # 编译防御: 静态存储必须声明, 且节流窗口与阈值必须原样出现。
    for k in ("private static var v43BurstAt: [Int: CFTimeInterval] = [:]",
              "Self.v43BurstAt[index] = _v43Now",
              "_v43Now - _v43Prev < 0.25",
              "Self.v43BurstAt = Self.v43BurstAt.filter",
              "if abs(delta) > 100 {",
              '[V43-BURST] idx='):
        if k not in t:
            raise RuntimeError(f"fix_burst_reflow_v43: 缺少关键片段 {k}")
    # 【防回退到错位】节流点必须落在 heightCache 写入**之后** —— 插到前面就等于
    # 拦高度落地, 直接裁字。这是 v43-B 第一版的错, 必须由编译防御钉死。
    i_hc = t.index("heightCache[index] = newHeight")
    i_v43 = t.index("// [V43-BURST] 涌入型突增的**全表重排**节流")
    if not i_hc < i_v43:
        raise RuntimeError(
            "fix_burst_reflow_v43: 节流点必须晚于 heightCache[index] = newHeight "
            f"(实际 hc@{i_hc} v43@{i_v43}) —— 插到前面会拦掉高度落地, 内容被裁")
    if t.count("V43-BURST") != 3:
        raise RuntimeError(
            f"fix_burst_reflow_v43: 标记数不符 (期望 3, 实际 {t.count('V43-BURST')})")
    return t


def fix_needh_latch_v42(t):
    """v42: 需求高度"闩锁" — 治KVO 触发时 needH=0 导致补齐被跳过。

    ## v41 实测结论: v41 修好了它负责的那一段

    log10 (run#102) 的判据读数:

    | 指标| v40 时代 | v41 实测|
    |---|---|---|
    | pass 结束仍欠账| 46/59| **1/94** |
    | KVO 抓到的原始宽度| 764.7 / 1783.3 / 100000 | **全部 358.0** |
    | 补齐实际执行 | 0 次 | 16 次 |
    | KVOFIXH(兜底命中) | — | 0(无绕过路径) |

    pass 末尾 `V41-DEBT` 只打出1 次(欠 42.0pt, 短文本), 而 v40 时代是 46/59 零例外。
    **v41 的 KVO 补高度是有效的。** 哨兵风暴也从 227 次降到 158 次。

    ## 但v41 暴露了它的盲点: 82% 的触发里 needH = 0

    ```
    KVOPRE 样本 94
      needH <= 1 (补齐被跳过): 77   <-- 82%
      needH >1  (补齐会执行): 17
    ```

    被卡住的 superview 高度(needH=0 时 svH 恒定不变, 多次采样同一个值):

    ```
    sv=(16.0,306.7, 358.0, 1123.7)  x4 次
    sv=(16.0, 97.0, 358.0, 1006.0)  x25 次
    sv=(16.0,191.3, 358.0,  911.3)  x8 次
    sv=(16.0, 31.7, 358.0,  252.0)  x9 次
    ```

    1123.7 卡 4 次、1006.0 卡 25 次, **恒定不变** → 永远等不到补齐, 末行持续被裁。
    用户症状「助手输出最后一段字卡住不显示」正是这个。

    ## 为什么 needH 会是 0: 测量分支的入口有三道门

    `ios15LastNeededH` 的**唯一赋值点**在 layoutSubviews 内第 7736 行
    (`ios15LastNeededH = _needH`), 它所在的 if 入口是第 7618 行:

    ```swift
    if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {
        ...
        let _needH = sizeThatFits(...).height
        ios15LastNeededH = _needH          // <-- 唯一赋值点
    }
    ```

    三道门任一不满足, `ios15LastNeededH` 就永远是初始值 0:
      1. `!isScrollEnabled`      —— log10 实测 scroll=false 18/18, 这道门**通常是通的**
      2. `findCollectionView()`  —— 从 superview 向上遍历找 NoAnimationCollectionView
      3. `rCv2.bounds.width > 1` —— SwiftUI hosting 层级未就绪时宽度可能为 0

    **KVO 抢帧器不在这三道门里** —— 它只靠 `guard let self` 和 `cvW > 1`
    (后者还有屏宽兜底), 所以**抢帧器会触发, 但测量可能从未跑过**。
    这就是 82% needH=0 的来源: KVO 正常工作, 测量链没跟上。

    ## v42 修法: 把需求高度"闩锁"住, 不让它退回 0

    两个互补的动作:

    **A. 闩锁(核心)**: 需求高度一旦算出就记住, 后续不该被重置回 0。
       测量分支的入口三道门在某些布局态下会短暂不满足, 此时不该让
       `ios15LastNeededH` 停在 0 —— 它应该**保留上一次成功测出的值**。
       于是新增 `ios15LatchedNeedH`, 并配一组键`ios15LatchLen / ios15LatchW /
       ios15LatchHash`(文本长度 / 容器宽 / 内容 hash)。

### 【设计修正】为什么不是"取 max"—— 这是个会造假空白的坑

最初的设计是"流式输出下文本只增不减, 所以取历史最大值是安全的"。
**这个假设不成立。** UITextView 会被复用去展示**更短的新内容**
(SwiftUI 滚动复用 / 消息切换 / 折叠展开), 于是:

    旧长文本的 max 高度 2000.3
      -> 复用给新短文本(真实需求 400)
      -> 短文本仍被撑到 2000.3
      -> **1600pt 大片空白**

这正是 v40 用户报过的症状, 不能为了治卡字而引入它。

所以闩锁改成**带键的精确缓存**, 不用 max:

  - 键 = (textStorage.length, textContainer.size.width, 内容hash)
  - 键命中  -> 直接复用缓存高度(不重新排版, 零开销)
  - 键不符  -> 说明文本或宽度变了, 缓存视为无效, 走 B 的自测重算并刷新键
  - 测量成功 -> **直接覆盖**缓存(而不是取 max), 因为每次成功测量都是权威值

这样"只增不减"这个脆弱前提就不需要了: 变长、变短、变宽、复用, 全部由键覆盖。

### B. 兜底自测(不依赖三道门) + 120ms 节流

当缓存键不命中时, KVO 里**自己测一次**。KVO 闭包里有 self、有 textStorage、
有 textContainer, 完全可以调 `sizeThatFits`。这条路径不经过那三道门, 于是即使
测量链没跟上也能拿到高度。宽度用 `textContainer.size.width`(已是排版实际用的宽),
与测高严格同宽。

**但自测必须节流(120ms)。** 这是推 v42 前审查出来的第二个真实风险:
键再精确, 流式输出下 `textStorage.length` 也每帧都变, 键必然次次不命中 ->
次次 `sizeThatFits`。而测量链(layoutSubviews)本来就在做同样的排版, 叠加等于
**排版开销翻倍, 正好加重用户报的"终端卡一下才显示"** —— 为了治卡字而引入卡顿,
是净亏。所以自测限频 120ms, 窗口内沿用上一个高度(流式增长下差异极小, 末行仍被
补齐), 布局收尾时键会重新命中, 精确值照常回来。

## 诊断: 这次要能区分"三道门哪一道没通"

  - `V42-GATE`      测量入口三道门的实际取值(在入口 if 之前打)
  - `V42-LATCH`     KVO 走了缓存命中分支(证明键判定是对的)
  - `V42-THROTTLE`  键不符但被节流, 沿用旧高度(证明自测在限频, 不是没跑)
  - `V42-MISS`      真正自测并刷新了键与缓存(证明测量链确实没跟上)
  - `V41-DEBT`      pass 末尾仍欠账(沿用 v41, 加闩锁后的读数)

上一版已经踩过一次坑(v39/v40 都把"诊断挂错层"当成"代码没跑")。
所以 `V42-GATE` 打在**紧贴入口 if 的前一行**, 无论进不进得去都会打。
    """
    if "V42-GATE" in t:
        return t

    # ---- A. 闩锁变量声明 (放在 ios15LastNeededH 旁边) ----
    ANCHOR_DECL = "    var ios15LastNeededH: CGFloat = 0"
    if ANCHOR_DECL not in t:
        raise RuntimeError("fix_needh_latch_v42: 未找到 ios15LastNeededH 声明锚点 (上游结构变了?)")
    NEW_DECL = """    var ios15LastNeededH: CGFloat = 0
    /// [V42-LATCH] 需求高度闩锁(带键精确缓存) —— 见函数 docstring 的完整推导。
    ///
    /// v41 实测(log10): KVO 抢帧器 94 次触发里**77 次(82%)读到的 needH 是 0**,
    /// 于是补齐条件 `needH > 1` 直接跳过, superview 卡在 1123.7 / 1006.0 等值上
    /// 恒定不变(多次采样同值), 末行持续被裁 → 用户症状「最后一段字卡住」。
    ///
    /// 根因: `ios15LastNeededH` 的唯一赋值点在 layoutSubviews 的
    /// `if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1`
    /// 内部。三道门任一不满足就永远是初始值 0; 而 KVO 抢帧器**不在这三道门里**,
    /// 于是"抢帧器正常工作, 测量链没跟上"。
    ///
    /// 【为什么不取 max —— 这是个会造假空白的坑】
    /// "流式输出下文本只增不减, 所以历史最大值就是当前需求高度" 这个假设**不成立**:
    /// UITextView 会被复用去展示**更短的新内容**(滚动复用 / 消息切换 / 折叠展开)。
    /// 那样旧长文本的 max(比如 2000.3)会把新短文本(真实需求 400)撑到 2000.3,
    /// 凭空多出 1600pt 大片空白 —— 正是 v40 用户报过的症状。不能为了治卡字引入它。
    ///
    /// 所以闩锁是**带键的精确缓存**: 键 = (文本长度, textContainer 宽, 内容 hash)。
    ///   键命中  -> 复用缓存高度, 不重新排版(零开销)
    ///   键不符  -> 缓存对当前内容无效, 走 KVO 兜底自测重算并刷新键
    ///   测量成功 -> **直接覆盖**(不是取 max), 因为每次成功测量都是权威值
    /// 于是"只增不减"这个脆弱前提不再需要: 变长/变短/变宽/复用都被键覆盖。
    var ios15LatchedNeedH: CGFloat = 0
    var ios15LatchLen: Int = 0
    var ios15LatchW: CGFloat = -1
    var ios15LatchHash: Int = 0"""
    t = t.replace(ANCHOR_DECL, NEW_DECL, 1)

    # ---- B. 测量分支入口: 打三道门的诊断 (紧贴 if 之前) ----
    ANCHOR_GATE = """            if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {
            // [IOS15-FIX-CLIP v14] 状态判定 + 修复。"""
    if ANCHOR_GATE not in t:
        raise RuntimeError("fix_needh_latch_v42: 未找到测量入口 if 锚点 (上游结构变了?)")
    NEW_GATE = """            // [V42-GATE] 测量入口三道门的实际取值 — 见函数 docstring「诊断」。
            //
            // 【为什么必须打在这里】要区分"三道门哪一道没通", 就必须打在三道门
            // **之前**。挂在里面的诊断在门关着时是哑的 —— v39/v40/v41 连续三次
            // 把诊断挂错层, 连续三次误判成"代码没跑"。这条铁律不能再犯。
            //
            // 【Swift 编译坑·v42 实测踩到】这一段**不能**写成裸 `{ ... }`。
            // 它的上一行是 v18 补丁的注释 + 一个已结束的语句, Swift 会把 `{`
            // 解析成那个表达式的 **trailing closure**, 于是块内所有裸引用都被
            // 要求显式 `self.`, 并且报 "closure expression is unused"。
            // v42 第一次推送就是这样编译失败的(8 个 error, 全部集中在这段)。
            // 修法两条同时上: (1) 全部引用加 `self.` 前缀; (2) 用 `do { }` 而不是
            // 裸 `{ }` —— `do` 块是独立语句, 不可能被吸成 trailing closure。
            do {
                struct _GateLog { static var last: CFTimeInterval = 0 }
                let _gn = CACurrentMediaTime()
                if _gn - _GateLog.last > 1.0 {
                    _GateLog.last = _gn
                    let _gCV = self.findCollectionView()
                    NSLog("[V42-GATE] scrollOff=%d cvNil=%d cvW=%.1f latched=%.1f latchLen=%d latchW=%.1f raw=%.1f storageLen=%lu",
                          self.isScrollEnabled ? 0 : 1,
                          _gCV == nil ? 1 : 0,
                          _gCV?.bounds.width ?? -1,
                          self.ios15LatchedNeedH, self.ios15LatchLen, self.ios15LatchW,
                          self.ios15LastNeededH,
                          UInt(self.textStorage.length))
                }
            }
            if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {
            // [IOS15-FIX-CLIP v14] 状态判定 + 修复。"""
    t = t.replace(ANCHOR_GATE, NEW_GATE, 1)

    # ---- C. 赋值点: 同时更新闩锁 ----
    ANCHOR_SET = "            ios15LastNeededH = _needH"
    if t.count(ANCHOR_SET) != 1:
        raise RuntimeError(
            f"fix_needh_latch_v42: needH 赋值点异常 (期望 1, 实际 {t.count(ANCHOR_SET)})")
    NEW_SET = """            ios15LastNeededH = _needH
            // [V42-LATCH-SET] 刷新闩锁的键与值。**直接覆盖, 不是取 max** ——
            // 每次成功测量都是当前内容的权威值; 取 max 会在视图复用时留下
            // 旧长文本的高度, 把新短文本撑出大片空白。详见 ios15LatchedNeedH 声明处。
            //
            // 【Swift 编译坑】这里同样可能落在 trailing closure 语境里, 所以
            // 属性引用一律写 `self.`, 与上面的 V42-GATE 保持同一防御口径。
            self.ios15LatchedNeedH = _needH
            self.ios15LatchLen = self.textStorage.length
            // [V43-LATCHW] 键里的宽度必须是**抢回后的净宽** _realW2, 不能存
            // textContainer.size.width(此刻是 SwiftUI 刚写下的脏宽 390)。
            // 两链不同源 -> 键在"抢回前/抢回后"之间反复失效 -> 退化成每次自测,
            // 而每次自测用的又是脏宽, 于是值也错。log11 证据: V42-MISS 102 次
            // vs V42-LATCH 103 次看似平衡, 但 THROTTLE 只命中 3 次, 说明
            // 绝大多数自测发生在"距上次自测 > 120ms"之后 —— 键压根没起作用。
            self.ios15LatchW = _realW2
            self.ios15LatchHash = self.textStorage.mutableString.hash"""
    t = t.replace(ANCHOR_SET, NEW_SET, 1)

    # ---- D. KVO 里: 闩锁 + 兜底自测 ----
    # 【踩坑】锚点缩进必须逐字符对齐产物(KVO 闭包体是 12 空格)。
    ANCHOR_KVO = """            if self.ios15LastNeededH > 1, f.size.height + 0.5 < self.ios15LastNeededH {
                var _hFix = f
                _hFix.size.height = self.ios15LastNeededH"""
    if ANCHOR_KVO not in t:
        raise RuntimeError("fix_needh_latch_v42: 未找到 KVO 补高度锚点 (v41 结构变了?)")
    NEW_KVO = """            // [V42-FALLBACK] 闩锁(带键缓存) + 兜底自测 —— 见函数 docstring 的完整推导。
            //
            // v41 实测: KVO 94 次触发里 77 次(82%) needH=0, 补齐被跳过,
            // superview 卡在 1123.7/1006.0 恒定不变。这里两件事:
            //   1. 键命中 -> 直接用闩锁缓存高度(零排版开销)
            //   2. 键不符 -> **KVO 自己测一次** —— 这条路径不经过
            //      `!isScrollEnabled / findCollectionView / cvW>1` 那三道门,
            //      所以测量链没跟上时也能拿到高度。宽度用 textContainer.size.width,
            //      与排版实际用的宽严格一致, 保证测高与渲染同宽。
            //
            // 【为什么不用 max】闩锁若取历史最大值, 视图复用展示更短的新文本时
            // 会把新文本撑到旧高度, 凭空造出大片空白(见声明处注释)。
            //
            // 【为什么要键】键命中才复用; 文本长度/宽度/内容任一变化都判定缓存
            // 无效并重算。条件用逗号列表 = Swift 短路求值, 长度或宽度不符时
            // 不会去算 hash, 省掉每帧的字符串哈希开销。
            //
            // 【为什么还要节流】键再精确, 流式输出下 len 也每帧都变, 必然次次
            // 不命中 -> 次次 sizeThatFits。测量链本来就在排版, 叠加会翻倍,
            // 正好加重"终端卡一下"。所以自测本身再限频 120ms。
            let _v42Len = self.textStorage.length
            let _v42Now = CACurrentMediaTime()
            // [V43-NETW] 测高**必须用抢回后的净宽**, 不能用 textContainer.size.width。
            //
            // 【v42 实测打脸·这是 v42 自己的设计错误, 不是上游问题】
            // v42 注释里写"宽度用 textContainer.size.width, 与排版实际用的宽严格一致",
            // **这句话是错的**。log11 逐条交叉比对证明同一段文本被量出**两个高度**:
            //
            //   文本长度   KVO自测(脏390)   v18实测(净358)    差
            //   len=51        79.3              79.3           0.0
            //   len=80       112.3             112.3           0.0
            //   len=336      356.7             440.7          84.0   <-- 裁掉整段
            //   len=466      782.3             821.7          39.4
            //   len=533      857.7             897.0          39.3
            //
            // 短文本在 390/358 下高度完全相同(0 差), 长文本才差出整行 —— 这精确解释
            // 了用户说的"**只有第一段卡字**": 第一段通常最长。
            //
            // 机制: SwiftUI 每帧把 textContainer 宽写成 390(全屏宽), v18 在
            // layoutSubviews 里抢回 358 并**用 358 测高**写进 frame。而 KVO 抢帧器
            // 每帧抢在 v18 之前跑, 此刻 tcW 还是脏的 390, 于是用 390 测出一个
            // **偏小**的高度, 写进 superview。两条链同文本不同宽 -> 高度不一致 ->
            // 拉锯。log11 里 `svH=252.0 -> 356.7 debt=104.7` 47 次一字不差、持续
            // 60 秒, 就是这个拉锯的稳态。
            //
            // 修法: 净宽与 v18 完全同源 —— `max(200, cvW - 32)`, 两条链同宽必然同值,
            // 拉锯从根上消失(而不是靠节流压住, 节流只是让它慢一点仍在错)。
            //
            // 为什么不能"两链都改用 tcW": v18 必须用净宽, 因为渲染排版最终是按
            // 358 做的(行碎片已被 v18 的 invalidateLayout 重排), 用 390 量出来的
            // 高度对应一个**不存在的排版**, 永远对不上真实渲染。
            let _v43NetW = max(200.0, cvW - 32)
            // 闩锁键的宽度也必须换成净宽: 键里存脏宽的话, 即使值对了也会在
            // "抢回前/抢回后"两个键之间反复失效, 退化成每次都自测(v42 的
            // V42-THROTTLE 命中 3 次 / V42-MISS 102 次就是征兆)。
            let _v42TCW = _v43NetW
            let _v43DirtyW = self.textContainer.size.width
            // [V43-WIDTH] 脏宽/净宽/两者测出的高度差 —— 一次就能判断是否同宽。
            // 同宽时 dh 应为 0.0; 若非 0 说明还有第三条测量链在用别的宽。
            struct _WLog { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
            if _v42Now - _WLog.last > 0.5 {
                _WLog.last = _v42Now
                _WLog.n &+= 1
                let _hNet = self.sizeThatFits(
                    CGSize(width: _v43NetW, height: .greatestFiniteMagnitude)).height
                let _hDirty = self.sizeThatFits(
                    CGSize(width: _v43DirtyW, height: .greatestFiniteMagnitude)).height
                NSLog("[V43-WIDTH] dirtyW=%.1f netW=%.1f hDirty=%.1f hNet=%.1f dh=%.1f len=%d n=%u",
                      _v43DirtyW, _v43NetW, _hDirty, _hNet, _hNet - _hDirty, _v42Len, _WLog.n)
            }
            // _v42SelfLast: 上次**自测**时刻(节流基准), 声明在 KVO 闭包体顶部
            // 的局部变量区, 不进实例属性 —— KVO 闭包每帧新建, 但这个值需要跨帧,
            // 所以放在闭包捕获不到的层级不行; 实际上 Swift 每次调用 observe 闭包
            // 都是同一个 block 上下文, 局部 static 才是跨帧的稳定存储。
            // 这里直接用 block 内的 static 结构体托管(见下), 避免误用局部变量。
            struct _SelfLast { static var t: CFTimeInterval = 0 }
            let _v42SelfLast = _SelfLast.t
            var _v42Need = CGFloat(0)
            if self.ios15LatchedNeedH > 1,
               self.ios15LatchLen == _v42Len,
               abs(self.ios15LatchW - _v42TCW) < 0.5,
               self.ios15LatchHash == self.textStorage.mutableString.hash {
                // [V42-LATCH] 缓存命中: 键与当前内容一致, 复用上次测出的高度。
                _v42Need = self.ios15LatchedNeedH
                struct _LatchLog { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                if _v42Now - _LatchLog.last > 0.5 {
                    _LatchLog.last = _v42Now
                    _LatchLog.n &+= 1
                    NSLog("[V42-LATCH] hit needH=%.1f len=%d tcW=%.1f n=%u",
                          _v42Need, _v42Len, _v42TCW, _LatchLog.n)
                }
            } else if _v42TCW > 1, _v42Len > 0, self.ios15LatchedNeedH > 1,
                      _v42Now - _v42SelfLast < 0.12 {
                // [V42-THROTTLE] 自测节流: 键不符但距上次自测不足 120ms。
                //
                // 【为什么必须节流】流式输出下 textStorage.length 每次都变, 键必然
                // 不命中 -> 每次 KVO 触发都要 sizeThatFits 一次。而测量链
                // (layoutSubviews) 本来就在做同样的排版, 不节流等于排版开销翻倍,
                // **会正好加重用户报的"终端卡一下才显示"**。
                //
                // 宁可短暂用一个略旧的高度(流式增长下差异极小, 末行仍被补齐),
                // 也不能每帧重排。布局收尾阶段键会重新命中, 精确值照常回来。
                _v42Need = self.ios15LatchedNeedH
                struct _ThrLog { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                if _v42Now - _ThrLog.last > 0.5 {
                    _ThrLog.last = _v42Now
                    _ThrLog.n &+= 1
                    NSLog("[V42-THROTTLE] reuse needH=%.1f len=%d sinceSelf=%.3f n=%u",
                          _v42Need, _v42Len, _v42Now - _v42SelfLast, _ThrLog.n)
                }
            } else if _v42TCW > 1, _v42Len > 0 {
                // [V42-MISS] 缓存键不命中 -> 兜底自测。绕过三道门, 测量链
                // 没跟上时也能拿到需求高度, 并顺手刷新键与缓存值。
                let _fh = self.sizeThatFits(
                    CGSize(width: _v42TCW, height: .greatestFiniteMagnitude)).height
                if _fh > 1 {
                    _v42Need = _fh
                    self.ios15LatchedNeedH = _fh
                    self.ios15LatchLen = _v42Len
                    self.ios15LatchW = _v42TCW
                    self.ios15LatchHash = self.textStorage.mutableString.hash
                    _SelfLast.t = _v42Now
                    struct _FbLog { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                    if _v42Now - _FbLog.last > 0.5 {
                        _FbLog.last = _v42Now
                        _FbLog.n &+= 1
                        NSLog("[V42-MISS] selfMeasured needH=%.1f len=%d tcW=%.1f n=%u",
                              _fh, _v42Len, _v42TCW, _FbLog.n)
                    }
                }
            }
            if _v42Need > 1 {
                self.ios15LastNeededH = _v42Need
            }
            if _v42Need > 1, f.size.height + 0.5 < _v42Need {
                var _hFix = f
                _hFix.size.height = _v42Need"""
    t = t.replace(ANCHOR_KVO, NEW_KVO, 1)

    # ---- E. 补齐内部的引用改名(v41 里读的是 ios15LastNeededH, 改用统一变量) ----
    OLD_BODY = """                self.ios15KvoFixing = true
                obj.frame = _hFix
                self.ios15KvoFixing = false
                // [V41-KVOHEIGHT-HIT] 补齐真的执行了(节流 0.5s)。v39/v40 之所以
                // 判"补齐没跑"是因为诊断挂在结果已修好的那一层; 这里挂在
                // "即将写入欠账值"的那一刻, 只要欠账被补就必定打出来。
                struct _KvoHit { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                let _kh = CACurrentMediaTime()
                if _kh - _KvoHit.last > 0.5 {
                    _KvoHit.last = _kh
                    _KvoHit.n &+= 1
                    NSLog("[V41-KVOHEIGHT] fixed svH=%.1f -> needH=%.1f debt=%.1f svW=%.1f n=%u",
                          f.size.height, self.ios15LastNeededH,
                          self.ios15LastNeededH - f.size.height, f.size.width, _KvoHit.n)
                }"""
    if OLD_BODY not in t:
        raise RuntimeError("fix_needh_latch_v42: 未找到 v41 补齐主体锚点 (v41 结构变了?)")
    NEW_BODY = OLD_BODY.replace("self.ios15LastNeededH,\n                          self.ios15LastNeededH - f.size.height",
                                "_v42Need,\n                          _v42Need - f.size.height")
    t = t.replace(OLD_BODY, NEW_BODY, 1)

    # ---- F. polluted 判据与兜底也改用统一变量 ----
    OLD_POLL = """            if self.ios15LastNeededH > 1, f.size.height + 0.5 >= self.ios15LastNeededH {
                struct _KvoPost { static var last: CFTimeInterval = 0 }
                let _kpo = CACurrentMediaTime()
                if _kpo - _KvoPost.last > 0.5 {
                    _KvoPost.last = _kpo
                    NSLog("[V41-KVOPOST] sv=(%.1f,%.1f,%.1f,%.1f) needH=%.1f",
                          f.origin.x, f.origin.y, f.size.width, f.size.height,
                          self.ios15LastNeededH)
                }
            }"""
    if OLD_POLL not in t:
        raise RuntimeError("fix_needh_latch_v42: 未找到 KVOPOST 段锚点 (v41 结构变了?)")
    NEW_POLL = OLD_POLL.replace("if self.ios15LastNeededH > 1, f.size.height + 0.5 >= self.ios15LastNeededH {",
                                "if _v42Need > 1, f.size.height + 0.5 >= _v42Need {") \
                    .replace("                          self.ios15LastNeededH)", "                          _v42Need)")
    t = t.replace(OLD_POLL, NEW_POLL, 1)

    OLD_HDEBT = "            let _hDebt = self.ios15LastNeededH > 1 && f.size.height + 0.5 < self.ios15LastNeededH\n            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt"
    if OLD_HDEBT not in t:
        raise RuntimeError("fix_needh_latch_v42: 未找到 _hDebt 判据锚点 (v41 结构变了?)")
    NEW_HDEBT = ("            let _hDebt = _v42Need > 1 && f.size.height + 0.5 < _v42Need\n"
                 "            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt")
    t = t.replace(OLD_HDEBT, NEW_HDEBT, 1)

    OLD_RESCUE = """            if self.ios15LastNeededH > 1, fix.size.height + 0.5 < self.ios15LastNeededH {"""
    if OLD_RESCUE not in t:
        raise RuntimeError("fix_needh_latch_v42: 未找到兜底补高条件锚点 (v41 结构变了?)")
    NEW_RESCUE = """            if _v42Need > 1, fix.size.height + 0.5 < _v42Need {"""
    t = t.replace(OLD_RESCUE, NEW_RESCUE, 1)

    OLD_RESCUE_LOG = """                    NSLog("[V41-KVOFIXH] rescue fixH=%.1f -> needH=%.1f debt=%.1f n=%u",
                          fix.size.height, self.ios15LastNeededH,
                          self.ios15LastNeededH - fix.size.height, _FixH.n)
                }
                fix.size.height = self.ios15LastNeededH"""
    if OLD_RESCUE_LOG not in t:
        raise RuntimeError("fix_needh_latch_v42: 未找到兜底补高主体锚点 (v41 结构变了?)")
    NEW_RESCUE_LOG = """                    NSLog("[V41-KVOFIXH] rescue fixH=%.1f -> needH=%.1f debt=%.1f n=%u",
                          fix.size.height, _v42Need,
                          _v42Need - fix.size.height, _FixH.n)
                }
                fix.size.height = _v42Need"""
    t = t.replace(OLD_RESCUE_LOG, NEW_RESCUE_LOG, 1)

    # ---- 断言 ----
    for mk, desc in [("V42-GATE", "三道门诊断"),
                     ("V42-LATCH", "闩锁命中诊断"),
                     ("V42-MISS", "兜底自测诊断")]:
        if _v42_marks(t, mk) != 1:
            raise RuntimeError(
                f"fix_needh_latch_v42: {desc}标记数不符 (期望 1, 实际 {_v42_marks(t, mk)})")

    # 硬要求 0: 闩锁**禁止**取 max。max 在视图复用展示更短文本时会造出大片空白。
    if "ios15LatchedNeedH = _needH\n" not in t or "if _needH > ios15LatchedNeedH" in t:
        raise RuntimeError(
            "fix_needh_latch_v42: 闩锁必须直接覆盖赋值, 不得取 max(会造假空白)")

    # 硬要求 0a: 自测必须节流。流式输出下 len 每帧都变, 键必然次次不命中,
    # 不节流就是每帧 sizeThatFits -> 排版开销翻倍, 正好加重"终端卡一下"。
    if "V42-THROTTLE" not in t or "_v42Now - _v42SelfLast < 0.12" not in t:
        raise RuntimeError("fix_needh_latch_v42: KVO 自测缺少 120ms 节流(会加重卡顿)")

    # 硬要求 0b: 三个键变量必须都在 KVO 里参与键判定, 否则缓存会跨内容误命中
    for k in ("ios15LatchLen", "ios15LatchW", "ios15LatchHash"):
        if t.count(k) < 4:  # 声明(带类型) + 赋值点 + KVO键判定 + KVO刷新
            raise RuntimeError(
                f"fix_needh_latch_v42: 闩锁键 {k} 参与度不足(会被跨内容误命中)")

    # 硬要求 1: 三道门诊断必须在入口 if **之前** (门关着时也要能说话)
    i_g = t.index('NSLog("[V42-GATE]')
    i_if = t.index("if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {")
    if i_g > i_if:
        raise RuntimeError("fix_needh_latch_v42: V42-GATE 必须在测量入口 if 之前")

    # 硬要求 2: 闩锁刷新必须在赋值点之后, 且三个键一起刷
    i_set = t.index("ios15LastNeededH = _needH")
    i_latch = t.index("ios15LatchedNeedH = _needH")
    if i_latch < i_set:
        raise RuntimeError("fix_needh_latch_v42: 闩锁刷新必须在 needH 赋值之后")
    # 【必须带 self. 前缀】v42 第一次推送编译失败教训: 该赋值点与 V42-GATE 块
    # 处在同一段落, Swift 可能把后面的 `{` 吸成 trailing closure, 于是裸引用
    # 会被要求显式 self.。所以注入时就一律写 self.，断言也跟着锚 self. 版本。
    #
    # 【v43 两代兼容】键里的宽度两代不同, 都必须带 self.:
    #   v42 世代: self.ios15LatchW = self.textContainer.size.width  (脏宽, 会造假)
    #   v43 世代: self.ios15LatchW = _realW2                        (抢回净宽, 正确)
    # 判据要两代都放行 —— 不能因为 v43 改了写法就把 v42 判据删掉, 那等于让
    # "键刷新"这件事彻底无人看守; 但也不能只认 v42, 否则 v43 永远跑不过。
    for k in ("self.ios15LatchLen = self.textStorage.length",
              "self.ios15LatchHash = self.textStorage.mutableString.hash"):
        if k not in t:
            raise RuntimeError(f"fix_needh_latch_v42: 赋值点缺少键刷新 {k}")
    _v43_w = "self.ios15LatchW = _realW2"
    _v42_w = "self.ios15LatchW = self.textContainer.size.width"
    if _v43_w not in t and _v42_w not in t:
        raise RuntimeError(
            "fix_needh_latch_v42: 赋值点缺少键刷新 (v43 净宽 / v42 脏宽 两种写法都不存在)")

    # 【编译防御】V42-GATE 必须用 do { } 而不是裸 { }。裸块会被 Swift 吸成
    # 上一个表达式的 trailing closure -> 8 个编译错误(closure expression is
    # unused + 全量要求显式 self.)。这是 v42 首次推送的真实失败原因。
    i_do = t.index("// [V42-GATE] 测量入口三道门的实际取值")
    seg_gate = t[i_do:t.index("if !isScrollEnabled, let rCv2 = findCollectionView()", i_do)]
    if chr(10) + "            do {" not in seg_gate:
        raise RuntimeError(
            "fix_needh_latch_v42: V42-GATE 块必须用 do { }(裸 { } 会被吸成 trailing closure 编译失败)")
    if "self.findCollectionView()" not in seg_gate:
        raise RuntimeError(
            "fix_needh_latch_v42: V42-GATE 块内必须用 self.findCollectionView()(显式捕获)")

    # 硬要求 3: KVO 补齐必须用统一变量 _v42Need, 不能直接读 ios15LastNeededH
    i_kvo = t.index("// [V42-FALLBACK] 闩锁(带键缓存) + 兜底自测")
    i_asg = t.index(chr(10) + "                _hFix.size.height = _v42Need")
    i_poll = t.index("let _hDebt = _v42Need > 1")
    if not (i_kvo < i_asg < i_poll):
        raise RuntimeError("fix_needh_latch_v42: KVO 补齐/polluted 判据必须统一用 _v42Need")

    # 硬要求 4: 闩锁声明必须与 ios15LastNeededH 同处(便于阅读与维护)
    if t.count("var ios15LatchedNeedH: CGFloat = 0") != 1:
        raise RuntimeError("fix_needh_latch_v42: 闩锁变量声明数异常")

    return t


def fix_diag_textframe_v44(t):
    """v44: **纯诊断**, 不改任何行为 — 定位"补高补错了对象"。

    ## 为什么这一版只加诊断不修

    v43 装机实测(minis-2026-10-03 12.log, 18:05:34~ 18:17:27)推翻了 v43-A 的假设。
    v43-A 的设计前提是"净宽量出的高度一定 >= 脏宽量出的", 因为脏宽 390 更宽、
    行更少、更矮。**实测符号会翻转**:

    | 时刻 | len | hDirty(390) | hNet(358) | dh | 方向 |
    |---|---|---|---|---|---|
    | 18:06:12 | 1583 | 1960.7 | 1769.3 | **-191.3** | 净宽**更矮** |
    | 18:17:11 | 828 | 1384.3 | 1474.0 | **+89.7** | 净宽**更高** |

    143 条 `V43-WIDTH` 里 29 条 dh≠ 0(114 条为 0)。**如果两条链真同源, dh 恒为 0。**
    符号翻转说明还有第三条测量链/排版状态在参与, 而它既不是 v42 自测也不是 v18。
    在没看见它之前改任何行为都是第三次盲猜(v41/v42/v43 各猜错一次)。

    ## 日志里的两个硬事实

    **1. 补高循环永不收敛**(v43 依然如此, v41 就有的老问题):

    ```
    18:17:11.246 V41-KVOPRE  sv=(16,247.3,358.0,1026.3) needH=0.0
    18:17:11.252 V41-KVOHEIGHT fixed svH=1026.3 -> needH=1474.0 debt=447.7
    18:17:11.256 LEFT-CLIP-FIX v18 sv0=(16,247.3,100000.0,1026.3) frameH=1474.0
    18:17:12.075 V41-KVOPRE  sv=(16,247.3,358.0,1026.3) needH=0.0   <- 又变回去
    ... 同一个 447.7 循环到 n=138
    ```

    `V41-KVOPRE` 抓的 `obj` 是**superview**(scroll 容器), 每 0.5s 补一次, 补完
    SwiftUI 收尾又写回 1026.3, 于是无限循环。`debt` 分布极度集中:
    447.7 / 425.0 各 12~10 次、**156.3 达 84 次** —— 全部是固定值, 一次没收敛。

    **2. 补的是superview, 渲染文字的是 UITextView**。这是本条诊断要回答的核心问题:
    superview 补到 1474 了, 文字照样被裁, 那就说明**欠账不在 superview 上**。

    ## 三个假设, 一条日志一次打完

    三个候选根因都发生在同一 KVO 闭包、同一时刻, 所以在补高段之后打**一条**
    日志就能全部区分, 不需要三个版本:

    | 假设 | 判据 | 读法 |
    |---|---|---|
    | A. textView 自己矮了没人补 | `tvH` vs `needH` | `tvH < needH - 0.5` → A 成立 |
    | B. 补高被 `ios15KvoFixing` 重入挡掉 | `svAfter`(补后立刻回读) | `svAfter < needH - 0.5` → B 成立 |
    | C. 附件高度没算进 needH | `usedH`(layoutManager) vs `needH` | `usedH < needH - 5` → C 成立(needH 虚高) |

    `svAfter` 是**补完立刻回读 obj.frame.height** —— v41 补高时从不回读,
    所以"补没补上"这件事至今没有任何日志能回答。这是最关键的新增判据。

    `usedH` 用 `layoutManager.usedRect(for: self.textContainer).height`:
    TextKit 眼里真正占了多少行。表格/代码块是 NSTextAttachment, 如果它们的
    attachmentBounds 没被计入排版, `needH` 就会比 usedH 大一截 —— 那就是 C。

    ## 为什么必须用 do { } 而不是裸 { }

    v42 首次推送的真实失败: 裸块被 Swift 吸成上一个表达式的 trailing closure,
    报"closure expression is unused"并连锁要求显式 self.。V42-GATE 已经被迫
    改成 do { }踩过这个坑, 这里直接用 do { }。

    ## 节流

    0.5s 一次, 与 V41-KVOPRE / V43-WIDTH 同周期, 三条日志可逐条并列对照 ——
    同一节流周期内它们看到的是同一帧。
    """
    ANCHOR = """                // 补完立刻交棒: 下面的宽度修正必须基于新高度继续, 不能return。
                f = _hFix
            }"""
    if ANCHOR not in t:
        raise RuntimeError(
            "fix_diag_textframe_v44: 未找到补高段末尾锚点 `f = _hFix`(v41/v42 结构变了?)")
    if t.count(ANCHOR) != 1:
        raise RuntimeError(
            f"fix_diag_textframe_v44: 补高锚点不唯一(命中 {t.count(ANCHOR)} 处) —— "
            "KVO 闭包外有形态相近的兄弟, 盲插会打到一个根本不补高的位置")

    NEW = """                // 补完立刻交棒: 下面的宽度修正必须基于新高度继续, 不能return。
                f = _hFix
            }
            // [V44-TEXTFRAME] 见函数 docstring: v41/v42/v43 三轮都在猜"高度够不够",
            // 这一条把三个候选根因一次打完, 不改任何行为。
            //
            // tvH     —— **渲染文字的 UITextView 自己**有多高。superview 补到
            //            needH 而 tvH 仍矮, 那欠账根本不在 superview 上(假设 A)。
            // svAfter —— 补高**立刻回读**。v41 补完从不回读, 所以"补上了没有"
            //            至今无日志可答(假设 B: 被 ios15KvoFixing 重入挡掉)。
            // usedH   —— TextKit 眼里真正占用的行高。表格/代码块是 attachment,
            //            若其 bounds 没进排版, needH 会虚高(假设 C)。
            do {
                struct _TfdLog { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                let _tfdNow = CACurrentMediaTime()
                if _tfdNow - _TfdLog.last > 0.5 {
                    _TfdLog.last = _tfdNow
                    _TfdLog.n &+= 1
                    let _tfdTvH = self.frame.height
                    let _tfdSvAfter = obj.frame.height
                    let _tfdUsed = self.layoutManager.usedRect(
                        for: self.textContainer).height
                    NSLog("[V44-TEXTFRAME] tvH=%.1f svAfter=%.1f usedH=%.1f needH=%.1f tvW=%.1f svW=%.1f tcW=%.1f len=%d n=%u",
                          _tfdTvH, _tfdSvAfter, _tfdUsed, _v42Need,
                          self.frame.size.width, obj.frame.size.width,
                          self.textContainer.size.width, _v42Len, _TfdLog.n)
                }
            }"""
    t = t.replace(ANCHOR, NEW, 1)
    verify_textframe_v44(t)
    return t


def fix_tvh_debt_v45(t):
    """v45: 补高**补到画字的那个视图上** — 治"外层留空白/字卡一半"。

    ## v44 的归因结论(log13, 53 条 V44-TEXTFRAME, 零例外)

    v44 是纯诊断版, 装机后一条日志把三个假设一次打完, 结果 44/53 命中
    同一个组合, 剩下 9 条是正常短消息:

    | 组合 | 次数 | 含义 |
    |---|---|---|
    | A-C | 44 | textView 自己矮 + attachment 虚高 |
    | --C | 9 | 正常 |

    **假设 B(补高被 `ios15KvoFixing` 重入挡掉)彻底排除**:
    `svAfter == needH` 在 53 条里**全部成立**(1136.3/1136.3、538.0/538.0、
    49.0/49.0 …)。补高从来都成功了, 从来没被挡掉过。

    ## 真凶: 补的对象错了 —— 补了 superview, 文字活在 UITextView 里

    决定性的一行:

    ```
    tvH=912.7  svAfter=1136.3  needH=1136.3  tvW=390.0  svW=358.0  len=629
    ↑画字的UITextView 自己矮了 223.6pt
    ```

    v41~v44 四版都在补 `sv.frame`(superview/scroll容器), 而**画字的是
    `self.frame`**(UITextView 自己)。superview 补到 1136.3 了, 里面那个
    UITextView 只有 912.7 —— 多出来的 223.6pt 是**空壳**, 文字被自己
    的 bounds 裁断。

    这就是用户报的"上面 Minis 下面一小片空白 + 字还是卡一半"的**完整机制**:
    外层被撑高, 内层矮一截, 空出来的地方没有文字, 有文字的地方被裁。

    ## 欠账额的结构证明"不是拉锯, 是两个来源各写一次"

    44 条样本逐条算:

    ```
    needH - tvH = (usedH - tvH) + (needH - usedH)
    ```

    `usedH - tvH` **恒为负**(-8.0 ~ -44.7, 均值 -34.5), 从没转正过。
    如果 tvH 是被随机拉回來的拉锯, 这个差必然有正有负。恒负说明:
    UITextView 的高度始终**系统性地**比 TextKit 实际占用矮一截, 而外层
    欠的账正好等于"自己矮的量 + 一份固定差额"。

    44 条欠账样本的 `needH - tvH` 分布高度集中:
    223.6(30 次)/ 224.0(3)/ 112.0(16)/ 45.0 / 22.3 —— 全是固定值。

    ## 顺带确认: 脏宽是**共犯**, 不是主犯

    ```
    44 条欠账样本: tvW=390/tcW=390 -> 42 条, tvW=358/tcW=358 -> 2 条
     9 条正常样本: tvW=358/tcW=358 -> 9 条(100%)
    ```

    欠账几乎全部发生在 `tcW=390`(脏宽没抢回)时, 正常样本 100% 是 358。
    但**本版不动宽度** —— 宽度抢回在 v13/v34 反复引起过闪屏/整体缩小,
    风险面独立, 留待单独一版。这一版只治 tvH, 让 A 主因先落地看效果。

    ## 修法: 在 KVO 补高路径里, 把 needH 同时写进 self.frame

    位置选在 v41 补高段之后、V41-KVOPOST 之前 —— 那里 `_v42Need` 刚算完、
    `f` 已是补过 sv高度的新帧, 是**同一条KVO 闭包内**唯一能同时拿到
    `needH` 与 `self` 的地方, 不需要跨函数传递。

    写 `self.frame` 有个前提必须守住: **只动高度, 绝不碰 origin 和宽度**。
    宽度是 v18/v34 那一族(经`ios15LastSaneSVFrame` + KVO 宽度修正)精心
    维护的, 在这里碰它等于绕过那套状态机。判据用 `frame.size.height`,
    写入也只改 `size.height` —— 语义上"给这个视图更多竖直空间", 不越界。

    ## 为什么不写"tvH 补到 max(needH, usedH)"

    因为 A 与 C 都会在这里被一并缓解: needH 已经是本闭包按**抢回后的净宽**
    算出的权威需求高(v43-A 起`_v42TCW = max(200, cvW-32)`), 补到它即
    包含 C 需要的空间。C 的 `needH-usedH` 差额(30~268pt)会被这一条覆盖掉,
    不需要额外为 C 写任何代码。若装机后 C 仍显形, 再单独收口。

    ## 与 v41 的关系(幂等, 不是叠加)

    v41 补的是 `obj.frame`(superview), v45 补的是 `self.frame`。
    两者目标不同层, 互不覆盖 —— v41 之后 `f` 已是新高度, v45 在它之上
    再补 self。连续多帧执行时 `tvH >= needH` 自然让本段条件转 false,
    不存在反复写入。日志按 0.5s 节流, 与 v44 同周期便于并列对照。
    """
    ANCHOR = """            // [V44-TEXTFRAME] 见函数 docstring: v41/v42/v43 三轮都在猜"高度够不够",
            // 这一条把三个候选根因一次打完, 不改任何行为。
            //
            // tvH     —— **渲染文字的 UITextView 自己**有多高。superview 补到
            //            needH 而 tvH 仍矮, 那欠账根本不在 superview 上(假设 A)。"""
    if ANCHOR not in t:
        raise RuntimeError(
            "fix_tvh_debt_v45: 未找到 V44 诊断段锚点(V44 没注入? 登记顺序错了?)")
    if t.count(ANCHOR) != 1:
        raise RuntimeError(
            f"fix_tvh_debt_v45: V44 段锚点不唯一(命中 {t.count(ANCHOR)} 处)")

    NEW = """            // [V45-TVHFIX] 补高**补到画字的那个视图上** — 见函数 docstring。
            //
            // v44 归因(log13, 53 条零例外): 假设 A 命中 44/53, 假设 B 被彻底
            // 排除(svAfter == needH 全成立)。真凶是**补错了对象**:
            // v41~v44 一路补的都是 superview(sv.frame), 而画字的是
            // UITextView 自己(self.frame)。实测 tvH=912.7 而 svAfter=needH=
            // 1136.3 —— 外层补到位了, 内层矮 223.6pt, 多出来的是空壳,
            // 有字的地方被自己的 bounds 裁掉。这就是"下面一小片空白 + 字卡一半"。
            //
            // 【只动高度, 绝不碰 origin/width】宽度由 v18/v34 那一族经
            // ios15LastSaneSVFrame 精心维护, 在这里碰它等于绕过那套状态机
            // (v13/v34 都因抢宽引起过闪屏/整体缩小)。所以判据与写入都只涉
            // size.height, 语义严格限定为"给这个视图更多竖直空间"。
            //
            // needH 是本闭包按抢回后净宽算出的权威需求高(v43-A 起
            // _v42TCW = max(200, cvW-32)), 补到它即同时覆盖 v44 假设 C 的
            // 虚高差额, C 无需单独代码。连续多帧时 tvH >= needH 让条件自然
            // 转 false, 幂等不反复写。
            do {
                if _v42Need > 1, self.frame.size.height + 0.5 < _v42Need {
                    var _tvf = self.frame
                    _tvf.size.height = _v42Need
                    self.frame = _tvf
                    struct _TvhLog { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                    let _tvhNow = CACurrentMediaTime()
                    if _tvhNow - _TvhLog.last > 0.5 {
                        _TvhLog.last = _tvhNow
                        _TvhLog.n &+= 1
                        NSLog("[V45-TVHFIX] tvH %.1f -> needH %.1f debt %.1f tvW %.1f svH %.1f len %d n %u",
                              f.size.height, _v42Need, _v42Need - f.size.height,
                              self.frame.size.width, obj.frame.size.height,
                              _v42Len, _TvhLog.n)
                    }
                }
            }
""" + ANCHOR
    t = t.replace(ANCHOR, NEW, 1)
    verify_tvh_debt_v45(t)
    return t


def fix_diag_attachment_v46(t):
    """v46: 表格附件高度**没进排版**的归因 — 治"终端框盖住上面的字/定时任务字闪烁卡住"。

    ## v45 验收结论(log14/log15, 装机实测)

    v45 把欠账补到画字的那个视图上, **完全成功**:

    - log14: `V45-TVHFIX debt=0.0` 71/71, `needH - tvH == 0.0` 74/74
    - log15: `V45-TVHFIX debt` 仍全 0.0, 跨帧 tvH 稳定(23 个 len 里只有
      len=49 有多值, 且是流式正常重测 182->236, 不是抖动)

    假设 A(UITextView 自己矮)彻底关闭。但用户反馈**两个新现象仍在**:

    1. 终端框(表格)盖住上面的字; 定时任务那几个字一下有一下没有、卡住
    2. 内容下方还有一小片空白

    ## log15 的硬证据: 现象 1 = v44 假设 C 真实命中

    ```
    [V44-TEXTFRAME] tvH=304.3 svAfter=376.3 usedH=114.3 needH=304.3 len=29
    [invalidateCell][SKIP-DEDUPE] lastH=304.3 tableGen=4 — fingerprint match
    [table#0 CACHE UPDATE] rows=7 cols=2          <- 表格内容变了
    [UAV][SKIP-DEDUPE] tableGen=6                <- 代数变了但仍被去重跳过
    ```

    三个数字打架: `needH=304.3`(UITextView 的高度) / `usedH=114.3`
    (TextKit 真实占用) / `svAfter=376.3`(superview 反而更高)。
    **`usedH` 只有 `needH` 的 1/3** —— 表格那个 7x2 附件占的 ~190pt
    完全没进 `usedRect`。量化: 111 条 V44 里 **71 条 `needH-usedH > 8.5`**
    (中位 55.6pt, 最大 190.0pt), 另 40 条 `<= 8.5`(纯文字, 附件高度为 0,
    差额就是 textContainerInset 的 8.1~8.3)。**差额与"有没有附件"完全同构。**

    而"定时任务字一下有一下没有"是 len=49 那组: 唯一一组
    **`usedH` 恒为 99.9 而 `needH` 在 182<->236 之间跳**的样本 ——
    附件高度在两种取值间反复切换, 文字跟着忽隐忽现。

    ## 四个候选根因(源码逐个定位, 装机一次打完)

    `TableAttachment` 的高度要走完这条链才能进排版:

    ```
    update(rows:) -> contentGeneration++ / needsLayoutInvalidation
                  -> computeLayout(for: w) -> cachedLayout
                  -> attachmentBounds(...) -> CGRect.height
                  -> TextKit typesetter -> usedRect
    ```

    链上有**四个**能造成"attachmentBounds 返回了新高度但 usedRect 没变"的点:

    - **D1 缓存未失效**: `computeLayout` 开头 `if let cached = cachedLayout,
      cached.width == width { return cached }` —— 表格 `update()` 若判定
      `structureChanged || contentGrew` 为 false(只是某个单元格内容变了变短,
      或列数比较维度不对), `cachedLayout` 就留着**旧 rowHeights**,
      `attachmentBounds` 返回旧高度。**这是最可疑的一个。**
    - **D2 探针宽度**: `isOversizedProbe`(lineFrag.width >= 100_000)时高度
      按 `containerRealWidth ?? lastRealWidth ?? narrowestRealWidth` 算, 而
      **返回的 width 仍是 clampedWidth**。SwiftUI 探针拿到的 cell 尺寸与
      真实宽度不同源。
    - **D3 失效信号没被消费**: `needsLayoutInvalidation` 置位后, 若
      `updateUIView` 那条 invalidate 路径没跑到, layoutManager 根本不知道
      附件 bounds 变了。
    - **D4 容器被短路**: `NSTextContainerSetSizeGuard` 把同 tick 重复
      `setSize:` 全部丢弃(log15: 累计 3617 次短路, 高度出现 2000.0 /
      1057.3 / 18.7 等一串与真实需求无关的值)。容器尺寸不更新 ->
      TextKit 不重排 -> `usedRect` 冻结。

    一条日志同时打 D1/D2/D3/D4, 装机后用数据定 v47 修法。**不改任何行为。**

    ## 为什么不能盲修

    这四点修法互相冲突: D1 要放宽缓存失效判据(但那正是 HangFix 2026-05-14
    为了治"流式每 token 全量重测导致主线程卡死数秒"而故意保留的), D4 要
    放宽 guard(而 guard 是治 `fillLayoutHole` 11918ms 主线程卡死的)。
    **两个都是拿性能换正确性, 盲修任何一处都可能把卡死放回来。** 所以先量。

    ## 判据设计(每条都要能证伪一个具体修法)

    - `attWant`  = 直接调 `attachmentBounds` 拿它**现在**会返回的高度
      (用当前 tcW 构造 lineFrag) —— 若它已经等于 needH, 说明 attachmentBounds
      侧是对的, 问题在下游(D3/D4); 若它还是旧的, 根因就是 D1/D2。
    - `attCached` = `cachedLayout?.totalHeight` —— 与 attWant 对比, 差值
      就是"缓存扣了多少"。
    - `attGen`    = `contentGeneration`, `attNVI` = `needsLayoutInvalidation`
      —— 若 attWant 已是新高度而 usedH 仍旧, 且 attNVI 为 true, 则 D3 成立。
    - `attN`      = textStorage 里附件的个数(0 则本条无意义, 跳过)。

    ## 与 v44/v45 的关系(纯并列, 不覆盖)

    v44 打几何(tvH/svAfter/usedH/needH), v45 补几何, **v46 一行几何都不碰**
    —— 它只读 attachment 与 cachedLayout 的内部状态。挂在 v45 之后,
    同一闭包同一帧, 便于三者并列对照。
    """
    # 锚点 = V44 段头。v45 把自己插在 V44 段**之前**(顺序: v42 -> v44 注入 ->
    # v45 在 V44 段前插 -> v46 在 V44 段前、v45 之后插), 所以锚点取 V44 段头
    # 即可让 v46 落在 v45 之后。
    # 【踩坑记录】第一版锚点写成 "v45 段尾的 }" + V44 段头, 结果替换后
    # 全文花括号净 +1 编译失败 —— 那个前导 `}` 是**闭合 v45 的 do 块**的,
    # v46 段自带完整闭合(do{...}), 把这个 `}` 一起替换掉就没人闭 v45 的块了。
    # 锚点只取 V44 段头, 不碰前一行。
    ANCHOR = _V44HEAD = """            // [V44-TEXTFRAME] 见函数 docstring: v41/v42/v43 三轮都在猜"高度够不够",\n"""
    if ANCHOR not in t:
        raise RuntimeError(
            "fix_diag_attachment_v46: 未找到 V44 诊断段锚点(v44/v45 没注入? 登记顺序错了?)")
    if t.count(ANCHOR) != 1:
        raise RuntimeError(
            f"fix_diag_attachment_v46: V44 段锚点不唯一(命中 {t.count(ANCHOR)} 处)")

    # 只读访问器: cachedLayout 是 private, 诊断段在 SelectableMarkdownTextView 里,
    # 不加这个就读不到 —— D1(缓存扣了多少高度)就永远无法验证。
    # 必须是只读 getter, 没有任何 setter, 结构上不可能写。
    ACCESSOR = """    /// [V46-ATTACH] 只读访问器: 把 private 的 cachedLayout 的总高暴露给诊断段。
    /// 纯诊断用, **没有 setter** —— 结构上不可能从这里改缓存。
    var attV46CachedTotalH: CGFloat { cachedLayout?.totalHeight ?? -1 }
    /// [V46-ATTACH] 缓存自算宽度(0 = 从未算过)。用于判断缓存是不是在别的
    /// 宽度下留下的陈旧值(D1 的另一半)。
    var attV46CachedWidth: CGFloat { cachedLayout?.width ?? 0 }

""" + """    /// Discard the cached layout so the next `computeLayout` / `attachmentBounds`
    /// recomputes column widths and row heights for whatever width is current."""
    _acc_anchor = """    /// Discard the cached layout so the next `computeLayout` / `attachmentBounds`
    /// recomputes column widths and row heights for whatever width is current."""
    if _acc_anchor not in t:
        raise RuntimeError(
            "fix_diag_attachment_v46: 未找到 cachedLayout 邻近锚点(TableAttachment 结构变了?)")
    if t.count(_acc_anchor) != 1:
        raise RuntimeError(
            f"fix_diag_attachment_v46: cachedLayout 锚点不唯一(命中 {t.count(_acc_anchor)} 处)")
    t = t.replace(_acc_anchor, ACCESSOR, 1)

    _V44HEAD = ANCHOR
    NEW = """            // [V46-ATTACH] 表格附件高度**没进排版**的归因 — 见函数 docstring。
            //
            // log15 硬证据: needH=304.3 而 usedH=114.3(差 190pt), 表格 7x2
            // 附件占的高度完全不在 usedRect 里; 111 条里 71 条 needH-usedH>8.5,
            // 差额与"有没有附件"完全同构。这是 v44 假设 C 的首次真实命中。
            //
            // **纯诊断, 一行几何都不碰。** 链路上有四个可疑点(D1 缓存未失效 /
            // D2 探针宽度 / D3 失效信号未消费 / D4 容器被 guard 短路), 修法
            // 互相冲突 —— D1/D4 都是拿性能换正确性的历史 trade-off, 盲修任一
            // 处都可能把主线程卡死放回来。先量, 再动。
            do {
                var _v46AttN = 0
                var _v46AttWant = CGFloat(0)
                var _v46AttCached = CGFloat(-1)
                var _v46AttCachedW = CGFloat(-1)
                var _v46AttGen = UInt64(0)
                var _v46AttNVI = false
                // 【踩坑记录(run#37124793234)】第一版写的是
                // `self.textStorage?.enumerateAttributes(...)` —— **API 名错了**。
                // NSAttributedString 只有 `enumerateAttribute(_:in:options:using:)`
                // (单数), 没有复数形式, 于是 run#37124793234 在"编译 App"这一步
                // 失败 —— 注入与断言全绿(断言只看子串存在性, 抓不到 API 名错误),
                // 编译期才炸。修法: 照源码既有写法(traitCollectionDidChange /
                // needsAttachmentRecovery 两处都是这个形式)改成
                // `textStorage as? NSTextStorage` + `enumerateAttribute`。
                if let _v46St = textStorage as? NSTextStorage {
                    _v46St.enumerateAttribute(
                        .attachment,
                        in: NSRange(location: 0, length: _v46St.length),
                        options: []) { _v, _, _ in
                        guard let _a = _v as? NSTextAttachment else { return }
                        _v46AttN += 1
                        if let _t = _a as? TableAttachment {
                            _v46AttGen &+= _t.contentGeneration
                            if _v46AttNVI == false, _t.needsLayoutInvalidation { _v46AttNVI = true }
                            // D1: 缓存里扣了多少高度
                            if _v46AttCached < 0 { _v46AttCached = 0 }
                            // D1/D2: attachmentBounds 现在**会**返回多高 —— 用当前
                            // tcW 构造 lineFrag, 与 usedH/needH 并列对照。
                            let _v46W = self.textContainer.size.width
                            let _v46Frag = CGRect(x: 0, y: 0, width: _v46W, height: .greatestFiniteMagnitude)
                            let _v46R = _t.attachmentBounds(
                                for: self.textContainer, proposedLineFragment: _v46Frag,
                                glyphPosition: .zero, characterIndex: 0)
                            _v46AttWant += _v46R.height
                            _v46AttCached = _t.attV46CachedTotalH
                            if _v46AttCachedW < 0 { _v46AttCachedW = _t.attV46CachedWidth }
                        }
                    }
                }
                if _v46AttN > 0 {
                    struct _V46Log { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                    let _v46Now = CACurrentMediaTime()
                    if _v46Now - _V46Log.last > 0.5 {
                        _V46Log.last = _v46Now
                        _V46Log.n &+= 1
                        let _v46Lm = self.layoutManager
                        let _v46Used = _v46Lm.usedRect(for: self.textContainer).height
                        NSLog("[V46-ATTACH] attN=%d attWant=%.1f attCached=%.1f cachedW=%.1f attGen=%llu attNVI=%d usedH=%.1f needH=%.1f tcW=%.1f tcH=%.1f nGlyph=%d len=%d n=%u",
                              _v46AttN, _v46AttWant, _v46AttCached, _v46AttCachedW, _v46AttGen,
                              _v46AttNVI ? 1 : 0, _v46Used, _v42Need,
                              self.textContainer.size.width, self.textContainer.size.height,
                              _v46Lm.numberOfGlyphs, _v42Len, _V46Log.n)
                    }
                }
            }
""" + _V44HEAD
    t = t.replace(ANCHOR, NEW, 1)
    verify_attachment_v46(t)
    return t


def verify_attachment_v46(t):
    """校验 v46 附件诊断段 —— 独立成函数, 理由同 verify_textframe_v44。

    【判据顺序】具体 -> 宽泛, 标记计数放最后当总兜底(v44 实跑踩出来的:
    标记计数放最前会把其他判据全部稀释掉, 那些防御形同虚设)。

    【★纯诊断纪律】与 v44 同一条纪律, 但这里判据更重: v46 必须**只读不写**。
    四个候选根因(D1/D2/D3/D4)互相冲突, 任何一个写操作都会让装机数据
    无法归因 —— 写了 attachmentBounds 之外的任何东西, 就分不清"修好了"
    还是"被诊断改坏了"。所以硬禁: 一切对实例状态的赋值、一切 frame/
    bounds/size 写入、invalidate* 调用、缓存写入。
    """
    # 0. 整段缺失。必须排在字段检查之前(否则报"缺字段"方向误导)。
    _i0 = t.find("// [V46-ATTACH] 表格附件高度")
    if _i0 < 0:
        raise RuntimeError("verify_attachment_v46: 诊断段整段缺失")
    # 0.5 只读访问器必须一并注入 —— 没有它就读不到 cachedLayout(它是 private),
    #     D1(缓存扣了多少)就永远无法验证。
    if "var attV46CachedTotalH" not in t:
        raise RuntimeError("verify_attachment_v46: 缺少 TableAttachment 只读访问器 attV46CachedTotalH")
    # 1. 六个判据字段一个都不能少, 少一个就有一个候选根因永远无法验证。
    for k in ('NSLog("[V46-ATTACH] attN=%d attWant=%.1f attCached=%.1f cachedW=%.1f attGen=%llu',
              "attNVI=%d usedH=%.1f needH=%.1f tcW=%.1f tcH=%.1f nGlyph=%d len=%d n=%u",
              "_v46R = _t.attachmentBounds(",
              "_v46AttWant += _v46R.height",
              "_v46AttCached = _t.attV46CachedTotalH",
              "_v46AttCachedW = _t.attV46CachedWidth",
              # ★run#37124793234 的真实死因: 写成了 enumerateAttributes(复数)。
              #   NSAttributedString 只有 enumerateAttribute(单数), 编译期才炸,
              #   而断言只查子串存在性抓不到 —— 这里把 API 形式钉死。
              "textStorage as? NSTextStorage",
              "enumerateAttribute(",
              "NSRange(location: 0, length: _v46St.length)",
              # ★反向测试 A5 逼出来的: attNVI 必须**声明+被读+进日志**三处齐全。
              #   原来只查 `var _v46AttNVI = false` 这个子串, 删掉它之后
              #   `if _v46AttNVI == false ...` 与 NSLog 里的 attNVI 仍在,
              #   判据 `in t` 依然为真 —— 字段等于白声明, D3 永远无法验证。
              "var _v46AttNVI = false",
              "if _v46AttNVI == false, _t.needsLayoutInvalidation { _v46AttNVI = true }",
              "_v46AttNVI ? 1 : 0",
              "if _v46AttN > 0 {"):
        if k not in t:
            raise RuntimeError(f"verify_attachment_v46: 缺少判据字段 {k}")
    # 2. 必须用 do { } —— 裸块会被吸成 trailing closure(v42 首次推送就栽在这)。
    #    【切片边界】切到 do 块的闭合而不是 NSLog( —— NSLog 参数列表里也含
    #    self. 引用, 只切到 NSLog( 会把参数切掉让下一条判据误报(同 v44)。
    _i_do = t.find("do {", _i0)
    if _i_do < 0:
        raise RuntimeError("verify_attachment_v46: 诊断段没有 do { 块")
    _i_end = t.find("\n            }\n", _i_do)
    if _i_end < 0:
        raise RuntimeError("verify_attachment_v46: do 块未闭合")
    _v46_seg = t[_i0:_i_end + 15]
    # 3. ★纯诊断: 段内不得对**任何已有状态**赋值。
    #    【为什么不用"逐行白名单"】第一版写的是逐行 if/continue 白名单, 结果
    #    为了让正常代码通过, 白名单里堆了 11 条 continue 特例 —— 任何一处
    #    格式变动(缩进/换行/参数顺序)都会误报, 而漏放只要写一个新语句就穿透。
    #    改成**扣赋值语句本身**: 去掉注释与字符串后, 找出所有"标识符 = "形式
    #    的赋值, 再排除掉唯一合法的一类(局部 `let`/`var` 声明)。语义判据,
    #    不受格式影响。
    _v46_code = _strip_swift_noise(_v46_seg)
    for _ln in _v46_code.splitlines():
        _s = _ln.strip()
        if not _s:
            continue
        # 局部声明: 合法
        if _s.startswith("let ") or _s.startswith("var "):
            continue
        # struct 声明行里的 `static var last: CFTimeInterval = 0` 是**类型标注
        # 上的默认值**, 不是对已有状态的写。节流计数器必须有这个结构
        # (与 V41-KVOPRE/V44/V45 同款), 不能因此把 attNVI/attain 判据删掉。
        if _s.startswith("struct "):
            continue
        # 自增: 不是赋值(它本身就是"读+写", 但写的是诊断自己的计数器)
        if "&+=" in _s:
            continue
        # 可选绑定是**读取**, 不是赋值 —— `guard let _a = attrs[...]` / `if let
        # x = y` 只是把可选项解包成本地常量, 它没有写任何已有状态。
        # (第一版没排除这条, 结果诊断段里第一个 guard let 就被自己判死。)
        _bind = re.match(r"^(guard|if|while)\s+(let|var)\b", _s)
        if _bind:
            continue
        # 找赋值: 形如 `x = ...` 或 `x.y = ...` / `x[i] = ...`
        _m = re.search(r"(?<![\w.\]\)])\b([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*(?:\[[^\]]*\])?)\s*=(?!=)", _s)
        if _m and not _s.startswith("=="):
            # ★只拦"对已有状态的写", 不拦诊断自己的局部计数器。
            #   `_v46AttNVI = true` 写的是本段刚声明的局部 var, 它是**收集
            #   判据数据**的必要步骤(attNVI 这个字段就是这么来的), 不是修法。
            #   `_V46Log.last = ...` 同理 —— 节流计数器是所有诊断段的标准
            #   结构(V41-KVOPRE/V44/V45 都是这么写的), 禁掉它等于禁掉节流,
            #   而没有节流的诊断会把主线程日志打爆。
            #   真正要禁的是写 self./attachment/容器/缓存 —— 那些由第 4 条
            #   的危险调用清单覆盖。判据若不区分这两者, 就会逼着把 attNVI
            #   这类必需字段从诊断里删掉, 反而损失候选根因的判据。
            _lhs = _m.group(1)
            if not (_lhs.startswith("_v46") or _lhs.startswith("_V46Log")):
                raise RuntimeError(
                    f"verify_attachment_v46: ★纯诊断违规 —— 段内出现赋值 {_lhs!r}: {_s[:70]!r} "
                    "(v46 必须只读; 任何写入都会让四个候选根因无法归因)")
    # 4. ★硬禁危险调用: invalidate / 强制布局 / 缓存写入。这些是"修法"动作,
    #    出现在诊断段里等于偷偷把 v47 的活干了, 装机数据失去归因价值。
    # 4b. ★硬禁危险 API 名 —— 必须在**剥掉注释与字符串之后**的代码上查。
    #     【踩坑记录(本轮实跑)】第一版直接查原始文本, 结果注入体里那段
    #     "踩坑记录: 第一版写的是 enumerateAttributes" 的**注释**被判成真代码,
    #     自己把自己拦下了。API 名误报/漏报都发生在这里: 注释里提一嘴错名字
    #     不算错, 代码里真写错才算。所以这一条必须基于 _v46_code。
    for _bad in ("invalidateLayout", "invalidateDisplay", "invalidateIntrinsic",
                 "invalidateSize", "ensureLayout", "invalidateCachedLayout",
                 "cachedLayout =", "needsLayoutInvalidation =", "needsViewRebuild =",
                 "textContainer.size =", ".frame =", "setNeedsDisplay",
                 "computeLayout(", "contentGeneration &+=",
                 # ★run#37124793234 的真实死因。NSAttributedString 只有
                 #   enumerateAttribute(单数), 写成复数编译必炸, 而所有其它
                 #   判据都抓不到(它们只查自己关心的子串)—— 只能显式禁。
                 "enumerateAttributes"):
        if _bad in _v46_code:
            raise RuntimeError(
                f"verify_attachment_v46: 段内出现禁用项 {_bad!r}"
                + ("  ★API 名错误: NSAttributedString 只有 enumerateAttribute(单数), "
                   "写成复数编译期才炸(run#37124793234 就是这样失败的)"
                   if _bad == "enumerateAttributes" else "  ★纯诊断违规"))
    # 4c. 必需的 API 形式(正向): 遍历附件必须走 textStorage as? NSTextStorage
    #     + enumerateAttribute(单数)。少了任一个都编译不过, 所以正向也钉死。
    for _must in ("textStorage as? NSTextStorage", "enumerateAttribute(",
                  "NSRange(location: 0, length: _v46St.length)"):
        if _must not in _v46_code:
            raise RuntimeError(
                f"verify_attachment_v46: 段内缺少必需的 API 形式 {_must!r} "
                "(编译期错误, 断言阶段必须拦住)")
    # 5. 必须挂在 v45 之后、v44 之前(同一闭包内, v45 -> v46 -> v44 依次相邻),
    #    这样几何(v44)/补高(v45)/附件(v46)三者同帧并列对照。
    #    【反向测试 C2 逼出来的缺口】原来只查了"v46 在 v45 之后", 没查
    #    "v46 在 v44 之前" —— 把 v46 搬到 v44 之后(v45 < v44 < v46)时,
    #    第一条判据仍然成立, 整段漏放。现在两个方向都钉死。
    _i45 = t.find("// [V45-TVHFIX] 补高**补到画字的那个视图上**")
    if _i45 < 0:
        raise RuntimeError("verify_attachment_v46: 未找到 v45 段(登记顺序错了?)")
    if _i45 > _i0:
        raise RuntimeError(
            "verify_attachment_v46: v46 挂在 v45 之前 —— 必须排在 v45 之后, "
            "同一闭包同帧, 三者(几何/补高/附件)才能并列对照")
    _i44 = t.find("// [V44-TEXTFRAME] 见函数 docstring")
    if _i44 < 0:
        raise RuntimeError("verify_attachment_v46: 未找到 v44 段(登记顺序错了?)")
    if _i0 > _i44:
        raise RuntimeError(
            "verify_attachment_v46: v46 挂在 v44 之后 —— 必须排在 v44 之前 "
            "(插入点固定在 V44 段头, 顺序应为 v45 -> v46 -> v44)")
    # 6. 节流必须 0.5s —— 与 V41-KVOPRE/V44-TEXTFRAME/V45-TVHFIX 同周期。
    if "_v46Now - _V46Log.last > 0.5" not in t:
        raise RuntimeError("verify_attachment_v46: 必须 0.5s 节流(与其余诊断同周期)")
    # 7. 必须保留 v44 诊断与 v45 修法(诊断是加法, 不是替换)。
    for _keep in ('NSLog("[V44-TEXTFRAME]', 'NSLog("[V45-TVHFIX]'):
        if _keep not in t:
            raise RuntimeError(f"verify_attachment_v46: 必须保留 {_keep} —— v46 是加法")
    # 8. 全文花括号平衡(共用 _brace_balance)。min_depth 也查 ——
    #    v45 反向测试 F1 实跑教训: 在别处插一个永不闭合的函数, 前 7 条判据
    #    全过、编译才炸。放最后当总兜底。
    _depth, _low = _brace_balance(t)
    if _depth != 0:
        raise RuntimeError(f"verify_attachment_v46: 花括号不平衡(净 {_depth:+d} 处)")
    if _low < 0:
        raise RuntimeError(f"verify_attachment_v46: 花括号中途变负(最深 {_low}) —— 有未闭合结构")
    # 9. 标记计数放最后当总兜底(见函数 docstring「判据顺序」)。
    if t.count('NSLog("[V46-ATTACH]') != 1:
        raise RuntimeError("verify_attachment_v46: V46-ATTACH 标记必须唯一")
    # 10. 访问器必须无 setter —— 结构上保证"只读"。出现 setter 即失去意义,
    #     而且会让第 4 条的纯诊断防线从后门被打开。
    _i_acc = t.find("var attV46CachedTotalH")
    if _i_acc < 0:
        raise RuntimeError("verify_attachment_v46: 访问器缺失")
    _acc_line = t[t.rfind("\n", 0, _i_acc) + 1:t.find("\n", _i_acc)]
    if "{" not in _acc_line or "}" not in _acc_line:
        raise RuntimeError(
            f"verify_attachment_v46: 访问器必须是只读 getter(结构上不可写): {_acc_line.strip()!r}")
    if "set" in _acc_line:
        raise RuntimeError("verify_attachment_v46: 访问器不得带 setter")


def fix_width_reflow_v47(t):
    """v47: 统一测宽源 —— 治'终端框盖住上面的字 / 定时任务字一下有一下没有'。

    ── log16 归因(v46 纯诊断装机实测, 45 条 V46-ATTACH / 77 条 V44-TEXTFRAME)──

    v46 的四个候选根因, 实测**三个全部排除**:

      D1 缓存未失效      → 排除: `attWant == attCached` **45/45**。缓存新鲜,
                             attachmentBounds 返回的高度就是对的。
      D2 探针宽度不同源    → 排除: `cachedW` 与 `tcW` 恒差 1.0(389 vs 390),
                             不是"别的宽度下留下的陈旧值"。
      D3 失效信号未消费    → 排除: `attNVI=1` **0/45**, 信号从未置位。
      D4 容器被 guard 短路 → **真凶, 但机制与预想不同**(见下)。

    ── 决定性证据: 按 len 聚合 V46 ──

        len    n   attWant   usedH    needH      tcH    gap
         26    1      74.0    151.5    159.7    151.7    8.2   ← 正常
        266    1     182.0    623.4    631.7    623.7    8.3   ← 正常
        538    1     182.0    814.5    822.7    814.7    8.2   ← 正常
        591    7     182.0    826.5    901.7    893.7   75.2   ← 异常
        680    1     326.0   1192.1   1245.0   1237.0   52.9   ← 异常
        775   33     326.0   1301.5   1354.3   1346.3   52.8   ← 异常

      1. `tcH - needH = -8.0` **恒定在全部 7 组** —— 容器高度恰好等于需求高度
         减一个 textContainerInset。**容器本身没问题, v45 补高完全正确。**
      2. `tcH - usedH` 正常组是 **0.2~0.3**(容器与 TextKit 占用完全吻合),
         异常组是 **67.2 / 44.9 / 44.8** —— 差的这几十 pt 就是"空壳"。
      3. `attWant` 与 gap **不成比例**(182→75.2, 326→52.8) → 不是"附件整体
         没进排版", 而是**行数不一致**。

    ── 真凶: 测宽与渲染宽不同源, 行碎片按 390 排、需求高度按 358 算 ──

    源码既有链条(v34 已建"一处计算处处一致"的单一真相源):

        渲染端 v18 (layoutSubviews, 7752 起):
            var _realW = _svW > 1 ? min(_svW, _cvW) : _cvW
            if _edgeTouch { _realW = max(_realW - 32, 100) }   → 358
            ios15LastRenderContentW = _realW                  ← 真相源
            if textContainer.size.width > _realW + 1 { textContainer.size.width = _realW }
            ...
            let _realW2 = _realW
            var _ios15WRegrabbed = false
            if abs(textContainer.size.width - _realW2) > 0.5 {
                textContainer.size.width = _realW2
                _ios15WRegrabbed = true                       ← ★仅"当帧偏了"才为真
            }
            if _ios15WRegrabbed, textStorage.length > 0 {
                layoutManager.invalidateLayout(...)            ← ★条件性重排
            }
            let _needH = sizeThatFits(CGSize(width: _realW2, ...)).height   ← 按 358 算

        测高端 invalidateCellSizeIfNeeded (8339 起):
            measureWidth = ios15LastRenderContentW ?? ...                    ← 也按 358

    **`_ios15WRegrabbed` 是条件量, 这是 v47 的靶心。**

    先把"哪些数是对的"钉清楚(log16 实测, 不是推理):
      · `tcH - needH = -8.0` 恒定 → **容器高度是对的**
      · `V43-WIDTH dirtyW=390.0 netW=358.0 dh=0.0` → **测高用的是净宽 358, 也对**
      · 但 `tcW` 实测恒为 390, 且 `tcH - usedH` 在异常组是 44~67pt → **排版宽度错了**

    所以是"**测高对、排版错**"。要修的是让**排版**也稳定在 358, 而不是改测高
    去迁就 390。

    错在哪: `_ios15WRegrabbed` 由 `abs(tcW - _realW2) > 0.5` 决定, 它只是
    "**有没有改过容器宽**"的标志, 不是"**行碎片有没有按目标宽重排过**"的标志。
    v18 在 7752 的 layoutSubviews 里抢回 358 后, 行碎片才按 358 重排; 但
    `ensureLayout` 之外还有别处会触发布局, 且 SwiftUI 每帧把容器宽推回全屏
    390(codeload 的 v43 注释实证: "SwiftUI poll 每帧把容器宽打回 390")。当
    SwiftUI 写回 390 后**没有再走 v18**(例如 KVO 抢帧器先跑、或本次 pass 早退),
    行碎片就停在 390 上, 而 `_needH` 恒按 358 算 —— **两个数不同源**。

    ★关键区分: `invalidateLayout` 才是让行碎片按新宽重排的那一步, 而
    `textContainer.size.width = ` 只改容器不重排既有碎片。原来的判据把两者
    混为一谈, 于是"容器宽碰巧已经对了"的那些帧就**跳过重排** —— 碎片留在
    旧宽, 高度按新宽算, 差出来的就是那 44~67pt 空壳。

    v47 不去追"tcW 为什么是 390"(那是 SwiftUI 的正常行为, 改它就是 v13/v34
    翻过的车), 只补上"**行碎片是否与目标宽同步**"这个本该有的判据。

    ── 为什么不能改测高端 ──

    注释里已论证(留在源码里, 不重复): "为什么不能'两链都改用 tcW': v18 必须
    用净宽, 因为渲染排版最终是按 358 做的…用 390 量出来的高度对应一个
    **不存在的排版**"。v13/v34 都因抢宽引起过闪屏与整体缩小, 那是**改渲染端
    钳宽**翻的车; 本版只加**同宽重排**, 不新增任何宽度写入点。

    ── 修法(只改一处, 最小面) ──

    把 `_ios15WRegrabbed` 从"本帧宽度确实变了"改成"**本帧渲染宽与上次排版
    时用的宽不同**"。新增实例属性 `ios15LastLaidOutW`, 在 `ensureLayout` 之后
    记下本次实际用于排版的宽; 下次进来若与 `_realW2` 不同(哪怕此刻 tcW 恰好
    已被 SwiftUI 改成 358), 也强制 invalidateLayout 一次。

    这样:
      · 不新增宽度写入点(仍只有 v18 那两处) → 不碰 v13/v34 的雷区
      · 不改测高端 → measureWidth 继续读 ios15LastRenderContentW
      · 只在"排版宽与目标宽不一致"时多排一次, 稳态下 **零额外开销**
      · 幂等: 排完即记, 下帧相等则不进 if → 不反复重排

    ── 为什么这样能治'盖住'与'闪' ──

      · 盖住: 行碎片按 358 排 → usedH 追上 needH → 空壳消失 → 终端框不再
        画在空壳上
      · 闪: usedH 与 needH 不再随 SwiftUI 帧摆动 → 高度不再在两个值间跳 →
        "定时任务那几个字一下有一下没有"消失

    ★只碰宽度与重排, **不碰高度逻辑** —— v45 的 tvH 补高已实测有效(debt 全 0),
    一旦在这里动高度就会把 v45 的成果推翻。校验函数硬禁任何 height 写入。
    """
    OLD = """            let _realW2 = _realW
            var _ios15WRegrabbed = false
            if abs(textContainer.size.width - _realW2) > 0.5 {
                textContainer.size.width = _realW2
                _ios15WRegrabbed = true
            }"""
    NEW = """            let _realW2 = _realW
            var _ios15WRegrabbed = false
            if abs(textContainer.size.width - _realW2) > 0.5 {
                textContainer.size.width = _realW2
                _ios15WRegrabbed = true
            }
            // [V47-REWRAP] log16 归因: 行碎片"按 390 排、需求高度按 358 算"。
            // 容器被 SwiftUI 每帧推回全屏 390, 于是同一段文字在两个宽度下
            // 排出的**行数不同**: 390 宽行少、358 宽行多。usedH 追不上 needH,
            // 差出的 44~67pt 是**空壳**(实测 tcH-needH 恒 -8.0 说明容器本身
            // 没问题), 下一个视图就画在空壳上 —— 用户看到的"终端框盖住上面的字"。
            //
            // 原来的 `_ios15WRegrabbed` 只表示"**有没有改过容器宽**", 不表示
            // "**行碎片有没有按目标宽重排过**"。`invalidateLayout` 才是让碎片
            // 按新宽重排的那一步; 而 SwiftUI 每帧把容器宽推回全屏 390(实测
            // tcW 恒为 390), 当某帧没有再走 v18 时, 碎片就停在旧宽上,
            // 而 `_needH` 恒按 358 算 —— **两个数不同源**。
            //
            // 修法: 把重排判据从"tcW 此刻是否偏了"换成"**上次排版用的宽是否
            // 等于目标宽**"。只在两者不等时多排一次, 稳态下零额外开销; 排完
            // 立刻记下, 下帧相等则不进 if → 幂等, 不会每帧重排。
            //
            // **不新增任何宽度写入点**(仍只有上面那两处) —— v13/v34 反复因
            // 抢宽引起闪屏与整体缩小, 那是改钳宽翻的车, 这里只加同宽重排。
            // **不碰高度** —— v45 的 tvH 补高已实测有效(debt 全 0)。
            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {
                _ios15WRegrabbed = true
            }"""
    if OLD not in t:
        raise RuntimeError(
            "fix_width_reflow_v47: 未找到 _realW2/_ios15WRegrabbed 锚点 —— "
            "上游 SelectableMarkdownView 的 v18 抢宽段结构变了, 必须更新 OLD 后再发版")
    t = t.replace(OLD, NEW, 1)

    # 记下本次实际用于排版的宽(紧跟 ensureLayout 之后, 那才是行碎片真正定型的地方)
    OLD2 = """            let _needH = sizeThatFits(CGSize(width: _realW2, height: .greatestFiniteMagnitude)).height
            if _ios15WRegrabbed {
                layoutManager.ensureLayout(for: textContainer)
            }"""
    NEW2 = """            let _needH = sizeThatFits(CGSize(width: _realW2, height: .greatestFiniteMagnitude)).height
            if _ios15WRegrabbed {
                layoutManager.ensureLayout(for: textContainer)
                // [V47-REWRAP] 行碎片已按 _realW2 定型, 记下来供下次比对。
                self.ios15LastLaidOutW = _realW2
            }"""
    if OLD2 not in t:
        raise RuntimeError(
            "fix_width_reflow_v47: 未找到 ensureLayout 锚点 —— "
            "上游 v18 的测高段结构变了, 必须更新 OLD2 后再发版")
    t = t.replace(OLD2, NEW2, 1)

    # 新增实例属性。
    #
    # 【锚点为什么是 ios15LastSaneSVFrame 而不是 ios15LastRenderContentW】
    # 后者是 **v34** 才注入的属性, 而 v47 排在 v46 之后 —— 此刻它根本还不存在,
    # 拿它当锚点必然 RuntimeError(run#37129575066 就是这么崩的, 死在第 12 步
    # 「第三阶段」, 连自检都没到)。ios15LastSaneSVFrame 是 v18 同批注入的,
    # 在 v47 之前一定存在。
    # 教训: 选锚点只能挑**排在本版之前**就注入的符号, 不能挑"同一真相源家族"
    # 里看着更贴切的那个 —— 家族关系是语义, 注入时序才是硬约束。
    DECL_OLD = """    var ios15LastSaneSVFrame: CGRect?"""
    DECL_NEW = """    var ios15LastSaneSVFrame: CGRect?
    /// [V47-WSTATE] 行碎片**上一次定型时**用的排版宽。见 fix_width_reflow_v47
    /// 的 docstring: 容器宽会被 SwiftUI 每帧推回全屏 390, 而需求高度恒按净宽
    /// 358 算, 两者不同源 → 行数不一致 → usedH 少 44~67pt(空壳, 表现为
    /// "终端框盖住上面的字")。本属性让 v18 能察觉"排版宽 ≠ 目标宽"并补一次
    /// 重排。稳态下恒等于 _realW2, 不触发任何额外开销。
    var ios15LastLaidOutW: CGFloat?"""
    if DECL_OLD not in t:
        raise RuntimeError(
            "fix_width_reflow_v47: 未找到 ios15LastSaneSVFrame 声明锚点")
    t = t.replace(DECL_OLD, DECL_NEW, 1)

    verify_width_reflow_v47(t)
    return t

def fix_width_pin_v48(t):
    """v48: 排版宽钉回目标宽 —— log17 归因「v47 只治了一半」后的收口。

    ── log17 实测: v47 起了一半作用但没根治 ──

    对比两版装机日志的 `V44-TEXTFRAME`:

                     tcW=390   tcW=358   gap最小  gap最大   gap<1 的条数
      log16 (v46)      69         8       8.1     75.2          0
      log17 (v47)      48         8       8.0    117.5          0

    两点关键:

    1) `tcW` 与 `tvH - usedH` **完全同构, 零例外**:
         tcW=358.0 → gap 恒为 8.0~8.3   (= textContainerInset 上下之和, 正常态)
         tcW=390.0 → gap 为 30.5 / 117.5  (空壳)
       len=229 那组最有说服力: 同一段文字, tcW=358 时 gap=8.1,
       tcW=390 时 gap=30.5 —— 差值就是 390 宽排不下的那几行。

    2) tcW=390 的帧从 69 降到 48, 说明 **v47 的重排确实触发了**,
       但没根治: 碎片在 358 排完, SwiftUI 下一帧又把容器推回 390,
       于是"重排→被推回→再重排"无限摆动。`tvH-needH` 全部 56 条为 0.0
       (v45 的补高依然完美), 所以问题**只在宽度**, 不在高度。

    ── 为什么 v47 必然治不好 ──

    v47 只调`invalidateLayout`, **不写`textContainer.size.width`** ——
    那是当时为了"不碰 v13/v34 抢宽雷区"刻意留的约束。但 TextKit 的
    `ensureLayout` 只在**当前容器宽**下重排; 容器宽还是 390 时, 重排出来的
    仍是 390 宽的行数, 一点用都没有。log17 的 tcW 分布直接证实了这一点:
    v47 跑完之后仍有 48/56 帧的 tcW 是 390。

    所以必须**同时把容器宽钉回 _realW2**, 让"排版用的宽"与"测高用的宽"
    真正同源。这是一次新的抢宽, 因此本版把 v13/v34 的教训当成硬约束:

    ── 防闪屏: 为什么这次抢宽不会重演 v13/v34 ──

    v13/v34 翻车的原因是**在 SwiftUI 的布局 pass 之外无条件抢宽**, 且
    抢到的宽与父视图语义宽不一致, 导致 SwiftUI 认为尺寸又变了、整棵
    cell 重新走一遍 layout。本版与它们的差别是**有界且幂等**:

      · **有界**: 目标宽 `_realW2` 不是新算的, 就是 v18 已经算好并写进
        `textContainer` 的那个值(与 `sizeThatFits` 测高用的是同一个),
        所以"排版宽 == 测高宽 == v18 认可的宽", 不引入第三方宽度。
      · **幂等**: 判据是 `abs(tcW - _realW2) > 0.5`。已经在 358 时
        不写、不重排, 稳态下**零额外开销**; 被 SwiftUI 推回 390 时才
        拉回一次 —— 这是**纠偏**不是**竞争**。
      · **不碰高度**: 一个高度写入都不加, v45 的 tvH 补高成果不受影响。
      · **不碰 origin/bounds**: 只写 `textContainer.size.width`,
        不动 `frame`/`bounds`, 所以不会触发"整体缩小"那类几何漂移。
      · **在 v18 段内**: 复用 v18 已经算好的 `_realW2` 与它自己的
        `if _ios15WRegrabbed` 块, 不新增独立的抢宽时机 ——
        v13/v34 的事故都源于"另起一个时机去改别人算好的宽"。

    ── 与 v47 的关系 ──

    v47 的 `ios15LastLaidOutW` 判据**保留不动**: 它判的是"碎片有没有按
    目标宽重排过", 与"容器宽有没有被钉住"是两个正交的问题。v48 只在
    v47 判据成立的同一处, 补一次宽度写入 —— 两个判据合起来才是完整条件:

        容器宽 == 目标宽  且  碎片按目标宽重排过

    ── 为什么不能更激进(常驻钳宽) ──

    "每帧无条件写 358"看着更彻底, 但那正是 v13/v34 翻车的形态: 与
    SwiftUI 的布局 pass 正面竞争。本版只在 v47 判据(碎片与目标宽不
    一致)时纠偏, 而碎片一致本身就说明布局已经稳定, 不需要再抢。

    ★登记必须排在 v47 之后(锚点是 v47 注入的 `ios15LastLaidOutW` 回写)。
    """
    OLD = """            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {
                _ios15WRegrabbed = true
            }"""
    NEW = """            if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {
                _ios15WRegrabbed = true
            }
            // [V48-PIN] log17 归因: v47 只治了一半 —— 重排触发了(tcW=390 的帧
            // 69→48), 但 `textContainer.size.width` 仍是 390, 于是
            // `ensureLayout` 照着 390 重排, 与按 358 算出的 `_needH` 依旧
            // 不同源。log17 里 tcW 与 gap 完全同构、零例外:
            //     tcW=358.0 → tvH-usedH 恒 8.0~8.3  (textContainerInset, 正常)
            //     tcW=390.0 → tvH-usedH 为 30.5/117.5(空壳)
            // len=229 那组最直接: 同一段文字, 358 宽 gap=8.1, 390 宽 gap=30.5。
            //
            // 修法: 碎片与目标宽不一致时, **连容器宽一起钉回** _realW2。
            // 两者合起来才是完整条件 —— 容器宽==目标宽, 且碎片按目标宽重排过。
            //
            // **这不是新的抢宽时机**: 写在 v18 段内, 复用 v18 已算好的
            // _realW2(与 sizeThatFits 测高用的是同一个值), 不引入第三方宽度。
            // 判据 `abs(tcW-_realW2)>0.5` 保证幂等 —— 已在 358 时不写不重排,
            // 稳态零开销; 被推回 390 才纠偏一次, 是**纠偏**不是**竞争**。
            // v13/v34 翻车是因为在布局 pass 外无条件抢宽、与 SwiftUI 竞争,
            // 本版恰好相反。只写 size.width, **不碰 frame/bounds/origin/高度**,
            // 所以不会引起"整体缩小"那类几何漂移, 也不推翻 v45 的 tvH 补高。
            if _ios15WRegrabbed, abs(textContainer.size.width - _realW2) > 0.5 {
                textContainer.size.width = _realW2
            }"""
    if OLD not in t:
        raise RuntimeError(
            "fix_width_pin_v48: 未找到 v47 的重排判据锚点 —— "
            "上游或 v47 结构变了, 必须更新 OLD 后再发版")
    t = t.replace(OLD, NEW, 1)

    verify_width_pin_v48(t)
    return t


# [V48-FORBIDDEN] v48 段内禁写的标识集合 —— 精确匹配。
#   与 v47 的区别: v47 禁一切高度写入(它压根不该碰宽度), 而 v48 **要写宽度**,
#   所以这里只禁高度与几何(origin/bounds/frame), 宽度不在禁用集合里。
#   用子串会踩坑: `_ios15WRegrabbed` 里含 "eight"(r-EIGHT-grabbed)。
_V48_FORBIDDEN_LHS = frozenset((
    "height", "Height", "h", "needH", "newHeight", "lastComputedHeight",
    "ios15LastNeededH", "ios15LastNeededH", "frame", "bounds", "origin",
    "_hf", "_needH", "_needH39", "sizeToFit", "ios15LastSaneSVFrame",
))

# v48 允许的唯一写入 —— 精确等值, 任何变体都算违规。
#   理由: 抢宽翻车几乎都源于"多写了几样"。白名单比黑名单可靠:
#   多写一个 frame.origin 就足以让整棵 cell 重新布局(v13/v34 的教训)。
_V48_ALLOWED_WRITE = "textContainer.size.width = _realW2"


# v48 段判据的编译期兜底基线 —— 上游 SelectableMarkdownView 自身的花括号
# 净差(剥注释后)。不是 0: 该文件含 `\(expr)` 插值与 #if 预处理器块, 简单计数
# 本来就不配平。判据只看"净差有没有被本版改动", 不看绝对值。
_V48_BASELINE_BRACE = -1


def verify_width_pin_v48(t):
    """校验 v48 —— 独立成函数, 不只服务于注入。

    ★判据范围必须精确到 v48 新增块(与 v47 同教训): 既有代码不是本版的
    产物, 判据不能碰它。范围 = `// [V48-PIN]` 到该段末尾的 `}`。
    """
    # ---- 1. 注入点存在 ----
    i_pin = t.find("// [V48-PIN]")
    if i_pin < 0:
        raise RuntimeError("verify_width_pin_v48: 未找到 V48-PIN 注入点")

    # v48 段 = 从 V48-PIN 标记起, 到本段块闭合(行首 12 空格的 } 为界)。
    # 段尾锚点必须在注入点下游 —— 用固定字符数回退等于没有边界(v47 教训)。
    # 段 = V48-PIN 标记起, 到**下游稳定锚点** `// [IOS15-FIX-RELC v28]` 之前
    # (那是 v18 抢宽段末尾的既有标记, sabotage 不会碰它)。
    #
    # 【踩坑记录 —— 这条判据曾经形同虚设, 15/20 条 sabotage 全漏放】
    # 第一版用 `t.find("\n            }", i_pin)` 当段右边界。但 v48 的 if 块
    # **只有一层**, 那个闭合花括号恰好紧跟在唯一的写入行之后 —— 于是段切片
    # 在写入行处就截断了, 反向测试往写入行后面追加的 `frame.size.width =` /
    # `bounds.size.width =` / 高度写入**全部落在段外**, 一条都扫不到。
    # 于是"写入白名单"和"禁高度/几何"两组判据同时失效, 却看起来全绿。
    #
    # 教训比修法重要: **段右边界锚点必须选在 sabotage 改不到的地方**。
    # 锚点选在被测代码自己的闭合花括号上, 等于把判据的视野关在被测对象里 ——
    # 判据只能证明"第一行没问题", 证明不了"后面几行没问题"。
    # 这与 v47 的"二次切割"是同一个根源: 都在用**代码自身结构**当边界。
    #
    # ★★ 第四次翻版(run#37137912522): 这次不是"太窄"而是"**太宽**"。
    #   v49 把纯诊断探针插在钉宽 if 之后、v28 标记之前, 而本判据的段一直
    #   伸到 v28 标记 ⇒ v49 探针的三行记忆位写入被算进 v48 的白名单, 判出
    #       pure=BAD 赋值4处 违规=[...] 旁路=False idem=OK
    #   而 v49 本身完全合规(它自己的四层判据在 CI 里全绿)。
    #   ⚠️ 同一段右边界在**三处**都有副本(本函数、ci_assert_v48.py、及其
    #   反向测试), 只改一处就是 run#37133885324 那次"判据被复制多份"的翻版。
    #
    # ⇒ 右边界改为 **v49 探针起点**(若 v49 未注入则仍用 v28 标记兜底):
    #     · 切掉 v49 探针(那是 v49 的事, 由 v49 判据管)
    #     · 保留 v48 if 之后的空间(反向测试 B11 要在那里追加合法读取
    #       来验证"判据不误伤", 收得太紧会把那条误判成破坏)
    _V49_HEAD = "// [V49-WWRITER-V18]"
    i_v49 = t.find(_V49_HEAD, i_pin)
    if i_v49 > i_pin:
        i_end = i_v49
    else:
        i_end = t.find("// [IOS15-FIX-RELC v28]", i_pin)
        if i_end < 0:
            raise RuntimeError(
                "verify_width_pin_v48: 未找到段尾锚点(既没有 %s 也没有"
                " // [IOS15-FIX-RELC v28]) —— v18 抢宽段结构变了, "
                "判据范围必须重新确定" % _V49_HEAD)
    blk = t[i_pin:i_end]

    # ---- 2. 剥注释后做纯语义检查 ----
    import re as _re
    code = _re.sub(r"//[^\n]*", "",
                   _re.sub(r"/\*.*?\*/", "", blk, flags=_re.S))

    def _lhs(line):
        m = _re.match(r"\s*([\w.]+)\s*(?:=|\+=|-=|\*=|/=)(?!=)", line)
        return m.group(1) if m else None

    writes = []
    for line in code.split("\n"):
        tgt = _lhs(line)
        if tgt:
            writes.append((tgt, line.strip()))

    # ---- 3. ★白名单: 只许写 textContainer.size.width, 且只写 _realW2 ----
    for tgt, line in writes:
        # 完整点号链 + 末段双重命中。
        #   只看末段不够: 别的接收者(textView.size.width)也会末段相同。
        #   只看整链不够: 变量名恰好叫 size.width 的情况会漏。
        if tgt != "textContainer.size.width" and tgt.split(".")[-1] != "size.width":
            raise RuntimeError(
                "verify_width_pin_v48: v48 段内出现非白名单写入 `%s`(行: %s)"
                % (tgt, line))
        if tgt != "textContainer.size.width":
            raise RuntimeError(
                "verify_width_pin_v48: 宽度写入换了接收者 `%s`(行: %s) —— "
                "只准写 textContainer.size.width" % (tgt, line))
        # 右侧必须是 _realW2, 不能是别的宽
        m_val = _re.search(r"=\s*([^=].*?)\s*$", line)
        if not m_val or m_val.group(1).strip() != "_realW2":
            raise RuntimeError(
                "verify_width_pin_v48: 宽度写入的值不是 _realW2(行: %s) —— "
                "换宽度来源等于引入第三方宽度, v13/v34 的闪屏就是这么来的"
                % line)

    # ---- 4. ★禁高度/几何(防"整体缩小"与推翻 v45) ----
    for tgt, line in writes:
        if tgt in _V48_FORBIDDEN_LHS or tgt.split(".")[-1] in _V48_FORBIDDEN_LHS:
            raise RuntimeError(
                "verify_width_pin_v48: v48 段内写了高度/几何 `%s`(行: %s) —— "
                "本版只许写 textContainer.size.width" % (tgt, line))

    # ---- 5. 必须复用 v47 的判据(不得另起抢宽时机) ----
    if "_ios15WRegrabbed" not in blk:
        raise RuntimeError(
            "verify_width_pin_v48: 未复用 _ios15WRegrabbed —— "
            "另起抢宽时机就是 v13/v34 闪屏事故的形态")
    if "abs(textContainer.size.width - _realW2) > 0.5" not in blk:
        raise RuntimeError(
            "verify_width_pin_v48: 写入前必须用 abs(tcW-_realW2)>0.5 把门 —— "
            "无条件写回 358 是与SwiftUI 竞争, 等于 v13/v34 翻车")

    # ---- 5b. ★禁TextKit 的函数式旁路(判据曾被 setSize 绕过) ----
    # 【踩坑 —— 这是判据的实质漏洞, 不是形式问题】
    # 反向测试 A3 把写入换成
    #     textContainer.setSize(CGSize(width: _realW2, height: ...))
    # 结果段内识别到的赋值变成 **0 处** —— 因为上面所有判据都只认
    # `目标 = 值` 这种正则形态, 而 setSize 是**函数调用**。
    # 于是"写入白名单"和"禁高度/几何"两组判据同时失效, 却全绿。
    # 语义上 setSize 与 size 赋值**等价**, 都是改容器宽, 必须一并禁掉 ——
    # 校验只认自己写的形态, 等于给旁路留了门。
    for _banned in ("setSize(", "setSize:", ".setSize"):
        if _banned in code:
            raise RuntimeError(
                "verify_width_pin_v48: v48 段内出现 TextKit 函数式旁路 `%s` —— "
                "setSize 与 size 赋值语义等价, 同样是抢宽, 必须一并禁掉"
                % _banned)
    # 段内除白名单那一处外, 不得出现任何函数调用形式的写操作
    if _re.search(r"\btextContainer\s*\.\s*(?:set[A-Z]|[a-z]+\s*\()", code):
        raise RuntimeError(
            "verify_width_pin_v48: v48 段内出现 textContainer 上的其他写操作 —— "
            "只准 textContainer.size.width = _realW2")

    # ---- 6. 幂等: 回写 ios15LastLaidOutW 仍在(由 v47 保证, 这里查未被破坏) ----
    if "self.ios15LastLaidOutW = _realW2" not in t:
        raise RuntimeError(
            "verify_width_pin_v48: v47 的 ios15LastLaidOutW 回写不见了")

    # ---- 6b. ★编译期兜底: 全文件花括号**增量**配平 ----
    # E1 类 sabotage(在文件末尾插未闭合函数)落在 v48 段范围之外, 段判据
    # 按分层职责理应放行 —— 但未闭合函数编译期就炸, 必须拦住, 所以加第二道网。
    #
    # 【为什么必须判"增量"而不是绝对值】这个文件的花括号**本来就不配平**:
    # 剥注释后净差是 -1, 去掉字符串字面量后是 +3 —— 因为 Swift 的
    # `\(expr)` 字符串插值、`#if` 预处理器块、以及跨行字符串都会打乱简单计数。
    # 所以绝对值判据必然误报(实测B11「加一行合法读取」就被误伤)。
    # 正确做法: 只判 sabotage 有没有让净差**发生变化** —— 基线自身的偏差
    # 是上游/历史遗留的常数, 与本版无关; 变的是 sabotage 带来的。
    _all = _re.sub(r"//[^\n]*", "",
                   _re.sub(r"/\*.*?\*/", "", t, flags=_re.S))
    _bal = _all.count("{") - _all.count("}")
    if _bal != _V48_BASELINE_BRACE:
        raise RuntimeError(
            "verify_width_pin_v48: 全文件花括号净差从基线 %d 变成 %d —— "
            "段判据看不到段外的破坏, 这条是第二道网(净差变化说明有人动过结构)"
            % (_V48_BASELINE_BRACE, _bal))

    # ---- 7. 加法保留: v47 / v45 / v44 / v46 标记仍在 ----
    # V48-PIN / V47-WSTATE 各1 处; V47-REWRAP 天然是 2 处(v47 有两个注入点:
    # 判据处 + ensureLayout 回写处), 写死1 会把v48 的校验变成废判据。
    for tag, want in (("// [V48-PIN]", 1), ("// [V47-REWRAP]", 2),
                      ("/// [V47-WSTATE]", 1)):
        if t.count(tag) != want:
            raise RuntimeError(
                "verify_width_pin_v48: 标记 %s 计数应为 %d, 实为 %d"
                % (tag, want, t.count(tag)))
    for tag in ("[V44-TEXTFRAME]", "[V45-TVHFIX]", "[V46-ATTACH]"):
        if ('NSLog("' + tag) not in t:
            raise RuntimeError(
                "verify_width_pin_v48: v48 吃掉了 %s 的诊断日志" % tag)

    return True


# ══════════════════════════════════════════════════════════════════════
# v49 —— 【纯诊断】钉死「谁把 textContainer.size.width 推回 390」
# ══════════════════════════════════════════════════════════════════════
#
# ── log18 实测: v48 起了一半作用, 但重文本仍未治好 ──
#
# log18(59 条 V44-TEXTFRAME)按容器宽分组:
#
#     tcW      条数   gap最小  gap最大
#     358.0      10      8.1      8.5     ← 全部正常
#     390.0      49      8.2     97.6     ← ★18 帧正常 + 31 帧残缺(混合!)
#
# ★★ log17 的"tcW 与 gap 完全同构"**被打破**了:
# len=122 在 tcW=390 下 gap=8.2(**正常**) —— 前两版从未有过这个组合。
# ⇒ **v48 的钉宽确实生效了**, 但只治好了轻文本。
#
# 而重文本(len=1013, 含 1 个表格)仍然残缺:
#
#     n=9   cachedW=357.0  tcW=358.0  usedH=1727.6  gap=8.1    ✅
#     n=10  cachedW=389.0  tcW=390.0  usedH=1638.1  gap=97.6   ❌
#
# **cachedW 与 tcW 完全同构(35/36 零例外)** ⇒ 推宽者与 cachedW 同源。
#
# ── 逐毫秒读 log18 的 00:07:42 那几行, 因果链就齐了 ──
#
#   .672 [V42-GATE] cvW=390.0 latched=0.0 raw=0.0 storageLen=1013
#        [V41-KVOPRE] sv=(16,202.7,358.0,1377.7) needH=0.0 cvW=390.0
#   .676 [V43-WIDTH] dirtyW=390.0 netW=358.0 hDirty=1646.3 hNet=1735.7 dh=89.3
#   .678 [V42-MISS] selfMeasured needH=1735.7 **tcW=358.0**   ← ★此刻排版是对的
#        [V41-KVOHEIGHT] svH 1377.7→1735.7 debt=358.0
#   .679 [V46-ATTACH] usedH=1638.1 **tcW=390.0** cachedW=389.0 ← ★2ms 后被推回
#        [V44-TEXTFRAME] tcW=390.0 usedH=1638.1
#
# ⇒ 在 42.678→42.679 这**1 毫秒**里, tcW 从 358 变成 390。
# v48 的钉宽写在 `layoutSubviews` 里的 v18 段(缩进 12, 三层深),
# 而这段代码在**表格附件测量(V46-ATTACH)** 之前就跑完了 ——
# 纠偏时机**早于**推宽时机, 于是追不上。
#
# ── 为什么这一版是纯诊断, 不直接修 ──
#
# 从"1 毫秒内被推回"能推出候选写入者至少三个: V46 的 attachmentBounds
# 测量链、v37 的 probe 钳位链、SwiftUI 自己的布局 pass。**三者的修法互相冲突**:
# 放宽 V46 会动 v16 表格渲染; 动 probe 钳位会动 v37 那套 9 处泄漏防护;
# 抢 SwiftUI pass 就是 v13/v34 翻车的老路。
# 而 D4(`TextContainerGuard` 熔断 219 次, 358x2000 被熔 109 次)那条路
# 是治 fillLayoutHole 11918ms 卡死的, 同样是历史 trade-off。
#
# ⇒ 先用探针把「谁最后写的 tcW、值从哪来」打出来, 装机一次就能定位到**行**,
#    而不是继续在三个候选里猜。判据只读, 段内零赋值(与 v44/v46 同纪律)。
#
# ── 探针设计: 记录每一次 tcW 变化及其"来源指纹" ──
#
# 关键难点: Swift 无法在赋值点拦截。改用**前后差分 + 时序对齐**:
#   在 v18 段末尾(layoutSubviews 内, v48 钉宽**之后**)读一次 tcW,
#   在 KVO 抢帧器里(v41 补高处)再读一次, 两者同帧比对:
#     · v18 读到的已是 358, KVO 读到 390 ⇒ 推宽发生在 v18 之后
#   再叠加 `attV46CachedWidth`(cachedW)与 `cvW`, 三者构成完整指纹。
#
# ★ 为什么指纹里要记 `boundW`(textContainer 自身 bounds 宽):
#   TextKit 内部有一条独立于 size 的排版路径会用 bounds 推导宽度。
#   log18 里 `tcH=2000.0` 与 `358x2000.0` 被熔 109 次说明容器高常被放到
#   2000(v25/v26 遗留), 此时 TextKit 可能走 bounds 分支。
#   只记 size 看不到这一条。

# ★ v49 探针的静态状态声明为**类型级**(与 v44/v46 的诊断 struct 同法),
#   不能留在函数内 —— 【本轮实踩, 编译级】原先把它放在 v18 段(layoutSubviews
#   内)声明, 而 KVO 侧探针在另一个函数里引用 `_V49W`, **Swift 局部类型
#   跨函数不可见 → 编译直接失败**。类型级 struct 的 static 存储同样是
#   全进程单例, 语义不变, 探针只在自己的两个点读写它。
_V49_STATE = """    /// [V49-WSTATE] 探针静态状态: v18 段与 KVO 段的同帧读数 + 来源指纹。
    /// **必须是类型级** —— 两个读点分处 layoutSubviews 与 KVO 闭包两个函数,
    /// 函数内局部 struct 跨函数不可见(本轮实踩, 编译失败)。
    /// 纯诊断用的记忆字段, 不参与任何布局决策。
    struct _V49W {
        static var last: CFTimeInterval = 0
        static var n: UInt = 0
        // ★跨函数指纹: v18 段(layoutSubviews)与 KVO 抢帧器各写一次,
        // 两者在**同一帧**内的差值就是"谁在 v18 之后推的宽"。
        static var v18W: CGFloat = -1
        static var v18Tick: UInt = 0
        static var kvoW: CGFloat = -1
        static var kvoTick: UInt = 0
        static var tick: UInt = 0
    }
"""

_V49_TAIL = """            // [V49-WWRITER-V18] log18 归因: **谁**把容器宽推回 390。
            // 纯诊断, 段内零赋值 —— 与 v44/v46 同纪律, 行为改动必须另起一版。
            //
            // log18 逐毫秒铁证(00:07:42):
            //   .678 [V42-MISS] tcW=358.0  usedH=1727.6  ← 排版正确
            //   .679 V46-ATTACH tcW=390.0  usedH=1638.1  ← 1ms 后被推回
            // 而 v48 的钉宽写在 v18 段内(本段之前就跑完了) ⇒ 纠偏早于推宽,
            // 追不上。所以 v48 治好了轻文本(len=122 在 390 宽下 gap=8.2)
            // 却治不了重文本(len=1013 在 358 宽下 gap=8.1、在 390 下 97.6)。
            //
            // 候选写入者至少三个(V46 附件测量链 / v37 probe 钳位链 /
            // SwiftUI 布局 pass), 修法互相冲突, 先探针定位到行再动刀。
            _V49W.tick &+= 1
            self.ios15V18W = textContainer.size.width
            _V49W.v18W = textContainer.size.width
            _V49W.v18Tick = _V49W.tick
            // [V49-WWRITER-V18-END] 段结束标记 —— 见 v49 判据第 3 组。
"""

_V49_KVO = """                        // [V49-WWRITER-KVO] KVO 侧读数(与 v18 侧同帧比对)
                        _V49W.tick &+= 1
                        _V49W.kvoW = self.textContainer.size.width
                        _V49W.kvoTick = _V49W.tick
                        // ★来源指纹三个都必须是**真实读数**, 声明了不赋值等于白打:
                        //   cvW   = collectionView 自身脏宽(log18 里恒 390,
                        //           而 svW 是 358 —— 两者之差 32 就是嫌疑)
                        //   laidW = v47 注入的 ios15LastLaidOutW, 即行碎片**上一次
                        //           定型时用的排版宽**。装机后判据:
                        //             laidW=358 而 kvoW=390 ⇒ 碎片按 358 排过,
                        //             容器宽却被推回 390 —— 排版与视口脱钩,
                        //             gap 就是 97.6 那种空壳;
                        //             laidW=390 ⇒ 连排版都按脏宽定型了(v47 判据
                        //             压根没触发), 修法完全不同。
                        // ★cvW 直接用本 KVO 闭包已有的局部量 cvW(作用域内, 零新增读取)。
                        // ★laidW 走 v47 注入的类型级属性(同在
                        //   SelectableMarkdownTextView 内, 可读)。
                        //   —— 本轮实踩: 原先想用 v46 的只读 getter
                        //   `attV46CachedWidth`(log18 里 cachedW=389 ↔ tcW=390
                        //   完全同构 35/36, 是最直接的嫌疑), 但那个 getter 声明在
                        //   **TableAttachment 类**里(@2039), 而本探针在
                        //   **SelectableMarkdownTextView** 内 —— **跨类访问不到,
                        //   编译直接失败**。换成同类型的 laidW, 诊断力不减:
                        //   两者问的都是"碎片按哪个宽排的"。
                        // ★不新加读取语句, 免得探针自己引入新的布局读取扰动。
                        self.ios15V41CvW = cvW
                        self.ios15V46LaidOutW = self.ios15LastLaidOutW ?? -1
                        let _v49Now = CACurrentMediaTime()
                        if _v49Now - _V49W.last > 0.5 {
                            _V49W.last = _v49Now
                            _V49W.n &+= 1
                            let _v49SameTick = _V49W.v18Tick == _V49W.kvoTick
                            NSLog("[V49-WWRITER] v18W=%.1f kvoW=%.1f boundW=%.1f cvW=%.1f laidW=%.1f tcH=%.1f sameTick=%d dtick=%d usedH=%.1f needH=%.1f len=%d n=%u",
                                  _V49W.v18W, _V49W.kvoW, self.textContainer.bounds.width,
                                  self.ios15V41CvW, self.ios15V46LaidOutW,
                                  self.textContainer.size.height,
                                  _v49SameTick ? 1 : 0,
                                  Int(_V49W.kvoTick &- _V49W.v18Tick),
                                  self.layoutManager.usedRect(for: self.textContainer).height,
                                  self.ios15LastNeededH, self.textStorage.length, _V49W.n)
                        }
                        // [V49-WWRITER-KVO-END] 段结束标记 —— 见 v49 判据第 3 组。
"""


def fix_width_writer_diag_v49(t):
    """v49: 【纯诊断】钉死「谁把 textContainer.size.width 推回 390」。

    见本函数上方 V49 段的大段归因注释。核心结论三条:

    1. log18 证明 v48 **方向对但只治好轻文本** —— tcW=390 组里第一次出现
       gap=8.2 的正常帧(len=122), 而 len=1013(重文本+表格)仍然 97.6。
    2. 逐毫秒对齐: tcW 在 `00:07:42.678 → .679` 的 **1 毫秒**内从 358
       变成 390, 推宽者是 V46 附件测量链(`cachedW=389` 与 `tcW=390`
       完全同构 35/36)。而 v48 的钉宽在 v18 段, **早于**它跑完。
    3. 候选写入者三个且修法互相冲突 ⇒ 本版只探不打。

    探针落在两处(构成同帧差分):
      · v18 段末尾(layoutSubviews 内, **v48 钉宽之后**)—— 记 `v18W`
      · v41 KVO 抢帧器内 —— 记 `kvoW` + 完整来源指纹
    两处读数在同一 tick 内不同 ⇒ 中间有人写过。
    """
    # ---- 注入点 1: v48 的钉宽 if 之后 ----
    OLD1 = """            if _ios15WRegrabbed, abs(textContainer.size.width - _realW2) > 0.5 {
                textContainer.size.width = _realW2
            }"""
    if OLD1 not in t:
        raise RuntimeError(
            "fix_width_writer_diag_v49: 未找到 v48 的钉宽锚点 —— "
            "v48 结构变了, 必须更新 OLD1 后再发版")
    if t.count(OLD1) != 1:
        raise RuntimeError(
            "fix_width_writer_diag_v49: v48 钉宽锚点命中 %d 处(应恰为 1), "
            "定位会错" % t.count(OLD1))
    t = t.replace(OLD1, OLD1 + "\n" + _V49_TAIL.rstrip("\n"), 1)

    # ---- 注入点 2: v41 KVO 抢帧器内(V41-KVOHEIGHT 那条日志之后) ----
    # 选它是因为它是"v18 之后、SwiftUI pass 之外"的最后一个已知观测点,
    # 且 log18 显示 KVO 在 42.678 触发过 —— 正是推宽的那一毫秒。
    OLD2 = 'NSLog("[V41-KVOHEIGHT]'
    i2 = t.find(OLD2)
    if i2 < 0:
        raise RuntimeError(
            "fix_width_writer_diag_v49: 未找到 V41-KVOHEIGHT 日志锚点 —— "
            "v41 结构变了, 必须更新 OLD2 后再发版")
    if t.count(OLD2) != 1:
        raise RuntimeError(
            "fix_width_writer_diag_v49: V41-KVOHEIGHT 命中 %d 处(应恰为 1)"
            % t.count(OLD2))
    # 定位这条 NSLog 所在调用的结尾(`)` 后跟换行 + 缩进), 插在其后
    # ★插入点用**下游稳定锚点**, 不用"找这条 NSLog 的结尾"——
    #   V41-KVOHEIGHT 是多行格式串, 它的参数列表在下一行, 而 `t.find(");")`
    #   会越过整个补高块抓到 500 多行之后的某个 `);`(实测偏到行 6298,
    #   而日志在行 5730)。三版定位写法都栽在这里:
    #     · find(")", find("n=%u")) → 抓到 v44 那条日志(格式串末尾也是 n=%u)
    #     · find(");")            → 越过补高块抓到远处的括号
    #     · find 整块 OLD1         → 位置对但被前面的错误定位连带
    #   纪律: **锚点必须是下游的真实代码标记, 不能是"某个分隔符"**。
    #   这里用 v41 补高块结束的那两行(唯一的):
    #       }            ← 关掉 0.5s 节流块
    #       f = _hFix    ← 交棒给后续宽度修正
    #   插在 `f = _hFix` 之后 —— 此时 v41 的高度已补完, 是"v18 之后的
    #   最后一个已知观测点", 正是探针要对比的位置。
    #   裸串 "f = _hFix" 在文件里有**两处**: 一处是 v41 自己写的**注释**
    #   (「(`f = _hFix`), Swift 的 let 不可重新赋值」), 一处是真代码。
    #   裸串计数为 2 —— 与 v48 期间"锚点必须唯一"同一个教训, 这里补上前缀。
    _HANDOFF = "交棒: 下面的宽度修正必须基于新高度继续"
    i2end = t.find(_HANDOFF, i2)
    if i2end < 0:
        raise RuntimeError(
            "fix_width_writer_diag_v49: 未找到 v41 的交棒注释锚点 —— "
            "v41 结构变了, 必须更新 _HANDOFF 后再发版")
    # 从注释行推到该行末尾(下一个换行), 插在它之后
    i2end = t.find("\n", i2end)
    if i2end < 0:
        raise RuntimeError("fix_width_writer_diag_v49: 交棒行结尾定位失败")
    t = (t[:i2end + 1] + _V49_KVO.rstrip("\n") + "\n"
         + t[i2end + 1:].lstrip("\n"))

    # ---- 探针状态: 类型级 struct + 三个实例属性 ----
    # ★ struct 必须与实例属性**分开注入**: struct 是类型级声明, 属性是
    #   实例级, 前者是 `    struct`(4 空格)后者是 `    var`(4 空格),
    #   但 struct 内部成员是 8 空格 —— 混在一段里会写出坏的缩进层级。
    #   更要紧的是语义: struct 的 static 存储全进程单例(两个读点共享),
    #   属性是每实例一份(只做"最近一次读数"的可观测出口)。
    DECL = """    var ios15V18W: CGFloat = -1
    var ios15V41CvW: CGFloat = -1
    var ios15V46LaidOutW: CGFloat = -1
"""
    DECL_ANCHOR = "    /// [V47-WSTATE]"
    if DECL_ANCHOR not in t:
        raise RuntimeError(
            "fix_width_writer_diag_v49: 未找到 V47-WSTATE 属性声明锚点 —— "
            "v47 结构变了, 必须更新 DECL_ANCHOR 后再发版")
    t = t.replace(DECL_ANCHOR, _V49_STATE.rstrip("\n") + "\n" + DECL + DECL_ANCHOR, 1)

    # ---- 注入后自检 ----
    # 结构判据实现在本文件内(verify_width_writer_v49), 因为注入时就要用它
    # 把关; CI 侧另有一份 scripts/ios15_verify/verify_v49.py 做 70 条正向
    # 判据 + 另两项(作用域/重文本)。两份**互补不重叠**:
    #   本函数 = 注入时最小自检(结构 + 零赋值 + 加法), 缺它就没有"注入即拦"
    #   verify_v49.py = 装机前完整正向验证(70 条)
    #   scope_check_v49.py = 编译级作用域
    #   reverse_v49_heavy.py = 重文本专项
    # 纪律: **同一类判据只能有一处实现**(v48 的 run#37133557819 就是死于
    # 内联判据与 verify_v47.py 两份副本只改了一份)。上面四类**职责不重叠**,
    # 所以不构成副本。
    verify_width_writer_v49(t)
    return t


# v49 段禁写的标识 —— 纯诊断: 连宽度读取都不该改, 更不该写。
_V49_FORBIDDEN_LHS = frozenset((
    "textContainer", "size", "bounds", "frame", "origin", "layoutManager",
    "textStorage", "characterStorage", "cachedLayout", "rowHeights",
    "attV46CachedWidth", "attV46CachedTotalH", "ios15LastNeededH",
))

# v49 段右边界锚点 —— **由探针自己声明**, 不借外部标记。
# 【本轮实踩, 连踩两次】原先 v18 侧借 `// [IOS15-FIX-RELC v28]`、KVO 侧借
# `NSLog("[V44-TEXTFRAME]` 当右界, 两处都错:
#   · KVO 侧那个右界在下游 5000 行开外, 把 v41 自己的 `f = _hFix`、
#     v45 整段、v46 整段全吞进"探针段" ⇒ 段内零赋值判据必然误报
#     (报错: "KVO 侧 探针段内出现赋值 'f = _hFix'")。
#   · 借外部标记 = 判据与被注入代码的**下游邻居**耦合, 上游重排版本一改
#     邻居就误报, 而那段邻居跟本版毫无关系。
# 正确做法: 每段自带 END 标记, 判据只认自己这一对标记。段边界由注入函数
# 自己定义, 与文件其他部分零耦合。
_V49_END_V18 = "// [V49-WWRITER-V18-END]"
_V49_END_KVO = "// [V49-WWRITER-KVO-END]"


def verify_width_writer_v49(t):
    """校验 v49 探针段: 结构在位 + **段内零赋值**(纯诊断的硬底线)。"""
    import re as _re

    # ★两个注入点用**不同标记**, 按语义定位而不是按文件顺序 ——
    #   KVO 侧在行 ~5730、v18 侧在行 ~8093, **KVO 侧排在前面**。
    #   原先两处都叫 `// [V49-WWRITER]`, 判据用 `find` + `find(+1)` 取
    #   "第一个/第二个", 于是把 i1(KVO 侧)当成 v18 侧, 坐标判据必然误报
    #   (本轮实踩: "探针上游找不到 textContainer.size.width = _realW2")。
    #   教训与"锚点必须唯一"同源, 但更进一层: **唯一还不够, 还得能区分**。
    for tag, want in (("// [V49-WWRITER-V18]", 1), ("// [V49-WWRITER-KVO]", 1),
                      ("/// [V49-WSTATE]", 1),
                      (_V49_END_V18, 1), (_V49_END_KVO, 1)):
        if t.count(tag) != want:
            raise RuntimeError(
                "verify_width_writer_v49: 标记 %s 计数应为 %d, 实为 %d"
                % (tag, want, t.count(tag)))

    # ---- 1. 两段都在位 ----
    i1 = t.find("// [V49-WWRITER-V18]")
    i2 = t.find("// [V49-WWRITER-KVO]")
    if i1 < 0 or i2 < 0:
        raise RuntimeError(
            "verify_width_writer_v49: 两个探针注入点缺失(v18@%d kvo@%d)"
            % (i1, i2))
    # ★判据: 探针必须**紧邻在 v48 钉宽 if 的闭合花括号之后**。
    #
    # 【为什么不能用绝对坐标比较 —— 本轮连踩三次】
    #   V48-PIN 标记、v18 既有钳宽、v48 钉宽 if 三者的行序是:
    #       v18 既有钳宽(@425145) < V48-PIN(@426293) < v48 钉宽 if(@427269)
    #   而 v49 探针插在钉宽 if 之后(@427431)。于是:
    #     · 只比 PIN        → 探针 > PIN, 判据成立(这条碰巧对)
    #     · 只比裸串钉宽行  → 抓到 v18 那处(@425145 < 探针), 判据成立(也碰巧对)
    #     · 两者都比        → PIN(@426293) < 钉宽行(@425145) 不成立, **误报**
    #   三次错位都源于"从文件里找某个串的坐标, 再猜它属于哪一处"。
    #   正确做法: **只比"探针紧邻上游"** —— 以探针为起点往前找最近的
    #   `_realW2` 写入, 它必然是 v48 的钉宽行(v18 那处远在几千行之外)。
    #   这样判据与绝对行号无关, 上游重排版本也不会失效。
    _up = t.rfind(_V48_ALLOWED_WRITE, 0, i1)
    if _up < 0:
        raise RuntimeError(
            "verify_width_writer_v49: v18 侧探针上游找不到 %s —— "
            "探针必须插在 v48 钉宽 if 之后" % _V48_ALLOWED_WRITE)
    _gap = t[_up:i1]
    # 两者之间只允许有注释、空行与那个 if 的闭合花括号 —— 有代码就是插错位置了
    # _gap 的**正确形态**就是"那一行写入 + 闭合花括号":
    #     textContainer.size.width = _realW2
    # }
    # 所以剥注释去空白后必须恰为 `textContainer.size.width=_realW2}`。
    # 先前写成"只许 `}`"是判据写严了(本轮实踩, 自检当场抓出来)。
    _code = re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", _gap, flags=re.S))
    _code = re.sub(r"\s+", "", _code)
    _expect = re.sub(r"\s+", "", _V48_ALLOWED_WRITE + "}")
    if _code != _expect:
        raise RuntimeError(
            "verify_width_writer_v49: 探针与 v48 钉宽行之间夹了非预期内容 —— "
            "得到 %r, 应为 %r(探针必须紧邻钉宽 if 的闭合花括号)"
            % (_code[:60], _expect))

    # ---- 2. 探针状态声明齐全 ----
    # ★ struct 必须是**类型级**(4 空格缩进, 紧邻实例属性块之前)——
    #   函数内局部 struct 跨函数不可见, 两个读点分处 layoutSubviews 与
    #   KVO 闭包, 放在函数内编译直接失败(本轮实踩)。
    for k in ("var ios15V18W: CGFloat = -1",
              "var ios15V41CvW: CGFloat = -1",
              "var ios15V46LaidOutW: CGFloat = -1"):
        if k not in t:
            raise RuntimeError(
                "verify_width_writer_v49: 缺少探针状态属性 %r" % k)
    # 类型级 struct 的缩进层级必须正确: `    struct _V49W {`(4 空格)
    if "\n    struct _V49W {\n" not in t:
        raise RuntimeError(
            "verify_width_writer_v49: _V49W 必须声明为**类型级** struct"
            "(4 空格缩进) —— 函数内局部 struct 跨函数不可见, 会编译失败")
    # 段内不得再出现 struct 声明(否则就是误放回函数内了)
    for seg, name in (("v18 侧", _V49_TAIL), ("KVO 侧", _V49_KVO)):
        if "struct _V49W" in name:
            raise RuntimeError(
                "verify_width_writer_v49: ★%s 探针文本里含 struct _V49W 声明 —— "
                "它必须只出现在类型级声明段, 段内重复声明会遮蔽跨函数读取"
                % name)

    # ---- 3. ★段内零赋值(纯诊断的硬底线) ----
    # 两个段各自独立判。段内**只允许**对静态探针字段(_V49W.*)与
    # 探针状态属性(self.ios15V*)赋值 —— 那是探针自己的记忆位。
    # 任何对 textContainer / size / bounds / frame / layoutManager /
    # 缓存的赋值都算违规: 纯诊断一旦改了行为, 归因就作废
    # (分不清"修好了"还是"被诊断改坏了")。
    _end1 = t.find(_V49_END_V18, i1)
    _seg1 = t[i1:_end1] if _end1 > i1 else ""
    _end2 = t.find(_V49_END_KVO, i2)
    _seg2 = t[i2:_end2] if _end2 > i2 else ""
    if not (_seg1 and _seg2):
        raise RuntimeError(
            "verify_width_writer_v49: 探针段切片失败(seg1=%d seg2=%d 字符) —— "
            "END 标记必须在各自 START 标记下游" % (len(_seg1), len(_seg2)))

    for seg, name in ((_seg1, "v18 侧"), (_seg2, "KVO 侧")):
        code = _re.sub(r"//[^\n]*", "",
                       _re.sub(r"/\*.*?\*/", "", seg, flags=_re.S))
        for ln in code.split("\n"):
            m = _re.match(r"\s*(?:let\s+|var\s+)?([\w.]+)\s*(?:=|\+=|-=|\*=|/=)(?!=)", ln)
            if not m:
                continue
            tgt = m.group(1)
            last = tgt.split(".")[-1]
            # 允许: 探针自己的记忆位
            # ★按**最后一段**匹配, 与 reverse_v49_heavy.py 的 ALLOWED_EXACT
            #   保持同一口径 —— 两边不一致会互相打脸(本轮实踩: 专项里对
            #   `_V49W.v18W` 用完整串 startswith 判成越界, 误报)。
            if last in ("last", "n", "v18W", "v18Tick", "kvoW",
                        "kvoTick", "tick"):
                continue
            if last.startswith("ios15V"):
                continue
            if last.startswith("_v49"):
                continue
            raise RuntimeError(
                "verify_width_writer_v49: ★%s 探针段内出现赋值 %r —— "
                "本版是纯诊断, 一行写操作都会让归因作废"
                % (name, ln.strip()[:60]))

    # ---- 4. 段内零函数式写操作(invalidate*/setSize/computeLayout) ----
    for seg, name in ((_seg1, "v18 侧"), (_seg2, "KVO 侧")):
        code = _re.sub(r"//[^\n]*", "",
                       _re.sub(r"/\*.*?\*/", "", seg, flags=_re.S))
        for bad in ("invalidateLayout", "invalidateDisplay", "invalidateSize",
                    "ensureLayout", "setNeedsLayout", "setNeedsDisplay",
                    "setSize", "computeLayout", "invalidateCachedLayout"):
            if bad in code:
                raise RuntimeError(
                    "verify_width_writer_v49: ★%s 探针段内出现 %s —— "
                    "纯诊断不得触发任何布局或强制重排" % (name, bad))

    # ---- 5. 日志字段齐全(装机后靠这些字段定位) ----
    _need = ("v18W=", "kvoW=", "boundW=", "cvW=", "laidW=", "tcH=",
             "sameTick=", "dtick=", "usedH=", "needH=", "len=")
    for k in _need:
        if k not in _seg2:
            raise RuntimeError(
                "verify_width_writer_v49: KVO 侧日志缺字段 %r —— "
                "装机后靠它区分'同帧内被写'与'跨 pass 被写'" % k)
    # 格式串与实参个数必须配平: %-specifier 数 == 实参数, 否则装机即崩。
    # (纯诊断也不许崩 —— 崩了就拿不到日志, 整版白测。)
    _spec = len([m for m in _re.findall(r"%[-0-9.]*[a-z]", _seg2)])
    _arg = _seg2.count("%.1f") + _seg2.count("%d") + _seg2.count("%u")
    if _spec != _arg:
        raise RuntimeError(
            "verify_width_writer_v49: KVO 侧日志格式符数 %d 与实参数 %d 不配平"
            % (_spec, _arg))

    # ---- 6. 加法保留: v44/v45/v46/v47/v48 一个都不能少 ----
    # ★期望值必须**从干净上游跑完的完整链产物**上数, 不能凭印象写。
    #   【本轮实踩, 与 v48 那次"假故障"同源】原先凭印象写了
    #   V44=1/V45=1/V46=1, 实测基线是 2/2/4 —— 原因: 这些标记在产物里
    #   **各出现多次**: 一次是段首的 `// [Vn-...] 见函数 docstring` 标记,
    #   一次是段内 `NSLog("[Vn-...]`, 而 v46 另有第二处段(V46-ATTACH 出现 4 次)。
    #   拿半截产物或凭印象数, 判据就成了假故障 —— 上一次就是这样差点把
    #   v48 的真修法一起改坏。
    #   基线: /tmp/v48fin(干净上游 1.14 跑完 v48 全链)581354 字节。
    for tag, want in (("// [V48-PIN]", 1), ("// [V47-REWRAP]", 2),
                      ("/// [V47-WSTATE]", 1), ("[V44-TEXTFRAME]", 2),
                      ("[V45-TVHFIX]", 2), ("[V46-ATTACH]", 4)):
        if t.count(tag) != want:
            raise RuntimeError(
                "verify_width_writer_v49: 加法违例 %s 计数应为 %d, 实为 %d"
                % (tag, want, t.count(tag)))

    return True


# [V47-FORBIDDEN] v47 段内禁写的标识集合 —— 精确匹配, 不用子串。
#   用子串会踩坑: 既有变量 `_ios15WRegrabbed` 里含 "eight"(r-EIGHT-grabbed)。
#   这里只列**真正与高度有关**的名字, 且区分大小写形态。
_V47_FORBIDDEN_LHS = frozenset((
    "height", "Height", "h", "needH", "newHeight", "lastComputedHeight",
    "ios15LastNeededH", "frame", "_hf", "_needH", "_needH39", "size",
))


def verify_width_reflow_v47(t):
    """校验 v47 —— 独立成函数, 不只服务于注入。

    ★两条纪律:

      1. **只准碰宽度与重排, 不准碰高度。** v45 的 tvH 补高已实测有效
         (log15 109 条 V45-TVHFIX debt 全为 0.0), 任何 height 写入都会把
         那个成果推翻。所以本判据硬禁 v47 新增段里的一切高度赋值。
      2. **不准新增宽度写入点。** v13/v34 反复因抢宽引起闪屏与整体缩小,
         那是改钳宽翻的车。v47 只能在既有钳宽之后**加重排**; 若有人在 v47
         段里新增 `textContainer.size.width =` 就是回退到那条老路。

    判据顺序: 具体 → 宽泛, 标记计数放最后当总兜底(与 v44/v45/v46 同纪律)。
    """
    # ★两个标记必须分开(本轮实踩): 属性声明在文件前部(~281k), 代码注入段在
    #   ~420k。若都用 "// [V47-REWRAP]", find() 抓到的是**声明**而不是注入段,
    #   于是段切片从文件中部开始 → 把 v45 的赋值圈进来 → 误判"v47 写高度"。
    #   所以声明用 [V47-WSTATE], 代码段用 [V47-REWRAP], 各自唯一。
    MARK = "// [V47-REWRAP]"
    DECL_MARK = "/// [V47-WSTATE]"
    if t.count(MARK) < 1:
        raise RuntimeError("verify_width_reflow_v47: 未找到 V47-REWRAP 标记")
    if t.count('NSLog("[V47-REWRAP]') != 0:
        # v47 是修法不是诊断, 不该有日志; 万一有人加了日志说明想走诊断路线
        raise RuntimeError(
            "verify_width_reflow_v47: v47 是修法, 不得含诊断日志 —— "
            "归因已完成(log16), 纯诊断留给后续版本")

    # 1. 两处注入点都在
    if "if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {" not in t:
        raise RuntimeError(
            "verify_width_reflow_v47: 未找到重排判据(ios15LastLaidOutW 比对) —— "
            "v47 的核心是把重排条件从'此刻 tcW 是否偏了'换成'上次排版宽是否等于目标宽'")
    if "self.ios15LastLaidOutW = _realW2" not in t:
        raise RuntimeError(
            "verify_width_reflow_v47: 未找到排版宽回写 —— "
            "重排后必须记下本次宽度, 否则每帧都会重排(v13 卡死的老路)")

    # 2. 属性声明存在且是可选 CGFloat(初值 nil = 从未排版过)
    if "var ios15LastLaidOutW: CGFloat?" not in t:
        raise RuntimeError(
            "verify_width_reflow_v47: 未找到 ios15LastLaidOutW 声明 —— "
            "必须是 CGFloat? 而不是 CGFloat, 初值 nil 才表示'还没排过版'")

    # 3. ★位置: 必须紧跟既有钳宽之后、ensureLayout 之前/之后。
    #    判据: 重排判据里出现 _realW2(既有局部量), 而 _realW2 的定义在锚点里。
    #
    #    【锚点形态踩坑记录 —— 这条比看起来重要】本判据先后试过两个形态:
    #      · `let _realW2 = _realW`               ← **对的**
    #      · `let _realW2 = _realW` ← 错的
    # 起因是拿一份**只跑到 v43 就中断**的半截产物当基线, 里面 v43-A"就地改宽"
    # 刚把这一行改成 max(...) 而 v34 还没跑, 于是误以为形态变了, 把 OLD 锚点
    # 和判据一起改了 —— 结果完整链跑完(v34 又改回 _realW)反而找不到锚点。
    # 两次教训:
    #   1. **基线必须是从干净上游跑完的完整链产物**, 半截产物比错误基线更危险,
    #      因为它能自洽地通过本地验证。
    #   2. 中间态(任何两版之间)不是产物形态, 判据不能锚在中间态上。
    _i_w = t.find("let _realW2 = _realW")
    _i_chk = t.find("if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {")
    _i_set = t.find("self.ios15LastLaidOutW = _realW2")
    if min(_i_w, _i_chk, _i_set) < 0:
        raise RuntimeError("verify_width_reflow_v47: 注入点缺失")
    if not (_i_w < _i_chk < _i_set):
        raise RuntimeError(
            "verify_width_reflow_v47: 注入顺序错 —— 应为 _realW2 定义 -> 重排判据 -> "
            "排版宽回写(实际 %d/%d/%d)" % (_i_w, _i_chk, _i_set))

    # 4. ★硬禁: v47 **自己新增的行**里不得有高度写入(v45 成果保护)。
    #    ★判据范围必须精确到 v47 新增块, 不能整段扫 ——
    #    【踩坑记录(本轮实跑三轮)】前两版把 [V47 注入点, V42-LATCH-SET) 整段
    #    当作"v47 段", 结果连续误伤**源码既有**的合法代码:
    #      · `ios15LastNeededH = _needH`(v18 自己的, 不是 v45 的)
    #      · `textContainer.size.width = _realW2`(v18 既有钳宽)
    #    第一版还因 `"eight" in _lhs` 子串匹配误伤 `_ios15WRegrabbed`
    #    (r-EIGHT-grabbed)。教训: **既有代码不是本版的产物, 判据不能碰它**。
    #    这里改成: 只取 v47 两个标记之间的代码(标记是 v47 独有的)。
    _i_a = t.find(MARK)                       # 重排判据处的标记
    _i_b = t.find(MARK, _i_a + 1)             # 回写处的标记
    if _i_a < 0 or _i_b < 0:
        raise RuntimeError("verify_width_reflow_v47: V47 标记缺失")
    # 【v48 起必须收这个边界 —— 否则本函数会 RuntimeError】
    #   v48 恰恰**就是**在 v47 判据这一处补写容器宽(log17 实测: v47 只调
    #   invalidateLayout 而不写 textContainer.size.width, 于是 ensureLayout
    #   照着 390 重排, 治不了 117pt 空壳)。下面第 5 条硬禁段内出现
    #   `textContainer.size.width =`, 而段右边界原本止于
    #   `if _ios15WRegrabbed, textStorage.length > 0 {` —— v48-PIN 在那之前,
    #   于是 v48 的写入被算成 v47 的, 注入到 v48 时直接抛异常。
    #
    #   ★这是同一个病根的**第三份副本**: CI 断言 49(YAML 内联)、
    #   verify_v47.py、本函数。三处曾各写各的, 结果 run#37133557819 里
    #   前者被 CI 抓到, 后两者靠"CI 先在断言处失败"而侥幸没暴露。
    #   纪律: **一份判据只能有一处实现**; 后版扩展同一段代码时,
    #   前版的"纯度判据"要跟着收边界, 而不是删掉判据。
    _blk1_end = t.find("if _ios15WRegrabbed, textStorage.length > 0 {", _i_a)
    if "// [V48-PIN]" in t[_i_a:]:
        _blk1_end = min(_blk1_end, t.index("// [V48-PIN]", _i_a))
    _blk1 = t[_i_a:_blk1_end]
    # 第二块: 回写标记之后到 ios15LastNeededH 之前(v47 只加了回写)
    _i_end2 = t.find("ios15LastNeededH = _needH", _i_b)
    if _i_end2 < 0:
        _i_end2 = _i_b + 300
    _blk2 = t[_i_b:_i_end2]
    _code = _strip_swift_noise(_blk1) + "\n" + _strip_swift_noise(_blk2)
    # ★必须同时匹配**带点的赋值目标**(反向测试 B1 逼出来的漏放):
    #   `frame.size.height = 9999` 的赋值目标是 "frame.size.height", 正则若只取
    #   第一个 \w+ 会得到 "frame" —— 而 frame 在禁用集合里, 恰好也能拦住;
    #   但 `textView.size.height = 9999` 的第一个 \w+ 是 "textView"(不在集合),
    #   就会漏放。所以这里同时取**整条点号链**与**末段**, 任一命中即拦。
    for _ln in _code.split("\n"):
        _m = re.match(r"\s*([\w.]+)\s*(?:=|\+=|-=|\*=|/=)(?!=)\s*", _ln)
        if not _m:
            continue
        _target = _m.group(1)
        _lhs = _target.split(".")[-1]
        # ★必须用**精确的高度标识集合**, 不能用 "eight" 子串匹配 ——
        #   既有变量 `_ios15WRegrabbed` 里就含 eight(r-EIGHT-grabbed),
        #   子串匹配会把这个合法赋值误判成高度写入(本轮实踩)。
        if _lhs in _V47_FORBIDDEN_LHS or _target in _V47_FORBIDDEN_LHS:
            raise RuntimeError(
                "verify_width_reflow_v47: ★v47 新增行内出现高度写入 %r: %r "
                "—— v45 的 tvH 补高已实测有效(debt 全 0), v47 只碰宽度与重排"
                % (_lhs, _ln.strip()[:70]))
        if _lhs.startswith("_v47"):
            raise RuntimeError(
                "verify_width_reflow_v47: v47 新增行内出现局部赋值 %r —— "
                "v47 是修法, 局部计数器不属于本版职责" % (_lhs))

    # 5. ★硬禁: v47 新增行内不得再写宽度(回退到 v13/v34 的老路)
    #    同样只看 _code(v47 自己新增的两块), 不看既有钳宽。
    for _bad in ("textContainer.size.width =", "textContainer.size =",
                 "frame.size.width =", "bounds.size ="):
        if _bad in _code:
            raise RuntimeError(
                f"verify_width_reflow_v47: 段内出现宽度写入 {_bad!r} —— "
                "v47 只能在既有钳宽之后加重排; 新增宽度写入点是 v13/v34 "
                "闪屏与整体缩小事故的根因, 不得重犯")

    # 6. 重排调用签名必须与源码既有写法一致(v25-fix2 编译验证过的合法形式)
    if "layoutManager.invalidateLayout(forCharacterRange: NSMakeRange(0, textStorage.length), actualCharacterRange: nil)" not in t:
        raise RuntimeError(
            "verify_width_reflow_v47: invalidateLayout 签名与源码既有写法不一致 —— "
            "必须用 v25-fix2 编译验证过的 "
            "invalidateLayout(forCharacterRange:actualCharacterRange:)")

    # 7. 必须保留 v44/v45/v46(加法, 不是替换)
    for _keep in ('NSLog("[V44-TEXTFRAME]', 'NSLog("[V45-TVHFIX]',
                  'NSLog("[V46-ATTACH]'):
        if _keep not in t:
            raise RuntimeError(f"verify_width_reflow_v47: 必须保留 {_keep} —— v47 是加法")

    # 8. 全文花括号平衡(总兜底)
    _depth, _low = _brace_balance(t)
    if _depth != 0:
        raise RuntimeError(f"verify_width_reflow_v47: 花括号不平衡(净 {_depth:+d} 处)")
    if _low < 0:
        raise RuntimeError(f"verify_width_reflow_v47: 花括号中途变负(最深 {_low})")

    # 9. 标记计数放最后
    if t.count(MARK) != 2:
        raise RuntimeError(
            "verify_width_reflow_v47: V47-REWRAP 标记必须恰好 2 处(判据 + 回写), "
            "实际 %d 处" % t.count(MARK))
    if t.count(DECL_MARK) != 1:
        raise RuntimeError(
            "verify_width_reflow_v47: V47-WSTATE 声明标记必须恰好 1 处, "
            "实际 %d 处" % t.count(DECL_MARK))


def verify_textframe_v44(t):
    """校验 v44 诊断段 —— 独立成函数, 不只服务于注入。

    【为什么必须独立】第一版防御测试全军覆没(11条 sabotage 全部漏放), 原因:
    sabotage 之后又去调 `fix_diag_textframe_v44`, 而它会在锚点处**再注入一份
    崭新的、完好的**诊断(锚点 `f = _hFix` + 注释 + 闭合 注入后依然存在, 实测
    count=1), 校验随之通过 —— 等于每次都在测一份没被破坏的代码。
    把校验拆出来单独调, sabotage 才真正验得到。锚点失配类防御仍留在注入函数里。
    """
    # ---- 编译防御 ----
    # ★判据顺序有讲究(实跑踩出来的): **标记计数必须放最后当总兜底**。
    #   最初把它放第一位, 结果"字段缺失""裸块""混入写操作"这几条全部先被它拦下
    #   (报"标记数=2"), 各自的判据一次都没被执行到 —— 等于那些防御形同虚设,
    #   删掉标记计数它们就完全不生效。这与 v43 踩过的"判据被稀释"是同一类错误,
    #   只是方向相反: 那次是判据太宽, 这次是判据太严、抢在其他判据前面。
    #   所以顺序 = 具体 → 宽泛, 让每条防御报出它自己该报的原因。
    #   (同一次实跑还抓到测试脚本自己的假通过: sabotage 在 base 上替换 SEG,
    #    而 SEG 是从 injected 切出来的, base 里不存在 —— str.replace 原样返回,
    #    12 条 case 全退化成"校验未注入的 base", 报错像拦住了, 实则零判据被验到。)
    #
    # 0. 诊断段整段缺失。必须排在字段检查**之前**: 整段被删时字段当然也没了,
    #    报"缺少判据字段"等于让人去查一个根本不存在的东西, 方向误导。
    #    用 find 而非 index: 少一次裸 ValueError(run#371 教训)。
    _i_tfd0 = t.find("// [V44-TEXTFRAME] 见函数 docstring")
    if _i_tfd0 < 0:
        raise RuntimeError("verify_textframe_v44: 诊断段整段缺失")
    # 1. 三个判据字段一个都不能少, 少一个就有一条假设永远无法验证。
    for k in ("_tfdTvH = self.frame.height",
              "_tfdSvAfter = obj.frame.height",
              "_tfdUsed = self.layoutManager.usedRect(",
              "self.textContainer).height"):
        if k not in t:
            raise RuntimeError(f"verify_textframe_v44: 缺少判据字段 {k}")
    # 2. 必须用 do { } —— 裸块会被吸成 trailing closure, v42 首次推送就栽在这。
    #    【切片边界】必须切到 do 块的**闭合**而不是 NSLog( —— NSLog 的参数列表里
    #    也含 self. 引用(self.textContainer.size.width 等), 只切到 NSLog( 会把
    #    参数列表切掉, 让下一条判据误报"缺字段"。这是本函数实跑时真撞到的。
    #
    #    【为什么不能用固定字符窗口】第一版写的是"标记后 400 字符内必须出现
    #    do {", 结果正常产物直接误报: 标记与 do { 之间夹着 7 行中文注释
    #    (讲三个假设分别是什么), 实测 400 根本不够, 而这段注释还会随
    #    文档增删变长 —— 用字符数赌注释长度, 迟早再炸一次。
    #    改用**语义窗口**: 诊断段必须完整落在"补高 NSLog"与"// [V41-KVOPOST]"
    #    之间。这两端都是稳定锚点, 且正是诊断段该待的位置(见本函数第 5 条),
    #    窗口长度随代码自由伸缩也不会误判。
    if "// [V41-KVOPOST]" not in t:
        raise RuntimeError(
            "verify_textframe_v44: 找不到 // [V41-KVOPOST] 锚点 —— v41 未注入? "
            "v44 依赖 v41 的 KVO 块, 登记必须排在 v41 之后")
    _i_kvopost = t.index("// [V41-KVOPOST]")
    if _i_kvopost <= _i_tfd0:
        raise RuntimeError(
            f"verify_textframe_v44: // [V41-KVOPOST] 在诊断段之前 "
            f"(tfd@{_i_tfd0} post@{_i_kvopost}) —— 上游结构变了?")
    _win = t[_i_tfd0:_i_kvopost]
    _DO = chr(10) + "            do {"
    if _DO not in _win:
        raise RuntimeError(
            "verify_textframe_v44: 必须用 do { }(裸 { } 会被吸成 trailing closure 编译失败)")
    # 必须落在窗口**开头之后**, 否则 t.index 会向前命中更早的 do 块而假通过。
    _i_do = t.find(_DO, _i_tfd0)
    if not _i_tfd0 < _i_do < _i_kvopost:
        raise RuntimeError(
            f"verify_textframe_v44: do {{ 位置越界 (do@{_i_do} 窗口[{_i_tfd0},{_i_kvopost}])"
            " —— 诊断段被拆散了? 裸块被吸成 trailing closure?")
    # 同缩进的闭合 } 必须存在, 否则 do 块没关(或者被上游改动挪走了)。
    _i_close = t.find(chr(10) + "            }", _i_do)
    if _i_close < 0 or _i_close > _i_kvopost:
        raise RuntimeError(
            f"verify_textframe_v44: do 块缺同缩进闭合(找 {chr(10)}            }} 于 {_i_do} 之后)"
            " —— 上游结构变了, 或 do 块的 } 缩进被改动")
    seg = t[_i_do:_i_close]
    # 3. 闭包内引用 self 的成员必须带 self. —— 与 V42-GATE 同一个编译教训。
    for k in ("self.frame.height", "obj.frame.height", "self.layoutManager.usedRect(",
              "self.textContainer.size.width"):
        if k not in seg:
            raise RuntimeError(f"verify_textframe_v44: do块内必须显式用 {k}")
    # 4. ★纯诊断: 诊断块内绝不允许出现写操作。钉死这一点是本版存在的意义 ——
    #    v44 只加诊断, 装机结果才有归因价值(能区分"修好的"和"看着好的")。
    #    以后若有人顺手在这里补textView 高度, 行为改动会伪装成诊断, 那一版的
    #    结论全部作废。
    for forbidden in ("self.frame =", "self.ios15LastNeededH =", "self.ios15LatchedNeedH =",
                      "obj.frame =", "textContainer.size ="):
        if forbidden in seg:
            raise RuntimeError(
                f"verify_textframe_v44: v44 是**纯诊断**, 块内出现写操作 {forbidden} —— "
                "行为改动必须另起一版, 否则装机结果无法归因")
    # 5. ★诊断必须落在**补高之后**: 在补高之前打, svAfter 与 svH 是同一个值,
    #    假设 B(补高被挡掉)永远无法证伪。v43-B 第一版就栽在"插在写入之前"上。
    #
    #    【为什么不能直接 t.index】run#37118226923 就是死在这: 裸 ValueError
    #    只会说 "substring not found", 看到的人根本猜不到是**登记顺序**错了
    #    (v44 排在 v42 前面, 干净基线上 v42 那行还不存在)。凡是 index 可能落空的
    #    判据, 都要自己捕获并把"为什么会没有"写进消息。
    #    锚点串两种写法都接受: v42 注入的是 `self.ios15LastNeededH = _v42Need`,
    #    但若将来 v42 改成局部变量形式, 位置判据不该连坐崩掉。
    _NEED_ANCHORS = ("self.ios15LastNeededH = _v42Need",
                     "ios15LastNeededH = _v42Need")
    _i_need = -1
    for _a in _NEED_ANCHORS:
        if _a in t:
            _i_need = t.index(_a)
            break
    if _i_need < 0:
        raise RuntimeError(
            "verify_textframe_v44: 找不到补高赋值点(ios15LastNeededH = _v42Need) —— "
            "多半是 main() 里 v44 登记排在了 v42 **之前**: 干净上游基线上 v42 还没注入"
            "这行, v44 的位置判据必然落空(run#37118226923 的真实死因)")
    i_hit = t.find('NSLog("[V41-KVOHEIGHT]')
    i_tfd = _i_tfd0
    if i_hit < 0:
        raise RuntimeError(
            "verify_textframe_v44: 找不到 V41-KVOHEIGHT 补高日志 —— v41 未注入? "
            "v44 依赖 v41 的补高块, 登记必须排在 v41 之后")
    if not _i_need < i_hit < _i_tfd0:
        raise RuntimeError(
            "verify_textframe_v44: 诊断必须在补高之后 "
            f"(need@{_i_need} hit@{i_hit} tfd@{_i_tfd0}) —— 插在补高前则 svAfter 无意义")
    # 6. 节流周期必须与 V41-KVOPRE / V43-WIDTH 同为 0.5s, 三条日志才可并列对照。
    if "_tfdNow - _TfdLog.last > 0.5" not in t:
        raise RuntimeError("verify_textframe_v44: 诊断必须 0.5s 节流(与 V41-KVOPRE 同周期)")
    # 7. 标记必须是**唯一**的一次 NSLog —— 注释行里的同名字符串不算。
    #    (与 _v41_marks/_v42_marks 同一个教训: 模糊匹配会把注释算进去。)
    #    放最后当总兜底, 理由见本段开头的顺序说明。
    #    【Python 3.11 限制】f-string 表达式里不能出现反斜杠, 所以先把待查串
    #    算好再插进消息, 不能写成 f"{t.count('a\\\"b')}"。
    _tfd_mark = 'NSLog("[V44-TEXTFRAME]'
    _tfd_cnt = t.count(_tfd_mark)
    if _tfd_cnt != 1:
        raise RuntimeError(
            f"verify_textframe_v44: NSLog 标记数不符 (期望 1, 实际 {_tfd_cnt})")
    return t


def verify_tvh_debt_v45(t):
    """校验 v45 补高段 —— 独立成函数(与 v44 同一条纪律, 见该函数docstring)。

    ## 本版校验的核心判据: **只准动高度,不准碰宽度**

    v45 的整个安全性建立在"只写 size.height"上。宽度由 v18/v34 一族经
    ios15LastSaneSVFrame 精心维护, v13/v34 都因抢宽引起过闪屏/整体缩小。
    一旦 v45 的代码里出现 origin.x / size.width 的写入或改动, 就是在绕过
    那套状态机, 且装机后一旦闪屏将无法归因(是 v45 引起的还是老问题复发)。

    所以下面第 4 条是**硬禁**任何非 height 的 frame 改动, 而不只是"检查一下"。
    """
    # ---- 判据顺序: 具体 → 宽泛, 标记计数放最后当总兜底 ----
    # (与 verify_textframe_v44 完全同一个教训: 判据抢在前面会把其他判据
    #  全部稀释掉, 删掉标记计数它们就完全不生效。见该函数开头的说明。)
    #
    # 0. 整段缺失。排在字段检查之前: 整段被删时字段当然也没了, 报"缺字段"
    #    会让人去查一个根本不存在的东西, 方向误导。用 find 不用 index。
    _i_tvh = t.find("// [V45-TVHFIX] 补高**补到画字的那个视图上**")
    if _i_tvh < 0:
        raise RuntimeError("verify_tvh_debt_v45: 补高段整段缺失")
    # 1. 核心判据字段: 判据条件 + 写入 + 日志。
    for k in ("if _v42Need > 1, self.frame.size.height + 0.5 < _v42Need {",
              "_tvf.size.height = _v42Need",
              "self.frame = _tvf"):
        if k not in t:
            raise RuntimeError(f"verify_tvh_debt_v45: 缺少关键字段 {k}")
    # 2. 必须用 do { } —— 裸块会被吸成 trailing closure(v42 首次推送就栽这)。
    #    切片到 do 块的**闭合**, 不能切到 NSLog( : NSLog 参数列表里也含
    #    self. 引用, 只切到 NSLog( 会把参数切掉让下一条判据误报"缺字段"
    #    (v44 校验实跑时真撞到过这个坑)。
    #
    #    【为什么用语义窗口而非固定字符数】v44 第一版写的是"标记后 400 字符内
    #    必须出现 do {", 结果标记与 do { 之间夹着 7 行中文注释, 400 不够,
    #    直接误报正常产物。注释长度会随文档增删变长, 用字符数赌它迟早再炸。
    #    改用稳定锚点做窗口: 本段必须落在"V45 标记"与"V44 诊断标记"之间
    #    —— 那正是本段该待的位置(v41 补高段之后、诊断之前)。
    _MARK44 = "// [V44-TEXTFRAME] 见函数 docstring"
    if _MARK44 not in t:
        raise RuntimeError(
            "verify_tvh_debt_v45: 找不到 V44 诊断标记 —— v44 未注入? "
            "v45 的注入锚点依赖 v44 段, 登记必须排在 v44 之后")
    _i_44 = t.index(_MARK44)
    if _i_44 <= _i_tvh:
        raise RuntimeError(
            f"verify_tvh_debt_v45: V44 段在 v45 段之前 "
            f"(tvh@{_i_tvh} v44@{_i_44}) —— 上游结构变了?")
    _DO = chr(10) + "            do {"
    if _DO not in t[_i_tvh:_i_44]:
        raise RuntimeError(
            "verify_tvh_debt_v45: 必须用 do { }(裸 { } 会被吸成 trailing closure 编译失败)")
    _i_do = t.find(_DO, _i_tvh)
    if not _i_tvh < _i_do < _i_44:
        raise RuntimeError(
            f"verify_tvh_debt_v45: do {{ 位置越界 (do@{_i_do} 窗口[{_i_tvh},{_i_44}])"
            " —— 补高段被拆散了? 裸块被吸成 trailing closure?")
    # 6. do 块必须有同缩进闭合, 否则块没关(或者被上游改动挪走了)。
    #    ★这一条不只是"闭合存在" —— 反向测试 F1 实跑抓到: 在别处插一个
    #    永不闭合的函数, 块本身闭合完好, 前7 条判据**全部通过**, 编译才炸。
    #    所以必须在**全文**扫花括号平衡, 不能只盯着本块。
    _i_close = t.find(chr(10) + "            }", _i_do)
    if _i_close < 0 or _i_close > _i_44:
        raise RuntimeError(
            "verify_tvh_debt_v45: do 块缺同缩进闭合(找 "
            f"{chr(10)}            }} 于 {_i_do} 之后) —— 上游结构变了, 或闭合 }} 缩进被改动")
    # 全文花括号平衡(跳过行注释/块注释/字符串, 与正向脚本同一套扫描逻辑)。
    # 用手写状态机而非 t.count("{")==t.count("}") —— 后者会被注释里的大括号
    # 和字符串里的引号骗到。min_depth 也要查: 中途变负说明有孤立右括号,
    # 末尾相等也掩盖不了。
    _depth = 0
    _mind = 0
    _state = None
    _j = 0
    while _j < len(t):
        _c = t[_j]
        _nxt = t[_j + 1] if _j + 1 < len(t) else ""
        if _state is None:
            if _c == "/" and _nxt == "/":
                _state = "line"; _j += 2; continue
            if _c == "/" and _nxt == "*":
                _state = "block"; _j += 2; continue
            if _c == '"':
                _state = "str"; _j += 1; continue
            if _c == "{":
                _depth += 1
            elif _c == "}":
                _depth -= 1
                _mind = min(_mind, _depth)
            _j += 1
        elif _state == "line":
            if _c == chr(10):
                _state = None
            _j += 1
        elif _state == "block":
            if _c == "*" and _nxt == "/":
                _state = None; _j += 2
            else:
                _j += 1
        else:
            if _c == "\\":
                _j += 2
            elif _c == '"':
                _state = None; _j += 1
            else:
                _j += 1
    if _depth != 0 or _mind < 0:
        raise RuntimeError(
            f"verify_tvh_debt_v45: 花括号不平衡 (final={_depth}, min={_mind}) —— "
            "注入破坏了块结构, 会编译失败(反向测试 F1 抓到过这条缺失)")
    seg = t[_i_do:_i_close]
    # 3. 闭包内引用 self 的成员必须带 self. —— 与 V42-GATE 同一个编译教训
    #    (裸块被吸成 trailing closure 后, 块内裸引用会连锁报错)。
    for k in ("self.frame.size.height", "self.frame.size.width", "self.frame = _tvf"):
        if k not in seg:
            raise RuntimeError(f"verify_tvh_debt_v45: do 块内必须显式用 {k}")
    # 4. ★★硬禁: 块内除 size.height 外不得改动 frame 的任何其他维度。
    #    判据用"赋值目标"而不是"出现次数" —— 注释里提到 width 是允许的(本版
    #    注释就解释了为什么不碰宽度), 真正要禁的是**代码**改了它。
    #
    #    【bounds.size 也在禁列】反向测试 B4 实跑抓到: 只禁 frame 的三个维度时,
    #    块内改 `self.bounds.size.height` 能一路溜过。但 bounds 与 frame 在
    #    UITextView 上是两套东西 —— 改 bounds 会连带影响滚动内容与
    #    textContainer 的可见区域, 后果比改 frame 更难归因。所以一并禁死。
    for forbidden in ("size.width =", "origin.x =", "origin.y =",
                      "_tvf.size.width", "_tvf.origin", "bounds.size"):
        if forbidden in seg:
            raise RuntimeError(
                f"verify_tvh_debt_v45: ★只准动高度, 块内出现非高度改动 {forbidden} —— "
                "宽度由 v18/v34 经 ios15LastSaneSVFrame 维护, 在这里碰它会绕过"
                "那套状态机(v13/v34 都因抢宽引起过闪屏/整体缩小); bounds 另有一套"
                "语义(滚动内容/可见区域), 改它后果更难归因")
    # 5. ★必须落在 v41 补高**之后**: 在补高之前补self.frame 会拿到尚未补过
    #    高度的 sv 上下文, 且与 v41 的写入顺序纠缠, 装机后无法归因。
    #    用先判存在再 find —— 裸index 的 ValueError 只说"substring not found",
    #    看的人猜不到是**登记顺序**错了(run#37118226923 的真实死因)。
    _NEED_ANCHORS = ("self.ios15LastNeededH = _v42Need",
                     "ios15LastNeededH = _v42Need")
    _i_need = -1
    for _a in _NEED_ANCHORS:
        if _a in t:
            _i_need = t.index(_a)
            break
    if _i_need < 0:
        raise RuntimeError(
            "verify_tvh_debt_v45: 找不到补高赋值点(ios15LastNeededH = _v42Need) —— "
            "多半是 main() 里 v45 登记排在了 v42 **之前**: 干净上游基线上 v42 "
            "还没注入这行, 位置判据必然落空(run#37118226923 的真实死因)")
    i_hit = t.find('NSLog("[V41-KVOHEIGHT]')
    if i_hit < 0:
        raise RuntimeError(
            "verify_tvh_debt_v45: 找不到 V41-KVOHEIGHT 补高日志 —— v41 未注入? "
            "v45 依赖 v41 的补高块, 登记必须排在 v41 之后")
    if not _i_need < i_hit < _i_tvh:
        raise RuntimeError(
            "verify_tvh_debt_v45: 补高段必须在 v41 补高之后 "
            f"(need@{_i_need} hit@{i_hit} tvh@{_i_tvh}) —— "
            "插在补高前会与 v41 的写入顺序纠缠, 装机后无法归因")
    # 6. 节流周期必须为 0.5s —— 与 V41-KVOPRE / V44-TEXTFRAME 同周期,
    #    三条日志才能逐条并列对照(同一节流周期内看到的是同一帧)。
    if "_tvhNow - _TvhLog.last > 0.5" not in t:
        raise RuntimeError(
            "verify_tvh_debt_v45: 必须 0.5s 节流(与 V41-KVOPRE/V44-TEXTFRAME 同周期)")
    # 7. 标记必须是**唯一**的一次 NSLog —— 注释行里的同名字符串不算。
    #    (与 _v41_marks 同一个教训: 模糊匹配会把注释算进去。)
    #    放最后当总兜底, 理由见本段开头的顺序说明。
    _tvh_mark = 'NSLog("[V45-TVHFIX]'
    _tvh_cnt = t.count(_tvh_mark)
    if _tvh_cnt != 1:
        raise RuntimeError(
            f"verify_tvh_debt_v45: NSLog 标记数不符 (期望 1, 实际 {_tvh_cnt})")
    return t


def fix_table_width_clamp_v38b(t):
    """v38-B: 表格 attachmentBounds 宽度钳到真实容器宽 — 治"第 10 条泄漏"。

    日志实证 (minis-2026-10-03 6.log, v37 实测):
    ```
    04:55:02.961  [MarkdownRenderer] [RND] table#0 CACHE MISS rows=8 cols=2 → 重算
    04:55:02.965  [MarkdownRenderer] [RND] table#1 CACHE MISS rows=5 cols=2 → 重算
    04:55:03.027  [TextContainerGuard] short-circuited setSize: size=1096.0x1291.7
    04:55:06.729  [LEFT-CLIP-FIX v18] sv0=(16.0, 247.67, 1096.0, 1299.67) (svW=358.0 poll=true)
    ```

    v37 把 9 处 `width: lineFrag.width` 换成了 `ios15ClampProbeWidth(...)`,
    守卫是 `proposed >= 100_000` —— 它只拦 10M 哨兵值。**1096 不是哨兵值,
    是表格自己算出的"真实"内容宽**, 所以 v37 拦不住, 反而因为先钳了 lineFrag
    让 `usableWidth = floor(lineFrag.width) - 1` 拿到一个看起来合法的数, 照常返回。

    危害: 1096 进 superview.frame → TextKit 按 1096 排版(不换行) → 高度算小 →
    末行裁切(病根 A 的 448pt 欠账即由此而来); 同时每帧拉锯 = 终端框卡顿。

    修法: 在表格 attachmentBounds 出口再钳一道 —— 任何 > 真实容器宽的返回宽度
    都压回真实容器宽。与 v37 的区别: v37 拦"哨兵值", v38-B 拦"合法但超宽的值"。
    两者叠加后表格不可能再吐出超宽。
    """
    if "V38B-TABLEWIDTH" in t:
        return t

    # 表格 returnWidth 的最终出口(v28 改过的那行), 已有 v28 的 min(...)
    OLD = """        let returnWidth = isOversizedProbe
            ? min(clampedWidth, (containerRealWidth ?? lastRealWidth ?? Self.narrowestRealWidth))
            : usableWidth"""
    if OLD not in t:
        raise RuntimeError("fix_table_width_clamp_v38b: 未命中 v28 returnWidth 锚点 (上游结构变了?)")

    NEW = """        // [V38B-TABLEWIDTH] 表格返回宽的最终出口再钳一道。
        //
        // v37 只拦 >= 100_000 的 10M 哨兵值; 但表格在**非 probe** 路径下按
        // usableWidth = floor(lineFrag.width) - 1 自行算宽, 得到一个"看起来合法"
        // 的超宽值 —— minis-2026-10-03 6.log 实测 1096 (= 表格真实内容宽,
        // 不是哨兵值, 所以 v37 的守卫拦不住)。它进 superview.frame 后:
        //   TextKit 按 1096 排版不换行 → 高度算小 → 末行被裁 448pt (病根 A);
        //   每帧超宽↔正常宽拉锯 → 终端框卡顿 (病根 C)。
        //
        // 这里把上限从"哨兵值阈值"改成"真实容器宽": 表格是块级内容, 本就该按
        // 容器宽排版, 任何超过容器宽的返回值都是错的(容器内放不下)。
        // 正常路径 usableWidth <= containerRealWidth 时 max() 取原值, 行为不变。
        let _v38Cap: CGFloat = containerRealWidth ?? lastRealWidth ?? Self.narrowestRealWidth
        let returnWidth = min(usableWidth, max(1, _v38Cap))"""
    t = t.replace(OLD, NEW, 1)
    return t


def fix_setsize_storm_clamp_v38c(t):
    """v38-C: setSize 风暴收敛 — 治"终端框卡一下才显示画面" + "长文本卡字"。

    日志实证 (minis-2026-10-03 6.log, v37 实测):
    ```
    [TextContainerGuard] short-circuited setSize: size=358.0x100000.0 tick=9858 repeatThisTick=3 totalShortCircuits=2849
    [TextContainerGuard] short-circuited setSize: size=1096.0x1291.7 tick=9844 repeatThisTick=2 totalShortCircuits=2785
    [TextContainerGuard] short-circuited setSize: REJECT-NAN-INF-NEG size=0.0x-16.0 total=2881
    ```
    统计: setSize 风暴 167 次, 其中 **358.0x100000.0 独占 87 次(最高频)**;
    totalShortCircuits 累计 **2913**; 另有 28 次 0.0x-16.0 负高度。
    tick 范围 1586 ~ 12402, 横跨整个会话 = 不是单点爆发, 是持续占用主线程。

    为什么现有守卫拦不住 100000:
      kMaxContainerHeight = 1e5 正是 100000, 钳位是 `<=` 边界 → 100000 恰好**放行**;
      随后熔断只丢"同 tick 同尺寸重复", 而这些调用**跨 tick 尺寸相同**,
      于是每个新 tick 都重新初始化、重新放行 → 每个 tick 真跑一次 CoreText
      在 358x100000 上排版。熔断形同虚设, 87 次每次都真干活。

    为什么 100000 一定是错的:
      1. 它是 intrinsic-size 探测的哨兵值(与 v37 处理的 lineFrag.width=10M 同源),
         目的只是让 TextKit 报出"我不约束高度", 不是一个真实排版需求;
      2. 真实气泡最高 ~1748pt(v37 日志实测的最大 cell 高), 100000 是它的 57 倍;
      3. 按 100000 高排版出来的结果, TextKit 会认为"下方还有 98000pt 空白",
         usedRect / 高度回报都不可信 —— 这正是 v25 拿它测高时"布局永不收敛"的老问题。

    修法: 在有限性检查**之后**加一道"探测高度"识别 —— 高度 >= kProbeHeightFloor
    (实测校准为 3000pt, 见下方【v39 实测修正】) 一律压到 kProbeHeightCeiling
    之下的合理值。这样:
      - 87 次 100000 探测变成 0 次(直接落进收敛值), CoreText 调用量降一个数量级;
      - 真实的 358x550.9 / 358x901.3 等尺寸完全不受影响(远低于 3000);
      - 高度回报不再被 98000pt 假空白污染, 末行测高更准(与病根 A 互补)。

    为什么不动 kMaxContainerHeight: 它是 v26 反复验证过的值, 注释明确写了
    "不要在派生的容器尺寸上和 UIKit 对抗, 要修就修产生它的 frame 源头"。
    本补丁正是"修源头"——把哨兵探测在源头识别出来, 而不是压低上限。
    """
    if "V38C-PROBEH" in t:
        return t

    # 锚点: 有限性检查块之前的 kMaxContainerHeight 钳位 (v26 注入的原生代码)
    ANCHOR = """    if (newSize.width > 1e5) newSize.width = 1e5;"""
    if ANCHOR not in t:
        raise RuntimeError("fix_setsize_storm_clamp_v38c: 未找到宽度 1e5 钳位锚点 (上游结构变了?)")

    NEW = """    // [V38C-PROBEH] intrinsic 探测哨兵高度收敛。
    //
    // 背景 (minis-2026-10-03 6.log, v37 实测): setSize: size=358.0x100000.0
    // 出现 87 次(最高频), totalShortCircuits 累计 2913, tick 横跨 1586~12402。
    // 根因: kMaxContainerHeight 恰好 = 1e5 = 100000, 而这里是 `<=` 边界 → 100000
    // **恰好放行**; 熔断只丢"同 tick 同尺寸", 这些调用跨 tick 尺寸相同 → 每个
    // 新 tick 重新初始化并真跑一次 CoreText 在 358x100000 上排版, 熔断形同虚设。
    //
    // 100000 一定是错的: 它是 intrinsic 探测的哨兵值(与 v37 处理的 lineFrag.width
    // = 10M 同源), 只想让 TextKit 报"我不约束高度"; 真实气泡最高 ~1748pt
    // (同日志实测 cell 高上限), 100000 是它的 57 倍。按 100000 高排版后 TextKit
    // 认为下方还有 ~98000pt 假空白, usedRect/高度回报都不可信。
    //
    // 修法: 高度 >= 3000 判定为探测哨兵, 压到 2000。
    //
    // 【v39 实测修正】初版取 8000/4000 过于保守: log7 显示 4000 反而成了新的最高频
    // (358x4000 × 131 次), 因为 4000 仍远超真实需求。log7 实测真实气泡最高只有
    // **901.3pt**(FIRST-MEASURE newH 与 needH 双向确认), 3000 已有 3.3× 余量,
    // 2000 也有 2.2× 余量。既保持"真实尺寸零影响", 又能把哨兵排版成本再降一半。
    // 哨兵本身不丢弃(下游需要它做 max-width/高度发现), 只是不再让 CoreText
    // 在十万点高度上真的排版。
    //
    // 【v40 实测: 阈值维持 3000/2000 不动, 不能收紧】
    // log8 看似"2000 成了最高频 x221"支持收紧, 但 FIRST-MEASURE 的 newH 实证
    // **真实气泡最高 2002.3pt**, 且 setSize 里真实尺寸已出现 1994.3 / 1863.0 / 1799.0
    // —— 它们紧贴 2000。若收到 1200/800, 这些**真实排版会被误判成哨兵并压掉**,
    // 直接制造一轮新的裁字(比现在更隐蔽, 因为只在长文本出现)。
    // 结论: 2000 不是"新风暴源"而是"真实上限", 221 次命中恰恰说明真实内容这么高。
    // 风暴的真正解法是消掉哨兵**探测行为**, 而不是压低哨兵值的上限 ——
    // 那属于 v25/v26 测高链的职责, 不在哨兵钳位这一层。
    const CGFloat kProbeHeightFloor = 3000.0;
    const CGFloat kProbeHeightCeiling = 2000.0;
    if (newSize.height >= kProbeHeightFloor) {
        if (gProbeHeightCount == 0) {
            NSLog(@"[TextContainerGuard] [V38C] probe-height %.0f -> %.0f "
                  @"container=%p",
                  newSize.height, kProbeHeightCeiling,
                  (__bridge void *)self);
        }
        gProbeHeightCount += 1;
        newSize.height = kProbeHeightCeiling;
    }
    if (newSize.width > 1e5) newSize.width = 1e5;"""
    t = t.replace(ANCHOR, NEW, 1)

    # 声明计数器 (放在 kMaxContainerHeight 定义之后)
    DECL_ANCHOR = "static const CGFloat kMaxContainerHeight = 1e5;"
    if DECL_ANCHOR not in t:
        raise RuntimeError("fix_setsize_storm_clamp_v38c: 未找到 kMaxContainerHeight 定义锚点")
    t = t.replace(DECL_ANCHOR, DECL_ANCHOR + """
// [V38C-PROBEH] 被识别为 intrinsic 哨兵的 setSize 累计次数 (诊断用)。
static NSUInteger gProbeHeightCount = 0;""", 1)

    if t.count("V38C-PROBEH") != 2:
        raise RuntimeError(f"fix_setsize_storm_clamp_v38c: 标记数不符 (期望 2, 实际 {t.count('V38C-PROBEH')})")
    return t


def fix_inputbar_kick(t):
    """v30-C: 输入栏假死自愈 — 治"键盘弹出后底部留白无法打字"。

    log13 实证: [InputBarHealth] STALLED 两次 (18:30:26 / 18:30:30), 直到
    18:32:25 才自愈 — 2 分钟无法打字。上游自己注释承认唯一疗法是"退出会话
    重进"(重建 composer host), 探针却只打日志不行动。

    修法: 探针确认 900ms 无 geometry 回调后, 就地执行用户的手动疗法 —
    重置种子 (didSeedInputBarHeight=false) + bump composer 子树的 .id 身份
    → SwiftUI 重建全新 hosting 视图 → onGeometryChange 恢复回调 → 输入栏
    复活。草稿文本存于 vm.inputText (ViewModel), 重建不丢草稿。
    仅在非语音、非编辑态触发, 避免打断语音转写。
    """
    if "V30-INPUTBAR-KICK" in t:
        return t
    OLD_STATE = "    @State private var inputBarHealthProbe: Task<Void, Never>?"
    NEW_STATE = """    @State private var inputBarHealthProbe: Task<Void, Never>?
    // [V30-INPUTBAR-KICK] STALLED 自愈: bump 此值重建 composer 子树身份
    @State private var composerRebuildTick: Int = 0"""
    OLD_ID = """            .onGeometryChange15(for: CGRect.self) { proxy in
                proxy.frame(in: .global)"""
    NEW_ID = """            // [V30-INPUTBAR-KICK] composer 死亡自愈的重建开关: tick 变化
            // 即换 identity → SwiftUI 重建 hosting 视图 (等价退出重进会话)。
            .id(composerRebuildTick)
            .onGeometryChange15(for: CGRect.self) { proxy in
                proxy.frame(in: .global)"""
    OLD_STALL = """                    AppLogger(category: "InputBarLayout").error(_stallMsg)"""
    NEW_STALL = """                    AppLogger(category: "InputBarLayout").error(_stallMsg)
                    // [V30-INPUTBAR-KICK] 不再只报错等待用户退出重进 — 就地重建:
                    // 重置种子 + bump .id, composer host 复活后 geometry 回调
                    // 恢复, 种子重新落地。草稿在 vm.inputText, 重建不丢。
                    if !voiceInputActive && !voiceVM.isEditingTranscript {
                        didSeedInputBarHeight = false
                        composerRebuildTick &+= 1
                        AppLogger(category: "InputBarLayout").error("[InputBarHealth][V30-KICK] rebuilding composer host (tick=\\(composerRebuildTick)) — draft preserved in vm.inputText")
                    }"""
    if OLD_STATE not in t or OLD_ID not in t or OLD_STALL not in t:
        print("   [fix_inputbar_kick] 锚点未命中, 跳过")
        return t
    t = t.replace(OLD_STATE, NEW_STATE, 1)
    t = t.replace(OLD_ID, NEW_ID, 1)
    return t.replace(OLD_STALL, NEW_STALL, 1)


def main():
    print("== iOS 15 兜底修复 v2 (ROOT=%s) ==" % ROOT)
    print("-- 文件指纹/结构自检 --")
    for rel in ("Views/Providers/UnifiedModelPicker.swift",
                "Views/Chat/HelperSheet.swift", "MinisApp.swift"):
        p = os.path.join(ROOT, rel)
        if os.path.isfile(p):
            print("   %-46s %d bytes" % (rel, os.path.getsize(p)))

    edit("Views/Providers/UnifiedModelPicker.swift", fix_unified_model_picker, "Duration/sleep/toolbar")
    edit("Agent/Intents/ModelSelectionEntity.swift", strip_lsr_calls, "LSR -> 插值字面量")
    edit("NativeOffloads/AlarmOffloadBridge.swift", strip_lsr_calls, "LSR -> 插值字面量")
    edit("Views/Chat/HelperSheet.swift", fix_helper_transcript_style, "类型@available + 调用点兜底")
    edit("Views/ContentView.swift", fix_notification_nav_store, "深链垫片注入本文件")
    edit("MinisApp.swift", fix_minis_app, "守卫 iOS16 调用 + 撤 fileProviderDomain 标注")
    edit("AppDelegate.swift", fix_app_delegate, "守卫 ShortcutNotificationDelegate")
    edit("Agent/Jobs/HelperRunner.swift", fix_helper_runner, "内部守卫 extractResponseText")
    edit("Agent/Jobs/ScheduledJobRunner.swift", fix_scheduled_job_runner, "守卫 ShortcutNotification")
    edit("Providers/Voice/VoiceProviderResolver.swift", fix_voice_provider_resolver, "guard iOS17")
    edit("Providers/Voice/SystemVoiceCatalog.swift", fix_system_voice_catalog, "languageCode 可选链")
    edit("Views/Chat/ChatInputBar.swift", fix_chat_input_bar, "补 Alignment vertical:")
    edit("Views/Providers/AddProviderView.swift", fix_login_sheet_guards, "登录 Sheet 守卫")
    edit("Views/Providers/ProviderInstanceDetailView.swift", fix_login_sheet_guards, "登录 Sheet 守卫")
    edit("Shared/LoggingManager.swift", fix_ish_verbose_trace, "ish_set_verbose_trace 补桩")
    edit("Views/Settings/MemoryManagementView.swift", fix_force_sync_memory, "forceSyncMemory 调用点守卫")
    edit("Views/Chat/AIChatView.swift", fix_aichat_view, "拆分超长字符串插值")
    edit_glob("**/iOS15Compat.swift", fix_compat_shim, "兼容层 PhotosPickerItem.supportedContentTypes: [Any]->[UTType]")
    edit_glob("**/iOS15Compat.swift", inject_geom_backport, "注入 onGeometryChange 回填实现")
    edit_glob("**/iOS15Compat.swift", fix_hosting_config_shim, "UIHostingConfiguration 替身补系统LayoutSizeFitting (自排版)")
    edit_glob("**/iOS15Compat.swift", fix_hosting_content_maxwidth, "v22: SwiftUI rootView 设 maxWidth (压住超宽理想宽 → 根除污染帧/闪字/空白)")
    edit_glob("**/iOS15Compat.swift", fix_hosting_view_width, "v24: hosting 视图硬钉宽度=可用宽+裁切溢出, 根除 730/100000 超宽气泡(字不显示/空白/闪字)")
    edit("ShareExtension/ShareViewController.swift", fix_share_extension_timeout, "分享扩展加 8s 超时兜底 (防永久挂住)")
    edit("Shared/SharedContainerStore.swift", fix_share_store, "PendingShare 双通道存储 (UserDefaults + 共享容器文件)")
    edit("Agent/MessageList/MessageListLayout.swift", fix_message_list_defer, "iOS15: 大幅缩小(>50pt)修正立即生效, 消黑块虚高")
    edit("Minis.xcodeproj/project.pbxproj", fix_widget_activitykit, "Widget 弱链接 ActivityKit + AppIntents (iOS15.5 无这两个框架, dyld 崩)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_markdown_measure_width, "iOS15: 测量宽度钳制到集合视图宽度, 消正文错位/裁切")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_markdown_render_width, "iOS15: 渲染端 frame/偏移钳制 + cell 自排版提议宽度钳制, 消正文错位(第二轮)")
    edit("Agent/MessageList/MessageListInfrastructure.swift", fix_markdown_render_width, "iOS15: cell 自排版提议宽度入口钳制")
    edit("Agent/MessageList/MessageListInfrastructure.swift", fix_markdown_layout_reconcile, "iOS15: TextKit 高度兜底, 修末行裁切 + 收敛 FIRST-MEASURE 死循环")
    # ---- v4: setSize 风暴熔断 + 有限高度 + 代码块 widthTracksTextView + 左裁字诊断 ----
    edit("Shared/NSTextContainerSetSizeGuard.m", fix_textcontainer_guard_stormbreaker, "v4: setSize 风暴熔断(同tick>40次锁定) + 容器高度上限1e7→1e5, 斩断 CoreText fillLayoutHole 12s 卡死")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_code_textview_widthtrack, "v4: codeTextView 关 widthTracksTextView 并固定容器宽, 消代码块 589.3x17.3 重排风暴")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_clip_v3_property, "v12: 记录最后正常容器帧属性 (superview 污染精确还原)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_left_clip_diag_superview, "v5: 老会话双边裁字修复 — 渲染端容器宽度钳回+强制重排 (原 v4 仅诊断)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_defer_large_shrink, "v5: 大幅收缩(-100pt)修正立即生效, 消回复后大片空白 (控制台输出折叠卡片欠账数秒)")
    edit("Agent/Markdown/MinisMarkdownParser.swift", fix_markdown_table_extension, "v27: iOS15 启用 cmark-gfm table 扩展 (上游 else 分支漏 table, 表格整段降级为巨型单行纯文本 → 撑爆测量宽 → 高度振荡跳字)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_table_probe_width, "v28: 表格 probe 返回宽 32768 钳到真实容器宽 (iOS15 superview 被撑爆 → 白色巨块盖住内容)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_probe_width_global_clamp_v37, "v37: 9 处 attachmentBounds 泄漏路径统一钳住 probe 宽 (sv0 撑到 817/1077/100000 → 每帧拉锯卡顿 + 末行裁切)")
    # ---- v38: 三条独立病根, 根因不同分层修, 互不干扰 ----
    edit("Views/Chat/SelectableMarkdownView.swift", fix_stream_end_force_remeasure_v38a, "v38-A: 高度欠账自愈重测 — 治'末行整段不显示'(supervisor高 1299.67 vs needH 1748, 差 448pt 被裁; v18 改frame 赢不了布局 pass, 改走 invalidateCellSizeIfNeeded 提交诉求)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_table_width_clamp_v38b, "v38-B: 表格 attachmentBounds 返回宽钳到真实容器宽 (第 10 条泄漏: 1096 不是哨兵值, v37 的 >=100000 守卫拦不住)")
    edit("Shared/NSTextContainerSetSizeGuard.m", fix_setsize_storm_clamp_v38c, "v38-C: intrinsic 哨兵高度 100000 收敛到 4000 (358x100000 独占 87 次最高频风暴 → 终端框卡顿 + 长文本卡字)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_framefix_height_clamp_v39, "v39: 帧同步补上高度 — 治'字显示不全/排版不对'(v23 帧同步只修宽度不修高度, 每帧把 v18 撑好的高度改回去 → svH 恒为 needH 的 0.50~0.74, 37/37)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_framefix_height_unconditional_v40, "v40: 高度补齐挪出 polluted 分支 — 治'块重叠/字只剩一半'(v39 实测: textView 自身 frameH==needH 已 52/52 全对, 但 superview 52/52 仍欠 23.7~476pt。根因: polluted 判据只看宽度, 宽度修好后早退, v39 的高度代码一行没跑 → 宽度修好反而挡住了高度)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_kvo_height_clamp_v41, "v41: KVO 抢帧器补高度 — 治'字只剩一半/终端框不接结果'(推翻 v39/v40 的诊断: log9 同一毫秒同一 layoutSubviews 内 DIAG2 读到 358x2000.33 而开头快照是 100000x1455.33 → v18+v40 在 pass 内**确实修好了**, 欠账是 pass 结束后 SwiftUI 写回的。真凶: KVO 抢帧器只修x/width 从不写高度, 且 polluted 判据只看宽度 → '宽度正常+高度欠账'的帧被 if !polluted { return } 放过 → 末行被裁。v41: KVO 内无条件补高度 + polluted 增加高度维度 + 提交前兜底 + pass 末尾 V41-DEBT 回写侦测)")
    # ---- v43: 两个独立根因分开治(用户实测: "只有第一段卡" + "终端框还是卡画面") ----
    edit("Agent/MessageList/MessageListLayout.swift", fix_burst_reflow_v43, "v43-B: 涌入型突增的重排节流(250ms/idx) — 治'终端框卡一下才显示画面'(log11: shell_execute 输出 1.08 秒涌入 7 行表格, idx=14 连续 5 次 INVALIDATE 29→159→303→408→518→742, 对应 ReflowGap re-flows=6 全日志最高。根因: shouldInvalidate=delta>2 全放行, 上游那个 delta>100 只是**日志**阈值不是判定阈值) + 治字被裁的宽度不同源在 SelectableMarkdownView 侧 v43-A")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_needh_latch_v42, "v42: 需求高度闩锁 + KVO 兜底自测 — 治'最后一段字卡住'(v41 实测: KVO 94 次触发里**77 次(82%) needH=0**, 补齐条件 needH>1 直接跳过 → superview 卡在 1123.7/1006.0 恒定不变(25次同值), 末行持续被裁。根因: ios15LastNeededH 唯一赋值点在 layoutSubviews 第7618 行那个 `if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1` 内部, 三道门任一不满足就永远是 0; 而 KVO 抢帧器**不在这三道门里** → '抢帧器正常工作, 测量链没跟上'。v42: 闩锁改为**带键精确缓存**(长度/宽/hash, 不用 max——max 会在视图复用时把新短文本撑到旧高度造出大片空白) + KVO 里键不符时自测兜底(不经过那三道门) + V42-GATE 打在三道门之前(区分哪一道没通) + V42-LATCH/V42-MISS 区分缓存命中与自测)【v43-A 已就地改宽: 键与自测统一用抢回净宽 max(200,cvW-32), 见函数内 V43-NETW/V43-LATCHW】")
    # ---- v44: 纯诊断, 不改行为 ----
    # ★★必须排在 v42 **之后** —— 这是 CI run#37118226923 失败的直接原因。
    #   v44 的注入锚点与位置判据都依赖 v42 注入的那行
    #   `self.ios15LastNeededH = _v42Need`。第一次登记时把 v44 放在了 v42 前面,
    #   CI 从干净上游跑, v44 先执行 -> 那行还不存在 -> verify 里
    #   t.index("self.ios15LastNeededH = _v42Need") 抛 ValueError, 整个
    #   ios15_fallback 崩在第三阶段, 编译/打包全部没跑。
    #   【为什么本地全绿】本地验证用的是 /tmp/ci_v43c —— 那是 v43 完整流水线
    #   的产物, v42 **早就被打过了**, 所以无论登记顺序如何都找得到锚点。
    #   用旧产物当基线, 恰好掩盖了"顺序依赖"这类只在干净基线上才暴露的 bug。
    #   ⇒ 往后凡是"依赖前序补丁产物"的注入, 登记顺序本身就是判据, 必须验。
    #
    # log12 装机实测把 v43-A 的"宽度同源"前提直接推翻: 143 条 V43-WIDTH 里
    # dh 有 29 条非 0 且**会正负翻转**(18:06:12 dh=-191.3 净宽反而更矮,
    # 18:17:11 dh=+89.7 净宽更高)。同源的话 dh 应恒为 0, 说明还有第三条测量链。
    # 同时 V41 补高循环跑到 n=138 永不收敛(debt 恒定 156.3/447.7)。
    # v41/v42/v43 三轮都在猜"高度够不够", 全部猜错, 所以这一版**只测不改**:
    # 一条 V44-TEXTFRAME 把三个候选根因一次打完, 装机结果才有归因价值。
    edit("Views/Chat/SelectableMarkdownView.swift", fix_diag_textframe_v44, "v44: 【纯诊断, 不改任何行为】V44-TEXTFRAME — 治'终端框内容显示不全/字卡一半'的归因版。log12 硬证据: (1) v43-A '宽度同源'假设被推翻, dh 会正负翻转, 存在第三条测量链; (2) V41 补高循环 n=138 永不收敛, debt 恒在 156.3/447.7; (3) V41-KVOPRE 抓的是**superview**, 而画字的是 UITextView 自己, 补 superview 可能补不到画字的那个。一条日志同时测三个假设: tvH(UITextView 自身高) vs needH → 假设A 渲染视图自己矮了没人补; svAfter(补高**立刻回读**) vs needH → 假设B 补高被 ios15KvoFixing 重入挡掉(v41 补完从不回读, 这条至今无日志可答); usedH(TextKit usedRect 真实占用) vs needH → 假设C 表格/代码块 attachment bounds 没进排版导致 needH 虚高。0.5s 节流与 V41-KVOPRE/V43-WIDTH 同周期以便并列对照; 校验函数硬禁块内任何写操作, 行为改动必须另起一版。★登记必须排在 v42 之后(锚点依赖 v42 注入的赋值点, run#37118226923 就是栽在这)")
    # ---- v45: 补高补到画字的那个视图上(行为版, 归因已完成) ----
    # ★登记必须排在 v42 与 v44 **之后**:
    #   - 排在 v42 后: 位置判据依赖 v42 注入的 `self.ios15LastNeededH = _v42Need`,
    #     干净上游基线上那行还不存在(run#37118226923 的真实死因)。
    #   - 排在 v44 后: 注入锚点就是 V44 诊断段的首行, v44 没注入则锚点落空。
    #
    # log13 归因(53 条 V44-TEXTFRAME, 零例外): 假设 A 命中 44/53,
    # 假设 B(svAfter < needH)**彻底排除** —— svAfter == needH 53/53 全成立。
    # 真凶: v41~v44 一路补的都是 superview(sv.frame), 而画字的是 UITextView
    # 自己(self.frame)。实测 tvH=912.7 而 svAfter=needH=1136.3, 外层补到位、
    # 内层矮 223.6pt —— 多出来的是空壳, 有字的地方被自己的 bounds 裁掉。
    # 这就是"下面一小片空白 + 字还是卡一半"的完整机制。
    # 44 条样本的 `usedH - tvH` **恒为负**(-8.0~-44.7, 均值 -34.5), 从没转正
    # —— 不是随机拉锯, 是两个来源各写一次高度的系统性偏差。
    # 本版只治 tvH(A 主因), **不碰宽度**: 脏宽 tcW=390 确是共犯(欠账样本 42/44
    # 是脏宽, 正常样本 9/9 是净宽 358), 但宽度抢回在 v13/v34 反复引起过闪屏,
    # 风险面独立, 留待单独一版。
    edit("Views/Chat/SelectableMarkdownView.swift", fix_tvh_debt_v45, "v45: 补高**补到画字的那个视图上** — 治'下面一小片空白 + 字卡一半'(v44 纯诊断归因, log13 53 条零例外: 假设 A 命中 44/53, 假设 B 彻底排除 —— svAfter == needH 53/53 全成立, 补高从来没被挡掉过。真凶是**补错了对象**: v41~v44 一路补 superview 的 sv.frame, 而画字的是 UITextView 自己的 self.frame。实测 tvH=912.7 而 svAfter=needH=1136.3 —— 外层补到位了, 内层矮 223.6pt, 多出来的是空壳(所以有空白), 有字的地方被自己的 bounds 裁断(所以卡一半)。44 条样本的 usedH-tvH 恒为负(-8.0~-44.7 均值 -34.5) 从不转正, 证明不是随机拉锯而是两个来源各写一次高度。修法: 在 KVO 补高路径里把 needH 同时写进 self.frame。**只动 size.height, 绝不碰 origin/width** —— 宽度由 v18/v34 经 ios15LastSaneSVFrame 维护, 在这里碰它等于绕过那套状态机(v13/v34 都因抢宽引起过闪屏/整体缩小), 校验函数硬禁非高度改动。needH 是本闭包按抢回后净宽算出的权威需求高, 补到它即同时覆盖 v44 假设 C 的虚高差额(30~268pt), C 无需单独代码; 连续多帧时 tvH >= needH 让条件自然转 false, 幂等不反复写。★登记必须排在 v42 与 v44 之后")
    # ---- v46: 表格附件排版链归因(纯诊断, 一行几何都不碰) ----
    edit("Views/Chat/SelectableMarkdownView.swift", fix_diag_attachment_v46, "v46: 【纯诊断, 不改任何行为】V46-ATTACH — 治'终端框盖住上面的字/定时任务字一下有一下没有'。log15 硬证据: needH=304.3 而 usedH=114.3(差 190pt), 表格 7x2 附件占的高度完全不在 usedRect 里; 111 条 V44 里 71 条 needH-usedH>8.5(中位 55.6 最大 190.0), 另 40 条 <=8.5(纯文字, 差额就是 textContainerInset 的 8.1~8.3) —— **差额与'有没有附件'完全同构**, 这是 v44 假设 C 的首次真实命中。len=49 那组更直白: 唯一一组 usedH 恒为 99.9 而 needH 在 182<->236 之间跳的样本, 附件高度反复切换 = 文字忽隐忽现。链路上四个候选根因一次性打完: D1 缓存未失效(computeLayout 开头 cachedLayout 命中即返回, update() 的 structureChanged||contentGrew 若为 false 就留着旧 rowHeights) / D2 探针宽度(isOversizedProbe 时高度按 containerRealWidth 算但返回宽度是 clampedWidth) / D3 失效信号未消费(needsLayoutInvalidation 置位但 invalidate 路径没跑到) / D4 容器被 TextContainerGuard 短路(log15 累计 3617 次, 高度出现 2000.0/1057.3/18.7 等与真实需求无关的值)。**为什么不盲修**: D1 要放宽缓存失效判据, 而那正是 HangFix 2026-05-14 治'流式每 token 全量重测致主线程卡死数秒'故意保留的; D4 要放宽 guard, 而 guard 是治 fillLayoutHole 11918ms 卡死的 —— 两处都是拿性能换正确性的历史 trade-off, 盲修任一处都可能把卡死放回来。校验函数硬禁段内一切赋值与 invalidate*/computeLayout 调用(用剥注释去字符串后的语义级赋值识别, 不靠逐行白名单), 并硬禁访问器带 setter; 另注入 TableAttachment.attV46CachedTotalH/attV46CachedWidth 两个**只读 getter**(cachedLayout 是 private, 不加就读不到, D1 就无法验证)。0.5s 节流与 V41-KVOPRE/V44-TEXTFRAME/V45-TVHFIX 同周期。★登记必须排在 v45 之后(同一闭包同帧, 三者并列对照)")
    # ---- v47: 统一测宽源(排版宽与目标宽同步) ----
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_reflow_v47, "v47: 统一测宽源 — 治'终端框盖住上面的字/定时任务字一下有一下没有'(v46 纯诊断归因, log16 45 条: **D1/D2/D3 三个候选全排除** —— `attWant==attCached` 45/45 缓存新鲜, `cachedW` 与 `tcW` 恒差 1.0 不是陈旧值, `attNVI=1` 0/45 失效信号从未置位。真凶是**排版宽与测高宽不同源**: `tcH-needH=-8.0` 恒定证明容器高度没问题, `V43-WIDTH dirtyW=390 netW=358 dh=0.0` 证明测高用的净宽 358 也没问题, 但 `tcW` 实测恒为 390 且 `tcH-usedH` 在异常组达 44~67pt —— **同一段文字在 390/358 两个宽度下排出的行数不同**, 行碎片停在旧宽而 needH 恒按新宽算, 差出的就是空壳(终端框于是画在空壳上)。根因是 `_ios15WRegrabbed` 由 `abs(tcW-_realW2)>0.5` 决定, 它只表示'有没有改过容器宽'而不表示'碎片有没有按目标宽重排过' —— 而 `invalidateLayout` 才是让碎片重排的那一步。修法: 新增 `ios15LastLaidOutW` 记住上次排版宽, 与目标宽不等就补一次 invalidateLayout。**不新增任何宽度写入点**(仍只有 v18 那两处)、**不碰高度**(v45 成果保护), 稳态下零额外开销且幂等。v13/v34 曾因抢宽引起闪屏与整体缩小, 那是改钳宽翻的车, 本版只加同宽重排。★登记必须排在 v46 之后")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_pin_v48, "v48: 排版宽钉回目标宽 — 收口 log17 实测的「v47 只治了一半」。log17 对比 log16: tcW=390 的帧 69→48(v47 的重排确实触发了), 但仍有 48/56 帧 tcW 是 390 —— 因为 v47 只调 invalidateLayout **不写 textContainer.size.width**, TextKit 的 ensureLayout 只在当前容器宽下重排, 容器还是 390 时重排出来的仍是 390 宽的行数, 与按 358 算的 _needH 依旧不同源。**log17 里 tcW 与 gap 完全同构、零例外**: tcW=358.0 → tvH-usedH 恒 8.0~8.3(= textContainerInset 上下之和, 正常态), tcW=390.0 → gap 为 30.5(len=229)/117.5(len=839, 连续 26 条一模一样)。len=229 那组最直接: 同一段文字, 358 宽 gap=8.1, 390 宽 gap=30.5, 差值就是 390 宽排不下的那几行。tvH-needH 全部 56 条为 0.0, v45 补高依然完美, 问题**只在宽度不在高度**。修法: 碎片与目标宽不一致时, **连容器宽一起钉回 _realW2**, 两者合起来才是完整条件(容器宽==目标宽 且 碎片按目标宽重排过); v47 的 ios15LastLaidOutW 判据保留不动, 两个判据正交。**这不是新的抢宽时机**: 写在 v18 段内, 复用 v18 已算好的 _realW2(与 sizeThatFits 测高同一个值), 不引入第三方宽度; 判据 abs(tcW-_realW2)>0.5 保证幂等(已在 358 不写不重排, 稳态零开销; 被推回 390 才纠偏一次, 是**纠偏**不是**竞争**)。v13/v34 翻车是因为在布局 pass外无条件抢宽、与 SwiftUI 竞争, 本版恰好相反; 只写 size.width, **不碰 frame/bounds/origin/高度**, 不会引起「整体缩小」那类几何漂移, 也不推翻 v45。**不做常驻钳宽**: 每帧无条件写 358 正是 v13/v34 的翻车形态。校验用**白名单**(只许 textContainer.size.width = _realW2, 精确等值)而非黑名单 —— 多写一个 frame.origin 就足以让整棵 cell 重新布局。★登记必须排在 v47 之后(锚点是 v47 注入的判据块)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_writer_diag_v49, "v49: 【纯诊断, 不改任何行为】V49-WWRITER — 钉死「谁把 textContainer.size.width 推回 390」。log18 首次打破 log17 的「tcW 与 gap 完全同构」: tcW=390 组里出现 18 帧 gap=8.2(**正常**) —— len=122 在 390 宽下排版正确, 前两版从未有过 ⇒ **v48 钉宽确实生效, 但只治好轻文本**。重文本 len=1013(含 1 个表格)仍残缺: n=9 cachedW=357→tcW=358→usedH=1727.6 gap=8.1 ✅ / n=10 cachedW=389→tcW=390→usedH=1638.1 gap=97.6 ❌ —— **cachedW 与 tcW 完全同构(35/36)**。逐毫秒读 00:07:42: .678 [V42-MISS] tcW=358 usedH=1727.6(对) → .679 [V46-ATTACH] tcW=390 usedH=1638.1, **1 毫秒内被推回**; 而 v48 的钉宽写在 v18 段(缩进 12, layoutSubviews 内), **早于**表格附件测量链跑完 ⇒ 纠偏追不上。**为什么纯诊断不盲修**: 候选写入者至少三个(V46 attachmentBounds 测量链 / v37 probe 钳位链 / SwiftUI 布局 pass), 修法互相冲突 —— 放宽 V46 动表格渲染, 动 probe 钳位动 v37 那套 9 处泄漏防护, 抢 SwiftUI pass 是 v13/v34 翻车老路; 而 D4(TextContainerGuard 熔断 219 次, 358x2000 被熔 109 次)那条路是治 fillLayoutHole 11918ms 卡死的, 同样是历史 trade-off。先探针定位到**行**再动刀。探针两处构成**同帧差分**: v18 段末尾(v48 钉宽之后, 记 v18W) + v41 KVO 抢帧器(记 kvoW + 来源指纹 cvW/laidW/boundW/tcH)。同 tick 内读到不同值 ⇒ 中间有人写过; 跨 tick ⇒ SwiftUI pass 之间写的。段内零赋值零 invalidate*(与 v44/v46 同纪律), 指纹全部走既有只读属性与本闭包局部量(cvW 用 KVO 闭包内已有的局部量, laidW 用 v47 注入的 ios15LastLaidOutW), 不新增读取语句以免探针自己扰动布局。★本轮实踩两个**编译级**坑: (1) struct _V49W 声明在函数体内 → KVO 侧跨函数引用不到(局部类型跨函数不可见) ⇒ 已提到类型级; (2) 原想读 v46 的 attV46CachedWidth, 但那个 getter 声明在 **TableAttachment** 类里而探针在 SelectableMarkdownTextView 内 ⇒ 跨类访问, 编译失败 ⇒ 换成同类型的 laidW(问的都是「碎片按哪个宽排的」, 诊断力不减)。为此新增 scripts/ios15_verify/scope_check_v49.py 专查作用域(判据查不出编译问题)。0.5s 节流与 V44/V45/V46/V41 同周期。★登记必须排在 v48 之后(探针要读 v48 钉宽之后的值)")
    # ---- v30: 测高双引擎振荡熔断 + 流式测高节流 + 输入栏假死自愈 ----
    edit("Agent/MessageList/MessageListLayout.swift", fix_flip_block, "v30-A: 双引擎测高反振荡 — 斩断 est=1176↔850 回路 (列表高度瞬间跳跃/剧烈抖动)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_measure_throttle, "v30-B: 流式测高节流至 ~8次/秒 — 主线程不再被全量 TextKit 排版占满 (卡顿/STALLED/停止迟钝)")
    edit("Views/Chat/AIChatView.swift", fix_inputbar_kick, "v30-C: 输入栏假死自愈 — STALLED 时就地重建 composer host (草稿保留)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_stabilize_v32, "v32: 渲染宽+测高宽统一 per-cell contentW(视图宽-内边距) — 消除测宽分歧与溢出裁字")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_realw2_v33, "v33: v28 遗留 _realW2 硬编码 cvW-32 改为 contentW — 修边框裁字/卡字/终端框卡内容")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_sync_v34, "v34: 渲染宽回归 superview 基准(过渡态免疫) + 渲染/测高共享 ios15LastRenderContentW — 修整体缩小/不贴边/闪屏(log10-03: tcW 390×27/326×25 交替, v33 公式过渡态双重扣减)")
    edit_glob("**/iOS15Compat.swift", fix_hosting_fullwidth_v35, "v35: hosting 视图/内容改回全屏宽(不再 -32) — 根治整体缩小/气泡不贴边/终端框折叠(v22/v24 把整个 cell 硬钉 358, 而 cell 应全宽 390)")
    edit_glob("**/iOS15Compat.swift", fix_hosting_track_parent_v36, "v36: hosting 视图宽从写死屏宽改为与父等宽 — 修'气泡差一点贴边'(UIScreen 常量 != collectionView 实测宽)")

    # ---- 诊断: 几何测量回填是否落地 (inputBarHeight 相关的关键校验) ----
    print("-- 诊断 dump (几何测量回填点) --")
    n15 = 0
    for root, _, files in os.walk(ROOT):
        for fn in files:
            if not fn.endswith(".swift"):
                continue
            fp = os.path.join(root, fn)
            txt = read(fp)
            if ".onGeometryChange15(" in txt:
                rel = os.path.relpath(fp, ROOT)
                for i, l in enumerate(txt.split("\n"), 1):
                    if ".onGeometryChange15(" in l:
                        print("   %-56s L%d" % (rel, i))
                        n15 += 1
    print("   回填点合计 %d 处" % n15)
    p = os.path.join(ROOT, "iOS15Compat.swift")
    print("   回填实现(IOS15_GEOM_BACKPORT): %s" % (
        ("存在" if "IOS15_GEOM_BACKPORT" in read(p) else "缺失")
        if os.path.isfile(p) else "缺 iOS15Compat.swift"))
    p = os.path.join(ROOT, "Views/Chat/AIChatView.swift")
    if os.path.isfile(p):
        txt = read(p)
        print("   inputBarHeight 写入点: %d 处" % txt.count("inputBarHeight = newH"))

    # ---- 诊断: 把关键文件片段打到运行日志 (失败时我能看到编译时真实源码) ----
    print("-- 诊断 dump (AppDelegate 20-84) --")
    p = os.path.join(ROOT, "AppDelegate.swift")
    if os.path.isfile(p):
        for i, l in enumerate(read(p).split("\n")[19:84], start=20):
            print("   %4d| %s" % (i, l))
    print("-- 诊断 dump (ModelSelectionEntity LSR 区域) --")
    p = os.path.join(ROOT, "Agent/Intents/ModelSelectionEntity.swift")
    if os.path.isfile(p):
        for i, l in enumerate(read(p).split("\n")[130:165], start=131):
            print("   %4d| %s" % (i, l))
    print("-- 诊断 dump (AIChatView 1450-1800) --")
    p = os.path.join(ROOT, "Views/Chat/AIChatView.swift")
    if os.path.isfile(p):
        for i, l in enumerate(read(p).split("\n")[1449:1800], start=1450):
            print("   %4d| %s" % (i, l))
    print("-- 诊断 dump (UnifiedModelPicker toolbarContent) --")
    p = os.path.join(ROOT, "Views/Providers/UnifiedModelPicker.swift")
    if os.path.isfile(p):
        txt = read(p).split("\n")
        for i, l in enumerate(txt):
            if "toolbarContent" in l:
                for j in range(i, min(i + 22, len(txt))):
                    print("   %4d| %s" % (j + 1, txt[j]))
                break
    # ---- 诊断: guard 熔断是否落地 ----
    print("-- 诊断 dump (NSTextContainerSetSizeGuard 熔断) --")
    p = os.path.join(ROOT, "Shared/NSTextContainerSetSizeGuard.m")
    if os.path.isfile(p):
        gt = read(p)
        print("   IOS15-FIX-STORM 标记: %s" % ("存在" if "IOS15-FIX-STORM" in gt else "缺失"))
        print("   kStormForwardLimit:   %s" % ("存在" if "kStormForwardLimit" in gt else "缺失"))
        print("   kMaxContainerHeight:  %s" % ("存在" if "kMaxContainerHeight" in gt else "缺失"))
        print("   高度上限已降(非1e7):   %s" % ("是" if "kMaxContainerHeight) newSize.height = kMaxContainerHeight" in gt else "否"))
    print("== iOS 15 兜底修复 v2 完成 ==")


if __name__ == "__main__":
    main()
