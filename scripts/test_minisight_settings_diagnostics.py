#!/usr/bin/env python3
"""Structural checks for the split settings architecture; no iOS build."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"
STORE = (IOS / "MiniSightConfigStore.swift").read_text()
SCHEMA = (IOS / "MiniSightSettings.swift").read_text()
VIEW = (IOS / "Views/Settings/MiniSightSettingsView.swift").read_text()
PAGES = "\n".join(p.read_text() for p in (IOS / "Views/Settings").glob("MiniSight*Page.swift"))
AI = (IOS / "Views/Settings/MiniSightAIPage.swift").read_text()


class SettingsArchitecture(unittest.TestCase):
    def test_every_key_has_store_page_and_snapshot(self):
        keys = dict(re.findall(r'static let (\w+) = "(minisight\.[\w.]+)"', SCHEMA))
        self.assertGreaterEqual(len(keys), 40)
        snapshot = SCHEMA[SCHEMA.index("enum MiniSightRuntimeSnapshot"):]
        for variable, key in keys.items():
            with self.subTest(key=key):
                self.assertIn(variable, STORE, "store property missing")
                bound = (f"config.{variable}" in PAGES or f"$config.{variable}" in PAGES
                         or f"MiniSightSettingKey.{variable}" in PAGES
                         or variable in {"aiPermissions", "shownRevision"})
                self.assertTrue(bound, "no page binding")
                self.assertIn(key, snapshot + SCHEMA, "not in snapshot or schema")

    def test_publish_is_bounded_retry_not_single_read(self):
        self.assertTrue("dispatch_after" in STORE or "asyncAfter" in STORE)
        self.assertIn("attempt >= 4", STORE)
        self.assertIn("revision_retry", STORE)
        self.assertIn("revision_visible", STORE)

    def test_file_writes_verified_and_persona_autosave(self):
        shown = VIEW[VIEW.index("static func saveShown("):VIEW.index("static func loadAI(")]
        self.assertIn("throws", shown)
        self.assertIn("Data(contentsOf: shownURL) == expected", shown)
        self.assertIn("DispatchQueue.main.asyncAfter(deadline: .now() + 0.5", AI)
        self.assertIn("replacingPersona(text, in: current)", VIEW)
        self.assertIn("verified == data, UIImage(data: verified) != nil", VIEW)

    def test_ai_test_uses_shared_client_and_logs(self):
        for stage in ("click", "skip", "response"):
            self.assertIn(f'"ai_test", "{stage}"', AI)
        self.assertIn("MiniSightAI(container:", AI)
        self.assertNotIn("URLSession", AI)
        self.assertNotIn("localizedDescription", AI)

    def test_reader_is_bounded_and_sanitized(self):
        reader = VIEW[VIEW.index("enum MiniSightSettingsDiagnostics"):]
        self.assertIn("static let tailBytes = 60 * 1024", reader)
        self.assertIn("read(upToCount: tailBytes)", reader)
        self.assertIn("for (key, value) in input where allowed.contains(key)", reader)


if __name__ == "__main__":
    unittest.main(verbosity=2)
