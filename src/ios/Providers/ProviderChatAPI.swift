import Foundation
import CryptoKit

// Ordinary chat only: image/voice/OAuth and explicitly fixed legacy instances
// retain their existing wire path. No hostname guessing or background probes.
enum ProviderChatAPIFormat: String, Codable, CaseIterable, Sendable {
    case chatCompletions, responses
}
enum ProviderChatAPIMode: String, Codable, CaseIterable, Sendable {
    case automatic, chatCompletions, responses
}

enum ProviderChatAPIError: LocalizedError {
    case unavailable, unverified, correctionFailed, scopeChanged
    var errorDescription: String? {
        switch self {
        case .unavailable: return "此配置暂不支持自动识别，原来的接口方式没有改变。"
        case .unverified: return "没有收到有效的模型回复，未保存接口模式；不会继续尝试其它入口。"
        case .correctionFailed: return "按站点明确要求纠正接口后仍未成功，已停止，不会反复换接口或换 Key。"
        case .scopeChanged: return "配置或 Key 已改变，本次识别结果未保存，请使用当前配置重新识别。"
        }
    }
}
struct ProviderChatEndpointRejection: Error, Sendable {
    let target: ProviderChatAPIFormat
    // Match the complete structured server message, never a displayed/truncated
    // 403. An unrelated permissions/quota failure must not become a retry.
    static func target(status: Int, body: String, fromChat: Bool) -> ProviderChatAPIFormat? {
        guard [400,403,404,405].contains(status), body.utf8.count <= 16_384,
              let data=body.data(using:.utf8),
              let root=(try? JSONSerialization.jsonObject(with:data)) as? [String:Any],
              let error=root["error"] as? [String:Any],
              let message=error["message"] as? String else { return nil }
        let text=message.lowercased().split(whereSeparator: { $0.isWhitespace }).joined(separator:" ")
        // Both explicit clauses are required. Merely mentioning Responses in
        // an authentication/error message grants no permission to send again.
        let current=fromChat ? "/v1/chat/completions" : "/v1/responses"
        let other=fromChat ? "/v1/responses" : "/v1/chat/completions"
        guard text.contains("only supports " + other),
              text.contains(current + " is disabled") else { return nil }
        return fromChat ? .responses : .chatCompletions
    }
}

// This reference travels with the request worker, including rebuilt key
// providers. At most one compatibility correction, never one per key.
final class ProviderChatAPIBudget: @unchecked Sendable {
    @TaskLocal static var current: ProviderChatAPIBudget?
    private let lock=NSLock()
    private var spent=false
    func take() -> Bool {
        lock.lock(); defer { lock.unlock() }
        guard !spent else { return false }; spent=true; return true
    }
    static func worker(_ operation: @escaping @Sendable () async -> Void) -> Task<Void,Never> {
        let budget=current ?? ProviderChatAPIBudget()
        return Task { await $current.withValue(budget) { await operation() } }
    }
}

struct ProviderChatAPIRecord: Codable, Sendable {
    let instanceId: String
    let configuration: String
    let credentialFingerprint: String
    let modelId: String
    let scope: String
    let format: ProviderChatAPIFormat
    let date: Date
}
final class ProviderChatAPIHistory: @unchecked Sendable {
    static let shared=ProviderChatAPIHistory()
    private let lock=NSLock()
    private let writes=DispatchQueue(label:"minis.chat-api.success-writes",qos:.utility)
    private var rows: [String:ProviderChatAPIRecord]=[:]
    private var epochs: [String:UUID]=[:]
    private let defaults: UserDefaults
    static let didChange=Notification.Name("ProviderChatAPIChoicesChanged")
    private let storageKey="provider.chat-api.verified.v2"
    private var observer:NSObjectProtocol?
    init(defaults: UserDefaults = .standard) {
        self.defaults=defaults
        if let data=defaults.data(forKey:storageKey),data.count<=256*1024,
           let decoded=try? JSONDecoder().decode([ProviderChatAPIRecord].self,from:data) {
            for row in decoded.sorted(by:{$0.date > $1.date}).prefix(128) { rows[row.scope]=row }
        }
        observer=NotificationCenter.default.addObserver(forName:Notification.Name("ProviderMultiKeyManager.didChange"),object:nil,queue:nil) { [weak self] note in
            guard note.userInfo?["quotaCredentialsUnchanged"] as? Bool != true,
                  let id=note.object as? String else{return}
            self?.invalidate(id)
        }
    }
    deinit {if let observer {NotificationCenter.default.removeObserver(observer)}}
    func epoch(_ id:String) -> UUID {
        lock.lock();defer{lock.unlock()}
        if let value=epochs[id] { return value }
        let value=UUID();epochs[id]=value;return value
    }
    func cached(_ scope:String) -> ProviderChatAPIFormat? {
        lock.lock();defer{lock.unlock()};return rows[scope]?.format
    }
    func invalidate(_ id:String) {
        lock.lock();epochs[id]=UUID();rows=rows.filter{$0.value.instanceId != id}
        enqueueSnapshotLocked();lock.unlock()
    }
    func save(scope:String,instanceId:String,epoch:UUID,format:ProviderChatAPIFormat,
              configuration:String,credentialFingerprint:String,modelId:String) -> Bool {
        lock.lock();defer{lock.unlock()}
        guard !Task.isCancelled,epochs[instanceId]==epoch else { return false }
        if let old=rows[scope],old.format==format {return true}
        rows[scope]=ProviderChatAPIRecord(instanceId:instanceId,configuration:configuration,
            credentialFingerprint:credentialFingerprint,modelId:modelId,scope:scope,format:format,date:Date())
        if rows.count>128 {
            for row in rows.values.sorted(by:{$0.date > $1.date}).dropFirst(128) { rows[row.scope]=nil }
        }
        enqueueSnapshotLocked();return true
    }
    func formats(instanceId:String,configuration:String,credentials:Set<String>) -> Set<ProviderChatAPIFormat> {
        lock.lock();defer{lock.unlock()}
        return Set(rows.values.filter {
            $0.instanceId==instanceId && $0.configuration==configuration && credentials.contains($0.credentialFingerprint)
        }.map(\.format))
    }
    func invalidateAll() {
        lock.lock()
        for id in Array(epochs.keys) {epochs[id]=UUID()}
        rows.removeAll();enqueueSnapshotLocked();lock.unlock()
    }
    private func enqueueSnapshotLocked() {
        let snapshot=Array(rows.values);let defaults=self.defaults;let key=storageKey
        // Only enqueue under lock. UserDefaults I/O never holds a cache lock.
        // One queue preserves mutation order, so an old write cannot resurrect
        // an invalidated choice. Read-back is verified before notification.
        writes.async {
            guard let data=try? JSONEncoder().encode(snapshot) else{return}
            defaults.set(data,forKey:key)
            guard defaults.data(forKey:key)==data else{return}
            DispatchQueue.main.async {
                NotificationCenter.default.post(name:Self.didChange,object:nil)
            }
        }
    }
}

final class ProviderChatAPIContext: @unchecked Sendable {
    let instance:ProviderInstance
    let scope:String
    let epoch:UUID
    let configuration:String
    let credentialFingerprint:String
    let modelId:String
    let initial:ProviderChatAPIFormat
    let validate:@MainActor () async -> Bool
    init(instance:ProviderInstance,scope:String,configuration:String,credentialFingerprint:String,
         modelId:String,initial:ProviderChatAPIFormat,validate:@escaping @MainActor () async -> Bool) {
        self.instance=instance;self.scope=scope;self.configuration=configuration
        self.credentialFingerprint=credentialFingerprint;self.modelId=modelId;self.initial=initial
        epoch=ProviderChatAPIHistory.shared.epoch(instance.id);self.validate=validate
    }
    func record(_ format:ProviderChatAPIFormat) async throws {
        try Task.checkCancellation()
        guard await validate() else {throw ProviderChatAPIError.scopeChanged}
        try Task.checkCancellation()
        guard ProviderChatAPIHistory.shared.save(scope:scope,instanceId:instance.id,epoch:epoch,format:format,
                configuration:configuration,credentialFingerprint:credentialFingerprint,modelId:modelId) else {
            throw ProviderChatAPIError.scopeChanged
        }
    }
}

@MainActor
enum ProviderChatAPI {
    static func invalidate(instanceId:String) { ProviderChatAPIHistory.shared.invalidate(instanceId) }
    static func fingerprint(_ string:String) -> String {
        SHA256.hash(data:Data(string.utf8)).map{String(format:"%02x",$0)}.joined()
    }
    static func instanceConfiguration(_ instance:ProviderInstance) -> String {
        // Explicit material is stable across process restarts; Codable JSON
        // dictionary order is deliberately not used as cache identity.
        let fields=[instance.id,instance.providerType.rawValue,instance.credentialType.rawValue,
                    instance.customBaseURL ?? "",String(instance.appendV1Suffix),
                    instance.chatAPIFormatMode?.rawValue ?? "legacy",instance.effectiveCustomUserAgent ?? "",
                    String(instance.azureMode),String(instance.codexClientMask)]
        return fingerprint(fields.map{"\($0.utf8.count):\($0)"}.joined())
    }
    static func configuration(instance:ProviderInstance,provider:OpenAIProvider) -> String? {
        guard let identity=provider.credentialResourceIdentity else{return nil}
        var data=Data(instanceConfiguration(instance).utf8)
        let suffix="\n\(provider.customBaseURL ?? "")\n\(provider.appendV1Suffix)\n\(provider.model.id)\n\(identity)"
        data.append(Data(suffix.utf8))
        // Model override headers/body also change applicability. Only the
        // fingerprint is retained; never persist raw user headers or a key.
        if let extra=try? JSONSerialization.data(withJSONObject:provider.extraHeaders,options:.sortedKeys) {data.append(extra)}
        if let encoded=try? JSONSerialization.data(withJSONObject:provider.overrideExtraBody,options:.sortedKeys) {data.append(encoded)}
        return SHA256.hash(data:data).map{String(format:"%02x",$0)}.joined()
    }
    @discardableResult
    static func configure(_ provider:OpenAIProvider,instance:ProviderInstance,entry:ModelEntry? = nil) -> OpenAIProvider {
        defer { ProviderTurnCompaction.configure(provider, instance: instance, entry: entry) }
        guard [.openAI,.openAIResponses].contains(instance.providerType),instance.credentialType == .apiKey else{return provider}
        guard let mode=instance.chatAPIFormatMode else{return provider} // Legacy fixed choice.
        if mode != .automatic {
            provider.forceResponsesAPI = mode == .responses
            return provider
        }
        let modality=provider.model.modalityOverride ?? .textOnly
        guard modality.contains(.textInput),modality.contains(.textOutput),
              !instance.azureMode,!instance.isOpenCodeChannel,!provider.codexClientMask,
              provider.perRequestHeaders == nil,let raw=instance.effectiveCustomBaseURL,
              var url=URLComponents(string:raw),let host=url.host,!host.isEmpty,
              url.user==nil,url.password==nil,
              url.scheme?.lowercased()=="https" || (url.scheme?.lowercased()=="http" && ["localhost","127.0.0.1","::1"].contains(host)),
              case .apiKey(let key)=provider.authMode else{return provider}
        var hint:ProviderChatAPIFormat?
        let path=url.path.trimmingCharacters(in:CharacterSet(charactersIn:"/"))
        let trimmedPath=url.path.hasSuffix("/") ? String(url.path.dropLast()) : url.path
        if path.hasSuffix("chat/completions") {
            hint = .chatCompletions;url.path=String(trimmedPath.dropLast("chat/completions".count))
        } else if path.hasSuffix("responses") {
            hint = .responses;url.path=String(trimmedPath.dropLast("responses".count))
        }
        if hint != nil {
            provider.customBaseURL=url.string
            // Endpoint URL was explicit. Its remaining prefix already carries
            // any /v1, so do not append a second version segment.
            provider.appendV1Suffix=false
        }
        guard let scope=configuration(instance:instance,provider:provider) else{return provider}
        let initial=ProviderChatAPIHistory.shared.cached(scope) ?? hint ?? .chatCompletions
        let context=ProviderChatAPIContext(instance:instance,scope:scope,
                configuration:instanceConfiguration(instance),credentialFingerprint:fingerprint(key),
                modelId:provider.model.id,initial:initial) {
            guard let current=ProviderConfigStore.shared.instance(for:instance.id),
                  instanceConfiguration(current)==instanceConfiguration(instance),current.isEnabled else{return false}
            if let entry,ProviderConfigStore.shared.entry(for:entry.id) != entry {return false}
            let manager=ProviderMultiKeyManager.shared
            if await manager.isActiveAsync(for:instance.id) {
                let ring=await manager.keysAsync(for:instance.id)
                return ring.contains{$0.key==key && $0.isEnabled && $0.status != .disabled}
            }
            return (await manager.primaryKeyAsync(for:instance.id) ?? "")==key
        }
        provider.chatAPIContext=context
        provider.forceResponsesAPI = initial == .responses
        return provider
    }

    static func status(for instance:ProviderInstance) async -> String {
        guard instance.chatAPIFormatMode == .automatic else {
            return instance.chatAPIFormatMode == .responses ||
                   (instance.chatAPIFormatMode == nil && instance.providerType == .openAIResponses)
                ? "Responses API" : "Chat Completions"
        }
        let manager=ProviderMultiKeyManager.shared
        let credentials:Set<String>
        if await manager.isActiveAsync(for:instance.id) {
            credentials=Set((await manager.keysAsync(for:instance.id))
                .filter{$0.isEnabled && $0.status != .disabled}.map{fingerprint($0.key)})
        } else {
            credentials=Set([fingerprint(await manager.primaryKeyAsync(for:instance.id) ?? "")])
        }
        guard ProviderConfigStore.shared.instance(for:instance.id)==instance else{return "自动"}
        let formats=ProviderChatAPIHistory.shared.formats(instanceId:instance.id,
                         configuration:instanceConfiguration(instance),credentials:credentials)
        if formats.count>1 {return "自动（按模型适配）"}
        if formats.first == .responses {return "自动（已识别：Responses）"}
        if formats.first == .chatCompletions {return "自动（已识别：普通聊天）"}
        return "自动"
    }

    // There is deliberately no probe/detect API. Adding a provider never sends
    // a synthetic chat; only a real user message can establish a working format.
}

// Preserve unknown DB extras and use the existing dirty/sync/save pipeline.
// Only mode preference syncs/backups; verified credential-bound results stay local.
enum ProviderChatAPIConfiguration {
    static func merging(_ instance:ProviderInstance,into old:String?) throws -> String? {
        var object:[String:Any]=[:]
        if let old {
            guard let data=old.data(using:.utf8),let value=try JSONSerialization.jsonObject(with:data) as? [String:Any] else {
                throw ProviderChatAPIError.scopeChanged
            }
            object=value
        }
        if let mode=instance.chatAPIFormatMode {object["chatAPIFormatMode"]=mode.rawValue}
        else {object.removeValue(forKey:"chatAPIFormatMode")}
        guard !object.isEmpty else{return old}
        return String(data:try JSONSerialization.data(withJSONObject:object,options:.sortedKeys),encoding:.utf8)
    }
    static func applying(_ extras:String?,to original:ProviderInstance) throws -> ProviderInstance {
        var instance=original
        guard let extras else{return instance}
        guard let data=extras.data(using:.utf8),let object=try JSONSerialization.jsonObject(with:data) as? [String:Any] else{throw ProviderChatAPIError.scopeChanged}
        if let raw=object["chatAPIFormatMode"] as? String {instance.chatAPIFormatMode=ProviderChatAPIMode(rawValue:raw)}
        return instance
    }
}
