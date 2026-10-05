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
MD_GUARD = 'guard deferredCorrectionPending || _stillOwing || _v62oversized else { return }'
MD_REPORT = '_v53ReportDebtToCell(_stillOwing || _v62oversized ? _debt : 0)'
MD_OVER = 'let _v62oversized = _cellH > 1 && _need > 1 && (_cellH - _need) > 40'


def build_product():
    """完整移植链生成两个产物(infra, md)。"""
    up = os.environ.get('OPENMINIS_UPSTREAM_IOS', '')
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
    for key in (MD_OVER, MD_GUARD, MD_REPORT):
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
    infra, md = prod
    if MD_GUARD not in md:
        return prod, '锚点缺失'
    return (infra, md.replace(MD_GUARD,
           'guard deferredCorrectionPending || _stillOwing else { return }', 1)), '摘盈余驱动'


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

    caught = passed = 0
    for name, fn in SABOTAGE:
        mutated, desc = fn(prod)
        if mutated == prod and not name.startswith('BASE'):
            print('  ⚠ %-24s 注入未生效(锚点缺失)，本条无效' % name)
            passed += 1
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
    print('v62 反向: %d 拦下, %d 漏过（共 %d 条 sabotage）' % (caught, passed, n))
    return 0 if passed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
