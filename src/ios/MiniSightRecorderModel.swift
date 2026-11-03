import Combine
import Foundation

@MainActor
final class MiniSightAppRecorderModel: ObservableObject {
    @Published private(set) var isRecording = false
    @Published var message: String?
    private let service = MiniSightAppRecorder()

    init() {
        service.stateHandler = { [weak self] value in
            DispatchQueue.main.async { self?.isRecording = value }
        }
        service.messageHandler = { [weak self] value in
            DispatchQueue.main.async { self?.message = value }
        }
    }

    func startIfNeeded() { if !isRecording { service.start() } }
    func start() { service.start() }
    func stop() { service.stop() }
    func stopIfNeeded() { service.stopIfNeeded() }
}
