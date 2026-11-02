//
//  SessionWorkflowGate.swift
//  MinisApp
//
//  Hard gates for the per-session plugin-engineer workflow.
//
//  The prompt tells the model to stop at discussion/result/push/install. That
//  alone is advisory. This file is the dispatch-side check: `git push` and
//  package installation are refused until the user's next message approves
//  exactly that gate.
//
//  Scope is deliberately narrow. Local edits and read-only commands stay
//  ungated; only external state changes and respring are blocked.
//

import Foundation

enum SessionAgentWorkflow {
    enum Gate: String {
        case edit
        case push
        case install
    }

    enum Check {
        case notGated
        case approved(Gate)
        case blocked(Gate, message: String)
    }

    static let pluginEngineerKeyPrefix = "session.agent.pluginEngineer."
    static let workflowSkillId = "tweak-workflow"
    private static let awaitingPrefix = "session.agent.workflow.awaiting."
    private static let approvedGatePrefix = "session.agent.workflow.approvedGate."
    private static let approvedAtPrefix = "session.agent.workflow.approvedAt."
    private static let signaturePrefix = "session.agent.workflow.signature."
    private static let autoSkillPrefix = "session.agent.workflow.autoSkill."
    private static let approvalLifetime: TimeInterval = 10 * 60

    // MARK: - Enable

    static func isEnabled(_ sessionId: String) -> Bool {
        UserDefaults.standard.bool(forKey: pluginEngineerKeyPrefix + sessionId)
    }

    @MainActor
    static func setEnabled(_ enabled: Bool, sessionId: String) {
        UserDefaults.standard.set(enabled, forKey: pluginEngineerKeyPrefix + sessionId)

        if enabled {
            // The mode owns this skill while it is on. Only record the
            // auto-enable when the skill was not already the user's choice.
            if !SkillStore.shared.isEnabledForSession(workflowSkillId, sessionId: sessionId) {
                SkillStore.shared.setSessionOverride(skillId: workflowSkillId,
                                                     sessionId: sessionId,
                                                     enabled: true)
                UserDefaults.standard.set(true, forKey: autoSkillPrefix + sessionId)
            }
            return
        }

        if UserDefaults.standard.bool(forKey: autoSkillPrefix + sessionId) {
            SkillStore.shared.clearSessionOverride(skillId: workflowSkillId, sessionId: sessionId)
            UserDefaults.standard.removeObject(forKey: autoSkillPrefix + sessionId)
        }
        clearApproval(sessionId: sessionId)
    }

    // MARK: - User approval

    /// Called on a real user send. A gate that was waiting for an answer only
    /// advances on an affirmative message; anything else closes the wait and
    /// makes the next external call ask again.
    static func noteUserMessage(_ text: String, sessionId: String) {
        guard isEnabled(sessionId), let gate = awaiting(sessionId: sessionId) else { return }
        if isApprovalText(text, for: gate) {
            let defaults = UserDefaults.standard
            defaults.set(gate.rawValue, forKey: approvedGatePrefix + sessionId)
            defaults.set(Date().timeIntervalSince1970, forKey: approvedAtPrefix + sessionId)
            defaults.removeObject(forKey: signaturePrefix + sessionId)
        } else {
            clearApproval(sessionId: sessionId)
        }
    }

    private static func isApprovalText(_ raw: String, for gate: Gate) -> Bool {
        let text = raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        guard !text.isEmpty, text.count <= 40 else { return false }
        var words: [String] = ["可以", "继续", "行", "好", "ok", "yes"]
        switch gate {
        case .edit: words += ["改", "做", "开始", "照这个"]
        case .push: words += ["推", "推送", "开推", "push"]
        case .install: words += ["装", "安装", "开始装", "install"]
        }
        return words.contains { text.hasPrefix($0) }
    }

    // MARK: - Dispatch gate

    /// File tools are refused until the user has confirmed the proposed
    /// result. STATUS.md is bookkeeping and stays writable during discussion.
    static func checkFileTool(tool: String, argsJson: String, sessionId: String?) -> Check {
        guard tool == "file_write" || tool == "file_edit" else { return .notGated }
        guard let sessionId, isEnabled(sessionId) else { return .notGated }

        if let data = argsJson.data(using: .utf8),
           let args = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let path = args["path"] as? String,
           path.hasSuffix("/STATUS.md") || path == "STATUS.md" {
            return .notGated
        }
        return evaluate(.edit, signature: nil, sessionId: sessionId)
    }

    /// Check a shell command immediately before execution.
    static func check(command: String, sessionId: String?) -> Check {
        guard let sessionId, isEnabled(sessionId), let gate = classify(command) else {
            return .notGated
        }
        // A push is scoped to the exact command (branch/remote). An install is
        // scoped to the package path; a following respring has no path and
        // rides on the same approval.
        return evaluate(gate, signature: scopedSignature(for: gate, command: command), sessionId: sessionId)
    }

    private static func evaluate(_ gate: Gate, signature: String?, sessionId: String) -> Check {
        let defaults = UserDefaults.standard
        let approvedGate = defaults.string(forKey: approvedGatePrefix + sessionId)
        let approvedAt = defaults.double(forKey: approvedAtPrefix + sessionId)
        let stored = defaults.string(forKey: signaturePrefix + sessionId)
        let fresh = approvedAt > 0 && Date().timeIntervalSince1970 - approvedAt <= approvalLifetime
        let sameScope = signature == nil || stored == nil || stored == signature

        if approvedGate == gate.rawValue, fresh, sameScope {
            if let signature, stored == nil { defaults.set(signature, forKey: signaturePrefix + sessionId) }
            // Keep the gate armed and the approval alive for retries of the
            // exact same command (for example a transient network failure).
            defaults.set(gate.rawValue, forKey: awaitingPrefix + sessionId)
            return .approved(gate)
        }

        clearApproval(sessionId: sessionId)
        defaults.set(gate.rawValue, forKey: awaitingPrefix + sessionId)
        return .blocked(gate, message: blockedMessage(for: gate))
    }

    private static func blockedMessage(for gate: Gate) -> String {
        switch gate {
        case .edit:
            return "Error: 插件工程师闸门拦下了代码修改：用户还没有确认具体结果。先列出要改的文件、行为变化、验收项和风险，问“照这个做吗”，然后结束本回合。STATUS.md 可以直接写，其他文件等批准后再改。"
        case .push:
            return "Error: 插件工程师闸门拦下了推送/CI：用户还没有在当前这一步批准。先用普通文字给出改动摘要、测试结果和目标分支，问“要推送吗”，然后结束本回合，等用户下一条消息批准。推送必须直接执行 `git push`，不要藏进脚本绕过闸门。"
        case .install:
            return "Error: 插件工程师闸门拦下了安装/注销：用户还没有在当前这一步批准。先给出包路径、版本、架构、签名/哈希核验和回滚办法，问“要安装吗”，然后结束本回合，等用户下一条消息批准。安装必须直接调用 `minis-mcp-cli call 越狱mcp install_app` 或 `mcp-appinst`，不要藏进脚本绕过闸门。"
        }
    }

    private static func awaiting(sessionId: String) -> Gate? {
        guard let raw = UserDefaults.standard.string(forKey: awaitingPrefix + sessionId) else { return nil }
        return Gate(rawValue: raw)
    }

    private static func clearApproval(sessionId: String) {
        let d = UserDefaults.standard
        d.removeObject(forKey: awaitingPrefix + sessionId)
        d.removeObject(forKey: approvedGatePrefix + sessionId)
        d.removeObject(forKey: approvedAtPrefix + sessionId)
        d.removeObject(forKey: signaturePrefix + sessionId)
    }

    // MARK: - Prompt

    static func promptFragment(for sessionId: String) -> String? {
        guard isEnabled(sessionId) else { return nil }
        let state: String = {
            switch awaiting(sessionId: sessionId) {
            case .edit?: return "等待结果确认"
            case .push?: return "等待推送批准"
            case .install?: return "等待安装批准"
            case nil: return "无待批准动作"
            }
        }()
        return """
        <plugin-engineer>
        当前会话启用了「插件工程师」。工具不变，规则比通用自动执行更严格。
        当前状态：\(state)

        流程与硬停：
        1. 先回答用户问题，再商讨方案和取舍。只读检查可以，不改文件。结尾给明确结论，问结论是否正确，然后结束本回合。
        2. 用户确认结论后，给具体结果：改哪些文件、行为变化、验收项、风险。问是否照做；没确认不写文件。
        3. 结果确认由闸门强制：未批准时 file_write/file_edit 会被拒绝（STATUS.md 除外）。
        4. 用户确认后才改本地并检查。完成后给改动和测试结果，问“推送吗”，然后结束回合（文字或 ask_user 均可）。没批准不 commit/push/CI。
        5. 出包并核验后给包、哈希和验收边界，问“安装吗”，然后结束回合（文字或 ask_user 均可）。没批准不安装、不卸载、不注销、不重启。
        6. 安装后真机验收完给通过/失败/未测，停，不自动开下一件。

        闸门由 App 强制执行：
        - 闸门拒绝 file_write/file_edit 时，说明结果、问“照这个做吗”并结束本回合。
        - 推送只直接执行 `git push`，CI 只直接执行 `gh workflow run` / `gh run`。
        - 安装只直接执行 `minis-mcp-cli call 越狱mcp install_app` 或 `mcp-appinst`；注销用 `killall SpringBoard` / `sbreload`。
        - 调用被闸门拒绝时，说明结果、问批准并结束本回合；不要换别的方式绕过。
        - 用户批准只对当前命令和当前版本有效；换 commit、换包或超过十分钟重新问。

        证据：先读真实源码/日志/包；静态检查不能写成真机通过。中断前写下最后安全步骤和未授权动作。
        </plugin-engineer>
        """
    }

    // MARK: - Shell classification

    /// Recognises only direct, visible invocations. A push hidden inside an
    /// opaque release script is intentionally not guessed; the prompt tells the
    /// model to keep these calls direct.
    private static func classify(_ command: String) -> Gate? {
        var found: Gate?
        for statement in shellStatements(command) {
            let words = statement
            var i = 0
            while i < words.count {
                let name = (words[i] as NSString).lastPathComponent
                if words[i].range(of: #"^[A-Za-z_][A-Za-z0-9_]*="#, options: .regularExpression) != nil
                    || ["env", "command", "exec", "nohup", "if", "then", "do", "else", "!"].contains(name) {
                    i += 1
                    continue
                }
                if name == "timeout", i + 2 < words.count {
                    i += 1
                    if words[i] == "--" { i += 1 }
                    if !words[i].hasPrefix("-") { i += 1; continue }
                }
                break
            }
            guard i < words.count else { continue }
            let name = (words[i] as NSString).lastPathComponent
            let tail = Array(words.dropFirst(i + 1))

            if ["sh", "bash", "ash", "dash", "zsh"].contains(name),
               let ci = tail.indices.first(where: {
                   tail[$0].hasPrefix("-") && !tail[$0].hasPrefix("--") && tail[$0].contains("c")
               }), ci + 1 < tail.count,
               let nested = classify(tail[ci + 1]) {
                found = merge(found, nested)
                continue
            }

            if name == "git", gitSubcommand(tail) == "push" { found = merge(found, .push) }
            if name == "gh", isGitHubCITrigger(tail) { found = merge(found, .push) }

            if let tool = mcpTool(name: name, words: tail) {
                if ["install_app", "uninstall_app"].contains(tool) { found = merge(found, .install) }
            }
            if name == "mcp-appinst" { found = merge(found, .install) }
            if name == "dpkg", tail.contains("-i") || tail.contains("--install") { found = merge(found, .install) }
            if name == "killall", tail.contains("SpringBoard") { found = merge(found, .install) }
            if ["sbreload", "respring"].contains(name) { found = merge(found, .install) }
        }
        return found
    }

    private static func merge(_ current: Gate?, _ next: Gate) -> Gate {
        // Installing is the later, more consequential gate; when one command
        // contains both, asking for install also implies the push finished.
        (current == .install || next == .install) ? .install : .push
    }

    private static func gitSubcommand(_ tail: [String]) -> String? {
        var i = 0
        while i < tail.count {
            let w = tail[i]
            if ["-C", "-c", "--git-dir", "--work-tree"].contains(w) { i += 2; continue }
            if w.hasPrefix("-") { i += 1; continue }
            return w
        }
        return nil
    }

    private static func isGitHubCITrigger(_ tail: [String]) -> Bool {
        let bare = tail.filter { !$0.hasPrefix("-") }
        if bare.first == "workflow", bare.dropFirst().first == "run" { return true }
        if bare.first == "run", bare.dropFirst().first == "rerun" { return true }
        return false
    }

    private static func mcpTool(name: String, words: [String]) -> String? {
        if name == "minis-mcp-cli", words.count >= 3, words[0] == "call" {
            return words[2]
        }
        if name == "mcp", words.count >= 2, words[0] == "call" {
            return words[1]
        }
        return nil
    }

    private static func scopedSignature(for gate: Gate, command: String) -> String? {
        if gate == .push {
            return command.split(whereSeparator: { $0.isWhitespace }).joined(separator: " ")
        }
        for raw in command.split(whereSeparator: { $0.isWhitespace }) {
            var word = raw.trimmingCharacters(in: CharacterSet(charactersIn: "\"'"))
            if word.hasPrefix("path=") { word.removeFirst(5) }
            let lower = word.lowercased()
            if lower.hasSuffix(".deb") || lower.hasSuffix(".ipa") || lower.hasSuffix(".tipa") {
                return word
            }
        }
        return nil
    }

    private static func shellStatements(_ command: String) -> [[String]] {
        let chars = Array(command)
        var statements: [[String]] = []
        var words: [String] = []
        var word = ""
        var quote: Character?
        var started = false
        var i = 0
        func finishWord() {
            if started { words.append(word); word = ""; started = false }
        }
        func finishStatement() {
            finishWord()
            if !words.isEmpty { statements.append(words); words = [] }
        }
        while i < chars.count {
            let c = chars[i]
            if c == "\\", quote != "'", i + 1 < chars.count {
                i += 1
                if chars[i] != "\n" { word.append(chars[i]); started = true }
            } else if let q = quote {
                if c == q { quote = nil } else { word.append(c) }
            } else if c == "'" || c == "\"" {
                quote = c
                started = true
            } else if c == "#", !started {
                while i < chars.count, chars[i] != "\n" { i += 1 }
                finishStatement()
            } else if c == "<", i + 1 < chars.count, chars[i + 1] == "<" {
                finishStatement()
                return statements
            } else if "\n;|&()".contains(c) {
                finishStatement()
            } else if c.isWhitespace {
                finishWord()
            } else {
                word.append(c)
                started = true
            }
            i += 1
        }
        guard quote == nil else { return [] }
        finishStatement()
        return statements
    }
}
