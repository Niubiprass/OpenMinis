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

ROOT = Path(__file__).resolve().parents[1]
LOC = (ROOT / 'src/ios/Shared/AppLocalization.swift').read_text()
CHAT = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
BUBBLE = (ROOT / 'src/ios/Views/Chat/ChatMessageViews.swift').read_text()
PROVIDERS = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
ADD_PROVIDER = (ROOT / 'src/ios/Views/Providers/AddProviderView.swift').read_text()


class Sanitizer(unittest.TestCase):

    def test_helper_exists(self):
        self.assertIn('enum FriendlyErrorText {', LOC)

    def test_cancellation_is_suppressed_only_for_real_cancel(self):
        i = LOC.index('private static func isCancellation')
        body = LOC[i:i + 600]
        self.assertIn('capture(#"\\bCode=(-999)', body)
        self.assertIn('NSURLErrorDomain', body)
        self.assertIn('cancelled', body.lower())
        self.assertIn('guard text.hasPrefix("Error Domain=NSURLErrorDomain")', body)

    def test_cancel_returns_nil_not_a_message(self):
        i = LOC.index('static func sanitize(_ raw: String) -> String?')
        body = LOC[i:i + 600]
        self.assertIn('guard !isCancellation(text) else { return nil }', body)

    def test_raw_nserror_is_classified_without_foundation_wrapper(self):
        i = LOC.index('private static func rewriteRawNSError')
        body = LOC[i:i + 900]
        self.assertIn('Error Domain=', body)
        self.assertIn('classify(reason', body)
        self.assertIn('NSURLErrorCancelled', body)

    def test_html_dump_is_collapsed_without_markup(self):
        i = LOC.index('private static func collapseHTMLDump')
        body = LOC[i:i + 1000]
        self.assertIn('<!doctype', LOC.lower())
        self.assertIn('return classify("", status: status', body)
        self.assertIn('524', LOC)  # cloudflare-family codes mapped

    def test_provider_json_sse_and_safe_code_are_extracted(self):
        self.assertIn('JSONSerialization.jsonObject', LOC)
        self.assertIn('data:', LOC)
        self.assertIn('collectJSON', LOC)
        self.assertIn('safeCode', LOC)
        self.assertIn('stripKnownWrapper', LOC)

    def test_required_categories_have_chinese_display_copy(self):
        for phrase in ('余额或额度不足', '短时请求过多', '没有权限', 'API Key 无效',
                       '模型或路由不存在', '上下文超出', '内容被供应商审核',
                       '服务暂时过载', '请求超时', '网络连接失败', '证书或 TLS',
                       '文件读写失败', '无法识别的错误'):
            self.assertIn(phrase, LOC)

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
