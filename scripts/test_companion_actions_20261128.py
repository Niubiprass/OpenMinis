#!/usr/bin/env python3
"""Current-character companion read-only integration; portable C is not UIKit."""
from pathlib import Path
import re,unittest,subprocess,tempfile,hashlib,json
R=Path(__file__).resolve().parents[1];C=R/'src/ios/MiniSightCore' if (R/'src/ios/MiniSightCore').exists() else R
HEAD=C/'MiniSightCompanionActions.h';RESOURCE=C/'MiniSightResources.m'
def sourcechecks(s,r):
 assert 'sameImage && schemaOK && single && layout == 3 && variant == 0 && !explicitPack && !usingDefault' in s
 assert 'if(!png||![MSCompanionSHA(png) isEqual:character])return nil;' in s
 assert '[b[@"pack_manifest_sha256"] isEqual:MSCompanionSHA(manifest)]' in s
 assert 'MSCompanionDirectory(path)' in s and 'O_NOFOLLOW' in s and 'AT_SYMLINK_NOFOLLOW' in s
 assert 'st_mtimespec.tv_nsec' in s and 'st_ctimespec.tv_nsec' in s and 'st.st_ino' in s
 assert 'if([cachedIdentity isEqual:identity])' in s
 assert '[metadata[@"layoutVersion"] isEqual:@3]' in s
 assert 'metadata[@"actionPack"] != nil' in s
 assert 'companionActionManifestWithContainer:' in r
 assert 'MSCompanionManifest(container, metadata, NO)' in r
 for token in ['writeToFile:', 'writeToURL:', 'MSBridgeWrite(', 'setObject:', 'activate(', 'replaceCurrent(', 'contentsOfURL:']:
  assert token not in s,'readonly header must not '+token
 if 'Tweak.xm' in [p.name for p in C.iterdir()]:
  assert 'if (!usingDefault && atlas && !action)' in r and 'MSCompanionManifest(container,petMeta,NO)' in r
 return True
class Checks(unittest.TestCase):
 def test_readonly_integration(self):sourcechecks(HEAD.read_text(),RESOURCE.read_text())
 def test_real_production_C_all_128_states(self):
  text=HEAD.read_text();f=text[text.index('static inline bool MSCompanionEligible('):text.index('static NSString *MSCompanionRoot')]
  cases='''int main(void){for(unsigned n=0;n<128;n++){bool a=n&1,b=n&2,c=n&4,d=n&8,e=n&16,f=n&32,g=n&64;assert(MSCompanionEligible(a,b,c,d?3:1,e?0:1,f,g)==(a&&b&&c&&d&&e&&!f&&!g));}return 0;}'''
  with tempfile.TemporaryDirectory(prefix='companion-policy-') as d:
   p=Path(d);(p/'s.c').write_text('#include <stdbool.h>\n#include <assert.h>\n'+f+cases)
   subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(p/'s.c'),'-o',str(p/'run')],check=True,timeout=30)
   subprocess.run([str(p/'run')],check=True,timeout=10)
 def test_safety_mutants_rejected(self):
  s=HEAD.read_text();r=RESOURCE.read_text();sourcechecks(s,r)
  variants=[('!explicitPack && !usingDefault','true'),('if(!png||![MSCompanionSHA(png) isEqual:character])return nil;',''),('[b[@"pack_manifest_sha256"] isEqual:MSCompanionSHA(manifest)]','YES'),('O_NOFOLLOW','0'),('st_ctimespec.tv_nsec','st_ctimespec.tv_sec'),('[metadata[@"layoutVersion"] isEqual:@3]','YES')]
  for old,new in variants:
   with self.subTest(mutation=old):
    self.assertIn(old,s)
    with self.assertRaises(AssertionError):sourcechecks(s.replace(old,new),r)
 def test_cancel_switch_failure_and_diagnostics(self):
  s=(C/'MiniSightPetEffects.m').read_text()
  def check(s):
   switch=s.split('- (void)setActionManifestPath:',1)[1].split('- (void)loadManifestGeneration:',1)[0]
   assert '++_generation; ++_frameRequest; _framePending = NO;' in switch
   assert '_dailyActionOwned = NO;' in switch and '_lastDailyClip = nil;' in switch
   assert '[self restorePoster];' in switch and '[_library purgeFrames]; _library = nil;' in switch
   assert 'generation != self->_generation || request != self->_frameRequest || !self->_running' in s
   cancel=s.split('- (void)cancelDailyAction {',1)[1].split('- (void)tick:',1)[0]
   assert 'if (!_dailyActionOwned) return;' in cancel
   assert 'Another role already took over.' in cancel
   assert '++_frameRequest; _framePending = NO;' in cancel
   assert '[self restorePoster];' in cancel and '[self chooseRole];' in cancel
   assert 'MSDiagEvent(@"pet", @"load", @"failed"' in s and 'MSDiagEvent(@"pet", @"load", @"ok"' in s
   assert 'generation != self->_generation) return;' in s
  check(s)
  for old in ['++_generation; ++_frameRequest; _framePending = NO;', 'request != self->_frameRequest || ', 'if (!_dailyActionOwned) return;', 'MSDiagEvent(@"pet", @"load", @"failed"']:
   self.assertIn(old,s)
   with self.assertRaises(AssertionError):check(s.replace(old,''))
 def test_app_follows_same_readonly_interface(self):
  if not (R/'src/ios/MiniSightInAppRuntime.swift').exists():self.skipTest('App interface is checked by App tree')
  s=(R/'src/ios/MiniSightInAppRuntime.swift').read_text();portion=s.split('static var actionManifestPath: String?',1)[1].split('static var petIdentity:',1)[0]
  self.assertIn('value["actionPack"] == nil',portion)
  self.assertIn('MiniSightResources.companionActionManifest(container: containerPath, metadata: value)',portion)
  self.assertNotIn('activate',portion);self.assertNotIn('replaceCurrent',portion)
if __name__=='__main__':unittest.main(verbosity=2)
