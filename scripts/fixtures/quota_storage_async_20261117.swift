// Real production commit/enqueue/writer/restore/TTL/cancel paths, synthetic IO.
// No queue sync/flush exists in production. Gates have bounded process failure.
@main struct QuotaStorageFixture {
    final class Probe: @unchecked Sendable {
        let lock = NSLock(); var finished = false
        func complete() { lock.lock(); finished = true; lock.unlock() }
        func isFinished() -> Bool { lock.lock(); defer { lock.unlock() }; return finished }
    }
    static func mainProbe(_ service: CacheAsyncHarness, id: String, expectedUSD: Double? = nil) async {
        let probe = Probe()
        DispatchQueue.global().asyncAfter(deadline: .now() + 2) {
            if !probe.isFinished() { fatalError("UI cachedQuota/failureNote blocked by storage") }
        }
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            DispatchQueue.main.async {
                let visible = service.cachedQuota(instanceId: id)
                if let expectedUSD { checkAsync(visible?.amountUSD == expectedUSD, "non-nil UI snapshot projected while writer blocked") }
                _ = service.cachedQuota(instanceId: "unrelated")
                service.noteFailure("synthetic", instanceId: id)
                checkAsync(service.failureNote(instanceId: id) == "synthetic", "failure snapshot")
                service.clearFailure(instanceId: id)
                probe.complete(); continuation.resume()
            }
        }
    }
    static func until(_ label: String, _ predicate: () -> Bool) async {
        let deadline = Date().addingTimeInterval(10)
        while Date() < deadline { if predicate() { return }; await Task.yield() }
        fatalError(label)
    }
    static func success(_ service: CacheAsyncHarness, id: String, row: String, key: String) async {
        let date = Date()
        service.consumed(.init(instanceId: id, rowId: row,
            credentialIdentity: ProviderQuotaSuccess.identity(key), succeededAt: date))
        await until("success memory commit blocked") { service.inspect { $0.clocks[id]?.lastSuccessAt == date } }
    }
    static func query(_ service: CacheAsyncHarness, id: String, row: String = "main", key: String = "synthetic-main") async {
        let result = await service.refreshRow(for: ProviderInstance(id: id), key: key, rowId: row, publishSingle: true)
        checkAsync(result.succeeded, "real synthetic bill commit")
    }
    static func main() async {
        let ids = ["save", "pointer", "remove", "epoch", "sibling", "cold", "cancel", "all", "nil-row"]
        await MainActor.run {
            UIApplication.shared.applicationState = .background
            for id in ids { ProviderConfigStore.shared.values[id] = ProviderInstance(id: id) }
        }
        for id in ids {
            ProviderKeychainHelper.put("synthetic-main", id: id)
            ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-ring")], id: id)
        }
        let save = CacheAsyncHarness()
        let observer = NotificationCenter.default.addObserver(
            forName: Foundation.UserDefaults.didChangeNotification, object: UserDefaults.standard.suite, queue: .main) { _ in
                _ = save.cachedQuota(instanceId: "save")
                _ = save.failureNote(instanceId: "save")
            }
        let saveGate = StorageGate()
        UserDefaults.standard.arm("set", key: CacheAsyncHarness.storedPrefix + "save.main", gate: saveGate)
        let heldSave = Task { await query(save, id: "save") }
        await saveGate.waitForArrival()
        await mainProbe(save, id: "save", expectedUSD: 1.10) // BEFORE joining writer/producer: old lock mutant must fail here
        await heldSave.value
        checkAsync(save.cachedQuota(instanceId: "save")?.amountUSD == 1.10, "memory visible before storage")
        await success(save, id: "save", row: "ring", key: "synthetic-ring")
        ProviderMultiKeyManager.shared.put([.init(id: "ring", key: "synthetic-new")], id: "save")
        await success(save, id: "save", row: "ring", key: "synthetic-new")
        await query(save, id: "save", row: "ring", key: "synthetic-new")
        await mainProbe(save, id: "save")
        let newest = save.inspect { $0.currentOrigins["save"]! }
        saveGate.release(); await save.flushWriter()
        checkAsync(CacheAsyncHarness.storedCurrent("save") == newest, "FIFO latest owner pointer")
        checkAsync(CacheAsyncHarness.storedInfo(instanceId: "save", origin: newest, processOwner: newest.owner)?.info.amountUSD == 2.31, "latest row converges")
        NotificationCenter.default.removeObserver(observer)

        let pointer = CacheAsyncHarness(); await query(pointer, id: "pointer"); await pointer.flushWriter()
        let pointerGate = StorageGate()
        UserDefaults.standard.arm("set", key: CacheAsyncHarness.currentPrefix + "pointer", gate: pointerGate)
        await success(pointer, id: "pointer", row: "main", key: "synthetic-main")
        await pointerGate.waitForArrival(); await mainProbe(pointer, id: "pointer")
        await success(pointer, id: "pointer", row: "ring", key: "synthetic-ring")
        let latestPointer = pointer.inspect { $0.currentOrigins["pointer"]! }
        pointerGate.release(); await pointer.flushWriter()
        checkAsync(CacheAsyncHarness.storedCurrent("pointer") == latestPointer, "blocked current write cannot win over successor")

        let remove = CacheAsyncHarness(); await query(remove, id: "remove"); await remove.flushWriter()
        let collectGate = FixtureGate(), removeGate = StorageGate()
        await FixturePlan.shared.pauseCollect("main", at: collectGate)
        let oldQuery = Task { await remove.refreshRow(for: ProviderInstance(id: "remove"), key: "synthetic-main", rowId: "main", publishSingle: true) }
        await collectGate.waitForArrival()
        UserDefaults.standard.arm("remove", key: CacheAsyncHarness.storedPrefix + "remove.main", gate: removeGate)
        ProviderKeychainHelper.put("synthetic-replaced", id: "remove")
        await collectGate.release(); await removeGate.waitForArrival()
        await mainProbe(remove, id: "remove"); _ = await oldQuery.value
        await success(remove, id: "remove", row: "main", key: "synthetic-replaced")
        await query(remove, id: "remove", key: "synthetic-replaced")
        let removeOrigin = remove.inspect { $0.currentOrigins["remove"]! }
        removeGate.release(); await remove.flushWriter()
        checkAsync(CacheAsyncHarness.storedCurrent("remove") == removeOrigin, "old delete cannot erase new pointer")
        checkAsync(CacheAsyncHarness.storedInfo(instanceId: "remove", origin: removeOrigin, processOwner: removeOrigin.owner) != nil, "old delete then new save converges")

        let nilSeed = CacheAsyncHarness(); await query(nilSeed, id: "nil-row"); await nilSeed.flushWriter()
        let nilRow = CacheAsyncHarness(), nilGate = StorageGate()
        await FixturePlan.shared.emptyNextCollect("main")
        UserDefaults.standard.arm("remove", key: CacheAsyncHarness.storedPrefix + "nil-row.main", gate: nilGate)
        let nilAttempt = Task { await nilRow.refreshRow(for: ProviderInstance(id: "nil-row"), key: "synthetic-main", rowId: "main", publishSingle: true) }
        await nilGate.waitForArrival(); await mainProbe(nilRow, id: "nil-row")
        _ = await nilAttempt.value
        await success(nilRow, id: "nil-row", row: "main", key: "synthetic-main")
        await query(nilRow, id: "nil-row")
        await mainProbe(nilRow, id: "nil-row", expectedUSD: 1.10)
        let nilLatest = nilRow.inspect { $0.currentOrigins["nil-row"]! }
        nilGate.release(); await nilRow.flushWriter()
        checkAsync(CacheAsyncHarness.storedCurrent("nil-row") == nilLatest && CacheAsyncHarness.storedInfo(instanceId: "nil-row", origin: nilLatest, processOwner: nilLatest.owner) != nil, "row(nil) delete cannot overtake later current/row save")

        let epochService = CacheAsyncHarness()
        await query(epochService, id: "sibling", row: "ring", key: "synthetic-ring")
        await epochService.flushWriter()
        let siblingOrigin = epochService.inspect { $0.rowOrigins["sibling"]!["ring"]! }
        let epochGate = StorageGate()
        UserDefaults.standard.arm("set", key: CacheAsyncHarness.storedPrefix + "epoch.main", gate: epochGate)
        let oldSave = Task { await query(epochService, id: "epoch") }
        await epochGate.waitForArrival(); await oldSave.value
        await success(epochService, id: "epoch", row: "ring", key: "synthetic-ring") // queued pointer superseded by reset
        epochService.invalidate(instanceId: "epoch")
        await mainProbe(epochService, id: "epoch")
        await query(epochService, id: "epoch")
        epochGate.release(); await epochService.flushWriter()
        checkAsync(CacheAsyncHarness.storedCurrent("epoch") == nil, "reset cannot replay queued old pointer")
        checkAsync(UserDefaults.standard.data(forKey: CacheAsyncHarness.storedPrefix + "epoch.ring") == nil, "old epoch rows absent")
        checkAsync(CacheAsyncHarness.storedInfo(instanceId: "sibling", origin: siblingOrigin, processOwner: siblingOrigin.owner) != nil, "instance reset preserves sibling records")
        let mainOrigin = epochService.inspect { $0.rowOrigins["epoch"]!["main"]! }
        checkAsync(CacheAsyncHarness.storedInfo(instanceId: "epoch", origin: mainOrigin, processOwner: mainOrigin.owner) != nil, "new epoch row survives tombstone")

        let all = CacheAsyncHarness(), allGate = StorageGate()
        await query(all, id: "all", row: "ring", key: "synthetic-ring")
        await success(all, id: "all", row: "ring", key: "synthetic-ring")
        await all.flushWriter()
        let durableAll = all.inspect { $0.currentOrigins["all"]! }
        UserDefaults.standard.arm("set", key: CacheAsyncHarness.storedPrefix + "all.main", gate: allGate)
        let allSave = Task { await query(all, id: "all") }
        await allGate.waitForArrival(); await allSave.value
        await success(all, id: "all", row: "main", key: "synthetic-main")
        let pendingMain = all.inspect { $0.currentOrigins["all"]! }
        all.invalidateAll()
        await mainProbe(all, id: "all")
        allGate.release(); await all.flushWriter()
        checkAsync(UserDefaults.standard.data(forKey: CacheAsyncHarness.storedPrefix + "all.main") != nil && CacheAsyncHarness.storedCurrent("all") == durableAll, "all barrier preserves durable data, rejects queued pointer")
        _ = await all.resolveCurrent("all", epoch: all.inspect { $0.epochs["all"]! })
        // A newer actual Main success was not written before the epoch barrier.
        // The production invalidatedOrigins candidate must beat the older Ring
        // disk pointer; restoring 2.31 here would silently change the actual Key.
        checkAsync(all.cachedQuota(instanceId: "all")?.amountUSD == 1.10 && all.inspect { $0.currentOrigins["all"] } == pendingMain, "all invalidation preserves latest successful owner over old disk pointer")
        all.invalidate(instanceId: "all"); await all.flushWriter()
        _ = await all.resolveCurrent("all", epoch: all.inspect { $0.epochs["all"]! })
        checkAsync(all.cachedQuota(instanceId: "all")?.amountUSD == 1.10 && all.inspect { $0.currentOrigins["all"] } == pendingMain && CacheAsyncHarness.storedCurrent("all") == durableAll, "instance invalidation preserves latest successful owner and durable data")
        // With no in-memory success candidate, a cold service still restores the
        // valid older durable Ring record. This separately proves offline IO.
        let allCold = CacheAsyncHarness(), allColdEpoch = UUID()
        allCold.setup { $0.epochs["all"] = allColdEpoch }
        _ = await allCold.resolveCurrent("all", epoch: allColdEpoch)
        checkAsync(allCold.cachedQuota(instanceId: "all")?.amountUSD == 2.31 && allCold.inspect { $0.currentOrigins["all"] } == durableAll, "cold all invalidation restores valid durable owner balance offline")
        checkAsync(CacheAsyncHarness.storedInfo(instanceId: "sibling", origin: siblingOrigin, processOwner: siblingOrigin.owner) != nil, "all barrier leaves sibling records untouched")

        let seed = CacheAsyncHarness(); await query(seed, id: "cold"); await seed.flushWriter()
        let cold = CacheAsyncHarness(), coldEpoch = UUID(), readGate = StorageGate()
        cold.setup { $0.epochs["cold"] = coldEpoch }
        UserDefaults.standard.arm("read", key: CacheAsyncHarness.currentPrefix + "cold", gate: readGate)
        let oldRestore = Task { await cold.resolveCurrent("cold", epoch: coldEpoch) }
        await readGate.waitForArrival()
        await mainProbe(cold, id: "cold")
        await success(cold, id: "cold", row: "ring", key: "synthetic-ring")
        await query(cold, id: "cold", row: "ring", key: "synthetic-ring")
        readGate.release()
        let oldResolution = await oldRestore.value
        checkAsync(oldResolution == nil, "old disk read cannot override new memory version")
        await cold.flushWriter()
        let reopen = CacheAsyncHarness(), reopenEpoch = UUID()
        reopen.setup { $0.epochs["cold"] = reopenEpoch }
        _ = await reopen.resolveCurrent("cold", epoch: reopenEpoch)
        checkAsync(reopen.cachedQuota(instanceId: "cold")?.amountUSD == 2.31, "cold current owner/row restore")

        // Real cold foreground TTL -> scheduleAutomatic -> runAutomatic ->
        // refreshRow. No consumed event, clock substitute or schedule counter.
        let cancel = CacheAsyncHarness(), cancellationGate = FixtureGate()
        await FixturePlan.shared.pauseCollect("main", at: cancellationGate)
        await MainActor.run {
            UIApplication.shared.applicationState = .active
            cancel.refreshAllIfNeeded(instances: [ProviderInstance(id: "cancel")])
        }
        await cancellationGate.waitForArrival()
        cancel.suspendAutomaticRefresh()
        await MainActor.run { UIApplication.shared.applicationState = .background }
        await cancellationGate.release()
        await until("cancelled real task leaked running/ticket") {
            cancel.inspect { $0.clocks["cancel"]?.running == false && $0.inFlight["cancel|main"] == nil }
        }
        checkAsync(cancel.inspect { $0.clocks["cancel"]?.dirty } == true, "background cancel keeps dirty")
        cancel.setup { $0.clocks["cancel"]?.lastAttemptAt = Date().addingTimeInterval(-40) }
        await MainActor.run {
            UIApplication.shared.applicationState = .active
            cancel.refreshAllIfNeeded(instances: [ProviderInstance(id: "cancel")])
        }
        await until("foreground cold fallback did not commit bill") { cancel.inspect { $0.cache["cancel"]?.info?.amountUSD == 1.10 } }
        await cancel.flushWriter()
        cancel.suspendAutomaticRefresh()
        print("quota-storage-async-ok")
    }
}
