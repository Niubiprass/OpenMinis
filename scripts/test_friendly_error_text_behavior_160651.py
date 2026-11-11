#!/usr/bin/env python3
"""Behavior test for FriendlyErrorText using the production Swift source.

The harness extracts the enum from src/ios/Shared/AppLocalization.swift and
writes that exact source into a temporary Foundation-only Swift program. On a
macOS CI runner with swiftc it compiles and executes real sanitizer behavior.
This iSH checkout has no swiftc, so the compile/execute test is skipped here;
the source-extraction contract still runs locally.
"""
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src/ios/Shared/AppLocalization.swift"
MARK = "// MARK: - [T-compaction-l10n]"


def production_enum() -> str:
    source = SOURCE.read_text(encoding="utf-8")
    start = source.index("enum FriendlyErrorText {")
    end = source.index(MARK, start)
    return source[start:end].rstrip()


def harness(enum_source: str) -> str:
    # AppLocalized is the only production dependency outside Foundation. The
    # test returns the key itself, which is sufficient because the sanitizer's
    # category copy is already Chinese in the production source.
    return r'''import Foundation

func AppLocalized(_ key: String, comment: StaticString? = nil) -> String { key }

''' + enum_source + r'''

func check(_ condition: @autoclosure () -> Bool, _ message: String) {
    precondition(condition(), message)
}

let cancelled = "Error Domain=NSURLErrorDomain Code=-999 \"cancelled\" UserInfo={}"
check(FriendlyErrorText.sanitize(cancelled) == nil, "only a real NSURLError cancellation is hidden")

let providerMinus999 = #"{"code":-999,"message":"upstream failed"}"#
let minus999Display = FriendlyErrorText.sanitize(providerMinus999) ?? ""
check(minus999Display.contains("无法识别"), "provider -999 is not treated as cancellation")

let unknown = FriendlyErrorText.sanitize("Provider error: Something exploded with stack trace") ?? ""
check(unknown.contains("无法识别"), "unknown English gets Chinese fallback")
check(!unknown.contains("Something exploded"), "unknown provider text is not leaked")

let chinese = FriendlyErrorText.sanitize("Provider error: 服务暂时不可用（上游维护）") ?? ""
check(chinese.contains("服务暂时不可用（上游维护）"), "safe provider Chinese reason is retained")

let unauthorized = FriendlyErrorText.sanitize(#"HTTP 401: {"error":{"message":"Incorrect API key","type":"invalid_request_error"}}"#) ?? ""
check(unauthorized.contains("HTTP 401"), "HTTP status is retained")
check(unauthorized.contains("API Key 无效"), "401 is classified as invalid key")
check(!unauthorized.contains("invalid_request_error"), "provider JSON type is not displayed")

let rateLimited = FriendlyErrorText.sanitize(#"SSE Stream error: data: {"error":{"message":"Rate limit exceeded","code":"rate_limit_exceeded"}}"#) ?? ""
check(rateLimited.contains("短时请求过多"), "429/rate limit is classified as short throttling")
check(rateLimited.contains("代码 rate_limit_exceeded"), "safe provider code is retained")

let quota = FriendlyErrorText.sanitize(#"HTTP 402: {"error":{"message":"insufficient_quota"}}"#) ?? ""
check(quota.contains("余额或额度"), "quota is distinct from throttling")
check(!quota.contains("短时请求过多"), "quota is not mislabeled as rate limiting")

let overloaded = FriendlyErrorText.sanitize("HTTP 503: overloaded") ?? ""
check(overloaded.contains("供应商服务暂时过载"), "5xx overload is classified")

let html = FriendlyErrorText.sanitize("HTTP 524: <!DOCTYPE html><html><body>origin timeout</body></html>") ?? ""
check(html.contains("HTTP 524"), "HTML status is retained")
check(html.contains("超时"), "524 is classified as a timeout")
check(!html.contains("<html>"), "HTML body is removed")

print("FriendlyErrorText Foundation behavior: OK")
'''


class ProductionBehavior(unittest.TestCase):
    def test_harness_extracts_current_production_enum(self):
        enum_source = production_enum()
        self.assertTrue(enum_source.startswith("enum FriendlyErrorText {"))
        self.assertIn("static func sanitize(_ raw: String) -> String?", enum_source)
        self.assertIn("jsonPayload(in:", enum_source)
        self.assertIn("private static func classify", enum_source)

    def test_foundation_behavior_when_swiftc_is_available(self):
        swiftc = shutil.which("swiftc")
        if not swiftc:
            self.skipTest("swiftc unavailable in iSH; macOS CI runs this extracted Foundation harness")
        with tempfile.TemporaryDirectory(prefix="friendly-error-") as directory:
            directory = Path(directory)
            source = directory / "FriendlyErrorTextBehavior.swift"
            binary = directory / "friendly-error-behavior"
            source.write_text(harness(production_enum()), encoding="utf-8")
            compile_result = subprocess.run(
                [swiftc, str(source), "-o", str(binary)],
                text=True, capture_output=True, timeout=120,
            )
            self.assertEqual(compile_result.returncode, 0, compile_result.stderr)
            run_result = subprocess.run(
                [str(binary)], text=True, capture_output=True, timeout=30,
            )
            self.assertEqual(run_result.returncode, 0, run_result.stderr)
            self.assertIn("Foundation behavior: OK", run_result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
