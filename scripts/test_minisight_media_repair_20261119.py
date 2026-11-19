#!/usr/bin/env python3
"""Local source + actual production C + Apple log roundtrip. No device/mic/network.
Native requires Apple tools; --require-native fails closed when unavailable.
"""
from pathlib import Path
import argparse, json, re, shutil, subprocess, sys, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'src/ios/MiniSightCore' if (ROOT/'src/ios/MiniSightCore').is_dir() else ROOT
OPTIONS=argparse.Namespace(require_native=False)

def run(args, **kw):
    return subprocess.run([str(x) for x in args],text=True,capture_output=True,timeout=120,**kw)

def definition(text, signature):
    m=re.search(r'^'+re.escape(signature)+r'[^;{]*\{',text,re.M)
    assert m, signature
    i=text.index('{',m.start())+1; depth=1
    while depth:
        if text[i]=='{': depth+=1
        elif text[i]=='}':depth-=1
        i+=1
    return text[m.start():i]

C_MAIN=r'''
#include "MiniSightLiveliness.h"
#include "MiniSightGravity.h"
#include <stdio.h>
#include <string.h>
#define CHECK(x) do { if(!(x)){fprintf(stderr,"FAIL line %d: %s\n",__LINE__,#x);return 1;} }while(0)
int main(void) {
    CHECK(MSPetPoseAtlasRow(MSPetPoseWake)==5);
    CHECK(MSPetPoseAtlasRow(MSPetPoseDrag)==3);
    CHECK(MSPetPoseAtlasRowAt(MSPetPoseMusic,.1)==3);
    CHECK(MSPetPoseAtlasRowAt(MSPetPoseMusic,1.1)==0);
    CHECK(MSPetPoseAtlasRowAt(MSPetPoseMusic,2.1)==0);
    CHECK(MSPetPoseAtlasRowAt(MSPetPoseMusic,2.2)==3);
    CHECK(MSPetPoseColumnAt(MSPetPoseMusic,.1)==0);
    CHECK(MSPetPoseColumnAt(MSPetPoseMusic,.8)==2);
    CHECK(MSPetPoseColumnAt(MSPetPoseMusic,1.2)==0);
    CHECK(MSPetPoseColumnAt(MSPetPoseMusic,1.9)==4);
    unsigned rows=0;
    const int counts[9]={6,8,8,4,5,8,6,6,6};
    for(int i=0;i<6400;i++) {
        double t=i/1000.;int row=MSPetPoseAtlasRowAt(MSPetPoseMusic,t),col=MSPetPoseColumnAt(MSPetPoseMusic,t);
        CHECK(row>=0 && row<9 && col>=0 && col<counts[row]);rows|=1u<<row;
    }
    CHECK(rows==((1u<<0)|(1u<<3)));
    CHECK(MSPetPoseRestore(MSPetPoseDrag,1,0,0)==MSPetPoseMusic);
    CHECK(MSPetPoseRestore(MSPetPoseMusic,0,0,0)==MSPetPoseIdle);
    CHECK(MSPetPoseRestore(MSPetPoseWave,1,1,0)==MSPetPoseSleep);
    CHECK(MSPetPoseRestore(MSPetPoseWave,1,0,1)==MSPetPoseWake);
    CHECK(MSPetPoseAtlasRowAt(MSPetPoseMusic,NAN)==3);
    CHECK(MSPetPoseAtlasRow(-12)==0 && MSPetPoseAtlasRow(900)==0);
    MSGravityBody body={0};MSRect bounds={0,0,500,600};
    uint64_t token=MSGravityBodyLaunch(&body,bounds,(MSPoint){250,599.9},(MSPoint){30,1100});
    unsigned hits=MSGravityBodyStep(&body,bounds,0,.01,token);
    CHECK(hits&MSGravityHitFloor);CHECK(body.floorImpactVelocity>=720.);
    CHECK(MSGravityBodyAbsorbHardFloor(&body,bounds,hits));
    CHECK(!body.active && body.velocity.x==0 && body.velocity.y==0 && body.position.y==600);
    CHECK(body.floorImpactVelocity>=720.);
    MSGravityBodyCancel(&body);CHECK(body.floorImpactVelocity==0 && !body.active);
    token=MSGravityBodyLaunch(&body,bounds,(MSPoint){250,599.9},(MSPoint){30,200});
    hits=MSGravityBodyStep(&body,bounds,0,.01,token);
    MSGravityBody before=body;
    CHECK(hits&MSGravityHitFloor);CHECK(!MSGravityBodyAbsorbHardFloor(&body,bounds,hits));
    CHECK(!memcmp(&before,&body,sizeof(body))); // light rebound is unchanged
    CHECK(!MSGravityBodyAbsorbHardFloor(&body,bounds,MSGravityHitCeiling));
    puts("PASS actual C: 6400 pose frames, distinct posture rows, heavy/light contact and cancel");
    return 0;
}
'''

class Source(unittest.TestCase):
    def test_music_actual_chain(self):
        monitor=(CORE/'MiniSightMusicMonitor.m').read_text(); effects=(CORE/'MiniSightPetEffects.m').read_text()
        for marker in ('MSMusicResolvedInfo(first, last, player)',
          'self->_lyrics && track && self->_track && self->_progressAvailable', '[_timer invalidate]; _timer = nil;',
          'MSMusicEvidence(@"request"', 'MSMusicEvidence(@"finish"', 'MSMusicEvidence(@"readback"', 'MSMusicEvidence(@"deliver"'):
            self.assertIn(marker, monitor)
        for marker in ('recordLyricsVisible:YES', 'recordLyricsVisible:NO', '@"lyrics_no_space"', '@"empty_line"', '_lyricsReasonEvidence'):
            self.assertIn(marker,effects)
        self.assertNotIn('static BOOL lastVisible',effects)
        if ROOT!=CORE:
            reader=(ROOT/'src/ios/MiniSightInAppRuntime.swift').read_text()
            for marker in ('music_readback','music_stale','lyrics_received','self.line = nextLine','pet.lyricsLine = parent.lyricsLine'):
                self.assertIn(marker,reader)
    def test_log_vocab_and_privacy(self):
        log=(CORE/'MiniSightLog.m').read_text()
        reasons=set(re.findall(r'@"([\w.-]+)"',re.search(r'@"reason": \[NSSet setWithArray:@\[(.*?)\]\]',log).group(1)))
        for reason in ('no_supported_player','metadata_missing','lyrics_fetch','lyrics_timeline','no_synced_lyrics',
          'snapshot_verified','snapshot_write_failed','lyrics_received','lyrics_line','lyrics_no_space','floor_contact','landing_settle','landing_stand','landing_clear','feature_removed'):
            self.assertIn(reason,reasons)
        for feature in ('music','lyrics','pet','name_wake'):self.assertIn('@"'+feature+'"',log)
        self.assertIn('MSDiagMaxBytes = 200 * 1024',log);self.assertIn('MSDiagPending >= 256',log)
        fields=re.search(r'MSDiagKeys = \[NSSet setWithArray:@\[(.*?)\]\]',log).group(1)
        for name in ('title','artist','lyric','audio','url','credential'):self.assertNotIn('@"'+name+'"',fields)
    def test_host_ownership(self):
        s=(CORE/'MiniSightPet.m').read_text()
        self.assertIn('MSGravityBodyAbsorbHardFloor',definition(s,'- (void)motionTick:'))
        self.assertIn('[self clearLandingRecovery]',definition(s,'- (void)cancelMotion'))
        self.assertIn('_landingRecoveryStage != 0 ||',definition(s,'- (MSPetResidentContext)residentContext'))
        self.assertIn('MiniSightPetStateDragging',definition(s,'- (void)beginDraggingAtPoint:'))
        self.assertIn('MiniSightPetStateJumping',definition(s,'- (void)endDraggingCancelled:'))
        self.assertIn('MSPetPoseColumnAt',definition(s,'- (void)advanceSpriteAtTime:'))
        self.assertNotIn('saveShown',definition(s,'- (void)beginLandingRecoveryWithImpact:'))

class Portable(unittest.TestCase):
    def test_production_policies_and_compiled_mutants(self):
        compiler=shutil.which('cc') or shutil.which('clang');self.assertIsNotNone(compiler)
        live=(CORE/'MiniSightLiveliness.h').read_text(); gravity=(CORE/'MiniSightGravity.h').read_text()
        variants={'baseline':(live,gravity),
          'single-pose':(live.replace('return t < 1.1 ? 3 : 0;', '(void)t; return 0;'),gravity),
          'hard-floor-keeps-bounce':(live,gravity.replace('body->velocity = (MSPoint){0.,0.};\n    body->active = 0;', 'body->velocity = (MSPoint){0.,-1.};\n    body->active = 1;')),
          'light-floor-absorbed':(live,gravity.replace('body->floorImpactVelocity < 720.','body->floorImpactVelocity < -1.'))}
        with tempfile.TemporaryDirectory(prefix='ms-media-policy-') as tmp:
            tmp=Path(tmp);(tmp/'main.c').write_text(C_MAIN)
            shutil.copyfile(CORE/'MiniSightGeometry.h',tmp/'MiniSightGeometry.h')
            for name,(l,g) in variants.items():
                (tmp/'MiniSightLiveliness.h').write_text(l);(tmp/'MiniSightGravity.h').write_text(g)
                b=run([compiler,'-std=c11','-Wall','-Wextra','-Werror','-pedantic','-I',tmp,tmp/'main.c','-lm','-o',tmp/'case'])
                self.assertEqual(b.returncode,0,name+b.stderr)
                r=run([tmp/'case']);self.assertEqual(r.returncode,0 if name=='baseline' else 1,name+r.stderr)
                if name=='baseline':print(r.stdout.strip())
                else:self.assertIn('FAIL line',r.stderr);print('REJECT compiled mutant:',name)

class NativeLogs(unittest.TestCase):
    def test_actual_bounded_writer_readback_and_mutants(self):
        if sys.platform!='darwin' or not shutil.which('xcrun'):
            message='Apple native log-roundtrip NOT_RUN: no Apple toolchain'
            if OPTIONS.require_native:self.fail(message)
            self.skipTest(message)
        sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
        clang=subprocess.check_output(['xcrun','--find','clang'],text=True).strip()
        fixture=ROOT/'scripts/fixtures/minisight_media_repair_20261119/log_roundtrip.m'
        original=(CORE/'MiniSightLog.m').read_text()
        variants={'baseline': original,
            'music-feature-dropped': original.replace('@"music", @"lyrics", @"pet", @"name_wake"','@"lyrics", @"pet", @"name_wake"'),
            'reason-dropped': original.replace('@"lyrics_no_space"','@"fixture_no_space"')}
        with tempfile.TemporaryDirectory(prefix='ms-log-roundtrip-') as directory:
            directory=Path(directory)
            for name,source in variants.items():
                self.assertNotEqual(source,original) if name!='baseline' else None
                case=directory/name;case.mkdir()
                (case/'MiniSightLog.m').write_text(source)
                (case/'main.m').write_text(fixture.read_text())
                r=run([clang,'-isysroot',sdk,'-fobjc-arc','-fblocks','-Wall','-Wextra','-Werror=return-type',
                    '-I',case,'-I',CORE,case/'main.m','-framework','Foundation','-o',case/'logger'])
                self.assertEqual(r.returncode,0,name+r.stdout+r.stderr)
                r=run([case/'logger',case/'synthetic-container'])
                self.assertEqual(r.returncode,0 if name=='baseline' else 1,name+r.stdout+r.stderr)
                if name=='baseline':print(r.stdout.strip())
                else:self.assertIn('FAIL log-roundtrip:',r.stderr);print('REJECT compiled log mutant:',name)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--require-native',action='store_true');OPTIONS,rest=parser.parse_known_args()
    unittest.main(argv=[__file__]+rest,verbosity=2)
