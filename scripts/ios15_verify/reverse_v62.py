# -*- coding: utf-8 -*-
"""v62 反向测试 —— 治「工具卡片间大空白」(V62-SURPLUS 盈余镜像)。

【每条 sabotage 对应一个真实可能犯的错】
  S1 摘 note 盈余分支          ← -290 被 debt<=1 吞掉的原病复发
  S2 盈余阈值 -40 → -100000    ← 永不触发, 分支成死代码
  S3 守卫摘一条(A 路)          ← dedup 短路继续返回旧高 337/384
  S4 guard 摘 _v62oversized    ← 收缩没有 invalidate 驱动源
  S5 上报不喂负值              ← 盈余计数永远到不了「熟」
  S6 欠账互斥清盈余删掉        ← 两计数同时熟, 判据语义含糊
  S7 盈余分支不喂 ripe 返回值  ← 计数在涨但短路守卫拿不到信号
"""
import io
import os
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream_base import upstream_ios  # noqa: E402  唯一的上游解析入口

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FB = os.path.join(ROOT, 'scripts', 'ios15_fallback.py')
INFRA_REL = os.path.join('Agent', 'MessageList', 'MessageListInfrastructure.swift')
MD_REL = os.path.join('Views', 'Chat', 'SelectableMarkdownView.swift')

GUARD = '!v53DebtIsRipe, !v53SurplusIsRipe {'
RIPE_DECL = 'var v53SurplusIsRipe: Bool { v53SurplusSeenCount >= 2 }'
NOTE_FUNC = 'func v53NotePendingDebt('
NOTE_BRANCH = """        if debt < -40 {
            v53DebtSeenCount = 0
            v53PendingHeightDebt = 0
            v53SurplusHeightDebt = -debt
            v53SurplusSeenCount += 1
            return v53SurplusIsRipe
        }"""
MUTEX_BLOCK = """        v53SurplusSeenCount = 0
        v53SurplusHeightDebt = 0
        v53PendingHeightDebt = debt"""
# ★v63 适配: settle 入口 guard 多了第四条腿 `|| _v63drift`(打破 v53/v62 的
#   两拍循环依赖)。锚死 v62 形态会让基线判红 —— 而基线红是**最容易修也最
#   容易掩盖**的一类: 改锚点就行, 但改完这条 sabotage 就测不到新腿了。
#   ⇒ 两种形态都接受; v63 那条腿由 reverse_v63.py 的 S9~S12 专门测
#     (直调 verify_uncouple_v63), 职责不丢。
#   教训见 verify-discipline 第 10 条。
MD_GUARD_V62 = 'guard deferredCorrectionPending || _stillOwing || _v62oversized else { return }'
MD_GUARD_V63 = ('guard deferredCorrectionPending || _stillOwing '
                '|| _v62oversized || _v63drift else { return }')
MD_GUARDS = (MD_GUARD_V63, MD_GUARD_V62)   # 优先新形态
MD_REPORT = '_v53ReportDebtToCell(_stillOwing || _v62oversized ? _debt : 0)'
MD_OVER = 'let _v62oversized = _cellH > 1 && _need > 1 && (_cellH - _need) > 40'


def build_product():
    """完整移植链生成两个产物(infra, md)。"""
    up = upstream_ios(quiet=True)
    if up and os.path.isdir(up):
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, 'src', 'ios')
            os.makedirs(dst, exist_ok=True)
            subprocess.run(['cp', '-r', os.path.join(up, '.'), dst], check=True)
            steps = [
                [sys.executable, os.path.join(ROOT, 'scripts', 'ios15_port.py'), dst],
                [sys.executable, os.path.join(ROOT, 'scripts', 'ios15_port_v2.py')],
                [sys.executable, os.path.join(ROOT, 'scripts', 'ios15_runtime_fixes.py')],
                [sys.executable, FB, dst],
            ]
            for cmd in steps:
                r = subprocess.run(cmd, cwd=td, capture_output=True, text=True)
                if r.returncode != 0:
                    raise RuntimeError('移植链步骤失败(%s):\n' % os.path.basename(cmd[1])
                                       + r.stderr[-3000:])
            infra = io.open(os.path.join(dst, INFRA_REL), encoding='utf-8').read()
            md = io.open(os.path.join(dst, MD_REL), encoding='utf-8').read()
            return (infra, md), 'fullchain@clean'
    base = os.path.join(ROOT, 'src', 'ios')
    return (io.open(os.path.join(base, INFRA_REL), encoding='utf-8').read(),
            io.open(os.path.join(base, MD_REL), encoding='utf-8').read()), 'src/ios'


def judge(prod):
    infra, md = prod
    if RIPE_DECL not in infra:
        return False, '盈余 ripe 声明缺失'
    if infra.count(GUARD) != 3:
        return False, '三短路守卫应恰 3 处带盈余条件, 实测 %d' % infra.count(GUARD)
    i = infra.find(NOTE_FUNC)
    if i < 0:
        return False, 'note 函数缺失'
    seg = infra[i:i + 2200]
    for key in ('if debt < -40 {', 'v53SurplusSeenCount += 1',
                'return v53SurplusIsRipe'):
        if key not in seg:
            return False, 'note 盈余分支不完整(缺 %r)' % key[:24]
    if MUTEX_BLOCK not in infra:
        return False, '欠账态互斥清盈余缺失'
    # guard 两种形态都接受(见 MD_GUARDS 的说明)
    if not any(g in md for g in MD_GUARDS):
        return False, 'settle 入口缺 guard(v62/v63 两种形态都没找到)'
    for key in (MD_OVER, MD_REPORT):
        if key not in md:
            return False, 'settle 入口缺 %r' % key[:36]
    return True, 'v62 五层全过'


def s1_drop_branch(prod):
    infra, md = prod
    if NOTE_BRANCH not in infra:
        return prod, '锚点缺失'
    return (infra.replace(NOTE_BRANCH, '', 1), md), '摘 note 盈余分支'


def s2_threshold_dead(prod):
    infra, md = prod
    if 'if debt < -40 {' not in infra:
        return prod, '锚点缺失'
    return (infra.replace('if debt < -40 {', 'if debt < -100000 {', 1), md), '阈值改死'


def s3_drop_guard_a(prod):
    infra, md = prod
    if infra.count(GUARD) != 3:
        return prod, '锚点缺失'
    return (infra.replace(GUARD, '!v53DebtIsRipe {', 1), md), '摘 A 路盈余守卫'


def s4_drop_guard_cond(prod):
    """摘掉驱动条件(_v62oversized)。

    ★sabotage 必须打到**当前形态**的那个 guard 上。若拿 v62 形态去替换,
      在 v63 产物上会「锚点缺失」⇒ 本条空测 ⇒ 而空测现在算失败。
      ⇒ 先按 MD_GUARDS 的顺序找当前形态, 替换时把它整条换成退化形态。
    """
    infra, md = prod
    for g in MD_GUARDS:
        if g in md:
            return (infra, md.replace(
                g, 'guard deferredCorrectionPending || _stillOwing else { return }', 1)), \
                '摘盈余驱动'
    return prod, '锚点缺失'


def s5_report_zero(prod):
    infra, md = prod
    if MD_REPORT not in md:
        return prod, '锚点缺失'
    return (infra, md.replace(MD_REPORT,
           '_v53ReportDebtToCell(_stillOwing ? _debt : 0)', 1)), '上报不喂负值'


def s6_drop_mutex(prod):
    infra, md = prod
    key = """        // [V62-SURPLUS] 欠账与盈余互斥: 转入欠账态时清盈余计数,
        // 避免两个镜像计数同时「熟」导致短路判据语义含糊。
""" + MUTEX_BLOCK
    if key not in infra:
        return prod, '锚点缺失'
    return (infra.replace(key, '', 1), md), '删互斥清盈余'


def s7_branch_no_return(prod):
    infra, md = prod
    if '            return v53SurplusIsRipe\n' not in infra:
        return prod, '锚点缺失'
    return (infra.replace('            return v53SurplusIsRipe\n',
                          '            return false\n', 1), md), '分支不喂 ripe'


SABOTAGE = [
    ('BASE 基线', lambda x: (x, '')),
    ('S1 摘 note 盈余分支', s1_drop_branch),
    ('S2 盈余阈值改死', s2_threshold_dead),
    ('S3 摘 A 路守卫', s3_drop_guard_a),
    ('S4 摘盈余驱动', s4_drop_guard_cond),
    ('S5 上报不喂负值', s5_report_zero),
    ('S6 删互斥清盈余', s6_drop_mutex),
    ('S7 分支不喂 ripe', s7_branch_no_return),
]


def main():
    print('=' * 62)
    print('v62 反向测试（工具卡片空白: V62-SURPLUS 盈余镜像）')
    print('=' * 62)
    prod, origin = build_product()
    print('产物来源: %s (infra %d / md %d 字符)'
          % (origin, len(prod[0]), len(prod[1])))

    caught = passed = voided = 0
    for name, fn in SABOTAGE:
        mutated, desc = fn(prod)
        if mutated == prod and not name.startswith('BASE'):
            # ★纪律第 10 条: 锚点失效必须**自己报错**, 且必须算失败。
            #   原实现把空测计入 `passed`, 而结尾按 passed==0 判成败
            #   ⇒ 「N-1 拦下 + 1 空测」被当成全过 = **空测当成通过**。
            #   判据链少一条守门却仍显示全绿, 比红更危险。
            #   实测: v63 给 REUSE 快速路径加了 config 判等 ⇒ v61 的 S1 锚点
            #   落空, 而 run#156 一路绿到 CI 才在别处炸出来。
            print('  ✗ %-24s 锚点缺失 —— 本条**空测**, 结果不作数(记失败)' % name)
            voided += 1
            continue
        ok, why = judge(mutated)
        if name.startswith('BASE'):
            if ok:
                print('  ✅ %-24s 基线通过' % name)
            else:
                print('  ❌ %-24s 基线就红: %s' % (name, why))
                return 1
            continue
        if ok:
            print('  ❌ %-24s 漏过（%s）' % (name, desc))
            passed += 1
        else:
            print('  ✅ %-24s 拦下: %s' % (name, why[:66]))
            caught += 1

    n = len(SABOTAGE) - 1
    print('-' * 62)
    print('v62 反向: %d 拦下, %d 漏过, %d 空测（共 %d 条 sabotage）' % (caught, passed, voided, n))
    if voided:
        print('★ 有 %d 条空测 —— 结果不作数, 修锚点或修产物。' % voided)
    return 0 if (passed == 0 and voided == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
