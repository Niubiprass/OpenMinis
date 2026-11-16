import Foundation
import UIKit
import WebKit
import Combine
import CryptoKit

// BEGIN QUOTA_CURRENT_KEY_PURE
/// Shared by production and offline Swift fixtures. No credential or transport.
enum ProviderQuotaCurrentKeyPolicy {
    struct Origin: Codable, Equatable {
        let rowId: String
        let owner: String
    }
    static func current(lastSuccess: Origin?, available: [Origin]) -> Origin? {
        if let lastSuccess, available.contains(lastSuccess) { return lastSuccess }
        return available.first { $0.rowId == "main" }
    }
    static func canRestore(_ stored: Origin, current: Origin?) -> Bool {
        current == stored && !stored.owner.isEmpty
    }
    static func mayCommitResolution(captured: Origin?, current: Origin?,
                                    capturedSuccessAt: Date?, currentSuccessAt: Date?) -> Bool {
        captured == current && capturedSuccessAt == currentSuccessAt
    }
    struct RefreshClock {
        var dirty = false
        var lastSuccessAt: Date?
        var lastAttemptAt: Date?
        var retryAt: Date?
        var failures = 0
        var running = false
        mutating func consumed(at now: Date) {
            dirty = true
            lastSuccessAt = now
        }
        func deadline(active: Bool, now: Date) -> Date? {
            guard active, dirty, !running else { return nil }
            return [now, lastSuccessAt?.addingTimeInterval(2) ?? now,
                    lastAttemptAt?.addingTimeInterval(30) ?? now, retryAt ?? now].max()
        }
        mutating func begin(at now: Date) {
            dirty = false; running = true; lastAttemptAt = now
        }
        mutating func finish(at now: Date, succeeded: Bool, retryAfter: TimeInterval? = nil) {
            running = false
            if succeeded { failures = 0; retryAt = nil }
            else {
                failures = min(failures + 1, 5)
                let delay = max(30 * pow(2, Double(failures - 1)), retryAfter ?? 0)
                retryAt = now.addingTimeInterval(min(900, max(30, delay)))
                // No autonomous retry loop. New consumption/foreground TTL retries.
            }
        }
        mutating func cancelled() { running = false; dirty = true }
    }
    static func retryAfter(_ header: String?, at now: Date) -> TimeInterval? {
        guard let header else { return nil }
        if let seconds = Double(header), seconds.isFinite {
            return min(900, max(30, seconds))
        }
        let parser = DateFormatter()
        parser.locale = Locale(identifier: "en_US_POSIX")
        parser.timeZone = TimeZone(secondsFromGMT: 0)
        parser.dateFormat = "EEE, dd MMM yyyy HH:mm:ss zzz"
        return parser.date(from: header).map { min(900, max(30, $0.timeIntervalSince(now))) }
    }
}
// END QUOTA_CURRENT_KEY_PURE

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
    /// v1 was an unowned lowest-key summary; never replay it as current Key.
    /// v2 stores each row's origin (salted one-way identity, never credentials).
    private struct StoredQuota: Codable {
        let origin: ProviderQuotaCurrentKeyPolicy.Origin
        let displayText: String
        let amountUSD: Double?
        let balanceUSD: Double?
        let kindIsBalance: Bool
        let highlighted: Bool
        let fetchedAt: Date
        let observedAt: Date?
    }
    private static let storedPrefix = "quota.lastKnown.v2."
    private static let currentPrefix = "quota.currentRow.v2."
    private static let durableSalt: String = {
        let slot = "quota.cacheOriginSalt.v2"
        if let value = UserDefaults.standard.string(forKey: slot) { return value }
        let value = UUID().uuidString
        UserDefaults.standard.set(value, forKey: slot)
        return value
    }()

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

    private static func store(_ info: QuotaInfo?, instanceId: String,
                              origin: ProviderQuotaCurrentKeyPolicy.Origin, at date: Date) {
        let key = storedPrefix + instanceId + "." + origin.rowId
        guard let info else { UserDefaults.standard.removeObject(forKey: key); return }
        let value = StoredQuota(origin: origin, displayText: info.displayText,
                                amountUSD: info.amountUSD, balanceUSD: info.balanceUSD,
                                kindIsBalance: info.kind == .balance, highlighted: info.highlighted,
                                fetchedAt: date, observedAt: info.observedAt)
        guard let data = try? JSONEncoder().encode(value) else { return }
        UserDefaults.standard.set(data, forKey: key)
    }

    private static func storedInfo(instanceId: String, origin: ProviderQuotaCurrentKeyPolicy.Origin,
                                   processOwner: String) -> (info: QuotaInfo, fetchedAt: Date)? {
        guard let data = UserDefaults.standard.data(forKey: storedPrefix + instanceId + "." + origin.rowId),
              let value = try? JSONDecoder().decode(StoredQuota.self, from: data),
              ProviderQuotaCurrentKeyPolicy.canRestore(value.origin, current: origin) else { return nil }
        let info = QuotaInfo(displayText: value.displayText, highlighted: false,
                             kind: value.kindIsBalance ? .balance : .used,
                             balanceUSD: value.balanceUSD, amountUSD: value.amountUSD,
                             observedAt: value.observedAt, isStale: true, owner: processOwner)
        return (info, value.fetchedAt)
    }
    private static func storedCurrent(_ instanceId: String) -> ProviderQuotaCurrentKeyPolicy.Origin? {
        guard let data = UserDefaults.standard.data(forKey: currentPrefix + instanceId) else { return nil }
        return try? JSONDecoder().decode(ProviderQuotaCurrentKeyPolicy.Origin.self, from: data)
    }

    private struct CacheEntry {
        let info: QuotaInfo?
        let fetchedAt: Date // attempt time, NOT the successful observation time
        let owner: String
        var origin: ProviderQuotaCurrentKeyPolicy.Origin? = nil
    }
    private var cache: [String: CacheEntry] = [:]
    private var keyCache: [String: [String: CacheEntry]] = [:]
    private var failureNotes: [String: String] = [:]
    private var inFlight: [String: UUID] = [:]
    private var epochs: [String: UUID] = [:]
    private var currentOrigins: [String: ProviderQuotaCurrentKeyPolicy.Origin] = [:]
    private var rowOrigins: [String: [String: ProviderQuotaCurrentKeyPolicy.Origin]] = [:]
    // A disabled row may still be manually inspected, but never becomes the
    // representative. Cache ownership and request selectability are distinct.
    private var selectableOrigins: [String: [String: ProviderQuotaCurrentKeyPolicy.Origin]] = [:]
    private var validating = Set<String>()
    private var clocks: [String: ProviderQuotaCurrentKeyPolicy.RefreshClock] = [:]
    private var scheduled: [String: Task<Void, Never>] = [:]
    private var fallbackTask: Task<Void, Never>?
    private var lastPublished: [String: String] = [:]
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
                    .sink { [weak self] note in
                        guard note.userInfo?["quotaCredentialsUnchanged"] as? Bool != true else { return }
                        if let id = note.object as? String { self?.invalidate(instanceId: id) }
                        else { self?.invalidateAll() }
                    },
                NotificationCenter.default.publisher(for: ProviderMultiKeyManager.didSucceed)
                    .sink { [weak self] note in
                        guard let success = note.object as? ProviderQuotaSuccess else { return }
                        self?.consumed(success)
                    },
                NotificationCenter.default.publisher(for: UIApplication.didBecomeActiveNotification)
                    .sink { [weak self] _ in
                        self?.refreshAllIfNeeded(instances: store.instances)
                        self?.startForegroundFallback()
                    },
                NotificationCenter.default.publisher(for: UIApplication.didEnterBackgroundNotification)
                    .sink { [weak self] _ in self?.suspendAutomaticRefresh() }
            ]
            let observer = ProviderQuotaCookieObserver { [weak self] in self?.invalidateAll() }
            self.cookieObserver = observer
            WKWebsiteDataStore.default().httpCookieStore.add(observer)
            self.startForegroundFallback()
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
        let needsValidation = currentOrigins[instanceId] == nil && !validating.contains(instanceId)
        lock.unlock()
        // Never do Keychain XPC in a SwiftUI body or expose unverified v1 data.
        if needsValidation { warmCurrent(instanceId: instanceId) }
        return live
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
        currentOrigins.removeAll(); rowOrigins.removeAll(); selectableOrigins.removeAll(); validating.removeAll()
        epochs.removeAll(); inFlight.removeAll()
        for task in scheduled.values { task.cancel() }; scheduled.removeAll()
        clocks = clocks.mapValues { value in var clock = value; clock.cancelled(); return clock }
        lock.unlock()
        Self.metadataLock.lock(); Self.relayHints.removeAll(); Self.metadataLock.unlock()
        Task { @MainActor in self.revision += 1 }
    }
    func invalidate(instanceId: String) {
        lock.lock()
        cache.removeValue(forKey: instanceId)
        keyCache.removeValue(forKey: instanceId)
        currentOrigins.removeValue(forKey: instanceId); rowOrigins.removeValue(forKey: instanceId)
        selectableOrigins.removeValue(forKey: instanceId)
        validating.remove(instanceId)
        scheduled.removeValue(forKey: instanceId)?.cancel()
        clocks[instanceId, default: .init()].cancelled()
        failureNotes = failureNotes.filter { !$0.key.hasPrefix(instanceId + "|") }
        inFlight = inFlight.filter { !$0.key.hasPrefix(instanceId + "|") }
        epochs[instanceId] = UUID()
        lock.unlock()
        Self.metadataLock.lock(); Self.relayHints.removeAll(); Self.metadataLock.unlock()
        Task { @MainActor in self.revision += 1 }
    }

    private func invalidateRow(instanceId: String, rowId: String, epoch: UUID, ticket: UUID,
                               capturedOwner: String?) {
        let slot = failureKey(instanceId, rowId)
        lock.lock()
        guard epochs[instanceId] == epoch, inFlight[slot] == ticket else { lock.unlock(); return }
        inFlight.removeValue(forKey: slot)
        let activeOrigin = rowOrigins[instanceId]?[rowId] ?? keyCache[instanceId]?[rowId]?.origin
        let currentOrigin = currentOrigins[instanceId] ?? Self.storedCurrent(instanceId)
        // A successful request may have installed a newer owner without a
        // config notification/epoch change. Only retire the captured old owner.
        guard activeOrigin == nil || activeOrigin?.owner == capturedOwner,
              currentOrigin?.rowId != rowId || currentOrigin?.owner == capturedOwner else { lock.unlock(); return }
        keyCache[instanceId]?.removeValue(forKey: rowId)
        rowOrigins[instanceId]?.removeValue(forKey: rowId)
        selectableOrigins[instanceId]?.removeValue(forKey: rowId)
        failureNotes.removeValue(forKey: slot)
        if currentOrigins[instanceId]?.rowId == rowId { currentOrigins.removeValue(forKey: instanceId) }
        UserDefaults.standard.removeObject(forKey: Self.storedPrefix + instanceId + "." + rowId)
        if let saved = Self.storedCurrent(instanceId), saved.rowId == rowId, saved.owner == capturedOwner {
            UserDefaults.standard.removeObject(forKey: Self.currentPrefix + instanceId)
        }
        lock.unlock()
        _ = publishAggregate(for: instanceId)
        publishRevision(instanceId)
        // No sibling ticket, cache, epoch or retry clock is invalidated here.
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
        let candidate = keyCache[instanceId]?[row.id] ?? (row.isMain && !multiKeyOn ? cache[instanceId] : nil)
        let entry = candidate?.origin == rowOrigins[instanceId]?[row.id] ? candidate : nil
        row.info = entry?.info.map { Self.reproject($0) }
        row.queriedAt = entry?.fetchedAt
        row.failureNote = failureNotes[failureKey(instanceId, row.id)]
    }
    static func mask(_ key: String) -> String {
        guard key.count > 14 else { return String(repeating: "•", count: 10) }
        return key.prefix(6) + "…" + key.suffix(4)
    }

    // MARK: Refresh scheduling
    private static func rowKey(_ instanceId: String, rowId: String, includingUnavailable: Bool = false) -> String? {
        if rowId == "main" { return ProviderKeychainHelper.loadAPIKey(instanceId: instanceId) }
        guard ProviderMultiKeyManager.shared.isEnabled(for: instanceId) else { return nil }
        return ProviderMultiKeyManager.shared.keys(for: instanceId).first {
            $0.id == rowId && (includingUnavailable || ($0.isEnabled && $0.status != .disabled))
        }?.key
    }
    private func warmCurrent(instanceId: String) {
        lock.lock()
        guard !validating.contains(instanceId) else { lock.unlock(); return }
        validating.insert(instanceId)
        let epoch = epochs[instanceId] ?? UUID(); epochs[instanceId] = epoch
        lock.unlock()
        Task.detached(priority: .utility) { _ = await self.resolveCurrent(instanceId, epoch: epoch) }
    }
    @discardableResult
    private func resolveCurrent(_ instanceId: String, epoch: UUID) async -> Context? {
        let instance = await MainActor.run { ProviderConfigStore.shared.instance(for: instanceId) }
        guard let instance else {
            lock.lock()
            if epochs[instanceId] == epoch { validating.remove(instanceId) }
            lock.unlock(); return nil
        }
        lock.lock()
        guard epochs[instanceId] == epoch else { lock.unlock(); return nil }
        let last = currentOrigins[instanceId] ?? Self.storedCurrent(instanceId)
        let lastSuccessAt = clocks[instanceId]?.lastSuccessAt
        lock.unlock()
        let checkedRows = Array(Set([last?.rowId ?? "main", "main"]))
        var contexts: [(ProviderQuotaCurrentKeyPolicy.Origin, Context)] = []
        for rowId in checkedRows {
            guard !Task.isCancelled, let key = Self.rowKey(instanceId, rowId: rowId),
                  let context = await Self.context(for: instance, key: key, rowId: rowId) else { continue }
            contexts.append((.init(rowId: rowId, owner: context.durableOwner), context))
        }
        // Keychain reads are outside the mutex, including the final readback.
        contexts = contexts.filter { Self.rowKey(instanceId, rowId: $0.0.rowId) == $0.1.key }
        let selected = ProviderQuotaCurrentKeyPolicy.current(lastSuccess: last, available: contexts.map { $0.0 })
        lock.lock()
        guard epochs[instanceId] == epoch else { lock.unlock(); return nil }
        validating.remove(instanceId)
        guard !Task.isCancelled,
              ProviderQuotaCurrentKeyPolicy.mayCommitResolution(
                captured: last, current: currentOrigins[instanceId] ?? Self.storedCurrent(instanceId),
                capturedSuccessAt: lastSuccessAt, currentSuccessAt: clocks[instanceId]?.lastSuccessAt) else {
            lock.unlock()
            // A newer success owns the selection. Its dirty work must still
            // converge even when this was the already-scheduled lookup.
            await scheduleAutomatic(instanceId)
            return nil
        }
        for rowId in checkedRows { selectableOrigins[instanceId]?.removeValue(forKey: rowId) }
        for (origin, context) in contexts {
            rowOrigins[instanceId, default: [:]][origin.rowId] = origin
            selectableOrigins[instanceId, default: [:]][origin.rowId] = origin
            if keyCache[instanceId]?[origin.rowId]?.owner != context.owner {
                keyCache[instanceId]?[origin.rowId] = nil
                if let saved = Self.storedInfo(instanceId: instanceId, origin: origin, processOwner: context.owner) {
                    keyCache[instanceId, default: [:]][origin.rowId] = .init(info: saved.info, fetchedAt: saved.fetchedAt, owner: context.owner, origin: origin)
                }
            }
        }
        currentOrigins[instanceId] = selected
        lock.unlock()
        _ = publishAggregate(for: instanceId)
        publishRevision(instanceId)
        return contexts.first { $0.0 == selected }?.1
    }
    func consumed(_ success: ProviderQuotaSuccess) {
        lock.lock()
        let epoch = epochs[success.instanceId] ?? UUID(); epochs[success.instanceId] = epoch
        lock.unlock()
        Task.detached(priority: .utility) {
            let instance = await MainActor.run { ProviderConfigStore.shared.instance(for: success.instanceId) }
            guard let instance, let key = Self.rowKey(success.instanceId, rowId: success.rowId),
                  ProviderQuotaSuccess.identity(key) == success.credentialIdentity,
                  let context = await Self.context(for: instance, key: key, rowId: success.rowId) else { return }
            // Loading the account-cookie context may suspend. Never publish a
            // successful lease for a row deleted/replaced/disabled meanwhile.
            guard Self.rowKey(success.instanceId, rowId: success.rowId) == key else { return }
            let origin = ProviderQuotaCurrentKeyPolicy.Origin(rowId: success.rowId, owner: context.durableOwner)
            self.lock.lock()
            guard self.epochs[success.instanceId] == epoch,
                  self.clocks[success.instanceId]?.lastSuccessAt.map({ $0 < success.succeededAt }) ?? true else {
                self.lock.unlock(); return
            }
            if self.rowOrigins[success.instanceId]?[success.rowId] != origin {
                self.keyCache[success.instanceId]?.removeValue(forKey: success.rowId)
                self.failureNotes.removeValue(forKey: self.failureKey(success.instanceId, success.rowId))
            }
            self.currentOrigins[success.instanceId] = origin
            self.rowOrigins[success.instanceId, default: [:]][success.rowId] = origin
            self.selectableOrigins[success.instanceId, default: [:]][success.rowId] = origin
            self.clocks[success.instanceId, default: .init()].consumed(at: success.succeededAt)
            if let data = try? JSONEncoder().encode(origin) {
                UserDefaults.standard.set(data, forKey: Self.currentPrefix + success.instanceId)
            }
            self.lock.unlock()
            _ = self.publishAggregate(for: success.instanceId)
            self.publishRevision(success.instanceId)
            await self.scheduleAutomatic(success.instanceId)
        }
    }
    @MainActor private func startForegroundFallback() {
        fallbackTask?.cancel()
        guard UIApplication.shared.applicationState == .active else { return }
        fallbackTask = Task { @MainActor in
            while !Task.isCancelled {
                do { try await Task.sleep(nanoseconds: 900_000_000_000) } catch { return }
                guard UIApplication.shared.applicationState == .active else { return }
                self.refreshAllIfNeeded(instances: ProviderConfigStore.shared.instances)
            }
        }
    }
    private func suspendAutomaticRefresh() {
        lock.lock()
        fallbackTask?.cancel(); fallbackTask = nil
        for task in scheduled.values { task.cancel() }; scheduled.removeAll()
        lock.unlock()
    }
    private func scheduleAutomatic(_ instanceId: String) async {
        let active = await MainActor.run { UIApplication.shared.applicationState == .active }
        lock.lock()
        // Consumption during a query remains pending; do not cancel/restart it.
        guard clocks[instanceId]?.running != true else { lock.unlock(); return }
        scheduled.removeValue(forKey: instanceId)?.cancel()
        guard let deadline = clocks[instanceId]?.deadline(active: active, now: Date()) else { lock.unlock(); return }
        let epoch = epochs[instanceId] ?? UUID(); epochs[instanceId] = epoch
        scheduled[instanceId] = Task.detached(priority: .utility) {
            do { try await Task.sleep(nanoseconds: UInt64(max(0, deadline.timeIntervalSinceNow) * 1_000_000_000)) }
            catch { return }
            guard !Task.isCancelled else { return }
            await self.runAutomatic(instanceId, epoch: epoch)
        }
        lock.unlock()
    }
    private func runAutomatic(_ instanceId: String, epoch: UUID) async {
        guard await MainActor.run(body: { UIApplication.shared.applicationState == .active }) else { return }
        guard let context = await resolveCurrent(instanceId, epoch: epoch),
              let instance = await MainActor.run(body: { ProviderConfigStore.shared.instance(for: instanceId) }) else { return }
        let origin = ProviderQuotaCurrentKeyPolicy.Origin(rowId: context.rowId, owner: context.durableOwner)
        lock.lock()
        guard !Task.isCancelled, epochs[instanceId] == epoch, currentOrigins[instanceId] == origin,
              let due = clocks[instanceId]?.deadline(active: true, now: Date()), due <= Date() else { lock.unlock(); return }
        clocks[instanceId, default: .init()].begin(at: Date())
        lock.unlock()
        let outcome = await refreshRow(for: instance, key: context.key, rowId: context.rowId, publishSingle: true)
        lock.lock()
        guard epochs[instanceId] == epoch else { lock.unlock(); return }
        if Task.isCancelled || outcome.deferred { clocks[instanceId, default: .init()].cancelled() }
        else { clocks[instanceId, default: .init()].finish(at: Date(), succeeded: outcome.succeeded, retryAfter: outcome.retryAfter) }
        lock.unlock()
        await scheduleAutomatic(instanceId)
    }
    private func publishRevision(_ instanceId: String) {
        lock.lock()
        let rows = (keyCache[instanceId] ?? [:]).keys.sorted().map { id -> String in
            let entry = keyCache[instanceId]?[id]
            return id + ":" + (entry?.info?.displayText ?? "?") + ":" + String(entry?.info?.observedAt?.timeIntervalSince1970 ?? 0)
                + ":" + String(entry?.info?.isStale ?? true) + ":" + (failureNotes[failureKey(instanceId, id)] ?? "")
        }.joined(separator: "|")
        let value = (currentOrigins[instanceId]?.rowId ?? "unknown") + ":" + (currentOrigins[instanceId]?.owner ?? "") + rows
        let changed = lastPublished[instanceId] != value
        lastPublished[instanceId] = value
        lock.unlock()
        if changed { Task { @MainActor in self.revision += 1 } }
    }
    func refreshQuota(for instance: ProviderInstance) async {
        let key = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) ?? ""
        await refreshRow(for: instance, key: key, rowId: "main", publishSingle: true)
    }
    func refreshAllIfNeeded(instances: [ProviderInstance]) {
        // [T-quota-foreground-only] Automatic queries read ONLY the current row.
        guard UIApplication.shared.applicationState == .active else { return }
        for instance in instances where instance.isEnabled && instance.credentialType == .apiKey {
            lock.lock()
            let missing = cache[instance.id].map { Date().timeIntervalSince($0.fetchedAt) >= ttl } ?? true
            if missing { clocks[instance.id, default: .init()].dirty = true }
            lock.unlock()
            Task { await self.scheduleAutomatic(instance.id) }
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
        _ = publishAggregate(for: instance.id)
        publishRevision(instance.id)
    }
    private struct RefreshOutcome {
        var succeeded = false
        var retryAfter: TimeInterval? = nil
        var deferred = false
    }
    @discardableResult
    private func refreshRow(for instance: ProviderInstance, key: String, rowId: String,
                            publishSingle: Bool) async -> RefreshOutcome {
        let slot = failureKey(instance.id, rowId), ticket = UUID()
        lock.lock()
        guard !Task.isCancelled else { lock.unlock(); return .init() }
        guard inFlight[slot] == nil else { lock.unlock(); return .init(deferred: true) }
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
        let currentKey = Self.rowKey(instance.id, rowId: rowId, includingUnavailable: true)
        let freshInstance = await MainActor.run { ProviderConfigStore.shared.instance(for: instance.id) }
        let currentContext: Context?
        if let freshInstance { currentContext = await Self.context(for: freshInstance, key: currentKey ?? "", rowId: rowId) }
        else { currentContext = nil }
        let verifiedKey = Self.rowKey(instance.id, rowId: rowId, includingUnavailable: true)
        let selectable = Self.rowKey(instance.id, rowId: rowId) == verifiedKey && verifiedKey != nil
        if context?.owner != currentContext?.owner || currentKey != verifiedKey {
            invalidateRow(instanceId: instance.id, rowId: rowId, epoch: epoch, ticket: ticket,
                          capturedOwner: context?.durableOwner)
            return .init()
        }
        lock.lock()
        guard epochs[instance.id] == epoch, inFlight[slot] == ticket else { lock.unlock(); return .init() }
        inFlight.removeValue(forKey: slot)
        guard !Task.isCancelled, let context, let result else { lock.unlock(); return .init() }
        let origin = ProviderQuotaCurrentKeyPolicy.Origin(rowId: rowId, owner: context.durableOwner)
        rowOrigins[instance.id, default: [:]][rowId] = origin
        if selectable { selectableOrigins[instance.id, default: [:]][rowId] = origin }
        else { selectableOrigins[instance.id]?.removeValue(forKey: rowId) }
        let previous = keyCache[instance.id]?[rowId]?.info
        let merged = result.merging(previous: previous.map { Self.snapshot($0) })
        let info = Self.project(merged)
        let entry = CacheEntry(info: info, fetchedAt: Date(), owner: context.owner, origin: origin)
        keyCache[instance.id, default: [:]][rowId] = entry
        let notes = result.attempts.filter { !$0.probeMiss }.compactMap(\.failureNote)
        if !notes.isEmpty { failureNotes[slot] = Array(Set(notes)).sorted().joined(separator: "；") }
        else if info == nil { failureNotes[slot] = AppLocalized("站点没有返回可用余额（可能不支持余额查询）") }
        else if info?.kind == .used && info?.readings.allSatisfy({ !$0.unlimited && !$0.rejected && $0.total == nil }) == true {
            failureNotes[slot] = AppLocalized("站点只返回了用量，没有返回剩余余额")
        } else { failureNotes.removeValue(forKey: slot) }
        // Persistence is inside the epoch fence; an old owner cannot replay
        // after a newer credential event. Every manually queried row is saved.
        let persisted = entry.info.map { Self.reproject($0) }
        Self.store(persisted, instanceId: instance.id, origin: origin, at: entry.fetchedAt)
        lock.unlock()
        _ = publishAggregate(for: instance.id)
        Self.logRefresh(instanceId: instance.id, rowId: rowId, info: persisted, note: notes.first)
        Self.logger.info("balance query instance=\(instance.id.prefix(8)) row=\(rowId) took \(String(format: "%.2f", Date().timeIntervalSince(started)))s")
        publishRevision(instance.id)
        return .init(succeeded: result.attempts.contains { $0.succeeded } && context.retry.retryAfter == nil,
                     retryAfter: context.retry.retryAfter)
    }
    /// Compatibility name only: publish the last SUCCESSFUL actual Key, never
    /// a minimum/sum across rows. A missing current-row reading stays unknown.
    private func publishAggregate(for instanceId: String) -> QuotaInfo? {
        lock.lock(); defer { lock.unlock() }
        let available = Array((selectableOrigins[instanceId] ?? [:]).values)
        let selected = ProviderQuotaCurrentKeyPolicy.current(
            lastSuccess: currentOrigins[instanceId] ?? Self.storedCurrent(instanceId), available: available)
        currentOrigins[instanceId] = selected
        guard let selected, rowOrigins[instanceId]?[selected.rowId] == selected,
              let entry = keyCache[instanceId]?[selected.rowId], entry.origin == selected else {
            cache.removeValue(forKey: instanceId)
            return nil
        }
        cache[instanceId] = entry
        return entry.info.map { Self.reproject($0) }
    }

    private final class RetryCapture { var retryAfter: TimeInterval? }
    private struct RateLimited: Error { let retryAfter: TimeInterval }
    private struct Context {
        let durableOwner: String
        let rowId: String
        let retry = RetryCapture()
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
        let durableInput = ([durableSalt] + Array(parts.dropFirst())).map { "\($0.utf8.count):" + $0 }.joined()
        let durableOwner = SHA256.hash(data: Data(durableInput.utf8)).map { String(format: "%02x", $0) }.joined()
        return Context(durableOwner: durableOwner, rowId: rowId, root: root, accountRoot: accountRoot, key: key, token: token, uid: uid,
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

    private static func get(_ request: URLRequest, retry: RetryCapture? = nil) async throws -> Data {
        try Task.checkCancellation()
        let result: (Data, URLResponse)
        do { result = try await transport.data(for: request) }
        catch {
            if Task.isCancelled { throw CancellationError() }
            throw RelayQuotaProtocol.Failure.transport
        }
        try Task.checkCancellation()
        guard let http = result.1 as? HTTPURLResponse else { throw RelayQuotaProtocol.Failure.transport }
        if http.statusCode == 429 {
            let seconds = ProviderQuotaCurrentKeyPolicy.retryAfter(http.value(forHTTPHeaderField: "Retry-After"), at: Date()) ?? 30
            retry?.retryAfter = max(retry?.retryAfter ?? 0, seconds)
            throw RateLimited(retryAfter: seconds)
        }
        guard http.statusCode == 200 else { throw RelayQuotaProtocol.Failure.http(http.statusCode) }
        return result.0
    }
    private static func failure(_ error: Error) -> String {
        if error is RateLimited { return RelayQuotaProtocol.Failure.http(429).note }
        return (error as? RelayQuotaProtocol.Failure)?.note ?? RelayQuotaProtocol.Failure.transport.note
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
            guard !Task.isCancelled, ctx.retry.retryAfter == nil else { break }
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
        let data = try await get(req, retry: ctx.retry), observedAt = Date()
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
        let data = try await get(req, retry: ctx.retry), observedAt = Date()
        switch source {
        case .sub2api:
            return try RelayQuotaProtocol.parseSub2API(data, root: ctx.root, now: observedAt)
        case .newAPIKey:
            _ = try RelayQuotaProtocol.parseNewAPI(data, root: ctx.root, now: observedAt, scale: nil)
            let scale = await siteScale(root: ctx.root)
            return try RelayQuotaProtocol.parseNewAPI(data, root: ctx.root, now: observedAt, scale: scale)
        case .openAIBilling:
            return try await fetchOpenAIBillingQuota(data, request: req, root: ctx.root, observedAt: observedAt, retry: ctx.retry)
        case .anthropic:
            return try RelayQuotaProtocol.parseAnthropic(data, root: ctx.root, now: observedAt)
        case .newAPIAccount: throw RelayQuotaProtocol.Failure.unsupported
        }
    }
    private static func fetchOpenAIBillingQuota(_ subscription: Data, request: URLRequest, root: String,
                                               observedAt: Date, retry: RetryCapture? = nil) async throws -> [RelayQuotaProtocol.Reading] {
        var req = request
        guard let url = RelayQuotaProtocol.endpoint(root: root, path: "/v1/dashboard/billing/usage") else {
            throw RelayQuotaProtocol.Failure.invalidURL
        }
        req.url = monthURL(url, anthropic: false)
        let usage = try? await get(req, retry: retry)
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