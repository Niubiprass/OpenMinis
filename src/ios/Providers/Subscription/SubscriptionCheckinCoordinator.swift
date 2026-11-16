import Foundation
import CryptoKit
import UIKit

// BEGIN SUBSCRIPTION_CHECKIN_POLICY_PURE
/// Durable state contains confirmed receipts or specifically verified retryable
/// failures only. Qualification, exclusion and uncertain outcomes live in memory.
struct SubscriptionCheckinRecord: Codable, Equatable {
    var completedDay: String?
    var notifiedDay: String?
    var attemptDay: String?
    var attemptedAt: Date?
    var reminderDay: String?
    var remindedAt: Date?
    /// Read compatibility only. New exclusions are never written to defaults.
    var blockedDay: String?
    var blockedNote: String?
    /// Only a newly accepted claim may produce a success notice. Legacy
    /// completed records and status discoveries carry no new receipt.
    var receiptDay: String?
    /// Missing in v2 legacy JSON: pending attempts never imply eligibility.
    /// Together with blockedDay, absence means eligibility is unknown today.
    var eligibleDay: String?
    var claimDay: String?
    var failedClaimDay: String?
    /// Opt-in evidence, not a classification inferred from arbitrary codes.
    /// Old JSON defaults to false and must never keep nagging after upgrade.
    var verifiedRetryableFailure: Bool = false
}

extension SubscriptionCheckinRecord {
    enum CodingKeys: String, CodingKey {
        case completedDay, notifiedDay, attemptDay, attemptedAt, reminderDay, remindedAt
        case blockedDay, blockedNote, receiptDay, eligibleDay, claimDay, failedClaimDay
        case verifiedRetryableFailure
    }

    init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        completedDay = try c.decodeIfPresent(String.self, forKey: .completedDay)
        notifiedDay = try c.decodeIfPresent(String.self, forKey: .notifiedDay)
        attemptDay = try c.decodeIfPresent(String.self, forKey: .attemptDay)
        attemptedAt = try c.decodeIfPresent(Date.self, forKey: .attemptedAt)
        reminderDay = try c.decodeIfPresent(String.self, forKey: .reminderDay)
        remindedAt = try c.decodeIfPresent(Date.self, forKey: .remindedAt)
        blockedDay = try c.decodeIfPresent(String.self, forKey: .blockedDay)
        blockedNote = try c.decodeIfPresent(String.self, forKey: .blockedNote)
        receiptDay = try c.decodeIfPresent(String.self, forKey: .receiptDay)
        eligibleDay = try c.decodeIfPresent(String.self, forKey: .eligibleDay)
        claimDay = try c.decodeIfPresent(String.self, forKey: .claimDay)
        failedClaimDay = try c.decodeIfPresent(String.self, forKey: .failedClaimDay)
        verifiedRetryableFailure = try c.decodeIfPresent(Bool.self, forKey: .verifiedRetryableFailure) ?? false
    }
}

enum SubscriptionCheckinPolicy {
    static let retryInterval: TimeInterval = 2 * 60 * 60

    static func day(_ date: Date) -> String {
        var calendar = Calendar(identifier: .gregorian)
        calendar.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let parts = calendar.dateComponents([.year, .month, .day], from: date)
        return String(format: "%04d-%02d-%02d", parts.year!, parts.month!, parts.day!)
    }

    static func canAttempt(_ record: SubscriptionCheckinRecord, now: Date) -> Bool {
        let today = day(now)
        if record.completedDay == today { return false }
        if record.blockedDay == today { return false }
        guard record.attemptDay == today, let last = record.attemptedAt else { return true }
        return now.timeIntervalSince(last) >= retryInterval
    }

    static func needsSuccessNotice(_ record: SubscriptionCheckinRecord, now: Date) -> Bool {
        record.completedDay == day(now) && record.receiptDay == day(now) && record.notifiedDay != day(now)
    }

    static func needsReminder(_ record: SubscriptionCheckinRecord, now: Date) -> Bool {
        let today = day(now)
        guard record.completedDay != today else { return false }
        // Legacy exclusions never produce a popup or reminder; new excluded
        // accounts show no check-in control/note and have only memory state.
        if record.blockedDay == today { return false }
        guard record.verifiedRetryableFailure,
              record.eligibleDay == today, record.claimDay == today,
              record.failedClaimDay == today else { return false }
        guard record.reminderDay == today, let last = record.remindedAt else { return true }
        return now.timeIntervalSince(last) >= retryInterval
    }

    static func isBlocked(_ record: SubscriptionCheckinRecord, now: Date) -> Bool {
        record.blockedDay == day(now) && record.completedDay != day(now)
    }
}
// END SUBSCRIPTION_CHECKIN_POLICY_PURE

@MainActor
enum SubscriptionCheckinLedger {
    private static let prefix = "subscription.checkin.v2."
    private struct Participation {
        var day: String
        var status: SubscriptionCheckin
        var updatedAt: Date
        var retryAt: Date?
        var stopForDay = false
        var dispatched = false
    }
    private static let memoryLimit = 128
    private static var participation: [String: Participation] = [:]

    private static func transient(_ key: String, now: Date) -> Participation? {
        let today = SubscriptionCheckinPolicy.day(now)
        participation = participation.filter { $0.value.day == today }
        return participation[key]
    }

    private static func keep(_ value: Participation, key: String, now: Date) {
        _ = transient(key, now: now)
        if participation[key] == nil, participation.count >= memoryLimit,
           let oldest = participation.min(by: { $0.value.updatedAt < $1.value.updatedAt })?.key {
            participation.removeValue(forKey: oldest)
        }
        participation[key] = value
    }

    static func canAttempt(_ key: String, now: Date = Date()) -> Bool {
        let value = record(key, now: now)
        if let state = transient(key, now: now) {
            if state.stopForDay { return false }
            if let retryAt = state.retryAt, now < retryAt { return false }
        }
        return SubscriptionCheckinPolicy.canAttempt(value, now: now)
    }

    static func key(token: SubscriptionTokenStorage, slot: String) -> String {
        let identity = SubscriptionAccounts.identity(token) ?? "\(token.provider):slot:\(slot)"
        return SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func key(_ context: SubscriptionCreditAPI.Context) -> String {
        key(token: SubscriptionTokenStorage(provider: context.type.rawValue,
            credentials: context.credentials, loginAccount: nil), slot: context.instanceId)
    }

    static func record(_ key: String, now: Date = Date()) -> SubscriptionCheckinRecord {
        guard let data = UserDefaults.standard.data(forKey: prefix + key),
              var value = try? JSONDecoder().decode(SubscriptionCheckinRecord.self, from: data)
        else { return SubscriptionCheckinRecord() }
        let today = SubscriptionCheckinPolicy.day(now)
        let legacyBlocked = value.blockedDay != nil
        let legacyFailure = value.failedClaimDay != nil && !value.verifiedRetryableFailure
        if value.completedDay != today {
            if value.blockedDay == today {
                keep(Participation(day: today, status: .init(checkedIn: false,
                    eligibility: .ineligible, reward: nil), updatedAt: now, stopForDay: true), key: key, now: now)
            } else if legacyFailure && value.failedClaimDay == today {
                // The old nonzero code is not proof of permanent ineligibility.
                // Quiet for this process/day, without replaying that old refusal.
                keep(Participation(day: today, status: .init(checkedIn: false,
                    eligibility: .unknown, reward: nil), updatedAt: now, stopForDay: true), key: key, now: now)
            } else if value.completedDay == nil, !value.verifiedRetryableFailure,
                      value.attemptDay == today, let last = value.attemptedAt {
                keep(Participation(day: today, status: .init(checkedIn: false,
                    eligibility: .unknown, reward: nil), updatedAt: now,
                    retryAt: last.addingTimeInterval(SubscriptionCheckinPolicy.retryInterval)), key: key, now: now)
            }
        }
        if value.completedDay == nil && !value.verifiedRetryableFailure {
            // Only this identity's obsolete, uncompleted check-in key is removed.
            UserDefaults.standard.removeObject(forKey: prefix + key)
            return SubscriptionCheckinRecord()
        }
        if legacyBlocked || legacyFailure {
            // Preserve all confirmed completion/receipt/dedup fields, including
            // yesterday's success, while retiring obsolete failure-only fields.
            value.blockedDay = nil; value.blockedNote = nil
            if legacyFailure {
                value.eligibleDay = nil; value.claimDay = nil; value.failedClaimDay = nil
            }
            write(key, value)
        }
        return value
    }

    private static func write(_ key: String, _ record: SubscriptionCheckinRecord) {
        guard let data = try? JSONEncoder().encode(record) else { return }
        UserDefaults.standard.set(data, forKey: prefix + key)
    }

    static func completed(_ key: String, now: Date = Date()) -> Bool {
        record(key, now: now).completedDay == SubscriptionCheckinPolicy.day(now)
    }

    /// Qualification must precede this call. Even an eligible attempt stays
    /// memory-only until a receipt or specifically verified retry error arrives.
    static func beginAttempt(_ key: String, now: Date = Date()) {
        guard var state = transient(key, now: now), state.status.canClaim,
              !state.stopForDay, !completed(key, now: now) else { return }
        state.updatedAt = now
        state.retryAt = now.addingTimeInterval(SubscriptionCheckinPolicy.retryInterval)
        state.dispatched = false
        keep(state, key: key, now: now)
    }

    /// Caller owns the claim lock and has already qualified. No fresh key is
    /// created, and a concurrent receipt can never be removed by cleanup.
    static func clearClaimOutcome(_ key: String, requestDay: String, now: Date = Date()) {
        discardUncompleted(key, requestDay: requestDay, now: now)
    }

    private static func discardUncompleted(_ key: String, requestDay: String, now: Date) {
        guard requestDay == SubscriptionCheckinPolicy.day(now) else { return }
        var value = record(key, now: now)
        guard value.completedDay != requestDay else { return }
        if value.completedDay == nil {
            if UserDefaults.standard.data(forKey: prefix + key) != nil {
                UserDefaults.standard.removeObject(forKey: prefix + key)
            }
        } else {
            let previous = value
            value.eligibleDay = nil; value.claimDay = nil; value.failedClaimDay = nil
            value.verifiedRetryableFailure = false
            value.blockedDay = nil; value.blockedNote = nil
            if value != previous { write(key, value) }
        }
    }

    @discardableResult
    static func beginClaim(_ key: String, requestDay: String, now: Date = Date()) -> Bool {
        guard requestDay == SubscriptionCheckinPolicy.day(now), !completed(key, now: now),
              var state = transient(key, now: now), state.status.canClaim,
              !state.stopForDay else { return false }
        state.dispatched = true
        keep(state, key: key, now: now)
        return true
    }

    static func failedClaim(_ key: String, requestDay: String,
                            verifiedRetryableFailure: Bool = false, now: Date = Date()) {
        guard verifiedRetryableFailure, requestDay == SubscriptionCheckinPolicy.day(now),
              let state = transient(key, now: now), state.status.canClaim,
              state.dispatched, !state.stopForDay else { return }
        var value = record(key, now: now)
        guard value.completedDay != requestDay else { return }
        value.attemptDay = requestDay; value.attemptedAt = state.updatedAt
        value.eligibleDay = requestDay; value.claimDay = requestDay
        value.failedClaimDay = requestDay
        value.verifiedRetryableFailure = true
        write(key, value)
    }

    /// Unknown qualifications/replies never create a durable failure or attempt.
    static func unknown(_ key: String, requestDay: String, expected: SubscriptionCheckinRecord? = nil,
                        now: Date = Date()) {
        guard requestDay == SubscriptionCheckinPolicy.day(now) else { return }
        let value = record(key, now: now)
        if let expected, value != expected { return }
        guard value.completedDay != requestDay else { return }
        if let state = transient(key, now: now), state.stopForDay || (expected != nil && state.dispatched) { return }
        discardUncompleted(key, requestDay: requestDay, now: now)
        keep(Participation(day: requestDay, status: .init(checkedIn: false,
            eligibility: .unknown, reward: nil), updatedAt: now,
            retryAt: now.addingTimeInterval(SubscriptionCheckinPolicy.retryInterval)), key: key, now: now)
    }

    /// Unmapped refusal: quiet for today, NOT labelled unsupported/ineligible.
    static func quietRefusal(_ key: String, requestDay: String, now: Date = Date()) {
        guard requestDay == SubscriptionCheckinPolicy.day(now), !completed(key, now: now) else { return }
        discardUncompleted(key, requestDay: requestDay, now: now)
        keep(Participation(day: requestDay, status: .init(checkedIn: false,
            eligibility: .unknown, reward: nil), updatedAt: now, stopForDay: true), key: key, now: now)
    }

    static func confirmed(_ key: String, requestDay: String, notify: Bool = false, now: Date = Date()) {
        // A reply crossing midnight cannot mark the new day as signed.
        guard requestDay == SubscriptionCheckinPolicy.day(now) else { return }
        var value = record(key)
        let previous = value
        value.completedDay = requestDay
        value.blockedDay = nil
        value.blockedNote = nil
        value.eligibleDay = nil
        value.failedClaimDay = nil
        value.verifiedRetryableFailure = false
        participation.removeValue(forKey: key)
        // A repeated status read must not consume a concurrent new receipt's
        // pending notice. Discovering an existing check-in is otherwise silent.
        if notify {
            value.receiptDay = requestDay
        } else if value.receiptDay != requestDay {
            value.notifiedDay = requestDay
        }
        guard value != previous else { return }
        write(key, value)
        ProviderConfigStore.shared.authRevision &+= 1
    }

    static func blocked(_ key: String, requestDay: String, note: String, now: Date = Date()) {
        guard requestDay == SubscriptionCheckinPolicy.day(now), !completed(key, now: now) else { return }
        // A late refusal never downgrades a confirmed receipt. No blockedDay
        // is written, and only this identity's uncompleted old key is retired.
        discardUncompleted(key, requestDay: requestDay, now: now)
        let status = SubscriptionCheckin(checkedIn: false, eligibility: .ineligible, reward: nil, note: note)
        let changed = transient(key, now: now)?.status != status
        keep(Participation(day: requestDay, status: status, updatedAt: now, stopForDay: true), key: key, now: now)
        if changed { ProviderConfigStore.shared.authRevision &+= 1 }
    }

    static func cachedStatus(_ key: String, now: Date = Date()) -> SubscriptionCheckin? {
        let value = record(key, now: now)
        if value.completedDay == SubscriptionCheckinPolicy.day(now) {
            return SubscriptionCheckin(checkedIn: true, canClaim: false, reward: nil)
        }
        if let state = transient(key, now: now), state.stopForDay || (state.retryAt.map { now < $0 } ?? false),
           state.status.eligibility != .eligible {
            return state.status
        }
        return nil
    }

    static func remember(_ status: SubscriptionCheckin, key: String, requestDay: String,
                         forceRefresh: Bool = false, now: Date = Date()) {
        guard requestDay == SubscriptionCheckinPolicy.day(now) else { return }
        if status.checkedIn {
            confirmed(key, requestDay: requestDay, notify: false, now: now)
        } else if status.eligibility == .ineligible {
            blocked(key, requestDay: requestDay, note: status.note ?? "今天暂不能签到", now: now)
        } else if status.eligibility == .eligible {
            guard !completed(key, now: now) else { return }
            // Only an explicit refresh can lift an earlier same-day exclusion.
            if let state = transient(key, now: now), state.stopForDay && !forceRefresh { return }
            keep(Participation(day: requestDay, status: status, updatedAt: now), key: key, now: now)
        } else {
            unknown(key, requestDay: requestDay, now: now)
        }
    }

    static func markNotified(_ key: String, now: Date = Date()) {
        var value = record(key, now: now)
        guard SubscriptionCheckinPolicy.needsSuccessNotice(value, now: now) else { return }
        value.notifiedDay = SubscriptionCheckinPolicy.day(now)
        write(key, value)
    }

    static func markReminded(_ key: String, now: Date = Date()) {
        var value = record(key, now: now)
        guard SubscriptionCheckinPolicy.needsReminder(value, now: now) else { return }
        value.reminderDay = SubscriptionCheckinPolicy.day(now)
        value.remindedAt = now
        write(key, value)
    }
}

/// Foreground only: root appearance and foreground entry start this timer.
/// A one-minute local tick checks dates; server requests are gated at two hours
/// per account until completion, then entirely skipped for the rest of the day.
@MainActor
enum SubscriptionAutoCheckin {
    private static var timer: Timer?
    private static var running = false
    private static var task: Task<Void, Never>?

    static func activate() {
        guard UIApplication.shared.applicationState == .active else { return }
        if timer == nil {
            timer = Timer.scheduledTimer(withTimeInterval: 60, repeats: true) { _ in
                Task { @MainActor in runIfNeeded() }
            }
        }
        runIfNeeded()
    }

    static func deactivate() {
        timer?.invalidate(); timer = nil
        task?.cancel() // an uncertain write is never replayed here
    }

    static func runIfNeeded() {
        guard !running, UIApplication.shared.applicationState == .active,
              UIApplication.shared.isProtectedDataAvailable else { return }
        running = true
        task = Task { @MainActor in
            defer { running = false; task = nil }
            await Task.yield()
            await run()
        }
    }

    private static func run() async {
        let store = ProviderConfigStore.shared
        var visited = Set<String>()
        var noticeKeys: [String] = []
        var reminderKeys: [String] = []
        for snapshot in store.instances where snapshot.providerType.isDomesticSubscription {
            for slot in snapshot.subscriptionAccountSlots {
                guard !Task.isCancelled, UIApplication.shared.applicationState == .active else { return }
                guard let current = store.instance(for: snapshot.id), current.isEnabled,
                      current.subscriptionAutoCheckin, current.subscriptionAccountSlots.contains(slot),
                      let token = ProviderKeychainHelper.loadOAuthToken(instanceId: slot, as: SubscriptionTokenStorage.self),
                      token.provider == current.providerType.rawValue, !token.accessToken.isEmpty else { continue }
                let key = SubscriptionCheckinLedger.key(token: token, slot: slot)
                guard visited.insert(key).inserted else { continue }
                let now = Date()
                var record = SubscriptionCheckinLedger.record(key)
                if SubscriptionCheckinLedger.canAttempt(key, now: now) {
                    let expectedRecord = record
                    var reachedClaim = false
                    do {
                        let context = try await SubscriptionCreditAPI.context(current, accountSlot: slot)
                        guard let fresh = store.instance(for: current.id), fresh.isEnabled,
                              fresh.subscriptionAutoCheckin, !Task.isCancelled else { continue }
                        // claim owns qualification and the account write lock.
                        reachedClaim = true
                        _ = try await SubscriptionCreditAPI.claim(context, automatic: true)
                    } catch {
                        if error is CancellationError || Task.isCancelled { return }
                        if !reachedClaim {
                            SubscriptionCheckinLedger.unknown(key, requestDay: SubscriptionCheckinPolicy.day(now),
                                expected: expectedRecord)
                        }
                        // Refusals/unknowns are silent. Only specifically verified
                        // retryable failures can enter the reminder report below.
                    }
                    record = SubscriptionCheckinLedger.record(key)
                }
                // [T-checkin-exclude-blocked] An account the server says cannot
                // check in today is OUT of the report entirely: it is not a
                // success, not a failure, and never counted or mentioned.
                if SubscriptionCheckinLedger.cachedStatus(key)?.eligibility == .ineligible,
                   record.completedDay != SubscriptionCheckinPolicy.day(Date()) { continue }
                if SubscriptionCheckinPolicy.needsSuccessNotice(record, now: Date()) {
                    noticeKeys.append(key)
                } else if SubscriptionCheckinPolicy.needsReminder(record, now: Date()) {
                    reminderKeys.append(key)
                }
            }
        }
        guard !Task.isCancelled, UIApplication.shared.applicationState == .active else { return }
        // Another account's await may let a manual refresh/claim resolve an
        // earlier pending account. Revalidate before consuming any notice.
        noticeKeys = noticeKeys.filter {
            SubscriptionCheckinPolicy.needsSuccessNotice(SubscriptionCheckinLedger.record($0), now: Date())
        }
        reminderKeys = reminderKeys.filter {
            SubscriptionCheckinPolicy.needsReminder(SubscriptionCheckinLedger.record($0), now: Date())
        }
        // One combined toast: never stack a success and failure popup on launch.
        if !noticeKeys.isEmpty {
            noticeKeys.forEach { SubscriptionCheckinLedger.markNotified($0) }
            reminderKeys.forEach { SubscriptionCheckinLedger.markReminded($0) }
            // Only accounts that can check in appear here; blocked ones were
            // skipped above and are never counted.
            // Colour + 3s: a white one-second pill could not be told apart from
            // a failure. Green = all good, red = anything failed.
            if reminderKeys.isEmpty {
                MinisToast.show("\(noticeKeys.count) 个账号已签到", duration: 3.0,
                                systemImage: "checkmark.circle.fill", tint: .systemGreen)
            } else {
                MinisToast.show("\(noticeKeys.count) 个账号已签到，\(reminderKeys.count) 个签到失败",
                                duration: 3.6, systemImage: "exclamationmark.circle.fill", tint: .systemRed)
            }
        } else if !reminderKeys.isEmpty {
            reminderKeys.forEach { SubscriptionCheckinLedger.markReminded($0) }
            MinisToast.show("\(reminderKeys.count) 个账号签到失败", duration: 3.6,
                            systemImage: "exclamationmark.circle.fill", tint: .systemRed)
        }
    }
}
