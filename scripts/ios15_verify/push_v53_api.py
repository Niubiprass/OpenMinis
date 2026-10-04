#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v53 推送: git data API 单次提交(只传改动文件)。

★为什么不用 `git push`:
  1. 权限已验证可写(PUT contents -> 201), 但 git 协议要往 refs 上推
     几十 MB 的 pack, 这个网络环境反复 GnuTLS recv error(-110) / 连接超时。
  2. API 通道每次只传改动文件的 base64, 单个请求几百 KB, 稳。
⇒ 纪律: **推送失败要分清「权限」/「网络」/「历史」三种**:
     权限 403 / 网络 GnuTLS / 历史 non-fast-forward —— 修法完全不同。

★为什么是单次提交:
  Contents API 每 PUT 一个文件就是一次 commit, 会触发 N 个 CI run。
  git data API 是 blobs(N) -> trees(1) -> commits(1) -> refs(1),
  **只有最后一次 ref 更新触发 CI**, 整批改动只跑一次流水线。

★base_tree 用远端当前 HEAD 而不是本地父:
  探测过程中在远端产生过一个探针 commit(948e919a), 本地 v53 的父是
  8005536 —— 直接推会 non-fast-forward。base_tree + parents 都取远端
  当前 HEAD, 就是在**远端现状之上**加 v53, 不碰任何已有历史。
"""
import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

REPO = "Niubiprass/OpenMinis"
API = "https://api.github.com/repos/%s" % REPO
ROOT = os.path.dirname(os.path.abspath(__file__))     # scripts/ios15_verify
ROOT = os.path.dirname(os.path.dirname(ROOT))          # <root>

# 本次要推的 10 个文件(与 git show --stat 一致)
# 本次要推的文件: **自动从 git 取本次提交的改动**, 不再硬编码。
# 纪律 53: 推送脚本里硬编码文件列表, 迟早会漏推或多推 —— v55.2 那次就是
# FILES 停留在 v53 的 3 个文件, 差点把 v55 的产物漏在远端之外。
def _changed_files():
    out = subprocess.check_output(
        ["git", "show", "--name-only", "--pretty=format:", "HEAD"],
        cwd=ROOT).decode()
    files = [x.strip() for x in out.splitlines() if x.strip()]
    if not files:
        sys.stderr.write("!! HEAD 没有改动文件, 拒绝推送\n")
        sys.exit(1)
    return files


FILES = _changed_files()

HDRS = {
    "Accept": "application/vnd.github+json",
    "X-GitHub-Api-Version": "2022-11-28",
    "User-Agent": "codebuddy-push",
}


def api(method, path, token, payload=None, tries=4):
    """带重试的 API 调用。403 直接抛出(那是权限问题, 重试无用)。"""
    last = None
    for k in range(tries):
        data = None if payload is None else json.dumps(payload).encode()
        h = dict(HDRS)
        h["Authorization"] = "Bearer " + token
        req = urllib.request.Request(API + path, data=data, headers=h,
                                     method=method)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()[:300]
            if e.code in (401, 403):
                sys.stderr.write("!! %s %s -> %d (权限问题, 不重试)\n%s\n"
                                 % (method, path, e.code, body))
                raise
            last = "%d %s" % (e.code, body)
        except Exception as e:                      # 网络类: 可重试
            last = "%s: %s" % (type(e).__name__, e)
        if k + 1 < tries:
            time.sleep(3 * (k + 1))
    sys.stderr.write("!! %s %s 连续 %d 次失败, 最后: %s\n"
                     % (method, path, tries, last))
    raise SystemExit(1)


def main():
    token = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("V53_TOKEN")
    if not token:
        sys.stderr.write("用法: push_v53_api.py <PAT>\n")
        return 1

    base = api("GET", "/branches/main", token)["commit"]["sha"]
    print("远端 main HEAD = %s" % base)
    print("(本地 v53 的父是 8005536 —— 探测 commit 使远端前移, "
          "故 base/parent 都取远端现状, 绝不 force push)\n")

    entries = []
    for rel in FILES:
        full = os.path.join(ROOT, rel)
        with open(full, "rb") as f:
            data = f.read()
        blob = api("POST", "/git/blobs", token, {
            "content": base64.b64encode(data).decode(),
            "encoding": "base64",
        })
        entries.append({"path": rel, "mode": "100644",
                        "type": "blob", "sha": blob["sha"]})
        print("  blob %s  %-58s %7d B" % (blob["sha"][:10], rel, len(data)))

    tree = api("POST", "/git/trees", token,
               {"base_tree": base, "tree": entries})
    print("\ntree = %s" % tree["sha"])

    msg = subprocess.check_output(
        ["git", "log", "-1", "--pretty=%B"],
        cwd="/tmp/push53").decode().strip()
    commit = api("POST", "/git/commits", token, {
        "message": msg, "tree": tree["sha"], "parents": [base],
    })
    print("commit = %s" % commit["sha"])

    ref = api("PATCH", "/git/refs/heads/main", token,
              {"sha": commit["sha"], "force": False})
    print("main -> %s" % ref["object"]["sha"])
    print("\n✅ 单次提交完成 —— 只触发一个 CI run")
    return 0


if __name__ == "__main__":
    sys.exit(main())
