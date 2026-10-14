# 160v64 iOS 15 repair 1

## Source identity

This branch starts from `f017c76cae19053a86236112544c4185c9e94783`, the ported application source produced by the original build #160 / run `37265888866` (porting scripts `650adb0`). It does not re-import current upstream or replay the latest accumulated compatibility guards. The installed baseline and original IPA have matching Mach-O UUID and `__TEXT,__text` SHA-256; differences in a re-signed whole-file digest do not establish a different application code version.

## Changes

- Keep iOS 15 hosting controllers for the same complete message/block identity; reset state only when the item changes. Update content even when measured height is unchanged.
- Measure full-width cells consistently. SwiftUI content owns its internal padding; do not subtract it again in the host. Refresh the root width on real width changes.
- Coalesce streaming/footer reflows while preserving the final pending invalidation. Layout timing is instance-local.
- Do not schedule streaming glyph alpha fades on iOS 15. Settle old ranges before full attributed-text replacement, teardown, and scene suspension. Retain the existing iOS 16+ animation behavior.
- Compare attributed-text prefixes across the union of old and new run boundaries; do not miss a color/font/transparent segment inside a longer new run. Keep original-font fallback reconciliation without discarding genuine style differences.
- Add Settings → Auto Context Compression using the existing global opt-in preference, so legacy chat-menu toggles and Settings share one value. Default soft budget: 256,000; trigger: 85% (217,600). A lower model/group window takes priority. The budget never enlarges a real model window; disabling it retains existing window protection.
- Proactive budget compaction uses an explicit persisted raw-history boundary strictly before the current run's first user input, rejects unfinished tool pairs, and retains original database messages. It is bounded and rechecks actual window safety after every awaited compaction, including no-progress/growing summaries.
- Package for minimum iOS 15.5 with source App Group entitlements only. No new elevated privileges, device installation, logout, or restart is performed. App build number: 160641.

## Research references

Reviewed implementation protocols, not wholesale library replacements:

- ChatLayout: `dd4cb5c8f91623331ba023d0ab64d844f8436204`, stable item identity, reconfigure transactions and layout invalidation: https://github.com/ekazaev/ChatLayout
- InputBarAccessoryView: `83cf29212e2cdb947226eead38a535c9b12629cb`, independent text updates and height-change notifications: https://github.com/nathantannar4/InputBarAccessoryView
- swift-markdown-ui: `8371aeb32f35795a9e559029fb08613355733626`, render/parse separation and iOS 15 limitations: https://github.com/gonzalezreal/swift-markdown-ui

No new dependency or copied library implementation is introduced. Existing licenses remain applicable. InputBarAccessoryView does not establish an IME marked-text fix; streaming output and Chinese composition must be tested separately.

## Validation boundaries

Python source-contract tests are not Swift compilation, UIKit runtime tests or proof of the original crash root cause. CI also executes the extracted production Foundation-only budget/preferences Swift code and builds the actual iPhoneOS application. Successful packaging/minimum-OS/signature checks do not prove every dynamically resolved symbol or every device behavior is compatible.

Device acceptance must cover continuous Chinese/English output, same-line and cross-line appends, stop/cancel/resume, session switching, code/tables/attachments, scrolling up during output, the final token followed by idle, and width changes (390→744→390). Verify iOS 16+ animation separately. Verify budget-off, lower model cap, 85% boundary, malformed saved input, no completed prior history, tool pairing, and no-progress compaction. Compaction summaries can omit details; original chat history remains stored.

No claim is made that all prior SIGABRT events share one layout cause; earlier logs also contain memory-pressure exit evidence. Device testing is required before calling the crashes fixed.
