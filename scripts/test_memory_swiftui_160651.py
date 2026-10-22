#!/usr/bin/env python3
"""Typecheck the actual memory store/UI against real SwiftUI/UIKit for iOS 15.5.

Only application services and a minimal iOS15 NavigationStack shim are stubbed.
The memory source files and Apple SwiftUI/UIKit frameworks are not replaced.
V64R_REQUIRE_SWIFT=1 fails closed without Xcode. No installs or user file writes.
"""
from pathlib import Path
import os
import platform
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / 'src/ios'
# Compile whole files, including MemoryContentView and MemoryFileEditView;
# never extract declarations, rewrite production sources, or replace memory UI.
SOURCES = (
    'Agent/Session/MemoryDocumentStore.swift',
    'Views/Chat/ScopedMemoryLibraryView.swift',
    'Views/Chat/SessionMemoryView.swift',
    'Views/Settings/MemoryManagementView.swift',
    'Views/Chat/MinisShareSheet.swift',
)
STUBS = r'''
import SwiftUI
import Foundation

// Application services only. No memory store/editor/library/share-view doubles.
struct ChatFolder {
    let id: String
    let name: String
}
enum HarnessMemoryPolicy { case global, folder }
struct ChatFolderConfiguration {
    var memoryPolicy: HarnessMemoryPolicy = .global
}
actor ChatStore {
    static let shared = ChatStore()
    func markDirty(recordType: String, recordId: String) {}
    func listFolders() -> [ChatFolder] { [] }
    func getFolderConfiguration(_ id: String) throws -> ChatFolderConfiguration { ChatFolderConfiguration() }
}
@MainActor enum SoulStore { static func refreshCache() {} }
func AppLocalized(_ key: String) -> String { key }
enum ForceSyncHelper {
    static func markMemoryDirty() async -> Int { 0 }
    static func bidirectionalSync(recordTypes: [String]) async {}
}
enum MemoryWriteRevoker {
    static func revoke(writtenContent: String) -> String { "Harness only" }
}
struct HarnessFolderConfiguration { var readsGlobalMemory = false }
struct HarnessFolderContext {
    var folderId: String?
    var memoryDirectory: URL
    var usesFolderMemory = false
    var configuration = HarnessFolderConfiguration()
}
struct HarnessMessage {
    var blocks: [HarnessBlock] = []
}
struct HarnessBlock {
    enum Kind { case memoryTool(String), text }
    var kind: Kind = .text
    var toolSummary: String?
    var toolInputArgs: String?
    var content = ""
}
final class AIChatViewModel: ObservableObject {
    // These URLs are never read/written: the harness typechecks, it does not run UI.
    static let minisMemoryPersistentDir = URL(fileURLWithPath: "/memory-compile-harness")
    static func minisFolderMemoryPersistentDir(for folderId: String) -> URL {
        minisMemoryPersistentDir.appendingPathComponent(folderId, isDirectory: true)
    }
    @Published var messages: [HarnessMessage] = []
    var folderRuntimeContext: HarnessFolderContext?
    func refreshFolderRuntimeContext() async throws {}
}

// Minimal no-path iOS15Compat.NavigationStack surface used by these pages.
// Real SwiftUI still builds/typechecks every child; this is not an AnyView/Text substitute.
struct NavigationStack<Content: View>: View {
    private let content: Content
    init(@ViewBuilder root: () -> Content) { content = root() }
    var body: some View {
        NavigationView { content }.navigationViewStyle(StackNavigationViewStyle())
    }
}

struct AgentPersona: Identifiable, Equatable {
    let id: String
    var name: String
    var icon: String
    var style: String
}
final class PersonaStore: ObservableObject {
    static let shared = PersonaStore()
    @Published var personas: [AgentPersona] = []
    var blankByDefault = true
    func persona(id: String?) -> AgentPersona? { nil }
    func memoryEntryCount(for personaId: String) -> Int { 0 }
    @discardableResult
    func moveMemory(fromPersonaId sourceId: String, toPersonaId targetId: String) -> Bool { false }
    @discardableResult
    func moveMemoryFile(named fileName: String, toPersonaId targetId: String?) -> Bool { false }
}
struct SharedMemoryRecord: Identifiable { let id: String }
final class SharedMemoryStore: ObservableObject {
    static let shared = SharedMemoryStore()
    @Published var records: [SharedMemoryRecord] = []
}
struct SharedMemoryListView: View { var body: some View { EmptyView() } }
struct PersonaShareSheet: View {
    let source: AgentPersona
    let title: String
    let content: String
    var body: some View { EmptyView() }
}
func AppLocalizedFormat(_ format: String, _ args: CVarArg...) -> String { format }
enum MemoryMaintenance {
    struct Result { let warning: String? }
    static func runIfNeeded() -> Result { Result(warning: nil) }
}
'''


class HarnessContracts(unittest.TestCase):
    def test_all_real_sources_exist_and_memory_types_are_not_stubbed(self):
        self.assertEqual(set(SOURCES), {
            'Agent/Session/MemoryDocumentStore.swift',
            'Views/Chat/ScopedMemoryLibraryView.swift',
            'Views/Chat/SessionMemoryView.swift',
            'Views/Settings/MemoryManagementView.swift',
            'Views/Chat/MinisShareSheet.swift',
        })
        for relative in SOURCES:
            self.assertTrue((IOS / relative).is_file(), relative)
        for declaration in ('struct MemoryManagementView', 'struct SessionMemoryView',
                            'struct ScopedMemoryLibraryView', 'struct ScopedMemoryDocumentView',
                            'struct MemoryContentView', 'struct MemoryFileEditView',
                            'struct MinisShareSheet', 'class MemoryDocumentStore',
                            'struct MemoryLibraryRoot', 'static let memoryFilesDidChange'):
            self.assertNotIn(declaration, STUBS)


class RealSwiftUICompile(unittest.TestCase):
    def unavailable(self, reason):
        if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
            self.fail('V64R_REQUIRE_SWIFT=1: real SwiftUI/UIKit iOS15.5 compilation required; ' + reason)
        self.skipTest(reason + '; actual memory UI Swift compilation NOT run')

    def test_memory_views_typecheck_for_ios15_5(self):
        xcrun = shutil.which('xcrun')
        if platform.system() != 'Darwin' or not xcrun:
            self.unavailable('Xcode/iPhoneOS SDK is unavailable')
        sdk_probe = subprocess.run([xcrun, '--sdk', 'iphoneos', '--show-sdk-path'],
                                   capture_output=True, text=True, timeout=30)
        sdk = sdk_probe.stdout.strip()
        if sdk_probe.returncode != 0 or not sdk or not Path(sdk).is_dir():
            self.unavailable('No usable iPhoneOS SDK: ' + sdk_probe.stderr.strip())
        compiler_probe = subprocess.run([xcrun, '--sdk', 'iphoneos', '--find', 'swiftc'],
                                        capture_output=True, text=True, timeout=30)
        if compiler_probe.returncode != 0 or not compiler_probe.stdout.strip():
            self.unavailable('Xcode swiftc is unavailable: ' + compiler_probe.stderr.strip())
        with tempfile.TemporaryDirectory(prefix='memory-swiftui-ios15-') as temporary:
            stubs = Path(temporary) / 'ApplicationStubs.swift'
            stubs.write_text(STUBS, encoding='utf-8')
            result = subprocess.run([
                xcrun, '--sdk', 'iphoneos', 'swiftc', '-swift-version', '5', '-typecheck',
                '-sdk', sdk, '-target', 'arm64-apple-ios15.5',
                '-module-cache-path', str(Path(temporary) / 'ModuleCache'),
                str(stubs), *(str(IOS / relative) for relative in SOURCES),
            ], text=True, capture_output=True, timeout=240)
            # Missing tools may skip locally; a real typecheck error NEVER skips.
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print('Actual SessionMemoryView/MemoryManagementView/ScopedMemoryLibraryView + ' +
                  'content/editor + store + MinisShareSheet: iOS15.5 TYPECHECK PASS')
            print('Application services/NavigationStack shim only are stubbed; not a full-App or device test.')


if __name__ == '__main__':
    print('Optional real Apple-framework typecheck; not a device or full-App test.', flush=True)
    unittest.main(verbosity=2)
