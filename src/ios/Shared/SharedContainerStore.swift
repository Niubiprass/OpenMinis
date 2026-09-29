import Foundation

/// Reads and writes PendingShare data to the App Group shared container.
/// Compiled into both the main app target and the Share Extension target.
enum SharedContainerStore {
    static let appGroupID = "group.com.openminis.app"

    /// The App Group container URL.
    ///
    /// On normally-provisioned builds this is the shared container created for
    /// `group.com.openminis.app`. On builds where the App Group is **not**
    /// registered — most notably TrollStore-signed IPA, which ships no
    /// provisioning profile to create the shared container — the system
    /// returns `nil` from `containerURL(forSecurityApplicationGroupIdentifier:)`.
    /// In that case we transparently fall back to a private subdirectory of
    /// the app's own sandbox, so callers never have to deal with a `nil`
    /// container (and a force-unwrap crash on launch).
    static var containerDirectory: URL {
        if let container = FileManager.default
            .containerURL(forSecurityApplicationGroupIdentifier: appGroupID) {
            return container
        }
        let fallback = FileManager.default
            .urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent("MinisAppGroupFallback", isDirectory: true)
        try? FileManager.default.createDirectory(at: fallback, withIntermediateDirectories: true)
        return fallback
    }

    private static let pendingShareKey = "pendingShare"

    static var sharedDefaults: UserDefaults? {
        // TrollStore-signed builds have no registered App Group, so `suiteName:`
        // returns nil. Fall back to the app's own standard defaults so the
        // pending-share handshake still works for the "Open in Minis" path,
        // which runs entirely inside the main app's sandbox (no cross-process
        // sharing required — unlike the Share Extension).
        UserDefaults(suiteName: appGroupID) ?? UserDefaults.standard
    }

    /// Directory for transferring attachment files into the app.
    ///
    /// Layered on top of `containerDirectory`: when the App Group exists this is
    /// the shared container (so a supported Share Extension could write here),
    /// and when it doesn't we transparently fall back to a private subdirectory
    /// of the app's own sandbox. The "Open in Minis" document-import path runs
    /// inside the main app itself, so this fallback keeps it fully functional on
    /// TrollStore where App Groups are unavailable.
    static var sharedFileDirectory: URL? {
        containerDirectory
            .appendingPathComponent("ShareExtension", isDirectory: true)
    }

    // MARK: - Write (called by Share Extension)

    static func savePendingShare(_ share: PendingShare) {
        guard let defaults = sharedDefaults else { return }
        let encoder = JSONEncoder()
        encoder.dateEncodingStrategy = .iso8601
        if let data = try? encoder.encode(share) {
            defaults.set(data, forKey: pendingShareKey)
            defaults.synchronize()
        }
    }

    // MARK: - Read & Consume (called by main app)

    static func loadPendingShare() -> PendingShare? {
        guard let defaults = sharedDefaults,
              let data = defaults.data(forKey: pendingShareKey) else { return nil }
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .iso8601
        return try? decoder.decode(PendingShare.self, from: data)
    }

    static func clearPendingShare() {
        sharedDefaults?.removeObject(forKey: pendingShareKey)
        sharedDefaults?.synchronize()
    }

    /// Remove all files from the shared transfer directory.
    static func cleanSharedFiles() {
        guard let dir = sharedFileDirectory else { return }
        let fm = FileManager.default
        if let files = try? fm.contentsOfDirectory(at: dir, includingPropertiesForKeys: nil) {
            for file in files {
                try? fm.removeItem(at: file)
            }
        }
    }
}
