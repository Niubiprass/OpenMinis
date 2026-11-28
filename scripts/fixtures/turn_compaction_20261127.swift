// Adapters are synthetic; the wrapper, parser, history and budget above are
// extracted verbatim from production. No URLSession/network or real settings.
enum TestRole: Sendable { case user, assistant }
struct AgentMessage: Sendable { let role: TestRole }
struct AgentToolDefinition: Sendable {}
enum ThinkingLevel: Sendable { case off }
enum AgentStopReason: Sendable { case endTurn, toolUse, maxTokens, refusal }
enum AgentBlockStart: Sendable { case text, toolUse(id: String, name: String) }
enum AgentStreamEvent: Sendable {
    case textDelta(String), thinkingDelta(String), done(AgentStopReason)
    case contentBlockStart(AgentBlockStart), toolInputDelta, toolCallComplete
}
enum ProviderChatAPIError: Error { case scopeChanged }
enum LLMError: Error { case transientError(message: String, statusCode: Int?) }
enum ProviderChatAPIFormat { case chatCompletions, responses }
struct ChatContext { let scope: String; let initial: ProviderChatAPIFormat }
struct ProviderChatAPIHistory {
    static let shared = Self()
    func cached(_ scope: String) -> ProviderChatAPIFormat? { nil }
}
final class FakeProvider: @unchecked Sendable {
    var turnCompactionContext: ProviderTurnContext?
    var chatAPIContext: ChatContext?
    var usesChatCompletionsAPI = true
}
struct FakeError: Error {}
struct FixtureLogger: Sendable { func info(_ message: String) {} }
struct AppLogger: Sendable { init(category: String) {} ; func error(_ message: String) {} ; func info(_ message: String) {} }
let logger = FixtureLogger()
enum Plan: Sendable {
    case reject(Int, Bool), normal, empty, thinking, tool, truncated, fail, preludeReject
}
final class OpenAIAgentProvider: @unchecked Sendable {
    let provider = FakeProvider()
    var plans: [Plan]
    var opened = 0
    var endpoints: [String] = []
    var counts: [Int] = []
    init(_ plans: [Plan]) { self.plans = plans }
    /* ACTUAL_WRAPPER */
    private func streamAgentMessageUncompacted(messages: [AgentMessage], systemPrompt: String?, tools: [AgentToolDefinition], maxTokens: Int, thinkingLevel: ThinkingLevel) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        try open(messages, endpoint: "ordinary")
    }
    private func streamResponsesAPI(messages: [AgentMessage], systemPrompt: String?, tools: [AgentToolDefinition], maxTokens: Int, thinkingLevel: ThinkingLevel) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        try open(messages, endpoint: "responses")
    }
    private func streamChatCompletions(messages: [AgentMessage], systemPrompt: String?, tools: [AgentToolDefinition], maxTokens: Int, thinkingLevel: ThinkingLevel) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        try open(messages, endpoint: "chat")
    }
    private func open(_ messages: [AgentMessage], endpoint: String) throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        opened += 1; endpoints.append(endpoint); counts.append(ProviderTurnRun.count(messages))
        let plan: Plan = plans.isEmpty ? .fail : plans.removeFirst()
        if case .reject(let limit, let responses) = plan {
            var error = ProviderTurnLimitRejection(limit: limit); error.responses = responses; throw error
        }
        return AsyncThrowingStream { continuation in
            switch plan {
            case .normal:
                continuation.yield(.textDelta("ok")); continuation.yield(.done(.endTurn)); continuation.finish()
            case .empty: continuation.yield(.done(.endTurn)); continuation.finish()
            case .thinking:
                continuation.yield(.thinkingDelta("thought")); continuation.yield(.done(.endTurn)); continuation.finish()
            case .tool: continuation.yield(.contentBlockStart(.toolUse(id: "t", name: "fake"))); continuation.yield(.done(.toolUse)); continuation.finish()
            case .truncated: continuation.yield(.textDelta("partial")); continuation.yield(.done(.maxTokens)); continuation.yield(.done(.endTurn)); continuation.finish()
            case .preludeReject:
                continuation.yield(.thinkingDelta("")); continuation.finish(throwing: ProviderTurnLimitRejection(limit: 100))
            default: continuation.finish(throwing: FakeError())
            }
        }
    }
}

@MainActor
@main struct TurnFixture {
    static var cases = 0
    static func check(_ value: @autoclosure () -> Bool, _ label: String) {
        precondition(value(), label); cases += 1
    }
    static func messages(_ count: Int) -> [AgentMessage] {
        (0..<count).map { _ in AgentMessage(role: .assistant) } + [AgentMessage(role: .user)]
    }
    static func drain(_ agent: OpenAIAgentProvider, count: Int, run: ProviderTurnRun?) async -> Error? {
        do {
            try await ProviderTurnRun.$current.withValue(run) {
                let upstream = try await agent.streamAgentMessageClamped(messages: messages(count), systemPrompt: "system", tools: [], maxTokens: 128, thinkingLevel: .off)
                let stream = try await ProviderTurnOpenGate.prime(upstream)
                for try await _ in stream {}
            }
            return nil
        } catch { return error }
    }
    static func main() async {
        let body = #"{"error":{"code":"session_turn_limit_exceeded","type":"invalid_request_error","message":"当前会话模型已回复 100 轮，达到上限。This conversation has reached 100 model turns."}}"#
        check(ProviderTurnLimitRejection.parse(status: 400, body: body)?.limit == 100, "exact actual bilingual error")
        for status in [200,401,403,429,500] { check(ProviderTurnLimitRejection.parse(status: status, body: body) == nil, "status rejected") }
        for text in ["bad json", #"{"error":{"code":"invalid_request","message":"session_turn_limit_exceeded 100"}}"#, #"{"code":"session_turn_limit_exceeded","limit":100}"#] {
            check(ProviderTurnLimitRejection.parse(status: 400, body: text) == nil, "structure/code rejected")
        }
        check(ProviderTurnLimitRejection.parse(status: 400, body: body + String(repeating: " ", count: 17000)) == nil, "bounded")
        let unknown = #"{"error":{"code":"session_turn_limit_exceeded","message":"limit reached"}}"#
        check(ProviderTurnLimitRejection.parse(status: 400, body: unknown)?.limit == nil, "unknown is not 100")
        let budget = ProviderTurnRun(enabled: { true }, compact: { _ in nil })
        check(budget.takeRecovery(), "first budget"); check(!budget.takeRecovery(), "second budget denied")
        check(budget.takeProactive("a"), "first proactive"); check(!budget.takeProactive("a"), "repeat proactive denied")
        let base = UUID().uuidString
        let suite = "TurnFixture." + base
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        let store = ProviderTurnHistory(defaults: defaults)
        let scope = String(repeating: "a", count: 64)
        let observation = store.observe(scope: scope, limit: 100, count: 100)
        check(store.row(scope)?.trigger == nil, "observed not proactive")
        store.verify(observation, reducedCount: 3)
        check(store.row(scope)?.trigger == 90, "verified proactive margin")
        let newer = store.observe(scope: scope, limit: 100, count: 90)
        store.verify(observation, reducedCount: 3)
        check(store.row(scope)?.verified == false, "old verification revoked")
        store.verify(newer, reducedCount: 90)
        check(store.row(scope)?.verified == false, "same size cannot verify")
        for count in 0..<150 { _ = store.observe(scope: String(format: "%064x", count), limit: nil, count: count) }
        check(store.row(scope) == nil, "bounded eviction")
        for plan in [Plan.normal, .empty, .thinking, .tool, .truncated, .fail, .reject(100,false), .preludeReject] {
            let agent = OpenAIAgentProvider([.reject(100,false), plan])
            let context = ProviderTurnContext(seed: base + String(cases), entryId: "e", validate: { true })
            agent.provider.turnCompactionContext = context
            var compacts = 0
            let run = ProviderTurnRun(enabled: { true }, compact: { id in
                check(id == "e", "entry forwarded"); compacts += 1; return messages(3)
            })
            let error = await drain(agent, count: 100, run: run)
            check(compacts == 1, "one compact only")
            check(agent.opened == 2, "at most two same-key HTTP opens")
            check(agent.endpoints == ["ordinary", "chat"], "actual rejecting chat endpoint")
            let row = ProviderTurnHistory.shared.row(context.scope(responses: false))
            if case .normal = plan {
                check(error == nil && row?.verified == true, "only completed nonempty verifies")
            } else {
                check(row?.verified == false, "empty/thinking/tool/truncated/error cannot verify")
            }
        }
        do {
            let agent = OpenAIAgentProvider([.reject(100,true), .normal])
            agent.provider.turnCompactionContext = ProviderTurnContext(seed: base + "responses", entryId: nil, validate: { true })
            let run = ProviderTurnRun(enabled: { true }, compact: { _ in messages(2) })
            let error = await drain(agent, count: 100, run: run)
            check(error == nil && agent.endpoints == ["ordinary", "responses"], "actual rejecting responses endpoint")
        }
        do {
            let agent = OpenAIAgentProvider([.preludeReject, .normal])
            agent.provider.turnCompactionContext = ProviderTurnContext(seed: base + "exposed", entryId: nil, validate: { true })
            var compacts = 0
            let run = ProviderTurnRun(enabled: { true }, compact: { _ in compacts += 1; return messages(2) })
            let error = await drain(agent, count: 100, run: run)
            check(error != nil && agent.opened == 1 && compacts == 0, "any event prohibits replay")
        }
        do {
            let agent = OpenAIAgentProvider([.reject(100,false), .normal])
            agent.provider.turnCompactionContext = ProviderTurnContext(seed: base + "off", entryId: nil, validate: { true })
            var compacts = 0
            let run = ProviderTurnRun(enabled: { false }, compact: { _ in compacts += 1; return messages(2) })
            let error = await drain(agent, count: 100, run: run)
            check(error != nil && agent.opened == 1 && compacts == 0, "switch off ordinary path")
        }
        do {
            let agent = OpenAIAgentProvider([.reject(100,false), .normal])
            var valid = true
            agent.provider.turnCompactionContext = ProviderTurnContext(seed: base + "invalidated", entryId: nil, validate: { valid })
            let run = ProviderTurnRun(enabled: { true }, compact: { _ in valid = false; return messages(2) })
            let error = await drain(agent, count: 100, run: run)
            check(error != nil && agent.opened == 1, "config invalidated during compact no resend")
        }
        do {
            let agent = OpenAIAgentProvider([.reject(100,false), .normal])
            agent.provider.turnCompactionContext = ProviderTurnContext(seed: base + "no-shrink", entryId: nil, validate: { true })
            let run = ProviderTurnRun(enabled: { true }, compact: { _ in messages(100) })
            let error = await drain(agent, count: 100, run: run)
            check(error != nil && agent.opened == 1, "nonshrinking compact not resent")
        }
        do {
            let agent = OpenAIAgentProvider([.normal])
            let context = ProviderTurnContext(seed: base + "preempt", entryId: nil, validate: { true })
            agent.provider.turnCompactionContext = context
            let row = ProviderTurnHistory.shared.observe(scope: context.scope(responses: false), limit: 100, count: 100)
            ProviderTurnHistory.shared.verify(row, reducedCount: 3)
            var compacts = 0
            let run = ProviderTurnRun(enabled: { true }, compact: { _ in compacts += 1; return messages(3) })
            let error = await drain(agent, count: 90, run: run)
            check(error == nil && agent.counts == [3] && compacts == 1, "verified scope anticipates before HTTP")
        }
        do {
            let agent = OpenAIAgentProvider([.reject(100,false), .normal])
            agent.provider.turnCompactionContext = ProviderTurnContext(seed: base + "cancel", entryId: nil, validate: { true })
            let entered = AsyncStream<Void>.makeStream()
            let release = AsyncStream<Void>.makeStream()
            let run = ProviderTurnRun(enabled: { !Task.isCancelled }, compact: { _ in
                entered.continuation.yield(())
                for await _ in release.stream { break }
                return messages(2)
            })
            let task = Task { await drain(agent, count: 100, run: run) }
            for await _ in entered.stream { break }
            task.cancel(); release.continuation.finish(); entered.continuation.finish()
            let error = await task.value
            check(error != nil && agent.opened == 1, "cancel while compact no resend")
        }
        do {
            let run = ProviderTurnRun(enabled: { true }, compact: { _ in
                try? await Task.sleep(nanoseconds: 60_000_000)
                return [AgentMessage(role: .user)]
            })
            do {
                let stream = try await ProviderTurnRun.$current.withValue(run) {
                    let upstream = AsyncThrowingStream<AgentStreamEvent, Error> { c in
                        let t = Task {
                            _ = await run.performCompaction(nil)
                            if !Task.isCancelled { c.yield(.done(.endTurn)); c.finish() }
                        }
                        c.onTermination = { _ in t.cancel() }
                    }
                    return try await ProviderTurnOpenGate.prime(upstream, firstOutputTimeout: 0.02, summaryTimeout: 0.3)
                }
                for try await _ in stream {}
                check(!run.isCompacting(), "long summary excluded from first-output budget")
            } catch { check(false, "summary prematurely timed out") }
            run.noteCompactionFailure(.summaryFailed, error: NSError(domain: "synthetic", code: 7))
            let rejection = run.compactionFailure(ProviderTurnLimitRejection(limit: 100))
            check(rejection.stop == .summaryFailed && rejection.causeCode == 7, "summary cause preserved")
            check(rejection.errorDescription?.contains("生成摘要失败") == true, "summary stage visible")
        }
        print("NATIVE TurnFixture PASS checks=\(cases); actual production wrapper/parser/store/budget, synthetic adapters")
    }
}
