// App dependencies only are mocked; ledger, policy, checkin and claim are production code.
// The production AppLogger needs CrashReporter/NSLog plumbing that the harness does not compile;
// the check-in code only ever needs the sink, so the same minimal stub used by the other
// Swift harnesses stands in for it (see scripts/test_compact_orphan_toolcall.swift).
struct AppLogger {
    let category: String
    init(subsystem: String = "com.openminis.app", category: String) { self.category = category }
    func info(_ message: @autoclosure () -> String) { }
    func notice(_ message: @autoclosure () -> String) { }
    func warning(_ message: @autoclosure () -> String) { }
    func error(_ message: @autoclosure () -> String) { }
}
enum ProviderType: String, Sendable { case workBuddy, traeCN; var isDomesticSubscription: Bool { true } }
enum KWWKAI { struct OAuthCredentials: Equatable, Sendable { let access: String } }
struct SubscriptionTokenStorage { let provider: String; let credentials: KWWKAI.OAuthCredentials; let loginAccount: String?; var accessToken: String { credentials.access } }
struct ProviderInstance { let id: String; var providerType: ProviderType = .traeCN; let credentialType = "oauth"; var subscriptionAccountSlots = ["a", "b"]; var subscriptionActiveSlot: String? { "a" }; var isEnabled = true; var subscriptionAutoCheckin = true }
extension String { static let oauth = "oauth" }
@MainActor enum SubscriptionAccounts { static func identity(_ token: SubscriptionTokenStorage) -> String? { token.provider + ":" + token.credentials.access } }
// Stable deterministic hash stand-in: key selection itself remains production code.
enum SHA256 { static func hash(data: Data) -> [UInt8] { Array(data) } }
@MainActor final class ProviderConfigStore { static let shared = ProviderConfigStore(); var authRevision = 0; func instance(for id: String) -> ProviderInstance? { ProviderInstance(id: id) } }
@MainActor final class SubscriptionOAuthManager { static let shared = SubscriptionOAuthManager(); var epoch = UUID(); func accountEpoch(instanceId: String) -> UUID { epoch }; func validCredentials(instanceId: String, type: ProviderType) async throws -> KWWKAI.OAuthCredentials { .init(access: "fake-account") } }
@MainActor enum ProviderKeychainHelper {
    static func oauthNeedsReauth(instanceId: String) -> Bool { false }
    static func loadOAuthToken(instanceId: String, as: SubscriptionTokenStorage.Type) -> SubscriptionTokenStorage? { SubscriptionTokenStorage(provider: "traeCN", credentials: .init(access: "fake-account"), loginAccount: nil) }
}
struct TraeCredential { init(_ credentials: KWWKAI.OAuthCredentials) {}; var deviceID: String? { "fixture-device" } }
@MainActor final class UIApplication { static let shared = UIApplication(); enum State { case active }; let applicationState = State.active }
@MainActor enum CheckinTransport {
    static var reads = 0, writes = 0
    static var status: [String: Any] = ["code": 0, "checked_in": true]
    static var response: [String: Any] = ["code": 0]
    static var suspended = false
    static var pending: CheckedContinuation<Void, Never>?
    static func send(mutation: Bool) async throws -> [String: Any] {
        if mutation { writes += 1 } else { reads += 1 }
        if suspended { await withCheckedContinuation { pending = $0 } }
        return mutation ? response : status
    }
    static func release() { suspended = false; pending?.resume(); pending = nil }
}

@main struct CheckinRuntimeTests {
    @MainActor static func main() async throws {
        func expect(_ ok: Bool, _ label: String) { precondition(ok, label) }
        let defaults = UserDefaults.standard
        // The runner supplies a temporary HOME and process; never touches real account state.
        for key in defaults.dictionaryRepresentation().keys where key.hasPrefix("subscription.checkin.v2.") { defaults.removeObject(forKey: key) }
        let now = Date(), day = SubscriptionCheckinPolicy.day(now)
        let ctx = SubscriptionCreditAPI.Context(instanceId: "a", parentId: "p", type: .traeCN, epoch: SubscriptionOAuthManager.shared.epoch, credentials: .init(access: "fake-account"))
        let duplicate = SubscriptionCreditAPI.Context(instanceId: "b", parentId: "p", type: .traeCN, epoch: ctx.epoch, credentials: ctx.credentials)
        let key = SubscriptionCheckinLedger.key(ctx)
        expect(key == SubscriptionCheckinLedger.key(duplicate), "same account across slots")
        func clear() { defaults.removeObject(forKey: "subscription.checkin.v2." + key) }
        _ = try await SubscriptionCreditAPI.checkin(ctx)
        expect(SubscriptionCheckinLedger.completed(key), "status persisted")
        expect(!SubscriptionCheckinPolicy.needsSuccessNotice(SubscriptionCheckinLedger.record(key), now: now), "discovered completion silent")
        let saved = defaults.data(forKey: "subscription.checkin.v2." + key)!
        expect(try JSONDecoder().decode(SubscriptionCheckinRecord.self, from: saved).completedDay == day, "persisted JSON roundtrip")
        _ = try await SubscriptionCreditAPI.checkin(duplicate)
        expect(CheckinTransport.reads == 1, "same-account cache no second query")
        clear()
        CheckinTransport.status = ["code": 9095]
        let refused = try await SubscriptionCreditAPI.checkin(ctx)
        expect(!refused.canClaim, "9095 status becomes terminal status")
        let blocked = SubscriptionCheckinLedger.record(key)
        expect(!SubscriptionCheckinPolicy.canAttempt(blocked, now: now), "terminal blocks automatic retry")
        expect(!SubscriptionCheckinPolicy.needsReminder(blocked, now: now), "terminal has no reminder")
        _ = try await SubscriptionCreditAPI.checkin(duplicate)
        expect(CheckinTransport.reads == 2, "blocked cache reused")
        clear()
        CheckinTransport.status = ["code": 0, "checked_in": false, "enable": true]
        _ = try await SubscriptionCreditAPI.claim(ctx)
        expect(CheckinTransport.writes == 1, "one accepted mutation")
        expect(SubscriptionCheckinPolicy.needsSuccessNotice(SubscriptionCheckinLedger.record(key), now: now), "new claim has receipt")
        SubscriptionCheckinLedger.remember(.init(checkedIn: true, canClaim: false, reward: nil), key: key, requestDay: day)
        expect(SubscriptionCheckinPolicy.needsSuccessNotice(SubscriptionCheckinLedger.record(key), now: now), "status cannot consume pending receipt")
        SubscriptionCheckinLedger.markNotified(key)
        _ = try await SubscriptionCreditAPI.claim(duplicate)
        expect(CheckinTransport.writes == 1, "duplicate account does not claim again")
        expect(!SubscriptionCheckinPolicy.needsSuccessNotice(SubscriptionCheckinLedger.record(key), now: now), "manual/auto notice only once")
        clear()
        CheckinTransport.response = ["code": 9095]
        do { _ = try await SubscriptionCreditAPI.claim(ctx); fatalError("9095 must refuse") }
        catch let error as SubscriptionBillingError { expect(error.terminal, "mutation refusal terminal") }
        expect(SubscriptionCheckinLedger.cachedStatus(key)?.canClaim == false, "mutation refusal saved")
        clear()
        let reads = CheckinTransport.reads
        CheckinTransport.suspended = true
        let first = Task { @MainActor in try await SubscriptionCreditAPI.checkin(ctx) }
        while CheckinTransport.pending == nil { await Task.yield() }
        let second = Task { @MainActor in try await SubscriptionCreditAPI.checkin(duplicate) }
        for _ in 0..<20 { await Task.yield() }
        first.cancel()
        CheckinTransport.status = ["code": 0, "checked_in": true]
        CheckinTransport.release()
        do { _ = try await first.value; fatalError("cancelled waiter must fail") } catch is CancellationError {}
        _ = try await second.value
        expect(CheckinTransport.reads == reads + 1, "concurrent waiters share status")
        expect(SubscriptionCheckinLedger.completed(key), "live waiter persists despite owner cancellation")
        clear()
        CheckinTransport.suspended = true
        let stale = Task { @MainActor in try await SubscriptionCreditAPI.checkin(ctx) }
        while CheckinTransport.pending == nil { await Task.yield() }
        SubscriptionOAuthManager.shared.epoch = UUID()
        CheckinTransport.status = ["code": 9095]
        CheckinTransport.release()
        do { _ = try await stale.value; fatalError("replaced account must fail") } catch is CancellationError {}
        expect(SubscriptionCheckinLedger.cachedStatus(key) == nil, "stale refusal never persisted")
        SubscriptionCheckinLedger.confirmed(key, requestDay: "1900-01-01", notify: true, now: now)
        SubscriptionCheckinLedger.blocked(key, requestDay: "1900-01-01", note: "old", now: now)
        expect(SubscriptionCheckinLedger.cachedStatus(key) == nil, "cross-day writes ignored")
        // The retry window is a 2 h interval but eligibility is per Asia/Shanghai day:
        // outside 00:00–21:59 local, `now + 7199s` is already tomorrow and the policy
        // (correctly) allows the attempt. Pin the sample to a fixed local time so the
        // assertion tests the interval instead of the wall clock the runner happened to use.
        var pinned = Calendar(identifier: .gregorian)
        pinned.timeZone = TimeZone(identifier: "Asia/Shanghai")!
        let localNoon = pinned.date(bySettingHour: 12, minute: 0, second: 0, of: now)!
        SubscriptionCheckinLedger.beginAttempt(key, now: localNoon)
        expect(!SubscriptionCheckinPolicy.canAttempt(SubscriptionCheckinLedger.record(key), now: localNoon.addingTimeInterval(7199)), "network retry before two hours blocked")
        expect(SubscriptionCheckinPolicy.canAttempt(SubscriptionCheckinLedger.record(key), now: localNoon.addingTimeInterval(7200)), "network retry at two hours allowed")
        clear()
        print("subscription-checkin-runtime-ok")
    }
}
