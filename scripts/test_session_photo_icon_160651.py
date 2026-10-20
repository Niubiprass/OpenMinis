#!/usr/bin/env python3
"""Source-contract tests for [T-session-photo-icon].

「这里可以实现从照片里面选择图片吗？」 — the 编辑会话 sheet's category grid only
offered fixed glyphs. A session may now use a photo instead.

Storage contract: a 96 px square PNG data URI in UserDefaults, keyed by session
id. NOT on the session record (it would need a schema migration for a cosmetic
field) and NOT synced (a peer device should not inherit a local photo).
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
CONTENT = (ROOT / 'src/ios/Views/ContentView.swift').read_text()
STORE = (ROOT / 'src/ios/Agent/Chat/ChatLifecycleSupport.swift').read_text()


class Store(unittest.TestCase):

    def test_store_keeps_icons_by_session_id(self):
        self.assertIn('final class SessionIconStore: ObservableObject', STORE)
        self.assertIn('private static let defaultsKey = "sessionCustomIcons"', STORE)

    def test_set_and_clear(self):
        i = STORE.index('func setIcon(_ dataURI: String?, for sessionId: String)')
        body = STORE[i:i + 500]
        self.assertIn('icons[sessionId] = dataURI', body)
        self.assertIn('icons.removeValue(forKey: sessionId)', body)

    def test_deleted_sessions_are_pruned(self):
        self.assertIn('func prune(keeping liveIds: Set<String>)', STORE)


class Editing(unittest.TestCase):

    def test_edit_sheet_offers_a_photo(self):
        self.assertIn('AppLocalized("自定义图标")', CONTENT)
        self.assertIn('AppLocalized("从照片选择")', CONTENT)

    def test_picker_is_ios15_safe_and_retained(self):
        self.assertIn('PHPickerViewController(configuration: config)', CONTENT)
        self.assertIn('@StateObject private var photoPicker = SessionIconPhotoPicker()', CONTENT)
        self.assertIn('final class SessionIconPhotoPicker: NSObject, ObservableObject, PHPickerViewControllerDelegate', CONTENT)

    def test_image_uses_the_shared_encoder(self):
        self.assertIn('SidebarIconImage.encode(image)', CONTENT)
        self.assertIn('SoulIconImage.dataURI(fromPNG: png)', STORE)


class RowRendering(unittest.TestCase):

    def test_rows_prefer_the_photo(self):
        # Both row types delegate to the SAME observed, full-circle leaf.
        self.assertEqual(CONTENT.count('SessionPhotoIcon(sessionId: iconSessionId, category: session.category)'), 2)
        i = CONTENT.index('private struct SessionPhotoIcon: View')
        body = CONTENT[i:CONTENT.index('private struct FolderPhotoIcon: View', i)]
        self.assertIn('@ObservedObject private var icons = SessionIconStore.shared', body)
        self.assertLess(body.index('icons.image(for: sessionId)'), body.index('sessionCategoryIcon(for: category)'))

    def test_photo_is_clipped_to_a_circle(self):
        i = CONTENT.index('private struct SessionPhotoIcon: View')
        body = CONTENT[i:CONTENT.index('private struct FolderPhotoIcon: View', i)]
        self.assertIn('.frame(width: 44, height: 44)', body)
        self.assertIn('.clipShape(Circle())', body)
        self.assertNotIn('.frame(width: 26, height: 26)', body)


if __name__ == '__main__':
    unittest.main(verbosity=2)
