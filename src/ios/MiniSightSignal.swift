import CoreFoundation
import Foundation
import UIKit

// MARK: - [T-minisight-agent-signal] Owned activity scopes + Darwin snapshots
//
// Visibility is NOT authorization and NOT evidence that execution started.
// An approval-only burst must show the pet, but must never start recording or
// navigate to the foreground. Activity snapshots contain no command/prompt/key.
// There is deliberately no active timeout: only the owner can end its token.
final class MiniSightSignal: @unchecked Sendable {
    static let shared = MiniSightSignal()
    static let startedNotification = "com.openminis.agent.started"
    static let stoppedNotification = "com.openminis.agent.stopped"
    static let activityNotification = "com.openminis.minisight.activity"
    static let processInstanceID = UUID().uuidString

    enum Phase { case pendingApproval, waiting, executing }
    struct Token: Hashable, Sendable { fileprivate let id = UUID() }
    private struct Activity {
        var phase: Phase
        let status: String
    }

    private static let minimumVisible: TimeInterval = 0.6
    private let lock = NSLock()
    // File I/O and Darwin delivery are ordered but never run under the state lock.
    private let publishQueue = DispatchQueue(label: "com.openminis.minisight.signal", qos: .utility)
    private var activities: [Token: Activity] = [:]
    private var stateGeneration: UInt64 = 0
    private var shownAt: TimeInterval?
    private var burstExecuted = false
    private var pendingHide: DispatchWorkItem?
    private var pendingHome: DispatchWorkItem?
    private var lastStatus = ""
    private init() {}

    /// Direct MCP function names are NOT registered in this branch's switch
    /// (they return Unknown tool). Do not turn an unexecuted name into activity.
    /// Decode ONLY command, never tool_title/content/other JSON metadata.
    static func shouldSignal(tool: String, args: String) -> Bool {
        guard tool == "shell_execute", let data = args.data(using: .utf8),
              let object = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
              let command = object["command"] as? String else { return false }
        return !deviceInvocations(command, includeNative: false).isEmpty
    }

    /// Native mutating host CLIs and nested bin/mcp call need the SAME approval
    /// as their minis-mcp-cli spelling. Read-only logreader stays read-only.
    static func requiresHostApproval(_ command: String) -> Bool {
        let dangerous: Set<String> = ["run_command", "write_file", "uninstall_app",
                                      "mcp-root", "mcp-appinst", "mcp-ldid"]
        return deviceInvocations(command).contains { dangerous.contains($0) }
    }

    /// Bounded syntax-only recognition, not a shell evaluator/security gate.
    /// Follow visible sh -c/env/timeout wrappers and command chains, but never
    /// scan quoted echo/grep payloads, JSON metadata or opaque script files.
    /// Hidden aliases/subprocesses need instrumentation at their real dispatch
    /// boundary; guessing arbitrary script contents would light local work.
    private static func deviceInvocations(_ command: String, includeNative: Bool = true, nesting: Int = 0) -> [String] {
        guard nesting < 6 else { return [] }
        let native: Set<String> = includeNative
            ? ["mcp-root", "mcp-appinst", "mcp-ldid", "mcp-logreader"]
            : []
        var result: [String] = []
        for statement in shellStatements(command) {
            var words = statement
            while let first = words.first {
                let name = (first as NSString).lastPathComponent
                if first.range(of: #"^[A-Za-z_][A-Za-z0-9_]*="#, options: .regularExpression) != nil
                    || ["env", "command", "exec", "nohup", "if", "then", "do", "else", "!"].contains(name) {
                    words.removeFirst()
                    continue
                }
                if name == "timeout", words.count > 2 {
                    words.removeFirst()
                    if words.first == "--" { words.removeFirst() }
                    if words.first?.hasPrefix("-") == false { words.removeFirst(); continue }
                }
                break
            }
            guard let first = words.first else { continue }
            let name = (first as NSString).lastPathComponent
            if ["sh", "bash", "ash", "dash", "zsh"].contains(name) {
                if let i = words.indices.dropFirst().first(where: {
                    words[$0].hasPrefix("-") && !words[$0].hasPrefix("--") && words[$0].contains("c")
                }), i + 1 < words.count {
                    result += deviceInvocations(words[i + 1], includeNative: includeNative, nesting: nesting + 1)
                }
            } else if native.contains(name) {
                if !words.dropFirst().contains("--help") && !words.dropFirst().contains("--version") {
                    result.append(name)
                }
            } else if name == "minis-mcp-cli", words.count >= 4, words[1] == "call",
                      !words[2].isEmpty, !words[3].isEmpty {
                // The real CLI invocation must include both server and tool.
                result.append(name)
            } else if name == "mcp", words.count >= 3, words[1] == "call",
                      !words[2].isEmpty {
                // Local wrapper form: mcp call <tool>.
                result.append(name)
            }
        }
        return result
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
                // Heredoc bodies are data (or opaque scripts), not free-standing
                // commands. Recognize the head only; never scan their payload.
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

    @discardableResult
    func begin(phase: Phase, tool: String, args: String) -> Token {
        lock.lock()
        defer { lock.unlock() }
        let token = Token()
        pendingHide?.cancel()
        pendingHide = nil
        pendingHome?.cancel()
        pendingHome = nil
        let show = shownAt == nil
        if show {
            shownAt = ProcessInfo.processInfo.systemUptime
            burstExecuted = false
        }
        activities[token] = Activity(phase: phase, status: Self.describe(tool: tool, args: args))
        if phase == .executing { burstExecuted = true }
        publishLocked(edge: show ? Self.startedNotification : nil)
        return token
    }

    func update(_ token: Token, phase: Phase) {
        lock.lock()
        defer { lock.unlock() }
        guard var activity = activities[token], activity.phase != phase else { return }
        activity.phase = phase
        activities[token] = activity
        if phase == .executing { burstExecuted = true }
        publishLocked()
    }

    /// 把这次 MCP 调用翻译成一句人话，写到共享文件供插件显示说话气泡。
    private static func describe(tool: String, args: String) -> String {
        let map: [(String, String)] = [
            ("tap_screen", "正在点屏幕"), ("tap_element", "正在点屏幕"),
            ("swipe_screen", "正在滑动"), ("screenshot", "正在截图"),
            ("run_command", "正在执行命令"), ("launch_app", "正在打开 App"),
            ("install_app", "正在装 App"), ("uninstall_app", "正在卸载"),
            ("read_file", "正在读文件"), ("write_file", "正在写文件"),
            ("list_dir", "正在看目录"), ("get_syslog", "正在看日志"),
            ("get_crash_logs", "正在看崩溃日志"), ("get_app_info", "正在看 App 信息"),
            ("list_apps", "正在看 App 列表"), ("press_", "正在按按键"),
            ("set_brightness", "正在调亮度"), ("set_volume", "正在调音量"),
        ]
        for (key, text) in map where args.contains(key) { return text }
        return "正在操作手机"
    }

    private struct PublishedSnapshot: Encodable, Sendable {
        let protocolVersion: Int
        let pid: Int32
        let processInstanceID: String
        let stateGeneration: UInt64
        let pendingApprovalCount: Int
        let waitingCount: Int
        let executingCount: Int
        let activeCount: Int
        let pendingApproval: Bool
        let executing: Bool
        let visible: Bool
        /// Current App already returns to Minis on its own after real execution.
        /// The tweak reads this to avoid a second LaunchServices foreground call.
        let nativeReturn: Bool
    }

    /// Called under lock, but it only snapshots memory and enqueues ordered I/O.
    /// No filesystem work, JSON encoding, or Darwin callback runs under this lock.
    private func publishLocked(edge: String? = nil) {
        stateGeneration &+= 1
        let pending = activities.values.filter { $0.phase == .pendingApproval }.count
        let waiting = activities.values.filter { $0.phase == .waiting }.count
        let executing = activities.values.filter { $0.phase == .executing }.count
        let snapshot = PublishedSnapshot(
            protocolVersion: 1, pid: ProcessInfo.processInfo.processIdentifier,
            processInstanceID: Self.processInstanceID, stateGeneration: stateGeneration,
            pendingApprovalCount: pending, waitingCount: waiting, executingCount: executing,
            activeCount: activities.count, pendingApproval: pending > 0,
            executing: executing > 0, visible: shownAt != nil, nativeReturn: true)
        let text = activities.values.first(where: { $0.phase == .executing })?.status
            ?? (pending > 0 ? "等待你确认" : waiting > 0 ? "等待设备操作" : "操作已结束")
        let statusChanged = text != lastStatus
        if statusChanged { lastStatus = text }
        publishQueue.async {
            guard let dir = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first?
                .appendingPathComponent("MiniSight", isDirectory: true) else {
                if let edge { Self.post(edge) }
                return
            }
            try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
            // Write the human text BEFORE activity.json/notification. The tweak
            // reacts to the activity notification immediately; posting first let
            // it pair the new snapshot with the previous status line.
            var statusWritten = false
            if statusChanged {
                statusWritten = (try? Data(text.utf8).write(
                    to: dir.appendingPathComponent("status.txt"), options: .atomic)) != nil
            }
            let dataWritten: Bool
            if let data = try? JSONEncoder().encode(snapshot) {
                dataWritten = (try? data.write(to: dir.appendingPathComponent("activity.json"), options: .atomic)) != nil
            } else {
                dataWritten = false
            }
            if dataWritten { Self.post(Self.activityNotification) }
            if dataWritten, statusChanged, statusWritten {
                Self.post("com.openminis.minisight.status")
            }
            if dataWritten, let edge { Self.post(edge) }
        }
    }

    /// Idempotent and ownership-scoped: late cleanup of A cannot decrement B.
    func end(_ token: Token) {
        lock.lock()
        defer { lock.unlock() }
        guard activities.removeValue(forKey: token) != nil else { return }
        guard activities.isEmpty else { publishLocked(); return }
        let elapsed = shownAt.map { ProcessInfo.processInfo.systemUptime - $0 } ?? Self.minimumVisible
        let delay = Self.minimumVisible - elapsed
        if delay <= 0 {
            shownAt = nil
            publishLocked(edge: Self.stoppedNotification)
            returnHomeSoonLocked()
        } else {
            publishLocked()
            let generation = stateGeneration
            let item = DispatchWorkItem { [weak self] in self?.hideIfIdle(generation: generation) }
            pendingHide?.cancel()
            pendingHide = item
            DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: item)
        }
    }

    /// Idle recovery only. Stopping one turn must end its own tokens; it must
    /// NEVER clear other sessions' pending approvals or executing operations.
    func reset() {
        lock.lock()
        defer { lock.unlock() }
        guard activities.isEmpty else { return }
        let wasVisible = shownAt != nil
        shownAt = nil
        burstExecuted = false
        pendingHide?.cancel()
        pendingHide = nil
        pendingHome?.cancel()
        pendingHome = nil
        publishLocked(edge: wasVisible ? Self.stoppedNotification : nil)
    }

    private func hideIfIdle(generation: UInt64) {
        lock.lock()
        defer { lock.unlock() }
        guard activities.isEmpty, stateGeneration == generation, shownAt != nil else { return }
        shownAt = nil
        pendingHide = nil
        publishLocked(edge: Self.stoppedNotification)
        returnHomeSoonLocked()
    }

    /// Preserve return-after-execution, but not after approval/denial alone.
    /// A later begin/reset invalidates even an already-dispatched home block.
    private func returnHomeSoonLocked() {
        guard burstExecuted else { return }
        let generation = stateGeneration
        let item = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.lock.lock()
            let idle = self.activities.isEmpty && self.shownAt == nil && self.stateGeneration == generation
            self.lock.unlock()
            guard idle, UIApplication.shared.applicationState != .active else { return }
            if let url = URL(string: "minis://") { UIApplication.shared.open(url) }
        }
        pendingHome = item
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4, execute: item)
    }

    private static func post(_ name: String) {
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(name as CFString),
            nil,
            nil,
            true)
    }
}
