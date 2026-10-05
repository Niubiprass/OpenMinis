# -*- coding: utf-8 -*-
"""v63 反向测试 —— 治「工具卡片整屏狂跳 + 文字非流式突现」。

【为什么 v63 要有反向测试, 而前面 62 版没写】
  v60 的提交记录原话:「v31~v59 的容器层对抗 30 余版从未被真机验证」。
  30 余版全绿却没治好病, 根因是**判据只能证明"代码在", 证明不了
  "代码在跑"**。装机日志里 `V53-DEBT`/`V62-SURPLUS` 出现 **0 次**,
  `live=` 唯一取值 `{0}` —— 代码全在, 从未执行。
  所以 v63 除了形状判据(verify_*_v63), 还带**探针**
  (`[V63-PROBE]` / `[V63-INTSIZE]`), 装机即可自证是否被执行。
  本文件守的是「形状判据自己会不会失灵」。

【每条 sabotage 对应一个真实可能犯的错】
  S1  摘 invalidateIntrinsicContentSize  ← 回到 v60 病根(唯一信号源被切断)
  S2  invalidate 排到 rootView 赋值之前  ← SwiftUI 还没换就通知, 无效
  S3  用 setNeedsLayout 替代 invalidate    ← StackOverflow 77027194 明确说它无效
  S4  fast path 摘 config 身份判等          ← 拿别的消息的 host 就地刷 rootView
  S5  世代号不自增                          ← 判等恒不成立, 快速路径永不命中
  S6  重建路径不记身份戳                    ← 同 S4, 反向触发
  S7  intrinsic 高度改回 noIntrinsicMetric  ← 回到 v60 形态(宽度治理的误伤)
  S8  intrinsic 宽度放开成 fit.width        ← 100032 污染宽从这条通道回潮
  S9  摘 _v63drift 的 guard 接线             ← 声明了没接线(纪律第 13 条)
  S10 _v63drift 阈值 8 → 0                  ← 亚像素噪声全放行, 抖动更狂
  S11 _v63drift 阈值 8 → 100000             ← 永不触发, 等于没改
  S12 _v63drift 与 debt 计数重新绑定        ← 循环依赖引回来, 病复发
  S13 摘 _ios15ApplyGen 自增                ← 同 S5, 但破坏点在 apply 入口
  S14 探针字段/打印被摘                     ← 装机又变成"零输出", 无人察觉

★纪律对照:
  第 5 条「判据输出文案本身是判据」⇒ 每条拦住时打印的是**判据的原文**,
        不是"失败"。装机/评审时能直接看出哪条判据在把关。
  第 7 条「只允许用编译器已验证存在的 API」⇒ S3 专门把 invalidate 换成
        setNeedsLayout, 由判据拦住 —— 这是最容易"顺手优化"犯的错。
  第 10 条「反向测试锚点失效必须自己报错」⇒ 锚点缺失算**失败**而非跳过。
        ★v63 落地时 S5 就因 v63 加了第四条腿而空测, 被本脚本的锚点计数抓到。
"""
import io
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
FB = os.path.join(ROOT, "scripts", "ios15_fallback.py")
COMPAT_REL = os.path.join("src", "ios", "iOS15Compat.swift")
MD_REL = os.path.join("src", "ios", "Views", "Chat", "SelectableMarkdownView.swift")

# ---- 产物里的锚点(与 ios15_fallback.py 的 V63_* 常量逐字对应) ----
APPLY_HEAD = "    private func apply(_ config: UIContentConfiguration) {"
GEN_INC = "        _ios15ApplyGen &+= 1"
REUSE_HEAD = ("        if let existing = host, "
              "let newConfig = config as? UIHostingConfiguration<Content>, "
              "_v63ConfigGen == _ios15ApplyGen {")
ROOTVIEW_SET = ("            existing.rootView = AnyView(newConfig.content"
                ".frame(maxWidth: _ios15ContentMaxW2, alignment: .leading))")
INVALIDATE = "            existing.view.invalidateIntrinsicContentSize()"
STAMP = "        _v63ConfigGen = _ios15ApplyGen"
INTSIZE_RET = ("        return CGSize(width: UIView.noIntrinsicMetric, "
               "height: ceil(fit.height))")
DRIFT_DEF = ("        let _v63drift = _cellH > 1 && _need > 1 "
             "&& abs(_cellH - _need) > 8")
GUARD = ("        guard deferredCorrectionPending || _stillOwing "
         "|| _v62oversized || _v63drift else { return }")
PROBE_DECL = "    private static var _v63FastHit: UInt = 0"
PROBE_CALL = "            _v63ProbeIncr()"
# ★这段锚点含 Swift 字符串插值 `\(`。Python 源码里写两个反斜杠才解析出
#   一个 —— 写成一个会被当成 `\_`(反斜杠+下划线), 静默不命中。
#   本项目已因此浪费三轮(改一次坏一次), 故下面加**自检**:
#   构造完立刻断言首插值前缀正确, 错了当场抛, 不留到跑 sab 才发现。
PROBE_PRINT = ('        print("[V63-PROBE] fast='
               '\\(_HostingContentCellView._v63FastHit) rebuild=')
assert '_v63FastHit' in PROBE_PRINT and '\\(_Hosting' in PROBE_PRINT, (
    "PROBE_PRINT 的 Swift 插值转义写错了(须为 \\() —— "
    "Python 源码里要写两个反斜杠, 只写一个会变成 \\_")


def load_fb():
    """加载注入脚本以取**真实判据** —— 判据自己必须被测。"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("fb_v63", FB)
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pass
    return mod


def build_product(root_arg):
    """读产物。root_arg 可为产物根目录; 缺文件则报环境不全。"""
    root = root_arg or os.path.join(ROOT, "src")
    base = root if os.path.isdir(os.path.join(root, "src")) else os.path.dirname(
        os.path.dirname(root))
    compat_p = os.path.join(base, COMPAT_REL)
    md_p = os.path.join(base, MD_REL)
    for p in (compat_p, md_p):
        if not os.path.exists(p):
            return None, p
    return (io.open(compat_p, encoding="utf-8").read(),
            io.open(md_p, encoding="utf-8").read()), base


def judge(fb, prod):
    """用注入脚本里的两条真实判据做判定。

    ★不另写一套形状检查: 纪律第 8 条「同一逻辑只能一处实现」。
    这里跑的就是 CI 会跑的那两个函数, 所以本反向测试守护的是
    **判据本身的有效性**, 而非一份平行副本。
    """
    if prod is None:
        return False, "产物缺失"
    compat, md = prod
    try:
        fb.verify_intrinsic_gate_v63(compat, md)
        fb.verify_uncouple_v63(md)
    except RuntimeError as e:
        return False, str(e)
    except Exception as e:
        # ★纪律第 10 条配套: 判据只该抛 RuntimeError。其他异常类型说明
        #   测试自身坏了(签名错/函数名错), 不算「拦住」——
        #   v53 的 S5~S7 就曾因 TypeError 而假绿。
        return False, "★判据自身异常(%s): %s" % (type(e).__name__, e)
    return True, "两条 v63 判据全过"


# ---------------------------------------------------------------- sabotage
def _sub(prod, old, new, count=1):
    """带锚点计数的替换。锚点缺失返回 None(交由调用方判失败)。"""
    if old not in prod:
        return None
    if prod.count(old) != count:
        return None
    return prod.replace(old, new, count)


def s1_drop_invalidate(prod):
    compat, md = prod
    if INVALIDATE not in compat:
        return None
    return (compat.replace(INVALIDATE, "            // sabotage: 摘掉 invalidate", 1), md)


def s2_invalidate_before(prod):
    compat, md = prod
    if INVALIDATE not in compat or ROOTVIEW_SET not in compat:
        return None
    c = compat.replace(INVALIDATE, "", 1)
    c = c.replace(ROOTVIEW_SET, INVALIDATE.strip() + "\n" + ROOTVIEW_SET, 1)
    return (c, md)


def s3_setneedslayout(prod):
    """最容易"顺手优化"犯的错: 用 setNeedsLayout 替代 invalidate。"""
    compat, md = prod
    if INVALIDATE not in compat:
        return None
    return (compat.replace(
        INVALIDATE,
        "            existing.view.setNeedsLayout()", 1), md)


def s4_drop_identity(prod):
    compat, md = prod
    if REUSE_HEAD not in compat:
        return None
    return (compat.replace(
        REUSE_HEAD,
        "        if let existing = host, "
        "let newConfig = config as? UIHostingConfiguration<Content> {", 1), md)


def s5_no_gen_inc(prod):
    compat, md = prod
    if GEN_INC not in compat:
        return None
    return (compat.replace(GEN_INC, "        // sabotage: 世代号不自增", 1), md)


def s6_no_stamp(prod):
    compat, md = prod
    if STAMP not in compat:
        return None
    return (compat.replace(STAMP, "        // sabotage: 不记身份戳", 1), md)


def s7_intsize_back_to_v60(prod):
    """把高度改回 noIntrinsicMetric —— 回到 v60 形态。"""
    compat, md = prod
    if INTSIZE_RET not in md:
        return None
    return (compat, md.replace(
        INTSIZE_RET,
        "        return CGSize(width: UIView.noIntrinsicMetric, "
        "height: UIView.noIntrinsicMetric)", 1))


def s8_intsize_width_open(prod):
    """宽度放开 —— 100032 污染宽的回潮通道。"""
    compat, md = prod
    if INTSIZE_RET not in md:
        return None
    return (compat, md.replace(
        INTSIZE_RET,
        "        return CGSize(width: ceil(fit.width), height: ceil(fit.height))", 1))


def s9_drop_drift_wire(prod):
    """声明了但没接线(纪律第 13 条: 查数据流要连声明一起查)。"""
    compat, md = prod
    if not GUARD in md:
        return None
    return (compat, md.replace(
        GUARD,
        "        guard deferredCorrectionPending || _stillOwing "
        "|| _v62oversized else { return }", 1))


def s10_drift_threshold_zero(prod):
    compat, md = prod
    if DRIFT_DEF not in md:
        return None
    return (compat, md.replace(DRIFT_DEF, DRIFT_DEF.replace("> 8", "> 0"), 1))


def s11_drift_threshold_dead(prod):
    compat, md = prod
    if DRIFT_DEF not in md:
        return None
    return (compat, md.replace(DRIFT_DEF, DRIFT_DEF.replace("> 8", "> 100000"), 1))


def s12_rebind_to_debt(prod):
    """把循环依赖引回来。"""
    compat, md = prod
    if not GUARD in md:
        return None
    return (compat, md.replace(
        GUARD,
        "        guard deferredCorrectionPending || _stillOwing "
        "|| _v62oversized || (v53DebtIsRipe && _v63drift) else { return }", 1))


def s13_drop_gen_inc_apply(prod):
    """破坏点在 apply 入口的自增(与 S5 同果不同点, 守"入口"这一侧)。"""
    compat, md = prod
    if APPLY_HEAD not in compat or GEN_INC not in compat:
        return None
    return (compat.replace(GEN_INC, "", 1), md)


def s14_drop_probe(prod):
    """摘探针 —— 装机又变成"零输出", 无人察觉(v53/v62 就死在这)。"""
    compat, md = prod
    if PROBE_DECL not in compat or PROBE_CALL not in compat or PROBE_PRINT not in compat:
        return None
    c = compat.replace(PROBE_DECL, "    // sabotage: 探针字段被摘", 1)
    c = c.replace(PROBE_CALL, "            // sabotage: 探针不被调用", 1)
    c = c.replace(PROBE_PRINT, '        print("[V63-PROBE] 摘掉了")', 1)
    return (c, md)


SABOTAGE = [
    ("BASE 基线",              None),
    ("S1 摘 invalidate",       s1_drop_invalidate),
    ("S2 invalidate 排前",     s2_invalidate_before),
    ("S3 用 setNeedsLayout",   s3_setneedslayout),
    ("S4 摘 config 身份判等",  s4_drop_identity),
    ("S5 世代号不自增",        s5_no_gen_inc),
    ("S6 重建不记身份戳",      s6_no_stamp),
    ("S7 高度回 v60 形态",     s7_intsize_back_to_v60),
    ("S8 宽度放开(污染回潮)",  s8_intsize_width_open),
    ("S9 摘 drift 的 guard",   s9_drop_drift_wire),
    ("S10 drift 阈值改 0",     s10_drift_threshold_zero),
    ("S11 drift 阈值改死",     s11_drift_threshold_dead),
    ("S12 drift 重新绑 debt",  s12_rebind_to_debt),
    ("S13 apply 入口摘自增",   s13_drop_gen_inc_apply),
    ("S14 摘探针",             s14_drop_probe),
]


def main():
    root_arg = sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else None
    print("=" * 64)
    print("v63 反向测试（工具卡片狂跳 + 文字非流式: invalidate + drift 兜底）")
    print("=" * 64)
    prod, origin = build_product(root_arg)
    if prod is None:
        print("✗ 环境不全, 缺产物: %s" % origin)
        print("  跑法: bash scripts/verify_v63.sh  (会生成 /tmp/v63verify)")
        return 3
    print("产物来源: %s (compat %d / md %d 字符)"
          % (origin, len(prod[0]), len(prod[1])))
    fb = load_fb()

    caught = missed = 0
    for name, fn in SABOTAGE:
        if fn is None:
            ok, why = judge(fb, prod)
            if ok:
                print("  ✅ %-22s 基线通过" % name)
            else:
                print("  ❌ %-22s 基线就红: %s" % (name, why))
                return 1
            continue
        mutated = fn(prod)
        if mutated is None:
            # ★锚点失效算**失败**, 不算跳过(纪律第 10 条)。
            print("  ❌ %-22s 锚点未命中 —— 本条空测, 结果不作数" % name)
            missed += 1
            continue
        ok, why = judge(fb, mutated)
        if ok:
            print("  ❌ %-22s 漏过（判据没反应）" % name)
            missed += 1
        else:
            print("  ✅ %-22s 拦下: %s" % (name, why[:66]))
            caught += 1

    n = len(SABOTAGE) - 1
    print("-" * 64)
    print("v63 反向: %d 拦下, %d 漏过（共 %d 条 sabotage）" % (caught, missed, n))
    return 0 if missed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
