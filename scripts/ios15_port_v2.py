#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OpenMinis -> iOS 15 移植（第二阶段）。

第一阶段（ios15_port.py）已处理 NavigationStack / presentationDetents。
第二阶段针对 Xcode 编译暴露出的 1554 个真实错误，按杠杆从大到小处理：

  1. AppLocalized 参数类型 String.LocalizationValue(iOS16) -> String    [约 1000+]
  2. Agent/Intents 目录整目录标注 @available(iOS 16.0, *)              [约 260]
  3. 删除 iOS16 专属的纯装饰性 SwiftUI 修饰符                           [约 30]
  4. Task.sleep(for: .milliseconds(x)) -> Task.sleep(nanoseconds:)      [约 14]
  5. TextField(..., axis:) / usingTextLayoutManager / String(localized:) [约 10]
  6. 生成 iOS15Compat.swift 兼容层并注入 Xcode 工程                      [约 120]

设计原则：
  - 全部幂等（重复执行不叠加改动）
  - 全部尽力而为（找不到目标就跳过并打印，绝不抛异常中断构建）
  - 只做文本级改写，不改动工程结构（除注入兼容层文件外）
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys

ROOT = "src/ios"

# 脚本版本号。每轮修复都会改它，日志第一行就会打印，
# 用来确认 runner 上跑的是不是最新脚本（避免又下到 CDN 缓存的旧版）。
SCRIPT_VERSION = "v10-20260929j"
COMPAT_NAME = "iOS15Compat.swift"
PRISTINE_COMMIT = None  # 已废弃：浅克隆下取不到真正的初始提交，改用内存基线
# 转换前的文件内容快照（路径 -> 内容），由 snapshot_baseline() 填充，
# 供结构自检做「转换前 vs 转换后」对比。不依赖 git 历史。
BASELINE = {}

# 上游原版仓库。每次构建都从这里拉干净源码覆盖 src/ios，
# 和用户 fork 的提交历史彻底解耦。
# 尊重 UPSTREAM_REF 环境变量（port-and-build.yml 注入，默认 1.14）。
# 用户策略：默认钉死 1.14（tag），只在 App Store 大版本新功能上线时
# 改成新 tag，避免上游 main 的小更新静默弄坏 TrollStore 包。
_UP_REF = os.environ.get("UPSTREAM_REF", "main")
UPSTREAM_TGZ = ("https://codeload.github.com/OpenMinis/OpenMinis"
                "/tar.gz/%s" % _UP_REF)

# ---------------------------------------------------------------- 基础工具

# 不需要、也不该做 iOS15 移植的目录。
#
# AgentWidget 是 iOS 17 的 Live Activity / 灵动岛扩展（日志里它的编译目标就是
# -target arm64-apple-ios17.0）。iOS 15.5 设备根本没有 Live Activity 和灵动岛，
# 移植它零收益；而它那套多层尾随闭包
#   ActivityConfiguration(...) { } dynamicIsland: { DynamicIsland { }
#   compactLeading: { } compactTrailing: { } minimal: { } }
# 已经被我的删除逻辑误伤三次（v6/v7/v9），每次都留下半截结构。
# 整个目录保持原样、部署目标维持 17.0，是最省事也最正确的做法。
SKIP_DIRS = {"AgentWidget", "AgentWidgetExtension"}

# 含这些标记的源文件，一律不做「删除类」改写。多行尾随闭包的重灾区，
# 按行删或按表达式删都可能留下半截闭包。
DELETE_GUARD_TOKENS = (
    "ActivityConfiguration(",
    "dynamicIsland:",
    "DynamicIsland",
)

# 本脚本自己生成、每轮需要清掉重来的产物文件
OUR_ARTIFACTS = {"iOS15Compat.swift"}


def swift_files(base: str):
    """递归收集 base 下所有 .swift 文件（跳过隐藏目录与豁免目录）。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames
                       if not d.startswith(".") and d not in SKIP_DIRS]
        for fn in filenames:
            if fn.endswith(".swift"):
                out.append(os.path.join(dirpath, fn))
    return sorted(out)


def guarded(text: str) -> bool:
    """文件是否含受保护的多尾随闭包构造（只允许标注类改写，不允许删除类）。"""
    return any(tok in text for tok in DELETE_GUARD_TOKENS)


def read(p: str) -> str:
    with open(p, encoding="utf-8", errors="replace") as f:
        return f.read()


def write(p: str, s: str) -> None:
    with open(p, "w", encoding="utf-8") as f:
        f.write(s)


def edit(path: str, fn) -> bool:
    """对单个文件应用 fn，返回是否发生了改动。"""
    try:
        old = read(path)
    except OSError:
        return False
    new = fn(old)
    if new != old:
        write(path, new)
        return True
    return False


def log(msg: str) -> None:
    print(msg, flush=True)


# ------------------------------------------------- 1. AppLocalized 参数类型

APPL_PATH = os.path.join(ROOT, "Shared", "AppLocalization.swift")

NEW_APPL_BODY = '''/// Localized string that follows the in-app language override.
///
/// iOS 15 port note: the original signature took `String.LocalizationValue`
/// (iOS 16+) and forwarded to `String(localized:bundle:)` (also iOS 16+).
/// Both are unavailable on iOS 15, which produced 1000+ errors at every call
/// site. This version takes a plain `String` and resolves through
/// `NSLocalizedString`, which routes through
/// `Bundle.localizedString(forKey:value:table:)` -- exactly the seam the
/// language-override swizzle in MinisApp.swift already patches, so the in-app
/// language picker keeps working.
///
/// - Parameters:
///   - key: the localization key, i.e. the English source string.
///   - comment: translator context.
func AppLocalized(_ key: String, comment: StaticString? = nil) -> String {
    NSLocalizedString(key, bundle: AppBundle.current,
                      comment: comment.map { String(describing: $0) } ?? "")
}
'''


def fix_applocalized() -> None:
    """把 AppLocalized 的 iOS16 参数/实现换成 iOS15 可用的等价物。"""
    if not os.path.isfile(APPL_PATH):
        log("⚠️  未找到 %s，跳过 AppLocalized 改造" % APPL_PATH)
        return

    text = read(APPL_PATH)
    orig = text

    # 参数类型：String.LocalizationValue -> String
    text = text.replace("_ key: String.LocalizationValue", "_ key: String")

    # 实现：String(localized:...) -> NSLocalizedString(...)
    text = re.sub(
        r"String\(localized:\s*key,\s*bundle:\s*AppBundle\.current,\s*comment:\s*comment\)",
        'NSLocalizedString(key, bundle: AppBundle.current,\n'
        '                      comment: comment.map { String(describing: $0) } ?? "")',
        text,
    )

    # 删掉 LocalizedStringResource 重载（该类型 iOS16 才有）
    text = re.sub(
        r"\n/// `LocalizedStringResource` overload.*?\n"
        r"func AppLocalized\(_ resource: LocalizedStringResource\) -> String \{.*?\n\}\n",
        "\n",
        text,
        flags=re.S,
    )
    # 兜底：任何残留的 LocalizedStringResource 版本
    text = re.sub(
        r"\nfunc AppLocalized\(_ resource: LocalizedStringResource\)[^\n]*\n\{.*?\n\}\n",
        "\n",
        text,
        flags=re.S,
    )

    if "LocalizedStringResource" in text:
        # 还有别处引用，逐行清掉显式类型标注
        text = re.sub(r"\n[^\n]*\bLocalizedStringResource\b[^\n]*", "", text)

    if text != orig:
        write(APPL_PATH, text)
        log("✅ 已改造 AppLocalization.swift（参数 String.LocalizationValue -> String）")
    else:
        log("ℹ️  AppLocalization.swift 无需改动（或已是 iOS15 版本）")


# ------------------------------------------- 2. 全项目清除 LocalizedStringResource

def strip_localizedstringresource() -> None:
    """清掉其他文件里对 LocalizedStringResource 的显式类型标注。

    例外：`static var/let xxx: LocalizedStringResource` 是 AppIntent 等协议
    要求的属性（如 `static var title`），改类型会破坏协议一致性
    （v2 第一版在这里翻过车：AudioTogglePlaybackIntent 不再符合 AppIntent）。
    这类声明一律跳过，改由 annotate_appintent_files 用 @available 处理。
    """
    STATIC_DECL = re.compile(r"\bstatic\s+(?:var|let)\s+\w+\s*:\s*LocalizedStringResource")
    n = 0
    for path in swift_files(ROOT):
        if path == APPL_PATH:
            continue

        def _fn(text: str) -> str:
            if "LocalizedStringResource" not in text:
                return text
            out = []
            for ln in text.split("\n"):
                if STATIC_DECL.search(ln):
                    out.append(ln)  # 协议属性, 保持原类型
                    continue
                ln = ln.replace(": LocalizedStringResource?", ": String?")
                ln = ln.replace(": LocalizedStringResource", ": String")
                ln = ln.replace("-> LocalizedStringResource", "-> String")
                ln = ln.replace("<LocalizedStringResource>", "<String>")
                ln = ln.replace("[LocalizedStringResource]", "[String]")
                ln = ln.replace("as? LocalizedStringResource", "as? String")
                ln = ln.replace("as LocalizedStringResource", "as String")
                out.append(ln)
            return "\n".join(out)

        if edit(path, _fn):
            n += 1
    log("✅ 清理 LocalizedStringResource 类型标注：%d 个文件" % n)


# AppIntents 相关协议（出现在类型继承列表中即视为意图/实体类型）
INTENT_PROTO_RE = re.compile(
    r":\s*(?:LiveActivityIntent|AppIntent|AppShortcutsProvider|AppEntity|AppEnum|AppShortcut)\b"
)


def restore_intent_props() -> None:
    """恢复上一版脚本误改的协议属性（static var title: String -> LocalizedStringResource）。

    上一版把全项目 LocalizedStringResource 标注无差别替换成 String，导致
    AudioTogglePlaybackIntent 等意图类型不再符合 AppIntent 协议。
    这里只处理「文件中含 AppIntents 协议」的场景，且只恢复协议要求的属性名。
    """
    n = 0
    for path in swift_files(ROOT):
        try:
            text = read(path)
        except OSError:
            continue
        if not INTENT_PROTO_RE.search(text):
            continue
        orig = text
        text = re.sub(
            r"(static\s+(?:var|let)\s+title\s*:\s*)String(\s*=)",
            r"\1LocalizedStringResource\2", text)
        text = re.sub(
            r"(static\s+(?:var|let)\s+summary\s*:\s*)String(\s*=)",
            r"\1LocalizedStringResource\2", text)
        if text != orig:
            write(path, text)
            n += 1
    log("✅ 恢复 AppIntent 协议属性（title/summary）：%d 个文件" % n)


def annotate_file_top_decls(path: str, avail: str) -> bool:
    """给文件的顶层类型声明加 @available(avail, *)（幂等）。已标注则跳过。"""
    marker = "@available(iOS %s, *) // ios15-port" % avail
    text = read(path)
    if marker in text or "@available(iOS 16.0, *) // ios15-port" in text:
        return False
    lines = text.split("\n")
    out = []
    for ln in lines:
        m = DECL_RE.match(ln)
        if m and not ln.lstrip().startswith("//"):
            out.append(m.group("ind") + marker)
        out.append(ln)
    write(path, "\n".join(out))
    return True


def annotate_appintent_files() -> None:
    """Intents 目录之外的意图/实体类型也要隔离（如 Shared/AudioTogglePlaybackIntent）。

    - LiveActivityIntent 需要 iOS 17 -> 标 17.0
    - 其余 AppIntents API 从 iOS 16 开始 -> 标 16.0
    前提：引用这些类型的扩展 target 会由 fix_fileprovider_deployment.py
    抬高部署目标（AgentWidgetExtension -> 17.0），主 App 不引用它们。
    """
    n = 0
    for path in swift_files(ROOT):
        rel = os.path.relpath(path, ROOT).replace(os.sep, "/")
        if rel.startswith("Agent/Intents/"):
            continue  # annotate_intents 已按 16.0 处理
        try:
            text = read(path)
        except OSError:
            continue
        if not INTENT_PROTO_RE.search(text):
            continue
        avail = "17.0" if "LiveActivityIntent" in text else "16.0"
        if annotate_file_top_decls(path, avail):
            n += 1
    log("✅ Intents 目录外的意图类型标注 @available：%d 个文件" % n)


# ------------------------------------------------- 3. Intents 目录整体标注

INTENTS_DIR = os.path.join(ROOT, "Agent", "Intents")

DECL_RE = re.compile(
    r"^(?P<ind>[ \t]*)(?P<mods>(?:public |internal |fileprivate |private |open |final |indirect )*)"
    r"(?P<kind>struct|class|enum|actor|protocol|extension)\s+(?P<name>\w+)"
)


def annotate_intents() -> None:
    """给 Agent/Intents 下每个顶层声明加 @available(iOS 16.0, *)。

    AppIntents 框架在 iOS 15 上不存在对应 API，整块标注后编译器不再检查其
    内部实现；引用点集中在该目录内（AppShortcutsProvider 等），因此不会把
    错误扩散到主 App。
    """
    if not os.path.isdir(INTENTS_DIR):
        log("⚠️  未找到 %s，跳过 Intents 标注" % INTENTS_DIR)
        return

    n = 0
    for path in swift_files(INTENTS_DIR):
        if annotate_file_top_decls(path, "16.0"):
            n += 1
    log("✅ Intents 目录标注 @available(iOS 16.0, *)：%d 个文件" % n)


# ------------------------------------------------------------ 0. 源码还原

def _skip_string(text: str, i: int) -> int:
    """i 指向起始引号（单引号式 " 或三引号式三个双引号），返回字面量结束之后的位置。

    支持 Swift 字符串插值 \\( ... ) —— 插值内部可以再嵌套字符串与括号，
    因此用「先遇到未闭合引号就递归跳过」的方式处理，避免
    "\\(foo(\")\"))" 这类写法让外层字面量提前闭合（v9 的误报根因之一）。
    """
    n = len(text)
    multiline = text.startswith('"""', i)
    i += 3 if multiline else 1
    while i < n:
        c = text[i]
        if c == "\\":
            if i + 1 < n and text[i + 1] == "(":
                i = _skip_interp(text, i + 2)
                continue
            i += 2
            continue
        if multiline and text.startswith('"""', i):
            return i + 3
        if not multiline and c == '"':
            return i + 1
        i += 1
    return n


def _skip_interp(text: str, i: int) -> int:
    """i 指向 \\( 之后，返回与它配对的 ) 之后的位置。"""
    n = len(text)
    depth = 1
    while i < n:
        c = text[i]
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c in "([{":
            depth += 1
        elif c in ")]}":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _paren_balance_ok(text: str) -> bool:
    """检查 ( ) { } [ ] 是否配平（跳过注释与字符串字面量、多行字符串）。"""
    pairs = {"(": ")", "{": "}", "[": "]"}
    stack = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i)
            i = n if j < 0 else j
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j < 0 else j + 2
            continue
        if c == '"':
            i = _skip_string(text, i)
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif c in ")}]":
            if not stack or stack[-1] != c:
                return False
            stack.pop()
        i += 1
    return not stack


# 已知会毁掉语法的残骸特征（不依赖解析器，命中即判坏）。
# v6/v7 的两次事故都是这两种：多行尾随闭包删头留身、setBadgeCount 残句。
BROKEN_RES = [
    re.compile(r"^[ \t]*\}[ \t]*isTargeted:[ \t]*\{", re.M),
    re.compile(r"=[ \t]*\d+[ \t]*\{[ \t]*_[ \t]*in[ \t]*\}", re.M),
]


def _pristine_text(path: str):
    """取该文件转换前的原文（快照）；不在快照里返回 None。"""
    return BASELINE.get(path)


def check_and_rollback_broken() -> None:
    """转换后自检：只回滚「确实被我们改坏」的文件。

    v9 的教训：直接拿括号配平当判据会大面积误报 —— 我的迷你解析器
    认不全 Swift 语法（raw string、正则字面量、插值嵌套 …），
    原文件本身就判不配平的文件会被无辜回滚，等于整轮移植作废。

    v10c 判据（三条全都必须成立才算坏）：
      1. 文件确实被本轮改动过（与转换前快照不同）；
      2. 命中已知残骸特征，或「转换前配平、转换后不配平」；
      3. 第 2 条的括号判据里，若转换前本身就判不配平 —— 那是解析器
         的锅，不是转换的锅，一律放过。
    """
    bad = []          # [(path, 原因)]
    parser_noise = 0  # 解析器自己判不平（转换前就这样）的文件数
    total = 0

    for path in swift_files(ROOT):
        total += 1
        try:
            cur = read(path)
        except OSError:
            continue
        orig = _pristine_text(path)
        if orig is None:      # 新增文件（如兼容层），无基线可比
            continue
        if orig == cur:       # 没改动
            continue

        reason = None
        for rx in BROKEN_RES:
            m = rx.search(cur)
            if m and not rx.search(orig):
                reason = "命中损坏特征 %r" % m.group(0).strip()[:60]
                break

        if reason is None and not _paren_balance_ok(cur):
            if _paren_balance_ok(orig):
                reason = "转换前配平、转换后不配平"
            else:
                parser_noise += 1  # 解析器对原文件就误判，放过

        if reason:
            bad.append((path, reason))

    if parser_noise:
        log("ℹ️  %d 个文件被解析器判为不配平，但初始提交同样如此 → "
            "判定为解析器语法覆盖不足，未回滚" % parser_noise)

    if not bad:
        log("✅ 结构自检通过：%d 个 Swift 文件，无损坏特征、无括号退化"
            % total)
        return

    for path, reason in bad:
        # 先把现场写进日志，方便下次定位（我看不到源码，只能靠这个）
        try:
            d = subprocess.run(["git", "diff", "--", path],
                               capture_output=True, text=True, timeout=60)
            diff = d.stdout
            if len(diff) > 4000:
                diff = diff[:2000] + "\n...[截断]...\n" + diff[-2000:]
            log("❌ %s %s，改动如下：\n%s" % (path, reason, diff))
        except Exception:
            pass
        # 让 swiftc 亲口说出语法错误行号，比我的迷你解析器准得多
        # 让 swiftc 亲口说出语法错误行号，比我的迷你解析器准得多
        swiftc_diagnose(path)
        # 回滚 = 恢复成转换前的快照（浅克隆下没有可信的 git 基线）
        orig = BASELINE.get(path)
        if orig is not None:
            try:
                write(path, orig)
                log("🔄 %s 已回滚到转换前状态（该文件本次不作移植）" % path)
                continue
            except OSError:
                pass
        log("⚠️  %s 判定损坏且无法回滚，请检查" % path)


def swiftc_diagnose(path: str, limit: int = 12) -> None:
    """用 macOS 自带的 swiftc 做纯语法解析（-parse，不做类型检查）。

    只打印诊断，不参与回滚决策 —— 它的输出是我下一轮定位问题最可靠的线索。
    """
    if not shutil.which("swiftc"):
        return
    try:
        sdk = subprocess.run(["xcrun", "--sdk", "iphoneos", "--show-sdk-path"],
                             capture_output=True, text=True, timeout=60)
        args = ["swiftc", "-parse"]
        if sdk.returncode == 0 and sdk.stdout.strip():
            args += ["-sdk", sdk.stdout.strip()]
        args += ["-target", "arm64-apple-ios15.5", path]
        r = subprocess.run(args, capture_output=True, text=True, timeout=120)
    except Exception:
        return
    out = (r.stdout or "") + (r.stderr or "")
    lines = [l for l in out.split("\n") if "error:" in l][:limit]
    if lines:
        log("   swiftc -parse 诊断：\n     " + "\n     ".join(l.strip() for l in lines))


def restore_from_upstream() -> None:
    """从上游 OpenMinis 主分支拉取干净源码，整体覆盖 src/ios。

    为什么不再用 git 历史还原：
      GitHub Actions 的 checkout@v4 默认浅克隆（fetch-depth=1），本地历史
      只有一个 graft 根提交 = checkout 时所在的那个提交 = 上一轮运行提交
      的「移植结果」。于是 `git rev-list --max-parents=0` 找到的所谓初始
      提交，本身就是被上一轮改过的代码 —— 把损坏当基线，还原了个寂寞
      （v10b 的第 11 轮：转换 0 改动、仓库里坏文件原样保留，就是这个原因）。

    上游 tarball 和 fork 的提交历史完全无关，每次都是干净的原版；
    就算 fork 里已经提交了改坏的文件，也会被整体覆盖掉。

    尽力而为：下载失败就保留仓库当前版本继续跑，绝不中断构建。
    """
    if not os.path.isdir(ROOT):
        return
    import tarfile
    import tempfile
    import urllib.request

    tmpdir = tempfile.mkdtemp(prefix="upstream_om_")
    try:
        req = urllib.request.Request(
            UPSTREAM_TGZ, headers={"User-Agent": "ios15-port-script"})
        tgz = os.path.join(tmpdir, "upstream.tgz")
        with urllib.request.urlopen(req, timeout=180) as resp:
            with open(tgz, "wb") as f:
                f.write(resp.read())
        with tarfile.open(tgz, "r:gz") as tf:
            tf.extractall(tmpdir)
        os.remove(tgz)
        src = None
        for name in os.listdir(tmpdir):
            cand = os.path.join(tmpdir, name, "src", "ios")
            if os.path.isdir(cand):
                src = cand
                break
        if src is None:
            log("⚠️  上游压缩包里没有 src/ios，保留仓库当前版本继续")
            return
        # 上游 tarball 不含子模块内容；如果 src/ios 里有子模块会被清掉，
        # 所以覆盖后统一补一次 submodule 恢复（没有子模块时是空操作）
        shutil.rmtree(ROOT)
        shutil.copytree(src, ROOT)
        subprocess.run(["git", "submodule", "update", "--init", "--recursive",
                        ROOT], capture_output=True, timeout=600)
        n = sum(1 for dp, _, fs in os.walk(ROOT) for f in fs
                if f.endswith(".swift"))
        log("✅ 已从上游 OpenMinis/main 还原干净源码（%d 个 Swift 文件）" % n)
    except Exception as e:
        log("⚠️  上游还原失败（%s），退回仓库当前版本继续" % str(e)[:160])
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)


def cleanup_artifacts() -> None:
    """清掉上一轮脚本自己生成的产物（幂等，每轮重新生成）。

    只删我方产物白名单，绝不「还原所有改动」—— 仓库里工作区之外的东西
    一概不碰，避免误删真实源码。
    """
    removed = 0
    if os.path.isdir(ROOT):
        for dirpath, dirnames, filenames in os.walk(ROOT):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")]
            for fn in filenames:
                if fn in OUR_ARTIFACTS:
                    try:
                        os.remove(os.path.join(dirpath, fn))
                        removed += 1
                    except OSError:
                        pass
        for d in ("Compat",):
            try:
                os.rmdir(os.path.join(ROOT, d))
            except OSError:
                pass
    if removed:
        log("✅ 已清掉上一轮产物 %d 个" % removed)


def _replace_outside_comments(text: str, old: str, new: str) -> str:
    """只替换代码里的 old，跳过 // 行注释与 /// 文档注释。

    源码注释里经常抄一段真实代码当示例（`.contextMenu { } preview: { }`、
    `.contentShape(.contextMenuPreview, …)` 之类），无差别 str.replace 会把
    注释改得跟代码对不上，后面再按注释线索排错就全乱了。
    """
    out = []
    for ln in text.split("\n"):
        if ln.lstrip().startswith("//"):
            out.append(ln)
        else:
            out.append(ln.replace(old, new))
    return "\n".join(out)


def _delete_call(text: str, name: str, drop_trailing_closure: bool = False):
    """整调用配平删除 name(...)（单行/多行都安全）。

    drop_trailing_closure=True 时连同后面的尾随闭包一起删
    （.onGeometryChange(for: X.self) { proxy in ... } 这种）。
    """
    pat = re.compile(re.escape(name) + r"\s*\(")
    out = text
    guard = 0
    while guard < 200:
        guard += 1
        m = pat.search(out)
        if not m:
            break
        lp = m.end() - 1
        e = _expr_end(out, lp)
        if e is None:
            # 配不平就不动它，用占位符推进搜索位置避免死循环
            out = out[:m.start()] + "\x00" + out[m.end():]
            continue
        end = e
        if drop_trailing_closure:
            # 吃掉尾随闭包，包括 Swift 的多个尾随闭包形态：
            #   .onGeometryChange(for: X.self) { proxy in … } action: { … }
            # 第一个闭包无标签，后续的都带 label:，所以要循环吃。
            j = e
            g2 = 0
            while g2 < 10:
                g2 += 1
                while j < len(out) and out[j] in " \t\r\n":
                    j += 1
                k2 = j
                lab = re.match(r"[A-Za-z_]\w*\s*:\s*", out[k2:])
                if lab:
                    k2 += lab.end()
                if k2 < len(out) and out[k2] == "{":
                    k = _match_delim(out, k2)
                    if k:
                        end = k
                        j = k
                        continue
                break
        i = m.start()
        ls = out.rfind("\n", 0, i) + 1
        if out[ls:i].strip() == "":
            i = ls
            if end < len(out) and out[end] == "\n":
                end += 1
        out = out[:i] + out[end:]
    return out.replace("\x00", name + "(")


def strip_toolbar_conditionals(text: str) -> str:
    """去掉 .toolbar { ... } 里最外层的 if 条件分支。

    @ToolbarContentBuilder 的 buildIf（条件分支）是 iOS 16 才有的，
    iOS 15 的 toolbar 闭包里写 if 会报 "'buildIf' is only available in
    iOS 16.0 or newer"（第 15 轮光这一类就 16 个错误）。

    只处理 toolbar 块的**直接**子语句（缩进与块内首行一致），
    更深层的 @ViewBuilder 闭包里的 if 是合法的，绝不能碰。
    """
    pat = re.compile(r"\.toolbar\s*(?:\([^)]*\))?\s*\{")
    out = text
    pos = 0
    guard = 0
    while guard < 100:
        guard += 1
        m = pat.search(out, pos)
        if not m:
            break
        lb = m.end() - 1                      # 指向 {
        eb = _match_delim(out, lb)
        if not eb:
            pos = m.end()
            continue
        block = out[lb + 1:eb - 1]
        # 块内首行的缩进 = toolbar 直接子语句的缩进
        base = None
        for ln in block.split("\n"):
            if ln.strip():
                base = len(ln) - len(ln.lstrip())
                break
        if base is None:
            pos = eb
            continue
        ifpat = re.compile(r"(?m)^([ \t]*)if[ \t]+[^\n]*\{[ \t]*$")
        inner = block
        g2 = 0
        while g2 < 100:
            g2 += 1
            im = ifpat.search(inner)
            if not im:
                break
            if len(im.group(1)) != base:
                # 不是直接子语句，放过。
                # 注意：占位符必须加在行首且**保留原行内容**——早期版本把整行
                # 换成 "\x01"、恢复时只写回 "if "，于是深层 if 变成了一个光秃秃
                # 的 "if"，凭空多出语法错误。
                inner = inner[:im.start()] + "\x01" + inner[im.start():]
                continue
            lb2 = inner.rfind("{", im.start(), im.end())
            eb2 = _match_delim(inner, lb2)
            if not eb2:
                inner = inner[:im.start()] + "\x01" + inner[im.end():]
                continue
            # 去掉 "if 条件 {" 与配对的 "}"，保留分支体
            inner = inner[:im.start()] + inner[lb2 + 1:eb2 - 1] + inner[eb2:]
        inner = inner.replace("\x01", "")
        out = out[:lb + 1] + inner + out[eb - 1:]
        pos = lb + 1 + len(inner)
    return out


def _strip_textfield_axis(text: str) -> str:
    """删掉 TextField(...) 里的 axis: 参数（iOS 16 专属）。

    按括号配平定位参数范围，这样跨行写的
      TextField("", text: Binding(get: {...}, set: {...}), axis: .vertical)
    也能处理。
    """
    pat = re.compile(r"\bTextField\s*\(")
    out = text
    pos = 0
    guard = 0
    while guard < 200:
        guard += 1
        m = pat.search(out, pos)
        if not m:
            break
        lp = m.end() - 1
        e = _expr_end(out, lp)
        if e is None or e < lp:
            pos = m.end()
            continue
        body = out[m.end():e - 1]          # 参数部分，不含外层 ( )
        nb = re.sub(r",\s*axis:\s*[\w.]+", "", body)
        if nb != body:
            out = out[:m.end()] + nb + out[e - 1:]
        pos = m.end()
    return out


def stage1_fixes() -> None:
    """第一阶段脚本（ios15_port.py）的规则，在这里重跑一遍。

    工作流里第一阶段确实先跑过，但第二阶段开头会从上游重新铺一遍源码，
    把它改的东西整体覆盖了 —— 第 12 轮就栽在这儿：编译只剩 2 个错误，
    全是 'NavigationStack' is only available in iOS 16.0 or newer，
    因为那次替换的成果被上游还原抹掉了。
    所以这批规则必须在还原之后再执行一次。

    注意：这里**不再**把 NavigationStack 替换成 NavigationView。第 15 轮就是
    这么干的，结果 `NavigationStack(path: $navigationPath)` 变成了
    `NavigationView(path: $navigationPath)` —— 后者根本不存在，凭空多出
    "extra arguments at positions #1, #2" 这类级联错误，而且 path 驱动的程序化
    导航全废。现在改成由 iOS15Compat.swift 里的 NavigationStack 替身接管。
    """
    touched = 0
    for path in swift_files(ROOT):
        t = read(path)
        if not any(k in t for k in (
                ".presentationDetents", ".symbolEffect", ".fontWeight",
                ".onGeometryChange", ".photosPicker", ".toolbar",
                "lineLimit", "listRowSeparatorLeading", ".contextMenu",
                ".gradient")):
            continue
        orig = t
        # iOS 16/17 专属、iOS 15 无对应的视觉 API，整调用删除
        t = _delete_call(t, ".presentationDetents")
        t = _delete_call(t, ".symbolEffect")
        # 纯视觉增强（字重/加粗/图片选择器）：删掉不影响功能
        t = _delete_call(t, ".fontWeight")
        t = _delete_call(t, ".bold")
        # ⚠️ onGeometryChange 绝不能删！它是"几何测量"的唯一来源：
        #   * inputBarHeight（输入栏高度）→ 消息列表底部内边距
        #   * floatingBarHeight（悬浮工具条高度）
        #   * topSafeAreaInset（导航栏高度）/ inputBottomRowWidth
        # 之前整调用删除，导致 inputBarHeight 永远是 0：消息列表底部不留空，
        # **最后一条消息被输入栏永久盖住、滚不进可视区**（用户现象："执行任务
        # 字不会上移"），底部还会渲染成一块黑区。
        # 上游注释自己写明了这个后果（"the last message was permanently stuck
        # under the composer — unable to scroll into view"）。
        # 改为调用 iOS15Compat.swift 里的回填实现（GeometryReader+PreferenceKey，
        # 与 iOS 16 原版语义一致：值变化时才回调）。
        t = _replace_outside_comments(
            t, ".onGeometryChange(", ".onGeometryChange15(")
        t = _delete_call(t, ".photosPicker")
        # .lineLimit(1...2) 这种区间写法是 iOS 16，退化成上限
        t = re.sub(r"\.lineLimit\(\s*(\d+)\s*\.\.\.\s*(\d+)\s*\)",
                   r".lineLimit(\2)", t)
        # Alignment.listRowSeparatorLeading 是 iOS 16 的 AlignmentID
        t = t.replace(".listRowSeparatorLeading", ".leading")
        # 强制选中 iOS 13 的 contextMenu(menuItems:) 重载，别被 iOS 16 的
        # menuItems:preview: 抢走
        t = _fix_context_menu(t)
        # Color.orange.gradient 是 iOS 16 的 ShapeStyle
        t = re.sub(r"\b(Color\.[\w.]+)\.gradient\b", r"\1", t)
        # contentShape(.contextMenuPreview, …) 的第一参是 iOS 16 的
        # ContentShapeKinds；压成 iOS 15 的单参 contentShape(_:)。
        # 注意：必须跳过注释行——源码里 `/// .contentShape(.contextMenuPreview,
        # RoundedRectangle(...))` 这种文档注释也有同样的子串，无差别替换会把
        # 注释里的示例代码改花（跟之前 contextMenu preview: 的坑同源）。
        t = _replace_outside_comments(
            t, ".contentShape(.contextMenuPreview, ", ".contentShape(")
        # @ToolbarContentBuilder 的 buildIf 是 iOS 16，去掉 toolbar 里的条件分支
        t = strip_toolbar_conditionals(t)
        if t != orig:
            write(path, t)
            touched += 1
    log("✅ 第一阶段规则复跑（presentationDetents/symbolEffect/fontWeight/"
        "onGeometryChange→回填15/photosPicker/toolbar-if…）：%d 个文件受影响" % touched)


def _fix_context_menu(text: str) -> str:
    """处理 .contextMenu 的两种 iOS 16 写法，使其兼容 iOS 15：

    1) .contextMenu { … } preview: { … }
       —— preview: 是 iOS 16 才有的自定义预览标签块，iOS 15 没有对应物，
          整块删掉。删完变成 .contextMenu { … }（iOS 14 尾随闭包，iOS 15 可用）。
    2) .contextMenu { … }
       —— 显式改写成 .contextMenu(menuItems: { … })，把重载钉死在 iOS 13 那版，
          避免编译器去选 iOS 16 的 menuItems:preview: 双参重载。
    """
    # 第 1 步：删掉紧跟在 .contextMenu 调用后面的 preview: { … } 块
    out = text
    pos = 0
    guard = 0
    while guard < 300:
        guard += 1
        m = re.compile(r"\.contextMenu").search(out, pos)
        if not m:
            break
        i = m.end()
        while i < len(out) and out[i] in " \t\r\n":
            i += 1
        if i >= len(out) or out[i] not in "{(":
            pos = m.end()
            continue
        eb = _match_delim(out, i)        # .contextMenu {…} 或 (menuItems:{…}) 的结束 }
        if not eb:
            pos = m.end()
            continue
        # 调用结束后跳过空白，看是否紧跟 preview: { … }
        k = eb
        while k < len(out) and out[k] in " \t\r\n":
            k += 1
        if out[k:k + 8] == "preview:":
            p = k + 8
            while p < len(out) and out[p] in " \t\r\n":
                p += 1
            if out[p] == "{":
                pe = _match_delim(out, p)
                if pe:
                    out = out[:k] + out[pe:]   # 删掉 preview: { … }
                    continue                   # 重新扫描，可能有多个 contextMenu
        pos = eb
    # 第 2 步：剩余的 .contextMenu { … } 改写成 (menuItems: { … })
    out2 = out
    pos = 0
    while guard < 600:
        guard += 1
        m = re.compile(r"\.contextMenu\s*\{").search(out2, pos)
        if not m:
            break
        lb = m.end() - 1
        eb = _match_delim(out2, lb)
        if not eb:
            pos = m.end()
            continue
        block = out2[lb:eb]
        out2 = out2[:lb] + "(menuItems: " + block + ")" + out2[eb:]
        pos = lb + len("(menuItems: ") + len(block) + 1
    return out2


def snapshot_baseline() -> None:
    """转换前给全部 Swift 文件拍快照，作为结构自检的对照基线。

    同样是因为浅克隆：git show HEAD:path 拿到的是上一轮的移植结果，
    不是干净原文。干脆不依赖 git，直接在内存里留一份「转换前」的内容。
    """
    BASELINE.clear()
    for path in swift_files(ROOT):
        try:
            BASELINE[path] = read(path)
        except OSError:
            continue
    log("✅ 已记录转换前基线：%d 个文件" % len(BASELINE))
# ------------------------------------------- 4. 删除 iOS16 装饰性修饰符

# 纯单行参数式修饰符，按行删是安全的
DELETE_LINE_RES = [
    r"\.presentationDragIndicator\(",
    r"\.toolbarBackground\(",
    r"\.listRowSeparatorLeading\(",
    r"\.scrollIndicators\(",
    r"\.scrollDismissesKeyboard\(",
    r"\.scrollContentBackground\(",
    r"\.persistentSystemOverlays\(",
    r"\.navigationSplitViewColumnWidth\(",
    r"\.toolbar\([^\n]*for:\s*\.(?:navigationBar|bottomBar|tabBar)",
]

# 带尾随闭包的多行构造，必须整调用配平删除，绝不能按行删！
# .dropDestination(for: .text) { items, _ in
#     ...
# } isTargeted: { over in
#     ...
# }
CALL_DELETE_RES = [
    r"\.dropDestination\(",
    r"\.draggable\(",
]


def _match_delim(text: str, i: int):
    """i 指向 ( { [ 之一，返回配对闭括号之后的位置；自动跳过字符串字面量。"""
    pairs = {"(": ")", "{": "}", "[": "]"}
    stack = []
    n = len(text)
    while i < n:
        c = text[i]
        if c == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    break
                i += 1
            i += 1
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif stack and c == stack[-1]:
            stack.pop()
            if not stack:
                return i + 1
        elif c in ")}]" and not stack:
            return None
        i += 1
    return None


def _expr_end(text: str, lp: int):
    """lp 指向调用的 "("，返回整个调用（含全部尾随闭包）结束位置。"""
    i = _match_delim(text, lp)
    if i is None:
        return None
    while True:
        # 带标签的尾随闭包（如 isTargeted: { over in ... }），允许跨行
        m = re.match(r"\s*\w+\s*:\s*\{", text[i:])
        if m:
            e = _match_delim(text, i + m.end() - 1)
            if e is None:
                return None
            i = e
            continue
        # 第一个尾随闭包必须紧跟在同一行的 ")" 之后。
        # 不限制的话，"跨过若干空行去吃下一个结构的 {" 会误删无关代码。
        m2 = re.match(r"[ \t]*\{", text[i:])
        if m2:
            e = _match_delim(text, i + m2.end() - 1)
            if e is None:
                return None
            i = e
            continue
        break
    return i


def delete_call_exprs() -> None:
    """整调用配平删除多行构造（dropDestination / draggable 等）。"""
    pats = [re.compile(p) for p in CALL_DELETE_RES]
    touched = 0
    for path in swift_files(ROOT):
        text = read(path)
        if guarded(text):
            # 含 Live Activity 多层尾随闭包的文件，删除类改写一律不碰
            continue
        changed = False
        for pat in pats:
            guard = 0
            while guard < 200:
                guard += 1
                m = pat.search(text)
                if not m:
                    break
                lp = m.end() - 1  # 模式含 "("，m.end()-1 必指向它
                e = _expr_end(text, lp)
                if e is None:
                    log("⚠️  %s: 无法配平 %s 调用，跳过" % (path, pat.pattern))
                    break
                # 安全网：单次删除超过 2000 字符几乎一定是配平算错，宁可不删
                if e - m.start() > 2000:
                    log("⚠️  %s: %s 调用跨 %d 字符，疑似配平算错，跳过"
                        % (path, pat.pattern, e - m.start()))
                    break
                i = m.start()
                ls = text.rfind("\n", 0, i) + 1
                if text[ls:i].strip() == "":
                    i = ls
                    if e < len(text) and text[e] == "\n":
                        e += 1
                text = text[:i] + text[e:]
                changed = True
        if changed:
            write(path, text)
            touched += 1
    log("✅ 整体删除多行构造（dropDestination/draggable）：%d 个文件受影响" % touched)


# 孤儿形态：} isTargeted: {  —— 上一版脚本按行删掉了 .dropDestination(
# 开头行后残留在仓库里的半截闭包。
# 注意：标签必须限定为 isTargeted（dropDestination 专属）。像
#   AsyncImage(url:) { phase in ... } placeholder: { ... }
# 这种合法的多尾随闭包链，形态几乎一样，早年宽泛的正则曾把它们整段误删。
ORPHAN_TRAILING_RE = re.compile(r"(?m)^([ \t]*)\}[ \t]*isTargeted:[ \t]*\{")


def repair_orphan_trailing_closures() -> None:
    """自愈：清理上一版「删头留身」造成的语法残骸。

    破坏形态（.dropDestination( 行已被删）：
        <第一闭包体若干行（缩进比孤儿行深）>
        } isTargeted: { over in        ← 孤儿行
            <isTargeted 体>
        }
    从孤儿行向上吞掉缩进更深的连续非空行，从孤儿行内的 "{"
    配平到它的结束 "}"，整段删除。幂等：清完即无匹配。
    """
    touched = 0
    for path in swift_files(ROOT):
        text0 = read(path)
        # 双保险：只有在本文件里已经找不到 .dropDestination 开头行时，
        # "} isTargeted: {" 才可能是残骸（干净的源码里两者必然成对出现）。
        if ".dropDestination(" in text0:
            continue
        if not ORPHAN_TRAILING_RE.search(text0):
            continue
        changed = False
        for _ in range(50):
            text = read(path)
            m = ORPHAN_TRAILING_RE.search(text)
            if not m:
                break
            lines = text.split("\n")
            orphan_idx = text[: m.start()].count("\n")
            indent_len = len(m.group(1))
            # 1) 向上吞掉缩进更深的连续非空行（第一闭包的残骸）
            start = orphan_idx
            k = orphan_idx - 1
            while k >= 0:
                ln = lines[k]
                if ln.strip() == "":
                    k -= 1
                    continue
                li = len(ln) - len(ln.lstrip())
                if li > indent_len:
                    start = k
                    k -= 1
                    continue
                break
            # 2) 从孤儿行内的 "{" 配平到结束 "}"
            brace = text.find("{", m.start())
            end_pos = _match_delim(text, brace) if brace >= 0 else None
            if end_pos is None:
                log("⚠️  %s: 孤儿闭包无法配平，跳过" % path)
                break
            end_idx = text[:end_pos].count("\n")
            del lines[start : end_idx + 1]
            new = "\n".join(lines)
            if new == text:
                break
            write(path, new)
            changed = True
        if changed:
            touched += 1
    if touched:
        log("🩹 已修复上一版删行残留的孤儿闭包：%d 个文件" % touched)


def delete_modifiers() -> None:
    """删除 iOS16 专属、纯视觉/交互增强的修饰符整行（iOS15 无对应 API）。"""
    pats = [re.compile(p) for p in DELETE_LINE_RES]
    total = 0
    touched = 0
    for path in swift_files(ROOT):
        def _fn(text: str) -> str:
            lines = text.split("\n")
            out = []
            for ln in lines:
                if any(p.search(ln) for p in pats):
                    continue
                out.append(ln)
            return "\n".join(out)

        before = read(path)
        after = _fn(before)
        if after != before:
            write(path, after)
            touched += 1
    log("✅ 删除 iOS16 装饰性修饰符：%d 个文件受影响" % touched)


# ------------------------------------------------------- 5. 零散 API 替换

def misc_fixes() -> None:
    """零散但确定可行的替换。"""
    touched = 0
    for path in swift_files(ROOT):
        def _fn(t: str) -> str:
            orig = t

            # Task.sleep(for: .milliseconds(n)) -> Task.sleep(nanoseconds:)
            t = re.sub(
                r"Task\.sleep\(for:\s*\.milliseconds\(([^()]*)\)\)",
                r"Task.sleep(nanoseconds: UInt64(\1) * 1_000_000)", t)
            t = re.sub(
                r"Task\.sleep\(for:\s*\.seconds\(([^()]*)\)\)",
                r"Task.sleep(nanoseconds: UInt64(\1) * 1_000_000_000)", t)
            t = re.sub(
                r"Task\.sleep\(for:\s*\.nanoseconds\(([^()]*)\)\)",
                r"Task.sleep(nanoseconds: UInt64(\1))", t)

            # TextField(..., axis: .vertical) -> TextField(...)
            # 必须按括号配平找参数范围：真实写法里 text: 常常是一个跨多行的
            # Binding(get:set:)，单行正则根本匹配不到（第 13 轮就是这么漏的）
            t = _strip_textfield_axis(t)

            # Locale.Language / Locale.Region 系列（iOS 16 才有）降级到
            # iOS 15 上语义等价的旧属性：
            #   loc.language.languageCode?.identifier -> loc.languageCode
            #   loc.region?.identifier                -> loc.regionCode
            # 两者的差别只是 Optional<Locale.LanguageCode> vs String?，
            # 后面的 ?.identifier / $0.identifier 要一并去掉。
            for _old, _new in (
                (".language.languageCode?.identifier", ".languageCode"),
                (".language.languageCode", ".languageCode"),
                (".language.script?.identifier", ".scriptCode"),
                (".language.script", ".scriptCode"),
                (".language.variant?.identifier", ".variantCode"),
                (".language.variant", ".variantCode"),
                (".language.maximalIdentifier", ".identifier"),
                (".region?.identifier", ".regionCode"),
                (".region.identifier", ".regionCode"),
            ):
                t = t.replace(_old, _new)
            # 跟着的 .map { ... $0.identifier ... } 里 $0 已经变成 String 了
            for _prop in ("languageCode", "scriptCode", "variantCode",
                          "regionCode"):
                t = re.sub(
                    r"\.%s\.map\s*\{([^{}]*?)\}" % _prop,
                    lambda m: ".%s.map {" % _prop
                              + m.group(1).replace("$0.identifier", "$0") + "}",
                    t)

            # UITextView(usingTextLayoutManager:) -> UITextView()
            t = re.sub(r"\(\s*usingTextLayoutManager:\s*(?:true|false)\s*\)", "()", t)
            t = re.sub(r",\s*usingTextLayoutManager:\s*(?:true|false)", "", t)

            # String(localized: "x") -> "x"
            t = re.sub(r"String\(localized:\s*\"([^\"]*)\"\)", r'"\1"', t)

            # UNUserNotificationCenter/UIApplication.setBadgeCount (iOS16)
            #   -> applicationIconBadgeNumber
            # 必须把调用连同尾随闭包（{ _ in }）一起替换，否则留下 "= 0 { _ in }" 残句
            badge_pat = re.compile(
                r"([ \t]*)(?:try\s+)?(?:await\s+)?[A-Za-z_][^\n{}]*?\.setBadgeCount\(")

            def _badge_sub(s: str) -> str:
                out = []
                pos = 0
                guard = 0
                while guard < 500:
                    guard += 1
                    m = badge_pat.search(s, pos)
                    if not m:
                        out.append(s[pos:])
                        break
                    lp = m.end() - 1
                    e = _match_delim(s, lp)
                    if e is None:
                        out.append(s[pos:m.end()])
                        pos = m.end()
                        continue
                    arg = s[lp + 1:e - 1].strip()
                    j = e
                    m2 = re.match(r"[ \t]*\{", s[j:])
                    if m2:
                        e2 = _match_delim(s, j + m2.end() - 1)
                        if e2 is not None:
                            j = e2
                    out.append(s[pos:m.start(1)] + m.group(1)
                               + "UIApplication.shared.applicationIconBadgeNumber = " + arg)
                    pos = j
                return "".join(out)

            t = _badge_sub(t)

            # 自愈：上一版替换 setBadgeCount 时漏掉了尾随闭包，留下
            #   ...applicationIconBadgeNumber = 0 { _ in }
            # 删掉挂在赋值后面的残留闭包即可恢复成正确的赋值语句。
            guard = 0
            while guard < 200:
                guard += 1
                m = re.search(r"\.applicationIconBadgeNumber\s*=\s*[^\n=;]*?[^\s][ \t]*\{", t)
                if not m:
                    break
                e = _match_delim(t, m.end() - 1)
                if e is None:
                    break
                t = t[:m.end() - 1] + t[e:]

            return t

        before = read(path)
        after = _fn(before)
        if after != before:
            write(path, after)
            touched += 1
    log("✅ 零散 API 替换（sleep/axis/badge/…）：%d 个文件受影响" % touched)


# ------------------------------------------- 5b. 第 15 轮日志里剩余的功能型 API


def _convert_regex_literals(text: str) -> str:
    """iOS 16 的 Regex 字面量 (/…/) 换成 MinisRegex + NSRegularExpression。

    - `markdown.ranges(of: /…/)`      -> `MinisRegex.ranges(markdown, "…")`
    - `key.wholeMatch(of: keyRegex)`  -> `MinisRegex.wholeMatch(key, keyRegex)`
    - `static let keyRegex = /…/`     -> `static let keyRegex = "…"`
    """
    def _lit_to_str(body: str) -> str:
        # 正则字面量里的 \[ 在普通字符串里要写成 \\[
        return '"' + body.replace("\\", "\\\\").replace('"', '\\"') + '"'

    # 1) 内联字面量: X.ranges(of: /…/)
    def _ranges(m):
        return "MinisRegex.ranges(%s, %s)" % (m.group(1), _lit_to_str(m.group(2)))

    text = re.sub(r"(\w+)\.ranges\(\s*of:\s*/((?:[^/\\\n]|\\.)*)/\s*\)",
                  _ranges, text)

    # 2) wholeMatch(of:) —— iOS 16 的 Regex 方法
    text = re.sub(r"(\w+)\.wholeMatch\(\s*of:\s*(\w+)\s*\)\s*!=\s*nil",
                  r"MinisRegex.wholeMatch(\1, \2)", text)

    # 3) 正则字面量常量声明
    def _lit_decl(m):
        return "%s = %s" % (m.group(1), _lit_to_str(m.group(2)))

    text = re.sub(
        r"(?m)^(\s*(?:public |private |internal )?(?:static )?(?:let|var)\s+\w+\s*)"
        r"=\s*/((?:[^/\\\n]|\\.)*)/\s*$", _lit_decl, text)
    return text


def _replace_flow_layout(text: str) -> str:
    """`struct FlowLayout: Layout` -> 一个 iOS 15 可编译的 View。

    `Layout` 协议是 iOS 16 才有的，而 iOS 15 拿不到子视图尺寸，做不到真正的
    自动换行。这里退化成横向可滚动的 HStack：不会溢出，视觉上接近。
    """
    pat = re.compile(
        r"(?m)^(?P<i>[ \t]*)(?P<mod>(?:private |fileprivate |internal |public )?)"
        r"struct\s+FlowLayout\s*:\s*Layout\s*\{")
    out = text
    guard = 0
    while guard < 20:
        guard += 1
        m = pat.search(out)
        if not m:
            break
        lb = m.end() - 1
        eb = _match_delim(out, lb)
        if not eb:
            break
        ind = m.group("i")
        repl = (
            "%(i)s%(mod)sstruct FlowLayout<Content: View>: View {\n"
            "%(i)s    var hSpacing: CGFloat = 8\n"
            "%(i)s    var vSpacing: CGFloat = 8\n"
            "%(i)s    var alignment: HorizontalAlignment = .leading\n"
            "%(i)s    private let content: Content\n"
            "\n"
            "%(i)s    init(hSpacing: CGFloat = 8, vSpacing: CGFloat = 8,\n"
            "%(i)s         alignment: HorizontalAlignment = .leading,\n"
            "%(i)s         @ViewBuilder content: () -> Content) {\n"
            "%(i)s        self.hSpacing = hSpacing\n"
            "%(i)s        self.vSpacing = vSpacing\n"
            "%(i)s        self.alignment = alignment\n"
            "%(i)s        self.content = content()\n"
            "%(i)s    }\n"
            "\n"
            "%(i)s    var body: some View {\n"
            "%(i)s        ScrollView(.horizontal, showsIndicators: false) {\n"
            "%(i)s            HStack(alignment: .center, spacing: hSpacing) { content }\n"
            "%(i)s                .padding(.vertical, vSpacing > 0 ? vSpacing / 2 : 0)\n"
            "%(i)s                .frame(maxWidth: .infinity,\n"
            "%(i)s                       alignment: Alignment(horizontal: alignment))\n"
            "%(i)s        }\n"
            "%(i)s    }\n"
            "%(i)s}"
        ) % {"i": ind, "mod": m.group("mod")}
        out = out[:m.start()] + repl + out[eb:]
    return out


def _drop_transfer_representation(text: str) -> str:
    """删掉 `static var transferRepresentation: some TransferRepresentation { … }`。

    Transferable 那套（FileRepresentation / SentTransferredFile）是 iOS 16 的；
    iOS 15 上只保留 `struct X: Transferable` 的壳，让引用它的代码还能编译。
    """
    pat = re.compile(
        r"(?m)^[ \t]*static\s+var\s+transferRepresentation\s*:[^\n]*\{")
    out = text
    guard = 0
    while guard < 20:
        guard += 1
        m = pat.search(out)
        if not m:
            break
        lb = m.end() - 1
        eb = _match_delim(out, lb)
        if not eb:
            break
        i = m.start()
        ls = out.rfind("\n", 0, i) + 1
        end = eb
        if out[end:end + 1] == "\n":
            end += 1
        out = out[:ls] + out[end:]
    return out


# 注意：不能用文件顶部的 DECL_RE —— 它只认 struct/class/enum/extension，
# 用来找「enclosing 函数」会一路穿到类型声明上，guard 就永远插不进去。
ANY_DECL_RE = re.compile(
    r"^[ \t]*(?:(?:public|internal|fileprivate|private|open|final|static|"
    r"override|mutating|@\w+(?:\([^)]*\))?)\s+)*"
    r"(?:var|let|func|init|struct|class|enum|actor|protocol|extension)\b")


def _enclosing_decl_line(lines, idx):
    """从 idx 往上找最近的、缩进更小的声明行（含 func/var/let）。"""
    if idx >= len(lines):
        idx = len(lines) - 1
    base = len(lines[idx]) - len(lines[idx].lstrip())
    for j in range(idx, -1, -1):
        ln = lines[j]
        if not ln.strip() or ln.lstrip().startswith("//"):
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind < base and ANY_DECL_RE.match(ln):
            return j
    return None


GUARD_LINE = "guard #available(iOS 16.0, *) else { return }"


def _guard_avail_in_funcs(text: str, tokens, version: str = "16.0") -> str:
    """给用到了 iOS16 token 的空返回函数体开头插入 guard #available。

    比给函数本身加 @available 安全：不改签名，调用点不用跟着改，
    也就不会沿调用链一路向上传播出一堆新错误。
    """
    lines = text.split("\n")
    need = set()
    for idx, ln in enumerate(lines):
        if not any(tok in ln for tok in tokens):
            continue
        j = _enclosing_decl_line(lines, idx)
        if j is not None and "func " in lines[j] and "-> " not in lines[j]:
            need.add(j)
    if not need:
        return text
    brace_line = {}
    for j in need:
        k = j
        while k < len(lines):
            if "{" in lines[k]:
                brace_line[k] = lines[k]
                break
            k += 1
    if not brace_line:
        return text
    out = []
    for idx, ln in enumerate(lines):
        out.append(ln)
        if idx in brace_line:
            ind = len(ln) - len(ln.lstrip())
            out.append(" " * (ind + 4)
                       + "guard #available(iOS %s, *) else { return }" % version)
    return "\n".join(out)


def _guard_sizeThatFits(text: str) -> str:
    """给 sizeThatFits(_:ProposedViewSize:...) 整段方法加 @available(iOS 16)。

    ProposedViewSize 是 iOS 16 才有的类型，iOS 15 没有同名类型也没有这个
    签名。加 @available 后，iOS 15 上整段方法不编译，UIViewRepresentable 退回
    默认 intrinsic content size；iOS 16 上正常 override。
    """
    pat = re.compile(
        r"(?m)^([ \t]*)func\s+sizeThatFits\(\s*_\s+proposal:\s*ProposedViewSize\b")
    out = text
    guard = 0
    while guard < 20:
        guard += 1
        m = pat.search(out)
        if not m:
            break
        ind = m.group(1)
        ls = out.rfind("\n", 0, m.start()) + 1
        prev_end = out.rfind("\n", 0, ls)
        prev = out[prev_end + 1:ls] if prev_end >= 0 else ""
        if "@available" in prev:
            continue
        out = out[:ls] + ("%s@available(iOS 16.0, *) // ios15-port\n" % ind) + out[ls:]
    return out


def stage3_api_fixes() -> None:
    """第 15 轮 build.log 里剩下、且能机械处理的功能型 API。"""
    n_files = 0
    for path in swift_files(ROOT):
        t = read(path)
        orig = t

        t = _convert_regex_literals(t)
        t = t.replace("ShareLink(", "MinisShareLinkButton(")
        t = _drop_transfer_representation(t)
        # sizeThatFits(_:ProposedViewSize:uiView:context:) 是 iOS 16 的
        # UIViewRepresentable 可选方法；iOS 15 没有 ProposedViewSize 也没有
        # 这个签名。整段方法加 @available(iOS 16)，iOS 15 上不编译，
        # 退回 UIViewRepresentable 默认的 intrinsic content size。
        t = _guard_sizeThatFits(t)
        # AVAssetImageGenerator.image(at:) 是 iOS 16 的 async 版本
        t = re.sub(
            r"let \(([^,]+),\s*_\)\s*=\s*try\s+await\s+(\w+)\.image\(at:\s*([^)]*)\)",
            r"let \1 = try \2.copyCGImage(at: \3, actualTime: nil)", t)
        # ToolbarItem(placement: .secondaryAction) 是 iOS 16 的位置
        t = t.replace("placement: .secondaryAction", "placement: .automatic")
        t = _replace_flow_layout(t)
        # Locale 降级后残留的可选链
        t = t.replace(".languageCode?.identifier.lowercased()",
                      ".languageCode?.lowercased()")
        # Notification.Name 的 static 成员被标成了 iOS 16（它属于 AppIntents
        # 那一批），但名字本身就是 rawValue —— 直接换成运行时构造的同名
        # Notification.Name，绕过 availability，不影响收发。
        if ".openSessionFromIntent" in t:
            t = t.replace(".openSessionFromIntent",
                          'Notification.Name("openSessionFromIntent")')
        # 单行赋值：SFSpeechAudioBufferRecognitionRequest.addsPunctuation (iOS 16)
        t = re.sub(
            r"(?m)^([ \t]*)(recognitionRequest\.addsPunctuation\s*=\s*[^\n]+)$",
            lambda m: "%sif #available(iOS 16.0, *) {\n%s    %s\n%s}"
                      % (m.group(1), m.group(1), m.group(2), m.group(1)), t)

        # 用到了整套 iOS16 框架的函数：插 guard #available，不改签名
        t = _guard_avail_in_funcs(t, (
            "NSFileProviderManager.", "NSFileProviderDomain(",
            "WeatherService.", "ShortcutNotificationDelegate",
            "ShortcutRunTracker.", "NotificationNavigationStore."))

        # 属性没法插 guard，只能标 @available —— 用它的函数上面都插了 guard，
        # 所以引用点都在 available 上下文里
        if "private static let fileProviderDomain" in t and not re.search(
                r"@available[^\n]*\n\s*private static let fileProviderDomain\b", t):
            t = re.sub(r"(?m)^([ \t]*)(private static let fileProviderDomain\b)",
                       r"\1@available(iOS 16.0, *) // ios15-port\n\1\2", t)

        if t != orig:
            write(path, t)
            n_files += 1
    log("✅ 第三阶段（Regex/ShareLink/FlowLayout/FileProvider 隔离…）："
        "%d 个文件受影响" % n_files)


# ------------------------------------------------------- 6. iOS15 兼容层

COMPAT_SWIFT = r'''//
//  iOS15Compat.swift
//  MinisApp
//
//  iOS 15 port: SwiftUI types introduced in iOS 16, reimplemented with the
//  iOS 15 API surface. Behaviour is intentionally close-but-not-identical --
//  these exist so the app compiles and stays usable on iOS 15.5, not to win
//  design awards.
//

import SwiftUI

// MARK: - AnyShape (iOS 16)

/// Type-erased `Shape`. iOS 16 ships this; iOS 15 needs a hand-rolled version.
public struct AnyShape: Shape {
    private let _path: (CGRect) -> Path

    public init<S: Shape>(_ wrapped: S) {
        // 显式闭包，不依赖 unapplied method reference —— 后者在某些
        // Swift 版本/泛型上下文下会推导失败
        _path = { rect in wrapped.path(in: rect) }
    }

    public func path(in rect: CGRect) -> Path {
        _path(rect)
    }
}

// MARK: - UnevenRoundedRectangle (iOS 16)

/// Rectangle with a per-corner radius. iOS 16 ships this; iOS 15 does not.
public struct UnevenRoundedRectangle: Shape {
    public var topLeadingRadius: CGFloat
    public var bottomLeadingRadius: CGFloat
    public var bottomTrailingRadius: CGFloat
    public var topTrailingRadius: CGFloat
    public var style: RoundedCornerStyle

    public init(topLeadingRadius: CGFloat = 0,
                bottomLeadingRadius: CGFloat = 0,
                bottomTrailingRadius: CGFloat = 0,
                topTrailingRadius: CGFloat = 0,
                style: RoundedCornerStyle = .continuous) {
        self.topLeadingRadius = topLeadingRadius
        self.bottomLeadingRadius = bottomLeadingRadius
        self.bottomTrailingRadius = bottomTrailingRadius
        self.topTrailingRadius = topTrailingRadius
        self.style = style
    }

    public func path(in rect: CGRect) -> Path {
        let w = rect.width
        let h = rect.height
        let tl = max(0, min(topLeadingRadius, min(w, h) / 2))
        let tr = max(0, min(topTrailingRadius, min(w, h) / 2))
        let bl = max(0, min(bottomLeadingRadius, min(w, h) / 2))
        let br = max(0, min(bottomTrailingRadius, min(w, h) / 2))

        var p = Path()
        p.move(to: CGPoint(x: rect.minX + tl, y: rect.minY))
        p.addLine(to: CGPoint(x: rect.maxX - tr, y: rect.minY))
        if tr > 0 {
            p.addArc(center: CGPoint(x: rect.maxX - tr, y: rect.minY + tr),
                     radius: tr, startAngle: .degrees(-90), endAngle: .degrees(0),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - br))
        if br > 0 {
            p.addArc(center: CGPoint(x: rect.maxX - br, y: rect.maxY - br),
                     radius: br, startAngle: .degrees(0), endAngle: .degrees(90),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.minX + bl, y: rect.maxY))
        if bl > 0 {
            p.addArc(center: CGPoint(x: rect.minX + bl, y: rect.maxY - bl),
                     radius: bl, startAngle: .degrees(90), endAngle: .degrees(180),
                     clockwise: false)
        }
        p.addLine(to: CGPoint(x: rect.minX, y: rect.minY + tl))
        if tl > 0 {
            p.addArc(center: CGPoint(x: rect.minX + tl, y: rect.minY + tl),
                     radius: tl, startAngle: .degrees(180), endAngle: .degrees(270),
                     clockwise: false)
        }
        p.closeSubpath()
        return p
    }
}

// MARK: - LabeledContent (iOS 16)

/// Label + value row. iOS 16 ships this; iOS 15 approximates it with an
/// `HStack` that pushes the content to the trailing edge.
public struct LabeledContent<Label: View, Content: View>: View {
    private let label: Label
    private let content: Content

    public init(@ViewBuilder content: () -> Content,
                @ViewBuilder label: () -> Label) {
        self.content = content()
        self.label = label()
    }

    public var body: some View {
        HStack(alignment: .firstTextBaseline) {
            label
            Spacer(minLength: 8)
            content
        }
    }
}

extension LabeledContent where Label == Text {
    /// `LabeledContent("Title", value: "…")`
    public init<S1: StringProtocol, S2: StringProtocol>(_ title: S1, value: S2)
    where Content == Text {
        self.init(content: { Text(value) }, label: { Text(title) })
    }

    /// `LabeledContent("Title") { … }`
    public init<S: StringProtocol>(_ title: S, @ViewBuilder content: () -> Content) {
        self.init(content: content, label: { Text(title) })
    }
}

// MARK: - NavigationPath (iOS 16)

/// Minimal stand-in for SwiftUI's iOS 16 `NavigationPath`.
///
/// The port replaces `NavigationStack(path:)` with `NavigationView`, so these
/// values are carried but never drive navigation on iOS 15. Kept as a real
/// type so existing `@State` declarations and helpers still compile.
public struct NavigationPath: Equatable {
    private var elements: [AnyHashable]

    public init() {
        elements = []
    }

    public init<C: Collection>(_ elements: C) where C.Element: Hashable {
        self.elements = elements.map { AnyHashable($0) }
    }

    public var count: Int { elements.count }
    public var isEmpty: Bool { elements.isEmpty }

    public mutating func append<V: Hashable>(_ value: V) {
        elements.append(AnyHashable(value))
    }

    public mutating func removeLast(_ k: Int = 1) {
        guard k > 0 else { return }
        elements.removeLast(min(k, elements.count))
    }

    public static func == (lhs: NavigationPath, rhs: NavigationPath) -> Bool {
        lhs.elements == rhs.elements
    }

    /// 栈顶元素 —— iOS 15 的 shim 用它决定该 push 哪一层。
    public var last: AnyHashable? { elements.last }

    public var allElements: [AnyHashable] { elements }
}

// MARK: - navigationDestination(for:) 注册表 (iOS 16)

/// iOS 16 的 `.navigationDestination(for: D.self) { d in … }` 把「值 → 目标视图」的
/// 映射交给 SwiftUI 的 path 系统。iOS 15 没有这套机制，这里用一个全局注册表
/// 近似：注册时记下类型 → 构造器，push 时按栈顶元素的实际类型回查。
///
/// 局限性：全局单例，多个 NavigationStack 共享同一份映射。本项目只有
/// ContentView 与 Settings 两处使用，且目标类型不同，实际不会串。
public final class NavigationDestinationRegistry {
    public static let shared = NavigationDestinationRegistry()

    private var handlers: [ObjectIdentifier: (Any) -> AnyView] = [:]
    private let lock = NSLock()

    public func register<D: Hashable>(_ type: D.Type,
                                      handler: @escaping (D) -> AnyView) {
        lock.lock()
        defer { lock.unlock() }
        handlers[ObjectIdentifier(type)] = { value in
            guard let typed = value as? D else { return AnyView(EmptyView()) }
            return handler(typed)
        }
    }

    public func resolve(_ value: Any) -> AnyView {
        lock.lock()
        defer { lock.unlock() }
        let key = ObjectIdentifier(type(of: value))
        if let h = handlers[key] { return h(value) }
        // 类型不完全匹配时（例如 AnyHashable 装箱差异）逐个尝试。
        for (_, h) in handlers {
            let probe = h(value)
            if !(probe is AnyView) { return probe }
        }
        return AnyView(EmptyView())
    }

    public func resolveHashable(_ value: AnyHashable) -> AnyView {
        resolve(value.base)
    }
}

/// `NavigationLink(value:)` / `NavigationStack(path:)` 共用的目标视图。
public struct NavigationPathDestinationView: View {
    let value: AnyHashable

    public init(_ value: AnyHashable) { self.value = value }

    public var body: some View {
        NavigationDestinationRegistry.shared.resolveHashable(value)
    }
}

/// `.navigationDestination(for:)` 的 iOS 15 替身：注册映射，不改变视图本身。
private struct _NavigationDestinationInstaller: ViewModifier {
    func body(content: Content) -> some View { content }
}

extension View {
    /// iOS 16 `.navigationDestination(for:destination:)` 替身。
    ///
    /// 在 iOS 15 上把 `destination` 闭包登记进注册表；`NavigationLink(value:)`
    /// 与 `NavigationStack(path:)` 随后从注册表取回目标视图。
    public func navigationDestination<D: Hashable, V: View>(
        for data: D.Type,
        @ViewBuilder destination: @escaping (D) -> V
    ) -> some View {
        NavigationDestinationRegistry.shared.register(D.self) { d in
            AnyView(destination(d))
        }
        return modifier(_NavigationDestinationInstaller())
    }
}

// MARK: - NavigationLink(value:) (iOS 16)

extension NavigationLink {
    /// iOS 16 的 `NavigationLink(value:label:)`。
    ///
    /// 在 iOS 15 上退化成传统的 `NavigationLink(destination:label:)`，目的地由
    /// `.navigationDestination` 注册表按 `value` 的实际类型解析出来。
    public init<P: Hashable>(value: P, @ViewBuilder label: () -> Label)
    where Destination == NavigationPathDestinationView {
        self.init(destination: NavigationPathDestinationView(AnyHashable(value)),
                  label: label)
    }
}

// MARK: - NavigationStack (iOS 16)

/// iOS 16 `NavigationStack` 替身。
///
/// 用 iOS 15 的 `NavigationView` + 一个隐藏的 `NavigationLink(isActive:)`
/// 模拟：path 非空 → push 栈顶对应的目标；path 清空 → pop 回根。
/// 只驱动一层（本项目 path 深度为 1，深层由视图内部的普通 NavigationLink 展开）。
public struct NavigationStack<Root: View>: View {
    @Binding private var path: NavigationPath
    private let root: Root

    public init(path: Binding<NavigationPath>, @ViewBuilder root: () -> Root) {
        self._path = path
        self.root = root()
    }

    public init(@ViewBuilder root: () -> Root) {
        self._path = .constant(NavigationPath())
        self.root = root()
    }

    public var body: some View {
        NavigationView {
            root
                .background(
                    NavigationLink(
                        isActive: Binding(
                            get: { !path.isEmpty },
                            set: { active in
                                if !active { path.removeLast(path.count) }
                            }
                        ),
                        destination: {
                            Group {
                                if let top = path.last {
                                    NavigationPathDestinationView(top)
                                } else {
                                    EmptyView()
                                }
                            }
                        },
                        label: { EmptyView() }
                    )
                    .opacity(0)
                    .frame(width: 0, height: 0)
                )
        }
        .navigationViewStyle(StackNavigationViewStyle())
    }
}

// MARK: - NavigationSplitView (iOS 16)

public enum NavigationSplitViewVisibility {
    case automatic
    case doubleColumn
    case detailOnly
}

/// iOS 15 上不存在分栏容器，退化为「固定宽度侧栏 + 详情」的 HStack。
/// 只有 iPad 宽布局会走到这里；iPhone 走 `NavigationStack` 分支。
public struct NavigationSplitView<Sidebar: View, Detail: View>: View {
    @Binding private var columnVisibility: NavigationSplitViewVisibility
    private let sidebar: Sidebar
    private let detail: Detail

    public init(columnVisibility: Binding<NavigationSplitViewVisibility>,
                @ViewBuilder sidebar: () -> Sidebar,
                @ViewBuilder detail: () -> Detail) {
        self._columnVisibility = columnVisibility
        self.sidebar = sidebar()
        self.detail = detail()
    }

    public init(@ViewBuilder sidebar: () -> Sidebar,
                @ViewBuilder detail: () -> Detail) {
        self._columnVisibility = .constant(.automatic)
        self.sidebar = sidebar()
        self.detail = detail()
    }

    public var body: some View {
        GeometryReader { geo in
            HStack(spacing: 0) {
                if columnVisibility != .detailOnly {
                    sidebar
                        .frame(width: min(340, geo.size.width * 0.36))
                }
                detail
                    .frame(maxWidth: .infinity)
            }
        }
    }
}

// MARK: - UIHostingConfiguration (iOS 16)

/// `UIHostingConfiguration` 的 iOS 15 替身。
///
/// 遵守 `UIContentConfiguration`，所以项目里的
/// `cell.applyContentConfiguration(config)` 一行都不用改：cell 拿到的是
/// 一个普通的 content configuration，内部用 `UIHostingController` 渲染。
private final class _HostingContentCellView<Content: View>: UIView, UIContentView {
    private var host: UIHostingController<AnyView>?
    var configuration: UIContentConfiguration {
        didSet { apply(configuration) }
    }

    init(configuration: UIContentConfiguration) {
        self.configuration = configuration
        super.init(frame: .zero)
        backgroundColor = .clear
        apply(configuration)
    }

    @available(*, unavailable)
    required init?(coder: NSCoder) { nil }

    private func apply(_ config: UIContentConfiguration) {
        subviews.forEach { $0.removeFromSuperview() }
        host = nil
        guard let config = config as? UIHostingConfiguration<Content> else { return }
        let controller = UIHostingController(rootView: AnyView(config.content))
        controller.view.backgroundColor = .clear
        controller.view.translatesAutoresizingMaskIntoConstraints = false
        addSubview(controller.view)
        NSLayoutConstraint.activate([
            controller.view.leadingAnchor.constraint(equalTo: leadingAnchor),
            controller.view.trailingAnchor.constraint(equalTo: trailingAnchor),
            controller.view.topAnchor.constraint(equalTo: topAnchor),
            controller.view.bottomAnchor.constraint(equalTo: bottomAnchor),
        ])
        host = controller
    }
}

public struct UIHostingConfiguration<Content: View>: UIContentConfiguration {
    public let content: Content
    private let _minWidth: CGFloat?
    private let _minHeight: CGFloat?

    public init(@ViewBuilder content: () -> Content) {
        self.content = content()
        self._minWidth = nil
        self._minHeight = nil
    }

    private init(content: Content, minWidth: CGFloat?, minHeight: CGFloat?) {
        self.content = content
        self._minWidth = minWidth
        self._minHeight = minHeight
    }

    public func minSize(width: CGFloat? = nil, height: CGFloat? = nil)
    -> UIHostingConfiguration<Content> {
        UIHostingConfiguration(content: content, minWidth: width, minHeight: height)
    }

    public func margins(_ edges: Edge.Set = .all, _ length: CGFloat? = nil)
    -> UIHostingConfiguration<Content> {
        self  // iOS 15 的替身不实现边距；cell 自身已按 zero margins 布局
    }

    public func makeContentView() -> UIView & UIContentView {
        _HostingContentCellView<Content>(configuration: self)
    }

    public func updated(for state: UIConfigurationState) -> UIHostingConfiguration<Content> {
        self
    }
}

// MARK: - PhotosPickerItem (iOS 16)

/// `PhotosUI.PhotosPickerItem` 的 iOS 15 替身。
///
///  photo picker 本身（`PhotosPicker` / `.photosPicker`）在 iOS 15 不存在，
///  移植脚本会摘掉那些 modifier，所以这里的实例永远是"空"的：
///  `loadTransferable` 返回 nil，相关代码自然走失败分支而不是崩溃。
public struct PhotosPickerItem: Hashable {
    public init() {}

    public var itemIdentifier: String? { nil }
    public var supportedContentTypes: [Any] { [] }

    public func loadTransferable<T>(type: T.Type) async throws -> T? { nil }

    public static func == (lhs: PhotosPickerItem, rhs: PhotosPickerItem) -> Bool { true }
    public func hash(into hasher: inout Hasher) {}
}

// MARK: - Transferable / ShareLink (iOS 16)

/// iOS 16 的 `Transferable` 协议替身。仅用于让 `struct X: Transferable`
/// 的声明继续成立；真正的传输行为在 iOS 15 上不可用。
public protocol Transferable {}

public enum MinisSharePresenter {
    public static func present(items: [Any]) {
        let vc = UIActivityViewController(activityItems: items, applicationActivities: nil)
        guard let scene = UIApplication.shared.connectedScenes
                .compactMap({ $0 as? UIWindowScene })
                .first(where: { $0.activationState == .foregroundActive }),
              let window = scene.windows.first(where: { $0.isKeyWindow })
                ?? scene.windows.first,
              let root = window.rootViewController else { return }
        var presenter = root
        while let presented = presenter.presentedViewController {
            presenter = presented
        }
        presenter.present(vc, animated: true)
    }
}

// MARK: - Regex 字面量替身 (iOS 16)

/// iOS 16 的 `Regex` 字面量 (`/…/`) 与 `wholeMatch(of:)` / `ranges(of:)`
/// 在 iOS 15 没有对应物，移植脚本把它们改写成这里的 NSRegularExpression 包装。
public enum MinisRegex {
    public static func wholeMatch(_ text: String, _ pattern: String) -> Bool {
        let full = NSRange(text.startIndex..., in: text)
        guard let re = try? NSRegularExpression(pattern: pattern),
              let m = re.firstMatch(in: text, range: full) else { return false }
        return NSEqualRanges(m.range, full)
    }

    public static func ranges(_ text: String, _ pattern: String) -> [Range<String.Index>] {
        guard let re = try? NSRegularExpression(pattern: pattern) else { return [] }
        let full = NSRange(text.startIndex..., in: text)
        return re.matches(in: text, range: full).compactMap { Range($0.range, in: text) }
    }
}

// MARK: - MinisShareLinkButton (ShareLink 替代, iOS 15)

/// iOS 15 没有 `ShareLink`（它是 iOS 16 才有的），这里用 `UIActivityViewController`
/// 包一个等价的分享按钮。stage3 把源码里的 `ShareLink(...)` 整调用替换成它，
/// 调用点不用改。支持 `ShareLink(item:)` / `ShareLink(item:subject:message:)` /
/// `ShareLink("标题", item:)` 三种写法。
import UIKit

public struct MinisShareLinkButton: View {
    public let item: Any
    public var subject: String? = nil
    public var message: String? = nil

    public init(item: Any, subject: String? = nil, message: String? = nil) {
        self.item = item
        self.subject = subject
        self.message = message
    }

    public init(_ label: String, item: Any) {
        self.item = item
        self.subject = nil
        self.message = nil
    }

    public var body: some View {
        Button(action: { share() }) {
            Label("Share", systemImage: "square.and.arrow.up")
        }
    }

    private func share() {
        let items: [Any]
        if let url = item as? URL {
            items = [url]
        } else if let str = item as? String {
            items = [str]
        } else {
            items = [item]
        }
        let av = UIActivityViewController(activityItems: items,
                                          applicationActivities: nil)
        if let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
           let root = scene.windows.first?.rootViewController {
            av.popoverPresentationController?.sourceView = root.view
            root.present(av, animated: true, completion: nil)
        }
    }
}
'''


def _field(blk: str, name: str):
    """从 pbxproj 对象块里取一个标量字段的值。"""
    m = re.search(r'\b' + name + r'\s*=\s*"?([^";]+)"?\s*;', blk)
    return m.group(1).strip() if m else None


def _children(blk: str):
    """取一个 group 块 children = ( ... ) 里的 uuid 列表。"""
    m = re.search(r"children\s*=\s*\((.*?)\);", blk, re.S)
    if not m:
        return []
    return re.findall(r"^\s*(\w+)\s*/\*", m.group(1), re.M)


def _all_groups(text: str):
    """[(uuid, path, children)]，只收 PBXGroup / PBXVariantGroup。"""
    b, e = _section(text, "PBXGroup")
    out = []
    if b < 0 or e <= b:
        return out
    for m in re.finditer(r"^\t\t(\w+)\s*(?:/\*[^*]*?\*/)?\s*=\s*\{", text[b:e], re.M):
        uuid = m.group(1)
        gs, ge = _block(text, uuid)
        if gs is None:
            continue
        blk = text[gs:ge]
        if "isa = PBXGroup" not in blk and "isa = PBXVariantGroup" not in blk:
            continue
        out.append((uuid, _field(blk, "path"), _children(blk)))
    return out


def resolve_compat_dir(text: str, ref: str) -> str:
    """算出 Xcode 会把 ref 解析到哪个目录（相对工程目录，"" 即工程目录）。

    兼容层以 path = "iOS15Compat.swift" + sourceTree = <group> 挂在某个 group 下，
    Xcode 按「该 group 的目录 + path」找文件；若不在任何 group 里则退回工程目录。
    磁盘上的文件必须放在同一处，否则会报 "Build input file cannot be found"。
    """
    groups = _all_groups(text)
    parent = {}
    for uuid, _p, kids in groups:
        for k in kids:
            parent.setdefault(k, uuid)
    comps = []
    cur = parent.get(ref)
    seen = set()
    while cur and cur not in seen:
        seen.add(cur)
        nxt = None
        for uuid, p, _kids in groups:
            if uuid == cur:
                if p:
                    comps.insert(0, p)
                nxt = parent.get(cur)
                break
        if nxt is None:
            break
        cur = nxt
    return "/".join(comps)


def write_compat(subdir: str = "") -> None:
    d = os.path.normpath(os.path.join(ROOT, subdir)) if subdir else ROOT
    target = os.path.join(d, COMPAT_NAME)

    # 旧版本曾写到 src/ios/Compat/ 子目录，但 pbxproj 里挂的是 mainGroup，
    # Xcode 会去 src/ios/ 找 -> 报 Build input file cannot be found。清理掉。
    stale_dir = os.path.join(ROOT, "Compat")
    stale = os.path.join(stale_dir, COMPAT_NAME)
    if os.path.isfile(stale) and os.path.abspath(stale) != os.path.abspath(target):
        try:
            os.remove(stale)
            log("🧹 已删除旧位置的兼容层 %s" % stale)
        except OSError:
            pass
        try:
            os.rmdir(stale_dir)
            log("🧹 已删除空目录 %s" % stale_dir)
        except OSError:
            pass

    os.makedirs(d, exist_ok=True)
    write(target, COMPAT_SWIFT)
    log("✅ 已写入兼容层 %s" % target)


# --------------------------------------------------- pbxproj 注入兼容层

PBX = os.path.join(ROOT, "Minis.xcodeproj", "project.pbxproj")


def _section(text: str, name: str):
    b = text.find("/* Begin %s section */" % name)
    e = text.find("/* End %s section */" % name)
    return b, e


def _block(text: str, uuid: str):
    # 注释可选：PBXGroup 里没有 name 的组写成 `UUID = {`，带 name 的才写 `UUID /* name */ = {`
    m = re.search(re.escape(uuid) + r"\s*(?:/\*.*?\*/)?\s*=\s*\{", text)
    if not m:
        return None, None
    start = m.end() - 1
    depth = 0
    i = start
    while i < len(text):
        c = text[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return m.start(), i + 1
        i += 1
    return m.start(), len(text)


def _unique(base: str, text: str) -> str:
    """生成一个 text 中尚不存在的 uuid。"""
    cand = base
    n = 0
    while cand in text:
        n += 1
        cand = base[:-2] + "%02d" % n
    return cand


def _insert_into_section(text: str, section: str, line: str):
    b, _ = _section(text, section)
    if b < 0:
        return text, False
    marker = "/* Begin %s section */" % section
    pos = b + len(marker)
    return text[:pos] + "\n" + line + text[pos:], True


def inject_compat() -> str:
    """把 iOS15Compat.swift 加入主 App target 的编译源。

    幂等 + 自愈：每一步都先检查是否已存在，只在缺失时补齐，
    所以重复执行不会叠加，也能修好上一次跑歪留下的半成品引用。

    返回 Xcode 实际会去查找该文件的目录（相对工程目录，"" 表示工程目录本身）。
    """
    if not os.path.isfile(PBX):
        log("⚠️  未找到 %s，跳过注入（兼容层不会参与编译）" % PBX)
        return ""

    text = read(PBX)
    name = re.escape(COMPAT_NAME)

    def _sec(s):
        i, j = _section(text, s)
        return text[i:j] if (i >= 0 and j > i) else ""

    # ---- 1) PBXFileReference
    ref = None
    m = re.search(r"(\w+)\s*/\*\s*" + name + r"\s*\*/\s*=\s*\{isa = PBXFileReference;",
                  _sec("PBXFileReference"))
    if m:
        ref = m.group(1)
    if ref is None:
        ref = _unique("IOS15COMPAT0000000000000A", text)
        ins = '\t\t%s /* %s */ = {isa = PBXFileReference; lastKnownFileType = sourcecode.swift; path = "%s"; sourceTree = "<group>"; };\n' % (
            ref, COMPAT_NAME, COMPAT_NAME)
        text, ok = _insert_into_section(text, "PBXFileReference", ins)
        if not ok:
            log("⚠️  找不到 PBXFileReference section，跳过注入")
            return ""
        log("✅ PBXFileReference 已创建 (%s)" % ref)
    else:
        # 自愈：path 必须是 mainGroup 子级的相对路径，否则 Xcode 找不到文件
        gs, ge = _block(text, ref)
        if gs is not None:
            blk = text[gs:ge]
            p = _field(blk, "path")
            if p and p != COMPAT_NAME:
                nb = blk.replace('path = "%s"' % p, 'path = "%s"' % COMPAT_NAME)
                nb = nb.replace("path = %s;" % p, 'path = "%s";' % COMPAT_NAME)
                if nb != blk:
                    text = text[:gs] + nb + text[ge:]
                    log("🔧 已修正文件引用路径 %s -> %s" % (p, COMPAT_NAME))

    # ---- 2) PBXBuildFile
    build = None
    m = re.search(r"(\w+)\s*/\*\s*" + name + r"\s+in Sources\s*\*/\s*=\s*\{isa = PBXBuildFile;",
                  _sec("PBXBuildFile"))
    if m:
        build = m.group(1)
    if build is None:
        build = _unique("IOS15COMPAT0000000000000B", text)
        ins2 = '\t\t%s /* %s in Sources */ = {isa = PBXBuildFile; fileRef = %s /* %s */; };\n' % (
            build, COMPAT_NAME, ref, COMPAT_NAME)
        text, ok = _insert_into_section(text, "PBXBuildFile", ins2)
        if ok:
            log("✅ PBXBuildFile 已创建 (%s)" % build)
        else:
            log("⚠️  找不到 PBXBuildFile section")

    # 3) 挂到 mainGroup 的 children
    mg = re.search(r"mainGroup\s*=\s*(\w+)", text)
    if mg:
        gs, ge = _block(text, mg.group(1))
        if gs is not None:
            blk = text[gs:ge]
            if re.search(r"^\s*%s\s*/\*" % re.escape(ref), blk, re.M):
                log("ℹ️  兼容层已在 mainGroup 中")
            elif "children" in blk:
                newblk = re.sub(r"(children\s*=\s*\()",
                                r"\1\n\t\t\t\t%s /* %s */," % (ref, COMPAT_NAME),
                                blk, count=1)
                text = text[:gs] + newblk + text[ge:]
                log("✅ 兼容层已挂到 mainGroup")
            else:
                log("⚠️  mainGroup 没有 children 列表")

    # 4) 加入主 App target 的 Sources phase
    tm = re.search(r"(\w+)\s*/\*\s*Minis\s*\*/\s*=\s*\{\s*isa = PBXNativeTarget;", text)
    if tm:
        ts, te = _block(text, tm.group(1))
        tblock = text[ts:te]
        # 找 PBXSourcesBuildPhase section 范围，判断哪个 phase 属于它
        sb, se = _section(text, "PBXSourcesBuildPhase")
        src_ids = set()
        if sb >= 0:
            src_ids = set(re.findall(r"(\w+)\s*/\*\s*Sources\s*\*/", text[sb:se]))
        for pid in re.findall(r"(\w+)\s*/\*[^)]*?\*/", tblock):
            pass
        phases = re.findall(r"(\w+)\s*/\*\s*([^*]*?)\s*\*/", tblock)
        chosen = None
        for pid, pname in phases:
            if pid in src_ids or pname == "Sources":
                chosen = pid
                break
        if chosen:
            ps, pe = _block(text, chosen)
            if ps is not None:
                pblk = text[ps:pe]
                if re.search(r"^\s*%s\s*/\*" % re.escape(build), pblk, re.M):
                    log("ℹ️  兼容层已在 Sources phase 中")
                elif "files" in pblk:
                    newp = re.sub(r"(files\s*=\s*\()",
                                  r"\1\n\t\t\t\t%s /* %s in Sources */," % (build, COMPAT_NAME),
                                  pblk, count=1)
                    text = text[:ps] + newp + text[pe:]
                    log("✅ 兼容层已加入 target 的 Sources phase (%s)" % chosen)
                else:
                    log("⚠️  Sources phase 没有 files 列表")
            else:
                log("⚠️  未定位到 Sources phase 块")
        else:
            log("⚠️  未在主 target 中找到 Sources phase，兼容层可能不参与编译")
    else:
        log("⚠️  未找到名为 Minis 的 PBXNativeTarget，跳过 Sources 注入")

    # 5) 算出 Xcode 到底会去哪个目录找这个文件（决定 write_compat 写到哪）
    sub = resolve_compat_dir(text, ref)
    log("📍 [仅提示, 非错误] 兼容层文件将写入: %s"
        % os.path.join(ROOT, sub or ""))

    write(PBX, text)
    return sub


# ------------------------------------------------------------------ main

def main() -> None:
    if not os.path.isdir(ROOT):
        log("⚠️  未找到 %s，请在仓库根目录执行本脚本" % ROOT)
        sys.exit(0)

    log("=== OpenMinis -> iOS 15 移植（第二阶段）%s ===" % SCRIPT_VERSION)
    # 1. 从上游拉干净原版覆盖 src/ios（浅克隆下 git 历史不可信，必须这么干）
    restore_from_upstream()
    cleanup_artifacts()
    # 2. 第一阶段规则在还原之后重跑一遍（否则成果会被上游源码覆盖掉）
    stage1_fixes()
    # 3. 给干净基线拍快照（结构自检的对照物，不依赖 git）
    snapshot_baseline()
    # 4. 全部转换
    fix_applocalized()
    strip_localizedstringresource()
    restore_intent_props()
    annotate_intents()
    annotate_appintent_files()
    delete_call_exprs()
    repair_orphan_trailing_closures()
    delete_modifiers()
    misc_fixes()
    stage3_api_fixes()
    # 先注入（决定文件该放在哪），再按 pbxproj 解析出的目录写文件
    subdir = inject_compat()
    write_compat(subdir)
    check_and_rollback_broken()
    log("=== 完成 ===")


if __name__ == "__main__":
    main()
