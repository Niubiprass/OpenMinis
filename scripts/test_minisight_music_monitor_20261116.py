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
import sys
import tempfile
import unittest
import test_minisight_music_host_bridge_20261126 as host_bridge
from test_minisight_music_host_bridge_20261126 import MusicLeasePortableTests, MusicHostSourceTests, MusicHostNativeTests

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
        'track compatibility sandwich': 'MSMusicTrackIdentityCompatible(first, last, player)',
        'timer invalidation retained': '[_timer invalidate]; _timer = nil;',
        'exact track signature': '[firstTrack.cacheKey isEqualToString:lastTrack.cacheKey]',
        'stable cached lyrics survive missing ID': 'if (identifier.length) self->_identifier = [identifier copy];',
        'partial metadata does not fetch old track': 'self->_lyrics && track && self->_track && self->_progressAvailable',
        'request requires current metadata': 'self->_lyrics && track && self->_track && self->_progressAvailable',
        'event coalescing': 'if (_eventQueued) return;',
        'metadata-only hint': '[note.name isEqualToString:metadataName]',
        'bounded evidence lease': 'now - validAt <= 1.',
        'candidate absolute expiry': '_candidateUntil = MSMusicNow() + 3.;',
        'expiry rejection': '[self discardCandidate:@"candidate_expired"];',
        'apply expiry before reuse': 'if (self->_candidateUntil > 0. && !MSMusicCandidateAlive(received, self->_candidateUntil))',
        'confirmed stop immediate': '[self discardCandidate:@"confirmed_stop"];',
        'complete candidate consumption': 'if (track) self->_candidateUntil = 0.;',
        'positive PID rejection fence': 'if (self->_pidRead > 0 && self->_track) self->_verifiedPID = self->_pidRead;',
        'known direct switch': 'if (!fallback && player.length && _source.length && ![_source isEqualToString:player]) {',
        'unverified new source hidden': '_source = nil; _playerIdentified = NO;',
        'pause immediate hide': 'if (playing != 1) [self beginPause];',
        'pause candidate not destruction': '[self beginCandidate:@"confirmed_pause"];',
        'no metadata stop': 'if (playing != 1 && !hasMetadata)',
        'stage one conflict': '[self discardCandidate:@"metadata_conflict"];',
        'identity diagnostics': '@"identity_epoch": @(_identityEpoch)',
        'no false fresh PID0': 'PID0 is unknown, NOT a confirmed stop and NOT a fresh sample.',
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
        'reference time': 'age <= progressTrack.duration + 3.',
        'finite duration continuity': 'return isfinite(first) && isfinite(last) && fabs(first - last) <= 1.0;',
        'epsilon requires successful timeline': 'return hasTimeline && MSMusicTrackConflictMask(firstTrack, lastTrack) == 0 &&',
        'epsilon retains ID fence': '!(firstID.length && lastID.length && ![firstID isEqualToString:lastID]);',
        'fixed track anchor assignment': 'if (!self->_track) {\n                    self->_track = track;',
        'fixed progress anchor': 'MiniSightLyricsTrack *progressTrack = track && self->_timeline ? self->_track : track;',
        'first read anchor': '!MSMusicTrackContinuity(self->_track, self->_identifier, firstTrack, MSMusicIdentifier(first), self->_timeline != nil, self->_fetching)',
        'apply read anchor': 'track, identifier, self->_timeline != nil, self->_fetching)) || conflictingPartial;',
        'double read progress continuity': 'BOOL sameTrack = firstTrack && resolvedTrack && MSMusicTrackConflictMask(firstTrack, resolvedTrack) == 0;',
        'real readback': 'MSBridgeRead(container, @"music-state.json", 16384)',
        'diagnostic helper': 'MSMusicDiagnose(',
        'diagnostic snapshot': '@"diagnostics": diagnostics',
        'selected player tracking': '_playerIdentified',
        'progress stage tracking': '_progressAvailable',
        'request completion tracking': '_lyricsRequestFinished',
        'stable incomplete metadata': 'MSMusicTrackIdentityCompatible(first, last, player)',
        'PID int dispatch': '((id (*)(id, SEL, int))objc_msgSend)(controller, sel, pid)',
        'PID NSInteger dispatch': '((id (*)(id, SEL, NSInteger))objc_msgSend)(controller, sel, (NSInteger)pid)',
        'PID runtime classifier': 'MSMusicPIDABIForTypes(sig.methodReturnType, sig.numberOfArguments,',
        'PID controller nil diagnostic': '@"pid_controller_unavailable"',
        'PID method missing diagnostic': '@"pid_method_unavailable"',
        'PID signature diagnostic': '@"pid_signature_rejected"',
        'PID nonpositive diagnostic': '@"player_pid_nonpositive"',
        'PID nil mapping diagnostic': '@"pid_mapping_missing"',
        'PID second mapping': 'NSString *pidReason = nil, *lastPlayer = MSMusicPIDPlayer(pid, &pidReason);',
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
    pause = source.split('- (void)beginPause {', 1)[-1].split('- (NSTimeInterval)motionPosition', 1)[0]
    for token in ('++_trackGeneration;', '[_client cancel]; _fetching = NO;',
                  '[self beginCandidate:@"confirmed_pause"];', '[self publishLine:nil playing:NO force:NO];'):
        if token not in pause:
            result.append('pause fence:' + token)
    if '_timeline = nil' in pause or '_candidateUntil = 0.' in pause:
        result.append('pause destroys successful timeline/deadline')
    poll = source.split('- (void)pollAt:', 1)[-1].split('- (void)rejectPlayer:', 1)[0]
    revoke, read = poll.find('[self discardCandidate:@"player_changed"];'), poll.find('_reading = YES;')
    if revoke < 0 or read < 0 or revoke >= read:
        result.append('known source switch not revoked before native read')
    return result


class SourceTests(unittest.TestCase):
    def test_mr_source_authority_regressions(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('test_music_source_authority_20261128.py'))],
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout + result.stderr)

    def test_pending_continuity_regressions(self):
        result = subprocess.run([sys.executable, str(Path(__file__).with_name('test_minisight_lyrics_pending_20261127.py'))],
                                text=True, capture_output=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout + result.stderr)

    def test_contract(self):
        self.assertEqual(errors((plugin() / 'MiniSightMusicMonitor.m').read_text()), [])

    def test_negative_controls(self):
        source = (plugin() / 'MiniSightMusicMonitor.m').read_text()
        for old, new in (
            ('stage != _readStage', 'NO'),
            ('[_timer invalidate]; _timer = nil;', '_timer = nil;'),
            ('[firstTrack.cacheKey isEqualToString:lastTrack.cacheKey]', 'YES'),
            ('MSMusicTrackIdentityCompatible(first, last, player)', 'NO'),
            ('verified && version == _bridgeVersion', 'verified'),
            ('self->_retryTimes[retryKey] = @(received + 60.);', ''),
            ('_readTimedOut = YES; ++_readGeneration;', '_readTimedOut = YES; _reading = NO;'),
            ('((id (*)(id, SEL, int))objc_msgSend)(controller, sel, pid)', 'nil'),
            ('((id (*)(id, SEL, NSInteger))objc_msgSend)(controller, sel, (NSInteger)pid)', 'nil'),
            ('MSMusicPIDABIForTypes(sig.methodReturnType, sig.numberOfArguments,', 'wrongClassifier('),
            ('now - validAt <= 1.', 'true'),
            ('[self discardCandidate:@"candidate_expired"];', ''),
            ('if (self->_candidateUntil > 0. && !MSMusicCandidateAlive(received, self->_candidateUntil))', 'if (NO)'),
            ('[self discardCandidate:@"confirmed_stop"];', ''),
            ('[self discardCandidate:@"metadata_conflict"];', ''),
            ('if (track) self->_candidateUntil = 0.;', 'self->_candidateUntil = 0.;'),
            ('if (self->_pidRead > 0 && self->_track) self->_verifiedPID = self->_pidRead;', 'self->_verifiedPID = self->_pidRead;'),
            ('if (!fallback && player.length && _source.length && ![_source isEqualToString:player]) {', 'if (NO) {'),
            ('_source = nil; _playerIdentified = NO;', '_source = player; _playerIdentified = YES;'),
            ('if (playing != 1) [self beginPause];', ''),
            ('[self beginCandidate:@"confirmed_pause"];', '[self discardCandidate:@"confirmed_pause"];'),
            ('if (playing != 1 && !hasMetadata)', 'if (NO)'),
            ('++_trackGeneration; ++_identityEpoch; [_client cancel]; _fetching = NO;\n    [self beginCandidate:@"confirmed_pause"];', '[self beginCandidate:@"confirmed_pause"];'),
        ):
            with self.subTest(mutation=old):
                self.assertIn(old, source)
                self.assertTrue(errors(source.replace(old, new)))

    def test_continuity_negative_controls(self):
        source = (plugin() / 'MiniSightMusicMonitor.m').read_text()
        for old, new in (
            ('return isfinite(first) && isfinite(last) && fabs(first - last) <= 1.0;', 'return true;'),
            ('return hasTimeline && MSMusicTrackConflictMask(firstTrack, lastTrack) == 0 &&', 'return MSMusicTrackConflictMask(firstTrack, lastTrack) == 0 &&'),
            ('if (!self->_track) {\n                    self->_track = track;', 'if (YES) {\n                    self->_track = track;'),
            ('MiniSightLyricsTrack *progressTrack = track && self->_timeline ? self->_track : track;', 'MiniSightLyricsTrack *progressTrack = track;'),
            ('!(firstID.length && lastID.length && ![firstID isEqualToString:lastID]);', 'YES;'),
            ('!MSMusicTrackContinuity(self->_track, self->_identifier, firstTrack, MSMusicIdentifier(first), self->_timeline != nil, self->_fetching)', 'NO'),
            ('track, identifier, self->_timeline != nil, self->_fetching)) || conflictingPartial;', 'track, identifier, YES)) || conflictingPartial;'),
            ('BOOL sameTrack = firstTrack && resolvedTrack && MSMusicTrackConflictMask(firstTrack, resolvedTrack) == 0;', 'BOOL sameTrack = YES;'),
        ):
            with self.subTest(mutation=old):
                self.assertEqual(source.count(old), 1)
                self.assertTrue(errors(source.replace(old, new)))

    def test_pid_and_snapshot_production_policy(self):
        source = (plugin() / 'MiniSightMusicMonitor.m').read_text()
        self.assertNotIn('MSMusicAppIDFn', source)
        self.assertEqual(source.count('static NSString *MSMusicResolvePlayer('), 1)
        self.assertNotIn('static NSString *MSMusicPlayer(', source)
        self.assertIn('BOOL fallback = MSMusicUsePIDSource(MSMusicPID != NULL);', source)
        self.assertIn('return pidAPIAvailable ? sampledPID > 0 : sameDirect;', source)
        self.assertIn('!MSMusicPIDMatches(self->_pidRead, pid, [player isEqual:lastPlayer])', source)
        self.assertIn('!MSMusicPublishDue(changed, force, MSMusicNow(), _writeAt)', source)
        self.assertIn('@"motionTime": @(motionPosition)', source)
        self.assertNotIn('_motionLogAt', source)
        body = source.split('// BEGIN MUSIC SAMPLE POLICY',1)[1].split('\n',1)[1].split('// END MUSIC SAMPLE POLICY',1)[0]
        cases = """int main(void){
            assert(MSMusicPIDMatches(5,5,true)); assert(!MSMusicPIDMatches(5,6,true));
            assert(!MSMusicPIDMatches(5,5,false)); assert(!MSMusicPIDMatches(0,0,true));
            for(int i=0;i<8;++i) assert(!MSMusicPublishDue(false,false,100+i*.25,100));
            assert(MSMusicPublishDue(false,false,102,100)); assert(MSMusicPublishDue(true,false,100,100));
            assert(MSMusicPublishDue(false,true,100,100));
            assert(MSMusicMetadataLease(true,true,101.,100.));
            assert(!MSMusicMetadataLease(true,true,101.001,100.));
            assert(!MSMusicMetadataLease(false,true,100.,100.));
            assert(!MSMusicMetadataLease(true,false,100.,100.));
            assert(!MSMusicMetadataLease(true,true,99.,100.));
            assert(!MSMusicMetadataLease(true,true,100.,0.));
            assert(MSMusicCandidateAlive(103.,103.));
            assert(!MSMusicCandidateAlive(103.001,103.));
            assert(!MSMusicCandidateAlive(100.,0.));
            assert(MSMusicNextRhythmGeneration(0,true,false,true) == 1); }\n"""
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp)/'cases'
            subprocess.run(['cc','-std=c11','-x','c','-Wall','-Wextra','-Werror','-pedantic','-o',str(binary),'-'],input='#include <assert.h>\n#include <stdbool.h>\n'+body+cases,text=True,check=True)
            subprocess.run([str(binary)],check=True)

    def test_same_track_progress_group_policy(self):
        source = (plugin() / 'MiniSightMusicMonitor.m').read_text()
        body = source.split('// BEGIN MUSIC PROGRESS POLICY', 1)[1].split('// END MUSIC PROGRESS POLICY', 1)[0]
        cases = '''int main(void) {
            assert(MSMusicUseFirstProgress(true,true,true,true));
            assert(!MSMusicUseFirstProgress(false,true,true,true));
            assert(!MSMusicUseFirstProgress(true,false,true,true));
            assert(!MSMusicUseFirstProgress(true,true,false,true));
            assert(!MSMusicUseFirstProgress(true,true,true,false));
        }\n'''
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / 'progress'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-x','c','-o',str(binary),'-'],
                input='#include <assert.h>\n#include <stdbool.h>\n'+body+cases,text=True,check=True)
            subprocess.run([str(binary)],check=True)
        self.assertIn('for (NSString *field in @[@"ElapsedTime", @"PlaybackRate", @"Timestamp"])', source)

    def test_real_harness_is_not_python_model(self):
        native = FIXTURE.read_text()
        self.assertIn('#import "MiniSightMusicMonitor.m"', native)
        self.assertIn('#define MINISIGHT_MUSIC_MONITOR_TEST 1', native)
        self.assertIn('MSMusicInfo = GetInfo; MSMusicIsPlaying = GetState;', native)
        self.assertIn('MSMusicPID = GetPID', native)
        self.assertIn('maxPending <= 1', native)
        self.assertIn('writes - before <= 2', native)
        self.assertNotIn('https://', native)
        self.assertNotIn('@implementation MiniSightMusicMonitor', native)


class PortablePresentationTests(unittest.TestCase):
    def test_lexical_production_duration_policy(self):
        source = (plugin() / 'MiniSightMusicMonitor.m').read_text()
        body = source.split('// BEGIN MUSIC DURATION POLICY', 1)[1].split('\n', 1)[1].split('// END MUSIC DURATION POLICY', 1)[0]
        cases = '''int main(void) {
            assert(MSMusicPendingContinuity(true,true));
            assert(!MSMusicPendingContinuity(false,true));
            assert(!MSMusicPendingContinuity(true,false));
            assert(!MSMusicPendingContinuity(false,false));
            assert(MSMusicDurationCompatible(261.,261.1316));
            assert(MSMusicDurationCompatible(261.1316,261.2245));
            assert(MSMusicDurationCompatible(261.,262.));
            assert(MSMusicDurationCompatible(262.,261.));
            assert(!MSMusicDurationCompatible(261.,262.000001));
            assert(MSMusicDurationCompatible(261.,261.8));
            assert(MSMusicDurationCompatible(261.8,262.6));
            assert(!MSMusicDurationCompatible(261.,262.6));
            assert(!MSMusicDurationCompatible(NAN,261.));
            assert(!MSMusicDurationCompatible(261.,NAN));
            assert(!MSMusicDurationCompatible(INFINITY,INFINITY));
            assert(!MSMusicDurationCompatible(-INFINITY,261.));
        }\n'''
        with tempfile.TemporaryDirectory(prefix='minisight-duration-') as tmp:
            binary = Path(tmp) / 'duration'
            result = subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-x', 'c', '-o', str(binary), '-', '-lm'], input='#include <assert.h>\n#include <stdbool.h>\n#include <math.h>\n'+body+cases,
                text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            subprocess.run([str(binary)], check=True, timeout=15)

    def test_actual_production_pid_abi(self):
        cc = shutil.which('cc') or shutil.which('clang')
        self.assertIsNotNone(cc, 'Portable C compiler is required')
        with tempfile.TemporaryDirectory(prefix='minisight-pid-abi-') as tmp:
            binary = Path(tmp) / 'player-abi'
            result = subprocess.run([cc, '-std=c11', '-Wall', '-Wextra', '-Werror', '-pedantic',
                '-I', str(plugin()), str(FIXTURE.with_name('player_abi.c')), '-o', str(binary)],
                text=True, capture_output=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            result = subprocess.run([str(binary)], text=True, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PORTABLE PASS:', result.stdout)
            print(result.stdout.strip())

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
                str(plugin() / 'MiniSightLyrics.m'), str(plugin() / 'MiniSightLog.m'), '-framework', 'Foundation', '-o', str(binary)],
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
    host_bridge.REQUIRE_NATIVE = OPTIONS.require_native
    print('Source conformance only; native SKIP is NOT runtime success.', flush=True)
    unittest.main(argv=[__file__] + rest, verbosity=2)
