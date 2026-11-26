#!/usr/bin/env python3
"""Actual lexical production C/ObjC/Swift music host bridge checks; no device or I/O."""
from pathlib import Path
import argparse, math, platform, shutil, subprocess, tempfile, unittest
ROOT = Path(__file__).resolve().parents[1]
CORE = ROOT/'src/ios/MiniSightCore' if (ROOT/'src/ios/MiniSightCore').is_dir() else ROOT
APP = ROOT if (ROOT/'src/ios').is_dir() else ROOT.parents[2]/'app'
PLUGIN = ROOT if (ROOT/'Tweak.xm').is_file() else ROOT.parent/'plugin/debs/MiniSight'
REQUIRE_NATIVE = False

def function(source, name):
    start = source.index('static ', source.rfind('\n', 0, source.index(name)) + 1)
    brace = source.index('{', source.index(name, start)); depth = 1; end = brace + 1
    while depth:
        depth += (source[end] == '{') - (source[end] == '}'); end += 1
    return source[start:end]

def native(test):
    if platform.system() != 'Darwin' or not shutil.which('xcrun'):
        reason = 'Apple Foundation SDK unavailable: host bridge native NOTRUN'
        if REQUIRE_NATIVE: test.fail(reason)
        test.skipTest(reason)
    return subprocess.check_output(['xcrun','--find','clang'],text=True).strip(), subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()

class MusicLeasePortableTests(unittest.TestCase):
    def test_lexical_generation_and_three_compiled_mutants(self):
        source = (CORE/'MiniSightMusicMonitor.m').read_text()
        helper = function(source, 'MSMusicNextRhythmGeneration(')
        cases = '''
int main(void) {
 unsigned long long token=MSMusicNextRhythmGeneration(0,true,false,true);
 assert(token==1);
 for(int heartbeat=0;heartbeat<100;++heartbeat) {
   unsigned long long lyricGeneration=(unsigned long long)heartbeat+10;
   (void)lyricGeneration;
   token=MSMusicNextRhythmGeneration(token,true,true,true); assert(token==1);
 }
 assert(MSMusicNextRhythmGeneration(token,false,true,true)==token);
 assert(MSMusicNextRhythmGeneration(token,false,false,false)==token);
 token=MSMusicNextRhythmGeneration(token,true,false,true); assert(token==2);
 token=MSMusicNextRhythmGeneration(token,true,true,false); assert(token==3);
 assert(MSMusicNextRhythmGeneration(9007199254740991ULL,true,false,true)==1);
 assert(MSMusicNextRhythmGeneration(9007199254740990ULL,true,false,true)==9007199254740991ULL);
 assert(MSMusicNextRhythmGeneration(9007199254740991ULL,true,true,true)==9007199254740991ULL);
 assert(MSMusicNextRhythmGeneration(0,false,false,true)==0);
 return 0;
}
'''
        mutations = {
            'baseline': helper,
            'alwaysincrement': helper.replace('if (!active || (wasActive && sameSource && previous)) return previous;', '(void)active; (void)wasActive; (void)sameSource;'),
            'neverincrement': helper[:helper.index('{')+1]+' (void)active; (void)wasActive; (void)sameSource; return previous; }',
            'sourceignore': helper.replace('wasActive && sameSource && previous', 'wasActive && previous').replace('{\n', '{\n    (void)sameSource;\n',1),
        }
        with tempfile.TemporaryDirectory(prefix='music-lease-') as tmp:
            for name, text in mutations.items():
                with self.subTest(mutation=name):
                    if name != 'baseline': self.assertNotEqual(text,helper)
                    binary=Path(tmp)/name
                    built=subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-x','c','-o',str(binary),'-'],input='#include <assert.h>\n#include <stdbool.h>\n'+text+cases,text=True,capture_output=True,timeout=60)
                    self.assertEqual(built.returncode,0,'compile failure is NOT mutant kill: '+built.stderr)
                    ran=subprocess.run([str(binary)],text=True,capture_output=True,timeout=15)
                    if name=='baseline': self.assertEqual(ran.returncode,0,ran.stderr)
                    else:
                        self.assertNotEqual(ran.returncode,0)
                        self.assertIn('Assertion',ran.stderr)
                    print('ACTUAL C: '+name+' compile=0 run='+str(ran.returncode),flush=True)

class MusicHostSourceTests(unittest.TestCase):
    def test_monitor_evidence_and_lease_source_chain(self):
        s=(CORE/'MiniSightMusicMonitor.m').read_text()
        for text in ['BOOL motionActive = _allowed && _motion && playing;', 'MSMusicNextRhythmGeneration(_rhythmGeneration,', 'motionActive, wasMotionActive, [_snapshot[@"source"] isEqual:source]', '@"rhythmGeneration": @(motionActive ? _rhythmGeneration : 0)', '@"progressAvailable": @((BOOL)measuredProgress)', '@"motionRate": @(isfinite(_rate) ? _rate : 0.)', 'BOOL measuredProgress = motionActive && _progressAvailable && !_awaitingFreshInfo &&', 'nextRhythmGeneration != _rhythmGeneration', '[_snapshot[@"progressAvailable"] boolValue] != measuredProgress', '![_snapshot[@"motionRate"] isEqual:@(_rate)]', '@"generation": @(_trackGeneration)']:
            self.assertIn(text,s)
        part=s.split('BOOL motionActive =',1)[1].split('double motionPosition',1)[0]
        self.assertNotIn('_trackGeneration',part)
        self.assertNotIn('safeLine',part)
    def test_tweak_two_position_call_sites_and_legacy_close(self):
        if not (PLUGIN/'Tweak.xm').is_file(): self.skipTest('standalone App tree: sibling tweak unavailable')
        t=(PLUGIN/'Tweak.xm').read_text(); update=t.split('static void MiniSightUpdateMusic(void)',1)[1].split('static BOOL MiniSightGravityEnabled',1)[0]
        self.assertEqual(update.count('MiniSightRhythmConfigurePetWithPosition('),2)
        self.assertEqual(update.count('MiniSightSnapshotMusicToken(snapshot), MiniSightSnapshotMeasuredPosition(snapshot)'),2)
        self.assertIn('MiniSightRhythmConfigurePet(gMiniSightPet, NO, 0)',t)
        self.assertIn('snapshot[@"rhythmGeneration"] ?: snapshot[@"generation"]',t)

class MusicHostNativeTests(unittest.TestCase):
    def test_actual_tweak_foundation_helpers(self):
        clang,sdk=native(self)
        if not (PLUGIN/'Tweak.xm').is_file(): self.skipTest('standalone App checkout has no tweak source')
        t=(PLUGIN/'Tweak.xm').read_text()
        body=function(t,'MiniSightSnapshotMeasuredPosition(')+'\n'+function(t,'MiniSightSnapshotMusicToken(')
        cases=(ROOT/'scripts/fixtures/minisight_music_monitor_20261116/host_bridge.m').read_text()
        with tempfile.TemporaryDirectory(prefix='music-host-objc-') as tmp:
            src=Path(tmp)/'host.m'; out=Path(tmp)/'host'
            src.write_text('#import <Foundation/Foundation.h>\n#import <CoreFoundation/CoreFoundation.h>\n#include <math.h>\n#include <assert.h>\n'+body+cases)
            p=subprocess.run([clang,'-isysroot',sdk,'-fobjc-arc','-fblocks','-Wall','-Wextra',str(src),'-framework','Foundation','-o',str(out)],text=True,capture_output=True,timeout=90)
            self.assertEqual(p.returncode,0,p.stderr)
            subprocess.run([str(out)],check=True,timeout=15)
    def test_actual_swift_reader_and_host_evidence(self):
        if not shutil.which('swiftc'):
            if REQUIRE_NATIVE: self.fail('swiftc unavailable: Swift bridge NOTRUN')
            self.skipTest('swiftc unavailable: Swift bridge NOTRUN; static checks are not Swift ABI execution')
        p=APP/'src/ios/MiniSightInAppRuntime.swift'
        if not p.is_file(): self.skipTest('standalone plugin has no App reader')
        s=p.read_text(); policy=s.split('// BEGIN MUSIC READER POLICY',1)[1].split('// END MUSIC READER POLICY',1)[0]
        token=s.split('                if let musicGeneration =',1)[1].split('                let defaults =',1)[0]
        token=('if let musicGeneration ='+token).replace('self.rhythmToken','rhythmToken')
        evidence='let positionEvidence ='+s.split('                let positionEvidence =',1)[1].split('                if self.hasPositionEvidence',1)[0]
        wrapper='\nprivate func read(_ raw: [String: Any], _ nextPlaying: Bool) -> (UInt,Bool) {\nlet value: [String: Any]? = raw\nlet snapshot=MiniSightMusicSnapshot.decode(value)!\nvar rhythmToken: UInt=0\n'+token+evidence+'return (rhythmToken,positionEvidence)\n}\n'
        cases=(ROOT/'scripts/fixtures/minisight_music_monitor_20261116/host_bridge.swift').read_text()
        with tempfile.TemporaryDirectory(prefix='music-host-swift-') as tmp:
            src=Path(tmp)/'main.swift'; binary=Path(tmp)/'host'
            src.write_text('import Foundation\nimport CoreFoundation\n'+policy+wrapper+cases)
            p=subprocess.run(['swiftc',str(src),'-o',str(binary)],text=True,capture_output=True,timeout=90)
            self.assertEqual(p.returncode,0,p.stderr)
            subprocess.run([str(binary)],check=True,timeout=15)

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('--require-native',action='store_true'); o,rest=p.parse_known_args(); REQUIRE_NATIVE=o.require_native
    unittest.main(argv=[__file__]+rest,verbosity=2)
