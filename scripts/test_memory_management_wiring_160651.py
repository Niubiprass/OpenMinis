#!/usr/bin/env python3
"""Source/build contracts for the integrated memory library and shared editor.

Read-only checks, not Swift compilation or a device verdict. The separate
SwiftUI harness must typecheck these real files against Apple frameworks.
"""
from pathlib import Path
import re
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"
SESSION = (IOS / "Views/Chat/SessionMemoryView.swift").read_text(encoding="utf-8")
MANAGEMENT = (IOS / "Views/Settings/MemoryManagementView.swift").read_text(encoding="utf-8")
LIBRARY = (IOS / "Views/Chat/ScopedMemoryLibraryView.swift").read_text(encoding="utf-8")


def project_object(project, identifier):
    match = re.search(r"^\t\t" + re.escape(identifier) + r" /\*.*?\*/ = \{(.*?)^\t\t\};",
                      project, re.M | re.S)
    if not match:
        raise AssertionError("Missing project object: " + identifier)
    return match.group(1)


class MemoryManagementWiring(unittest.TestCase):
    def test_real_files_are_in_main_app_sources(self):
        project = (IOS / "Minis.xcodeproj/project.pbxproj").read_text(encoding="utf-8")
        targets = re.findall(r"^\t\t(\w+) /\* Minis \*/ = \{\s*isa = PBXNativeTarget;", project, re.M)
        self.assertEqual(len(targets), 1)
        target = project_object(project, targets[0])
        self.assertIn("isa = PBXNativeTarget;", target)
        phases = re.findall(r"(\w+) /\* Sources \*/", target)
        self.assertEqual(len(phases), 1)
        sources = project_object(project, phases[0])
        self.assertIn("isa = PBXSourcesBuildPhase;", sources)
        for relative in ("Agent/Session/MemoryDocumentStore.swift",
                         "Views/Chat/ScopedMemoryLibraryView.swift",
                         "Views/Chat/SessionMemoryView.swift",
                         "Views/Settings/MemoryManagementView.swift",
                         "Views/Chat/MinisShareSheet.swift", "iOS15Compat.swift"):
            with self.subTest(source=relative):
                path = IOS / relative
                self.assertTrue(path.is_file())
                name = re.escape(path.name)
                refs = re.findall(r"^\s*(\w+) /\* " + name + r" \*/ = \{isa = PBXFileReference;[^\n]*path = \"?" + name + r'\"?;', project, re.M)
                self.assertEqual(len(refs), 1, relative + ": file reference")
                builds = re.findall(r"^\s*(\w+) /\* " + name + r" in Sources \*/ = \{isa = PBXBuildFile; fileRef = " + refs[0] + r"\b", project, re.M)
                self.assertTrue(builds, relative + ": build reference")
                self.assertTrue(any(re.search(r"\b" + build + r" /\* " + name + r" in Sources \*/", sources)
                                    for build in builds), relative + ": main app Sources membership")

    def test_explicit_and_runtime_session_roots_do_not_fall_back(self):
        entry = SESSION.split("private var sessionContents", 1)[0]
        for token in ("roots: [MemoryLibraryRoot]? = nil", "self.libraryRoots = roots",
                      "if let roots = libraryRoots ?? runtimeRoots", "roots: roots, onSaveDirty: onSaveDirty",
                      "guard libraryRoots == nil else { return }", "try await vm.refreshFolderRuntimeContext()",
                      "context.usesFolderMemory", "directory: context.memoryDirectory, isReadOnly: false, isGlobal: false",
                      "if context.configuration.readsGlobalMemory", "isReadOnly: true, isGlobal: true",
                      "runtimeRoots = roots", "runtimeError = error.localizedDescription", "runtimeReady = true",
                      "else if !runtimeReady", "else if let runtimeError", "sessionContents"):
            self.assertIn(token, entry)
        self.assertNotIn(".sharedMemory", entry)
        self.assertNotIn("store.save(", entry)
        self.assertLess(entry.index("else if let runtimeError"), entry.rindex("sessionContents"))
        self.assertNotIn("minisMemoryPersistentDir", LIBRARY)
        self.assertNotIn("activeSession", LIBRARY)

    def test_global_settings_use_one_real_shared_library(self):
        settings, editor = MANAGEMENT.split("struct MemoryFileEditView: View", 1)
        for token in ('ScopedMemoryLibraryView(title: AppLocalized("Memory"), roots: memoryRoots)',
                      '@AppStorage("memory.global.enabled")', 'Toggle(AppLocalized("settings_memory_global_enabled")',
                      'MemoryLibraryRoot(id: "shared-memory"', "directory: AIChatViewModel.minisMemoryPersistentDir",
                      "isReadOnly: false, isGlobal: true", "ForceSyncHelper.markMemoryDirty()",
                      'recordTypes: ["MemoryGlobalV2", "MemoryDailyV2"]'):
            self.assertIn(token, settings)
        for token in ("TextEditor(", "contentsOfDirectory(", ".onDelete(", "removeItem(", ".write("):
            self.assertNotIn(token, settings)
        self.assertIn("try store.save(snapshot, text: content)", editor)
        self.assertNotIn(".write(", editor)

    def test_content_library_and_compat_entry_share_one_editor(self):
        content = SESSION.split("struct MemoryContentView: View", 1)[1].split("// MARK: - Memory Write Detail", 1)[0]
        self.assertIn("MemoryContentView(root: root, fileName: document.fileName, onSaveDirty: onSaveDirty)", LIBRARY)
        compat = LIBRARY.split("struct ScopedMemoryDocumentView: View", 1)[1].split("func markGlobalMemoryDirty", 1)[0]
        self.assertIn("MemoryContentView(root: root, fileName: fileName, onSaveDirty: onSaveDirty)", compat)
        self.assertNotIn("TextEditor(", LIBRARY)
        self.assertNotIn("store.save(", content)
        self.assertIn("MemoryFileEditView(root: root, snapshot: base, onSaveDirty: onSaveDirty)", content)
        self.assertEqual(MANAGEMENT.count("TextEditor(text: $content)"), 1)
        self.assertIn("MemoryContentView(root: .sharedMemory, fileName: fileURL.lastPathComponent", SESSION)
        for source in (LIBRARY, content):
            self.assertIn(".sheet(item: $share) { MinisShareSheet(url: $0.url) }", source)
            self.assertNotIn("UIActivityViewController(", source)
        self.assertEqual((SESSION + MANAGEMENT + LIBRARY).count("static let memoryFilesDidChange"), 1)

    def test_existing_share_wrapper_remains_official_source(self):
        relative = "src/ios/Views/Chat/MinisShareSheet.swift"
        upstream = subprocess.check_output(
            ["git", "show", "b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c:" + relative], cwd=ROOT)
        self.assertEqual((ROOT / relative).read_bytes(), upstream)


if __name__ == '__main__':
    print('SOURCE/BUILD WIRING ONLY: real integrated memory pages; no Swift or device verdict.', flush=True)
    unittest.main(verbosity=2)
