#!/usr/bin/env python3
"""Literal producers + actual ObjC/Swift offline behavior, synthetic temp data.
Missing Apple tools: explicit SKIP, --require-native/V64R_REQUIRE_SWIFT=1 fails.
No device, permission, microphone, URLs or media queries. CI must register this.
"""
import argparse, hashlib, importlib.util, json, os, shutil, subprocess, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
IS_APP=(ROOT/'src/ios/MiniSightCore').is_dir()
CORE=ROOT/'src/ios/MiniSightCore' if IS_APP else ROOT
FIX=ROOT/'scripts/fixtures/minisight_shown_name_20261117'
PLUGIN=ROOT.parent.parent/'MiniSight-complete-20261105/debs/MiniSight' if IS_APP else ROOT
APP=ROOT if IS_APP else ROOT.parents[2]/'openminis/minisight-workbuddy-trae-20261112'
SWIFT=APP/'src/ios' if (APP/'src/ios/MiniSightWakeRemote.swift').is_file() else FIX/'swift_sources'
OPTIONS=argparse.Namespace(require_native=os.getenv('V64R_REQUIRE_SWIFT')=='1')
def load(name):
 defpath=ROOT/'scripts'/('test_minisight_'+name+'.py')
 if name=='name_roundtrip_20261116' and not defpath.is_file():defpath=FIX/'native_tools.py'
 spec=importlib.util.spec_from_file_location(name,defpath)
 module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);return module
PRESENT=load('presentation_readback_20261116');ROUND=load('name_roundtrip_20261116')
ROUND.REMOTE=SWIFT/'MiniSightWakeRemote.swift';ROUND.POLICY=SWIFT/'MiniSightWakePolicy.swift'
def extract(text,marker): return PRESENT.extract(text,marker)
def sha(text): return hashlib.sha256(text.encode()).hexdigest()
class Source(unittest.TestCase):
 def test_exact_production_excerpts(self):
  manifest=json.loads((FIX/'PRODUCTION.json').read_text())
  for item in manifest['excerpts']:
   if item['fixture']=='host_producer.inc': continue # retired host; tested by retirement suite, not live producer
   literal=extract((FIX/item['fixture']).read_text(),item['marker'])
   self.assertEqual(sha(literal),item['sha256'])
   for relative in item['sources']:
    if relative.startswith('PLUGIN/'):path=PLUGIN/relative[7:]
    elif relative.startswith('src/ios/MiniSightCore/'):path=CORE/Path(relative).name
    else:path=APP/relative
    if path.is_file(): self.assertEqual(extract(path.read_text(),item['marker']),literal)
    elif relative.startswith('PLUGIN/') or not IS_APP:
     print('SKIP unavailable live cross-tree source parity: pinned literal production evidence retained '+relative)
    else: self.fail('missing actual producer '+str(path))
  for filename,digest in manifest['native_files'].items():
   self.assertEqual(hashlib.sha256((FIX/filename).read_bytes()).hexdigest(),digest)
  for filename in ('MiniSightWakeRemote.swift','MiniSightWakePolicy.swift'):
   if (APP/'src/ios'/filename).is_file():self.assertEqual((APP/'src/ios'/filename).read_bytes(),(FIX/'swift_sources'/filename).read_bytes())
 def test_explicit_shown_only_writer(self):
  if not (APP/'src/ios/MiniSightConfigStore.swift').is_file():self.skipTest('live App store unavailable; pinned literal methods native-tested, not full integration proof')
  store=(APP/'src/ios/MiniSightConfigStore.swift').read_text()
  self.assertNotIn('saveShown',extract(store,'    func persistAll()'))
  self.assertNotIn('saveShown',extract(store,'    func reloadShownFromFile()'))
  self.assertIn('guard loaded, !readingShown',extract(store,'    private func publishShown()'))
  self.assertIn('case MiniSightSettingKey.shown: return MiniSightPetFile.loadShown()',store)
  self.assertIn('readingShown = true',store)
  self.assertNotIn('return true',extract((APP/'src/ios/Views/Settings/MiniSightSettingsView.swift').read_text(),'    static func loadShown()'))
 def test_final_identity_and_safety_fences(self):
  if not (APP/'src/ios/MiniSightInAppRuntime.swift').is_file():self.skipTest('live App final UI/controller integration not mounted; native reader/policy still required')
  activity=(APP/'src/ios/MiniSightInAppRuntime.swift').read_text()
  self.assertIn('(evidence["_minisightShownIdentity"] as? String) == (current["_minisightShownIdentity"] as? String)',activity)
  self.assertNotIn('String(contentsOf: shownURL',activity)
  policy=(APP/'src/ios/MiniSightWakePolicy.swift').read_text()
  self.assertIn('fresh && lockKnown == true && unlocked == false',policy)
  self.assertIn('!c.companionScreenOff && !c.companionSafetyUnknown',policy)
  controller=(APP/'src/ios/MiniSightWakeController.swift').read_text()
  self.assertIn('var backgroundAudioIsLive: Bool { false }',controller)
  self.assertIn('func claimNameWakeVoice(token: String, generation: Int) -> Bool { false }',controller)
  self.assertNotIn('AVAudioEngine()',controller)
  self.assertNotIn('MiniSightWakeEngine()',controller)
 def test_cross_tree_shared_slices_and_real_fixtures(self):
  for directory in [CORE]+([PLUGIN] if PLUGIN.is_dir() and PLUGIN!=CORE else []):
   header=(directory/'MiniSightResources.h').read_text()
   for api in ('NS_SWIFT_NAME(shownEvidence(container:));','NS_SWIFT_NAME(saveShown(_:container:));'):
    self.assertIn(api,header);self.assertIn(api,(FIX/'resources_bridge.h').read_text())
  if PLUGIN.is_dir():
   for filename in ('MiniSightNameWakeState.h','MiniSightShownReadback.h'):
    self.assertEqual((CORE/filename).read_bytes(),(PLUGIN/filename).read_bytes())
   for marker in ('+ (NSDictionary<NSString *, id> *)shownEvidenceWithContainer:', '+ (BOOL)saveShown:'):
    self.assertEqual(extract((CORE/'MiniSightResources.m').read_text(),marker),extract((PLUGIN/'MiniSightResources.m').read_text(),marker))
  for filename in ('shown_main.swift','screen_cases.swift','screen_cases.inc'):
   text=(FIX/filename).read_text();self.assertNotIn('https://',text);self.assertNotIn('AVAudio',text)
  self.assertIn('stale cached ON page exit must not undo menu hide',(FIX/'shown_main.swift').read_text())
  self.assertIn('unknown screen is not trusted locked',(FIX/'screen_cases.swift').read_text())
 def test_actual_roundtrip_entry_uses_public_decoded_state(self):
  expected=ROOT/'scripts/fixtures/minisight_name_roundtrip_20261116' if IS_APP else FIX/'roundtrip_baseline'
  self.assertEqual(ROUND.FIXTURE.resolve(),expected.resolve())
  entry=(ROUND.FIXTURE/'main.swift').read_text()
  import inspect
  runner=inspect.getsource(Native.name)
  self.assertIn('old=ROUND.FIXTURE',runner)
  self.assertIn("main=(old/'main.swift').read_text()",runner)
  self.assertIn('guard let state = MiniSightWakeRemote.decodeState(value)',entry)
  self.assertNotIn('MiniSightWakeRemote.boolean(',entry)
  for field in ('unlocked','allowed','busy','lockKnown','screenKnown','screenOff'):
   self.assertIn('"'+field+'": state.'+field,entry)
  for assertion in ('legacy integer 0/1 semantics','invalid boolean','missing boolean','normalized state cannot grant unsafe listen','legacy integer actual temporary file','state exact schema missing','state exact schema extra'):
   self.assertIn(assertion,entry)
class Native(unittest.TestCase):
 def tools(self,tmp):
  tools,reason=ROUND.apple_toolchain(tmp)
  if not tools:
   message='Apple native shown + host boolean writer/Swift reader NOT executed: '+reason
   if OPTIONS.require_native:self.fail(message)
   self.skipTest(message)
  return tools
 def name(self,tmp,tools,core,mutant=False):
  sdk,clang,swift=tools
  old=ROUND.FIXTURE
  writer=(old/'writer.m').read_text()
  host=(FIX/'host_producer.inc').read_text()
  if mutant:
   host=host.replace('if (lockKnownOut) *lockKnownOut = lockKnown;', 'unlocked = gMiniSightScreenKnown && !gMiniSightScreenBlanked && unlocked; lockKnown = YES;\n    if (unlockedOut) *unlockedOut = unlocked;\n    if (lockKnownOut) *lockKnownOut = lockKnown;')
  writer=writer.replace('static NSUInteger assertions = 0;', (FIX/'host_support.m').read_text()+'\n'+host+'\nstatic NSUInteger assertions = 0;')
  writer=writer.replace('        fprintf(stdout, "PASS native ObjC writer:',(FIX/'screen_cases.inc').read_text()+'\n        fprintf(stdout, "PASS native ObjC writer:')
  (tmp/'writer.m').write_text(writer)
  main=(old/'main.swift').read_text()
  main=main.replace('do {\n    try check(CommandLine.arguments.count == 2,',(FIX/'screen_cases.swift').read_text()+'\ndo {\n    try screenCases(CommandLine.arguments[1])\n    try check(CommandLine.arguments.count == 2,')
  (tmp/'main.swift').write_text(main)
  ROUND.command([clang,'-isysroot',sdk,'-fobjc-arc','-Wall','-Wextra','-Werror','-I',core,'-I',FIX,tmp/'writer.m','-framework','Foundation','-framework','CoreFoundation','-o',tmp/'writer'])
  ROUND.command([swift,'-sdk',sdk,'-swift-version','5','-warnings-as-errors',ROUND.REMOTE,ROUND.POLICY,old/'support.swift',tmp/'main.swift','-o',tmp/'reader'])
  ROUND.command([tmp/'writer',tmp/'wire']);result=subprocess.run([str(tmp/'reader'),str(tmp/'wire')],text=True,capture_output=True,timeout=30)
  if mutant:
   self.assertEqual(result.returncode,1,result.stdout+result.stderr);self.assertIn('FAIL assertion: unknown screen is not trusted locked',result.stderr)
  else:self.assertEqual(result.returncode,0,result.stdout+result.stderr);print(result.stdout.strip())
 def test_host_writer_to_actual_swift_reader_both_trees(self):
  with tempfile.TemporaryDirectory(prefix='ms-shown-name-') as directory:
   tmp=Path(directory);tools=self.tools(tmp)
   cores=[CORE]
   if PLUGIN.is_dir():cores.append(PLUGIN)
   else:print('SKIP independent plugin binary compile (tree unavailable); pinned identical producer tested')
   for i,core in enumerate(cores):
    case=tmp/str(i);case.mkdir();self.name(case,tools,core)
   # Force the former defect in a real writer copy. Baseline ran first.
   mutated=tmp/'mutant';mutated.mkdir()
   text=(FIX/'host_producer.inc').read_text()
   old='BOOL unlocked = [MiniSightMusicMonitor deviceIsUnlockedWithKnown:&lockKnown];'
   self.assertIn(old,text)
   self.name(mutated,tools,CORE,mutant=True)
 def test_actual_settings_save_cancel_and_hide_interleavings(self):
  with tempfile.TemporaryDirectory(prefix='ms-shown-store-') as directory:
   tmp=Path(directory);tools=self.tools(tmp);self.shown(tmp,tools)
   mutant=tmp/'mutant';mutant.mkdir();self.shown(mutant,tools,mutant=True)
 def shown(self,tmp,tools,mutant=False):
  sdk,clang,swift=tools
  objc='#import "resources_bridge.h"\n#import "MiniSightShownReadback.h"\n@implementation MiniSightResources\n'+(FIX/'resources_producer.inc').read_text()+'\n@end\n'
  shutil.copyfile(FIX/'resources_bridge.h',tmp/'resources_bridge.h');(tmp/'resources.m').write_text(objc)
  ROUND.command([clang,'-isysroot',sdk,'-fobjc-arc','-Wall','-Wextra','-Werror','-I',CORE,'-I',tmp,'-c',tmp/'resources.m','-o',tmp/'resources.o'])
  store=(FIX/'store_producer.inc').read_text()
  if mutant:
   old='        reloadShownFromFile()\n        let d = UserDefaults.standard'
   self.assertIn(old,store);store=store.replace(old,'        try? MiniSightPetFile.saveShown(shown) { }\n        let d = UserDefaults.standard')
  (tmp/'support.swift').write_text((FIX/'shown_support.swift').read_text()+(FIX/'shown_producer.inc').read_text()+'\n}\n'+(FIX/'store_support.swift').read_text()+store+'\n}\n')
  shutil.copyfile(FIX/'shown_main.swift',tmp/'main.swift')
  ROUND.command([swift,'-sdk',sdk,'-swift-version','5','-warnings-as-errors','-import-objc-header',tmp/'resources_bridge.h',tmp/'support.swift',tmp/'main.swift',tmp/'resources.o','-Xlinker','-framework','-Xlinker','Foundation','-o',tmp/'shown'])
  result=subprocess.run([str(tmp/'shown'),str(tmp/'wire')],text=True,capture_output=True,timeout=30)
  if mutant:
   self.assertEqual(result.returncode,1,result.stdout+result.stderr)
   self.assertIn('stale cached ON page exit must not undo menu hide',result.stderr)
  else:
   self.assertEqual(result.returncode,0,result.stdout+result.stderr);self.assertIn('PASS native shown settings',result.stdout);print(result.stdout.strip())
if __name__=='__main__':
 parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--require-native',action='store_true',default=OPTIONS.require_native)
 OPTIONS,rest=parser.parse_known_args();print('Source PASS is not native behavior; strict missing-tool mode fails.',flush=True)
 unittest.main(argv=[__file__]+rest,verbosity=2)
