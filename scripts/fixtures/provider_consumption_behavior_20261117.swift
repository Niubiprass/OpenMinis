// Exercises real factories + MultiKeyAgentProvider + recordSuccess + emitted
// notification + real quota consumed/automatic query, with synthetic IO only.
final class ConsumptionEvents: @unchecked Sendable {
    let lock = NSLock()
    var values: [String: [ProviderQuotaSuccess]] = [:]
    func append(_ event: ProviderQuotaSuccess) {
        lock.lock(); values[event.instanceId, default: []].append(event); lock.unlock()
    }
    func get(_ id: String) -> [ProviderQuotaSuccess] { lock.lock(); defer { lock.unlock() }; return values[id] ?? [] }
}
@main struct ProviderConsumptionFixture {
    static let events = ConsumptionEvents()
    static let service = ProviderQuotaService.shared
    static let manager = ProviderMultiKeyManager.shared
    static func until(_ label: String, _ predicate: () -> Bool) async {
        let deadline = Date().addingTimeInterval(12)
        while Date() < deadline { if predicate() { return }; await Task.yield() }
        fatalError(label)
    }
    static func settle() async {
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            DispatchQueue.main.async { continuation.resume() }
        }
        for _ in 0..<300 { await Task.yield() }
    }
    static func configure(_ id: String, key: String = "synthetic-main", enabled: Bool = false,
                          ring: [ProviderAPIKey] = [], credential: ProviderInstance.CredentialType = .apiKey,
                          type: ProviderType = .openAI) async -> ModelEntry {
        await MainActor.run {
            var instance = ProviderInstance(id: id)
            instance.credentialType = credential; instance.providerType = type
            ProviderConfigStore.shared.values[id] = instance
        }
        ProviderKeychainHelper.put(key, id: id)
        manager.put(ring, id: id, enabled: enabled)
        return ModelEntry(providerInstanceId: id)
    }
    static func agent(_ entry: ModelEntry, allows: Bool = true) async -> any AgentProvider {
        await AIChatViewModel.makeAgentProvider(for: entry, resolveSessionId: { nil }, allowsMultiKey: allows)
    }
    static func drain(_ provider: any AgentProvider) async throws {
        let stream = try await provider.streamAgentMessageClamped(messages: [], systemPrompt: nil, tools: [], maxTokens: 128, thinkingLevel: .off)
        for try await _ in stream {}
        try Task.checkCancellation()
    }
    static func clock(_ id: String) -> Date? { service.inspect { $0.clocks[id]?.lastSuccessAt } }
    static func requestSucceeded(_ id: String, row: String = "main") async -> ProviderQuotaSuccess {
        await until("didSucceed absent: " + id) { events.get(id).count == 1 }
        let event = events.get(id)[0]
        await until("real consumed absent: " + id) { clock(id) == event.succeededAt }
        checkAsync(event.rowId == row, "actual frozen row: " + id)
        checkAsync(event.requestEpoch != nil, "sending epoch captured: " + id)
        return event
    }
    static func main() async throws {
        await MainActor.run { UIApplication.shared.applicationState = .background }
        let observer = NotificationCenter.default.addObserver(forName: ProviderMultiKeyManager.didSucceed, object: nil, queue: nil) { note in
            guard let success = note.object as? ProviderQuotaSuccess else { return }
            events.append(success)
            // Exact production observer success forwarding; consumed must
            // de-duplicate this replay after the direct report call.
            service.consumed(success)
        }
        defer { NotificationCenter.default.removeObserver(observer) }

        let off = await configure("off", ring: [ProviderAPIKey(key: "synthetic-unused-ring")])
        let before = manager.counts()
        try! await drain(agent(off))
        let offEvent = await requestSucceeded("off")
        checkAsync(offEvent.credentialIdentity == ProviderQuotaSuccess.identity("synthetic-main"), "off freezes main")
        checkAsync(manager.counts().0 == before.0 && manager.counts().1 == before.1, "off no selection/retry/statistics")
        let empty = await configure("empty", enabled: true)
        try! await drain(agent(empty))
        _ = await requestSucceeded("empty")
        checkAsync(manager.counts().0 == before.0, "empty ring no selection")

        for (id, type) in [("anthropic", ProviderType.anthropic), ("gemini", .gemini)] {
            let entry = await configure(id, type: type)
            let provider = await agent(entry)
            if type == .anthropic { checkAsync((provider as? MultiKeyAgentProvider)?.isAnthropic == true, "Anthropic type bridge") }
            try! await drain(provider)
            _ = await requestSucceeded(id)
        }
        let oauth = await configure("oauth", key: "synthetic-oauth", credential: .oauth)
        try! await drain(agent(oauth))
        let noKey = await configure("no-key", key: "  \n ")
        try! await drain(agent(noKey))
        let internalEntry = await configure("inner")
        try! await drain(agent(internalEntry, allows: false))
        await settle()
        for id in ["oauth", "no-key", "inner"] {
            checkAsync(events.get(id).isEmpty && clock(id) == nil, "must not report: " + id)
        }

        for (id, scenario) in [("open-failure", ConsumptionScenario.failOpen), ("stream-failure", .failStream)] {
            let entry = await configure(id, key: id)
            await ConsumptionPlan.shared.set(id, scenario)
            do { try await drain(agent(entry)); fatalError("error swallowed: " + id) } catch {}
            await settle()
            checkAsync(events.get(id).isEmpty && clock(id) == nil, "failed stream no report")
        }
        let creationGate = FixtureGate()
        let creationEntry = await configure("creation", key: "creation")
        await ConsumptionPlan.shared.set("creation", .held(creationGate))
        let creationProvider = await agent(creationEntry)
        let opened = try! await creationProvider.streamAgentMessageClamped(messages: [], systemPrompt: nil, tools: [], maxTokens: 128, thinkingLevel: .off)
        await creationGate.waitForArrival()
        await settle()
        checkAsync(events.get("creation").isEmpty && clock("creation") == nil, "stream creation not consumption")
        await creationGate.release()
        for try await _ in opened {}
        _ = await requestSucceeded("creation")

        let partialGate = FixtureGate()
        let partialEntry = await configure("partial", key: "partial")
        await ConsumptionPlan.shared.set("partial", .partial(partialGate))
        let partialProvider = await agent(partialEntry)
        let task = Task { try await drain(partialProvider) }
        await partialGate.waitForArrival()
        task.cancel(); await partialGate.release()
        do { try await task.value; fatalError("cancel swallowed") } catch {}
        await settle()
        checkAsync(events.get("partial").isEmpty && clock("partial") == nil, "partial + done + cancel no report")

        // Multi ON: baseline and per-lease builders use allowsMultiKey:false.
        let ringKey = ProviderAPIKey(key: "synthetic-ring")
        let multi = await configure("multi", key: "synthetic-main", enabled: true, ring: [ringKey])
        let multiProvider = await agent(multi)
        let leaseCount = manager.counts().0
        try! await drain(multiProvider)
        _ = await requestSucceeded("multi")
        await settle()
        checkAsync(events.get("multi").count == 1 && manager.counts().0 == leaseCount + 1, "multi cannot double report")
        checkAsync(manager.keys(for: "multi")[0].successCount == 0, "only actual leased main counted")

        // A main succeeds first but its manager active-check/report is delayed.
        // B ring succeeds and reports first; releasing A cannot steal B owner.
        let delayed = await configure("delayed", key: "synthetic-A", enabled: true, ring: [ringKey])
        let delayedProvider = await agent(delayed)
        let reportGate = FixtureGate()
        await ConsumptionPlan.shared.set("synthetic-A", .delayed(reportGate))
        let a = Task { try await drain(delayedProvider) }
        await reportGate.waitForArrival()
        try! await drain(delayedProvider)
        let bEvent = await requestSucceeded("delayed", row: ringKey.id)
        await reportGate.release(); try! await a.value
        await until("A report not delivered") { events.get("delayed").count == 2 }
        await settle()
        let aEvent = events.get("delayed").first { $0.rowId == "main" }!
        checkAsync(aEvent.succeededAt < bEvent.succeededAt, "freeze boundary A before B despite delayed report")
        checkAsync(clock("delayed") == bEvent.succeededAt && service.inspect { $0.currentOrigins["delayed"]?.rowId == ringKey.id }, "late A cannot steal B")

        // Statistics themselves receive reversed successful completion times.
        let stats = await configure("stats", enabled: true, ring: [ringKey])
        let epoch = service.consumptionEpoch(for: stats.providerInstanceId)
        let lease = ProviderKeyLease(id: ringKey.id, key: ringKey.key)
        let old = Date(); let newer = old.addingTimeInterval(2)
        let statsIdentity = ProviderQuotaSuccess.identity(lease.key)
        await Task.detached {
            manager.recordSuccess(lease: lease, for: "stats", succeededAt: newer, requestEpoch: epoch, credentialIdentity: statsIdentity)
            manager.recordSuccess(lease: lease, for: "stats", succeededAt: old, requestEpoch: epoch, credentialIdentity: statsIdentity)
        }.value
        checkAsync(manager.keys(for: "stats")[0].lastUsed == newer && manager.keys(for: "stats")[0].successCount == 2, "lastUsed max preserves both counts")

        // Frozen main identity must never switch to an edited saved key.
        let frozenEntry = await configure("identity", key: "synthetic-old")
        let frozenProvider = await agent(frozenEntry)
        ProviderKeychainHelper.put("synthetic-new", id: "identity")
        try! await drain(frozenProvider)
        await until("frozen identity report") { events.get("identity").count == 1 }
        await settle()
        checkAsync(events.get("identity")[0].credentialIdentity == ProviderQuotaSuccess.identity("synthetic-old") && clock("identity") == nil, "actual sent identity retained; edited identity rejected")

        // Same key and owner, but config epoch invalidates the in-flight send.
        let epochEntry = await configure("epoch", key: "epoch")
        let epochProvider = await agent(epochEntry)
        let epochGate = FixtureGate()
        await ConsumptionPlan.shared.set("epoch", .held(epochGate))
        let epochTask = Task { try await drain(epochProvider) }
        await epochGate.waitForArrival()
        service.invalidate(instanceId: "epoch")
        await epochGate.release(); try! await epochTask.value
        await until("epoch event reported") { events.get("epoch").count == 1 }
        await settle()
        checkAsync(clock("epoch") == nil, "request epoch rejects old in-flight send even with identical key")

        // QuickTest executes its production text arm, not a hand-made send.
        let qt = await configure("quick-text")
        _ = try! await quickText(qt)
        _ = await requestSucceeded("quick-text")
        let qtFailure = await configure("quick-failure", key: "quick-failure")
        await ConsumptionPlan.shared.set("quick-failure", .failOpen)
        do { _ = try await quickText(qtFailure); fatalError("QuickTest failure swallowed") } catch {}
        await settle(); checkAsync(events.get("quick-failure").isEmpty, "QuickTest failure no report")

        let qi = await configure("quick-image")
        _ = try! await quickImage(qi)
        _ = await requestSucceeded("quick-image")
        let qif = await configure("quick-image-failure", key: "quick-image-failure")
        await ConsumptionPlan.shared.set("quick-image-failure", .failOpen)
        do { _ = try await quickImage(qif); fatalError("quick image failure swallowed") } catch {}
        await settle(); checkAsync(events.get("quick-image-failure").isEmpty, "quick image failure no event")
        for (id, spec, success) in [
            ("raw-success", SyntheticRawSpec(), true),
            ("raw-explicit-endpoint", SyntheticRawSpec(endpoint: "/v1/chat"), true),
            ("raw-nil-auth-override", SyntheticRawSpec(endpoint: nil, headers: ["Authorization": "synthetic-other"]), false),
            ("raw-http-failure", SyntheticRawSpec(endpoint: "/fail"), false),
            ("raw-auth-override", SyntheticRawSpec(headers: ["Authorization": "synthetic-other"]), false),
            ("raw-query-override", SyntheticRawSpec(endpoint: "/v1/chat?key=synthetic-other"), false)
        ] {
            let entry = await configure(id)
            let req = try! await LLMProviderFactory.makeProviderWithConsumption(for: entry)
            try! await rawBoundary(req.provider as! OpenAIProvider, consumption: req.consumption, spec: spec)
            if success { _ = await requestSucceeded(id) }
            else { await settle(); checkAsync(events.get(id).isEmpty, "raw HTTP/auth boundary must not misreport") }
        }
        let rawFailEntry = await configure("raw-transport-failure", key: "raw-transport-failure")
        let rawFailRequest = try! await LLMProviderFactory.makeProviderWithConsumption(for: rawFailEntry)
        await ConsumptionPlan.shared.set("raw-transport-failure", .failOpen)
        do { try await rawBoundary(rawFailRequest.provider as! OpenAIProvider, consumption: rawFailRequest.consumption, spec: SyntheticRawSpec()); fatalError("raw transport failure swallowed") } catch {}
        await settle(); checkAsync(events.get("raw-transport-failure").isEmpty, "raw transport failure no event")

        // LLM factory returns the real concrete branch; observer is separate.
        for (id, credential) in [("llm-key", ProviderInstance.CredentialType.apiKey), ("llm-oauth", .oauth)] {
            let entry = await configure(id, credential: credential)
            let request = try! await LLMProviderFactory.makeProviderWithConsumption(for: entry)
            checkAsync(request.provider is OpenAIProvider, "OpenAI downcast preserved")
            _ = try! await offloadSend(request.provider, consumption: request.consumption)
            if credential == .apiKey { _ = await requestSucceeded(id) }
            else { await settle(); checkAsync(events.get(id).isEmpty, "LLM OAuth no report") }
        }
        let llmMultiEntry = await configure("llm-multi", enabled: true, ring: [ringKey])
        let llmMultiRequest = try! await LLMProviderFactory.makeProviderWithConsumption(for: llmMultiEntry)
        let llmLeaseCount = manager.counts().0
        _ = try! await offloadSend(llmMultiRequest.provider, consumption: llmMultiRequest.consumption)
        _ = await requestSucceeded("llm-multi")
        await settle()
        checkAsync(events.get("llm-multi").count == 1 && manager.counts().0 == llmLeaseCount, "concrete LLM uses actual main even with ring ON; no extra lease or dual event")
        let llmEmptyEntry = await configure("llm-empty", key: "  ")
        let llmEmptyRequest = try! await LLMProviderFactory.makeProviderWithConsumption(for: llmEmptyEntry)
        _ = try! await offloadSend(llmEmptyRequest.provider, consumption: llmEmptyRequest.consumption)
        await settle(); checkAsync(events.get("llm-empty").isEmpty, "empty LLM credential must not report")
        for (id, scenario) in [("send-failure", ConsumptionScenario.failOpen), ("offload-stream-failure", .failStream)] {
            let entry = await configure(id, key: id)
            let request = try! await LLMProviderFactory.makeProviderWithConsumption(for: entry)
            await ConsumptionPlan.shared.set(id, scenario)
            do {
                if id == "send-failure" { _ = try await offloadSend(request.provider, consumption: request.consumption) }
                else { try await offloadStream(request.provider, consumption: request.consumption) }
                fatalError("Offload failure swallowed")
            } catch {}
            await settle(); checkAsync(events.get(id).isEmpty, "Offload failure no report")
        }
        let osEntry = await configure("offload-stream")
        let osRequest = try! await LLMProviderFactory.makeProviderWithConsumption(for: osEntry)
        try! await offloadStream(osRequest.provider, consumption: osRequest.consumption)
        _ = await requestSucceeded("offload-stream")
        let ocEntry = await configure("offload-cancel", key: "offload-cancel")
        let ocRequest = try! await LLMProviderFactory.makeProviderWithConsumption(for: ocEntry)
        let ocGate = FixtureGate()
        await ConsumptionPlan.shared.set("offload-cancel", .partial(ocGate))
        let ocTask = Task { try await offloadStream(ocRequest.provider, consumption: ocRequest.consumption) }
        await ocGate.waitForArrival(); ocTask.cancel(); await ocGate.release()
        do { try await ocTask.value; fatalError("Offload cancellation swallowed") } catch {}
        await settle(); checkAsync(events.get("offload-cancel").isEmpty, "Offload partial/done cancelled no report")

        // Real emitted event -> real quota consumed -> real scheduling and
        // synthetic collect -> real cache commit; no direct manual refresh.
        await MainActor.run { UIApplication.shared.applicationState = .active }
        let actualEntry = await configure("event-to-quota")
        try! await drain(agent(actualEntry))
        let realEvent = await requestSucceeded("event-to-quota")
        await until("emitted event did not schedule/commit real quota") { service.cachedQuota(instanceId: "event-to-quota")?.amountUSD == 1.10 }
        await settle()
        checkAsync(events.get("event-to-quota").count == 1 && clock("event-to-quota") == realEvent.succeededAt, "duplicate notification did not advance real completion time")
        checkAsync(service.inspect { $0.clocks["event-to-quota"]?.dirty == false }, "real refresh consumes dirty ticket")
        print("provider-consumption-production-ok")
    }
}
