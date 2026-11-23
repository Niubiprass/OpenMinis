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
    double low=1.,high=-1.;
    for(int i=0;i<6400;i++) {
        double t=i/1000.;
        MSPetMusicCue cue=MSPetMusicCueAt(t);
        int row=MSPetPoseAtlasRowAt(MSPetPoseMusic,t),col=MSPetPoseColumnAt(MSPetPoseMusic,t);
        CHECK(cue.pose==MSPetPoseIdle && row==0 && col>=0 && col<6);
        CHECK(cue.pulse>=0. && cue.pulse<=1.);
        MSPetMusicPresentation p=MSPetMusicPresentationAt(t);
        CHECK(isfinite(p.angle) && fabs(p.angle)<=.125 && p.bob>=-.018-1e-12 && p.bob<=0.);
        low=fmin(low,p.angle);high=fmax(high,p.angle);
        MSPetMusicPresentation repeat=MSPetMusicPresentationAt(t+1.2);
        CHECK(fabs(p.angle-repeat.angle)<1e-10 && fabs(p.bob-repeat.bob)<1e-10);
        MSPetMusicPresentation next=MSPetMusicPresentationAt(t+.001);
        CHECK(fabs(next.angle-p.angle)<.001 && fabs(next.bob-p.bob)<.001);
    }
    CHECK(low<-.09 && high>.09); // Rest-only presentation helper; real host walk/hop is covered by pet_paths.
    CHECK(MSPetPoseColumnAt(MSPetPoseMusic,3.85)>0);
    CHECK(MSPetPoseColumnAt(MSPetPoseMusic,.8)==0);
    CHECK(MSPetMusicInterpolate(12,.25,true)==12.25 && MSPetMusicInterpolate(12,.25,false)==12);
    CHECK(MSPetMusicInterpolate(1,-1,true)==1 && MSPetMusicInterpolate(1,300,true)==6);
    double ages[]={0.,.379,.38,.939,.94,1.479,1.48,2.159,2.16,NAN};
    int stages[]={1,1,2,2,3,3,4,4,0,0};
    for(unsigned i=0;i<10;i++) CHECK(MSPetLandingStageAt(ages[i])==stages[i]);
    for(int stage=0;stage<=4;stage++) CHECK(MSPetLandingColumn(stage,.5)==0);
    double dizzyMax=0.;
    CHECK(MSPetLandingPresentationAt(0.).angle==0.);
    for(int i=0;i<2160;i++) {
        double t=i/1000.;
        MSPetLandingPresentation p=MSPetLandingPresentationAt(t),next=MSPetLandingPresentationAt(t+.001);
        CHECK(isfinite(p.angle) && p.angle>=0. && p.angle<=1.18+1e-12);
        CHECK(p.dizzy>=0. && p.dizzy<=1. && fabs(next.angle-p.angle)<.007);
        dizzyMax=fmax(dizzyMax,p.dizzy);
    }
    CHECK(dizzyMax>.99 && MSPetLandingPresentationAt(.6).angle>1.17);
    CHECK(MSPetLandingPresentationAt(2.16).angle==0. && MSPetLandingPresentationAt(2.16).dizzy==0.);
    double invalid[]={NAN,INFINITY,-1.};
    for(unsigned i=0;i<3;i++) {
        CHECK(MSPetMusicPresentationAt(invalid[i]).angle==0. && MSPetMusicPresentationAt(invalid[i]).bob==0.);
        CHECK(MSPetLandingPresentationAt(invalid[i]).angle==0. && MSPetLandingPresentationAt(invalid[i]).dizzy==0.);
    }
    CHECK(MSPetPoseRestore(MSPetPoseDrag,1,0,0)==MSPetPoseMusic);
    CHECK(MSPetPoseRestore(MSPetPoseMusic,0,0,0)==MSPetPoseIdle);
    CHECK(MSPetPoseRestore(MSPetPoseWave,1,1,0)==MSPetPoseSleep);
    CHECK(MSPetPoseRestore(MSPetPoseWave,1,0,1)==MSPetPoseWake);
    CHECK(MSPetPoseAtlasRowAt(MSPetPoseMusic,NAN)==0);
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
    puts("PASS actual C: 6400 in-place music frames, continuous recovery, heavy/light contact and cancel");
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
        for reason in ('media_controller_unavailable', 'no_active_player', 'player_bundle_missing',
                       'unsupported_player', 'netease_player_selected', 'supported_player_selected'):
            self.assertIn('@"' + reason + '"', monitor)
        resolver=re.search(r'static NSString \*(MSMusic\w+)\(NSString \*\*reason\)', monitor)
        self.assertIsNotNone(resolver)
        name=resolver.group(1)
        self.assertIn(name+'(&playerReason)', monitor)
        self.assertNotRegex(monitor, r'static NSString \*'+name+r'\(void\)')
        self.assertIn('[app isKindOfClass:NSString.class] ? app : MSMusicObject(app, @"bundleIdentifier")', monitor)
        for marker in ('recordLyricsVisible:YES', 'recordLyricsVisible:NO', '@"lyrics_no_space"', '@"empty_line"', '_lyricsReasonEvidence'):
            self.assertIn(marker,effects)
        self.assertNotIn('static BOOL lastVisible',effects)
        if ROOT!=CORE:
            reader=(ROOT/'src/ios/MiniSightInAppRuntime.swift').read_text()
            for marker in ('player_stage', 'reason_detail', 'lyrics_received','self.line = nextLine','pet.lyricsLine = parent.lyricsLine'):
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
        renderer=definition(s,'- (void)applySpriteFrame')
        for marker in ('_effects.musicPosition','MSPetPoseAtlasRowAt((int)_state, position)', 'MSPetPoseColumnAt((int)_state, position)'):
            self.assertIn(marker,renderer)
        live=(CORE/'MiniSightLiveliness.h').read_text(); gravity=(CORE/'MiniSightGravity.h').read_text()
        pet_header=CORE/'MiniSightPet.h'
        self.assertNotIn('sit/sleep/wake',pet_header.read_text().lower())
        self.assertIn('failed',pet_header.read_text().lower())
        self.assertIn('(void)stage; (void)age; return 0;', live)
        self.assertIn('p.angle = .085 * sin(phase) + .045 * sin(2. * phase);',live)
        self.assertIn('p.bob = -.018 *',live)
        effects=(CORE/'MiniSightPetEffects.m').read_text()
        tick=definition(effects.split('@implementation MiniSightPetEffects',1)[1],'- (void)tick:')
        for marker in ('MSPetMusicCueAt(dance ? self.musicPosition : -1.)', 'MSPetMusicPresentationAt(position)', 'MSPetLandingPresentationAt(now - _recoveryBegan)', 'MSPetFitVisualTransform'):
            self.assertIn(marker,tick)
        dance=tick.split('    if (dance) {',1)[1].split('    MSPetLandingPresentation recoveryMark',1)[0]
        self.assertIn('x = 0.;',dance)
        self.assertIn('sx = 1.; sy = 1.;',dance)
        self.assertNotIn('pet.center =',dance)
        self.assertNotIn('MSPetPoseJump',dance)
        self.assertNotIn('MSPetPoseWalk',dance)
        self.assertNotIn('return @"music";',definition(effects,'- (NSString *)currentRole'))
        playing=definition(s,'- (void)setMusicPlaying:')
        self.assertIn('_motionActive && !_physicsMotion && !_dragging',playing)
        self.assertIn('[self cancelMotion]',playing)
        self.assertIn('[self reconcilePlayback]',playing)
        roam=definition(s,'- (void)roamOnce')
        self.assertIn('MSPetMusicTravelAt',roam)
        self.assertIn('[self startMotionTo:MSPetCGPoint(travel.target) jump:travel.jump rest:.25]',roam)
        self.assertIn('(_musicMotion && ![self mayPerformMusicMotion])',definition(s,'- (void)motionTick:'))
        self.assertIn('_musicMotion = NO;',definition(s,'- (void)cancelMotion'))
        recovery=definition(s,'- (void)beginLandingRecoveryWithImpact:')
        self.assertIn('[self setSpriteState:MiniSightPetStateIdle]',recovery)
        self.assertNotIn('MiniSightPetStateSleeping',recovery)
        self.assertIn('_effects.landingRecoveryHeld',definition(s,'- (void)frameTick:'))
        self.assertIn('_dizzyStars.hidden = YES',definition(effects,'- (void)setRunning:'))
        self.assertIn('[_dizzyStars removeFromSuperlayer]',definition(effects,'- (void)invalidate'))
        self.assertIn('++_frameRequest',definition(effects,'- (void)setLandingRecoveryStage:'))
        self.assertIn('MSPetMusicInterpolate',definition(effects,'- (NSTimeInterval)musicPosition'))
        self.assertIn('MSPetLandingStageAt',definition(s,'- (void)frameTick:'))
        host=(CORE/'Tweak.xm' if ROOT==CORE else ROOT/'src/ios/MiniSightInAppRuntime.swift').read_text()
        self.assertIn('motionTime',host)
        self.assertEqual(host.count('Pet.musicPosition = MiniSightSnapshotMotionPosition(snapshot)' if ROOT==CORE else 'pet.musicPosition = parent.musicAnchor?.current'),2)
        self.assertNotIn('saveShown',definition(s,'- (void)beginLandingRecoveryWithImpact:'))

class Portable(unittest.TestCase):
    def test_production_policies_and_compiled_mutants(self):
        compiler=shutil.which('cc') or shutil.which('clang');self.assertIsNotNone(compiler)
        live=(CORE/'MiniSightLiveliness.h').read_text(); gravity=(CORE/'MiniSightGravity.h').read_text()
        variants={'baseline':(live,gravity),
          'music-walk-row':(live.replace('MSPetMusicCue cue = {MSPetPoseIdle, 0u, 0.};','MSPetMusicCue cue = {MSPetPoseWalkRight, 0u, 0.};'),gravity),
          'music-frozen-sway':(live.replace('p.angle = .085 * sin(phase) + .045 * sin(2. * phase);','p.angle = 0.;'),gravity),
          'frozen-clock':(live.replace('playing ? MSPetFiniteClamp(age, 0., 5.)', 'playing ? 0.*age'),gravity),
          'skip-dizzy':(live.replace('elapsed < .94 ? 2', 'elapsed < .94 ? 3'),gravity),
          'stepped-topple':(live.replace('p.angle = 1.18 * MSPetSmoothUnit(age / .27);','p.angle = 1.18;'),gravity),
          'hard-floor-keeps-bounce':(live,gravity.replace('body->velocity = (MSPoint){0.,0.};\n    body->active = 0;', 'body->velocity = (MSPoint){0.,-1.};\n    body->active = 1;')),
          'light-floor-absorbed':(live,gravity.replace('body->floorImpactVelocity < 720.','body->floorImpactVelocity < -1.'))}
        with tempfile.TemporaryDirectory(prefix='ms-media-policy-') as tmp:
            tmp=Path(tmp);(tmp/'main.c').write_text(C_MAIN)
            shutil.copyfile(CORE/'MiniSightGeometry.h',tmp/'MiniSightGeometry.h')
            for name,(l,g) in variants.items():
                if name!='baseline': self.assertNotEqual((l,g),(live,gravity),name+' did not change production')
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
