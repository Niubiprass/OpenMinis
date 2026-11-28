import Foundation
import CryptoKit
import Dispatch

final class TraceTestLog: @unchecked Sendable {
    static let shared = TraceTestLog()
    private let lock = NSLock()
    private var lines: [String] = []
    func append(_ value: String) { lock.lock(); lines.append(value); lock.unlock() }
    func take() -> [[String:String]] {
        lock.lock(); let result = lines; lines.removeAll(); lock.unlock()
        return result.compactMap { line in
            guard let data=line.data(using:.utf8) else { return nil }
            return (try? JSONSerialization.jsonObject(with:data)) as? [String:String]
        }
    }
}
struct AppLogger: Sendable {
    init(category: String) {}
    func info(_ line: String) { TraceTestLog.shared.append(line) }
}
/* ACTUAL_LIFECYCLE */
/* ACTUAL_NETWORK_HELPER */
struct ProviderTurnLimitRejection: Error {}
enum LLMError: Error {
    case cancelled, networkError(Error), rateLimited, invalidAPIKey
    case transientError(message: String, statusCode: Int?), providerError(message: String)
}
enum ActualSplitPolicy {
/* ACTUAL_SPLIT_POLICY */
}
@main struct TraceFixture {
    static func check(_ condition: @autoclosure () -> Bool, _ label: String) {
        precondition(condition(), label)
    }
    static func rows(_ stage: String, _ values: [[String:String]]) -> [[String:String]] {
        values.filter { $0["event"] == stage }
    }
    static func main() {
        let trace=CompactLifecycleTrace(session:"SECRET_SESSION")
        trace.event("begin",["trigger":"turn_limit"])
        trace.event("begin",["trigger":"manual"])
        trace.event("summary_begin",["model_hash":CompactLifecycleTrace.fingerprint("SECRET_MODEL"),"body":"SECRET_BODY","reason":"SECRET_REASON"])
        let net=CompactSummaryNetworkState(trace:trace,route:"responses",providerHash:CompactLifecycleTrace.fingerprint("SECRET_PROVIDER"),modelHash:CompactLifecycleTrace.fingerprint("SECRET_MODEL"))
        net.event(["type":"response.output_text.delta","delta":"SECRET_TEXT"],text:"SECRET_TEXT",usage:false,useChat:false)
        net.event(["type":"response.completed"],text:nil,usage:true,useChat:false)
        net.end(); net.end(cancelled:true)
        trace.cancel("user_stop");trace.cancel("network_cancel")
        trace.event("end",["outcome":"cancelled"])
        trace.cancel("model_switch") // late callback cannot rewrite the task's terminal cause
        trace.event("end",["outcome":"restored"])
        trace.event("summary_end",["outcome":"success"])
        trace.event("network_end",["finish":"cancel","events":"0"])
        let all=TraceTestLog.shared.take()
        check(rows("begin",all).count==1,"one attempt begin")
        check(rows("end",all).count==1,"one attempt end")
        check(rows("network_start",all).first?["purpose"]=="compact_summary","actual network/sink vocabulary")
        check(rows("network_end",all).first?["finish"]=="completed","actual network finish preserved")
        check(rows("network_end",all).last?["late"]=="1","late network end retained")
        check(rows("summary_end",all).isEmpty,"late work cannot look successful")
        check(rows("end",all).first?["cancel_origin"]=="user_stop","explicit stop wins generic transport cancel")
        check(trace.cancellation()=="user_stop","late cancellation cannot mutate state")
        check(Set(all.compactMap{$0["attempt"]}).count==1,"one attempt across network")
        check(Set(all.compactMap{$0["session_hash"]}).count==1,"one session fingerprint")
        check(all.allSatisfy{ row in !row.values.contains(where:{$0.contains("SECRET_")}) },"no canary text or identifiers leaked")
        let seq=all.compactMap{Int($0["sequence"] ?? "")};check(Set(seq).count==seq.count,"unique sequence")
        check(rows("summary_begin",all).first?["body"]==nil && rows("summary_begin",all).first?["reason"]==nil,"whitelist rejects body and arbitrary reason")
        let bounded=CompactLifecycleTrace(session:nil);bounded.event("begin")
        for _ in 0..<300 { bounded.event("summary_begin") }
        bounded.event("end",["outcome":"failed"])
        for _ in 0..<60 { bounded.event("network_end",["finish":"cancel"]) }
        let limited=TraceTestLog.shared.take()
        check(rows("end",limited).count==1 && limited.count<=289,"bounded lifecycle including late endings")
        let race=CompactLifecycleTrace(session:"RACE");race.event("begin")
        DispatchQueue.concurrentPerform(iterations:64) { _ in race.event("end",["outcome":"failed"]) }
        check(rows("end",TraceTestLog.shared.take()).count==1,"racing endings exactly once")
        check(!ActualSplitPolicy.isSegmentRetryableError(CompactSummaryFailure.empty),"empty summary never splits")
        check(!ActualSplitPolicy.isSegmentRetryableError(CompactSummaryFailure.incomplete),"incomplete never splits")
        check(!ActualSplitPolicy.isSegmentRetryableError(CancellationError()),"cancel never splits")
        check(!ActualSplitPolicy.isSegmentRetryableError(URLError(.cannotParseResponse)),"network parse error never splits")
        check(!ActualSplitPolicy.isSegmentRetryableError(LLMError.transientError(message:"timeout",statusCode:nil)),"timeout never splits")
        check(ActualSplitPolicy.isSegmentRetryableError(LLMError.providerError(message:"context_length_exceeded")),"size fallback retained")
        print("NATIVE PASS: actual lifecycle + actual network helper + actual retry classifier; no URLSession/iOS execution")
    }
}
