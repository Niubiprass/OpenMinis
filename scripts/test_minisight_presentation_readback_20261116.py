#!/usr/bin/env python3
"""Actual production Tweak excerpts and resource writer, synthetic dependencies.
No device, audio, music titles, live network or native runtime on iSH. --require-native
fails closed without macOS Foundation. Portable checks do NOT prove UIKit visuals.
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT/'src/ios/MiniSightCore' if (ROOT/'src/ios/MiniSightCore').is_dir() else ROOT
FIXTURE = ROOT/'scripts/fixtures/minisight_presentation_readback_20261116'
OPTIONS = argparse.Namespace(require_native=os.getenv('V64R_REQUIRE_SWIFT') == '1')

def extract(text, marker):
    start = text.index(marker)
    brace = text.index('{', start)
    depth, quote, comment = 0, None, None
    i = brace
    while i < len(text):
        c, pair = text[i], text[i:i+2]
        if comment == 'line':
            if c == '\n': comment = None
        elif comment == 'block':
            if pair == '*/': comment = None; i += 1
        elif quote:
            if c == '\\': i += 1
            elif c == quote: quote = None
        elif pair == '//': comment = 'line'; i += 1
        elif pair == '/*': comment = 'block'; i += 1
        elif c in ('"', "'"): quote = c
        elif c == '{': depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0: return text[start:i+1]
        i += 1
    raise ValueError(marker)

class Source(unittest.TestCase):
    def test_literal_production_excerpts_match(self):
        manifest = json.loads((FIXTURE/'PRODUCTION-EXCERPTS.json').read_text())
        for kind, filename in [('tweak','tweak_presentation.inc'), ('resources','resources_shown_writer.inc')]:
            excerpt = (FIXTURE/filename).read_text()
            source_file = CORE/('Tweak.xm' if kind == 'tweak' else 'MiniSightResources.m')
            for marker, digest in manifest[kind].items():
                literal = extract(excerpt, marker)
                self.assertEqual(hashlib.sha256(literal.encode()).hexdigest(), digest)
                if source_file.is_file(): self.assertEqual(extract(source_file.read_text(), marker), literal)
        self.assertIn('literal-production-excerpt', manifest['kind'])
    def test_real_io_and_convergence_paths_covered(self):
        source = (CORE/'MiniSightShownReadback.h').read_text()
        for required in ('O_NOFOLLOW', 'O_NONBLOCK', 'before.st_size == 1', 'read(fd, bytes', 'after.st_ino', '_minisightShownIdentity', 'MSMusicShownEvidence(container,'):
            self.assertIn(required, source)
        runtime = (FIXTURE/'runtime.m').read_text()
        for required in ('MiniSightApplyShownReadback()', 'CompletePreferences(staleSettings)', 'CompleteResource(staleResources)', 'gMiniSightAppliedRenderer == 1', 'atomic_load(&notifications)', 'relative-invalid'):
            self.assertIn(required, runtime)
        self.assertNotIn('https://', runtime)
        self.assertNotIn('AVAudio', runtime)
        support = (FIXTURE/'support.m').read_text()
        self.assertIn('#include "tweak_presentation.inc"', support)
        self.assertIn('#include "resources_shown_writer.inc"', support)

class Native(unittest.TestCase):
    def compile_and_run(self, directory, *, reject=False):
        if platform.system() != 'Darwin' or not shutil.which('xcrun'):
            message = 'Apple Foundation unavailable: real Tweak/write/readback fixture NOT compiled/executed'
            if OPTIONS.require_native: self.fail(message)
            self.skipTest(message)
        clang = subprocess.check_output(['xcrun', '--find', 'clang'], text=True).strip()
        sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
        with tempfile.TemporaryDirectory(prefix='ms-presentation-runtime-') as temp:
            binary = Path(temp)/'runtime'
            result = subprocess.run([clang, '-isysroot', sdk, '-fobjc-arc', '-fblocks', '-std=gnu11',
                '-Wall', '-Wextra', '-Werror=return-type', '-Wno-unused-function', '-I', str(CORE),
                '-I', str(directory), str(directory/'runtime.m'), '-framework', 'Foundation', '-o', str(binary)],
                text=True, capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=20)
            if reject: self.assertNotEqual(result.returncode, 0, 'unsafe production mutation incorrectly passed')
            else:
                self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
                self.assertIn('NATIVE PRESENTATION READBACK PASS:', result.stdout)
                print(result.stdout.strip())
    def test_actual_tweak_and_writer(self): self.compile_and_run(FIXTURE)
    def test_stale_setting_and_resource_mutations(self):
        self.compile_and_run(FIXTURE)  # Baseline must really compile and run first.
        original = (FIXTURE/'tweak_presentation.inc').read_text()
        # A second production epoch guard in ConvergeSettings rescues a single
        # bypass. Mutate BOTH defenses to test a genuinely unsafe stale apply.
        mutations = [
            [ ('!MSMusicEpochIsCurrent(gMiniSightSettingsEpoch, epoch) || gMiniSightSettingsRefreshAgain', 'NO'),
              ('if (!MSMusicEpochIsCurrent(gMiniSightSettingsEpoch, gMiniSightPreferencesEpoch)) {', 'if (NO) {') ],
            [ ('MiniSightConvergeSettings(YES);', 'MiniSightUpdateMusic();') ]
        ]
        for edits in mutations:
            with self.subTest(mutation=edits):
                changed = original
                for old,new in edits:
                    self.assertIn(old, changed)
                    changed = changed.replace(old,new,1)
                with tempfile.TemporaryDirectory(prefix='ms-unsafe-presentation-') as temp:
                    directory = Path(temp)
                    for filename in ('support.m', 'runtime.m', 'resources_shown_writer.inc'):
                        shutil.copyfile(FIXTURE/filename, directory/filename)
                    (directory/'tweak_presentation.inc').write_text(changed)
                    self.compile_and_run(directory, reject=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-native', action='store_true', default=OPTIONS.require_native)
    OPTIONS, rest = parser.parse_known_args()
    print('Source integrity only on iSH; native SKIP is NOT successful runtime verification.', flush=True)
    unittest.main(argv=[__file__]+rest, verbosity=2)
