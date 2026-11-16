// Runs extracted production policy, cache persistence and representative selection.
func check(_ value: @autoclosure () -> Bool, _ label: String) {
    if !value() { fatalError(label) }
}
typealias Policy = ProviderQuotaCurrentKeyPolicy
let main = Policy.Origin(rowId: "main", owner: "synthetic-main-owner")
let low = Policy.Origin(rowId: "ring-low", owner: "synthetic-low-owner")
let healthy = Policy.Origin(rowId: "ring-good", owner: "synthetic-good-owner")
let replaced = Policy.Origin(rowId: "ring-good", owner: "synthetic-new-credential")
check(Policy.current(lastSuccess: nil, available: [low, healthy, main]) == main, "default main, never lowest")
check(Policy.current(lastSuccess: healthy, available: [low, healthy, main]) == healthy, "last actual success")
check(Policy.current(lastSuccess: healthy, available: [low, main]) == main, "deleted/disabled ring fallback main")
check(Policy.current(lastSuccess: healthy, available: [low, replaced, main]) == main, "same row new owner fallback main")
check(Policy.current(lastSuccess: nil, available: [low]) == nil, "missing main stays unknown, not arbitrary sibling")
check(!Policy.canRestore(healthy, current: replaced), "old credential cache rejected")
check(Policy.current(lastSuccess: main, available: [main]) == main, "single-main ordinary path")
check(Policy.mayCommitResolution(captured: main, current: main, capturedSuccessAt: nil, currentSuccessAt: nil), "stable resolution commits")
check(!Policy.mayCommitResolution(captured: main, current: healthy, capturedSuccessAt: nil, currentSuccessAt: nil), "new successful row fences old lookup")
let successTime = Date(timeIntervalSince1970: 1_700_000_000)
check(!Policy.mayCommitResolution(captured: main, current: main, capturedSuccessAt: nil, currentSuccessAt: successTime), "same row newer consumption fences old lookup")

let now = Date(timeIntervalSince1970: 1_700_000_000)
var clock = Policy.RefreshClock()
clock.dirty = true
check(clock.deadline(active: true, now: now) == now, "foreground TTL without prior consumption actually becomes due")
clock.consumed(at: now)
clock.consumed(at: now.addingTimeInterval(1))
check(clock.deadline(active: true, now: now) == now.addingTimeInterval(3), "latest burst debounce two seconds")
check(clock.deadline(active: false, now: now) == nil && clock.dirty, "background no query, retain dirty")
clock.begin(at: now.addingTimeInterval(3))
clock.consumed(at: now.addingTimeInterval(4))
check(clock.deadline(active: true, now: now) == nil, "inflight no restart")
clock.finish(at: now.addingTimeInterval(5), succeeded: true)
check(clock.deadline(active: true, now: now.addingTimeInterval(5)) == now.addingTimeInterval(33), "pending latest success survives per-instance throttle")
clock.begin(at: now.addingTimeInterval(33))
clock.finish(at: now.addingTimeInterval(34), succeeded: false, retryAfter: 120)
clock.consumed(at: now.addingTimeInterval(35))
check(clock.deadline(active: true, now: now) == now.addingTimeInterval(154), "429 Retry-After respected")
clock.begin(at: now.addingTimeInterval(154)); clock.cancelled()
check(clock.dirty && !clock.running, "cancel retains pending")
check(clock.deadline(active: false, now: now) == nil, "background resume gate")
check(clock.deadline(active: true, now: now.addingTimeInterval(155)) == now.addingTimeInterval(184), "foreground resume preserves cooldown")
check(Policy.retryAfter("999999", at: now) == 900, "Retry-After bounded")
check(Policy.retryAfter("-2", at: now) == 30, "negative delay bounded")
check(Policy.retryAfter("not-a-date", at: now) == nil, "malformed header unknown")

let service = CacheHarness()
func put(_ origin: Policy.Origin, amount: Double) {
    let info = CacheHarness.QuotaInfo(displayText: "Key 额度 $\(amount)", highlighted: false,
        kind: .balance, balanceUSD: amount, amountUSD: amount, observedAt: now, owner: origin.owner)
    service.rowOrigins["fixture", default: [:]][origin.rowId] = origin
    service.selectableOrigins["fixture", default: [:]][origin.rowId] = origin
    service.keyCache["fixture", default: [:]][origin.rowId] = .init(info: info, fetchedAt: now, owner: origin.owner, origin: origin)
    CacheHarness.store(info, instanceId: "fixture", origin: origin, at: now)
}
put(low, amount: -0.01); put(main, amount: 1.10); put(healthy, amount: 2.31)
check(service.publishAggregate(for: "fixture")?.amountUSD == 1.10, "real production representative is main not min")
service.currentOrigins["fixture"] = healthy
check(service.publishAggregate(for: "fixture")?.amountUSD == 2.31, "real production last successful ring")
// Query failure/parking never calls consumed and does not change current origin.
check(service.publishAggregate(for: "fixture")?.amountUSD == 2.31, "failed sibling cannot take active")
service.keyCache["fixture"]?[healthy.rowId] = nil
check(service.publishAggregate(for: "fixture") == nil, "unread current row stays unknown, no sibling substitute")
service.rowOrigins["fixture"]?[healthy.rowId] = nil
service.selectableOrigins["fixture"]?[healthy.rowId] = nil
check(service.publishAggregate(for: "fixture")?.amountUSD == 1.10, "real deleted-row fallback main")
let loaded = CacheHarness.storedInfo(instanceId: "fixture", origin: healthy, processOwner: "new-process")
check(loaded?.info.amountUSD == 2.31 && loaded?.info.isStale == true, "row-scoped reload retains honest last-known")
check(loaded?.info.observedAt == now, "reload observation not refresh timestamp")
check(CacheHarness.storedInfo(instanceId: "fixture", origin: replaced, processOwner: "new-process") == nil, "same-row changed credential cannot reload old balance")
let currentData = try! JSONEncoder().encode(healthy)
UserDefaults.standard.set(currentData, forKey: CacheHarness.currentPrefix + "fixture")
check(CacheHarness.storedCurrent("fixture") == healthy, "last successful row persists, never lowest")
for row in [main, low, healthy] { CacheHarness.store(nil, instanceId: "fixture", origin: row, at: now) }
UserDefaults.standard.removeObject(forKey: CacheHarness.currentPrefix + "fixture")
print("quota-current-key-ok")
