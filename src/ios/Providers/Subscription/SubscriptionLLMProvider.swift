import Foundation
import KWWKAI

/// App adapters only. No KWWKAgent runtime and no tool executor is linked here.
final class SubscriptionLLMProvider: LLMProvider {
    let instance: ProviderInstance
    var model: LLMModel
    let resolveSessionId: @Sendable () -> String?
    let overrides: ModelOverrides
    var name: String { instance.label }

    init(instance: ProviderInstance, model: LLMModel,
         resolveSessionId: @escaping @Sendable () -> String? = { nil },
         overrides: ModelOverrides = ModelOverrides()) {
        self.instance = instance; self.model = model
        self.resolveSessionId = resolveSessionId; self.overrides = overrides
    }

    func streamMessage(messages: [LLMMessage], systemPrompt: String?, maxTokens: Int,
                       temperature: Double?) async throws -> AsyncThrowingStream<LLMStreamChunk, Error> {
        try SubscriptionEndpoints.validate(instance)
        let context = try SubscriptionMessageMapping.plain(messages)
        let engine = SubscriptionStreamEngine(instance: instance, model: model,
            resolveSessionId: resolveSessionId, overrides: overrides)
        let events = engine.stream(messages: context, systemPrompt: systemPrompt, tools: [],
            maxTokens: maxTokens, temperature: temperature, thinkingLevel: .off, plain: true)
        return AsyncThrowingStream { continuation in
            let pump = Task {
                do {
                    for try await event in events {
                        switch event {
                        case .contentBlockStart(.text): continuation.yield(.started)
                        case .textDelta(let delta): continuation.yield(.text(delta))
                        case .usage(let usage): continuation.yield(.usage(usage))
                        case .done(let reason):
                            let raw: String
                            switch reason {
                            case .endTurn: raw = "stop"
                            case .toolUse: raw = "tool_calls"
                            case .maxTokens: raw = "length"
                            case .refusal: raw = "refusal"
                            }
                            continuation.yield(.finished(stopReason: raw))
                        default: break
                        }
                    }
                    continuation.finish()
                } catch { continuation.finish(throwing: SubscriptionFailure.map(error)) }
            }
            continuation.onTermination = { _ in pump.cancel() }
        }
    }

    func sendMessage(messages: [LLMMessage], systemPrompt: String?, maxTokens: Int,
                     temperature: Double?) async throws -> LLMResponse {
        let stream = try await streamMessage(messages: messages, systemPrompt: systemPrompt,
                                             maxTokens: maxTokens, temperature: temperature)
        var text = ""; var reason: String?; var usage: LLMUsage?
        for try await chunk in stream {
            switch chunk {
            case .text(let value): text += value
            case .usage(let value): usage = value
            case .finished(let value): reason = value
            case .started: break
            }
        }
        return LLMResponse(text: text, stopReason: reason, usage: usage)
    }
}

final class SubscriptionAgentProvider: AgentProvider {
    let instance: ProviderInstance
    let model: LLMModel
    let resolveSessionId: @Sendable () -> String?
    let overrides: ModelOverrides
    var name: String { instance.label }
    var defaultMaxTokens: Int { overrides.maxOutputTokens ?? model.maxOutputTokens ?? 16_384 }

    init(instance: ProviderInstance, model: LLMModel,
         resolveSessionId: @escaping @Sendable () -> String? = { nil },
         overrides: ModelOverrides = ModelOverrides()) {
        self.instance = instance; self.model = model
        self.resolveSessionId = resolveSessionId; self.overrides = overrides
    }

    func streamAgentMessageClamped(messages: [AgentMessage], systemPrompt: String?,
                                  tools: [AgentToolDefinition], maxTokens: Int,
                                  thinkingLevel: ThinkingLevel) async throws -> AsyncThrowingStream<AgentStreamEvent, Error> {
        try SubscriptionEndpoints.validate(instance)
        return SubscriptionStreamEngine(instance: instance, model: model,
            resolveSessionId: resolveSessionId, overrides: overrides).stream(
                messages: try SubscriptionMessageMapping.agent(messages, model: model),
                systemPrompt: systemPrompt, tools: try SubscriptionMessageMapping.tools(tools),
                maxTokens: maxTokens, temperature: nil, thinkingLevel: thinkingLevel, plain: false)
    }
}

/// KWWKAI has no assistant-image block. Reject that shape, rather than move
/// the image to another role or silently drop it. User/tool-result images are
/// preserved here and rechecked against the ACCOUNT's live model capability.
enum SubscriptionMessageMapping {
    static func plain(_ messages: [LLMMessage]) throws -> [KWWKAI.Message] {
        try messages.map { message in
            guard message.audios.isEmpty else {
                throw LLMError.providerError(message: "订阅聊天暂不支持音频输入；附件未发送")
            }
            if message.role == .assistant {
                guard message.images.isEmpty else {
                    throw LLMError.providerError(message: "订阅聊天不支持 assistant 图片历史；附件未发送")
                }
                return .assistant(KWWKAI.AssistantMessage(content: [.text(.init(text: message.content))],
                    api: "openai-completions", provider: "", model: ""))
            }
            var blocks: [KWWKAI.UserBlock] = [.text(.init(text: message.content))]
            for image in message.images {
                blocks.append(.image(try imageContent(image.data, image.mimeType)))
            }
            return .user(KWWKAI.UserMessage(content: blocks))
        }
    }

    static func imageContent(_ data: Data, _ mimeType: String) throws -> KWWKAI.ImageContent {
        guard !data.isEmpty, ["image/png", "image/jpeg", "image/gif", "image/webp"].contains(mimeType.lowercased()) else {
            throw LLMError.providerError(message: "不支持或为空的图片附件：\(mimeType)")
        }
        return KWWKAI.ImageContent(data: data.base64EncodedString(), mimeType: mimeType.lowercased())
    }

    static func agent(_ messages: [AgentMessage], model: LLMModel) throws -> [KWWKAI.Message] {
        var output: [KWWKAI.Message] = []
        for message in messages {
            var user: [KWWKAI.UserBlock] = []
            var assistant: [KWWKAI.AssistantBlock] = []
            // The visible interleaved text is portable. encrypted reasoningEcho
            // is deliberately NEVER read or replayed across provider families.
            if message.role == .assistant, let text = message.reasoningContent, !text.isEmpty {
                assistant.append(.thinking(.init(thinking: text, thinkingSignature: "reasoning_content")))
            }
            func flush() {
                if !user.isEmpty { output.append(.user(.init(content: user))); user.removeAll() }
                if !assistant.isEmpty {
                    output.append(.assistant(.init(content: assistant, api: "openai-completions",
                        provider: "", model: model.id, stopReason: message.isInterrupted ? .aborted : .stop)))
                    assistant.removeAll()
                }
            }
            for part in message.parts {
                switch part {
                case .text(let text):
                    if message.role == .user { user.append(.text(.init(text: text))) }
                    else { assistant.append(.text(.init(text: text))) }
                case .imageData(let data, let mime, _):
                    guard message.role == .user else {
                        throw LLMError.providerError(message: "订阅聊天不支持 assistant 图片历史；附件未发送")
                    }
                    user.append(.image(try imageContent(data, mime)))
                case .toolUse(let id, let name, let input, _):
                    guard !id.isEmpty, !name.isEmpty else {
                        throw LLMError.providerError(message: "历史工具调用缺少真实 id/name")
                    }
                    let call = KWWKAI.ToolCall(id: id, name: name, arguments: try SubscriptionJSON.value(input))
                    if message.role == .assistant {
                        assistant.append(.toolCall(call))
                    } else {
                        flush()
                        output.append(.assistant(.init(content: [.toolCall(call)],
                            api: "openai-completions", provider: "", model: model.id,
                            stopReason: message.isInterrupted ? .aborted : .toolUse)))
                    }
                case .toolResult(let id, let name, let content, let isError, let data, let mime, _, _, _):
                    flush()
                    var blocks: [KWWKAI.ToolResultBlock] = [.text(.init(text: content))]
                    if let data { blocks.append(.image(try imageContent(data, mime ?? "image/png"))) }
                    output.append(.toolResult(.init(toolCallId: id, toolName: name, content: blocks, isError: isError)))
                }
            }
            flush()
        }
        return output
    }

    static func tools(_ definitions: [AgentToolDefinition]) throws -> [KWWKAI.Tool] {
        var names = Set<String>()
        return try definitions.map { definition in
            guard definition.name.range(of: #"^[A-Za-z0-9_-]{1,64}$"#, options: .regularExpression) != nil,
                  names.insert(definition.name).inserted else {
                throw LLMError.providerError(message: "订阅工具名必须唯一且符合 [A-Za-z0-9_-]{1,64}：\(definition.name)")
            }
            var properties: [String: KWWKAI.JSONValue] = [:]
            for (name, parameter) in definition.parameters {
                var schema: [String: KWWKAI.JSONValue] = [
                    "type": .string(parameter.type.rawValue), "description": .string(parameter.description)]
                if let values = parameter.enumValues { schema["enum"] = .array(values.map { .string($0) }) }
                if parameter.type == .array { schema["items"] = .object([:]) }
                properties[name] = .object(schema)
            }
            guard definition.required.allSatisfy({ properties[$0] != nil }) else {
                throw LLMError.providerError(message: "工具 schema 的 required 不在 properties 内：\(definition.name)")
            }
            return KWWKAI.Tool(name: definition.name, description: definition.description,
                parameters: .object(["type": .string("object"), "properties": .object(properties),
                    "required": .array(definition.required.map { .string($0) })]))
        }
    }

    static func containsImages(_ messages: [KWWKAI.Message]) -> Bool {
        messages.contains { message in
            switch message {
            case .user(let u): return u.content.contains { if case .image = $0 { return true }; return false }
            case .toolResult(let r): return r.content.contains { if case .image = $0 { return true }; return false }
            default: return false
            }
        }
    }
}

/// Cancellation can race Task creation. A cancelled owner cancels a newly
/// installed pump too; each attempt's handle remains registered until it ends.
private final class SubscriptionPumpLifetime: @unchecked Sendable {
    private let lock = NSLock()
    private var cancelled = false
    private var task: Task<Void, Never>?
    private var handle: KWWKAI.CancellationHandle?
    func install(_ task: Task<Void, Never>) {
        lock.lock(); self.task = task; let stop = cancelled; lock.unlock()
        if stop { task.cancel() }
    }
    func install(_ handle: KWWKAI.CancellationHandle?) {
        lock.lock(); self.handle = handle; let stop = cancelled; lock.unlock()
        if stop { handle?.cancel() }
    }
    func cancel() {
        lock.lock(); cancelled = true; let task = task; let handle = handle; lock.unlock()
        task?.cancel(); handle?.cancel()
    }
}

private struct SubscriptionStreamEngine {
    let instance: ProviderInstance
    let model: LLMModel
    let resolveSessionId: @Sendable () -> String?
    let overrides: ModelOverrides

    func stream(messages: [KWWKAI.Message], systemPrompt: String?, tools: [KWWKAI.Tool],
                maxTokens: Int, temperature: Double?, thinkingLevel: ThinkingLevel,
                plain: Bool) -> AsyncThrowingStream<AgentStreamEvent, Error> {
        let lifetime = SubscriptionPumpLifetime()
        return AsyncThrowingStream { continuation in
            let pump = Task { @MainActor in
                let manager = SubscriptionOAuthManager.shared
                let request: SubscriptionOAuthManager.RequestSnapshot
                do { request = try manager.requestSnapshot(instance: self.instance) }
                catch { continuation.finish(throwing: SubscriptionFailure.map(error)); return }
                let instance = request.instance
                let accounts = request.accounts
                var lastFailure: Error?
                for (accountIndex, snapshot) in accounts.enumerated() {
                // Each original slot is visited at most once. New logins/slots
                // appearing during this request never join its replay roster.
                if accountIndex > 0 {
                    guard let current = ProviderConfigStore.shared.instance(for: instance.id),
                          current.subscriptionAutoFailover else { break }
                    do { try manager.requireCurrent(snapshot) }
                    catch {
                        if Task.isCancelled { continuation.finish(throwing: LLMError.cancelled); return }
                        continue // removed, logged-out or replaced candidate
                    }
                }
                var account = snapshot
                var rejectedAccess: String?
                var yieldedContent = false
                for attempt in 0...1 {
                    let signal = KWWKAI.CancellationHandle()
                    lifetime.install(signal)
                    do {
                        try Task.checkCancellation()
                        try signal.throwIfCancelled()
                        try SubscriptionEndpoints.validate(instance)
                        account = try await manager.requestCredentials(account,
                            forceRefresh: attempt == 1, rejectedAccess: rejectedAccess)
                        let credentials = account.credentials
                        rejectedAccess = credentials.access
                        try SubscriptionEndpoints.validate(credentials)
                        let catalog = try await SubscriptionCatalogCache.shared.catalog(
                            instance: instance, credentials: credentials, cancellation: signal)
                        try manager.requireCurrent(account)
                        try signal.throwIfCancelled()
                        guard var wireModel = catalog.models.first(where: { $0.id == model.id }) else {
                            throw LLMError.providerError(message: "该账号的在线模型目录不包含 \(model.id)，请刷新模型列表")
                        }
                        let hasImages = SubscriptionMessageMapping.containsImages(messages)
                        guard !hasImages || (instance.providerType == .workBuddy && wireModel.input.contains(.image)) else {
                            throw LLMError.providerError(message: "此订阅站点/账号模型仅支持文字；图片未发送（手动能力覆盖不能启用图片）")
                        }
                        let settings = try SubscriptionRequestSettings(instance: instance, overrides: overrides,
                            temperature: temperature, thinkingLevel: thinkingLevel, wireModel: wireModel)
                        if let window = overrides.contextWindow, window > 0 { wireModel.contextWindow = window }
                        // Only WorkBuddy's wire accepts max_tokens. Trae's
                        // source wire has no output-limit control; a user-set
                        // maxOutputTokens is rejected by settings, not discarded.
                        let outputLimit = overrides.maxOutputTokens ?? maxTokens
                        guard outputLimit > 0 else { throw LLMError.providerError(message: "输出 token 限制必须大于零") }
                        let context = KWWKAI.Context(systemPrompt: systemPrompt, messages: messages,
                                                   tools: tools.isEmpty ? nil : tools)
                        let auth: KWWKAI.ResolvedProviderAuth
                        let provider: any KWWKAI.APIProvider
                        if instance.providerType == .workBuddy {
                            auth = KWWKAI.ResolvedProviderAuth(token: credentials.access, scheme: .bearer,
                                headers: KWWKAI.WorkBuddyOAuth.accountHeaders(credentials, site: .china))
                            // Intentionally NOT WorkBuddyProvider: its private
                            // WorkBuddyWire.mendMessages/ChatClient alter words
                            // and retry channel rejections. The strict variant
                            // below uses only public OpenAI encoding/streaming.
                            provider = SubscriptionWorkBuddyProvider(client: SubscriptionRequestHTTPClient(
                                inner: SubscriptionHTTPClient(allowedHosts: SubscriptionEndpoints.workBuddyHosts),
                                settings: settings, kind: .workBuddy, account: account))
                        } else {
                            let trae = TraeCredential(credentials)
                            auth = KWWKAI.ResolvedProviderAuth(scheme: .none,
                                headers: TraeWire.accountHeaders(token: trae.access, userID: trae.userID,
                                    machineID: trae.machineID, deviceID: trae.deviceID))
                            provider = TraeProvider(site: .china, origin: SubscriptionEndpoints.traeOrigin,
                                functions: catalog.functions,
                                client: SubscriptionRequestHTTPClient(
                                    inner: SubscriptionHTTPClient(allowedHosts: SubscriptionEndpoints.traeHosts),
                                    settings: settings, kind: .traeCN, account: account))
                        }
                        var options = KWWKAI.StreamOptions(temperature: settings.temperature,
                            maxTokens: instance.providerType == .workBuddy ? outputLimit : nil,
                            // Resolve at EACH request, never freeze a session in init.
                            sessionId: resolveSessionId(), headers: settings.headers,
                            resolvedAuth: auth, reasoning: settings.reasoning, cancellation: signal)
                        if plain { options.toolChoice = .none }
                        let upstream = provider.stream(model: wireModel, context: context, options: options)
                        var state = SubscriptionEventState(plain: plain, tools: tools)
                        for await event in upstream {
                            try Task.checkCancellation()
                            try signal.throwIfCancelled()
                            try manager.requireCurrent(account)
                            // Inspect raw events BEFORE mapping: tool identity or
                            // arguments may be buffered without visible output.
                            yieldedContent = yieldedContent || SubscriptionEventState.hasOutput(event)
                            for mapped in try state.accept(event) {
                                yieldedContent = true
                                continuation.yield(mapped)
                            }
                        }
                        // Iteration never throws: final failures must be checked
                        // even when a provider emitted no .error event.
                        let result = await upstream.result()
                        try Task.checkCancellation()
                        try signal.throwIfCancelled()
                        try manager.requireCurrent(account)
                        yieldedContent = yieldedContent || SubscriptionEventState.hasOutput(result)
                        try state.validateFinal(result)
                        try manager.promoteSuccessfulAccount(account, request: request)
                        if let responseModel = result.responseModel, !responseModel.isEmpty {
                            continuation.yield(.responseModel(responseModel))
                        }
                        // Delay executable tool completions until final success:
                        // no partial/corrupt/failed stream can execute a call.
                        for call in state.completed {
                            continuation.yield(.toolCallComplete(id: call.id, name: call.name,
                                args: try state.arguments(call), metadata: nil))
                        }
                        let reasoning = result.content.compactMap { block -> String? in
                            if case .thinking(let t) = block { return t.thinking }; return nil
                        }.joined()
                        if !reasoning.isEmpty { continuation.yield(.reasoningContent(reasoning)) }
                        continuation.yield(.usage(SubscriptionEventState.usage(result.usage)))
                        continuation.yield(.done(stopReason: result.stopReason == .length ? .maxTokens
                            : state.completed.isEmpty ? .endTurn : .toolUse))
                        signal.cancel(); lifetime.install(nil)
                        continuation.finish()
                        return
                    } catch {
                        signal.cancel(); lifetime.install(nil)
                        if error is CancellationError || Task.isCancelled {
                            continuation.finish(throwing: LLMError.cancelled); return
                        }
                        let failure = SubscriptionFailure.capture(error)
                        let explicitQuota = SubscriptionFailure.isExplicitQuota(error)
                        let mapped = SubscriptionFailure.map(error)
                        // [T-subscription-multi-account] This account is out of
                        // credits and nothing was emitted yet: move to the next
                        // account instead of failing the turn. Content already on
                        // screen never falls back (no duplicated/double-charged
                        // retry), and no other error kind is treated as "try
                        // another account" — an expired login still asks the user.
                        if !yieldedContent, accountIndex + 1 < accounts.count,
                           explicitQuota,
                           SubscriptionAccounts.isQuotaExhausted(mapped) {
                            do { try manager.requireCurrent(account) }
                            catch { continuation.finish(throwing: LLMError.cancelled); return }
                            lastFailure = mapped
                            break
                        }
                        if !explicitQuota, attempt == 0, !yieldedContent,
                           rejectedAccess != nil, failure.isCredentialRejection {
                            continue // one refresh, with the rejected access snapshot
                        }
                        continuation.finish(throwing: mapped); return
                    }
                }
                }
                continuation.finish(throwing: lastFailure ?? LLMError.invalidAPIKey())
            }
            lifetime.install(pump)
            continuation.onTermination = { _ in lifetime.cancel() }
        }
    }
}

struct SubscriptionEventState {
    let plain: Bool
    let tools: [KWWKAI.Tool]
    var inputs: [Int: String] = [:]
    var identities: [Int: SubscriptionToolIdentity] = [:]
    var completed: [KWWKAI.ToolCall] = []
    var hasText = false
    var hasThinking = false
    var finalSeen = false

    /// Output can be present in a partial/final even before a mapped event is
    /// delivered. Any tool fragment locks replay, including an incomplete id.
    static func hasOutput(_ message: KWWKAI.AssistantMessage) -> Bool {
        message.content.contains { block in
            switch block {
            case .text(let text): return !text.text.isEmpty
            case .thinking(let thinking): return !thinking.thinking.isEmpty
            case .toolCall: return true
            // An Anthropic fallback block is the alternative form of a text or
            // thinking fragment. Treat anything it carries as output: replaying
            // after visible content would duplicate the turn.
            case .fallback: return true
            }
        }
    }
    static func hasOutput(_ event: KWWKAI.AssistantMessageEvent) -> Bool {
        switch event {
        case .toolCallStart, .toolCallDelta, .toolCallEnd: return true
        case .textDelta(_, let text, let partial), .thinkingDelta(_, let text, let partial),
             .textEnd(_, let text, let partial), .thinkingEnd(_, let text, let partial):
            return !text.isEmpty || hasOutput(partial)
        case .start(let partial), .textStart(_, let partial), .thinkingStart(_, let partial),
             .done(_, let partial), .error(_, let partial):
            return hasOutput(partial)
        }
    }

    private func call(at index: Int, in partial: KWWKAI.AssistantMessage) throws -> KWWKAI.ToolCall {
        guard partial.content.indices.contains(index), case .toolCall(let call) = partial.content[index] else {
            throw LLMError.providerError(message: "工具流缺少对应的 partial 调用块")
        }
        return call
    }
    private mutating func start(_ index: Int, _ call: KWWKAI.ToolCall, ending: Bool = false) throws -> [AgentStreamEvent] {
        var identity = identities[index] ?? SubscriptionToolIdentity()
        let emit = try identity.observe(id: call.id, name: call.name, ending: ending)
        identities[index] = identity
        return emit ? [.contentBlockStart(.toolUse(id: call.id, name: call.name))] : []
    }
    func arguments(_ call: KWWKAI.ToolCall) throws -> [String: Any] {
        // The App preflight owns missing top-level fields: tool_title is
        // display-only, while a missing command/path is returned as a tool
        // error to the model. Keep type/enum/nested-schema validation for
        // supplied values here; never weaken raw JSON or identity checks.
        guard call.unparsedArguments == nil, case .object = call.arguments,
              !call.id.isEmpty, !call.name.isEmpty,
              let tool = tools.first(where: { $0.name == call.name }) else {
            throw LLMError.providerError(message: "拒绝执行无效工具参数或未知工具：\(call.name)")
        }
        var validationTool = tool
        if case .object(var schema) = validationTool.parameters {
            schema.removeValue(forKey: "required")
            validationTool.parameters = .object(schema)
        }
        do { _ = try KWWKAI.validateToolArguments(tool: validationTool, toolCall: call) }
        catch { throw LLMError.providerError(message: "工具参数类型不正确：\(call.name)：\(error)") }
        guard let object = try SubscriptionJSON.object(call.arguments) as? [String: Any] else {
            throw LLMError.providerError(message: "工具参数必须是 JSON 对象")
        }
        return object
    }
    mutating func accept(_ event: KWWKAI.AssistantMessageEvent) throws -> [AgentStreamEvent] {
        switch event {
        case .start: return []
        case .textStart: return [.contentBlockStart(.text)]
        case .textDelta(_, let text, _):
            if !text.isEmpty {
                hasText = hasText || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                return [.textDelta(text)]
            }; return []
        case .thinkingDelta(_, let text, _):
            if !text.isEmpty {
                hasThinking = hasThinking || !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                return [.thinkingDelta(text)]
            }; return []
        case .toolCallStart(let index, let partial):
            guard !plain else { throw LLMError.providerError(message: "普通聊天返回了未请求的工具调用") }
            return try start(index, try call(at: index, in: partial))
        case .toolCallDelta(let index, let delta, let partial):
            guard !plain else { throw LLMError.providerError(message: "普通聊天返回了未请求的工具调用") }
            let current = try call(at: index, in: partial)
            inputs[index, default: ""] += delta
            guard inputs[index, default: ""].utf8.count <= 4 * 1024 * 1024 else {
                throw LLMError.providerError(message: "工具参数流超过安全大小限制")
            }
            var out = try start(index, current)
            if !current.name.isEmpty { out.append(.toolInputDelta(name: current.name, accumulated: inputs[index] ?? "")) }
            return out
        case .toolCallEnd(let index, let call, let partial):
            guard !plain else { throw LLMError.providerError(message: "普通聊天返回了未请求的工具调用") }
            let current = try self.call(at: index, in: partial)
            guard current.id == call.id, current.name == call.name,
                  !completed.contains(where: { $0.id == call.id }) else {
                throw LLMError.providerError(message: "工具调用身份不一致或重复")
            }
            _ = try arguments(call) // unparsedArguments must never become {}.
            let raw = try SubscriptionRequestProtocol.toolArguments(inputs[index] ?? "")
            guard try SubscriptionJSON.value(raw) == call.arguments else {
                throw LLMError.providerError(message: "工具参数与原始 JSON 流不一致；工具未执行")
            }
            let out = try start(index, current, ending: true)
            completed.append(call)
            return out
        case .error(_, let message):
            throw message.failure ?? KWWKAI.ProviderFailure(message: message.errorMessage ?? "订阅流返回错误")
        case .done(_, let message):
            if message.stopReason == .error || message.failure != nil {
                throw message.failure ?? KWWKAI.ProviderFailure(message: message.errorMessage ?? "订阅流失败")
            }
            if message.stopReason == .aborted { throw CancellationError() }
            finalSeen = true
            return []
        case .textEnd, .thinkingStart, .thinkingEnd: return []
        }
    }
    func validateFinal(_ message: KWWKAI.AssistantMessage) throws {
        if message.stopReason == .aborted { throw CancellationError() }
        if message.stopReason == .error || message.failure != nil {
            throw message.failure ?? KWWKAI.ProviderFailure(message: message.errorMessage ?? "订阅流失败")
        }
        guard finalSeen else { throw LLMError.transientError(message: "订阅流缺少完成事件") }
        let calls = message.content.compactMap { block -> KWWKAI.ToolCall? in
            if case .toolCall(let call) = block { return call }; return nil
        }
        guard calls.count == completed.count, calls.elementsEqual(completed, by: {
            $0.id == $1.id && $0.name == $1.name && $0.arguments == $1.arguments
                && $0.unparsedArguments == $1.unparsedArguments
        }) else {
            throw LLMError.providerError(message: "订阅工具流未完整结束；工具未执行")
        }
        for call in calls { _ = try arguments(call) }
        guard hasText || (!plain && (hasThinking || !completed.isEmpty)) else {
            throw LLMError.transientError(message: "订阅服务返回空响应，未作为成功处理")
        }
    }
    static func usage(_ usage: KWWKAI.Usage) -> LLMUsage {
        LLMUsage(inputTokens: usage.input + usage.cacheRead + usage.cacheWrite,
            outputTokens: usage.output, cacheCreationInputTokens: usage.cacheWrite,
            cacheReadInputTokens: usage.cacheRead)
    }
}

// BEGIN SUBSCRIPTION_QUOTA_PURE
/// Retry evidence is machine-readable only. KWWK's broad display category
/// also reads prose; that category alone must never spend a second account.
enum SubscriptionQuotaEvidence {
    static func isExplicit(code: String?, status: Int?, transport: Bool) -> Bool {
        guard !transport else { return false }
        if let status, status >= 500 || status == 408 { return false }
        guard let code = code?.lowercased() else { return false }
        return ["14018", "insufficient_quota", "quota_exhausted"].contains(code)
    }

    /// WorkBuddy's observed error.data.code may be an integer. Read only its
    /// documented envelope positions, never a number/phrase in message text.
    static func code(in root: [String: Any]) -> String? {
        let error = root["error"] as? [String: Any] ?? root
        let data = error["data"] as? [String: Any] ?? [:]
        let rootData = root["data"] as? [String: Any] ?? [:]
        for value in [data["code"], error["code"], root["code"], rootData["code"], error["type"]] {
            if let string = value as? String, !string.isEmpty { return string }
            if let n = value as? NSNumber, String(cString: n.objCType) != "c",
               n.doubleValue.isFinite, n.doubleValue.rounded() == n.doubleValue,
               n.doubleValue > Double(Int.min), n.doubleValue < Double(Int.max) {
                return String(n.intValue)
            }
        }
        return nil
    }

    static func preservingErrorCode(_ payload: String) throws -> String {
        guard var root = (try? JSONSerialization.jsonObject(with: Data(payload.utf8))) as? [String: Any],
              let code = code(in: root), code != "0",
              root["error"] != nil || root["choices"] == nil else { return payload }
        var error = root["error"] as? [String: Any] ?? [:]
        // Keep all original data and error fields; only expose the existing
        // machine code to the generic parser. No inferred code from prose.
        error["code"] = code
        if error["message"] == nil {
            error["message"] = (error["data"] as? [String: Any])?["msg"]
                ?? root["msg"] ?? root["message"] ?? root["error"] as? String
        }
        root["error"] = error
        return String(decoding: try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys]), as: UTF8.self)
    }
}
// END SUBSCRIPTION_QUOTA_PURE

enum SubscriptionFailure {
    static func capture(_ error: Error) -> KWWKAI.ProviderFailure {
        if let directory = error as? SubscriptionDirectoryProtocol.InvalidDirectory {
            return KWWKAI.ProviderFailure(message: directory.localizedDescription,
                httpStatus: directory.code.flatMap { [401, 403].contains($0) ? $0 : nil },
                providerCode: directory.code.map(String.init))
        }
        return KWWKAI.ProviderFailure.capture(error)
    }
    static func isExplicitQuota(_ error: Error) -> Bool {
        // A mapped/local error has already lost provenance. Never recover
        // replay permission by scanning its user-visible description.
        guard error is KWWKAI.ProviderFailure || error is SubscriptionDirectoryProtocol.InvalidDirectory else { return false }
        let failure = capture(error)
        return SubscriptionQuotaEvidence.isExplicit(code: failure.providerCode, status: failure.httpStatus,
            transport: failure.transportDomain != nil || failure.transportCode != nil)
    }
    static func wireFailure(_ data: Data, status: Int) throws -> KWWKAI.ProviderFailure {
        let root = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any] ?? [:]
        var failure = KWWKAI.ProviderFailure.payload(try SubscriptionJSON.value(root),
            fallback: String(decoding: data.prefix(4096), as: UTF8.self))
        failure.httpStatus = status
        failure.providerCode = SubscriptionQuotaEvidence.code(in: root) ?? failure.providerCode
        return failure
    }
    static func map(_ error: Error) -> LLMError {
        if let error = error as? LLMError { return error }
        if error is CancellationError { return .cancelled }
        let failure = capture(error)
        if isExplicitQuota(error) {
            return .providerError(message: "insufficient_quota：\(failure.message)")
        }
        // Transport and server status win over any quota wording carried in
        // a diagnostic. A bare 402/429 is not evidence of spent credit here.
        if failure.transportDomain != nil || failure.transportCode != nil {
            if failure.transportDomain == NSURLErrorDomain, failure.transportCode == NSURLErrorCancelled { return .cancelled }
            return .networkError(underlying: failure)
        }
        if let status = failure.httpStatus, status >= 500 || status == 408 {
            return .transientError(message: failure.message, statusCode: status)
        }
        if failure.httpStatus == 429 { return .rateLimited }
        if failure.providerCode == "11140" { return .providerError(message: "账号限制 11140：\(failure.message)") }
        // KWWK preserves category rather than losing quota to a generic 429.
        // LLMError has no contextOverflow/quota cases in this App version;
        // retain canonical markers so its existing classifiers can detect it.
        switch failure.category {
        case .authentication: return .invalidAPIKey(detail: failure.message)
        case .rateLimit: return .rateLimited
        case .quota: return .providerError(message: failure.message) // prose-only; no canonical marker
        case .contextOverflow: return .providerError(message: "context_length_exceeded / context overflow：\(failure.message)")
        case .cancelled: return .cancelled
        case .server, .timeout:
            return .transientError(message: failure.message, statusCode: failure.httpStatus)
        case .transport: return .networkError(underlying: failure)
        case .refusal, .invalidRequest, .unknown:
            if let status = failure.httpStatus {
                return ProviderServiceError.httpError(statusCode: status, body: failure.message)
            }
            return .providerError(message: failure.message)
        }
    }
}

struct SubscriptionRequestSettings: Sendable {
    let temperature: Double?
    let topP: Double?
    let headers: [String: String]
    let extraBody: [String: String]
    let reasoning: KWWKAI.ReasoningLevel?

    init(instance: ProviderInstance, overrides: ModelOverrides, temperature: Double?,
         thinkingLevel: ThinkingLevel, wireModel: KWWKAI.Model) throws {
        let isTrae = instance.providerType == .traeCN
        self.temperature = overrides.temperature ?? temperature
        topP = overrides.topP
        headers = try SubscriptionRequestProtocol.headers(overrides.customHeaders ?? [:])
        extraBody = try SubscriptionRequestProtocol.extras(overrides.extraBodyParams ?? [:], isTrae: isTrae)
        if let value = self.temperature, !value.isFinite || !(0...2).contains(value) {
            throw LLMError.providerError(message: "temperature 必须是 0 到 2 的有限数值")
        }
        if let value = topP, !value.isFinite || !(0...1).contains(value) {
            throw LLMError.providerError(message: "topP 必须是 0 到 1 的有限数值")
        }
        if isTrae {
            // The user-provided mending wire accepts only messages, tools,
            // model/config_name/function and reasoning_effort. No invented
            // temperature/top_p/max_tokens passthrough to a text-only gate.
            guard self.temperature == nil, topP == nil, overrides.maxOutputTokens == nil else {
                throw LLMError.providerError(message: "Trae CN 原始 wire 不支持 temperature、topP 或自定义 maxOutputTokens；请移除这些覆盖")
            }
        }
        if let effort = extraBody["reasoning_effort"] {
            let offered = wireModel.thinkingLevelMap?.values.compactMap { $0 } ?? []
            guard offered.contains(effort) else {
                throw LLMError.providerError(message: "此账号模型未声明 reasoning_effort=\(effort)；不可猜测支持等级")
            }
        }
        if thinkingLevel == .off || !wireModel.reasoning {
            reasoning = nil
        } else if wireModel.thinkingLevelMap == nil {
            // Reasoning capability does not imply controllable effort tiers.
            reasoning = nil
        } else {
            reasoning = KWWKAI.ReasoningLevel(rawValue: thinkingLevel == .ultra ? "max" : thinkingLevel.rawValue)
        }
    }
}

/// Only changes optional scalar parameters after KWWK's normal encoding.
/// It never retries, redirects, changes messages, renames tools or executes one.
struct SubscriptionRequestHTTPClient: KWWKAI.HTTPClient {
    let inner: any KWWKAI.HTTPClient
    let settings: SubscriptionRequestSettings
    let kind: ProviderType
    let account: SubscriptionOAuthManager.AccountSnapshot

    func stream(url: URL, method: String, headers: [String: String], body: Data?,
                cancellation: KWWKAI.CancellationHandle?) async throws -> (HTTPURLResponse, AsyncThrowingStream<Data, Error>) {
        try await stream(url: url, method: method, headers: headers, body: body,
                         cancellation: cancellation, timeoutSeconds: 60)
    }
    func stream(url: URL, method: String, headers: [String: String], body: Data?,
                cancellation: KWWKAI.CancellationHandle?, timeoutSeconds: TimeInterval) async throws -> (HTTPURLResponse, AsyncThrowingStream<Data, Error>) {
        var body = body
        if let original = body {
            guard var root = try JSONSerialization.jsonObject(with: original) as? [String: Any] else {
                throw LLMError.providerError(message: "订阅请求编码不是 JSON 对象")
            }
            if kind == .workBuddy {
                if let topP = settings.topP { root["top_p"] = topP }
                for (key, value) in settings.extraBody { root[key] = value }
            } else {
                // Already checked against the actual source wire's allowlist.
                for (key, value) in settings.extraBody { root[key] = value }
            }
            body = try JSONSerialization.data(withJSONObject: root, options: [.sortedKeys])
        }
        try await SubscriptionOAuthManager.shared.requireCurrent(account)
        try Task.checkCancellation()
        try cancellation?.throwIfCancelled()
        let (response, bytes) = try await inner.stream(url: url, method: method, headers: headers, body: body,
            cancellation: cancellation, timeoutSeconds: timeoutSeconds)
        try await SubscriptionOAuthManager.shared.requireCurrent(account)
        try cancellation?.throwIfCancelled()
        if response.statusCode >= 400 {
            let data = try await SubscriptionJSON.collect(bytes, limit: 1_048_576, cancellation: cancellation)
            try await SubscriptionOAuthManager.shared.requireCurrent(account)
            throw try SubscriptionFailure.wireFailure(data, status: response.statusCode)
        }
        guard kind == .workBuddy else { return (response, bytes) }
        // KWWK's generic payload reader drops numeric error.data.code. Preserve
        // it as the same string code; message/tool encoding remains untouched.
        let framed = AsyncThrowingStream<Data, Error> { continuation in
            let pump = Task {
                do {
                    for try await event in KWWKAI.parseSSE(bytes: bytes) {
                        try Task.checkCancellation()
                        try cancellation?.throwIfCancelled()
                        try await SubscriptionOAuthManager.shared.requireCurrent(account)
                        let data = try SubscriptionQuotaEvidence.preservingErrorCode(event.data)
                        var frame = "event: \(event.event)\n"
                        for line in data.components(separatedBy: "\n") { frame += "data: \(line)\n" }
                        continuation.yield(Data((frame + "\n").utf8))
                    }
                    continuation.finish()
                } catch { continuation.finish(throwing: error) }
            }
            continuation.onTermination = { _ in pump.cancel() }
        }
        return (response, framed)
    }
}

/// The public KWWK WorkBuddyProvider is deliberately NOT used: at pinned
/// a7fe8390 it silently rewords flagged text and moves system instructions
/// into user messages on a channel rejection. This strict adapter reuses the
/// public OpenAI provider without that policy-changing WorkBuddyChatClient.
/// Refusals (11101/11128 etc.) are returned without any shape retry.
struct SubscriptionWorkBuddyProvider: KWWKAI.APIProvider {
    let api = "openai-completions"
    private let completions: KWWKAI.OpenAICompletionsProvider

    init(client: any KWWKAI.HTTPClient) {
        // Exact domestic clientHeaders from the pinned WorkBuddyWire source.
        let headers = [
            "X-Product": "SaaS", "X-IDE-Type": "WorkBuddy",
            "User-Agent": KWWKAI.WorkBuddyOAuth.userAgent,
            "X-Requested-With": "XMLHttpRequest", "X-Agent-Intent": "craft",
            "X-Agent-Purpose": "conversation", "X-IDE-Name": "WorkBuddy",
            "X-IDE-Version": KWWKAI.WorkBuddyOAuth.clientVersion,
        ]
        completions = KWWKAI.OpenAICompletionsProvider(client: client,
            defaultBaseURL: URL(string: KWWKAI.WorkBuddySite.china.chatBaseURL)!, extraHeaders: headers,
            bodyDecorator: { root, _, _, _ in SubscriptionRequestProtocol.workBuddyBody(&root) },
            headersDecorator: { headers, _, _, _ in
                // Opaque per-request ids only. Do not derive/mislabel a real
                // account, user-send, session or conversation from prompt text.
                let request = UUID().uuidString.replacingOccurrences(of: "-", with: "").lowercased()
                headers["X-Request-ID"] = request
                headers["X-Conversation-Message-ID"] = request
            })
    }
    func stream(model: KWWKAI.Model, context: KWWKAI.Context,
                options: KWWKAI.StreamOptions?) -> KWWKAI.AssistantMessageStream {
        completions.stream(model: model, context: context, options: options)
    }
}

// BEGIN SUBSCRIPTION_REQUEST_PURE
// Foundation-only production logic compiled verbatim by the macOS harness.
struct SubscriptionToolIdentity {
    private(set) var id = ""
    private(set) var name = ""
    private var emitted = false
    private var ended = false

    /// Observe only pre-end snapshots. KWWK's OpenAI decoder mints missing
    /// ids during finalization; such an id is NOT evidence from the server.
    mutating func observe(id: String, name: String, ending: Bool = false) throws -> Bool {
        guard !ended,
              self.id.isEmpty || id.isEmpty || self.id == id,
              self.name.isEmpty || name.isEmpty || self.name == name else {
            throw SubscriptionRequestProtocol.InvalidOverride("工具流 id/name 中途变化或重复结束；工具未执行")
        }
        if ending {
            guard !self.id.isEmpty, !self.name.isEmpty, self.id == id, self.name == name else {
                throw SubscriptionRequestProtocol.InvalidOverride("工具流缺少服务端真实 id/name；不接受结束时生成的身份")
            }
            ended = true
        } else {
            if !id.isEmpty { self.id = id }
            if !name.isEmpty { self.name = name }
        }
        guard !emitted, !self.id.isEmpty, !self.name.isEmpty else { return false }
        emitted = true
        return true
    }
}

enum SubscriptionRequestProtocol {
    struct InvalidOverride: LocalizedError {
        let errorDescription: String?
        init(_ message: String) { errorDescription = message }
    }
    static func toolArguments(_ raw: String) throws -> [String: Any] {
        guard let object = try JSONSerialization.jsonObject(with: Data(raw.utf8)) as? [String: Any] else {
            throw InvalidOverride("工具参数必须为单一完整 JSON 对象；未替换为 {}")
        }
        return object
    }
    static func headers(_ source: [String: String]) throws -> [String: String] {
        let reserved: Set<String> = [
            "authorization", "proxy-authorization", "host", "cookie", "cookie2", "set-cookie",
            "content-type", "content-length", "connection", "transfer-encoding", "accept",
            "api-key", "x-api-key", "x-ide-token", "x-cloudide-token", "x-uid",
            "x-machine-id", "x-device-id", "x-user-id", "x-domain", "x-enterprise-id", "x-tenant-id",
            "user-agent", "x-product", "x-ide-type", "x-ide-name", "x-ide-version", "x-ide-version-code",
            "x-app-id", "x-app-version", "x-app-version-code", "x-requested-with", "x-plugin-channel",
            "x-agent-type", "x-agent-intent", "x-agent-purpose", "x-device-type", "x-device-cpu",
            "x-os-version", "x-ide-version-type", "request-traffic-type", "x-custom-trace-id",
            "x-flow-traceparent", "x-conversation-id", "x-conversation-request-id",
            "x-conversation-message-id", "x-request-id", "session_id", "x-session-id",
            "x-client-request-id", "x-session-affinity", "forwarded", "referer", "origin",
        ]
        var seen = Set<String>()
        for (name, value) in source {
            let key = name.lowercased()
            guard name.range(of: #"^[!#$%&'*+.^_`|~0-9A-Za-z-]+$"#, options: .regularExpression) != nil,
                  !reserved.contains(key), !key.hasPrefix("sec-"), !key.hasPrefix("proxy-"),
                  !key.hasPrefix("x-forwarded-"), !key.contains("token"), !key.contains("auth"),
                  seen.insert(key).inserted,
                  !value.unicodeScalars.contains(where: { $0.value < 32 || $0.value == 127 }) else {
                throw InvalidOverride("禁止覆盖订阅认证/路由/协议保留头或无效头：\(name)")
            }
        }
        return source
    }
    static func extras(_ source: [String: String], isTrae: Bool) throws -> [String: String] {
        // ModelOverrides stores STRING values. Preserve them as strings;
        // numeric sampling parameters use the typed temperature/topP fields.
        // Protocol-owned arrays/addresses/credential fields never pass through.
        let allowed: Set<String> = isTrae ? ["reasoning_effort"] : ["reasoning_effort", "user"]
        for key in source.keys where !allowed.contains(key) {
            throw InvalidOverride("\(isTrae ? "Trae CN" : "WorkBuddy") 不支持或禁止额外参数 \(key)；未静默忽略")
        }
        return source
    }
    static func workBuddyBody(_ root: inout [String: Any]) {
        var messages = root["messages"] as? [[String: Any]] ?? []
        if messages.first?["role"] as? String != "system" {
            messages.insert(["role": "system", "content": "You are a helpful assistant."], at: 0)
        }
        // All EXISTING words/blocks/roles remain untouched, including channel
        // keywords, multilingual content and system instructions.
        root["messages"] = messages
        if let choice = root["tool_choice"] as? [String: Any],
           let function = choice["function"] as? [String: Any], let name = function["name"] as? String {
            root["tool_choice"] = name
        } else if root["tool_choice"] as? String == "none" {
            root.removeValue(forKey: "tool_choice")
            root.removeValue(forKey: "tools")
            root.removeValue(forKey: "parallel_tool_calls")
        }
    }
}
// END SUBSCRIPTION_REQUEST_PURE
