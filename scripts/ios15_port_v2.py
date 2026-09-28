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
COMPAT_REL = os.path.join(ROOT, "Compat", COMPAT_NAME)

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
    """清掉其他文件里对 LocalizedStringResource 的显式类型标注。"""
    n = 0
    for path in swift_files(ROOT):
        if path == APPL_PATH:
            continue

        def _fn(text: str) -> str:
            if "LocalizedStringResource" not in text:
                return text
            out = text
            out = out.replace(": LocalizedStringResource?", ": String?")
            out = out.replace(": LocalizedStringResource", ": String")
            out = out.replace("-> LocalizedStringResource", "-> String")
            out = out.replace("<LocalizedStringResource>", "<String>")
            out = out.replace("[LocalizedStringResource]", "[String]")
            out = out.replace("as? LocalizedStringResource", "as? String")
            out = out.replace("as LocalizedStringResource", "as String")
            return out

        if edit(path, _fn):
            n += 1
    log("✅ 清理 LocalizedStringResource 类型标注：%d 个文件" % n)


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
        def _fn(text: str) -> str:
            if "@available(iOS 16.0, *) // ios15-port" in text:
                return text
            lines = text.split("\n")
            out = []
            for ln in lines:
                m = DECL_RE.match(ln)
                if m and not ln.lstrip().startswith("//"):
                    ind = m.group("ind")
                    out.append("%s@available(iOS 16.0, *) // ios15-port" % ind)
                    n_insert = True
                out.append(ln)
            return "\n".join(out)

        before = read(path)
        after = _fn(before)
        if after != before:
            write(path, after)
            n += 1
    log("✅ Intents 目录标注 @available(iOS 16.0, *)：%d 个文件" % n)


# ------------------------------------------- 4. 删除 iOS16 装饰性修饰符

DELETE_LINE_RES = [
    r"\.presentationDragIndicator\(",
    r"\.toolbarBackground\(",
    r"\.listRowSeparatorLeading\(",
    r"\.scrollIndicators\(",
    r"\.scrollDismissesKeyboard\(",
    r"\.scrollContentBackground\(",
    r"\.persistentSystemOverlays\(",
    r"\.navigationSplitViewColumnWidth\(",
    r"\.dropDestination\(",
    r"\.draggable\(",
    r"\.toolbar\([^\n]*for:\s*\.(?:navigationBar|bottomBar|tabBar)",
]


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

            # UNUserNotificationCenter.setBadgeCount (iOS16) -> applicationIconBadgeNumber
            def _badge(m):
                arg = m.group(2).strip()
                return "%sUIApplication.shared.applicationIconBadgeNumber = %s" % (
                    m.group(1), arg)
            t = re.sub(r"([ \t]*)(?:try\s+)?(?:await\s+)?[A-Za-z_][^\n]*\.setBadgeCount\(([^()]*)\)",
                       _badge, t)

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


def write_compat() -> None:
    os.makedirs(os.path.dirname(COMPAT_REL), exist_ok=True)
    write(COMPAT_REL, COMPAT_SWIFT)
    log("✅ 已写入兼容层 %s" % COMPAT_REL)


# --------------------------------------------------- pbxproj 注入兼容层

PBX = os.path.join(ROOT, "Minis.xcodeproj", "project.pbxproj")


def _section(text: str, name: str):
    b = text.find("/* Begin %s section */" % name)
    e = text.find("/* End %s section */" % name)
    return b, e


def _block(text: str, uuid: str):
    m = re.search(re.escape(uuid) + r"\s*/\*.*?\*/\s*=\s*\{", text)
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


def inject_compat() -> None:
    """把 iOS15Compat.swift 加入主 App target 的编译源。"""
    if not os.path.isfile(PBX):
        log("⚠️  未找到 %s，跳过注入（兼容层不会参与编译）" % PBX)
        return

    text = read(PBX)
    if "/* %s */" % COMPAT_NAME in text:
        log("ℹ️  兼容层已在工程中，跳过注入")
        return

    ref = "IOS15COMPAT0000000000000A"
    build = "IOS15COMPAT0000000000000B"
    while ref in text or build in text:
        ref += "A"
        build += "B"

    # 1) PBXFileReference
    b, e = _section(text, "PBXFileReference")
    if b < 0:
        log("⚠️  找不到 PBXFileReference section，跳过注入")
        return
    ins = '\t\t%s /* %s */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "%s"; sourceTree = "<group>"; };\n' % (
        ref, COMPAT_NAME, COMPAT_NAME)
    text = text[:b + len("/* Begin PBXFileReference section */")] + "\n" + ins + text[b + len("/* Begin PBXFileReference section */"):]

    # 2) PBXBuildFile
    b2, _ = _section(text, "PBXBuildFile")
    if b2 >= 0:
        ins2 = '\t\t%s /* %s in Sources */ = {isa = PBXBuildFile; fileRef = %s /* %s */; };\n' % (
            build, COMPAT_NAME, ref, COMPAT_NAME)
        marker = "/* Begin PBXBuildFile section */"
        text = text[:b2 + len(marker)] + "\n" + ins2 + text[b2 + len(marker):]

    # 3) 挂到 mainGroup 的 children
    mg = re.search(r"mainGroup = (\w+)", text)
    if mg:
        gs, ge = _block(text, mg.group(1))
        if gs is not None:
            blk = text[gs:ge]
            if "children" in blk:
                newblk = re.sub(r"(children\s*=\s*\()",
                                r"\1\n\t\t\t\t%s /* %s */," % (ref, COMPAT_NAME),
                                blk, count=1)
                text = text[:gs] + newblk + text[ge:]

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
                if "files" in pblk:
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

    write(PBX, text)


# ------------------------------------------------------------------ main

def main() -> None:
    if not os.path.isdir(ROOT):
        log("⚠️  未找到 %s，请在仓库根目录执行本脚本" % ROOT)
        sys.exit(0)

    log("=== OpenMinis -> iOS 15 移植（第二阶段）===")
    fix_applocalized()
    strip_localizedstringresource()
    annotate_intents()
    delete_modifiers()
    misc_fixes()
    write_compat()
    inject_compat()
    log("=== 完成 ===")


if __name__ == "__main__":
    main()
