#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地跑完 CI 里**所有**判据门禁 —— 改完 fallback 先跑这个, 再推。

【为什么必须有这个脚本】
run#37223103334（v57.0 首次推送）红了，原因是 workflow 里**第三处**
`polluted` 整行匹配的硬编码内联判据（断言 43，`python3 -c "..."` 形式）
没跟着改 —— 我改了 `verify_v41.py`，但 CI 真正执行的是 workflow 里
那段**内联复制品**。

⇒ 教训：CI 门禁**散落在三处**，改一处不等于改全部：
   ① `scripts/ios15_verify/*.py`     —— 有名字的判据脚本
   ② `.github/workflows/*.yml` 里内联的 `python3 -c "..."` —— **无名字的复制品**
   ③ `regress_all_v.py` 的汇总表

本脚本把三处**全部**抽出来在本地跑一遍，缺参数时从 workflow 里把
参数一并解析出来（v566 那类需要 `fallback 路径 + 干净上游` 的）。

★第四类抽取故障(run#37271671515 / CI#161, 2026-10-05):
  workflow 里判据的参数常写成 shell 变量引用, 例如
      GUARD_V65="src/ios/Shared/NSTextContainerSetSizeGuard.m"
      python3 "$SCRIPT_DIR/ios15_verify/verify_guard_v65.py" "$GUARD_V65"
  本脚本早先把参数原样抽成字面量 `'"$GUARD_V65"'` 传下去, 于是
      ❌ [Errno 2] No such file or directory: '"$GUARD_V65"'
  ★★这个错最坏的地方在于它**伪装成判据报红**: 看到 `❌` 会本能地
  以为 v65 判据自己坏了, 去找判据的逻辑问题 —— 实际坏的是抽取器。
  历史同族: run#57 第三次门禁遗漏(内联复制品)、本次(shell 变量未解析)。
  ⇒ 抽取器必须**先把变量求值**, 求不出来的**显式报红**并说明是抽取故障,
    绝不能把 `'"$VAR"'` 这种字符串当文件名递给判据。

用法：
    python3 scripts/ios15_verify/local_all_gates.py [仓库根目录]

需要一份未被移植过的上游 src/ios 作基线：
    export OPENMINIS_UPSTREAM_IOS=/path/to/upstream/src/ios
没有时会跳过依赖上游的项，并明确报出（不假装通过）。
"""
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream_base import upstream_ios  # noqa: E402  唯一的上游解析入口

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
WF_DIR = os.path.join(ROOT, '.github', 'workflows')
UPSTREAM = upstream_ios(quiet=True) or ''
FALLBACK = 'scripts/ios15_fallback.py'

# 需要 (fallback 路径, 干净上游) 两个参数的脚本 —— 从 workflow 里解析
NEEDS_ARGS = {
    'ios15_verify/reverse_v566.py': lambda: [FALLBACK, UPSTREAM],
    'ios15_verify/check_idempotent_reapply.py': lambda: [FALLBACK, UPSTREAM, '3'],
    # ★断言72 的判据(CI 里读打包好的 IPA 二进制)。
    #   本地**不能**照搬 CI 的参数:
    #     CI 里  IPA="Minis-iOS${{ env.DEPLOY_TARGET }}.ipa"
    #   而上面的 parse_shell_vars 只认 `VAR=字面量`, **不认 `${{ ... }}` 表达式**
    #   ⇒ 抽取时 IPA 被求成 `Minis-iOS${{ env.DEPLOY_TARGET }}.ipa`
    #   ⇒ 脚本收到一个**字面文件名** ⇒ FileNotFoundError
    #   ⇒ CI 37361069156 / 37361453374 两个 run 都死在这一步,
    #      **编译一步都没跑**(这正是"判据自己把流水线掐死"的反面教训:
    #      新加的判据不但没抓到问题, 还先把构建堵住了)。
    #   ⇒ 传 --self-test: 造好/坏两份样本, **双向**验判据有鉴别力。
    #     这比凑一个"能过的参数"强: 它验的是判据的有效性本身,
    #     而不是判据在某个环境里恰好不报错(§16 的反面)。
    'ios15_verify/verify_binary_guard_markers.py': lambda: ['--self-test'],
}

# ★workflow 里 `VAR=value` 形式的赋值(引号可有可无)。用于把判据参数里的
#   "$VAR" 求成真实值 —— 否则会把 '"$VAR"' 当文件名递下去(CI#161 的红项)。
_SHELL_ASSIGN = re.compile(
    r'^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)=(?:"([^"\n]*)"|\'([^\'\n]*)\'|([^\s#]+))\s*$',
    re.M)


def parse_shell_vars(txt):
    """从 workflow 文本里收 `VAR=value` 赋值 -> {名字: 值}。

    ★必须收**整份文件**再求值, 而不是只看调用点附近: workflow 里
    `GUARD_V65=...` 与用到它的 `python3 ... "$GUARD_V65"` 隔着十几行
    (中间是几条 grep 断言)。
    ★同名变量后者覆盖前者 —— 与 shell 顺序执行语义一致。
    """
    out = {}
    for m in _SHELL_ASSIGN.finditer(txt):
        name = m.group(1)
        val = m.group(2)
        if val is None:
            val = m.group(3)
        if val is None:
            val = m.group(4)
        out[name] = val
    return out


def expand_args(args, shvars, where):
    """把参数里的 `$VAR` / `"$VAR"` 求成真实值。

    ★★求不出来时**抛异常**, 绝不把字面量往下传:
      传下去的话, 判据会报 `[Errno 2] No such file or directory: '"$GUARD_V65"'`,
      那条错看起来像"判据坏了", 实际是抽取器坏了 —— 排错方向会被带偏
      (CI#161 就是这么白查了一轮)。
    """
    out = []
    for a in args:
        # 剥掉 shell 引号: 判据收到的是路径本身, 不该带引号
        v = a
        if len(v) >= 2 and v[0] == v[-1] and v[0] in '"\'':
            v = v[1:-1]
        def _sub(m):
            name = m.group(1) or m.group(2)
            if name in shvars:
                return shvars[name]
            raise RuntimeError(
                "抽取故障: %s 的参数 %r 引用了 shell 变量 $%s, "
                "但整份 workflow 里找不到它的赋值。\n"
                "  这不是判据报红, 是本抽取器没把变量求值 —— "
                "把 '\"$%s\"' 当文件名递给判据了。" % (where, a, name, name))
        v = re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)', _sub, v)
        out.append(v)
    return out



# [v68] 需要放宽超时的聚合型脚本(理由见执行处注释)。
# ★ 绝不用"删掉它"来让门禁变绿 —— 那是把验证手段关掉(§16 的反面)。
SLOW_SCRIPTS = {
    # 聚合型: 内部串行跑 27 个 reverse, 多个要重建完整产物
    # (reverse_v62.py 实测 97s), 400s 仍不够(total 6:40 / CPU 仅 27.69s ⇒ 等子进程)
    'ios15_verify/regress_all_v.py': 1500,
    # ★ [v68] 下面这些**单个跑很快**, 但在 regress_all_v 的紧邻子进程压力下
    #   会被挤过 180s 阈值。实测证据:
    #     reverse_v61.py 单独跑 = **15.8 秒**(rc=0, 5/5 全拦)
    #   而门禁里同一项 = TIMEOUT >180s
    #   ⇒ 这不是判据卡住, 是**资源竞争**(§21: 工具的坏法会伪装成判据报红)。
    #   统一放宽而不是逐条追查 —— 逐条追查只会把"这次刚好快了"当成"修好了"。
    'ios15_verify/reverse_v61.py': 900,
    'ios15_verify/reverse_v62.py': 900,
    'ios15_verify/reverse_v565.py': 900,
    'ios15_verify/reverse_v566.py': 900,
    'ios15_verify/reverse_v567.py': 900,
    'ios15_verify/reverse_v568.py': 900,
    'ios15_verify/reverse_v569.py': 900,
    'ios15_verify/reverse_v570.py': 900,
    'ios15_verify/reverse_v53.py': 900,
    'ios15_verify/check_idempotent_reapply.py': 900,
}


def sh(cmd, cwd=ROOT, timeout=180):
    """跑一条判据。**必须带超时** —— 递归或死循环会让整轮门禁永久挂住,
    而 CI 上表现为「无输出直到 job 超时」，比直接红更难查。"""
    try:
        return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, env=dict(os.environ))
    except subprocess.TimeoutExpired as e:
        class _R:
            returncode = 124
            stdout = (e.stdout or b'').decode('utf-8', 'replace') \
                if isinstance(e.stdout, bytes) else (e.stdout or '')
            stderr = 'TIMEOUT >%ds —— 判据卡住(递归?死循环?)' % timeout
        return _R()


def collect_inline():
    """抽 workflow 里内联的 python3 -c 判据（去重）。"""
    out = []
    seen = set()
    pat = re.compile(r'\$\(python3 -c "([^"]+)"\)')
    pat2 = re.compile(r'python3 -c "([^"]+?)"\s*$')
    for fn in sorted(os.listdir(WF_DIR)) if os.path.isdir(WF_DIR) else []:
        if not fn.endswith(('.yml', '.yaml')):
            continue
        p = os.path.join(WF_DIR, fn)
        txt = io.open(p, encoding='utf-8').read()
        for pat_ in (pat, pat2):
            for m in pat_.finditer(txt):
                code = m.group(1)
                # 只收读 src/ios 的产物判据（脚本调用另走一条路）
                if 'src/ios' not in code or code in seen:
                    continue
                seen.add(code)
                out.append(('inline %s:%d' % (fn, txt[:m.start()].count('\n') + 1),
                            code))
    return out


def collect_scripts():
    """抽 workflow 里 `python3 <脚本>` 形式的判据（去重 + 解析参数）。

    ★★两处抽取故障都在这里(CI#161 实证, 详见模块 docstring):
      ① shell 变量未求值 —— `"$GUARD_V65"` 被当文件名递给判据;
      ② 管道/续行吞进参数 —— `python3 x.py . 2>&1 | tee f` 的 `2>&1 | tee f`
         也被当成参数。判据只用 argv[1] 时无害, 但一旦哪个判据多读一个
         argv 就会拿到 `|` 当文件名。⇒ 在管道/重定向/换行处**截断**。
    """
    out = []
    seen = set()
    pat = re.compile(r'python3 "\$SCRIPT_DIR/(ios15_verify/[A-Za-z0-9_./-]+\.py)"'
                     r'([^\n]*)')
    if not os.path.isdir(WF_DIR):
        return out
    for fn in sorted(os.listdir(WF_DIR)):
        if not fn.endswith(('.yml', '.yaml')):
            continue
        p = os.path.join(WF_DIR, fn)
        txt = io.open(p, encoding='utf-8').read()
        shvars = parse_shell_vars(txt)
        for m in pat.finditer(txt):
            rel = m.group(1)
            # ★必须排除自己 —— 否则它会把自己当成一条判据再跑一遍,
            #   无限递归(本脚本第一版就卡在这里, 跑 5 分钟不出结果)。
            if os.path.basename(rel) == os.path.basename(__file__):
                continue
            args = m.group(2).strip()
            # ★在管道/重定向/命令连接符处**截断参数**。
            #   `python3 x.py . 2>&1 | tee f` 的 `2>&1 | tee f` 是 shell 的
            #   重定向与管道, 不是 x.py 的参数。逐字符截会漏掉 `2>&1` 的
            #   数字部分(踩过一次), 所以按 **token** 判: token 里出现
            #   | & ; < > ( ) \\ 或纯数字(FD/行号)即停。
            cut = []
            for tk in args.split():
                if (set(tk) & set('|&;<>()\\')) or re.match(r'^\d+$', tk):
                    break
                cut.append(tk)
            # ★key 必须用**截断后**的 args —— 否则同一脚本在不同调用点
            #   (一处带管道一处不带)会被当成两条, 白跑一遍。
            key = rel + ' ' + ' '.join(cut)
            if key in seen:
                continue
            seen.add(key)
            # ★先把 shell 变量求值 —— 求不出会在 expand_args 里抛,
            #   由 main() 记成一条**明确的**抽取故障, 而不是让判据报
            #   `[Errno 2] ... '"$GUARD_V65"'` 那种误导性的错。
            where = 'inline %s:%d' % (fn, txt[:m.start()].count('\n') + 1)
            try:
                args_list = expand_args(cut, shvars, where)
            except RuntimeError as e:
                out.append(('%s  [抽取故障]' % where, None, str(e)))
                continue
            args = ' '.join(cut)
            # 参数以 \ 续行时正则吃不全；已知需要固定参数的走 NEEDS_ARGS
            if rel in NEEDS_ARGS or args.startswith('\\'):
                args = ' '.join(NEEDS_ARGS.get(rel, list)())
                rel_key = rel + ' <fixed args>'
                if rel_key in seen:
                    continue
                seen.add(rel_key)
                out.append(('script ' + rel, rel, args.split()))
                continue
            out.append(('script ' + rel, rel, args_list))
    return out



def main():
    print('=' * 68)
    print('本地全量门禁（改完 fallback 先跑这个再推）')
    print('=' * 68)
    print('仓库根: %s' % ROOT)
    print('干净上游: %s' % (UPSTREAM or '★未设 —— 依赖上游的项会跳过'))

    # --- 基础编译 ---
    checks = []
    r = sh([sys.executable, '-m', 'py_compile', FALLBACK])
    checks.append(('py_compile ' + FALLBACK, r.returncode == 0,
                   (r.stdout + r.stderr)[-300:]))

    # --- 判据脚本 ---
    for item in collect_scripts():
        if len(item) == 3 and item[1] is None:
            # 抽取故障(shell 变量求不出值等) —— **必须报红, 且文案要说清
            # "坏的是抽取器不是判据" —— 否则会被读成判据有问题, 白查一轮。
            label, _, msg = item
            checks.append((label, False, 'EXTRACT-FAIL ' + msg))
            continue
        if len(item) == 2:
            continue
        _, rel, args = item
        path = os.path.join(ROOT, 'scripts', rel)
        if not os.path.isfile(path):
            checks.append(('script ' + rel, False, '脚本不存在'))
            continue
        if (rel in NEEDS_ARGS or any('upstream' in a or a == '.upstream-ios'
                                     for a in args)) and not UPSTREAM:
            checks.append(('script ' + rel, True,
                           'SKIP(需干净上游，设 OPENMINIS_UPSTREAM_IOS)'))
            continue
        # [v68] 聚合型脚本单独放宽超时阈值。
        #
        # 【为什么必须放宽, 而不是把它从清单里删掉】
        # regress_all_v.py 要串行跑 **27 个 reverse 脚本**, 其中多个标了
        # "upstream" ⇒ 每个都要重建完整产物(四步注入链), 单个实测 ~97 秒
        # (reverse_v62.py)。180 秒的通用阈值下它**必然**超时。
        # 实测: 400 秒仍不够(total 6:40, 但 CPU 只有 27.69s user / 8%
        # ⇒ 不是死循环, 纯粹是等子进程)。
        #
        # ★这条红**不是 v68 引入的**: 该脚本最后一次改动是 v67b(2f1ecc1),
        #   本轮 v68 对它零改动(git diff 为空)。它是 v54(3403c94)起的
        #   历史结构性问题, 之前 CI 上跑所以没暴露。
        # ⇒ 处理: 放宽阈值到 1500s, 并把**超时与判据失败严格区分**:
        #   超时**不算通过**(仍记红), 但文案必须说清是超时而非判据坏了 ——
        #   否则又会走上 CI#161 那条"坏的是抽取器不是判据"的老路。
        _tmo = SLOW_SCRIPTS.get(rel, 180)
        r = sh([sys.executable, 'scripts/' + rel] + args, timeout=_tmo)
        checks.append(('script ' + rel, r.returncode == 0,
                       (r.stdout + r.stderr)[-400:]))

    # --- 内联判据 ---
    for label, code in collect_inline():
        # ★同样排除自身: 断言52b 的 run 行含本脚本名, 抽出来会再跑一遍。
        if 'local_all_gates' in code:
            continue
        r = sh([sys.executable, '-c', code])
        ok = r.returncode == 0 and 'BAD' not in r.stdout
        checks.append((label, ok, (r.stdout + r.stderr)[-300:]))

    # --- 汇总 ---
    npass = sum(1 for _, ok, _ in checks if ok and 'SKIP' not in _)
    nskip = sum(1 for _, _, m in checks if m.startswith('SKIP'))
    nfail = len(checks) - npass - nskip
    print('-' * 68)
    for label, ok, msg in checks:
        if 'SKIP' in msg:
            mark = '⏭ '
        elif ok:
            mark = '✅'
        else:
            mark = '❌'
        line = '%s %s' % (mark, label)
        if not ok and 'SKIP' not in msg:
            line += '\n     ' + msg.strip().replace('\n', '\n     ')[:600]
        elif 'SKIP' in msg:
            line += '  ' + msg
        print(line)
    print('-' * 68)
    print('合计: %d 通过 / %d 失败 / %d 跳过' % (npass, nfail, nskip))
    if nfail:
        print('\n★ 有 %d 条红。推送前必须全绿 —— CI 里红一次要多等 20 分钟。' % nfail)
    return 1 if nfail else 0


if __name__ == '__main__':
    sys.exit(main())
