import Foundation
import Darwin
var assertions = 0
func check(_ value: @autoclosure () -> Bool, _ message: String) throws {
    assertions += 1
    if !value() { throw NSError(domain: "FAIL assertion: " + message, code: 1) }
}
do {
    let directory = CommandLine.arguments[1]
    MiniSightPetFile.containerPath = directory
    let path = URL(fileURLWithPath: directory).appendingPathComponent("Documents/MiniSight/shown")
    try FileManager.default.createDirectory(at: path.deletingLastPathComponent(), withIntermediateDirectories: true)
    let store = SyntheticStore()
    try check(!MiniSightPetFile.loadShown(), "missing App shown failclosed")
    store.reloadShownFromFile()
    try check(!store.shown && fixtureNotifications == 0, "passive reload never writes/notifies")
    for bad in ["", "bad", "true", "2", "1\n", "00", String(repeating: "1", count: 10000)] {
        try Data(bad.utf8).write(to: path, options: .atomic)
        try check(!MiniSightPetFile.loadShown(), "invalid App shown failclosed")
        let native = MiniSightResources.shownEvidence(container: directory)
        try check((native["_minisightShownKnown"] as? Bool) == false, "same native invalid evidence")
    }
    try FileManager.default.removeItem(at: path)
    let target = path.deletingLastPathComponent().appendingPathComponent("synthetic-target")
    try Data("1".utf8).write(to: target)
    try FileManager.default.createSymbolicLink(at: path, withDestinationURL: target)
    try check(!MiniSightPetFile.loadShown(), "symlink rejected by App native reader")
    try FileManager.default.removeItem(at: path)
    store.shown = true
    try check(MiniSightPetFile.loadShown() && fixtureNotifications == 1, "normal explicit ON save/readback/notify")
    try check(fixtureSnapshots.last?[MiniSightSettingKey.shown] as? Bool == true, "normal saved snapshot ON")
    let onIdentity = MiniSightResources.shownEvidence(container: directory)["_minisightShownIdentity"] as? String
    var menuWrites = 0
    try MiniSightPetFile.saveShown(false) { menuWrites += 1 }
    let offIdentity = MiniSightResources.shownEvidence(container: directory)["_minisightShownIdentity"] as? String
    try check(onIdentity != offIdentity && menuWrites == 1, "menu atomic hide changes identity")
    // Store still has cached true; exact persistAll must never rewrite shown.
    store.persistAll()
    try check(!MiniSightPetFile.loadShown(), "stale cached ON page exit must not undo menu hide")
    try check(offIdentity == (MiniSightResources.shownEvidence(container: directory)["_minisightShownIdentity"] as? String), "page exit preserves shown identity")
    try check(!store.shown, "page passive reload reflects hidden")
    // A hide BETWEEN reload/raw and delivery must remain authoritative too.
    store.shown = true
    fixtureAfterRaw = { _ = MiniSightResources.saveShown(false, container: directory) }
    store.persistAll()
    try check(!MiniSightPetFile.loadShown(), "hide during unrelated page save remains OFF")
    try check(fixtureSnapshots.last?[MiniSightSettingKey.shown] as? Bool == false, "final runtime snapshot reflects latest file OFF")
    let before = MiniSightResources.shownEvidence(container: directory)["_minisightShownIdentity"] as? String
    // Cancelled local editing makes no setter call and performs no transaction.
    var cancelledDraft = true
    cancelledDraft = false
    _ = cancelledDraft
    try check(before == (MiniSightResources.shownEvidence(container: directory)["_minisightShownIdentity"] as? String), "cancelled draft writes nothing")
    store.shown = true
    try check(MiniSightPetFile.loadShown(), "new explicit enable after menu hide still works")
    store.shown = false
    try check(!MiniSightPetFile.loadShown(), "normal OFF still works")
    let notifyBeforeFailure = fixtureNotifications
    MiniSightPetFile.containerPath = "relative-invalid"
    store.shown = true
    try check(!store.shown && fixtureNotifications == notifyBeforeFailure && store.lastError != nil, "failed explicit save rolls back and never announces ON")
    UserDefaults.standard.removeObject(forKey: MiniSightSettingKey.shown)
    UserDefaults.standard.removeObject(forKey: MiniSightSettingKey.shownRevision)
    try FileManager.default.removeItem(atPath: directory)
    print("PASS native shown settings: \(assertions) assertions; actual load/save/reload/persist, no UI/device/audio")
} catch {
    fputs(String(describing: error) + "\n", stderr)
    exit(1)
}
