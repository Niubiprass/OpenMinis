#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workflow run 块的 bash 静态语法检查(v53.1 新增, v53.2 改零依赖)。

★为什么需要它:
  run#127(v53 首次上远端)红的原因**不在任何判据里** ——
  v52/v53 的判据本地全绿, 但整个 step 在 line 1052 报
      syntax error near unexpected token `)'
  根因是断言 56 的 `echo` 文案里用了 markdown 反引号:
      echo "... `applyCellCorrection()` 返回 true ..."
  bash 在**双引号内**照样把反引号当命令替换执行, 于是那个 `(` 开启的
  命令替换永远闭合不了 ⇒ 整个 run 块解析失败 ⇒ exit 2 ⇒ CI 红。
  同一位置的 v52 文案有 0 个反引号, 所以它一直没事。

★★ v53.2 改成零依赖(自己踩的坑):
  第一版用 `import yaml` 解析 workflow, 结果 run#128 直接
      ModuleNotFoundError: No module named 'yaml'
  —— **CI runner 上没有 PyYAML**(本地有, 是我拿本地当默认了)。
  ⇒ 纪律: **判据脚本只能用 CI 上确定存在的东西**。
    本地有 ≠ CI 有; 判据脚本必须**零第三方依赖**(只用标准库 +
    `bash`/`git` 这类一定存在的二进制)。
  同理, 内嵌 `python3 - <<'EOF'` 的反斜杠会被 YAML 折叠(实测 `\\n`→`n`),
  守卫自己先 SyntaxError ⇒ **判据脚本一律放独立文件, workflow 只调用**。

用法: python3 bash_syntax_check.py [workflow 路径]
退出码: 0 = 全部 run 块语法 OK; 1 = 有语法错(逐条打印, 并点名反引号)
"""
import os
import re
import subprocess
import sys
import tempfile


def extract_runs(text):
    """从 workflow 原文里抽出所有 `run: |` / `run: >` 块。

    ★不用 yaml 库: CI runner 上没有 PyYAML(实测 ModuleNotFoundError)。
      这个 workflow 的 run 块一律是 `run: |` 缩进块, 用行级状态机
      扫「缩进比 run: 更深」的行即可, 不需要真正的 YAML 解析。
    ★产出: [(step_name, [脚本行...]), ...]

    ★★ v53.2 补: **单行 `run:` 也要查**。
      第一版只匹配 `run: |` / `run: >` 这种块形式, 漏掉了 4 个单行块
      (`run: sudo xcode-select …` / `run: python3 "…"` 等) ——
      抽取数从 18 掉到 14 就是漏它们的信号。
      ⇒ 纪律: **抽取器要拿「总数」当自检**。若与 `grep -c '^\s*-?\s*run:'`
        的结果不等, 说明正则失配了, 判据自己漏了块却报「全绿」。
    """
    out = []
    lines = text.split("\n")
    i, n = 0, len(lines)
    # 块形式的 run 行数(用于自检)
    n_run = len([l for l in lines if re.match(r"^\s*-?\s*run:", l)])
    n_block = 0
    while i < n:
        m = re.match(r"^(\s*)-?\s*run:\s*(.*?)\s*$", lines[i])
        if not m:
            i += 1
            continue
        base = len(m.group(1))
        rest = m.group(2)
        # step 名字: 往上找最近的 `- name:`
        name = "?"
        for k in range(i - 1, max(-1, i - 12), -1):
            mn = re.match(r"^\s*-?\s*name:\s*(.+?)\s*$", lines[k])
            if mn:
                name = mn.group(1).strip().strip("'\"")
                break
        if rest in ("|", ">", "|-", ">-", "|+", ">+", ""):
            # 块形式: 收「缩进 > base 且非空」的行
            body, j = [], i + 1
            while j < n:
                ln = lines[j]
                if ln.strip() == "":
                    body.append("")
                    j += 1
                    continue
                ind = len(ln) - len(ln.lstrip())
                if ind <= base:
                    break
                body.append(ln)
                j += 1
            real = [b for b in body if b.strip()]
            if real:
                cut = min((len(b) - len(b.lstrip()) for b in real), default=0)
                body = [b[cut:] if b.strip() else "" for b in body]
            n_block += 1
            out.append((name, body))
            i = j
        else:
            # 单行形式: 整行就是脚本
            out.append((name, [rest]))
            i += 1
    if len(out) != n_run:
        print("BASH-N WARN: 抽出 %d 个 run 块, 但文件里 run: 行共 %d 行 —— "
              "抽取器可能失配, 判据自己漏了块却会报全绿" % (len(out), n_run))
    return out


def main():
    wf = sys.argv[1] if len(sys.argv) > 1 else ".github/workflows/port-and-build.yml"
    if not os.path.exists(wf):
        sys.stderr.write("找不到 %s\n" % wf)
        return 1
    with open(wf, encoding="utf-8") as f:
        text = f.read()

    runs = extract_runs(text)
    if not runs:
        print("BASH-N WARN: 没抽出任何 run 块(正则是否失配? 判据自身坏了)")
        return 1

    bad = 0
    for idx, (name, body) in enumerate(runs):
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False,
                                         encoding="utf-8") as f:
            f.write("\n".join(body) + "\n")
            fn = f.name
        p = subprocess.run(["bash", "-n", fn], capture_output=True)
        os.unlink(fn)
        if p.returncode != 0:
            bad += 1
            first = (p.stderr.decode() or "").split("\n")[0]
            print("BASH-N BAD  step[%d] %r" % (idx, name[:60]))
            print("            %s" % first[:160])
            for k, ln in enumerate(body, 1):
                st = ln.strip()
                if st.startswith("echo ") and "`" in st:
                    print("            ★ L%d 的 echo 里有反引号 —— bash 在双引号内"
                          "会当命令替换执行" % k)
                    break

    print("bash -n: 共 %d 个 run 块, %d 个有语法错" % (len(runs), bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
