#!/usr/bin/env python3
"""Source contract for stable chat principal-title geometry."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent.parent
CHAT = ROOT / "src/ios/Views/Chat/AIChatView.swift"


class ChatNavigationTitleStability(unittest.TestCase):
    def test_chat_principal_stays_on_shared_nav_frame(self):
        text = CHAT.read_text()
        self.assertIn(".modifier(NavTitleFrameModifier())", text)
        self.assertIn("ToolbarItem(placement: .principal) { title() }", text)

    def test_legacy_detail_row_keeps_constant_row_count(self):
        text = CHAT.read_text()
        title = text.split("private var titleView: some View {", 1)[1].split(
            "private var thinkingLevelBadge", 1
        )[0]
        self.assertIn("if let detail = resolved {", title)
        self.assertIn("} else if legacyLayout {", title)
        self.assertIn(".frame(height: legacyLayout ? 14 : nil, alignment: .center)", title)
        self.assertIn(".frame(height: 14)", title)


if __name__ == "__main__":
    unittest.main(verbosity=2)
