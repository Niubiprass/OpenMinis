import CoreFoundation
import Darwin
import Foundation

/// Tiny local control messages, not voice or names. SpringBoard alone confirms
/// the current screen/pet/response; a saved switch or missed notification is
/// never treated as proof that the companion is ready.
@MainActor
final class MiniSightWakeRemote {
    static let requestNote = "com.openminis.minisight.namewake.request"
    static let responseNote = "com.openminis.minisight.namewake.response"
    static let stateNote = "com.openminis.minisight.namewake.state"
    struct State: Equatable, Sendable {
        let clock: Double
        let host: String
        let revision: String
        let unlocked: Bool
        let allowed: Bool
        let busy: Bool
        func isFresh(now: Double, revision: String) -> Bool {
            self.revision == revision && clock.isFinite && clock >= 0 &&
                now.isFinite && now >= clock && now - clock <= 4
        }
    }
    struct Reply: Equatable, Sendable {
        let clock: Double
        let host: String
        let revision: String
        let token: String
        let state: String
        let responseGeneration: UInt
        let voiceGeneration: UInt
        let reason: String
    }
    var onState: ((State?) -> Void)?
    var onReply: ((Reply) -> Void)?
    private let queue = DispatchQueue(label: "com.openminis.minisight.namewake.files", qos: .utility)
    private let mailbox = Mailbox()
    private var observer: UnsafeMutablePointer<UInt8>?
    private var inFlight = false
    private var again = false
    private var revision = 0
    private var lastReply: Reply?
    private let directory: URL = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
        .appendingPathComponent("MiniSight", isDirectory: true)

    /// Cross-queue request fencing. Stop/replace invalidates queued writes before
    /// they publish a note; newest cancel overrides an older queued hit/ready.
    private final class Mailbox: @unchecked Sendable {
        private let lock = NSLock()
        private var generation = 0
        func next() -> Int { lock.lock(); defer { lock.unlock() }; generation &+= 1; return generation }
        func matches(_ value: Int) -> Bool { lock.lock(); defer { lock.unlock() }; return value == generation }
    }
    func install() {
        guard observer == nil else { return }
        let pointer = UnsafeMutablePointer<UInt8>.allocate(capacity: 1); observer = pointer
        for note in [Self.stateNote, Self.responseNote] {
            CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(), pointer,
                { _, _, _, _, _ in
                    // No UI/audio work on the Darwin callback thread.
                    Task { @MainActor in MiniSightWakeController.shared.pollRemoteState() }
                }, note as CFString, nil, .deliverImmediately)
        }
    }
    func poll() {
        install()
        if inFlight { again = true; return }
        inFlight = true; revision &+= 1
        let ticket = revision, directory = self.directory
        queue.async { [weak self] in
            let state = Self.read(directory, "namewake-state.json").flatMap(Self.decodeState)
            let reply = Self.read(directory, "namewake-response.json").flatMap(Self.decodeReply)
            Task { @MainActor [weak self] in
                guard let self, self.revision == ticket else { return }
                self.inFlight = false
                self.onState?(state)
                if let reply, reply != self.lastReply { self.lastReply = reply; self.onReply?(reply) }
                if self.again { self.again = false; self.poll() }
            }
        }
    }
    func post(action: String, token: UUID, state: State, completion: ((Bool) -> Void)? = nil) {
        guard ["hit", "ready", "cancel"].contains(action) else { completion?(false); return }
        let generation = mailbox.next(), mailbox = self.mailbox, directory = self.directory
        let object: [String: Any] = ["schema": 1, "clock": ProcessInfo.processInfo.systemUptime,
            "host": state.host, "revision": state.revision, "token": token.uuidString, "action": action]
        queue.async {
            guard mailbox.matches(generation) else { return }
            let success = Self.write(directory, "namewake-request.json", value: object)
            guard mailbox.matches(generation) else { return }
            if success {
                CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
                    CFNotificationName(Self.requestNote as CFString), nil, nil, true)
            }
            if let completion { Task { @MainActor in completion(success) } }
        }
    }
    func invalidate() {
        _ = mailbox.next()
        revision &+= 1; inFlight = false; again = false; lastReply = nil
    }
    nonisolated static func decodeState(_ value: [String: Any]) -> State? {
        guard value.count == 7, schema(value), let clock = clock(value), let host = uuid(value["host"]),
              let revision = string(value["revision"], limit: 128),
              let unlocked = boolean(value["unlocked"]), let allowed = boolean(value["allowed"]),
              let busy = boolean(value["busy"]) else { return nil }
        return State(clock: clock, host: host, revision: revision, unlocked: unlocked, allowed: allowed, busy: busy)
    }
    nonisolated static func decodeReply(_ value: [String: Any]) -> Reply? {
        guard value.count == 9, schema(value), let clock = clock(value), let host = uuid(value["host"]),
              let token = uuid(value["token"]), let revision = string(value["revision"], limit: 128),
              let state = string(value["state"], limit: 32),
              ["accepted", "voice_requested", "cancelled", "declined"].contains(state),
              let response = unsigned(value["responseGeneration"]), let voice = unsigned(value["voiceGeneration"]),
              let reason = string(value["reason"], limit: 96, allowEmpty: true) else { return nil }
        return Reply(clock: clock, host: host, revision: revision, token: token, state: state,
                     responseGeneration: response, voiceGeneration: voice, reason: reason)
    }
    nonisolated private static func schema(_ value: [String: Any]) -> Bool { unsigned(value["schema"]) == 1 }
    nonisolated private static func clock(_ value: [String: Any]) -> Double? {
        guard let number = value["clock"] as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        let value = number.doubleValue
        return value.isFinite && value >= 0 ? value : nil
    }
    nonisolated private static func boolean(_ value: Any?) -> Bool? {
        guard let number = value as? NSNumber else { return nil }
        let type = CFGetTypeID(number)
        if type == CFBooleanGetTypeID() { return number.boolValue }
        // Installed schema-1 companions boxed an Objective-C && as int. Accept
        // only exact integer CFNumber 0/1 during this rolling local repair.
        // No strings, truthiness, floats (even 0.0/1.0), or truncation/overflow.
        guard type == CFNumberGetTypeID() else { return nil }
        let legacy = unsafeBitCast(number, to: CFNumber.self) // verified toll-free type
        guard !CFNumberIsFloatType(legacy) else { return nil }
        if number.compare(NSNumber(value: 0)) == .orderedSame { return false }
        if number.compare(NSNumber(value: 1)) == .orderedSame { return true }
        return nil
    }
    nonisolated private static func unsigned(_ value: Any?) -> UInt? {
        guard let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() else { return nil }
        let text = number.stringValue
        guard !text.isEmpty, text.utf8.allSatisfy({ (48...57).contains($0) }) else { return nil }
        return UInt(text)
    }
    nonisolated private static func string(_ value: Any?, limit: Int, allowEmpty: Bool = false) -> String? {
        guard let text = value as? String, (allowEmpty || !text.isEmpty), text.utf8.count <= limit,
              text.unicodeScalars.allSatisfy({ !CharacterSet.controlCharacters.contains($0) }) else { return nil }
        return text
    }
    nonisolated private static func uuid(_ value: Any?) -> String? {
        guard let text = string(value, limit: 36), let uuid = UUID(uuidString: text), uuid.uuidString == text else { return nil }
        return text
    }
    nonisolated private static func read(_ directory: URL, _ name: String) -> [String: Any]? {
        guard let data = readData(directory, name),
              let value = try? JSONSerialization.jsonObject(with: data) as? [String: Any] else { return nil }
        return value
    }
    nonisolated private static func readData(_ directory: URL, _ name: String) -> Data? {
        let dir = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard dir >= 0 else { return nil }; defer { close(dir) }
        let fd = openat(dir, name, O_RDONLY | O_NOFOLLOW | O_NONBLOCK | O_CLOEXEC)
        guard fd >= 0 else { return nil }; defer { close(fd) }
        var info = stat()
        guard fstat(fd, &info) == 0, (info.st_mode & mode_t(S_IFMT)) == mode_t(S_IFREG),
              info.st_size > 0, info.st_size <= 8192 else { return nil }
        var data = Data(count: 8193)
        let count: Int? = data.withUnsafeMutableBytes { bytes in
            var total = 0
            while total < bytes.count {
                let n = Darwin.read(fd, bytes.baseAddress!.advanced(by: total), bytes.count - total)
                if n < 0 && errno == EINTR { continue }
                if n < 0 { return nil }
                if n == 0 { return total }
                total += n
            }
            return nil
        }
        guard let count, count <= 8192, count == info.st_size else { return nil }
        data.count = count; return data
    }
    nonisolated private static func write(_ directory: URL, _ name: String, value: [String: Any]) -> Bool {
        guard let data = try? JSONSerialization.data(withJSONObject: value), data.count <= 8192 else { return false }
        do { try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true) } catch { return false }
        let dir = open(directory.path, O_RDONLY | O_DIRECTORY | O_NOFOLLOW | O_CLOEXEC)
        guard dir >= 0 else { return false }; defer { close(dir) }
        let temporary = name + "." + UUID().uuidString + ".tmp"
        let fd = openat(dir, temporary, O_WRONLY | O_CREAT | O_EXCL | O_NOFOLLOW | O_CLOEXEC, mode_t(0o600))
        guard fd >= 0 else { return false }
        let success = data.withUnsafeBytes { bytes -> Bool in
            var total = 0
            while total < bytes.count {
                let n = Darwin.write(fd, bytes.baseAddress!.advanced(by: total), bytes.count - total)
                if n < 0 && errno == EINTR { continue }
                if n <= 0 { return false }
                total += n
            }
            return true
        }
        close(fd)
        let renamed = success && renameat(dir, temporary, dir, name) == 0
        unlinkat(dir, temporary, 0)
        return renamed && readData(directory, name) == data
    }
    deinit {
        if let observer {
            CFNotificationCenterRemoveEveryObserver(CFNotificationCenterGetDarwinNotifyCenter(), observer)
            observer.deallocate()
        }
    }
}
