#!/usr/bin/env python3
"""Source-contract tests for [T-l10n-interpolation].

Reported 2026-10-20 with two screenshots: the composer placeholder read
「Message Minis (@ to mention files)」 in an otherwise Chinese UI, while other
hints in the same rotating placeholder were correctly Chinese
(「Minis 可以把 ↵ 键设为发送或换行」).

Root cause, and it is systemic: `AppLocalized(_ key: String)` takes a PLAIN
String, so `AppLocalized("Message \\(name) (@ to mention files)")` interpolates
FIRST and then looks up the sentence "Message Minis (@ to mention files)" — a
key that exists in no catalog. Every string with a value in it silently fell
back to English; every string without one was translated, which is exactly the
mixed result on screen.

Fix: `AppLocalizedFormat(key, args…)` looks the parameterized entry up
("Message %@ (@ to mention files)") and applies the arguments afterwards.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
LOCALIZATION = (ROOT / 'src/ios/Shared/AppLocalization.swift').read_text()
CHAT_VIEW = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
MODELS = (ROOT / 'src/ios/Agent/Chat/ChatModels.swift').read_text()


class HelperExists(unittest.TestCase):

    def test_format_helper_is_defined(self):
        self.assertIn('func AppLocalizedFormat(_ key: String, _ args: CVarArg...) -> String', LOCALIZATION)

    def test_helper_formats_after_lookup(self):
        # Look up the %@ entry, THEN substitute — the order is the whole fix.
        i = LOCALIZATION.index('func AppLocalizedFormat(')
        body = LOCALIZATION[i:i + 400]
        self.assertIn('NSLocalizedString(key, bundle: AppBundle.current', body)
        self.assertIn('String(format:', body)


class ComposerFixed(unittest.TestCase):

    def test_placeholder_uses_the_format_helper(self):
        self.assertIn('AppLocalizedFormat("Message %@ (@ to mention files)", soulName)', CHAT_VIEW)
        self.assertNotIn('AppLocalized("Message \\(soulName)', CHAT_VIEW)

    def test_mention_hint_uses_the_format_helper(self):
        self.assertIn('AppLocalizedFormat("Try @ to mention files for %@ to read", soulName)', CHAT_VIEW)
        self.assertNotIn('AppLocalized("Try @ to mention files for \\(soulName)', CHAT_VIEW)

    def test_context_usage_line_uses_the_format_helper(self):
        self.assertIn('AppLocalizedFormat("Context %@ used · %@", pct, size)', MODELS)


class CatalogCoversThem(unittest.TestCase):

    def test_every_parameterized_key_is_translated(self):
        import json
        d = json.loads((ROOT / 'src/ios/Localizable.xcstrings').read_text())
        for key in ("Message %@ (@ to mention files)",
                    "Try @ to mention files for %@ to read",
                    "Context %@ used · %@"):
            entry = d['strings'].get(key)
            self.assertIsNotNone(entry, key)
            self.assertIn('zh-Hans', entry['localizations'], key)


if __name__ == '__main__':
    unittest.main(verbosity=2)
