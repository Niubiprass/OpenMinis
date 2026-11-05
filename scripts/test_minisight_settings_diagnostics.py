#!/usr/bin/env python3
"""Offline structural checks; no iOS build, network, device or live AI request."""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "src/ios/Views/Settings/MiniSightSettingsView.swift"
SOURCE = FILE.read_text()

def section(start, end):
    return SOURCE.split(start, 1)[1].split(end, 1)[0]

class SettingsDiagnostics(unittest.TestCase):
    def test_all_existing_appstorage_settings_have_change_and_snapshot(self):
        bindings = re.findall(r'@AppStorage\("([^"]+)"\) private var (\w+)', SOURCE)
        self.assertEqual(len(bindings), 12, "Review intentional additions explicitly")
        snapshot = section('private var settingsSnapshot:', 'private func settingEvent')
        for key, variable in bindings:
            self.assertIn(f'.onChange(of: {variable})', SOURCE)
            self.assertIn(f'("{key}", {variable})', snapshot)
            self.assertIn(f'setting: "{key}"', SOURCE)

    def test_revision_disk_readback_gates_publish(self):
        flush = section('private func flushAndPost(', 'private func post(')
        for token in ['UUID().uuidString', 'defaults.set(revision, forKey: "minisight.settings.revision")',
                      '_ = defaults.synchronize()', 'readDefaultsDomain()', 'for item in snapshot',
                      '.isEqual(item.value)', 'guard mismatches == 0, revisionMatches else',
                      'shownMatches', '"readback_mismatch"', '"readback_failed"', 'settingsError =']:
            self.assertIn(token, flush)
        self.assertLess(flush.index('guard mismatches == 0, revisionMatches else'), flush.index('post(name)'))
        self.assertNotRegex(flush, r'(if|guard)\s+.*synchronize\(')
        self.assertIn('stage: "publish", result: "pending"', flush)
        self.assertNotIn('stage: "receive"', flush)
        self.assertNotIn('"apply"', flush)
        disk = section('static func readDefaultsDomain()', '/// Bounded at the handle')
        self.assertIn('Library/Preferences', disk)
        self.assertIn('PropertyListSerialization', disk)
        self.assertNotIn('dictionaryRepresentation', disk)

    def test_file_writes_are_verified_and_persona_autosave_preserved(self):
        shown = section('static func saveShown(', 'static func loadAI(')
        self.assertIn('throws', shown)
        self.assertIn('Data(contentsOf: shownURL) == expected', shown)
        self.assertNotIn('try?', shown)
        self.assertIn('DispatchQueue.main.asyncAfter(deadline: .now() + 0.45', SOURCE)
        self.assertIn('replacingPersona(text, in: current)', SOURCE)
        self.assertIn('onWrite?()', SOURCE)
        self.assertIn('verified == data, UIImage(data: verified) != nil', SOURCE)
        for setting in ['ai_persona', 'ai_connection']:
            self.assertIn(f'"setting": "{setting}", "readback": true', SOURCE)

    def test_test_uses_shared_ai_and_logs_lifecycle_without_content(self):
        test = section('private func testAI() async', 'private func cancelAITest()')
        self.assertIn('MiniSightAI(container:', test)
        self.assertEqual(test.count('client.send('), 1)
        self.assertNotIn('URLSession', test)
        for stage in ['click', 'skip', 'start', 'response', 'display']:
            self.assertIn(f'"ai_test", "{stage}"', test)
        self.assertIn('"ai_test", "cancel"', SOURCE)
        for reason in ['busy', 'cooldown', 'persona_unsaved', 'connection_unsaved', 'invalid_input', 'stale_generation']:
            self.assertIn(f'"{reason}"', test)
        self.assertNotIn('reply.displayText', SOURCE)
        self.assertNotIn('localizedDescription', SOURCE)
        self.assertNotIn('MSDiagMessage(', SOURCE)
        for match in re.finditer(r'MSDiagEvent\((.*?)\)\s*\n', SOURCE, re.S):
            call = match.group(1)
            self.assertNotRegex(call, r'config\.(endpoint|key|model)|reply\.(text(?!\.count)|displayText)|aiURL|aiKey|aiModel|aiPersona|error\.localized')

    def test_log_reader_bounded_and_redacted(self):
        reader = section('private enum MiniSightSettingsDiagnostics', 'private struct MiniSightRuntimeLogView')
        self.assertIn('static let tailBytes = 60 * 1024', reader)
        self.assertIn('read(upToCount: tailBytes)', reader)
        self.assertIn('seek(toOffset: offset)', reader)
        self.assertNotIn('Data(contentsOf:', reader.replace('// Bounded at the handle, not after Data(contentsOf:)', ''))
        for name in ['diagnostic-app.log', 'diagnostic-app.log.1', 'diagnostic-plugin.log', 'diagnostic-plugin.log.1', 'diagnostic.log', 'diagnostic.log.1']:
            self.assertIn(f'"{name}"', reader)
        self.assertIn('compactMap { sanitizedEvent', reader)
        self.assertIn('guard !filename.hasPrefix("diagnostic.log")', reader)
        self.assertIn('for (key, value) in input where allowed.contains(key)', reader)
        view = SOURCE.split('private struct MiniSightRuntimeLogView', 1)[1]
        self.assertIn('@State private var source = 0', view)
        for token in ['UIPasteboard.general.string = text', 'Button("刷新")', 'failure =', 'presentationMode']:
            self.assertIn(token, view)
        self.assertNotIn('NavigationStack', view)

    def test_swift_syntax_if_parser_available(self):
        try:
            from tree_sitter import Language, Parser
            import tree_sitter_swift
        except ImportError:
            self.skipTest('Optional tree_sitter + tree_sitter_swift not installed; structural checks still run')
        try:
            tree = Parser(Language(tree_sitter_swift.language())).parse(SOURCE.encode())
        except ValueError as error:
            self.skipTest('Parser ABI mismatch; Swift/iOS compile not verified: ' + str(error))
        errors = []
        def visit(node):
            if node.type == 'ERROR' or node.is_missing:
                errors.append((node.type, tuple(node.start_point), tuple(node.end_point)))
            for child in node.children:
                visit(child)
        visit(tree.root_node)
        self.assertEqual(errors, [], errors[:10])

if __name__ == '__main__':
    unittest.main(verbosity=2)
