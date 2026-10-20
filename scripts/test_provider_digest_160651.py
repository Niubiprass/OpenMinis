#!/usr/bin/env python3
"""Source-contract tests for [T-provider-error-digest] and [T-compaction-l10n].

「运营商反馈回来的那种没有中文吗？」 — provider text was the last English left
on screen. It cannot be translated wholesale (protocol field names), so a
known-pattern digest puts one Chinese sentence on top and keeps the raw text
underneath, smaller and dimmer.

Also pins the compaction rows: their English sentence is written into the
transcript at compaction time, so the translation must happen at DISPLAY or old
rows would stay English forever.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
LOC = (ROOT / 'src/ios/Shared/AppLocalization.swift').read_text()
CHAT = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()
BUBBLE = (ROOT / 'src/ios/Views/Chat/ChatMessageViews.swift').read_text()


class Digest(unittest.TestCase):

    def test_known_patterns_are_covered(self):
        i = LOC.index('enum ProviderErrorDigest')
        body = LOC[i:]
        for needle in ('thinking', 'invalid api key', 'model', 'context length',
                       'rate limit', 'content filter', 'overloaded', 'timeout'):
            self.assertIn(needle, body.lower())

    def test_unknown_text_returns_nil(self):
        i = LOC.index('static func summary(for raw: String) -> String?')
        body = LOC[i:i + 300]
        self.assertIn('-> String?', body)
        self.assertIn('return nil', LOC[LOC.index('enum ProviderErrorDigest'):])

    def test_banner_shows_summary_then_raw(self):
        self.assertIn('ProviderErrorDigest.summary(for: error)', CHAT)
        self.assertIn('.font(.system(size: 10.5))', CHAT)

    def test_tool_interruption_is_chinese(self):
        model = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel.swift').read_text()
        persist = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+Persistence.swift').read_text()
        self.assertIn('AppLocalized("工具执行被意外中断了。")', model)
        self.assertIn('AppLocalized("工具执行被意外中断了。")', persist)


class CompactionRows(unittest.TestCase):

    def test_translation_happens_at_display(self):
        self.assertIn('CompactionCopy.localize(message.content)', BUBBLE)

    def test_all_four_shapes_are_handled(self):
        i = LOC.index('enum CompactionCopy')
        body = LOC[i:]
        self.assertIn('messages compacted', body)
        self.assertIn('Compacting conversation...', body)
        self.assertIn('Compacting with ', body)
        self.assertIn('Compaction failed', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
