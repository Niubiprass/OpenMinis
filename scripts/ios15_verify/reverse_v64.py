#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reverse_v64 —— v64 反向判据(9 条 sabotage, 直调真判据)。

★与 v63 反向判据的关键差别
  v64 初版的 9 条 sab 全部在问「锁在不在」: 摘标记、摘类体、改 private、
  宿主改泛型、摘复位…… 判据和 sabotage 共享同一个假设 —— "有锁 = 治病"。
  于是 9 条全绿, 而那把锁被装机时间戳证伪(0.35s 窗拦不住 0.4s/0.6s 那两拍)。

  这一版的 9 条改成**问实质**, 每条都对应一种"看起来改了、其实没治病"的形态:

    S1 摘闸门            —— 断掉播种就完事?(不, iOS15 可能把旧值赢回来)
    S2 闸门只算不改写     —— 算出来不用 = 没拦(v53 当年的原样病)
    S3 闸门无条件         —— 退化成 v53/v62 式锁死, 高度永远不更新
    S4 闸门无 tk 豁免     —— 会连真实增长一起拦(误杀)
    S5 播种改回取上一轮   —— 环没断, 只是注释改了
    S6 播种换名字绕过     —— 换个属性名继续取上一轮(判据不能只防一种写法)
    S7 播种不用压缩语义   —— 与 targetSize 声明不一致, 仍可能被污染
    S8 闸门挪到写回之后   —— 拦了也不采纳, 形同虚设
    S9 est 无下限         —— 首帧被锁成 0

★纪律(verify-discipline)
  - 判据输出文案本身是判据: 报错要说清"哪种没治病的形态被放过"
  - 判据宁可漏报不可误报: BASE 必须先独立通过, 且不计入 passed
  - 空测(voided)独立计数, 不许混进 passed
  - sabotage 调**真判据**(fb.verify_deseed_v64), 不复刻判据逻辑
"""
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(REPO, "scripts"))
import ios15_fallback as fb  # noqa: E402

INFRA_REL = os.path.join("src", "ios", "Agent", "MessageList",
                         "MessageListInfrastructure.swift")

SEED_MARK = "[V64-DESEED]"
GATE_MARK = "[V64-CONVERGE]"


def _read(base):
    if os.path.isfile(base):
        base = os.path.dirname(os.path.dirname(os.path.dirname(base)))
    if not os.path.isdir(os.path.join(base, "src", "ios")):
        base = os.path.dirname(base)
    p = os.path.join(base, INFRA_REL)
    if not os.path.isfile(p):
        raise SystemExit("✗ 产物缺失: %s (先跑 verify_v63.sh 或 ci_assert_v64.py 建产物)" % p)
    with open(p, encoding="utf-8") as f:
        return f.read()


def _block(t, marker, what):
    """按花括号配平取出 marker 所在块。★不按固定行数(锚点会随上游注释漂移)。"""
    i = t.find(marker)
    if i < 0:
        raise SystemExit("✗ sabotage 前置失败: %s 标记 %r 不在基线里" % (what, marker))
    j = t.find("{", i)
    if j < 0:
        raise SystemExit("✗ sabotage 前置失败: %s 标记之后无 '{'" % what)
    d = 0
    for k in range(j, len(t)):
        if t[k] == "{":
            d += 1
        elif t[k] == "}":
            d -= 1
            if d == 0:
                return i, k + 1
    raise SystemExit("✗ sabotage 前置失败: %s 花括号不配平" % what)


# ─────────────────────────── 9 条 sabotage ───────────────────────────

def s1_drop_gate(t):
    """S1 摘掉整个收敛闸(花括号配平, 连体一起删)。

    形态: 只断播种就收工。以为「反馈通道断了就万事大吉」。
    为什么危险: iOS 15 的 SwiftUI 是否真遵守 .fittingSizeLevel 无法在编译期
    确认; 若它仍把上一轮的值赢回来, 累加会**换一条路**复发, 而此时判据全绿。
    """
    i, k = _block(t, GATE_MARK, "收敛闸")
    # 连带把紧随其后的两行原始赋值恢复, 保持文件可编译
    t = t[:i] + "        fittingSize.height = _ios15Reconciled\n        attrs.size.height = fittingSize.height" + t[k:]
    return t


def s2_gate_no_write(t):
    """S2 闸门只算不改写: 保留全部计算, 把改写那行摘掉。

    形态: 打了日志、算了 _v64grew/_v64tkFresh, 却没写回 _ios15Reconciled。
    这是 v53 当年的原样病(105 次宣告纠正, preSVH 恒为 1004)。
    """
    old = "            _ios15Reconciled = _v64est\n"
    assert t.count(old) == 1, "S2 前置失败: 改写行数=%d" % t.count(old)
    return t.replace(old, "            // sabotage: 算了但不改写\n", 1)


def s3_gate_unconditional(t):
    """S3 闸门退化成无条件保留 est(把触发条件去掉)。

    形态: 高度从此永远锁在旧值。表面上"不跳了"—— 这正是 v53/v62 被 v63
    揭穿的那个「稳定」假象, 只是换了个位置犯。真实内容变高时也不更新 ⇒
    裁字/空白。
    """
    old = "        if _v64grew && !_v64tkFresh, _v64est > 4 {"
    assert t.count(old) == 1, "S3 前置失败: 条件行数=%d" % t.count(old)
    return t.replace(old, "        if true {", 1)


def s4_gate_no_tk_exemption(t):
    """S4 闸门去掉 TextKit 豁免分支: 连真实增长一起拦。

    形态: 闸门只问「重算值 ≥ est」, 不问「Tk 有没有给出更新的实测」。
    内容真的变高时 _ios15Reconciled 会高于 est, 但那可能正是重算的结果 ⇒
    被误判成"没重算"而保留 est ⇒ 长消息永远长不出来。
    """
    old = "        if _v64grew && !_v64tkFresh, _v64est > 4 {"
    assert t.count(old) == 1, "S4 前置失败"
    return t.replace(old, "        if _v64grew, _v64est > 4 {", 1)


def s5_seed_takes_prev(t):
    """S5 播种改回取上一轮结果(只改一行, 注释原样留着)。

    形态: 注释仍然写着"不播种/切断自我反馈", 代码却把 attrs.size.height
    喂回去。这是最典型的「注释改了代码没改」—— 只查标记的判据必然放过。
    """
    old = ("        var fittingSize = CGSize(width: targetSize.width,\n"
           "                                 height: UIView.layoutFittingCompressedSize.height)")
    assert t.count(old) == 1, "S5 前置失败: 去播种行数=%d" % t.count(old)
    return t.replace(
        old,
        "        var fittingSize = CGSize(width: targetSize.width, height: attrs.size.height)",
        1)


def s6_seed_renamed_attr(t):
    """S6 播种换个属性名继续取上一轮(lastComputedHeight)。

    ★这条专门防「判据只防一种写法」。S5 改的是 attrs.size.height,
      判据里逐字匹配就抓到了; 但上游若改成 lastComputedHeight(同样是
      上一轮的结果), 逐字匹配会漏。判据必须按**语义**禁: 播种语句里
      不得出现任何"上一轮结果"的来源。
    """
    old = ("        var fittingSize = CGSize(width: targetSize.width,\n"
           "                                 height: UIView.layoutFittingCompressedSize.height)")
    assert t.count(old) == 1, "S6 前置失败"
    return t.replace(
        old,
        "        var fittingSize = CGSize(width: targetSize.width, height: lastComputedHeight)",
        1)


def s7_seed_not_compressed(t):
    """S7 播种不用压缩语义(改成一个中性常量)。

    形态: 不取上一轮了, 但与 targetSize 声明的压缩语义不一致 —— 留 0 或留 1
    在不同 SwiftUI 版本下行为不同, 且等于放弃了"从内容重算"的明确意图。
    """
    old = ("        var fittingSize = CGSize(width: targetSize.width,\n"
           "                                 height: UIView.layoutFittingCompressedSize.height)")
    assert t.count(old) == 1, "S7 前置失败"
    return t.replace(
        old,
        "        var fittingSize = CGSize(width: targetSize.width, height: 0)",
        1)


def s8_gate_after_writeback(t):
    """S8 闸门整块挪到 lastComputedHeight 写回**之后**。

    形态: 闸门在位、也算对了, 但顺序错了 —— 写回早已发生, 拦下的值不会被
    采纳。判据若只查"闸门在不在"必然放过(这正是 v64 初版的盲区)。

    ★踩过的坑: 第一版把闸门插到写回点**之前**(`rest.find(anchor)` 前插),
      结果闸门和写回之间的相对顺序根本没变 —— 基线里闸门本来就在写回之前,
      插到前面等于插到闸门和写回之间, 顺序依旧正确 ⇒ sabotage 空转, 判据
      "漏过"了一个根本没被破坏的形态。
      这类"sabotage 自己没破坏任何东西"必须被发现, 不能算判据的错 ——
      所以本文件对每条 sabotage 都有 `t == base` 与前置断言, 且 S8 现在
      插到写回点**之后**(那才是"顺序错"的真实形态)。
    """
    i, k = _block(t, GATE_MARK, "收敛闸")
    block = t[i:k]
    rest = t[:i] + t[k:]
    anchor = "        lastComputedHeight = fittingSize.height"
    assert rest.count(anchor) == 1, "S8 前置失败: 写回点数=%d" % rest.count(anchor)
    j = rest.find(anchor)
    # 插到该行**之后**(行尾换行处), 而不是之前 —— 之后才是"顺序错"
    eol = rest.find("\n", j)
    assert eol > 0, "S8 前置失败: 写回行无换行结尾"
    return rest[:eol + 1] + block + "\n" + rest[eol + 1:]


def s9_gate_no_floor(t):
    """S9 去掉 est > 4 的下限。

    形态: 首帧/近零态(est 还不是"已测量"的值)也被当基线保留 ⇒ 内容第一次
    出现时高度被锁成 ~0 ⇒ 整格空白。
    """
    old = "        if _v64grew && !_v64tkFresh, _v64est > 4 {"
    assert t.count(old) == 1, "S9 前置失败"
    return t.replace(old, "        if _v64grew && !_v64tkFresh {", 1)


def s10_bad_identifier(t):
    """S10 收敛闸引用不存在的标识符 —— **run#159 的真实错误**。

    形态: `_v64found`(真名 `_ios15Found`), 编译期报
      `cannot find '_v64found' in scope`, 整个 App 构建不出来。

    ★为什么这条必须留(而不是"这种错谁也不会写"):
      run#159 上 35 条判据**全绿**, 判据全绿而编译红 —— 因为它们都只查
      文本「在不在」, 查不出「引用的标识符存不存在」。
      这是本项目第四次撞上「判据全绿但…」(前三次见 CONTEXT §4.10.5),
      也是最贵的一次: 前面几次浪费的是时间, 这次浪费的是一次 CI run。
    """
    old = "        let _v64tkFresh = _ios15Found && _v64tk > _v64est + 0.5"
    assert t.count(old) == 1, "S10 前置失败: 目标行数=%d" % t.count(old)
    return t.replace(old, "        let _v64tkFresh = _v64found && _v64tk > _v64est + 0.5", 1)


SABOTAGE = [
    ("S1 摘收敛闸(只断播种就收工)",      s1_drop_gate),
    ("S2 闸门只算不改写",                s2_gate_no_write),
    ("S3 闸门退化成无条件锁死",          s3_gate_unconditional),
    ("S4 闸门无 TextKit 豁免(误杀真实增长)", s4_gate_no_tk_exemption),
    ("S5 播种改回取上一轮",              s5_seed_takes_prev),
    ("S6 播种换属性名取上一轮",          s6_seed_renamed_attr),
    ("S7 播种不用压缩语义",              s7_seed_not_compressed),
    ("S8 闸门挪到写回之后(形同虚设)",    s8_gate_after_writeback),
    ("S9 闸门无 est 下限(首帧锁 0)",     s9_gate_no_floor),
    ("S10 引用不存在的标识符(run#159 真错)", s10_bad_identifier),
]


def _judge(t):
    """跑真判据。通过返回 None, 失败返回异常。"""
    try:
        fb.verify_deseed_v64(t)
        return None
    except Exception as e:
        return e


def main():
    base_arg = sys.argv[1] if len(sys.argv) > 1 else os.path.join(REPO, "src")
    base = _read(base_arg)

    # ── BASE 必须先独立通过(修掉"BASE 计入 passed"的判据自身 bug) ──
    berr = _judge(base)
    if berr is not None:
        print("✗ 基线本身不通过 —— 反向判据无法工作(先修产物或判据)")
        print("  基线报错: %s" % berr)
        return 1
    print("基线: OK(不计入 passed)")

    if not all(m in base for m in (SEED_MARK, GATE_MARK)):
        print("✗ 基线缺标记 %r/%r —— v64 注入没生效, 空测" % (SEED_MARK, GATE_MARK))
        return 3

    passed = 0
    voided = 0
    missed = []
    for name, fn in SABOTAGE:
        try:
            t = fn(base)
        except SystemExit as e:
            print("  ∅ %-40s 空测(%s)" % (name, e))
            voided += 1
            continue
        except AssertionError as e:
            print("  ∅ %-40s 空测(sabotage 自身前置失败: %s)" % (name, e))
            voided += 1
            continue
        if t == base:
            print("  ∅ %-40s 空测(sabotage 什么也没改)" % name)
            voided += 1
            continue
        err = _judge(t)
        if err is None:
            print("  ✗ %-40s 漏过" % name)
            missed.append(name)
        else:
            print("  ✓ %-40s 拦下" % name)
            passed += 1

    total = len(SABOTAGE)
    print("v64 反向: %d 拦下, %d 漏过, %d 空测(共 %d 条 sabotage)"
          % (passed, len(missed), voided, total))
    if voided:
        print("::error::v64 反向有 %d 条空测 —— 空测不是通过, 必须修 sabotage" % voided)
    for m in missed:
        print("::error::v64 反向漏过: %s —— 判据放过了一种没治病的形态" % m)
    return 1 if (missed or voided) else 0


if __name__ == "__main__":
    sys.exit(main())
