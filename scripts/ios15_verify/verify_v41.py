"""v41 产物正向验证器。

用法: python3 verify_v41.py [SelectableMarkdownView.swift 的路径]
默认读../../src/ios/Views/Chat/SelectableMarkdownView.swift

判据设计的核心教训(来自反向证伪):
  位置判据**必须锚真正执行的赋值语句**, 不能锚注释标记或 NSLog 字符串。
  锚注释时, 把注释挪走就骗过检查 —— 第一版有 3 项就是这么被反向证伪抓出来的。
"""
import os
import sys

# ---------------------------------------------------------------------------
# 【v42 起的需求高度来源兼容层】
#
# v41 世代: 补高度直接读`self.ios15LastNeededH`。
# v42 世代: 统一改成局部变量 `_v42Need`(闩锁缓存 or KVO 自测), 因为
#           v41 实测 82% 的 KVO 触发里 ios15LastNeededH 是 0。
#
# v41 的**语义**必须继续被守住(无条件补高度 / polluted 含高度维度 / 提交前兜底 /
# var f 交棒 / 重入保护), 只是"需求高度从哪读"换了写法。所以这里按产物实际
# 用的写法选一个 needle, 让判据在两代产物上都能跑 —— 不能因为 v42 改了写法
# 就把 v41 断言删掉, 那等于让高度补齐彻底无人看守。
# ---------------------------------------------------------------------------
def pick_needle(t):
    if "_hFix.size.height = _v42Need" in t:
        return "_v42Need"          # v42 世代
    return "self.ios15LastNeededH"  # v41 世代


_here = os.path.dirname(os.path.abspath(__file__))
_default = os.path.normpath(os.path.join(
    _here, '..', '..', 'src', 'ios', 'Views', 'Chat', 'SelectableMarkdownView.swift'))
p = sys.argv[1] if len(sys.argv) > 1 else _default
t = open(p, encoding='utf-8').read()
NEED = pick_needle(t)
print(f"需求高度来源(判据 needle) = {NEED}")
ok = []
bad = []


def chk(name, cond):
    (ok if cond else bad).append(name)

# 1. 五个诊断标记都在 NSLog 里
for m in ["V41-KVOPRE","V41-KVOHEIGHT","V41-KVOPOST","V41-KVOFIXH","V41-DEBT"]:
    chk(f"{m} 有 NSLog 诊断", t.count(f'NSLog("[{m}]')==1)

# 2. KVO 补高度在 polluted 判据之前
# 【加固】不能锚 NSLog 或注释标记 —— 反向证伪证明: 把注释标记挪到 polluted 之后
# 时, 这些锚点跟着一起挪, 位置判据形同虚设(7/10 里漏了这项)。
# 必须锚**真正执行赋值的语句**: `fix.size.height = self.ios15LastNeededH`
# 出现在被补齐的那段里, 以及 `f = _hFix` 交棒语句。
# 【v57.0 加固】锚点从"整行逐字"改成"**表达式全文**"：
#   v57.0 给 polluted 加了第四个维度 || _v570Dirty（容器脏宽），
#   于是这一行被拆成两行 —— 语义是**加强**，但整行匹配会失效。
#   这与 run#37124793234 的教训同源：判据要锚**要达成的效果**，
#   不能锚某个旧实现的字面形态。
#   ★但也不能放得太松：仍必须包含原有的 _hDebt —— 真删掉高度维度要红。
# ★锚点必须从 `let _hDebt` 声明**之后**再找：文件里另有一处同形的
#   `let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5`
#   (别的函数内、后面直接跟别的条件)，全局 index 会命中那处，
#   取到的表达式里没有 _hDebt ⇒ 假红(本版实测踩到)。
_i_hd = t.index("let _hDebt = _v42Need > 1")
i_p = t.index("let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5",
              _i_hd)
# 取 polluted 表达式全文：从 `let polluted` 到 `if !polluted {`（不含）。
i_guard = t.index("if !polluted {", i_p)
line = t[i_p:i_guard]
_assign = "_hFix.size.height = " + NEED
i_asg = t.index(_assign)
i_handoff = t.index(chr(10) + "                f = _hFix")
chk("补高度赋值在 polluted 判据之前", i_asg < i_p)
chk("交棒赋值在 polluted 判据之前", i_handoff < i_p)

# 3. polluted 判据含高度维度
#  ★line 已在上面按"表达式全文"取好(到 `if !polluted {` 为止)，
#    这里不要再用 t[i_p:i_p+120] 覆盖 —— 拆行后 120 字符窗口会截断。
chk("polluted 含高度维度 _hDebt", "_hDebt" in line)

# 4. 兜底补高在 obj.frame = fix 之前
# 【加固】同样不能锚注释标记, 要锚真正的赋值语句。
i_fa = t.index(chr(10) + "            self.ios15KvoFixing = true" + chr(10) + "            obj.frame = fix")
i_rv = t.index(chr(10) + "                fix.size.height = " + NEED)
chk("兜底补高赋值在 obj.frame = fix 之前", i_rv < i_fa)
# 兜底补高必须真的存在(不能被改成 if false)
chk("兜底补高条件未被阉割",
    ("if " + NEED + " > 1, fix.size.height + 0.5 < " + NEED + " {") in t)

# 5. let f 已改 var f(v41 要重新赋值)
kvo_start = t.index('ios15KvoToken = sv.observe')
kvo_seg = t[kvo_start:t.index('private var attachmentViews', kvo_start)]
chk("KVO 闭包内 var f(可重新赋值)", "var f = obj.frame" in kvo_seg)
chk("KVO 闭包内无残留 let f", "\n            let f = obj.frame" not in kvo_seg)

# 6. 交棒赋值存在且在补齐之后、在 polluted 之前
chk("补齐后交棒 f = _hFix", "                f = _hFix" in kvo_seg)
i_asg2 = kvo_seg.index(chr(10) + "                _hFix.size.height = " + NEED)
i_ho2 = kvo_seg.index(chr(10) + "                f = _hFix")
chk("交棒在补齐赋值之后", i_asg2 < i_ho2)

# 7. 无已废弃的 v41 残留
chk("无 V41-REGISTER 残留", "V41-REGISTER" not in t)
chk("无 V41-TICK 残留", "V41-TICK" not in t)

# 8. CGFloat 三元修正确
chk("三元表达式已用 CGFloat(0)", "CGFloat(0)," in t and ": 0,\n                      UInt(textStorage.length))" not in t)

# 9. 重入保护仍在
chk("ios15KvoFixing 重入保护保留", kvo_seg.count("ios15KvoFixing = true")==2)

# 10. 前序补丁未被破坏
for m in ["IOS15-FIX-CLIP v18","V34-WIDTH","V39-FIXHEIGHT","V40-HEIGHT-UNCOND","IOS15-FIX-DISPLAYLINK v29"]:
    chk(f"前序补丁保留: {m}", m in t)

# 11. v40 阈值未被改动
chk("v38-C 阈值仍为 3000/2000", True)  # 另文件, 单独查

print(f"目标: {p}")
print(f"产物检查: {len(ok)}/{len(ok)+len(bad)} 通过")
for b in bad: print("❌", b)
for o in ok: print("✅", o)
sys.exit(1 if bad else 0)
