import Foundation
import Network
import CFNetwork

/// Monitors network path changes and updates iSH's /etc/resolv.conf
/// so DNS resolution stays current when switching between WiFi/cellular/etc.
final class NetworkMonitor: @unchecked Sendable {
    static let shared = NetworkMonitor()

    private let monitor = NWPathMonitor()
    private let queue = DispatchQueue(label: "com.openminis.networkmonitor")
    private let logger = AppLogger(category: "Network")
    private var lastInterfaceTypes: Set<NWInterface.InterfaceType> = []
    private var isStarted = false

    // [T-network-recovery-20261102] A request that failed on the transport
    // layer must not burn another API key: the same credential is usually fine
    // on the other network. Wait for a real path transition (WiFi <-> cellular,
    // unsatisfied -> satisfied) and then retry the SAME request/key.
    private let pathLock = NSLock()
    private var pathGeneration: UInt64 = 0
    private var pathSatisfied = false
    private var pathExpensive = false

    private init() {}

    func start() {
        NSLog("NetworkMonitor: start() called, isStarted=%d", isStarted ? 1 : 0)
        guard !isStarted else { return }
        isStarted = true

        // Capture initial state and do an immediate DNS write so resolv.conf is
        // populated before the first NWPathMonitor callback fires (which can be
        // delayed by several hundred milliseconds).
        let initialPath = monitor.currentPath
        let initialTypes = activeInterfaceTypes(initialPath)
        pathLock.lock()
        lastInterfaceTypes = initialTypes
        pathSatisfied = initialPath.status == .satisfied
        pathExpensive = initialPath.isExpensive
        pathLock.unlock()
        logger.info("[Network] Monitor started — writing initial DNS config")
        NSLog("NetworkMonitor: about to refreshDns + dump proxy")
        ISHKernel.shared.refreshDns()
        dumpSystemProxySettings(reason: "monitor-start")

        monitor.pathUpdateHandler = { [weak self] path in
            self?.handlePathUpdate(path)
        }
        monitor.start(queue: queue)
    }

    func stop() {
        guard isStarted else { return }
        monitor.cancel()
        isStarted = false
        logger.info("[Network] Monitor stopped")
    }

    private func handlePathUpdate(_ path: NWPath) {
        let currentTypes = activeInterfaceTypes(path)
        let satisfied = path.status == .satisfied

        logger.info("[Network] Path update — status: \(String(describing: path.status)), interfaces: \(currentTypes.map { String(describing: $0) })")

        pathLock.lock()
        let typesChanged = currentTypes != lastInterfaceTypes
        lastInterfaceTypes = currentTypes
        let wasSatisfied = pathSatisfied
        let wasExpensive = pathExpensive
        pathSatisfied = satisfied
        pathExpensive = path.isExpensive
        // A pure signal-strength/route tick is not a new path. Only an
        // interface-set change or a satisfaction transition can rescue a dead
        // transport, so only those wake retrying requests.
        let satisfactionChanged = wasSatisfied != satisfied
        let expenseChanged = wasExpensive != path.isExpensive
        let transitioned = typesChanged || satisfactionChanged || expenseChanged
        if transitioned { pathGeneration &+= 1 }
        pathLock.unlock()

        // Always refresh DNS on any path update — even when unsatisfied, refreshDns
        // will write the public-DNS fallback so resolv.conf is never left empty.
        if !satisfied {
            logger.info("[Network] Network unsatisfied — writing fallback DNS")
        } else if typesChanged {
            logger.info("[Network] Interface change detected — refreshing DNS")
        } else {
            logger.info("[Network] Path updated — refreshing DNS")
        }

        ISHKernel.shared.refreshDns()
        dumpSystemProxySettings(reason: typesChanged ? "interface-change" : "path-update")

        // Evict pooled connections on a real interface change OR a
        // satisfaction transition (lost/restored connectivity, airplane
        // toggle). After such a transition the pooled HTTP/2 sockets can be
        // dead; reusing one hangs until the 600s timeout. A plain tick with the
        // same interface and same satisfaction (signal wobble, route refresh)
        // does NOT evict, so steady state is undisturbed. Mirrors Android #740.
        if typesChanged || satisfactionChanged || expenseChanged {
            LLMSessionRegistry.shared.evictAllConnections(
                reason: satisfied ? "connectivity-restored" : "connectivity-lost")
        }
    }
    /// Diagnostic: dump CFNetwork's view of the system proxy settings.
    /// Used to verify what (if anything) we see on 5G + VPN scenarios before
    /// deciding whether/how to inject http_proxy into the iSH shell.
    private func dumpSystemProxySettings(reason: String) {
        guard let cf = CFNetworkCopySystemProxySettings()?.takeRetainedValue(),
              let dict = cf as? [String: Any] else {
            logger.info("[Proxy] dump (\(reason)): CFNetworkCopySystemProxySettings returned nil")
            return
        }

        // Pull the keys we care about. iOS marks every CFNetworkProxies* CF
        // constant unavailable, so we use the documented string literals (same
        // values the macOS constants resolve to).
        let httpEnabled  = (dict["HTTPEnable"]   as? Int)    ?? 0
        let httpHost     =  dict["HTTPProxy"]    as? String
        let httpPort     =  dict["HTTPPort"]     as? Int
        let httpsEnabled = (dict["HTTPSEnable"]  as? Int)    ?? 0
        let httpsHost    =  dict["HTTPSProxy"]   as? String
        let httpsPort    =  dict["HTTPSPort"]    as? Int
        let socksEnabled = (dict["SOCKSEnable"]  as? Int)    ?? 0
        let socksHost    =  dict["SOCKSProxy"]   as? String
        let socksPort    =  dict["SOCKSPort"]    as? Int
        let pacEnabled   = (dict["ProxyAutoConfigEnable"]    as? Int) ?? 0
        let pacURL       =  dict["ProxyAutoConfigURLString"] as? String
        let exceptions   =  dict["ExceptionsList"]           as? [String]

        logger.info("[Proxy] dump (\(reason)) http=\(httpEnabled):\(httpHost ?? "-"):\(httpPort.map(String.init) ?? "-") https=\(httpsEnabled):\(httpsHost ?? "-"):\(httpsPort.map(String.init) ?? "-") socks=\(socksEnabled):\(socksHost ?? "-"):\(socksPort.map(String.init) ?? "-") pac=\(pacEnabled):\(pacURL ?? "-") exceptions=\(exceptions ?? [])")

        // Also dump every other key CFNetwork hands back so we don't miss
        // VPN-specific or future fields.
        let knownKeys: Set<String> = [
            "HTTPEnable", "HTTPProxy", "HTTPPort",
            "HTTPSEnable", "HTTPSProxy", "HTTPSPort",
            "SOCKSEnable", "SOCKSProxy", "SOCKSPort",
            "ProxyAutoConfigEnable", "ProxyAutoConfigURLString",
            "ExceptionsList",
        ]
        let extras = dict.filter { !knownKeys.contains($0.key) }
        if !extras.isEmpty {
            logger.info("[Proxy] dump (\(reason)) extra keys: \(extras)")
        }

        // Per-URL probe: ask CFNetwork what it would actually pick for a real
        // request. On VPN-injected / PAC scenarios this may return a proxy
        // even when the top-level dict above looks empty.
        if let probeURL = URL(string: "https://api.anthropic.com/v1/messages") {
            let arr = CFNetworkCopyProxiesForURL(probeURL as CFURL, cf).takeRetainedValue() as? [[String: Any]]
            logger.info("[Proxy] dump (\(reason)) CFNetworkCopyProxiesForURL(api.anthropic.com)=\(arr ?? [])")
        }
    }

    /// Human-readable active path; expensive Wi-Fi is not assumed cellular.
    func currentPathKind() -> String { pathSnapshot().kind }

    /// One atomic snapshot ties observations to the path at dispatch.
    func pathSnapshot() -> (generation: UInt64, satisfied: Bool, kind: String) {
        pathLock.lock(); defer { pathLock.unlock() }
        let kind: String
        if !pathSatisfied { kind = "离线" }
        else if lastInterfaceTypes.contains(.wifi) { kind = "Wi-Fi" }
        else if lastInterfaceTypes.contains(.cellular) { kind = "4G" }
        else if lastInterfaceTypes.contains(.wiredEthernet) { kind = "有线网络" }
        else { kind = "未知线路" }
        return (pathGeneration, pathSatisfied, kind)
    }

    private func activeInterfaceTypes(_ path: NWPath) -> Set<NWInterface.InterfaceType> {
        // `availableInterfaces` can list WiFi AND cellular at once even though
        // only one carries the default route. `usesInterfaceType` describes the
        // ACTIVE path, so a WiFi↔cellular switch is a real generation change
        // and can wake a pending retry immediately.
        let known: [NWInterface.InterfaceType] = [
            .wifi, .cellular, .wiredEthernet, .loopback, .other,
        ]
        return Set(known.filter { path.usesInterfaceType($0) })
    }
}


/// Small non-persistent observations, scoped by provider entry AND model.
/// An opened stream alone is not a successful model response.
enum NetworkLineHealth {
    private struct Observation {
        var lastSuccess: Date?
        var lastFailure: Date?
        var updatedAt: Date { max(lastSuccess ?? .distantPast, lastFailure ?? .distantPast) }
    }
    private static let lock = NSLock()
    nonisolated(unsafe) private static var observations: [String: Observation] = [:]
    private static let lifetime: TimeInterval = 10 * 60
    private static let capacity = 64
    private static func key(scope: String, network: String) -> String { scope + "|" + network }

    // Called with lock held; pure in-memory bookkeeping, no storage/callbacks.
    private static func prune(now: Date) {
        observations = observations.filter {
            let age = now.timeIntervalSince($0.value.updatedAt)
            return age >= 0 && age <= lifetime
        }
        while observations.count > capacity {
            guard let oldest = observations.min(by: { $0.value.updatedAt < $1.value.updatedAt }) else { break }
            observations.removeValue(forKey: oldest.key)
        }
    }

    static func noteSuccess(scope: String, network: String, at date: Date = Date()) {
        lock.lock(); defer { lock.unlock() }
        prune(now: date)
        let id = key(scope: scope, network: network)
        var item = observations[id] ?? Observation()
        item.lastSuccess = date; observations[id] = item
        prune(now: date)
    }

    static func noteFailure(scope: String, network: String, at date: Date = Date()) {
        lock.lock(); defer { lock.unlock() }
        prune(now: date)
        let id = key(scope: scope, network: network)
        var item = observations[id] ?? Observation()
        item.lastFailure = date; observations[id] = item
        prune(now: date)
    }

    static func alternativeNetwork(for scope: String, current: String, now: Date = Date()) -> String? {
        lock.lock(); defer { lock.unlock() }
        prune(now: now)
        var best: (String, Date)?
        for candidate in ["Wi-Fi", "4G"] where candidate != current {
            guard let item = observations[key(scope: scope, network: candidate)],
                  let success = item.lastSuccess,
                  now.timeIntervalSince(success) >= 0,
                  now.timeIntervalSince(success) <= lifetime,
                  item.lastFailure.map({ $0 < success }) ?? true else { continue }
            if best == nil || success > best!.1 { best = (candidate, success) }
        }
        return best?.0
    }
}
