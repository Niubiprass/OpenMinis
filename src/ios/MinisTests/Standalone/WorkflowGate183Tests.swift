// REAL policy execution on a Foundation host, not source-string assertions.
// swiftc -D WORKFLOW_GATE_STANDALONE -parse-as-library \
//   src/ios/Agent/Chat/SessionWorkflowGate.swift \
//   src/ios/MinisTests/Standalone/WorkflowGate183Tests.swift -o /tmp/workflow183
// /tmp/workflow183
import Foundation
import Dispatch

#if WORKFLOW_GATE_STANDALONE
@MainActor
final class WorkflowGate183SkillStore {
    static let shared = WorkflowGate183SkillStore()
    var selections: [String: Bool] = [:]
    var sessionOverrideVersion = 0
    var clears = 0
    var folderDefaults: [String: Bool] = [:]
    var globalEnabled = false
    func isEnabledForSession(_ skillId: String, sessionId: String) -> Bool {
        if skillId == SessionAgentWorkflow.workflowSkillId,
           SessionAgentWorkflow.isEnabled(sessionId) { return true }
        return selections[sessionId] ?? folderDefaults[sessionId] ?? globalEnabled
    }
    func refreshWorkflowSelection() { sessionOverrideVersion += 1 }
    func setSessionOverride(skillId: String, sessionId: String, enabled: Bool) {
        selections[sessionId] = enabled; sessionOverrideVersion += 1
    }
    func clearSessionOverride(skillId: String, sessionId: String) {
        selections.removeValue(forKey: sessionId); sessionOverrideVersion += 1; clears += 1
    }
}

private final class ApprovalCount: @unchecked Sendable {
    private let lock = NSLock()
    private var count = 0
    func add(_ check: SessionAgentWorkflow.Check) {
        if case .approved = check { lock.lock(); count += 1; lock.unlock() }
    }
    var value: Int { lock.lock(); defer { lock.unlock() }; return count }
}

@main
@MainActor
struct WorkflowGate183Tests {
    typealias W = SessionAgentWorkflow
    static var failures = 0
    static var checks = 0
    static func expect(_ value: Bool, _ label: String) {
        checks += 1
        if !value { failures += 1; print("FAIL \(label)") }
    }
    static func blocked(_ value: W.Check, _ gate: W.Gate? = nil) -> Bool {
        if case .blocked(let actual, _) = value { return gate == nil || gate == actual }
        return false
    }
    static func approved(_ value: W.Check, _ gate: W.Gate) -> Bool {
        if case .approved(let actual) = value { return gate == actual }; return false
    }
    static func ungated(_ value: W.Check) -> Bool {
        if case .notGated = value { return true }; return false
    }
    static func answer(_ value: W.Check) -> String {
        guard case .blocked(_, let message) = value,
              let line = message.components(separatedBy: "\n").first(where: { $0.hasPrefix("批准") }) else {
            expect(false, "blocked response exposes exact pending answer"); return "INVALID"
        }
        return line
    }
    static func session() -> String {
        let id = UUID().uuidString
        W.setEnabled(true, sessionId: id)
        return id
    }
    static func file(_ path: String, _ sessionId: String, tool: String = "file_write") -> W.Check {
        let data = try! JSONSerialization.data(withJSONObject: ["path": path, "content": "test"])
        return W.checkFileTool(tool: tool, argsJson: String(data: data, encoding: .utf8)!, sessionId: sessionId)
    }

    static func main() {
        let suite = "workflow183.tests." + UUID().uuidString
        let defaults = UserDefaults(suiteName: suite)!
        defer { defaults.removePersistentDomain(forName: suite) }
        W.resetForTests(defaults: defaults)
        expect(!W.isEnabled(""), "empty session stays disabled")
        expect(ungated(W.check(command: "git push", sessionId: nil)), "nil session")
        expect(ungated(W.check(command: "git push", sessionId: "disabled")), "mode off")
        expect(W.promptFragment(for: "disabled") == nil, "no prompt when off")
        expect(ungated(W.checkFileTool(tool: "file_read", argsJson: "{}", sessionId: session())), "read tool")
        expect(ungated(W.checkFileTool(tool: "file_write", argsJson: "{}", sessionId: nil)), "nil file session")

        let edit = session()
        let editAnswer = answer(file("/tmp/source.swift", edit))
        expect(blocked(file("/tmp/source.swift", edit), .edit), "edit waits")
        expect(ungated(file("/tmp/STATUS.md", edit)), "bookkeeping exception")
        expect(ungated(file("STATUS.md", edit, tool: "file_edit")), "relative bookkeeping")
        for path in ["/tmp/STATUS.md.bak", "/tmp/STATUS.md/child", "/tmp/../STATUS.md", "/tmp/./STATUS.md", "minis://workspace/STATUS.md"] {
            expect(blocked(file(path, edit)), "not bookkeeping: \(path)")
        }
        W.noteUserMessage(editAnswer, sessionId: edit)
        expect(approved(file("/tmp/a.swift", edit), .edit), "strict edit approval")
        expect(approved(file("/tmp/b.swift", edit, tool: "file_edit"), .edit), "edit stage permits several files")
        expect(approved(W.check(command: "mkdir /tmp/build; printf x > /tmp/build/a", sessionId: edit), .edit), "visible shell write stage")
        W.noteUserMessage("新问题，先看看", sessionId: edit)
        expect(blocked(file("/tmp/c.swift", edit)), "new user message ends edit stage")
        expect(blocked(W.checkFileTool(tool: "file_write", argsJson: "not-json", sessionId: edit)), "invalid JSON fails closed")
        expect(blocked(W.checkFileTool(tool: "file_edit", argsJson: "{}", sessionId: edit)), "unknown path fails closed")

        let actions: [(W.Gate, String)] = [
            (.push, "git -C /tmp/repo push origin HEAD:review"),
            (.ci, "gh workflow run check.yml --ref review"),
            (.install, "dpkg -i /tmp/a.deb"),
            (.uninstall, "dpkg --remove sample.package"),
            (.respring, "killall SpringBoard"),
            (.reboot, "reboot")
        ]
        for (gate, command) in actions {
            let id = session()
            let first = W.check(command: command, sessionId: id)
            expect(blocked(first, gate), "classify \(gate)")
            let reply = answer(first)
            W.noteUserMessage(reply, sessionId: id)
            expect(approved(W.check(command: command, sessionId: id), gate), "approve \(gate) once")
            let retry = W.check(command: command, sessionId: id)
            expect(blocked(retry, gate), "failure/retry needs fresh approval: \(gate)")
            expect(answer(retry) != reply, "retry nonce changes: \(gate)")
            W.noteUserMessage(reply, sessionId: id)
            expect(blocked(W.check(command: command, sessionId: id)), "old answer cannot replay: \(gate)")
        }

        let negatives: [(String) -> String] = [
            { _ in "可以" }, { _ in "好" }, { _ in "继续" }, { _ in "yes" }, { _ in "ok" },
            { _ in "安装" }, { _ in "批准安装但先看看" }, { _ in "用户未确认" },
            { "不" + $0 }, { "不要" + $0 }, { "先看看，" + $0 },
            { "先别做，" + $0 }, { $0 + "，但不要执行" }, { $0 + "?" },
            { $0 + "\n先看看" }, { "引用：" + $0 },
            { $0.replacingOccurrences(of: "安装", with: "推送") },
            { $0.replacingOccurrences(of: "批准", with: "不批准") },
            { _ in "批准安装 unrelated-question-card" }
        ]
        for (index, negative) in negatives.enumerated() {
            let id = session()
            let reply = answer(W.check(command: actions[2].1, sessionId: id))
            W.noteUserMessage(negative(reply), sessionId: id)
            expect(blocked(W.check(command: actions[2].1, sessionId: id)), "negative/prefix/wrong-gate \(index)")
        }
        // Every gate is independent of all other gates, not an install/push merge.
        for (gate, command) in actions {
            for (otherGate, otherCommand) in actions where otherGate != gate {
                let id = session()
                let reply = answer(W.check(command: command, sessionId: id))
                W.noteUserMessage(reply, sessionId: id)
                expect(blocked(W.check(command: otherCommand, sessionId: id), otherGate), "\(gate) never authorizes \(otherGate)")
            }
        }

        let mixed = [
            "git push origin review && dpkg -i /tmp/a.deb",
            "dpkg -i /tmp/a.deb; killall SpringBoard",
            "dpkg -i /tmp/a.deb && dpkg -r sample.package",
            "gh workflow run check.yml; git push origin review",
            "reboot; sbreload", "git push origin a; git push origin b",
            "git commit -m local && git push origin review",
            "git push origin review > /tmp/push.log",
            "bash -lc 'git push origin review && dpkg -i /tmp/a.deb'"
        ]
        for command in mixed {
            let id = session()
            expect(blocked(W.check(command: command, sessionId: id)), "reject mixed \(command)")
            W.noteUserMessage("批准安装", sessionId: id)
            expect(blocked(W.check(command: command, sessionId: id)), "mixed has no approvable pending")
        }
        let id = session()
        let pushA = "git push origin HEAD:review"
        let pushB = "git push other HEAD:review"
        let pendingA = answer(W.check(command: pushA, sessionId: id))
        expect(blocked(W.check(command: pushB, sessionId: id)), "new target cannot replace pending")
        W.noteUserMessage(pendingA, sessionId: id)
        expect(approved(W.check(command: pushA, sessionId: id), .push), "first pending retains exact target")
        expect(blocked(W.check(command: pushB, sessionId: id)), "different remote requires confirmation")
        let changed = session()
        let changedAnswer = answer(W.check(command: pushA, sessionId: changed))
        W.noteUserMessage(changedAnswer, sessionId: changed)
        expect(blocked(W.check(command: pushA + " ", sessionId: changed)), "even whitespace changes exact signature")
        expect(blocked(W.check(command: pushA, sessionId: changed)), "mismatch revokes unused grant")
        let revoked = session()
        let revokedAnswer = answer(W.check(command: pushA, sessionId: revoked))
        W.noteUserMessage(revokedAnswer, sessionId: revoked)
        W.noteUserMessage("先看看，不推", sessionId: revoked)
        expect(blocked(W.check(command: pushA, sessionId: revoked)), "new send revokes unused external approval")
        let isolated = session()
        let isolatedAnswer = answer(W.check(command: pushA, sessionId: isolated))
        W.noteUserMessage(isolatedAnswer, sessionId: session())
        expect(blocked(W.check(command: pushA, sessionId: isolated)), "session isolation")

        for _ in 0..<8 {
            let concurrent = session()
            let reply = answer(W.check(command: pushA, sessionId: concurrent))
            W.noteUserMessage(reply, sessionId: concurrent)
            let count = ApprovalCount()
            DispatchQueue.concurrentPerform(iterations: 32) { _ in
                count.add(W.check(command: pushA, sessionId: concurrent))
            }
            expect(count.value == 1, "atomic consume: exactly one of 32 concurrent calls")
        }
        let disabled = session()
        let disabledAnswer = answer(W.check(command: pushA, sessionId: disabled))
        W.noteUserMessage(disabledAnswer, sessionId: disabled)
        W.setEnabled(false, sessionId: disabled)
        W.setEnabled(true, sessionId: disabled)
        expect(blocked(W.check(command: pushA, sessionId: disabled)), "toggle revokes approval")

        for command in [
            "git status --short", "git log -1", "gh run view 12", "gh workflow list",
            "printf '%s' 'git push; dpkg -i /tmp/a.deb'", "echo git push # reboot",
            "cat /tmp/source.swift", "dpkg -l", "python3 --version"
        ] {
            expect(ungated(W.check(command: command, sessionId: session())), "read/literal remains ungated: \(command)")
        }
        let direct: [(W.Gate, String)] = [
            (.push, "timeout -s TERM 5s env -u HOME command /usr/bin/git -C /tmp push origin review"),
            (.push, "bash -lc 'git push origin review'"),
            (.ci, "gh -R owner/repo run rerun 12"),
            (.ci, "gh api -X POST repos/a/b/actions/workflows/test.yml/dispatches"),
            (.install, "minis-mcp-cli call 越狱mcp install_app '{\"path\":\"/tmp/a.ipa\"}'"),
            (.uninstall, "minis-mcp-cli call 越狱mcp uninstall_app '{\"bundle_id\":\"sample.app\"}'"),
            (.uninstall, "mcp-appinst --uninstall sample.app"),
            (.respring, "sbreload"), (.reboot, "shutdown -r now"),
            (.edit, "sed -i 's/a/b/' /tmp/source.swift"), (.edit, "touch /tmp/source.swift")
        ]
        for (gate, command) in direct {
            expect(blocked(W.check(command: command, sessionId: session()), gate), "direct wrapper detection: \(command)")
        }
        for command in [
            "git push origin $BRANCH", "bash -lc 'git push $REMOTE HEAD'",
            "$(echo git) push", "echo `git push`", "git push 'unterminated",
            "cat <<EOF\ngit push\nEOF", "eval 'git push'", "for x in a b; do git push; done",
            "find /tmp -exec git push \\;", "xargs git push"
        ] {
            let opaque = session()
            expect(blocked(W.check(command: command, sessionId: opaque)), "opaque/unbound fails closed")
            W.noteUserMessage("可以继续", sessionId: opaque)
            expect(blocked(W.check(command: command, sessionId: opaque)), "opaque cannot use generic approval")
        }

        for (gate, command) in actions {
            let id = session()
            _ = W.check(command: command, sessionId: id)
            W.noteUserMessage("批准" + gate.title, sessionId: id)
            expect(approved(W.check(command: command, sessionId: id), gate), "concise action-specific approval")
            expect(blocked(W.check(command: command, sessionId: id)), "concise approval also single-use")
        }
        let autoTurn = session()
        let autoAnswer = answer(W.check(command: actions[0].1, sessionId: autoTurn))
        W.noteUserMessage(autoAnswer, sessionId: autoTurn)
        W.invalidateAuthorization(sessionId: autoTurn)
        expect(blocked(W.check(command: actions[0].1, sessionId: autoTurn)), "automatic turn revokes, never grants")
        for command in [
            "mcp-appinst /tmp/a.deb --respring",
            "mcp-appinst /tmp/a.deb --reboot=true",
            "minis-mcp-cli call 越狱mcp install_app --input '{\"path\":\"/tmp/a.deb\",\"respring\":true}'",
            "minis-mcp-cli call 越狱mcp install_app --input '{\"path\":\"/tmp/a.deb\",\"reboot\":true}'"
        ] {
            let id = session()
            expect(blocked(W.check(command: command, sessionId: id)), "implicit device action refused")
            W.noteUserMessage("批准安装", sessionId: id)
            expect(blocked(W.check(command: command, sessionId: id)), "mixed install cannot be approved as one action")
        }

        let skills = WorkflowGate183SkillStore.shared
        let own = session()
        expect(skills.isEnabledForSession(W.workflowSkillId, sessionId: own), "auto-enables workflow skill")
        let beforeClear = skills.clears
        W.setEnabled(false, sessionId: own)
        expect(skills.clears == beforeClear, "overlay never deletes a skill selection")
        expect(!skills.isEnabledForSession(W.workflowSkillId, sessionId: own), "turning mode off removes only overlay")
        let explicitFalse = UUID().uuidString
        skills.setSessionOverride(skillId: W.workflowSkillId, sessionId: explicitFalse, enabled: false)
        W.setEnabled(true, sessionId: explicitFalse)
        expect(skills.isEnabledForSession(W.workflowSkillId, sessionId: explicitFalse), "mode requires workflow over explicit false")
        W.setEnabled(false, sessionId: explicitFalse)
        expect(skills.selections[explicitFalse] == false, "explicit false survives mode toggle")
        expect(!skills.isEnabledForSession(W.workflowSkillId, sessionId: explicitFalse), "false restored exactly")
        let folderFalse = UUID().uuidString
        skills.folderDefaults[folderFalse] = false
        W.setEnabled(true, sessionId: folderFalse)
        W.setEnabled(false, sessionId: folderFalse)
        expect(skills.selections[folderFalse] == nil, "folder default not replaced by an override")
        expect(!skills.isEnabledForSession(W.workflowSkillId, sessionId: folderFalse), "folder false restored")
        let already = UUID().uuidString
        skills.setSessionOverride(skillId: W.workflowSkillId, sessionId: already, enabled: true)
        W.setEnabled(true, sessionId: already)
        let beforeExisting = skills.clears
        W.setEnabled(false, sessionId: already)
        expect(skills.clears == beforeExisting, "does not retract user's pre-enabled skill")
        let adopted = session()
        skills.setSessionOverride(skillId: W.workflowSkillId, sessionId: adopted, enabled: true)
        let beforeAdopted = skills.clears
        W.setEnabled(false, sessionId: adopted)
        expect(skills.clears == beforeAdopted, "manual reselection releases auto ownership conservatively")
        expect(skills.isEnabledForSession(W.workflowSkillId, sessionId: adopted), "manual choice remains")

        print("Swift runtime: \(checks - failures)/\(checks) passed; \(failures) failures")
        exit(failures == 0 ? 0 : 1)
    }
}
#endif
