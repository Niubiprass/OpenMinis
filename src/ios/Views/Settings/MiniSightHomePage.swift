import SwiftUI

/// Settings overview mirroring the reference layout: pet header, identity,
/// AI, palette/costume/download, feel, size. Rhythm + permissions live one
/// level deeper. Every row edits MiniSightConfigStore only.
struct MiniSightHomeView: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    @State private var petImage: UIImage?

    var body: some View {
        List {
            VStack(spacing: 8) {
                if let petImage {
                    Image(uiImage: petImage).resizable().scaledToFit()
                        .frame(height: 140)
                }
                Text(config.nickname.isEmpty ? "我的桌宠" : config.nickname)
                    .font(.title3.weight(.semibold))
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 10)
            .listRowBackground(Color.clear)
            .listRowSeparator(.hidden)

            Section {
                Toggle("启用桌宠", isOn: $config.shown)
                Toggle("允许触摸互动", isOn: $config.interaction)
                Picker("单击手势", selection: $config.singleTap) {
                    ForEach(MiniSightGesture.allCases, id: \.self) { Text($0.title).tag($0) }
                }
                Picker("双击手势", selection: $config.doubleTap) {
                    ForEach(MiniSightGesture.allCases, id: \.self) { Text($0.title).tag($0) }
                }
                Picker("长按手势", selection: $config.longPress) {
                    ForEach(MiniSightGesture.allCases, id: \.self) { Text($0.title).tag($0) }
                }
                Picker("样式", selection: $config.style) {
                    Text("桌宠").tag(1)
                    Text("胶囊").tag(0)
                }
                Picker("显示方式", selection: $config.mode) {
                    Text("仅调用时").tag(0)
                    Text("常驻").tag(1)
                }
                Picker("显示端", selection: $config.renderer) {
                    Text("越狱插件").tag(0)
                    Text("App 内").tag(1)
                }
            } footer: {
                Text("在主屏幕和 App 内显示；锁屏临时暂停，解锁恢复；隐藏时不显示。双击默认语音输入。")
            }

            Section {
                NavigationLink(MiniSightSupplier(rawValue: config.supplier)?.title ?? "选择供应商") {
                    MiniSightSupplierPage()
                }
                NavigationLink("AI 连接") { MiniSightAIPage() }
            } header: { Text("AI") }

            Section {
                NavigationLink(MiniSightPetPalette(rawValue: config.tint)?.title ?? "原图") {
                    MiniSightTintPage()
                }
                NavigationLink(config.costume.isEmpty ? "默认" : config.costume) { MiniSightCostumePage() }
                NavigationLink("下载素材") { MiniSightDownloadPage() }
            } header: { Text("配色与服装") } footer: {
                Text("服装和配色的可用项来自本地已导入素材；没有素材源时不显示虚假下载列表。")
            }

            Section {
                NavigationLink(config.activity.title) {
                    MiniSightActivityPage()
                }
                Toggle("增强拖动响应", isOn: $config.dragResponse)
                Toggle("动作音效", isOn: $config.petSound)
                Toggle("重力感应", isOn: $config.gravity)
                Toggle("摇晃触发失衡", isOn: $config.gravityShake)
                LabeledContent("倾斜强度 \(String(format: "%.1f", config.gravityStrength))") {
                    Slider(value: $config.gravityStrength, in: 0.4...1.6, step: 0.1)
                }
            } header: { Text("动作与手感") } footer: {
                Text("动作音效只在互动和自主活动时响。")
            }

            Section {
                LabeledContent("角色大小 \(Int(config.petSize))") {
                    Slider(value: $config.petSize, in: 36...140, step: 2)
                }
                LabeledContent("底部额外间隙 \(Int(config.bottomGap))") {
                    Slider(value: $config.bottomGap, in: 0...40, step: 2)
                }
                Button("重置到安全位置") {
                    UserDefaults.standard.removeObject(forKey: "minisight.pet.x")
                    UserDefaults.standard.removeObject(forKey: "minisight.pet.y")
                    CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
                        CFNotificationName("com.openminis.minisight.position" as CFString), nil, nil, true)
                }
            } header: { Text("大小与位置") } footer: {
                Text("底部留白参考 10–40；数值越大离 Dock 越远，自动限制在安全区内。")
            }

            Section {
                NavigationLink("聊天、语音与录屏") { MiniSightDialoguePage() }
                Button("清除桌宠聊天记录", role: .destructive) {
                    MiniSightChatPanel.existing()?.clearConversation()
                }
            } header: { Text("聊天与录屏") }

            Section {
                Text(config.saveState).font(.caption).foregroundStyle(.secondary)
                if let error = config.lastError { Text(error).font(.caption).foregroundStyle(.red) }
                Text("PETDFY · 本地素材").font(.caption2).foregroundStyle(.tertiary)
            }
        }
        .navigationTitle("桌宠")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            petImage = MiniSightPetFile.load()
            config.reloadShownFromFile()
        }
        .onDisappear { config.persistAll() }
    }
}

// MARK: - Simple pickers

struct MiniSightSupplierPage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    var body: some View {
        List {
            Section {
                ForEach(MiniSightSupplier.allCases, id: \.self) { item in
                    Button { apply(item) } label: {
                        HStack {
                            Text(item.title)
                            Spacer()
                            if config.supplier == item.rawValue {
                                Image(systemName: "checkmark").foregroundStyle(.tint)
                            }
                        }
                    }
                }
            } footer: {
                Text("只填入默认接口地址，Key 和模型仍要自己填；DeepSeek Harness 需手填地址。")
            }
        }
        .navigationTitle("供应商设置")
        .onDisappear { config.persistAll() }
    }

    private func apply(_ item: MiniSightSupplier) {
        config.supplier = item.rawValue
        guard let endpoint = item.endpoint else { return }
        // Only pre-fill the URL file; never touch an already saved key/model.
        var object = (try? MiniSightAIConfigFile.read(MiniSightPetFile.aiConfigURL)) ?? [:]
        object["url"] = endpoint
        _ = try? MiniSightAIConfigFile.writeAndVerify(object, to: MiniSightPetFile.aiConfigURL)
        MSDiagEvent("settings", "apply", "ok", ["setting": "ai_supplier", "source": "settings"])
    }
}

struct MiniSightTintPage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    var body: some View {
        List {
            ForEach(MiniSightPetPalette.allCases, id: \.self) { item in
                Button { config.tint = item.rawValue } label: {
                    HStack {
                        Circle().fill(item == .natural ? Color.secondary.opacity(0.25) : item.color)
                            .frame(width: 22, height: 22)
                        Text(item.title)
                        Spacer()
                        if config.tint == item.rawValue { Image(systemName: "checkmark").foregroundStyle(.tint) }
                    }
                }
            }
        }
        .navigationTitle("配色")
    }
}

struct MiniSightCostumePage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    @State private var items: [MiniSightAssetCatalog.Item] = []
    var body: some View {
        List {
            Button { config.costume = "" } label: {
                HStack { Text("默认"); Spacer(); if config.costume.isEmpty { Image(systemName: "checkmark") } }
            }
            ForEach(items, id: \.name) { item in
                Button { config.costume = item.name } label: {
                    HStack { Text(item.name); Spacer(); if config.costume == item.name { Image(systemName: "checkmark") } }
                }
            }
            if items.isEmpty {
                Text("还没有导入素材包，可在“下载素材”或相册导入。")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .navigationTitle("服装")
        .onAppear { items = MiniSightAssetCatalog.load() }
    }
}

struct MiniSightActivityPage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    var body: some View {
        List {
            LabeledContent("活动间隔 \(Int(config.activityInterval)) 秒") {
                Slider(value: $config.activityInterval, in: 3...20, step: 1)
            }
            ForEach(MiniSightActivity.allCases, id: \.self) { item in
                Button { config.activity = item } label: {
                    HStack { Text(item.title); Spacer(); if config.activity == item { Image(systemName: "checkmark") } }
                }
            }
        }
        .navigationTitle("自主活动")
    }
}

struct MiniSightDownloadPage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    @State private var address = ""
    @State private var notice = ""
    var body: some View {
        List {
            Section {
                TextField("素材目录地址（可选）", text: $address)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                Button("保存并检查") { check() }
                Text(notice).font(.caption).foregroundStyle(.secondary)
            } footer: {
                Text("没有配置地址时只列出本地已导入素材，不显示假的下载条目。")
            }
            Section {
                let items = MiniSightAssetCatalog.load()
                if items.isEmpty { Text("暂无").font(.caption).foregroundStyle(.secondary) }
                ForEach(items, id: \.name) { item in Text(item.name).font(.caption) }
            } header: { Text("已导入") }
        }
        .navigationTitle("下载素材")
        .onAppear { address = config.downloadSource }
    }

    private func check() {
        guard let url = URL(string: address), url.scheme == "https" || url.scheme == "http" else {
            notice = "地址格式不正确。"; return
        }
        config.downloadSource = address
        notice = "地址已保存；具体素材包仍需放到该目录后由本地导入。"
    }
}
