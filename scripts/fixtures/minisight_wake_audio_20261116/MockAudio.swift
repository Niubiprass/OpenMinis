// Synthetic dependencies ONLY: no AVFoundation, Speech, devices or microphone.
// noff_try_objc simulates the bridge's false result, not native NSException catching.
import Foundation
import CoreFoundation

struct AppLogger {
    init(category: String) {}
    func info(_ message: String) {}
    func warning(_ message: String) {}
    func error(_ message: String) {}
}
protocol ObservableObject {}
@propertyWrapper struct Published<Value> {
    var wrappedValue: Value
    init(wrappedValue: Value) { self.wrappedValue = wrappedValue }
}
final class UserDefaults {
    static let standard = UserDefaults()
    private var values: [String: Any] = [:]
    func string(forKey key: String) -> String? { values[key] as? String }
    func set(_ value: Any?, forKey key: String) { values[key] = value }
}
final class EventLog {
    static let shared = EventLog()
    private let lock = NSLock()
    private var items: [String] = []
    func append(_ value: String) { lock.withLock { items.append(value) } }
    func clear() { lock.withLock { items.removeAll() } }
    var events: [String] { lock.withLock { items } }
}
final class VoiceOutputPlayer {
    static let shared = VoiceOutputPlayer()
    var stopCount = 0
    var pauseCount = 0
    var resumeCount = 0
    func stopAll() { stopCount += 1 }
    func pause() { pauseCount += 1 }
    func resume() { resumeCount += 1 }
}
final class AVAudioSession {
    enum Category: String { case record, playback, playAndRecord }
    enum Mode: String { case measurement, `default`, spokenAudio }
    struct CategoryOptions: OptionSet {
        let rawValue: Int
        static let mixWithOthers = Self(rawValue: 1)
        static let duckOthers = Self(rawValue: 2)
        static let notifyOthersOnDeactivation = Self(rawValue: 4)
    }
    enum InterruptionType: UInt { case began = 1, ended = 0 }
    enum SilenceSecondaryAudioHintType: UInt { case begin = 1, end = 0 }
    enum RecordPermission: Equatable { case granted, denied, undetermined }
    static let interruptionNotification = Notification.Name("mock.interruption")
    static let silenceSecondaryAudioHintNotification = Notification.Name("mock.secondary")
    static let routeChangeNotification = Notification.Name("mock.route")
    private static let instance = AVAudioSession()
    static func sharedInstance() -> AVAudioSession { instance }
    private let lock = NSLock()
    private var storedCategory: Category = .playback
    private var storedMode: Mode = .default
    private var storedOptions: CategoryOptions = []
    private var storedActive = false
    private var failActive = false
    private var activationGate: DispatchSemaphore?
    private var entered = false
    var category: Category { lock.withLock { storedCategory } }
    var mode: Mode { lock.withLock { storedMode } }
    var categoryOptions: CategoryOptions { lock.withLock { storedOptions } }
    var isActive: Bool { lock.withLock { storedActive } }
    var gateEntered: Bool { lock.withLock { entered } }
    var secondaryAudioShouldBeSilencedHint = false
    var recordPermission: RecordPermission = .granted
    var permissionRequests = 0
    func requestRecordPermission(_ callback: (Bool) -> Void) {
        permissionRequests += 1
        callback(recordPermission == .granted)
    }
    func failNextActivation() { lock.withLock { failActive = true } }
    func blockNextActivation(_ gate: DispatchSemaphore) {
        lock.withLock { activationGate = gate; entered = false }
    }
    func setCategory(_ category: Category, mode: Mode, options: CategoryOptions) throws {
        EventLog.shared.append("category:\(category.rawValue):\(mode.rawValue):\(options.rawValue)")
        lock.withLock { storedCategory = category; storedMode = mode; storedOptions = options }
    }
    func setActive(_ value: Bool, options: CategoryOptions = []) throws {
        let gate = lock.withLock { () -> DispatchSemaphore? in
            guard value else { return nil }
            let result = activationGate
            activationGate = nil
            if result != nil { entered = true }
            return result
        }
        gate?.wait()
        let fail = lock.withLock { () -> Bool in
            guard value, failActive else { return false }
            failActive = false
            return true
        }
        if fail { throw NSError(domain: "MockAudioSession", code: 1) }
        lock.withLock { storedActive = value }
        EventLog.shared.append("active:\(value)")
    }
}
let AVAudioSessionInterruptionTypeKey = "mock.interruption.type"
let AVAudioSessionSilenceSecondaryAudioHintTypeKey = "mock.secondary.type"
final class AVAudioApplication {
    static let shared = AVAudioApplication()
    var recordPermission: AVAudioSession.RecordPermission = .granted
    var permissionRequests = 0
    static func requestRecordPermission() async -> Bool {
        shared.permissionRequests += 1
        return shared.recordPermission == .granted
    }
}
struct AVAudioTime {}
struct AVAudioFormat {
    var channelCount: UInt32
    var sampleRate: Double
}
final class AVAudioPCMBuffer {
    var frameLength: UInt32 = 0
    var floatChannelData: UnsafePointer<UnsafeMutablePointer<Float>>? { nil }
}
enum MockFault {
    static var installException = false
    static var recognitionException = false
    static var bridgeFailed = false
    static var engineStartError = false
}
func noff_try_objc(_ body: () -> Void) -> Bool {
    body()
    let success = !MockFault.bridgeFailed
    MockFault.bridgeFailed = false
    return success
}
final class AVAudioInputNode {
    var format = AVAudioFormat(channelCount: 1, sampleRate: 16000)
    var hasTap = false
    func inputFormat(forBus: Int) -> AVAudioFormat { format }
    func outputFormat(forBus: Int) -> AVAudioFormat { format }
    func removeTap(onBus: Int) { hasTap = false }
    func installTap(onBus: Int, bufferSize: Int, format: AVAudioFormat?,
                    block: @escaping (AVAudioPCMBuffer, AVAudioTime) -> Void) {
        hasTap = true
        if MockFault.installException {
            MockFault.installException = false
            MockFault.bridgeFailed = true
        }
    }
}
final class AVAudioEngine {
    static var latest: AVAudioEngine?
    let inputNode = AVAudioInputNode()
    var isRunning = false
    init() { Self.latest = self }
    func prepare() {}
    func start() throws {
        if MockFault.engineStartError {
            MockFault.engineStartError = false
            throw NSError(domain: "MockEngine", code: 2)
        }
        isRunning = true
    }
    func stop() { isRunning = false }
}

enum SFSpeechRecognizerAuthorizationStatus: Equatable { case authorized, denied, notDetermined }
struct SFTranscription { let formattedString: String }
struct SFSpeechRecognitionResult {
    let bestTranscription: SFTranscription
    let isFinal: Bool
}
final class SFSpeechAudioBufferRecognitionRequest {
    var shouldReportPartialResults = false
    var requiresOnDeviceRecognition = false
    var ended = false
    func append(_ buffer: AVAudioPCMBuffer) {}
    func endAudio() { ended = true }
}
final class SFSpeechRecognitionTask {
    let callback: (SFSpeechRecognitionResult?, Error?) -> Void
    var cancelled = false
    init(_ callback: @escaping (SFSpeechRecognitionResult?, Error?) -> Void) {
        self.callback = callback
    }
    func cancel() { cancelled = true }
    // Intentionally permits callbacks after cancel, to exercise generation guards.
    func deliver(_ text: String, final: Bool = false) {
        callback(SFSpeechRecognitionResult(bestTranscription: SFTranscription(formattedString: text),
                                          isFinal: final), nil)
    }
}
final class SFSpeechRecognizer {
    static var authorization: SFSpeechRecognizerAuthorizationStatus = .authorized
    static var permissionRequests = 0
    static var tasks: [SFSpeechRecognitionTask] = []
    static var available = true
    var isAvailable: Bool { Self.available }
    var supportsOnDeviceRecognition = true
    init?(locale: Locale) { if locale.identifier == "zz-invalid" { return nil } }
    static func supportedLocales() -> Set<Locale> {
        [Locale(identifier: "en-US"), Locale(identifier: "zh-CN"), Locale(identifier: "fr-FR")]
    }
    static func authorizationStatus() -> SFSpeechRecognizerAuthorizationStatus { authorization }
    static func requestAuthorization(_ callback: (SFSpeechRecognizerAuthorizationStatus) -> Void) {
        permissionRequests += 1
        callback(authorization)
    }
    func recognitionTask(with request: SFSpeechAudioBufferRecognitionRequest,
                         resultHandler: @escaping (SFSpeechRecognitionResult?, Error?) -> Void)
        -> SFSpeechRecognitionTask {
        let task = SFSpeechRecognitionTask(resultHandler)
        Self.tasks.append(task)
        if MockFault.recognitionException {
            MockFault.recognitionException = false
            MockFault.bridgeFailed = true
        }
        return task
    }
}
