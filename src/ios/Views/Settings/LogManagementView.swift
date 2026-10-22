import SwiftUI
import UIKit

// MARK: - View Model

class LogManagementViewModel: ObservableObject {
    struct LogFile: Identifiable {
        let id: String
        let name: String
        let url: URL
        let date: Date
        let size: Int64
        let type: String  // "running" | "crash" | "other"
    }

    @Published var logFiles: [LogFile] = []
    @Published var totalSize: Int64 = 0
    /// [T-crash-report-groups] One entry per recurring cause, newest first.
    @Published var crashGroups: [CrashReportGroup] = []

    /// Running + other logs (non-crash). Shown in the "Log Files" section.
    var runningFiles: [LogFile] { logFiles.filter { $0.type != "crash" } }
    /// Crash reports (crash-*.log). Shown in a separate section only if non-empty.
    var crashFiles: [LogFile] { logFiles.filter { $0.type == "crash" } }

    private let formatter: ByteCountFormatter = {
        let f = ByteCountFormatter()
        f.allowedUnits = [.useBytes, .useKB, .useMB, .useGB]
        f.countStyle = .file
        return f
    }()

    func format(_ bytes: Int64) -> String {
        formatter.string(fromByteCount: bytes)
    }

    func load() {
        let files = LoggingManager.shared.logFiles()
        logFiles = files.map {
            LogFile(id: $0.name, name: $0.name, url: $0.url, date: $0.date, size: $0.size, type: $0.type)
        }
        totalSize = LoggingManager.shared.totalLogSize()
        crashGroups = CrashReportIndex.groups(from: crashFiles)
    }
}

// MARK: - [T-crash-report-groups] Repeated crashes, grouped by cause

/// Grouping follows the same idea as Sentry's crash fingerprint and FaST
/// (MIT) stack-trace alignment: the exception/termination type plus the top
/// app frame identify one recurring problem. Minis writes its own text crash
/// reports, so the parser is independent; no third-party code is copied.
enum CrashReportCategory: String {
    case lockWait
    case messageList
    case providerPage
    case questionCard
    case startup
    case foregroundKill
    case backgroundTermination
    case other

    var title: String {
        switch self {
        case .lockWait: return AppLocalized("主线程等锁")
        case .messageList: return AppLocalized("消息列表卡顿")
        case .providerPage: return AppLocalized("供应商页卡顿")
        case .questionCard: return AppLocalized("提问卡片卡顿")
        case .startup: return AppLocalized("启动闪退")
        case .foregroundKill: return AppLocalized("前台被杀")
        case .backgroundTermination: return AppLocalized("后台被回收")
        case .other: return AppLocalized("其他崩溃")
        }
    }

    var detail: String {
        switch self {
        case .lockWait: return AppLocalized("打开供应商/多 Key 页时卡住")
        case .messageList: return AppLocalized("长会话加载/流式输出时卡住")
        case .providerPage: return AppLocalized("供应商页渲染时卡住")
        case .questionCard: return AppLocalized("提问卡片显示时卡住")
        case .startup: return AppLocalized("启动阶段闪退")
        case .foregroundKill: return AppLocalized("前台运行时被系统杀掉")
        case .backgroundTermination: return AppLocalized("切到后台后被系统回收")
        case .other: return AppLocalized("未归类")
        }
    }

    var suggestion: String {
        switch self {
        case .lockWait:
            return AppLocalized("供应商/多 Key 页不要在主线程读 Key；保存成功/失败记录不要放在锁里写 UserDefaults。")
        case .messageList:
            return AppLocalized("消息列表快照避免每条消息全表扫描；长会话先压缩，再打开。")
        case .providerPage:
            return AppLocalized("供应商页 body 里不要做 Keychain/网络同步调用，改成后台预加载。")
        case .questionCard:
            return AppLocalized("检查提问卡片的高度测量和缓存，避免每次刷新都重新排版整张卡。")
        case .startup:
            return AppLocalized("先停用最近新增的注入/插件，再看崩溃栈第一帧；启动阶段不要做重活。")
        case .foregroundKill:
            return AppLocalized("看最近一次前台操作；如果是 watchdog，检查主线程是否在等锁或跑大循环。")
        case .backgroundTermination:
            return AppLocalized("后台被系统回收，检查后台任务是否超时；回到前台先恢复状态。")
        case .other:
            return AppLocalized("先看原始报告的关键栈；没有符号时提供 dSYM 或二进制。")
        }
    }
}

struct CrashReportEntry: Identifiable {
    let id: String
    let name: String
    let url: URL
    let date: Date
    let size: Int64
    let type: String
    let category: CrashReportCategory
    let frames: [String]
}

struct CrashReportGroup: Identifiable {
    let id: String
    let category: CrashReportCategory
    let title: String
    let detail: String
    let entries: [CrashReportEntry]

    var count: Int { entries.count }
    var latest: CrashReportEntry? { entries.first }
}

enum CrashReportIndex {
    static func groups(from files: [LogManagementViewModel.LogFile]) -> [CrashReportGroup] {
        var buckets: [CrashReportCategory: [CrashReportEntry]] = [:]
        for file in files {
            let entry = parse(file)
            buckets[entry.category, default: []].append(entry)
        }
        return buckets.map { category, entries in
            let sorted = entries.sorted { $0.date > $1.date }
            return CrashReportGroup(id: category.rawValue,
                                    category: category,
                                    title: category.title,
                                    detail: category.detail,
                                    entries: sorted)
        }
        .sorted { ($0.latest?.date ?? .distantPast) > ($1.latest?.date ?? .distantPast) }
    }

    static func parse(_ file: LogManagementViewModel.LogFile) -> CrashReportEntry {
        let text = LoggingManager.shared.readLog(at: file.url, maxBytes: 1_048_576)
        let date = parseDate(in: text) ?? file.date
        let type = value(of: "Type:", in: text) ?? ""
        return CrashReportEntry(id: file.id,
                                name: file.name,
                                url: file.url,
                                date: date,
                                size: file.size,
                                type: type,
                                category: category(type: type, text: text),
                                frames: keyFrames(in: text))
    }

    static func parseDate(in text: String) -> Date? {
        guard let raw = value(of: "Date:", in: text) else { return nil }
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "en_US_POSIX")
        formatter.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return formatter.date(from: raw)
    }

    static func value(of key: String, in text: String) -> String? {
        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            let trimmed = String(line).trimmingCharacters(in: .whitespaces)
            guard trimmed.hasPrefix(key) else { continue }
            return String(trimmed.dropFirst(key.count)).trimmingCharacters(in: .whitespaces)
        }
        return nil
    }

    static func category(type: String, text: String) -> CrashReportCategory {
        let lower = text.lowercased()
        // SIGKILL has no stack of its own; the "Last HangDetector Stacks"
        // section can describe an older hang, so type wins here.
        if type.lowercased().contains("sigkill") || type.lowercased().contains("foreground crash") {
            return .foregroundKill
        }
        let hasHang = lower.contains("last hangdetector stacks") && lower.contains("hang #")
        if hasHang {
            if lower.contains("providermultikeymanager")
                && (lower.contains("savemainstate") || lower.contains("keys(for") || lower.contains("quotarows")) {
                return .lockWait
            }
            if lower.contains("collectionviewmessagelist") && lower.contains("applysnapshot") {
                return .messageList
            }
            if lower.contains("questioncard") { return .questionCard }
            if lower.contains("providerinstancedetailview") { return .providerPage }
        }
        if type.lowercased().contains("background termination") {
            return .backgroundTermination
        }
        if lower.contains("launch") || lower.contains("startup") {
            return .startup
        }
        return .other
    }

    /// App frames only, in report order, capped so a group detail stays small.
    static func keyFrames(in text: String) -> [String] {
        var result: [String] = []
        for line in text.split(separator: "\n", omittingEmptySubsequences: true) {
            let trimmed = String(line).trimmingCharacters(in: .whitespaces)
            guard trimmed.hasPrefix("#") else { continue }
            guard trimmed.contains("Minis +0x") || trimmed.contains("$s5Minis") else { continue }
            if let range = trimmed.range(of: "Minis +0x") {
                let tail = trimmed[range.upperBound...]
                let parts = tail.split(separator: " ", maxSplits: 1, omittingEmptySubsequences: true)
                let symbol = parts.count > 1 ? String(parts[1]) : String(tail)
                if !symbol.isEmpty { result.append(symbol) }
            } else {
                result.append(trimmed)
            }
            if result.count >= 8 { break }
        }
        return result
    }
}

enum CrashReportTime {
    static func text(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = Calendar.current.isDateInToday(date) ? "HH:mm" : "MM-dd HH:mm"
        return formatter.string(from: date)
    }
}

// MARK: - Log Management View

struct LogManagementView: View {
    @StateObject private var vm = LogManagementViewModel()
    @ObservedObject private var loggingManager = LoggingManager.shared
    @State private var showDeleteAllConfirm = false
    @State private var showShareSheet = false

    /// Selected top-level tab. Bound to a deep-link query string so
    /// `minis://settings/logs?tab=config-audit` lands users straight on
    /// the audit list. Stored as a String so the Picker can drive it.
    @State var initialTab: String = "logs"
    @State private var tab: String = "logs"

    var body: some View {
        VStack(spacing: 0) {
            Picker("Tab", selection: $tab) {
                Text("Logs").tag("logs")
                Text("Config Changes").tag("config-audit")
            }
            .pickerStyle(.segmented)
            .padding(.horizontal)
            .padding(.vertical, 8)

            if tab == "config-audit" {
                ConfigAuditView()
            } else {
                logsBody
            }
        }
        .navigationTitle("Logs")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            // "crashes" is no longer a tab — crash reports now live in a
            // section of the Logs body. Fall back to "logs" for stale deep links.
            tab = (initialTab == "crashes") ? "logs" : initialTab
            vm.load()
        }
    }

    private func crashTimeText(_ date: Date) -> String {
        CrashReportTime.text(date)
    }

    @ViewBuilder
    private var logsBody: some View {
        List {
            Section {
                Toggle("Enable Logging", isOn: $loggingManager.isEnabled)
                if loggingManager.isEnabled {
                    // [T-ios-log-verbose-tier] Verbose turns on the
                    // high-frequency traces (per-syscall filesystem, per-render
                    // tool lifecycle, per-request context diagnostics). They are
                    // off by default because they are enormous: two measured
                    // days ran to 775 MB and 171 MB, of which 73% and 99% came
                    // from a handful of such traces.
                    Picker("Detail Level", selection: $loggingManager.level) {
                        // Two fixed cases, so the localized keys are literals
                        // (AppLocalized needs a literal, not a runtime String).
                        Text("Info").tag(AppLogger.Level.info)
                        Text("Verbose").tag(AppLogger.Level.verbose)
                    }
                }
            } footer: {
                if loggingManager.isEnabled && loggingManager.level == .verbose {
                    Text("Verbose adds high-frequency traces (filesystem, rendering, context). Useful when reproducing a specific problem — logs grow very quickly, so switch back to Info afterwards.")
                } else {
                    Text("When enabled, all console output is captured to daily log files.")
                }
            }

            Section("Log Files") {
                if vm.runningFiles.isEmpty {
                    Text("No log files")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(vm.runningFiles) { file in
                        NavigationLink {
                            LogDetailView(url: file.url, name: file.name)
                        } label: {
                            HStack {
                                Text(file.name)
                                    .lineLimit(1)
                                Spacer()
                                Text(vm.format(file.size))
                                    .foregroundStyle(.secondary)
                            }
                        }
                    }
                    .onDelete { indexSet in
                        let files = vm.runningFiles
                        for index in indexSet {
                            LoggingManager.shared.deleteLog(at: files[index].url)
                        }
                        vm.load()
                    }
                }
            }

            if !vm.crashFiles.isEmpty {
                Section("Crash Reports") {
                    NavigationLink {
                        CrashReportGroupsView(groups: vm.crashGroups)
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(.yellow)
                            VStack(alignment: .leading, spacing: 2) {
                                Text("崩溃报告")
                                HStack(spacing: 4) {
                                    Text("\(vm.crashFiles.count) 份")
                                    if let latest = vm.crashGroups.first?.latest?.date ?? vm.crashFiles.first?.date {
                                        Text("· 最近 \(crashTimeText(latest))")
                                    }
                                    Text("· 已按原因合并")
                                }
                                .font(.caption)
                                .foregroundStyle(.secondary)
                            }
                            Spacer()
                        }
                    }
                }
            }

            if #available(iOS 17.0, *) {
                Section {
                    NavigationLink {
                        SyncLogView()
                    } label: {
                        HStack {
                            Label("iCloud Sync Logs", systemImage: "icloud.fill")
                            Spacer()
                            Text("\(SyncLogStore.shared.entries.count)")
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            }

            if !vm.logFiles.isEmpty {
                Section {
                    Button(role: .destructive) {
                        showDeleteAllConfirm = true
                    } label: {
                        HStack {
                            Label("Delete All Logs", systemImage: "trash")
                            Spacer()
                            Text(vm.format(vm.totalSize))
                                .foregroundStyle(.secondary)
                        }
                    }
                } footer: {
                    Text("Total log storage: \(vm.format(vm.totalSize))")
                }
            }
        }
        .toolbar {

                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        showShareSheet = true
                    } label: {
                        Image(systemName: "square.and.arrow.up")
                    }
                }
            
        }
        .sheet(isPresented: $showShareSheet) {
            LogShareSheet(urls: vm.logFiles.map(\.url))
        }
        .alert("Delete All Logs?", isPresented: $showDeleteAllConfirm) {
            Button("Delete All", role: .destructive) {
                LoggingManager.shared.deleteAllLogs()
                vm.load()
            }
            Button("Cancel", role: .cancel) {}
        } message: {
            Text("This will delete \(vm.format(vm.totalSize)) of log files. This action cannot be undone.")
        }
    }
}

// MARK: - Log Detail View

struct LogDetailView: View {
    let url: URL
    let name: String
    @State private var content: String = ""
    @State private var isLoading = true

    var body: some View {
        Group {
            if isLoading {
                ProgressView()
            } else {
                LogTextView(text: content)
            }
        }
        .navigationTitle(name)
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    if !ExternalFileImporter.ingest(url, into: ShareCoordinator.shared, accompanyingText: "帮我分析这个崩溃日志") {
                        ShareFeedbackToast.show("发送失败，请稍后再试")
                    }
                } label: {
                    Image(systemName: "paperplane")
                }
                .accessibilityLabel("发送到会话")
            }
            ToolbarItem(placement: .topBarTrailing) {
                MinisShareLinkButton(item: url)
            }
        }
        .task {
            let fileURL = url
            let loaded = await Task.detached(priority: .userInitiated) {
                LoggingManager.shared.readLog(at: fileURL)
            }.value
            content = loaded
            isLoading = false
        }
    }
}

// MARK: - [T-crash-report-groups] Grouped list + local summary

struct CrashReportGroupsView: View {
    let groups: [CrashReportGroup]

    var body: some View {
        List {
            if let first = groups.first, let latest = first.latest {
                Section {
                    Button {
                        send(latest)
                    } label: {
                        Label("发送最新崩溃到会话", systemImage: "paperplane")
                    }
                } footer: {
                    Text("会把最新报告作为附件放进一个新会话，你再让 AI 分析。")
                }
            }

            Section {
                ForEach(groups) { group in
                    NavigationLink {
                        CrashReportGroupDetailView(group: group)
                    } label: {
                        HStack(spacing: 10) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .foregroundStyle(.yellow)
                            VStack(alignment: .leading, spacing: 2) {
                                Text(group.title)
                                if let latest = group.latest {
                                    Text("最近 \(CrashReportTime.text(latest.date)) · \(group.detail)")
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                }
                            }
                            Spacer()
                            Text("\(group.count) 次")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
            } header: {
                Text("按原因分组")
            } footer: {
                Text("共 \(total) 份，已合并相同原因；点一组看具体是哪几次。")
            }
        }
        .navigationTitle("崩溃报告")
        .navigationBarTitleDisplayMode(.inline)
    }

    private var total: Int { groups.reduce(0) { $0 + $1.count } }

    private func send(_ entry: CrashReportEntry) {
        if !ExternalFileImporter.ingest(entry.url, into: ShareCoordinator.shared, accompanyingText: "帮我分析这个崩溃日志") {
            ShareFeedbackToast.show("发送失败，请稍后再试")
        }
    }
}

struct CrashReportGroupDetailView: View {
    let group: CrashReportGroup

    var body: some View {
        List {
            Section {
                ForEach(group.entries) { entry in
                    NavigationLink {
                        LogDetailView(url: entry.url, name: entry.name)
                    } label: {
                        VStack(alignment: .leading, spacing: 2) {
                            Text(entry.name)
                                .lineLimit(1)
                            Text("\(CrashReportTime.text(entry.date)) · \(ByteCountFormatter.string(fromByteCount: entry.size, countStyle: .file))")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .swipeActions(edge: .trailing) {
                        Button {
                            send(entry)
                        } label: {
                            Label("发送到会话", systemImage: "paperplane")
                        }
                        .tint(.blue)
                    }
                }
            } header: {
                Text(group.title)
            } footer: {
                Text(group.detail)
            }
        }
        .navigationTitle(group.title)
        .navigationBarTitleDisplayMode(.inline)
    }

    private func send(_ entry: CrashReportEntry) {
        if !ExternalFileImporter.ingest(entry.url, into: ShareCoordinator.shared, accompanyingText: "帮我分析这个崩溃日志") {
            ShareFeedbackToast.show("发送失败，请稍后再试")
        }
    }
}

// MARK: - UITextView wrapper (TextKit 2 lazy layout)

private struct LogTextView: UIViewRepresentable {
    let text: String

    func makeUIView(context: Context) -> UITextView {
        let textView = UITextView()
        textView.isEditable = false
        textView.isSelectable = true
        textView.backgroundColor = .clear
        textView.font = .monospacedSystemFont(ofSize: 11, weight: .regular)
        textView.textColor = .label
        textView.textContainerInset = UIEdgeInsets(top: 12, left: 12, bottom: 12, right: 12)
        textView.dataDetectorTypes = []
        return textView
    }

    func updateUIView(_ textView: UITextView, context: Context) {
        if textView.text != text {
            textView.text = text
        }
    }
}

// MARK: - Share Sheet

private struct LogShareSheet: UIViewControllerRepresentable {
    let urls: [URL]
    func makeUIViewController(context: Context) -> UIActivityViewController {
        // [T-share-sheet-uti] See MinisShareSheet.sanitizedShareURL.
        let safe = urls.map { MinisShareSheet.sanitizedShareURL($0) ?? $0 }
        return UIActivityViewController(activityItems: safe, applicationActivities: nil)
    }
    func updateUIViewController(_ vc: UIActivityViewController, context: Context) {}
}
