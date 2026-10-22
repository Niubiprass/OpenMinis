#!/usr/bin/env python3
"""Source + extracted SQLite contracts only; no Swift build, app or device run."""
from pathlib import Path
import json
import re
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORE = (ROOT / "src/ios/Agent/Chat/ChatStore.swift").read_text()
VIEW = (ROOT / "src/ios/Views/ContentView.swift").read_text()
SYNC = (ROOT / "src/ios/Agent/Sync/V2/SyncedTypes.swift").read_text()
DDL = re.search(r"CREATE TABLE IF NOT EXISTS folders \([\s\S]*?\n            \)", STORE)[0]
UPDATE = re.search(r'let sql = "(UPDATE folders SET configuration_json[^"\n]+)"', STORE)[1]
REMOTE = re.search(r'INSERT INTO folders \(id, name, icon, color, origin, sort_index, pinned_at,[\s\S]*?updated_at = excluded.updated_at', STORE)[0]
EDITOR = VIEW.split("private struct ChatFolderSettingsSheet: View {", 1)[1].split("/// A pending \"move sessions", 1)[0]
SAVE = STORE.split("func saveFolderConfiguration(", 1)[1].split("/// Create a folder", 1)[0]


class SourceContracts(unittest.TestCase):
    def test_backward_compatible_defaults(self):
        for text in ("var configuration: ChatFolderConfiguration?", "configuration: ChatFolderConfiguration? = nil",
                     "var skillDefaults: [String: Bool] = [:]", "var soulPrompt: String? = nil",
                     "var memoryPolicy: ChatFolderMemoryPolicy = .global", "var readsGlobalMemory: Bool = false",
                     "guard let json else { return .default }"):
            self.assertIn(text, STORE)
        self.assertEqual(STORE.count("try values.decodeIfPresent("), 6)
        self.assertIn('soulMode = try values.decodeIfPresent(String.self, forKey: .soulMode)', STORE)
        self.assertIn('column: "configuration_json", definition: "TEXT"', STORE)
        self.assertLess(STORE.index("CREATE TABLE IF NOT EXISTS folders ("), STORE.index('column: "configuration_json"'))

    def test_save_checks_and_no_runtime_side_effects(self):
        for text in ("guard current == expected", "SoulStore.isOverLimit(body)", "throw ChatFolderConfigurationError.soulTooLong",
                     "sqlite3_step(stmt) == SQLITE_DONE", "sqlite3_changes(db) == 1", "throw ChatFolderConfigurationError.conflict",
                     "sqlite3_bind_text(stmt", "sqlite3_destructor_type.self"):
            self.assertIn(text, SAVE)
        for text in ("markDirty(", "updated_at =", "setSessionOverride(", "SoulStore.save("):
            self.assertNotIn(text, SAVE)
        folder_sync = SYNC.split("struct SyncedFolder:", 1)[1].split("enum SyncedTypesBootstrap", 1)[0]
        self.assertNotIn("configuration", folder_sync)

    def test_editor_is_draft_only_and_honest(self):
        for text in ("SkillStore.shared", "skills.skills", "skillSelection(skill.id)", ".tag(-1)", ".tag(1)", ".tag(0)",
                     "draft.skillDefaults.removeValue(forKey: id)", "SoulStore.bodyTokenLimit", "SoulStore.tokenCount(",
                     'Button("取消") { dismiss() }', "expected: original", "catch {", "failure = error.localizedDescription",
                     "仅在本机保存分组配置", "候选功能，需独立测试", "不等于安全沙箱或隔离保证"):
            self.assertIn(text, EDITOR)
        self.assertEqual(EDITOR.count("saveFolderConfiguration("), 1)
        for text in ("AIChatViewModel", "setEnabled(", "setSessionOverride(", "SoulStore.save(", "UserDefaults", ".onChange("):
            self.assertNotIn(text, EDITOR)
        self.assertIn(".sheet(item: $folderToConfigure)", VIEW)
        self.assertIn("folderToConfigure = folder", VIEW)

    def test_runtime_context_is_bounded_and_decode_errors_propagate(self):
        resolver = STORE.split("func resolveFolderRuntimeContext(", 1)[1].split("private func folderConfigurationJSON", 1)[0]
        self.assertIn("for sessionId: String", resolver)
        self.assertIn("for _ in 0..<16", resolver)
        self.assertIn("visited.insert(cursor).inserted", resolver)
        self.assertIn("let session = getSession(cursor)", resolver)
        self.assertLess(resolver.index("session.parentSessionId"), resolver.index("session.folderId"))
        self.assertIn("cursor = parentId", resolver)
        self.assertIn("throw ChatFolderConfigurationError.invalidSessionHierarchy", resolver)
        self.assertIn("try getFolderConfiguration(folderId)", resolver)
        self.assertIn("catch ChatFolderConfigurationError.missingFolder", resolver)
        self.assertEqual(resolver.count("catch"), 1)
        self.assertNotIn("try?", resolver)

    def test_draft_folder_is_forwarded_before_run(self):
        chat = (ROOT / "src/ios/Views/Chat/AIChatView.swift").read_text()
        self.assertIn("draft.initialFolderId = initialFolderId", chat)
        self.assertIn("CachedViewModel(sessionId: sessionId, initialFolderId: initialFolderId)", chat)
        self.assertEqual(VIEW.count("initialFolderId: initialFolderId(forDraft: id)"), 2)
        draft_lookup = VIEW.split("private func initialFolderId(forDraft", 1)[1].split("/// UI bookkeeping", 1)[0]
        self.assertIn("Self.isNewSessionId(id)", draft_lookup)
        self.assertIn("pending.draftId == id", draft_lookup)
        self.assertIn(".disabled(draft.memoryPolicy != .folder)", EDITOR)
        self.assertNotIn(".disabled(true)", EDITOR)


class SQLiteContracts(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.execute(DDL)
        self.db.execute("INSERT INTO folders(id,name,created_at,updated_at) VALUES ('a','Work',1,2),('b','Work',1,2)")
        self.value = json.dumps({"skillDefaults": {"x": False}, "soulPrompt": "test", "memoryPolicy": "folder", "readsGlobalMemory": False})

    def tearDown(self):
        self.db.close()

    def test_defaults_and_old_database_migration(self):
        self.assertEqual(self.db.execute("SELECT configuration_json FROM folders").fetchall(), [(None,), (None,)])
        old = sqlite3.connect(":memory:")
        self.addCleanup(old.close)
        old.execute(DDL.replace("configuration_json TEXT,", ""))
        for _ in range(2):
            if "configuration_json" not in [row[1] for row in old.execute("PRAGMA table_info(folders)")]:
                old.execute("ALTER TABLE folders ADD COLUMN configuration_json TEXT")
        self.assertEqual([row[1] for row in old.execute("PRAGMA table_info(folders)")].count("configuration_json"), 1)

    def test_uuid_scoping_and_same_named_folders(self):
        self.assertEqual(self.db.execute(UPDATE, (self.value, "a", None)).rowcount, 1)
        self.assertEqual(self.db.execute("SELECT configuration_json FROM folders WHERE id='b'").fetchone(), (None,))
        self.assertEqual(self.db.execute("SELECT updated_at FROM folders WHERE id='a'").fetchone(), (2,))

    def test_stale_snapshot_and_deleted_folder_cannot_save(self):
        self.db.execute(UPDATE, (self.value, "a", None))
        self.assertEqual(self.db.execute(UPDATE, ("{}", "a", None)).rowcount, 0)
        self.assertEqual(self.db.execute(UPDATE, ("{}", "a", self.value)).rowcount, 1)
        self.db.execute("DELETE FROM folders WHERE id='a'")
        self.assertEqual(self.db.execute(UPDATE, (self.value, "a", "{}")).rowcount, 0)

    def test_commit_survives_database_reopen(self):
        # Only test-owned tempfile storage is touched; no app/user database.
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "chat.db"
            db = sqlite3.connect(path)
            db.execute(DDL)
            db.execute("INSERT INTO folders(id,name,created_at,updated_at) VALUES ('a','Work',1,2)")
            db.execute(UPDATE, (self.value, "a", None))
            db.commit()
            db.close()
            reopened = sqlite3.connect(path)
            try:
                self.assertEqual(reopened.execute("SELECT configuration_json FROM folders WHERE id='a'").fetchone(), (self.value,))
            finally:
                reopened.close()

    def test_remote_rename_preserves_local_configuration(self):
        self.db.execute(UPDATE, (self.value, "a", None))
        self.db.execute(REMOTE, ("a", "Renamed", None, None, "manual", 0, None, "desc", 1, 9))
        self.assertEqual(self.db.execute("SELECT name,configuration_json FROM folders WHERE id='a'").fetchone(), ("Renamed", self.value))


if __name__ == "__main__":
    unittest.main(verbosity=2)
