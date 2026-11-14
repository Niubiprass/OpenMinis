#!/usr/bin/env python3
"""Static guard for [T-model-refresh-authoritative].

The refresh response is the model list: an unlisted catalog entry is deleted
immediately, no "not listed" marker and no grace window; a later response that
lists it restores it (overrides + groups) from a local tombstone. The number of
models is never used as a completeness signal: 12 -> 2 and 2 -> 12 are both
applied at once. A successful response replaces even when it is empty; failed or
unfinished requests keep the old list. Paginated providers must finish paging
before replacement.

Runs in seconds; the behavioural model lives in
src/ios/MinisTests/Standalone/ModelAbsenceGraceTests.swift.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STORE = ROOT / "src/ios/Providers/ProviderConfigStore.swift"
TEST = ROOT / "src/ios/MinisTests/Standalone/ModelAbsenceGraceTests.swift"
PICKER = ROOT / "src/ios/Views/Providers/UnifiedModelPicker.swift"

fails = []


def need(cond, what):
    if not cond:
        fails.append(what)


def main():
    store = STORE.read_text()
    test = TEST.read_text()
    picker = PICKER.read_text()

    # The deletion path.
    need("let absentCatalog = existing.filter { !$0.isCustom && !refreshedModelIds.contains($0.baseModel.id) }" in store,
         "unlisted catalog entries are collected for deletion")
    need("suspiciousShrink" not in store, "no count heuristic remains")
    need("return ModelFetchResult(models: models, source: \"api\"" in store,
         "a successful response is accepted even when empty")
    need("degraded: false" in store, "success is marked as authoritative")
    need("deleted \\(absentCatalog.count) unlisted catalog entr" in store,
         "a normal refresh logs the deletion")
    need("now.timeIntervalSince(since) > Self.modelAbsenceGracePeriod" not in store,
         "grace expiry no longer decides deletion")
    need("absentSince: nil" in store, "returned entries carry no stale marker")

    # Display counts must describe the applied list, not falsely count preserved
    # custom/voice rows as removed or duplicate API rows as extra models.
    summary = store.index('let finalModelIds =')
    need(summary > store.index('config.modelEntries.append(contentsOf: enrichedCustom)'),
         'summary measured after custom preservation')
    need(summary > store.index('config.modelEntries.append(contentsOf: preservedVoice)'),
         'summary measured after voice preservation')
    need('ModelListDiff(found: models.count,' in store, 'found count uses deduplicated models')
    need('removed: beforeSet.subtracting(finalSet).count' in store, 'removed count uses final applied set')
    need('added: finalSet.subtracting(beforeSet).count' in store, 'added count uses final applied set')
    detail = (ROOT / 'src/ios/Views/Providers/ProviderInstanceDetailView.swift').read_text()
    need('guard let diff = store.replaceEntries' in detail, 'skipped application cannot display success')
    need('fetchSummary = nil' in detail and 'if let summary = fetchSummary' in detail,
         'summary clears at refresh start and is displayed')

    # Restoration.
    need("struct RetiredModelOverride: Codable" in store, "tombstone type exists")
    need("retiredModelTTL: TimeInterval = 90 * 24 * 60 * 60" in store, "tombstones expire")
    need("retired.removeValue(forKey: retiredKey(instanceId, model.id))" in store,
         "a re-listed model is restored from its tombstone")
    need("restoredGroups.append" in store, "groups are remembered")
    need("restored \\(restoredCount) group membership" in store, "groups are restored")
    need("saveRetiredModelOverrides(retired)" in store, "tombstones are persisted")

    # Group refs still pruned on a real removal.
    need("removedMembers[entryId] = now" in store,
         "group removals are stamped for sync")
    need("safer" not in store, "no stale finder left")
    for rel in ("OpenAI/OpenAIModelsAPI.swift", "Anthropic/AnthropicModelsAPI.swift", "Gemini/GeminiModelsAPI.swift"):
        need("ModelPagination.collect" in (ROOT / "src/ios/Providers" / rel).read_text(),
             f"{rel} finishes pagination before replacing")
    need("struct ModelPage" in (ROOT / "src/ios/Providers/ModelPagination.swift").read_text(),
         "pagination helper exists")
    need("advertised another page but gave no cursor" in (ROOT / "src/ios/Providers/ModelPagination.swift").read_text(),
         "a missing cursor is an incomplete list, not a short one")
    need("func refreshModels(for instance: ProviderInstance) async -> ModelRefreshOutcome" in store,
         "refresh reports success or failure")

    # Rule tag present in both places, so the intent is traceable.
    need("[T-model-refresh-authoritative]" in store, "store rule is tagged")
    need("[T-model-refresh-authoritative]" in test, "test names the rule")

    # The picker still knows how to render a legacy absent entry.
    need("isUnavailableFromProvider" in picker, "legacy marker rendering still exists")

    if fails:
        print("❌ model-refresh-authoritative guard failed:")
        for f in fails:
            print("   -", f)
        return 1
    print("✅ model-refresh-authoritative guard passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
