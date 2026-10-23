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
    @State private var showStrategyPicker = false
    @State private var showAdd = false
    @State private var newKeyText = ""
    @State private var newKeyName = ""
    @State private var editingKey: ProviderAPIKey?
    @State private var deletingKey: ProviderAPIKey?
    @State private var addDuplicate = false

    private var manager: ProviderMultiKeyManager { .shared }

    var body: some View {
        List {
            // [T-multikey-revert-top] 顶部两段恢复原样：用户要改的只有下面
            // KEY 列表的行内布局，概览和策略本来就是分开的两段、各自一张卡，
            // 之前合并/自定义内边距反而让它们比下面的列表窄一截、圆角也显得
            // 更胖。这里原样退回，宽度和内边距与列表完全一致。
            Section {
                HStack(spacing: 7) {
                    Circle()
                        .fill(badCount > 0 ? Color.orange : Color.green)
                        .frame(width: 8, height: 8)
                    Text("\(keys.count) 个 Key")
                    Text("·").foregroundStyle(.tertiary)
                    Text("\(okCount) 正常")
                        .foregroundStyle(okCount > 0 ? Color.green : Color.secondary)
                    if badCount > 0 {
                        Text("·").foregroundStyle(.tertiary)
                        Text("\(badCount) 错误").foregroundStyle(.red)
                    }
                    Spacer()
                }
                .font(.system(size: 14, weight: .medium))
            }

            Section {
                Button {
                    showStrategyPicker = true
                } label: {
                    HStack {
                        Text("负载均衡策略")
                        Spacer()
                        Text(strategy.displayName)
                            .foregroundStyle(.secondary)
                        Image(systemName: "chevron.up.chevron.down")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.tertiary)
                    }
                }
                .buttonStyle(.plain)
            }

            Section {
                if keys.isEmpty {
                    Text("还没有添加 Key")
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(keys) { k in
                        keyRow(k)
                            .listRowInsets(EdgeInsets(top: 7, leading: 16, bottom: 7, trailing: 14))
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
                Text("出错的 Key 不会删除，只是暂时跳过。5 分钟后会自动再试一次，也可以左滑恢复使用；点按 Key 可编辑或删除。")
            }
        }
        .navigationTitle(Text("多 Key 管理"))
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            strategy = manager.strategy(for: instance.id)
            reload()
        }
        .confirmationDialog("负载均衡策略", isPresented: $showStrategyPicker, titleVisibility: .visible) {
            ForEach(MultiKeyStrategy.allCases, id: \.rawValue) { item in
                Button(item == strategy ? "\(item.displayName) ✓" : item.displayName) {
                    strategy = item
                    manager.setStrategy(item, for: instance.id)
                }
            }
            Button("取消", role: .cancel) {}
        } message: {
            Text(strategy.explanation)
        }
        .sheet(isPresented: $showAdd) {
            addSheet
                .alert("这个 Key 已经添加过了", isPresented: $addDuplicate) {
                    Button("知道了", role: .cancel) {}
                } message: {
                    Text("同一把 Key 不需要重复添加。")
                }
        }
        .sheet(item: $editingKey) { key in
            editSheet(for: key)
        }
        .confirmationDialog(
            "删除这个 Key？",
            isPresented: Binding(get: { deletingKey != nil },
                                 set: { if !$0 { deletingKey = nil } }),
            presenting: deletingKey
        ) { key in
            Button("删除", role: .destructive) {
                manager.remove(keyId: key.id, for: instance.id)
                deletingKey = nil
                reload()
            }
            Button("取消", role: .cancel) { deletingKey = nil }
        } message: { key in
            Text("删除后不再使用 \(key.masked)。当前正在进行的回复不会中断。")
        }
    }

    // MARK: - Pieces

    private var okCount: Int {
        keys.filter { $0.isSelectable(recoveryInterval: ProviderMultiKeyManager.recoveryInterval) }.count
    }

    private var badCount: Int { keys.count - okCount }

    @ViewBuilder
    private func keyRow(_ k: ProviderAPIKey) -> some View {
        let selectable = k.isSelectable(recoveryInterval: ProviderMultiKeyManager.recoveryInterval)
        // [T-multikey-inline-status] 徽标原来被 Spacer 推到行的最右边，
        // 一把 Key 名字只有 ~10 个字符，中间就空出一大条。改成紧贴 Key 名字，
        // 中间不再留空；右侧余量是卡片内边距，不是“两块内容之间的空”。
        HStack(alignment: .center, spacing: 12) {
            Circle()
                .fill(selectable ? Color.green : Color.red)
                .frame(width: 8, height: 8)

            // 固定列宽：每行的 Key 名字长度不同，徽标如果紧贴名字就会
            // 一行一个位置。给名字一个固定宽度，徽标就垂直对齐在同一条线上；
            // 名字与徽标之间留 12pt，不再贴在一起。
            Text(k.masked)
                .font(.system(size: 14, design: .monospaced))
                .lineLimit(1)
                .frame(width: 132, alignment: .leading)

            Text(selectable ? "正常" : badgeText(k))
                .font(.system(size: 10.5, weight: .medium))
                .foregroundStyle(selectable ? Color.green : Color.red)
                .lineLimit(1)
                // [T-multikey-chip-no-squeeze] 右侧「成功 N 次」拿了
                // layoutPriority(1)，徽标被压成一列竖着的「正/常」，胶囊跟着
                // 变高变胖。徽标固定按内容宽度排版，谁挤都不许换行。
                .fixedSize(horizontal: true, vertical: false)
                .padding(.horizontal, 7)
                .padding(.vertical, 2)
                .background(
                    (selectable ? Color.green : Color.red).opacity(0.14),
                    in: Capsule()
                )

            Spacer(minLength: 6)

            Text(subtitle(for: k, selectable: selectable))
                .font(.caption2)
                .foregroundStyle(.secondary)
                .lineLimit(1)
                .layoutPriority(1)
                .multilineTextAlignment(.trailing)
        }
        .contentShape(Rectangle())
        .onTapGesture { editingKey = k }
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
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            Button(role: .destructive) {
                deletingKey = k
            } label: {
                Label("删除", systemImage: "trash")
            }
            Button {
                editingKey = k
            } label: {
                Label("编辑", systemImage: "pencil")
            }
            .tint(.blue)
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

    private func editSheet(for key: ProviderAPIKey) -> some View {
        MultiKeyEditSheet(key: key,
                          existingKeys: keys.filter { $0.id != key.id }.map(\.key),
                          onSave: { name, replacement, enabled in
            manager.update(keyId: key.id, for: instance.id) { k in
                k.name = name
                if let replacement, !replacement.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                    k.key = replacement.trimmingCharacters(in: .whitespacesAndNewlines)
                    // A changed credential must not inherit the old key's
                    // cooldown or failure badge.
                    k.status = .active
                    k.consecutiveFailures = 0
                    k.lastError = nil
                    k.unavailableUntil = nil
                }
                k.isEnabled = enabled
                if !enabled {
                    k.status = .disabled
                } else if k.status == .disabled {
                    k.status = .active
                }
            }
            reload()
        })
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
                        if keys.contains(where: { $0.key == trimmed }) {
                            addDuplicate = true
                            return
                        }
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

/// [T-multikey-edit] Edit an existing key without ever showing the full secret.
/// An empty replacement field keeps the stored credential untouched.
struct MultiKeyEditSheet: View {
    let key: ProviderAPIKey
    let existingKeys: [String]
    /// (name, replacement key, enabled)
    let onSave: (String?, String?, Bool) -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var name: String
    @State private var replacement: String = ""
    @State private var enabled: Bool
    @State private var duplicateKey = false

    init(key: ProviderAPIKey,
         existingKeys: [String],
         onSave: @escaping (String?, String?, Bool) -> Void) {
        self.key = key
        self.existingKeys = existingKeys
        self.onSave = onSave
        _name = State(initialValue: key.name ?? "")
        _enabled = State(initialValue: key.isEnabled)
    }

    var body: some View {
        NavigationView {
            Form {
                Section {
                    TextField("给这个 Key 起个名字（可选）", text: $name)
                } header: {
                    Text("备注")
                } footer: {
                    Text("比如「主号」「小号」，只用于区分，不影响请求。")
                }

                Section {
                    SecureField("留空则保持当前 Key", text: $replacement)
                        .textContentType(.password)
                        .autocapitalization(.none)
                        .disableAutocorrection(true)
                        .font(.system(.body, design: .monospaced))
                } header: {
                    Text("API Key")
                } footer: {
                    Text("当前：\(key.masked)\n只有填写新 Key 才会替换；保存后不会显示完整内容。")
                }

                Section {
                    Toggle("启用这个 Key", isOn: $enabled)
                } footer: {
                    Text(enabled
                         ? "关闭后不会再被请求选中，但不会删除。"
                         : "已停用：不会参与轮询，记录仍保留。")
                }

            }
            .navigationTitle(Text("编辑 Key"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        let trimmedName = name.trimmingCharacters(in: .whitespacesAndNewlines)
                        let trimmedKey = replacement.trimmingCharacters(in: .whitespacesAndNewlines)
                        if !trimmedKey.isEmpty, existingKeys.contains(trimmedKey) {
                            duplicateKey = true
                            return
                        }
                        onSave(trimmedName.isEmpty ? nil : trimmedName,
                               trimmedKey.isEmpty ? nil : trimmedKey,
                               enabled)
                        dismiss()
                    }
                }
            }
            .alert("这个 Key 已经添加过了", isPresented: $duplicateKey) {
                Button("知道了", role: .cancel) {}
            } message: {
                Text("请换一把 Key，或保留当前 Key 不改。")
            }
        }
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
