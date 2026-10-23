#!/usr/bin/env python3
"""Source contracts for folder drawers on the Storage page."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORAGE = (ROOT / "src/ios/Views/Settings/StorageManagementView.swift").read_text(encoding="utf-8")


class StorageGrouping(unittest.TestCase):
    def test_sessions_carry_folder_identity(self):
        self.assertIn("let folderId: String?", STORAGE)
        self.assertIn("let folderName: String?", STORAGE)
        self.assertIn("session.folderId.flatMap { folderNames[$0] }", STORAGE)

    def test_drawers_and_ungrouped_section(self):
        self.assertIn("struct StorageSessionGroup", STORAGE)
        self.assertIn("private var sessionGroups", STORAGE)
        self.assertIn('AppLocalized("未分组")', STORAGE)
        self.assertIn('@AppStorage("storage.collapsedGroups")', STORAGE)
        self.assertIn("toggleGroup(group.id)", STORAGE)
        self.assertIn("ForEach(sessionGroups)", STORAGE)

    def test_rows_still_keep_swipe_cleanup(self):
        self.assertIn("private func sessionRow", STORAGE)
        self.assertIn("SessionStorageDetailView(session: session", STORAGE)
        self.assertIn(".swipeActions(edge: .trailing, allowsFullSwipe: false)", STORAGE)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: storage drawers; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)
