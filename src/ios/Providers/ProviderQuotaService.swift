import Foundation
import UIKit
import WebKit
import Combine
import CryptoKit

/// Account ledgers and chat-key quotas remain independent readings. The old
/// QuotaInfo projection is retained for existing titles, pickers and badges.
final class ProviderQuotaService: ObservableObject {
    static let shared = ProviderQuotaService()
    @Published private(set) var revision = 0

    struct QuotaInfo {
        let displayText: String
        let highlighted: Bool
        var kind: Kind = .used
        /// Set only when the primary reading has proven USD units.
        var balanceUSD: Double? = nil
        var amountUSD: Double? = nil
        var readings: [RelayQuotaProtocol.Reading] = []
        var attempts: [RelayQuotaProtocol.Attempt] = []
        var primaryReadingID: String? = nil
        var lastAttemptAt: Date? = nil
        var observedAt: Date? = nil
        var isStale = false
        var isPartial = false
        /// Internal process-local credential digest. Never log or persist it.
        fileprivate var owner: String = ""
        /// Other pools kept separate from the primary amount, already labelled.
        var secondaryText: String? = nil
        /// Why a source did not answer; sanitized, never a raw body.
        var failureText: String? = nil
        enum Kind { case used, balance }
    }

    static let lowThresholdDefaultsKey = "quota.lowThresholdUSD"
    /// [T-quota-disk-cache] Only the numbers that were already on screen, so a
    /// relaunch shows the last known balance at once instead of an empty row
    /// while every relay is probed again. No credential, digest or endpoint.
    private struct StoredQuota: Codable {
        let displayText: String
        let amountUSD: Double?
        let balanceUSD: Double?
        let kindIsBalance: Bool
        let highlighted: Bool
        let fetchedAt: Date
    }
    private static let storedPrefix = "quota.lastKnown."

    private static let logger = AppLogger(category: "Quota")

    /// [T-quota-timing] One line per balance query: how long it took and what
    /// came back. This module had no logging at all, so "the balance is slow"
    /// could not be traced to a step; now a slow relay is visible by name.
    static func logRefresh(instanceId: String, rowId: String, info: QuotaInfo?, note: String?) {
        let amount: String
        if let usd = info?.amountUSD ?? info?.balanceUSD { amount = String(format: "%.2f USD", usd) }
        else if let text = info?.displayText { amount = text }
        else { amount = "none" }
        let kind = info?.kind == .balance ? "balance" : (info == nil ? "missing" : "used")
        logger.info("balance query instance=\(instanceId.prefix(8)) row=\(rowId) kind=\(kind) value=\(amount) note=\(note ?? "-")")
    }

    private static func store(_ info: QuotaInfo?, instanceId: String, at date: Date) {
        let key = storedPrefix + instanceId
        guard let info else {
            UserDefaults.standard.removeObject(forKey: key)
            return
        }
        let value = StoredQuota(displayText: info.displayText,
                                amountUSD: info.amountUSD,
                                balanceUSD: info.balanceUSD,
                                kindIsBalance: info.kind == .balance,
                                highlighted: info.highlighted,
                                fetchedAt: date)
        guard let data = try? JSONEncoder().encode(value) else { return }
        UserDefaults.standard.set(data, forKey: key)
    }

    private static func storedInfo(instanceId: String) -> (info: QuotaInfo, fetchedAt: Date)? {
        guard let data = UserDefaults.standard.data(forKey: storedPrefix + instanceId),
              let value = try? JSONDecoder().decode(StoredQuota.self, from: data) else { return nil }
        let info = QuotaInfo(displayText: value.displayText,
                             highlighted: value.highlighted,
                             kind: value.kindIsBalance ? .balance : .used,
                             balanceUSD: value.balanceUSD,
                             amountUSD: value.amountUSD)
        return (info, value.fetchedAt)
    }

    private struct CacheEntry {
        let info: QuotaInfo?
        let fetchedAt: Date // attempt time, NOT the successful observation time
        let owner: String
    }
    private var cache: [String: CacheEntry] = [:]
    private var keyCache: [String: [String: CacheEntry]] = [:]
    private var failureNotes: [String: String] = [:]
    private var inFlight: [String: UUID] = [:]
    private var epochs: [String: UUID] = [:]
    private let lock = NSLock()
    /// [T-quota-15min] How long a stored balance is reused before the list
    /// asks the relay again. Longer means fewer requests to someone else's
    /// server; the detail page still refreshes only when the user asks.
    private let ttl: TimeInterval = 15 * 60
    private var observers: [AnyCancellable] = []
    private var cookieObserver: ProviderQuotaCookieObserver?
    private static let salt = UUID().uuidString
    private static let transport: URLSession = {
        let config = URLSessionConfiguration.ephemeral
        config.httpCookieStorage = nil
        config.httpShouldSetCookies = false
        config.urlCredentialStorage = nil
        config.urlCache = nil
        config.timeoutIntervalForResource = 15
        return URLSession(configuration: config, delegate: RelayQuotaRedirectGuard(), delegateQueue: nil)
    }()
    private static let metadataLock = NSLock()
    private static var scales: [String: (RelayQuotaProtocol.Scale?, Date)] = [:]
    private static var scaleTasks: [String: Task<RelayQuotaProtocol.Scale?, Never>] = [:]
    private static var relayHints: [String: RelayQuotaProtocol.Source] = [:]

    private init() {
        // Existing writers already publish these changes; no edits to the
        // credential/config stores are needed. Stale in-flight results are fenced.
        Task { @MainActor in
            let store = ProviderConfigStore.shared
            self.observers = [
                store.$authRevision.dropFirst().sink { [weak self] _ in self?.invalidateAll() },
                store.$config.dropFirst().sink { [weak self] _ in self?.invalidateAll() },
                NotificationCenter.default.publisher(for: ProviderMultiKeyManager.didChange)
                    .sink { [weak self] _ in self?.invalidateAll() }
            ]
            let observer = ProviderQuotaCookieObserver { [weak self] in self?.invalidateAll() }
            self.cookieObserver = observer
            WKWebsiteDataStore.default().httpCookieStore.add(observer)
        }
    }

    struct KeyQuota: Identifiable {
        let id: String
        let title: String
        let badge: String
        let masked: String
        let isMain: Bool
        var info: QuotaInfo? = nil
        var queriedAt: Date? = nil
        var failureNote: String? = nil
        var isUnavailable: Bool { info == nil && queriedAt != nil }
    }

    private func failureKey(_ instanceId: String, _ rowId: String) -> String { "\(instanceId)|\(rowId)" }
    func failureNote(instanceId: String, rowId: String = "main") -> String? {
        lock.lock(); defer { lock.unlock() }
        return failureNotes[failureKey(instanceId, rowId)]
    }
    func noteFailure(_ text: String, instanceId: String, rowId: String = "main") {
        lock.lock(); defer { lock.unlock() }
        failureNotes[failureKey(instanceId, rowId)] = text
    }
    func clearFailure(instanceId: String, rowId: String = "main") {
        lock.lock(); defer { lock.unlock() }
        failureNotes.removeValue(forKey: failureKey(instanceId, rowId))
    }
    func cachedQuota(instanceId: String) -> QuotaInfo? {
        lock.lock()
        let live = cache[instanceId]?.info.map { Self.reproject($0) }
        lock.unlock()
        if let live { return live }
        // [T-quota-disk-cache] Nothing in memory (fresh launch): show the last
        // number this account already had instead of an empty row.
        return Self.storedInfo(instanceId: instanceId)?.info
    }
    func isMissing(instanceId: String) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        if let e = cache[instanceId] { return Date().timeIntervalSince(e.fetchedAt) >= ttl }
        // A stored number existed, but nothing was queried in this process yet.
        return true
    }
    private func invalidateAll() {
        lock.lock()
        cache.removeAll(); keyCache.removeAll(); failureNotes.removeAll()
        epochs.removeAll(); inFlight.removeAll()
        lock.unlock()
        Self.metadataLock.lock(); Self.relayHints.removeAll(); Self.metadataLock.unlock()
        Task { @MainActor in self.revision += 1 }
    }
    func invalidate(instanceId: String) {
        lock.lock()
        cache.removeValue(forKey: instanceId)
        keyCache.removeValue(forKey: instanceId)
        failureNotes = failureNotes.filter { !$0.key.hasPrefix(instanceId + "|") }
        inFlight = inFlight.filter { !$0.key.hasPrefix(instanceId + "|") }
        epochs[instanceId] = UUID()
        lock.unlock()
        Self.metadataLock.lock(); Self.relayHints.removeAll(); Self.metadataLock.unlock()
        Task { @MainActor in self.revision += 1 }
    }

    private static func snapshot(_ info: QuotaInfo) -> RelayQuotaProtocol.Snapshot {
        .init(owner: info.owner, readings: info.readings, attempts: info.attempts)
    }
    private static func reproject(_ info: QuotaInfo) -> QuotaInfo {
        project(snapshot(info)) ?? info
    }
    static func project(_ snapshot: RelayQuotaProtocol.Snapshot) -> QuotaInfo? {
        guard let primary = snapshot.primary else { return nil }
        let hasRemaining = primary.remaining != nil && !primary.rejected && !primary.unlimited
        let value = hasRemaining ? primary.remaining : primary.used
        let kind: QuotaInfo.Kind = hasRemaining ? .balance : .used
        let text: String
        if primary.rejected { text = "Key 已失效" }
        else if let value {
            // [T-quota-no-raw-points] A reading the site only reports in quota
            // points is NOT money. Showing "11817571.00 quota" in the row read
            // as a life-changing balance; say plainly that it is unconverted.
            let number = primary.unit.isUSD ? String(format: "$%.2f", value)
                : "额度点未换算"
            text = (hasRemaining ? primary.label : "已用") + " " + number
        } else if primary.unlimited { text = primary.label + " · 不限量" }
        else if let total = primary.total {
            let number = primary.unit.isUSD ? String(format: "$%.2f", total)
                : String(format: "%.2f %@", total, primary.unit.label)
            text = "总额 " + number + " · 余量未知"
        } else { text = "余量未知" }
        return QuotaInfo(displayText: text, highlighted: snapshot.isLow(thresholdUSD: lowThresholdUSD),
                         kind: kind, balanceUSD: hasRemaining && primary.unit.isUSD ? value : nil,
                         amountUSD: primary.unit.isUSD && !primary.rejected ? value : nil,
                         readings: snapshot.readings, attempts: snapshot.attempts,
                         primaryReadingID: primary.id, lastAttemptAt: snapshot.lastAttemptAt,
                         observedAt: primary.observedAt, isStale: primary.isStale(),
                         isPartial: snapshot.attempts.contains { !$0.probeMiss && (!$0.succeeded || $0.failureNote != nil) }
                            || snapshot.readings.contains { $0.isStale() }, owner: snapshot.owner,
                         secondaryText: RelayQuotaProtocol.secondaryLine(snapshot.readings, primary: primary),
                         failureText: RelayQuotaProtocol.failureLine(snapshot.attempts))
    }

    // MARK: - [T-quota-multikey-perkey] Per-key rows
    func quotaRows(for instance: ProviderInstance) -> [KeyQuota] {
        var rows: [KeyQuota] = []
        if let main = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id),
           !main.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
            var row = KeyQuota(id: "main", title: AppLocalized("主 Key"),
                               badge: AppLocalized("主"), masked: Self.mask(main), isMain: true)
            attach(&row, instanceId: instance.id)
            rows.append(row)
        }
        guard ProviderMultiKeyManager.shared.isEnabled(for: instance.id) else { return rows }
        let ring = ProviderMultiKeyManager.shared.keys(for: instance.id)
        guard !ring.isEmpty else { return rows }
        for (index, key) in ring.enumerated() {
            var row = KeyQuota(id: key.id, title: String(format: AppLocalized("轮询 %lld"), Int64(index + 1)),
                               badge: "\(index + 1)", masked: key.masked, isMain: false)
            attach(&row, instanceId: instance.id)
            rows.append(row)
        }
        return rows
    }
    private func attach(_ row: inout KeyQuota, instanceId: String) {
        let multiKeyOn = ProviderMultiKeyManager.shared.isEnabled(for: instanceId)
        lock.lock(); defer { lock.unlock() }
        let entry = keyCache[instanceId]?[row.id] ?? (row.isMain && !multiKeyOn ? cache[instanceId] : nil)
        row.info = entry?.info.map { Self.reproject($0) }
        row.queriedAt = entry?.fetchedAt
        row.failureNote = failureNotes[failureKey(instanceId, row.id)]
    }
    static func mask(_ key: String) -> String {
        guard key.count > 14 else { return String(repeating: "•", count: 10) }
        return key.prefix(6) + "…" + key.suffix(4)
    }

    // MARK: Refresh scheduling
    func refreshQuota(for instance: ProviderInstance) async {
        let key = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) ?? ""
        await refreshRow(for: instance, key: key, rowId: "main", publishSingle: true)
    }
    func refreshAllIfNeeded(instances: [ProviderInstance]) {
        let missing = instances
            .filter { $0.isEnabled && !ProviderMultiKeyManager.shared.isEnabled(for: $0.id) }
            .filter { isMissing(instanceId: $0.id) }
        guard !missing.isEmpty else { return }
        // [T-quota-foreground-only] Never query a provider while the app is
        // backgrounded: nobody is looking at the number, and it only adds
        // traffic the relay can see.
        guard UIApplication.shared.applicationState == .active else { return }
        Task.detached(priority: .utility) {
            for instance in missing {
                guard UIApplication.shared.applicationState == .active else { return }
                await self.refreshQuota(for: instance)
            }
        }
    }
    func refreshAllKeys(for instance: ProviderInstance) async {
        let rows = quotaRows(for: instance)
        guard !rows.isEmpty else { return }
        var secrets: [String: String] = [:]
        if let main = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) { secrets["main"] = main }
        for key in ProviderMultiKeyManager.shared.keys(for: instance.id) { secrets[key.id] = key.key }
        let active = Set(rows.map(\.id))
        lock.lock()
        keyCache[instance.id] = (keyCache[instance.id] ?? [:]).filter { active.contains($0.key) }
        lock.unlock()
        // At most four keys in flight; each key probes a finite list once.
        await withTaskGroup(of: Void.self) { group in
            var count = 0
            for row in rows {
                guard let secret = secrets[row.id] else { continue }
                if count >= 4 { await group.next() }
                count += 1
                group.addTask {
                    await self.refreshRow(for: instance, key: secret, rowId: row.id, publishSingle: false)
                }
            }
        }
        if let aggregate = publishAggregate(for: instance.id) {
            // [T-quota-disk-cache] Persist the multi-Key aggregate the row shows.
            Self.store(aggregate, instanceId: instance.id, at: Date())
        }
        await MainActor.run { self.revision += 1 }
    }
    private func refreshRow(for instance: ProviderInstance, key: String, rowId: String,
                            publishSingle: Bool) async {
        let slot = failureKey(instance.id, rowId), ticket = UUID()
        lock.lock()
        guard inFlight[slot] == nil else { lock.unlock(); return }
        let epoch = epochs[instance.id] ?? UUID()
        epochs[instance.id] = epoch
        inFlight[slot] = ticket
        lock.unlock()
        let context = await Self.context(for: instance, key: key, rowId: rowId)
        let started = Date()
        if context == nil {
            Self.logger.info("balance query instance=\(instance.id.prefix(8)) row=\(rowId) skipped: no usable credential/root")
        }
        let result: RelayQuotaProtocol.Snapshot?
        if let context { result = await Self.collect(context) } else { result = nil }
        // Verify current stored credentials as well as the generation fence.
        // This catches Keychain replacement before its published event lands.
        let currentKey = rowId == "main" ? ProviderKeychainHelper.loadAPIKey(instanceId: instance.id)
            : ProviderMultiKeyManager.shared.keys(for: instance.id).first(where: { $0.id == rowId })?.key
        let currentContext = await Self.context(for: instance, key: currentKey ?? "", rowId: rowId)
        if context?.owner != currentContext?.owner {
            invalidate(instanceId: instance.id)
            return
        }
        lock.lock()
        guard epochs[instance.id] == epoch, inFlight[slot] == ticket else { lock.unlock(); return }
        inFlight.removeValue(forKey: slot)
        let previous = keyCache[instance.id]?[rowId]?.info ?? (publishSingle ? cache[instance.id]?.info : nil)
        let merged = result?.merging(previous: previous.map { Self.snapshot($0) })
        let info = merged.flatMap { Self.project($0) }
        let entry = CacheEntry(info: info, fetchedAt: Date(), owner: context?.owner ?? "")
        keyCache[instance.id, default: [:]][rowId] = entry
        if publishSingle { cache[instance.id] = entry }
        let notes = result?.attempts.filter { !$0.probeMiss }.compactMap(\.failureNote) ?? []
        if !notes.isEmpty { failureNotes[slot] = Array(Set(notes)).sorted().joined(separator: "；") }
        else if info == nil { failureNotes[slot] = AppLocalized("站点没有返回可用余额（可能不支持余额查询）") }
        else if info?.kind == .used && info?.readings.allSatisfy({ !$0.unlimited && !$0.rejected && $0.total == nil }) == true {
            failureNotes[slot] = AppLocalized("站点只返回了用量，没有返回剩余余额")
        } else { failureNotes.removeValue(forKey: slot) }
        lock.unlock()
        if publishSingle {
            // [T-quota-disk-cache] Persist what the row shows, so the next
            // launch draws it before any request is sent.
            let persisted = entry.info.map { Self.reproject($0) }
            Self.store(persisted, instanceId: instance.id, at: entry.fetchedAt)
            Self.logRefresh(instanceId: instance.id, rowId: rowId, info: persisted,
                            note: notes.first)
            Self.logger.info("balance query instance=\(instance.id.prefix(8)) row=\(rowId) took \(String(format: "%.2f", Date().timeIntervalSince(started)))s")
        }
        await MainActor.run { self.revision += 1 }
    }
    /// Select a representative; never sum balances or compare money to quota
    /// points. Comparisons require the same scope, source, unit and host.
    private func publishAggregate(for instanceId: String) -> QuotaInfo? {
        lock.lock(); defer { lock.unlock() }
        let entries = keyCache[instanceId] ?? [:]
        let ordered = entries.keys.sorted { a, b in a == "main" ? b != "main" : (b == "main" ? false : a < b) }
        let infos = ordered.compactMap { entries[$0]?.info }.map { Self.reproject($0) }
        guard let first = infos.first else {
            cache[instanceId] = CacheEntry(info: nil, fetchedAt: Date(), owner: "")
            return nil
        }
        var selected = first
        if let primary = first.readings.first(where: { $0.id == first.primaryReadingID }) {
            let comparable = infos.filter { info in
                guard let r = info.readings.first(where: { $0.id == info.primaryReadingID }) else { return false }
                return !r.rejected && !r.unlimited && r.remaining != nil && r.scope == primary.scope
                    && r.source == primary.source && r.unit == primary.unit && r.relayHost == primary.relayHost
            }
            selected = comparable.min { a, b in
                let av = a.readings.first { $0.id == a.primaryReadingID }?.remaining ?? .infinity
                let bv = b.readings.first { $0.id == b.primaryReadingID }?.remaining ?? .infinity
                return av < bv
            } ?? first
        }
        cache[instanceId] = CacheEntry(info: selected, fetchedAt: Date(), owner: selected.owner)
        // [T-quota-disk-cache] The caller persists this representative (the
        // same number the row shows) once the lock is released.
        return Self.reproject(selected)
    }

    private struct Context {
        let root: String
        let accountRoot: String
        let key: String
        let token: String?
        let uid: String?
        let cookie: String?
        let owner: String
        let isRelay: Bool
        let anthropic: Bool
    }
    private static func context(for instance: ProviderInstance, key: String, rowId: String) async -> Context? {
        guard instance.isEnabled, instance.credentialType == .apiKey, !key.isEmpty else { return nil }
        let fallback: String
        switch instance.providerType {
        case .openAI, .openAIResponses: fallback = "https://api.openai.com"
        case .anthropic: fallback = "https://api.anthropic.com"
        default: return nil
        }
        guard let root = RelayQuotaProtocol.root(instance.effectiveCustomBaseURL ?? fallback),
              let accountRoot = RelayQuotaProtocol.root(balanceRoot(instanceId: instance.id, apiBase: root)) else { return nil }
        let rawToken = ProviderKeychainHelper.resolvedQuotaAccessToken(instanceId: instance.id, keyId: rowId)
        let token = rawToken?.trimmingCharacters(in: .whitespacesAndNewlines)
        let uid = userID(instanceId: instance.id, keyId: rowId)
        let cookie = token?.isEmpty == false ? nil : await sessionCookieHeader(for: accountRoot)
        // Length-prefix parts: no delimiter ambiguity. Salt limits correlation.
        let parts = [salt, instance.id, rowId, instance.providerType.rawValue, root, accountRoot,
                     key, token ?? "", uid ?? "", cookie ?? ""]
        let input = parts.map { "\($0.utf8.count):" + $0 }.joined()
        let owner = SHA256.hash(data: Data(input.utf8)).map { String(format: "%02x", $0) }.joined()
        let host = URL(string: root)?.host?.lowercased() ?? ""
        return Context(root: root, accountRoot: accountRoot, key: key, token: token, uid: uid,
                       cookie: cookie, owner: owner, isRelay: host != "api.openai.com" && host != "api.anthropic.com",
                       anthropic: instance.providerType == .anthropic)
    }
    static func fetchQuota(for instance: ProviderInstance) async -> QuotaInfo? {
        let key: String?
        switch instance.credentialType {
        case .apiKey: key = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id)
        default: key = nil
        }
        guard let key else { return nil }
        return await fetchQuota(for: instance, key: key)
    }
    static func fetchQuota(for instance: ProviderInstance, key: String,
                           rowId: String = "main") async -> QuotaInfo? {
        guard let ctx = await context(for: instance, key: key, rowId: rowId) else { return nil }
        return project(await collect(ctx))
    }

    private static func get(_ request: URLRequest) async throws -> Data {
        let result: (Data, URLResponse)
        do { result = try await transport.data(for: request) }
        catch { throw RelayQuotaProtocol.Failure.transport }
        guard let http = result.1 as? HTTPURLResponse else { throw RelayQuotaProtocol.Failure.transport }
        guard http.statusCode == 200 else { throw RelayQuotaProtocol.Failure.http(http.statusCode) }
        return result.0
    }
    private static func failure(_ error: Error) -> String {
        (error as? RelayQuotaProtocol.Failure)?.note ?? RelayQuotaProtocol.Failure.transport.note
    }
    private static func collect(_ ctx: Context) async -> RelayQuotaProtocol.Snapshot {
        var readings: [RelayQuotaProtocol.Reading] = []
        var attempts: [RelayQuotaProtocol.Attempt] = []
        // User-saved management token + user ID always get their own query.
        // Account success does NOT short-circuit the independent chat-key probe.
        if ctx.token?.isEmpty == false || ctx.cookie != nil {
            do {
                let values = try await fetchNewAPIBalance(ctx)
                readings += values
                attempts.append(.init(source: .newAPIAccount, endpoint: ctx.accountRoot + "/api/user/self",
                                      attemptedAt: Date(), succeeded: true, failureNote: nil))
            } catch {
                attempts.append(.init(source: .newAPIAccount, endpoint: ctx.accountRoot + "/api/user/self",
                                      attemptedAt: Date(), succeeded: false, failureNote: failure(error)))
            }
        }
        metadataLock.lock(); let hint = relayHints[ctx.owner]; metadataLock.unlock()
        let order: [RelayQuotaProtocol.Source] = ctx.isRelay
            ? (hint.map { [$0] } ?? RelayQuotaProtocol.Source.probeOrder)
            : [ctx.anthropic ? .anthropic : .openAIBilling]
        for source in order {
            do {
                let values = try await query(source, ctx: ctx)
                readings += values
                let incomplete = values.contains { $0.refreshFailed }
                attempts.append(.init(source: source, endpoint: ctx.root + source.path,
                                      attemptedAt: Date(), succeeded: !incomplete,
                                      failureNote: incomplete ? "用量查询失败或字段缺失；余量未知或保留上次读数" : nil))
                if ctx.isRelay {
                    metadataLock.lock(); relayHints[ctx.owner] = source; metadataLock.unlock()
                }
                break
            } catch {
                attempts.append(.init(source: source, endpoint: ctx.root + source.path,
                                      attemptedAt: Date(), succeeded: false, failureNote: failure(error), probeMiss: hint == nil))
                // A remembered family never triggers a fallback storm on auth,
                // rate or transport failures. 404 permits re-detection NEXT refresh.
                if case RelayQuotaProtocol.Failure.http(404) = error {
                    metadataLock.lock(); relayHints.removeValue(forKey: ctx.owner); metadataLock.unlock()
                }
            }
        }
        if !attempts.contains(where: { $0.succeeded && $0.source != .newAPIAccount }) {
            for index in attempts.indices { attempts[index].probeMiss = false }
        }
        return .init(owner: ctx.owner, readings: readings, attempts: attempts)
    }
    private static func fetchNewAPIBalance(_ ctx: Context) async throws -> [RelayQuotaProtocol.Reading] {
        let req = try RelayQuotaProtocol.request(root: ctx.accountRoot, source: .newAPIAccount,
                                                chatKey: nil, accountToken: ctx.token, userID: ctx.uid, cookie: ctx.cookie)
        // [T-quota-parallel-scale] Ask for the ratio while the balance request
        // is still in flight. Serially this was two round trips on every
        // refresh — the 4-5s entries in the device log.
        async let pendingScale = siteScale(root: ctx.accountRoot)
        let data = try await get(req), observedAt = Date()
        _ = try RelayQuotaProtocol.parseAccount(data, root: ctx.accountRoot, now: observedAt, scale: nil)
        let scale = await pendingScale
        return try RelayQuotaProtocol.parseAccount(data, root: ctx.accountRoot, now: observedAt, scale: scale)
    }
    private static func query(_ source: RelayQuotaProtocol.Source, ctx: Context) async throws -> [RelayQuotaProtocol.Reading] {
        var req = try RelayQuotaProtocol.request(root: ctx.root, source: source,
                                                chatKey: ctx.key, accountToken: nil, userID: nil)
        if source == .anthropic {
            req.url = monthURL(req.url!, anthropic: true)
        }
        let data = try await get(req), observedAt = Date()
        switch source {
        case .sub2api:
            return try RelayQuotaProtocol.parseSub2API(data, root: ctx.root, now: observedAt)
        case .newAPIKey:
            _ = try RelayQuotaProtocol.parseNewAPI(data, root: ctx.root, now: observedAt, scale: nil)
            let scale = await siteScale(root: ctx.root)
            return try RelayQuotaProtocol.parseNewAPI(data, root: ctx.root, now: observedAt, scale: scale)
        case .openAIBilling:
            return try await fetchOpenAIBillingQuota(data, request: req, root: ctx.root, observedAt: observedAt)
        case .anthropic:
            return try RelayQuotaProtocol.parseAnthropic(data, root: ctx.root, now: observedAt)
        case .newAPIAccount: throw RelayQuotaProtocol.Failure.unsupported
        }
    }
    private static func fetchOpenAIBillingQuota(_ subscription: Data, request: URLRequest, root: String,
                                               observedAt: Date) async throws -> [RelayQuotaProtocol.Reading] {
        var req = request
        guard let url = RelayQuotaProtocol.endpoint(root: root, path: "/v1/dashboard/billing/usage") else {
            throw RelayQuotaProtocol.Failure.invalidURL
        }
        req.url = monthURL(url, anthropic: false)
        let usage = try? await get(req)
        var readings = try RelayQuotaProtocol.parseBilling(subscription, usage: usage, root: root, now: observedAt)
        if readings.first?.used != nil { readings[0].usedObservedAt = Date() }
        // A failed usage half cannot replace a previous full remainder with an
        // invented zero usage. Explicit USD balance is independently usable.
        if readings.first?.used == nil { readings[0].refreshFailed = true }
        return readings
    }
    private static func monthURL(_ url: URL, anthropic: Bool) -> URL {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(secondsFromGMT: 0)!
        let now = Date()
        let start = calendar.date(from: calendar.dateComponents([.year, .month], from: now)) ?? now
        var comps = URLComponents(url: url, resolvingAgainstBaseURL: false)!
        if anthropic {
            comps.queryItems = [URLQueryItem(name: "starting_at", value: ISO8601DateFormatter().string(from: start)),
                                URLQueryItem(name: "ending_at", value: ISO8601DateFormatter().string(from: now)),
                                URLQueryItem(name: "limit", value: "1")]
        } else {
            let df = DateFormatter()
            df.locale = Locale(identifier: "en_US_POSIX"); df.timeZone = calendar.timeZone; df.dateFormat = "yyyy-MM-dd"
            comps.queryItems = [URLQueryItem(name: "start_date", value: df.string(from: start)),
                                URLQueryItem(name: "end_date", value: df.string(from: now))]
        }
        return comps.url ?? url
    }
    static let relayPlaceholderLimitUSD: Double = RelayQuotaProtocol.placeholderLimitUSD
    static func apiRoot(_ baseURL: String) -> String { RelayQuotaProtocol.root(baseURL) ?? "" }

    /// Public site metadata: no Authorization/Cookie, per-root in-flight
    /// coalescing and 5-minute positive AND negative cache. No default USD rate.
    private static let scalePrefix = "quota.qpu."

    private static func storeScale(_ value: Double, root: String) {
        guard value > 0 else { return }
        UserDefaults.standard.set(value, forKey: scalePrefix + root)
    }

    /// Last ratio this site published, reused when today's request fails.
    private static func storedScale(root: String) -> RelayQuotaProtocol.Scale? {
        let value = UserDefaults.standard.double(forKey: scalePrefix + root)
        guard value > 0 else { return nil }
        return RelayQuotaProtocol.Scale(quotaPerUnit: value, observedAt: Date(),
                                        endpoint: root + "/api/status")
    }

    private static func siteScale(root: String) async -> RelayQuotaProtocol.Scale? {
        metadataLock.lock()
        if let cached = scales[root], Date().timeIntervalSince(cached.1) < 300 {
            metadataLock.unlock(); return cached.0
        }
        if let pending = scaleTasks[root] { metadataLock.unlock(); return await pending.value }
        let task = Task<RelayQuotaProtocol.Scale?, Never> {
            guard let url = RelayQuotaProtocol.endpoint(root: root, path: "/api/status") else { return nil }
            var req = URLRequest(url: url)
            req.timeoutInterval = 8; req.httpShouldHandleCookies = false
            guard let data = try? await get(req),
                  let fresh = RelayQuotaProtocol.scale(data, root: root, now: Date()) else {
                // [T-quota-qpu-persist] A relay that answered once keeps its
                // ratio across launches. Without this a failed /api/status
                // turned the next reading into raw quota points, which the row
                // then showed as a huge bogus number (11817571.00 quota).
                return Self.storedScale(root: root)
            }
            Self.storeScale(fresh.quotaPerUnit, root: root)
            return fresh
        }
        scaleTasks[root] = task
        metadataLock.unlock()
        let result = await task.value
        metadataLock.lock()
        scales[root] = (result, Date()); scaleTasks.removeValue(forKey: root)
        metadataLock.unlock()
        return result
    }
    static func quotaPerUnit(root: String) async -> Double? {
        await siteScale(root: root)?.quotaPerUnit
    }

    static func sessionCookieHeader(for root: String) async -> String? {
        guard let url = RelayQuotaProtocol.endpoint(root: root, path: "/api/user/self"), let host = url.host else { return nil }
        let cookies: [HTTPCookie] = await withCheckedContinuation { continuation in
            DispatchQueue.main.async {
                WKWebsiteDataStore.default().httpCookieStore.getAllCookies { continuation.resume(returning: $0) }
            }
        }
        let now = Date()
        let relevant = cookies.filter { cookie in
            let domain = cookie.domain.hasPrefix(".") ? String(cookie.domain.dropFirst()) : cookie.domain
            let path = cookie.path
            let pathMatches = url.path == path || (url.path.hasPrefix(path) && (path.hasSuffix("/") || url.path.dropFirst(path.count).hasPrefix("/")))
            return (host == domain || host.hasSuffix("." + domain)) && pathMatches
                && (!cookie.isSecure || url.scheme == "https") && (cookie.expiresDate.map { $0 > now } ?? true)
        }.sorted { $0.name < $1.name }
        guard !relevant.isEmpty else { return nil }
        return relevant.map { "\($0.name)=\($0.value)" }.joined(separator: "; ")
    }
    static func hasBalanceCredential(instanceId: String) async -> Bool {
        ProviderKeychainHelper.loadQuotaAccessToken(instanceId: instanceId)?.isEmpty == false
    }

    static func panelBaseURL(instanceId: String) -> String? {
        let raw = UserDefaults.standard.string(forKey: "quota.panelBaseURL.\(instanceId)") ?? ""
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    static func setPanelBaseURL(_ url: String, instanceId: String) {
        let normalized = normalizePanelURL(url) ?? ""
        UserDefaults.standard.set(normalized, forKey: "quota.panelBaseURL.\(instanceId)")
        shared.invalidate(instanceId: instanceId)
    }

    /// Reduce whatever the user pasted to scheme + host + port.
    ///
    /// Reported 2026-10-21: the field held
    /// `https://www.cun.ai/profile` — a full page URL copied from the browser —
    /// so the balance request became `…/profile/api/user/self` and 404'd. A
    /// panel address is a HOST, not a page; anything after the host is dropped,
    /// and a bare `cun.ai` gets an https scheme so it is a usable URL.
    static func normalizePanelURL(_ raw: String) -> String? {
        var text = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !text.isEmpty else { return nil }
        if !text.lowercased().hasPrefix("http://"), !text.lowercased().hasPrefix("https://") {
            text = "https://" + text
        }
        guard let parsed = URL(string: text), let host = parsed.host, !host.isEmpty else { return nil }
        var comps = URLComponents()
        comps.scheme = parsed.scheme ?? "https"
        comps.host = host
        comps.port = parsed.port
        return comps.url?.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
    }

    /// [T-quota-newapi-user] `New-Api-User` header value.
    ///
    /// New API's `/api/user/self` rejects an otherwise valid access token with
    /// 「Unauthorized, New-Api-User header not provided」 unless the numeric user
    /// id rides along in a header of that name. The id is printed on the site's
    /// own dashboard ("用户 ID"), so it is one number the user copies once.
    static func userID(instanceId: String, keyId: String? = nil) -> String? {
        let defaults = UserDefaults.standard
        // Per-key first: two keys under one provider can belong to two
        // different site accounts, each with its own numeric user id.
        if let keyId, !keyId.isEmpty {
            let raw = defaults.string(forKey: "quota.newAPIUserID.\(instanceId).\(keyId)") ?? ""
            let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            if !trimmed.isEmpty { return trimmed }
        }
        let raw = defaults.string(forKey: "quota.newAPIUserID.\(instanceId)") ?? ""
        let trimmed = raw.trimmingCharacters(in: .whitespacesAndNewlines)
        return trimmed.isEmpty ? nil : trimmed
    }

    static func setUserID(_ value: String, instanceId: String, keyId: String? = nil) {
        let trimmed = value.trimmingCharacters(in: .whitespacesAndNewlines)
        let key: String
        if let keyId, !keyId.isEmpty {
            key = "quota.newAPIUserID.\(instanceId).\(keyId)"
        } else {
            key = "quota.newAPIUserID.\(instanceId)"
        }
        if trimmed.isEmpty {
            UserDefaults.standard.removeObject(forKey: key)
        } else {
            UserDefaults.standard.set(trimmed, forKey: key)
        }
        shared.invalidate(instanceId: instanceId)
    }

    /// Root for the balance endpoints: the configured panel host when present,
    /// else the API host with `/v1` stripped.
    static func balanceRoot(instanceId: String, apiBase: String) -> String {
        if let stored = panelBaseURL(instanceId: instanceId),
           let panel = normalizePanelURL(stored) {
            return panel
        }
        return apiRoot(apiBase)
    }

    static var lowThresholdUSD: Double {
        let stored = UserDefaults.standard.object(forKey: lowThresholdDefaultsKey) as? Double
        guard let stored, stored.isFinite, stored >= 0 else { return 3.0 }
        return stored
    }

}

private final class ProviderQuotaCookieObserver: NSObject, WKHTTPCookieStoreObserver {
    private let changed: () -> Void
    init(changed: @escaping () -> Void) { self.changed = changed }
    func cookiesDidChange(in cookieStore: WKHTTPCookieStore) { changed() }
}

// MARK: - [T-turn-cost-site-pricing] Auto-read New API / One API pricing

/// Reads a site's own `/api/pricing` endpoint and turns its ratios into
/// per-million-token USD prices. Triggered only by the user's button; this
/// never runs in the chat path, so an unreachable site cannot delay a message.
final class ProviderPricingService: ObservableObject {
    static let shared = ProviderPricingService()

    struct ModelPrice: Codable, Equatable {
        /// USD per 1M input tokens. nil for per-call models.
        var input: Double?
        /// USD per 1M output tokens. nil for per-call models.
        var output: Double?
        /// USD per call for quota_type != 0 models.
        var fixed: Double?
    }

    struct SitePricing: Codable, Equatable {
        var group: String
        var groupRatio: Double
        var quotaPerUnit: Double
        var fetchedAt: Date
        var prices: [String: ModelPrice]
        /// Site's `/api/status.usd_exchange_rate`, when provided.
        var exchangeRate: Double? = nil
    }

    @Published private(set) var revision = 0
    private let keyPrefix = "pricing.site."
    private let manualPrefix = "pricing.manual."
    private let ratePrefix = "pricing.rateOverride."
    private let currencyPrefix = "pricing.currency."
    private let customCurrencyPrefix = "pricing.customCurrency."
    private let customRatePrefix = "pricing.customRate."
    private let lock = NSLock()
    private var cache: [String: SitePricing] = [:]

    private init() {}

    func pricing(for instanceId: String) -> SitePricing? {
        lock.lock(); defer { lock.unlock() }
        if let cached = cache[instanceId] { return cached }
        guard let data = UserDefaults.standard.data(forKey: keyPrefix + instanceId),
              let decoded = try? JSONDecoder().decode(SitePricing.self, from: data) else { return nil }
        cache[instanceId] = decoded
        return decoded
    }

    /// A user-entered override for one model. Manual beats site pricing: it
    /// exists precisely for sites whose endpoint is absent or wrong.
    func manualPrice(instanceId: String, modelId: String) -> ModelPrice? {
        guard let data = UserDefaults.standard.data(forKey: manualPrefix + instanceId),
              let map = try? JSONDecoder().decode([String: ModelPrice].self, from: data) else { return nil }
        return map[modelId.lowercased()]
    }

    func setManualPrice(instanceId: String, modelId: String, input: Double?, output: Double?) {
        var map: [String: ModelPrice] = [:]
        if let data = UserDefaults.standard.data(forKey: manualPrefix + instanceId),
           let decoded = try? JSONDecoder().decode([String: ModelPrice].self, from: data) {
            map = decoded
        }
        if let input, let output, input > 0, output > 0 {
            map[modelId.lowercased()] = ModelPrice(input: input, output: output, fixed: nil)
        } else {
            map.removeValue(forKey: modelId.lowercased())
        }
        if let data = try? JSONEncoder().encode(map) {
            UserDefaults.standard.set(data, forKey: manualPrefix + instanceId)
        }
        DispatchQueue.main.async { self.revision += 1 }
    }

    func price(instanceId: String, modelId: String) -> ModelPrice? {
        manualPrice(instanceId: instanceId, modelId: modelId)
            ?? pricing(for: instanceId)?.prices[modelId.lowercased()]
    }

    /// Per-provider conversion override. nil means "use the rate the site
    /// publishes, then the global display rate". Stored by instance because
    /// relays quote different CNY rates.
    func rateOverride(instanceId: String) -> Double? {
        let value = UserDefaults.standard.double(forKey: ratePrefix + instanceId)
        return value > 0 ? value : nil
    }

    func setRateOverride(instanceId: String, rate: Double?) {
        let key = ratePrefix + instanceId
        if let rate, rate > 0 {
            UserDefaults.standard.set(rate, forKey: key)
        } else {
            UserDefaults.standard.removeObject(forKey: key)
        }
        DispatchQueue.main.async { self.revision += 1 }
    }

    func effectiveRate(instanceId: String) -> Double? {
        rateOverride(instanceId: instanceId)
            ?? pricing(for: instanceId)?.exchangeRate
    }

    /// Per-provider display currency. The global Settings value remains the
    /// fallback for providers the user never opened.
    func displayCurrency(instanceId: String) -> String {
        if let custom = customCurrency(instanceId: instanceId) { return custom }
        let key = currencyPrefix + instanceId
        guard let stored = UserDefaults.standard.string(forKey: key)?.uppercased(),
              stored == "CNY" || stored == "USD" else { return TurnCost.currency }
        return stored
    }

    func setDisplayCurrency(instanceId: String, currency: String) {
        let code = currency.uppercased()
        guard code == "CNY" || code == "USD" else { return }
        UserDefaults.standard.set(code, forKey: currencyPrefix + instanceId)
        // Choosing a built-in currency must clear a previous custom override,
        // otherwise the cost would keep using the hidden custom code.
        clearCustomCurrency(instanceId: instanceId)
        DispatchQueue.main.async { self.revision += 1 }
    }

    /// A user-entered ISO-style code, e.g. EUR. Returns nil when not configured.
    func customCurrency(instanceId: String) -> String? {
        let raw = UserDefaults.standard.string(forKey: customCurrencyPrefix + instanceId) ?? ""
        let code = raw.uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        guard code.count >= 2, code.count <= 8,
              code.unicodeScalars.allSatisfy({ CharacterSet.uppercaseLetters.contains($0) }),
              customRate(instanceId: instanceId) != nil else { return nil }
        return code
    }

    /// Units of the custom currency per 1 USD.
    func customRate(instanceId: String) -> Double? {
        let value = UserDefaults.standard.double(forKey: customRatePrefix + instanceId)
        return value > 0 ? value : nil
    }

    func setCustomCurrency(instanceId: String, code: String?, rate: Double?) {
        let normalized = (code ?? "").uppercased().trimmingCharacters(in: .whitespacesAndNewlines)
        if normalized.count >= 2, normalized.count <= 8,
           normalized.unicodeScalars.allSatisfy({ CharacterSet.uppercaseLetters.contains($0) }),
           let rate, rate > 0 {
            UserDefaults.standard.set(normalized, forKey: customCurrencyPrefix + instanceId)
            UserDefaults.standard.set(rate, forKey: customRatePrefix + instanceId)
        } else {
            clearCustomCurrency(instanceId: instanceId)
        }
        DispatchQueue.main.async { self.revision += 1 }
    }

    private func clearCustomCurrency(instanceId: String) {
        UserDefaults.standard.removeObject(forKey: customCurrencyPrefix + instanceId)
        UserDefaults.standard.removeObject(forKey: customRatePrefix + instanceId)
    }

    /// Rate used by the cost display: custom units/USD, else site/global CNY.
    func effectiveDisplayRate(instanceId: String) -> Double? {
        if customCurrency(instanceId: instanceId) != nil {
            return customRate(instanceId: instanceId)
        }
        return effectiveRate(instanceId: instanceId)
    }

    func summary(for instanceId: String) -> (count: Int, date: Date?)? {
        guard let p = pricing(for: instanceId) else { return nil }
        return (p.prices.count, p.fetchedAt)
    }

    /// Public `/api/status` carries the site's own CNY rate. This is display
    /// metadata only; no credential is sent.
    private static func siteExchangeRate(root: String) async -> Double? {
        guard let url = URL(string: root + "/api/status") else { return nil }
        var req = URLRequest(url: url)
        req.timeoutInterval = 8
        guard let (data, resp) = try? await URLSession.shared.data(for: req),
              let http = resp as? HTTPURLResponse, http.statusCode == 200,
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let payload = obj["data"] as? [String: Any],
              let rate = (payload["usd_exchange_rate"] as? NSNumber)?.doubleValue,
              rate > 0 else { return nil }
        return rate
    }

    /// One explicit request. Returns the number of models read.
    func refresh(for instance: ProviderInstance) async throws -> Int {
        var base = instance.effectiveCustomBaseURL
        if base == nil {
            switch instance.providerType {
            case .openAI, .openAIResponses: base = "https://api.openai.com"
            case .anthropic: base = "https://api.anthropic.com"
            default: throw NSError(domain: "ProviderPricing", code: 1,
                                   userInfo: [NSLocalizedDescriptionKey: AppLocalized("该供应商不支持站点定价")])
            }
        }
        guard let base, !base.isEmpty else {
            throw NSError(domain: "ProviderPricing", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: AppLocalized("没有可用的站点地址")])
        }
        let root = ProviderQuotaService.balanceRoot(instanceId: instance.id, apiBase: base)
        guard let url = URL(string: root + "/api/pricing") else {
            throw NSError(domain: "ProviderPricing", code: 1,
                          userInfo: [NSLocalizedDescriptionKey: AppLocalized("站点地址无效")])
        }
        var req = URLRequest(url: url)
        req.timeoutInterval = 15
        req.setValue("application/json", forHTTPHeaderField: "Accept")
        let (data, resp) = try await URLSession.shared.data(for: req)
        guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
            let code = (resp as? HTTPURLResponse)?.statusCode ?? -1
            throw NSError(domain: "ProviderPricing", code: Int(code),
                          userInfo: [NSLocalizedDescriptionKey: String(format: AppLocalized("站点没有开放定价接口（HTTP %lld）"), Int64(code))])
        }
        guard let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let rows = obj["data"] as? [[String: Any]] else {
            throw NSError(domain: "ProviderPricing", code: 2,
                          userInfo: [NSLocalizedDescriptionKey: AppLocalized("返回格式不是 New API 定价")])
        }
        if (obj["success"] as? Bool) == false {
            throw NSError(domain: "ProviderPricing", code: 3,
                          userInfo: [NSLocalizedDescriptionKey: AppLocalized("站点拒绝读取定价")])
        }

        let groupRatios = (obj["group_ratio"] as? [String: Any]) ?? [:]
        let group = groupRatios["default"] != nil ? "default" : (groupRatios.keys.sorted().first ?? "default")
        let groupRatio = (groupRatios[group] as? NSNumber)?.doubleValue ?? 1.0
        guard let qpu = await ProviderQuotaService.quotaPerUnit(root: root) else {
            throw NSError(domain: "ProviderPricing", code: 5,
                          userInfo: [NSLocalizedDescriptionKey: AppLocalized("站点未返回额度换算率，不能推算美元价格")])
        }
        let siteRate = await Self.siteExchangeRate(root: root)

        var prices: [String: ModelPrice] = [:]
        for row in rows {
            guard let name = (row["model_name"] as? String)?.lowercased(), !name.isEmpty else { continue }
            let ratio = (row["model_ratio"] as? NSNumber)?.doubleValue ?? 0
            let completion = (row["completion_ratio"] as? NSNumber)?.doubleValue ?? 1
            let quotaType = (row["quota_type"] as? NSNumber)?.intValue ?? 0
            let modelPrice = (row["model_price"] as? NSNumber)?.doubleValue ?? 0
            if quotaType != 0 {
                if modelPrice > 0 { prices[name] = ModelPrice(input: nil, output: nil, fixed: modelPrice) }
                continue
            }
            guard ratio > 0, qpu > 0 else { continue }
            let input = ratio * groupRatio * 1_000_000.0 / qpu
            let output = input * completion
            if input > 0 { prices[name] = ModelPrice(input: input, output: output, fixed: nil) }
        }
        guard !prices.isEmpty else {
            throw NSError(domain: "ProviderPricing", code: 4,
                          userInfo: [NSLocalizedDescriptionKey: AppLocalized("站点没有返回可用的模型价格")])
        }
        let value = SitePricing(group: group, groupRatio: groupRatio,
                                quotaPerUnit: qpu, fetchedAt: Date(), prices: prices,
                                exchangeRate: siteRate)
        lock.lock()
        cache[instance.id] = value
        lock.unlock()
        if let encoded = try? JSONEncoder().encode(value) {
            UserDefaults.standard.set(encoded, forKey: keyPrefix + instance.id)
        }
        await MainActor.run { self.revision += 1 }
        return prices.count
    }
}