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
// count is irrelevant: 12 models may become 2 today and 20 tomorrow. Only a
// failed or unfinished request keeps the old list.
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

/// Mirrors replaceEntries: the returned ids are the list. No count heuristic.
func replace(existing: [Entry], returned: [String], now: Date = Date(),
             tombs: inout [String: Tombstone], newBase: Int = 1_048_576) -> [Entry] {
    let returnedSet = Set(returned)
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

// MARK: - 3. Count changes are not a signal

print("\n▶️  a big drop is applied at once, not deferred")
var shrinkTombs: [String: Tombstone] = [:]
let big = (0..<12).map { Entry(modelId: "m\($0)") }
let shrunk = replace(existing: big, returned: (0..<3).map { "m\($0)" }, now: t0, tombs: &shrinkTombs)
ckEq("only the returned rows remain", shrunk.count, 3)
ckEq("every dropped model is tombstoned", shrinkTombs.count, 9)
// The old rule needed a second refresh; this one must not.
ckEq("nothing is carried over", find(shrunk, "m11"), nil)

print("\n▶️  a full empty response empties the list")
var emptyTombs: [String: Tombstone] = [:]
let emptied = replace(existing: big, returned: [], now: t0, tombs: &emptyTombs)
ckEq("list is empty", emptied.count, 0)
ckEq("all twelve are tombstoned", emptyTombs.count, 12)

print("\n▶️  a later full list brings all of them back")
var backTombs = emptyTombs
let returnedAll = replace(existing: emptied, returned: big.map { $0.modelId }, now: t0.addingTimeInterval(60), tombs: &backTombs)
ckEq("all twelve return", returnedAll.count, 12)
ck("tombstones consumed", backTombs.isEmpty)

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
ck("no count heuristic remains", !store.contains("suspiciousShrink"))
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
ck("a successful response replaces even when empty", store.contains("return ModelFetchResult(models: models, source: \"api\""))
ck("pagination must finish before replacement",
   ["OpenAI/OpenAIModelsAPI.swift", "Anthropic/AnthropicModelsAPI.swift", "Gemini/GeminiModelsAPI.swift"].allSatisfy { rel in
       (read("../../Providers/" + rel) ?? "").contains("ModelPagination.collect")
   })

print("\n" + String(repeating: "─", count: 60))
if failures == 0 {
    print("✅ All model-refresh-authoritative tests passed")
    exit(0)
} else {
    print("❌ \(failures) failure(s)")
    exit(1)
}
