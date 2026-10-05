#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reverse_guard_v65.py —— v65 反向验证（10 条 sabotage）。

纪律（docs/verify-discipline.md §16/§17）：
  §16 sabotage 必须**自己证明"它真的破坏了什么"** —— 破坏后 base==改后
       的，必须独立计为空测(voided)，不能算漏过。
  §17 反向必须覆盖"换个名字继续错" —— 只逐字匹配一种写法的判据是假的。

BASE 独立计数，不计入 passed。
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))


def run_verify(root):
    env = dict(os.environ)
    r = subprocess.run(
        [sys.executable, os.path.join(HERE, "verify_guard_v65.py"),
         os.path.join(root, "src/ios/Shared/NSTextContainerSetSizeGuard.m")],
        capture_output=True, text=True, env=env)
    return r.returncode, (r.stdout + r.stderr).strip()


# ---------------- 10 条 sabotage ----------------
def s1_restore_merged_reject(t):
    """把拆开的两段合回「NaN/inf/负 尺寸一个 if 全部丢弃」。

    问: 只做熔断豁免、不拆丢弃分支 —— 判据拦得住吗?
    这正是旧版代码的形态(61 次丢弃 = 卡字)。
    """
    old = re.search(
        r"    if \(!isfinite\(newSize\.width\) \|\| !isfinite\(newSize\.height\)\) \{"
        r".*?\n    \}\n", t, re.S)
    if not old:
        raise AssertionError("锚点1: NaN/inf 硬拒分支没找到")
    merged = ("    if (!isfinite(newSize.width) || !isfinite(newSize.height) ||\n"
              "        newSize.width < 0 || newSize.height < 0) {\n"
              "        gShortCircuitCount += 1;\n"
              "        return;\n"
              "    }\n")
    return t[:old.start()] + merged + t[old.end():]


def s2_put_back_return(t):
    """修正分支内加 return —— 改回「丢弃」语义。

    ★为什么插在修正块**内部**而不是块外:
      插在块外(修正块与 IMP 调用之间)会与合法的风暴熔断 SKIP 分支里的
      return 混在一起, 判据无法区分二者 —— 那不是判据该管的射程。
      插在块内语义完全等价(TextKit 同样收不到修正值), 且无歧义。
    """
    # [v66] 锚点跟着源码改: 旧写法 `newSize.height = fabs(...)` 已被
    # 「fabs + 下界钳制」取代(v65 装机证明旧写法对 height==0 是空操作)。
    old = "            CGFloat _ah = fabs(newSize.height);"
    if old not in t:
        raise AssertionError("锚点2: fabs 修正语句没找到")
    new = ("            newSize.height = fabs(newSize.height);\n"
           "            return;  /* sabotage: 修正后仍丢弃 */")
    t = t.replace(old, new, 1)
    return t


def s3_storm_no_gate(t):
    """熔断退回无条件 —— 恢复「真实排版也计入预算」。"""
    old = ("    if (newSize.height >= 2000.0) {\n"
           "        s->commitCount += 1;\n"
           "        if (s->commitCount > kStormForwardLimit) {\n"
           "            s->stormed = YES;\n"
           "        }\n"
           "    }")
    if old not in t:
        raise AssertionError("锚点3: 哨兵门槛块没找到")
    new = ("    s->commitCount += 1;\n"
           "    if (s->commitCount > kStormForwardLimit) {\n"
           "        s->stormed = YES;\n"
           "    }")
    return t.replace(old, new)


def s4_drop_fabs(t):
    """去掉负高取绝对值 —— 负高原样喂回 TextKit。"""
    # [v66] 锚点跟着源码改: 旧写法 `newSize.height = fabs(...)` 已被
    # 「fabs + 下界钳制」取代(v65 装机证明旧写法对 height==0 是空操作)。
    old = "            CGFloat _ah = fabs(newSize.height);"
    if old not in t:
        raise AssertionError("锚点4: fabs 没找到")
    # ★保留钳制行: 只抽掉 fabs 这一行, 于是精确测「负高不再取绝对值」
    #   这件事(第②层), 而不会先撞上第⑦层的「钳制缺失」。
    return t.replace(old, "            CGFloat _ah = newSize.height;")


def s5_gate_after_commit(t):
    """门槛挪到 commitCount 自增**之后** —— 东西都在位，但顺序让它不生效。

    ★这是 §17「换个写法继续错」的变体: 判据若只查"门槛存在",
      查不出"门槛在自增之后于是拦不住"。
    """
    old = ("    if (newSize.height >= 2000.0) {\n"
           "        s->commitCount += 1;\n"
           "        if (s->commitCount > kStormForwardLimit) {\n"
           "            s->stormed = YES;\n"
           "        }\n"
           "    }")
    new = ("    s->commitCount += 1;\n"
           "    if (s->commitCount > kStormForwardLimit) {\n"
           "        s->stormed = YES;\n"
           "    }\n"
           "    if (newSize.height >= 2000.0) {\n"
           "        /* sabotage: 门槛在自增之后, 已经来不及了 */\n"
           "    }")
    if old not in t:
        raise AssertionError("锚点5: 哨兵门槛块没找到")
    return t.replace(old, new)


def s6_rename_ceiling_literal(t):
    """把 2000.0 换成 2001.0 —— 注释改了常量没同步。"""
    old = "    if (newSize.height >= 2000.0) {"
    if old not in t:
        raise AssertionError("锚点6: 哨兵门槛字面量没找到")
    return t.replace(old, "    if (newSize.height >= 2001.0) {")


def s7_only_one_component(t):
    """只判高度不判宽度 —— 0.0x-8.0 的宽度 0 得不到修正。"""
    old = "    if (newSize.width <= 0 || newSize.height <= 0) {"
    if old not in t:
        raise AssertionError("锚点7: 修正进入条件没找到")
    return t.replace(old, "    if (newSize.height <= 0) {")


def s8_split_into_two_ifs(t):
    """两个分量拆到两个独立 if —— 半吊子修法。"""
    old = "    if (newSize.width <= 0 || newSize.height <= 0) {"
    if old not in t:
        raise AssertionError("锚点8: 修正进入条件没找到")
    return t.replace(old, "    if (newSize.width <= 0) {\n    }\n    if (newSize.height <= 0) {")


def s9_scope_ref_ceiling(t):
    """★引用 kProbeHeightCeiling —— 本轮真实犯过并当场抓住的编译红。

    kProbeHeightCeiling 是函数体内局部 const，V65-STORM 段落引用它
    会编译失败。这条把那个错误固化下来。
    """
    old = "    if (newSize.height >= 2000.0) {"
    if old not in t:
        raise AssertionError("锚点9: 哨兵门槛没找到")
    return t.replace(old, "    if (newSize.height >= kProbeHeightCeiling) {")


def s10_missing_identifier(t):
    """★引用不存在的标识符 —— run#159 的真实错误形态。

    判据全绿（文本在位）但编译红（符号不存在）。
    """
    old = "    if (newSize.height >= 2000.0) {"
    if old not in t:
        raise AssertionError("锚点10: 哨兵门槛没找到")
    return t.replace(old, "    if (newSize.height >= kV65SentinelFloor) {")


def s11_category_member(t):
    """★还原 CI#162(run 37275980272) 的真实编译红。

    实测错误:
        NSTextContainerSetSizeGuard.m:153:51:
        error: no member named 'width' in 'struct CGRect'
      153 |   _w = [UIScreen mainScreen].bounds.width - 32.0;

    ★为什么这条必须固化: v65 推送前我做过 clang 语法+类型检查, **0 error** ——
      因为我自建的桩里给 `CGRect` **补了** width/height 字段(为了好写),
      而真实 SDK 里它们是 CoreGraphics `CGGeometry` **category** 提供的,
      且 UIKit 的模块化导入**不 re-export** 它。
      ⇒ 桩比真实 SDK 宽松 = 假绿(verify-discipline §23)。
      ⇒ 这条判据是**不依赖任何桩**的纯源码检查, 是那盏假绿灯的唯一防线。

    ★★第一版把整段 KVC 换成一行 bounds.width, 结果反向**虽然拦下了**,
      报出来的却是「② 负高修正缺失」—— 它先撞上第②层, **没测到第⑥层本身**。
      那是 S2 的领地, 测⑥等于没测(同 §21/§22.4 的教训)。
      ⇒ 正确形态: **只把兜底那一行改成 category 访问**, KVC 探测段与
        fabs/height 修正全部原样保留, 于是只有第⑥层会红。
    """
    old = "                if (!(_w > 1) || !isfinite(_w) || _w > 1e5) {\n                    _w = 358.0;\n                }"
    if old not in t:
        raise AssertionError("锚点11: 兜底宽度那段没找到")
    bad = ("                if (!(_w > 1) || !isfinite(_w) || _w > 1e5) {\n"
           "                    _w = [UIScreen mainScreen].bounds.width - 32.0;\n"
           "                }")
    return t.replace(old, bad)


def s12_fabs_noop(t):
    """★★还原 v65 装机日志实测的**空操作**（本轮真实缺陷）。

    8.log (17:20:41-55, iOS 15.5 / iPhone13,2) 82507 条:
        size=0.0x0.0 -> 326.0x0.0     ← 前后高度**完全相同**
    ⇒ 实际进入修正分支 2644129 次, 全部 height==0
    ⇒ 根因: 写的是 `newSize.height = fabs(newSize.height)`, 而 fabs(0.0)==0.0
    ⇒ 单容器 14 秒 264 万次: 内存 151.8→624.2MB(+470MB) ⇒ SIGKILL,
      同期主线程 6281ms 卡顿 ⇒ 抖动。抖/卡/崩**同一个根因**。

    ★为什么旧判据 6 层全放过了它: `fabs` 那个写法**语法完全合法**,
      看代码"像不像修好了"的检查一律放行 ⇒ 本项目第七次
      「验证手段骗了自己」的第 7 号形态（判据全绿、编译全绿、药不治病）。
    ⇒ 第 ⑦ 层直接断言"不得把 fabs 结果直接赋回"+"必须有下界钳制"。

    ★只改这一处(保留 fabs 调用本身, 免得先撞上第②层的 fabs 检查),
      于是只有第⑦层会红 —— 拦下 ≠ 测到(同 §21/§22.4)。
    """
    # ★[v68] 锚点改成**只匹配代码本身**, 不匹配注释文字。
    #   原锚点把 `// 0 / -0 / 亚 1pt 一律抬到 1` 这句注释也写死了, 而 v68
    #   把这一行展开成了多行(要读 lastGoodHeight) ⇒ 锚点失配 ⇒
    #   **sabotage 自身空测**(纪律 §16: 空测必须独立计, 不能算漏过)。
    #   ★这本身就是 §17「换个名字继续错」的第四种形态:
    #     **上游改注释, 判据就静默失效** —— 注释是最容易变的部分,
    #     拿它当锚点等于把判据绑在注释上。
    #   修正: 用正则定位「fabs 调用 + 下界钳制」的**代码骨架**, 注释一律不管。
    pat = re.compile(
        r"[ \t]*CGFloat _ah = fabs\(newSize\.height\);\n"
        r"(?:[^\n]*\n)*?"                      # v68 插入的注释与 _prev 取值
        r"[ \t]*if \(!\(_ah > 1\.0\)\) \{\n"
        r"(?:[^\n]*\n)*?"                      # 钳制体(v68 是多行, v66 是单行)
        r"[ \t]*\}\n")
    m = pat.search(t)
    if not m:
        raise AssertionError(
            "锚点12: 「fabs 调用 + 下界钳制」的代码骨架没找到\n"
            "  ★这个锚点必须只匹配代码, 不能匹配注释 —— v68 把钳制体展开成"
            "多行后, 写死注释的锚点会静默空测(§16/§17)。")
    # 整块替换成 v65 的空操作写法: fabs 结果直接赋回(对 height==0 是空操作)
    bad = "            newSize.height = fabs(newSize.height);\n"
    return t[:m.start()] + bad + t[m.end():]


def s13_drop_hardstop(t):
    """★去掉跨 tick 硬闸门 ⇒ 264 万次风暴复现。

    装机实测: 单容器 0x2802b8820 在 14 秒内被喂 2644129 次 0x0。
    per-tick 的 storm-breaker 每换 tick 清零, 而上游 0x0 **每个 tick 都在喂**
    ⇒ 计数永远到不了 40 ⇒ 永不熔断 ⇒ 每次都走 KVC 取值+装箱+转发
    ⇒ 14 秒 +470MB ⇒ 内存压力 ⇒ SIGKILL(闪退); 同期 6281ms 卡顿(抖动)。

    ⇒ 必须有**跨 tick 累加**的 nonPositiveStreak + kNonPositiveHardLimit。
      本用例把它退回 per-tick(跟着 commitCount 一起清零), 模拟"没做这层"。
    """
    old = "    if (_newTick) { s->commitCount = 0; s->stormed = NO; }"
    if old not in t:
        raise AssertionError("锚点13: per-tick 清零那行没找到")
    bad = ("    if (_newTick) { s->commitCount = 0; s->stormed = NO; }\n"
           "    // [S13] 模拟「没做跨 tick 累加」的错误实现\n"
           "    if (_newTick) { s->nonPositiveStreak = 0; }")
    return t.replace(old, bad)



# ---------------- v68: 4 条 sabotage ----------------
def s14_streak_back_inside_gate(t):
    """★把 streak 累加**塞回** per-tick 门槛里 —— 精确复现 v66 的死代码。

    问: 判据能不能识破「累加存在但永远执行不到」?
    这正是 v66/v67b 装机的形态:
      · 197 万次修正 / 11 秒 / 单容器 / 内存 +1.4GB ⇒ SIGKILL
      · 而 NONPOSITIVE-STORM / NONPOSITIVE-HARDSTOP 日志**各 0 次**
    ⇒ 语法合法、编译通过、第 ⑦ 层全绿, 而运行时那行是死代码。
    ★本项目**第八次**「验证手段骗了自己」:
      ⑦层问"streak 会不会被清零"(恒真), 病根是"会不会被累加"(恒假)。
    ⇒ 第 ⑧ 层必须直接断言累加语句的花括号深度为 0。
    """
    old = """        s->nonPositiveStreak += 1;
        if ((s->nonPositiveStreak & 0x3F) == 1) {"""
    if old not in t:
        raise AssertionError("锚点14: streak 累加那行没找到")
    new = ("""        if (s->commitCount > kStormForwardLimit) {
          s->nonPositiveStreak += 1;
        }
        if ((s->nonPositiveStreak & 0x3F) == 1) {""")
    return t.replace(old, new, 1)


def s15_hardstop_back_to_permanent(t):
    """★硬闸门退回 v66 的「永久停止转发」 —— 断内存换来空白。

    问: 判据能不能识破「闸门太狠」?
    v66 写的是 `if (streak > 400) { return; }` —— 命中即**永久**停止。
    后果: 上游持续算崩时该容器再也收不到 setSize ⇒ 高度永久冻结
    ⇒ 屏幕保留一整块旧几何 ⇒ **巨大空白**(v61 刚修掉的症状换个形态回来),
    而且把「上游万一自愈」的可能性一并删掉了。
    ⇒ 第 ⑨ 层必须要求降频游标 + 步长常量。
    """
    old = """        s->nonPositiveSkipTick += 1;
        if (s->nonPositiveSkipTick < kNonPositiveSkipStride) {
            return;   // 本次丢弃: 只丢这一次, 不是永久
        }
        s->nonPositiveSkipTick = 0;   // 本次放行"""
    if old not in t:
        raise AssertionError("锚点15: 降频放行那几行没找到")
    new = """        return;   // [S15] 退回 v66 的永久停止转发"""
    return t.replace(old, new, 1)


def s16_floor_back_to_bare_one(t):
    """★修正值退回**裸 1.0** —— 活锁的燃料。

    问: 判据能不能识破「修正值上游仍然不满意」?
    v66 把 0.0 抬到 1.0 **确实生效了**(日志实测 326.0x1.0), 但:
      197 万次修正的结果**全是同一个值 1.0**
      ⇒ 上游收到 1.0 与收到 0.0 是同一件事(1pt 装不下任何一行, 回报 0 行)
      ⇒ 自反馈回路一秒都没被断掉 ⇒ 活锁 ⇒ 11 秒吃掉 1.4GB
    ★ v65 的病是"修正成和原来一样的值"(空操作);
      v66 的病是"修正成上游仍不满意的值"(活锁) —— 断的位置不同。
    ⇒ 第 ⑨ 层必须要求下界钳制块里出现 lastGoodHeight。
    """
    old = re.search(
        r"            if \(!\(_ah > 1\.0\)\) \{.*?\n            \}\n", t, re.S)
    if not old:
        raise AssertionError("锚点16: 下界钳制块没找到")
    new = "            if (!(_ah > 1.0)) { _ah = 1.0; }   // [S16] 裸 1.0\n"
    return t[:old.start()] + new + t[old.end():]


def s17_drop_goodh_recording(t):
    """★去掉 lastGoodHeight 的**记录**, 让字段永远是 0。

    问: 判据能不能识破「字段存在但没人写」?
    这是 §19「标识符存在 != 可见」的变体 —— 这次是
    「字段存在 != **被赋值**」。字段在 GuardState 里, lastGoodHeight = 0,
    而非正高度的修正值依赖它 ⇒ 每次都退回 1.0 ⇒ 活锁照旧,
    而所有"字段存在"类断言全绿。
    ⇒ 第 ⑨ 层必须检查记录语句本身。
    """
    old = """    if (newSize.height > 0.0 && isfinite(newSize.height) &&
        newSize.height <= kMaxContainerHeight) {
        s->lastGoodHeight = newSize.height;
    }"""
    if old not in t:
        raise AssertionError("锚点17: lastGoodHeight 记录段没找到")
    return t.replace(old, "    // [S17] 不记录 lastGoodHeight(字段永远为 0)", 1)


SABS_V68 = [
    ("S14", "streak 累加塞回 per-tick 门槛(v66 死代码原样)",
     s14_streak_back_inside_gate),
    ("S15", "硬闸门退回永久停止(断内存→换空白)",
     s15_hardstop_back_to_permanent),
    ("S16", "修正值退回裸 1.0(活锁燃料)",
     s16_floor_back_to_bare_one),
    ("S17", "不记录 lastGoodHeight(字段存在但没人写)",
     s17_drop_goodh_recording),
]


SABS = [
    ("S1", "恢复合并式丢弃(NaN/inf/负一个if全丢)", s1_restore_merged_reject),
    ("S2", "修正分支末尾加 return(改回丢弃)", s2_put_back_return),
    ("S3", "熔断退回无条件(真实排版也计费)", s3_storm_no_gate),
    ("S4", "去掉 fabs(负高原样喂回)", s4_drop_fabs),
    ("S5", "门槛挪到自增之后(顺序让它不生效)", s5_gate_after_commit),
    ("S6", "哨兵字面量改 2001(常量与注释不同步)", s6_rename_ceiling_literal),
    ("S7", "只判高度不判宽度(0 宽不修)", s7_only_one_component),
    ("S8", "两分量拆成两个独立 if", s8_split_into_two_ifs),
    ("S9", "引用 kProbeHeightCeiling(作用域外,编译红)", s9_scope_ref_ceiling),
    ("S10", "引用不存在的 kV65SentinelFloor(编译红)", s10_missing_identifier),
    ("S11", "用 CGRect category 成员 bounds.width(CI#162 原样编译红)",
     s11_category_member),
    ("S12", "高度修正退回 fabs(对 0 是空操作,装机 264万次风暴)",
     s12_fabs_noop),
    ("S13", "跨 tick 累加退回 per-tick(风暴永不熔断)",
     s13_drop_hardstop),
] + SABS_V68


def main():
    src_root = sys.argv[1] if len(sys.argv) > 1 else "."
    guard_rel = "src/ios/Shared/NSTextContainerSetSizeGuard.m"
    base = os.path.join(src_root, guard_rel)
    if not os.path.isfile(base):
        print("✗ 找不到 %s" % base)
        return 2
    orig = open(base, encoding="utf-8").read()

    rc, out = run_verify(src_root)
    print("BASE: rc=%d  %s" % (rc, out.splitlines()[-1] if out else ""))
    if rc != 0:
        print("✗ BASE 未通过, 反向无意义(判据自己坏了)")
        return 2
    print("BASE 通过(独立计数, 不计入 passed)\n")

    passed = 0
    caught = 0
    voided = []
    tmp = tempfile.mkdtemp(prefix="v65rev")
    try:
        for name, desc, fn in SABS:
            # --- sabotage 自己必须证明"真的破坏了什么" ---
            try:
                bad = fn(orig)
            except AssertionError as e:
                print("  %-4s ⚠️ 空测(sabotage 自身失败): %s" % (name, e))
                voided.append(name)
                continue
            if bad == orig:
                print("  %-4s ⚠️ 空测(sabotage 没有改动任何东西)" % name)
                voided.append(name)
                continue
            # 独立计数: sabotage 后判据必须失败
            d = os.path.join(tmp, name)
            os.makedirs(os.path.join(d, "src/ios/Shared"), exist_ok=True)
            shutil.copytree(os.path.join(src_root, "src/ios"),
                            os.path.join(d, "src/ios"), dirs_exist_ok=True)
            with open(os.path.join(d, guard_rel), "w", encoding="utf-8") as f:
                f.write(bad)
            rc2, out2 = run_verify(d)
            if rc2 == 0:
                print("  %-4s ❌ 漏过  %s" % (name, desc))
            else:
                caught += 1
                passed += 1
                last = out2.splitlines()[0] if out2 else ""
                print("  %-4s ✅ 拦下  %s" % (name, desc))
                print("        └─ %s" % last[:120])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print("\n反向: %d 拦下 / %d 漏过 / %d 空测" %
          (caught, len(SABS) - caught - len(voided), len(voided)))
    if voided:
        return 3
    if caught != len(SABS):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
