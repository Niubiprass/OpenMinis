#!/usr/bin/env python3
"""Retired name-wake must never claim input. Source gates + actual Apple host tests.
No real permissions, mic, user defaults or bridge files. Strict fails without Apple.
"""
from pathlib import Path
import argparse, platform, re, shutil, subprocess, tempfile, unittest, sys
ROOT=Path(__file__).resolve().parents[1]
APP=ROOT if (ROOT/'src/ios').is_dir() else None
PLUGIN=ROOT if (ROOT/'MiniSightNameWakeHost.h').is_file() else ROOT.parent.parent/'MiniSight-complete-20261105/debs/MiniSight'
OPTIONS=argparse.Namespace(require_native=False)

def function(s,marker):
    m=re.search(r'^\s*'+re.escape(marker)+r'[^;{]*\{',s,re.M); assert m,marker
    i=s.index('{',m.start())+1;d=1
    while d:
        if s[i]=='{': d+=1
        elif s[i]=='}': d-=1
        i+=1
    return s[m.start():i].strip()

def check_controller(s):
    assert 'var backgroundAudioIsLive: Bool { false }' in s
    assert 'var isNameWakeDisabled: Bool { true }' in s
    assert 'func requestEnabled(_ enabled: Bool)' in s
    assert 'UserDefaults.standard.set(false, forKey: MiniSightSettingKey.wakeEnabled)' in function(s,'func requestEnabled(')
    for x in ['AVAudioEngine(', 'MiniSightWakeEngine(', 'requestPermissions(', 'requestRecordPermission(', 'input.start(', 'remote.install(', 'Timer.scheduledTimer', 'AVSpeechSynthesizer(']:
        assert x not in s, x

def check_host(s):
    for marker in ['static void MiniSightNameWakeReadRequest(', 'static void MiniSightNameWakeUpdate(', 'static void MiniSightNameWakeCancel(']:
        body=function(s,marker)
        for x in ['readRequestInContainer', 'timerWithTimeInterval', 'showNameWakeResponse', 'beginNameWakeVoiceInput', 'publishContainer', 'cancelNameWakeRequestForToken']:
            assert x not in body, marker+':'+x
    assert 'gMiniSightNameWakeToken = nil' in s
    assert 'gMiniSightNameWakePresentationHeld = NO' in s

class Source(unittest.TestCase):
    def test_controller_disabled_and_real_old_source_rejected(self):
        if APP is None:self.skipTest('App source unavailable in independent plugin build; plugin gate remains required')
        s=(APP/'src/ios/MiniSightWakeController.swift').read_text();check_controller(s)
        # Old active implementation must be rejected by the same contract.
        r=subprocess.run(['git','show','HEAD:src/ios/MiniSightWakeController.swift'],cwd=APP,text=True,capture_output=True)
        if r.returncode==0 and 'AVAudioEngine()' in r.stdout:
            with self.assertRaises(AssertionError):check_controller(r.stdout)
        with self.assertRaises(AssertionError):check_controller(s.replace('var backgroundAudioIsLive: Bool { false }','var backgroundAudioIsLive: Bool { true }'))
        store=(APP/'src/ios/MiniSightConfigStore.swift').read_text()
        self.assertIn('wakeEnabled = false',store)
        home=(APP/'src/ios/Views/Settings/MiniSightHomePage.swift').read_text()
        self.assertNotIn('MiniSightWakePage()',home)
        launch=(APP/'src/ios/MinisApp.swift').read_text()
        self.assertIn('MiniSightVoiceBridge.shared.install()',launch)
        self.assertNotIn('MiniSightWakeController.shared.install()',launch)
        self.assertIn('feature_removed',launch)
    def test_manual_entry_preserved_and_legacy_request_cannot_fallthrough(self):
        if APP is None:self.skipTest('App manual bridge source not mounted')
        voice=(APP/'src/ios/MiniSightVoiceBridge.swift').read_text()
        branch=voice.split('if object["source"] as? String == "nameWake" {',1)[1].split('\n        }',1)[0]
        self.assertIn('return',branch);self.assertNotIn('handleNameWakeRequest(',branch)
        self.assertNotIn('SpeechRecognitionManager.shared',branch)
        self.assertIn('legacy_request_rejected',branch)
        self.assertNotIn('startListening(generation:',branch)
        self.assertIn('try manager.startRecording()',voice)
        speech=(APP/'src/ios/Agent/Speech/SpeechRecognitionManager.swift').read_text()
        start=function(speech,'func startRecording(nameWake: Bool = false) throws')
        self.assertIn('guard !nameWake else',start)
        self.assertLess(start.index('guard !nameWake else'),start.index('beginAndWait(intent)'))
        panel=(APP/'src/ios/MiniSightCore/MiniSightChatPanel.m').read_text()
        self.assertIn('语音输入',panel);self.assertIn('beginVoiceInput',panel)
    def test_plugin_no_poll_no_ui_no_audio(self):
        if not PLUGIN.is_dir(): self.skipTest('plugin source not mounted; independent plugin gate must run')
        s=(PLUGIN/'MiniSightNameWakeHost.h').read_text();check_host(s)
        with self.assertRaises(AssertionError):check_host(s.replace('static void MiniSightNameWakeReadRequest(void) {','static void MiniSightNameWakeReadRequest(void) { readRequestInContainer();'))
        tweak=(PLUGIN/'Tweak.xm').read_text()
        makefile=(PLUGIN/'Makefile').read_text()
        self.assertNotIn('MiniSightNameWakeBridge.m', makefile)
        self.assertNotIn('MiniSightNameWakeBridge.h', tweak)
        self.assertNotIn('MSNWRequestNote', tweak)
        self.assertIn('MiniSightUpdateMusic();',tweak)
        self.assertIn('MiniSightChatPanel',tweak)

class Native(unittest.TestCase):
    def tools(self):
        if platform.system()!='Darwin' or not shutil.which('xcrun'):
            message='Apple native retirement/Swift behavior NOT_RUN: no Apple toolchain'
            if OPTIONS.require_native:self.fail(message)
            self.skipTest(message)
        sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
        clang=subprocess.check_output(['xcrun','--find','clang'],text=True).strip()
        return sdk,clang
    def test_real_plugin_host_inert_calls(self):
        sdk,clang=self.tools()
        if not PLUGIN.is_dir(): self.skipTest('independent App runner has no plugin tree; separate plugin gate required')
        with tempfile.TemporaryDirectory(prefix='ms-retire-host-') as directory:
            d=Path(directory);s='''#import <Foundation/Foundation.h>
#include <stdio.h>
#import "MiniSightLog.h"
static NSString *gMiniSightNameWakeToken, *gMiniSightContainer;
static BOOL gMiniSightNameWakePresentationHeld, gMiniSightNameWakeCancelling;
#include "MiniSightNameWakeHost.h"
int main(void) { @autoreleasepool {
    gMiniSightNameWakeToken=@"old";gMiniSightNameWakePresentationHeld=YES;
    MiniSightNameWakeUpdate();
    if(gMiniSightNameWakeToken || gMiniSightNameWakePresentationHeld)return 1;
    MiniSightNameWakeReadRequest();MiniSightNameWakeCancel(@"cancelled",YES);
    if(gMiniSightNameWakeToken || gMiniSightNameWakePresentationHeld)return 2;
    puts("NATIVE PASS retirement: real plugin host cannot poll, present, or claim input");
    return 0;
} }
'''
            (d/'main.m').write_text(s)
            r=subprocess.run([clang,'-isysroot',sdk,'-fobjc-arc','-Wall','-Wextra','-Werror','-I',str(PLUGIN),str(d/'main.m'),str(PLUGIN/'MiniSightLog.m'),'-framework','Foundation','-o',str(d/'host')],text=True,capture_output=True,timeout=120)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            r=subprocess.run([str(d/'host')],text=True,capture_output=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr);print(r.stdout.strip())
    def test_actual_controller_rejects_legacy_enable_and_claim(self):
        sdk,_=self.tools()
        if APP is None:self.skipTest('controller is tested by independent App native suite')
        swift=subprocess.check_output(['xcrun','--find','swiftc'],text=True).strip()
        with tempfile.TemporaryDirectory(prefix='ms-retire-swift-') as directory:
            d=Path(directory)
            source=(APP/'src/ios/MiniSightWakeController.swift').read_text().replace('import UIKit','typealias UIView = NSObject')
            source+='''
enum MiniSightSettingKey { static let wakeEnabled="fixture.wake" }
enum MiniSightWakeName { struct Prepared { let pronunciation: String } }
final class FixtureDefaults { var on=true; func set(_ value: Bool, forKey: String) { on=value } }
enum UserDefaults { static let standard=FixtureDefaults() }
@main struct Main {
    @MainActor static func main() {
        let controller=MiniSightWakeController.shared
        controller.install();controller.requestEnabled(true)
        precondition(UserDefaults.standard.on == false)
        precondition(controller.backgroundAudioIsLive == false)
        precondition(controller.claimNameWakeVoice(token:"old",generation:42) == false)
        precondition(controller.awaitsNameWakeReply(token:"old") == false)
        controller.retry()
        precondition(controller.responseActive == false && controller.permissionPending == false)
        print("NATIVE PASS retirement: real controller rejects old enable/claim; no mic dependencies")
    }
}
'''
            (d/'controller.swift').write_text(source)
            r=subprocess.run([swift,'-sdk',sdk,'-swift-version','5','-parse-as-library',str(d/'controller.swift'),'-o',str(d/'controller')],text=True,capture_output=True,timeout=120)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr)
            r=subprocess.run([str(d/'controller')],text=True,capture_output=True,timeout=20)
            self.assertEqual(r.returncode,0,r.stdout+r.stderr);print(r.stdout.strip())

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--require-native',action='store_true');OPTIONS,rest=p.parse_known_args()
    unittest.main(argv=[__file__]+rest,verbosity=2)
