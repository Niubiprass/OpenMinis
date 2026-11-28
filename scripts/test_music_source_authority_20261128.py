#!/usr/bin/env python3
"""Actual shared C source policy + integration guards. No MR/UIKit runtime here."""
from pathlib import Path
import unittest,subprocess,tempfile,re
ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'src/ios/MiniSightCore' if (ROOT/'src/ios/MiniSightCore').is_dir() else ROOT
FIX=ROOT/'scripts/fixtures/minisight_music_monitor_20261116/runtime.m'

def block(s,a,b):return s.split(a,1)[1].split(b,1)[0]
def check(s):
 p=block(s,'- (void)pollAt:','- (void)rejectPlayer:')
 a=block(s,'- (BOOL)acceptRead:','- (void)readInfo:')
 m=block(s,'- (void)handleMetadataChange','- (void)handleMediaChange')
 h=block(s,'- (void)handleMediaChange','- (BOOL)refreshPresentation')
 need=lambda v,label: (_ for _ in ()).throw(AssertionError(label)) if not v else None
 need('BOOL fallback = MSMusicUsePIDSource(MSMusicPID != NULL);' in p,'MR consulted even with stale/unsupported SB hint')
 need('if (!fallback && player.length && _source.length' in p,'SB never destroys candidate before MR')
 need('if (!_sourceFromPID || !_playing || _awaitingFreshInfo)' in p,'stable PID poll must not blank each cycle')
 need('self->_source.length && ![self->_source isEqualToString:resolved]' in p,'MR positive source switch clears')
 need('self->_verifiedPID > 0 && self->_verifiedPID != pid' in p,'MR process restart clears')
 need(p.index('MSMusicPIDPlayer(pid, &reason)')<p.index('self->_pidRead = pid;'),'white-listed MR mapping before sample')
 need('MSMusicReadSourceOK(MSMusicPID != NULL, _pidRead, [player isEqualToString:direct])' in a,'MR not vetoed by unrelated SB state')
 need('MSMusicMetadataSourceOK(' in m and '_sourceFromPID, _verifiedPID' in m,'verified metadata continuity')
 need('BOOL awaitPID = MSMusicUsePIDSource(MSMusicPID != NULL);' in h,'notification retains hidden candidate pending MR')
 need('MSMusicPIDMatches(self->_pidRead, pid, [player isEqual:lastPlayer])' in s,'fresh second MR PID and allowlist match')
 need('if (!MSMusicPID && ![player isEqualToString:direct])' in s,'lyric result not falsely discarded by stale SB')
 need('self->_lyricsAwaitingFreshInfo = YES;' in s,'lyric result still needs fresh identity')
 need('static inline bool MSMusicUsePIDSource(bool pidAPIAvailable) { return pidAPIAvailable; }' in s,'MR policy')
 need('return pidAPIAvailable ? sampledPID > 0 : sameDirect;' in s,'no known-SB bypass for MR PID0')
 need('return sameDirect || (fromPID && verifiedPID > 0);' in s,'old identity lease not unconditional')
 for b in ['com.netease.cloudmusic','com.tencent.QQMusic','com.kugou.kugou1002','com.yeelion.kwplayer','com.apple.Music']:
  need('@"'+b+'"' in s,'five player allowlist')
 need('if (![players containsObject:value])' in s,'unknown MR player still denied')
 need('generation != _readGeneration' in a and 'ticket != _readTicket' in a and 'stage != _readStage' in a,'late/duplicate callback fence')
 need('now - validAt <= 1.' in s,'metadata lease never grows')
 need('MSMusicPID' not in block(s,'static bool MSMusicMetadataLease','static bool MSMusicCandidateAlive'),'no live request in lease policy')

C=r'''
int main(void){
 assert(MSMusicUsePIDSource(true));assert(!MSMusicUsePIDSource(false));
 /* Every known, missing or unsupported SB hint consults MR when available. */
 for(int hint=0;hint<3;hint++){
  assert(MSMusicUsePIDSource(true));assert(MSMusicReadSourceOK(true,123,hint==0));
  assert(!MSMusicReadSourceOK(true,0,hint==0));assert(!MSMusicReadSourceOK(true,-1,hint==0));
 }
 assert(MSMusicReadSourceOK(false,0,true));assert(!MSMusicReadSourceOK(false,123,false));
 assert(MSMusicPIDMatches(123,123,true));assert(!MSMusicPIDMatches(123,456,true));
 assert(!MSMusicPIDMatches(123,123,false));assert(!MSMusicPIDMatches(0,0,true));
 assert(MSMusicMetadataSourceOK(false,true,123));assert(!MSMusicMetadataSourceOK(false,true,0));
 assert(!MSMusicMetadataSourceOK(false,false,123));assert(MSMusicMetadataSourceOK(true,false,0));
 assert(MSMusicMetadataLease(true,MSMusicMetadataSourceOK(false,true,123),1000.5,1000.));
 assert(!MSMusicMetadataLease(true,true,1001.001,1000.));assert(!MSMusicMetadataLease(false,true,1000.5,1000.));
 assert(!MSMusicCandidateAlive(1003.001,1003.));assert(MSMusicCandidateAlive(1003.,1003.));
 return 0;
}'''
class Tests(unittest.TestCase):
 def test_actual_source_policy_runs(self):
  s=(CORE/'MiniSightMusicMonitor.m').read_text();code=block(s,'// BEGIN MUSIC SAMPLE POLICY (shared verbatim with portable tests)\n','// END MUSIC SAMPLE POLICY')
  with tempfile.TemporaryDirectory(prefix='mr-source-policy-') as t:
   p=Path(t);f=p/'test.c';f.write_text('#include <assert.h>\n#include <stdbool.h>\n'+code+C)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-unused-function',str(f),'-o',str(p/'run')],check=True,timeout=30)
   subprocess.run([str(p/'run')],check=True,timeout=10)
 def test_real_source_integration(self):check((CORE/'MiniSightMusicMonitor.m').read_text())
 def test_unsafe_source_variants_rejected(self):
  s=(CORE/'MiniSightMusicMonitor.m').read_text();check(s)
  variants=[('BOOL fallback = MSMusicUsePIDSource(MSMusicPID != NULL);','BOOL fallback = !player && MSMusicPID;'),
   ('return pidAPIAvailable ? sampledPID > 0 : sameDirect;','return sampledPID > 0 || sameDirect;'),
   ('if (!fallback && player.length && _source.length','if (player.length && _source.length'),
   ('if (!_sourceFromPID || !_playing || _awaitingFreshInfo)','if (YES)'),
   ('self->_source.length && ![self->_source isEqualToString:resolved]','NO'),
   ('(self->_verifiedPID > 0 && self->_verifiedPID != pid)) {','NO) {'),
   ('MSMusicPIDMatches(self->_pidRead, pid, [player isEqual:lastPlayer])','pid > 0'),
   ('return sameDirect || (fromPID && verifiedPID > 0);','return true;')]
  for a,b in variants:
   with self.subTest(mutation=a):
    self.assertEqual(s.count(a),1)
    with self.assertRaises(AssertionError):check(s.replace(a,b))
 def test_native_positive_and_negative_cases_registered(self):
  f=FIX.read_text()
  for token in ['MR source overrides stale unsupported SB hint','unknown actual MR source remains rejected','known SB cannot bypass MR PID zero','MR stable poll does not hide current lyrics','SB-only unsupported remains rejected without MR API']:
   self.assertIn(token,f)
if __name__=='__main__':unittest.main(verbosity=2)
