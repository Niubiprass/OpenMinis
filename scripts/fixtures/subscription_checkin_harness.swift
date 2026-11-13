import Foundation

// Async-free harness for SubscriptionCheckinPolicy (the PURE region is
// concatenated above this file). No network, no Keychain, no device state.

func day(_ iso: String) -> Date {
    let f = ISO8601DateFormatter()
    f.formatOptions = [.withInternetDateTime]
    return f.date(from: iso)!
}

func expect(_ condition: Bool, _ message: String) {
    if !condition {
        print("FAIL: \(message)")
        exit(1)
    }
}

// Day boundary is Asia/Shanghai, not UTC: 16:00Z is already next day there.
expect(SubscriptionCheckinPolicy.day(day("2026-01-01T15:59:59Z")) == "2026-01-01", "day before 16:00Z")
expect(SubscriptionCheckinPolicy.day(day("2026-01-01T16:00:00Z")) == "2026-01-02", "day at 16:00Z")

let noon = day("2026-01-02T04:00:00Z")
expect(SubscriptionCheckinPolicy.day(noon) == "2026-01-02", "noon same day")

// Fresh record: eligible.
var record = SubscriptionCheckinRecord()
expect(SubscriptionCheckinPolicy.canAttempt(record, now: noon), "fresh record may attempt")
expect(!SubscriptionCheckinPolicy.needsSuccessNotice(record, now: noon), "nothing signed, no success notice")
// Not completed and never reminded: the first reminder is due.
expect(SubscriptionCheckinPolicy.needsReminder(record, now: noon), "first reminder due")

// An attempt is not a completion: still pending, but not immediately retried.
record.attemptDay = "2026-01-02"
record.attemptedAt = noon
expect(!SubscriptionCheckinPolicy.canAttempt(record, now: noon.addingTimeInterval(60)), "no retry within 2h")
expect(!SubscriptionCheckinPolicy.canAttempt(record, now: noon.addingTimeInterval(2 * 3600 - 1)), "no retry just before 2h")
expect(SubscriptionCheckinPolicy.canAttempt(record, now: noon.addingTimeInterval(2 * 3600)), "retry at 2h")
expect(!SubscriptionCheckinPolicy.needsSuccessNotice(record, now: noon), "attempt alone is not success")

// A confirmed day stops both retry and reminder for the rest of the day.
record.completedDay = "2026-01-02"
expect(!SubscriptionCheckinPolicy.canAttempt(record, now: noon.addingTimeInterval(6 * 3600)), "completed stops retry")
expect(!SubscriptionCheckinPolicy.needsReminder(record, now: noon), "completed needs no reminder")
expect(SubscriptionCheckinPolicy.needsSuccessNotice(record, now: noon), "success notice once")
record.notifiedDay = "2026-01-02"
expect(!SubscriptionCheckinPolicy.needsSuccessNotice(record, now: noon), "success notice only once")

// Next day: a completed yesterday must not block today.
let tomorrow = day("2026-01-03T04:00:00Z")
expect(SubscriptionCheckinPolicy.canAttempt(record, now: tomorrow), "new day may attempt")
expect(SubscriptionCheckinPolicy.needsReminder(record, now: tomorrow), "new day reminder due")
expect(!SubscriptionCheckinPolicy.needsSuccessNotice(record, now: tomorrow), "yesterday is not today's success")

// Reminder throttling is independent from attempts.
record = SubscriptionCheckinRecord()
record.reminderDay = "2026-01-02"
record.remindedAt = noon
expect(!SubscriptionCheckinPolicy.needsReminder(record, now: noon.addingTimeInterval(3600)), "reminder throttled 1h")
expect(SubscriptionCheckinPolicy.needsReminder(record, now: noon.addingTimeInterval(2 * 3600)), "reminder at 2h")
expect(SubscriptionCheckinPolicy.canAttempt(record, now: noon), "reminder does not consume attempt")

print("subscription-checkin-ok")
