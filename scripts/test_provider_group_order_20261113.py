#!/usr/bin/env python3
"""Provider-group ordering source contracts; no credentials, builds or app state.
Run: python3 scripts/test_provider_group_order_20261113.py
"""
from pathlib import Path
import re
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
        self.assertIn("ForEach(ProviderGroupOrder.types(in: store.instances)", VIEW)
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
        move = block(VIEW, "private func moveGroups(")
        self.assertIn("types.move(fromOffsets: source, toOffset: destination)", move)
        self.assertIn("ProviderGroupOrder.instanceIDs(in: instances, orderedTypes: types)", move)
        self.assertIn("store.reorderInstances(orderedIds)", move)

    def test_groups_are_dragged_inline_in_edit_mode(self):
        # Groups drag in the same list as providers: no sheet, no second screen.
        self.assertNotIn("showGroupOrder", VIEW)
        self.assertNotIn("ProviderGroupOrderSheet", VIEW)
        self.assertIn(".environment(\\.editMode, $editMode)", VIEW)
        editing = block(VIEW, "if editMode.isEditing, ProviderGroupOrder.types")
        self.assertIn("ForEach(ProviderGroupOrder.types(in: store.instances)", editing)
        self.assertIn(".onMove(perform: moveGroups)", editing)
        self.assertIn("分组顺序", editing)
        # Both drag surfaces share one persistence path.
        self.assertIn("moveGroups", VIEW)
        self.assertIn("moveInstances(in: type, from: source, to: destination)", VIEW)

    def test_instance_drag_and_shadow_voice_are_retained(self):
        self.assertIn("moveInstances(in: type, from: source, to: destination)", VIEW)
        move = block(VIEW, "private func moveInstances(in")
        self.assertIn("sectionIter.next() ?? inst.id", move)
        self.assertIn("store.reorderInstances(newGlobalIds)", move)
        self.assertIn("let shadows = store.shadowVoiceProviders()", VIEW)
        self.assertIn("store.hasFoldedShadowDuplicates()", VIEW)
        self.assertIn("ForEach(shadows)", VIEW)
        self.assertIn("ShadowVoiceProviderDetailView(instanceId: shadow.instanceId)", VIEW)

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
