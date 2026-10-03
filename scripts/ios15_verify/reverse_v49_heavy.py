#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v49 反向测试 —— **加重文本专项**。

【为什么必须做】v48 是判据全绿、CI 全绿、装机照样错的典型:
  判据证明"代码形状对", 不证明"在重文本场景下行为对"。log18 显示
  tcW=390 的帧仍有 49 条(其中 31 条残缺), 根因是重文本(len=1013 含表格)。

【v49 恰恰是为重文本而生的探针】它在**每一帧**都跑, 所以"重文本下不能
  自我损害"就是本版最该验的事。八条:
    T1 段内零副作用        —— 只写自己的记忆位
    T2 不触发重排          —— 重文本每帧重排 = 终端卡一下(v49 不能换新 bug)
    T3 usedRect 只在节流内  —— ★核心: usedRect 是**惰性**属性, 无条件读
                               每帧都可能触发排版, 重文本下必卡
    T3b 其它惰性读取同理    —— size.height / lineFragmentWidth
    T4 v18 侧无条件执行     —— 纯读+记记忆位, 不该有行为分支
    T5 不碰 v37 钳位链      —— 那是 9 处泄漏防护的历史 trade-off
    T6 v48 钉宽写入点仍在   —— 钉宽失效 = v48 成果作废(加法纪律)
    T7 v47 重排仍在         —— 重排失效 = 碎片与视口脱钩(加法纪律)
    T8 ★探针路径可达性     —— 探针若被包进 `if _ios15WRegrabbed {`,
                               则"碎片已排好"的常态路径反而不经过探针,
                               而那正是 log18 里最该看的帧

用法: reverse_v49_heavy.py <SelectableMarkdownView.swift> [--sab]
"""
import re
import sys

PROBE_V18 = "// [V49-WWRITER-V18]"
PROBE_KVO = "// [V49-WWRITER-KVO]"
END_V18 = "// [V49-WWRITER-V18-END]"
END_KVO = "// [V49-WWRITER-KVO-END]"

# v49 段内**禁写**的标识 —— 与 verify_width_writer_v49 第 3 组同一份口径。
FORBIDDEN = (
    "textContainer", "layoutManager", "textStorage", "cachedLayout",
    "attV46CachedWidth", "attV46CachedTotalH", "ios15LastNeededH",
    "ios15LastLaidOutW", "ios15LastRenderContentW", "ios15LatchW",
    "ios15LatchedNeedH", "ios15LastSaneSVFrame", "_ios15WRegrabbed",
    "_realW2", "bounds", "frame", "origin", "size",
)
ALLOWED_PREFIX = ("ios15V", "_v49", "_V49W")
# ★白名单必须按**最后一段**判断, 不能对完整标识符 startswith(本轮实踩):
#   `_V49W.v18W` 的最后一段是 `v18W`, 对完整串 startswith("_V49W") 为假
#   → 自己的记忆位被当成越界写入, T1 误报。
#   (verify_width_writer_v49 第 3 组用的就是 split(".")[-1], 口径必须一致,
#    否则结构判据与专项判据会互相打脸。)
ALLOWED_EXACT = {"last", "n", "v18W", "v18Tick", "kvoW", "kvoTick", "tick"}


def _seg(t, a, b):
    i = t.find(a)
    if i < 0:
        raise AssertionError("缺少标记 %s" % a)
    j = t.find(b, i)
    if j < 0:
        raise AssertionError("缺少 %s" % b)
    return t[i:j]


def _code(seg):
    return re.sub(r"//[^\n]*", "", re.sub(r"/\*.*?\*/", "", seg, flags=re.S))


def _writes(code):
    out = []
    for ln in code.split("\n"):
        m = re.match(r"\s*(?:let\s+|var\s+)?([\w.]+)\s*(?:=|\+=|-=|\*=|/=)(?!=)", ln)
        if m:
            out.append((m.group(1), ln.strip()))
    return out


def heavy_checks(t):
    res = []
    seg1 = _seg(t, PROBE_V18, END_V18)
    seg2 = _seg(t, PROBE_KVO, END_KVO)
    c1, c2 = _code(seg1), _code(seg2)

    # ---- T1 段内零副作用 ----
    bad = []
    for tgt, ln in _writes(c1) + _writes(c2):
        last = tgt.split(".")[-1]
        if last in ALLOWED_EXACT or last.startswith(ALLOWED_PREFIX):
            continue
        bad.append("%s -> %s" % (tgt, ln[:50]))
    res.append(("T1 探针段内零副作用(只写自己的记忆位)",
                not bad, "; ".join(bad) or "无越界写入"))

    # ---- T2 不触发重排 ----
    hits = [b for b in ("invalidateLayout", "invalidateDisplay",
                        "invalidateSize", "ensureLayout", "setNeedsLayout",
                        "setNeedsDisplay", "setSize", "computeLayout",
                        "invalidateCachedLayout")
            if b in c1 or b in c2]
    res.append(("T2 探针不触发重排/失效(否则重文本每帧重排=新卡顿)",
                not hits, "命中: %s" % hits if hits else "干净"))

    # ---- T3 usedRect 只在节流闸门内 ★核心 ----
    m = re.search(r"if\s+_v49Now\s*-\s*_V49W\.last\s*>\s*0\.5\s*\{", c2)
    if not m:
        res.append(("T3 节流闸门存在(0.5s)", False, "找不到节流 if"))
        return res
    gate = m.start()
    ur = [x.start() for x in re.finditer(r"usedRect", c2)]
    outside = [p for p in ur if p < gate]
    res.append(("T3 usedRect 只在节流命中时读(★重文本每帧重排防线)",
                not outside,
                "闸门外有 %d 处 usedRect" % len(outside) if outside
                else "%d 处 usedRect 全在闸门内" % len(ur)))

    # ---- T3b 其它惰性读取同理 ----
    lazy_out = []
    for s in ("textContainer.size.height", "textContainer.lineFragmentWidth"):
        for x in re.finditer(re.escape(s), c2):
            if x.start() < gate:
                lazy_out.append(s)
    res.append(("T3b 惰性读取(size.height/lineFragmentWidth)也在闸门内",
                not lazy_out,
                "闸门外: %s" % sorted(set(lazy_out)) if lazy_out else "全在闸门内"))

    # ---- T4 v18 侧无条件执行 ----
    # v18 侧在 layoutSubviews 里每帧跑, 只能读+记记忆位。
    # 判据: 它写的东西全在 ALLOWED_PREFIX 内(已由 T1 覆盖),
    # 这里额外确认它**没有**包裹性的 if(有则说明想控制行为)
    wrap = re.findall(r"^\s*if\b", c1, re.M)
    res.append(("T4 v18 侧无包裹性 if(纯读+记忆位, 不控行为)",
                not wrap, "%d 个 if" % len(wrap) if wrap else "无 if"))

    # ---- T5 不碰 v37 钳位链 ----
    v37 = [k for k in ("ios15LastRenderContentW", "_cvW0", "clampWidth",
                       "probeW", "v37") if k in c1 or k in c2]
    res.append(("T5 不读 v37 钳位链(9 处泄漏防护的 trade-off)",
                not v37, "命中: %s" % v37 if v37 else "未触碰"))

    # ---- T6 加法: v48 钉宽写入点必须还在 ----
    # ★不能只数 `textContainer.size.width = _realW2` 的总数(本轮实踩):
    #   该串在产物里出现**两次** —— v18 既有钳宽 + v48 钉宽。把两处一起
    #   改名, 总数仍是 0 <1 才拦得住; 只改一处时总数仍 ≥1 → 漏放。
    #   正确口径: 钉宽那处的**特征**是它在 `// [V48-PIN]` 段内、且被
    #   `if _ios15WRegrabbed, abs(...)` 包着。判它存在 = V48-PIN 段内
    #   能找到那行写入。
    i_pin = t.find("// [V48-PIN]")
    pin_write = 0
    if i_pin >= 0:
        nxt = t.find("// [IOS15-FIX-RELC v28]", i_pin)
        seg = t[i_pin:nxt if nxt > i_pin else i_pin + 4000]
        pin_write = len(re.findall(
            r"textContainer\.size\.width\s*=\s*_realW2\b", seg))
    res.append(("T6 v48 钉宽写入点仍在(钉宽失效=v48 成果作废)",
                pin_write >= 1,
                "V48-PIN 段内钉宽写入 %d 处(总串计数会漏放, 见注释)" % pin_write))

    # ---- T7 加法: v47 重排仍在 ----
    rewrap = t.count("// [V47-REWRAP]")
    ens = t.count("layoutManager.ensureLayout(for: textContainer)")
    res.append(("T7 v47 重排仍在(重排失效=碎片与视口脱钩)",
                rewrap >= 1 and ens >= 1,
                "V47-REWRAP %d, ensureLayout %d" % (rewrap, ens)))

    # ---- T8 ★探针路径可达性 ----
    i_probe = t.find(PROBE_V18)
    if i_pin < 0 or i_probe < 0:
        res.append(("T8 探针在 v18 段无条件路径(加重文本必经过)", False,
                    "锚点缺失"))
    else:
        between = t[t.find("_realW2", i_pin):i_probe]
        between = re.sub(r"//[^\n]*", "", between)
        opens = between.count("{") - between.count("}")
        res.append(("T8 探针在 v18 段无条件路径(加重文本必经过)",
                    opens <= 0,
                    "净开口 %d(>0 ⇒ 探针被包进分支, 常态帧不经过)"
                    % opens if opens > 0 else "无多余开口, 无条件执行"))

    return res



# ══════════════════════════════════════════════════════════════
#  sabotage —— 一个从不失败的检查等于没检查。
#  下面 8 条逐条破坏基线, 每条都必须让 heavy_checks 报 FAIL。
#  H1/H3/H6/H7 是本专项的"存在理由": 惰性读取每帧触发、纯诊断变修复、
#  探针被包进分支导致常态帧不经过、误读 v37 trade-off 链。
# ══════════════════════════════════════════════════════════════

def _sab_cases(t):
    cases = []

    def h1(x):
        # ★最关键: usedRect 提到节流闸门外 → 重文本(len=1013)每帧触发排版
        old = ("                        let _v49Now = CACurrentMediaTime()\n"
               "                        if _v49Now - _V49W.last > 0.5 {")
        new = ("                        let _v49Now = CACurrentMediaTime()\n"
               "                        let _v49ProbeUR = self.layoutManager"
               ".usedRect(for: self.textContainer).height\n"
               "                        if _v49Now - _V49W.last > 0.5 {")
        assert old in x, "H1 锚点失效"
        return x.replace(old, new, 1)
    cases.append(("H1 usedRect 提到节流闸门外(重文本每帧重排)", h1))

    def h2(x):
        old = "                        _V49W.tick &+= 1"
        new = ("                        _V49W.tick &+= 1\n"
               "                        self.layoutManager.invalidateLayout("
               "forCharacterRange: NSMakeRange(0, 0), actualCharacterRange: nil)")
        assert old in x, "H2 锚点失效"
        return x.replace(old, new, 1)
    cases.append(("H2 探针内触发 invalidateLayout", h2))

    def h3(x):
        old = "            _V49W.v18W = textContainer.size.width"
        new = (old + "\n            textContainer.size.width = _realW2")
        assert old in x, "H3 锚点失效"
        return x.replace(old, new, 1)
    cases.append(("H3 探针内新增宽度写入(纯诊断变修复)", h3))

    def h4(x):
        # ★精准打击 V48-PIN 段内那处 —— 裸串 replace(...,1) 改的是**第一处**
        #   (v18 既有钳宽), 钉宽那处完好 → 漏放(本轮实踩)。
        i = x.find("// [V48-PIN]")
        nx = x.find("// [IOS15-FIX-RELC v28]", i)
        seg = x[i:nx]
        new = seg.replace("textContainer.size.width = _realW2",
                          "textContainer.size.width = _realW9", 1)
        assert new != seg, "H4 未命中"
        return x[:i] + new + x[nx:]
    cases.append(("H4 v48 钉宽写入点消失", h4))

    def h5(x):
        old = "layoutManager.ensureLayout(for: textContainer)"
        assert old in x, "H5 锚点失效"
        return x.replace(old, "_v47Noop()", 1)
    cases.append(("H5 v47 重排失效", h5))

    def h6(x):
        old = "            // [V49-WWRITER-V18]"
        new = ("            if _ios15WRegrabbed {\n"
               "            // [V49-WWRITER-V18]")
        assert old in x, "H6 锚点失效"
        return x.replace(old, new, 1)
    cases.append(("H6 探针被包进 if(常态帧不经过探针)", h6))

    def h7(x):
        old = "            _V49W.v18W = textContainer.size.width"
        new = old + "\n            _ = ios15LastRenderContentW"
        assert old in x, "H7 锚点失效"
        return x.replace(old, new, 1)
    cases.append(("H7 探针读 v37 钳位链内部量", h7))

    def h8(x):
        old = "if _v49Now - _V49W.last > 0.5 {"
        assert old in x, "H8 锚点失效"
        return x.replace(old, "if true {", 1)
    cases.append(("H8 去掉 0.5s 节流(每帧都打日志)", h8))

    return cases


def _sabotage(t):
    import subprocess
    import tempfile
    import os
    me = os.path.abspath(__file__)
    bad_n = 0
    for name, fn in _sab_cases(t):
        try:
            b = fn(t)
        except AssertionError as e:
            print("❌ %-46s sabotage 自身失败: %s" % (name[:46], e))
            bad_n += 1
            continue
        if b == t:
            print("❌ %-46s 未改动任何内容" % name[:46])
            bad_n += 1
            continue
        fd, p = tempfile.mkstemp(suffix=".swift")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(b)
            r = subprocess.run([sys.executable, me, p],
                               capture_output=True, text=True, timeout=180)
        finally:
            os.unlink(p)
        if r.returncode == 0:
            print("❌ %-46s ★未被拦截*" % name[:46])
            bad_n += 1
        else:
            hit = [l for l in r.stdout.split("\n") if l.startswith("❌")]
            print("✅ %-46s %s" % (name[:46],
                                  (hit[0][2:74] if hit else "已拦")))
    return len(_sab_cases(t)), bad_n


def main():
    if len(sys.argv) < 2:
        print("用法: reverse_v49_heavy.py <SelectableMarkdownView.swift> [--sab]")
        return 2
    t = open(sys.argv[1], encoding="utf-8").read()
    print("══ v49 加重文本专项 ══")
    try:
        res = heavy_checks(t)
    except AssertionError as e:
        print("❌ %s" % e)
        return 1
    fail = 0
    for name, ok, why in res:
        print("%s %-50s %s" % ("✅" if ok else "❌", name[:50], why[:66]))
        if not ok:
            fail += 1
    print()
    if fail:
        print("❌ 加重文本专项 %d/%d 条未过" % (fail, len(res)))
        return 1
    print("✅ 加重文本专项 %d/%d 条全过" % (len(res), len(res)))

    if "--sab" in sys.argv:
        print()
        print("══ sabotage(逐条破坏, 每条都必须被拦) ══")
        tot, bad = _sabotage(t)
        if bad:
            print()
            print("❌ %d/%d 条 sabotage 未被拦截" % (bad, tot))
            return 1
        print()
        print("✅ %d/%d 条 sabotage 全被拦截" % (tot, tot))
    return 0


if __name__ == "__main__":
    sys.exit(main())
