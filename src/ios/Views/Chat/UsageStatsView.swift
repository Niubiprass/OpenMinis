import SwiftUI

// MARK: - ViewModel

@MainActor
class UsageStatsViewModel: ObservableObject {
    /// [T-token-attribution-snapshot] How much to trust a row's model.
    enum Attribution: String {
        /// Per-message snapshot: the model that actually served the request.
        case measured
        /// Pre-snapshot row, inferred from the session's CURRENT model. Shown,
        /// but labelled — it may be wrong if the session ever switched models.
        case estimated
        /// Orphaned row: no snapshot and no session left to infer from.
        case unknownSession
        /// Snapshot present but the model is gone from the live config
        /// (provider deleted). Renders normally FROM the snapshot — this is the
        /// case that used to disappear into "Other".
        case measuredRemoved
    }

    struct ModelStats {
        let modelId: String
        let displayName: String
        var attribution: Attribution = .measured
        /// Provider section resolved from the snapshot's ProviderType rawValue,
        /// which survives the provider being deleted. nil falls back to the
        /// live-config lookup.
        var providerGroupOverride: String? = nil
        var inputTokens: Int = 0
        var outputTokens: Int = 0
        var cacheCreationTokens: Int = 0
        var cacheReadTokens: Int = 0
        var distinctDays: Set<String> = []
        var distinctSessions: Set<String> = []

        /// Unique per (model, attribution) — see the ForEach that uses it.
        var rowKey: String { "\(modelId)#\(attribution.rawValue)" }

        /// One short line for the two states a user can act on, else nil.
        ///
        /// `.estimated` deliberately returns nil. It was explained at first,
        /// but it is by far the most common state — every row predating the
        /// per-message columns — and repeating the same sentence under almost
        /// every row read as noise rather than information. The distinction is
        /// still enforced underneath: estimated rows keep their own bucket and
        /// never merge into a measured one, so the numbers stay honest even
        /// with the label gone.
        var attributionCaveat: String? {
            switch attribution {
            case .measured, .estimated:
                return nil
            case .unknownSession:
                return AppLocalized(
                    "Model unknown — the session record was deleted",
                    comment: "Usage stats: orphaned row")
            case .measuredRemoved:
                return AppLocalized(
                    "No longer in your configured providers",
                    comment: "Usage stats: model removed from config")
            }
        }

        var totalTokens: Int { inputTokens + outputTokens + cacheCreationTokens + cacheReadTokens }
        var dailyAvgTokens: Int {
            let days = max(distinctDays.count, 1)
            return totalTokens / days
        }
        var sessionAvgTokens: Int {
            let sessions = max(distinctSessions.count, 1)
            return totalTokens / sessions
        }
    }

    struct ProviderGroup: Identifiable {
        let id: String // provider name
        var models: [ModelStats]
        var totalTokens: Int { models.reduce(0) { $0 + $1.totalTokens } }
    }

    @Published var providers: [ProviderGroup] = []
    @Published var grandTotalInput: Int = 0
    @Published var grandTotalOutput: Int = 0
    @Published var grandTotalCacheCreation: Int = 0
    @Published var grandTotalCacheRead: Int = 0
    @Published var isLoaded = false
    /// [T-p2-helper-usage] delegate_task counts + helper token cost.
    @Published var helperStats: ChatStore.HelperUsageStats?
    /// [T-usage-redesign] 顶部时间范围与按范围的汇总。
    enum UsageRange: String, CaseIterable, Identifiable {
        case today, week, month, all
        var id: String { rawValue }
        var title: String {
            switch self {
            case .today: return AppLocalized("今天")
            case .week:  return AppLocalized("7 天")
            case .month: return AppLocalized("30 天")
            case .all:   return AppLocalized("全部")
            }
        }
        /// 固定窗口天数；nil = 全部（用实际跨度）。
        var days: Int? {
            switch self {
            case .today: return 1
            case .week:  return 7
            case .month: return 30
            case .all:   return nil
            }
        }
    }

    struct DailyPoint: Identifiable {
        let id = UUID()
        let day: Date
        let total: Int
    }

    struct GroupSlice: Identifiable {
        let id: String
        let name: String
        let total: Int
    }

    @Published var range: UsageRange = .week
    @Published var summaryInput = 0
    @Published var summaryOutput = 0
    @Published var summaryCacheRead = 0
    @Published var summaryCacheCreate = 0
    @Published var summaryDaily: [DailyPoint] = []
    @Published var summaryActiveDays = 0
    @Published var summaryDaysInRange = 1
    @Published var summaryByProvider: [GroupSlice] = []
    @Published var summaryByModel: [GroupSlice] = []
    /// [T-usage-today-hourly] 「今天」按小时聚合（24 个桶）。
    @Published var summaryHourly: [Int] = []

    private var rawRecords: [ChatStore.UsageRecord] = []
    private var groupForModelId: [String: String] = [:]
    private var displayForModelId: [String: String] = [:]

    func setRange(_ r: UsageRange) {
        guard r != range else { return }
        range = r
        rebuildSummary()
    }

    private static let dayFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "yyyy-MM-dd"
        return f
    }()

    func load() async {
        let records = await ChatStore.shared.fetchUsageStats()
        helperStats = await ChatStore.shared.fetchHelperUsage()

        // Resolve each model id to a PROVIDER-TYPE group (what the user sees in
        // the Providers list — OpenAI + its compatibles, Anthropic, Gemini, xAI,
        // OpenRouter, …). We group by ProviderType, NOT by the model's own
        // `provider` string (which is inconsistent: "Gemini"/"OpenRouter"/"doubao"
        // …). Priority for a given model id:
        //   1) a configured provider instance that owns this model → its
        //      providerType.displayName (an OpenAI-compatible vendor like DeepSeek/
        //      Groq/Doubao/Azure all correctly fold into "OpenAI").
        //   2) a static built-in model → its provider, normalized.
        //   3) neither (a since-deleted instance / renamed model) → "Other".
        let store = ProviderConfigStore.shared
        // modelId → providerType.displayName, from configured instances.
        let instanceMap = Dictionary(store.instances.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        var modelIdToProviderGroup: [String: String] = [:]
        for entry in store.modelEntries {
            if let inst = instanceMap[entry.providerInstanceId] {
                modelIdToProviderGroup[entry.model.id] = inst.providerType.displayName
            }
        }
        // Fallback map + display names from static built-in models.
        let staticLookup = Dictionary(LLMModel.allModels.map { ($0.id, $0) }, uniquingKeysWith: { a, _ in a })
        func providerGroup(for modelId: String) -> String {
            if let g = modelIdToProviderGroup[modelId] { return g }
            if let p = staticLookup[modelId]?.provider {
                // Normalize built-in provider strings to ProviderType display names.
                switch p {
                case "Google", "Gemini", "Google Gemini": return ProviderType.gemini.displayName
                case "xAI":       return ProviderType.xAI.displayName
                case "OpenRouter": return ProviderType.openRouter.displayName
                default:          return p   // "Anthropic"/"OpenAI" already canonical
                }
            }
            return AppLocalized("Other", comment: "Usage stats: unknown provider group")
        }
        let modelLookup = staticLookup.merging(
            Dictionary(store.modelEntries.map { ($0.model.id, $0.model) }, uniquingKeysWith: { a, _ in a }),
            uniquingKeysWith: { _, configured in configured })

        // Group by modelId
        var statsByModel: [String: ModelStats] = [:]
        for record in records {
            let model = modelLookup[record.modelId]

            // [T-token-attribution-snapshot] Four distinct states. They must not
            // share a bucket: an estimated row merged into a measured one
            // inherits credibility it does not have, which is precisely how the
            // original mis-attribution stayed invisible.
            let attribution: Attribution
            if record.modelId.isEmpty {
                attribution = .unknownSession
            } else if !record.hasSnapshot {
                attribution = .estimated
            } else if model == nil {
                attribution = .measuredRemoved
            } else {
                attribution = .measured
            }

            // Prefer the snapshot's own strings — for a model whose provider
            // has been deleted they are the only surviving human-readable name.
            let displayName = record.modelDisplayName?.isEmpty == false
                ? record.modelDisplayName!
                : (model?.displayName ?? record.modelId)

            let key = "\(record.modelId)#\(attribution.rawValue)"
            var stats = statsByModel[key] ?? ModelStats(
                modelId: record.modelId, displayName: displayName,
                attribution: attribution,
                // Snapshot rawValue wins; it is stable and locale-independent,
                // unlike the display strings that produced duplicate
                // "Google" / "Gemini" / "Google Gemini" sections.
                providerGroupOverride: record.providerType.flatMap {
                    ProviderType(rawValue: $0)?.displayName
                }
            )
            stats.inputTokens += record.usage.inputTokens
            stats.outputTokens += record.usage.outputTokens
            stats.cacheCreationTokens += record.usage.cacheCreationTokens
            stats.cacheReadTokens += record.usage.cacheReadTokens
            stats.distinctDays.insert(Self.dayFormatter.string(from: record.date))
            stats.distinctSessions.insert(record.sessionId)
            statsByModel[key] = stats
        }

        // Group by PROVIDER TYPE (the Providers-list grouping).
        var providerMap: [String: [ModelStats]] = [:]
        for (_, stats) in statsByModel {
            let group = stats.providerGroupOverride ?? providerGroup(for: stats.modelId)
            providerMap[group, default: []].append(stats)
        }

        // Emit every group — a preferred ProviderType order first, then any
        // remaining groups (e.g. "Other") appended so NOTHING is silently dropped.
        let preferredOrder = ProviderType.allCases.map(\.displayName)
        var groups: [ProviderGroup] = []
        var emitted = Set<String>()
        func emit(_ provider: String) {
            guard !emitted.contains(provider), var models = providerMap[provider] else { return }
            emitted.insert(provider)
            models.sort { $0.totalTokens > $1.totalTokens }
            groups.append(ProviderGroup(id: provider, models: models))
        }
        for p in preferredOrder { emit(p) }
        for p in providerMap.keys.sorted() { emit(p) }   // leftovers (incl. "Other")

        grandTotalInput = statsByModel.values.reduce(0) { $0 + $1.inputTokens }
        grandTotalOutput = statsByModel.values.reduce(0) { $0 + $1.outputTokens }
        grandTotalCacheCreation = statsByModel.values.reduce(0) { $0 + $1.cacheCreationTokens }
        grandTotalCacheRead = statsByModel.values.reduce(0) { $0 + $1.cacheReadTokens }
        providers = groups

        // [T-usage-redesign] 保存原始记录供范围切换使用，并算一份当前范围汇总。
        rawRecords = records
        for r in records where groupForModelId[r.modelId] == nil {
            groupForModelId[r.modelId] = providerGroup(for: r.modelId)
        }
        for r in records {
            if let dn = r.modelDisplayName, !dn.isEmpty, displayForModelId[r.modelId] == nil {
                displayForModelId[r.modelId] = dn
            }
        }
        rebuildSummary()

        isLoaded = true
    }

    /// [T-usage-redesign] 按当前时间范围重算顶部汇总、每日序列与分组占比。
    private func rebuildSummary() {
        let cal = Calendar.current
        let startOfToday = cal.startOfDay(for: Date())
        let cutoff: Date? = range.days.flatMap {
            cal.date(byAdding: .day, value: -($0 - 1), to: startOfToday)
        }
        var inp = 0, out = 0, cacheRead = 0, cacheCreate = 0
        var byDay: [Date: Int] = [:]
        var byProvider: [String: Int] = [:]
        var byModel: [String: Int] = [:]

        for r in rawRecords {
            if let c = cutoff, r.date < c { continue }
            inp += r.usage.inputTokens
            out += r.usage.outputTokens
            cacheRead += r.usage.cacheReadTokens
            cacheCreate += r.usage.cacheCreationTokens
            let total = r.usage.inputTokens + r.usage.outputTokens
                + r.usage.cacheReadTokens + r.usage.cacheCreationTokens
            byDay[cal.startOfDay(for: r.date), default: 0] += total
            byProvider[groupForModelId[r.modelId] ?? "Other", default: 0] += total
            byModel[r.modelId, default: 0] += total
        }

        summaryInput = inp
        summaryOutput = out
        summaryCacheRead = cacheRead
        summaryCacheCreate = cacheCreate
        summaryActiveDays = byDay.count

        if let d = range.days {
            summaryDaysInRange = d
            var pts: [DailyPoint] = []
            for i in 0..<d {
                if let day = cal.date(byAdding: .day, value: -(d - 1 - i), to: startOfToday) {
                    pts.append(DailyPoint(day: day, total: byDay[day] ?? 0))
                }
            }
            summaryDaily = pts
        } else {
            let days = byDay.keys.sorted()
            summaryDaily = days.suffix(14).map { DailyPoint(day: $0, total: byDay[$0] ?? 0) }
            if let first = days.first {
                summaryDaysInRange = max(1, (cal.dateComponents([.day], from: first, to: startOfToday).day ?? 0) + 1)
            } else {
                summaryDaysInRange = 1
            }
        }

        // [T-usage-today-hourly] 今天单独按小时聚合，供柱状图使用。
        if range == .today {
            var hours = [Int](repeating: 0, count: 24)
            for r in rawRecords where r.date >= startOfToday {
                let h = cal.component(.hour, from: r.date)
                guard h >= 0, h < 24 else { continue }
                hours[h] += r.usage.inputTokens + r.usage.outputTokens
                    + r.usage.cacheReadTokens + r.usage.cacheCreationTokens
            }
            summaryHourly = hours
        } else {
            summaryHourly = []
        }

        summaryByProvider = byProvider
            .map { GroupSlice(id: $0.key, name: $0.key, total: $0.value) }
            .sorted { $0.total > $1.total }
        summaryByModel = byModel
            .map { GroupSlice(id: $0.key, name: displayForModelId[$0.key] ?? $0.key, total: $0.value) }
            .sorted { $0.total > $1.total }
    }
}

// MARK: - View

struct UsageStatsView: View {
    @StateObject private var vm = UsageStatsViewModel()
    @State private var groupMode: GroupMode = .provider

    private enum GroupMode { case provider, model }

    private var totalAll: Int {
        vm.summaryInput + vm.summaryOutput + vm.summaryCacheRead + vm.summaryCacheCreate
    }
    private var totalInputInclCache: Int {
        vm.summaryInput + vm.summaryCacheRead + vm.summaryCacheCreate
    }
    private var hitRate: Double {
        totalInputInclCache > 0 ? Double(vm.summaryCacheRead) / Double(totalInputInclCache) * 100 : 0
    }
    private var dailyAvg: Int {
        vm.summaryDaysInRange > 0 ? totalAll / vm.summaryDaysInRange : 0
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 14) {
                rangePicker

                if !vm.isLoaded {
                    ProgressView().padding(.top, 40)
                } else if totalAll == 0 {
                    Text("No usage data yet. Start a conversation to see token statistics here.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 20)
                } else {
                    summaryCard
                    chartCard
                    groupPicker
                    groupList
                }

                if let h = vm.helperStats, h.delegateCalls > 0 || h.childSessions > 0 {
                    helperCard(h)
                }
            }
            .padding(.horizontal, 16)
            .padding(.top, 8)
            .padding(.bottom, 28)
        }
        .background(Color(UIColor.systemGroupedBackground))
        .navigationTitle("Usage")
        .navigationBarTitleDisplayMode(.inline)
        .task { await vm.load() }
    }

    // MARK: 时间范围

    private var rangePicker: some View {
        HStack(spacing: 0) {
            ForEach(UsageStatsViewModel.UsageRange.allCases) { r in
                let selected = vm.range == r
                Button {
                    vm.setRange(r)
                } label: {
                    Text(r.title)
                        .font(.system(size: 13, weight: selected ? .semibold : .regular))
                        .foregroundStyle(selected ? Color.primary : Color.secondary)
                        .frame(maxWidth: .infinity)
                        .frame(height: 26)
                        .background(
                            RoundedRectangle(cornerRadius: 13, style: .continuous)
                                .fill(selected ? Color(UIColor.tertiarySystemFill) : .clear)
                        )
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(Color(UIColor.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    // MARK: 总 Token 卡片

    private var summaryCard: some View {
        VStack(alignment: .leading, spacing: 0) {
            Text("总 Token").font(.system(size: 13)).foregroundStyle(.secondary)
                .padding(.bottom, 6)
            Text(formatBig(totalAll)).font(.system(size: 34, weight: .bold))
                .padding(.bottom, 6)
            Text("不含缓存读取 \(formatCount(totalAll - vm.summaryCacheRead))")
                .font(.system(size: 13)).foregroundStyle(.secondary)
                .padding(.bottom, 6)

            HStack(spacing: 0) {
                Text("日均 \(formatCount(dailyAvg))")
                Spacer()
                Text("活跃天数 \(vm.summaryActiveDays)/\(vm.summaryDaysInRange)")
            }
            .font(.system(size: 12)).foregroundStyle(.tertiary)
            .padding(.bottom, 14)

            // 构成条
            GeometryReader { geo in
                let w = geo.size.width
                HStack(spacing: 0) {
                    segment(frac: ratio(vm.summaryInput), color: .blue, total: w)
                    segment(frac: ratio(vm.summaryCacheRead), color: Color(red: 0.38, green: 0.65, blue: 0.86), total: w)
                    segment(frac: ratio(vm.summaryCacheCreate), color: .orange, total: w)
                    segment(frac: ratio(vm.summaryOutput), color: .green, total: w)
                }
                .frame(height: 6)
                .clipShape(Capsule())
            }
            .frame(height: 6)
            .padding(.bottom, 12)

            // 图例：两列，值右对齐
            let cols = legendItems
            HStack(alignment: .top, spacing: 0) {
                legendColumn(Array(cols.prefix(2)))
                legendColumn(Array(cols.suffix(from: 2)))
            }

            Divider().padding(.vertical, 12)

            HStack {
                Text("缓存命中率").font(.system(size: 13)).foregroundStyle(.secondary)
                Spacer()
                Text(String(format: "%.1f%%", hitRate)).font(.system(size: 13, weight: .semibold))
            }
        }
        .padding(16)
        .background(Color(UIColor.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private struct LegendItem { let name: String; let value: String; let color: Color }

    private var legendItems: [LegendItem] {
        [LegendItem(name: "输入", value: formatCount(vm.summaryInput), color: .blue),
         LegendItem(name: "缓存写入", value: formatCount(vm.summaryCacheCreate), color: .orange),
         LegendItem(name: "缓存读取", value: formatCount(vm.summaryCacheRead),
                    color: Color(red: 0.38, green: 0.65, blue: 0.86)),
         LegendItem(name: "输出", value: formatCount(vm.summaryOutput), color: .green)]
    }

    @ViewBuilder
    private func legendColumn(_ items: [LegendItem]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(items.enumerated()), id: \.offset) { _, item in
                HStack(spacing: 6) {
                    Circle().fill(item.color).frame(width: 6, height: 6)
                    Text(item.name).font(.system(size: 11)).foregroundStyle(.secondary)
                    Spacer(minLength: 4)
                    Text(item.value).font(.system(size: 11, weight: .semibold))
                }
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.trailing, 8)
    }

    private func ratio(_ v: Int) -> Double {
        totalAll > 0 ? Double(v) / Double(totalAll) : 0
    }

    @ViewBuilder
    private func segment(frac: Double, color: Color, total: CGFloat) -> some View {
        if frac > 0 {
            Rectangle().fill(color).frame(width: max(2, total * frac))
        }
    }

    // MARK: 柱状图

    private struct ChartPoint {
        let label: String
        let value: Int
        let showLabel: Bool
    }

    /// [T-usage-chart-axis] 统一取"能被 4 等分的整齐上限"：刻度只会是
    /// 1 / 2 / 2.5 / 5 这类数字，不会冒出 67M、33M 这种怪值。
    private func niceMax(_ v: Int) -> Int {
        guard v > 0 else { return 4 }
        let raw = Double(v) / 4.0
        let exp = pow(10, floor(log10(raw)))
        for m in [1.0, 2.0, 2.5, 5.0, 10.0] where raw <= exp * m {
            return Int(exp * m * 4)
        }
        return Int(exp * 40)
    }

    private func shortNumber(_ v: Int) -> String {
        if v >= 1_000_000_000 { return String(format: "%.0fB", Double(v) / 1_000_000_000) }
        if v >= 1_000_000 { return String(format: "%.0fM", Double(v) / 1_000_000) }
        if v >= 1000 { return String(format: "%.0fk", Double(v) / 1000) }
        return "\(v)"
    }

    private var chartCard: some View {
        let hourly = (vm.range == .today)
        let rawPoints: [(String, Int)] = hourly
            ? vm.summaryHourly.enumerated().map { ("\($0.offset)", $0.element) }
            : vm.summaryDaily.map { (shortDay($0.day), $0.total) }

        let count = max(1, rawPoints.count)
        let stride: Int = {
            if hourly { return 6 }
            if count <= 7 { return 1 }
            return max(1, Int(ceil(Double(count) / 6.0)))
        }()
        let points: [ChartPoint] = rawPoints.enumerated().map { idx, item in
            ChartPoint(label: item.0, value: item.1,
                       showLabel: idx % stride == 0 || idx == count - 1)
        }

        let maxValue = niceMax(points.map(\.value).max() ?? 0)
        let peak = points.map(\.value).max() ?? 0

        return VStack(alignment: .leading, spacing: 12) {
            HStack(spacing: 8) {
                Text(hourly ? "今天" : "每日用量")
                    .font(.system(size: 13, weight: .semibold))
                Spacer(minLength: 8)
                Text((hourly ? "按小时 · " : "") + "峰值 \(shortNumber(peak))")
                    .font(.system(size: 11))
                    .foregroundStyle(.tertiary)
            }

            HStack(alignment: .top, spacing: 8) {
                // Y 轴：5 个刻度，右对齐
                VStack(alignment: .trailing, spacing: 0) {
                    ForEach(Array((0...4).reversed()), id: \.self) { i in
                        Text(shortNumber(maxValue * i / 4))
                            .font(.system(size: 9))
                            .foregroundStyle(.tertiary)
                            .frame(height: 16, alignment: .top)
                        if i > 0 { Spacer(minLength: 0) }
                    }
                }
                .frame(width: 34, height: 132, alignment: .topTrailing)

                VStack(spacing: 6) {
                    GeometryReader { geo in
                        let w = geo.size.width
                        let h = geo.size.height
                        let slot = w / CGFloat(count)
                        ZStack(alignment: .bottom) {
                            // 网格线
                            VStack(spacing: 0) {
                                ForEach(0..<5, id: \.self) { i in
                                    Rectangle()
                                        .fill(Color(UIColor.quaternaryLabel).opacity(0.35))
                                        .frame(height: 0.5)
                                    if i < 4 { Spacer(minLength: 0) }
                                }
                            }
                            // 柱体
                            HStack(alignment: .bottom, spacing: 0) {
                                ForEach(Array(points.enumerated()), id: \.offset) { _, p in
                                    let barW = min(hourly ? 9 : 16, max(6, slot * 0.55))
                                    Group {
                                        if p.value <= 0 {
                                            RoundedRectangle(cornerRadius: 1)
                                                .fill(Color(UIColor.tertiaryLabel).opacity(0.45))
                                                .frame(width: barW, height: 2)
                                        } else {
                                            RoundedRectangle(cornerRadius: 3, style: .continuous)
                                                .fill(Color(red: 0.29, green: 0.43, blue: 0.67))
                                                .frame(width: barW,
                                                       height: max(3, h * 0.94 * CGFloat(p.value) / CGFloat(maxValue)))
                                        }
                                    }
                                    .frame(width: slot)
                                    .frame(maxHeight: .infinity, alignment: .bottom)
                                }
                            }
                        }
                    }
                    .frame(height: 132)

                    // X 轴标签
                    HStack(spacing: 0) {
                        ForEach(Array(points.enumerated()), id: \.offset) { _, p in
                            Text(p.showLabel ? p.label : " ")
                                .font(.system(size: 9))
                                .foregroundStyle(.tertiary)
                                .lineLimit(1)
                                .frame(maxWidth: .infinity)
                        }
                    }
                    .frame(height: 12)
                }
            }
        }
        .padding(16)
        .background(Color(UIColor.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func shortDay(_ d: Date) -> String {
        let f = DateFormatter()
        f.dateFormat = "M/d"
        return f.string(from: d)
    }

    // MARK: 分组

    private var groupPicker: some View {
        HStack(spacing: 0) {
            ForEach([GroupMode.provider, GroupMode.model], id: \.self) { mode in
                let selected = groupMode == mode
                Button {
                    groupMode = mode
                } label: {
                    Text(mode == .provider ? "按服务商" : "按模型")
                        .font(.system(size: 13, weight: selected ? .semibold : .regular))
                        .foregroundStyle(selected ? Color.primary : Color.secondary)
                        .frame(maxWidth: .infinity)
                        .frame(height: 24)
                        .background(
                            RoundedRectangle(cornerRadius: 12, style: .continuous)
                                .fill(selected ? Color(UIColor.tertiarySystemFill) : .clear)
                        )
                }
                .buttonStyle(.plain)
            }
        }
        .padding(3)
        .background(Color(UIColor.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 15, style: .continuous))
    }

    private var groupList: some View {
        let slices = groupMode == .provider ? vm.summaryByProvider : vm.summaryByModel
        return VStack(spacing: 0) {
            ForEach(Array(slices.enumerated()), id: \.element.id) { idx, s in
                if idx > 0 { Divider().padding(.leading, 16) }
                HStack(spacing: 8) {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(s.name).font(.system(size: 14, weight: .medium)).lineLimit(1)
                        Text(formatCount(s.total)).font(.system(size: 11)).foregroundStyle(.secondary)
                    }
                    Spacer(minLength: 8)
                    Text(percentText(s.total)).font(.system(size: 12, weight: .semibold))
                        .foregroundStyle(.secondary)
                    Image(systemName: "chevron.right")
                        .font(.system(size: 11, weight: .semibold))
                        .foregroundStyle(.tertiary)
                }
                .padding(.horizontal, 16)
                .frame(height: 56)
            }
        }
        .background(Color(UIColor.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func percentText(_ v: Int) -> String {
        guard totalAll > 0 else { return "0%" }
        let p = Double(v) / Double(totalAll) * 100
        return p >= 99.95 ? "100%" : String(format: "%.1f%%", p)
    }

    // MARK: 代理任务

    private func helperCard(_ h: ChatStore.HelperUsageStats) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text("代理任务").font(.system(size: 13)).foregroundStyle(.secondary)
            helperRow("委派次数", "\(h.delegateCalls)")
            helperRow("Primary / Sub 档", "\(h.primaryRuns) / \(h.subRuns)")
            helperRow("代理任务输入 Token", formatCount(h.helperInputTokens))
            helperRow("代理任务输出 Token", formatCount(h.helperOutputTokens))
        }
        .padding(16)
        .background(Color(UIColor.secondarySystemGroupedBackground),
                    in: RoundedRectangle(cornerRadius: 16, style: .continuous))
    }

    private func helperRow(_ title: String, _ value: String) -> some View {
        HStack {
            Text(title).font(.system(size: 13)).foregroundStyle(.secondary)
            Spacer()
            Text(value).font(.system(size: 13, weight: .medium))
        }
    }

    private func formatBig(_ count: Int) -> String {
        if count >= 1_000_000_000 {
            return String(format: "%.1fB", Double(count) / 1_000_000_000)
        }
        if count >= 1_000_000 {
            return String(format: "%.1fM", Double(count) / 1_000_000)
        }
        return formatCount(count)
    }

    private func formatCount(_ count: Int) -> String {
        if count >= 1_000_000 {
            let m = Double(count) / 1_000_000.0
            return String(format: "%.1fM", m)
        }
        if count >= 1000 {
            let k = Double(count) / 1000.0
            return k.truncatingRemainder(dividingBy: 1) == 0
                ? "\(Int(k))k"
                : String(format: "%.1fk", k)
        }
        return "\(count)"
    }
}
