
// Compiled with the actual Catalog.swift by test_minisight_action_import.py.
// This is NOT a claim that Linux can execute Apple's ImageIO or UIKit.
private enum TestFailure: Error { case failed(String) }
private var assertions = 0
private func expect(_ value: @autoclosure () throws -> Bool, _ name: String) throws {
    assertions += 1
    if try !value() { throw TestFailure.failed(name) }
}
private func rejects(_ name: String, _ body: () throws -> Void) throws {
    var rejected = false
    do { try body() } catch { rejected = true }
    try expect(rejected, name)
}
extension MiniSightAssetCatalog {
    static func testRollback(_ json: Data) throws {
        try replaceCurrent(Data([0x7f]), json: json, keepBackup: true)
    }
    static func testCommit(_ root: URL, id: String, operation: MiniSightAssetOperation) throws {
        _ = try commitAction(root, id: id, title: "cancelled", operation: operation)
    }
}
private func runDefaultBootstrapTests() throws {
    let fm = FileManager.default
    let png = MiniSightPetFile.url
    let meta = MiniSightPetFile.directory.appendingPathComponent("pet.json")
    try fm.createDirectory(at: MiniSightPetFile.directory, withIntermediateDirectories: true)
    let fallback = try MiniSightDefaultAssets.stageFallback()
    try expect(MiniSightDefaultAssets.validated(fallback), "actual bundled original bytes hash/ImageIO verified")
    try expect(try MiniSightAssetCatalog.ensureDefaultIfAbsent(), "empty selection seeds default")
    let originalImage = try Data(contentsOf: png), originalMeta = try Data(contentsOf: meta)
    try expect(try !MiniSightAssetCatalog.ensureDefaultIfAbsent(), "existing default never reseeded")
    try expect(try Data(contentsOf: png) == originalImage && Data(contentsOf: meta) == originalMeta, "default second pass exact bytes preserved")
    try Data("bad user image".utf8).write(to: png)
    try Data("{corrupt-user-metadata".utf8).write(to: meta)
    try expect(try !MiniSightAssetCatalog.ensureDefaultIfAbsent(), "corrupt user pair is not replaced")
    try expect(try Data(contentsOf: png) == Data("bad user image".utf8) && Data(contentsOf: meta) == Data("{corrupt-user-metadata".utf8), "bad selection left intact for render-only fallback")
    try fm.removeItem(at: png); try fm.removeItem(at: meta)
    try fm.createSymbolicLink(atPath: png.path, withDestinationPath: "does-not-exist.png")
    try expect(try !MiniSightAssetCatalog.ensureDefaultIfAbsent(), "dangling user path never overwritten")
    try fm.removeItem(at: png)
}

private func runImportTests() throws {
    try runDefaultBootstrapTests()
    typealias C = MiniSightAssetCatalog
    typealias A = MiniSightActionImport
    let fm = FileManager.default
    let work = URL(fileURLWithPath: CommandLine.arguments[1])
    let fixture = URL(fileURLWithPath: CommandLine.arguments[2])
    let png = try Data(contentsOf: fixture.appendingPathComponent("source.png"))
    let gif = try Data(contentsOf: fixture.appendingPathComponent("idle.gif"))
    let originalJSON = try Data(contentsOf: fixture.appendingPathComponent("actions.json"))
    let originalManifest = try A.parse(originalJSON)
    try fm.createDirectory(at: MiniSightPetFile.directory, withIntermediateDirectories: true)
    try png.write(to: MiniSightPetFile.url)
    var notifications = 0
    let observer = NotificationCenter.default.addObserver(forName: C.didChange, object: nil, queue: .main) { _ in notifications += 1 }
    defer { NotificationCenter.default.removeObserver(observer) }
    func current() throws -> Data { try Data(contentsOf: MiniSightPetFile.url) }
    func pack(_ item: C.Item) -> URL { MiniSightPetFile.directory.appendingPathComponent(item.metadata!.actionPack!).deletingLastPathComponent() }
    func catalogImage(_ item: C.Item) throws -> Data { try Data(contentsOf: C.dir.appendingPathComponent(item.name)) }
    func files() throws -> [String] { try fm.contentsOfDirectory(atPath: C.dir.path).sorted() }
    func testDirectory(_ change: (inout A.Manifest) -> Void) throws -> URL {
        let root = work.appendingPathComponent("source-" + UUID().uuidString, isDirectory: true)
        try fm.createDirectory(at: root, withIntermediateDirectories: false)
        try png.write(to: root.appendingPathComponent("source.png"))
        try gif.write(to: root.appendingPathComponent("idle.gif"))
        var manifest = originalManifest; change(&manifest)
        try JSONEncoder().encode(manifest).write(to: root.appendingPathComponent("actions.json"))
        return root
    }
    func rejectManifest(_ name: String, _ change: (inout A.Manifest) -> Void) throws {
        let root = try testDirectory(change)
        let before = try files(), image = try current()
        try rejects(name) { _ = try C.importActionDirectory(root, title: name, operation: MiniSightAssetOperation()) }
        try expect(try files() == before && current() == image, name + " no commit")
    }

    // Pre-existing metadata-free original must survive adding ANY asset.
    let still = try C.importData(png, kind: .singleImage, title: "existing static", operation: MiniSightAssetOperation())
    let staticBytes = try catalogImage(still)
    try expect(still.metadata?.actionPack == nil, "legacy metadata remains optional")
    try expect(try current() == png, "static addition does not activate")
    var oldObject = try JSONSerialization.jsonObject(with: JSONEncoder().encode(still.metadata!)) as! [String: Any]
    oldObject.removeValue(forKey: "actionPack")
    let oldMeta = try JSONDecoder().decode(C.Metadata.self, from: JSONSerialization.data(withJSONObject: oldObject))
    try expect(oldMeta.valid && oldMeta.actionPack == nil, "old JSON decodes")
    let op = MiniSightAssetOperation()
    let animated = try C.importData(gif, kind: .auto, title: "GIF", operation: op)
    try expect(!op.cancel(), "late cancel cannot claim committed import")
    try expect(try current() == png && catalogImage(still) == staticBytes, "GIF does not overwrite current/static original")
    try expect(try A.read(pack(animated), "resources/original.gif", limit: C.maxInputBytes) == gif, "GIF original exact bytes")
    let manifest = try A.validate(pack(animated), operation: MiniSightAssetOperation())
    try expect(manifest.clips.count == 1 && manifest.clips[0].role == "idle", "single GIF explicit idle")
    try expect(manifest.clips[0].frames.map(\.duration) == [0.04, 0.17], "unclamped GIF frame delays preserved")
    var shortGIF = gif; shortGIF[23] = 1; shortGIF[24] = 0 // first GCE is explicitly 10ms
    try rejects("out-of-policy GIF delay rejected, never browser-clamped") {
        _ = try C.importData(shortGIF, kind: .auto, title: "short delay", operation: MiniSightAssetOperation())
    }
    try expect(animated.metadata!.layoutVersion == 1 && animated.metadata!.variants == 1 && animated.metadata!.sourceKind == "singleImage", "whole poster, not inferred atlas")
    let normalPoster = try A.read(pack(animated), "poster.png", limit: C.maxStoredBytes)
    let animatedBytes = try catalogImage(animated)
    let animatedJSON = try Data(contentsOf: C.dir.appendingPathComponent(animated.metadata!.id + ".json"))
    _ = try C.snapshot(); _ = try C.snapshot()
    try expect(try catalogImage(animated) == animatedBytes, "768:936-shaped action poster not migrated/flipped")
    try expect(try Data(contentsOf: C.dir.appendingPathComponent(animated.metadata!.id + ".json")) == animatedJSON, "poster metadata never auto-sliced")
    try expect(try A.read(pack(animated), "poster.png", limit: C.maxStoredBytes) == normalPoster, "immutable normal poster retained")
    try expect(normalPoster != animatedBytes, "only legacy copy uses legacy inversion")
    var badMeta = animated.metadata!
    for path in ["/actions.json", "actionpacks/../actions.json", "actionpacks/" + UUID().uuidString + "/actions.json", "https://example.com/actions.json"] {
        badMeta.actionPack = path
        try expect(!badMeta.valid, "metadata rejects illegal/mismatched reference")
    }
    badMeta = animated.metadata!; badMeta.layoutVersion = 3
    try expect(!badMeta.valid, "action metadata cannot become atlas")

    let beforeCancel = try files()
    let cancelled = MiniSightAssetOperation(); cancelled.cancel()
    try rejects("cancel before import") { _ = try C.importData(gif, kind: .auto, title: "cancel", operation: cancelled) }
    try expect(try files() == beforeCancel && current() == png, "cancel untouched")
    let staged = try A.temporary(); defer { try? fm.removeItem(at: staged) }
    let stagedOp = MiniSightAssetOperation()
    let stagedID = try A.stageDirectory(fixture, to: staged, operation: stagedOp)
    try expect(try A.read(staged, "resources/source.png", limit: C.maxInputBytes) == png, "all relative resources staged")
    stagedOp.cancel()
    try rejects("cancel after complete copy before commit") { try C.testCommit(staged, id: stagedID, operation: stagedOp) }
    try expect(try files() == beforeCancel && current() == png, "post-copy cancel does not switch")
    let bundle = try C.importActionDirectory(fixture, title: "JSON package", operation: MiniSightAssetOperation())
    try expect(try A.read(pack(bundle), "original-actions.json", limit: A.manifestLimit) == originalJSON, "source manifest immutable")
    try expect(try A.read(pack(bundle), "resources/source.png", limit: C.maxInputBytes) == png, "PNG source immutable")
    let saved = try A.validate(pack(bundle), operation: MiniSightAssetOperation())
    try expect(saved.id == bundle.metadata!.id && saved.id != originalManifest.id && saved.clips.contains(where: { $0.role == "music" }), "UUID normalized; explicit music supported")
    try expect(saved.clips.contains(where: { $0.role == "idleAlt" && $0.category == "play" }), "daily category survives native Catalog parse")
    try expect(try current() == png, "folder addition never switches")

    try rejectManifest("unknown category") { $0.clips[1].category = "walking" }
    try rejectManifest("unknown role") { $0.clips[0].role = "running" }
    try rejectManifest("idle required") { $0.clips.removeFirst() }
    try rejectManifest("duplicate clip ID") { $0.clips[1].id = $0.clips[0].id }
    try rejectManifest("unsafe ID") { $0.clips[0].id = "_idle" }
    try rejectManifest("index beyond decoded source") { $0.clips[0].frames[0].index = 2 }
    try rejectManifest("index 600") { $0.clips[0].frames[0].index = 600 }
    try rejectManifest("short duration") { $0.clips[0].frames[0].duration = 0.01 }
    try rejectManifest("long duration") { $0.clips[0].frames[0].duration = 11 }
    try rejectManifest("clip duration budget") { $0.clips[0].frames = Array(repeating: A.Frame(file: "idle.gif", index: 0, duration: 10), count: 13) }
    try rejectManifest("601 frames") { $0.clips[0].frames = Array(repeating: A.Frame(file: "idle.gif", index: 0, duration: 0.02), count: 601) }
    try rejectManifest("65 clips") { m in m.clips = (0..<65).map { A.Clip(id: "c\($0)", role: "idle", frames: [A.Frame(file: "idle.gif", index: 0, duration: 0.1)]) } }
    try rejectManifest("6001 total frames") { m in m.clips = (0..<11).map { A.Clip(id: "c\($0)", role: "idle", frames: Array(repeating: A.Frame(file: "idle.gif", index: 0, duration: 0.02), count: 600)) } }
    try rejectManifest("rect outside source") { $0.clips[0].frames[0].rect = [0.9, 0, 0.2, 1] }
    try rejectManifest("zero rect") { $0.clips[0].frames[0].rect = [0, 0, 0, 1] }
    try rejectManifest("inconsistent logical aspect") { $0.clips[0].frames[0].rect = [0, 0, 0.5, 1] }
    for path in ["../source.png", "/tmp/source.png", "https://example.com/a.png", "x\\source.png", "a/./b.png", "a//b.png", "%2e%2e/source.png", "missing.png"] {
        try rejectManifest("relative traversal/missing \(path)") { $0.clips[1].frames[0].file = path }
    }
    let malformed = Data("{\"schema\":1,\"schema\":1,\"id\":\"BE27E983-68DC-4D38-9755-13BBA99862A9\",\"clips\":[]}".utf8)
    try rejects("duplicate JSON keys") { _ = try A.parse(malformed) }
    try rejects("manifest byte budget") { _ = try A.parse(Data(repeating: 32, count: A.manifestLimit + 1)) }
    try rejects("nested JSON budget") { _ = try A.parse(Data((String(repeating: "[", count: 20) + "0" + String(repeating: "]", count: 20)).utf8)) }
    let corrupt = try testDirectory { _ in }
    try Data("exists but not an image".utf8).write(to: corrupt.appendingPathComponent("source.png"))
    try rejects("existing corrupt source is NOT importable") { _ = try C.importActionDirectory(corrupt, title: "corrupt", operation: MiniSightAssetOperation()) }
    try Data(contentsOf: fixture.appendingPathComponent("oversize.png")).write(to: corrupt.appendingPathComponent("source.png"))
    try rejects("oversize decoded dimensions") { _ = try C.importActionDirectory(corrupt, title: "large", operation: MiniSightAssetOperation()) }
    let linked = try testDirectory { $0.clips[1].frames[0].file = "linked/source.png" }
    try fm.createSymbolicLink(at: linked.appendingPathComponent("linked"), withDestinationURL: fixture)
    try rejects("intermediate symlink cannot escape") { _ = try C.importActionDirectory(linked, title: "link", operation: MiniSightAssetOperation()) }
    try fm.removeItem(at: linked.appendingPathComponent("source.png"))
    try fm.createSymbolicLink(at: linked.appendingPathComponent("source.png"), withDestinationURL: fixture.appendingPathComponent("source.png"))
    try rejects("final symlink cannot escape") { _ = try A.read(linked, "source.png", limit: C.maxInputBytes) }
    let bounded = linked.appendingPathComponent("bytes")
    try Data(repeating: 1, count: 33).write(to: bounded)
    try rejects("bounded descriptor read") { _ = try A.read(linked, "bytes", limit: 32) }
    try expect(try catalogImage(still) == staticBytes && current() == png, "all failures preserve old originals")

    // Current/backup metadata are the ONLY activation markers.
    try C.activate(animated)
    try expect(try current() == animatedBytes, "activation copies legacy poster")
    try expect(try C.snapshot().currentID == animated.id, "catalog selection matches activated UUID")
    let backupImage = MiniSightPetFile.directory.appendingPathComponent("pet.backup.png")
    let backupJSON = MiniSightPetFile.directory.appendingPathComponent("pet.backup.json")
    try expect(try Data(contentsOf: backupImage) == png && !fm.fileExists(atPath: backupJSON.path), "metadata-free old bytes backed up exactly")
    try C.restorePrevious()
    try expect(try current() == png && !fm.fileExists(atPath: C.metadataURL.path), "old metadata-free restore exact")
    try C.delete(animated)
    try expect(fm.fileExists(atPath: pack(animated).path), "backup action reference protects deleted catalog pack")
    try C.restorePrevious()
    try expect(try current() == animatedBytes, "restore works after deleting action catalog entry")
    try C.activate(bundle)
    let goodCurrent = try current(), goodJSON = try Data(contentsOf: C.metadataURL)
    let goodBackup = try Data(contentsOf: backupImage), goodBackupJSON = try Data(contentsOf: backupJSON)
    try rejects("post-write verification failure rolls back") { try C.testRollback(goodJSON) }
    try expect(try current() == goodCurrent && Data(contentsOf: C.metadataURL) == goodJSON, "failed transaction restores current pair")
    try expect(try Data(contentsOf: backupImage) == goodBackup && Data(contentsOf: backupJSON) == goodBackupJSON, "failed transaction restores previous backup pair")
    let missingSource = pack(animated).appendingPathComponent("resources/original.gif")
    try fm.removeItem(at: missingSource)
    try rejects("missing backup source fails before switch") { try C.restorePrevious() }
    try expect(try current() == goodCurrent && Data(contentsOf: C.metadataURL) == goodJSON, "failed restore retains current")
    try gif.write(to: missingSource) // This test-only damage is repaired before lifecycle checks.
    try C.delete(bundle)
    try expect(fm.fileExists(atPath: pack(bundle).path), "active pack retained after catalog deletion")
    try C.activate(still)
    try expect(!fm.fileExists(atPath: pack(animated).path), "unreferenced deleted pack collected")
    try expect(fm.fileExists(atPath: pack(bundle).path), "new backup pack retained")
    try C.activate(still)
    try expect(!fm.fileExists(atPath: pack(bundle).path), "pack collected when last current/backup reference disappears")
    try expect(try catalogImage(still) == staticBytes, "original static never covered by new action")
    // Old unknown sidecar/image files stay byte-for-byte unchanged, not repaired by a generic import.
    let oldFile = C.dir.appendingPathComponent("legacy-unknown.png")
    let oldSidecar = C.dir.appendingPathComponent("legacy-unknown.json")
    try png.write(to: oldFile); try Data("old format".utf8).write(to: oldSidecar)
    _ = try C.snapshot()
    try expect(try Data(contentsOf: oldFile) == png && Data(contentsOf: oldSidecar) == Data("old format".utf8), "old unknown files retained")
    RunLoop.current.run(until: Date().addingTimeInterval(0.1))
    try expect(notifications >= 10, "successful import/activation/restore/delete publish changes")
    print("PASS native ImageIO + real Catalog: \(assertions) assertions")
}
do { try runImportTests() }
catch { fputs("FAIL native action importer: \(error)\n", stderr); exit(1) }
