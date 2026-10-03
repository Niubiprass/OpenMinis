#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v51 编译级作用域检查。

v51 两段都在**方法体内注入 Swift 代码**, 而本机没有 swiftc, 编译问题只能
在 CI 装包前拦下。这里查五类编译级/作用域风险:

  A. API 存在性 —— 只允许出现编译器已验证存在的 API。
     ★v51-A 读了三个新成员: `frame.size.width` / `superview?.frame.size.width` /
       `textStorage.length`, 全部来自 UIView/UITextView, 但仍要显式列出来 ——
       v49 教训: 连踩两次 `textContainer.bounds` 与 `.lineFragmentWidth`,
       两次都是"没查证就猜 API 名"。

  B. **NSLog 变参实参类型** —— 本组最有价值的一条, 是 run#37146140252
     红在"编译 App"的唯一原因:
         NSLog("... laidW=%.1f ...", self.ios15LastLaidOutW, ...)
       ^ `ios15LastLaidOutW` 声明是 `CGFloat?`, 而 **NSLog 是 C 变参函数**,
         Swift 不能把 Optional 桥接进变参:
             error: 'NSLog' is unavailable: Variadic function is unavailable
     ⇒ 扫**每一个**实参里的标识符, 查它的声明类型, 带 `?` 的必须已解包。
     ★查法必须**逐实参、不要求配平**: 本轮第一版按"占位符数 vs 实参数"配对,
       结果 **0 处命中** —— 实参里有三元表达式与函数调用, 顶层逗号切分后
       数量对不上, 全部被 `continue` 跳过, 判据却输出"0 处"看着像通过。
       ⇒ 实参个数对不上时**宁可多查不可漏查**。

  C. 段内零危险写 —— v51-A 改 `frame.size.width`, 这是 v18 段一路
     (v32→v48)从未碰过的维度, 判据必须硬查: 不许碰 origin / height /
     bounds / 整个 size / textContainer。

  D. `_realW2` 可达性 —— v51-A 用了 `_realW2`。它是 v18 段内的局部量,
     而本版落点在 `// [V49-WWRITER-V18-END]` 之后(同一段内)⇒ 必须确认
     落点与声明之间**没有跨函数的 `func` 边界**。

  E. NSLog 变参个数 —— 格式串占位符数必须与实参数一致(不等就是 UB,
     且 iOS 15 上会打出乱码或直接崩)。
"""
import os
import re
import sys

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
    # ★v51-A 新读到的三个: 都是 UIView / NSTextStorage 的既有成员
    "UIView": {"frame", "bounds", "superview", "subviews", "layer",
               "setNeedsLayout", "layoutIfNeeded"},
    "NSTextStorage": {"length", "mutableString", "string", "characters"},
}

# ---- 已知不存在的 API(v49 两次编译失败的化石 + v51 新增几处易错点)----
BOGUS = {
    "textContainer.bounds": "NSTextContainer 没有 bounds(那是 NSView 的)",
    "textContainer.lineFragmentWidth": "它属于 TextKit2 的 NSTextLayoutManager 一族",
    "textContainer.attachedRange": "不存在",
    "layoutManager.estimatedGlyphCount": "不存在",
    "textStorage.glyphCount2": "不存在",
    "frame.anchor": "CGRect 没有 anchor",
    "frame.safeWidth": "不存在(别自己造)",
    "superview.width": "UIView 没有 width(要 frame.size.width)",
}

FAILS = []


def fail(msg):
    FAILS.append(msg)
    print("  ★ %s" % msg)


def strip_comments(code):
    """剥掉 // 注释与 /* */ 块, 并去掉字符串字面量 ——
    否则注释里写 `textContainer.bounds` 会造成假阳性(判据自己的注释
    恰好就写着这两个 API 名)。"""
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
    """扫出本类型里所有 `var/let x: T` 的声明, 返回 {名: 类型串}。

    ★只取**声明**(左侧有 `:`), 不取赋值 —— 取赋值会把局部量也算进来,
    而 NSLog 实参里的局部量类型是推断的, 不可查。
    """
    out = {}
    for m in re.finditer(
            r"^\s*(?:(?:public|private|internal|fileprivate|open)\s+)?"
            r"(?:static\s+)?(?:var|let)\s+(\w+)\s*:\s*([^=\n]+?)\s*(?:=[^=]|$)",
            t, re.M):
        out[m.group(1)] = m.group(2).strip()
    return out


def _scan_nslog_args(code, decls, seg_name, dry=False):
    """扫每个 NSLog 调用的**每一个**实参, 查其中标识符的类型。

    ★不按占位符配对(本轮踩过: 配对后 0 处命中, 看着像通过)。
      实参里有三元表达式与函数调用, 顶层逗号切分后数量对不上。
    ★括号配平扫调用体 —— 不能用正则 `.*?\)`, 实参里有嵌套括号
      (例如 `min(a, b)`), 非配平会提前截断。
    """
    checked = 0
    n_opt = 0
    n_arity = 0
    for cm in re.finditer(r"NSLog\(", code):
        # ---- 括号配平, 取出调用体 ----
        i = cm.end() - 1          # 指向 '('
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
            if not dry:
                fail("%s: NSLog( 的括号不配平 —— 调用体切不出来" % seg_name)
            continue
        body = code[i + 1:j]
        # ---- 顶层逗号切分(跳过括号/字符串内的逗号) ----
        parts = []
        buf = []
        d = 0
        inq = False
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
        fmt = parts[0]
        args = parts[1:]
        checked += 1
        # ---- E. 占位符个数 vs 实参数 ----
        n_ph = len(re.findall(r"%[-+ #0-9.*]*[a-zA-Z@]", fmt))
        if n_ph and n_ph != len(args):
            if not dry:
                fail("%s: NSLog 占位符 %d 个但实参 %d 个(不匹配=UB, "
                     "iOS 15 上会打乱码甚至崩): %s"
                     % (seg_name, n_ph, len(args), fmt.strip()[:60]))
            n_arity += 1
        # ---- B. 逐实参查类型 ----
        for a in args:
            # `?? -1` / `!` 是在**解包**, 那是合法写法(必须先判掉)
            unwrapped = "??" in a or a.strip().endswith("!")
            if unwrapped:
                continue
            # ★★ S7 的漏放点: `superview?.frame.size.width` 是**可选链**,
            #   结果是 `CGFloat?`, 但里面没有一个能查到声明的**标识符**
            #   (`superview` 是 UIView 的属性, 不在 `_collect_decls` 的范围,
            #    `frame`/`size`/`width` 是成员名)。⇒ 上面那段按标识符查类型
            #    完全查不到它, S7 sabotage(去掉 `?? -1`)就"未被拦截"。
            #   修法: **含 `?.` 的实参本身即 Optional**, 除非已 `??` 解包,
            #    否则就是往 C 变参里塞可选值 —— 与 run#37146140252 同型。
            #   ⇒ 纪律: **按"查声明"这类间接手段够不到时, 补一条直接形态判据**;
            #     只靠一条路查, 漏掉的那一类会安静地通过。
            if "?." in a:
                if not dry:
                    fail("%s: NSLog 变参含未解包的可选链 `%s` —— 结果是 Optional, "
                         "不能进 C 变参(run#37146140252 同型)。修法: `?? -1`"
                         % (seg_name, a.strip()[:50]))
                n_opt += 1
                continue
            for ident in re.findall(r"\b([A-Za-z_]\w*)\b", a):
                ty = decls.get(ident)
                if ty and ty.endswith("?"):
                    if not dry:
                        fail("%s: NSLog 变参实参含可选类型 `%s: %s` —— "
                             "NSLog 是 C 变参函数, Swift 不能桥接 Optional "
                             "(run#37146140252 的真实死因)。修法: 实参处 `?? -1`"
                             % (seg_name, ident, ty))
                    n_opt += 1
    return checked, n_opt, n_arity


def main():
    if len(sys.argv) < 2:
        print("用法: scope_check_v51.py <SelectableMarkdownView.swift>")
        return 3
    md = sys.argv[1]
    if not os.path.isfile(md):
        print("找不到产物: %s" % md)
        return 3
    t = open(md, encoding="utf-8").read()

    # ---- 段边界: 一律用**下游稳定锚点**, 不用固定字符数 ----
    seg_a = seg_of(t, "// [V51-FRAMEPIN]", "// [IOS15-FIX-RELC v28]", "V51-FRAMEPIN")
    seg_diag = seg_of(t, "// [V51-FRAMEPIN-DIAG]", "// [IOS15-FIX-RELC v28]",
                      "V51-FRAMEPIN-DIAG")
    seg_c = seg_of(t, "// [V51-PROBE]", "// [V45-TVHFIX]", "V51-PROBE")
    if not (seg_a and seg_diag and seg_c):
        print("  scope BAD(段缺失)")
        return 1

    # ================= A. API 存在性 =================
    for seg in (seg_a, seg_diag, seg_c):
        code = strip_comments(seg)
        for bogus, why in BOGUS.items():
            if bogus in code:
                fail("出现 %s —— %s" % (bogus, why))
        # 段内出现的 TextKit / superview 成员必须都在白名单内。
        # ★`frame` **不在这个列表里**: `frame` 是 UIView 上的**属性名**,
        #   不是接收者 —— `frame.size.width` 里的接收者是 `self`。
        #   本轮第一版把 frame 当接收者查成员, 报"frame 上没有成员 size"
        #   ×5 —— 判据自己造了个不存在的类型。⇒ 纪律: **白名单里的键必须是
        #   真正的接收者表达式**, 属性名不算。
        for m in re.finditer(
                r"\b(textContainer|layoutManager|textStorage|superview)"
                r"\.([a-zA-Z_]\w*)", code):
            recv, member = m.group(1), m.group(2)
            if recv == "superview":
                allowed = KNOWN["UIView"]
            elif recv == "textContainer":
                allowed = KNOWN["NSTextContainer"]
            elif recv == "layoutManager":
                allowed = KNOWN["NSLayoutManager"]
            else:
                allowed = KNOWN["NSTextStorage"]
            if member not in allowed and not member.startswith("swift_"):
                fail("%s 上没有成员 %r(v51 只应读既有成员)" % (recv, member))
        # `frame` 只允许接 size / bounds 两个成员(UIView 的 CGRect 属性)
        for m in re.finditer(r"\bframe\.([a-zA-Z_]\w*)", code):
            if m.group(1) not in ("size", "bounds", "origin", "minX", "minY",
                                  "maxX", "maxY", "width", "height",
                                  "midX", "midY", "integral", "standardized"):
                fail("CGRect 上没有成员 %r" % m.group(1))

    # ================= B/E. NSLog 变参 =================
    decls = _collect_decls(t)
    tot = opt = ar = 0
    for seg, nm in ((strip_comments(seg_a), "V51-FRAMEPIN"),
                    (strip_comments(seg_diag), "V51-FRAMEPIN-DIAG"),
                    (strip_comments(seg_c), "V51-PROBE")):
        c, o, a = _scan_nslog_args(seg, decls, nm)
        tot += c
        opt += o
        ar += a
    print("  A API 白名单           OK")
    print("  B/E NSLog 变参         %d 个调用, 可选类型 %d, 个数不符 %d"
          % (tot, opt, ar))

    # ================= C. 段内零危险写 =================
    code_a = strip_comments(seg_a)
    # ★这些禁止的对象要用**属性链**形式查, 不能用 `\.origin\s*=` ——
    #   本轮第一版这么写, 结果 `_v51f.origin.x = 16` 根本匹配不到
    #   (中间隔着 `.x`), S1 sabotage 于是"未被拦截", 而 C 组还打印 OK。
    #   这是继 E 组之后的第二次「看起来在跑、实际没钉住」。
    #   ⇒ 正确写法: `\.origin(?:\.\w+)*\s*=` —— 允许中间任意级成员。
    #   ⇒ 纪律: **判据里的正则要拿自己的 sabotage 反着验一遍**,
    #     只信"破坏后变红", 不信"检查代码存在"。
    for pat, why in ((r"textContainer\.size(?:\.\w+)*\s*=", "textContainer 宽高"),
                     (r"\.origin(?:\.\w+)*\s*=", "origin"),
                     (r"\.size\s*=\s*[^=]", "整个 size"),
                     (r"\.size\.height\s*=", "height"),
                     (r"\.size\.height(?:\.\w+)*\s*=", "height"),
                     (r"\bbounds\s*=\s*[^=]", "bounds"),
                     (r"\bbounds(?:\.\w+)*\s*=", "bounds"),
                     (r"\bsuperview:\s*=", "superview")):
        if re.search(pat, code_a):
            fail("V51-FRAMEPIN 段内出现 %s 写入 —— 本版只许改 frame.size.width"
                 % why)
    # C-2: A2 单调判据(只在偏大时写)
    if not re.search(r"if frame\.size\.width > _realW2 \+ 1 \{", code_a):
        got = re.findall(r"if frame\.size\.width[^\n{]*\{", code_a)
        fail("A2 判据不是单调的 `> _realW2 + 1`, 实为 %r —— 纠偏不竞争" % (got or "无",))
    if re.search(r"if frame\.size\.width <", code_a):
        fail("A2 判据出现 `<` —— 本版只纠偏不缩放")
    print("  C 段内零危险写        OK")

    # ================= D. _realW2 可达性 =================
    # 落点(v51 段)与 `_realW2` 声明之间不得有 `func` 边界 —— 跨函数不可见。
    i_decl = t.find("let _realW2 = _realW")
    if i_decl < 0:
        fail("找不到 `let _realW2 = _realW` 声明 —— v18 段结构变了?")
    else:
        i_use = t.find("// [V51-FRAMEPIN]")
        if i_use < 0:
            fail("[V51-FRAMEPIN] 段缺失")
        else:
            between = t[i_decl:i_use]
            if re.search(r"^\s*(?:(?:public|private|internal|fileprivate|open)\s+)?"
                         r"func\s", between, re.M):
                fail("D: 声明与落点之间有 `func` 边界 —— `_realW2` 是局部量, "
                     "跨函数不可见(编译失败)")
            else:
                print("  D _realW2 可达        OK(同函数, 相距 %d 字符)"
                      % (i_use - i_decl))

    if FAILS:
        print("scope BAD(%d 条)" % len(FAILS))
        return 1
    print("scope OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
