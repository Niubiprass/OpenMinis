import SwiftUI

extension MiniSightQuickAction: Identifiable { var id: String { rawValue } }

struct MiniSightShortcutsPage: View {
    @EnvironmentObject private var config: MiniSightConfigStore
    @State private var editing: MiniSightQuickAction?
    @State private var showReset = false

    var body: some View {
        List {
            Section {
                Toggle("显示快捷按钮", isOn: $config.quickButtons)
                Picker("按钮位置", selection: $config.quickPosition) {
                    Text("气泡上方").tag("above")
                    Text("输入条下方").tag("below")
                }
                .pickerStyle(.segmented)
            } footer: {
                Text("快捷按钮只执行本地动作和短句，不会自动联网；带“对话”的按钮才发 AI 请求。")
            }

            Section {
                ForEach(config.quickOrder, id: \.self) { action in
                    Button {
                        editing = action
                    } label: {
                        HStack {
                            Text(action.title)
                            Spacer()
                            Text(config.quickLines[action.rawValue] ?? MiniSightConfig.quickLine(action))
                                .font(.caption).foregroundStyle(.secondary).lineLimit(1)
                            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
                        }
                    }
                }
                .onMove { from, to in
                    guard let source = from.first else { return }
                    config.moveQuick(from: source, to: to > source ? to - 1 : to)
                }
            } header: {
                HStack { Text("动作与短句"); Spacer(); EditButton().font(.caption) }
            } footer: {
                Text("拖动右侧把手排序；关闭自定义短句后恢复默认句。")
            }

            Section {
                Button("恢复默认按钮与短句", role: .destructive) { showReset = true }
            }
        }
        .navigationTitle("快捷按钮与短句")
        .onDisappear { config.persistAll() }
        .sheet(item: $editing) { action in
            MiniSightShortcutEditor(action: action)
                .environmentObject(config)
        }
        .alert("恢复默认？", isPresented: $showReset) {
            Button("恢复", role: .destructive) {
                config.quickOrder = MiniSightQuickAction.allCases
                for action in MiniSightQuickAction.allCases { config.setQuickLine("", for: action) }
                config.quickButtons = true
                config.quickPosition = "above"
            }
            Button("取消", role: .cancel) {}
        }
    }
}

private struct MiniSightShortcutEditor: View {
    @EnvironmentObject private var config: MiniSightConfigStore
    @Environment(\.dismiss) private var dismiss
    let action: MiniSightQuickAction
    @State private var text = ""

    var body: some View {
        NavigationView {
            List {
                Section {
                    TextField(action.defaultLine, text: $text)
                        .onChange(of: text) { config.setQuickLine($0, for: action) }
                } footer: {
                    Text("最多 120 字；清空使用默认句。输入只存本地，不当作命令执行。")
                }
                Section {
                    Button("使用默认句") { text = action.defaultLine; config.setQuickLine("", for: action) }
                        .disabled(text == action.defaultLine)
                }
            }
            .navigationTitle(action.title)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .topBarTrailing) { Button("完成") { dismiss() } } }
        }
        .navigationViewStyle(.stack)
        .onAppear {
            let saved = (UserDefaults.standard.dictionary(forKey: MiniSightSettingKey.quickLines)?[action.rawValue] as? String) ?? ""
            text = saved.isEmpty ? action.defaultLine : saved
        }
        .onDisappear { config.persistAll() }
    }
}
