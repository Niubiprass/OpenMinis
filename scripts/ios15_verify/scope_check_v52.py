#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v52 编译级作用域检查。

v52 三段都在**方法体内注入 Swift 代码**, 而本机没有 swiftc, 编译问题只能
在 CI 装包前拦下。这里查六类编译级/作用域风险:

  A. API 存在性 —— 只允许出现编译器已验证存在的 API。
     ★v52-B 新读了 `superview?.frame.size.width`(已验证: V41-DEBT 读的就是它),
       v52-E 新读了 `superview?.frame.size.height`(同上)。但仍要显式列出来 ——
       v49 教训: 连踩两次 `textContainer.bounds` 与 `.lineFragmentWidth`,
       两次都是"没查证就猜 API 名"。

  B. **NSLog 变参实参类型** —— 是 run#37146140252 红在"编译 App"的唯一原因:
         NSLog("... laidW=%.1f ...", self.ios15LastLaidOutW, ...)
       ^ `ios15LastLaidOutW` 声明是 `CGFloat?`, 而 **NSLog 是 C 变参函数**,
         Swift 不能把 Optional 桥接进变参。
     ⇒ 扫**每一个**实参里的标识符, 查它的声明类型, 带 `?` 的必须已解包;
       另含 `?.` 可选链的直接形态判据(间接手段够不到的那一类)。
     ★v52 特有的坑: `ios15LastSaneContentW` 声明就是 `CGFloat?`，
       而 v52-B 的 NSLog **刻意不直接打印它**(打的是已解包后的 `_v52w`)——
       判据要能区分这两种写法。

  C. 段内零危险写 —— v52 段的性质是**只读判据 + 回落**:
     A/B/C 段不许碰 textContainer / frame / bounds / origin / invalidate*;
     E 段的快照是纯只读。**闸门自己动几何 = 与 SwiftUI 争布局 = v13/v34 翻车形态。**

  D. **局部量可达性** —— v52 两段都跨了段落:
     · v52-B 段用到 `_cvW` / `_edgeTouch` / `_svf0`, 都声明在同段更上方
     · v52-E 段用到 `_v52PreSVH`(声明在测高行之前) / `_needH` / `_edgeTouch`
     ⇒ 必须确认落点与声明之间**没有跨 `func` 的边界**。
     ★这是 v52 最容易踩的一条: v52-E 的判据块与快照之间隔着 v18 的测高循环,
       一旦哪天有人把 v18 段整体挪进另一个函数, `_v52PreSVH` 就不可达。

  E. NSLog 变参个数 —— 占位符数必须与实参数一致(不等是 UB, iOS 15 上乱码甚至崩)。

  F. **记忆位声明的存在性与形态** —— v52-A 引入 `ios15LastSaneContentW`。
     两类致命错法都能在编译期或运行期炸, 但**症状都不指向真正原因**:
       · 声明缺失 ⇒ 注入的 Swift 引用到不存在的标识符, 报错在几百行之外
       · 声明成 `static` ⇒ 编译能过, 但同屏并存的两种气泡宽度(358/326)
         会互相污染记忆位 ⇒ 回落时可能回落到另一个气泡的宽度
     ⇒ 判据必须显式查「声明存在」+「不是 static」+「是实例属性」。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ---- A. 只列 Apple 文档 / 上游已验证存在的成员 ----
KNOWN = {
    "NSTextContainer": {"size", "lineFragmentPadding", "maximumNumberOfLines",
                        "lineBreakMode", "exclusionPaths", "layoutManager",
                        "textLayoutManager", "textView", "widthTracksTextView",
                        "heightTracksTextView", "isSimpleRectangularTextContainer"},
    "NSLayoutManager": {"usedRect", "usedRange", "textContainer", "textStorage",
                        "glyphRange", "numberOfGlyphs", "ensureLayout",
                        "invalidateLayout", "invalidateDisplay"},
    "UITextView": {"textContainer", "textStorage", "layoutManager", "frame",
                   "bounds", "textContainerInset", "contentSize", "isScrollEnabled"},
    "UIView": {"frame", "bounds", "superview", "subviews", "layer",
               "setNeedsLayout", "layoutIfNeeded"},
    "NSTextStorage": {"length", "mutableString", "string", "characters"},
}

# ---- 已知不存在的 API(v49 两次编译失败的化石 + v52 易错点)----
BOGUS = {
    "textContainer.bounds": "NSTextContainer 没有 bounds(那是 NSView 的)",
    "textContainer.lineFragmentWidth": "它属于 TextKit2 的 NSTextLayoutManager 一族",
    "superview.width": "UIView 没有 width(要 frame.size.width)",
    "superview.size": "UIView 没有 size(要 frame.size)",
    "textContainer.contentWidth": "不存在",
    "frame.safeWidth": "不存在(别自己造)",
}

FAILS = []


def fail(msg):
    FAILS.append(msg)
    print("  ★ %s" % msg)


def strip_comments(code):
    code = re.sub(r"/\*.*?\*/", " ", code, flags=re.S)
    code = re.sub(r"//[^\n]*", " ", code)
    code = re.sub(r'"(?:[^"\\\n]|\\.)*"', '""', code)
    return code


def seg_of(t, begin, end, name):
    i = t.find(begin)
    if i < 0:
        fail("%s 段缺失(标记 %s)" % (name, begin))
        return ""
    j = t.find(end, i + 1)
    if j < 0:
        fail("%s 段未闭合(标记 %s)" % (name, end))
        return t[i:i + 2000]
    return t[i:j]


def _collect_decls(t):
    out = {}
    for m in re.finditer(
            r"^\s*(?:(?:public|private|internal|fileprivate|open)\s+)?"
            r"(?:static\s+)?(?:var|let)\s+(\w+)\s*:\s*([^=\n]+?)\s*(?:=[^=]|$)",
            t, re.M):
        out[m.group(1)] = m.group(2).strip()
    return out


def _scan_nslog_args(code, decls, seg_name):
    """扫每个 NSLog 调用的**每一个**实参, 查其中标识符的类型。

    ★不按占位符配对(实参里有三元表达式与函数调用, 顶层逗号切分后数量对不上,
      按配对查会 0 处命中, 看着像通过)。宁可多查不可漏查。
    ★括号配平扫调用体 —— 实参里有嵌套括号(例如 `min(a, b)`)。
    """
    checked = n_opt = n_arity = 0
    for cm in re.finditer(r"NSLog\(", code):
        i = cm.end() - 1
        depth = 0
        j = i
        while j < len(code):
            if code[j] == "(":
                depth += 1
            elif code[j] == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        else:
            fail("%s: NSLog( 的括号不配平 —— 调用体切不出来" % seg_name)
            continue
        body = code[i + 1:j]
        parts, buf, d, inq = [], [], 0, False
        for c in body:
            if c == '"':
                inq = not inq
            if not inq:
                if c in "([{":
                    d += 1
                elif c in ")]}":
                    d -= 1
                elif c == "," and d == 0:
                    parts.append("".join(buf))
                    buf = []
                    continue
            buf.append(c)
        parts.append("".join(buf))
        parts = [p for p in parts if p.strip()]
        if len(parts) < 2:
            continue
        fmt, args = parts[0], parts[1:]
        checked += 1
        # ---- E. 占位符个数 vs 实参数 ----
        n_ph = len(re.findall(r"%[-+ #0-9.*]*[a-zA-Z@]", fmt))
        if n_ph and n_ph != len(args):
            fail("%s: NSLog 占位符 %d 个但实参 %d 个(不匹配=UB, "
                 "iOS 15 上会打乱码甚至崩): %s"
                 % (seg_name, n_ph, len(args), fmt.strip()[:60]))
            n_arity += 1
        # ---- B. 逐实参查类型 ----
        for a in args:
            if "??" in a or a.strip().endswith("!"):
                continue          # 已在解包, 合法
            if "?." in a:
                # 含 `?.` 的实参本身即 Optional, 除非已 `??` 解包
                fail("%s: NSLog 变参含未解包的可选链 `%s` —— 结果是 Optional, "
                     "不能进 C 变参(run#37146140252 同型)。修法: `?? -1`"
                     % (seg_name, a.strip()[:50]))
                n_opt += 1
                continue
            for ident in re.findall(r"\b([A-Za-z_]\w*)\b", a):
                ty = decls.get(ident)
                if ty and ty.endswith("?"):
                    fail("%s: NSLog 变参实参含可选类型 `%s: %s` —— "
                         "NSLog 是 C 变参函数, Swift 不能桥接 Optional "
                         "(run#37146140252 的真实死因)。修法: 实参处 `?? -1`"
                         % (seg_name, ident, ty))
                    n_opt += 1
    return checked, n_opt, n_arity


def main():
    if len(sys.argv) < 2:
        print("用法: scope_check_v52.py <SelectableMarkdownView.swift>")
        return 3
    md = sys.argv[1]
    if not os.path.isfile(md):
        print("找不到产物: %s" % md)
        return 3
    t = open(md, encoding="utf-8").read()

    # ---- 段边界: 一律用**紧贴被测代码的下游锚点** ----
    # ★不用 `// [V48-PIN]` 当右界: 它在 v52 块下方约 60 行, 中间夹着 v18
    #   原有的 textContainer 写入 ⇒ 段开大会把上游合法写入算成 v52 的罪。
    #   这个坑在 fallback 的 verify 里第一版真踩出来了(自检当场报
    #   "段内出现 textContainer 宽高")。
    seg_gate = seg_of(t, "// [V52-B]", "var _realW = _svW > 1", "V52-GATE")
    seg_pre = seg_of(t, "// [V52-DEBT-PRE]",
                     "let _needH = sizeThatFits(CGSize(width: _realW2", "V52-DEBT-PRE快照")
    # 判据段的起点要回退到 `if !_edgeTouch` 那一行 —— 标记在 if 体内部,
    # 段从标记起切会漏掉条件行本身(这也是 fallback verify 踩过的)。
    i_debt = t.find("// [V52-DEBT-PRE]", t.find("let _needH = sizeThatFits(CGSize(width: _realW2"))
    seg_debt = ""
    if i_debt < 0:
        fail("V52-DEBT-PRE 判据段缺失")
    else:
        i_start = t.rfind("if !_edgeTouch, _needH > 1, textStorage.length > 0,",
                          0, i_debt)
        if i_start < 0:
            fail("V52-DEBT-PRE 判据段的 if 头没找到 —— 段起点比标记还早")
        else:
            j = t.find("if _didFix {", i_debt)
            if j < 0:
                fail("V52-DEBT-PRE 判据段未闭合(找不到 `if _didFix {`)")
            else:
                seg_debt = t[i_start:j]
    if not (seg_gate and seg_pre and seg_debt):
        print("  scope BAD(段缺失)")
        return 1

    decls = _collect_decls(t)

    # ================= A. API 存在性 =================
    for seg in (seg_gate, seg_pre, seg_debt):
        code = strip_comments(seg)
        for bogus, why in BOGUS.items():
            if bogus in code:
                fail("出现 %s —— %s" % (bogus, why))
        for m in re.finditer(
                r"\b(textContainer|layoutManager|textStorage|superview)"
                r"\.([a-zA-Z_]\w*)", code):
            recv, member = m.group(1), m.group(2)
            allowed = KNOWN["UIView" if recv == "superview" else
                            "NSTextContainer" if recv == "textContainer" else
                            "NSLayoutManager" if recv == "layoutManager" else
                            "NSTextStorage"]
            if member not in allowed:
                fail("%s 上没有成员 `%s`(v49 教训: 没查证就猜 API 名)" % (recv, member))

    # ================= B + E. NSLog 变参类型与个数 =================
    tot_c = tot_o = tot_a = 0
    for seg, nm in ((seg_gate, "V52-GATE"), (seg_debt, "V52-DEBT")):
        c, o, a = _scan_nslog_args(strip_comments(seg), decls, nm)
        tot_c += c
        tot_o += o
        tot_a += a
    if tot_c < 2:
        fail("只扫到 %d 条 NSLog(预期 2 条: 闸门 + 欠账自愈)—— "
             "扫描器本身可能失效" % tot_c)

    # ================= C. 段内零危险写 =================
    # 闸门段: 纯只读判据 + 回落, 一个字节都不许写进渲染链。
    code_gate = strip_comments(seg_gate)
    for pat, why in (
            (r"textContainer\.size(?:\.\w+)*\s*=", "textContainer 宽高"),
            (r"\bframe(?:\.\w+)*\s*=\s*[^=]", "frame 写入"),
            (r"\bbounds(?:\.\w+)*\s*=\s*[^=]", "bounds 写入"),
            (r"\.origin(?:\.\w+)*\s*=", "origin 写入"),
            (r"\.invalidateLayout\s*\(", "invalidateLayout"),
            (r"\.ensureLayout\s*\(", "ensureLayout"),
            (r"\.setNeedsLayout\s*\(", "setNeedsLayout"),
            (r"\.invalidateIntrinsicContentSize\s*\(", "invalidateIntrinsicContentSize")):
        if re.search(pat, code_gate):
            fail("★闸门段内出现 %s —— 闸门是**只读判据 + 回落**, "
                 "自己动几何就是与 SwiftUI 争布局(v13/v34 翻车形态)" % why)
    # 快照段: 纯只读。
    code_pre = strip_comments(seg_pre)
    for pat, why in (
            (r"\bframe(?:\.\w+)*\s*=\s*[^=]", "frame 写入"),
            (r"\bbounds(?:\.\w+)*\s*=\s*[^=]", "bounds 写入"),
            (r"\.invalidateLayout\s*\(", "invalidateLayout"),
            (r"\.setNeedsLayout\s*\(", "setNeedsLayout")):
        if re.search(pat, code_pre):
            fail("★快照段内出现 %s —— 快照必须是纯只读" % why)
    # 判据段: 允许的写只有记忆位与 pending flag; 不许碰几何。
    code_debt = strip_comments(seg_debt)
    for pat, why in (
            (r"textContainer\.size(?:\.\w+)*\s*=", "textContainer 宽高"),
            (r"\bframe(?:\.\w+)*\s*=\s*[^=]", "frame 写入"),
            (r"\bbounds(?:\.\w+)*\s*=\s*[^=]", "bounds 写入"),
            (r"\.invalidateLayout\s*\(", "invalidateLayout"),
            (r"\.ensureLayout\s*\(", "ensureLayout"),
            (r"\.setNeedsLayout\s*\(", "setNeedsLayout")):
        if re.search(pat, code_debt):
            fail("★欠账自愈段内出现 %s —— 自愈只该走 invalidateCellSizeIfNeeded "
                 "那条**诉求**链, 不许自己改几何" % why)
    # 借用 flag 的机制不许被删(那是 v38-A 已验证可用的部分)
    for pat, why in (("invalidateCellSizeIfNeeded()", "诉求侧提交调用"),
                     ("deferredCorrectionPending", "pending flag 借道")):
        if pat not in code_debt:
            fail("★%s 不见了 —— v38-A 的借用机制是已验证可用的部分, "
                 "本版只该换判据源" % why)

    # ================= D. 局部量可达性 =================
    # v52-E 的快照与判据块之间隔着 v18 的测高循环 —— 一旦有人把 v18 段
    # 整体挪进另一个函数, `_v52PreSVH` 立刻不可达(编译报 "cannot find in scope",
    # 而报错位置在判据块, 真正的原因在改动处)。
    for name in ("_v52PreSVH", "_needH"):
        di = t.find("let %s " % name)  # ★尾部空格: 排除 `let _needH40` 这类前缀命中
        if di < 0:
            fail("局部量 `%s` 没找到" % name)
            continue
        if name == "_v52PreSVH":
            use = t.find("_v52PreSVH <", di)
        else:
            use = t.find("_v52PreSVH < _needH", di)
        if use < 0:
            continue
        seg_between = t[di:use]
        # 函数边界(顶层 `func` / `class` 缩进为 0 或 4)
        if re.search(r"^\s{0,4}(?:public |private |internal |fileprivate |open )*"
                     r"(?:final class|class|func)\b", seg_between, re.M):
            fail("`%s` 的声明与使用之间跨了函数边界 —— 局部量不可达, "
                 "编译期报 'cannot find in scope'" % name)

    # ================= F. 记忆位声明 =================
    if not re.search(r"^    var ios15LastSaneContentW: CGFloat\?$", t, re.M):
        fail("★记忆位 `ios15LastSaneContentW` 未声明成实例属性 —— "
             "注入的 Swift 会引用到不存在的标识符, 报错在几百行之外")
    if re.search(r"static\s+var\s+ios15LastSaneContentW", t):
        fail("★记忆位是 static —— 同屏并存的两种气泡宽度(358/326)会互相污染, "
             "回落时可能回落到另一个气泡的宽度")
    # 记忆位必须真的被闸门段用到(声明了却没人写 = 又一个静默失效)
    if "ios15LastSaneContentW" not in strip_comments(seg_gate):
        fail("★闸门段里没有引用记忆位 —— 声明了却没用, 等于没有记忆")

    print("  scope: NSLog %d 条(可选实参 %d / 个数不匹配 %d), "
          "段 3/3, 记忆位 1/1" % (tot_c, tot_o, tot_a))
    if FAILS:
        print("  scope=BAD %d 项" % len(FAILS))
        return 1
    print("  scope=OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
