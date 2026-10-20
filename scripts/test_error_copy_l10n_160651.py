#!/usr/bin/env python3
"""Source-contract tests for [T-error-copy-l10n].

Reported 2026-10-20 with a screenshot of the transcript banner:
「⚠️ Rate limited — please try again later」 sitting in an otherwise Chinese UI.
The user's words: 有时候也是看不懂它的这种提示.

The banner prints `LLMError.errorDescription` VERBATIM, and the group-exhausted
trail appends `fallbackReason` once per attempted model. Both were English
literals, so every provider failure leaked English into the transcript no matter
which language the app was set to.

Contract:
- Every user-facing sentence in LLMError goes through AppLocalized.
- Anything with a value interpolated keeps the value: format strings, not
  string concatenation, so the provider's id/number survives untranslated.
- The Chinese catalog actually carries all of them — a localized call whose key
  is missing renders English again, which is the exact bug being fixed.
"""
import json
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
ERROR = (ROOT / 'src/ios/Providers/LLMError.swift').read_text()
CATALOG = json.loads((ROOT / 'src/ios/Localizable.xcstrings').read_text())

NEEDED = {
    "Rate limited — please try again later": "请求太频繁，请稍后再试",
    "Invalid API key": "API Key 无效",
    "Invalid API key: %@": "API Key 无效：%@",
    "Network error: %@": "网络错误：%@",
    "Provider error: %@": "服务商报错：%@",
    "Service temporarily unavailable: %@": "服务暂时不可用：%@",
    "Decoding error: %@": "返回数据解析失败：%@",
    "Request was cancelled": "请求已取消",
    "Unknown error: %@": "未知错误：%@",
    "no details": "无详细信息",
}


def zh(key):
    entry = CATALOG['strings'].get(key)
    if not entry:
        return None
    return entry.get('localizations', {}).get('zh-Hans', {}).get('stringUnit', {}).get('value')


class ErrorCopyLocalized(unittest.TestCase):

    @staticmethod
    def _code_only(body):
        # Comments legitimately quote the old English copy (the doc comment
        # explains what the bug was); only CODE matters here.
        return "\n".join(l for l in body.split("\n") if not l.strip().startswith("//"))

    def test_no_bare_english_returns(self):
        # The English text still appears — as the LOOKUP KEY inside
        # AppLocalized("…"), which is exactly how the catalog finds its
        # translation. What must be gone is a bare `return "Rate limited…"`,
        # the shape that leaked English into a Chinese UI.
        body = self._code_only(ERROR[ERROR.index('var errorDescription: String?'):ERROR.index('var isNetworkError')])
        self.assertNotIn('return "', body)
        self.assertNotIn('?? "', body)

    def test_each_case_uses_app_localized(self):
        body = ERROR[ERROR.index('var errorDescription: String?'):ERROR.index('var isNetworkError')]
        self.assertEqual(body.count('AppLocalized('), 10)

    def test_values_are_interpolated_not_dropped(self):
        # The provider's own text (ids, quota numbers, http codes) must survive.
        for fmt in ('AppLocalized("Network error: %@"), error.localizedDescription',
                    'AppLocalized("Provider error: %@"), message',
                    'AppLocalized("Decoding error: %@"), error.localizedDescription'):
            self.assertIn(fmt, ERROR)

    def test_fallback_reason_also_localized(self):
        body = ERROR[ERROR.index('var fallbackReason: String'):ERROR.index('var isFallbackable')]
        self.assertIn('AppLocalized("Rate limited")', body)
        self.assertIn('AppLocalized("Invalid API key")', body)
        self.assertIn('AppLocalized("Error")', body)

    def test_catalog_has_every_chinese_translation(self):
        missing = [k for k, v in NEEDED.items() if zh(k) != v]
        self.assertEqual(missing, [])

    def test_translation_keeps_format_placeholders(self):
        for key in NEEDED:
            if '%@' in key:
                self.assertEqual(zh(key).count('%@'), key.count('%@'), key)


if __name__ == '__main__':
    unittest.main(verbosity=2)
