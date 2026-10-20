#!/usr/bin/env python3
"""Source-contract tests for [T-friendly-error-text].

Two banners reported 2026-10-20, right after the "everything is Chinese now"
build went in:

    1) Error Domain=NSURLErrorDomain Code=-999 "已取消" UserInfo={NSErrorFa…
    2) 服务商报错：HTTP 524: <!DOCTYPE html><!--[if lt IE 7]> <html class="no-js ie…

(1) is the raw NSError description — English scaffolding around a Chinese
    message — and code -999 is `NSURLErrorCancelled`: a superseded or stopped
    request, not a failure. Showing it trains the user to ignore the banner.
(2) is a relay answering with an HTML error page; the provider layer prefixes a
    500-character body cap, so the banner renders markup.

Both are presentation problems and are fixed at the presentation edge, leaving
the underlying error untouched for logs and fallback decisions.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
LOC = (ROOT / 'src/ios/Shared/AppLocalization.swift').read_text()
CHAT = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
BUBBLE = (ROOT / 'src/ios/Views/Chat/ChatMessageViews.swift').read_text()


class Sanitizer(unittest.TestCase):

    def test_helper_exists(self):
        self.assertIn('enum FriendlyErrorText {', LOC)

    def test_cancellation_is_suppressed(self):
        i = LOC.index('private static func isCancellation')
        body = LOC[i:i + 400]
        self.assertIn('Code=-999', body)
        self.assertIn('cancelled', body.lower())

    def test_cancel_returns_nil_not_a_message(self):
        i = LOC.index('static func sanitize(_ raw: String) -> String?')
        body = LOC[i:i + 500]
        self.assertIn('if isCancellation(text) { return nil }', body)

    def test_raw_nserror_is_rewritten(self):
        i = LOC.index('private static func rewriteRawNSError')
        body = LOC[i:i + 900]
        self.assertIn('Error Domain=', body)
        self.assertIn('网络错误：%@', body)

    def test_html_dump_is_collapsed_to_its_status_line(self):
        i = LOC.index('private static func collapseHTMLDump')
        body = LOC[i:i + 1200]
        self.assertIn('<!doctype', body.lower())
        self.assertIn('服务商返回了一个错误页面（不是接口响应）', body)
        self.assertIn('524', LOC)  # cloudflare-family codes mapped

    def test_http_codes_get_human_meanings(self):
        i = LOC.index('private static func httpMeaning')
        body = LOC[i:i + 900]
        # 524 shares a combined case with the other Cloudflare 52x codes.
        for code in ('429', '500', '502', '503', '504'):
            self.assertIn(f'case {code}', body)
        self.assertIn('520, 521, 522, 523, 524', body)


class AppliedAtDisplay(unittest.TestCase):

    def test_banner_uses_the_sanitizer_and_hides_when_nil(self):
        self.assertIn('let friendly = FriendlyErrorText.sanitize(error)', CHAT)

    def test_inline_error_uses_the_sanitizer(self):
        self.assertIn('FriendlyErrorText.sanitize(rawError)', BUBBLE)


if __name__ == '__main__':
    unittest.main(verbosity=2)
