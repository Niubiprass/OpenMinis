import PhotosUI
import SwiftUI
import UIKit
import UniformTypeIdentifiers

enum MiniSightPetPalette: String, CaseIterable {
    case natural, warm, cool, mint, rose
    var title: String {
        switch self {
        case .natural: return "原图"
        case .warm: return "暖橙"
        case .cool: return "冷蓝"
        case .mint: return "薄荷"
        case .rose: return "玫瑰"
        }
    }
    var color: Color {
        switch self {
        case .natural: return .clear
        case .warm: return Color(red: 0.96, green: 0.55, blue: 0.32)
        case .cool: return Color(red: 0.38, green: 0.58, blue: 0.98)
        case .mint: return Color(red: 0.35, green: 0.80, blue: 0.61)
        case .rose: return Color(red: 0.92, green: 0.45, blue: 0.63)
        }
    }
}

struct MiniSightAppearancePage: View {
    // [T-minisight-page-no-envobject] Read the shared store directly: the pages
    // are pushed from several hosts and an un-injected EnvironmentObject traps
    // at body evaluation (SIGTRAP in MiniSightPermissionsPage.body, 2026-11-06).
    @StateObject private var config = MiniSightConfigStore.shared
    @State private var petImage: UIImage?
    @State private var photoPicker = false
    @State private var filePicker = false
    @State private var error: String?
    @State private var assetSource = ""
    @State private var downloadAddress = UserDefaults.standard.string(forKey: "minisight.asset.source") ?? ""
    @State private var costumes = MiniSightAssetCatalog.load()

    var body: some View {
        List {
            Section {
                HStack(spacing: 14) {
                    if let petImage {
                        Image(uiImage: petImage).resizable().scaledToFit()
                            .frame(width: 64, height: 72).clipShape(RoundedRectangle(cornerRadius: 10))
                    } else {
                        RoundedRectangle(cornerRadius: 10).fill(Color.secondary.opacity(0.12))
                            .frame(width: 64, height: 72)
                            .overlay(Image(systemName: "pawprint").foregroundStyle(.secondary))
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text(petImage == nil ? "还没有导入桌宠" : "当前精灵图")
                        Text("9 行动作图集，静止图也可用").font(.caption).foregroundStyle(.secondary)
                    }
                }
                Button { photoPicker = true } label: { Label("从相册导入", systemImage: "photo.on.rectangle") }
                Button { filePicker = true } label: { Label("从文件导入图集", systemImage: "folder") }
                if petImage != nil {
                    Button(role: .destructive) { removePet() } label: { Label("删除当前桌宠", systemImage: "trash") }
                }
            } header: { Text("素材") }

            Section {
                Picker("配色", selection: $config.tint) {
                    ForEach(MiniSightPetPalette.allCases, id: \.self) { Text($0.title).tag($0.rawValue) }
                }
            } header: { Text("角色配色") }
            Section {
                if costumes.isEmpty {
                    Text("还没有可选择的素材包。导入的图集会记录在本地素材列表，不做虚假下载。")
                        .font(.caption).foregroundStyle(.secondary)
                } else {
                    Picker("服装 / 素材包", selection: $config.costume) {
                        Text("使用当前素材").tag("")
                        ForEach(costumes, id: \.name) { Text($0.name).tag($0.name) }
                    }
                }
                ForEach(costumes, id: \.name) { item in
                    HStack {
                        Text(item.name).font(.footnote)
                        Spacer()
                        Text("\(item.bytes / 1024) KB").font(.caption2).foregroundStyle(.secondary)
                    }
                }
            } header: { Text("已导入素材包") } footer: {
                Text("选择素材包会应用对应的本地文件；没有下载源时不会显示可下载列表。")
            }

            Section {
                TextField("素材目录地址（可选）", text: $downloadAddress)
                    .textInputAutocapitalization(.never).autocorrectionDisabled()
                    .onSubmit { UserDefaults.standard.set(downloadAddress, forKey: "minisight.asset.source") }
                if !downloadAddress.isEmpty {
                    Button("检查素材地址") { checkSource() }
                }
                Text(assetSource).font(.caption).foregroundStyle(.secondary)
            } header: { Text("素材来源") } footer: {
                Text("本地导入不依赖网络。素材来源和许可由素材包提供，导入前请在来源页确认。")
            }

            Section {
                Picker("外观", selection: $config.darkMode) {
                    Text("跟随系统").tag("system")
                    Text("浅色").tag("light")
                    Text("深色").tag("dark")
                }
                .pickerStyle(.segmented)
            } header: { Text("深浅色") }
        }
        .navigationTitle("配色与服装")
        .onAppear { petImage = MiniSightPetFile.load() }
        .onDisappear { config.persistAll() }
        .sheet(isPresented: $photoPicker) {
            MiniSightPhotoPicker(onPick: { importPet($0, source: "photos") }, onFailure: { error = "照片读取失败" })
        }
        .sheet(isPresented: $filePicker) { MiniSightDocumentPicker { importPet($0) } }
        .alert("导入失败", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
            Button("好") { error = nil }
        } message: { Text(error ?? "") }
    }

    private func importPet(_ image: UIImage, source: String = "files") {
        do {
            try MiniSightPetFile.save(image) { }
            petImage = MiniSightPetFile.load()
            guard petImage != nil else { throw MiniSightAIConfigFile.Failure.verificationFailed }
            MiniSightAssetCatalog.add(image, source: source)
            costumes = MiniSightAssetCatalog.load()
            config.style = 1
            MSDiagEvent("assets", "apply", "ok", ["setting": "pet", "source": source, "readback": true])
        } catch {
            MSDiagEvent("assets", "readback", "failed", ["setting": "pet", "source": source, "code": (error as NSError).code])
            self.error = "图集没有保存成功或回读失败。"
        }
    }

    private func importPet(_ url: URL) {
        let access = url.startAccessingSecurityScopedResource()
        defer { if access { url.stopAccessingSecurityScopedResource() } }
        do {
            let data = try Data(contentsOf: url)
            guard let image = UIImage(data: data) else { throw MiniSightAIConfigFile.Failure.invalidFile }
            importPet(image)
        } catch { self.error = "文件无法读取或不是图片。" }
    }

    private func removePet() {
        do {
            try MiniSightPetFile.delete()
            petImage = nil
            config.style = 0
        } catch { self.error = "删除或删除后核对失败。" }
    }

    private func checkSource() {
        guard let url = URL(string: downloadAddress) else { assetSource = "地址格式不正确。"; return }
        assetSource = "地址已保存；素材下载需要具体文件或清单。"
        UserDefaults.standard.set(downloadAddress, forKey: "minisight.asset.source")
        _ = url
    }
}

/// Local imported atlases. Only real files are listed; there is no baked
/// download catalog while no source is configured.
enum MiniSightAssetCatalog {
    struct Item { let name: String; let bytes: Int }
    static var dir: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            .appendingPathComponent("MiniSight/costumes", isDirectory: true)
    }
    static func load() -> [Item] {
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return ((try? FileManager.default.contentsOfDirectory(at: dir, includingPropertiesForKeys: [.fileSizeKey])) ?? [])
            .filter { ["png", "webp", "jpg"].contains($0.pathExtension.lowercased()) }
            .compactMap { url in
                let values = try? url.resourceValues(forKeys: [.fileSizeKey])
                return Item(name: url.lastPathComponent, bytes: values?.fileSize ?? 0)
            }.sorted { $0.name < $1.name }
    }
    static func add(_ image: UIImage, source: String) {
        guard source == "files", let data = image.pngData() else { return }
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        try? data.write(to: dir.appendingPathComponent("local-\(Int(Date().timeIntervalSince1970)).png"))
    }
}
