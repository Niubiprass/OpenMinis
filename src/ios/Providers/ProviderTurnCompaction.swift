import Foundation
import CryptoKit

// A non-2xx, structured server rejection, before any parser/stream is opened.
// Never infer a retry from a generic 400, rate limit or a displayed substring.
struct ProviderTurnLimitRejection: LocalizedError, Sendable {
    let limit: Int?
    var responses = false
    var confirmedServerRejection = true
    enum Stop: String, Sendable {
        case notAttempted = "尚未完成压缩恢复"
        case unavailable = "没有可安全压缩的历史，或会话状态已变化"
        case summaryFailed = "生成摘要失败"
        case skipped = "压缩未执行（正在压缩或选区不可用）"
        case cancelled = "压缩已取消"
        case commitFailed = "摘要生成后未能安全保存或应用"
        case notReduced = "压缩后有效回复数未减少，未重发"
        case scopeChanged = "压缩期间会话或供应商配置已变化，未重发"
        case retryRejected = "压缩后重发仍被服务商轮数限制拒绝"
        case retryFailed = "压缩后重发失败"
        case retryIncomplete = "压缩后回复未正常完整结束"
        case firstOutputTimeout = "等待恢复后的首个回复超时"
        case summaryTimeout = "压缩摘要等待超时"
    }
    var stop: Stop = .notAttempted
    var causeCode: Int? = nil
    func stopped(_ reason: Stop, code: Int? = nil) -> Self {
        var result = self; result.stop = reason; result.causeCode = code; return result
    }
    var errorDescription: String? {
        let detail = causeCode.map { "（错误码 \($0)）" } ?? ""
        let prefix = confirmedServerRejection ? "服务商明确拒绝：会话回复轮数已达上限。" : "自动恢复已停止："
        return "\(prefix)\(stop.rawValue)\(detail)，已停止；不会反复压缩或轮换 Key。"
    }
    static func parse(status: Int, body: String) -> Self? {
        guard [400,409,422].contains(status), body.utf8.count <= 16_384,
              let data = body.data(using: .utf8),
              let root = (try? JSONSerialization.jsonObject(with: data)) as? [String:Any],
              let error = root["error"] as? [String:Any],
              [error["code"], error["type"]].contains(where: { ($0 as? String) == "session_turn_limit_exceeded" }) else { return nil }
        let message = error["message"] as? String ?? ""
        // The symbolic code permits recovery; only explicit count phrases or
        // a structured limit permit storing a numeric limit. No universal 100.
        var limit: Int?
        if let number = error["limit"] as? Int, (2...1_000_000).contains(number) { limit = number }
        if limit == nil {
            let patterns = [#"(?i)(?:replied|responded)\s+(\d{1,6})\s+turns"#,
                            #"(?i)(?:limit|maximum|max)\s*(?:of|is|:)?\s*(\d{1,6})\s*turns"#,
                            #"(?:已回复|已响应|上限为|最多)\s*(\d{1,6})\s*轮"#]
            for pattern in patterns {
                guard let regex = try? NSRegularExpression(pattern: pattern),
                      let match = regex.firstMatch(in: message, range: NSRange(message.startIndex..., in: message)),
                      let range = Range(match.range(at: 1), in: message),
                      let number = Int(message[range]), (2...1_000_000).contains(number) else { continue }
                limit = number; break
            }
        }
        return Self(limit: limit)
    }
}

struct ProviderTurnObservation: Codable, Sendable {
    let scope: String // SHA256(provider + config + credential + model + actual endpoint)
    let limit: Int?
    let rejectedCount: Int // outbound assistant rows: proxy, NOT server accounting
    let observationId: UUID
    var verified: Bool
    let date: Date
    var trigger: Int? {
        guard verified, rejectedCount >= 6 else { return nil }
        let boundary = min(rejectedCount, limit ?? rejectedCount)
        guard boundary >= 6 else { return nil }
        return boundary - max(2, boundary / 10)
    }
}

// App-local bounded history. Persist only fingerprints and numeric evidence,
// never the response body, key, URL, prompt, local chat ID or server identity.
final class ProviderTurnHistory: @unchecked Sendable {
    static let shared = ProviderTurnHistory()
    private let lock = NSLock()
    private let writes = DispatchQueue(label: "minis.turn-limit.writes", qos: .utility)
    private let defaults: UserDefaults
    private let key = "provider.turn-limit.observations.v1"
    private var rows: [String:ProviderTurnObservation] = [:]
    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        if let data = defaults.data(forKey: key), data.count <= 128*1024,
           let values = try? JSONDecoder().decode([ProviderTurnObservation].self, from: data) {
            for row in values.sorted(by: { $0.date > $1.date }).prefix(128)
                where row.scope.count == 64 && (0...1_000_000).contains(row.rejectedCount) &&
                      (row.limit == nil || (2...1_000_000).contains(row.limit!)) { rows[row.scope] = row }
        }
    }
    func row(_ scope: String) -> ProviderTurnObservation? {
        lock.lock(); defer { lock.unlock() }; return rows[scope]
    }
    @discardableResult
    func observe(scope: String, limit: Int?, count: Int) -> ProviderTurnObservation {
        lock.lock(); defer { lock.unlock() }
        // A new real rejection revokes prior verification immediately.
        let row = ProviderTurnObservation(scope: scope, limit: limit, rejectedCount: min(max(0,count),1_000_000), observationId: UUID(), verified: false, date: Date())
        rows[scope] = row; enqueueLocked(); return row
    }
    @discardableResult
    func verify(_ observation: ProviderTurnObservation, reducedCount: Int) -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !Task.isCancelled, reducedCount < observation.rejectedCount,
              rows[observation.scope]?.observationId == observation.observationId else { return false }
        var row = observation; row.verified = true; rows[row.scope] = row; enqueueLocked()
        return true
    }
    private func enqueueLocked() {
        if rows.count > 128 {
            for row in rows.values.sorted(by: { $0.date > $1.date }).dropFirst(128) { rows[row.scope] = nil }
        }
        let snapshot = Array(rows.values), defaults = self.defaults, key = self.key
        writes.async {
            guard let data = try? JSONEncoder().encode(snapshot) else { return }
            defaults.set(data, forKey: key)
            // Read-back failure is not reported as persisted success.
            guard defaults.data(forKey: key) == data else {
                AppLogger(category: "TurnCompact").error("learning persistence readback failed")
                return
            }
        }
    }
}

// Bound to ONE agent run and inherited by nested unstructured workers. The
// compaction request is explicitly run with current=nil to prevent recursion.
final class ProviderTurnRun: @unchecked Sendable {
    @TaskLocal static var current: ProviderTurnRun?
    @TaskLocal static var isRecoverySummary = false
    let compact: @MainActor (String?) async -> [AgentMessage]?
    let enabled: @MainActor () -> Bool
    private let lock = NSLock()
    private var recoverySpent = false
    private var proactiveSpent = Set<String>()
    private var compacting = false
    private var compactionStarted: TimeInterval?
    private var compactionElapsed: TimeInterval = 0
    func compactionTime() -> TimeInterval {
        lock.lock(); defer { lock.unlock() }
        return compactionElapsed + (compactionStarted.map { max(0, ProcessInfo.processInfo.systemUptime - $0) } ?? 0)
    }
    private var compactFailure: ProviderTurnLimitRejection.Stop = .unavailable
    private var compactCause: Int?
    func noteCompactionFailure(_ stop: ProviderTurnLimitRejection.Stop, error: Error? = nil) {
        lock.lock(); defer { lock.unlock() }
        compactFailure = stop; compactCause = error.map { ($0 as NSError).code }
    }
    func compactionFailure(_ rejection: ProviderTurnLimitRejection) -> ProviderTurnLimitRejection {
        lock.lock(); defer { lock.unlock() }
        return rejection.stopped(compactFailure, code: compactCause)
    }
    func isCompacting() -> Bool {
        lock.lock(); defer { lock.unlock() }; return compacting
    }
    private func setCompacting(_ value: Bool) {
        lock.lock(); defer { lock.unlock() }
        compacting = value
        if value {
            compactionStarted = ProcessInfo.processInfo.systemUptime
            compactFailure = .unavailable; compactCause = nil
        } else if let started = compactionStarted {
            compactionElapsed += max(0, ProcessInfo.processInfo.systemUptime - started)
            compactionStarted = nil
        }
    }
    @MainActor
    func performCompaction(_ entryId: String?) async -> [AgentMessage]? {
        setCompacting(true); defer { setCompacting(false) }
        return await compact(entryId)
    }
    init(enabled: @escaping @MainActor () -> Bool, compact: @escaping @MainActor (String?) async -> [AgentMessage]?) {
        self.enabled = enabled; self.compact = compact
    }
    func takeRecovery() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !recoverySpent else { return false }; recoverySpent = true; return true
    }
    func hasSpentRecovery() -> Bool {
        lock.lock(); defer { lock.unlock() }; return recoverySpent
    }
    func takeProactive(_ scope: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return proactiveSpent.insert(scope).inserted
    }
    static func count(_ messages: [AgentMessage]) -> Int { messages.filter { $0.role == .assistant }.count }
}

final class ProviderTurnContext: @unchecked Sendable {
    let seed: String
    let entryId: String?
    let validate: @MainActor () async -> Bool
    let confirm: @MainActor () -> Bool
    init(seed: String, entryId: String?, confirm: @escaping @MainActor () -> Bool = { true },
         validate: @escaping @MainActor () async -> Bool) {
        self.seed = seed; self.entryId = entryId; self.validate = validate; self.confirm = confirm
    }
    @MainActor
    func observe(_ rejection: ProviderTurnLimitRejection, count: Int, run: ProviderTurnRun) async -> ProviderTurnObservation? {
        guard await validate(), confirm(), run.enabled(), !Task.isCancelled else { return nil }
        return ProviderTurnHistory.shared.observe(scope: scope(responses: rejection.responses), limit: rejection.limit, count: count)
    }
    @MainActor
    func verify(_ observation: ProviderTurnObservation, count: Int, run: ProviderTurnRun) async -> Bool {
        guard await validate(), confirm(), run.enabled(), !Task.isCancelled else { return false }
        return ProviderTurnHistory.shared.verify(observation, reducedCount: count)
    }
    func scope(responses: Bool) -> String {
        let material = seed + (responses ? "|responses" : "|chat/completions")
        return SHA256.hash(data: Data(material.utf8)).map { String(format: "%02x", $0) }.joined()
    }
}

@MainActor
enum ProviderTurnCompaction {
    static func configure(_ provider: OpenAIProvider, instance: ProviderInstance, entry: ModelEntry?) {
        guard [.openAI,.openAIResponses].contains(instance.providerType), instance.credentialType == .apiKey,
              provider.perRequestHeaders == nil, case .apiKey(let key) = provider.authMode,
              let seed = ProviderChatAPI.configuration(instance: instance, provider: provider) else { return }
        let authRevision = ProviderConfigStore.shared.authRevision
        let encoder = JSONEncoder(); encoder.outputFormatting = [.sortedKeys]
        let overrides = entry.flatMap { try? encoder.encode($0.overrides) } ?? Data()
        let scopedSeed = ProviderChatAPI.fingerprint(seed + String(decoding: overrides, as: UTF8.self))
        let matches: @MainActor () -> Bool = {
            guard ProviderConfigStore.shared.authRevision == authRevision,
                  let current = ProviderConfigStore.shared.instance(for: instance.id), current.isEnabled,
                  ProviderChatAPI.instanceConfiguration(current) == ProviderChatAPI.instanceConfiguration(instance) else { return false }
            if let entry, ProviderConfigStore.shared.entry(for: entry.id) != entry { return false }
            return true
        }
        provider.turnCompactionContext = ProviderTurnContext(seed: scopedSeed, entryId: entry?.id, confirm: matches) {
            guard matches() else { return false }
            let manager = ProviderMultiKeyManager.shared
            let credentialMatches: Bool
            if await manager.isActiveAsync(for: instance.id) {
                credentialMatches = (await manager.keysAsync(for: instance.id)).contains { $0.key == key && $0.isEnabled && $0.status != .disabled }
            } else {
                credentialMatches = (await manager.primaryKeyAsync(for: instance.id) ?? "") == key
            }
            return credentialMatches && matches() && !Task.isCancelled
        }
    }
}

// Do not hand a stream to the fixed-index UI consumer while recovery can
// still insert a compact divider. First event/error closes that recovery window.
final class ProviderTurnOpenGate: @unchecked Sendable {
    private let lock = NSLock()
    private var ready = false
    private var waiter: CheckedContinuation<Void,Never>?
    private var worker: Task<Void,Never>?
    private var cancelled = false
    func install(_ task: Task<Void,Never>) {
        lock.lock(); worker = task; let cancel = cancelled; lock.unlock()
        if cancel { task.cancel() }
    }
    func wait() async {
        await withCheckedContinuation { continuation in
            lock.lock()
            if ready { lock.unlock(); continuation.resume() }
            else { waiter = continuation; lock.unlock() }
        }
    }
    func open() {
        lock.lock(); ready = true; let continuation = waiter; waiter = nil; lock.unlock()
        continuation?.resume()
    }
    func cancel() {
        lock.lock(); cancelled = true; let task = worker; lock.unlock()
        task?.cancel(); open()
    }
    static func prime(_ upstream: AsyncThrowingStream<AgentStreamEvent,Error>,
                      firstOutputTimeout: TimeInterval = 120, summaryTimeout: TimeInterval = 900) async throws -> AsyncThrowingStream<AgentStreamEvent,Error> {
        let gate = ProviderTurnOpenGate()
        let run = ProviderTurnRun.current
        let result = AsyncThrowingStream<AgentStreamEvent,Error> { continuation in
            let worker = Task {
                // Summary generation has its own bounded watchdog. Do not
                // charge its time to the ordinary first-output allowance.
                let timeout = Task {
                    let started = ProcessInfo.processInfo.systemUptime
                    let initialSummaryTime = run?.compactionTime() ?? 0
                    let tick = UInt64(max(0.001, min(0.1, min(firstOutputTimeout, summaryTimeout) / 4)) * 1_000_000_000)
                    while !Task.isCancelled {
                        do { try await Task.sleep(nanoseconds: tick); try Task.checkCancellation() }
                        catch { return }
                        let elapsed = max(0, ProcessInfo.processInfo.systemUptime - started)
                        let summary = max(0, (run?.compactionTime() ?? 0) - initialSummaryTime)
                        let summaryExpired = summary >= summaryTimeout
                        guard summaryExpired || max(0, elapsed - summary) >= firstOutputTimeout else { continue }
                        if run?.hasSpentRecovery() == true {
                            continuation.finish(throwing: ProviderTurnLimitRejection(limit: nil, confirmedServerRejection: false).stopped(summaryExpired ? .summaryTimeout : .firstOutputTimeout))
                        } else {
                            continuation.finish(throwing: LLMError.transientError(message: "等待模型首个回复超时，请重试。", statusCode: nil))
                        }
                        gate.cancel(); return
                    }
                }
                defer { timeout.cancel(); gate.open() }
                do {
                    for try await event in upstream {
                        try Task.checkCancellation()
                        timeout.cancel(); gate.open()
                        continuation.yield(event)
                    }
                    continuation.finish()
                } catch { continuation.finish(throwing: error) }
            }
            gate.install(worker)
            continuation.onTermination = { _ in worker.cancel() }
        }
        await withTaskCancellationHandler(operation: { await gate.wait() }, onCancel: { gate.cancel() })
        try Task.checkCancellation()
        return result
    }
}
