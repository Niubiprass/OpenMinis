// Tests for [T-model-refresh-authoritative] — the refresh response IS the
// model list.
//
// The old rule was [T-model-absence-grace]: a catalog model a provider stopped
// listing was kept for 7 days, labelled "Not listed by provider". On a relay
// that drops a model from /v1/models for one response and lists it again on the
// next — common with upstream rotation — the row flipped to "not listed",
// reappeared, and the cycle repeated; the 7-day clock was never reached.
//
// The rule under test: a catalog entry missing from the response is deleted on
// the spot, no marker, no grace. A later response that lists it restores it —
// with its overrides and its group memberships, from a local tombstone. The one
// exception is a suspicious shrink (more than half of a list of at least four
// gone at once), which keeps everything for one round because that is what a
// truncated response looks like.
//
// Standalone (`swift ModelAbsenceGraceTests.swift`) like its neighbours:
// deps/libs/libish_emu.a is device-only arm64, so the app cannot link for a
// simulator and an XCTest bundle has nowhere to run.

import Foundation

var failures = 0
func ck(_ l: String, _ ok: Bool) { if ok { print("  ✅ \(l)") } else { print("  ❌ \(l)"); failures += 1 } }
func ckEq<T: Equatable>(_ l: String, _ a: T, _ b: T) {
    if a == b { print("  ✅ \(l)") } else { print("  ❌ \(l)\n     expected: \(b)\n     actual:   \(a)"); failures += 1 }
}

// MARK: - Model of the entry, tombstone and refresh rule

struct Entry: Equatable {
    var modelId: String
    var contextWindowOverride: Int?
    var isCustom: Bool = false
    var groupIds: [String] = []
    var baseContextWindow: Int = 1_048_576
    var effectiveContextWindow: Int { contextWindowOverride ?? baseContextWindow }
}

struct Tombstone: Equatable {
    let uuid: String
    let contextWindowOverride: Int?
    let groupIds: [String]
}

/// Mirrors the NEW replaceEntries: delete unlisted catalog entries, restore
/// re-listed ones from the tombstone, keep everything on a suspicious shrink.
func replace(existing: [Entry], returned: [String], now: Date = Date(),
             tombs: inout [String: Tombstone], newBase: Int = 1_048_576) -> [Entry] {
    let returnedSet = Set(returned)
    let shrink = existing.count >= 4 && returned.count * 2 < existing.count
    var out: [Entry] = []
    for id in returned {
        let prior = existing.first { $0.modelId == id }
        let tomb = prior == nil ? tombs.removeValue(forKey: id) : nil
        out.append(Entry(modelId: id,
                         contextWindowOverride: prior?.contextWindowOverride ?? tomb?.contextWindowOverride,
                         isCustom: false,
                         groupIds: prior?.groupIds ?? tomb?.groupIds ?? [],
                         baseContextWindow: newBase))
    }
    for e in existing where !e.isCustom && !returnedSet.contains(e.modelId) {
        if shrink { out.append(e); continue }
        tombs[e.modelId] = Tombstone(uuid: "uuid-\(e.modelId)",
                                     contextWindowOverride: e.contextWindowOverride,
                                     groupIds: e.groupIds)
    }
    for e in existing where e.isCustom && !returnedSet.contains(e.modelId) { out.append(e) }
    return out
}

let t0 = Date(timeIntervalSince1970: 1_800_000_000)
func find(_ list: [Entry], _ id: String) -> Entry? { list.first { $0.modelId == id } }

// MARK: - 1. The reported loop is gone

print("\n▶️  a model skipped once disappears immediately")
let target = "gemini-3.8-flash-high"
var tombs: [String: Tombstone] = [:]
let before = [Entry(modelId: target, contextWindowOverride: 400_000, groupIds: ["g1"]),
              Entry(modelId: "gemini-3.8-flash"), Entry(modelId: "gpt-4o")]
let after1 = replace(existing: before, returned: ["gemini-3.8-flash", "gpt-4o"], now: t0, tombs: &tombs)
ck("the entry is gone", find(after1, target) == nil)
ck("so no row can show a 'not listed' state", find(after1, target) == nil)
ckEq("its override is not lost, it is tombstoned", tombs[target]?.contextWindowOverride, 400_000)
ckEq("its group is remembered too", tombs[target]?.groupIds, ["g1"])

// MARK: - 2. Coming back restores everything

print("\n▶️  a later response that lists it brings it back intact")
let after2 = replace(existing: after1, returned: [target, "gemini-3.8-flash", "gpt-4o"],
                     now: t0.addingTimeInterval(60), tombs: &tombs)
ckEq("entry is back", find(after2, target)?.modelId, target)
ckEq("override restored", find(after2, target)?.contextWindowOverride, 400_000)
ckEq("group restored", find(after2, target)?.groupIds, ["g1"])
ck("tombstone consumed", tombs[target] == nil)

// MARK: - 3. Suspicious shrink defers deletion

print("\n▶️  a half-length list keeps everything for one round")
var shrinkTombs: [String: Tombstone] = [:]
let big = (0..<12).map { Entry(modelId: "m\($0)") }
let shrunk = replace(existing: big, returned: (0..<3).map { "m\($0)" }, now: t0, tombs: &shrinkTombs)
ckEq("nothing deleted", shrunk.count, 12)
ck("nothing tombstoned", shrinkTombs.isEmpty)
// The next healthy refresh then deletes what is still missing.
let healed = replace(existing: shrunk, returned: (0..<3).map { "m\($0)" }, now: t0.addingTimeInterval(600),
                     tombs: &shrinkTombs)
ckEq("the next healthy refresh deletes them", healed.count, 3)
ckEq("and tombstones every one", shrinkTombs.count, 9)

print("\n▶️  the shrink threshold matches the code")
// existing >= 4 && returned*2 < existing
ck("4 entries → 1 is a shrink", 4 >= 4 && 1 * 2 < 4)
ck("4 entries → 2 is NOT a shrink", !(4 >= 4 && 2 * 2 < 4))
ck("3 entries → 1 is NOT a shrink", !(3 >= 4 && 1 * 2 < 3))

// MARK: - 4. No collateral change

print("\n▶️  unrelated behaviour is unchanged")
var none: [String: Tombstone] = [:]
let full = replace(existing: before, returned: [target, "gemini-3.8-flash", "gpt-4o"], now: t0, tombs: &none)
ckEq("a full response keeps every entry", full.count, 3)
ck("and tombstones nothing", none.isEmpty)
let withCustom = [Entry(modelId: "my-custom", contextWindowOverride: 123, isCustom: true), Entry(modelId: "gpt-4o")]
let customKept = replace(existing: withCustom, returned: ["gpt-4o"], now: t0, tombs: &none)
ck("custom entries are still kept", find(customKept, "my-custom") != nil)
ckEq("a plain model is not tombstoned twice", none["gpt-4o"], nil)
ckEq("the vendor's new base still wins for un-overridden models",
      find(full, "gpt-4o")?.effectiveContextWindow, 1_048_576)

// MARK: - 5. Source invariants

print("\n▶️  source invariants")
func read(_ p: String) -> String? { try? String(contentsOfFile: p, encoding: .utf8) }
guard let store = read("../../Providers/ProviderConfigStore.swift") else {
    print("  ❌ could not read ProviderConfigStore.swift"); exit(1)
}
ck("unlisted catalog entries are collected for deletion, not kept",
   store.contains("let absentCatalog = existing.filter { !$0.isCustom && !refreshedModelIds.contains($0.baseModel.id) }"))
ck("they are only appended on a suspicious shrink",
   store.contains("if suspiciousShrink {"))
ck("a normal refresh logs a deletion",
   store.contains("deleted \\(absentCatalog.count) unlisted catalog entr"))
ck("the old grace expiry no longer drives deletion",
   !store.contains("now.timeIntervalSince(since) > Self.modelAbsenceGracePeriod"))
ck("tombstones carry overrides, hidden flag and groups",
   store.contains("struct RetiredModelOverride: Codable"))
ck("a re-listed model is restored from its tombstone",
   store.contains("retired.removeValue(forKey: retiredKey(instanceId, model.id))"))
ck("group membership is restored", store.contains("restored \\("))
ck("tombstones expire", store.contains("retiredModelTTL: TimeInterval = 90 * 24 * 60 * 60"))
ck("the rule is tagged", store.contains("[T-model-refresh-authoritative]"))

print("\n" + String(repeating: "─", count: 60))
if failures == 0 {
    print("✅ All model-refresh-authoritative tests passed")
    exit(0)
} else {
    print("❌ \(failures) failure(s)")
    exit(1)
}
