#!/usr/bin/env python3
"""Local production-path regression, no network/device/iOS compilation.
Executes current Pet/Effects method bodies translated to C ONLY at UIKit/ObjC
message/property seams. Foundation/QuartzCore decoding/delivery/timer scheduling
are fixture dependencies, NOT claimed to execute on Linux. Native runner keeps
its original Apple/authorized-CI gates; --require-native fails closed.
"""
from pathlib import Path
import argparse, hashlib, json, re, shutil, subprocess, sys, tempfile
HERE=Path(__file__).resolve().parent
FIX=HERE/'fixtures/minisight_pet_paths_20261122'

# Fail-closed extraction of DEFINITIONS, not a snapshot of old policy.
def method(text, signature):
    m=re.search(r'^'+re.escape(signature)+r'[^\n{;]*\{',text,re.M)
    if not m: raise AssertionError('missing definition '+signature)
    start=text.index('{',m.start()); i=start+1; depth=1
    while depth:
        if text[i]=='{': depth+=1
        elif text[i]=='}': depth-=1
        i+=1
    return text[m.start():i]

def strip_call(s,name):
    # Only diagnostics/assertions are removed. No behavioral call is skipped.
    while True:
        m=re.search(r'\b'+re.escape(name)+r'\s*\(',s)
        if not m: return s
        i=m.end(); depth=1; quote=False; escape=False
        while depth:
            c=s[i]
            if quote:
                if escape: escape=False
                elif c=='\\': escape=True
                elif c=='"': quote=False
            elif c=='"': quote=True
            elif c=='(': depth+=1
            elif c==')': depth-=1
            i+=1
        end=s.index(';',i)+1; s=s[:m.start()]+s[end:]

P_METHODS={
 'shouldAnimate':('bool','void'), 'mayRoam':('bool','void'),
 'measuredMusicInputAt:':('bool','double now'),
 'mayPerformMusicMotion':('bool','void'), 'roamOnce':('void','void'),
 'holdState:forDuration:':('void','int state, double duration'),
 'setRoamPace:':('void','double pace'), 'setSuspended:':('void','bool suspended'),
 'setRoamingPaused:':('void','bool paused'), 'setInteractionActive:':('void','bool active'),
 'setActivityActive:':('void','bool active'), 'setLyricsSuppressed:':('void','bool suppressed'),
 'setMotionLocked:forReason:':('void','bool locked, unsigned reason'), 'stopPlaying':('void','void'),
 'startPlaying':('void','void'), 'setCenterBounds:':('void','CGRect bounds'),
 'feasibleCenters':('MSRect','void'), 'clampedCenter:':('CGPoint','CGPoint point'),
 'setSpriteState:':('void','int state'), 'currentSpriteInterval':('double','void'),
 'frameCountForRow:':('int','int row'), 'applySpriteFrame':('void','void'),
 'restorePosterFrame':('void','void'), 'advanceSpriteAtTime:':('void','double now'),
 'frameTick:':('void','int timer'), 'setMusicPlaying:':('void','bool playing'),
 'scheduleDailyActionFrom:':('void','double now'), 'tryDailyActionAt:':('void','double now'),
 'cancelDailyAction':('void','void'), 'setDailyActionsEnabled:':('void','bool enabled'),
 'setRhythmFollowing:':('void','bool following'), 'clearRhythm':('void','void'),
 'resetRhythmForSession:':('void','uint64_t sessionToken'), 'checkRhythmAtTime:':('void','double now'),
 'applyRhythmFrame:receivedAt:':('void','MSRhythmFrame frame, double receivedAt'),
 'startMotionTo:jump:rest:':('void','CGPoint target, bool jump, double rest'),
 'beginDraggingAtPoint:':('void','CGPoint localPoint'),
 'updateDraggingTarget:':('void','CGPoint center'), 'endDraggingCancelled:':('void','bool cancelled'),
 'startMotionTo:jump:rest:':('void','CGPoint target, bool jump, double rest'),
 'motionTick:':('void','int link'), 'finishMotion':('void','void'),
 'beginLandingRecoveryWithImpact:':('void','double impact'),
 'clearLandingRecovery':('void','void'), 'cancelMotion':('void','void'),
 'scheduleRoam':('void','void'), 'reconcilePlaybackOnce':('void','void'),
 'gravityAngleAtTime:':('double','double now'),
 'setGravityLayerAngle:animated:':('void','double angle, bool animated'),
 'applyGravityTransformAtTime:':('void','double now'),
}
E_METHODS={
 'musicPosition':('double','void'), 'setMusicPosition:':('void','double position'),
 'setMusicPlaying:':('void','bool playing'), 'currentRole':('const char *','void'),
 'autonomyHeld':('bool','void'), 'landingRecoveryHeld':('bool','void'),
 'setLegacyState:waking:':('void','int state, bool waking'),
 'setFlightAngle:squash:active:':('void','double angle, double squash, bool active'),
 'setFloorImpactVelocity:':('void','double velocity'), 'setLandingRecoveryStage:':('void','int stage'),
 'beginDragAt:':('void','CGPoint localPoint'), 'dragTo:':('void','CGPoint center'),
 'endDragCancelled:':('CGPoint','bool cancelled'), 'land':('void','void'), 'setRunning:':('void','bool running'),
 'tick:':('void','int link'), 'resetRigidPresentation':('void','void'),
 'cancelDailyAction':('void','void'), 'setRhythmFollowing:':('void','bool following'),
 'applyRhythmStrength:pulse:':('void','double strength, double pulse'),
 'applyRhythmSampleTime:':('void','double sampleTime'),
}
P_SHIMS={'isActuallyVisible':'FixtureVisible','wakeForInteraction':'FixtureWake',
 'invalidateRoamTimer':'FixtureInvalidateRoam','invalidateFrameTimer':'FixtureInvalidateFrame',
 'ensureFrameTimer':'FixtureEnsureFrame','ensureMotionLink':'FixtureEnsureMotion',
 'cancelGravityImpulse':'FixtureCancelGravity','updateResidentAtTime:':'FixtureUpdateResident',
 'consumeAttentionAtTime:':'FixtureConsumeAttention','clearResidentForPlayback':'FixtureClearResident',
 'armRoamTimerWithDelay:':'FixtureArmRoam','reconcilePlayback':'P_reconcilePlaybackOnce'}
E_SHIMS={'chooseRole':'FixtureChooseRole','advanceActions:':'FixtureAdvanceActions',
 'presentationBlocked':'FixtureBlocked','hasDailyActions':'FixtureHasDailyActions','setRunning:':'FixtureSetRunning',
 'restorePoster':'FixtureRestorePoster','placeLyricsBlocked:':'FixtureLyrics',
 'requestFrame:':'FixtureRequestFrame','performDailyAction':'FixtureDailyActionDuration',
 'setTilt:sway:':'FixtureTilt', 'performIdleAction':'FixtureIdleAction'}

def cname(owner,key): return owner+'_'+key.split(':')[0]

def message(content,owner):
    receiver,rest=content.split(None,1)
    # Selector boundaries are top-level: a colon inside a nested call is not a selector.
    cuts=[]; depth=0; quoted=False
    for match in re.finditer(r'[()"]|\b(\w+):',rest):
        token=match.group(0)
        if token=='"': quoted=not quoted
        elif not quoted:
            if token=='(': depth+=1
            elif token==')': depth-=1
            elif depth==0: cuts.append((match.start(),match.end(),match.group(1)))
    if cuts:
        key=''.join(c[2]+':' for c in cuts)
        args=[rest[c[1]:(cuts[j+1][0] if j+1<len(cuts) else len(rest))].strip() for j,c in enumerate(cuts)]
    else: key=rest.strip(); args=[]
    if receiver=='self': target=owner
    elif receiver=='_effects': target='E'
    else: target=None
    if target:
        known=P_METHODS if target=='P' else E_METHODS
        shims=P_SHIMS if target=='P' else E_SHIMS
        if key in known: return cname(target,key)+'('+', '.join(args)+')'
        if key in shims: return shims[key]+'('+', '.join(args)+')'
    fixed={('CATransaction','begin'):'((void)0)',('CATransaction','commit'):'((void)0)',
      ('CATransaction','setDisableActions:'):'((void)0)',
      ('_motionLink','invalidate'):'FixtureInvalidateMotion()',
      ('_link','invalidate'):'FixtureEffectLinkStop()',
      ('_link','addToRunLoop:forMode:'):'FixtureEffectLinkStart()',
      ('CADisplayLink','displayLinkWithTarget:selector:'):'FixtureEffectLinkCreate()',
      ('_sprite','removeAnimationForKey:'):'((void)0)',
      ('_library','purgeFrames'):'FixturePurgeFrames()',
      ('super','setImage:'):'FixtureClearHostImage()',
      ('CAShapeLayer','layer'):'true',('UIBezierPath','bezierPath'):'FixturePath()',
      ('stars','moveToPoint:'):'FixtureMove(stars, '+', '.join(args)+')',
      ('stars','addLineToPoint:'):'FixtureLine(stars, '+', '.join(args)+')',
      ('stars','closePath'):'FixtureClose(stars)',
      ('_sprite','addSublayer:'):'((void)0)'}
    if (receiver,key) in fixed: return fixed[(receiver,key)]
    raise AssertionError('unmapped Objective-C seam: ['+content+']')

def definition(text,key):
    m=re.search(r'^- \([^)]+\)'+re.escape(key.split(':')[0])+r'\b[^\n;{]*\{',text,re.M)
    if not m: raise AssertionError('missing production selector '+key)
    sig=text[m.start():text.index('{',m.start())].rstrip()
    return method(text,sig)

def translate(raw,owner):
    s=raw[raw.index('{')+1:-1].replace('self->','')
    s=re.sub(r'//[^\n]*|/\*.*?\*/','',s,flags=re.S)
    s=strip_call(strip_call(s,'MSDiagEvent'),'NSAssert')
    s=re.sub(r'NSString \*source = [^\n]*;','',s)
    # ObjC object reads have controllable fixture metadata, not fake asset decoding.
    s=s.replace('_library.roles[@"land"].count','E.hasLand')
    s=s.replace('[_transientRole isEqualToString:@"idleAlt"]','FixtureRole(E.transientRole, "idleAlt")')
    s=s.replace('(MiniSightPetState)', '(int)')
    s=s.replace('_effects.rhythmFollowing = following;', '[_effects setRhythmFollowing:following];')
    s=s.replace('_effects.actionManifestPath.length','E.manifestPresent')
    s=re.sub(r'\[_role isEqualToString:@"(\w+)"\]',r'FixtureRole(E.role, "\1")',s)
    s=s.replace('[self->_role isEqualToString:self->_transientRole]','FixtureRole(E.role, E.transientRole)')
    s=s.replace('[@[@"tap", @"idleAlt", @"land", @"shakeSoft", @"shakeHard", @"wake"] containsObject:_role]','FixtureTransient(E.role)')
    s=s.replace('_clip.duration','E.clipDuration')
    s=s.replace('_link.preferredFramesPerSecond','E.linkFPS')
    s=s.replace('_bubble.hidden','E.bubbleHidden')
    s=s.replace('_preferredFPS','E.preferredFPS')
    s=s.replace('_dizzyStars.frame','D.frame').replace('_dizzyStars.path','D.path')
    s=s.replace('_dizzyStars.opacity','D.opacity').replace('_dizzyStars.hidden','D.hidden')
    s=s.replace('_dizzyStars.fillColor','D.fillColor').replace('_dizzyStars.strokeColor','D.strokeColor')
    s=s.replace('_dizzyStars.lineWidth','D.lineWidth').replace('_dizzyStars','E.starsExists')
    s=s.replace('_sprite.affineTransform','S.transform')
    s=s.replace('_gravityLayer.contentsRect','S.contentsRect').replace('_gravityLayer.contents','S.contents')
    s=s.replace('_sheet.CGImage','P.sheetExists').replace('_gravityLayer','P.layerExists')
    s=s.replace('self.layer.contents','P.hostContents')
    s=s.replace('UIColor.systemYellowColor.CGColor','1').replace('UIColor.labelColor.CGColor','2')
    s=s.replace('stars.CGPath','stars')
    s=s.replace('MiniSightPetView *pet = _pet;','void *pet = P.hasPet ? (void *)1 : NULL;')
    s=s.replace('UIView *viewport = pet.superview;','FixtureViewport *viewport = &Viewport;')
    s=s.replace('viewport.bounds','viewport->bounds')
    s=s.replace('UIBezierPath *stars','FixturePathData *stars')
    # Assignments still dispatch the real production setter/body where necessary.
    s=re.sub(r'_effects.musicPlaying = ([^;]+);',r'E_setMusicPlaying(\1);',s)
    s=re.sub(r'(?:self|pet).center = ([^;]+);',r'FixtureSetCenter(\1);',s)
    reads={'_effects.presentationBlocked':'FixtureBlocked()', '_effects.autonomyHeld':'E_autonomyHeld()',
      '_effects.landingRecoveryHeld':'E_landingRecoveryHeld()', '_effects.hasActions':'E.ownsSprite',
      '_effects.hasDailyActions':'FixtureHasDailyActions()',
      '_effects.musicPosition':'E_musicPosition()', '_effects.musicPlaying':'E.musicPlaying',
      '_effects.visualOffset':'E.visualOffset', '_effects.busy':'E.busy',
      'self.musicPosition':'E_musicPosition()', 'self.transform':'P.transform',
      'self.center':'P.center','self.bounds':'P.bounds',
      'pet.window.hidden':'P.windowHidden','pet.window':'P.windowExists',
      'pet.hidden':'P.hidden','pet.alpha':'P.alpha','pet.center':'P.center','pet.bounds':'P.bounds'}
    for old,new in reads.items(): s=s.replace(old,new)
    # Innermost message first. Array subscripts are C and stay untouched.
    while True:
        m=re.search(r'\[([A-Za-z_]\w*)\s+',s)
        if not m: break
        start=m.start(); depth=1; i=m.end(); quoted=False
        while depth:
            c=s[i]
            if c=='"' and s[i-1]!='\\': quoted=not quoted
            if not quoted:
                if c=='[': depth+=1
                elif c==']': depth-=1
            i+=1
        content=s[start+1:i-1]
        inner=re.search(r'\[([A-Za-z_]\w*)\s+',content)
        if inner:
            a=start+1+inner.start(); j=a+1; d=1
            while d:
                if s[j]=='[': d+=1
                elif s[j]==']': d-=1
                j+=1
            s=s[:a]+message(s[a+1:j-1],owner)+s[j:]
        else: s=s[:start]+message(content,owner)+s[i:]
    s=re.sub(r'\b(_[a-zA-Z]\w*)\b',lambda m:owner+'.'+m[1][1:],s)
    s=s.replace('(__bridge id)','').replace('@"','"')
    s=re.sub(r'\bnil\b','0',s)
    # Fixture types, without Objective-C ABI/code generation.
    for a,b in [('CFTimeInterval','double'),('NSTimeInterval','double'),('CGFloat','double'),
      ('NSInteger','int'),('NSUInteger','unsigned'),('BOOL','bool')]: s=re.sub(r'\b'+a+r'\b',b,s)
    if '@' in s or re.search(r'\b(?:self|pet)\.|\[[A-Za-z_]\w*\s+',s):
        raise AssertionError('untranslated production behavior in '+owner+': '+s)
    return s

def generate(pet,effects):
    effects=effects.split('@implementation MiniSightPetEffects',1)[1]
    declarations=[]; bodies=[]; evidence=[]
    state=re.search(r'typedef NS_ENUM\(NSInteger, MiniSightPetState\) \{.*?\};',pet,re.S).group(0)
    state=re.sub(r'//[^\n]*','',state).replace('typedef NS_ENUM(NSInteger, MiniSightPetState)','enum')
    constants=[]
    names=['kMiniSightPetRows','kMiniSightPetMaxCols','kMiniSightSpriteInterval',
      'kMiniSightIdleSpriteInterval','kMiniSightSleepSpriteInterval',
      'kMiniSightRoamActiveLo','kMiniSightRoamActiveHi','kMiniSightRoamIdleLo','kMiniSightRoamIdleHi',
      'kMiniSightWalkSpeed','kMiniSightWalkMinDuration','kMiniSightWalkMaxDuration',
      'kMiniSightJumpDuration','kMiniSightJumpDesiredHeight','kMiniSightJumpMinHeight', 'kMiniSightWaveHold']
    for name in names:
        line=re.search(r'^static const \w+ '+name+r' = [^;]+;',pet,re.M).group(0)
        constants.append(re.sub(r'const (NSInteger|NSTimeInterval)', lambda m: 'const double' if m[1] == 'NSTimeInterval' else 'const int', line))
    for owner,text,table in [('P',pet,P_METHODS),('E',effects,E_METHODS)]:
        for key,(kind,args) in table.items():
            raw=definition(text,key); translated=translate(raw,owner)
            if owner=='E' and key=='setFloorImpactVelocity:': translated='ObservedImpact = velocity; /* read-only entry instrumentation */\n'+translated
            name=cname(owner,key); declarations.append('static '+kind+' '+name+'('+args+');')
            bodies.append('/* Production selector '+key+' */\nstatic '+kind+' '+name+'('+args+') {\n'+translated+'\n}')
            evidence.append({'owner':owner,'selector':key,'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),
              'translated_sha256':hashlib.sha256(translated.encode()).hexdigest(),'raw':raw})
    callback=definition(effects,'requestFrame:')
    m=re.search(r'if \(first && self->_recoveryStage && \[self->_role isEqualToString:@"land"\]\) \{',callback)
    assert m, 'prepared land frame handoff removed'
    i=m.end();depth=1
    while depth:
        if callback[i]=='{':depth+=1
        elif callback[i]=='}':depth-=1
        i+=1
    raw=callback[m.start():i]
    translated=translate('{'+raw+'}','E')
    declarations.append('static void FixturePreparedFrame(bool first);')
    bodies.append('static void FixturePreparedFrame(bool first) {\n'+translated+'\n}')
    evidence.append({'owner':'E','selector':'requestFrame: prepared-land fragment',
      'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'raw':raw})
    timer=definition(pet,'armRoamTimerWithDelay:')
    raw=re.search(r'if \(!strongSelf[^\n]+\n\s*\[strongSelf roamOnce\];',timer).group(0)
    translated=translate('{'+raw.replace('strongSelf->_','_').replace('[strongSelf ','[self ')+'}','P')
    bodies.append('static void FixtureRoamCallback(bool strongSelf, unsigned generation, int fired) {\n'+translated+'\n}')
    evidence.append({'owner':'P','selector':'armRoamTimerWithDelay: captured callback guard',
      'raw_sha256':hashlib.sha256(raw.encode()).hexdigest(),'raw':raw})
    return state+'\n'+'\n'.join(constants+declarations+bodies)+'\n',evidence


def source_guards(pet,effects):
    effects=effects.split('@implementation MiniSightPetEffects',1)[1]
    advancing=definition(pet,'advanceSpriteAtTime:')
    assert advancing.index('BOOL poseFree') < advancing.index('if (_effects.hasActions) return;')
    assert '_effects.autonomyHeld' in advancing, 'music interrupts supplied tap/land action'
    dance=definition(effects,'tick:').split('    if (dance) {',1)[1].split('    MSPetLandingPresentation recoveryMark',1)[0]
    assert 'pet.center =' not in dance and 'sx = 1.; sy = 1.;' in dance and 'x = 0.;' in dance
    assert '_displayedFrame != NSNotFound' in definition(effects,'tick:')
    assert 'MSGravityBodyAbsorbHardFloor' in definition(pet,'motionTick:')
    assert '[self clearLandingRecovery]' in definition(pet,'cancelMotion')
    assert '[_effects land]' in definition(pet,'finishMotion')
    assert 'UIAccessibilityIsReduceMotionEnabled' in definition(pet,'frameTick:')
    assert '_dizzyStars.hidden = YES' in definition(effects,'setRunning:')
    assert '[_dizzyStars removeFromSuperlayer]' in effects or '[_dizzyStars removeFromSuperlayer]' in definition(effects,'invalidate') or '[_dizzyStars removeFromSuperlayer]' in effects.replace('removeFromSuperlayer','removeFromSuperlayer')


def main(argv=None):
    ap=argparse.ArgumentParser(description='Pet/Effects production-path host C regression')
    ap.add_argument('--trace',default=None,help='write JSON frame trace to this path')
    ap.add_argument('--evidence',default=None,help='write extracted production method hashes and seam list')
    ap.add_argument('--mutations',action='store_true',help='require compiled music behavior negatives to be rejected')
    ap.add_argument('--compiler',default=None,help='explicit host C compiler for bounded low-memory retries')
    ap.add_argument('--only-mutant',action='append',default=[],help='resume named negatives after a resource failure; default runs all five')
    ap.add_argument('--require-native',action='store_true',help='fail if Apple native runtime cannot run')
    args=ap.parse_args(argv)
    known_mutants = {'music-host-starved', 'center-frozen-until-finish', 'no-travelling-hops',
                     'no-music-motion-gate', 'stop-keeps-music-route'}
    if args.only_mutant and (not args.mutations or not set(args.only_mutant) <= known_mutants):
        ap.error('--only-mutant requires --mutations and exact known variant names')
    root=HERE.parent
    core=root/'src/ios/MiniSightCore' if (root/'src/ios/MiniSightCore/MiniSightPet.m').is_file() else root
    pet=(core/'MiniSightPet.m').read_text()
    effects=(core/'MiniSightPetEffects.m').read_text()
    header,evidence=generate(pet,effects)
    source_guards(pet,effects)
    if args.evidence:
        Path(args.evidence).write_text(json.dumps({'core':str(core),'methods':evidence,
            'pet_shims':P_SHIMS,'effects_shims':E_SHIMS,
            'limitations':'C translation only: no ObjC ABI, UIKit, QuartzCore, real NSTimer/CADisplayLink or ActionLibrary image decoding/delivery'},ensure_ascii=False,indent=2)+'\n')
    print('source guards PASS; %d production method bodies extracted'%len(evidence))
    cc=shutil.which(args.compiler) if args.compiler else (shutil.which('clang') or shutil.which('gcc'))
    if not cc:
        print('SKIP: no host C compiler; production-path control flow NOT executed')
        if args.require_native:
            print('FAIL: --require-native requested but Apple runtime and host C are unavailable')
            return 1
        return 0
    with tempfile.TemporaryDirectory() as tmp:
        td=Path(tmp)
        (td/'production-paths.h').write_text(header)
        shutil.copy(str(FIX/'driver.c'),str(td/'driver.c'))
        for case in ('rhythm_cases.c', 'rhythm_extra_cases.c', 'daily_fallback_cases.c', 'music_ordinary_cases.c'):
            shutil.copy(str(FIX/case), str(td/case))
        for name in ('MiniSightGeometry.h','MiniSightGravity.h','MiniSightLiveliness.h','MiniSightPetBehavior.h','MiniSightPetMusicMotion.h',
                     'MiniSightPetRhythmPolicy.h','MiniSightRhythmFrame.h','MiniSightPetDailyPolicy.h','MiniSightMusicAnimationClock.h'):
            shutil.copy(str(core/name),str(td/name))
        exe=td/'pet_paths'
        build=subprocess.run([cc,'-std=c99','-O1','-Wall','-Wno-unused-function','-I',str(td),
                              str(td/'driver.c'),'-lm','-o',str(exe)],capture_output=True,text=True)
        if build.returncode!=0:
            print(build.stdout);print(build.stderr)
            print('FAIL: host C compile failed')
            return 1
        run=[str(exe)]+((['--trace',args.trace]) if args.trace else [])
        result=subprocess.run(run,capture_output=True,text=True)
        print(result.stdout,end='')
        if result.returncode!=0:
            print(result.stderr,end='')
            print('FAIL: production-path scenarios failed')
            return 1
        if args.mutations:
            music=(core/'MiniSightPetMusicMotion.h').read_text()
            variants={
              'music-host-starved':(pet.replace('    if (!_rhythmFollowing && _effects.musicPlaying) {','    if (!_rhythmFollowing && _effects.musicPlaying) { return;'),music),
              'center-frozen-until-finish':(pet.replace('self.center = [self clampedCenter:MSPetCGPoint(sample)];','self.center = MSPetCGPoint(_motionStart);'),music),
              'no-travelling-hops':(pet,re.sub(r'travel.jump = [^;]+;', 'travel.jump = false;',music)),
              'no-music-motion-gate':(pet.replace('(_musicMotion && ![self mayPerformMusicMotion])','NO'),music),
            }
            playing=definition(pet,'setMusicPlaying:')
            # Stop now has three independent cleanup defenses: the setter's
            # direct cancel, its clearRhythm call, and reconcile's owned-music
            # gate. Break all three so this remains an unsafe behavioral mutant
            # rather than a safe variant rescued by the other real defense.
            missing_cancel=playing.replace('if (_musicMotion && !_physicsMotion && !_dragging) [self cancelMotion];','if (_musicMotion) { /* deliberately broken stop */ }')
            missing_cancel=missing_cancel.replace('[self clearRhythm];', '/* deliberately broken rhythm stop */')
            missing_stop=pet.replace(playing,missing_cancel)
            cleanup=definition(pet,'reconcilePlaybackOnce')
            broken_cleanup=cleanup.replace('((!_rhythmFollowing && _effects.musicPlaying) || _musicMotion)',
                '(!_rhythmFollowing && _effects.musicPlaying)')
            assert broken_cleanup != cleanup, 'stop cleanup negative must break the independent reconcile defense'
            missing_stop=missing_stop.replace(cleanup,broken_cleanup)
            variants['stop-keeps-music-route']=(missing_stop,music)
            for name,(mutated,policy) in variants.items():
                if args.only_mutant and name not in args.only_mutant: continue
                assert (mutated,policy)!=(pet,music), 'no-op mutation '+name
                generated,_=generate(mutated,effects)
                (td/'production-paths.h').write_text(generated)
                (td/'MiniSightPetMusicMotion.h').write_text(policy)
                build=subprocess.run([cc,'-std=c99','-O1','-Wall','-Wno-unused-function','-I',str(td),
                    str(td/'driver.c'),'-lm','-o',str(exe)],capture_output=True,text=True)
                if build.returncode:
                    print('FAIL: mutant must compile before runtime rejection: '+name+'\n'+build.stderr)
                    return 1
                rejected=subprocess.run([str(exe)],capture_output=True,text=True)
                if rejected.returncode!=1 or 'FAIL:' not in rejected.stderr:
                    print('FAIL: music mutant escaped: '+name+'\n'+rejected.stdout+rejected.stderr)
                    return 1
                print('REJECT compiled music mutant: '+name+' / '+rejected.stderr.strip())
    print('PASS: Pet/Effects production control flow executed on host C')
    print('SKIP: UIKit/QuartzCore/Foundation native behavior not executed on Linux')
    if args.require_native:
        print('FAIL: --require-native requested but Apple native runtime is unavailable')
        return 1
    return 0


if __name__=='__main__':
    raise SystemExit(main())
