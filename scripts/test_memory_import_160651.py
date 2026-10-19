#!/usr/bin/env python3
"""Source-contract tests for [T-memory-import].

Covers the three required sources (Files picker, clipboard, share-sheet) and
the two decisions the user demanded: the destination is ALWAYS chosen (never
written straight in), and a same-name file always prompts
overwrite / rename / skip.

Static checks only; the Files picker and a real share sheet need a device.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
MEMVIEW = (ROOT / 'src/ios/Views/Settings/MemoryManagementView.swift').read_text()
STORE = (ROOT / 'src/ios/Agent/Session/MemoryDocumentStore.swift').read_text()
INBOX = (ROOT / 'src/ios/Shared/MemoryImportInbox.swift').read_text()
APP = (ROOT / 'src/ios/MinisApp.swift').read_text()
PLIST = (ROOT / 'src/ios/Info.plist').read_text()
PBX = (ROOT / 'src/ios/Minis.xcodeproj/project.pbxproj').read_text()


class ImportSources(unittest.TestCase):
    def test_three_sources_present(self):
        self.assertIn('Button {\n                        showFilePicker = true', MEMVIEW)
        self.assertIn('从「文件」选择', MEMVIEW)
        self.assertIn('pasteFromClipboard()', MEMVIEW)
        self.assertIn('从剪贴板导入', MEMVIEW)
        self.assertIn('MemoryDocumentPicker', MEMVIEW)

    def test_share_sheet_inbox(self):
        self.assertIn('enum MemoryImportInbox', INBOX)
        self.assertIn('ext == "md" || ext == "markdown" || ext == "txt"', INBOX)
        # Routed BEFORE the generic attachment pipeline.
        inbox = APP.index('MemoryImportInbox.handle(url)')
        attach = APP.index('ExternalFileImporter.canIngest(url)')
        self.assertLess(inbox, attach)

    def test_markdown_declared_in_info_plist(self):
        self.assertIn('net.daringfireball.markdown', PLIST)
        self.assertIn('Markdown Document', PLIST)

    def test_inbox_registered_in_project(self):
        # BuildFile + FileReference + group child + Sources phase.
        self.assertIn('MemoryImportInbox.swift in Sources */ = {isa = PBXBuildFile', PBX)
        self.assertIn('MemoryImportInbox.swift */ = {isa = PBXFileReference', PBX)
        self.assertIn('MemoryImportInbox.swift in Sources */,', PBX)
        self.assertIn('MemoryImportInbox.swift */,', PBX)


class DestinationChoice(unittest.TestCase):
    def test_target_always_chosen(self):
        self.assertIn('enum MemoryImportTarget', MEMVIEW)
        for case in ('case globalMemory', 'case dailyMemory', 'case customName'):
            self.assertIn(case, MEMVIEW)
        self.assertIn('Text("导入到")', MEMVIEW)

    def test_nothing_written_before_confirm(self):
        # The store call lives only in the confirm path.
        self.assertIn('private func beginImport()', MEMVIEW)
        self.assertIn('store.importDocument(', MEMVIEW)
        start = MEMVIEW.index('private func beginImport()')
        self.assertNotIn('importDocument', MEMVIEW[MEMVIEW.index('private func pasteFromClipboard'):start])


class ConflictPolicy(unittest.TestCase):
    def test_all_three_options_offered(self):
        self.assertIn('覆盖原文件', MEMVIEW)
        self.assertIn('重命名', MEMVIEW)
        self.assertIn('跳过这个文件', MEMVIEW)

    def test_conflict_detected_before_write(self):
        self.assertIn('store.documentExists(rootID: MemoryLibraryRoot.sharedMemory.id, fileName: name)', MEMVIEW)

    def test_store_import_refuses_silent_overwrite(self):
        self.assertIn('if !overwrite, fm.fileExists(atPath: url.path) { throw Failure.conflict }', STORE)
        self.assertIn('func importDocument(rootID: String, fileName: String, text: String, overwrite: Bool)', STORE)

    def test_rename_picks_free_name(self):
        self.assertIn('while store.documentExists(rootID: MemoryLibraryRoot.sharedMemory.id, fileName: candidate)', MEMVIEW)


if __name__ == '__main__':
    unittest.main(verbosity=2)
