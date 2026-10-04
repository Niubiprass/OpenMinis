# -*- coding: utf-8 -*-
"""v59 反向测试 —— 「关掉容器宽跟随」这条线到底拦不拦得住真错。

v59 是 v31~v58 全部失败后的断源版: SelectableMarkdownTextView.init() 的
widthTracksTextView 从 true 改 false, 让 KVO 纠偏写入的净宽不再被系统
每趟布局从 frame(390) 重新派生覆盖。

【每条 sabotage 对应一个真实可能犯的错】
  S1 改回 true            ← 直接回到「改了等于没改」的天花板(本版治的病)
  S2 删掉首帧兜底          ← 关掉跟随后容器默认 1e7, 首趟排版排成一行超长
  S3 顺手把 TableScrollView 那处也改 false ← 范围失控(v56.6 纪律:
       表格内联代码的 frame 是干净的, 它不是病灶)
  S4 摘掉标记但保留行为    ← 判据只看标记会放过「改了没标记」
  S5 兜底宽写成 1e7       ← 等于没兜底, 且重现历史 1e7 污染
"""
import io
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FB = os.path.join(ROOT, 'scripts', 'ios15_fallback.py')

MARK = '[V59-NOTRACK]'
TRUE_LINE = '        textContainer.widthTracksTextView = true'
FALSE_LINE = '        textContainer.widthTracksTextView = false'
FALLBACK_INIT = '        textContainer.size = CGSize(width: 320, height: 2000)'


def build_product():
    up = os.environ.get('OPENMINIS_UPSTREAM_IOS', '')
    if up and os.path.isdir(up):
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, 'src', 'ios')
            os.makedirs(dst, exist_ok=True)
            subprocess.run(['cp', '-r', os.path.join(up, '.'), dst], check=True)
            r = subprocess.run([sys.executable, FB, dst],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError('fallback 跑失败:\n' + r.stderr[-3000:])
            p = os.path.join(dst, 'Views', 'Chat', 'SelectableMarkdownView.swift')
            if os.path.isfile(p):
                return io.open(p, encoding='utf-8').read(), 'fallback@clean'
    p = os.path.join(ROOT, 'src', 'ios', 'Views', 'Chat',
                     'SelectableMarkdownView.swift')
    return io.open(p, encoding='utf-8').read(), 'src/ios'


def judge(t):
    if MARK not in t:
        return False, '缺 %s 标记' % MARK
    i = t.find(MARK)
    tail = t[i:i + 3000]
    if 'isEditable = false' not in tail:
        return False, '标记不在 SelectableMarkdownTextView.init() 里(v46 形态)'
    if 'textContainer.size = CGSize(width: 320' not in tail:
        return False, '缺首帧兜底(容器默认 1e7, 首趟排成一行超长)'
    n_true = t.count('widthTracksTextView = true')
    if n_true != 1:
        return False, ('全文件「跟随宽」%d 处(应为 1) —— 0=表格那处也被改了'
                       '(范围失控), >1=上游新增视图需登记' % n_true)
    n_false = t.count('widthTracksTextView = false')
    if n_false != 2:
        return False, ('全文件「关闭跟随」%d 处(应为 2: codeTextView + 主视图) —— '
                       '1=注入没生效, >2=别处新关未登记' % n_false)
    return True, 'v59 五层全过'


def s1_back_to_true(x):
    """S1: 改回 true —— 直接回到天花板(必须拦, 这是本版的全部意义)。"""
    if MARK not in x:
        return x, '锚点缺失'
    i = x.find(MARK)
    j = x.rfind('\n', 0, i) + 1
    # 标记上一行就是 false 那行
    k = x.rfind(FALSE_LINE, 0, j)
    if k < 0:
        return x, '锚点缺失'
    return x[:k] + TRUE_LINE + x[k + len(FALSE_LINE):], '改回 true'


def s2_no_fallback_init(x):
    """S2: 删掉首帧兜底 —— 容器默认 1e7, 首趟排成一行超长。"""
    if FALLBACK_INIT not in x:
        return x, '锚点缺失'
    i = x.find(FALLBACK_INIT)
    ls = x.rfind('\n', 0, i) + 1
    return x[:ls] + x[x.find('\n', i) + 1:], '删首帧兜底'


def s3_overreach_table(x):
    """S3: 顺手把 TableScrollView 那处也改 false —— 范围失控。"""
    if TRUE_LINE not in x:
        return x, '锚点缺失'
    return x.replace(TRUE_LINE, FALSE_LINE, 1), '表格那处也改 false'


def s4_drop_mark(x):
    """S4: 摘掉标记但保留行为 —— 只看标记的判据会放过。"""
    i = x.find(MARK)
    if i < 0:
        return x, '锚点缺失'
    ls = x.rfind('\n', 0, i) + 1
    le = x.find('\n', i)
    return x[:ls] + x[le + 1:], '删标记行'


def s5_bad_fallback_init(x):
    """S5: 兜底宽写成 1e7 —— 等于没兜底, 重现历史 1e7 污染。"""
    if FALLBACK_INIT not in x:
        return x, '锚点缺失'
    return x.replace(FALLBACK_INIT,
                     '        textContainer.size = CGSize(width: 1e7, height: 2000)', 1), \
        '兜底宽写成 1e7'


SABOTAGE = [
    ('BASE 基线', lambda x: (x, '')),
    ('S1 改回 true', s1_back_to_true),
    ('S2 删首帧兜底', s2_no_fallback_init),
    ('S3 表格那处也改 false', s3_overreach_table),
    ('S4 删标记保留行为', s4_drop_mark),
    ('S5 兜底宽 1e7', s5_bad_fallback_init),
]


def main():
    print('=' * 62)
    print('v59 反向测试（关闭容器宽跟随 —— 断源）')
    print('=' * 62)
    prod, origin = build_product()
    print('产物来源: %s (%d 字符)' % (origin, len(prod)))

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
    print('v59 反向: %d 拦下, %d 漏过（共 %d 条 sabotage）' % (caught, passed, n))
    return 0 if passed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
