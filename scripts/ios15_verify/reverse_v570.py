# -*- coding: utf-8 -*-
"""v57.0 反向测试 —— 独立于 fallback 实现的外部判据。

设计原则（沿用 v565~v569 的踩坑经验）：

1. **不能只验标记在不在**。sabotage S7 摘掉标记但保留行为时，
   仅靠 `in t` 的判据照样全绿。
2. **每条 sabotage 必须对应一个真实可能犯的错**，而不是随机变异。
   本版最典型的两个坑：
   - 把纠偏写到 `if !polluted` **之后** ⇒ 每帧早退，一次都不执行；
   - 诊断回读 `textContainer.size.width` 冒充脏值 ⇒ 永远打「全绿」。
3. **判据要从干净上游重跑生成**（subprocess 调 fallback），而不是
   直接读 src/ios —— 否则测的是"产物此刻的样子"，测不出注入链是否可用。
"""
import io
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FB = os.path.join(ROOT, 'scripts', 'ios15_fallback.py')

DIRTY = '''            let _v570NetW = max(200.0, cvW - 32)
            let _v570Dirty = abs(self.textContainer.size.width - _v570NetW) > 1
            if _v570Dirty {
                self.textContainer.size.width = _v570NetW
            }'''

POLLUTED = '''            let polluted = f.size.width > cvW + 1 || f.origin.x < -0.5
                || _hDebt || _v570Dirty
            if !polluted {'''

DIRTY_LINE = 'let _v570Dirty = abs(self.textContainer.size.width - _v570NetW) > 1'
WRITE_LINE = 'self.textContainer.size.width = _v570NetW'
DIAG_MARK = '[V570-KVODIAG]'
DIAG_FMT = '[V570-KVOCW] dirty=%d netW='
MARK = '[V570-KVOCW]'


# ----------------------------------------------------------------------
# 产物获取：优先跑 fallback 从干净上游生成，拿不到就退回 src/ios
# ----------------------------------------------------------------------
def build_product():
    up = os.environ.get('OPENMINIS_UPSTREAM_IOS')
    if up and os.path.isdir(up):
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, 'src', 'ios')
            # ★必须先建目录：cp -r 到不存在的目标路径会报
            #   "cannot create directory ... No such file or directory"
            #   (run#147 本地回归实测踩到 —— 它只在传了
            #    OPENMINIS_UPSTREAM_IOS 时才走这条分支,
            #    所以本地不传环境变量时反而测不出来)。
            os.makedirs(dst, exist_ok=True)
            subprocess.run(['cp', '-r', os.path.join(up, '.'), dst], check=True)
            r = subprocess.run(
                [sys.executable, FB, dst],
                capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError('fallback 从干净上游跑失败:\n' + r.stderr[-3000:])
            p = os.path.join(dst, 'Views', 'Chat', 'SelectableMarkdownView.swift')
            if os.path.isfile(p):
                return io.open(p, encoding='utf-8').read(), 'fallback@clean'
    p = os.path.join(ROOT, 'src', 'ios', 'Views', 'Chat', 'SelectableMarkdownView.swift')
    return io.open(p, encoding='utf-8').read(), 'src/ios'




# ----------------------------------------------------------------------
# v58 之后的摘块工具 —— s1/s10/s11 共用
# ----------------------------------------------------------------------
# 【为什么 v57.0 版的 DIRTY 常量在 v58 之后失效】
#   DIRTY 是 v57.0 注入的原始 5 行块; v58 的注入把其中 `if _v570Dirty {`
#   块扩充(块内加了 invalidateLayout + 大段注释) ⇒ 旧 5 行串在产物里
#   **不复存在** ⇒ t.find(DIRTY) 返回 -1 ⇒ s1/s10/s11 全部"注入未生效"
#   (本版实测: 3 条同时变无效, 判据还显示 9/12 拦下 —— 看着还行, 其实
#    最核心的三条位置回归已经没人测了)。
# 【行级摘块对注释长度免疫】(与 reverse_v58.py 的纪律同源)
def _extract_v57_block(t):
    """摘掉纠偏块(let _v570NetW 起, 到 if _v570Dirty 的缩进收尾 })。

    返回 (摘掉后的文本, 块原文)。定位失败返回 (None, None)。
    """
    raw = t.split('\n')
    i_netw = -1
    for k, ln in enumerate(raw):
        if 'let _v570NetW = max(200.0, cvW - 32)' in ln:
            i_netw = k
            break
    if i_netw < 0:
        return None, None
    i_if = -1
    for k in range(i_netw, min(i_netw + 6, len(raw))):
        if raw[k].strip() == 'if _v570Dirty {':
            i_if = k
            break
    if i_if < 0:
        return None, None
    indent = raw[i_if][:len(raw[i_if]) - len(raw[i_if].lstrip())]
    i_end = -1
    for k in range(i_if + 1, len(raw)):
        if raw[k].startswith(indent + '}'):
            i_end = k
            break
    if i_end < 0:
        return None, None
    block = '\n'.join(raw[i_netw:i_end + 1])
    rest = raw[:i_netw] + raw[i_end + 1:]
    return '\n'.join(rest), block

# ----------------------------------------------------------------------
# 外部判据（刻意不 import fallback 的 verify，避免自己验自己）
# ----------------------------------------------------------------------
def judge(t):
    """返回 (通过?, 失败原因)。六层, 与 fallback 内 verify 同强度。"""
    if MARK not in t:
        return False, '缺少 %s 标记' % MARK
    if DIRTY_LINE not in t:
        return False, '缺少双向判据整行: %s' % DIRTY_LINE

    # ★段起点用 _v570NetW 声明（v57.0 独有），而不是 DIRTY_LINE ——
    #   DIRTY_LINE 在别的版本段里可能出现同形行，起点取错会误判基线。
    i_seg = t.find('let _v570NetW = ')
    if i_seg < 0:
        return False, '缺少 _v570NetW 声明'
    i_d = t.find(DIRTY_LINE, i_seg, i_seg + 400)
    if i_d < 0:
        return False, '缺少双向判据整行: %s' % DIRTY_LINE

    i_p = t.find('|| _hDebt || _v570Dirty', i_d)
    if i_p < 0:
        return False, 'polluted 判据没并入 _v570Dirty（早退分支看不到容器脏宽）'
    # ★这里要抓的是 S1 的**真实后果**：把整块纠偏挪到早退之后时，
    #   `let _v570Dirty` 声明也跟着挪到了 polluted 之后 ⇒ Swift 编译期
    #   "use of local variable '_v570Dirty' before its declaration"。
    #   所以检查方向是「声明晚于引用」= i_d > i_p（正常形态是 i_d < i_p）。
    #   ★方向写反过一次，基线被误判红 —— 变量声明在使用之前才是合法的。
    if i_d > i_p:
        return False, ('_v570Dirty 的声明晚于 polluted 对它的引用 '
                       '⇒ Swift 编译期 use-before-declaration')

    # ★写入点必须落在 v57.0 段内：layoutSubviews 段里另有一个
    #   `self.textContainer.size.width = ...` 写入点(v49 段)，全局首个匹配
    #   会拿它当 v57.0 的纠偏，于是"纠偏挪到早退之后"这类 sabotage 漏过
    #   (实测漏过一次)。限定搜索窗口 = 判据行之后 400 字符内。
    i_w = t.find(WRITE_LINE, i_d, i_d + 400)
    i_g = t.find('if !polluted {', i_p)
    if i_g < 0:
        return False, 'polluted 之后找不到早退分支'
    if i_w < 0:
        return False, '缺少纠偏写入（或写入点离判据过远，不属 v57.0 段）'
    if i_w > i_g:
        return False, '纠偏写在 `if !polluted` 之后 ⇒ 每帧早退, 永不执行'

    if DIAG_MARK not in t:
        return False, '缺少 %s 纯诊断' % DIAG_MARK
    if DIAG_FMT not in t:
        return False, ('诊断必须用 dirty 标记式 `%s` —— 回读宽度在纠正之后恒等于 '
                       'netW, 永远打全绿骗人' % DIAG_FMT)
    if '[V570-BIDIR]' in t:
        return False, ('旧 [V570-BIDIR] 双向化修法还在 —— 它在 tcW=390 上与旧判据'
                       '行为完全相同, 证明不了 390 的成因')
    # 净宽来源必须与 layoutSubviews 的 _realW2 同源（max(200, cvW-32)）
    # ★锚定 v57.0 的那处声明 —— 该表达式在 ios15ApplyFrameFix 段也出现过,
    #   全局 `in t` 会被别处满足, 于是"净宽取错源"这条 sabotage 就漏过
    #   (实测漏过一次, 与 S4 同一个坑的两面)。
    k = t.find('let _v570NetW = ')
    if k < 0:
        return False, '缺少 _v570NetW 声明'
    if 'max(200.0, cvW - 32)' not in t[k:k + 60]:
        return False, ('净宽不是 max(200.0, cvW-32), 与 _realW2 不同源 '
                       '⇒ 又一次拉锯')

    # ★★v57.1 新增: 纠偏必须早于「本帧第一次用宽度做决策」的三处 ★★
    # v57.0 只约束「纠偏 < 早退」, 那条**通过了**但太弱 —— 早退在一帧的
    # 中段, 前面还有六条语句, 排版已按脏宽发生过一次。装机日志(len=297):
    #   .545 V45 v18W=358 kvoW=390 laidW=-1 usedH=258.7 needH=409.7
    # 那 151pt(≈6 行)就是落屏用的按 390 排的行碎片, 纠偏发生在它之后。
    #
    # ★锚点必须用「KVO 闭包第一条业务语句」而不是 V43 声明行 ★
    #   本条判据第一版锚 V43(`let _v43DirtyW = ...`), 结果 reverse S10
    #   **漏过** —— 因为把纠偏插在 `let _v42TCW = _v43NetW` 之后、V43 声明
    #   之前时, 写入行号只比 V43 早 2 行, `i_w > i_a` 不成立。
    #   但那个位置**仍然是错的**: V41-KVOPRE 诊断、`_v42Len`/`_v42Now` 声明、
    #   以及 V43 整块注释都还在纠偏之前, 语义上纠偏并没有到「闭包最前」。
    #   ⇒ 锚点上移到 `_v42Len`(闭包第一条业务语句), 语义才与 v57.1 一致。
    for _anchor, _why in (
            ('let _v42Len = self.textStorage.length',
             'KVO 闭包第一条业务语句(_v42Len 声明)'),
            ('let _v43DirtyW = self.textContainer.size.width',
             'V43-WIDTH 声明行(它在此读脏宽并算 dh)'),
            ('CGSize(width: _v42TCW, height: .greatestFiniteMagnitude)).height',
             'V42-MISS 的 sizeThatFits 调用行(它用此宽测高并刷新闩锁键)'),
            ('[V44-TEXTFRAME]',
             'V44-TEXTFRAME 诊断行(它读到的 tcW 必须已纠偏)'),
    ):
        i_a = t.find(_anchor)
        if i_a < 0:
            return False, '顺序锚点缺失 —— %s' % _why
        if i_w > i_a:
            return False, ('★v57.1 顺序错★ 纠偏写在「%s」之后 ⇒ '
                           '本帧已按脏宽排版/测高/落盘, 纠偏太晚' % _why)
    return True, ''


# ----------------------------------------------------------------------
# sabotage
# ----------------------------------------------------------------------
def s_base(t):
    return t, '基线'


def s1_move_after_guard(t):
    """把纠偏整块挪到 `if !polluted {` 之后 —— 最容易犯的错。

    ★必须锚定 v57.0 段内的 DIRTY 块：文件里 layoutSubviews 段还有一个
      同名的 `textContainer.size.width = ...` 写入点(v49)，全局首个匹配
      会拿错位置，让本条 sabotage 变成"什么都没改"(实测漏过一次)。
    """
    out, blk = _extract_v57_block(t)
    if out is None:
        return t, '锚点缺失'
    ip = out.find('|| _hDebt || _v570Dirty')
    g = out.find('if !polluted {', ip)
    ls = out.rfind('\n', 0, g) + 1
    return out[:ls] + blk + '\n' + out[ls:], '纠偏挪到早退之后'


def s2_polluted_no_dirty(t):
    """polluted 不并入 _v570Dirty —— 纠偏照做，但仍然每帧早退后被跳过。"""
    if '|| _hDebt || _v570Dirty' not in t:
        return t, '锚点缺失'
    return (t.replace('|| _hDebt || _v570Dirty', '|| _hDebt', 1),
            'polluted 漏掉 _v570Dirty')


def s3_one_way(t):
    """退回单向 `>` —— 只抓偏大，放过偏小。"""
    out = t.replace(DIRTY_LINE,
                    'let _v570Dirty = textContainer.size.width > _v570NetW + 1', 1)
    return out, '判据退回单向'


def s4_netw_wrong(t):
    """净宽取错源（用 tcW 自己算 ⇒ 恒等于脏宽 ⇒ 判据恒假）。

    ★必须改 v57.0 那一处：`max(200.0, cvW - 32)` 在 ios15ApplyFrameFix 段
      也出现过，无脑 replace(...,1) 会改到别处，本条等于没改(实测漏过一次)。
    """
    k = t.find('let _v570NetW = max(200.0, cvW - 32)')
    if k < 0:
        return t, '锚点缺失'
    out = t[:k] + 'let _v570NetW = self.textContainer.size.width' + t[k + len('let _v570NetW = max(200.0, cvW - 32)'):]
    return out, '净宽取 tcW 自己（不同源）'


def s5_tolerance_loose(t):
    """容差从 1 放大到 32 —— 390 vs 358 差 32，刚好被吞掉。"""
    out = t.replace(DIRTY_LINE,
                    'let _v570Dirty = abs(self.textContainer.size.width - _v570NetW) > 32',
                    1)
    return out, '容差放大到 32（吞掉实际差值）'


def s6_drop_diag(t):
    """摘掉诊断标记但保留行为 —— 专治「只验标记」型弱判据。"""
    out = t.replace(DIAG_MARK, '[V570-NODIAG]', 1)
    out = out.replace(DIAG_FMT, '[V570-KVOCW] x=%d netW=', 1)
    return out, '诊断标记/格式被摘'


def s7_readback_diag(t):
    """诊断回读宽度冒充脏值 —— 语法合法、编译通过，但永远打「全绿」。"""
    out = t.replace(DIAG_FMT, '[V570-KVOCW] tcW=%.1f netW=', 1)
    # 同步把参数列表改成回读 tcW，让 sabotage 自身是自洽的
    out = out.replace('_v570Dirty ? 1 : 0, _v570NetW,',
                      'self.textContainer.size.width, _v570NetW,', 1)
    return out, '诊断回读 tcW 冒充脏值'


def s8_keep_old_bidir(t):
    """复活旧 [V570-BIDIR] 双向化 —— 证明不了 390 成因的假修法。"""
    i = t.find(MARK)
    return t[:i] + ('// [V570-BIDIR] if abs(textContainer.size.width - _realW) > 1 {\n'
                    + t[i:]), '复活旧 BIDIR 假修法'


def s9_drop_write(t):
    """判据算了 dirty 却不写 —— 纯诊断冒充修复。"""
    out = t.replace(WRITE_LINE, '_ = _v570Dirty  // 故意不写', 1)
    return out, '只判不写'


# ★★v57.1 三条: 专测新位置约束 ★★
# 这三条模拟的正是 v57.0 装机后的真实失败形态 —— 判据全绿、症状原样。
def s10_move_back_before_v43(t):
    """把纠偏整块挪回 V43 之后（= v57.0 的位置）。

    ★这是 v57.0 **真实**的形态：纠偏在 `if !polluted` 之前，v57.0 的
      「纠偏 < 早退」判据**真的通过了**，但它排在 V43/V42-MISS/V44 之后，
      排版已按脏宽发生一次 ⇒ 屏幕仍是按 390 排的那一版。
      本条是整个 v57.1 的核心回归: 它必须被拦下。
    """
    out, blk = _extract_v57_block(t)
    if out is None:
        return t, '锚点缺失'
    a = out.find('let _v43DirtyW = self.textContainer.size.width')
    if a < 0:
        return t, 'V43 锚点缺失'
    ls = out.rfind('\n', 0, a) + 1
    return out[:ls] + blk + '\n' + out[ls:], '纠偏挪到 V43 之后(= v57.0 位置)'


def s11_move_after_v44(t):
    """把纠偏整块挪到 V44-TEXTFRAME 诊断之后 —— 诊断先看到脏宽。"""
    out, blk = _extract_v57_block(t)
    if out is None:
        return t, '锚点缺失'
    a = out.find('// [V44-TEXTFRAME]')
    if a < 0:
        return t, 'V44 锚点缺失'
    ls = out.rfind('\n', 0, a) + 1
    return out[:ls] + blk + '\n' + out[ls:], '纠偏挪到 V44 之后'


def s12_weaken_to_v42miss_only(t):
    """只守住 V42-MISS 一处，放弃 V43/V44 —— 制造"部分守住"的假绿。

    ★这类"改了一处漏了两处"是最常见的漏网形态：判据只要锚点选得够多
      就容易让人误以为全覆盖。本条逼判据必须**三处全查**。
    """
    out = t.replace('let _v43DirtyW = self.textContainer.size.width',
                    'let _v43DirtyW = _v570NetW  // 假装已在纠偏段内', 1)
    return out, '把 V43 锚点改成假满足(V43 仍在纠偏之后)'


SABOTAGE = [
    ('BASE', s_base),
    ('S1 纠偏挪到早退之后', s1_move_after_guard),
    ('S2 polluted 漏掉 dirty', s2_polluted_no_dirty),
    ('S3 判据退回单向 >', s3_one_way),
    ('S4 净宽取 tcW 自己', s4_netw_wrong),
    ('S5 容差放大到 32', s5_tolerance_loose),
    ('S6 诊断标记被摘', s6_drop_diag),
    ('S7 诊断回读 tcW 冒充脏值', s7_readback_diag),
    ('S8 复活旧 BIDIR 假修法', s8_keep_old_bidir),
    ('S9 只判不写', s9_drop_write),
    ('S10 纠偏挪到 V43 之后(=v57.0 位置)', s10_move_back_before_v43),
    ('S11 纠偏挪到 V44 之后', s11_move_after_v44),
    ('S12 V43 锚点改假满足', s12_weaken_to_v42miss_only),
]


def main():
    print('=' * 62)
    print('v57.1 反向测试（KVO 闭包最前纠偏容器宽）')
    print('=' * 62)
    prod, origin = build_product()
    print('产物来源: %s' % origin)

    caught = passed_through = 0
    for name, fn in SABOTAGE:
        mutated, desc = fn(prod)
        if mutated == prod and name != 'BASE':
            print('  ⚠ %-26s 注入未生效（锚点缺失），本条无效' % name)
            passed_through += 1
            continue
        ok, why = judge(mutated)
        if name == 'BASE':
            if ok:
                print('  ✅ %-26s 基线通过' % name)
            else:
                print('  ❌ %-26s 基线就红: %s' % (name, why))
                return 1
            continue
        if ok:
            print('  ❌ %-26s 漏过（%s）' % (name, desc))
            passed_through += 1
        else:
            print('  ✅ %-26s 拦下: %s' % (name, why))
            caught += 1

    n = len(SABOTAGE) - 1
    print('-' * 62)
    print('v571 反向: %d 拦下, %d 漏过（共 %d 条 sabotage）' % (caught, passed_through, n))
    return 0 if passed_through == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
