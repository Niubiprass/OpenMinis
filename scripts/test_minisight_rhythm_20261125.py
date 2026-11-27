#!/usr/bin/env python3
"""Offline synthetic PCM -> FFT -> actual MIT estimator; no capture/socket/CI/device."""
from pathlib import Path
import argparse,json,shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'src/ios/MiniSightCore'
if not CORE.is_dir():CORE=ROOT
F=ROOT/'scripts/fixtures/minisight_rhythm_20261125'

def run(cmd,limit=420):
 r=subprocess.run([str(x) for x in cmd],capture_output=True,text=True,timeout=limit)
 if r.returncode:raise RuntimeError('Offline command failed: '+r.stdout[-1800:]+r.stderr[-1800:])
 return r.stdout

def main():
 run([__import__('sys').executable, ROOT/'scripts/test_rhythm_transport_health_20261127.py'],120)
 p=argparse.ArgumentParser();p.add_argument('--output',type=Path);a=p.parse_args()
 cxx=shutil.which('clang++') or shutil.which('g++');cc=shutil.which('clang') or shutil.which('cc')
 if not cxx or not cc:raise SystemExit('portable host C/C++ compiler required')
 results={'scope':'synthetic PCM/FFT + production C/C++ only; no Apple/audio/device','scenarios':[]}
 with tempfile.TemporaryDirectory(prefix='minisight-rhythm-local-') as t:
  t=Path(t);exe=t/'analyzer'
  base=[cxx,'-std=c++11','-O1','-w','-I',CORE]
  deps=[CORE/'MiniSightRhythmAnalyzer.cpp',CORE/'vendor/BeatDetektor/BeatDetektor.cpp']
  run(base+[F/'test_analyzer.cpp',*deps,'-o',exe])
  text=run([exe],600);print(text,end='')
  rows=[json.loads(x) for x in text.splitlines() if x.startswith('{')]
  required=[x for x in rows if x.get('required')]
  assert len(required)==6 and all(x['pass'] for x in required)
  assert rows[-1]['test_failures']==0
  results['scenarios']=rows
  boundary=t/'boundaries';run(base+[F/'analyzer_boundaries.cpp',*deps,'-o',boundary]);results['boundary_stdout']=run([boundary])
  print(results['boundary_stdout'],end='')
  wire=t/'wire';run([cc,'-std=c11','-O1','-I',CORE,F/'wire_receive.c','-lm','-o',wire]);results['wire_stdout']=run([wire]);print(results['wire_stdout'],end='')
  results['status']='PASS_REQUIRED_OFFLINE_CASES'
  results['known_optional_failures']=[x for x in rows if x.get('required') is False and x.get('pass') is False]
  assert '#define MINISIGHT_ENABLE_RHYTHM_TRANSPORT 0' in (CORE/'MiniSightRhythmClient.m').read_text()
  if results['known_optional_failures']:
   print('LIMITATION: optional digital-silence barepulse still fails; not all music supported')
 if a.output:
  a.output.parent.mkdir(parents=True,exist_ok=True);a.output.write_text(json.dumps(results,indent=2)+'\n')
 print('PASS required offline rhythm checks; NOT live audio or phone beat alignment')
if __name__=='__main__':main()
