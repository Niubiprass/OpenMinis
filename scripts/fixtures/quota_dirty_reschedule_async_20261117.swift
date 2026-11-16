// Real production invalidate/warm/resolve/schedule/run/refresh methods; no network.
@main struct QuotaDirtyRescheduleFixture {
    static func until(_ label: String, _ test: () -> Bool) async {
        let limit = Date().addingTimeInterval(10)
        while Date() < limit { if test() { return }; await Task.yield() }
        fatalError(label)
    }
    static func seed(_ id: String) async -> CacheAsyncHarness {
        await MainActor.run { ProviderConfigStore.shared.values[id] = ProviderInstance(id: id) }
        ProviderKeychainHelper.put("synthetic-main", id: id)
        ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-ring")], id: id)
        let service = CacheAsyncHarness()
        _ = await service.refreshRow(for: ProviderInstance(id: id), key: "synthetic-main", rowId: "main", publishSingle: true)
        service.consumed(.init(instanceId: id, rowId: "main", credentialIdentity: ProviderQuotaSuccess.identity("synthetic-main"), succeededAt: Date()))
        await until("consumption did not really schedule") { service.inspect { $0.scheduled[id] != nil && $0.clocks[id]?.dirty == true } }
        await service.flushWriter()
        return service
    }
    static func main() async {
        await MainActor.run { UIApplication.shared.applicationState = .active }
        for id in ["non-current-failure", "label-only"] {
            let service = await seed(id)
            let oldEpoch = service.inspect { $0.epochs[id]! }
            let owner = fixtureOwner(ProviderInstance(id: id), row: "main", key: "synthetic-main")
            if id == "non-current-failure" {
                // Production failure notification invalidates the instance;
                // failing B changes its status but current A remains valid.
                ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-ring", status: .disabled)], id: id)
                service.invalidate(instanceId: id)
            } else {
                await MainActor.run { ProviderConfigStore.shared.values[id]?.label = "edited-label" }
                service.invalidateAll() // config publisher's actual service path
            }
            checkAsync(service.inspect { $0.epochs[id] != oldEpoch }, "old scheduled epoch retired")
            await until("valid dirty owner stranded after scheduled cancellation") {
                service.inspect { $0.clocks[id]?.dirty == false && $0.clocks[id]?.running == false && $0.cache[id]?.info?.isStale == false }
            }
            let count = await FixturePlan.shared.count(owner)
            checkAsync(count == 2, "exactly seed plus ONE resumed real query")
            for _ in 0..<100 { _ = service.cachedQuota(instanceId: id) }
            await service.scheduleAutomatic(id)
            let after = await FixturePlan.shared.count(owner)
            checkAsync(after == 2 && service.inspect { $0.scheduled[id] == nil }, "revision/warm does not restart clean query")
            service.suspendAutomaticRefresh()
        }
        // Old durable main pointer exists, but latest successful ring pointer
        // is queued behind a blocked writer. Invalidation must revalidate ring,
        // NOT roll the representative back to the older disk/main account.
        for id in ["pending-ring-single", "pending-ring-all"] {
            let service = await seed(id), blocked = StorageGate()
            await service.scheduleAutomatic(id) // leave the initial delayed slot
            service.writer.async { blocked.pause() }
            await blocked.waitForArrival()
            let successAt = Date()
            service.consumed(.init(instanceId: id, rowId: "ring", credentialIdentity: ProviderQuotaSuccess.identity("synthetic-ring"), succeededAt: successAt))
            await until("ring consumption did not own selection") { service.inspect { $0.currentOrigins[id]?.rowId == "ring" && $0.clocks[id]?.lastSuccessAt == successAt } }
            if id == "pending-ring-all" { service.invalidateAll() }
            else { service.invalidate(instanceId: id) }
            await until("pending ring owner was not resumed") { service.inspect { $0.clocks[id]?.dirty == false && $0.clocks[id]?.running == false } }
            checkAsync(service.inspect { $0.currentOrigins[id]?.rowId == "ring" && $0.cache[id]?.origin?.rowId == "ring" }, "pending latest representative preserved after revalidation")
            let ringCalls = await FixturePlan.shared.count(fixtureOwner(ProviderInstance(id: id), row: "ring", key: "synthetic-ring"))
            let mainCalls = await FixturePlan.shared.count(fixtureOwner(ProviderInstance(id: id), row: "main", key: "synthetic-main"))
            checkAsync(ringCalls == 1 && mainCalls == 1, "one resumed ring query, never older disk main query")
            blocked.release(); await service.flushWriter(); service.suspendAutomaticRefresh()
        }
        let background = await seed("background-invalidated")
        let bgOwner = fixtureOwner(ProviderInstance(id: "background-invalidated"), row: "main", key: "synthetic-main")
        await MainActor.run { UIApplication.shared.applicationState = .background }
        background.invalidate(instanceId: "background-invalidated")
        await until("background owner was not revalidated") { background.inspect { $0.currentOrigins["background-invalidated"] != nil && !$0.validating.contains("background-invalidated") } }
        await background.scheduleAutomatic("background-invalidated")
        let bgCount = await FixturePlan.shared.count(bgOwner)
        checkAsync(bgCount == 1 && background.inspect { $0.scheduled["background-invalidated"] == nil && $0.clocks["background-invalidated"]?.dirty == true }, "background must not query; dirty retained")
        await MainActor.run {
            UIApplication.shared.applicationState = .active
            background.refreshAllIfNeeded(instances: [ProviderInstance(id: "background-invalidated")])
        }
        await until("foreground did not resume dirty once") { background.inspect { $0.clocks["background-invalidated"]?.dirty == false && $0.clocks["background-invalidated"]?.running == false } }
        let resumedCount = await FixturePlan.shared.count(bgOwner)
        checkAsync(resumedCount == 2, "one foreground retry")
        background.suspendAutomaticRefresh()

        let invalid = await seed("invalid-owner")
        ProviderKeychainHelper.put("", id: "invalid-owner")
        invalid.invalidate(instanceId: "invalid-owner")
        await until("invalid credential resolution did not complete") { invalid.inspect { !$0.validating.contains("invalid-owner") } }
        checkAsync(invalid.inspect { $0.currentOrigins["invalid-owner"] == nil && $0.scheduled["invalid-owner"] == nil }, "no restart for invalid owner")
        let oldEpoch = invalid.inspect { $0.epochs["invalid-owner"]! }
        invalid.invalidate(instanceId: "invalid-owner")
        await invalid.scheduleAutomatic("invalid-owner", expectedEpoch: oldEpoch)
        checkAsync(invalid.inspect { $0.scheduled["invalid-owner"] == nil }, "stale epoch cannot schedule")
        invalid.setup { $0.clocks["invalid-owner"]?.running = true }
        await invalid.scheduleAutomatic("invalid-owner")
        checkAsync(invalid.inspect { $0.scheduled["invalid-owner"] == nil }, "running query cannot be restarted")

        // Foreground changes while context awaits, without relying on observer
        // cancellation: runAutomatic itself must recheck before any collect.
        let late = CacheAsyncHarness(), gate = FixtureGate(), id = "late-background"
        await MainActor.run { ProviderConfigStore.shared.values[id] = ProviderInstance(id: id) }
        ProviderKeychainHelper.put("synthetic-main", id: id)
        await FixturePlan.shared.pauseContext("main", at: gate)
        await MainActor.run { late.refreshAllIfNeeded(instances: [ProviderInstance(id: id)]) }
        await gate.waitForArrival()
        await MainActor.run { UIApplication.shared.applicationState = .background }
        await gate.release()
        await until("late background resolver remained stuck") { late.inspect { $0.currentOrigins[id] != nil } }
        let lateCount = await FixturePlan.shared.count(fixtureOwner(ProviderInstance(id: id), row: "main", key: "synthetic-main"))
        checkAsync(lateCount == 0, "no query after background during resolve")
        late.suspendAutomaticRefresh()
        print("quota-dirty-reschedule-ok")
    }
}
