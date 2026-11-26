import Foundation

// Shapes only; actual ordering, normalization, Rank and worker are extracted.
struct LLMModel {
    let id: String
    let displayName: String
    let contextWindow: Int?
}
struct ModelEntry {
    let providerInstanceId: String
    let baseModel: LLMModel
}
struct ProviderInstance { let id: String; let createdAt: Date }
struct ProviderConfig { let instances: [ProviderInstance]; let modelEntries: [ModelEntry] }
enum ModelsDevAPI {
    struct ReleaseEntry {
        let date: Date
        let day: Int
        let outputCost: Double?
        let context: Int?
    }
    struct ReleaseIndex {
        let byFullId: [String: ReleaseEntry]
        let byTail: [String: ReleaseEntry]
    }
    static var catalog: ReleaseIndex?
    static var reads = 0
    static func releaseIndex() -> ReleaseIndex? { reads += 1; return catalog }
}

// PRODUCTION_DECLARATIONS

@main struct PickerSortProbe {
    static func model(_ id: String, name: String? = nil, context: Int? = nil, instance: String = "A") -> ModelEntry {
        ModelEntry(providerInstanceId: instance, baseModel: LLMModel(id: id, displayName: name ?? id, contextWindow: context))
    }
    private static func keys(_ entries: [ModelEntry], index: ModelsDevAPI.ReleaseIndex?) -> [PickerSortInput.ReleaseKey] {
        entries.enumerated().map { offset, entry in
            .init(modelID: entry.baseModel.id, rank: ModelReleaseIndex.rank(modelId: entry.baseModel.id,
                displayName: entry.baseModel.displayName, contextWindow: entry.baseModel.contextWindow, index: index), offset: offset)
        }
    }
    static func offsets(_ entries: [ModelEntry]) -> [String] { entries.map { $0.providerInstanceId + ":" + $0.baseModel.id } }

    @MainActor static func main() async throws {
        let d1 = ModelReleaseIndex.parseReleaseDate("2025-02-01")!
        let d2 = ModelReleaseIndex.parseReleaseDate("2026-03")!
        let catalog = ModelsDevAPI.ReleaseIndex(byFullId: [
            "vendor/new": .init(date: d2.date, day: d2.day, outputCost: 4, context: 1000),
            "old": .init(date: d1.date, day: d1.day, outputCost: 1, context: 500)
        ], byTail: [
            "new": .init(date: d2.date, day: d2.day, outputCost: 4, context: 1000),
            "old": .init(date: d1.date, day: d1.day, outputCost: 1, context: 500)
        ])
        ModelsDevAPI.catalog = catalog
        let worker = PickerSortWorker()
        let instances = [ProviderInstance(id: "B", createdAt: Date(timeIntervalSince1970: 2)),
                         ProviderInstance(id: "A", createdAt: Date(timeIntervalSince1970: 1)),
                         ProviderInstance(id: "C", createdAt: Date(timeIntervalSince1970: 2))]
        let entries = [model("z", instance: "B"), model("old"), model("vendor/new"),
                       model("local", instance: "C"), model("orphan", instance: "missing"),
                       model("undated"), model("old"), model("a", instance: "B")]
        let reference = SortReference(config: .init(instances: instances, modelEntries: entries))
        let alphaInput = PickerSortInput.alphabetical(instances: instances.enumerated().map { offset, instance in
            .init(id: instance.id, createdAt: instance.createdAt.timeIntervalSinceReferenceDate, offset: offset)
        }, entries: entries.enumerated().map { offset, entry in
            .init(instanceID: entry.providerInstanceId, modelID: entry.baseModel.id, offset: offset)
        })
        let alpha = try await worker.sort(alphaInput)[0]
        precondition(offsets(alpha.map { entries[$0] }) == offsets(reference.sortedEntries(entries)), "actual alphabetical equivalence")
        let ranked = try await worker.sort(.release(sections: [keys(entries, index: catalog)]))[0]
        precondition(offsets(ranked.map { entries[$0] }) == offsets(SortReference.sortedByReleaseRank(entries)), "actual release equivalence")
        precondition(ranked.filter { $0 == 1 || $0 == 6 } == [1, 6], "stable duplicate tie")
        let reads = ModelsDevAPI.reads
        let _ = keys(entries, index: catalog)
        precondition(ModelsDevAPI.reads == reads, "one explicit index, no per-item reload")
        let system: [PickerSortInput.ReleaseKey] = [
            .init(modelID: "z-system", rank: nil, offset: 0), .init(modelID: "a-system", rank: nil, offset: 1)
        ]
        let systemOrder = try await worker.sort(.release(sections: [system, [], [.init(modelID: "one", rank: nil, offset: 0)]]))
        precondition(systemOrder == [[0, 1], [], [0]], "system / singleton order unchanged")
        let unknown = [model("z-custom"), model("a-local"), model("b-relay")]
        let nilOrder = try await worker.sort(.release(sections: [keys(unknown, index: nil)]))[0]
        precondition(nilOrder == [1, 2, 0], "undated/custom stay and sort")

        // Each guard rejects independently, including unsaved config changes.
        let ticket = PickerBuildTicket(generation: 7, revision: 3, snapshotRevision: 9, key: "voice")
        precondition(ticket.accepts(current: ticket, cancelled: false))
        precondition(!ticket.accepts(current: ticket, cancelled: true), "cancelled task")
        precondition(!ticket.accepts(current: .init(generation: 8, revision: 3, snapshotRevision: 9, key: "voice"), cancelled: false), "old generation")
        precondition(!ticket.accepts(current: .init(generation: 7, revision: 4, snapshotRevision: 9, key: "voice"), cancelled: false), "new config")
        precondition(!ticket.accepts(current: .init(generation: 7, revision: 3, snapshotRevision: 10, key: "voice"), cancelled: false), "unsaved snapshot")
        precondition(!ticket.accepts(current: .init(generation: 7, revision: 3, snapshotRevision: 9, key: "text"), cancelled: false), "new cache key")
        let cancellation = PickerSortCancellation()
        cancellation.cancel()
        do {
            _ = try PickerSortWorker.orderedOffsets(alphaInput, cancellation: cancellation)
            preconditionFailure("cancel token ignored")
        } catch is CancellationError { }

        // Returned offsets apply to the CAPTURED array, never a new live array.
        let replacement = [model("replaced")]
        precondition(entries.count != replacement.count)
        precondition(alpha.map { entries[$0] }.count == entries.count, "snapshot aligned")
        let newEntries = [model("new-z"), model("new-a")]
        let newOrder = try await worker.sort(.release(sections: [keys(newEntries, index: nil)]))[0]
        precondition(newOrder.map { newEntries[$0].baseModel.id } == ["new-a", "new-z"], "new snapshot aligned")

        // Synthetic scale only, not a claim about a 302-model phone. Race a
        // cancelled request against two replacements; every continuation ends.
        let large = (0..<20000).reversed().map { index in
            PickerSortInput.EntryKey(instanceID: "A", modelID: String(index), offset: index)
        }
        let slow = Task { try await worker.sort(.alphabetical(instances: [], entries: large)) }
        slow.cancel()
        let first = Task { try await worker.sort(alphaInput) }
        first.cancel()
        let latest = try await worker.sort(alphaInput)
        precondition(latest[0] == alpha, "latest request succeeds after cancellation")
        do {
            _ = try await slow.value
            preconditionFailure("cancelled large task returned an order")
        } catch is CancellationError { }
        do {
            _ = try await first.value
            preconditionFailure("cancelled old task returned an order")
        } catch is CancellationError { }
        print("PASS: actual picker worker ordering / cancellation / ticket / captured snapshot")
    }
}
