import Foundation
import os.log

private let logger = AppLogger(category: "ModelGroupRouter")

/// Resolves which ModelEntry to use from a ModelGroup based on the routing strategy.
@MainActor
enum ModelGroupRouter {

    /// Resolve the initial model entry for a session from a group.
    /// - Parameters:
    ///   - group: The model group to resolve from.
    ///   - sessionId: Used for deterministic load-balance hashing.
    ///   - store: The provider config store to look up entries.
    /// - Returns: The resolved ModelEntry id, or nil if no enabled member is available.
    static func resolve(group: ModelGroup, sessionId: String, store: ProviderConfigStore) -> String? {
        let available = availableEntryIds(group: group, store: store)
        logger.info("🔀ROUTE resolve group=\(group.name) strategy=\(group.strategy.rawValue) members=\(group.memberEntryIds) available=\(available)")
        guard !available.isEmpty else {
            logger.warning("🔀ROUTE resolve: no available entries")
            return nil
        }

        switch group.strategy {
        case .fallback:
            logger.info("🔀ROUTE resolve fallback → \(available.first!)")
            return available.first

        case .loadBalance:
            let index = abs(sessionId.hashValue) % available.count
            logger.info("🔀ROUTE resolve loadBalance index=\(index) → \(available[index])")
            return available[index]
        }
    }

    /// Get the next fallback entry after the current one failed.
    /// Cycles forward from the current entry, wrapping around to entries before it,
    /// so that one full round of all available entries is attempted per reasoning turn.
    /// Returns nil if no more fallbacks are available.
    static func nextFallback(
        group: ModelGroup,
        currentEntryId: String,
        store: ProviderConfigStore
    ) -> String? {
        nextFallback(
            currentEntryId: currentEntryId,
            available: availableEntryIds(group: group, store: store)
        )
    }

    /// [T-perf-router-ring-once] Ring walk against an ALREADY computed available
    /// list. Callers that loop over the ring (compaction fallback candidates)
    /// used to call the overload above once per step, which re-filtered every
    /// group member — and each filter calls `store.entry(for:)` — so the walk
    /// was O(members²) lookups on the main actor. Compute `availableEntryIds`
    /// once, then walk this.
    static func nextFallback(
        currentEntryId: String,
        available: [String]
    ) -> String? {
        guard let currentIdx = available.firstIndex(of: currentEntryId) else {
            return available.first
        }
        let remaining = available[(currentIdx + 1)...]
        if let next = remaining.first { return next }
        let before = available[..<currentIdx]
        if let wrapped = before.first { return wrapped }
        return nil
    }

    /// Returns group members that were filtered out (unavailable) with reasons.
    static func unavailableMembers(
        group: ModelGroup, store: ProviderConfigStore
    ) -> [(model: String, instance: String, reason: String)] {
        var result: [(model: String, instance: String, reason: String)] = []
        for entryId in group.memberEntryIds {
            guard let entry = store.entry(for: entryId) else { continue }
            guard let inst = store.instance(for: entry.providerInstanceId) else { continue }
            let label = inst.label
            if entry.isHidden {
                result.append((model: entry.model.displayName, instance: label, reason: AppLocalized("Hidden")))
            } else if !inst.isEnabled {
                result.append((model: entry.model.displayName, instance: label, reason: AppLocalized("Disabled")))
            } else if !inst.hasAnyCredential {
                result.append((model: entry.model.displayName, instance: label, reason: AppLocalized("Not logged in")))
            }
        }
        return result
    }

    // MARK: - Private

    /// Filter group members to those that are enabled, whose provider instance
    /// is enabled, AND whose instance has a usable credential. The credential
    /// gate is what stops a no-token OAuth instance — common after iCloud
    /// sync brings the instance metadata across without bringing its
    /// per-device OAuth tokens — from winning the fallback race and producing
    /// a 403 `OAuth authentication is currently not allowed for this
    /// organization`. The factory would still build a provider for it, but
    /// the request would fail immediately and waste a fallback slot.
    ///
    /// [T-perf-router-ring-once] Internal (not private) so ring-walking callers
    /// can pay for this filter once instead of once per step; see
    /// `nextFallback(currentEntryId:available:)`. Per-entry logs are debug: with
    /// a large group this ran hundreds of times per turn and the info-level
    /// spam alone filled the on-disk log.
    static func availableEntryIds(group: ModelGroup, store: ProviderConfigStore) -> [String] {
        group.memberEntryIds.filter { entryId in
            guard let entry = store.entry(for: entryId) else {
                logger.debug("🔀ROUTE filter: entry \(entryId) not found in store")
                return false
            }
            guard !entry.isHidden else {
                logger.debug("🔀ROUTE filter: entry \(entryId) is hidden")
                return false
            }
            guard let instance = store.instance(for: entry.providerInstanceId) else {
                logger.debug("🔀ROUTE filter: instance \(entry.providerInstanceId) not found for entry \(entryId)")
                return false
            }
            guard instance.isEnabled else {
                logger.debug("🔀ROUTE filter: instance \(instance.label) (\(instance.id)) disabled for entry \(entryId)")
                return false
            }
            guard instance.hasAnyCredential else {
                logger.debug("🔀ROUTE filter: instance \(instance.label) (\(instance.id)) has no credential for entry \(entryId)")
                return false
            }
            return true
        }
    }
}
