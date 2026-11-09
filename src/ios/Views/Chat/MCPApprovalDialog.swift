import Foundation
import UIKit

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

    /// Extract the shell command inside `run_command command='…'` so the
    /// approval describes the real effect rather than the MCP relay syntax.
    nonisolated private static func effectiveMCPCommand(_ command: String) -> String {
        let lower = command.lowercased()
        guard let marker = lower.range(of: "command=") else { return command }
        var value = String(command[marker.upperBound...])
            .trimmingCharacters(in: .whitespacesAndNewlines)
        if let first = value.first, first == "'" || first == "\"" {
            let body = value.dropFirst()
            if let end = body.lastIndex(of: first) {
                value = String(body[..<end])
            }
        }
        return value
    }

    /// Translate a tool call into its concrete device effect. Raw shell text
    /// is deliberately not shown in the approval card.
    nonisolated static func describeMCPCommand(_ command: String) -> MCPCommandUsage {
        let lower = command.lowercased()
        let inner = effectiveMCPCommand(command).lowercased()
        let text = lower + "\n" + inner
        func has(_ s: String) -> Bool { text.contains(s) }
        let read = { (title: String, purpose: String) in
            MCPCommandUsage(title: title, purpose: purpose,
                            risk: "只读 · 不会改动任何数据或设置", isWrite: false)
        }
        let write = { (title: String, purpose: String) in
            MCPCommandUsage(title: title, purpose: purpose,
                            risk: "写入 · 会改动设备上的文件或系统状态", isWrite: true)
        }

        if has("reboot userspace") || has("launchctl reboot") {
            return write("允许重启用户空间？", "重启 SpringBoard/用户空间，当前界面和插件会暂时中断。")
        }
        if has("cn.zgbb.inject.system.plist") && has("pkdx") {
            return write("允许修改 RootHide 注入配置？", "备份并修改注入配置中的 /pkdx 标记，可能改变对应插件的加载行为。")
        }
        if has("uninstall_app") { return write("允许卸载 App？", "从手机中移除指定应用。") }
        if has("install_app") { return write("允许安装 App？", "在手机上安装指定应用包。") }
        if has("screenshot") { return read("允许截屏？", "读取当前屏幕画面并返回截图。") }
        if has("tap_screen") || has("tap_element") {
            return write("允许点击屏幕？", "模拟点击，可能触发当前界面上的按钮。")
        }
        if has("swipe_screen") { return write("允许滑动屏幕？", "模拟一次屏幕滑动。") }
        if has("record_screen") || has("start_recording") || has("record") {
            return write("允许录屏？", "录制设备屏幕画面。")
        }
        if has("launch_app") { return write("允许打开 App？", "把指定应用切到前台。") }
        if has("press_") { return write("允许模拟按键？", "触发指定的系统按键操作。") }
        if has("set_brightness") || has("set_volume") {
            return write("允许修改系统设置？", "调整屏幕亮度或音量。")
        }
        if has("get_syslog") { return read("允许读取系统日志？", "读取设备系统日志内容。") }
        if has("crash_log") { return read("允许读取崩溃日志？", "读取 App 的崩溃报告。") }
        if has("get_app_info") || has("list_apps") {
            return read("允许读取 App 信息？", "查看已安装 App 的列表或详情。")
        }
        if has("list_dir") { return read("允许查看目录？", "列出指定文件夹中的项目。") }
        if has("read_file") || has("grep ") || has("tail ") || has("cat ") {
            return read("允许读取文件或日志？", "读取指定文件内容，不会修改文件。")
        }
        if has("write_file") || has("edit_file") || has("sed -i") || has("plutil") {
            return write("允许写入或修改文件？", "在设备文件系统中创建或更改文件。")
        }
        if has("cp ") { return write("允许复制文件？", "把文件复制到另一条路径。") }
        if has("mv ") { return write("允许移动或重命名文件？", "更改文件路径或名称。") }
        if has("rm ") { return write("允许删除文件？", "移除指定文件或目录。") }
        if has("curl ") || has("wget ") {
            return read("允许发起网络请求？", "连接网络读取或下载数据。")
        }
        return write("允许执行设备命令？", "这条命令的具体作用无法自动归类，请确认后再执行。")
    }

    /// 命令执行前的闸门。返回 false = 用户拒绝，调用方必须中止。
    func mcpApprovalGateAllows(_ command: String) async -> Bool {
        guard Self.isMCPCommand(command) else { return true }
        // 由「允许 AI 操作手机」总开关控制；打开后每条危险命令都要确认。
        guard HostAccessPermission.isEnabled else { return false }
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
    /// Dedicated alert window. The dialog is never presented on an arbitrary
    /// view controller, so it cannot land on an off-screen presenter.
    private var hostWindow: UIWindow?

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
            guard let scene = scenes.first(where: { $0.activationState == .foregroundActive }) ?? scenes.first else {
                cont.resume(returning: false)
                return
            }
            // 已有弹窗在等 → 直接拒绝这一次，免得两个遮罩叠着关不掉。
            if MCPApprovalDialog.current != nil {
                cont.resume(returning: false)
                return
            }
            let dialog = MCPApprovalDialog(usage: usage, command: command)
            MCPApprovalDialog.current = dialog
            // Dedicated window: its root IS the dialog, so there is no
            // presentation chain to fail on. Hiding it removes the dim view
            // in the same step, which is what makes the old lock-up impossible.
            let window = UIWindow(windowScene: scene)
            window.windowLevel = .alert + 1
            window.rootViewController = dialog
            dialog.hostWindow = window
            dialog.finish = { ok in
                MCPApprovalDialog.current = nil
                cont.resume(returning: ok)
            }
            window.makeKeyAndVisible()
            // 60 秒没人理 → 自动拒绝并关闭，防止界面被遮罩锁死。
            let work = DispatchWorkItem { [weak dialog] in dialog?.close(false) }
            dialog.timeoutWork = work
            DispatchQueue.main.asyncAfter(deadline: .now() + 60, execute: work)
        }
    }

    /// Confirm a dangerous MCP command from the tool loop.
    @MainActor
    static func confirm(_ command: String) async -> Bool {
        await present(usage: AIChatViewModel.describeMCPCommand(command), command: command)
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
        // Root cause of the invisible-but-touch-blocking dialog: the card
        // used Auto Layout without opting out of its autoresizing mask, so
        // its frame solved to 0x0 while the full-screen dim view still ate
        // every touch.
        card.translatesAutoresizingMaskIntoConstraints = false
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
        let window = hostWindow
        hostWindow = nil
        window?.isHidden = true
        window?.rootViewController = nil
        // Hand key status back to the app's own window.
        if let fallback = UIApplication.shared.connectedScenes
            .compactMap({ $0 as? UIWindowScene })
            .flatMap({ $0.windows })
            .first(where: { !$0.isHidden && $0 !== window }) {
            fallback.makeKey()
        }
        done(allowed)
    }
}
