import SwiftUI
import Combine

// MARK: - Assistant Block View (individual block — isolated invalidation)

struct AssistantBlockView: View {
    @ObservedObject var block: AssistantBlock
    @ObservedObject var message: ChatMessage
    let isActiveMessage: Bool
    var commandStartTime: Date?
    var onStop: (() -> Void)?
    var onTapBlank: ((CGPoint) -> Void)?
    var onCopyScreenshot: (() -> Void)?
    /// [T-selection-menu-minis-tts] Selection-menu read-aloud hooks, plumbed
    /// down to SelectableMarkdownView (nil for non-text or streaming contexts).
    var onReadAloud: (() -> Void)?
    var onSpeakText: ((String) -> Void)?
    var browserPool: BrowserTabPool?
    var toolSnapshots: [ToolSnapshotItem] = []
    @Binding var highlightedBlockId: UUID?
    @Binding var detailBlock: AssistantBlock?
    private var isHighlighted: Bool { highlightedBlockId == block.id }

    var body: some View {
        switch block.kind {
        case .text:
            let hasVisibleText = !block.content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            if hasVisibleText {
                textBlockView
                    .padding(.vertical, 2)
                    .background(
                        RoundedRectangle(cornerRadius: 8)
                            .fill(ChatColors.accent.opacity(isHighlighted ? 0.10 : 0))
                    )
            }
        case .thinking:
            ThinkingBlockView(
                block: block,
                isStreaming: isActiveMessage && message.blocks.last?.id == block.id
            )
            .id(block.id) // Never carry frozen scroll/text @State into a reused block.
            .padding(.vertical, 2)
        case .shellTool:
            ToolCapsuleView(block: block, icon: "terminal", accentColor: .green,
                            commandStartTime: commandStartTime, onStop: onStop, browserPool: browserPool,
                            toolSnapshots: toolSnapshots, detailBlock: $detailBlock)
        case .fileReadTool:
            ToolCapsuleView(block: block, icon: "doc.text", accentColor: .cyan,
                            commandStartTime: commandStartTime, onStop: onStop,
                            toolSnapshots: toolSnapshots, detailBlock: $detailBlock)
        case .fileWriteTool:
            ToolCapsuleView(block: block, icon: "doc.text.fill", accentColor: .blue,
                            commandStartTime: commandStartTime, onStop: onStop,
                            toolSnapshots: toolSnapshots, detailBlock: $detailBlock)
        case .fileEditTool:
            ToolCapsuleView(block: block, icon: "square.and.pencil", accentColor: .orange,
                            commandStartTime: commandStartTime, onStop: onStop,
                            toolSnapshots: toolSnapshots, detailBlock: $detailBlock)
        case .browserTool:
            ToolCapsuleView(block: block, icon: "globe", accentColor: .blue,
                            commandStartTime: commandStartTime, onStop: onStop, browserPool: browserPool,
                            toolSnapshots: toolSnapshots, detailBlock: $detailBlock)
        case .readImageTool:
            ToolCapsuleView(block: block, icon: "photo", accentColor: .purple,
                            commandStartTime: commandStartTime, onStop: onStop,
                            toolSnapshots: toolSnapshots, detailBlock: $detailBlock)
        case .memoryTool:
            ToolCapsuleView(block: block, icon: "brain.head.profile", accentColor: .pink,
                            commandStartTime: commandStartTime, onStop: onStop,
                            toolSnapshots: toolSnapshots, detailBlock: $detailBlock)
        case .delegateTool:
            if HelperBlockInfo.controlSummary(block) != nil {
                // [T-subagent-control-capsule] A status / steer / cancel /
                // resume call is the model operating on its own sub agents —
                // a tool call like any other, so it gets the ordinary tool
                // capsule rather than a bespoke row.
                //
                // The first cut was a centred grey line. It read as a section
                // divider rather than an action, said nothing about WHAT was
                // sent, could not be opened, and its own vertical padding made
                // it taller than the capsules around it. The shared capsule
                // fixes all four at once: same metrics as every other tool, a
                // tappable detail sheet carrying the full arguments and result,
                // and the sub agent accent so it still reads as agent work.
                ToolCapsuleView(block: block, icon: "slider.horizontal.3",
                                accentColor: HelperAccent.color,
                                commandStartTime: commandStartTime, onStop: onStop,
                                toolSnapshots: toolSnapshots, detailBlock: $detailBlock)
            } else {
                // [T-p2-helper-block-render] Own view: status / tier / elapsed /
                // summary instead of the generic capsule's raw content.
                HelperBlockView(block: block, detailBlock: $detailBlock)
            }
        case .questionCard:
            // [T-115-ask-card] Inline question/confirmation card. Interactive
            // while the vm still holds the matching active card; read-only
            // (answer summary / unconfirmed) otherwise.
            QuestionCardView(block: block)
                .padding(.vertical, 2)
        case .info:
            let allLines = block.content.components(separatedBy: "\n").filter { !$0.isEmpty }
            // Separate reason lines (⚠️) from the final switched line (✅)
            let reasonLines = allLines.filter { $0.hasPrefix("⚠️") }
            let switchedLine = allLines.first { !$0.hasPrefix("⚠️") && !$0.isEmpty }
            // Truncate middle if more than 9 reason lines
            let displayReasons: [String] = {
                if reasonLines.count <= 9 { return reasonLines }
                return Array(reasonLines.prefix(4)) + [AppLocalized("⋯ \(reasonLines.count - 8) more")] + Array(reasonLines.suffix(4))
            }()
            VStack(alignment: .leading, spacing: 3) {
                ForEach(Array(displayReasons.enumerated()), id: \.offset) { _, line in
                    Text(line)
                        .font(.system(size: 10))
                        .foregroundStyle(ChatColors.primaryText.opacity(0.45))
                        .lineLimit(2)
                }
                if let switchedLine {
                    HStack(spacing: 5) {
                        Image(systemName: "arrow.triangle.2.circlepath")
                            .font(.system(size: 10, weight: .semibold))
                            .foregroundStyle(.orange.opacity(0.8))
                        Text(switchedLine)
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(ChatColors.primaryText.opacity(0.75))
                            .lineLimit(2)
                    }
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(.horizontal, 10)
            .padding(.vertical, 7)
            .background(Color.orange.opacity(0.08))
            .clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.orange.opacity(0.14), lineWidth: 0.5))
            .contextMenu (menuItems: {
                Button {
                    UIPasteboard.general.string = block.content
                } label: {
                    Label(AppLocalized("Copy Error"), systemImage: "doc.on.doc")
                }
            })
        }
    }

    @ViewBuilder
    private var textBlockView: some View {
        SelectableMarkdownView(
            markdown: block.content,
            cachedContent: block.cachedMarkdown,
            cachedAttributedString: block.cachedAttributedString,
            messageId: message.id,
            blockId: block.id,
            onTapBlank: onTapBlank,
            onCopyScreenshot: onCopyScreenshot,
            onReadAloud: onReadAloud,
            onSpeakText: onSpeakText
        )
        .fixedSize(horizontal: false, vertical: true)
        .modifier(MinisOpenURLHandler())
    }
}

// MARK: - Shimmer Overlay (continuous diagonal shine via offset animation)

/// A diagonal shimmer band that sweeps from top-leading to bottom-trailing.
/// Uses a single stable gradient with an animated offset rather than rebuilding
/// gradient stops every frame — avoids a CAGradientLayer colorspace teardown
/// race during CATransaction flush (EXC_BAD_ACCESS at encode_colorspace).
struct ShimmerOverlay: View {
    @Environment(\.colorScheme) private var colorScheme
    @State private var offsetX: CGFloat = -1.0

    // [V568-SHIMMER] 亮条的**行程**, 单位 pt。
    // ★这一行是本版全部修复的支点。旧代码写的是 `offsetX * geo.size.width` ——
    //   动画目标里含布局量。于是 body 每重算一次(流式 chunk / cell 复用),
    //   geo.size 就变, @State animation 就从「当前呈现值」重新 ease 到新目标,
    //   正在跑的 repeatForever 被**打断**: 亮条停在半路或跳到另一半。
    //   用户看到的正是「卡一下才显示」+「卡一半一半显示」。
    // 现在目标只依赖 offsetX 一个 @State ⇒ body 怎么重算都不打断动画。
    private static let travel: CGFloat = 600

    private var peakOpacity: CGFloat {
        colorScheme == .light ? 0.75 : 0.25
    }

    private func bell(_ x: CGFloat) -> CGFloat {
        exp(-4.5 * x * x)
    }

    private var stableStops: [Gradient.Stop] {
        let stepCount = 12
        let bandRadius: CGFloat = 0.40
        let center: CGFloat = 0.5
        var stops: [Gradient.Stop] = []
        stops.append(.init(color: .white.opacity(0), location: 0))
        for i in 0...stepCount {
            let frac = CGFloat(i) / CGFloat(stepCount)
            let pos = center - bandRadius + frac * bandRadius * 2.0
            let dist = (pos - center) / bandRadius
            let alpha = bell(dist) * peakOpacity
            stops.append(.init(color: .white.opacity(Double(alpha)), location: pos))
        }
        stops.append(.init(color: .white.opacity(0), location: 1))
        return stops
    }

    var body: some View {
        // [V568-SHIMMER] GeometryReader **保留**: 亮条本身要铺满 capsule 的
        // 宽度, 那是真实布局量。但它**不再进入 offset 的目标**。
        GeometryReader { geo in
            let diag = geo.size.width + geo.size.height
            Rectangle()
                .fill(
                    LinearGradient(
                        stops: stableStops,
                        startPoint: UnitPoint(x: 0, y: 1),
                        endPoint: UnitPoint(x: 1, y: 0)
                    )
                )
                .frame(width: diag, height: geo.size.height)
                // [V568-SHIMMER] ★只乘固定行程, 不乘 geo.size.width。
                // 视觉等价: 旧版从 -W 扫到 +W(总 2W); 新版从 -travel 扫到
                // +travel。travel 取 600pt 足以覆盖 iPhone 上最宽的 capsule,
                // 且是**编译期常量** ⇒ 动画目标与布局彻底解耦。
                .offset(x: offsetX * Self.travel)
                .onAppear {
                    withAnimation(
                        .linear(duration: 2.8)
                        .repeatForever(autoreverses: false)
                    ) {
                        offsetX = 1.0
                    }
                }
        }
        .clipped()
    }
}

// MARK: - Tool Capsule View (unified pill for all tool types)

struct ToolCapsuleView: View {
    @ObservedObject var block: AssistantBlock
    let icon: String
    let accentColor: Color
    var commandStartTime: Date?
    var onStop: (() -> Void)?
    var browserPool: BrowserTabPool?
    var toolSnapshots: [ToolSnapshotItem] = []
    @Binding var detailBlock: AssistantBlock?
    @State private var dotsActive = false
    /// [T-tool-bg-suspended-hint] Drives the background-suspension info alert.
    @State private var showBgHintAlert = false
    /// [T-ios-memory-write-revoke] Confirmation + result alerts for undoing a
    /// memory_write straight from the tool capsule's long-press menu.
    @State private var showRevokeMemoryAlert = false
    @State private var revokeMemoryResult: String?
    @State private var showRevokeMemoryResultAlert = false
    @ObservedObject private var keepAlive = BackgroundKeepAliveManager.shared

    /// Show the yellow ⓘ hint only when this tool was flagged as background-
    /// suspended AND enhanced background isn't already effective (nothing to
    /// suggest if it's on). Mirrors the BackgroundInterruptionTracker gate.
    private var showBgSuspendedHint: Bool {
        block.wasBackgroundSuspended && !keepAlive.enhancedBackgroundEffective
    }
    /// [T-ios-retry-hide-when-processing] Used to suppress the "Re-run From
    /// Here" long-press menu item while the agent loop is busy — tapping it
    /// mid-run would corrupt the in-flight processing state.
    @EnvironmentObject private var vm: AIChatViewModel

    /// [T-ios-memory-write-revoke] Whether this block is a `memory_write` that
    /// carries input args at all — the cheap check that decides whether the Undo
    /// menu item is offered. Deliberately does NOT parse the JSON: this feeds
    /// `ToolMenuKey`, which is rebuilt on every eager body pass, and re-running
    /// `JSONSerialization` there is exactly the per-frame work the menu gate
    /// exists to avoid. Other tools and `memory_get` never match.
    private var isRevocableMemoryWrite: Bool {
        guard case .memoryTool(let action) = block.kind, action == "memory_write" else { return false }
        guard let args = block.toolInputArgs else { return false }
        return !args.isEmpty
    }

    /// The text this block wrote to memory. Parsed lazily — only when the menu
    /// item is actually tapped — same treatment as `toolDetailsClipboard`.
    /// Nil when the args carry no non-empty `content` (e.g. a malformed or
    /// still-streaming tool call), which the confirm action treats as a no-op.
    private var memoryWriteContent: String? {
        guard case .memoryTool(let action) = block.kind, action == "memory_write" else { return nil }
        return MemoryWriteRevoker.writtenContent(fromToolInputArgs: block.toolInputArgs)
    }

    /// Display text: prefer LLM-generated toolSummary, fall back to toolDescription.
    private var displayText: String {
        // [T-subagent-control-capsule] A control call describes itself from the
        // action it performed ("Resumed 2 sub agent(s)"), which is the whole
        // point of the row. Its `tool_title` names the RUN it acted on, so
        // preferring the summary here would label three different operations
        // on the same sub agent identically.
        if let control = HelperBlockInfo.controlSummary(block) { return control }
        if let summary = block.toolSummary, !summary.isEmpty {
            return summary
        }
        return block.toolDescription
    }

    /// [T-ios-tool-bubble-longpress-menu] Human-readable, paste-back-able
    /// dump of this tool call + its result for the "Copy Tool Details"
    /// menu action. Pulls tool name from the block kind, the input JSON
    /// from toolInputArgs (pretty-printed when it parses), and the result
    /// text + status from the block's content / toolStatus (with the
    /// snapshot text as a fallback source).
    private var toolDetailsClipboard: String {
        // Tool name from the block kind.
        let toolName: String
        switch block.kind {
        case .shellTool:     toolName = "shell_execute"
        case .fileReadTool:  toolName = "file_read"
        case .fileWriteTool: toolName = "file_write"
        case .fileEditTool:  toolName = "file_edit"
        case .browserTool:   toolName = "browser_use"
        case .readImageTool: toolName = "read_image"
        case .memoryTool:    toolName = "memory"
        case .delegateTool:  toolName = SubAgentDefinition.toolName
        case .text, .thinking, .info, .questionCard: toolName = "unknown"
        }

        // Pretty-print the input JSON when possible; otherwise emit raw.
        let inputBlock: String
        if let raw = block.toolInputArgs, !raw.isEmpty {
            if let data = raw.data(using: .utf8),
               let obj = try? JSONSerialization.jsonObject(with: data),
               let pretty = try? JSONSerialization.data(withJSONObject: obj, options: [.prettyPrinted, .sortedKeys]),
               let prettyStr = String(data: pretty, encoding: .utf8) {
                inputBlock = prettyStr
            } else {
                inputBlock = raw
            }
        } else {
            inputBlock = "(no input captured)"
        }

        // Result text: prefer the live block content, fall back to the
        // snapshot text matched by toolUseId.
        var resultText = block.content
        if resultText.isEmpty, let tuId = block.toolUseId,
           let snap = toolSnapshots.first(where: { $0.id == tuId }) {
            resultText = snap.snapshot.text ?? ""
        }
        let hasScreenshot = block.imageFilePath != nil
            || (block.toolUseId.flatMap { tuId in toolSnapshots.first(where: { $0.id == tuId }) }?.snapshot.type == .image)

        // Status string.
        let statusStr: String
        switch block.toolStatus {
        case .success:   statusStr = "success"
        case .failed:    statusStr = "failed"
        case .cancelled: statusStr = "cancelled"
        case .running:   statusStr = "running"
        case .streaming: statusStr = "streaming"
        case .none:      statusStr = "unknown"
        }

        var resultMeta = "(\(resultText.count) chars, \(statusStr)"
        if hasScreenshot { resultMeta += ", screenshot" }
        resultMeta += ")"

        return """
        ## Tool Call
        name: \(toolName)
        id: \(block.toolUseId ?? "(none)")
        input:
        \(inputBlock)

        ## Tool Result
        \(resultMeta)
        \(resultText)
        """
    }

    private var isStreaming: Bool {
        if case .streaming = block.toolStatus { return true }
        return false
    }

    private var isActive: Bool {
        switch block.toolStatus {
        case .streaming, .running: return true
        default: return false
        }
    }

    var body: some View {
        HStack {
            HStack(spacing: 8) {
                // Status indicator / icon
                statusOrIcon

                // Description text with bouncing dots during streaming
                HStack(spacing: 0) {
                    Text(displayText)
                        .font(.system(size: 13, weight: .medium))
                        // [T-subagent-control-capsule] Sub agent control calls
                        // title in the accent, every other tool in the normal
                        // text colour.
                        //
                        // Elsewhere the accent lives only on the icon, which is
                        // enough when the title names a file or a command — the
                        // text itself is the content. A control call's title IS
                        // the operation ("Sent a course correction"), and it
                        // belongs to the sub agent world the purple identifies;
                        // leaving it in the default colour made these read as
                        // ordinary tool calls that happened to have a purple
                        // glyph, which is what the report is about.
                        .foregroundStyle(isSubAgentControl ? accentColor : ChatColors.primaryText)
                        .lineLimit(1)
                    if isStreaming {
                        ForEach(0..<3, id: \.self) { i in
                            Text(".")
                                .font(.system(size: 13, weight: .medium))
                                .foregroundStyle(ChatColors.primaryText)
                                .offset(y: dotsActive ? -2 : 1)
                                .animation(
                                    .easeInOut(duration: 0.35)
                                        .repeatForever(autoreverses: true)
                                        .delay(Double(i) * 0.12),
                                    value: dotsActive
                                )
                        }
                    }
                }
                .lineLimit(1)

                // Execution duration (shown after completion). The HH:mm:ss
                // start time is surfaced inside the detail view's bottom bar
                // (ToolLiveSheet.bottomBar) instead of here — the inline
                // pill list stays clean.
                if let dur = durationText {
                    Text(dur)
                        .font(.system(size: 11, weight: .regular, design: .monospaced))
                        .foregroundStyle(ChatColors.tertiaryText)
                }

                // Stop button for running commands
                if case .running = block.toolStatus {
                    Button {
                        onStop?()
                    } label: {
                        // Visual: 10×10 red square unchanged. Hit area enlarged to
                        // 24×24 via an expanded contentShape, while the negative
                        // padding pins the *layout* footprint back to 18×18 so the
                        // capsule width/height is identical to before.
                        RoundedRectangle(cornerRadius: 2)
                            .fill(.red)
                            .frame(width: 10, height: 10)
                            .frame(width: 24, height: 24)
                            .contentShape(Rectangle())
                            .padding(-3)
                    }
                    .buttonStyle(.plain)
                }
            }
            .padding(.horizontal, 12)
            .frame(height: 36)
            // [V568-SHIMMER] 固定 36pt 已是上游既有约定(cell 估算也按 36),
            // 这里只**显式钉住高度**, 让 ShimmerOverlay 的 GeometryReader 拿到
            // 稳定尺寸。★不改任何视觉: 上游 .frame(height: 36) 本来就是它。
            .frame(height: 36)
            .background(Color(UIColor.systemGray6))
            .clipShape(Capsule())
            .overlay(
                Group {
                    if isActive {
                        ShimmerOverlay()
                            .clipShape(Capsule())
                            .allowsHitTesting(false)
                    }
                }
            )
            .overlay(
                Capsule()
                    .stroke(ChatColors.toolBorder, lineWidth: 0.5)
            )
            .contentShape(Capsule())
            .onTapGesture {
                detailBlock = block
            }
            .contextMenu (menuItems: {
                // [T-ios-msg-contextmenu-recursion-crash] Gate the eager menu
                // tree behind an Equatable key so this tool cell's body churn
                // during `gh`/shell streaming doesn't rebuild + re-diff the menu
                // subtree every frame (part of the deep ContextMenuModifier
                // recursion in incident 98E8805F). `toolDetailsClipboard` is read
                // lazily at TAP time, so the key only tracks structure: the tool
                // (blockId), whether the Re-run branch is shown (isProcessing),
                // and whether the memory-Undo branch is shown. All three are
                // cheap reads — the expensive payloads (clipboard dump, written
                // memory text) are built at tap time, never in the key.
                EquatableMenuGate(key: ToolMenuKey(
                    blockId: block.id,
                    isProcessing: vm.isProcessing,
                    canRevokeMemoryWrite: isRevocableMemoryWrite
                )) {
                    // [T-ios-tool-bubble-longpress-menu]
                    Button {
                        UIPasteboard.general.string = toolDetailsClipboard
                    } label: {
                        Label(AppLocalized("Copy Tool Details"), systemImage: "doc.on.doc")
                    }
                    // [T-ios-retry-hide-when-processing] Only expose the
                    // destructive Re-run action when the agent loop is idle.
                    // Re-running mid-stream would tear down an in-flight turn
                    // and confuse downstream state — hide both the divider and
                    // the button as a group so the menu doesn't leave a
                    // trailing separator with nothing under it.
                    if !vm.isProcessing {
                        Divider()
                        Button(role: .destructive) {
                            // Re-run the whole assistant turn that owns this
                            // tool_use. Routed via notification so we don't have
                            // to thread a vm closure through the 4-layer cell
                            // hosting chain — AIChatView's RerunFromToolBlockListener
                            // maps blockId → owning assistant msg → preceding user
                            // msg → vm.retryFromMessage.
                            NotificationCenter.default.post(
                                name: .rerunFromToolBlock,
                                object: nil,
                                userInfo: ["blockId": block.id]
                            )
                        } label: {
                            Label(AppLocalized("Re-run From Here"), systemImage: "arrow.clockwise")
                        }
                    }
                    // [T-ios-memory-write-revoke] Undo the daily-log entry this
                    // memory_write produced, without a detour through
                    // Memories in Session → detail sheet. Only appears for a
                    // memory_write that carries input args.
                    if isRevocableMemoryWrite {
                        Divider()
                        Button(role: .destructive) {
                            showRevokeMemoryAlert = true
                        } label: {
                            Label(AppLocalized("Undo This Memory Write"), systemImage: "trash.slash")
                        }
                    }
                }
                .equatable()
            })
            // [T-tool-bg-suspended-hint] Yellow ⓘ just outside the capsule's
            // trailing edge when this tool was likely suspended by the OS in the
            // background. Tapping shows an alert offering to enable enhanced
            // background (deep-links to Settings → Permissions → Background).
            if showBgSuspendedHint {
                Button {
                    showBgHintAlert = true
                } label: {
                    Image(systemName: "info.circle.fill")
                        .font(.system(size: 15))
                        .foregroundStyle(.yellow)
                }
                .buttonStyle(.plain)
                .padding(.leading, 6)
                .accessibilityLabel(Text(AppLocalized("Background suspension info")))
            }
            Spacer(minLength: 0)
        }
        .alert(
            AppLocalized("Task may have been paused"),
            isPresented: $showBgHintAlert
        ) {
            Button(AppLocalized("Go Enable")) {
                // Deep-link to Settings → Permissions → Background, nudging the
                // recommended rows ON — they highlight only while still OFF
                // (= minis://settings/background?focus=…:true,…:true). Location
                // Tracking is included so the background heartbeat that keeps the
                // task Live Activity refreshing in real time gets enabled too.
                DeepLinkCoordinator.shared.setFocus(
                    rawQueryValue: "enhancedBackgroundExecution:true,backgroundSpeakEnabled:true,locationTrackingEnabled:true")
                DeepLinkCoordinator.shared.pendingSettingsTarget = .background
            }
            Button(AppLocalized("Maybe Later"), role: .cancel) {}
        } message: {
            Text(AppLocalized("This tool may have been paused by the system while running in the background. Enable enhanced background execution to improve background task reliability."))
        }
        // [T-ios-memory-write-revoke] Mirrors the Revoke Memory confirmation in
        // SessionMemoryView: confirm, then report the outcome in place — the
        // user stays in the transcript, no navigation. The bubble itself is
        // left alone; only the underlying daily-log file changed.
        .alert(
            AppLocalized("Revoke Memory"),
            isPresented: $showRevokeMemoryAlert
        ) {
            Button(AppLocalized("Cancel"), role: .cancel) {}
            Button(AppLocalized("Revoke"), role: .destructive) {
                // The menu item is gated on the cheap enum+args check, so the
                // `content` parse can still come back empty here (malformed or
                // still-streaming args). Report that rather than failing silently.
                if let written = memoryWriteContent {
                    if vm.folderRuntimeContext?.usesFolderMemory == true {
                        revokeMemoryResult = "请在本组记忆管理中编辑此条目；旧撤销入口不会访问全局记忆。"
                    } else {
                        revokeMemoryResult = MemoryWriteRevoker.revoke(writtenContent: written)
                    }
                } else {
                    revokeMemoryResult = AppLocalized("No written content to revoke.")
                }
                showRevokeMemoryResultAlert = true
            }
        } message: {
            Text(AppLocalized("Remove this memory entry from the daily log? This cannot be undone."))
        }
        .alert(revokeMemoryResult ?? "", isPresented: $showRevokeMemoryResultAlert) {
            Button(AppLocalized("OK")) {}
        }
        .onChange(of: isStreaming) { streaming in
            dotsActive = streaming
        }
        .onAppear {
            if isStreaming {
                dotsActive = true
            }
        }
    }

    // MARK: - Status / Icon

    @ViewBuilder
    private var statusOrIcon: some View {
        Image(systemName: icon)
            .font(.system(size: 13))
            .foregroundStyle(iconColor)
    }

    private var iconColor: Color {
        switch block.toolStatus {
        // [T-subagent-control-capsule] A sub agent control call keeps its
        // accent when it succeeds, instead of turning the universal green.
        //
        // Green answers "did this tool work", which every other capsule needs
        // because they are all the same colour once finished. These are the
        // exception: their accent is what says "this was the model operating
        // on its sub agents", and that identity is exactly what the reader is
        // scanning for in a transcript full of tool calls — a succeeded
        // control call rendered green was indistinguishable from a shell
        // command. Failure and cancellation still override, since those must
        // read as problems before they read as anything else.
        case .success where isSubAgentControl: return accentColor
        case .success: return .green
        case .failed: return .red
        case .cancelled: return .yellow
        default: return accentColor
        }
    }

    /// True for a status / steer / resume / cancel call on a sub agent.
    /// `isControlOnly`, not `controlSummary`: same answer, and this is read on
    /// every body pass of every tool capsule — no point building a localized
    /// label only to compare it against nil.
    private var isSubAgentControl: Bool { HelperBlockInfo.isControlOnly(block) }

    /// Formatted execution duration (e.g. "1.2s", "45s", "2m 10s").
    private var durationText: String? {
        guard let dur = block.toolDuration else { return nil }
        if dur < 1 { return String(format: "%.1fs", dur) }
        if dur < 60 { return String(format: "%.0fs", dur) }
        let mins = Int(dur) / 60
        let secs = Int(dur) % 60
        return "\(mins)m \(secs)s"
    }

}



extension Notification.Name {
    static let thinkingBlockToggled = Notification.Name("thinkingBlockToggled")
    /// Posted when a long-press selection menu's "Add to Chat Input" action
    /// fires. userInfo["text"] is the selected text to append. The active
    /// chat's AIChatView listens and forwards to `vm.appendToInputText`.
    static let chatInputAppendRequested = Notification.Name("chatInputAppendRequested")
    /// Posted when an inline media attachment (image / video thumbnail /
    /// audio waveform) finishes async loading and its intrinsic content
    /// size changes. The collection view listens and invalidates self-sizing
    /// caches so cells re-measure. notification.object is the source URL
    /// string (for logging only — handler invalidates all visible cells).
    /// [T-attachment-size-invalidate 2026-05-21]
    static let minisAttachmentSizeChanged = Notification.Name("minisAttachmentSizeChanged")
    /// Posted from a tool capsule's long-press menu "Re-run from here".
    /// userInfo["blockId"] is the AssistantBlock.id (UUID) of the tapped
    /// tool_use. The active AIChatView listens, maps the block to its
    /// owning assistant message, finds the preceding user message, and
    /// re-runs the agent loop from there. [T-ios-tool-bubble-longpress-menu]
    static let rerunFromToolBlock = Notification.Name("rerunFromToolBlock")
}

/// Listens for `.rerunFromToolBlock` and drives the re-run. Extracted into
/// its own ViewModifier (like ChatInputAppendListener) to keep AIChatView's
/// body within the Swift type-checker budget. [T-ios-tool-bubble-longpress-menu]
///
/// "Re-run from here" semantics (block boundary —
/// T-ios-rerun-from-tool-block-position): re-run from the exact point this
/// tool_use was about to be issued. retryFromToolBlock keeps the blocks
/// BEFORE the target tool_use within its assistant turn, drops the target
/// block + later blocks in that turn + all later messages (rewriting the
/// trimmed assistant row in the DB), then re-runs the agent loop. If the
/// target is the first block with nothing preceding it, that path degrades
/// to a preceding-user-message truncation automatically.
struct RerunFromToolBlockListener: ViewModifier {
    let vm: AIChatViewModel

    func body(content: Content) -> some View {
        content.onReceive(NotificationCenter.default.publisher(for: .rerunFromToolBlock)) { note in
            guard let blockId = note.userInfo?["blockId"] as? UUID else { return }
            vm.retryFromToolBlock(blockId: blockId)
            vm.forceScrollToBottom.send()
        }
    }
}

/// View-modifier wrapper around the `chatInputAppendRequested` listener.
/// Extracted out of AIChatView.body because that body sits at the Swift
/// type-checker's expression budget and inlining another `.onReceive` block
/// trips the "compiler unable to type-check this expression in reasonable
/// time" diagnostic.
/// Listens for `.dismissAllImmersivePresentations` and calls the host
/// view's clear method. Extracted into its own modifier so AIChatView's
/// body type stays demangleable — adding the onReceive directly to body
/// trips the Swift type-checker timeout (same class of issue as the
/// 2026-04-17 inputBar / 2026-05-24 attachmentMenu blow-ups).
struct DismissImmersiveCoversListener: ViewModifier {
    let onDismiss: () -> Void

    func body(content: Content) -> some View {
        content.onReceive(NotificationCenter.default.publisher(for: .dismissAllImmersivePresentations)) { _ in
            onDismiss()
        }
    }
}

struct ChatInputAppendListener: ViewModifier {
    let vm: AIChatViewModel
    @Binding var inputFocused: Bool

    func body(content: Content) -> some View {
        content.onReceive(NotificationCenter.default.publisher(for: .chatInputAppendRequested)) { note in
            guard let text = note.userInfo?["text"] as? String else { return }
            vm.appendToInputText(text)
            // Focus the composer + pop the keyboard so the user can
            // immediately continue typing after a long-press → Add to Chat
            // Input. Independent of the post-reply auto-pop Settings
            // toggle (#354 / eb6d8164) — that gate is for *passive*
            // moments (reply finished, scroll, etc.); this is a direct
            // user gesture and should always focus. (T-add-to-input-focus)
            //
            // Async hop so the inputText `didSet` settles into the
            // composer's TextField before the focus binding flips —
            // without it the keyboard occasionally pops first and the
            // text appears mid-animation.
            DispatchQueue.main.async {
                inputFocused = true
            }
        }
    }
}

// MARK: - Thinking Block View

/// [T-thinkperf-release-displaylink] Retired hitch monitor.
///
/// This was a CADisplayLink that ticked at 60fps for the entire life of an
/// expanded, streaming thinking block, logging frame gaps > 100ms plus a
/// per-second frame summary. It was pure instrumentation for
/// T-thinking-stream-jank: nothing ever read it but its own log lines.
///
/// It has been removed rather than `#if DEBUG`-gated, for two reasons:
///
///  1. It shipped. The originating commit (7573e28b8) called it "cheap enough
///     to stay on in Debug" but never gated it, so every Release build ran the
///     display link in the field. A 60fps timer's cost is not its tick body
///     (85ms of main-thread CPU across a 209s Time Profiler trace, 2026-08-11)
///     but the main-thread wake-up it forces every frame, which keeps the CPU
///     out of idle. `stop()` only began a 25s grace window, so it kept ticking
///     for 18s after the stream ended — observed at 172-190s while the app was
///     otherwise idle at ~15ms/s. That is the shape of a battery complaint,
///     and a CPU-percentage view hides it.
///  2. A display link perturbs exactly what it claims to measure: holding the
///     frame pipeline active changes the frame timing being sampled.
///
/// The jank it was built to investigate was diagnosed and fixed (the follow
/// trigger moved from per-delta to flush pace). Should that work resume, prefer
/// Instruments over a permanent in-app probe on a per-frame path.
///
/// The type is kept as an inert stub so call sites stay put and no behaviour
/// depends on whether a probe happens to be compiled in.
@MainActor
final class ThinkingHitchMonitor {
    static let shared = ThinkingHitchMonitor()

    /// Retained so `ThinkingBlockView` keeps compiling; nothing reads it.
    var bodyEvalCount = 0
    var contentLenProvider: (() -> Int)?

    func start(owner: UUID) {}
    func stop(owner: UUID) {}
}

struct ThinkingBlockView: View {
    @ObservedObject var block: AssistantBlock
    let isStreaming: Bool

    // [T-thinking-scroll-followback GH#125] Per-view follow state. Reset on
    // cell reuse / re-entry is fine — a fresh view simply follows again.
    @State private var thinkingUserScrolledAway = false
    @State private var lastThinkingDragAt: Date = .distantPast
    @State private var frozenThinkingContent: String? = nil

    /// Bind to block.isThinkingExpanded so state survives cell reuse and triggers cell re-sizing.
    private var isExpanded: Binding<Bool> {
        Binding(
            get: { block.isThinkingExpanded },
            set: { block.isThinkingExpanded = $0 }
        )
    }

    init(block: AssistantBlock, isStreaming: Bool) {
        self.block = block
        self.isStreaming = isStreaming
        // Auto-expand-on-stream is handled in `.onAppear` (gated by block.id)
        // rather than from `init`. Mutating @Published from a SwiftUI view
        // initializer fires for every cell-reuse pass and was reaching the
        // wrong block when the cell was being recycled between an earlier
        // (frozen) thinking block and the currently-streaming one — manifesting
        // as "tap an old thinking block, see the streaming block's content."
    }

    /// Reconcile on mount as well as on stream transitions: a reconfigured or
    /// reused host can first mount with isStreaming == false, so onChange alone
    /// never sees the stream-end edge. Only the model publishes size changes.
    private func reconcileAutomaticExpansion(streaming: Bool) {
        guard !block.thinkingUserToggled else { return }
        let autoExpand = (UserDefaults.standard.object(forKey: "chat.autoExpandThinking") as? Bool) ?? true
        guard !streaming || autoExpand else { return }
        let expanded = streaming
        guard block.isThinkingExpanded != expanded else { return }
        var transaction = Transaction(animation: nil)
        if #available(iOS 16.0, *) {
            transaction = Transaction()
        } else {
            transaction.disablesAnimations = true
        }
        withTransaction(transaction) {
            block.isThinkingExpanded = expanded
        }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            // Header
            HStack(spacing: 6) {
                Image("ThinkingIcon")
                    .resizable()
                    .frame(width: 14, height: 14)
                    .foregroundStyle(.blue)
                Text(AppLocalized("Deep Thinking"))
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(.blue)
                if isStreaming {
                    ProgressView()
                        .controlSize(.mini)
                        .tint(.blue)
                }
                Spacer()
                // [T-thinking-count-beside-chevron] The character count sits at
                // the RIGHT end, tight against the chevron, matching Android
                // (ChatAssistantMessageUI.kt: weight(1f) → count → 4dp → icon).
                //
                // It used to sit immediately after the title, on the left of the
                // spacer, so the two platforms disagreed. The 4pt gap is the
                // HStack's own `spacing: 6` overridden locally — the enclosing
                // spacing would otherwise put 6pt here and the number would not
                // read as belonging to the chevron.
                HStack(spacing: 4) {
                    if block.content.count > 0 || block.thinkingContentBuffer.count > 0 {
                        let charCount = max(block.content.count, block.thinkingContentBuffer.count)
                        Text(charCount > 1000 ? "\(charCount / 1000)K" : "\(charCount)")
                            .font(.system(size: 11, weight: .medium, design: .monospaced))
                            .foregroundStyle(.blue.opacity(0.6))
                    }
                    Image(systemName: isExpanded.wrappedValue ? "chevron.up" : "chevron.down")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(.blue.opacity(0.5))
                }
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 10)
            .contentShape(Rectangle())
            .onTapGesture {
                // Mark before flipping so a concurrent stream-end collapse
                // cannot stomp the user's choice. The coordinator observes the
                // committed @Published isThinkingExpanded value for visible AND
                // offscreen blocks; do not also post a second resize request.
                AppLogger(category: "ThinkingCollapse").info("[ThinkingCollapse] tap block=\(block.id.uuidString.prefix(8)) wasExpanded=\(isExpanded.wrappedValue) streaming=\(isStreaming) contentLen=\(block.content.count)")
                block.thinkingUserToggled = true
                if !isExpanded.wrappedValue {
                    block.flushThinkingBuffer()
                }
                isExpanded.wrappedValue.toggle()
            }

            // Content — only visible when expanded, windowed to the tail
            // to prevent UI freeze on very long thinking (T-thinking-render-perf-ios).
            if isExpanded.wrappedValue, !block.content.isEmpty {
                // [T-thinking-stream-window] While STREAMING, shrink the tail
                // window 8000 → 2000: every flush re-lays-out the whole Text
                // on the main thread, and an 8K plain-text relayout per flush
                // is the reported "5K starts to lag, 10K unusable" jank (the
                // hitch cost scales with the WINDOW, not the total). Reading
                // the live tail only needs the recent context; the full 8K
                // window comes back the moment streaming ends.
                let windowSize = isStreaming ? 2000 : 8000
                let total = block.content.count
                let isTruncated = total > windowSize
                let displayContent: String = frozenThinkingContent ?? {
                    // [T-thinkperf-release-displaylink] The slice timing and
                    // body-eval counter that used to wrap this closure are gone.
                    // It runs on EVERY body evaluation of an expanded thinking
                    // block, so it paid two CFAbsoluteTimeGetCurrent calls per
                    // eval to feed a counter only ThinkPerf's own log lines read.
                    // The question it existed to answer — do body re-evals track
                    // per-token contentUpdateSeq rather than the flush? — was
                    // answered (they did) and fixed.
                    guard isTruncated else { return block.content }
                    let startIdx = block.content.index(block.content.endIndex, offsetBy: -windowSize)
                    let cleanStart = block.content[startIdx...].firstIndex(of: "\n")
                        .map { block.content.index(after: $0) }
                        .flatMap { $0 < block.content.endIndex ? $0 : nil } ?? startIdx
                    return String(block.content[cleanStart...])
                }()

                // A vertical ScrollView has no intrinsic height. maxHeight alone
                // lets an iOS 15 hosting cell reuse a zero/old proposal. A hidden
                // copy of the SAME windowed content supplies the natural height;
                // the bounded overlay scrolls without taking part in self-sizing.
                let thinkingBody = VStack(alignment: .leading, spacing: 0) {
                            if isTruncated {
                                Text("Showing last \(displayContent.count / 1000)K of \(total / 1000)K characters", comment: "Thinking window truncation hint")
                                    .font(.system(size: 11))
                                    .foregroundStyle(.secondary)
                                    .padding(.horizontal, 12)
                                    .padding(.bottom, 4)
                            }
                            // [T-thinking-stream-jank] textSelection(.enabled)
                            // makes SwiftUI Text substantially more expensive
                            // per layout; selecting text that is actively
                            // moving is useless anyway — enable it only once
                            // streaming finished.
                            let thinkingText = Text(displayContent)
                                .font(.system(size: 13))
                                .foregroundStyle(ChatColors.tertiaryText)
                                .lineSpacing(3)
                            Group {
                                if isStreaming {
                                    thinkingText
                                } else {
                                    thinkingText.textSelection(.enabled)
                                }
                            }
                                .frame(maxWidth: .infinity, alignment: .leading)
                                .padding(.horizontal, 12)
                                .padding(.bottom, 10)
                                .id("thinkingBottom")
                        }
                thinkingBody
                    .fixedSize(horizontal: false, vertical: true)
                    .hidden()
                    .accessibilityHidden(true)
                    .frame(maxHeight: 300, alignment: .top)
                    .clipped()
                    .overlay(alignment: .topLeading) {
                        ScrollViewReader { proxy in
                            ScrollView { thinkingBody }
                    // [T-thinking-scroll-followback GH#125] User-intent gate,
                    // Android parity (ChatAssistantMessageUI.kt): mark
                    // scrolled-away ONLY when a real finger drag moved the view
                    // off the bottom — programmatic scrollTo offsets must not
                    // set it, or follow would permanently disarm. Deployment
                    // target is iOS 16 (no onScrollPhaseChange), so "real drag"
                    // = a simultaneous DragGesture seen within the last 350ms.
                    // A downward drag inside the box means "show me earlier
                    // text" — that IS the scrolled-away intent, and unlike a
                    // geometry probe it cannot be spoofed by our own
                    // programmatic scrollTo (which fires no gesture). An
                    // upward drag (heading back toward the tail) re-arms
                    // following, as does the stream ending.
                    .simultaneousGesture(
                        DragGesture(minimumDistance: 6)
                            .onEnded { value in
                                lastThinkingDragAt = Date()
                                if value.translation.height > 12 {
                                    if !thinkingUserScrolledAway {
                                        thinkingUserScrolledAway = true
                                        frozenThinkingContent = displayContent
                                        AppLogger(category: "ThinkPerf").info("[ThinkPerf] user scrolled away (dy=\(Int(value.translation.height))) — follow paused, content frozen at \(displayContent.count) chars")
                                    }
                                } else if value.translation.height < -12, thinkingUserScrolledAway {
                                    thinkingUserScrolledAway = false
                                    frozenThinkingContent = nil
                                    AppLogger(category: "ThinkPerf").info("[ThinkPerf] user scrolled back (dy=\(Int(value.translation.height))) — following resumed")
                                }
                            }
                    )
                    // [T-thinking-stream-jank] Follow the tail at FLUSH pace
                    // (content updates every 0.3s), not per token. The old
                    // trigger was the per-delta contentUpdateSeq — with it
                    // @Published, an expanded block re-ran body + an animated
                    // scrollTo for every delta (~60-105/s measured); the flush
                    // pace is ~3-4/s for the same visual result.
                    .onChange(of: block.content.count) { len in
                        guard isStreaming, !thinkingUserScrolledAway else { return }
                        // [T-thinkperf-release-displaylink] Removed: this fired on
                        // every content flush of a streaming thinking block, and
                        // building the interpolated string cost more than the log
                        // call. The two scroll-gesture lines above stay — they
                        // fire once per user drag, not per flush.
                        // iOS 15 self-sizing must not animate an inner scroll
                        // while the outer row is publishing a new natural size.
                        // Both animations otherwise retarget the same content on
                        // every flush. Preserve the existing newer-iOS behavior.
                        if #available(iOS 16.0, *) {
                            if len > 3000 {
                                proxy.scrollTo("thinkingBottom", anchor: .bottom)
                            } else {
                                withAnimation(.linear(duration: 0.15)) {
                                    proxy.scrollTo("thinkingBottom", anchor: .bottom)
                                }
                            }
                        } else {
                            var transaction = Transaction(animation: nil)
                            transaction.disablesAnimations = true
                            withTransaction(transaction) {
                                proxy.scrollTo("thinkingBottom", anchor: .bottom)
                            }
                        }
                    }
                    .onChange(of: isStreaming) { streaming in
                        if !streaming {
                            thinkingUserScrolledAway = false
                            frozenThinkingContent = nil
                        }
                    }
                        }
                    }
            }
        }
        // [T-thinking-stream-jank] Hitch monitor runs while this block is
        // EXPANDED — streaming or static. The refined report says the jank is
        // tied to the expanded state itself (collapse instantly recovers), so
        // the monitor must also capture expanded-static interactions (list
        // scrolling, new messages arriving) to compare against collapsed.
        .task(id: isExpanded.wrappedValue) {
            if isExpanded.wrappedValue {
                ThinkingHitchMonitor.shared.contentLenProvider = { [weak block] in
                    block?.thinkingContentBuffer.count ?? -1
                }
                ThinkingHitchMonitor.shared.start(owner: block.id)
            } else {
                ThinkingHitchMonitor.shared.stop(owner: block.id)
            }
        }
        .onDisappear {
            ThinkingHitchMonitor.shared.stop(owner: block.id)
        }
        .background(Color.blue.opacity(0.06))
        .clipShape(RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(Color.blue.opacity(0.15), lineWidth: 0.5)
        )
        .task(id: block.id) {
            reconcileAutomaticExpansion(streaming: isStreaming)
        }
        .onChange(of: isStreaming) { streaming in
            reconcileAutomaticExpansion(streaming: streaming)
        }
    }
}

// MARK: - Typing Indicator

struct TypingIndicator: View {
    @State private var dotOffsets: [Bool] = [false, false, false]
    /// Live Soul name so the indicator reads "<custom name> is thinking…" when
    /// the user has renamed the assistant in Soul settings. Updates via
    /// `.soulMdChanged` Notification — same wiring used by `AssistantSoulName`.
    @State private var soulName: String = {
        let n = SoulStore.cachedMetadata.name.trimmingCharacters(in: .whitespacesAndNewlines)
        return n.isEmpty ? "Minis" : n
    }()

    var body: some View {
        // The thinking-level badge that used to trail this indicator was
        // removed — the nav-bar title (AIChatView.thinkingLevelBadge) is now
        // the single place that shows and changes the thinking level, so a
        // duplicate here was redundant. ThinkingLevelSheetView is unchanged;
        // it's still presented from the nav-bar badge.
        HStack(spacing: 0) {
            Text("\(soulName) is thinking")
            ForEach(0..<3, id: \.self) { i in
                Text(".")
                    .offset(y: dotOffsets[i] ? -3 : 1)
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: .soulMdChanged)) { _ in
            let n = SoulStore.cachedMetadata.name.trimmingCharacters(in: .whitespacesAndNewlines)
            soulName = n.isEmpty ? "Minis" : n
        }
        .font(.system(size: 15, weight: .medium))
        .foregroundStyle(ChatColors.tertiaryText)
        .padding(.top, 0)
        .onAppear {
            for i in 0..<3 {
                withAnimation(
                    .easeInOut(duration: 0.4)
                        .repeatForever(autoreverses: true)
                        .delay(Double(i) * 0.15)
                ) {
                    dotOffsets[i] = true
                }
            }
        }
    }
}

// MARK: - Thinking Level Sheet

struct ThinkingLevelSheetView: View {
    let currentLevel: ThinkingLevel
    let availableLevels: [ThinkingLevel]
    let contextUsage: ContextUsage?
    let contextFixedTokens: Int
    let onSelect: (ThinkingLevel) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var selectedLevel: ThinkingLevel
    @State private var thinkingEnabled: Bool

    init(currentLevel: ThinkingLevel,
         availableLevels: [ThinkingLevel],
         contextUsage: ContextUsage? = nil,
         contextFixedTokens: Int = 0,
         onSelect: @escaping (ThinkingLevel) -> Void) {
        let levels = availableLevels.isEmpty ? [ThinkingLevel.medium] : availableLevels
        let initial: ThinkingLevel
        if currentLevel.isEnabled {
            initial = levels.contains(currentLevel)
                ? currentLevel
                : (levels.last(where: { $0 <= currentLevel }) ?? levels[0])
        } else {
            initial = levels[0]
        }
        self.currentLevel = currentLevel
        self.availableLevels = availableLevels
        self.contextUsage = contextUsage
        self.contextFixedTokens = contextFixedTokens
        self.onSelect = onSelect
        _selectedLevel = State(initialValue: initial)
        _thinkingEnabled = State(initialValue: currentLevel.isEnabled)
    }

    private var levels: [ThinkingLevel] {
        availableLevels.isEmpty ? [.medium] : availableLevels
    }

    private var selectedBinding: Binding<ThinkingLevel> {
        Binding(
            get: { selectedLevel },
            set: { level in
                selectedLevel = level
                thinkingEnabled = true
            }
        )
    }

    var body: some View {
        // [T-thinking-panel-inset] 面板不再铺满整张 sheet：左右各留 12pt、
        // 底部留 12pt，圆角 26。sheet 本身的高度/下拉关闭/抓手都不变，
        // 只是内容收成一张浮在底部的卡片（iOS 15 的 sheet 没有宽度 inset API，
        // 只能靠内边距实现）。
        VStack(spacing: 0) {
            header
            ScrollView(.vertical, showsIndicators: false) {
                VStack(spacing: 12) {
                    thinkingCard
                    if let usage = contextUsage {
                        contextCard(usage)
                    }
                    thinkingToggle
                }
                .padding(.horizontal, 16)
                .padding(.bottom, 22)
            }
        }
        .background(Color(UIColor.secondarySystemGroupedBackground))
        .clipShape(RoundedRectangle(cornerRadius: 26, style: .continuous))
        .padding(.horizontal, 12)
        .padding(.bottom, 12)
        .background(Color.clear)
    }

    private var header: some View {
        HStack(spacing: 8) {
            Image("ThinkingIcon")
                .resizable()
                .frame(width: 20, height: 20)
                .foregroundStyle(Color.accentColor)
            Text(AppLocalized("Thinking Intensity"))
                .font(.system(size: 17, weight: .semibold))
            Spacer(minLength: 8)
            Text(thinkingEnabled ? selectedLevel.displayName : ThinkingLevel.off.displayName)
                .font(.system(size: 14, weight: .semibold))
                .foregroundStyle(Color.accentColor)
            Button(AppLocalized("Done")) {
                commit()
            }
            .font(.system(size: 15, weight: .semibold))
            .padding(.leading, 6)
        }
        .padding(.horizontal, 16)
        .padding(.top, 10)
        .padding(.bottom, 12)
    }

    private var thinkingCard: some View {
        VStack(alignment: .leading, spacing: 10) {
            ThinkingSlider(levels: levels, selected: selectedBinding)
                .padding(.horizontal, 8)
                .opacity(thinkingEnabled ? 1 : 0.45)
            // [T-thinking-labels-align] 圆点在滑块里是按
            // `17 + (宽-34) × i/(n-1)` 摆的（两端给圆钮留半径），
            // 而原来是等分 HStack 居中，两套坐标越靠两端差得越多，
            // 「低」「极高」几乎对不上点。这里改成同一套坐标定位。
            GeometryReader { geo in
                let thumb: CGFloat = 34
                let inset = thumb / 2
                let usable = max(1, geo.size.width - thumb)
                ForEach(Array(levels.enumerated()), id: \.offset) { index, level in
                    let rawX = levels.count > 1
                        ? inset + usable * CGFloat(index) / CGFloat(levels.count - 1)
                        : geo.size.width / 2
                    // 两端标签不能越出边界，夹回半宽
                    let halfWidth = min(44, geo.size.width / CGFloat(max(2, levels.count)))
                    let x = min(max(rawX, halfWidth), geo.size.width - halfWidth)
                    Text(level.displayName)
                        .font(.system(size: levels.count > 5 ? 10 : 10.5,
                                      weight: level == selectedLevel ? .semibold : .regular))
                        .foregroundStyle(level == selectedLevel && thinkingEnabled
                                         ? Color.accentColor
                                         : Color.secondary)
                        .lineLimit(1)
                        .minimumScaleFactor(0.65)
                        .frame(width: halfWidth * 2)
                        .position(x: x, y: 8)
                }
            }
            .frame(height: 16)
            Text(AppLocalized("Drag the slider or tap a dot. Levels follow the current model."))
                .font(.system(size: 11))
                .foregroundStyle(Color.secondary)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color(UIColor.tertiarySystemGroupedBackground))
        )
    }

    private var thinkingToggle: some View {
        HStack(spacing: 8) {
            VStack(alignment: .leading, spacing: 2) {
                Text(AppLocalized("Thinking Process"))
                    .font(.system(size: 15))
                Text(AppLocalized("Hide thinking process when off"))
                    .font(.system(size: 11))
                    .foregroundStyle(Color.secondary)
            }
            Spacer()
            Toggle("", isOn: $thinkingEnabled)
                .labelsHidden()
                .tint(.green)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 13)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color(UIColor.tertiarySystemGroupedBackground))
        )
    }

    private func contextCard(_ usage: ContextUsage) -> some View {
        let window = max(1, usage.windowTokens)
        let used = max(0, usage.usedTokens)
        let fixed = max(0, min(contextFixedTokens, used))
        let messages = max(0, used - fixed)
        let remaining = max(0, window - used)
        let percent = min(100, max(0, Double(used) / Double(window) * 100))

        return VStack(alignment: .leading, spacing: 9) {
            HStack {
                Text(AppLocalized("Context Usage"))
                    .font(.system(size: 13, weight: .semibold))
                Spacer()
                Text(String(format: "%.1f%%", percent))
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color.accentColor)
            }
            HStack(alignment: .firstTextBaseline, spacing: 4) {
                Text(TokenCountFormatter.short(used))
                    .font(.system(size: 19, weight: .semibold))
                    .monospacedDigit()
                Text("/ \(TokenCountFormatter.short(window))")
                    .font(.system(size: 12))
                    .foregroundStyle(Color.secondary)
                    .monospacedDigit()
            }
            ThinkingContextBar(system: fixed, messages: messages, window: window)
            contextLine(color: .blue,
                        title: AppLocalized("System & Settings"),
                        value: fixed,
                        muted: false)
            contextLine(color: .green,
                        title: AppLocalized("Message Content"),
                        value: messages,
                        muted: false)
            contextLine(color: Color(UIColor.tertiaryLabel),
                        title: AppLocalized("Remaining Space"),
                        value: remaining,
                        muted: true)
        }
        .padding(16)
        .background(
            RoundedRectangle(cornerRadius: 14, style: .continuous)
                .fill(Color(UIColor.secondarySystemGroupedBackground))
        )
    }

    private func contextLine(color: Color,
                             title: String,
                             value: Int,
                             muted: Bool) -> some View {
        HStack(spacing: 7) {
            Circle()
                .fill(color)
                .frame(width: 7, height: 7)
            Text(title)
                .font(.system(size: 12))
                .foregroundStyle(Color.primary)
            Spacer()
            Text(TokenCountFormatter.short(value))
                .font(.system(size: 12))
                .monospacedDigit()
                .foregroundStyle(muted ? Color.secondary : Color.primary)
        }
        .padding(.vertical, 1)
    }

    private func commit() {
        let result: ThinkingLevel = thinkingEnabled ? selectedLevel : .off
        onSelect(result)
        dismiss()
    }
}

private struct ThinkingSlider: View {
    let levels: [ThinkingLevel]
    @Binding var selected: ThinkingLevel
    @State private var dragRatio: CGFloat?

    private var effectiveRatio: CGFloat {
        if let dragRatio { return dragRatio }
        let index = levels.firstIndex(of: selected) ?? 0
        return levels.count > 1 ? CGFloat(index) / CGFloat(levels.count - 1) : 0
    }

    var body: some View {
        GeometryReader { geo in
            let width = max(geo.size.width, 1)
            let thumb: CGFloat = 34
            let inset = thumb / 2
            let usable = max(1, width - thumb)
            let thumbX = inset + usable * effectiveRatio

            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color(UIColor.tertiarySystemFill))
                    .frame(height: 40)
                Capsule()
                    .fill(LinearGradient(colors: [Color.accentColor.opacity(0.92), Color.accentColor],
                                         startPoint: .leading,
                                         endPoint: .trailing))
                    .frame(width: min(width, thumbX + thumb / 2), height: 40)
                ForEach(levels.indices, id: \.self) { i in
                    Circle()
                        .fill(Color.white.opacity(0.92))
                        .frame(width: 5, height: 5)
                        .position(x: dotX(index: i, inset: inset, usable: usable, count: levels.count),
                                  y: 20)
                }
                Circle()
                    .fill(Color(UIColor.systemBackground))
                    .frame(width: thumb, height: thumb)
                    .overlay(Circle().stroke(Color.accentColor, lineWidth: 2))
                    .shadow(color: Color.black.opacity(0.12), radius: 3, x: 0, y: 1)
                    .position(x: thumbX, y: 20)
                    .animation(nil, value: effectiveRatio)
            }
            .contentShape(Rectangle())
            .gesture(
                DragGesture(minimumDistance: 0)
                    .onChanged { value in
                        let clamped = min(max(value.location.x, inset), width - inset)
                        let fraction = min(max((clamped - inset) / usable, 0), 1)
                        dragRatio = fraction
                        let raw = Int((fraction * CGFloat(max(1, levels.count - 1))).rounded())
                        let index = min(max(raw, 0), levels.count - 1)
                        if levels.indices.contains(index), selected != levels[index] {
                            var transaction = Transaction()
                            transaction.animation = nil
                            withTransaction(transaction) {
                                selected = levels[index]
                            }
                        }
                    }
                    .onEnded { _ in
                        dragRatio = nil
                    }
            )
        }
        .frame(height: 40)
    }

    private func dotX(index: Int, inset: CGFloat, usable: CGFloat, count: Int) -> CGFloat {
        guard count > 1 else { return inset + usable / 2 }
        return inset + usable * CGFloat(index) / CGFloat(count - 1)
    }
}

private struct ThinkingContextBar: View {
    let system: Int
    let messages: Int
    let window: Int

    var body: some View {
        GeometryReader { geo in
            let total = max(1, window)
            let width = geo.size.width
            let systemWidth = width * CGFloat(system) / CGFloat(total)
            let messagesWidth = width * CGFloat(messages) / CGFloat(total)
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color(UIColor.tertiarySystemFill))
                HStack(spacing: 0) {
                    Rectangle()
                        .fill(Color.accentColor)
                        .frame(width: systemWidth)
                    Rectangle()
                        .fill(Color.green)
                        .frame(width: messagesWidth)
                }
            }
            .clipShape(Capsule())
        }
        .frame(height: 7)
    }
}

private struct ThinkingSheetDetentsConfigurator: UIViewControllerRepresentable {
    final class Coordinator {
        weak var configuredSheet: UISheetPresentationController?
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIViewController(context: Context) -> UIViewController {
        let controller = UIViewController()
        controller.view.backgroundColor = .clear
        DispatchQueue.main.async {
            configure(controller, coordinator: context.coordinator)
        }
        return controller
    }

    func updateUIViewController(_ uiViewController: UIViewController, context: Context) {
        DispatchQueue.main.async {
            configure(uiViewController, coordinator: context.coordinator)
        }
    }

    private func configure(_ controller: UIViewController, coordinator: Coordinator) {
        var root: UIViewController? = controller
        while let parent = root?.parent {
            root = parent
        }
        guard let sheet = root?.presentationController as? UISheetPresentationController else { return }
        guard coordinator.configuredSheet !== sheet else { return }
        coordinator.configuredSheet = sheet
        sheet.detents = [.medium(), .large()]
        sheet.prefersGrabberVisible = true
        sheet.prefersScrollingExpandsWhenScrolledToEdge = false
        sheet.preferredCornerRadius = 26
        // [T-thinking-panel-inset] 让 sheet 自身透明，面板左右/底部的留边
        // 才能露出后面被暗化的聊天内容，看起来是一张浮卡而不是整块白板。
        root?.view.backgroundColor = .clear
        root?.view.isOpaque = false
        for sub in root?.view.subviews ?? [] {
            sub.backgroundColor = .clear
            sub.isOpaque = false
        }
    }
}

extension View {
    @ViewBuilder
    func thinkingLevelSheetPresentation() -> some View {
        if #available(iOS 16.0, *) {
            self
                .presentationDetents([.fraction(0.6), .large])
                .presentationDragIndicator(.visible)
        } else {
            self.background(ThinkingSheetDetentsConfigurator())
        }
    }
}

// MARK: - Tool Copy Button

private struct ToolCopyButton: View {
    var accentColor: Color = .green
    let content: () -> String
    @State private var copied = false

    var body: some View {
        Button {
            UIPasteboard.general.string = content()
            copied = true
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                copied = false
            }
        } label: {
            Image(systemName: copied ? "checkmark" : "doc.on.doc")
                .font(.system(size: 11))
                .frame(width: 16, height: 16)
                .foregroundStyle(copied ? accentColor : accentColor.opacity(0.4))
        }
        .animation(.easeInOut(duration: 0.15), value: copied)
    }
}
