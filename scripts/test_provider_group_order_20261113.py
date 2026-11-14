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
        self.assertIn("ForEach(ProviderGroupOrder.types(in: store.instances), id: \\.self)", VIEW)
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
        move = block(VIEW, "private func moveGroup(")
        self.assertIn("ProviderGroupOrder.types(in: store.instances)", move)
        self.assertIn("others.enumerated()", move)
        self.assertIn("y < frame.midY", move)
        self.assertIn("ProviderGroupOrder.instanceIDs(in: store.instances, orderedTypes: order)", move)
        self.assertIn("store.reorderInstances(ids)", move)
        # Dropping a group where it already sits must not rewrite anything.
        self.assertIn("guard target != from else { return }", move)

    def test_each_group_is_its_own_section_with_a_header_handle(self):
        # The regression this guards: every group was flattened into ONE list
        # section, which merged the cards. Groups are independent Sections.
        self.assertNotIn("showGroupOrder", VIEW)
        self.assertNotIn("ProviderGroupOrderSheet", VIEW)
        self.assertNotIn("ProviderListRow", VIEW)
        self.assertNotIn("8, 8)\u8c03\u6574", VIEW)
        self.assertIn(".environment(\\.editMode, $editMode)", VIEW)
        self.assertIn("ForEach(ProviderGroupOrder.types(in: store.instances), id: \\.self) { type in", VIEW)
        self.assertIn("groupSection(type)", VIEW)
        section = block(VIEW, "private func groupSection(")
        self.assertIn("Section {", section)
        self.assertIn("} header: {", section)
        self.assertIn("if editMode == .active {", section)
        self.assertIn("GroupDragHandle(type: type, drag: $groupDrag)", section)
        self.assertIn(".onMove { source, destination in", section)
        self.assertIn("moveInstances(in: type, from: source, to: destination)", section)

    def test_group_drag_follows_the_finger_and_undoes_nothing_else(self):
        handle = block(VIEW, "struct GroupDragHandle")
        self.assertIn("DragGesture(minimumDistance: 4, coordinateSpace: .global)", handle)
        self.assertIn("onDrop(value.location.y)", handle)
        self.assertIn(".highPriorityGesture(", handle)
        self.assertIn(".offset(y: groupDrag.dragging == type ? groupDrag.translation : 0)", VIEW)
        self.assertIn("value: [type: proxy.frame(in: .global)]", VIEW)
        self.assertIn("GroupFramesKey", VIEW)

    def test_instance_drag_stays_inside_its_group(self):
        move = block(VIEW, "private func moveInstances(in type: ProviderType")
        self.assertIn("let members = all.filter { $0.providerType == type }", move)
        self.assertIn("guard instance.providerType == type else { return instance.id }", move)
        self.assertIn("iterator.next()?.id ?? instance.id", move)
        self.assertIn("store.reorderInstances(ids)", move)
        self.assertNotIn("instanceIDs(in:", move)
        self.assertIn("allowsFullSwipe: false", VIEW)
        swipe = block(VIEW, ".swipeActions(")
        self.assertIn("pendingDeleteInstance = instance", swipe)
        self.assertNotIn("store.removeInstance", swipe)
        self.assertIn("presenting: pendingDeleteInstance", VIEW)
        self.assertIn("store.removeInstance(instance.id)", VIEW)
        self.assertIn(".swipeEditDestination(item: $editingInstanceId)", VIEW)
        self.assertIn("let shadows = store.shadowVoiceProviders()", VIEW)
        self.assertIn("store.hasFoldedShadowDuplicates()", VIEW)
        self.assertIn("ForEach(shadows)", VIEW)
        self.assertIn("ShadowVoiceProviderDetailView(instanceId: shadow.instanceId)", VIEW)

if __name__ == "__main__":
    unittest.main(verbosity=2)
