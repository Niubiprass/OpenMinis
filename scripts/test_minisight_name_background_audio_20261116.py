#!/usr/bin/env python3
"""Source guards + actual production Swift bodies with synthetic dependencies.
Python never simulates arbitration/session policy. iSH native SKIP is explicit;
--require-native (or V64R_REQUIRE_SWIFT=1) fails closed without an Apple compiler.
No iOS build/install/CI, real microphone, external request or device operations.
"""
from pathlib import Path
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_minisight_wake_audio_20261116 import block, span, REQUIRE_NATIVE

ROOT = Path(__file__).resolve().parents[1]
CP = "src/ios/Providers/Voice/AudioSessionCoordinator.swift"
SP = "src/ios/Agent/Speech/SpeechRecognitionManager.swift"
BP = "src/ios/Agent/Background/BackgroundKeepAliveManager.swift"
VP = "src/ios/MiniSightVoiceBridge.swift"
C, S, B, V = [(ROOT / p).read_text() for p in (CP, SP, BP, VP)]
FIX = ROOT / "scripts/fixtures/minisight_name_background_audio_20261116"


def baseline(path):
    return subprocess.check_output(["git", "show", f"82f9fb1:{path}"], cwd=ROOT, text=True)


class SourceGuards(unittest.TestCase):
    def test_stable_raw_values_explicit_priority(self):
        intent = block(C, "enum Intent: Int")
        for name, value in (("nameWakeDictation", -2), ("wakeWord", -1),
                            ("backgroundKeepAlive", 0), ("replyTTS", 1),
                            ("mediaAttachment", 2), ("capture", 3)):
            self.assertRegex(intent, rf"case {name} = {value}\b")
        self.assertIn("$0.priority < $1.priority", C)
        ranks = block(intent, "var priority: Int")
        for rank, name in enumerate(("backgroundKeepAlive", "wakeWord", "nameWakeDictation",
                                     "replyTTS", "mediaAttachment", "capture")):
            self.assertIn(f"case .{name}: return {rank}", ranks)

    def test_four_old_profiles_byte_identical(self):
        new = block(C, "private func profile(")
        old = block(baseline(CP), "private func profile(")
        marker = "        case .capture:"
        self.assertEqual(new[new.index(marker):], old[old.index(marker):])
        self.assertIn("case .wakeWord, .nameWakeDictation:", new)
        self.assertIn("return (.playAndRecord, .measurement, [.mixWithOthers])", new)
        self.assertNotIn(".allowBluetooth", new)

    def test_silent_owner_cannot_preempt_or_overwrite_input(self):
        begin = block(C, "private func beginInternal(")
        self.assertIn("intent.priority > Intent.wakeWord.priority", begin)
        self.assertLess(begin.index("active.insert(intent)"), begin.index("yieldSilentAudioToNameInput()"))
        self.assertLess(begin.index("yieldSilentAudioToNameInput()"), begin.index('apply(reason:'))
        self.assertIn("!top.isNameWakeInput", block(C, "var keepAlivePlaybackApplied"))
        self.assertIn("hasNameWakeInputIntent", block(C, "var keepAlivePlaybackBlocked"))

    def test_atomic_handoff_does_not_cancel_claim(self):
        begin = block(C, "private func beginInternal(")
        section = begin.split("if intent == .nameWakeDictation {")[1].split("} else {")[0]
        self.assertIn("active.remove(.wakeWord)", section)
        self.assertNotIn("preemptWakeWord()", section)
        self.assertNotIn("end(", section)
        self.assertIn("preemptNameWakeDictation()", begin)
        for marker, callback in (("private func preemptWakeWord()", "onWakeWordPreempted?()"),
                                 ("private func preemptNameWakeDictation()", "onNameWakeDictationPreempted?()")):
            method = block(C, marker)
            self.assertLess(method.index("active.remove("), method.index(callback))
            self.assertNotIn("Task", method)
        apply = block(C, "private func apply(")
        self.assertIn("top == nil || top?.isNameWakeInput == true", apply)

    def test_speech_only_releases_recorded_intent(self):
        start = block(S, "func startRecording(nameWake:")
        self.assertIn("Bool = false", start)
        self.assertIn("nameWake ? .nameWakeDictation : .capture", start)
        self.assertIn("guard !coordinator.isCapturing", start)
        self.assertIn("canBeginNameWakeDictation", start)
        self.assertIn("permissionsAlreadyGranted", start)
        self.assertIn("defer { if !started { tearDown() } }", start)
        self.assertLess(start.index("beginAndWait(intent)"), start.index("self.audioEngine.inputNode"))
        self.assertIn("audioEngine.isRunning else", start)
        teardown = block(S, "private func tearDown()")
        self.assertIn("let intent = recordingIntent", teardown)
        self.assertIn("end(intent)", teardown)
        self.assertLess(teardown.index("recordingIntent = nil"), teardown.index("onNameWakeRecordingEnded?()"))
        self.assertLess(teardown.index("onNameWakeRecordingEnded?()"), teardown.index("end(intent)"))
        self.assertNotIn("end(.capture)", teardown)
        self.assertNotIn("recognizedText =", teardown)
        self.assertIn("guard recordingIntent == .nameWakeDictation", block(S, "func stopNameWakeRecording()"))
        self.assertNotRegex(S, r"\.set(Category|Active)\s*\(")

    def test_real_backing_and_switch_defaults_unchanged(self):
        backing = block(B, "var backgroundExecutionIsBacked")
        self.assertIn("case .wakeWord, .nameWakeDictation:", backing)
        self.assertIn("return MiniSightWakeController.shared.backgroundAudioIsLive", backing)
        wanted = block(B, "private var silentAudioWanted")
        self.assertIn("!AudioSessionCoordinator.shared.hasNameWakeInputIntent", wanted)
        self.assertIn("!MiniSightWakeController.shared.backgroundAudioIsLive", wanted)
        self.assertIn('releaseIntent: false', block(B, "func yieldSilentAudioToNameInput()"))
        self.assertIn("if releaseIntent { coordinator.end(.backgroundKeepAlive) }", B)
        for marker in ("var enhancedBackgroundEnabled:", "var backgroundSpeakEnabled:",
                       "var enhancedBackgroundEffective:", "var survivalTier:"):
            self.assertEqual(block(B, marker), block(baseline(BP), marker))

    def test_named_source_token_and_claim_before_starting(self):
        handle = block(V, "private func handleRequest()")
        self.assertIn('object["source"] as? String == "nameWake"', handle)
        self.assertIn('object["nameWakeToken"] as? String', handle)
        self.assertIn("UUID(uuidString: token)?.uuidString == token", handle)
        self.assertLess(handle.index("handleNameWakeRequest("), handle.index('if action == "stop"'))
        named = block(V, "private func handleNameWakeRequest(")
        self.assertLess(named.index("claimNameWakeVoice("), named.index('state: "starting"'))
        named_start = block(V, "private func startNameWakeListening(")
        self.assertIn("permissionsAlreadyGranted", named_start)
        self.assertNotIn("requestPermissions", named_start)
        self.assertIn("startRecording(nameWake: true)", named_start)
        self.assertIn("backgroundRecognitionHasLiveAudio", named_start)
        self.assertIn("nameWakeVoiceStarted(generation: generation)", named_start)
        self.assertIn("45_000_000_000", named_start)
        self.assertIn("await manager.requestPermissions()", block(V, "private func startListening("))

    def test_name_cancel_waiting_matched_once_manual_safe(self):
        cancel = block(V, "func cancelNameWake(")
        self.assertIn("session.generation == generation", cancel)
        self.assertNotIn("guard listening", cancel)
        finish = block(V, "private func finishNameWake(")
        self.assertIn("session.lease == lease", finish)
        self.assertLess(finish.index("namedSession = nil"), finish.index("nameWakeVoiceEnded("))
        self.assertIn("namedStartTask?.cancel()", finish)
        self.assertIn("stopNameWakeRecording()", finish)
        self.assertNotIn(".stopRecording()", finish)
        self.assertEqual(V.count("nameWakeVoiceEnded("), 1)
        self.assertIn("manager.state == .idle", block(V, "private func recordingBecameIdle("))

    def test_external_recording_sync_stop_and_no_auto_resume(self):
        for marker in ("private func pauseTTSForExternalAudio(", "private func handleInterruption("):
            self.assertIn("preemptNameWakeDictation()", block(C, marker))
        self.assertIn("self.tearDown()", S.split("onNameWakeDictationPreempted =")[1].split("// [T-voice")[0])
        self.assertIn("pendingRecordingRestart = wasRecording && !wasNameWake", S)
        self.assertNotIn("beginBackgroundTask", V)

    def test_extraction_keeps_production_bodies_not_python_runtime(self):
        sources = production_sources()
        for marker in ("private func beginInternal(", "func beginAndWait(",
                       "func beginWakeWordListening(", "private func profile("):
            self.assertEqual(block(C, marker), block(sources["Coordinator.swift"], marker))
        for marker in ("func startRecording(nameWake:", "private func tearDown()"):
            self.assertEqual(block(S, marker), block(sources["Speech.swift"], marker))
        for marker in ("private func handleNameWakeRequest(", "private func startNameWakeListening(",
                       "private func finishNameWake(", "func cancelNameWake("):
            self.assertEqual(block(V, marker), block(sources["VoiceBridge.swift"], marker))
        self.assertEqual(block(B, "var backgroundExecutionIsBacked"),
                         block(sources["BackgroundBridgeMocks.swift"], "var backgroundExecutionIsBacked"))
        self.assertEqual(block(B, "func stopSilentAudio("),
                         block(sources["BackgroundBridgeMocks.swift"], "func stopSilentAudio("))
        for name, source in sources.items():
            self.assertNotRegex(source, r"(?m)^import (AVFoundation|Speech|UIKit|Combine)$", name)


def production_sources():
    coordinator = re.sub(r"(?m)^import (Foundation|AVFoundation|UIKit)\n", "", C)
    start, end = span(coordinator, "private func registerInterruptionObserver()")
    coordinator = coordinator[:start] + "private func registerInterruptionObserver() {}" + coordinator[end:]
    coordinator = coordinator.replace("@objc ", "")
    for name in ("handleInterruption", "handleSilenceSecondaryAudioHint", "handleRouteChange"):
        coordinator = coordinator.replace(f"private func {name}(", f"func {name}(")
    speech = re.sub(r"(?m)^import (AVFoundation|Combine|Speech)\n", "", S)
    bridge = re.sub(r"(?m)^import (Combine|CoreFoundation|Foundation)\n", "", V)
    start, end = span(bridge, "func install()")
    bridge = bridge[:start] + "func install() {}" + bridge[end:]
    for name in ("handleRequest", "recordingBecameIdle"):
        bridge = bridge.replace(f"private func {name}(", f"func {name}(")
    bridge = bridge.replace("private var files =", "var files =")
    bridge = bridge.replace("private var writeQueue =", "var writeQueue =")
    post = ('CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),\n'
            '                    CFNotificationName(resultNote as CFString), nil, nil, true)')
    assert post in bridge
    bridge = bridge.replace(post, 'EventLog.shared.append("voice:\\(generation):\\(state):\\(final)")')
    bka_members = "\n\n".join(block(B, m) for m in (
        "var backgroundExecutionIsBacked", "var silentAudioIsPlaying", "private var silentAudioWanted",
        "func yieldSilentAudioToNameInput()", "func stopSilentAudio("))
    bka_members = bka_members.replace("private var silentAudioWanted", "var silentAudioWanted")
    dependencies = (FIX / "BackgroundBridgeMocks.swift").read_text().replace(
        "// PRODUCTION_BKA_MEMBERS", bka_members)
    mock = (ROOT / "scripts/fixtures/minisight_wake_audio_20261116/MockAudio.swift").read_text()
    mock = mock.replace("    var stopCount = 0", "    var isPlaying = false\n    var isPaused = false\n    var stopCount = 0")
    mock = mock.replace("func stop() { isRunning = false }",
                        'func stop() { isRunning = false; EventLog.shared.append("stop-engine") }')
    return {"MockAudio.swift": mock, "BackgroundBridgeMocks.swift": dependencies,
            "Coordinator.swift": "import Foundation\nimport CoreFoundation\n" + coordinator,
            "Speech.swift": "import Foundation\n" + speech,
            "VoiceBridge.swift": "import Foundation\n" + bridge}


class NativeProductionHarness(unittest.TestCase):
    def test_production_swift_mock(self):
        compiler, xcrun = shutil.which("swiftc"), shutil.which("xcrun")
        if not compiler or not xcrun or platform.system() != "Darwin":
            if REQUIRE_NATIVE:
                self.fail("native REQUIRED: Apple Swift/SDK unavailable")
            self.skipTest("native SKIP: iSH/no swiftc or Apple SDK; source guards are NOT runtime proof")
        sdk = subprocess.run([xcrun, "--sdk", "macosx", "--show-sdk-path"],
                             text=True, capture_output=True, timeout=20)
        if sdk.returncode or not Path(sdk.stdout.strip()).is_dir():
            if REQUIRE_NATIVE:
                self.fail("native REQUIRED: Apple SDK unavailable")
            self.skipTest("native SKIP: Apple host SDK unavailable")
        with tempfile.TemporaryDirectory(prefix="minisight-name-background-") as directory:
            folder = Path(directory)
            sources = production_sources()
            for name, source in sources.items():
                (folder / name).write_text(source)
            output = folder / "name-background-harness"
            result = subprocess.run([compiler, "-swift-version", "5", "-parse-as-library", "-sdk",
                sdk.stdout.strip(), *[str(folder / name) for name in sources],
                str(FIX / "NameBackgroundAudioHarness.swift"), "-o", str(output)],
                text=True, capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run = subprocess.run([str(output)], text=True, capture_output=True, timeout=45)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("PASS production Swift/mock:", run.stdout)
            print(run.stdout.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
