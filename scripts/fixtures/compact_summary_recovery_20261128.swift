import Foundation
/* ACTUAL_SUMMARY_FAILURE */
/* ACTUAL_SUMMARY_ASSEMBLER */
/* ACTUAL_SUMMARY_BUDGET */

@MainActor
@main struct SummaryRecoveryFixture {
    static var checks = 0
    static func check(_ value: @autoclosure () -> Bool, _ note: String) {
        precondition(value(), note); checks += 1
    }
    static func final(_ text: String, status: String = "completed", reason: String? = nil) -> [String:Any] {
        var response: [String:Any] = ["status":status,"output":[["type":"message","role":"assistant","content":[["type":"output_text","text":text]]]]]
        if let reason { response["incomplete_details"] = ["reason":reason] }
        return ["type":status == "completed" ? "response.completed":"response.incomplete","response":response]
    }
    static func fail(_ expected: CompactSummaryFailure, _ action: () throws -> Void) {
        do { try action(); preconditionFailure("missing expected error \(expected)") }
        catch { check((error as? CompactSummaryFailure) == expected,"typed precise failure") }
    }
    static func main() throws {
        var s = CompactSummaryStreamAssembler()
        let finished = try s.consume(final("完整摘要"),useChat:false)
        check(finished == "完整摘要", "final-only response restores summary text")
        check(tryFinish(s) == "stop", "complete final response accepted")
        s = CompactSummaryStreamAssembler()
        var received = try s.consume(["type":"response.output_text.delta","delta":"Hel","output_index":0,"content_index":0],useChat:false)
        received += try s.consume(["type":"response.output_text.done","text":"Hello","output_index":0,"content_index":0],useChat:false)
        received += try s.consume(["type":"response.output_item.done","output_index":0,"item":["type":"message","role":"assistant","content":[["type":"output_text","text":"Hello"]]]],useChat:false)
        received += try s.consume(final("Hello"),useChat:false)
        s.done();check(received == "Hello" && tryFinish(s) == "stop", "final snapshots add unseen suffix exactly once")
        let duplicate = try s.consume(final("Hello"),useChat:false)
        check(duplicate.isEmpty, "duplicate terminal does not duplicate summary")
        fail(.invalidResponse) { _ = try s.consume(["type":"response.output_text.delta","delta":"late"],useChat:false) }
        s = CompactSummaryStreamAssembler()
        _ = try s.consume(["type":"response.reasoning_summary_text.delta","delta":"not a summary"],useChat:false)
        _ = try s.consume(["type":"response.completed","response":["status":"completed","output":[["type":"reasoning","summary":[["text":"secret reasoning"]]]]]],useChat:false)
        fail(.empty) { _ = try s.finish() }
        for text in ["", "unfinished"] {
            s = CompactSummaryStreamAssembler()
            _ = try s.consume(final(text,status:"incomplete",reason:"max_output_tokens"),useChat:false)
            s.done(); fail(.outputLimit) { _ = try s.finish() }
        }
        for status in ["in_progress", "failed", "cancelled"] {
            s = CompactSummaryStreamAssembler()
            var contradictory = final("not-complete",status:status)
            contradictory["type"] = "response.completed"
            _ = try s.consume(contradictory,useChat:false)
            s.done(); fail(.incomplete) { _ = try s.finish() }
        }
        s = CompactSummaryStreamAssembler()
        var truncatedFinal = final("cut",status:"completed",reason:"max_output_tokens")
        truncatedFinal["type"] = "response.completed"
        _ = try s.consume(truncatedFinal,useChat:false)
        s.done(); fail(.outputLimit) { _ = try s.finish() }
        s = CompactSummaryStreamAssembler()
        _ = try s.consume(["type":"response.output_text.delta","delta":"partial"],useChat:false)
        fail(.incomplete) { _ = try s.finish() }
        fail(.invalidResponse) { _ = try s.consume(final("different text"),useChat:false) }
        s = CompactSummaryStreamAssembler()
        _ = try s.consume(["type":"response.refusal.delta","delta":"no"],useChat:false)
        s.done();fail(.refused) { _ = try s.finish() }
        s = CompactSummaryStreamAssembler()
        let message: [String:Any] = ["choices":[["index":0,"message":["role":"assistant","content":[["type":"text","text":"final-only chat"],["type":"reasoning","text":"not copied"]]],"finish_reason":"stop"]]]
        let chat = try s.consume(message,useChat:true)
        check(chat == "final-only chat" && tryFinish(s) == "stop", "chat message and typed content blocks supported")
        s = CompactSummaryStreamAssembler()
        received = try s.consume(["choices":[["delta":["content":"one"]]]],useChat:true)
        received += try s.consume(["choices":[["message":["role":"assistant","content":"one two"],"finish_reason":"stop"]]],useChat:true)
        s.done(); check(received == "one two", "chat delta then final snapshot not duplicated")
        s = CompactSummaryStreamAssembler()
        _ = try s.consume(["choices":[["delta":["reasoning_content":"thinking only"],"finish_reason":"length"]]],useChat:true)
        s.done();fail(.outputLimit) { _ = try s.finish() }
        s = CompactSummaryStreamAssembler()
        _ = try s.consume(["choices":[["delta":["content":"part"],"finish_reason":"length"]]],useChat:true)
        _ = try s.consume(["choices":[["delta":[:],"finish_reason":"stop"]]],useChat:true)
        s.done(); fail(.outputLimit) { _ = try s.finish() }
        s = CompactSummaryStreamAssembler()
        fail(.invalidResponse) { _ = try s.consume(["choices":[["index":1,"delta":["content":"other"]]]],useChat:true) }
        s = CompactSummaryStreamAssembler()
        _ = try s.consume(["type":"response.output_text.delta","delta":"A","output_index":0],useChat:false)
        _ = try s.consume(["type":"response.output_text.delta","delta":"B","output_index":1],useChat:false)
        fail(.invalidResponse) { _ = try s.consume(["type":"response.output_text.done","text":"A+","output_index":0],useChat:false) }
        s = CompactSummaryStreamAssembler()
        fail(.invalidResponse) { _ = try s.consume(["type":"response.output_text.delta","delta":String(repeating:"a",count:2*1024*1024+1)],useChat:false) }
        s = CompactSummaryStreamAssembler()
        _ = try s.consume(["type":"response.output_item.done","output_index":0,"item":["type":"function_call","name":"never-run","arguments":"secret"]],useChat:false)
        s.done(); fail(.empty) { _ = try s.finish() }
        check(CompactSummaryBudget.ceiling(window:128000,input:1000,declared:128000) == 32768,"bounded summary ceiling")
        check(CompactSummaryBudget.initial(ceiling:32768)==8192,"initial request remains modest")
        check(CompactSummaryBudget.ceiling(window:12000,input:10000,declared:32000)==2000,"context headroom wins")
        check(CompactSummaryBudget.ceiling(window:128000,input:1000,declared:4000)==4000,"explicit model cap respected")
        check(CompactSummaryBudget.retry(after:CompactSummaryFailure.outputLimit,used:8192,ceiling:32768)==16384,"explicit truncation can recover without user settings")
        check(CompactSummaryBudget.retry(after:CompactSummaryFailure.outputLimit,used:4000,ceiling:4000)==nil,"no request above model cap")
        for error in [CompactSummaryFailure.empty,.incomplete,.refused,.invalidResponse] {
            check(CompactSummaryBudget.retry(after:error,used:8192,ceiling:32768)==nil,"unproven failures never repeat")
        }
        check(CompactSummaryBudget.retry(after:CancellationError(),used:8192,ceiling:32768)==nil,"cancel never repeats")
        check(CompactSummaryBudget.ceiling(window:1,input:Int.max,declared:nil)==0,"tiny window fail closed")
        check(CompactSummaryBudget.initial(ceiling:0)==0,"zero allowance not silently raised")
        print("NATIVE PASS: \(checks) actual summary assembler/budget cases; no URLSession/device or model request")
    }
    private static func tryFinish(_ s: CompactSummaryStreamAssembler) -> String {
        do { return try s.finish() } catch { preconditionFailure("unexpected summary failure \(error)") }
    }
}
