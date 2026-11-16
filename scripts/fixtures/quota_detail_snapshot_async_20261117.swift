// Real production detail coordinator AND quotaRows/attach/refreshRow projection.
// Dependency gates pause R1 after capturing rows; no algorithm mock.
@main struct QuotaDetailSnapshotFixture {
    @MainActor static func until(_ label: String, _ test: () -> Bool) async {
        let limit = Date().addingTimeInterval(10)
        while Date() < limit { if test() { return }; await Task.yield() }
        fatalError(label)
    }
    static func commit(_ instance: ProviderInstance, row: String = "main", key: String = "synthetic-main") async {
        let result = await ProviderQuotaService.shared.refreshRow(for: instance, key: key, rowId: row, publishSingle: true)
        checkAsync(result.succeeded, "actual external bill did not commit")
    }
    @MainActor static func main() async {
        UIApplication.shared.applicationState = .background
        let a = ProviderInstance(id: "detail-A"), b = ProviderInstance(id: "detail-B")
        for instance in [a, b] {
            ProviderConfigStore.shared.values[instance.id] = instance
            ProviderKeychainHelper.put("synthetic-main", id: instance.id)
            ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-ring")], id: instance.id)
        }
        let loader = ProviderQuotaDetailSnapshotLoader()
        // Real Combine signal from the production publishRevision method;
        // sink invokes exactly the View's .onChange projection entry.
        let subscription = ProviderQuotaService.shared.$revision.dropFirst().sink { _ in loader.project(for: a) }
        loader.reload(for: a)
        await until("cold rows failed") { loader.snapshot.rows.count == 2 }
        checkAsync(loader.snapshot.rows.first?.info == nil, "cold info unknown")
        let service = ProviderQuotaService.shared
        let successAt = Date().addingTimeInterval(-5)
        service.consumed(.init(instanceId: a.id, rowId: "main", credentialIdentity: ProviderQuotaSuccess.identity("synthetic-main"), succeededAt: successAt))
        await until("external consumption did not commit") { service.inspect { $0.clocks[a.id]?.lastSuccessAt == successAt } }
        UIApplication.shared.applicationState = .active
        await service.runAutomatic(a.id, epoch: service.consumptionEpoch(for: a.id))
        UIApplication.shared.applicationState = .background
        await until("external automatic commit not projected") { loader.snapshot.rows.first?.info?.amountUSD == 1.10 }
        checkAsync(loader.snapshot.rows.first?.info?.highlighted == true, "fresh low balance highlighted")
        FixtureThreshold.shared.set(0.5)
        loader.project(for: a) // same method used by actual AppStorage onChange
        await until("threshold decrease did not reproject") { loader.snapshot.rows.first?.info?.highlighted == false }
        FixtureThreshold.shared.set(3)
        loader.project(for: a)
        await until("threshold increase did not reproject") { loader.snapshot.rows.first?.info?.highlighted == true }

        // Hold a real old reload R1 after rows were captured. R2 is a manual
        // refresh on the SAME instance. R1's old threshold cannot overwrite R2.
        let r1 = FixtureReadGate()
        ProviderMultiKeyManager.shared.pauseProjectionUsage(id: a.id, at: r1)
        loader.reload(for: a)
        await r1.waitForArrival()
        FixtureThreshold.shared.set(0.5)
        loader.refresh(for: a, multi: false)
        await until("manual R2 failed") { !loader.refreshing && loader.snapshot.rows.first?.info?.highlighted == false && loader.message != nil }
        r1.release()
        await until("R1 worker did not finish") { loader.projectionTask == nil }
        checkAsync(loader.snapshot.rows.first?.info?.highlighted == false, "delayed R1 must never replace R2")
        checkAsync(loader.message == "已更新余额", "manual result message belongs to R2")

        // Revision storms occupy ONE reader plus ONE replaceable pending slot.
        let storm = FixtureReadGate()
        ProviderMultiKeyManager.shared.pauseProjectionUsage(id: a.id, at: storm)
        loader.project(for: a)
        await storm.waitForArrival()
        FixtureThreshold.shared.set(3)
        for _ in 0..<200 { loader.project(for: a) }
        checkAsync(loader.pending != nil && loader.projectionTask != nil, "bounded pending worker exists")
        storm.release()
        await until("latest coalesced projection failed") { loader.projectionTask == nil && loader.snapshot.rows.first?.info?.highlighted == true }
        let owner = fixtureOwner(a, row: "main", key: "synthetic-main")
        let count = await FixturePlan.shared.count(owner)
        checkAsync(count == 2, "revision/threshold events never query: external commit plus manual only")

        let cancelGate = FixtureReadGate()
        ProviderMultiKeyManager.shared.pauseProjectionUsage(id: a.id, at: cancelGate)
        loader.project(for: a)
        await cancelGate.waitForArrival()
        loader.cancel(); cancelGate.release()
        await until("cancel reader did not drain") { loader.projectionTask == nil }
        checkAsync(loader.snapshot.rows.isEmpty && loader.message == nil, "cancel rejects delayed same-instance result")

        await commit(b, row: "ring", key: "synthetic-ring")
        loader.reload(for: a)
        await until("A reload failed") { loader.projectionTask == nil }
        let switchGate = FixtureReadGate()
        ProviderMultiKeyManager.shared.pauseProjectionUsage(id: a.id, at: switchGate)
        loader.project(for: a)
        await switchGate.waitForArrival()
        loader.reload(for: b)
        switchGate.release()
        await until("instance B projection failed") { loader.projectionTask == nil && loader.snapshot.rows.last?.info?.amountUSD == 2.31 }
        checkAsync(loader.instanceId == b.id && loader.snapshot.rows.first?.info == nil, "instance switch cannot install old A rows")

        // Manual query delayed at collect, then config changed / view cancelled.
        let manualGate = FixtureGate()
        await FixturePlan.shared.pauseCollect("main", at: manualGate)
        loader.refresh(for: b, multi: false)
        await manualGate.waitForArrival()
        var changed = b; changed.label = "edited"
        loader.reload(for: changed)
        await manualGate.release()
        await until("config reload projection/manual did not drain") { loader.projectionTask == nil && loader.manualTask == nil }
        checkAsync(!loader.refreshing && loader.message == nil, "late manual cannot publish across config scope")
        let cancelledManual = FixtureGate()
        await FixturePlan.shared.pauseCollect("main", at: cancelledManual)
        loader.refresh(for: changed, multi: false)
        await cancelledManual.waitForArrival()
        loader.cancel(); await cancelledManual.release()
        // Wait for the production ticket to drain, not an arbitrary sleep.
        await until("cancelled query ticket/worker leaked") { loader.manualTask == nil && ProviderQuotaService.shared.inspect { $0.inFlight[b.id + "|main"] == nil } }
        checkAsync(loader.snapshot.rows.isEmpty && loader.message == nil && !loader.refreshing, "cancelled manual does not old-write UI")
        subscription.cancel()
        print("quota-detail-snapshot-ok")
    }
}
