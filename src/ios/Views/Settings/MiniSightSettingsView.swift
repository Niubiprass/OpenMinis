//
//  MiniSightSettingsView.swift
//  Minis
//
//  [T-minisight-pet] Settings for the MiniSight operation indicator. The pet
//  artwork is user-imported (Photos or Files, Petdex 9-row sheets); nothing is
//  bundled, matching how SwipeDeck / Bottom-x do it. The imported sheet is
//  downscaled to 768 px wide and written to the app's Documents so the
//  SpringBoard tweak can read it without any sandbox escape.
//

import CoreFoundation
import PhotosUI
import SwiftUI
import UniformTypeIdentifiers
import UIKit

private enum MiniSightPetFile {
    static var directory: URL {
        let base = FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first
            ?? FileManager.default.temporaryDirectory
        let dir = base.appendingPathComponent("MiniSight", isDirectory: true)
        try? FileManager.default.createDirectory(at: dir, withIntermediateDirectories: true)
        return dir
    }

    static var url: URL { directory.appendingPathComponent("pet.png") }

    static func load() -> UIImage? {
        guard let data = try? Data(contentsOf: url) else { return nil }
        return UIImage(data: data)
    }

    /// 9-row sheets are 1536 px wide on Petdex; 768 is plenty for a 96 pt pet.
    static func save(_ image: UIImage) -> Bool {
        let maxWidth: CGFloat = 768
        let scale = min(1, maxWidth / max(image.size.width, 1))
        let size = CGSize(width: image.size.width * scale, height: image.size.height * scale)
        let renderer = UIGraphicsImageRenderer(size: size)
        let scaled = renderer.image { _ in
            image.draw(in: CGRect(origin: .zero, size: size))
        }
        guard let data = scaled.pngData() else { return false }
        do {
            try data.write(to: url, options: .atomic)
            return true
        } catch {
            return false
        }
    }

    static func delete() {
        try? FileManager.default.removeItem(at: url)
    }

    static var aiConfigURL: URL { directory.appendingPathComponent("ai.json") }
    static var shownURL: URL { directory.appendingPathComponent("shown") }

    static func loadShown() -> Bool {
        guard let data = try? Data(contentsOf: shownURL) else { return true }
        return String(data: data, encoding: .utf8) != "0"
    }

    static func saveShown(_ on: Bool) {
        try? Data((on ? "1" : "0").utf8).write(to: shownURL, options: .atomic)
    }

    static func loadAI() -> (String, String, String) {
        guard let data = try? Data(contentsOf: aiConfigURL),
              let obj = try? JSONSerialization.jsonObject(with: data) as? [String: String]
        else { return ("", "", "") }
        return (obj["url"] ?? "", obj["key"] ?? "", obj["model"] ?? "")
    }

    static func saveAI(url: String, key: String, model: String) {
        let obj = ["url": url, "key": key, "model": model]
        guard let data = try? JSONSerialization.data(withJSONObject: obj) else { return }
        try? data.write(to: aiConfigURL, options: .atomic)
    }
}

struct MiniSightSettingsView: View {
    /// 0 = capsule, 1 = pet.
    @AppStorage("minisight.style") private var style = 0
    @AppStorage("minisight.record") private var record = false
    @AppStorage("minisight.longPress") private var longPressToRecord = true
    @AppStorage("minisight.mode") private var mode = 0   // 0 = 仅调用时，1 = 常驻
    @State private var shown = true
    @AppStorage("minisight.petSize") private var petSize = 96.0

    @State private var aiURL = ""
    @State private var aiKey = ""
    @State private var aiModel = ""
    @State private var aiStatus: String?
    @State private var petImage: UIImage?
    @State private var showPhotoPicker = false
    @State private var showFilePicker = false
    @State private var importError: String?

    var body: some View {
        List {
            Section {
                Picker("样式", selection: $style) {
                    Text("胶囊").tag(0)
                    Text("桌宠").tag(1)
                }
                .pickerStyle(.segmented)
            } footer: {
                Text("切换后立即生效。桌宠只在导入后可用。")
            }

            Section {
                Toggle("显示桌宠", isOn: $shown)
            } footer: {
                Text("双击桌宠也会关掉它；关掉后 MCP 调用也不再出现，要恢复就在这里打开。")
            }

            Section {
                Picker("显示方式", selection: $mode) {
                    Text("仅调用时").tag(0)
                    Text("常驻").tag(1)
                }
                .pickerStyle(.segmented)
            } header: {
                Text("显示方式")
            } footer: {
                Text("仅调用时：只有 AI 调用越狱 MCP 才出现，结束收起。常驻：一直在桌面，MCP 调用时额外弹说话气泡。")
            }

            Section {
                HStack(spacing: 12) {
                    if let petImage {
                        Image(uiImage: petImage)
                            .resizable()
                            .scaledToFit()
                            .frame(width: 56, height: 60)
                            .background(Color.secondary.opacity(0.12))
                            .clipShape(RoundedRectangle(cornerRadius: 10))
                    } else {
                        RoundedRectangle(cornerRadius: 10)
                            .fill(Color.secondary.opacity(0.12))
                            .frame(width: 56, height: 60)
                            .overlay(Image(systemName: "pawprint").foregroundStyle(.secondary))
                    }
                    VStack(alignment: .leading, spacing: 4) {
                        Text(petImage == nil ? "还没有导入桌宠" : "已导入桌宠")
                        if petImage != nil {
                            Text("9 行 Petdex 精灵图").font(.caption).foregroundStyle(.secondary)
                        }
                    }
                }
                Button { showPhotoPicker = true } label: {
                    Label("从相册导入（768×936 PNG）", systemImage: "photo.on.rectangle")
                }
                Button { showFilePicker = true } label: {
                    Label("从文件导入（Petdex webp）", systemImage: "folder")
                }
                if petImage != nil {
                    Button(role: .destructive) {
                        MiniSightPetFile.delete()
                        petImage = nil
                        style = 0
                    } label: {
                        Label("删除当前桌宠", systemImage: "trash")
                    }
                }
            } header: {
                Text("桌宠")
            } footer: {
                Text("素材从 petdex.dev 下载后导入；图集是 9 行动作（待机/走/跑/跳…），不是单张图。")
            }

            Section {
                HStack(spacing: 12) {
                    Text("大小")
                    Slider(value: $petSize, in: 36...140, step: 2)
                    Text("\(Int(petSize))")
                        .font(.footnote.monospacedDigit())
                        .foregroundStyle(.secondary)
                        .frame(width: 34, alignment: .trailing)
                }
            } header: {
                Text("桌宠大小")
            } footer: {
                Text("36–140，立即生效。")
            }

            Section {
                TextField("接口地址，如 https://api.openai.com/v1", text: $aiURL)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                    .font(.system(.footnote, design: .monospaced))
                SecureField("API Key", text: $aiKey)
                    .font(.system(.footnote, design: .monospaced))
                TextField("模型名", text: $aiModel)
                    .textInputAutocapitalization(.never)
                    .autocorrectionDisabled()
                Button("保存并测试") {
                    MiniSightPetFile.saveAI(url: Self.endpoint(for: aiURL.trimmingCharacters(in: .whitespaces)),
                                            key: aiKey.trimmingCharacters(in: .whitespaces),
                                            model: aiModel.trimmingCharacters(in: .whitespaces))
                    Task { await testAI() }
                }
                if let aiStatus {
                    Text(aiStatus).font(.footnote).foregroundStyle(.secondary)
                }
            } header: {
                Text("桌宠 AI")
            } footer: {
                Text("给桌宠点击说话用，OpenAI 兼容接口。不填或失败就用预置句子。Key 存在 App 容器的文件里，插件才能读到。")
            }

            Section {
                Button("测试显示 3 秒") {
                    post("com.openminis.agent.started")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
                        post("com.openminis.agent.stopped")
                    }
                }
            } footer: {
                Text("用来确认指示器正常，不需要 AI 操作。")
            }

            Section {
                Toggle("操作时录屏", isOn: $record)
                Toggle("长按指示器切换录屏", isOn: $longPressToRecord)
            } header: {
                Text("录屏")
            } footer: {
                Text("录屏默认关闭。开启后，AI 开始操作就录，结束保存；长按可以随时手动开/关。")
            }
        }
        .navigationTitle("操作指示器")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            petImage = MiniSightPetFile.load()
            shown = MiniSightPetFile.loadShown()
            let ai = MiniSightPetFile.loadAI()
            aiURL = ai.0; aiKey = ai.1; aiModel = ai.2
        }
        .onChange(of: style) { _ in flushAndPost("com.openminis.minisight.settings") }
        .onChange(of: mode) { _ in flushAndPost("com.openminis.minisight.settings") }
        .onChange(of: shown) { value in
            MiniSightPetFile.saveShown(value)
            flushAndPost(value ? "com.openminis.minisight.show" : "com.openminis.minisight.settings")
        }
        .onChange(of: petSize) { _ in flushAndPost("com.openminis.minisight.settings") }
        .sheet(isPresented: $showPhotoPicker) {
            MiniSightPhotoPicker { image in importImage(image) }
        }
        .sheet(isPresented: $showFilePicker) {
            MiniSightDocumentPicker { url in importFile(url) }
        }
        .alert("导入失败", isPresented: Binding(
            get: { importError != nil },
            set: { if !$0 { importError = nil } }
        )) {
            Button("好") { importError = nil }
        } message: {
            Text(importError ?? "")
        }
    }

    private func importImage(_ image: UIImage) {
        if MiniSightPetFile.save(image) {
            petImage = MiniSightPetFile.load()
            style = 1
        } else {
            importError = "保存失败，存储空间可能不足。"
        }
    }

    /// 只填域名补 /v1，填到 /v1 补 /chat/completions，已经是完整端点就不动。
    static func endpoint(for base: String) -> String {
        if base.hasSuffix("/chat/completions") { return base }
        let path = URL(string: base)?.path ?? ""
        if path.isEmpty || path == "/" { return base + "/v1/chat/completions" }
        return base + "/chat/completions"
    }

    private func testAI() async {
        let base = aiURL.trimmingCharacters(in: .whitespaces)
        let key = aiKey.trimmingCharacters(in: .whitespaces)
        let model = aiModel.trimmingCharacters(in: .whitespaces)
        guard !base.isEmpty, !key.isEmpty, !model.isEmpty,
              let url = URL(string: Self.endpoint(for: base))
        else { aiStatus = "地址 / Key / 模型不完整"; return }

        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.timeoutInterval = 8
        req.setValue("Bearer \(key)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        let body: [String: Any] = [
            "model": model,
            "max_tokens": 40,
            "messages": [
                ["role": "system", "content": "你是可爱的桌宠，说一句不超过20字的中文撒娇话，不要引号。"],
                ["role": "user", "content": "说一句"],
            ],
        ]
        req.httpBody = try? JSONSerialization.data(withJSONObject: body)
        do {
            let (data, resp) = try await URLSession.shared.data(for: req)
            guard let http = resp as? HTTPURLResponse, http.statusCode == 200 else {
                aiStatus = "失败：HTTP \((resp as? HTTPURLResponse)?.statusCode ?? -1)"; return
            }
            let obj = (try? JSONSerialization.jsonObject(with: data)) as? [String: Any]
            let choices = obj?["choices"] as? [[String: Any]]
            let msg = choices?.first?["message"] as? [String: Any]
            aiStatus = (msg?["content"] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? "返回里没有内容"
        } catch {
            aiStatus = "失败：\(error.localizedDescription)"
        }
    }

    /// AppStorage 写的是内存里的 defaults，异步落盘；插件收到通知会立刻读
    /// plist，没落盘就读到旧值（表现为要拨两次才生效）。先强写盘再发。
    private func flushAndPost(_ name: String) {
        UserDefaults.standard.synchronize()
        post(name)
    }

    private func post(_ name: String) {
        CFNotificationCenterPostNotification(
            CFNotificationCenterGetDarwinNotifyCenter(),
            CFNotificationName(name as CFString), nil, nil, true)
    }

    private func importFile(_ url: URL) {
        let accessing = url.startAccessingSecurityScopedResource()
        defer { if accessing { url.stopAccessingSecurityScopedResource() } }
        guard let data = try? Data(contentsOf: url), let image = UIImage(data: data) else {
            importError = "这个文件不是可识别的图片。"
            return
        }
        importImage(image)
    }
}

// MARK: - Pickers

private struct MiniSightPhotoPicker: UIViewControllerRepresentable {
    let onPick: (UIImage) -> Void

    func makeUIViewController(context: Context) -> PHPickerViewController {
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.filter = .images
        config.selectionLimit = 1
        let picker = PHPickerViewController(configuration: config)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: PHPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    final class Coordinator: NSObject, PHPickerViewControllerDelegate {
        let onPick: (UIImage) -> Void
        init(onPick: @escaping (UIImage) -> Void) { self.onPick = onPick }

        func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
            picker.dismiss(animated: true)
            guard let provider = results.first?.itemProvider,
                  provider.canLoadObject(ofClass: UIImage.self) else { return }
            provider.loadObject(ofClass: UIImage.self) { object, _ in
                guard let image = object as? UIImage else { return }
                DispatchQueue.main.async { self.onPick(image) }
            }
        }
    }
}

private struct MiniSightDocumentPicker: UIViewControllerRepresentable {
    let onPick: (URL) -> Void

    func makeUIViewController(context: Context) -> UIDocumentPickerViewController {
        let picker = UIDocumentPickerViewController(forOpeningContentTypes: [.image], asCopy: true)
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ controller: UIDocumentPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator { Coordinator(onPick: onPick) }

    final class Coordinator: NSObject, UIDocumentPickerDelegate {
        let onPick: (URL) -> Void
        init(onPick: @escaping (URL) -> Void) { self.onPick = onPick }

        func documentPicker(_ controller: UIDocumentPickerViewController, didPickDocumentsAt urls: [URL]) {
            guard let url = urls.first else { return }
            onPick(url)
        }
    }
}
