// Production cache is prepended by the Python runner.
private final class Counter: @unchecked Sendable {
    private let lock = NSLock()
    private var n = 0
    func hit() { lock.lock(); n += 1; lock.unlock() }
    var value: Int { lock.lock(); defer { lock.unlock() }; return n }
}
private final class Gate: @unchecked Sendable {
    let entered = DispatchSemaphore(value: 0)
    let release = DispatchSemaphore(value: 0)
    func block() {
        entered.signal()
        precondition(release.wait(timeout: .now() + 10) == .success, "test gate timed out")
    }
    func awaitEntry() async {
        let didEnter = await Task.detached { self.entered.wait(timeout: .now() + 10) == .success }.value
        precondition(didEnter, "probe never started")
    }
}
@main struct RunCacheTests {
    static func main() async {
        typealias Cache = ProviderRowCredentialCache
        let cache = Cache()
        func request(_ id: String = "A", _ revision: UInt = 1,
                     type: ProviderType = .openAI, credential: ProviderCredential = .apiKey,
                     emptyAllowed: Bool = false) -> Cache.Request {
            .init(instanceId: id, providerType: type, credentialType: credential,
                  allowsEmptyAPIKey: emptyAllowed, subscriptionAccountIds: nil,
                  subscriptionActiveAccountId: nil, revision: revision, generation: cache.generation)
        }
        let hits = Counter()
        let r = request()
        precondition(cache.cachedDisplay(for: r) == nil)
        let probe: @Sendable (Cache.Request) -> Cache.Display = { _ in
            hits.hit()
            return .init(isConfigured: true, summary: "masked")
        }
        await withTaskGroup(of: Cache.Display?.self) { group in
            for _ in 0..<24 { group.addTask { await cache.value(for: r, probe: probe) } }
            for await display in group { precondition(display?.summary == "masked") }
        }
        precondition(hits.value == 1, "concurrent requests must share one worker")
        precondition(cache.cachedDisplay(for: r)?.summary == "masked")
        for _ in 0..<1000 { _ = cache.cachedDisplay(for: r) }
        precondition(hits.value == 1, "drawing a row must never probe credentials")

        let slow = Gate()
        let older = request("A", 2), newer = request("A", 3)
        let oldTask = Task { await cache.value(for: older) { _ in
            slow.block(); return .init(isConfigured: true, summary: "old")
        } }
        await slow.awaitEntry()
        let fresh = await cache.value(for: newer) { _ in .init(isConfigured: true, summary: "new") }
        precondition(fresh?.summary == "new")
        slow.release.signal()
        let obsolete = await oldTask.value
        precondition(obsolete == nil, "old revision must never publish late")
        precondition(cache.cachedDisplay(for: newer)?.summary == "new")
        precondition(cache.cachedDisplay(for: older) == nil)
        let rejected = await cache.value(for: older, probe: probe)
        precondition(rejected == nil, "outdated request must not replace newer cache entry")

        let invalidation = Gate(), beforeReset = request("B")
        let pending = Task { await cache.value(for: beforeReset) { _ in
            invalidation.block(); return .init(isConfigured: true, summary: "expired generation")
        } }
        await invalidation.awaitEntry()
        cache.invalidateAll()
        invalidation.release.signal()
        let invalidated = await pending.value
        precondition(invalidated == nil)
        precondition(cache.cachedDisplay(for: beforeReset) == nil)
        precondition(cache.cachedDisplay(for: newer) == nil)

        let cancellation = Gate(), cancelledRequest = request("C")
        let waiter = Task { await cache.value(for: cancelledRequest) { _ in
            cancellation.block(); return .init(isConfigured: true, summary: "cancelled")
        } }
        await cancellation.awaitEntry()
        waiter.cancel(); cancellation.release.signal()
        let cancelled = await waiter.value
        precondition(cancelled == nil)
        precondition(cache.cachedDisplay(for: cancelledRequest) == nil)

        // Exercise the production provider predicates against synthetic values.
        ProviderKeychainHelper.reset(); cache.invalidateAll()
        let missing = await cache.value(for: request("missing"))
        precondition(missing?.isConfigured == false && missing?.summary == "No API key")
        let keyless = await cache.value(for: request("keyless", emptyAllowed: true))
        precondition(keyless?.isConfigured == true && keyless?.summary == "No key required")
        ProviderKeychainHelper.setKey("abcdef1234567890", id: "key")
        let configured = await cache.value(for: request("key"))
        precondition(configured?.summary == "abcdef...7890")
        for type in [ProviderType.anthropic, .gemini, .openAI, .antigravity, .xAI, .kimiCode] {
            let id = "token-" + type.rawValue
            ProviderKeychainHelper.setToken(TestToken(accessToken: ""), id: id)
            let authenticated = await cache.value(for: request(id, type: type, credential: .oauth))
            precondition(authenticated?.isConfigured == true, "retain existing !=nil token rule")
        }
        ProviderKeychainHelper.setManual("", id: "manual")
        let manual = await cache.value(for: request("manual", credential: .oauth))
        precondition(manual?.isConfigured == true, "retain manual token presence rule")
        ProviderKeychainHelper.setToken(CopilotTokenStorage(githubToken: ""), id: "copilot")
        let copilot = await cache.value(for: request("copilot", type: .githubCopilot, credential: .oauth))
        precondition(copilot?.isConfigured == false)
        ProviderKeychainHelper.setToken(SubscriptionTokenStorage(provider: "workBuddy", accessToken: "synthetic"), id: "subscription")
        let wrongVendor = await cache.value(for: request("subscription", type: .traeCN, credential: .oauth))
        precondition(wrongVendor?.isConfigured == false)
        let rightVendor = await cache.value(for: request("subscription", 2, type: .workBuddy, credential: .oauth))
        precondition(rightVendor?.isConfigured == true)
        ProviderKeychainHelper.setReauth("subscription")
        let expired = await cache.value(for: request("subscription", 3, type: .workBuddy, credential: .oauth))
        precondition(expired?.isConfigured == false && expired?.needsReauth == true)
        precondition(expired?.summary == "Sign-in expired")
        print("PASS: production credential-cache concurrency, cancellation, invalidation and provider predicates")
    }
}
