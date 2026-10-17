#!/usr/bin/env python3
"""Read-only source contracts + in-memory SQL checks for the iOS 15.5 port.

Run: python3 scripts/test_appstore115_lowrisk_160651.py
Negative control: append --ref b113f88 (new activation/menu contracts must fail).
No Swift build, simulator, device, Keychain, or user preferences are accessed.
SQL checks execute queries extracted from Swift, not the Swift methods themselves.
"""
import argparse
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = "src/ios/"
BASELINE = "b113f88f0d6035e15e16533af825fe250052d578"
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--ref", help="Read Swift/catalog sources from a Git ref instead")
args, remaining = parser.parse_known_args()


def source(path, ref=None):
    if ref:
        return subprocess.check_output(
            ["git", "show", f"{ref}:{IOS}{path}"], cwd=ROOT, text=True)
    return (ROOT / IOS / path).read_text()


def body(text, marker):
    """Balanced block scanner; not a Swift parser. Comments/strings keep braces."""
    start = text.index("{", text.index(marker))
    level = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            level += 1
        elif text[i] == "}":
            level -= 1
            if level == 0:
                return text[start + 1:i]
    raise AssertionError("Unbalanced block: " + marker)


def sql(text, marker):
    return re.search(r'let sql = "([^"\n]+)"', body(text, marker))[1]


ENV = source("Shared/EnvVarStore.swift", args.ref)
UI = source("Views/Settings/EnvironmentVariablesView.swift", args.ref)
SKILLS = source("Agent/Session/SkillStore.swift", args.ref)
MENU = source("Views/Skills/SkillsManagementView.swift", args.ref)
MCP = source("Agent/Session/MCPStore.swift", args.ref)
SESSION_VIEWS = ("Views/Chat/SessionSkillsView.swift", "Views/MCP/SessionMCPsView.swift")


class LowRisk115Contracts(unittest.TestCase):
    def test_old_metadata_and_keychain_mutations_are_unchanged(self):
        original = source("Shared/EnvVarStore.swift", BASELINE)
        self.assertEqual(body(ENV, "struct EnvVarEntry:"), body(original, "struct EnvVarEntry:"))
        for marker in ("func add(", "func update(", "func updateNote(", "func delete(",
                       "func applyRemoteItem(", "func applyRemoteDeletion(", "func value(",
                       "func loadValueSync(", "func saveValueSync(", "func saveValue(",
                       "func deleteValue(", "private func saveEntries("):
            with self.subTest(marker=marker):
                self.assertEqual(body(ENV, marker), body(original, marker))

    def test_activation_is_opt_out_and_loaded_at_launch(self):
        self.assertIn('disabledEntryIDsKey = "envvar.disabled_entry_ids"', ENV)
        self.assertIn('@Published private(set) var disabledEntryIDs: Set<String> = []', ENV)
        self.assertIn('self.disabledEntryIDs = Self.loadDisabledEntryIDs()', body(ENV, 'init()'))
        self.assertIn('stringArray(forKey: disabledEntryIDsKey) ?? []', body(ENV, 'func loadDisabledEntryIDs('))
        self.assertIn('entries.first(where: { $0.id == id })?.key', body(ENV, 'func isEnabled('))
        self.assertIn('$0.key == key && disabledEntryIDs.contains($0.id)', body(ENV, 'func isEnabled('))

    def test_toggle_persists_only_ids_without_touching_values_or_sync(self):
        toggle = body(ENV, 'func setEnabled(')
        for expected in ('entries.first(where: { $0.id == id })?.key', 'isEnabled(id: id) != enabled',
                         'for entry in entries where entry.key == key', 'disabled.remove(entry.id)', 'disabled.insert(entry.id)',
                         'UserDefaults.standard.set(disabled.sorted(), forKey: Self.disabledEntryIDsKey)',
                         '"envvar.runtime.epoch"'):
            self.assertIn(expected, toggle)
        self.assertLess(toggle.index('UserDefaults.standard.set'), toggle.index('disabledEntryIDs = disabled'))
        for forbidden in ('saveValue', 'loadValue', 'deleteValue', 'saveEntries', 'markEntryDirty',
                          'ChatStore', 'keychain', 'logger'):
            self.assertNotIn(forbidden, toggle)

    def test_export_filters_disabled_keys_before_reading_any_value(self):
        export = body(ENV, 'func allAsDict(')
        for expected in ('Self.loadDisabledEntryIDs()', 'JSONDecoder().decode([EnvVarEntry].self',
                         'Set(entries.filter { disabled.contains($0.id) }.map(\\.key))',
                         'for entry in entries where !disabledKeys.contains(entry.key)'):
            self.assertIn(expected, export)
        self.assertLess(export.index('!disabledKeys.contains(entry.key)'),
                        export.index('Self.loadValue(forKey: entry.key)'))
        self.assertIn('dict[entry.key] = val', export)

    def test_disabled_secrets_remain_in_privacy_redaction(self):
        redactor = source('Shared/EnvVarRedactor.swift', args.ref)
        read = body(redactor, 'private static func loadAllValuesUncached(')
        self.assertIn('for entry in entries {', read)
        self.assertIn('EnvVarStore.loadValueSync(forKey: entry.key)', read)
        self.assertNotIn('disabled', read)
        self.assertNotIn('isEnabled', read)
        for marker in ('private func saveEntries(', 'func reloadFromDisk('):
            self.assertIn('EnvVarRedactor.invalidateCache()', body(ENV, marker))

    def test_both_shell_consumers_use_filtered_snapshot_even_if_empty(self):
        execution = source('Agent/ISH/ISHExecutionCoordinator.swift', args.ref)
        self.assertIn('var customEnv = EnvVarStore.shared.allAsDict()', execution)
        self.assertIn('environment: customEnv.isEmpty ? nil : customEnv', execution)
        terminal = source('Views/Rootfs/ISHTerminalView.swift', args.ref)
        startup = body(terminal, 'private func finishStartShell(')
        self.assertIn('var customEnv = EnvVarStore.shared.allAsDict()', startup)
        self.assertIn('ISHKernel.shared.customEnvironment = customEnv', startup)
        self.assertNotIn('if !customEnv.isEmpty', startup)
        self.assertLess(startup.index('customEnvironment = customEnv'), startup.index('executeCommand('))

    def test_ui_activation_is_separate_from_edit_reveal_and_copy(self):
        row = body(UI, 'private func envVarRow(')
        self.assertIn('Toggle("Enabled", isOn: Binding(', row)
        self.assertIn('get: { store.isEnabled(id: entry.id) }', row)
        self.assertIn('set: { store.setEnabled(id: entry.id, enabled: $0) }', row)
        self.assertNotIn('onTapGesture', row)
        summary = body(UI, 'private func envVarSummary(')
        for expected in ('revealedKeys.insert(entry.id)', 'UIPasteboard.general.string',
                         'editingEntry = entry'):
            self.assertIn(expected, summary)
        self.assertEqual(body(UI, 'private struct EnvVarFormSheet:'),
                         body(source('Views/Settings/EnvironmentVariablesView.swift', BASELINE),
                              'private struct EnvVarFormSheet:'))

    def test_source_copy_only_uses_existing_url_without_changing_skill_store(self):
        menu = body(MENU, '.contextMenu')
        self.assertIn('if let source = skill.sourceURL, !source.isEmpty', menu)
        self.assertIn('UIPasteboard.general.setItems', menu)
        self.assertIn('.localOnly: true', menu)
        self.assertIn('.expirationDate:', menu)
        self.assertIn('Label("Copy Source Link", systemImage: "link")', menu)
        for forbidden in ('URLSession', 'open(', 'setEnabled', 'deleteSkill', 'save', 'markDirty'):
            self.assertNotIn(forbidden, menu)
        self.assertEqual(body(SKILLS, 'var sourceURL:'),
                         body(source('Agent/Session/SkillStore.swift', BASELINE), 'var sourceURL:'))
        self.assertIn('if case .url(let u) = importSource { return u }', body(SKILLS, 'var sourceURL:'))

    def test_existing_session_batch_scope_and_draft_identity_are_preserved(self):
        for path in SESSION_VIEWS:
            view = source(path, args.ref)
            with self.subTest(path=path):
                self.assertIn('private func applyToAll(', view)
                bulk = body(view, 'private func applyToAll(')
                self.assertEqual(bulk.count('await ensureSessionId?()'), 1)
                self.assertIn('if let sid = resolvedSessionId', bulk)
                self.assertIn('resolvedSessionId = sid', bulk)
                self.assertEqual(bulk.count('store.setSessionOverride('), 2)
                self.assertNotIn('store.setEnabled(', bulk)
                self.assertNotIn('sessionId: ""', bulk)
                for expected in ('let scope = filtered', 'scope.allSatisfy { isEnabled($0) }',
                                 'applyToAll(scope, enabled: newValue)', 'store.sessionOverrideVersion'):
                    self.assertIn(expected, view)
                setter = body(SKILLS if 'Skill' in path else MCP, 'func setSessionOverride(')
                self.assertIn('dbSetSessionOverride(', setter)
                self.assertIn('sessionOverrideVersion += 1', setter)
                getter = body(SKILLS if 'Skill' in path else MCP, 'func isEnabledForSession(')
                self.assertIn('if let override = dbSessionOverride(', getter)
                self.assertIn('return override', getter)
                for forbidden in ('dbSetEnabled(', '.isEnabled =', '.enabled ='):
                    self.assertNotIn(forbidden, setter)

    def test_session_override_sql_is_scoped_and_deletion_supported(self):
        # Exercise actual parameterized SQL in an isolated in-memory DB.
        # This proves storage scope, NOT a particular default/inheritance policy.
        for store, table, item_column in ((SKILLS, 'session_skill_overrides', 'skill_id'),
                                          (MCP, 'mcp_session_overrides', 'server_id')):
            with self.subTest(table=table), sqlite3.connect(':memory:') as db:
                schema = re.search(r'CREATE TABLE IF NOT EXISTS ' + table + r' \(.*?;', store, re.S)[0]
                db.executescript(schema)
                insert = sql(store, 'private func dbSetSessionOverride(')
                delete = sql(store, 'private func dbDeleteSessionOverride(')
                select = sql(store, 'private func dbSessionOverride(')
                self.assertIn('session_id = ? AND ' + item_column + ' = ?', select)
                self.assertIn('session_id = ? AND ' + item_column + ' = ?', delete)
                db.execute(insert, ('other-session', 'visible', 1))
                db.execute(insert, ('current-session', 'hidden', 1))
                # A filtered bulk disable touches only the visible skill/server.
                for item in ['visible']:
                    db.execute(insert, ('current-session', item, 0))
                self.assertEqual(db.execute(select, ('current-session', 'visible')).fetchone(), (0,))
                self.assertEqual(db.execute(select, ('current-session', 'hidden')).fetchone(), (1,))
                self.assertEqual(db.execute(select, ('other-session', 'visible')).fetchone(), (1,))
                # Override deletion is also keyed by session + item.
                db.execute(delete, ('current-session', 'visible'))
                self.assertIsNone(db.execute(select, ('current-session', 'visible')).fetchone())

    def test_new_strings_are_localized_and_existing_values_preserved(self):
        catalog = json.loads(source('Localizable.xcstrings', args.ref))['strings']
        keys = ('Copy Source Link',
                'Disable a variable to keep its value without injecting it into new shells on this device. '
                'Existing processes are unchanged. This does not disable credentials already saved in providers or MCP servers.')
        for key in keys:
            for locale in ('en', 'zh-Hans', 'zh-Hant'):
                with self.subTest(key=key, locale=locale):
                    self.assertTrue(catalog[key]['localizations'][locale]['stringUnit']['value'])
        original = json.loads(source('Localizable.xcstrings', BASELINE))['strings']
        for key in ('Enabled', 'Disable All', 'Enable All'):
            self.assertEqual(catalog[key], original[key])

    def test_runtime_secret_resolution_refuses_disabled_values(self):
        resolver = source('Shared/Config/Collections/ProvidersCollection.swift', args.ref)
        self.assertIn('EnvVarStore.loadEnabledValueSync(forKey: name)', resolver)
        enabled = body(ENV, 'func loadEnabledValueSync(')
        self.assertIn('loadDisabledEntryIDs()', enabled)
        self.assertIn('$0.key == key && disabled.contains($0.id)', enabled)
        self.assertLess(enabled.index('disabled.contains'), enabled.index('return loadValueSync'))

    def test_mcp_epoch_does_not_reuse_old_environment_pool(self):
        cli = source('default_mount/usr/local/lib/minis-mcp-cli/main.py', args.ref)
        self.assertIn('os.environ.get("MINIS_ENV_EPOCH", "legacy")', cli)
        self.assertIn('PID_FILE = _daemon_base + ".pid"', cli)
        self.assertIn('PORT_FILE = _daemon_base + ".port"', cli)
        import ast
        tree = ast.parse(cli)
        nodes = [n for n in tree.body if isinstance(n, ast.Assign) and
                 any(isinstance(t, ast.Name) and t.id in ('_epoch', '_daemon_base', 'PID_FILE', 'PORT_FILE', 'LOCK_FILE') for t in n.targets)]
        class Environment:
            def __init__(self, epoch): self.environ = {'MINIS_ENV_EPOCH': epoch}
        def paths(epoch):
            namespace = {'os': Environment(epoch)}
            exec(compile(ast.Module(body=nodes, type_ignores=[]), '<epoch-test>', 'exec'), namespace)
            return tuple(namespace[k] for k in ('PID_FILE', 'PORT_FILE', 'LOCK_FILE'))
        self.assertNotEqual(paths('before'), paths('after'))
        self.assertTrue(all(p.startswith('/tmp/minis-mcp-daemon-') for p in paths('../../bad/epoch')))
        self.assertTrue(all('..' not in p for p in paths('../../bad/epoch')))

    def test_new_control_blocks_do_not_require_newer_ios_apis(self):
        blocks = body(UI, 'private func envVarRow(') + body(MENU, '.contextMenu')
        for forbidden in ('ShareLink(', 'ImageRenderer', 'SwiftData', 'NavigationStack',
                          '.topBarTrailing', '.onChange', 'sensoryFeedback', 'ContentUnavailableView'):
            self.assertNotIn(forbidden, blocks)


if __name__ == '__main__':
    print('SOURCE CONTRACTS + IN-MEMORY SQL ONLY; no Swift build or iOS/device verification.', flush=True)
    unittest.main(argv=['test_appstore115_lowrisk_160651.py'] + remaining, verbosity=2)
