import Foundation
import CryptoKit
import UIKit

// BEGIN SUBSCRIPTION_CHECKIN_POLICY_PURE
/// Local state has no credential or account name. Confirmed completion and
/// explicit ineligibility stop automatic queries for today; transport errors retry.
struct SubscriptionCheckinRecord: Codable, Equatable {
    var completedDay: String?
    var notifiedDay: String?
    var attemptDay: String?
    var attemptedAt: Date?
    var reminderDay: String?
    var remindedAt: Date?
    /// Suppresses automatic attempts until tomorrow. An explicit manual refresh
    /// may recheck eligibility if the account's conditions change during the day.
    var blockedDay: String?
    var blockedNote: String?
    /// Only a newly accepted claim may produce a success notice. Legacy
    /// completed records and status discoveries carry no new receipt.
    var receiptDay: String?
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
        // A definite "cannot check in today" answer is shown on that account's
        // row only; it never produces a popup or the two-hour reminder.
        if record.blockedDay == today { return false }
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

    static func key(token: SubscriptionTokenStorage, slot: String) -> String {
        let identity = SubscriptionAccounts.identity(token) ?? "\(token.provider):slot:\(slot)"
        return SHA256.hash(data: Data(identity.utf8)).map { String(format: "%02x", $0) }.joined()
    }

    static func key(_ context: SubscriptionCreditAPI.Context) -> String {
        key(token: SubscriptionTokenStorage(provider: context.type.rawValue,
            credentials: context.credentials, loginAccount: nil), slot: context.instanceId)
    }

    static func record(_ key: String) -> SubscriptionCheckinRecord {
        guard let data = UserDefaults.standard.data(forKey: prefix + key),
              let value = try? JSONDecoder().decode(SubscriptionCheckinRecord.self, from: data)
        else { return SubscriptionCheckinRecord() }
        return value
    }

    private static func write(_ key: String, _ record: SubscriptionCheckinRecord) {
        guard let data = try? JSONEncoder().encode(record) else { return }
        UserDefaults.standard.set(data, forKey: prefix + key)
    }

    static func completed(_ key: String, now: Date = Date()) -> Bool {
        record(key).completedDay == SubscriptionCheckinPolicy.day(now)
    }

    static func beginAttempt(_ key: String, now: Date = Date()) {
        var value = record(key)
        value.attemptDay = SubscriptionCheckinPolicy.day(now)
        value.attemptedAt = now
        write(key, value)
    }

    static func confirmed(_ key: String, requestDay: String, notify: Bool = false, now: Date = Date()) {
        // A reply crossing midnight cannot mark the new day as signed.
        guard requestDay == SubscriptionCheckinPolicy.day(now) else { return }
        var value = record(key)
        let previous = value
        value.completedDay = requestDay
        value.blockedDay = nil
        value.blockedNote = nil
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
        guard requestDay == SubscriptionCheckinPolicy.day(now) else { return }
        var value = record(key)
        // A late refusal must never downgrade confirmed completion.
        guard value.completedDay != requestDay else { return }
        let previous = value
        value.blockedDay = requestDay
        value.blockedNote = note
        guard value != previous else { return }
        write(key, value)
        ProviderConfigStore.shared.authRevision &+= 1
    }

    static func cachedStatus(_ key: String, now: Date = Date()) -> SubscriptionCheckin? {
        let value = record(key)
        if value.completedDay == SubscriptionCheckinPolicy.day(now) {
            return SubscriptionCheckin(checkedIn: true, canClaim: false, reward: nil)
        }
        if SubscriptionCheckinPolicy.isBlocked(value, now: now) {
            return SubscriptionCheckin(checkedIn: false, canClaim: false, reward: nil,
                note: value.blockedNote ?? "今天暂不能签到")
        }
        return nil
    }

    static func remember(_ status: SubscriptionCheckin, key: String, requestDay: String, now: Date = Date()) {
        guard requestDay == SubscriptionCheckinPolicy.day(now) else { return }
        if status.checkedIn {
            confirmed(key, requestDay: requestDay, notify: false, now: now)
        } else if !status.canClaim {
            blocked(key, requestDay: requestDay, note: status.note ?? "今天暂不能签到", now: now)
        } else {
            // An explicit manual refresh may confirm eligibility has changed.
            var value = record(key)
            guard SubscriptionCheckinPolicy.isBlocked(value, now: now) else { return }
            value.blockedDay = nil
            value.blockedNote = nil
            write(key, value)
            ProviderConfigStore.shared.authRevision &+= 1
        }
    }

    static func markNotified(_ key: String, now: Date = Date()) {
        var value = record(key)
        value.notifiedDay = SubscriptionCheckinPolicy.day(now)
        write(key, value)
    }

    static func markReminded(_ key: String, now: Date = Date()) {
        var value = record(key)
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
                if SubscriptionCheckinPolicy.canAttempt(record, now: now) {
                    SubscriptionCheckinLedger.beginAttempt(key, now: now)
                    do {
                        let context = try await SubscriptionCreditAPI.context(current, accountSlot: slot)
                        guard let fresh = store.instance(for: current.id), fresh.isEnabled,
                              fresh.subscriptionAutoCheckin, !Task.isCancelled else { continue }
                        // claim owns the one fresh status read and the write lock.
                        // It records a definite "not today" answer as blocked.
                        _ = try await SubscriptionCreditAPI.claim(context, automatic: true)
                    } catch {
                        if error is CancellationError || Task.isCancelled { return }
                        // Terminal answers (device already used, not eligible,
                        // already signed) are remembered by claim and stay silent.
                        if (error as? SubscriptionBillingError)?.terminal == true { continue }
                        // Anything else stays pending and retries in two hours.
                    }
                    record = SubscriptionCheckinLedger.record(key)
                }
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
            MinisToast.show(reminderKeys.isEmpty ? "今日已签到" : "\(noticeKeys.count) 个账号今日已签到，\(reminderKeys.count) 个还未完成")
        } else if !reminderKeys.isEmpty {
            reminderKeys.forEach { SubscriptionCheckinLedger.markReminded($0) }
            MinisToast.show("\(reminderKeys.count) 个账号今天还没签到成功，稍后再试")
        }
    }
}
