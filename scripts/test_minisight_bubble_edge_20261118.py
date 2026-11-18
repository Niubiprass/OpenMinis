#!/usr/bin/env python3
"""Exact production bubble functions + real shared C geometry; no device/CI I/O.
macOS runs Foundation/QuartzCore with mocked UIKit and deterministic measurement.
Linux reports native SKIP; --require-native fails. Native mutants compile/run only
AFTER baseline compiles and passes. App mirror is self-contained, never reads P.
"""
from pathlib import Path
import argparse, hashlib, json, platform, re, shutil, subprocess, tempfile
ROOT=Path(__file__).resolve().parents[1]
IS_APP=(ROOT/'src/ios/MiniSightCore').is_dir()
CORE=ROOT/'src/ios/MiniSightCore' if IS_APP else ROOT
FIX=ROOT/'scripts/fixtures/minisight_bubble_edge_20261118'
SIGNATURES={
 'body':'static MSSize MiniSightBodySize(void)',
 'reserve':'static double MiniSightBubbleReserve(void)',
 'layout':'static MSLayout MiniSightLayoutNow(void)',
 'hide':'static void MiniSightHideBubble(void)',
 'place':'static void MiniSightPlaceBubble(CGFloat w, CGFloat h)',
 'show':'static void MiniSightShowBubbleWidth(NSString *raw, CGFloat maxW, NSUInteger cap)',
 'follow':'extern "C" void MiniSightFollowBubble(void)',
 'cancel':'static void MiniSightCancelConfirm(void)',
 'answer':'static void MiniSightAnswerConfirm(BOOL allow)',
 'confirm':'static void MiniSightShowConfirm(void)',
 'writer':'static void MiniSightWriteConfirmResult(BOOL allow)'}
def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()
def function(text,signature):
    m=re.search(re.escape(signature)+r'\s*\{',text); assert m,signature
    start=m.start(); opening=text.index('{',start); depth=0
    for i in range(opening,len(text)):
        if text[i]=='{': depth+=1
        elif text[i]=='}':
            depth-=1
            if not depth:return text[start:i+1]
    raise AssertionError('unbalanced '+signature)
def between(text,start,end):
    return text.split(start,1)[1].split(end,1)[0]
def extract(text):
    p={name:function(text,sig) for name,sig in SIGNATURES.items()}
    p['globals']='BOOL gMiniSightBubbleShown'+between(text,'BOOL gMiniSightBubbleShown','static NSString *gMiniSightLastLine')
    p['constants']='\n'.join(line for line in text.splitlines() if re.match(r'static const CGFloat kMiniSight(?:Width|Height|Edge|BubbleGap|BubbleReserve|ConfirmReserve)\s*=',line))
    for key,cls in [('tap','MiniSightBubbleTapTarget'),('target','MiniSightConfirmTarget')]:
        start='@interface '+cls+' : NSObject'
        p[key]=start+between(text,start,'static '+cls+' *')+'static '+cls+' *'+between(text,'static '+cls+' *',';')+';'
    destroy=function(text,'static void MiniSightDestroyUI(void)')
    start='    gMiniSightBubble = nil; gMiniSightBubbleScroll = nil;'
    p['reset']=start+between(destroy,start,'    gMiniSightPill = nil;')
    p['timeout']=next(line.strip() for line in p['confirm'].splitlines() if 'gMiniSightConfirmTimeout = dispatch_block_create' in line)
    return p

def source():
    meta=json.loads((FIX/'provenance.json').read_text())
    raw=(FIX/'source.json').read_bytes(); assert sha(raw)==meta['snapshot_sha256']
    snapshot=json.loads(raw)
    assert all(sha(v)==meta['piece_sha256'][k] for k,v in snapshot.items())
    p=snapshot if IS_APP else extract((ROOT/'Tweak.xm').read_text())
    assert p==snapshot,'production excerpts drifted: refresh audited mirror with provenance'
    layout=FIX/'MiniSightLayout.h' if IS_APP else ROOT/'MiniSightLayout.h'
    assert sha(layout.read_bytes())==meta['layout_sha256']
    assert sha((CORE/'MiniSightGeometry.h').read_bytes())==meta['geometry_sha256']
    for k in ('confirm','writer','answer','cancel'):
        assert sha(p[k])==meta['approval_before_sha256'][k],k+' changed approval behavior'
    assert sha(p['show'].replace('    gMiniSightBubbleDesiredSize = CGSizeMake(w, h);\n',''))==meta['show_before_sha256'],'width/font/cap styling changed'
    assert 'gMiniSightBubbleDesiredSize = CGSizeMake(w, h);' in p['show']
    assert p['show'].index('gMiniSightBubbleDesiredSize =')<p['show'].index('MiniSightPlaceBubble(w, h);')
    assert 'MiniSightPlaceBubble(gMiniSightBubbleDesiredSize.width, gMiniSightBubbleDesiredSize.height);' in p['follow']
    assert 'static CGPoint last' not in p['follow'] and '.bounds' not in p['follow']
    assert p['place'].index('gMiniSightBubble.frame =')<p['place'].index('!MSLayoutBubbleFits(')
    assert '(!gMiniSightPet || gMiniSightConfirming)' in p['place']
    assert 'if (gMiniSightPet && !gMiniSightConfirming)' in p['layout']
    assert 'layoutChanged || fabs(cx - gMiniSightBubbleTailX)' in p['place']
    for s in ('gMiniSightBubbleDesiredSize = CGSizeZero;','gMiniSightBubbleLayoutValid = NO;','gMiniSightBubbleTailX = -1.0;'):
        assert s in p['reset']
    assert 'MiniSightAnswerConfirm(NO);' in p['cancel'] and 'MiniSightAnswerConfirm(NO);' in p['timeout']
    for s in ('@selector(deny:)','@selector(allow:)','@"拒绝"','@"允许"','55 * NSEC_PER_SEC'):
        assert s in p['confirm']
    print('PASS source: logical size, no center-only cache, frame-before-no-fit, unchanged approval/width/font')
    return p,layout

def run(argv):
    return subprocess.run(argv,text=True,capture_output=True,timeout=120)
def compiled(compiler,flags,src,exe,expected=None):
    b=run([compiler,*flags,str(src),'-o',str(exe),'-lm'])
    assert b.returncode==0,'compile failure is NOT a killed mutant:\n'+b.stdout+b.stderr
    r=run([str(exe)])
    if expected:
        assert r.returncode==1 and expected in r.stderr,(r.returncode,r.stdout,r.stderr)
    else:
        assert r.returncode==0,(r.returncode,r.stdout,r.stderr)
        print(r.stdout.strip())

def portable(layout):
    cc=shutil.which('cc') or shutil.which('clang'); assert cc,'C compiler required'
    with tempfile.TemporaryDirectory(prefix='ms-bubble-c-') as d:
        d=Path(d)
        (d/'MiniSightLayout.h').write_bytes(layout.read_bytes())
        src=d/'main.c'; src.write_text('#include "MiniSightLayout.h"\n#include "portable_cases.h"\nint main(void) { printf("PASS actual C bubble geometry: %ld checks (not Show/Follow)\\n",MSBubbleEdgeCases()); return 0; }\n')
        flags=['-std=c11','-Wall','-Wextra','-Werror','-pedantic','-I',str(d),'-I',str(CORE),'-I',str(FIX)]
        compiled(cc,flags,src,d/'baseline')
        h=layout.read_text(); anchor='    double top = anchor.y - L.body.h * .5;'
        assert h.count(anchor)==1
        (d/'MiniSightLayout.h').write_text(h.replace(anchor,'    return 1;\n'+anchor))
        compiled(cc,flags,src,d/'unsafe-fit','FAIL C bubble')
        print('PASS compiled C negative: fit-always-true rejected (baseline first)')

def assembled(p):
    order=('constants','globals','body','reserve','layout','hide','place','tap','show','follow','target','cancel','answer')
    return '\n\n'.join(p[k] for k in order)+'\nstatic void FixtureResetBubble(void) {\n'+p['reset']+'}\nstatic void FixtureArmConfirmTimeout(void) {\n'+p['timeout']+'\n}\n'
def native(p,layout,required):
    if platform.system()!='Darwin' or not shutil.which('xcrun'):
        print(('FAIL' if required else 'SKIP')+' native exact Show/Place/Follow + approval: Apple Foundation/QuartzCore unavailable; native baseline and mutants NOT_RUN')
        return not required
    cc=subprocess.check_output(['xcrun','--find','clang++'],text=True).strip()
    sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
    with tempfile.TemporaryDirectory(prefix='ms-bubble-native-') as tmp:
        d=Path(tmp);(d/'MiniSightLayout.h').write_bytes(layout.read_bytes())
        text=(FIX/'native.mm').read_text(); assert text.count('// PRODUCTION_EXCERPT')==1
        variants=[('baseline',dict(p),None)]
        bad=dict(p)
        bad['show']=bad['show'].replace('    gMiniSightBubbleDesiredSize = CGSizeMake(w, h);\n','')
        bad['follow']=bad['follow'].replace('gMiniSightBubbleDesiredSize.width, gMiniSightBubbleDesiredSize.height','gMiniSightBubble.bounds.size.width, gMiniSightBubble.bounds.size.height')
        frame='    gMiniSightBubble.frame = CGRectMake(box.x, box.y, box.w, box.h);\n'
        bad['place']=bad['place'].replace(frame,'').replace('    gMiniSightBubble.alpha = 1.;',frame+'    gMiniSightBubble.alpha = 1.;')
        variants.append(('old-no-size',bad,'FAIL native bubble: first top 160x52 then middle'))
        bad=dict(p);bad['follow']=bad['follow'].replace('    // Center alone', '    static CGPoint last;\n    if (CGPointEqualToPoint(last, host.center) && gMiniSightBubble.frame.size.height > 0) return;\n    last = host.center;\n    // Center alone')
        variants.append(('old-center-only',bad,'FAIL native bubble: stationary viewport clipped then restored'))
        bad=dict(p);bad['follow']=bad['follow'].replace('gMiniSightBubbleDesiredSize.width, gMiniSightBubbleDesiredSize.height','gMiniSightBubble.bounds.size.width, gMiniSightBubble.bounds.size.height')
        variants.append(('clipped-bounds',bad,'FAIL native bubble: stationary viewport clipped then restored'))
        bad=dict(p);bad['place']=bad['place'].replace('layoutChanged || fabs(cx - gMiniSightBubbleTailX)','fabs(cx - gMiniSightBubbleTailX)')
        variants.append(('stale-tail',bad,'FAIL native bubble: hidden long then short text'))
        # A baseline build/run failure raises immediately; no negative is counted.
        for name,actual,expected in variants:
            assert name=='baseline' or actual!=p,name+' ineffective mutation'
            src=d/'main.mm';src.write_text(text.replace('// PRODUCTION_EXCERPT',assembled(actual)))
            flags=['-std=c++17','-isysroot',sdk,'-fobjc-arc','-fblocks','-Wall','-Wextra','-Werror=return-type',
                   '-Wno-unused-function','-Wno-unused-variable','-I',str(d),'-I',str(CORE),'-I',str(FIX),
                   '-framework','Foundation','-framework','CoreGraphics','-framework','QuartzCore']
            compiled(cc,flags,src,d/name,expected)
            if expected:print('PASS native compiled assertion mutant rejected:',name)
    return True

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--require-native',action='store_true')
    args=ap.parse_args();p,layout=source();portable(layout)
    return 0 if native(p,layout,args.require_native) else 1
if __name__=='__main__':raise SystemExit(main())
