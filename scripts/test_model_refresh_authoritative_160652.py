#!/usr/bin/env python3
"""Static guard for [T-model-refresh-authoritative].

The refresh response is the model list: an unlisted catalog entry is deleted
immediately, no "not listed" marker and no grace window; a later response that
lists it restores it (overrides + groups) from a local tombstone. Only a
suspicious shrink (more than half of a list of >= 4 gone) defers deletion for one
round.

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
    need("let suspiciousShrink = existing.count >= 4 && models.count * 2 < existing.count" in store,
         "shrink threshold is the documented one")
    need("if suspiciousShrink {" in store, "shrink defers deletion")
    need("deleted \\(absentCatalog.count) unlisted catalog entr" in store,
         "a normal refresh logs the deletion")
    need("now.timeIntervalSince(since) > Self.modelAbsenceGracePeriod" not in store,
         "grace expiry no longer decides deletion")
    need("kept.absentSince = nil" in store, "the old marker is normalised away")

    # Restoration.
    need("struct RetiredModelOverride: Codable" in store, "tombstone type exists")
    need("retiredModelTTL: TimeInterval = 90 * 24 * 60 * 60" in store, "tombstones expire")
    need("retired.removeValue(forKey: retiredKey(instanceId, model.id))" in store,
         "a re-listed model is restored from its tombstone")
    need("restoredGroups.append" in store, "groups are remembered")
    need("restored \\(restoredCount) group membership" in store, "groups are restored")
    need("saveRetiredModelOverrides(retired)" in store, "tombstones are persisted")

    # Group refs still pruned on a real removal.
    need("if suspiciousShrink {" in store and "prunedEntryIds" in store,
         "group references are pruned only for real removals")

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
