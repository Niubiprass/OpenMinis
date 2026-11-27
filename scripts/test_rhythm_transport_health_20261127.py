#!/usr/bin/env python3
"""Portable production C helper + actual ObjC use checks; no iOS runtime claim."""
import pathlib,subprocess,tempfile,unittest,os
ROOT=pathlib.Path(__file__).resolve().parents[1]
if not (ROOT/'MiniSightRhythmTransportHealth.h').exists():
 ROOT=ROOT/'src/ios/MiniSightCore'
BODY=r'''
#include "MiniSightRhythmTransportHealth.h"
#include <assert.h>
#include <string.h>
int main(void){
 MSRhythmHealthSample s={0};s.startedAt=10;s.now=10;
 assert(MSRhythmHealthClassify(s)==MSRhythmHealthWaiting);
 s.now=11.999;assert(MSRhythmHealthClassify(s)==MSRhythmHealthWaiting);
 s.now=12;assert(MSRhythmHealthClassify(s)==MSRhythmHealthNoPackets);
 s.datagrams=1;assert(MSRhythmHealthClassify(s)==MSRhythmHealthRejected);
 s.decoded=1;assert(MSRhythmHealthClassify(s)==MSRhythmHealthStale);
 s.fresh=true;assert(MSRhythmHealthClassify(s)==MSRhythmHealthReset);
 s.hasUpdate=true;assert(MSRhythmHealthClassify(s)==MSRhythmHealthUnqualified);
 s.frame.flags=MSRhythmFlagSilence;assert(MSRhythmHealthClassify(s)==MSRhythmHealthSilence);
 s.frame.flags=MSRhythmFlagValid;s.frame.confidence=.68;assert(MSRhythmHealthClassify(s)==MSRhythmHealthUnqualified);
 s.frame.period=.5;assert(MSRhythmHealthClassify(s)==MSRhythmHealthQualified);
 s.frame.flags|=MSRhythmFlagClipping;assert(MSRhythmHealthClassify(s)==MSRhythmHealthUnqualified);
 s.frame.flags=MSRhythmFlagValid;s.frame.confidence=.679;assert(MSRhythmHealthClassify(s)==MSRhythmHealthUnqualified);
 s.fresh=false;assert(MSRhythmHealthClassify(s)==MSRhythmHealthStale);
 MSRhythmHealthLimiter l={0};
 assert(MSRhythmHealthShouldLog(&l,MSRhythmHealthWaiting,10));
 assert(!MSRhythmHealthShouldLog(&l,MSRhythmHealthWaiting,11));
 assert(MSRhythmHealthShouldLog(&l,MSRhythmHealthNoPackets,12));
 assert(!MSRhythmHealthShouldLog(&l,MSRhythmHealthNoPackets,13));
 assert(!MSRhythmHealthShouldLog(&l,MSRhythmHealthNoPackets,27));
 for(unsigned i=0;i<100;i++)(void)MSRhythmHealthShouldLog(&l,(i%2)?MSRhythmHealthQualified:MSRhythmHealthNoPackets,28+i);
 assert(l.count==16);assert(!MSRhythmHealthShouldLog(&l,MSRhythmHealthQualified,999));
 assert(!MSRhythmHealthShouldLog(0,MSRhythmHealthWaiting,10));
 unsigned n=UINT_MAX;MSRhythmHealthIncrement(&n);assert(n==UINT_MAX);
 n=0;MSRhythmHealthIncrement(&n);assert(n==1);
 assert(!strcmp(MSRhythmHealthReason(MSRhythmHealthNoPackets),"rhythm_no_packets"));
 assert(!strcmp(MSRhythmHealthReason(MSRhythmHealthQualified),"rhythm_frame_qualified"));
 return 0;
}
'''
class Health(unittest.TestCase):
 def compile_run(self,body,root=ROOT):
  with tempfile.TemporaryDirectory() as td:
   p=pathlib.Path(td);(p/'test.c').write_text(body)
   c=subprocess.run([os.environ.get('CC','cc'),'-std=c11','-Wall','-Wextra','-Werror','-pedantic','-I'+str(root),str(p/'test.c'),'-lm','-o',str(p/'run')],capture_output=True,text=True)
   self.assertEqual(c.returncode,0,c.stderr)
   return subprocess.run([str(p/'run')],capture_output=True).returncode
 def test_real_production_classification_and_log_budget(self): self.assertEqual(self.compile_run(BODY),0)
 def test_source_consumes_real_io_and_never_claims_action_ready(self):
  t=(ROOT/'MiniSightRhythmClient.m').read_text()
  for part in ['MSRhythmHealthClassify(sample)','MSRhythmHealthShouldLog(&_healthLimiter','MSRhythmHealthIncrement(&_datagrams)','MSRhythmHealthIncrement(&_decoded)','MSRhythmHealthIncrement(&_updates)','sendto(_socket,packet,length,0,','MSRhythmHealthSendError','MSRhythmHealthSocketError','MSRhythmHealthReceiveError','@"input_ready":@NO','@"samples":@(_updates)','@"code":@(_ioErrors)']:
   self.assertIn(part,t)
  self.assertIn('if(_eligibilityHandler && !_eligibilityHandler()){[self stop];return;}',t)
  self.assertIn('[self sendLease:NO];close(_socket)',t)
  self.assertIn('Latest-value mailbox',t)
 def test_three_compiled_production_mutants_are_rejected(self):
  original=(ROOT/'MiniSightRhythmTransportHealth.h').read_text()
  for a,b in [('if (!s.datagrams)','if (s.datagrams)'),('f.confidence >= MS_PET_RHYTHM_MIN_CONFIDENCE','f.confidence >= .60'),('s->count >= 16','s->count >= 17')]:
   self.assertEqual(original.count(a),1)
   with tempfile.TemporaryDirectory() as td:
    p=pathlib.Path(td)
    for h in ROOT.glob('*.h'):(p/h.name).write_bytes(h.read_bytes())
    (p/'MiniSightRhythmTransportHealth.h').write_text(original.replace(a,b))
    self.assertNotEqual(self.compile_run(BODY,p),0,a)
if __name__=='__main__':unittest.main(verbosity=2)
