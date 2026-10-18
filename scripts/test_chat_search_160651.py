#!/usr/bin/env python3
"""Source-contract tests for [T-115-chat-search]: in-chat search + jump.

Flow: AIChatView navigation bar magnifier -> ChatSearchView sheet (SQLite
search via existing ChatStore.searchMessages on the CURRENT session) ->
onSelect(MessageSearchJump) -> pendingSearchJump applied in sheet onDismiss ->
CollectionViewMessageListV3.searchJump consumed by the Coordinator
(nonce-gated) -> scrollToItem + transient yellow flash.

Hard constraints:
- The jump is applied ONLY after the sheet fully dismisses (onDismiss), so
  the list is visible before it scrolls.
- No changes to streaming, layout or compaction paths.
"""
import unittest
from pathlib import Path

ROOT = Path('/var/minis/shared/OpenMinis-160649')
V3 = (ROOT / 'src/ios/Agent/MessageList/CollectionViewMessageListV3.swift').read_text()
SEARCH = (ROOT / 'src/ios/Views/Chat/ChatSearchView.swift').read_text()
CHAT = (ROOT / 'src/ios/Views/Chat/AIChatView.swift').read_text()


class ChatSearchViewSource(unittest.TestCase):
    """[T-115-chat-search] The search sheet."""

    def test_sheet_exists_and_contract(self):
        self.assertIn('struct ChatSearchView: View', SEARCH)
        self.assertIn('let onSelect: (MessageSearchJump) -> Void', SEARCH)
        self.assertIn('TextField(AppLocalized("Search current chat…"), text: $query)', SEARCH)
        self.assertIn('Button(AppLocalized("Done")) { dismiss() }', SEARCH)

    def test_uses_existing_store_search_only(self):
        # Reuses ChatStore.searchMessages (SQLite LIKE + snippet) — no new
        # query engine, scoped to the current session.
        self.assertIn('await ChatStore.shared.searchMessages(', SEARCH)
        self.assertIn('sessionIds: sid.map { [$0] }', SEARCH)
        self.assertIn('keywords: keywords', SEARCH)
        self.assertIn('limit: 50', SEARCH)

    def test_result_maps_to_uuid_jump(self):
        self.assertIn('UUID(uuidString: r.messageId)', SEARCH)
        self.assertIn('MessageSearchJump(\n                    messageId: hit.id', SEARCH)
        self.assertIn('nonce: Int.random', SEARCH)


class MessageSearchJumpSource(unittest.TestCase):
    """[T-115-chat-search] The jump type."""

    def test_jump_type_equatable_with_nonce(self):
        self.assertIn('struct MessageSearchJump: Equatable {', V3)
        self.assertIn('let messageId: UUID', V3)
        self.assertIn('let nonce: Int', V3)
        self.assertIn('nonce-gated', V3)


class MessageListJumpSource(unittest.TestCase):
    """[T-115-chat-search] List-side consumption."""

    def test_representable_carries_jump(self):
        self.assertIn('var searchJump: MessageSearchJump? = nil', V3)

    def test_update_consumes_nonce_gated(self):
        # Only a NEW nonce fires a jump; re-renders with the same request are
        # no-ops (so the list never re-scrolls on unrelated updates).
        self.assertIn('if let jump = searchJump, jump != coord.lastHandledSearchJump {', V3)
        self.assertIn('coord.lastHandledSearchJump = jump', V3)
        self.assertIn('coord.handleSearchJump(jump)', V3)

    def test_coordinator_has_handler_and_state(self):
        self.assertIn('var lastHandledSearchJump: MessageSearchJump? = nil', V3)
        self.assertIn('func handleSearchJump(_ jump: MessageSearchJump)', V3)

    def test_handler_scrolls_and_flashes(self):
        self.assertIn('MessageListItem.messageId(of: $0) == target', V3)
        self.assertIn('cv.scrollToItem(at: ip, at: .top, animated: true)', V3)
        self.assertIn('0x5EAC', V3)          # flash overlay tag
        self.assertIn('systemYellow.withAlphaComponent(0.28)', V3)

    def test_handler_miss_is_graceful(self):
        self.assertIn('jump MISS', V3)


class ChatViewIntegrationSource(unittest.TestCase):
    """[T-115-chat-search] AIChatView wiring."""

    def test_state_and_toolbar_button(self):
        self.assertIn('@State private var showChatSearch = false', CHAT)
        self.assertIn('@State private var chatSearchJump: MessageSearchJump? = nil', CHAT)
        self.assertIn('@State private var pendingSearchJump: MessageSearchJump? = nil', CHAT)
        self.assertIn('Image(systemName: "magnifyingglass")', CHAT)

    def test_jump_applied_only_on_dismiss(self):
        # The ONLY place chatSearchJump is written must be the sheet's
        # onDismiss block; the sheet body may only set pendingSearchJump.
        self.assertIn('.sheet(isPresented: $showChatSearch, onDismiss: {', CHAT)
        self.assertIn('chatSearchJump = j', CHAT)
        self.assertIn('pendingSearchJump = jump', CHAT)
        # Negative: the sheet itself must not apply the jump directly.
        sheet_body_zone = CHAT.split('.sheet(isPresented: $showChatSearch', 1)[1]
        sheet_body_zone = sheet_body_zone.split('.sheet(isPresented: $showTokenUsage)', 1)[0]
        self.assertNotIn('chatSearchJump = jump', sheet_body_zone)

    def test_list_instantiation_wires_jump(self):
        self.assertIn('searchJump: chatSearchJump,', CHAT)

    def test_toolbar_host_opened_by_search_callback(self):
        self.assertIn('onSearch: {', CHAT)
        self.assertIn('showChatSearch = true', CHAT)
        self.assertIn('let onSearch: () -> Void', CHAT)


if __name__ == '__main__':
    unittest.main(verbosity=2)