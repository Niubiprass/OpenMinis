#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 断言 49 的实现 —— v47 统一测宽源(重排判据)。

【为什么单独成文件 —— run#37133557819 的真实死因】
这一版之前, 断言 49 的三条判据是**内联在 workflow 里的单行 python3 -c**,
而 `verify_v47.py` 里另有一份几乎相同的实现。两份副本:

  - v48 在 v47 判据那一处补写容器宽(log17 实测 v47 只重排不写宽, 治不了
    117pt 空壳), 于是 v47 的"新增行内无宽度写入"判据必然失败。
  - 我在本地修了 `verify_v47.py` 的段右边界(收到 `// [V48-PIN]`),
    **忘了 YAML 里那份副本** —— 本地 28/28 全绿, CI run#37133557819 却死在
    断言 49 的 `纯宽度=BAD textContainer.size.width = _realW2`。

    ❌ 纯宽度 BAD: v47 新增行里混进了宽度或高度写入。前者回退到 v13/v34
       抢宽老路(闪屏/整体缩小), 后者推翻 v45 的 tvH 补高成果(debt 已全 0)

注意这条失败**是正确的**: v48 就是来写这个宽度的。修法不是回退 v48,
也不是删判据, 而是让判据的立意回到"**v47 自己**不写宽度", 并把段右边界
收到 v48 之前。

**教训比修法重要: 一份判据只能有一处实现。**
内联在 YAML 里的判据改起来没有语法检查、没有 IDE 跳转、跑一次要 7 分钟,
于是"本地过了"根本不能证明"CI 会过"。落成文件后 CI 只调它,
判据改一处就够, 本地与 CI 永远同源。

判据逻辑与 verify_v47.py 的第 3/4/6/7 组一致 —— 事实上这个文件就是
verify_v47.py 的可执行子集。

用法: ci_assert_v47.py [产物根目录]  —— 不传则用仓库工作区 src/ios
"""
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "."
SWIFT = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")

# v47 的三处锚点
CHK = "if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {"
SET = "self.ios15LastLaidOutW = _realW2"
DECL = "var ios15LastLaidOutW: CGFloat?"
MARK = "// [V47-REWRAP]"
WSTATE = "/// [V47-WSTATE]"

# ★v48-PIN: v47 第一块的段右边界必须止于此
#   【v48 起的关键修正 —— run#37133557819 之死】
#   原来止于 `if _ios15WRegrabbed, textStorage.length > 0 {`。v48 恰好在
#   v47 判据**这一处**补写容器宽, 于是那条写入被算进了 v47 的段里。
#   纪律: **后版扩展了同一段代码时, 前版的"纯度判据"要跟着收边界,
#   而不是删掉判据**(v48 有自己的白名单判据兜底)。
V48 = "// [V48-PIN]"

# 禁几何/高度 —— v13/v34 的"整体缩小"与 v45 的 tvH 成果都在这条线上
FORB = ("height", "Height", "h", "needH", "newHeight", "lastComputedHeight",
        "ios15LastNeededH", "frame", "bounds", "origin", "_hf", "_needH",
        "_needH39", "size", "sizeToFit")


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

    # ---- 1. core: 锚点齐全 + 顺序 _realW2 < 判据 < 回写 ----
    miss = [x for x in (CHK, SET, DECL, MARK) if x not in t]
    if miss:
        core = "BAD 缺:" + "|".join(miss)
        fails.append("core " + core)
    else:
        # ★锚点形态必须是 `let _realW2 = _realW` —— v34 把它从 max(...) 改回了
        #   _realW。锚在 max(...) 上是 v47 CI 失败第一轮的写法(run#37129575066),
        #   详见 ios15_fallback.py 里 fix_width_reflow_v47 的踩坑注释。
        w = t.find("let _realW2 = _realW")
        c = t.index(CHK)
        s = t.index(SET)
        if min(w, c, s) >= 0 and w < c < s:
            core = "OK"
        else:
            core = "BAD 顺序 w=%d chk=%d set=%d" % (w, c, s)
            fails.append("core " + core)

    # ---- 2. pure: ★新增行内零宽度零高度写入 ----
    i = t.find(MARK)
    j = t.find(MARK, i + 1) if i >= 0 else -1
    if core == "OK" and i >= 0 and j > i:
        end1 = t.find("if _ios15WRegrabbed, textStorage.length > 0 {", i)
        if V48 in t[i:]:
            # v48 恰好在 v47 判据处补写容器宽 → 段右边界收到它之前,
            # 让本判据继续只管"v47 自己写了什么"。
            end1 = min(end1, t.index(V48, i)) if end1 > 0 else t.index(V48, i)
        e2 = t.find("ios15LastNeededH = _needH", j)
        blk1 = t[i:end1] if end1 > i else ""
        blk2 = t[j:e2] if e2 > j else t[j:j + 300]
        code = strip_comments(blk1) + "\n" + strip_comments(blk2)

        hits = []
        for line in code.split("\n"):
            tgt = _lhs(line)
            if not tgt:
                continue
            # 精确匹配 + 点号链双重命中(挡 "textView.size.height" 这类别的接收者)
            if tgt in FORB or tgt.split(".")[-1] in FORB:
                hits.append(line.strip()[:40])
        # (== 比较不是赋值, (?![=]) 已排除 —— 否则 _ios15WRegrabbed 那行
        #  比较会被当成赋值而误伤, 与 v45 反向测试 F1 同一个教训。)
        wbad = [w for w in ("textContainer.size.width =", "textContainer.size =",
                            "frame.size.width =", "bounds.size =") if w in code]
        ctr = re.search(r"\b_v47\w*\s*=", code)
        if hits or wbad or ctr or "NSLog" in code:
            pure = "BAD 宽=%s 高=%s 计数器=%s 日志=%s" % (
                wbad, hits, bool(ctr), "NSLog" in code)
            fails.append("pure " + pure)
        else:
            pure = "OK"
    else:
        pure = "BAD 段不可用"

    # ---- 3. idem: 回写**紧跟** ensureLayout 之后 + 加法保留 + 标记计数 ----
    #
    # ★v50 起这条判据的立意改了(本轮唯一一处"改判据语义"而不是"改边界"):
    #   原判据查的是 `s > e and cl > s`, 即"回写与 ensureLayout **同块**"。
    #   而 v50-C 那个修复的全部内容就是**把回写提出那个 if** ——
    #   v49 实测 laidW=-1 出现 138/143 次, 因为 `_ios15WRegrabbed` 只表示
    #   "容器宽此刻偏离目标宽", 而滑动时容器宽**恰好已经是**目标宽。
    #   ⇒ 判据原来断言的那个形态, 正是导致 138/143 空记忆的那个形态。
    #
    #   改后的红线(更贴合本条判据本来的立意"记忆与重排同处一段"):
    #     ① 回写必须在 ensureLayout **之后**(顺序不能倒);
    #     ② 回写与 ensureLayout 之间的**距离**有界(仍在同一段里, 不是散到别处);
    #     ③ ensureLayout 可以关在 `if _ios15WRegrabbed` 里(那是 C1 要求保留的),
    #        但**回写必须比它更浅或同级** —— 即不得被那个 if 一起吞掉。
    #   ①②③ 合起来正好表达"紧随其后, 且不再被 if 吞掉"。
    #
    #   ★③ 为什么不能写"两者必须同层"(本轮第一版就是这么写的, 当场报错):
    #     ensureLayout **本来就在 if 里**(C1 要求它留在那), 所以它的缩进
    #     必然比函数体深一层。要求"同层"等于要求把 ensureLayout 提出来 ——
    #     那正是 C1 明令禁止的。⇒ 判据把两版红线写成了互相矛盾的形式。
    #     这与"红线在代码里存在 ≠ 被真正执行"同源: **判据本身写错,
    #     表现得却像被测代码违规**。
    #
    #   ★为什么这次可以改判据语义, 而前几次"边界误伤"不许改判据:
    #     边界误伤 = 新代码落进旧判据区间, 旧判据本身**仍然正确**;
    #     本例     = 旧判据断言的那个**形态本身**已被实测证明是病根
    #                (138/143 次记忆为空), 继续保留它就是保留 bug。
    #     ⇒ 判据与产物冲突时先问: 这条红线当初**为了防什么**?
    #       防得住病根的留, 防的恰好是病根的必须改。
    if core == "OK":
        c = t.index(CHK)
        s = t.index(SET)
        e = t.find("layoutManager.ensureLayout(for: textContainer)", c)
        after = (e > 0 and s > e)
        # 两者之间不许隔超过 2000 字符(注释可以长, 但不该长到它们脱节;
        #   实测 v50 产物为 982 —— 判据里的界必须**从产物数出来**)
        near = after and (s - e) < 2000
        # 回写不得比 ensureLayout 更深(否则又被 if 吞了)
        _ls = t.rfind("\n", 0, s) + 1
        _le = t.rfind("\n", 0, e) + 1
        ind_s = len(t[_ls:s]) - len(t[_ls:s].lstrip())
        ind_e = len(t[_le:e]) - len(t[_le:e].lstrip())
        not_nested = ind_s <= ind_e
        same = after and near and not_nested
        q = chr(34)
        keep = all(("NSLog(" + q + g) in t for g in
                   ("[V44-TEXTFRAME]", "[V45-TVHFIX]", "[V46-ATTACH]"))
        # ★标记计数不能写死 1: V47-REWRAP 天然 2 处(判据处 + ensureLayout
        #   回写处两个注入点)。曾写死 1 报 RuntimeError。
        marks = (t.count(MARK) == 2 and t.count(WSTATE) == 1)
        if same and keep and marks:
            idem = "OK"
        else:
            idem = ("BAD 紧随=%s 距离=%s 未被吞=%s 保留=%s 标记=%s"
                    % (after, (s - e) if after else "-", not_nested, keep, marks))
            fails.append("idem " + idem)
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
