#!/usr/bin/env python3
"""Wake integration contracts + REAL portable C/Apple Foundation gates.
No device/microphone, sample inference, chat request or local iOS compilation.
"""
import argparse, hashlib, json, platform, re, shutil, subprocess, sys, tempfile
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT/'src/ios'
FIX = ROOT/'scripts/fixtures/minisight_wake_20261116'
ASSETS = IOS/'Resources/MiniSightWake'

def read(name): return (IOS/name).read_text()
def require(value, name):
    if not value: raise AssertionError(name)

def source_gate():
    c=read('MiniSightWakeController.swift'); e=read('MiniSightWakeEngine.swift')
    p=read('MiniSightCore/MiniSightChatPanel.m'); h=read('MiniSightCore/MiniSightChatPanel.h')
    settings=read('MiniSightSettings.swift'); store=read('MiniSightConfigStore.swift')
    ui=read('Views/Settings/MiniSightWakePage.swift'); runtime=read('MiniSightInAppRuntime.swift')
    checks={
        'separate local KWS': 'SherpaOnnxCreateKeywordSpotter(&config)' in e and 'SFSpeech' not in e,
        'three-buffer bound': 'queuedBuffers < 3' in e,
        'C-string constructor lifetime': 'definition.withCString' in e and 'files.encoder.path.withCString' in e,
        'gap fresh stream': 'self.stream = SherpaOnnxCreateKeywordStream(spotter)' in e,
        'no KWS audio file/network': not re.search(r'URLSession|URLRequest|AVAudioFile|\.write\(', e),
        'current token + epoch': 'self.audioEpoch == epoch' in e and 'self.current == token' in e,
        'bounded first presentation': '800_000_000' in c and 'waitingForAnchor' in c,
        'real host anchor': 'panel.anchorView = anchor' in c and 'registerPetAnchor(pet)' in runtime,
        'weak panel lifetime': 'private weak var responsePanel' in c,
        'response lifecycle gate': 'MSNameWakeMayStartInput(' in p and 'isNameWakeResponseCurrent(generation:' in c,
        'cancel not hardcoded': 'cancelled: false' not in c and 'nameWakeCancellationHandler' in c,
        'old hit rejected on handoff': 'currentResponse(token)' in c and 'beginNameWakeVoiceInput(generation: generation)' in c,
        'speaker tail gap': '200_000_000' in c,
        'keyboard/name only cancellation': 'if (self.voiceFromNameWake) [self cancelVoice];' in p,
        'close/reopen invalidate': p.count('[self invalidateNameWakeResponse]') >= 6,
        'no automatic send': 'sendTapped' not in c and '.send(' not in c,
        'guard foreground + protected data': 'applicationState == .active' in c and 'isProtectedDataAvailable' in c,
        'system recording/call guards': 'UIScreen.main.isCaptured' in c and 'RPScreenRecorder.shared().isRecording' in c and 'calls.calls' in c,
        'renderer actual readback': 'd.integer(forKey: MiniSightSettingKey.renderer) == 1' in c,
        'style actual readback': 'd.integer(forKey: MiniSightSettingKey.style) == 1' in c,
        'background companion request': 'remote.post(action: "hit"' in c and 'remote.post(action: "ready"' in c,
        'real input pulse': 'pulse.markFrame(inputToken:' in c and 'pulse.isFresh(now:' in c,
        'permission only explicit': 'manager.requestPermissions()' in c and 'if !enabled' in c,
        'cross-App voice claim': 'func claimNameWakeVoice(' in c and 'func nameWakeVoiceStarted(' in c,
        'normal final preserves draft': 'nameWakeVoiceFinishedHandler' in p,
        'view teardown is not OFF': 'wake.presentationDetached()' in runtime,
        'App-level lifecycle observers': 'UIApplication.didEnterBackgroundNotification' in c,
        'no elevated process': 'beginBackgroundTask' not in c and 'openURL' not in c,
        'paired identity save': 'saveWakeIdentity(prepared)' in c and 'loaded = false' in store,
        'generation on permissions': 'self.enableGeneration == request' in c,
        'explicit UI disclosure': 'confirmationDialog("允许本机名字监听？"' in ui,
        'iOS15 text entry': '.autocorrectionDisabled()' not in ui and '.disableAutocorrection(true)' in ui,
        'runtime default OFF': 'MiniSightSettingKey.wakeEnabled: false' in settings,
        'all 51 settings kept': 'runtimeFields.count == 51' in settings,
    }
    for name,ok in checks.items(): require(ok,name)
    for field in ['wakeEnabled','wakeName','wakePronunciation']:
        require(f'case MiniSightSettingKey.{field}: return {field}' in store, 'persist '+field)
        require(f'MiniSightSettingKey.{field}:' in settings, 'snapshot '+field)
    project=read('Minis.xcodeproj/project.pbxproj')
    for name in ['Controller','Engine','Assets','Name','Policy','Remote','AudioPulse','Page']:
        require(project.count('MiniSightWake'+name+'.swift in Sources')==2, 'PBX '+name)
    require('relativePath = Packages/MiniSightKeywordRuntime;' in project,'local binary package')
    workflow = (ROOT/'.github/workflows/openminis-app.yml').read_text()
    require('id: source_gate' in workflow, 'CI must retain the native validation outcome')
    package = workflow.split('- name: Package without adding elevated entitlements', 1)[1]
    require('if [ "${{ steps.source_gate.outcome }}" != success ]; then' in package and
            package.index('steps.source_gate.outcome') < package.index('APP=DerivedData/'),
            'Failed native validation must block every IPA publication')
    manifest=json.loads((ASSETS/'manifest.json').read_text())
    require({x['file'] for x in manifest['files']}=={'encoder.onnx','decoder.onnx','joiner.onnx','tokens.txt'},'model-only resources')
    for row in manifest['files']:
        data=(ASSETS/row['file']).read_bytes()
        require(len(data)==row['bytes'] and hashlib.sha256(data).hexdigest()==row['sha256'], 'asset SHA '+row['file'])
        require(row['sha256'] in read('MiniSightWakeAssets.swift'),'code pin '+row['file'])
    require(not list(ASSETS.rglob('*.wav')) and not list(ASSETS.rglob('keywords*.txt')),'no sample keywords/audio')
    require((ASSETS/'Licenses/STATIC-NOTICE-WITH-GAPS.md').is_file(),'license status retained')
    print('PASS wake source: '+str(len(checks))+' guards + 51-key wiring + four pinned model/token files')
    return manifest

def portable():
    compiler=shutil.which('cc') or shutil.which('clang')
    require(compiler,'portable C compiler missing')
    header=IOS/'MiniSightCore/MiniSightNameWakeGate.h'
    original=header.read_text()
    with tempfile.TemporaryDirectory(prefix='ms-wake-gate-',dir='/tmp') as d:
        folder=Path(d); binary=folder/'gate'
        def build(text):
            (folder/header.name).write_text(text)
            subprocess.run([compiler,'-std=c11','-Wall','-Wextra','-Werror','-O2','-I'+str(folder),str(FIX/'panel_gate.c'),'-o',str(binary)],check=True,timeout=40)
        build(original); subprocess.run([str(binary)],check=True,timeout=15)
        mutants=[original.replace('expected == identity && ','((void)identity, true) && ',1),
                 original.replace('!editing && ','((void)editing, true) && ',1)]
        for text in mutants:
            require(text!=original,'mutation applied'); build(text)
            run=subprocess.run([str(binary)],capture_output=True,text=True,timeout=15)
            require(run.returncode!=0,'unsafe panel mutation accepted')
    print('PASS two unsafe mutation negatives (identity/keyboard takeover)')

def native(required):
    if platform.system()!='Darwin' or not shutil.which('xcrun'):
        print('SKIP Apple Foundation policy/assets behavior: no Apple Swift/SDK')
        if required: raise RuntimeError('native Foundation REQUIRED; unavailable')
        return
    compiler=subprocess.check_output(['xcrun','--find','swiftc'],text=True).strip()
    sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True,timeout=30).strip()
    require(Path(sdk).is_dir(), 'Apple macOS SDK missing; Foundation tests did not run')
    with tempfile.TemporaryDirectory(prefix='ms-wake-foundation-') as d:
        binary=Path(d)/'wake-foundation'
        subprocess.run([compiler,'-sdk',sdk,'-swift-version','5',str(IOS/'MiniSightWakePolicy.swift'),str(IOS/'MiniSightWakeAssets.swift'),
            str(IOS/'MiniSightWakeName.swift'),str(FIX/'main.swift'),'-o',str(binary)],check=True,timeout=120)
        subprocess.run([str(binary),str(ASSETS)],check=True,timeout=45)

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--require-native',action='store_true')
    ap.add_argument('--require-ios',action='store_true');ap.add_argument('--require-release-license',action='store_true')
    a=ap.parse_args()
    try:
        manifest=source_gate();portable();native(a.require_native)
        if a.require_ios:
            from test_minisight_wake_ios_20261116 import typecheck
            typecheck()
        else: print('SKIP iOS Swift/UIKit/C-API typecheck: not requested/authorized here')
        if a.require_release_license:
            from test_minisight_keyword_provenance_20261116 import artifact_gate
            artifact_gate()  # Includes actual Eigen/JSON compiled-header/source correspondence.
            require((ASSETS/'Licenses/CorrespondingSource/eigen-5.0.1.tar.gz').is_file(),
                    'Corresponding covered source missing from App resources')
            print('PASS release source obligations: controlled build proof verified; historical prebuilt gaps superseded')
        return 0
    except (AssertionError,RuntimeError,OSError,subprocess.SubprocessError) as exc:
        print('FAIL '+str(exc),file=sys.stderr);return 1
if __name__=='__main__':sys.exit(main())
