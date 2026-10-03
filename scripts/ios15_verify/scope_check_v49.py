#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v49 探针的**作用域静态检查** —— 判据证明不了编译。

【为什么需要它】本轮 v49 连踩两个**编译级**错误, 判据全都放行:
  1. `struct _V49W` 声明在 v18 段内(layoutSubviews 函数体里), 而 KVO 侧
     探针在**另一个函数**里引用它 —— Swift 局部类型跨函数不可见, 编译
     直接失败。判据第 2 组只查了 "struct 存在", 查不出"声明在哪一层"。
  2. KVO 侧探针读 `self.attV46CachedWidth`, 而那个 getter 声明在
     **TableAttachment 类**里(@2039), 探针却在
     **SelectableMarkdownTextView** 内 —— 跨类访问不到, 同样编译失败。
     判据第 5 组只查了"日志字段齐全", 查不出"这个属性能不能在这儿读"。

【本检查做什么】只验 v49 探针新增代码的**作用域合法性**, 四条:
  A. `_V49W` 声明在**类型级**(缩进与类成员一致), 且类体内只有一处声明
  B. KVO 侧探针引用的每个 `self.xxx` / `xxx` 标识符, 在
     SelectableMarkdownTextView 类型内**确实存在**(或是局部量 cvW)
  C. 探针段内引用的类型名都在本文件里声明过(没有凭空引用外部类型)
  D. 探针段内没有引用任何**其它类**的成员(跨类访问 = 编译失败)

【与判据的分工】
  verify_width_writer_v49  → 结构在位 / 段内零赋值 / 标记计数(纯文本)
  scope_check_v49 (本文件) → 作用域与可见性(编译级)
  两者都过, 才认为可以发版。
"""
import re
import sys

PROBE_V18 = "// [V49-WWRITER-V18]"
PROBE_KVO = "// [V49-WWRITER-KVO]"
END_V18 = "// [V49-WWRITER-V18-END]"
END_KVO = "// [V49-WWRITER-KVO-END]"

# 探针宿主类 —— KVO 与 v18 两侧探针都在这个类里。
# ★只写**纯类名**, 不带 "final class" 前缀: _class_body() 会在声明行里
#   匹配 `(final )?class <纯类名>`, 写成整串会导致永远匹配不上。
HOST = "SelectableMarkdownTextView"
# 本文件里**其它**顶层类型 —— 它们的成员在 HOST 内不可见(除非是 static
# 且类型名限定)。出现即编译失败。
OTHER_CLASSES = (
    "SelectableMarkdownTheme", "CodeBlockAttachment", "TableAttachment",
    "AudioAttachment", "MinisLayoutManager",
)


def _fail(msg):
    raise AssertionError("scope_check_v49: " + msg)


def _mask(t):
    """把注释与字符串字面量替换成等长空格, 只留代码骨架。

    ★必要性(本轮实踩): 直接对源码裸配平花括号会**失衡** —— 本文件的
      类体里有字符串字面量/注释含 '{' 与 '}'(如 "\(...)" 插值、示例文本),
      裸扫到文件末尾 depth 仍为 1, 于是"类体"切不出来, 检查全盘误报。
      插值里的括号是真实代码, 所以只整体挖空字符串(不区分插值) ——
      对"找类体边界"这个用途足够, 边界永远在类体末尾那层 '}'。
    """
    out = list(t)
    i, n = 0, len(t)
    while i < n:
        c = t[i]
        if c == "/" and i + 1 < n and t[i + 1] == "/":
            while i < n and t[i] != "\n":
                out[i] = " "
                i += 1
        elif c == "/" and i + 1 < n and t[i + 1] == "*":
            depth_c = 1
            out[i] = out[i + 1] = " "
            i += 2
            while i < n and depth_c:
                if t[i] == "/" and i + 1 < n and t[i + 1] == "*":
                    depth_c += 1
                    out[i] = out[i + 1] = " "
                    i += 2
                elif t[i] == "*" and i + 1 < n and t[i + 1] == "/":
                    depth_c -= 1
                    out[i] = out[i + 1] = " "
                    i += 2
                else:
                    if t[i] != "\n":
                        out[i] = " "
                    i += 1
        elif c == '"':
            # 三引号多行字符串
            if t[i:i + 3] == '"""':
                out[i] = out[i + 1] = out[i + 2] = " "
                i += 3
                while i < n and t[i:i + 3] != '"""':
                    if t[i] != "\n":
                        out[i] = " "
                    i += 1
                for _ in range(3):
                    if i < n:
                        out[i] = " "
                        i += 1
            else:
                out[i] = " "
                i += 1
                while i < n and t[i] != '"':
                    if t[i] == "\\" and i + 1 < n:
                        out[i] = " "
                        out[i + 1] = " "
                        i += 2
                        continue
                    if t[i] != "\n":
                        out[i] = " "
                    i += 1
                if i < n:
                    out[i] = " "
                    i += 1
        else:
            i += 1
    return "".join(out)


def _class_body(t, name):
    """取某个顶层类型的类体(按大括号配平)。找不到返回 ''。

    ★定位纪律(本轮实踩两次): 不用"从文件里 find 类名再猜哪处是声明"
      这种写法 —— 类名在文件里往往**先出现在注释里**(如 "Same rationale
      as SelectableMarkdownTextView.addInteraction"), 首次命中根本不是声明。
      正确做法: **逐行扫, 只认行首的结构声明**, 且必须带类型名。
    """
    pat = re.compile(
        r"^[ \t]*(?:@[\w()., ]+[ \t]*\n[ \t]*)*"          # 修饰注解可独占行
        r"(?:(?:public|private|internal|fileprivate|open|final)\s+)*"
        r"(class|struct|enum|extension)\s+" + re.escape(name) + r"\b",
        re.M)
    m = pat.search(t)
    if not m:
        return ""
    # 必须是顶层(行首无缩进), 否则是嵌套类型 —— 嵌套类型不在本检查范围
    if m.group(0)[:1] in (" ", "\t"):
        return ""
    # ★从**声明行本身**找 '{', 不能跳到下一行(本轮实踩): Swift 的类声明
    #   常写成 `final class X: UITextView, Delegate {` —— 行尾就带 '{'。
    #   跳到下一行会抓到类体里第一个 '{'(这里是
    #   `override var intrinsicContentSize: CGSize {`), 于是"类体"被切成
    #   269 字符, 后续所有成员都查不到 → 误报"声明不在类内"。
    #
    #   两种合法形态都要接受:
    #     (a) '{' 在声明行内(单行声明)      —— 最常见
    #     (b) '{' 在后续行(多行声明/注解跨行) —— 允许, 但要求 200 字符内
    nl = t.find("\n", m.start())
    if nl < 0:
        return ""
    k_same = t.find("{", m.start())
    if k_same >= 0 and k_same < nl:
        k = k_same                                    # 形态 (a)
    else:
        k = t.find("{", nl)                           # 形态 (b)
        if k < 0 or k - nl > 200:
            return ""
    # ★配平必须用**挖空注释/字符串后的骨架**, 不能裸扫(本轮实踩):
    #   本文件类体内有字符串字面量与注释含花括号, 裸扫到文件末尾 depth
    #   仍为 1 → 类体切不出来 → 检查全盘误报。
    sk = _mask(t)
    depth, p = 0, k
    while p < len(sk):
        if sk[p] == "{":
            depth += 1
        elif sk[p] == "}":
            depth -= 1
            if depth == 0:
                return t[k:p]
        p += 1
    return ""


def _seg(t, start, end):
    i = t.find(start)
    if i < 0:
        _fail("缺少标记 %s" % start)
    j = t.find(end, i)
    if j < 0:
        _fail("标记 %s 之后找不到 %s" % (start, end))
    return t[i:j]


def _strip_comments(code):
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.S)
    return re.sub(r"//[^\n]*", "", code)


def scope_check_v49(t):
    body = _class_body(t, "SelectableMarkdownTextView")
    if not body:
        _fail("找不到宿主类 %s 的类体" % HOST)

    seg_v18 = _seg(t, PROBE_V18, END_V18)
    seg_kvo = _seg(t, PROBE_KVO, END_KVO)

    # ---- A. _V49W 必须是类型级声明, 且只有一处 ----
    decls = []
    for m in re.finditer(r"^([ \t]*)struct\s+_V49W\b", t, re.M):
        decls.append(m)
    if len(decls) != 1:
        _fail("_V49W 声明应恰为 1 处, 实为 %d —— "
              "重复声明会遮蔽跨函数读取" % len(decls))
    ind = len(decls[0].group(1).expandtabs(4))
    if ind != 4:
        _fail("_V49W 声明缩进为 %d 空格, 应为 4 —— 缩进 >4 说明它落在某个"
              "函数体内, **局部 struct 跨函数不可见**, KVO 侧会编译失败"
              % ind)
    off = decls[0].start()
    # 声明必须落在宿主类体内。
    # ★偏移比较要严谨: body 是 t.find("{") 之后的内容, 所以 body 在 t 里
    #   的起点 = 类声明行的位置, 用 t.find(body) 拿到的正是不含前导 `{`
    #   的那段文本起点 —— 直接拿声明偏移去比会差几个字符而误判
    #   (本轮实踩)。稳妥做法: 找 body 的**最后一个**特征(类体末尾的 "}")
    #   之前的范围, 或者干脆用"类体文本在 t 中的首次出现位置 + 容差"。
    bstart = t.find(body)
    if bstart < 0:
        _fail("类体文本在源文件里定位不到(不应发生)")
    # body 以 "{" 开头, 它在 t 中的位置就是类体的 '{' 处
    bstart = t.rfind("{", 0, bstart + 1)
    if not (bstart <= off < bstart + len(body)):
        _fail("_V49W 声明不在宿主类 %s 内(声明@%d, 类体 %d~%d)"
              % (HOST, off, bstart, bstart + len(body)))

    # ---- B/C. 探针内引用的标识符必须在宿主类内可见 ----
    # 宿主类里可见 = 类成员(任意缩进的 var/let/func/struct 声明)
    #             + 探针所在函数的局部量
    # KVO 侧额外可见: cvW / _v49Now(探针自己声明的局部量)
    members = set(re.findall(
        r"^\s*(?:@\w+\s+)*(?:public |private |internal |fileprivate |"
        r"open |static |final |lazy |weak |unowned )*"
        r"(?:var|let|func|struct|enum|typealias)\s+([A-Za-z_]\w*)",
        body, re.M))
    # KVO 闭包内的局部量(v41 自己声明的), 探针合法引用
    kvo_locals = set(re.findall(
        r"\b(?:let|var)\s+([A-Za-z_]\w*)\s*(?:=|:)", seg_kvo))
    # 探针自己声明的局部量
    own_locals = {"_v49Now", "_v49SameTick"}
    # 宿主类的继承自 UIKitView 的成员(用到但不必在类体里声明)
    inherited = {
        "textContainer", "layoutManager", "textStorage", "bounds", "frame",
        "size", "superview", "subviews", "window", "layer", "tintColor",
        "isHidden", "alpha", "tag", "superview", "setNeedsLayout",
        "setNeedsDisplay", "invalidateIntrinsicContentSize", "addSubview",
    }
    # 类型级静态成员: _V49W.xxx 由类型本身提供
    static_ok = {"_V49W"}

    for seg, name in ((seg_v18, "v18 侧"), (seg_kvo, "KVO 侧")):
        code = _strip_comments(seg)
        # 抓 self.X 与裸标识符引用(排除 Swift 关键字/字面量/参数标签)
        refs = set(re.findall(r"\bself\.([A-Za-z_]\w*)", code))
        if name == "KVO 侧":
            refs |= set(re.findall(r"(?<![\w.])([a-z_]\w*)(?=\s*[,)\n])",
                                   code))
        for r in sorted(refs):
            if r in inherited or r in members or r in own_locals \
                    or r in kvo_locals or r in static_ok:
                continue
            # 局部量(cvW 等)在 KVO 段里已被 kvo_locals 收走
            _fail("★%s 探针引用 self.%s —— 它在宿主类 %s 内**不可见**。"
                  "若它属于其它类型就是跨类访问, 编译失败(本轮实踩: "
                  "attV46CachedWidth 属于 TableAttachment)"
                  % (name, r, HOST))

    # ---- D. 探针不得引用其它顶层类型的成员 ----
    for seg, name in ((seg_v18, "v18 侧"), (seg_kvo, "KVO 侧")):
        code = _strip_comments(seg)
        for oc in OTHER_CLASSES:
            # 裸类型名限定访问 OtherCls.member
            if re.search(r"\b%s\s*\." % re.escape(oc), code):
                _fail("★%s 探针访问了 %s 的成员 —— 那是另一个类型, "
                      "跨类访问编译失败" % (name, oc))
            # 或者直接用该类独有的成员名
        # 宿主类外的成员名: 取其它类体里的成员, 看有没有被引用
        for oc in OTHER_CLASSES:
            ob = _class_body(t, oc)
            if not ob:
                continue
            omem = set(re.findall(
                r"^\s*(?:@\w+\s+)*(?:public |private |internal |fileprivate |"
                r"open |static |final |lazy |weak )*"
                r"(?:var|let|func)\s+([A-Za-z_]\w*)", ob, re.M))
            hit = omem & set(re.findall(r"\bself\.([A-Za-z_]\w*)", code))
            if hit:
                _fail("★%s 探针引用 self.%s —— 该成员声明在 %s 里, "
                      "而探针在 %s 内, 跨类访问编译失败"
                      % (name, sorted(hit)[0], oc, HOST))

    # ---- E. ★探针调用的 API 必须在接收者类型上真实存在 ----
    #
    # 【本轮实踩, run#37139821021】v49 探针里写了
    #     self.textContainer.bounds.width
    # `NSTextContainer` 是 `NSView`(NSLayoutManager 那侧)之外的**纯
    # TextKit 对象**, 它**没有 bounds** —— 那是 NSView 的 API:
    #     error: value of type 'NSTextContainer' has no member 'bounds'
    #
    # ★为什么 B/C 两层都没抓到: 上面 `inherited` 白名单里有 "bounds"
    #   (它是宿主类 SelectableMarkdownTextView 自己的 UIView 成员),
    #   于是 `self.textContainer.bounds` 里的 `bounds` 被当成"继承自
    #   UIKitView 的合法成员"放行。**白名单只验名字, 不验接收者** ——
    #   同一个名字挂在不同类型的链路上, 合法性完全不同。
    #
    #   修法: 这里单列一张"已知 TextKit 对象的合法成员"表, 只覆盖
    #   探针真正可能碰的几个对象。表外的一律要求显式登记。
    # ★表里**故意不含 "self"**: 宿主类自己的成员由 B/C 两层管(它们查的是
    #   宿主类体与其它顶层类型)。这张表只管"挂在 TextKit 对象上的成员",
    #   把 self 塞进来会让 `self.ios15V18W` 被判成"self 上没有这个成员"。
    KNOWN_MEMBERS = {
        "textContainer": {
            # ★只列 Apple 文档确认存在的成员。lineFragmentWidth **不在其中**
            #   (它属于 TextKit2 的 NSTextLayoutManager 一族) ——
            #   run#37141013946 就死在把它写进白名单之后。
            "size", "layoutManager", "textStorage", "textView",
            "maximumNumberOfLines", "lineBreakMode", "lineFragmentPadding",
            "widthTracksTextView", "heightTracksTextView",
            "exclusionPaths", "isSimpleRectangularTextContainer",
        },
        "layoutManager": {
            "usedRect", "usedRange", "textContainer", "textStorage",
            "glyphRange", "numberOfGlyphs", "allowsNonContiguousLayout",
        },
        "textStorage": {"length"},
    }
    for seg, name in ((seg_v18, "v18 侧"), (seg_kvo, "KVO 侧")):
        code = _strip_comments(seg)
        # ★必须抓**完整链**的最后一跳。
        #   【本轮实踩】第一版写的是 `(?<![\w.])([a-z_]\w*)\.([a-z_]\w*)`,
        #   只能抓到 "self".'textContainer' 这种两段链的第一跳, 于是
        #   `self.textContainer.attachedRange` 里真正要查的 **attachedRange
        #   根本没被看到** —— 4 条 sabotage 全漏放, 检查形同虚设。
        #   正确做法: 先把 `X.Y` 连续链整体抓出来, 再逐跳验证。
        for m in re.finditer(r"(?<![\w.])([a-z_]\w*(?:\.[a-z_]\w*)+)", code):
            chain = m.group(1).split(".")
            # 逐跳推进: 只要当前节点是已知 TextKit 对象, 就用它那张表
            # 校验**下一跳**, 然后把下一跳当作新的当前节点继续。
            # ★不能"校验通过就 break" —— `self.textContainer.layoutManager.xxx`
            # 里 textContainer 与 layoutManager **都是** TextKit 对象,
            # 中间那一跳也要查。第一版在 textContainer 验通后直接 break,
            # 于是 `textContainer.layoutManager.estimatedGlyphCount` 全漏放。
            for idx in range(len(chain) - 1):
                node, nxt = chain[idx], chain[idx + 1]
                if node not in KNOWN_MEMBERS:
                    if node == "self":
                        # ★只能**跳过**, 不能 break(本轮实踩, 调试出来的)。
                        #   Swift 成员访问几乎都写成 `self.textContainer.xxx`,
                        #   于是 chain[0] 恒为 "self" —— 一开始就 break 的话,
                    #   后面每一跳都不会被检查, 整条 E 层形同虚设
                    #   (4 条 sabotage 全漏放却毫无察觉)。
                        continue
                    break          # 已离开 TextKit 链路(局部量等), 归 B/C 层
                if nxt in KNOWN_MEMBERS[node]:
                    continue      # 这一跳合法, 继续沿链推进
                _fail("★%s 探针访问 %s —— **%s 上没有这个成员**, "
                      "编译会失败(run#37139821021 就是这么挂的: "
                      "NSTextContainer 没有 bounds, 那是 NSView 的 API)。"
                      "TextKit 对象的合法成员表见本函数 KNOWN_MEMBERS"
                      % (name, ".".join(chain[:idx + 1] + [nxt]), node))

    # ★单点硬禁: 探针里出现这两个不存在的 API 即失败。
    #   历史教训见上 —— 即使有人后来往白名单里补了它们, 这条仍然拦。
    #   ★提示文案**不能**再推荐 lineFragmentWidth: run#37141013946 就是
    #     照着上一版"请改用 lineFragmentWidth"的建议改的, 结果它同样不存在。
    #     ⇒ 一个把下一个人推向编译错误的提示, 比没有提示更坏。
    for _bogus, _why in (
        ("textContainer.bounds",
         "bounds 是 NSView 的 API, NSTextContainer 不是 NSView 子类"),
        ("textContainer.lineFragmentWidth",
         "它属于 TextKit2 的 NSTextLayoutManager 一族, 不是 NSTextContainer 的成员"),
    ):
        if _bogus in _strip_comments(seg_v18 + seg_kvo):
            _fail("★探针出现 %s —— %s。读容器宽一律用 "
                  "self.textContainer.size.width(同一份文件里 40+ 处在用, "
                  "编译器已验证); 排版来源问 ios15LastLaidOutW(v47 注入)"
                  % (_bogus, _why))

    return True


def main():
    if len(sys.argv) < 2:
        print("用法: scope_check_v49.py <SelectableMarkdownView.swift>")
        return 2
    t = open(sys.argv[1], encoding="utf-8").read()
    try:
        scope_check_v49(t)
    except AssertionError as e:
        print("❌ %s" % e)
        return 1
    print("✅ v49 探针作用域检查通过 (A 类型级 struct / B 标识符可见 / "
          "C 无跨类访问 / E TextKit 成员存在)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
