import Foundation

struct TestFailure: Error { let message: String }
var checks = 0
func check(_ value: @autoclosure () -> Bool, _ message: String) throws {
    checks += 1
    if !value() { throw TestFailure(message: message) }
}
func checkPolicy() throws {
    var c = MiniSightWakePolicy.Context(enabled: true, foreground: true, unlocked: true,
        shown: true, petStyle: true, appRenderer: true, hasAsset: true, permissionGranted: true,
        audioAvailable: true, recordingOrCall: false, chatVisible: false, now: 10, cooldownUntil: 9)
    c.armed = true
    try check(MiniSightWakePolicy.decision(c) == .listen, "ordinary authorized path")
    let base = c
    c.enabled = false; try check(MiniSightWakePolicy.decision(c) == .disabled, "OFF")
    c = base; c.foreground = false; c.companionRequired = true; c.companionReady = true
    try check(MiniSightWakePolicy.decision(c) == .listen, "Home/other app with companion stays active")
    c.companionReady = false; try check(MiniSightWakePolicy.decision(c) == .companion, "missing companion fails closed")
    c = base; c.armed = false; try check(MiniSightWakePolicy.decision(c) == .inactive, "unarmed cannot open mic")
    c = base; c.unlocked = false; try check(MiniSightWakePolicy.decision(c) == .locked, "lock")
    c = base; c.shown = false; try check(MiniSightWakePolicy.decision(c) == .hidden, "hide")
    c = base; c.petStyle = false; try check(MiniSightWakePolicy.decision(c) == .hidden, "pill style")
    c = base; c.appRenderer = false; c.companionRequired = true; c.companionReady = true
    try check(MiniSightWakePolicy.decision(c) == .listen, "plugin renderer uses companion")
    c = base; c.hasAsset = false; try check(MiniSightWakePolicy.decision(c) == .missingAsset, "no asset")
    c = base; c.permissionGranted = false; try check(MiniSightWakePolicy.decision(c) == .permission, "permission denied")
    c = base; c.audioAvailable = false; try check(MiniSightWakePolicy.decision(c) == .busy, "other audio owner")
    c = base; c.recordingOrCall = true; try check(MiniSightWakePolicy.decision(c) == .busy, "call/ReplayKit/drag")
    c = base; c.chatVisible = true; try check(MiniSightWakePolicy.decision(c) == .busy, "chat priority")
    for now in [8.9, Double.nan, Double.infinity] {
        c = base; c.now = now; try check(MiniSightWakePolicy.decision(c) == .cooldown, "cooldown/invalid clock")
    }
    c = base; c.cooldownUntil = .infinity; try check(MiniSightWakePolicy.decision(c) == .cooldown, "invalid deadline")
    let token = UUID(), old = UUID()
    try check(MiniSightWakePolicy.validHit(active: token, incoming: token, isListening: true, decision: .listen), "current hit")
    try check(!MiniSightWakePolicy.validHit(active: token, incoming: old, isListening: true, decision: .listen), "old hit")
    try check(!MiniSightWakePolicy.validHit(active: nil, incoming: token, isListening: true, decision: .listen), "cancelled hit")
    try check(!MiniSightWakePolicy.validHit(active: token, incoming: token, isListening: false, decision: .listen), "no physical mic")
    try check(!MiniSightWakePolicy.validHit(active: token, incoming: token, isListening: true, decision: .busy), "busy hit")
    for mask in 0..<32 {
        let foreground = mask & 1 != 0, unlocked = mask & 2 != 0, shown = mask & 4 != 0
        let enabled = mask & 8 != 0, cancelled = mask & 16 != 0
        try check(MiniSightWakePolicy.permitsContinuation(foreground: foreground, unlocked: unlocked,
            shown: shown, enabled: enabled, cancelled: cancelled) == (mask == 14 || mask == 15), "continuation gates \(mask)")
    }
}
final class AssetResultBox: @unchecked Sendable {
    private let lock = NSLock()
    private var stored: Result<MiniSightWakeAssets.Files, Error>?
    func put(_ value: Result<MiniSightWakeAssets.Files, Error>) { lock.lock(); stored = value; lock.unlock() }
    func get() -> Result<MiniSightWakeAssets.Files, Error> { lock.lock(); defer { lock.unlock() }; return stored! }
}
func loadOnWorker(_ root: URL) -> Result<MiniSightWakeAssets.Files, Error> {
    let box = AssetResultBox(), sem = DispatchSemaphore(value: 0)
    DispatchQueue.global(qos: .utility).async { box.put(Result { try MiniSightWakeAssets.load(at: root) }); sem.signal() }
    precondition(sem.wait(timeout: .now()+10) == .success)
    return box.get()
}
func checkAssets(_ path: String) throws {
    let root = URL(fileURLWithPath: path, isDirectory: true)
    let files = try loadOnWorker(root).get()
    try check(files.vocabulary.count == 227, "real bundled vocabulary")
    let prepared = try MiniSightWakeName.prepare(name: "小鱼", pronunciation: "xiao3 yu2", vocabulary: files.vocabulary)
    try check(prepared.definition == "x iǎo y ú @minisight", "bundled model name definition")
    let temporary = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.copyItem(at: root, to: temporary)
    defer { try? FileManager.default.removeItem(at: temporary) }
    var bytes = try Data(contentsOf: temporary.appendingPathComponent("encoder.onnx"))
    bytes[bytes.startIndex] ^= 1
    try bytes.write(to: temporary.appendingPathComponent("encoder.onnx"))
    switch loadOnWorker(temporary) {
    case .success: throw TestFailure(message: "corrupt model accepted")
    case .failure: checks += 1
    }
    bytes[bytes.startIndex] ^= 1
    try bytes.write(to: temporary.appendingPathComponent("encoder.onnx"))
    _ = try loadOnWorker(temporary).get() // Restore clean model before testing missing tokens.
    try FileManager.default.removeItem(at: temporary.appendingPathComponent("tokens.txt"))
    switch loadOnWorker(temporary) {
    case .success: throw TestFailure(message: "missing tokens accepted")
    case .failure: checks += 1
    }
}
do {
    guard CommandLine.arguments.count == 2 else { throw TestFailure(message: "model directory missing") }
    try checkPolicy(); try checkAssets(CommandLine.arguments[1])
    print("PASS production Foundation wake policy/assets: \(checks) checks; no model inference or microphone")
} catch { fputs("FAIL native wake: \(error)\n", stderr); exit(1) }
