#!/usr/bin/env python3
"""Source-contract tests for the two Soul-settings bugs reported 2026-10-20.

1) 「语言选了中文，又变回原来的东西了，他不能保存，他只能自动」
   Two causes, both fixed here:
     a. The row was a `Picker`. On this iOS 15 build its selection did not
        stick, so the row kept showing 自动 after choosing 中文.
     b. `reload()` ran on EVERY `.onAppear`. The Language row pushes a child
        list here, so coming back re-appeared the page and reloaded from disk,
        discarding the choice that had not been saved yet.

2) 「它不能选择图片，我点图片没有反应，它只能用那个 emoji」
   `.photosPicker` / `PhotosPickerItem` are iOS 16+, and the port stripped the
   modifier but left the bindings: 选择图片… set `showPhotoPicker = true` and
   nothing read it. Replaced with a PHPickerViewController presented through
   the same `UIKitPickerPresenter` the chat composer uses.

Static source checks only; the visible behaviour needs a device.
"""
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
SOUL = (ROOT / 'src/ios/Views/Settings/SoulSettingsView.swift').read_text()


class LanguageSticks(unittest.TestCase):

    def test_no_ios16_picker_left(self):
        self.assertNotIn('Picker(AppLocalized("Language")', SOUL)

    def test_language_row_is_a_menu_with_direct_assignment(self):
        i = SOUL.index('[T-soul-language-sticks]')
        body = SOUL[i:i + 1400]
        self.assertIn('Menu {', body)
        self.assertIn('lang = opt.value', body)

    def test_label_shows_current_value(self):
        self.assertIn('Self.langOptions.first { $0.value == lang }?.label ?? lang', SOUL)

    def test_reload_is_load_once(self):
        self.assertNotIn('.onAppear(perform: reload)', SOUL)
        self.assertIn('.onAppear { if !loadedRef.didLoad { reload() } }', SOUL)
        self.assertIn('var didLoad = false', SOUL)
        self.assertIn('loadedRef.didLoad = true', SOUL)


class ImagePickerWorks(unittest.TestCase):

    def test_no_dead_photos_picker_bindings(self):
        for dead in ('showPhotoPicker', 'photoItem', 'PhotosPickerItem'):
            self.assertNotIn(f'var {dead}', SOUL)

    def test_image_option_presents_a_real_picker(self):
        i = SOUL.index('Button(AppLocalized("Choose Image…"))')
        tail = SOUL[i:i + 160]
        self.assertIn('presentIconPhotoPicker()', tail)

    def test_phpicker_with_retained_delegate(self):
        self.assertIn('PHPickerViewController(configuration: config)', SOUL)
        # A weak delegate on a temporary would never call back.
        self.assertIn('@StateObject private var iconPhotoPicker = SoulIconPhotoPicker()', SOUL)
        self.assertIn('final class SoulIconPhotoPicker: NSObject, ObservableObject, PHPickerViewControllerDelegate', SOUL)

    def test_presented_through_the_shared_presenter(self):
        # The chat composer's presenter waits for the dialog to dismiss first.
        self.assertIn('UIKitPickerPresenter.present(picker)', SOUL)

    def test_picked_image_goes_through_the_same_encoder(self):
        # One encoder means the settings path and the `minis-config` path can
        # never disagree about what is storable.
        self.assertIn('SoulIconImage.encode(image)', SOUL)
        self.assertIn('case .failure:', SOUL)


if __name__ == '__main__':
    unittest.main(verbosity=2)
