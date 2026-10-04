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

ROOT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else '.')
WF_DIR = os.path.join(ROOT, '.github', 'workflows')
UPSTREAM = os.environ.get('OPENMINIS_UPSTREAM_IOS', '').strip()
FALLBACK = 'scripts/ios15_fallback.py'

# 需要 (fallback 路径, 干净上游) 两个参数的脚本 —— 从 workflow 里解析
NEEDS_ARGS = {
    'ios15_verify/reverse_v566.py': lambda: [FALLBACK, UPSTREAM],
    'ios15_verify/check_idempotent_reapply.py': lambda: [FALLBACK, UPSTREAM, '3'],
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
    """抽 workflow 里 `python3 <脚本>` 形式的判据（去重 + 解析参数）。"""
    out = []
    seen = set()
    pat = re.compile(r'python3 "\$SCRIPT_DIR/(ios15_verify/[A-Za-z0-9_./-]+\.py)"'
                     r'((?:\s+[^\s;\\]+)*)')
    if not os.path.isdir(WF_DIR):
        return out
    for fn in sorted(os.listdir(WF_DIR)):
        if not fn.endswith(('.yml', '.yaml')):
            continue
        txt = io.open(os.path.join(WF_DIR, fn), encoding='utf-8').read()
        for m in pat.finditer(txt):
            rel = m.group(1)
            # ★必须排除自己 —— 否则它会把自己当成一条判据再跑一遍,
            #   无限递归(本脚本第一版就卡在这里, 跑 5 分钟不出结果)。
            if os.path.basename(rel) == os.path.basename(__file__):
                continue
            args = m.group(2).strip()
            key = rel + ' ' + args
            if key in seen:
                continue
            seen.add(key)
            # 参数以 \ 续行时正则吃不全；已知需要固定参数的走 NEEDS_ARGS
            if rel in NEEDS_ARGS or args.startswith('\\'):
                args = ' '.join(NEEDS_ARGS.get(rel, list)())
                rel_key = rel + ' <fixed args>'
                if rel_key in seen:
                    continue
                seen.add(rel_key)
                out.append(('script ' + rel, rel, args.split()))
                continue
            out.append(('script ' + rel, rel, args.split() if args else []))
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
        r = sh([sys.executable, 'scripts/' + rel] + args)
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
