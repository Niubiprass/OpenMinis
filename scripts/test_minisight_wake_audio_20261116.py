#!/usr/bin/env python3
"""Focused wake-audio contracts + production Swift/mock harness.

No Python policy simulation. Native tests require swiftc and an Apple host SDK;
iSH reports SKIP, never a native PASS. Nothing builds an iOS App, starts a real
engine, contacts a device/network, invokes CI, or changes the other candidates.
"""
from pathlib import Path
import platform
import re
import os
import sys
import shutil
import subprocess
import tempfile
import unittest

REQUIRE_NATIVE = os.environ.get("V64R_REQUIRE_SWIFT") == "1" or "--require-native" in sys.argv
if "--require-native" in sys.argv:
    sys.argv.remove("--require-native")
ROOT = Path(__file__).resolve().parents[1]
COORD_PATH = "src/ios/Providers/Voice/AudioSessionCoordinator.swift"
SPEECH_PATH = "src/ios/Agent/Speech/SpeechRecognitionManager.swift"
COORD = (ROOT / COORD_PATH).read_text()
SPEECH = (ROOT / SPEECH_PATH).read_text()
FIXTURES = ROOT / "scripts/fixtures/minisight_wake_audio_20261116"


def span(source, marker):
    start = source.index(marker)
    opening = source.index("{", start)
    depth, i, quoted = 0, opening, False
    while i < len(source):
        c = source[i]
        if quoted:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                quoted = False
        elif source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end
            continue
        elif source.startswith("/*", i):
            i = source.index("*/", i + 2) + 2
            continue
        elif c == '"':
            quoted = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return start, i + 1
        i += 1
    raise AssertionError(f"Unbalanced production block: {marker}")


def block(source, marker):
    start, end = span(source, marker)
    return source[start:end]


def baseline(path):
    return subprocess.check_output(["git", "show", f"82f9fb1:{path}"], cwd=ROOT, text=True)


def extracted_sources():
    coordinator = re.sub(r"(?m)^import (Foundation|AVFoundation|UIKit)\n", "", COORD)
    start, end = span(coordinator, "private func registerInterruptionObserver()")
    coordinator = coordinator[:start] + "private func registerInterruptionObserver() {}" + coordinator[end:]
    coordinator = coordinator.replace("@objc ", "")
    for method in ("handleInterruption", "handleSilenceSecondaryAudioHint", "handleRouteChange"):
        coordinator = coordinator.replace(f"private func {method}(", f"func {method}(")
    speech = re.sub(r"(?m)^import (AVFoundation|Combine|Speech)\n", "", SPEECH)
    return ("import Foundation\nimport CoreFoundation\n" + coordinator,
            "import Foundation\n" + speech)


class SourceContracts(unittest.TestCase):
    def test_intent_values_and_wake_profile(self):
        intent = block(COORD, "enum Intent: Int")
        for name, value in (("wakeWord", -1), ("backgroundKeepAlive", 0), ("replyTTS", 1),
                            ("mediaAttachment", 2), ("capture", 3)):
            self.assertRegex(intent, rf"case {name} = {value}\b")
        profile = block(COORD, "private func profile(")
        self.assertIn("return (.playAndRecord, .measurement, [.mixWithOthers])", profile)
        self.assertNotIn("allowBluetooth", profile)

    def test_old_profiles_are_byte_identical(self):
        previous = block(baseline(COORD_PATH), "private func profile(")
        current = block(COORD, "private func profile(")
        self.assertEqual(current[current.index("        case .capture:"):],
                         previous[previous.index("        case .capture:"):])

    def test_wake_guard_and_async_ack(self):
        guard = block(COORD, "var canBeginWakeWordListening")
        self.assertIn("!interrupted", guard)
        self.assertIn("!pausedByExternalAudio", guard)
        self.assertIn("!isPreemptingWakeWord", guard)
        self.assertIn("active.allSatisfy { $0 == .wakeWord }", guard)
        begin = block(COORD, "func beginWakeWordListening(")
        self.assertIn("Self.sessionQueue.async", begin)
        self.assertIn("Task { @MainActor", begin)
        self.assertNotIn(".wait(", begin)
        self.assertNotIn("beginAndWait", begin)
        for check in ("generation == self.wakeWordGeneration", "Self.applyRevision == revision",
                      "self.canBeginWakeWordListening", "self.hasIntent(.wakeWord)",
                      "self.appliedIntent == .wakeWord"):
            self.assertIn(check, begin)
        self.assertIn("self.end(.wakeWord)", begin)

    def test_preemption_is_synchronous_and_reentrant_safe(self):
        self.assertIn("var onWakeWordPreempted: (@MainActor () -> Void)?", COORD)
        begin = block(COORD, "private func beginInternal(")
        self.assertLess(begin.index("preemptWakeWord()"), begin.index('apply(reason:'))
        self.assertLess(begin.index("active.insert(intent)"), begin.index("preemptWakeWord()"))
        preempt = block(COORD, "private func preemptWakeWord()")
        self.assertLess(preempt.index("active.remove(.wakeWord)"), preempt.index("onWakeWordPreempted?()"))
        self.assertIn("isPreemptingWakeWord = true", preempt)
        self.assertIn("defer { isPreemptingWakeWord = false }", preempt)
        self.assertNotIn("Task", preempt)
        self.assertNotIn("apply(reason:", preempt)

    def test_end_is_own_intent_only(self):
        end = block(COORD, "func end(_ intent:")
        self.assertIn("active.remove(intent)", end)
        self.assertNotIn("removeAll", end)
        self.assertIn("if intent == .wakeWord { wakeWordGeneration &+= 1 }", end)

    def test_interruption_and_external_audio_preempt(self):
        interruption = block(COORD, "private func handleInterruption(")
        began = interruption.split("case .ended:")[0]
        self.assertLess(began.index("interrupted = true"), began.index("preemptWakeWord()"))
        self.assertIn("preemptWakeWord()", block(COORD, "private func pauseTTSForExternalAudio("))
        self.assertIn("if top == .wakeWord,", block(COORD, "private func apply("))

    def test_legacy_wait_and_background_ack_unchanged(self):
        old = baseline(COORD_PATH)
        for marker in ("func beginAndWait(", "func beginBackgroundKeepAlive("):
            self.assertEqual(block(COORD, marker), block(old, marker))

    def test_media_tts_preemption_retained(self):
        begin = block(COORD, "private func beginInternal(")
        self.assertIn("VoiceOutputPlayer.shared.stopAll()", begin)
        self.assertIn("Self.replyTTSPreemptedNotification", begin)
        self.assertLess(begin.index("stopAll()"), begin.index('apply(reason:'))
        previous = block(baseline(COORD_PATH), "private func beginInternal(")
        marker = "// Media attachment preempts reply TTS"
        self.assertEqual(begin[begin.index(marker):], previous[previous.index(marker):])

    def test_speech_no_direct_session_mutation(self):
        self.assertNotRegex(SPEECH, r"\.set(Category|Active)\s*\(")
        start = block(SPEECH, "func startRecording()")
        self.assertLess(start.index("guard !coordinator.isCapturing"), start.index("ownsCaptureIntent = true"))
        self.assertLess(start.index("ownsCaptureIntent = true"), start.index("beginAndWait(.capture)"))
        self.assertIn("defer { if !started { tearDown() } }", start)
        self.assertIn("guard coordinator.beginAndWait(.capture) else", start)
        self.assertLess(start.index("beginAndWait(.capture)"), start.index("audioEngine.inputNode"))

    def test_all_initialization_failures_rollback(self):
        start = block(SPEECH, "func startRecording()")
        for fragment in ("guard let recognizer = speechRecognizer", "recordingFormat.channelCount > 0",
                         "recordingFormat.sampleRate > 0", "guard installOk, startError == nil else",
                         "guard recognitionOK, recognitionTask != nil else"):
            self.assertIn(fragment, start)
        self.assertLess(start.index("recognitionOK, recognitionTask != nil"), start.index('recognizedText = ""'))
        self.assertLess(start.index('recognizedText = ""'), start.index("started = true"))
        teardown = block(SPEECH, "private func tearDown()")
        self.assertIn("if ownsCaptureIntent {", teardown)
        self.assertLess(teardown.index("ownsCaptureIntent = false"), teardown.index("end(.capture)"))
        self.assertEqual(teardown.count("end(.capture)"), 1)
        self.assertIn("noff_try_objc", teardown)
        self.assertNotIn("recognizedText =", teardown)

    def test_cancelled_callbacks_cannot_damage_new_recording(self):
        start = block(SPEECH, "func startRecording()")
        self.assertEqual(start.count("self.recordingGeneration == generation"), 2)
        teardown = block(SPEECH, "private func tearDown()")
        self.assertLess(teardown.index("recordingGeneration &+= 1"), teardown.index("recognitionTask?.cancel()"))

    def test_permission_and_language_policies_unchanged(self):
        old = baseline(SPEECH_PATH)
        for marker in ("var permissionsAlreadyGranted", "func requestPermissions()",
                       "func setLanguage(", "func restartRecordingIfPending()", "func setProvider("):
            self.assertEqual(block(SPEECH, marker), block(old, marker))
        self.assertNotIn("requestPermission", block(COORD, "func beginWakeWordListening("))
        self.assertIn("request.requiresOnDeviceRecognition = true", SPEECH)
        self.assertIn("guard let self, self.state == .recording", SPEECH)

    def test_extraction_keeps_production_methods_not_python_policy(self):
        coordinator, speech = extracted_sources()
        for marker in ("enum Intent: Int", "private func profile(", "func beginAndWait(",
                       "func beginWakeWordListening(", "private func beginInternal(", "func end(",
                       "private func apply(", "private func preemptWakeWord()"):
            self.assertEqual(block(coordinator, marker), block(COORD, marker))
        for marker in ("func startRecording()", "private func tearDown()", "func setLanguage("):
            self.assertEqual(block(speech, marker), block(SPEECH, marker))
        for path in FIXTURES.glob("*.swift"):
            self.assertNotRegex(path.read_text(), r"(?m)^import (AVFoundation|Speech|UIKit|Combine)$")


class NativeProductionHarness(unittest.TestCase):
    def test_native_production_swift_mock_harness(self):
        compiler = shutil.which("swiftc")
        xcrun = shutil.which("xcrun")
        if not compiler or platform.system() != "Darwin" or not xcrun:
            if REQUIRE_NATIVE:
                self.fail("native REQUIRED: Apple Swift/SDK unavailable")
            self.skipTest("native SKIP: iSH/no swiftc or Apple SDK; source contracts are NOT runtime validation")
        sdk = subprocess.run([xcrun, "--sdk", "macosx", "--show-sdk-path"],
                             text=True, capture_output=True, timeout=20)
        if sdk.returncode or not Path(sdk.stdout.strip()).is_dir():
            if REQUIRE_NATIVE:
                self.fail("native REQUIRED: Apple host SDK unavailable")
            self.skipTest("native SKIP: Apple host SDK unavailable")
        with tempfile.TemporaryDirectory(prefix="minisight-wake-audio-") as temporary:
            folder = Path(temporary)
            coordinator, speech = extracted_sources()
            (folder / "Coordinator.swift").write_text(coordinator)
            (folder / "Speech.swift").write_text(speech)
            executable = folder / "wake-audio-harness"
            result = subprocess.run([compiler, "-swift-version", "5", "-parse-as-library", "-sdk",
                sdk.stdout.strip(), str(FIXTURES / "MockAudio.swift"), str(folder / "Coordinator.swift"),
                str(folder / "Speech.swift"), str(FIXTURES / "WakeAudioHarness.swift"), "-o", str(executable)],
                text=True, capture_output=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            run = subprocess.run([str(executable)], text=True, capture_output=True, timeout=45)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertIn("PASS native production Swift mock harness:", run.stdout)
            print(run.stdout.strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)
