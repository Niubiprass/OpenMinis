import Foundation

private let logger = AppLogger(category: "Backup")

/// The credential section of a backup package (docs/backup-restore-design.md §5.4).
///
/// **Stage 3a scope: the values are base64-encoded, NOT encrypted.** §5's
/// AES-256-GCM/Argon2id layer is a later step, so a package produced now
/// contains credentials that anyone can decode with a base64 tool. The manifest
/// reports `encrypted: false` and `includesCredentials: true` so this is stated
/// rather than implied — see `BackupExporter.exportProviders`.
///
/// Field names and encoding are NOT invented here. They match the existing
/// cross-platform provider-share format on both ends:
///   - iOS `ProviderConfigStore.exportInstanceJSON` (ProviderConfigStore.swift:1037)
///   - Android `ProviderRepository.exportInstanceJSON`
///     (data/repository/ProviderRepository.kt:2122, credentials at :2204-2242)
/// Both write `apiKey` / `manualOAuthToken` / `oauthToken` / `oauthEmail` /
/// `oauthGcpProject` as base64 of the UTF-8 bytes (Android uses
/// `Base64.NO_WRAP`, which is the same standard alphabet + padding that
/// `Data.base64EncodedString()` produces, just without line breaks — and
/// `base64EncodedString()` emits no line breaks by default, so the two are
/// byte-identical). Deviating here would silently break interop, which §5.4
/// explicitly warns against ("do not invent a second scheme").
struct BackupSecrets: Codable {
    var v: Int = 1
    var providers: [ProviderSecret] = []
    var envVars: [EnvVarSecret] = []
    var mcpOAuth: [MCPOAuthSecret] = []

    /// One provider instance's credentials. Every value is base64; nil means
    /// the credential simply isn't present for that instance.
    struct ProviderSecret: Codable {
        let instanceId: String
        /// Carried for human/debug legibility and to help a cross-platform
        /// importer match instances; not a secret.
        let label: String?
        let providerType: String?
        var apiKey: String?
        var manualOAuthToken: String?
        /// The structured OAuth login blob (access + refresh + expiry),
        /// JSON-encoded then base64'd — matching both platforms' `oauthToken`.
        var oauthToken: String?
        var oauthEmail: String?
        var oauthGcpProject: String?
        /// Additional subscription slots belonging to `instanceId`. The legacy
        /// slot (`instanceId` itself) stays in `oauthToken` for old backups.
        /// These blobs live ONLY in the credential section, never provider_config.
        var subscriptionAccounts: [SubscriptionAccountSecret]?

        var isEmpty: Bool {
            apiKey == nil && manualOAuthToken == nil && oauthToken == nil
                && oauthEmail == nil && oauthGcpProject == nil
                && (subscriptionAccounts?.isEmpty ?? true)
        }
    }

    struct SubscriptionAccountSecret: Codable {
        let accountId: String
        /// base64 of SubscriptionTokenStorage JSON; includes its provider tag.
        let oauthToken: String
    }

    struct EnvVarSecret: Codable {
        /// The variable name, e.g. `GITHUB_TOKEN`. Plaintext: it's metadata,
        /// and §2's `env_vars.json` already carries it unencoded.
        let name: String
        /// base64 of the value's UTF-8 bytes.
        let value: String
    }

    struct MCPOAuthSecret: Codable {
        let serverId: String
        /// base64 of the JSON token blob.
        let token: String
        /// base64 of the client secret, when one was issued.
        var clientSecret: String?
    }
}

/// Shared export/restore ownership check. A slot is never a provider instance:
/// models and configuration remain on its parent. Refuse ambiguous/colliding
/// ownership before touching Keychain, even for a hand-edited backup.
enum BackupSubscriptionAccounts {
    static func owns(_ accountId: String, parent: ProviderInstance,
                     instances: [ProviderInstance]) -> Bool {
        guard parent.providerType.isDomesticSubscription,
              parent.credentialType == .oauth,
              !parent.id.isEmpty,
              instances.filter({ $0.id == parent.id }).count == 1,
              parent.subscriptionAccountSlots.contains(accountId) else { return false }
        guard (try? SubscriptionConfigurationStorage.validate(parent)) != nil,
              parent.ownsSubscriptionSlot(accountId) else { return false }
        return !instances.contains { other in
            other.id != parent.id
                && (other.id == accountId || other.subscriptionAccountSlots.contains(accountId))
        }
    }

    /// Validate the whole credential set before touching Keychain. Duplicate or
    /// cross-parent entries are ambiguous, so none of that provider is adopted.
    static func decoded(_ secret: BackupSecrets.ProviderSecret, parent: ProviderInstance,
                        instances: [ProviderInstance]) throws -> [(slot: String, token: SubscriptionTokenStorage)] {
        guard secret.instanceId == parent.id, secret.providerType == parent.providerType.rawValue,
              parent.providerType.isDomesticSubscription, parent.credentialType == .oauth,
              secret.apiKey == nil, secret.manualOAuthToken == nil,
              secret.oauthEmail == nil, secret.oauthGcpProject == nil else {
            throw SubscriptionConfigurationStorage.Invalid.accounts
        }
        var blobs = secret.subscriptionAccounts ?? []
        if let legacy = secret.oauthToken { blobs.insert(.init(accountId: parent.id, oauthToken: legacy), at: 0) }
        var seen = Set<String>()
        return try blobs.map { item in
            guard seen.insert(item.accountId).inserted,
                  owns(item.accountId, parent: parent, instances: instances),
                  let data = Data(base64Encoded: item.oauthToken),
                  let token = try? JSONDecoder().decode(SubscriptionTokenStorage.self, from: data),
                  token.provider == parent.providerType.rawValue, !token.accessToken.isEmpty else {
                throw SubscriptionConfigurationStorage.Invalid.accounts
            }
            return (slot: item.accountId, token: token)
        }
    }

    /// Decode the credential-bearing provider share using the same wire fields
    /// as backup. Every destination is freshly allocated; source ids are never
    /// used as local Keychain addresses. Old single-account shares had no id.
    static func remapShare(_ object: [String: Any], destination: ProviderInstance) throws
        -> (instance: ProviderInstance, accounts: [(slot: String, token: SubscriptionTokenStorage)]) {
        guard destination.providerType.isDomesticSubscription,
              destination.credentialType == .oauth,
              object["apiKey"] == nil, object["manualOAuthToken"] == nil,
              object["customBaseURL"] == nil, object["customUserAgent"] == nil,
              object["azureMode"] == nil, object["imageEndpointMode"] == nil else {
            throw SubscriptionConfigurationStorage.Invalid.accounts
        }
        let hasAccounts = object["subscriptionAccountIds"] != nil || object["subscriptionAccounts"] != nil
        let sourceId: String
        if let id = object["instanceId"] as? String, !id.isEmpty { sourceId = id }
        else {
            guard !hasAccounts, object["instanceId"] == nil else { throw SubscriptionConfigurationStorage.Invalid.accounts }
            sourceId = "legacy-share"
        }
        var source = ProviderInstance(id: sourceId, label: destination.label,
                                      providerType: destination.providerType, credentialType: .oauth)
        let json = try JSONSerialization.data(withJSONObject: object)
        source = try SubscriptionConfigurationStorage.applying(String(data: json, encoding: .utf8), to: source)
        var secretObject = object
        secretObject["instanceId"] = sourceId
        let secret = try JSONDecoder().decode(BackupSecrets.ProviderSecret.self,
            from: JSONSerialization.data(withJSONObject: secretObject))
        let accounts = try decoded(secret, parent: source, instances: [source])
        var mapping: [String: String] = [:]
        for slot in source.subscriptionAccountSlots {
            mapping[slot] = slot == sourceId ? destination.id : destination.id + ".subscription." + UUID().uuidString
        }
        var result = destination
        result.subscriptionAccountIds = source.subscriptionAccountIds == nil ? nil
            : source.subscriptionAccountSlots.compactMap { mapping[$0] }
        result.subscriptionActiveAccountId = source.subscriptionActiveAccountId.flatMap { mapping[$0] }
        result.subscriptionAutoFailover = source.subscriptionAutoFailover
        result.subscriptionAutoCheckin = source.subscriptionAutoCheckin
        return (result, accounts.map { (slot: mapping[$0.slot]!, token: $0.token) })
    }
}

/// Reads credentials out of the Keychain and assembles the §5.4 structure.
///
/// §5.4 is explicit that the ONLY viable path is "decrypt in-process, re-encode,
/// re-protect with the backup's own key" — a Keychain item cannot be exported as
/// a ciphertext container, and Android's EncryptedSharedPreferences XML is
/// device-bound garbage off-device. So this deliberately reads plaintext into
/// memory; the protection is supposed to come from §5's encryption layer.
enum BackupSecretsCollector {

    /// Assemble the credential section for the given provider instances.
    ///
    /// - Parameter instances: the instances being exported, so the secrets
    ///   section never carries keys for a provider the package doesn't include.
    @MainActor
    static func collect(instances: [ProviderInstance]) -> BackupSecrets {
        var out = BackupSecrets()

        for instance in instances {
            if instance.providerType.isDomesticSubscription {
                if let secret = collectSubscription(instance: instance, instances: instances, loadToken: { slot in
                    ProviderKeychainHelper.loadOAuthToken(instanceId: slot, as: SubscriptionTokenStorage.self)
                }) {
                    out.providers.append(secret)
                }
                continue
            }
            var secret = BackupSecrets.ProviderSecret(
                instanceId: instance.id,
                label: instance.label,
                providerType: instance.providerType.rawValue)

            if !instance.providerType.isDomesticSubscription,
               let key = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) {
                secret.apiKey = b64(key)
            }
            if !instance.providerType.isDomesticSubscription,
               let manual = ProviderKeychainHelper.loadOAuthString(
                instanceId: instance.id, account: "manual-oauth-token") {
                secret.manualOAuthToken = b64(manual)
            }
            // The structured OAuth blob is stored under a per-provider-type
            // Codable, so the read has to switch on the type exactly as
            // exportInstanceJSON does.
            if let blob = oauthTokenBlob(for: instance) {
                secret.oauthToken = blob.base64EncodedString()
            }
            if instance.providerType == .gemini {
                if let email = ProviderKeychainHelper.loadOAuthString(
                    instanceId: instance.id, account: "oauth-email") {
                    secret.oauthEmail = b64(email)
                }
                if let project = ProviderKeychainHelper.loadOAuthString(
                    instanceId: instance.id, account: "oauth-gcp-project") {
                    secret.oauthGcpProject = b64(project)
                }
            }

            // An instance with no credential contributes nothing — writing an
            // all-nil row would just inflate the section and imply a secret
            // exists where none does.
            if !secret.isEmpty { out.providers.append(secret) }
        }

        for entry in EnvVarStore.shared.entries {
            guard let value = EnvVarStore.loadValueSync(forKey: entry.key), !value.isEmpty
            else { continue }
            out.envVars.append(.init(name: entry.key, value: b64(value)))
        }

        // MCPServerConfig.id IS the servers.json key / server name — the same
        // string MCPOAuthController keys its Keychain accounts by.
        for server in MCPStore.shared.servers {
            guard let tokens = MCPOAuthController.tokens(server: server.id),
                  let data = try? JSONEncoder().encode(tokens) else { continue }
            var item = BackupSecrets.MCPOAuthSecret(
                serverId: server.id, token: data.base64EncodedString())
            if let cs = MCPOAuthController.clientSecret(server: server.id), !cs.isEmpty {
                item.clientSecret = b64(cs)
            }
            out.mcpOAuth.append(item)
        }

        logger.info("[Backup] secrets collected providers=\(out.providers.count) envVars=\(out.envVars.count) mcpOAuth=\(out.mcpOAuth.count)")
        return out
    }

    /// Injectable read seam: tests exercise the real collector with synthetic
    /// credentials, without querying Keychain or contacting account APIs.
    @MainActor
    static func collectSubscription(instance: ProviderInstance, instances: [ProviderInstance],
                                    loadToken: (String) -> SubscriptionTokenStorage?) -> BackupSecrets.ProviderSecret? {
        var secret = BackupSecrets.ProviderSecret(
            instanceId: instance.id, label: instance.label, providerType: instance.providerType.rawValue)
        var accounts: [BackupSecrets.SubscriptionAccountSecret] = []
        var seen = Set<String>()
        for slot in instance.subscriptionAccountSlots {
            guard seen.insert(slot).inserted,
                  BackupSubscriptionAccounts.owns(slot, parent: instance, instances: instances),
                  let token = loadToken(slot),
                  token.provider == instance.providerType.rawValue, !token.accessToken.isEmpty,
                  let data = try? JSONEncoder().encode(token) else { continue }
            if slot == instance.id {
                // Preserve the legacy wire shape, but never copy the ACTIVE
                // secondary account into the parent's unrelated Keychain service.
                secret.oauthToken = data.base64EncodedString()
            } else {
                accounts.append(.init(accountId: slot, oauthToken: data.base64EncodedString()))
            }
        }
        if !accounts.isEmpty { secret.subscriptionAccounts = accounts }
        return secret.isEmpty ? nil : secret
    }

    @MainActor
    private static func oauthTokenBlob(for instance: ProviderInstance) -> Data? {
        let id = instance.id
        switch instance.providerType {
        case .anthropic:
            return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: ClaudeTokenStorage.self)
                .flatMap { try? JSONEncoder().encode($0) }
        case .openAI:
            return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: CodexTokenStorage.self)
                .flatMap { try? JSONEncoder().encode($0) }
        case .gemini:
            return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: GeminiTokenStorage.self)
                .flatMap { try? JSONEncoder().encode($0) }
        case .xAI:
            return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: XAITokenStorage.self)
                .flatMap { try? JSONEncoder().encode($0) }
        case .kimiCode:
            return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: KimiTokenStorage.self)
                .flatMap { try? JSONEncoder().encode($0) }
        case .githubCopilot:
            // [T-copilot-backup-token] Without this the `default` below swallowed
            // Copilot, so a restored install lost the sign-in — while the login
            // sheet's disclaimer explicitly tells the user "a backup you export
            // yourself can include it". Only `githubToken` is load-bearing; the
            // session token is short-lived and re-minted on demand, so an
            // expired one in the blob costs nothing.
            //
            // Note this switch carries a `default`, so the compiler did NOT
            // flag the new provider case here — the omission had to be found by
            // reading. Any future provider with an OAuth blob must be added by
            // hand, the same way.
            return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: CopilotTokenStorage.self)
                .flatMap { try? JSONEncoder().encode($0) }
        case .workBuddy, .traeCN:
            // Collected slot-by-slot above, together with explicit ownership.
            return nil
        case .antigravity, .openAIResponses, .openRouter, .unsupported:
            return nil
        }
    }

    private static func b64(_ s: String) -> String {
        Data(s.utf8).base64EncodedString()
    }
}
