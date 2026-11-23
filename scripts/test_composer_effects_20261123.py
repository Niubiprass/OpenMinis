#!/usr/bin/env python3
"""Static + production numeric tests. Apple runtime checks skip honestly on iSH.
Python preview is a target, NOT an iOS renderer. No network/device calls.
"""
from pathlib import Path
import hashlib,json,math,os,re,shutil,subprocess,tempfile,unittest
ROOT=Path(__file__).resolve().parent.parent
SWIFT=ROOT/'src/ios/Views/Chat/ComposerEffects.swift'
CHAT=ROOT/'src/ios/Views/Chat/AIChatView.swift'
FIX=ROOT/'scripts/fixtures/composer_effects_20261123/preview-dot-samples.json'
BASE='4c1a5eb1325f9d376859dbdd33c4b4505be3d6be'

def block(text,marker):
 s=text.index(marker);o=text.index('{',s);d=1;i=o+1
 while d:
  d+=(text[i]=='{')-(text[i]=='}');i+=1
 return text[s:i]

def old(path):
 return subprocess.check_output(['git','show',BASE+':'+path],cwd=ROOT,text=True)

class SourceContracts(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.s=SWIFT.read_text();cls.c=CHAT.read_text();cls.p=(ROOT/'src/ios/Minis.xcodeproj/project.pbxproj').read_text()
 def test_new_model_is_really_hosted(self):
  host=block(self.c,'private struct ComposerSurface: ViewModifier')
  self.assertIn('ComposerFlowingWave(levels: waveLevels, voiceActive: voiceActive)',host)
  self.assertIn('.frame(height: ComposerFlowingWave.canvasHeight)',host)
  self.assertNotIn('ComposerRainbowWave(',host)
  self.assertNotIn('opacity: 0.86',host)
  self.assertEqual(host.count('.overlay(alignment: .bottom) { wave }'),2)
  self.assertIn('.background { decoratedSurface }',host)
  self.assertIn('shape.fill(ChatColors.inputBg)',host)
  self.assertNotIn('.padding(',host)
  self.assertNotIn('.offset(',host)
  self.assertEqual(block(host,'private var shape: RoundedRectangle'),block(old('src/ios/Views/Chat/AIChatView.swift'),'private var shape: RoundedRectangle'))
 def test_text_layout_and_warning_not_changed(self):
  prior=old('src/ios/Views/Chat/AIChatView.swift')
  c=self.c.replace('ComposerFlowingWave(levels: waveLevels, voiceActive: voiceActive)','ComposerRainbowWave(levels: waveLevels, opacity: 0.86, voiceActive: voiceActive)').replace('ComposerFlowingWave.canvasHeight','ComposerRainbowWave.canvasHeight')
  new_call='''.modifier(ComposerSurface(waveLevels: composerWaveLevels,
                                      voiceActive: voiceInputActive || speechManager.state == .recording,
                                      beamActive: (vm.contextUsage?.tier ?? .normal) == .normal))'''
  old_call='.modifier(ComposerSurface(waveLevels: composerWaveLevels, voiceActive: voiceInputActive || speechManager.state == .recording))'
  self.assertEqual(c.count(new_call),1)
  c=c.replace(new_call,old_call)
  # Host decoration is the only changed region. Everything outside it,
  # including the entire content tree, geometry observers and warning view,
  # must remain byte-exact relative to the approved baseline.
  current_host=block(c,'private struct ComposerSurface: ViewModifier')
  prior_host=block(prior,'private struct ComposerSurface: ViewModifier')
  c=c.replace(current_host,prior_host)
  self.assertEqual(c,prior)
  self.assertEqual(re.findall(r'\.shadow\([^\n]+',current_host),re.findall(r'\.shadow\([^\n]+',prior_host))
  self.assertEqual(block(self.c,'private struct ComposerContextGlow: View'),block(prior,'private struct ComposerContextGlow: View'))
  self.assertEqual((ROOT/'src/ios/Views/Chat/AudioWaveformView.swift').read_text(),old('src/ios/Views/Chat/AudioWaveformView.swift'))
 def test_border_warning_priority_not_inner_wave(self):
  self.assertIn('beamActive: (vm.contextUsage?.tier ?? .normal) == .normal',self.c)
  host=block(self.c,'private struct ComposerSurface: ViewModifier')
  self.assertEqual(host.count('.overlay { ComposerBorderBeam(active: beamActive) }'),2)
  self.assertIn('.background { decoratedSurface }',host)
  self.assertIn('guard active else { return }',block(self.s,'struct ComposerBorderBeam: View'))
  wave=block(self.s,'struct ComposerFlowingWave: View')
  self.assertNotIn('guard active',wave)
  self.assertNotIn('contextUsage',wave)
 def test_no_ios17_package_api(self):
  for token in ('.colorEffect(', 'ShaderLibrary.', '.resolve(in:', 'GeometryReader', 'Timer.publish', '.drawingGroup('):
   code=re.sub(r'//[^\n]*','',self.s)
   self.assertNotIn(token,code)
  self.assertIn('Canvas(opaque: false, colorMode: .nonLinear)',self.s)
  self.assertIn('.radialGradient(Gradient(stops: stops)',self.s)
 def test_motion_and_interactions(self):
  for name in ['ComposerFlowingWave','ComposerBorderBeam']:
   view=block(self.s,'struct '+name+': View')
   for t in ['.allowsHitTesting(false)','.accessibilityHidden(true)','paused: !running','.onDisappear {','.onChange(of: scenePhase)','.onChange(of: reduceMotion)']:
    self.assertIn(t,view)
   self.assertIn('visible && scenePhase == .active && !reduceMotion',view)
  self.assertNotIn('ObservableObject',block(self.s,'final class ComposerEffectClock'))
  self.assertNotIn('Task.sleep',self.s)
  self.assertNotIn('UserDefaults',self.s)
 def test_per_dot_light_pipeline_not_fixed_buckets(self):
  wave=block(self.s,'struct ComposerFlowingWave: View')
  self.assertNotIn('Buckets',wave)
  for t in ['dot.rgb.scaled(k).quantized().color','dot.rgb.lifted(0.13).scaled(k).quantized().color','point.opacity = floor(dot.alpha * 255) / 255']:
   self.assertIn(t,wave)
  self.assertEqual(wave.count('.blendMode(.plusLighter)'),2)
  self.assertEqual(wave.count('Canvas(opaque: false, colorMode: .nonLinear)'),3)
  self.assertNotIn('addFilter(.blur(',wave)
  self.assertIn('.blur(radius: 2)',wave)
  self.assertIn('.blur(radius: 0.50)',wave)
  self.assertLess(wave.index('{ wash, size in'),wave.index('point.opacity = floor('))
  self.assertLess(wave.index('point.opacity = floor('),wave.index('{ sheen, size in'))
 def test_tracks_the_actual_continuous_shape(self):
  track=block(self.s,'final class ComposerBeamTrack')
  self.assertIn('RoundedRectangle(cornerRadius: 20, style: .continuous)',track)
  for t in ['path.forEach { element','if area < 0 { contour.reverse() }','if contour.first == contour.last','Array(contour[..<next]) + [seamPoint]','while low + 1 < high']:
   self.assertIn(t,track)
  self.assertIn('guard size != cachedSize || points.isEmpty',track)
 def test_resources_and_version(self):
  self.assertIn('ComposerEffects.swift in Sources',self.p)
  self.assertIn('BorderBeam-LICENSE.txt in Resources',self.p)
  self.assertEqual(self.p.count('BEA2026112300000000000001 /* ComposerEffects.swift in Sources */'),2)
  self.assertEqual(self.p.count('BEA2026112300000000000003 /* BorderBeam-LICENSE.txt in Resources */'),2)
  self.assertIn('Copyright (c) 2026 ismnoiet',(SWIFT.parent/'BorderBeam-LICENSE.txt').read_text())
  for t in ['MARKETING_VERSION = 1.18','MARKETING_VERSION = 1.17']:
   self.assertNotIn(t,self.p)
  self.assertEqual(self.p.count('MARKETING_VERSION = 1.16;'),8)
 def test_native_gate_is_wired(self):
  wf=(ROOT/'.github/workflows/ios15-v64-repair.yml').read_text()
  self.assertIn('python3 scripts/test_composer_effects_20261123.py',wf)

class PortableProductionMath(unittest.TestCase):
 def test_cpp_runs_extracted_production_ridge_and_cycle(self):
  # These three actual Swift function bodies only use primitive scalar math;
  # translate their syntax and compile the production expressions, not a new
  # hand-written approximation. Does not validate SwiftUI/Swift ABI.
  cc=shutil.which('c++') or shutil.which('g++') or shutil.which('clang++')
  if not cc:self.skipTest('C++ compiler unavailable; scalar native checks NOT run')
  s=SWIFT.read_text(); functions=[]
  def translate(marker,decl):
   body=block(s,marker).split('{',1)[1].rsplit('}',1)[0]
   body=re.sub(r'//[^\n]*','',body).strip()
   body=body.replace('.pi','M_PI').replace('let ','double ').replace('var ','double ')
   body=body.replace('Double(row)','double(row)').replace('floor(', 'floor(')
   body=re.sub(r'\b(min|max)\((-?\d+),',r'\1(\2.0,',body)
   body=body.replace('ridgeSeparation(time)','ridgeSeparation(time)')
   body=body.replace('guard elapsed.isFinite else { return 1 }','if (!std::isfinite(elapsed)) { return 1; }')
   body=re.sub(r'if ([^\n{]+) \{',r'if (\1) {',body)
   lines=[]
   # Multi-line arithmetic expressions remain one statement until next declaration.
   body=re.sub(r'\n\s*([*+])',r' \1',body)
   if marker=='static func ridgeSeparation(':body='return '+body
   for line in body.splitlines():
    line=line.strip()
    if not line:continue
    line=re.sub(r'(return [^{};]+)(?=\s*})',r'\1;',line)
    if not line.endswith(('{','}',';')):line+=';'
    lines.append(line)
   functions.append(decl+' {\n'+'\n'.join(lines)+'\n}')
  translate('static func ridgeSeparation(', 'double ridgeSeparation(double time)')
  translate('static func light(', 'double light(double unit, int row, double time)')
  translate('static func smoothstep(', 'double smoothstep(double value)')
  translate('static func spectrumWeight(', 'double spectrumWeight(double elapsed)')
  fixture=json.loads(FIX.read_text());checks=[]
  for f in fixture['frames']:
   for d in f['samples']:
    # x and y identify exact row/unit for the production sp formula.
    checks.append('assert(fabs(light(%.17g,%d,%.17g)-%.17g)<2e-10);'%(d['x']/350,round((34-d['y'])/2.35),f['time'],d['light']))
  driver='''
for (int i=0;i<100000;++i) {
 double t=i*.0001, w=spectrumWeight(t);
 assert(w>=0&&w<=1);
 if(i>0) assert(fabs(w-spectrumWeight(t-.0001))<.001);
}
assert(spectrumWeight(0)==1);
assert(spectrumWeight(2.4)==1);
assert(spectrumWeight(3.1)==0);
assert(spectrumWeight(4.8)==0);
assert(spectrumWeight(5.5)==1);
puts("production ridge/cycle scalar checks passed");
'''
  text='#include <cmath>\n#include <algorithm>\n#include <cassert>\n#include <cstdio>\nusing std::min;using std::max;\nconst double lap=2.4,handover=.6;\n'+'\n'.join(functions)+'\nint main(){\n'+'\n'.join(checks)+driver+'\n}'
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'test.cpp').write_text(text)
   r=subprocess.run([cc,'-std=c++11','-O1',str(p/'test.cpp'),'-o',str(p/'test')],capture_output=True,text=True,timeout=90)
   self.assertEqual(r.returncode,0,r.stderr)
   r=subprocess.run([str(p/'test')],capture_output=True,text=True,timeout=30)
   self.assertEqual(r.returncode,0,r.stderr);print(r.stdout)

class AppleProduction(unittest.TestCase):
 def test_swift_numeric_samples_clock_and_real_continuous_track(self):
  swift=shutil.which('swiftc')
  required=os.environ.get('V64R_REQUIRE_SWIFT')=='1' or __import__('sys').platform=='darwin'
  if not swift:
   if required:self.fail('Apple Swift required; native production checks NOT run')
   self.skipTest('Apple Swift/SwiftUI unavailable; no native verdict')
  if __import__('sys').platform!='darwin':self.skipTest('SwiftUI requires Apple SDK')
  fixture=json.loads(FIX.read_text())
  checks=[]
  for frame in fixture['frames']:
   checks.append('do { let ds=ComposerFlowModel.dots(width:350,baseline:34,time:%.17g); precondition(ds.count == %d)'%(frame['time'],frame['count']))
   for d in frame['samples']:
    checks.append('do { let d=ds[%d]; '%d['index']+'; '.join('precondition(abs(%s - %.17g)<2e-9)'%(name,v) for name,v in [('d.x',d['x']),('d.y',d['y']),('d.diameter',d['diameter']),('d.rgb.r',d['rgb'][0]),('d.rgb.g',d['rgb'][1]),('d.rgb.b',d['rgb'][2]),('d.alpha',d['alpha']),('d.light',d['light']),('d.vertical',d['vertical'])])+' }')
   checks.append('}')
  harness='''
import Foundation
import SwiftUI
import QuartzCore
@main struct Run {
 static func main() {
'''+ '\n'.join(checks)+'''
 let clock=ComposerEffectClock()
 precondition(clock.advance(running:true,timestamp:10)==0)
 precondition(abs(clock.advance(running:true,timestamp:11)-1)<1e-9)
 _=clock.advance(running:false,timestamp:100)
 precondition(clock.advance(running:true,timestamp:200)==1)
 precondition(abs(clock.advance(running:true,timestamp:201)-2)<1e-9)
 clock.resetAnchor()
 precondition(clock.advance(running:true,timestamp:1000)==2)
 for w in [1.0,2,3,296,350,390,768,1024] {
  let ds=ComposerFlowModel.dots(width:w,baseline:72,time:7.25)
  precondition(ds.count<=256*11)
  for d in ds { precondition(d.x.isFinite && d.alpha>=0 && d.alpha<=1) }
  for h in [1.0,3,45,92,200] {
   let track=ComposerBeamTrack();track.prepare(size:CGSize(width:w,height:h))
   if w<=2||h<=2 { precondition(track.length==0); continue }
   precondition(track.length.isFinite && track.length>0)
   let a=track.point(at:0),b=track.point(at:1)
   precondition(hypot(a.x-b.x,a.y-b.y)<1e-5)
   for i in -20...120 {
    let p=track.point(at:Double(i)/100)
    precondition(p.x >= -0.01 && p.x <= w + 0.01 && p.y >= -0.01 && p.y <= h + 0.01)
   }
  }
 }
 precondition(ComposerFlowModel.dots(width:.nan,baseline:72,time:0).isEmpty)
 precondition(ComposerFlowModel.dots(width:350,baseline:72,time:.infinity).isEmpty)
 print("NATIVE composer dot/clock/continuous-track checks passed (not a UI screenshot)")
 }
}
'''
  with tempfile.TemporaryDirectory() as td:
   p=Path(td);(p/'run.swift').write_text(harness)
   architecture=__import__('platform').machine()
   target='arm64-apple-macosx12.0' if architecture in ('arm64','aarch64') else 'x86_64-apple-macosx12.0'
   r=subprocess.run([swift,'-swift-version','5','-target',target,'-parse-as-library',str(SWIFT),str(p/'run.swift'),'-o',str(p/'run')],capture_output=True,text=True,timeout=180)
   self.assertEqual(r.returncode,0,r.stderr)
   r=subprocess.run([str(p/'run')],capture_output=True,text=True,timeout=30)
   self.assertEqual(r.returncode,0,r.stdout+r.stderr);print(r.stdout)

if __name__=='__main__':unittest.main(verbosity=2)
