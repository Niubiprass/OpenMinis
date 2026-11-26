// Synthetic shapes only. The actual loader declaration is inserted verbatim.
import Foundation
#if canImport(Combine)
import Combine
#else
protocol ObservableObject: AnyObject {}
final class TestSubscription { let cancelAction: () -> Void; init(_ action: @escaping () -> Void) { cancelAction = action }; deinit { cancelAction() } }
final class TestPublisher<Value> {
    var callbacks: [UUID: (Value) -> Void] = [:]
    var current: Value
    init(_ value: Value) { current = value }
    func sink(receiveValue: @escaping (Value) -> Void) -> TestSubscription {
        let id = UUID(); callbacks[id] = receiveValue; receiveValue(current)
        return TestSubscription { [weak self] in self?.callbacks[id] = nil }
    }
    func send(_ value: Value) { current = value; for callback in callbacks.values { callback(value) } }
}
@propertyWrapper struct Published<Value> {
    private var value: Value
    let projectedValue: TestPublisher<Value>
    init(wrappedValue: Value) { value = wrappedValue; projectedValue = TestPublisher(wrappedValue) }
    var wrappedValue: Value {
        get { value }
        set { projectedValue.send(newValue); value = newValue }
    }
}
#endif

enum ProviderType: String { case synthetic, replacement }
enum ProviderCredential: String { case apiKey, oauth }
struct ProviderInstance {
    var id = "row-A"
    var providerType = ProviderType.synthetic
    var credentialType = ProviderCredential.apiKey
    var customBaseURL: String? = "synthetic-root"
    var appendV1Suffix = true
    var subscriptionAccountIds: [String]? = ["synthetic-account-A"]
    var subscriptionActiveAccountId: String? = "synthetic-account-A"
}
@MainActor final class ProviderConfigStore {
    static let shared = ProviderConfigStore()
    var instances = [ProviderInstance()]
    var authRevision: UInt = 0
    var configRevision: UInt = 0
    var modelSnapshotRevision: UInt = 0
    func instance(for id: String) -> ProviderInstance? { instances.first { $0.id == id } }
}
final class ProviderRowCredentialCache: @unchecked Sendable {
    static let shared = ProviderRowCredentialCache()
    var generation: UInt = 0 // test writes on MainActor only
}
final class ProviderQuotaService: @unchecked Sendable {
    static let shared = ProviderQuotaService()
    var revision = 0 // test writes on MainActor only
    struct QuotaInfo {
        enum Kind { case balance, used }
        let displayText: String
        let highlighted: Bool
        let kind: Kind
    }
    private let mutex = NSLock()
    private var amount: Double? = 5
    private var threshold: Double = 3
    func set(amount: Double?, threshold: Double) {
        mutex.lock(); self.amount = amount; self.threshold = threshold; mutex.unlock()
    }
    func cachedQuota(instanceId: String) -> QuotaInfo? {
        precondition(!Thread.isMainThread, "synthetic read must run off-main")
        mutex.lock(); defer { mutex.unlock() }
        return amount.map { QuotaInfo(displayText: "synthetic-\($0)", highlighted: $0 < threshold, kind: .balance) }
    }
}

// PRODUCTION_LOADER

// A synthetic gate only; never touches app Defaults, Keychain, account or network.
final class RowReadGate: @unchecked Sendable {
    typealias Scope = ProviderQuotaRowProjectionLoader.Scope
    typealias Display = ProviderQuotaRowProjectionLoader.Display
    private let lock = NSLock()
    private let semaphore = DispatchSemaphore(value: 0)
    private var blocked = false
    private var payload: Display? = Display(displayText: "synthetic-A", highlighted: false, kind: .balance)
    private var captured: [Scope] = []
    private var active = 0
    private var peak = 0
    private var ended = 0
    func set(_ value: Display?) { lock.lock(); payload = value; lock.unlock() }
    func blockNext() { lock.lock(); blocked = true; lock.unlock() }
    func release() { semaphore.signal() }
    func counts() -> (started: Int, finished: Int, peak: Int) {
        lock.lock(); defer { lock.unlock() }; return (captured.count, ended, peak)
    }
    func scopes() -> [Scope] { lock.lock(); defer { lock.unlock() }; return captured }
    func read(_ scope: Scope) -> Display? {
        precondition(!Thread.isMainThread, "gate must never block UI")
        lock.lock()
        captured.append(scope); active += 1; peak = max(peak, active)
        let wait = blocked, value = payload; blocked = false
        lock.unlock()
        if wait { precondition(semaphore.wait(timeout: .now() + 5) == .success, "gate timed out") }
        lock.lock(); active -= 1; ended += 1; lock.unlock()
        return value
    }
}

@main struct QuotaRowProjectionProbe {
    typealias Loader = ProviderQuotaRowProjectionLoader
    @MainActor static func pause() async { try? await Task.sleep(nanoseconds: 20_000_000) }
    @MainActor static func until(_ message: String, _ predicate: () -> Bool) async {
        for _ in 0..<2000 {
            if predicate() { return }
            try? await Task.sleep(nanoseconds: 1_000_000)
        }
        preconditionFailure("Timed out: " + message)
    }
    @MainActor static func scope(_ instance: ProviderInstance? = nil, auth: UInt? = nil) -> Loader.Scope {
        let store = ProviderConfigStore.shared
        return Loader.makeScope(instance: instance ?? store.instances[0], authRevision: auth ?? store.authRevision,
                                configRevision: store.configRevision, snapshotRevision: store.modelSnapshotRevision,
                                credentialGeneration: ProviderRowCredentialCache.shared.generation)
    }
    @MainActor static func main() async {
        let gate = RowReadGate()
        let loader = Loader(reader: { gate.read($0) }, isCurrent: { _, _ in true })
        let a = scope()
        var emissions = 0
        let subscription = loader.$display.sink { _ in emissions += 1 }
        let initial = emissions
        loader.project(scope: a, quotaRevision: 0)
        await until("initial projection") { loader.display?.displayText == "synthetic-A" }
        precondition(emissions == initial + 1)
        loader.project(scope: a, quotaRevision: 1)
        await until("equal re-read") { gate.counts().finished == 2 }
        await pause()
        precondition(emissions == initial + 1, "same value must not republish")

        var other = ProviderInstance(); other.id = "row-B"
        let b = scope(other)
        let otherGate = RowReadGate()
        let otherLoader = Loader(reader: { otherGate.read($0) }, isCurrent: { _, _ in true })
        otherLoader.project(scope: b, quotaRevision: 1)
        await until("other row initial") { otherLoader.display != nil }
        otherGate.set(.init(displayText: "synthetic-B-new", highlighted: true, kind: .balance))
        otherLoader.project(scope: b, quotaRevision: 2)
        loader.project(scope: a, quotaRevision: 2)
        await until("other row revision") { otherLoader.display?.displayText == "synthetic-B-new" && gate.counts().finished == 3 }
        await pause()
        precondition(emissions == initial + 1, "another row revision must not publish this row")
        gate.set(nil); loader.project(scope: a, quotaRevision: 3)
        await until("empty cache clears pill") { loader.display == nil }
        precondition(emissions == initial + 2)
        withExtendedLifetime(subscription) {}

        // Block one real detached read, replace its pending request repeatedly.
        // Different auth/scope must clear old display before new work completes.
        let slow = RowReadGate()
        slow.blockNext()
        let bounded = Loader(reader: { slow.read($0) }, isCurrent: { _, _ in true })
        var seen: [String] = []
        let boundedSubscription = bounded.$display.sink { if let value = $0 { seen.append(value.displayText) } }
        bounded.project(scope: a, quotaRevision: 0)
        await until("slow started") { slow.counts().started == 1 }
        let newer = scope(auth: 1), newest = scope(auth: 2)
        bounded.project(scope: newer, quotaRevision: 1)
        bounded.project(scope: newest, quotaRevision: 2)
        precondition(bounded.display == nil && bounded.value(for: a) == nil)
        precondition(slow.counts().started == 1, "cancel must retain occupied slot")
        slow.set(.init(displayText: "synthetic-new-auth", highlighted: false, kind: .used))
        slow.release()
        await until("latest auth replaces old") { bounded.display?.displayText == "synthetic-new-auth" }
        precondition(slow.scopes() == [a, newest], "only latest pending may read")
        precondition(slow.counts().peak == 1 && !seen.contains("synthetic-A"), "no parallel/late old read")
        precondition(bounded.value(for: a) == nil, "wrong scope may not read new pill")
        withExtendedLifetime(boundedSubscription) {}

        let cancelled = RowReadGate(); cancelled.blockNext()
        let cancelLoader = Loader(reader: { cancelled.read($0) }, isCurrent: { _, _ in true })
        var late = 0
        let cancelSubscription = cancelLoader.$display.sink { if $0 != nil { late += 1 } }
        cancelLoader.project(scope: a, quotaRevision: 0)
        await until("cancel started") { cancelled.counts().started == 1 }
        cancelLoader.cancel(); cancelled.release()
        await until("cancel finished") { cancelled.counts().finished == 1 }
        await pause()
        precondition(cancelLoader.display == nil && late == 0, "disappear cannot publish old read")
        cancelLoader.project(scope: a, quotaRevision: 1)
        await until("reappearance re-reads") { cancelLoader.display != nil }
        precondition(cancelled.counts().started == 2 && cancelled.counts().peak == 1)
        withExtendedLifetime(cancelSubscription) {}

        let deinitGate = RowReadGate(); deinitGate.blockNext()
        var dying: Loader? = Loader(reader: { deinitGate.read($0) }, isCurrent: { _, _ in true })
        weak var weakLoader = dying
        dying?.project(scope: a, quotaRevision: 0)
        await until("deinit read started") { deinitGate.counts().started == 1 }
        dying = nil
        precondition(weakLoader == nil, "worker must not retain loader across await")
        deinitGate.release()
        await until("deinit worker returned") { deinitGate.counts().finished == 1 }

        // Default production reader+validator run against synthetic memory only.
        let service = ProviderQuotaService.shared
        let store = ProviderConfigStore.shared
        let thresholdLoader = Loader()
        service.set(amount: 5, threshold: 3)
        thresholdLoader.project(scope: scope(), quotaRevision: service.revision)
        await until("threshold initial") { thresholdLoader.display != nil }
        precondition(thresholdLoader.display?.highlighted == false)
        service.set(amount: 5, threshold: 9)
        thresholdLoader.project(scope: scope(), quotaRevision: service.revision)
        await until("threshold warning") { thresholdLoader.display?.highlighted == true }
        service.set(amount: nil, threshold: 9)
        thresholdLoader.project(scope: scope(), quotaRevision: service.revision)
        await until("default cache nil") { thresholdLoader.display == nil }

        // Live validation must also reject changes that precede view callbacks.
        for mutation in 0..<8 {
            store.instances = [ProviderInstance()]
            store.authRevision = 0; store.configRevision = 0; store.modelSnapshotRevision = 0
            ProviderRowCredentialCache.shared.generation = 0
            service.revision = 0
            let validationGate = RowReadGate(); validationGate.blockNext()
            let checked = Loader(reader: { validationGate.read($0) })
            let captured = scope()
            checked.project(scope: captured, quotaRevision: 0)
            await until("live validation started") { validationGate.counts().started == 1 }
            switch mutation {
            case 0: store.authRevision = 1
            case 1: store.configRevision = 1
            case 2: store.modelSnapshotRevision = 1
            case 3: store.instances[0].providerType = .replacement
            case 4: store.instances[0].customBaseURL = "synthetic-new-root"
            case 5:
                store.instances[0].subscriptionAccountIds = ["synthetic-account-B"]
                store.instances[0].subscriptionActiveAccountId = "synthetic-account-B"
            case 6: ProviderRowCredentialCache.shared.generation = 1
            default: service.revision = 1
            }
            validationGate.release()
            await until("live validation finished") { validationGate.counts().finished == 1 }
            await pause()
            precondition(checked.display == nil, "live scope/revision invalidation must reject result")
            precondition(checked.value(for: captured) == nil)
        }
        print("PASS: actual quota row projection / equal-value / other-row / latest-pending / cancel / scope / empty / threshold / deinit")
    }
}
