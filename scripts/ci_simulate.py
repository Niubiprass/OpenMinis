#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""本地 CI 模拟器: 在 pristine 上游源码上复现 port-and-build.yml 的
"拉源码 → 四个补丁脚本 → 42 条断言" 全流程, 在推送前就判定会不会变红。

为什么需要它:
  run#88/#89 连续两次因为**断言引用了补丁刚改掉的旧字符串**而红, 每次都要
  等 3~6 分钟的 CI 才发现。而 workflow 里的断言只是一串grep, 完全可以在本地
  用同一份源码跑一遍。

用法:
    python3 scripts/ci_simulate.py            # 用 GitHub API 取pristine 上游
    python3 scripts/ci_simulate.py --cached   # 复用/tmp/ci_sim/up 已有文件
"""
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

REPO = "OpenMinis/OpenMinis"
REF = "1.14"
CACHE = "/tmp/ci_sim/up"
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WF = os.path.join(REPO_ROOT, ".github/workflows/port-and-build.yml")

# workflow 断言里grep 的全部目标文件。缺一个就在报告里标"未取到", 不静默跳过 ——
# 静默跳过正是让过期断言活到 CI 的原因。
ASSERT_FILES = [
    "src/ios/Views/Chat/SelectableMarkdownView.swift",
    "src/ios/Views/Chat/AIChatView.swift",
    "src/ios/Views/Chat/ChatInputBar.swift",
    "src/ios/Agent/MessageList/MessageListLayout.swift",
    "src/ios/Agent/MessageList/MessageListInfrastructure.swift",
    "src/ios/Agent/Markdown/MinisMarkdownParser.swift",
    "src/ios/Shared/NSTextContainerSetSizeGuard.m",
    "src/ios/Minis.xcodeproj/project.pbxproj",
]

TOKEN = os.environ.get("GITHUB_TOKEN") or re.search(
    r"x-access-token:([^@]+)@", subprocess.run(
        ["git", "remote", "-v"], capture_output=True, text=True,
        cwd=REPO_ROOT).stdout).group(1)


def fetch(rel, tries=5):
    """取 pristine 上游文件到 CACHE。

    GitHub 在这个网络环境下会 IncompleteRead / 断流, 且**不会**把坏文件写进
    缓存(我们只在完整解码后才落盘), 所以重试是安全的; 但必须把"上一轮
    遗留的坏文件"清掉, 否则 --cached 会一直用一个截断文件。
    """
    os.makedirs(CACHE, exist_ok=True)
    dst = os.path.join(CACHE, rel.replace("/", "_"))
    if os.path.exists(dst) and os.path.getsize(dst) > 0:
        return dst
    url = f"https://api.github.com/repos/{REPO}/contents/{rel}?ref={REF}"
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={
                "Authorization": f"token {TOKEN}",
                "Accept": "application/vnd.github+json",
            })
            with urllib.request.urlopen(req, timeout=180) as r:
                raw = r.read()
            d = json.loads(raw)
            if "content" not in d:
                raise RuntimeError(d.get("message"))
            data = base64.b64decode(d["content"])
            # GitHub contents API 对 >1MB 会返回 content:"" + download_url。
            if not data and d.get("download_url"):
                with urllib.request.urlopen(
                        urllib.request.Request(d["download_url"],
                                               headers={"Authorization": f"token {TOKEN}"}),
                        timeout=300) as r2:
                    data = r2.read()
            if len(data) != d.get("size"):
                raise RuntimeError(f"长度不符: {len(data)} != {d.get('size')}")
            with open(dst, "wb") as f:
                f.write(data)
            return dst
        except Exception as e:
            last = e
            # 半截文件绝不能留在缓存里
            if os.path.exists(dst):
                os.remove(dst)
            if i < tries - 1:
                time.sleep(3 * (i + 1))
    raise RuntimeError(f"{rel}: {last}")


def main():
    cached = "--cached" in sys.argv
    # ---- 1. 取 pristine 上游 ----
    work = "/tmp/ci_sim/src/ios"
    os.makedirs(work, exist_ok=True)
    # 复用此前手工验证时已完整取到的文件(命名规则一致), 省掉重复的网络往返
    for stale in os.listdir(CACHE) if os.path.isdir(CACHE) else []:
        os.remove(os.path.join(CACHE, stale))
    for src_dir in ("/tmp/up",):
        if not os.path.isdir(src_dir):
            continue
        for n in os.listdir(src_dir):
            if n.endswith(".json"):
                continue
            tgt = os.path.join(CACHE, n)
            if not os.path.exists(tgt) and os.path.getsize(os.path.join(src_dir, n)) > 1000:
                shutil.copy(os.path.join(src_dir, n), tgt)
    missing = []
    for rel in ASSERT_FILES:
        try:
            if cached:
                src = os.path.join(CACHE, rel.replace("/", "_"))
                if not os.path.exists(src):
                    missing.append(rel)
                    continue
            else:
                src = fetch(rel)
        except Exception as e:
            print(f"  ⚠️取不到 {rel}: {e}")
            missing.append(rel)
            continue
        dst = os.path.join(work, rel[len("src/ios/"):])
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(src, "rb") as a, open(dst, "wb") as b:
            b.write(a.read())
    print(f"1. pristine 上游: {len(ASSERT_FILES)-len(missing)}/{len(ASSERT_FILES)} 个文件"
          + (f",缺失 {missing}" if missing else ""))

    # ---- 2. 跑四个补丁脚本 (与 workflow 同序) ----
    for script in ["ios15_port.py", "ios15_port_v2.py",
                   "ios15_runtime_fixes.py", "ios15_fallback.py"]:
        before = _snapshot(work)
        r = subprocess.run([sys.executable, os.path.join(REPO_ROOT, "scripts", script)],
                           capture_output=True, text=True, timeout=900)
        after = _snapshot(work)
        changed = sorted(k for k in after if before.get(k) != after[k])
        status = "OK" if r.returncode == 0 else f"EXIT={r.returncode}"
        print(f"2. {script:26s} {status:10s} 改动 {len(changed)} 个文件")
        if r.returncode != 0:
            tail = (r.stderr or r.stdout).strip().splitlines()[-6:]
            for line in tail:
                print(f"      {line}")
            print("   ❌ 补丁脚本自身失败 —— CI 会在此变红")
            return 2
        if not changed and script == "ios15_fallback.py":
            # 只有最后一个脚本"零改动"才是真信号: 它是纯anchored 替换, 全部
            # 失配说明上游变形。前面几个脚本会做全仓库扫描/新建文件, 在只取了
            # 部分文件的模拟环境里本来就可能无改动, 不能据此判死。
            print("   ❌ ios15_fallback 零改动 —— 锚点全部失效, CI 会静默产出未修复的包")
            return 2
        if not changed:
            print(f"   (提示: 该脚本在本次模拟的**不完整**源码集上无改动 ——"
                  f"预期行为, 只有 ios15_fallback 的零改动才是真信号)")

    # ---- 3. 逐条回验workflow 里的断言 ----
    wf = open(WF, encoding="utf-8").read()
    seg = wf[wf.find("断言1:"):wf.find("上传 IPA")]
    # 抓 if 条件里的 grep: 区分正向 (grep -q) 与反向 (! grep -q)
    conds = re.findall(r'(!?)\s*grep -q "([^"]+?)" (src/ios/[^\s;]+)', seg)
    files = {}
    for dirpath, _, names in os.walk(work):
        for n in names:
            p = os.path.join(dirpath, n)
            rel = "src/ios/" + os.path.relpath(p, work).replace(os.sep, "/")
            try:
                files[rel] = open(p, encoding="utf-8", errors="ignore").read()
            except Exception:
                pass

    ok = neg_ok = 0
    fails, unchecked = [], []
    for neg, needle, rel in conds:
        if rel not in files:
            unchecked.append((rel, needle))
            continue
        present = needle in files[rel]
        want = not present if neg else present
        if want:
            if neg:
                neg_ok += 1
            else:
                ok += 1
        else:
            fails.append((rel, needle, bool(neg)))

    print(f"3. 断言回验: 正向命中 {ok} 条, 反向(确认已移除)通过 {neg_ok} 条, "
          f"失败 {len(fails)} 条, 未取到源码 {len(unchecked)} 条")
    for rel, needle, neg in fails:
        kind = "反向断言(期望不存在却存在)" if neg else "正向断言(期望存在却缺失)"
        print(f"   ❌ {kind}: {rel.split('/')[-1]} | {needle[:78]}")
    for rel, needle in unchecked:
        print(f"   ⚠️ 未验证(源码未取到): {rel} | {needle[:60]}")

    if fails:
        print("\n❌ 结论: 推送后 CI 会在断言阶段变红, 请先修workflow。")
        return 1
    if unchecked:
        print("\n⚠️ 有断言未验证, 不能保证绿灯。")
        return 1
    print("\n✅ 结论: 全部断言在 pristine 产物上通过, 可以推送。")
    return 0


def _snapshot(root):
    snap = {}
    for dirpath, _, names in os.walk(root):
        for n in names:
            p = os.path.join(dirpath, n)
            try:
                snap[p] = os.path.getmtime(p), os.path.getsize(p)
            except OSError:
                pass
    return snap


if __name__ == "__main__":
    sys.exit(main())
