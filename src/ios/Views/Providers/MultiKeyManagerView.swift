import SwiftUI

/// [T-multikey] Key ring management for one provider.
///
/// Layout follows the approved mock: a stats card, a strategy row, the key
/// list, and an add button. Every string is Chinese and explains itself —
/// the goal is that a non-technical reader can tell why a key is being skipped.
struct MultiKeyManagerView: View {

    let instance: ProviderInstance

    @State private var keys: [ProviderAPIKey] = []
    @State private var strategy: MultiKeyStrategy = .roundRobin
    @State private var showAdd = false
    @State private var newKeyText = ""
    @State private var newKeyName = ""

    private var manager: ProviderMultiKeyManager { .shared }

    var body: some View {
        List {
            Section {
                statRow("总数", "\(keys.count)", color: .primary)
                statRow("正常", "\(okCount)", color: .green)
                statRow("错误", "\(badCount)", color: badCount > 0 ? .red : .secondary)
            }

            Section {
                NavigationLink(destination: MultiKeyStrategyView(selection: $strategy)
                        .onDisappear {
                            manager.setStrategy(strategy, for: instance.id)
                        }) {
                    HStack {
                        Text("负载均衡策略")
                        Spacer()
                        Text(strategy.displayName)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section {
                if keys.isEmpty {
                    Text("还没有添加 Key")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(keys) { k in
                        keyRow(k)
                    }
                    .onDelete { indexSet in
                        for i in indexSet { manager.remove(keyId: keys[i].id, for: instance.id) }
                        reload()
                    }
                }
                Button {
                    newKeyText = ""
                    newKeyName = ""
                    showAdd = true
                } label: {
                    Label("添加 Key", systemImage: "plus.circle.fill")
                }
            } header: {
                Text("Key 列表")
            } footer: {
                Text("出错的 Key 不会删除，只是暂时跳过。5 分钟后会自动再试一次，也可以右滑重新启用。")
            }
        }
        .navigationTitle(Text("多 Key 管理"))
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            strategy = manager.strategy(for: instance.id)
            reload()
        }
        .sheet(isPresented: $showAdd) {
            addSheet
        }
    }

    // MARK: - Pieces

    private var okCount: Int {
        keys.filter { $0.isSelectable(recoveryInterval: ProviderMultiKeyManager.recoveryInterval) }.count
    }

    private var badCount: Int { keys.count - okCount }

    private func statRow(_ title: String, _ value: String, color: Color) -> some View {
        HStack {
            Text(title)
            Spacer()
            Text(value)
                .foregroundStyle(color)
                .font(.system(size: 19, weight: .regular))
        }
    }

    @ViewBuilder
    private func keyRow(_ k: ProviderAPIKey) -> some View {
        let selectable = k.isSelectable(recoveryInterval: ProviderMultiKeyManager.recoveryInterval)
        HStack(alignment: .center, spacing: 10) {
            Circle()
                .fill(selectable ? Color.green : Color.red)
                .frame(width: 8, height: 8)

            VStack(alignment: .leading, spacing: 3) {
                Text(k.masked)
                    .font(.system(size: 14, design: .monospaced))
                Text(subtitle(for: k, selectable: selectable))
                    .font(.caption2)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
            }

            Spacer()

            Text(selectable ? "正常" : badgeText(k))
                .font(.system(size: 10.5, weight: .medium))
                .foregroundStyle(selectable ? Color.green : Color.red)
                .padding(.horizontal, 7)
                .padding(.vertical, 2)
                .background(
                    (selectable ? Color.green : Color.red).opacity(0.14),
                    in: Capsule()
                )
        }
        .swipeActions(edge: .leading, allowsFullSwipe: true) {
            if !selectable {
                Button {
                    manager.reactivate(keyId: k.id, for: instance.id)
                    reload()
                } label: {
                    Label("恢复使用", systemImage: "arrow.clockwise")
                }
                .tint(.green)
            }
        }
    }

    private func badgeText(_ k: ProviderAPIKey) -> String {
        if !k.isEnabled { return "已停用" }
        if k.status == .error { return "错误" }
        return "不可用"
    }

    private func subtitle(for k: ProviderAPIKey, selectable: Bool) -> String {
        var parts: [String] = []
        if let name = k.name, !name.isEmpty { parts.append(name) }
        parts.append("成功 \(k.successCount) 次")
        if let err = k.lastError, !err.isEmpty, !selectable {
            parts.append(err)
        } else if let used = k.lastUsed {
            parts.append(Self.relative(used))
        }
        return parts.joined(separator: " · ")
    }

    private static func relative(_ date: Date) -> String {
        let s = Date().timeIntervalSince(date)
        if s < 60 { return "刚刚用过" }
        if s < 3600 { return "\(Int(s / 60)) 分钟前" }
        if s < 86400 { return "\(Int(s / 3600)) 小时前" }
        return "\(Int(s / 86400)) 天前"
    }

    private var addSheet: some View {
        NavigationView {
            Form {
                Section {
                    TextField("sk-…", text: $newKeyText)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                        .font(.system(.body, design: .monospaced))
                } header: {
                    Text("API Key")
                }
                Section {
                    TextField("给这个 Key 起个名字（可选）", text: $newKeyName)
                } header: {
                    Text("备注")
                } footer: {
                    Text("备注只是为了让你在列表里分清哪个是哪个，比如「主号」「小号」。")
                }
            }
            .navigationTitle(Text("添加 Key"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { showAdd = false }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("添加") {
                        let trimmed = newKeyText.trimmingCharacters(in: .whitespacesAndNewlines)
                        guard !trimmed.isEmpty else { return }
                        let name = newKeyName.trimmingCharacters(in: .whitespacesAndNewlines)
                        _ = manager.add(trimmed, name: name.isEmpty ? nil : name, for: instance.id)
                        showAdd = false
                        reload()
                    }
                    .disabled(newKeyText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                }
            }
        }
    }

    private func reload() {
        keys = manager.keys(for: instance.id)
    }
}

/// [T-multikey] Strategy picker. Each option carries a plain-language line so
/// the choice does not require understanding what "round robin" means.
struct MultiKeyStrategyView: View {
    @Binding var selection: MultiKeyStrategy

    var body: some View {
        List {
            ForEach(MultiKeyStrategy.allCases, id: \.rawValue) { s in
                Button {
                    selection = s
                } label: {
                    HStack(alignment: .top, spacing: 10) {
                        VStack(alignment: .leading, spacing: 4) {
                            Text(s.displayName)
                                .foregroundStyle(.primary)
                            Text(s.explanation)
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .fixedSize(horizontal: false, vertical: true)
                        }
                        Spacer()
                        if selection == s {
                            Image(systemName: "checkmark")
                                .foregroundStyle(.tint)
                        }
                    }
                    .contentShape(Rectangle())
                }
                .buttonStyle(.plain)
            }
        }
        .navigationTitle(Text("负载均衡策略"))
        .navigationBarTitleDisplayMode(.inline)
    }
}
