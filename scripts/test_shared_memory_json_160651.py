#!/usr/bin/env python3
"""Source contracts for cross-device shared-memory JSON export/import."""
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORE = (ROOT / "src/ios/Agent/Session/SoulStore.swift").read_text(encoding="utf-8")
VIEW = (ROOT / "src/ios/Views/Settings/SoulSettingsView.swift").read_text(encoding="utf-8")


class SharedMemoryJSON(unittest.TestCase):
    def test_store_exports_and_imports(self):
        self.assertIn("func exportArchive() -> URL?", STORE)
        self.assertIn("func importArchive(_ data: Data, target: AgentPersona) -> Int", STORE)
        self.assertIn("targetPersonaId: target.id", STORE)
        self.assertIn("targetPersonaName: target.name", STORE)

    def test_ui_has_export_and_import(self):
        i = VIEW.index("struct SharedMemoryListView")
        j = VIEW.index("struct SharedMemoryComposeSheet", i)
        body = VIEW[i:j]
        self.assertIn("store.exportArchive()", body)
        self.assertIn("showJSONPicker", body)
        self.assertIn(".fileImporter(isPresented: $showJSONPicker", body)
        self.assertIn("store.importArchive(data, target: persona)", body)
        self.assertIn("导入给哪个人格", body)

    def test_target_is_always_local(self):
        # Foreign persona ids are never trusted; import remaps to the selected
        # local persona.
        self.assertIn("targetPersonaId: target.id", STORE)
        self.assertIn("targetPersonaName: target.name", STORE)


if __name__ == "__main__":
    print("SOURCE CONTRACTS ONLY: shared-memory JSON; no Swift/device verdict.", flush=True)
    unittest.main(verbosity=2)
