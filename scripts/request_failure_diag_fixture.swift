// Appended AFTER the actual helper extracted from OpenAIProvider.swift.
// Synthetic strings only. No URLSession, credentials, filesystem or network.
var checks = 0
func check(_ condition: @autoclosure () -> Bool, _ name: String) {
    precondition(condition(), "FAIL: " + name)
    checks += 1
    print("PASS " + name)
}
let synthetic = "sk-SYNTHETIC-NOT-A-CREDENTIAL-private-echo"
let url = URL(string: "https://example.invalid/private/\(synthetic)?key=\(synthetic)")!
let base: [String: Any] = ["model": synthetic, "messages": [["role": "user", "content": synthetic]],
    "stream": true, "stream_options": ["include_usage": true], "max_completion_tokens": 128,
    "reasoning_effort": "max"]
func get(_ body: [String: Any] = base, responses: Bool = false, bytes: Int? = 987,
         stage: OpenAIRequestFailureDiagnostic.Stage = .http, headers: [String: String] = [:],
         errorBody: String? = nil, error: Error? = nil) -> (String, [String: Any]) {
    let response = HTTPURLResponse(url: url, statusCode: 400, httpVersion: nil, headerFields: headers)!
    let text = OpenAIRequestFailureDiagnostic.line(body: body, isResponsesAPI: responses,
        providerId: synthetic, url: url, encodedBytes: bytes, stage: stage,
        response: response, responseBody: errorBody, error: error,
        gate: OpenAIRequestFailureDiagnostic.Limiter())!
    let object = try! JSONSerialization.jsonObject(with: Data(text.utf8)) as! [String: Any]
    return (text, object)
}
func counts(_ body: [String: Any], responses: Bool = false) -> [String: Int] {
    get(body, responses: responses).1["counts"] as! [String: Int]
}
let first = get()
check(!first.0.contains(synthetic) && !first.0.contains("example.invalid"), "no model/provider/URL secret echo")
check(first.0.utf8.count <= 4096, "bounded log line")
check(first.1["bodyBytes"] as? Int == 987 && first.1["jsonEncoded"] as? Bool == true, "exact serialized byte count")
check(first.1["max_completion_tokens"] as? Int == 128, "numeric output limit")
check(first.1["effort"] as? String == "max" && first.1["stream"] as? Bool == true && first.1["includeUsage"] as? Bool == true, "actual safe parameter values")
var changed = base
changed[synthetic] = synthetic
changed["reasoning_effort"] = synthetic
changed["max_tokens"] = synthetic
let arbitrary = get(changed)
check(!arbitrary.0.contains(synthetic) && arbitrary.1["unknownFieldCount"] as? Int == 1, "unknown names and values withheld")
check(get([:]).1["modelEmpty"] as? Bool == true, "missing model diagnosed")
check(get(["model": ""]).1["modelEmpty"] as? Bool == true, "empty model diagnosed")
check(get(bytes: nil, stage: .encoding).1["jsonEncoded"] as? Bool == false, "encoding failure is not encoded")
let safeID = "z8r_01m8c2xbms7nc49mqb6m46n4zb"
let errorBody = "{\"request_id\":\"\(safeID)\",\"error\":{\"code\":\"invalid_request\",\"type\":\"invalid_request\",\"message\":\"\(synthetic)\"}}"
let err = get(errorBody: errorBody)
check(err.1["requestID"] == nil && err.1["requestIDPresent"] as? Bool == true && err.1["errorCode"] as? String == "invalid_request" && !err.0.contains(synthetic) && !err.0.contains(safeID), "error code allowed but even ordinary request IDs never echoed")
check(!get(headers: ["x-request-id": synthetic]).0.contains(synthetic), "credential-looking header withheld")
for echo in ["0123456789abcdef0123456789abcdef", "req_ExamplePromptText", UUID().uuidString] {
    let privacy = get(headers: ["x-request-id": echo])
    check(!privacy.0.contains(echo) && privacy.1["requestIDHash"] is String, "request ID shaped secrets also withheld")
}
check(get(errorBody: String(repeating: synthetic, count: 3000)).1["errorBodyCapped"] as? Bool == true, "large error body not parsed or copied whole")
check(!get(errorBody: "not-json " + synthetic).0.contains(synthetic), "non-JSON error text never echoed")
let privateError = NSError(domain: synthetic, code: 1, userInfo: [NSLocalizedDescriptionKey: synthetic])
check(!get(stage: .transport, error: privateError).0.contains(synthetic), "error descriptions and foreign domains withheld")
let fields = get(["model": false, "messages": NSNull(), "max_tokens": true]).1
check((fields["fields"] as? [String: String])?["model"] == "bool" && fields["max_tokens"] as? String == "other", "Boolean and numeric types distinguished")
let tool: [String: Any] = ["role": "assistant", "content": NSNull(), "tool_calls": [["id": "c1", "type": "function", "function": ["name": synthetic, "arguments": synthetic]]]]
let result: [String: Any] = ["role": "tool", "tool_call_id": "c1", "content": synthetic]
let paired = counts(["messages": [tool, result, ["role": "user", "content": "next"]]])
check(paired["toolCalls"] == 1 && paired["toolResults"] == 1 && paired["orphanResults"] == 0 && paired["missingResults"] == 0, "valid tool adjacency")
let missing = counts(["messages": [tool, ["role": "user", "content": "intervened"], result]])
check(missing["missingResults"] == 1 && missing["orphanResults"] == 1, "interrupted tool adjacency detected")
let duplicate = counts(["messages": [tool, result, tool, result]])
check(duplicate["duplicateCalls"] == 1, "duplicate call IDs detected")
check(counts(["messages": [result]])["orphanResults"] == 1, "orphan result detected")
let invalid = counts(["messages": [["role": "assistant", "tool_calls": [["id": String(repeating: "x", count: 257)]]]]])
check(invalid["invalidCallIDs"] == 1, "oversize IDs bounded")
let responseItems: [[String: Any]] = [["type": "function_call", "call_id": "r1", "name": synthetic, "arguments": synthetic], ["type": "reasoning"], ["type": "function_call_output", "call_id": "r1", "output": synthetic]]
let responseCounts = counts(["input": responseItems], responses: true)
check(responseCounts["toolCalls"] == 1 && responseCounts["toolResults"] == 1 && responseCounts["missingResults"] == 0, "Responses call/result pairing")
let parts: [[String: Any]] = [["type": "text", "text": synthetic], ["type": "image_url", "image_url": ["url": synthetic]], ["type": "input_audio", "input_audio": ["data": synthetic]]]
let media = get(["messages": [["role": "user", "content": parts]]])
check((media.1["counts"] as? [String: Int])?["images"] == 1 && !media.0.contains(synthetic), "multimodal counts without media data")
let huge = counts(["messages": Array(repeating: ["role": "user", "content": String(repeating: "x", count: 9000)], count: 300)])
check(huge["messages"] == 300 && huge["scanned"] == 256 && huge["capped"] == 1 && huge["textSamplesCapped"] == 256 && huge["textBytesSampled"] == 65536, "bounded message and total text scans")
let manyCalls = counts(["messages": Array(repeating: ["role": "assistant", "tool_calls": Array(repeating: ["id": "dup"], count: 80)], count: 300)])
check(manyCalls["toolCalls"] == 256 && (manyCalls["capped"] ?? 0) > 0, "total call ID scan budget")
let badDefs = counts(["messages": [], "tools": Array(repeating: ["type": "function"], count: 150)])
check(badDefs["tools"] == 150 && badDefs["toolsScanned"] == 128 && badDefs["invalidToolDefinitions"] == 128, "tool definition count and cap")
let gate = OpenAIRequestFailureDiagnostic.Limiter()
check((0..<8).allSatisfy { gate.take(now: Double($0)) == 0 }, "eight events allowed")
check(gate.take(now: 10) == nil && gate.take(now: 11) == nil, "rate cap suppresses extra events")
check(gate.take(now: 61) == 2, "next window reports suppressed count")
let cancelGate = OpenAIRequestFailureDiagnostic.Limiter()
let cancelled = OpenAIRequestFailureDiagnostic.line(body: base, isResponsesAPI: false, providerId: nil,
    url: url, encodedBytes: nil, stage: .transport, error: CancellationError(), now: 0, gate: cancelGate)
check(cancelled == nil && cancelGate.take(now: 0) == 0, "task cancellation is silent and consumes no budget")
let urlCancelled = OpenAIRequestFailureDiagnostic.line(body: base, isResponsesAPI: false, providerId: nil,
    url: url, encodedBytes: nil, stage: .httpRead, error: NSError(domain: NSURLErrorDomain, code: NSURLErrorCancelled), gate: cancelGate)
check(urlCancelled == nil, "URL cancellation is silent")
check(get().1["modelHash"] as? String == first.1["modelHash"] as? String, "same process identity correlates")
let concurrentGate = OpenAIRequestFailureDiagnostic.Limiter()
let countLock = NSLock()
nonisolated(unsafe) var admitted = 0
DispatchQueue.concurrentPerform(iterations: 100) { _ in
    if concurrentGate.take(now: 1) != nil { countLock.lock(); admitted += 1; countLock.unlock() }
}
check(admitted == 8, "concurrent rate limit remains exact")
print("NATIVE_CHECKS \(checks)")
