import CryptoKit
import Foundation
import KWWKAI

/// Domestic subscription endpoints are not user-configurable relays.
/// The Trae chat host is from the user-provided Apelin-providers/trae source,
/// NOT a verified official trae.cn domain. Tokens leave the device for this host.
/// Keep this provenance/risk visible in the provider's login UI and documentation.
enum SubscriptionEndpoints {
    static let workBuddyHosts: Set<String> = ["copilot.tencent.com"]
    static let traeHosts: Set<String> = ["trae-api-cn.mchost.guru"]
    static let traeOrigin = "https://trae-api-cn.mchost.guru"

    static func validate(_ instance: ProviderInstance) throws {
        guard instance.providerType == .workBuddy || instance.providerType == .traeCN else {
            throw LLMError.providerError(message: "不支持的订阅服务商")
        }
        guard instance.customBaseURL?.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty != false else {
            throw LLMError.providerError(message: "订阅服务商不接受自定义 Base URL；凭证只能发送到固定国内站点")
        }
    }

    static func validate(_ credentials: KWWKAI.OAuthCredentials) throws {
        for key in ["baseUrl", "baseURL", "base_url"] {
            if case .string(let value)? = credentials.extras[key], !value.isEmpty {
                throw LLMError.providerError(message: "订阅凭证中含自定义地址；为防止凭证外发已拒绝请求")
            }
        }
    }
}

enum SubscriptionModelsAPI {
    /// An invalid/partial directory throws: callers must retain the previous list.
    /// An explicitly empty authoritative directory is different and returns [].
    static func fetchModels(instance: ProviderInstance) async throws -> [LLMModel] {
        try SubscriptionEndpoints.validate(instance)
        var rejectedAccess: String?
        for attempt in 0...1 {
            do {
                let credentials = try await SubscriptionOAuthManager.shared.validCredentials(
                    instanceId: instance.id, type: instance.providerType,
                    forceRefresh: attempt == 1, rejectedAccess: rejectedAccess)
                rejectedAccess = credentials.access
                let catalog = try await SubscriptionCatalogCache.shared.catalog(
                    instance: instance, credentials: credentials, refresh: true)
                return catalog.models.map { model in
                    var result = LLMModel(
                        id: model.id, displayName: model.name,
                        provider: instance.providerType == .workBuddy ? "WorkBuddy" : "Trae CN",
                        modalityOverride: model.input.contains(.image) ? [.textInput, .textOutput, .imageInput] : .textOnly,
                        contextWindow: model.contextWindow > 0 ? model.contextWindow : nil,
                        maxOutputTokens: model.maxTokens > 0 ? model.maxTokens : nil,
                        supportsReasoning: model.reasoning,
                        interleavedReasoningField: model.reasoning ? "reasoning_content" : nil,
                        reasoningEffortValues: SubscriptionCatalog.efforts(model),
                        declaresNoEffortTiers: SubscriptionCatalog.efforts(model)?.isEmpty == true)
                    result.effortDeclarationIsAuthoritative = true
                    return result
                }
            } catch {
                if error is CancellationError || Task.isCancelled { throw LLMError.cancelled }
                let failure = SubscriptionFailure.capture(error)
                if attempt == 0, rejectedAccess != nil, failure.isCredentialRejection { continue }
                throw SubscriptionFailure.map(error)
            }
        }
        throw LLMError.invalidAPIKey()
    }
}

struct SubscriptionCatalog: Sendable {
    var models: [KWWKAI.Model]
    var functions: [String: String] = [:]

    static func efforts(_ model: KWWKAI.Model) -> [String]? {
        guard let map = model.thinkingLevelMap else { return [] }
        let order = ["off", "minimal", "low", "medium", "high", "xhigh", "max"]
        return order.compactMap { map[$0] ?? nil }.filter { $0 != "none" }
    }
}

/// No origin-only/global-account cache. The fingerprint covers the ENTIRE
/// credential (including uid/domain/tenant). It is never persisted or logged.
/// Restored models resolve their route lazily here on their first request.
actor SubscriptionCatalogCache {
    static let shared = SubscriptionCatalogCache()
    private struct Key: Hashable { let instance: String; let provider: String; let fingerprint: String }
    private struct Record { let catalog: SubscriptionCatalog; let date: Date }
    private var records: [Key: Record] = [:]
    private let lifetime: TimeInterval = 600

    func catalog(instance: ProviderInstance, credentials: KWWKAI.OAuthCredentials,
                 refresh: Bool = false, cancellation: KWWKAI.CancellationHandle? = nil) async throws -> SubscriptionCatalog {
        try SubscriptionEndpoints.validate(instance)
        try SubscriptionEndpoints.validate(credentials)
        try Task.checkCancellation()
        try cancellation?.throwIfCancelled()
        let encoder = JSONEncoder()
        encoder.outputFormatting = .sortedKeys
        let digest = SHA256.hash(data: try encoder.encode(credentials))
        let key = Key(instance: instance.id, provider: instance.providerType.rawValue,
                      fingerprint: digest.map { String(format: "%02x", $0) }.joined())
        if !refresh, let record = records[key], Date().timeIntervalSince(record.date) < lifetime {
            return record.catalog
        }
        let catalog: SubscriptionCatalog
        switch instance.providerType {
        case .workBuddy:
            let client = SubscriptionWorkBuddyConfigClient(
                inner: SubscriptionHTTPClient(allowedHosts: SubscriptionEndpoints.workBuddyHosts, timeout: 15),
                cancellation: cancellation)
            let listings: [KWWKAI.WorkBuddyModels.Listing]
            do {
                listings = try await KWWKAI.WorkBuddyModels.fetch(site: .china, credentials: credentials, client: client)
            } catch {
                // Fixed upstream fetch rejects an empty CLI roster. Only the
                // structurally validated, code=0 empty list is authoritative.
                if client.authoritativeEmpty { listings = [] } else { throw error }
            }
            catalog = SubscriptionCatalog(models: client.applyingReportedLimits(to: listings.map(\.model)))
        case .traeCN:
            let token = TraeCredential(credentials)
            let entries = try await TraeWire.roster(
                origin: SubscriptionEndpoints.traeOrigin,
                token: TraeTokenStore.Token(value: token.access, userID: token.userID,
                    refresh: token.refresh, expires: token.expires,
                    machineID: token.machineID, deviceID: token.deviceID),
                client: SubscriptionHTTPClient(allowedHosts: SubscriptionEndpoints.traeHosts, timeout: 12),
                cancellation: cancellation)
            catalog = SubscriptionCatalog(models: entries.map { $0.model },
                functions: Dictionary(uniqueKeysWithValues: entries.map { ($0.id, $0.function) }))
        default:
            throw LLMError.providerError(message: "不支持的订阅服务商")
        }
        try Task.checkCancellation()
        try cancellation?.throwIfCancelled()
        // Publish atomically only after ALL directory functions succeeded.
        records = records.filter { $0.key.instance != instance.id }
        if records.count >= 64, let oldest = records.min(by: { $0.value.date < $1.value.date })?.key {
            records.removeValue(forKey: oldest)
        }
        records[key] = Record(catalog: catalog, date: Date())
        return catalog
    }
}

/// One JSON bridge only; never use the App's unrelated JSONValue namespace.
enum SubscriptionJSON {
    static func value(_ object: Any) throws -> KWWKAI.JSONValue {
        let data = try JSONSerialization.data(withJSONObject: object, options: [.fragmentsAllowed])
        return try JSONDecoder().decode(KWWKAI.JSONValue.self, from: data)
    }
    static func object(_ value: KWWKAI.JSONValue) throws -> Any {
        try JSONSerialization.jsonObject(with: JSONEncoder().encode(value), options: [.fragmentsAllowed])
    }
    static func collect(_ stream: AsyncThrowingStream<Data, Error>, limit: Int,
                        cancellation: KWWKAI.CancellationHandle?) async throws -> Data {
        var data = Data()
        for try await chunk in stream {
            try Task.checkCancellation()
            try cancellation?.throwIfCancelled()
            guard data.count + chunk.count <= limit else {
                throw LLMError.providerError(message: "订阅服务响应超过安全大小限制")
            }
            data.append(chunk)
        }
        return data
    }
}

/// KWWKAI owns WorkBuddy's row/effort/image interpretation. This narrow
/// transport validates the envelope before feeding it to that public parser,
/// and prevents its bundled window fallback from becoming account metadata.
final class SubscriptionWorkBuddyConfigClient: KWWKAI.HTTPClient, @unchecked Sendable {
    let inner: any KWWKAI.HTTPClient
    let cancellation: KWWKAI.CancellationHandle?
    private let lock = NSLock()
    private var inspected: SubscriptionDirectoryProtocol.WorkBuddyConfig?

    init(inner: any KWWKAI.HTTPClient, cancellation: KWWKAI.CancellationHandle?) {
        self.inner = inner; self.cancellation = cancellation
    }
    private func snapshot() -> SubscriptionDirectoryProtocol.WorkBuddyConfig? {
        lock.lock(); defer { lock.unlock() }; return inspected
    }
    private func store(_ config: SubscriptionDirectoryProtocol.WorkBuddyConfig) {
        lock.lock(); defer { lock.unlock() }; inspected = config
    }
    var authoritativeEmpty: Bool { snapshot()?.ids.isEmpty == true }

    func applyingReportedLimits(to models: [KWWKAI.Model]) -> [KWWKAI.Model] {
        let details = snapshot()?.details ?? [:]
        return models.map { model in
            var model = model
            let detail = details[model.id] ?? [:]
            model.contextWindow = SubscriptionDirectoryProtocol.positiveInt(detail["maxInputTokens"]) ?? 0
            model.maxTokens = SubscriptionDirectoryProtocol.positiveInt(detail["maxOutputTokens"]) ?? 0
            // Pinned KWWK invents low/high/max when supportsReasoning alone
            // is true. Account metadata must contain only declared tiers.
            let declared = (detail["reasoning"] as? [String: Any])?["supportedEfforts"] as? [String] ?? []
            var efforts = declared
            let reasoning = detail["reasoning"] as? [String: Any] ?? [:]
            if !efforts.isEmpty, detail["onlyReasoning"] as? Bool != true,
               reasoning["canDisableThinking"] as? Bool != false, !efforts.contains("none") {
                efforts.insert("none", at: 0)
            }
            model.reasoning = detail["supportsReasoning"] as? Bool == true || !declared.isEmpty
            model.thinkingLevelMap = efforts.isEmpty ? nil : Dictionary(uniqueKeysWithValues:
                ["off", "minimal", "low", "medium", "high", "xhigh", "max"].map { level in
                    let wire = level == "off" ? "none" : level
                    return (level, efforts.contains(wire) ? Optional(wire) : nil)
                })
            return model
        }
    }

    func stream(url: URL, method: String, headers: [String: String], body: Data?,
                cancellation: KWWKAI.CancellationHandle?) async throws -> (HTTPURLResponse, AsyncThrowingStream<Data, Error>) {
        let signal = cancellation ?? self.cancellation
        let (response, bytes) = try await inner.stream(url: url, method: method, headers: headers,
                                                     body: body, cancellation: signal)
        let data = try await SubscriptionJSON.collect(bytes, limit: 4 * 1024 * 1024, cancellation: signal)
        if response.statusCode == 200 {
            let config = try SubscriptionDirectoryProtocol.workBuddyConfig(data)
            store(config)
        }
        return (response, AsyncThrowingStream { c in c.yield(data); c.finish() })
    }
}

// BEGIN SUBSCRIPTION_DIRECTORY_PURE
// Foundation-only production logic; the macOS fixture harness compiles this
// exact region, not a rewritten test-side parser.
enum SubscriptionDirectoryProtocol {
    struct WorkBuddyConfig {
        let ids: [String]
        let details: [String: [String: Any]]
    }
    struct InvalidDirectory: LocalizedError {
        let errorDescription: String?
        let code: Int?
        init(_ message: String, code: Int? = nil) { errorDescription = message; self.code = code }
    }
    static func integer(_ value: Any?) -> Int? {
        guard let n = value as? NSNumber, String(cString: n.objCType) != "c",
              n.doubleValue.isFinite, n.doubleValue.rounded() == n.doubleValue,
              n.doubleValue > Double(Int.min), n.doubleValue < Double(Int.max) else { return nil }
        return n.intValue
    }
    static func positiveInt(_ value: Any?) -> Int? {
        guard let n = value as? NSNumber, String(cString: n.objCType) != "c",
              n.doubleValue.isFinite, n.doubleValue > 0,
              n.doubleValue.rounded() == n.doubleValue,
              n.doubleValue < Double(Int.max) else { return nil }
        return n.intValue
    }
    static func workBuddyConfig(_ data: Data) throws -> WorkBuddyConfig {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any],
              let code = integer(root["code"]) else {
            throw InvalidDirectory("WorkBuddy 配置不是有效的 JSON 包络")
        }
        guard code == 0 else {
            // Preserve machine-readable codes for auth/quota classification.
            throw InvalidDirectory("WorkBuddy config code=\(code): \((root["msg"] as? String ?? "配置请求失败").prefix(1024))", code: code)
        }
        guard let config = root["data"] as? [String: Any],
              let agents = config["agents"] as? [[String: Any]],
              let rows = config["models"] as? [[String: Any]],
              agents.filter({ $0["name"] as? String == "cli" }).count == 1,
              let cli = agents.first(where: { $0["name"] as? String == "cli" }),
              let ids = cli["models"] as? [String],
              ids.allSatisfy({ !$0.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty }),
              Set(ids).count == ids.count else {
            throw InvalidDirectory("WorkBuddy 配置缺少完整的 CLI 模型目录；保留旧列表")
        }
        var details: [String: [String: Any]] = [:]
        for row in rows {
            guard let id = row["id"] as? String, !id.isEmpty, details[id] == nil else {
                throw InvalidDirectory("WorkBuddy 模型明细损坏或重复；保留旧列表")
            }
            details[id] = row
        }
        guard ids.allSatisfy({ details[$0] != nil }) else {
            throw InvalidDirectory("WorkBuddy CLI 模型缺少对应明细；保留旧列表")
        }
        for id in ids {
            let row = details[id]!
            for key in ["maxInputTokens", "maxOutputTokens"] {
                if let value = row[key], !(value is NSNull), integer(value).map({ $0 >= 0 }) != true {
                    throw InvalidDirectory("WorkBuddy token 元数据损坏；保留旧列表")
                }
            }
            if let raw = row["reasoning"], !(raw is NSNull) {
                guard let reasoning = raw as? [String: Any] else {
                    throw InvalidDirectory("WorkBuddy reasoning 元数据损坏；保留旧列表")
                }
                if let raw = reasoning["supportedEfforts"], !(raw is NSNull) {
                    try validateEfforts(raw)
                }
            }
        }
        return WorkBuddyConfig(ids: ids, details: details)
    }
    static func traeRows(_ data: Data) throws -> [[String: Any]] {
        guard let root = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw InvalidDirectory("Trae 模型目录不是 JSON 对象")
        }
        // The source protocol publishes this field at the root. Missing is
        // NOT the same thing as a server-authorized empty config_info_list.
        if let raw = root["code"] {
            guard let code = integer(raw) else { throw InvalidDirectory("Trae directory code 无效") }
            if code != 0 {
                throw InvalidDirectory("Trae directory code=\(code): \((root["message"] as? String ?? "目录请求失败").prefix(1024))", code: code)
            }
        }
        guard let rows = root["config_info_list"] as? [[String: Any]] else {
            throw InvalidDirectory("Trae 模型目录不完整；保留旧列表")
        }
        var seen = Set<String>()
        for row in rows {
            guard let id = row["config_name"] as? String,
                  !id.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
                  seen.insert(id).inserted else {
                throw InvalidDirectory("Trae 模型条目缺少 config_name 或重复；保留旧列表")
            }
            for key in ["display_config", "context_window_tokens", "reasoning"] {
                if let value = row[key], !(value is NSNull), !(value is [String: Any]) {
                    throw InvalidDirectory("Trae 模型能力元数据损坏；保留旧列表")
                }
            }
            if let value = row["model_detail_list"], !(value is NSNull), !(value is [[String: Any]]) {
                throw InvalidDirectory("Trae model_detail_list 损坏；保留旧列表")
            }
            let context = row["context_window_tokens"] as? [String: Any] ?? [:]
            let details = row["model_detail_list"] as? [[String: Any]] ?? []
            for (object, key) in [(context, "dev")] + details.flatMap({ [($0, "prompt_max_tokens"), ($0, "max_tokens")] }) {
                if let value = object[key], !(value is NSNull), integer(value).map({ $0 >= 0 }) != true {
                    throw InvalidDirectory("Trae token 元数据损坏；保留旧列表")
                }
            }
            if let efforts = (row["reasoning"] as? [String: Any])?["supportedEfforts"], !(efforts is NSNull) {
                try validateEfforts(efforts)
            }
            for detail in details {
                if let efforts = detail["supported_efforts"], !(efforts is NSNull) { try validateEfforts(efforts) }
            }
        }
        return rows
    }
    static func validateEfforts(_ value: Any) throws {
        guard let efforts = value as? [String], Set(efforts).count == efforts.count,
              efforts.allSatisfy({ ["none", "minimal", "low", "medium", "high", "xhigh", "max"].contains($0) }) else {
            throw InvalidDirectory("订阅目录 effort 等级损坏或不受支持；保留旧列表")
        }
    }
}
// END SUBSCRIPTION_DIRECTORY_PURE
