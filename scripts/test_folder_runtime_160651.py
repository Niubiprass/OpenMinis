#!/usr/bin/env python3
"""Folder policy wiring + optional real Foundation execution; not a device verdict."""
from pathlib import Path
import os, shutil, subprocess, tempfile, unittest
ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / 'src/ios'
def read(p): return (IOS / p).read_text()
MEM = read('Agent/Chat/AIChatViewModel+MemoryTools.swift')
VM = read('Agent/Chat/AIChatViewModel.swift')
FILE = read('Agent/Chat/AIChatViewModel+FileTools.swift')
ROUTER = read('Agent/ISH/MinisFsRouter.swift')
COORD = read('Agent/ISH/ISHExecutionCoordinator.swift')
STORE = read('Agent/Chat/ChatStore.swift')
SKILLS = read('Agent/Session/SkillStore.swift')
class Wiring(unittest.TestCase):
    def test_every_prompt_site_uses_authorized_roots(self):
        self.assertEqual(VM.count('for fragment in scopedMemoryPromptFragments()'), 2)
        self.assertNotIn('Self.loadGlobalMemoryFragment()', VM)
        self.assertIn('try await refreshFolderRuntimeContext()', VM)
        self.assertEqual(VM.count('memoryStatusFragment + folderMemoryStatusFragment'), 2)
        self.assertIn('context.configuration.readsGlobalMemory', MEM)
        self.assertIn('label: "global-read-only/"', MEM)
    def test_write_and_read_share_folder_context(self):
        self.assertIn('let persistDir = effectiveMemoryDirectory', MEM)
        self.assertIn('let roots = folderRuntimeContext?.readDirectories', MEM)
        self.assertIn('if folderRuntimeContext?.usesFolderMemory != true', MEM)
        self.assertIn('options: .atomic', MEM)
        dispatch = read('Agent/Chat/AIChatViewModel+ConcurrentTools.swift')
        for name in ('memory_write', 'memory_get'):
            self.assertIn(f'case "{name}":\n            try await refreshFolderRuntimeContext()', dispatch)
    def test_paths_do_not_use_frontmost_scope(self):
        self.assertIn('hostURL(for: linuxPath, sessionId: fsSessionId)', FILE)
        self.assertIn('hostURL(for: path, sessionId: fsSessionId)', FILE)
        self.assertIn('case "memory": base = effectiveMemoryDirectory', FILE)
        self.assertIn('guard target.path == root.path || target.path.hasPrefix(root.path + "/")', FILE)
        self.assertIn('setMemoryDirectory(memoryDirectory, for: sessionId)', COORD)
        self.assertIn('let sid = sid(for: fsContext)', ROUTER)
        self.assertIn('let directory = memoryDirectory(for: sid)', ROUTER)
    def test_memory_write_fast_path_never_uses_last_mounted_session(self):
        write = FILE.split('func executeFileWrite(', 1)[1].split('func executeFileEdit(', 1)[0]
        self.assertNotIn('hostURL(for: path)', write)
        self.assertIn('if path.hasPrefix("/var/minis/mounts/") {', write)
        self.assertIn('hostURL = await resolvePathForDirectRead(path)', write)
        resolver = FILE.split('func resolvePathForDirectRead(', 1)[1].split('func ', 1)[0]
        self.assertLess(resolver.index('refreshFolderRuntimeContext()'), resolver.index('return target'))
        self.assertIn('catch { return nil }', resolver)
        host = COORD.split('func hostURL(for ', 1)[1].split('/// Kill all', 1)[0]
        memory = host.split('if linuxPath == AIChatViewModel.minisMemoryLinuxDir', 1)[1].split('if let sid = sessionId ?? mountedSessionId', 1)[0]
        self.assertIn('guard let sid = sessionId else { return nil }', memory)
        self.assertIn('return MinisFsRouter.shared.hostURL(forGuest: linuxPath, sid: sid)', memory)
        self.assertNotIn('mountedPaths', memory)
    def test_interactive_terminal_captures_the_same_scope_token(self):
        terminal = read('Views/Rootfs/ISHTerminalView.swift')
        self.assertIn('resolveFolderRuntimeContext(for: sid)', terminal)
        self.assertIn('MinisFsRouter.shared.setMemoryDirectory(directory, for: sid)', terminal)
        self.assertIn('ISHKernel.shared.interactiveFSContext = sessionId.map', terminal)
        kernel = read('iSH/ISHKernel.m')
        self.assertIn('uint64_t fsContext = self.interactiveFSContext;', kernel)
        self.assertIn('current->group->fs_context = fsContext;', kernel)
        self.assertIn('NSDictionary<NSString *, NSString *> *environmentCopy = [self.customEnvironment copy];', kernel)
        self.assertIn('NSDictionary<NSString *, NSString *> *customEnv = environmentCopy;', kernel)
    def test_cleanup_precedes_throwing_folder_resolution(self):
        block = COORD.split('func execute(',1)[1].split('func mountForSession',1)[0]
        self.assertLess(block.index('defer {'), block.index('try Task.checkCancellation()'))
        self.assertLess(block.index('defer {'), block.index('resolveFolderRuntimeContext'))
    def test_session_choice_precedes_group_default(self):
        getter = SKILLS.split('func isEnabledForSession(',1)[1].split('/// A counter',1)[0]
        self.assertLess(getter.index('dbSessionOverride'),getter.index('folderDefaultsBySession'))
        self.assertLess(getter.index('folderDefaultsBySession'),getter.index('skills.first'))
        setter = SKILLS.split('func setSessionOverride(',1)[1].split('// MARK: - Usage',1)[0]
        self.assertIn('func clearSessionOverride(',setter)
        self.assertIn('dbSetSessionOverride',setter)
        view=read('Views/Chat/SessionSkillsView.swift')
        self.assertIn('SessionSoulPromptSheet',view)
        self.assertIn('clearSessionOverride',view)
        self.assertIn('session.soul.body.',MEM)
    def test_new_group_is_filed_before_first_turn(self):
        persistence=read('Agent/Chat/AIChatViewModel+Persistence.swift')
        create=persistence.split('func ensureSessionReturningId()',1)[1].split('func ensureSessionBindingFromDefaults',1)[0]
        self.assertLess(create.index('setFolderIfUnfiled'),create.index('mountMinis(for:'))
        self.assertIn('initialFolderId',create)
        self.assertIn('for _ in 0..<16', STORE)
    def test_no_migration_or_global_writes_by_group(self):
        self.assertNotIn('moveItem(',MEM)
        self.assertNotIn('removeItem(',MEM)
        self.assertNotIn('copyItem(',MEM)
        self.assertIn('if folderRuntimeContext?.usesFolderMemory != true',MEM)
        sheet=read('Views/Chat/SessionMemoryView.swift')
        self.assertIn('isReadOnly: true, isGlobal: true',sheet)
        self.assertIn('else if let runtimeError',sheet)
class RealFoundation(unittest.TestCase):
    def test_folder_policy_and_legacy_decoding(self):
        compiler=shutil.which('swiftc')
        if not compiler:
            if os.getenv('V64R_REQUIRE_SWIFT')=='1': self.fail('swiftc required, unavailable')
            self.skipTest('No Swift compiler; actual policy execution NOT tested')
        config=STORE.split('enum ChatFolderMemoryPolicy:',1)[1].split('enum ChatFolderConfigurationError',1)[0]
        config='enum ChatFolderMemoryPolicy:'+config
        context=MEM.split('struct FolderRuntimeContext {',1)[1].split('// MARK: - Memory Tools',1)[0]
        context='struct FolderRuntimeContext {'+context
        program='import Foundation\n'+config+'''\nenum AIChatViewModel {
 static var minisMemoryPersistentDir: URL { URL(fileURLWithPath: "/global") }
 static func minisFolderMemoryPersistentDir(for id: String) -> URL { URL(fileURLWithPath: "/folders/"+id) }
}\n'''+context+'''
func require(_ test: @autoclosure () -> Bool) { precondition(test()) }
let old = try ChatFolderConfiguration.decodeStoredJSON(nil)
require(old.memoryPolicy == .global && !old.readsGlobalMemory)
let empty = try JSONDecoder().decode(ChatFolderConfiguration.self, from: Data("{}".utf8))
require(empty == old)
var privateConfig = old
privateConfig.memoryPolicy = .folder
let a = FolderRuntimeContext(folderId: "A", configuration: privateConfig)
let b = FolderRuntimeContext(folderId: "B", configuration: privateConfig)
require(a.memoryDirectory != b.memoryDirectory)
require(a.readDirectories.count == 1 && a.memoryDirectory.path == "/folders/A")
privateConfig.readsGlobalMemory = true
let reader = FolderRuntimeContext(folderId: "A", configuration: privateConfig)
require(reader.memoryDirectory == a.memoryDirectory && reader.readDirectories.count == 2)
require(reader.readDirectories[1].label == "global-read-only/")
require(reader.readDirectories[1].directory.path == "/global")
let legacy = FolderRuntimeContext(folderId: nil, configuration: privateConfig)
require(!legacy.usesFolderMemory && legacy.memoryDirectory.path == "/global")
do { _ = try ChatFolderConfiguration.decodeStoredJSON("{bad"); preconditionFailure("bad JSON silently allowed") } catch {}
let encoded = try JSONEncoder().encode(privateConfig)
require(try JSONDecoder().decode(ChatFolderConfiguration.self, from: encoded) == privateConfig)
print("Real Foundation folder policy: PASS")
'''
        # throwing expression must be evaluated before passing a nonthrowing autoclosure
        program=program.replace('require(try JSONDecoder().decode(ChatFolderConfiguration.self, from: encoded) == privateConfig)','let decoded = try JSONDecoder().decode(ChatFolderConfiguration.self, from: encoded)\nrequire(decoded == privateConfig)')
        with tempfile.TemporaryDirectory() as directory:
            main=Path(directory)/'main.swift'; main.write_text(program)
            binary=Path(directory)/'policy'
            built=subprocess.run([compiler,'-swift-version','5',str(main),'-o',str(binary)],capture_output=True,text=True,timeout=120)
            self.assertEqual(built.returncode,0,built.stdout+built.stderr)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            self.assertIn('Real Foundation folder policy: PASS',run.stdout)
if __name__=='__main__':
    print('Source wiring + optional real Swift policy; not a whole-app or rootfs sandbox test.')
    unittest.main(verbosity=2)
