#!/usr/bin/env python3
"""Provider-group ordering source contracts; no credentials, builds or app state.
Run: python3 scripts/test_provider_group_order_20261113.py
"""
from pathlib import Path
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
        rows = block(VIEW, "private var listRows")
        self.assertIn("ProviderGroupOrder.types(in: instances)", rows)
        self.assertNotIn("isEnabled", rows)
        build = block(PICKER, "private func buildSections()")
        self.assertIn("for type in ProviderGroupOrder.types(in: store.instances)", build)
        self.assertLess(build.index("ProviderGroupOrder.types"), build.index("instance.isEnabled"))
        self.assertNotIn("ProviderType.allCases", VIEW + build)

    def test_group_title_is_a_row_with_the_native_handle(self):
        # [T-provider-group-drag-v3] The title has to be a LIST ROW: the list
        # engine only gives reorder handles to rows, and a header can carry
        # neither the handle nor the drag. This also forbids the custom
        # gesture that never reacted on device.
        self.assertNotIn('GroupDragHandle', VIEW)
        self.assertNotIn('GroupFramesKey', VIEW)
        self.assertNotIn('highPriorityGesture', VIEW)
        self.assertNotIn('ProviderGroupOrderSheet', VIEW)
        self.assertNotIn('分组顺序', VIEW)
        self.assertIn('ForEach(listRows) { entry in', VIEW)
        self.assertIn('.onMove(perform: moveRows)', VIEW)
        entry = block(VIEW, 'struct ProviderListEntry')
        self.assertIn('case group(ProviderType)', entry)
        self.assertIn('case instance(ProviderInstance)', entry)

    def test_each_group_still_looks_like_its_own_card(self):
        bg = block(VIEW, 'private func rowBackground(')
        self.assertIn('RoundedRectangle(cornerRadius: 12', bg)
        self.assertIn('.padding(.top, entry.isFirst ? 8 : 0)', bg)
        self.assertIn('.padding(.bottom, entry.isLast ? 8 : 0)', bg)
        rows = block(VIEW, 'private var listRows')
        self.assertIn('isFirst: true, isLast: false', rows)
        self.assertIn('isLast: index == members.count - 1', rows)
        self.assertIn('.listRowSeparator(.hidden)', VIEW)
        self.assertIn('secondarySystemGroupedBackground', VIEW)

    def test_group_order_comes_from_title_rows_only(self):
        move = block(VIEW, 'private func moveRows(')
        self.assertIn('case .group(let type):', move)
        self.assertIn('if !types.contains(type) { types.append(type) }', move)
        self.assertIn('members[instance.providerType, default: []].append(instance.id)', move)
        self.assertIn('Set(ids) == Set(instances.map(\\.id))', move)
        self.assertIn('store.reorderInstances(ids)', move)
        # A provider row must never decide where a group sits.
        self.assertNotIn('types.append(instance.providerType)', move.split('for instance in instances')[0])

    def test_instance_and_shadow_voice_behaviour_is_kept(self):
        self.assertIn('allowsFullSwipe: false', VIEW)
        swipe = block(VIEW, '.swipeActions(')
        self.assertIn('pendingDeleteInstance = instance', swipe)
        self.assertNotIn('store.removeInstance', swipe)
        self.assertIn('presenting: pendingDeleteInstance', VIEW)
        self.assertIn('let shadows = store.shadowVoiceProviders()', VIEW)
        self.assertIn('store.hasFoldedShadowDuplicates()', VIEW)
        self.assertIn('ForEach(shadows)', VIEW)
        self.assertIn('ShadowVoiceProviderDetailView(instanceId: shadow.instanceId)', VIEW)

    def test_picker_keeps_saved_order_after_selection_and_reload(self):
        capped = block(PICKER, 'private var cappedEntriesByInstance')
        self.assertIn('orderedByLastUsedProvider(filteredEntriesByInstance)', capped)
        base = block(PICKER, 'private func buildSections()')
        self.assertIn('ProviderGroupOrder.types(in: store.instances)', base)
        self.assertNotIn('ProviderType.allCases', base)
        lift = block(PICKER, 'private func orderedByLastUsedProvider')
        self.assertIn('debouncedSearch.isEmpty', lift)
        self.assertNotIn('store.reorderInstances', lift)

    def test_existing_save_path_persists_and_syncs_positional_order(self):
        reorder = block(STORE, 'func reorderInstances(_ newOrder: [String])')
        self.assertIn('config.instances = reordered', reorder)
        self.assertIn('save()', reorder)
        save = block(STORE, 'private func save()')
        self.assertIn('configRevision &+= 1', save)
        self.assertIn('await db.bulkReplace(from: snapshot)', save)
        bulk = block(DB, 'func bulkReplace(from')
        self.assertIn('sortOrder: idx', bulk)

if __name__ == "__main__":
    unittest.main(verbosity=2)
