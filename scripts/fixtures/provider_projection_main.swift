// All assertions below run inside the extracted production cache's MainActor.
// No replacement count/projection algorithm is implemented in this fixture.
extension CountStore {
    func runProjectionCases() {
        func entry(_ owner: String, _ id: String, hidden: Bool = false,
                   voice: Bool = false, input: Bool = false, output: Bool = false,
                   modified: TimeInterval? = nil) -> ModelEntry {
            precondition(voice == (input || output), "synthetic flags match production voice union")
            return ModelEntry(providerInstanceId: owner,
                       baseModel: ProjectionBaseModel(id: id, isVoiceCandidate: voice,
                           isVoiceInputCandidate: input, isVoiceOutputCandidate: output),
                       isHidden: hidden, userModifiedAt: modified.map { Date(timeIntervalSince1970: $0) })
        }
        // Preserve the original count regression's exact A/B/hidden/missing data.
        config = ProviderConfig(modelEntries: [entry("A", "a1"), entry("A", "hidden", hidden: true),
                                               entry("B", "b1"), entry("A", "a2")])
        precondition(visibleEntryCount(for: "A") == 2)
        precondition(visibleEntryCount(for: "B") == 1)
        precondition(visibleEntryCount(for: "missing") == 0)
        config.modelEntries = []
        precondition(modelEntryProjection == nil, "original direct clear invalidates")
        precondition(visibleEntryCount(for: "A") == 0)
        config = ProviderConfig(instances: [ProviderInstance(id: "A"), ProviderInstance(id: "B")],
            modelEntries: [
                entry("A", "text", modified: 90),
                entry("A", "input", hidden: true, voice: true, input: true, modified: 10),
                entry("A", "output", voice: true, output: true, modified: 20),
                entry("A", "both", voice: true, input: true, output: true, modified: 30),
                entry("B", "hidden-text", hidden: true, modified: 40),
                entry("B", "hidden-output", hidden: true, voice: true, output: true, modified: 5)
            ])
        precondition(visibleEntryCount(for: "A") == 3, "visible A excludes hidden")
        precondition(visibleEntryCount(for: "B") == 0, "all-hidden B")
        precondition(visibleEntryCount(for: "missing") == 0, "missing count")
        precondition(hasVoiceModels(for: "A") && hasVoiceModels(for: "B"), "hidden is not a voice filter")
        precondition(!hasVoiceModels(for: "missing"), "missing voice")
        let projection = derivedModelEntryProjection()
        let rep = ProviderInstance(id: "A")
        // SHADOW_MODEL_SELECTION
        precondition(entries.map(\.baseModel.id) == ["input", "output", "both"], "voice union keeps source order")
        precondition(inputs.map(\.baseModel.id) == ["input", "both"], "input includes hidden")
        precondition(outputs.map(\.baseModel.id) == ["output", "both"], "output union")
        precondition(projection.voiceEntriesByInstance["B"]?.map(\.baseModel.id) == ["hidden-output"])
        precondition(projection.voiceInstanceIds == Set(["A", "B"]))
        precondition(projection.latestModifiedAtByInstance["A"] == Date(timeIntervalSince1970: 90), "nonvoice timestamp")
        precondition(projection.latestModifiedAtByInstance["B"] == Date(timeIntervalSince1970: 40), "hidden nonvoice timestamp")
        precondition(projection.latestModifiedAtByInstance["missing"] == nil)
        precondition(modelEntryProjection != nil, "cache primed")
        _ = visibleEntryCount(for: "A")
        precondition(modelEntryProjection != nil, "repeat cache access")

        // Direct nested value writes must trigger the REAL config didSet.
        config.modelEntries[1].isHidden = false
        precondition(modelEntryProjection == nil, "direct hidden mutation invalidates")
        precondition(visibleEntryCount(for: "A") == 4)
        precondition(hasVoiceModels(for: "A"), "hidden toggle preserves voice capability")
        config.modelEntries.append(entry("B", "new-text", modified: 100))
        precondition(modelEntryProjection == nil, "append invalidates")
        precondition(visibleEntryCount(for: "B") == 1)
        precondition(derivedModelEntryProjection().latestModifiedAtByInstance["B"] == Date(timeIntervalSince1970: 100))
        config.modelEntries.removeAll { $0.providerInstanceId == "A" }
        precondition(modelEntryProjection == nil, "remove invalidates")
        precondition(visibleEntryCount(for: "A") == 0 && !hasVoiceModels(for: "A"))

        // Copy/alias assignment must not keep the previous snapshot's cache.
        var alias = config
        alias.modelEntries.append(entry("A", "aliased-model", voice: true, input: true))
        config = alias
        precondition(modelEntryProjection == nil, "whole assignment invalidates")
        precondition(visibleEntryCount(for: "A") == 1 && hasVoiceModels(for: "A"))
        config.modelEntries[config.modelEntries.count - 1].overrides.name = "renamed alias"
        precondition(modelEntryProjection == nil, "model alias mutation invalidates even with same count")
        precondition(visibleEntryCount(for: "A") == 1 && hasVoiceModels(for: "A"))
        precondition(derivedModelEntryProjection().voiceEntriesByInstance["A"]?.first?.overrides.name == "renamed alias")
        precondition(derivedModelEntryProjection().latestModifiedAtByInstance["A"] == nil)
        var replacement = config
        replacement.modelEntries = [entry("B", "replacement", voice: true, output: true)]
        config = replacement
        precondition(modelEntryProjection == nil, "assignment removes old and adds new")
        precondition(visibleEntryCount(for: "A") == 0 && !hasVoiceModels(for: "A"))
        precondition(visibleEntryCount(for: "B") == 1 && hasVoiceModels(for: "B"))
        config = .empty
        precondition(modelEntryProjection == nil, "empty assignment invalidates")
        precondition(visibleEntryCount(for: "B") == 0 && !hasVoiceModels(for: "B"))
        precondition(derivedModelEntryProjection().voiceEntriesByInstance.isEmpty)
        precondition(derivedModelEntryProjection().latestModifiedAtByInstance.isEmpty)
        print("PASS: production visible model count / voice union / timestamps / config invalidation")
    }
}
@main struct ProjectionMain {
    @MainActor static func main() {
        CountStore(config: .empty).runProjectionCases()
    }
}
