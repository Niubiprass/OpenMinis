// Synthetic data shapes and DI I/O ONLY. All cache/load/index/lookup code below
// is extracted from the production API; no network, Defaults or credentials.
import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
private struct TestLogger {
    func info(_ s: String) {}
    func error(_ s: String) {}
}
private let logger = TestLogger()
struct ModelModality: OptionSet, Equatable, Sendable {
    let rawValue: Int
    static let textInput = Self(rawValue: 1 << 0)
    static let imageInput = Self(rawValue: 1 << 1)
    static let pdfInput = Self(rawValue: 1 << 2)
    static let audioInput = Self(rawValue: 1 << 3)
    static let videoInput = Self(rawValue: 1 << 4)
    static let textOutput = Self(rawValue: 1 << 5)
    static let imageOutput = Self(rawValue: 1 << 6)
    static let audioOutput = Self(rawValue: 1 << 7)
    static let videoOutput = Self(rawValue: 1 << 8)
}
struct LLMModel: Equatable, Sendable {
    var id: String
    var displayName: String
    var provider: String
    var modalityOverride: ModelModality? = nil
    var contextWindow: Int? = nil
    var maxOutputTokens: Int? = nil
    var supportsReasoning: Bool? = nil
    var interleavedReasoningField: String? = nil
    var reasoningEffortValues: [String]? = nil
    var declaresNoEffortTiers: Bool? = nil
    var effortDeclarationIsAuthoritative: Bool? = nil
}
private final class FixtureIO: @unchecked Sendable {
    static let shared = FixtureIO()
    let entered = DispatchSemaphore(value: 0)
    let gate = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var data = Data()
    private var blocked = false
    private var reads = 0
    func configure(_ value: Data, blocked: Bool) {
        lock.lock(); data = value; self.blocked = blocked; reads = 0; lock.unlock()
    }
    func read() -> (Data, Date)? {
        lock.lock(); let value = data; let block = blocked; reads += 1; lock.unlock()
        if block {
            entered.signal()
            precondition(gate.wait(timeout: .now() + 10) == .success, "fixture cold gate timed out")
        }
        return (value, Date())
    }
    var readCount: Int { lock.lock(); defer { lock.unlock() }; return reads }
}

private final class BuildGate: @unchecked Sendable {
    static let shared = BuildGate()
    let entered = DispatchSemaphore(value: 0)
    let gate = DispatchSemaphore(value: 0)
    private let lock = NSLock()
    private var armed: String?
    func arm(_ kind: String) { lock.lock(); armed = kind; lock.unlock() }
    func checkpoint(_ kind: String) {
        lock.lock(); let block = armed == kind
        if block { armed = nil }; lock.unlock()
        if block {
            entered.signal()
            precondition(gate.wait(timeout: .now() + 10) == .success, "fixture index gate timed out")
        }
    }
}

// PRODUCTION_CATALOG

// Access only: no replacement algorithm. Private extensions share this file.
extension ModelsDevAPI {
    static func fixtureReset(_ data: Data, blocked: Bool = false) {
        catalog.withLock { $0 = CatalogState() }
        FixtureIO.shared.configure(data, blocked: blocked)
    }
    static func fixtureRefresh(_ data: Data) {
        installRefreshedRegistry(parseRegistry(data)!, timestamp: Date())
    }
    static func fixtureCapturedDerived() -> @Sendable () -> (String?, Int?, Int?) {
        let snapshot = loadRegistry()!
        return {
            let stage = stage2Index(for: snapshot)?["family-1-model"]?.model.name
            let aggregate = aggregateIndex(for: snapshot)?["family-1"]?.limit?.context
            let release = releaseIndex(for: snapshot).byFullId["family-1-model"]?.day
            return (stage, aggregate, release)
        }
    }
    static func fixtureCoherentCaches() -> Bool {
        catalog.withLock { state in
            guard let epoch = state.snapshot?.epoch else { return false }
            return state.stage2?.epoch == epoch && state.aggregate?.epoch == epoch && state.release?.epoch == epoch
        }
    }
}

extension LegacyCatalogOracle {
    static func fixtureInstall(_ data: Data) {
        cachedRegistry = parseRegistry(data)!
        cacheTimestamp = Date()
        cachedStage2Index = nil; cachedAggregateIndex = nil; cachedReleaseIndex = nil
    }
}

private func sample(_ name: String, context: Int, date: String) -> Data {
    Data("""
    {"relay":{"id":"relay","name":"relay","api":"https://fixture.invalid/v1","models":{
      "family-1-model":{"id":"family-1-model","name":"\(name)","limit":{"context":\(context),"output":12},"release_date":"\(date)","cost":{"input":1,"output":2},"reasoning":true,"reasoning_options":[{"type":"effort","values":[null,"HIGH",3,"max"]}],"modalities":{"input":["text","image"],"output":["text"]}},
      "gpt-5.6":{"id":"gpt-5.6","release_date":"2026-07","cost":{"output":4}},
      "embedding":{"id":"embedding","family":"embedding"},
      "undated":{"id":"undated"}}}}
    """.utf8)
}

@main struct CatalogFixture {
    @MainActor static func main() async {
        let old = sample("old", context: 111, date: "2025-01-02")
        let new = sample("new", context: 999, date: "2026-11-01")
        ModelsDevAPI.fixtureReset(old, blocked: true)
        let ticket = PickerBuildTicket(generation: 1, revision: 1, snapshotRevision: 1, key: "fixture")
        var cancelledPublications = 0
        let cancelled = Task { @MainActor in
            let result = await ModelsDevAPI.prepareReleaseIndex()
            if result != nil && ticket.accepts(current: ticket, cancelled: Task.isCancelled) {
                cancelledPublications += 1
            }
        }
        let tasks = (0..<40).map { _ in Task { await ModelsDevAPI.prepareReleaseIndex() } }
        let entered = await Task.detached {
            FixtureIO.shared.entered.wait(timeout: .now() + 5) == .success
        }.value
        precondition(entered, "async cold work never entered")
        var heartbeats = 0
        await Task { @MainActor in heartbeats += 1 }.value
        precondition(heartbeats == 1 && FixtureIO.shared.readCount == 1, "main heartbeat blocked or cold read fanned out")
        cancelled.cancel()
        FixtureIO.shared.gate.signal()
        for task in tasks {
            let result = await task.value
            precondition(result != nil)
        }
        await cancelled.value
        precondition(cancelledPublications == 0 && FixtureIO.shared.readCount == 1, "cancelled waiter published/killed shared preparation")
        _ = await ModelsDevAPI.prepareReleaseIndex()
        precondition(FixtureIO.shared.readCount == 1, "cache hit re-read disk")

        let captured = ModelsDevAPI.fixtureCapturedDerived()
        let before = captured()
        ModelsDevAPI.fixtureRefresh(new)
        let current = ModelsDevAPI.fixtureCapturedDerived()()
        let stale = await Task.detached { captured() }.value
        precondition(before.0 == "old" && before.1 == 111)
        precondition(current.0 == "new" && current.1 == 999 && before.2 != current.2)
        precondition(stale.0 == before.0 && stale.1 == before.1 && stale.2 == before.2, "old snapshot mixed derived epochs")
        precondition(ModelsDevAPI.fixtureCoherentCaches(), "late derived cache poisoned current epoch")

        // The cold read is already executing when refresh swaps the registry.
        ModelsDevAPI.fixtureReset(old, blocked: true)
        let late = Task { await ModelsDevAPI.prepareReleaseIndex() }
        let lateEntered = await Task.detached { FixtureIO.shared.entered.wait(timeout: .now() + 5) == .success }.value
        precondition(lateEntered)
        ModelsDevAPI.fixtureRefresh(new)
        FixtureIO.shared.gate.signal()
        let lateResult = await late.value
        precondition(lateResult?.byFullId["family-1-model"]?.day == current.2, "late cold parse replaced refresh epoch")
        _ = ModelsDevAPI.fixtureCapturedDerived()()
        precondition(ModelsDevAPI.fixtureCoherentCaches())

        // Pause each REAL index builder after capture but before it returns.
        for kind in ["stage2", "aggregate", "release"] {
            ModelsDevAPI.fixtureReset(old)
            let work = ModelsDevAPI.fixtureCapturedDerived()
            BuildGate.shared.arm(kind)
            let delayed = Task.detached { work() }
            let started = await Task.detached {
                BuildGate.shared.entered.wait(timeout: .now() + 5) == .success
            }.value
            precondition(started)
            ModelsDevAPI.fixtureRefresh(new)
            let newest = ModelsDevAPI.fixtureCapturedDerived()()
            BuildGate.shared.gate.signal()
            let delayedValue = await delayed.value
            precondition(delayedValue.0 == "old" && delayedValue.1 == 111 && delayedValue.2 == before.2, "inflight old index lost its snapshot")
            precondition(newest.0 == "new" && ModelsDevAPI.fixtureCoherentCaches(), "inflight index poisoned current epoch")
        }

        // Frozen original implementation is the oracle, not a Python reimplementation.
        LegacyCatalogOracle.fixtureInstall(new)
        let inputs = ["family-1-model", "Vendor/FAMILY.1_MODEL", "family-1-model-cpa", "family-1-other", "missing"]
        for provider in ["OpenAI", "relay", "Antigravity"] {
            for id in inputs {
                let m = LLMModel(id: id, displayName: id, provider: provider)
                precondition(ModelsDevAPI.enrichModel(m) == LegacyCatalogOracle.enrichModel(m), "single lookup oracle mismatch")
            }
            let models = inputs.map { LLMModel(id: $0, displayName: $0, provider: provider) }
            precondition(ModelsDevAPI.enrichModels(models) == LegacyCatalogOracle.enrichModels(models), "bulk lookup oracle mismatch")
        }
        for url in ["https://fixture.invalid", "https://fixture.invalid/v1/", "https://fixture.invalid/custom", "https://missing.invalid"] {
            precondition(ModelsDevAPI.fetchModels(forBaseURL: url).sorted { $0.id < $1.id } == LegacyCatalogOracle.fetchModels(forBaseURL: url).sorted { $0.id < $1.id })
        }
        for id in inputs + ["VENDOR/family-1-model"] {
            let a = ModelsDevAPI.pricingPerMillion(for: id), b = LegacyCatalogOracle.pricingPerMillion(for: id)
            precondition(a?.input == b?.input && a?.output == b?.output, "price oracle mismatch")
        }
        let a = ModelsDevAPI.releaseIndex()!, b = LegacyCatalogOracle.releaseIndex()!
        precondition(a.byFullId.keys.sorted() == b.byFullId.keys.sorted() && a.byTail.keys.sorted() == b.byTail.keys.sorted())
        for key in a.byFullId.keys {
            precondition(a.byFullId[key]?.day == b.byFullId[key]?.day && a.byFullId[key]?.outputCost == b.byFullId[key]?.outputCost && a.byFullId[key]?.context == b.byFullId[key]?.context)
        }
        print("PASS: production catalog single-flight / main heartbeat / cancel ticket / late parse / snapshot caches / legacy oracle")
    }
}
