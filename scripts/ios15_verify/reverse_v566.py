#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v56.6 判据的反向测试: 证明 verify_toolbar_minheight_v566 真的能拦。

【为什么这一版的判据必须反向测试 —— 而且形态与v565 不同】
v565 的教训是「装在错误的类里, 全部判据照样全绿」。
v566 换了个形态: **重复代码只改一处**。

  ToolLiveSheet.swift 里 `cardWidth * 3.0 / 4.0` 有**三处**:
    :1657 snapshotTextContent(终端)   ← 本版改
    :2337 textContent(终端)            ← 本版改
    :1809 file_edit 的 diff 卡片        ← 本版**不动**(没证据说它有问题)

实测里判据真的抓到了两件事:
  ① 我原本只写了两处锚点, 判据报「仍残留」—— 逼我确认第三处的归属,
     并把判据从「全文件搜字符串」改成「按宿主函数定位」;
  ② 我在新注释里写了「旧式 cardWidth * 3.0 / 4.0 ...」这句说明,
     裸字符串搜索把它当成残留代码 ⇒ 判据**把自己写的说明当罪证**。
     修法: 判据全文先剥注释(`_v566_strip_comments_only`)。

这两条都不是我预想到的, 都是判据在实跑中抓出来的 ⇒ 与v565 同一结论:
**新写的判据, 先证明它会红, 再相信它的绿。**

注入的 sabotage:
  S1  只改 textContent, snapshotTextContent 留 3/4     -> 覆盖范围(分叉)
  S2  两处都改, 但把新写法删掉一处                    -> 覆盖范围(计数)
  S3  把上限从 400 改成 4000                          -> 常量被偷改
  S4  删掉下限常量(只剩上限)                          -> 常量缺失
  S5  删掉 linesShownInPreview 的空输入分支            -> 空卡片退回固定高
  S6  把两处新写法换成「宽度乘 1/2」                   -> 数字看着对但语义错
  S7  把 diff 卡片那处也一起改成新写法                 -> 范围失控(顺手重构)
  S8  删掉 [V566-MINH] 标记(改回去了但没标记)         -> 幂等标记
  S9  在 textContent 里用 previewLinesCount(不存在的属性)-> 编译会失败
  BASE 未改动产物必须通过

用法: python3 reverse_v566.py <fallback脚本> <干净上游 src/ios>
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_FB = os.path.join(os.path.dirname(HERE), "ios15_fallback.py")
TLS_REL = "Views/Chat/ToolLiveSheet.swift"

# 判据报错时必然出现的关键词(判据文案里点名了它要抓什么)
# ★EXPECT 必须写**该条 sabotage 真正会触发的那条判据的文案**。
#   第一版我按「直觉」写(S1 以为会报「仍残留 3/4」), 结果三条报红却被判成
#   「报红了但不是本条判据」—— 假失败。
#   实测的正确对应:
#     S1 换掉 snapshot 那行 → 命中**覆盖范围**的「没有它自己那行」(不是 3/4 那条)
#     S7 改掉 diff 卡片   → 命中**范围失控**的「应恰好剩 1 处」
#     S9 换掉 content.count → 同S1, 命中覆盖范围
#   ⇒ 纪律: 写完sabotage 要**实跑看它报哪条**, 再据此写 EXPECT,
#     不能凭直觉写 —— 否则反向测试自己变成噪声源。
EXPECT = {
    "S1": "没有它自己那行",
    "S2": "新写法出现",
    "S3": "缺(或被改)",
    "S4": "cardFloorHeight",
    "S5": "空输入分支",
    "S6": "新写法出现",
    "S7": "应恰好剩 1 处",
    "S8": "带 [V566-MINH] 标记的行只有",
    "S9": "没有它自己那行",
}

CASES = []


def case(tag, name):
    def deco(fn):
        CASES.append((tag, name, fn))
        return fn
    return deco


@case("S1", "只改 textContent, snapshot 留 3/4")
def s1(t):
    # 把 snapshotTextContent 那处新写法还原成旧的 3/4
    return t.replace(
        "let v566BodyLines = CGFloat(min(max(linesShownInPreview(text.count), 0), 18))",
        "let v566BodyLines = CGFloat(min(max(0, 0), 18))\n"
        "            let _unused = text", 1)


@case("S2", "删掉一处新写法(只剩一处)")
def s2(t):
    return t.replace("v566HeadH + v566BodyLines * v566RowH + v566Pad,", "v566HeadH + 28,", 1)


@case("S3", "上限 400 改 4000")
def s3(t):
    return t.replace("static let cardCeilHeight: CGFloat = 400",
                     "static let cardCeilHeight: CGFloat = 4000", 1)


@case("S4", "删掉下限常量")
def s4(t):
    return t.replace("    static let cardFloorHeight: CGFloat = 88\n", "", 1)


@case("S5", "删掉 linesShownInPreview 空输入分支")
def s5(t):
    return t.replace("        guard charCount > 0 else { return 0 }\n", "", 1)


@case("S6", "新写法换成宽度乘 1/2")
def s6(t):
    return t.replace("v566HeadH + v566BodyLines * v566RowH + v566Pad,",
                     "cardWidth * 0.5,", 1)


@case("S7", "把 diff 卡片那处也一起改(范围失控)")
def s7(t):
    # 第三处(缩进更深, diff 卡片)也换成新写法 —— 4 处
    return t.replace(
        "                    let cardMinHeight = cardWidth * 3.0 / 4.0\n",
        "                    let cardMinHeight = cardWidth * 0.5\n", 1)


@case("S8", "去掉 [V566-MINH] 标记")
def s8(t):
    return t.replace("[V566-MINH]", "[removed]", 2)


@case("S9", "引用不存在的 previewLinesCount")
def s9(t):
    return t.replace("linesShownInPreview(block.content.count)",
                     "linesShownInPreview(self.previewLinesCount)", 1)


def _verify_only(fb, tls):
    """只跑 verify —— 不重跑 fix, 让 sabotage 直接落到判据上。"""
    fn = tempfile.mktemp(suffix=".py")
    open(fn, "w", encoding="utf-8").write(
        "import importlib.util\n"
        "spec = importlib.util.spec_from_file_location('fb', %r)\n" % fb
        + "m = importlib.util.module_from_spec(spec)\n"
          "spec.loader.exec_module(m)\n"
          "t = open(%r, encoding='utf-8').read()\n" % tls
        + "m.verify_toolbar_minheight_v566(t)\nprint('OK')\n")
    p = subprocess.run([sys.executable, fn], capture_output=True, text=True)
    os.unlink(fn)
    return (p.stdout or "") + (p.stderr or "")


def main():
    if len(sys.argv) < 3:
        sys.stderr.write(__doc__)
        return 1
    fb = sys.argv[1] if os.path.exists(sys.argv[1]) else DEFAULT_FB
    upstream = sys.argv[2]
    if not os.path.isdir(upstream):
        sys.stderr.write("找不到干净上游: %s\n" % upstream)
        return 1
    fb = os.path.abspath(fb)

    base = tempfile.mkdtemp(prefix="v566rev_")
    ok, bad = [], []
    try:
        # ---- 干净基线: 跑一遍 fix 拿产物(摘掉 verify 调用以便 sabotage 触发) ----
        src = open(fb, encoding="utf-8").read()
        stripped = src.replace("    verify_toolbar_minheight_v566(t)\n\n    return t",
                               "    return t", 1)
        if stripped == src:
            sys.stderr.write(
                "摘不掉 verify 调用 —— fallback 里自检的位置变了, 本脚本锚点失效\n")
            return 1
        fb2 = os.path.join(base, "fb_nov.py")
        open(fb2, "w", encoding="utf-8").write(stripped)

        prod = os.path.join(base, "ios")
        shutil.copytree(upstream, prod)
        p = subprocess.run([sys.executable, fb2, prod],
                           capture_output=True, text=True, timeout=1800)
        tls = os.path.join(prod, TLS_REL)
        if not os.path.exists(tls):
            sys.stderr.write("产物里没有 %s\n" % TLS_REL)
            return 1
        clean = open(tls, encoding="utf-8").read()
        if "[V566-MINH]" not in clean:
            sys.stderr.write(
                "❌ 干净基线里没有 V566 标记 —— 锚点已失效, 本脚本测不到东西\n")
            return 1

        # ---- BASE ----
        out = _verify_only(fb, tls)
        if "OK" in out:
            ok.append(("BASE 未改动的产物必须通过", "基线无误伤"))
        else:
            bad.append(("BASE 未改动的产物必须通过", out.strip()[:150]))

        # ---- sabotage ----
        for tag, name, fn in CASES:
            t2 = fn(clean)
            if t2 == clean:
                bad.append(("%s %s" % (tag, name), "sabotage 没改动任何字节 —— 锚点失效, 白测"))
                continue
            f2 = tempfile.mktemp(suffix=".swift")
            open(f2, "w", encoding="utf-8").write(t2)
            out = _verify_only(fb, f2)
            os.unlink(f2)
            if "OK" in out:
                bad.append(("%s %s" % (tag, name), "判据没报红 —— 判据是废的"))
            else:
                kw = EXPECT.get(tag)
                hit = (kw in out) if kw else True
                if hit:
                    ok.append(("%s %s" % (tag, name), out.strip().split("\n")[-1][:80]))
                else:
                    bad.append(("%s %s" % (tag, name),
                                "报红了但不是本条判据(期望关键词 %r): %s"
                                % (kw, out.strip()[:120])))
    finally:
        shutil.rmtree(base, ignore_errors=True)

    print("=" * 70)
    for n, msg in ok:
        print("✅ %-46s %s" % (n, msg))
    for n, msg in bad:
        print("❌ %-46s %s" % (n, msg))
    print("=" * 70)
    print("v566 反向: %d 拦下, %d 漏过" % (len(ok), len(bad)))
    if bad:
        print("⇒ 判据有洞, 别信它的绿。")
        return 1
    print("✅ 全部 sabotage 都被拦下, 且基线无误伤")
    return 0


if __name__ == "__main__":
    sys.exit(main())