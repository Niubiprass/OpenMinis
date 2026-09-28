#!/usr/bin/env python3
"""读 xcodebuild 的日志，把剩下的 iOS 16/17 API 机械降级。

给工作流里的「编译 → 修复 → 再编译」循环用。

为什么需要它：静态移植脚本只能处理事先预判到的 API，而一个几万行的
SwiftUI 项目总会冒出没见过的写法。与其让人肉看日志再来一轮（一次 20 分钟），
不如让 runner 自己按机械规则收敛。

只做**语法安全**的改写：
  · 删掉整调用的 modifier（配平括号 + 尾随闭包）
  · 删掉无括号的成员访问
  · builder 里的 if/else 展平成只留一支
  · 撤回本脚本自己加过的 @available 标注
  · 给成员声明补 @available（链式 modifier 行不碰）

做完按文件写回，并打印这一轮处理了哪些错误。
"""
import os
import re
import sys

ROOT = sys.argv[2] if len(sys.argv) > 2 else "src/ios"

# xcodebuild 的诊断行前面通常有几格缩进，别用 ^ 直接锚到 '/'
AVAIL_RE = re.compile(
    r"^[ \t]*(?P<path>/\S+?\.swift):(?P<line>\d+):(?P<col>\d+): error: "
    r"(?P<msg>.*)$", re.MULTILINE
)
ONLY_RE = re.compile(r"'([^']+)' is only available in iOS (\d+(?:\.\d+)?)(?: or newer)?")
CONVERT_RE = re.compile(
    r"cannot convert value of type '[^']+' to expected argument type '([^']+)'")
CONTEXT_RE = re.compile(
    r"(?P<path>/\S+?\.swift):(?P<line>\d+):(?P<col>\d+): error: (?P<msg>.+)")

# 我们自己在移植过程中加的标注，撤回它是安全的（源码原本没有）
OUR_MARKER = "// ios15-port"

SKIP_DIRS = {"AgentWidget", "AgentWidgetExtension"}


# ---------------------------------------------------------------- 括号工具

def _skip_string(text: str, i: int) -> int:
    """text[i] 是引号，返回字符串结束后的下标。处理多行字符串与插值。"""
    n = len(text)
    if text.startswith('"""', i):
        j = i + 3
        while j < n:
            if text[j] == "\\":
                j += 2
                continue
            if text.startswith('"""', j):
                return j + 3
            j += 1
        return n
    q = text[i]
    j = i + 1
    while j < n:
        c = text[j]
        if c == "\\":
            j += 2
            continue
        if c == q:
            return j + 1
        j += 1
    return n


def _match_delim(text: str, i: int):
    """text[i] 是 ( [ { 之一，返回配对闭合符之后的下标；配不平返回 None。"""
    pairs = {"(": ")", "[": "]", "{": "}"}
    if i >= len(text) or text[i] not in pairs:
        return None
    stack = [pairs[text[i]]]
    j = i + 1
    n = len(text)
    while j < n and stack:
        c = text[j]
        if c in "\"'":
            j = _skip_string(text, j)
            continue
        if c in pairs:
            stack.append(pairs[c])
        elif c in ")]}":
            if stack[-1] == c:
                stack.pop()
            else:
                return None
        j += 1
    return j if not stack else None


def _expr_end(text: str, lp: int):
    """text[lp] 是 '('，返回整调用结束（')' 之后）的下标。"""
    e = _match_delim(text, lp)
    return e


# ---------------------------------------------------------------- 改写动作

def _delete_call(text: str, name: str, drop_closures: bool = True) -> str:
    """删掉所有 name(...) 整调用。"""
    pat = re.compile(re.escape(name) + r"\s*\(")
    out = text
    guard = 0
    while guard < 100:
        guard += 1
        m = pat.search(out)
        if not m:
            break
        lp = m.end() - 1
        e = _expr_end(out, lp)
        if e is None:
            out = out[:m.start()] + "\x00" + out[m.end():]
            continue
        end = e
        if drop_closures:
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


def _delete_member(text: str, name: str) -> str:
    """删掉 .name 这种无括号的成员访问。"""
    return re.sub(r"\." + re.escape(name) + r"\b", "", text)


def _flatten_builder_branch(text: str, line_no: int) -> str:
    """builder 里的 if/else：展平成只保留第一支。

    iOS 15 的 @ToolbarContentBuilder / 部分 builder 没有 buildIf / buildEither。
    删掉 `if … {` 与其配对的 `}`（以及 `} else {` 与它的 `}`），留下分支体。
    """
    lines = text.split("\n")
    idx = line_no - 1
    if idx >= len(lines):
        return text
    ln = lines[idx]
    m = re.match(r"^(\s*)if\b.*\{\s*$", ln)
    if not m:
        return text
    indent = m.group(1)
    offset = sum(len(x) + 1 for x in lines[:idx])
    lb = offset + ln.rfind("{")
    eb = _match_delim(text, lb)
    if not eb:
        return text
    body = text[lb + 1:eb - 1]
    # 后面紧跟 `} else {` 时，else 那支整个丢掉
    rest = text[eb:]
    em = re.match(r"\s*else\s*\{", rest)
    if em:
        lb2 = eb + rest.index("{")
        eb2 = _match_delim(text, lb2)
        if eb2:
            text = text[:lb2] + text[eb2:]
            rest = text[eb:]
    return text[:lb] + body + rest


DECL_RE = re.compile(
    r"^(?P<ind>[ \t]*)(?:(?:public|private|internal|fileprivate|open|final|"
    r"static|@\w+(?:\([^)]*\))?)\s+)*"
    r"(?P<kind>var|let|func|class|struct|enum|protocol|extension|actor)\b")


def _enclosing_decl_line(lines, idx):
    """从 idx 往上找最近的、缩进更小的声明行。"""
    base = len(lines[idx]) - len(lines[idx].lstrip()) if idx < len(lines) else 0
    for j in range(idx, -1, -1):
        ln = lines[j]
        if not ln.strip() or ln.lstrip().startswith("//"):
            continue
        ind = len(ln) - len(ln.lstrip())
        if ind < base and DECL_RE.match(ln):
            return j
    return None


def _add_available(text: str, line_no: int, version: str) -> str:
    """给包含该行的成员声明加 @available(iOS version, *)。"""
    lines = text.split("\n")
    idx = line_no - 1
    j = _enclosing_decl_line(lines, idx)
    if j is None:
        return text
    # 已经标过就不重复加
    for k in range(max(0, j - 3), j):
        if "@available" in lines[k]:
            return text
    ind = len(lines[j]) - len(lines[j].lstrip())
    marker = "@available(iOS %s, *) %s" % (version, OUR_MARKER)
    lines.insert(j, " " * ind + marker)
    return "\n".join(lines)


def _insert_guard(text: str, line_no: int, version: str) -> str:
    """在空返回的函数体开头插 guard #available(iOS v, *) else { return }。

    比 @available 好：不改函数签名，调用点不需要跟着改，也就不会沿调用链
    传播出一串新错误。
    """
    lines = text.split("\n")
    idx = line_no - 1
    j = _enclosing_decl_line(lines, idx)
    if j is None:
        return text
    k = j
    while k < len(lines) and "{" not in lines[k]:
        k += 1
    if k >= len(lines):
        return text
    ind = len(lines[k]) - len(lines[k].lstrip())
    guard_line = " " * (ind + 4) + "guard #available(iOS %s, *) else { return }" % version
    if k + 1 < len(lines) and "guard #available" in lines[k + 1]:
        return text
    lines.insert(k + 1, guard_line)
    return "\n".join(lines)


def _is_view_decl(decl_line: str) -> bool:
    """SwiftUI 的 body / some View 计算属性：绝不能加 @available。

    一旦给 `var body: some View` 标上 iOS 16，整个视图在 iOS 15 就不存在了，
    比原来的错误严重得多。
    """
    return bool(re.search(r"some\s+(View|ToolbarContent|Commands|Scene)\b", decl_line)) \
        or bool(re.search(r"\bvar\s+body\b", decl_line))


def _strip_available(text: str, symbol: str) -> str:
    """撤回某个项目符号定义上方的 @available(iOS 16/17, *) 标注。

    移植脚本为了让 AppIntents 那批代码过关，给整目录的顶层声明都加了
    @available(iOS 16.0, *)。副作用是像 NotificationNavigationStore 这种
    其实不依赖 iOS 16 的类型也被标成了 16，调用点跟着一起报 unavailable。
    把标注撤回去，比沿着调用链一路补 @available 干净得多。
    """
    pat = re.compile(
        r"(?m)^[ \t]*@available\(iOS \d+(?:\.\d+)?, \*\)[^\n]*\n"
        r"(?=[ \t]*(?:public |private |internal |fileprivate |open |final )*"
        r"(?:static )?(?:var|let|func|class|struct|enum|protocol|extension|actor)[ \t]+"
        + re.escape(symbol) + r"\b)")
    new, n = pat.subn("", text)
    return new if n else text


_DEF_CACHE = {}


def _find_definition(root: str, symbol: str):
    """在项目里找 symbol 的定义文件。结果缓存，避免每个符号都全盘 grep。"""
    if symbol in _DEF_CACHE:
        return _DEF_CACHE[symbol]
    pat = re.compile(
        r"(?m)^\s*(?:public |private |internal |fileprivate |open |final )*"
        r"(?:class|struct|enum|protocol|extension|actor)\s+" + re.escape(symbol) + r"\b")
    found = (None, None)
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fn in filenames:
            if not fn.endswith(".swift"):
                continue
            p = os.path.join(dirpath, fn)
            try:
                with open(p, encoding="utf-8", errors="replace") as f:
                    t = f.read()
            except OSError:
                continue
            if pat.search(t):
                found = (p, t)
                break
        if found[0]:
            break
    _DEF_CACHE[symbol] = found
    return found


# ---------------------------------------------------------------- 主流程

def main() -> int:
    log_path = sys.argv[1] if len(sys.argv) > 1 else "build.log"
    try:
        with open(log_path, encoding="utf-8", errors="replace") as f:
            raw = f.read()
    except OSError:
        print("[autofix] 读不到 %s" % log_path)
        return 2

    # 只认真正的文件内错误；注释里带 "error:" 的行不算
    errs = []
    for m in AVAIL_RE.finditer(raw):
        errs.append((m.group("path"), int(m.group("line")), m.group("msg")))

    # 去重（同一 site 常被报多次）
    seen = set()
    uniq = []
    for p, l, msg in errs:
        key = (p, l, msg)
        if key in seen:
            continue
        seen.add(key)
        uniq.append((p, l, msg))

    touched = {}
    stats = {"modifier": 0, "member": 0, "branch": 0,
             "unavail": 0, "guard": 0, "strip": 0, "skip": 0}

    for path, line, msg in uniq:
        if not os.path.isfile(path):
            stats["skip"] += 1
            continue
        try:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = touched.get(path) or f.read()
        except OSError:
            continue

        m = ONLY_RE.search(msg)
        symbol = None
        version = None
        if m:
            symbol, version = m.group(1), m.group(2)
        else:
            m2 = CONVERT_RE.search(msg)
            if m2:
                symbol, version = m2.group(1), "16.0"

        if not symbol:
            stats["skip"] += 1
            continue

        # 先看这一行长什么样
        lines = text.split("\n")
        cur = lines[line - 1] if line - 1 < len(lines) else ""
        stripped = cur.strip()

        new = text

        # 1) builder 的 buildIf / buildEither
        if symbol in ("buildIf", "buildEither(first:)", "buildEither(second:)"):
            new = _flatten_builder_branch(text, line)
            if new != text:
                stats["branch"] += 1
                touched[path] = new
                continue

        # 2) 链式 modifier：.foo(...)
        if "." + symbol + "(" in cur:
            new = _delete_call(text, "." + symbol)
            if new != text:
                stats["modifier"] += 1
                touched[path] = new
                continue

        # 3) 无括号的成员访问：.foo
        if re.search(r"\." + re.escape(symbol) + r"\b", cur) and "(" not in cur:
            new = _delete_member(text, symbol)
            if new != text:
                stats["member"] += 1
                touched[path] = new
                continue

        # 4) 项目自己定义的符号：先试撤回我们加的标注
        defpath, deftext = _find_definition(ROOT, symbol)
        if defpath:
            d2 = _strip_available(touched.get(defpath) or deftext, symbol)
            if d2 != (touched.get(defpath) or deftext):
                stats["strip"] += 1
                touched[defpath] = d2
                if defpath == path:
                    text = d2
                    lines = text.split("\n")
                    cur = lines[line - 1] if line - 1 < len(lines) else ""
                continue

        # 5) 系统类型/API：优先在函数体插 guard；实在不行才补 @available
        if stripped.startswith("."):
            stats["skip"] += 1
            continue
        j = _enclosing_decl_line(text.split("\n"), line - 1)
        decl = text.split("\n")[j] if j is not None else ""
        if j is None or _is_view_decl(decl):
            stats["skip"] += 1
            continue
        if re.search(r"\bfunc\b", decl) and "-> " not in decl:
            new = _insert_guard(text, line, version)
            kind = "guard"
        else:
            new = _add_available(text, line, version)
            kind = "unavail"
        if new != text:
            stats[kind] = stats.get(kind, 0) + 1
            touched[path] = new
            continue
        stats["skip"] += 1

    for p, t in touched.items():
        try:
            with open(p, "w", encoding="utf-8") as f:
                f.write(t)
        except OSError as e:
            print("[autofix] 写回失败 %s: %s" % (p, e))

    print("[autofix] 错误 %d 条 → 改动 %d 个文件 | "
          "删 modifier %d / 删成员 %d / 展平分支 %d / 补 @available %d / "
          "插 guard %d / 撤回标注 %d / 跳过 %d"
          % (len(uniq), len(touched), stats["modifier"], stats["member"],
             stats["branch"], stats["unavail"], stats["guard"],
             stats["strip"], stats["skip"]))
    return 0 if touched else 1


if __name__ == "__main__":
    sys.exit(main())
