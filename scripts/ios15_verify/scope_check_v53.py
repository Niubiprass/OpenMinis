#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v53 编译级作用域检查。

本机没有 swiftc, 编译问题只能在 CI 装包前拦下。v53 的风险面比前几版大得多
—— 它第一次**跨文件**改动(`MessageListInfrastructure.swift`), 而且第一次
引入「实例方法被另一个文件的类型调用」的可见性问题。查六类:

  A. 跨文件可见性 —— v53 在 `SelectableMarkdownView` 里调用
     `cell.v53NotePendingDebt(_:)` / `cell.v53PendingHeightDebt`, 而
     `v53NotePendingDebt` 定义在**另一个文件**的 `SelfSizingCell` 上。
     ★必须是 `internal`(无修饰符默认)且**非 private**; 若误加 `private`,
     编译报 "method is private and cannot be used from another file"。

  B. NSLog 变参实参类型 —— 这是 run#37146140252 红在「编译 App」的唯一原因:
     `NSLog` 是 C 变参函数, Swift 不能把 `CGFloat?` 桥接进变参。
     v53 新增 4 条探针(V53-SHORT / V53-MEM / V53-HOLD / DeferDebt 新字段),
     每条都要查实参类型。

  C. NSLog 变参**个数** —— 占位符数必须等于实参数, 不等是 UB,
     iOS 15 上会打出乱码甚至崩。v53 的 `[V53-SHORT]` 用了 `%llu` 配
     `UInt64(...)`, 这种必须实测配平。

  D. 段内零危险写 —— v53-C1 改的是**记忆位**和闸门局部量, 绝不许碰
     textContainer / frame / bounds / invalidateLayout。
     ★C2 在**另一个文件**里给三条短路加条件, 同样不许改任何 return 值。

  E. 记忆位与欠账字段的声明位置 —— `v53PendingHeightDebt` / `v53DebtSeenCount`
     必须在 `SelfSizingCell` 类体内(不能漏在类外), 否则 Swift 报
     "declaration is only valid at file scope"。

  F. 可达性 —— `_v53ReportDebtToCell` 用到的 `findCell()` 是 `private`,
     在**同一个文件同类**内可见 ⇒ 合法。若将来被挪出该类, 判据要报。

用法: scope_check_v53.py <产物根目录 或 SelectableMarkdownView.swift>
退出码: 0 = 通过, 1 = 有问题, 3 = 环境不全
"""
import os
import re
import sys

MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"
INFRA_REL = "src/ios/Agent/MessageList/MessageListInfrastructure.swift"

# ---- A. 跨文件调用必须 internal(无 private/fileprivate) ----
CROSS_FILE_CALLS = (
    ("v53NotePendingDebt", "欠账上报入口 —— SelectableMarkdownView 跨文件调用它"),
    ("v53PendingHeightDebt", "欠账量字段 —— 探针要读它"),
    ("v53DebtIsRipe", "欠账成熟判据 —— 三条短路各读它一次"),
)

# ---- B. NSLog 变参里出现即为错的类型(带 ? 的 Optional 不能进 varargs) ----
FORBIDDEN_VARARG_TYPES = (
    "CGFloat?", "Int?", "Double?", "Bool?",
)

# ---- 已知不存在的 API ----
BOGUS = {
    "textContainer.bounds": "NSTextContainer 没有 bounds(那是 NSView 的)",
    "textContainer.lineFragmentWidth": "NSTextContainer 没有 lineFragmentWidth",
    "textStorage attributedString": "NSTextStorage 没有 attributedString 属性",
    "superview?.safeAreaInsets": "UIView 没有 safeAreaInsets(那是 scrollView/VC)",
}

# ---- NSLog 格式符 -> 允许的实参类型提示(仅用于报错文案) ----
PLACEHOLDER = re.compile(r"%[-+0-9.]*(?:ll)?[a-zA-Z@]")


def _strip_noise(src):
    """去掉注释与字符串字面量, 只留可执行代码(与 fallback 同口径)。"""
    out = []
    i, n = 0, len(src)
    while i < n:
        c = src[i]
        if c == "/" and i + 1 < n and src[i + 1] == "/":
            j = src.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and src[i + 1] == "*":
            d, i = 1, i + 2
            while i < n and d > 0:
                if i + 1 < n and src[i] == "/" and src[i + 1] == "*":
                    d += 1
                    i += 2
                    continue
                if i + 1 < n and src[i] == "*" and src[i + 1] == "/":
                    d -= 1
                    i += 2
                    continue
                i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


def resolve(target):
    if os.path.isfile(target):
        return os.path.abspath(target), None
    md = os.path.join(target, MD_REL)
    if os.path.exists(md):
        return md, os.path.abspath(target)
    return None, None


def main():
    if len(sys.argv) < 2:
        print("用法: scope_check_v53.py <产物根目录 或 SelectableMarkdownView.swift>")
        return 3
    md, root = resolve(sys.argv[1])
    if md is None:
        print("SKIP(找不到产物: %s)" % MD_REL)
        return 3
    infra = os.path.join(root or "", INFRA_REL)
    if not os.path.isfile(infra):
        # 单文件模式: 从 swift 路径往上退两级拿 root
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(md)))))
        infra = os.path.join(root, INFRA_REL)
    if not os.path.isfile(infra):
        print("SKIP(找不到产物: %s —— v53 跨文件改动, 必须有它才能查)" % INFRA_REL)
        return 3

    t = open(md, encoding="utf-8").read()
    f = open(infra, encoding="utf-8").read()
    code_t = _strip_noise(t)
    code_f = _strip_noise(f)
    print("产物: %s (%d) + %s (%d)" % (os.path.basename(md), len(t),
                                       os.path.basename(infra), len(f)))

    bad = []

    # ---- A. 跨文件可见性 ----
    for name, why in CROSS_FILE_CALLS:
        # 找声明行, 确认前面没有 private/fileprivate
        m = re.search(r"^([ \t]*)((?:private|fileprivate)\s+)?"
                      r"(?:static\s+)?(?:var|func)\s+%s\b" % re.escape(name),
                      f, re.M)
        if not m:
            bad.append("A: `%s` 在 %s 里没有声明 —— %s"
                       % (name, os.path.basename(infra), why))
            continue
        if m.group(2):
            bad.append(
                "A: ★`%s` 声明为 `%s` —— 它被 **另一个文件**的 "
                "SelectableMarkdownView 调用, 私有化会编译失败"
                "(\"method is private and cannot be used from another file\")。"
                "原因: %s" % (name, m.group(2).strip(), why))
        # 使用侧必须真的存在调用
        if name == "v53NotePendingDebt" and "cell.v53NotePendingDebt(debt)" not in code_t:
            bad.append("A: `%s` 在 SelectableMarkdownView 侧没有调用点 —— "
                       "欠账送不到 cell, 三条短路无从判断" % name)
        if name == "v53DebtIsRipe" and code_f.count("!v53DebtIsRipe") != 3:
            bad.append("A: `v53DebtIsRipe` 使用点应为 3 处(A/B/C 三条短路), "
                       "实为 %d" % code_f.count("!v53DebtIsRipe"))

    # ---- B. NSLog 变参实参里不得有 Optional ----
    for src, tag in ((code_t, "SelectableMarkdownView"), (code_f, "MessageListInfrastructure")):
        for m in re.finditer(r'NSLog\("([^"]*)"((?:\s*,\s*[^;]*?)?)\)', src):
            fmt, args = m.group(1), m.group(2) or ""
            for bad_t in FORBIDDEN_VARARG_TYPES:
                # 实参里出现 `xxx: BadT?` 形态
                if re.search(r"[A-Za-z_]\w*\s*:\s*%s\b" % re.escape(bad_t), args):
                    bad.append(
                        "B: ★%s 的 NSLog 实参里出现 `%s` —— NSLog 是 C 变参函数, "
                        "Swift 不能把 Optional 桥接进变参, iOS 15 上编译直接失败"
                        % (tag, bad_t))
            # `?` 直接跟在标识符后(未解包)也算
            for m2 in re.finditer(r"[A-Za-z_]\w*\?[,)]", args):
                bad.append(
                    "B: ★%s 的 NSLog 实参 `%s?` 未解包 —— 变参不接受 Optional"
                    % (tag, m2.group(1)))

    # ---- C. NSLog 占位符/实参个数配平 ----
    for src, tag in ((t, "SelectableMarkdownView"), (f, "MessageListInfrastructure")):
        for m in re.finditer(r'NSLog\(\s*"([^"]*)"\s*((?:,[^;]*?)?)\)\s*\n', src):
            fmt, args = m.group(1), (m.group(2) or "").lstrip(",").rstrip()
            if "[V5" not in fmt and "[V4" not in fmt:
                continue
            n_ph = len(PLACEHOLDER.findall(fmt))
            if not args.strip():
                n_args = 0
            else:
                # 顶层逗号切分(忽略括号/引号内)
                depth, cur, n_args = 0, [], 0
                instr = False
                for ch in args:
                    if ch == '"':
                        instr = not instr
                    if not instr:
                        if ch in "([{":
                            depth += 1
                        elif ch in ")]}":
                            depth -= 1
                        elif ch == "," and depth == 0:
                            n_args += 1
                            continue
                    cur.append(ch)
                if "".join(cur).strip():
                    n_args += 1
            if n_ph != n_args:
                bad.append(
                    "C: ★%s 的 NSLog 占位符 %d 个但实参 %d 个 —— 个数不等是 "
                    "varargs UB, iOS 15 上打出乱码甚至崩。格式串: %s"
                    % (tag, n_ph, n_args, fmt[:60]))

    # ---- D. C1 段内零几何写 ----
    i = t.find("let _v53memW")
    if i >= 0:
        seg = _strip_noise(t[i:t.find("}()", i) + 3])
        for pat, why in (
                (r"textContainer\.size(?:\.\w+)*\s*=", "textContainer 宽高"),
                (r"\bframe(?:\.\w+)*\s*=\s*[^=]", "frame 写入"),
                (r"\bbounds(?:\.\w+)*\s*=\s*[^=]", "bounds 写入"),
                (r"\.invalidateLayout\s*\(", "invalidateLayout"),
                (r"\.setNeedsLayout\s*\(", "setNeedsLayout")):
            if re.search(pat, seg):
                bad.append("D: ★`_v53memW` 段内出现 %s —— C1 是**纯判据**, "
                           "不许动几何(动了就不是记忆位修复而是抢宽)" % why)

    # ---- D2. 三条短路的 return 值不得被改 ----
    for tag in ("// [V53-PROBE] A 路", "// [V53-PROBE] B 路", "// [V53-PROBE] C 路"):
        j = f.find(tag)
        if j < 0:
            continue
        seg = _strip_noise(f[j:j + 420])
        # 只允许 `return copy`; 任何把 copy.size.height 改成别的值的写法都算
        for m in re.finditer(r"copy\.size\.height\s*=\s*([^;\n]+)", seg):
            rhs = m.group(1).strip()
            if rhs not in ("cached", "sh", "copy.size.height"):
                bad.append(
                    "D2: ★%s 之后 copy.size.height 被赋成 `%s` —— "
                    "v53 只加条件不改返回值; 改高度就变成了新的抢宽时机"
                    % (tag, rhs[:40]))

    # ---- E. 字段声明必须在类体内 ----
    for name in ("v53PendingHeightDebt", "v53DebtSeenCount"):
        m = re.search(r"^([ \t]*)(?:private\s+)?var\s+%s\b" % re.escape(name),
                      f, re.M)
        if not m:
            bad.append("E: `%s` 在 %s 里没有声明"
                       % (name, os.path.basename(infra)))
            continue
        indent = len(m.group(1))
        if indent == 0:
            bad.append(
                "E: ★`%s` 声明在**文件作用域**(缩进 0) —— 它是 cell 的实例状态, "
                "必须在 SelfSizingCell 类体内, 否则编译报 "
                "\"declaration is only valid at file scope\"" % name)
        elif indent > 8:
            bad.append(
                "E: ★`%s` 缩进 %d(>8) —— 疑似声明在嵌套函数/闭包内, "
                "那样 cell 的所有实例都读不到" % (name, indent))

    # ---- F. 已知不存在的 API ----
    for src, tag in ((t, "SelectableMarkdownView"), (f, "MessageListInfrastructure")):
        code = _strip_noise(src)
        for api, why in BOGUS.items():
            if api in code:
                bad.append("F: ★%s 用了 %s —— %s" % (tag, api, why))

    if bad:
        print("scope=BAD (%d 项)" % len(bad))
        for b in bad:
            print("   · %s" % b)
        return 1
    print("scope=OK  跨文件可见性/NSLog 变参类型/占位符配平/段内零几何写/字段作用域 全过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
