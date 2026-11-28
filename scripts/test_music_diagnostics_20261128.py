#!/usr/bin/env python3
"""Portable regression/source mutation checks; NOT ObjC/iOS execution proof."""
from pathlib import Path
import re, subprocess, tempfile, unittest
ROOT=Path(__file__).resolve().parents[1]
def core():
 return ROOT/'src/ios/MiniSightCore' if (ROOT/'src').exists() else ROOT

def failures(s,l):
 out=[]
 def need(ok,label):
  if not ok: out.append(label)
 poll=s.split('- (void)pollAt:',1)[1].split('- (void)rejectPlayer:',1)[0]
 reset='_readStage = 0; _pidRead = 0; ++_readGeneration;'
 resolve='NSString *player = MSMusicResolvePlayer(&playerReason);'
 need(reset in poll and poll.index(reset)<poll.index(resolve),'reset before resolve')
 need('NSUInteger request = _readGeneration, ticket = ++_readTicket;' in poll,'one generation per attempt')
 need('_playerOrigin = @"direct"; _playerKind = @"unknown";' in poll and poll.index('_playerOrigin = @"direct";')<poll.index(resolve),'direct starts clean')
 need('_playerKind = MSMusicPlayerKind(player, playerReason);' in poll,'direct category')
 need('if (fallback) {\n        _playerOrigin = @"pid"; _playerKind = @"unknown";' in poll,'real fallback origin')
 need('self->_playerKind = MSMusicPlayerKind(resolved, reason);\n        if (!resolved)' in poll,'PID rejection category')
 need('BOOL fallback = MSMusicUsePIDSource(MSMusicPID != NULL);' in poll,'MR identity has priority when available')
 need('if (!fallback && player.length && _source.length' in poll,'stale direct hint cannot revoke MR candidate')
 need('MSMusicPIDMatches(self->_pidRead, pid, [player isEqual:lastPlayer])' in s,'actual unknown/changed MR source still denied')
 missing=s.split('static BOOL MSMusicMissingSource(',1)[1].split('static double MSMusicNumber',1)[0]
 need('unsupported_player' not in missing,'unsupported cannot fallback')
 identity=s.split('- (void)identityEvidence:',1)[1].split('- (void)conflictEvidence:',1)[0]
 key=identity.split('NSArray *key = ',1)[1].split(';',1)[0]
 need('_playerOrigin ?: @"unknown"' in key and '_playerKind ?: @"unknown"' in key,'source/category in throttle key')
 need('< 60.) return;' in identity,'60 second coalescing retained')
 for f,iv in [('player_origin','_playerOrigin'),('player_kind','_playerKind')]:
  need('@"'+f+'": '+iv+' ?: @"unknown"' in identity,'emit '+f)
  need(l.count('@"'+f+'"')==2,'register enum and key '+f)
 kind=s.split('static NSString *MSMusicPlayerKind(',1)[1].split('static NSString *MSMusicResolvePlayer',1)[0]
 returns=set(re.findall(r'return @"([^"]+)"',kind))
 need(returns=={'netease','qq','kugou','kuwo','apple'},'five fixed supported categories')
 need('? @"unsupported" : @"unknown";' in kind,'controlled failure categories')
 need('return player' not in kind and 'NSLog' not in kind,'no raw identity output')
 return out

class DiagnosticTests(unittest.TestCase):
 def setUp(self):
  self.s=(core()/'MiniSightMusicMonitor.m').read_text(); self.l=(core()/'MiniSightLog.m').read_text()
 def test_contract(self): self.assertEqual(failures(self.s,self.l),[])
 def test_reset_compiles_and_executes_verbatim_C(self):
  reset=re.search(r'    (_readStage = 0; _pidRead = 0; \+\+_readGeneration;)',self.s).group(1)
  body='#include <assert.h>\nint main(void){ unsigned long _readStage=4,_readGeneration=218; int _pidRead=123;\n'+reset+'\nassert(_readStage==0 && _readGeneration==219 && _pidRead==0);\n'+reset+'\nassert(_readStage==0 && _readGeneration==220 && _pidRead==0); return 0;}'
  with tempfile.TemporaryDirectory() as t:
   p=Path(t); (p/'reset.c').write_text(body)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'reset.c'),'-o',str(p/'reset')],check=True)
   subprocess.run([str(p/'reset')],check=True)
 def test_every_fix_has_negative_control(self):
  mutations=[('_readStage = 0; _pidRead = 0; ++_readGeneration;','_pidRead = 0;'),
   ('NSUInteger request = _readGeneration, ticket = ++_readTicket;','NSUInteger request = ++_readGeneration, ticket = ++_readTicket;'),
   ('_playerOrigin = @"direct"; _playerKind = @"unknown";','_playerKind = @"unknown";'),
   ('_playerKind = MSMusicPlayerKind(player, playerReason);',''),
   ('_playerOrigin = @"pid"; _playerKind = @"unknown";','_playerOrigin = @"direct";'),
   ('self->_playerKind = MSMusicPlayerKind(resolved, reason);',''),
   ('_playerOrigin ?: @"unknown", _playerKind ?: @"unknown"]','@"unknown"]'),
   ('now - [_identityEvidenceAt[reason] doubleValue] < 60.) return;','now - [_identityEvidenceAt[reason] doubleValue] < 0.) return;'),
   ('BOOL fallback = MSMusicUsePIDSource(MSMusicPID != NULL);','BOOL fallback = !player && MSMusicPID;'),
   ('return @"qq";','return player;')]
  for old,new in mutations:
   with self.subTest(old=old):
    self.assertEqual(self.s.count(old),1)
    self.assertTrue(failures(self.s.replace(old,new),self.l))
 def test_logger_negative_controls(self):
  for field in ['player_origin','player_kind']:
   broken=self.l.replace('@"'+field+'": [NSSet','@"arbitrary": [NSSet')
   self.assertTrue(failures(self.s,broken))
 def test_original_native_unsupported_negative_retained(self):
  fixture=(ROOT/'scripts/fixtures/minisight_music_monitor_20261116/runtime.m').read_text()
  self.assertIn('explicitly unsupported never falls back to PID',fixture)
  self.assertIn('unsupported poll resets stale stage/PID',fixture)
  self.assertIn('PID mapping rejection is not mislabeled',fixture)

if __name__=='__main__': unittest.main(verbosity=2)
