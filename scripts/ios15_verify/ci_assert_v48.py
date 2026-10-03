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
#
# ★★ 第三次翻版(run#37137912522): 右边界又出事了, 这次是**右边界太宽**。
#   v49 把纯诊断探针插在 `V48-PIN` 段内(钉宽 if 之后、v28 标记之前),
#   而本判据的段是 `[V48-PIN, IOS15-FIX-RELC v28)` —— 于是 v49 探针的
#   三行记忆位写入(self.ios15V18W= / _V49W.v18W= / _V49W.v18Tick=)
#   全被算进 v48 的白名单段, 于是:
#       core=OK pure=BAD 赋值4处 违规=[...] 旁路=False idem=OK
#       ❌ v48 异常
#   而 v49 本身完全合规(它自己的四层判据在 CI 里全绿)。
#
#   ⇒ v48 段的右边界必须**紧贴钉宽 if 的闭合花括号**, 不能用下游的
#     v28 标记。v48 自己的内容就只有那一个 if, 到闭合花括号为止;
#     闭合之后的东西(v28 重排、v49 探针)都不属于 v48。
#   这与"右边界要选在 sabotage 改不到的地方"是同一条纪律的两面:
#     右边界既要**够宽**(容得下 v48 自己的全部代码)、
#     又要**够窄**(容不下别人的代码)。两个方向都栽过。
PIN = "// [V48-PIN]"
END = "// [IOS15-FIX-RELC v28]"
GUARD = "if _ios15WRegrabbed, abs(textContainer.size.width - _realW2) > 0.5 {"
WRITE = "textContainer.size.width = _realW2"
# ★v48 段的**真右界** = V48-PIN 之后**第一个版本号 > 48 的标记**, 现场正则扫。
#   · 切掉 v49/v50/v51… 的任何注入 —— 那些是它们自己的事, 由各自判据管
#   · 保留 v48 if 之后的空间 —— 反向测试 B11 要在那里追加一行合法读取,
#     验证"判据不误伤"。收得太紧(比如收到 if 的闭合花括号)会把那条
#     误判成破坏, 于是 v48 反向测试出现假漏放(本轮实踩)。
#   纯 v48 产物(无更高版本标记)时回退到 v28 标记。
#
# ★★ 这里曾硬编码 `V49_HEAD = "// [V49-WWRITER-V18]"`, 而那是同一个错误
#   的重演: 每来一个新版本就得改一次判据。v50 把
#   `TableAttachment.ios15PinnedW = _realW2` 插在 V48-PIN 与 V49 探针之间
#   (那正是"钉宽同一处同一帧"的位置), 本判据当场报
#       pure=BAD 赋值3处 违规=['TableAttachment.ios15PinnedW = _realW2', ...]
#   而 v50 完全合规。⇒ 硬编码版本号 = 每次加版必漏一次。
#   ⚠️ 本函数、`reverse_v48.py`、`ios15_fallback.verify_width_pin_v48`
#     三处必须与此一致 —— 改一处就是"判据被复制多份"那次的翻版。
_V48_END_RE = re.compile(r"//\s*\[V(?:49|[5-9]\d|\d{3,})[ \-\]]")


def _v48_end(t, i_pin):
    """v48 段的右界位置(不含)。三处副本必须与此一致。"""
    m = _V48_END_RE.search(t, i_pin + len(PIN))
    if m:
        return m.start()
    j = t.find(END, i_pin)
    if j < 0:
        raise SystemExit("BAD 未找到 v48 段右界(既无 V49+ 标记也无 %s)" % END)
    return j


# 禁几何/高度 —— v13/v34 的"整体缩小"与 v45 的 tvH 成果都在这条线上
FORBID = ("height", "Height", "h", "needH", "newHeight", "lastComputedHeight",
          "ios15LastNeededH", "frame", "bounds", "origin", "_hf", "_needH",
          "_needH39", "sizeToFit", "ios15LastSaneSVFrame")


def strip_comments(s):
    s = re.sub(r"/\*.*?\*/", "", s, flags=re.S)
    return re.sub(r"//[^\n]*", "", s)


def _v48_block(t):
    """切出 v48 自己的段。

    ★右边界用 END_NEAR(钉宽 if 的闭合花括号), 不用 END(v28 标记) ——
    run#37137912522 的教训: v49 探针就插在这两者之间, 用 END 会把 v49
    的三行记忆位写入算进 v48 的白名单, 判出 `pure=BAD 赋值4处`,
    而 v49 本身完全合规。详见常量定义处的注释。
    """
    i = t.index(PIN)
    return t[i:_v48_end(t, i)]


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
        # ★右边界用 END_NEAR 而非 END: v49 探针插在 END 之前, 用 END 判顺序
        #   会被 v49 的存在干扰(详见 _v48_block 的 docstring)。
        i = t.index(PIN)
        j = _v48_end(t, i)
        g = t.find(GUARD, i)
        if not (i < g < j):
            core = "BAD 顺序 i=%d 守卫=%d j=%d" % (i, g, j)
            fails.append(core)
        else:
            core = "OK"

    # ---- 2. pure: ★白名单 + 禁函数式旁路 ----
    if core == "OK":
        blk = _v48_block(t)
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
        blk = _v48_block(t)
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
