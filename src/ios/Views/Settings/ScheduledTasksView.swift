import SwiftUI

/// [T-115-scheduled-detail] Scheduled task management (1.15 "定时任务 UI").
///
/// Lists every registered `AgentJob` (created via the `minis-scheduled` CLI,
/// model tool calls or App Intents), showing state, next fire time and the
/// session that created it, with a per-row enable toggle, swipe-to-delete and
/// a detail page.
///
/// Refresh model: `AgentJobRegistry` is an ObservableObject but job fields
/// mutate without @Published, so this view re-reads `registry.list()` on
/// appear and after every mutation it performs. No timers, no polling.
struct ScheduledTasksView: View {
    private let registry = AgentJobRegistry.shared

    @State private var jobs: [AgentJob] = []
    @State private var sessionTitles: [String: String] = [:]

    var body: some View {
        List {
            if jobs.isEmpty {
                Section {
                    VStack(alignment: .leading, spacing: 6) {
                        Image(systemName: "clock")
                            .font(.title2)
                            .foregroundStyle(.secondary)
                        Text(AppLocalized("No scheduled tasks yet"))
                            .font(.subheadline)
                        Text(AppLocalized("在对话中让 AI 用 minis-scheduled 创建定时任务后，它们会出现在这里。"))
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.vertical, 14)
                }
            } else {
                Section {
                    ForEach(jobs, id: \.id) { job in
                        NavigationLink {
                            ScheduledTaskDetailView(job: job) { refresh() }
                        } label: {
                            row(job)
                        }
                    }
                    .onDelete { offsets in
                        for idx in offsets {
                            let job = jobs[idx]
                            registry.cancel(jobId: job.id, reason: "deleted from scheduled tasks UI", silent: true)
                            registry.remove(jobId: job.id)
                        }
                        refresh()
                    }
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(AppLocalized("Scheduled Tasks"))
        .navigationBarTitleDisplayMode(.inline)
        .onAppear { refresh() }
    }

    // MARK: - Row

    private func row(_ job: AgentJob) -> some View {
        VStack(alignment: .leading, spacing: 3) {
            HStack(spacing: 6) {
                Text(job.title.isEmpty ? (job.label ?? job.id.prefix(8)) : job.title)
                    .font(.body.weight(.semibold))
                    .lineLimit(1)
                stateBadge(job)
            }
            Text(subtitle(job))
                .font(.caption)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 2)
    }

    private func stateBadge(_ job: AgentJob) -> some View {
        let (text, color) = Self.stateInfo(job)
        return Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(color.opacity(0.15), in: Capsule())
            .foregroundStyle(color)
    }

    static func stateInfo(_ job: AgentJob) -> (String, Color) {
        if (job.state == .pending || job.state == .running) && !job.isEnabled {
            return ("已停用", .gray)
        }
        switch job.state {
        case .pending: return ("待触发", .blue)
        case .running: return ("执行中", .green)
        case .done: return ("已完成", .gray)
        case .cancelled: return ("已取消", .secondary)
        case .failed: return ("失败", .red)
        case .timeout: return ("超时", .orange)
        }
    }

    private func subtitle(_ job: AgentJob) -> String {
        let parts: [String] = [
            scheduleText(job),
            fireCountText(job),
            ownerText(job)
        ].compactMap { $0 }
        return parts.joined(separator: " · ")
    }

    private func scheduleText(_ job: AgentJob) -> String? {
        if (job.state == .pending || job.state == .running) && !job.isEnabled {
            return nil // 停用由徽章表达
        }
        if let next = job.nextFireAt, job.state == .pending || job.state == .running {
            return "下次 " + Self.timeText(next)
        }
        if let f = job.finishedAt, job.state == .done || job.state == .failed || job.state == .timeout {
            return Self.dateText(f)
        }
        if job.state == .running {
            if let e = job.elapsed { return "已运行 " + Self.durationText(e) }
            return "运行中"
        }
        return nil
    }

    func fireCountText(_ job: AgentJob) -> String? {
        guard job.firedCount > 0 else { return nil }
        return "已触发 \(job.firedCount) 次"
    }

    private func ownerText(_ job: AgentJob) -> String? {
        guard let sid = job.creatorSessionId else { return nil }
        let name = sessionTitles[sid] ?? ("会话 " + sid.prefix(8))
        return "来自「\(name)」"
    }

    // MARK: - Refresh

    private func refresh() {
        jobs = registry.list()
        Task {
            var titles: [String: String] = [:]
            for job in jobs {
                guard let sid = job.creatorSessionId, titles[sid] == nil else { continue }
                if let s = await ChatStore.shared.getSession(sid), !s.title.isEmpty {
                    titles[sid] = s.title
                }
            }
            sessionTitles = titles
        }
    }

    // MARK: - Formatting helpers (shared with the detail page)

    static func triggerText(_ trigger: AgentJobTrigger) -> String {
        switch trigger {
        case .immediate:
            return "立即"
        case .once(let after):
            return "一次性 · \(durationText(after))后"
        case .loop(let interval, let count):
            if let count { return "循环 · 每\(durationText(interval)) · 剩余 \(count) 次" }
            return "循环 · 每\(durationText(interval)) · 无次数上限"
        case .cron(let h, let m, let days, _, _):
            let daysStr = days.isEmpty
                ? "每天"
                : days.sorted().map { weekdayName($0) }.joined(separator: "、")
            return daysStr + String(format: " %02d:%02d", h, m)
        case .onCompletion:
            return "当关联任务完成时触发"
        }
    }

    static func targetText(_ target: AgentJobTarget) -> String {
        switch target {
        case .new:
            return "新会话"
        case .followUp(let sid):
            return "在会话 \(sid.prefix(8)) 中追加一轮"
        case .rerun(let sid, _):
            return "重跑会话 \(sid.prefix(8))"
        case .childOfCurrent:
            return "当前会话（隐藏子会话）"
        }
    }

    static func durationText(_ seconds: TimeInterval) -> String {
        if seconds < 60 { return "\(Int(seconds)) 秒" }
        if seconds < 3600 { return "\(Int(seconds) / 60) 分钟" }
        return String(format: "%.1f 小时", seconds / 3600)
    }

    static func weekdayName(_ n: Int) -> String {
        let names = ["", "周一", "周二", "周三", "周四", "周五", "周六", "周日"]
        return (1...7).contains(n) ? names[n] : "周\(n)"
    }

    private static let hmFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f
    }()
    private static let mdhmFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "M月d日 HH:mm"
        return f
    }()

    static func timeText(_ date: Date) -> String {
        let cal = Calendar.current
        let hm = hmFormatter.string(from: date)
        if cal.isDateInToday(date) { return "今天 " + hm }
        if cal.isDateInTomorrow(date) { return "明天 " + hm }
        return mdhmFormatter.string(from: date)
    }

    static func dateText(_ date: Date) -> String {
        mdhmFormatter.string(from: date)
    }
}

// MARK: - Detail

/// [T-115-scheduled-detail] Full read-only view of one job + enable/delete.
struct ScheduledTaskDetailView: View {
    let job: AgentJob
    /// Called after any mutation so the parent list refreshes.
    var onChanged: () -> Void = {}

    private let registry = AgentJobRegistry.shared
    @Environment(\.dismiss) private var dismiss
    @State private var ownerName: String?

    var body: some View {
        let canToggle = job.state == .pending || job.state == .running
        List {
            Section {
                VStack(alignment: .leading, spacing: 4) {
                    HStack(spacing: 6) {
                        Text(job.title.isEmpty ? (job.label ?? job.id.prefix(8)) : job.title)
                            .font(.headline)
                        ScheduledTasksView.stateInfoBadge(job)
                    }
                    Text("创建于 " + ScheduledTasksView.dateText(job.createdAt)
                         + (job.firedCount > 0 ? " · 执行 \(job.firedCount) 次" : ""))
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .padding(.vertical, 4)
            }

            Section(AppLocalized("Task")) {
                kv(AppLocalized("触发规则"), ScheduledTasksView.triggerText(job.trigger))
                if let next = job.nextFireAt, job.state == .pending || job.state == .running {
                    kv(AppLocalized("下次触发"), ScheduledTasksView.timeText(next))
                }
                kv(AppLocalized("任务内容"), job.prompt ?? job.title)
                kv(AppLocalized("落在"), ScheduledTasksView.targetText(job.target))
                if let model = job.modelEntryId { kv("模型", model) }
                if let owner = ownerName { kv(AppLocalized("创建自"), owner) }
            }

            Section(AppLocalized("History")) {
                kv(AppLocalized("状态"), ScheduledTasksView.stateText(job))
                if let last = job.lastFireOk {
                    kv(AppLocalized("最近一次"), last ? "成功" : "失败")
                }
                if let result = job.resultText, !result.isEmpty {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(AppLocalized("结果")).font(.caption).foregroundStyle(.secondary)
                        Text(result).font(.footnote)
                    }
                    .padding(.vertical, 2)
                }
                if let elapsed = job.elapsed {
                    kv(AppLocalized("耗时"), ScheduledTasksView.durationText(elapsed))
                }
            }

            if canToggle {
                Section {
                    Toggle(isOn: Binding(
                        get: { job.isEnabled },
                        set: { v in
                            registry.setEnabled(jobId: job.id, enabled: v)
                            onChanged()
                        }
                    )) {
                        Text(AppLocalized("启用此任务"))
                    }
                } footer: {
                    Text(AppLocalized("关闭后任务不再触发；重新打开立即恢复排程。"))
                }
            }

            Section {
                Button(role: .destructive) {
                    registry.cancel(jobId: job.id, reason: "deleted from scheduled task detail", silent: true)
                    registry.remove(jobId: job.id)
                    onChanged()
                    dismiss()
                } label: {
                    Text(AppLocalized("删除此任务")).frame(maxWidth: .infinity)
                }
            } footer: {
                Text(AppLocalized("删除会立即停止并移除任务，无法恢复。"))
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle(AppLocalized("Task Detail"))
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            guard let sid = job.creatorSessionId else { return }
            Task {
                if let s = await ChatStore.shared.getSession(sid), !s.title.isEmpty {
                    ownerName = "「\(s.title)」会话"
                }
            }
        }
    }

    private func kv(_ key: String, _ value: String) -> some View {
        HStack(alignment: .top) {
            Text(key).foregroundStyle(.secondary)
            Spacer(minLength: 16)
            Text(value).multilineTextAlignment(.trailing)
        }
        .font(.subheadline)
        .padding(.vertical, 2)
    }
}

extension ScheduledTasksView {
    /// Badge view for the detail page header.
    static func stateInfoBadge(_ job: AgentJob) -> some View {
        let (text, color) = stateInfo(job)
        return Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 7)
            .padding(.vertical, 2)
            .background(color.opacity(0.15), in: Capsule())
            .foregroundStyle(color)
    }

    static func stateText(_ job: AgentJob) -> String {
        let (text, _) = stateInfo(job)
        return text
    }
}