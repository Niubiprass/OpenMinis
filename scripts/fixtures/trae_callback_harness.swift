import Foundation

func check(_ label: String, _ condition: Bool, _ detail: String = "") {
    if condition { print("  ok   \(label)") }
    else { print("  FAIL \(label) \(detail)"); failures += 1 }
}
var failures = 0

// ---- correlation ----------------------------------------------------------
check("missing trace is nil", try! TraeCallbackRequest.traceID([:]) == nil)
check("loginTraceID accepted", try! TraeCallbackRequest.traceID(["loginTraceID": "t1"]) == "t1")
check("snake_case accepted", try! TraeCallbackRequest.traceID(["login_trace_id": "t1"]) == "t1")
check("both same accepted",
      try! TraeCallbackRequest.traceID(["loginTraceID": "t1", "login_trace_id": "t1"]) == "t1")
var conflicted = false
do { _ = try TraeCallbackRequest.traceID(["loginTraceID": "a", "login_trace_id": "b"]) }
catch { conflicted = true }
check("conflicting aliases rejected", conflicted)

// ---- request parsing ------------------------------------------------------
func head(_ target: String, method: String = "GET", origin: String? = nil,
          host: String = "127.0.0.1:5555", extra: [String] = []) -> String {
    var lines = ["\(method) \(target) HTTP/1.1", "Host: \(host)"]
    if let origin { lines.append("Origin: \(origin)") }
    lines.append(contentsOf: extra)
    return lines.joined(separator: "\r\n")
}
func code(_ raw: String) -> String {
    raw.addingPercentEncoding(withAllowedCharacters: CharacterSet.alphanumerics) ?? raw
}
let goodTarget = "/authorize?authCodeInfo=" + code(#"{"AuthCode":"c1"}"#) + "&loginTraceID=t1"
let port: UInt16 = 5555

func action(_ raw: String) -> TraeCallbackRequest.Action? {
    try? TraeCallbackRequest.parse(raw, port: port, expectedTrace: "t1")
}
if case .callback(let p)? = action(head(goodTarget)) {
    check("valid callback parsed", p["loginTraceID"] == "t1")
} else { check("valid callback parsed", false) }

if case .preflight? = action(head("/authorize", method: "OPTIONS")) {
    check("preflight answered without payload", true)
} else { check("preflight answered without payload", false) }

check("preflight still needs correlation-free path", action(head("/authorize?x=1", method: "OPTIONS")) != nil)

// A page redirect from www.trae.cn is allowed; any other origin is not.
check("trae origin allowed", action(head(goodTarget, origin: "https://www.trae.cn")) != nil)
check("foreign origin rejected", action(head(goodTarget, origin: "https://evil.example")) == nil)
check("rebinding host rejected", action(head(goodTarget, host: "attacker.example:5555")) == nil)
check("wrong port rejected", action(head(goodTarget, host: "127.0.0.1:9999")) == nil)

// Correlation is mandatory: no trace, wrong trace, duplicate trace.
check("no trace rejected", action(head("/authorize?authCodeInfo=" + code(#"{"AuthCode":"c1"}"#))) == nil)
check("wrong trace rejected", action(head("/authorize?authCodeInfo=" + code(#"{"AuthCode":"c1"}"#) + "&loginTraceID=t2")) == nil)
check("duplicate field rejected",
      action(head("/authorize?authCodeInfo=" + code(#"{"AuthCode":"c1"}"#) + "&loginTraceID=t1&loginTraceID=t1")) == nil)

// Path, method, encoding.
check("wrong path rejected", action(head("/callback?loginTraceID=t1")) == nil)
check("POST rejected", action(head(goodTarget, method: "POST")) == nil)
check("scheme-less target rejected", action(head("authorize?loginTraceID=t1")) == nil)
check("bad header rejected", action(head(goodTarget, extra: ["NoColon"])) == nil)
check("content-length body rejected", action(head(goodTarget, extra: ["Content-Length: 12"])) == nil)

// Payload shapes.
check("unparseable authCodeInfo rejected",
      action(head("/authorize?authCodeInfo=notjson&loginTraceID=t1")) == nil)
check("empty auth code rejected",
      action(head("/authorize?authCodeInfo=" + code(#"{"AuthCode":""}"#) + "&loginTraceID=t1")) == nil)
check("foreign loginHost rejected",
      action(head(goodTarget + "&loginHost=" + code("https://www.trae.ai"))) == nil)
check("domestic loginHost allowed",
      action(head(goodTarget + "&loginHost=" + code("https://api.trae.cn"))) != nil)
check("error callback without code allowed",
      action(head("/authorize?error=access_denied&loginTraceID=t1")) != nil)

// ---- one-shot state ------------------------------------------------------
var state = TraeCallbackState()
check("cannot start without trace", state.begin() == false)
state.expectTrace("t1")
check("starts once", state.begin())
check("second start refused", state.begin() == false)
check("late trace ignored", { state.expectTrace("t2"); return state.expectedTrace == "t1" }())
check("first answer accepted", state.finish(.success(["loginTraceID": "t1"])))
check("second answer refused", state.finish(.success(["loginTraceID": "t1"])) == false)
state.stop()
check("stop is terminal", state.begin() == false && state.finish(.success([:])) == false)
if case .failure? = state.result { check("stop reports cancellation", true) }
else { check("stop reports cancellation", false) }

var answeredEarly = TraeCallbackState()
answeredEarly.expectTrace("t1"); _ = answeredEarly.begin()
_ = answeredEarly.finish(.success(["a": "b"]))
let early = answeredEarly.result
if case .success(let value)? = early { check("answer delivered before waiter", value["a"] == "b") }
else { check("answer delivered before waiter", false) }

var cancelled = TraeCallbackState()
cancelled.expectTrace("t1"); _ = cancelled.begin()
cancelled.stop()
if case .failure? = cancelled.result { check("cancelled flow never reports success", true) }
else { check("cancelled flow never reports success", false) }

var reused = TraeCallbackState()
reused.stop()
check("stopped listener refuses a new trace", { reused.expectTrace("t2"); return reused.expectedTrace == nil }())

if failures == 0 { print("trae-callback-ok") } else { print("trae-callback-failures=\(failures)") }
exit(failures == 0 ? 0 : 1)
