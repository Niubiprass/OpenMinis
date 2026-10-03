#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v42 反向证伪: 逐个破坏真实代码块, 确认 verify_v42 的每条判据都会 FAIL。

用法:
    python3 reverse_v42.py [产物路径]

纪律(v41 踩过的坑):
  - sabotage 必须破坏**真实执行的代码块**。挪注释不算有效 sabotage ——
    注释不影响功能, 那样只会误判"检查项无效"。
  - 每条判据都要能被至少一个 sabotage 打中; 打不中就是这条判据形同虚设。
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile

SRC = sys.argv[1] if len(sys.argv) > 1 else \
    "/tmp/ci_v42b/src/ios/Views/Chat/SelectableMarkdownView.swift"
HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY = os.path.join(HERE, "verify_v42.py")
N = chr(10)


def run_verify(path):
    r = subprocess.run([sys.executable, VERIFY, path],
                       capture_output=True, text=True)
    return r.returncode, r.stdout


base_rc, base_out = run_verify(SRC)
print("=== 基线(未破坏) ===")
print(base_out.strip().splitlines()[-1])
assert base_rc == 0, "基线就没通过, 后续证伪无意义"

# (sabotage 名, 要替换的原文, 替换后的文字)
SABOTAGE = [
    # 1. 把闩锁改回取 max —— 这是 v42 审查中发现的真实缺陷, 必须能被抓到
    ("闩锁改回取 max(会造假空白)",
     N + "            ios15LatchedNeedH = _needH",
     N + "            if _needH > ios15LatchedNeedH { ios15LatchedNeedH = _needH }"),

    # 2. 键判定去掉 Hash —— 缓存会跨内容误命中
    ("键判定去掉 Hash",
     "               self.ios15LatchHash == self.textStorage.mutableString.hash {",
     "               true {"),

    # 3. 键判定去掉 Len —— 流式增长时误命中
    ("键判定去掉 Len",
     "               self.ios15LatchLen == _v42Len,",
     "               true,"),

    # 4. 键判定去掉宽度容差
    ("键判定去掉宽度容差",
     "               abs(self.ios15LatchW - _v42TCW) < 0.5,",
     "               true,"),

    # 5. 抽掉节流 —— 每帧 sizeThatFits, 加重卡顿
    ("抽掉 120ms 节流",
     "            } else if _v42TCW > 1, _v42Len > 0, self.ios15LatchedNeedH > 1," + N +
     "                      _v42Now - _v42SelfLast < 0.12 {",
     "            } else if false {"),

    # 6. 节流时刻不再刷新 -> 节流退化成永久冻结
    ("自测后不刷新节流时刻",
     "                    _SelfLast.t = _v42Now",
     "                    // sabotage: 不刷新"),

    # 7. 节流基准改成局部变量(每次调用都重置为 0, 节流失效)
    ("节流基准改成局部变量",
     "            struct _SelfLast { static var t: CFTimeInterval = 0 }" + N +
     "            let _v42SelfLast = _SelfLast.t",
     "            let _v42SelfLast = CFTimeInterval(0)"),

    # 8. 节流分支放弃补齐(而不是沿用旧高度)
    ("节流分支放弃补齐",
     N + "                _v42Need = self.ios15LatchedNeedH" + N +
     "                struct _ThrLog",
     N + "                struct _ThrLog"),

    # 9. GATE 挪到三道门之后 —— 门关着时它就是哑的。
    # 【sabotage 设计】必须移动**整个 GATE 块**(含 let/if/NSLog/花括号),
    # 只挪那行 `if !isScrollEnabled...` 的话 GATE 块仍留在原地, 位置关系没真变 ——
    # 这是 v41 踩过的坑: 无效 sabotage 会让人误以为"检查项无效"。
    ("GATE 整块挪到三道门之后",
     N + "            // [V42-GATE] 测量入口三道门的实际取值 — 见函数 docstring「诊断」。" + N +
     "            // 【为什么必须打在这里】要区分\"三道门哪一道没通\", 就必须打在三道门" + N +
     "            // **之前**。挂在里面的诊断在门关着时是哑的 —— v39/v40/v41 连续三次" + N +
     "            // 把诊断挂错层, 连续三次误判成\"代码没跑\"。这条铁律不能再犯。" + N +
     "            {" + N +
     "                struct _GateLog { static var last: CFTimeInterval = 0 }" + N +
     "                let _gn = CACurrentMediaTime()" + N +
     "                if _gn - _GateLog.last > 1.0 {" + N +
     "                    _GateLog.last = _gn" + N +
     "                    let _gCV = findCollectionView()" + N +
     "                    NSLog(\"[V42-GATE] scrollOff=%d cvNil=%d cvW=%.1f latched=%.1f latchLen=%d latchW=%.1f raw=%.1f storageLen=%lu\"," + N +
     "                          isScrollEnabled ? 0 : 1," + N +
     "                          _gCV == nil ? 1 : 0," + N +
     "                          _gCV?.bounds.width ?? -1," + N +
     "                          ios15LatchedNeedH, ios15LatchLen, ios15LatchW," + N +
     "                          ios15LastNeededH," + N +
     "                          UInt(textStorage.length))" + N +
     "                }" + N +
     "            }" + N +
     "            if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {",
     N + "            if !isScrollEnabled, let rCv2 = findCollectionView(), rCv2.bounds.width > 1 {" + N +
     "            // [V42-GATE] 测量入口三道门的实际取值 — 见函数 docstring「诊断」。" + N +
     "            {" + N +
     "                struct _GateLog { static var last: CFTimeInterval = 0 }" + N +
     "                let _gn = CACurrentMediaTime()" + N +
     "                if _gn - _GateLog.last > 1.0 {" + N +
     "                    _GateLog.last = _gn" + N +
     "                    let _gCV = findCollectionView()" + N +
     "                    NSLog(\"[V42-GATE] scrollOff=%d cvNil=%d cvW=%.1f latched=%.1f latchLen=%d latchW=%.1f raw=%.1f storageLen=%lu\"," + N +
     "                          isScrollEnabled ? 0 : 1," + N +
     "                          _gCV == nil ? 1 : 0," + N +
     "                          _gCV?.bounds.width ?? -1," + N +
     "                          ios15LatchedNeedH, ios15LatchLen, ios15LatchW," + N +
     "                          ios15LastNeededH," + N +
     "                          UInt(textStorage.length))" + N +
     "                }" + N +
     "            }"),

    # 10. GATE 不再自己 findCollectionView(诊断值变假)
    ("GATE 借外部变量冒充门值",
     "                    let _gCV = findCollectionView()",
     "                    let _gCV = self.superview"),

    # 11. 闩锁刷新挪到 needH 赋值之前(顺序倒置)
    ("闩锁刷新挪到赋值之前",
     N + "            ios15LastNeededH = _needH" + N +
     "            // [V42-LATCH-SET] 刷新闩锁的键与值。**直接覆盖, 不是取 max** ——",
     N + "            // [V42-LATCH-SET] 刷新闩锁的键与值。**直接覆盖, 不是取 max** ——"),
    # 上面这条拆两步更精确, 这里用另一条实现
    ("闩锁刷新与赋值顺序倒置",
     N + "            ios15LatchedNeedH = _needH" + N +
     "            ios15LatchLen = textStorage.length",
     N + "            ios15LatchLen = textStorage.length"),

    # 12. 赋值点不刷 Len 键(键永远陈旧)
    ("赋值点不刷 Len 键",
     N + "            ios15LatchLen = textStorage.length",
     N + "            // sabotage: 不刷 Len"),

    # 13. 赋值点不刷 W 键
    ("赋值点不刷 W 键",
     N + "            ios15LatchW = textContainer.size.width",
     N + "            // sabotage: 不刷 W"),

    # 14. 赋值点不刷 Hash 键
    ("赋值点不刷 Hash 键",
     N + "            ios15LatchHash = textStorage.mutableString.hash",
     N + "            // sabotage: 不刷 Hash"),

    # 15. 自测改用屏宽而不是排版实际宽(测高与渲染不同宽)
    ("自测改用屏宽",
     "            let _v42TCW = self.textContainer.size.width",
     "            let _v42TCW = UIScreen.main.bounds.width"),

    # 16. 自测不再调 sizeThatFits
    ("自测不再调 sizeThatFits",
     "                let _fh = self.sizeThatFits(",
     "                let _fh = CGFloat(0) + (("),

    # 17. 补齐赋值改回裸读 ios15LastNeededH(统一变量失效)
    ("补齐改回裸读 ios15LastNeededH",
     N + "                _hFix.size.height = _v42Need",
     N + "                _hFix.size.height = self.ios15LastNeededH"),

    # 18. _hDebt 判据改回裸读
    ("_hDebt 改回裸读",
     "            let _hDebt = _v42Need > 1 && f.size.height + 0.5 < _v42Need",
     "            let _hDebt = self.ios15LastNeededH > 1 && f.size.height + 0.5 < self.ios15LastNeededH"),

    # 19. polluted 丢掉 _hDebt 维度(v41 的洞回来了)
    ("polluted 丢掉 _hDebt",
     "            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5 || _hDebt",
     "            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5"),

    # 20. 兜底补高条件被阉割
    ("兜底补高条件被阉割",
     "            if _v42Need > 1, fix.size.height + 0.5 < _v42Need {",
     "            if false {"),

    # 21. 兜底补高不再赋值
    ("兜底补高不再赋值",
     "                fix.size.height = _v42Need",
     "                // sabotage: 不补兜底高度"),

    # 22. _v42Need 初值改成 Int 字面量(Swift 类型冲突)
    ("_v42Need 初值用 Int 字面量",
     "            var _v42Need = CGFloat(0)",
     "            var _v42Need = 0"),

    # 23. 闩锁改成 let(补齐要交棒, 编译失败)
    ("KVO 的 f 改回 let",
     N + "            var f = obj.frame",
     N + "            let f = obj.frame"),

    # 24. 重入保护被破坏
    ("重入保护被破坏",
     "            guard let self = self, !self.ios15KvoFixing else { return }",
     "            guard let self = self else { return }"),

    # 25. 补齐段的写帧保护被抽掉
    ("补齐段写帧保护被抽掉",
     N + "                self.ios15KvoFixing = true" + N +
     "                obj.frame = _hFix" + N +
     "                self.ios15KvoFixing = false",
     N + "                obj.frame = _hFix"),

    # 26. 抽掉 V42-GATE 标记本体
    ("抽掉 V42-GATE 标记",
     'NSLog("[V42-GATE] scrollOff',
     'NSLog("[V42GATE] scrollOff'),

    # 27. 抽掉 V42-THROTTLE 标记
    ("抽掉 V42-THROTTLE 标记",
     'NSLog("[V42-THROTTLE] reuse',
     'NSLog("[V42THROTTLE] reuse'),

    # 28. 抽掉 V42-LATCH 标记
    ("抽掉 V42-LATCH 标记",
     'NSLog("[V42-LATCH] hit',
     'NSLog("[V42LATCH] hit'),

    # 29. 抽掉 V42-MISS 标记
    ("抽掉 V42-MISS 标记",
     'NSLog("[V42-MISS] selfMeasured',
     'NSLog("[V42MISS] selfMeasured'),

    # 30. 破坏 v41 的 KVOHEIGHT 标记(版本回归检测)
    ("破坏 v41 KVOHEIGHT 标记",
     'NSLog("[V41-KVOHEIGHT] fixed',
     'NSLog("[V41-KVOHEIGHT-X] fixed'),
]

orig = io.open(SRC, encoding="utf-8").read()
caught, missed = 0, []

for name, old, new in SABOTAGE:
    if orig.count(old) != 1:
        print(f"  SKIP  {name}: 锚点命中 {orig.count(old)} 次(需恰好 1)")
        missed.append(name + "(锚点异常)")
        continue
    tmp = tempfile.NamedTemporaryFile("w", suffix=".swift",
                                       delete=False, encoding="utf-8")
    tmp.write(orig.replace(old, new, 1))
    tmp.close()
    rc, out = run_verify(tmp.name)
    if rc != 0:
        caught += 1
        fails = [l.strip() for l in out.splitlines() if l.strip().startswith("FAIL")]
        print(f"  抓到  {name}")
        for f in fails[:2]:
            print(f"          {f[6:]}")
    else:
        print(f"  漏掉  {name}   <-- 这条判据形同虚设")
        missed.append(name)
    os.unlink(tmp.name)

print(f"\n反向证伪: {caught}/{len(SABOTAGE)} 全部抓到")
if missed:
    print("漏掉/异常:")
    for m in missed:
        print("  -", m)
sys.exit(0 if not missed else 1)
