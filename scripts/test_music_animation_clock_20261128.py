#!/usr/bin/env python3
"""Portable clock behavior and source integration; native UIKit is not run here."""
from pathlib import Path
import subprocess, tempfile, unittest, shutil
ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'src/ios/MiniSightCore'
if not CORE.is_dir(): CORE=ROOT

def contract(e,p,h):
    assert 'MSMusicAnimationElapsed(&_rhythmAnimation)' in e, 'measured artwork still follows song position'
    assert 'MSMusicAnimationObserve(&_rhythmAnimation, sampleTime)' in e, 'sample clock not consumed'
    assert 'applyRhythmSampleTime:(NSTimeInterval)sampleTime' in h, 'missing public seam'
    gate=p.index('if (!gate || !action.accepted)')
    sample=p.index('[_effects applyRhythmSampleTime:frame.sampleTime];')
    assert gate < sample and 'return;' in p[gate:sample], 'unaccepted input can animate'
    assert 'MSMusicAnimationReset(&_rhythmAnimation)' in e, 'missing reset'

C=r'''
#include <assert.h>
#include <math.h>
#include "MiniSightMusicAnimationClock.h"
int main(void) {
 MSMusicAnimationClock s={0};
 assert(MSMusicAnimationElapsed(&s)==0.);
 assert(MSMusicAnimationObserve(&s,100.));
 for(int i=1;i<=6;i++) assert(MSMusicAnimationObserve(&s,100.+i*.05));
 assert(fabs(MSMusicAnimationElapsed(&s)-.30)<1e-8);
 /* UI wall time and absent/song seeks cannot advance or reset this clock. */
 for(int i=0;i<1000;i++)assert(fabs(MSMusicAnimationElapsed(&s)-.30)<1e-8);
 MSMusicAnimationRestart(&s); assert(MSMusicAnimationElapsed(&s)==0.);
 assert(MSMusicAnimationObserve(&s,100.35)); assert(fabs(MSMusicAnimationElapsed(&s)-.05)<1e-8);
 assert(!MSMusicAnimationObserve(&s,100.35));assert(MSMusicAnimationElapsed(&s)==0.);
 assert(MSMusicAnimationObserve(&s,101.)); assert(MSMusicAnimationElapsed(&s)==0.);
 assert(!MSMusicAnimationObserve(&s,100.));assert(MSMusicAnimationElapsed(&s)==0.);
 assert(MSMusicAnimationObserve(&s,200.)); assert(!MSMusicAnimationObserve(&s,201.));
 assert(MSMusicAnimationElapsed(&s)==0.);assert(!MSMusicAnimationObserve(&s,NAN));
 assert(!MSMusicAnimationObserve(&s,INFINITY));assert(!MSMusicAnimationObserve(&s,-1.));
 assert(MSMusicAnimationObserve(&s,1.));assert(MSMusicAnimationObserve(&s,1.2));
 MSMusicAnimationReset(&s);assert(!s.anchored&&MSMusicAnimationElapsed(&s)==0.);
 assert(MSMusicAnimationObserve(&s,500.));assert(MSMusicAnimationElapsed(&s)==0.);
 assert(!MSMusicAnimationObserve(0,0.));assert(MSMusicAnimationElapsed(0)==0.);
 return 0;
}'''
class Checks(unittest.TestCase):
 def test_source_integration(self):
  contract((CORE/'MiniSightPetEffects.m').read_text(),(CORE/'MiniSightPet.m').read_text(),(CORE/'MiniSightPetEffects.h').read_text())
 def test_source_mutants_rejected(self):
  e=(CORE/'MiniSightPetEffects.m').read_text();p=(CORE/'MiniSightPet.m').read_text();h=(CORE/'MiniSightPetEffects.h').read_text()
  contract(e,p,h)
  for a,b in [('MSMusicAnimationElapsed(&_rhythmAnimation)','self.musicPosition'),('MSMusicAnimationObserve(&_rhythmAnimation, sampleTime)','false')]:
   self.assertIn(a,e)
   with self.assertRaises(AssertionError):contract(e.replace(a,b),p,h)
  needle='[_effects applyRhythmSampleTime:frame.sampleTime];'
  with self.assertRaises((AssertionError,ValueError)):contract(e,p.replace(needle,''),h)
 def test_production_clock_compiled(self):
  self.assertTrue((CORE/'MiniSightMusicAnimationClock.h').is_file())
  cc=shutil.which('cc') or shutil.which('gcc')
  self.assertIsNotNone(cc,'host C compiler missing')
  with tempfile.TemporaryDirectory(prefix='ms-clock-') as t:
   f=Path(t)/'clock.c';f.write_text(C);out=Path(t)/'clock'
   subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-I',str(CORE),str(f),'-lm','-o',str(out)],check=True,timeout=30)
   subprocess.run([str(out)],check=True,timeout=10)
if __name__=='__main__':unittest.main(verbosity=2)
