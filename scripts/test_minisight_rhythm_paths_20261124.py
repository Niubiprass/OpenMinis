#!/usr/bin/env python3
"""Pure offline host CI gate. Never opens sockets, captures sound or loads hooks.
C/C++ method extraction and local synthesized audio are NOT iOS/UIKit proof.
"""
from pathlib import Path
import argparse,importlib.util,json,hashlib,shutil,subprocess,tempfile,sys,re
ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'src/ios/MiniSightCore' if (ROOT/'src/ios/MiniSightCore/MiniSightPet.m').is_file() else ROOT
FIX=ROOT/'scripts/fixtures/minisight_rhythm_20261124'

def generate_harness(pet,effects):
 spec=importlib.util.spec_from_file_location('rhythm_released_paths',ROOT/'scripts/test_minisight_pet_paths_20261122.py');b=importlib.util.module_from_spec(spec);spec.loader.exec_module(b)
 b.P_METHODS.update({'setRhythmFollowing:':('void','bool following'),'clearRhythm':('void','void'),'resetRhythmForSession:':('void','uint64_t sessionToken'),'checkRhythmAtTime:':('void','double now'),'applyRhythmFrame:receivedAt:':('void','MSRhythmFrame frame, double receivedAt')})
 b.E_METHODS.update({'setRhythmFollowing:':('void','bool following'),'applyRhythmStrength:pulse:':('void','double strength, double pulse')})
 old=b.translate
 def translate(raw,owner):return old(raw.replace('_effects.rhythmFollowing = following;','[_effects setRhythmFollowing:following];'),owner)
 b.translate=translate;b.source_guards(pet,effects);return b,b.generate(pet,effects)

def driver_source():
 driver=(ROOT/'scripts/fixtures/minisight_pet_paths_20261122/driver.c').read_text()
 replacements=[('#include "MiniSightPetMusicMotion.h"','#include "MiniSightPetMusicMotion.h"\n#include "MiniSightPetRhythmPolicy.h"'),(' unsigned musicMotionStep,roamGeneration;',' bool rhythmFollowing,rhythmStarting;\n uint64_t rhythmSessionToken;\n MSPetRhythmPolicy rhythmPolicy;\n MSPetRhythmAction rhythmAction;\n unsigned musicMotionStep,roamGeneration;'),(' bool bubbleHidden,hasWalk,hasJump;',' bool rhythmFollowing;\n double rhythmStrength,rhythmPulse,rhythmAt;\n bool bubbleHidden,hasWalk,hasJump;'),('int main(int argc,char**argv) {',(FIX/'rhythm_cases.c').read_text()+'\n'+(FIX/'extra_cases.c').read_text()+'\nint main(int argc,char**argv) {'),(' MusicBoundsAndNormal();',' MusicBoundsAndNormal();\n RhythmSuite(); RhythmExtra();')]
 for old,new in replacements:
  if driver.count(old)!=1:raise AssertionError('fixture seam missing/ambiguous: '+old)
  driver=driver.replace(old,new)
 return driver

def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('--mutations',action='store_true');a=p.parse_args()
 cc=shutil.which('clang') or shutil.which('gcc');assert cc,'host C compiler required'
 pet=(CORE/'MiniSightPet.m').read_text();effects=(CORE/'MiniSightPetEffects.m').read_text();b,(generated,evidence)=generate_harness(pet,effects)
 assert len(evidence)>=65,'production methods disappeared'
 with tempfile.TemporaryDirectory(prefix='minisight-rhythm-paths-') as tmp:
  td=Path(tmp);(td/'production-paths.h').write_text(generated);(td/'driver.c').write_text(driver_source())
  names=['MiniSightGeometry.h','MiniSightGravity.h','MiniSightLiveliness.h','MiniSightPetBehavior.h','MiniSightPetMusicMotion.h','MiniSightPetRhythmPolicy.h','MiniSightRhythmFrame.h']
  for n in names:shutil.copyfile(CORE/n,td/n)
  binary=td/'paths'
  def execute(label,expected):
   c=subprocess.run([cc,'-std=c99','-O1','-Wall','-Wno-unused-function','-I',str(td),str(td/'driver.c'),'-lm','-o',str(binary)],capture_output=True,text=True,timeout=180)
   assert c.returncode==0,label+' must compile, not a runtime kill:\n'+c.stdout+c.stderr
   r=subprocess.run([str(binary)],capture_output=True,text=True,timeout=60)
   if expected==0:
    assert r.returncode==0,r.stdout+r.stderr;print(r.stdout,end='')
   else:
    assert r.returncode==1 and 'FAIL:' in r.stderr,label+' survived/crashed rather than assertion rejection:\n'+r.stdout+r.stderr;print('REJECT compiled rhythm path mutant:',label,r.stderr.strip())
  execute('production',0)
  if a.mutations:
   music=(CORE/'MiniSightPetMusicMotion.h').read_text();variants={
    'music-host-starved':(pet.replace('    if (_effects.musicPlaying) {','    if (_effects.musicPlaying) { return;'),music),
    'center-frozen-until-finish':(pet.replace('self.center = [self clampedCenter:MSPetCGPoint(sample)];','self.center = MSPetCGPoint(_motionStart);'),music),
    'no-travelling-hops':(pet,re.sub(r'travel.jump = [^;]+;','travel.jump = false;',music)),
    'no-music-motion-gate':(pet.replace('(_musicMotion && ![self mayPerformMusicMotion])','NO'),music)}
   playing=b.definition(pet,'setMusicPlaying:');broken=playing.replace('[self clearRhythm];','/* intentionally omit shared stop cleanup */').replace('if (_musicMotion && !_physicsMotion && !_dragging) [self cancelMotion];','if (_musicMotion) { /* broken: no local cancel */ }');rhythm_clear=b.definition(pet,'clearRhythm');broken_clear=rhythm_clear.replace('if (_musicMotion && !_physicsMotion && !_dragging) [self cancelMotion];','if (_musicMotion) { /* broken: no stop cancellation */ }');broken=broken.replace(rhythm_clear,broken_clear);variants['stop-keeps-music-route']=(pet.replace(playing,broken),music)
   for label,(modified,policy) in variants.items():
    assert (modified,policy)!=(pet,music),label+' mutation no-op'
    # Runtime tests exercise deliberate damage; source-conformance guards are
    # intentionally checked on BASELINE above, not used as mutation kills.
    text,_=b.generate(modified,effects);(td/'production-paths.h').write_text(text);(td/'MiniSightPetMusicMotion.h').write_text(policy);execute(label,1)
 print('PASS rhythm paths: %d actual production excerpts, original regressions + new rhythm ownership/session/quiet cases'%len(evidence))
 print('NOT RUN: iOS UIKit/QuartzCore/actual audio scheduling/device/PAC; host seam dependencies explicitly mocked')
 return 0
if __name__=='__main__':raise SystemExit(main())
