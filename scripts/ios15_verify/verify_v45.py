#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v45 正向验证: 抓"V45 补高段缺失"与"越界改了宽度/位置"两类回归。

用法: python3 verify_v45.py [产物根目录]
默认 /tmp/ci_v45

背景 (minis-2026-10-03 13.log, v44 装机实测, 53 条 V44-TEXTFRAME 零例外):

  组合(A/B/C)  次数
    A-C      44      <- 渲染视图自己矮 + attachment 虚高
    --C        9      <- 正常短消息

  **假设 B(补高被 ios15KvoFixing 重入挡掉)彻底排除**:
  `svAfter == needH` 在 53 条里全部成立(1136.3/1136.3、538.0/538.0、
  49.0/49.0 …)。补高从来都成功了, 从来没被挡掉过 —— v41~v44 一直在怀疑
  一个不存在的问题。

  决定性的一行:
      tvH=912.7  svAfter=1136.3  needH=1136.3  tvW=390.0  svW=358.0  len=629
      ↑画字的 UITextView 自己矮了 223.6pt

  真凶是**补错了对象**: v41~v44 一路补的都是 superview 的 sv.frame, 而画字的
  是 UITextView 自己的 self.frame。外层补到 1136.3 了, 里面那个只有 912.7 ——
  多出来的 223.6pt 是空壳(所以"下面一小片空白"), 有字的地方被自己的 bounds
  裁断(所以"字卡一半")。

  44 条样本的 `usedH - tvH` **恒为负**(-8.0 ~ -44.7, 均值 -34.5), 从没转正过。
  随机拉锯必然有正有负, 恒负说明是两个来源各写一次高度的系统性偏差。

本脚本最关键的一条是 `只准动高度`: v45 全部的安全性建立在"只写 size.height"上。
宽度由 v18/v34 经 ios15LastSaneSVFrame 精心维护, v13/v34 都因抢宽引起过闪屏/
整体缩小。一旦 v45 碰了 origin/width 就是在绕过那套状态机, 且装机后一旦闪屏
将无法归因(是 v45 引起的, 还是老问题复发)。宁可让 CI 拦下。
"""
import sys
import os

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/ci_v45"
MD = os.path.join(ROOT, "src/ios/Views/Chat/SelectableMarkdownView.swift")

N = "\n"
ok = 0
bad = []


def ck(name, cond):
    global ok
    if cond:
        ok += 1
    else:
        bad.append(name)


if not os.path.exists(MD):
    print(f"产物不存在: {MD}")
    sys.exit(2)

t = open(MD, encoding="utf-8").read()

# ============ 1. 段落存在性 ============
ck("v45 补高段存在", "// [V45-TVHFIX]" in t)
ck("v45 NSLog 存在", 'NSLog("[V45-TVHFIX]' in t)

# ============ 2. 核心判据字段 ============
# 条件: 只在 tvH 确实矮于 needH 时才补
ck("判据含 tvH < needH",
   "if _v42Need > 1, self.frame.size.height + 0.5 < _v42Need {" in t)
# 写入: 走临时变量, 只改 height
ck("写入走临时变量 _tvf", "var _tvf = self.frame" in t)
ck("只写 _tvf.size.height", "_tvf.size.height = _v42Need" in t)
ck("提交回 self.frame", "self.frame = _tvf" in t)

# ============ 3. 位置: 必须在 v41 补高之后 ============
NEED_A = ("self.ios15LastNeededH = _v42Need", "ios15LastNeededH = _v42Need")
i_need = -1
for a in NEED_A:
    if a in t:
        i_need = t.index(a)
        break
ck("找到 v42 补高赋值点", i_need >= 0)

i_hit = t.find('NSLog("[V41-KVOHEIGHT]')
ck("找到 v41 补高日志", i_hit >= 0)

i_tvh = t.find("// [V45-TVHFIX]")
if i_need >= 0 and i_hit >= 0 and i_tvh >= 0:
    ck("v45 在 v41 补高之后 (need < hit < tvh)",
       i_need < i_hit < i_tvh)
else:
    ck("v45 在 v41 补高之后 (need < hit < tvh)", False)

# ============ 4. 位置: 必须在 v44 诊断段之前 ============
M44 = "// [V44-TEXTFRAME] 见函数 docstring"
ck("找到 v44 诊断段", M44 in t)
if M44 in t and i_tvh >= 0:
    ck("v45 在 v44 之前 (tvh < v44)", i_tvh < t.index(M44))
else:
    ck("v45 在 v44 之前 (tvh < v44)", False)

# ============ 5. ★只准动高度 ============
# 切出 v45 的 do 块本体(从 do { 到同缩进闭合), 只在**代码**里查写操作。
# 注释里提到 width 是允许的(本版注释就解释了为什么不碰宽度), 所以不能
# 全文搜"width" —— 那会把注释和日志格式串一起算进去。
DO = N + "            do {"
i_do = t.find(DO, i_tvh) if i_tvh >= 0 else -1
seg = ""
if 0 < i_do < len(t):
    i_close = t.find(N + "            }", i_do)
    if i_close > 0:
        seg = t[i_do:i_close]
ck("v45 do 块可定位", bool(seg))

# 5a. do 块内禁止出现的写操作(语义: 越界改了非高度维度)
forbidden = {
    "size.width =": "改了宽度",
    "origin.x =": "改了 x",
    "origin.y =": "改了 y",
    "_tvf.size.width": "临时变量动了宽度",
    "_tvf.origin": "临时变量动了 origin",
    "bounds.size": "动了 bounds(与 frame 语义不同, 会连带改滚动内容)",
}
for f, why in forbidden.items():
    ck(f"★未越界: 块内无 {f} ({why})", f not in seg)

# 5b. 显式白名单: 这三行必须都在(证明确实是"只动 height"的完整实现)
ck("判据用 frame.size.height", "self.frame.size.height" in seg)
ck("写入用 size.height", "_tvf.size.height = _v42Need" in seg)
ck("临时变量来自 self.frame", "var _tvf = self.frame" in seg)

# ============ 6. do { } 编译防御 ============
# v42 首次推送的真实失败: 裸块被 Swift 吸成上一个表达式的 trailing closure,
# 报 "closure expression is unused" 并连锁要求显式 self.。这里必须用 do { }。
ck("用 do { } (非裸块)", DO in seg)
# 同缩进闭合必须存在, 否则块没关
if i_do >= 0:
    ck("do 块有同缩进闭合", t.find(N + "            }", i_do) > i_do)

# ============ 7. 显式 self. (闭包内引用规则) ============
for k in ("self.frame.size.height", "self.frame.size.width", "self.frame = _tvf"):
    ck(f"块内显式 self.: {k}", k in seg)

# ============ 8. 节流 ============
ck("0.5s 节流(与 V41-KVOPRE/V44-TEXTFRAME 同周期)",
   "_tvhNow - _TvhLog.last > 0.5" in t)

# ============ 9. 标记唯一 ============
# 注释行里的同名字符串不算, 所以数的是带 NSLog( 的完整标记。
ck("V45-TVHFIX NSLog 标记唯一(恰好 1 次)",
   t.count('NSLog("[V45-TVHFIX]') == 1)

# ============ 10. 幂等性(静态论证) ============
# 条件是 `self.frame.size.height + 0.5 < _v42Need`, 写入后 tvH == needH,
# 于是下一帧条件转 false, 不会反复写。若判据被改成 `<= needH` 就会死循环。
ck("判据用 < (非 <=) 保证幂等",
   "self.frame.size.height + 0.5 < _v42Need {" in t
   and "self.frame.size.height + 0.5 <= _v42Need {" not in t)

# ============ 11. 保留 v44 诊断(不能被顺手删掉) ============
# v45 是行为版, 但 v44 的诊断必须留着 —— 装机后要靠它验证 v45 是否真的把
# tvH 拉到了 needH(tvH == needH 即成功)。删掉就没法归因了。
ck("v44 诊断仍在(装机后要靠它验证 v45 效果)",
   'NSLog("[V44-TEXTFRAME]' in t)

# ============ 12. 花括号平衡 ============
depth = 0
mind = 0
state = None
i = 0
while i < len(t):
    c = t[i]
    nxt = t[i + 1] if i + 1 < len(t) else ""
    if state is None:
        if c == "/" and nxt == "/":
            state = "line"; i += 2; continue
        if c == "/" and nxt == "*":
            state = "block"; i += 2; continue
        if c == '"':
            state = "str"; i += 1; continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            mind = min(mind, depth)
        i += 1
    elif state == "line":
        if c == "\n":
            state = None
        i += 1
    elif state == "block":
        if c == "*" and nxt == "/":
            state = None; i += 2
        else:
            i += 1
    else:
        if c == "\\":
            i += 2
        elif c == '"':
            state = None; i += 1
        else:
            i += 1
ck(f"花括号平衡 (final={depth}, min={mind})", depth == 0 and mind == 0)

print(f"产物检查: {ok}/{ok + len(bad)} 通过")
if bad:
    print("\n失败:")
    for b in bad:
        print(f"  ✗ {b}")
    sys.exit(1)
print("✅ v45 补高补到画字视图上就位 (tvH 欠账修/ 只动高度 / 位置在 v41 补高后 / 幂等)")
