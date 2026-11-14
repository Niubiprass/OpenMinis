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
        section = block(VIEW, "private func groupSection(")
        self.assertIn("store.instances.filter { $0.providerType == type }", section)
        self.assertNotIn("isEnabled", section)
        build = block(PICKER, "private func buildSections()")
        self.assertIn("for type in ProviderGroupOrder.types(in: store.instances)", build)
        self.assertLess(build.index("ProviderGroupOrder.types"), build.index("instance.isEnabled"))
        self.assertNotIn("ProviderType.allCases", VIEW + build)

    def test_groups_keep_their_original_section_card_layout(self):
        # The UI must stay the original grouped list: one Section per provider
        # type, native header outside, one card of rows inside. The flattened
        # single-section rewrite and per-row card backgrounds were rejected.
        self.assertIn("ForEach(ProviderGroupOrder.types(in: store.instances), id: \\.self) { type in", VIEW)
        self.assertIn('groupSection(type)', VIEW)
        section = block(VIEW, 'private func groupSection(')
        self.assertIn('Section {', section)
        self.assertIn('} header: {', section)
        self.assertIn('.onMove { source, destination in', section)
        self.assertIn('moveInstances(in: type, from: source, to: destination)', section)
        for gone in ('ProviderListEntry', 'rowBackground', 'CardCornerShape',
                     'listRowBackground', 'ProviderGroupOrderSheet', '分组顺序'):
            self.assertNotIn(gone, VIEW)

    def test_header_is_the_grip_and_adds_no_new_icon(self):
        section = block(VIEW, 'private func groupSection(')
        self.assertNotIn('line.3.horizontal', section)
        self.assertIn('GroupHeaderDrag(enabled: editMode == .active', section)
        self.assertIn('.contentShape(Rectangle())', section)
        modifier = block(VIEW, 'struct GroupHeaderDrag')
        self.assertIn('content.onDrag {', modifier)
        self.assertIn('NSItemProvider(object: type.rawValue as NSString)', modifier)
        delegate = block(VIEW, 'struct GroupDropDelegate')
        self.assertIn('func performDrop(info: DropInfo) -> Bool', delegate)
        self.assertIn('perform(source, target)', delegate)

    def test_group_drop_only_reorders_groups(self):
        move = block(VIEW, 'private func moveGroup(from source: ProviderType')
        self.assertIn('ProviderGroupOrder.types(in: instances)', move)
        self.assertIn('types.remove(at: fromIndex)', move)
        self.assertIn('types.insert(source, at: insertAt)', move)
        self.assertIn('ProviderGroupOrder.instanceIDs(in: instances, orderedTypes: types)', move)
        self.assertIn('store.reorderInstances(ids)', move)

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
