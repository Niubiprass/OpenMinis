import SwiftUI
import UIKit
import Foundation
import CryptoKit

struct AboutView: View {
    /// [T-inapp-update-beta] Checker lives with the page that uses it: this
    /// file is already in the target, and the update surface is About-only.
    @StateObject private var updater = UpdateChecker()
    @AppStorage("update.autoCheck") private var autoCheckEnabled = true

    /// [T-version-display] Shows ONLY the marketing version ("1.15").
    ///
    /// The build number used to be appended as "1.14 (160651)". The user's
    /// requirement: the app should read as the current release (1.15) and the
    /// internal build stamp must stay invisible — it is only needed to tell
    /// builds apart during debugging, and `buildDate` below already answers
    /// "which build is actually running?" on the device.
    private let appVersion: String = {
        Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
    }()

    /// When this binary was built, from the executable's modification date.
    ///
    /// Exists because the version string alone cannot answer "is the fix I
    /// just shipped actually running on that device?" — CFBundleVersion is
    /// static across rebuilds, so an OTA install that silently didn't replace
    /// the app looks identical to one that did. That ambiguity has cost real
    /// debugging time on the test devices. Same source as the debug server's
    /// `buildDate`, but visible in Release too, where no debug server exists.
    /// [T-env-diagnostic-line] One line naming the RUNTIME environment, for
    /// bug reports.
    ///
    /// A macOS 27 rendering report cost a full round trip because nothing in
    /// the app said which environment it was: "Designed for iPad" (an
    /// unmodified iOS binary on Apple Silicon) and Mac Catalyst (UIKit bridged
    /// onto AppKit) look identical in a screenshot but share almost no
    /// rendering path, and the SDK release notes that explain a symptom apply
    /// to one and not the other. Guessing wrong sends the whole diagnosis down
    /// the wrong track.
    ///
    /// `isiOSAppOnMac` is the authoritative discriminator and is what
    /// distinguishes the two; `targetEnvironment(macCatalyst)` is resolved at
    /// COMPILE time, so it reports how this binary was built rather than where
    /// it is running — both are printed because the pair is what identifies
    /// the mode unambiguously.
    private let environmentLine: String = {
        let osv = ProcessInfo.processInfo.operatingSystemVersion
        let os = "\(osv.majorVersion).\(osv.minorVersion).\(osv.patchVersion)"
        let idiom: String = switch UIDevice.current.userInterfaceIdiom {
        case .phone: "phone"
        case .pad: "pad"
        case .mac: "mac"
        case .tv: "tv"
        case .carPlay: "carPlay"
        case .vision: "vision"
        default: "unspecified"
        }
        #if targetEnvironment(macCatalyst)
        let built = "catalyst"
        #else
        let built = "ios"
        #endif
        let onMac = ProcessInfo.processInfo.isiOSAppOnMac
        // "iOSAppOnMac" is Designed for iPad; "catalyst" built + not
        // isiOSAppOnMac is a true Catalyst run; otherwise a real device.
        let mode = onMac ? "iOSAppOnMac" : (built == "catalyst" ? "catalyst" : "device")
        return "\(mode) · \(idiom) · OS \(os) · built:\(built)"
    }()

    private let buildDate: String = {
        guard let url = Bundle.main.executableURL,
              let attrs = try? FileManager.default.attributesOfItem(atPath: url.path),
              let mod = attrs[.modificationDate] as? Date
        else { return "unknown" }
        let fmt = DateFormatter()
        // Local time, seconds included: this gets compared by eye against the
        // timestamp of a build that just finished.
        fmt.dateFormat = "yyyy-MM-dd HH:mm:ss"
        return fmt.string(from: mod)
    }()

    var body: some View {
        List {
            // MARK: - Project Info
            Section {
                VStack(spacing: 8) {
                    if let icon = UIImage(named: "AppIcon60x60") ?? UIImage(named: "AppIcon") {
                        Image(uiImage: icon)
                            .resizable()
                            .frame(width: 80, height: 80)
                            .clipShape(RoundedRectangle(cornerRadius: 18))
                            .overlay(
                                RoundedRectangle(cornerRadius: 18)
                                    .stroke(Color(UIColor.separator), lineWidth: 0.5)
                            )
                    }
                    Text("Minis")
                        .font(.title2.bold())
                    Text("Version \(appVersion)")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    Text("Built \(buildDate)")
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        // Selectable so it can be copied into a bug report.
                        .textSelection(.enabled)
                    // [T-env-diagnostic-line] Sits with the build date because
                    // it answers the same question — "what exactly is running?"
                    // — and gets copied into the same bug reports.
                    Text(environmentLine)
                        .font(.caption)
                        .foregroundStyle(.tertiary)
                        .textSelection(.enabled)
                    Text("Minis is Your Fully Local, Fully Private On-Device Agent.")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .listRowBackground(Color.clear)
            }

            // MARK: - Links
            Section("Links") {
                Link(destination: URL(string: "https://github.com/OpenMinis")!) {
                    Label {
                        HStack {
                            Text("GitHub Repository")
                                .foregroundStyle(Color(UIColor.label))
                            Spacer()
                            Image(systemName: "arrow.up.right.square")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    } icon: {
                        Image(systemName: "link.circle.fill")
                    }
                }
                Link(destination: URL(string: "https://github.com/OpenMinis/OpenMinis/issues")!) {
                    Label {
                        HStack {
                            Text("Report an Issue")
                                .foregroundStyle(Color(UIColor.label))
                            Spacer()
                            Image(systemName: "arrow.up.right.square")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    } icon: {
                        Image(systemName: "exclamationmark.circle.fill")
                    }
                }
            }

            // MARK: - Updates
            // [T-inapp-update-beta] One state block at a time — never a stack of
            // them. The channel row and the auto-check switch stay put so the
            // block swapping between "available" and "downloading" does not move
            // anything under the user's finger.
            Section {
                updateStateRow
                HStack {
                    Label {
                        Text("更新渠道")
                    } icon: {
                        Image(systemName: "arrow.triangle.branch")
                            .foregroundStyle(.orange)
                    }
                    Spacer()
                    Text("测试版")
                        .foregroundStyle(.secondary)
                }
                Toggle(isOn: $autoCheckEnabled) {
                    Label {
                        Text("自动检查更新")
                    } icon: {
                        Image(systemName: "arrow.clockwise")
                            .foregroundStyle(.green)
                    }
                }
            } header: {
                HStack(spacing: 6) {
                    Text("应用更新")
                    if updater.hasUpdate {
                        Circle().fill(Color.red).frame(width: 7, height: 7)
                    }
                }
            } footer: {
                VStack(alignment: .leading, spacing: 6) {
                    Text("需要 TrollStore 已启用 URL Scheme。覆盖安装，数据保留。")
                    Text("当前版本 \(appVersion) (build \(currentBuild))")
                        .foregroundStyle(.tertiary)
                }
            }
        }
        .navigationTitle("About")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            updater.autoCheckIfDue(enabled: autoCheckEnabled)
        }
    }

    /// Build stamp injected by CI; 0 when an older/local build lacks it.
    private var currentBuild: Int {
        (Bundle.main.infoDictionary?["MinisBuildNumber"] as? String).flatMap(Int.init) ?? 0
    }

    /// One row that changes with the checker's phase.
    @ViewBuilder
    private var updateStateRow: some View {
        switch updater.phase {
        case .idle:
            HStack(spacing: 11) {
                Image(systemName: "arrow.down.circle")
                    .foregroundStyle(.secondary)
                Text("尚未检查")
                Spacer()
                Button("检查更新") { updater.check(manual: true) }
                    .buttonStyle(.borderless)
            }
        case .checking:
            HStack(spacing: 11) {
                ProgressView()
                Text("正在检查…")
            }
        case .latest:
            HStack(spacing: 11) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.blue)
                VStack(alignment: .leading, spacing: 2) {
                    Text("已是最新")
                    Text("版本 \(appVersion) (build \(currentBuild))")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("再次检查") { updater.check(manual: true) }
                    .buttonStyle(.borderless)
            }
        case let .available(build, version, size, notes):
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 11) {
                    Image(systemName: "arrow.down.circle.fill")
                        .foregroundStyle(.green)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("有可用更新")
                        Text("版本 \(version) (build \(build)) · \(ByteCountFormatter.string(fromByteCount: size, countStyle: .file))")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                if !notes.isEmpty {
                    Text(notes)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                HStack {
                    Spacer()
                    Button("立即更新") { updater.downloadAndInstall() }
                        .buttonStyle(.borderless)
                        .font(.body.weight(.medium))
                    Spacer()
                }
            }
        case let .downloading(fraction):
            VStack(alignment: .leading, spacing: 6) {
                HStack(spacing: 11) {
                    Image(systemName: "arrow.down.circle.fill")
                        .foregroundStyle(.green)
                    Text("正在下载… \(Int(fraction * 100))%")
                    Spacer()
                    Button("取消") { updater.cancel() }
                        .buttonStyle(.borderless)
                }
                ProgressView(value: fraction)
            }
        case .installing:
            HStack(spacing: 11) {
                Image(systemName: "shippingbox.fill")
                    .foregroundStyle(.green)
                VStack(alignment: .leading, spacing: 2) {
                    Text("已交给 TrollStore")
                    Text("安装完成后重新打开 Minis 生效")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        case let .schemeMissing(version):
            VStack(alignment: .leading, spacing: 8) {
                HStack(alignment: .top, spacing: 11) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text("TrollStore 的 URL Scheme 没开")
                        Text("版本 \(version) 已可更新；先到 TrollStore 设置里启用 URL Scheme。")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                }
                HStack {
                    Spacer()
                    Button("去 TrollStore") { updater.openTrollStore() }
                        .buttonStyle(.borderless)
                }
            }
        case let .failed(message):
            HStack(spacing: 11) {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.orange)
                VStack(alignment: .leading, spacing: 2) {
                    Text("检查失败")
                    Text(message)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("重试") { updater.check(manual: true) }
                    .buttonStyle(.borderless)
            }
        }
    }
}

// MARK: - Update checker
// [T-inapp-update-beta] One channel only (beta), fed by a GitHub Release that
// CI rewrites on every successful build under a fixed tag. The release carries
// `latest.json` (build/version/size/sha256/notes) plus the IPA itself; this
// checker reads the manifest, compares build numbers, downloads and hands the
// verified file to TrollStore through its URL scheme.
//
// Deliberately no auth: the repository is public, so a read-only anonymous GET
// is enough (60 requests/hour, and the automatic check is capped at one a day).
// No token is shipped in the binary.

struct UpdateManifest: Decodable, Equatable {
    let build: Int
    let version: String
    let notes: String
    let ipa: String
    let sha256: String
    let size: Int64
}

@MainActor
final class UpdateChecker: ObservableObject {
    enum Phase: Equatable {
        case idle
        case checking
        case latest
        case available(build: Int, version: String, size: Int64, notes: String)
        case downloading(Double)
        case installing
        case schemeMissing(String)
        case failed(String)
    }

    static let repository = "Niubiprass/OpenMinis"
    static let channelTag = "beta-latest"
    static let trollStoreScheme = "apple-magnifier://install?url="
    private static let lastCheckKey = "update.lastCheck"
    private static let pendingBuildKey = "update.pendingBuild"

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var hasUpdate = false

    private var manifest: UpdateManifest?
    private var ipaURL: URL?
    private var task: Task<Void, Never>?
    private let build: Int

    init() {
        build = (Bundle.main.infoDictionary?["MinisBuildNumber"] as? String).flatMap(Int.init) ?? 0
        if let pending = UserDefaults.standard.object(forKey: Self.pendingBuildKey) as? Int,
           pending > 0, build >= pending {
            UserDefaults.standard.removeObject(forKey: Self.pendingBuildKey)
            phase = .latest
        }
    }

    /// Automatic check: at most once every 24h, and only if the switch is on.
    func autoCheckIfDue(enabled: Bool) {
        guard enabled else { return }
        if let last = UserDefaults.standard.object(forKey: Self.lastCheckKey) as? Date,
           Date().timeIntervalSince(last) < 24 * 3600 { return }
        check(manual: false)
    }

    func check(manual: Bool) {
        _ = manual
        guard task == nil else { return }
        phase = .checking
        hasUpdate = false
        task = Task { [weak self] in
            guard let self else { return }
            defer { self.task = nil }
            do {
                let (manifest, ipa) = try await self.fetchManifest()
                UserDefaults.standard.set(Date(), forKey: Self.lastCheckKey)
                self.manifest = manifest
                self.ipaURL = ipa
                if manifest.build > self.build {
                    self.hasUpdate = true
                    self.phase = .available(build: manifest.build, version: manifest.version,
                                            size: manifest.size, notes: manifest.notes)
                } else {
                    self.phase = .latest
                }
            } catch {
                if Task.isCancelled { return }
                self.phase = .failed((error as? UpdateError)?.text ?? "网络或仓库暂时不可用")
            }
        }
    }

    func downloadAndInstall() {
        guard phase.isAvailable, let manifest = manifest, let ipaURL = ipaURL, task == nil else { return }
        guard let schemeProbe = URL(string: "apple-magnifier://") , UIApplication.shared.canOpenURL(schemeProbe) else {
            phase = .schemeMissing(manifest.version)
            return
        }
        phase = .downloading(0)
        task = Task { [weak self] in
            guard let self else { return }
            defer { self.task = nil }
            do {
                let file = try await self.download(manifest: manifest, from: ipaURL)
                self.phase = .installing
                self.hasUpdate = false
                UserDefaults.standard.set(manifest.build, forKey: Self.pendingBuildKey)
                self.handToTrollStore(file: file)
            } catch {
                if Task.isCancelled { return }
                self.phase = .failed((error as? UpdateError)?.text ?? "下载失败")
            }
        }
    }

    func cancel() {
        task?.cancel()
        task = nil
        phase = manifest.map { Phase.available(build: $0.build, version: $0.version, size: $0.size, notes: $0.notes) } ?? .idle
    }

    func openTrollStore() {
        if let url = URL(string: "apple-magnifier://") {
            _ = UIApplication.shared.open(url)
        }
    }

    // MARK: - Networking

    private struct ReleaseResponse: Decodable {
        struct Asset: Decodable {
            let name: String
            let browser_download_url: URL
        }
        let body: String?
        let assets: [Asset]
    }

    private func fetchManifest() async throws -> (UpdateManifest, URL) {
        guard let releaseURL = URL(string: "https://api.github.com/repos/\(Self.repository)/releases/tags/\(Self.channelTag)") else {
            throw UpdateError("地址不合法")
        }
        var request = URLRequest(url: releaseURL)
        request.setValue("application/vnd.github+json", forHTTPHeaderField: "Accept")
        request.timeoutInterval = 20
        let (data, response) = try await URLSession.shared.data(for: request)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw UpdateError("仓库里还没有发布的测试版")
        }
        let release = try JSONDecoder().decode(ReleaseResponse.self, from: data)
        guard let manifestAsset = release.assets.first(where: { $0.name == "latest.json" }) else {
            throw UpdateError("这个发布缺少版本清单")
        }
        let (mData, _) = try await URLSession.shared.data(from: manifestAsset.browser_download_url)
        var manifest = try JSONDecoder().decode(UpdateManifest.self, from: mData)
        if manifest.notes.isEmpty { manifest = UpdateManifest(build: manifest.build, version: manifest.version,
                                                              notes: release.body ?? "", ipa: manifest.ipa,
                                                              sha256: manifest.sha256, size: manifest.size) }
        guard let ipa = release.assets.first(where: { $0.name == manifest.ipa }) else {
            throw UpdateError("这个发布缺少安装包")
        }
        return (manifest, ipa.browser_download_url)
    }

    /// Streams to disk in 1 MB chunks, hashing as it goes, so a 76 MB IPA never
    /// sits in memory twice.
    private func download(manifest: UpdateManifest, from url: URL) async throws -> URL {
        let directory = FileManager.default.temporaryDirectory.appendingPathComponent("updates", isDirectory: true)
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        let destination = directory.appendingPathComponent(manifest.ipa)
        try? FileManager.default.removeItem(at: destination)
        guard FileManager.default.createFile(atPath: destination.path, contents: nil),
              let handle = try? FileHandle(forWritingTo: destination) else {
            throw UpdateError("无法写入临时文件")
        }
        defer { try? handle.close() }

        let (bytes, response) = try await URLSession.shared.bytes(from: url)
        guard (response as? HTTPURLResponse)?.statusCode == 200 else {
            throw UpdateError("下载地址返回错误")
        }
        var hasher = SHA256()
        var chunk = [UInt8]()
        chunk.reserveCapacity(1 << 20)
        var written = 0
        let expected = max(manifest.size, 1)
        var lastTick = Date.distantPast
        for try await byte in bytes {
            if Task.isCancelled { throw UpdateError("已取消") }
            chunk.append(byte)
            if chunk.count >= (1 << 20) {
                let data = Data(chunk)
                hasher.update(data: data)
                try handle.write(contentsOf: data)
                written += data.count
                chunk.removeAll(keepingCapacity: true)
                if Date().timeIntervalSince(lastTick) > 0.2 {
                    lastTick = Date()
                    phase = .downloading(min(Double(written) / Double(expected), 0.99))
                }
            }
        }
        if !chunk.isEmpty {
            let data = Data(chunk)
            hasher.update(data: data)
            try handle.write(contentsOf: data)
            written += data.count
        }
        let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard written == manifest.size else {
            throw UpdateError("包大小不符（\(written) / \(manifest.size)）")
        }
        guard digest.caseInsensitiveCompare(manifest.sha256) == .orderedSame else {
            throw UpdateError("校验失败，安装包不完整")
        }
        return destination
    }

    private func handToTrollStore(file: URL) {
        guard let url = URL(string: Self.trollStoreScheme + (file.absoluteString.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? file.absoluteString)) else {
            phase = .failed("无法生成安装链接")
            return
        }
        _ = UIApplication.shared.open(url)
    }
}

struct UpdateError: Error {
    let text: String
    init(_ text: String) { self.text = text }
}

private extension UpdateChecker.Phase {
    var isAvailable: Bool {
        if case .available = self { return true }
        return false
    }
}
