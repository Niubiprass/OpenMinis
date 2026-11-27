#!/usr/bin/env python3
"""Real C geometry execution + source contracts. No device/iOS execution."""
import argparse,hashlib,json,os,shutil,subprocess,tempfile
from pathlib import Path
R=Path(__file__).resolve().parents[1]
CORE=R/'src/ios/MiniSightCore' if (R/'src/ios').is_dir() else R
H=(CORE/'MiniSightGeometry.h').read_text()
C=r'''
#include "MiniSightGeometry.h"
#include <assert.h>
int main(void) {
 MSSize pet={80,104};
 MSRect base=MSBodyCenterBounds(390,844,pet,2);
 MSRect clear=MSPetKeyboardCenters(base,pet,(MSRect){0,0,0,0});
 assert(clear.x==base.x && clear.y==base.y && clear.w==base.w && clear.h==base.h);
 MSRect bad=MSPetKeyboardCenters(base,pet,(MSRect){NAN,400,390,444});
 assert(bad.h==base.h);
 MSRect b=MSPetKeyboardCenters(base,pet,(MSRect){0,550,390,294});
 assert(b.x==base.x && b.w==base.w && b.y==base.y);
 assert(fabs(b.y+b.h+pet.h*.5-(550-76))<1e-8);
 MSPoint p=MSClampCenter(b,(MSPoint){200,800});
 assert(p.y+pet.h*.5<=550-76+1e-8);
 MSRect full=MSPetKeyboardCenters(base,pet,(MSRect){0,0,390,844});
 assert(full.h<0);
 for(int top=140;top<844;top+=7) for(int size=32;size<180;size+=9) {
   MSSize body={size,size};MSRect original=MSBodyCenterBounds(390,844,body,2);
   MSRect allowed=MSPetKeyboardCenters(original,body,(MSRect){0,top,390,844-top});
   if(allowed.h>=0) {
     for(int y=-100;y<1000;y+=29) {
       MSPoint q=MSClampCenter(allowed,(MSPoint){100,y});
       assert(q.y+size*.5<=top-76+1e-8);
     }
     MSPoint q=MSClampCenter(allowed,(MSPoint){180,allowed.y});
     MSPoint restored=MSClampCenter(original,q);
     assert(restored.x==q.x && restored.y==q.y); // Hide does not move to bottom.
   }
 }
 return 0;
}
'''
def run(h):
 with tempfile.TemporaryDirectory() as d:
  p=Path(d); (p/'MiniSightGeometry.h').write_text(h);(p/'case.c').write_text(C)
  subprocess.run([shutil.which('clang') or 'cc','-std=c11','-Wall','-Wextra','-Werror','-pedantic',str(p/'case.c'),'-lm','-o',str(p/'case')],check=True,timeout=45)
  return subprocess.run([str(p/'case')],stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=15).returncode
assert run(H)==0
for old,new in [('keyboard.y - 76. - body.h * .5','keyboard.y - body.h * .5'),('keyboard.y - 76. - body.h * .5','keyboard.y - 76. - body.h * 0.'),('base.h = fmin(base.h, bottom - base.y);','base.h = fmax(0., fmin(base.h, bottom - base.y));')]:
 assert old in H
 assert run(H.replace(old,new))!=0,old
print('PASS real C keyboard geometry + three compiled assertion mutants; not UIKit/keyboard runtime')
if (R/'src/ios').is_dir():
 S=(R/'src/ios/MiniSightSettings.swift').read_text();A=(R/'src/ios/MiniSightInAppRuntime.swift').read_text();K=(R/'src/ios/MiniSightConfigStore.swift').read_text()
 for t in ['static let keyboardAvoidance = "minisight.keyboard.avoid"','MiniSightSettingKey.keyboardAvoidance: "keyboardAvoidance"','MiniSightSettingKey.keyboardAvoidance: false','runtimeFields.count == 53']:
  assert t in S,t
 for t in ['publish(MiniSightSettingKey.keyboardAvoidance)','keyboardAvoidance = MiniSightConfig.bool(MiniSightSettingKey.keyboardAvoidance, false)','case MiniSightSettingKey.keyboardAvoidance: return keyboardAvoidance']:assert t in K
 for t in ['panKeyboardEpoch == host.keyboardEpoch','keyboardWillChangeFrameNotification','keyboardWillHideNotification','MSPetKeyboardCenters','if pet.isHidden != noRoom','keyboardScreenFrame = .null']:assert t in A,t
 clear=A.split('@objc private func keyboardCleared',1)[1].split('override func layoutSubviews',1)[0]
 assert 'centerX =' not in clear and 'centerY =' not in clear
 P=R.parent/'plugin/debs/MiniSight'
else:P=CORE
if (P/'Tweak.xm').is_file():
 T=(P/'Tweak.xm').read_text()
 assert 'MSPetKeyboardCenters' in T and 'gMiniSightKeyboardInterruptedDrag' in T
 assert 'UIKeyboardWillChangeFrameNotification' in T and 'UIKeyboardWillHideNotification' in T
 assert 'gMiniSightKeyboardScreenFrame = CGRectZero;' in T
 for root in [CORE,P]:
  panel=(root/'MiniSightChatPanel.m').read_text()
  assert '(anchor.hidden && !keyboardOccluded)' in panel
  assert 'anchor.window.hidden || anchor.window.windowScene != self.window.windowScene' in panel
  assert '((MiniSightPetView *)anchor).keyboardAvoidanceOccluded' in panel
  assert '@property (nonatomic) BOOL keyboardAvoidanceOccluded;' in (root/'MiniSightPet.h').read_text()
  assert '"minisight.keyboard.avoid": @"keyboardAvoidance"' in (root/'MiniSightResources.m').read_text()
  assert '"minisight.keyboard.avoid"' in (root/'MiniSightLog.m').read_text()
 if P!=CORE:assert (P/'MiniSightGeometry.h').read_bytes()==(CORE/'MiniSightGeometry.h').read_bytes()
print('PASS static settings/notification/readback wiring guards; keyboard delivery NOT verified')
