// Compiled with -parse-as-library on macOS. Every async service method below
// is production extraction; all keys/owners/amounts are synthetic, no network.
@main struct QuotaAsyncFixture {
    static func waitForSuccess(_ service: CacheAsyncHarness, id: String = "race", at date: Date) async {
        let limit = Date().addingTimeInterval(3)
        while Date() < limit {
            if service.inspect({ $0.clocks[id]?.lastSuccessAt }) == date { return }
            await Task.yield()
        }
        fatalError("synthetic success did not complete")
    }
    static func main() async {
        await MainActor.run {
            for id in ["race", "manual", "busy", "owner-race"] { ProviderConfigStore.shared.values[id] = ProviderInstance(id: id) }
        }
        for id in ["race", "manual", "busy", "owner-race"] {
            ProviderKeychainHelper.put("synthetic-main", id: id)
            ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-ring")], id: id)
        }
        let race = CacheAsyncHarness()
        let instance = ProviderInstance(id: "race")
        _ = await race.refreshRow(for: instance, key: "synthetic-main", rowId: "main", publishSingle: true)
        let epoch = race.inspect { $0.epochs["race"]! }
        let gate = FixtureGate()
        await FixturePlan.shared.pauseContext("main", at: gate)
        let oldLookup = Task { await race.resolveCurrent("race", epoch: epoch) }
        await gate.waitForArrival()
        let succeededAt = Date()
        race.consumed(.init(instanceId: "race", rowId: "ring",
            credentialIdentity: ProviderQuotaSuccess.identity("synthetic-ring"), succeededAt: succeededAt))
        await waitForSuccess(race, at: succeededAt)
        await gate.release()
        let oldResult = await oldLookup.value
        checkAsync(oldResult == nil, "old resolver rejected after newer successful ring")
        checkAsync(race.inspect { $0.currentOrigins["race"]?.rowId } == "ring", "new success not overwritten")
        checkAsync(race.inspect { $0.clocks["race"]?.dirty } == true, "new consumption remains pending")
        checkAsync(race.inspect { $0.scheduledCount["race"] ?? 0 } >= 2, "lookup rejection preserves convergence")

        let manual = CacheAsyncHarness(), manualInstance = ProviderInstance(id: "manual")
        ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-ring", isEnabled: false, status: .disabled)], id: "manual")
        let mainGate = FixtureGate(), disabledGate = FixtureGate()
        await FixturePlan.shared.pauseCollect("main", at: mainGate)
        await FixturePlan.shared.pauseCollect("ring", at: disabledGate)
        let mainTask = Task { await manual.refreshRow(for: manualInstance, key: "synthetic-main", rowId: "main", publishSingle: false) }
        let disabledTask = Task { await manual.refreshRow(for: manualInstance, key: "synthetic-ring", rowId: "ring", publishSingle: false) }
        await mainGate.waitForArrival(); await disabledGate.waitForArrival()
        let manualEpoch = manual.inspect { $0.epochs["manual"]! }
        await disabledGate.release()
        let disabledResult = await disabledTask.value
        checkAsync(disabledResult.succeeded, "disabled row manually inspected without invalidating instance")
        checkAsync(manual.inspect { $0.inFlight["manual|main"] != nil }, "sibling ticket preserved")
        checkAsync(manual.inspect { $0.epochs["manual"] } == manualEpoch, "disabled row cannot bump sibling epoch")
        checkAsync(manual.inspect { $0.selectableOrigins["manual"]?["ring"] } == nil, "disabled row never selectable")
        checkAsync(manual.publishAggregate(for: "manual") == nil, "disabled result does not become representative")
        let replacementGate = FixtureGate()
        await FixturePlan.shared.pauseCollect("ring", at: replacementGate)
        let stale = Task { await manual.refreshRow(for: manualInstance, key: "synthetic-ring", rowId: "ring", publishSingle: false) }
        await replacementGate.waitForArrival()
        ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-replaced", isEnabled: false, status: .disabled)], id: "manual")
        await replacementGate.release()
        let staleResult = await stale.value
        checkAsync(!staleResult.succeeded, "old row credential discarded")
        checkAsync(manual.inspect { $0.inFlight["manual|main"] != nil }, "single-row owner change preserves sibling")
        checkAsync(manual.inspect { $0.epochs["manual"] } == manualEpoch, "row cleanup cannot invalidate whole instance")
        await mainGate.release()
        let mainResult = await mainTask.value
        checkAsync(mainResult.succeeded && manual.publishAggregate(for: "manual")?.amountUSD == 1.10, "ordinary main survives disabled/manual races")

        let ownerRace = CacheAsyncHarness(), ownerInstance = ProviderInstance(id: "owner-race")
        _ = await ownerRace.refreshRow(for: ownerInstance, key: "synthetic-main", rowId: "main", publishSingle: true)
        _ = await ownerRace.refreshRow(for: ownerInstance, key: "synthetic-ring", rowId: "ring", publishSingle: false)
        let ownerEpoch = ownerRace.inspect { $0.epochs["owner-race"]! }
        let ownerGate = FixtureGate()
        await FixturePlan.shared.pauseCollect("ring", at: ownerGate)
        let oldOwnerQuery = Task { await ownerRace.refreshRow(for: ownerInstance, key: "synthetic-ring", rowId: "ring", publishSingle: false) }
        await ownerGate.waitForArrival()
        ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-new-owner")], id: "owner-race")
        let newSuccessAt = Date()
        ownerRace.consumed(.init(instanceId: "owner-race", rowId: "ring",
            credentialIdentity: ProviderQuotaSuccess.identity("synthetic-new-owner"), succeededAt: newSuccessAt))
        await waitForSuccess(ownerRace, id: "owner-race", at: newSuccessAt)
        let newOrigin = ownerRace.inspect { $0.currentOrigins["owner-race"]! }
        await ownerGate.release(); _ = await oldOwnerQuery.value
        checkAsync(ownerRace.inspect { $0.currentOrigins["owner-race"] } == newOrigin, "old owner failure cannot retire newer successful row")
        checkAsync(ownerRace.inspect { $0.rowOrigins["owner-race"]?["ring"] } == newOrigin, "new row identity survives stale invalidation")
        checkAsync(CacheAsyncHarness.storedCurrent("owner-race") == newOrigin, "old owner cannot erase durable new-success pointer")
        checkAsync(ownerRace.inspect { $0.inFlight["owner-race|ring"] } == nil, "old ticket still drained without retaining stale slot")
        checkAsync(ownerRace.inspect { $0.epochs["owner-race"] } == ownerEpoch, "same-epoch race really exercised")

        let busy = CacheAsyncHarness(), busyInstance = ProviderInstance(id: "busy")
        _ = await busy.refreshRow(for: busyInstance, key: "synthetic-main", rowId: "main", publishSingle: true)
        let busyEpoch = busy.inspect { $0.epochs["busy"]! }
        let inFlightGate = FixtureGate()
        await FixturePlan.shared.pauseCollect("main", at: inFlightGate)
        let heldQuery = Task { await busy.refreshRow(for: busyInstance, key: "synthetic-main", rowId: "main", publishSingle: false) }
        await inFlightGate.waitForArrival()
        busy.setup { $0.clocks["busy", default: .init()].consumed(at: Date().addingTimeInterval(-5)) }
        await busy.runAutomatic("busy", epoch: busyEpoch)
        let deferred = busy.inspect { $0.clocks["busy"]! }
        checkAsync(deferred.dirty && !deferred.running && deferred.failures == 0, "manual in-flight deferral retains dirty without failure")
        checkAsync(deferred.deadline(active: true, now: Date())! > Date().addingTimeInterval(25), "deferred retry obeys thirty-second floor")
        checkAsync(busy.inspect { $0.scheduledCount["busy"] ?? 0 } == 1, "deferred auto attempt schedules pending work")
        await inFlightGate.release(); _ = await heldQuery.value
        busy.setup { $0.clocks["busy"]?.lastAttemptAt = Date().addingTimeInterval(-40) }
        await busy.runAutomatic("busy", epoch: busyEpoch)
        checkAsync(busy.inspect { $0.clocks["busy"]?.dirty } == false, "real automatic query consumes retained work")
        checkAsync(busy.publishAggregate(for: "busy")?.amountUSD == 1.10, "actual fresh bill rather than local budget arithmetic")
        print("quota-current-key-async-ok")
    }
}
