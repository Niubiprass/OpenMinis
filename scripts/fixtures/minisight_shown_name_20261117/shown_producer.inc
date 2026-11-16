    static func loadShown() -> Bool {
        let evidence = MiniSightResources.shownEvidence(container: containerPath)
        return (evidence["_minisightShownKnown"] as? Bool) == true &&
            (evidence["_minisightShown"] as? Bool) == true
    }
    static func saveShown(_ on: Bool, onWrite: () -> Void) throws {
        // The same bounded native transaction as the companion; missing/bad
        // files never imply ON. Defaults/notification follow verified disk only.
        guard MiniSightResources.saveShown(on, container: containerPath) else {
            throw MiniSightAIConfigFile.Failure.verificationFailed
        }
        onWrite()
    }
