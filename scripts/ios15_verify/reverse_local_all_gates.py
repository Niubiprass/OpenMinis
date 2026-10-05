#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""reverse_local_all_gates.py —— 抽取器自身的反向 sabotage。

【为什么判据脚本还需要被反向测】
CI#161（run 37271671515）的红项**不是判据报红，是抽取器坏了**：
`local_all_gates.py` 把 workflow 里的 `"$GUARD_V65"` 原样抽成字面量
`'"$GUARD_V65"'` 递给判据，判据报
    ❌ [Errno 2] No such file or directory: '"$GUARD_V65"'
这条错**伪装成判据有问题**——看到 ❌ 会本能地去查 v65 判据的逻辑，
实际要修的是抽取器。判据本身在 CI 的全版本回归里是绿的（37/0/0）。

⇒ 抽取器属于判据体系的一部分，必须自己扛得住 sabotage。
  否则「判据全绿」这个前提会在下一个版本悄悄失效。

【本脚本第一版自己踩的坑（§21 同族，值得记住）】
  ★ 写 sabotage 时用 `monkeypatch G.ROOT`，而采集函数里硬引用
    `G.collect_scripts()` —— 于是 9 条 sabotage 全部「结果完全没变」，
    报 9 条漏过。根因不是判据宽，是**测试自己没有真的把改坏的模块跑起来**。
  ★ 修法是让采集函数**显式接收模块对象**，而不是靠改全局状态。
    判据放不宽和 sabotage 设计得对不对，是两件事。
  ★ 同版还写了 `or True` 的假 checker（无论结果如何都判通过），
    那是另一种形式的空测，一并去掉。

【 sabotage 清单（9 条，每条对应抽取器的一项能力）】
  S1  shell 变量未求值(双引号) —— 还原 CI#161 的原样故障
  S2  剥引号只认双引号       —— 单引号参数里的变量解不出
  S3  ${VAR} 花括号形态不识别
  S4  变量表收不到赋值       —— 等价于把整份 workflow 的赋值丢掉
  S5  管道吞进参数           —— 还原 regress_all_v 的抽取故障
  S6  重定向 FD 数字残留     —— `2>&1` 的 `2` 当成参数
  S7  key 用截断前 args      —— 同脚本被判成两条
  S8  剥引号过度             —— 把路径首尾字符误当引号剥掉
  S9  抽取故障被静默当通过   —— main() 里 EXTRACT-FAIL 记 True

【BASE 纪律】
BASE 独立计数，不计入 passed；sabotage 自身失败或 bad == orig 记 voided。
"""
import os
import re
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import local_all_gates as G  # noqa: E402

ORIG_TXT = open(os.path.join(HERE, 'local_all_gates.py'),
                encoding='utf-8').read()

# ★WF 刻意覆盖每种形态，每条 sabotage 都有一个专属观测点。
#   没有专属观测点的 sabotage 测了等于没测（空测）。
#
# ★★观测点是**踩过两轮坑才凑齐的**(§21):
#   第一轮漏 S6/S8/S9 三条 —— 逐条查下去发现都不是判据宽, 是 WF 里
#   **够不着那条被改的路径**:
#     · S6: `2>&1` 是**一个** token(含 `&`), 第一个条件就拦下了 ⇒
#           纯数字分支在 WF 里永远不生效。要观测它必须单独放一个
#           形如 `3` 的裸 FD token。
#     · S8: WF 里没有「首尾相同的路径」(src/... 头 s 尾 m) ⇒ 过度剥引号
#           够不着。要观测它必须放一个首尾相同的 token。
#     · S9: 改的是 `main()` 里的 checks 分支, 而反向只跑 `collect_scripts()`
#           ⇒ **观测面根本不在同一条路径上**, 怎么改都不会被发现。
#           这条改为直接跑 main() 判定(见 s9 与 c9)。
WF = '''jobs:
  t:
    steps:
      - name: a
        run: |
          GUARD_V65="src/ios/Shared/NSTextContainerSetSizeGuard.m"
          SGL='scripts/ios15_fallback.py'
          if python3 "$SCRIPT_DIR/ios15_verify/verify_guard_v65.py" "$GUARD_V65" ; then
            echo ok
          fi
          if python3 "$SCRIPT_DIR/ios15_verify/ci_assert_v64.py" '${SGL}'
          if python3 "$SCRIPT_DIR/ios15_verify/ci_assert_v63.py" ${GUARD_V65}
          if python3 "$SCRIPT_DIR/ios15_verify/regress_all_v.py" . 2>&1 | tee /tmp/o.txt
          if python3 "$SCRIPT_DIR/ios15_verify/regress_all_v.py" .
          if python3 "$SCRIPT_DIR/ios15_verify/ci_assert_v47.py" "$NOT_DEFINED_ANYWHERE"
          # —— 以下两行是 S6 / S8 的专属观测点 ——
          if python3 "$SCRIPT_DIR/ios15_verify/ci_assert_v48.py" . 3
          if python3 "$SCRIPT_DIR/ios15_verify/ci_assert_v49.py" "s"
          if python3 "$SCRIPT_DIR/ios15_verify/ci_assert_v50.py" a/b/c/a
'''


def _items(mod, wf=WF):
    """用**指定模块**跑一遍抽取。

    ★必须显式传模块 —— 不能靠 monkeypatch 原始模块的全局状态:
      第一版就是这么写的, 结果 sabotage 改坏的模块根本没被执行,
      9 条全「结果没变」(§21)。monkeypatch 只能影响「谁被调用」,
      影响不了「被调用的是哪个模块」。
    """
    import tempfile
    import shutil
    d = tempfile.mkdtemp(prefix='gates_sab_')
    try:
        wfd = os.path.join(d, '.github', 'workflows')
        os.makedirs(wfd)
        with open(os.path.join(wfd, 'w.yml'), 'w', encoding='utf-8') as f:
            f.write(wf)
        old_root, old_wf = mod.ROOT, mod.WF_DIR
        mod.ROOT, mod.WF_DIR = d, wfd
        try:
            return mod.collect_scripts()
        finally:
            mod.ROOT, mod.WF_DIR = old_root, old_wf
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _as_map(items, main_src=None):
    """抽成 {rel: [args元组, ...]}；抽取故障收到 __extract_fail__ 下。

    ★额外挂一份 `__main_src__`（main() 的源码）—— S9 改的是 main() 里的
      checks 分支, 而抽取结果在 collect_scripts() 里, 两者**不同一条路径**。
      观测面够不着就会漏过(踩过一次), 所以把 main() 源码也纳入观测面。
    """
    out = {}
    for it in items:
        if len(it) == 3 and it[1] is None:
            out.setdefault('__extract_fail__', []).append(it[2])
            continue
        out.setdefault(it[1], []).append(tuple(it[2]))
    if main_src is not None:
        out['__main_src__'] = [main_src]
    return out


def _args(m, rel):
    return m.get(rel, [])


# ---------------- checker：每条只看自己的专属观测点 ----------------
def c1(m):
    """S1：双引号变量必须求值成真实路径。"""
    return bool(_args(m, 'ios15_verify/verify_guard_v65.py')) and \
        _args(m, 'ios15_verify/verify_guard_v65.py')[0] == \
        ('src/ios/Shared/NSTextContainerSetSizeGuard.m',)


def c2(m):
    """S2：单引号包住的变量也要剥引号并求值。"""
    lst = _args(m, 'ios15_verify/ci_assert_v64.py')
    return bool(lst) and lst[0] == ('scripts/ios15_fallback.py',)


def c3(m):
    """S3：${VAR} 形态要能求值（ci_assert_v63 用的是裸 ${GUARD_V65}）。"""
    lst = _args(m, 'ios15_verify/ci_assert_v63.py')
    return bool(lst) and lst[0] == ('src/ios/Shared/NSTextContainerSetSizeGuard.m',)


def c4(m):
    """S4：变量表非空 ⇒ 至少一条赋值被求值成功。"""
    lst = _args(m, 'ios15_verify/verify_guard_v65.py')
    return bool(lst) and lst[0] and not lst[0][0].startswith('$')


def c5(m):
    """S5：regress_all_v 的参数不得含管道/重定向 token。"""
    for t in _args(m, 'ios15_verify/regress_all_v.py'):
        for a in t:
            if any(x in a for x in ('&', '|', 'tee', '>')):
                return False
    return True


def c6(m):
    """S6：裸 FD token(纯数字)必须被截断掉。

    ★观测点是 WF 里 `ci_assert_v48.py . 3` 那个 `3` —— `2>&1` 是一个
      token(含 `&`), 靠第一个条件就拦下, 观测不到纯数字分支。
    """
    lst = _args(m, 'ios15_verify/ci_assert_v48.py')
    return bool(lst) and lst[0] == ('.',)


def c7(m):
    """S7：同一 rel 只应出现一条（两个调用点参数相同，截断后应去重）。"""
    return len(_args(m, 'ios15_verify/regress_all_v.py')) == 1


def c8(m):
    """S8：剥引号不得过度 —— **首尾相同的裸路径**不能被剥掉头尾。

    ★观测点是 WF 里 `ci_assert_v50.py a/b/c/a`:
      头 `a` 尾 `a`, 一旦把 `v[0] in '"\\''` 这个约束去掉, 就会被剥成 `/b/c/`
      ⇒ 判据拿到一个根本不存在的路径。
    ★★踩过一次: 观测点一开始写成 `"ss"`, 结果正确版与过度版**都**剥成
      `ss` —— 因为剥引号只做一次, 两版结果相同, 观测不到差别。
      过度剥引号的危害只发生在「**没有引号**但首尾相同」的 token 上。
    """
    lst = _args(m, 'ios15_verify/ci_assert_v50.py')
    return bool(lst) and lst[0] == ('a/b/c/a',)


def c9(m):
    """S9：抽取故障必须被 main() 记成**红项**，不能当通过。

    ★★这条不能只看 collect_scripts 的抽取结果 —— 改的是 main() 里
      checks.append 的第二个参数。真跑一次 main() 太贵(会执行全部判据),
      所以改为**静态判定**: 源码里处理抽取故障的那一次 append 必须传 False。
    """
    src = m.get('__main_src__', [''])[0]
    hit = re.search(
        r"checks\.append\(\(label,\s*(True|False),\s*'EXTRACT-FAIL", src)
    if not hit:
        return False
    return hit.group(1) == 'False'


# ---------------- sabotage ----------------
def s1_unresolved_var(t):
    """CI#161 原样故障：expand_args 原样返回，不做变量替换。"""
    return t.replace(
        "    out = []\n    for a in args:\n        # 剥掉 shell 引号",
        "    return list(args)\n    out = []\n    for a in args:\n        # 剥掉 shell 引号",
        1)


def s2_dquote_only(t):
    """剥引号只认双引号。"""
    return t.replace(
        "        if len(v) >= 2 and v[0] == v[-1] and v[0] in '\"\\'':\n            v = v[1:-1]",
        "        if len(v) >= 2 and v[0] == v[-1] and v[0] == '\"':\n            v = v[1:-1]",
        1)


def s3_brace_form(t):
    """只处理 $VAR，不处理 ${VAR}。"""
    # ★锚点按**源码里的真实形态**写(单引号 raw string), 不是按 re.escape 的结果。
    #   第一版把 `\\$\\{` 写进 Python 字符串, 实际去源码里找 `\$\{`, 找不到
    #   ⇒ 锚点失效 ⇒ 记空测。空测必须报出来, 不能当通过。
    old = "v = re.sub(r'\\$\\{([A-Za-z_][A-Za-z0-9_]*)\\}|\\$([A-Za-z_][A-Za-z0-9_]*)', _sub, v)"
    new = "v = re.sub(r'\\$([A-Za-z_][A-Za-z0-9_]*)', _sub, v)"
    assert old in t, 'S3 锚点失效'
    return t.replace(old, new, 1)


def s4_empty_vartable(t):
    """parse_shell_vars 永远返回空表。"""
    old = "    out = {}\n    for m in _SHELL_ASSIGN.finditer(txt):"
    assert old in t, 'S4 锚点失效'
    return t.replace(old, "    return {}\n    out = {}\n    for m in _SHELL_ASSIGN.finditer(txt):", 1)


def s5_pipe_swallowed(t):
    """不再在管道/重定向处截断。"""
    old = "                if (set(tk) & set('|&;<>()\\\\')) or re.match(r'^\\d+$', tk):\n                    break"
    assert old in t, 'S5 锚点失效'
    return t.replace(old, "                if False:\n                    break", 1)


def s6_redirect_digit(t):
    """只拦含符号的 token，漏掉纯数字 FD。"""
    old = "                if (set(tk) & set('|&;<>()\\\\')) or re.match(r'^\\d+$', tk):"
    assert old in t, 'S6 锚点失效'
    return t.replace(old, "                if set(tk) & set('|&;<>()\\\\'):", 1)


def s7_key_before_cut(t):
    """key 用截断前的 args —— 同脚本被判成两条。"""
    old = "            key = rel + ' ' + ' '.join(cut)"
    assert old in t, 'S7 锚点失效'
    return t.replace(old, "            key = rel + ' ' + args", 1)


def s8_strip_quote_overreach(t):
    """剥引号过度：只看首尾相等，不管是不是引号字符。"""
    old = "        if len(v) >= 2 and v[0] == v[-1] and v[0] in '\"\\'':\n            v = v[1:-1]"
    assert old in t, 'S8 锚点失效'
    return t.replace(old, "        if len(v) >= 2 and v[0] == v[-1]:\n            v = v[1:-1]", 1)


def s9_silent_extract_fail(t):
    """main() 把抽取故障当通过。"""
    old = "            checks.append((label, False, 'EXTRACT-FAIL ' + msg))"
    assert old in t, 'S9 锚点失效'
    return t.replace(old, "            checks.append((label, True, 'EXTRACT-FAIL ignored'))", 1)


SABS = [
    ('S1 shell变量未求值(CI#161原样故障)', s1_unresolved_var, c1),
    ('S2 剥引号只认双引号', s2_dquote_only, c2),
    ('S3 ${VAR}形态不识别', s3_brace_form, c3),
    ('S4 变量表收不到赋值', s4_empty_vartable, c4),
    ('S5 管道吞进参数(regress_all_v原样故障)', s5_pipe_swallowed, c5),
    ('S6 重定向FD数字残留', s6_redirect_digit, c6),
    ('S7 key用截断前args致重复条目', s7_key_before_cut, c7),
    ('S8 剥引号过度', s8_strip_quote_overreach, c8),
    ('S9 抽取故障被当通过', s9_silent_extract_fail, c9),
]


def main():
    print('=' * 68)
    print('local_all_gates 抽取器 反向 sabotage（%d 条）' % len(SABS))
    print('=' * 68)

    base = _as_map(_items(G), ORIG_TXT)
    # ★BASE 不该要求「零抽取故障」—— WF 里**故意**放了一条未定义变量
    #   (`$NOT_DEFINED_ANYWHERE`) 来观测 S9, BASE 报出那条故障才是对的。
    #   BASE 真正要验的是: 该求值的都求出来了, 且故障被报成**条目**而不是被吞。
    v = _args(base, 'ios15_verify/verify_guard_v65.py')
    if not v or v[0] != ('src/ios/Shared/NSTextContainerSetSizeGuard.m',):
        print('❌ BASE 未把 $GUARD_V65 求值成真实路径，反向无意义')
        print('   实得:', v)
        return 1
    if not _args(base, '__extract_fail__'):
        print('❌ BASE 未把未定义变量报成抽取故障 ⇒ 抽取故障这条通路没判据看守')
        return 1
    print('BASE: ✅ $GUARD_V65 → %s' % v[0][0])
    print('       ${GUARD_V65} → %s' % (_args(base, 'ios15_verify/ci_assert_v63.py') or None))
    print("       '$SGL'      → %s" % (_args(base, 'ios15_verify/ci_assert_v64.py') or None))
    print('       regress_all → %s（管道已截断, 且两处调用去重成一条）'
          % _args(base, 'ios15_verify/regress_all_v.py'))
    print('       未定义变量  → 抽取故障 %d 条（应报, 不该静默）' % len(_args(base, '__extract_fail__')))
    print('-' * 68)

    blocked = leaked = voided = 0
    for name, mut, chk in SABS:
        try:
            txt = mut(ORIG_TXT)
        except AssertionError as e:
            voided += 1
            print('⚠️  %-46s %s' % (name, e))
            continue
        if txt == ORIG_TXT:
            voided += 1
            print('⚠️  %-46s sabotage 没改到源码' % name)
            continue
        try:
            compile(txt, 'sab.py', 'exec')
        except SyntaxError as e:
            voided += 1
            print('⚠️  %-46s 改出语法错: %s' % (name, e))
            continue

        # ★必须 exec 成一个**真模块对象**再传进去。
        #   第一版直接把 exec 的 dict 当模块用, 于是 `mod.ROOT` 抛
        #   `'dict' object has no attribute 'ROOT'` —— 9 条 sabotage 全部
        #   在这同一个无关点上崩掉, 报出「8 拦下 0 漏过」的**假绿**。
        #   崩溃确实「暴露了故障」, 但它崩的地方跟被改的那处能力毫无关系,
        #   等于一条都没测(比漏过更坏: 看起来有人看守)。
        sab_mod = types.ModuleType('sab_local_all_gates')
        sab_mod.__file__ = os.path.join(HERE, 'local_all_gates.py')
        try:
            exec(compile(txt, 'sab_local_all_gates.py', 'exec'), sab_mod.__dict__)
        except Exception as e:
            voided += 1
            print('⚠️  %-46s exec 期崩了: %s' % (name, e))
            continue

        try:
            sab = _as_map(_items(sab_mod), txt)
        except Exception as e:
            voided += 1
            print('⚠️  %-46s 采集期崩了(与被改能力无关, 不算拦下): %s'
                  % (name, str(e)[:50]))
            continue

        if sab == base:
            leaked += 1
            print('❌ %-46s 漏过 —— 结果完全没变' % name)
            continue
        # sabotage 后, 本条 checker 关心的那个能力必须坏掉
        if chk(sab):
            leaked += 1
            print('❌ %-46s 漏过 —— 结果变了但本能力仍判定为正常' % name)
            continue
        blocked += 1
        print('✅ %-46s 拦下' % name)

    print('-' * 68)
    print('反向: %d 拦下, %d 漏过, %d 空测（共 %d 条 sabotage）'
          % (blocked, leaked, voided, len(SABS)))
    return 1 if (leaked or voided) else 0


if __name__ == '__main__':
    sys.exit(main())
