import Foundation
import SwiftUI
import UIKit
import PhotosUI
import UniformTypeIdentifiers

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
                    // Fixed width too: an unconstrained scaledToFit keeps the
                    // 2304pt atlas ideal width and makes List reflow forever.
                    Image(uiImage: petImage).resizable().scaledToFit()
                        .frame(width: 128, height: 139)
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
                Picker("深浅色", selection: $config.darkMode) {
                    Text("跟随系统").tag("system")
                    Text("浅色").tag("light")
                    Text("深色").tag("dark")
                }
            } footer: {
                Text("在主屏幕和 App 内显示；锁屏临时暂停，解锁恢复；隐藏时不显示。双击默认语音输入。")
            }

            Section {
                NavigationLink("AI 连接（服务商 / 自定义链接）") { MiniSightAIPage() }
            } header: { Text("AI") }

            Section {
                NavigationLink("素材与服装") { MiniSightCostumePage() }
            } header: { Text("素材") } footer: {
                Text("素材来自本机导入；8 列 × 9 行的动作图集按行播放动作，其他图片按单张静态角色保留原分辨率。桌宠直接使用素材原色。")
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
                if let error = config.lastError { Text(error).font(.caption).foregroundStyle(.red) }
            }
        }
        .navigationTitle("桌宠")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            refreshPreview()
            config.reloadShownFromFile()
        }
        .onReceive(NotificationCenter.default.publisher(for: MiniSightAssetCatalog.didChange)) { _ in refreshPreview() }
        .onDisappear { config.persistAll() }
    }
    private func refreshPreview() {
        MiniSightAssetCatalog.io.async {
            // Also migrates a sheet that the old PNG-only detector stored as a
            // single image; that path publishes didChange, which re-enters here
            // and lands on a real pack preview.
            _ = try? MiniSightAssetCatalog.snapshot()
            let image = try? MiniSightAssetCatalog.preview(at: MiniSightPetFile.url, variant: MiniSightAssetCatalog.currentVariant)
            DispatchQueue.main.async { petImage = image }
        }
    }
}

// MARK: - Simple pickers

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
    var body: some View { MiniSightDownloadPage() }
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
    @StateObject private var config = MiniSightConfigStore.shared
    @State private var link = ""
    @State private var kind = MiniSightAssetCatalog.ImportKind.auto
    @State private var items: [MiniSightAssetCatalog.Item] = []
    @State private var currentID: String?
    @State private var canRestore = false
    @State private var notice = ""
    @State private var failed = false
    @State private var importing = false
    @State private var showFiles = false
    @State private var showPhotos = false
    @State private var operation: MiniSightAssetOperation?
    @State private var downloader: MiniSightAssetDownload?
    @State private var thumbs: [String: UIImage] = [:]

    var body: some View {
        List {
            Section {
                Picker("素材格式", selection: $kind) {
                    ForEach(MiniSightAssetCatalog.ImportKind.allCases) { Text($0.title).tag($0) }
                }.disabled(importing)
                TextField("图片或 8×9 图集直链", text: $link)
                    .textInputAutocapitalization(.never).autocorrectionDisabled().keyboardType(.URL)
                Button("从链接添加") { importLink() }.disabled(importing || link.isEmpty)
                Button("从相册添加") { showPhotos = true }.disabled(importing)
                Button("从文件添加") { showFiles = true }.disabled(importing)
                if importing {
                    HStack { ProgressView(); Button("取消") { if operation?.cancel() == true { notice = "正在取消…" } } }
                }
                if !notice.isEmpty { Text(notice).font(.caption).foregroundStyle(failed ? Color.red : Color.secondary) }
            } header: { Text("添加素材") } footer: {
                Text("支持图片直链、相册或文件；网页和 ZIP 不直接导入。8 列 × 9 行的动作图集按行播放动作（PNG 或相册转换件都行），其他图片按单张静态角色保留原分辨率。添加不会替你打开桌宠。")
            }
            Section {
                TextField("素材目录地址（可选记录）", text: $config.downloadSource)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                Text("留作参考；单张素材仍用上方链接/相册/文件添加。").font(.caption).foregroundStyle(.secondary)
            } header: { Text("素材来源") }
            Section {
                if items.isEmpty { Text("尚未添加素材").foregroundStyle(.secondary) }
                LazyVGrid(columns: Array(repeating: GridItem(.flexible(), spacing: 10), count: 4), spacing: 12) {
                    ForEach(items) { item in
                        Button { activate(item) } label: {
                            VStack(spacing: 4) {
                                ZStack(alignment: .topTrailing) {
                                    if let image = thumbs[item.id] {
                                        Image(uiImage: image).resizable().scaledToFit()
                                    } else {
                                        Color.secondary.opacity(0.10)
                                    }
                                    if item.id == currentID {
                                        Image(systemName: "checkmark.circle.fill")
                                            .foregroundStyle(.white, Color.accentColor)
                                    }
                                }
                                .frame(height: 72)
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                                .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.25), lineWidth: 0.5))
                                Text(item.title).font(.caption2).lineLimit(1)
                            }
                        }
                        .buttonStyle(.plain)
                        .disabled(importing || item.metadata == nil)
                        .contextMenu {
                            Button(role: .destructive) { remove(item) } label: { Label("删除", systemImage: "trash") }
                        }
                    }
                }
                if canRestore { Button("恢复上一次素材") { restore() }.disabled(importing) }
            } header: { Text("我的宠物 · 点一只直接切换") }
        }
        .navigationTitle("添加素材")
        .onAppear { reload() }
        .onDisappear { _ = operation?.cancel() }
        .sheet(isPresented: $showFiles) { MiniSightFilePicker { file in showFiles = false; importFile(file) } }
        .sheet(isPresented: $showPhotos) {
            MiniSightAssetPhotoPicker { provider in
                showPhotos = false
                guard let provider else { return }
                let op = begin()
                let selectedKind = kind
                let type = provider.registeredTypeIdentifiers.first { UTType($0)?.conforms(to: .image) == true } ?? UTType.image.identifier
                provider.loadFileRepresentation(forTypeIdentifier: type) { url, error in
                    guard let url else { complete(.failure(error ?? MiniSightAssetCatalog.Failure.unreadable)); return }
                    // Provider URLs expire at callback return: stage bytes here,
                    // on its background callback, not a later main-queue job.
                    do {
                        let staged = try MiniSightAssetCatalog.stage(file: url, operation: op)
                        process(staged, kind: selectedKind, operation: op)
                    } catch { complete(.failure(error)) }
                }
            }
        }
    }
    private func begin() -> MiniSightAssetOperation {
        let op = MiniSightAssetOperation()
        operation = op; importing = true; failed = false; notice = "正在读取素材…"
        MSDiagEvent("assets", "request", "pending", ["source": "settings"])
        return op
    }
    private func importFile(_ url: URL) {
        let op = begin(), selectedKind = kind
        MiniSightAssetCatalog.io.async {
            let scoped = url.startAccessingSecurityScopedResource()
            defer { if scoped { url.stopAccessingSecurityScopedResource() } }
            do {
                let staged = try MiniSightAssetCatalog.stage(file: url, operation: op)
                process(staged, kind: selectedKind, operation: op)
            } catch { complete(.failure(error)) }
        }
    }
    private func importLink() {
        do {
            let url = try MiniSightAssetCatalog.inputURL(link)
            let op = begin(), selectedKind = kind
            let download = MiniSightAssetDownload(operation: op, progress: { count, expected in
                DispatchQueue.main.async { notice = expected > 0 ? "下载中 \(count * 100 / max(Int(expected), 1))%" : "下载中 \(count / 1024) KB" }
            }, completion: { result in
                MiniSightAssetCatalog.io.async {
                    do {
                        let item = try MiniSightAssetCatalog.importData(result.get(), kind: selectedKind, title: "链接素材", operation: op)
                        complete(.success(item))
                    } catch { complete(.failure(error)) }
                }
            })
            downloader = download; download.start(url)
        } catch { failed = true; notice = error.localizedDescription }
    }
    private func process(_ staged: URL, kind: MiniSightAssetCatalog.ImportKind, operation: MiniSightAssetOperation) {
        MiniSightAssetCatalog.io.async {
            do { complete(.success(try MiniSightAssetCatalog.importFile(staged, kind: kind, title: "本地素材", operation: operation))) }
            catch { complete(.failure(error)) }
        }
    }
    private func complete(_ result: Result<MiniSightAssetCatalog.Item, Error>) {
        DispatchQueue.main.async {
            importing = false; operation = nil; downloader = nil
            switch result {
            case .success: failed = false; notice = "已添加，点击列表中的素材切换。"; reload()
            case .failure(let error): failed = true; notice = error.localizedDescription
            }
            MSDiagEvent("assets", "finish", failed ? "failed" : "ok", ["source": "settings"])
        }
    }
    private func reload() {
        MiniSightAssetCatalog.io.async {
            do {
                let snapshot = try MiniSightAssetCatalog.snapshot()
                var images: [String: UIImage] = [:]
                for item in snapshot.items {
                    if let image = try? MiniSightAssetCatalog.preview(at: MiniSightAssetCatalog.dir.appendingPathComponent(item.name), variant: item.variant) {
                        images[item.id] = image
                    }
                }
                DispatchQueue.main.async { items = snapshot.items; thumbs = images; currentID = snapshot.currentID; canRestore = snapshot.canRestore }
            } catch { DispatchQueue.main.async { failed = true; notice = error.localizedDescription } }
        }
    }
    private func activate(_ item: MiniSightAssetCatalog.Item) {
        perform { try MiniSightAssetCatalog.activate(item) }
        config.costume = item.title
    }
    private func remove(_ item: MiniSightAssetCatalog.Item) {
        perform { try MiniSightAssetCatalog.delete(item) }
        if item.id == currentID { config.costume = "" }
    }
    private func restore() { perform { try MiniSightAssetCatalog.restorePrevious() }; config.costume = "" }
    private func perform(_ work: @escaping () throws -> Void) {
        importing = true
        MiniSightAssetCatalog.io.async {
            do {
                try work()
                DispatchQueue.main.async {
                    importing = false; failed = false; notice = "素材已更新。"
                    MiniSightAssetCatalog.publishChange(); reload()
                }
            } catch { DispatchQueue.main.async { importing = false; failed = true; notice = error.localizedDescription } }
        }
    }
}

struct MiniSightFilePicker: UIViewControllerRepresentable {
    let onPick: (URL) -> Void
    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.image], asCopy: true)
        picker.delegate = context.coordinator
        return picker
    }
    func updateUIViewController(_ controller: UIDocumentPickerViewController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(onPick) }
    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL) -> Void
        init(_ onPick: @escaping (URL) -> Void) { self.onPick = onPick }
        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) { if let url = urls.first { onPick(url) } }
    }
}
struct MiniSightAssetPhotoPicker: UIViewControllerRepresentable {
    let picked: (NSItemProvider?) -> Void
    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration(photoLibrary: .shared()); config.filter = .images; config.selectionLimit = 1
        let picker = PHPickerViewController(configuration: config); picker.delegate = context.coordinator; return picker
    }
    func updateUIViewController(_ controller: PHPickerViewController, context: Context) {}
    func makeCoordinator() -> Coordinator { Coordinator(picked) }
    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let picked: (NSItemProvider?) -> Void
        init(_ picked: @escaping (NSItemProvider?) -> Void) { self.picked = picked }
        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) { picked(results.first?.itemProvider) }
    }
}
