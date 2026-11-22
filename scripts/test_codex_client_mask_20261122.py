#!/usr/bin/env python3
"""Source contracts for [T-codex-client-mask] ("伪装 Codex 端").

Background, measured 2026-11-22 against new.sharedchat.cc/codex by replaying a
real codex 0.171.0 capture:

  • The gate is the body-level `client_metadata` block. Absent → 403
    `codex_access_restricted`; an empty object → 403; three keys already pass.
  • Our own tools, a tool set with no Codex tools, no tools at all, a one-line
    developer message instead of the 20 KB base instructions, and a body with
    none of the Codex message scaffolding ALL returned 200 with a real reply.
    Header subsets barely matter (User-Agent + originator alone was accepted).

So the implementation deliberately adds identity only, and must never rewrite
the caller's tools / instructions / messages: doing that would make the model
call `exec_command`, which this app cannot run.

These tests pin the parts that would silently regress: the field set (must keep
matching the real client), the gate conditions, persistence defaults, and the
places that copy a ProviderInstance (a dropped field there resets the toggle).
"""
import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROVIDER = (ROOT / 'src/ios/Providers/OpenAI/OpenAIProvider.swift').read_text()
INSTANCE = (ROOT / 'src/ios/Providers/ProviderInstance.swift').read_text()
FACTORY = (ROOT / 'src/ios/Providers/LLMProviderFactory.swift').read_text()
CHAT_FACTORY = (ROOT / 'src/ios/Agent/Chat/AIChatViewModel+ProviderFactory.swift').read_text()
DETAIL = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
STORE = (ROOT / 'src/ios/Providers/ProviderConfigStore.swift').read_text()
PBX = (ROOT / 'src/ios/Minis.xcodeproj/project.pbxproj').read_text()

CAPTURE = Path('/var/minis/shared/codex-fingerprint/codex_final_body.json')

# Key sets taken from the real codex 0.171.0 capture. Kept as constants so CI
# (which has no capture file) still pins the field set; when the capture IS
# present the tests additionally prove these constants did not drift from it.
EXPECTED_CLIENT_METADATA_KEYS = {
    'root_turn_id', 'session_id', 'thread_id', 'turn_id',
    'x-codex-installation-id', 'x-codex-turn-metadata', 'x-codex-window-id',
}
EXPECTED_TURN_METADATA_KEYS = {
    'installation_id', 'session_id', 'thread_id', 'agent_name', 'turn_id',
    'window_id', 'window_number', 'context_window_id', 'request_kind',
    'history_initialization', 'root_turn_id', 'thread_source', 'turn_trigger',
    'sandbox', 'sandbox_mode', 'auto_review_enabled',
    'node_repl_auto_review_required', 'node_repl_disabled',
    'turn_started_at_unix_ms', 'analytics_enabled', 'model',
}


def _emitted_client_metadata_keys():
    body = mask_body()
    # Anchor on the assignment, not the subscript: `out["client_metadata"]`
    # contains a `]` of its own that would truncate a naive scan.
    i = body.index('out["client_metadata"] = [')
    j = body.index('"prompt_cache_key"', i)
    return set(re.findall(r'"([a-z0-9\-_]+)":', body[i:j]))


def _emitted_turn_metadata_keys():
    body = mask_body()
    start = body.index('var turnMetadataJSON: String {')
    return set(re.findall(r'"([a-z0-9\-_]+)":', body[start:body.index('guard let data', start)]))


def mask_body():
    """The appended [T-codex-client-mask] section of OpenAIProvider.swift."""
    i = PROVIDER.index('// MARK: - Codex client mask')
    return PROVIDER[i:]


# --- Python port of the Swift helpers, to pin the observable shape ----------

def derived_uuid(seed: str) -> str:
    h1, h2 = 0xCBF2_9CE4_8422_2325, 0x9E37_79B9_7F4A_7C15
    for byte in seed.encode():
        h1 = ((h1 ^ byte) * 0x0000_0100_0000_01B3) & 0xFFFF_FFFF_FFFF_FFFF
        h2 = (((h2 + byte) * 0x0000_0100_0000_01B3) & 0xFFFF_FFFF_FFFF_FFFF) ^ (h2 >> 29)
    raw = bytearray()
    for shift in range(56, -1, -8):
        raw.append((h1 >> shift) & 0xFF)
    for shift in range(56, -1, -8):
        raw.append((h2 >> shift) & 0xFF)
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    h = raw.hex()
    return f"{h[0:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:32]}"


UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


class MaskShape(unittest.TestCase):

    def test_client_metadata_matches_the_real_client(self):
        """The keys we emit must be exactly the ones a real capture carries."""
        self.assertEqual(_emitted_client_metadata_keys(), EXPECTED_CLIENT_METADATA_KEYS,
                         'client_metadata keys drifted from the real Codex client')
        if CAPTURE.exists():
            real = set(json.loads(CAPTURE.read_text())['client_metadata'])
            self.assertEqual(EXPECTED_CLIENT_METADATA_KEYS, real,
                             'the pinned key set drifted from the capture')

    def test_turn_metadata_carries_every_field_the_client_sends(self):
        self.assertEqual(_emitted_turn_metadata_keys(), EXPECTED_TURN_METADATA_KEYS,
                         'turn metadata keys drifted from the real Codex client')
        if CAPTURE.exists():
            real = json.loads(
                json.loads(CAPTURE.read_text())['client_metadata']['x-codex-turn-metadata'])
            self.assertEqual(EXPECTED_TURN_METADATA_KEYS, set(real),
                             'the pinned key set drifted from the capture')

    def test_header_set_covers_the_identity_headers(self):
        body = mask_body()
        start = body.index('func headers(streaming: Bool)')
        head = body[start:body.index('func apply(to body', start)]
        for name in ('originator', 'User-Agent', 'session-id', 'thread-id',
                     'x-client-request-id', 'x-codex-window-id',
                     'x-codex-turn-metadata', 'x-codex-installation-id', 'Accept'):
            self.assertIn(f'"{name}"', head, f'missing header {name}')
        # Never fabricate auth: the key/OAuth path owns Authorization.
        self.assertNotIn('Authorization', head)

    def test_identical_ids_in_header_and_body(self):
        """Codex derives both from one turn; a mismatch is a visible tell."""
        # The helper lives outside the appended mask section, so search the file.
        helper = PROVIDER[PROVIDER.index('private func applyCodexClientMask'):]
        helper = helper[:helper.index('\n    }\n')]
        self.assertIn('ctx.headers(streaming: streaming)', helper)
        self.assertIn('ctx.apply(to: body)', helper)
        self.assertIn('let ctx = CodexClientMask.context(', helper)
        self.assertEqual(helper.count('CodexClientMask.context('), 1,
                         'context must be built once per request')

    def test_the_mask_never_rewrites_tools_or_messages(self):
        """Measured unnecessary; rewriting them would break the agent loop."""
        body = mask_body()
        for forbidden in ('out["tools"]', 'out["input"]', 'out["instructions"]',
                          'out["reasoning"]', 'out["include"]'):
            self.assertNotIn(forbidden, body)
        self.assertIn('out["client_metadata"]', body)


class MaskGating(unittest.TestCase):

    def test_mask_is_skipped_on_the_official_codex_backend(self):
        body = mask_body()
        gate = PROVIDER[PROVIDER.index('private func shouldApplyCodexClientMask'):]
        gate = gate[:gate.index('}')]
        self.assertIn('codexClientMask && isResponsesAPI && !isCodexOAuth', gate)

    def test_both_responses_builders_apply_it(self):
        # Agent stream path and offload path must not drift apart.
        self.assertGreaterEqual(PROVIDER.count('shouldApplyCodexClientMask(isResponsesAPI:'), 2)
        self.assertGreaterEqual(PROVIDER.count('applyCodexClientMask(to: &body'), 2)

    def test_default_is_off(self):
        self.assertIn('var codexClientMask: Bool = false', PROVIDER)
        self.assertIn('codexClientMask: Bool = false', INSTANCE)


class Persistence(unittest.TestCase):

    def test_old_data_decodes_to_off(self):
        self.assertIn('codexClientMask = (try? c.decodeIfPresent(Bool.self, forKey: .codexClientMask)) ?? false',
                      INSTANCE)

    def test_off_instances_serialize_without_the_key(self):
        self.assertIn('if codexClientMask { try c.encode(codexClientMask, forKey: .codexClientMask) }',
                      INSTANCE)

    def test_both_factories_carry_it(self):
        self.assertIn('p.codexClientMask = instance.codexClientMask', FACTORY)
        self.assertIn('p.codexClientMask = instance.codexClientMask', CHAT_FACTORY)
        self.assertIn('p.providerInstanceId = instance.id', FACTORY)

    def test_switching_api_format_keeps_the_toggle(self):
        """The picker rebuilds the instance from a field list — a missed field
        silently resets the user's setting."""
        i = DETAIL.index('let newInstance = ProviderInstance(')
        block = DETAIL[i:DETAIL.index('store.updateInstance(newInstance)', i)]
        self.assertIn('codexClientMask: instance.codexClientMask', block)

    def test_backup_import_keeps_the_toggle(self):
        self.assertIn('let codexClientMask = dict["codexClientMask"] as? Bool ?? false', STORE)
        self.assertIn('codexClientMask: codexClientMask', STORE)


class SettingsUI(unittest.TestCase):

    def test_toggle_exists_and_is_gated_to_responses(self):
        self.assertIn('private func codexClientMaskSection', DETAIL)
        self.assertIn('if instance.providerType == .openAIResponses {', DETAIL)
        self.assertIn('codexClientMaskSection(instance)', DETAIL)

    def test_toggle_wording_matches_the_reference_app(self):
        self.assertIn('伪装 Codex 端', DETAIL)
        self.assertIn('适配仅允许 Codex 的中转', DETAIL)

    def test_toggle_persists_through_the_store(self):
        i = DETAIL.index('private func codexClientMaskSection')
        section = DETAIL[i:i + 1200]
        self.assertIn('updated.codexClientMask = on', section)
        self.assertIn('store.updateInstance(updated)', section)


class Identity(unittest.TestCase):

    def test_derived_ids_are_stable_and_uuid_shaped(self):
        a = derived_uuid('thread:abc')
        b = derived_uuid('thread:abc')
        c = derived_uuid('thread:abd')
        self.assertEqual(a, b, 'same conversation must keep one thread id')
        self.assertNotEqual(a, c)
        self.assertRegex(a, UUID_RE)

    def test_swift_matches_the_port(self):
        """Pin the Swift algorithm to the ported one, so the shape cannot drift."""
        body = mask_body()
        self.assertIn('0xcbf2_9ce4_8422_2325', body)
        self.assertIn('0x0000_0100_0000_01b3', body)
        self.assertIn('bytes[6] = (bytes[6] & 0x0f) | 0x70', body)
        self.assertIn('bytes[8] = (bytes[8] & 0x3f) | 0x80', body)

    def test_thread_id_reuses_a_uuid_prompt_cache_key(self):
        body = mask_body()
        self.assertIn('uuidShaped(seed)', body)
        self.assertIn('seed.lowercased()', body)

    def test_installation_id_is_persisted_per_instance(self):
        body = mask_body()
        self.assertIn('codexClientMask.installationId.', body)
        self.assertIn('UserDefaults.standard.set(fresh, forKey: key)', body)


class Hygiene(unittest.TestCase):

    def test_no_test_key_is_hardcoded(self):
        for text in (PROVIDER, INSTANCE, DETAIL, FACTORY, CHAT_FACTORY, STORE):
            self.assertNotIn('sk-95d6', text)

    def test_version_bumped_for_this_feature(self):
        self.assertIn('MARKETING_VERSION = 1.16;', PBX)
        self.assertNotIn('MARKETING_VERSION = 1.15;', PBX)


if __name__ == '__main__':
    unittest.main(verbosity=2)
