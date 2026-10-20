#!/usr/bin/env python3
"""[T-sidebar-icon-menu] Direct, independent folder/session photo actions.

Source contracts run locally. On macOS the actual added Swift members are
also type-checked against the iOS 15.5 SDK surface with small dependency stubs.
No network, photo library, device, database or real UserDefaults are accessed.
Local iSH explicitly skips native validation; no compile success is implied.
"""
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent.parent
CONTENT = (ROOT / 'src/ios/Views/ContentView.swift').read_text()
STORE = (ROOT / 'src/ios/Agent/Chat/ChatLifecycleSupport.swift').read_text()
CATALOG = json.loads((ROOT / 'src/ios/Localizable.xcstrings').read_text())['strings']


def member(source, marker, indent=''):
    start = source.index(marker)
    end = source.index('\n' + indent + '}', start) + len('\n' + indent + '}')
    return source[start:end]


class DirectMenuContracts(unittest.TestCase):
    def test_shared_menu_has_direct_change_and_conditional_restore(self):
        menu = member(CONTENT, 'private struct SidebarIconMenu: View')
        self.assertIn('actions.send(.changeIcon(target))', menu)
        self.assertIn('if hasCustomIcon {', menu)
        self.assertIn('actions.send(.restoreIcon(target))', menu)
        for label in ('更换图标', '恢复默认图标'):
            self.assertIn(f'Label("{label}"', menu)
        self.assertIn('case .session(let id): return sessions.icon(for: id) != nil', menu)
        self.assertIn('case .folder(let id): return folders.icon(for: id) != nil', menu)

    def test_session_menu_available_outside_group_condition(self):
        menu = member(CONTENT, 'private struct SessionContextMenu: View')
        self.assertLess(menu.index('SidebarIconMenu(target: .session(key.sid)'), menu.index('if key.filed {'))
        self.assertEqual(CONTENT.count('SessionContextMenu('), 2)
        self.assertEqual(CONTENT.count('hasCustomIcon: sidebarIcons.icon('), 2)
        self.assertIn('let hasCustomIcon: Bool', member(CONTENT, 'private struct MenuKey: Equatable'))

    def test_empty_or_collapsed_folder_does_not_need_a_member(self):
        start = CONTENT.index('private func folderSectionHeader(')
        end = CONTENT.index('private func initialFolderId(', start)
        header = CONTENT[start:end]
        self.assertIn('SidebarIconMenu(target: .folder(fid), actions: menuActions)', header)
        self.assertNotIn('group.ids.first', header)
        self.assertIn('.id("folderHeader-\\(group.folderId ?? "")")', header)

    def test_remote_path_has_the_same_actions_without_forking(self):
        start = CONTENT.index('private var remoteDeviceSessionSections:')
        end = CONTENT.index('private func refreshRemoteDeviceSessions()', start)
        body = CONTENT[start:end]
        self.assertIn('SidebarIconMenu(target: .session(session.id), actions: menuActions)', body)
        self.assertLess(body.index('SidebarIconMenu('), body.index('forkSession('))

    def test_direct_picker_does_not_route_through_an_editor(self):
        body = member(CONTENT, 'private func presentSidebarIconPicker(', '    ')
        self.assertIn('config.filter = .images', body)
        self.assertIn('config.selectionLimit = 1', body)
        self.assertIn('PHPickerViewController(configuration: config)', body)
        self.assertIn('picker.delegate = sidebarPhotoPicker', body)
        self.assertIn('UIKitPickerPresenter.present(picker)', body)
        self.assertIn('SidebarIconImage.encode(image)', body)
        self.assertIn('await target.save(uri, request: request)', body)
        self.assertIn('let request = target.beginRequest()', body)
        self.assertIn('sidebarPhotoPicker.setCompletion(', body)
        for forbidden in ('sessionToEdit', 'FolderSettingsSheet', 'openSession(', 'refreshSessionList(', '.photosPicker'):
            self.assertNotIn(forbidden, body)
        self.assertIn('@StateObject private var sidebarPhotoPicker = SessionIconPhotoPicker()', CONTENT)

    def test_stable_action_channel_handles_both_targets(self):
        body = member(CONTENT, 'private func wireMenuActions()', '    ')
        self.assertIn('case .changeIcon(let target):\n                presentSidebarIconPicker(for: target)', body)
        self.assertIn('case .restoreIcon(let target):\n                target.restoreDefault()', body)

    def test_callback_is_snapshotted_before_loading_or_cancelling(self):
        body = member(CONTENT, 'private final class SessionIconPhotoPicker:')
        snapshot = 'let completion = completions.removeValue(forKey: ObjectIdentifier(picker))'
        self.assertLess(body.index(snapshot), body.index('picker.dismiss('))
        self.assertLess(body.index(snapshot), body.index('guard let provider'))
        self.assertLess(body.index(snapshot), body.index('provider.loadObject('))
        self.assertIn('DispatchQueue.main.async { completion?(image) }', body)
        self.assertNotIn('onPicked', body)

    def test_old_load_cannot_override_new_pick_or_restore_after_actor_hop(self):
        target = member(CONTENT, 'private enum SidebarIconTarget:')
        self.assertIn('private static var requests: [SidebarIconTarget: UUID]', target)
        self.assertIn('func restoreDefault() {\n        _ = beginRequest()', target)
        save = member(target, 'func save(', '    ')
        self.assertEqual(save.count('guard Self.requests[self] == request else { return }'), 3)
        self.assertRegex(save, r'getSession\(id\)[^\n]*\n\s*guard Self.requests\[self\] == request')
        self.assertRegex(save, r'getFolder\(id\)[^\n]*\n\s*guard Self.requests\[self\] == request')
        editor = member(CONTENT, 'struct SessionEditSheet:')
        self.assertIn('SidebarIconTarget.session(session.id).restoreDefault()', editor)
        self.assertIn('await target.save(uri, request: request)', editor)

    def test_typed_target_does_not_create_or_modify_chat_records(self):
        target = member(CONTENT, 'private enum SidebarIconTarget:')
        self.assertIn('case session(String)', target)
        self.assertIn('case folder(String)', target)
        self.assertIn('guard await ChatStore.shared.getSession(id) != nil', target)
        self.assertIn('guard await ChatStore.shared.getFolder(id) != nil', target)
        self.assertIn('SessionIconStore.shared.setIcon(dataURI, for: id)', target)
        self.assertIn('FolderIconStore.shared.setIcon(dataURI, for: id)', target)
        for forbidden in ('createSession', 'createFolder', 'setFolder', 'updateSession', 'renameFolder'):
            self.assertNotIn(forbidden, target)

    def test_chinese_menu_keys_are_translated(self):
        for label in ('更换图标', '恢复默认图标'):
            value = CATALOG[label]['localizations']
            self.assertEqual(value['zh-Hans']['stringUnit']['value'], label)
            self.assertTrue(value['en']['stringUnit']['value'])


class StorageAndRenderingContracts(unittest.TestCase):
    def test_folder_storage_namespace_is_separate_and_not_synced(self):
        folders = member(STORE, 'final class FolderIconStore:')
        sessions = member(STORE, 'final class SessionIconStore:')
        self.assertIn('"folderCustomIcons"', folders)
        self.assertIn('"sessionCustomIcons"', sessions)
        self.assertNotIn('"sessionCustomIcons"', folders)
        self.assertNotIn('"folderCustomIcons"', sessions)
        for forbidden in ('ChatStore', 'SyncedFolder', 'iCloud', 'folder.name'):
            self.assertNotIn(forbidden, folders)
        self.assertIn('init(defaults: UserDefaults = .standard)', folders)

    def test_store_caches_are_invalidated_before_publishing(self):
        for marker, name in [('final class SessionIconStore:', 'sessionId'), ('final class FolderIconStore:', 'folderId')]:
            body = member(STORE, marker)
            self.assertIn('NSCache<NSString, UIImage>()', body)
            setter = member(body, 'func setIcon(', '    ')
            self.assertIn('guard icons[' + name + '] != normalized else { return }', setter)
            self.assertLess(setter.index('imageCache.removeObject('), setter.index('icons.removeValue('))

    def test_folder_photos_cover_all_three_display_surfaces(self):
        expected = [
            'FolderPhotoIcon(folderId: item.folder.id, glyphs: item.glyphs, diameter: 40)',
            'FolderPhotoIcon(folderId: folder.id, glyphs: folderMiniBarGlyphs(folder.id), diameter: 30)',
            'FolderPhotoIcon(folderId: group.folderId ?? "", glyphs: group.glyphs)',
        ]
        for call in expected:
            self.assertIn(call, CONTENT)
        self.assertEqual(CONTENT.count('FolderPhotoIcon('), 3)
        self.assertEqual(CONTENT.count('FolderComposedIcon('), 1)

    def test_avatar_leaves_observe_correct_store_and_fill_the_circle(self):
        session = member(CONTENT, 'private struct SessionPhotoIcon:')
        folder = member(CONTENT, 'private struct FolderPhotoIcon:')
        self.assertIn('@ObservedObject private var icons = SessionIconStore.shared', session)
        self.assertIn('@ObservedObject private var icons = FolderIconStore.shared', folder)
        for body, dimensions in [(session, '44'), (folder, 'diameter')]:
            self.assertIn('.scaledToFill()', body)
            self.assertIn(f'.frame(width: {dimensions}, height: {dimensions})', body)
            self.assertIn('.clipShape(Circle())', body)
        self.assertIn('FolderComposedIcon(glyphs: glyphs, diameter: diameter)', folder)
        self.assertIn('sessionCategoryIcon(for: category)', session)

    def test_equatable_rows_snapshot_icon_revision_not_whole_photo(self):
        row = member(CONTENT, 'private struct SessionRow:')
        self.assertIn('&& lhs.iconSessionId == rhs.iconSessionId', row)
        self.assertIn('&& lhs.iconRevision == rhs.iconRevision', row)
        self.assertIn('let iconRevision: UInt64', row)
        self.assertIn('SessionPhotoIcon(sessionId: iconSessionId, category: session.category)', row)
        self.assertIn('@ObservedObject private var sidebarIcons = SessionIconStore.shared', CONTENT)
        self.assertEqual(CONTENT.count('iconRevision: sidebarIcons.revision('), 2)
        self.assertNotIn('.id(iconRevision)', CONTENT)

    def test_promoted_draft_uses_real_icon_id_without_changing_tag(self):
        self.assertIn('iconSessionId: Self.isNewSessionId(session.id) ? newSessionRealId : session.id', CONTENT)
        self.assertIn('hasCustomIcon: sidebarIcons.icon(for: menuSid) != nil', CONTENT)
        self.assertIn('.tag(session.id)', CONTENT)

    def test_photo_clip_does_not_crop_existing_status_overlays(self):
        row = member(CONTENT, 'private struct SessionRow:')
        self.assertIn('providerIcon\n                .frame(width: 44, height: 44)', row)
        self.assertLess(row.index('.clipShape(Circle())'), row.index('.overlay {'))
        for feature in ('SuspendedRing(', 'SpinningRing(', 'badgeCircle(', 'showsUnreadDot'):
            self.assertIn(feature, row)
        self.assertNotIn('.frame(width: 26, height: 26)', row)

    def test_new_encoder_downsamples_directly_to_44pt_at_3x(self):
        body = member(STORE, 'enum SidebarIconImage {')
        self.assertIn('static let storedPixels: CGFloat = 132', body)
        self.assertIn('format.scale = 1', body)
        self.assertIn('format.opaque = false', body)
        self.assertIn('image.draw(in: rect)', body)
        self.assertIn('SoulIconImage.dataURI(fromPNG: png)', body)
        self.assertNotIn('squareCropped(', body)
        self.assertIn('image.size.width > 0, image.size.height > 0', body)


class NativeRequestOrdering(unittest.TestCase):
    def test_actual_target_rejects_stale_results_and_keeps_namespaces_separate(self):
        swiftc = shutil.which('swiftc')
        if not swiftc:
            if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
                self.fail('swiftc required for request-order fixtures')
            self.skipTest('swiftc unavailable: actual request-order Swift NOT executed')
        with tempfile.TemporaryDirectory(prefix='icon-request-order-') as folder:
            source = Path(folder) / 'IconRequestOrder.swift'
            binary = Path(folder) / 'icon-request-order'
            source.write_text(request_order_harness())
            compiled = subprocess.run([swiftc, '-swift-version', '5', '-parse-as-library',
                                       str(source), '-o', str(binary)], capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('request-order-ok', result.stdout)


def request_order_harness():
    stubs = r'''
import Foundation
@MainActor final class SessionIconStore {
    static let shared = SessionIconStore()
    var icons: [String: String] = [:]
    func setIcon(_ value: String?, for id: String) { icons[id] = value }
}
@MainActor final class FolderIconStore {
    static let shared = FolderIconStore()
    var icons: [String: String] = [:]
    func setIcon(_ value: String?, for id: String) { icons[id] = value }
}
actor ChatStore {
    static let shared = ChatStore()
    private var held = false
    private var gate: CheckedContinuation<Void, Never>?
    func hold() { held = true }
    func pending() -> Bool { gate != nil }
    func release() { held = false; gate?.resume(); gate = nil }
    func getSession(_ id: String) async -> String? {
        if held { await withCheckedContinuation { gate = $0 } }
        return id == "deleted" ? nil : id
    }
    func getFolder(_ id: String) -> String? { id == "deleted" ? nil : id }
}
'''
    runs = r'''
@main struct RequestOrderFixtures {
    @MainActor static func main() async {
        let s = SidebarIconTarget.session("same-id")
        let f = SidebarIconTarget.folder("same-id")
        let old = s.beginRequest()
        let newer = s.beginRequest()
        await s.save("new", request: newer)
        await s.save("stale", request: old)
        precondition(SessionIconStore.shared.icons["same-id"] == "new")
        let staleOnRestore = s.beginRequest()
        s.restoreDefault()
        await s.save("stale-after-reset", request: staleOnRestore)
        precondition(SessionIconStore.shared.icons["same-id"] == nil)
        let sessionTicket = s.beginRequest()
        let folderTicket = f.beginRequest()
        await s.save("session", request: sessionTicket)
        await f.save("folder", request: folderTicket)
        precondition(SessionIconStore.shared.icons["same-id"] == "session")
        precondition(FolderIconStore.shared.icons["same-id"] == "folder")
        f.restoreDefault()
        precondition(FolderIconStore.shared.icons["same-id"] == nil)
        precondition(SessionIconStore.shared.icons["same-id"] == "session")
        let deleted = SidebarIconTarget.folder("deleted")
        await deleted.save("orphan", request: deleted.beginRequest())
        precondition(FolderIconStore.shared.icons["deleted"] == nil)
        // A newer action happens while the old save is suspended on ChatStore.
        await ChatStore.shared.hold()
        let waitingTicket = s.beginRequest()
        let waiting = Task { @MainActor in await s.save("late", request: waitingTicket) }
        while !(await ChatStore.shared.pending()) { await Task.yield() }
        s.restoreDefault()
        await ChatStore.shared.release()
        await waiting.value
        precondition(SessionIconStore.shared.icons["same-id"] == nil)
        print("request-order-ok")
    }
}
'''
    return stubs + member(CONTENT, 'private enum SidebarIconTarget:') + runs


class NativeTypecheck(unittest.TestCase):
    def test_actual_added_swift_members_typecheck_for_ios15(self):
        if sys.platform != 'darwin' or not shutil.which('xcrun'):
            if os.environ.get('V64R_REQUIRE_SWIFT') == '1':
                self.fail('Xcode/iOS SDK required for native sidebar icon validation')
            self.skipTest('No Xcode/iOS SDK: actual added Swift code NOT typechecked')
        sdk = subprocess.check_output(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-path'], text=True).strip()
        with tempfile.TemporaryDirectory(prefix='sidebar-icons-') as folder:
            path = Path(folder) / 'SidebarIconTypecheck.swift'
            path.write_text(swift_harness())
            result = subprocess.run(['xcrun', '--sdk', 'iphonesimulator', 'swiftc', '-swift-version', '5',
                                     '-typecheck', '-target', 'arm64-apple-ios15.5-simulator',
                                     '-sdk', sdk, str(path)], capture_output=True, text=True, timeout=180)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


def swift_harness():
    soul = (ROOT / 'src/ios/Agent/Session/SoulStore.swift').read_text()
    stubs = '''
import Foundation
import Combine
import SwiftUI
import UIKit
import PhotosUI

enum SoulIconImage {
    enum RejectionReason: Error { case unreadable }
    static func decode(_ value: String) -> UIImage? { nil }
    static func dataURI(fromPNG data: Data) -> String { "data:image/png;base64," + data.base64EncodedString() }
}
actor ChatStore {
    static let shared = ChatStore()
    func getSession(_ id: String) -> String? { id }
    func getFolder(_ id: String) -> String? { id }
}
struct FolderGlyph { let color: Color }
struct FolderComposedIcon: View {
    let glyphs: [FolderGlyph]
    var diameter: CGFloat = 44
    var body: some View { Color.clear.frame(width: diameter, height: diameter) }
}
func sessionCategoryIcon(for category: String?) -> (systemName: String, color: Color) {
    ("terminal.fill", .orange)
}
private enum SessionMenuAction {
    case changeIcon(SidebarIconTarget)
    case restoreIcon(SidebarIconTarget)
}
@MainActor private final class SessionMenuActionChannel {
    var handler: ((SessionMenuAction) -> Void)?
    func send(_ action: SessionMenuAction) { handler?(action) }
}
'''
    blocks = [member(STORE, 'final class SessionIconStore:'),
              member(STORE, 'final class FolderIconStore:'),
              member(STORE, 'enum SidebarIconImage {'),
              member(CONTENT, 'private enum SidebarIconTarget:'),
              member(CONTENT, 'private struct SidebarIconMenu:'),
              member(CONTENT, 'private struct SessionPhotoIcon:'),
              member(CONTENT, 'private struct FolderPhotoIcon:'),
              member(CONTENT, 'private final class SessionIconPhotoPicker:')]
    presenter = (ROOT / 'src/ios/iOS15Compat.swift').read_text()
    blocks.append(member(presenter, 'enum UIKitPickerPresenter {'))
    # Exercise the actual SwiftUI owner/@StateObject + UIKit picker wiring too.
    blocks.append('''
@MainActor private struct PickerOwner: View {
    @StateObject private var sidebarPhotoPicker = SessionIconPhotoPicker()
    var body: some View { EmptyView() }
''' + member(CONTENT, 'private func presentSidebarIconPicker(', '    ') + '\n}')
    return stubs + '\n\n'.join(blocks)


if __name__ == '__main__':
    unittest.main(verbosity=2)
