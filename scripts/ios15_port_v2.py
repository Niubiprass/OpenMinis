#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenMinis -> iOS 15 移植（第二阶段）。

第一阶段（ios15_port.py）已处理 NavigationStack / presentationDetents。
第二阶段针对 Xcode 编译暴露出的 1554 个真实错误，按杠杆从大到小处理：

  1. AppLocalized 参数类型 String.LocalizationValue(iOS16) -> String    [约 1000+]
  2. Agent/Intents 目录整目录标注 @available(iOS 16.0, *)              [约 260]
  3. 删除 iOS16 专属的纯装饰性 SwiftUI 修饰符                           [约 30]
  4. Task.sleep(for: .milliseconds(x)) -> Task.sleep(nanoseconds:)      [约 14]
  5. TextField(..., axis:) / usingTextLayoutManager / String(localized:) [约 10]
  6. 生成 iOS15Compat.swift 兼容层并注入 Xcode 工程                      [约 120]

设计原则：
  - 全部幂等（重复执行不叠加改动）
  - 全部尽力而为（找不到目标就跳过并打印，绝不抛异常中断构建）
  - 只做文本级改写，不改动工程结构（除注入兼容层文件外）
"""
from __future__ import annotations

import os
import re
import sys

ROOT = "src/ios"
COMPAT_NAME = "iOS15Compat.swift"

# ---------------------------------------------------------------- 基础工具

def swift_files(base: str):
    """递归收集 base 下所有 .swift 文件（跳过隐藏目录）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if not d.startswith(".")]
        for fn in filenames:
            if fn.endswith(".swift"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def read(p: str) -> str:
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def write(p: str, s: str) -> None:
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def edit(path: str, fn) -> bool:
    """对单个文件应用 fn，返回是否发生了改动。"""
    try:
        old = read(path)
    except OSError:
        return False
    new = fn(old)
    if new != old:
        write(path, new)
        return True
    return False


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------- 1. AppLocalized 参数类型

APPL_PATH = os.path.join(ROOT, "Shared", "AppLocalization.swift")

NEW_APPL_BODY = '''/// Localized string that follows the in-app language override.
///
/// iOS 15 port note: the original signature took `String.LocalizationValue`
/// (iOS 16+) and forwarded to `String(localized:bundle:)` (also iOS 16+).
/// Both are unavailable on iOS 15, which produced 1000+ errors at every call
/// site. This version takes a plain `String` and resolves through
/// `NSLocalizedString`, which routes through
/// `Bundle.localizedString(forKey:value:table:)` -- exactly the seam the
/// language-override swizzle in MinisApp.swift already patches, so the in-app
/// language picker keeps working.
///
/// - Parameters:
///   - key: the localization key, i.e. the English source string.
///   - comment: translator context.
func AppLocalized(_ key: String, comment: StaticString? = nil) -> String {
    NSLocalizedString(key, bundle: AppBundle.current,
                      comment: comment.map { String(describing: $0) } ?? "")
}
'''


def fix_applocalized() -> None:
    """把 AppLocalized 的 iOS16 参数/实现换成 iOS15 可用的等价物。"""
    if not os.path.isfile(APPL_PATH):
        log("⚠️  未找到 %s，跳过 AppLocalized 改造" % APPL_PATH)
        return

    text = read(APPL_PATH)
    orig = text

    # 参数类型：String.LocalizationValue -> String
    text = text.replace("_ key: String.LocalizationValue", "_ key: String")

    # 实现：String(localized:...) -> NSLocalizedString(...)
    text = re.sub(
        r"String\(localized:\s*key,\s*bundle:\s*AppBundle\.current,\s*comment:\s*comment\)",
        'NSLocalizedString(key, bundle: AppBundle.current,\n'
        '                      comment: comment.map { String(describing: $0) } ?? "")',
        text,
    )

    # 删掉 LocalizedStringResource 重载（该类型 iOS16 才有）
    text = re.sub(
        r"\n/// `LocalizedStringResource` overload.*?\n"
        r"func AppLocalized\(_ resource: LocalizedStringResource\) -> String \{.*?\n\}\n",
        "\n",
        text,
        flags=re.S,
    )
    # 兜底：任何残留的 LocalizedStringResource 版本
    text = re.sub(
        r"\nfunc AppLocalized\(_ resource: LocalizedStringResource\)[^\n]*\n\{.*?\n\}\n",
        "\n",
        text,
        flags=re.S,
    )

    if "LocalizedStringResource" in text:
        # 还有别处引用，逐行清掉显式类型标注
        text = re.sub(r"\n[^\n]*\bLocalizedStringResource\b[^\n]*", "", text)

    if text != orig:
        write(APPL_PATH, text)
        log("✅ 已改造 AppLocalization.swift（参数 String.LocalizationValue -> String）")
    else:
        log("ℹ️  AppLocalization.swift 无需改动（或已是 iOS15 版本）")


# ------------------------------------------- 2. 全项目清除 LocalizedStringResource

def strip_localizedstringresource() -> None:
    """清掉其他文件里对 LocalizedStringResource 的显式类型标注。

    例外：`static var/let xxx: LocalizedStringResource` 是 AppIntent 等协议
    要求的属性（如 `static var title`），改类型会破坏协议一致性
    （v2 第一版在这里翻过车：AudioTogglePlaybackIntent 不再符合 AppIntent）。
    这类声明一律跳过，改由 annotate_appintent_files 用 @available 处理。
    """
    STATIC_DECL = re.compile(r"\bstatic\s+(?:var|let)\s+\w+\s*:\s*LocalizedStringResource")
    n = 0
    for path in swift_files(ROOT):
        if path == APPL_PATH:
            continue

        def _fn(text: str) -> str:
            if "LocalizedStringResource" not in text:
                return text
            out = []
            for ln in text.split("\n"):
                if STATIC_DECL.search(ln):
                    out.append(ln)  # 协议属性, 保持原类型
                    continue
                ln = ln.replace(": LocalizedStringResource?", ": String?")
                ln = ln.replace(": LocalizedStringResource", ": String")
                ln = ln.replace("-> LocalizedStringResource", "-> String")
                ln = ln.replace("<LocalizedStringResource>", "<String>")
                ln = ln.replace("[LocalizedStringResource]", "[String]")
                ln = ln.replace("as? LocalizedStringResource", "as? String")
                ln = ln.replace("as LocalizedStringResource", "as String")
                out.append(ln)
            return "\n".join(out)

        if edit(path, _fn):
            n += 1
    log("✅ 清理 LocalizedStringResource 类型标注：%d 个文件" % n)


# AppIntents 相关协议（出现在类型继承列表中即视为意图/实体类型）
INTENT_PROTO_RE = re.compile(
    r":\s*(?:LiveActivityIntent|AppIntent|AppShortcutsProvider|AppEntity|AppEnum|AppShortcut)\b"
)


def restore_intent_props() -> None:
    """恢复上一版脚本误改的协议属性（static var title: String -> LocalizedStringResource）。

    上一版把全项目 LocalizedStringResource 标注无差别替换成 String，导致
    AudioTogglePlaybackIntent 等意图类型不再符合 AppIntent 协议。
    这里只处理「文件中含 AppIntents 协议」的场景，且只恢复协议要求的属性名。
    """
    n = 0
    for path in swift_files(ROOT):
        try:
            text = read(path)
        except OSError:
            continue
        if not INTENT_PROTO_RE.search(text):
            continue
        orig = text
        text = re.sub(
            r"(static\s+(?:var|let)\s+title\s*:\s*)String(\s*=)",
            r"\1LocalizedStringResource\2", text)
        text = re.sub(
            r"(static\s+(?:var|let)\s+summary\s*:\s*)String(\s*=)",
            r"\1LocalizedStringResource\2", text)
        if text != orig:
            write(path, text)
            n += 1
    log("✅ 恢复 AppIntent 协议属性（title/summary）：%d 个文件" % n)


def annotate_file_top_decls(path: str, avail: str) -> bool:
    """给文件的顶层类型声明加 @available(avail, *)（幂等）。已标注则跳过。"""
    marker = "@available(iOS %s, *) // ios15-port" % avail
    text = read(path)
    if marker in text or "@available(iOS 16.0, *) // ios15-port" in text:
        return False
    lines = text.split("\n")
    out = []
    for ln in lines:
        m = DECL_RE.match(ln)
        if m and not ln.lstrip().startswith("//"):
            out.append(m.group("ind") + marker)
        out.append(ln)
    write(path, "\n".join(out))
    return True


def annotate_appintent_files() -> None:
    """Intents 目录之外的意图/实体类型也要隔离（如 Shared/AudioTogglePlaybackIntent）。

    - LiveActivityIntent 需要 iOS 17 -> 标 17.0
    - 其余 AppIntents API 从 iOS 16 开始 -> 标 16.0
    前提：引用这些类型的扩展 target 会由 fix_fileprovider_deployment.py
    抬高部署目标（AgentWidgetExtension -> 17.0），主 App 不引用它们。
    """
    n = 0
    for path in swift_files(ROOT):
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        if rel.startswith("Agent/Intents/"):
            continue  # annotate_intents 已按 16.0 处理
        try:
            text = read(path)
        except OSError:
            continue
        if not INTENT_PROTO_RE.search(text):
            continue
        avail = "17.0" if "LiveActivityIntent" in text else "16.0"
        if annotate_file_top_decls(path, avail):
            n += 1
    log("✅ Intents 目录外的意图类型标注 @available：%d 个文件" % n)


# ------------------------------------------------- 3. Intents 目录整体标注

INTENTS_DIR = os.path.join(ROOT, "Agent", "Intents")

DECL_RE = re.compile(
    r"^(?P<ind>[ \t]*)(?P<mods>(?:public |internal |fileprivate |private |open |final |indirect )*)"
    r"(?P<kind>struct|class|enum|actor|protocol|extension)\s+(?P<name>\w+)"
)


def annotate_intents() -> None:
    """给 Agent/Intents 下每个顶层声明加 @available(iOS 16.0, *)。

    AppIntents 框架在 iOS 15 上不存在对应 API，整块标注后编译器不再检查其
    内部实现；引用点集中在该目录内（AppShortcutsProvider 等），因此不会把
    错误扩散到主 App。
    """
    if not os.path.isdir(INTENTS_DIR):
        log("⚠️  未找到 %s，跳过 Intents 标注" % INTENTS_DIR)
        return

    n = 0
    for path in swift_files(INTENTS_DIR):
        if annotate_file_top_decls(path, "16.0"):
            n += 1
    log("✅ Intents 目录标注 @available(iOS 16.0, *)：%d 个文件" % n)


# ------------------------------------------- 4. 删除 iOS16 装饰性修饰符

# 纯单行参数式修饰符，按行删是安全的
DELETE_LINE_RES = [
    r"\.presentationDragIndicator\(",
    r"\.toolbarBackground\(",
    r"\.listRowSeparatorLeading\(",
    r"\.scrollIndicators\(",
    r"\.scrollDismissesKeyboard\(",
    r"\.scrollContentBackground\(",
    r"\.persistentSystemOverlays\(",
    r"\.navigationSplitViewColumnWidth\(",
    r"\.toolbar\([^\n]*for:\s*\.(?:navigationBar|bottomBar|tabBar)",
]

# 带尾随闭包的多行构造，必须整调用配平删除，绝不能按行删！
# .dropDestination(for: .text) { items, _ in
#     ...
# } isTargeted: { over in
#     ...
# }
CALL_DELETE_RES = [
    r"\.dropDestination\(",
    r"\.draggable\(",
]


def _match_delim(text: str, i: int):
    """i 指向 ( { [ 之一，返回配对闭括号之后的位置；自动跳过字符串字面量。"""
    pairs = {"(": ")", "{": "}", "[": "]"}
    stack = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
            i += 1
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif stack and c == stack[-1]:
            stack.pop()
            if not stack:
                return i + 1
        elif c in ")}]" and not stack:
            return None
        i += 1
    return None


def _expr_end(text: str, lp: int):
    """lp 指向调用的 "("，返回整个调用（含全部尾随闭包）结束位置。"""
    i = _match_delim(text, lp)
    if i is None:
        return None
    while True:
        # 形如  label: { ... }  的后续尾随闭包（如 isTargeted: { over in ... }）
        m = re.match(r"\s*\w+\s*:\s*\{", text[i:])
        if not m:
            m = re.match(r"\s*\{", text[i:])
        if not m:
            break
        e = _match_delim(text, i + m.end() - 1)
        if e is None:
            return None
        i = e
    return i


def delete_call_exprs() -> None:
    """整调用配平删除多行构造（dropDestination / draggable 等）。"""
    pats = [re.compile(p) for p in CALL_DELETE_RES]
    touched = 0
    for path in swift_files(ROOT):
        text = read(path)
        changed = False
        for pat in pats:
            guard = 0
            while guard < 200:
                guard += 1
                m = pat.search(text)
                if not m:
                    break
                lp = m.end() - 1  # 模式含 "("，m.end()-1 必指向它
                e = _expr_end(text, lp)
                if e is None:
                    log("⚠️  %s: 无法配平 %s 调用，跳过" % (path, pat.pattern))
                    break
                i = m.start()
                ls = text.rfind("\n", 0, i) + 1
                if text[ls:i].strip() == "":
                    i = ls
                    if e < len(text) and text[e] == "\n":
                        e += 1
                text = text[:i] + text[e:]
                changed = True
        if changed:
            write(path, text)
            touched += 1
    log("✅ 整体删除多行构造（dropDestination/draggable）：%d 个文件受影响" % touched)


# 孤儿形态："} isTargeted: {" 这类行 —— 上一版脚本按行删掉了
# .dropDestination( 开头行后残留在仓库里的半截闭包
ORPHAN_TRAILING_RE = re.compile(r"(?m)^([ \t]*)\}[ \t]*\w+:[ \t]*\{")


def repair_orphan_trailing_closures() -> None:
    """自愈：清理上一版「删头留身」造成的语法残骸。

    破坏形态（.dropDestination( 行已被删）：
        <第一闭包体若干行（缩进比孤儿行深）>
        } isTargeted: { over in        ← 孤儿行
            <isTargeted 体>
        }
    从孤儿行向上吞掉缩进更深的连续非空行，从孤儿行内的 "{"
    配平到它的结束 "}"，整段删除。幂等：清完即无匹配。
    """
    touched = 0
    for path in swift_files(ROOT):
        changed = False
        for _ in range(50):
            text = read(path)
            m = ORPHAN_TRAILING_RE.search(text)
            if not m:
                break
            lines = text.split("\n")
            orphan_idx = text[: m.start()].count("\n")
            indent_len = len(m.group(1))
            # 1) 向上吞掉缩进更深的连续非空行（第一闭包的残骸）
            start = orphan_idx
            k = orphan_idx - 1
            while k >= 0:
                ln = lines[k]
                if ln.strip() == "":
                    k -= 1
                    continue
                li = len(ln) - len(ln.lstrip())
                if li > indent_len:
                    start = k
                    k -= 1
                    continue
                break
            # 2) 从孤儿行内的 "{" 配平到结束 "}"
            brace = text.find("{", m.start())
            end_pos = _match_delim(text, brace) if brace >= 0 else None
            if end_pos is None:
                log("⚠️  %s: 孤儿闭包无法配平，跳过" % path)
                break
            end_idx = text[:end_pos].count("\n")
            del lines[start : end_idx + 1]
            new = "\n".join(lines)
            if new == text:
                break
            write(path, new)
            changed = True
        if changed:
            touched += 1
    if touched:
        log("🩹 已修复上一版删行残留的孤儿闭包：%d 个文件" % touched)


def delete_modifiers() -> None:
    """删除 iOS16 专属、纯视觉/交互增强的修饰符整行（iOS15 无对应 API）。"""
    pats = [re.compile(p) for p in DELETE_LINE_RES]
    total = 0
    touched = 0
    for path in swift_files(ROOT):
        def _fn(text: str) -> str:
            lines = text.split("\n")
            out = []
            for ln in lines:
                if any(p.search(ln) for p in pats):
                    continue
                out.append(ln)
            return "\n".join(out)

        before = read(path)
        after = _fn(before)
        if after != before:
            write(path, after)
            touched += 1
    log("✅ 删除 iOS16 装饰性修饰符：%d 个文件受影响" % touched)


# ------------------------------------------------------- 5. 零散 API 替换

def misc_fixes() -> None:
    """零散但确定可行的替换。"""
    touched = 0
    for path in swift_files(ROOT):
        def _fn(t: str) -> str:
            orig = t

            # Task.sleep(for: .milliseconds(n)) -> Task.sleep(nanoseconds:)
            t = re.sub(
                r"Task\.sleep\(for:\s*\.milliseconds\(([^()]*)\)\)",
                r"Task.sleep(nanoseconds: UInt64(\1) * 1_000_000)", t)
            t = re.sub(
                r"Task\.sleep\(for:\s*\.seconds\(([^()]*)\)\)",
                r"Task.sleep(nanoseconds: UInt64(\1) * 1_000_000_000)", t)
            t = re.sub(
                r"Task\.sleep\(for:\s*\.nanoseconds\(([^()]*)\)\)",
                r"Task.sleep(nanoseconds: UInt64(\1))", t)

            # TextField(..., axis: .vertical) -> TextField(...)
            t = re.sub(r"(TextField\([^\n]*?),\s*axis:\s*\.\w+\)", r"\1)", t)

            # UITextView(usingTextLayoutManager:) -> UITextView()
            t = re.sub(r"\(\s*usingTextLayoutManager:\s*(?:true|false)\s*\)", "()", t)
            t = re.sub(r",\s*usingTextLayoutManager:\s*(?:true|false)", "", t)

            # String(localized: "x") -> "x"
            t = re.sub(r"String\(localized:\s*\"([^\"]*)\"\)", r'"\1"', t)

            # UNUserNotificationCenter/UIApplication.setBadgeCount (iOS16)
            #   -> applicationIconBadgeNumber
            # 必须把调用连同尾随闭包（{ _ in }）一起替换，否则留下 "= 0 { _ in }" 残句
            badge_pat = re.compile(
                r"([ \t]*)(?:try\s+)?(?:await\s+)?[A-Za-z_][^\n{}]*?\.setBadgeCount\(")

            def _badge_sub(s: str) -> str:
                out = []
                pos = 0
                guard = 0
                while guard < 500:
                    guard += 1
                    m = badge_pat.search(s, pos)
                    if not m:
                        out.append(s[pos:])
                        break
                    lp = m.end() - 1
                    e = _match_delim(s, lp)
                    if e is None:
                        out.append(s[pos:m.end()])
                        pos = m.end()
                        continue
                    arg = s[lp + 1:e - 1].strip()
                    j = e
                    m2 = re.match(r"[ \t]*\{", s[j:])
                    if m2:
                        e2 = _match_delim(s, j + m2.end() - 1)
                        if e2 is not None:
                            j = e2
                    out.append(s[pos:m.start(1)] + m.group(1)
                               + "UIApplication.shared.applicationIconBadgeNumber = " + arg)
                    pos = j
                return "".join(out)

            t = _badge_sub(t)

            # 自愈：上一版替换 setBadgeCount 时漏掉了尾随闭包，留下
            #   ...applicationIconBadgeNumber = 0 { _ in }
            # 删掉挂在赋值后面的残留闭包即可恢复成正确的赋值语句。
            guard = 0
            while guard < 200:
                guard += 1
                m = re.search(r"\.applicationIconBadgeNumber\s*=\s*[^\n=;]*?[^\s][ \t]*\{", t)
                if not m:
                    break
                e = _match_delim(t, m.end() - 1)
                if e is None:
                    break
                t = t[:m.end() - 1] + t[e:]

            return t

        before = read(path)
        after = _fn(before)
        if after != before:
            write(path, after)
            touched += 1
    log("✅ 零散 API 替换（sleep/axis/badge/…）：%d 个文件受影响" % touched)


# ------------------------------------------------------- 6. iOS15 兼容层

COMPAT_SWIFT = r'''//
//  iOS15Compat.swift
//  MinisApp
//
//  iOS 15 port: SwiftUI types introduced in iOS 16, reimplemented with the
//  iOS 15 API surface. Behaviour is intentionally close-but-not-identical --
//  these exist so the app compiles and stays usable on iOS 15.5, not to win
//  design awards.
//

import SwiftUI

// MARK: - AnyShape (iOS 16)

/// Type-erased `Shape`. iOS 16 ships this; iOS 15 needs a hand-rolled version.
public struct AnyShape: Shape {
    private let _path: (CGRect) -> Path

    public init<S: Shape>(_ wrapped: S) {
        _path = wrapped.path(in:)
    }

    public func path(in rect: CGRect) -> Path {
        _path(rect)
    }
}

// MARK: - UnevenRoundedRectangle (iOS 16)

/// Rectangle with a per-corner radius. iOS 16 ships this; iOS 15 does not.
public struct UnevenRoundedRectangle: Shape {
    public var topLeadingRadius: CGFloat
    public var bottomLeadingRadius: CGFloat
    public var bottomTrailingRadius: CGFloat
    public var topTrailingRadius: CGFloat
    public var style: RoundedCornerStyle

    public init(topLeadingRadius: CGFloat = 0,
                bottomLeadingRadius: CGFloat = 0,
                bottomTrailingRadius: CGFloat = 0,
                topTrailingRadius: CGFloat = 0,
                style: RoundedCornerStyle = .continuous) {
        self.topLeadingRadius = topLeadingRadius
        self.bottomLeadingRadius = bottomLeadingRadius
        self.bottomTrailingRadius = bottomTrailingRadius
        self.topTrailingRadius = topTrailingRadius
        self.style = style
    }

    public func path(in rect: CGRect) -> Path {
        let w = rect.width
        let h = rect.height
        let tl = max(0, min(topLeadingRadius, min(w, h) / 2))
        let tr = max(0, min(topTrailingRadius, min(w, h) / 2))
        let bl = max(0, min(bottomLeadingRadius, min(w, h) / 2))
        let br = max(0, min(bottomTrailingRadius, min(w, h) / 2))

        var p = Path()
        p.move(to: CGPoint(x: rect.minX + tl, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX - tr, y: rect.minY))
        if tr > 0 {
            p.addArc(center: CGPoint(x: rect.maxX - tr, y: rect.minY + tr),
                     radius: tr, startAngle: .degrees(-90), endAngle: .degrees(0),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - br))
        if br > 0 {
            p.addArc(center: CGPoint(x: rect.maxX - br, y: rect.maxY - br),
                     radius: br, startAngle: .degrees(0), endAngle: .degrees(90),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.minX + bl, y: rect.maxY))
        if bl > 0 {
            p.addArc(center: CGPoint(x: rect.minX + bl, y: rect.maxY - bl),
                     radius: bl, startAngle: .degrees(90), endAngle: .degrees(180),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.minX, y: rect.minY + tl))
        if tl > 0 {
            p.addArc(center: CGPoint(x: rect.minX + tl, y: rect.minY + tl),
                     radius: tl, startAngle: .degrees(180), endAngle: .degrees(270),
                     clockwise: false)
        }
        p.closeSubpath()
        return p
    }
}

// MARK: - LabeledContent (iOS 16)

/// Label + value row. iOS 16 ships this; iOS 15 approximates it with an
/// `HStack` that pushes the content to the trailing edge.
public struct LabeledContent<Label: View, Content: View>: View {
    private let label: Label
    private let content: Content

    public init(@ViewBuilder content: () -> Content,
                @ViewBuilder label: () -> Label) {
        self.content = content()
        self.label = label()
    }

    public var body: some View {
        HStack(alignment: .firstTextBaseline) {
            label
            Spacer(minLength: 8)
            content
        }
    }
}

extension LabeledContent where Label == Text {
    /// `LabeledContent("Title", value: "…")`
    public init<S1: StringProtocol, S2: StringProtocol>(_ title: S1, value: S2)
    where Content == Text {
        self.init(content: { Text(value) }, label: { Text(title) })
    }

    /// `LabeledContent("Title") { … }`
    public init<S: StringProtocol>(_ title: S, @ViewBuilder content: () -> Content) {
        self.init(content: content, label: { Text(title) })
    }
}

// MARK: - NavigationPath (iOS 16)

/// Minimal stand-in for SwiftUI's iOS 16 `NavigationPath`.
///
/// The port replaces `NavigationStack(path:)` with `NavigationView`, so these
/// values are carried but never drive navigation on iOS 15. Kept as a real
/// type so existing `@State` declarations and helpers still compile.
public struct NavigationPath: Equatable {
    private var elements: [AnyHashable]

    public init() {
        elements = []
    }

    public init<C: Collection>(_ elements: C) where C.Element: Hashable {
        self.elements = elements.map { AnyHashable($0) }
    }

    public var count: Int { elements.count }
    public var isEmpty: Bool { elements.isEmpty }

    public mutating func append<V: Hashable>(_ value: V) {
        elements.append(AnyHashable(value))
    }

    public mutating func removeLast(_ k: Int = 1) {
        guard k > 0 else { return }
        elements.removeLast(min(k, elements.count))
    }

    public static func == (lhs: NavigationPath, rhs: NavigationPath) -> Bool {
        lhs.elements == rhs.elements
    }
}

// MARK: - ProposedViewSize (iOS 16)

/// Size proposal used by `UIViewRepresentable.sizeThatFits`.
public struct ProposedViewSize: Equatable {
    public var width: CGFloat?
    public var height: CGFloat?

    public init(width: CGFloat? = nil, height: CGFloat? = nil) {
        self.width = width
        self.height = height
    }

    public init(_ size: CGSize) {
        self.width = size.width
        self.height = size.height
    }

    public static let zero = ProposedViewSize(width: 0, height: 0)
    public static let infinity = ProposedViewSize(width: .infinity, height: .infinity)
    public static let unspecified = ProposedViewSize(width: nil, height: nil)

    public func replacingUnspecifiedDimensions(by size: CGSize) -> CGSize {
        CGSize(width: width ?? size.width, height: height ?? size.height)
    }
}
'''


def _field(blk: str, name: str):
    """从 pbxproj 对象块里取一个标量字段的值。"""
    m = re.search(r'\b' + name + r'\s*=\s*"?([^";]+)"?\s*;', blk)
    return m.group(1).strip() if m else None


def _children(blk: str):
    """取一个 group 块 children = ( ... ) 里的 uuid 列表。"""
    m = re.search(r"children\s*=\s*\((.*?)\);", blk, re.S)
    if not m:
        return []
    return re.findall(r"^\s*(\w+)\s*/\*", m.group(1), re.M)


def _all_groups(text: str):
    """[(uuid, path, children)]，只收 PBXGroup / PBXVariantGroup。"""
    b, e = _section(text, "PBXGroup")
    out = []
    if b < 0 or e <= b:
        return out
    for m in re.finditer(r"^\t\t(\w+)\s*(?:/\*[^*]*?\*/)?\s*=\s*\{", text[b:e], re.M):
        uuid = m.group(1)
        gs, ge = _block(text, uuid)
        if gs is None:
            continue
        blk = text[gs:ge]
        if "isa = PBXGroup" not in blk and "isa = PBXVariantGroup" not in blk:
            continue
        out.append((uuid, _field(blk, "path"), _children(blk)))
    return out


def resolve_compat_dir(text: str, ref: str) -> str:
    """算出 Xcode 会把 ref 解析到哪个目录（相对工程目录，"" 即工程目录）。

    兼容层以 path = "iOS15Compat.swift" + sourceTree = <group> 挂在某个 group 下，
    Xcode 按「该 group 的目录 + path」找文件；若不在任何 group 里则退回工程目录。
    磁盘上的文件必须放在同一处，否则会报 "Build input file cannot be found"。
    """
    groups = _all_groups(text)
    parent = {}
    for uuid, _p, kids in groups:
        for k in kids:
            parent.setdefault(k, uuid)
    comps = []
    cur = parent.get(ref)
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        nxt = None
        for uuid, p, _kids in groups:
            if uuid == cur:
                if p:
                    comps.insert(0, p)
                nxt = parent.get(cur)
                break
        if nxt is None:
            break
        cur = nxt
    return "/".join(comps)


def write_compat(subdir: str = "") -> None:
    d = os.path.normpath(os.path.join(ROOT, subdir)) if subdir else ROOT
    target = os.path.join(d, COMPAT_NAME)

    # 旧版本曾写到 src/ios/Compat/ 子目录，但 pbxproj 里挂的是 mainGroup，
    # Xcode 会去 src/ios/ 找 -> 报 Build input file cannot be found。清理掉。
    stale_dir = os.path.join(ROOT, "Compat")
    stale = os.path.join(stale_dir, COMPAT_NAME)
    if os.path.isfile(stale) and os.path.abspath(stale) != os.path.abspath(target):
        try:
            os.remove(stale)
            log("🧹 已删除旧位置的兼容层 %s" % stale)
        except OSError:
            pass
        try:
            os.rmdir(stale_dir)
            log("🧹 已删除空目录 %s" % stale_dir)
        except OSError:
            pass

    os.makedirs(d, exist_ok=True)
    write(target, COMPAT_SWIFT)
    log("✅ 已写入兼容层 %s" % target)


# --------------------------------------------------- pbxproj 注入兼容层

PBX = os.path.join(ROOT, "Minis.xcodeproj", "project.pbxproj")


def _section(text: str, name: str):
    b = text.find("/* Begin %s section */" % name)
    e = text.find("/* End %s section */" % name)
    return b, e


def _block(text: str, uuid: str):
    # 注释可选：PBXGroup 里没有 name 的组写成 `UUID = {`，带 name 的才写 `UUID /* name */ = {`
    m = re.search(re.escape(uuid) + r"\s*(?:/\*.*?\*/)?\s*=\s*\{", text)
    if not m:
        return None, None
    start = m.end() - 1
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return m.start(), i + 1
        i += 1
    return m.start(), len(text)


def _unique(base: str, text: str) -> str:
    """生成一个 text 中尚不存在的 uuid。"""
    cand = base
    n = 0
    while cand in text:
        n += 1
        cand = base[:-2] + "%02d" % n
    return cand


def _insert_into_section(text: str, section: str, line: str):
    b, _ = _section(text, section)
    if b < 0:
        return text, False
    marker = "/* Begin %s section */" % section
    pos = b + len(marker)
    return text[:pos] + "\n" + line + text[pos:], True


def inject_compat() -> str:
    """把 iOS15Compat.swift 加入主 App target 的编译源。

    幂等 + 自愈：每一步都先检查是否已存在，只在缺失时补齐，
    所以重复执行不会叠加，也能修好上一次跑歪留下的半成品引用。

    返回 Xcode 实际会去查找该文件的目录（相对工程目录，"" 表示工程目录本身）。
    """
    if not os.path.isfile(PBX):
        log("⚠️  未找到 %s，跳过注入（兼容层不会参与编译）" % PBX)
        return ""

    text = read(PBX)
    name = re.escape(COMPAT_NAME)

    def _sec(s):
        i, j = _section(text, s)
        return text[i:j] if (i >= 0 and j > i) else ""

    # ---- 1) PBXFileReference
    ref = None
    m = re.search(r"(\w+)\s*/\*\s*" + name + r"\s*\*/\s*=\s*\{isa = PBXFileReference;",
                  _sec("PBXFileReference"))
    if m:
        ref = m.group(1)
    if ref is None:
        ref = _unique("IOS15COMPAT0000000000000A", text)
        ins = '\t\t%s /* %s */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "%s"; sourceTree = "<group>"; };\n' % (
            ref, COMPAT_NAME, COMPAT_NAME)
        text, ok = _insert_into_section(text, "PBXFileReference", ins)
        if not ok:
            log("⚠️  找不到 PBXFileReference section，跳过注入")
            return ""
        log("✅ PBXFileReference 已创建 (%s)" % ref)
    else:
        # 自愈：path 必须是 mainGroup 子级的相对路径，否则 Xcode 找不到文件
        gs, ge = _block(text, ref)
        if gs is not None:
            blk = text[gs:ge]
            p = _field(blk, "path")
            if p and p != COMPAT_NAME:
                nb = blk.replace('path = "%s"' % p, 'path = "%s"' % COMPAT_NAME)
                nb = nb.replace("path = %s;" % p, 'path = "%s";' % COMPAT_NAME)
                if nb != blk:
                    text = text[:gs] + nb + text[ge:]
                    log("🔧 已修正文件引用路径 %s -> %s" % (p, COMPAT_NAME))

    # ---- 2) PBXBuildFile
    build = None
    m = re.search(r"(\w+)\s*/\*\s*" + name + r"\s+in Sources\s*\*/\s*=\s*\{isa = PBXBuildFile;",
                  _sec("PBXBuildFile"))
    if m:
        build = m.group(1)
    if build is None:
        build = _unique("IOS15COMPAT0000000000000B", text)
        ins2 = '\t\t%s /* %s in Sources */ = {isa = PBXBuildFile; fileRef = %s /* %s */; };\n' % (
            build, COMPAT_NAME, ref, COMPAT_NAME)
        text, ok = _insert_into_section(text, "PBXBuildFile", ins2)
        if ok:
            log("✅ PBXBuildFile 已创建 (%s)" % build)
        else:
            log("⚠️  找不到 PBXBuildFile section")

    # 3) 挂到 mainGroup 的 children
    mg = re.search(r"mainGroup\s*=\s*(\w+)", text)
    if mg:
        gs, ge = _block(text, mg.group(1))
        if gs is not None:
            blk = text[gs:ge]
            if re.search(r"^\s*%s\s*/\*" % re.escape(ref), blk, re.M):
                log("ℹ️  兼容层已在 mainGroup 中")
            elif "children" in blk:
                newblk = re.sub(r"(children\s*=\s*\()",
                                r"\1\n\t\t\t\t%s /* %s */," % (ref, COMPAT_NAME),
                                blk, count=1)
                text = text[:gs] + newblk + text[ge:]
                log("✅ 兼容层已挂到 mainGroup")
            else:
                log("⚠️  mainGroup 没有 children 列表")

    # 4) 加入主 App target 的 Sources phase
    tm = re.search(r"(\w+)\s*/\*\s*Minis\s*\*/\s*=\s*\{\s*isa = PBXNativeTarget;", text)
    if tm:
        ts, te = _block(text, tm.group(1))
        tblock = text[ts:te]
        # 找 PBXSourcesBuildPhase section 范围，判断哪个 phase 属于它
        sb, se = _section(text, "PBXSourcesBuildPhase")
        src_ids = set()
        if sb >= 0:
            src_ids = set(re.findall(r"(\w+)\s*/\*\s*Sources\s*\*/", text[sb:se]))
        for pid in re.findall(r"(\w+)\s*/\*[^)]*?\*/", tblock):
            pass
        phases = re.findall(r"(\w+)\s*/\*\s*([^*]*?)\s*\*/", tblock)
        chosen = None
        for pid, pname in phases:
            if pid in src_ids or pname == "Sources":
                chosen = pid
                break
        if chosen:
            ps, pe = _block(text, chosen)
            if ps is not None:
                pblk = text[ps:pe]
                if re.search(r"^\s*%s\s*/\*" % re.escape(build), pblk, re.M):
                    log("ℹ️  兼容层已在 Sources phase 中")
                elif "files" in pblk:
                    newp = re.sub(r"(files\s*=\s*\()",
                                  r"\1\n\t\t\t\t%s /* %s in Sources */," % (build, COMPAT_NAME),
                                  pblk, count=1)
                    text = text[:ps] + newp + text[pe:]
                    log("✅ 兼容层已加入 target 的 Sources phase (%s)" % chosen)
                else:
                    log("⚠️  Sources phase 没有 files 列表")
            else:
                log("⚠️  未定位到 Sources phase 块")
        else:
            log("⚠️  未在主 target 中找到 Sources phase，兼容层可能不参与编译")
    else:
        log("⚠️  未找到名为 Minis 的 PBXNativeTarget，跳过 Sources 注入")

    # 5) 算出 Xcode 到底会去哪个目录找这个文件（决定 write_compat 写到哪）
    sub = resolve_compat_dir(text, ref)
    log("📍 兼容层应放在 %s" % (os.path.join(ROOT, sub) if sub else ROOT))

    write(PBX, text)
    return sub


# ------------------------------------------------------------------ main

def main() -> None:
    if not os.path.isdir(ROOT):
        log("⚠️  未找到 %s，请在仓库根目录执行本脚本" % ROOT)
        sys.exit(0)

    log("=== OpenMinis -> iOS 15 移植（第二阶段）===")
    fix_applocalized()
    strip_localizedstringresource()
    restore_intent_props()
    annotate_intents()
    annotate_appintent_files()
    delete_call_exprs()
    repair_orphan_trailing_closures()
    delete_modifiers()
    misc_fixes()
    # 先注入（决定文件该放在哪），再按 pbxproj 解析出的目录写文件
    subdir = inject_compat()
    write_compat(subdir)
    log("=== 完成 ===")


if __name__ == "__main__":
    main()
