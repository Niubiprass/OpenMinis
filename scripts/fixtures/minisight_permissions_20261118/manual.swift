import Foundation

func MSDiagEvent(_ a: String, _ b: String, _ c: String, _ details: [String: Any]) {}
@MainActor final class ManualBridge {
    var activeGeneration = 1, nextGeneration = 1
    var manualStartPending = true, listening = false
    var namedSession: Int?
    var speechDeadline: Task<Void, Never>?
    var writes = [String]()
    func write(result: String, final: Bool, reason: String?, generation: Int, state: String) {
        writes.append(reason ?? state)
    }
    func stop() { listening = false; speechDeadline?.cancel(); speechDeadline = nil }
    func begin() -> Task<Void, Never> {
        Task { await self.startListening(generation: 1, lease: 1) }
    }
    // PRODUCTION_MANUAL_METHOD
}
