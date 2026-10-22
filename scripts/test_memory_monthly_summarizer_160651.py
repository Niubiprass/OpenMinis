#!/usr/bin/env python3
"""Source contracts for the monthly-memory AI summarizer (no Swift toolchain here).

Run: python3 scripts/test_memory_monthly_summarizer_160651.py

Read-only checks over one new Swift file, plus a Python rehearsal of its prompt
budget fed with the REAL rule text parsed out of that file. The rehearsal
checks the arithmetic (no off-by-one that overshoots the cap); it is not Swift
execution. No build, simulator, device, network, UserDefaults, file writes or
git access — this host has no swiftc/Xcode, so "compiles" is never claimed.
"""
import re
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SWIFT = ROOT / "src/ios/Agent/Session/MemoryMonthlySummarizer.swift"
PROJECT = ROOT / "src/ios/Minis.xcodeproj/project.pbxproj"
SOURCE = SWIFT.read_text(encoding="utf-8")

MARKER = "…（已截断）"
CJK = re.compile(r"[\u4e00-\u9fff]")


def swift_block(text, marker):
    """Balanced-brace slice starting at `marker`. Not a Swift parser.

    The production strings in this file contain no braces, so brace counting
    is sufficient here; comments and string literals are still skipped by
    `code_only` for the purity scan.
    """
    start = text.index(marker)
    brace = text.index("{", start)
    depth = 0
    for i in range(brace, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    raise AssertionError("unbalanced block: " + marker)


def code_only(text):
    """Drop comments and string literals (multi-line strings included)."""
    out = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith('"""', i):
            end = text.find('"""', i + 3)
            i = n if end < 0 else end + 3
            out.append('""')
            continue
        if text[i] == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            out.append('""')
            continue
        if text.startswith("//", i):
            end = text.find("\n", i)
            i = n if end < 0 else end
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i)
            i = n if end < 0 else end + 2
            continue
        out.append(text[i])
        i += 1
    return "".join(out)


def shape_problems(src):
    problems = []
    imports = re.findall(r"(?m)^\s*import\s+(\w+)", code_only(src))
    if imports != ["Foundation"]:
        problems.append("imports must be exactly Foundation, got %r" % (imports,))
    struct = swift_block(src, "struct MonthlyMemoryDigest")
    for decl in ("let month: String", "let summary: String", "let sourceDays: Int"):
        if decl not in struct:
            problems.append("MonthlyMemoryDigest is missing %r" % decl)
    if len(re.findall(r"let \w+: \w+", struct)) != 3:
        problems.append("MonthlyMemoryDigest must store exactly the three fields")
    if "@MainActor" in code_only(src):
        problems.append("@MainActor is not allowed on this service")
    if src.count("{") != src.count("}"):
        problems.append("unbalanced braces in file")
    for token in ("TODO", "FIXME", "fatalError("):
        if token in code_only(src):
            problems.append("leftover %r" % token)
    return problems


def error_problems(src):
    problems = []
    block = swift_block(src, "enum MonthlySummaryError")
    for case in ("case emptyInput", "case emptySummary"):
        if case not in block:
            problems.append("missing %r" % case)
    if "errorDescription: String?" not in block:
        problems.append("missing LocalizedError.errorDescription")
    desc = swift_block(block, "var errorDescription")
    for case, wanted in (("emptyInput", "日记忆"), ("emptySummary", "空摘要")):
        match = re.search(r"case \." + case + r":\s*return \"([^\"]+)\"", desc)
        if not match:
            problems.append("no Chinese description for .%s" % case)
            continue
        message = match.group(1)
        if not CJK.search(message) or wanted not in message:
            problems.append(".%s description must be Chinese and mention %r" % (case, wanted))
    if len(re.findall(r"return \"", desc)) != 2:
        problems.append("errorDescription must cover exactly the two cases")
    return problems


def prompt_problems(src):
    problems = []
    make = swift_block(src, "static func makePrompt")
    if not re.search(
        r"static func makePrompt\(\s*month: String,\s*"
        r"dailyTexts: \[\(day: String, text: String\)\],\s*"
        r"maxChars: Int = 24000\s*\) -> String",
        make,
    ):
        problems.append("makePrompt signature drifted (month/dailyTexts/maxChars=24000 -> String)")

    rules = swift_block(src, "private static func instructionBlock")
    for token in ("只输出摘要", "不得编造", "不要推测", "中文", "YYYY-MM-DD",
                  "决定", "偏好", "未完成", "截断"):
        if token not in rules:
            problems.append("rule text is missing %r" % token)
    if "不要因为" in rules and "补全" not in rules:
        problems.append("truncation rule must forbid filling the gap")
    if "\\(dayCount)" not in rules and "日记忆原文" not in rules:
        problems.append("rule text must state how many daily files it got")

    for token in ("## \\(entry.day)", "String(entry.text.prefix(cap)) + truncationMarker",
                  "truncationMarker", "maxChars", "bodyBudget", "headingCost"):
        if token not in make:
            problems.append("makePrompt is missing %r" % token)
    if not re.search(r"maxChars - instruction\.count - headingCost - joinCost - markerCost", make):
        problems.append("prompt budget must subtract the fixed parts before clipping bodies")
    if "prompt.count > maxChars" not in make:
        problems.append("no final length backstop")
    if "guard !entries.isEmpty else" not in make:
        problems.append("makePrompt must keep working for an empty month")
    if 'truncationMarker = "' + MARKER + '"' not in src:
        problems.append("truncation marker text changed")
    return problems


def digest_problems(src):
    problems = []
    digest = swift_block(src, "static func digest")
    if not re.search(
        r"static func digest\(\s*month: String,\s*"
        r"dailyTexts: \[\(day: String, text: String\)\],\s*"
        r"maxChars: Int = 24000,\s*"
        r"summarize: \(String\) async throws -> String\) async throws -> MonthlyMemoryDigest",
        digest,
    ):
        problems.append("digest must take an injected `summarize` closure and return MonthlyMemoryDigest")
    if "try await summarize(prompt)" not in digest:
        problems.append("digest must await the injected closure with the built prompt")
    if not re.search(r"guard !entries\.isEmpty else \{ throw MonthlySummaryError\.emptyInput \}", digest):
        problems.append("digest must throw .emptyInput before calling the model")
    if "trimmingCharacters(in: .whitespacesAndNewlines)" not in digest:
        problems.append("digest must trim the model answer")
    if not re.search(r"guard !summary\.isEmpty else \{ throw MonthlySummaryError\.emptySummary \}", digest):
        problems.append("digest must throw .emptySummary for a blank answer")
    if "sourceDays: entries.count" not in digest:
        problems.append("digest must report how many days fed the summary")
    if "makePrompt(month: stamp, dailyTexts: entries, maxChars: maxChars)" not in digest:
        problems.append("digest must reuse makePrompt (no second prompt builder)")
    if "maxChars: maxChars" not in digest:
        problems.append("digest must forward the caller's budget")
    return problems


FORBIDDEN = (
    "UserDefaults", "FileManager", "URLSession", "URLRequest", "URL(string",
    "String(contentsOf", "Data(contentsOf", "write(to:", ".standard",
    "DispatchQueue", "NotificationCenter", "NSUbiquitousKeyValueStore",
    "@MainActor", "Task {", "Task.detached", "async let", "print(",
    "LLMProvider", "LLMError", "ModelEntry", "ProviderConfig", "ProviderInstance",
    "OpenAI", "Anthropic", "Gemini", "OpenRouter", "Copilot", "xAI", "Kimi",
)


def purity_problems(src):
    code = code_only(src)
    return ["forbidden dependency %r" % token for token in FORBIDDEN if token in code]


def instruction_template(src):
    """The real rule text, with Swift's multiline indentation stripping applied."""
    block = swift_block(src, "private static func instructionBlock")
    start = block.index('"""') + 3
    end = block.index('"""', start)
    return textwrap.dedent(block[start:end]).strip("\n")


def render_rules(template, month, day_count):
    return (template
            .replace("\\(label)", month)
            .replace("\\(dayCount)", str(day_count))
            .replace("\\(truncationMarker)", MARKER))


def rehearse_prompt(template, month, days, max_chars=24000):
    """Mirror of makePrompt's arithmetic, fed the real rule text.

    Counts code points, which equals Swift `Character` for the CJK/ASCII used
    here (no emoji or combining marks).
    """
    entries = [(d.strip(), t.strip()) for d, t in days if t.strip()]
    rules = render_rules(template, month, len(entries))
    if not entries:
        return rules + "\n\n（本月没有可用的日记忆。）"
    heading_cost = sum(len(d) + 4 for d, _ in entries)
    join_cost = 2 + 2 * (len(entries) - 1)
    marker_cost = len(entries) * (len(MARKER) + 1)
    budget = max_chars - len(rules) - heading_cost - join_cost - marker_cost
    if budget <= 0:
        return rules
    share = budget // len(entries)
    spare = sum(max(0, share - len(t)) for _, t in entries)
    long_count = sum(1 for _, t in entries if len(t) > share)
    cap = share + (spare // long_count if long_count else 0)
    blocks = []
    for day, text in entries:
        body = text[:cap] + MARKER if len(text) > cap else text
        blocks.append("## %s\n%s" % (day, body))
    prompt = rules + "\n\n" + "\n\n".join(blocks)
    return prompt if len(prompt) <= max_chars else prompt[:max(max_chars, len(rules))]


class FileShape(unittest.TestCase):
    def test_new_file_is_self_contained(self):
        self.assertTrue(SWIFT.is_file(), "missing " + str(SWIFT))
        self.assertEqual(shape_problems(SOURCE), [])

    def test_xcode_project_was_not_touched(self):
        # Deliberately registered nowhere: `Agent/Session` is a plain group, and
        # editing project.pbxproj was out of scope for this change.
        self.assertNotIn("MemoryMonthlySummarizer.swift", PROJECT.read_text(encoding="utf-8"))


class PromptContract(unittest.TestCase):
    def test_prompt_rules_and_budget(self):
        self.assertEqual(prompt_problems(SOURCE), [])

    def test_default_budget_rehearsal_fits(self):
        template = instruction_template(SOURCE)
        days = [("2026-09-%02d" % (i + 1), "决定" * 1500) for i in range(30)]
        prompt = rehearse_prompt(template, "2026-09", days)
        self.assertLessEqual(len(prompt), 24000)
        for day, _ in days:
            self.assertIn("## " + day, prompt)
        # One mention in the rules, plus one per clipped day body.
        self.assertEqual(prompt.count(MARKER), 1 + len(days))

    def test_short_month_is_not_clipped(self):
        template = instruction_template(SOURCE)
        days = [("2026-09-%02d" % (i + 1), "第%d天：决定用 Swift，偏好中文，未完成迁移。" % (i + 1))
                for i in range(30)]
        prompt = rehearse_prompt(template, "2026-09", days)
        for day, text in days:
            self.assertIn("## %s\n%s" % (day, text), prompt)
        # Only the rules mention the marker; no body was clipped.
        self.assertEqual(prompt.count(MARKER), 1)

    def test_oversized_month_stays_under_cap(self):
        template = instruction_template(SOURCE)
        days = [("2026-09-%02d" % (i + 1), "长" * 100000) for i in range(31)]
        prompt = rehearse_prompt(template, "2026-09", days)
        self.assertLessEqual(len(prompt), 24000)
        self.assertTrue(prompt.startswith("你在整理月记忆"))
        self.assertEqual(prompt.count("## 2026-09-"), 31)

    def test_tiny_cap_keeps_rules_whole(self):
        template = instruction_template(SOURCE)
        rules = render_rules(template, "2026-09", 3)
        prompt = rehearse_prompt(template, "2026-09", [("2026-09-01", "x" * 500)] * 3, max_chars=120)
        self.assertEqual(prompt, rules)


class DigestContract(unittest.TestCase):
    def test_injection_and_errors(self):
        self.assertEqual(digest_problems(SOURCE), [])

    def test_errors_are_localized_chinese(self):
        self.assertEqual(error_problems(SOURCE), [])


class Purity(unittest.TestCase):
    def test_no_io_defaults_network_or_provider(self):
        self.assertEqual(purity_problems(SOURCE), [])


class ChecksCanFail(unittest.TestCase):
    """Negative controls: each checker must reject a source that breaks it."""

    def test_purity_check_bites(self):
        mutated = SOURCE.replace("static let truncationMarker",
                                 "static let leak = UserDefaults.standard\n    static let truncationMarker", 1)
        self.assertTrue(purity_problems(mutated))

    def test_prompt_check_bites(self):
        mutated = SOURCE.replace("不得编造", "尽量准确", 1)
        self.assertTrue(prompt_problems(mutated))

    def test_digest_check_bites(self):
        mutated = SOURCE.replace(
            "guard !entries.isEmpty else { throw MonthlySummaryError.emptyInput }", "", 1)
        self.assertTrue(digest_problems(mutated))

    def test_error_check_bites(self):
        mutated = SOURCE.replace("模型返回了空摘要", "model returned nothing", 1)
        self.assertTrue(error_problems(mutated))

    def test_block_scanner_rejects_unbalanced_source(self):
        with self.assertRaises(AssertionError):
            swift_block(SOURCE + "\nfunc broken() {", "func broken")


if __name__ == "__main__":
    unittest.main(verbosity=2)