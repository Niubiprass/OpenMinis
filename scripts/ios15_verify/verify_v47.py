#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v47 正向验证: 证明"统一测宽源"修法真正落进包里。

用法: python3 verify_v47.py [产物根目录]
默认 /tmp/v47run

背景 (minis-2026-10-03 16.log, v46 纯诊断装机实测, 45 条 V46-ATTACH):

  v46 打的四个候选根因, 实测**三个全部排除**:

    D1 缓存未失效   → `attWant == attCached` **45/45**, 缓存新鲜
    D2 探针宽度     → `cachedW` 与 `tcW` 恒差 1.0(389 vs 390), 不是陈旧值
    D3 失效信号     → `attNVI=1` **0/45**, 信号从未置位
    D4 容器被短路   → **真凶, 但机制不同**

  按 len 聚合后的决定性证据:

      len    n   attWant   usedH    needH      tcH    gap
       26    1      74.0    151.5    159.7    151.7    8.2   正常
      266    1     182.0    623.4    631.7    623.7    8.3   正常
      538    1     182.0    814.5    822.7    814.7    8.2   正常
      591    7     182.0    826.5    901.7    893.7   75.2   异常
      680    1     326.0   1192.1   1245.0   1237.0   52.9   异常
      775   33     326.0   1301.5   1354.3   1346.3   52.8   异常

    · `tcH - needH = -8.0` **恒定在全部 7 组** → 容器高度没问题, v45 补高正确
    · `tcH - usedH` 正常组 0.2~0.3, 异常组 67.2/44.9/44.8 → 差的是**空壳**
    · `attWant` 与 gap **不成比例**(182→75.2, 326→52.8) → 不是附件没进排版,
      而是**行数不一致**

  ⇒ 同一段文字在 390(容器宽)与 358(净宽)下排出的行数不同。行碎片停在旧宽,
    而 `needH` 恒按新宽算, 差出的就是空壳 —— 终端框于是画在空壳上, 表现为
    "终端框盖住上面的字"; usedH 随帧摆动则表现为"定时任务字一下有一下没有"。

  根因: `_ios15WRegrabbed` 由 `abs(tcW - _realW2) > 0.5` 决定, 它只表示
  "有没有改过容器宽", 不表示"行碎片有没有按目标宽重排过"。而真正让碎片重排
  的是 `invalidateLayout`。

修法: 新增 `ios15LastLaidOutW` 记住上次排版宽, 与目标宽不等就补一次重排。
**不新增宽度写入点、不碰高度** —— v13/v34 曾因抢宽引起闪屏与整体缩小,
v45 的 tvH 补高已实测有效(debt 全 0)。
"""
import os
import re
import sys

ROOT = sys.argv[1] if len(sys.argv) > 1 else "/tmp/v47run"
MD = os.path.join(ROOT, "src", "ios", "Views", "Chat", "SelectableMarkdownView.swift")
SCRIPT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                       "..", "ios15_fallback.py"))
SCRIPT_SRC = open(SCRIPT, encoding="utf-8").read()

ok = 0
bad = []


def ck(name, cond, detail=""):
    global ok
    if cond:
        ok += 1
    else:
        bad.append(name + ((" :: " + detail) if detail else ""))


if not os.path.exists(MD):
    print("❌ 产物不存在:", MD)
    sys.exit(1)
t = open(MD, encoding="utf-8").read()


def strip_noise(src):
    """剥 Swift 注释与字符串 —— 判"代码里真写了"必须先剥噪声。"""
    out, i, n = [], 0, len(src)
    while i < n:
        c = src[i]
        if c == '"':
            i += 1
            while i < n:
                if src[i] == "\\":
                    i += 2
                    continue
                if src[i] == '"':
                    i += 1
                    break
                i += 1
            out.append('""')
            continue
        if src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
            continue
        if src.startswith("/*", i):
            depth, i = 1, i + 2
            while i < n and depth:
                if src.startswith("/*", i):
                    depth += 1
                    i += 2
                elif src.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    i += 1
            continue
        out.append(c)
        i += 1
    return "".join(out)


# ---- 1. 两处注入点存在 ----
ck("v47 重排判据存在",
   "if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {" in t)
ck("v47 排版宽回写存在", "self.ios15LastLaidOutW = _realW2" in t)
ck("v47 判据把 _ios15WRegrabbed 置真(与既有 invalidateLayout 同一开关)",
   re.search(r"if abs\(\(self\.ios15LastLaidOutW \?\? -1\) - _realW2\) > 0\.5 \{\s*\n\s*_ios15WRegrabbed = true",
             t) is not None)

# ---- 2. 属性声明: 可选类型 + 文档标记 ----
ck("ios15LastLaidOutW 声明为 CGFloat?(初值 nil = 从未排版过)",
   "var ios15LastLaidOutW: CGFloat?" in t)
ck("V47-WSTATE 文档标记唯一",
   t.count("/// [V47-WSTATE]") == 1)

# ---- 3. 位置: _realW2 定义 < 重排判据 < 回写 ----
# 【锚点形态踩坑记录 —— run#37129575066 之死, 两次翻版】
#   本判据的 find 串在 `_realW` 与 `max(200.0, _cvW - 32)` 之间来回改了两轮,
#   两次都是被**错误的基线**骗的 —— 教训比结论重要:
#
#   第一轮: 基线是"旧 v46 产物 + 追加 v47", 锚点恰好对得上 → 本地 28/28 全绿,
#           而 CI 从干净上游重跑时崩在 RuntimeError(锚点失配)。
#   第二轮: 复现时链只跑到 v43 就被我掐了, 拿这份**半截产物**看形态, 见到
#           `max(200.0, _cvW - 32)`(v43-A 刚就地改宽、v34 还没改回去),
#           于是反向把 OLD 锚点也改成 max(...) —— 结果完整链跑完又找不到锚点。
#           **半截产物比错误基线更危险: 它能自洽地通过本地验证, 因为
#           "半截"这件事本身不写在文件里。**
#
#   正确形态是 `let _realW2 = _realW`: v34 又把它从 max(...) 改回了 _realW
#   (见 ios15_fallback.py 里 fix_width_sync_v34 的 NEW)。
#
#   纪律: (1) 基线必须是从干净上游跑完的**完整链**产物;
#         (2) 中间态(任何两版之间)不是产物形态, 判据不能锚在中间态上;
#         (3) 判据锚点要与注入函数的 OLD 锚点**逐字一致** —— 两处不同步就会
#             出现"本地全绿、CI 崩"这种最难查的组合。
_i_w = t.find("let _realW2 = _realW")
_i_chk = t.find("if abs((self.ios15LastLaidOutW ?? -1) - _realW2) > 0.5 {")
_i_set = t.find("self.ios15LastLaidOutW = _realW2")
ck("注入顺序正确 _realW2 < 重排判据 < 回写",
   min(_i_w, _i_chk, _i_set) >= 0 and _i_w < _i_chk < _i_set,
   "w=%d chk=%d set=%d" % (_i_w, _i_chk, _i_set))
# 判据写成"区间包含"而不是"相邻两次 find 比较" —— 后者在有注释行时
# 会因为多出一个 find 而误判(本轮实踩)。真正要保证的是:
# 回写落在 ensureLayout 所在 if 块内部, 且在该块闭合花括号之前。
_i_ens = t.find("layoutManager.ensureLayout(for: textContainer)", _i_chk)
_ck_ok = _i_ens > 0 and _i_ens < _i_set
if _ck_ok:
    _blk_end = t.find("\n            }", _i_set)
    _ck_ok = _blk_end > _i_set
ck("回写在 ensureLayout 之后的同一 if 块内(碎片定型之后才记)", _ck_ok,
   "ens=%d set=%d" % (_i_ens, _i_set))

# ---- 4. ★纯宽度: 不得新增任何宽度写入点 ----
#    v13/v34 曾因抢宽引起闪屏与整体缩小 —— 新增宽度写入点是那条老路。
#
# ★★ 计数必须先于 find(run#118 暴露, 与 ios15_fallback.verify_width_reflow_v47
#    同款修正): _i47/_i47b 是 find() 抓的**前两个**标记。文件里一旦多出第三
#    个 `// [V47-REWRAP]`(反向测试 C3 就干这个), "第二个"会变成那个多出来
#    的, 于是下面的段切片横跨 v48 的钉宽写入, 报出一条与 sabotage 意图无关的
#    "段内出现宽度写入"。判据照样拦住了(不是漏放), 但反向测试的措辞断言
#    对不上, run#118 的断言 52 就被这条假"漏放"顶红。
#    ⇒ 顺序纪律: 先用计数锁死标记集合, 再用 find 取位置。
ck("V47-REWRAP 标记恰好 2 处(多出第 3 个会让下面的 find 抓错段)",
   t.count("// [V47-REWRAP]") == 2,
   "实际 %d 处" % t.count("// [V47-REWRAP]"))
_i47 = t.find("// [V47-REWRAP]")
_i47b = t.find("// [V47-REWRAP]", _i47 + 1)
ck("两个 V47-REWRAP 代码标记都在", _i47 >= 0 and _i47b > _i47)
if _i47 >= 0 and _i47b > _i47:
    # 【v48 起的变化】v48 恰恰**就是**在 v47 判据那一处补写容器宽
    # (log17 实测: v47 只重排不写宽, 于是 ensureLayout 照着 390 重排,
    #  治不了 117pt 空壳)。本判据的立意仍是"**v47 自己**不写宽度",
    #  但段右边界必须止于 V48-PIN —— 否则会把 v48 的写入算成 v47 的。
    # 纪律: 后版扩展了同一段代码时, 前版的"纯度判据"要跟着收边界,
    #  而不是删掉判据(v48 有自己的白名单判据兜底)。
    #
    # ★★ 这条判据曾有**三份副本**(run#37133557819 前后各踩一次):
    #   1) 本文件 verify_v47.py
    #   2) .github/workflows/port-and-build.yml 断言 49 内联的 python3 -c
    #   3) ios15_fallback.py 里 verify_width_reflow_v47 的内嵌校验
    #   三处曾各写各的, 同一个错误要改三遍 —— 而漏掉的那两处是靠
    #   "另一份判据先失败"才没被暴露, 那不是运气。
    #   现在 1)/2) 已落成 scripts/ios15_verify/ci_assert_v47.py(CI 只调它),
    #   3) 也已收边界。**一份判据只能有一处实现。**
    _v48_at = t.find("// [V48-PIN]", _i47)
    _blk1_end = t.find("if _ios15WRegrabbed, textStorage.length > 0 {", _i47)
    if _v48_at > 0 and _blk1_end > 0:
        _blk1_end = min(_blk1_end, _v48_at)
    _blk1 = t[_i47:_blk1_end]
    _i_e = t.find("ios15LastNeededH = _needH", _i47b)
    _blk2 = t[_i47b:_i_e if _i_e > 0 else _i47b + 300]
    _code = strip_noise(_blk1) + "\n" + strip_noise(_blk2)
    for _bad_ in ("textContainer.size.width =", "textContainer.size =",
                  "frame.size.width =", "bounds.size ="):
        ck("v47 新增行内无宽度写入(%s)" % _bad_, _bad_ not in _code)
    # 高度保护: 精确匹配 + 点号链双重命中
    FORB = ("height", "Height", "h", "needH", "newHeight", "lastComputedHeight",
            "ios15LastNeededH", "frame", "_hf", "_needH", "_needH39", "size")
    hits = []
    for _ln in _code.split("\n"):
        _m = re.match(r"\s*([\w.]+)\s*(?:=|\+=|-=|\*=|/=)(?!=)\s*", _ln)
        if not _m:
            continue
        _t = _m.group(1)
        if _t in FORB or _t.split(".")[-1] in FORB:
            hits.append(_t)
    ck("★v47 新增行内无高度写入(v45 成果保护)", not hits, "命中: %s" % hits)
    ck("v47 新增行内无局部计数器(修法不是诊断)",
       not re.search(r"\b_v47\w*\s*=", _code))
    ck("v47 未夹带诊断日志(归因已完成)",
       "NSLog" not in _code)

# ---- 5. 重排签名必须是源码既有、编译验证过的形式 ----
ck("invalidateLayout 签名与 v25-fix2 编译验证形式一致",
   "layoutManager.invalidateLayout(forCharacterRange: NSMakeRange(0, textStorage.length), actualCharacterRange: nil)" in t)

# ---- 6. 幂等性: 重排判据在稳态下不进 if(排完即记, 下帧相等) ----
# 稳态幂等: 回写必须在 `if _ios15WRegrabbed { ... }` 块内 ——
# 若落在块外, 每帧都会命中判据并重排(主线程卡死的老路)。
# 逐行剥掉注释后再判, 避免注释里的字样干扰。
# ---- 6. 稳态幂等: 回写必须在 ensureLayout 之后的同一花括号块内 ----
# 语义就是两件事, 不去匹配具体排版:
#   (a) ensureLayout 出现在回写之前
#   (b) 从 ensureLayout 起往后数, 回写之前不得出现块闭合
# 【为什么不用一条大正则】前四版都在这里栽了: 锚点前缀重复
# (`if _ios15WRegrabbed` vs 上游 `if _ios15WRegrabbed, textStorage.length > 0`)、
# 剥注释留空行、find 抓到错误的那一处 —— 每一次都是**措辞**问题而非代码问题。
# 改成两条独立的坐标比较后, 判据里再没有需要对齐的字符串形态。
_i_ens2 = t.find("layoutManager.ensureLayout(for: textContainer)", _i_chk)
ck("ensureLayout 在回写之前", _i_ens2 > 0 and _i_ens2 < _i_set,
   "ens=%d set=%d" % (_i_ens2, _i_set))
_close_between = t.find("\n            }", _i_ens2)
ck("回写与 ensureLayout 同块(其间无块闭合)",
   _close_between < 0 or _close_between > _i_set,
   "close=%d set=%d" % (_close_between, _i_set))
# 反面: 回写若落在块外, ensureLayout 之后最近的闭合花括号会在回写之前 ——
# 上面那条判的就是这个。稳态下 ios15LastLaidOutW == _realW2, 判据不进 if。

# ---- 5. 重排签名必须是源码既有、编译验证过的形式 ----
ck("invalidateLayout 签名与 v25-fix2 编译验证形式一致",
   "layoutManager.invalidateLayout(forCharacterRange: NSMakeRange(0, textStorage.length), actualCharacterRange: nil)" in t)

# ---- 6. 幂等性: 重排判据在稳态下不进 if(排完即记, 下帧相等) ----
# 稳态幂等: 回写必须在 `if _ios15WRegrabbed { ... }` 块内 ——
# 若落在块外, 每帧都会命中判据并重排(主线程卡死的老路)。
# 逐行剥掉注释后再判, 避免注释里的字样干扰。
# ★剥注释只在**回写点附近**做, 不能整文件剥完再 find ——
#   `if _ios15WRegrabbed {` 在文件里有两处(v47 之前那处条件式重排、v47 附近
#   那处回写), 整文件 find 会抓到**第一处**, 于是判据永远不成立(本轮实踩)。
# 段起点要用**回写之前最近的那个** `if _ios15WRegrabbed {`, 而不是 _i_chk ——

# ---- 7. 加法: v44/v45/v46 必须在 ----
for _k in ('NSLog("[V44-TEXTFRAME]', 'NSLog("[V45-TVHFIX]', 'NSLog("[V46-ATTACH]'):
    ck("保留 %s" % _k, _k in t)

# ---- 8. Swift 符号存在性(编译期才炸的那类, 上轮栽过) ----
for _n, _cond in (
    ("layoutManager 存在(重排调用接收者)", "layoutManager" in t),
    ("ensureLayout(for:) 存在", "ensureLayout(for:" in t),
    ("CGFloat 可用", "CGFloat" in t),
    ("_realW2 复用渲染宽 v34 的改写形态", "let _realW2 = _realW" in t),
):
    ck(_n, _cond)

# ---- 9. v47 两块代码自身闭合(净深度 0) ----
# 【前四版这一条是废判据】算了个 _depth 却没参与判断, 条件写成 `>= 0`
# 恒为真。教训与 v45 反向测试 F1 相同: 判据必须**真的消费**算出来的值。
# v47 净深度不能按"全文"算(整个 Swift 文件因字符串插值/条件编译本就不为 0,
# 与 v46 产物同为 1), 所以只对 v47 自己那两块算。
_blkA = strip_noise(_blk1)
ck("v47 判据块净深度 0",
   _blkA.count("{") - _blkA.count("}") == 0,
   "净 %+d" % (_blkA.count("{") - _blkA.count("}")))
# 回写块的切片右边界是 `ios15LastNeededH = _needH`, 于是段尾会带上外层
# if 的闭合花括号 → 净深度 -1。这**不是缺陷**: v47 在这块只新增了一行赋值,
# 结构上不可能不闭合。所以判据是"剥掉段尾那个外层闭合后为 0"。
_c2 = strip_noise(_blk2).rstrip()
if _c2.endswith("}"):
    _c2 = _c2[:-1].rstrip()
ck("v47 回写块净深度 0(剥掉段尾外层闭合后)",
   _c2.count("{") - _c2.count("}") == 0,
   "净 %+d" % (_c2.count("{") - _c2.count("}")))

print()
print("v47 正向验证: %d 通过, %d 失败" % (ok, len(bad)))
if bad:
    for x in bad:
        print("  ✗", x)
    sys.exit(1)
print("✅ 全部通过")
