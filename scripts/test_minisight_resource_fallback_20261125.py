#!/usr/bin/env python3
"""Real C rebuild policy + source wiring; ObjC metadata validator native only on CI."""
from pathlib import Path
import argparse,os,platform,shutil,subprocess,tempfile
ROOT=Path(__file__).resolve().parents[1]
P=ROOT.parent/'plugin/debs/MiniSight'
if not P.is_dir(): P=ROOT
if not (P/'Tweak.xm').exists(): P=ROOT/'debs/MiniSight'

def definition(s,start):
 a=s.index(start);i=s.index('{',a);depth=1;j=i+1
 while depth:
  if s[j]=='{':depth+=1
  elif s[j]=='}':depth-=1
  j+=1
 return s[a:j]


def portable():
 text=(P/'Tweak.xm').read_text();source=(P/'MiniSightResources.m').read_text()
 assert 'MSAssetNeedsHostRebuild(resourcesFresh' in text
 assert 'if (MiniSightShown() && !MiniSightAppOwnsPresentation())' in text
 assert 'BOOL badMetadata = hasMetadata &&' in source
 assert 'NSDictionary *petMeta = !badMetadata && [object isKindOfClass:NSDictionary.class] ? object : nil;' in source
 assert 'UIImage *atlas = !badMetadata && petPath ?' in source
 assert '!usingDefault && [petMeta[@"actionPack"] isKindOfClass:NSString.class]' in source
 c='''#include "MiniSightAssetFallbackPolicy.h"
#include <assert.h>
#include <stdio.h>
int main(void) { for(unsigned x=0;x<32;++x){
bool f=x&1, style=x&2, built=x&4, pet=x&8, atlas=x&16;
assert(MSAssetNeedsHostRebuild(f,style,built,pet,atlas)==(f&&style&&built&&!pet&&atlas));
} puts("PASS production fallback host rebuild 32 states; does not enable/show the pet");}
'''
 with tempfile.TemporaryDirectory() as d:
  exe=Path(d)/'policy'
  subprocess.run(['clang','-std=c11','-Wall','-Wextra','-Werror','-pedantic','-I',str(P),'-x','c','-o',str(exe),'-'],input=c,text=True,check=True)
  subprocess.run([str(exe)],check=True)
 return definition(source,'static BOOL MSAtlasMetadataReadable(')


def native(body,required):
 if platform.system()!='Darwin' or not shutil.which('xcrun'):
  print('SKIP native Foundation invalid metadata validator; no Apple runtime on iSH')
  if required: raise SystemExit(2)
  return
 test='''
int main(void){ @autoreleasepool {
assert(!MSAtlasMetadataReadable(nil)); assert(!MSAtlasMetadataReadable(@[]));
assert(!MSAtlasMetadataReadable(@"bad"));
assert(MSAtlasMetadataReadable(@{}));
assert(MSAtlasMetadataReadable(@{@"sourceKind":@"singleImage",@"layoutVersion":@3,@"variants":@1,@"selectedVariant":@0}));
for(id bad in @[@{},@[],@"3",@YES,@(-1),@4.5])
 assert(!MSAtlasMetadataReadable(@{@"sourceKind":@"singleImage",@"layoutVersion":bad}));
assert(!MSAtlasMetadataReadable(@{@"sourceKind":@[],@"layoutVersion":@3}));
assert(!MSAtlasMetadataReadable(@{@"layoutVersion":@5}));
assert(!MSAtlasMetadataReadable(@{@"actionPack":@{}}));
assert(!MSAtlasMetadataReadable(@{@"selectedVariant":@72}));
puts("NATIVE PASS actual Foundation metadata gate: array/dictionary fields/malformed types rejected, old missing fields accepted");
} }
'''
 with tempfile.TemporaryDirectory() as d:
  src=Path(d)/'main.m';src.write_text('#import <Foundation/Foundation.h>\n#import <CoreFoundation/CoreFoundation.h>\n#include <math.h>\n#include <assert.h>\n'+body+test)
  exe=Path(d)/'native';sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
  subprocess.run(['xcrun','clang','-fobjc-arc','-Wall','-Wextra','-Werror','-isysroot',sdk,str(src),'-framework','Foundation','-o',str(exe)],check=True)
  subprocess.run([str(exe)],check=True)


if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--require-native',action='store_true');opt=a.parse_args()
 native(portable(),opt.require_native)
