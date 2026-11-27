#!/usr/bin/env python3
"""Portable C behavior is real; UIKit/ImageIO only typechecked on approved CI.
No device, audio, network, CI dispatch or installation. --require-ios fails closed.
"""
import argparse
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'src/ios/MiniSightCore'
PLUGIN = Path(os.environ.get('MINISIGHT_PLUGIN_ROOT', '/var/minis/shared/MiniSight-complete-20261105')) / 'debs/MiniSight'
FIX = ROOT / 'scripts/fixtures/minisight_liveliness_20261116/policy.c'
ARGS = argparse.Namespace(require_ios=False, ios_sdk=None)

class Integration(unittest.TestCase):
    def test_sprite_not_text_or_hit_region_transforms(self):
        effects = (CORE / 'MiniSightPetEffects.m').read_text()
        pet = (CORE / 'MiniSightPet.m').read_text()
        self.assertIn('_sprite.affineTransform = transform', effects)
        self.assertNotIn('self.transform = CGAffineTransformConcat', pet)
        self.assertIn('return _ownsSprite;', effects)
        self.assertIn('self->_ownsSprite = YES;', effects)
        self.assertIn('self->_frameFailures >= 3', effects)
        self.assertIn('[self restorePoster]', effects)
        self.assertIn('request != self->_frameRequest', effects)
        self.assertIn('self->_running', effects)
        self.assertIn('_effects.autonomyHeld', pet)
        self.assertIn('[self setSpriteState:MiniSightPetStateIdle];', pet.split('- (void)finishMotion {', 1)[1])
        self.assertIn('for (NSUInteger pass = 0; pass < 2;', pet)
        self.assertIn('_lastSpriteRect = CGRectNull', pet)
        from test_minisight_atlas_restore_20261118 import validate
        validate(pet, effects, (CORE / 'MiniSightPet.h').read_text())
        if PLUGIN.is_dir():
            validate((PLUGIN / 'MiniSightPet.m').read_text(),
                     (PLUGIN / 'MiniSightPetEffects.m').read_text(),
                     (PLUGIN / 'MiniSightPet.h').read_text())
        self.assertIn('if ([self presentationBlocked]) return @"idle";', effects)
        self.assertIn('fabs(_measurementWidth - available)', effects)
        self.assertIn('!CGSizeEqualToSize(_lastTailSize, _bubbleSize)', effects)
        self.assertIn('pet.center.y + _visualOffset.y', effects)
        self.assertIn('double time = loops ? fmod(elapsed, duration) : fmin(elapsed, duration)', effects)
        self.assertIn('now - _selectionBegan < 2.', effects)
        self.assertNotIn('Text(k.key)', effects)

    def test_release_and_cancel_paths(self):
        runtime = (ROOT / 'src/ios/MiniSightInAppRuntime.swift').read_text()
        gesture = runtime.split('@objc private func pan(', 1)[1].split('func teardown()', 1)[0]
        ended = gesture.split('case .ended:', 1)[1].split('case .cancelled', 1)[0]
        cancelled = gesture.split('case .cancelled, .failed:', 1)[1].split('default:', 1)[0]
        self.assertLess(ended.index('pet.updateDraggingTarget'), ended.index('pet.endDraggingCancelled(false)'))
        self.assertIn('pet.endDraggingCancelled(true)', cancelled)
        self.assertNotIn('parent.center', cancelled)
        self.assertNotIn('pet.center =', gesture)
        self.assertNotIn('beginDragging(withDirection: delta', gesture)
        if PLUGIN.is_dir():
            tweak = (PLUGIN / 'Tweak.xm').read_text()
            ended = tweak.split('case UIGestureRecognizerStateEnded: {', 1)[1].split('default:', 1)[0]
            self.assertLess(ended.index('[gMiniSightPet updateDraggingTarget:want]'), ended.index('[gMiniSightPet endDraggingCancelled:NO]'))
            self.assertIn('else MiniSightSetAnchor(want, NO)', tweak)
            self.assertIn('gMiniSightPet.lyricsSuppressed = YES', tweak)
            self.assertIn('MiniSightUpdateMusic();', tweak)

    def test_settings_and_project_are_wired(self):
        keys = (ROOT / 'src/ios/MiniSightSettings.swift').read_text()
        store = (ROOT / 'src/ios/MiniSightConfigStore.swift').read_text()
        for key in ['lyricsEnabled', 'musicMotion']:
            self.assertIn('MiniSightSettingKey.' + key + ': false', keys)
            self.assertIn('MiniSightSettingKey.' + key + ': return ' + key, store)
        self.assertIn('runtimeFields.count == 53', keys)  # Previous 52 plus independent keyboard avoidance.
        self.assertIn('MiniSightSettingKey.dailyActionsEnabled: "dailyActionsEnabled"', keys)
        self.assertIn('MiniSightSettingKey.dailyActionsEnabled: true', keys)
        self.assertIn('case MiniSightSettingKey.dailyActionsEnabled: return dailyActionsEnabled', store)
        for key in ['wakeEnabled', 'wakeName', 'wakePronunciation']:
            self.assertIn('MiniSightSettingKey.' + key + ':', keys)
            self.assertIn('case MiniSightSettingKey.' + key + ': return ' + key, store)
        catalog = (ROOT / 'src/ios/Agent/Chat/MiniSightCatalog.swift').read_text()
        self.assertGreaterEqual(catalog.count('"image/gif"'), 1)
        self.assertIn('image/webp, image/gif', catalog)
        project = (ROOT / 'src/ios/Minis.xcodeproj/project.pbxproj').read_text()
        for name in ['MiniSightPetEffects', 'MiniSightActionLibrary', 'MiniSightLyrics']:
            self.assertEqual(project.count('/* ' + name + '.m in Sources */'), 2)
            self.assertIn('path = ' + name + '.m;', project)
        if PLUGIN.is_dir():
            for name in ['MiniSightPetEffects.h', 'MiniSightPetEffects.m', 'MiniSightLiveliness.h', 'MiniSightActionLibrary.h', 'MiniSightActionLibrary.m', 'MiniSightLyrics.h', 'MiniSightLyrics.m']:
                self.assertEqual((CORE / name).read_bytes(), (PLUGIN / name).read_bytes(), name)

class PortablePolicy(unittest.TestCase):
    def run_policy(self, header):
        compiler = shutil.which('cc') or shutil.which('clang')
        self.assertIsNotNone(compiler, 'portable C compiler missing')
        with tempfile.TemporaryDirectory(prefix='minisight-policy-') as temp:
            path = Path(temp)
            (path / 'MiniSightLiveliness.h').write_text(header)
            result = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(path), str(FIX), '-lm', '-o', str(path / 'policy')], text=True, capture_output=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(path / 'policy')], text=True, capture_output=True, timeout=30)
            return result

    def test_production_policy(self):
        result = self.run_policy((CORE / 'MiniSightLiveliness.h').read_text())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())

    def test_behavior_mutations_are_detected(self):
        header = (CORE / 'MiniSightLiveliness.h').read_text()
        for before, after in [('exp(-omega * dt)', '1.'), ('speed < 160.', 'speed < 0.'),
                ('now - last.t > .11', 'now - last.t > 10.'), ('fmin(speed, 1800.)', 'speed')]:
            with self.subTest(mutation=before):
                self.assertEqual(header.count(before), 1)
                result = self.run_policy(header.replace(before, after))
                self.assertNotEqual(result.returncode, 0, before + ' escaped real C checks')

class AppleTypes(unittest.TestCase):
    def test_production_effects_and_lyrics_ios15(self):
        if platform.system() != 'Darwin' or not shutil.which('xcrun'):
            if ARGS.require_ios: self.fail('Apple SDK required; production UIKit types NOT checked')
            self.skipTest('Apple SDK unavailable; UIKit/MediaRemote runtime NOT tested')
        self.assertIn(os.environ.get('CI', '').lower(), ['1', 'true', 'yes'], 'Apple compilation reserved for authorized CI')
        sdk = ARGS.ios_sdk or subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
        self.assertTrue(Path(sdk).is_dir())
        for arch in ['arm64', 'arm64e']:
            for name in ['MiniSightPet.m', 'MiniSightPetEffects.m', 'MiniSightActionLibrary.m', 'MiniSightLyrics.m', 'MiniSightMusicMonitor.m']:
                result = subprocess.run(['xcrun', '--sdk', 'iphoneos', 'clang', '-std=gnu11', '-fobjc-arc', '-fblocks',
                    '-fsyntax-only', '-Wall', '-Wextra', '-Werror=return-type', '-Werror=unguarded-availability-new',
                    '-Wno-deprecated-declarations', '-target', arch + '-apple-ios15.5', '-isysroot', sdk,
                    '-I', str(CORE), str(CORE / name)], text=True, capture_output=True, timeout=120)
                self.assertEqual(result.returncode, 0, name + '\n' + result.stdout + result.stderr)
        print('PASS production UIKit/ImageIO arm64 and arm64e iOS15.5 typechecks; no device rendering')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-ios', action='store_true')
    parser.add_argument('--ios-sdk')
    ARGS, rest = parser.parse_known_args()
    unittest.main(argv=[__file__] + rest, verbosity=2)
