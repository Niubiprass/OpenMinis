// Appended to the byte-preserved Engine/Name/Assets sources in one main.swift.
// No alternate prepare/stop state machine. All transitions are production methods.
import Foundation
import Dispatch
import Darwin
import SherpaOnnxC

enum CancelHooks {
    private static let lock = NSLock()
    private static var stage = ""
    private static var expected: UUID?
    private static var armed = false
    private static let reached = DispatchSemaphore(value: 0)
    private static let release = DispatchSemaphore(value: 0)
    static func arm(_ point: String, token: UUID?) {
        lock.lock(); defer { lock.unlock() }
        precondition(!armed); stage = point; expected = token; armed = true
    }
    static func at(_ point: String, token: UUID?) {
        lock.lock()
        let matches = armed && stage == point && (expected == nil || expected == token)
        if matches { armed = false }
        lock.unlock()
        if matches {
            reached.signal()
            precondition(release.wait(timeout: .now() + 15) == .success, "barrier release timeout: \(point)")
        }
    }
    static func wait() {
        precondition(reached.wait(timeout: .now() + 15) == .success, "barrier not reached: \(stage)")
    }
    static func resume() { release.signal() }
}
@_cdecl("CancelFixtureConstructorBarrier")
func cancelFixtureConstructorBarrier() { CancelHooks.at("constructor", token: nil) }

extension MiniSightWakeEngine {
    func cancelFixtureSeed() {
        worker.sync {
            cachedFiles = MiniSightWakeAssets.Files(
                encoder: URL(fileURLWithPath: "/fixture/encoder.onnx"),
                decoder: URL(fileURLWithPath: "/fixture/decoder.onnx"),
                joiner: URL(fileURLWithPath: "/fixture/joiner.onnx"),
                tokens: URL(fileURLWithPath: "/fixture/tokens.txt"),
                vocabulary: Set(["n", "ǐ", "h", "ǎo"]))
        }
    }
    func cancelFixtureDrain() {
        worker.sync {} // precise FIFO completion of prepareLatest and queued cleanup
        DispatchQueue.main.sync {} // precise FIFO completion of queued deliveries
    }
    func cancelFixtureSnapshot() -> (UUID?, UUID?, UUID?, Bool, Bool) {
        worker.sync {
            state { (current, ready, builtToken, spotter != nil, stream != nil) }
        }
    }
}
final class CallbackLog: @unchecked Sendable {
    private let lock = NSLock()
    private var success = [UUID: Int]()
    private var failure = [UUID: Int]()
    private var hit = 0
    func complete(_ token: UUID, result: Result<MiniSightWakeName.Prepared, Error>) {
        lock.lock(); defer { lock.unlock() }
        switch result {
        case let .success(value):
            precondition(value.name == "你好" && value.tokens == ["n", "ǐ", "h", "ǎo"])
            success[token, default: 0] += 1
        case .failure: failure[token, default: 0] += 1
        }
    }
    func unexpectedHit() { lock.lock(); hit += 1; lock.unlock() }
    func assertCounts(_ token: UUID, successes: Int, failures: Int = 0) {
        lock.lock(); defer { lock.unlock() }
        precondition(success[token, default: 0] == successes, "wrong success generation: \(token)")
        precondition(failure[token, default: 0] == failures, "wrong failure generation: \(token)")
        precondition(hit == 0, "unexpected hit/failure callback without audio")
    }
}
func submit(_ engine: MiniSightWakeEngine, _ token: UUID, _ log: CallbackLog) {
    engine.prepare(name: "你好", pronunciation: "ni3 hao3", token: token,
                   onHit: { _ in log.unexpectedHit() },
                   onFailure: { _, _ in log.unexpectedHit() },
                   completion: { log.complete(token, result: $0) })
}
func assertDestroyed(_ kind: Int32, _ index: Int32, _ count: Int32) {
    precondition(CancelMockDestroyed(kind, index) == count, "late handle not released exactly once / live new handle destroyed")
}
func assertClean() {
    precondition(CancelMockInvalidDestroy() == 0, "double/wrong-kind/parent-first destroy")
    for kind in [Int32(0), Int32(1)] {
        for index in 0..<CancelMockCount(kind) { assertDestroyed(kind, index, 1) }
    }
    precondition(CancelMockAcceptCount() == 0, "unexpected audio input")
}
func runStopped(_ point: String, streamFailure: Bool = false) {
    CancelMockReset()
    let engine = MiniSightWakeEngine(); engine.cancelFixtureSeed()
    let old = UUID(); let log = CallbackLog()
    CancelMockSetMode(streamFailure ? 1 : 0)
    CancelHooks.arm(point, token: point == "workerEntry" || point == "constructor" ? nil : old)
    submit(engine, old, log); CancelHooks.wait()
    engine.stop(); engine.stop() // repeated cancellation must be idempotent
    CancelHooks.resume(); engine.cancelFixtureDrain()
    let snapshot = engine.cancelFixtureSnapshot()
    precondition(snapshot.0 == nil && snapshot.1 == nil && snapshot.2 == nil && !snapshot.3 && !snapshot.4,
                 "stopped generation became ready or retained late native handles: \(point)")
    log.assertCounts(old, successes: 0)
    precondition(CancelMockCount(0) == (point == "workerEntry" ? 0 : 1))
    precondition(CancelMockCount(1) == (point == "workerEntry" || streamFailure ? 0 : 1))
    engine.stop(); engine.cancelFixtureDrain(); assertClean()
    print("PASS stop \(point)\(streamFailure ? " stream-failure" : ""): no stale ready/callback, each late handle destroyed once")
}
func runReplacement(_ point: String, cancelOld: Bool, oldFailure: Bool = false) {
    CancelMockReset()
    let engine = MiniSightWakeEngine(); engine.cancelFixtureSeed()
    let old = UUID(), fresh = UUID(); let log = CallbackLog()
    CancelMockSetMode(oldFailure ? 1 : 0)
    CancelHooks.arm(point, token: point == "workerEntry" || point == "constructor" ? nil : old)
    submit(engine, old, log); CancelHooks.wait()
    if cancelOld { engine.stop(); engine.stop() }
    if oldFailure { CancelMockSetMode(0) }
    submit(engine, fresh, log)
    CancelHooks.resume(); engine.cancelFixtureDrain()
    let snapshot = engine.cancelFixtureSnapshot()
    precondition(snapshot.0 == fresh && snapshot.1 == fresh && snapshot.2 == fresh && snapshot.3 && snapshot.4,
                 "late old cleanup damaged new usable generation: \(point)")
    log.assertCounts(old, successes: 0); log.assertCounts(fresh, successes: 1)
    let models: Int32 = point == "workerEntry" ? 1 : 2
    let streams: Int32 = oldFailure || point == "workerEntry" ? 1 : 2
    precondition(CancelMockCount(0) == models && CancelMockCount(1) == streams)
    if models == 2 { assertDestroyed(0, 0, 1) }
    if streams == 2 { assertDestroyed(1, 0, 1) }
    assertDestroyed(0, models - 1, 0); assertDestroyed(1, streams - 1, 0)
    precondition(CancelMockInvalidDestroy() == 0)
    engine.stop(); engine.stop(); engine.cancelFixtureDrain(); assertClean()
    print("PASS replacement \(point) cancelOld=\(cancelOld): old suppressed, new callback/ready/live handles intact")
}
func runDeinit() {
    CancelMockReset()
    var engine: MiniSightWakeEngine? = MiniSightWakeEngine(); engine!.cancelFixtureSeed()
    let token = UUID(); let log = CallbackLog()
    submit(engine!, token, log); engine!.cancelFixtureDrain(); log.assertCounts(token, successes: 1)
    engine = nil; assertClean()
    print("PASS deinit releases accepted handles exactly once")
}
func runAllCancellationCases() {
    precondition(!Thread.isMainThread)
    for point in ["workerEntry", "beforeMake", "constructor", "afterMake", "beforeDelivery", "mainDelivery"] {
        runStopped(point)
        runReplacement(point, cancelOld: true)
        runReplacement(point, cancelOld: false)
    }
    runStopped("constructor", streamFailure: true)
    runStopped("mainDelivery", streamFailure: true)
    runReplacement("mainDelivery", cancelOld: true, oldFailure: true)
    runReplacement("mainDelivery", cancelOld: false, oldFailure: true)
    runDeinit(); CancelMockReset()
    print("PASS native actual Engine worker/stop/delivery: 23 barrier cases; no microphone or audio input")
}
DispatchQueue.global(qos: .userInitiated).async {
    runAllCancellationCases()
    exit(0)
}
dispatchMain()
