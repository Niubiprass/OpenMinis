#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 断言 50 的实现 —— v48 排版宽钉回目标宽。

【为什么单独成文件, 不写在 workflow 的 python3 -c 里】
YAML 双引号标量会把 `\n` **真的转成换行**, 于是
    re.sub(r'//[^\n]*', '', s)
在 YAML 里变成两行, 正则被截断, 报
    ParserError: expected <block end>, but found ']'
(本文件既有教训, 断言 49 早就踩过一次)。想把 `\n` 换成 `chr(10)` 也能绕,
但单行 python 塞三层逻辑(剥注释 + 赋值识别 + 白名单 + 旁路检测)已经
超过可读阈值 —— 断言一旦读不懂, 就没有人敢改。这里落成文件, CI 只调它。

用法: ci_assert_v48.py [产物根目录]   —— 不传则用仓库工作区 src/ios
"""
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
SWIFT = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")

# 段右边界: 用**下游的 v28 标记**, 不用被测代码自己的闭合花括号。
# 【踩坑 —— 判据曾因此 15/20 条 sabotage 全漏放】v48 的 if 块只有一层,
# 那个闭合花括号恰好紧跟在唯一写入行之后, 段切片在写入行处就截断了,
# 追加在写入行**之后**的破坏(frame/bounds/高度/setSize)全落在段外。
# 教训: 锚点要选在 sabotage 改不到的地方, 否则判据只能证明"第一行没问题"。
PIN = "// [V48-PIN]"
END = "// [IOS15-FIX-RELC v28]"
GUARD = "if _ios15WRegrabbed, abs(textContainer.size.width - _realW2) > 0.5 {"
WRITE = "textContainer.size.width = _realW2"

# 禁几何/高度 —— v13/v34 的"整体缩小"与 v45 的 tvH 成果都在这条线上
FORBID = ("height", "Height", "h", "needH", "newHeight", "lastComputedHeight",
          "ios15LastNeededH", "frame", "bounds", "origin", "_hf", "_needH",
          "_needH39", "sizeToFit", "ios15LastSaneSVFrame")


def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


def _lhs(line):
    m = re.match(r"\s*([\w.]+)\s*(?:=|\+=|-=|\*=|/=)(?!=)", line)
    return m.group(1) if m else None


def main():
    if not os.path.exists(SWIFT):
        print("BAD 产物不存在: %s" % SWIFT)
        return 1
    t = open(SWIFT, encoding="utf-8").read()

    fails = []

    # ---- 1. core: 锚点齐全且顺序为 PIN < 守卫 < v28 ----
    miss = [x for x in (PIN, END, GUARD, WRITE) if x not in t]
    if miss:
        fails.append("core 缺: %s" % "|".join(miss))
        core = "BAD 缺:" + "|".join(miss)
    else:
        i = t.index(PIN)
        j = t.index(END, i)
        g = t.find(GUARD, i)
        if not (i < g < j):
            core = "BAD 顺序 i=%d 守卫=%d j=%d" % (i, g, j)
            fails.append(core)
        else:
            core = "OK"

    # ---- 2. pure: ★白名单 + 禁函数式旁路 ----
    if core == "OK":
        blk = t[t.index(PIN):t.index(END, t.index(PIN))]
        code = strip_comments(blk)
        assigns = []
        for line in code.split("\n"):
            tgt = _lhs(line)
            if tgt:
                assigns.append((tgt, line.strip()))
        bad = [ln for tgt, ln in assigns
               if tgt != "textContainer.size.width"
               or tgt.split(".")[-1] in FORBID]
        # 值必须恰为 _realW2 —— 换宽度来源等于引入第三方宽度
        for tgt, ln in assigns:
            m = re.search(r"=\s*([^=].*?)\s*$", ln)
            if not m or m.group(1).strip() != "_realW2":
                bad.append("值非 _realW2: " + ln)
        # ★setSize 是**函数调用**而非赋值, 只认 `目标=值` 的正则会被它整体绕过
        #   (实测反向 A3 就是这么溜过去的, 段内赋值数变成 0, 判据全绿)
        side = ("setSize(" in code) or bool(
            re.search(r"textContainer\s*\.\s*(?:set[A-Z]|\w+\s*\()", code))
        if len(assigns) != 1 or bad or side:
            pure = "BAD 赋值%d处 违规=%s 旁路=%s" % (len(assigns), bad, side)
            fails.append("pure: " + pure)
        else:
            pure = "OK"
    else:
        pure = "BAD 段不可用"

    # ---- 3. idem: 幂等门 + 复用 v47 + 加法保留 ----
    if core == "OK":
        blk = t[t.index(PIN):t.index(END, t.index(PIN))]
        gate = "abs(textContainer.size.width - _realW2) > 0.5 {" in blk
        reuse = "_ios15WRegrabbed" in blk
        v47 = ("self.ios15LastLaidOutW = _realW2" in t
               and "var ios15LastLaidOutW: CGFloat?" in t)
        q = chr(34)
        keep = all(("NSLog(" + q + g) in t
                   for g in ("[V44-TEXTFRAME]", "[V45-TVHFIX]", "[V46-ATTACH]"))
        marks = (t.count(PIN) == 1 and t.count("// [V47-REWRAP]") == 2
                 and t.count("/// [V47-WSTATE]") == 1)
        if gate and reuse and v47 and keep and marks:
            idem = "OK"
        else:
            idem = ("BAD 幂等门=%s 复用=%s v47=%s 保留=%s 标记=%s"
                    % (gate, reuse, v47, keep, marks))
            fails.append("idem: " + idem)
    else:
        idem = "BAD 段不可用"

    print("core=%s pure=%s idem=%s" % (core, pure, idem))
    if fails:
        for f in fails:
            print("   —— " + f)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
