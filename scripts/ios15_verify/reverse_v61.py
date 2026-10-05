# -*- coding: utf-8 -*-
"""v61 反向测试 —— 治「整屏跳动/流式跳出」(REUSE 快速路径 + MONO 单调锁)。

【每条 sabotage 对应一个真实可能犯的错】
  S1 摘掉 apply 快速路径          ← 流式每 tick 重建 host, 跳动元凶复活
  S2 摘掉单调锁生效点             ← 测量抖动直接上屏
  S3 容差 -8 改成 -0              ← 字体/图片加载的合法微缩也被锁死
  S4 重建路径锁重置删掉           ← cell 复用换消息沿用上一条锁定高
                                     → 矮消息底部大空白
  S5 快速路径去掉 maxWidth 修饰   ← 内容理想宽(100032)从这条路径回潮
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
COMPAT_REL = 'iOS15Compat.swift'

FAST_KEY = 'existing.rootView = AnyView(newConfig.content.frame(maxWidth:'
MONO_TAIL = """        if width != ios15MonoHW { ios15MonoHW = width; ios15MonoH = 0 }
        if ios15MonoH > 1, height > 1, height < ios15MonoH - 8 {
            height = ios15MonoH
        }
        if height > ios15MonoH { ios15MonoH = height }
        return CGSize(width: width, height: max(0, height))"""
# ★v63 适配: REUSE 快速路径的 `if let` 条件加了 config 身份判等
#   `_v63ConfigGen == _ios15ApplyGen`(治「拿别的消息的 host 就地刷 rootView」),
#   所以 v61 形态的裸串已不存在 —— 照旧用旧锚点会让 S1 变空测。
#   ★这不是「改锚点就完了」: 改的时候必须问「v63 加的那条腿有没有被测到」
#     ⇒ v63 自己的 reverse_v63.py 用 S4 专门测它(直调 verify_intrinsic_gate_v63)。
#   教训见 verify-discipline 第 10 条: 锚点失效必须自己报错, 不许静默跳过。
#   —— 而本文件此前恰恰违反了这条(见下方 main() 的计数修正)。
FAST_BLOCK_START = ('        if let existing = host, '
                    'let newConfig = config as? UIHostingConfiguration<Content>'
                    ', _v63ConfigGen == _ios15ApplyGen {')
FAST_BLOCK_START_V61 = ('        if let existing = host, '
                        'let newConfig = config as? UIHostingConfiguration<Content> {')
FAST_BLOCK_END = '            return\n        }\n'


def build_product():
    """完整移植链生成产物(优先), 否则 src/ios 现货。"""
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
            return io.open(os.path.join(dst, COMPAT_REL), encoding='utf-8').read(), 'fullchain@clean'
    return io.open(os.path.join(ROOT, 'src', 'ios', COMPAT_REL), encoding='utf-8').read(), 'src/ios'


def judge(t):
    if t.count('[V61-REUSE]') != 2:
        return False, '[V61-REUSE] 应恰 2 处, 实测 %d' % t.count('[V61-REUSE]')
    if t.count('[V61-MONO]') != 3:
        return False, '[V61-MONO] 应恰 3 处, 实测 %d' % t.count('[V61-MONO]')
    if FAST_KEY not in t:
        return False, '快速路径 rootView 缺 maxWidth 修饰(理想宽回潮)'
    i_fast = t.find('[V61-REUSE] 就地更新快速路径')
    i_rebuild = t.find('subviews.forEach { $0.removeFromSuperview() }')
    if not (0 < i_fast < i_rebuild):
        return False, '快速路径未排在重建路径之前'
    if 'ios15MonoHW = width' not in t or 'ios15MonoH - 8' not in t:
        return False, '锁生效点逻辑不完整(缺宽绑定/容差)'
    if MONO_TAIL not in t:
        return False, '单调锁生效点整块缺失'
    # 重建路径重置锚点必须用 ios15MonoHW = 0: 锁尾部(479)含子串
    # "ios15MonoH = 0"(ios15MonoHW = width; ios15MonoH = 0), find 会误命中,
    # 而 "ios15MonoHW = 0" 全文件唯一(重建重置独有)。
    i_reset = t.find('ios15MonoHW = 0')
    i_hostc = t.find('host = controller')
    if not (0 < i_hostc < i_reset):
        return False, '重建路径缺锁重置(复用串扰 → 矮消息大空白)'
    return True, 'v61 五层全过'


def _extract_if_block(t, start_key):
    """从 start_key 行起, 按花括号配平摘出整个 if 块文本与区间。"""
    i = t.find(start_key)
    if i < 0 or t.count(start_key) != 1:
        return None
    ls = t.rfind('\n', 0, i) + 1
    depth = 0
    j = i
    while j < len(t):
        if t[j] == '{':
            depth += 1
        elif t[j] == '}':
            depth -= 1
            if depth == 0:
                le = t.find('\n', j) + 1
                return ls, le
        j += 1
    return None


def s1_drop_fast_path(x):
    """S1: 删掉 apply 快速路径整块 —— rebuild 风暴复活。

    ★两种形态都接受: v61 原形态与 v63 加了 config 判等的形态。
      写死任一形态都会在下一版加条件时再次空测 —— 而空测会被
      「本条无效」一句话轻轻带过, 于是判据链少了一条守门却仍全绿。
      ⇒ 宁可模糊匹配, 不可锚死形态。
    """
    span = None
    for start in (FAST_BLOCK_START, FAST_BLOCK_START_V61):
        span = _extract_if_block(x, start)
        if span:
            break
    if not span:
        return x, '锚点缺失'
    # 连同前面的注释行一起删
    ls, le = span
    prev = x.rfind('\n', 0, x.rfind('// [V61-REUSE]', 0, ls)) if '// [V61-REUSE]' in x[:ls] else ls
    start = x.rfind('\n', 0, x.rfind('// [V61-REUSE]', 0, ls)) + 1
    return x[:start] + x[le:], '摘快速路径'


def s2_drop_mono_tail(x):
    """S2: 摘掉单调锁生效点整块。"""
    if MONO_TAIL not in x:
        return x, '锚点缺失'
    return x.replace(MONO_TAIL,
                     '        return CGSize(width: width, height: max(0, height))', 1), '摘锁生效点'


def s3_zero_tolerance(x):
    """S3: 容差 -8 改 -0 —— 合法微缩也被锁死。"""
    if 'height < ios15MonoH - 8' not in x:
        return x, '锚点缺失'
    return x.replace('height < ios15MonoH - 8', 'height < ios15MonoH - 0', 1), '容差改 0'


def s4_drop_reset(x):
    """S4: 删重建路径的锁重置 —— 复用串扰(矮消息沿用高消息)。"""
    key = """        // [V61-MONO] 走到重建路径 = 内容标识换了(新消息/复用), 锁重置。
        ios15MonoH = 0
        ios15MonoHW = 0
"""
    if key not in x:
        return x, '锚点缺失'
    return x.replace(key, '', 1), '删重建路径锁重置'


def s5_bare_rootview(x):
    """S5: 快速路径 rootView 不带 maxWidth —— 理想宽回潮通道。"""
    if FAST_KEY not in x:
        return x, '锚点缺失'
    return x.replace(FAST_KEY, 'existing.rootView = AnyView(newConfig.content', 1) \
        .replace('_ios15ContentMaxW2, alignment: .leading))\n            return',
                 ')\n            return', 1), '快速路径裸 rootView'


SABOTAGE = [
    ('BASE 基线', lambda x: (x, '')),
    ('S1 摘 apply 快速路径', s1_drop_fast_path),
    ('S2 摘单调锁生效点', s2_drop_mono_tail),
    ('S3 容差改 0', s3_zero_tolerance),
    ('S4 删重建路径锁重置', s4_drop_reset),
    ('S5 快速路径裸 rootView', s5_bare_rootview),
]


def main():
    print('=' * 62)
    print('v61 反向测试（整屏跳动: REUSE 快速路径 + MONO 单调锁）')
    print('=' * 62)
    prod, origin = build_product()
    print('产物来源: %s (%d 字符)' % (origin, len(prod)))

    caught = passed = voided = 0
    for name, fn in SABOTAGE:
        mutated, desc = fn(prod)
        if mutated == prod and not name.startswith('BASE'):
            # ★纪律第 10 条: 锚点失效必须**自己报错**, 且必须算失败。
            #   此前这里把锚点缺失计入 `passed` 再 continue ——
            #   而 `passed` 的语义是"漏过", 结尾又按 passed==0 判成败,
            #   于是 "4 拦下 + 1 空测 = 5" 被当成全过, **空测当成了通过**。
            #   v63 加了 config 判等 ⇒ S1 锚点落空 ⇒ run#156 就是这样
            #   一路绿到 CI 才在别处炸出来。空测必须显式变红。
            print('  ✗ %-24s 锚点缺失 —— 本条**空测**, 结果不作数(记失败)' % name)
            print('     ★这说明产物结构变了而本脚本没跟上。'
                  '空测比红更危险: 它让判据链少一条守门却仍显示全绿。')
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
    print('v61 反向: %d 拦下, %d 漏过, %d 空测（共 %d 条 sabotage）'
          % (caught, passed, voided, n))
    if voided:
        print('★ 有 %d 条空测 —— 结果不作数, 修锚点或修产物。' % voided)
    return 0 if (passed == 0 and voided == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
