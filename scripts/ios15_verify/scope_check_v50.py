#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v50 编译级作用域检查。

A' 与 C 都在**方法体内注入 Swift 代码**, 而本机没有 swiftc, 编译问题只能
在 CI 装包前拦下。这里查四类编译级风险:

  A. API 存在性 —— 只允许出现编译器已验证存在的 API。
     (v49 教训: 连踩两次 `textContainer.bounds` 与 `.lineFragmentWidth`,
      两次都是"没查证就猜 API 名")

  B. 作用域 —— `TableAttachment.ios15PinnedW` 从 SelectableMarkdownTextView
     跨类写入: 这是**合法**的(static 成员可跨类访问), 但必须确认它写的是
     `TableAttachment.` 而不是裸 `ios15PinnedW`(后者会解析到 self 上的
     某个成员, 编译失败或静默写错地方)。

  C. 段内零危险写 —— v50 两段都不许碰 textContainer 宽度与高度。
     A' 只加一个静态标量, C 只多写一个 CGFloat 属性。

  D. trailing closure 陷阱 —— v42 实踩: 注入段若紧跟在某表达式之后,
     裸 `{ }` 会被 Swift 解析成 trailing closure, 于是段内所有裸引用都要求
     显式 self., 并报 "closure expression is unused"。所以两段都必须用
     `do { }`。
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
    "UIFont": {"systemFont"},
}

# ---- 已知不存在的 API(v49 两次编译失败的化石)----
BOGUS = {
    "textContainer.bounds": "NSTextContainer 没有 bounds(那是 NSView 的)",
    "textContainer.lineFragmentWidth": "它属于 TextKit2 的 NSTextLayoutManager 一族",
    "textContainer.attachedRange": "不存在",
    "layoutManager.estimatedGlyphCount": "不存在",
    "textStorage.glyphCount2": "不存在",
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


def main():
    if len(sys.argv) < 2:
        print("用法: scope_check_v50.py <SelectableMarkdownView.swift>")
        return 3
    md = sys.argv[1]
    if not os.path.isfile(md):
        print("找不到产物: %s" % md)
        return 3
    t = open(md, encoding="utf-8").read()

    # ★段边界一律用**下游稳定锚点**(本轮踩过: 原先给 V50-LAIDW 选的下游标记
    #   `// [IOS15-FIX-RELC v28]` 其实在它**上游** —— 那是 v28 的标记, 位置更靠前。
    #   于是 seg_of 找不到 end, 报的是"段未闭合"这种让人摸不着头脑的错。
    #   ⇒ 选锚点的判据: ① 必须在 begin 之后; ② 属于同一段或紧随其后。
    #      下面每个 end 都紧贴各自的实际段尾。
    # ★end 必须在**被查内容之后**。本轮踩坑: V50-PINW-WRITE 段的 end 一度
    #   选了紧邻其后的 `// [V50-PINW-DIAG]` —— 而那正是本段要查的诊断块,
    #   于是 `pinnedW=` 被切出段外, 报"缺诊断字段"。
    #   ⇒ 选锚点顺序: ① 在 begin 之后; ② 在**本段全部待查内容之后**;
    #      ③ 属于同一段或紧随其后。三条同时满足。
    # ★C 必须按"记忆赋值本体"与"诊断块"**拆成两段**(与 core 判据同构):
    #   诊断块被有意挪到 `ios15LastNeededH = _needH` 之后(为了不落进
    #   v47 的纯度段), 而那行是 v47 的既有**高度**写入 —— 两标记之间
    #   夹着它, 若并成一段, C 组的"段内零危险写"会当场误报。
    #   ★本轮第一次改这里时只把 seg_c 指向诊断块, 结果 C 组
    #   "允许写 ios15LastLaidOutW"这条**失去了被检查的对象**(形同虚设),
    #   而 A/D 两组照常跑、输出照常 OK —— 又是"看起来在跑、实际没钉住"。
    #   ⇒ 两段都要切, 且都要进 A/C/D 三组循环。
    seg_a = seg_of(t, "// [V50-UNIFY]", "// [TableProbeFix]", "V50-UNIFY")
    seg_w = seg_of(t, "// [V50-PINW-WRITE]", "// [V49-WWRITER-V18]", "V50-PINW-WRITE")
    _i_mk = t.find("// [V50-LAIDW]")
    _i_ens = t.rfind("if _ios15WRegrabbed {", max(0, _i_mk - 400), _i_mk)
    if _i_ens < 0:
        fail("V50-LAIDW 本体段起点找不到(ensureLayout 的 if 不在上游 400 字符内)")
        seg_m = ""
    else:
        seg_m = t[_i_ens:t.find("ios15LastNeededH = _needH", _i_ens)]
    seg_c = seg_of(t, "// [V50-LAIDW-DIAG]", "// [V42-LATCH-SET]", "V50-LAIDW")
    if not (seg_a and seg_w and seg_c and seg_m):
        print("  scope BAD(段缺失)")
        return 1

    # ---- A. API 存在性 ----
    for seg in (seg_a, seg_w, seg_m, seg_c):
        code = strip_comments(seg)
        for bogus, why in BOGUS.items():
            if bogus in code:
                fail("探针出现 %s —— %s" % (bogus, why))
        # 三段里出现的 TextKit 成员必须都在白名单内
        for m in re.finditer(r"(?:textContainer|layoutManager|textStorage)\.([a-zA-Z_]\w*)", code):
            recv, member = m.group(0).split(".")
            allowed = KNOWN["NSTextContainer"] if recv == "textContainer" else (
                      KNOWN["NSLayoutManager"] if recv == "layoutManager" else {"length"})
            if member not in allowed and not member.startswith("swift_"):
                fail("%s 上没有成员 %r(v50 只应读既有成员)" % (recv, member))

    # ---- B. 跨类写入必须限定类名 ----
    code_w = strip_comments(seg_w)
    for m in re.finditer(r"^.*ios15PinnedW\s*=.*$", code_w, re.M):
        line = m.group(0)
        if "TableAttachment." not in line:
            fail("跨类写入未限定: %r —— 裸 ios15PinnedW 会解析到 self 上的"
                 "成员, 编译失败或静默写错地方" % line.strip()[:90])
    # 声明必须存在且在 TableAttachment 类内(紧跟 narrowestRealWidth)
    if not re.search(r"nonisolated\(unsafe\) static var ios15PinnedW: CGFloat = 0", t):
        fail("ios15PinnedW 声明缺失或形态不符(须与 narrowestRealWidth 同构)")
    else:
        i_decl = t.find("static var ios15PinnedW")
        i_nrw = t.find("static var narrowestRealWidth")
        if i_nrw < 0 or abs(i_decl - i_nrw) > 2000:
            fail("ios15PinnedW 声明离 narrowestRealWidth 太远(%d 字符) —— "
                 "它必须与既有跨实例宽度通道同处一片" % abs(i_decl - i_nrw))

    # ---- C. 段内零危险写 ----
    # C 段写 ios15LastLaidOutW 是**允许的**(那正是 C 的修复), 但宽度与高度不许碰。
    # ★本体段(seg_m)起点就是 ensureLayout 那个 if —— 而 ensureLayout
    #   **必须**留在 `_ios15WRegrabbed` 里(那是 C1, 由 core 判据查)。
    #   所以这里把它与记忆赋值一起豁免, 否则 C 组会要求删掉 C1 保护的东西,
    #   判据之间自相矛盾(本轮实踩: sab 报 "V50-LAIDW 段内出现 ensureLayout")。
    for name, seg, allow in (
            ("V50-PINW-WRITE", seg_w, ("ios15PinnedW",)),
            ("V50-LAIDW", seg_m, ("ios15LastLaidOutW", "ensureLayout")),
            ("V50-LAIDW-DIAG", seg_c, ("ios15LastLaidOutW",))):
        code = strip_comments(seg)
        body = "\n".join(l for l in code.split("\n")
                         if not any(a in l for a in allow))
        for m in re.finditer(r"textContainer\.size\.(width|height)\s*=", body):
            fail("%s 段内出现 textContainer.size.%s 写入 —— v50 不许新增宽度写入, "
                 "也不许碰高度(v45 成果)" % (name, m.group(1)))
        for bad in ("frame.size", "bounds.size", "frame.origin", "setNeedsLayout",
                    "invalidateLayout", "ensureLayout", "invalidateDisplay"):
            if bad in body:
                fail("%s 段内出现 %s —— v50 只允许写一个 CGFloat/静态标量"
                     % (name, bad))

    # ---- D. trailing closure 陷阱: 注入的 do 块必须完整 ----
    for name, seg in (("V50-PINW-WRITE", seg_w), ("V50-LAIDW", seg_m),
                      ("V50-LAIDW-DIAG", seg_c), ("V50-UNIFY", seg_a)):
        code = strip_comments(seg)
        if code.count("do {") < code.count("NSLog"):
            fail("%s 段内 NSLog 数(%d)多于 do 块数(%d) —— 有 NSLog 没被 do 包住, "
                 "裸 { } 会被 Swift 解析成 trailing closure(v42 实踩: 8 个编译错误)"
                 % (name, code.count("NSLog"), code.count("do {")))
        if code.count("{") != code.count("}"):
            fail("%s 段花括号不配平(左 %d 右 %d)"
                 % (name, code.count("{"), code.count("}")))

    # ---- 诊断字段(装机靠它确认) ----
    # ★这里**必须查原 seg 而不是 strip_comments 后的**: 字段名(如 `laidW=`)
    #   就住在 NSLog 的字符串字面量里, 而 strip_comments 会把字面量替换成 `""`
    #   —— 本轮因此误报三条(判据自己踩的坑)。
    #   ⇒ 分工: 查"代码里有什么"用 strip_comments(避注释假阳性),
    #      查"日志里打什么"用原始段。两者别混。
    for f, seg, nm in (("pinnedW=", seg_w, "V50-PINW"),
                       ("used=", seg_a, "V50-UNIFY"),
                       ("laidW=", seg_c, "V50-LAIDW")):
        if f not in seg:
            fail("%s 段缺诊断字段 %r —— 装机后靠它确认修复是否生效" % (nm, f))

    if FAILS:
        print("  scope BAD(%d 条)" % len(FAILS))
        return 1
    print("  scope OK ✅ v50 编译级检查通过 (A API存在性 / B 跨类限定 / "
          "C 段内零危险写 / D do 块完整)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
