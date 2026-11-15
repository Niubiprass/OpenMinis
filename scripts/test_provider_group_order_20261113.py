#!/usr/bin/env python3
"""Provider-group ordering source contracts; no credentials, builds or app state.
Run: python3 scripts/test_provider_group_order_20261113.py
"""
from pathlib import Path
import os
import shutil
import subprocess
import sys
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
        self.assertIn("instances.filter { $0.providerType == type }", rows)
        self.assertNotIn("isEnabled", rows)
        build = block(PICKER, "private func buildSections()")
        self.assertIn("for type in ProviderGroupOrder.types(in: store.instances)", build)
        self.assertLess(build.index("ProviderGroupOrder.types"), build.index("instance.isEnabled"))
        self.assertNotIn("ProviderType.allCases", VIEW + build)

    def test_titles_are_rows_so_the_system_gives_them_a_handle(self):
        # Chosen explicitly: the system only reorders ROWS, so the grey title is
        # a row now and gets the native ☰ in edit mode. It is drawn with a clear
        # background so the screen still looks like separate cards with the
        # title outside them.
        self.assertIn('ForEach(listRows)', VIEW)
        self.assertIn('.onMove(perform: moveRows)', VIEW)
        self.assertIn('private func moveRows(from source: IndexSet', VIEW)
        self.assertNotIn('ProviderGroupDragBridge', VIEW)
        self.assertNotIn('UILongPressGestureRecognizer', VIEW)
        self.assertNotIn('GroupHeaderDrag', VIEW)
        self.assertNotIn('line.3.horizontal', VIEW)

    def test_group_title_looks_like_the_old_header(self):
        bg = block(VIEW, 'private func rowBackground(')
        self.assertIn('case .group:', bg)
        self.assertIn('Color.clear', bg)
        self.assertIn('CardCornerShape(top: entry.isFirstMember ? 12 : 0', bg)
        content = block(VIEW, 'private func rowContent(')
        self.assertIn('providerGroupTitle(type, count:', content)
        title = block(VIEW, 'private func providerGroupTitle(')
        self.assertIn('.font(.caption)', title)
        self.assertIn('case .group(let type):', content)
        rows = block(VIEW, 'private var listRows')
        self.assertIn('isFirstMember: index == 0, isLastMember: index == members.count - 1', rows)

    def test_group_order_comes_only_from_title_rows(self):
        move = block(VIEW, 'private func moveRows(from source: IndexSet')
        self.assertIn('case .group(let type):', move)
        self.assertIn('if !types.contains(type) { types.append(type) }', move)
        self.assertIn('store.reorderInstances(ids)', move)
        self.assertIn('Set(ids) == Set(instances.map(\\.id))', move)

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
