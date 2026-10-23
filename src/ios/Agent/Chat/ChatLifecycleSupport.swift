import Combine
import Foundation
import SwiftUI
import UIKit
import UserNotifications

private let logger = AppLogger(category: "AIChatVM")

// MARK: - Session Activity Tracker

/// Tracks which sessions are currently processing, so the home screen
/// can display a spinner even when the user navigates away from the chat.
@MainActor
final class SessionActivityTracker: ObservableObject {
    static let shared = SessionActivityTracker()
    /// Session IDs that are currently processing (streaming / running tools).
    /// Canonical keys are real session IDs (UUIDs). Draft IDs are mirrored
    /// through `draftAliases` instead — see `setDraftAlias` — so the tracker
    /// only ever stores one entry per active session, preserving the
    /// "processing ends → entry clears" invariant that Live Activity relies
    /// on.
    @Published var activeSessions: Set<String> = []
    /// Maps a sidebar draft ID to its real session ID after ensureSession
    /// migrates from draft→real. Allows sidebar proxy rows that still
    /// identify themselves by draftId (ContentView's `displaySessions`) to
    /// reflect the live state of their underlying real session without
    /// double-inserting into `activeSessions`.
    @Published var draftAliases: [String: String] = [:]
    @Published var currentToolStatus: String = ""

    /// Per-session tool info for Live Activity carousel.
    struct SessionToolInfo {
        var title: String = ""
        var toolName: String = ""
        var toolStatus: String = ""
        var loopIteration: Int = 0
        /// When `toolName` last changed. Used to pick the most-recently-invoked
        /// tool across all sessions for the Dynamic Island minimal icon.
        var lastToolChange: Date = .distantPast
        /// [T-agent-inner-tool-front] Last time ANYTHING about this session's
        /// tool changed — the name or just the status line.
        ///
        /// Distinct from `lastToolChange`, which only moves when the tool NAME
        /// changes and drives the Dynamic Island's "most recent tool" pick. An
        /// agent doing ten browser_use operations in a row never changes its
        /// name, so a picker keyed on that would see it as idle the whole time.
        var lastActivity: Date = .distantPast
    }
    @Published var sessionToolInfo: [String: SessionToolInfo] = [:]

    /// The SF Symbol for the most-recently-invoked tool across all active
    /// sessions (the session whose `toolName` changed last). Drives the
    /// Dynamic Island minimal icon's "latest tool" frame. Nil when no active
    /// session has a tool yet.
    func latestToolName() -> String? {
        let active = activeSessions
        return sessionToolInfo
            .filter { active.contains($0.key) && !$0.value.toolName.isEmpty }
            .max { $0.value.lastToolChange < $1.value.lastToolChange }?
            .value.toolName
    }
    private var lastLiveActivityPush: Date = .distantPast
    private static let liveActivityThrottleInterval: TimeInterval = 5.0
    private var throttledUpdateWorkItem: DispatchWorkItem?

    func updateToolInfo(sessionId: String, toolName: String, toolStatus: String) {
        var info = sessionToolInfo[sessionId] ?? SessionToolInfo()
        let nameChanged = info.toolName != toolName
        let statusChanged = info.toolStatus != toolStatus
        info.toolName = toolName
        info.toolStatus = toolStatus
        if nameChanged {
            info.lastToolChange = Date()
        }
        if nameChanged || statusChanged {
            info.lastActivity = Date()
        }
        sessionToolInfo[sessionId] = info
        guard nameChanged || statusChanged else { return }
        // [T-log-noise-privacy] No `status` text: it is the model's own
        // description of what it is doing right now ("搜索苹果 Q4 财报详情") —
        // user-facing content, written to the log on EVERY tool step of every
        // running session, which sub agents multiply by the fan-out width.
        // The tool name and the changed flag are what the Live Activity and
        // the tool bar actually key off; the prose was only ever incidental.
        logger.info("[LiveActivity][toolInfo] sid=\(sessionId.prefix(8)) toolName=\(toolName) statusLen=\(toolStatus.count) nameChanged=\(nameChanged)")
        if nameChanged {
            throttledUpdateWorkItem?.cancel()
            throttledUpdateWorkItem = nil
            lastLiveActivityPush = Date()
            BackgroundKeepAliveManager.shared.updateLiveActivityIfNeeded(source: "toolNameChange")
        } else {
            let elapsed = Date().timeIntervalSince(lastLiveActivityPush)
            if elapsed >= Self.liveActivityThrottleInterval {
                throttledUpdateWorkItem?.cancel()
                throttledUpdateWorkItem = nil
                lastLiveActivityPush = Date()
                BackgroundKeepAliveManager.shared.updateLiveActivityIfNeeded(source: "toolStatusChange")
            } else if throttledUpdateWorkItem == nil {
                let delay = Self.liveActivityThrottleInterval - elapsed
                let work = DispatchWorkItem { [weak self] in
                    guard let self else { return }
                    self.lastLiveActivityPush = Date()
                    self.throttledUpdateWorkItem = nil
                    BackgroundKeepAliveManager.shared.updateLiveActivityIfNeeded(source: "toolStatusThrottled")
                }
                throttledUpdateWorkItem = work
                DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: work)
            }
        }
    }

    func updateLoopIteration(_ sessionId: String, iteration: Int) {
        var info = sessionToolInfo[sessionId] ?? SessionToolInfo()
        info.loopIteration = iteration
        sessionToolInfo[sessionId] = info
    }

    func updateSessionTitle(_ sessionId: String, title: String) {
        var info = sessionToolInfo[sessionId] ?? SessionToolInfo()
        guard info.title != title else { return }
        info.title = title
        sessionToolInfo[sessionId] = info
        BackgroundKeepAliveManager.shared.updateLiveActivityIfNeeded(source: "titleChange")
    }

    /// Thread-safe mirror of `activeSessions` + `draftAliases`, readable from
    /// non-MainActor contexts — notably the ChatStore actor's iCloud merge
    /// path, which must know whether a session is mid-run before applying a
    /// remote message. The `@MainActor`-isolated published state can't be read
    /// off-main, so every mutation also refreshes this lock-guarded snapshot.
    private static let mirrorLock = NSLock()
    nonisolated(unsafe) private static var activeSessionsMirror: Set<String> = []
    nonisolated(unsafe) private static var draftAliasesMirror: [String: String] = [:]

    /// Non-MainActor query: is this session (or its draft alias) running
    /// locally? Used by sync to avoid clobbering a session that's actively
    /// streaming / running tools.
    nonisolated static func isActiveThreadSafe(_ sessionId: String) -> Bool {
        mirrorLock.lock(); defer { mirrorLock.unlock() }
        if activeSessionsMirror.contains(sessionId) { return true }
        if let real = draftAliasesMirror[sessionId], activeSessionsMirror.contains(real) { return true }
        return false
    }

    private func syncMirror() {
        Self.mirrorLock.lock()
        Self.activeSessionsMirror = activeSessions
        Self.draftAliasesMirror = draftAliases
        Self.mirrorLock.unlock()
    }

    func setActive(_ sessionId: String, source: String = #function) {
        let wasPresent = activeSessions.contains(sessionId)
        activeSessions.insert(sessionId)
        syncMirror()
        logger.info("🟢[Tracker] setActive(\(sessionId.prefix(8))) src=\(source) wasPresent=\(wasPresent) now count=\(activeSessions.count) ids=[\(activeSessions.map { $0.prefix(8) }.joined(separator: ","))]")
    }

    func setInactive(_ sessionId: String, source: String = #function) {
        let wasPresent = activeSessions.contains(sessionId)
        activeSessions.remove(sessionId)
        sessionToolInfo.removeValue(forKey: sessionId)
        // Drop any alias pointing at this session — if the real session is
        // no longer active, its draft alias should not linger either.
        let orphanedAliases = draftAliases.filter { $0.value == sessionId }.map { $0.key }
        for draftKey in orphanedAliases {
            draftAliases.removeValue(forKey: draftKey)
        }
        syncMirror()
        logger.info("🔴[Tracker] setInactive(\(sessionId.prefix(8))) src=\(source) wasPresent=\(wasPresent) now count=\(activeSessions.count) ids=[\(activeSessions.map { $0.prefix(8) }.joined(separator: ","))] clearedAliases=\(orphanedAliases.count)")
    }

    /// Register an alias from a draft ID to its newly-minted real session
    /// ID. After this, `isActive(draftId)` returns `isActive(realId)`.
    /// Removed automatically when the real session goes inactive.
    func setDraftAlias(draft draftId: String, real realId: String) {
        draftAliases[draftId] = realId
        syncMirror()
        logger.info("🔗[Tracker] setDraftAlias(\(draftId.prefix(8)) → \(realId.prefix(8)))")
    }

    func isActive(_ sessionId: String) -> Bool {
        if activeSessions.contains(sessionId) { return true }
        if let realId = draftAliases[sessionId],
           activeSessions.contains(realId) { return true }
        return false
    }

    /// `isActive` in aggregation-pass form: active ids with draft aliases
    /// resolved IN, so callers sweeping a whole list (the sidebar grouping)
    /// build this once and do plain hash lookups per member instead of
    /// entering the tracker per member. O(active + aliases) — tiny.
    var resolvedActiveSessionIds: Set<String> {
        var out = activeSessions
        for (draftId, realId) in draftAliases where activeSessions.contains(realId) {
            out.insert(draftId)
        }
        return out
    }
}

/// Keeps the screen awake while any chat session is running a task, when the
/// user has opted in via Appearance Settings. Toggles
/// `UIApplication.isIdleTimerDisabled` from transitions of
/// `SessionActivityTracker.activeSessions`; revokes the lock as soon as all
/// sessions go idle so we don't keep the screen on longer than necessary.
@MainActor
final class KeepScreenAwakeController {
    static let shared = KeepScreenAwakeController()

    static let userDefaultsKey = "keepScreenAwakeDuringTasks"

    private var activityCancellable: AnyCancellable?
    private var defaultsObserver: NSObjectProtocol?
    private var backgroundObserver: NSObjectProtocol?
    private var foregroundObserver: NSObjectProtocol?
    private var lockHeld = false
    private var appInBackground = false

    private init() {}

    /// Wire up observers. Safe to call once at app launch.
    func start() {
        // Use a strong `self` capture — this is a singleton and the
        // cancellables/observers live for the app lifetime. A `[weak self]`
        // here would never actually fire anyway, but writing `self` avoids
        // the class of bugs where a subtle retain-cycle audit removes the
        // shared reference and the sink silently becomes a no-op.
        activityCancellable = SessionActivityTracker.shared.$activeSessions
            .receive(on: DispatchQueue.main)
            .sink { _ in
                KeepScreenAwakeController.shared.refresh(reason: "tracker")
            }

        // `UserDefaults.didChangeNotification` fires for every key in the
        // suite, which is very chatty but cheap — refresh() is idempotent
        // and short-circuits when shouldHoldLock matches the current state.
        defaultsObserver = NotificationCenter.default.addObserver(
            forName: UserDefaults.didChangeNotification,
            object: nil, queue: .main
        ) { _ in
            KeepScreenAwakeController.shared.refresh(reason: "defaults")
        }

        // Release the lock when the app is not in the foreground so we
        // don't keep a backgrounded device awake (the system puts us to
        // sleep soon anyway, but being explicit avoids holding the lock
        // across a background→foreground cycle if iOS ever keeps us
        // scheduled longer than expected).
        backgroundObserver = NotificationCenter.default.addObserver(
            forName: UIApplication.didEnterBackgroundNotification,
            object: nil, queue: .main
        ) { _ in
            KeepScreenAwakeController.shared.onScenePhaseChanged(background: true)
        }
        foregroundObserver = NotificationCenter.default.addObserver(
            forName: UIApplication.willEnterForegroundNotification,
            object: nil, queue: .main
        ) { _ in
            // [T-ios-scenephase-active-sigkill] Defer the foreground transition
            // off the synchronous notification delivery. Writing isIdleTimerDisabled
            // synchronously here overlaps with SwiftUI view-graph re-evaluation
            // during the foreground transition → SIGKILL. Matches the deferral
            // pattern in BackgroundKeepAliveManager (6e54b5fd). The background
            // observer above stays synchronous — backgrounding has no view-graph risk.
            Task { @MainActor in
                await Task.yield()
                KeepScreenAwakeController.shared.onScenePhaseChanged(background: false)
            }
        }

        refresh(reason: "start")
    }

    private func onScenePhaseChanged(background: Bool) {
        appInBackground = background
        refresh(reason: background ? "background" : "foreground")
    }

    /// Evaluate the desired idle-timer state and apply it when it differs
    /// from the current held state. Safe to call from any observer.
    private func refresh(reason: String) {
        let enabled = UserDefaults.standard.bool(forKey: Self.userDefaultsKey)
        let sessionCount = SessionActivityTracker.shared.activeSessions.count
        let hasRunningTask = sessionCount > 0
        // Three ways to release the lock:
        //   - user turned the setting off
        //   - nothing is running
        //   - app went to background (system will sleep us anyway; we just
        //     want to not hold a stale lock)
        let shouldHoldLock = enabled && hasRunningTask && !appInBackground

        guard shouldHoldLock != lockHeld else {
            logger.debug("[KeepScreen] noop reason=\(reason) sessions=\(sessionCount) enabled=\(enabled) bg=\(self.appInBackground) held=\(self.lockHeld)")
            return
        }
        UIApplication.shared.isIdleTimerDisabled = shouldHoldLock
        lockHeld = shouldHoldLock
        logger.info("[KeepScreen] isIdleTimerDisabled=\(shouldHoldLock) reason=\(reason) sessions=\(sessionCount) enabled=\(enabled) bg=\(self.appInBackground)")
    }
}

// MARK: - Session Concurrency Manager

/// Limits the number of sessions actively running LLM requests.
/// Excess sessions are suspended in FIFO order and resumed when slots free up.
@MainActor
final class SessionConcurrencyManager: ObservableObject {
    static let shared = SessionConcurrencyManager()

    // Shared by ordinary chat sessions regardless of provider/model.
    let maxConcurrent: Int = 10

    @Published private(set) var runningSessions: Set<String> = []
    @Published private(set) var suspendedSessions: [String] = []
    private var waiters: [(id: String, continuation: CheckedContinuation<Void, Never>)] = []

    /// Acquire a processing slot. Returns immediately if under limit, otherwise suspends until a slot opens.
    func acquireSlot(sessionId: String) async throws {
        if runningSessions.count < maxConcurrent {
            runningSessions.insert(sessionId)
            return
        }

        // Over limit — suspend and wait
        suspendedSessions.append(sessionId)
        await withCheckedContinuation { (continuation: CheckedContinuation<Void, Never>) in
            waiters.append((id: sessionId, continuation: continuation))
        }
        // After resuming, check if the task was cancelled while waiting
        try Task.checkCancellation()
        runningSessions.insert(sessionId)
    }

    /// Release a processing slot and resume the next waiting session (FIFO).
    func releaseSlot(sessionId: String) {
        runningSessions.remove(sessionId)
        resumeNextWaiter()
    }

    /// Cancel a suspended session's wait so cancellation can propagate.
    func cancelWait(sessionId: String) {
        suspendedSessions.removeAll { $0 == sessionId }
        if let idx = waiters.firstIndex(where: { $0.id == sessionId }) {
            let waiter = waiters.remove(at: idx)
            waiter.continuation.resume()
        }
    }

    /// Whether a session is currently suspended waiting for a slot.
    func isSuspended(_ sessionId: String) -> Bool {
        suspendedSessions.contains(sessionId)
    }

    private func resumeNextWaiter() {
        guard !waiters.isEmpty else { return }
        let next = waiters.removeFirst()
        suspendedSessions.removeAll { $0 == next.id }
        next.continuation.resume()
    }
}

// MARK: - ViewModel Cache

/// Caches AIChatViewModel instances by session ID so re-entering a session
/// reuses the same (possibly still-running) ViewModel instead of creating a new one.
@MainActor
final class ViewModelCache {
    static let shared = ViewModelCache()

    /// [T-vmcache-pools] Which LRU pool a cached VM belongs to.
    ///
    /// Child (sub agent) conversations must not compete with the user's own
    /// for the ordinary budget: a fan-out of three sub agents used to evict
    /// three normal conversations, and a long-running child could hold a slot
    /// the user never sees. They get their own, larger pool instead.
    enum PoolKind: String {
        /// A conversation the user opens directly.
        case normal
        /// A sub agent / helper run. Created by HelperRunner, usually never
        /// displayed; see `releaseRenderState`.
        case child
    }

    private var cache: [String: AIChatViewModel] = [:]

    /// Pool membership per session id. Absent ⇒ `.normal`, so every existing
    /// call site keeps its previous behaviour without passing anything.
    private var poolKinds: [String: PoolKind] = [:]

    /// Session IDs in least-recently-used → most-recently-used order. Kept in
    /// sync with `cache`: appended/moved to the end on every access, removed
    /// with the entry. Drives soft-cap eviction so we don't retain a fully
    /// loaded ViewModel (messages + agentHistory + parsed markdown blocks) for
    /// every session opened since launch — the primary driver of the app's
    /// resident-memory baseline, which pushes the process toward jetsam once
    /// iSH (gh/python3) adds its own footprint. [T-ios-vmcache-lru-evict]
    private var lruOrder: [String] = []

    /// Soft cap on cached ViewModels. Beyond this, the least-recently-used
    /// NON-processing VMs are evicted (a processing VM is never evicted — its
    /// agent loop must keep running). Re-entering an evicted session rebuilds
    /// the VM and re-hydrates messages from SQLite via the normal isNew path.
    /// [T-ios-vmcache-lru-evict]
    private static let softCap: Int = 6

    /// [T-vmcache-pools] Separate, larger cap for child (sub agent) VMs.
    ///
    /// Larger than the normal cap because a single fan-out can legitimately
    /// hold several children at once (`AgentJobRegistry.maxConcurrentChildJobs`
    /// is 3, and finished-but-not-yet-swept children linger), while each child
    /// is cheaper: `releaseRenderState` strips its render state as soon as it
    /// is not on screen, so a resident child is mostly message text.
    private static let childSoftCap: Int = 10

    init() {
        // Evict aggressively under memory pressure — same hook BrowserTabPool
        // and ThumbnailCache use. Drops every non-processing cached VM (and
        // its messages / history / parsed-markdown trees).
        NotificationCenter.default.addObserver(
            forName: UIApplication.didReceiveMemoryWarningNotification,
            object: nil,
            queue: .main
        ) { [weak self] _ in
            MainActor.assumeIsolated { self?.evictOnMemoryWarning() }
        }
    }
    /// Session IDs whose underlying SQLite rows were mutated by an
    /// inbound iCloud merge while the user was NOT on that session's
    /// chat screen. The next `getOrCreate` HIT for one of these IDs
    /// returns `isStale=true` so AIChatView can trigger a reload
    /// instead of rendering the cached `messages` snapshot. The set is
    /// consumed (drained) on read — a single reload pays off the debt.
    /// See ChatStore.mergeRemoteMessage for the producer side
    /// (T-inbound-message-cached-vm-stale).
    private var staleSessionIds: Set<String> = []

    /// Get an existing ViewModel for the session, or create and cache a new one.
    /// Returns `(vm, isNew)` — caller should only call `loadSession()` when `isNew` is true.
    /// For staleness-aware callers (e.g. AIChatView's init), additionally check
    /// `consumeStaleFlag(sessionId:)` AFTER this call and trigger a reload
    /// when it returns true.
    func getOrCreate(for sessionId: String, kind: PoolKind = .normal) -> (vm: AIChatViewModel, isNew: Bool) {
        // A session's pool is decided by whoever FIRST caches it, and then
        // sticks. HelperRunner passes `.child`; everyone else gets `.normal`
        // by default, so the 18 non-helper call sites needed no change.
        //
        // [T-vmcache-pool-sticky] Assign only when unset. The tag has to be
        // immune in BOTH directions, not just one:
        //
        //  • child → normal: HelperBlockView / HelperSheet open a child for
        //    VIEWING and must not thereby move it into the user's budget.
        //    Covered by only writing on `.child`.
        //  • normal → child: a `.child` call naming an ordinary session would
        //    have silently re-tagged it, moving a conversation the user owns
        //    into the sub agent pool — where it is swept against a different
        //    cap and, worse, released by HelperSheet's disappear handler.
        //    Reachable today: `debug.agent.openHelperSheet` takes an arbitrary
        //    `childSessionId` from the caller (DebugJSONRPC.swift:2833), and
        //    nothing downstream proves it is really a child.
        //
        // Whichever kind wins is therefore the one the session was first
        // created under, which is the only one with real information behind it.
        if kind == .child, poolKinds[sessionId] == nil, cache[sessionId] == nil {
            poolKinds[sessionId] = .child
        }
        if let existing = cache[sessionId] {
            touch(sessionId)
            logger.info("🔄SESSION ViewModelCache HIT session=\(sessionId) vm=\(existing.vmInstanceId) isProcessing=\(existing.isProcessing)")
            return (existing, false)
        }
        let vm = AIChatViewModel()
        vm.sessionId = sessionId
        cache[sessionId] = vm
        touch(sessionId)
        // A brand-new cache entry doesn't need the stale signal — its
        // `isNew` path already triggers loadSession — clear any
        // accumulated marker so we don't carry it past a remove+recreate.
        staleSessionIds.remove(sessionId)
        let isStillActive = SessionActivityTracker.shared.activeSessions.contains(sessionId)
        logger.info("🔄SESSION ViewModelCache MISS session=\(sessionId) vm=\(vm.vmInstanceId) — created new, trackerActive=\(isStillActive)")
        if isStillActive {
            logger.warning("[BlocksLost] ViewModelCache MISS for tracker-active session \(sessionId.prefix(8)) — agent loop running on a different VM; new VM will pick up results via detachedLoopEnd notification")
        }
        evictIfOverCap()
        return (vm, true)
    }

    /// Returns true if the given session was marked stale by an inbound
    /// iCloud merge since the cached VM last loaded, and consumes the
    /// flag in the same call so a single reload pays off the debt. Safe
    /// to call even when no VM is cached (returns false).
    func consumeStaleFlag(sessionId: String) -> Bool {
        staleSessionIds.remove(sessionId) != nil
    }

    /// Mark a cached session as having stale messages (e.g. iCloud merged
    /// new MessageV2 rows into SQLite). No-op when the session has no
    /// cached VM. When the session IS the foreground-visible one,
    /// `.cloudSyncDidFetchChanges` already drove an in-place reload via
    /// `reloadMessagesFromDB`, so this only matters for background
    /// sessions opened later (T-inbound-message-cached-vm-stale).
    func markStale(sessionId: String) {
        guard cache[sessionId] != nil else { return }
        staleSessionIds.insert(sessionId)
    }

    /// Get an existing cached ViewModel without creating a new one.
    func get(for sessionId: String) -> AIChatViewModel? {
        if cache[sessionId] != nil { touch(sessionId) }
        return cache[sessionId]
    }

    /// Remove a session's ViewModel from the cache (e.g. on session delete).
    /// Deliberately still a `cancel()`: this is session DELETION, where the
    /// conversation and its in-flight work really are meant to stop. Only the
    /// capacity-driven paths above were changed to release instead.
    func remove(sessionId: String) {
        lruOrder.removeAll { $0 == sessionId }
        poolKinds.removeValue(forKey: sessionId)
        if let removed = cache.removeValue(forKey: sessionId) {
            removed.cancel()
            logger.info("🔄SESSION ViewModelCache REMOVE session=\(sessionId) vm=\(removed.vmInstanceId)")
        }
    }

    /// Create a fresh (uncached) ViewModel for draft sessions (nil sessionId).
    func createDraft() -> AIChatViewModel {
        let vm = AIChatViewModel()
        logger.info("🔄SESSION ViewModelCache createDraft vm=\(vm.vmInstanceId)")
        return vm
    }

    /// Move a draft ViewModel into the cache once its session ID is assigned.
    func cacheDraft(_ vm: AIChatViewModel, sessionId: String) {
        cache[sessionId] = vm
        touch(sessionId)
        logger.info("🔄SESSION ViewModelCache cacheDraft session=\(sessionId) vm=\(vm.vmInstanceId)")
        evictIfOverCap()
    }

    // MARK: - LRU eviction

    /// Mark a session as most-recently-used.
    private func touch(_ sessionId: String) {
        lruOrder.removeAll { $0 == sessionId }
        lruOrder.append(sessionId)
    }

    /// Evict least-recently-used, non-processing VMs down to `softCap`.
    /// A processing VM (running agent loop) is skipped — it must stay alive —
    /// so the resident count can briefly exceed the cap when many sessions are
    /// processing at once, which is intended.
    /// A VM must stay resident if its agent loop is running OR it's the
    /// session the user is currently viewing (evicting the foreground VM would
    /// drop its unsent input draft / scroll state and force a reload mid-view).
    private func isEvictable(_ sessionId: String, _ vm: AIChatViewModel) -> Bool {
        if vm.isProcessing { return false }
        if sessionId == AIChatViewModel.activeSessionId { return false }
        if SessionActivityTracker.shared.activeSessions.contains(sessionId) { return false }
        // [T-ios-evict-cancels-subagents] A parent whose own loop has ENDED but
        // which still has sub agents running in the background is NOT idle.
        //
        // `isProcessing` describes this VM's own agent loop only. The ordinary
        // background-delegation shape is: the parent delegates, finishes its
        // turn (isProcessing → false) and waits for the callback. Such a VM
        // looked evictable, and `evict` calls `vm.cancel()` — which is the full
        // user-Stop path, including `cancelAll(parent:)`. So an LRU sweep
        // silently killed live sub agents and logged them as
        // `reason=user stopped the conversation (silent)`, blaming a user who
        // had touched nothing.
        //
        // Observed: 22 evictions in one session, all `over softCap(6)`; job
        // 3CBA002A died 189s into a 30m budget this way, its parent reading
        // `isProcessing=false lastBlocks=4`.
        if AgentJobRegistry.shared.hasActiveChildren(parent: sessionId) { return false }
        return true
    }

    /// [T-vmcache-pools] Each pool is swept against its OWN cap, so a burst of
    /// sub agents can no longer evict the conversations the user is working in
    /// (and vice versa). Within a pool the order is still plain LRU.
    private func evictIfOverCap() {
        evictPool(.normal, cap: Self.softCap)
        evictPool(.child, cap: Self.childSoftCap)
    }

    private func poolKind(_ sessionId: String) -> PoolKind {
        poolKinds[sessionId] ?? .normal
    }

    private func evictPool(_ kind: PoolKind, cap: Int) {
        let members = lruOrder.filter { poolKind($0) == kind && cache[$0] != nil }
        guard members.count > cap else { return }
        var overflow = members.count - cap
        // Walk LRU → MRU within this pool only.
        for sessionId in members where overflow > 0 {
            guard let vm = cache[sessionId], isEvictable(sessionId, vm) else { continue }
            evict(sessionId, vm: vm, reason: "over \(kind.rawValue)Cap(\(cap))")
            overflow -= 1
        }
    }

    /// On a memory warning, drop every evictable cached VM (and its
    /// messages / agentHistory / parsed-markdown trees). Re-entering a
    /// session rebuilds its VM from SQLite.
    private func evictOnMemoryWarning() {
        let victims = cache.filter { isEvictable($0.key, $0.value) }
        for (sessionId, vm) in victims {
            evict(sessionId, vm: vm, reason: "memory warning")
        }
        // [T-renderer-cache-bounded] The renderers survive VM eviction (they
        // are keyed by message, on a static), so under real pressure they have
        // to be dropped explicitly or the warning frees far less than it looks.
        // Every VM that stays resident rebuilds its renderers lazily.
        let renderers = SelectableMarkdownView.dropAllRenderers()
        logger.info("🔄SESSION ViewModelCache memory-warning evicted \(victims.count) VM(s), \(self.cache.count) remain, dropped \(renderers) renderer(s)")
    }

    /// [T-vmcache-release] Evicting is a RELEASE, never a cancel.
    ///
    /// This line used to be `vm.cancel()` — the full user-Stop path, including
    /// `AgentJobRegistry.cancelAll(parent:silent:)`. A cache-size policy
    /// therefore reached through into the job registry and killed live sub
    /// agents, reporting them as a user stop (761be79da). `releaseForEviction`
    /// frees the same memory and touches no jobs.
    private func evict(_ sessionId: String, vm: AIChatViewModel, reason: String) {
        vm.releaseForEviction()
        cache.removeValue(forKey: sessionId)
        poolKinds.removeValue(forKey: sessionId)
        lruOrder.removeAll { $0 == sessionId }
        // Clearing the stale marker too — a rebuilt VM loads fresh from SQLite.
        staleSessionIds.remove(sessionId)
        logger.info("🔄SESSION ViewModelCache EVICT session=\(sessionId) vm=\(vm.vmInstanceId) (\(reason))")
    }

    // MARK: - Background UI Suspension

    /// Suspend streaming UI updates on ALL cached VMs that are actively
    /// processing. Called from MinisApp on scenePhase → .inactive so that
    /// no MarkdownRenderer layout work runs on the main thread while the
    /// app is transitioning to background — iOS can SIGKILL for excessive
    /// background CPU/rendering otherwise.
    func suspendAllStreamingUI() {
        for (_, vm) in cache where vm.isProcessing {
            vm.setStreamingUIUpdatesSuspended(true)
        }
    }

    /// [T-ios-stacknav-transition-attributegraph-race] Suspend every streaming
    /// vm across a WHOLE-TREE re-mount, then resume after `seconds`.
    ///
    /// Distinct from `suspendAllStreamingUI` above: that one sets the
    /// scroll/background THROTTLE (`streamingUIUpdatesSuspended`), this one
    /// sets the teardown GUARD (`transitionSuspended`), which is what keeps
    /// `objectWillChange` out of a hosting subgraph UIKit is destroying.
    ///
    /// The one caller is `MinisApp`'s `.id(appLanguage)` re-key: changing the
    /// app language drops and re-mounts the entire view tree, including a chat
    /// that may be mid-stream underneath the Settings sheet. That is the same
    /// race the two ContentView observers guard for push/pop, but there is no
    /// "outgoing session" to name — every mounted vm is outgoing — so it fans
    /// out over the cache.
    func suspendAllForTreeRemount(resumeAfter seconds: TimeInterval = 0.4) {
        var suspended: [AIChatViewModel] = []
        for (_, vm) in cache where vm.isProcessing {
            vm.setSuspendedForTransition(true)
            suspended.append(vm)
        }
        guard !suspended.isEmpty else { return }
        // Strong refs to the suspended vms are intentional: they must outlive
        // the window to be resumed, and the cache owns them regardless.
        DispatchQueue.main.asyncAfter(deadline: .now() + seconds) {
            for vm in suspended { vm.setSuspendedForTransition(false) }
        }
    }

    /// Resume streaming UI updates on ALL cached VMs, flushing any chunks
    /// that accumulated while backgrounded. Called from MinisApp on
    /// scenePhase → .active so the user sees the latest content
    /// immediately on return.
    func resumeAllStreamingUI() {
        var cleared = 0
        for (_, vm) in cache where vm.streamingUIUpdatesSuspended {
            vm.setStreamingUIUpdatesSuspended(false)
            cleared += 1
        }
        // [T-ios-scroll-suspend-leak] Record how many VMs this foreground-return
        // pass unblocked. A leaked scroll-suspend that survived a switch-away
        // gets cleared here on the NEXT foreground return — so a nonzero count
        // long after backgrounding is a signal the leak occurred.
        if cleared > 0 {
            logger.info("[SuspendState] resumeAllStreamingUI cleared \(cleared) suspended VM(s)")
            // [T-ios-tool-status-desync] Nudge the session list to re-query
            // the DB so the row subtitle picks up any tool_use blocks that
            // were persisted while the app was suspended. The per-VM
            // objectWillChange above covers in-chat views; this covers the
            // session list whose lastMessage comes from a DB query triggered
            // by .sessionDidUpdate.
            for (sid, vm) in cache where vm.isProcessing {
                NotificationCenter.default.post(name: .sessionDidUpdate, object: sid)
            }
        }
    }

    // MARK: - Pending Transfer

    /// Stash for input content being moved to another session.
    ///
    /// [T-ios-moveto-transfer-race] `targetId` and `createdAt` are load-bearing.
    /// The slot used to hold content only, so whichever AIChatView appeared
    /// first consumed it — if the push to the intended target was swallowed by
    /// a transition race, the content landed in whatever session the user
    /// happened to open next, or sat in the slot until they opened the target
    /// by hand. Consumers must now match `targetId` before consuming, and
    /// treat an entry older than `staleAfter` as abandoned.
    struct PendingTransfer {
        let targetId: String
        let inputText: String
        let attachments: [InputAttachment]
        let createdAt: Date

        /// A transfer that was never consumed this long after being staged has
        /// missed its navigation; it must not ambush a later session.
        static let staleAfter: TimeInterval = 30

        var isStale: Bool { Date().timeIntervalSince(createdAt) > Self.staleAfter }

        init(targetId: String, inputText: String, attachments: [InputAttachment]) {
            self.targetId = targetId
            self.inputText = inputText
            self.attachments = attachments
            self.createdAt = Date()
        }
    }

    /// Set by MoveToSessionSheet, consumed by AIChatView on appear — but only
    /// by the view whose session id matches `targetId`.
    static var pendingTransfer: PendingTransfer?

    // MARK: - Move-to seed  [T-ios-moveto-seed]

    /// The most recent session list any surface has loaded, kept so the
    /// "Move to…" sheet can paint populated on its first frame instead of
    /// waiting on the ChatStore actor.
    ///
    /// Why it lives here rather than being read from `ChatStore`: that store is
    /// a real `actor`, so its `sessionListCache` cannot be read synchronously
    /// from the main actor. Exposing it `nonisolated` would hand out an array
    /// that DB writes mutate concurrently — a genuine data race, not a
    /// theoretical one. This holder is `@MainActor` (the whole type is), so
    /// both the write and the read happen on the main actor and no isolation is
    /// crossed at all.
    ///
    /// Deliberately a plain snapshot, not a second source of truth: it is only
    /// ever used as a first-frame placeholder, and the sheet's own `.task`
    /// overwrites it with the authoritative query a moment later. Staleness is
    /// therefore bounded by one frame of display, and a wrong row corrects
    /// itself before it can be tapped in any realistic timing.
    private(set) static var recentSessionsSeed: [ChatSession] = []

    /// Record a freshly-loaded list as the seed. Callers pass whatever they
    /// just fetched; the child-session filter is applied here so every writer
    /// cannot forget it (child sessions are never move targets).
    static func noteSessionsLoaded(_ sessions: [ChatSession]) {
        let visible = sessions.filter { !$0.isChild }
        guard !visible.isEmpty else { return }   // never replace a good seed with nothing
        recentSessionsSeed = Array(visible.prefix(MoveToSeedLimit))
    }

    /// Cap on the stored seed. Matches the sheet's own `recentLimit`: holding
    /// more would just be retained memory the picker never shows.
    static let MoveToSeedLimit = 50

    /// Drop a staged transfer, deleting any attachment files it still owns so a
    /// discarded move doesn't leak cache entries.
    static func discardPendingTransfer(reason: String) {
        guard let transfer = pendingTransfer else { return }
        pendingTransfer = nil
        for a in transfer.attachments {
            try? FileManager.default.removeItem(at: a.cacheURL)
        }
        logger.info("[MoveTo] Discarded pending transfer for target=\(transfer.targetId) reason=\(reason)")
    }
}


// MARK: - [T-session-monitor] Which sessions report into the cross-session pill

/// Per-session opt-in for the cross-session status pill.
///
/// The user's model (2026-10-20): nothing shows unless a session is explicitly
/// marked 监看 from its long-press menu. That keeps the pill off by default —
/// no global switch to find — and makes "whose status am I seeing" a fact the
/// user set themselves rather than something the app guessed.
///
/// `startedAt` exists because the pill has to answer "多久了": the activity
/// tracker knows WHICH sessions are running, not since when. Recording the first
/// moment we saw a marked session running is enough for a per-session stopwatch,
/// and it is dropped the moment that session stops so the next run starts clean.
final class SessionMonitorStore: ObservableObject {
    static let shared = SessionMonitorStore()

    private static let defaultsKey = "monitoredSessionIds"

    /// Session ids the user marked 监看. Local-only, never synced: it is a view
    /// preference, not session data.
    @Published private(set) var monitored: Set<String> =
        Set(UserDefaults.standard.stringArray(forKey: SessionMonitorStore.defaultsKey) ?? [])

    /// First instant each monitored session was seen running.
    private var startedAt: [String: Date] = [:]

    private init() {}

    func isMonitored(_ sessionId: String) -> Bool {
        monitored.contains(sessionId)
    }

    /// Flip one session. Called from the sidebar's context menu.
    func toggle(_ sessionId: String) {
        if monitored.contains(sessionId) {
            monitored.remove(sessionId)
            startedAt.removeValue(forKey: sessionId)
        } else {
            monitored.insert(sessionId)
        }
        UserDefaults.standard.set(Array(monitored), forKey: Self.defaultsKey)
    }

    /// Reconcile with the live activity set: start a clock for every marked
    /// session that just began running, drop the clock of one that stopped.
    func sync(runningIds: Set<String>) {
        var touched = false
        for id in runningIds where monitored.contains(id) && startedAt[id] == nil {
            startedAt[id] = Date()
            touched = true
        }
        if !startedAt.isEmpty {
            for id in startedAt.keys where !runningIds.contains(id) {
                startedAt.removeValue(forKey: id)
                touched = true
            }
        }
        _ = touched
    }

    /// How long this monitored session has been running, or nil when it is idle.
    func elapsed(_ sessionId: String) -> TimeInterval? {
        startedAt[sessionId].map { Date().timeIntervalSince($0) }
    }

    /// Drop marks for sessions that no longer exist (deleted, or a draft that
    /// never materialised), so the set cannot grow stale forever.
    func prune(keeping liveIds: Set<String>) {
        let pruned = monitored.intersection(liveIds)
        guard pruned.count != monitored.count else { return }
        monitored = pruned
        startedAt = startedAt.filter { liveIds.contains($0.key) }
        UserDefaults.standard.set(Array(pruned), forKey: Self.defaultsKey)
    }
}

// MARK: - [T-session-photo-icon] A session may use a photo instead of its category glyph

/// Per-session custom icon, keyed by the persisted session id, never by a
/// folder id. Existing 96px PNG data URIs remain readable; new sidebar picks
/// use 132px (44pt @3x). These local display preferences do not change chat
/// records or iCloud payloads.
final class SessionIconStore: ObservableObject {
    static let shared = SessionIconStore()
    private static let defaultsKey = "sessionCustomIcons"

    @Published private(set) var icons: [String: String] =
        (UserDefaults.standard.dictionary(forKey: SessionIconStore.defaultsKey) as? [String: String]) ?? [:]
    private var revisions: [String: UInt64] = [:]
    private let imageCache = NSCache<NSString, UIImage>()
    /// [T-icon-save-offmain] UserDefaults writes go over XPC to cfprefsd and
    /// block the caller. Writing the whole icon dictionary synchronously from
    /// `setIcon` ran on the main thread at the exact moment the app came back
    /// from PHPickerViewController — a background-to-foreground transition.
    /// iOS gives that transition 10 s (scene-update watchdog); with a few
    /// dozen icons the cfprefsd round-trip plus the sidebar re-render blew it
    /// and the app was SIGKILLed with 0x8badf00d at 02:27 and 02:38.
    /// Persist a snapshot on a utility queue instead; the in-memory state and
    /// revision counter still update synchronously so the UI reacts at once.
    private let persistQueue = DispatchQueue(label: "com.minis.sessionIcons.persist", qos: .utility)

    private init() { imageCache.countLimit = 64 }

    private func schedulePersist() {
        let snapshot = icons
        persistQueue.async { UserDefaults.standard.set(snapshot, forKey: Self.defaultsKey) }
    }

    func icon(for sessionId: String) -> String? {
        icons[sessionId]
    }

    /// Cheap snapshot for the sidebar's Equatable row, not a new row identity.
    func revision(for sessionId: String) -> UInt64 { revisions[sessionId] ?? 0 }

    func image(for sessionId: String) -> UIImage? {
        if let cached = imageCache.object(forKey: sessionId as NSString) { return cached }
        guard let uri = icons[sessionId], let image = SoulIconImage.decode(uri) else { return nil }
        imageCache.setObject(image, forKey: sessionId as NSString)
        return image
    }

    func setIcon(_ dataURI: String?, for sessionId: String) {
        let normalized: String? = dataURI?.isEmpty == false ? dataURI : nil
        guard icons[sessionId] != normalized else { return }
        imageCache.removeObject(forKey: sessionId as NSString)
        revisions[sessionId] = (revisions[sessionId] ?? 0) &+ 1
        if let dataURI = normalized {
            icons[sessionId] = dataURI
        } else {
            icons.removeValue(forKey: sessionId)
        }
        schedulePersist()
    }

    /// Call only with a complete set of live IDs, never visible/search results.
    func prune(keeping liveIds: Set<String>) {
        let kept = icons.filter { liveIds.contains($0.key) }
        guard kept.count != icons.count else { return }
        for id in icons.keys where !liveIds.contains(id) {
            imageCache.removeObject(forKey: id as NSString)
            revisions[id] = (revisions[id] ?? 0) &+ 1
        }
        icons = kept
        schedulePersist()
    }
}

// MARK: - [T-sidebar-icon-menu] Independent local folder photos

/// A folder remains a container, not a session. Its photo lives in its OWN
/// namespace, keyed by folder.id rather than name, latest member or session.id.
/// Do not put a photo into ChatFolder.icon: that field is an iCloud-synced
/// SF Symbol name. No database migration or sync change is needed here.
final class FolderIconStore: ObservableObject {
    static let shared = FolderIconStore()
    private static let defaultsKey = "folderCustomIcons"
    private let defaults: UserDefaults
    @Published private(set) var icons: [String: String]
    private let imageCache = NSCache<NSString, UIImage>()
    /// [T-icon-save-offmain] Same reason as SessionIconStore: never write the
    /// whole dictionary to UserDefaults on the main thread during the
    /// background→foreground return from the photo picker.
    private let persistQueue = DispatchQueue(label: "com.minis.folderIcons.persist", qos: .utility)

    init(defaults: UserDefaults = .standard) {
        self.defaults = defaults
        icons = (defaults.dictionary(forKey: Self.defaultsKey) as? [String: String]) ?? [:]
        imageCache.countLimit = 64
    }

    private func schedulePersist() {
        let snapshot = icons
        let store = defaults
        persistQueue.async { store.set(snapshot, forKey: Self.defaultsKey) }
    }

    func icon(for folderId: String) -> String? { icons[folderId] }

    func image(for folderId: String) -> UIImage? {
        if let cached = imageCache.object(forKey: folderId as NSString) { return cached }
        guard let uri = icons[folderId], let image = SoulIconImage.decode(uri) else { return nil }
        imageCache.setObject(image, forKey: folderId as NSString)
        return image
    }

    func setIcon(_ dataURI: String?, for folderId: String) {
        let normalized: String? = dataURI?.isEmpty == false ? dataURI : nil
        guard icons[folderId] != normalized else { return }
        imageCache.removeObject(forKey: folderId as NSString)
        if let normalized {
            icons[folderId] = normalized
        } else {
            icons.removeValue(forKey: folderId)
        }
        schedulePersist()
    }
}

/// [T-115-ask-alert] Keeps an ask_user card discoverable after the user
/// leaves its chat: an in-app banner while Minis is open elsewhere, and one
/// local notification when the app goes to the background. Tapping either
/// returns to the session that is waiting. The card itself remains the only
/// place to answer, so this never chooses or submits anything.
@MainActor
final class QuestionAlertCenter: ObservableObject {
    static let shared = QuestionAlertCenter()

    struct Pending: Identifiable, Equatable {
        let id: String          // toolUseId: stable per question card
        let sessionId: String
        let question: String
    }

    @Published private(set) var pending: Pending?
    @Published private(set) var visibleSessionId: String?
    @Published private(set) var bannerDismissed = false

    private var backgroundObserver: NSObjectProtocol?
    private var activeObserver: NSObjectProtocol?

    private init() {}

    var shouldShowBanner: Bool {
        guard let pending else { return false }
        return !bannerDismissed
            && UIApplication.shared.applicationState == .active
            && visibleSessionId != pending.sessionId
    }

    func setVisibleSession(_ id: String?) {
        guard visibleSessionId != id else { return }
        visibleSessionId = id
        if id == pending?.sessionId { bannerDismissed = true }
    }

    func clearVisibleSession(_ id: String?) {
        guard let id, visibleSessionId == id else { return }
        visibleSessionId = nil
        // Leaving the waiting chat must make the banner eligible again; the
        // flag is only there to suppress it while that chat is on screen.
        if pending?.sessionId == id { bannerDismissed = false }
    }

    func questionAppeared(sessionId: String?, toolUseId: String, question: String) {
        guard let sessionId, !sessionId.isEmpty else { return }
        if pending?.id == toolUseId { return }
        if let old = pending { removeNotification(id: old.id) }
        pending = Pending(id: toolUseId, sessionId: sessionId,
                          question: question.trimmingCharacters(in: .whitespacesAndNewlines))
        bannerDismissed = false
        installObserversIfNeeded()
        if UIApplication.shared.applicationState != .active, let pending {
            postNotification(for: pending)
        }
    }

    func questionEnded(toolUseId: String) {
        if pending?.id == toolUseId { pending = nil }
        removeNotification(id: toolUseId)
    }

    func dismissBanner() { bannerDismissed = true }

    func open(_ item: Pending) {
        removeNotification(id: item.id)
        NotificationCenter.default.post(
            name: Notification.Name("openSessionFromIntent"),
            object: nil,
            userInfo: ["sessionId": item.sessionId]
        )
        dismissBanner()
    }

    private func installObserversIfNeeded() {
        if backgroundObserver == nil {
            backgroundObserver = NotificationCenter.default.addObserver(
                forName: UIApplication.didEnterBackgroundNotification,
                object: nil, queue: .main
            ) { [weak self] _ in
                Task { @MainActor in self?.postIfNeeded() }
            }
        }
        if activeObserver == nil {
            activeObserver = NotificationCenter.default.addObserver(
                forName: UIApplication.didBecomeActiveNotification,
                object: nil, queue: .main
            ) { [weak self] _ in
                Task { @MainActor in
                    if let self, let id = self.pending?.id {
                        self.removeNotification(id: id)
                    }
                    self?.objectWillChange.send()
                }
            }
        }
    }

    private func postIfNeeded() {
        guard let pending, UIApplication.shared.applicationState != .active else { return }
        postNotification(for: pending)
    }

    private static func identifier(_ id: String) -> String { "ask-user-\(id)" }

    private func removeNotification(id: String) {
        let center = UNUserNotificationCenter.current()
        let ids = [Self.identifier(id)]
        center.removeDeliveredNotifications(withIdentifiers: ids)
        center.removePendingNotificationRequests(withIdentifiers: ids)
    }

    private func postNotification(for item: Pending) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound, .badge]) { _, _ in }
        center.setNotificationCategories([
            UNNotificationCategory(identifier: "QUESTION_WAITING", actions: [], intentIdentifiers: [])
        ])
        let content = UNMutableNotificationContent()
        content.title = AppLocalized("有问题等你回答")
        // Deliberately no question text: the notification can be seen on a
        // lock screen. The card remains the place where the question is read.
        content.body = AppLocalized("打开 Minis 查看并回答，任务正在等待。")
        content.sound = .default
        content.categoryIdentifier = "QUESTION_WAITING"
        content.userInfo = [
            "sessionId": item.sessionId,
            "questionToolUseId": item.id,
        ]
        let request = UNNotificationRequest(
            identifier: Self.identifier(item.id),
            content: content,
            trigger: nil
        )
        center.add(request) { error in
            if let error {
                AppLogger(category: "AskAlert").error("[AskAlert] notification failed: \(error.localizedDescription)")
            }
        }
    }
}

/// Top-edge reminder shown while the app is open on a different screen.
/// Visual language follows `BackgroundInterruptionBanner`: one compact row,
/// rounded 16pt, same shadow and edge padding; no modal takeover.
struct QuestionAlertBanner: View {
    @ObservedObject private var center = QuestionAlertCenter.shared

    var body: some View {
        if let item = center.pending, center.shouldShowBanner {
            Button {
                center.open(item)
            } label: {
                HStack(spacing: 11) {
                    Image(systemName: "questionmark.bubble.fill")
                        .font(.system(size: 17, weight: .semibold))
                        .foregroundStyle(.white)
                        .frame(width: 34, height: 34)
                        .background(Circle().fill(Color.accentColor))

                    VStack(alignment: .leading, spacing: 2) {
                        Text("有问题等你回答")
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.primary)
                        Text("点一下回到会话，任务正在等待")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .lineLimit(1)
                    }
                    Spacer(minLength: 8)
                    Image(systemName: "chevron.right")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.tertiary)
                }
                .padding(.horizontal, 13)
                .padding(.vertical, 10)
                .background(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .fill(Color(UIColor.secondarySystemBackground))
                        .shadow(color: .black.opacity(0.15), radius: 9, y: 4)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 16, style: .continuous)
                        .stroke(Color.primary.opacity(0.07), lineWidth: 0.5)
                )
                .padding(.horizontal, 12)
                .padding(.top, 8)
            }
            .buttonStyle(.plain)
            .transition(.move(edge: .top).combined(with: .opacity))
            .accessibilityLabel(Text("有问题等你回答，点一下回到会话"))
        }
    }
}

/// [T-turn-cost-ledger] Independent, best-effort cost ledger. It deliberately
/// does not touch the message table or `TokenUsage`: a failed write only loses
/// a cost row, never chat history. Historical messages have no rows, so the UI
/// must say "since this update" instead of pretending the total is complete.
struct CostSnapshot: Equatable {
    var lastUSD: Double? = nil
    var turnUSD: Double = 0
    var sessionUSD: Double = 0
    var sessionHasLedger = false
    /// Site's own USD→CNY rate when the pricing button read it; nil falls back
    /// to the user's existing global rate.
    var exchangeRate: Double? = nil
    /// Per-provider display currency. nil = the global setting.
    var currency: String? = nil

    var lastLabel: String? {
        guard let lastUSD else { return nil }
        return TurnCost.compact(lastUSD, rate: exchangeRate, currency: currency) + "/次"
    }
}

final class CostLedger {
    static let shared = CostLedger()

    struct Entry: Codable {
        let sessionId: String
        let messageId: String
        let modelId: String
        let instanceId: String
        let usd: Double
        let inputTokens: Int
        let outputTokens: Int
        let cacheReadTokens: Int
        let cacheCreationTokens: Int
        let at: Date
    }

    private let lock = NSLock()
    private let queue = DispatchQueue(label: "com.openminis.cost-ledger", qos: .utility)
    private var entries: [Entry] = []
    private var totals: [String: Double] = [:]

    private init() { load() }

    private var fileURL: URL? {
        guard let base = FileManager.default.urls(for: .applicationSupportDirectory,
                                                  in: .userDomainMask).first else { return nil }
        let dir = base.appendingPathComponent("OpenMinis", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir.appendingPathComponent("cost-ledger.json")
    }

    private func load() {
        guard let url = fileURL, let data = try? Data(contentsOf: url) else { return }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        guard let decoded = try? decoder.decode([Entry].self, from: data) else { return }
        entries = decoded
        for e in decoded { totals[e.sessionId, default: 0] += e.usd }
    }

    func record(sessionId: String, messageId: String, modelId: String,
                instanceId: String, usage: TokenUsage, usd: Double) {
        guard usd > 0 else { return }
        let entry = Entry(sessionId: sessionId, messageId: messageId,
                          modelId: modelId, instanceId: instanceId,
                          usd: usd, inputTokens: usage.inputTokens,
                          outputTokens: usage.outputTokens,
                          cacheReadTokens: usage.cacheReadTokens,
                          cacheCreationTokens: usage.cacheCreationTokens,
                          at: Date())
        lock.lock()
        entries.append(entry)
        if entries.count > 20_000 { entries.removeFirst(entries.count - 20_000) }
        totals[sessionId, default: 0] += usd
        let snapshot = entries
        lock.unlock()
        queue.async { [weak self] in self?.write(snapshot) }
    }

    func total(for sessionId: String) -> Double {
        lock.lock(); defer { lock.unlock() }
        return totals[sessionId] ?? 0
    }

    func hasEntries(for sessionId: String) -> Bool {
        lock.lock(); defer { lock.unlock() }
        return (totals[sessionId] ?? 0) > 0
    }

    private func write(_ snapshot: [Entry]) {
        guard let url = fileURL else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        guard let data = try? encoder.encode(snapshot) else { return }
        try? data.write(to: url, options: .atomic)
    }
}

/// [T-turn-cost-ledger] Read-only breakdown. The composer line deliberately
/// carries only the per-call figure; turn and session totals live here so the
/// input field does not grow three numbers wide.
struct CostDetailSheet: View {
    @ObservedObject var vm: AIChatViewModel
    @Environment(\.dismiss) private var dismiss

    private var sessionId: String { vm.sessionId ?? "draft-\(vm.vmInstanceId)" }
    private var sessionTotal: Double { CostLedger.shared.total(for: sessionId) }
    private var hasLedger: Bool { CostLedger.shared.hasEntries(for: sessionId) }

    var body: some View {
        NavigationView {
            Form {
                Section {
                    HStack {
                        Text("本次")
                        Spacer()
                        Text(vm.costSnapshot.lastUSD.map { TurnCost.formatted($0, currency: vm.costSnapshot.currency) } ?? "—")
                            .foregroundStyle(.secondary)
                    }
                    HStack {
                        Text("本轮（含工具调用）")
                        Spacer()
                        Text(vm.costSnapshot.turnUSD > 0
                             ? TurnCost.formatted(vm.costSnapshot.turnUSD, rate: vm.costSnapshot.exchangeRate, currency: vm.costSnapshot.currency) : "—")
                            .foregroundStyle(.secondary)
                    }
                    HStack {
                        Text("本会话累计")
                        Spacer()
                        Text(sessionTotal > 0
                             ? TurnCost.formatted(sessionTotal, rate: vm.costSnapshot.exchangeRate, currency: vm.costSnapshot.currency) : "—")
                            .foregroundStyle(.secondary)
                    }
                    HStack {
                        Text("汇率")
                        Spacer()
                        Group {
                            if let code = vm.costSnapshot.currency,
                               code != "CNY", code != "USD",
                               let rate = vm.costSnapshot.exchangeRate {
                                Text(String(format: "%.4f · 自定义 %@", rate, code))
                            } else {
                                Text(vm.costSnapshot.exchangeRate.map { String(format: "%.2f · 站点", $0) }
                                     ?? String(format: "%.2f · 全局", TurnCost.usdToCny))
                            }
                        }
                        .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("费用")
                } footer: {
                    Text(hasLedger
                         ? "金额是预估，按站点定价和你的汇率换算；最终以站点账单为准。"
                         : "这里的账本从更新后开始记录，历史消息没有中间调用记录，所以不会显示旧会话的完整总额。")
                }
            }
            .navigationTitle(Text("费用明细"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") { dismiss() }
                }
            }
        }
    }
}
    /// Bound the render target BEFORE drawing. Unlike cropping an original-size
/// square and then resizing it, this never allocates a full-resolution crop.
/// Output keeps the existing SoulIconImage PNG data-URI format; the Soul's
/// own 32pt / 96px policy is unchanged.
enum SidebarIconImage {
    static let storedPixels: CGFloat = 132

    static func encode(_ image: UIImage) -> Result<String, SoulIconImage.RejectionReason> {
        guard image.cgImage != nil, image.size.width > 0, image.size.height > 0 else {
            return .failure(.unreadable)
        }
        let side = storedPixels
        let scale = max(side / image.size.width, side / image.size.height)
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let rect = CGRect(x: (side - size.width) / 2, y: (side - size.height) / 2,
                          width: size.width, height: size.height)
        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = false
        let rendered = UIGraphicsImageRenderer(size: CGSize(width: side, height: side), format: format).image { _ in
            image.draw(in: rect)
        }
        guard let png = rendered.pngData() else { return .failure(.unreadable) }
        return .success(SoulIconImage.dataURI(fromPNG: png))
    }
}
