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
import re
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
NATIVE22 = FIXTURES / "minisight_lyrics_20261122/native_client.inc"
NATIVE23 = FIXTURES / "minisight_lyrics_20261123/native_client.inc"
PORTABLE = FIXTURES / "minisight_lyrics_20261123/portable.c"
DATA = FIXTURES / "minisight_lyrics_20261116.json"
DEFAULT_PLUGIN = ROOT.parent.parent / "MiniSight-complete-20261105"
OPTIONS = argparse.Namespace(
    plugin_root=os.environ.get("MINISIGHT_LYRICS_PLUGIN_ROOT") or (str(DEFAULT_PLUGIN) if DEFAULT_PLUGIN.is_dir() else None),
    require_native=os.environ.get("MINISIGHT_LYRICS_REQUIRE_NATIVE") == "1" or os.environ.get("CI", "").lower() == "true",
)


def contract_errors(source, header):
    """Only source conformance, NOT runtime proof. Controls ensure these checks fail closed."""
    errors = []
    for symbol in ("MiniSightLyricLine", "MiniSightLyricsTimeline", "MiniSightLyricsTrack", "MiniSightLyricsClient"):
        if "@interface " + symbol not in header:
            errors.append("API:" + symbol)
    required = {
        "HTTPS exact endpoint": 'componentsWithString:@"https://lrclib.net/api/get"',
        "HTTPS fallback endpoint": 'componentsWithString:@"https://lrclib.net/api/search"',
        "strict endpoint path": 'MSLyricsAllowedURL(response.URL, MSLyricsRouteLRCLibSearch)',
        "QQ JSONP strict": "MSQQJSONP",
        "QQ base64 canonical": "base64EncodedStringWithOptions:0",
        "QQ exact source host": '@"c.y.qq.com"',
        "QQ request bounded MID": 'MSLyricsQQMIDOK(midBytes.bytes, midBytes.length)',
        "QQ delayed captured generation": 'MSLyricsQQTicket(ticket, owner.generation, owner.activeGeneration,',
        "QQ only from LRCLIB search": 'MSLyricsMayTryQQ(!wasQQ && wasSearch, _qqSearchAttempted, error != nil, timeline != nil,',
        "QQ validate response URL": '(_qqTask && ![response.URL isEqual:task.originalRequest.URL])',
        "QQ optional response echo": 'obj[@"songmid"] && ![obj[@"songmid"] isEqual:_qqSongMID]',
        "QQ parse actual envelope": 'MSLyricsQQPayloadRange(data.bytes, data.length, &at, &length)',
        "QQ stage attempt fence": "_qqSearchAttempted",
        "QQ lyrics timed parser": "timelineWithLRC:lrc duration:_track.duration",
        "search attempt fence": "_searchAttempted",
        "search query item": 'queryItemWithName:@"q"',
        "bounded search candidates": '[payload count] > 20',
        "search body parser": "timelineForSearchResponseData:",
        "explicit unsynced rescue only": 'status == 200 && validatedUnsynced',
        "strict parser before rescue": '[reason isEqualToString:@"no_synced_lyrics"]',
        "absent field is rejected": 'if (!lrc) return nil;',
        "finished task shared deadline": '!MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime, _deadline)',
        "queued delivery shared deadline": 'MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime, deadline)',
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
        "weak delegate owner": "@property(nonatomic, weak, nullable) MiniSightLyricsClient *owner;",
        "no redirects": "completionHandler(nil);",
        "honor server wait": "MAX(fallback, seconds)",
        "explicit blank clearing without a timed expiry": "if (!line.text.length) return nil;",
    }
    for label, needle in required.items():
        if needle not in source:
            errors.append(label)
    for forbidden in ("UIKit", "MediaRemote", "AVFoundation", "plainLyrics", "NSLog(", "Authorization", "album_name", "HTTPBody ="):
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
            ('status == 200 && validatedUnsynced', 'status == 200'),
            ('if (!lrc) return nil;', ''),
            ('!MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime, _deadline)', 'NO'),
        ]
        for old, new in changes:
            with self.subTest(mutation=old):
                self.assertIn(old, source)
                self.assertTrue(contract_errors(source.replace(old, new), header))

    def test_detail_codes_are_bounded_and_log_allowlisted(self):
        import re
        src = SOURCE.read_text()
        log = (CORE / 'MiniSightLog.m').read_text()
        # Dictionary syntax, not a following ':' alone: ternary reason values
        # also precede colons. Keep the expected result set unchanged.
        keys = set(re.findall(r'(?:@\{|,)\s*@"(lyrics_[a-z_]+)"\s*:', src))
        codes = set(re.findall(r'@"(lyrics_[a-z_]+|no_synced_lyrics)"', src)) - keys
        self.assertEqual(codes, set('lyrics_http lyrics_cooldown lyrics_network_error lyrics_response_rejected lyrics_not_found lyrics_rate_limited lyrics_timeout lyrics_service_unavailable lyrics_oversized lyrics_track_mismatch lyrics_instrumental lyrics_invalid_lrc lyrics_timeline no_synced_lyrics'.split()))
        for code in codes: self.assertIn('@"'+code+'"',log)
        self.assertNotIn('localizedDescription',src)
        evidence = src.split('static void MSLyricsEvidence(',1)[1].split('// BEGIN LYRICS PORTABLE POLICY',1)[0]
        self.assertEqual(src.count('MSDiagEvent('), 1)
        self.assertIn('MSDiagEvent(@"lyrics", stage, result', evidence)
        self.assertIn('now - [times[slot] doubleValue] < 60.0', evidence)
        self.assertIn('MIN((NSUInteger)21, candidates)', evidence)
        self.assertIn('MIN(bytes, MSLyricsMaxBytes)', evidence)
        self.assertIn('MIN(599, status)', evidence)
        for field in ('title', 'artist', 'lyric', 'url', 'cookies', 'error'):
            self.assertNotIn('@"' + field + '"', evidence)
        self.assertIn('@"lyrics_route": [NSSet setWithArray:@[@"exact", @"search", @"qq_search", @"qq_lyric", @"positive_cache", @"negative_cache", @"cooldown"]]', log)
        self.assertIn('search ? @"qq_search" : @"qq_lyric"', src)
        self.assertIn('wasQQ ? (qqSearch ? @"qq_search" : @"qq_lyric")', src)
        self.assertIn('Seven fixed routes x two stages', src)
        self.assertIn('@"0.8.50", @"0.8.51"', log)

    def test_qq_network_contract_is_exact_and_bounded(self):
        src = SOURCE.read_text()
        self.assertIn('https://c.y.qq.com/soso/fcgi-bin/client_search_cp', src)
        self.assertIn('https://c.y.qq.com/lyric/fcgi-bin/fcg_query_lyric_new.fcg', src)
        self.assertIn('!url.user.length && !url.password.length && !url.fragment.length', src)
        self.assertIn('application/x-javascript', src)
        self.assertIn('@"text/html"', src)
        self.assertIn('https://y.qq.com/portal/player.html', src)
        self.assertIn('MSLyricsQQTicket(ticket, owner.generation, owner.activeGeneration,', src)
        self.assertIn('owner.qqSearchPending', src)
        self.assertIn('_qqSearchPending = YES;', src)
        self.assertIn('finishQQTimeoutForRoute', src)
        self.assertIn('r.HTTPShouldHandleCookies = NO', src)
        self.assertIn('QQFallbackNativeTests', NATIVE23.read_text())

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
        self.assertIn('#include "minisight_lyrics_20261122/native_client.inc"', native)
        self.assertIn('#include "minisight_lyrics_20261123/native_client.inc"', native)
        self.assertTrue(NATIVE22.is_file(), "missing prior native include must fail locally, not await Apple CI")
        self.assertIn('search_ambiguous', fixture)
        added = NATIVE23.read_text()
        for call in ('LyricsDiagnosticRoundtripTests', 'ExplicitUnsyncedFallbackTests', 'SearchBoundaryTransportTests', 'SearchCancelDeadlineTests', 'SearchSizeAndRedirectTests', 'QQFallbackNativeTests', 'QQQueuedLifecycleTests', 'QQRejectedInputsTests'):
            self.assertEqual(native.count(call+'('), 1)
            self.assertIn('static void ' + call + '(', added)
        for needle in ('NSURLErrorTimedOut','NSURLErrorNotConnectedToInternet','@503','@429','@302','searchPending','oldTask','@"deadline"','get404/search404/cache'):
            self.assertIn(needle, added)
        self.assertIn('searchPending', NATIVE22.read_text())
        self.assertIn('songmid', added)
        self.assertIn('abc123', added)
        self.assertIn('QQ synthetic line', added)
        self.assertNotIn('@implementation MiniSightLyrics', added)

    def test_plugin_byte_identical(self):
        if not OPTIONS.plugin_root:
            self.skipTest("plugin tree not supplied/present; use --plugin-root for parity check")
        root = Path(OPTIONS.plugin_root)
        plugin = root if (root / "MiniSightLyrics.m").is_file() else root / "debs/MiniSight"
        for name in ("MiniSightLyrics.h", "MiniSightLyrics.m", "MiniSightLog.m"):
            app = (CORE / name).read_bytes(); other = (plugin / name).read_bytes()
            # Version labels differ in independently released hosts. Only that one
            # pre-existing, known enum delta is allowed; QQ routes must be identical.
            if name == "MiniSightLog.m" and app != other:
                label=b'@"0.8.51", @"0.8.52~rhythm-off1"]]'; self.assertEqual(other.count(label),1)
                other = other.replace(label,b'@"0.8.51"]]')
            self.assertEqual(app, other, name)
        for local in (NATIVE, NATIVE22, NATIVE23, DATA, PORTABLE, Path(__file__).resolve()):
            relative = local.relative_to(ROOT)
            self.assertEqual(local.read_bytes(), (plugin / relative).read_bytes(), str(relative))


class PortableProductionPolicyTests(unittest.TestCase):
    def test_verbatim_c_policy_and_compiled_mutants(self):
        compiler = shutil.which('cc') or shutil.which('clang')
        self.assertIsNotNone(compiler, 'a host C compiler is required for portable policy checks')
        source = SOURCE.read_text()
        policy = source.split('// BEGIN LYRICS PORTABLE POLICY', 1)[1].split('// END LYRICS PORTABLE POLICY', 1)[0]
        prelude = '#include <stdbool.h>\n#include <stddef.h>\n#include <stdint.h>\n#include <math.h>\n#include <float.h>\n'
        mutations = {
            'network-may-search': ('return !failed && !search && !attempted', 'return (!failed || failed) && !search && !attempted'),
            'recursive-search': ('!search && !attempted', '(!search || search) && (!attempted || attempted)'),
            'no-unsynced-rescue': ('status == 200 && validatedUnsynced', 'status == 201 && validatedUnsynced'),
            'all-200-may-search': ('status == 200 && validatedUnsynced', 'status == 200 && (validatedUnsynced || !validatedUnsynced)'),
            'cache-rejected': ('status == 200 && !rejected', 'status == 200 && (!rejected || rejected)'),
            'nearest-tie-accepted': ('equivalent[i] != equivalent[best]', 'equivalent[i] == equivalent[best]'),
            'duration-too-loose': ('delta > 2.0', 'delta > 3.0'),
            'deadline-inclusive': ('now < deadline', 'now <= deadline'),
            'qq-preempt-primary': ('return lrclibSearch && !attempted', 'return (lrclibSearch || !lrclibSearch) && !attempted'),
            'qq-any-200': ('status == 200 && confirmedMissing', 'status == 200 && (confirmedMissing || !confirmedMissing)'),
            'qq-old-ticket': ('captured == current && captured == active', 'current == active && captured != 0'),
            'qq-mid-inversion': ('!MSLyricsASCIIAlpha(bytes[i]) && !MSLyricsASCIIDigit(bytes[i])', 'MSLyricsASCIIAlpha(bytes[i]) || MSLyricsASCIIDigit(bytes[i])'),
            'qq-extra-separator': ("p[--end] != ')'", "p[--end] == ')'"),
        }
        with tempfile.TemporaryDirectory(prefix='minisight-lyrics-c-') as tmp:
            directory = Path(tmp)
            for name, mutation in [('production', None)] + list(mutations.items()):
                text = policy
                if mutation:
                    old, new = mutation
                    self.assertIn(old, text, name + ' must actually mutate production C')
                    text = text.replace(old, new)
                case = directory / (name + '.c')
                case.write_text(prelude + text + PORTABLE.read_text())
                binary = directory / name
                compiled = subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic', str(case), '-lm', '-o', str(binary)], capture_output=True, text=True, timeout=60)
                self.assertEqual(compiled.returncode, 0, name + compiled.stdout + compiled.stderr)
                result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
                if not mutation:
                    self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                    print(result.stdout.strip())
                else:
                    self.assertEqual(result.returncode, 1, name + result.stdout + result.stderr)
                    self.assertIn('FAIL portable', result.stderr, 'crash is not an assertion-based mutation kill')
                    print('REJECT compiled C mutant:', name)


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
                   str(source), str(NATIVE), str(CORE / "MiniSightLog.m"), "-framework", "Foundation", "-o", str(binary)]
        result = subprocess.run(command, text=True, capture_output=True, timeout=90)
        if result.returncode:
            raise AssertionError("Native compilation failed (not skipped):\n" + result.stdout + result.stderr)
        return binary

    def run_fixture(self, binary):
        return subprocess.run([str(binary), str(DATA)], capture_output=True, text=True, timeout=90)

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
            "blank": ("if (!line.text.length) return nil;", "return line.text;"),
            "body_cap": ("MSLyricsMaxBytes = 1024 * 1024;", "MSLyricsMaxBytes = 2 * 1024 * 1024;"),
            "unsynced_rescue": ('[reason isEqualToString:@"no_synced_lyrics"]', 'NO'),
            "callback_deadline": ('!MSLyricsDispatchReady(NSProcessInfo.processInfo.systemUptime, _deadline)', 'NO'),
            "search_artist": ('[artist isEqualToString:track.artist]', 'YES'),
            "search_ambiguity": ('equivalent[i] != equivalent[best]', 'false'),
            "qq_old_song_timer": ('captured == current && captured == active', 'current == active && captured != 0'),
            "qq_conflicting_echo": ('obj[@"songmid"] && ![obj[@"songmid"] isEqual:_qqSongMID]', 'obj[@"songmid"] && NO'),
            "qq_fractional_service_code": ('[code isEqualToNumber:@0]', '[code integerValue] == 0'),
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
    parser.add_argument("--require-native", action="store_true", default=OPTIONS.require_native)
    parser.add_argument("--portable-only", action="store_true", help="Run source and portable C checks only; do not attempt Foundation tests")
    OPTIONS, remaining = parser.parse_known_args()
    if OPTIONS.portable_only and OPTIONS.require_native:
        parser.error("portable-only cannot replace required native tests")
    if OPTIONS.portable_only:
        print("Apple Foundation explicitly NOT run (--portable-only)", flush=True)
        del NativeFoundationTests
    print("Source checks are conformance only; native SKIP is NOT runtime success.", flush=True)
    unittest.main(argv=[__file__] + remaining, verbosity=2)
