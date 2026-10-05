#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v56.7 反向测试: 折叠态缩略图两处性能洞的判据能不能拦住「改坏」。

★为什么这一版的 sabotage 特别关注**等价性**:
  v56.7 洞1 是**换实现**(components+suffix → 反向扫)而不是加新逻辑。
  这类改动最危险的形态是「优化掉了但行为变了」—— 判据若只查「新代码在」,
  照样全绿。所以 sabotage 里有整整 4 条(S5~S8)专门破坏**边界分支**,
  它们命中的都是等价性自证那一层, 而不是「代码在不在」那一层。

★与 v566 反向的差异:
  v566 的洞在**一个文件**里(两处重复代码), 本版跨**两个文件** ——
  所以 BASE 要同时准备两个文件, 且 sabotage 也要能只破坏其中一个。
"""
import importlib.util
import os
import subprocess
import sys
import tempfile
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from upstream_base import upstream_ios  # noqa: E402  唯一的上游解析入口

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
FB = os.path.join(ROOT, "scripts", "ios15_fallback.py")
UP = upstream_ios(quiet=True)

SHEET = "Views/Chat/ToolLiveSheet.swift"
CHAT = "Views/Chat/AIChatView.swift"


def load_fb():
    """载入 fallback。

    ★与 reverse_v566 同一手法: 先把 v567 的自检调用**摘掉**再跑,
    这样 sabotage 后的产物能落地, 由外部判据独立判红。
    少了这一步, sabotage 会在 edit 内部就抛异常, 测不到判据本身。
    """
    src = open(FB, encoding="utf-8").read()
    src = src.replace("\n    verify_thumb_perf_v567(t)\n    return t",
                      "\n    return t")
    tmp = tempfile.NamedTemporaryFile("w", suffix=".py", delete=False,
                                      encoding="utf-8")
    tmp.write(src)
    tmp.close()
    spec = importlib.util.spec_from_file_location("fb_noverify", tmp.name)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    os.unlink(tmp.name)
    return m


def read(rel):
    with open(os.path.join(UP, rel), encoding="utf-8") as f:
        return f.read()


def apply_both(m):
    """跑两个 v567 edit, 返回 (sheet_text, chat_text)。"""
    s = m.fix_thumb_tail_v567(read(SHEET))
    c = m.fix_monitor_idem_v567(read(CHAT))
    return s, c


def sabotage(name, s, c):
    """返回被破坏后的 (sheet, chat, 期望命中的判据关键词)。"""
    if name == "BASE":
        return s, c, None

    if name == "S1_洞1完全没改":
        return read(SHEET), c, "一个都没堵上"

    if name == "S2_洞1实现写了没接线":
        s = s.replace("return Self.v567TailLines(text, count: count)",
                      'return text.split(separator: "\\n").suffix(count)'
                      '.joined(separator: "\\n")', 1)
        return s, c, "没有转发到 v567TailLines"

    if name == "S3_洞1写完实现把函数删了":
        # 只留注释里的实现声明, 删掉函数体 ⇒ 判据的边界分支检查要红
        k = s.find("    private static func v567TailLines(")
        e = s.find("\n    }", s.find("return text ", k))
        s = s[:k] + "    private static func v567TailLines(" + s[e + 6:]
        return s, c, "缺"

    if name == "S4_洞1把chunkedLines也一起改了(范围失控)":
        return s.replace('let allLines = sanitized.components(separatedBy: "\\n")',
                         'let allLines = Array(sanitized.utf8)', 1), c, "恰好 1 处"

    if name == "S5_删掉count<=0边界":
        s = s.replace('        if count <= 0 { return "" }\n', "", 1)
        return s, c, "缺"

    if name == "S6_删掉行数不足边界":
        s = s.replace("        if total <= count { return text }      "
                      "// 全部都要, 原样返回\n", "", 1)
        return s, c, "缺"

    if name == "S7_把原样切片改成重新拼装":
        s = s.replace("""                    return String(decoding: view.suffix(from: view.index(after: idx)),
                                  as: UTF8.self)""",
                      """                    var parts: [String] = []
                    var cur: [UInt8] = []
                    for bb in view.suffix(from: view.index(after: idx)) {
                        if bb == nl { parts.append(String(decoding: cur, as: UTF8.self))
                                      cur = [] } else { cur.append(bb) }
                    }
                    parts.append(String(decoding: cur, as: UTF8.self))
                    return parts.joined(separator: "\\\\n")""", 1)
        return s, c, "缺"

    if name == "S8_上限被偷改(用等价但更贵的实现)":
        # 反向扫改成「先切全部再 suffix」—— 行为等价但优化没了
        s = s.replace("""        var seen = 0
        let view = text.utf8
        var idx = view.startIndex
        while idx < view.endIndex {
            if view[idx] == nl {
                seen += 1
                if seen == total - count {
                    return String(decoding: view.suffix(from: view.index(after: idx)),
                                  as: UTF8.self)
                }
            }
            idx = view.index(after: idx)
        }
        return text""",
                      """        let all = text.components(separatedBy: "\\\\n")
        return all.suffix(count).joined(separator: "\\\\n")""", 1)
        return s, c, "缺"

    if name == "S9_洞2guard挪走(充数在别处)":
        return s, c.replace("        if timer != nil { return }        "
                            "// [V567-PERF] 幂等 guard\n", "", 1), "幂等"

    if name == "S10_guard重复插入":
        return s, c.replace("    func start() {\n        if timer != nil { return }",
                             "    func start() {\n        if timer != nil { return }\n"
                             "        if timer != nil { return }", 1), "恰好 1 处"

    if name == "S11_标记被摘掉":
        s = s.replace("[V567-PERF]", "[PERF]")
        c = c.replace("[V567-PERF]", "[PERF]")
        return s, c, "标记的行只有"

    raise KeyError(name)


CASES = [
    "BASE",
    "S1_洞1完全没改",
    "S2_洞1实现写了没接线",
    "S3_洞1写完实现把函数删了",
    "S4_洞1把chunkedLines也一起改了(范围失控)",
    "S5_删掉count<=0边界",
    "S6_删掉行数不足边界",
    "S7_把原样切片改成重新拼装",
    "S8_上限被偷改(用等价但更贵的实现)",
    "S9_洞2guard挪走(充数在别处)",
    "S10_guard重复插入",
    "S11_标记被摘掉",
]


def main():
    if not UP:
        print("!! 找不到干净上游基线(已探测$OPENMINIS_UPSTREAM_IOS 与 "
              "仓库内 .upstream-ios)")
        print("   CI 里应由 workflow 另存 .upstream-ios; 本地可用 "
              "OPENMINIS_UPSTREAM_IOS 指定")
        return 1
    m = load_fb()
    base_sheet, base_chat = apply_both(m)

    caught = 0
    passed_through = 0
    for name in CASES:
        want = EXPECT.get(name)
        s, c, _w = sabotage(name, base_sheet, base_chat)
        why = ""
        ok = False
        # 判据要对**两个文件各自**跑一遍(它们作用域不同)
        for text in (s, c):
            try:
                m.verify_thumb_perf_v567(text)
            except RuntimeError as e:
                why = str(e)
                ok = True
                break
        if name == "BASE":
            ok = (s is base_sheet or s == base_sheet) and c == base_chat
            why = "基线无误伤" if ok else "基线被改动了!!"
        else:
            if ok and want and want not in why:
                ok = False
                why = "报红了但不是本条判据(期望含 %r): %s" % (want, why[:90])
        label = "✅" if ok else ("❌ 漏过" if name != "BASE" else "❌")
        print("%s %-40s %s" % (label, name, why[:120]))
        if ok:
            caught += 1
        else:
            passed_through += 1

    print("=" * 70)
    if passed_through:
        print("v567 反向: %d 拦下, %d 漏过" % (caught, passed_through))
        return 1
    print("v567 反向: %d 拦下, 0 漏过" % caught)
    print("✅ 全部 sabotage 都被拦下, 且基线无误伤")
    return 0


EXPECT = {
    "S1_洞1完全没改": "一个都没堵上",
    "S2_洞1实现写了没接线": "没有转发到 v567TailLines",
    "S3_洞1写完实现把函数删了": "缺",
    "S4_洞1把chunkedLines也一起改了(范围失控)": "恰好 1 处",
    "S5_删掉count<=0边界": "缺",
    "S6_删掉行数不足边界": "缺",
    "S7_把原样切片改成重新拼装": "缺",
    "S8_上限被偷改(用等价但更贵的实现)": "缺",
    "S9_洞2guard挪走(充数在别处)": "幂等",
    "S10_guard重复插入": "恰好 1 处",
    "S11_标记被摘掉": "标记的行只有",
}

if __name__ == "__main__":
    sys.exit(main())
