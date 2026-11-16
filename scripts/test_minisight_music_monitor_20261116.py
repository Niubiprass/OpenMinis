#!/usr/bin/env python3
"""Source conformance + actual production ObjC/Foundation callback harness on macOS.
No device, MediaRemote loading, playback, bridge disk writes or real LRCLIB calls.
Linux reports native SKIP; source assertions are NOT native execution evidence.
"""
import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PLUGIN = ROOT.parent.parent / 'MiniSight-complete-20261105'
OPTIONS = argparse.Namespace(plugin_root=os.getenv('MINISIGHT_MUSIC_PLUGIN_ROOT', str(DEFAULT_PLUGIN)), require_native=False)
FIXTURE = ROOT / 'scripts/fixtures/minisight_music_monitor_20261116/runtime.m'


def plugin():
    # Each CI repository carries the same production monitor source snapshot.
    local = ROOT / 'src/ios/MiniSightCore'
    if (local / 'MiniSightMusicMonitor.m').is_file():
        return local
    direct = ROOT
    if (direct / 'MiniSightMusicMonitor.m').is_file():
        return direct
    return Path(OPTIONS.plugin_root) / 'debs/MiniSight'


def errors(source):
    required = {
        'info ABI': 'typedef void (*MSMusicInfoFn)(dispatch_queue_t, void (^)(CFDictionaryRef));',
        'playing ABI': 'typedef void (*MSMusicPlayingFn)(dispatch_queue_t, void (^)(Boolean));',
        'symbol kind': 'S_ATTR_PURE_INSTRUCTIONS | S_ATTR_SOME_INSTRUCTIONS',
        'string kind': 'CFGetTypeID(value) == CFStringGetTypeID()',
        'main boundary': 'dispatch_async(dispatch_get_main_queue(), ^{ completion(info); });',
        'borrow before hop': 'NSDictionary *info = MSMusicCopyInfo(raw);',
        'physical slot': 'if (!_reading && now >= _pollAt)',
        'timeout slot retained': '_readTimedOut = YES; ++_readGeneration;',
        'callback stage': 'stage != _readStage',
        'snapshot sandwich': '[firstIdentity isEqualToString:lastIdentity]',
        'event coalescing': 'if (_eventQueued) return;',
        'single song cooldown': 'self->_retryTimes[retryKey] = @(received + 60.);',
        'bounded cooldown': 'self->_retryTimes.count >= 16',
        'bridge mailbox': 'if (_bridgeScheduled) return;',
        'bridge freshness': 'verified && version == _bridgeVersion',
        'container scrub': 'MSBridgeWrite(_writtenContainer, @"music-state.json", clear)',
        'lyrics generation': 'generation != self->_trackGeneration',
        'process fence': 'allowed = allowed && _springBoard;',
        'lock state': 'if (allowed && ![MiniSightMusicMonitor deviceIsUnlockedWithKnown:&lockKnown]) {',
        'runtime gate recheck': 'if (![self refreshPresentation]) return;',
        'real boolean writer': '@"playing": @((BOOL)(_allowed && playing))',
        'evidence writer': '@"presentation": _presentation ?: @{}, @"stopReason": stopReason',
        'unknown metadata motion': 'track.cacheKey ?: @"unknown"',
        'lyrics independent freshness': 'self->_lyricsAwaitingFreshInfo = YES;',
        'lock ABI': "(type[0] != 'B' && type[0] != 'c')",
        'reference time': 'age <= track.duration + 3.',
        'real readback': 'MSBridgeRead(container, @"music-state.json", 16384)',
    }
    result = [label for label, text in required.items() if text not in source]
    for forbidden in ('MRMediaRemoteSendCommand', 'MRMediaRemoteSetElapsedTime', 'NSLog(', '/api/get', 'AVAudioRecorder'):
        if forbidden in source:
            result.append('forbidden:' + forbidden)
    configure = source.split('- (void)configureAllowed:', 1)[1].split('- (void)mediaChanged:', 1)[0]
    if '_reading = NO' in configure or '_retryTimes = ' in configure:
        result.append('reopen resets physical slot/cooldown')
    timeout = source.split('if (_reading && !_readTimedOut', 1)[1].split('if (!_reading', 1)[0]
    if '_reading = NO' in timeout:
        result.append('timeout incorrectly cancels native call')
    return result


class SourceTests(unittest.TestCase):
    def test_contract(self):
        self.assertEqual(errors((plugin() / 'MiniSightMusicMonitor.m').read_text()), [])

    def test_negative_controls(self):
        source = (plugin() / 'MiniSightMusicMonitor.m').read_text()
        for old, new in (
            ('stage != _readStage', 'NO'),
            ('[firstIdentity isEqualToString:lastIdentity]', 'YES'),
            ('verified && version == _bridgeVersion', 'verified'),
            ('self->_retryTimes[retryKey] = @(received + 60.);', ''),
            ('_readTimedOut = YES; ++_readGeneration;', '_readTimedOut = YES; _reading = NO;'),
        ):
            with self.subTest(mutation=old):
                self.assertIn(old, source)
                self.assertTrue(errors(source.replace(old, new)))

    def test_real_harness_is_not_python_model(self):
        native = FIXTURE.read_text()
        self.assertIn('#import "MiniSightMusicMonitor.m"', native)
        self.assertIn('#define MINISIGHT_MUSIC_MONITOR_TEST 1', native)
        self.assertIn('MSMusicInfo = GetInfo; MSMusicIsPlaying = GetState;', native)
        self.assertIn('maxPending <= 1', native)
        self.assertIn('writes - before <= 2', native)
        self.assertNotIn('https://', native)
        self.assertNotIn('@implementation MiniSightMusicMonitor', native)


class PortablePresentationTests(unittest.TestCase):
    def test_actual_production_gate_and_epochs(self):
        cc = shutil.which('cc') or shutil.which('clang')
        self.assertIsNotNone(cc, 'Portable C compiler is required')
        with tempfile.TemporaryDirectory(prefix='minisight-presentation-') as tmp:
            binary = Path(tmp) / 'presentation'
            result = subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(plugin()), str(FIXTURE.with_name('presentation.c')), '-lm', '-o', str(binary)],
                text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PORTABLE PASS:', result.stdout)
            print(result.stdout.strip())


class NativeFoundationTests(unittest.TestCase):
    def test_production_runtime(self):
        if platform.system() != 'Darwin' or not shutil.which('xcrun'):
            reason = 'Apple Foundation SDK unavailable; native monitor runtime NOT executed'
            if OPTIONS.require_native:
                self.fail(reason)
            self.skipTest(reason)
        clang = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        with tempfile.TemporaryDirectory(prefix='minisight-monitor-') as tmp:
            binary = Path(tmp) / 'runtime'
            result = subprocess.run([clang, '-isysroot', sdk, '-fobjc-arc', '-fblocks', '-Wall', '-Wextra',
                '-Werror=return-type', '-Wno-unused-parameter', '-I', str(plugin()), str(FIXTURE),
                str(plugin() / 'MiniSightLyrics.m'), '-framework', 'Foundation', '-o', str(binary)],
                text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=45)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('NATIVE PASS:', result.stdout)
            print(result.stdout.strip())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plugin-root', default=OPTIONS.plugin_root)
    parser.add_argument('--require-native', action='store_true')
    OPTIONS, rest = parser.parse_known_args()
    print('Source conformance only; native SKIP is NOT runtime success.', flush=True)
    unittest.main(argv=[__file__] + rest, verbosity=2)
