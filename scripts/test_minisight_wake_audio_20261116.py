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


def strip_permission_cancellation_guards(method):
    """Undo ONLY the three sanctioned cooperative-cancel lines, at exact sites.
    The P mirror may still contain the untouched legacy permission function.
    Every other byte must still compare equal to the historical implementation.
    """
    line = "        guard !Task.isCancelled else { return false }\n"
    if line not in method:
        return method
    assert method.count(line) == 3, "permission guard count changed"
    for before, after in (
        ("func requestPermissions() async -> Bool {\n", "        let speechStatus"),
        ("        }\n", "        guard speechStatus == .authorized else {"),
        ("        }\n", "        guard audioStatus else {"),
    ):
        exact = before + line + after
        assert method.count(exact) == 1, "permission guard site changed: " + after
        method = method.replace(exact, before + after, 1)
    return method


def recording_start(source=SPEECH):
    # Both current named-entry and the preserveDraft public-wrapper layout use
    # this REAL shared implementation. Never look for the obsolete no-arg body.
    marker = "private func startRecording(nameWake:" if "private func startRecording(nameWake:" in source else "func startRecording(nameWake:"
    return block(source, marker)


def extracted_sources():
    # Lazy import preserves the existing background runner's block/span import.
    # Reuse its production BKA/voice-bridge dependencies and shared MockAudio
    # adaptation, not a second arbitration/permission model. Equality is tested.
    from test_minisight_name_background_audio_20261116 import production_sources
    return production_sources()


def assert_manual_permission_contract(test, source):
    start = block(source, "private func startListening(")
    test.assertIn("guard await manager.requestPermissions() else", start)
    test.assertLess(start.index("requestPermissions()"), start.index("try manager.startRecording("))
    test.assertIn('reason: "permission"', start)
    test.assertIn("generation == activeGeneration, lease == nextGeneration, !Task.isCancelled", start)
    test.assertLess(start.index("!Task.isCancelled"), start.index("try manager.startRecording("))


def assert_recording_contract(test, source):
    start = recording_start(source)
    test.assertIn("guard permissionsAlreadyGranted, state != .recording", start)
    test.assertEqual(start.count("self.recordingGeneration == generation"), 2)
    test.assertEqual(start.count("self.recordingIntent == intent"), 2)
    test.assertLess(start.index("recordingGeneration &+= 1"), start.index("recognitionTask?.cancel()"))
    teardown = block(source, "private func tearDown()")
    test.assertLess(teardown.index("recordingGeneration &+= 1"), teardown.index("task.cancel()"))
    test.assertIn("let intent = recordingIntent", teardown)
    test.assertIn("if let intent { AudioSessionCoordinator.shared.end(intent) }", teardown)
    test.assertEqual(teardown.count("AudioSessionCoordinator.shared.end("), 1)
    test.assertLess(teardown.index("recordingIntent = nil"), teardown.index("end(intent)"))
    test.assertNotIn("end(.capture)", teardown)
    test.assertNotIn("end(.backgroundKeepAlive)", teardown)
    test.assertNotIn("recognizedText =", teardown)


def negative_sources(sources):
    # Compile only deliberate mutations of extracted Swift. Python checks source
    # structure; the native gate must also reject each mutant at a CHECK below.
    def altered(name, old, new, count=1):
        result = dict(sources)
        assert result[name].count(old) == count, (name, old)
        result[name] = result[name].replace(old, new)
        return result
    return {
        "manual-permission-bypass": (
            altered("VoiceBridge.swift", "guard await manager.requestPermissions() else {", "guard true else {"),
            "manual speech denial never starts engine"),
        "named-permission-bypass": (
            altered("Speech.swift", "guard permissionsAlreadyGranted, state != .recording,", "guard state != .recording,"),
            "named permission denial must throw"),
        "lost-recording-generation": (
            altered("Speech.swift", "self.recordingGeneration == generation,", "", count=2),
            "cancelled callback cannot end newer capture"),
        "foreign-owner-release": (
            altered("Speech.swift", "if let intent { AudioSessionCoordinator.shared.end(intent) }",
                    "if let intent { AudioSessionCoordinator.shared.end(intent); AudioSessionCoordinator.shared.end(.backgroundKeepAlive) }"),
            "speech stop cannot release background owner"),
    }


class SourceContracts(unittest.TestCase):
    def test_intent_values_and_wake_profile(self):
        intent = block(COORD, "enum Intent: Int")
        for name, value in (("nameWakeDictation", -2), ("wakeWord", -1),
                            ("backgroundKeepAlive", 0), ("replyTTS", 1),
                            ("mediaAttachment", 2), ("capture", 3)):
            self.assertRegex(intent, rf"case {name} = {value}\b")
        priority = block(intent, "var priority: Int")
        for rank, name in enumerate(("backgroundKeepAlive", "wakeWord", "nameWakeDictation",
                                     "replyTTS", "mediaAttachment", "capture")):
            self.assertIn(f"case .{name}: return {rank}", priority)
        self.assertIn("active.max(by: { $0.priority < $1.priority })", COORD)
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
        self.assertIn("!isPreemptingNameWakeDictation", guard)
        self.assertIn("active.allSatisfy { $0.isNameWakeInput || $0 == .backgroundKeepAlive }", guard)
        named_guard = block(COORD, "var canBeginNameWakeDictation")
        for check in ("!interrupted", "!pausedByExternalAudio", "!isPreemptingWakeWord",
                      "!isPreemptingNameWakeDictation",
                      "active.allSatisfy { $0 == .wakeWord || $0 == .backgroundKeepAlive }"):
            self.assertIn(check, named_guard)
        self.assertIn("self == .wakeWord || self == .nameWakeDictation", block(COORD, "var isNameWakeInput"))
        self.assertNotIn("active.isEmpty", guard + named_guard)
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
        self.assertIn("preemptNameWakeDictation()", began)
        self.assertIn("preemptNameWakeDictation()", block(COORD, "private func pauseTTSForExternalAudio("))
        apply = block(COORD, "private func apply(")
        self.assertIn("if top == nil || top?.isNameWakeInput == true,", apply)
        self.assertIn("!Self.applyStateLock.withLock({ Self.applyRevision == revision })", apply)
        self.assertIn("if Self.applyRevision == revision", apply)

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
        start = recording_start()
        self.assertIn("nameWake ? .nameWakeDictation : .capture", start)
        self.assertLess(start.index("guard !coordinator.isCapturing"), start.index("recordingIntent = intent"))
        self.assertLess(start.index("recordingIntent = intent"), start.index("beginAndWait(intent)"))
        self.assertIn("defer { if !started { tearDown() } }", start)
        self.assertIn("guard coordinator.beginAndWait(intent) else", start)
        self.assertLess(start.index("beginAndWait(intent)"), start.index("self.audioEngine.inputNode"))
        if "func startRecording(preserveDraft:" in SPEECH:
            # If a public draft-preserving wrapper is present, it must route
            # ordinary recording to the same capture body, without discarding
            # preserveDraft. The extracted wrapper itself remains byte-identical.
            manual = block(SPEECH, "func startRecording(preserveDraft:")
            self.assertRegex(manual, r"preserveDraft:\s*Bool\s*=\s*false\b")
            self.assertRegex(manual, r"startRecording\(nameWake:\s*false,\s*preserveDraft:\s*preserveDraft\)")
        else:
            self.assertIn("func startRecording(nameWake: Bool = false)", start)

    def test_all_initialization_failures_rollback(self):
        start = recording_start()
        for fragment in ("guard let recognizer = speechRecognizer, recognizer.isAvailable",
                         "guard formatOK, let inputNode", "recordingFormat.channelCount > 0",
                         "recordingFormat.sampleRate.isFinite", "recordingFormat.sampleRate > 0",
                         "guard installOk, startError == nil, audioEngine.isRunning else",
                         "guard recognitionOK, recognitionTask != nil else",
                         "defer { if !started { tearDown() } }"):
            self.assertIn(fragment, start)
        self.assertLess(start.index("recognitionOK, recognitionTask != nil"), start.index('recognizedText = ""'))
        self.assertLess(start.index('recognizedText = ""'), start.index("started = true"))
        teardown = block(SPEECH, "private func tearDown()")
        assert_recording_contract(self, SPEECH)
        for fragment in ("noff_try_objc { self.audioEngine.stop() }",
                         "noff_try_objc { self.audioEngine.inputNode.removeTap(onBus: 0) }",
                         "request.endAudio()", "task.cancel()"):
            self.assertIn(fragment, teardown)
        self.assertLess(teardown.index("recordingIntent = nil"), teardown.index("onNameWakeRecordingEnded?()"))
        self.assertLess(teardown.index("onNameWakeRecordingEnded?()"), teardown.index("end(intent)"))

    def test_cancelled_callbacks_cannot_damage_new_recording(self):
        assert_recording_contract(self, SPEECH)

    def test_permission_and_language_policies_unchanged(self):
        old = baseline(SPEECH_PATH)
        for marker in ("var permissionsAlreadyGranted", "func requestPermissions()",
                       "func restartRecordingIfPending()"):
            current = block(SPEECH, marker)
            if marker == "func requestPermissions()":
                current = strip_permission_cancellation_guards(current)
            self.assertEqual(current, block(old, marker))
        # The ONLY sanctioned language/provider delta is the named-input branch:
        # ordinary capture still has precisely the historical control flow.
        # Compare the complete blocks after undoing just that explicit delta.
        for marker in ("func setLanguage(", "func setProvider("):
            current = block(SPEECH, marker)
            self.assertIn("let wasNameWake = recordingIntent == .nameWakeDictation", current)
            current = current.replace("        let wasNameWake = recordingIntent == .nameWakeDictation\n", "")
            current = current.replace("wasRecording && !wasNameWake", "wasRecording")
            self.assertEqual(current, block(old, marker))
        self.assertNotIn("requestPermission", block(COORD, "func beginWakeWordListening("))
        self.assertIn("request.requiresOnDeviceRecognition = true", SPEECH)
        self.assertIn("guard let self, self.state == .recording", SPEECH)
        sources = extracted_sources()
        assert_manual_permission_contract(self, sources["VoiceBridge.swift"])
        assert_recording_contract(self, SPEECH)

    def test_atomic_input_handoff_retains_background_owner(self):
        begin = block(COORD, "private func beginInternal(")
        self.assertIn("intent.priority > Intent.wakeWord.priority", begin)
        handoff = begin.split("if intent == .nameWakeDictation {")[1].split("} else {")[0]
        self.assertIn("active.remove(.wakeWord)", handoff)
        self.assertIn("wakeWordGeneration &+= 1", handoff)
        self.assertNotIn("preemptWakeWord()", handoff)
        self.assertNotIn("end(", handoff)
        self.assertLess(begin.index("active.insert(intent)"), begin.index("yieldSilentAudioToNameInput()"))
        self.assertLess(begin.index("yieldSilentAudioToNameInput()"), begin.index('apply(reason:'))
        self.assertNotIn("end(.backgroundKeepAlive)", begin)
        self.assertIn("!top.isNameWakeInput", block(COORD, "var keepAlivePlaybackApplied"))
        self.assertIn("hasNameWakeInputIntent", block(COORD, "var keepAlivePlaybackBlocked"))

    def test_source_negative_controls_reject_permission_generation_and_foreign_release(self):
        sources = extracted_sources()
        assert_manual_permission_contract(self, sources["VoiceBridge.swift"])
        assert_recording_contract(self, sources["Speech.swift"])
        for name, (mutant, _) in negative_sources(sources).items():
            with self.subTest(mutant=name), self.assertRaises(AssertionError):
                if name == "manual-permission-bypass":
                    assert_manual_permission_contract(self, mutant["VoiceBridge.swift"])
                else:
                    assert_recording_contract(self, mutant["Speech.swift"])

    def test_extraction_keeps_production_methods_not_python_policy(self):
        from test_minisight_name_background_audio_20261116 import production_sources
        sources = extracted_sources()
        self.assertEqual(sources, production_sources())
        self.assertEqual(set(sources), {"MockAudio.swift", "BackgroundBridgeMocks.swift",
                                      "Coordinator.swift", "Speech.swift", "VoiceBridge.swift"})
        coordinator, speech = sources["Coordinator.swift"], sources["Speech.swift"]
        # Whole-file speech equality: no production branch/guard/body rewritten.
        self.assertEqual(speech, "import Foundation\n" + re.sub(
            r"(?m)^import (AVFoundation|Combine|Speech)\n", "", SPEECH))
        expected = re.sub(r"(?m)^import (Foundation|AVFoundation|UIKit)\n", "", COORD)
        start, end = span(expected, "private func registerInterruptionObserver()")
        expected = expected[:start] + "private func registerInterruptionObserver() {}" + expected[end:]
        expected = expected.replace("@objc ", "")
        for name in ("handleInterruption", "handleSilenceSecondaryAudioHint", "handleRouteChange"):
            expected = expected.replace(f"private func {name}(", f"func {name}(")
        self.assertEqual(coordinator, "import Foundation\nimport CoreFoundation\n" + expected)
        for marker in ("enum Intent: Int", "private func profile(", "func beginAndWait(",
                       "func beginBackgroundKeepAlive(", "func beginWakeWordListening(",
                       "private func beginInternal(", "func end(", "private func apply(",
                       "private func preemptWakeWord()", "private func preemptNameWakeDictation()"):
            self.assertEqual(block(coordinator, marker), block(COORD, marker))
        self.assertEqual(recording_start(speech), recording_start(SPEECH))
        for marker in ("private func tearDown()", "func setLanguage(",
                       "func requestPermissions()", "func setProvider("):
            self.assertEqual(block(speech, marker), block(SPEECH, marker))
        if "func startRecording(preserveDraft:" in SPEECH:
            self.assertEqual(block(speech, "func startRecording(preserveDraft:"),
                             block(SPEECH, "func startRecording(preserveDraft:"))
        bridge = (ROOT / "src/ios/MiniSightVoiceBridge.swift").read_text()
        for marker in ("func handleRequest(", "private func startListening(", "func stop()",
                       "private func handleNameWakeRequest(", "private func startNameWakeListening(",
                       "private func finishNameWake(", "func cancelNameWake("):
            self.assertEqual(block(sources["VoiceBridge.swift"], marker), block(bridge, marker))
        backing = (ROOT / "src/ios/Agent/Background/BackgroundKeepAliveManager.swift").read_text()
        for marker in ("var backgroundExecutionIsBacked", "var silentAudioIsPlaying", "var silentAudioWanted",
                       "func yieldSilentAudioToNameInput()", "func stopSilentAudio("):
            self.assertEqual(block(sources["BackgroundBridgeMocks.swift"], marker), block(backing, marker))
        mock = (FIXTURES / "MockAudio.swift").read_text()
        mock = mock.replace("    var stopCount = 0", "    var isPlaying = false\n    var isPaused = false\n    var stopCount = 0")
        mock = mock.replace("func stop() { isRunning = false }",
                            'func stop() { isRunning = false; EventLog.shared.append("stop-engine") }')
        self.assertEqual(sources["MockAudio.swift"], mock)
        for name, source in sources.items():
            self.assertNotRegex(source, r"(?m)^import (AVFoundation|Speech|UIKit|Combine)$", name)
        for path in FIXTURES.glob("*.swift"):
            self.assertNotRegex(path.read_text(), r"(?m)^import (AVFoundation|Speech|UIKit|Combine)$")


class NativeProductionHarness(unittest.TestCase):
    def native_toolchain(self):
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
        return compiler, sdk.stdout.strip()

    def compile_and_run(self, sources, compiler, sdk):
        with tempfile.TemporaryDirectory(prefix="minisight-wake-audio-") as temporary:
            folder = Path(temporary)
            for name, source in sources.items():
                (folder / name).write_text(source)
            executable = folder / "wake-audio-harness"
            result = subprocess.run([compiler, "-swift-version", "5", "-parse-as-library", "-sdk", sdk,
                *[str(folder / name) for name in sources], str(FIXTURES / "WakeAudioHarness.swift"),
                "-o", str(executable)], text=True, capture_output=True, timeout=120)
            # A mutant compile error is NOT evidence of behavioural rejection.
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            return subprocess.run([str(executable)], text=True, capture_output=True, timeout=45)

    def test_native_production_swift_mock_harness(self):
        compiler, sdk = self.native_toolchain()
        run = self.compile_and_run(extracted_sources(), compiler, sdk)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("PASS native production Swift mock harness:", run.stdout)
        print(run.stdout.strip())

    def test_native_negative_controls_fail_at_runtime(self):
        compiler, sdk = self.native_toolchain()
        for name, (sources, diagnostic) in negative_sources(extracted_sources()).items():
            with self.subTest(mutant=name):
                run = self.compile_and_run(sources, compiler, sdk)
                self.assertNotEqual(run.returncode, 0, f"negative control escaped: {name}\n{run.stdout}")
                self.assertNotIn("PASS native production Swift mock harness:", run.stdout)
                self.assertIn(diagnostic, run.stdout + run.stderr,
                              f"mutant failed at the wrong assertion: {name}\n{run.stdout}{run.stderr}")
                print(f"PASS native negative control rejected at assertion: {name}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
