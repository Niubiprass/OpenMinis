#!/usr/bin/env python3
"""Local/static checks plus REAL Objective-C/Foundation tests on macOS; no network.
Linux MUST report native SKIP, never a translated/reimplemented-parser success.
Use --require-native on macOS CI. This script does not launch CI or alter projects.
"""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT / "src/ios/MiniSightCore"
if not (CORE / "MiniSightLyrics.m").is_file() and (ROOT / "MiniSightLyrics.m").is_file():
    CORE = ROOT  # Same source and fixture runner in the plugin repository.
FIXTURES = ROOT / "scripts/fixtures"
SOURCE = CORE / "MiniSightLyrics.m"
HEADER = CORE / "MiniSightLyrics.h"
NATIVE = FIXTURES / "minisight_lyrics_20261116.m"
DATA = FIXTURES / "minisight_lyrics_20261116.json"
DEFAULT_PLUGIN = ROOT.parent.parent / "MiniSight-complete-20261105"
OPTIONS = argparse.Namespace(
    plugin_root=os.environ.get("MINISIGHT_LYRICS_PLUGIN_ROOT") or (str(DEFAULT_PLUGIN) if DEFAULT_PLUGIN.is_dir() else None),
    require_native=os.environ.get("MINISIGHT_LYRICS_REQUIRE_NATIVE") == "1",
)


def contract_errors(source, header):
    """Only source conformance, NOT runtime proof. Controls ensure these checks fail closed."""
    errors = []
    for symbol in ("MiniSightLyricLine", "MiniSightLyricsTimeline", "MiniSightLyricsTrack", "MiniSightLyricsClient"):
        if "@interface " + symbol not in header:
            errors.append("API:" + symbol)
    required = {
        "HTTPS endpoint": 'componentsWithString:@"https://lrclib.net/api/get"',
        "generation fence": "owner.generation == generation",
        "task identity fence": "if (task != _task)",
        "stream cap": "data.length > MSLyricsMaxBytes - _body.length",
        "byte budget": "MSLyricsMaxBytes = 1024 * 1024;",
        "exact title": "[title isEqualToString:track.title]",
        "exact artist": "[artist isEqualToString:track.artist]",
        "duration tolerance": "fabs([duration doubleValue] - track.duration) > 2.0",
        "ephemeral session": "NSURLSessionConfiguration.ephemeralSessionConfiguration",
        "no cookie store": "config.HTTPCookieStorage = nil;",
        "no cookie acceptance": "config.HTTPShouldSetCookies = NO;",
        "no credential store": "config.URLCredentialStorage = nil;",
        "no disk cache": "config.URLCache = nil;",
        "request deadline": "config.timeoutIntervalForRequest = 12.0;",
        "resource deadline": "config.timeoutIntervalForResource = 15.0;",
        "small memory cache": "_cache.countLimit = 16;",
        "cost limit": "_cache.totalCostLimit = 4 * MSLyricsMaxBytes;",
        "main delegate queue": "delegateQueue:NSOperationQueue.mainQueue",
        "cancel task": "[_task cancel];",
        "weak delegate owner": "@property(nonatomic, weak) MiniSightLyricsClient *owner;",
        "no redirects": "completionHandler(nil);",
        "honor server wait": "MAX(fallback, seconds)",
        "blank clearing": "if (!line.text.length || time - line.time >= MSLyricsMaxDisplay) return nil;",
    }
    for label, needle in required.items():
        if needle not in source:
            errors.append(label)
    for forbidden in ("UIKit", "MediaRemote", "AVFoundation", "/api/search", "plainLyrics", "NSLog(", "Authorization", "album_name", "HTTPBody ="):
        if forbidden in source:
            errors.append("forbidden:" + forbidden)
    return errors


class SourceContractTests(unittest.TestCase):
    def test_production_contract(self):
        self.assertEqual(contract_errors(SOURCE.read_text(), HEADER.read_text()), [])

    def test_static_negative_controls(self):
        source, header = SOURCE.read_text(), HEADER.read_text()
        changes = [
            ("owner.generation == generation", "YES"),
            ("fabs([duration doubleValue] - track.duration) > 2.0", "NO"),
            ("config.URLCredentialStorage = nil;", ""),
            ("data.length > MSLyricsMaxBytes - _body.length", "NO"),
            ("MAX(fallback, seconds)", "fallback"),
        ]
        for old, new in changes:
            with self.subTest(mutation=old):
                self.assertIn(old, source)
                self.assertTrue(contract_errors(source.replace(old, new), header))

    def test_fixture_calls_production_not_a_port(self):
        fixture = json.loads(DATA.read_text())
        self.assertEqual(fixture["track"]["title"].strip(), "Fixture  Song")
        native = NATIVE.read_text()
        self.assertIn("[MiniSightLyricsTimeline timelineWithLRC:", native)
        self.assertIn("[MiniSightLyricsClient timelineForResponseData:", native)
        self.assertIn("@interface FixtureProtocol : NSURLProtocol", native)
        self.assertIn("+ (BOOL)canInitWithRequest:(NSURLRequest *)request { return YES; }", native)
        self.assertNotIn("@implementation MiniSightLyricsTimeline", native)
        self.assertNotIn("@implementation MiniSightLyricsClient", native)

    def test_plugin_byte_identical(self):
        if not OPTIONS.plugin_root:
            self.skipTest("plugin tree not supplied/present; use --plugin-root for parity check")
        plugin = Path(OPTIONS.plugin_root) / "debs/MiniSight"
        for name in ("MiniSightLyrics.h", "MiniSightLyrics.m"):
            self.assertEqual((CORE / name).read_bytes(), (plugin / name).read_bytes(), name)


class NativeFoundationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if platform.system() != "Darwin" or not shutil.which("xcrun"):
            reason = "Apple Foundation SDK unavailable (Linux/no xcrun); production native tests NOT executed"
            if OPTIONS.require_native:
                raise AssertionError(reason)
            raise unittest.SkipTest(reason)
        cls.clang = subprocess.check_output(["xcrun", "--find", "clang"], text=True).strip()
        cls.sdk = subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip()
        cls.temp = tempfile.TemporaryDirectory(prefix="minisight-lyrics-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.baseline = cls.compile(SOURCE, "production")

    @classmethod
    def compile(cls, source, name):
        binary = cls.directory / name
        command = [cls.clang, "-isysroot", cls.sdk, "-fobjc-arc", "-fblocks", "-Wall", "-Wextra",
                   "-Werror=return-type", "-Wno-unused-parameter", "-I", str(CORE),
                   str(source), str(NATIVE), "-framework", "Foundation", "-o", str(binary)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise AssertionError("Native compilation failed (not skipped):\n" + result.stdout + result.stderr)
        return binary

    def run_fixture(self, binary):
        return subprocess.run([str(binary), str(DATA)], capture_output=True, text=True, timeout=45)

    def test_real_production_foundation(self):
        result = self.run_fixture(self.baseline)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("NATIVE PASS:", result.stdout)
        print(result.stdout.strip())

    def test_native_mutations_are_killed(self):
        # Same real harness against independently broken production copies; never installed.
        source = SOURCE.read_text()
        mutations = {
            "duration": ("fabs([duration doubleValue] - track.duration) > 2.0", "NO"),
            "generation": ("owner.generation == generation", "YES"),
            "late_task": ("if (task != _task)", "if (NO)"),
            "retry_after": ("return isfinite(seconds) ? MAX(fallback, seconds) : DBL_MAX;", "return fallback;"),
            "blank": ("if (!line.text.length || time - line.time >= MSLyricsMaxDisplay) return nil;",
                      "if (time - line.time >= MSLyricsMaxDisplay) return nil;"),
            "body_cap": ("MSLyricsMaxBytes = 1024 * 1024;", "MSLyricsMaxBytes = 2 * 1024 * 1024;"),
        }
        # Baseline must succeed before a failing mutant is counted as detected.
        baseline = self.run_fixture(self.baseline)
        self.assertEqual(baseline.returncode, 0, baseline.stdout + baseline.stderr)
        for name, (old, new) in mutations.items():
            with self.subTest(mutation=name):
                self.assertIn(old, source)
                changed = self.directory / (name + ".m")
                changed.write_text(source.replace(old, new))
                result = self.run_fixture(self.compile(changed, name))
                self.assertNotEqual(result.returncode, 0, "Surviving native mutant: " + name)
                self.assertIn("FAIL:", result.stderr, "Crash/timeout is not an assertion-based mutation kill")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    default_plugin = ROOT.parent.parent / "MiniSight-complete-20261105"
    parser.add_argument("--plugin-root", default=os.environ.get("MINISIGHT_LYRICS_PLUGIN_ROOT") or (str(default_plugin) if default_plugin.is_dir() else None))
    parser.add_argument("--require-native", action="store_true", default=os.environ.get("MINISIGHT_LYRICS_REQUIRE_NATIVE") == "1")
    OPTIONS, remaining = parser.parse_known_args()
    print("Source checks are conformance only; native SKIP is NOT runtime success.", flush=True)
    unittest.main(argv=[__file__] + remaining, verbosity=2)
