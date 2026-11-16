// Shadow only the persistence dependency. Literal production store methods
// execute unchanged; tests never touch runner/device preferences.
final class UserDefaults {
    static let standard = UserDefaults()
    private var values = [String: Any]()
    func set(_ value: Any?, forKey key: String) { values[key] = value }
    func string(forKey key: String) -> String? { values[key] as? String }
    func removeObject(forKey key: String) { values.removeValue(forKey: key) }
}
var fixtureNotifications = 0
var fixtureSnapshots = [[String: Any]]()
var fixtureEvents = [String]()
var fixtureAfterRaw: (() -> Void)?
func MSDiagEvent(_ module: String, _ action: String, _ result: String, _ fields: [String: Any]) {
    fixtureEvents.append(action + ":" + result)
}
enum MiniSightSettingKey {
    static let shown = "SYNTHETIC.shown"
    static let shownRevision = "SYNTHETIC.revision"
}
enum MiniSightConfig { static let all = [MiniSightSettingKey.shown] }
final class SyntheticStore {
    var loaded = true
    var readingShown = false
    var shown = false { didSet { publishShown() } }
    var publishGeneration = 0
    var lastError: String?
    var saveState = ""
    // Only irrelevant configuration values/notification transport are mocked.
    // publishShown, reloadShownFromFile and persistAll below are literal actual
    // production methods; the shown writer/reader is real ObjC I/O.
    func raw(_ key: String) -> Any {
        let value = MiniSightPetFile.loadShown()
        fixtureAfterRaw?()
        fixtureAfterRaw = nil
        return value
    }
    func publish(_ key: String) {
        publishGeneration += 1
        deliver(generation: publishGeneration, revision: "SYNTHETIC", attempt: 0)
    }
    func deliver(generation: Int, revision: String, attempt: Int) {
        fixtureSnapshots.append([MiniSightSettingKey.shown: MiniSightPetFile.loadShown()])
        fixtureNotifications += 1
    }
