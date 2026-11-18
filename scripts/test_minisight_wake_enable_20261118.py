#!/usr/bin/env python3
"""Literal controller enable-task regression; no Python lifecycle simulation.
Source ordering + old-production/mutant negatives run on iSH. Apple native
executes the actual requestEnabled/saveName/settingsChanged bodies against
synthetic permission continuations, plus actual policy/state/pulse. No mic/UI,
real defaults, user files, network or CI. --require-native fails without Apple.
"""
from pathlib import Path
import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
import unittest
from test_minisight_wake_audio_20261116 import block, REQUIRE_NATIVE
from test_minisight_permissions_20261118 import (permission_sources, permission_contract,
    SOURCE as SPEECH_SOURCE, native_sdk, compiled_candidate)

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"
FIX = ROOT / "scripts/fixtures/minisight_wake_enable_20261118"
PATH = "src/ios/MiniSightWakeController.swift"
SOURCE = (ROOT / PATH).read_text()
BASELINE = "a9e3d7e833aa1377b0ef34a5fc97e704a950904d"
MARKERS = ("func requestEnabled(_ enabled: Bool)", "func saveName(_ prepared:", "private func settingsChanged()",
           "func updatePresentation(", "private func applicationChanged(",
           "private func invalidatePendingEnable()", "private func invalidatePendingEnableIfUnsafe()",
           "private func applicationDidEnterBackground()")


def body(source=SOURCE):
    return block(source, MARKERS[0])


def task(source=SOURCE):
    return block(body(source), "self.permissionTask = Task")


def contract(source):
    """Structural guards, explicitly NOT native execution evidence."""
    method = body(source)
    queued = task(source)
    permission = queued.index("await manager.requestPermissions()")
    first = queued.index("guard let self, self.enableGeneration == request, !Task.isCancelled")
    assert first < permission, "cancelled queued task reaches permission API before guard"
    pre = queued[:permission]
    for expected in ("applicationState == .active", "!self.appLocked", "!self.protectedDataUnavailable",
                     "UIApplication.shared.isProtectedDataAvailable", "MiniSightSettingKey.style) == 1"):
        assert expected in pre, "missing queued eligibility: " + expected
    post = queued[permission:]
    assert post.index("guard self.enableGeneration == request, !Task.isCancelled") < post.index("self.armed =")
    commit = post[:post.index("self.armed =")]
    assert "guard self.foreground" not in commit, "rendering inactive must not reject consent"
    assert "self.armed = self.foreground && UIApplication.shared.applicationState == .active" in post, "inactive must not arm"
    for expected in ("applicationState != .background", "!self.appLocked",
                     "!self.protectedDataUnavailable", "UIApplication.shared.isProtectedDataAvailable",
                     "MiniSightSettingKey.style) == 1"):
        assert expected in commit, "missing commit eligibility: " + expected
    assert "permissionTask = nil; permissionPending = false" in method[:method.index("if !enabled")], "replacement retains pending spinner"
    assert "requestPermissions()" not in block(source, MARKERS[2]), "didChange must not request permission"
    invalidator = block(source, "private func invalidatePendingEnable()")
    for expected in ("guard permissionPending", "enableGeneration &+= 1", "permissionTask?.cancel()",
                     "permissionTask = nil; permissionPending = false"):
        assert expected in invalidator, "lost pending invalidation: " + expected
    assert "invalidatePendingEnable()" in block(source, "private func applicationDidEnterBackground()")
    assert "applicationChanged(active: false)" in block(source, "private func applicationDidEnterBackground()")
    assert "armed =" not in invalidator and "wakeEnabled =" not in invalidator, "must not disable existing background listener"
    assert "invalidatePendingEnable()" not in block(source, "private func applicationChanged(")
    assert "invalidatePendingEnableIfUnsafe()" in block(source, "private func refresh()")
    unsafe = block(source, "private func invalidatePendingEnableIfUnsafe()")
    for expected in ("applicationState == .background", "appLocked", "protectedDataUnavailable",
                     "!UIApplication.shared.isProtectedDataAvailable", "MiniSightSettingKey.style) != 1"):
        assert expected in unsafe, "missing unsafe event: " + expected
    install = block(source, "func install()")
    assert "self?.applicationDidEnterBackground()" in install
    assert "self?.protectedDataUnavailable = true\n                self?.invalidatePendingEnableIfUnsafe()" in install
    assert "self?.appLocked = locked; self?.refresh()" in install


def refresh_prefix(source=SOURCE):
    return block(source, "private func refresh()").split("        let c = context(), decision")[0].split("{\n", 1)[1]


def sources(source=SOURCE, legacy=False):
    support = (FIX / "support.swift").read_text()
    token = "    // PRODUCTION_METHODS: byte-for-byte requestEnabled, saveName, settingsChanged."
    assert support.count(token) == 1
    support = support.replace(token, "\n\n".join(block(source, m) for m in MARKERS))
    support = support.replace("        // PRODUCTION_REFRESH_PREFIX\n", refresh_prefix(source))
    remote = (IOS / "MiniSightWakeRemote.swift").read_text()
    state = "import Foundation\nenum MiniSightWakeRemote {\n" + block(remote, "struct State:") + "\n}\n"
    main = (FIX / "main.swift").read_text()
    if legacy:
        main = main.replace("@MainActor static func main() async {", "@MainActor static func main() async {\n        PermissionProbe.modernAPI = false")
    return {**permission_sources(availability_adapter=legacy),
            "Controller.swift": support, "State.swift": state,
            "Policy.swift": (IOS / "MiniSightWakePolicy.swift").read_text(),
            "Pulse.swift": (IOS / "MiniSightWakeAudioPulse.swift").read_text(),
            "main.swift": main}


def mutants():
    old = subprocess.check_output(["git", "show", f"{BASELINE}:{PATH}"], cwd=ROOT, text=True)
    original = body(SOURCE)
    queued = task(SOURCE)
    before = block(queued, "guard UIApplication.shared.applicationState == .active")
    # block() returns guard through else body. Replacement retains its cleanup;
    # it only deliberately removes the actual safety predicates.
    after = block(queued, "guard UIApplication.shared.applicationState != .background")
    def erase_guard(text):
        return "guard self.enableGeneration == request " + text[text.index("else {"):]
    return {
        "old-production": (SOURCE.replace(original, body(old)), "queued unsafe enable must not prompt"),
        "lost-queued-safety": (SOURCE.replace(before, erase_guard(before)), "queued unsafe enable must not prompt"),
        "lost-commit-safety": (SOURCE.replace(after, erase_guard(after)), "grant in unsafe context must not arm new listening"),
        "reject-inactive-sheet": (SOURCE.replace("guard UIApplication.shared.applicationState != .background",
            "guard UIApplication.shared.applicationState == .active"), "normal inactive permission-sheet completion remains allowed"),
        "require-render-active": (SOURCE.replace("guard UIApplication.shared.applicationState != .background",
            "guard self.foreground, UIApplication.shared.applicationState != .background"), "normal inactive permission-sheet completion remains allowed"),
        "arm-while-inactive": (SOURCE.replace("self.armed = self.foreground && UIApplication.shared.applicationState == .active",
            "self.armed = true"), "normal inactive permission-sheet completion remains allowed"),
        "cancel-render-inactive": (SOURCE.replace("private func applicationChanged(active: Bool) {",
            "private func applicationChanged(active: Bool) {\n        if !active { invalidatePendingEnable() }"),
            "real presentation inactive is not a background cancellation"),
        "lost-background-event": (SOURCE.replace("        invalidatePendingEnable()\n        applicationChanged(active: false)",
            "        applicationChanged(active: false)"), "unsafe event cancels pending generation immediately"),
        "lost-unsafe-refresh": (SOURCE.replace("private func refresh() {\n        invalidatePendingEnableIfUnsafe()",
            "private func refresh() {"), "unsafe event cancels pending generation immediately"),
        "lost-task-cancel": (SOURCE.replace(block(SOURCE, "private func invalidatePendingEnable()"),
            block(SOURCE, "private func invalidatePendingEnable()").replace("permissionTask?.cancel(); ", "")),
            "unsafe cancelled name request never advances to microphone"),
        "stale-spinner": (SOURCE.replace("permissionTask?.cancel(); permissionTask = nil; permissionPending = false\n        if !enabled",
            "permissionTask?.cancel(); permissionTask = nil\n        if !enabled"), "rejected replacement clears old spinner"),
    }


class SourceTests(unittest.TestCase):
    def test_permission_boundaries_and_old_negative(self):
        contract(SOURCE)
        for name, (mutant, _) in mutants().items():
            self.assertNotEqual(mutant, SOURCE, name)
            with self.assertRaises(AssertionError, msg=name):
                contract(mutant)
        print(f"PASS source contract: current + {len(mutants())} unsafe/old-production negatives (not native)")

    def test_literal_production_excerpts(self):
        generated = sources()
        for marker in MARKERS:
            self.assertEqual(block(generated["Controller.swift"], marker), block(SOURCE, marker))
        self.assertEqual(block(generated["State.swift"], "struct State:"),
                         block((IOS / "MiniSightWakeRemote.swift").read_text(), "struct State:"))
        self.assertEqual(generated["Policy.swift"], (IOS / "MiniSightWakePolicy.swift").read_text())
        self.assertEqual(generated["Pulse.swift"], (IOS / "MiniSightWakeAudioPulse.swift").read_text())
        self.assertNotIn("import AVFoundation", generated["Controller.swift"])
        self.assertNotIn("Foundation.UserDefaults", generated["Controller.swift"])
        for text in generated.values():
            self.assertNotIn("https://", text)
        self.assertIn("Task.cancel()", SOURCE)
        prefix = refresh_prefix()
        self.assertIn(prefix, block(generated["Controller.swift"], "func refresh()"))
        self.assertIn("self.foreground = foreground", block(generated["Controller.swift"], "func updatePresentation("))
        runtime = (IOS / "MiniSightInAppRuntime.swift").read_text()
        self.assertIn("let active = phase == .active", runtime)
        self.assertIn("wake.updatePresentation(foreground: active", runtime)
        self.assertEqual(block(generated["Permissions.swift"], "func requestPermissions()"),
                         block(SPEECH_SOURCE, "func requestPermissions()"))

    def test_only_exact_enable_and_event_delta_production_changed(self):
        old = subprocess.check_output(["git", "show", f"{BASELINE}:{PATH}"], cwd=ROOT, text=True)
        normalized = SOURCE.replace(body(), "ENABLE_METHOD")
        for marker in MARKERS[5:]:
            exact = "    " + block(SOURCE, marker) + "\n"
            self.assertEqual(normalized.count(exact), 1)
            normalized = normalized.replace(exact, "")
        for before, after in (
            ("self?.applicationDidEnterBackground()", "self?.applicationChanged(active: false)"),
            ("                self?.invalidatePendingEnableIfUnsafe()\n", ""),
            ("private func refresh() {\n        invalidatePendingEnableIfUnsafe()", "private func refresh() {"),
        ):
            self.assertEqual(normalized.count(before), 1)
            normalized = normalized.replace(before, after)
        self.assertEqual(normalized, old.replace(body(old), "ENABLE_METHOD"))
        # Speech is NOT exempt: normalize exactly the only permitted function's
        # three lines, then compare the ENTIRE file to HEAD. All else stays guarded.
        permission_contract(SPEECH_SOURCE)
        for name in ("MiniSightWakeEngine.swift", "MiniSightWakeAssets.swift", "MiniSightWakePolicy.swift",
                     "MiniSightWakeRemote.swift", "MiniSightWakeName.swift", "MiniSightWakeAudioPulse.swift",
                     "Providers/Voice/AudioSessionCoordinator.swift", "MiniSightVoiceBridge.swift"):
            expected = subprocess.check_output(["git", "show", f"{BASELINE}:src/ios/{name}"], cwd=ROOT)
            self.assertEqual((IOS / name).read_bytes(), expected, name)

    def test_mutants_keep_production_bodies(self):
        for name, (mutant, message) in mutants().items():
            self.assertEqual(block(sources(mutant)["Controller.swift"], MARKERS[0]), body(mutant), name)
            self.assertIn(message, (FIX / "main.swift").read_text(), name)


class NativeTests(unittest.TestCase):
    def test_actual_swift_lifecycle_and_native_mutants(self):
        swift, sdk = native_sdk(self)
        with tempfile.TemporaryDirectory(prefix="ms-wake-enable-") as directory:
            root = Path(directory)
            for legacy in (False, True):
                name = "legacy-selector-production" if legacy else "literal-production"
                run = compiled_candidate(self, root, name, sources(legacy=legacy), swift, sdk)
                self.assertIn("PASS literal controller enable lifecycle", run.stdout)
                self.assertIn("PASS actual policy/state/pulse", run.stdout)
            for name, (source, rejected) in mutants().items():
                compiled_candidate(self, root, name, sources(source), swift, sdk, rejected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
