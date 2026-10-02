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
            let f = obj.frame
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
            let _realW2 = max(200.0, _cvW - 32)
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
    而 v28 在渲染函数末尾注入的 `let _realW2 = max(200.0, _cvW - 32)` = 358 会把
    textContainer 强行撑到 358 —— 塞进 326 宽的框里, 右侧 32pt 溢出被裁 → "边框裁字/卡字";
    终端/代码框(内部再嵌一层)同理被卡。v32 已把 _realW 与测高宽改为 per-cell contentW,
    但 _realW2 是该函数最后一次赋值, 会覆盖 v32 → 必须一并改为 contentW, 三者才一致。
    """
    OLD = """            let _realW2 = max(200.0, _cvW - 32)"""
    NEW = """            // [V33-WIDTH2] 与 _realW/测高宽 同一式子(视图宽 - 内边距): 气泡型 326、贴边型 358
            // 各取真实宽, 绝不把 326 的框撑到 358 (那会右侧溢出裁字)。不再硬编码 cvW-32。
            let _realW2 = max(200.0, min(bounds.width, _cvW) - textContainerInset.left - textContainerInset.right)"""
    if "V33-WIDTH2" in t:
        return t
    if OLD not in t:
        raise RuntimeError(
            "[fix_realw2_v33] _realW2 锚点未命中 —— 上游 SelectableMarkdownView 里没有 "
            "`let _realW2 = max(200.0, _cvW - 32)` 这行。它是渲染函数最后一次宽度赋值, "
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

    修法: 在有限性检查**之前**加一道"探测高度"识别 —— 高度 >= kProbeHeightFloor
    (取 8000pt, 远高于任何真实气泡, 又远低于 100000) 一律压到 kMaxContainerHeight
    之下的合理值, 且**每 tick 只放行一次**。这样:
      - 87 次 100000 探测变成最多每 tick 1 次, CoreText 调用量降一个数量级;
      - 真实的 358x550.9 / 358x1748.0 等尺寸完全不受影响(远低于 8000);
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
    // 修法: 高度 >= 8000 (远高于任何真实气泡, 远低于 1e5) 判定为探测哨兵,
    // 压到 kProbeHeightCeiling。真实尺寸 (<8000) 一个字节都不受影响。
    // 哨兵本身不丢弃(下游需要它做 max-width/高度发现), 只是不再让 CoreText
    // 在十万点高度上真的排版。
    const CGFloat kProbeHeightFloor = 8000.0;
    const CGFloat kProbeHeightCeiling = 4000.0;
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
