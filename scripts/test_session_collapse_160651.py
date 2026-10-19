#!/usr/bin/env python3
"""Source-contract tests for [T-sidebar-session-collapse].

The user's request (2026-10-20): a group can already be folded as a whole, but
there was no way to put ONE session away — folding the group hides all of it,
unfolding brings all of it back. What was asked for: tuck individual, no-longer
needed sessions inside a group, keeping the group open and the sessions still in
use on screen.

Contract:
- Manual only. Nothing is ever auto-collapsed (no date/age heuristic).
- No cap: 0..all members of a group.
- Group-scoped: the affordance exists only for a session with a folder, and the
  tucked rows come back inside the SAME group.
- The strip sits at the TOP of the group's members, above every shown row, so
  the rows below never reorder between the two states.
- Tucked rows keep their state visible: running / paused / unread roll up onto
  the strip (their own row badges are off screen).
- Per-device view state: persisted to UserDefaults, never synced, never written
  to the session record.
- Search must still find a tucked session, so collapse is bypassed while
  searching.
- Select-mode "select all" must still include tucked members.

Static source checks only; the visual/behavioural pass needs a device.
"""
import re
import unittest

from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
CONTENT = (ROOT / 'src/ios/Views/ContentView.swift').read_text()
STRINGS = (ROOT / 'src/ios/Localizable.xcstrings').read_text()


def section(start, end):
    i = CONTENT.index(start)
    return CONTENT[i:CONTENT.index(end, i)]


class CollapseModel(unittest.TestCase):
    """[T-sidebar-session-collapse] grouping produces the strip + visible rows."""

    def test_sidebar_group_carries_collapsed_ids(self):
        self.assertIn('var collapsedIds: [String] = []', CONTENT)
        self.assertIn('var collapseStripExpanded = false', CONTENT)
        for flag in ('collapsedAnyUnread', 'collapsedAnyActive', 'collapsedAnyPaused'):
            self.assertIn(f'var {flag} = false', CONTENT)

    def test_grouping_partitions_members(self):
        self.assertIn('let tuckedMembers = displayOrdered.filter { collapsedSessionIds.contains($0.id) }', CONTENT)
        self.assertIn('let shownMembers = displayOrdered.filter { !collapsedSessionIds.contains($0.id) }', CONTENT)
        self.assertIn('g.collapsedIds = tuckedMembers.map(\\.id)', CONTENT)

    def test_total_count_still_counts_everyone(self):
        # The card's "N chats" line is the real membership, not the visible rows.
        self.assertIn('g.totalCount = m.count', CONTENT)
        self.assertNotIn('g.totalCount = shownMembers.count', CONTENT)

    def test_tucked_rows_reenter_above_shown_rows(self):
        # The whole point of the layout: expanding the strip prepends, so the
        # rows the user is looking at never move.
        self.assertIn('g.ids = g.collapsedIds + g.ids', CONTENT)

    def test_folder_collapse_still_wins(self):
        # A closed group shows nothing at all — strip included.
        block = section('if g.isCollapsed {', '} else if g.collapseStripExpanded {')
        self.assertIn('g.ids = []', block)

    def test_strip_aggregates_only_tucked_members(self):
        idx = CONTENT.index('for s in tuckedMembers {')
        body = CONTENT[idx:CONTENT.index('}', idx) + 1]
        self.assertIn('collapsedAnyUnread', body)
        # Never reuses the group-level flags (a shown running session must not
        # light the strip).
        self.assertNotIn('g.anyUnread', body)
        self.assertNotIn('g.anyActive', body)


class CollapseInteraction(unittest.TestCase):

    def test_menu_item_only_for_filed_sessions(self):
        self.assertIn('if key.filed {', CONTENT)
        block = CONTENT[CONTENT.index('if key.filed {'):]
        block = block[:block.index('}\n        }')]
        self.assertIn('.toggleSessionCollapse(key.sid)', block)

    def test_wording_flips_with_state(self):
        self.assertIn('key.collapsed ? "Uncollapse" : "Collapse"', CONTENT)
        self.assertIn('let collapsed: Bool', CONTENT)

    def test_toggle_persists_immediately(self):
        idx = CONTENT.index('private func toggleSessionCollapse(_ sessionId: String) {')
        body = CONTENT[idx:CONTENT.index('\n    }', idx)]
        self.assertIn('collapsedSessionIds.insert(sessionId)', body)
        self.assertIn('collapsedSessionIds.remove(sessionId)', body)
        self.assertIn('UserDefaults.standard.set(Array(collapsedSessionIds), forKey: "collapsedSessionIds")', body)

    def test_state_loaded_once_from_defaults(self):
        self.assertIn('stringArray(forKey: "collapsedSessionIds")', CONTENT)

    def test_strip_open_state_is_not_persisted(self):
        # Deliberately transient: only the session marks persist.
        self.assertNotIn('forKey: "expandedCollapseStripGroupIds"', CONTENT)
        self.assertNotIn('forKey: "expandedCollapseStrips"', CONTENT)

    def test_deleted_sessions_are_pruned(self):
        idx = CONTENT.index('Drop tuck marks whose session no')
        body = CONTENT[idx:idx + 900]
        self.assertIn('collapsedSessionIds.intersection(liveIds)', body)
        self.assertIn('UserDefaults.standard.set(Array(pruned), forKey: "collapsedSessionIds")', body)

    def test_no_automatic_collapse_heuristic(self):
        # Nothing may tuck a session without the user asking.
        for bad in ('collapsedSessionIds.insert(s.id)',
                    'collapsedSessionIds.insert(session.id)',
                    'collapsedSessionIds.formUnion'):
            self.assertNotIn(bad, CONTENT)


class CollapseRendering(unittest.TestCase):

    def test_strip_row_exists_in_both_list_paths(self):
        self.assertEqual(CONTENT.count('erasedCollapseStrip(group)'), 2)

    def test_strip_sits_above_member_rows(self):
        for _ in range(2):
            pass
        for m in re.finditer(r'erasedCollapseStrip\(group\)', CONTENT):
            tail = CONTENT[m.end():m.end() + 200]
            self.assertIn('ForEach(group.ids', tail)

    def test_strip_hidden_in_select_mode(self):
        self.assertEqual(CONTENT.count('!group.collapsedIds.isEmpty, !group.isCollapsed, !isSelecting'), 2)

    def test_strip_carries_state_dots(self):
        idx = CONTENT.index('private func collapseStrip(_ group: SidebarGroup) -> some View {')
        body = CONTENT[idx:CONTENT.index('private func erasedCollapseStrip', idx)]
        for flag in ('collapsedAnyActive', 'collapsedAnyPaused', 'collapsedAnyUnread'):
            self.assertIn(flag, body)

    def test_card_corners_account_for_strip_only_groups(self):
        self.assertIn('var hasMemberRows: Bool { !ids.isEmpty || !collapsedIds.isEmpty }', CONTENT)
        self.assertIn('isExpanded: !group.isCollapsed && group.hasMemberRows', CONTENT)
        self.assertIn('FolderMemberRowBackground(isLast: group.ids.isEmpty)', CONTENT)

    def test_select_all_includes_tucked(self):
        self.assertIn('Set(group.ids).union(group.collapsedIds)', CONTENT)


class CollapseScopeAndSearch(unittest.TestCase):

    def test_search_bypasses_collapse(self):
        self.assertIn('collapsedSessionIds: isSearching ? [] : collapsedSessionIds', CONTENT)

    def test_collapse_state_in_memo_key(self):
        self.assertIn('let collapsedSessionIds: Set<String>', CONTENT)
        self.assertIn('let expandedCollapseStrips: Set<String>', CONTENT)
        self.assertIn('expandedCollapseStrips: expandedCollapseStripGroupIds', CONTENT)


class CollapseLocalization(unittest.TestCase):

    def test_chinese_strings_present(self):
        for key in ('"Collapse"', '"Uncollapse"', '"%lld collapsed chats"', '"Collapse %lld chats"'):
            self.assertIn(key, STRINGS)
        for value in ('收起', '移出收起', '已收起 %lld 个会话', '收起 %lld 个会话'):
            self.assertIn(value, STRINGS)

    def test_strip_uses_localized_text(self):
        # A bare String concatenation would render English regardless of locale.
        self.assertIn('Text("\\(group.collapsedIds.count) collapsed chats")', CONTENT)
        self.assertIn('Text("Collapse \\(group.collapsedIds.count) chats")', CONTENT)


class FolderIndependentExpand(unittest.TestCase):
    """[T-folder-independent-expand] Groups must not close each other.

    Reported 2026-10-20 with a screen recording: opening one group closed the
    other one, so the list only ever showed a single expanded group. The user's
    contract: a group is closed only when they close it.
    """

    def test_no_accordion_mass_collapse(self):
        self.assertNotIn('collapsedFolderIds = Set(folders.map(\\.id))', CONTENT)

    def test_toggle_touches_only_the_tapped_id(self):
        i = CONTENT.index('private func toggleFolderCollapsed(')
        body = CONTENT[i:CONTENT.index('UserDefaults.standard.set(Array(collapsedFolderIds)', i)]
        self.assertIn('collapsedFolderIds.remove(folderId)', body)
        self.assertIn('collapsedFolderIds.insert(folderId)', body)
        self.assertNotIn('Set(folders', body)

    def test_state_still_persisted(self):
        self.assertIn('forKey: "collapsedFolderIds"', CONTENT)

    def test_scroll_correction_removed_with_accordion(self):
        # That correction existed to chase a header dragged off screen by a
        # sibling closing above it; with independent state nothing above moves.
        self.assertNotIn('[T-ios-folder-accordion-scroll-anchor] Keep the tapped folder in view', CONTENT)


if __name__ == '__main__':
    unittest.main(verbosity=2)
