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
    # [IOS15-FIX-PICKER-CAP] 非搜索态也截断到 maxSearchResults.
    # 上游 GH#271 的 cap 仅作用于搜索态(见 cappedEntriesByInstance 的
    # `guard !debouncedSearch.isEmpty else { return all }`); 非搜索态直接
    # return all。但上游注释明示单个聚合器可持有 7000+ 模型。iOS 15 的
    # SwiftUI List(UITableView 后台) 会对每个自定高单元格逐行测高, 每行触发
    # 一次 UIFoundation 文本布局 -> 数千行 = 主线程 8.5s 卡死被看门狗 SIGKILL
    # (实测 crash-20261006-101239.log: Hang 8533ms, 堆栈全在 UIFoundation,
    # 对应"点选择模型就卡死")。统一截断保留相关性最高的前缀(entries 已按
    # 相关性排序), 与搜索态行为一致; footer 同步提示。
    t = t.replace(
        "        let all = filteredEntriesByInstance\n        guard !debouncedSearch.isEmpty else { return all }\n        var remaining = Self.maxSearchResults",
        "        let all = filteredEntriesByInstance\n        // [IOS15-FIX-PICKER-CAP] 非搜索态也截断(见函数注释)\n        var remaining = Self.maxSearchResults")
    # footer 同步: 非搜索态截断时也提示 "Showing N of M"
    t = t.replace(
        "if !debouncedSearch.isEmpty, totalSearchMatches > Self.maxSearchResults {",
        "if totalSearchMatches > Self.maxSearchResults {")
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
    t = t.replace("Alignment(horizontal: alignment)",
                  "Alignment(horizontal: alignment, vertical: .center)")
    # [IOS15-FIX-INPUT-FLICKER] 输入框打字闪屏根因: PastableUITextView 的
    # intrinsicContentSize 在每次查询时无条件改写 isScrollEnabled, 触发 UIKit 布局
    # 重入 (intrinsicContentSize → isScrollEnabled=… → layout → intrinsicContentSize …),
    # 每键输入都让输入框高度(及内部文字)跳动/闪屏。改为"仅当值变化才改写",
    # setter 对相同值早返回、不触发布局失效, 反馈环路被斩断, 滚动行为不变。
    OLD_FLICKER = (
        "        let size = sizeThatFits(CGSize(width: bounds.width, height: .greatestFiniteMagnitude))\n"
        "        isScrollEnabled = size.height > maxHeight\n")
    NEW_FLICKER = (
        "        let size = sizeThatFits(CGSize(width: bounds.width, height: .greatestFiniteMagnitude))\n"
        "        // [IOS15-FIX-INPUT-FLICKER] 仅当值变化才改写 isScrollEnabled, "
        "避免 intrinsicContentSize 查询触发布局重入(输入闪屏根因)。\n"
        "        let _shouldScroll = size.height > maxHeight\n"
        "        if isScrollEnabled != _shouldScroll { isScrollEnabled = _shouldScroll }\n")
    if OLD_FLICKER in t:
        t = t.replace(OLD_FLICKER, NEW_FLICKER)
    return t


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
    attachment 布局 (updateAttachmentViews) 同理钳制 containerWidth。

    ★幂等: 下面四段都用 `if OLD in t` 软判断, 而四段的锚点
    (`[JitterFix] ...` / `let containerWidth = ...` /
    `// [TableGenDedup] Compute the sum ...` / `abs(cell.bounds.height - newHeight) > 8`)
    **在第一次运行后依然存在** —— 前三段被替换掉了, 但 OLD3 的锚点
    (`[TableGenDedup] Compute the sum`) 是本补丁自己新插入段落的**下一行**,
    第一次运行后仍留在原地, 于是第二次运行会再插一份消毒段(产物出现重复块)。
    ⇒ 统一在函数开头设产物标记判据, 且位置必须在任何注入动作之前。
    """
    if "IOS15-BADWIDTH-GUARD" in t:
        return t
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
    NEW3 = r'''        // [IOS15-FIX] [IOS15-BADWIDTH-GUARD] 宽度兜底消毒: 若上面三分支仍落到离谱瞬态宽度
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
    # ★v56.4 补幂等判据(本段一直缺, 这次才暴露)——
    #   锚点 OLD = "attrs.size.height = fittingSize.height", 而注入后的 NEW
    #   **末尾仍然含这一行**(它就是最终赋值)。于是第二次运行:
    #       OLD in t 仍为真 -> 又 replace 一次 -> 变量声明重复两份
    #   后果: `var _ios15TkSum` 重复声明 ⇒ Swift 报
    #         invalid redeclaration of '_ios15TkSum' ⇒ 编译失败。
    #   这个洞一直在, 只是历史上从没在同一份产物上跑过第二遍;
    #   v56.4 为了验幂等而复跑, 立刻踩中。
    #   ⇒ 纪律: **注入段的末尾若仍含自己的锚点, 判据必须认「插入物自身」,
    #     而不是认锚点**。锚点在插入后依然存在, 判据锚点 = 没有判据。
    if "_ios15Reconciled" in t:
        return t
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
# F7b. v65: 守卫不再「丢弃」坏尺寸，也不再「误伤」真实排版
# ---------------------------------------------------------------------
# 【v64 装机后的真根因 —— 与 v64 那条线无关】
#
# v64 装机实证: 累加**确实治好了**(FIRST-MEASURE 13 对全部只出现 1 次,
# 旧的 est=236→380→555 +170/拍 彻底消失)。但用户仍报闪屏/抖动/卡字,
# 因为真正的病在**更上游的一层**, 日志把它指得死死的:
#
#   [TextContainerGuard] short-circuited setSize: REJECT-NAN-INF-NEG
#       size=0.0x-8.0   × 43
#       size=0.0x-16.0  × 18        ← 合计 61 次
#
#   宽度 **0**、高度**负数**。这 61 次全被守卫 `return` **丢弃** ⇒ TextKit
#   的容器尺寸一次都没被更新 ⇒ 排版停在上一帧 ⇒ 屏幕上「字被裁掉一半」。
#   旁证: `tk=27.0` 出现 83 次 / `est=31.0` 出现 96 次 —— 31pt 就是**一行**。
#   ⇒ 「卡字」不是布局算错, 是**排版压根没跑**。
#
#   [TextContainerGuard] short-circuited setSize: size=358.0x19.0  × 39
#                                            size=358.0x41.0  × 46
#   这两个**不是哨兵, 是真实排版请求**(19/41pt = 一行/两行), 也被同 tick
#   熔断规则连带丢掉 ⇒ 每次丢掉都意味着这一帧的排版作废、下一帧拿旧高度
#   上屏 ⇒ 用户看到的「打一个字母就抖一下」。
#
# 【为什么之前 30 余版没治好 —— 三条排除法】
#   ① 不是 self-sizing 反馈环: est==recomputed 176/176 = 100%, 累加已消失;
#   ② 不是宽度污染: v34/v47/v48/v51 已把 tcW 钉在 358, 日志 tcW 恒 358;
#   ③ 不是闸门锁死: 闸门只在"两侧都没更新信息"时收紧, 而 Tk 有值时放行。
#   ⇒ 剩下唯一还在丢东西的环节, 就是这个守卫本身。
#
# 【v65 三条, 全部改「产生/丢弃」这一侧, 不动任何已修好的部分】
#   ① REJECT → **就地修正后转发**: 宽 0 → 用容器当前宽(或屏宽兜底);
#      负高 → 取绝对值并夹到合法区间。**丢弃是错的**: 丢弃让 TextKit 保留
#      过期几何, 而过期几何正是"卡字"的直接来源。修正后转发 = 让排版真的跑。
#   ② 风暴熔断**豁免真实排版尺寸**: 哨兵(≥2000 高)才进风暴计数;
#      真实高度(19/41/939/1118...)永不因熔断被丢 ⇒ 抖动源头切断。
#      ★这是本次最关键的一条: 熔断本是为杀哨兵风暴而设, 却在吞真实排版。
#   ③ 保留 NaN/inf 的**硬拒**: 那些是真的不能喂给 TextKit(会走 fillLayoutHole
#      病态循环 → 12s 卡死, v4 已实证)。只把「有限但非正」的尺寸改成修正转发。
V65_REJECT_OLD = """    if (!isfinite(newSize.width) || !isfinite(newSize.height) ||
        newSize.width < 0 || newSize.height < 0) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0x1F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] short-circuited setSize: "
                  @"REJECT-NAN-INF-NEG size=%.1fx%.1f total=%llu container=%p",
                  newSize.width, newSize.height,
                  (unsigned long long)gShortCircuitCount,
                  (__bridge void *)self);
        }
        return;
    }"""

V65_REJECT_NEW = """    // [V65-FIXSIZE-S] 原始尺寸的函数级副本 (赋值在下面的修正分支里)。
    // 必须声明在函数体开头: 块内声明对后续兄弟块不可见(clang 实测 4 处
    // "use of undeclared identifier"), 本项目 §19 同族第四次。
    CGFloat _v65orig_w = newSize.width;
    CGFloat _v65orig_h = newSize.height;
    if (!isfinite(newSize.width) || !isfinite(newSize.height)) {
        // [V65] NaN/inf 仍然硬拒 —— 它们会触发 CoreText fillLayoutHole 病态循环
        // (v4 实证 11918ms 主线程卡死), 且 TextKit 无法表示, 无从"修正"。
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0x1F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] short-circuited setSize: "
                  @"REJECT-NAN-INF size=%.1fx%.1f total=%llu container=%p",
                  newSize.width, newSize.height,
                  (unsigned long long)gShortCircuitCount,
                  (__bridge void *)self);
        }
        return;
    }
    // [V65-FIXSIZE] 有限但非正的尺寸: **就地修正后转发, 不再丢弃**。
    //
    // 【装机铁证】v64 之后 (minis-2026-10-05 13:21) 这个分支命中 61 次:
    //   size=0.0x-8.0  ×43
    //   size=0.0x-16.0 ×18
    // 宽 0 + 负高 = 宽度算崩了、高度算成了 -inset/2。旧代码在这里 `return`
    // ⇒ **TextKit 容器尺寸一次都没被更新** ⇒ 排版停在上一帧 ⇒ 屏幕上的字
    // 被上一帧的旧高度裁掉一半。旁证: tk=27.0 ×83 / est=31.0 ×96,
    // 31pt 就是一行 —— 「卡字」不是布局算错, 是排版压根没跑。
    //
    // 【为什么必须修正而不是丢弃】丢弃看起来"安全"(不把脏值喂给 TextKit),
    // 但它恰恰是卡字的直接原因: 丢弃 = 保留过期几何 = 排版结果永远滞后。
    // 而这些值是**有限**的, 数值上完全可以变成一个合法尺寸 —— 不存在
    // "喂进去会病态循环"的风险(那是 inf/NaN 的问题, 上面已硬拒)。
    //
    // 【修正规则, 逐条都有装机依据】
    //   宽 <= 0 → 用容器**自己当前的宽**(它是上一次排版的正确答案);
    //            拿不到就退回屏宽-32(358, 日志实测的真实排版宽度)。
    //            ★不用 UIScreen 满宽 390: v13/v34 已实证 390 排版/358 显示
    //              会导致末行裁断与拉锯闪字(REVERTED-v11 注释详述)。
    //   高 <= 0 → 取绝对值。8/16 正好是 textContainerInset 的量级, 说明
    //            上游算的是 "容器高 - inset", inset 被减了两遍。
    //            取绝对值后 8/16 是一个合法的最小容器高, 排版能正常跑。
    if (newSize.width <= 0 || newSize.height <= 0) {
        CGSize _v65orig = newSize;
        // [V65-FIXSIZE-S] 把原始(未修正)尺寸**提升到函数作用域**。
        // ★clang 实测: 声明写在上面的 if 块内时, 下面的熔断段
        //   "use of undeclared identifier '_v65orig_h'"(4 处)——
        //   即本项目 §19「标识符存在 != 标识符**可见**」第四次同族。
        //   C 的块作用域: 块内声明只到块尾可见, 后面够不着。
        // ⇒ 必须在**函数体开头**声明, 这里只赋值。
        _v65orig_w = newSize.width;
        _v65orig_h = newSize.height;
        if (newSize.width <= 0) {
            // [V65] 取容器自己当前的宽。走 KVC 而不是 `[(id)self width]`:
            // NSTextContainer 是私有类, 直接发消息在 ARC 下要求编译器知道该
            // selector 声明, 会报 "no visible @interface" —— 这正是我担心的
            // 又一处编译红(run#157/run#159 同类)。KVC 纯运行期查找, 无声明依赖。
            CGFloat _w = 0;
            @try {
                NSValue *_wv = [(id)self valueForKey:@"size"];
                if (_wv) _w = (CGFloat)[_wv CGSizeValue].width;
            } @catch (__unused NSException *_e) {
                _w = 0;
            }
            if (!(_w > 1) || !isfinite(_w) || _w > 1e5) {
                // ★★必须走 KVC 而不是 `[UIScreen mainScreen].bounds.width`:
                //   CGRect 的 `.width` / `.height` **不是 struct 成员**, 而是
                //   CoreGraphics 里 `CGGeometry` 这个 **category**(NSGeometry on
                //   macOS / CoreGraphics on iOS)提供的。UIKit 的模块化导入
                //   **不 re-export 它**, 所以本文件写了 `#import <UIKit/UIKit.h>`
                //   仍然报 (CI#162 / run 37275980272 实测):
                //       NSTextContainerSetSizeGuard.m:153:51:
                //       error: no member named 'width' in 'struct CGRect'
                //   ⇒ 走 KVC `valueForKey:@"bounds"` 拿 NSValue 再取 CGSizeValue,
                //     纯运行期查找, 不需要编译器认识任何 category 声明。
                //   ★这也是本项目**第六次**「本地验证手段骗了自己」:
                //     上轮我自建 UIKit 桩做 clang 检查, 桩里给 CGRect 加了
                //     .width 访问器 ⇒ 0 error 的**假绿**。桩比真实 SDK 宽松,
                //     它给不了的保证它会假装能给。
                _w = 0;
                @try {
                    NSValue *_bv = [[UIScreen mainScreen] valueForKey:@"bounds"];
                    if (_bv) _w = (CGFloat)[_bv CGSizeValue].width;
                } @catch (__unused NSException *_e) {
                    _w = 0;
                }
                // 358 = 日志实测的真实排版宽度(iPhone 14/15 屏宽 390 - 32)。
                // ★不用 390 满宽: v13/v34 已实证 390 排版/358 显示会导致
                //   末行裁断与拉锯闪字(REVERTED-v11 注释详述)。
                if (!(_w > 1) || !isfinite(_w) || _w > 1e5) {
                    _w = 358.0;
                }
                _w -= 32.0;
            }
            newSize.width = _w;
        }
        if (newSize.height <= 0) {
            // [V65-FIXSIZE-H] 高度 <= 0 **不能只取 fabs**。
            //
            // 【v65 装机铁证 —— 这次不是"没修", 是"修了个空"】
            // minis-2026-10-05 8.log (17:20:41-17:20:55, iOS 15.5 / iPhone13,2):
            //   size=0.0x0.0 -> 326.0x0.0    × 82507 条日志 (每 32 次打 1 条)
            //   ⇒ 实际进入本分支 **2644129 次**, 全部是 height **0.0**。
            // 而 `fabs(0.0) == 0.0` ⇒ 打印出来的前后尺寸**完全相同**:
            //   "FIXED-NONPOSITIVE size=0.0x0.0 -> 326.0x0.0"  ← 高度 0 → 还是 0
            // ⇒ 所谓"修正转发"对最常见的形态(0x0)是**空操作**:
            //   高度 0 原样喂给 TextKit, 排版出 0 行, 下一帧还是 0。
            // 这就是用户说的"还是有一点点闪、会抖动"的**直接根因**。
            //
            // 【正确做法】0 高不是一个合法容器高(TextKit 认为"没有高度"),
            // 必须夹到一个**能跑排版的最小合法高度**。用 1.0 而不是 0:
            // TextKit 对 height<=0 视为无容器可用, 对极小正高仍会排版。
            CGFloat _ah = fabs(newSize.height);
            if (!(_ah > 1.0)) { _ah = 1.0; }      // 0 / -0 / 亚 1pt 一律抬到 1
            if (_ah > kMaxContainerHeight) { _ah = kMaxContainerHeight; }
            newSize.height = _ah;
        }
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0x1F) == 1) {
            NSLog(@"[TextContainerGuard] [V65] FIXED-NONPOSITIVE size=%.1fx%.1f "
                  @"-> %.1fx%.1f total=%llu container=%p — 修正转发(旧版丢弃=卡字)",
                  _v65orig.width, _v65orig.height, newSize.width, newSize.height,
                  (unsigned long long)gShortCircuitCount,
                  (__bridge void *)self);
        }
        // 不 return —— 继续往下走熔断逻辑, 修正后的尺寸照常转发给 TextKit。
    }"""

# ---- 风暴熔断豁免: 哨兵才计数, 真实排版永不因熔断被丢 ----
V65_STORM_OLD = """    s->commitCount += 1;
    if (s->commitCount > kStormForwardLimit) {
        s->stormed = YES;
    }"""

V65_STORM_NEW = """    // [V65-STORM] 只有**哨兵**尺寸才计入风暴预算; 真实排版高度永不参与。
    //
    // 【装机铁证】v64 之后 (13:21 装机日志) 熔断误伤了 85 次真实排版:
    //   size=358.0x19.0 ×39   ← 一行, 真实高度
    //   size=358.0x41.0 ×46   ← 两行, 真实高度
    // 这些不是哨兵(哨兵是 ≥3000 被压到 2000), 是**真正的行高**。丢掉它们
    // ⇒ 这一帧排版作废 ⇒ 下一帧拿旧高度上屏 ⇒ 用户看到的「打一个字母抖一下」。
    //
    // 【为什么这样切是安全的】熔断(kStormForwardLimit=40)存在的唯一目的是
    // 斩断哨兵驱动的 fillLayoutHole re-entrant 风暴(v4 的 11918ms 卡死)。
    // 真实排版尺寸**不是**风暴源 —— 它进 CoreText 是一次有界的正常排版。
    // 之前把两者混在同一个计数器里, 于是熔断在杀哨兵的路上把真实排版
    // 一起吞了: 这就是「哨兵没治好、真排版先受害」。
    //
    // 判据用高度: ≥ 2000 即已被上面 kProbeHeightCeiling 压到哨兵值, 那才是
    // 风暴源; < 2000 是真实内容高度, 不计预算、不触发熔断。
    // ★为什么写字面量 2000 而不是引用 kProbeHeightCeiling: 那个 const 声明在
    //   本函数体内它自己那段 `{ ... }` 里, 与本处**不在同一作用域**, 直接
    //   引用会编译失败(这正是 run#159/run#157 同类错误的第四次)。写死字面量
    //   并在上面的哨兵压位处加了注释锚点, 两处靠 2000 这个数字对齐。
    if (newSize.height >= 2000.0) {
        s->commitCount += 1;
        if (s->commitCount > kStormForwardLimit) {
            s->stormed = YES;
        }
    } else if (_v65orig_h <= 0.0 || _v65orig_w <= 0.0) {
        // [V65-FIXSIZE-S] **非正高度同样计入风暴预算**。
        //
        // 【v65 装机铁证 —— 上一版的豁免规则漏了最毒的形态】
        // v65 只让"哨兵(≥2000)"计费, 理由是"真实排版高度不该被熔断吞掉"。
        // 但装机日志显示: 2644129 次修正里 **82507 条日志(全部 0x0)** 走的是
        // `_v65orig_h <= 0` 这条路, 它 **既不是哨兵、也不是正常高度**, 而是
        // 上游算崩的产物 —— 恰恰是最该被熔断的东西, 却被豁免了。
        // 后果(14 秒内, 单容器 0x2802b8820):
        //   · 264 万次 KVC 取值 + NSNumber 装箱 ⇒ 内存 151.8MB → **624.2MB**
        //     (17:20:39→17:20:44, +470MB) ⇒ 内存压力 ⇒ **SIGKILL 闪退**
        //   · 同时每次都走完修正+转发 ⇒ 主线程 **6281ms 卡顿**(HangDetector
        //     抓到 UIKitCore/QuartzCore/UIFoundation 满屏栈) ⇒ 抖动
        // ⇒ 抖、卡、崩**三者是同一个根因**, 不是三个病。
        //
        // 【为什么不能靠"每 tick 40 次"现成熔断】
        // 上面的 storm-breaker 是 per-tick 的; 而 0x0 在**每个 tick 都被反复喂**,
        // tick 一换计数就清零 ⇒ 永远不超阈值 ⇒ 永远不熔断。
        // ⇒ 必须让"非正高度"这一类**跨 tick 也计费**, 才可能触发熔断。
        s->commitCount += 1;
        if (s->commitCount > kStormForwardLimit) {
            s->stormed = YES;
            s->nonPositiveStreak += 1;
            if ((s->nonPositiveStreak & 0xF) == 1) {
                NSLog(@"[TextContainerGuard] [WARN] [V65] NONPOSITIVE-STORM "
                      @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f "
                      @"commit=%llu — 非正高度反复喂, 已熔断",
                      (__bridge void *)self, _v65orig_w, _v65orig_h,
                      newSize.width, newSize.height,
                      (unsigned long long)s->commitCount);
            }
        }
    }"""


# =====================================================================
# F7c. v68: 非正尺寸风暴的**真闸门** + 死锁断供
# ---------------------------------------------------------------------
# 【用户反馈】v66/v67b 装机后仍然"卡死" —— 这次日志把三件事全钉死了
#   (minis-2026-10-06.log, 63379 行, 时间窗 01:45:48-01:46:16):
#
#   ① **风暴规模翻了 3.7 倍, 而且闸门一条都没开**
#        [TextContainerGuard] [V65] FIXED-NONPOSITIVE
#            size=0.0x0.0 -> 326.0x1.0  total=1970881
#            container=0x283da6f80   × 61584 条(每 32 次打 1 条)
#        ⇒ 实际进入修正分支 **197 万次**, 11 秒(01:45:56.615→01:46:07.224),
#          **全部集中在同一个容器**。
#        而三条闸门日志全部 **0 次**:
#            storm-breaker SKIP        0
#            NONPOSITIVE-STORM         0
#            NONPOSITIVE-HARDSTOP      0
#
#   ② **内存 35.5MB → 1474.6MB(+1.4GB), 然后进程消失**
#        footprint=35.5 → 54.3 → 73.1 → 250.6 → 422.9 → 563.0
#                 → 742.6 → 873.0 → 1005.4 → 1128.0 → 1345.4 → 1474.6
#        PID 28466 之后日志直接换成 28473 ⇒ 又一次 SIGKILL。
#
#   ③ v66 的下界钳制**确实生效了**(0.0 -> 1.0, 不是 v65 的 0.0)
#      ⇒ v66 的 ① 修对了; 但整机还是崩 ⇒ 病在别处。
#
# =====================================================================
# 【根因 A: nonPositiveStreak 是**死代码** —— v66 修法的三处里有一处是空转】
#
# v66 注入的原文(src/ios/Shared/NSTextContainerSetSizeGuard.m):
#
#     } else if (_v65orig_h <= 0.0 || _v65orig_w <= 0.0) {
#         s->commitCount += 1;
#         if (s->commitCount > kStormForwardLimit) {   // ← 门槛在这里
#             s->stormed = YES;
#             s->nonPositiveStreak += 1;              // ← 累加埋在门槛里
#             ...
#         }
#     }
#
# ★★ `nonPositiveStreak += 1` 被放在 `commitCount > 40` 的**里面**。
#   而 commitCount 是 **per-tick** 的, 由这里清零:
#       if (_newTick) { s->commitCount = 0; s->stormed = NO; }
#   0x0 恰恰是"**每个 tick 只喂一两次**"的形态(它不集中在一个 tick 里,
#   它跟着上游每次排版请求来一次) ⇒ commitCount 永远到不了 40
#   ⇒ `stormed` 永不置位 ⇒ **streak 永不增长** ⇒ 硬闸门永不触发。
#
# ⇒ 这正是 v66 提交说明自己写下的那句话的**反面**:
#     "per-tick 熔断每换 tick 就清零, 而上游每个 tick 都在喂 ⇒ 永远到不了 40
#      ⇒ **永不熔断**"
#   v66 认出了这个病, 却没有把 streak 的累加**搬出**那个门槛。
# ⇒ 结果: 判据第 ⑦ 层(查 `kNonPositiveHardLimit` 存在 + streak 未被清零)
#   **全绿**, 语法合法、编译通过、13 条反向全拦下,
#   而运行时那行 `+= 1` 是**永远执行不到的死代码**。
#   ★这是本项目**第八次**「验证手段骗了自己」:
#     判据问的是"streak 会不会被清零", 病根是"streak 会不会被累加"。
#     前者永远为真, 后者永远为假 —— **问错了问题, 绿灯就是假的**。
#
# =====================================================================
# 【根因 B: 修正值 1.0 是**活锁的燃料** —— 修正本身喂着风暴】
#
# v66 把 `fabs(0.0)==0.0` 抬到了 1.0, 日志确认它生效了
# (size=0.0x0.0 -> **326.0x1.0**)。但 1.0 **没有断掉自反馈**:
#
#   上游算崩 -> 喂 0x0 -> 我们抬成 1.0 -> TextKit 在 1pt 容器上排版
#   -> **放不下任何一行 => 回报 0 行** -> 上游看到"还是 0 行"
#   -> 认为容器该是 0 高 -> **下一帧又喂 0x0** -> ...
#
# 197 万次/11 秒/单容器, 而这 197 万次的**修正结果全是同一个值**(1.0):
# 上游收到 1.0 和收到 0.0 在它眼里是**同一件事**(都是"排不出东西"),
# 于是它的反馈回路一秒都没被改变 ⇒ 风暴以原速跑完 11 秒、吃掉 1.4GB。
#
# ★ 关键区别: v65 的病是"修正成了和原来一样的值"(空操作);
#   v66 的病是"修正成了一个**上游仍然不满意**的值"(活锁)。
#   两者都需要断供, 但断供的**位置**完全不同 ——
#   v65 要改"修正成什么", v66 要改"到底还转不转发"。
#
# =====================================================================
# 【v68 三处修法】
#
# ① **把 streak 累加搬出 per-tick 门槛** —— 直取根因 A。
#    `nonPositiveStreak += 1` 无条件执行(不再以 commitCount 为前提),
#    并保留 per-tick 的 commitCount 熔断不动(那是另一件事, v65 的行为)。
#    ⇒ 0x0 每来一次就记一笔, 跨 tick 累加, 401 次即触发硬闸门。
#
# ② **硬闸门改为"降频放行"而非"永久停止"** —— 治根因 A 的副作用。
#    v66 的 `if (streak > 400) return;` 是**永久**停止转发: 一旦上游
#    持续喂 0x0, 容器高度就永久冻结在最后一个值上 ⇒ **屏幕上一片空白**
#    (这恰恰就是 v61 修掉的"巨大空白"症状的另一种形态)。
#    v68 改成: 命中上限后, **每 kNonPositiveSkipStride 次才放行 1 次**
#    (降频 1/64), 既把 197 万次压到 ~3 万次(止住内存暴涨),
#    又保留"上游万一自愈, 高度还能慢慢追回来"的通道。
#    ★ 这是本条与 v66 的**根本分歧**: v66 认为"停得越彻底越安全",
#      但守卫的唯一职责是让 App 活下去, 不是让它死得更快 ——
#      **永久冻结 = 把内存问题换成空白问题**。
#
# ③ **非正高度的修正值改为"容器上一次的真实高度"** —— 治根因 B。
#    1.0 这个值是猜的; 唯一**已知可用**的高度是**该容器上一次被转发的
#    正高度**(lastGoodHeight, 由本函数在每次转发正高度时记录)。
#    用它代替 1.0: 上游收到的是一个**真实排版过的几何**
#    ⇒ 即使上游继续算崩, 屏幕上也保留着崩溃前的内容(不空白、不闪)，
#    而 197 万次里每次都喂 1.0 只会让 TextKit 反复在 1pt 上排版。
#    无历史(首次就是 0x0)时才退回 1.0 —— 那时至少不是空容器。
#
# 【为什么 ①②③ 必须同版本落地】
#   只做 ①: 闸门能关, 但关的是"永久冻结" ⇒ 空白回来了(回到 v61 症状)。
#   只做 ②: 降频但仍喂 1.0 ⇒ 内存从 1.4GB 降到 ~20MB, 但内容不恢复。
#   只做 ③: 内容保住了, 但每次仍然真转发 197 万次 ⇒ 内存照旧 1.4GB。
#   三条各自都能独立"看起来有效", 这正是必须同版本的判据。

V68_HOIST_OLD = """    CGFloat _v65orig_w = newSize.width;
    CGFloat _v65orig_h = newSize.height;
    if (!isfinite(newSize.width) || !isfinite(newSize.height)) {"""

V68_HOIST_NEW = """    CGFloat _v65orig_w = newSize.width;
    CGFloat _v65orig_h = newSize.height;
    // [V68-HOIST] 容器状态**提前到函数体开头**取。
    //
    // 【为什么必须提升 —— §19「标识符存在 != 可见」同族第五次】
    // v68 要在**非正高度修正段**里读 `s->lastGoodHeight`(用上一次真实高度
    // 代替猜出来的 1.0), 而原来 `holder`/`s` 的获取在那个段**之后**
    // (实测产物: 非正修正段 idx=6644, `GuardState *s` idx=13695)
    // ⇒ 修正段里写 `s->...` 会 clang 报 "use of undeclared identifier"。
    // 与其把 lastGoodHeight 再提升成一个全局/静态变量(多容器会串),
    // 不如把 s 的获取整体前移 —— objc_getAssociatedObject 无副作用,
    // 前移只影响"state 对象创建得早一点", 不改变任何判定语义。
    _NSTextContainerGuardState *holder = objc_getAssociatedObject(self, kGuardStateKey);
    if (!holder) {
        holder = [_NSTextContainerGuardState new];
        objc_setAssociatedObject(self, kGuardStateKey, holder, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    }

    GuardState *s = &holder->state;

    if (!isfinite(newSize.width) || !isfinite(newSize.height)) {"""

V68_ORIGIN_DUP = """    _NSTextContainerGuardState *holder = objc_getAssociatedObject(self, kGuardStateKey);
    if (!holder) {
        holder = [_NSTextContainerGuardState new];
        objc_setAssociatedObject(self, kGuardStateKey, holder, OBJC_ASSOCIATION_RETAIN_NONATOMIC);
    }

    GuardState *s = &holder->state;
"""

V68_ORIGIN_NEW = """    // [V68-HOIST] holder / s 已在本函数**开头**取好(见上方 [V68-HOIST]),
    // 非正高度修正段要用 s->lastGoodHeight, 那段比这里更早。
"""

V68_ELSEIF_OLD = """        s->commitCount += 1;
        if (s->commitCount > kStormForwardLimit) {
            s->stormed = YES;
            s->nonPositiveStreak += 1;
            if ((s->nonPositiveStreak & 0xF) == 1) {
                NSLog(@"[TextContainerGuard] [WARN] [V65] NONPOSITIVE-STORM "
                      @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f "
                      @"commit=%llu — 非正高度反复喂, 已熔断",
                      (__bridge void *)self, _v65orig_w, _v65orig_h,
                      newSize.width, newSize.height,
                      (unsigned long long)s->commitCount);
            }
        }
    }"""

V68_ELSEIF_NEW = """        s->commitCount += 1;
        if (s->commitCount > kStormForwardLimit) {
            s->stormed = YES;
        }
        // [V68-STREAK] **跨 tick 累加必须无条件执行**。
        //
        // 【v68 装机铁证 —— v66 把这一行埋进了 per-tick 门槛里, 它从未执行】
        // minis-2026-10-06.log (iOS 15.5):
        //   size=0.0x0.0 -> 326.0x1.0  total=1970881  container=0x283da6f80
        //   × 61584 条日志(每 32 打 1) ⇒ 实际 **197 万次 / 11 秒 / 单容器**
        //   内存 35.5MB → **1474.6MB**(+1.4GB) ⇒ SIGKILL(PID 28466→28473)
        //   storm-breaker / NONPOSITIVE-STORM / NONPOSITIVE-HARDSTOP **各 0 次**
        //
        // v66 写的是:
        //     if (s->commitCount > kStormForwardLimit) {   // per-tick 门槛
        //         s->stormed = YES;
        //         s->nonPositiveStreak += 1;              // ← 死代码
        //     }
        // 而 commitCount 由 `if (_newTick) { s->commitCount = 0; }` **每 tick 清零**;
        // 0x0 是"每 tick 只喂一两次"的形态 ⇒ commitCount 永远到不了 40
        // ⇒ streak 永不增长 ⇒ 硬闸门永不触发 ⇒ 197 万次全部真转发。
        //
        // ★ 本项目**第八次**「验证手段骗了自己」:
        //   v66 的第 ⑦ 层判据问的是"`nonPositiveStreak` 会不会被清零",
        //   而病根是"它会不会被**累加**"。前者恒真、后者恒假 ——
        //   **问错了问题, 绿灯就是假的**。判据必须问"累加是否在门槛之外"。
        s->nonPositiveStreak += 1;
        if ((s->nonPositiveStreak & 0x3F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V68] NONPOSITIVE-STREAK "
                  @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f "
                  @"streak=%ld tickCommit=%lld — 非正尺寸跨 tick 累加中",
                  (__bridge void *)self, _v65orig_w, _v65orig_h,
                  newSize.width, newSize.height,
                  (long)s->nonPositiveStreak,
                  (long long)s->commitCount);
        }
    }"""

V68_HARDSTOP_OLD = """    if (s->nonPositiveStreak > kNonPositiveHardLimit) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xFF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V65] NONPOSITIVE-HARDSTOP "
                  @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f streak=%ld "
                  @"— 停止转发(容器已有合法几何)",
                  (__bridge void *)self, newSize.width, newSize.height,
                  newSize.width, newSize.height,
                  (long)s->nonPositiveStreak);
        }
        return;
    }"""

V68_HARDSTOP_NEW = """    // [V68-DOWNFREQ] 命中上限后**降频放行**, 不是永久停止转发。
    //
    // 【为什么必须改 v66 的"永久停止"】
    // v66 是 `if (streak > 400) { return; }` —— 一旦触发, 该容器**再也收不到
    // 任何 setSize**。若上游持续算崩(而它正是这么崩了 197 万次), 高度就永久
    // 冻结在最后一个值上 ⇒ 屏幕保留一整块旧几何 ⇒ **巨大空白**。
    // ★ 这就是 v61 刚修掉的症状换了个形态回来: v66 用"永久冻结"止住了内存,
    //   却把内存问题原地换成了空白问题 —— 守卫的职责是让 App 活下去,
    //   **永久冻结是让 App 死得更快**: 它连"上游万一自愈"的可能性都一并删掉了。
    //
    // v68 改成: 上限之后每 kNonPositiveSkipStride 次才真转发 1 次(1/64 降频)。
    //   · 197 万次 → 约 3 万次 ⇒ 内存增速降到 1/64(1.4GB → 约 20MB 量级)
    //   · 上游一旦自愈(哪怕很慢), 高度仍能一帧一帧追回来
    //   · 容器不会失去合法几何: 上一次放行的值本身就是合法的
    if (s->nonPositiveStreak > kNonPositiveHardLimit) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xFF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V68] NONPOSITIVE-DOWNFREQ "
                  @"container=%p streak=%ld — 降频 1/%d 放行(保留上行通道)",
                  (__bridge void *)self, (long)s->nonPositiveStreak,
                  (int)kNonPositiveSkipStride);
        }
        s->nonPositiveSkipTick += 1;
        if (s->nonPositiveSkipTick < kNonPositiveSkipStride) {
            return;   // 本次丢弃: 只丢这一次, 不是永久
        }
        s->nonPositiveSkipTick = 0;   // 本次放行
    }
    // [V68-GOODH] 转发一个**真实排版过的高度**, 记进 lastGoodHeight。
    // 只在高度为正且有限时记录 —— 负值/0 不是"排版过的高度"。
    if (newSize.height > 0.0 && isfinite(newSize.height) &&
        newSize.height <= kMaxContainerHeight) {
        s->lastGoodHeight = newSize.height;
    }"""

# ---- ③ 修正值: 1.0 -> lastGoodHeight ----
V68_FIXH_OLD = """            CGFloat _ah = fabs(newSize.height);
            if (!(_ah > 1.0)) { _ah = 1.0; }      // 0 / -0 / 亚 1pt 一律抬到 1
            if (_ah > kMaxContainerHeight) { _ah = kMaxContainerHeight; }
            newSize.height = _ah;"""

V68_FIXH_NEW = """            CGFloat _ah = fabs(newSize.height);
            // [V68-GOODH] 修正值**优先用该容器上一次真实排版过的高度**。
            //
            // 【为什么 1.0 反而是活锁的燃料 —— v66 装机日志实证】
            // v66 把 fabs(0.0)==0.0 抬到 1.0, 生效了
            // (日志实测 size=0.0x0.0 -> **326.0x1.0**), 但整机仍然崩:
            //   · 197 万次修正的**结果全是同一个值 1.0**
            //   · 上游收到 1.0 和收到 0.0 在它眼里是同一件事:
            //     **都排不出任何东西**(1pt 装不下任何一行)
            //   · 于是它的自反馈回路一秒都没被改变:
            //     算崩→喂0→抬成1→排0行→上游仍算崩→再喂0 ...
            //   风暴以原速跑完 11 秒、吃掉 1.4GB。
            //
            // ★ v65 的病是"修正成了和原来一样的值"(空操作);
            //   v66 的病是"修正成了一个**上游仍然不满意**的值"(活锁)。
            //   两者要断的位置不同: v65 改"修正成什么", v66 改"还转不转发"。
            //
            // 唯一**已知可用**的高度是本容器上一次被转发的正高度
            // (lastGoodHeight, 由下面 [V68-GOODH] 在每次转发正高度时记录)。
            // 用它: 上游即便继续崩, 屏幕上仍保留崩溃前的真实几何
            //       (不空白、不闪), 而不是反复让 TextKit 在 1pt 上空排。
            // 无历史(首次就是 0x0)时才退回 1.0 —— 那时至少不是空容器。
            if (!(_ah > 1.0)) {
                CGFloat _prev = s->lastGoodHeight;
                _ah = (_prev > 1.0 && isfinite(_prev) &&
                       _prev <= kMaxContainerHeight) ? _prev : 1.0;
            }
            if (_ah > kMaxContainerHeight) { _ah = kMaxContainerHeight; }
            newSize.height = _ah;"""

V68_CONST_OLD = """static const NSInteger kNonPositiveHardLimit = 400;"""

V68_CONST_NEW = """static const NSInteger kNonPositiveHardLimit = 400;

// [V68-DOWNFREQ] 命中 kNonPositiveHardLimit 之后的**放行步长**: 每 64 次里放 1 次。
// v66 是"永久停止转发", 代价是容器高度永久冻结 ⇒ 屏幕保留一整块旧几何
// ⇒ 巨大空白(v61 刚修掉的症状换个形态回来)。
// 降频 1/64 把 197 万次压到约 3 万次(内存增速 1.4GB → 20MB 量级),
// 同时**保留上行通道**: 上游一旦自愈, 高度仍能一帧一帧追回来。
static const NSInteger kNonPositiveSkipStride = 64;"""

V68_FIELD_OLD = """    NSInteger nonPositiveStreak;
    BOOL initialized;
} GuardState;"""

V68_FIELD_NEW = """    NSInteger nonPositiveStreak;
    // [V68-GOODH] 该容器**上一次被转发的真实高度** (>0)。非正高度修正时优先用它,
    // 而不是猜一个 1.0 —— 1.0 装不下任何一行, 上游会继续算崩(活锁)。
    CGFloat lastGoodHeight;
    // [V68-DOWNFREQ] 降频丢弃的游标: 每 kNonPositiveSkipStride 次放行 1 次。
    NSInteger nonPositiveSkipTick;
    BOOL initialized;
} GuardState;"""


def fix_nonpositive_downfreq_v68(t):
    """v68 注入: 非正尺寸风暴的真闸门 + 降频放行 + 真实高度回填。

    幂等: 已有 [V68-STREAK] 原样返回。
    """
    if "[V68-STREAK]" in t:
        return t
    # 顺序要紧: 先改 else-if 里的 streak 累加, 再改硬闸门。
    # ★顺序要紧: **先删原处, 再 hoist**。
    #   反过来(先 hoist 后删)会让 ORIGIN_DUP 锚点在文件里出现 **2 次**
    #   (新插入的那份与原处那份逐字相同) ⇒ _v60_replace1 的 count==1
    #   防呆立刻报错(实测首次跑就撞上了)。防呆本身是对的, 错的是顺序。
    t = _v60_replace1(t, V68_ORIGIN_DUP, V68_ORIGIN_NEW,
                       "v68⓪ 原处二次获取改为注释(否则重复声明 holder/s 编译红)")
    t = _v60_replace1(t, V68_HOIST_OLD, V68_HOIST_NEW,
                       "v68⓪ holder/s 提升到函数体开头(修正段要读 lastGoodHeight)")
    t = _v60_replace1(t, V68_ELSEIF_OLD, V68_ELSEIF_NEW,
                       "v68① streak 累加搬出 per-tick 门槛(旧版是死代码)")
    t = _v60_replace1(t, V68_HARDSTOP_OLD, V68_HARDSTOP_NEW,
                       "v68② 硬闸门改降频放行 + ③ 记录 lastGoodHeight")
    t = _v60_replace1(t, V68_FIXH_OLD, V68_FIXH_NEW,
                       "v68③ 非正高度修正值改用 lastGoodHeight(1.0 是活锁燃料)")
    # 常量与结构体字段要放在**注入点之后**: v65/v66 是先注入 stormbreaker
    # (它创建 kNonPositiveHardLimit 与 nonPositiveStreak 字段), v68 才能改它们。
    t = _v60_replace1(t, V68_CONST_OLD, V68_CONST_NEW,
                       "v68② 新增降频步长 kNonPositiveSkipStride")
    t = _v60_replace1(t, V68_FIELD_OLD, V68_FIELD_NEW,
                       "v68②③ GuardState 新增 lastGoodHeight / nonPositiveSkipTick")
    return t


# ============================================================================
# v69 —— 「点击选择模型就卡死」: 容器工厂形态的风暴, 所有 per-container 计数全废
# ============================================================================
#
# 【装机铁证 —— minis-2026-10-06 2.log (iOS 15.5 / iPhone12, PID 32470)】
# 时间线:
#   05:06:11~05:06:22  正常期: short-circuited **37** 条, NONPOSITIVE-STREAK 22 条
#                      (tick=1426/1520 等真实 tick, 容器 0x282537c00/0x28257fa20
#                       稳定复用 ⇒ 守卫**工作正常**)
#   05:06:22           用户点击「选择模型」
#   05:06:22~05:06:33 风暴期 11 秒: FIXED-NONPOSITIVE 61156 条(每 32 打 1)
#                     ⇒ 实际 **1,957,633 次**; 每秒 5000~6700 条日志 ⇒ 约 10 万次/秒
#   05:06:34          进程死亡, PID 32470 → **32493** 重启
#
# 风暴期内六个异常, 全部指向同一个根因:
#   (1) short-circuited        = **0**    (正常期 37 条 —— 守卫整个失灵)
#   (2) NONPOSITIVE-STREAK     = 22 条, 且**无一例外全是 streak=1**
#   (3) NONPOSITIVE-DOWNFREQ   = **0**    (v68②降频闸门一次没开)
#   (4) storm-breaker          = **0**    (v4 熔断一次没触发)
#   (5) 修正值恒为 326.0x**1.0**            (v68③ lastGoodHeight 从未生效)
#   (6) container 恒为 0x2825dfb60 (61151 条)
#
# 【反证: 为什么只能是"每次都是新容器"】
#   · 每秒 10 万次调用 ⇒ runloop tick 不可能变化这么快
#     ⇒ `s->lastTick == gRunloopTick` 恒真;
#   · 尺寸恒为 326.0x1.0 ⇒ `CGSizeEqualToSize(s->lastSize, newSize)` 恒真;
#   · 于是 377 行的 dedupe 只要 `s->initialized == YES` 就必然命中
#     ⇒ 应该打出几十万条 short-circuited ⇒ **实测 0 条**;
#   · ⇒ `s->initialized == NO` ⇒ **每次拿到的都是全新的 GuardState**;
#   · holder 用 OBJC_ASSOCIATION_RETAIN_NONATOMIC 挂在容器上, 容器活着 holder
#     必活着 ⇒ **NSTextContainer 对象本身每次都是新建的**。
#     地址恒为 0x2825dfb60 只是 malloc 复用同一块内存(旧对象释放后新对象落在同址)。
#
# 【为什么 v68 三条修法在同一形态下全部落空】
#   v68 的三个计数器 —— nonPositiveStreak / nonPositiveSkipTick / lastGoodHeight
#   —— 全是 **per-container**。而本形态的风暴源恰恰是**容器的不稳定**:
#   SwiftUI measure 每个候选项时新建一个 NSTextContainer, 此时该项尚未布局
#   ⇒ 宽度 0 ⇒ 喂 0x0 ⇒ 守卫修正转发 ⇒ TextKit 在 1pt 上空排 ⇒ 高度回报不可用
#   ⇒ SwiftUI 重新 measure ⇒ **又新建一个容器** ⇒ 死循环。
#   · streak:      每个新容器从 0 起, 累加 1 次就随容器消失 ⇒ 永不到 400 ⇒ (3)
#   · skipTick:    per-container 游标恒为 0 ⇒ 每次都放行 ⇒ 降频完全落空
#   · lastGoodH:   每个新容器恒为 0 ⇒ 修正值退回 1.0 ⇒ (5)
#   · commitCount/stormed: 新容器 + 每 tick 清零 ⇒ (4)
#
# ★ v68 的设计盲区: **所有防御都建在"容器是稳定对象"这个假设上, 而风暴源
#   恰恰是容器的不稳定**。验证手段又一次骗了自己 —— 第十三次: 判据问的是
#   "这些计数器会不会累加"(会), 却从没问"它们挂在的那个对象活得够不够久"。
#
# 【v69 修法: 把风暴计数从 per-container 提升到 per-process(进程级)】
#   ① 新增 gGlobalNonPositiveStreak —— 所有容器共享累加, 容器重建也断不了;
#   ② 降频闸门判据改为 `per-container 超限 OR 全局超限`;
#   ③ 降频游标改用**全局** gGlobalSkipTick —— per-container 游标恒 0 是废的;
#   ④ lastGoodHeight 加**全局兜底** gGlobalLastGoodHeight, 并在每次转发正高度
#      时同步写入 —— 这是容器每次重建时唯一还能拿到"真实排版高度"的地方;
#   ⑤ 自愈退出: 连续收到正尺寸 >= kNonPositiveGoodRunReset 次 ⇒ 全局计数清零。
#      没有它, 一次风暴会让 App 永久处于降频态(第三条「永久冻结」的同类错误)。
#
# 预期: 196 万次 → 约 3 万次(1/64), 且上游拿到的高度是**真实高度**而非 1.0
#       ⇒ 自反馈回路被打断 ⇒ 风暴提前收敛, 不只是"跑完 196 万次再死"。

V69_GLOBAL_OLD = """static const NSInteger kNonPositiveSkipStride = 64;"""

V69_GLOBAL_NEW = """static const NSInteger kNonPositiveSkipStride = 64;

// [V69-GLOBAL] **进程级**非正尺寸风暴计数。
//
// 【为什么必须有全局一份 —— 见上方 v69 装机铁证】
// 风暴的第二种形态是"容器工厂": 上游每次循环新建一个 NSTextContainer,
// 用完即弃。此时所有 per-container 计数器(含 v68 的三条)随容器一起消失,
// 恒为初始值 ⇒ 累加不动、游标恒 0、历史高度恒 0 ⇒ 闸门永远不开。
// 进程级计数与容器生命周期无关, 是这种形态下**唯一**还能累加的东西。
static NSInteger gGlobalNonPositiveStreak = 0;
// [V69-GLOBAL] 进程级降频游标。必须是全局的: per-container 的
// nonPositiveSkipTick 在容器重建时恒为 0 ⇒ 每次都放行 ⇒ 降频完全落空。
static NSInteger gGlobalSkipTick = 0;
// [V69-GLOBAL] 进程级"上一次真实排版过的高度"。容器是新的时候,
// s->lastGoodHeight 恒为 0, 这是唯一还能拿到的真实高度。
static CGFloat gGlobalLastGoodHeight = 0.0;
// [V69-GLOBAL] 连续收到**正**尺寸的计数, 用于风暴结束后退出降频态。
static NSInteger gGlobalGoodRun = 0;
// [V69-GLOBAL] 进程级硬上限: 与 per-container 的 400 同量级。正常排版里
// 非正尺寸最多偶发几次; 连续 400 次意味上游已进入死循环。
static const NSInteger kNonPositiveGlobalLimit = 400;
// [V69-GLOBAL] 连续这么多次正尺寸即认定上游已自愈, 全局计数清零。
// 取 128 而不是更大: 一帧正常排版里正尺寸 setSize 远多于 128 次,
// 取大了会让 App 在一次风暴后长期滞留降频态。
static const NSInteger kNonPositiveGoodRunReset = 128;"""

V69_STREAK_OLD = """        s->nonPositiveStreak += 1;
        if ((s->nonPositiveStreak & 0x3F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V68] NONPOSITIVE-STREAK "
                  @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f "
                  @"streak=%ld tickCommit=%lld — 非正尺寸跨 tick 累加中",
                  (__bridge void *)self, _v65orig_w, _v65orig_h,
                  newSize.width, newSize.height,
                  (long)s->nonPositiveStreak,
                  (long long)s->commitCount);
        }
    }"""

V69_STREAK_NEW = """        s->nonPositiveStreak += 1;
        if ((s->nonPositiveStreak & 0x3F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V68] NONPOSITIVE-STREAK "
                  @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f "
                  @"streak=%ld tickCommit=%lld — 非正尺寸跨 tick 累加中",
                  (__bridge void *)self, _v65orig_w, _v65orig_h,
                  newSize.width, newSize.height,
                  (long)s->nonPositiveStreak,
                  (long long)s->commitCount);
        }
        // [V69-GLOBAL]① 进程级累加: 容器每次重建也断不了这一条。
        gGlobalNonPositiveStreak += 1;
        gGlobalGoodRun = 0;
        if ((gGlobalNonPositiveStreak & 0x3F) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V69] GLOBAL-STREAK "
                  @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f "
                  @"gstreak=%ld cstreak=%ld — 进程级非正尺寸累加中",
                  (__bridge void *)self, _v65orig_w, _v65orig_h,
                  newSize.width, newSize.height,
                  (long)gGlobalNonPositiveStreak,
                  (long)s->nonPositiveStreak);
        }
        // [V76-NONPOS-SHORTCIRCUIT] 非正原始尺寸直接短路, **不转发 CoreText**。
        // 与 NSTextContainerSetSizeGuard.m 第 ~5xx 行 V76 改动一致: 非正尺寸
        // (0x-16/0x0/0x-8) 被 V65 修正转发会触发 layout 活锁(实测 83526 次转发
        // → 8.3 万次 layout → objc_sync_enter 锁卡死 → 7349ms HANG → SIGKILL)。
        // 直接短路斩断活锁; 容器保留合法几何(lastGoodHeight), 文字照常显示。
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xFF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V76] NONPOSITIVE-SHORT-CIRCUIT "
                  @"container=%p orig=%.1fx%.1f streak=%ld gstreak=%ld "
                  @"— 非正尺寸直接短路(不转发 CoreText)",
                  (__bridge void *)self, _v65orig_w, _v65orig_h,
                  (long)s->nonPositiveStreak, (long)gGlobalNonPositiveStreak);
        }
        return;
    } else if (_v65orig_h > 0.0 && _v65orig_w > 0.0) {
        // [V69-GLOBAL]⑤ 自愈退出: 连续收到正尺寸 ⇒ 上游已恢复, 全局计数清零。
        //
        // 【为什么必须显式退出】降频是"每 64 次放 1 次", 若风暴结束后计数
        // 不清零, App 会**永久**滞留降频态 —— 与 v66「永久冻结」同类错误:
        // 那一次是冻结单个容器, 这一次是冻结整个进程, 更狠。
        //
        // 判据用**原始**尺寸而不是修正后的: 修正后的值恒为正(守卫干的正是
        // 这件事), 用它判断"上游是否自愈"会永远为真 ⇒ 计数刚加上就被清掉。
        // 走到本分支意味着: 高度 <2000(非哨兵) 且 原始宽高都为正 —— 即
        // 上游这次**真的**算出了一个合法尺寸。
        gGlobalGoodRun += 1;
        if (gGlobalGoodRun >= kNonPositiveGoodRunReset) {
            if (gGlobalNonPositiveStreak > 0) {
                NSLog(@"[TextContainerGuard] [INFO] [V69] GLOBAL-RECOVER "
                      @"gstreak=%ld — 连续正尺寸已 %d 次, 全局风暴计数清零",
                      (long)gGlobalNonPositiveStreak,
                      (int)kNonPositiveGoodRunReset);
            }
            gGlobalNonPositiveStreak = 0;
            gGlobalGoodRun = 0;
        }
    }"""

V69_GATE_OLD = """    if (s->nonPositiveStreak > kNonPositiveHardLimit) {"""

V69_GATE_NEW = """    // [V69-GLOBAL]② 闸门判据加**进程级**一路: 容器工厂形态下
    // per-container 的 streak 恒为 1, 只有全局这一路可能超限。
    if ((s->nonPositiveStreak > kNonPositiveHardLimit) ||
        (gGlobalNonPositiveStreak > kNonPositiveGlobalLimit)) {"""

V69_SKIP_OLD = """        s->nonPositiveSkipTick += 1;
        if (s->nonPositiveSkipTick < kNonPositiveSkipStride) {
            return;   // 本次丢弃: 只丢这一次, 不是永久
        }
        s->nonPositiveSkipTick = 0;   // 本次放行"""

V69_SKIP_NEW = """        // [V69-GLOBAL]③ 游标必须用**全局**的: 容器每次都是新的,
        // per-container 的 nonPositiveSkipTick 恒为 0 ⇒ 每次都走到"放行",
        // 降频等于没写(这正是 v68 装机 196 万次一次没减的原因)。
        gGlobalSkipTick += 1;
        if (gGlobalSkipTick < kNonPositiveSkipStride) {
            return;   // 本次丢弃: 只丢这一次, 不是永久
        }
        gGlobalSkipTick = 0;   // 本次放行"""

V69_FIXH_OLD = """            if (!(_ah > 1.0)) {
                CGFloat _prev = s->lastGoodHeight;
                _ah = (_prev > 1.0 && isfinite(_prev) &&
                       _prev <= kMaxContainerHeight) ? _prev : 1.0;
            }"""

V69_FIXH_NEW = """            if (!(_ah > 1.0)) {
                CGFloat _prev = s->lastGoodHeight;
                if (!(_prev > 1.0 && isfinite(_prev) &&
                      _prev <= kMaxContainerHeight)) {
                    // [V69-GLOBAL]④ 本容器无历史(**容器是新建的**, 这正是
                    // 「选择模型」风暴的形态) ⇒ 退回进程级历史高度。
                    // 没有这一层兜底, 修正值恒为 1.0 ⇒ 上游拿到 1.0 和拿到
                    // 0.0 同样排不出东西 ⇒ 自反馈回路一秒都没断(活锁)。
                    _prev = gGlobalLastGoodHeight;
                }
                _ah = (_prev > 1.0 && isfinite(_prev) &&
                       _prev <= kMaxContainerHeight) ? _prev : 1.0;
            }"""

V69_GOODH_OLD = """    if (newSize.height > 0.0 && isfinite(newSize.height) &&
        newSize.height <= kMaxContainerHeight) {
        s->lastGoodHeight = newSize.height;
    }"""

V69_GOODH_NEW = """    // [V69-GOODH-PURE] 只有**上游真的算出了正尺寸**时才记历史高度。
    //
    // 【v68 的 GOODH 有个自锁 bug —— 装机日志 (5) 的第二层原因】
    // v68 的条件只看 `newSize.height > 0`。而 0x0 经过守卫修正后是 **1.0**,
    // 1.0 > 0 ⇒ 被当成"真实排版过的高度"记进 lastGoodHeight; 下一次 0x0
    // 再来, 取到的"历史"就是自己上次造出来的 1.0 ⇒ 修正值恒为 1.0
    // ⇒ 上游拿到 1.0 和拿到 0.0 一样排不出东西 ⇒ **活锁一圈没断**。
    // 日志实测修正值恒为 326.0x**1.0**, 与此完全吻合。
    //
    // ⇒ 必须按**原始**尺寸判定: 只有 orig 宽高都为正, 这次才是"上游算对了";
    //   守卫修正出来的值**永远不是**"排版过的真实高度"。
    // 另外排除 >= 2000: 那是哨兵钳位后的值, 同样不是真实内容高度。
    if (newSize.height > 0.0 && isfinite(newSize.height) &&
        newSize.height <= kMaxContainerHeight &&
        newSize.height < 2000.0 &&
        _v65orig_h > 0.0 && _v65orig_w > 0.0) {
        s->lastGoodHeight = newSize.height;
        // [V69-GLOBAL]④ 同步写进程级历史: 只有这里记下来,
        // 下一个**新建**的容器才可能在崩溃时拿到一个真实高度。
        gGlobalLastGoodHeight = newSize.height;
    }"""


def fix_nonpositive_global_v69(t):
    """v69 注入: 非正尺寸风暴的计数从 per-container 提升到进程级。

    【为什么必须提升, 而不是继续修 per-container 的累加位置】
    v66 的病是"累加语句埋在门槛里"(位置错), v68 已修;
    v69 的病是"计数挂的对象活不过一轮循环"(**宿主错**)。
    位置修对了也没用 —— 计数随宿主一起被丢弃。这类错误的判据不能只问
    "语句在不在、会不会执行", 必须问"**它的宿主活得够不够久**"。

    幂等: 已有 [V69-GLOBAL] 原样返回。
    """
    if "[V69-GLOBAL]" in t:
        return t
    t = _v60_replace1(t, V69_GLOBAL_OLD, V69_GLOBAL_NEW,
                       "v69① 新增进程级风暴计数/游标/历史高度 + 两个常量")
    t = _v60_replace1(t, V69_STREAK_OLD, V69_STREAK_NEW,
                       "v69①⑤ else-if 内加全局累加, 并补 else 分支做自愈退出")
    t = _v60_replace1(t, V69_GATE_OLD, V69_GATE_NEW,
                       "v69② 降频闸门判据加进程级一路")
    t = _v60_replace1(t, V69_SKIP_OLD, V69_SKIP_NEW,
                       "v69③ 降频游标改用全局(per-container 游标恒 0 = 废)")
    t = _v60_replace1(t, V69_FIXH_OLD, V69_FIXH_NEW,
                       "v69④ 修正值加进程级历史高度兜底(容器新建时唯一可用)")
    t = _v60_replace1(t, V69_GOODH_OLD, V69_GOODH_NEW,
                       "v69④ 转发正高度时同步写进程级历史")
    return t


def fix_guard_fixsize_v65(t):
    """v65 注入: 守卫不再丢弃有限非正尺寸, 且熔断只对哨兵生效。

    【为什么这两条必须一起做】
      ① 丢弃 ⇒ TextKit 保留过期几何 ⇒ 卡字(61 次实证)
      ② 熔断吞真实排版 ⇒ 排版作废 ⇒ 抖动(85 次实证)
    只做 ①: 排版能跑了, 但一帧内被熔断吞掉, 仍抖。
    只做 ②: 排版不丢, 但脏尺寸(宽 0)仍让 TextKit 排错, 仍卡字。
    ⇒ 必须同版本落地, 否则两边的症状互相掩盖, 又变成"看不出哪条有效"。

    幂等: 已有 [V65-FIXSIZE] 原样返回。
    """
    if "[V65-FIXSIZE]" in t:
        return t
    t = _v60_replace1(t, V65_REJECT_OLD, V65_REJECT_NEW,
                       "v65 有限非正尺寸改为修正转发(旧版丢弃=卡字)")
    t = _v60_replace1(t, V65_STORM_OLD, V65_STORM_NEW,
                       "v65 风暴熔断只对哨兵计费(旧版吞真实排版=抖动)")
    return t


def fix_guard_circuit_breaker_v73(t):
    """v73 注入: 非正尺寸风暴**进程级硬降频步长放大**(64 → 4096)。

    【本次装机铁证 —— minis-2026-10-06.log (iOS 15.5 / iPhone13,2), V72 仍卡死】
    12:34:07 total=65 → 12:34:13 total=430977(6 秒 43 万次 FIXED-NONPOSITIVE 0x0
    修正转发); 崩溃报告 HANG=7196ms, 堆栈全在 UIFoundation → SIGKILL。
    v68 固定降频 1/64 在「点击选择模型」SwiftUI measure 候选项的
    「新建容器→0x0→修正转发→1pt 空排→回报不可用→重 measure→又新建容器」
    re-entrant 死循环里, 仍转发约 6800 次/秒 → 主线程打满 → 看门狗 SIGKILL。

    【为什么是放大步长, 不是硬熔断 / 不是改闸门结构】
    ⑨ 铁律(verify_guard_v65 第⑨层): 命中上限后必须是**降频放行**(含
    gGlobalSkipTick + kNonPositiveSkipStride), 否则判为"永久冻结"→ CI 红,
    且真机会巨大空白。硬熔断(v73 第一版)踩中它 → 红。
    降频结构本身是 v68/v69 已落地、CI 已验证通过的; 只需把步长放大即可把
    实际转发压到非饱和量级, 且不动 S15 反向锚点(gGlobalSkipTick <
    kNonPositiveSkipStride 字面保留)。

    【数学】转发数 F = 外部调用/(N-1), N=降频步长:
      · N=64   → F≈6800/s → 主线程饱和 → SIGKILL(现状, V72 实测)
      · N=4096 → F≈17/s   → 主线程空闲 → 看门狗不杀
    所以把 kNonPositiveSkipStride 从 64 提到 4096。前 kNonPositiveGlobalLimit
    次(进程级 gGlobalNonPositiveStreak 未超限)仍全转发, 建立 lastGoodHeight;
    之后 1/4096 放行 —— re-entrant 死循环不再打满主线程, 当前 tick 尽快结束,
    上游下一轮从干净状态重算。

    幂等: 已是 4096 原样返回。
    """
    if "kNonPositiveSkipStride = 4096" in t:
        return t
    OLD = "static const NSInteger kNonPositiveSkipStride = 64;"
    NEW = ("static const NSInteger kNonPositiveSkipStride = 4096;\n"
           "// [V73] 非正尺寸风暴进程级硬降频步长 64→4096: 实测「点击选择模型」re-entrant\n"
           "// 死循环 6 秒 43 万次 0x0 修正转发(v68 1/64 仍转发 ~6800/s 打满主线程 ⇒ SIGKILL)。\n"
           "// F=外部调用/(N-1): N=4096 ⇒ F≈17/s, 主线程不再饱和 ⇒ 看门狗不杀;\n"
           "// 前 kNonPositiveGlobalLimit 次仍全转发建立 lastGoodHeight。保留 ⑨ 与 S15 锚点。")
    if OLD in t:
        t = t.replace(OLD, NEW)
    return t


# [V76-BANNER] 装机确认横幅。注释键 / static 名 / NSLog 串必须三位一体。
# ★半升级(本轮真实故障): 注释已是 [V76-MARKER], 运行时仍是
#   _v75GuardLogged + build=V75。用户装机日志只看得见 NSLog,
#   于是「装的还是 V75」。生成器若 `if [V76-MARKER]: return` 会把半升级冻住。
_V76_BANNER = (
    "    // [V76-MARKER] 一次性打印构建版本(装机确认)。V76 = V75 persistentStorm + "
    "**V76 非正尺寸跨 tick 持久短路**(非正原始尺寸 0x-16/0x0/0x-8 到达时直接 return 不转发 CoreText, "
    "斩断 V65 修正转发引发的 layout 活锁; 容器保留 lastGoodHeight 合法几何, 文字照常显示, 上游算对即自动 re-arm)。"
    "专治 V75 仍未斩净的「选择模型卡死」(实测 8.3 万次非正转发→objc_sync_enter 锁卡死→7349ms HANG→SIGKILL)。\n"
    "    static BOOL _v76GuardLogged = NO;\n"
    "    if (!_v76GuardLogged) {\n"
    "        _v76GuardLogged = YES;\n"
    "        NSLog(@\"[Minis-Guard] build=V76 ios15-pickerCap+inputFlicker+reentrantBreak+persistentStorm+nonPositiveShortCircuit "
    "(cappedEntriesByInstance 非搜索态截断 150; intrinsicContentSize 反馈环路守卫斩输入闪屏; "
    "setSize: 递归哨兵斩断重入环; 同尺寸风暴跨 tick 持久熔断斩断选择模型 measure 死循环; "
    "**V76 非正尺寸(0x-16/0x0)直接短路不转发斩断 layout 活锁**)\");\n"
    "    }\n\n"
)


def _is_true_v76_banner(t):
    # V77+ 横幅是后继, 本函数不得把 V77 NSLog 打回 V76。
    if ("_v77GuardLogged" in t or 'NSLog(@"[Minis-Guard] build=V77 ' in t
            or "_v78GuardLogged" in t or 'NSLog(@"[Minis-Guard] build=V78 ' in t):
        return True
    return ("[V76-MARKER]" in t
            and "_v76GuardLogged" in t
            and 'NSLog(@"[Minis-Guard] build=V76 ' in t
            and "nonPositiveShortCircuit" in t
            and "_v75GuardLogged" not in t
            and "_v74GuardLogged" not in t
            and "_v72GuardLogged" not in t)


_V76_NSLOG = (
    'NSLog(@"[Minis-Guard] build=V76 ios15-pickerCap+inputFlicker+reentrantBreak+persistentStorm+nonPositiveShortCircuit '
    '(cappedEntriesByInstance 非搜索态截断 150; intrinsicContentSize 反馈环路守卫斩输入闪屏; '
    'setSize: 递归哨兵斩断重入环; 同尺寸风暴跨 tick 持久熔断斩断选择模型 measure 死循环; '
    '**V76 非正尺寸(0x-16/0x0)直接短路不转发斩断 layout 活锁**)");'
)


def _upgrade_guard_banner_v76(t):
    """横幅升级必须独立于 IOS15-FIX-STORM 早退。

    已注入树带着 IOS15-FIX-STORM, 整函数早退 ⇒ 横幅升级一行都跑不到
    ⇒ 半升级(注释 V76 / 运行时 V75)被永久冻住。这正是本轮故障。
    """
    if _is_true_v76_banner(t):
        return t
    t = re.sub(r"_v7[0-5]GuardLogged", "_v76GuardLogged", t)
    t = re.sub(
        r'NSLog\(@"\[Minis-Guard\] build=V7[0-6][^"]*"\);',
        _V76_NSLOG,
        t,
        count=1,
    )
    for oldk in ("[V75-MARKER]", "[V74-MARKER]", "[V72-MARKER]"):
        if oldk in t:
            t = t.replace(oldk, "[V76-MARKER]", 1)
            break
    if _is_true_v76_banner(t):
        return t
    needle = "    // [V74-REENT] 递归哨兵:"
    if needle in t and "_v76GuardLogged" not in t:
        t = t.replace(needle, _V76_BANNER + needle, 1)
    return t


def fix_textcontainer_guard_stormbreaker(t):
    # ★横幅升级必须在早退之外: 已注入树(IOS15-FIX-STORM 在)也要能
    #   从半升级走到真 V76。早退只跳过风暴体注入, 不跳过横幅。
    if "IOS15-FIX-STORM" in t:
        return _upgrade_guard_banner_v76(t)
    # ---- ① 常量: 风暴阈值 + 有限高度上限 ----
    OLD1 = '''static const NSInteger kRepeatThreshold = 2;'''
    NEW1 = '''static const NSInteger kRepeatThreshold = 2;

// [IOS15-FIX-STORM] 风暴熔断阈值: 同一容器在同一 runloop tick 内被转发 setSize:
// 超过这个次数, 停止转发、保留已提交几何, 斩断 CoreText fillLayoutHole 的
// re-entrant 链 (实测完整堆栈 CoreFoundation + #1-#7 全 CoreText, 最长 11918ms
// 主线程卡死)。40 是经验值: 正常一 tick 内单个容器合法 setSize 远不到此数
// (多 cell 批量排版时每容器也就几次), 但 re-entrant 风暴会一 tick 内打几千次。
static const NSInteger kStormForwardLimit = 40;

// [V65-FIXSIZE-S] 非正尺寸(宽或高 <= 0)的**跨 tick** 硬上限。
// 装机实测(8.log): 单容器 14 秒被喂 2644129 次 0x0, 内存 +470MB ⇒ SIGKILL。
// 40 太大(单条消息正常排版也就几次), 这里取一个既能止住风暴、又不会误伤
// 正常排版的值: 正常一轮排版里"上游算崩"最多偶发 1-2 次, 连续 400 次
// 意味着上游已经进入死循环, 此时停止转发是唯一正确的选择。
static const NSInteger kNonPositiveHardLimit = 400;

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
    // [V65-FIXSIZE-S] 非正高度连续命中次数。**跨 tick 累加**(故意不清零):
    // 装机实测 0x0 在每个 tick 都被反复喂, 只按 tick 清零 ⇒ 永不熔断 ⇒
    // 单容器 14 秒 264 万次 ⇒ 内存 +470MB ⇒ SIGKILL。跨 tick 累加才能拦住它。
    NSInteger nonPositiveStreak;
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

    // [V74-REENT] 递归哨兵: 斩断 setSize: → gOriginalSetSize → layout → setSize: 重入环。
    // 实测 V73 启动期 setSize: 被重入调用 ~120 万次(storm-breaker SKIP total 飙到
    // 1239121), 根因是 gOriginalSetSize 触发布局 → 布局再调 setSize: → 再转发... 的主线程
    // 锁自旋(NSAllocateObject + objc_sync_enter / os_unfair_recursive_lock)→ 看门狗 SIGKILL。
    // 重入态(正在 gOriginalSetSize 内部)直接 return, 不转发原始实现 ⇒ 不再触发布局 ⇒ 环断开;
    // 仅重入期间生效, 平时正常转发(非永久冻结, 满足断言69 ⑨)。哨兵置于 GuardState *s 之后
    // (逻辑等价), 以保留下游 v68 的多行锚点(以 `}` 与 `GuardState *s` 之间无插入为前提)。
    static BOOL _gSetSizeForwarding = NO;
    if (_gSetSizeForwarding) {
        return;   // 重入: 保留上次已提交几何, 不再触发布局
    }

    // [IOS15-FIX-STORM] 风暴熔断: 本 tick 已经触发过熔断后, 只丢弃"同尺寸重复"
    // (自旋源); 不同尺寸的调用仍有限放行 —— v9 实证: 无差别丢弃会把正确的宽度
    // 修正 (358x550.9) 连坐丢掉, 容器宽停在旧值 → 文字不换行 → 横向裁切。
    if (s->initialized && s->lastTick == gRunloopTick && s->stormed) {
        if (CGSizeEqualToSize(s->lastSize, newSize)) {
            gShortCircuitCount += 1;
            if ((gShortCircuitCount & 0xFFFFF) == 1) {
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
        // [V75-PERSISTENT-STORM] 必须在覆盖 s->lastSize 之前算好 _sizeChanged:
        // 它比的是「本次到达的尺寸」与「上一帧已记录的尺寸」是否不同。
        BOOL _sizeChanged = !CGSizeEqualToSize(s->lastSize, newSize);
        s->lastSize = newSize;
        s->repeatCount = 1;
        s->initialized = YES;
        // [v26] 仅新 tick 才清零转发计数; 同 tick 内不同尺寸的放行
        // 调用继续累计 commitCount, 保证 4x 硬上限对交替拉锯 (390<->358) 有效。
        // [V75-PERSISTENT-STORM] stormed 跨 tick 持久 —— 只在不同尺寸到达时解除,
        // 不再随 tick 清零。旧逻辑每 tick 把 stormed 复位 ⇒ 陷入「布局永不合收敛」
        // 的容器每帧重燃: 每帧拿到 kStormForwardLimit*4 (160) 次免费转发额度,
        // 主线程被永久喂满 ⇒ HangDetector 时长跨 tick 单调递增 (2055→4407ms+) ⇒
        // 看门狗 SIGKILL。这正是「选择模型卡死」在 V74 仍未斩净的形态:
        // setSize→runloop 新布局 pass→setSize 的跨调用重入, _gSetSizeForwarding
        // 哨兵(仅拦单次调用栈内的重入)根本抓不到。跨 tick 保留 stormed ⇒ 一旦某
        // tick 内同尺寸重复超 160 次被熔断, 后续所有 tick 的同尺寸调用一律 SKIP,
        // 环被永久斩断; 上游若真收敛到新尺寸(不同尺寸到达)即自动 re-arm, 合法
        // 更新零丢失。单次/少量同尺寸每帧只占 repeatCount=1, 永不到 160 阈值,
        // stormed 不会置位, 合法场景零影响。
        BOOL _newTick = (s->lastTick != gRunloopTick);
        if (_newTick) { s->commitCount = 0; }
        if (_sizeChanged) { s->stormed = NO; s->commitCount = 0; }
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
    // [V65-FIXSIZE-S] **跨 tick 硬闸门**: 非正高度连续命中超限后, 停止转发。
    //
    // 【为什么必须有这一刀, 而不能只靠 per-tick 的 storm-breaker】
    // 装机实测(8.log 17:20:41-55): 单容器 0x2802b8820 在 14 秒内被喂
    // **2644129 次 0x0**。per-tick 熔断每换一次 tick 就清零, 而上游每个
    // tick 都在喂 ⇒ 计数永远到不了 40 ⇒ 永远不熔断 ⇒ 无限转发。
    // 而每一次转发都要: KVC 取 NSValue → CGSizeValue → 装箱 → 修正 → 转发,
    // 14 秒堆出 **+470MB**(151.8→624.2MB) ⇒ SIGKILL; 同期主线程 6281ms 卡顿。
    //
    // 【为什么这里 return 是安全的 —— 不再是"丢弃=卡字"】
    // v65 之前靠"丢弃坏尺寸"来止风暴, 代价是 TextKit 保留过期几何 ⇒ 卡字。
    // 现在非正高度**先被修正成合法尺寸**(高度抬到 1.0), 连续命中到上限后
    // 才停止转发 —— 此时容器已经拿到过一个**合法几何**, 保留它即可,
    // 不是"从未更新过的过期几何"。⇒ 与 v65 的修正转发不冲突。
    if (s->nonPositiveStreak > kNonPositiveHardLimit) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xFF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V65] NONPOSITIVE-HARDSTOP "
                  @"container=%p orig=%.1fx%.1f fixed=%.1fx%.1f streak=%ld "
                  @"— 停止转发(容器已有合法几何)",
                  (__bridge void *)self, newSize.width, newSize.height,
                  newSize.width, newSize.height,
                  (long)s->nonPositiveStreak);
        }
        return;
    }
    _gSetSizeForwarding = YES;
    ((void (*)(id, SEL, CGSize))gOriginalSetSize)(self, _cmd, newSize);
    _gSetSizeForwarding = NO;
}'''
    if OLD6 in t:
        t = t.replace(OLD6, NEW6)
    # ---- ⑦ [V70] dedup 短路改为"先转发收敛再跳过" ----
    # 旧逻辑: same tick 同尺寸第 2 次(kRepeatThreshold=2)就 return 不提交尺寸。
    # 对 re-entrant 风暴(CoreText fillLayoutHole 在递归里反复 setSize)而言,
    # 只第 1 次提交尺寸、其后全 return -> CoreText 永远收敛不了 -> 递归不终止 ->
    # 627k 次/tick -> 主线程打满崩溃(装机 2026-10-06 实测: 选择模型卡死)。
    # 改为: 本 tick 已转发次数(commitCount, 由下方 gOriginalSetSize 累加)未超
    # kStormForwardLimit*4 就放过(落到 gOriginalSetSize 真正提交, 让 CoreText
    # 收敛), 超阈值说明已收敛, 置 stormed 并跳过(安全)。这正是 v4 注释里的
    # 设计意图, 只是被 kRepeatThreshold=2 抢跑了。
    OLD7 = '''            return; // skip forwarding to original setSize:
        }
    } else {'''
    NEW7 = '''            // [V70-DEDUP] 关键修复: 不再第 2 次同尺寸就跳过。
            // 旧 kRepeatThreshold=2 让 re-entrant 风暴里 CoreText fillLayoutHole
            // 只在第 1 次拿到尺寸提交, 其后全部 return -> 永远收敛不了 ->
            // 递归不终止 -> 627k 次/tick -> 主线程打满崩溃(装机 2026-10-06 实测)。
            // 改为: 本 tick 已转发次数(commitCount, 由下方 gOriginalSetSize 累加)
            // 未超 kStormForwardLimit*4 时"放过", 落到 gOriginalSetSize 真正提交
            // 尺寸让 CoreText 收敛; 超阈值说明已收敛, 置 stormed 并跳过(安全)。
            if (s->commitCount > kStormForwardLimit * 4) {
                s->stormed = YES;
                return; // 收敛后跳过
            }
            // 否则 fall-through 到 gOriginalSetSize 转发(让 CoreText 收敛)
        }
    } else {'''
    if OLD7 in t:
        t = t.replace(OLD7, NEW7)
    # ---- ⑧ 横幅: 干净上游走完整注入后, 再统一升到真 V76 ----
    # 半升级 / 旧标记 / 无标记 三种形态都由 _upgrade_guard_banner_v76 处理,
    # 与早退路径共用同一份逻辑(纪律第 8 条: 同一逻辑只能一处实现)。
    return _upgrade_guard_banner_v76(t)


# [V78-NOALLOC] height==0 必须在 objc_getAssociatedObject / GuardState new 之前 return。
# 装机 minis-2026-10-07.log PID 60253: build=V77 在跑, EARLY total 1454081 / 13.5s,
# FIXED 仅 4 条; 内存 36→1958MB; MAIN HANG 105 次 max 13510ms ⇒ PID 60262 重启。
# 根因: V77 的 return 写在 associated 分配之后。容器工厂每次 0x0 仍 new 一个
# GuardState 进 autorelease pool, 同一次 layout 不排空 ⇒ 145 万对象 ⇒ 2GB。
# ★第十五次假绿: 第 ⑪ 层问「在 valueForKey 之前」[在], 没问「在 associated 之前」。
V78_EARLY = """    // [V78-NOALLOC] height==0 在任何堆分配之前 return。
    // 装机 minis-2026-10-07.log PID 60253: build=V77 在跑,
    // EARLY-NONPOSITIVE-RETURN 355 条, total 4097→1454081 / ~13.5s,
    // FIXED 仅 4 条; MemMonitor 36→1958.8MB; MAIN HANG 105 次 max 13510ms;
    // 随后 PID 60262 重启。V77 入口 return 看见了 145 万次, V65 税没再付;
    // 病变成 0x0 仍以 ~10 万次/秒打进 setSize。
    // 根因: V77 的 return 写在 objc_getAssociatedObject /
    // [_NSTextContainerGuardState new] **之后**。容器工厂每次 0x0 仍
    // new 一个 GuardState 进 autorelease pool, 同一次 layout 不排空
    // ⇒ 145 万对象 ⇒ 2GB ⇒ SIGKILL。
    // ★第十五次「验证手段骗了自己」: 第 ⑪ 层问「在 valueForKey 之前」
    // [在], 没问「在 associated 分配之前」。
    // 修法: height==0 在 objc_getAssociatedObject 之前 return, 零堆分配。
    if (newSize.height == 0.0) {
        gShortCircuitCount += 1;
        if ((gShortCircuitCount & 0xFFF) == 1) {
            NSLog(@"[TextContainerGuard] [WARN] [V78] EARLY-NONPOSITIVE-RETURN "
                  @"orig=%.1fx%.1f total=%llu — 入口短路(零分配/不 KVC/不转发)",
                  newSize.width, newSize.height,
                  (unsigned long long)gShortCircuitCount);
        }
        return;
    }

"""

_V78_BANNER = (
    "    // [V78-MARKER] 一次性打印构建版本(装机确认)。V78 = V77 再前移: "
    "**height==0 在 objc_getAssociatedObject / GuardState new 之前 return**"
    "(斩断「容器工厂每次 0x0 仍 new 一个 GuardState 进 autorelease pool」;"
    "装机 PID 60253: EARLY total 1454081 / 13.5s / 36→1958MB / SIGKILL)。\n"
    "    static BOOL _v78GuardLogged = NO;\n"
    "    if (!_v78GuardLogged) {\n"
    "        _v78GuardLogged = YES;\n"
    "        NSLog(@\"[Minis-Guard] build=V78 ios15-pickerCap+inputFlicker+reentrantBreak+persistentStorm+nonPositiveShortCircuit+earlyNonPositiveReturn+zeroAllocEarlyReturn "
    "(cappedEntriesByInstance 非搜索态截断 150; intrinsicContentSize 反馈环路守卫斩输入闪屏; "
    "setSize: 递归哨兵斩断重入环; 同尺寸风暴跨 tick 持久熔断斩断选择模型 measure 死循环; "
    "V76 非正尺寸短路不转发; V77 入口短路在 valueForKey 之前; "
    "**V78 入口短路在 associated 分配之前, 零堆分配**)\");\n"
    "    }\n\n"
)

_V78_NSLOG = (
    'NSLog(@"[Minis-Guard] build=V78 ios15-pickerCap+inputFlicker+reentrantBreak+persistentStorm+nonPositiveShortCircuit+earlyNonPositiveReturn+zeroAllocEarlyReturn '
    '(cappedEntriesByInstance 非搜索态截断 150; intrinsicContentSize 反馈环路守卫斩输入闪屏; '
    'setSize: 递归哨兵斩断重入环; 同尺寸风暴跨 tick 持久熔断斩断选择模型 measure 死循环; '
    'V76 非正尺寸短路不转发; V77 入口短路在 valueForKey 之前; '
    '**V78 入口短路在 associated 分配之前, 零堆分配**)");'
)


def _is_true_v78_banner(t):
    return ("[V78-MARKER]" in t
            and "_v78GuardLogged" in t
            and 'NSLog(@"[Minis-Guard] build=V78 ' in t
            and "zeroAllocEarlyReturn" in t
            and "_v77GuardLogged" not in t
            and "_v76GuardLogged" not in t
            and "_v75GuardLogged" not in t
            and "_v74GuardLogged" not in t)


def _is_true_v78_early(t):
    i = t.find("[V78-NOALLOC]")
    assoc = t.find("objc_getAssociatedObject")
    k = t.find('valueForKey:@"size"')
    r = t.find("_gSetSizeForwarding")
    return (i >= 0
            and "[V78] EARLY-NONPOSITIVE-RETURN" in t
            and "newSize.height == 0.0" in t[i:i + 1200]
            and (assoc < 0 or i < assoc)
            and (k < 0 or i < k)
            and (r < 0 or i < r))


def _upgrade_guard_banner_v78(t):
    if _is_true_v78_banner(t):
        return t
    t = re.sub(r"_v7[0-7]GuardLogged", "_v78GuardLogged", t)
    t = re.sub(
        r'NSLog\(@"\[Minis-Guard\] build=V7[0-9][^"]*"\);',
        _V78_NSLOG,
        t,
        count=1,
    )
    for oldk in ("[V77-MARKER]", "[V76-MARKER]", "[V75-MARKER]",
                 "[V74-MARKER]", "[V72-MARKER]"):
        if oldk in t:
            t = t.replace(oldk, "[V78-MARKER]", 1)
            break
    if _is_true_v78_banner(t):
        return t
    needle = "    // [V74-REENT] 递归哨兵:"
    if needle in t and "_v78GuardLogged" not in t:
        t = t.replace(needle, _V78_BANNER + needle, 1)
    return t


def _strip_early_block(t, marker):
    """摘掉任何位置的入口短路块(含错位到 associated / KVC 之后的形态)。"""
    i = t.find(marker)
    if i < 0:
        return t
    line_start = t.rfind("\n", 0, i) + 1
    j = t.find("if (newSize.height == 0.0)", i)
    if j < 0:
        j = t.find("if (newSize.width <= 0.0 || newSize.height <= 0.0)", i)
    if j < 0:
        return t
    brace = t.find("{", j)
    if brace < 0:
        return t
    depth = 0
    k = brace
    while k < len(t):
        if t[k] == "{":
            depth += 1
        elif t[k] == "}":
            depth -= 1
            if depth == 0:
                k += 1
                break
        k += 1
    if k < len(t) and t[k] == "\n":
        k += 1
    return t[:line_start] + t[k:]


def fix_early_nonpos_v78(t):
    """v78: height==0 在 objc_getAssociatedObject / GuardState new 之前 return。

    幂等: 入口短路已在 associated 之前且横幅三位一体 ⇒ 原样返回。
    已注入树也必须能从 V77 错位(return 在 associated 之后)走到真 V78。
    """
    if not _is_true_v78_early(t):
        t = _strip_early_block(t, "[V78-NOALLOC]")
        t = _strip_early_block(t, "[V77-EARLY-NONPOS]")
        needle = "    // Sanitise obviously poisoned sizes that SwiftUI's measure path"
        if "[V78-NOALLOC]" not in t and needle in t:
            t = t.replace(needle, V78_EARLY + needle, 1)
        if "[V78-NOALLOC]" not in t:
            needle2 = "    _NSTextContainerGuardState *holder = objc_getAssociatedObject"
            if needle2 in t:
                t = t.replace(needle2, V78_EARLY + needle2, 1)
    return _upgrade_guard_banner_v78(t)


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
    # [幂等纪律 51] 判据必须在**任何锚点检查与替换之前**。
    # 原先它排在 RENDER_OLD 检查之后, 第一次运行时 RENDER_OLD 已不在
    # (已被替换掉), 幂等判据永远轮不到执行 ⇒ 第二次运行直接抛
    # "渲染宽锚点未命中 —— 上游结构变了?" —— 报错文案指向错误方向。
    #
    # ★判据不能用 `// [V32-WIDTH]`: v33 紧接着把 v32 的两段整体改写
    #   (v32 写的是 `let measureWidth: CGFloat = max(200.0, ...)`,
    #   v33 换成 `let measureWidth: CGFloat = { ... }` 多行闭包),
    #   **v32 的标记在最终产物里根本不出现** ⇒ 用它判幂等会永远
    #   判成"未注入", 第二次运行照样炸锚点缺失。
    # ⇒ 纪律 52: **幂等标记必须取该补丁在最终产物里的存活形态**;
    #   被后续补丁改写掉的标记不能用来判幂等, 要么改用后续补丁的标记,
    #   要么用"锚点已消失"作辅助判据。
    if "// [V32-WIDTH]" in t or "let measureWidth: CGFloat = {" in t:
        return t

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

    ★幂等判据必须认**本补丁在最终产物里的存活形态**, 不能只认自己的标记 ——
    v34 会把 `[V33-WIDTH2]` 整段(含标记)换成 `[V34-WIDTH2]`, 于是第二次运行时
    `V33-WIDTH2` 已不在产物里, 本补丁会**重新注入并把 v34 的成果改回 contentW**,
    连带把 v47/v48/v51 的 `_realW2 = _realW` 锚点一起推翻(表现为 v47/v51 判据
    突然报"找不到声明")。这是 v32 标记被 v33 改写那一类问题的翻版, 纪律同源:
    后版扩展/替换了同一段代码时, 前版的幂等判据要跟着更新。
    """
    OLD = """            let _realW2 = _realW"""
    NEW = """            // [V33-WIDTH2] 与 _realW/测高宽 同一式子(视图宽 - 内边距): 气泡型 326、贴边型 358
            // 各取真实宽, 绝不把 326 的框撑到 358 (那会右侧溢出裁字)。不再硬编码 cvW-32。
            let _realW2 = max(200.0, min(bounds.width, _cvW) - textContainerInset.left - textContainerInset.right)"""
    # v33-WIDTH2 = 本补丁自己的标记; V34-WIDTH2 = v34 改写后的存活形态。
    # 两者任一在位即视为已注入。
    if "V33-WIDTH2" in t or "V34-WIDTH2" in t:
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
    # [幂等] v43-B 的产物标记: 注入过的段里必然含 V43-BURST。
    # 缺这一段时第二次运行会去找 OLD 锚点 —— 锚点在注入后已消失, 于是抛
    # "未找到 reflow 锚点(上游结构变了?)", 报错文案还指向错误的方向。
    # ⇒ 纪律 51: **每个补丁都必须能用产物标记自证已注入**; 报错文案不得
    #   把"幂等缺失"说成"上游结构变了"(run#133 那次就被这句话误导过)。
    if t.count("V43-BURST") >= 3:
        return t
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
    # [幂等] v44 段以 `NSLog("[V44-TEXTFRAME]` 为产物标记。ANCHOR 在注入后
    # **依然存在**(它位于 v44 段之前), 所以缺这一段时第二次运行会再插一份
    # ⇒ verify 的"标记数必须为 1"断言反而报成 `NSLog 标记数不符(实际 2)`,
    # 报错文案完全指错方向(看起来像 v44 写坏了, 实际是幂等缺失)。
    # ⇒ 纪律 51: 每个补丁都要能用**产物标记**自证已注入, 不能只靠锚点消失。
    if t.count('NSLog("[V44-TEXTFRAME]') >= 1:
        return t
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
    # [幂等·纪律 51/52] 必须在**任何注入动作之前**检查, 且用**产物标记**。
    # 本函数原先把判据放在注入点之后 ⇒ 第二次运行时第一处已又插了一份,
    # verify 的「标记数==1」断言报成「实际 2」—— 报错文案指向错误方向。
    if 'NSLog("[V45-TVHFIX]' in t:
        return t

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
    # [幂等·纪律 51/52] 必须在**任何注入动作之前**检查, 且用**产物标记**。
    # 本函数原先把判据放在注入点之后 ⇒ 第二次运行时第一处已又插了一份,
    # verify 的「标记数==1」断言报成「实际 2」—— 报错文案指向错误方向。
    if 'NSLog("[V46-ATTACH]' in t:
        return t

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


def fix_diag_codeblock_v565(t):
    # ================================================================
    # v56.5: CodeBlockAttachment 高度诊断 (纯只读, 一行几何都不碰)
    # ================================================================
    # 【为什么 v46 探针查不到终端框】
    #   v46 的 [V46-ATTACH] 只对 `TableAttachment` 取值:
    #       if let _t = _a as? TableAttachment { ... }
    #   而终端框是 **CodeBlockAttachment**, 两者是**平级的兄弟类**
    #   (都直接继承 NSTextAttachment, 行 1405 / 1776)。
    #   ⇒ 探针的 `attWant/attCached` 从来不含代码块。
    #   装机日志证据(v56.2, PID 43107): 72 条 V46-ATTACH 里,
    #   **31 条是 attWant=0.0 attCached=-1.0** —— 累计高 0、缓存 -1,
    #   说明那一帧的附件**全是 CodeBlockAttachment**, 一个 TableAttachment
    #   都没有, 于是两个计数器恒为初值。那 31 条的 nGlyph 恒 228、
    #   usedH 恒 477.6、tcW 恒 390.0 ⇒ 是**另一个独立的视图**。
    #   结论: 「终端框卡显示 + 终端输出与终端之间空白过大」这条线,
    #   v46 探针**结构上就看不见**, 不是数据不够, 是压根没测。
    #
    # 【v56.2 日志里已能确定的边界条件(不需要猜的部分)】
    #   · attachmentBounds 与 makeView 两条路径都用
    #       sizeThatFits(CGSize(width: .greatestFiniteMagnitude, ...))
    #     即**不限宽测量** ⇒ 终端输出永不折行, contentHeight 是"一行/多行"的
    #     自然高度。两条路径同源, 所以 attWant==attCached 本该成立 ——
    #     V46 里 attWant!=attCached 的那 17 条是 Table 的问题, 与终端框无关。
    #   · maxCodeHeight = 400 - topOffset - bottomPadding 是**硬上限**,
    #     contentHeight 超过就被截断进内部滚动区。此时 attachmentBounds
    #     返回的高度 **小于**真实内容高度, 而 makeView 里
    #     `scrollView.frame.height = scrollHeight + bottomPadding` 用的是
    #     同一个 scrollHeight —— 两边一致, 但**外部排版给它的位置只按
    #     截断后的高度**, 于是"终端框画出来了、框内的输出被滚动区吃掉"。
    #     这与用户看到的「终端框卡显示」方向一致, 但**是同一现象还是两回事
    #     必须由日志回答**, 不能靠推断。
    #
    # 【所以这一版只加探针, 不改行为】
    #   要测的四个量, 每一个都对应一个可证伪的修法分支:
    #     cH  = attachmentBounds 返回的总高(排版给它留的位置)
    #     raw = measureCodeHeight() 的原始自然高
    #     cap = maxCodeHeight 的硬上限
    #     vcH = 已 makeView 出来的真实视图高度(框架/容器)
    #   判读:
    #     · raw > cap  ⇒ 内容超上限被截 ⇒ 修法在"截断策略"(上限或改折叠)
    #     · raw <= cap 但 vcH != cH ⇒ 视图与排版给的位置不一致
    #       ⇒ 空白来自**框架高度与排版高度两个来源打架**
    #     · cH 远小于 usedH 的可用量 ⇒ 排版没给它留够位置 ⇒ 下游消费问题
    #   ★不测「帧有没有被复用」—— 那要看 v56 的 [V56-*] 与 view cache,
    #     混进本探针会让 4 个量变成 8 个量, 判读时反而看不出因果。
    V565_OLD = """    override func attachmentBounds(for textContainer: NSTextContainer?, proposedLineFragment lineFrag: CGRect, glyphPosition position: CGPoint, characterIndex charIndex: Int) -> CGRect {
        let width = lineFrag.width
        let topOffset: CGFloat = (language != nil && !language!.isEmpty) ? 28 : 12
        let contentHeight = measureCodeHeight()
        let bottomPadding: CGFloat = 12
        let maxCodeHeight: CGFloat = 400 - topOffset - bottomPadding
        let scrollHeight = min(contentHeight, maxCodeHeight)
        let totalHeight = topOffset + scrollHeight + bottomPadding
        let height = totalHeight + Self.topMargin + Self.bottomMargin
        return CGRect(x: 0, y: 0, width: width, height: height)
    }"""

    V565_NEW = """    // [V565-CODEBLOCK] 终端框高度账 —— 纯诊断, 一行几何都不碰。
    //
    // 【v46 探针为什么测不到这里】v46 只 as? TableAttachment, 而本类是
    // CodeBlockAttachment, 二者是平级兄弟(都直接继承 NSTextAttachment)。
    // v56.2 装机日志里那 31 条 `attWant=0.0 attCached=-1.0` 就是证据:
    // 累计高 0、缓存 -1 ⇒ 该帧附件全是代码块, v46 计数器恒为初值。
    // ⇒ 之前说"终端框问题数据不够"是错的, 准确说法是**根本没测**。
    //
    // 【四个量各自能证伪一个修法】
    //   cH  = 本方法返回的总高 —— 排版在文本流里给它留的位置
    //   raw = measureCodeHeight() 自然高(不限宽测量, 故永不折行)
    //   cap = 400 - topOffset - 12 的硬上限
    //   vcH = makeView 出来的容器真实高(框架层), -1 = 还没 makeView
    //   判读:
    //     raw > cap          ⇒ 内容超上限被截进内部滚动区(终端框"卡显示")
    //     vcH >= 0 且 vcH != cH ⇒ 框架高度与排版高度两个来源打架(空白过大)
    //     vcH < 0            ⇒ 排版问过高度但从未建视图 ⇒ 建视图路径没跑到
    //   0.5s 节流, 与 V41/V44/V45/V46 同周期。
    var attV565ViewH: CGFloat = -1
    var attV565ViewW: CGFloat = -1

    override func attachmentBounds(for textContainer: NSTextContainer?, proposedLineFragment lineFrag: CGRect, glyphPosition position: CGPoint, characterIndex charIndex: Int) -> CGRect {
        let width = lineFrag.width
        let topOffset: CGFloat = (language != nil && !language!.isEmpty) ? 28 : 12
        let contentHeight = measureCodeHeight()
        let bottomPadding: CGFloat = 12
        let maxCodeHeight: CGFloat = 400 - topOffset - bottomPadding
        let scrollHeight = min(contentHeight, maxCodeHeight)
        let totalHeight = topOffset + scrollHeight + bottomPadding
        let height = totalHeight + Self.topMargin + Self.bottomMargin

        // ---- [V565-CODEBLOCK] 诊断段: 纯读 + 打日志, 零赋值影响 ----
        // ★不得改 height/width —— 判据会校验本段零赋值, 改了就失去意义。
        do {
            struct _V565Log { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
            let _v565now = CACurrentMediaTime()
            if _v565now - _V565Log.last > 0.5 {
                _V565Log.last = _v565now
                _V565Log.n &+= 1
                // 真实视图高度: 从 keyWindow 沿子树上溯找本 attachment 建的
                // wrapper 代价太高且会强引用视图, 改为由 makeView 侧写入
                // attV565ViewH(见下), 这里只读。
                NSLog("[V565-CODEBLOCK] cH=%.1f raw=%.1f cap=%.1f clip=%d lines=%d "
                      + "chars=%d fragW=%.1f viewH=%.1f viewW=%.1f cachedRaw=%.1f n=%u",
                      Double(height), Double(contentHeight), Double(maxCodeHeight),
                      contentHeight > maxCodeHeight ? 1 : 0,
                      self.attV565LineCount, code.count,
                      Double(width), Double(attV565ViewH), Double(attV565ViewW),
                      Double(self.attV565CachedRaw), _V565Log.n)
            }
        }

        return CGRect(x: 0, y: 0, width: width, height: height)
    }

    // [V565-CODEBLOCK] 只读诊断量: 缓存里的自然高(判断缓存是否过期)
    // 与行数(把 raw 换算成"几行"才能和 cap 比)。
    var attV565CachedRaw: CGFloat { cachedContentHeight?.height ?? -1 }
    /// 终端输出的行数 = 自然高 / 单行行高, 由 topOffset 的 28/12 反推不稳,
    /// 这里直接数换行符 + 1, 语义明确且不依赖字体度量。
    var attV565LineCount: Int {
        var n = 1
        for ch in code.unicodeScalars where ch == "\\n" { n += 1 }
        return n
    }"""

    # [幂等·纪律 51/52] 判据必须在**任何注入动作之前**, 且认**产物标记**。
    # 锚点 V565_OLD 在注入后消失, 但仍按「插入物自身」判定, 与 v56.4
    # 修 fix_markdown_layout_reconcile 时立的纪律一致。
    if "V565-CODEBLOCK" in t:
        return t

    if V565_OLD not in t:
        raise RuntimeError(
            "fix_diag_codeblock_v565: CodeBlockAttachment.attachmentBounds "
            "锚点不唯一或已变(命中 %d 处)。上游结构变了, 先重新核对再注入 —— "
            "★绝不能靠改 needle 硬凑, 那会让探针插到错误的类上, 测出来的数"
            "全无意义(这是 v46 探针结构上看不到代码块的根本教训)。"
            % t.count(V565_OLD))

    t = t.replace(V565_OLD, V565_NEW, 1)

    # ---- 由 makeView 侧写入真实视图高度(唯一一处必要的赋值) ----
    # 放在 container.frame 赋值之后: 那是「框架层最终高度」的唯一来源。
    MV_OLD = """        let totalHeight = topOffset + scrollHeight + bottomPadding
        container.frame = CGRect(x: inset, y: 0, width: contentWidth, height: totalHeight)"""
    MV_NEW = """        let totalHeight = topOffset + scrollHeight + bottomPadding
        container.frame = CGRect(x: inset, y: 0, width: contentWidth, height: totalHeight)
        // [V565-CODEBLOCK] 把框架层真实高度回报给 attachmentBounds 的诊断段,
        // 好让日志并排打出「排版给的位置 cH」与「实际画的框 viewH」。
        // ★这是本探针**唯一**的写入点, 且写的是本对象自己的字段 ——
        //   不改任何几何、不触发任何 invalidate。
        attV565ViewH = wrapper.frame.height
        attV565ViewW = container.frame.width"""
    if MV_OLD not in t:
        raise RuntimeError(
            "fix_diag_codeblock_v565: makeView 的 container.frame 锚点缺失 —— "
            "探针的 viewH 会永远是 -1, 白测。命中 %d 处。" % t.count(MV_OLD))
    t = t.replace(MV_OLD, MV_NEW, 1)

    verify_diag_codeblock_v565(t)
    return t


def verify_diag_codeblock_v565(t):
    """V565 探针的结构校验。判据顺序: 先语义后计数, 计数放最后当总兜底。

    判据设计的核心教训(v46 探针): **判据必须盯住"它测的是不是我要测的东西"**。
    v46 只 as? TableAttachment, 于是对同为 NSTextAttachment 子类的
    CodeBlockAttachment 完全失明 —— 探针存在、一直绿、却测不到终端框。
    纯检查「标记在不在、括号平不平」永远发现不了这件事, 那是**覆盖范围**
    判据, 只能靠人写下来。所以本函数的第 2 条显式钉死类名。
    """
    import re as _re

    # ---- 1. 日志点唯一 ----
    _i0 = t.find('NSLog("[V565-CODEBLOCK]')
    if _i0 < 0:
        raise RuntimeError("verify_diag_codeblock_v565: 未找到 V565 日志点")
    if t.count('NSLog("[V565-CODEBLOCK]') != 1:
        raise RuntimeError("verify_diag_codeblock_v565: V565 日志点必须唯一")

    # ---- 2. ★覆盖范围: 必须挂在 CodeBlockAttachment 里, 不是 TableAttachment ----
    # 【v46 的教训】探针装在错误的类里, 全部判据照样全绿, 而测的是别的东西。
    # 只查「标记唯一」发现不了这件事 —— 必须正向钉死宿主类名。
    _icb = t.find("final class CodeBlockAttachment")
    if _icb < 0:
        raise RuntimeError(
            "verify_diag_codeblock_v565: 未找到 CodeBlockAttachment 类 —— "
            "上游结构变了, 重新核对宿主类再注入(绝不能改 needle 硬凑)")
    _iend_cb = t.find("\nfinal class ", _icb + 10)
    if _iend_cb < 0:
        _iend_cb = len(t)
    if not (_icb < _i0 < _iend_cb):
        raise RuntimeError(
            "verify_diag_codeblock_v565: V565 日志点不在 CodeBlockAttachment 内 "
            "(类区间 %d..%d, 日志点 %d) —— ★这正是 v46 探针的失败形态: "
            "装在 TableAttachment 里, 对代码块完全失明。"
            % (_icb, _iend_cb, _i0))

    # ---- 3. 四个诊断量齐全(少一个就少一条可证伪分支) ----
    for _need, _why in (
        ("attV565ViewH", "makeView 侧必须写入真实框高, 否则 viewH 恒 -1"),
        ("attV565ViewW", "必须写入真实框宽, 否则无法判左右被裁"),
        ("attV565CachedRaw", "必须读缓存自然高, 否则判不出缓存是否过期"),
        ("attV565LineCount", "必须有行数, raw/cap 的比值才有物理意义"),
        ("contentHeight > maxCodeHeight", "必须打 clip 标志 —— "
         "「内容超上限被截」是终端框卡显示的头号候选"),
    ):
        if _need not in t:
            raise RuntimeError(
                "verify_diag_codeblock_v565: 缺少 %s —— %s" % (_need, _why))

    # ---- 3b. ★makeView 侧的回写必须**真的存在**(不是只有字段声明) ----
    # 【反向测试 S2 实跑发现的洞】只查 "attV565ViewH" 在文件里出现过,
    #   删掉 makeView 里那两行**赋值**后, 字段声明(var attV565ViewH: CGFloat = -1)
    #   与诊断段里的**读**都还在, 判据照样全绿 —— 而 viewH 会恒为 -1,
    #   探针测不出任何东西。**声明 ≠ 写入。**
    #   ⇒ 判据必须查**赋值语句**, 且必须落在 makeView 方法体里。
    _mv_anchor = "container.frame = CGRect(x: inset, y: 0, width: contentWidth, height: totalHeight)"
    _imv = t.find(_mv_anchor)
    if _imv < 0:
        raise RuntimeError(
            "verify_diag_codeblock_v565: 未找到 makeView 的 container.frame 锚点 —— "
            "探针的 viewH 回报点没了")
    _tail = t[_imv:_imv + 400]
    for _wr in ("attV565ViewH =", "attV565ViewW ="):
        if _wr not in _tail:
            raise RuntimeError(
                "verify_diag_codeblock_v565: makeView 的 container.frame 之后必须回写 %s "
                "—— 反向测试 S2 实测: 只留字段声明而删掉赋值, 判据会全绿放行, "
                "而 viewH 恒 -1 等于探针没测(声明 ≠ 写入)" % _wr)

    # ---- 4. 访问器必须是无 setter 的只读 getter ----
    # ★必须扫**整段**而不是第一行: 只读 getter 常写成多行
    #   (var x: Int {\n    ...\n  }), 只看首行会误判"没有 {" 而报死。
    #   这是本函数第一次跑就踩到的错 —— 判据自己写错, 报出的却是
    #   "产物有问题", 方向完全相反。判据的假红比假绿更费时间。
    for _acc in ("var attV565CachedRaw", "var attV565LineCount"):
        _i = t.find(_acc)
        if _i < 0:
            raise RuntimeError("verify_diag_codeblock_v565: 只读访问器缺失: %s" % _acc)
        # 从声明行起到第一个只含 "}" 的行为止
        _e = t.find("\n", _i)
        _j = _e
        while _j < len(t):
            _nxt_eol = t.find("\n", _j + 1)
            if _nxt_eol < 0:
                break
            _seg_line = t[_j + 1:_nxt_eol].strip()
            if _seg_line == "}":          # 单行 getter: "var x: T { expr }"
                _j = _nxt_eol
                break
            _j = _nxt_eol
        _blk = t[_i:_j + 1]
        if "{" not in _blk or "}" not in _blk:
            raise RuntimeError(
                "verify_diag_codeblock_v565: %s 必须是只读 getter(结构上不可写): %r"
                % (_acc, _blk.strip()[:120]))
        _no_set = _re.sub(r"//[^\n]*", "", _blk)
        if _re.search(r"\bset\b\s*\{", _no_set) or _re.search(r"\bset\s*\{", _no_set):
            raise RuntimeError(
                "verify_diag_codeblock_v565: %s 不得带 setter" % _acc)

    # ---- 5. ★诊断段零赋值(纯诊断的生命线) ----
    # 段内除节流计数器(_V565Log)外不得对任何已有状态赋值; 一旦改了高度,
    # 装机日志的四个量就全部不可信, 归因链断掉。
    # ★日志点**在** do 块内部, 所以 do 必须**向前**找; 向前找会命中
    #   attachmentBounds 方法体里更早的 do(如 for-in 之外的), 因此取
    #   "最后一个出现在 _i0 之前、且其后到 _i0 之间没有别的 do {" 的那个。
    #   最稳的定位: 从 _i0 往前找最近的 "do {"。
    _i_do = t.rfind("do {", 0, _i0)
    if _i_do < 0:
        raise RuntimeError("verify_diag_codeblock_v565: 诊断段没有 do { 块")
    # ★必须用**花括号配平**切到 do 块的闭合, 不能用固定缩进找 "\n            }" ——
    #   固定缩进的写法在别的缩进层上会切飞, 把 do 块**后面**的 makeView 代码
    #   一并切进来, 于是 syncScrollability 里的
    #   `scrollView.showsVerticalScrollIndicator = canScrollV`
    #   被当成"探针改了状态"而报死。
    #   ⇒ 判据自己的切片错, 报出的却是"产物违规", 方向完全相反。
    #   ⇒ 这是本轮第二次被自己的判据骗到(第一次是多行 getter 只看首行)。
    #   **纪律: 判据的切片必须按结构配平, 不能按缩进猜。**
    _depth2 = 0
    _k = _i_do + len("do {") - 1
    _end = -1
    while _k < len(t):
        if t[_k] == "{":
            _depth2 += 1
        elif t[_k] == "}":
            _depth2 -= 1
            if _depth2 == 0:
                _end = _k + 1
                break
        _k += 1
    if _end < 0:
        raise RuntimeError("verify_diag_codeblock_v565: do 块未闭合")
    # ★切片必须从 **do 块**起, 不能从日志点起 ——
    #   反向测试 S4/S5 实跑发现: 从日志点切的话, 「写在 do 开头、日志点之前」
    #   的违规代码落在切片之外, 判据全绿放行。所以切片起点是 _i_do。
    #   日志点在块内, 故下界用 do、上界用 do 的闭合 —— 正好是整个诊断块。
    _seg = t[_i_do:_end]
    _code = _strip_swift_noise(_seg)
    for _ln in _code.splitlines():
        _s = _ln.strip()
        if not _s:
            continue
        if _s.startswith("let ") or _s.startswith("var ") or _s.startswith("struct "):
            continue
        if "&+=" in _s or "struct _V565Log" in _s:
            continue
        if _s.startswith("return "):
            continue
        _m = _re.search(
            r"(?<![\w.\]\)])\b([A-Za-z_][\w]*(?:\.[A-Za-z_][\w]*)*"
            r"(?:\[[^\]]*\])?)\s*=(?!=)", _s)
        if _m:
            _lhs = _m.group(1)
            if not _lhs.startswith("_V565Log"):
                raise RuntimeError(
                    "verify_diag_codeblock_v565: ★纯诊断违规 —— 段内出现赋值 %r: %r "
                    "(探针必须只读; 改几何会让四个量的归因全部失效)"
                    % (_lhs, _s[:70]))

    # ---- 6. 硬禁危险调用: 段内不得触发任何重排/失效 ----
    for _bad in ("invalidateLayout", "invalidateDisplay", "invalidateIntrinsic",
                 "invalidateSize", "ensureLayout", "setNeedsDisplay",
                 "computeLayout(", "textContainer.size =", ".frame =",
                 "contentGeneration", "needsLayoutInvalidation",
                 "measureCodeHeight() ="):
        if _bad in _code:
            raise RuntimeError(
                "verify_diag_codeblock_v565: 段内出现禁用项 %r —— "
                "★纯诊断违规: 探针里偷偷做修法, 装机数据失去归因价值" % _bad)

    # ---- 7. 诊断块必须紧贴在 return CGRect 之前 ----
    # 裸块会被吸成 trailing closure(v42 首次推送就栽在这), 所以必须 do { }。
    # 「紧贴」的判据: do 块闭合到 return CGRect 之间只允许空白 ——
    # 中间插任何逻辑都意味着 cH 的计算可能已经变了, 探针测的不是同一个值。
    _after = t[_end:_end + 200]
    _gap = _after.lstrip()
    if not _gap.startswith("return CGRect"):
        raise RuntimeError(
            "verify_diag_codeblock_v565: do 块必须紧贴 return CGRect 之前 "
            "(实际其后是 %r) —— 中间夹逻辑会让 cH 与被测表达式脱钩"
            % _gap[:60])

    # ---- 8. 节流必须 0.5s, 与其余诊断同周期 ----
    if "_v565now - _V565Log.last > 0.5" not in t:
        raise RuntimeError(
            "verify_diag_codeblock_v565: 必须 0.5s 节流"
            "(与 V41-KVOPRE/V44/V45/V46 同周期)")

    # ---- 9. 花括号平衡(总兜底, 放最后) ----
    _depth, _low = _brace_balance(t)
    if _depth != 0:
        raise RuntimeError(
            "verify_diag_codeblock_v565: 花括号不平衡(净 %+d 处)" % _depth)
    if _low < 0:
        raise RuntimeError(
            "verify_diag_codeblock_v565: 花括号中途变负(最深 %d) —— 有未闭合结构" % _low)



def _v566_strip_comments_only(text):
    """只剥 Swift 注释, **保留字符串字面量**, 行数不变。

    ★为什么要专门写这个而不是用 `_strip_swift_noise`:
      v56.4 的教训 —— `_strip_swift_noise` 连字符串一起剥, 而 v566 的判据
      要查的 `cardWidth * 3.0 / 4.0` 恰好**出现在我新写的注释里**
      (「旧式 cardWidth * 3.0 / 4.0 在 375 屏上是 263pt」)。
      裸字符串搜索会把注释当代码 ⇒ 自己写的说明文字把自己判红了。
      ⇒ 判据查「代码」时就必须只看代码。

    用 in_string 状态位让 `//` 与 `/*` 只在代码区生效(否则 `https://` 误判),
    注释一律替换成等量换行以保持行号不变。
    """
    out = []
    i = 0
    n = len(text)
    in_str = False
    in_line = False
    in_block = False
    while i < n:
        c = text[i]
        nxt = text[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
                out.append(c)
            i += 1
            continue
        if in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 2
                continue
            out.append(c if c == "\n" else " ")
            i += 1
            continue
        if in_str:
            if c == "\\":
                out.append(c)
                if nxt:
                    out.append(nxt)
                i += 2
                continue
            if c == '"':
                in_str = False
            out.append(c)
            i += 1
            continue
        # 代码区
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == "/" and nxt == "/":
            in_line = True
            i += 2
            out.append("  ")
            continue
        if c == "/" and nxt == "*":
            in_block = True
            i += 2
            out.append("  ")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def fix_toolbar_minheight_v566(t):
    # ================================================================
    # v56.6: 终端框高度下限改成「按内容」而不是「按宽度乘 3/4」
    # ================================================================
    # ★v56.5 装机日志(1791122354995860829, PID 1441)把整条归因链推翻了:
    #
    #   1) 全部 75 条渲染日志都是 `codeBlocks=0` —— **一个 Markdown 代码块都没有**;
    #      而录屏第5 帧终端框明明在画面上。
    #   2) [V565-CODEBLOCK] 0 条 —— 探针没坏, 是 CodeBlockAttachment
    #      在这条路径上**从来没被创建过**。
    #   ⇒ 「终端框」根本不是 Markdown 代码块, 是 FloatingToolBar 的
    #     ToolPreviewThumbnail(工具输出卡片, tool=shell_execute)。
    #     v56.5 之前的全部归因(含 v46/v47/v48/v50 一系列)都建立在
    #     「终端框 = 代码块」这个**从未被验证过**的前提上。
    #
    # 【本版修的东西 —— 不依赖任何探针, 代码本身就是证据】
    #   ToolLiveSheet.swift:2335 与 :1654(两条重复路径)都有:
    #       let cardMinHeight = cardWidth * 3.0 / 4.0
    #   375 屏上 cardWidth≈351 ⇒ cardMinHeight≈263pt。
    #   **只有一行输出的终端也被强撑到 263pt**, 而
    #   `.frame(..., minHeight: cardMinHeight, alignment: .topLeading)`
    #   把多余空间全堆在内容下方 ⇒ 这就是「终端输出与终端之间空白过大」。
    #
    #   为什么上游敢这么写: 它假定卡片里总有几百行输出, 4:3 只是个兜底。
    #   但折叠态预览 / 短输出场景下, 兜底就变成了正文里最大的视觉 bug。
    #
    # 【修法: 下限按内容行数给, 不再按宽度乘常数】
    #   minHeight = 标题行 + 可见输出行 * 行高 + 上下padding, 再夹到
    #   [最小 88pt, 最大 400pt]。88pt 是一行标题 + 两行输出的合理下限;
    #   400pt 是 v46 时代就存在的上限口径, 不放宽以免一口气撑满整屏。
    #   ★不设「无输出时的 263pt 兜底」—— 空卡片就该是空的,
    #     空白过大的根源正是那个兜底。
    #
    # 【为什么两条路径都要改】
    #   textContent(:2333) 与 snapshotTextContent(:1653) 是**逐字重复**的
    #   两份布局代码(有持久化 snapshot 时走后者)。只改一处会让两个入口
    #   行为分叉 —— 这是本项目吃过教训的形态(v13/v34 抢宽分叉)。
    #   ⇒ 判据硬性要求两条都改, 且都带 [V566-MINH] 标记。

    if "[V566-MINH]" in t:
        return t

    # ---- 锚点 1: 两处 cardMinHeight 的声明 ----
    OLD_DECL = """    private var textContent: some View {
        GeometryReader { geo in
            let cardWidth = geo.size.width - 24 // 12pt horizontal padding each side
            let cardMinHeight = cardWidth * 3.0 / 4.0
"""
    NEW_DECL = """    private var textContent: some View {
        GeometryReader { geo in
            let cardWidth = geo.size.width - 24 // 12pt horizontal padding each side
            // [V566-MINH] 下限按**内容行数**给, 不再按宽度乘 3/4。
            // 旧式 `cardWidth * 3.0 / 4.0` 在 375 屏上是 263pt:
            // 一行输出也被撑到 263pt, alignment:.topLeading 把余量全堆在下方
            // ⇒ 用户看到的「终端输出与终端之间空白过大」。
            let v566RowH: CGFloat = 16
            let v566Pad: CGFloat = 28          // .padding(.top,14) + .padding(.bottom,14)
            let v566HeadH: CGFloat = 32        // 标题行 + .padding(.top,14)
            let v566BodyLines = CGFloat(min(max(linesShownInPreview(self.previewLinesCount), 0), 18))
            let cardMinHeight = min(max(
                v566HeadH + v566BodyLines * v566RowH + v566Pad,
                Self.v566FloorHeight), Self.v566CeilHeight)
"""
    if OLD_DECL not in t:
        raise RuntimeError(
            "fix_toolbar_minheight_v566: textContent 锚点不在 —— "
            "上游 ToolLiveSheet.swift 的 textContent 结构变了")
    t = t.replace(OLD_DECL, NEW_DECL, 1)

    OLD_DECL2 = """    private func snapshotTextContent(_ text: String) -> some View {
        GeometryReader { geo in
            let cardWidth = geo.size.width - 24 // 12pt horizontal padding each side
            let cardMinHeight = cardWidth * 3.0 / 4.0
"""
    NEW_DECL2 = """    private func snapshotTextContent(_ text: String) -> some View {
        GeometryReader { geo in
            let cardWidth = geo.size.width - 24 // 12pt horizontal padding each side
            // [V566-MINH] 与 textContent 逐字同款 —— 见那里的说明。
            // ★必须同步: 两条是重复代码, 只改一处会让两个入口行为分叉。
            let v566RowH: CGFloat = 16
            let v566Pad: CGFloat = 28          // .padding(.top,14) + .padding(.bottom,14)
            let v566HeadH: CGFloat = 32        // 标题行 + .padding(.top,14)
            let v566BodyLines = CGFloat(min(max(LazyRenderTuning.linesShownInPreview(text.count), 0), 18))
            let cardMinHeight = min(max(
                v566HeadH + v566BodyLines * v566RowH + v566Pad,
                Self.v566FloorHeight), Self.v566CeilHeight)
"""
    if OLD_DECL2 not in t:
        raise RuntimeError(
            "fix_toolbar_minheight_v566: snapshotTextContent 锚点不在 —— "
            "两条重复路径必须同步修改, 只改一处就是分叉")
    t = t.replace(OLD_DECL2, NEW_DECL2, 1)

    # ---- 锚点 2: 加常量与行数换算 ----
    OLD_TUNE = """fileprivate enum LazyRenderTuning {
    /// Lines per chunk — must match chunkedLines' default.
    static let chunkLines = 40"""
    NEW_TUNE = """fileprivate enum LazyRenderTuning {
    /// Lines per chunk — must match chunkedLines' default.
    static let chunkLines = 40
    /// [V566-MINH] 终端卡片高度下限/上限(与旧 3/4 口径的替代物)。
    /// 下限 88pt ≈ 标题 + 两行输出; 上限 400pt 沿用 v46 以来的口径,
    /// 不放宽 —— 免得一张长输出卡片吃掉整屏。
    static let cardFloorHeight: CGFloat = 88
    static let cardCeilHeight: CGFloat = 400
    /// [V566-MINH] 字符数 → 行数的粗估(等宽 13pt, 约 76 字符/行)。
    /// ★刻意不做精确测量: 精确排版正是本项目反复踩坑的地方
    ///   (v47 的宽度不��源、v48 的碎片不重排), 而下限只需要「大概有几行」。
    static func linesShownInPreview(_ charCount: Int) -> Int {
        guard charCount > 0 else { return 0 }
        let perLine = 76
        var lines = charCount / perLine
        if charCount % perLine != 0 { lines += 1 }
        return lines
    }"""
    if OLD_TUNE not in t:
        raise RuntimeError("fix_toolbar_minheight_v566: LazyRenderTuning 锚点不在")
    t = t.replace(OLD_TUNE, NEW_TUNE, 1)

    # textContent 里那处引用的是 self.previewLinesCount, 换成同源换算。
    # 它在自己的 body 里已有 block, 但 previewLinesCount 不是现成属性,
    # 直接用 block.content 的字符数即可 —— 折叠预览显示的就是它。
    # ★必须连**前缀**一起换, 不能只换尾部实参 ——
    #   run#142 编译失败(exit 65)就是这里: 替换后留下了
    #   `min(max(linesShownInPreview(block.content.count), ...` 这样的**裸调**,
    #   而 linesShownInPreview 是 LazyRenderTuning 的静态方法 ⇒ 编译不过。
    #   ⚠️CI 只把 build.log 重定向到文件, `grep error: || true` 又吞掉了输出,
    #   所以页面上只看到「exit 65」而看不到报错行 —— 下次先看 grep 是否真的为空。
    t = t.replace(
        "max(linesShownInPreview(self.previewLinesCount)",
        "max(LazyRenderTuning.linesShownInPreview(block.content.count)", 1)

    # ---- 锚点 3: ToolLiveSheet 里加两个转发常量(视图内用 Self.xxx) ----
    OLD_LAZY = """    private static let lazyRenderChunkLines = LazyRenderTuning.chunkLines"""
    NEW_LAZY = """    /// [V566-MINH] 转发到底层 tuning —— 视图体内用 `Self.v566FloorHeight`。
    private static let v566FloorHeight = LazyRenderTuning.cardFloorHeight
    private static let v566CeilHeight = LazyRenderTuning.cardCeilHeight
    private static let lazyRenderChunkLines = LazyRenderTuning.chunkLines"""
    if OLD_LAZY not in t:
        raise RuntimeError("fix_toolbar_minheight_v566: lazyRender 常量锚点不在")
    t = t.replace(OLD_LAZY, NEW_LAZY, 1)

    # ★自检放在**全部替换完成之后**再跑。
    #   v56.6 实跑踩到: 自检放在锚点3之前时它立刻报「仍残留 3/4」——
    #   因为那时候 OLD_LAZY 那处还没替换。那不是判据错, 是**顺序错**:
    #   判据提前跑 ⇒ 后面真正的修改永远跑不到 ⇒ 整个 edit 崩掉,
    #   与 run#37118226923(v44 登记排在 v42 之前导致 fallback 抛异常、
    #   后面编译/打包一步都跑不到)是同一类形态。
    #   ⇒ 纪律: **判据只能放在所有替换之后**, 绝不能夹在中间。
    verify_toolbar_minheight_v566(t)

    return t


def verify_toolbar_minheight_v566(t):
    """v56.6 判据: 高度下限不再按宽度乘 3/4, 且两条重复路径同步。

    ★这一版判据的重点不是「新代码写对了吗」, 而是**覆盖范围**:
      3/4 这个写法在文件里有**两份**(textContent / snapshotTextContent),
      而历史上这个项目反复出现的形态就是「只改了一处, 另一个入口继续错」
      —— v13/v34 的宽度分叉、v48 的碎片只在一处重排。
      ⇒ 判据硬性要求: 带标记的 cardMinHeight **必须恰好两份**,
        且两份都在各自的宿主函数里。少一份 = 分叉 = 判据红。
    """
    # ★按「含标记的行数」查, 不按「文件里有没有出现过标记」——
    #   反向测试 S8 实跑抓到: 只查 `"[V566-MINH]" in t` 时,
    #   把前三处标记换成别的词就再也拦不住了(第 4 处还在, `in` 仍为真)。
    #   ⇒ 判据要的是「该有标记的地方都有标记」, 不是「某处有过标记」。
    #   本版共4 处标记: 两处 cardMinHeight 注释 + 两处 LazyRenderTuning/常量注释。
    n_mark = sum(1 for ln in t.split("\n") if "[V566-MINH]" in ln)
    if n_mark < 4:
        raise RuntimeError(
            "verify_toolbar_minheight_v566: 带 [V566-MINH] 标记的行只有 %d 处"
            "(应 >=4) —— 标记被摘掉或版本只改了一部分, 3/4 硬比例可能还在"
            % n_mark)

    # ★全文先剥掉注释再查 ——
    #   实跑踩到: 我在新注释里写了「旧式 `cardWidth * 3.0 / 4.0` 在 375 屏上是
    #   263pt」这句说明, 裸字符串搜索把它当成残留代码, 判据**把自己写的
    #   说明当成了罪证**。
    #   ⇒ 判据一旦开始搜代码, 就必须先剥注释, 否则任何带解释的修复都会被自己判红。
    #   这与 v56.4 的 `_strip_swift_noise` 是两回事: 那个连字符串一起剥,
    #   而这里要保留字符串(万一 needle 出现在字符串字面量里也要能看到)。
    tc = _v566_strip_comments_only(t)

    n_mark = t.count("[V566-MINH]")
    # 标记出现 4 次: 两处 cardMinHeight 注释 + 两处 LazyRenderTuning 注释。
    # 不硬编这个数(会随注释调整而脆), 只查「cardMinHeight 的新写法恰好两份」。
    n_new = tc.count("v566BodyLines * v566RowH + v566Pad")
    if n_new != 2:
        raise RuntimeError(
            "verify_toolbar_minheight_v566: 新写法出现 %d 次(应为 2)—— "
            "textContent 与 snapshotTextContent 是**重复的两份代码**, "
            "只改一处会让两个入口高度行为分叉" % n_new)

    # 覆盖范围: 两处新写法必须分别落在两个宿主函数体内
    for host, needle in (
            ("private var textContent: some View {",
             "v566BodyLines = CGFloat(min(max(LazyRenderTuning.linesShownInPreview(block.content.count), 0), 18))"),
            ("private func snapshotTextContent(_ text: String) -> some View {",
             "v566BodyLines = CGFloat(min(max(LazyRenderTuning.linesShownInPreview(text.count), 0), 18))")):
        i_host = t.find(host)
        if i_host < 0:
            raise RuntimeError(
                "verify_toolbar_minheight_v566: 找不到宿主 %s —— "
                "上游结构变了, 判据的覆盖范围锚点失效" % host.split("{")[0].strip())
        i_next = t.find("\n    private ", i_host + 10)
        seg = t[i_host:i_next] if i_next > 0 else t[i_host:]
        if needle not in seg:
            raise RuntimeError(
                "verify_toolbar_minheight_v566: %s 里没有它自己那行 —— "
                "两份重复路径只改了一处, 两个入口会分叉"
                % host.split("{")[0].strip())

    # 旧写法在**目标两处**必须消失。
    # ★实测踩到: 全文件其实有**三处** `cardWidth * 3.0 / 4.0` ——
    #   :1657 snapshotTextContent(终端)
    #   :2337 textContent(终端)
    #   :1809 file_edit 的 diff 卡片(**不是终端框**)
    #   调研只报了前两处, 判据若写成「全文件不得残留」就会要求连diff 卡片
    #   一起改 —— 那是扩大范围, 会动到本版根本没证据的路径。
    #   ⇒ 判据必须**按宿主函数定位**, 而不是全文件搜字符串。
    #   这也是「覆盖范围」的正向形态: 不只说「哪里不该有」, 还要说「哪里该有」。
    for host in ("private func snapshotTextContent(_ text: String) -> some View {",
                 "private var textContent: some View {"):
        i_host = tc.find(host)
        if i_host < 0:
            continue
        i_next = tc.find("\n    private ", i_host + 10)
        seg = tc[i_host:i_next] if i_next > 0 else tc[i_host:]
        if "cardWidth * 3.0 / 4.0" in seg:
            raise RuntimeError(
                "verify_toolbar_minheight_v566: %s 里仍残留 3/4 硬比例 —— "
                "375 屏上就是 263pt 硬下限, 空白过大的根源没去掉"
                % host.split("{")[0].strip())
    # 第三处(file_edit diff 卡片)必须**保持原样** —— 本版没有证据说它有问题,
    # 顺手改它就是把「有据可改」变成「顺手重构」, 那是本项目最常见的翻车方式。
    if tc.count("cardWidth * 3.0 / 4.0") != 1:
        raise RuntimeError(
            "verify_toolbar_minheight_v566: 全文件 3/4 应恰好剩 1 处(file_edit "
            "diff 卡片, 本版不动它), 实测 %d 处 —— 多改或漏改都会让范围失控"
            % tc.count("cardWidth * 3.0 / 4.0"))

    # 上下限常量必须在
    # ★必须带**行尾锚点**(换行/空白) —— 反向测试 S3 实跑抓到:
    #   `... = 400` 是 `... = 4000` 的**子串**, 裸 `in` 判据在 4000 时照样成立
    #   ⇒ 上限被改成 4000(卡片吃掉整屏)而判据全绿。
    #   这是「子串匹配」这一类洞的典型形态: 判据看起来在查某个值,
    #   实际只查了那个值的**前缀**。
    #   ⇒ 纪律: 查数值必须连着它的**终止符**一起查。
    for need in ("static let cardFloorHeight: CGFloat = 88",
                 "static let cardCeilHeight: CGFloat = 400"):
        if not any(ln.strip() == need for ln in tc.split("\n")):
            raise RuntimeError(
                "verify_toolbar_minheight_v566: 缺(或被改) `%s` —— "
                "没有上下限的话长输出会撑爆整屏/短输出会被撑出大片空白" % need)

    # 换算函数必须在, 且要有空输入分支(空卡片就该是空的)
    if "static func linesShownInPreview(_ charCount: Int) -> Int" not in t:
        raise RuntimeError(
            "verify_toolbar_minheight_v566: 缺 linesShownInPreview —— "
            "高度下限无从计算")
    i_fn = t.find("static func linesShownInPreview(_ charCount: Int) -> Int")
    i_end = t.find("\n    }", i_fn)
    seg_fn = t[i_fn:i_end] if i_end > 0 else t[i_fn:i_fn + 400]
    if "charCount > 0" not in seg_fn:
        raise RuntimeError(
            "verify_toolbar_minheight_v566: linesShownInPreview 没有空输入分支 —— "
            "空卡片会被算出 0 行下限, 退回固定高度, 等于绕回原来的 bug")

    return True


def fix_thumb_tail_v567(t):
    # ================================================================
    # v56.7 洞1: 折叠态缩略图「取末尾 N 行」不再切整段输出
    #   —— 治「终端框卡显示 / 滑动卡字」的主因
    # ================================================================
    # ★v56.6 的续: v56.6 治空白(几何), 本版治**每帧重复劳动**(性能),
    #   两版症状不重叠。仍然是**代码本身即证据**, 不靠猜。
    #
    # ToolLiveSheet.swift:3177
    #     let lines = text.components(separatedBy: "\n")
    #     return lines.suffix(count).joined(separator: "\n")
    # `components(separatedBy:)` 为**每一个**换行分配一个 String,
    # 而四个调用方只要末尾 12 行(:2952 / :3006)或 6 行(:3042 / :3050)。
    # shell 输出一屏几百行是常态, 而 body 每 2 秒至少求值 1 次(见洞2)、
    # 流式时每来一个 chunk 再 1 次 ⇒ **每帧几百个 String 分配, 全是白搬**。
    # ⇒ 「字卡 / 卡显示」不是画得慢, 是**每帧都在无谓地搬字符串**。
    #
    # ★为什么安全(可观测行为完全不变):
    #   `lines.suffix(count).joined(separator: "\n")` 的结果恒等于
    #   **第 (总行数 - count) 个换行之后的那段原文本**。所以只需数一次换行、
    #   定位一次, 然后原样切片 —— **零中间 String 分配**。
    #   判据 verify_thumb_perf_v567 里有 11 组输入的等价性自证。
    #
    # ★为什么单独成一个函数而不是与洞2 合并:
    #   洞1 在 ToolLiveSheet.swift, 洞2 在 AIChatView.swift ——
    #   **一次 edit 只能改一个文件**。合成一个函数会让「找锚点」在错误的文件里
    #   进行, 实跑直接报「洞2 锚点没找到」(这正是本函数第一版的形态)。

    if "[V567-PERF]" in t:
        return t

    OLD_LASTLINES = '''    private func lastLines(_ text: String, count: Int) -> String {
        let lines = text.components(separatedBy: "\\n")
        return lines.suffix(count).joined(separator: "\\n")
    }'''
    NEW_LASTLINES = '''    /// [V567-PERF] 取末尾 count 行 —— **只切出要的那几行**。
    ///
    /// 旧写法 `text.components(separatedBy: "\\n").suffix(count)` 会为**每一个**
    /// 换行分配一个 String, 而调用方只要最后 12 行。shell 输出一屏几百行是常态,
    /// 而 `body` 每 2 秒至少求值 1 次 ⇒ 每帧几百个 String 分配, 全是白搬。
    /// **字卡 / 卡显示的直接来源就在这里。**
    ///
    /// 等价性: 对同一输入, 产出与 `components+suffix+joined` **逐字节相同**
    /// (含末尾空行 / 行数不足 / count<=0 / 全空行 / 非 ASCII 五类边界;
    ///  判据 verify_thumb_perf_v567 里有 11 组输入的等价性自证)。
    private func lastLines(_ text: String, count: Int) -> String {
        // [V567-PERF] 接线处也带标记 —— 判据查的是「实现**与**接线都在」,
        // 只标实现不标接线的话, 写完实现忘了改调用点也会全绿。
        return Self.v567TailLines(text, count: count)
    }

    /// [V567-PERF] 取末尾 count 行 —— 与 components+suffix 等价, 但**零中间分配**。
    ///
    /// 关键: `lines.suffix(count).joined(separator: "\\n")` 的结果, 恰好就是
    /// **第 (总行数 - count) 个换行之后的那段原文本**。所以只需数一次换行、
    /// 定位一次, 然后原样切片, 一个额外 String 都不用造。
    private static func v567TailLines(_ text: String, count: Int) -> String {
        if count <= 0 { return "" }
        let nl = UInt8(ascii: "\\n")
        var total = 1                        // components 的语义: 末尾无换行也算一行
        for b in text.utf8 where b == nl { total += 1 }
        if total <= count { return text }      // 全部都要, 原样返回
        var seen = 0
        let view = text.utf8
        var idx = view.startIndex
        while idx < view.endIndex {
            if view[idx] == nl {
                seen += 1
                if seen == total - count {
                    return String(decoding: view.suffix(from: view.index(after: idx)),
                                  as: UTF8.self)
                }
            }
            idx = view.index(after: idx)
        }
        return text                           // 理论上到不了, 兜底不崩
    }'''
    if OLD_LASTLINES not in t:
        raise RuntimeError(
            "fix_thumb_tail_v567: 洞1 锚点没找到(lastLines 的 components+suffix 实现)"
            " —— 上游改过? 判据不会瞎改, 先确认真实形状")
    t = t.replace(OLD_LASTLINES, NEW_LASTLINES, 1)

    # ★自检放在**全部替换完成之后**(v56.6 洞1 的教训: 夹在中间会让整个 edit 崩掉)
    verify_thumb_perf_v567(t)
    return t


def fix_monitor_idem_v567(t):
    # ================================================================
    # v56.7 洞2: SystemResourceMonitor.start() 补幂等 guard
    #   —— 治「滑动像掉帧」
    # ================================================================
    # AIChatView.swift:97
    #     func start() {
    #         sampleCPU()
    #         updateMemory()
    #         timer = Timer.scheduledTimer(...)   // ← 直接覆盖, 旧的没 invalidate
    # 旧 timer **没有 invalidate 就被丢了引用**, 仍在 CommonModes 里每 2 秒跑一次,
    # 并往主线程塞 DispatchQueue.main.async。
    #
    # 调用点两处(ToolLiveSheet :2933 onAppear + :2937 onChange(of: isLive)),
    # 而缩略图在滚动里反复 appear/disappear ⇒ start 次数可以远大于 stop
    # ⇒ **泄漏 timer 累积**; 每个泄漏 timer 的 @Published 又让整棵
    # ToolPreviewThumbnail 重算 ⇒ **与洞1 相乘**。
    # ⇒ 这是「滑动时更卡」的直接解释: 滑一次多几个泄漏 timer。
    #
    # ★为什么安全: start() 变幂等(已有 timer 直接返回), stop() 语义一字未改。
    #   纯粹「别重复起同一个表」, 不改任何读数。

    if "if timer != nil { return }" in t:
        return t

    OLD_START = '''    func start() {
        sampleCPU() // prime the previous ticks
        updateMemory()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in'''
    NEW_START = '''    // [V567-PERF] 幂等: 已有 timer 就直接返回。
    // 旧写法直接 `timer = Timer.scheduledTimer(...)` 覆盖 —— 旧 timer **没有**
    // invalidate 就被丢了引用, 仍在 CommonModes 里每 2 秒跑一次。
    // 调用点两处(onAppear + onChange(of: isLive)), 缩略图滚动中反复
    // appear/disappear ⇒ start 次数可以远大于 stop ⇒ 泄漏 timer 累积,
    // 每个都往主线程塞 DispatchQueue.main.async ⇒ 滑动时额外掉帧,
    // 且每次 @Published 都让整棵缩略图重算 ⇒ 与洞1 相乘。
    func start() {
        if timer != nil { return }        // [V567-PERF] 幂等 guard
        sampleCPU() // prime the previous ticks
        updateMemory()
        timer = Timer.scheduledTimer(withTimeInterval: 2, repeats: true) { [weak self] _ in'''
    if OLD_START not in t:
        raise RuntimeError(
            "fix_monitor_idem_v567: 洞2 锚点没找到(SystemResourceMonitor.start)"
            " —— 上游改过? 先确认真实形状")
    t = t.replace(OLD_START, NEW_START, 1)

    # ★自检放在替换之后
    verify_thumb_perf_v567(t)
    return t

def verify_thumb_perf_v567(t):
    """v56.7 判据: 折叠态缩略图两处性能洞都堵上, 且 tailLines 与旧实现等价。

    ★本版判据的三个要点:
      1. **覆盖范围**: 洞1 在 ToolLiveSheet.swift, 洞2 在 AIChatView.swift ——
         一次 edit 只碰一个文件, 所以本函数被**两个 edit 各自调用一次**,
         每次只查自己那半(用「该半的特征是否存在」区分, 不用参数传)。
         这是 v56.6「覆盖范围判据」在跨文件场景下的形态。
      2. **等价性自证**: 洞1 换了实现, 必须证明**行为没变**。
         这里不靠注释保证, 而是拿 11 组输入把新旧实现都跑一遍比对字节。
         ⇒ 判据自己证明「这是纯优化, 不是改行为」。
      3. **标记行数**: 查的是「该有标记的地方都有」, 与 v56.6 同纪律。
    """
    tc = _v566_strip_comments_only(t)

    is_sheet = "private static func v567TailLines(" in tc
    is_chat = "if timer != nil { return }" in tc
    if not is_sheet and not is_chat:
        raise RuntimeError(
            "verify_thumb_perf_v567: 两处性能洞一个都没堵上 —— "
            "v567TailLines 与 start() 幂等 guard 都没找到")

    if is_sheet:
        # 洞1: lastLines 必须已改成转发, 旧实现必须消失
        if "let lines = text.components(separatedBy:" in tc:
            raise RuntimeError(
                "verify_thumb_perf_v567: lastLines 仍在用 components+suffix —— "
                "整段输出的 String 分配还在, 卡字/卡显示没治")
        if "return Self.v567TailLines(text, count: count)" not in tc:
            raise RuntimeError(
                "verify_thumb_perf_v567: lastLines 没有转发到 v567TailLines "
                "—— 实现写了但没接上, 等于没修")
        # ★范围失控: 全文件 components(separatedBy: "\n") 另有 1 处
        #   (chunkedLines :2352, 它本来就要全部行), 多了少了都要红。
        n_comp = tc.count('components(separatedBy: "\\n")')
        if n_comp != 1:
            raise RuntimeError(
                "verify_thumb_perf_v567: ToolLiveSheet 里 components(separatedBy)"
                " 剩 %d 处(应恰好 1 处: chunkedLines :2352) —— "
                "要么 lastLines 没改干净, 要么误改了不该改的地方" % n_comp)
        # v567TailLines 必须有三条边界分支
        k = tc.find("private static func v567TailLines(")
        e = tc.find("\n    }", k)
        seg = tc[k:e if e > 0 else k + 2000]
        for need, why in (
                ('if count <= 0 { return "" }', "count<=0 边界"),
                ("if total <= count { return text }", "行数不足边界"),
                ("String(decoding: view.suffix(from:", "原样切片(不能重新拼装)")):
            if need not in seg:
                raise RuntimeError(
                    "verify_thumb_perf_v567: v567TailLines 缺 %s —— %s"
                    " 这条丢了就会和旧实现不等价" % (need, why))
        # ★等价性自证: 11 组输入, 新旧实现必须逐字节相同
        _v567_assert_tail_equiv()

    if is_chat:
        # 洞2: guard 必须紧跟在 func start() 之后(不能挪到别处充数)
        k = tc.find("func start() {")
        if k < 0:
            raise RuntimeError("verify_thumb_perf_v567: 找不到 func start()")
        if "if timer != nil { return }" not in tc[k:k + 240]:
            raise RuntimeError(
                "verify_thumb_perf_v567: SystemResourceMonitor.start() 没有幂等 "
                "guard —— 重复 start 会泄漏 timer, 滑动时额外掉帧")
        # 全文只能有一处这个 guard(防重复插入)
        n_guard = tc.count("if timer != nil { return }")
        if n_guard != 1:
            raise RuntimeError(
                "verify_thumb_perf_v567: 幂等 guard 出现 %d 处(应恰好 1 处) "
                "—— 重复插入会让 stop() 之后再也起不来" % n_guard)

    # ---- 标记行数: **按文件各自计数**, 不跨文件累计 ----
    # ★实跑踩到: 洞1 与洞2 在**两个不同文件**里, 而一次 edit 只碰一个文件。
    #   原来写「两文件合起来 >=6」⇒ 单跑任一 edit 都只有 2 处标记, 必然判红。
    #   ⇒ 判据的阈值必须与「判据被调用的那一半」匹配, 否则就是自己拦自己。
    #   (与 v56.6「覆盖范围按宿主函数定位」同一纪律: 阈值要跟着作用域走。)
    n_mark = sum(1 for ln in t.split("\n") if "[V567-PERF]" in ln)
    need = 3 if is_sheet else 2          # 洞1: 实现+接线+tailLines 声明 / 洞2: 注释块+guard 行
    if n_mark < need:
        raise RuntimeError(
            "verify_thumb_perf_v567: 带 [V567-PERF] 标记的行只有 %d 处(本文件应 >=%d) "
            "—— 标记被摘掉或本版只改了一半" % (n_mark, need))

    return True


def _v567_old_tail(text, count):
    """旧实现(components+suffix)的 Python 等价物, 只用于判据自证。"""
    if count <= 0:
        return ""
    lines = text.split("\n")
    return "\n".join(lines[len(lines) - count:]) if count < len(lines) else "\n".join(lines)


def _v567_new_tail(text, count):
    """新实现(v567TailLines)的 Python 等价物, 逐行照抄 Swift 的算法。"""
    if count <= 0:
        return ""
    nl = "\n"
    total = 1
    for b in text.encode("utf-8"):
        if chr(b) == nl:
            total += 1
    if total <= count:
        return text
    seen = 0
    # 逐字节扫(与 Swift 侧 String.UTF8View 一致), 定位第 (total-count) 个换行
    for i, b in enumerate(text.encode("utf-8")):
        if chr(b) == nl:
            seen += 1
            if seen == total - count:
                return text.encode("utf-8")[i + 1:].decode("utf-8")
    return text


def _v567_assert_tail_equiv():
    """等价性自证: 11 组输入, 新旧实现必须逐字节相同。

    ★为什么必须有这一步:
      v56.6 教过「判据全绿 ≠ 改对了」, 而这一版是**换实现**——
      光判「新代码在」不能证明「行为没变」。这一层是拿数据证明的。
      ★它已经真的抓到过一次 bug: 第一版按「跳过前 N 行再切」实现,
        在 '\\n\\n\\n' count=2 时少切一行(返回 '' 而旧的返回 '\\n'),
        纯靠肉眼看不出来 —— 是这一层把它逼出来的。
    """
    cases = [
        ("", 12),
        ("a", 12),
        ("a\nb\nc", 2),
        ("a\nb\nc", 12),          # 行数不足
        ("a\nb\nc", 0),           # count<=0
        ("a\nb\nc", -1),          # count<0
        ("a\nb\nc\n", 2),         # 末尾有空行
        ("a\n\nb", 12),           # 中间空行
        ("\n\n\n", 2),            # 全空行 ★第一版就是在这条上错的
        ("中文\n输出\n第三行", 2),  # 非 ASCII
        ("a\nb\nc\nd\ne", 3),     # 中间截取
    ]
    for text, count in cases:
        old = _v567_old_tail(text, count)
        new = _v567_new_tail(text, count)
        if old != new:
            raise RuntimeError(
                "verify_thumb_perf_v567: v567TailLines 与旧实现**不等价** "
                "(input=%r count=%d old=%r new=%r) —— 这就不是纯优化了, "
                "必须改到逐字节相同才能上线" % (text, count, old, new))
    return True



# =====================================================================
# v56.8 —— ToolCapsuleView「卡一半一半显示」/「卡一下才显示」
# =====================================================================
#
# ★★★ 这一切入点是用户 2026-10-04 23:56 的截图直接给出的, 不是推断 ★★★
# 截图内容: 三行 `>_ 检查系统环境信息 2s` / `>_ 检查常用工具与运行时 1s` /
#          `>_ 检查 Minis 目录结构 0.8s`
# 绿色 terminal 图标 + 标题 + 等宽耗时  ⇒  **ToolCapsuleView**
# (AssistantBlockView.swift:218, 由 :42 的
#  `ToolCapsuleView(block:block, icon:"terminal", accentColor:.green, ...)` 构造)
#
# ★★ 关键事实: AssistantBlockView.swift **零历史注入标记** ——
#   `grep -oE "\[V[0-9]+...\]" AssistantBlockView.swift` 结果为空。
#   v41~v53 那整条高度补高链(V41-KVOPRE / V44-TEXTFRAME / V45-TVHFIX /
#   V53 的 debt 记账)**全部挂在 SelectableMarkdownView.swift 上**, 只管
#   Markdown 文本视图, **从不覆盖这个文件**。
#   ⇒ 之前 v38~v56 一路在「卡字」上反复打转(改了十几次宽度/高度/去重),
#     治的一直是 Markdown 那条路, 而用户指的终端框是这条路上的**另一个对象**。
#   这是本项目第四次「探针/修法装错对象」(见 MSG_V568 顶部铁律)。
#
# 【病根: ShimmerOverlay 把动画目标和布局量绑死】
#
#   AssistantBlockView.swift:161 ShimmerOverlay.body:
#       GeometryReader { geo in
#           Rectangle().frame(width: diag, height: geo.size.height)
#                      .offset(x: offsetX * geo.size.width)   ← ★这里
#                      .onAppear { withAnimation(.linear(2.8)
#                                   .repeatForever(...)) { offsetX = 1.0 } }
#       }.clipped()
#
#   offsetX 是 @State, 动画目标是 `offsetX * geo.size.width`。
#   **目标里含 geo.size** ⇒ 每次 body 重算出新的 geo.size, 动画目标就变。
#   SwiftUI 对 @State 的 animation 是「从当前呈现值 ease 到新目标」——
#   于是一个跑到一半的 repeatForever 被**打断并重新 ease**,
#   闪光的亮条就**停在半路 / 跳到另一半**, 用户看到的就是:
#       「卡一下才显示」+「卡一半一半显示」。
#
#   为什么会重算: 这个 capsule 在消息流里, block 是 @ObservedObject,
#   流式输出时每来一个 chunk 就重算; 且 UICollectionView 滚动中 cell
#   反复 prepareForReuse → onAppear 反复触发 → 动画反复重启。
#
# 【修法: 把动画目标从「乘 geo.size」改成「乘固定常数」】
#   offset 的目标只依赖 offsetX 这一个 @State, 与任何布局量解耦。
#   亮条扫过的距离用 diag(几何常量) 换算一次即可, 之后 body 怎么重算
#   动画目标都不变 ⇒ repeatForever 不再被打断。
#
# ★为什么不用 GeometryReader 也不用 TimelineView:
#   - GeometryReader 在 overlay 里会引入一次额外的布局 pass;
#   - TimelineView(.animation) 每帧给新值, 在 UICollectionView 里逐帧
#     驱动 body 是掉帧的主要来源(见 MSG_V53: 滚动一停 halfBands 就归零);
#   两者都会把「修一处」变成「加一处」。

SHIMMER_OLD = '''struct ShimmerOverlay: View {
    @Environment(\\.colorScheme) private var colorScheme
    @State private var offsetX: CGFloat = -1.0

    private var peakOpacity: CGFloat {
        colorScheme == .light ? 0.75 : 0.25
    }

    private func bell(_ x: CGFloat) -> CGFloat {
        exp(-4.5 * x * x)
    }

    private var stableStops: [Gradient.Stop] {
        let stepCount = 12
        let bandRadius: CGFloat = 0.40
        let center: CGFloat = 0.5
        var stops: [Gradient.Stop] = []
        stops.append(.init(color: .white.opacity(0), location: 0))
        for i in 0...stepCount {
            let frac = CGFloat(i) / CGFloat(stepCount)
            let pos = center - bandRadius + frac * bandRadius * 2.0
            let dist = (pos - center) / bandRadius
            let alpha = bell(dist) * peakOpacity
            stops.append(.init(color: .white.opacity(Double(alpha)), location: pos))
        }
        stops.append(.init(color: .white.opacity(0), location: 1))
        return stops
    }

    var body: some View {
        GeometryReader { geo in
            let diag = geo.size.width + geo.size.height
            Rectangle()
                .fill(
                    LinearGradient(
                        stops: stableStops,
                        startPoint: UnitPoint(x: 0, y: 1),
                        endPoint: UnitPoint(x: 1, y: 0)
                    )
                )
                .frame(width: diag, height: geo.size.height)
                .offset(x: offsetX * geo.size.width)
                .onAppear {
                    withAnimation(
                        .linear(duration: 2.8)
                        .repeatForever(autoreverses: false)
                    ) {
                        offsetX = 1.0
                    }
                }
        }
        .clipped()
    }
}'''

SHIMMER_NEW = '''struct ShimmerOverlay: View {
    @Environment(\\.colorScheme) private var colorScheme
    @State private var offsetX: CGFloat = -1.0

    // [V568-SHIMMER] 亮条的**行程**, 单位 pt。
    // ★这一行是本版全部修复的支点。旧代码写的是 `offsetX * geo.size.width` ——
    //   动画目标里含布局量。于是 body 每重算一次(流式 chunk / cell 复用),
    //   geo.size 就变, @State animation 就从「当前呈现值」重新 ease 到新目标,
    //   正在跑的 repeatForever 被**打断**: 亮条停在半路或跳到另一半。
    //   用户看到的正是「卡一下才显示」+「卡一半一半显示」。
    // 现在目标只依赖 offsetX 一个 @State ⇒ body 怎么重算都不打断动画。
    private static let travel: CGFloat = 600

    private var peakOpacity: CGFloat {
        colorScheme == .light ? 0.75 : 0.25
    }

    private func bell(_ x: CGFloat) -> CGFloat {
        exp(-4.5 * x * x)
    }

    private var stableStops: [Gradient.Stop] {
        let stepCount = 12
        let bandRadius: CGFloat = 0.40
        let center: CGFloat = 0.5
        var stops: [Gradient.Stop] = []
        stops.append(.init(color: .white.opacity(0), location: 0))
        for i in 0...stepCount {
            let frac = CGFloat(i) / CGFloat(stepCount)
            let pos = center - bandRadius + frac * bandRadius * 2.0
            let dist = (pos - center) / bandRadius
            let alpha = bell(dist) * peakOpacity
            stops.append(.init(color: .white.opacity(Double(alpha)), location: pos))
        }
        stops.append(.init(color: .white.opacity(0), location: 1))
        return stops
    }

    var body: some View {
        // [V568-SHIMMER] GeometryReader **保留**: 亮条本身要铺满 capsule 的
        // 宽度, 那是真实布局量。但它**不再进入 offset 的目标**。
        GeometryReader { geo in
            let diag = geo.size.width + geo.size.height
            Rectangle()
                .fill(
                    LinearGradient(
                        stops: stableStops,
                        startPoint: UnitPoint(x: 0, y: 1),
                        endPoint: UnitPoint(x: 1, y: 0)
                    )
                )
                .frame(width: diag, height: geo.size.height)
                // [V568-SHIMMER] ★只乘固定行程, 不乘 geo.size.width。
                // 视觉等价: 旧版从 -W 扫到 +W(总 2W); 新版从 -travel 扫到
                // +travel。travel 取 600pt 足以覆盖 iPhone 上最宽的 capsule,
                // 且是**编译期常量** ⇒ 动画目标与布局彻底解耦。
                .offset(x: offsetX * Self.travel)
                .onAppear {
                    withAnimation(
                        .linear(duration: 2.8)
                        .repeatForever(autoreverses: false)
                    ) {
                        offsetX = 1.0
                    }
                }
        }
        .clipped()
    }
}'''

CAPSULE_FRAME_OLD = '''            .padding(.horizontal, 12)
            .frame(height: 36)
            .background(Color(UIColor.systemGray6))
            .clipShape(Capsule())'''

CAPSULE_FRAME_NEW = '''            .padding(.horizontal, 12)
            .frame(height: 36)
            // [V568-SHIMMER] 固定 36pt 已是上游既有约定(cell 估算也按 36),
            // 这里只**显式钉住高度**, 让 ShimmerOverlay 的 GeometryReader 拿到
            // 稳定尺寸。★不改任何视觉: 上游 .frame(height: 36) 本来就是它。
            .frame(height: 36)
            .background(Color(UIColor.systemGray6))
            .clipShape(Capsule())'''


def fix_capsule_shimmer_v568(t):
    """v56.8: 治 ToolCapsuleView 的「卡一下才显示 / 卡一半一半显示」。

    ★★★ 本版对象由用户截图直接确定, 不是推断 ★★★
    见 MSG_V568 顶部: 绿色 terminal 图标 + 标题 + 等宽耗时 = ToolCapsuleView,
    位于 AssistantBlockView.swift:218; 该文件**零历史注入标记**。

    两处改动:
      1. ShimmerOverlay 的 offset 目标 `offsetX * geo.size.width`
         → `offsetX * Self.travel`(固定 600pt), 动画与布局解耦。
         这是「卡一半」的真正病根。
      2. capsule 的 .frame(height: 36) 显式钉住(幂等加固), 让 GeometryReader
         拿到稳定高度。只钉不缩, 不改视觉。

    ★为什么 2 不是多余的: UICollectionView 滚动中 cell prepareForReuse
      后 onAppear 反复触发, 若此时高度仍在变化, 新版 offset 虽然不被
      布局量打断, 但亮条的高度仍会跟着跳 —— 视觉上还是「跳一下」。
      钉死高度让亮条尺寸也稳定。
    """
    if "[V568-SHIMMER]" in t:
        return t

    if SHIMMER_OLD not in t:
        raise RuntimeError(
            "fix_capsule_shimmer_v568: ShimmerOverlay 的 body 锚点没找到 —— "
            "上游结构可能变了, 需重新定位(不要先怀疑上游, 先 grep 干净副本)")

    if CAPSULE_FRAME_OLD not in t:
        raise RuntimeError(
            "fix_capsule_shimmer_v568: capsule 的 .frame(height: 36) 锚点"
            "没找到 —— 上游可能改了胶囊的高度或 padding 顺序")

    t = t.replace(SHIMMER_OLD, SHIMMER_NEW, 1)
    t = t.replace(CAPSULE_FRAME_OLD, CAPSULE_FRAME_NEW, 1)
    return t


def verify_capsule_shimmer_v568(t):
    """v56.8 判据: ShimmerOverlay 的 offset 已与 geo.size 解耦, 且旧耦合零残留。

    四层:
      1. **范围**: 两处 [V568-SHIMMER] 都在(ShimmerOverlay + capsule frame)。
      2. **旧耦合零残留**: 全文件**剥注释后**不得再出现
         `offsetX * geo.size.width`。这是本版唯一真正要治的东西,
         残留一处就等于没修。
      3. **新耦合在位**: 必须有 `offsetX * Self.travel`, 且 `travel`
         是编译期常量(static let), 不是 var 也不是从 geo 算出来的。
      4. **动画没被顺手删掉**: withAnimation + repeatForever 必须在 ——
         防止「为了不卡就把动画删了」这种假修复(会静默改变产品观感)。
    """
    tc = _v566_strip_comments_only(t)

    # ★先把 ShimmerOverlay 的**函数体**单独切出来。
    #   踩坑记录(判据自己的第一版就是这么错的): 判据第4层查
    #   「repeatForever / withAnimation 还在不在」, 但本文件**本来就有另外
    #   3 处动画**(ShimmerOverlay 之外的弹跳点 dotsActive、:990、:1126)。
    #   于是一条「删掉 ShimmerOverlay 的 repeatForever」的 sabotage
    #   依然能在文件别处找到 repeatForever ⇒ **判据全绿放过了删动画的假修复**。
    #   ⇒ 动画检查必须**限定在 ShimmerOverlay 函数体内**, 不能全文件搜。
    i0 = tc.find("struct ShimmerOverlay")
    if i0 < 0:
        raise RuntimeError(
            "verify_capsule_shimmer_v568: 找不到 struct ShimmerOverlay —— "
            "对象本身没了(是删了? 还是上游改名了?)")
    i1 = tc.find("\nstruct ", i0 + 1)
    if i1 < 0:
        i1 = len(tc)
    shimmer = tc[i0:i1]

    # 1. 范围(★按本次注入实际产生的标记数 4 处钉死, 少一处就是漏改)
    n_mark = sum(1 for ln in t.split("\n") if "[V568-SHIMMER]" in ln)
    if n_mark < 4:
        raise RuntimeError(
            "verify_capsule_shimmer_v568: 带 [V568-SHIMMER] 标记的行只有 %d 处"
            "(应 >=4 —— travel 声明 1 / offset 换算 1 / GeometryReader 保留说明 1 / "
            "capsule 高度钉死 1。少一处说明本次注入被部分回退或截断)" % n_mark)

    # 3. 新耦合在位且是编译期常量
    if "offsetX * Self.travel" not in tc:
        raise RuntimeError(
            "verify_capsule_shimmer_v568: 没有 `offsetX * Self.travel` —— "
            "offset 目标必须只依赖 @State offsetX, 与任何布局量解耦")

    if "static let travel: CGFloat" not in tc:
        raise RuntimeError(
            "verify_capsule_shimmer_v568: travel 不是 static let 常量 —— "
            "若它是 var 或从 geo 算出来, 就等于把耦合换了个地方, 没真解耦")

    # 4. 动画必须还在 —— ★**只查 ShimmerOverlay 函数体**(见上方 i0/i1 的说明)
    if "repeatForever" not in shimmer:
        raise RuntimeError(
            "verify_capsule_shimmer_v568: ShimmerOverlay 里的 repeatForever "
            "消失了 —— 本版是**解耦**, 不是删动画。删掉虽然不卡了, 但产品观感"
            "变了, 属于未经用户确认的行为改变(假修复)")

    if "withAnimation" not in shimmer:
        raise RuntimeError(
            "verify_capsule_shimmer_v568: ShimmerOverlay 里的 withAnimation "
            "消失了 —— 同上, 动画被删")

    # 5. 覆盖失控: 全文件**剥注释后**的旧耦合必须恰好 0 处。
    #    数量判据比"至少0处"严 —— 别人再引入一处同类耦合会被抓住。
    n_old = tc.count("offsetX * geo.size.width")
    if n_old != 0:
        raise RuntimeError(
            "verify_capsule_shimmer_v568: 剥注释后仍有 %d 处 "
            "`offsetX * geo.size.width`(应为 0) —— 动画目标还挂在布局量上, "
            "body 一重算就打断 repeatForever, 「卡一半一半显示」没治" % n_old)

    return True


# 供反向测试 import: v56.8 的「新旧行为」等价性自证。
# 旧版 offset 目标 = offsetX * geo.size.width
# 新版 offset 目标 = offsetX * 600
# 视觉上都要「从卡片左侧外扫到右侧外」, 所以只要 travel 覆盖最宽卡片即可。
# 这里钉的是**几何覆盖判据**: 375pt 屏上最宽的 capsule 不会超过屏宽,
# travel=600 足够从 -600 扫到 +600。
V568_TRAVEL_PT = 600
V568_MAX_SCREEN_PT = 440   # iPhone 16 Pro Max 逻辑宽度的上界, 留足余量



# =====================================================================
# v56.9 —— KVO skipSame 把欠账帧全部跳过(「定时任务」那行只剩上半)
# =====================================================================
#
# ★★★ 本版归因来自**装机日志 + 用户截图**, 不是推断 ★★★
#
# 【用户反馈】v56.8 装机后: 「根本没修复, 所有的情况一如既往, 滑动掉帧,
#   都不知道滑到哪里去了, 字还是滑动的时候卡掉, 显示也不完全」
#   两张截图对比: 同一段列表, 一张「文件处理 / 定时任务」两行都完整,
#   另一张「定时任务」那行**只剩上半**(halfBand 指纹), 且「检查环境配置」
#   胶囊同时压上来。
#
# 【装机日志的决定性读数】minis-2026-10-05.log / 7951 行
#
#   [V45-TVHFIX] 101 条, **debt 全部 0.0**  —— 补高链自己说「我补好了」
#   [V56-KVO]    95 条, **全部是 skipSame**, **没有一条 fixed/写入**
#
#   而 95 条里 **13 条 svH < needH**(几何确实欠着):
#     svH=26.7   needH=49.0     ← 就是「定时任务」那类短 cell
#     svH=132.7  needH=177.3
#     svH=210.0  needH=228.0
#     svH=266.0  needH=333.0
#     svH=283.0  needH=573.7
#     svH=372.7  needH=730.7
#     svH=407.0  needH=832.3
#     svH=657.0  needH=724.0
#     svH=792.7  needH=1061.0
#     svH=959.7  needH=1340.3
#     svH=1023.7 needH=1052.0
#     svH=1406.7 needH=1739.7
#     svH=1449.7 needH=1739.7 (被 29 次重复计入正常组)
#
#   ⇒ **KVO 抢帧器 95 次全部走了「跳过」分支, 一次都没真正修**。
#     而其中 13 次几何是真的欠着的。
#
# 【真凶: skipSame 分支只改局部变量, 不写 obj.frame】
#   SelectableMarkdownView.swift:5917 附近(v56.1 引入的同值抑制):
#
#       let _v56dup = abs(lastH - _v42Need) < 0.5 && (now - lastAt) < 0.12
#       if _v56dup {
#           NSLog("[V56-KVO] skipSame ...")
#           ...
#           var _v56hFix = f
#           _v56hFix.size.height = _v42Need     // ★ 只改**局部副本**
#           f = _v56hFix
#       } else if _v42Need > 1, f.size.height + 0.5 < _v42Need {
#           ...
#           obj.frame = _hFix                   // ★ 真正写回
#       }
#
#   抑制键是 (目标高度, 0.12s 窗), **完全不看当前几何**。
#   而欠账恰恰是一个**状态**: `f.size.height < needH`。
#
#   ⇒ 上一次 pass 已经写过 needH, 0.12s 内又被 SwiftUI 写回矮值, 于是
#     「目标高度与上次相同」+「在窗内」⇒ 判 dup ⇒ 跳过 ⇒ **欠账留着**。
#     而下一个 0.12s 之后呢? KVO **不再触发**(几何没变 ⇒ 没 KVO 事件) ⇒
#     欠账**永久凝固** ⇒ 那一行就一直只剩上半。
#
# ★这正是 v39/v40 判过「补齐代码一次都没执行过」的那个现象, 但根因反过来了:
#   v39/v40 的结论是「代码没跑」; v56.9 查明是「跑了, 但被自己写的抑制挡掉」。
#   ⇒ **同一个现象, 第 3 次以新根因回来。这也是判据全绿却治不好的第 5 次。**
#
# 【修法: 抑制必须以「几何是否真的欠着」为前提, 而不是以「值是否重复」】
#   重复抑制的**本意**是省掉「同 tick 内反复写同一个高度」这种几何零变化的
#   无谓同步 layout —— 那个本意是对的, 保留。
#   但当 `f.size.height + 0.5 < _v42Need` 时, 写入会让几何**真的变化**,
#   那就不是「零变化」, 必须写。
#   ⇒ 一行条件: skipSame 必须**且必须**要求「当前高度已达 needH」。

V569_SKIP_OLD = '''            if _v56dup {
                // 同窗同值: 跳过 obj.frame 写入(几何零变化)。
                struct _V56Skip { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                if _v56now - _V56Skip.last > 0.5 {
                    _V56Skip.last = _v56now
                    _V56Skip.n &+= 1
                    // ★整型转换必须用 UInt64(...), 不能用 (unsigned long long)。
                    //  run#135 实测: `(unsigned long long)x` 让 Swift 词法器在
                    //  `long long)x` 处报 `expected ',' separator`(两列都报)。
                    //  全项目 Swift 侧此前**从未**用过 C 风格转换 —— 只有
                    //  NSTextContainerSetSizeGuard.m 那个 .m 文件里有(ObjC 合法)。
                    //  v53-MEM(产物 8438 行)早已编译验证的写法是 `UInt64(...)`。
                    // ⇒ 纪律 48 扩展: **语法形式也要照抄已编译验证的代码**,
                    //   不只是 API 名。
                    NSLog("[V56-KVO] skipSame svH=%.1f needH=%.1f n=%u",
                          f.size.height, _v42Need, _V56Skip.n)
                }
                _V56KVOW.skipped &+= 1
                // 与下面「补完立刻交棒」同语义: 即使跳过 obj.frame 写入,
                // 局部 f 也要反映已补好的高度, 否则后续任何读 f 的探针
                // 都会看到欠账值、误判成"没补上"。
                var _v56hFix = f
                _v56hFix.size.height = _v42Need
                f = _v56hFix
            } else if _v42Need > 1, f.size.height + 0.5 < _v42Need {'''

V569_SKIP_NEW = '''            // [V569-DEBT] ★本版全部修复的支点。
            // 「同值抑制」只该在**几何零变化**时生效。
            // 而欠账是**状态**: `f.size.height < needH`。
            // 装机构装证据(minis-2026-10-05.log, 95 条 V56-KVO **全是 skipSame**,
            // 零条 fixed, 其中 13 条 svH < needH)证明:
            //   上一 pass 写过 needH → 0.12s 内被 SwiftUI 写回矮值 →
            //   「目标高度与上次相同」+「在窗内」⇒ 判 dup ⇒ 跳过 obj.frame 写入 →
            //   几何没变 ⇒ KVO **不再触发** ⇒ 欠账**永久凝固**。
            //   ⇒ 那一行就一直只剩上半(v53 起反复出现的 halfBand)。
            // 判据随之从「值是否重复」改成「值是否重复 **且** 几何已达标」。
            let _v56noDebt = f.size.height + 0.5 >= _v42Need
            if _v56dup && _v56noDebt {
                // 同窗同值 **且** 当前高度已达标: 纯重复写, 跳过(几何零变化)。
                struct _V56Skip { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                if _v56now - _V56Skip.last > 0.5 {
                    _V56Skip.last = _v56now
                    _V56Skip.n &+= 1
                    NSLog("[V56-KVO] skipSame svH=%.1f needH=%.1f n=%u",
                          f.size.height, _v42Need, _V56Skip.n)
                }
                _V56KVOW.skipped &+= 1
                var _v56hFix = f
                _v56hFix.size.height = _v42Need
                f = _v56hFix
            } else if _v42Need > 1, f.size.height + 0.5 < _v42Need {'''


V570_KVOCW_OLD = """            // [V41-POLLED] polluted 判据增加**高度维度**: 宽度正常但高度欠账的帧
            // 也必须进修正分支, 不能被 `if !polluted { return }` 放过。
            let _hDebt = _v42Need > 1 && f.size.height + 0.5 < _v42Need
            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt
            if !polluted {"""

V570_KVOCW_NEW = """            // [V41-POLLED] polluted 判据增加**高度维度**: 宽度正常但高度欠账的帧
            // 也必须进修正分支, 不能被 `if !polluted { return }` 放过。
            let _hDebt = _v42Need > 1 && f.size.height + 0.5 < _v42Need
            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
                || _hDebt || _v570Dirty
            if !polluted {"""


# ★v57.1★ 装机日志(minis-2026-10-05.log, 03:19:00.543~.547)证明 v57.0
#   的纠偏位置**仍然太晚**: 同一帧内六个既有探针与实际排版全部排在它之前。
#   ⇒ 整块从「早退之前」上移到「cvW 就绪之后、KVO 闭包第一条业务语句」。
V571_HEAD_OLD = """            guard cvW > 1 else { return }
            // [V41-KVOPRE] 抢帧器抓到的**原始**值(脏)。见函数 docstring「诊断打穿pass 内 vs pass 后」。"""

V571_HEAD_NEW = """            guard cvW > 1 else { return }
            // [V570-KVOCW] ★v57.1 全部修复的支点★（装机日志逐毫秒证据，见 edit() 理由）
            //
            // 【v57.0 为什么不够 —— 同一帧逐毫秒对齐, 六个既有探针全排在纠偏之前】
            // 装机日志 minis-2026-10-05.log, len=297 那一 tick（4ms 内）：
            //   .543 V41-KVOPRE    sv=(16.0,79.7,358.0,297.7)
            //   .544 V43-WIDTH     dirtyW=390.0 netW=358.0 dh=22.7
            //   .545 V42-MISS      selfMeasured needH=409.7 tcW=358.0   <- 测高用 358(对)
            //   .545 V41-KVOHEIGHT fixed svH=297.7 -> needH=409.7 debt=112.0
            //   .545 [V45]         v18W=358 kvoW=390 laidW=-1 **usedH=258.7 needH=409.7**
            //   .545 V44-TEXTFRAME tvW=390.0 svW=358.0 **tcW=390.0**
            //   .546 V570-KVOCW    **dirty=1**  <- v57.0 的纠偏到这里才执行
            //   .546 V50-PINW      tcW=358.0                            <- 纠偏成功
            //   .547 V50-LAIDW     laidW=358.0 regrabbed=1
            //
            // ⇒ `usedH=258.7 needH=409.7` 差 151pt(≈6 行), 而这 151pt 正是
            //   **落屏用的那份按 390 排的行碎片**。v57.0 把它纠回来了, 但
            //   纠正发生在排版之后 ⇒ 屏幕仍然是按 390 排的那一版。
            //   v57.0 的判据「纠偏行号 < 早退行号」是**真的通过了**, 但那个
            //   顺序约束**太弱** —— 早退本身就在一帧的中段, 前面还有六条语句。
            //
            // 【v57.1 的顺序约束: 纠偏必须早于「本帧第一次用宽度做决策」】
            //   排在最前的三个必须全在纠偏之后:
            //     V43-WIDTH 声明行  (它读 _v43DirtyW = textContainer.size.width)
            //     V42-MISS 调用行    (它 sizeThatFits 用 _v42TCW, 并刷新闩锁键 latchW)
            //     V44-TEXTFRAME 行   (诊断落点; 它读到的 tcW 必须是纠偏**后**的值)
            //   满足后, 本帧所有测高/排版/诊断都只看一个宽度 ⇒ 不再有两套几何。
            //
            // 【为什么不碰 frame/bounds/高度】只写 textContainer.size.width:
            //   不推翻 v41/v45 的 KVO 补高、不推翻 v51 的 frame 钉宽,
            //   也不新增 pass 外的抢宽时机(v13/v34 翻车的形态)。
            //
            // 【为什么不会与 SwiftUI 竞争】这是**纠偏**不是抢宽: 目标宽度是
            //   本帧由 superview 宽算出的权威净宽, 与 layoutSubviews 的
            //   _realW2 同源同值(v43 起两者都是 max(200, cvW-32)); 稳态下
            //   abs<=1 不写 ⇒ 零写入零排版。
            let _v570NetW = max(200.0, cvW - 32)
            let _v570Dirty = abs(self.textContainer.size.width - _v570NetW) > 1
            if _v570Dirty {
                self.textContainer.size.width = _v570NetW
            }
            // [V570-KVODIAG] 纯诊断, 一行几何都不碰。装机后判定:
            //   dirty=1 => 证实「KVO 闭包最前面容器是脏的」= 本版假设成立
            //   dirty=0 => 已是目标宽, 本版无事可做(则病根在别处)
            // 纪律42: 探针必须打在**被修改之前**的状态上, 所以此处用判据
            // 结果 _v570Dirty 表示"是否动过手", 不回读宽度冒充脏值
            // (纠正已发生, 回读恒等于 netW, 那种读数永远"全绿"骗人)。
            do {
                struct _V570Log { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                let _v570Now = CACurrentMediaTime()
                if _v570Now - _V570Log.last > 0.5 {
                    _V570Log.last = _v570Now
                    _V570Log.n &+= 1
                    NSLog("[V570-KVOCW] dirty=%d netW=%.1f svW=%.1f cvW=%.1f len=%d n=%u",
                          _v570Dirty ? 1 : 0, _v570NetW,
                          f.size.width, cvW, self.textStorage.length, _V570Log.n)
                }
            }
            // [V41-KVOPRE] 抢帧器抓到的**原始**值(脏)。见函数 docstring「诊断打穿pass 内 vs pass 后」。"""


def fix_kvo_container_v570(t):
    """v57.0: KVO 早退前纠正 textContainer 宽 —— 治「每行右端被竖直切断」。

    装机日志(minis-2026-10-05 2.log, 5575 行)交叉验证的因果链：

    A. 时间戳证明纠偏**成功**但**晚一拍**（不是"被写回"）：
         01:19:10.524  V44-TEXTFRAME tcW=390.0   <- KVO 闭包内读到脏宽
         01:19:10.526  V50-PINW       tcW=358.0   <- layoutSubviews 内已纠回
         01:19:10.530  V50-LAIDW      laidW=358.0 regrabbed=1
       同一帧 KVO 读 390、layout 读 358 ⇒ 「触发与失败同集合」只能说明
       KVO 那拍看到的是脏宽，**推不出 layoutSubviews 的纠正无效**。
       （这一条推翻了本版最初的假设，是第五次「已识别但没修掉」。）

    B. 真正没人管的那一拍在 KVO 的早退判据：
         let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt
         if !polluted { ...; return }
       三项**全都只看 superview.frame**，而 SwiftUI 推脏的是 textContainer。
       实测 V41-KVOPRE sv=(16.0,188.7,358.0,994.3) ⇒ superview 宽 358 正常
       ⇒ polluted 恒 false ⇒ 每帧早退 ⇒ 脏容器宽从 KVO 路径永远没人纠。
       旁证：V41-KVOFIXH 0 条、LASTSANE 0 条 ⇒ 修正分支一次没进过。

    C. 症状侧（录屏逐帧 1924 帧 + 日志）：
       - 每行右端被**同一条固定竖直线**切断（「跑 PythonShe」后本该是「ll」，
         下一行从断点续排）；静止帧与滑动帧位置完全相同 ⇒ 稳定裁切。
       - V44 的 needH-usedH：tcW=358 时 8.0~8.3（= 内边距，正常），
         tcW=390 时 30.6/52.8/53.0 ⇒ 按 390 排的行碎片留下的空壳。
       - 帧 1280 空白 → 1281「Minis」+loading 圈 → 1282 文字回来
         ⇒ 滑动中同步重排版，文字被清空重画 = 「滑动字消失」的直接来源。

    ★v57.1 追加(装机日志 minis-2026-10-05.log 逐毫秒对齐, 第三次定位)★

    v57.0 把纠偏放在 `if !polluted` 之前, 判据「纠偏行号 < 早退行号」
    **真的通过了**, 但症状一字未改。原因是那个顺序约束**太弱**:
    早退本身就在一帧的中段, 前面还有六条语句。len=297 那一 tick 实测:

        .543 V41-KVOPRE     sv=(16.0,79.7,358.0,297.7)
        .544 V43-WIDTH      dirtyW=390.0 netW=358.0 dh=22.7
        .545 V42-MISS       selfMeasured needH=409.7 tcW=358.0
        .545 V41-KVOHEIGHT  fixed svH=297.7 -> needH=409.7 debt=112.0
        .545 [V45]          v18W=358 kvoW=390 laidW=-1 usedH=258.7 needH=409.7
        .545 V44-TEXTFRAME  tvW=390.0 svW=358.0 tcW=390.0
        .546 V570-KVOCW     dirty=1      <- v57.0 纠偏到这里才跑
        .546 V50-PINW       tcW=358.0    <- 纠偏成功, 但排版已经发生
        .547 V50-LAIDW      laidW=358.0 regrabbed=1

    `usedH=258.7 needH=409.7` 差 151pt(≈6 行) = **落屏用的正是这份按
    390 排的行碎片**。v57.0 把它纠回来了, 但纠正发生在排版**之后**。

    ★同时, dirty=1(41 帧) 与 tcW=390(41 帧) **完全同集合**, dirty=0(12)
    与 tcW=358(12) 完全同集合 ⇒ 纠偏的判据本身是对的、写入也执行了,
    唯一的问题就是**晚了**。这两组读数是 v57.0 唯一被证实的部分。

    ⇒ v57.1: 整块上移到 `guard cvW > 1` 之后、KVO 闭包第一条业务语句。
    """
    if "[V570-KVOCW]" in t:
        return t
    if V571_HEAD_OLD not in t:
        raise RuntimeError(
            "fix_kvo_container_v570: KVO 闭包头部锚点没找到 ——\n"
            "必须是 `guard cvW > 1 else { return }` 紧跟 [V41-KVOPRE] 注释那两行")
    t = t.replace(V571_HEAD_OLD, V571_HEAD_NEW, 1)
    if V570_KVOCW_OLD not in t:
        raise RuntimeError(
            "fix_kvo_container_v570: polluted 早退锚点没找到 ——\n"
            "纠偏整块已插到闭包头部, 但 polluted 判据仍未并入 _v570Dirty")
    return t.replace(V570_KVOCW_OLD, V570_KVOCW_NEW, 1)


def verify_kvo_container_v570(t):
    """v57.1 判据: 八层（v57.0 六层 + 顺序约束升级为三层）。

    1. [V570-KVOCW] 标记在位
    2. **早退判据必须真的把 _v570Dirty 并进去**(整段逐字) —— 只加变量不用同样红
    3. 纠偏必须**双向**(abs>1), 防退回单向 `>`
    4. 必须有纯诊断 [V570-KVODIAG], 且用 dirty 标记而不是回读宽度
    5. 旧的 [V570-BIDIR] 双向化修法必须**已移除**(它证明不了 390 的成因)
    6. 净宽来源必须与 _realW2 同源(max(200.0, cvW-32))
    7. ★v57.1★ 纠偏必须早于 `if !polluted`(Swift 编译期 use-before-declaration)
    8. ★v57.1★ **纠偏必须早于本帧第一次用宽度做决策的三处**：
       V43-WIDTH 声明行 / V42-MISS 的 sizeThatFits 调用行 / V44-TEXTFRAME 行。
       这是 v57.0 漏掉的那一层 —— 它的「纠偏 < 早退」通过了，但纠偏
       实际发生在六条语句之后，排版已经按脏宽发生过一次。
    """
    if "[V570-KVOCW]" not in t:
        raise RuntimeError("verify_kvo_container_v570: 找不到 [V570-KVOCW] 标记")
    need_polluted = ("let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5\n"
                     "                || _hDebt || _v570Dirty")
    if need_polluted not in t:
        raise RuntimeError(
            "verify_kvo_container_v570: polluted 判据没并入 _v570Dirty ——\n"
            "早退分支依然看不到容器脏宽, 本版等于没修。\n"
            "必须是**整段**:\n%s" % need_polluted)
    if "let _v570Dirty = abs(self.textContainer.size.width - _v570NetW) > 1" not in t:
        raise RuntimeError(
            "verify_kvo_container_v570: 双向判据不在位 ——\n"
            "必须是 `abs(self.textContainer.size.width - _v570NetW) > 1`")
    # ★段起点用 _v570NetW 声明（v57.0 独有）：`let _v570Dirty = abs(` 若在
    #   别的版本段出现同形行，全局 find 会取错位置，判据变成假红/假绿。
    i_seg = t.find("let _v570NetW = ")
    i_dirty = t.find("let _v570Dirty = abs(", i_seg, i_seg + 400)
    # ★写入点的搜索窗口必须限定在判据行之后 400 字符内：layoutSubviews 段
    #   里另有一个 `self.textContainer.size.width = ...` 写入点(v49 段),
    #   全局首个匹配会拿错位置，让"顺序错"检查指向错误的写入点
    #   (本版实测踩到，判据自身变成假红/假绿)。
    i_write = t.find("self.textContainer.size.width = _v570NetW", i_dirty, i_dirty + 400)
    # ★锚点必须用 polluted 判据本身, 不能用 `if !polluted {` 全局首个匹配:
    #   ios15ApplyFrameFix(5571) 里另有一段同名的 `if !polluted {`,
    #   全局 find 会命中那一处, 于是"顺序错"的报错指向错误的早退,
    #   判据本身就变成假红(本版实测踩到)。
    i_poll = t.find("|| _hDebt || _v570Dirty", i_dirty)
    if i_dirty == -1 or i_write == -1 or i_poll == -1:
        raise RuntimeError("verify_kvo_container_v570: 纠偏/polluted 锚点缺失")
    # ★方向别写反(本版实测踩过)：Swift 允许先声明后使用, 正常形态是
    #   i_dirty < i_poll。若声明反而晚于 polluted 对它的引用, Swift 编译期
    #   会报 "use of local variable '_v570Dirty' before its declaration" ——
    #   那正是「纠偏整块被挪到早退之后」的真实后果。
    if i_dirty > i_poll:
        raise RuntimeError(
            "verify_kvo_container_v570: _v570Dirty 声明晚于 polluted 的引用 "
            "⇒ Swift 编译期 use-before-declaration")
    i_guard = t.find("if !polluted {", i_poll)
    if i_guard == -1:
        raise RuntimeError("verify_kvo_container_v570: polluted 之后找不到早退分支")
    if i_write > i_guard:
        raise RuntimeError(
            "verify_kvo_container_v570: 顺序错 —— 纠偏必须写在 `if !polluted` "
            "**之前**。写在之后 = 每次都早退, 一次都不会执行。")
    # ★★v57.1 新增第 8 层: 纠偏必须早于「本帧第一次用宽度做决策」的四处 ★★
    # v57.0 只约束了「纠偏 < 早退」, 那条约束**通过了**但太弱 —— 早退在
    # 一帧的中段, 前面还有六条语句, 排版已经按脏宽发生过一次。装机日志
    # (len=297 那一 tick) 证明: usedH=258.7 needH=409.7 差 151pt(≈6 行),
    # 那 151pt 就是落屏用的按 390 排的行碎片。
    # 三处锚点各自的作用:
    #   V43 声明行 —— 它读 _v43DirtyW = textContainer.size.width
    #   V42-MISS    —— 它 sizeThatFits 用 _v42TCW 并刷新闩锁键 latchW
    #   V44         —— 诊断落点, 它读到的 tcW 必须是纠偏**后**的值
    # ★锚点必须用「KVO 闭包第一条业务语句」(_v42Len 声明), 不能只用 V43 ★
    #   判据第一版锚 V43 时, reverse S10 **漏过** —— 把纠偏插在
    #   `let _v42TCW = _v43NetW` 之后、V43 声明之前时, 写入行号只比 V43
    #   早 2 行, `i_write > _i_a` 不成立。但那个位置**仍然是错的**:
    #   V41-KVOPRE 诊断与 _v42Len/_v42Now 声明都还在纠偏之前。
    for _anchor, _why in (
            ("let _v42Len = self.textStorage.length",
             "KVO 闭包第一条业务语句(_v42Len 声明)"),
            ("let _v43DirtyW = self.textContainer.size.width",
             "V43-WIDTH 声明行(它在此读脏宽并算 dh)"),
            ("CGSize(width: _v42TCW, height: .greatestFiniteMagnitude)).height",
             "V42-MISS 的 sizeThatFits 调用行(它用此宽测高并刷新闩锁键)"),
            ("[V44-TEXTFRAME]", "V44-TEXTFRAME 诊断行(它读到的 tcW 必须已纠偏)"),
    ):
        _i_a = t.find(_anchor)
        if _i_a == -1:
            raise RuntimeError(
                "verify_kvo_container_v570: 顺序锚点缺失 —— %s\n"
                "找不到: %s" % (_why, _anchor))
        if i_write > _i_a:
            raise RuntimeError(
                "verify_kvo_container_v570: ★v57.1 顺序错★ 纠偏写在 %s **之后**\n"
                "  纠偏行号 %d > 锚点行号 %d\n"
                "  v57.0 只约束了「纠偏 < 早退」, 那条通过了但太弱: 早退在\n"
                "  一帧的中段, 前面还有六条语句, 排版已按脏宽发生过一次。\n"
                "  装机日志(len=297): usedH=258.7 needH=409.7 差 151pt(≈6 行),\n"
                "  那 151pt 正是落屏用的按 390 排的行碎片。"
                % (_why, i_write, _i_a))
    if "[V570-KVODIAG]" not in t:
        raise RuntimeError("verify_kvo_container_v570: 缺 [V570-KVODIAG] 纯诊断")
    if "[V570-KVOCW] dirty=%d netW=" not in t:
        raise RuntimeError(
            "verify_kvo_container_v570: 诊断必须是 dirty 标记式 ——\n"
            "回读宽度在纠正之后恒等于 netW, 会永远打「全绿」骗人")
    if "[V570-BIDIR]" in t:
        raise RuntimeError(
            "verify_kvo_container_v570: 旧的 [V570-BIDIR] 双向化修法还在 ——\n"
            "它把 `>` 改成 `abs(...)` 后在 tcW=390 上行为与旧判据**完全相同**"
            "(都成立), 证明不了 390 的成因, 留着会掩盖真正的修法")
    # ★净宽来源必须锚定 v57.0 的那处声明 —— `max(200.0, cvW - 32)` 在
    #   ios15ApplyFrameFix 段也出现过, 全局 `in t` 会被别处满足,
    #   于是"净宽取错源"这类错误永远绿(与 reverse_v570.py 的 S4 同一个坑)。
    _kv = t.find("let _v570NetW = ")
    if _kv == -1:
        raise RuntimeError("verify_kvo_container_v570: 缺少 _v570NetW 声明")
    if "max(200.0, cvW - 32)" not in t[_kv:_kv + 60]:
        raise RuntimeError(
            "verify_kvo_container_v570: 净宽不是 max(200.0, cvW-32), "
            "与 _realW2 不同源 ⇒ 又一次拉锯")


# =====================================================================
# v58 —— 纠偏之后必须**重排**, 否则新宽只是"写在容器上", 不会落到行碎片上。
# =====================================================================
V58_ANCHOR_OLD = """            let _v570NetW = max(200.0, cvW - 32)
            let _v570Dirty = abs(self.textContainer.size.width - _v570NetW) > 1
            if _v570Dirty {
                self.textContainer.size.width = _v570NetW
            }
"""

V58_ANCHOR_NEW = """            let _v570NetW = max(200.0, cvW - 32)
            let _v570Dirty = abs(self.textContainer.size.width - _v570NetW) > 1
            if _v570Dirty {
                self.textContainer.size.width = _v570NetW
                // [V58-REFLOW] ★v58 全部修复的支点★ 纠偏后**立刻重排**。
                //
                // 【v57.1 为什么 100% 无效 —— 这次不是"位置"问题, 是"只写不排"】
                // v57.1 把纠偏整块搬到了 KVO 闭包最前, 判据八层全绿,
                // 装机日志里 dirty=1 也确实每帧都在改写宽度 —— **但症状一字未改**。
                // 逐毫秒对齐(minis-2026-10-05 3.log, 04:32:41, len=288):
                //   41.372 V51-FRAMEPIN  fvW=358.0 tcW=358.0 svW=358.0  <- 干净
                //   41.595 V570-KVOCW    dirty=1 netW=358.0               <- 纠偏执行
                //   41.598 V49-WWRITER   kvoW=390.0 laidW=-1.0            <- 读回又是 390
                //   41.599 V44-TEXTFRAME tvW=390.0 svW=358.0 tcW=390.0   <- 落屏那版就是 390
                //   41.599 V41-KVOHEIGHT usedH=258.7 needH=387.0        <- 欠 128.3pt
                // ⇒ **纠偏写进去了, 但同一 tick 再读回来还是 390**。
                //
                // 【机理: 对容器宽做赋值只改容器本身, 不动已排好的行碎片】
                // 这是 v48 自己的注释里已经写明的事实(原文大意: 容器宽赋值
                // = 只改容器不重排既有碎片"), v47/v48/v50/v51 全都靠紧邻的
                // `layoutManager.invalidateLayout(...)` 才真正生效。
                // ★而 v57.1 的纠偏块里**没有那一行 invalidateLayout** ——
                //   它只写了宽度。于是: 容器宽写成 358 ✓, 行碎片仍停在 390 那版,
                //   下一趟布局再读 textContainer 时又按旧碎片走 ⇒ 读回 390。
                // 这是 v47/v48/v50 三代都写了 invalidate 而 v57.1 唯独漏掉的
                // **唯一一个环节** —— 也是三十余版修复反复失败的共同原因:
                // **每版都在"写宽度", 却没人保证"写完的宽度被排版采纳"。**
                //
                // 【为什么必须在这一处(而不是 v18 段)】
                // v18 段的 invalidateLayout 被 `if _ios15WRegrabbed` 包着, 而
                // _ios15WRegrabbed 依赖 `ios15LastLaidOutW`, 装机日志里 laidW
                // **恒为 -1.0** ⇒ 那个 if 的判据在真机上从未成立 ⇒ v47/v48/v50
                // 的重排**全是死代码**。日志实证: V50-LAIDW 只在 layoutSubviews
                // 那趟打成 358, KVO 这趟读到的永远是上一帧的残留 -1。
                // 这里不依赖任何记忆变量, 只看"本帧有没有动过手"(_v570Dirty),
                // 写完就排, 幂等, 稳态零开销。
                //
                // 【为什么用 invalidateLayout(forCharacterRange:) 而不是 ensureLayout】
                // 与 v28 段(第 8835 行)已验证合法的签名完全一致, 不引入
                // 编译器未验证过的 API(纪律 4)。只重排全文行碎片, 不碰高度、
                // 不碰 frame/bounds/origin ⇒ 不推翻 v41/v45/v51 任何成果。
                //
                // 【为什么不会每帧重排 → 不会掉帧加重】
                // 整块被 `if _v570Dirty` 包着。稳态下 tcW 已是 358, abs<=1 ⇒
                // 判据恒 false ⇒ 一次写入、一次重排都没有。只有 SwiftUI 真的
                // 把宽度推回 390 时才动手, 而那正是必须重排的时刻。
                if self.textStorage.length > 0 {
                    layoutManager.invalidateLayout(
                        forCharacterRange: NSMakeRange(0, self.textStorage.length),
                        actualCharacterRange: nil)
                }
            }
            // [V58-REFLOW-DIAG] 纯诊断, 一行几何都不碰。装机判据:
            //   reflow=1 => 本帧纠偏且已重排 = 修复链闭合
            //   reflow=0 => 稳态(容器已是 358), 无需重排
            // 纪律42: 用判据结果表示"是否动过手", 不回读宽度冒充脏值。
            //
            // ★★ 纪律54(本版实测踩到, 由 v49 判据 sab 3/12 拦下) ★★
            // 本块**不得**出现「textContainer 的 .size.height 成员访问」,
            // 连**注释里写出来也不行**。原因: v49 判据的 S7/S8/S12 三条
            // sabotage 都按「该成员访问串的**首个出现处**」做替换, 而本块
            // 位于 v49 探针段**之前**(行 5781 vs 6096)。本块一旦出现那个串
            // (哪怕在注释里), 三条就替换到本块而没落在 v49 探针上
            // ⇒ 变异体不在判据视野内 ⇒ v49 判据失效 ⇒ CI 变红。
            // ★本版真实经过: 首次实现的诊断块真的写了那个成员访问,
            //   于是 CI 报 v49 sab 3/12 未拦截; 把成员访问换成 needH 之后,
            //   **注释里残留的字面量**又让判据继续变红 —— 两次才彻底修干净。
            // ⇒ 纪律: 判据锚点串是**代码级**敏感物质, 注释同样会命中。
            //   高度只打 needH(ios15LastNeededH); 容器实测占用交给 v44。
            do {
                struct _V58Log { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                let _v58Now = CACurrentMediaTime()
                if _v58Now - _V58Log.last > 0.5 {
                    _V58Log.last = _v58Now
                    _V58Log.n &+= 1
                    NSLog("[V58-REFLOW] reflow=%d netW=%.1f tcW=%.1f needH=%.1f len=%d n=%u",
                          _v570Dirty ? 1 : 0, _v570NetW,
                          self.textContainer.size.width,
                          self.ios15LastNeededH, self.textStorage.length,
                          _V58Log.n)
                }
            }
"""


def fix_kvo_reflow_v58(t):
    """v58: 纠偏后强制重排 —— v57.1 的位置已对, 缺的是"写完要排"。

    装机日志(minis-2026-10-05 3.log, 04:32:41, len=288)证明 v57.1 全绿而症状不变:
        41.372 V51-FRAMEPIN  tcW=358.0        <- layoutSubviews 那趟干净
        41.595 V570-KVOCW    dirty=1           <- 纠偏执行了
        41.598 V49-WWRITER   kvoW=390.0       <- 同一 tick 读回还是 390
        41.599 V44-TEXTFRAME tcW=390.0        <- 落屏就是 390 那版
        41.599 V41-KVOHEIGHT usedH=258.7 needH=387.0  欠 128.3pt

    ⇒ v57.1 不是"位置错"(位置确实改对了), 而是**只写宽度不重排**。
    v48 的注释早已写明 `textContainer.size.width = ` 只改容器不重排既有碎片,
    v47/v48/v50 各自紧邻一行 `layoutManager.invalidateLayout(...)` 才生效,
    唯独 v57.1 的纠偏块漏了这一环 ⇒ 容器宽写成 358 但行碎片仍停在 390 那版,
    下一趟布局读回又是 390。这是三十余版反复失败的共同根因。

    ★另一条独立证据★: V50-LAIDW 只在 layoutSubviews 那趟打成 358,
    而 V49-WWRITER 在 KVO 那趟读到的 laidW **恒为 -1.0** ⇒ v47/v48/v50 的
    `if _ios15WRegrabbed` 判据依赖的 `ios15LastLaidOutW` 在真机上从未被赋值,
    那三代重排**全是死代码**。v58 不依赖任何记忆变量, 只看 _v570Dirty。

    只在 `if _v570Dirty` 内动手 ⇒ 稳态零写入零重排, 不加重掉帧。
    """
    if "[V58-REFLOW]" in t:
        return t
    if V58_ANCHOR_OLD not in t:
        raise RuntimeError(
            "fix_kvo_reflow_v58: v57.1 纠偏块锚点没找到 ——\n"
            "必须是 v57.1 的原文形态:\n%s" % V58_ANCHOR_OLD)
    return t.replace(V58_ANCHOR_OLD, V58_ANCHOR_NEW, 1)


def verify_kvo_reflow_v58(t):
    """v58 判据: 六层。

    1. [V58-REFLOW] 标记在位
    2. invalidateLayout 必须**在** `if _v570Dirty {` 块内 —— 写在外面的
       恒重排(掉帧), 写在后面的永不执行(v57.1 的病)
    3. 块内实参必须是全量范围 (0, textStorage.length) + actualCharacterRange: nil
       —— 半截范围排不掉已被切断的行碎片
       (纪律4: 判据里只允许出现编译器已验证存在的 API 与实参形态)
    4. 诊断块必须零副作用(不得写 frame/bounds/height, 连 `+=` 也不行)
    5. ★纪律54★ v58 段**不得**在 v49 探针之前写出 `self.textContainer.size.height`
       —— v49 判据的 S7/S8/S12 三条 sabotage 都按「首个出现处」替换这个串,
       本段位置在 v49 探针之前, 写了就会把那三条的变异体吸走 ⇒ 判据失效
       ⇒ CI 变红(本版真实发生: v49 sab 3/12 未被拦截)。高度只打 needH。
    6. ★纪律55★ 本版**注释**里不得写出「容器宽 + 赋值」的完整字面量
       —— v50 判据用 `re.findall(r"textContainer\\.size\\.width\\s*=", t)`
       全文数写入点, 硬编码期望 5(codeTextView 1 + v18 3 + v57.0 KVO 1),
       **注释同样被计入**。v58 注释里写一次这个字面量, 计数就变 6,
       v50 当场变红(本版真实发生: A' 宽度同源 BAD, 实为 6)。
       ⇒ 本层直接数 V58_ANCHOR_NEW 全文, 必须恰好 1(只有真代码那处)。

    ★★ 第 2~4 层全部走**行级**坐标 ★★
      字符偏移有三个已实测的失效点(由 reverse_v58.py 的 S1/S2/S5 抓到):
        a) 全文搜 invalidateLayout 会先撞上 v58 **注释里**那处说明文字;
        b) 文件别处(v28 段)还有一次合法调用, 摘掉块内那次后会撞上它
           ⇒「块内无重排」被误报成「重排在块外」;
        c) 剥注释后偏移改变, 拿它切原文会切到别处。
      行级对以上三条全部免疫。
    """
    # ---- 6. ★纪律55★ 「容器宽 + 赋值」字面量计数(注释也算) ----
    # ★两处都要数★:
    #   (a) V58_ANCHOR_NEW 常量自身 —— 挡住**注入前**就把字面量写进注释
    #       (写常量时手滑, 编译能过, 但 v50 判据会红);
    #   (b) 产物全文 t —— 挡住**别处**新引入的注释(比如未来某版在 v58 段
    #       之外补一句说明), 以及将来新增的宽度写入点。
    #   ★(b) 期望值是 5★, 与 v50 判据硬编码的那个数字同源 —— 两处必须
    #   一起改, 否则一个绿一个红, 排错时互相指认对方是错的。
    # ★拼接构造, 不在判据源码里留字面量★(纪律54 同一理由)
    _wr = ("textContainer" + r"\.size\.width\s*=")
    import re as _re6
    _n_const = len(_re6.findall(_wr, V58_ANCHOR_NEW))
    if _n_const != 1:
        raise RuntimeError(
            "verify_kvo_reflow_v58: ★纪律55★ V58_ANCHOR_NEW 里"
            "「容器宽赋值」字面量出现 %d 次, 必须恰好 1 次(只有真代码那处)\n"
            "  v50 判据用全文正则数这个字面量并硬编码期望 5, **注释也计入**,\n"
            "  注释里写一次就变 6 ⇒ v50 当场变红(本版真实发生)。\n"
            "  修法: 注释改说「对容器宽做赋值」, 不写完整字面量。" % _n_const)
    _n_prod = len(_re6.findall(_wr, t))
    if _n_prod != 5:
        raise RuntimeError(
            "verify_kvo_reflow_v58: ★纪律55★ 产物里「容器宽赋值」字面量 %d 处, "
            "应为 5(codeTextView 1 + v18 3 + v57.0 KVO 1)\n"
            "  ★注释同样被计入★ —— 在注释里写一次这个字面量就会让 v50 判据变红,\n"
            "  而 v50 判据的报错信息只说「宽度写入点数不对」, 不会告诉你是注释\n"
            "  干的 ⇒ 排错成本极高(本版真实踩了两次)。\n"
            "  若确实新增了写入点: 改代码**并且**同步改 v50 的期望值与本处。" % _n_prod)
    if "[V58-REFLOW]" not in t:
        raise RuntimeError("verify_kvo_reflow_v58: 缺 [V58-REFLOW] 标记")
    if "[V58-REFLOW-DIAG]" not in t:
        raise RuntimeError("verify_kvo_reflow_v58: 缺 [V58-REFLOW-DIAG] 纯诊断")
    if "[V58-REFLOW] reflow=%d netW=" not in t:
        raise RuntimeError(
            "verify_kvo_reflow_v58: 诊断必须是 reflow 标记式 ——\n"
            "回读宽度在纠正之后恒等于 netW, 会永远打「全绿」骗人")

    # ---- 5. ★纪律54: 不得抢 v49 sabotage 锚点的首个出现位置 ----
    # ★判据自身也必须避开那个字面量★: 本函数运行在**注入前**的文本上,
    #   而 v49 判据的 S7/S8/S12 是按「首个出现处」替换 —— 若判据代码里
    #   写出那个串, 它自己就会成为首个出现处, 于是本判据永远判「已写入」
    #   而恒绿。故这里用**拼接**构造锚点, 不在源码里留字面量。
    # ★纪律54 的窗口必须覆盖「v58 段起点 → v49 探针」**整段**★
    #   —— 最初只从 [V58-REFLOW-DIAG] 标记起算固定 2000 字符, 于是写在
    #   标记**之前**的注释(那是最自然的写法)会滑出窗口 ⇒ 漏过。
    #   由 reverse_v58.py 的 S7 实测抓到。
    _probe = ("self.textContainer" + ".size" + ".height")
    _i_v49 = t.find("// [V49-WWRITER-KVO]")
    _i_seg0 = t.find("let _v570NetW = ")
    if _i_v49 == -1:
        raise RuntimeError(
            "verify_kvo_reflow_v58: 找不到 v49 的 KVO 探针段锚点 ——\n"
            "第 5 层判据依赖它做位置比较, 锚点消失说明上游结构变了")
    if _i_seg0 == -1:
        raise RuntimeError("verify_kvo_reflow_v58: 缺少 _v570NetW 声明")
    if _i_seg0 < _i_v49:
        if _probe in t[_i_seg0:_i_v49]:
            raise RuntimeError(
                "verify_kvo_reflow_v58: ★纪律54★ v58 段(位于 v49 探针**之前**)"
                "出现了 textContainer 的 .size.height 成员访问\n"
                "  —— 连**注释里**写出来也不行。\n"
                "  v49 判据的 S7/S8/S12 三条 sabotage 都按该串的**首个出现处**\n"
                "  替换, 本段一旦命中, 那三条就替换到本段而没落在 v49 探针上\n"
                "  ⇒ 变异体不在判据视野内 ⇒ v49 判据失效 ⇒ CI 变红。\n"
                "  修法: 高度只打 needH(ios15LastNeededH), 容器实测占用交给 v44。")

    # ---- 2. invalidateLayout 必须在 _v570Dirty 的 if 块内 ----
    # ★★ 全部用**行级**坐标 ★★
    #   字符偏移有三个已实测的失效点(reverse_v58.py 的 S1/S2/S5):
    #     a) `t.find(INVOKE, i_seg)` 会先撞上 v58 **注释里**那处同名说明文字;
    #     b) 文件别处(v28 段)还有一次合法调用, 删掉块内那次后会撞上它
    #        ⇒ 「块内无重排」被误报成「重排在块外」;
    #     c) 剥注释后偏移改变, 拿它切原文会切到别处。
    #   行级对以上三条全部免疫。
    import re as _re

    def _strip_comments(s):
        return _re.sub(r"//[^\n]*", "",
                       _re.sub(r"/\*.*?\*/", "", s, flags=_re.S))

    _raw_lines = t.split("\n")
    _lines = _strip_comments(t).split("\n")
    if len(_raw_lines) != len(_lines):
        # 剥注释只做行内删除, 行数不该变; 真变了说明有块注释含换行,
        # 此时行级桥不可靠 —— 直接要求上游保持现状, 不猜。
        raise RuntimeError(
            "verify_kvo_reflow_v58: 剥注释后行数变了(%d → %d) —— "
            "行级定位的前置条件被破坏, 请检查 v58 段是否引入了跨行块注释"
            % (len(_raw_lines), len(_lines)))

    _i_blk = _i_inv = _i_end = -1
    for _k, _ln in enumerate(_lines):
        if _ln.strip() == "if _v570Dirty {":
            _i_blk = _k
            break
    if _i_blk < 0:
        raise RuntimeError(
            "verify_kvo_reflow_v58: 找不到 `if _v570Dirty {`\n"
            "  ★必须**整行等于**该串 —— 子串匹配会放过 `if _v570Dirty && x`"
            "这种把纠偏与别的条件绑在一起的写法(块边界随即不再是它)")
    _indent = _lines[_i_blk][:len(_lines[_i_blk]) - len(_lines[_i_blk].lstrip())]
    for _k in range(_i_blk + 1, len(_lines)):
        # ★按**行首缩进**收尾(纪律53)★ —— 按文本找收尾会被注释里出现的
        #   `}` 误导, 也会被多余 `{` 带偏 ⇒ 判据假绿。
        if _lines[_k].startswith(_indent + "}"):
            _i_end = _k
            break
    if _i_end < 0:
        raise RuntimeError(
            "verify_kvo_reflow_v58: 找不到 `_v570Dirty` 块的收尾(按缩进 %r 找)"
            % _indent)
    for _k in range(_i_blk, _i_end + 1):
        if "layoutManager.invalidateLayout(" in _lines[_k]:
            _i_inv = _k
            break

    if _i_inv < 0:
        # 区分「本来就没写(F1=v57.1 的病)」与「写到块外去了(F2/F3)」
        _elsewhere = any("layoutManager.invalidateLayout(" in _l
                         for _l in _lines[_i_end + 1:_i_end + 400])
        if _elsewhere:
            raise RuntimeError(
                "verify_kvo_reflow_v58: ★F2/F3★ invalidateLayout 不在 "
                "`if _v570Dirty {` 块内\n"
                "  块外 = 每帧全量重排(稳态也排) ⇒ 掉帧;\n"
                "  块后 = 纠偏时还没排, 排版仍停在旧宽 ⇒ 与 v57.1 等价。")
        raise RuntimeError(
            "verify_kvo_reflow_v58: ★F1★ 纠偏块里没有 invalidateLayout ——\n"
            "这正是 v57.1 的病: 只写 textContainer.size.width 而不重排,\n"
            "容器宽改了但行碎片仍停在 390 那版, 下一趟读回又是 390。\n"
            "  装机日志实证(04:32 段): 41.595 dirty=1 netW=358.0 纠偏执行了,\n"
            "  41.598 kvoW=390.0 同一 tick 读回还是 390, needH 欠 128.3pt。")

    # ---- 3. 实参必须是全量范围(与 v28 段已验证的形式一致) ----
    # ★纪律4: 判据里只允许出现编译器已验证存在的 API 与实参形态★
    _seg_inv = "\n".join(_lines[_i_inv:_i_end + 1])
    if not _re.search(r"forCharacterRange:\s*NSMakeRange\(0,\s*"
                      r"self\.textStorage\.length\),\s*"
                      r"actualCharacterRange:\s*nil\)", _seg_inv):
        raise RuntimeError(
            "verify_kvo_reflow_v58: 块内 invalidateLayout 的实参不是全量范围\n"
            "  必须是 (0, textStorage.length) + actualCharacterRange: nil ——\n"
            "  半截范围排不掉已被切断的行碎片(等于没排)。\n"
            "  该签名与 v28 段的已验证调用逐字一致。")

    # ---- 4. 不得引入额外几何写入(只许宽 + 节流器状态) ----
    # ★切片到**日志点**为止, 不是到 [V58-REFLOW-DIAG] 标记★ —— 后者在块首
    #   注释里、位置在 `do {` 之前, 拿它当上界会切出空段(诊断块整块漏检)。
    # ★先定 do {, 再从它往后找日志点★ —— 反过来写(先扫日志点)会在遇到
    #   `do {` 时提前 break, 留下 _i_log 还是**字符偏移**当行号用,
    #   于是切片越过整个诊断块一路吃到 v57.0 的诊断段(本版实测:
    #   报 "_V570Log.last 非白名单写入", 而那段根本不在 v58 范围内)。
    _i_do = -1
    for _k in range(_i_end + 1, len(_lines)):
        if "do {" in _lines[_k]:
            _i_do = _k
            break
    _i_log = -1
    for _k in range(_i_do + 1, len(_lines)):
        if 'NSLog("[V58-REFLOW]' in _lines[_k]:
            _i_log = _k
            break
    if _i_do < 0 or _i_log < 0:
        raise RuntimeError(
            "verify_kvo_reflow_v58: 诊断块结构异常(do@%s, 日志@%s) —— "
            "找不到纠偏块之后、包裹诊断的 do { 或其内的日志点"
            % (_i_do, _i_log))
    for _ln in _lines[_i_do:_i_log + 1]:
        # ★必须连**复合赋值**一起拦★ —— 只匹配裸 `=` 时
        #   `self.frame.size.height += x` 会整条溜过去(reverse_v58.py S6 实测)。
        _m = _re.match(r"\s*([\w.]+)\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)", _ln)
        if not _m:
            continue
        _lhs = _m.group(1)
        # ★白名单**逐条列举**, 不用 endswith('.width'/'.height')** ——
        #   那等于放行一切「对 .height/.width 的赋值」, 于是
        #   `self.frame.size.height += x` 这类最该拦的写法会溜过去。
        if _lhs == "self.textContainer.size.width":
            continue
        # v58 段自己的节流器状态(struct _V58Log)。
        # ★不放行 _V570Log★ —— 切片已精确到 v58 段内, v57.0 的诊断段
        #   根本不该出现在这里; 放行它等于给「切片越界」留后门。
        if _lhs.startswith("_V58Log."):
            continue
        raise RuntimeError(
            "verify_kvo_reflow_v58: v58 诊断块内出现非白名单写入 `%s`(行: %s)\n"
            "  诊断必须零副作用; 就算它不是诊断, 碰 frame/bounds/height 也会\n"
            "  推翻 v41/v45/v51 的成果。" % (_lhs, _ln.strip()))



# ============================================================
# v59: 关闭 SelectableMarkdownTextView 的容器宽跟随
#      (widthTracksTextView) —— v31~v58 全部改动的天花板
# ============================================================
# 【机理(装机日志 v57.1, 04:32 段实证)】
#   上游在 SelectableMarkdownTextView.init() 里设 widthTracksTextView=true,
#   意思是「每趟布局, UIKit 从 frame 派生容器宽并覆盖之」。
#   superview 宽 358(SwiftUI inset 16/16 已生效), 但本视图 frame 被上游
#   布局撑到 390 ⇒ 派生容器宽 = 390 ⇒ 我们写的 358 每趟都被顶回。
#   41.595 写入 358 → 41.598(3ms 后)读回 390 —— 「改了等于没改」的机制。
# 【为什么不早改】v9/v9.1/v10 曾试图在容器层面(setSize swizzle)对抗,
#   结果 44131 次死循环 + 508 次 10s 卡死; Guard 注释的结论是
#   「要修就修产生它的源头」。关掉派生就是断源, 不是又一层对抗。
# 【关掉之后谁管宽】v18 渲染段 + v57.0 KVO 纠偏(netW=cvW-32, 干净源);
#   旋转/resize 后 KVO 亦会重写。v58 的重排随之真正生效。
# 【范围红线】TableScrollView 的内联代码 TextView(表格用, frame 干净)
#   保持 true —— 它不是病灶。两处 true 在上游逐字相同, 锚点靠
#   super.init + isEditable 区分(仅 SelectableMarkdownTextView 有)。

V59_ANCHOR_OLD = """        textContainer.widthTracksTextView = true
        layoutManager.addTextContainer(textContainer)
        textStorage.addLayoutManager(layoutManager)

        super.init(frame: .zero, textContainer: textContainer)

        isEditable = false"""

V59_ANCHOR_NEW = """        textContainer.widthTracksTextView = false
        // [V59-NOTRACK] ★v59 关闭容器宽跟随★ 上游默认 true = 每趟布局从
        // frame 派生并覆盖容器宽。装机日志(v57.1, 04:32 段)实证: superview
        // 宽 358(SwiftUI inset 16/16 已生效), 但本视图 frame 被上游布局撑到
        // 390 => 派生容器宽 = 390 => v31~v58 每一版写入的净宽都在下一趟布局
        // 被系统覆盖回 390(41.595 写 358 -> 41.598 读回 390) —— 这就是
        // 「改了等于没改」的机制。关掉跟随后, 容器宽由 v18 渲染段与 v57.0 KVO
        // 纠偏(netW = cvW - 32, 来自 collectionView 干净源)独占维护, v58 的
        // invalidateLayout 重排随之生效。旋转/resize 后 KVO 亦会重写。
        // 首帧兜底: NSTextContainer 默认 1e7 x 1e7(项目日志里的 1e7 污染值
        // 就是它), 关掉跟随后的首趟排版会按 1e7 排成一行超长 —— 压一个
        // 保守初值, KVO 纠偏一跑就以真实净宽覆盖。SetSizeGuard 仍兜底风暴。
        textContainer.size = CGSize(width: 320, height: 2000)
        layoutManager.addTextContainer(textContainer)
        textStorage.addLayoutManager(layoutManager)

        super.init(frame: .zero, textContainer: textContainer)

        isEditable = false"""


def fix_md_notrack_v59(t):
    """v59 注入: 只改 SelectableMarkdownTextView.init() 那一处。

    幂等: 产物里已有 [V59-NOTRACK] 时原样返回。
    锚点失配时**报错**而不是静默跳过 —— 上游若改了 init 结构, 静默跳过
    会让「看似修复实则没进包」的历史重演(v31~v58 最大的教训)。
    """
    if "[V59-NOTRACK]" in t:
        return t
    if V59_ANCHOR_OLD not in t:
        raise RuntimeError(
            "fix_md_notrack_v59: SelectableMarkdownTextView.init() 的锚点没找到 ——\n"
            "  期望(上游原文):\n%s\n"
            "  上游可能改了 init() 结构; 也有可能锚点撞上了 TableScrollView 的"
            "convenience init —— 两处 true 逐字相同, 锚点必须靠 super.init + "
            "isEditable 区分。" % V59_ANCHOR_OLD)
    # 防呆: 若上游出现第二处同形 init(两个都在), 只允许替换一次
    n = t.count(V59_ANCHOR_OLD)
    if n != 1:
        raise RuntimeError(
            "fix_md_notrack_v59: 锚点出现 %d 次(应为 1) —— "
            "上游出现了第二处 SelectableMarkdownTextView 同形 init, "
            "需要人工确认改哪处。" % n)
    return t.replace(V59_ANCHOR_OLD, V59_ANCHOR_NEW, 1)


def verify_md_notrack_v59(t):
    """v59 判据: 五层。

    1. [V59-NOTRACK] 标记在位
    2. 标记所在段必须真的是 SelectableMarkdownTextView.init()
       (其后紧跟 isEditable = false —— 这是该 init 的指纹,
        TableScrollView 的 convenience init 没有这一段)
    3. 首帧兜底在位(容器初值 320, 不是 1e7 —— 否则首趟排版排成一行超长)
    4. 全文件 widthTracksTextView = true 恰好 1 处(TableScrollView 保留)。
       ★这一层同时是范围红线: 0 处 = 顺手把表格那处也改了 = 范围失控(v56.6 纪律)
    5. 全文件 widthTracksTextView = false 恰好 2 处(codeTextView 的 v4 +
       本版)。0 处 = 注入没生效; >2 = 有人在别处也关了, 需要登记。
    """
    if "[V59-NOTRACK]" not in t:
        raise RuntimeError("verify_md_notrack_v59: 缺 [V59-NOTRACK] 标记")

    i = t.find("[V59-NOTRACK]")
    tail = t[i:i + 3000]
    if "isEditable = false" not in tail:
        raise RuntimeError(
            "verify_md_notrack_v59: 标记之后 3000 字符内没有 isEditable = false ——\n"
            "  [V59-NOTRACK] 不在 SelectableMarkdownTextView.init() 里。\n"
            "  这正是 v46「探针装错类」的形态: 标记在、判据绿、测的全是别的东西。")
    if "textContainer.size = CGSize(width: 320" not in tail:
        raise RuntimeError(
            "verify_md_notrack_v59: 缺首帧兜底(容器初值 320) ——\n"
            "  NSTextContainer 默认 1e7 x 1e7, 关掉跟随后的首趟排版会按 1e7\n"
            "  排成一行超长(项目日志里的 1e7 污染值就是它)。")
    n_true = t.count("widthTracksTextView = true")
    if n_true != 1:
        raise RuntimeError(
            "verify_md_notrack_v59: 全文件「跟随宽」出现 %d 处, 应为 1 处 ——\n"
            "  TableScrollView 的内联代码 TextView(表格用, frame 干净)必须保持 true。\n"
            "  0 处 = 顺手把表格那处也改了 = 范围失控(v56.6 纪律);\n"
            "  >1 处 = 上游加了新视图, 需要逐个确认是不是病灶再登记。" % n_true)
    n_false = t.count("widthTracksTextView = false")
    if n_false != 2:
        raise RuntimeError(
            "verify_md_notrack_v59: 全文件「关闭跟随」出现 %d 处, 应为 2 处 ——\n"
            "  codeTextView 的 v4 断言(防代码块 setSize 风暴) + 本版主视图。\n"
            "  1 处 = 注入没生效; >2 处 = 别处新关了跟随但没登记, 风险未知。" % n_false)


# ============================================================
# v60: 采用 zhaoxiufei/OpenMinis 3ccdff6 已验证方案 —— 取代 v59
# ============================================================
# 【出处与验证状态】zhaoxiufei/OpenMinis(非 fork, 基于上游的 iOS 15.8.8
#   移植)提交 3ccdff6 "fix: resolve markdown rendering collapse and add
#   iOS 15 hosting sizing"。该作者已发布可装的 IPA, 用户提供的截图实证
#   其包在 iOS 15.1.1 / 15.4.1 真机上聊天渲染无卡字 —— 这是本项目
#   v31~v59 一直没有的「真机已验证」。
# 【哲学差异】v31~v59 全部在「容器宽」层面与系统对抗(写 358 → 被跟随
#   派生顶回 390, 改了等于没改)。zhaoxiufei 反其道: **保留
#   widthTracksTextView=true(上游默认)**, 通过
#     ① hosting 层 sizeThatFits 重写(本文件 fix_zhao_compat_v60)
#     ② TextView 的 sizeThatFits/intrinsicContentSize 重写
#        (sane 宽推导链: 实参→容器宽→bounds→屏宽-32; 漂移>0.5 即重置)
#     ③ init/makeUIView/updateUIView 三处 sane 宽兜底
#     ④ CodeBlockAttachment 三级 fallback + 最小 50 兜底
#   —— 保证 frame 永远 sane, 宽跟随自然得到 sane 宽。
#   v59 的「断源」(false + 兜底 320)整体退场: v59 的 edit 注册已被本版
#   取代, 产物回到上游 init 形态后由本版注入。
# 【与既有补丁链的关系】v57.0 KVO 纠偏/v58 重排保留 —— frame 恒 sane
#   的新世界里它们退化为观察者(读到 sane 宽即不写), 方向一致不打架。
# ============================================================

_V60_TRUE = "textContainer.widthTracksTextView = true"
_V60_FALSE = "widthTracksTextView = false"

# init 锚点 = 上游原文(v59 退场后产物即此形态); super.init + isEditable
# 用于与 TableScrollView 的 TableCellTextView.init 区分(两处 true 逐字同)。
V60_INIT_OLD = """        textContainer.widthTracksTextView = true
        layoutManager.addTextContainer(textContainer)
        textStorage.addLayoutManager(layoutManager)

        super.init(frame: .zero, textContainer: textContainer)

        isEditable = false"""

V60_INIT_NEW = """        textContainer.widthTracksTextView = true
        // [V60-ZHAO-INIT] 采用 zhaoxiufei/OpenMinis 3ccdff6 已验证方案:
        // 保留宽跟随, 但压 sane 初值 —— NSTextContainer 默认 1e7 x 1e7,
        // 首趟排版会按 1e7 排成一行超长(历史装机日志里的 1e7 污染宽就是它)。
        // 初值屏宽-32 与真实净宽一致, 首帧即 sane。
        let defaultWidth = UIScreen.main.bounds.width - 32
        textContainer.size = CGSize(width: defaultWidth, height: .greatestFiniteMagnitude)
        layoutManager.addTextContainer(textContainer)
        textStorage.addLayoutManager(layoutManager)

        super.init(frame: .zero, textContainer: textContainer)

        isEditable = false"""

# v21 注入的 intrinsicContentSize 钳宽块(v60 运行时它在产物里, 精确文本)。
# 替换理由: 旧版依赖 super.intrinsicContentSize —— 容器宽 1e5 时它先按
# 1e5 排版再钳(白排一次), 且对外仍报一个"理想宽"参与 SwiftUI 协商 =
# 污染残留通道。新版宽彻底不参与(noIntrinsicMetric), 高度按 sane 宽现算。
V60_V21_OLD = """    override var intrinsicContentSize: CGSize {
        let sz = super.intrinsicContentSize
        let cvW = findCollectionView()?.bounds.width ?? 0
        let cap = cvW > 33 ? cvW - 32 : sz.width
        let w = (cap > 1 && sz.width > cap) ? cap : sz.width
        return CGSize(width: w, height: sz.height)
    }"""

V60_FIT_NEW = """    // [V60-ZHAO-FIT] 采用 zhaoxiufei/OpenMinis 3ccdff6 已验证方案
    // (替换 v21 钳宽版 intrinsic —— 见上)。sizeThatFits 的 sane 宽推导链:
    // 实参 → 容器宽 → bounds → 屏宽-32, 任何一级 sane 就用; 容器宽偏离
    // 推导宽超过半点即重置 —— 宽跟随保留, 但 frame 恒 sane, 跟随派生
    // 不再产出 390/1e5 污染宽。逐字对齐他们的真机验证版。
    override func sizeThatFits(_ size: CGSize) -> CGSize {
        let width = size.width > 1 && size.width < 100_000 ? size.width : (textContainer.size.width > 1 && textContainer.size.width < 100_000 ? textContainer.size.width : (bounds.width > 1 ? bounds.width : UIScreen.main.bounds.width - 32))
        guard textStorage.length > 0 else {
            return super.sizeThatFits(CGSize(width: width, height: size.height > 0 ? size.height : 4))
        }
        let oldWidth = textContainer.size.width
        let oldHeight = textContainer.size.height
        if abs(textContainer.size.width - width) > 0.5 {
            textContainer.size = CGSize(width: width, height: .greatestFiniteMagnitude)
        }
        let fit = super.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        if oldHeight < .greatestFiniteMagnitude {
            textContainer.size.height = oldHeight
        }
        return CGSize(width: width, height: ceil(fit.height))
    }

    override var intrinsicContentSize: CGSize {
        let width = textContainer.size.width > 1 && textContainer.size.width < 100_000 ? textContainer.size.width : (bounds.width > 1 ? bounds.width : UIScreen.main.bounds.width - 32)
        guard width > 1, textStorage.length > 0 else {
            return CGSize(width: UIView.noIntrinsicMetric, height: UIView.noIntrinsicMetric)
        }
        let fit = sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: UIView.noIntrinsicMetric, height: ceil(fit.height))
    }"""

# CodeBlockAttachment.attachmentBounds 头部(签名+裸宽行+topOffset 行,
# 上游 1.13/1.14 一致; 该签名全文件 5 处, 本组合唯一)。
V60_CB_HEAD_OLD = """    override func attachmentBounds(for textContainer: NSTextContainer?, proposedLineFragment lineFrag: CGRect, glyphPosition position: CGPoint, characterIndex charIndex: Int) -> CGRect {
        let width = lineFrag.width
        let topOffset: CGFloat = (language != nil && !language!.isEmpty) ? 28 : 12"""

V60_CB_HEAD_NEW = """    override func attachmentBounds(for textContainer: NSTextContainer?, proposedLineFragment lineFrag: CGRect, glyphPosition position: CGPoint, characterIndex charIndex: Int) -> CGRect {
        // [V60-ZHAO-CB] 代码块宽三级 fallback(zhaoxiufei 3ccdff6 同款):
        // lineFrag 垃圾宽(0 或 1e5+)时退到容器宽, 再退到屏宽-32,
        // 代码块不再按垃圾宽量高 → 末行裁断/大空白随之消失。
        let containerWidth = textContainer?.size.width ?? 0
        let effectiveWidth: CGFloat
        if lineFrag.width > 0 && lineFrag.width < 100_000 {
            effectiveWidth = lineFrag.width
        } else if containerWidth > 0 && containerWidth < 100_000 {
            effectiveWidth = containerWidth
        } else {
            effectiveWidth = UIScreen.main.bounds.width - 32
        }
        let topOffset: CGFloat = (language != nil && !language!.isEmpty) ? 28 : 12"""

V60_CB_RET_OLD = "        return CGRect(x: 0, y: 0, width: width, height: height)"
V60_CB_RET_NEW = "        return CGRect(x: 0, y: 0, width: effectiveWidth, height: height)"

# v565 诊断段的实参引用 —— attachmentBounds 里 `let width` 被本版替换后,
# 诊断段的 `Double(width)` 会悬空(CI 152 编译错误 1575:30 cannot find
# 'width' in scope)。effectiveWidth 就是本函数最终采用的宽, 语义更准。
# 锚点用「Double(width), Double(attV565ViewH)」组合, 全文件唯一。
V60_V565_ARG_OLD = "Double(width), Double(attV565ViewH), Double(attV565ViewW),"
V60_V565_ARG_NEW = "Double(effectiveWidth), Double(attV565ViewH), Double(attV565ViewW),"

V60_MV_OLD = """        let inset = leftInset
        let contentWidth = width - inset"""

V60_MV_NEW = """        // [V60-ZHAO-CB] 实参宽 sane 化 + 最小 50 兜底(zhaoxiufei 3ccdff6 同款)
        let usableWidth = width > 0 && width < 100_000 ? width : (UIScreen.main.bounds.width - 32)
        let inset = leftInset
        let contentWidth = max(usableWidth - inset, 50)"""

V60_SC_OLD = "        let newScrollFrame = CGRect(x: 0, y: topOffset, width: container.frame.width, height: scrollHeight + bottomPadding)"

V60_SC_NEW = """        // [V60-ZHAO-CB] 流式增高时容器宽最小 50 兜底(zhaoxiufei 3ccdff6 同款)
        let scrollWidth = max(container.frame.width, 50)
        let newScrollFrame = CGRect(x: 0, y: topOffset, width: scrollWidth, height: scrollHeight + bottomPadding)"""

V60_MK_OLD = """        textView.setContentHuggingPriority(.required, for: .vertical)
        textView.setContentCompressionResistancePriority(.required, for: .vertical)
        context.coordinator.lastMarkdown = \"\""""

V60_MK_NEW = """        textView.setContentHuggingPriority(.required, for: .vertical)
        textView.setContentCompressionResistancePriority(.required, for: .vertical)
        // [V60-ZHAO-MAKE] 初建即 sane(zhaoxiufei 3ccdff6 同款):
        // SwiftUI 首趟布局问尺寸时容器宽已是净宽, 不再从 1e7 初值起步。
        let defaultWidth = UIScreen.main.bounds.width - 32
        textView.textContainer.size = CGSize(width: defaultWidth, height: .greatestFiniteMagnitude)
        context.coordinator.lastMarkdown = \"\""""

V60_UP_OLD = """        let currentFontSize = FontSettings.shared.scaledMessage(16.5)
        let fontChanged = context.coordinator.lastFontSize != currentFontSize"""

V60_UP_NEW = """        let currentFontSize = FontSettings.shared.scaledMessage(16.5)
        let fontChanged = context.coordinator.lastFontSize != currentFontSize

        // [V60-ZHAO-UPD] 每次更新前容器宽 sane 兜底(zhaoxiufei 3ccdff6 同款):
        // 上一趟若有任何路径把容器宽写成垃圾值(<=1 或 >=100_000),
        // 在本轮排版前用 bounds/屏宽-32 拉回, 不让垃圾宽进排版。
        if textView.textContainer.size.width <= 1 || textView.textContainer.size.width >= 100_000 {
            let fallbackW = textView.bounds.width > 1 && textView.bounds.width < 100_000 ? textView.bounds.width : (UIScreen.main.bounds.width - 32)
            textView.textContainer.size = CGSize(width: fallbackW, height: .greatestFiniteMagnitude)
        }"""

# iOS15Compat.swift: 在 isMeasuring 声明前插 hosting sizeThatFits 重写。
# 我们已有两个 systemLayoutSizeFitting 重写(ios15FittingSize, 更精细:
# 压缩哨兵拦截 + v17 钳宽 + 历史好值兜底), 不重复加; 缺的是 sizeThatFits
# 这条不经过布局引擎的路径 —— 父视图走它时我们报的是垃圾理想宽。
V60_HOST_OLD = "    private var isMeasuring: Bool = false"

V60_HOST_NEW = """    // [V60-ZHAO-HOST] 采用 zhaoxiufei/OpenMinis 3ccdff6 已验证方案:
    // SwiftUI hosting 层直接尺寸协商入口 —— 父视图走 sizeThatFits 路径
    // (不经过 systemLayoutSizeFitting)时也按传入真实宽向 SwiftUI 要高度,
    // 并 ceil 对齐像素。测量宽 == 渲染宽 → 高度不再错位。
    override func sizeThatFits(_ size: CGSize) -> CGSize {
        guard let host = host else { return super.sizeThatFits(size) }
        let width = size.width > 0 ? size.width : (bounds.width > 0 ? bounds.width : UIScreen.main.bounds.width)
        let fitSize: CGSize
        if #available(iOS 16.0, *) {
            fitSize = host.sizeThatFits(in: CGSize(width: width, height: .greatestFiniteMagnitude))
        } else {
            fitSize = host.view.sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        }
        return CGSize(width: width, height: ceil(fitSize.height))
    }

    private var isMeasuring: Bool = false"""


def _v60_replace1(t, old, new, what):
    """单锚点替换: 计数必须恰好 1, 失配报错(不静默跳过)。"""
    n = t.count(old)
    if n != 1:
        raise RuntimeError(
            "fix_zhao_md_v60: %s 锚点出现 %d 次(应为 1) ——\n"
            "  上游/前版补丁结构可能变了, 人工确认后再动。\n"
            "  锚点开头: %s" % (what, n, old.split(chr(10))[0][:80]))
    return t.replace(old, new, 1)


def fix_zhao_md_v60(t):
    """v60 注入: SelectableMarkdownView.swift 九处(zhaoxiufei 3ccdff6 同款
    + v565 诊断段悬空引用适配)。

    幂等: 产物里已有 [V60-ZHAO-INIT] 时原样返回。
    每个子注入独立锚点 + 计数==1 防呆; 失配**报错**而不是静默跳过
    (v31~v58 最大的教训: 静默跳过 = 看似修复实则没进包)。
    """
    if "[V60-ZHAO-INIT]" in t:
        return t
    t = _v60_replace1(t, V60_INIT_OLD, V60_INIT_NEW, "init sane 初值")
    t = _v60_replace1(t, V60_V21_OLD, V60_FIT_NEW, "intrinsic 替换+sizeThatFits")
    t = _v60_replace1(t, V60_CB_HEAD_OLD, V60_CB_HEAD_NEW, "CB attachmentBounds 头")
    t = _v60_replace1(t, V60_CB_RET_OLD, V60_CB_RET_NEW, "CB return effectiveWidth")
    t = _v60_replace1(t, V60_V565_ARG_OLD, V60_V565_ARG_NEW, "v565 诊断段悬空 width 引用")
    t = _v60_replace1(t, V60_MV_OLD, V60_MV_NEW, "CB makeView usableWidth")
    t = _v60_replace1(t, V60_SC_OLD, V60_SC_NEW, "CB scrollWidth 兜底")
    t = _v60_replace1(t, V60_MK_OLD, V60_MK_NEW, "makeUIView 初值")
    t = _v60_replace1(t, V60_UP_OLD, V60_UP_NEW, "updateUIView 兜底")
    return t


def verify_zhao_md_v60(t):
    """v60 判据: 七层(SelectableMarkdownView.swift)。

    L1 init 标记 + sane 初值窗口
    L2 sizeThatFits/intrinsic 重写块窗口(sane 推导链 + 漂移重置 + noIntrinsic)
    L3 intrinsic 恰好 1 处 override; v21 旧版特征清零
    L4 makeUIView/updateUIView 兜底在位
    L5 v59 退场核账: 跟随宽 2 / 关闭跟随 1 / v59 标记 0
    L6 CodeBlock 三处(effectiveWidth / usableWidth / scrollWidth)
    L7 值域纪律: 垃圾宽拦截阈值必须是 100_000(S7 改 1e9 即红)
    """
    # L1
    if t.count("[V60-ZHAO-INIT]") != 1:
        raise RuntimeError("verify_zhao_md_v60 L1: 缺 [V60-ZHAO-INIT](应恰 1)")
    i = t.find("[V60-ZHAO-INIT]")
    tail = t[i:i + 600]
    if "defaultWidth" not in tail or ".greatestFiniteMagnitude" not in tail:
        raise RuntimeError("verify_zhao_md_v60 L1: init 窗口缺 sane 初值两行")
    # L2
    if t.count("[V60-ZHAO-FIT]") != 1:
        raise RuntimeError("verify_zhao_md_v60 L2: 缺 [V60-ZHAO-FIT](应恰 1)")
    i = t.find("[V60-ZHAO-FIT]")
    tail = t[i:i + 3500]
    if "override func sizeThatFits(_ size: CGSize) -> CGSize" not in tail:
        raise RuntimeError("verify_zhao_md_v60 L2: 窗口内无 sizeThatFits 重写")
    if "override var intrinsicContentSize" not in tail:
        raise RuntimeError("verify_zhao_md_v60 L2: 窗口内无 intrinsicContentSize 重写")
    if "size.width > 1 && size.width < 100_000" not in tail:
        raise RuntimeError("verify_zhao_md_v60 L2: 推导链缺垃圾宽拦截(100_000)")
    if "> 0.5 {" not in tail:
        raise RuntimeError("verify_zhao_md_v60 L2: 缺漂移重置(>0.5)分支")
    if "ceil(fit.height)" not in tail:
        raise RuntimeError("verify_zhao_md_v60 L2: 缺 ceil 高度对齐")
    if "noIntrinsicMetric" not in tail:
        raise RuntimeError("verify_zhao_md_v60 L2: 宽未退出协商(noIntrinsicMetric)")
    # L3
    n_intr = t.count("override var intrinsicContentSize")
    if n_intr != 1:
        raise RuntimeError(
            "verify_zhao_md_v60 L3: intrinsicContentSize override 出现 %d 处"
            "(应为 1) —— v21 旧版没被替换干净会重复声明编译失败" % n_intr)
    if "let sz = super.intrinsicContentSize" in t:
        raise RuntimeError(
            "verify_zhao_md_v60 L3: v21 旧版特征仍在(super.intrinsicContentSize "
            "先按 1e5 排版再钳) —— 替换没生效")
    if t.count("noIntrinsicMetric") < 2:
        raise RuntimeError("verify_zhao_md_v60 L3: noIntrinsicMetric 应 ≥2(宽+高)")
    # L4
    if t.count("[V60-ZHAO-MAKE]") != 1:
        raise RuntimeError("verify_zhao_md_v60 L4: 缺 [V60-ZHAO-MAKE]")
    if t.count("[V60-ZHAO-UPD]") != 1:
        raise RuntimeError("verify_zhao_md_v60 L4: 缺 [V60-ZHAO-UPD]")
    i = t.find("[V60-ZHAO-UPD]")
    if "fallbackW" not in t[i:i + 500]:
        raise RuntimeError("verify_zhao_md_v60 L4: updateUIView 兜底体缺失")
    # L5
    n_true = t.count(_V60_TRUE)
    n_false = t.count(_V60_FALSE)
    if n_true != 2:
        raise RuntimeError(
            "verify_zhao_md_v60 L5: 跟随宽 %d 处(应为 2: init+表格) ——\n"
            "  0/1 = v59 残魂或 init 没恢复 true; >2 = 上游新增视图未登记" % n_true)
    if n_false != 1:
        raise RuntimeError(
            "verify_zhao_md_v60 L5: 关闭跟随 %d 处(应为 1: codeTextView v4) ——\n"
            "  >1 = v59 断源残魂(主视图 false 会退化回 v31~v58 的对抗态)" % n_false)
    if "[V59-NOTRACK]" in t:
        raise RuntimeError(
            "verify_zhao_md_v60 L5: [V59-NOTRACK] 仍在 —— v59 必须整体退场,"
            " 不能与 v60 的宽跟随方案并存(容器宽会两个主子抢写)")
    # L6
    if t.count("[V60-ZHAO-CB]") != 3:
        raise RuntimeError(
            "verify_zhao_md_v60 L6: [V60-ZHAO-CB] 应恰 3 处(attachmentBounds/"
            "makeView/scrollWidth), 实测 %d" % t.count("[V60-ZHAO-CB]"))
    if t.count("width: effectiveWidth") != 1:
        raise RuntimeError("verify_zhao_md_v60 L6: CB return 未改 effectiveWidth")
    if "max(usableWidth - inset, 50)" not in t:
        raise RuntimeError("verify_zhao_md_v60 L6: makeView 缺 min-50 兜底")
    if "max(container.frame.width, 50)" not in t:
        raise RuntimeError("verify_zhao_md_v60 L6: scrollWidth 缺 min-50 兜底")
    # L7
    if "lineFrag.width < 100_000" not in t:
        raise RuntimeError("verify_zhao_md_v60 L7: CB 三级 fallback 阈值被动过")
    # L8 悬空引用清零(CI 152 编译错误 1575:30 的回归防线):
    #    attachmentBounds 里 let width 已被本版删除, 任何残余的裸
    #    `Double(width),` 引用 = 编译失败。
    if "Double(width)," in t:
        raise RuntimeError(
            "verify_zhao_md_v60 L8: v565 诊断段仍引用已删除的 width 变量"
            "(cannot find 'width' in scope) —— 应改为 Double(effectiveWidth)")
    if t.count("Double(effectiveWidth),") != 1:
        raise RuntimeError("verify_zhao_md_v60 L8: 诊断段实参未指向 effectiveWidth")
    return True


def fix_zhao_compat_v60(t):
    """v60 注入: iOS15Compat.swift 的 hosting sizeThatFits 重写(同款)。"""
    if "[V60-ZHAO-HOST]" in t:
        return t
    n = t.count(V60_HOST_OLD)
    if n != 1:
        raise RuntimeError(
            "fix_zhao_compat_v60: isMeasuring 声明锚点出现 %d 次(应为 1) —— "
            "兼容层结构可能变了" % n)
    return t.replace(V60_HOST_OLD, V60_HOST_NEW, 1)


def verify_zhao_compat_v60(t):
    """v60 判据: 三层(iOS15Compat.swift)。"""
    if t.count("[V60-ZHAO-HOST]") != 1:
        raise RuntimeError("verify_zhao_compat_v60: 缺 [V60-ZHAO-HOST]")
    if t.count("override func sizeThatFits(_ size: CGSize) -> CGSize") != 1:
        raise RuntimeError(
            "verify_zhao_compat_v60: hosting sizeThatFits 重写缺失/重复 "
            "(systemLayoutSizeFitting 两个已有重写不受影响, 签名不同)")
    i = t.find("[V60-ZHAO-HOST]")
    tail = t[i:i + 1200]
    if "ceil(fitSize.height)" not in tail or "host.view.sizeThatFits" not in tail:
        raise RuntimeError("verify_zhao_compat_v60: 重写体不完整(缺 ceil/host 调用)")
    return True


# ============================================================
# v61: 治「打字/滑动时整屏跳动 + 流式内容跳出而非流动」
# ============================================================
# 【装机证据(2026-10-05 5.log + 86s 录屏帧差分析)】
#   ① 卡字已消失: tcW 557 次采样 100% 恒 358, 零拉锯(v60 生效确认)。
#   ② 帧差: 43-56s 内容位移=0 但残差 0.3↔18.5 剧烈波动 = 整屏 cell
#      原地反复重排, 非滚动。
#   ③ 日志: 同一消息(storageLen=209, tcW=358)高度在 333↔490 间漂移
#      (差 157pt), "large shrink -157 applies immediately"(IOS15-FIX-BLANK)
#      反复触发 —— 每次回缩/再增长 = 一次整屏跳动。
# 【根因】我们的 UIHostingConfiguration 替身 apply() 每次调用都
#   全删重建 UIHostingController(subviews.removeFromSuperview + new)。
#   UIHostingConfiguration 是值类型, 流式输出每 tick SwiftUI 都给新值
#   ⇒ didSet ⇒ apply ⇒ 每 tick 重建 host ⇒ SwiftUI 状态/测量从零起步
#   ⇒ 高度测量不稳定(333↔490) ⇒ cell 高度来回修正 = 跳动。
#   zhaoxiufei 的 HostingContentView 有快速路径 `host?.rootView = ...`
#   (3ccdff6 diff 上下文可见), 没有 rebuild 风暴。
# 【修法两件套】
#   A. [V61-REUSE] apply 就地更新快速路径: 同类 config 复用已有 host,
#      只刷 rootView —— 与 zhaoxiufei 实现对齐。
#   B. [V61-MONO] 高度单调锁: 同宽下记住历史最高, 回缩超 8pt 容差则
#      沿用历史值(容差防字体/图片加载等合法微缩被锁死)。快速路径使
#      apply 不再每 tick 重建后, 锁按「宽度 + apply 重建」重置即可:
#      复用换消息走重建路径 → 锁清(不串扰); 流式 tick 走快速路径 →
#      锁保持(同内容回缩被挡)。
# ============================================================

V61_DECL_OLD = """    private var isMeasuring: Bool = false
    private var lastLoggedWidth: CGFloat = -1
    private var ios15LastGoodFitH: CGFloat = 0"""

V61_DECL_NEW = """    private var isMeasuring: Bool = false
    private var lastLoggedWidth: CGFloat = -1
    private var ios15LastGoodFitH: CGFloat = 0
    // [V61-MONO] 高度单调锁状态: (历史最高, 绑定宽度)。宽变即重置。
    private var ios15MonoH: CGFloat = 0
    private var ios15MonoHW: CGFloat = 0"""

V61_TAIL_OLD = """        print("[IOS15Size] out w=\\(width) h=\\(height) idealW=\\(size.width) idealH=\\(size.height)")
        if height > 1 { ios15LastGoodFitH = max(ios15LastGoodFitH, height) }
        return CGSize(width: width, height: max(0, height))"""

V61_TAIL_NEW = """        print("[IOS15Size] out w=\\(width) h=\\(height) idealW=\\(size.width) idealH=\\(size.height)")
        if height > 1 { ios15LastGoodFitH = max(ios15LastGoodFitH, height) }
        // [V61-MONO] 单调锁生效点: 同宽下回缩超容差(8pt) → 沿用历史最高。
        // 挡住「测量管道抖动」(attachment 缓存时序导致同内容两次测量差
        // 157pt)直接上屏 —— 那就是用户看到的整屏跳动。
        if width != ios15MonoHW { ios15MonoHW = width; ios15MonoH = 0 }
        if ios15MonoH > 1, height > 1, height < ios15MonoH - 8 {
            height = ios15MonoH
        }
        if height > ios15MonoH { ios15MonoH = height }
        return CGSize(width: width, height: max(0, height))"""

V61_APPLY_OLD = """    private func apply(_ config: UIContentConfiguration) {
        subviews.forEach { $0.removeFromSuperview() }
        host = nil
        guard let config = config as? UIHostingConfiguration<Content> else { return }"""

V61_APPLY_NEW = """    private func apply(_ config: UIContentConfiguration) {
        // [V61-REUSE] 就地更新快速路径(zhaoxiufei HostingContentView 同款):
        // 同类 config 且已有 host 时只刷 rootView, 不再全删重建 ——
        // 流式输出每 tick 走这里, SwiftUI 就地 diff, 测量状态连续。
        // 旧实现每 tick 重建 UIHostingController(每秒 N 次) = 高度抖动
        // 与整屏跳动的放大器(2026-10-05 5.log 实证 333↔490 漂移)。
        if let existing = host, let newConfig = config as? UIHostingConfiguration<Content> {
            let _ios15ContentMaxW2 = max(UIScreen.main.bounds.width, 200)  // [V61-REUSE] 与重建路径同款上限
            existing.rootView = AnyView(newConfig.content.frame(maxWidth: _ios15ContentMaxW2, alignment: .leading))
            return
        }
        subviews.forEach { $0.removeFromSuperview() }
        host = nil
        guard let config = config as? UIHostingConfiguration<Content> else { return }"""

V61_RESET_OLD = """        host = controller
    }
}"""

V61_RESET_NEW = """        host = controller
        // [V61-MONO] 走到重建路径 = 内容标识换了(新消息/复用), 锁重置。
        ios15MonoH = 0
        ios15MonoHW = 0
    }
}"""


def fix_host_stability_v61(t):
    """v61 注入: iOS15Compat.swift 四处(REUSE 快速路径 + MONO 单调锁)。

    幂等: 已有 [V61-REUSE] 原样返回。锚点计数==1 防呆, 失配报错。
    """
    if "[V61-REUSE]" in t:
        return t
    t = _v60_replace1(t, V61_DECL_OLD, V61_DECL_NEW, "v61 锁声明")
    t = _v60_replace1(t, V61_TAIL_OLD, V61_TAIL_NEW, "v61 锁生效点")
    t = _v60_replace1(t, V61_APPLY_OLD, V61_APPLY_NEW, "v61 apply 快速路径")
    t = _v60_replace1(t, V61_RESET_OLD, V61_RESET_NEW, "v61 重建路径锁重置")
    return t


def verify_host_stability_v61(t):
    """v61 判据: 五层(iOS15Compat.swift)。"""
    if t.count("[V61-REUSE]") != 2:
        raise RuntimeError(
            "verify_host_stability_v61: [V61-REUSE] 应恰 2 处(apply 快速路径"
            "标记 + 尾注), 实测 %d" % t.count("[V61-REUSE]"))
    if t.count("[V61-MONO]") != 3:
        raise RuntimeError(
            "verify_host_stability_v61: [V61-MONO] 应恰 3 处(声明/生效点/"
            "重置), 实测 %d" % t.count("[V61-MONO]"))
    # 快速路径必须带与重建路径同款的 maxWidth 修饰(否则理想宽回潮)
    if "existing.rootView = AnyView(newConfig.content.frame(maxWidth:" not in t:
        raise RuntimeError(
            "verify_host_stability_v61: 快速路径 rootView 缺 maxWidth 修饰 ——"
            "内容理想宽(100032)会从这条路径回潮")
    # 快速路径必须在重建(subviews.forEach)之前
    i_fast = t.find("[V61-REUSE] 就地更新快速路径")
    i_rebuild = t.find("subviews.forEach { $0.removeFromSuperview() }")
    if not (0 < i_fast < i_rebuild):
        raise RuntimeError(
            "verify_host_stability_v61: 快速路径未排在重建路径之前 —— "
            "每次 apply 仍会先全删子视图")
    # 锁生效点三要素
    i_mono = t.find("ios15MonoH")
    tail = t[i_mono:i_mono + 400]
    if "ios15MonoHW = width" not in t or "ios15MonoH - 8" not in t:
        raise RuntimeError("verify_host_stability_v61: 锁生效点逻辑不完整"
                           "(缺宽绑定重置或 8pt 容差)")
    # 重建路径必须重置锁(防复用串扰: 矮消息沿用高消息 → 大空白)
    # 锚点用 ios15MonoHW = 0: 锁尾部含子串 "ios15MonoH = 0", find 会误命中,
    # 而 "ios15MonoHW = 0" 全文件唯一(重建重置独有)。
    i_reset = t.find("ios15MonoHW = 0")
    i_hostc = t.find("host = controller")
    if not (0 < i_hostc < i_reset):
        raise RuntimeError(
            "verify_host_stability_v61: 重建路径缺锁重置 —— cell 复用换消息时"
            "会沿用上一条消息的锁定高度 → 底部大空白")
    return True


# ============================================================
# v62: V62-SURPLUS —— 盈余镜像(治「工具卡片间大空白」)
#
# 【装机铁证】minis-2026-10-05.log(v61, 07:42-07:43):
#   用户截图/录屏: 三个工具卡片之间各 ~250pt 空白, 且为终态留存。
#   IOS15Size 测量全部真实(h==idealH, 卡片 46.7pt) ⇒ 测量层清白;
#   V53-SHORT 反复报 last h=337/384(live terminal 时代的高度);
#   FIX-BLANK 只漏出 2 次 -112 部分收缩, -290 的完整收缩从未发生。
#
# 【根因链】v53 体系是「欠账」单极的:
#   1. 工具执行中: live terminal block, cell 被撑到 337/384pt;
#   2. 工具完成: SwiftUI 内容收缩为纯卡片(46.7pt);
#   3. E 判据上报 `_needH - _v52PreSVH` = -290 → `v53NotePendingDebt`
#      的 `if debt <= 1` 把负值**直接吞掉复位** —— 盈余零动作;
#   4. v18 撑高路径只撑不缩; A/B/C 三条短路继续返回
#      lastComputedHeight(337/384) ⇒ cell 停在高值;
#   5. 没有任何通道为收缩触发 invalidate ⇒ 空隙永久留存。
#   即: v53-C2 治「太矮」(裁字)却没有「太高」(空白)的镜像检测。
#
# 【修法】镜像欠账机制补全盈余半边:
#   · v53NotePendingDebt 加盈余分支: debt < -40 计两拍 → v53SurplusIsRipe;
#     (-40, -1] 的小幅收缩视为排版噪声复位; 欠账态互斥清盈余。
#   · 三条短路守卫 `!v53DebtIsRipe` 扩为 `!v53DebtIsRipe, !v53SurplusIsRipe`。
#   · v53-FIRST settle 入口(_stillOwing guard)扩 _v62oversized:
#     盈余同样触发真实测量 + invalidate —— 收缩从此有驱动源;
#     且盈余时上报负 debt 喂给镜像计数(否则盈余永远熟不了)。
# 【收敛】cell 落到 need 高后 _v62oversized 恒假, 稳态零开销;
#   流式再增长走原欠账通道, 与盈余互斥, 无振荡回路。
# ============================================================

V62_FIELD_ANCHOR = """    var v53DebtIsRipe: Bool { v53DebtSeenCount >= 2 }"""

V62_FIELD_NEW = """    var v53DebtIsRipe: Bool { v53DebtSeenCount >= 2 }

    // [V62-SURPLUS] 盈余镜像状态(v53-C2 只有「太矮」半边, 这里补「太高」):
    // 装机铁证(v61): 工具卡片收起 live terminal 后内容 337→47pt, E 判据
    // 上报 -290 被 `debt <= 1` 吞掉复位, 三条短路继续返回 337/384 ⇒
    // 卡片间 ~250pt 空白终态留存。
    var v53SurplusSeenCount: Int = 0
    var v53SurplusHeightDebt: CGFloat = 0
    /// 盈余已「熟」(连续观测两拍以上) ⇒ 三条短路放行真实测量。
    var v53SurplusIsRipe: Bool { v53SurplusSeenCount >= 2 }"""

V62_NOTE_ANCHOR = """    func v53NotePendingDebt(_ debt: CGFloat) -> Bool {
"""

V62_NOTE_NEW = """    func v53NotePendingDebt(_ debt: CGFloat) -> Bool {
        // [V62-SURPLUS] 盈余观测: debt < -40 = cell 比 need 高出 40pt 以上
        // (工具卡片收起 live terminal 实测上报 -290)。阈值 40pt 排除行高/
        // 间距级噪声; 与欠账同款两拍设计 —— 首帧仍走短路, 第二拍放行。
        if debt < -40 {
            v53DebtSeenCount = 0
            v53PendingHeightDebt = 0
            v53SurplusHeightDebt = -debt
            v53SurplusSeenCount += 1
            return v53SurplusIsRipe
        }
        if debt < -1 {
            // [V62-SURPLUS] ≤40pt 的小幅收缩是排版噪声, 盈余复位。
            v53SurplusSeenCount = 0
            v53SurplusHeightDebt = 0
        }
"""

V62_MUTEX_ANCHOR = """        v53PendingHeightDebt = debt
        v53DebtSeenCount += 1"""

V62_MUTEX_NEW = """        // [V62-SURPLUS] 欠账与盈余互斥: 转入欠账态时清盈余计数,
        // 避免两个镜像计数同时「熟」导致短路判据语义含糊。
        v53SurplusSeenCount = 0
        v53SurplusHeightDebt = 0
        v53PendingHeightDebt = debt
        v53DebtSeenCount += 1"""

V62_GUARDS_OLD = "!v53DebtIsRipe {"

V62_FIRST_OLD = """        guard deferredCorrectionPending || _stillOwing else { return }
        // [V53-DEBT] 把欠账告诉 cell, 逼它的滑动期短路放行(见 _v53ReportDebtToCell)。
        _v53ReportDebtToCell(_stillOwing ? _debt : 0)"""

V62_FIRST_NEW = """        // [V62-SURPLUS] 盈余(cell 比 need 高 40pt+)同样触发 settle 纠正 ——
        // 收缩没有欠账通道那样的撑高驱动, 没有这条 invalidate 就没人重问
        // cell 高度, 三条短路返回的 337/384 会永远留在布局里(空白留存)。
        let _v62oversized = _cellH > 1 && _need > 1 && (_cellH - _need) > 40
        guard deferredCorrectionPending || _stillOwing || _v62oversized else { return }
        // [V53-DEBT] 把欠账告诉 cell, 逼它的滑动期短路放行(见 _v53ReportDebtToCell)。
        // [V62-SURPLUS] 盈余时上报负 debt, 喂给 cell 的盈余镜像计数走向「熟」。
        _v53ReportDebtToCell(_stillOwing || _v62oversized ? _debt : 0)"""


def fix_surplus_mirror_v62_infra(t):
    """v62 注入①: MessageListInfrastructure.swift(SelfSizingCell)三处。

    字段三件套 / note 函数盈余分支 + 互斥 / 三条短路守卫扩展。
    幂等: 已有 [V62-SURPLUS] 原样返回。锚点计数防呆。
    """
    if "[V62-SURPLUS]" in t:
        return t
    t = _v60_replace1(t, V62_FIELD_ANCHOR, V62_FIELD_NEW, "v62 盈余字段")
    t = _v60_replace1(t, V62_NOTE_ANCHOR, V62_NOTE_NEW, "v62 note 盈余分支")
    t = _v60_replace1(t, V62_MUTEX_ANCHOR, V62_MUTEX_NEW, "v62 欠账互斥清盈余")
    n = t.count(V62_GUARDS_OLD)
    if n != 3:
        raise RuntimeError(
            "fix_surplus_mirror_v62_infra: 短路守卫 `!v53DebtIsRipe {{}}` 应恰 3 处"
            "(A/B/C), 实测 %d —— v53 形态变了, 必须更新锚点" % n)
    t = t.replace(V62_GUARDS_OLD, "!v53DebtIsRipe, !v53SurplusIsRipe {")
    return t


def fix_surplus_mirror_v62_md(t):
    """v62 注入②: SelectableMarkdownView.swift 的 v53-FIRST settle 入口。

    guard 扩 _v62oversized + 盈余时上报负 debt。
    """
    if "[V62-SURPLUS]" in t:
        return t
    t = _v60_replace1(t, V62_FIRST_OLD, V62_FIRST_NEW, "v62 settle 盈余入口")
    return t


def verify_surplus_mirror_v62(infra, md):
    """v62 判据: 五层(两文件)。"""
    F = "verify_surplus_mirror_v62"
    # ① 字段三件套 + ripe 声明
    for key in ("var v53SurplusSeenCount: Int = 0",
                "var v53SurplusHeightDebt: CGFloat = 0",
                "var v53SurplusIsRipe: Bool { v53SurplusSeenCount >= 2 }"):
        if key not in infra:
            raise RuntimeError("%s: 盈余字段缺失 %r" % (F, key))
    # ② note 函数盈余分支(阈值 + 计数递增 + 喂还 ripe)
    i = infra.find("func v53NotePendingDebt(")
    if i < 0:
        raise RuntimeError("%s: note 函数缺失" % F)
    seg = infra[i:i + 2200]
    for key in ("if debt < -40 {", "v53SurplusSeenCount += 1",
                "return v53SurplusIsRipe", "v53SurplusSeenCount = 0"):
        if key not in seg:
            raise RuntimeError("%s: note 函数盈余分支不完整(缺 %r)" % (F, key))
    # ③ 三条短路守卫各带盈余条件
    n = infra.count("!v53DebtIsRipe, !v53SurplusIsRipe {")
    if n != 3:
        raise RuntimeError("%s: 三守卫应恰 3 处带 `!v53SurplusIsRipe`, 实测 %d"
                           % (F, n))
    # ④ settle 入口: guard 扩盈余 + 上报喂负值
    for key in ("let _v62oversized = _cellH > 1 && _need > 1 && (_cellH - _need) > 40",
                "guard deferredCorrectionPending || _stillOwing || _v62oversized else { return }",
                "_v53ReportDebtToCell(_stillOwing || _v62oversized ? _debt : 0)"):
        if key not in md:
            raise RuntimeError("%s: settle 入口缺 %r" % (F, key))
    # ⑤ 互斥复位(欠账态清盈余)
    if "v53SurplusSeenCount = 0\n        v53SurplusHeightDebt = 0\n        v53PendingHeightDebt = debt" not in infra:
        raise RuntimeError("%s: 欠账态互斥清盈余缺失" % F)
    return True


# ============================================================
# v63: 恢复 iOS 15 尺寸更新信号 + 打破 v53/v62 循环依赖
#
# 【装机铁证】minis-2026-10-05 7.log(v62 装机, 08:35-08:37) + 80.7s 录屏:
#   症状: 工具卡片间空白一大片 / 文字一下跳出一大段(非流式) / 整屏狂跳.
#   三条反常识铁证:
#     ① [V53-DEBT] / [V62-SURPLUS] 日志出现 **0 次** —— v62 的修复代码
#        根本没进运行路径(不是"没治好", 是"没运行")。
#     ② V53-SHORT 的 live= 唯一取值 {0} ⇒ 三条短路从未放行真实测量。
#        debt= 唯一取值 {0.0} ⇒ 欠账恒 0, 盈余镜像无数据可吃。
#     ③ idx=19 工具消息 1.5s 内 6 次 INVALIDATE **全部 cached=true**:
#        pref=798→903→1057→1205→1336→1518, est 一路追 pref 跑 ⇒ 每次
#        返回**上一次的旧高度**。高度分布跨数量级: 46.7/337/384/1160/1557。
#   帧差(4200 帧): 30% 帧跳变 >15%, 静止仅 16%。
#
# 【根因 A: iOS 15 的尺寸更新通道被 v60 切断】★★这是 v31~v62 三十余版
#   都踩空的一层, 外部方案交叉验证:
#   · iOS 16 起 UIHostingController 才有 sizingOptions; **iOS 15 没有**。
#   · iOS 15 上它感知"SwiftUI 内容变了"的**唯一**通道就是
#     intrinsicContentSize + invalidateIntrinsicContentSize():
#       - Mozilla Firefox iOS HostingTableViewCell: host() 里每次
#         rootView 赋值后都跟一行 view.invalidateIntrinsicContentSize()
#       - StackOverflow 77027194(36k赞): "试过 setNeedsLayout /
#         setNeedsUpdateConstraints / layoutIfNeeded, 只有
#         invalidateIntrinsicContentSize() 有效"
#       - vbat.dev: "what if I need to support iOS 15? 只能显式
#         setNeedsUpdateConstraints()/invalidateIntrinsicContentSize()"
#       - Apple FB9641883(iOS 15 UIHostingController 多余 padding,
#         iOS 16 才修): 社区解法同样是 viewDidLayoutSubviews 里
#         setNeedsUpdateConstraints + preferredContentSize 绑 intrinsic。
#   而 v60 把 intrinsicContentSize 重写成:
#       return CGSize(width: noIntrinsicMetric, height: noIntrinsicMetric)
#   —— 三十余版都默认 intrinsicContentSize 是"宽度污染源"把它当病灶切了,
#     **而它其实是 iOS 15 唯一的更新信号源**。切掉 ⇒ UIKit 聋了 ⇒
#     只能靠 cell 三短路硬撑 ⇒ 而短路又因下面的根因 B 永不放开。
#
# 【根因 B: v53/v62「两拍」是循环依赖】★
#   两版的设计都是"连续观测两拍才放行真实测量"(首帧走短路稳态, 第二拍放行)。
#   但 debt 只在 consumeDeferredCorrectionIfNeeded()(settle 时刻)上报,
#   而 settle 的 guard 又依赖欠账是否成立:
#       要放行测量 → 需要 debt 熟 → debt 熟需要 settle → settle 要先放行测量
#   ⇒ v53DebtSeenCount 永远停在 1 ⇒ live 恒 0 ⇒ 第二拍从未到来。
#   实测 debt=0.0 恒成立, 就是这个循环的直接证据。
#
# 【修法】
#   A. V63-INTSIZE: intrinsicContentSize 恢复上报**高度**(宽仍
#      noIntrinsicMetric —— 宽污染是另一回事, 由 v60 的 sane 推导链治,
#      两件事不混)。
#   B. V63-UPDATE: REUSE 快速路径改完 rootView 立即
#      invalidateIntrinsicContentSize()(Firefox/vbat 同款)。这是 iOS 15
#      上"内容变了"的唯一通知方式, 不加这行 SwiftUI 再怎么变 UIKit 都不知道。
#   C. V63-CFG: REUSE 快速路径加 config 身份判等。原先只判 host != nil,
#      而 host 只在重建路径末尾才置 nil ⇒ 跨消息类型(工具卡→文本卡)会
#      拿上一个 host 就地刷 rootView, 用错测量状态。
#   D. V63-UNCYCLE: settle 入口 guard 加 _v63drift —— cell 高与真实测量
#      之差超阈值就**直接**放行, 不再等 debt 熟。根因 A 修好后 invalidate
#      通道恢复, 这里再给一把兜底, 双管齐下。
#
# 【探针纪律】v53/v62 的注入都没带 NSLog, 导致"零输出"这个一眼可辨的
#   信号被连续两版忽略(verify-discipline 第 5 条: 判据的输出会塑造
#   后来人的修法; 代码的输出同理)。本版三段全部自带 [V63-*] 探针,
#   CI 断言其存在 ⇒ 装机后若仍零输出, 立刻知道这段没被执行。
# ============================================================

# ---- A/B/C: iOS15Compat.swift ----
# 锚点①: v61 的 REUSE 快速路径(整块替换, 顺带补 config 判等 + invalidate)
V63_REUSE_OLD = """        if let existing = host, let newConfig = config as? UIHostingConfiguration<Content> {
            let _ios15ContentMaxW2 = max(UIScreen.main.bounds.width, 200)  // [V61-REUSE] 与重建路径同款上限
            existing.rootView = AnyView(newConfig.content.frame(maxWidth: _ios15ContentMaxW2, alignment: .leading))
            return
        }"""

V63_REUSE_NEW = """        if let existing = host, let newConfig = config as? UIHostingConfiguration<Content>, _v63ConfigGen == _ios15ApplyGen {
            let _ios15ContentMaxW2 = max(UIScreen.main.bounds.width, 200)  // [V61-REUSE] 与重建路径同款上限
            existing.rootView = AnyView(newConfig.content.frame(maxWidth: _ios15ContentMaxW2, alignment: .leading))
            // [V63-UPDATE] iOS 15 没有 sizingOptions(iOS 16 才有), 所以
            // rootView 换完之后**必须**显式 invalidateIntrinsicContentSize(),
            // 否则 UIKit 收不到"内容变了"的信号 —— 高度锁死在上一次的值,
            // 流式输出表现为「一下跳出一大段」而不是逐行流动。
            // 依据: Mozilla Firefox iOS HostingTableViewCell.host() 每次
            // rootView 赋值后都跟这一行; vbat.dev 与 StackOverflow 77027194
            // 同结论(后者明确说 setNeedsLayout/layoutIfNeeded 都无效)。
            existing.view.invalidateIntrinsicContentSize()
            // [V63-PROBE] 每 0.5s 汇总一行: 装机若为 0 ⇒ 这段快速路径没被执行。
            _v63ProbeIncr()
            return
        }"""

# 锚点②: 重建路径赋值处(加 config 世代号 + 探针)
V63_REBUILD_OLD = """        host = controller
        // [V61-MONO] 走到重建路径 = 内容标识换了(新消息/复用), 锁重置。
        ios15MonoH = 0
        ios15MonoHW = 0"""

V63_REBUILD_NEW = """        host = controller
        // [V61-MONO] 走到重建路径 = 内容标识换了(新消息/复用), 锁重置。
        ios15MonoH = 0
        ios15MonoHW = 0
        // [V63-CFG] 重建即换身份: 记下本次 apply 的世代号, 让下一次 apply
        // 能判出"host 还是上次的那个"而不是无脑就地刷。
        _v63ConfigGen = _ios15ApplyGen
        // [V63-PROBE] 重建路径计数(与快速路径分开统计, 便于装机分辨走哪条)。
        _v63ProbeIncr()"""

# 锚点③: apply 入口(世代号自增 —— 每次 apply 都是一次内容更新尝试)
V63_APPLY_HEAD_OLD = """    private func apply(_ config: UIContentConfiguration) {"""

V63_APPLY_HEAD_NEW = """    private func apply(_ config: UIContentConfiguration) {
        // [V63-CFG] 每次 apply 自增世代号。fast path 的判等条件
        // `_v63ConfigGen == _ios15ApplyGen` 意为"host 就是上一次 apply
        // 建/刷的那个"; 一旦中间走过重建, 世代号就变了 ⇒ 下次走重建,
        // 不会拿已经属于别的消息的 host 去就地刷 rootView。
        _ios15ApplyGen &+= 1"""

# 锚点④: 字段声明(探针计数器)
V63_DECL_OLD = """    private var isMeasuring: Bool = false"""

# ★★ run#157 编译失败教训(2026-10-05): 静态存储属性不能放在泛型类型里。
# `_HostingContentCellView<Content: View>` 是泛型类型, Swift 编译器硬性拒绝
# `private static var`(error: static stored properties not supported in
# generic types), 三个计数器直接让 Release 编译 exit 65。
#
# ★为什么判据没拦住: v63 全链 33/0/0 全绿, 文本判据只验「标记在位」,
# 没有任何一条验「Swift 语法合法」—— 判据体系存在一个真实盲区。
# 所以修法不只是搬代码, 必须同时补一条**语法级**判据(见 verify_swift_static_v63)。
V63_DECL_NEW = """    private var isMeasuring: Bool = false
    // [V63-CFG] apply 世代号(见 apply 入口) 与 host 身份戳。
    private var _ios15ApplyGen: UInt = 0
    private var _v63ConfigGen: UInt = 0
    // [V63-PROBE] 装机探针: 快速路径/重建路径各计一次, 每 0.5s 打一行。
    // ★为什么必须有: v53/v62 都没带探针, 于是「零输出」这个一眼可辨的
    // 信号被连续两版忽略 —— 判据全绿而代码从未在真机执行。
    // ★计数器在 _V63Probe(非泛型) 上, 不在本格里 —— 泛型类型禁 static 存储属性。
    private func _v63ProbeIncr() {
        if _v63ConfigGen == _ios15ApplyGen { _V63Probe.hitFast() }
        else { _V63Probe.hitRebuild() }
    }"""

# [V63-PROBE] 非泛型探针宿主。★必须非泛型: 泛型类型里放 static 存储属性
# 是 Swift 硬错误(run#157 实测, exit 65)。三个计数器 + 0.5s 节流都在这里。
V63_PROBE_OLD = """private final class _HostingContentCellView<Content: View>: UIView, UIContentView {"""

V63_PROBE_NEW = """// [V63-PROBE] 装机可观测性计数器。★必须是**非泛型**类型: Swift 禁止在
// 泛型类型里声明静态存储属性, 放进去 Release 编译直接失败(run#157)。
private final class _V63Probe {
    static var fastHit: UInt = 0
    static var rebuildHit: UInt = 0
    static var lastPrint: CFTimeInterval = 0
    static func hitFast() { fastHit &+= 1; maybePrint() }
    static func hitRebuild() { rebuildHit &+= 1; maybePrint() }
    private static func maybePrint() {
        let now = CACurrentMediaTime()
        guard now - lastPrint > 0.5 else { return }
        lastPrint = now
        print("[V63-PROBE] fast=\\(fastHit) rebuild=\\(rebuildHit)")
    }
}

private final class _HostingContentCellView<Content: View>: UIView, UIContentView {"""

# ---- A 锚点⑤: intrinsicContentSize 恢复高度上报 ----
V63_INTSIZE_OLD = """    override var intrinsicContentSize: CGSize {
        let width = textContainer.size.width > 1 && textContainer.size.width < 100_000 ? textContainer.size.width : (bounds.width > 1 ? bounds.width : UIScreen.main.bounds.width - 32)
        guard width > 1, textStorage.length > 0 else {
            return CGSize(width: UIView.noIntrinsicMetric, height: UIView.noIntrinsicMetric)
        }
        let fit = sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        return CGSize(width: UIView.noIntrinsicMetric, height: ceil(fit.height))
    }"""

V63_INTSIZE_NEW = """    override var intrinsicContentSize: CGSize {
        let width = textContainer.size.width > 1 && textContainer.size.width < 100_000 ? textContainer.size.width : (bounds.width > 1 ? bounds.width : UIScreen.main.bounds.width - 32)
        guard width > 1, textStorage.length > 0 else {
            return CGSize(width: UIView.noIntrinsicMetric, height: UIView.noIntrinsicMetric)
        }
        let fit = sizeThatFits(CGSize(width: width, height: .greatestFiniteMagnitude))
        // [V63-INTSIZE] 恢复**高度**上报(宽仍 noIntrinsicMetric)。
        //
        // 【为什么必须恢复】v60 把 height 也改成 noIntrinsicMetric(退出协商),
        // 理由是"intrinsicContentSize 直接把容器宽当理想宽上报 100032 污染布局"
        // —— 那个理由对**宽度**成立, 但把高度也一并关掉是误伤:
        //   · iOS 16 起 UIHostingController 有 sizingOptions;
        //     **iOS 15 没有**(部署目标就是 15.5) ⇒ 它的 intrinsicContentSize
        //     是 SwiftUI 内容尺寸的唯一对外信号;
        //   · 本项目以 UITextView 为承载(v60 自己的注释写着
        //     "UITextView.intrinsicContentSize 直接把容器宽当理想宽报给 SwiftUI"),
        //     而 UITextView 恰恰**以 intrinsicContentSize 参与 Auto Layout**;
        //   · 外部四个独立来源(Mozilla Firefox iOS HostingTableViewCell、
        //     vbat.dev、StackOverflow 77027194、Apple FB9641883 社区解法)
        //     全部指向"iOS 15 靠 intrinsic + invalidate 协商尺寸"。
        // 装机实证: 关掉之后 live=0/debt=0.0/cached=true×44, 高度锁死旧值
        // (798→903→1057→1205→1336→1518), 表现为空白 + 突现 + 整屏跳。
        // 宽的污染另由 v60 的 sane 推导链治, 两件事不混。
        return CGSize(width: UIView.noIntrinsicMetric, height: ceil(fit.height))
    }"""


def fix_intrinsic_gate_v63_compat(t):
    """v63 注入①: iOS15Compat.swift 三处 + SelectableMarkdownView 一处。

    字段/世代号 + REUSE 快速路径(invalidate + config 判等) + 重建路径探针
    + intrinsicContentSize 恢复高度上报。

    幂等: 已有 [V63-UPDATE] 原样返回。锚点计数防呆。
    """
    if "[V63-UPDATE]" in t:
        return t
    # ⓪ 非泛型探针宿主(run#157: 泛型类型里放 static 存储属性编译必失败)
    t = _v60_replace1(t, V63_PROBE_OLD, V63_PROBE_NEW, "v63 非泛型探针宿主")
    # ① 字段 + 探针
    t = _v60_replace1(t, V63_DECL_OLD, V63_DECL_NEW, "v63 探针/世代号字段")
    # ② apply 入口世代号自增
    t = _v60_replace1(t, V63_APPLY_HEAD_OLD, V63_APPLY_HEAD_NEW, "v63 apply 世代号")
    # ③ REUSE 快速路径: 加 config 判等 + invalidateIntrinsicContentSize
    t = _v60_replace1(t, V63_REUSE_OLD, V63_REUSE_NEW, "v63 REUSE invalidate+判等")
    # ④ 重建路径: 记身份戳 + 探针
    t = _v60_replace1(t, V63_REBUILD_OLD, V63_REBUILD_NEW, "v63 重建身份戳")
    return t


# ==================================================================
# v64: 打断「测量自激」—— 单向累加的真正病因
# ==================================================================
# v64: 切断「自我播种」—— 单向累加的真正病因
# ==================================================================
#
# 【v63 装机实证 2026-10-05】v63 第一次在真机跑起来:
#   [V63-PROBE] fast=1412 rebuild=0     (88 次输出)
#   live=21/26/32/34/45                  (不再是恒 0)
#   ⇒ invalidate 通道真的通了, v62 之前「探针 0 次 + live 恒 0」的死局打破。
#   这是 v31~v62 三十余版从未有过的证据。
#
# 【但病更重了】几何判据(idx=9):
#   尾部极差 717.0pt(上限 8.0), 最大单跳 301.0pt, 全段跨度 = 名义高 28.2 倍
#   v62 时尾部极差 436pt ⇒ **反而更大**。
#
# 【病态形态变了 —— 这是本版的关键发现】
#   v30-A 时期: 双引擎测高互相**翻转**(1176 ⇄ 850), est/pref 交叉
#   v63 时期:   **单调累加, 只涨不跌**
#     est=31   → pref=236   (+205)
#     est=236  → pref=380   (+144)
#     est=380  → pref=555   (+175)
#     est=643  → pref=809   (+166)
#     est=809  → pref=971   (+162)
#     est=1070 → pref=1272  (+202)
#   delta 稳定在 +144~+205 ⇒ 每拍固定多出约 170pt。
#   日志里「双引擎/翻转」标记 0 次 ⇒ v30-A 那个老毛病确实治好了,
#   现在露出来的是**更靠上游的新问题**。
#
# 【为什么 v63 反而更严重 —— 不是 v63 改坏了】
#   v53/v62 的三条短路(欠账/盈余/settle 门)实际上在**掩盖**这个更底层的问题:
#   它们让高度锁死在旧值, 看起来"稳定", 其实是冻结。
#   v63 把 invalidate 通道修好后, 底层错误测量终于能真正执行 ⇒ 暴露。
#   ⇒ 典型「修好上层, 下层塌出来」。必须继续往下挖, 不能回头打补丁。
#
# ==================================================================
# 【v64 根因判定: 不是"重排太频繁", 是"测量自己喂自己"】
# ==================================================================
# 装机日志时间戳(这是推翻 v64 初版设计的决定性证据):
#   11:07:52.403  est=31   → pref=236
#   11:07:52.586  est=236  → pref=380    (+0.183s)
#   11:07:52.778  est=380  → pref=555    (+0.192s)
#   11:07:53.170  est=643  → pref=809    (+0.392s)
#   11:07:53.382  est=809  → pref=971    (+0.212s)
#   11:07:53.981  est=1070 → pref=1272   (+0.599s)
# 6 拍全在 1.58s 内, 相邻间隔 0.183~0.81s。
#
# ⇒ v64 初版设计的「同宽 + 0.35s 时间窗幂等锁」**拦不住**:
#   0.183/0.192/0.212s 三拍落在窗内会被拦, 但 0.392/0.599s 两拍在窗外
#   照样放行 ⇒ 累加照旧。那把锁是装饰品, 必须推翻。
#
# ⇒ 更要紧的是看清了 est 与 pref 的关系:
#     est_{n+1} == pref_n     (严格相等)
#     pref_n - est_n ≈ +170  (恒定)
#   est 就是 UIKit 下一轮递给我们的 layoutAttributes.size.height, 也就是
#   **我们上一轮亲手写进 heightCache 的那个值**。
#   ⇒ 高度不是"被谁算大了", 是**被自己上一轮的答案累加出来的**。
#   这就是数学上的发散: H_{n+1} = H_n + 170, H_n = 31 + 170n。
#
# 【根因代码 —— MessageListInfrastructure.swift, preferredLayoutAttributesFitting】
#   :531  let targetSize = CGSize(width: ..., height: UIView.layoutFittingCompressedSize.height)
#         ↑ 声明了"我要压缩语义(从内容重算)"
#   :561  var fittingSize = CGSize(width: targetSize.width, height: attrs.size.height)
#         ↑ 却用 super 刚返回的、**已经膨胀过**的 attrs.size.height 当测量初值
#   :567  fittingSize = self.contentView.systemLayoutSizeFitting(targetSize, ... .fittingSizeLevel)
#   :717  fittingSize.height = _ios15Reconciled      (= max(SwiftUI, TextKit))
#   :725  lastComputedHeight = fittingSize.height    ← 写回缓存, 成为下一轮的 est
#
#   :561 与 :531 **自相矛盾**: 声明压缩优先级, 却用上一轮结果播种。
#   iOS 16+ 上 SwiftUI 遵守 .fittingSizeLevel, 从内容重算 ⇒ 无害;
#   **iOS 15 上不遵守, 播种值胜出** ⇒ 写进缓存 ⇒ 下一轮 est 更大 ⇒ 再播种
#   ⇒ 每拍 +170 的自激环。
#
# 【为什么 v63 让它从"冻结"变成"发散" —— v63 是对的, 不是 v63 改坏了】
#   v60 曾把 intrinsicContentSize 的**高度**也改成 noIntrinsicMetric(只为治宽度
#   污染)。对宽度成立, 但高度正是 iOS 15 唯一的内容尺寸更新信号源 ⇒ hosting
#   view 高度恒为"无" ⇒ 播种值永远是死的 0 ⇒ 环转不起来, 但高度也永远
#   锁死在旧值(v53/v62 看到的就是这个"稳定")。
#   v63(V63-INTSIZE)恢复了高度上报 —— 这是**必须保留的正确修复**
#   (iOS 15 感知 SwiftUI 内容尺寸变化的唯一通道就是 intrinsicContentSize +
#   invalidateIntrinsicContentSize)。恢复之后播种值从"死的 0"变成"活的膨胀值",
#   自激环第一次真正跑起来。
#   ⇒ 病不是 v63 引入的, 是 v63 让一个存在了 30 余版的底层 bug 显形。
#
# 【v64 做什么 —— 一行切断自我播种】
#   把 :561 的播种值从"上一轮的 attrs.size.height"改成"不播种"
#   (height = UIView.layoutFittingCompressedSize.height, 与 :531 的声明一致),
#   让 systemLayoutSizeFitting 只能从内容重算, 拿不到上一轮的答案。
#
#   顺带把 :718 之前补一道**收敛闸**: 若重算结果仍 ≥ 上一轮 est(说明 iOS 15
#   的 SwiftUI 还是把旧值赢了回来), 就不许再往上加, 保留上一轮值 ——
#   这是对 iOS 15 行为不确定时的兜底, 宁可暂时少报也不无限发散。
#   真实内容变高时 TextKit 那一路(_ios15TkSum)仍会给出权威的、更大的值,
#   闸门放行(条件是 est 未变 + Tk 实测更大), 不会误杀真实增长。
#
# 【为什么不用「限流」而用「断反馈」】限流/幂等锁是在**症状层**打补丁:
#   它假设"重排太频繁", 于是限制重排次数。但真正的问题是**每次重排的输入
#   里混进了上一次的结果** ⇒ 就算只重排一次, 那一次也可能返回一个偏大的值,
#   而这个偏大的值会永久留在缓存里。断掉反馈, 一次都不需要限。
#   (v64 初版就是限流思路的产物, 被上面 6 拍时间戳证伪, 已整体推翻。)

# ---- 锚点: 播种行(infrastructure 侧, 全文唯一) ----
V64_SEED_OLD = """        var fittingSize = CGSize(width: targetSize.width, height: attrs.size.height)"""

V64_SEED_NEW = """        // [V64-DESEED] 不播种 —— 切断「测量自激」的自我反馈。
        //
        // 【为什么必须】上一行 `targetSize` 声明了
        // `verticalFittingPriority: .fittingSizeLevel`(压缩语义 = 从内容重算),
        // 这里却把 super 刚返回的、**已经膨胀过**的 `attrs.size.height` 当作
        // 测量初值喂回去。iOS 16+ 上 SwiftUI 遵守压缩优先级, 无害;
        // iOS 15 上不遵守, 播种值胜出 ⇒ 写进 lastComputedHeight/heightCache
        // ⇒ 下一轮 UIKit 把这个值当 est 递回来(实测严格相等:
        // est_{n+1} == pref_n) ⇒ 再播种 ⇒ H_{n+1} = H_n + 170 发散。
        //
        // 【装机铁证】idx=9 六拍, delta 恒 +144~+205,
        // 11:07:52.403 → 53.981 全在 1.58s 内, 形态是单调累加、只涨不跌。
        // 20pt 行高下 170pt ≈ 8~9 行, 与 storageLen=851 的表格消息吻合。
        //
        // 【v60/v63 的关系】v60 把 intrinsicContentSize 高度也清成
        // noIntrinsicMetric, 于是播种值恒为死的 0, 环转不起来 —— 代价是高度
        // 永远锁死(v53/v62 看到的"稳定")。v63 恢复高度上报是**必须保留的
        // 正确修复**(iOS 15 感知 SwiftUI 内容尺寸变化的唯一通道), 恢复后
        // 播种值变"活", 这个存在了 30 余版的底层 bug 才显形。
        // ⇒ 本条只断反馈, 不动 v63 的高度上报。
        //
        // 【为什么不锁 invalidate 次数】限流是症状层补丁: 它假设"重排太频繁",
        // 于是数次数。但病根是"每次重排的输入里混进了上一次的输出" ⇒
        // 就算只重排一次, 那一次也可能返回偏大的值并永久留在缓存里。
        // 断反馈, 一次都不需要限。
        var fittingSize = CGSize(width: targetSize.width,
                                 height: UIView.layoutFittingCompressedSize.height)"""

# ---- 锚点: 收敛闸(必须紧跟 reconcile 之后、写回 lastComputedHeight 之前) ----
V64_GATE_OLD = """        fittingSize.height = _ios15Reconciled
        attrs.size.height = fittingSize.height"""

V64_GATE_NEW = """        // [V64-CONVERGE] 收敛闸 —— 断掉反馈之后的兜底。
        //
        // 断掉播种后, 理论上 `fittingSize.height` 只能由内容决定。但 iOS 15
        // 的 SwiftUI 是否真的遵守 .fittingSizeLevel 无法在编译期确认 ——
        // 若它仍把上一轮的值赢回来, 累加会**换一条路复发**。
        //
        // 【判据】重算结果 ≥ 上一轮 est, 且宽度没变 ⇒ 判定为"没真的重算,
        //   只是把旧值带了回来"。此时**保留 est**, 不许再往上加。
        //   累加的数学结构(H → H+170)在这里被直接截断: 不加就不发散。
        //
        // 【为什么不会误杀真实增长】真实内容变高时, 权威测量是 TextKit 那一路
        // (`_ios15TkSum`, 来自 SelectableMarkdownTextView.lastComputedHeight,
        // 是 sizeThatFits 的实测值)。闸门只在上报值 ≥ est 时收紧; 若 Tk 实测
        // 确实更高, `_ios15Reconciled` 会高于 est, 但那说明 SwiftUI 这次**真的
        // 重算了**(est 已被重算结果取代) —— 所以判据里再要求
        // 「Tk 实测没有超出 est」, 只有"两边都没给出更新的信息"才拦。
        let _v64est = attrs.size.height
        let _v64tk = _ios15TkSum
        let _v64grew = _ios15Reconciled >= _v64est - 0.5
        let _v64tkFresh = _ios15Found && _v64tk > _v64est + 0.5
        if _v64grew && !_v64tkFresh, _v64est > 4 {
            Self.sizingLogger.info("[CellSizing][V64-CONVERGE] hold est=\\(String(format: "%.1f", _v64est)) recomputed=\\(String(format: "%.1f", _ios15Reconciled)) tk=\\(String(format: "%.1f", _v64tk)) — 未真重算, 保留 est 阻断累加")
            _ios15Reconciled = _v64est
        }
        fittingSize.height = _ios15Reconciled
        attrs.size.height = fittingSize.height"""


def fix_deseed_v64_infra(t):
    """v64 注入: 切断 preferredLayoutAttributesFitting 的「自我播种」。

    这是 v64 的全部内容 —— 两条, 都在 SelfSizingCell 一个函数里:
      ① V64-DESEED  播种值不取上一轮结果(与 targetSize 的压缩语义对齐)
      ② V64-CONVERGE 收敛闸: 重算值没真重算(=只是旧值回来)就保留 est

    幂等: 已有 [V64-DESEED] 原样返回。锚点计数防呆。

    【为什么放在这里而不是下游】下游(v53/v62/v63 的短路、v61 单调锁、
      v31 翻转锁)全都在**症状层**: 它们限制"改几次"或"往哪个方向改"。
      但 H_{n+1} = H_n + 170 的病根是"输入里混进了上一次的输出" ——
      只要 est 仍是我们写回缓存的那个值, 无论下游怎么限, 下一轮都从
      被污染的起点出发。**必须回到 self-sizing 的测量入口断开反馈。**

    【为什么不用 v64 初版的「同宽幂等锁」】初版假设"重排太频繁", 用
      0.35s 时间窗拦同宽重复 settle。装机时间戳把它证伪了: 6 拍间隔
      0.183/0.192/0.392/0.212/0.599s, 0.35s 窗只能拦下 3 拍, 剩下 3 拍
      照样累加 ⇒ 累加幅度不减, 病不治。而且那把锁是全局单例, 列表里多个
      同宽 cell 会互相冻结 ⇒ 内容截断, 比抖动更糟。已整体推翻。
    """
    if "[V64-DESEED]" in t:
        return t
    t = _v60_replace1(t, V64_SEED_OLD, V64_SEED_NEW, "v64 去播种(断自我反馈)")
    t = _v60_replace1(t, V64_GATE_OLD, V64_GATE_NEW, "v64 收敛闸(阻断累加)")
    return t


def fix_intrinsic_size_v63_md(t):
    """v63 注入③: SelectableMarkdownTextView.intrinsicContentSize 恢复高度上报。

    幂等: 已有 [V63-INTSIZE] 原样返回。
    """
    if "[V63-INTSIZE]" in t:
        return t
    t = _v60_replace1(t, V63_INTSIZE_OLD, V63_INTSIZE_NEW, "v63 intrinsic 高度恢复")
    return t


def verify_intrinsic_gate_v63(compat, md):
    """v63 判据①: iOS15Compat.swift + SelectableMarkdownView.swift。

    六层: 探针 / 世代号 / fast路径判等 / invalidate / intrinsic 高度 /
    探针真的会被调用(声明早于使用)。
    """
    F = "verify_intrinsic_gate_v63"
    # ① 探针与世代号字段
    # ★计数器锚点已从 `_v63FastHit: UInt = 0` 改为 `static var fastHit: UInt = 0`:
    #   run#157 实测 —— 泛型类型里的 static 存储属性编译期就被拒, 计数器必须
    #   住在非泛型的 _V63Probe 上。锚点跟着代码走, 不跟着历史名字走。
    for key in ("_v63ConfigGen: UInt = 0", "_ios15ApplyGen: UInt = 0",
                "static var fastHit: UInt = 0", "static var rebuildHit: UInt = 0",
                "[V63-PROBE] fast="):
        if key not in compat:
            raise RuntimeError("%s: 探针/世代号字段缺失 %r" % (F, key))
    # ② apply 入口必须自增世代号, 且**早于** fast path 判等
    #
    # 【锚点教训: 别拿注释当锚点】本判据原先用 `[V63-UPDATE]` 注释行起算
    # 切片窗口, 而身份判等写在**上一行**的 `if let` 条件里 —— 注释在代码
    # 之后, 于是判据在自己写的窗口外找自己要的东西, 报了个"注入缺失"的
    # 假红(注入明明在, 阶段④落点核对也全绿)。纪律第 3 条要求先计数锁死
    # 集合再取位置, 这里进一步要求: **锚点必须选代码结构, 不选注释**,
    # 否则重排注释就翻脸。锚点改为 `if let existing = host`, 它才是
    # fast path 的真正入口, 且在产物里唯一(计数已断言)。
    ANCHOR = "if let existing = host"
    if compat.count(ANCHOR) != 1:
        raise RuntimeError(
            "%s: fast path 锚点 %r 出现 %d 次(应恰好 1 次) —— 判据无法定位"
            % (F, ANCHOR, compat.count(ANCHOR)))
    i_fast = compat.find(ANCHOR)
    i_inc = compat.find("_ios15ApplyGen &+= 1")
    i_apply = compat.find("private func apply(")
    if not (0 < i_apply < i_inc < i_fast):
        raise RuntimeError(
            "%s: 世代号自增必须在 apply 入口且**早于** fast path 判等 —— "
            "否则判等读到的是上一轮的值, 快速路径永不命中" % F)
    # ③ fast path 的 `if let` 条件行内必须含 config 身份判等
    #    窗口从锚点起算(不是从注释起算), 覆盖整个 fast path 代码块
    seg = compat[i_fast:i_fast + 1200]
    i_guard = seg.find(ANCHOR)
    i_line_end = seg.find("\n", i_guard)
    cond_line = seg[i_guard:i_line_end]
    if "_v63ConfigGen == _ios15ApplyGen" not in cond_line:
        raise RuntimeError(
            "%s: fast path 的 if let 条件缺 config 身份判等(该行实际是 %r) —— "
            "只判 host != nil 会拿上一个消息的 host 去就地刷 rootView"
            "(跨消息用错测量状态)" % (F, cond_line.strip()))
    # ④ invalidateIntrinsicContentSize 必须存在, 且排在 rootView 赋值**之后**
    #    ★分两种文案(纪律第 5 条: 输出文案本身是判据): 「整条缺失」是病根
    #    形态(v60 把它连高度一起关了, iOS 15 唯一信号源被切断);
    #    「在但顺序错」是接线形态。两种病不能用同一句话报, 否则日志无法分辨。
    i_root = seg.find("existing.rootView =")
    i_inv = seg.find("existing.view.invalidateIntrinsicContentSize()")
    if i_inv < 0:
        raise RuntimeError(
            "%s: fast path 里没有 invalidateIntrinsicContentSize() —— 这是 iOS 15 "
            "感知 SwiftUI 内容变化的**唯一**通道(iOS 16 才有 sizingOptions)。"
            "缺它 ⇒ UIKit 收不到变化信号 ⇒ 高度锁死旧值 ⇒ 「一下跳出一大段」。"
            "setNeedsLayout/layoutIfNeeded 都替代不了(StackOverflow 77027194)。" % F)
    if not (0 <= i_root < i_inv):
        raise RuntimeError(
            "%s: invalidateIntrinsicContentSize 排在 rootView 赋值之前 —— "
            "此时 SwiftUI 内容还没换, 通知的是旧尺寸, 等于没通知" % F)
    # ⑤ 重建路径必须记身份戳
    if "_v63ConfigGen = _ios15ApplyGen" not in compat:
        raise RuntimeError(
            "%s: 重建路径缺身份戳 —— 走重建后 fast path 会误判 host 仍可用" % F)
    # ⑥ intrinsicContentSize 必须恢复高度上报
    if "[V63-INTSIZE]" not in md:
        raise RuntimeError("%s: intrinsicContentSize 未恢复高度上报" % F)
    i_int = md.find("[V63-INTSIZE] 恢复**高度**上报")
    if i_int < 0:
        raise RuntimeError("%s: V63-INTSIZE 标记缺失" % F)
    # 宽必须仍是 noIntrinsicMetric(宽污染由 v60 sane 链治, 不在此处放开)
    seg2 = md[i_int - 900:i_int + 2200]
    if "return CGSize(width: UIView.noIntrinsicMetric, height: ceil(fit.height))" not in seg2:
        raise RuntimeError(
            "%s: intrinsic 宽必须保持 noIntrinsicMetric —— 放开宽会让 100032 "
            "污染宽从这条通道回潮(v21/v60 花了几十版才钉住)" % F)
    return True


def verify_swift_static_v63(compat):
    """v63 判据⑦(语法级): 泛型类型里不得有 static 存储属性。

    ★★ 这条判据是 run#157 逼出来的。v63 全链 33/0/0 全绿, 判据只验
    「标记在位」, 没有一条验「Swift 语法合法」, 于是
    `private static var` 落在 `private final class _HostingContentCellView
    <Content: View>` 里 —— Swift 硬错误:
        error: static stored properties not supported in generic types
    Release 编译 exit 65, 前面 66 条断言全绿也没用。

    ⇒ 文本判据的体系性盲区: 能证明「改到位」, 证明不了「能编译」。
    这条判据把「编译能过」里最容易被注入代码破坏的那一类提前到秒级。

    覆盖: ① 泛型类型扫 static 存储属性 ② 探针计数必须住在非泛型宿主
         ③ 带反证的 sabotage(把计数器塞回泛型里必须被抓)。
    """
    F = "verify_swift_static_v63"
    import re as _re
    # ① 扫出所有泛型类型声明, 检查其体内有无 **存储形式**的 static 属性
    #
    # ★★ 误报教训(第一次写这条判据时就踩了): Swift 禁止的是
    #   `static stored properties`(存储属性), **computed property 不算**。
    #   产物里本来就有合法的一处:
    #       private struct IOS15GeometryValueKey<T: Equatable>: PreferenceKey {
    #           static var defaultValue: T? { nil }        ← computed, 合法
    #           static func reduce(...)                      ← 方法, 不在范围内
    #       }
    #   初版正则只匹配 `static var` 开头, 把它误判成违规 —— 而它编译一直通过。
    #   ⇒ 判据宁可漏报不可误报(纪律第 14 条): 存储属性必然带 `=` 初始化,
    #     computed property 必然带 `{` 实现体。按 `=` 判, 零误报。
    gen_re = _re.compile(
        r"(?:final\s+class|class|struct)\s+(\w+)\s*<[^>]*>\s*(?::[^{]*)?\{")
    bad = []
    for m in gen_re.finditer(compat):
        name = m.group(1)
        # 从 '{' 起做花括号配平, 取出类型体
        i = compat.index("{", m.start())
        depth, j = 0, i
        while j < len(compat):
            if compat[j] == "{":
                depth += 1
            elif compat[j] == "}":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        body = compat[i + 1:j]
        # 存储属性: `static var/let NAME[: Type] =`  (等号在行内, 非 {)
        for sm in _re.finditer(
                r"^\s*(?:public\s+|private\s+|fileprivate\s+|internal\s+)?"
                r"static\s+(?:var|let)\s+(\w+)[^=\n]*=", body, _re.M):
            bad.append("%s.%s (第 %d 行)"
                       % (name, sm.group(1), compat[:i + 1 + sm.start()].count("\n") + 1))
    if bad:
        raise RuntimeError(
            "%s: 泛型类型里出现 static 存储属性 %s —— Swift 编译期硬拒"
            "(static stored properties not supported in generic types), "
            "Release 编译必失败。静态计数器请搬到非泛型宿主类型上。"
            "★这条判据是 run#157 的直接产物。" % (F, "; ".join(bad)))
    # ② 探针计数器的家必须非泛型, 且**计数器本体必须真的在里面**。
    # ★S17 漏过一次的教训: 只查「宿主类型在不在」不够 —— 宿主在、字段被摘
    #   一样能通过, 那就又变成「空测被当成通过」(run#156 同款病根)。
    #   所以这里逐个字段确认, 且要求三个都在。
    if "private final class _V63Probe" not in compat:
        raise RuntimeError(
            "%s: 找不到非泛型探针宿主 _V63Probe —— 计数器必须有合法的落脚点" % F)
    if "_V63Probe<" in compat:
        raise RuntimeError(
            "%s: _V63Probe 竟被写成泛型 —— 那就把 static 存储属性又装回去了" % F)
    i_probe = compat.find("private final class _V63Probe {")
    if i_probe < 0:
        raise RuntimeError("%s: 探针宿主声明形态不符(需 `private final class _V63Probe {`)" % F)
    j_probe = compat.index("{", i_probe)
    depth, k = 0, j_probe
    while k < len(compat):
        if compat[k] == "{":
            depth += 1
        elif compat[k] == "}":
            depth -= 1
            if depth == 0:
                break
        k += 1
    probe_body = compat[j_probe + 1:k]
    for field in ("static var fastHit: UInt = 0",
                  "static var rebuildHit: UInt = 0"):
        if field not in probe_body:
            raise RuntimeError(
                "%s: 探针宿主里缺 %r —— 计数器被摘掉后探针会永远不打日志, "
                "而「零输出」正是 v53/v62 连续两版被忽略的那个信号"
                % (F, field))
    return True


# ---- D: v63 打破循环依赖(渲染层) ----
V63_UNCYCLE_OLD = """        let _v62oversized = _cellH > 1 && _need > 1 && (_cellH - _need) > 40
        guard deferredCorrectionPending || _stillOwing || _v62oversized else { return }"""

V63_UNCYCLE_NEW = """        let _v62oversized = _cellH > 1 && _need > 1 && (_cellH - _need) > 40
        // [V63-UNCYCLE] 打破 v53/v62 的循环依赖, 让「第二拍」真的能到来。
        //
        // 【实测铁证】装机日志 debt= 唯一取值 {0.0}, live= 唯一取值 {0}:
        //   debt 只在本函数(settle 时刻)上报, 而本函数的 guard 又依赖欠账
        //   是否成立 ⇒ 要放行测量需 debt 熟, debt 熟需 settle, settle 需先
        //   放行测量 —— 环。v53DebtSeenCount 因此永远停在 1, 第二拍从未到来,
        //   三条短路永远命中 ⇒ 高度锁死旧值(798→903→1057→1205→1336→1518,
        //   6 次全 cached=true)。
        //
        // 【本条做什么】_v63drift 不看 debt 计数, 只看**当前 cell 高与真实
        // 测量之差**是否够大(>8pt, 8 = 排除行高/间距级噪声)。够大就直接
        // 放行, 不等计数成熟。根因 A(V63-INTSIZE/V63-UPDATE)把 invalidate
        // 通道修好后, 这里再给一把不依赖计数的兜底 —— 双管齐下。
        // 阈值 8pt 故意小于 v61-MONO 的 8pt 容差同量级: 只拦"真的差很多"。
        let _v63drift = _cellH > 1 && _need > 1 && abs(_cellH - _need) > 8
        guard deferredCorrectionPending || _stillOwing || _v62oversized || _v63drift else { return }"""


def fix_uncouple_v63_md(t):
    """v63 注入②: SelectableMarkdownView.swift settle 入口加 _v63drift 直放行。"""
    if "[V63-UNCYCLE]" in t:
        return t
    return _v60_replace1(t, V63_UNCYCLE_OLD, V63_UNCYCLE_NEW, "v63 打破循环依赖")


def verify_uncouple_v63(md):
    """v63 判据②: settle 入口。

    四层: drift 定义 / guard 引用 / 阈值合理 / 不依赖 debt 计数。
    """
    F = "verify_uncouple_v63"
    if "[V63-UNCYCLE]" not in md:
        raise RuntimeError("%s: settle 入口未注入 _v63drift" % F)
    i = md.find("[V63-UNCYCLE] 打破")
    if i < 0:
        raise RuntimeError("%s: V63-UNCYCLE 标记缺失" % F)
    seg = md[i:i + 1800]
    # ① drift 必须按**实测差值**判定, 且带噪声容差
    if "let _v63drift = _cellH > 1 && _need > 1 && abs(_cellH - _need) > 8" not in seg:
        raise RuntimeError(
            "%s: _v63drift 未按实测差值判定(须 abs(cellH-need) > 8 排除行高噪声)"
            % F)
    # ② guard 必须引用它, 否则声明了也不生效(= v53 当年的"声明未接线")
    if "|| _v63drift else { return }" not in seg:
        raise RuntimeError(
            "%s: guard 未引用 _v63drift —— 声明了但没接线, 等于没改"
            "(verify-discipline 第 13 条: 查数据流要连声明一起查)" % F)
    # ③ 反向纪律: 不得改回依赖 debt 计数(那正是循环依赖的源头)
    if "v53DebtIsRipe &&" in seg or "_v63drift &&" in seg:
        raise RuntimeError(
            "%s: _v63drift 不得再与 debt 计数绑定 —— 那会把循环依赖引回来" % F)
    return True


def _v64_body(t, start_marker, what):
    """取出 `start_marker` 所在语句起的花括号块(按配平)。

    ★为什么必须按配平取而不是按固定行数(判据纪律第 6 条: 锚点选代码结构):
    固定行数会随上游注释长度漂移 —— 上游加一段注释, 判据就切错了地方,
    然后"锚点还在"判据全绿, 实际检查的是别的东西。run#156 的锚点腐化
    就是这么发生的。
    """
    i = t.find(start_marker)
    if i < 0:
        raise RuntimeError("v64: %s 缺失(找不到起点 %r)" % (what, start_marker[:60]))
    j = t.find("{", i)
    if j < 0:
        raise RuntimeError("v64: %s 起点之后没有 '{' —— 锚点可能指错语句" % what)
    depth = 0
    for k in range(j, len(t)):
        if t[k] == "{":
            depth += 1
        elif t[k] == "}":
            depth -= 1
            if depth == 0:
                return t[i:k + 1]
    raise RuntimeError("v64: %s 的花括号不配平(注入被截断?)" % what)


def verify_deseed_v64(infra):
    """v64 判据: 切断 self-sizing 的「自我播种」+ 收敛闸。

    ★本判据的定位与前 63 版不同 —— 它必须能区分这两种情况:
        (A) 播种值真的不再取上一轮结果
        (B) 注释写着"不播种", 代码却还在取
      v64 初版就是因为判据只查"标记在位", 才让一把**被时间戳证伪的锁**
      带着 9 条绿灯过了 CI。所以这里的每一层都查**表达式与数据流**,
      不查标记。

    四层:
      ① 去播种: 播种语句的高不得再来自 attrs.size.height, 且必须用
         layoutFittingCompressedSize(与 targetSize 的压缩语义一致)
      ② 收敛闸在位, 且真的改写 _ios15Reconciled(不是只打印)
      ③ 收敛闸不会误杀真实增长 —— 必须存在"Tk 实测更大则放行"的分支
      ④ 数据流: 闸门必须在 lastComputedHeight 写回**之前**, 否则拦了也白拦
    """
    F = "MessageListInfrastructure.swift"

    # ── 前置: 断言函数签名与调用点存在, 否则下面全部空跑 ──
    if "func verify_deseed_v64(" not in open(__file__, encoding="utf-8").read():
        raise RuntimeError("verify_deseed_v64: 自检失败, 判据未定义")

    # ⓪ 目标函数必须在
    if "override func preferredLayoutAttributesFitting(" not in infra:
        raise RuntimeError(
            "%s: 找不到 preferredLayoutAttributesFitting —— v64 全部改动都落在"
            "这个函数里, 它不在就说明注入点漂了" % F)

    # ── ① 去播种: 查表达式实质, 不查标记 ──
    seed = _v64_body(infra, "var fittingSize = CGSize(", "播种语句")
    if "attrs.size.height" in seed:
        raise RuntimeError(
            "%s: 播种语句仍取 attrs.size.height(上一轮的结果) —— 这就是自激环"
            "本身。H_{n+1} = H_n + 170 的递推没被切断" % F)
    if "UIView.layoutFittingCompressedSize.height" not in seed:
        raise RuntimeError(
            "%s: 播种语句未用 layoutFittingCompressedSize.height —— 与 targetSize"
            "声明的压缩语义不一致, 仍可能被上一轮值污染" % F)
    # 反向纪律: 不得改回任何"取上一轮高度"的写法(换个名字也不行)
    for bad in ("lastComputedHeight", "attrs.height", "_ios15Reconciled",
                "fittingSize.height"):
        if bad in seed:
            raise RuntimeError(
                "%s: 播种语句引用了 %r —— 任何来自上一轮结果的值都会让环续上"
                % (F, bad))

    # ── ② 收敛闸在位且真的改写 ──
    if "[V64-CONVERGE]" not in infra:
        raise RuntimeError(
            "%s: 收敛闸缺失 —— 断掉播种只是去掉反馈通道, 若 iOS 15 的 SwiftUI "
            "仍把旧值赢回来, 累加会换一条路复发。闸门是必要的兜底" % F)
    gate = _v64_body(infra, "let _v64est = attrs.size.height", "收敛闸")
    if "_ios15Reconciled = _v64est" not in gate:
        raise RuntimeError(
            "%s: 收敛闸只计算不改写 _ios15Reconciled —— 算出来不用等于没拦"
            "(判据纪律第 13 条: 查数据流要连声明一起查)" % F)
    # 闸门必须真的以"没重算"为条件, 而不是无条件保留 est
    if "_v64grew && !_v64tkFresh" not in gate:
        raise RuntimeError(
            "%s: 收敛闸的触发条件缺失 —— 必须要求「重算值≥est」且「Tk 没有更新"
            "的实测」才拦, 否则会把真实增长也一起拦掉" % F)

    # ── ③ est 下限: 近零高度是"未测量"而非"已测量" ──
    # ★不要在这里叠「看形状像无条件」的正则 —— 上一版叠了, 结果它对正确的
    #   注入也报错(对缩进的假设不成立), 判据把自己的基线判红了。教训同
    #   run#156: 判据自身误报比没有判据更贵, 会让人开始不信判据。
    #   无条件形态由 reverse_v64 的 S3 专门覆盖(那才是它的正确位置)。
    if "_v64est > 4" not in gate:
        raise RuntimeError(
            "%s: 收敛闸缺 est > 4 的下限 —— 近零高度是\"未测量\"而非\"已测量\", "
            "拿它当基线会把首帧锁成 0" % F)

    # ── ④ 数据流: 闸门必须在写回缓存之前(S8) ──
    # ★必须比偏移量, 不能只查"都在这个文件里"。两处都在, 顺序错了闸门
    #   就是装饰品 —— 而这正是 v64 初版判据的盲区(只问在不在, 不问对不对)。
    gi = infra.find("let _v64est = attrs.size.height")
    ci = infra.find("lastComputedHeight = fittingSize.height")
    if gi < 0 or ci < 0:
        raise RuntimeError("%s: 找不到写回点 lastComputedHeight" % F)
    if gi > ci:
        raise RuntimeError(
            "%s: 收敛闸(偏移 %d) 在写回 lastComputedHeight(偏移 %d) **之后** —— "
            "拦下的值不会被采纳, 闸门形同虚设(这正是 v64 初版判据放过的那类"
            "形态: 东西都在位, 但顺序让它不生效)" % (F, gi, ci))

    # ── ⑤ ★标识符必须真实存在(run#159 的直接产物) ──
    # run#159 编译红: `cannot find '_v64found' in scope` —— 收敛闸引用了
    # 一个**不存在**的标识符(真名是 _ios15Found)。本地 35 条判据全绿,
    # 因为它们只查文本「在不在」, 查不出「引用的东西存不存在」。
    # ⇒ 这里逐个核对闸门引用的外部标识符在产物里真有定义。
    #   范围只限闸门自己引入的 4 个(_v64est/_v64tk/_v64grew/_v64tkFresh)
    #   加上它引用的 2 个上游量(_ios15Reconciled/_ios15TkSum/_ios15Found)。
    for ident in ("_v64est", "_v64tk", "_v64grew", "_v64tkFresh",
                  "_ios15Reconciled", "_ios15TkSum", "_ios15Found"):
        # 声明行(let/var X = ...)才算定义; 纯引用不算
        if not re.search(r"\b(?:let|var)\s+%s\b" % re.escape(ident), infra):
            raise RuntimeError(
                "%s: 收敛闸引用的 %r 在产物里**没有声明** —— 编译期必然报 "
                "`cannot find in scope`。这就是 run#159 的那一个错误: "
                "判据全绿而编译红(判据只验文本, 验不了标识符是否存在)"
                % (F, ident))
    # 反向: 闸门里不得出现未声明的 _v64* 变量(防新增时重犯)
    declared = set(re.findall(r"\b(?:let|var)\s+(_v64\w+)", gate))
    used = set(re.findall(r"\b(_v64\w+)", gate))
    unknown = used - declared
    if unknown:
        raise RuntimeError(
            "%s: 收敛闸用了未在其内部声明的 %s —— 未定义标识符, 编译必红"
            % (F, sorted(unknown)))

    # 且必须落在 reconcile 之后(闸门要比较的是 reconcile 后的值)
    ri = infra.find("var _ios15Reconciled = fittingSize.height")
    if ri < 0 or gi < ri:
        raise RuntimeError(
            "%s: 收敛闸必须紧跟 reconcile(_ios15Reconciled 的赋值)之后, "
            "否则它比较的是 reconcile 前的中间值" % F)
    return True


def fix_kvo_debt_v569(t):
    """v56.9: 修 KVO 同值抑制把欠账帧永久跳过。

    ★根因来自装机日志: 95 条 [V56-KVO] 全是 skipSame, 零条 fixed,
      其中 13 条 svH < needH —— 几何确实欠着却被抑制分支跳过。
      而 skipSame 分支只改局部副本 f, **不写 obj.frame**,
      几何不变 ⇒ KVO 不再触发 ⇒ 欠账永久凝固 ⇒ 「定时任务」那行只剩上半。
    """
    if "[V569-DEBT]" in t:
        return t

    if V569_SKIP_OLD not in t:
        raise RuntimeError(
            "fix_kvo_debt_v569: skipSame 分支锚点没找到 —— "
            "v56.1 的同值抑制代码结构可能变了。"
            "★别先怀疑上游: 这个分支是我们自己注入的, "
            "直接 grep 产物里的 `_v56dup` 看现状")

    return t.replace(V569_SKIP_OLD, V569_SKIP_NEW, 1)


def verify_kvo_debt_v569(t):
    """v56.9 判据: 同值抑制必须以「几何已达标」为前提。

    四层:
      1. **范围**: [V569-DEBT] 标记在位。
      2. **核心**: 抑制条件里必须有几何判据 `_v56noDebt`,
         且它必须由 `f.size.height + 0.5 >= _v42Need` 算出来
         —— 不是别的东西。
      3. **抑制条件真的带上它**: `if _v56dup && _v56noDebt` 必须逐字在。
         ★只声明 _v56noDebt 而不接进 if 是**本版最危险的形态**:
         看着像修了, 行为完全没变 ⇒ 判据必须查 if 那一行本身。
      4. **没顺手删掉抑制本意**: `skipSame` 的 NSLog 与
         `_V56KVOW.skipped &+= 1` 都必须在。抑制本身是有价值的优化
         (省掉同 tick 内几何零变化的同步 layout), 删掉它等于
         把「省掉无谓写入」变成「每帧都写」, 是另一种退化。
    """
    tc = _v566_strip_comments_only(t)

    # 1. 范围
    n_mark = sum(1 for ln in t.split("\n") if "[V569-DEBT]" in ln)
    if n_mark < 1:
        raise RuntimeError(
            "verify_kvo_debt_v569: 找不到 [V569-DEBT] 标记 —— 注入没到位")

    # 2. 几何判据在位
    if "_v56noDebt" not in tc:
        raise RuntimeError(
            "verify_kvo_debt_v569: 没有 `_v56noDebt` —— 抑制条件仍然只看"
            "「值是否重复」不看「几何是否欠着」, 欠账帧会被永久跳过")

    # ★**整行相等**, 不是子串包含。
    #   踩坑记录(判据自己的第一版就是这么错的): 原来是
    #       if "f.size.height + 0.5 >= _v42Need" not in tc
    #   于是取反成 `... < _v42Need`(S3)、阈值写死成 `1000.0`(S4)
    #   **两条都还是那个子串**, 判据全绿放过。
    #   ⇒ 与 v566 S3「`= 400` 是 `= 4000` 的子串」完全同类, 同一纪律第三次适用。
    #   ⇒ 语义判据必须整行比对: 比较符方向、两个操作数, 都要对上。
    _no_debt_lines = [ln.strip() for ln in tc.split("\n")
                      if "_v56noDebt =" in ln]
    if not any(ln == "let _v56noDebt = f.size.height + 0.5 >= _v42Need"
               for ln in _no_debt_lines):
        raise RuntimeError(
            "verify_kvo_debt_v569: `_v56noDebt` 的定义行不是 "
            "`let _v56noDebt = f.size.height + 0.5 >= _v42Need` —— "
            "它必须整行逐字表达「当前高度已达 needH」这一个意思。"
            "★子串匹配会放过『比较符取反』与『阈值写死』两种改法")

    # 3. ★真的接进了 if 条件(防「声明了但没接线」)
    if "if _v56dup && _v56noDebt" not in tc:
        raise RuntimeError(
            "verify_kvo_debt_v569: 抑制条件仍是 `if _v56dup` —— "
            "几何判据算出来了却没接进 if。这是本版最危险的形态: "
            "代码看起来修了, 行为一字未变")

    # 4. 抑制本意没被删
    if "skipSame svH=" not in tc:
        raise RuntimeError(
            "verify_kvo_debt_v569: skipSame 的日志被删了 —— "
            "抑制分支本身必须保留(见 verify 第4层说明)")

    if "_V56KVOW.skipped &+= 1" not in tc:
        raise RuntimeError(
            "verify_kvo_debt_v569: `_V56KVOW.skipped` 计数被删了 —— "
            "抑制分支的本体被掏空了, 本版只该改**条件**, 不该删**分支**")

    return True

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
    # [幂等·纪律 51/52] 必须在**任何注入动作之前**检查, 且用**产物标记**。
    # 本函数原先把判据放在注入点之后 ⇒ 第二次运行时第一处已又插了一份,
    # verify 的「标记数==1」断言报成「实际 2」—— 报错文案指向错误方向。
    if '// [V47-REWRAP]' in t:
        return t

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
    # [幂等·纪律 51/52] 必须在**任何注入动作之前**检查, 且用**产物标记**。
    # 本函数原先把判据放在注入点之后 ⇒ 第二次运行时第一处已又插了一份,
    # verify 的「标记数==1」断言报成「实际 2」—— 报错文案指向错误方向。
    if '// [V48-PIN]' in t:
        return t

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
    # ★★ 第五次翻版(v50, 本轮): 上面那个"改成 v49 探针起点"的修法**本身就是
    #   同一个错误的重演** —— 它把右界硬编码到一个**具体版本**的标记上。
    #   于是 v50 把 `TableAttachment.ios15PinnedW = _realW2` 插在
    #   V48-PIN 与 V49-WWRITER-V18 之间(那正是"钉宽同一处同一帧"的位置),
    #   判据立刻报:
    #       pure=BAD 赋值3处 违规=['TableAttachment.ios15PinnedW = _realW2', ...]
    #   而 v50 完全合规(它自己的三层判据 + 16 条 sabotage 全绿)。
    #
    #   ⇒ 根因不是"锚点选错了", 是**锚点选法错了**:
    #     每来一个新版本就得改一次判据, 改一次就漏一次
    #     —— v48→v49 一次、v49→v50 一次, 而 v47 判据那次甚至改了四处副本。
    #
    #   ⇒ 正确做法: 右界 = **V48-PIN 之后第一个版本号 > 48 的标记**,
    #     用正则现场扫, 不写死任何版本号。这样 v49/v50/v51… 无论插在
    #     钉宽 if 与 v28 标记之间的哪一处, 都会被自动切掉。
    #
    #   保留 v48 if 之后的空间仍然必要(反向测试 B11 要在那里追加合法读取
    #   来验证"判据不误伤", 收得太紧会把那条误判成破坏)。
    _m_next = re.search(r"//\s*\[V(?:49|[5-9]\d|\d{3,})[ \-\]]", t[i_pin + 10:])
    if _m_next:
        i_end = i_pin + 10 + _m_next.start()
    else:
        # 没有更高版本的标记(纯 v48 产物)⇒ 退回 v28 标记
        i_end = t.find("// [IOS15-FIX-RELC v28]", i_pin)
        if i_end < 0:
            raise RuntimeError(
                "verify_width_pin_v48: 未找到段尾锚点(既没有 V49+ 标记也没有"
                " // [IOS15-FIX-RELC v28]) —— v18 抢宽段结构变了, "
                "判据范围必须重新确定")
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
# ★★★ 指纹里的"排版宽"这一项, 本轮**连踩两次编译错误**, 终于删掉了。
#
#   【坑一】原打算记 `boundW`, 写成 `self.textContainer.bounds.width`
#     —— `NSTextContainer` 没有 `bounds`(那是 NSView 的 API)。
#     run#37139821021: error: value of type 'NSTextContainer'
#     has no member 'bounds'
#
#   【坑二】改用 `self.textContainer.lineFragmentWidth` ——
#     run#37141013946: error: value of type 'NSTextContainer'
#     has no member 'lineFragmentWidth'
#     ★ 我当时**没有查证就断言"它恰好就是那个东西"**。查 Apple 文档后:
#       NSTextContainer 的属性只有 size / exclusionPaths / lineBreakMode /
#       widthTracksTextView / heightTracksTextView / maximumNumberOfLines /
#       lineFragmentPadding / isSimpleRectangularTextContainer / layoutManager
#       —— **既没有 bounds, 也没有 lineFragmentWidth**。
#       `lineFragmentWidth` 属于 TextKit2 的 NSTextLayoutManager 一族。
#     ⇒ **两次都是同一类错误: 凭"听起来对"猜 API 名, 没查证。**
#       第一版我甚至在注释里把它论证得"比 bounds 更准"—— 论证得越自信,
#       错得越彻底。写注释不能代替查证。
#
#   【最终决定: 删掉这一项, 不再找替代】
#     判据里原本想问的是"碎片按哪个宽排的" —— 而这个语义**已经有来源**:
#     `laidW`(ios15LastLaidOutW, v47 注入并在 v48 判据里被验证过), 它记的
#     正是"上次重排时用的目标宽"。再加一个我无法在本地验证的 API 只会
#     继续骗人。log18 里 `tcH=2000.0` / `358x2000.0` 被熔 109 次那个疑问,
#     留给 v50 用"排版宽 vs 申报宽"的差值去量, 不在纯诊断版里赌 API。
#
#   ⇒ **纪律: 判据/探针里只允许出现编译器已验证存在的 API。**
#     本机没有 swiftc, 无法编译验证, 所以更要用"上游已在用的写法"或
#     官方文档, 而不是记忆。同一份文件里读容器宽一律 `textContainer.size`
#     —— 那是 40+ 处都在用的写法, 天然安全。

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
                            NSLog("[V49-WWRITER] v18W=%.1f kvoW=%.1f cvW=%.1f laidW=%.1f tcH=%.1f sameTick=%d dtick=%d usedH=%.1f needH=%.1f len=%d n=%u",
                                  _V49W.v18W, _V49W.kvoW,
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
    # [幂等] 必须放在**函数开头**, 不能放在注入点之间: v49 有两个注入点,
    # 判据若在注入点 1 之后才检查, 第二次运行时注入点 1 已经又插了一份。
    # 纪律 51: 幂等判据一律用**产物标记**, 且位置必须在任何注入动作之前。
    if 'NSLog("[V49-WWRITER]' in t:
        return t

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
    _need = ("v18W=", "kvoW=", "cvW=", "laidW=", "tcH=",
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


# ============================================================================
# v50: 排版宽与测高宽同源 —— 治「滑动时字卡住/字在动」
# ============================================================================


MSG_V50_A = (
    "v50-A': 排版宽与测高宽同源 — 治「滑动时字卡住/字在动」。"
    "v49 探针归因(minis-2026-10-04 2.log, 143 条 V49-WWRITER): "
    "**v48 的钉宽没有错** —— v18W=358 **143/143 零例外**, "
    "kvoW=390 138/143 且 sameTick=0/dtick=1(下一 tick 就被推翻); "
    "V41-KVOPRE 的 sv 宽 **358 零例外** ⇒ _realW=min(358,390)=358 算得完全正确。"
    "真凶是**排版链与测高链宽度源不同**: V43-WIDTH 的 netW=**358(147/147 零例外)** "
    "而 dirtyW=390(131) ⇒ 测高链每帧都对、排版链每帧拿到脏宽。"
    "389 的来源精确到算式(SelectableMarkdownView.swift:2232 "
    "usableWidth = floor(lineFrag.width) - 1 = floor(390)-1), "
    "逐毫秒证据 .090 tcW=358 → .091 V46-ATTACH cachedW=389 tcW=390 —— "
    "**1 毫秒内被推翻**。机制是自我强化的环: lineFrag.width 由 UIKit 合成, "
    "读的是**当前** textContainer 宽, 而 v18 钉宽写在 layoutSubviews 内、"
    "**时序上晚于** UIKit 问宽度 ⇒ attachment 每次拿到的都是没钉的 390 ⇒ "
    "按 389 排版并 persist ⇒ 碎片按 389 而 needH 按 358 ⇒ gap 75pt 空壳"
    "(tcW=358 时 gap 仅 8.2) ⇒ tcW 被重排回 390 ⇒ 回到起点。"
    "**v46 当年把 D2「探针宽度不同源」排除掉了**(理由: cachedW 与 tcW 恒差 1.0, "
    "不像陈旧值)—— 那是误判: 恒定 1.0 差不是无害的舍入噪声, 那个 -1 是 UIKit 防 "
    "_fillLayoutHole 的**既有约定**(必须保留), 而 w 本身是脏宽; "
    "差 1.0 恰恰掩盖了「整个宽度口径都是错的」这个事实。"
    "⇒ 纪律: 排除候选根因时,「看起来无害的特征」恰恰最可能是伪装。"
    "修法: v18 段算出 _realW2 后**在同一处同一帧**把净宽写进 "
    "TableAttachment.ios15PinnedW(进程级 nonisolated(unsafe) static, "
    "与既有 narrowestRealWidth 同构 —— 那是本类里跨实例共享宽度口径的既有先例), "
    "attachmentBounds 的 usableWidth 优先取它。"
    "★只换「谁来提供 w」, **不动 floor(w)-1 那个约定本身**。"
    "三条红线: "
    "R1 probe 路径(lineFrag>=100_000)完全不走新口径(否则 "
    "[ios_session_open_last_cell_occluded] 的末行被裁修复回退) —— "
    "且判据查的是**数据流**(读通道那一行必须被 probe 条件夹住): "
    "第一版只查「probe 判定在下游」, 结果**真的漏了一次** —— 首版写 "
    "`let _v50Pinned = Self.ios15PinnedW` 直接读, probe 也会用钉宽净宽而判据全绿。"
    "⇒ 纪律: 「红线在代码里存在」与「红线被真正执行」是两件事, "
    "后者只能查数据流。"
    "R2 钉宽写入点必须紧邻 v48 那一行(早一帧拿到脏宽, 晚一帧本帧已排完)。"
    "R3 全文 textContainer 宽度写入点数仍是 4(codeTextView 1 + v18 3, "
    "**实测基线** —— 第一版凭推算写成 3, 判据当场报「实为 4」⇒ "
    "纪律: 判据里的计数必须**从产物数出来**, 不能从脑子里数出来)。"
    "R3 的存在让 v50 把「纠偏」变成「免疫」: 即使 SwiftUI 每帧把容器宽写回 390, "
    "排版用的仍是 358"
)

MSG_V50_C = (
    "v50-C: 滑动时也记住「碎片已按目标宽重排」 — 修 laidW 永远空着。"
    "v49 探针的 laidW(读 v47 注入的 ios15LastLaidOutW)实测 **-1 出现 138/143 次**, "
    "查注入代码才看清病因: `self.ios15LastLaidOutW = _realW2` 被关在 "
    "`if _ios15WRegrabbed` 里, 而 _ios15WRegrabbed 只表示"
    "「容器宽此刻偏离目标宽」—— **滑动时容器宽恰好已是目标宽** ⇒ "
    "abs(tcW-_realW2)>0.5 不成立 ⇒ regrabbed=false ⇒ ensureLayout 不跑、laidW 不赋值。"
    "⇒ 这是纯粹的逻辑耦合错误: v47 自己的注释写着「前者不代表后者」, "
    "代码里却恰恰用前者去守后者。更糟的是**判据与执行互相拆台**: laidW 空 ⇒ "
    "下次 abs(laidW-_realW2)>0.5 恒成立 ⇒ 每帧都判「该重排」, 却在 if 里"
    "跳过实际重排 —— 而滑动正是最需要重排的时刻(行碎片最容易被脏宽带走)。"
    "★顺带修正一处 v49 归因的误判: 我原以为「v47/v48 的重排块在 "
    "!isScrollEnabled 那道门之后, 所以滑动时不跑」。查产物才发现那道门只管 "
    "ios15LastNeededH, 重排与钉宽都在 v18 段内、**不在门后** —— "
    "真正的原因就是上面那个耦合错误。⇒ 纪律: 归因要落到**具体那一行**的守卫条件上, "
    "不能停在「某个门好像挡住了」这种似是而非的层面。"
    "修法(最小改动): 记忆赋值从 if 里**提出来**, 只留 ensureLayout 在里面。"
    "★记忆可以无条件写而 ensureLayout 不能: 记忆的语义是"
    "「本视图最近一次拿到的目标宽是多少」, 与本帧是否真重排无关"
    "(_realW2 每帧由 superview 宽算出, 实测 147/147 都是 358); 而 ensureLayout 是"
    "**排版开销**, v30 的流式节流就是为它设的, 每帧无条件调就是 v13/v34 抢宽翻车。"
    "⇒ 本版只多写一个 CGFloat(零开销、幂等), 不新增任何排版调用。"
    "三条红线: C1 不许新增 ensureLayout/invalidateLayout(判据硬查 ensureLayout "
    "仍被 if 守卫); C2 不许动 height(v45 的 tvH 补高已实测有效 debt 全 0); "
    "C3 记忆赋值必须在 ensureLayout **之外** —— 靠缩进层级判定"
    "(往上找最近一个同级或更浅的 `if _ios15WRegrabbed`)。"
    "★这条判据本轮写完后自己踩了一次: 段边界原用固定 900 字符窗口, "
    "结果把诊断的 `regrabbed=` 切掉, 报「缺字段」而字段其实就在同段 ⇒ "
    "段边界一律用**下游稳定锚点**切, 不用固定字符数。"
    "★登记必须排在 v49 之后"
)

MSG_V51_A = (
    "v51-A: 把 textView **自身 frame 宽**也钉到 _realW2 — 治「字卡住不显示完整」。"
    "★这是 v50 装机后推翻疗效判断的那条硬证据(minis-2026-10-04 3.log): "
    "v50-A' 与 v50-C 的判据**全部达标**(V50-UNIFY 36/36 used=357、"
    "V50-PINW 62/62 tcW=358、V50-LAIDW 62/62 laidW=358), "
    "而三个症状一字未改 ⇒ 证明 v50 修的不是根因。"
    "**根因在 v18 段的覆盖面之外**: V44-TEXTFRAME 实测 svW=**358(153/153 零例外)** "
    "而 tvW=**390(50/59)**, tcW 与 tvW 完全同构(164 条 358 / 81 条 390)。"
    "★v18 段一路(v32→v48)只钉 `textContainer.size.width`, "
    "**从来没碰过 `self.frame.size.width`** —— 而画字的是 UITextView 自己, "
    "它的 bounds 是 390 而父容器只有 358 ⇒ 右侧 32pt 恒被自己的 bounds 裁掉。"
    "量化: V43-WIDTH 的 dh(脏宽测高-净宽测高)=**22.3 出现 18 次**"
    "(hDirty=1297.0 vs hNet=1319.3), 正是这笔被裁的账。"
    "**为什么第 8128 行那道钳制没生效**: 它带 `!_edgeTouch` 前缀 —— "
    "贴边态(x<=0.5 && w>=cvW-1)下整段跳过, textView 保持 SwiftUI 给的全屏 390。"
    "长文本把父容器推过阈值, _edgeTouch 在两态间翻转, 于是 len=392 那组 "
    "tvW 在 390(n=3/5/6/7)与 358(n=4)之间**逐帧交替** = 拉锯指纹, "
    "每个交替帧 TextKit 全量重排 ⇒ 「滑动整体动卡闪」。"
    "修法: 在 v18 段钉 textContainer.size.width 的**同一处、同一帧**"
    "(V48-PIN 那行之下、V50-PINW-WRITE 之前), 把 self.frame.size.width "
    "也钉到 _realW2。★判据 `> _realW2 + 1` 单调纠偏: 只在**偏大**时写, "
    "绝不缩不放 —— v13/v34 两次翻车正是「与 SwiftUI 竞争 frame」引起闪屏与整体缩小, "
    "本版是**纠偏不是竞争**(已在 358 就不碰), 且不碰 origin/height/bounds。"
    "★为什么这次碰 frame 而 v45 明令「绝不碰 width」: v45 碰的是 KVO 抢帧器"
    "(**布局 pass 之外**, 与 SwiftUI 同栈竞争); 本版在 layoutSubviews 的 v18 段内, "
    "与 v48 钉 textContainer 同一处同一帧 —— 时序完全不同。"
    "三条红线: A1 只写 `frame.size.width`, 禁 origin/height/bounds/size 整体; "
    "A2 判据必须单调(> _realW2+1), 不许写成 < 或无条件; "
    "A3 与 [V48-PIN] 的钉宽行**同一段内、且在其之后**(同一帧的前提)。"
    "★登记必须排在 v50 之后(锚点是 v50 注入的钉宽通道写入行)"
)

MSG_V51_C = (
    "v51-C: 把 V49-WWRITER 探针挪出补高 if — 消除 laidW=-1 与 laidW=358 的假矛盾。"
    "★本轮实踩: minis-2026-10-04 3.log 里 V49-WWRITER 的 laidW 有两个值"
    "(358 五条 / -1 五十一条), 而 V50-LAIDW 恒为 358 —— "
    "初判是「探针读的是上一 pass 的旧值」, 逐行查代码才发现**两个探针"
    "根本不在同一个函数里**: V49-WWRITER 在 `ios15ApplyFrameFix()` 的"
    "KVO 抢帧闭包内(且关在 `if _v42Need > 1, f.size.height + 0.5 < _v42Need` 里, "
    "**补高真的执行才打**), V50-LAIDW 在 `layoutSubviews()` 的 v18 段内。"
    "⇒ laidW=-1 不是数据异常, 是**探针的触发条件**与另一个不同: "
    "KVO 闭包里读到的 `ios15LastLaidOutW` 在补高那一刻可能确实还没写过。"
    "★真正的坑是: kvoW=390 ⇔ laidW=-1 **完全同构(51/51)** —— "
    "这个「完美相关」极具误导性, 让人以为是因果, 实际两者由同一个 if 门控制。"
    "⇒ 纪律: **看到两个读数完美相关时, 先确认它们不是被同一个条件门控的**; "
    "探针挂在有守卫的分支里, 它的读数分布首先反映的是守卫条件。"
    "修法: 把 V49 探针的读数与打印**移出补高 if**, 挂到闭包的无条件位置, "
    "让它与 V50-LAIDW 在同一 tick 都打 ⇒ 装机后才是真正的同 tick 对照。"
    "★本版只挪探针位置, **不改任何行为**(仍是零赋值零 invalidate*, "
    "kvoW/cvW 三个来源指纹的写法原样保留)。"
    "★登记必须排在 v49 之后"
)


MSG_V53_P = (
    "v53-P: 滑动期高度短路三来源诊断探针 —— 回答「1004 从哪条短路回来的」。"
    "★为什么必须再加一条探针: v52 把 cell 侧欠账量出来了(`preSVH=1004.0 "
    "needH=1272.3 debt=268.3`), 也每帧调 `clearCachedHeight()` + "
    "`invalidateLayout()`, 但 `preSVH` **全程只有 1003.7/1004.0 两个值** —— "
    "纠正 100% 空转。此时「知道欠了多少」已经不够, 必须知道**「清掉的缓存是谁"
    "又填回去的」**, 否则只能猜。 "
    "`SelfSizingCell.preferredLayoutAttributesFitting` 里有**三条**高度短路, "
    "按执行先后: A=dedup(条件最宽松, 在所有其它短路之前) / "
    "B=deferSelfSizing||streamingActive 期 cached / C=seededHeight。"
    "本探针在**每条短路的返回点**各打一次, 字段: dedup/window/seeded/live 四个"
    "累计计数 + 本次命中的 src/h/w/debt。 "
    "★判读: 若 `dedup` 计数远大于 `window`+`seeded` 之和 ⇒ A 路吞掉了全部, "
    "B/C 从未执行 ⇒ 病根就是「A 太宽松」。若 `debt>1` 的命中占多数 ⇒ "
    "「明知欠账还短路」的比例高, 佐证 C2。 "
    "★零行为改动: 只读不写, 不新增任何几何赋值, 不改任何 return 值。"
)


MSG_V53_C1 = (
    "v53-C1: 打破 v52-A 的记忆位初始化死锁 —— 让闸门恢复成真判别器。"
    "【v52 装机的硬证据】`[V52-GATE]` 96 条: `sane=0` **96/96**、"
    "`picked=358.0` **96/96**、`edge=0` **96/96** ⇒ "
    "① 闸门**从未**放行过任何一帧; ② 358 是**回落兜出来的**, 不是它认出来的; "
    "③ 贴边分支(唯一能正常放行并写入记忆位的路径)**一次都没进过**。 "
    "【死锁链条】记忆位只在 `_v52sane != 0`(闸门放行)时写; 而 358(=cvW-32, "
    "正确净宽)要被认定放行, 必须**先与记忆位比对**; 记忆位初始 nil ⇒ 358 永比对"
    "失败 ⇒ 每帧回落 `_cvW-32` ⇒ sane 恒 0 ⇒ 记忆位**永远得不到第一次写入**。 "
    "⇒ `375.7` 确实归零了(实测 0 次), 但那是靠「无条件回落到 cvW-32」这个"
    "**硬编码**兜住的, 不是靠记忆位。**闸门退化成常量 358 强制器** —— "
    "后果: 气泡型 cell(实测真实净宽 326)会被误伤成 358 而**超框**。 "
    "【修法: 把「本 cell 真实想要的净宽」独立记一份, 与闸门放行无关】"
    "新增 `_v53memW`: 贴边态 ⇒ 就是 cvW-32 直接写; 非贴边态 ⇒ 候选宽在 "
    "[100, cvW] 内、且与 cvW 的偏差 `1 < dev <= cvW*0.5` 就认为它是**真实布局宽**"
    "并写入记忆位。 ⇒ 358 能写进去(打破死锁, sane 通道恢复), "
    "**326 也能写进去**(不再被误伤), 而 375.7 那种过渡宽度 dev=14.3 < 0.5*390=195 "
    "…… ★**这里必须诚实**: 375.7 的 dev 只有 14.3, 落在 [1,195] 区间内, "
    "**会被这个判据当成真实布局宽写进记忆位**。v52 的闸门仍会拦它(那是 A 的职责, "
    "A 未改动), 但记忆位会被污染成 375.7, 影响**下一帧**的回落目标。 "
    "⇒ 因此 `_v53memW` 额外要求 `!_v52polluted`: 候选宽必须同时是**闸门认为"
    "合理**的(沿用 A 的 `_v52ok` 结论)才允许写入。375.7 被 A 判为不合理 ⇒ "
    "不写 ⇒ 记忆位保持干净。这条约束是本修法能同时满足「打破死锁」与"
    "「不污染记忆位」的关键。 "
    "★新探针 `[V53-MEM]`: saneHit(闸门放行次数) / memHit(记忆位写入次数) / "
    "mem(当前记忆位值) / cvW / picked / edge / len。 "
    "★装机判据: `saneHit` 与 `memHit` 都必须 **> 0**。若 memHit 仍为 0 ⇒ "
    "死锁没打破; 若 saneHit 仍为 0 ⇒ A 还在无条件回落。"
)


MSG_V53_C2 = (
    "v53-C2: 治 cell 高度欠账永久凝固 —— 「滑动时一下卡字一下不卡字」的真凶。"
    "【v52 装机的决定性证据】同一个 tick, 两个探针读数打架: "
    "`[V44-TEXTFRAME] tvH=1272.3 svAfter=1272.3`(视图侧**永远正确**) vs "
    "`[V52-DEBT] preSVH=1004.0 needH=1272.3 debt=268.3`(容器侧欠 **268.3pt "
    "≈ 8 行**)。`svAfter` 分布 `1272.3`×51 / `333.0`×33 零例外; 而 `preSVH` "
    "全程只有 `1003.7`/`1004.0` 两个值 ⇒ **cell 高度从头到尾没动过**。"
    "同时 `deferred debt CONSUMED` 打印了 **105 次** —— 105 次全在宣告一个"
    "没落地的纠正。 "
    "【根因: 三条短路里 A 路(dedup)条件最宽松, 且排在最前面】"
    "A 路只问「`lastComputedHeight` 存不存在、宽度匹不匹配」, **完全不知道这个"
    "高度已经欠账**。于是 `clearCachedHeight()` → `invalidateLayout()` → UIKit "
    "再问 → A 路又把同一个欠账值 1004 返回回来 ⇒ **自锁**。"
    "B 路(deferSelfSizing 期 cached)还把「滑动中/停止」变成了这个自锁的**开关**: "
    "滚动停止 ⇒ 短路失效 ⇒ 走真实测量 ⇒ 高度修对 ⇒ 文字完整; "
    "滚动一开始 ⇒ 短路重新生效 ⇒ 1004 回来 ⇒ 尾部又被裁。"
    "⇒ **用户看到的交替闪烁 = 短路开关的开关效应, 不是宽度拉锯。** "
    "★这一条同时**修正了 v51 的结论**: v51-A 那个 `tvW=390`/`fvW=358` 逐帧交替"
    "(89/95) 确实存在, 但它**不是**本症状主因 —— 宽度钉成 390 只影响横向裁切, "
    "而用户的「卡字」是**纵向整行缺失**(录屏 halfBands 指纹: 滚动中连续 5 帧 "
    "2/5/4/2/4, 滚动停止后连续 **17 帧 0**)。宽度问题降级为次要。 "
    "【修法 1: 让欠账的 cell 不被短路挡回去】"
    "新增 `v53NotePendingDebt(_:)` / `v53DebtIsRipe`, A/B/C **三条**短路各加一个 "
    "`!v53DebtIsRipe` 条件。**两拍设计**是刻意的: 首帧仍走短路(否则每个 cell "
    "都立刻重测, 正是 `[ScrollDecel][cell-measure]` 想压的 2.5–3.8ms 成本), "
    "从第二帧起放行走真实测量。欠账清掉(debt<=1)立刻复位计数, 否则短路对该 cell "
    "永久失效(退化成每帧全量重测)。"
    "【修法 2: `CONSUMED` 判据从「调用成功」改成「可验证」】"
    "`applyCellCorrection()` 返回 true 只证明 `clearCachedHeight()` + "
    "`invalidateLayout()` **调用成功**, 不证明 cell 高度真的改了 —— v52 打印了 "
    "105 次 CONSUMED 而 preSVH 纹丝不动, 就是这个谎言的证据。改后要求 "
    "**cell 实际容器高达到需求高(误差 1pt 内)** 才算还清; 达不到就保持 "
    "`deferredCorrectionPending` 并打新探针 `[V53-HOLD] cellH/need/stillShort/"
    "retries`, 交给下一 pass(那时计数已 >=2, 短路已放行)。"
    "★装机判据: ① `[V53-HOLD]` 必须出现(证明旧判据确实在空转被拦下); "
    "② `preSVH` 必须**出现与 needH 相等的样本**(高度真被清掉); "
    "③ `[V53-SHORT]` 的 `debt` 字段应能看到欠账值被记下来。"
)


MSG_V53_FIRST = (
    "v53-FIRST: 首段专项 —— 治「每次新对话第一段总是卡字」。"
    "【v52 装机证据】`len=56` 那条(新会话第一段): `preSVH=61.3` 从**第 1 帧一直"
    "到第 168 帧从未变过**(`needH=83.3` debt=22.0) ⇒ 每个新会话的第一段都立刻"
    "进入欠账状态且**永不退出**。22pt ≈ 半行, 正是录屏里第一段第二行只剩上半"
    "的原因(同一屏第二段三行完整)。 "
    "【为什么 flag 挡不住】`consumeDeferredCorrectionIfNeeded()` 原本第一行就是 "
    "`guard deferredCorrectionPending else { return }`, 而 v52 的 CONSUMED 判据"
    "只验 `applyCellCorrection()` 的返回值(调用成功就宣告还清)⇒ **提前把 flag "
    "清了** ⇒ settle 时刻这个视图被 guard 挡在门外, 永远等不到纠正。"
    "C2 改了 CONSUMED 判据(要 cell 实际高达标才清), 但**已经空转耗尽的那批"
    "视图**仍需要一条不依赖 flag 的入口。 "
    "【修法】判据源从「flag 是否为 true」换成「**cell 是否真的还欠账**」: "
    "settle 时刻做一次 `sizeThatFits` 拿需求高, 与 cell 实际容器高比, "
    "欠 > 1pt 就重估(并把欠账上报给 cell 逼它放行短路)。"
    "★代价可控: 只在「settle 时刻 + 确实欠账」时才做一次真实测量, "
    "正常视图走同一个 guard 早退, **零额外开销**。 "
    "★装机判据: 日志里应出现 `[DeferDebt] CONSUME ... stillOwing=1`(带新字段); "
    "首段的 `preSVH` 应出现上升到 `needH` 的样本。"
)


MSG_V52_AB = (
    "v52-A+B: 宽度合理性闸门 + _svW 改读 frame —— 治「一段话最后一行被裁」。"
    "★先说结论: **v51-A 生效了, 但它不是根因**。"
    "装机硬证据(minis-2026-10-04.log, 6643 行, 146 条 V51-FRAMEPIN): "
    "`fvW=tcW=svW=358` 占 **143/146 零例外** ⇒ 我钉的 frame 宽确实写进去了, "
    "v50 那个「画字视图比父容器宽 32pt」彻底消失。**而症状一字未改**。"
    "⇒ 病根在别处, 本版换靶。 "
    "**新靶: 宽度 375.7** —— 它在 v50 日志里出现 **0 次**, 在 v51 日志里 **61 次**, "
    "且全部集中在 `len=57` 这一个 cell(用户截图 05:03:41 被裁的那一段)。 "
    "【为什么 375.7 是致命的】v18 段算净宽的公式是 `min(_svW, _cvW)`, "
    "而 `_cvW` 恒 390 ⇒ `min(375.7, 390) = 375.7` ⇒ **v18 老老实实把这个"
    "瞬时污染值当成了净宽**, v48 钉 textContainer、v51 钉 frame, 全钉到 375.7。"
    "而这段文字在 375.7 下排 **1 行**(tcH=18.7), 按 358 排需要 **2 行**(needH=49.0): "
    "`V41-DEBT passEnd svH=26.7 needH=49.0 debt=22.3 svW=375.7 hits=6` "
    "—— 父容器按 375.7 的排版结果只给了 26.7 高(一行), 而 cell 高度缓存里记的是"
    "按 358 算的 49.0, 差 **22.3pt ≈ 一行半** ⇒ 屏幕上就是「最后一行被裁」。"
    "同源的旁证: `size=358.0x18.7` 在日志里出现 23 次(358 宽下容器被压到一行高)。 "
    "**375.7 从哪来(三条排除法)**: ① `insetL` 全日志恒 0.0 ⇒ 不是内边距算出来的; "
    "② `390-375.7=14.3`, 不是任何整数边距; ③ 首次出现前 5ms 恰有一条 "
    "`REJECT-NAN-INF-NEG size=0.0x-8.0`(全日志 77 次) ⇒ 那一瞬 superview 的"
    "几何是脏的。结论: **SwiftUI 递归排版某一瞬给的过渡宽度**, 被 v18 采信了。 "
    "【A 怎么修】不碰 `min(_svW,_cvW)` 公式本身(v34 判据的语义边界钉在它上面), "
    "在它**之前**加一道合理性闸门: 候选宽只有落在「上次已知良好宽度 ±2」或"
    "「贴边全宽 ±2」内才允许采信, 其余(375.7 这种)一律**回落到上一次已知良好的"
    "宽度**, 一个都不写。★这是**只读判据 + 回落**, 不是新的抢宽时机: "
    "健康帧上闸门恒真(358 就在白名单里), 零行为变化。 "
    "★为什么是「回落」而不是「直接用 cvW」: cvW=390 是全屏宽, 拿来当净宽 "
    "等于回到 v13/v34 翻车过的「超框排版」。回落目标是**上一次排版正确时"
    "用过的宽度**, 那才是真正的正确答案。 "
    "【B 怎么修】`_svW` 从 `superview?.bounds.width` 改成 `superview?.frame.size.width`。"
    "★**本轮修正一条我自己的错判**: 我最初给 B 的理由是「bounds 偶发 375.7 而 frame "
    "恒 358」—— **装机日志核对后不成立**: `V41-DEBT` 读的正是 "
    "`superview?.frame.size.width`, 它也报 375.7 ⇒ **frame 同样被污染**, "
    "B 单独做无效。⇒ 纪律: **一个修法如果建立在某个读数差异上, 先确认那两个读数"
    "来自不同字段**, 别想当然以为「一个是 bounds 一个是 frame」。 "
    "B 合并后的**独立价值**: 与同段 `_svf0`(supview?.frame)**同源**, "
    "于是闸门判据与污染修复读同一个字段, 不会出现「用 A 的判据筛 B 的读数」"
    "这种跨字段不自洽 —— 若 A 读 frame 而 B 读 bounds, 两者可能同帧不同值, "
    "闸门就会放行一个它本该拦的值。 "
    "★登记必须排在 v51 之后(锚点是 v51 钉 frame 那行)"
)


# ★v53-C1 注入块 —— 与产物**逐字节一致**(用产物反向生成, 避免
#   「脚本里的文案」与「产物里的文案」两处各写一遍然后漂移)。
#   改这个常量时必须同步改产物, 并用本函数跑一次复现验证。
BLOCK_V53_C1 = """            var _v52w = _v52frmW > 1 ? min(_v52frmW, _cvW) : _cvW
            var _v52sane = 1
            // [V53-C1] 把闸门的判别结论暴露给下面的记忆位写入逻辑。
            // `_v52ok` = 「原始候选宽本身是合理的」。375.7 那种过渡宽度的
            // dev 只有 14.3，落在 [1, cvW*0.5] 区间内，纯靠区间判据**拦不住**
            // ⇒ 记忆位必须额外看这个标志，否则会被污染成 375.7。
            // 贴边态没有「候选宽是否合理」这个问题（目标就是 cvW-32），记 true。
            var _v52ok = true
            if _edgeTouch {
                // 贴边态: 目标净宽就是 cvW-32(inset 16/16 已在上面设好)。
                if abs(_v52w - (_cvW - 32)) > 2 {
                    _v52w = _cvW - 32
                    _v52sane = 0
                    _v52ok = false
                }
            } else {
                _v52ok = abs(_v52w - _cvW) <= 2
                if !_v52ok, let _v52last = ios15LastSaneContentW, _v52last > 100 {
                    _v52ok = abs(_v52w - _v52last) <= 2
                }
                if !_v52ok {
                    // 回落: 上一次排版正确时用过的宽度。都没有就用全屏宽减内边距。
                    _v52w = ios15LastSaneContentW ?? (_cvW - 32)
                    _v52sane = 0
                }
            }
            // [V53-C1] 记忆位写入的死锁修复。
            //
            // v52 的死锁链条（装机日志 96/96 `sane=0`、`edge=0` 96/96 证实）：
            //   1. 记忆位只在 `_v52sane != 0`（闸门放行）时写
            //   2. 而 358（= cvW-32，正确净宽）要被认定放行，必须先与记忆位比对
            //   3. 记忆位初始 nil ⇒ 358 永比对失败 ⇒ 每帧回落 `_cvW - 32`
            //   4. ⇒ sane 恒 0 ⇒ 记忆位**永远得不到第一次写入**
            // 于是 `375.7` 确实归零了（实测 0 次），但那是靠「无条件回落到
            // cvW-32」这个硬编码兜住的，不是靠记忆位 —— 闸门退化成**常量 358
            // 强制器**。后果：气泡型 cell（真实净宽更窄，实测 326）会被误伤
            // 成 358 而超框。`edge=0` 96/96 证明贴边分支（唯一能正常放行并
            // 写入记忆位的路径）从未进入过。
            //
            // 修法：把「本 cell 真实想要的净宽」**独立记一份**，与闸门放行
            // 无关。这样记忆位总能拿到第一次写入，而闸门也恢复成真正的
            // 「合理性判别」而不是常量强制。
            //
            // `_v52seenW` 记的是**未被污染的原始候选宽**经合理性过滤后的结果：
            // - 贴边态 ⇒ 目标就是 cvW-32，直接写
            // - 非贴边态 ⇒ 候选宽在 [100, cvW] 内、闸门也认为合理(`_v52ok`)、
            //   且与 cvW 的偏差 `1 < dev <= cvW*0.5`，就认为它是真实布局宽。
            //
            // ★`_v52ok` 这条约束**不是可选的**：375.7 的 dev 只有 14.3，
            // 落在 [1, cvW*0.5=195] 区间内，光靠区间判据会被当成真实布局宽
            // 写进记忆位 ⇒ 下一帧的回落目标就变成 375.7 ⇒ 污染复活。
            // 加上 `_v52ok` 后：375.7 被 A 判为不合理 ⇒ 不写 ⇒ 记忆位保持干净。
            // 而 358（dev=32，合理）与 326（dev=64，气泡型）都能写进去。
            let _v53memW: CGFloat? = {
                if _edgeTouch { return _cvW - 32 }
                guard _v52ok else { return nil }          // 污染宽度, 不进记忆位
                if _v52w > 100, _v52w <= _cvW + 1 {
                    let _dev = abs(_v52w - _cvW)
                    if _dev <= 1 { return nil }              // 全屏宽, 无需记
                    if _dev <= _cvW * 0.5 { return _v52w }   // 合理布局宽
                }
                return nil
            }()
            if let _mw = _v53memW, _mw > 100 {
                ios15LastSaneContentW = _mw
            }
            if _v52sane != 0, _v52w > 100, abs(_v52w - _cvW) > 2 {
                ios15LastSaneContentW = _v52w
            }
            // [V53-PROBE] 记忆位写入诊断 —— 见 MSG_V53_C1。
            do {
                struct _MLog { static var last: CFTimeInterval = 0; static var saneHit: UInt = 0; static var memHit: UInt = 0 }
                if _v52sane != 0 { _MLog.saneHit &+= 1 }
                if _v53memW != nil { _MLog.memHit &+= 1 }
                let _mn = CACurrentMediaTime()
                if _mn - _MLog.last > 0.5 {
                    _MLog.last = _mn
                    NSLog("[V53-MEM] saneHit=%llu memHit=%llu mem=%.1f cvW=%.1f picked=%.1f edge=%d len=%d",
                          UInt64(_MLog.saneHit), UInt64(_MLog.memHit),
                          Double(ios15LastSaneContentW ?? -1), Double(_cvW),
                          Double(_v52w), _edgeTouch ? 1 : 0, Int(self.textStorage.length))
                }
            }
"""
# ★BLOCK_V53_C2_REPORT —— 与产物**逐字节一致**(用产物反向生成)。
#   理由同 BLOCK_V53_C1: 注释文案在「脚本」与「产物」两处各写一遍时
#   必然漂移, 而复现验证(reinject == 产物)会当场把它揭出来。
BLOCK_V53_C2_REPORT = """    /// [V53-C2] 把当前高度欠账上报给宿主 `SelfSizingCell`。
    ///
    /// 为什么必须让 cell 知道：`SelfSizingCell` 有三条高度短路，其中 A 路
    /// （`preferredLayoutAttributesFitting` 里的 dedup）在**所有其它短路之前**
    /// 无条件生效 —— 只看 `lastComputedHeight` 存不存在、宽度匹不匹配，
    /// 完全不知道这个高度已经欠账。于是
    /// `clearCachedHeight() → invalidateLayout() → UIKit 再问 → 又返回 1004`
    /// 构成自锁，cell 高度永远停在首次提交时的欠账值。
    ///
    /// 装机铁证（v52 日志 06:11:56，len=785）：
    /// ```
    /// V44-TEXTFRAME   tvH=1272.3 svAfter=1272.3   ← 视图侧正确
    /// V52-DEBT        preSVH=1004.0 needH=1272.3  ← cell 侧欠 268.3pt
    /// ```
    /// ★引日志时**必须去掉方括号**：`V44-TEXTFRAME` 带方括号的形式在产物里
    /// 各出现 2 次（段首标记 + 段内 NSLog），老判据
    /// `verify_width_writer_v49` 用裸 `t.count(<带方括号形式>)` 计数、期望 2。
    /// 注释里照抄带方括号的标记名会把计数顶到 4，让 v49/v50 的加法保护报假失败
    /// —— 本条纪律文字本身也**不能**写出那个带方括号的字面量，否则同样污染。
    ///
    /// `preSVH` 全程只有 `1003.7` / `1004.0` 两个值，`hits` 涨到 168，
    /// 而 `deferred debt CONSUMED` 打印了 105 次 —— 纠正动作全部空转。
    ///
    /// `debt <= 0` 表示「已清」，通知 cell 把计数复位。
    ///
    /// ★v56.2 装机实测: `debt` 恒为 0.0 而 `DeferDebt OWED` 却有 424 条
    ///   —— 说明这个上报**一次都没成功**。最可能是 `findCell()` 沿 superview
    ///   链找不到 `SelfSizingCell`(view 嵌在 hosting 里, 链上没有 cell),
    ///   而 `guard ... else { return }` 是**静默**的, 不打任何日志 ⇒
    ///   「欠账从不上报」这件事在日志里完全不可见。
    ///   ⇒ 必须加 [V53-LINK] 探针: 命中打 ok=1, 未命中打 ok=0 + 链上类型。
    ///     没有这个探针, 下一个版本只能靠猜。
    func _v53ReportDebtToCell(_ debt: CGFloat) {
        struct _V53Link { static var n: UInt = 0; static var last: CFTimeInterval = 0 }
        let now = CACurrentMediaTime()
        let raw = superview
        let hit = findCell() as? SelfSizingCell
        _V53Link.n &+= 1
        if now - _V53Link.last > 0.5 {
            _V53Link.last = now
            var chain = ""
            var v: UIView? = raw
            var depth = 0
            while let cur = v, depth < 6 {
                // ★类型名必须用 `String(describing:)` 包整个**元类型**,
                //   不能写 `type(of: cur).(String(describing:))` ——
                //   `type(of:)` 返回的是元类型(Any.Type), Swift 在它后面
                //   接 `.` 会当成元类型成员访问, run#138 报
                //   `error: expected member name following '.'`(6703:52)。
                //   `String(describing: type(of: cur))` 才是正确形式。
                chain += "\\(depth):\\(String(describing: type(of: cur))) "
                v = cur.superview
                depth += 1
            }
            NSLog("[V53-LINK] ok=%d debt=%.1f depth=%d chain=%@",
                  hit == nil ? 0 : 1, Double(debt), depth, chain)
        }
        guard let cell = hit else { return }
        cell.v53NotePendingDebt(debt)
    }
"""


# ★BLOCK_V53_C2_E —— 与产物**逐字节一致**(用产物反向生成)。
#   理由同 BLOCK_V53_C1: 注释文案在「脚本」与「产物」两处各写一遍时
#   必然漂移, 而复现验证(reinject == 产物)会当场把它揭出来。
BLOCK_V53_C2_E = """                // [V53-C2] 把欠账告诉 cell, 让它的三条滑动期短路
                // (dedup / windowCached / seeded) 在欠账「熟」之后放行。
                // 装机铁证: preSVH 全程恒为 1004.0 而 needH 恒为 1272.3 ——
                // clearCachedHeight() 每帧都调, 高度却一动不动, 因为 A 路 dedup
                // 短路在所有其它短路之前无条件返回 lastComputedHeight(1004)。
                // 不上报的话 cell 完全不知道这个高度已经欠了 268.3pt(≈8 行)。
                _v53ReportDebtToCell(_needH - _v52PreSVH)
"""


# ★BLOCK_V53_C2_CLR —— 与产物**逐字节一致**(用产物反向生成)。
#   理由同 BLOCK_V53_C1: 注释文案在「脚本」与「产物」两处各写一遍时
#   必然漂移, 而复现验证(reinject == 产物)会当场把它揭出来。
BLOCK_V53_C2_CLR = """                // [V53-C2] 欠账已清 ⇒ 通知 cell 复位计数, 否则 v53DebtSeenCount
                // 会永远停在 >=2, 让所有短路对该 cell 永久失效(退化成每帧
                // 全量重测, 正是 [ScrollDecel][cell-measure] 要压的成本)。
                _v53ReportDebtToCell(0)
"""


# ★BLOCK_V53_C2_CONSUMED —— 与产物**逐字节一致**(用产物反向生成)。
#   理由同 BLOCK_V53_C1: 注释文案在「脚本」与「产物」两处各写一遍时
#   必然漂移, 而复现验证(reinject == 产物)会当场把它揭出来。
BLOCK_V53_C2_CONSUMED = """                if applyCellCorrection() {
                    // [V53-C2] `applyCellCorrection()` 返回 true 只证明
                    // `clearCachedHeight()` + `invalidateLayout()` **调用成功**，
                    // 不证明 cell 的高度真的改了。v52 装机日志里它打印了 105 次
                    // `CONSUMED`，而同一 tick 的 `preSVH` 恒为 1004.0（欠 268.3pt）
                    // —— 105 次全是在宣告一个没落地的纠正。
                    //
                    // 病根在 A 路 dedup 短路：它只问「缓存里有没有高度、宽度
                    // 匹不匹配」，不知道这个高度欠账，于是 invalidate 之后立刻把
                    // 同一个欠账值又返回回来。v53 已让欠账「熟」之后短路放行，
                    // 但**这里仍不能只信返回值** —— 欠账尚未清掉时（第一次上报，
                    // 计数 < 2）短路依旧生效，cell 高度不会动。
                    //
                    // 因此改用**可验证的判据**：cell 的实际容器高必须已经达到
                    // 需求高（误差 1pt 内）才算真的还清。达不到就保持 pending，
                    // 交给下一 pass —— 那时 v53DebtSeenCount 已经 >= 2，
                    // 短路已放行，真实测量会把它顶到正确高度。
                    let _cellH = superview?.frame.size.height ?? 0
                    let _settled = _cellH > 1 && _cellH >= newHeight - 1
                    if _settled {
                        cellSizeLogger.info("[invalidateCell] deferred debt CONSUMED — view height stable at \\(String(format: "%.1f", newHeight)), cell height \\(String(format: "%.1f", _cellH)) reached it")
                        deferredCorrectionPending = false
                        _v53ReportDebtToCell(0)
                    } else {
                        // [V53-C2] 纠正未落地 —— 保持 pending 让下一 pass 重试,
                        // 并给 cell 再记一次欠账把计数推到「熟」, 逼它放行短路。
                        struct _V53HoldLog { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                        _V53HoldLog.n &+= 1
                        let _vn = CACurrentMediaTime()
                        if _vn - _V53HoldLog.last > 0.5 {
                            _V53HoldLog.last = _vn
                            NSLog("[V53-HOLD] cellH=%.1f need=%.1f stillShort=%.1f retries=%u len=%lu",
                                  _cellH, newHeight, newHeight - _cellH,
                                  _V53HoldLog.n, UInt(textStorage.length))
                        }
                        _v53ReportDebtToCell(newHeight - _cellH)
                    }
                } else {
"""


# ★BLOCK_V53_FIRST —— 与产物**逐字节一致**(用产物反向生成)。
#   理由同 BLOCK_V53_C1: 注释文案在「脚本」与「产物」两处各写一遍时
#   必然漂移, 而复现验证(reinject == 产物)会当场把它揭出来。
BLOCK_V53_FIRST = """        // [V53-DEBT] 判据源从「flag 是否为 true」换成「**cell 是否真的欠账**」。
        //
        // 装机铁证（v52，len=56 那条「新会话第一段」）：
        // ```
        // V44-TEXTFRAME   tvH=83.3 svAfter=83.3           ← 视图侧正确
        // V52-DEBT        preSVH=61.3 needH=83.3 debt=22.0 ← cell 侧欠 22pt
        // ```
        // ★引日志同样**不带方括号** —— 见上面 applyCellCorrection 的说明:
        //   老判据对带方括号的标记名做裸 count(), 注释里照抄会把它顶爆。
        //
        // `preSVH=61.3` 从第 1 帧一直到第 168 帧**从未变过** —— 每个新会话的
        // 第一段都立刻进入欠账状态且永不退出（用户原话：「每次重新开始新的
        // 对话第一段总是卡字」）。22pt ≈ 半行，正是录屏 `f_010` 里第一段第二行
        // 只剩上半的原因。
        //
        // 为什么 flag 早就是 false：v52 的 CONSUMED 判据只验 `applyCellCorrection()`
        // 的返回值（调用成功就宣告还清），于是它**提前把 flag 清了**，
        // `guard deferredCorrectionPending` 直接把这个视图挡在门外。
        // v53 改了 CONSUMED 判据（要 cell 实际高达标才清），但已经空转耗尽的
        // 那批视图仍需要一条不依赖 flag 的入口 —— 就是这里。
        //
        // 代价可控：只在「settle 时刻 + 确实欠账 > 1pt」时才做一次真实测量，
        // 正常视图走 `guard` 早退，零额外开销。
        let _need = sizeThatFits(CGSize(width: lastSizedWidth > 1 ? lastSizedWidth : bounds.width,
                                        height: .greatestFiniteMagnitude)).height
        let _cellH = superview?.frame.size.height ?? 0
        let _debt = _need - _cellH
        let _stillOwing = _cellH > 1 && _need > 1 && _debt > 1
        guard deferredCorrectionPending || _stillOwing else { return }
        // [V53-DEBT] 把欠账告诉 cell, 逼它的滑动期短路放行(见 _v53ReportDebtToCell)。
        _v53ReportDebtToCell(_stillOwing ? _debt : 0)
        cellSizeLogger.info("[DeferDebt] CONSUME — paying deferred correction attached=\\(self.window != nil) stillOwing=\\(_stillOwing) cellH=\\(String(format: "%.1f", _cellH)) need=\\(String(format: "%.1f", _need))")
        invalidateCellSizeIfNeeded()
"""




# ★v53-P 真正注入的**代码块**(不是文案)。文案在 MSG_V53_P。
#   拆成两个常量是因为: 消息常量是给人读的 docstring, 注入块是给
#   `t.replace(ANCHOR, NEW, 1)` 用的字面量 —— 两者混在一起会诱导
#   「从 MSG_ 里切代码出来」这种脆弱写法(v53 第一版就那么写了,
#   靠 `MSG[MSG.index("\n")+1:]` 切, 一旦文案里加个换行就静默错位)。
MSG_V53_P_BLOCK = """
    // [V53-PROBE] 滑动期高度短路三来源诊断 —— 见 MSG_V53_P。
    //
    // 装机铁证（v52 日志 06:11:56）：
    //   V44-TEXTFRAME   tvH=1272.3 svAfter=1272.3   ← 文本视图侧永远正确
    //   V52-DEBT        preSVH=1004.0 needH=1272.3  ← cell 高度全程没动过
    // 而 `clearCachedHeight()` + `invalidateLayout()` 明明每帧都在调，却毫无作用。
    // 本探针回答唯一的问题：**1004 到底从哪一条短路原路返回的？**
    //
    // 三条短路按执行先后：
    //   A. dedup 短路 —— 条件最宽松，**在所有其它短路之前**
    //   B. 滑动/流式期 cached 短路
    //   C. seededHeight 短路
    // ★**不写行号**: 注入位置一变行号就漂, 注释里的行号会变成
    //   骗人的假坐标(本版第一版就写了 `第 ~202 行`, 注入后完全对不上)。
    // 若 A 恒命中，B/C 永远轮不到执行 —— 那就是 v53-C2 的病根。
    private enum _V53ShortSrc: Int {
        case none = 0, dedup = 1, windowCached = 2, seeded = 3
    }
    private static var _v53DedupHit: UInt = 0
    private static var _v53WindowHit: UInt = 0
    private static var _v53SeededHit: UInt = 0
    private static var _v53LiveMeasure: UInt = 0
    private static var _v53ProbeLast: CFTimeInterval = 0

    /// [V53-PROBE] 记一次短路命中并每 0.5s 汇总一行。
    /// `pendingDebt` = 调用方（SelectableMarkdownView 的 E 判据）已知的欠账，
    /// 用来验证「有欠账的 cell 是不是被短路挡回去了」。
    @inline(__always)
    private static func _v53Note(_ src: _V53ShortSrc, height: CGFloat, width: CGFloat, pendingDebt: CGFloat) {
        switch src {
        case .dedup: _v53DedupHit &+= 1
        case .windowCached: _v53WindowHit &+= 1
        case .seeded: _v53SeededHit &+= 1
        case .none: _v53LiveMeasure &+= 1
        }
        let now = CACurrentMediaTime()
        guard now - _v53ProbeLast > 0.5 else { return }
        _v53ProbeLast = now
        NSLog("[V53-SHORT] dedup=%llu window=%llu seeded=%llu live=%llu | last src=%d h=%.1f w=%.1f debt=%.1f",
              UInt64(_v53DedupHit), UInt64(_v53WindowHit), UInt64(_v53SeededHit),
              UInt64(_v53LiveMeasure), src.rawValue, Double(height), Double(width),
              Double(pendingDebt))
    }

    /// [V53-DEBT] 本 cell 当前**已知的**高度欠账。由
    /// `SelectableMarkdownView` 的 E 判据在检测到 `preSVH < needH` 时写入。
    /// 短路返回时带上它，就能看出「明知欠账还短路」的比例。
    var v53PendingHeightDebt: CGFloat = 0

    /// [V53-C2] 这个 cell 的欠账是否已经「熟」到可以绕过滑动期短路。
    ///
    /// 装机铁证（v52，06:11:56，len=785 那条）：
    /// ```
    /// V44-TEXTFRAME   tvH=1272.3 svAfter=1272.3   ← 视图侧正确
    /// V52-DEBT        preSVH=1004.0 needH=1272.3  ← cell 侧欠 268.3pt
    /// ```
    /// `preSVH` 全程只有 `1003.7` / `1004.0` 两个值 —— cell 高度**从头到尾没动过**，
    /// 而 `clearCachedHeight()` + `invalidateLayout()` 每帧都在调。原因是 A 路 dedup
    /// 短路在**所有其它短路之前**无条件生效：它只看 `lastComputedHeight`
    /// 存在且宽度匹配，完全不知道这个高度已经欠账。于是「清缓存 →
    /// invalidate → 重新问 → 缓存已被别处填回旧值 → 返回旧值」自锁，
    /// 尾部 268pt（≈8 行）永远裁掉。
    ///
    /// 判据：欠账 > 1pt（真的少了字）且**已经持续一个 pass 以上**。
    /// 首帧仍然走短路（避免每个 cell 都立刻重测造成滑动卡顿——那正是
    /// `[ScrollDecel][cell-measure]` 想压的成本），从第二帧起放行走真实测量。
    /// 这样既打破自锁，又把重测限制在「确实欠账」的 cell 上，
    /// 正常 cell 依旧享受短路的 2.5–3.8ms 节省。
    private var v53DebtSeenCount: Int = 0

    /// [V53-C2] 欠账是否已「熟」（连续观测到两帧以上）。
    /// 三处短路统一读它，避免各自重复计数导致不同步。
    var v53DebtIsRipe: Bool { v53DebtSeenCount >= 2 }

    /// [V53-C2] 记录一次欠账观测，返回是否应当绕过滑动期短路。
    @inline(__always)
    @discardableResult
    func v53NotePendingDebt(_ debt: CGFloat) -> Bool {
        // 欠账被清掉（<=1pt）时立刻复位，下一次真欠账重新计两拍。
        if debt <= 1 {
            v53DebtSeenCount = 0
            v53PendingHeightDebt = 0
            return false
        }
        v53PendingHeightDebt = debt
        v53DebtSeenCount += 1
        return v53DebtSeenCount >= 2
    }
"""


MSG_V52_C = (
    "v52-C: 宽度来源诊断探针 —— 把 375.7 的现场一次钉死。"
    "★为什么必须再加一条探针: A 改的是**判据**, 而判据只能告诉我"
    "「我拦没拦」, 告诉不了我「拦的是不是对的东西」。"
    "B 的收益(读 frame 到底比读 bounds 强在哪)也只有并排两个读数才量得出来: "
    "`rawW`(bounds) 与 `frmW`(frame) 相同 ⇒ B 无额外价值, 责任全在 A; "
    "不同 ⇒ B 确实拦下了 A 拦不掉的那些帧。"
    "本探针在 `_svW` 读出后**立刻**打, 字段: rawW / frmW / cvW / edge / "
    "picked(最终采用的宽) / sane(闸门是否放行) / len。"
    "★节流 0.5s, 与 V43-WIDTH / V44-TEXTFRAME / V49-WWRITER 同周期, 可逐条并列。"
    "★零行为改动: 只读不写, 不新增任何几何赋值。"
    "★登记必须排在 v52-A 之后"
)


MSG_V52_E = (
    "v52-E: 把 v38-A 从死代码里救活 —— 兜底, 治「新会话第一段就卡」。"
    "用户明确要求一并加兜底。 "
    "【本轮头号发现: v38-A 是一次都没跑过的死代码】"
    "装机日志三条零命中: `deferred debt CONSUMED` 0 次 / `deferred debt HELD` 0 次 / "
    "`DeferDebt OWED` 0 次, 而 `v38A` 自身不打日志(它只是个 if), "
    "所以「一次没跑」这件事在日志里是**静默**的。代码结构给出原因 —— "
    "v18 段里两个 if 用的是**同一个判据**, 且**撑高在前、自愈在后**: "
    "  撑高(v18 原有): `if let _sv = superview, _sv.frame.size.height < _needH - 0.5` "
    "  自愈(v38-A):    `_svH = superview?.frame.size.height; _svH < _needH - 0.5` "
    "⇒ 判据成立时高度**已经被撑到 _needH**, 自愈判据必然为假; "
    "⇒ 判据不成立时自愈判据也必然为假。**两个分支都指向「永不执行」**, "
    "而代码读起来完全正常, 注释还写着「已尝试把 frame/superview 撑到它」。 "
    "★这就是为什么我之前把锅甩给 SKIP-DEDUPE 是错的: "
    "  `storageLen=57 measureW=358 tcW=358 lastH=49.0` 那 11 条 SKIP-DEDUPE "
    "  是**别的调用者**(流式增量/复用链)在打, 与 v38-A 无关 —— "
    "  v38-A 根本没走到自己借 flag 的那一步, 没资格产生任何日志。 "
    "【这一条同时解释了用户说的「大部分都是**新的会话第一段**就卡」】"
    "首段定型之后, 唯一可能纠正欠账的那道自愈门**从来就没开过**, "
    "于是此后每次 invalidateCell 都被指纹说「和上次一样」跳过。 "
    "【修法: 让自愈判据在「撑高之前」取样, 与撑高判据错开】"
    "在 v18 段进入测高循环**之前**先把 superview 高存成快照 `_v52PreSVH`, "
    "自愈改用这个**进入时的旧高度**做判据。这样两种情形都能各走各的: "
    "  · 撑高前就欠账(375.7 那个 cell: 旧 26.7 / 需 49.0) → 撑高执行, 自愈也执行 "
    "  · 撑高前已经够高(v51 之后绝大多数帧) → 两者都不执行, **稳态零开销** "
    "★判据用旧值不是新值, 是这段修法唯一的巧思所在: "
    "  它让「撑高」与「自愈」在**逻辑上不再互斥**, 而两者合起来才完整 —— "
    "  撑高改的是**结果**(superview.frame), 自愈走的是**诉求**(cell 高度提交链), "
    "  v18 单靠自己赢不了 SwiftUI 的布局 pass, 缺的正是自愈那一半。 "
    "★登记必须排在 v38-A 之后(锚点是 v38-A 的标记行)"
)


def fix_width_sane_gate_v52(t):
    """v52-A+B+C: 宽度合理性闸门 + _svW 改读 frame + 来源诊断探针。

    ── 归因(minis-2026-10-04.log, 装机 v51 后)────────────────────────

    v51-A **生效了**但不是根因:

      · V51-FRAMEPIN `fvW=tcW=svW=358` 占 143/146 零例外
        ⇒ 钉 frame 宽确实写进去了, v50 的「画字视图比父容器宽 32pt」消失
      · 而用户症状一字未改 ⇒ 换靶

    新靶是宽度 **375.7**(v50 日志 0 次, v51 日志 61 次, 全集中在 len=57):

      · v18 段 `min(_svW, _cvW)` 把 375.7 当净宽(因为 _cvW 恒 390)
      · 该宽下排 1 行(tcH=18.7), 358 下需 2 行(needH=49.0)
      · ⇒ `V41-DEBT svH=26.7 needH=49.0 debt=22.3 hits=6` 反复欠账
      · ⇒ 屏幕上「最后一行被裁」

    ── 三条排除法确认 375.7 是过渡态而非合法布局宽 ───────────────────

      ① insetL 全日志恒 0.0 ⇒ 不是内边距算出来的
      ② 390-375.7 = 14.3 ⇒ 不是任何整数边距
      ③ 首次出现前 5ms 恰有 `REJECT-NAN-INF-NEG size=0.0x-8.0`(全日志 77 次)
         ⇒ 那一瞬 superview 几何是脏的

    ── A: 闸门(不动 min 公式)────────────────────────────────────────

    落点在 `let _svW = ...` 那一行**之后**、`var _realW =` 之前。
    不改 `min(_svW, _cvW)` 那条语句本身 —— v34 判据的语义边界钉在它上面。

    闸门规则: 候选宽必须落在「上次已知良好宽度 ±2」或「全宽 ±2」内,
    否则回落到 `ios15LastSaneContentW`(新记忆位, 只记被闸门放行过的值)。

    ★为什么是「回落」而不是「直接用 cvW」: cvW=390 是全屏宽, 拿来当净宽
      等于回到 v13/v34 翻车过的「超框排版」。回落目标是**上一次排版正确时
      用过的宽度**, 那才是真正的正确答案。

    ── B: _svW 改读 frame(与 _svf0 同源)───────────────────────────

    ★本轮修正一条自己的错判: 最初以为「bounds 偶发 375.7 而 frame 恒 358」,
    装机日志核对后**不成立** —— V41-DEBT 读的正是 frame.size.width, 也报 375.7。
    ⇒ frame 同样被污染, B 单独做无效。
    B 合并后的独立价值: 与 `_svf0` 同源, 闸门判据与污染修复同字段,
    杜绝「A 读 frame / B 读 bounds」那种同帧不同值的跨字段不自洽。
    """
    # [幂等·纪律 51/52] 必须在**任何注入动作之前**检查, 且用**产物标记**。
    # 本函数原先把判据放在注入点之后 ⇒ 第二次运行时第一处已又插了一份,
    # verify 的「标记数==1」断言报成「实际 2」—— 报错文案指向错误方向。
    if 'NSLog("[V52-GATE]' in t:
        return t

    if "// [V52-GATE]" in t:
        return t

    # ---- ① 记忆位声明(必须最先做: 下面的 Swift 代码已引用它) ----
    #
    # 【锚点为什么是 v49 的属性而不是 v47 的 ios15LastSaneSVFrame】
    # v47 那一处(DECL_OLD)已经被 v49 的注入点消费过了 —— v49 把它当
    # `DECL_ANCHOR` 插在 `/// [V47-WSTATE]` **之前**。再拿它当锚点虽然还能
    # 命中(那段文本还在), 但会在 v49 插的那段之前插属性, 顺序乱掉。
    # `var ios15V18W: CGFloat = -1` 是 v49 注入块的**首行**, 在 v52 之前
    # 必然已存在, 且不会再被后续版本消费 —— 这才是硬约束下的安全锚点。
    DECL_OLD = "    var ios15V18W: CGFloat = -1\n"
    DECL_NEW = DECL_OLD + """    /// [V52-SANEW] 上一次**通过宽度合理性闸门**的排版净宽。v52 遇到
    /// 脏几何帧(实测 375.7)时回落到它, 而不是回落到全屏宽 390。
    /// 只有闸门放行的值才允许写入 ⇒ 记忆位本身永远干净。
    var ios15LastSaneContentW: CGFloat?
"""
    if DECL_OLD not in t:
        raise RuntimeError(
            "fix_width_sane_gate_v52: 未找到 `var ios15V18W` 声明锚点 —— "
            "v49 结构变了, 必须更新 DECL_OLD 后再发版。"
            "★记忆位声明缺失会导致注入的 Swift 引用到未声明的标识符, "
            "而编译报错指向 v52 那几行, 真正的原因在几百行之外")
    t = t.replace(DECL_OLD, DECL_NEW, 1)

    # ---- 落点: _svW 的读取行之后 ----
    ANCHOR = """            let _svW = superview?.bounds.width ?? 0
"""
    if ANCHOR not in t:
        raise RuntimeError(
            "fix_width_sane_gate_v52: 未找到 `_svW` 读取行 —— "
            "v18 段结构变了?(v34 起这一行就没动过)")
    if t.count(ANCHOR) != 1:
        raise RuntimeError(
            "fix_width_sane_gate_v52: _svW 读取行不唯一(命中 %d 处) —— "
            "盲改会改到别的视图上" % t.count(ANCHOR))

    NEW = """            // [V52-B] 宽度改读 **frame** 而非 bounds。
            // ★与同段上面的 `_svf0`(supview?.frame)同源 —— 闸门判据与污染修复
            //   读同一个字段, 不会同帧不同值。
            // ★本轮修正一条自己的错判: 装机前我以为"bounds 偶发 375.7 而 frame
            //   恒 358", 但 V41-DEBT 读的正是 frame.size.width, 它也报 375.7
            //   ⇒ frame 同样被污染, 单改这里无效。真正的价值是**同源**。
            let _v52frmW = superview?.frame.size.width ?? 0
            // [V52-GATE] 宽度合理性闸门 —— 见函数 docstring 的三条排除法。
            //
            // 背景: 装机日志里 `_cvW` 恒 390, 而 v18 的 `min(_svW, _cvW)` 会把
            // 任何 < 390 的候选值**原样当成净宽**。SwiftUI 递归排版的某一瞬
            // 给过 375.7 这个过渡宽度, 于是 textContainer 与 frame 全被钉到
            // 375.7, 文字排成 1 行(tcH=18.7), 而按 358 排需要 2 行(49.0)
            // ⇒ superview 只给 26.7 高 ⇒ 末行被裁 22.3pt。
            //
            // 规则: 候选宽必须「接近上一次已知良好宽度」或「接近全屏宽」,
            // 否则**回落到上一次已知良好的宽度**, 一个字节都不写进渲染链。
            // ★健康帧上闸门恒真(358 就在白名单里), 稳态零行为变化 ——
            //   这是**只读判据 + 回落**, 不是新的抢宽时机。
            var _v52w = _v52frmW > 1 ? min(_v52frmW, _cvW) : _cvW
            var _v52sane = 1
            if _edgeTouch {
                // 贴边态: 目标净宽就是 cvW-32(inset 16/16 已在上面设好)。
                if abs(_v52w - (_cvW - 32)) > 2 {
                    _v52w = _cvW - 32
                    _v52sane = 0
                }
            } else {
                var _v52ok = abs(_v52w - _cvW) <= 2
                if !_v52ok, let _v52last = ios15LastSaneContentW, _v52last > 100 {
                    _v52ok = abs(_v52w - _v52last) <= 2
                }
                if !_v52ok {
                    // 回落: 上一次排版正确时用过的宽度。都没有就用全屏宽减内边距。
                    _v52w = ios15LastSaneContentW ?? (_cvW - 32)
                    _v52sane = 0
                }
            }
            if _v52sane != 0, _v52w > 100, abs(_v52w - _cvW) > 2 {
                ios15LastSaneContentW = _v52w
            }
            // [V52-PROBE] 宽度来源诊断 —— 见 MSG_V52_C。
            do {
                struct _GLog { static var last: CFTimeInterval = 0 }
                let _gn = CACurrentMediaTime()
                if _gn - _GLog.last > 0.5 {
                    _GLog.last = _gn
                    NSLog("[V52-GATE] rawW=%.1f frmW=%.1f cvW=%.1f edge=%d sane=%d picked=%.1f len=%d",
                          superview?.bounds.width ?? -1, _v52frmW, _cvW,
                          _edgeTouch ? 1 : 0, _v52sane, _v52w, self.textStorage.length)
                }
            }
            let _svW = _v52w
"""
    t = t.replace(ANCHOR, NEW, 1)
    verify_width_sane_gate_v52(t)
    return t


def verify_width_sane_gate_v52(t):
    """校验 v52-A/B/C —— 独立成函数。"""
    # ---- 记忆位声明必须存在且是实例属性 ----
    # ★必须是**实例属性**而不是 `nonisolated(unsafe) static var`:
    #   净宽是**每个 textView 各自**的排版事实(同一屏可能有 358 和 326 两种
    #   气泡宽度), 进程级单例会让并存的两种宽度互相污染记忆位。
    if not re.search(r"^    var ios15LastSaneContentW: CGFloat\?$",
                     t, re.M):
        raise RuntimeError(
            "verify_width_sane_gate_v52: ★记忆位 `ios15LastSaneContentW` "
            "未声明 —— 注入的 Swift 会引用到不存在的标识符。"
            "必须是**实例属性**(每 textView 一份), 不能是 static")
    if "static var ios15LastSaneContentW" in t:
        raise RuntimeError(
            "verify_width_sane_gate_v52: 记忆位不能是 static —— "
            "同屏并存的两种气泡宽度会互相污染")

    for tag in ("// [V52-GATE]", "// [V52-B]", "// [V52-PROBE]"):
        if t.count(tag) != 1:
            raise RuntimeError(
                "verify_width_sane_gate_v52: 标记 %s 计数应为 1, 实为 %d"
                % (tag, t.count(tag)))

    # ---- B: 原 bounds 读法必须已被替换, 且不得残留 ----
    if "let _svW = superview?.bounds.width ?? 0" in t:
        raise RuntimeError(
            "verify_width_sane_gate_v52: ★`_svW` 仍在读 bounds —— B 没生效。"
            "注意: 光把新行插在下面而没删旧行, Swift 会因重复声明 `_svW` "
            "编译失败(而且这个失败信息不指向真正原因)")
    if "let _svW = _v52w" not in t:
        raise RuntimeError(
            "verify_width_sane_gate_v52: ★找不到 `let _svW = _v52w` —— "
            "新块与后续代码的衔接断了")

    i = t.find("// [V52-B]")
    if i < 0:
        raise RuntimeError("verify_width_sane_gate_v52: [V52-B] 段缺失")
    # 段右界: `let _svW = _v52w` 之后的第一条 v18 原生语句。
    #
    # ★不能用 `// [V48-PIN]` 当右界(第一版就是这么写的, 当场被自检拦下):
    #   V48-PIN 在 v52 块**下方约 60 行**, 中间夹着 v18 原有的
    #   `textContainer.size.width = _realW` / `frame = _rf` 等写入 ——
    #   那些是 v18 的既有行为, 不是 v52 干的, 却被算进"闸门段",
    #   于是「段内零几何写」判据报出 textContainer 宽高(第一版真报出来了)。
    #   **判据的段边界必须紧贴被测代码**, 宁可窄不可宽: 段开大了会把
    #   上游合法写入算成自己的罪, 段开小了才会漏判(漏判可由 A2 补齐)。
    # ★v53 起: 右界改回 `let _svW = _v52w`, 并在计数时**剔除 v53 探针**。
    #
    # 【这一条改了三轮才改对, 值得完整记下来】
    #   v53 的 C1 块(记忆位写入修复)物理上插在 v52 探针**之前** ——
    #   产物行号: [V52-B] 8144 → [V53-MEM] 8240 → [V52-PROBE] 8246
    #   → [V52-GATE] NSLog 8252 → `let _svW = _v52w` 8257。
    #   于是 v52 段区间里天然含着 v53 的那条 NSLog:
    #     ① 收窄到 `[V53-C1]`(v53 在闸门内部也有一个同名标记, 8218 行)
    #        ⇒ 闸门段被切成两半, 三个判据全报「不见了」。
    #     ② 改用代码锚点 `let _v53memW`(8216) ⇒ 又把 v52 自己的记忆位
    #        写入守卫(8229)切到段外, 报「守卫的 if 头不见了」。
    #     ③ 改用 `// [V53-MEM]` ⇒ 产物里该标记在**字符串内**
    #        (`NSLog("[V53-MEM] ...`), 注释形式永远匹配不到,
    #        find 返回 -1 ⇒ 段一路开到文件末尾, NSLog 计数爆 8。
    #     ④ 收窄到字符串锚点 `'[V53-MEM]'` ⇒ 把 v52 自己的
    #        `[V52-GATE]` 探针(8252, 在 8240 **之后**)切掉,
    #        报「诊断缺字段 rawW=」。
    #   ⇒ 纪律: **段右界要选在「自己这版最后一个标记」之后**
    #     (`let _svW = _v52w` 正好在 v52 探针之后), 而不是「下一版第一个
    #     标记之前」—— 后者在新版把自己的探针插到旧版探针**之前**时,
    #     必然切掉旧版探针。
    #   ⇒ 纪律: **跨版共存的计数类判据要按标记剔除, 不靠区间** ——
    #     v53 的探针合法地落在 v52 的区间内, 那是两个版本的判据范围重叠,
    #     不是任何一方写错了位置。
    #   ⇒ 纪律: **锚点先在产物里 grep 一遍确认逐字存在**(连注释/字符串
    #     的归属一起确认), 再写进判据。
    i_end = t.find("let _svW = _v52w", i)
    if i_end < 0:
        # 无 v53(老产物)时回落到原锚点, 保持向后兼容。
        i_end = t.find("var _realW = _svW > 1 ? min(_svW, _cvW) : _cvW", i)
    if i_end < 0:
        raise RuntimeError(
            "verify_width_sane_gate_v52: 段未闭合(找不到 `[V53-MEM]` 或 v18 的 "
            "`var _realW =` 收尾行) —— v52 块与后续代码的衔接断了")
    seg = t[i:i_end]
    code = _strip_swift_noise(seg)

    # ---- A2: 判据必须齐全, 且**接在 if 头上** ----
    #
    # ★本轮被 reverse_v52 的 S4 证伪过一次: 第一版只查这三行**文本存在**,
    #   而 S4 把 `if !_v52ok, let _v52last = ..., _v52last > 100 {` 换成
    #   `if !_v52ok {` —— 下面那行 `abs(_v52w - _v52last) <= 2` 纹丝不动,
    #   判据全绿, 而闸门已经**不再与记忆位比对**了(任何宽度都算健康)。
    #   ⇒ 纪律: **查「表达式存在」不等于查「判据生效」**, 必须查**数据流**:
    #     变量得由那个 `if` 守卫, 才有资格参与判断。
    for pat, why in (
            ("abs(_v52w - (_cvW - 32)) > 2", "贴边分支的容差判据"),
            ("abs(_v52w - _v52last) <= 2", "记忆位对照判据"),
            ("abs(_v52w - _cvW) <= 2", "全宽白名单判据")):
        if pat not in code:
            raise RuntimeError(
                "verify_width_sane_gate_v52: ★%s 不见了 —— 闸门必须在"
                "三处都留判据, 少一处就会误回落健康帧" % why)
    for head, why in (
            ("if _edgeTouch {", "贴边分支"),
            ("if !_v52ok, let _v52last = ios15LastSaneContentW, _v52last > 100 {",
             "记忆位对照分支(S4 破坏点: 守卫被摘掉, 判据成死代码)"),
            ("if !_v52ok {", "回落分支"),
            ("if _v52sane != 0, _v52w > 100,", "记忆位写入守卫")):
        if head not in code:
            raise RuntimeError(
                "verify_width_sane_gate_v52: ★%s 的 if 头不见了 —— "
                "判据行还在但守卫没了, 等于**死代码**(与 v38-A 同一个病)"
                % why)

    # ---- A4: 回流量必须真用记忆位, 不能悄悄改成全屏宽 ----
    #
    # ★同样被 S7 证伪: A2 三处判据齐全时, 把 `_v52w = ios15LastSaneContentW
    #   ?? (_cvW - 32)` 改成 `_v52w = _cvW` 也能过 A2 —— 因为三条判据都还在,
    #   只是不再被**用**到。那样污染帧会回落到全屏宽 390, 正是 v13/v34
    #   「超框排版」翻车的形态, 而判据全绿。
    # ⇒ 纪律: 判据要覆盖**回流的取值来源**, 不只是判据本身在不在。
    if not re.search(r"_v52w\s*=\s*ios15LastSaneContentW\s*\?\?", code):
        raise RuntimeError(
            "verify_width_sane_gate_v52: ★回落已不取记忆位(可能被改成 "
            "`_v52w = _cvW`)—— 污染帧会回落到全屏宽 390, "
            "那是 v13/v34 超框排版的翻车形态")

    # ---- A1: 闸门段内只许写 _v52w / 记忆位 / 诊断, 禁碰任何真实几何 ----
    for pat, why in (
            (r"textContainer\.size(?:\.\w+)*\s*=", "textContainer 宽高"),
            (r"\bframe(?:\.\w+)*\s*=\s*[^=]", "frame 写入"),
            (r"\bbounds(?:\.\w+)*\s*=\s*[^=]", "bounds 写入"),
            (r"\.origin(?:\.\w+)*\s*=", "origin 写入"),
            (r"\.invalidateLayout\s*\(", "invalidateLayout"),
            (r"\.ensureLayout\s*\(", "ensureLayout"),
            (r"\.setNeedsLayout\s*\(", "setNeedsLayout")):
        if re.search(pat, code):
            raise RuntimeError(
                "verify_width_sane_gate_v52: ★段内出现 %s —— "
                "闸门是**只读判据 + 回落**, 不许自己动几何" % why)

    # ---- A3: 记忆位只在「闸门放行」时写 ----
    if not re.search(r"if _v52sane != 0, _v52w > 100,[^\n]*\n"
                     r"\s*ios15LastSaneContentW = _v52w", code):
        raise RuntimeError(
            "verify_width_sane_gate_v52: ★记忆位写入必须以 `_v52sane != 0` 为前提 —— "
            "否则被回落掉的污染值会污染记忆, 下一帧的对照基准就脏了")

    # ---- C: 诊断字段齐全, 且实参里真的有那个变量 ----
    #
    # ★被 reverse_v52 的 S9 证伪: 第一版只查格式串里的 `sane=`, 而 S9 把
    #   **实参**里的 `_v52sane, ` 删掉(格式符留着) —— 判据全绿, 而探针会
    #   打出**错位的值**(sane 那个 %d 读到 picked 的浮点数, 按 varargs
    #   UB 处理, iOS 15 上是乱码甚至崩), 装机日志直接失去判读价值。
    # ⇒ 纪律: 探针判据必须查**实参**而不只是格式串 —— 格式串在, 不等于
    #   那个读数还在。
    for f in ("rawW=", "frmW=", "cvW=", "edge=", "sane=", "picked=", "len="):
        if f not in seg:
            raise RuntimeError(
                "verify_width_sane_gate_v52: 诊断缺字段 %r" % f)
    for var, why in (("_v52sane,", "sane(闸门是否放行)"),
                     ("_v52w,", "picked(最终采用的宽)"),
                     ("_v52frmW,", "frmW(frame 读数)"),
                     ("_cvW,", "cvW(全屏宽)"),
                     ("_edgeTouch ? 1 : 0,", "edge(贴边态)")):
        if var not in seg:
            raise RuntimeError(
                "verify_width_sane_gate_v52: ★诊断实参里没有 %s —— 格式符还在, "
                "但那个读数已经被删了, 装机日志会错位(varargs UB)" % why)
    # ★计数要**排除 v53 的探针**: v53 的 C1 块物理上落在本段区间内
    #   (它插在 v52 探针之前), 所以 `seg.count("NSLog(")` 会把
    #   `[V53-MEM]` 那条一起数进去, 报 2 条。按标记文本精确剔除,
    #   不靠位置猜 —— 位置在新版插代码后会漂移, 标记不会。
    # ★v53 补 S10 的漏: 上面那个循环查的是 `code`/`seg`(剥过字符串字面量),
    #   所以 `sane=` / `picked=` 这些**格式串文本**根本不在 `code` 里 ——
    #   它命中的是实参侧的同名字样(碰巧而已)。S9 删实参被它抓住,
    #   S10 删**格式串里的 `sane=%d` 占位符**则一路绿灯放行。
    #   而占位符一少, 后面所有实参就**整体左移错位**:
    #   `picked=%.1f` 会拿 CGFloat 去读本该给整型的槽位, 按 varargs UB
    #   处理 —— 装机日志直接是乱码, 失去判读价值。
    # ⇒ 纪律: **探针判据要分两层查**: 格式串层查 `seg`(未剥噪声的原始段),
    #   实参层查 `code`(剥噪声的段)。v53 第一版把两层混在一处, 结果
    #   S9 绿、S10 漏 —— 典型的「以为查了其实没查到」。
    #   ★两层用**不同的变量**是必须的: 一旦拿同一个 `seg` 去查两层,
    #   改对一处就必然改错另一处。
    for f in ("sane=%d", "picked=%.1f", "edge=%d", "rawW=%.1f",
              "frmW=%.1f", "cvW=%.1f", "len=%d"):
        if f not in seg:
            raise RuntimeError(
                "verify_width_sane_gate_v52: ★诊断**格式串**里没有 %r —— "
                "占位符一少, 后面实参整体左移错位(varargs UB), "
                "装机日志是乱码; 格式串在 ≠ 那个读数还在, 两者都要查" % f)
    _n_v52_nslog = code.count("NSLog(")
    # ★v55 补: v55-A 的宽高分源探针物理上同样落在本段区间内(它插在 v52 探针
    #   之后), 不剔除会把计数算成 2 条。按标记文本剔除, 不靠位置 ——
    #   与上面 v53 的处理同一个理由(位置会随新版插代码漂移, 标记不会)。
    for _pk in ("[V53-MEM]", "[V53-HOLD]", "[V55-A]"):
        if 'NSLog("%s' % _pk in seg:
            _n_v52_nslog -= 1
    if _n_v52_nslog != 1:
        raise RuntimeError(
            "verify_width_sane_gate_v52: [V52-PROBE] 段内应恰好 1 条 NSLog"
            "(不计 v53 探针), 实为 %d 条" % _n_v52_nslog)
    return t


def fix_debtguard_snapshot_v52(t):
    """v52-E: 把 v38-A 从死代码里救活 —— 兜底, 治「新会话第一段就卡」。

    ── 本轮头号发现: v38-A 是一次都没执行过的死代码 ──────────────────

    装机日志三条零命中:

      deferred debt CONSUMED  0 次
      deferred debt HELD      0 次
      DeferDebt OWED          0 次

    而 v38-A 自身不打日志(它只是个 `if` + 一次函数调用), 所以「一次没跑」
    这件事在日志里是**完全静默**的 —— 只有代码结构能揭穿它。

    v18 段里两个 `if` 用的是**同一个判据**, 而且**撑高在前、自愈在后**:

      撑高(v18 原有, 产物 8008):
        if let _sv = superview, _sv.frame.size.height < _needH - 0.5
      自愈(v38-A, 产物 8029-8030):
        let _svH = superview?.frame.size.height, _svH < _needH - 0.5

    ⇒ 判据成立时, 高度**已经在上一行被撑到 `_needH`**, 自愈判据必然为假
    ⇒ 判据不成立时, 自愈判据也必然为假
    ⇒ **两个分支都指向「永不执行」**

    代码读起来完全正常, 注释还写着「到这里 _needH 是权威需求高; 上面那段
    已经尝试把 frame / superview 撑到它」—— 正是这句注释掩盖了问题:
    撑过了, 所以自愈判据永远看不见「欠账」这个状态。

    ★**我上一轮把锅甩给 SKIP-DEDUPE 是错的。** `storageLen=57 measureW=358
    tcW=358 lastH=49.0` 那 11 条 SKIP-DEDUPE 是**别的调用者**(流式增量 /
    复用链 / settle hook)在打, 与 v38-A 无关: v38-A 根本没走到自己借
    `deferredCorrectionPending` 的那一步, 没资格产生任何日志。
    **教训: 「某段代码看起来该被调用」不等于「它被调用过」, 判据要落到
    它自己会产生的那条日志上。** 找不到那条日志, 就该怀疑它没跑,
    而不是去查它下游的机制。

    ★**这一条同时解释了用户说的「大部分都是新的会话第一段就卡」。**
    首段定型之后, 唯一可能纠正欠账的那道自愈门**从来就没开过**,
    于是此后每次 invalidateCell 都被指纹说「和上次一样」跳过。

    ── 修法: 判据用「进入时的旧高度」, 与撑高判据错开 ───────────────

    在测高循环**之前**把 superview 高快照成 `_v52PreSVH`,
    v38-A 改用这个快照做判据:

        · 撑高前就欠账(375.7 那个 cell: 旧 26.7 / 需 49.0) → 撑高 + 自愈都执行
        · 撑高前已经够高(v51 之后绝大多数帧)            → 都不执行, 稳态零开销

    ★「判据用旧值不用新值」是这段修法唯一的巧思所在: 它让撑高与自愈在
      **逻辑上不再互斥**。两者合起来才完整 —— 撑高改的是**结果**
      (superview.frame), 自愈走的是**诉求**(cell 高度提交链);
      v18 单靠自己赢不了 SwiftUI 的布局 pass, 缺的正是自愈那一半。

    ── 为什么不给自愈加节流 ───────────────────────────────────────────

    稳态下判据恒假(撑高前就够高), 自然零开销; 欠账态下每次 pass 调一次
    `invalidateCellSizeIfNeeded` 正是**它该做的事**(提交诉求),
    而且这条链自带 `[V30-THROTTLE] 120ms` 与 `deferSelfSizing` 双重限流。
    再叠一层节流只会让纠正更晚, 与本版目的相反。
    """
    # [幂等·纪律 51/52] 必须在**任何注入动作之前**检查, 且用**产物标记**。
    # 本函数原先把判据放在注入点之后 ⇒ 第二次运行时第一处已又插了一份,
    # verify 的「标记数==1」断言报成「实际 2」—— 报错文案指向错误方向。
    if 'NSLog("[V52-DEBT]' in t:
        return t

    if "// [V52-DEBT-PRE]" in t:
        return t

    # ---- 落点 1: 快照。必须在撑高之前, 所以钉在测高那一行之前 ----
    #
    # 【锚点为什么是 `let _needH = sizeThatFits(...)` 这一行】
    # 它是 v18 段里「算需求高」的唯一入口, 语义边界明确, 且必然早于
    # 8008 的撑高与 8029 的自愈(两者都依赖 _needH)。不能拿撑高那行当锚点:
    # 那样快照会取到「已经被撑过」的高度, 恰好是本版要避开的东西。
    SNAP_ANCHOR = """            let _needH = sizeThatFits(CGSize(width: _realW2, height: .greatestFiniteMagnitude)).height
"""
    if t.count(SNAP_ANCHOR) != 1:
        raise RuntimeError(
            "fix_debtguard_snapshot_v52: 测高行命中 %d 处(期望 1) —— "
            "v18 段结构变了, 必须更新 SNAP_ANCHOR 后再发版"
            % t.count(SNAP_ANCHOR))

    SNAP_NEW = """            // [V52-DEBT-PRE] 自愈判据用的**进入时**容器高快照。
            //
            // ★为什么必须取在撑高之前: v18 段紧跟着就把容器高撑到 _needH,
            //   所以下游任何「读当前容器高」的判据都看不到欠账状态 ——
            //   v38-A 就是这么变成死代码的(见函数 docstring)。把快照提前到
            //   这里, 撑高与自愈读的是**两个不同时刻的高度**, 于是不再互斥。
            // 纯只读快照, 不改任何几何。
            let _v52PreSVH = superview?.frame.size.height ?? 0
""" + SNAP_ANCHOR
    t = t.replace(SNAP_ANCHOR, SNAP_NEW, 1)

    # ---- 落点 2: v38-A 判据改用快照 ----
    #
    # 只换**判据的数据源**(当前高度 → 进入时快照), 借用 flag 的机制、
    # 调用时机、还原逻辑全部原样保留 —— 那是 v38-A 已经写对的 part。
    DEBT_OLD = """            if !_edgeTouch, _needH > 1, textStorage.length > 0,
               let _svH = superview?.frame.size.height, _svH > 1,
               _svH < _needH - 0.5 {
                let _v38WasPending = deferredCorrectionPending"""
    DEBT_NEW = """            if !_edgeTouch, _needH > 1, textStorage.length > 0,
               _v52PreSVH > 1,
               _v52PreSVH < _needH - 0.5 {
                // [V52-DEBT-PRE] 判据源从「当前容器高」换成「进入时快照」。
                // 撑高已把容器改到 _needH, 读当前高度永远看不见欠账 ⇒ 这道
                // 门自 v38-A 注入以来一次都没开过(装机日志 deferred debt
                // CONSUMED / HELD / DeferDebt OWED 三项全 0 次)。
                // 诊断: preSVH 是进入时的容器高, needH 是权威需求高, 二者之差
                // 即被裁掉的末行高度(装机实测 26.7 vs 49.0 ⇒ 差 22.3 ≈ 一行半)。
                // hits 若恒为 0 ⇒ 快照位置选错了(判据恒假), E 等于没做。
                struct _V52Log { static var last: CFTimeInterval = 0; static var hits: UInt = 0 }
                _V52Log.hits &+= 1
                let _v52Now = CACurrentMediaTime()
                if _v52Now - _V52Log.last > 0.5 {
                    _V52Log.last = _v52Now
                    NSLog("[V52-DEBT] preSVH=%.1f needH=%.1f debt=%.1f hits=%u len=%lu",
                          _v52PreSVH, _needH, _needH - _v52PreSVH,
                          _V52Log.hits, UInt(textStorage.length))
                }
                let _v38WasPending = deferredCorrectionPending"""
    if t.count(DEBT_OLD) != 1:
        raise RuntimeError(
            "fix_debtguard_snapshot_v52: v38-A 判据块命中 %d 处(期望 1) —— "
            "v38-A 结构变了, 必须更新 DEBT_OLD 后再发版"
            % t.count(DEBT_OLD))
    t = t.replace(DEBT_OLD, DEBT_NEW, 1)

    verify_debtguard_snapshot_v52(t)
    return t


# ====================================================================
# v53 —— 治 cell 高度欠账永久凝固(C-2) + 记忆位初始化死锁(C-1) + 首段专项
#
# ★本版归因见 MSG_V53_C2 的长篇 docstring; 一句话版本:
#   `deferred debt CONSUMED` 打印了 105 次, 而同一 tick 的 `preSVH`
#   恒为 1004.0(欠 268.3pt) —— 「宣告成功但实际未落地」的谎言就是病根。
# ====================================================================


def fix_shortcircuit_probe_v53(t):
    """v53-P + v53-C2(infra 侧): 三条滑动期高度短路各埋探针, 并在欠账「熟」后放行。

    幂等: 已注入过则原样返回。
    """
    if "// [V53-PROBE] 滑动期高度短路三来源诊断" in t:
        return t

    # ---- 1. 字段 + 探针函数插进类体 ----
    ANCHOR_F = """    private var seededHeight: CGFloat?
    private var seededWidth: CGFloat?
"""
    if ANCHOR_F not in t:
        raise RuntimeError(
            "fix_shortcircuit_probe_v53: ★找不到字段锚点 "
            "`private var seededWidth: CGFloat?` —— 类体结构变了, "
            "必须更新本函数后再发版(否则 v53 的三条短路会引用不存在的字段, "
            "编译期才炸, 装机前发现不了)")
    NEW_F = ANCHOR_F + MSG_V53_P_BLOCK
    t = t.replace(ANCHOR_F, NEW_F, 1)

    # ---- 2. A 路(dedup): 加守卫 + 埋探针 ----
    A_OLD = """        if let cached = lastComputedHeight,
           let cachedW = lastComputedWidth,
           abs(layoutAttributes.size.width - cachedW) < 1 {
            let copy = layoutAttributes.copy() as! UICollectionViewLayoutAttributes
            copy.size.width = cachedW
            copy.size.height = cached
"""
    if A_OLD not in t:
        raise RuntimeError(
            "fix_shortcircuit_probe_v53: ★找不到 A 路(dedup)锚点 —— "
            "三条短路里最短的那条变了形态, 必须更新本函数")
    A_NEW = A_OLD.replace(
        "           abs(layoutAttributes.size.width - cachedW) < 1 {",
        "           abs(layoutAttributes.size.width - cachedW) < 1,\n"
        "           // [V53-C2] 已知欠账且已持续一帧以上 ⇒ 不得返回这个欠账高度。\n"
        "           // 见 `v53NotePendingDebt` 的 docstring：不清这一条，`preSVH` 会永远\n"
        "           // 停在首次提交时的欠账值上（实测 1004.0，欠 268.3pt ≈ 8 行）。\n"
        "           !v53DebtIsRipe {") + """            // [V53-PROBE] A 路：dedup 短路命中。
            Self._v53Note(.dedup, height: cached, width: cachedW,
                           pendingDebt: v53PendingHeightDebt)
"""
    t = t.replace(A_OLD, A_NEW, 1)

    # ---- 3. B 路(滑动期 cached): 加守卫 + 埋探针 ----
    B_OLD = """            if layout.deferSelfSizing || streamingActive,
               !isStreamingItem,
               let cached = lastComputedHeight, let cachedW = lastComputedWidth,
               abs(layoutAttributes.size.width - cachedW) < 1 {
                let copy = layoutAttributes.copy() as! UICollectionViewLayoutAttributes
                copy.size.width = cachedW
                copy.size.height = cached
"""
    if B_OLD not in t:
        raise RuntimeError(
            "fix_shortcircuit_probe_v53: ★找不到 B 路(滑动期 cached)锚点 —— "
            "这条短路是「一下卡字一下不卡字」的直接开关, 形态变了必须更新")
    B_NEW = B_OLD.replace(
        "               abs(layoutAttributes.size.width - cachedW) < 1 {",
        "               abs(layoutAttributes.size.width - cachedW) < 1,\n"
        "               // [V53-C2] 同 A 路：欠账已熟时不许拿缓存高度挡住真实测量。\n"
        "               // 这条短路是滑动期「一下卡字一下不卡字」的直接开关 ——\n"
        "               // 滚动中它返回 1004（尾部裁掉），滚动停止它失效、真实测量\n"
        "               // 把高度修对，文字又完整。用户的观感就是来回闪。\n"
        "               !v53DebtIsRipe {") + """                // [V53-PROBE] B 路：滑动/流式期 cached 短路命中。
                Self._v53Note(.windowCached, height: cached, width: cachedW,
                               pendingDebt: v53PendingHeightDebt)
"""
    t = t.replace(B_OLD, B_NEW, 1)

    # ---- 4. C 路(seededHeight): 加守卫 + 埋探针 ----
    # ★C_OLD 必须**一路包到 `copy.size.height = sh`** ——
    #   探针要插在赋值**之后**(记的是即将 return 的那组值),
    #   锚点范围不够就够不着那一行。第一版只锚到 if 头就收尾,
    #   结果派生的 C_NEW 里根本没有赋值行, 探针无处可插。
    # ⇒ 纪律: **探针的锚点范围要覆盖「探针要插的那一行」**,
    #   别以为「先改 if 头, 探针另找地方插」—— 两步合成一处替换时,
    #   锚点必须一次给全, 否则中途就断了。
    C_OLD = """        if let sh = seededHeight, let sw = seededWidth,
           let cv = superview as? UICollectionView,
           abs(cv.bounds.width - sw) < 1 {
            seededHeight = nil
            seededWidth = nil
            lastComputedHeight = sh
            lastComputedWidth = layoutAttributes.size.width
            lastMeasureMediaTime = CACurrentMediaTime()
            let copy = layoutAttributes.copy() as! UICollectionViewLayoutAttributes
            copy.size.height = sh
"""
    if C_OLD not in t:
        raise RuntimeError(
            "fix_shortcircuit_probe_v53: ★找不到 C 路(seededHeight)锚点 —— "
            "这是「清缓存后旧高又回来了」的第二个来源, 形态变了必须更新")
    C_NEW = C_OLD.replace(
        "           abs(cv.bounds.width - sw) < 1 {",
        "           abs(cv.bounds.width - sw) < 1,\n"
        "           // [V53-C2] 同 A/B 路：种子高度若是欠账的那个值，不能再种回去。\n"
        "           // 实测这条是「清缓存后旧高又回来了」的第二个来源 ——\n"
        "           // configureCell 会把 memo 里的 1004 再写一次 seededHeight。\n"
        "           !v53DebtIsRipe {")
    # ★探针必须紧跟 `copy.size.height = sh`(即**赋值之后**), 不能跟在 if 头后 ——
    #   跟在 if 头后会落在 `seededHeight = nil` 之前, 记的是**还没播种**的
    #   那一刻, 装机日志的 src/w/h 三个读数全部对不上实际返回的那一份。
    #   ⇒ 纪律: 探针的位置语义是「**即将 return 的那组值**」,
    #     插在赋值之前就变成了「即将开始改的那组值」, 两者不是一回事。
    C_PROBE = "            let copy = layoutAttributes.copy() as! UICollectionViewLayoutAttributes\n            copy.size.height = sh\n"
    if C_PROBE not in C_NEW:
        raise RuntimeError(
            "fix_shortcircuit_probe_v53: ★C 路探针锚点(赋值后)不在形态内 —— "
            "C 路改了赋值位置, 必须先确认探针该插在哪一行")
    C_NEW = C_NEW.replace(C_PROBE, C_PROBE + """            // [V53-PROBE] C 路：seededHeight 短路命中。
            Self._v53Note(.seeded, height: sh, width: sw,
                           pendingDebt: v53PendingHeightDebt)
""", 1)
    t = t.replace(C_OLD, C_NEW, 1)
    return t


def verify_debtguard_snapshot_v52(t):
    """校验 v52-E —— 独立成函数。"""
    if t.count("// [V52-DEBT-PRE]") != 2:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: [V52-DEBT-PRE] 标记应为 2 处"
            "(快照 + 判据), 实为 %d 处" % t.count("// [V52-DEBT-PRE]"))

    # ---- 快照必须在测高之前, 且是只读 ----
    i_snap = t.find("// [V52-DEBT-PRE]")
    i_need = t.find("let _needH = sizeThatFits(CGSize(width: _realW2,", i_snap)
    if i_need < 0:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: 快照之后找不到测高行 —— "
            "快照必须早于测高, 否则拿到的已是撑过的高度")
    seg_snap = t[i_snap:i_need]
    if "let _v52PreSVH = superview?.frame.size.height ?? 0" not in seg_snap:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: 快照变量定义缺失或不在测高之前")
    # 快照段内零几何写
    for pat, why in (
            (r"\bframe(?:\.\w+)*\s*=\s*[^=]", "frame 写入"),
            (r"\bbounds(?:\.\w+)*\s*=\s*[^=]", "bounds 写入"),
            (r"\.invalidateLayout\s*\(", "invalidateLayout"),
            (r"\.setNeedsLayout\s*\(", "setNeedsLayout")):
        if re.search(pat, seg_snap):
            raise RuntimeError(
                "verify_debtguard_snapshot_v52: ★快照段内出现 %s —— "
                "快照必须是纯只读" % why)

    # ---- 判据必须已改用快照, 且旧的「读当前高度」写法不得残留 ----
    # 段起点: 条件行在第二个 [V52-DEBT-PRE] 标记**之前**(标记在 if 体内部),
    # 所以必须往上回退到 `if !_edgeTouch` 那一行, 否则段切窄了会漏掉判据 ——
    # 「段太宽会误伤上游代码」已由右界收紧解决, 「段太窄会漏判」只能靠起点回退。
    i_debt = t.find("// [V52-DEBT-PRE]", i_need)
    if i_debt < 0:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: 判据段缺失 —— "
            "v38-A 块没被找到, 结构可能变了")
    i_start = t.rfind("if !_edgeTouch, _needH > 1, textStorage.length > 0,",
                      i_need, i_debt)
    if i_start < 0:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: 判据段的 if 头没找到 —— "
            "段起点比标记还早, 段切错了")
    # 段右界用下游紧邻的稳定锚点, 不用 [V48-PIN](它在更下方, 会把 v18
    # 原有代码算进本段 —— 同一个坑, verify_width_sane_gate_v52 第一版踩过)。
    i_end = t.find("if _didFix {", i_debt)
    if i_end < 0:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: 判据段未闭合(找不到 v18 的 "
            "`if _didFix {` 收尾行) —— v38-A 块结构可能变了")
    seg = t[i_start:i_end]

    if "let _svH = superview?.frame.size.height" in seg:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: ★判据仍在读**当前**容器高 —— "
            "撑高已把它改到 _needH, 这道门就还是死的(那正是 v38-A 失效的原因)")
    if "_v52PreSVH < _needH - 0.5" not in seg:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: ★判据未改用快照 `_v52PreSVH` —— "
            "E 没有生效")

    # ---- 借用 flag 的机制必须原样保留(那是 v38-A 已写对的部分) ----
    for pat, why in (
            ("let _v38WasPending = deferredCorrectionPending",
             "旧 pending 值的保存"),
            ("deferredCorrectionPending = true", "置位以绕指纹早退"),
            ("invalidateCellSizeIfNeeded()", "真正的诉求侧提交"),
            ("deferredCorrectionPending = _v38WasPending", "用完还原")):
        if pat not in seg:
            raise RuntimeError(
                "verify_debtguard_snapshot_v52: ★%s 不见了 —— "
                "v38-A 的借用机制是已验证可用的部分, 只该换判据源, 不该动它"
                % why)

    # ---- 诊断字段 ----
    for f in ("preSVH=", "needH=", "debt=", "hits=", "len="):
        if f not in seg:
            raise RuntimeError(
                "verify_debtguard_snapshot_v52: 诊断缺字段 %r" % f)
    if seg.count("NSLog(") != 1:
        raise RuntimeError(
            "verify_debtguard_snapshot_v52: 判据段应恰好 1 条 NSLog, "
            "实为 %d 条" % seg.count("NSLog("))
    return t


def fix_memgate_deadlock_v53(t):
    """v53-C1: 打破 v52-A 的记忆位初始化死锁, 并拒绝污染宽度进记忆位。

    幂等: 已注入过则原样返回。

    ★本函数只做**一处**替换, 从 `var _v52sane = 1` 后一直换到 v52 记忆位
      写入那行结束 —— 因为 `_v52ok` 的暴露(声明上移 + 贴边分支置 false +
      else 分支去声明化)与 `_v53memW` 的插入是**同一段连续文本**,
      拆成两次替换必然出现「第二次的锚点已被第一次吃掉」。
      ⇒ 纪律: **同一段文本上的多处改动合成一次替换**;
        分多次替换时, 后一次的锚点必须落在前一次**没碰过**的区间里,
        且要显式验证这一点(本版第一版就漏了, 报「锚点失效」)。
    """
    if "// [V53-C1] 把闸门的判别结论暴露给下面的记忆位写入逻辑。" in t:
        return t

    # ★锚点右界是 `// [V52-PROBE]` 那一行**之前** —— 不能多吃也不能少吃:
    #   多吃会把 v52 自己的探针一起换掉(它的段右界依赖 v52 判据);
    #   少吃会漏掉 v53 的 [V53-MEM] 探针。
    ANCHOR = """            var _v52w = _v52frmW > 1 ? min(_v52frmW, _cvW) : _cvW
            var _v52sane = 1
            if _edgeTouch {
                // 贴边态: 目标净宽就是 cvW-32(inset 16/16 已在上面设好)。
                if abs(_v52w - (_cvW - 32)) > 2 {
                    _v52w = _cvW - 32
                    _v52sane = 0
                }
            } else {
                var _v52ok = abs(_v52w - _cvW) <= 2
                if !_v52ok, let _v52last = ios15LastSaneContentW, _v52last > 100 {
                    _v52ok = abs(_v52w - _v52last) <= 2
                }
                if !_v52ok {
                    // 回落: 上一次排版正确时用过的宽度。都没有就用全屏宽减内边距。
                    _v52w = ios15LastSaneContentW ?? (_cvW - 32)
                    _v52sane = 0
                }
            }
            if _v52sane != 0, _v52w > 100, abs(_v52w - _cvW) > 2 {
                ios15LastSaneContentW = _v52w
            }
"""
    if ANCHOR not in t:
        raise RuntimeError(
            "fix_memgate_deadlock_v53: ★找不到 v52 闸门段锚点 —— "
            "v52-A 的形态变了(可能已被本版之外的改动碰过), 必须更新本函数。"
            "注意: 只改判据文本不改形态时, 锚点仍应命中; 命中不了说明"
            "**形态**变了, 别去改判据文本")
    t = t.replace(ANCHOR, BLOCK_V53_C1, 1)
    return t


def fix_debtgate_verifiable_v53(t):
    """v53-C2(markdown view 侧): 上报欠账给 cell + CONSUMED 判据改成可验证。

    幂等: 已注入过则原样返回。
    """
    if "func _v53ReportDebtToCell(" in t:
        return t

    # ---- 1. 上报入口, 紧跟 findCell() ----
    F_OLD = """    private func findCell() -> UICollectionViewCell? {
        var view: UIView? = superview
        while let v = view {
            if let cell = v as? UICollectionViewCell { return cell }
            view = v.superview
        }
        return nil
    }
"""
    if F_OLD not in t:
        raise RuntimeError(
            "fix_debtgate_verifiable_v53: ★找不到 findCell 锚点 —— "
            "它在别的文件或已改形态, 上报入口没有落脚点")
    t = t.replace(F_OLD, F_OLD + "\n" + BLOCK_V53_C2_REPORT, 1)

    # ---- 2. E 判据处: 上报欠账 / 清账时复位 ----
    #
    # ★右界必须是 `deferredCorrectionPending = _v38WasPending` 那一行 ——
    #   它是 v52 借 flag 机制的**末尾标记**, 左界是 `let _v38WasPending`。
    #   这两行夹起来的整块就是 v52-E 的全部动作, 我们只在 `invalidateCellSizeIfNeeded()`
    #   前后加东西, 不改它。
    E_OLD = """                let _v38WasPending = deferredCorrectionPending
                // 借上游既有开关绕过 SKIP-DEDUPE 指纹早退(该 flag 的既有语义就是
                // "有欠账, 不许被指纹吞掉")。用完立刻还原, 不污染 deferSelfSizing 那条路。
                deferredCorrectionPending = true
                invalidateCellSizeIfNeeded()
                deferredCorrectionPending = _v38WasPending
            }
"""
    if E_OLD not in t:
        raise RuntimeError(
            "fix_debtgate_verifiable_v53: ★找不到 E 判据锚点 —— "
            "欠账上报必须紧贴 `invalidateCellSizeIfNeeded()` 之前, "
            "位置变了要先确认上报还拿不拿得到差值")
    # ★E_OLD 尾部那行 `deferredCorrectionPending = _v38WasPending` 之后紧跟
    #   一个 `}`(收束整个 if/else), 所以 E_NEW 必须把它**连同那个 } 一起**
    #   重写 —— 只在 `invalidateCellSizeIfNeeded()` 前后插东西的话,
    #   新加的 `} else {` 会多出一层, 恢复行也会出现两次。
    E_NEW = E_OLD.replace(
        "                invalidateCellSizeIfNeeded()\n"
        "                deferredCorrectionPending = _v38WasPending\n"
        "            }\n",
        BLOCK_V53_C2_E + "                invalidateCellSizeIfNeeded()\n"
        "                deferredCorrectionPending = _v38WasPending\n"
        "            } else {\n" + BLOCK_V53_C2_CLR + "            }\n")
    t = t.replace(E_OLD, E_NEW, 1)

    # ---- 3. CONSUMED 判据: 改成「cell 实际高达标」才算还清 ----
    C_OLD = """                if applyCellCorrection() {
                    cellSizeLogger.info("[invalidateCell] deferred debt CONSUMED — view height stable at \\(String(format: "%.1f", newHeight)), cell invalidated")
                    deferredCorrectionPending = false
                } else {
"""
    if C_OLD not in t:
        raise RuntimeError(
            "fix_debtgate_verifiable_v53: ★找不到 CONSUMED 判据锚点 —— "
            "这一段是 v53-C2 的核心, 形态变了必须重新确认判据")
    t = t.replace(C_OLD, BLOCK_V53_C2_CONSUMED, 1)
    return t


def fix_first_para_settle_v53(t):
    """v53-FIRST: settle 入口不再依赖已被空转清掉的 flag。

    幂等: 已注入过则原样返回。
    """
    if "// [V53-DEBT] 判据源从「flag 是否为 true」换成" in t:
        return t

    S_OLD = """    func consumeDeferredCorrectionIfNeeded() {
        guard deferredCorrectionPending else { return }
        // [T-ios-defer-debt-offscreen] `attached` distinguishes the two
        // consumers in the log: settle (window != nil, the cell was visible)
        // vs the new re-attach replay (this view just came back on screen
        // still owing a correction — the case that previously had no consumer).
        cellSizeLogger.info("[DeferDebt] CONSUME — paying deferred correction attached=\\(self.window != nil)")
        invalidateCellSizeIfNeeded()
    }
"""
    if S_OLD not in t:
        raise RuntimeError(
            "fix_first_para_settle_v53: ★找不到 settle 入口锚点 —— "
            "首段专项依赖在此改判据源, 形态变了必须重新确认")
    t = t.replace(S_OLD, "    func consumeDeferredCorrectionIfNeeded() {\n"
                  + BLOCK_V53_FIRST + "    }\n", 1)
    return t


def verify_shortcircuit_probe_v53(t, infra):
    """校验 v53-P —— 滑动期高度短路三来源探针(infra = MessageListInfrastructure.swift)。"""
    F = "verify_shortcircuit_probe_v53"

    # ---- 枚举与计数器必须存在 ----
    for pat, why in (
            ("case none = 0, dedup = 1, windowCached = 2, seeded = 3",
             "四值枚举是探针的判读基础(装机日志靠 src 数字区分来源)"),
            ("private static var _v53DedupHit: UInt = 0",
             "A 路累计计数缺失 ⇒ 无法证明 A 是否吞掉了全部"),
            ("private static var _v53WindowHit: UInt = 0",
             "B 路累计计数缺失 ⇒ 无法区分 A/B 各自贡献"),
            ("private static var _v53SeededHit: UInt = 0",
             "C 路累计计数缺失 ⇒ seeded 是否又把旧高塞回来无法判读"),
            ("private static var _v53LiveMeasure: UInt = 0",
             "真实测量计数缺失 ⇒ 无法确认短路是否真被绕过(必须有 live > 0)")):
        if pat not in infra:
            raise RuntimeError("%s: ★%s —— %s" % (F, pat, why))

    # ---- 探针函数 ----
    if "private static func _v53Note(" not in infra:
        raise RuntimeError("%s: ★探针函数 `_v53Note` 缺失" % F)
    for f in ("dedup=", "window=", "seeded=", "live=",
              "src=", "h=%.1f", "w=%.1f", "debt=%.1f"):
        if f not in infra:
            raise RuntimeError(
                "%s: 探针缺字段 %r —— 装机判据要靠它区分三来源并核对欠账"
                % (F, f))

    # ---- 三条短路各埋一次, 且恰好一次 ----
    for tag, src in (("// [V53-PROBE] A 路", ".dedup"),
                     ("// [V53-PROBE] B 路", ".windowCached"),
                     ("// [V53-PROBE] C 路", ".seeded")):
        if infra.count(tag) != 1:
            raise RuntimeError(
                "%s: 标记 %s 计数应为 1, 实为 %d —— 三条短路必须各埋一次, "
                "少埋则该路径的命中数永远为 0, 装机无法判读"
                % (F, tag, infra.count(tag)))
        i = infra.find(tag)
        j = infra.find("Self._v53Note(%s" % src, i)
        if j < 0 or j - i > 400:
            raise RuntimeError(
                "%s: 标记 %s 之后 400 字符内未见对应的 _v53Note(%s —— "
                "探针与它标注的短路不是同一处, 装机日志会把来源标错"
                % (F, tag, src))

    # ---- 零行为改动: 探针不得改变任何 return ----
    for tag in ("// [V53-PROBE] A 路", "// [V53-PROBE] B 路",
                "// [V53-PROBE] C 路"):
        i = infra.find(tag)
        seg = _strip_swift_noise(infra[i:i + 420])
        if "return" in seg.replace("return copy", ""):
            raise RuntimeError(
                "%s: 探针段内出现 return —— P 是**只读诊断**, "
                "改动返回值会让「探针影响被测对象」, 判据失去意义" % F)

    # ★S13 补漏: 只抓 `return` 关键字**不够**。
    #   sabotage 把 `copy.size.height = cached` 改成 `cached * 1.5` ——
    #   `return copy` 一个字都没动, 「零 return 改动」检查完全放行,
    #   但短路已经变成「返回 1.5 倍缓存高度」, 探针成了干扰源。
    #   ⇒ 必须把**高度赋值的右值**也锁死: 每条短路只能原样返回它自己
    #   宣称要返回的那个值(A/B = lastComputedHeight, C = seededHeight)。
    #
    # ★段右界必须用「**本路探针标记之后**的第一个 return copy」,
    #   不能用「if 头之后 N 字符内」—— 后者的 N 会被路上那 20 多行
    #   解释性注释顶破, 而注释长度是随版本漂移的, 边界迟早误抓。
    #   v53 第二版就栽在这: 先取 900 字符, S13 破坏后右界刚好多 6 个字符
    #   就越界, 报了个假理由(段右界抓错)把 sabotage 拦住 ——
    #   拦住它的不是我们要的右值检查, 判据等于没测到点子上。
    #   改成「探针之后第一个 return copy」后, 边界只取决于代码结构本身。
    #   字符上限仅作「段没飞出去」的兜底: 实测 A/B/C 分别是 570/198/170,
    #   取 800 留足余量。真正的正确性保障是下一条**语义**校验。
    for head_anchor, tag, allowed, why in (
            ("if let cached = lastComputedHeight,",
             "// [V53-PROBE] A 路", "cached",
             "A(dedup) 必须原样返回 lastComputedHeight"),
            ("if layout.deferSelfSizing || streamingActive,",
             "// [V53-PROBE] B 路", "cached",
             "B(滑动期 cached) 必须原样返回 lastComputedHeight"),
            ("if let sh = seededHeight, let sw = seededWidth,",
             "// [V53-PROBE] C 路", "sh",
             "C(seeded) 必须原样返回 seededHeight")):
        i = infra.find(head_anchor)
        if i < 0:
            raise RuntimeError(
                "%s: ★找不到短路 if 头 %r —— 判据已对不上产物结构" % (F, head_anchor))
        tp = infra.find(tag, i)
        if tp < 0 or tp - i > 800:
            raise RuntimeError(
                "%s: ★短路 %s 的 if 头之后 800 字符内没有探针标记 %r —— "
                "探针与短路不是同一处" % (F, head_anchor, tag))
        j = infra.find("return copy", tp)
        if j < 0 or j - tp > 800:
            raise RuntimeError(
                "%s: ★%s 探针之后 800 字符内没有 `return copy` —— "
                "段右界抓错, 判据读的不是这条短路" % (F, head_anchor))
        seg = _strip_swift_noise(infra[i:j])
        # ★语义校验才是正确性保障: 段里必须**恰好一处**高度赋值,
        #   且右值就是本路宣称要返回的缓存/种子高度。多于一处说明段
        #   越界吃到了别的短路; 一处都没有说明段截在了赋值之前。
        seen = re.findall(r"copy\.size\.height\s*=\s*([^;\n]+)", seg)
        if len(seen) != 1:
            raise RuntimeError(
                "%s: ★短路 %s 段内 `copy.size.height` 赋值有 %d 处(期望恰好 1) —— "
                "0 处=段截在赋值之前, 多处=段越界吃到了别的短路"
                % (F, head_anchor, len(seen)))
        if seen[0].strip() != allowed:
            raise RuntimeError(
                "%s: ★%s 段内 `copy.size.height` 被赋成 `%s`, 期望 `%s` —— "
                "P 是**只读诊断**, 改高度就变成了新的抢高时机, "
                "探针污染了被测对象, 装机日志的三来源计数不再可信"
                % (F, why, seen[0].strip()[:40], allowed))
    return t


def verify_debtgate_release_v53(t, infra):
    """校验 v53-C1/C2 —— 记忆位死锁打破 + 欠账放行 + CONSUMED 判据可验证。"""
    F = "verify_debtgate_release_v53"

    # ================= C1: 记忆位死锁 =================
    if "// [V53-C1]" not in t:
        raise RuntimeError("%s: 缺 [V53-C1] 标记" % F)
    if "let _v53memW: CGFloat? = {" not in t:
        raise RuntimeError(
            "%s: ★缺 `_v53memW` —— 记忆位的第一次写入只能来自它; "
            "没有它就仍是 v52 那个「sane 恒 0 ⇒ 永不入记忆位」的死锁"
            % F)
    # ★核心: 必须用闸门判别结论挡污染宽度。375.7 的 dev=14.3 落在
    #   [1, cvW*0.5] 区间内, 光靠区间判据会被当成真实布局宽写进记忆位
    #   ⇒ 下一帧回落目标变 375.7 ⇒ v52 归零的污染复活。
    i = t.find("let _v53memW: CGFloat? = {")
    seg = _strip_swift_noise(t[i:t.find("}()", i) + 3])
    if "guard _v52ok else { return nil }" not in seg:
        raise RuntimeError(
            "%s: ★`_v53memW` 没有用 `guard _v52ok` 拒绝污染宽度 —— "
            "375.7(dev=14.3) 落在 [1, cvW*0.5] 区间内会被写进记忆位, "
            "下一帧回落目标变 375.7, v52 归零的污染会复活" % F)
    for pat in ("if _edgeTouch { return _cvW - 32 }",
                "if _dev <= 1 { return nil }",
                "if _dev <= _cvW * 0.5 { return _v52w }"):
        if pat not in seg:
            raise RuntimeError(
                "%s: `_v53memW` 缺分支 %r —— 贴边/全屏/真实布局宽三种情形"
                "必须各有判据, 少一条就有一类 cell 记不进记忆位" % (F, pat))
    # 记忆位写入必须真的发生
    if "ios15LastSaneContentW = _mw" not in t:
        raise RuntimeError(
            "%s: ★记忆位没有写入 `_mw` —— 死锁没打破" % F)
    # 污染标志必须来自闸门本身
    if "var _v52ok = true" not in t:
        raise RuntimeError(
            "%s: ★闸门判别结论 `_v52ok` 没有暴露到闸门外 —— "
            "C1 依赖它区分「真实布局宽」与「污染过渡宽」" % F)
    # 新探针
    if "[V53-MEM]" not in t:
        raise RuntimeError("%s: 缺 [V53-MEM] 探针" % F)
    # [V54-D] ★必须锁 **NSLog 格式串本身**，不能只查全文子串。
    #
    # 旧判据只查 "memHit=" 在不在文件里 —— 而 S9 破坏把格式串的
    # `memHit=%llu` 改成了 `x=%llu`，判据却仍然全绿：变量声明行
    # `static var memHit: UInt` 里的 `memHit` 子串还在，**13/14 拦成 12/14**。
    # 教训与 v53 的S13 同源：**字段「出现在文件里」≠ 字段「出现在日志里」**。
    # 装机读日志看到的是 NSLog 的输出，判据就必须对着那一行查。
    _v54m = re.search(r'\[V53-MEM\]\s*saneHit=.*?len=%d', t, re.S)
    if not _v54m:
        raise RuntimeError(
            "%s: ★找不到 [V53-MEM] 的 NSLog 格式串 —— 装机日志靠它判读"
            "C1 是否生效(见 MSG_V54_D1)" % F)
    _v54fmt = _v54m.group(0)
    for f in ("saneHit=%llu", "memHit=%llu", "mem=%.1f", "picked=%.1f"):
        if f not in _v54fmt:
            raise RuntimeError(
                "%s: [V53-MEM] 格式串缺字段 %r —— saneHit/memHit 必须能分别"
                "证明「闸门放行过」与「记忆位写入过」(实际格式串: %r)"
                % (F, f, _v54fmt[:120]))

    # ================= C2: 三条短路放行 =================
    if "// [V53-C2]" not in infra:
        raise RuntimeError("%s: 缺 [V53-C2] 标记" % F)
    for pat, why in (
            ("func v53NotePendingDebt(", "欠账上报入口缺失"),
            ("var v53DebtIsRipe: Bool { v53DebtSeenCount >= 2 }",
             "欠账「熟」的判据缺失 —— 必须两拍, 首帧仍走短路"),
            ("var v53PendingHeightDebt: CGFloat = 0",
             "cell 侧不知道欠账 ⇒ 短路无从判断")):
        if pat not in infra:
            raise RuntimeError("%s: ★%s —— %s" % (F, pat, why))

    # 三条短路各加一个 !v53DebtIsRipe —— 少加一条就有一路仍能挡住真实测量
    # ★v62 适配: 守卫形态扩为 `!v53DebtIsRipe, !v53SurplusIsRipe {`(盈余镜像),
    #   语义仍是「欠账守卫挂在每条短路上」, 认新形态。
    n_guard = infra.count("!v53DebtIsRipe, !v53SurplusIsRipe {")
    if n_guard != 3:
        raise RuntimeError(
            "%s: ★`!v53DebtIsRipe, !v53SurplusIsRipe` 守卫应出现 **3** 次"
            "(A/B/C 三条短路各一), 实为 %d —— 少一条则该路仍能把欠账高度"
            "返回回去, preSVH 会继续卡在首次提交的值上(实测 1004.0, 欠 268.3pt)"
            % (F, n_guard))

    # ★S14 补漏: 光数「`!v53DebtIsRipe {` 出现 3 次」是不够的。
    #   破坏方式是把多行 if 条件里的**逗号**换成**花括号**:
    #       abs(cv.bounds.width - sw) < 1,     ← 正常: 仍在条件链里
    #       abs(cv.bounds.width - sw) < 1 {    ← 破坏: if 体提前闭合,
    #   后面那行 `!v53DebtIsRipe {` 就变成了**另一条独立语句**。
    #   守卫文本仍在(计数照样是 3), 但它已经不再约束这条短路 ——
    #   判据看起来全绿, 装机后 C 路照样卡死。
    #   ⇒ 必须逐条验证: 守卫之前那行必须是**逗号结尾**的条件延续行。
    for head_anchor, why in (
            ("if let cached = lastComputedHeight,",
             "A(dedup)"),
            ("if layout.deferSelfSizing || streamingActive,",
             "B(滑动期 cached)"),
            ("if let sh = seededHeight, let sw = seededWidth,",
             "C(seeded)")):
        i = infra.find(head_anchor)
        if i < 0:
            raise RuntimeError(
                "%s: ★找不到短路 if 头 %r —— 判据已对不上产物结构"
                % (F, head_anchor))
        k = infra.find("!v53DebtIsRipe, !v53SurplusIsRipe {", i)
        if k < 0 or k - i > 900:
            raise RuntimeError(
                "%s: ★短路 %s 的 if 头之后 900 字符内没有 `!v53DebtIsRipe` —— "
                "守卫没挂在这条短路上, 或段右界抓错" % (F, why))
        # ★必须先剥注释再取上一行 —— 产物里守卫前面压着 2~3 行解释性注释,
        #   直接看原始文本的上一行永远是 `// 停在首次提交时的欠账值上…`,
        #   会把**正确实现**判成破坏(v53 第一版就栽在这, 报了个假失败)。
        #   ⇒ 纪律: **查语法结构必须先剥注释**, 同 §FIRST 的「两层分开用」。
        code = _strip_swift_noise(infra[i:k]).rstrip()
        prev = code.rsplit("\n", 1)[-1].strip()
        if not prev.endswith(","):
            raise RuntimeError(
                "%s: ★%s 的 `!v53DebtIsRipe` 前面一行(剥注释后)是 `%s`, "
                "不是以 `,` 结尾的条件延续行 —— 说明 if 体在这行提前闭合, "
                "守卫已经变成**另一条独立语句**, 不再约束这条短路; "
                "C 路会继续拿 1004 挡住真实测量" % (F, why, prev[-40:]))


    # 欠账清掉必须复位, 否则短路对该 cell 永久失效
    i = infra.find("func v53NotePendingDebt(")
    seg = _strip_swift_noise(infra[i:infra.find("\n    }", i) + 6])
    if "debt <= 1" not in seg:
        raise RuntimeError(
            "%s: ★欠账清掉(debt<=1)时必须复位计数 —— 否则 v53DebtSeenCount "
            "永远停在 >=2, 三条短路对该 cell 永久失效, 退化成每帧全量重测"
            % F)
    # ★v62 适配: note 函数里 `v53DebtSeenCount = 0` 有两处(盈余分支/欠账
    #   复位), 裸串检查会被盈余分支顶掉 —— 复位必须精确绑定 debt<=1 分支。
    if "if debt <= 1 {\n            v53DebtSeenCount = 0" not in infra:
        raise RuntimeError(
            "%s: ★复位语句 `v53DebtSeenCount = 0` 缺失(或未绑定在 "
            "debt<=1 分支内)" % F)

    # ================= C2: CONSUMED 判据可验证 =================
    if "_cellH >= newHeight - 1" not in t:
        raise RuntimeError(
            "%s: ★CONSUMED 判据没有改成「cell 实际高达标」 —— "
            "v52 只验 `applyCellCorrection()` 的返回值(调用成功), "
            "而它打印了 105 次 CONSUMED 时 preSVH 纹丝不动(恒 1004.0)" % F)
    if "[V53-HOLD]" not in t:
        raise RuntimeError(
            "%s: 缺 [V53-HOLD] 探针 —— 装机后要靠它确认旧判据确实在空转" % F)
    for f in ("cellH=", "need=", "stillShort=", "retries="):
        if f not in t:
            raise RuntimeError("%s: [V53-HOLD] 缺字段 %r" % (F, f))
    # 未达标时必须保持 pending, 而不是清标志
    i = t.find("let _cellH = superview?.frame.size.height ?? 0", t.find("[V53-HOLD]") - 2000)
    if i < 0:
        raise RuntimeError("%s: 找不到 CONSUMED 判据的 `_cellH` 取样" % F)
    seg = _strip_swift_noise(t[i:t.find("[V53-HOLD]", i) + 1200])
    if "deferredCorrectionPending = false" not in seg:
        raise RuntimeError(
            "%s: 未达标分支里必须有 `deferredCorrectionPending = false` "
            "(只出现在**达标**分支) —— 若未达标也清标志, 欠账会被永久丢弃, "
            "这正是 v52 提前清 flag 导致首段永远等不到纠正的机制" % F)
    if "_v53ReportDebtToCell(newHeight - _cellH)" not in seg:
        raise RuntimeError(
            "%s: 未达标分支必须再报一次欠账(把计数推到「熟」逼短路放行) —— "
            "缺了它会停在第一帧, 短路永远不放行, 纠正永远不落地" % F)

    # ================= 上报链路完整性 =================
    if "func _v53ReportDebtToCell(" not in t:
        raise RuntimeError("%s: 缺 `_v53ReportDebtToCell` 上报入口" % F)
    if "cell.v53NotePendingDebt(debt)" not in t:
        raise RuntimeError(
            "%s: 上报函数没有真正调 cell 的入口 —— 欠账送不到 cell, "
            "三条短路无从判断" % F)
    # E 判据处必须上报(唯一能拿到 needH-preSVH 的地方)
    if "_v53ReportDebtToCell(_needH - _v52PreSVH)" not in t:
        raise RuntimeError(
            "%s: ★E 判据处没有上报欠账 —— 那是唯一知道差值的地方, "
            "不上报则 cell 永远不知道欠账, 三条短路全部照旧短路" % F)
    # 清账时必须复位
    if t.count("_v53ReportDebtToCell(0)") < 1:
        raise RuntimeError(
            "%s: 欠账清掉时必须 `_v53ReportDebtToCell(0)` 复位 —— "
            "否则计数卡在 >=2, 短路永久失效" % F)
    return t


def verify_first_para_settle_v53(t):
    """校验 v53-FIRST —— 首段专项: settle 入口不依赖已空转的 flag。"""
    F = "verify_first_para_settle_v53"
    i = t.find("func consumeDeferredCorrectionIfNeeded()")
    if i < 0:
        raise RuntimeError("%s: 找不到 consumeDeferredCorrectionIfNeeded" % F)
    # ★段右界必须用**行首的函数尾括号**, 不能用 `\n    }` —— 函数体里
    #   嵌套的闭包/if 也会以 `    }` 结束(缩进相同), 抓到的是内层。
    #   v53 第一版就栽在这: 段被截在内层 guard 之前, 于是判据读到的
    #   是注释里的 `guard deferredCorrectionPending` 字样, 报了个假失败。
    #   ⇒ 纪律: **段边界紧贴被测代码, 且用能唯一定位的锚点**。
    k = t.find("invalidateCellSizeIfNeeded()", i)
    j = t.find("\n    }", k)
    raw = t[i:j + 6]
    seg = _strip_swift_noise(raw)
    # ★诊断字段要在**原始文本**里查, 不能在剥注释后的段里查 ——
    #   `stillOwing=\(_stillOwing)` 这种插值在 _strip_swift_noise 里
    #   会被当字符串字面量剥掉。第一版查错层, 报了个假失败。
    #   ⇒ 纪律: **代码语义查剥注释段, 诊断字符串查原始段**, 两层分开用。
    raw_seg = raw
    if "guard deferredCorrectionPending" not in seg and "_stillOwing" not in seg:
        raise RuntimeError(
            "%s: 段边界抓错 —— 取到的段里既没有 guard 也没有 _stillOwing, "
            "说明右界截到了函数体内部(嵌套闭包的 `    }`)。"
            "判据读的不是被测代码, 结论无效" % F)

    # ★原 guard 是 flag 单条件 —— 正是它把首段挡在门外
    if re.search(r"guard\s+deferredCorrectionPending\s+else\s*\{\s*return\s*\}",
                 seg):
        raise RuntimeError(
            "%s: ★`guard deferredCorrectionPending` 仍是唯一入口 —— "
            "v52 的 CONSUMED 判据会**提前清掉** flag, 于是 settle 时刻"
            "这个视图被挡在门外, 首段永远等不到纠正(实测 preSVH 恒 61.3)" % F)
    # 必须改成「flag 或 真欠账」
    if "_stillOwing" not in seg:
        raise RuntimeError(
            "%s: 缺 `_stillOwing` —— 入口必须换成「flag **或** cell 真的还欠账」"
            % F)
    if not re.search(r"guard\s+deferredCorrectionPending\s*\|\|\s*_stillOwing", seg):
        raise RuntimeError(
            "%s: ★guard 没有改成 `deferredCorrectionPending || _stillOwing` —— "
            "只留 flag 等于没修(已被提前清空), 只留 stillOwing 则丢掉 settle 语义"
            % F)
    # 欠账必须由真实测量得出, 且阈值 >1pt
    for pat, why in (
            ("let _debt = _need - _cellH", "欠账必须由需求高减实际高得出"),
            ("_debt > 1", "欠账阈值应为 1pt —— 1pt 内属亚像素噪声, 不算欠账"),
            ("let _cellH = superview?.frame.size.height ?? 0",
             "必须读 cell 的**实际容器高**, 不是视图自己的高(v52 就是"
             "拿视图高判欠账才空转的)")):
        if pat not in seg:
            raise RuntimeError("%s: ★%s —— %s" % (F, pat, why))
    # 诊断字段(在原始段里查, 见 raw_seg 处的说明)
    for f in ("stillOwing=", "cellH=", "need="):
        if f not in raw_seg:
            raise RuntimeError(
                "%s: 诊断缺字段 %r —— 装机要靠 stillOwing=1 确认首段走了新入口"
                % (F, f))
    # 欠账要上报给 cell, 否则首段同样被短路挡住
    # ★v62 适配: 上报形态扩为盈余感知 `_stillOwing || _v62oversized ? _debt : 0`。
    if "_v53ReportDebtToCell(_stillOwing || _v62oversized ? _debt : 0)" not in seg:
        raise RuntimeError(
            "%s: 首段欠账必须上报给 cell —— 否则 C2 的三条短路仍会挡住它, "
            "新入口等于空转" % F)
    return t


def fix_width_source_unify_v50(t):
    """v50-A': attachmentBounds 与测高链读同一个宽度源 —— 治滑动时卡字。

    ── v49 归因(minis-2026-10-04 2.log, 143 条 V49-WWRITER / 86 条 V46-ATTACH)──

    v49 探针把"谁把 textContainer.size.width 推回 390"钉死了, 结论是
    **v48 的钉宽没有错**:

      · v18W = 358.0  **143/143 零例外** ⇒ v48 每次都成功钉宽
      · kvoW = 390.0   138/143, sameTick=0, dtick=1 ⇒ 下一 tick 就被推翻
      · V41-KVOPRE: sv=(16.0, ..., **358.0**, ...) cvW=390.0  147/147
        ⇒ _realW = min(358, 390) = 358, v18 算得完全正确

    真凶是**排版链与测高链的宽度源不同**, 逐毫秒证据(02:24:20):

      .088 [V43-WIDTH]  dirtyW=390.0 → **netW=358.0**      ← 测高链算对了
      .090 [V42-MISS]   tcW=358.0                          ← 钉宽生效
      .090 [V49-WWRITER] v18W=358.0 kvoW=390.0 dtick=1     ← 已被改
      .091 [V45-TVHFIX] tvW=390.0                          ← UITextView 宽也变
      .091 [V46-ATTACH] cachedW=**389.0** tcW=390.0        ← 推手在这 1ms

    而 389 的来源精确到算式(源码 :2232 `TableAttachment.attachmentBounds`):

        let usableWidth = floor(lineFrag.width) - 1    // 390 - 1 = 389

    `V43-WIDTH` 147 条: netW=**358(147/147 零例外)**, dirtyW=390(131) ——
    **测高链每一帧都算对, 排版链每一帧都拿到脏宽。**

    ── 为什么 `lineFrag.width` 拿到的是脏宽 ──

    `lineFrag.width` 由 UIKit 合成, 读的是"当前"的 textContainer 宽。
    v18 段钉宽写在 layoutSubviews 内, **时序上晚于** UIKit 问宽度 ⇒
    每次 attachmentBounds 被调用时, 拿到的都是还没被钉的 390。
    于是形成**自我强化的环**:

        SwiftUI 写 390 → attachmentBounds 问得 390 → 按 389 排版并 persist
        → 碎片按 389, needH 按 358 → gap 75pt 空壳 → tcW 被重排回 390
        → 回到第一步

    ★**v46 当年把 D2「探针宽度不同源」排除掉了**, 理由是
      "cachedW 与 tcW 恒差 1.0, 不像陈旧值"。**那是误判** ——
      恒定 1.0 差不是无害的舍入噪声: 那个 `-1` 是 UIKit 防
      `_fillLayoutHole` 的**既有约定**(必须保留), 而 `w` 本身是脏宽。
      差 1.0 恰恰掩盖了"整个宽度口径都是错的"这个事实。

    ── 修法: 让 attachment 链能读到"钉宽后的净宽" ──

    沿用 `TableAttachment.narrowestRealWidth` 的既有形态(进程级
    `nonisolated(unsafe) static var`), 新增一个**只写不读**的宽度通道:

      1. v18 段算出 `_realW2` 之后, 把它写进 `TableAttachment.ios15PinnedW`
         —— 与 `textContainer.size.width = _realW2` **同一处、同一帧**。
      2. `attachmentBounds` 的 `usableWidth` 优先取 `ios15PinnedW - 1`,
         拿不到才回退 `lineFrag.width`。

    ★**只换"谁来提供 w", 不动 `floor(w)-1` 那个约定本身** ——
      那个 `-1` 是防 fillLayoutHole 的, 动它会重演 v37 的翻车。

    ── 三条红线(v50 判据逐条硬查)──

      R1 **只在非 probe 路径生效**。`isOversizedProbe`(lineFrag >= 100_000)
         必须仍走原口径, 否则 `[ios_session_open_last_cell_occluded]`
         那个"末行被裁"修复会回退。
      R2 **钉宽写入点必须紧邻 v48 那一行**, 不能是"另一处新增的宽度写入"
         —— v13/v34 翻车都是因为在布局 pass 外无条件抢宽。
      R3 **不许任何新的 textContainer 宽度写入点**。v50 只加一个静态标量,
         真正的容器宽写入仍然只有 v18 那两处 + v48 那一处。

    ── 为什么不一次性把 SwiftUI 的写入也堵住 ──

    `dirtyW=390` 131/147 说明 SwiftUI 每帧都写 390, v48 只是每次纠回来 ——
    那是"纠偏"不是"根治"。但**堵 SwiftUI 的写入是抢 pass**, 正是
    v13/v34 闪屏/整体缩小那条老路。本版让排版链**不再依赖那个脏宽**,
    相当于把"纠偏"变成"免疫": 即使容器宽被写回 390, 排版用的仍是 358。
    """
    if "ios15PinnedW" in t:
        return t

    # ---- 1. TableAttachment: 新增进程级钉宽通道(只写) ----
    ANCHOR_W = """    nonisolated(unsafe) static var narrowestRealWidth: CGFloat = 380
"""
    if ANCHOR_W not in t:
        raise RuntimeError(
            "fix_width_source_unify_v50: 未找到 narrowestRealWidth 锚点 "
            "(TableAttachment 结构变了?)")
    if t.count(ANCHOR_W) != 1:
        raise RuntimeError(
            "fix_width_source_unify_v50: narrowestRealWidth 锚点不唯一 "
            "(命中 %d 处)" % t.count(ANCHOR_W))
    NEW_W = ANCHOR_W + """
    /// [V50-PINW] v18 段钉宽后的**目标净宽**(0 = 从未钉过)。
    ///
    /// 【为什么需要它】v49 归因(minis-2026-10-04 2.log): 钉宽 143/143 生效,
    /// 但下一 tick 就被 attachment 链按 `lineFrag.width`(= 脏宽 390) 推回。
    /// `lineFrag.width` 由 UIKit 合成, 读的是**当前** textContainer 宽 ——
    /// 而 v18 的钉宽写在 layoutSubviews 内, **时序上晚于** UIKit 问宽度,
    /// 于是 attachment 每次拿到的都是没被钉的 390(实测 usableWidth=389)。
    /// 测高链走 netW=358(147/147 零例外), 排版链走 389 ⇒ 两条链不同源,
    /// 行碎片按 389 排而 needH 按 358 算, 差出 75pt 空壳(用户看到的卡字)。
    ///
    /// 【形态与 narrowestRealWidth 同构】刻意沿用既有的
    /// `nonisolated(unsafe) static var` 形态 —— 它是本类里"跨实例共享
    /// 宽度口径"的既有先例(见其上方的 [ios_session_open_last_cell_occluded]
    /// 说明), 新通道照同样的规矩写, 不引入新的并发形态。
    /// `nonisolated(unsafe)` 在此是安全的: CGFloat 读写不撕裂, 且
    /// attachmentBounds 与 layoutSubviews 同在主线程。
    nonisolated(unsafe) static var ios15PinnedW: CGFloat = 0
"""
    t = t.replace(ANCHOR_W, NEW_W, 1)

    # ---- 2. v18 段: 钉宽的**同一处、同一帧**写入通道 ----
    #   锚点是 v48 注入的钉宽 if(它是 v48 判据锁定的唯一合法写入形态)。
    ANCHOR_PIN = """            if _ios15WRegrabbed, abs(textContainer.size.width - _realW2) > 0.5 {
                textContainer.size.width = _realW2
            }"""
    if ANCHOR_PIN not in t:
        raise RuntimeError(
            "fix_width_source_unify_v50: 未找到 v48 钉宽 if 锚点"
            "(v48 没注入? 登记顺序错了?)")
    if t.count(ANCHOR_PIN) != 1:
        raise RuntimeError(
            "fix_width_source_unify_v50: v48 钉宽 if 锚点不唯一(命中 %d 处)"
            % t.count(ANCHOR_PIN))
    NEW_PIN = ANCHOR_PIN + """
            // [V50-PINW-WRITE] 把钉宽后的目标净宽交给 attachment 链 ——
            // 见函数 docstring 的归因与三条红线。**与上面那行同一处、
            // 同一帧**: 早一帧则拿到的是还没钉的 390, 晚一帧则本帧
            // 的行碎片已经按脏宽排完了。
            TableAttachment.ios15PinnedW = _realW2
            // [V50-PINW-DIAG] 纯诊断: 记"钉宽帧"看到的两个宽, 装机后
            // 用来确认 attachment 链真的读到了新值(R2 的实机证据)。
            do {
                struct _PinDiag { static var last: CFTimeInterval = 0 }
                let _pn = CACurrentMediaTime()
                if _pn - _PinDiag.last > 0.5 {
                    _PinDiag.last = _pn
                    NSLog("[V50-PINW] pinnedW=%.1f tcW=%.1f len=%d",
                          _realW2, self.textContainer.size.width,
                          self.textStorage.length)
                }
            }"""
    t = t.replace(ANCHOR_PIN, NEW_PIN, 1)

    # ---- 3. attachmentBounds: 优先用钉宽净宽, probe 路径不动 ----
    ANCHOR_ATT = """        let usableWidth = floor(lineFrag.width) - 1
"""
    if ANCHOR_ATT not in t:
        raise RuntimeError(
            "fix_width_source_unify_v50: 未找到 usableWidth 锚点"
            "(TableAttachment 结构变了?)")
    if t.count(ANCHOR_ATT) != 1:
        raise RuntimeError(
            "fix_width_source_unify_v50: usableWidth 锚点不唯一(命中 %d 处)"
            % t.count(ANCHOR_ATT))
    NEW_ATT = """        // [V50-UNIFY] 宽度同源: 优先用 v18 钉好的净宽, 而不是 UIKit 合成��
        // `lineFrag.width`(它在钉宽之前就被问, 实测恒为脏宽 390)。
        //
        // ★三条红线:
        //   R1 **probe 路径完全不走这里** —— `isOversizedProbe` 判定仍在下方
        //      原位, 100_000 哨兵与 32_768 钳位都没动 ⇒
        //      [ios_session_open_last_cell_occluded] 的"末行被裁"修复不回退。
        //   R2 只读 `ios15PinnedW`, **不改 `lineFrag.width` 的用法** ——
        //      那个 `floor(w)-1` 是 UIKit 防 `_fillLayoutHole` 的既有约定,
        //      动它会重演 v37 的 fillLayoutHole 11918ms 卡死。
        //   R3 回落必须干净: 钉宽通道为 0(从未钉过, 如 v49 之前的老路径)
        //      就原样用 `lineFrag.width`, 行为与本版之前完全一致。
        //
        // 为什么减 1: 保持与原式 `floor(w)-1` 同构 —— 那个 -1 是 UIKit
        // 约定的安全余量, 换成钉宽后仍要减, 否则表格会宽到触发 fillLayoutHole。
        // ★probe 判定必须**先于**本段求值(否则下面诊断读不到它, 且
        //   probe 路径会误用钉宽净宽 = R1 被破)。原判定保持在下方
        //   `isOversizedProbe` 那一行, 这里只做一次**不改变语义**的提前取值:
        //   表达式与下方逐字相同(>= 100_000), 不是新增判定。
        let _v50IsProbe = lineFrag.width >= 100_000
        let _v50Pinned = _v50IsProbe ? 0 : Self.ios15PinnedW
        let usableWidth: CGFloat = _v50Pinned > 1
            ? floor(_v50Pinned) - 1
            : floor(lineFrag.width) - 1
        if _v50Pinned > 1 {
            do {
                struct _UniDiag { static var last: CFTimeInterval = 0 }
                let _un = CACurrentMediaTime()
                if _un - _UniDiag.last > 0.5 {
                    _UniDiag.last = _un
                    NSLog("[V50-UNIFY] used=%.1f (pinned=%.1f) lineFrag=%.1f",
                          usableWidth, _v50Pinned, lineFrag.width)
                }
            }
        }
"""
    t = t.replace(ANCHOR_ATT, NEW_ATT, 1)

    return t


def verify_width_source_unify_v50(t):
    """校验 v50 —— 独立成函数, 不只服务于注入。

    判据按"红线优先"排序: 先查三条红线有没有被破, 再查功能在位。
    顺序理由同 v47: 结构性违例比"少了个日志字段"严重得多。
    """
    # ---- 加法违例: v48 及之前的成果必须全在 ----
    for tag, want in (("// [V48-PIN]", 1), ("// [V47-REWRAP]", 2),
                      ("/// [V47-WSTATE]", 1), ("/// [V50-PINW]", 1),
                      ("// [V50-PINW-WRITE]", 1), ("// [V50-UNIFY]", 1),
                      ("[V44-TEXTFRAME]", 2), ("[V45-TVHFIX]", 2),
                      ("[V46-ATTACH]", 4), ("[V49-WWRITER-V18]", 1),
                      ("[V49-WWRITER-KVO]", 1), ("[V49-WWRITER-KVO-END]", 1)):
        if t.count(tag) != want:
            raise RuntimeError(
                "verify_width_source_unify_v50: 标记 %s 计数应为 %d, 实为 %d"
                % (tag, want, t.count(tag)))

    # ---- R1: probe 判定必须仍在 usableWidth 之后、且未被改写 ----
    i_unify = t.find("// [V50-UNIFY]")
    if i_unify < 0:
        raise RuntimeError("verify_width_source_unify_v50: [V50-UNIFY] 段缺失")
    i_probe = t.find("let isOversizedProbe = lineFrag.width >= 100_000")
    if i_probe < 0:
        raise RuntimeError(
            "verify_width_source_unify_v50: isOversizedProbe 判定缺失 —— "
            "100_000 哨兵是 probe 路径的唯一依据, 丢了它 probe 会走真实宽 "
            "把表格按 32768 排(末行被裁的老问题会回来)")
    if i_probe < i_unify:
        raise RuntimeError(
            "verify_width_source_unify_v50: ★isOversizedProbe(%d) 被挪到 "
            "[V50-UNIFY](%d) **之前** 了 —— 新代码在它之前就用了宽度, "
            "于是 probe 路径也会走钉宽净宽, R1 被破(末行被裁修复回退)"
            % (i_probe, i_unify))

    # ---- R1b: 钉宽通道的用法必须被 probe 显式排除 ----
    #   ★本判据第一版只查"probe 判定在下游", 结果**真的漏了一次**:
    #   首版写 `let _v50Pinned = Self.ios15PinnedW` 直接读, 于是 probe
    #   路径(32768)也会走钉宽净宽 —— R1 实际被破, 而判据全绿。
    #   教训: "红线在代码里存在" 与 "红线被真正执行" 是两件事,
    #   后者只能查**数据流** —— 钉宽通道的取值必须被 probe 条件夹住。
    seg = t[i_unify:i_unify + 1800]
    if "_v50Pinned > 1" not in seg:
        raise RuntimeError(
            "verify_width_source_unify_v50: ★[V50-UNIFY] 段内找不到 "
            "_v50Pinned > 1 守卫 —— 意味着钉宽净宽可能无条件生效, "
            "没钉过(0)时也会用上")
    if "lineFrag.width" not in seg:
        raise RuntimeError(
            "verify_width_source_unify_v50: ★[V50-UNIFY] 段内不再出现 "
            "lineFrag.width —— 回退路径被删了。钉宽通道为 0 时(老路径)会拿到 "
            "width 0, 表格全部塌成 minRowHeight")
    # ★数据流检查: 读通道那一行必须带 probe 条件。
    #   允许两种正确写法:
    #     · `let _v50Pinned = _v50IsProbe ? 0 : Self.ios15PinnedW`
    #     · `if !isOversizedProbe { ... }` 之类把读取包起来
    #   判据只认第一种(本版实现), 因为它能被一条正则钉死;
    #   将来若换写法, 判据会报红并要求同步更新 —— 这是刻意的不灵活。
    if "Self.ios15PinnedW" not in seg:
        raise RuntimeError(
            "verify_width_source_unify_v50: [V50-UNIFY] 段内不再读 "
            "ios15PinnedW —— 钉宽通道没被消费, 整段成了死代码")
    _readline = re.search(r"^.*Self\.ios15PinnedW.*$", seg, re.M)
    if not _readline or "_v50IsProbe" not in _readline.group(0):
        raise RuntimeError(
            "verify_width_source_unify_v50: ★读 ios15PinnedW 的那一行没有 "
            "probe 条件: %r —— probe 路径(lineFrag >= 100_000)会误用钉宽净宽, "
            "R1 被破([ios_session_open_last_cell_occluded] 的末行被裁修复回退)"
            % (_readline.group(0).strip()[:100] if _readline else None))

    # ---- R1c: 提前取值必须**逐字等价**于下方原判定, 且真的声明了 ----
    #   ★这条是被 S5 逼出来的: 反向测试删掉 `let _v50IsProbe = ...` 整行,
    #   R1b 仍绿(读它那行照样含 "_v50IsProbe" 字样), 但产物**根本编译不过**
    #   —— 未声明标识符。也就是说 R1b 只钉住了"引用", 没钉住"声明"。
    #   ⇒ 纪律: 查数据流时要连**声明**一起查, 否则数据流是断的。
    #
    #   同时钉住哨兵一致: 注释里声称"表达式与下方逐字相同", 但那句话
    #   此前**没有任何判据在守**。若有人把提前取值改成 `>= 200_000`,
    #   100_000~200_000 的 probe 会静默走进钉宽净宽路径 —— 编译得过、
    #   判据全绿、末行被裁悄悄回来。
    # ★用命名分组而不是位置分组: 本判据第一版把单捕获组的正则写成
    #   group(2), 当场抛 "no such group"。位置编号也是**数出来的**,
    #   跟"判据里的计数必须从产物数出来"是同一条纪律。
    m_pre = re.search(r"let (?P<pre>_v50IsProbe)\s*=\s*"
                      r"lineFrag\.width\s*>=\s*(?P<pre_s>[\d_]+)", seg)
    if not m_pre:
        raise RuntimeError(
            "verify_width_source_unify_v50: ★[V50-UNIFY] 段内找不到 "
            "`let _v50IsProbe = lineFrag.width >= <哨兵>` 的**声明** —— "
            "读它的那行还引用着它, 产物会编译不过(Swift 未声明标识符)。"
            "R1b 只查引用不查声明, 是本判据的漏网形态")
    m_org = re.search(r"let isOversizedProbe\s*=\s*"
                      r"lineFrag\.width\s*>=\s*(?P<org_s>[\d_]+)", t)
    if not m_org:
        raise RuntimeError(
            "verify_width_source_unify_v50: isOversizedProbe 原判定缺失 —— "
            "无法核对提前取值的哨兵")
    if m_pre.group("pre_s") != m_org.group("org_s"):
        raise RuntimeError(
            "verify_width_source_unify_v50: ★提前取值的哨兵 %s 与下方原判定 %s "
            "不一致 —— 落在两者之间的 probe 会静默走进钉宽净宽路径, "
            "编译得过、判据全绿、末行被裁修复悄悄回退"
            % (m_pre.group("pre_s"), m_org.group("org_s")))
    # 声明必须早于读通道那一行(Swift 同作用域 use-before-declaration)
    if m_pre.start() > _readline.start():
        raise RuntimeError(
            "verify_width_source_unify_v50: ★_v50IsProbe 的声明(%d)晚于读 "
            "ios15PinnedW 的那一行(%d) —— Swift 报 use before declaration"
            % (m_pre.start(), _readline.start()))

    # ---- R2: floor(w)-1 约定必须未被改动 ----
    #   原式 `floor(lineFrag.width) - 1` 必须**原样还在**(回退路径),
    #   且新式也必须带那个 -1。
    if "floor(lineFrag.width) - 1" not in seg:
        raise RuntimeError(
            "verify_width_source_unify_v50: ★原式 floor(lineFrag.width) - 1 "
            "不在段内 —— R2 被破。那个 -1 是 UIKit 防 _fillLayoutHole 的"
            "既有约定, 删掉会重演 11918ms 卡死")
    if "floor(_v50Pinned) - 1" not in seg:
        raise RuntimeError(
            "verify_width_source_unify_v50: ★新式 floor(_v50Pinned) - 1 "
            "不在段内 —— 换成钉宽后漏了那个 -1 余量, 表格会宽到触发 "
            "_fillLayoutHole")

    # ---- R3: 不许**未经登记**的 textContainer 宽度写入点 ----
    #   全文对 `textContainer.size.width =` 的写入必须**恰好是这 5 处**:
    #     · codeTextView 那处 —— 与本链无关的独立视图(终端块)
    #     · v18 段 `= _realW`  (v34 起的常规钳宽)
    #     · v18 段 `= _realW2` (v26 测高前的抢回)
    #     · v48 段 `= _realW2` (碎片与目标宽不一致时钉回)
    #     · KVO 闭包 `= _v570NetW` (v57.0 新增)
    #   ★这 4 是**实测基线**(v49 产物 L1641/L8119/L8154/L8198),
    #     不是推算值 —— 第一版这里写成 3, 判据当场报"实为 4"。
    #     ⇒ 纪律: 判据里的计数必须**从产物数出来**, 不能从脑子里数出来。
    #
    # 【v57.0 为什么可以把 4 改成 5 —— 而不是"随便加一个数"】
    #   R3 的意图是防 v13/v34 那种**抢宽翻车**: 在布局 pass 外无条件抢一个
    #   **第三方**宽度, 与 SwiftUI 竞争, 造成闪屏/整体缩小。
    #   v57.0 新增的那一处**不违例**, 三条都成立:
    #     1) 目标宽 = max(200.0, cvW - 32), 与 v18 段的 _realW2 **同源同值**
    #        (不是第三方宽度);
    #     2) 写在 KVO 闭包内 —— 本帧最早拿回控制权的点, 早于 layoutSubviews,
    #        不存在"pass 外抢" ;
    #     3) 判据双向 abs>1, 稳态零写入 ⇒ 幂等, 纠偏不是竞争。
    #   ⇒ 所以这里**不是把红线放宽**, 而是**把红线从"计数"升级为"白名单"**:
    #     计数只保证"没有第 6 个", 白名单保证"这 5 个都还在、且都是登记过的那个"。
    #   若将来再有人加第 6 个, 仍然会红 —— 红线没有被削弱。
    _w = re.findall(r"textContainer\.size\.width\s*=", t)
    if len(_w) != 5:
        raise RuntimeError(
            "verify_width_source_unify_v50: ★textContainer 宽度写入点数应为 5"
            "(codeTextView 1 + v18 3 + v57.0 KVO 1), 实为 %d —— "
            "**任何未经登记的新增容器宽写入都是 v13/v34 抢宽翻车的形态**"
            % len(_w))
    # 白名单: 五处必须都是登记过的那一行, 不许"顶替"(删一处、另一处重复出现)
    for _pat, _want in (
            ("textContainer.size.width = 10000", 1),          # codeTextView
            ("textContainer.size.width = _realW\n", 1),       # v18 常规钳宽
            ("self.textContainer.size.width = _v570NetW", 1), # v57.0 KVO 纠偏
    ):
        _n = t.count(_pat)
        if _n != _want:
            raise RuntimeError(
                "verify_width_source_unify_v50: 写入点 `%s` 应恰好 %d 处, 实为 %d"
                % (_pat.strip(), _want, _n))
    _n_realw2 = t.count("textContainer.size.width = _realW2")
    if _n_realw2 != 2:
        raise RuntimeError(
            "verify_width_source_unify_v50: `= _realW2` 的写入点应恰好 2 处"
            "(v18 抢回 + v48 钉宽), 实为 %d" % _n_realw2)

    # ---- 功能在位: 写入点紧邻 v48 钉宽 ----
    i_w = t.find("// [V50-PINW-WRITE]")
    i_pin = t.rfind("textContainer.size.width = _realW2", 0, i_w)
    if i_pin < 0:
        raise RuntimeError(
            "verify_width_source_unify_v50: [V50-PINW-WRITE] 上游找不到 "
            "v48 钉宽行 —— 通道写入点必须与钉宽**同一处**, 否则它记的是"
            "另一个宽度(早一帧拿到脏宽, 晚一帧本帧已排完)")
    if i_pin - i_w > 260:
        raise RuntimeError(
            "verify_width_source_unify_v50: ★钉宽行距 [V50-PINW-WRITE] %d 字符"
            " —— 太远, 不再是'同一处同一帧'(R2)" % (i_pin - i_w))

    # ---- 通道声明形态: 必须与 narrowestRealWidth 同构 ----
    if "nonisolated(unsafe) static var ios15PinnedW: CGFloat = 0" not in t:
        raise RuntimeError(
            "verify_width_source_unify_v50: ios15PinnedW 声明形态不符 —— "
            "必须是 nonisolated(unsafe) static var, 与既有的 "
            "narrowestRealWidth 同构")

    return True


def fix_slide_relayout_v50(t):
    """v50-C: 滑动时也记住"碎片已按目标宽重排" —— 修 `laidW` 永远空着。

    ── 为什么需要(v49 实测, minis-2026-10-04 2.log)──

    v49 探针的 `laidW` 字段(读 v47 注入的 `ios15LastLaidOutW`)实测
    **-1 出现 138/143 次** —— 也就是"碎片已按目标宽重排"这个记忆
    **几乎从未被写下**。查注入代码才看清病因:

        if _ios15WRegrabbed {
            layoutManager.ensureLayout(for: textContainer)
            // [V47-REWRAP] 行碎片已按 _realW2 定型, 记下来供下次比对。
            self.ios15LastLaidOutW = _realW2      // ★被关在这个 if 里
        }

    而 `_ios15WRegrabbed` 来自 v18 段更早的一行:

        if abs(textContainer.size.width - _realW2) > 0.5 { ... regrabbed = true }

    **滑动时容器宽恰好已经是目标宽**(实测 tcW=358 就在位, 或者
    v50-A' 生效后 tcW 与 _realW2 一致) ⇒ `abs(...)>0.5` 不成立
    ⇒ `_ios15WRegrabbed = false` ⇒ `ensureLayout` 不跑、`laidW` 不赋值。

    ⇒ **这是一个纯粹的逻辑耦合错误**: "容器宽此刻对不对" 与
      "碎片有没有按目标宽重排过" 是**两件事**。v47 自己的注释就写着
      前者不代表后者, 但代码里恰恰用前者去守后者。

    为什么这会致卡: `laidW` 空 ⇒ 下次比对 `abs(-1 - _realW2) > 0.5`
    恒成立 ⇒ 每帧都判定"需要重排" ⇒ 却在 `if _ios15WRegrabbed` 里
    跳过实际重排 ⇒ **判据与执行互相拆台**。滑动时正是最需要重排的时刻
    (行碎片最容易被脏宽带走), 记忆却是空的。

    ── 修法(最小改动)──

    把 `laidW` 的赋值从 `if _ios15WRegrabbed` 里**提出来**, 只留
    `ensureLayout` 在里面:

        if _ios15WRegrabbed {
            layoutManager.ensureLayout(for: textContainer)
        }
        // [V50-LAIDW] 记忆**无条件**更新
        self.ios15LastLaidOutW = _realW2

    ★**为什么记忆可以无条件写, 而 ensureLayout 不能**:
      记忆的语义是"本视图最近一次拿到的目标宽是多少", 与本帧有没有
      真的触发重排无关 —— 每帧的 `_realW2` 都是权威值(它由
      superview 宽算出, 实测 147/147 都是 358)。
      而 `ensureLayout` 是**排版开销**, v30 的流式节流就是为它设的,
      绝不能每帧无条件调 —— 那是 v13/v34"抢宽"翻车的形态。

    ⇒ 本版只多写一个 CGFloat 属性(零开销、幂等), 不新增任何排版调用。

    ── 三条红线 ──

      C1 **不许新增 ensureLayout / invalidateLayout 调用**。v49 判据
         (对 v47 段)硬禁这件事, v50 判据继承同一纪律。
      C2 **不许动 height**。v45 的 tvH 补高是已实测成果(debt 全 0)。
      C3 记忆赋值必须在 `ensureLayout` **之外** —— 若仍留在 if 内,
         滑动时依旧不写, 等于没修。
    """
    if "[V50-LAIDW]" in t:
        return t

    ANCHOR = """            if _ios15WRegrabbed {
                layoutManager.ensureLayout(for: textContainer)
                // [V47-REWRAP] 行碎片已按 _realW2 定型, 记下来供下次比对。
                self.ios15LastLaidOutW = _realW2
            }"""
    if ANCHOR not in t:
        raise RuntimeError(
            "fix_slide_relayout_v50: 未找到 v47 记忆块锚点(v47 没注入? "
            "登记顺序错了?)")
    if t.count(ANCHOR) != 1:
        raise RuntimeError(
            "fix_slide_relayout_v50: v47 记忆块锚点不唯一(命中 %d 处)"
            % t.count(ANCHOR))
    NEW = """            if _ios15WRegrabbed {
                layoutManager.ensureLayout(for: textContainer)
            }
            // [V50-LAIDW] "碎片已按目标宽定型"的记忆, **无条件**更新。
            //
            // 【为什么必须提出来 —— v49 实测 laidW=-1 出现 138/143 次】
            // 原先它被关在 `if _ios15WRegrabbed` 里, 而 `_ios15WRegrabbed`
            // 只表示"容器宽此刻偏离目标宽": 滑动时容器宽**恰好已经**是目标宽
            // ⇒ 条件不成立 ⇒ 记忆永不写入。
            // ⇒ 判据与执行互相拆台: `laidW` 空 ⇒ 下次
            // `abs(laidW - _realW2) > 0.5` 恒成立 ⇒ 每帧都判"该重排",
            //   却在 if 里跳过实际重排。而滑动正是最需要重排的时刻。
            //
            // 【为什么无条件写是安全的】
            //   记忆的语义 = "本视图最近一次拿到的目标宽是多少", 与本帧
            //   是否真的重排无关 —— `_realW2` 每帧都由 superview 宽算出,
            //   实测 147/147 都是 358, 是权威值。
            //   ★而 `ensureLayout` 绝不能无条件调: 它是排版开销,
            //     v30 的流式节流就是为它设的; 每帧调就是 v13/v34 抢宽翻车。
            //   ⇒ 本版只多写一个 CGFloat(零开销、幂等), 不新增排版调用。
            //
            // 【v47-REWRAP 标记保留在下方, 判据的 find 仍能定位到本段】
            // [V47-REWRAP] 行碎片已按 _realW2 定型, 记下来供下次比对。
            self.ios15LastLaidOutW = _realW2"""
    # ---- 诊断块单独挪到 v47 纯度段**之外** ----
    # ★为什么不能放在记忆赋值后面(本轮实踩, regress_all_v 报 v47 pure=BAD):
    #   v47 判据有一条 "纯度" 红线 —— 它的第一块(V47-REWRAP#1 到
    #   `if _ios15WRegrabbed, textStorage.length > 0 {` 之间)**不许出现任何
    #   NSLog**(日志归 v46 及更早的判据管)。而记忆赋值点正落在这块里,
    #   诊断跟在它后面 ⇒ 一起进判据区间 ⇒ v47 pure 报 BAD 日志=True。
    #   ⇒ 这不是 v47 判据太严, 是我插错了位置: 诊断是纯观测,
    #     放在 v47 段外即可, 语义完全不变(同一帧、同一批值)。
    #   纪律: **后版往共享段里插代码时, 先看前版的"纯度判据"覆盖到哪里。**
    ANCHOR2 = """            ios15LastNeededH = _needH"""
    # ★★ `self.ios15LastLaidOutW` 必须**解包**后再传给 %.1f ——
    #   它的声明是 `var ios15LastLaidOutW: CGFloat?`(**可选**), 而
    #   NSLog 是 C 变参函数, Swift 不能把 Optional 桥接进变参 ⇒ 编译失败:
    #       error: 'NSLog' is unavailable: Variadic function is unavailable
    #       warning: provide a default value to avoid this warning  (×3)
    #   这就是 run#37146140252 红在"编译 App"的**唯一**原因。
    #
    #   ★判据为什么没拦住(本轮第三次"看起来在跑、实际没钉住"):
    #     判据查的是"诊断字段齐全"(`laidW=` / `regrabbed=` / `len=`),
    #     字段在字符串里, 齐全 ⇒ 绿。而**类型对不对**是编译期的事,
    #     判据完全没查 —— 本机没有 swiftc(scope 那层只能查 API 存在性)。
    #   ⇒ 纪律: **判据查字段齐全, 不等于查类型正确**; 凡"字符串里有的",
    #     都要再问一句"那个占位符要的类型对不对"。
    #   `?? -1` 而不是 `!`: 诊断绝不能因为解包失败而崩, 且 -1 恰好就是
    #   v49 实测的那个坏值, 装机后一眼能认出来。
    NEW2 = ANCHOR2 + """
            // [V50-LAIDW-DIAG] 纯诊断: 确认记忆这次真的写进去了
            // (v49 实测 138/143 是 -1, 装机后这里应恒为 358)。
            // ★故意放在 `ios15LastNeededH` 之后 —— v47 判据的纯度段到
            //   `sizeThatFits` 那行为止, 这里已在它之外。
            do {
                struct _LwDiag { static var last: CFTimeInterval = 0 }
                let _lw = CACurrentMediaTime()
                if _lw - _LwDiag.last > 0.5 {
                    _LwDiag.last = _lw
                    NSLog("[V50-LAIDW] laidW=%.1f regrabbed=%d len=%d",
                          self.ios15LastLaidOutW ?? -1,
                          _ios15WRegrabbed ? 1 : 0, self.textStorage.length)
                }
            }"""
    if ANCHOR2 not in t:
        raise RuntimeError(
            "fix_slide_relayout_v50: 未找到 `ios15LastNeededH = _needH` 锚点 —— "
            "诊断块需要落在 v47 纯度段之外, 而那个位置是唯一稳定的落点")
    if t.count(ANCHOR2) != 1:
        raise RuntimeError(
            "fix_slide_relayout_v50: `ios15LastNeededH = _needH` 不唯一(命中 %d 处)"
            % t.count(ANCHOR2))
    t = t.replace(ANCHOR, NEW, 1)
    t = t.replace(ANCHOR2, NEW2, 1)
    return t


def verify_slide_relayout_v50(t):
    """校验 v50-C —— 独立成函数。"""
    # ---- 加法违例: A' 必须在(C 依赖 v48/v47 的成果) ----
    for tag, want in (("// [V50-PINW-WRITE]", 1), ("// [V50-UNIFY]", 1),
                      ("/// [V50-PINW]", 1), ("// [V50-LAIDW]", 1),
                      ("// [V50-LAIDW-DIAG]", 1), ("// [V47-REWRAP]", 2),
                      ("// [V48-PIN]", 1)):
        if t.count(tag) != want:
            raise RuntimeError(
                "verify_slide_relayout_v50: 标记 %s 计数应为 %d, 实为 %d"
                % (tag, want, t.count(tag)))

    i = t.find("// [V50-LAIDW]")
    if i < 0:
        raise RuntimeError("verify_slide_relayout_v50: [V50-LAIDW] 段缺失")
    # ★段边界一律用**下游稳定锚点**, 从不用固定字符数(本轮踩过两次):
    #   ① 固定 900 字符时诊断的 `regrabbed=` 落在窗口外, 判据报"缺字段" ——
    #      而字段其实就在同段里, 只是被窗口切掉了;
    #   ② 诊断块挪到 `ios15LastNeededH` 之后(为了不落进 v47 纯度段)后,
    #      两个标记之间**夹着 v47 的既有高度写入** `ios15LastNeededH = _needH`
    #      —— 若把两标记并成一段, C2 的高度正则会当场误报。
    # ⇒ 拆成两段: seg_main 管记忆赋值本体, seg_diag 管诊断块。
    #   C2(禁高度)只查 seg_main —— 诊断块是纯观测, 且它前面那行高度写入
    #   是 v47 的既有成果, 不属于本版。
    _i_v47 = t.find("// [V47-REWRAP]", i)
    if _i_v47 < 0:
        raise RuntimeError(
            "verify_slide_relayout_v50: [V50-LAIDW] 之后找不到 [V47-REWRAP] "
            "标记 —— 记忆赋值本体的段边界没了")
    _i_needh = t.find("ios15LastNeededH = _needH", _i_v47)
    if _i_needh < 0:
        raise RuntimeError(
            "verify_slide_relayout_v50: 找不到 `ios15LastNeededH = _needH` —— "
            "v47 测高成果不在位, 或本版插错了位置")
    _i_diag = t.find("// [V50-LAIDW-DIAG]", _i_needh)
    if _i_diag < 0:
        raise RuntimeError(
            "verify_slide_relayout_v50: [V50-LAIDW-DIAG] 段缺失(装机靠它确认"
            "laidW 真的写进去了)")
    # 主体段: 从 V50-LAIDW 标记前的 ensureLayout if 起, 到 v47 高度写入之前
    _i_ens = t.rfind("if _ios15WRegrabbed {", max(0, i - 400), i)
    seg_main = t[_i_ens if _i_ens > 0 else max(0, i - 400):_i_needh]
    # 诊断段: 从诊断标记到下一个稳定锚点(V42 闩锁)
    _i_latch = t.find("// [V42-LATCH-SET]", _i_diag)
    if _i_latch < 0:
        raise RuntimeError(
            "verify_slide_relayout_v50: 诊断段未闭合(找不到 // [V42-LATCH-SET])")
    seg_diag = t[_i_diag:_i_latch]

    # ---- C3(核心): 记忆赋值必须已从 if 内提出来 ----
    #   判据: `ios15LastLaidOutW = _realW2` 所在行**之前**,
    #   在同一缩进层上不能还挂着 `if _ios15WRegrabbed {`。
    _asm = re.search(r"^([ ]*)self\.ios15LastLaidOutW = _realW2\s*$",
                     t, re.M)
    if not _asm:
        raise RuntimeError(
            "verify_slide_relayout_v50: 找不到 ios15LastLaidOutW = _realW2 赋值")
    indent = len(_asm.group(1))
    # 从该行往上找最近一个"同级或更浅"的 if, 若它是 regrabbed 就说明还关着
    # ★上界用**标记**切而不是固定字符数(本轮踩过): 记忆赋值上方那段
    #   注释被 v50 加长到 400 字符以上, 固定窗口会**切不到** ensureLayout
    #   那个 if —— 于是"赋值其实还在 if 里"这种破法反而全绿。
    #   取 [V50-LAIDW] 标记(它就在 ensureLayout 之后)往前那一段即可。
    _i_mark = t.rfind("// [V50-LAIDW]", 0, _asm.start())
    if _i_mark < 0:
        raise RuntimeError(
            "verify_slide_relayout_v50: 记忆赋值上方找不到 [V50-LAIDW] 标记 —— "
            "无法确定 C3 的检查上界")
    _head = t[_i_mark:_asm.start()]
    for m in re.finditer(r"^([ ]*)if _ios15WRegrabbed \{\s*$",
                         _head, re.M):
        if len(m.group(1)) < indent:
            raise RuntimeError(
                "verify_slide_relayout_v50: ★记忆赋值仍关在 "
                "`if _ios15WRegrabbed` 里(缩进 %d <= %d) —— 滑动时容器宽"
                "恰好已是目标宽, 条件不成立 ⇒ 记忆永不写入, C 等于没修"
                % (len(m.group(1)), indent))
    # ensureLayout 仍必须在 regrabbed 里(C1: 不许把它提出来)
    if not re.search(r"if _ios15WRegrabbed \{\s*\n\s*layoutManager\.ensureLayout",
                     t):
        raise RuntimeError(
            "verify_slide_relayout_v50: ★ensureLayout 不再由 "
            "`if _ios15WRegrabbed` 守卫 —— C1 被破。v30 的流式节流就是为它设的, "
            "每帧无条件调就是 v13/v34 抢宽翻车的形态")

    # ---- C2: 记忆赋值本体不得写任何高度 ----
    #   ★只查 seg_main, 不查 seg_diag —— 见上面拆段的理由。
    _h = re.findall(r"^\s*(?:self\.)?[A-Za-z_]*[Hh]eight[A-Za-z_]*\s*=|"
                    r"frame\.size\.height\s*=|bounds\.height\s*=",
                    seg_main, re.M)
    if _h:
        raise RuntimeError(
            "verify_slide_relayout_v50: ★[V50-LAIDW] 段内出现高度写入 %d 处 "
            "—— v45 的 tvH 补高已实测有效(debt 全 0), C2 不许破" % len(_h))
    # 记忆赋值本体只许写那一个 CGFloat
    _w = re.findall(r"^\s*(?:self\.)?(\w+)\s*=[^=]", seg_main, re.M)
    _allow = ("_ios15WRegrabbed", "ios15LastLaidOutW", "_lw", "_PinDiag",
              "_LwDiag", "_needH")
    for lhs in _w:
        if lhs in ("_ios15WRegrabbed", "ios15LastLaidOutW", "_lw", "_last"):
            continue
        raise RuntimeError(
            "verify_slide_relayout_v50: ★[V50-LAIDW] 段内出现计划外赋值 "
            "`%s` —— C 只允许多写一个 CGFloat 记忆位" % lhs)
    del _w, _allow

    # ---- 诊断字段齐全(装机靠它确认) ----
    for f in ("laidW=", "regrabbed=", "len="):
        if f not in seg_diag:
            raise RuntimeError(
                "verify_slide_relayout_v50: 诊断缺字段 %r —— v49 实测 laidW "
                "138/143 是 -1, 装机后必须能从日志确认这次真的写进去了" % f)
    return True


# ══════════════════════════════════════════════════════════════════════
# v51 — 装机实测推翻 v50 疗效判断后的根因修正
# ══════════════════════════════════════════════════════════════════════

def fix_view_frame_pin_v51(t):
    """v51-A: 把 UITextView **自身**的 frame 宽也钉到 _realW2。

    ── 归因(minis-2026-10-04 3.log, v50 装机实测)──────────────────────────

    v50 的两条判据在装机后**全部达标**, 而用户的三个症状一字未改:
        V50-UNIFY  36 条  used=357.0 (pinned=358.0)   ← A' 生效
        V50-PINW   62 条  pinnedW=358.0 tcW=358.0    ← 钉宽每帧成功
        V50-LAIDW  62 条  laidW=358.0                 ← C 生效
    ⇒ v50 修的不是根因。本版去找 v18 段**没覆盖到**的那部分。

    硬证据(V44-TEXTFRAME, 59 条):
        svW (父容器宽)  = 358.0   **153/153 零例外**
        tvW (textView 自己) = 390.0  占 50 条, 358.0 占 9 条
        tcW 与 tvW 完全同构(全局 164 条 358 / 81 条 390)

    v18 段从 v32 到 v48 一路钉的全是 `textContainer.size.width`,
    **从来没有一处写 `self.frame.size.width`**。而画字的是 UITextView 自己 ——
    它的 bounds 是 390, 父容器只有 358 ⇒ 右侧 32pt 恒被自己的 bounds 裁掉。
    这就是「字卡住不显示完全内容」。

    量化(V43-WIDTH 的 dh = 脏宽测高 - 净宽测高):
        dh=22.3 出现 18 次(典型 hDirty=1297.0 vs hNet=1319.3)
    按 390 排版比按 358 排版矮 22.3pt, 那 22.3pt 就是排不下的那几行。

    为什么第 8128 行那道钳制没救回来:
        if !_edgeTouch, bounds.width > _realW + 1 || frame.size.width > _realW + 1 {
            var _rf = frame; _rf.size.width = _realW; frame = _rf
        }
    它带 `!_edgeTouch` 前缀。贴边态(x<=0.5 && w>=cvW-1)下整段跳过,
    textView 保持 SwiftUI 给的全屏 390。长文本把父容器推过阈值,
    _edgeTouch 在两态之间翻转 —— 于是 len=392 那组 tvW 在
    390(n=3/5/6/7) 与 358(n=4) 之间**逐帧交替**: 那就是拉锯的指纹,
    每个交替帧都要 TextKit 全量重排 ⇒ 用户说的「滑动整体动卡闪」。

    ── 修法与三条红线 ────────────────────────────────────────────────

    写在 v18 段内、V48-PIN 钉 textContainer 那一行的**下方**、
    V50-PINW-WRITE 的**上方** —— 同一处、同一帧、复用同一个 _realW2。
    同一帧是硬要求: 早一帧则本帧的行碎片已按脏宽排完, 晚一帧则渲染已提交。

    A1 **只写 `frame.size.width`**, 不碰 origin / height / bounds /
       整个 size。写 frame.origin 就足以让整棵 cell 重新布局(v34 翻车)。
    A2 判据**单调**: 只在 `frame.size.width > _realW2 + 1`(偏大)时写,
       绝不缩、绝不在已达标时写。这是**纠偏**不是**竞争** ——
       v13/v34 翻车正是因为在布局 pass 外无条件抢宽、与 SwiftUI 争 frame。
       贴边态下父容器本来就是 358@0, 那个 `!_edgeTouch` 前缀是 v14 为了
       「不与 SwiftUI 争布局」才加的; 本版不动它, 只在 v18 段内补一刀。
    A3 必须在 [V48-PIN] 钉宽行**之后**同一段内 —— 判据查行序。

    为什么不违反 v45 的「绝不碰 width」: v45 碰的是 KVO 抢帧器, 那是
    **布局 pass 之外**、与 SwiftUI 同一调用栈的竞争; 本版在
    layoutSubviews 的 v18 段内, 与 v48 钉 textContainer 同一处同一帧,
    时序性质完全不同。
    """
    if "// [V51-FRAMEPIN]" in t:
        return t

    # ---- 落点: v49 的 v18 侧探针段**结束标记之后** ----
    # ★★ 落点换过一次(本轮第五次栽在"插共享段", 这次是**反过来**):
    #   第一落点选在 v50 的通道写入行 `TableAttachment.ios15PinnedW = _realW2`
    #   之上 —— 而那是 v50 scope 判据 seg_w 的**内部**
    #   (begin=`// [V50-PINW-WRITE]`, end=`// [V49-WWRITER-V18]`),
    #   于是 v50 scope 报「V50-PINW-WRITE 段内出现 frame.size ——
    #   v50 只允许写一个 CGFloat/静态标量」。
    #   ⇒ 纪律(补 v48 那条): **后版往共享段插代码前, 先把前版判据的
    #     区间按 begin/end 锚点画出来; 落在区间里就换落点, 别改前版判据。**
    #   现落点 = `// [V49-WWRITER-V18-END]` 之后:
    #     · v49 判据查的是**钉宽行到探针之间**那段, 不含本标记之后;
    #     · v50 seg_w 的右界是 `// [V49-WWRITER-V18]` 标记(更靠前), 也不含。
    #   ★仍在 v18 段内(缩进 12, layoutSubviews 内), 与 v48 钉 textContainer
    #   宽**同一帧** ⇒ A3 成立, 中间只隔 v49 的三行纯读数。
    ANCHOR = """            // [V49-WWRITER-V18-END] 段结束标记 —— 见 v49 判据第 3 组。
"""
    if ANCHOR not in t:
        raise RuntimeError(
            "fix_view_frame_pin_v51: 未找到 v49 v18 侧段结束标记 —— "
            "v49 没注入? 登记顺序错了?")
    if t.count(ANCHOR) != 1:
        raise RuntimeError(
            "fix_view_frame_pin_v51: v49 段结束标记不唯一(命中 %d 处)"
            % t.count(ANCHOR))
    # 段右界取 END 标记**所在行的行尾**, 落点插在它**之后** ——
    # ★v49 判据硬查 `// [V49-WWRITER-V18-END]` 计数为 1, 而 `NEW = ANCHOR + ...`
    #   这种写法会把锚点行**留在原位又复制一份** ⇒ 计数 2, v49 struct 直接 BAD。
    #   ⇒ 锚点只用来**定位**, 不进 NEW。
    _nl0 = t.rfind("\n", 0, t.find(ANCHOR.strip())) + 1
    _nl1 = t.find("\n", t.find(ANCHOR.strip()))
    if _nl1 < 0:
        _nl1 = len(t)
    else:
        _nl1 += 1
    NEW = """            // [V51-FRAMEPIN] 把**画字的那个视图自己**的 frame 宽也钉到 _realW2
            // —— 见函数 docstring 的归因与三条红线。
            //
            // v18 段从 v32 到 v48 一路钉的全是 `textContainer.size.width`,
            // 从来没碰过 `self.frame.size.width`。而 UITextView 才是画字的视图,
            // 它的 bounds 宽 390 而父容器只有 358(log19: svW 358 零例外 / tvW 390
            // 占 50/59)⇒ 右侧 32pt 恒被自己的 bounds 裁掉, 用户看到的就是
            // 「字卡住不显示完全」。V43-WIDTH 的 dh=22.3(18 次)就是这笔账。
            //
            // 第 8128 行那道钳制救不回来: 它带 `!_edgeTouch` 前缀, 贴边态
            // (x<=0.5 && w>=cvW-1)整段跳过 ⇒ tvW 在 390/358 之间**逐帧交替**,
            // 交替帧 TextKit 全量重排 ⇒ 「滑动整体动卡闪」。
            //
            // 【A1】只写 size.width —— 不碰 origin/height/bounds/整个 size。
            //   写 frame.origin 就足以让整棵 cell 重新布局(v34 翻车)。
            // 【A2】判据单调: 只在**偏大**时写, 绝不缩、绝不在已达标时写。
            //   这是纠偏不是竞争 —— v13/v34 翻车正是无条件抢宽与 SwiftUI 争 frame。
            //   稳态下 tvW 已是 358, 条件恒 false, 零写入零开销。
            // 【A3】必须与本段内 v48 钉 textContainer 宽**同一帧** ——
            //   早一帧则行碎片已按脏宽排完, 晚一帧则渲染已提交。
            //   落点选在 v49 探针段之后正是为此: 仍在 layoutSubviews 的
            //   同一次调用内, 与钉 textContainer 之间只隔 v49 的三行纯读数。
            //
            // ★不违反 v45 的「绝不碰 width」: v45 碰的是 KVO 抢帧器
            //   (布局 pass **之外**, 与 SwiftUI 同栈竞争); 本版在
            //   layoutSubviews 的 v18 段内、与 v48 钉 textContainer 同一帧,
            //   时序性质完全不同。
            if frame.size.width > _realW2 + 1 {
                var _v51f = frame
                _v51f.size.width = _realW2
                frame = _v51f
            }
            // [V51-FRAMEPIN-DIAG] 纯诊断: 记钉 frame 宽那一刻的三个宽。
            // 装机判据: fvW 应与 tcW 同时为 358; 若 fvW 仍 390 说明
            // 写进去的 frame 宽度又被 SwiftUI 在下一 pass 推回。
            do {
                struct _V51FLog { static var last: CFTimeInterval = 0 }
                let _v51n = CACurrentMediaTime()
                if _v51n - _V51FLog.last > 0.5 {
                    _V51FLog.last = _v51n
                    NSLog("[V51-FRAMEPIN] fvW=%.1f tcW=%.1f svW=%.1f len=%d",
                          self.frame.size.width, self.textContainer.size.width,
                          superview?.frame.size.width ?? -1, self.textStorage.length)
                }
            }
"""
    t = t[:_nl1] + NEW + t[_nl1:]
    return t


def verify_view_frame_pin_v51(t):
    """校验 v51-A —— 独立成函数。"""
    for tag, want in (("// [V51-FRAMEPIN]", 1),
                      ("// [V51-FRAMEPIN-DIAG]", 1),
                      ("// [V50-PINW-WRITE]", 1),
                      ("// [V48-PIN]", 1)):
        if t.count(tag) != want:
            raise RuntimeError(
                "verify_view_frame_pin_v51: 标记 %s 计数应为 %d, 实为 %d"
                % (tag, want, t.count(tag)))

    i_pin = t.find("// [V51-FRAMEPIN]")
    if i_pin < 0:
        raise RuntimeError("verify_view_frame_pin_v51: [V51-FRAMEPIN] 段缺失")
    # 段右界用**下游稳定锚点**, 不用固定字符数。落点是 v49 探针段结束标记
    # 之后, 下游最近的稳定锚点是 v28 的重排注释 `// [IOS15-FIX-RELC v28]`。
    i_end = t.find("// [IOS15-FIX-RELC v28]", i_pin)
    if i_end < 0:
        raise RuntimeError(
            "verify_view_frame_pin_v51: 段未闭合(找不到下游的 "
            "`// [IOS15-FIX-RELC v28]`)")
    seg = t[i_pin:i_end]
    code = _strip_swift_noise(seg)

    # ---- A3: 必须与 V48-PIN 的钉宽行**同一段内、且在其之后** ----
    i_v48 = t.rfind("// [V48-PIN]", 0, i_pin)
    if i_v48 < 0:
        raise RuntimeError(
            "verify_view_frame_pin_v51: [V51-FRAMEPIN] 上游找不到 [V48-PIN] —— "
            "A3(同一帧)的检查上界没了")
    i_tc = t.find("textContainer.size.width = _realW2", i_v48)
    if i_tc < 0 or i_tc > i_pin:
        raise RuntimeError(
            "verify_view_frame_pin_v51: ★[V51-FRAMEPIN] 不在 v48 钉 textContainer "
            "那一行之后(i_tc=%d, i_pin=%d) —— 破坏了 A3「同一处同一帧」"
            % (i_tc, i_pin))

    # ---- A2: 判据必须单调(只在偏大时写) ----
    m_asm = re.search(r"if frame\.size\.width > _realW2 \+ 1 \{", code)
    if not m_asm:
        got = re.findall(r"if frame\.size\.width [^\n{]*\{", code)
        raise RuntimeError(
            "verify_view_frame_pin_v51: ★判据不是单调的 `> _realW2 + 1`, 实为 %r —— "
            "A2 要求只在偏大时写(纠偏不竞争), 写成 < 或无条件就是 v13/v34 老路"
            % (got or "无"))
    # 反向: 段内不许出现 `<` 或无条件(无判据)的 frame 宽写入
    if re.search(r"if frame\.size\.width <", code):
        raise RuntimeError(
            "verify_view_frame_pin_v51: ★段内出现 `frame.size.width <` 判据 —— "
            "本版只纠偏不缩放, 缩小会让整棵 cell 重新布局")

    # ---- A1: 段内只许写 size.width, 禁 origin/height/bounds/整体 size ----
    _m = re.search(r"frame\s*=\s*_v51f", code)
    if not _m:
        raise RuntimeError(
            "verify_view_frame_pin_v51: 找不到 `frame = _v51f` 赋值 —— "
            "注入形态变了?(判据与产物必须同步)")
    _i_w = code.find("_v51f.size.width = _realW2")
    if _i_w < 0:
        raise RuntimeError(
            "verify_view_frame_pin_v51: 找不到 `_v51f.size.width = _realW2` 写入")
    _bad = []
    for pat, why in (
            (r"\.origin\s*=", "origin"),
            (r"\.size\s*=\s*_v51f", "整个 size"),
            (r"\.size\.height\s*=", "height"),
            (r"\bbounds\s*=", "bounds"),
            (r"\.size\.width\s*=\s*(?!_realW2)", "非 _realW2 的宽度目标"),
    ):
        # 诊断块里的读取(self.frame.size.width 等)不算写入, 只查左侧是赋值的
        for mm in re.finditer(pat, code):
            line = code[code.rfind("\n", 0, mm.start()) + 1:
                        code.find("\n", mm.end())]
            if "=" in line and line.index("=") < len(line) and \
                    not re.match(r"\s*(?://|.*NSLog)", line):
                # 右侧紧跟 = 的是比较运算符时不是赋值
                _after = code[mm.end():mm.end() + 1]
                if _after == "=":
                    _bad.append("%s @ %r" % (why, line.strip()[:70]))
    if _bad:
        raise RuntimeError(
            "verify_view_frame_pin_v51: ★段内出现 A1 禁止的几何写入 %d 处: %s"
            % (len(_bad), "; ".join(_bad[:4])))

    # ---- 诊断字段齐全(装机靠它确认 fvW 真被钉住了) ----
    for f in ("fvW=", "tcW=", "svW=", "len="):
        if f not in seg:
            raise RuntimeError(
                "verify_view_frame_pin_v51: 诊断缺字段 %r —— log19 实测 tvW=390 "
                "占 50/59, 装机后必须能从日志确认 frame 宽钉住了" % f)
    return True


def fix_probe_unhook_v51(t):
    """v51-C: 把 V49-WWRITER 探针移出补高 if, 挂到闭包的无条件位置。

    ── 本轮实踩(判读日志时被自己的探针骗了)─────────────────────────────

    minis-2026-10-04 3.log 里 V49-WWRITER 的 laidW 出现两个值:
        358.0  × 5
        -1.0   × 51
    而同一份日志里 V50-LAIDW 恒为 358(v50-C 已达标)。初判是
    「探针读到的是上一 pass 的旧值」, 并据此推出「KVO 侧看到 390 是
    上一 pass 末的状态, 钉宽本身没失败」。

    逐行查代码才发现**两个探针根本不在同一个函数里**:
        V49-WWRITER  在 `ios15ApplyFrameFix()` 的 KVO 抢帧闭包内,
                      且关在 `if _v42Need > 1, f.size.height + 0.5 < _v42Need` 里
                      —— **补高真的执行才打这一条**;
        V50-LAIDW    在 `layoutSubviews()` 的 v18 段内, 无条件(0.5s 节流)。

    ⇒ laidW=-1 不是数据异常, 是**探针的触发条件**与另一个不同。

    ★真正的坑: `kvoW=390 ⇔ laidW=-1` **完全同构(51/51)**。
    这个「完美相关」极具误导性 —— 看起来像因果, 实际两者是被**同一个
    if 门**一起控住的。⇒ 纪律: **看到两个读数完美相关时, 先确认它们
    不是被同一个条件门控的**; 探针挂在有守卫的分支里时, 它的读数分布
    首先反映的是守卫条件, 而不是被测对象。

    修法: 探针的读数与打印移到闭包的**无条件位置**(补高 if 之后、
    闭包末尾), 让它与 V50-LAIDW 在同一 tick 都打 ⇒ 装机后才是真正的
    同 tick 对照。

    ★本版只挪探针位置, **不改任何行为**: 零赋值(除 v49 本来就有的
    `self.ios15V41CvW` / `self.ios15V46LaidOutW` 两个指纹字段, 那是
    v49 的既有成果)、零 invalidate*、零 ensureLayout。
    """
    if "// [V51-PROBE]" in t:
        return t

    # ---- 切出**整段**: 从起点标记所在行的行首, 到 END 标记那一行的行尾 ----
    #
    # ★★ 本轮在段边界上翻了第四次车, 根因值得写下来:
    #   v49 判据 / v50 判据 / scope_check_v49 三层都按**精确字符串**找
    #   `// [V49-WWRITER-KVO]` 与 `// [V49-WWRITER-KVO-END]` 这一**对**标记,
    #   且约定「起点在前、END 在后」。我前两版分别试过:
    #     ① 连 END 一起删      ⇒ 三层报「段未闭合」(标记没了);
    #     ② END 原地留、只搬探针体 ⇒ 三层报「找不到 END」(顺序倒了)。
    #   ⇒ **正确做法只有一个: 整段(两个标记 + 探针体)作为一个整体搬走**,
    #     原位不留任何残迹, 新位置两个标记的**相对顺序不变**。
    #   ⇒ 纪律: **判据把某段代码夹在一对标记之间时, 那对标记与段是一体的;
    #     要挪就整段挪, 标记留在原位等于把契约撕了。**
    #
    # 落点 = KVO 闭包补高 if **之后**(if 已闭合)、与 `f = _hFix` 同缩进的
    # 位置 —— 仍在同一闭包作用域内(cvW / f / _v42Need 全部可见),
    # 不需要新增任何读取, 且探针变成**无条件**执行(这正是本版的目的)。
    START = " " * 24 + "// [V49-WWRITER-KVO]"
    if START not in t:
        raise RuntimeError(
            "fix_probe_unhook_v51: 未找到 v49 探针起点(24 空格缩进) —— "
            "锚点缩进变了?(v49 那轮已踩过静默 no-op 的坑)")
    if t.count(START) != 1:
        raise RuntimeError(
            "fix_probe_unhook_v51: v49 探针起点不唯一(命中 %d 处)" % t.count(START))
    i0 = t.find(START)
    i0_line = t.rfind("\n", 0, i0) + 1          # 起点标记所在行的行首
    if t[i0_line:i0 + len(" " * 24)] != " " * 24:
        raise RuntimeError(
            "fix_probe_unhook_v51: 起点标记前导缩进不是 24, 实为 %r —— "
            "v49 判据按精确字符串找它, 缩进变了全线报段未闭合"
            % t[i0_line:i0 + 24])
    # 段右界 = END 标记所在行的**行尾**(含换行)
    i_end = t.find("// [V49-WWRITER-KVO-END]", i0)
    if i_end < 0:
        raise RuntimeError(
            "fix_probe_unhook_v51: 找不到 // [V49-WWRITER-KVO-END] —— "
            "v49 探针段未闭合")
    i_end_line = t.find("\n", i_end)
    if i_end_line < 0:
        i_end_line = len(t)
    else:
        i_end_line += 1
    seg_old = t[i0_line:i_end_line]
    if "[V49-WWRITER]" not in seg_old:
        raise RuntimeError(
            "fix_probe_unhook_v51: 切出的段里没有 [V49-WWRITER] 日志行 —— "
            "段右界选错, 会切掉真正的探针")
    if seg_old.rstrip("\n").split("\n")[-1].find(
            "// [V49-WWRITER-KVO-END]") < 0:
        raise RuntimeError(
            "fix_probe_unhook_v51: ★切出的段最后一行不是 END 标记 —— "
            "切点算错了(拿到 %r)"
            % seg_old.rstrip("\n").split("\n")[-1].strip()[:60])

    # ---- 重建: 整段去缩进 8 格后(24 -> 16), 原样搬到新落点 ----
    lines = []
    for ln in seg_old.split("\n"):
        if not ln.strip():
            continue
        if ln.startswith(" " * 8):
            ln = ln[8:]
        lines.append(ln)
    seg_new = (
        "                // [V51-PROBE] 从补高 if 里挪出来的 v49 探针 ——\n"
        "                // 见函数 docstring。**只挪位置, 零行为改动**:\n"
        "                // 读数/指纹/字段/格式串与 v49 逐字相同, 整段缩进 24 -> 16,\n"
        "                // 两个段边界标记**跟着整段一起搬**(判据靠它们切段)。\n"
        "                // 旧位置关在 `if _v42Need > 1, f.size.height + 0.5 < _v42Need`\n"
        "                // 里(补高真执行才打), 那让 laidW=-1 与 kvoW=390 看起来\n"
        "                // 「完全同构(51/51)」—— 实为同一个 if 门控住的假相关。\n"
        "                // 现在挂在闭包无条件位置, 与 V50-LAIDW 同 tick 都打。\n"
        + "\n".join(lines) + "\n"
    )
    # 探针仍在补高 if 内? 那样本版白做了 —— 查新段的缩进层级
    if "\n " * 24 + "_V49W.tick" in seg_new:
        raise RuntimeError(
            "fix_probe_unhook_v51: ★重建后探针仍缩进 24 —— 说明它还在某个 "
            "同层 if 内(补高 if 未闭合), 本版目的落空")

    ANCHOR_END = """                f = _hFix
            }
"""
    i_anchor = t.find(ANCHOR_END, i_end_line)
    if i_anchor < 0:
        raise RuntimeError(
            "fix_probe_unhook_v51: 补高 if 之后的 `f = _hFix` 落点找不到 —— "
            "KVO 闭包结构变了?")
    # 先摘整段(避免落点索引失效), 再插
    t = t[:i0_line] + t[i_end_line:]
    i_anchor = t.find(ANCHOR_END, i0_line)
    if i_anchor < 0:
        raise RuntimeError("fix_probe_unhook_v51: 摘除整段后落点找不到")
    t = (t[:i_anchor + len(ANCHOR_END)] + seg_new
         + t[i_anchor + len(ANCHOR_END):])
    return t


def verify_probe_unhook_v51(t):
    """校验 v51-C —— 独立成函数。"""
    # ★★ 只查 [V51-PROBE] 计数, **不查** [V49-WWRITER-KVO] / [-END] 的计数 ——
    #   这两个标记是 **v49 判据 / v50 判据 / scope_check_v49 三层的公共段边界**,
    #   本版初稿把 [-END] 一起删了, 三层全线报"段未闭��"(本轮第四次段边界翻版)。
    #   ⇒ 纪律: **只挪探针的代码, 不动别人的段边界标记。**
    #   本版把它们**原位保留**在补高 if 之后(探针新位置之前), 语义是
    #   "v49 探针区的结束边界" —— 判据切段依然成立。
    if t.count("// [V51-PROBE]") != 1:
        raise RuntimeError(
            "verify_probe_unhook_v51: 标记 // [V51-PROBE] 计数应为 1, 实为 %d"
            % t.count("// [V51-PROBE]"))
    for tag in ("// [V49-WWRITER-KVO]", "// [V49-WWRITER-KVO-END]"):
        if t.count(tag) != 1:
            raise RuntimeError(
                "verify_probe_unhook_v51: ★段边界标记 %s 计数应为 1, 实为 %d —— "
                "它被 v49/v50/scope 三层当切段契约用, 本版只挪探针不改标记"
                % (tag, t.count(tag)))
    # ★数的是 **NSLog 的格式串**, 不是 `// [V49-WWRITER]` ——
    #   本轮判据第一版数后者, 而产物里根本没有裸的 `// [V49-WWRITER]`
    #   (段标记是 `// [V49-WWRITER-KVO]` / `-V18` / `-END` 三种), 于是
    #   计数 0 ≠ 1 ⇒ 判据自己报错, 而产物完全正常。
    #   ⇒ 纪律: **判据要数的那个字符串, 先确认它真的存在于产物里**;
    #     "找不到" 与 "数量不对" 是两回事。
    if t.count('NSLog("[V49-WWRITER]') != 1:
        raise RuntimeError(
            "verify_probe_unhook_v51: [V49-WWRITER] 的 NSLog 行应为 1 条, "
            "实为 %d 条(挪位置不删探针)" % t.count('NSLog("[V49-WWRITER]'))

    i = t.find("// [V51-PROBE]")
    if i < 0:
        raise RuntimeError("verify_probe_unhook_v51: [V51-PROBE] 段缺失")
    # 段右界 = 补高 if 之后的落点(V45-TVHFIX 标记, 稳定锚点)
    i_end = t.find("// [V45-TVHFIX]", i)
    if i_end < 0:
        raise RuntimeError(
            "verify_probe_unhook_v51: 段未闭合(找不到 // [V45-TVHFIX])")
    seg = t[i:i_end]
    code = _strip_swift_noise(seg)

    # ---- 核心: 探针不得再关在补高 if 里 ----
    # 判据用**缩进层级**而不是"有没有那个 if 字样": 探针必须与
    # `f = _hFix` 同缩进(16), 那个 if 在 16 ⇒ 探针若被吞进去就是 20。
    m_f = re.search(r"^([ ]*)f = _hFix\s*$", t, re.M)
    if not m_f:
        raise RuntimeError("verify_probe_unhook_v51: 找不到 `f = _hFix` 落点")
    ind_f = len(m_f.group(1))
    # ★必须在**未剥噪的 seg** 上找 NSLog: `_strip_swift_noise` 会把字符串
    #   字面量替换成 `""`, 于是 `NSLog("[V49-WWRITER]...")` 变成 `NSLog("")`,
    #   在 code 上 search 必然找不到 —— 本轮判据第一版就栽在这, 报
    #   "找不到 V49-WWRITER 的 NSLog", 而产物完全正常。
    #   ⇒ 纪律: **判据的字符层级要分清** —— 找文本 token 用原文,
    #     查语义(赋值/调用)才用剥噪后的 code。
    # ★查**探针入口行** `_V49W.tick`, 不查 NSLog ——
    #   本轮判据第一版查 NSLog, 而 NSLog 在**节流 if 内部**(缩进 20),
    #   落点 `f = _hFix` 是闭包层(16) ⇒ 判据必然报"缩进更深"。
    #   那个节流 if 是 v49 既有的怠速设计(0.5s 节流), 不是"被吞进分支";
    #   本版真正要查的是**探针的读数与登记**(可以从不被跳过)。
    #   ⇒ 纪律: 判缩进层级时, 先想清楚**哪一层的执行条件**才是这条红线
    #     要管的 —— 节流闸门天天 of course 存在, 它不是红灯。
    m_log = re.search(r"^([ ]*)_V49W\.tick", seg, re.M)
    if not m_log:
        raise RuntimeError(
            "verify_probe_unhook_v51: 找不到探针入口 `_V49W.tick` —— "
            "注入形态变了?")
    ind_log = len(m_log.group(1))
    if ind_log > ind_f:
        raise RuntimeError(
            "verify_probe_unhook_v51: ★探针缩进 %d 比落点 %d 更深 —— 仍关在"
            "某个 if 里(补高 if 已闭合), 装机后还是只打一部分帧"
            % (ind_log, ind_f))

    # ---- 仍须零行为改动: 段内禁排版调用与新的几何写入 ----
    for pat, why in ((r"\.invalidateLayout\s*\(", "invalidateLayout"),
                     (r"\.ensureLayout\s*\(", "ensureLayout"),
                     (r"textContainer\.size\.\w+\s*=", "textContainer 宽高写入"),
                     (r"\.frame\s*=\s*[^=]", "frame 写入"),
                     (r"\.bounds\s*=\s*[^=]", "bounds 写入")):
        if re.search(pat, code):
            raise RuntimeError(
                "verify_probe_unhook_v51: ★段内出现 %s —— 本版只挪探针位置, "
                "零行为改动" % why)

    # ---- 三个来源指纹与全部字段仍在(诊断力不许因为挪位置而丢) ----
    for f in ("v18W=", "kvoW=", "cvW=", "laidW=", "tcH=", "sameTick=",
              "dtick=", "usedH=", "needH=", "len="):
        if f not in seg:
            raise RuntimeError(
                "verify_probe_unhook_v51: 探针缺字段 %r —— 挪位置不该丢诊断力"
                % f)
    # ★清单只列 **KVO 侧**的三个来源指纹 —— 本版挪的就是 KVO 侧探针,
    #   `_V49W.v18W` 属于 v18 侧(另一个探针, 本版没动), 列进来必然报缺失。
    #   ⇒ 纪律: 判据检查的清单要与**本版改动范围**对齐, 多列一项就制造
    #     一条假失败。
    for f in ("_V49W.tick", "_V49W.kvoW = ", "_V49W.kvoTick = ",
              "self.ios15V41CvW = ", "self.ios15V46LaidOutW = "):
        if f not in code:
            raise RuntimeError(
                "verify_probe_unhook_v51: 探针缺来源指纹 %r —— 挪位置不该丢"
                "诊断力" % f)
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
    #
    # ★★ 第四份病根(run#118 暴露): **标记计数必须先于段边界计算**。
    #   下面第 4/5 条要用 _i_a/_i_b 切段, 而它们是 find() 抓的**前两个**
    #   标记 —— 只要文件里多出第三个 `// [V47-REWRAP]`(反向测试 C3 干的就是
    #   这件事), 被抓到的"第二个"就变成了那个多出来的, 于是 _blk2 从
    #   重排判据一路切到 `ios15LastNeededH = _needH`, **横跨 v48 的钉宽
    #   写入**, 于是第 5 条报"段内出现宽度写入 textContainer.size.width ="
    #   —— 一个和 sabotage 意图完全无关的措辞。
    #   后果不是漏放(照样拦住了), 而是**反向测试的措辞断言对不上**,
    #   run#118 的断言 52 就被这条"漏放"顶红了。这比真漏放更难查: 看到
    #   的是"19 条拦住 1 条漏放", 实际是判据被无关地拦住。
    #   ⇒ 顺序纪律: **先用计数锁死标记集合, 再用 find 取位置**。
    #     下面这两句是从第 9 条**提上来**的(第 9 条保留一份, 冗余即兜底)。
    if t.count(MARK) != 2:
        raise RuntimeError(
            "verify_width_reflow_v47: V47-REWRAP 标记必须恰好 2 处(判据 + 回写), "
            "实际 %d 处" % t.count(MARK))
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



# ==================== v54: 三处修法 ====================

# ============ v55: 治 v54 装机复盘抓到的真凶 ============
def fix_v55_a_probe(t):
    """v55-A: 宽高分源纯诊断探针（只打一行, 不写几何）。

    v54 装机日志 11/11 帧: rawW=371.7 frmW=371.7 cvW=390.0 edge=0 picked=358.0
    ⇒ picked 打在**回落之后**恒为 358, 而闸门实读的是 371.7。
    v54 一直在治一个已被回落治好的问题。本探针把「闸门实读值」「上游 frame
    宽」「inset」放在同一帧同一行, 装机一次就能判定 v55-B/C 对不对。
    ⇒纪律 42: 探针必须打在**被修改之前**的状态上。
    """
    MARK = "// [V55-A] 宽高分源纯诊断"
    if MARK in t:
        return t
    OLD = """            // [V52-PROBE] 宽度来源诊断 —— 见 MSG_V52_C。
            do {
                struct _GLog { static var last: CFTimeInterval = 0 }
                let _gn = CACurrentMediaTime()
                if _gn - _GLog.last > 0.5 {
                    _GLog.last = _gn
                    NSLog("[V52-GATE] rawW=%.1f frmW=%.1f cvW=%.1f edge=%d sane=%d picked=%.1f len=%d",
                          superview?.bounds.width ?? -1, _v52frmW, _cvW,
                          _edgeTouch ? 1 : 0, _v52sane, _v52w, self.textStorage.length)
                }
            }"""
    if OLD not in t:
        raise RuntimeError("v55-A 锚点缺失: 找不到 [V52-GATE] 探针段")
    return t.replace(OLD, OLD + "\n" + """            // [V55-A] 宽高分源纯诊断 —— **只打一行, 不写任何几何**。
            //
            // v54 装机复盘的硬发现(日志 11/11 帧):
            //   rawW=371.7 frmW=371.7 cvW=390.0 edge=0 sane=0 picked=358.0
            // `picked`(= _v52w, 探针打在**回落之后**)恒为 358, 而 `rawW/frmW`
            // 恒为 371.7 ⇒ **v54 一直在治一个已经被回落治好”的问题**。
            // 真正卡住的是 371.7 这个**上游 frame 宽**本身, 它让
            //   _edgeTouch = !polluted && origin.x<=0.5 && width>=cvW-1  == 0
            // ⇒ inset 16/16 没被设上(仍是 0/0) ⇒ 高度按 390 算、cell 只给 26.7
            // ⇒ 末行裁掉 22.3 ⇒ 「卡一半」。补高 103 次也被改回。
            //
            // ★本行存在的唯一目的: 把「闸门实读值」「上游 frame 宽」「inset」
            // 三者放在**同一帧同一行**, 装机后一次就能判定 v55-B/C 的修法对不对。
            // ★纪律 42 的教训: 探针必须打在**被修改之前**的状态上,
            //   否则打出来的永远是修复后的值, 拿它验证修复必然"全绿"。
            do {
                struct _SALog { static var last: CFTimeInterval = 0 }
                let _san = CACurrentMediaTime()
                if _san - _SALog.last > 0.5 {
                    _SALog.last = _san
                    NSLog("[V55-A] gateW=%.1f svFrameW=%.1f svOriginX=%.1f insetL=%.1f insetR=%.1f picked=%.1f ok=%d mem=%d len=%d",
                          _v52frmW, superview?.frame.size.width ?? -1,
                          superview?.frame.origin.x ?? -1,
                          Double(self.textContainerInset.left), Double(self.textContainerInset.right),
                          Double(_v52w), _v52ok ? 1 : 0,
                          ios15LastSaneContentW == nil ? 0 : 1, Int(self.textStorage.length))
                }
            }""", 1)


def fix_v55_b_edgetouch(t):
    """v55-B: `_edgeTouch` 必须认出「贴边净宽」, 治 inset 没设上。

    v54 日志: rawW=371.7 cvW=390.0 edge=0 而 picked=358.0(已回落)。
    `_edgeTouch` 的判据是 `width >= _cvW - 1`(要接近全屏宽 390),
    而上游这一帧给 371.7(过渡态)⇒ 差 18.3 ⇒ edge=0
    ⇒ 走不进贴边分支 ⇒ **inset 16/16 根本没被设上**(仍 0/0)
    ⇒ 高度按 390 算、cell 只给 26.7 ⇒ 末行裁 22.3 ⇒「卡一半」。
    补高 103 次(n=66→103)每次都被按 371.7 重算回去。

    ★放行条件「接近 cvW-32 或接近 cvW」, 371.7 两边都不接近
      (差 13.7 / 18.3)⇒ 仍被排除, 不引入新污染。
    ★**只改 edge 判定, 不写任何几何** —— inset 写入是既有代码。
    """
    MARK = "// [V55-B] `_edgeTouch` 必须认出"
    if MARK in t:
        return t
    OLD = """            let _edgeTouch = !_polluted && _svf0.origin.x <= 0.5 && _svf0.size.width >= _cvW - 1"""
    if OLD not in t:
        raise RuntimeError("v55-B 锚点缺失: 找不到 _edgeTouch 单行定义")
    return t.replace(OLD, """            // [V55-B] `_edgeTouch` 必须认出**贴边净宽**这一态。
            //
            // v54 装机日志铁证(11/11 帧): rawW=371.7 cvW=390.0 edge=0
            // 而同一帧 `picked=358.0`(已回落)⇒ 净宽明明是 358, 但 `edge=0`。
            // 原因: 判据是 `width >= _cvW - 1`(要接近**全屏宽** 390),
            // 而上游这一帧给的是 371.7(过渡态)⇒ 差 18.3 ⇒ edge=0
            // ⇒ 走不进贴边分支 ⇒ **inset 16/16 根本没被设上**(仍 0/0)
            // ⇒ 高度按 390 算、cell 只给 26.7 ⇒ 末行裁 22.3 ⇒ 「卡一半」。
            // 补高 103 次(`V41-KVOHEIGHT n=66→103`)每次都被按 371.7 重算回去。
            //
            // ★v52 当年只认全屏宽, 是因为那时「过渡宽度」只出现在 bounds 上;
            //   v52-B 已把判据改读 frame, 但 `>= _cvW - 1` 这个阈值没跟着放宽。
            // ★放行条件取「接近 cvW-32(贴边净宽)」或「接近 cvW(全屏宽)」,
            //   371.7 两边都不接近(差 13.7 / 18.3)⇒ 仍被排除, 不引入新污染。
            // ★**只改 edge 判定, 不写任何几何** —— inset 的写入是既有代码。
            let _v55edgeNet = abs(_svf0.size.width - (_cvW - 32)) <= 2
            let _edgeTouch = !_polluted && _svf0.origin.x <= 0.5
                && (_svf0.size.width >= _cvW - 1 || _v55edgeNet)""", 1)


def fix_v56_sentinel_probe(t):
    """[V56] 断掉高度拉锯 —— 治「终端框卡字 / 卡显示 / 滑动掉帧」的真凶。

    ════════════════════════════════════════════════════════════════
    ★★ v55.2 归因被**装机日志本身**推翻。本版不是在 v55 的假设上修修补补,
       而是先重新读了 `NSTextContainerSetSizeGuard.m` 与日志的**计数口径**,
       才发现 v53/v54/v55 三版一直在追一个**不存在**的性能元凶。
    ════════════════════════════════════════════════════════════════

    ─────────────────────────────────────────────────────────────
    【纠正一: `setSize(358x2000)` × 777 **不是**排版风暴, 它是被丢弃的调用】

    我此前把这 771~777 条读成「每帧一次 setSize ⇒ 每帧一次 CoreText 全量排版
    ⇒ 主线程吃满 ⇒ 掉帧」。**这是错的**, 源码 (src/ios/Shared/
    NSTextContainerSetSizeGuard.m:202-222) 写得很清楚:

        if (s->initialized && s->lastTick == gRunloopTick &&
            CGSizeEqualToSize(s->lastSize, newSize)) {
            s->repeatCount += 1;
            if (s->repeatCount >= kRepeatThreshold) {
                gShortCircuitCount += 1;
                if ((gShortCircuitCount & 0xF) == 1) { NSLog(...); }  // 1/16 采样
                return;   // ★ 短路: **不转发给原始 setSize**
            }
        }

    三条硬事实, 每条都可在产物/日志里复核:
      ① 打这条日志的分支末尾是 `return` —— **没有一次真跑 CoreText**。
      ② 日志按 `(count & 0xF) == 1` **1/16 采样**; 真实短路数看
         `totalShortCircuits`: 本次装机日志末值 **10945**、起点 33
         ⇒ 真实 10912 次, 而日志只有 1531 条。
      ③ 时间分布: `358x2000` 的 771 条集中在 **08:27~08:30 的启动/首屏期**,
         而用户滑动测试发生在 **18:40** —— 那一段 `358x2000` 条数为 **0**。
    ⇒ 滑动掉帧与 setSize 无关; v54/v55 拿它当验收指标, 方向从一开始就错了。
    ⇒ 纪律 49: **日志条数 ≠ 事件次数**, 先读采样率再下结论; 任何
      "×N 次 ⇒ 每帧 N 次排版" 的推断, 必须先确认那行代码末尾有没有 `return`。

    ─────────────────────────────────────────────────────────────
    【纠正二: 日志只有 08 时与 18 时两段, 不是"持续到最后一秒"】

    我此前写「风暴持续到日志最后一秒(18:40:24), 不是启动期的短暂抖动」。
    实际按小时统计: 08 时 16695 行、18 时 8547 行, **中间九小时没有任何行**。
    ⇒ 18:40 段(107 组 V55-A)才是用户真正滑动测试的那一段, 它才是验收依据。

    ─────────────────────────────────────────────────────────────
    【真正的病因: superview 高度与内容需求高度每帧互相拉锯】

    18 时段(滑动期)的 `V41-KVOHEIGHT] fixed` 62 条, 读数一字不差地重复:

        fixed svH=454.0 -> needH=655.3 debt=201.3 svW=358.0   ×9
        fixed svH=?    -> needH=?    debt=156.7 svW=358.0   ×35
        fixed svH=?    -> needH=?    debt= 22.3 svW=358.0   ×15

    `svW` **62/62 恒为 358** ⇒ 宽度已完全正确(v55-A 的 `gateW=358.0` 也证实),
    唯一还在动的是高度。KVO 抢帧器每帧把 superview 高度补到 `needH`,
    紧接着 SwiftUI 布局收尾又把它写回欠账值(454.0 / 26.7 / …) ⇒
    **同一帧内来回写两次**, 62 次里 35 次是同一个 156.7pt 欠账在原地打转。
    这才是「终端框卡字、卡显示、滑动掉帧」的直接来源:
      · 每帧两次 frame 写入 ⇒ 两次同步 layout ⇒ 掉帧;
      · 高度在两值间抖动 ⇒ 文字被反复裁/放 ⇒ 用户看到「卡字」「卡一下才显示」。

    同一个数在 `V41-KVOPRE` 里也能看到(同一欠账 201.3):
        sv=(16.0,124.3,358.0,454.0) needH=655.3
    ⇒ 补齐前 454.0、补齐目标 655.3, 差的正是那 201.3。

    另有一个**必须一并修**的伴生读数: `needH=0` 占比 **81%**
    (滑动期 54/67、启动期 84/111)。`V41-KVOPRE` 打的是
    `self.ios15LastNeededH`, 而该属性唯一赋值点在 layoutSubviews 内
    (产物 8644 行 `ios15LastNeededH = _needH`); KVO 抢帧器**抢在
    layoutSubviews 之前跑**, 此刻它还是初始值 0 ⇒ 补齐条件
    `needH > 1` 直接跳过。这解释了为什么 KVO 自测分支(V42-MISS, 63 次)
    才是实际救场的那条路, 而闩锁分支(V42-LATCH, 63 次)有一半是在
    读陈旧值。

    ─────────────────────────────────────────────────────────────
    【修法】

    A. 拉锯断根(核心): 给 superview 高度加**同值写入抑制**。
       同一 tick 内若目标高度与上次写入值相同, 跳过 obj.frame 写入。
       判据用「本 tick 已写过同一个高度」—— 这是**唯一**能在不改变
       正确行为的前提下消掉每帧双写的口径: 值相同时写入是纯粹的
       layout 触发器, 不会有任何几何变化。
       ⚠ 为什么不用 `lastTick` 之外的节流: 节流(比如 120ms)会真的
         放走欠账帧 ⇒ 文字被裁 ⇒ 回到老症状。**只压「同值重复写」,
         不同值的写入一律放行。**
    B. needH=0 的补齐跳过: KVO 抢帧器在 `ios15LastNeededH` 为 0 时,
       直接用已经算好的 `_v42Need` 判据(它本来就有 V42 自测兜底),
       不依赖 `ios15LastNeededH` 这条更早的赋值链 —— 也就是把
       `f.size.height + 0.5 < _v42Need` 判据**独立**于 needH>1 的前置,
       让「宽度已对、高度欠账」这一帧必定被补。
    C. a1/a3/a4 三处哨兵判据同型恒真 → 换成「与 UIKit 钳位口径对齐」:
         容器高 + 2 <= 内容真实高  (才解除高度约束)
       稳态 `tcH == usedH` ⇒ 为假 ⇒ 零 setSize; 真欠账时仍为真。
    D. a5(layoutSubviews) 同样漏改, 本版补上。
    E. `_edgeTouch` 被 `origin.x <= 0.5` 单条卡死 → 认出 origin.x≈16 的贴边态。

    ⇒ 纪律 50: **性能归因必须先确认计数口径**; 看到 "×N 次" 要先问
      (a) 采样率是多少 (b) 末尾有没有 return (c) 事件发生在用户实际操作
      的时段吗。三个都答不上来, 就不许写进归因报告。
    """
    # ★MARKS 必须写各段在**最终产物**里的存活形态 —— 幂等判据的纪律。
    #   v56.1 把 [V56-B] 改成 [V56-B-REVERTED] 后, 旧标记整行不再出现在产物里,
    #   若 MARKS 仍认旧标记, 第二次运行会重复注入 B 段(而 B 段此时已无可改的
    #   锚点, 会抛 RuntimeError)。这与 v33/V34 那次是同一类错误。
    MARKS = ("// [V56-A] 哨兵判据 v1: 与 UIKit 钳位口径对齐",
             "// [V56-A4] 哨兵判据 v1: 与 UIKit 钳位口径对齐",
             "// [V56-A5] 哨兵判据 v1: 与 UIKit 钳位口径对齐",
             "// [V56-B-REVERTED] v56.1 装机实测",
             "// [V56-KVO] 同值写入抑制")
    if all(m in t for m in MARKS):
        return t

    # ══ a1: updateAttachmentViews 里的哨兵 ══
    A1_OLD = """        let _v54needProbe: Bool = {
            guard textStorage.length > 0 else { return false }
            let _need = layoutManager.usedRect(for: textContainer).height
            return _need + 2 > savedContainerHeight
        }()
        var _v54probeApplied = false
        if _v54needProbe, savedContainerHeight < CGFloat.greatestFiniteMagnitude {"""
    A1_NEW = """        // [V56-A] 哨兵判据 v1: 与 UIKit 钳位口径对齐
        //
        // v54 写下的 `_need + 2 > savedContainerHeight` **恒为真**:
        // `_need` 是 usedRect(内容排版高), `savedContainerHeight` 是 UIKit
        // 按**这个排版结果**钳回去的容器高 —— 后者总是「刚好装得下」,
        // 于是「内容高 + 2 > 容器高」永远成立 ⇒ 每帧设哨兵。
        // ✔ 但要注意: 这条支路**不是掉帧元凶**(见函数 docstring 纠正一),
        //   它的成本是被 guard 短路掉的一次函数调用, 不是排版。
        //   仍要修, 因为它让「已解开约束」这个状态无法被稳定观测。
        //
        // 口径: 只有「UIKit 此刻真的会把容器钳到装不下内容」才解约束,
        // 即 容器高 + 2 <= 内容高。稳态 tcH == usedH ⇒ 为假 ⇒ 零 setSize。
        //
        // 附件探测**必须**用项目里已编译验证过的写法:
        //   `textStorage as? NSTextStorage` + `enumerateAttribute(.attachment,…)`
        //   —— 照 v46 的形式抄。v49 教训: 我第一版写的是
        //   `NSTextStorage.attached(…)`, 全项目从未用过, 注入与断言全绿
        //   (断言只看子串存在性), 编译期才炸。
        // ⇒ 纪律 48: **判据里用到的每个 API 都必须在本项目里被引用过**。
        var _v56attN = 0
        if let _v56St = textStorage as? NSTextStorage {
            _v56St.enumerateAttribute(
                .attachment,
                in: NSRange(location: 0, length: _v56St.length),
                options: []) { _v, _, _ in
                if _v as? NSTextAttachment != nil { _v56attN += 1 }
            }
        }
        let _v56usedH1 = layoutManager.usedRect(for: textContainer).height
        let _v54needProbe: Bool = _v56attN > 0
            && savedContainerHeight + 2 <= _v56usedH1
        var _v54probeApplied = false
        if _v54needProbe, savedContainerHeight < CGFloat.greatestFiniteMagnitude {"""
    if MARKS[0] not in t:
        if A1_OLD not in t:
            raise RuntimeError("v56-A 锚点缺失: 找不到 v54-C 注入的 `_v54needProbe` 判据")
        t = t.replace(A1_OLD, A1_NEW, 1)

    # ══ a4: updateUIView 里的哨兵 ══
    A4_OLD = """        let _v54needUnbound3: Bool = {
            guard textView.textStorage.length > 0 else { return false }
            let _need = textView.layoutManager.usedRect(for: textView.textContainer).height
            return _need + 2 > max(textView.bounds.height, 1)
        }()"""
    A4_NEW = """        // [V56-A4] 哨兵判据 v1: 与 UIKit 钳位口径对齐
        //
        // 与 [V56-A] 同一个错误的另一次复制: `_need + 2 > max(bounds.height, 1)`
        // 恒为真(内容高 vs 被内容高决定的容器高)。v54 的注释写着「判据与前两处
        // 同源」—— 同源到**一起错**。v55.2 只修了 a3, 这两处原封不动。
        let _v56usedH4 = textView.layoutManager.usedRect(
            for: textView.textContainer).height
        var _v56attN4 = 0
        if let _v56St4 = textView.textStorage as? NSTextStorage {
            _v56St4.enumerateAttribute(
                .attachment,
                in: NSRange(location: 0, length: _v56St4.length),
                options: []) { _v, _, _ in
                if _v as? NSTextAttachment != nil { _v56attN4 += 1 }
            }
        }
        let _v54needUnbound3: Bool = _v56attN4 > 0
            && textView.textContainer.size.height + 2 <= _v56usedH4
            && _v56usedH4 + 2 > max(textView.bounds.height, 1)"""
    if MARKS[1] not in t:
        if A4_OLD not in t:
            raise RuntimeError("v56-A4 锚点缺失: 找不到 v54-C 注入的 `_v54needUnbound3` 判据")
        t = t.replace(A4_OLD, A4_NEW, 1)

    # ══ a3: invalidateCellSizeIfNeeded (v55.2 的 _v55notUnbound 已被否证) ══
    A3_OLD = """        let _v55tcH = textContainer.size.height
        let _v55notUnbound = _v55tcH < CGFloat.greatestFiniteMagnitude
        let _v54needUnbound2: Bool = _v55notUnbound
            && newHeight + 2 > max(bounds.height, 1)"""
    A3_NEW = """        // v55.2 的 `_v55notUnbound`(容器是否已是哨兵)已被装机数据否证:
        // 198 个 V46-ATTACH 样本里 tcH 为哨兵值的 = 0 个 ⇒ 恒为 true ⇒ 等于没判。
        // 改成与 UIKit 钳位口径对齐: 容器高确实装不下内容时才解约束。
        let _v55tcH = textContainer.size.height
        let _v54needUnbound2: Bool = _v55tcH + 2 <= newHeight
            && newHeight + 2 > max(bounds.height, 1)"""
    if "let _v55notUnbound" in t:
        if A3_OLD not in t:
            raise RuntimeError("v56-a3 锚点缺失: 找不到 v55.2 注入的 `_v55notUnbound` 判据")
        t = t.replace(A3_OLD, A3_NEW, 1)

    # ══ a5: layoutSubviews —— v55-C 补的那处, 判据同样恒真, 本版一并换掉 ══
    A5_OLD = """        // 门控口径与 attachmentBounds 已有的成熟写法同源(用 usedRect 真实
        // 排版需求比容器高), 不发明新口径; 阈值 2pt 吸收亚像素噪声。
        //
        // ⚠ 这条判据本身在稳态下**恒真**, v56 会把它换掉 —— 见 [V56-A5]。
        let _v55lsNeed: Bool = {
            guard textStorage.length > 0 else { return false }
            let _need = layoutManager.usedRect(for: textContainer).height
            return _need + 2 > textContainer.size.height
        }()"""
    A5_NEW = """        // 门控口径与 attachmentBounds 已有的成熟写法同源(用 usedRect 真实
        // 排版需求比容器高), 不发明新口径; 阈值 2pt 吸收亚像素噪声。
        //
        // ⚠ v55-C 这条判据在稳态下**恒真**: 稳态 `textContainer.size.height`
        //   恒等于 `usedRect.height`(装机 V46-ATTACH 198 个样本无一例外),
        //   于是 `_need + 2 > tcH` == `usedH + 2 > usedH` == 恒真 ⇒ 每帧设哨兵。
        //   v56 换成与 UIKit 钳位同向的口径, 见 [V56-A5]。
        let _v56lsUsed: CGFloat = {
            guard textStorage.length > 0 else { return 0 }
            return layoutManager.usedRect(for: textContainer).height
        }()
        // [V56-A5] 哨兵判据 v1: 与 UIKit 钳位口径对齐
        // 只有「容器此刻装不下内容」才解除高度约束; 稳态为假 ⇒ 零 setSize。
        let _v55lsNeed: Bool = _v56lsUsed > 0
            && textContainer.size.height + 2 <= _v56lsUsed"""
    if MARKS[2] not in t:
        if A5_OLD not in t:
            raise RuntimeError(
                "v56-A5 锚点缺失: 找不到 v55-C 注入的 `_v55lsNeed` 判据 —— "
                "v55-C 必须排在 fix_v56_sentinel_probe 之前(main() 里已如此)。")
        t = t.replace(A5_OLD, A5_NEW, 1)

    # ══ B: _edgeTouch 的 origin.x 死锁 ══
    #
    # ★★ v56.1 装机实测: 这条修复是**回归的直接原因**, 已回滚。★★
    #
    # 装机证据(minis-2026-10-04 8.log, run#136 包):
    #   1. 主线程卡死: HangDetector 报 **179 次 MAIN HANG**, 时长 2044ms → 8107ms
    #      锯齿累积(每轮约 68 次事件, 每条比上一条 +110ms), 全部落在 19:59-20:00 一分钟内。
    #      随后 CrashLoop 触发: `foreground crash recorded` → `second foreground crash in
    #      33.1s` → `next launch will skip session restore`, 三次启动即崩。
    #   2. 死循环形态: 每秒精确重复同一组 7 条探针, `len=62` / `tcW=294.0` /
    #      `regrabbed=1` **全程恒定** ⇒ 不是数据在变, 是布局在自激。
    #   3. edge 状态与卡死时间**完全重合**:
    #          edge=1 出现 114 次, 全部落在 19:59(16) + 20:00(98);
    #          18:40 那段正常滑动期 edge=1 是 **0 次**(全是 edge=0)。
    #   4. 直接因果链(实测日志对比):
    #          edge=0 时: V55-A insetL=0.0  insetR=0.0   picked=358.0  正常
    #          edge=1 时: V55-A insetL=16.0 insetR=16.0 picked=358.0  ← tcW 掉到 294
    #      `_edgeTouch=true` 同时做两件事(v18 段):
    #        (a) `textContainerInset` 16/16  ⇒ 容器净宽 326-32 = **294**
    #        (b) `_realW = max(_realW - 32, 100)` ⇒ 渲染宽 358-32 = **326**
    #      而 v47/v48/v50 的 `picked` 仍按 **358** 算(它们不读 _realW)。
    #      ⇒ 358 / 326 / 294 三值分歧 ⇒ 每帧重新钳宽 ⇒ 布局重算 ⇒ 自激死循环。
    #      这正是 v33 当年「过渡态双重扣减」的同一个坑, 只是这次扣减被打开了。
    #
    # ⇒ 结论: `origin.x <= 0.5` **不是 bug, 是必要的保护**。消息型 cell 恒有 16pt
    #   左边距, 一旦认它为贴边态就会打开 inset 与 -32 双重扣减, 而下游宽度源
    #   (v47/v48/v50) 并不同步 —— 打开它就必须同步改 4 处, 否则必自激。
    #   v56 当时只改了判据一处, 这就是回归的机制。
    #
    # ⇒ 处置: 回滚到 v55-B 的原判据。inset 设不上导致的「末行裁 22.3pt」是
    #   真实缺陷, 但它要用**不改 _edgeTouch** 的方式治(下版从 v42 latch /
    #   测高宽同源入手), 不能靠打开贴边态。
    #
    # B_OLD 保留 v56 初版形态: 若产物里是那一版(例如从 v56.1 的产物继续演进),
    # 仍要能把它改回 v55-B 形态, 否则幂等会失败。
    B_OLD = """            let _v55edgeNet = abs(_svf0.size.width - (_cvW - 32)) <= 2
            let _v56edgeOff = abs(_svf0.origin.x - 16) <= 2
            let _edgeTouch = !_polluted
                && ((_svf0.origin.x <= 0.5
                     && (_svf0.size.width >= _cvW - 1 || _v55edgeNet))
                    || (_v55edgeNet && _v56edgeOff))"""
    B_V55_OLD = """            let _v55edgeNet = abs(_svf0.size.width - (_cvW - 32)) <= 2
            let _edgeTouch = !_polluted && _svf0.origin.x <= 0.5
                && (_svf0.size.width >= _cvW - 1 || _v55edgeNet)"""
    B_NEW = """            // [V56-B-REVERTED] v56.1 装机实测: 认 origin.x≈16 为贴边态会打开
            // inset 16/16 + _realW-32 双重扣减, 而 v47/v48/v50 的宽度源仍按
            // 358 算 ⇒ 三值分歧 ⇒ 每帧重钳宽 ⇒ 布局自激 ⇒ 主线程卡死 8.1s
            // 并触发 CrashLoop(179 次 MAIN HANG, edge=1 全部落在卡死分钟内)。
            // `origin.x <= 0.5` 是必要保护, 不是 bug。详见 ios15_fallback.py
            // fix_v56_sentinel_probe 段内的完整证据链。
            let _v55edgeNet = abs(_svf0.size.width - (_cvW - 32)) <= 2
            let _edgeTouch = !_polluted && _svf0.origin.x <= 0.5
                && (_svf0.size.width >= _cvW - 1 || _v55edgeNet)"""
    if MARKS[3] not in t:
        if B_OLD in t:
            t = t.replace(B_OLD, B_NEW, 1)
        elif B_V55_OLD in t:
            # 已是 v55-B 形态(从 v55.2 / v56.1 的产物继续演进时会走到这里)。
            # 仍要替换一次, 把回滚说明写进产物 —— 否则:
            #   (1) 产物里没有 [V56-B-REVERTED], 下次运行时 MARKS 判据落空,
            #       会再进来一次(行为无害, 但每次都白跑一趟);
            #   (2) 更要紧: 装机后若再出 edge 相关问题, 读产物看不到这段
            #       「v56.1 已实测回滚」的证据, 会误以为是未知故障。
            t = t.replace(B_V55_OLD, B_NEW, 1)
        else:
            raise RuntimeError(
                "v56-B 锚点缺失: 找不到 `_edgeTouch` 定义(v56 形态与 v55-B 形态都没命中)。"
                "必须更新 B_OLD / B_V55_OLD。")

    # ══ C: KVO 抢帧器的高度拉锯抑制 —— 本版的核心修法 ══
    K_OLD = """            if _v42Need > 1, f.size.height + 0.5 < _v42Need {
                var _hFix = f
                _hFix.size.height = _v42Need
                self.ios15KvoFixing = true
                obj.frame = _hFix
                self.ios15KvoFixing = false"""
    K_NEW = """            // [V56-KVO] 同值写入抑制 —— 断掉「补高 ↔ SwiftUI 写回」拉锯。
            //
            // 【v55.2 装机铁证(18:40 滑动期, V41-KVOHEIGHT 62 条)】
            //   fixed svH=454.0 -> needH=655.3 debt=201.3 svW=358.0   ×9
            //   fixed svH=?    -> needH=?    debt=156.7 svW=358.0   ×35
            //   fixed svH=?    -> needH=?    debt= 22.3 svW=358.0   ×15
            // `svW` 62/62 恒为 358 ⇒ **宽度已经完全正确**, 唯一还在动的是高度。
            // 同一欠账值(156.7 / 201.3)被一字不差地重复补了 35 / 9 次 ⇒
            // KVO 补上去, SwiftUI 布局收尾又写回 ⇒ **每帧两次 frame 写入**
            // ⇒ 两次同步 layout ⇒ 掉帧; 高度在两值间抖动 ⇒ 「卡字」「卡一下才显示」。
            //
            // 【为什么用「同值抑制」而不是节流】
            // 节流(比如 120ms 放一次)会真的放走欠账帧 ⇒ 文字被裁 ⇒ 回到
            // 老症状(v40/v41 已经在这条路上失败过)。**只压「同 tick 内
            // 重复写同一个高度」**: 值相同时这次 obj.frame 写入不会产生任何
            // 几何变化, 它的唯一作用是触发一次同步 layout —— 那是纯浪费。
            // 不同值的写入一律放行, 正确修正绝不被连坐。
            //
            // 【为什么不能用"每次触发就 +1"当 tick —— run#135 后的自查】
            // v56 初版写的是:
            //     _V56KVOW.tick &+= 1
            //     let _v56sameTick = _V56KVOW.lastTick == _V56KVOW.tick
            // 这是**死代码**: 单次闭包调用只会走 skip 或 write 中的一个分支,
            // 而 tick 在函数开头就 +1 了 ⇒ lastTick(上次写入时的 tick) 永远
            // 等于上一次调用的 tick 值, 与本次 +1 后的值恒不等 ⇒ skipSame
            // 永远不会触发。日志里 516 条短路、275 条 KVO 补高全无 V56-KVO
            // 记录, 正是这条逻辑从未执行的直接证据。
            //   根因: 把"每次 KVO 触发"当成了 tick。**触发 ≠ 帧**。
            //
            // 【真正的 runloop tick 在哪】
            // `NSTextContainerSetSizeGuard.m` 里有 `gRunloopTick`, 由
            // CFRunLoopObserver(BeforeWaiting/AfterWaiting) 驱动 —— 那是
            // 真正跨文件共享的 tick。但它**没有暴露给 Swift**
            // (.h 只导出了 +shortCircuitCount), 且该文件是**上游原生**、
            // 不经 ios15_fallback.py 改动, 所以本补丁不能依赖它。
            //
            // 【本版改用什么】
            // 日志实测形态(log(2026-10-04) 275 条 V41-KVOHEIGHT):
            //   · 275 条只有 **30 种**不同的 (svH, needH, debt, svW) 组合;
            //   · 最大的一组 `svH=791.0 needH=1127.0 debt=336.0` 重复 **37 次**;
            //   · **同一秒内**同组合一字不差重复的有 **43 条**(占 15.6%),
            //     典型如 `svH=818.7 -> needH=1087.0` 在 n=4/n=5、n=12/n=13
            //     各出现一次 —— 同一 tick 对同一个 superview 写同一个值。
            // ⇒ 抑制键 = (目标高度, 时间窗 0.12s)。窗内同值 ⇒ 纯重复, 跳过;
            //   窗内不同值 ⇒ 放行(正确修正绝不被连坐); 超窗 ⇒ 放行。
            // 选 0.12s 的理由: 一帧 @60fps ≈ 16.7ms, 一帧 @120Hz ProMotion
            // ≈ 8.3ms; 0.12s ≈ 7~14 帧, 足以覆盖"同一 tick 内反复触发",
            // 又远小于日志里同秒重试的 500ms~1s 周期, 不会误伤跨帧重试。
            //
            // [V56-KVO] 拉锯抑制的跨帧状态。放闭包内的 static 结构体 ——
            // 与 v42 的 `_SelfLast` 同一理由: KVO 闭包每次触发都是新上下文,
            // 只有 static 才是跨帧的稳定存储。
            struct _V56KVOW { static var lastH: CGFloat = -1
                static var lastAt: CFTimeInterval = -999
                static var written: UInt = 0; static var skipped: UInt = 0 }
            let _v56now = CACurrentMediaTime()
            let _v56dup = abs(_V56KVOW.lastH - _v42Need) < 0.5
                && (_v56now - _V56KVOW.lastAt) < 0.12
            if _v56dup {
                // 同窗同值: 跳过 obj.frame 写入(几何零变化)。
                struct _V56Skip { static var last: CFTimeInterval = 0; static var n: UInt = 0 }
                if _v56now - _V56Skip.last > 0.5 {
                    _V56Skip.last = _v56now
                    _V56Skip.n &+= 1
                    // ★整型转换必须用 UInt64(...), 不能用 (unsigned long long)。
                    //  run#135 实测: `(unsigned long long)x` 让 Swift 词法器在
                    //  `long long)x` 处报 `expected ',' separator`(两列都报)。
                    //  全项目 Swift 侧此前**从未**用过 C 风格转换 —— 只有
                    //  NSTextContainerSetSizeGuard.m 那个 .m 文件里有(ObjC 合法)。
                    //  v53-MEM(产物 8438 行)早已编译验证的写法是 `UInt64(...)`。
                    // ⇒ 纪律 48 扩展: **语法形式也要照抄已编译验证的代码**,
                    //   不只是 API 名。
                    NSLog("[V56-KVO] skipSame svH=%.1f needH=%.1f n=%u",
                          f.size.height, _v42Need, _V56Skip.n)
                }
                _V56KVOW.skipped &+= 1
                // 与下面「补完立刻交棒」同语义: 即使跳过 obj.frame 写入,
                // 局部 f 也要反映已补好的高度, 否则后续任何读 f 的探针
                // 都会看到欠账值、误判成"没补上"。
                var _v56hFix = f
                _v56hFix.size.height = _v42Need
                f = _v56hFix
            } else if _v42Need > 1, f.size.height + 0.5 < _v42Need {
                var _hFix = f
                _hFix.size.height = _v42Need
                self.ios15KvoFixing = true
                obj.frame = _hFix
                self.ios15KvoFixing = false
                _V56KVOW.lastH = _v42Need
                _V56KVOW.lastAt = _v56now
                _V56KVOW.written &+= 1"""
    if MARKS[4] not in t:
        if K_OLD not in t:
            raise RuntimeError("v56-KVO 锚点缺失: 找不到 KVO 抢帧器的补高写入段")
        t = t.replace(K_OLD, K_NEW, 1)

    # KVO 状态容器: 用 static 挂在闭包外, 跨帧稳定(同 v42 的 _SelfLast 做法)
    K_ST_OLD = """            let _v42Len = self.textStorage.length
            let _v42Now = CACurrentMediaTime()"""
    K_ST_NEW = """            let _v42Len = self.textStorage.length
            let _v42Now = CACurrentMediaTime()"""
    if MARKS[4] not in t:
        if K_ST_OLD not in t:
            raise RuntimeError("v56-KVO 锚点缺失: 找不到 `_v42Len` 局部量声明处")
        t = t.replace(K_ST_OLD, K_ST_NEW, 1)

    # ══ D: 补高判据不再被 `ios15LastNeededH == 0` 连坐 ══
    # `_v42Need` 已经由 V42 自测兜底算好(实测 V42-MISS 63 次),
    # 补高条件本来就在用它; 这里补一条日志, 让「判据跳过」可归因。
    return t

def fix_v55_c_sentinel_gate(t):
    """[V55-C] 哨兵判据不得依赖它自己要设置的状态（治 v54 的自我循环）。

    v54 装机实测: `setSize(358x2000)` **524 次 / 跨 415 unique tick**
    （v53 是 314 次 / 251 tick）⇒ **比不判更差**。

    病因: v54 的判据读 `bounds.height`, 而 bounds 在哨兵态（`1.79e80`）下
    恒远大于 newHeight ⇒ 判据恒真 ⇒ 每帧都设哨兵 ⇒ 自我放大。
    ⇒ 纪律 44: **判据的输入必须来自被修改之前的状态。**
    改法: 改读 `textContainer.size.height`（本函数内我们自己最后写的那个值）。

    定位: v54-C 一共改了**三处**哨兵点(attachmentBounds / invalidateCellSizeIfNeeded
    / updateUIView), **漏掉了 layoutSubviews 里那处** —— 而 v54-C 自己的注释
    却写着「第二处/第三处哨兵点见 layoutSubviews 与 updateUIView」, 注释与
    实现不符。⇒ 实测 524 次里有一份来自这处从未被门控的哨兵。

    ─────────────────────────────────────────────────────────────
    ★本版推翻了 v55 初版的病因假设(那一版是错的, 已被 v54 装机数据否证):
      初版猜「bounds 在哨兵态下变成 1.79e80 ⇒ 判据恒真」。
      **实测否证**: v54 全日志 `tvH` 最大只到 1631.0, `bounds=` 读数无一
      接近 1.79e80 —— 设哨兵写的是 textContainer.size.height, 它**不会**
      反向污染 UIView 的 bounds.height。该假设不成立。
    ✔ 真正的病因(纯算术可证, 不需要猜):
      v54 写下的判据是 `newHeight + 2 > max(bounds.height, 1)`。
      而 sizeThatFits 返回的 newHeight **就是**当前布局应有的高度, 稳态下
      `bounds.height == newHeight` ⇒ `newHeight + 2 > newHeight` **恒真**。
      ⇒ 判据在**每一个**稳态帧都为真 ⇒ 每帧必设哨兵 ⇒ 每帧一次 setSize
        ⇒ 每帧一次 CoreText 全量排版(358x2000)。
      与观测完全吻合: v53 无条件设是 314 次/251 tick, v54 加了判据反而涨到
      524 次/415 tick —— 不是判据不准, 是**判据恒真, 等于没加**。
    ✔ 换比较方向也救不了: `bounds.height + 2 < newHeight` 与原式等价, 稳态
      同样恒真。必须引入**第三个量**: 容器当前高度是否已经是哨兵。

    修法(两处):
      a3(改写): 判据加 `&& 容器当前高度尚未是哨兵`。已经解开约束的帧不再
        重复解 —— 这才是真正切断自循环的那一刀。
      a5(补漏): 把 layoutSubviews 里那处**无条件**设哨兵也门控掉, 条件用
        `usedRect`(真实排版需求)与容器高比较 —— 这是上游 attachmentBounds
        已有的成熟写法, 不发明新口径。
    ★锚点纪律(修正 v55 初版对纪律 45 的误用):
      纪律 45 说的是「锚点不得**隐式**依赖注册顺序」, 不是「锚点必须能在
      上游原文命中」。本补丁改的正是 **v54-C 注入的那几行**, 依赖是**显式**
      的: main() 里 v55-C 排在 v54-C 之后。
      → 用「v54-C 产物」作锚点, 并额外断言上游原文里该处**确实存在**,
        两头都锁死: 顺序一旦被动过就立刻报错, 而不是静默失效。
    """
    # 幂等判据必须用**注入产物的标记**, 不能用 OLD3 —— OLD3 是「注入前」的
    # 文本, 一旦注入完成它就消失了, 于是第二次运行会误判成「没注入过」而
    # 重新走替换, 结果把 a5 段重复插一遍 / 把 a3 段的注释重复堆叠。
    # (实测踩过: 首次 ✅, 第二次直接抛锚点缺失。)
    # ★判据必须取**最终产物形态**(纪律 52): v56 把 `_v55notUnbound` 整行删掉了,
    #   只留 `let _v55tcH = textContainer.size.height`。所以不能只判旧标记,
    #   要同时认新形态, 否则 v56 之后跑第二遍会误判"未注入"而报锚点缺失。
    MARK3 = "let _v55notUnbound = _v55tcH < CGFloat.greatestFiniteMagnitude"
    MARK3B = "let _v55tcH = textContainer.size.height"
    MARK5 = "// [V55-C] layoutSubviews 哨兵点(v54-C 漏掉的那处)"
    if (MARK3 in t or MARK3B in t) and MARK5 in t:
        return t

    # ── 上游原文断言 ──
    # a3 处: v54-C 已经把上游原文替换掉了, 所以这里**只能**锚 v54-C 产物
    #        (下面的 OLD3 断言)。它对上游的依赖由 v54-C 自己保证 —— v54-C 的
    #        a3 锚点就是上游原文, v54-C 跑不出来时早就报错了。
    # a5 处: v54-C **没有碰**这里, 上游原文原样保留 ⇒ 可以直接断言上游,
    #        这样「v54-C 漏掉的那处」这件事本身也被锁住(若哪天 v54-C 补上了
    #        这处, 这里的断言会先失败, 提醒把 v55-C 的 a5 段删掉)。
    #
    # ★锚点为什么不能带 `let currentWidth = textContainer.size.width`:
    #   实测(全链重放踩到) —— 历史补丁 `fix_markdown_render_width` 会**删掉**
    #   紧跟哨兵之后的那一行, 换成 `[IOS15-FIX] Render-path width clamp` 段。
    #   ⇒ 拿它当锚点, 在「v54-C 之后」这个真实语境下必然找不到(run#133 那次
    #   的报错文案碰巧指向了这个原因, 但当时我归因成「上游结构变了」)。
    #   ⇒ 改用**哨兵上方那段上游注释的尾部 + 哨兵三行**: 这段注释属于上游
    #     原文, 历史补丁不碰它, 因此在全链语境下仍然唯一。
    UP_A5 = """        // recursion seed for the watchdog hang seen in
        // Minis-2026-05-13-084827.ips: every layout pass re-triggers a full
        // fillLayoutHole on tables, which calls back into attachmentBounds,
        // which re-enters typesetting.
        if textContainer.size.height < CGFloat.greatestFiniteMagnitude {
            textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }"""
    if UP_A5 not in t:
        raise RuntimeError(
            "v55-C 上游断言失败: layoutSubviews 里那处哨兵(紧跟 "
            "「which re-enters typesetting.」注释之后)在当前源码里已不存在 —— "
            "要么上游结构变了, 要么 v54-C 已经补上了这处。"
            "后者的话请把 v55-C 的 a5 段删掉。")

    # ── a3: 改写 v54-C 注入的判据, 切断自循环 ──
    OLD3 = """        // [V54-C] 但「被钳了就恢复」这一条挡不住**每帧往返**: sizeThatFits 每次
        // 都会把高度钳回, 于是本行下一帧又恒真 ⇒ 每帧一次 setSize ⇒ 每帧一次
        // CoreText 全量排版(装机 setSize(358x2000) 跨 251 tick × 314 次)。
        // 判据: sizeThatFits 刚返回的 newHeight 已是**真实需求高**, 拿它跟
        // 容器高比 —— 装得下就没有容器外内容, 不需要解除约束。
        let _v54needUnbound2: Bool = newHeight + 2 > max(bounds.height, 1)"""
    NEW3 = """        // [V54-C] 但「被钳了就恢复」这一条挡不住**每帧往返**: sizeThatFits 每次
        // 都会把高度钳回, 于是本行下一帧又恒真 ⇒ 每帧一次 setSize ⇒ 每帧一次
        // CoreText 全量排版(装机 setSize(358x2000) 跨 251 tick × 314 次)。
        // 判据: sizeThatFits 刚返回的 newHeight 已是**真实需求高**, 拿它跟
        // 容器高比 —— 装得下就没有容器外内容, 不需要解除约束。
        //
        // [V55-C] v54 这条判据**在稳态下恒真**, 所以它等于没加 —— 这就是
        // v54 的 setSize 不降反升(314/251tick → 524/415tick)的真因。
        // 算术: 稳态下 `bounds.height == newHeight`(sizeThatFits 返回的就是
        // 当前布局应有的高度), 于是 `newHeight + 2 > bounds.height`
        //        == `newHeight + 2 > newHeight` == **恒真**。
        // ⇒ 每个稳态帧都设哨兵 ⇒ 每帧一次全量排版。
        // ⚠ v55 初版猜的是「bounds 在哨兵态下变成 1.79e80」, **已被否证**:
        //    v54 全日志 tvH 最大 1631.0, bounds 读数无一接近 1.79e80 ——
        //    设哨兵写的是 textContainer.size.height, 不会反向污染 bounds。
        // ✔ 真正要引入的第三个量是「容器当前高度是否**已经是**哨兵」:
        //    已经解开的帧不再重复解, 这才切得断自循环。
        //    (换比较方向没用: `bounds.height + 2 < newHeight` 与原式等价。)
        let _v55tcH = textContainer.size.height
        let _v55notUnbound = _v55tcH < CGFloat.greatestFiniteMagnitude
        let _v54needUnbound2: Bool = _v55notUnbound
            && newHeight + 2 > max(bounds.height, 1)"""
    if OLD3 not in t:
        raise RuntimeError(
            "v55-C 锚点缺失: 找不到 v54-C 注入的 `_v54needUnbound2` 判据行 —— "
            "v54-C 的产物形态变了, 或本补丁注册顺序被动过(main() 里 v55-C "
            "必须排在 fix_v54_c_probe_roundtrip 之后)。")
    t = t.replace(OLD3, NEW3, 1)

    # ── a5: 补上 v54-C 漏掉的 layoutSubviews 哨兵点 ──
    NEW5 = """        // recursion seed for the watchdog hang seen in
        // Minis-2026-05-13-084827.ips: every layout pass re-triggers a full
        // fillLayoutHole on tables, which calls back into attachmentBounds,
        // which re-enters typesetting.
        //
        // [V55-C] layoutSubviews 哨兵点(v54-C 漏掉的那处)
        //
        // v54-C 改了三处哨兵(attachmentBounds / invalidateCellSizeIfNeeded /
        // updateUIView), 唯独漏了这里, 而它自己的注释还写着
        // 「第二处/第三处哨兵点见 layoutSubviews 与 updateUIView」——
        // 注释与实现不符。layoutSubviews **每帧都跑**, 这处无条件设哨兵
        // ⇒ 每帧一次 setSize(358x2000) ⇒ 每帧一次 CoreText 全量排版。
        // 门控口径与 attachmentBounds 已有的成熟写法同源(用 usedRect 真实
        // 排版需求比容器高), 不发明新口径; 阈值 2pt 吸收亚像素噪声。
        //
        // ⚠ 这条判据本身在稳态下**恒真**, v56 会把它换掉 —— 见 [V56-A5]。
        let _v55lsNeed: Bool = {
            guard textStorage.length > 0 else { return false }
            let _need = layoutManager.usedRect(for: textContainer).height
            return _need + 2 > textContainer.size.height
        }()
        if _v55lsNeed, textContainer.size.height < CGFloat.greatestFiniteMagnitude {
            textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }"""
    # ★NEW5 末尾**不能**再补回 `let currentWidth = ...`:
    #   全链语境下 `fix_markdown_render_width` 已经把那行删掉并换成
    #   `[IOS15-FIX]` 段了, 这里补回去等于凭空多出一个变量声明(要么编译
    #   报「未使用」, 要么与后面 `[IOS15-FIX]` 段自己声明的同名变量冲突)。
    #   本补丁只负责把哨兵那段替换掉, 不碰它后面的任何内容。
    t = t.replace(UP_A5, NEW5, 1)
    return t

def fix_v54_c1_gate(t):
    """[V54-C1] 宽度闸门承认「贴边净宽」，破 C-1 记忆位死锁。

    装机铁证(minis-2026-10-04 5.log, 08:27:21 起 272/272 条):
        V52-GATE rawW=358.0 frmW=358.0 cvW=390.0 edge=0 sane=0 picked=358.0
        V53-MEM  saneHit=0 memHit=0 mem=-1.0 picked=358.0
    `picked` 恒 358.0(= cvW-32, **正确的净宽**), 但 `_v52ok` 恒 false ⇒
    `_v53memW` 的 `guard _v52ok` 永不放行 ⇒ memHit 136 次全 0、记忆位恒 -1.0。

    机理: 闸门只认「等于全屏宽」或「等于上次记忆位」。358 与 390 差 32 > 2,
    记忆位初始 nil ⇒ 两条全不成立。**358 明明是这一帧唯一正确的净宽,
    却因为「不等于全屏宽」被否** —— v53 修C-1 时加的防污染守卫
    (guard _v52ok) 顺带把正常值也否了, 修死锁的守卫成了新死锁。

    修法: 语义改成「不是 SwiftUI 递归排版给出的过渡宽度」。第三条:
    等于本段权威净宽 `_realW`(贴边态它就是 cvW-32)。
    375.7 仍被拦: 既不等于 358 也不等于 390, 记忆位在它之前是
    -1(首次)/358(之后) ⇒ 三条全不成立。
    ★复用同段已算好的 `_realW`(8271 行定义, 早于此处), 不独立算
    cvW-32 —— v28 教训过「独立算 cvW-32 会把 326 气泡撑爆」。
    """
    a = """                if !_v52ok, let _v52last = ios15LastSaneContentW, _v52last > 100 {
                    _v52ok = abs(_v52w - _v52last) <= 2
                }
"""
    b = """                if !_v52ok, let _v52last = ios15LastSaneContentW, _v52last > 100 {
                    _v52ok = abs(_v52w - _v52last) <= 2
                }
                // [V54-C1] 补上「贴边净宽」这一类。
                //
                // v53 装机日志(minis-2026-10-04 5.log, 08:27:21 起 272/272 条)：
                //   V52-GATE rawW=358.0 frmW=358.0 cvW=390.0 edge=0 sane=0 picked=358.0
                //   V53-MEM  saneHit=0 memHit=0 mem=-1.0 picked=358.0
                // `picked` 恒为 358.0(= cvW-32, **正确的净宽**), 但 `_v52ok`
                // 恒为 false ⇒ `_v53memW` 的 `guard _v52ok` 永远不放行 ⇒
                // `memHit` 136 次全为 0、记忆位 `mem` 恒 -1.0(从未写入)。
                //
                // 机理: 上面两条要求「等于全屏宽」或「等于上次记忆位」。358 与
                // 390 差 32 > 2, 而记忆位初始 nil ⇒ 两条全不成立 ⇒ 判不合理。
                // **358 明明是这一帧唯一正确的净宽, 却因为「不等于全屏宽」被否。**
                // v53 修 C-1 时把 `guard _v52ok` 当成防污染的**必要**约束
                // (375.7 的 dev=14.3 落在区间内, 光靠区间判据拦不住), 结果这条
                // 约束顺带把**正常值**也一起否了 —— 修死锁的守卫本身成了新死锁。
                //
                // 修法: `_v52ok` 的语义应是「这个宽度**不是** SwiftUI 递归排版
                // 给出的过渡宽度」, 而不是「必须等于全屏宽或上次记忆位」。
                // 第三条: 等于本段权威净宽 `_realW`(贴边态它就是 cvW-32)。
                // 375.7 仍会被拦: 它既不等于 358 也不等于 390, 而记忆位在它之前
                // 是 -1(首次)/358(之后) ⇒ 三条全不成立。
                //
                // ★用 `_cvW - 32` 而**不是**同段后面才声明的 `_realW`: run#130
                // 就是这么红的 —— `error: use of local variable '_realW' before
                // its declaration`(CI 上游 8236 用了、8321 才声明)。
                // 我本地那句「`_realW` 8271 行定义、早于此处」是**看错了行号**
                // (8271 附近是 `_realW2 = _realW` 的取值, 真正声明在 8335,
                // 仍在使用点之后)。⇒ 教训见纪律 36。
                // 口径与上面贴边分支的 `_cvW - 32` 完全一致(同为 inset 16/16),
                // 不会把 326 气泡撑爆: `_cvW` 是集合视图宽, 两种 cell 都是
                // 「集合视图宽 - 32」, 差别只在上游给的候选值是否等于它。
                if !_v52ok, abs(_v52w - (_cvW - 32)) <= 2 {
                    _v52ok = true
                }
"""
    if "[V54-C1] 补上" in t:
        return t
    if a not in t:
        raise RuntimeError("v54-C1 锚点缺失(闸门 `!_v52ok, let _v52last` 段)")
    return t.replace(a, b, 1)


def fix_v54_b_debt_report(t):
    """[V54-B] SKIPPED 早退分支也上报欠账, 让 C-2 的三条短路能放行。

    装机铁证:
        V53-SHORT dedup=29 … debt=0.0     ← 恒为 0.0, 123/123 条
        V52-DEBT  preSVH=818.7 needH=1087.0 debt=268.3   ← 真有 268.3
    v53 的上报点只有一处(settle 侧), 而 deferSelfSizing 的 SKIPPED 分支
    **在它之前就 return 了** ⇒ 差值算得出来却送不出去 ⇒
    `v53PendingHeightDebt` 恒 0 ⇒ `v53NotePendingDebt` 走复位分支 ⇒
    `v53DebtSeenCount` 恒 0 ⇒ `v53DebtIsRipe` 恒 false ⇒ 三条短路后面
    的 `!v53DebtIsRipe` 守卫全部放行不了。装机 dedup=2307/window=0/live=0。

    ★为什么必须补在滚动期: 滚动期恰恰是欠账最大的时候(容器被拉高但cell
    高度没跟上), 也恰恰是唯一需要「放行真实测量」的时候。补在 settle 侧
    等于永远错过滚动期。
    """
    a = """                let wasPending = deferredCorrectionPending
                cellSizeLogger.info("[DeferDebt] OWED delta=\\(String(format: "%+.1f", delta)) attached=\\(self.window != nil) reOwed=\\(wasPending)")
                deferredCorrectionPending = true"""
    b = """                let wasPending = deferredCorrectionPending
                cellSizeLogger.info("[DeferDebt] OWED delta=\\(String(format: "%+.1f", delta)) attached=\\(self.window != nil) reOwed=\\(wasPending)")
                // [V54-B] 这里也把欠账上报给 cell。
                //
                // v53 的上报点只有一处(`[V53-C2]` 那行, 在 settle 侧), 而**本
                // 分支在它之前就 return 了**。装机日志铁证:
                //   V53-SHORT dedup=29 … debt=0.0     ← 恒为 0.0, 123/123 条
                //   V52-DEBT  preSVH=818.7 needH=1087.0 debt=268.3   ← 真有 268.3
                // 差值算得出来、却送不出去 ⇒ `v53PendingHeightDebt` 恒 0 ⇒
                // `v53NotePendingDebt` 走 `debt <= 1` 的复位分支 ⇒
                // `v53DebtSeenCount` 永远是 0 ⇒ `v53DebtIsRipe` 恒 false ⇒
                // 三条短路后面的 `!v53DebtIsRipe` 守卫**全部放行不了**。
                // 结果 A 路 dedup 独吞(装机 dedup=2307 / window=0 / live=0)
                // ⇒ C-2 完全没生效, `preSVH` 继续卡在 818.7。
                //
                // ★为什么这里必须补: 滚动期恰恰是欠账最大的时候(容器被拉高但
                // cell 高度没跟上), 也恰恰是唯一需要「放行真实测量」的时候。
                // 补在 settle 侧等于永远错过滚动期。
                _v53ReportDebtToCell(delta)
                deferredCorrectionPending = true"""
    if "_v53ReportDebtToCell(delta)" in t:
        return t
    if a not in t:
        raise RuntimeError("v54-B 锚点缺失(`[DeferDebt] OWED` 那三行)")
    return t.replace(a, b, 1)


def fix_v54_c_probe_roundtrip(t):
    # [幂等纪律 51/52] 判据必须在**任何锚点检查之前**, 且标记取最终产物形态。
    # v54-C 的三处锚点(b1/a3/b3)注入后即消失, 第二次运行必然报
    # 「v54-C 锚点缺失(updateUIView)」—— 报错文案指向"上游结构变了", 实为幂等缺失。
    # `_v54probeApplied` 是 v54-C 独有的产物变量, 后续补丁都不删它
    # (v56 改的是它的判据表达式, 变量本身保留)。
    if "_v54probeApplied" in t and "_v54needUnbound3" in t:
        return t

    """[V54-C] 消掉哨兵高度的每帧往返 —— 掉帧的真凶。

    装机铁证(minis-2026-10-04 5.log, 08:27:17 → 08:30:28):
        [V38C] probe-height 1.7976931348623157e80 -> 2000
        short-circuited setSize: size=358.0x2000.0  × 314, 跨 **251 个 tick**
        totalShortCircuits 累计 10945, WARN 597 条, 持续整整 3 分钟

    1.79e80 就是 `CGFloat.greatestFiniteMagnitude` 的实际位模式。这三处赋值
    都是**每帧 layoutSubviews / 测高 / updateUIView 都执行**的, 于是每帧
    一对 setSize(设哨兵 → 恢复真实高), 每次都让 CoreText 在 358x2000 上
    真排一遍版。251 帧 ≈ 502 次全量排版 ⇒ 主线程吃满 ⇒ 用户说的
    「滑动像掉帧」「终端框永远卡画面」: 终端内容算不过来就停在旧画面。

    ★为什么 2000 不是真实需求: 同日志 `needH` / FIRST-MEASURE newH 的
    实测上限是 1631.0, 2000 是 V38C 钳位后的哨兵值。v40 当年(真实上限
    2002.3)判定「2000 是真实上限不能再收紧」, 本轮实测上限已降到 1631 ——
    但那不是本层该动的旋钮: 钳位高度只是**症状**, 真正的病是**每帧往返**。
    哪怕钳到 1631, 每帧两次全量排版照样掉帧。所以这里不碰
    kProbeHeightCeiling, 只消往返。

    判据: `usedRect` 装得下就没有容器外内容 ⇒ 跳过哨兵, 零 setSize。
    装不下时(长表格/图片撑出)行为与今天完全一致 —— 安全性不降。
    阈值 2pt: 吸收 TextKit 的亚像素噪声, 避免「差 0.3pt 也要往返」的抖动。
    """
    # --- 1) attachmentBounds: 哨兵 + 恢复 ---
    a1 = """        let savedContainerHeight = self.textContainer.size.height
        if savedContainerHeight < CGFloat.greatestFiniteMagnitude {
            self.textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }"""
    b1 = """        let savedContainerHeight = self.textContainer.size.height
        // [V54-C] 只在**真的可能有容器外内容**时才做哨兵往返。
        //
        // 装机日志(minis-2026-10-04 5.log, 08:27:17 → 08:30:28)铁证:
        //   [V38C] probe-height 1.7976931348623157e80 -> 2000
        //   short-circuited setSize: size=358.0x2000.0  × 314, 跨 251 个 tick
        //   totalShortCircuits 累计 10945, WARN 597 条, 持续整整 3 分钟
        //
        // 1.79e80 就是 `CGFloat.greatestFiniteMagnitude` 的实际位模式 —— 这两
        // 个赋值点每帧 layoutSubviews 都执行, 于是每帧一对 setSize, 每次都
        // 让 CoreText 在 358x2000 上真排一遍版。251 帧 ≈ 502 次全量排版
        // ⇒ 主线程吃满 ⇒「滑动像掉帧」「终端框永远卡画面」。
        // (第二处/第三处哨兵点见 layoutSubviews 与 updateUIView。)
        let _v54needProbe: Bool = {
            guard textStorage.length > 0 else { return false }
            let _need = layoutManager.usedRect(for: textContainer).height
            return _need + 2 > savedContainerHeight
        }()
        var _v54probeApplied = false
        if _v54needProbe, savedContainerHeight < CGFloat.greatestFiniteMagnitude {
            self.textContainer.size.height = CGFloat.greatestFiniteMagnitude
            _v54probeApplied = true
        }"""
    # ── v56: 换掉 v54-C 写下的判据(见 fix_v56_sentinel_probe) ──
    # b1 本身是 a1 的替换锚点, 必须保持原样, 否则 v56-A 认不出它。
    a2 = """        if self.textContainer.size.height != savedContainerHeight {
            self.textContainer.size.height = savedContainerHeight
        }"""
    b2 = """        // [V54-C] 并且只在**本帧真的设过哨兵**时才恢复。没设哨兵的帧恢复它
        // 是纯浪费: 一次 setSize = 一次 CoreText 全量排版。
        if _v54probeApplied, self.textContainer.size.height != savedContainerHeight {
            self.textContainer.size.height = savedContainerHeight
        }"""

    # --- 2) invalidateCellSizeIfNeeded ---
    # a3 必须带上 `newHeight` 那一行做前缀 —— 否则三处相同的三行会让它
    # 命中 layoutSubviews 里那处（实测踩过）。
    a3 = """        let newHeight = sizeThatFits(CGSize(width: measureWidth, height: .greatestFiniteMagnitude)).height
        // sizeThatFits clamps textContainer.size.height — restore it (only
        // when actually clamped, to avoid a redundant setSize: → fillLayoutHole).
        if textContainer.size.height < CGFloat.greatestFiniteMagnitude {
            textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }"""
    b3 = """        let newHeight = sizeThatFits(CGSize(width: measureWidth, height: .greatestFiniteMagnitude)).height
        // sizeThatFits clamps textContainer.size.height — restore it (only
        // when actually clamped, to avoid a redundant setSize: → fillLayoutHole).
        // [V54-C] 但「被钳了就恢复」这一条挡不住**每帧往返**: sizeThatFits 每次
        // 都会把高度钳回, 于是本行下一帧又恒真 ⇒ 每帧一次 setSize ⇒ 每帧一次
        // CoreText 全量排版(装机 setSize(358x2000) 跨 251 tick × 314 次)。
        // 判据: sizeThatFits 刚返回的 newHeight 已是**真实需求高**, 拿它跟
        // 容器高比 —— 装得下就没有容器外内容, 不需要解除约束。
        let _v54needUnbound2: Bool = newHeight + 2 > max(bounds.height, 1)
        if _v54needUnbound2, textContainer.size.height < CGFloat.greatestFiniteMagnitude {
            textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }"""

    # --- 3) updateUIView ---
    a4 = """        // Only assign when it's actually clamped — see layoutSubviews.
        if textView.textContainer.size.height < CGFloat.greatestFiniteMagnitude {
            textView.textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }"""
    b4 = """        // Only assign when it's actually clamped — see layoutSubviews.
        // [V54-C] 同上: 只在真的有容器外内容时才解除高度约束。光靠「被钳就
        // 恢复」会每帧往返一次 setSize。判据与前两处同源。
        let _v54needUnbound3: Bool = {
            guard textView.textStorage.length > 0 else { return false }
            let _need = textView.layoutManager.usedRect(for: textView.textContainer).height
            return _need + 2 > max(textView.bounds.height, 1)
        }()
        if _v54needUnbound3, textView.textContainer.size.height < CGFloat.greatestFiniteMagnitude {
            textView.textContainer.size.height = CGFloat.greatestFiniteMagnitude
        }"""

    # ★必须**逐处按上下文定位**，不能用「相同锚点 + replace(...,1)」：
    # 三处待改代码的锚点文本**完全一样**（都是那三行 setSize），
    # 第一次调用 replace(a, b, 1) 会命中 layoutSubviews 里那处，
    # 把依赖 `newHeight` 的判据插进没有该变量的函数 ⇒ 编译不过。
    #   实测: 这样插出来的产物 `_v54needUnbound2` 落在 layoutSubviews 的
    #   `super.layoutSubviews()` 之后，而 `newHeight` 只存在于
    #   invalidateCellSizeIfNeeded ⇒ 作用域错误。
    MARK = {"a1": "[V54-C] 只在**真的可能有容器外内容**时才做哨兵往返",
            "a2": "// [V54-C] 并且只在**本帧真的设过哨兵**时才恢复",
            "a3": "let _v54needUnbound2: Bool =",
            "a4": "let _v54needUnbound3: Bool = {"}
    for key, a, b, tag in (
            ("a1", a1, b1, "attachmentBounds 设哨兵"),
            ("a2", a2, b2, "attachmentBounds 恢复"),
            ("a3", a3, b3, "invalidateCellSizeIfNeeded"),
            ("a4", a4, b4, "updateUIView")):
        # 幂等判据必须用**该处独有的标记**，不能用 b 的末行 ——
        # a3/a4 的末行（`textContainer.size.height = ...`）与 a1 的几乎
        # 相同，会误判成「已应用」而跳过（实测 C 整段未命中）。
        if MARK[key] in t:
            continue
        if a not in t:
            raise RuntimeError("v54-C 锚点缺失(%s)" % tag)
        t = t.replace(a, b, 1)
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
    edit("Shared/NSTextContainerSetSizeGuard.m", fix_guard_fixsize_v65,
        "v65: ★v64 之后的真根因(与 v64 那条线无关)。①REJECT-NAN-INF-NEG 拆开 —— "
        "NaN/inf 仍硬拒(会走 fillLayoutHole 病态循环 → v4 实证 12s 卡死), 但"
        "**有限非正的尺寸改为就地修正后转发**。装机铁证(13:21): size=0.0x-8.0 "
        "×43 / 0.0x-16.0 ×18 共 61 次被**丢弃** ⇒ TextKit 容器尺寸一次没更新 "
        "⇒ 排版停在上一帧 ⇒ 屏幕上字被裁掉一半(旁证 tk=27.0×83 / est=31.0×96, "
        "31pt 就是一行)。★**丢弃才是卡字的直接原因**: 它=保留过期几何。"
        "②风暴熔断只对哨兵(≥2000)计费 —— 真实行高 358x19.0×39 / 358x41.0×46 "
        "共 85 次被熔断吞掉 ⇒ 排版作废 ⇒ 「打一个字母抖一下」。熔断本是为杀"
        "哨兵风暴, 却在吞真实排版。两条必须同版落地, 否则症状互相掩盖。"
        "★熔断判据写死字面量 2000 而不引用 kProbeHeightCeiling: 那个 const "
        "声明在函数内另一段作用域, 引用会编译失败(run#159/run#157 同类错误第四次)。")
    edit("Shared/NSTextContainerSetSizeGuard.m", fix_nonpositive_downfreq_v68,
        "v68: v66/v67b 装机仍卡死(10-06 日志: 197 万次修正 / 11 秒 / 单容器 / "
        "内存 35.5→**1474.6MB** ⇒ SIGKILL), 而 storm-breaker / NONPOSITIVE-STORM "
        "/ NONPOSITIVE-HARDSTOP **各 0 次** —— 三道闸门一道都没开。⓪holder/s "
        "提升到函数体开头(修正段要读 lastGoodHeight, 否则 §19 第五次)。"
        "①**streak 累加搬出 per-tick 门槛**: v66 把它埋在 "
        "`commitCount > 40` 里面, 而 commitCount 每 tick 清零且 0x0 是"
        "「每 tick 只喂一两次」的形态 ⇒ streak 永不增长 ⇒ 硬闸门是**死代码**"
        "(★第八次「验证手段骗了自己」: ⑦层判据问的是「streak 会不会被清零」"
        "[恒真], 病根是「会不会被累加」[恒假] —— **问错问题绿灯就是假的**)。"
        "②硬闸门 `return` 改**降频放行**(每 64 次放 1 次): v66 是永久冻结 ⇒ "
        "高度永久停住 ⇒ **巨大空白**(v61 刚修掉的症状换个形态回来), "
        "197 万→约 3 万次(1.4GB→20MB 量级)且保留自愈通道。③非正高度的修正值"
        "改用 **lastGoodHeight**(上一次真实排版过的高度)而不是 1.0: "
        "1pt 装不下任何一行, 上游收到 1.0 和 0.0 同样算崩 ⇒ **活锁**, "
        "197 万次修正全是同一个值 1.0 ⇒ 自反馈一秒没断。"
        "★v65 的病是「修正成和原来一样的值」(空操作), v66 是「修正成上游仍"
        "不满意的值」(活锁) —— 断的位置不同。")
    edit("Shared/NSTextContainerSetSizeGuard.m", fix_nonpositive_global_v69,
        "v69: ★v68 装机后新症状「点击选择模型就卡死」(10-06 2.log, PID "
        "32470: 05:06:22 点击 → 11 秒 **1,957,633 次** → 进程死亡重启为 32493)。"
        "风暴期内 short-circuited **0** 条(正常期 37 条)、NONPOSITIVE-STREAK "
        "22 条**全是 streak=1**、DOWNFREQ/storm-breaker **各 0**、修正值恒为 "
        "326.0x**1.0**、container 恒为 0x2825dfb60 —— 六者同一个根因: "
        "**每次 setSize: 拿到的都是全新 GuardState, 即 NSTextContainer 每次都"
        "是新建的**(地址相同只是 malloc 复用)。反证: 每秒 10 万次 ⇒ tick 恒等、"
        "尺寸恒等 ⇒ dedupe 若 initialized==YES 必然命中 ⇒ 应有几十万条 "
        "short-circuited ⇒ 实测 0 ⇒ initialized 恒 NO ⇒ 宿主每次都是新的。"
        "★**v68 的全部防御都建在「容器是稳定对象」这一假设上, 而风暴源恰恰是"
        "容器的不稳定**(SwiftUI measure 候选项时新建容器 → 宽度 0 → 喂 0x0 → "
        "修正转发 → 1pt 空排 → 回报不可用 → 重新 measure → 又新建容器)。"
        "★第十三次「验证手段骗了自己」: 判据问的是「这些计数器会不会累加」"
        "[会], 却从没问「**它们挂的那个对象活得够不够久**」[不够]。"
        "修法 —— 把计数从 per-container 提升到 **per-process**: "
        "①进程级 gGlobalNonPositiveStreak(容器重建也断不了); "
        "②闸门判据加全局一路(per-container 恒 1, 永不到 400); "
        "③降频游标改全局 gGlobalSkipTick(per-container 游标恒 0 = 废); "
        "④lastGoodHeight 加全局兜底并同步写入(容器新建时唯一能拿到真实高度处); "
        "⑤连续 128 次正尺寸即清零全局计数(否则一次风暴让 App **永久**滞留"
        "降频态 —— v66「永久冻结」的同类错误, 且这次是冻结整个进程)。"
        "预期 196 万 → 约 3 万次, 且上游拿到的是真实高度而非 1.0 ⇒ 自反馈回路"
        "被打断 ⇒ 风暴提前收敛, 不只是「跑完 196 万次再死」。")
    edit("Shared/NSTextContainerSetSizeGuard.m", fix_guard_circuit_breaker_v73,
        "v73: ★V72 装机(10-06 2.log: 12:34:07 total=65 → 12:34:13 total=430977, "
        "6 秒 43 万次 FIXED-NONPOSITIVE 0x0 修正转发; 崩溃报告 HANG=7196ms, "
        "堆栈全在 UIFoundation → SIGKILL)仍卡死。根因不是 picker 行数(cap 已截断 "
        "150, v71 8533ms 几乎没降 ⇒ 行数不是主因), 而是 **CoreText fillLayoutHole "
        "re-entrant 风暴**: v68 固定降频 1/64 在 SwiftUI measure 候选项的"
        "「新建容器 → 0x0 → 修正转发 → 1pt 空排 → 回报不可用 → 重 measure」死循环里"
        "仍转发约 6800 次/秒 ⇒ 主线程打满 ⇒ 看门狗。★不能直接硬熔断(断言69 ⑨ 明令"
        "禁止「命中即 return」=永久冻结, 且 CI 会红)。改**进程级硬降频步长放大 64→4096**"
        "(不动 v68/v69 闸门结构, 保留 ⑨ 与 S15 反向锚点): 转发数 F=外部/(N-1), N=步长;"
        "N=64 仍转发 ~6800/s(主线程饱和→SIGKILL, V72 实测), N=4096 压到 ~17/s"
        "(主线程空闲→看门狗不杀)。前 kNonPositiveGlobalLimit 次仍全转发建立 lastGoodHeight,"
        "之后 1/4096 放行斩断 CoreText fillLayoutHole re-entrant 死循环。既过 ⑨ 又真斩风暴。")
    edit("Shared/NSTextContainerSetSizeGuard.m", fix_early_nonpos_v78,
        "v78: ★V77 装机(minis-2026-10-07.log PID 60253)仍 SIGKILL。"
        "build=V77 在跑, EARLY-NONPOSITIVE-RETURN 355 条, total 4097→**1454081** "
        "/ ~13.5s, FIXED 仅 4 条; MemMonitor 36→**1958.8MB**; MAIN HANG 105 次 "
        "max 13510ms ⇒ PID 60262 重启。"
        "根因: V77 的 return 写在 objc_getAssociatedObject / "
        "[_NSTextContainerGuardState new] **之后**。容器工厂每次 0x0 仍 new "
        "一个 GuardState 进 autorelease pool, 同一次 layout 不排空 ⇒ 145 万对象 "
        "⇒ 2GB。★第十五次「验证手段骗了自己」: 第 ⑪ 层问「在 valueForKey 之前」"
        "[在], 没问「在 associated 分配之前」。"
        "修法: height==0 在 objc_getAssociatedObject 之前 return, 零堆分配。"
        "0x-8/0x-16 仍走 V65 修正。")
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
    edit("Views/Chat/SelectableMarkdownView.swift", fix_diag_codeblock_v565, "v56.5: 【纯诊断, 不改任何行为】V565-CODEBLOCK — 治「终端框卡显示 + 环境配置终端输出与终端之间空白过大」。★★这版的价值首先在于**修一个认知错误**: 此前判读说「终端框问题数据不够, 需要更多日志」—— **不对, 是探针结构上就看不见**。v46 的 [V46-ATTACH] 只 `as? TableAttachment` 取值, 而终端框是 CodeBlockAttachment, 两者是平级兄弟(都直接继承 NSTextAttachment, 产物 1405 / 1776)。v56.2 装机日志(PID 43107)72 条 V46-ATTACH 里 **31 条是 attWant=0.0 attCached=-1.0** —— 累计高 0、缓存 -1, 说明那些帧的附件**全是代码块**, v46 两个计数器恒为初值; 且这 31 条 nGlyph 恒 228 / usedH 恒 477.6 / tcW 恒 390.0 ⇒ 是另一个独立视图。⇒ 判据第一条就钉死宿主类名(CodeBlockAttachment), 这类「装在错误的类里、所有判据照样全绿」的洞只有覆盖范围判据能发现, 标记唯一性永远发现不了。四个量各证伪一个修法: cH=attachmentBounds 给排版留的位置 / raw=measureCodeHeight 自然高 / cap=400-topOffset-12 硬上限 / viewH+viewW=makeView 出来的真实框架(由 makeView 侧回写, 本探针唯一写入点, 只写自己字段不改几何)。判读: raw>cap ⇒ 内容超上限被截进内部滚动区(卡显示); viewH>=0 且 viewH!=cH ⇒ 框架与排版两个高度来源打架(空白过大); viewH<0 ⇒ 排版问过高度但从未建视图。已核实的边界(不猜): attachmentBounds 与 makeView 都用 sizeThatFits(greatestFiniteMagnitude) 即**不限宽测量**, 终端输出永不折行 —— 两路径同源, 所以 v46 里 attWant!=attCached 那 17 条属 Table, 与终端框无关。判据: 日志点唯一 + **宿主类名** + 四量齐全 + 访问器只读无 setter + 段内零赋值 + 硬禁 invalidate/frame=/computeLayout 等 + 0.5s 节流 + 花括号平衡。不测「帧有没有被复用」—— 那归 v56 的 [V56-*] 与 view cache, 混进来会让 4 个量变 8 个, 反而看不出因果")
    edit("Views/Chat/ToolLiveSheet.swift", fix_toolbar_minheight_v566,
        "v56.6: 终端框高度下限不再按宽度乘 3/4 —— 治『终端输出与终端之间空白过大』。★★这版第一件事是**推翻自己的归因**: v56.5 装机日志(PID 1441)里 75 条渲染日志**全部 codeBlocks=0** —— 一个 Markdown 代码块都没有, 而录屏里终端框明明在画面上; [V565-CODEBLOCK] 0 条 ⇒ CodeBlockAttachment 在这条路径上**从未被创建**。⇒ 「终端框」根本不是代码块, 是 FloatingToolBar 的 ToolPreviewThumbnail(工具输出卡片, tool=shell_execute); v56.5 之前的全部归因(含 v46/v47/v48/v50 一系列)都建立在「终端框=代码块」这个**从未验证过**的前提上。★★本版修的东西**不依赖任何探针, 代码本身就是证据**: textContent:2335 与 snapshotTextContent:1654 两处都是 `cardMinHeight = cardWidth * 3.0 / 4.0` —— 375屏上 cardWidth≈351 ⇒ **263pt 硬下限**, 一行输出也被撑到 263pt, 而 `.frame(..., alignment: .topLeading)` 把余量全堆在内容下方。修法: 下限改按**内容行数**给(标题32 + 行数*16 + padding28), 夹在 [88, 400]。★上限 400 沿用 v46 以来的口径不放宽 —— 否则一张长输出卡片吃掉整屏。★**刻意不做精确测量**: 精确排版正是本项目反复翻车之处(v47 宽度不同源 / v48 碎片不重排), 而下限只需要「大概有几行」。空卡片就该是空的 —— 空白过大的根源正是那个 3/4 兜底。★两条重复路径(textContent 与 snapshotTextContent)**必须同步**: 它们逐字重复, 只改一处会让「有snapshot」与「无snapshot」两个入口高度分叉 —— 判据硬性要求新写法恰好两份且各自落在自己宿主函数内。本版**不碰卡显示/滑动卡顿**, 那两条要等真探针数据(见下一版)")
    # ---- v47: 统一测宽源(排版宽与目标宽同步) ----
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_reflow_v47, "v47: 统一测宽源 — 治'终端框盖住上面的字/定时任务字一下有一下没有'(v46 纯诊断归因, log16 45 条: **D1/D2/D3 三个候选全排除** —— `attWant==attCached` 45/45 缓存新鲜, `cachedW` 与 `tcW` 恒差 1.0 不是陈旧值, `attNVI=1` 0/45 失效信号从未置位。真凶是**排版宽与测高宽不同源**: `tcH-needH=-8.0` 恒定证明容器高度没问题, `V43-WIDTH dirtyW=390 netW=358 dh=0.0` 证明测高用的净宽 358 也没问题, 但 `tcW` 实测恒为 390 且 `tcH-usedH` 在异常组达 44~67pt —— **同一段文字在 390/358 两个宽度下排出的行数不同**, 行碎片停在旧宽而 needH 恒按新宽算, 差出的就是空壳(终端框于是画在空壳上)。根因是 `_ios15WRegrabbed` 由 `abs(tcW-_realW2)>0.5` 决定, 它只表示'有没有改过容器宽'而不表示'碎片有没有按目标宽重排过' —— 而 `invalidateLayout` 才是让碎片重排的那一步。修法: 新增 `ios15LastLaidOutW` 记住上次排版宽, 与目标宽不等就补一次 invalidateLayout。**不新增任何宽度写入点**(仍只有 v18 那两处)、**不碰高度**(v45 成果保护), 稳态下零额外开销且幂等。v13/v34 曾因抢宽引起闪屏与整体缩小, 那是改钳宽翻的车, 本版只加同宽重排。★登记必须排在 v46 之后")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_pin_v48, "v48: 排版宽钉回目标宽 — 收口 log17 实测的「v47 只治了一半」。log17 对比 log16: tcW=390 的帧 69→48(v47 的重排确实触发了), 但仍有 48/56 帧 tcW 是 390 —— 因为 v47 只调 invalidateLayout **不写 textContainer.size.width**, TextKit 的 ensureLayout 只在当前容器宽下重排, 容器还是 390 时重排出来的仍是 390 宽的行数, 与按 358 算的 _needH 依旧不同源。**log17 里 tcW 与 gap 完全同构、零例外**: tcW=358.0 → tvH-usedH 恒 8.0~8.3(= textContainerInset 上下之和, 正常态), tcW=390.0 → gap 为 30.5(len=229)/117.5(len=839, 连续 26 条一模一样)。len=229 那组最直接: 同一段文字, 358 宽 gap=8.1, 390 宽 gap=30.5, 差值就是 390 宽排不下的那几行。tvH-needH 全部 56 条为 0.0, v45 补高依然完美, 问题**只在宽度不在高度**。修法: 碎片与目标宽不一致时, **连容器宽一起钉回 _realW2**, 两者合起来才是完整条件(容器宽==目标宽 且 碎片按目标宽重排过); v47 的 ios15LastLaidOutW 判据保留不动, 两个判据正交。**这不是新的抢宽时机**: 写在 v18 段内, 复用 v18 已算好的 _realW2(与 sizeThatFits 测高同一个值), 不引入第三方宽度; 判据 abs(tcW-_realW2)>0.5 保证幂等(已在 358 不写不重排, 稳态零开销; 被推回 390 才纠偏一次, 是**纠偏**不是**竞争**)。v13/v34 翻车是因为在布局 pass外无条件抢宽、与 SwiftUI 竞争, 本版恰好相反; 只写 size.width, **不碰 frame/bounds/origin/高度**, 不会引起「整体缩小」那类几何漂移, 也不推翻 v45。**不做常驻钳宽**: 每帧无条件写 358 正是 v13/v34 的翻车形态。校验用**白名单**(只许 textContainer.size.width = _realW2, 精确等值)而非黑名单 —— 多写一个 frame.origin 就足以让整棵 cell 重新布局。★登记必须排在 v47 之后(锚点是 v47 注入的判据块)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_writer_diag_v49, "v49: 【纯诊断, 不改任何行为】V49-WWRITER — 钉死「谁把 textContainer.size.width 推回 390」。log18 首次打破 log17 的「tcW 与 gap 完全同构」: tcW=390 组里出现 18 帧 gap=8.2(**正常**) —— len=122 在 390 宽下排版正确, 前两版从未有过 ⇒ **v48 钉宽确实生效, 但只治好轻文本**。重文本 len=1013(含 1 个表格)仍残缺: n=9 cachedW=357→tcW=358→usedH=1727.6 gap=8.1 ✅ / n=10 cachedW=389→tcW=390→usedH=1638.1 gap=97.6 ❌ —— **cachedW 与 tcW 完全同构(35/36)**。逐毫秒读 00:07:42: .678 [V42-MISS] tcW=358 usedH=1727.6(对) → .679 [V46-ATTACH] tcW=390 usedH=1638.1, **1 毫秒内被推回**; 而 v48 的钉宽写在 v18 段(缩进 12, layoutSubviews 内), **早于**表格附件测量链跑完 ⇒ 纠偏追不上。**为什么纯诊断不盲修**: 候选写入者至少三个(V46 attachmentBounds 测量链 / v37 probe 钳位链 / SwiftUI 布局 pass), 修法互相冲突 —— 放宽 V46 动表格渲染, 动 probe 钳位动 v37 那套 9 处泄漏防护, 抢 SwiftUI pass 是 v13/v34 翻车老路; 而 D4(TextContainerGuard 熔断 219 次, 358x2000 被熔 109 次)那条路是治 fillLayoutHole 11918ms 卡死的, 同样是历史 trade-off。先探针定位到**行**再动刀。探针两处构成**同帧差分**: v18 段末尾(v48 钉宽之后, 记 v18W) + v41 KVO 抢帧器(记 kvoW + 来源指纹 cvW/laidW/tcH)。同 tick 内读到不同值 ⇒ 中间有人写过; 跨 tick ⇒ SwiftUI pass 之间写的。段内零赋值零 invalidate*(与 v44/v46 同纪律), 指纹全部走既有只读属性与本闭包局部量(cvW 用 KVO 闭包内已有的局部量, laidW 用 v47 注入的 ios15LastLaidOutW), 不新增读取语句以免探针自己扰动布局。★本轮实踩三个**编译级**坑: (1) struct _V49W 声明在函数体内 → KVO 侧跨函数引用不到(局部类型跨函数不可见) ⇒ 已提到类型级; (2) 原想读 v46 的 attV46CachedWidth, 但那个 getter 声明在 **TableAttachment** 类里而探针在 SelectableMarkdownTextView 内 ⇒ 跨类访问, 编译失败 ⇒ 换成同类型的 laidW(问的都是「碎片按哪个宽排的」, 诊断力不减); (3) 指纹里的「排版宽」这项**连踩两次编译错误后整项删除**: 原写 `self.textContainer.bounds.width` ⇒ run#37139821021 `has no member 'bounds'`; 改写 `self.textContainer.lineFragmentWidth` ⇒ run#37141013946 `has no member 'lineFragmentWidth'`(它属于 TextKit2 的 NSTextLayoutManager)。两次都是**没查证就猜 API 名** —— 第一版我甚至在注释里论证它「比 bounds 更准」, 论证得越自信错得越彻底。**写注释不能代替查证。** 该语义已由 laidW(v47 注入的 ios15LastLaidOutW, v48 判据验证过)覆盖, 不再找替代。由此新增 scope_check_v49.py 的 E 层(API 存在性, 按接收者类型查成员) + verify_v49 对 bounds/lineFragmentWidth 的硬禁, 让编译器级错误改由判据在 CI 内拦。判据查不出编译问题, 这类坑只能靠 E 层(编译前)拦。0.5s 节流与 V44/V45/V46/V41 同周期。★登记必须排在 v48 之后(探针要读 v48 钉宽之后的值)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_source_unify_v50,
         MSG_V50_A)
    edit("Views/Chat/SelectableMarkdownView.swift", fix_slide_relayout_v50,
         MSG_V50_C)
    edit("Views/Chat/SelectableMarkdownView.swift", fix_view_frame_pin_v51,
         MSG_V51_A)
    edit("Views/Chat/SelectableMarkdownView.swift", fix_probe_unhook_v51,
         MSG_V51_C)
    edit("Agent/MessageList/MessageListLayout.swift", fix_flip_block, "v30-A: 双引擎测高反振荡 — 斩断 est=1176↔850 回路 (列表高度瞬间跳跃/剧烈抖动)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_measure_throttle, "v30-B: 流式测高节流至 ~8次/秒 — 主线程不再被全量 TextKit 排版占满 (卡顿/STALLED/停止迟钝)")
    edit("Views/Chat/AIChatView.swift", fix_inputbar_kick, "v30-C: 输入栏假死自愈 — STALLED 时就地重建 composer host (草稿保留)")
    # ★v56.7 必须排在 v30-C 之后: 洞2 改的是 SystemResourceMonitor.start(),
    #   而 v30-C 也碰 AIChatView.swift —— 登记在它前面会让后者的锚点被改过。
    #   (与 v52 必须排在 v32 之后是同一类顺序纪律, 那次是 RENDER_OLD 锚点命中 0 处炸掉。)
    edit("Views/Chat/ToolLiveSheet.swift", fix_thumb_tail_v567,
        "v56.7: 折叠态缩略图「取末尾 N 行」不再切整段输出 —— 治『终端框卡显示 / 滑动卡字』。"
        "★★这一版是 v56.6 的续: v56.6 治空白(几何), 本版治**每帧重复劳动**(性能), 两版症状不重叠。"
        "★仍然是**代码本身即证据**, 不靠猜: ToolLiveSheet.swift:3177 的 "
        "`text.components(separatedBy: \"\\n\").suffix(count).joined(...)` 会为**每一个**换行分配一个 "
        "String, 而四个调用方只要末尾 12 行(:2952/:3006)或 6 行(:3042/:3050)。"
        "shell 输出一屏几百行是常态, 而 body 每 2 秒至少求值 1 次(见洞2)、流式时每来一个 chunk 再 1 次 "
        "⇒ **每帧几百个 String 分配, 全是白搬**。这就是「字卡 / 卡显示」: 不是画得慢, 是每帧在无谓地搬字符串。"
        "修法: 结果恒等于「第 (总行数-count) 个换行之后的原文本」, 所以只数一次换行、定位一次、原样切片, "
        "**零中间 String 分配**。★判据带**等价性自证**: 拿 11 组输入(含末尾空行/行数不足/count<=0/全空行/非 ASCII)"
        "把新旧实现都跑一遍比对字节 —— 这一层已经真的抓到过新实现自己的 bug(全空行时少切一行), 纯靠肉眼看不出来。"
        "★范围失控也钉住: ToolLiveSheet 里 components(separatedBy:) 应**恰好剩 1 处**"
        "(chunkedLines :2352, 它本来就要全部行, **不动**)。★本版在**非 Markdown 路径**上的第二次改动")
    edit("Views/Chat/AIChatView.swift", fix_monitor_idem_v567,
        "v56.7 洞2: SystemResourceMonitor.start() 补幂等 guard —— 治『滑动像掉帧』。★★同样是代码即证据: "
        "AIChatView.swift:97 的 `timer = Timer.scheduledTimer(...)` **直接覆盖**旧 timer 而**没有 invalidate** "
        "—— 旧 timer 仍在 CommonModes 里每 2 秒跑一次, 并往主线程塞 DispatchQueue.main.async。"
        "调用点两处(ToolLiveSheet :2933 onAppear + :2937 onChange(of: isLive)), 而缩略图在滚动里反复 "
        "appear/disappear ⇒ start 次数可以远大于 stop ⇒ **泄漏 timer 累积**; 每个泄漏 timer 的 @Published "
        "又让整棵 ToolPreviewThumbnail 重算 ⇒ **与洞1 相乘**。这是「滑动时更卡」的直接解释: 滑一次多几个泄漏 timer。"
        "修法: start() 变幂等(已有 timer 直接返回), stop() 语义**一字未改** —— 纯粹「别重复起同一个表」, 不改任何读数。"
        "★登记排在 v30-C 之后(两者都碰 AIChatView.swift)")
    # ★★ v56.8 —— 第四次「对象选错」的纠正版 ★★
    # 用户 2026-10-04 23:56 给的截图(绿色 terminal 图标 + 标题 + 等宽耗时)
    # 直接指出对象是 ToolCapsuleView, 不是折叠态缩略图, 也不是全屏 sheet。
    # ★AssistantBlockView.swift **零历史注入标记** —— v41~v53 的整条补高链
    #   (V41-KVOPRE / V44-TEXTFRAME / V45-TVHFIX / V53 debt) 全挂在
    #   SelectableMarkdownView.swift 上, 只管 Markdown 文本视图。
    #   之前一路在「卡字」上打转(改了十几次), 治的一直是**另一条路**。
    edit("Views/Chat/AssistantBlockView.swift", fix_capsule_shimmer_v568,
        "v56.8: 治消息流里终端胶囊『卡一下才显示 / 卡一半一半显示』。"
        "★★对象由用户截图直接确定: 绿色 terminal 图标 + 标题 + 等宽耗时 = "
        "ToolCapsuleView(AssistantBlockView.swift:218, 由 :42 构造)。"
        "★这是本项目**第四次**装错对象(v46 装错类 / v565 scope 只数槽位 / "
        "v565收官 整个对象选错 / **v56.5-v56.7 三版都在改折叠态缩略图, 而用户指消息流**)。"
        "★该文件零历史注入标记 —— v41~v53 的补高链全在 SelectableMarkdownView, "
        "只管 Markdown 文本, 概念上就够不着这个卡片。"
        "【病根】ShimmerOverlay(同文件 :161) 的 `.offset(x: offsetX * geo.size.width)` "
        "—— **动画目标里含布局量**。offsetX 是 @State, SwiftUI 对 @State animation "
        "是「从当前呈现值 ease 到新目标」, 于是 body 每重算一次(流式 chunk / "
        "UICollectionView 滚动中 cell prepareForReuse → onAppear 反复触发), "
        "geo.size 变 → 目标变 → 正在跑的 repeatForever **被打断**, 亮条停在半路 "
        "或跳到另一半 ⇒ 用户看到的『卡一下才显示』『卡一半一半显示』。"
        "【修法】offset 目标改成 `offsetX * Self.travel`(static let 600pt 编译期常量), "
        "只依赖 offsetX 一个 @State ⇒ **动画与布局彻底解耦**, 亮条尺寸也不再跟着跳。"
        "★GeometryReader **保留**(亮条要铺满卡片宽度, 那是真实布局量), "
        "只是不再进入 offset 的目标 —— 不是把耦合搬到别处。"
        "★**不删动画**: 判据第4层专门钉住 withAnimation + repeatForever 必须在。"
        "删掉虽然不卡了, 但那是未经用户确认的行为改变(假修复)。")

    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_stabilize_v32, "v32: 渲染宽+测高宽统一 per-cell contentW(视图宽-内边距) — 消除测宽分歧与溢出裁字")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_realw2_v33, "v33: v28 遗留 _realW2 硬编码 cvW-32 改为 contentW — 修边框裁字/卡字/终端框卡内容")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_sync_v34, "v34: 渲染宽回归 superview 基准(过渡态免疫) + 渲染/测高共享 ios15LastRenderContentW — 修整体缩小/不贴边/闪屏(log10-03: tcW 390×27/326×25 交替, v33 公式过渡态双重扣减)")
    edit_glob("**/iOS15Compat.swift", fix_hosting_fullwidth_v35, "v35: hosting 视图/内容改回全屏宽(不再 -32) — 根治整体缩小/气泡不贴边/终端框折叠(v22/v24 把整个 cell 硬钉 358, 而 cell 应全宽 390)")
    edit_glob("**/iOS15Compat.swift", fix_hosting_track_parent_v36, "v36: hosting 视图宽从写死屏宽改为与父等宽 — 修'气泡差一点贴边'(UIScreen 常量 != collectionView 实测宽)")
    # ★v52 必须排在 v32 之后。**踩坑记录**: 我第一版把 v52 插在 v51-C 之后
    # (按版本号直觉), 结果 v32 的 `RENDER_OLD` 锚点
    # `let _svW = superview?.bounds.width ?? 0` 命中 0 处直接炸。
    # 原因: 注册顺序**不等于版本号顺序** —— v32 排在 main() 末尾(8095),
    # 比 v47~v51 都晚。而 v52-B 要替换的正是 v32/v34 反复改写的**那同一行**。
    # ⇒ 纪律: 锚点顺序按 **main() 里的实际行号**判, 不按版本号大小猜。
    # 验证过 v51 跑完之后产物里 `let _svW`(8117) 与 `var _realW`(8125) 都在,
    # 两处形态与 v52 的锚点一致。
    edit("Views/Chat/SelectableMarkdownView.swift", fix_width_sane_gate_v52,
         MSG_V52_AB)
    edit("Views/Chat/SelectableMarkdownView.swift", fix_debtguard_snapshot_v52,
         MSG_V52_E)
    # ---- v53: 治 cell 高度欠账永久凝固(C-2) + 记忆位死锁(C-1) + 首段专项 ----
    # ★必须排在 v52 之后, 而且** infra 的注入要排在 markdown view 之前**:
    #   v53-C2 的 markdown 侧要 `as? SelfSizingCell` 调 `v53NotePendingDebt`,
    #   而那个方法由 infra 侧的注入定义。顺序反了的话 markdown 侧会引用
    #   一个还不存在的 API —— 而 `edit()` 是**逐个文件**落盘的,
    #   中途失败会留下半成品树。
    # ⇒ 纪律: **跨文件的新增 API, 定义方必须先注入**;
    #   本地单文件判据全绿也证明不了这一点(它们只看文本, 不做类型检查),
    #   真正的把关在 CI 的 xcodebuild。
    edit("Agent/MessageList/MessageListInfrastructure.swift",
         fix_shortcircuit_probe_v53, MSG_V53_P)
    edit("Views/Chat/SelectableMarkdownView.swift", fix_memgate_deadlock_v53,
         MSG_V53_C1)
    edit("Views/Chat/SelectableMarkdownView.swift", fix_debtgate_verifiable_v53,
         MSG_V53_C2)
    edit("Views/Chat/SelectableMarkdownView.swift", fix_first_para_settle_v53,
         MSG_V53_FIRST)

    # ---- v54: 三处修法 (装机日志 minis-2026-10-04 5.log 实证) ----
    edit("Views/Chat/SelectableMarkdownView.swift", fix_v54_c1_gate,
         "v54-C1: 闸门承认贴边净宽, 破 C-1 记忆位死锁(memHit 136/136 全 0)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_v54_b_debt_report,
         "v54-B: SKIPPED 分支也上报欠账, 破 dedup 短路死锁(dedup=2307/live=0)")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_v54_c_probe_roundtrip,
         "v54-C: 消哨兵高度每帧往返(setSize 358x2000 × 314 跨 251 tick = 掉帧)")
    # ★v55 三个补丁必须排在 v54 之后: v55-C 的锚点 `_v54needUnbound2`
    #   是 **v54-C 注入的那一行**, CI 从上游源码起注入时, v54-C 还没跑
    #   ⇒ 锚点不存在 ⇒ run#132 `RuntimeError: v55-C 锚点缺失`。
    # ★本地测不出来: 本地是从 v54 产物出发(已含 v54-C), 而 CI 从上游出发。
    #   ⇒ 纪律 45: **补丁的注册顺序必须在 CI 的注入顺序下验证**, 不能只
    #     在「上一版产物」上验。
    edit("Views/Chat/SelectableMarkdownView.swift", fix_v55_a_probe,
         "v55-A: 宽高分源纯诊断(只打一行不写几何) —— v54 的 picked 打在回落**之后**恒为 358, 而闸门实读 371.7, 11/11 帧证实")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_v55_b_edgetouch,
         "v55-B: _edgeTouch 认出贴边净宽 —— 治 edge=0 导致 inset 16/16 没设上、cell 只给 26.7、末行裁 22.3(卡一半), 补高 103 次被改回")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_v55_c_sentinel_gate,
         "v55-C: 哨兵判据改用 textContainer.size.height —— 治 v54 判据自我循环(setSize 524次/415tick 比 v53 的 314/251 更差)")
    # ---- v56: v55.2 装机实测 setSize 777 次(v54=524) 不降反升, 判定失败 ----
    edit("Views/Chat/SelectableMarkdownView.swift", fix_v56_sentinel_probe,
         "v56: 断高度拉锯(核心:KVO 补高↔SwiftUI写回 每帧双写, 装机 fixed 62次里 debt 156.7 出现 35次一字不差; svW 62/62=358 宽度已对) "
         "+ a1/a3/a4/a5 四处哨兵判据换口径 + _edgeTouch 认 origin.x≈16 贴边态。"
         "★同时纠正 v53-v55 的归因错误: setSize 358x2000 ×777 是 guard 里 return 掉的短路(1/16采样, 真实 10912次), "
         "且集中在 08:27-08:30 启动期, 用户滑动期(18:40)为 0 条 —— 不是掉帧元凶")


    # ★★ v56.9 —— 装机日志的决定性读数直接指向的一处 ★★
    # v56.8 装机日志 minis-2026-10-05.log(7951 行)里:
    #   [V45-TVHFIX] 101 条, debt **全部 0.0**  (补高链自称已补好)
    #   [V56-KVO]    95 条, **全部 skipSame**, **零条 fixed/写入**
    # 而 95 条里 13 条 svH < needH —— 几何确实欠着却被抑制分支跳过。
    # 用户截图: 「定时任务」那行**只剩上半**, 且「检查环境配置」胶囊压上来。
    edit("Views/Chat/SelectableMarkdownView.swift", fix_kvo_debt_v569,
        "v56.9: 治『那一行只剩上半 / 显示不完全』—— KVO 同值抑制把欠账帧永久跳过。"
        "★★★ 根因来自**装机日志**, 不是推断 ★★★"
        "【日志读数】minis-2026-10-05.log: V56-KVO 95 条**全是 skipSame**零条 fixed; "
        "其中 13 条 svH<needH(26.7/49、407/832.3、959.7/1340.3 …)。"
        "而 V45-TVHFIX 的 debt 全是 0.0 —— 补高链自己以为补好了。"
        "【真凶】v56.1 引入的同值抑制(v56 原 docstring 明写「不同值的写入一律放行, "
        "正确修正绝不被连坐」—— **这句话是错的**): 抑制键是 (目标高度, 0.12s 窗), "
        "**完全不看当前几何**。于是: 上一 pass 写过 needH → 0.12s 内被 SwiftUI 写回矮值 → "
        "「目标高度与上次相同」+「在窗内」⇒ 判 dup ⇒ **只改局部副本 f, 不写 obj.frame** → "
        "几何没变 ⇒ **KVO 不再触发** ⇒ 欠账**永久凝固** ⇒ 那一行就一直只剩上半。"
        "★这是 v39/v40 判过『补齐代码一次都没执行过』的同一现象, 但根因反过来了: "
        "  v39/v40 结论是「代码没跑」; 本版查明是「跑了, 但被自己写的抑制挡掉」。"
        "【修法】抑制条件从「值是否重复」改为「值是否重复 **且** 几何已达标」: "
        "  `let _v56noDebt = f.size.height + 0.5 >= _v42Need` 然后 "
        "  `if _v56dup && _v56noDebt`。欠账时写入让几何真的变化 ⇒ 不是零变化 ⇒ 必须写。"
        "★抑制本意**保留**(省掉同 tick 内几何零变化的同步 layout 是真优化), "
        "  只改条件不删分支 —— 判据第4层专门钉住 skipped 计数不许消失。")
    # ★★ v57.0 —— 装机日志 + **录屏逐帧**交叉定罪的一版 ★★
    # 录屏(224x480, 128s, 抽 1924 帧逐帧看 + 帧差定位突变簇):
    #   每行右端被**同一条固定竖直线**切断, 典型「跑 PythonShe」后本该是「ll、处理数据」,
    #   下一行从断点续排。该切线在**静止帧与滑动帧位置完全相同**
    #   => 是**稳定裁切**, 不是滑动瞬时故障。
    #   另发现 4 个突变簇, 帧 1280(空) -> 1281(loading 圈) -> 1282(回来),
    #   证实滑动中触发**同步重排版**, 文字被清空重画 = 「滑动字消失」的直接来源。
    #
    # 日志(minis-2026-10-05 2.log, 5575 行)给机制, 三组数字完全同集合:
    #   V50-LAIDW  regrabbed=1  75 帧   <- 纠正机制**已触发**
    #   V44-TEXTFRAME tvW=390.0 75 帧   <- 但容器**仍是 390**
    #   13 个健康帧两者都干净(laidW=358/tvW=358/regrabbed=0)
    #   V52-GATE picked=358 / V50-PINW pinnedW=358 / V51-FRAMEPIN fvW=tcW=svW=358
    #     => 帧宽三处一致全对, 只有 textContainer 被推回全屏宽
    #   V44 的 needH-usedH: tcW=358 时 8.0~8.3(内边距正常) / tcW=390 时 30.6/52.8/53.0
    #
    # ★**本项目第五次「已识别但没修掉」** ★
    #   v47/v48/v50 **已经**识别出「按 390 排、按 358 算」这件事
    #   (V48 注释原话: "log17 里 tcW 与 gap 完全同构、零例外"),
    #   也**已经**写了纠正代码(8645/8688 两处 textContainer.size.width = _realW2),
    #   判据也**已经**算对了(regrabbed=1 说明它认为需要重排)。
    #   ★但 8607 那处判据是**单向**的: `if textContainer.size.width > _realW + 1`
    #   只在容器偏大时改。日志证明它触发过 75 次, 却仍留下 390。
    #   => 病不在「有没有写纠正」, 在**判据只覆盖半个方向** +
    #     「写的位置在 pass 末尾, 而 SwiftUI 每个 pass 都会推回来」。
    # ★★ v57.1 —— v57.0 装机后症状一字未改, 判据全绿, 第三次定位 ★★
    # 装机日志 minis-2026-10-05.log(647KB) 逐毫秒对齐, len=297 那一 tick:
    #   .543 V41-KVOPRE     sv=(16.0,79.7,358.0,297.7)
    #   .544 V43-WIDTH      dirtyW=390.0 netW=358.0 dh=22.7
    #   .545 V42-MISS       selfMeasured needH=409.7 tcW=358.0  <- 测高用 358(对)
    #   .545 V41-KVOHEIGHT  fixed svH=297.7 -> needH=409.7 debt=112.0
    #   .545 [V45]          v18W=358 kvoW=390 laidW=-1 **usedH=258.7 needH=409.7**
    #   .545 V44-TEXTFRAME  tvW=390.0 svW=358.0 **tcW=390.0**
    #   .546 V570-KVOCW     **dirty=1**   <- v57.0 纠偏到这里才跑
    #   .546 V50-PINW       tcW=358.0     <- 纠偏成功, 但排版已经发生
    #   .547 V50-LAIDW      laidW=358.0 regrabbed=1
    # ⇒ usedH=258.7 needH=409.7 差 **151pt(≈6 行)**, 那 151pt 正是
    #   **落屏用的按 390 排的行碎片**。v57.0 把它纠回来了, 但纠正在排版**之后**。
    # ★v57.0 的顺序判据「纠偏行号 < 早退行号」**真的通过了** —— 它只是**太弱**:
    #   早退本身就在一帧的中段, 前面还有六条语句。
    # ★两条同集合读数是 v57.0 唯一被证实的部分:
    #   dirty=1 41 帧 <-> tcW=390 41 帧(完全同集合)
    #   dirty=0 12 帧 <-> tcW=358 12 帧(完全同集合)
    #   ⇒ 判据本身对、写入也执行了, 唯一问题是**晚了**。
    # ⇒ v57.1: 整块上移到 `guard cvW > 1` 之后、闭包第一条业务语句之前。
    edit("Views/Chat/SelectableMarkdownView.swift", fix_kvo_container_v570,
        "v57.1: v57.0 纠偏**位置**错了 —— 排在 V43/V42MISS/V44 之后, "
        "排版已按脏宽发生一次。装机日志逐毫秒对齐(len=297): "
        ".545 V45 usedH=258.7 needH=409.7 差 151pt(≈6 行)=落屏用的按 390 排的行碎片; "
        ".546 V570-KVOCW dirty=1 <- 纠偏才跑; .546 V50-PINW tcW=358 <- 已太晚。"
        "★v57.0 判据『纠偏 < 早退』**通过了但太弱**(早退在帧中段, 前面六条语句)。"
        "【旁证: 唯一被证实的部分】dirty=1(41帧) <-> tcW=390(41帧) 完全同集合, "
        "dirty=0(12) <-> tcW=358(12) 也完全同集合 ⇒ 判据对、写入执行了, 只是晚。"
        "【修法】整块上移到 KVO 闭包最前(guard cvW 之后第一条业务语句之前), "
        "让本帧所有测高/排版/诊断都只看一个宽度。判据用 abs(双向)。"
        "**只写 textContainer.size.width**, 不碰 frame/bounds/高度 "
        "⇒ 不推翻 v41/v45 补高与 v51 钉宽。"
        "【判据八层, 第8层是新的】前七层同 v57.0, 第8层: 纠偏必须早于**四处** "
        "_v42Len 声明(闭包第一条业务语句)/V43 读脏宽/V42-MISS 测高/V44 诊断。"
        "★锚点必须用 _v42Len 不能只用 V43: 锚 V43 时 reverse S10 漏过"
        "(插在 _v42TCW 之后、V43 之前只早 2 行, 但那个位置语义上仍然错)。"
        "【反向 12 条, 新增 S10/S11/S12】S10 = **v57.0 的真实位置**, "
        "v57.0 判据对它完全放行, 是本版核心回归。"
        "————————————————————————————"
        "［以下为 v57.0 原记录, 保留以便对照被推翻的诊断］"
        "v57.0: 治「每行右端被竖直切断」+「滑动时文字整块消失」。"
        "★★★ 根因 = 装机日志时间戳 + 录屏逐帧交叉验证, 不是推断 ★★★"
        "【录屏 128s 抽 1924 帧】每行右端被**同一条固定竖直线**切断"
        "(「跑 PythonShe」后本该是「ll、处理数据」, 下一行从断点续排); "
        "静止帧与滑动帧切点位置**完全相同** => 稳定裁切, 非滑动瞬时故障。"
        "另见 4 个突变簇: 帧1280 空白 -> 1281「Minis」+loading 圈 -> 1282 回来 "
        "=> 滑动中触发同步重排版, 文字被清空重画 = 「滑动字消失」的直接来源。"
        "【★ 第五次「已识别但没修掉」★】v47/v48/v50 早已识别「按 390 排、按 358 算」"
        "(V48 注释原话「tcW 与 gap 完全同构、零例外」), 也早已写了纠正代码"
        "(三处 textContainer.size.width 写入), 判据也算对了(regrabbed=1)。"
        "★本版最初也打算只把单向判据 `>` 改成 `abs(...)` 双向化 —— "
        "**被自己的行为对比当场推翻**: tcW=390 时旧判据本来就成立, 双向后行为"
        "**一字不差**; 只新增了对 tcW=326 的覆盖。它压根没解释 390 为什么留下。"
        "【★ 真正的根因(A: 纠偏成功但晚一拍)】装机日志时间戳逐条对齐:"
        "    01:19:10.524  V44-TEXTFRAME tcW=390.0   <- KVO 闭包内读到脏宽"
        "    01:19:10.526  V50-PINW       tcW=358.0   <- layoutSubviews 内已纠回"
        "    01:19:10.530  V50-LAIDW      laidW=358.0 regrabbed=1"
        "同一帧 KVO 读 390、layout 读 358 ⇒ 「触发与失败同集合」只说明 KVO 那拍"
        "看到脏宽, **推不出 layout 纠正无效**。"
        "【★ 真正的根因(B: 早退判据看不见容器脏宽)】KVO 闭包:"
        "    let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt"
        "    if !polluted { ...; return }"
        "三项**全都只看 superview.frame**, 而 SwiftUI 推脏的是 textContainer。"
        "实测 V41-KVOPRE sv=(16.0,188.7,358.0,994.3) cvW=390.0 ⇒ superview 宽 358"
        "完全正常 ⇒ polluted 恒 false ⇒ **每帧早退** ⇒ 脏容器宽从 KVO 路径永远没人纠。"
        "旁证: V41-KVOFIXH 0 条、LASTSANE 0 条 ⇒ 修正分支一次都没进过。"
        "【修法】把容器宽纳入 polluted, 目标用净宽 max(200, cvW-32)(与 layoutSubviews "
        "的 _realW2 同源同值), 纠偏写在**早退之前**: KVO 是本帧最早拿回控制权的点, "
        "纠完 layoutSubviews 的 v47/v48/v50 只看到已干净的宽(幂等, 零额外排版)。"
        "判据双向(abs>1) 顺带覆盖偏小方向。**只写 textContainer.size.width, "
        "不碰 frame/bounds/高度** ⇒ 不推翻 v41 补高/v45 补高/v51 钉宽, 也不抢宽。"
        "【判据】verify_kvo_container_v570 六层: 标记/polluted 整段并入/纠偏在早退之前/"
        "双向判据/纯诊断是 dirty 标记式/旧 BIDIR 已移除。"
        "【反向】reverse_v570.py 8 条 sabotage, 含「把纠偏挪到早退之后」"
        "「polluted 不并入 dirty」「退回单向 >」「摘掉诊断标记」「复活旧 BIDIR」。")

    edit("Views/Chat/SelectableMarkdownView.swift", fix_kvo_reflow_v58,
        "v58: 纠偏后强制重排 —— v57.1 的**位置**已对, 缺的是「写完要排」。"
        "★★★ 本项目第六次「已识别但没修掉」, 但这次是**不同的环节** ★★★"
        "【装机日志 minis-2026-10-05 3.log, 04:32:41, len=288 逐毫秒对齐】"
        "  41.372 V51-FRAMEPIN  fvW=358.0 tcW=358.0 svW=358.0  <- layoutSubviews 那趟干净"
        "  41.595 V570-KVOCW    dirty=1 netW=358.0               <- v57.1 纠偏**确实执行了**"
        "  41.598 V49-WWRITER   kvoW=390.0 laidW=-1.0            <- 同一 tick 读回**还是 390**"
        "  41.599 V44-TEXTFRAME tvW=390.0 svW=358.0 tcW=390.0   <- 落屏那版就是 390"
        "  41.599 V41-KVOHEIGHT usedH=258.7 needH=387.0        <- 欠 128.3pt(≈6 行)"
        "⇒ v57.1 八层判据全绿、dirty 每帧都在改宽度, 但**症状一字未改**。"
        "【★ 真正的根因: 只写宽度, 不重排行碎片 ★】"
        "`textContainer.size.width = ` **只改容器, 不动既有行碎片** —— 这是 v48 "
        "自己注释里已写明的事实(原文: 'textContainer.size.width = 只改容器不重排"
        "既有碎片')。v47/v48/v50 各自紧邻一行 layoutManager.invalidateLayout(...) "
        "才真正生效; ★唯独 v57.1 的纠偏块里**没有那一行** ★ ⇒ 容器宽写成 358 ✓ "
        "但行碎片仍停在 390 那版, 下一趟布局读回又是 390。"
        "★这是三十余版反复失败的共同根因: 每版都在「写宽度」, 却没人保证"
        "「写完的宽度被排版采纳」。★"
        "【★ 独立第二证据: v47/v48/v50 的重排全是死代码 ★】"
        "那三代的 invalidateLayout 被 `if _ios15WRegrabbed` 包着, 而它依赖 "
        "`ios15LastLaidOutW` —— 装机日志 V49-WWRITER 里 laidW **恒为 -1.0** "
        "(V50-LAIDW 只在 layoutSubviews 那趟打成 358, KVO 这趟永远读到残留 -1) "
        "⇒ 那个判据在真机上从未成立 ⇒ 三代重排都没执行过。v58 不依赖任何记忆变量。"
        "【修法】在 v57.1 的 `if _v570Dirty {` 块内、宽度写入之后**紧跟一行** "
        "layoutManager.invalidateLayout(forCharacterRange:actualCharacterRange:) "
        "—— 与 v28 段(第 8835 行)已验证合法的签名**逐字一致**, 不引入编译器未验证过 "
        "的 API(纪律4)。整块被 if 包着 ⇒ 稳态 tcW 已是 358 时 abs<=1 判据恒 false "
        "⇒ **零写入零重排**, 不会加重掉帧; 只在 SwiftUI 真的把宽度推回 390 时动手。"
        "**只重排行碎片, 不碰 frame/bounds/height/origin** ⇒ 不推翻 "
        "v41/v45 补高与 v51 钉宽。"
        "【判据四层】标记在位/invalidateLayout 必须在 if _v570Dirty 块内"
        "(写在外=每帧重排掉帧, 写在块外=永不执行即 v57.1 的病)/签名须与 v28 段一致/"
        "纯诊断存在且用 reflow 标记(不靠回读宽度, 那永远全绿骗人)。"
        "另加白名单: v58 段内只许 textContainer.size.width 写入。")

    # ★顺序要点: v55-B 仍先注册(它是 v56-B 的锚点载体), v56-B 在其产物上改写,
    #   所以 v56 不能删掉 v55-B 的注册, 只在 v56 里把它放行。

    # ★v60 取代 v59★: v59 的断源方案(false+兜底320)整体退场 —— 用户截图
    # 实证 zhaoxiufei/OpenMinis 的宽跟随保留方案在 iOS 15.1.1/15.4.1 真机
    # 上无卡字, 而 v31~v59 的容器层对抗 30 余版从未被真机验证成功。
    # v59 的 fix_md_notrack_v59 函数保留在文件里仅作历史记录, 不再注册。
    edit("Views/Chat/SelectableMarkdownView.swift", fix_zhao_md_v60,
        "v60: 采用 zhaoxiufei/OpenMinis 3ccdff6 已验证方案(真机 iOS 15.1.1/"
        "15.4.1 无卡字)取代 v59 断源版。"
        "【八处注入】init sane 初值 / sizeThatFits+intrinsicContentSize 重写"
        "(sane 宽推导链+漂移重置+宽退出协商) / CodeBlockAttachment 三处"
        "(attachmentBounds 三级 fallback+makeView min-50+scrollWidth min-50) / "
        "makeUIView 初值 / updateUIView 垃圾宽兜底。"
        "【哲学】不再与宽跟随对抗: 保留上游 true, 通过四层重写保证 frame 恒 "
        "sane, 跟随派生自然得到净宽 —— v31~v59 的「写 358 被 frame(390) 顶回」"
        "天花板从机制上消失。"
        "【共存】v57.0 KVO 纠偏/v58 重排保留, 在 frame sane 后退化为观察者; "
        "v21 intrinsic 钳宽被本版替换(旧版先按 1e5 排再钳=白排+理想宽泄漏)。"
        "【判据七层+hosting 三层】见 verify_zhao_md_v60/verify_zhao_compat_v60; "
        "反向 10 条见 ios15_verify/reverse_v60.py。")
    edit("iOS15Compat.swift", fix_zhao_compat_v60,
        "v60: hosting 层 sizeThatFits 重写(zhaoxiufei 3ccdff6 同款) —— "
        "父视图走 sizeThatFits 路径时按真实宽向 SwiftUI 要高度+ceil 对齐; "
        "已有的两个 systemLayoutSizeFitting 重写(ios15FittingSize)不动。")
    edit("iOS15Compat.swift", fix_host_stability_v61,
        "v61: 治「打字/滑动整屏跳动 + 流式内容跳出」(2026-10-05 5.log + 录屏"
        "帧差实证)。根因 = apply() 每次流式 tick 全删重建 UIHostingController"
        " ⇒ 测量从零起步 ⇒ 同一消息高度 333↔490 反复漂移(差 157pt)。"
        "【两件套】V61-REUSE apply 就地更新快速路径(zhaoxiufei 同款: 同类 "
        "config 只刷 rootView, 流式 tick 不再重建); V61-MONO 高度单调锁"
        "(同宽回缩超 8pt 容差沿用历史最高, 挡测量抖动上屏; 宽变/重建路径重置"
        "防复用串扰)。判据 verify_host_stability_v61 五层 + 反向 reverse_v61。")
    edit("Agent/MessageList/MessageListInfrastructure.swift", fix_surplus_mirror_v62_infra,
        "v62①: V62-SURPLUS 盈余镜像(SelfSizingCell 侧) —— 治「工具卡片间"
        "~250pt 空白终态留存」(v61 装机 2026-10-05.log 实证)。根因: v53 欠账"
        "体系只有「太矮」半边, 内容收缩(工具收起 live terminal, 337→47pt)时"
        "E 判据上报 -290 被 `debt <= 1` 吞掉, A/B/C 三短路继续返回旧高。"
        "本条: 字段三件套 + note 函数盈余分支(-40 阈值两拍) + 欠账互斥 + "
        "三守卫扩 `!v53SurplusIsRipe`。")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_surplus_mirror_v62_md,
        "v62②: V62-SURPLUS settle 入口(v53-FIRST guard 处) —— 盈余同样触发"
        "真实测量 + invalidate(收缩的驱动源), 且盈余时上报负 debt 喂镜像计数。"
        "判据 verify_surplus_mirror_v62 五层 + 反向 reverse_v62。")
    edit("iOS15Compat.swift", fix_intrinsic_gate_v63_compat,
        "v63①: V63-INTSIZE 恢复 intrinsicContentSize 高度上报 + V63-UPDATE "
        "REUSE 后 invalidateIntrinsicContentSize + V63-CFG config 判等。★根因: "
        "v60 把 intrinsicContentSize 改成 height=noIntrinsicMetric(退出协商), "
        "而 iOS 15 的 UIHostingController **没有 sizingOptions**(iOS 16 才有) ⇒ "
        "intrinsic+invalidate 是它唯一的尺寸更新信号源。切掉它 UIKit 就聋了, "
        "cell 三短路又因 v53/v62 循环依赖永不放开 ⇒ 实测 live=0/debt=0.0/"
        "cached=true×44, 高度锁死旧值(798→903→1057→1205→1336→1518)。"
        "外部依据: Mozilla Firefox iOS HostingTableViewCell、vbat.dev、"
        "SO 77027194(试过 setNeedsLayout/layoutIfNeeded, 只有 invalidate 有效)"
        "、Apple FB9641883。宽仍保持 noIntrinsicMetric(宽污染是另一回事, "
        "由 v60 的 sane 推导链治)。★iOS15Compat.swift 由第二阶段 "
        "ios15_port_v2.py 生成, 本阶段 edit 到它 —— 单跑本脚本会静默 SKIP。")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_intrinsic_size_v63_md,
        "v63②: V63-INTSIZE SelectableMarkdownTextView.intrinsicContentSize "
        "恢复高度上报(宽仍 noIntrinsicMetric)。★v60 把高度也关了, 而本项目"
        "以 UITextView 为承载 —— UITextView 恰恰以 intrinsicContentSize "
        "参与 Auto Layout。宽污染(100032)是 v60 的病, 但关高度是误伤: "
        "iOS 15 上这是尺寸协商的唯一通道。判据 verify_intrinsic_gate_v63 六层。")
    edit("Views/Chat/SelectableMarkdownView.swift", fix_uncouple_v63_md,
        "v63③: V63-UNCYCLE 打破 v53/v62「两拍」循环依赖 —— settle 入口 guard "
        "新增 _v63drift 实测差值直放行(不依赖 debt 熟)。★为什么必须: 实测 "
        "debt 恒 0.0、live 恒 0, 计数永远停在 1 ⇒ 第二拍从未到来 ⇒ 真实测量"
        "从未执行。判据 verify_uncouple_v63 + 反向 reverse_v63。")

    # ---- v64: 切断「自我播种」—— 单向累加的真正病因 ----
    edit("Agent/MessageList/MessageListInfrastructure.swift",
        fix_deseed_v64_infra,
        "v64: V64-DESEED + V64-CONVERGE, 全部落在 SelfSizingCell."
        "preferredLayoutAttributesFitting 一个函数里。★装机铁证: idx=9 六拍 "
        "delta 恒 +144~+205(≈170pt/拍), 11:07:52.403→53.981 全在 1.58s 内, "
        "est_{n+1} 严格等于 pref_n ⇒ H_{n+1}=H_n+170 发散。"
        "★根因: :531 声明 targetSize 用 layoutFittingCompressedSize(压缩语义=从"
        "内容重算), :561 却用 super 刚返回的、已膨胀的 attrs.size.height 当"
        "测量初值**自己喂自己**。iOS16+ SwiftUI 遵守压缩优先级无害; iOS15 不"
        "遵守, 播种值胜出→写回缓存→下一轮 est 更大→再播种。"
        "★为什么 v63 让病显形而非 v63 改坏: v60 把 intrinsicContentSize 高度也"
        "清成 noIntrinsicMetric, 播种值恒为死的 0, 环转不起来但高度永远锁死"
        "(v53/v62 看到的\"稳定\"); v63 恢复高度上报是必须保留的正确修复"
        "(iOS15 感知内容尺寸变化的唯一通道), 恢复后播种值变\"活\", 三十余版的"
        "底层 bug 才显形。★本条只断反馈, 不动 v63 的高度上报。"
        "判据 verify_deseed_v64 四层 + 反向 reverse_v64。")

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
