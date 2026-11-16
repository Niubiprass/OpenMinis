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
@MainActor final class ProviderConfigStore {
    static let shared = ProviderConfigStore()
    var authRevision = 0
    var instances: [ProviderInstance] = []
    func instance(for id: String) -> ProviderInstance? { instances.first { $0.id == id } ?? ProviderInstance(id: id) }
}
@MainActor final class SubscriptionOAuthManager {
    static let shared = SubscriptionOAuthManager()
    var epoch = UUID()
    func accountEpoch(instanceId: String) -> UUID { epoch }
    func validCredentials(instanceId: String, type: ProviderType) async throws -> KWWKAI.OAuthCredentials {
        .init(access: ProviderKeychainHelper.accessBySlot[instanceId] ?? "fake-account")
    }
}
@MainActor enum ProviderKeychainHelper {
    static var accessBySlot: [String: String] = [:]
    static func oauthNeedsReauth(instanceId: String) -> Bool { false }
    static func loadOAuthToken(instanceId: String, as: SubscriptionTokenStorage.Type) -> SubscriptionTokenStorage? {
        SubscriptionTokenStorage(provider: "traeCN", credentials: .init(access: accessBySlot[instanceId] ?? "fake-account"), loginAccount: nil)
    }
}
struct TraeCredential { init(_ credentials: KWWKAI.OAuthCredentials) {}; var deviceID: String? { "fixture-device" } }
@MainActor final class UIApplication {
    static let shared = UIApplication()
    enum State { case active, background }
    var applicationState = State.active
    var isProtectedDataAvailable = true
}
enum TestTint { case systemGreen, systemRed }
@MainActor enum MinisToast {
    static var notices: [String] = []
    static func show(_ text: String, duration: Double = 3, systemImage: String = "", tint: TestTint = .systemGreen) {
        notices.append(text)
    }
}
@MainActor enum CheckinTransport {
    static var reads = 0, writes = 0
    static var status: [String: Any] = ["code": 0, "checked_in": true]
    static var response: [String: Any] = ["code": 0]
    static var suspended = false
    static var pending: CheckedContinuation<Void, Never>?
    static var statusError: SubscriptionBillingError?
    static var claimError: SubscriptionBillingError?
    static var claimErrorBySlot: [String: SubscriptionBillingError] = [:]
    static var cancelClaim = false
    static var statusBySlot: [String: [String: Any]] = [:]
    static var responseBySlot: [String: [String: Any]] = [:]
    static var writesBySlot: [String: Int] = [:]
    static func send(mutation: Bool, slot: String) async throws -> [String: Any] {
        if mutation { writes += 1; writesBySlot[slot, default: 0] += 1 } else { reads += 1 }
        if suspended { await withCheckedContinuation { pending = $0 } }
        if mutation {
            if cancelClaim { throw CancellationError() }
            if let error = claimErrorBySlot[slot] { throw error }
            if let claimError { throw claimError }
        } else if let statusError { throw statusError }
        return mutation ? (responseBySlot[slot] ?? response) : (statusBySlot[slot] ?? status)
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
        func clear() {
            defaults.removeObject(forKey: "subscription.checkin.v2." + key)
            // Exercise day expiry rather than adding test-only production APIs.
            _ = SubscriptionCheckinLedger.cachedStatus(key, now: now.addingTimeInterval(86400))
        }
        func absent(_ identity: String) -> Bool { defaults.data(forKey: "subscription.checkin.v2." + identity) == nil }
        clear()
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
        expect(!SubscriptionCheckinLedger.canAttempt(key, now: now), "memory terminal blocks automatic retry")
        expect(absent(key), "status exclusion writes no UserDefaults journal")
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
        let writesBeforeQualification = CheckinTransport.writes
        for payload in [["code": 0, "enable": false], ["code": 0, "checked_in": false], ["code": 701]] as [[String: Any]] {
            CheckinTransport.status = payload
            do { _ = try await SubscriptionCreditAPI.claim(ctx); fatalError("unqualified must not claim") }
            catch is SubscriptionBillingError { }
            expect(CheckinTransport.writes == writesBeforeQualification, "ineligible/unknown never dispatch")
            expect(!SubscriptionCheckinPolicy.needsReminder(SubscriptionCheckinLedger.record(key), now: now), "ineligible/unknown silent")
            expect(absent(key), "ineligible/unknown qualification never creates journal")
            clear()
        }
        CheckinTransport.status = ["code": 0, "checked_in": false, "enable": true]
        CheckinTransport.response = ["code": 9004]
        do { _ = try await SubscriptionCreditAPI.claim(ctx); fatalError("definite refusal must fail") }
        catch let error as SubscriptionBillingError { expect(error.businessRefusal, "business rejection retained") }
        let rejected = SubscriptionCheckinLedger.record(key)
        expect(!rejected.verifiedRetryableFailure && !SubscriptionCheckinPolicy.needsReminder(rejected, now: now), "9004 alone cannot establish retryable account support")
        expect(absent(key), "generic refusal drops uncompleted UserDefaults key")
        expect(SubscriptionCheckinLedger.cachedStatus(key)?.eligibility == .unknown, "9004 not mislabelled ineligible")
        let refusedWrites = CheckinTransport.writes
        do { _ = try await SubscriptionCreditAPI.claim(ctx, automatic: true); fatalError("quiet memory must skip") }
        catch is SubscriptionBillingError { }
        expect(CheckinTransport.writes == refusedWrites, "automatic refusal not replayed today")
        clear()
        CheckinTransport.claimError = SubscriptionBillingError(message: "specifically verified retry fixture",
            businessRefusal: true, verifiedRetryableFailure: true)
        do { _ = try await SubscriptionCreditAPI.claim(ctx); fatalError("verified fixture must fail") }
        catch is SubscriptionBillingError { }
        let verified = SubscriptionCheckinLedger.record(key)
        expect(verified.verifiedRetryableFailure && SubscriptionCheckinPolicy.needsReminder(verified, now: now), "separate verified evidence can remind")
        let persistedFailure = defaults.data(forKey: "subscription.checkin.v2." + key)!
        expect(try JSONDecoder().decode(SubscriptionCheckinRecord.self, from: persistedFailure) == verified, "verified failure roundtrip")
        CheckinTransport.claimError = SubscriptionBillingError(message: "fixture reply lost")
        do { _ = try await SubscriptionCreditAPI.claim(ctx); fatalError("lost reply must not succeed") }
        catch is SubscriptionBillingError { }
        expect(!SubscriptionCheckinPolicy.needsReminder(SubscriptionCheckinLedger.record(key), now: now), "uncertain next claim cannot reuse old failure")
        CheckinTransport.claimError = nil
        clear()
        CheckinTransport.cancelClaim = true
        do { _ = try await SubscriptionCreditAPI.claim(ctx); fatalError("cancel must abort") }
        catch is CancellationError { }
        expect(!SubscriptionCheckinPolicy.needsReminder(SubscriptionCheckinLedger.record(key), now: now), "cancel has no failure")
        expect(absent(key), "cancelled mutation leaves no journal")
        CheckinTransport.cancelClaim = false
        clear()
        CheckinTransport.statusError = SubscriptionBillingError(message: "fixture query failed")
        do { _ = try await SubscriptionCreditAPI.checkin(ctx); fatalError("query must fail") }
        catch is SubscriptionBillingError { }
        expect(!SubscriptionCheckinPolicy.needsReminder(SubscriptionCheckinLedger.record(key), now: now), "qualification error is not claim failure")
        expect(absent(key), "qualification transport error creates no journal")
        CheckinTransport.statusError = nil
        clear()
        let expected = SubscriptionCheckinLedger.record(key)
        SubscriptionCheckinLedger.remember(.init(checkedIn: false, canClaim: true, reward: nil), key: key, requestDay: day)
        SubscriptionCheckinLedger.beginAttempt(key)
        SubscriptionCheckinLedger.beginClaim(key, requestDay: day)
        SubscriptionCheckinLedger.failedClaim(key, requestDay: day, verifiedRetryableFailure: true)
        SubscriptionCheckinLedger.unknown(key, requestDay: day, expected: expected)
        expect(SubscriptionCheckinPolicy.needsReminder(SubscriptionCheckinLedger.record(key), now: now), "stale unknown cannot erase newer refusal")
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
        CheckinTransport.status = ["code": 0, "checked_in": false, "enable": false]
        CheckinTransport.suspended = true
        let lateQuery = Task { @MainActor in try await SubscriptionCreditAPI.checkin(ctx) }
        while CheckinTransport.pending == nil { await Task.yield() }
        SubscriptionCheckinLedger.confirmed(key, requestDay: day, notify: true)
        let concurrentReceipt = defaults.data(forKey: "subscription.checkin.v2." + key)!
        CheckinTransport.release()
        let lateResult = try await lateQuery.value
        expect(lateResult.checkedIn, "late ineligible query returns confirmed completion")
        expect(defaults.data(forKey: "subscription.checkin.v2." + key) == concurrentReceipt, "late query preserves pending receipt bytes")
        clear()
        CheckinTransport.status = ["code": 0, "checked_in": false, "enable": true]
        CheckinTransport.response = ["code": 0]
        CheckinTransport.suspended = true
        let priorWrites = CheckinTransport.writes
        let claimingFirst = Task { @MainActor in try await SubscriptionCreditAPI.claim(ctx) }
        while CheckinTransport.pending == nil { await Task.yield() }
        do { _ = try await SubscriptionCreditAPI.claim(duplicate); fatalError("concurrent duplicate must not claim") }
        catch is SubscriptionBillingError { }
        CheckinTransport.release()
        _ = try await claimingFirst.value
        expect(CheckinTransport.writes == priorWrites + 1, "concurrent claims dispatch one mutation")
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
        SubscriptionCheckinLedger.unknown(key, requestDay: SubscriptionCheckinPolicy.day(localNoon), now: localNoon)
        expect(absent(key), "network retry metadata memory only")
        expect(!SubscriptionCheckinLedger.canAttempt(key, now: localNoon.addingTimeInterval(7199)), "network retry before two hours blocked")
        expect(SubscriptionCheckinLedger.canAttempt(key, now: localNoon.addingTimeInterval(7200)), "network retry at two hours allowed")
        clear()
        // Run the production automatic loop, not just the pure count predicate.
        func resetFourAccounts() {
            _ = SubscriptionCheckinLedger.cachedStatus(key, now: now.addingTimeInterval(86400))
            for entry in defaults.dictionaryRepresentation().keys where entry.hasPrefix("subscription.checkin.v2.") {
                defaults.removeObject(forKey: entry)
            }
            let slots = ["one", "two", "three", "four"]
            var provider = ProviderInstance(id: "four-account-provider")
            provider.subscriptionAccountSlots = slots
            ProviderConfigStore.shared.instances = [provider]
            ProviderKeychainHelper.accessBySlot = Dictionary(uniqueKeysWithValues: slots.map { ($0, "synthetic-" + $0) })
            CheckinTransport.status = ["code": 0, "checked_in": false, "enable": true]
            CheckinTransport.response = ["code": 0]
            CheckinTransport.statusBySlot = [:]; CheckinTransport.responseBySlot = [:]
            CheckinTransport.claimErrorBySlot = [:]
            CheckinTransport.writesBySlot = [:]
            MinisToast.notices = []
        }
        func fourthKey() -> String {
            SubscriptionCheckinLedger.key(token: SubscriptionTokenStorage(provider: "traeCN",
                credentials: .init(access: "synthetic-four"), loginAccount: nil), slot: "four")
        }
        func expectThreeOnly(_ label: String) {
            expect(MinisToast.notices == ["3 个账号已签到"], label)
            expect(absent(fourthKey()), "fourth UserDefaults key must be ABSENT: " + label)
            let savedKeys = defaults.dictionaryRepresentation().keys.filter { $0.hasPrefix("subscription.checkin.v2.") }
            expect(savedKeys.count == 3, "only three confirmed success journals saved")
            expect(savedKeys.allSatisfy { SubscriptionCheckinLedger.record(String($0.dropFirst("subscription.checkin.v2.".count))).completedDay == day }, "saved three all confirmed")
        }
        for fourth in [["code": 0, "enable": false], ["code": 0, "checked_in": false],
                       ["code": 0], ["code": 9095], ["code": 701]] as [[String: Any]] {
            resetFourAccounts()
            CheckinTransport.statusBySlot["four"] = fourth
            await SubscriptionAutoCheckin.run()
            expectThreeOnly("three successes plus unqualified fourth has no failure")
            expect(CheckinTransport.writesBySlot["four", default: 0] == 0, "fourth never receives claim")
            expect(CheckinTransport.writesBySlot.values.reduce(0, +) == 3, "only three eligible claims")
            let readsAfter = CheckinTransport.reads
            MinisToast.notices = []
            await SubscriptionAutoCheckin.run()
            expect(MinisToast.notices.isEmpty && CheckinTransport.reads == readsAfter, "same-day repeated pass is silent and cached")
        }
        for code in [9095, 9004, 701] {
            resetFourAccounts()
            CheckinTransport.responseBySlot["four"] = ["code": code]
            await SubscriptionAutoCheckin.run()
            expectThreeOnly("fourth refusal remains outside the report")
            expect(CheckinTransport.writesBySlot["four", default: 0] == 1, "only initial refusal was dispatched")
            expect(SubscriptionCheckinLedger.cachedStatus(fourthKey())?.eligibility == (code == 9095 ? .ineligible : .unknown), "unmapped code never invents ineligibility")
            let readsAfter = CheckinTransport.reads
            MinisToast.notices = []
            await SubscriptionAutoCheckin.run()
            expect(CheckinTransport.writesBySlot["four", default: 0] == 1 && CheckinTransport.reads == readsAfter, "no repeated claim/read while excluded in memory")
            expect(MinisToast.notices.isEmpty && absent(fourthKey()), "refusal never leaves daily reminder/journal")
            expect(SubscriptionCheckinLedger.canAttempt(fourthKey(), now: now.addingTimeInterval(86400)), "explicit/generic exclusion expires next day")
        }
        resetFourAccounts()
        CheckinTransport.claimErrorBySlot["four"] = SubscriptionBillingError(message: "verified retry fixture only",
            businessRefusal: true, verifiedRetryableFailure: true)
        await SubscriptionAutoCheckin.run()
        expect(MinisToast.notices == ["3 个账号已签到，1 个签到失败"], "specifically verified retryable failure still reminds in production loop")
        expect(SubscriptionCheckinLedger.record(fourthKey()).verifiedRetryableFailure, "verified-only durable failure evidence saved")
        let verifiedWrites = CheckinTransport.writes
        MinisToast.notices = []
        await SubscriptionAutoCheckin.run()
        expect(MinisToast.notices.isEmpty && CheckinTransport.writes == verifiedWrites, "verified reminder and retry are still throttled")
        resetFourAccounts()
        let old = Data("{\"eligibleDay\":\"\(day)\",\"claimDay\":\"\(day)\",\"failedClaimDay\":\"\(day)\"}".utf8)
        defaults.set(old, forKey: "subscription.checkin.v2." + fourthKey())
        await SubscriptionAutoCheckin.run()
        expectThreeOnly("legacy unverified failure migrated without nagging")
        expect(CheckinTransport.writesBySlot["four", default: 0] == 0, "old refusal not automatically reattempted today")
        MinisToast.notices = []
        await SubscriptionAutoCheckin.run()
        expect(MinisToast.notices.isEmpty && absent(fourthKey()), "legacy failure stays absent and silent")
        // Explicit user refresh can requalify; regular automatic reads cannot.
        let fourthContext = try await SubscriptionCreditAPI.context(ProviderConfigStore.shared.instances[0], accountSlot: "four")
        let eligibleAgain = try await SubscriptionCreditAPI.checkin(fourthContext, forceRefresh: true)
        expect(eligibleAgain.canClaim && absent(fourthKey()), "manual force refresh requalifies without creating journal")
        _ = try await SubscriptionCreditAPI.claim(fourthContext)
        expect(SubscriptionCheckinLedger.completed(fourthKey()), "explicit action can claim after requalification")
        let completedData = defaults.data(forKey: "subscription.checkin.v2." + fourthKey())!
        SubscriptionCheckinLedger.blocked(fourthKey(), requestDay: day, note: "late refusal")
        SubscriptionCheckinLedger.quietRefusal(fourthKey(), requestDay: day)
        SubscriptionCheckinLedger.unknown(fourthKey(), requestDay: day)
        expect(defaults.data(forKey: "subscription.checkin.v2." + fourthKey()) == completedData, "late refusal/error preserves actual success bytes")
        expect(!SubscriptionCheckinLedger.canAttempt(fourthKey()), "actual success remains deduplicated")
        expect(SubscriptionCheckinLedger.canAttempt(fourthKey(), now: now.addingTimeInterval(86400)), "memory exclusion expires next Asia/Shanghai day")
        resetFourAccounts()
        for index in 0...128 {
            SubscriptionCheckinLedger.unknown("memory-fixture-\(index)", requestDay: day,
                now: now.addingTimeInterval(Double(index) / 1000))
        }
        let boundedNow = now.addingTimeInterval(0.2)
        expect(SubscriptionCheckinLedger.cachedStatus("memory-fixture-0", now: boundedNow) == nil, "bounded memory evicts oldest entry")
        expect(SubscriptionCheckinLedger.cachedStatus("memory-fixture-128", now: boundedNow)?.eligibility == .unknown, "bounded memory retains latest")
        expect(absent("memory-fixture-128"), "bounded retry entries never persist")
        expect(SubscriptionCheckinLedger.cachedStatus("memory-fixture-128", now: now.addingTimeInterval(86400)) == nil, "memory entries expire at day boundary")
        UIApplication.shared.applicationState = .background
        await SubscriptionAutoCheckin.run()
        expect(MinisToast.notices.isEmpty && CheckinTransport.writesBySlot.isEmpty, "background has no claims or notices")
        print("subscription-checkin-runtime-ok")
    }
}
