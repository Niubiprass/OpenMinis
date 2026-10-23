#!/usr/bin/env python3
"""Source regression tests for the two small SwiftUI interaction fixes."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KEY_VIEW = (ROOT / "src/ios/Views/Providers/MultiKeyManagerView.swift").read_text()
MEMORY_VIEW = (ROOT / "src/ios/Views/Chat/ScopedMemoryLibraryView.swift").read_text()


class MultiKeyRowInteractionTests(unittest.TestCase):
    def setUp(self):
        self.row = KEY_VIEW.split("private func keyRow", 1)[1].split(
            "    private func badgeText", 1
        )[0]

    def test_row_tap_and_swipe_actions_remain(self):
        self.assertIn(".onTapGesture { editingKey = k }", self.row)
        self.assertIn('.swipeActions(edge: .leading', self.row)
        self.assertIn('.swipeActions(edge: .trailing', self.row)
        self.assertIn('Label("恢复使用", systemImage: "arrow.clockwise")', self.row)
        self.assertIn('Label("删除", systemImage: "trash")', self.row)
        self.assertIn('Label("编辑", systemImage: "pencil")', self.row)

    def test_row_has_no_resident_pencil_or_trash_buttons(self):
        self.assertNotIn('.accessibilityLabel(Text("编辑 Key"))', self.row)
        self.assertNotIn('.accessibilityLabel(Text("删除 Key"))', self.row)
        self.assertEqual(self.row.count('Image(systemName: "pencil")'), 0)
        self.assertEqual(self.row.count('Image(systemName: "trash")'), 0)


class MemoryDrawerInteractionTests(unittest.TestCase):
    def test_drawer_header_label_expands_and_hits_blank_space(self):
        header = MEMORY_VIEW.split('Button {\n                            toggleDrawer(section.title)', 1)[1].split(
            '.buttonStyle(.plain)', 1
        )[0]
        self.assertIn('.frame(maxWidth: .infinity)', header)
        self.assertIn('.contentShape(Rectangle())', header)
        self.assertLess(header.index('.frame(maxWidth: .infinity)'),
                         header.index('.contentShape(Rectangle())'))

    def test_drawer_header_keeps_plain_style(self):
        self.assertIn('.buttonStyle(.plain)', MEMORY_VIEW)


if __name__ == "__main__":
    unittest.main()
