#!/usr/bin/env python3
"""Shared C behavior + exact production Swift layout on Apple; no device/CI dispatch.
Plugin CI uses --portable-only (no App source in that repository).
--require-native never treats absent Apple Swift as successful execution.
"""
from pathlib import Path
import argparse, os, platform, shutil, subprocess, tempfile, re
ROOT=Path(__file__).resolve().parents[1]
CORE=ROOT/'src/ios/MiniSightCore' if (ROOT/'src/ios/MiniSightCore').is_dir() else ROOT
FIX=ROOT/'scripts/fixtures/minisight_pet_bounds_20261118'
IS_APP=CORE!=ROOT

def method(text, marker):
    definition=re.search(re.escape(marker.rstrip(' {'))+r'[^\n;]*\{',text)
    assert definition,'missing function definition: '+marker
    start=definition.start(); opening=text.index('{',start)
    depth=0
    for i in range(opening,len(text)):
        if text[i]=='{': depth+=1
        elif text[i]=='}':
            depth-=1
            if not depth:return text[start:i+1]
    raise AssertionError('unbalanced source method')

def source():
    effects=(CORE/'MiniSightPetEffects.m').read_text()
    assert 'MSPetFitVisualTransform(' in effects
    assert 'transform = CGAffineTransformMake(fitted.a, fitted.b, fitted.c, fitted.d, fitted.tx, fitted.ty);' in effects
    assert '_visualOffset.x += fitted.tx - transform.tx;' in effects
    if IS_APP:
        runtime=(ROOT/'src/ios/MiniSightInAppRuntime.swift').read_text()
        layout=method(runtime.split('private final class MiniSightPassthroughView:',1)[1],'override func layoutSubviews()')
        assert 'MSBodyCenterBounds(' in layout
        assert 'pet.gravitySafeSize' in layout and 'pet.center = pet.center' in layout
        assert 'safeAreaInsets' not in layout and '+ 24' not in layout
        assert 'MiniSightCore/MiniSightGeometry.h' in (ROOT/'src/ios/MinisApp-Bridging-Header.h').read_text()
        return layout
    tweak=(ROOT/'Tweak.xm').read_text()
    body=method(tweak,'static MSLayout MiniSightLayoutNow(void)')
    assert 'MSLayout layout = MSLayoutMake(' in body
    pet=method(body,'if (gMiniSightPet && !gMiniSightConfirming)')
    assert 'layout.centers = MSBodyCenterBounds(' in pet
    assert body.index('if (gMiniSightPet && !gMiniSightConfirming)') < body.index('MSBodyCenterBounds(')
    assert 'L.centers = MSCenterBounds(L.safe, L.body, L.gap + L.headroom);' in (ROOT/'MiniSightLayout.h').read_text()
    place=method(tweak,'static void MiniSightPlaceBubble(CGFloat w, CGFloat h)')
    assert '(!gMiniSightPet || gMiniSightConfirming)' in place
    assert place.index('gMiniSightBubble.frame =') < place.index('!MSLayoutBubbleFits(')
    assert 'gMiniSightBubble.alpha = 0.;' in place and 'gMiniSightBubble.alpha = 1.;' in place
    assert 'placing = NO;\n        return;' in place
    pan=method(tweak,'- (void)handlePan:(UIPanGestureRecognizer *)pan {')
    cancelled=pan.split('default:',1)[1]
    assert 'endDraggingCancelled:YES' in cancelled and 'MSMiniSightSetPreference' not in cancelled
    return None

def run_c(header, reject=False):
    cc=shutil.which('cc') or shutil.which('clang')
    assert cc,'Portable C compiler required'
    with tempfile.TemporaryDirectory(prefix='ms-body-bounds-') as d:
        d=Path(d);(d/'MiniSightGeometry.h').write_text(header)
        subprocess.run([cc,'-std=c11','-Wall','-Wextra','-Werror','-pedantic','-I',str(d),str(FIX/'bounds.c'),'-lm','-o',str(d/'bounds')],check=True,timeout=90)
        p=subprocess.run([str(d/'bounds')],text=True,capture_output=True,timeout=90)
        if reject:
            assert p.returncode==1 and 'FAIL bounds line' in p.stderr,(p.stdout,p.stderr)
        else:
            assert p.returncode==0,(p.stdout,p.stderr)
            assert 'PASS actual MSBodyCenterBounds:' in p.stdout
            print(p.stdout.strip())

def native(layout, required):
    if layout is None:raise AssertionError('native App source absent; plugin must select --portable-only')
    if platform.system()!='Darwin' or not shutil.which('xcrun'):
        print(('FAIL' if required else 'SKIP')+' native production host: Apple Swift unavailable (not PASS)')
        return not required
    swift=subprocess.check_output(['xcrun','--find','swiftc'],text=True).strip()
    sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
    with tempfile.TemporaryDirectory(prefix='ms-host-bounds-') as d:
        d=Path(d);bridge=d/'bridge.h';bridge.write_text('#include "MiniSightGeometry.h"\n')
        template=(FIX/'host.swift').read_text()
        assert template.count('// PRODUCTION_LAYOUT_METHOD')==1
        # Compile the actual method again with just the body radius erased.
        # A compile failure is never accepted as a behavior-negative success.
        cases=[('baseline',layout),('no-body-size',layout.replace(
            'w: Double(body.width), h: Double(body.height)',
            'w: Double(body.width) * 0, h: Double(body.height) * 0'))]
        assert cases[1][1]!=layout
        for name,actual in cases:
            src=d/'main.swift';src.write_text(template.replace('// PRODUCTION_LAYOUT_METHOD',actual))
            binary=d/name
            subprocess.run([swift,'-swift-version','5','-warnings-as-errors','-sdk',sdk,'-I',str(CORE),'-import-objc-header',str(bridge),str(src),'-o',str(binary)],check=True,timeout=120)
            p=subprocess.run([str(binary)],text=True,capture_output=True,timeout=25)
            if name=='baseline':
                assert p.returncode==0 and 'PASS native production layoutSubviews:' in p.stdout,(p.stdout,p.stderr)
                print(p.stdout.strip())
            else:assert p.returncode==1 and 'FAIL native host:' in p.stderr,(p.stdout,p.stderr)
        print('PASS compiled native host negative: removed body size rejected')
    return True

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--portable-only',action='store_true');p.add_argument('--require-native',action='store_true')
    a=p.parse_args();assert not(a.portable_only and a.require_native)
    layout=source();print('PASS source wiring: body envelope retained; no permanent bubble/safe-area reserve')
    h=(CORE/'MiniSightGeometry.h').read_text();run_c(h)
    for before,after in [('double edge = MSClamp(inset, 0., 2.);','double edge = 80.; (void)inset;'),('edge + halfW, right = width - edge - halfW','edge + halfW * 0, right = width - edge - halfW * 0')]:
        assert h.count(before)==1;run_c(h.replace(before,after),True)
    bad=h.replace('    t.tx = MSClamp(center.x + t.tx,', '    return t;\n    t.tx = MSClamp(center.x + t.tx,')
    assert bad!=h;run_c(bad,True)
    print('PASS 3 compiled C negatives: wide margin, missing body radius, missing visual edge fit rejected')
    if a.portable_only:print('NOT_RUN native App host: explicit portable-only');return 0
    return 0 if native(layout,a.require_native) else 1
if __name__=='__main__':
    raise SystemExit(main())
