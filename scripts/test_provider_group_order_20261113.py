#!/usr/bin/env python3
"""Provider-group ordering source contracts; no credentials, builds or app state.
Run: python3 scripts/test_provider_group_order_20261113.py
"""
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
IOS = ROOT / "src/ios"
VIEW = (IOS / "Views/Providers/ProviderInstancesView.swift").read_text()
PICKER = (IOS / "Views/Providers/UnifiedModelPicker.swift").read_text()
STORE = (IOS / "Providers/ProviderConfigStore.swift").read_text()
DB = (IOS / "Providers/ProviderConfigDB.swift").read_text()


def block(source, marker):
    start = source.index("{", source.index(marker))
    depth = 1
    end = start + 1
    while depth and end < len(source):
        depth += (source[end] == "{") - (source[end] == "}")
        end += 1
    if depth:
        raise AssertionError(f"unbalanced block: {marker}")
    return source[start + 1:end - 1]


class ProviderGroupOrderTests(unittest.TestCase):
    def test_both_screens_use_unfiltered_first_occurrence(self):
        types = block(VIEW, "static func types(in")
        self.assertIn("instances.compactMap", types)
        self.assertIn("seen.insert(instance.providerType).inserted", types)
        self.assertNotIn("isEnabled", types)
        self.assertNotIn("isVoiceOnly", types)
        self.assertIn("ProviderGroupOrder.rows(in: store.instances)", VIEW)
        build = block(PICKER, "private func buildSections()")
        self.assertIn("for type in ProviderGroupOrder.types(in: store.instances)", build)
        self.assertLess(build.index("ProviderGroupOrder.types"), build.index("instance.isEnabled"))
        self.assertNotIn("ProviderType.allCases", VIEW + build)

    def test_group_move_preserves_members_and_their_relative_order(self):
        ids = block(VIEW, "static func instanceIDs(in")
        self.assertIn("orderedTypes.flatMap", ids)
        self.assertIn("instances.filter { $0.providerType == type }.map(\\.id)", ids)
        self.assertNotIn("isEnabled", ids)
        self.assertNotIn("sorted", ids)
        move = block(VIEW, "private func moveRows(")
        self.assertIn("ProviderGroupOrder.reorderedIDs(", move)
        self.assertIn("store.reorderInstances(orderedIds)", move)
        logic = block(VIEW, "static func reorderedIDs(")
        self.assertIn("if case .group(let type) = row { return type }", logic)
        self.assertIn("instanceIDs(in: instances, orderedTypes: orderedTypes)", logic)
        self.assertNotIn("orderedTypes.append(instance.providerType)", logic)

    def test_groups_are_dragged_inline_in_edit_mode(self):
        self.assertNotIn("showGroupOrder", VIEW)
        self.assertNotIn("ProviderGroupOrderSheet", VIEW)
        self.assertIn(".environment(\\.editMode, $editMode)", VIEW)
        self.assertIn("ForEach(listRows)", VIEW)
        self.assertIn(".onMove(perform: moveRows)", VIEW)
        self.assertIn("groupHeaderRow(type)", VIEW)
        self.assertNotIn(".onMove(perform: moveGroups)", VIEW)
        self.assertIn("allowsFullSwipe: false", VIEW)
        swipe = block(VIEW, ".swipeActions(")
        self.assertIn("pendingDeleteInstance = instance", swipe)
        self.assertNotIn("store.removeInstance", swipe)
        self.assertIn("presenting: pendingDeleteInstance", VIEW)
        self.assertIn("store.removeInstance(instance.id)", VIEW)
        self.assertIn(".swipeEditDestination(item: $editingInstanceId)", VIEW)

    def test_instance_drag_and_shadow_voice_are_retained(self):
        move = block(VIEW, "static func reorderedIDs(")
        self.assertIn("member.providerType == instance.providerType", move)
        self.assertIn("orderedIDs = instances.map", move)
        self.assertIn("members.next() ?? instance.id", move)
        self.assertIn("let shadows = store.shadowVoiceProviders()", VIEW)
        self.assertIn("store.hasFoldedShadowDuplicates()", VIEW)
        self.assertIn("ForEach(shadows)", VIEW)
        self.assertIn("ShadowVoiceProviderDetailView(instanceId: shadow.instanceId)", VIEW)

    @unittest.skipUnless(shutil.which("swiftc"), "swiftc unavailable locally; run production Swift logic on Swift-enabled CI")
    def test_production_swift_drag_logic(self):
        # Compile the real production enums, not a Python rewrite. Only the two
        # model types are stubbed to avoid SwiftUI, Keychain and app dependencies.
        prelude = '''import Foundation
        enum ProviderType: String { case a, b, c }
        struct ProviderInstance { let id: String; let providerType: ProviderType }
        '''
        source = prelude + "\nenum ProviderGroupOrder {" + block(VIEW, "enum ProviderGroupOrder") + "}\n"
        source += "enum ProviderListRow: Identifiable {" + block(VIEW, "enum ProviderListRow") + "}\n"
        source += (ROOT / "scripts/fixtures/provider_group_order_main.swift").read_text()
        with tempfile.TemporaryDirectory(prefix="provider-group-order-") as directory:
            main = Path(directory) / "main.swift"
            binary = Path(directory) / "drag-tests"
            main.write_text(source)
            compiled = subprocess.run([shutil.which("swiftc"), str(main), "-o", str(binary)],
                                      capture_output=True, text=True, timeout=120)
            self.assertEqual(compiled.returncode, 0, compiled.stdout + compiled.stderr)
            executed = subprocess.run([str(binary)], capture_output=True, text=True, timeout=30)
            self.assertEqual(executed.returncode, 0, executed.stdout + executed.stderr)
            self.assertIn("PASS: 92 production Swift drag checks", executed.stdout)

    def test_picker_keeps_saved_order_after_selection_and_reload(self):
        capped = block(PICKER, "private var cappedEntriesByInstance")
        # The shared base order comes from the persisted instance array; the
        # management page and this picker must agree on it. A per-session
        # "last used provider" may lift ONE section for presentation only — it
        # never reorders the stored array and never survives a search.
        self.assertIn("orderedByLastUsedProvider(filteredEntriesByInstance)", capped)
        base = block(PICKER, "private func buildSections()")
        self.assertIn("ProviderGroupOrder.types(in: store.instances)", base)
        self.assertNotIn("ProviderType.allCases", base)
        lift = block(PICKER, "private func orderedByLastUsedProvider")
        self.assertIn("debouncedSearch.isEmpty", lift)
        self.assertIn("out.insert(picked, at: 0)", lift)
        self.assertNotIn("store.reorderInstances", lift)
        self.assertNotIn("store.save", lift)
        self.assertIn(".onChange(of: store.configRevision) { _ in loadSections() }", PICKER)
        build = block(PICKER, "private func buildSections()")
        self.assertIn("SystemVoiceProvider.providerInstance, systemEntries", build)
        self.assertIn("ProviderConfigStore.sortedByReleaseRank(entries)", build)

    def test_existing_save_path_persists_and_syncs_positional_order(self):
        reorder = block(STORE, "func reorderInstances(_ newOrder: [String])")
        self.assertIn("config.instances = reordered", reorder)
        self.assertIn("save()", reorder)
        save = block(STORE, "private func save()")
        self.assertIn("configRevision &+= 1", save)
        self.assertIn("JSONEncoder().encode(config)", save)
        self.assertIn("await db.bulkReplace(from: snapshot)", save)
        self.assertIn("await Self.emitV3MarkDirty(prior: prior, current: snapshot)", save)
        self.assertIn("where priorPos[inst.id] != idx", STORE)
        bulk = block(DB, "func bulkReplace(from")
        self.assertIn("for (idx, inst) in config.instances.enumerated()", bulk)
        self.assertIn('(r["sort_order"] as? Int) == idx', bulk)
        self.assertIn("sortOrder: idx", bulk)
        load = block(DB, "func loadAllInstanceRows()")
        self.assertRegex(load, re.compile(r"ORDER BY sort_order ASC"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
