import Foundation
#if canImport(FoundationNetworking)
import FoundationNetworking
#endif
import Dispatch

// Test double for the parent's shared lifecycle sink, NOT a second production
// implementation. Fingerprints here are deterministic test tokens, not crypto.
final class CompactLifecycleTrace: @unchecked Sendable {
    struct Record: Sendable { let stage: String; let fields: [String: String] }
    private let lock = NSLock()
    private var storage: [Record] = []
    private var cancellationStorage: [String] = []
    private var networkSequence = 0
    func nextNetwork() -> Int {
        lock.lock(); defer { lock.unlock() }; networkSequence += 1; return networkSequence
    }
    var records: [Record] {
        lock.lock(); defer { lock.unlock() }; return storage
    }
    var origins: [String] {
        lock.lock(); defer { lock.unlock() }; return cancellationStorage
    }
    func event(_ stage: String, _ fields: [String: String] = [:]) {
        lock.lock(); defer { lock.unlock() }; storage.append(Record(stage: stage, fields: fields))
    }
    func cancel(_ origin: String) {
        lock.lock(); defer { lock.unlock() }; cancellationStorage.append(origin)
    }
    static func fingerprint(_ value: String) -> String {
        var hash: UInt64 = 14695981039346656037
        for byte in value.utf8 { hash = (hash ^ UInt64(byte)) &* 1099511628211 }
        return String(format: "%016llx", hash)
    }
}

/* ACTUAL_HELPER */

enum ActualTextParser {
/* ACTUAL_TEXT_PARSER */
}

private func expect(_ condition: @autoclosure () -> Bool, _ message: String) {
    if !condition() { fatalError("compact network fixture: " + message) }
}

private func state(_ trace: CompactLifecycleTrace, chat: Bool = false) -> CompactSummaryNetworkState {
    CompactSummaryNetworkState(trace: trace, route: chat ? "chat_completions" : "responses",
                               providerHash: "fixture-provider-hash", modelHash: "fixture-model-hash")
}

private func response(_ headers: [String: String] = [:], status: Int = 200) -> HTTPURLResponse {
    HTTPURLResponse(url: URL(string: "https://example.invalid/SECRET_URL?q=SECRET_QUERY")!,
                    statusCode: status, httpVersion: "HTTP/1.1", headerFields: headers)!
}

@discardableResult
private func verify(_ trace: CompactLifecycleTrace, finish: String? = nil) -> [String: String] {
    let records = trace.records
    let ends = records.filter { $0.stage == "network_end" }
    expect(ends.count == 1, "unique end")
    expect(records.first?.stage == "network_start", "start first")
    expect(records.last?.stage == "network_end", "end last")
    expect(records.count <= 5, "bounded record count")
    let allowedStages: Set<String> = ["network_start", "network_headers", "network_first_event", "network_cancel", "network_end"]
    let allowedKeys: Set<String> = ["network", "purpose", "route", "provider_hash", "model_hash", "request_hash", "http", "events", "text_events", "text_chars", "reasoning_events", "usage_events", "unknown_events", "malformed_events", "bytes", "finish", "error_domain_hash", "error_code", "elapsed_ms"]
    for record in records {
        expect(allowedStages.contains(record.stage), "fixed stage")
        expect(Set(record.fields.keys).isSubset(of: allowedKeys), "field allowlist")
        for value in record.fields.values {
            expect(!value.contains("SECRET_") && !value.contains("example.invalid"), "no raw canary")
        }
    }
    for stage in allowedStages { expect(records.filter { $0.stage == stage }.count <= 1, "each stage once") }
    let last = ends[0].fields
    if let finish { expect(last["finish"] == finish, "finite expected finish: " + finish) }
    for key in ["events", "text_events", "text_chars", "reasoning_events", "usage_events", "unknown_events", "malformed_events", "bytes", "elapsed_ms"] {
        expect((Int(last[key] ?? "") ?? -1) >= 0, "nonnegative numeric field: " + key)
    }
    let cancelled = last["finish"] == "cancel"
    expect(trace.origins == (cancelled ? ["network_cancel"] : []), "cancel origin is transport, not user")
    expect(records.filter { $0.stage == "network_cancel" }.count == (cancelled ? 1 : 0), "cancel record once")
    return last
}

private func testEmptyAndHeaders() {
    let t = CompactLifecycleTrace(), s = state(CompactLifecycleTrace())
    // No headers/bytes when request-build or connection fails.
    let initial = state(t)
    initial.end(error: NSError(domain: "SECRET_CONNECT_DOMAIN", code: 73,
                               userInfo: [NSLocalizedDescriptionKey: "SECRET_ERROR_BODY"]))
    initial.end(cancelled: true)
    let e = verify(t, finish: "error")
    expect(e["request_hash"] == "none" && e["http"] == "none", "pre-headers fields")
    expect(e["error_code"] == "73", "numeric original error code")
    expect(e["error_domain_hash"] == CompactLifecycleTrace.fingerprint("SECRET_CONNECT_DOMAIN"), "hashed domain")
    expect(e["events"] == "0", "no event before connection")
    s.end() // unrelated fixture state; no global/shared counters
    let missing = CompactLifecycleTrace(), missingState = state(missing)
    missingState.headers(response(["Authorization": "SECRET_AUTH", "x-request-id-extra": "SECRET_NOT_ID"]))
    missingState.end()
    expect(verify(missing, finish: "eof")["request_hash"] == "none", "no wildcard or auth ID")
    let priority = CompactLifecycleTrace(), priorityState = state(priority)
    priorityState.headers(response(["X-Request-ID": "SECRET_FIRST_ID", "request-id": "SECRET_SECOND_ID"]))
    priorityState.headers(response(["x-request-id": "SECRET_LATE_ID"]))
    priorityState.end()
    expect(verify(priority, finish: "eof")["request_hash"] == CompactLifecycleTrace.fingerprint("SECRET_FIRST_ID"), "exact header priority, first headers only")
    for name in ["request-id", "openai-request-id", "x-ms-request-id"] {
        let trace = CompactLifecycleTrace(), network = state(CompactLifecycleTrace())
        let tested = state(trace)
        tested.headers(response([name: "SECRET_FALLBACK_ID"]))
        tested.end()
        expect(verify(trace)["request_hash"] == CompactLifecycleTrace.fingerprint("SECRET_FALLBACK_ID"), "header fallback")
        network.end()
    }
}

private func testResponsesCounts() {
    let trace = CompactLifecycleTrace(), network = state(CompactLifecycleTrace())
    let s = state(trace)
    s.headers(response(["x-request-id": "SECRET_REQUEST_ID"]))
    let lines = [": keepalive", "data:α"]
    for line in lines { s.line(line) }
    let textEvent: [String: Any] = ["type": "response.output_text.delta", "delta": "SECRET_TEXT_你好"]
    let text = ActualTextParser.parseResponsesAPITextDelta(textEvent)
    expect(text == "SECRET_TEXT_你好", "actual text parser")
    s.event(textEvent, text: text, usage: false, useChat: false)
    let reasoning: [String: Any] = ["type": "response.reasoning_summary_text.delta", "delta": "SECRET_REASONING"]
    expect(ActualTextParser.parseResponsesAPITextDelta(reasoning) == nil, "reasoning is not summary")
    s.event(reasoning, text: nil, usage: false, useChat: false)
    s.event(["type": "SECRET_UNKNOWN_TYPE", "body": "SECRET_UNKNOWN_BODY"], text: nil, usage: false, useChat: false)
    s.malformed()
    s.event(["type": "response.completed"], text: nil, usage: true, useChat: false)
    s.done()
    s.end(); s.end(cancelled: true)
    let e = verify(trace, finish: "completed")
    expect(e["events"] == "6" && e["text_events"] == "1", "SSE/data and text totals")
    expect(e["text_chars"] == String(text!.count), "character count")
    expect(e["reasoning_events"] == "1" && e["usage_events"] == "1", "reasoning and usage counts")
    expect(e["unknown_events"] == "1" && e["malformed_events"] == "1", "unknown/malformed not lost")
    expect(e["bytes"] == String(lines.reduce(0) { $0 + $1.utf8.count }), "decoded line byte definition")
    network.end()
}

private func testExplicitFinishes() {
    for (reason, expected) in [("stop", "stop"), ("length", "length"), ("content_filter", "refusal"),
                               ("tool_calls", "tool_calls"), ("function_call", "tool_calls"), ("SECRET_FINISH", "other")] {
        let t = CompactLifecycleTrace()
        let s = state(t, chat: true)
        s.event(["choices": [["delta": [:], "finish_reason": reason]]], text: nil, usage: false, useChat: true)
        s.done(); s.end()
        expect(verify(t, finish: expected)["events"] == "2", "chat explicit then DONE")
    }
    for (reason, expected) in [("max_output_tokens", "length"), ("content_filter", "refusal"), ("SECRET_INCOMPLETE", "incomplete")] {
        let t = CompactLifecycleTrace()
        let s = state(t)
        s.event(["type": "response.incomplete", "response": ["incomplete_details": ["reason": reason]]], text: nil, usage: false, useChat: false)
        s.done(); s.end()
        verify(t, finish: expected)
    }
    for type in ["response.refusal.delta", "response.refusal.done", "response.failed", "error"] {
        let t = CompactLifecycleTrace()
        let s = state(t)
        s.event(["type": type, "delta": "SECRET_REFUSAL"], text: nil, usage: false, useChat: false)
        s.end()
        verify(t, finish: type.contains("refusal") ? "refusal" : "error")
    }
    let t = CompactLifecycleTrace()
    let s = state(t, chat: true)
    s.event(["choices": [["delta": ["reasoning_content": "SECRET_REASONING"]]]], text: nil, usage: false, useChat: true)
    s.event(["choices": [["delta": ["refusal": "SECRET_REFUSAL"]]]], text: nil, usage: false, useChat: true)
    s.done(); s.end()
    let e = verify(t, finish: "refusal")
    expect(e["text_events"] == "0" && e["text_chars"] == "0" && e["reasoning_events"] == "1", "reasoning-only cannot become summary")
    let eof = CompactLifecycleTrace()
    state(eof).end()
    verify(eof, finish: "eof")
    let done = CompactLifecycleTrace()
    let d = state(done)
    d.done(); d.end()
    verify(done, finish: "done")
}

private func testErrorsAndCancellation() {
    let t = CompactLifecycleTrace()
    let s = state(t)
    s.headers(response(["request-id": "SECRET_ERROR_ID"], status: 403))
    s.line("SECRET_NON_2XX_BODY")
    s.end(error: NSError(domain: "SECRET_BODY_READ_DOMAIN", code: -1005,
                         userInfo: [NSLocalizedDescriptionKey: "SECRET_BODY_READ_ERROR"]))
    let e = verify(t, finish: "error")
    expect(e["http"] == "403" && e["bytes"] == String("SECRET_NON_2XX_BODY".utf8.count), "non-2xx read fault retains headers/bytes")
    expect(e["events"] == "0" && e["error_code"] == "-1005", "non-2xx is not SSE")
    let service = CompactLifecycleTrace()
    let serviceState = state(service)
    serviceState.event(["error": ["message": "SECRET_SERVICE_ERROR"]], text: nil, usage: false, useChat: false)
    serviceState.end(error: NSError(domain: "SECRET_SERVICE_DOMAIN", code: 500))
    expect(verify(service, finish: "error")["events"] == "1", "error JSON counted before throw")
    for mode in 0..<3 {
        let trace = CompactLifecycleTrace()
        let network = state(trace)
        switch mode {
        case 0: network.end(cancelled: true)
        case 1: network.end(error: URLError(.cancelled))
        default: network.end(error: CancellationError())
        }
        network.end(); network.end(cancelled: true)
        network.line("SECRET_LATE_LINE"); network.done(); network.malformed()
        network.headers(response(["request-id": "SECRET_LATE_REQUEST"]))
        let cancelled = verify(trace, finish: "cancel")
        expect(cancelled["events"] == "0" && cancelled["bytes"] == "0", "terminal ignores late callbacks")
    }
    let normal = CompactLifecycleTrace()
    let normalState = state(normal)
    normalState.end(); normalState.end(cancelled: true)
    verify(normal, finish: "eof") // .finished must not become cancellation
}

private func testBoundAndRaces() {
    let many = CompactLifecycleTrace()
    let manyState = state(many)
    for _ in 0..<20_000 {
        manyState.event(["type": "SECRET_UNKNOWN_TYPE"], text: nil, usage: false, useChat: false)
    }
    manyState.end()
    let manyEnd = verify(many, finish: "eof")
    expect(manyEnd["unknown_events"] == "20000" && manyEnd["events"] == "20000", "aggregate without per-chunk logs")
    expect(many.records.count == 3, "start/first/end only")
    for _ in 0..<40 {
        let t = CompactLifecycleTrace()
        let s = state(t)
        DispatchQueue.concurrentPerform(iterations: 80) { index in
            switch index % 5 {
            case 0: s.line("SECRET_CONCURRENT_LINE")
            case 1: s.done()
            case 2: s.end(cancelled: true)
            case 3: s.end(error: NSError(domain: "SECRET_RACE_DOMAIN", code: 91))
            default: s.end()
            }
        }
        verify(t)
    }
}

@main
struct CompactNetworkFixtureMain {
    static func main() {
        testEmptyAndHeaders()
        testResponsesCounts()
        testExplicitFinishes()
        testErrorsAndCancellation()
        testBoundAndRaces()
        print("PASS: actual CompactSummaryNetworkState + actual Responses text parser; headers, counters, finite finishes, redaction, errors, cancellations, bounded logs, races")
    }
}
