// Synthetic config/model/transport only. No credential APIs or URLSession.
struct ProviderInstance: Sendable {
    enum CredentialType: Sendable { case apiKey, oauth }
    let id: String
    var isEnabled = true
    var root = "https://quota.invalid"
    var credentialType = CredentialType.apiKey
    var providerType = ProviderType.openAI
    var isOpenCodeChannel = false
}
@MainActor final class ProviderConfigStore {
    static let shared = ProviderConfigStore()
    var values: [String: ProviderInstance] = [:]
    func instance(for id: String) -> ProviderInstance? { values[id] }
}
// Remaining synthetic transport dependencies; production factories below.
enum ProviderType: Sendable {
    case anthropic, gemini, openAI, openRouter, openAIResponses, xAI, kimiCode
    case antigravity, githubCopilot, workBuddy, traeCN, unsupported
}
enum ThinkingLevel: Int, Comparable, Sendable {
    case off, high
    static func < (a: Self, b: Self) -> Bool { a.rawValue < b.rawValue }
}
struct LLMModel: Sendable {
    var id = "synthetic-model"
    var catalogMaxThinkingLevel: ThinkingLevel { .high }
}
struct ModelEntry: Sendable {
    let providerInstanceId: String
    var id: String { providerInstanceId }
    var model = LLMModel()
    var overrides = "synthetic"
}
struct AgentMessage {}
struct AgentToolDefinition {}
struct ToolCallMetadata: Sendable { let thoughtSignature: String? }
enum AgentBlockStart { case text }
enum AgentStopReason { case endTurn }
enum AgentStreamEvent {
    case textDelta(String), thinkingDelta(String), responseModel(String), usage(Int)
    case contentBlockStart(AgentBlockStart), done(stopReason: AgentStopReason)
    case toolCallComplete(id: String, name: String, args: [String: String], metadata: ToolCallMetadata?)
}
enum LLMError: Error {
    case invalidAPIKey(detail: String), cancelled, rateLimited
    case networkError(Error), decodingError(Error), unknown(Error?)
    case providerError(message: String), transientError(message: String, statusCode: Int? = nil)
}
struct FixtureLogger { func error(_ value: String) {} }
let logger = FixtureLogger()
struct LLMMessage {
    enum Role { case user, assistant }
    var role: Role
    var content: String
}
struct LLMResponse { let text: String }
enum LLMStreamChunk { case text(String), finished }
enum SyntheticResult { case text(String) }
protocol LLMProvider: AnyObject {
    var key: String { get }
    var model: LLMModel { get }
    func sendMessage(messages: [LLMMessage], systemPrompt: String?, maxTokens: Int, temperature: Double?) async throws -> LLMResponse
    func streamMessage(messages: [LLMMessage], systemPrompt: String?, maxTokens: Int, temperature: Double?) async throws -> AsyncThrowingStream<LLMStreamChunk, Error>
}
enum ConsumptionScenario: Sendable {
    case success, failOpen, failStream, held(FixtureGate), partial(FixtureGate), delayed(FixtureGate)
}
actor ConsumptionPlan {
    static let shared = ConsumptionPlan()
    var scenarios: [String: ConsumptionScenario] = [:]
    var sends: [String] = []
    var nextActiveGate: FixtureGate?
    func set(_ key: String, _ scenario: ConsumptionScenario) { scenarios[key] = scenario }
    func begin(_ key: String) -> ConsumptionScenario {
        sends.append(key)
        return scenarios.removeValue(forKey: key) ?? .success
    }
    func sent(_ key: String) -> Int { sends.filter { $0 == key }.count }
    func armActive(_ gate: FixtureGate) { nextActiveGate = gate }
    func takeActive() -> FixtureGate? { defer { nextActiveGate = nil }; return nextActiveGate }
}
func syntheticAgentStream(_ key: String) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
    let scenario = await ConsumptionPlan.shared.begin(key)
    if case .failOpen = scenario { throw LLMError.providerError(message: "synthetic open failure") }
    return AsyncThrowingStream { continuation in
        let worker = Task {
            switch scenario {
            case .held(let gate): await gate.wait()
            case .partial(let gate):
                continuation.yield(.textDelta("partial"))
                continuation.yield(.done(stopReason: .endTurn))
                await gate.wait()
            case .delayed(let gate): await ConsumptionPlan.shared.armActive(gate)
            default: break
            }
            if case .failStream = scenario {
                continuation.finish(throwing: LLMError.providerError(message: "synthetic stream failure")); return
            }
            continuation.yield(.textDelta("hello"))
            continuation.yield(.done(stopReason: .endTurn))
            continuation.finish()
        }
        continuation.onTermination = { _ in worker.cancel() }
    }
}
class SyntheticLLMProvider: LLMProvider, @unchecked Sendable {
    let key: String
    let model: LLMModel
    init(apiKey: String, model: LLMModel) { key = apiKey; self.model = model }
    func sendMessage(messages: [LLMMessage], systemPrompt: String?, maxTokens: Int, temperature: Double?) async throws -> LLMResponse {
        let scenario = await ConsumptionPlan.shared.begin(key)
        switch scenario {
        case .failOpen, .failStream: throw LLMError.providerError(message: "synthetic send failure")
        case .held(let gate), .partial(let gate): await gate.wait()
        default: break
        }
        return LLMResponse(text: "hello")
    }
    func streamMessage(messages: [LLMMessage], systemPrompt: String?, maxTokens: Int, temperature: Double?) async throws -> AsyncThrowingStream<LLMStreamChunk, Error> {
        let stream = try await syntheticAgentStream(key)
        return AsyncThrowingStream { continuation in
            let worker = Task {
                do {
                    for try await event in stream {
                        switch event {
                        case .textDelta(let text): continuation.yield(.text(text))
                        case .done: continuation.yield(.finished)
                        default: break
                        }
                    }
                    continuation.finish()
                } catch { continuation.finish(throwing: error) }
            }
            continuation.onTermination = { _ in worker.cancel() }
        }
    }
}
final class OpenAIProvider: SyntheticLLMProvider, @unchecked Sendable {}
final class AnthropicProvider: SyntheticLLMProvider, @unchecked Sendable {}
final class GeminiProvider: SyntheticLLMProvider, @unchecked Sendable {}
final class SubscriptionLLMProvider: SyntheticLLMProvider, @unchecked Sendable {
    init(instance: ProviderInstance, model: LLMModel, resolveSessionId: @escaping @Sendable () -> String?, overrides: String) {
        super.init(apiKey: "synthetic-oauth", model: model)
    }
}
class SyntheticAgentProvider: AgentProvider, @unchecked Sendable {
    let provider: SyntheticLLMProvider
    var name: String { "Synthetic" }
    var model: LLMModel { provider.model }
    var defaultMaxTokens: Int { 128 }
    init(provider: SyntheticLLMProvider) { self.provider = provider }
    func streamAgentMessageClamped(messages: [AgentMessage], systemPrompt: String?, tools: [AgentToolDefinition], maxTokens: Int, thinkingLevel: ThinkingLevel) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        try await syntheticAgentStream(provider.key)
    }
}
final class AnthropicAgentProvider: SyntheticAgentProvider, @unchecked Sendable {}
final class OpenAIAgentProvider: SyntheticAgentProvider, @unchecked Sendable {}
final class GeminiAgentProvider: SyntheticAgentProvider, @unchecked Sendable {
    var signatures: [String: ToolCallMetadata] = [:]
    func restoreToolCallMetadata(_ values: [String: ToolCallMetadata]) { signatures.merge(values) { _, new in new } }
    func recordToolCallMetadata(id: String, metadata: ToolCallMetadata) { signatures[id] = metadata }
}
final class AntigravityAgentProvider: SyntheticAgentProvider, @unchecked Sendable {
    func restoreToolCallMetadata(_ values: [String: ToolCallMetadata]) {}
}
final class SubscriptionAgentProvider: SyntheticAgentProvider, @unchecked Sendable {
    init(instance: ProviderInstance, model: LLMModel, resolveSessionId: @escaping @Sendable () -> String?, overrides: String) {
        super.init(provider: SyntheticLLMProvider(apiKey: "synthetic-oauth", model: model))
    }
}
enum OpenCodeChannel {
    @MainActor static func attach(to: OpenAIProvider, resolveSessionId: @escaping @Sendable () -> String?) {}
}

struct SyntheticMedia { enum Kind { case image }; let type = Kind.image; let data = Data("image".utf8) }
extension LLMResponse { var mediaAttachments: [SyntheticMedia] { [SyntheticMedia()] } }
extension SyntheticResult { static func image(_ value: Data) -> SyntheticResult { .text("image") } }
enum QuickTestError: Error { case unsupported(String), noOutput(String) }
struct SyntheticRawSpec { var endpoint: String? = nil; var method = "POST"; var headers: [String: String] = [:] }
struct SyntheticRawResult { let status: Int }
extension OpenAIProvider {
    func generateImage(prompt: String, n: Int, size: String, quality: String?) async throws -> LLMResponse {
        try await sendMessage(messages: [], systemPrompt: nil, maxTokens: 128, temperature: nil)
    }
    func rawPassthroughRequest(endpoint: String?, method: String, headers: [String: String], bodyObject: [String: Any]?) async throws -> SyntheticRawResult {
        _ = try await sendMessage(messages: [], systemPrompt: nil, maxTokens: 128, temperature: nil)
        return SyntheticRawResult(status: endpoint?.contains("fail") == true ? 500 : 200)
    }
}
