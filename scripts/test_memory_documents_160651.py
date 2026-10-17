#!/usr/bin/env python3
"""Source contracts + optional compiled Foundation-only tests; never a device verdict.

Run: python3 scripts/test_memory_documents_160651.py
Set V64R_REQUIRE_SWIFT=1 to fail closed if swiftc is unavailable. No installation.
Only test-owned files in tempfile are created/cleaned up by the runtime harness.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
STORE_PATH = ROOT / "src/ios/Agent/Session/MemoryDocumentStore.swift"
VIEW_PATH = ROOT / "src/ios/Views/Chat/ScopedMemoryLibraryView.swift"
STORE = STORE_PATH.read_text(encoding="utf-8")
VIEW = VIEW_PATH.read_text(encoding="utf-8")
SESSION = (ROOT / "src/ios/Views/Chat/SessionMemoryView.swift").read_text(encoding="utf-8")
MANAGEMENT = (ROOT / "src/ios/Views/Settings/MemoryManagementView.swift").read_text(encoding="utf-8")
SHARE = (ROOT / "src/ios/Views/Chat/MinisShareSheet.swift").read_text(encoding="utf-8")
CONTENT = SESSION.split("struct MemoryContentView: View", 1)[1].split("// MARK: - Memory Write Detail", 1)[0]
EDITOR = MANAGEMENT.split("struct MemoryFileEditView: View", 1)[1].split("extension Notification.Name", 1)[0]


def between(source, start, end):
    return source.split(start, 1)[1].split(end, 1)[0]


class SourceContracts(unittest.TestCase):
    def test_fixed_interfaces(self):
        self.assertIn("struct MemoryLibraryRoot: Identifiable", STORE)
        for name, kind in (("id", "String"), ("title", "String"), ("directory", "URL"),
                           ("isReadOnly", "Bool"), ("isGlobal", "Bool")):
            self.assertRegex(STORE, rf"let {name}:\s*{kind}")
        self.assertIn("struct ScopedMemoryLibraryView<Header: View>: View", VIEW)
        self.assertEqual(VIEW.count("init(title: String, roots: [MemoryLibraryRoot], onSaveDirty: MemorySaveDirty? = nil"), 2)
        self.assertIn("@ViewBuilder header: () -> Header", VIEW)
        self.assertIn("extension ScopedMemoryLibraryView where Header == EmptyView", VIEW)
        self.assertIn("struct ScopedMemoryDocumentView: View", VIEW)
        self.assertIn("MemoryContentView(root: root, fileName: fileName, onSaveDirty: onSaveDirty)", VIEW)
        self.assertIn("init(root: MemoryLibraryRoot, fileName: String, title: String? = nil,", CONTENT)
        self.assertIn("init(root: MemoryLibraryRoot, snapshot: MemoryDocumentStore.Snapshot,", EDITOR)
        for source in (VIEW, CONTENT, EDITOR):
            self.assertIn("onSaveDirty: MemorySaveDirty?", source)
        self.assertIn("func readSnapshot(", STORE)
        self.assertIn("func list() throws", STORE)
        self.assertIn("func export(_ snapshots:", STORE)

    def test_foundation_only_and_no_implicit_scope(self):
        self.assertEqual(re.findall(r"^import (\w+)", STORE, re.M), ["Foundation"])
        for token in ("AIChatViewModel", "activeSession", "minisMemoryPersistentDir", "UserDefaults",
                      "AppStorage", "ChatStore", "UIKit", "SoulStore", "NotificationCenter"):
            self.assertNotIn(token, STORE)
        for token in ("activeSession", "minisMemoryPersistentDir", "AppStorage", "memory.global.enabled"):
            self.assertNotIn(token, VIEW)

    def test_lock_cas_and_exact_bytes(self):
        save = between(STORE, "func save(", "func export(")
        self.assertIn("private static let lock = NSLock()", STORE)
        self.assertIn("try locked {", save)
        self.assertIn("originalBytes: Data?", STORE)
        self.assertIn("let current = try self.readBytes(at: url)", save)
        self.assertIn("(current != nil) == snapshot.exists", save)
        self.assertIn("current == snapshot.originalBytes", save)
        self.assertLess(save.index("current == snapshot.originalBytes"), save.index("bytes.write"))
        self.assertIn("throw Failure.conflict", save)
        self.assertIn("Data(text.utf8)", save)
        self.assertIn("options: .atomic", save)
        self.assertIn("NSFileCoordinator", STORE)
        self.assertIn("canImport(Darwin)", STORE)
        self.assertIn("External uncoordinated writers do not share the lock", STORE)

    def test_readonly_and_path_checks_are_in_store(self):
        save = between(STORE, "func save(", "func export(")
        self.assertLess(save.index("guard !root.isReadOnly"), save.index("createDirectory"))
        self.assertIn("throw Failure.readOnly", save)
        for token in ('fileName.hasSuffix(".md")', '!fileName.hasPrefix(".")',
                      '!fileName.contains("/")', '!fileName.contains("\\\\")',
                      'CharacterSet.controlCharacters', 'type != .typeRegular',
                      'type == .typeDirectory', 'canonical == directories[index]'):
            self.assertIn(token, STORE)
        self.assertIn("matches.count == 1", STORE)
        self.assertNotIn("contentsOfDirectory(at: directory", STORE)
        listing = between(STORE, "func list()", "func readSnapshot(")
        self.assertIn('if root.isGlobal && !names.contains("GLOBAL.md")', listing)
        self.assertIn('$0.caseInsensitiveCompare("SOUL.md") != .orderedSame', listing)

    def test_missing_global_documents_only_and_no_read_creation(self):
        read = between(STORE, "private func readUnlocked(", "private func makeSnapshot(")
        self.assertEqual(read.count('root.isGlobal && ["GLOBAL.md", "SOUL.md"].contains(fileName)'), 2)
        self.assertIn("throw Failure.missing", read)
        self.assertIn("String(data: bytes, encoding: .utf8) != nil", STORE)
        self.assertNotIn("try?", STORE)
        self.assertNotIn("createDirectory", between(STORE, "func list()", "func save("))
        self.assertNotIn("createDirectory", read)
        for token in ("removeItem", "delete", "copyItem", "moveItem", "enumerator("):
            self.assertNotIn(token, STORE)

    def test_export_snapshot_sources_and_safe_temp(self):
        export = between(STORE, "func export(", "private func locked")
        for token in ("fm.temporaryDirectory", "UUID().uuidString", '"memories.md"',
                      "snapshot.originalText", "snapshot.exists", "root.title", "root.id", "snapshot.fileName"):
            self.assertIn(token, export)
        self.assertNotIn("Data(contentsOf:", export)
        self.assertIn('"## Source:', export)
        self.assertIn('### File:', export)
        self.assertNotIn("visibility", export)

    def test_draft_cancel_refresh_and_failed_save(self):
        cancel = between(EDITOR, 'Button("Cancel")', '// [T-global-memory-save-always-visible]')
        self.assertIn('{ dismiss() }', cancel)
        for token in ("store.save", "markGlobalMemoryDirty", "post(name:", "onSaved("):
            self.assertNotIn(token, cancel)
        self.assertIn("_content = State(initialValue: snapshot.originalText)", EDITOR)
        self.assertIn("TextEditor(text: $content)", EDITOR)
        self.assertNotIn(".onReceive(", EDITOR)
        self.assertNotIn(".onChange(", EDITOR)
        save = EDITOR.split("private func save()", 1)[1]
        success, catch = save.split("} catch {", 1)
        self.assertIn("let saved = try store.save(snapshot, text: content)", success)
        for token in ("onSaveDirty(root, fileName)", "markGlobalMemoryDirty(root: root, fileName: fileName)",
                      "onSaved(saved)", ".memoryFilesDidChange", "dismiss()"):
            self.assertLess(success.index("try store.save"), success.index(token))
            self.assertNotIn(token, catch)
        self.assertIn("saveError = error.localizedDescription", catch)
        self.assertNotIn("content =", catch)
        self.assertNotIn('"Saved"', catch)
        self.assertIn(".sheet(item: $editingSnapshot, onDismiss: { reload() }) { base in", CONTENT)
        callback = between(CONTENT, "MemoryFileEditView(root:", ".navigationViewStyle(")
        for token in ("snapshot: base", "onSaveDirty: onSaveDirty", "snapshot = result", "saved = true"):
            self.assertIn(token, callback)
        self.assertEqual(CONTENT.count("guard editingSnapshot == nil else { return }"), 2)
        self.assertIn(".disabled(editingSnapshot != nil || snapshot?.exists != true)", CONTENT)
        self.assertIn("guard editingSnapshot == nil, let snapshot = snapshot else { return }", CONTENT)
        self.assertIn("try store.export([snapshot])", CONTENT)
        self.assertIn(".interactiveDismissDisabled(true)", CONTENT)
        self.assertIn(".interactiveDismissDisabled(true)", EDITOR)

    def test_ios15_toolbar_sheet_and_global_management(self):
        self.assertIn("UIActivityViewController(activityItems: [safeURL]", SHARE)
        self.assertIn("MinisShareSheet.sanitizedShareURL(url) ?? url", SHARE)
        self.assertIn("ToolbarItem(placement: .cancellationAction)", EDITOR)
        self.assertIn("ToolbarItem(placement: .confirmationAction)", EDITOR)
        self.assertIn('Button("Cancel")', EDITOR)
        self.assertIn('Button("Save") { save() }.disabled(root.isReadOnly)', EDITOR)
        self.assertIn(".disabled(root.isReadOnly || snapshot == nil || editingSnapshot != nil)", CONTENT)
        self.assertIn("NavigationView {", CONTENT)
        self.assertIn("ScopedMemoryLibraryView(title: AppLocalized(\"Memory\"), roots: [.sharedMemory])", MANAGEMENT)
        for source in (VIEW, CONTENT):
            self.assertIn(".sheet(item: $share) { MinisShareSheet(url: $0.url) }", source)
        for source in (VIEW, CONTENT, EDITOR):
            for token in ("ShareLink(", "ImageRenderer", "SwiftData", ".topBarTrailing", "NavigationStack {",
                          "ToolbarItemGroup", "onDelete"):
                self.assertNotIn(token, source)

    def test_dirty_map_only_after_global_success(self):
        dirty = VIEW.split("func markGlobalMemoryDirty", 1)[1].split("struct MemoryShareItem", 1)[0]
        for token in ("guard root.isGlobal", 'case "GLOBAL.md"', '"MemoryGlobalV2"', '"memory-global"',
                      'case "SOUL.md"', "SoulStore.refreshCache()", '"SoulV2"', '"soul"', '"MemoryDailyV2"'):
            self.assertIn(token, dirty)
        self.assertIn("formatter.isLenient = false", dirty)
        self.assertIn("formatter.string(from: date) == stem", dirty)
        self.assertIn("if let onSaveDirty = onSaveDirty { onSaveDirty(root, fileName) }", EDITOR)
        self.assertIn("else { markGlobalMemoryDirty(root: root, fileName: fileName) }", EDITOR)
        self.assertNotIn("markGlobalMemoryDirty(", CONTENT)
        self.assertEqual(VIEW.count("func markGlobalMemoryDirty"), 1)

    def test_search_selection_and_library_refresh(self):
        for token in (".searchable(text: $query", "$0.rootID == root.id", "$0.fileName.localizedCaseInsensitiveContains(term)",
                      "root.title.localizedCaseInsensitiveContains(term)", "$0.originalText.localizedCaseInsensitiveContains(term)",
                      ".disabled(!document.exists)", "guard isLibraryVisible else { return }",
                      "selected.formIntersection(Set(roots.flatMap { filtered($0) }.map { $0.id }))",
                      "selected.formIntersection(Set(roots.flatMap { filtered($0) }.filter { $0.exists }.map { $0.id }))",
                      "try store.export(documents.filter { selected.contains($0.id) })"):
            self.assertIn(token, VIEW)
        self.assertNotIn("store.save(", VIEW)


SWIFT_TEST = r'''
import Foundation

func check(_ condition: @autoclosure () throws -> Bool, _ name: String) throws {
    guard try condition() else { throw NSError(domain: "MemoryTest", code: 1, userInfo: [NSLocalizedDescriptionKey: name]) }
}
func rejects(_ expected: MemoryDocumentStore.Failure? = nil, _ name: String, _ operation: () throws -> Void) throws {
    do { try operation() }
    catch {
        if let expected = expected {
            try check((error as? MemoryDocumentStore.Failure) == expected, name + ": wrong error: \(error)")
        }
        return
    }
    try check(false, name + ": unexpectedly succeeded")
}
let fm = FileManager.default
let base = URL(fileURLWithPath: CommandLine.arguments[1], isDirectory: true).standardizedFileURL.resolvingSymlinksInPath()
func root(_ id: String, _ name: String, readOnly: Bool = false, global: Bool = false) -> MemoryLibraryRoot {
    MemoryLibraryRoot(id: id, title: "Source " + id, directory: base.appendingPathComponent(name, isDirectory: true),
                      isReadOnly: readOnly, isGlobal: global)
}
func write(_ root: MemoryLibraryRoot, _ name: String, _ content: String) throws {
    try fm.createDirectory(at: root.directory, withIntermediateDirectories: true)
    try Data(content.utf8).write(to: root.directory.appendingPathComponent(name), options: .atomic)
}
let group = root("group-A", "a")
let other = root("group-B", "b")
let global = root("global", "global", global: true)
let store = MemoryDocumentStore(roots: [group, other, global])
try check(!fm.fileExists(atPath: global.directory.path), "init must not create directories")
let initial = try store.list()
try check(initial.count == 1 && initial[0].fileName == "GLOBAL.md" && !initial[0].exists, "global placeholder")
let pending = try store.readSnapshot(rootID: "global", fileName: "GLOBAL.md")
var cancelledDraft = pending.originalText
cancelledDraft = "draft never saved"
try check(cancelledDraft == "draft never saved", "independent draft")
try check(!fm.fileExists(atPath: global.directory.path), "list/read/cancel must not create directory")
try rejects(.unsavedExport, "missing global is not saved") { _ = try store.export([pending]) }
let created = try store.save(pending, text: "# Global\n用户偏好\n")
try check(created.exists && created.originalText == "# Global\n用户偏好\n", "create global")
try rejects(.conflict, "stale missing snapshot must not overwrite") { _ = try store.save(pending, text: "lost") }
let emptyRoot = root("empty", "empty", global: true)
let emptyStore = MemoryDocumentStore(roots: [emptyRoot])
let missingEmpty = try emptyStore.readSnapshot(rootID: "empty", fileName: "GLOBAL.md")
try write(emptyRoot, "GLOBAL.md", "")
try rejects(.conflict, "missing versus existing empty") { _ = try emptyStore.save(missingEmpty, text: "lost") }

try write(group, "2026-10-17.md", "# A\n原文\n")
try write(other, "2026-10-17.md", "# B\nsecond group\n")
try write(global, "SOUL.md", "identity\n")
let soul = try store.readSnapshot(rootID: "global", fileName: "SOUL.md")
try check(soul.originalText == "identity\n", "direct SOUL entry is readable")
let listed = try store.list()
try check(!listed.contains { $0.fileName.lowercased() == "soul.md" }, "SOUL excluded from list")
try check(listed.filter { $0.fileName == "2026-10-17.md" }.count == 2, "root/filename distinct")
let original = try store.readSnapshot(rootID: "group-A", fileName: "2026-10-17.md")
try rejects(.unauthorized, "unknown root") { _ = try store.readSnapshot(rootID: "unknown", fileName: "GLOBAL.md") }
let duplicate = MemoryDocumentStore(roots: [group, group])
try rejects(.unauthorized, "duplicate root ID") { _ = try duplicate.list() }
let wrongDirectory = root("group-A", "elsewhere")
let wrongStore = MemoryDocumentStore(roots: [wrongDirectory])
try rejects(.unauthorized, "snapshot cannot cross root directory") { _ = try wrongStore.save(original, text: "lost") }
let readonly = MemoryLibraryRoot(id: group.id, title: group.title, directory: group.directory, isReadOnly: true, isGlobal: false)
let readonlyStore = MemoryDocumentStore(roots: [readonly])
let roSnapshot = try readonlyStore.readSnapshot(rootID: group.id, fileName: original.fileName)
try rejects(.readOnly, "readonly save") { _ = try readonlyStore.save(roSnapshot, text: "lost") }
try check(try store.readSnapshot(rootID: group.id, fileName: original.fileName).originalText == original.originalText,
          "readonly must not change bytes")
'''

SWIFT_TEST += r'''
for name in ["../escape.md", "/tmp/escape.md", "folder/file.md", "folder\\file.md", "..md", ".hidden.md", "", "a:bad.md", "bad\n.md", "bad\0.md", "a.MD"] {
    try rejects(.unsafePath, "unsafe filename \(name)") { _ = try store.readSnapshot(rootID: group.id, fileName: name) }
}
try fm.createDirectory(at: group.directory.appendingPathComponent("nested"), withIntermediateDirectories: true)
try Data("hidden nested file".utf8).write(to: group.directory.appendingPathComponent("nested/hidden.md"))
try check(!(try store.list()).contains { $0.fileName == "hidden.md" }, "list must not recurse")
try fm.createDirectory(at: group.directory.appendingPathComponent("directory.md"), withIntermediateDirectories: true)
try rejects(.unsafePath, "directory cannot be read as document") { _ = try store.readSnapshot(rootID: group.id, fileName: "directory.md") }
let links = root("links", "links")
try fm.createDirectory(at: links.directory, withIntermediateDirectories: true)
try fm.createSymbolicLink(atPath: links.directory.appendingPathComponent("link.md").path,
                          withDestinationPath: other.directory.appendingPathComponent("2026-10-17.md").path)
try fm.createSymbolicLink(atPath: links.directory.appendingPathComponent("dangling.md").path,
                          withDestinationPath: base.appendingPathComponent("absent.md").path)
let linkStore = MemoryDocumentStore(roots: [links])
for name in ["link.md", "dangling.md"] {
    try rejects(.unsafePath, "file symlink \(name)") { _ = try linkStore.readSnapshot(rootID: links.id, fileName: name) }
}
try rejects(.unsafePath, "symlink list must fail explicitly") { _ = try linkStore.list() }
let rootLink = root("root-link", "root-link")
try fm.createSymbolicLink(atPath: rootLink.directory.path, withDestinationPath: other.directory.path)
let rootLinkStore = MemoryDocumentStore(roots: [rootLink])
try rejects(.unsafePath, "root symlink") { _ = try rootLinkStore.readSnapshot(rootID: rootLink.id, fileName: "2026-10-17.md") }
let parentLink = base.appendingPathComponent("parent-link")
try fm.createSymbolicLink(atPath: parentLink.path, withDestinationPath: base.path)
let childLink = MemoryLibraryRoot(id: "child-link", title: "child", directory: parentLink.appendingPathComponent("b"),
                                  isReadOnly: false, isGlobal: false)
try rejects(.unsafePath, "ancestor symlink") {
    _ = try MemoryDocumentStore(roots: [childLink]).readSnapshot(rootID: childLink.id, fileName: "2026-10-17.md")
}

// External changes BEFORE CAS are detected; uncoordinated changes DURING CAS cannot be guaranteed.
try write(group, original.fileName, "external change\n")
try rejects(.conflict, "raw edit before CAS") { _ = try store.save(original, text: "lost") }
let fresh = try store.readSnapshot(rootID: group.id, fileName: original.fileName)
let independentStore = MemoryDocumentStore(roots: [group])
_ = try independentStore.save(fresh, text: "winner\n")
try rejects(.conflict, "other store instance") { _ = try store.save(fresh, text: "stale\n") }
let removed = try store.readSnapshot(rootID: group.id, fileName: original.fileName)
try fm.moveItem(at: group.directory.appendingPathComponent(original.fileName),
                to: group.directory.appendingPathComponent("test-owned-removed.fixture"))
try rejects(.conflict, "removed existing file") { _ = try store.save(removed, text: "lost") }
try check(!fm.fileExists(atPath: group.directory.appendingPathComponent(original.fileName).path), "CAS must not recreate removed file")
try write(group, original.fileName, "\u{00E9}")
let composed = try store.readSnapshot(rootID: group.id, fileName: original.fileName)
try write(group, original.fileName, "e\u{0301}")
try rejects(.conflict, "canonically equivalent but byte-different UTF8") { _ = try store.save(composed, text: "lost") }
let valid = try store.readSnapshot(rootID: group.id, fileName: original.fileName)
try Data([0xff, 0xfe]).write(to: group.directory.appendingPathComponent(original.fileName), options: .atomic)
try rejects(.invalidUTF8, "invalid UTF8 read") { _ = try store.readSnapshot(rootID: group.id, fileName: original.fileName) }
try rejects(.invalidUTF8, "read failure must not be treated as empty") { _ = try store.save(valid, text: "lost") }
try check(try Data(contentsOf: group.directory.appendingPathComponent(original.fileName)) == Data([0xff, 0xfe]), "error leaves bytes intact")
try write(group, original.fileName, "before concurrent saves\n")
let concurrentSnapshot = try store.readSnapshot(rootID: group.id, fileName: original.fileName)
let resultLock = NSLock()
var successes = 0
var conflicts = 0
var unexpected: [String] = []
DispatchQueue.concurrentPerform(iterations: 2) { index in
    do {
        _ = try (index == 0 ? store : independentStore).save(concurrentSnapshot, text: "writer-\(index)\n")
        resultLock.lock(); successes += 1; resultLock.unlock()
    } catch {
        resultLock.lock()
        if (error as? MemoryDocumentStore.Failure) == .conflict { conflicts += 1 }
        else { unexpected.append(String(describing: error)) }
        resultLock.unlock()
    }
}
try check(successes == 1 && conflicts == 1 && unexpected.isEmpty, "exactly one concurrent save succeeds")

let otherSnapshot = try store.readSnapshot(rootID: other.id, fileName: original.fileName)
let exportURL = try store.export([original, otherSnapshot])
let exported = try String(contentsOf: exportURL, encoding: .utf8)
try check(exportURL.lastPathComponent == "memories.md" && exportURL.lastPathComponent.utf8.allSatisfy { $0 < 128 }, "ASCII export filename")
let tempPath = fm.temporaryDirectory.standardizedFileURL.resolvingSymlinksInPath().path
try check(exportURL.standardizedFileURL.resolvingSymlinksInPath().path.hasPrefix(tempPath + "/"), "export must be inside app temp")
try check(exported.contains("Source group-A [group-A]") && exported.contains("Source group-B [group-B]"), "export source headings")
try check(exported.components(separatedBy: "### File: 2026-10-17.md").count == 3, "same filename keeps both sources")
try check(exported.contains(original.originalText) && exported.contains(otherSnapshot.originalText), "exports saved original content, not live file")
try check(!exported.contains("writer-"), "export must not copy live bytes or drafts")
let secondURL = try store.export([original])
try check(secondURL.deletingLastPathComponent() != exportURL.deletingLastPathComponent(), "random export directories avoid overwrites")
try rejects(.unsavedExport, "empty selection") { _ = try store.export([]) }
print("Foundation runtime: PASS (read-only, path/symlink, exact CAS, creation/deletion, invalid UTF8, concurrent store instances, saved snapshot export)")
'''


class FoundationRuntime(unittest.TestCase):
    def test_compiled_store(self):
        compiler = shutil.which("swiftc")
        if not compiler:
            if os.environ.get("V64R_REQUIRE_SWIFT") == "1":
                self.fail("V64R_REQUIRE_SWIFT=1 but swiftc is unavailable; fail closed (no installation).")
            self.skipTest("SKIP: swiftc unavailable; Foundation runtime and Darwin coordinator were NOT tested.")
        with tempfile.TemporaryDirectory(prefix="memory-documents-160651-") as temporary:
            temp = Path(temporary)
            main = temp / "main.swift"
            main.write_text(SWIFT_TEST, encoding="utf-8")
            executable = temp / "memory-store-tests"
            build = subprocess.run([compiler, "-swift-version", "5", str(STORE_PATH), str(main), "-o", str(executable)],
                                   text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=180)
            self.assertEqual(build.returncode, 0, "Swift compilation failed:\n" + build.stdout + build.stderr)
            environment = os.environ.copy()
            environment["TMPDIR"] = str(temp) + "/"
            run = subprocess.run([str(executable), str(temp)], text=True, stdout=subprocess.PIPE,
                                 stderr=subprocess.PIPE, timeout=90, env=environment)
            self.assertEqual(run.returncode, 0, "Foundation runtime failed:\n" + run.stdout + run.stderr)
            self.assertIn("Foundation runtime: PASS", run.stdout)
            print(run.stdout, end="")


if __name__ == "__main__":
    print("SOURCE CONTRACTS are not Swift compilation, SwiftUI execution, or device verification.", flush=True)
    unittest.main(verbosity=2)
