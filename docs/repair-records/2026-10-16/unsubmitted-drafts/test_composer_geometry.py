#!/usr/bin/env python3
"""Composer source contracts; not an IME/device acceptance test."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / 'src/ios/Views/Chat/ChatInputBar.swift').read_text()

class ComposerContracts(unittest.TestCase):
    def test_intrinsic_scroll_setter_is_change_only(self):
        section = SOURCE.split('override var intrinsicContentSize: CGSize {', 1)[1].split('\n    override ', 1)[0]
        self.assertIn('let shouldScroll = size.height > maxHeight', section)
        self.assertRegex(section, r'if isScrollEnabled != shouldScroll\s*\{\s*isScrollEnabled = shouldScroll')
        self.assertIn('if let pinnedHeight', section)
        self.assertIn('min(size.height, maxHeight)', section)

    def test_pending_selection_defers_during_ime(self):
        self.assertIn('if tv.markedTextRange == nil, let want = desiredCaret {', SOURCE)
        caret = SOURCE.split('if tv.markedTextRange == nil, let want = desiredCaret {', 1)[1].split('// Keep font in sync', 1)[0]
        self.assertIn('max(0, min(want, length))', caret)
        self.assertIn('tv.selectedRange.location != clamped', caret)
        self.assertNotIn('unmarkText()', caret)

    def test_existing_ime_and_next_keystroke_protections_remain(self):
        self.assertIn('if tv.text != text, tv.markedTextRange == nil || text.isEmpty', SOURCE)
        self.assertIn('if textView.markedTextRange != nil { return true }', SOURCE)
        code = re.sub(r'//[^\n]*', '', SOURCE)
        self.assertNotIn('skipNextProgrammaticChange', code)

if __name__ == '__main__':
    unittest.main(verbosity=2)
