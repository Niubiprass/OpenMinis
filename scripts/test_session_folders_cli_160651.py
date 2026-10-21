#!/usr/bin/env python3
"""Offline folder CLI regression tests. Never invokes the CLI or touches app data.

On a Mac with swiftc, compile actual SessionFoldersBridge plus actual sendPrompt
and its two helpers, with in-memory dependency fakes. Transformations are limited
to removing @objc / the UIKit import and selecting complete declarations. No
business statements are rewritten. Foundation/Dispatch remain real; UIKit and
app services are fixture types. Objective-C dispatch is checked only as wiring.

Run: python3 scripts/test_session_folders_cli_160651.py
CI requiring native execution: SESSION_FOLDERS_REQUIRE_SWIFT=1 python3 ...
A missing compiler is SKIP, never evidence of native behavior passing.
"""
from pathlib import Path
import os
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "src/ios/NativeOffloads"
FIXTURES = Path(__file__).with_name("fixtures") / "session_folders_cli_160651"


def declaration(source, marker):
    """Select one balanced Swift declaration, ignoring braces in strings/comments.

    Production declarations used here have ordinary Swift strings, not raw or
    multiline strings. Fail if extraction drifts instead of silently using a copy.
    """
    start = source.index(marker)
    opening = source.index("{", start)
    depth, i, state, comment_depth = 0, opening, "code", 0
    while i < len(source):
        c, pair = source[i], source[i:i + 2]
        if state == "string":
            if c == "\\":
                i += 2
                continue
            if c == '"':
                state = "code"
        elif state == "line":
            if c == "\n":
                state = "code"
        elif state == "block":
            if pair == "/*":
                comment_depth += 1
                i += 1
            elif pair == "*/":
                comment_depth -= 1
                i += 1
                if not comment_depth:
                    state = "code"
        elif pair == "//":
            state = "line"
            i += 1
        elif pair == "/*":
            state, comment_depth = "block", 1
            i += 1
        elif c == '"':
            state = "string"
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return source[start:i + 1]
        i += 1
    raise ValueError("Unbalanced declaration: " + marker)


def extracted_swift():
    folders = (NATIVE / "SessionFoldersBridge.swift").read_text()
    sends = (NATIVE / "SessionsOffloadBridge.swift").read_text()
    models = (ROOT / "src/ios/Agent/Chat/ChatStore.swift").read_text()
    configuration = "\n".join(declaration(models, name) for name in (
        "enum ChatFolderMemoryPolicy:", "struct ChatFolderConfiguration:"))
    methods = "\n".join(declaration(sends, marker) for marker in (
        "@MainActor\n    private static func resolveBindingModelName(",
        "@MainActor\n    private static func stageAttachments(",
        "@objc public static func callerSessionId(",
        "@objc public static func sendPrompt("))
    actual = (configuration + "\n" + folders + "\n" +
              declaration(sends, "private struct SessionFolderSendError:") +
              "\nprivate let logger = AppLogger(category: \"SessionsOffload\")\n" +
              "public class SessionsOffloadBridge: NSObject {\n" + methods + "\n}\n")
    actual = re.sub(r"(?m)^import UIKit\s*\n", "", actual)
    actual = re.sub(r"@objc\b\s*", "", actual)
    return actual


class SourceWiring(unittest.TestCase):
    """Small source checks only: these are not native execution results."""

    def test_extraction_contains_whole_actual_declarations(self):
        generated = extracted_swift()
        self.assertNotIn("@objc", generated)
        self.assertNotIn("import UIKit", generated)
        send = declaration((NATIVE / "SessionsOffloadBridge.swift").read_text(),
                           "@objc public static func sendPrompt(")
        self.assertIn(send.replace("@objc ", ""), generated)
        folder_body = declaration((NATIVE / "SessionFoldersBridge.swift").read_text(),
                                  "@objc public class SessionFoldersBridge:")
        self.assertIn(re.sub(r"@objc\b\s*", "", folder_body), generated)

    def test_objc_passes_guest_caller_and_folder_options(self):
        source = (NATIVE / "SessionsOffload.m").read_text()
        caller = source.split("static NSString *caller_session_id(void)", 1)[1].split("\n}", 1)[0]
        self.assertIn("current->group->fs_context", caller)
        self.assertIn("callerSessionIdWithFsContext:context", caller)
        send = source.split("static int cmd_send(", 1)[1].split("// ── Subcommand: folders", 1)[0]
        for token in ('folder:noff_find_arg(argc, argv, "--folder")',
                      'inheritModel:noff_has_flag(argc, argv, "--inherit-model")',
                      'callerSessionId:caller_session_id()',
                      'return [data[@"ok"] isEqual:@NO] ? NOFF_EXIT_ERROR : NOFF_EXIT_SUCCESS;'):
            self.assertIn(token, send)
        folders = source.split("static int cmd_folders(", 1)[1].split("// ── Subcommand: retry", 1)[0]
        for token in ('args[@"confirm"] = @YES', 'args[key] || i + 1 >= argc',
                      'noff_resolve_host_path(args[@"path"])',
                      'performWithAction:action args:args callerSessionId:caller_session_id()',
                      'return [data[@"ok"] isEqual:@NO] ? NOFF_EXIT_ERROR : NOFF_EXIT_SUCCESS;'):
            self.assertIn(token, folders)
        self.assertRegex(source, r'isEqualToString:@"folders"[\s\S]{0,180}cmd_folders\(')

    def test_fixture_has_entry_point_for_every_declared_scenario(self):
        behavior = (FIXTURES / 'Behavior.swift').read_text()
        self.assertIn('@main struct FolderBehaviorMain', behavior)
        for scenario in SCENARIOS:
            self.assertIn('"' + scenario + '"', behavior)
        self.assertIn('await testMove(scenario)', behavior)
        self.assertIn('await testCRUD(scenario)', behavior)
        self.assertIn('await testSend(scenario)', behavior)

    def test_project_registers_folder_bridge(self):
        project = (ROOT / 'src/ios/Minis.xcodeproj/project.pbxproj').read_text()
        self.assertEqual(project.count('SessionFoldersBridge.swift in Sources'), 2)
        source = (NATIVE / 'SessionsOffload.m').read_text()
        self.assertIn('if ([data[@"ok"] isEqual:@NO]) result[@"ok"] = @NO;', source)
        self.assertIn('NSString *prompt = nil;', source)
        self.assertNotIn('NSString *prompt = first_positional', source)

    def test_swift_caller_uses_router_token(self):
        source = (NATIVE / "SessionsOffloadBridge.swift").read_text()
        caller = declaration(source, "@objc public static func callerSessionId(")
        self.assertIn("MinisFsRouter.shared.sid(for: fsContext)", caller)
        self.assertNotIn("activeSession", caller)


SCENARIOS = (
    "caller_token", "send_default", "send_current", "send_none",
    "send_current_missing", "send_current_unfiled", "send_bad_caller",
    "send_ambiguous", "send_explicit_name", "send_existing", "send_existing_mismatch",
    "send_store_failure", "send_missing_persistence", "send_context_failure",
    "send_model_inheritance", "send_invalid_model", "send_inherit_invalid",
    "send_outcomes", "crud", "crud_failures", "request_validation",
    "selector_errors", "configure_patch", "configure_invalid", "configure_cas",
    "configure_storage_failure", "move_prevalidation", "move_none_current",
    "move_running_scope", "move_storage_failure", "helper_rejected",
    "remove_confirmation", "merge_preserves", "dissolve_preserves",
    "remove_running_descendant", "remove_storage_failure", "icon",
)


class NativeBehavior(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler = shutil.which("swiftc")
        if not compiler:
            message = "SKIP native: swiftc unavailable; actual Swift business logic NOT executed"
            if os.environ.get("SESSION_FOLDERS_REQUIRE_SWIFT") == "1":
                raise AssertionError(message)
            raise unittest.SkipTest(message)
        cls.directory = tempfile.TemporaryDirectory(prefix="session-folders-offline-")
        cls.addClassCleanup(cls.directory.cleanup)
        directory = Path(cls.directory.name)
        actual = directory / "Actual.swift"
        actual.write_text(extracted_swift())
        cls.binary = directory / "folder-tests"
        build = subprocess.run([
            compiler, "-swift-version", "5", "-parse-as-library", str(actual),
            str(FIXTURES / "Fakes.swift"), str(FIXTURES / "Behavior.swift"),
            "-o", str(cls.binary)], capture_output=True, text=True, timeout=180)
        if build.returncode:
            raise AssertionError("Actual Swift harness did not compile:\n" + build.stdout + build.stderr)

    def run_scenario(self, scenario):
        # Each case is a fresh process with fake stores; HOME / temp roots are
        # isolated too. The native app, CLI, simulator and phone are never run.
        with tempfile.TemporaryDirectory(prefix="session-folders-case-") as directory:
            env = dict(os.environ, HOME=directory, TMPDIR=directory,
                       SESSION_FOLDERS_FIXTURE_ROOT=directory)
            run = subprocess.run([str(self.binary), scenario], env=env,
                                 capture_output=True, text=True, timeout=30)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("PASS native " + scenario, run.stdout)


def _native_test(scenario):
    def test(self):
        self.run_scenario(scenario)
    test.__name__ = "test_" + scenario
    return test


for _scenario in SCENARIOS:
    setattr(NativeBehavior, "test_" + _scenario, _native_test(_scenario))

if __name__ == "__main__":
    print("Offline test only: source wiring + optional actual Swift with fakes. "
          "SKIP native is not a native pass.", flush=True)
    unittest.main(verbosity=2)
