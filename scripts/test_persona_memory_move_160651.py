#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[T-persona-memory-move] Persona memory move backend (source contracts).

This host has no swiftc/Xcode, so these are SOURCE-level checks, not a compile
or device verdict. They pin:
  * the two exact entry points the memory UI will call,
  * the ordering that keeps a failed move from losing text,
  * the path rules that keep a move inside memory/personas/,
  * that sharing (copy) is still a separate, non-destructive path.

Run: python3 scripts/test_persona_memory_move_160651.py
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOUL_PATH = ROOT / "src/ios/Agent/Session/SoulStore.swift"
SOUL = SOUL_PATH.read_text(encoding="utf-8")

MOVE_SIG = (
    "func moveMemory(fromPersonaId sourceId: String, "
    "toPersonaId targetId: String) -> Bool"
)
MOVE_FILE_SIG = (
    "func moveMemoryFile(named fileName: String, "
    "toPersonaId targetId: String?) -> Bool"
)
HELPER_SIG = "func memoryFileURL(named fileName: String) -> URL?"
POST = "NotificationCenter.default.post(name: .memoryFilesDidChange, object: nil)"


def brace_block(source, open_index):
    """Return the {...} block at `open_index`, ignoring braces in comments/strings."""
    depth = 0
    i = open_index
    n = len(source)
    in_line = in_block = in_string = False
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if in_line:
            if c == "\n":
                in_line = False
        elif in_block:
            if c == "*" and nxt == "/":
                in_block = False
                i += 1
        elif in_string:
            if c == "\\":
                i += 1
            elif c == '"':
                in_string = False
        elif c == "/" and nxt == "/":
            in_line = True
            i += 1
        elif c == "/" and nxt == "*":
            in_block = True
            i += 1
        elif c == '"':
            in_string = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[open_index:i + 1]
        i += 1
    raise AssertionError("unbalanced braces after index %d" % open_index)


def body_of(signature):
    """Method body including its closing brace."""
    start = SOUL.index(signature)
    brace = SOUL.index("{", start)
    return brace_block(SOUL, brace)


class Base(unittest.TestCase):
    def assert_before(self, body, first, second):
        self.assertIn(first, body)
        self.assertIn(second, body)
        self.assertLess(body.index(first), body.index(second),
                        "%r must appear before %r" % (first, second))


class Signatures(Base):
    def test_persona_store_owns_the_move_api(self):
        store = SOUL.split("final class PersonaStore: ObservableObject", 1)[1]
        store = store.split("extension Notification.Name", 1)[0]
        for sig in (MOVE_SIG, MOVE_FILE_SIG, HELPER_SIG):
            self.assertIn(sig, store)
        # Not bolted onto SharedMemoryStore: sharing stays a copy.
        shared = SOUL.split("final class SharedMemoryStore: ObservableObject", 1)[1]
        self.assertNotIn("moveMemory", shared)

    def test_signatures_are_exact_and_discardable(self):
        for name, sig in (("moveMemory", MOVE_SIG), ("moveMemoryFile", MOVE_FILE_SIG)):
            self.assertRegex(
                SOUL,
                r"@discardableResult\s+" + re.escape(sig),
                "%s must stay @discardableResult so the UI can ignore the Bool" % name,
            )
            self.assertRegex(SOUL, rf"func {name}\(.*\)\s*->\s*Bool", re.S)

    def test_read_only_helper_has_no_side_effects(self):
        helper = body_of(HELPER_SIG)
        self.assertIn("validatedMemoryFileURL(named: fileName)", helper)
        self.assertIn("regularFileType(at: url) == .typeRegular", helper)
        for forbidden in ("write(", "createFile", "createDirectory", "removeItem"):
            self.assertNotIn(forbidden, helper)


class MoveBetweenPersonas(Base):
    def setUp(self):
        self.body = body_of(MOVE_SIG)

    def test_same_id_is_rejected_first(self):
        self.assertIn("guard sourceId != targetId else { return false }", self.body)
        # Before any lookup or file access.
        self.assert_before(self.body, "guard sourceId != targetId", "persona(id: sourceId)")
        self.assert_before(self.body, "guard sourceId != targetId", "readMemoryText")

    def test_both_personas_must_exist(self):
        self.assertIn(
            "guard let source = persona(id: sourceId), "
            "let target = persona(id: targetId) else { return false }",
            self.body,
        )
        self.assert_before(self.body, "persona(id: sourceId)", "memoryURL(for: source.id)")
        self.assert_before(self.body, "persona(id: targetId)", "appendMemoryText")

    def test_missing_blank_and_non_utf8_source_are_rejected(self):
        self.assertIn("regularFileType(at: sourceURL) == .typeRegular", self.body)
        self.assertIn("let raw = readMemoryText(at: sourceURL)", self.body)
        self.assertIn("let content = raw.trimmingCharacters(in: .whitespacesAndNewlines)", self.body)
        self.assertIn("guard !content.isEmpty else { return false }", self.body)
        self.assert_before(self.body, "trimmingCharacters", "appendMemoryText")

    def test_header_is_source_name_plus_minute_stamp(self):
        self.assertIn(
            r'"\n\n## 从 \(source.name) 移入 · \(memoryTimestamp())\n\n\(content)"',
            self.body,
        )
        stamp = body_of("private func memoryTimestamp")
        self.assertIn('"yyyy-MM-dd HH:mm"', stamp)
        self.assertIn("en_US_POSIX", stamp)
        self.assertIn("Calendar(identifier: .gregorian)", stamp)

    def test_target_is_written_before_source_is_cleared(self):
        self.assert_before(
            self.body,
            "appendMemoryText(block, to: memoryURL(for: target.id))",
            "clearMemoryFile(at: sourceURL)",
        )
        # The source text is read before anything is written anywhere.
        self.assert_before(self.body, "readMemoryText(at: sourceURL)", "appendMemoryText")

    def test_source_survives_as_empty_file_and_persona_is_kept(self):
        self.assertIn("clearMemoryFile(at: sourceURL)", self.body)
        self.assertNotIn("removeItem", self.body)
        self.assertNotIn("delete(id:", self.body)
        self.assertNotIn("personas.removeAll", self.body)
        clear = body_of("private func clearMemoryFile")
        self.assertIn("try Data().write(to: url, options: .atomic)", clear)

    def test_posts_only_after_the_move_completes(self):
        self.assertIn(POST, self.body)
        self.assertGreater(self.body.rindex(POST), self.body.index("clearMemoryFile(at: sourceURL)"))
        self.assertTrue(
            self.body.rstrip().endswith(POST + "\n        return true\n    }"),
            "the success path must post then return true",
        )


class MoveOrphanFile(Base):
    def setUp(self):
        self.body = body_of(MOVE_FILE_SIG)

    def test_bare_markdown_name_only(self):
        validator = body_of("private func isValidMemoryFileName")
        for rule in (
            "fileName.count > 3",
            'fileName.hasSuffix(".md")',
            '!fileName.hasPrefix(".")',
            '!fileName.contains("/")',
            r'!fileName.contains("\\")',
            '!fileName.contains("..")',
            "CharacterSet.controlCharacters",
        ):
            self.assertIn(rule, validator)
        self.assertIn("else { return false }", validator)
        resolver = body_of("private func validatedMemoryFileURL")
        self.assertIn("guard isValidMemoryFileName(fileName) else { return nil }", resolver)

    def test_direct_child_and_regular_file_only(self):
        resolver = body_of("private func validatedMemoryFileURL")
        self.assertIn("personasDirectory.standardizedFileURL", resolver)
        self.assertIn("url.deletingLastPathComponent().standardizedFileURL.path == directory.path", resolver)
        self.assertIn("if let type = regularFileType(at: url), type != .typeRegular { return nil }", resolver)
        # A name is never joined with a caller-supplied path component.
        self.assertNotIn("appendingPathComponent(fileName, isDirectory: true)", resolver)

    def test_nil_target_appends_to_global(self):
        self.assertIn(
            'targetURL = AIChatViewModel.minisMemoryPersistentDir.appendingPathComponent("GLOBAL.md")',
            self.body,
        )
        self.assertIn('heading = "从未归属移入"', self.body)
        self.assertIn("if let targetId {", self.body)

    def test_persona_target_requires_an_existing_persona(self):
        self.assertIn("guard let target = persona(id: targetId) else { return false }", self.body)
        self.assertIn("targetURL = memoryURL(for: target.id)", self.body)
        self.assertIn(r'heading = "从 \(fileName) 移入"', self.body)

    def test_target_cannot_be_the_source_file(self):
        self.assertIn(
            "guard targetURL.standardizedFileURL.path != sourceURL.standardizedFileURL.path "
            "else { return false }",
            self.body,
        )

    def test_source_is_deleted_only_after_target_write(self):
        self.assert_before(self.body, "readMemoryText(at: sourceURL)", "appendMemoryText")
        self.assert_before(self.body, "appendMemoryText(block, to: targetURL)", "deleteMemoryFile(at: sourceURL)")
        delete = body_of("private func deleteMemoryFile")
        self.assertIn("try FileManager.default.removeItem(at: url)", delete)
        # A move deletes; it must not leave an empty orphan behind.
        self.assertNotIn("clearMemoryFile", self.body)

    def test_blank_source_is_rejected(self):
        self.assertIn("guard !content.isEmpty else { return false }", self.body)
        self.assert_before(self.body, "trimmingCharacters", "appendMemoryText")

    def test_posts_only_after_the_move_completes(self):
        self.assertIn(POST, self.body)
        self.assertGreater(self.body.rindex(POST), self.body.index("deleteMemoryFile(at: sourceURL)"))
        self.assertTrue(
            self.body.rstrip().endswith(POST + "\n        return true\n    }"),
            "the success path must post then return true",
        )


class SharingStaysACopy(Base):
    def test_shared_store_is_untouched(self):
        shared = SOUL.split("final class SharedMemoryStore: ObservableObject", 1)[1]
        self.assertIn("func share(source:", shared)
        self.assertIn("func copyToTarget(", shared)
        self.assertIn("来自", shared)
        self.assertIn("options: .atomic", shared)
        self.assertNotIn("moveMemory", shared)
        self.assertNotIn("removeItem", shared)

    def test_persona_memory_paths_are_unchanged(self):
        self.assertIn("func memoryURL(for personaId: String) -> URL", SOUL)
        self.assertIn('appendingPathComponent("\\(personaId).md")', SOUL)
        self.assertIn("private func ensureMemoryFile(for personaId: String)", SOUL)

    def test_memory_view_contract_is_unchanged(self):
        view = (ROOT / "src/ios/Views/Chat/SessionMemoryView.swift").read_text(encoding="utf-8")
        self.assertIn(
            "init(root: MemoryLibraryRoot, fileName: String, title: String? = nil,",
            view,
        )
        self.assertIn("private let fileName: String", view)


if __name__ == "__main__":
    unittest.main(verbosity=2)