#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workflow run 块的 bash 静态语法检查(v53.1 新增)。

★为什么需要它:
  run#127(v53 首次上远端)红的原因**不在任何判据里** ——
  v52/v53 的判据本地全绿, 但整个 step 在 line 1052 报
      syntax error near unexpected token `)'
  根因是断言 56 的 `echo` 文案里用了 markdown 反引号:
      echo "... `applyCellCorrection()` 返回 true ..."
  bash 在**双引号内**照样把反引号当命令替换执行, 于是那个 `(` 开启的
  命令替换永远闭合不了 ⇒ 整个 run 块解析失败 ⇒ exit 2 ⇒ CI 红。
  同一位置的 v52 文案有 0 个反引号, 所以它一直没事。

★为什么放在独立文件而不是内嵌 heredoc:
  内嵌 `python3 - <<'EOF'` 的写法里, 反斜杠会被 YAML 折叠
  (实测 `\\n` 变成 `n`, 守卫脚本自己先 SyntaxError) ——
  **在 YAML 里嵌代码本身就不可靠**。本轮就是这么把自己写挂的。
  ⇒ 纪律: **判据脚本一律放独立文件**, workflow 只负责调用。

★判据纪律:
  「判据全绿」不等于「脚本能跑」。判据是 python, 跑在它前后的
  **shell 才是真正的执行体**。shell 解析不过, 根本执行不到判据。
  ⇒ 提交前必须过一遍 `bash -n`。

用法: python3 bash_syntax_check.py [workflow 路径]
退出码: 0 = 全部 run 块语法 OK; 1 = 有语法错(逐条打印)
"""
import os
import subprocess
import sys
import tempfile

import yaml


def main():
    wf = sys.argv[1] if len(sys.argv) > 1 else ".github/workflows/port-and-build.yml"
    if not os.path.exists(wf):
        sys.stderr.write("找不到 %s\n" % wf)
        return 1

    with open(wf, encoding="utf-8") as f:
        d = yaml.safe_load(f)

    bad = 0
    total = 0
    for jn, j in (d.get("jobs") or {}).items():
        for i, s in enumerate(j.get("steps") or []):
            r = s.get("run")
            if not r:
                continue
            total += 1
            with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False,
                                             encoding="utf-8") as f:
                f.write(r)
                fn = f.name
            p = subprocess.run(["bash", "-n", fn], capture_output=True)
            os.unlink(fn)
            if p.returncode != 0:
                bad += 1
                first = (p.stderr.decode() or "").split("\n")[0]
                print("BASH-N BAD  job=%s step[%d] %r" % (jn, i, s.get("name")))
                print("            %s" % first[:160])
                # 顺带指出: 该 step 里有没有反引号(本次的真凶)
                for k, ln in enumerate(r.split("\n"), 1):
                    st = ln.strip()
                    if st.startswith("echo ") and "`" in st:
                        print("            ★ L%d 的 echo 里有反引号 —— "
                              "bash 在双引号内会当命令替换执行" % k)
                        break

    print("bash -n: 共 %d 个 run 块, %d 个有语法错" % (total, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
