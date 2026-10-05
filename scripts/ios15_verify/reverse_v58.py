# -*- coding: utf-8 -*-
"""v58 反向测试 —— 「纠偏后必须重排」这一条到底拦不拦得住真错。

【v58 要防的具体形态（每条都是本项目真实翻过的车）】

  F1  只写容器宽、不重排  ← **这正是 v57.1**，装机 30+ 版没修好就是它。
      机理：NSTextContainer.size.width 只改容器，不动**已排好的行碎片**。
      表现：宽 358 的框里摆着按 390 排的行 ⇒ 整行右段被切掉（卡字），
            且 usedRect 只有 258.7 而 needH 是 387 ⇒ 欠 6 行高度。
  F2  重排写在 `if _v570Dirty` **之外** —— 表面"修好了"，实则每帧全量重排
      ⇒ 滑动时主线程被排版吃满（用户说的"滑动时整体画面都在动"）。
  F3  重排写在块**之后** —— 永不执行，与 F1 等价但更难看出来。
  F4  诊断改成回读 textContainer 宽度冒充脏值 ⇒ 永远打 reflow=0，
      用户看日志以为"没触发"，实际是探针在骗人。
  F5  顺手把 invalidateLayout 换成 invalidateDisplay / ensureLayout 等
      语义不同的调用（换实现而非加逻辑 ⇒ 最危险的形态）。
  F6  v58 段内顺手改 frame/bounds/height ⇒ 推翻 v41/v45/v51 的成果。
  F7  注释里写出别的判据的锚点字面量（纪律54/55）—— 这两条**本版真实
      把 CI 弄红过**：v49 3/12 未拦、v50 计数变 6。判据自己必须能拦。

【为什么判据要独立于 fallback】
  直接 import fallback 的 verify 等于"自己验自己"：verify 里的锚点串一旦
  与注入串一起被改坏，两边一起绿。这里刻意不 import —— 从干净上游重跑
  fallback 拿到产物，再用本文件里**手写复制的字面量**去判。
"""
import io
import os
import re
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream_base import upstream_ios  # noqa: E402  唯一的上游解析入口

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FB = os.path.join(ROOT, 'scripts', 'ios15_fallback.py')

# ---- 与 V58_ANCHOR_OLD 逐字一致（这是**注入前**的形态，v57.1 的病根）----
OLD_BLOCK = '''            let _v570NetW = max(200.0, cvW - 32)
            let _v570Dirty = abs(self.textContainer.size.width - _v570NetW) > 1
            if _v570Dirty {
                self.textContainer.size.width = _v570NetW
            }'''

MARK = '[V58-REFLOW]'
DIAG_MARK = '[V58-REFLOW-DIAG]'
DIAG_FMT = '[V58-REFLOW] reflow=%d netW='
INVOKE = 'layoutManager.invalidateLayout('
V49_ANCHOR = '// [V49-WWRITER-KVO]'

# 纪律54/55 的两个「敏感物质」，**用拼接构造**，不在这份文件里留字面量
_PROBE_H = 'self.textContainer' + '.size' + '.height'
_PROBE_W = 'textContainer' + r'\.size\.width\s*='


# ----------------------------------------------------------------------
# 产物获取：跑 fallback 从干净上游生成
# ----------------------------------------------------------------------
def build_product():
    up = upstream_ios(quiet=True)
    if up and os.path.isdir(up):
        with tempfile.TemporaryDirectory() as td:
            dst = os.path.join(td, 'src', 'ios')
            os.makedirs(dst, exist_ok=True)
            subprocess.run(['cp', '-r', os.path.join(up, '.'), dst], check=True)
            r = subprocess.run([sys.executable, FB, dst],
                               capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError('fallback 从干净上游跑失败:\n' + r.stderr[-3000:])
            p = os.path.join(dst, 'Views', 'Chat', 'SelectableMarkdownView.swift')
            if os.path.isfile(p):
                return io.open(p, encoding='utf-8').read(), 'fallback@clean'
    p = os.path.join(ROOT, 'src', 'ios', 'Views', 'Chat',
                     'SelectableMarkdownView.swift')
    return io.open(p, encoding='utf-8').read(), 'src/ios'


# ----------------------------------------------------------------------
# 外部判据（不 import fallback）
# ----------------------------------------------------------------------
def _code_only(t):
    """剥掉注释 —— ★判据与 sabotage 都必须先剥注释★
    纪律54/55 的本质: 判据锚点串是**代码级**敏感物质, 注释同样会被搜命中。
    不剥就会把说明文字当成罪证(本项目在 v566/v58 上各踩一次)。"""
    return re.sub(r'//[^\n]*', '', re.sub(r'/\*.*?\*/', '', t, flags=re.S))


def _diag_lines(t, ln_end):
    """返回 v58 诊断块的**行列表**（从其 do { 到日志点那一行，含）。

    ★上界用**日志点行**而不是 [V58-REFLOW-DIAG] 标记★ —— 后者落在块首的
      注释里, 位置在 `do {` **之前**, 拿它当上界会切出空段(本版第一版踩到)。
    ★下界从纠偏块收尾之后起★ —— 文件里有几十个 do {, 无约束 rfind 会圈进
      几千行无关代码, 基线直接误报红(本版第二版踩到)。
    ★一律行级★ —— 字符偏移会被注释长度带偏(见 sabotage 区的说明)。
    """
    stripped, _raw = _code_lines(t)
    i_log = -1
    for k, ln in enumerate(stripped):
        if ('NSLog("' + MARK) in ln:
            i_log = k
            break
    if i_log < 0:
        return None
    for k in range(ln_end + 1, i_log):
        if 'do {' in stripped[k]:
            return stripped[k:i_log + 1]
    return None


def judge(t):
    """返回 (通过?, 失败原因)。"""
    if MARK not in t:
        return False, '缺少 %s 标记 —— 注入没到位' % MARK
    if DIAG_MARK not in t:
        return False, '缺少 %s 纯诊断' % DIAG_MARK
    if DIAG_FMT not in t:
        return False, ('诊断不是 reflow 标记式 —— 回读宽度在纠正之后恒等于 '
                       'netW, 会永远打「全绿」骗人')

    # ★F1/F2/F3 三层一律用**行级**定位★ —— 字符偏移分不清「块内/块外/块后」,
    #   只会把三种形态都报成同一句(本版实测 S1/S2/S3 全报 F2/F3)。
    stripped, _raw = _code_lines(t)
    ln_blk, ln_inv, ln_end = _v58_line_span(t)
    if ln_blk < 0 or ln_end < 0:
        return False, '找不到 `if _v570Dirty {` 块(或缩进异常)'
    if ln_inv < 0:
        # 块内没有重排。但要区分「本来就没写」与「写到块外去了」——
        # 后者才是 F2/F3。全文(剥注释后)还有没有同名调用?
        rest = stripped[ln_end + 1:]
        elsewhere = any(INVOKE in l for l in rest[:400])
        if elsewhere:
            return False, ('★F2/F3★ invalidateLayout 不在 `if _v570Dirty` 块内'
                           ' —— 块外=每帧全量重排(掉帧); 块后=永不执行'
                           '(等价于 v57.1 的病)')
        return False, ('★F1★ 纠偏块里没有 invalidateLayout —— '
                       '这就是 v57.1 的病: 只改容器宽, 行碎片不重排 ⇒ 卡字')
    # 全量范围实参(F5) —— 逐行看, 与块边界同一坐标系
    seg_inv = '\n'.join(stripped[ln_inv:ln_end + 1])
    if not re.search(r'forCharacterRange:\s*NSMakeRange\(0,\s*'
                     r'self\.textStorage\.length\),\s*'
                     r'actualCharacterRange:\s*nil\)', seg_inv):
        return False, ('★F5★ 块内 invalidateLayout 的实参不是全量范围 —— '
                       '半截范围排不掉已被切断的行碎片')

    # 诊断块不得对几何量做写入（F6）
    code = _diag_lines(t, ln_end)
    if code is None:
        return False, '纠偏块之后找不到诊断块的 do { 包裹'
    for ln in code:
        # ★必须连**复合赋值**一起拦★ —— 只匹配裸 `=` 时,
        #   `self.frame.size.height += x` 整条溜过去(本版实测 S6 漏过)。
        #   右侧比较(==/!=/>=/<=)不误伤: `=` 后面跟的是 `=`<(?!=) 已经排掉。
        mm = re.match(r'\s*([\w.]+)\s*(?:[-+*/%&|^]|<<|>>)?=(?!=)', ln)
        if not mm:
            continue
        lhs = mm.group(1)
        # ★白名单必须**逐条列举**, 不能用 `endswith('.width'/'.height')` ★
        #   —— 那等于放行一切「对 .height/.width 的赋值」, 于是
        #   `self.frame.size.height += x` 这类最该拦的写法会整条溜过去
        #   (本版实测: S6 因此漏过)。S6 抓的就是这个。
        #   只放行: ① 本段唯一允许的几何写入 ② 节流器自己的状态字段。
        if lhs == 'self.textContainer.size.width':
            continue
        if lhs.startswith('_V58Log.'):
            continue
        return False, '★F6★ 诊断块内改了几何量: %s' % lhs

    # 纪律54: v58 段整块位于 v49 探针**之前**，不得出现 size.height 成员访问。
    # ★窗口必须覆盖「v58 段起点 → v49 探针」整段, 不能只从 DIAG 标记起算
    #   固定长度★ —— 注释写在标记之前(那是最自然的写法)就滑出窗口,
    #   判据会漏过(本版实测 S7 第一版就是这么漏的)。
    i_v49 = t.find(V49_ANCHOR)
    if i_v49 < 0:
        return False, '找不到 v49 探针锚点 —— 纪律54 层无法判定'
    i_v58 = t.find('let _v570NetW = ')
    if i_v58 < 0:
        return False, '找不到 _v570NetW 声明 —— 纪律54 层无法定位 v58 段'
    if i_v58 < i_v49:
        if _PROBE_H in t[i_v58:i_v49]:
            return False, ('★F7/纪律54★ v58 段(在 v49 探针之前)出现 '
                           'size.height 成员访问(连注释也不行) ⇒ v49 的 '
                           'S7/S8/S12 变异体会被吸走 ⇒ v49 判据失效')

    # 纪律55: 全文数「容器宽赋值」字面量，必须恰好 5 处
    n = len(re.findall(_PROBE_W, t))
    if n != 5:
        return False, ('★F7/纪律55★ 全文「容器宽赋值」字面量 %d 处, 应为 5 '
                       '(codeTextView 1 + v18 3 + v57.0 KVO 1) —— '
                       '注释里写一次也会被计入(本版真实把 v50 弄红过)' % n)

    return True, 'v58 六层全过'


# ----------------------------------------------------------------------
# Sabotage —— 每条对应上面一个 F 形态
# ----------------------------------------------------------------------
# ★★ 全部 surgery 走**行级**操作 ★★
#   原因(本版实测踩到): 判据内部要先剥注释才能定位到真正的代码, 而剥注释
#   会改变所有偏移量。若在「剥注释后的偏移」上切片原文, 切到的就是**别处**
#   —— S1/S5/S6 三条同时漏过, 症状还各不相同(删了重排却仍在段内计数 1、
#   换 API 换到了别处、插 frame 插到别的地方)。
#   行级手术对注释长度免疫, 是唯一可靠的写法。
def _code_lines(t):
    """返回 (剥注释后的行列表, 原始行列表)。两列表**行数与行号一一对应**
    —— `_code_only` 只做行内删除, 不增删换行, 因此行号是稳定的桥。"""
    raw = t.split('\n')
    stripped = _code_only(t).split('\n')
    assert len(raw) == len(stripped), '剥注释改变了行数, 行级桥失效'
    return stripped, raw


def _v58_line_span(src):
    """v58 纠偏块的行号区间 [起, 尾]（含），以及块内 invalidateLayout 的行号。

    ★收尾按**行首缩进**找(纪律53)★。返回 (-1,-1,-1) 表示定位失败。
    ★入参接受**整文本**或**已剥注释的行列表**★ —— 内部按类型分派,
      免得调用方为了拿行号还得记得先剥注释(本版就踩过:
      judge 传了整文本进去, 于是逐行都匹配不到, 基线直接红)。
    """
    stripped = _code_lines(src)[0] if isinstance(src, str) else src
    i_blk = -1
    for k, ln in enumerate(stripped):
        if 'if _v570Dirty {' in ln:
            i_blk = k
            break
    if i_blk < 0:
        return -1, -1, -1
    if stripped[i_blk].strip() != 'if _v570Dirty {':
        return -1, -1, -1
    indent = stripped[i_blk][:len(stripped[i_blk]) - len(stripped[i_blk].lstrip())]
    i_end = -1
    for k in range(i_blk + 1, len(stripped)):
        if stripped[k].startswith(indent + '}'):
            i_end = k
            break
    if i_end < 0:
        return -1, -1, -1
    i_inv = -1
    for k in range(i_blk, i_end + 1):
        if INVOKE in stripped[k]:
            i_inv = k
            break
    return i_blk, i_inv, i_end


def _rebuild(raw):
    return '\n'.join(raw)


CALL_LINES = [
    '                layoutManager.invalidateLayout(',
    '                    forCharacterRange: NSMakeRange(0, self.textStorage.length),',
    '                    actualCharacterRange: nil)',
]


def _call_end_span(stripped, i_inv):
    """返回 invalidateLayout 调用占用的行号区间 [起, 尾]（含尾行）。

    ★必须按**配平括号**定位, 不能用 `[^)]*` 正则★ —— 实参里自带括号
      (`NSMakeRange(0, len)`), 正则会在第一个 `)` 处截断, 只删掉半句,
      留下 `, actualCharacterRange: nil)` 悬在块里(本版第一版 S1/S2/S3
      全因此"被 F5 层拦下"而不是被 F1 拦下 —— 拦住了但报错了层)。
    """
    depth = 0
    started = False
    for k in range(i_inv, len(stripped)):
        for ch in stripped[k]:
            if ch == '(':
                depth += 1
                started = True
            elif ch == ')':
                depth -= 1
        if started and depth == 0:
            return i_inv, k
    return -1, -1


def s1_no_reflow(x):
    """F1: 摘掉 invalidateLayout = 回到 v57.1 形态(★v57.1 的病, 最该拦的一条)。"""
    stripped, raw = _code_lines(x)
    i_blk, i_inv, i_end = _v58_line_span(stripped)
    if i_inv < 0:
        return x, '锚点缺失'
    a, b = _call_end_span(stripped, i_inv)
    if a < 0:
        return x, '锚点缺失'
    del raw[a:b + 1]
    return _rebuild(raw), '删掉重排'


def s2_reflow_outside(x):
    """F2: 把重排挪到块外(仍在同一函数内) —— 每帧全量重排 ⇒ 掉帧。"""
    stripped, raw = _code_lines(x)
    i_blk, i_inv, i_end = _v58_line_span(stripped)
    if i_inv < 0:
        return x, '锚点缺失'
    a, b = _call_end_span(stripped, i_inv)
    if a < 0:
        return x, '锚点缺失'
    call = raw[a:b + 1]
    del raw[a:b + 1]
    # 插到纠偏块收尾(原 i_end 行)之后
    raw[i_end:i_end] = [ln.replace(' ' * 16, ' ' * 8, 1) for ln in call]
    return _rebuild(raw), '重排挪到块外'


def s3_reflow_after(x):
    """F3: 把重排挪到 v44 探针之后 —— 位置对但顺序在纠偏之前, 等于不重排。"""
    stripped, raw = _code_lines(x)
    i_blk, i_inv, i_end = _v58_line_span(stripped)
    if i_inv < 0:
        return x, '锚点缺失'
    a, b = _call_end_span(stripped, i_inv)
    if a < 0:
        return x, '锚点缺失'
    call = raw[a:b + 1]
    del raw[a:b + 1]
    for k, ln in enumerate(raw):
        if '[V44-TEXTFRAME' in ln:
            raw[k:k] = [c.replace(' ' * 16, ' ' * 8, 1) for c in call]
            return _rebuild(raw), '重排挪到 v44 之后'
    return x, '锚点缺失'


def s4_diag_fake(x):
    """F4: 诊断改成回读容器宽冒充脏值。"""
    if DIAG_FMT not in x:
        return x, '锚点缺失'
    return x.replace(DIAG_FMT, '[V58-REFLOW] tcW=%d netW=', 1), '诊断回读冒充'


def s5_wrong_api(x):
    """F5: 换成语义不同的调用(invalidateDisplay)。"""
    stripped, raw = _code_lines(x)
    i_blk, i_inv, i_end = _v58_line_span(stripped)
    if i_inv < 0:
        return x, '锚点缺失'
    a, b = _call_end_span(stripped, i_inv)
    if a < 0:
        return x, '锚点缺失'
    raw[a] = raw[a].replace('invalidateLayout', 'invalidateDisplay')
    return _rebuild(raw), '换 API'


def s6_touch_frame(x):
    """F6: 在 v58 诊断块内顺手改 frame 高度 —— 推翻 v41/v45/v51。"""
    stripped, raw = _code_lines(x)
    i_blk, i_inv, i_end = _v58_line_span(stripped)
    if i_end < 0:
        return x, '锚点缺失'
    # 诊断块的 do { 在纠偏块收尾之后、日志点之前
    i_log = -1
    for k, ln in enumerate(stripped):
        if ('NSLog("' + MARK) in ln:
            i_log = k
            break
    if i_log < 0:
        return x, '锚点缺失'
    i_do = -1
    for k in range(i_end + 1, i_log):
        if 'do {' in stripped[k]:
            i_do = k
    if i_do < 0:
        return x, '锚点缺失'
    pad = ' ' * (len(raw[i_do]) - len(raw[i_do].lstrip()))
    # ★必须插在 `do {` **之后**★ —— 判据的诊断段是「do { 到日志点」,
    #   插在 do 之前就落在段外, 变异体不在判据视野内(本版实测漏过)。
    raw[i_do + 1:i_do + 1] = [pad + '    let _v58Bad = 1.0',
                             pad + '    self.frame.size.height += _v58Bad']
    return _rebuild(raw), '段内改 frame 高度'


def s7_comment_height(x):
    """F7/纪律54: 注释里写出 size.height 成员访问。

    ★插在 DIAG 标记那一行**之前**★ —— 判据的纪律54 窗口覆盖「v58 段起点 →
      v49 探针」整段, 但 sabotage 必须落在最容易被写到的位置才能证明窗口够大
      (本版第一版插在标记之后, 判据窗口只从标记起算 ⇒ 漏过)。
    """
    i = x.find(DIAG_MARK)
    if i < 0:
        return x, '锚点缺失'
    ls = x.rfind('\n', 0, i) + 1
    pad = x[ls:i]
    return (x[:ls] + pad + '// 参考: self.textContainer.size.height 已由 v44 记录\n'
            + x[ls:], '注释里写 height 锚点串')


def s8_comment_width(x):
    """F7/纪律55: 注释里写出「容器宽赋值」完整字面量。"""
    i = x.find('let _v570NetW = ')
    if i < 0:
        return x, '锚点缺失'
    ls = x.rfind('\n', 0, i) + 1
    pad = x[ls:i]
    return (x[:ls] + pad + '// 旧写法 textContainer.size.width = X 已废弃\n'
            + x[ls:], '注释里写宽度赋值字面量')


SABOTAGE = [
    ('BASE 基线', lambda x: (x, '')),
    ('S1 摘掉重排(=v57.1)', s1_no_reflow),
    ('S2 重排挪到块外', s2_reflow_outside),
    ('S3 重排挪到 v44 之后', s3_reflow_after),
    ('S4 诊断回读冒充脏值', s4_diag_fake),
    ('S5 换 invalidateDisplay', s5_wrong_api),
    ('S6 段内改 frame 高度', s6_touch_frame),
    ('S7 注释写 height 锚点(纪律54)', s7_comment_height),
    ('S8 注释写宽度赋值字面量(纪律55)', s8_comment_width),
]


def main():
    print('=' * 64)
    print('v58 反向测试（纠偏后必须重排 —— 卡字/掉帧的支点）')
    print('=' * 64)
    prod, origin = build_product()
    print('产物来源: %s (%d 字符)' % (origin, len(prod)))

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
            print('  ✗ %-34s 锚点缺失 —— 本条**空测**, 结果不作数(记失败)' % name)
            voided += 1
            continue
        ok, why = judge(mutated)
        if name.startswith('BASE'):
            if ok:
                print('  ✅ %-34s 基线通过' % name)
            else:
                print('  ❌ %-34s 基线就红: %s' % (name, why))
                return 1
            continue
        if ok:
            print('  ❌ %-34s 漏过（%s）' % (name, desc))
            passed += 1
        else:
            print('  ✅ %-34s 拦下: %s' % (name, why[:74]))
            caught += 1

    n = len(SABOTAGE) - 1
    print('-' * 64)
    print('v58 反向: %d 拦下, %d 漏过, %d 空测（共 %d 条 sabotage）'
          % (caught, passed, voided, n))
    if voided:
        print('★ 有 %d 条空测 —— 结果不作数, 修锚点或修产物。' % voided)
    return 0 if (passed == 0 and voided == 0) else 1


if __name__ == '__main__':
    sys.exit(main())
