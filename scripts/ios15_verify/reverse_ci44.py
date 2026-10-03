#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CI 断言 44 的反向证伪: 逐个破坏产物, 确认断言 44 的每条判据都会 FAIL。

用法:
    python3 reverse_ci44.py [产物目录或 swift 路径]

纪律(v41 踩过的坑):
  - 断言本身也要反向证伪。否则"断言恒OK"和"断言有效"分不清。
  - sabotage 必须破坏真实代码, 不能只挪注释。
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WF = os.path.normpath(os.path.join(HERE, "..", "..", ".github", "workflows",
                                  "port-and-build.yml"))
ARG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v42b"
SWIFT_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"
SWIFT = os.path.join(ARG, SWIFT_REL) if os.path.isdir(ARG) else ARG
N = chr(10)


def extract_v42_block():
    """从工作流里抽出断言 44 的 run 片段(连同它依赖的路径上下文)。"""
    y_src = io.open(WF, encoding="utf-8").read()
    i = y_src.index("断言44: v42")
    j = y_src.index('echo "::endgroup::"', i)
    frag = y_src[y_src.rindex("\n", 0, i) + 1: j]
    # 去掉 YAML 块标量的缩进
    lines = []
    for l in frag.splitlines():
        lines.append(l[12:] if l.startswith(" " * 12) else l)
    return "\n".join(lines)


def run_block(workdir):
    frag = extract_v42_block()
    with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False,
                                     encoding="utf-8") as f:
        f.write(frag)
        tmp = f.name
    p = subprocess.run(["bash", tmp], cwd=workdir, capture_output=True, text=True)
    os.unlink(tmp)
    return p.returncode, p.stdout + p.stderr


# ---------- 基线 ----------
base_rc, base_out = run_block(os.path.dirname(SWIFT) + "/../..")
base_rc, base_out = run_block(ARG if os.path.isdir(ARG) else ".")
print("=== 基线(未破坏) ===")
print([l for l in base_out.splitlines() if "v42" in l][-1][:160])
if base_rc != 0:
    print(base_out[-800:])
    sys.exit("基线未通过, 证伪无意义")

SABOTAGE = [
    ("闩锁改回取 max",
     N + "            self.ios15LatchedNeedH = _needH",
     N + "            if _needH > self.ios15LatchedNeedH { self.ios15LatchedNeedH = _needH }"),
    ("键判定去掉 Hash",
     "               self.ios15LatchHash == self.textStorage.mutableString.hash {",
     "               true {"),
    ("键判定去掉 Len",
     "               self.ios15LatchLen == _v42Len,",
     "               true,"),
    ("键判定去掉宽度容差",
     "               abs(self.ios15LatchW - _v42TCW) < 0.5,",
     "               true,"),
    ("抽掉 120ms 节流",
     "            } else if _v42TCW > 1, _v42Len > 0, self.ios15LatchedNeedH > 1," + N +
     "                      _v42Now - _v42SelfLast < 0.12 {",
     "            } else if false {"),
    ("自测后不刷新节流时刻",
     "                    _SelfLast.t = _v42Now",
     "                    // sabotage"),
    ("节流基准改成局部变量",
     "            struct _SelfLast { static var t: CFTimeInterval = 0 }" + N +
     "            let _v42SelfLast = _SelfLast.t",
     "            let _v42SelfLast = CFTimeInterval(0)"),
    ("节流分支放弃补齐",
     N + "                _v42Need = self.ios15LatchedNeedH" + N +
     "                struct _ThrLog",
     N + "                struct _ThrLog"),
    # 【sabotage 设计】必须移动**整个 GATE 块**(从注释到收尾花括号), 只改块内
    # 某一行的话 GATE 的 NSLog 位置根本没动, 位置判据察觉不到 —— 这是无效
    # sabotage, 会让人误以为"位置判据形同虚设"。v41 踩过同型坑。
    # 【sabotage 设计】只把 `do {` 这一行挪到三道门 if 之后 = GATE 块整体移位。
    # 之前硬编码 20 行注释做锚点, 注释一改就锚点异常(跳过) —— 锚点必须选**稳定
    # 且语义关键**的那一行。`do {` 恰好是 CI 编译防御判据盯的那一行。
    ("GATE 整块挪到三道门之后",
     N + "            do {" + N +
     "                struct _GateLog { static var last: CFTimeInterval = 0 }" + N +
     "                let _gn = CACurrentMediaTime()" + N +
     "                if _gn - _GateLog.last > 1.0 {" + N +
     "                    _GateLog.last = _gn" + N +
     "                    let _gCV = self.findCollectionView()",
     N + "            // [GATE-MOVED]"),
    ("GATE 的 do 块被塞到三道门之后",
     N + "            if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {" + N +
     "            // [IOS15-FIX-CLIP v14] 状态判定 + 修复。",
     N + "            do {" + N +
     "                struct _GateLog { static var last: CFTimeInterval = 0 }" + N +
     "                let _gn = CACurrentMediaTime()" + N +
     "                if _gn - _GateLog.last > 1.0 {" + N +
     "                    _GateLog.last = _gn" + N +
     "                    let _gCV = self.findCollectionView()" + N +
     "                    NSLog(\"[V42-GATE] scrollOff=%d cvNil=%d cvW=%.1f latched=%.1f latchLen=%d latchW=%.1f raw=%.1f storageLen=%lu\"," + N +
     "                          self.isScrollEnabled ? 0 : 1," + N +
     "                          _gCV == nil ? 1 : 0," + N +
     "                          _gCV?.bounds.width ?? -1," + N +
     "                          self.ios15LatchedNeedH, self.ios15LatchLen, self.ios15LatchW," + N +
     "                          self.ios15LastNeededH," + N +
     "                          UInt(self.textStorage.length))" + N +
     "                }" + N +
     "            }" + N +
     "            if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {" + N +
     "            // [IOS15-FIX-CLIP v14] 状态判定 + 修复。"),
    ("闩锁刷新挪到赋值之前",
     N + "            ios15LastNeededH = _needH" + N +
     "            //",
     N + "            // [V42-LATCH-SET]"),
    ("赋值点不刷 Len 键",
     N + "            self.ios15LatchLen = self.textStorage.length",
     N + "            // sabotage"),
    ("赋值点不刷 W 键",
     N + "            self.ios15LatchW = self.textContainer.size.width",
     N + "            // sabotage"),
    ("赋值点不刷 Hash 键",
     N + "            self.ios15LatchHash = self.textStorage.mutableString.hash",
     N + "            // sabotage"),
    ("自测改用屏宽",
     "            let _v42TCW = self.textContainer.size.width",
     "            let _v42TCW = UIScreen.main.bounds.width"),
    ("_v42Need 初值用 Int 字面量",
     "            var _v42Need = CGFloat(0)",
     "            var _v42Need = 0"),
    ("抽掉 V42-GATE 标记",
     'NSLog("[V42-GATE] scrollOff',
     'NSLog("[V42GATE] scrollOff'),
    ("抽掉 V42-THROTTLE 标记",
     'NSLog("[V42-THROTTLE] reuse',
     'NSLog("[V42THROTTLE] reuse'),
    ("抽掉 V42-LATCH 标记",
     'NSLog("[V42-LATCH] hit',
     'NSLog("[V42LATCH] hit'),
    ("抽掉 V42-MISS 标记",
     'NSLog("[V42-MISS] selfMeasured',
     'NSLog("[V42MISS] selfMeasured'),

    # ===== 以下 3 条复现 v42 首次推送的真实编译失败(run 37082710565) =====
    ("GATE 退回裸 { }(重现原始编译失败)",
     N + "            do {" + N + "                struct _GateLog",
     N + "            {" + N + "                struct _GateLog"),
    ("GATE 内 findCollectionView 去掉 self.",
     "let _gCV = self.findCollectionView()",
     "let _gCV = findCollectionView()"),
    ("GATE 内属性引用去掉 self.",
     "                          self.ios15LatchedNeedH, self.ios15LatchLen, self.ios15LatchW,",
     "                          ios15LatchedNeedH, ios15LatchLen, ios15LatchW,"),
]

orig = io.open(SWIFT, encoding="utf-8").read()
caught, skipped = 0, []

print("\n=== 逐条破坏 ===")
for name, old, new in SABOTAGE:
    if orig.count(old) != 1:
        print(f"  跳过  {name}: 锚点命中 {orig.count(old)} 次")
        skipped.append(name)
        continue
    bak = SWIFT + ".bak"
    shutil.copy2(SWIFT, bak)
    try:
        io.open(SWIFT, "w", encoding="utf-8").write(orig.replace(old, new, 1))
        rc, out = run_block(ARG if os.path.isdir(ARG) else ".")
        if rc != 0:
            caught += 1
            line = [l for l in out.splitlines() if "❌" in l]
            print(f"  抓到  {name}")
            if line:
                print(f"          {line[0][:170]}")
        else:
            print(f"  漏掉  {name}   <-- 判据形同虚设")
            skipped.append(name)
    finally:
        shutil.move(bak, SWIFT)

print(f"\nCI 断言 44 反向证伪: {caught}/{len(SABOTAGE)} 全部抓到")
if skipped:
    print("漏掉/跳过:")
    for s in skipped:
        print("  -", s)
sys.exit(0 if not skipped else 1)
