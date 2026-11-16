import Foundation

// Compile the entire unmodified production Remote on macOS. Its Darwin observer
// has an App-controller symbol, but this fixture NEVER installs or polls it.
// Any accidental observer/controller dispatch is a hard failure, not fake I/O.
@MainActor
final class MiniSightWakeController {
    static let shared = MiniSightWakeController()
    private init() {}
    func pollRemoteState() { fatalError("fixture must not poll remote state") }
}
