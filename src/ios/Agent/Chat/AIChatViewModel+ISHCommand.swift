import Foundation

private let logger = AppLogger(category: "AIChatVM")

// MARK: - Command Execution (ISHShellExecutor)

extension AIChatViewModel {

    // MARK: - Command Execution (ISHShellExecutor)

    /// Result of command execution containing output text and exit code.
    struct CommandResult {
        let output: String
        let exitCode: Int
    }

    /// Execute a command via ISHExecutionCoordinator (serialized, mount-safe).
    /// Returns clean stdout+stderr output without any TTY artifacts, plus the exit code.
    func executeCommand(_ command: String, timeout: TimeInterval? = nil, lineCallback: @escaping (String) -> Void) async throws -> CommandResult {
        let effectiveTimeout = timeout ?? defaultCommandTimeout

        // [T-mcp-approval-gate] 越狱 MCP 的调用必须先得到用户同意（默认强制弹窗）。
        // 关掉设置里的开关就不弹窗，恢复普通调用。
        if !(await mcpApprovalGateAllows(command)) {
            logger.info("MCP command rejected by user: \(command.prefix(80))")
            return CommandResult(output: "用户拒绝执行该命令（越狱 MCP 调用需要确认）", exitCode: -1)
        }

        logger.info("Executing command via coordinator (timeout: \(Int(effectiveTimeout))s): \(command)")

        // [T-p2-shared-workspace] A helper's shell runs in its parent's bucket.
        guard let sid = fsSessionId else {
            return CommandResult(output: "Error: no session", exitCode: -1)
        }

        // [T-bash-on-demand] Detect busybox-ash-incompatible bash syntax and, if
        // found, transparently install + switch to bash. Install time is NOT
        // charged against `effectiveTimeout` (it has its own budget inside
        // OnDemandBash). Only the shell_execute path reaches here; the
        // interactive terminal uses a different path and is untouched.
        let bashism = BashismDetector.detect(command)
        var bashReminder: String? = nil
        if bashism.needsBash {
            let outcome = await OnDemandBash.shared.ensureBash(executor: ishExecutor(sessionId: sid))
            switch outcome {
            case .available:
                if bashism.mustSwitchInterpreter {
                    // §3.2 M3: run the script via bash by self-writing it in the
                    // guest (base64, single line, no host→fakefs write, self-cleaning).
                    return try await runViaBash(command, sessionId: sid, timeout: effectiveTimeout,
                                                lineCallback: lineCallback)
                }
                // T1 only (script already invokes bash itself) — run as-is under sh.
            case .unavailable(let reason):
                // Fall back to sh; attach a reminder if the command then fails,
                // or immediately for silent-error (S) hits whose failure mode is
                // "looks fine, wrong result" (design §4.2 default-on exception).
                bashReminder = BashismReminder.build(hits: bashism.hits, installFailure: reason)
            }
        }
        return try await runWithReminder(command, sessionId: sid, timeout: effectiveTimeout,
                                         reminder: bashReminder, silentClass: bashism.hasSilent,
                                         lineCallback: lineCallback)
    }

    /// Executor adapter handing OnDemandBash a way to run guest commands.
    private func ishExecutor(sessionId sid: String) -> OnDemandBash.Executor {
        OnDemandBash.Executor(run: { command, timeout in
            let r = try? await ISHExecutionCoordinator.shared.execute(
                sessionId: sid, command: command, timeout: timeout,
                lineCallback: { _ in }, pidCallback: { _ in })
            return r?.exitCode ?? -1
        })
    }

    /// Sentinel exit code the bash wrapper returns when bash is missing at run
    /// time (distinguishes "bash gone" from a script that legitimately exits
    /// 127). 119 is otherwise unused by our commands.
    private static let bashMissingSentinel = 119

    /// Run `script` under bash by self-writing it in the guest (M3): base64 →
    /// decode to a per-pid temp file → `bash file` → capture rc → delete. No
    /// host→fakefs write, no heredoc, self-cleaning on the same command line.
    /// The wrapper guards on `command -v bash` first so a bash that vanished
    /// between our cache check and now (user `apk del bash`) is detected
    /// precisely (M5) and self-healed inline rather than failing the command.
    private func runViaBash(_ script: String, sessionId sid: String,
                            timeout: TimeInterval,
                            lineCallback: @escaping (String) -> Void,
                            allowReinstall: Bool = true) async throws -> CommandResult {
        // [T-heredoc-trailing-newline] Same heredoc-terminator rule applies to
        // the decoded script bash runs: a heredoc that ends the file with no
        // trailing newline fails with "unexpected end of file". Guarantee one.
        let normalized = script.hasSuffix("\n") ? script : script + "\n"
        let b64 = Data(normalized.utf8).base64EncodedString()
        let f = "/tmp/.minis-exec-$$.sh"
        let wrapped = "command -v bash >/dev/null 2>&1 || exit \(Self.bashMissingSentinel); "
            + "printf %s '\(b64)' | base64 -d > \(f) && bash \(f); rc=$?; rm -f \(f); exit $rc"
        let result = try await runRaw(wrapped, sessionId: sid, timeout: timeout, lineCallback: lineCallback)

        // M5 self-heal: bash disappeared after we cached it available. Re-probe
        // and, once only, try to reinstall + rerun under bash inline so THIS
        // command still succeeds instead of the next one.
        // The coordinator can surface either the raw exit code (119) or the
        // wait(2)-encoded status (119 << 8 = 30464), so accept both.
        if result.exitCode == Self.bashMissingSentinel
            || result.exitCode == (Self.bashMissingSentinel << 8) {
            await OnDemandBash.shared.markDisappeared()
            if allowReinstall {
                let outcome = await OnDemandBash.shared.ensureBash(executor: ishExecutor(sessionId: sid))
                if case .available = outcome {
                    return try await runViaBash(script, sessionId: sid, timeout: timeout,
                                                lineCallback: lineCallback, allowReinstall: false)
                }
            }
            // Reinstall unavailable → degrade to sh so the script at least runs.
            return try await runRaw(script, sessionId: sid, timeout: timeout, lineCallback: lineCallback)
        }
        return result
    }

    /// Run `command` and, when a bash reminder applies, append it to the output
    /// per the §4.2 trigger rules (non-zero exit, OR any silent-class hit).
    private func runWithReminder(_ command: String, sessionId sid: String,
                                 timeout: TimeInterval, reminder: String?, silentClass: Bool,
                                 lineCallback: @escaping (String) -> Void) async throws -> CommandResult {
        let result = try await runRaw(command, sessionId: sid, timeout: timeout, lineCallback: lineCallback)
        guard let reminder else { return result }
        let shouldAppend = result.exitCode != 0 || silentClass
        guard shouldAppend else { return result }
        return CommandResult(output: result.output + "\n\n" + reminder, exitCode: result.exitCode)
    }

    /// The original coordinator call + output sanitation/truncation, factored
    /// out so the bash/sh/reminder wrappers share one implementation.
    private func runRaw(_ command: String, sessionId sid: String, timeout: TimeInterval,
                        lineCallback: @escaping (String) -> Void) async throws -> CommandResult {
        let effectiveTimeout = timeout

        let cmdIdx = await ShellCommandRingBuffer.shared.didStart(command: command, sessionId: sid)

        // [T-ios-shellring-counter-leak] Balance didStart on EVERY exit path.
        // The old code called didExit only on the normal-return path below, so a
        // throw (CancellationError / kernelNotBooted) or a cancelled enclosing
        // task leaked `_runningCount` permanently — leaving the entry rendered as
        // "RUNNING" forever in crash reports and making `hasRunningCommand` a
        // one-way latch that pinned keep-alive on for the rest of the process.
        //
        // Deliberately do-catch rather than `defer { Task { … } }`: a detached
        // Task spawned from a defer during CANCELLATION is exactly the case that
        // may never be scheduled, which is the main path we need to cover. An
        // `await` on the error path is structured and always runs. `exitCode`
        // stays nil so the entry records an abort, not a fake exit status.
        let result: ISHCommandResult
        do {
            result = try await ISHExecutionCoordinator.shared.execute(
                sessionId: sid,
                command: command,
                timeout: effectiveTimeout,
                // ISHShellExecutor dispatches every line on the main queue
                // already (ISHShellExecutor.m:780/812), so we're guaranteed to
                // run on the main thread here. Calling the MainActor-isolated
                // closure synchronously via `assumeIsolated` avoids spawning a
                // fresh `Task { @MainActor in ... }` per line — that wrapper
                // used to pile up behind high-volume output (one MainActor job
                // per line) and starve other MainActor work such as
                // BrowserUseOffloadBridge's semaphore signal, causing
                // execute_js/navigate to hang inside a Python subprocess.
                lineCallback: { line in
                    MainActor.assumeIsolated { lineCallback(line) }
                },
                pidCallback: { [weak self] pid in
                    // Unlike lineCallback, pidCallback is invoked from the
                    // coordinator actor context (not the main queue), so we
                    // can't MainActor.assumeIsolated here. It only fires 1-2
                    // times per command so a Task hop is fine.
                    Task { @MainActor in
                        self?.runningCommandPid = pid
                        self?.commandStartTime = pid > 0 ? Date() : nil
                    }
                }
            )
        } catch {
            await ShellCommandRingBuffer.shared.didAbort(index: cmdIdx)
            throw error
        }

        await ShellCommandRingBuffer.shared.didExit(index: cmdIdx, exitCode: result.exitCode)

        // Fold carriage-return sequences: simulate terminal line-overwrite behaviour.
        // Tools like yt-dlp emit "\r[download] X%" to overwrite the current line; without a TTY
        // every update is captured verbatim, ballooning the output with hundreds of redundant lines.
        // We replay each \r as a real terminal would: later text on the same line overwrites earlier text,
        // so only the final state of each line is kept — matching what you would actually see on screen.
        var output = Self.sanitizeTerminalOutput(result.output)

        // Apply truncation — keep head + tail so the model sees both the beginning and end
        if output.count > Self.kMaxToolResultChars {
            let totalChars = output.count
            let totalLines = output.components(separatedBy: "\n").count
            let halfLen = Self.kMaxToolResultChars / 2
            let head = String(output.prefix(halfLen))
            let tail = String(output.suffix(halfLen))
            output = head
                + "\n\n...\n\n"
                + tail
                + "\n\n[OUTPUT TRUNCATED] Showing first & last \(halfLen) of \(totalChars) chars (\(totalLines) lines total)."
                + "\nUse file_read tool to read specific sections."
        }

        return CommandResult(output: output, exitCode: result.exitCode)
    }

    /// Sanitize raw shell output so it matches what a user would actually see on a terminal.
    ///
    /// Two passes are applied in order:
    ///
    /// **Pass 1 — carriage-return folding**
    /// A real TTY processes `\r` by moving the cursor to column 0, causing subsequent
    /// characters to overwrite what was already on that line.  Pipe-captured output has
    /// no TTY, so every `\r`-update is stored verbatim.  Tools like yt-dlp, curl, wget,
    /// and rsync can emit hundreds of progress lines that are pure noise for the model.
    /// We replay the same cursor logic: within each newline-delimited chunk, split on `\r`
    /// and keep only the last non-empty segment — the text a terminal would finally display.
    ///
    /// **Pass 2 — ANSI / VT escape sequence stripping**
    /// After CR-folding the remaining text may still contain ANSI SGR colour/style codes
    /// (e.g. `\033[1;32m`, `\033[0m`), cursor-movement sequences (`\033[A`, `\033[2K`,
    /// `\033[G`), and other CSI/OSC/ST control sequences.  None of these are meaningful
    /// as plain text; stripping them produces clean output the model can reason about.
    static func sanitizeTerminalOutput(_ raw: String) -> String {
        // ── Pass 1: carriage-return folding ──────────────────────────────────────
        let crFolded: String
        if !raw.contains("\r") {
            crFolded = raw
        } else {
            var lines: [String] = []
            for chunk in raw.components(separatedBy: "\n") {
                if !chunk.contains("\r") {
                    lines.append(chunk)
                } else {
                    // Split on \r; the last non-empty segment is what the terminal shows.
                    let segments = chunk.components(separatedBy: "\r")
                    let final = segments.last(where: { !$0.isEmpty }) ?? segments.last ?? ""
                    lines.append(final)
                }
            }
            // Collapse consecutive blank lines left by folding.
            var collapsed: [String] = []
            var blankRun = 0
            for line in lines {
                if line.isEmpty {
                    blankRun += 1
                    if blankRun <= 1 { collapsed.append(line) }
                } else {
                    blankRun = 0
                    collapsed.append(line)
                }
            }
            crFolded = collapsed.joined(separator: "\n")
        }

        // ── Pass 2: ANSI / VT escape sequence stripping ──────────────────────────
        // Covers:
        //   CSI sequences  \033[ … <final byte 0x40-0x7E>  (colours, cursor movement, erase)
        //   OSC sequences  \033] … \007  or  \033] … \033\\  (window title, hyperlinks)
        //   Single-char Fe  \033[A-Z@\[\\\]^_]  (e.g. \033M reverse index)
        //   Literal ESC     \033  (bare, not followed by anything matched above)
        guard crFolded.contains("\u{1B}") else { return crFolded }

        // Single NSRegularExpression is cheap to apply; pattern is anchored to ESC.
        let pattern = "\u{1B}(?:\\[[0-9;]*[A-Za-z@`]|\\][^\u{07}\u{1B}]*(?:\u{07}|\u{1B}\\\\)|[@-Z\\\\-_]|\u{1B})"
        guard let regex = try? NSRegularExpression(pattern: pattern) else { return crFolded }
        let range = NSRange(crFolded.startIndex..., in: crFolded)
        return regex.stringByReplacingMatches(in: crFolded, range: range, withTemplate: "")
    }

}

// MARK: - [T-mcp-approval-gate] 越狱 MCP 调用前确认

/// 每条命令对应的用途说明与风险等级（只读 / 写入）。
struct MCPCommandUsage {
    let title: String
    let purpose: String
    let risk: String
    let isWrite: Bool
}

extension AIChatViewModel {

    static let mcpMarkers = ["minis-mcp-cli", "mcp-root", "mcp-appinst", "mcp-ldid", "mcp-logreader"]

    /// 这条命令是不是在调用越狱 MCP 的那套工具。
    static func isMCPCommand(_ command: String) -> Bool {
        let lower = command.lowercased()
        return mcpMarkers.contains { lower.contains($0) }
    }

    /// 把命令翻译成"它到底要干什么"。顺序敏感：先匹配更具体的工具名。
    static func describeMCPCommand(_ command: String) -> MCPCommandUsage {
        let lower = command.lowercased()
        func has(_ s: String) -> Bool { lower.contains(s) }
        let read = { (title: String, purpose: String) in
            MCPCommandUsage(title: title, purpose: purpose,
                            risk: "只读 · 不会改动任何数据或设置", isWrite: false)
        }
        let write = { (title: String, purpose: String) in
            MCPCommandUsage(title: title, purpose: purpose,
                            risk: "写入 · 会改动设备上的文件", isWrite: true)
        }

        if has("uninstall_app") { return write("允许卸载 App？", "卸载手机上的一个 App。") }
        if has("install_app")   { return write("允许安装 App？", "在手机上安装一个 App 安装包。") }
        if has("write_file")    { return write("允许写入文件？", "往设备上的某个文件写入内容，会覆盖原有内容。") }
        if has("run_command")   { return write("允许执行终端命令？", "执行一条 shell 命令，可能读写设备文件。") }
        if has("screenshot")    { return read("允许截取屏幕？", "抓取当前屏幕画面，作为截图保存。") }
        if has("tap_screen") || has("tap_element") {
            return write("允许点击屏幕？", "在你手机上模拟一次点击，可能会操作到别的 App。")
        }
        if has("swipe_screen")  { return write("允许滑动屏幕？", "在你手机上模拟一次滑动。") }
        if has("launch_app")    { return write("允许打开 App？", "把另一个 App 切到前台。") }
        if has("press_")        { return write("允许按硬件键？", "模拟按下音量/电源/Home 等实体键。") }
        if has("set_brightness") || has("set_volume") {
            return write("允许修改系统设置？", "调整屏幕亮度或音量。")
        }
        if has("read_file")     { return read("允许读取文件？", "读取设备上的一个文件内容。") }
        if has("list_dir")      { return read("允许列出目录？", "查看某个文件夹里有哪些文件。") }
        if has("get_syslog")    { return read("允许读取系统日志？", "抓取一段实时系统日志。") }
        if has("crash_log")     { return read("允许读取崩溃日志？", "读取 App 的崩溃报告。") }
        if has("get_app_info") || has("list_apps") {
            return read("允许读取 App 信息？", "查看已安装 App 的列表或详情。")
        }
        return MCPCommandUsage(title: "允许调用越狱 MCP？",
                               purpose: "执行一条越狱环境下的操作。",
                               risk: "可能改动设备，请确认命令内容",
                               isWrite: true)
    }

    /// 命令执行前的闸门。返回 false = 用户拒绝，调用方必须中止。
    func mcpApprovalGateAllows(_ command: String) async -> Bool {
        guard Self.isMCPCommand(command) else { return true }
        // [T-mcp-approval-safety] 默认关闭：这个弹窗曾多次把整屏挡住点不动，
        // 先默认不弹；要用的人自己去设置里打开。
        let enabled = (UserDefaults.standard.object(forKey: "permissions.mcpApprovalGate") as? Bool) ?? false
        guard enabled else { return true }
        let usage = Self.describeMCPCommand(command)
        return await MCPApprovalDialog.present(usage: usage, command: command)
    }
}

// MARK: - 弹窗

/// [T-mcp-approval-gate] 自绘确认弹窗：标题居中，正文与命令块左边缘对齐，
/// 只有「拒绝 / 允许」，不记忆任何选择。
final class MCPApprovalDialog: UIViewController {
    /// [T-mcp-approval-safety] 同一时间只允许一个审批弹窗，避免多个叠在一起
    /// 关不干净、留下挡住整屏的暗色遮罩。
    private static weak var current: MCPApprovalDialog?
    /// 超时兜底：没人点就按拒绝处理，绝不把界面锁死。
    private var timeoutWork: DispatchWorkItem?

    private let usage: MCPCommandUsage
    private let commandText: String
    private var finish: ((Bool) -> Void)?

    init(usage: MCPCommandUsage, command: String) {
        self.usage = usage
        self.commandText = command
        super.init(nibName: nil, bundle: nil)
        modalPresentationStyle = .overFullScreen
        modalTransitionStyle = .crossDissolve
    }

    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }

    /// [T-mcp-approval-safety] 回到前台时清掉"没人等的"遮罩：如果弹窗还在但
    /// 已经没有任何调用在等它（那一轮早结束了），它挡住整屏就是纯 bug。
    private static var cleanupInstalled = false
    static func installForegroundCleanup() {
        guard !cleanupInstalled else { return }
        cleanupInstalled = true
        NotificationCenter.default.addObserver(forName: UIApplication.didBecomeActiveNotification,
                                               object: nil, queue: .main) { _ in
            DispatchQueue.main.async {
                guard let dlg = MCPApprovalDialog.current else { return }
                if dlg.finish == nil {
                    dlg.dismiss(animated: false)
                    MCPApprovalDialog.current = nil
                }
            }
        }
    }

    @MainActor
    static func present(usage: MCPCommandUsage, command: String) async -> Bool {
        installForegroundCleanup()
        return await withCheckedContinuation { (cont: CheckedContinuation<Bool, Never>) in
            let scenes = UIApplication.shared.connectedScenes.compactMap { $0 as? UIWindowScene }
            guard var top = scenes.flatMap({ $0.windows }).first(where: { $0.isKeyWindow })?.rootViewController else {
                cont.resume(returning: false)
                return
            }
            while let presented = top.presentedViewController, !presented.isBeingDismissed {
                top = presented
            }
            // 已有弹窗在等 → 直接拒绝这一次，免得两个遮罩叠着关不掉。
            if MCPApprovalDialog.current != nil {
                cont.resume(returning: false)
                return
            }
            let dialog = MCPApprovalDialog(usage: usage, command: command)
            MCPApprovalDialog.current = dialog
            dialog.finish = { ok in
                MCPApprovalDialog.current = nil
                cont.resume(returning: ok)
            }
            top.present(dialog, animated: false)
            // 60 秒没人理 → 自动拒绝并关闭，防止界面被遮罩锁死。
            let work = DispatchWorkItem { [weak dialog] in dialog?.close(false) }
            dialog.timeoutWork = work
            DispatchQueue.main.asyncAfter(deadline: .now() + 60, execute: work)
        }
    }

    private let dim = UIView()
    private let card = UIView()

    override func viewDidDisappear(_ animated: Bool) {
        super.viewDidDisappear(animated)
        // 被系统强制移除（例如父控制器消失）时，也要把等待方放行，避免挂死。
        if let done = finish {
            finish = nil
            timeoutWork?.cancel()
            MCPApprovalDialog.current = nil
            done(false)
        }
    }

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        dim.backgroundColor = UIColor.black.withAlphaComponent(0.45)
        dim.frame = view.bounds
        dim.autoresizingMask = [.flexibleWidth, .flexibleHeight]
        // 点遮罩 = 拒绝（而不是什么都不做）：万一有异常，也不会把界面锁死。
        dim.addGestureRecognizer(UITapGestureRecognizer(target: self, action: #selector(dimTapped)))
        view.addSubview(dim)

        card.backgroundColor = UIColor(white: 0.17, alpha: 1)
        card.layer.cornerRadius = 16
        card.layer.cornerCurve = .continuous
        card.clipsToBounds = true
        view.addSubview(card)
        build()
    }

    private func label(_ text: String, size: CGFloat, weight: UIFont.Weight = .regular,
                       color: UIColor, lines: Int = 0) -> UILabel {
        let l = UILabel()
        l.text = text
        l.font = UIFont.systemFont(ofSize: size, weight: weight)
        l.textColor = color
        l.numberOfLines = lines
        return l
    }

    private func build() {
        let pad: CGFloat = 18
        let stack = UIStackView()
        stack.axis = .vertical
        stack.spacing = 6
        stack.translatesAutoresizingMaskIntoConstraints = false

        let title = label(usage.title, size: 16, weight: .semibold, color: .white)
        title.textAlignment = .center
        stack.addArrangedSubview(title)
        stack.setCustomSpacing(12, after: title)

        let tool = label(toolLine(), size: 11, color: UIColor(white: 0.68, alpha: 1), lines: 1)
        stack.addArrangedSubview(tool)

        stack.addArrangedSubview(label(usage.purpose, size: 12, color: .white))
        stack.addArrangedSubview(label(usage.risk, size: 11,
                                       color: usage.isWrite ? UIColor.systemOrange : UIColor(white: 0.62, alpha: 1)))

        // 命令块：左侧 3pt 竖条 + 等宽文字，左边缘与上面文字对齐
        let cmdRow = UIView()
        let bar = UIView()
        bar.backgroundColor = UIColor(red: 0.35, green: 0.47, blue: 0.63, alpha: 1)
        bar.layer.cornerRadius = 1.5
        bar.translatesAutoresizingMaskIntoConstraints = false
        cmdRow.addSubview(bar)

        let cmd = label(truncatedCommand(), size: 10, color: UIColor(red: 0.75, green: 0.86, blue: 1, alpha: 1))
        cmd.font = UIFont.monospacedSystemFont(ofSize: 10, weight: .regular)
        cmd.translatesAutoresizingMaskIntoConstraints = false
        cmdRow.addSubview(cmd)

        let hint = label("将在你的设备上执行", size: 10, color: UIColor(white: 0.55, alpha: 1))
        hint.translatesAutoresizingMaskIntoConstraints = false
        cmdRow.addSubview(hint)

        NSLayoutConstraint.activate([
            bar.leadingAnchor.constraint(equalTo: cmdRow.leadingAnchor),
            bar.topAnchor.constraint(equalTo: cmdRow.topAnchor),
            bar.bottomAnchor.constraint(equalTo: cmdRow.bottomAnchor),
            bar.widthAnchor.constraint(equalToConstant: 3),
            cmd.leadingAnchor.constraint(equalTo: bar.trailingAnchor, constant: 12),
            cmd.trailingAnchor.constraint(equalTo: cmdRow.trailingAnchor),
            cmd.topAnchor.constraint(equalTo: cmdRow.topAnchor),
            hint.leadingAnchor.constraint(equalTo: cmd.leadingAnchor),
            hint.topAnchor.constraint(equalTo: cmd.bottomAnchor, constant: 6),
            hint.bottomAnchor.constraint(equalTo: cmdRow.bottomAnchor)
        ])
        stack.setCustomSpacing(10, after: stack.arrangedSubviews.last!)
        stack.addArrangedSubview(cmdRow)

        card.addSubview(stack)
        NSLayoutConstraint.activate([
            stack.leadingAnchor.constraint(equalTo: card.leadingAnchor, constant: pad),
            stack.trailingAnchor.constraint(equalTo: card.trailingAnchor, constant: -pad),
            stack.topAnchor.constraint(equalTo: card.topAnchor, constant: 18)
        ])

        // 按钮行
        let buttons = UIStackView()
        buttons.axis = .horizontal
        buttons.distribution = .fillEqually
        buttons.translatesAutoresizingMaskIntoConstraints = false
        let line = UIView()
        line.backgroundColor = UIColor(white: 0.30, alpha: 1)
        line.translatesAutoresizingMaskIntoConstraints = false
        let vline = UIView()
        vline.backgroundColor = UIColor(white: 0.30, alpha: 1)
        vline.translatesAutoresizingMaskIntoConstraints = false

        let reject = button("拒绝", bold: false) { [weak self] in self?.close(false) }
        let allow = button("允许", bold: true) { [weak self] in self?.close(true) }
        buttons.addArrangedSubview(reject)
        buttons.addArrangedSubview(allow)

        card.addSubview(line)
        card.addSubview(vline)
        card.addSubview(buttons)

        NSLayoutConstraint.activate([
            line.leadingAnchor.constraint(equalTo: card.leadingAnchor),
            line.trailingAnchor.constraint(equalTo: card.trailingAnchor),
            line.topAnchor.constraint(equalTo: stack.bottomAnchor, constant: 16),
            line.heightAnchor.constraint(equalToConstant: 0.5),

            buttons.topAnchor.constraint(equalTo: line.bottomAnchor),
            buttons.leadingAnchor.constraint(equalTo: card.leadingAnchor),
            buttons.trailingAnchor.constraint(equalTo: card.trailingAnchor),
            buttons.heightAnchor.constraint(equalToConstant: 44),
            buttons.bottomAnchor.constraint(equalTo: card.bottomAnchor),

            vline.widthAnchor.constraint(equalToConstant: 0.5),
            vline.centerXAnchor.constraint(equalTo: card.centerXAnchor),
            vline.topAnchor.constraint(equalTo: line.bottomAnchor),
            vline.bottomAnchor.constraint(equalTo: card.bottomAnchor),

            card.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            card.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            card.widthAnchor.constraint(equalToConstant: 292)
        ])
    }

    private func button(_ title: String, bold: Bool, action: @escaping () -> Void) -> UIButton {
        let b = UIButton(type: .system)
        b.setTitle(title, for: .normal)
        b.titleLabel?.font = UIFont.systemFont(ofSize: 16, weight: bold ? .semibold : .regular)
        b.setTitleColor(UIColor(red: 0.04, green: 0.52, blue: 1, alpha: 1), for: .normal)
        b.addAction(UIAction { _ in action() }, for: .touchUpInside)
        return b
    }

    private func toolLine() -> String {
        let parts = commandText.split(separator: " ")
        if let idx = parts.firstIndex(where: { $0.lowercased().contains("minis-mcp-cli") }) {
            let rest = parts.dropFirst(idx + 1).prefix(3).joined(separator: " ")
            return "越狱 mcp · " + rest
        }
        return "越狱 mcp"
    }

    private func truncatedCommand() -> String {
        let one = commandText.replacingOccurrences(of: "\n", with: " ")
        return one.count > 90 ? String(one.prefix(90)) + "…" : one
    }

    @objc private func dimTapped() { close(false) }

    private func close(_ allowed: Bool) {
        guard let done = finish else { return }   // 幂等：重复调用不重复 resume
        finish = nil
        timeoutWork?.cancel()
        timeoutWork = nil
        MCPApprovalDialog.current = nil
        dismiss(animated: false) { done(allowed) }
    }
}
