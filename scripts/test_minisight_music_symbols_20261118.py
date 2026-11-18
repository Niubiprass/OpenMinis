#!/usr/bin/env python3
"""Production symbol-resolver regression, not a replacement model or MR ABI claim.
Portable C runs the exact extracted MSMusicSymbol body against constructed layouts.
macOS Foundation runs the unchanged production .m against actual dlsym/dladdr and
CoreFoundation shared-cache exports; baseline must pass before native mutants count.
No device, private-framework loading, network, credentials, or bridge disk writes.
"""
import argparse
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / 'src/ios/MiniSightCore' if (ROOT / 'src/ios/MiniSightCore').is_dir() else ROOT
FIXTURES = ROOT / 'scripts/fixtures/minisight_music_symbols_20261118'
OPTIONS = argparse.Namespace(require_native=False)
SOURCE = CORE / 'MiniSightMusicMonitor.m'
ANCHOR = 'strncmp(seg->segname, SEG_TEXT, sizeof(seg->segname)) == 0'
LEGACY = 'seg->fileoff == 0 && seg->filesize'
CODE_GUARD = '(code && (seg->initprot & VM_PROT_EXECUTE))'


def function(source):
    return source[source.index('static void *MSMusicSymbol('):source.index('static NSTimeInterval MSMusicNow(')]


def mutants(source):
    assert source.count(ANCHOR) == source.count(CODE_GUARD) == 1
    return [('legacy-fileoff', source.replace(ANCHOR, LEGACY), 'shared-cache nonzero fileoff code accepted', 'cached code resolved'),
            ('unsafe-kind', source.replace(CODE_GUARD, '(1 || ' + CODE_GUARD + ')'), 'data cannot be called as code', 'data denied as code')]


def run(args, timeout=90):
    return subprocess.run(args, text=True, capture_output=True, timeout=timeout)


class SourceGuards(unittest.TestCase):
    def test_production_anchor_and_security_guards(self):
        body = function(SOURCE.read_text())
        self.assertIn(ANCHOR, body)
        self.assertNotIn('seg->fileoff', body)
        for text in ('if (found) return NULL;', CODE_GUARD,
                     '!code && (seg->initprot & VM_PROT_READ) && !(seg->initprot & VM_PROT_EXECUTE)',
                     'value - start > sections[i].size - needed', 'return symbol;',
                     'ptrauth_strip(address, ptrauth_key_function_pointer)'):
            self.assertIn(text, body)
        # The returned pointer stays the dlsym pointer, not the stripped inspection address.
        self.assertNotIn('return (void *)address;', body)

    def test_writer_clock_is_not_uptime(self):
        source = SOURCE.read_text()
        writer = source.split('- (void)publishLine:', 1)[1].split('- (void)drainBridge', 1)[0]
        self.assertIn('NSTimeInterval now = NSDate.date.timeIntervalSince1970;', writer)
        self.assertIn('@"time": @(now)', writer)
        self.assertIn('_writeAt = MSMusicNow();', writer)
        bridge_path = ROOT / 'src/ios/MiniSightInAppRuntime.swift'
        if bridge_path.exists():
            bridge = bridge_path.read_text().split('private final class MiniSightMusicBridge:', 1)[1].split('private final class MiniSightAppActivity:', 1)[0]
            self.assertIn('Date().timeIntervalSince1970', bridge)
            self.assertIn('now - time <= 5', bridge)

    def test_real_image_fixture_not_private_abi_substitute(self):
        fixture = (FIXTURES / 'native.m').read_text()
        self.assertIn('#import "MiniSightMusicMonitor.m"', fixture)
        for text in ('MH_DYLIB_IN_CACHE', 'seg->fileoff != 0', 'CFStringGetTypeID',
                     'kCFRunLoopDefaultMode', 'resolved function callable', 'return 77;'):
            self.assertIn(text, fixture)
        self.assertNotIn('MediaRemote.framework', fixture)
        self.assertNotIn('@implementation MiniSightMusicMonitor', fixture)


class PortableProductionTests(unittest.TestCase):
    def test_constructed_layouts_and_assertion_negative_controls(self):
        compiler = shutil.which('cc') or shutil.which('clang')
        self.assertIsNotNone(compiler, 'portable C compiler required')
        source = SOURCE.read_text()
        template = (FIXTURES / 'portable.c').read_text()
        with tempfile.TemporaryDirectory(prefix='minisight-symbol-') as tmp:
            for label, content, failure, _ in [('baseline', source, None, None)] + mutants(source):
                src, exe = Path(tmp) / (label + '.c'), Path(tmp) / label
                src.write_text(template.replace('/* PRODUCTION_SYMBOL_FUNCTION */', function(content)))
                built = run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', str(src), '-o', str(exe)])
                self.assertEqual(built.returncode, 0, label + ': ' + built.stdout + built.stderr)
                result = run([str(exe)], timeout=15)
                if failure:
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('FAIL: ' + failure, result.stderr)
                    print('PORTABLE ASSERTION MUTANT KILLED:', label)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('PORTABLE PASS:', result.stdout)
                    print(result.stdout.strip())


class NativeRealImageTests(unittest.TestCase):
    def test_real_shared_cache_baseline_then_mutants(self):
        if platform.system() != 'Darwin' or not shutil.which('xcrun'):
            reason = 'Apple Foundation/shared-cache host unavailable; native image/PAC tests NOT executed'
            if OPTIONS.require_native:
                self.fail(reason)
            self.skipTest(reason)
        compiler = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        source = SOURCE.read_text()
        with tempfile.TemporaryDirectory(prefix='minisight-native-symbol-') as tmp:
            # No subTest here: a baseline failure must abort before ANY mutants.
            for label, content, _, failure in [('baseline', source, None, None)] + mutants(source):
                (Path(tmp) / 'MiniSightMusicMonitor.m').write_text(content)
                exe = Path(tmp) / label
                built = run([compiler, '-isysroot', sdk, '-fobjc-arc', '-fblocks', '-Wall', '-Wextra',
                    '-Werror=return-type', '-Wno-unused-parameter', '-I', tmp, '-I', str(CORE),
                    str(FIXTURES / 'native.m'), str(CORE / 'MiniSightLyrics.m'), '-framework', 'Foundation', '-o', str(exe)])
                self.assertEqual(built.returncode, 0, label + ': ' + built.stdout + built.stderr)
                result = run([str(exe)], timeout=20)
                if label == 'baseline' and result.returncode == 77:
                    if OPTIONS.require_native:
                        self.fail(result.stderr)
                    self.skipTest(result.stderr)
                if failure:
                    self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                    self.assertIn('FAIL: ' + failure, result.stderr)
                    print('NATIVE ASSERTION MUTANT KILLED:', label)
                else:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    self.assertIn('NATIVE PASS:', result.stdout)
                    print(result.stdout.strip())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-native', action='store_true')
    OPTIONS, rest = parser.parse_known_args()
    print('Portable layouts are not MR/PAC ABI evidence; native SKIP is not a pass.', flush=True)
    unittest.main(argv=[__file__] + rest, verbosity=2)
