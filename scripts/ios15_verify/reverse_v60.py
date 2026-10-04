# -*- coding: utf-8 -*-
"""v60 反向测试 —— zhaoxiufei 3ccdff6 已验证方案(宽跟随保留+sane 推导链)。

v60 取代 v59: 保留 widthTracksTextView=true(上游默认), 通过 hosting 层
sizeThatFits 重写 + TextView 的 sizeThatFits/intrinsicContentSize 重写
(sane 宽推导链+漂移重置) + init/makeUIView/updateUIView 三处兜底 +
CodeBlockAttachment 三级 fallback, 保证 frame 恒 sane。

【每条 sabotage 对应一个真实可能犯的错】
  S1  摘掉 TextView sizeThatFits 的 override  ← 推导链整条失效, 回到
      「frame 被撑到 390 → 跟随派生 390」的天花板(本版治的病)
  S2  intrinsicContentSize 换回 v21 钳宽版    ← 先按 1e5 排再钳=白排一次,
      且与新版重复声明=编译失败 / 理想宽泄漏通道重开
  S3  init 的 true 改回 false(v59 残魂)       ← 断源复辟: 与 KVO 纠偏
      抢写容器宽, 两个主子打架
  S4  删 makeUIView 初值兜底                  ← 首帧容器宽 = 1e7 默认值,
      首趟排版排成一行超长
  S5  删 updateUIView 垃圾宽兜底              ← 上一趟写坏的宽直接进本轮排版
  S6  摘掉 hosting sizeThatFits 的 override   ← 父视图走 sizeThatFits 路径
      时报垃圾理想宽, cell 高度错位
  S7  推导链阈值 100_000 改成 1e9             ← 1e5 垃圾宽被当 sane 放行
  S8  漂移重置 >0.5 改成 >500                 ← 容器宽漂 499pt 都不重置
  S9  CB return 改回裸 width                  ← 代码块按垃圾宽量高,
      末行裁断/大空白复发
  S10 makeView 去掉 min-50                    ← usableWidth 极端时 contentWidth
      ≤0, 代码块塌成零宽
"""
import io
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FB = os.path.join(ROOT, 'scripts', 'ios15_fallback.py')

MD_REL = os.path.join('Views', 'Chat', 'SelectableMarkdownView.swift')
COMPAT_REL = 'iOS15Compat.swift'

MK_INIT = '[V60-ZHAO-INIT]'
MK_FIT = '[V60-ZHAO-FIT]'
MK_CB = '[V60-ZHAO-CB]'
MK_MAKE = '[V60-ZHAO-MAKE]'
MK_UPD = '[V60-ZHAO-UPD]'
MK_HOST = '[V60-ZHAO-HOST]'

TRUE_LINE = '        textContainer.widthTracksTextView = true'
FALSE_LINE = '        textContainer.widthTracksTextView = false'

V21_BLOCK = """    override var intrinsicContentSize: CGSize {
        let sz = super.intrinsicContentSize
        let cvW = findCollectionView()?.bounds.width ?? 0
        let cap = cvW > 33 ? cvW - 32 : sz.width
        let w = (cap > 1 && sz.width > cap) ? cap : sz.width
        return CGSize(width: w, height: sz.height)
    }"""

MAKE_BLOCK = """        // [V60-ZHAO-MAKE] 初建即 sane(zhaoxiufei 3ccdff6 同款):
        // SwiftUI 首趟布局问尺寸时容器宽已是净宽, 不再从 1e7 初值起步。
        let defaultWidth = UIScreen.main.bounds.width - 32
        textView.textContainer.size = CGSize(width: defaultWidth, height: .greatestFiniteMagnitude)
"""

UPD_BLOCK_START = '        // [V60-ZHAO-UPD] 每次更新前容器宽 sane 兜底'


def build_product():
    """从干净上游跑**完整移植链**生成产物(优先), 否则用 src/ios 现货。

    ★v60 判据覆盖 iOS15Compat.swift —— 该文件是 ios15_port_v2.py 生成的,
      不是上游自带; 所以不能像 v59 那样只跑 fallback, 必须四步全跑。
      port_v2/runtime_fixes 硬编码 cwd 相对路径 src/ios ⇒ 临时目录必须
      是 <td>/src/ios 且 cwd=<td>。
    """
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
            md = io.open(os.path.join(dst, MD_REL), encoding='utf-8').read()
            ct = io.open(os.path.join(dst, COMPAT_REL), encoding='utf-8').read()
            return md, ct, 'fullchain@clean'
    base = os.path.join(ROOT, 'src', 'ios')
    md = io.open(os.path.join(base, MD_REL), encoding='utf-8').read()
    ct = io.open(os.path.join(base, COMPAT_REL), encoding='utf-8').read()
    return md, ct, 'src/ios'


def judge(md, compat):
    """与 fallback 内 verify_zhao_md_v60 / verify_zhao_compat_v60 同强度。"""
    # L1 init
    if md.count(MK_INIT) != 1:
        return False, '缺 %s(应恰 1)' % MK_INIT
    i = md.find(MK_INIT)
    if 'defaultWidth' not in md[i:i + 600] or '.greatestFiniteMagnitude' not in md[i:i + 600]:
        return False, 'init 窗口缺 sane 初值两行'
    # L2 fit 块
    if md.count(MK_FIT) != 1:
        return False, '缺 %s(应恰 1)' % MK_FIT
    i = md.find(MK_FIT)
    tail = md[i:i + 3500]
    if 'override func sizeThatFits(_ size: CGSize) -> CGSize' not in tail:
        return False, '窗口内无 sizeThatFits 重写'
    if 'override var intrinsicContentSize' not in tail:
        return False, '窗口内无 intrinsicContentSize 重写'
    if 'size.width > 1 && size.width < 100_000' not in tail:
        return False, '推导链缺垃圾宽拦截(100_000)'
    if '> 0.5 {' not in tail:
        return False, '缺漂移重置(>0.5)分支'
    if 'ceil(fit.height)' not in tail:
        return False, '缺 ceil 高度对齐'
    if 'noIntrinsicMetric' not in tail:
        return False, '宽未退出协商(noIntrinsicMetric)'
    # L3 intrinsic 唯一 + v21 特征清零
    n_intr = md.count('override var intrinsicContentSize')
    if n_intr != 1:
        return False, ('intrinsicContentSize override %d 处(应 1) —— '
                       'v21 旧版没替换干净=重复声明编译失败' % n_intr)
    if 'let sz = super.intrinsicContentSize' in md:
        return False, 'v21 旧版特征仍在(先按 1e5 排再钳)'
    if md.count('noIntrinsicMetric') < 2:
        return False, 'noIntrinsicMetric 应 ≥2(宽+高)'
    # L4 make/update 兜底
    if md.count(MK_MAKE) != 1:
        return False, '缺 %s' % MK_MAKE
    if md.count(MK_UPD) != 1:
        return False, '缺 %s' % MK_UPD
    i = md.find(MK_UPD)
    if 'fallbackW' not in md[i:i + 500]:
        return False, 'updateUIView 兜底体缺失'
    # L5 v59 退场核账
    n_true = md.count('textContainer.widthTracksTextView = true')
    n_false = md.count('widthTracksTextView = false')
    if n_true != 2:
        return False, ('跟随宽 %d 处(应 2: init+表格) —— 0/1=v59 残魂或 init '
                       '没恢复 true; >2=上游新增未登记' % n_true)
    if n_false != 1:
        return False, ('关闭跟随 %d 处(应 1: codeTextView v4) —— '
                       '>1=v59 断源残魂' % n_false)
    if '[V59-NOTRACK]' in md:
        return False, '[V59-NOTRACK] 仍在 —— v59 必须整体退场'
    # L6 CodeBlock 三处
    if md.count(MK_CB) != 3:
        return False, ('%s 应恰 3 处(attachmentBounds/makeView/scrollWidth), '
                       '实测 %d' % (MK_CB, md.count(MK_CB)))
    if md.count('width: effectiveWidth') != 1:
        return False, 'CB return 未改 effectiveWidth'
    if 'max(usableWidth - inset, 50)' not in md:
        return False, 'makeView 缺 min-50 兜底'
    if 'max(container.frame.width, 50)' not in md:
        return False, 'scrollWidth 缺 min-50 兜底'
    # L7 CB 阈值
    if 'lineFrag.width < 100_000' not in md:
        return False, 'CB 三级 fallback 阈值被动过'
    # compat 三层
    if compat.count(MK_HOST) != 1:
        return False, 'compat 缺 %s' % MK_HOST
    if compat.count('override func sizeThatFits(_ size: CGSize) -> CGSize') != 1:
        return False, 'compat hosting sizeThatFits 重写缺失/重复'
    i = compat.find(MK_HOST)
    tail = compat[i:i + 1200]
    if 'ceil(fitSize.height)' not in tail or 'host.view.sizeThatFits' not in tail:
        return False, 'compat 重写体不完整(缺 ceil/host 调用)'
    return True, 'v60 十层全过'


def _del_block(x, start_line, n_lines):
    """从 start_line(精确行文本)起删 n_lines 行。锚点必须唯一。"""
    if x.count(start_line) != 1:
        return x
    i = x.find(start_line)
    ls = x.rfind('\n', 0, i) + 1
    for _ in range(n_lines):
        le = x.find('\n', ls)
        if le < 0:
            return x
        ls = le + 1
    return x[:x.rfind('\n', 0, x.find(start_line)) + 1] + x[ls:]


def s1_drop_stf_override(x):
    """S1: 摘掉 TextView sizeThatFits 的 override(降级成死代码)。"""
    a, b = x
    key = '    override func sizeThatFits(_ size: CGSize) -> CGSize {'
    if a.count(key) != 1:
        return (a, b), '锚点缺失'
    return (a.replace(key, '    private func sizeThatFitsZhaoded(_ size: CGSize) -> CGSize {', 1), b), \
        '摘 TextView sizeThatFits override'


def s2_restore_v21(x):
    """S2: intrinsicContentSize 换回 v21 钳宽版(模拟回退)。"""
    a, b = x
    i = a.find(MK_FIT)
    if i < 0:
        return (a, b), '锚点缺失'
    # 新块: 从 [V60-ZHAO-FIT] 注释行起, 到 intrinsicContentSize 的收尾 `    }`
    ls = a.rfind('\n', 0, i) + 1
    end_key = 'return CGSize(width: UIView.noIntrinsicMetric, height: ceil(fit.height))'
    j = a.find(end_key, ls)
    if j < 0:
        return (a, b), '锚点缺失'
    le = a.find('\n', j) + 1          # return 行尾
    le = a.find('\n', le) + 1         # `    }` 行尾
    return (a[:ls] + V21_BLOCK + '\n' + a[le:], b), '换回 v21 钳宽版'


def s3_v59_ghost(x):
    """S3: init 的 true 改回 false(v59 残魂) —— 断源复辟。"""
    a, b = x
    if a.count(TRUE_LINE) != 2:
        return (a, b), '锚点缺失'
    # 改 init 那处(带 super.init 指纹的), 模拟有人手滑恢复 v59
    key = TRUE_LINE + '\n        // ' + MK_INIT
    if key not in a:
        return (a, b), '锚点缺失'
    return (a.replace(key, FALSE_LINE + '\n        // ' + MK_INIT, 1), b), \
        'init 改回 false(v59 残魂)'


def s4_drop_make(x):
    """S4: 删 makeUIView 初值兜底 —— 首帧从 1e7 默认值起步。"""
    a, b = x
    if a.count(MK_MAKE) != 1:
        return (a, b), '锚点缺失'
    return (a.replace(MAKE_BLOCK, '', 1), b), '删 makeUIView 兜底'


def s5_drop_upd(x):
    """S5: 删 updateUIView 垃圾宽兜底块。"""
    a, b = x
    i = a.find(UPD_BLOCK_START)
    if i < 0:
        return (a, b), '锚点缺失'
    ls = a.rfind('\n', 0, i) + 1
    end_key = 'textView.textContainer.size = CGSize(width: fallbackW, height: .greatestFiniteMagnitude)'
    j = a.find(end_key, ls)
    if j < 0:
        return (a, b), '锚点缺失'
    le = a.find('\n', j) + 1          # 兜底赋值行尾
    le = a.find('\n', le) + 1         # `        }` 行尾
    return (a[:ls] + a[le:], b), '删 updateUIView 兜底'


def s6_drop_host_override(x):
    """S6: 摘掉 hosting sizeThatFits 的 override。"""
    a, b = x
    key = '    override func sizeThatFits(_ size: CGSize) -> CGSize {'
    if b.count(key) != 1:
        return (a, b), '锚点缺失'
    return (a, b.replace(key, '    private func sizeThatFitsZhaoded(_ size: CGSize) -> CGSize {', 1)), \
        '摘 hosting sizeThatFits override'


def s7_raise_threshold(x):
    """S7: 推导链阈值 100_000 改成 1e9 —— 1e5 垃圾宽被当 sane 放行。"""
    a, b = x
    key = 'let width = size.width > 1 && size.width < 100_000 ? size.width :'
    if a.count(key) != 1:
        return (a, b), '锚点缺失'
    return (a.replace(key,
            'let width = size.width > 1 && size.width < 1000000000 ? size.width :', 1), b), \
        '推导链阈值改 1e9'


def s8_kill_drift_reset(x):
    """S8: 漂移重置 >0.5 改成 >500 —— 漂 499pt 都不重置。"""
    a, b = x
    key = 'if abs(textContainer.size.width - width) > 0.5 {'
    if a.count(key) != 1:
        return (a, b), '锚点缺失'
    return (a.replace(key, 'if abs(textContainer.size.width - width) > 500 {', 1), b), \
        '漂移重置阈值改 500'


def s9_bare_cb_width(x):
    """S9: CB return 改回裸 width —— 代码块按垃圾宽量高。"""
    a, b = x
    key = 'return CGRect(x: 0, y: 0, width: effectiveWidth, height: height)'
    if a.count(key) != 1:
        return (a, b), '锚点缺失'
    return (a.replace(key, 'return CGRect(x: 0, y: 0, width: width, height: height)', 1), b), \
        'CB return 改回裸 width'


def s10_drop_min50(x):
    """S10: makeView 去掉 min-50 —— contentWidth 可能 ≤0。"""
    a, b = x
    key = 'let contentWidth = max(usableWidth - inset, 50)'
    if a.count(key) != 1:
        return (a, b), '锚点缺失'
    return (a.replace(key, 'let contentWidth = usableWidth - inset', 1), b), \
        'makeView 去掉 min-50'


SABOTAGE = [
    ('BASE 基线', lambda x: (x, '')),
    ('S1 摘 TextView sizeThatFits', s1_drop_stf_override),
    ('S2 换回 v21 钳宽版', s2_restore_v21),
    ('S3 init 改回 false(v59 残魂)', s3_v59_ghost),
    ('S4 删 makeUIView 兜底', s4_drop_make),
    ('S5 删 updateUIView 兜底', s5_drop_upd),
    ('S6 摘 hosting sizeThatFits', s6_drop_host_override),
    ('S7 推导链阈值 1e9', s7_raise_threshold),
    ('S8 漂移重置改 500', s8_kill_drift_reset),
    ('S9 CB 裸 width', s9_bare_cb_width),
    ('S10 makeView 去 min-50', s10_drop_min50),
]


def main():
    print('=' * 62)
    print('v60 反向测试（zhaoxiufei 3ccdff6 方案: 宽跟随保留+sane 推导链）')
    print('=' * 62)
    md0, ct0, origin = build_product()
    prod = (md0, ct0)
    print('产物来源: %s (md %d / compat %d 字符)' % (origin, len(md0), len(ct0)))

    caught = passed = 0
    for name, fn in SABOTAGE:
        mutated, desc = fn(prod)
        if mutated == prod and not name.startswith('BASE'):
            print('  ⚠ %-28s 注入未生效(锚点缺失)，本条无效' % name)
            passed += 1
            continue
        ok, why = judge(mutated[0], mutated[1])
        if name.startswith('BASE'):
            if ok:
                print('  ✅ %-28s 基线通过' % name)
            else:
                print('  ❌ %-28s 基线就红: %s' % (name, why))
                return 1
            continue
        if ok:
            print('  ❌ %-28s 漏过（%s）' % (name, desc))
            passed += 1
        else:
            print('  ✅ %-28s 拦下: %s' % (name, why[:66]))
            caught += 1

    n = len(SABOTAGE) - 1
    print('-' * 62)
    print('v60 反向: %d 拦下, %d 漏过（共 %d 条 sabotage）' % (caught, passed, n))
    return 0 if passed == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
