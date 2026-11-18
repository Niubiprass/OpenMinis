#!/usr/bin/env python3
"""Literal two-stage permissions + manual entry, never system permission/audio.
Apple native positives must compile/run before compiled assertion negatives.
Portable checks are source-only; --require-native fails closed without Apple.
"""
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import unittest
from test_minisight_wake_audio_20261116 import block, REQUIRE_NATIVE, strip_permission_cancellation_guards

ROOT = Path(__file__).resolve().parents[1]
BASELINE = "a9e3d7e833aa1377b0ef34a5fc97e704a950904d"
PATH = "src/ios/Agent/Speech/SpeechRecognitionManager.swift"
SOURCE = (ROOT / PATH).read_text()
FIX = ROOT / "scripts/fixtures/minisight_permissions_20261118"
MARKER = "func requestPermissions()"
CANCEL = "        guard !Task.isCancelled else { return false }\n"
MANUAL = (ROOT / "src/ios/MiniSightVoiceBridge.swift").read_text()
MANUAL_MARKER = "private func startListening("
PORTABLE_ONLY = "--portable-only" in sys.argv
if PORTABLE_ONLY:
    sys.argv.remove("--portable-only")


def permission_contract(source):
    current = block(source, MARKER)
    assert current.count(CANCEL) == 3, "requires all three cancellation fences"
    old = subprocess.check_output(["git", "show", f"{BASELINE}:{PATH}"], cwd=ROOT, text=True)
    assert strip_permission_cancellation_guards(current) == block(old, MARKER), "permission semantics changed"
    assert source.replace(current, block(old, MARKER)) == old, "non-permission Speech method changed"


def permission_sources(source=SOURCE, availability_adapter=False):
    method = block(source, MARKER)
    support = (FIX / "support.swift").read_text()
    assert support.count("// PRODUCTION_PERMISSION_METHOD") == 1
    support = support.replace("// PRODUCTION_PERMISSION_METHOD", method)
    assert block(support, MARKER) == method
    if availability_adapter:
        # macOS always takes #available(iOS ..., *). ONLY this selector changes
        # for fallback coverage; both API/continuation branch bodies stay literal.
        selector = "if #available(iOS 17.0, *)"
        assert support.count(selector) == 1
        support = support.replace(selector, "if PermissionProbe.modernAPI")
    manual = (FIX / "manual.swift").read_text().replace("// PRODUCTION_MANUAL_METHOD", block(MANUAL, MANUAL_MARKER))
    return {"Permissions.swift": support, "Manual.swift": manual,
            "PermissionCases.swift": (FIX / "cases.swift").read_text()}


def permission_mutants():
    method = block(SOURCE, MARKER)
    pieces = method.split(CANCEL)
    assert len(pieces) == 4
    names = ("lost-entry-cancel", "lost-speech-cancel", "lost-final-cancel")
    messages = ("cancelled permission entry never presents Speech",
                "cancelled Speech continuation never presents microphone",
                "cancelled microphone completion returns false")
    result = {}
    for n, (name, message) in enumerate(zip(names, messages)):
        mutant = pieces[0] + "".join(("" if i == n else CANCEL) + pieces[i + 1] for i in range(3))
        result[name] = (SOURCE.replace(method, mutant), message)
    return result


def native_sdk(test):
    swift, xcrun = shutil.which("swiftc"), shutil.which("xcrun")
    if PORTABLE_ONLY and not REQUIRE_NATIVE:
        test.skipTest("native NOT_RUN: --portable-only; source checks are not compiled/runtime proof")
    if platform.system() != "Darwin" or not swift or not xcrun:
        if REQUIRE_NATIVE:
            test.fail("native REQUIRED: Apple Swift/SDK unavailable")
        test.skipTest("native SKIP: Apple Swift/SDK unavailable; source PASS is not runtime proof")
    sdk = subprocess.run([xcrun, "--sdk", "macosx", "--show-sdk-path"], capture_output=True, text=True, timeout=20)
    if sdk.returncode or not Path(sdk.stdout.strip()).is_dir():
        if REQUIRE_NATIVE:
            test.fail("native REQUIRED: Apple host SDK unavailable")
        test.skipTest("native SKIP: Apple host SDK unavailable")
    return swift, sdk.stdout.strip()


def compiled_candidate(test, root, name, generated, swift, sdk, rejected=None):
    folder = root / name; folder.mkdir()
    for filename, text in generated.items():
        (folder / filename).write_text(text)
    output = folder / "regression"
    result = subprocess.run([swift, "-swift-version", "5", "-parse-as-library", "-warnings-as-errors",
        "-sdk", sdk, *[str(folder / filename) for filename in generated], "-o", str(output)],
        capture_output=True, text=True, timeout=120)
    test.assertEqual(result.returncode, 0, name + "\n" + result.stdout + result.stderr)
    run = subprocess.run([str(output)], capture_output=True, text=True, timeout=30)
    if rejected:
        test.assertNotEqual(run.returncode, 0, "native accepted " + name)
        test.assertIn("CHECK failed: " + rejected, run.stderr, name + "\n" + run.stderr)
        print("PASS compiled assertion negative: " + name)
    else:
        test.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        print(run.stdout.strip())
    return run


def standalone_sources(source=SOURCE, legacy=False):
    generated = permission_sources(source, availability_adapter=legacy)
    generated["main.swift"] = '''import Foundation
import Darwin
@MainActor func check(_ ok: @autoclosure () -> Bool, _ message: String) {
    if !ok() { fputs("CHECK failed: \\(message)\\n", stderr); exit(1) }
}
@MainActor func drain() async { for _ in 0..<100 { await Task.yield() } }
@main struct Main { @MainActor static func main() async {
    PermissionProbe.modernAPI = ''' + ("false" if legacy else "true") + '''
    await runPermissionCases()
    check(PermissionProbe.''' + ("legacyMicRequests" if legacy else "modernMicRequests") + ''' == 1,
          "selected microphone branch was really exercised")
} }
'''
    return generated


class SourceTests(unittest.TestCase):
    def test_exact_permission_delta_and_source_negatives(self):
        permission_contract(SOURCE)
        for name, (mutant, message) in permission_mutants().items():
            with self.assertRaises(AssertionError, msg=name):
                permission_contract(mutant)
            self.assertIn(message, (FIX / "cases.swift").read_text())
        for old, new in (("cont.resume(returning: status)", "cont.resume(returning: .authorized)"),
                         ("func setLanguage(_ newLocale: Locale)", "func setLanguage(_ otherLocale: Locale)")):
            with self.assertRaises(AssertionError):
                permission_contract(SOURCE.replace(old, new))
        print("PASS permission source-only: 3 cancelled-guard + 2 protected-byte negatives")

    def test_verbatim_two_stage_and_manual_excerpts(self):
        generated = permission_sources()
        self.assertEqual(block(generated["Permissions.swift"], MARKER), block(SOURCE, MARKER))
        self.assertEqual(block(generated["Manual.swift"], MANUAL_MARKER), block(MANUAL, MANUAL_MARKER))
        self.assertEqual(block(SOURCE, MARKER).count("withCheckedContinuation"), 2)
        self.assertIn("await AVAudioApplication.requestRecordPermission()", generated["Permissions.swift"])
        self.assertIn("AVAudioSession.sharedInstance().requestRecordPermission", generated["Permissions.swift"])
        for text in generated.values():
            self.assertNotIn("import AVFoundation", text)
            self.assertNotIn("import Speech", text)
        adapter = permission_sources(availability_adapter=True)["Permissions.swift"]
        self.assertEqual(adapter.replace("if PermissionProbe.modernAPI", "if #available(iOS 17.0, *)"),
                         generated["Permissions.swift"])


class NativeTests(unittest.TestCase):
    def test_actual_permissions_manual_and_compiled_negatives(self):
        swift, sdk = native_sdk(self)
        with tempfile.TemporaryDirectory(prefix="ms-permissions-") as directory:
            root = Path(directory)
            # Unmodified production positive always comes FIRST, then adapter.
            for legacy in (False, True):
                prefix = "legacy-selector-" if legacy else "literal-"
                compiled_candidate(self, root, prefix + "production", standalone_sources(legacy=legacy), swift, sdk)
                for name, (source, message) in permission_mutants().items():
                    compiled_candidate(self, root, prefix + name, standalone_sources(source, legacy), swift, sdk, message)


if __name__ == "__main__":
    unittest.main(verbosity=2)
