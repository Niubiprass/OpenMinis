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

    private func ios15FittingSize(_ targetSize: CGSize) -> CGSize {
        var width = targetSize.width
        // ⚠️ 关键: 布局引擎问"压缩尺寸"时传的是 UIView.layoutFittingCompressedSize,
        // 宽高都是 Double.greatestFiniteMagnitude (≈1.8e308)。它是**有限数**,
        // 所以 `width.isInfinite` 拦不住 —— 之前直接把它当真实宽度交给 SwiftUI,
        // 内容按无界宽度排版: 长文本不换行、按自然宽度居中渲染 → 左右被裁;
        // 同时 TextKit 在这个荒谬宽度下抛 NSException → 自排版永远退回估算
        // 高度 → 单元格之间大片黑块（日志实测 1977 次全部 threw）。
        // 这里把"未指定/哨兵"宽度替换成集合视图的真实宽度。
        if !(width > 0) || width.isInfinite || width >= 1_000_000 {
            var probe: UIView? = superview
            var cvW: CGFloat = 0
            while let v = probe {
                if let collection = v as? UICollectionView {
                    cvW = collection.bounds.width
                    break
                }
                probe = v.superview
            }
            width = cvW > 0 ? cvW : (window?.bounds.width ?? UIScreen.main.bounds.width)
        }
        let probeCvW = (superview?.superview as? UICollectionView)?.bounds.width ?? -1
        print("[IOS15Size] in targetW=\\(targetSize.width) w=\\(width) cellW=\\(bounds.width) cvW=\\(probeCvW) hostNil=\\(host == nil)")
        guard let host = host, !isMeasuring else {
            return CGSize(width: width, height: max(0, bounds.height))
        }
        isMeasuring = true
        defer { isMeasuring = false }
        var size = host.view.sizeThatFits(CGSize(width: width,
                                                 height: CGFloat.greatestFiniteMagnitude))
        if !(size.height > 0) {
            size = host.view.sizeThatFits(CGSize(width: width, height: 0))
        }
        var height = size.height
        if !(height > 0) { height = bounds.height }
        print("[IOS15Size] out w=\\(width) h=\\(height) idealW=\\(size.width) idealH=\\(size.height)")
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


def fix_widget_activitykit(t):
    """AgentWidgetExtension 在 iOS 15.5 上根本没有 ActivityKit 框架, 但
    AgentLiveActivityWidget.swift 顶层 `import ActivityKit` 会让编译器以**强链接**
    方式把该 framework 写进扩展的 load command; dyld 在加载扩展时因找不到库而
    崩 (Library not loaded: .../ActivityKit.framework/ActivityKit), 持续吐崩溃日志。
    所有 ActivityKit 的实际使用都包在 @available(iOSApplicationExtension 16.2, *)
    里, iOS 15.5 上根本不会执行 —— 因此只需把它改成**弱链接**, dyld 即可容忍缺失。
    """
    if '"-weak_framework"' in t:
        return t
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
        insert = ('\n\t\t\t\tOTHER_LDFLAGS = (\n\t\t\t\t\t"-weak_framework",\n'
                  '\t\t\t\t\tActivityKit,\n\t\t\t\t);')
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
        let measureWidth: CGFloat
        if proposedMeasureW > 1, proposedMeasureW < 100_000,
           (cvContentWidth <= 1 || proposedMeasureW <= cvContentWidth + 1) {
            measureWidth = proposedMeasureW
        } else if cvContentWidth > 1 {
            measureWidth = cvContentWidth
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
        let containerWidth = (cvContentWidthUAV > 1 && rawContainerWidth > cvContentWidthUAV + 1)
            ? cvContentWidthUAV : rawContainerWidth'''
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

    // [IOS15-FIX-STORM] 风暴熔断: 本 tick 已经触发过熔断, 直接跳过转发、保留
    // 上次已提交几何。这样 re-entrant 的 setSize 链在到达阈值后立刻断掉, 不再
    // 驱动 CoreText fillLayoutHole 自旋 (实测 11918ms 主线程卡死的根因)。
    if (s->initialized && s->lastTick == gRunloopTick && s->stormed) {
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
        s->lastTick = gRunloopTick;
        s->repeatCount = 1;
        s->commitCount = 0;   // [IOS15-FIX-STORM] 重置本 tick 转发计数
        s->stormed = NO;      // [IOS15-FIX-STORM] 重置熔断标志
        s->initialized = YES;
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
    OLD = '''        let currentWidth = textContainer.size.width'''
    NEW = '''        // [IOS15-FIX-CLIP] 老会话双边裁字修复: 容器/自身宽度钳回 + 强制重排。
        // 仅限不可滚动视图 (可滚动的代码块视图自管宽度/偏移, 不动)。
        if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {
            let _svW = superview?.bounds.width ?? 0
            // 真实宽度 = min(superview, collectionView); superview 宽度瞬时
            // 异常小 (<200) 时退回 collectionView 宽度, 防止把容器钳成窄条。
            let _realW = _svW > 200 ? min(_svW, rCv2.bounds.width) : rCv2.bounds.width
            let _tcOldW = textContainer.size.width
            var _didFix = false
            if textContainer.size.width > _realW + 1 {
                textContainer.size.width = _realW
                _didFix = true
            }
            if bounds.width > _realW + 1 || frame.size.width > _realW + 1 {
                var _rf = frame
                _rf.size.width = _realW
                frame = _rf
                _didFix = true
            }
            if bounds.origin.x != 0 {
                var _rb = bounds
                _rb.origin.x = 0
                bounds = _rb
                _didFix = true
            }
            // [IOS15-FIX-CLIP v2] 上游只在"测量"阶段钳了宽度, 但 frame/superview 帧
            // 仍会被 iOS15 SwiftUI 递归排版传入的瞬时离谱 bounds.width (1e7) 焊死 ——
            // 日志 svFrame 实测宽 1e7、origin.x=-5e6, 整块文本被推到屏幕外/被裁。这里
            // 把失控的 superview 帧钳回: 宽收到集合视图宽度、origin.x 归零。钳制目标
            // 低于触发阈值 (cvW 与 0), 重排后会落到阈值内, 不会形成死循环。
            if let _sv = superview,
               _sv.frame.size.width > rCv2.bounds.width * 2 || _sv.frame.origin.x < -rCv2.bounds.width {
                var _svf = _sv.frame
                if _svf.size.width > rCv2.bounds.width * 2 {
                    _svf.size.width = rCv2.bounds.width
                }
                if _svf.origin.x < -rCv2.bounds.width {
                    _svf.origin.x = 0
                }
                _sv.frame = _svf
                _didFix = true
            }
            if _didFix {
                layoutManager.ensureLayout(for: textContainer)
                setNeedsLayout()
                struct _ClipFixLog { static var lastLog: CFTimeInterval = 0 }
                let _nowF = CACurrentMediaTime()
                if _nowF - _ClipFixLog.lastLog > 1.0 {
                    _ClipFixLog.lastLog = _nowF
                    AppLogger(category: "CellSize").info("[LEFT-CLIP-FIX] clamped tcW " + String(describing: _tcOldW) + " -> " + String(describing: _realW) + " (svW=" + String(describing: _svW) + " cvW=" + String(describing: rCv2.bounds.width) + ") frameW=" + String(describing: frame.size.width) + " boundsO=" + String(describing: bounds.origin) + " storageLen=" + String(describing: textStorage.length))
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
    edit("ShareExtension/ShareViewController.swift", fix_share_extension_timeout, "分享扩展加 8s 超时兜底 (防永久挂住)")
    edit("Shared/SharedContainerStore.swift", fix_share_store, "PendingShare 双通道存储 (UserDefaults + 共享容器文件)")
    edit("Agent/MessageList/MessageListLayout.swift", fix_message_list_defer, "iOS15: 大幅缩小(>50pt)修正立即生效, 消黑块虚高")
    edit("Minis.xcodeproj/project.pbxproj", fix_widget_activitykit, "Widget 弱链接 ActivityKit (iOS15.5 无此框架, dyld 崩)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_markdown_measure_width, "iOS15: 测量宽度钳制到集合视图宽度, 消正文错位/裁切")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_markdown_render_width, "iOS15: 渲染端 frame/偏移钳制 + cell 自排版提议宽度钳制, 消正文错位(第二轮)")
    edit("Agent/MessageList/MessageListInfrastructure.swift", fix_markdown_render_width, "iOS15: cell 自排版提议宽度入口钳制")
    edit("Agent/MessageList/MessageListInfrastructure.swift", fix_markdown_layout_reconcile, "iOS15: TextKit 高度兜底, 修末行裁切 + 收敛 FIRST-MEASURE 死循环")
    # ---- v4: setSize 风暴熔断 + 有限高度 + 代码块 widthTracksTextView + 左裁字诊断 ----
    edit("Shared/NSTextContainerSetSizeGuard.m", fix_textcontainer_guard_stormbreaker, "v4: setSize 风暴熔断(同tick>40次锁定) + 容器高度上限1e7→1e5, 斩断 CoreText fillLayoutHole 12s 卡死")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_code_textview_widthtrack, "v4: codeTextView 关 widthTracksTextView 并固定容器宽, 消代码块 589.3x17.3 重排风暴")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_left_clip_diag_superview, "v5: 老会话双边裁字修复 — 渲染端容器宽度钳回+强制重排 (原 v4 仅诊断)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_defer_large_shrink, "v5: 大幅收缩(-100pt)修正立即生效, 消回复后大片空白 (控制台输出折叠卡片欠账数秒)")

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
