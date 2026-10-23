import Foundation

// MARK: - Cross-Provider Helpers

/// Sanitize a tool-use ID so it is valid for all providers.
/// Anthropic requires `^[a-zA-Z0-9_-]+$`; OpenAI Responses API can produce
/// IDs containing `|` (e.g. `call_xxx|fc_yyy`).  Replace any disallowed
/// character with `-`.
func sanitizeToolId(_ id: String) -> String {
    let allowed = CharacterSet.alphanumerics.union(CharacterSet(charactersIn: "_-"))
    return String(id.unicodeScalars.map { allowed.contains($0) ? Character($0) : Character("-") })
}

// MARK: - Canonical Tool Definitions

/// Canonical tool definition used by the agent loop — provider-agnostic.
struct AgentToolDefinition {
    let name: String
    let description: String
    let parameters: [String: AgentToolParam]
    let required: [String]
    /// Explicit property generation order. When provided, providers that support it
    /// (e.g. Gemini) will instruct the model to emit parameters in this order.
    let propertyOrdering: [String]?

    init(name: String, description: String, parameters: [String: AgentToolParam], required: [String], propertyOrdering: [String]? = nil) {
        self.name = name
        self.description = description
        self.parameters = parameters
        self.required = required
        self.propertyOrdering = propertyOrdering
    }
}

struct AgentToolParam {
    let type: AgentParamType
    let description: String
    let enumValues: [String]?

    init(type: AgentParamType, description: String, enumValues: [String]? = nil) {
        self.type = type
        self.description = description
        self.enumValues = enumValues
    }
}

enum AgentParamType: String {
    case string
    case integer
    case boolean
    /// [T-115-ask-card] JSON array (e.g. ask_user's `questions`).
    case array
}

// MARK: - Agent Messages

/// A single content part in agent messages — provider-agnostic.
enum AgentContentPart: @unchecked Sendable {
    case text(String)
    /// `isOffloadedArgument` — [T-offload-stub-system-reminder issue #374]. True
    /// when the context offloader replaced this call's `content` argument with a
    /// pruned-argument notice because the real payload was moved to
    /// `/var/minis/offloads/…`. The `.toolResult` case has carried
    /// `isOffloadReadback` since GH#343 for the same reason: the scanner cannot
    /// tell its own output from new material by reading the text.
    ///
    /// Provenance, not presentation: the notice text is also detectable via
    /// `AIChatViewModel.isOffloadedStub`, but that is a string test on a payload
    /// the model can imitate, whereas this flag is set only by the offloader.
    /// Defaults to `false` so every existing construction site and all history
    /// persisted before this change decode unchanged.
    case toolUse(id: String, name: String, input: [String: Any], isOffloadedArgument: Bool = false)
    /// `imageLinuxPath` — iSH-visible linux path the image bytes were
    /// persisted to (e.g. `/var/minis/browser/<sid>/screenshot_*.jpg`,
    /// `/var/minis/attachments/uploads/*`). Carried so the request-level
    /// image budget can emit a re-fetchable text placeholder when the
    /// cumulative payload would exceed the 25MB cap. Defaults to nil for
    /// backward compatibility with existing call sites and persisted
    /// history.
    ///
    /// `isOffloadReadback` — [T-offload-readback-loop] GH#343. True when this
    /// result is the content of a file the offloader itself wrote, fetched back
    /// by `file_read` against `/var/minis/offloads/…`.
    ///
    /// It exists because the two places that decide what to offload cannot tell
    /// that from the text: the candidate scanner skipped anything starting with
    /// `[CONTEXT OFFLOADED]`, and a read-BACK carries the original payload with
    /// no such prefix, so it re-entered as a brand-new candidate and was written
    /// to a second file, whose stub the model then read, and so on. Reproduced
    /// on an iPhone 11: context oscillated 123K→108K→124K→109K chars across
    /// four rounds while `bigInCtx` stayed at 6 — no net progress, one new file
    /// per lap.
    ///
    /// A flag rather than more text-sniffing: the marker travels with the part
    /// from the moment the read happens, so neither path has to re-derive it
    /// from a string whose format can change (`file_read` prepends its own
    /// `[path | N bytes | …]` header, which is exactly what a prefix check
    /// would trip over).
    ///
    /// Defaults to false so every existing call site and all persisted history
    /// decode unchanged.
    case toolResult(id: String, name: String, content: String, isError: Bool, imageData: Data? = nil, imageMimeType: String? = nil, pageURL: String? = nil, imageLinuxPath: String? = nil, isOffloadReadback: Bool = false)
    /// `linuxPath` — same semantics as above. Used for user attachments
    /// and read_image results that don't ride through .toolResult.
    case imageData(data: Data, mimeType: String, linuxPath: String? = nil)
}

/// Native reasoning payload captured from the provider response, used to
/// preserve chain-of-thought across multi-turn requests. Lives **in memory
/// only** (not persisted) — restart loses encrypted content, which is
/// acceptable because the visible text + tool history is unchanged.
///
/// Each echo is tagged with the producing model so cross-model switches
/// (e.g. gpt-5.5 → deepseek) can be detected and the encrypted payload
/// stripped — encrypted_content is model-specific and meaningless to a
/// different model family.
struct ReasoningEcho: @unchecked Sendable {
    /// Stable provider family tag; matches `OpenAIAgentProvider.responsesAPIProviderKind`
    /// etc. Different families never share schemas.
    let providerKind: String
    /// Concrete model id (e.g. "gpt-5.5", "o3-mini"). Encrypted payloads are
    /// only safe to echo back to the **same** model id within the same
    /// provider family.
    let modelId: String
    /// [T-responses-reasoning-inherit issue #368] The upstream that minted these
    /// items (`OpenAIAgentProvider.reasoningUpstreamIdentity` — the custom base
    /// URL, or "openai-official"). `encrypted_content` is decryptable only by
    /// that endpoint, so this — not `modelId` — is what decides whether a replay
    /// is safe.
    ///
    /// Defaulted so every existing construction site and all in-flight history
    /// keep compiling; an echo with no recorded upstream is replayed on the
    /// model-id match alone, i.e. the pre-#368 behaviour.
    var upstreamIdentity: String? = nil
    /// Reasoning items captured in original emission order — must be
    /// re-inserted into the next request's input array in the same order
    /// (Responses API rejects out-of-order reasoning items).
    let items: [Item]

    enum Item: @unchecked Sendable {
        /// OpenAI Responses API reasoning item.
        case openaiReasoning(id: String, encryptedContent: String?, summary: [String])
    }
}

// MARK: - ReasoningEcho persistence [T-responses-echo-persist]

extension ReasoningEcho {
    /// Wire form written to `messages.reasoning_echo`.
    ///
    /// `encryptedContent` is intentionally absent: it is large, endpoint-bound,
    /// and cannot be decrypted by any endpoint but the one that minted it, so
    /// persisting it across a restart would cost bytes for a payload we must
    /// drop the moment the upstream differs. What DOES need to survive is the
    /// server-minted `id` — the only value that may legally appear as
    /// `reasoning.id` in a later request — plus `upstreamIdentity`, without
    /// which the replay gate cannot tell a same-relay resume from a hop.
    private struct Wire: Codable {
        struct Item: Codable {
            let id: String
            let summary: [String]
        }
        let providerKind: String
        let modelId: String
        let upstreamIdentity: String?
        let items: [Item]
    }

    /// JSON for persistence, or nil when there is nothing worth storing.
    var persistableJSON: String? {
        let wire = Wire(
            providerKind: providerKind,
            modelId: modelId,
            upstreamIdentity: upstreamIdentity,
            items: items.compactMap { item in
                if case .openaiReasoning(let id, _, let summary) = item {
                    return Wire.Item(id: id, summary: summary)
                }
                return nil
            }
        )
        guard !wire.items.isEmpty,
              let data = try? JSONEncoder().encode(wire) else { return nil }
        return String(data: data, encoding: .utf8)
    }

    /// Rebuild from `persistableJSON`. Items come back with no
    /// `encryptedContent`, which is the documented degradation above.
    init?(persistedJSON json: String?) {
        guard let json, let data = json.data(using: .utf8),
              let wire = try? JSONDecoder().decode(Wire.self, from: data),
              !wire.items.isEmpty else { return nil }
        self.init(
            providerKind: wire.providerKind,
            modelId: wire.modelId,
            upstreamIdentity: wire.upstreamIdentity,
            items: wire.items.map { .openaiReasoning(id: $0.id, encryptedContent: nil, summary: $0.summary) }
        )
    }
}

/// A message in the agent conversation.
struct AgentMessage: @unchecked Sendable {
    enum Role: String, Sendable { case user, assistant }
    let role: Role
    var parts: [AgentContentPart]
    /// True when this assistant message was interrupted mid-stream (e.g. network drop).
    /// tool_use blocks inside may have incomplete/empty inputs (partialJson never finished).
    /// Placeholder tool_results must NOT be injected for interrupted messages, because
    /// sending a tool_result for a tool_use with empty input causes API 400 errors.
    var isInterrupted: Bool = false
    /// Opaque reasoning content from thinking models (e.g. Kimi, DeepSeek, QwQ).
    /// Must be echoed back on assistant messages for multi-turn conversations.
    var reasoningContent: String?
    /// Native reasoning payload (Responses-API encrypted items, etc.). In
    /// memory only — see `ReasoningEcho` for cross-model isolation rules.
    var reasoningEcho: ReasoningEcho?
    /// DB message id (RawMessage.id) once this message has been persisted.
    /// Populated by persistAgentMessage after buildRawMessage succeeds, or by
    /// loadSession on restore. Used by compact logic to resolve marker boundaries
    /// via id instead of sort_order. nil while the message is still in-flight
    /// (e.g. mid-stream before persist).
    var dbMessageId: String? = nil
}

// MARK: - Stream Events

/// Stream events from an agent provider — unified across Anthropic/Gemini.
enum AgentStreamEvent: @unchecked Sendable {
    /// A new content block started (text or tool).
    case contentBlockStart(AgentBlockStart)
    /// Incremental text delta.
    case textDelta(String)
    /// Tool input update (for streaming JSON preview).
    /// `accumulated` is the full JSON so far, `name` is the tool name.
    case toolInputDelta(name: String, accumulated: String)
    /// Tool call completed with final parsed arguments.
    case toolCallComplete(id: String, name: String, args: [String: Any], metadata: ToolCallMetadata?)
    /// Usage stats.
    case usage(LLMUsage)
    /// [T-agent-model-identity] The model name the API REPORTED for this
    /// response (Anthropic `message.model`, OpenAI chunk / `response.model`,
    /// Gemini `modelVersion`). Emitted once per response where the provider
    /// exposes it; consumers must tolerate its absence.
    case responseModel(String)
    /// Real-time thinking content delta for live UI display.
    case thinkingDelta(String)
    /// Accumulated reasoning content from thinking models (opaque, must be echoed back).
    case reasoningContent(String)
    /// Native reasoning payload (e.g. OpenAI Responses-API encrypted items)
    /// for in-memory multi-turn replay. Cross-model isolation rules live on
    /// `ReasoningEcho`.
    case reasoningEcho(ReasoningEcho)
    /// Response finished.
    case done(stopReason: AgentStopReason)
}

enum AgentBlockStart: Sendable {
    case text
    case toolUse(id: String, name: String)
}

enum AgentStopReason: Sendable {
    case endTurn
    case toolUse
    case maxTokens
    /// Anthropic safety classifier declined the request (HTTP 200 + `stop_reason: "refusal"`,
    /// input tokens billed, empty `content`). Distinct from `.endTurn` so the agent loop can
    /// surface an actionable message instead of a generic "empty response" and skip the
    /// pointless transient-retry path (a refusal is deterministic, not transient).
    /// Fires as a false-positive on Fable 5 for benign turns carrying the large agentic
    /// system prompt + tool set (OAuth path). See [T-ios-fable5-empty-response].
    case refusal
}

/// Provider-specific metadata attached to a tool call (e.g. Gemini thought signatures).
struct ToolCallMetadata: @unchecked Sendable {
    let thoughtSignature: String?
}

// MARK: - Protocol

/// Protocol for providers that support the agent loop (streaming + tool use).
protocol AgentProvider {
    var name: String { get }
    var model: LLMModel { get }
    /// Default max output tokens for this provider.
    var defaultMaxTokens: Int { get }

    /// Provider-specific streaming implementation. Receives a thinking level
    /// that has already been clamped to the model's effective max by the
    /// protocol extension — implementations should NOT re-clamp.
    func streamAgentMessageClamped(
        messages: [AgentMessage],
        systemPrompt: String?,
        tools: [AgentToolDefinition],
        maxTokens: Int,
        thinkingLevel: ThinkingLevel
    ) async throws -> AsyncThrowingStream<AgentStreamEvent, Error>
}

extension AgentProvider {
    func streamAgentMessage(
        messages: [AgentMessage],
        systemPrompt: String?,
        tools: [AgentToolDefinition],
        maxTokens: Int,
        thinkingLevel: ThinkingLevel
    ) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        let clamped = min(thinkingLevel, model.catalogMaxThinkingLevel)
        return try await streamAgentMessageClamped(
            messages: messages, systemPrompt: systemPrompt,
            tools: tools, maxTokens: maxTokens, thinkingLevel: clamped
        )
    }

    /// Default: thinking off.
    func streamAgentMessage(
        messages: [AgentMessage],
        systemPrompt: String?,
        tools: [AgentToolDefinition],
        maxTokens: Int
    ) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        try await streamAgentMessage(messages: messages, systemPrompt: systemPrompt, tools: tools, maxTokens: maxTokens, thinkingLevel: .off)
    }
}


// MARK: - Request-scoped credential failover

/// Keeps the same model, headers and history; changes only the API credential.
/// Never print builder arguments or the lease (both contain secrets).
final class MultiKeyAgentProvider: AgentProvider, @unchecked Sendable {
    typealias Builder = @MainActor (String) async -> any AgentProvider
    private let instanceId: String
    private let baseline: any AgentProvider
    private let builder: Builder
    private let lock = NSLock()
    private var metadata: [String: ToolCallMetadata] = [:]
    private var resumeExclusions: Set<String> = []
    var name: String { baseline.name }
    var model: LLMModel { baseline.model }
    var defaultMaxTokens: Int { baseline.defaultMaxTokens }
    var isAnthropic: Bool { baseline is AnthropicAgentProvider }

    init(instanceId: String, baseline: any AgentProvider, builder: @escaping Builder) {
        self.instanceId = instanceId; self.baseline = baseline; self.builder = builder
    }

    func restoreToolCallMetadata(_ values: [String: ToolCallMetadata]) {
        lock.lock(); defer { lock.unlock() }
        metadata.merge(values) { _, new in new }
    }
    private func metadataSnapshot() -> [String: ToolCallMetadata] {
        lock.lock(); defer { lock.unlock() }; return metadata
    }
    private func takeResumeExclusions() -> Set<String> {
        lock.lock(); defer { lock.unlock() }
        let ids = resumeExclusions; resumeExclusions.removeAll(); return ids
    }
    private func excludeOnResume(_ id: String) {
        lock.lock(); defer { lock.unlock() }; resumeExclusions.insert(id)
    }

    func streamAgentMessageClamped(messages: [AgentMessage], systemPrompt: String?,
                                   tools: [AgentToolDefinition], maxTokens: Int,
                                   thinkingLevel: ThinkingLevel) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        try Task.checkCancellation()
        let manager = ProviderMultiKeyManager.shared
        let active = manager.isActive(for: instanceId)
        let keyCount = active ? manager.keys(for: instanceId).count : 0
        // Priority mode gets two same-key retries before failover. The budget
        // includes those retry slots so a three-key ring cannot exhaust the
        // loop before the later keys are reached.
        let priorityRetries = manager.strategy(for: instanceId) == .priority ? 2 : 0
        let budget = active
            ? (keyCount + 1) + keyCount * priorityRetries
            : 1
        let initialExclusions = takeResumeExclusions()
        return AsyncThrowingStream { continuation in
            let worker = Task {
                var attempted = initialExclusions
                var attemptedSecrets = Set<String>()
                var lastError: Error?
                var retryLease: ProviderKeyLease?
                var sameKeyRetries = 0
                for _ in 0..<budget {
                    do { try Task.checkCancellation() }
                    catch { continuation.finish(throwing: error); return }
                    let lease: ProviderKeyLease
                    let isSameKeyRetry: Bool
                    if let pending = retryLease {
                        lease = pending
                        retryLease = nil
                        isSameKeyRetry = true
                    } else {
                        guard let next = manager.lease(for: instanceId, excluding: attempted) else { break }
                        lease = next
                        attempted.insert(lease.id)
                        sameKeyRetries = 0
                        isSameKeyRetry = false
                    }
                    if !isSameKeyRetry {
                        // A retry deliberately reuses a secret already seen in
                        // this request; only a newly leased key is deduped.
                        guard attemptedSecrets.insert(lease.key).inserted else { continue }
                    }
                    var exposed = false
                    var pending: [AgentStreamEvent] = []
                    do {
                        let provider = await builder(lease.key)
                        let signatures = metadataSnapshot()
                        await MainActor.run {
                            if let gemini = provider as? GeminiAgentProvider {
                                gemini.restoreToolCallMetadata(signatures)
                            } else if let antigravity = provider as? AntigravityAgentProvider {
                                antigravity.restoreToolCallMetadata(signatures)
                            }
                        }
                        let stream = try await provider.streamAgentMessageClamped(
                            messages: messages, systemPrompt: systemPrompt, tools: tools,
                            maxTokens: maxTokens, thinkingLevel: thinkingLevel)
                        for try await event in stream {
                            try Task.checkCancellation()
                            // Keep non-visible prelude local until the first substantive event.
                            // A rejected stream may announce its model or an empty block first.
                            let prelude: Bool
                            switch event {
                            case .responseModel, .usage, .contentBlockStart(.text): prelude = true
                            case .textDelta(let text), .thinkingDelta(let text): prelude = text.isEmpty
                            default: prelude = false
                            }
                            if !exposed && prelude {
                                // Bound malformed preludes; never buffer unbounded provider output.
                                if pending.count < 16 { pending.append(event) }
                                continue
                            }
                            if !exposed {
                                for item in pending { continuation.yield(item) }
                                pending.removeAll(); exposed = true
                            }
                            if case .toolCallComplete(let id, _, _, let info) = event, let info {
                                restoreToolCallMetadata([id: info])
                                await MainActor.run {
                                    (provider as? GeminiAgentProvider)?.recordToolCallMetadata(id: id, metadata: info)
                                }
                            }
                            continuation.yield(event)
                        }
                        try Task.checkCancellation()
                        for item in pending { continuation.yield(item) }
                        if manager.isActive(for: instanceId) { manager.recordSuccess(lease: lease, for: instanceId) }
                        continuation.finish(); return
                    } catch {
                        if Task.isCancelled { continuation.finish(throwing: CancellationError()); return }
                        let kind = MultiKeyFailureKind.classify(error)
                        if manager.isActive(for: instanceId) { manager.recordFailure(lease: lease, kind: kind, for: instanceId) }
                        guard kind.mayTryAnotherKey else { continuation.finish(throwing: error); return }
                        lastError = error
                        if exposed {
                            // Existing agent-loop recovery clears ONLY its uncommitted tail
                            // and re-dispatches. Never append a second answer/tool stream here.
                            excludeOnResume(lease.id)
                            continuation.finish(throwing: error); return
                        }
                        // Priority: keep the same key for a bounded number of
                        // retries before treating it as broken. Other strategies
                        // keep their existing one-failure-per-key behavior.
                        if priorityRetries > 0, sameKeyRetries < priorityRetries {
                            sameKeyRetries += 1
                            // New startedAt so a success after a failed retry
                            // clears the parked/error state instead of being
                            // ignored as older than the failure.
                            retryLease = ProviderKeyLease(id: lease.id, key: lease.key,
                                                          startedAt: Date())
                            await Task.yield()
                            continue
                        }
                        sameKeyRetries = 0
                        // No content or tool escaped: another key may safely serve this request.
                        await Task.yield()
                    }
                }
                continuation.finish(throwing: lastError ?? LLMError.providerError(
                    message: "本供应商没有可用的 Key；所有 Key 已停用或暂时不可用，请检查余额、权限或稍后重试。"))
            }
            continuation.onTermination = { _ in worker.cancel() }
        }
    }
}
