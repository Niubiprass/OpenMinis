import SwiftUI
import UIKit
import Foundation
import CryptoKit
import Combine

struct AboutView: View {
    /// App-wide state survives leaving About and also drives the Settings badge.
    @ObservedObject private var updater = UpdateChecker.shared
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
        .onChange(of: autoCheckEnabled) { enabled in
            if enabled { updater.check(manual: true) }
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
        case .restoring:
            HStack(spacing: 11) {
                ProgressView()
                Text("正在恢复后台下载…")
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
        case let .downloadReady(version):
            HStack(spacing: 11) {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(.green)
                VStack(alignment: .leading, spacing: 2) {
                    Text("下载完成")
                    Text("版本 \(version) 已准备好安装")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                Button("安装更新") { updater.installDownloaded() }
                    .buttonStyle(.borderless)
            }
        case .verifying:
            HStack(spacing: 11) {
                ProgressView()
                Text("正在校验安装包…")
            }
        case .openingInstaller:
            HStack(spacing: 11) {
                ProgressView()
                Text("正在打开安装器…")
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
        case let .failed(title, message):
            VStack(alignment: .leading, spacing: 8) {
                HStack(spacing: 11) {
                    Image(systemName: "exclamationmark.triangle.fill")
                        .foregroundStyle(.orange)
                    VStack(alignment: .leading, spacing: 2) {
                        Text(title)
                        Text(message)
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    Spacer()
                    Button("重试") { updater.retry() }
                        .buttonStyle(.borderless)
                }
                if updater.hasUpdate {
                    Text("仍有可用更新，更新提示会保留。")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
    }
}

// This small row accessory observes the updater; progress must not invalidate
// the entire SettingsSheet (which contains unrelated providers and permissions).
struct AboutUpdateBadge: View {
    @ObservedObject private var updater = UpdateChecker.shared

    var body: some View {
        HStack(spacing: 6) {
            if updater.hasUpdate {
                Circle().fill(Color.red).frame(width: 7, height: 7)
                    .accessibilityHidden(true)
                Text("有更新")
                    .font(.caption.weight(.medium))
                    .foregroundStyle(.red)
            } else if updater.isLatest {
                Text("已是最新")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .fixedSize(horizontal: true, vertical: false)
        .accessibilityElement(children: .combine)
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

struct UpdateManifest: Codable, Equatable {
    let build: Int
    let version: String
    let notes: String
    let ipa: String
    let sha256: String
    let size: Int64

    var isValid: Bool {
        build > 0 && !version.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && size > 0 && !ipa.isEmpty && ipa == (ipa as NSString).lastPathComponent
            && !ipa.contains("\\") && ipa.lowercased().hasSuffix(".ipa")
            && !ipa.unicodeScalars.contains(where: { CharacterSet.controlCharacters.contains($0) })
            && sha256.utf8.count == 64
            && sha256.utf8.allSatisfy { (48...57).contains($0) || (65...70).contains($0) || (97...102).contains($0) }
    }
}

@MainActor
final class UpdateChecker: ObservableObject {
    enum Phase: Equatable {
        case idle
        case checking
        case latest
        case available(build: Int, version: String, size: Int64, notes: String)
        case restoring
        case downloading(Double)
        case downloadReady(String)
        case verifying
        case openingInstaller
        case installing
        case schemeMissing(String)
        case failed(title: String, message: String)
    }

    static let shared = UpdateChecker()
    static let repository = "Niubiprass/OpenMinis"
    static let channelTag = "beta-latest"
    static let trollStoreScheme = "apple-magnifier://install?url="
    private static let lastCheckKey = "update.lastCheck"
    private static let pendingBuildKey = "update.pendingBuild"
    private static let cachedManifestKey = "update.cachedManifest"
    private static let cachedIPAURLKey = "update.cachedIPAURL"

    @Published private(set) var phase: Phase = .idle
    @Published private(set) var hasUpdate = false
    @Published private(set) var isLatest = false

    private var manifest: UpdateManifest?
    private var ipaURL: URL?
    private var task: Task<Void, Never>?
    private var verificationTask: Task<Void, Never>?
    private var downloadObservation: AnyCancellable?
    private var lastAttempt: Date?
    private var checkID = UUID()
    private var installID = UUID()
    private var retryAction: RetryAction = .check
    private let build: Int
    private enum RetryAction { case check, download, install }
    private static let checkedBuildKey = "update.checkedBuild"
    private static let lastAttemptKey = "update.lastAttempt"

    init() {
        build = (Bundle.main.infoDictionary?["MinisBuildNumber"] as? String).flatMap(Int.init) ?? 0
        let defaults = UserDefaults.standard
        lastAttempt = defaults.object(forKey: Self.lastAttemptKey) as? Date
        // A freshly installed build should re-check at once, not wait behind the
        // previous build's five-minute retry gate.
        if defaults.integer(forKey: Self.checkedBuildKey) != build {
            defaults.removeObject(forKey: Self.lastAttemptKey)
            lastAttempt = nil
        }
        if let pending = defaults.object(forKey: Self.pendingBuildKey) as? Int, build >= pending {
            defaults.removeObject(forKey: Self.pendingBuildKey)
        }
        if let data = defaults.data(forKey: Self.cachedManifestKey),
           let cached = try? JSONDecoder().decode(UpdateManifest.self, from: data), cached.isValid,
           let rawURL = defaults.string(forKey: Self.cachedIPAURLKey),
           let url = URL(string: rawURL), Self.isReleaseURL(url) {
            manifest = cached
            ipaURL = url
            showManifest()
        }
        downloadObservation = UpdateDownloadCoordinator.shared.$state.sink { [weak self] state in
            self?.acceptDownloadState(state)
        }
    }

    /// Used from launch, foreground, Settings and About. Cached results survive
    /// the daily throttle; failures retry after five minutes, not after a day.
    func autoCheckIfDue(enabled: Bool) {
        let defaults = UserDefaults.standard
        let sameBuild = defaults.integer(forKey: Self.checkedBuildKey) == build
        guard UpdateCheckSchedule.shouldCheck(enabled: enabled,
            hasCachedResult: manifest != nil && sameBuild,
            lastSuccess: defaults.object(forKey: Self.lastCheckKey) as? Date,
            lastAttempt: lastAttempt, now: Date()) else { return }
        check(manual: false)
    }

    func autoCheckIfEnabled() {
        guard UIApplication.shared.applicationState == .active else { return }
        let enabled = UserDefaults.standard.object(forKey: "update.autoCheck") as? Bool ?? true
        autoCheckIfDue(enabled: enabled)
    }

    func check(manual: Bool) {
        guard task == nil, !transferBusy, verificationTask == nil else { return }
        if case .downloadReady = phase { return }
        if case .openingInstaller = phase { return }
        if case .installing = phase { return }
        lastAttempt = Date()
        UserDefaults.standard.set(lastAttempt, forKey: Self.lastAttemptKey)
        retryAction = .check
        isLatest = false
        phase = .checking
        // A failed recheck must not erase a previously discovered update badge.
        let id = UUID()
        checkID = id
        task = Task { [weak self] in
            guard let self else { return }
            defer { if self.checkID == id { self.task = nil } }
            do {
                let (fresh, ipa) = try await self.fetchManifest()
                try Task.checkCancellation()
                guard self.checkID == id else { return }
                if let known = self.manifest, known.build > fresh.build {
                    throw UpdateError("更新服务器返回了较旧清单，请稍后重试")
                }
                let data = try JSONEncoder().encode(fresh)
                let defaults = UserDefaults.standard
                defaults.set(data, forKey: Self.cachedManifestKey)
                defaults.set(ipa.absoluteString, forKey: Self.cachedIPAURLKey)
                defaults.set(self.build, forKey: Self.checkedBuildKey)
                defaults.set(Date(), forKey: Self.lastCheckKey)
                self.manifest = fresh
                self.ipaURL = ipa
                self.showManifest()
                NSLog("[AppUpdate] check success build=%d manual=%d", fresh.build, manual ? 1 : 0)
            } catch {
                guard !Task.isCancelled, self.checkID == id else { return }
                self.phase = .failed(title: "检查失败", message: Self.errorText(error))
                NSLog("[AppUpdate] check failed: %@", Self.errorText(error))
            }
        }
    }

    private func showManifest() {
        guard let manifest else {
            hasUpdate = false
            isLatest = false
            phase = .idle
            return
        }
        hasUpdate = manifest.build > build
        isLatest = !hasUpdate
        phase = hasUpdate ? .available(build: manifest.build, version: manifest.version,
                                      size: manifest.size, notes: manifest.notes) : .latest
    }

    private var transferBusy: Bool {
        switch UpdateDownloadCoordinator.shared.state {
        case .restoring, .downloading: return true
        default: return false
        }
    }

    func downloadAndInstall() {
        guard let manifest, manifest.build > build, let ipaURL,
              task == nil, verificationTask == nil, !transferBusy else { return }
        guard schemeAvailable else { phase = .schemeMissing(manifest.version); return }
        retryAction = .download
        do {
            try UpdateDownloadCoordinator.shared.start(manifest: manifest, from: ipaURL)
        } catch {
            phase = .failed(title: "下载失败", message: Self.errorText(error))
        }
    }

    private var schemeAvailable: Bool {
        guard let url = URL(string: "apple-magnifier://") else { return false }
        return UIApplication.shared.canOpenURL(url)
    }

    private func adoptDownload(_ download: UpdateManifest) {
        if manifest != download || ipaURL == nil {
            ipaURL = UpdateDownloadCoordinator.shared.restoredSourceURL
        }
        manifest = download
    }

    private func acceptDownloadState(_ state: UpdateDownloadCoordinator.State) {
        switch state {
        case .idle:
            if phase == .restoring {
                showManifest()
                // @Published emits before the coordinator's stored state changes.
                // Defer one turn so the initial restore cannot swallow auto-check.
                Task { @MainActor [weak self] in self?.autoCheckIfEnabled() }
            }
        case .restoring:
            phase = .restoring
        case let .downloading(download, fraction):
            adoptDownload(download)
            hasUpdate = download.build > build
            isLatest = !hasUpdate
            phase = .downloading(fraction)
        case let .downloaded(download, _):
            if download.build <= build {
                if manifest == nil { manifest = download }
                showManifest()
                Task { @MainActor in UpdateDownloadCoordinator.shared.discardDownload() }
                return
            }
            adoptDownload(download)
            hasUpdate = true
            isLatest = false
            retryAction = .install
            phase = .downloadReady(download.version)
        case let .failed(download, message):
            if let download, download.build <= build {
                if manifest == nil { manifest = download }
                showManifest()
                return
            }
            if let download { manifest = download; hasUpdate = true; isLatest = false }
            retryAction = ipaURL == nil ? .check : .download
            phase = .failed(title: "下载失败", message: message)
        }
    }

    /// Hash on a utility thread; foreground handoff always needs a user tap.
    func installDownloaded() {
        guard task == nil, verificationTask == nil,
              case let .downloaded(download, file) = UpdateDownloadCoordinator.shared.state,
              download.build > build else { return }
        guard schemeAvailable else { phase = .schemeMissing(download.version); return }
        let id = UUID()
        installID = id
        retryAction = .install
        phase = .verifying
        verificationTask = Task { [weak self] in
            guard let self else { return }
            defer { if self.installID == id { self.verificationTask = nil } }
            do {
                let worker = Task.detached(priority: .utility) {
                    try Self.verifyFile(file, manifest: download)
                }
                try await withTaskCancellationHandler(operation: {
                    try await worker.value
                }, onCancel: { worker.cancel() })
                try Task.checkCancellation()
                guard self.installID == id else { return }
            } catch {
                guard !Task.isCancelled, self.installID == id else { return }
                UpdateDownloadCoordinator.shared.discardDownload()
                self.retryAction = .download
                self.phase = .failed(title: "校验失败", message: Self.errorText(error))
                return
            }
            guard UIApplication.shared.applicationState == .active else {
                self.phase = .downloadReady(download.version)
                return
            }
            self.phase = .openingInstaller
            do {
                try await self.handToTrollStore(file: file, build: download.build)
            } catch {
                guard self.installID == id else { return }
                self.phase = .failed(title: "打开安装器失败", message: Self.errorText(error))
            }
        }
    }

    func retry() {
        switch retryAction {
        case .check: check(manual: true)
        case .download: downloadAndInstall()
        case .install: installDownloaded()
        }
    }

    func cancel() {
        checkID = UUID()
        installID = UUID()
        task?.cancel()
        verificationTask?.cancel()
        task = nil
        verificationTask = nil
        UpdateDownloadCoordinator.shared.cancel()
        showManifest()
    }

    func schemeSettingsReturned() {
        guard case .schemeMissing = phase, schemeAvailable else { return }
        if case let .downloaded(download, _) = UpdateDownloadCoordinator.shared.state {
            phase = .downloadReady(download.version)
        } else {
            showManifest()
        }
    }

    func openTrollStore() {
        if let url = URL(string: "apple-magnifier://") {
            UIApplication.shared.open(url, options: [:], completionHandler: nil)
        }
    }

    // MARK: - Networking

    /// Releases are addressed by FIXED paths, never through api.github.com.
    ///
    /// The anonymous REST API allows 60 requests per hour per IP; the app, the
    /// developer and every tool on the same network share it, and exhausting it
    /// made every check fail with 403 (reported on device 2026-11-05). The
    /// release tag and the asset name are constant, so the plain
    /// `releases/download/<tag>/<asset>` URLs serve the same bytes through the
    /// download path, which has no such quota. Nothing here needs the API.
    private static func releaseAssetURL(_ name: String) -> URL? {
        guard !name.isEmpty, name == (name as NSString).lastPathComponent,
              !name.contains("\\"),
              var components = URLComponents(string: "https://github.com/\(repository)/releases/download/\(channelTag)/\(name)") else {
            return nil
        }
        // A build republishes the same tag, so never trust a cached body. The
        // query only defeats intermediaries; GitHub ignores it.
        components.queryItems = [URLQueryItem(name: "v", value: UUID().uuidString)]
        return components.url
    }

    private static func isReleaseURL(_ url: URL) -> Bool {
        url.scheme == "https" && url.host?.lowercased() == "github.com"
            && url.path.hasPrefix("/\(repository)/releases/download/")
            && url.user == nil && url.password == nil
    }

    private static func request(_ url: URL, accept: String) -> URLRequest {
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalAndRemoteCacheData,
                                 timeoutInterval: 25)
        request.setValue("OpenMinis-Updater/1.0 (iOS)", forHTTPHeaderField: "User-Agent")
        request.setValue(accept, forHTTPHeaderField: "Accept")
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        return request
    }

    private static func requireOK(_ response: URLResponse, stage: String) throws {
        guard let http = response as? HTTPURLResponse else {
            throw UpdateError("\(stage):没有收到 HTTP 响应")
        }
        guard http.statusCode == 200 else {
            let detail: String
            switch http.statusCode {
            case 404, 410:
                // The publisher deletes and recreates the tag on every build:
                // this is the publish gap, not a broken repository.
                detail = "更新可能正在发布,请稍后重试"
            case 403, 429:
                if http.value(forHTTPHeaderField: "X-RateLimit-Remaining") == "0" {
                    detail = "GitHub 请求额度已用完,请稍后重试"
                } else {
                    detail = "GitHub 暂时拒绝或限制了请求,请稍后重试"
                }
            case 500...599: detail = "GitHub 服务暂时异常,请稍后重试"
            default: detail = "服务器未能完成请求"
            }
            throw UpdateError("\(stage):HTTP \(http.statusCode),\(detail)")
        }
    }

    private func fetchManifest() async throws -> (UpdateManifest, URL) {
        guard let manifestURL = Self.releaseAssetURL("latest.json"),
              Self.isReleaseURL(manifestURL) else {
            throw UpdateError("版本清单地址不合法")
        }
        let (data, response) = try await URLSession.shared.data(
            for: Self.request(manifestURL, accept: "application/json"))
        try Self.requireOK(response, stage: "读取版本清单")
        var manifest: UpdateManifest
        do { manifest = try JSONDecoder().decode(UpdateManifest.self, from: data) }
        catch { throw UpdateError("版本清单格式不正确,请稍后重试") }
        guard manifest.isValid else { throw UpdateError("版本清单的构建号、文件名、大小或校验值无效") }
        // The IPA sits next to the manifest under the same tag; the manifest
        // names it, and `isValid` already rejected any path-like name.
        guard let ipaURL = Self.releaseAssetURL(manifest.ipa), Self.isReleaseURL(ipaURL) else {
            throw UpdateError("安装包地址不合法")
        }
        return (manifest, ipaURL)
    }

    nonisolated static func verifyFile(_ file: URL, manifest: UpdateManifest) throws {
        guard manifest.isValid else { throw UpdateError("版本清单无效") }
        let handle = try FileHandle(forReadingFrom: file)
        defer { try? handle.close() }
        var hasher = SHA256()
        var written: Int64 = 0
        while true {
            try Task.checkCancellation()
            let data = try handle.read(upToCount: 1 << 20) ?? Data()
            if data.isEmpty { break }
            written += Int64(data.count)
            guard written <= manifest.size else { throw UpdateError("包大小超出版本清单") }
            hasher.update(data: data)
        }
        guard written == manifest.size else {
            throw UpdateError("包大小不符（\(written) / \(manifest.size)）")
        }
        let digest = hasher.finalize().map { String(format: "%02x", $0) }.joined()
        guard digest.caseInsensitiveCompare(manifest.sha256) == .orderedSame else {
            throw UpdateError("SHA-256 校验失败，请重新下载")
        }
    }

    private func handToTrollStore(file: URL, build: Int) async throws {
        guard var components = URLComponents(string: "apple-magnifier://install") else {
            throw UpdateError("无法生成安装链接")
        }
        components.queryItems = [URLQueryItem(name: "url", value: file.absoluteString)]
        guard let url = components.url else { throw UpdateError("无法生成安装链接") }
        UserDefaults.standard.set(build, forKey: Self.pendingBuildKey)
        let opened = await withCheckedContinuation { (continuation: CheckedContinuation<Bool, Never>) in
            UIApplication.shared.open(url, options: [:]) { accepted in
                continuation.resume(returning: accepted)
            }
        }
        guard opened else {
            UserDefaults.standard.removeObject(forKey: Self.pendingBuildKey)
            throw UpdateError("无法打开 TrollStore，请确认已启用 URL Scheme")
        }
        phase = .installing
    }

    func becameActive() {
        schemeSettingsReturned()
        if case .installing = phase,
           case let .downloaded(download, _) = UpdateDownloadCoordinator.shared.state {
            phase = .downloadReady(download.version)
        }
        autoCheckIfEnabled()
    }

    private static func errorText(_ error: Error) -> String {
        if let error = error as? UpdateError { return error.text }
        if let error = error as? URLError {
            switch error.code {
            case .timedOut: return "网络请求超时，请重试"
            case .notConnectedToInternet: return "当前没有网络连接"
            case .networkConnectionLost: return "网络连接中断，请重试"
            case .cannotFindHost, .cannotConnectToHost: return "无法连接 GitHub，请检查网络"
            default: return "网络错误（\(error.errorCode)）：\(error.localizedDescription)"
            }
        }
        return error.localizedDescription
    }
}

struct UpdateError: Error {
    let text: String
    init(_ text: String) { self.text = text }
}

enum UpdateCheckSchedule {
    static let successInterval: TimeInterval = 24 * 3600
    static let retryInterval: TimeInterval = 5 * 60

    static func shouldCheck(enabled: Bool, hasCachedResult: Bool,
                            lastSuccess: Date?, lastAttempt: Date?, now: Date) -> Bool {
        guard enabled else { return false }
        if let lastAttempt, (0..<retryInterval).contains(now.timeIntervalSince(lastAttempt)) { return false }
        let failedSinceSuccess = lastAttempt.map { attempt in
            lastSuccess.map { attempt > $0 } ?? true
        } ?? false
        if hasCachedResult, !failedSinceSuccess, let lastSuccess,
           (0..<successInterval).contains(now.timeIntervalSince(lastSuccess)) { return false }
        return true
    }
}

private struct PersistedUpdateDownload: Codable {
    let transferID: String
    let manifest: UpdateManifest
    let sourceURL: String
    let relativePath: String
    let taskIdentifier: Int

    var isValid: Bool {
        guard manifest.isValid, UUID(uuidString: transferID) != nil,
              let url = URL(string: sourceURL), url.scheme == "https",
              url.host?.lowercased() == "github.com",
              url.path.hasPrefix("/Niubiprass/OpenMinis/releases/download/"),
              url.user == nil, url.password == nil else { return false }
        return relativePath == "MinisUpdates/\(transferID)/\(manifest.ipa)"
    }
}

private enum UpdateDownloadPersistence {
    static let key = "update.download.pending" // migrate older local candidates
    static let rootName = "MinisUpdates"

    static var root: URL {
        FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
            .appendingPathComponent(rootName, isDirectory: true)
    }
    static var metadataURL: URL { root.appendingPathComponent("download.json") }

    static func load() -> PersistedUpdateDownload? {
        // Atomic disk metadata is durable before resume. UserDefaults alone can
        // still be pending in cfprefsd when the app is suspended or reclaimed.
        let data: Data?
        if FileManager.default.fileExists(atPath: metadataURL.path) {
            data = try? Data(contentsOf: metadataURL)
        } else {
            data = UserDefaults.standard.data(forKey: key)
        }
        guard let data else { return nil }
        return try? JSONDecoder().decode(PersistedUpdateDownload.self, from: data)
    }

    static func save(_ record: PersistedUpdateDownload) throws {
        guard record.isValid else { throw UpdateError("下载记录无效") }
        try prepareDirectory(root)
        try JSONEncoder().encode(record).write(to: metadataURL, options: .atomic)
        UserDefaults.standard.removeObject(forKey: key)
    }

    static func clear() throws {
        if FileManager.default.fileExists(atPath: metadataURL.path) {
            try FileManager.default.removeItem(at: metadataURL)
        }
        UserDefaults.standard.removeObject(forKey: key)
    }

    static func prepareDirectory(_ directory: URL) throws {
        try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true,
            attributes: [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication])
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        var url = directory
        try url.setResourceValues(values)
    }

    static func fileURL(relativePath: String) -> URL {
        // Callers validate the exact UUID/name-derived relative path first.
        root.deletingLastPathComponent().appendingPathComponent(relativePath, isDirectory: false)
    }
}

// This delegate is used only with OperationQueue.main. Synchronous forwarding
// preserves callback order and moves the temporary file before returning.
@MainActor
private final class UpdateDownloadSessionDelegate: NSObject, URLSessionDownloadDelegate {
    weak var owner: UpdateDownloadCoordinator?

    nonisolated func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                                didWriteData bytesWritten: Int64, totalBytesWritten: Int64,
                                totalBytesExpectedToWrite: Int64) {
        MainActor.assumeIsolated {
            guard let id = downloadTask.taskDescription else { return }
            owner?.didWrite(transferID: id, received: totalBytesWritten,
                            expected: totalBytesExpectedToWrite)
        }
    }

    nonisolated func urlSession(_ session: URLSession, downloadTask: URLSessionDownloadTask,
                                didFinishDownloadingTo location: URL) {
        MainActor.assumeIsolated {
            owner?.receivedFile(task: downloadTask, location: location)
        }
    }

    nonisolated func urlSession(_ session: URLSession, task: URLSessionTask,
                                didCompleteWithError error: Error?) {
        MainActor.assumeIsolated {
            guard let id = task.taskDescription else { return }
            owner?.didComplete(transferID: id, message: error?.localizedDescription)
        }
    }

    nonisolated func urlSessionDidFinishEvents(forBackgroundURLSession session: URLSession) {
        MainActor.assumeIsolated { owner?.didDrainBackgroundEvents() }
    }
}

@MainActor
final class UpdateDownloadCoordinator: ObservableObject {
    enum State: Equatable {
        case idle
        case restoring
        case downloading(UpdateManifest, Double)
        case downloaded(UpdateManifest, URL)
        case failed(UpdateManifest?, String)
    }

    static let shared = UpdateDownloadCoordinator()
    nonisolated static let sessionIdentifier = "com.openminis.app.update-download"

    @Published private(set) var state: State = .idle

    var restoredSourceURL: URL? {
        guard let record = UpdateDownloadPersistence.load(), record.isValid,
              record.transferID == currentTransferID else { return nil }
        return URL(string: record.sourceURL)
    }

    private let delegate: UpdateDownloadSessionDelegate
    private let session: URLSession
    private var currentTransferID: String?
    private var currentTaskIdentifier: Int?
    private var currentManifest: UpdateManifest?
    private var lastProgressPublish = Date.distantPast
    private var backgroundCompletions: [() -> Void] = []
    private var backgroundEventsFinished = false
    private var restorationID = UUID()

    init() {
        let delegate = UpdateDownloadSessionDelegate()
        self.delegate = delegate
        let configuration = URLSessionConfiguration.background(withIdentifier: Self.sessionIdentifier)
        configuration.isDiscretionary = false
        configuration.sessionSendsLaunchEvents = true
        configuration.allowsCellularAccess = true
        configuration.waitsForConnectivity = true
        configuration.timeoutIntervalForResource = 24 * 3600
        self.session = URLSession(configuration: configuration, delegate: delegate,
                                   delegateQueue: OperationQueue.main)
        delegate.owner = self
        restore()
    }

    func start(manifest: UpdateManifest, from url: URL) throws {
        guard manifest.isValid else { throw UpdateError("版本清单无效") }
        guard url.scheme?.lowercased() == "https", url.host?.lowercased() == "github.com",
              url.path.hasPrefix("/Niubiprass/OpenMinis/releases/download/"),
              url.user == nil, url.password == nil else {
            throw UpdateError("下载地址不安全")
        }
        guard manifest.ipa == (manifest.ipa as NSString).lastPathComponent,
              !manifest.ipa.contains("\\") else {
            throw UpdateError("安装包文件名不安全")
        }
        switch state {
        case .restoring, .downloading:
            throw UpdateError("下载已经在进行中")
        default:
            break
        }
        guard finishAndClear(cancelTask: true) else { throw UpdateError("无法清除旧下载记录，请重试") }

        let transferID = UUID().uuidString
        let relativePath = "\(UpdateDownloadPersistence.rootName)/\(transferID)/\(manifest.ipa)"
        let destination = UpdateDownloadPersistence.fileURL(relativePath: relativePath)
        try UpdateDownloadPersistence.prepareDirectory(destination.deletingLastPathComponent())
        var request = URLRequest(url: url, cachePolicy: .reloadIgnoringLocalCacheData)
        request.setValue("OpenMinis-Updater/1.0 (iOS)", forHTTPHeaderField: "User-Agent")
        request.setValue("no-cache", forHTTPHeaderField: "Cache-Control")
        let task = session.downloadTask(with: request)
        task.taskDescription = transferID
        let record = PersistedUpdateDownload(transferID: transferID, manifest: manifest,
                                              sourceURL: url.absoluteString,
                                              relativePath: relativePath,
                                              taskIdentifier: task.taskIdentifier)
        do { try UpdateDownloadPersistence.save(record) }
        catch {
            task.cancel()
            try? FileManager.default.removeItem(at: destination.deletingLastPathComponent())
            throw error
        }
        currentTransferID = transferID
        currentTaskIdentifier = task.taskIdentifier
        currentManifest = manifest
        lastProgressPublish = .distantPast
        backgroundEventsFinished = false
        state = .downloading(manifest, 0)
        task.resume()
    }

    func cancel() {
        finishAndClear(cancelTask: true)
    }

    func discardDownload() {
        finishAndClear(cancelTask: true)
    }

    func handleBackgroundEvents(completionHandler: @escaping () -> Void) {
        backgroundCompletions.append(completionHandler)
        // A finished batch from yesterday must not acknowledge today's batch.
        backgroundEventsFinished = false
        // A cold reconnection can find no tasks because all terminal callbacks
        // were delivered just before UIKit registered this handler. A one-shot
        // snapshot covers that case without a timer or prematurely acknowledging
        // an active download. File moves/terminal state writes are synchronous.
        session.getAllTasks { [weak self] tasks in
            guard tasks.isEmpty else { return }
            Task { @MainActor [weak self] in self?.finishBackgroundEventsIfIdle() }
        }
    }

    private func finishBackgroundEventsIfIdle() {
        guard !backgroundCompletions.isEmpty, currentTaskIdentifier == nil else { return }
        switch state {
        case .restoring, .downloading: return
        default: didDrainBackgroundEvents()
        }
    }

    fileprivate func didWrite(transferID: String, received: Int64, expected: Int64) {
        guard transferID == currentTransferID, let manifest = currentManifest else { return }
        switch state {
        case .downloaded, .failed: return
        default: break
        }
        let now = Date()
        guard now.timeIntervalSince(lastProgressPublish) >= 0.2 || received == expected else { return }
        lastProgressPublish = now
        let fraction = min(max(Double(received) / Double(max(manifest.size, 1)), 0), 0.99)
        state = .downloading(manifest, fraction)
    }

    fileprivate func didFinish(transferID: String, file: URL) {
        guard transferID == currentTransferID,
              let record = UpdateDownloadPersistence.load(), record.transferID == transferID else {
            return
        }
        currentTaskIdentifier = nil
        currentManifest = record.manifest
        state = .downloaded(record.manifest, file)
    }

    fileprivate func didComplete(transferID: String, message: String?) {
        guard transferID == currentTransferID else { return }
        currentTaskIdentifier = nil
        switch state {
        case .downloaded, .failed: return
        default: break
        }
        state = .failed(currentManifest, message ?? "下载结束但未保存安装包，请重新下载")
    }

    fileprivate func didDrainBackgroundEvents() {
        backgroundEventsFinished = true
        finishBackgroundCompletions()
    }

    private func finishBackgroundCompletions() {
        guard backgroundEventsFinished, !backgroundCompletions.isEmpty else { return }
        let handlers = backgroundCompletions
        backgroundCompletions.removeAll()
        handlers.forEach { $0() }
    }

    @discardableResult
    private func finishAndClear(cancelTask: Bool) -> Bool {
        let transferID = currentTransferID
        let record = UpdateDownloadPersistence.load()
        currentTransferID = nil
        currentTaskIdentifier = nil
        currentManifest = nil
        restorationID = UUID()
        if cancelTask, let transferID {
            session.getAllTasks { tasks in
                tasks.filter { $0.taskDescription == transferID }.forEach { $0.cancel() }
            }
        }
        do {
            try UpdateDownloadPersistence.clear()
            if let record, record.isValid {
                let path = UpdateDownloadPersistence.fileURL(relativePath: record.relativePath)
                if FileManager.default.fileExists(atPath: path.deletingLastPathComponent().path) {
                    try FileManager.default.removeItem(at: path.deletingLastPathComponent())
                }
            }
            state = .idle
            return true
        } catch {
            state = .failed(record?.manifest, "清除旧下载失败：\(error.localizedDescription)")
            return false
        }
    }

    private func restore() {
        let saved = UpdateDownloadPersistence.load()
        let record = saved?.isValid == true ? saved : nil
        if saved != nil && record == nil { try? UpdateDownloadPersistence.clear() }
        currentTransferID = record?.transferID
        currentManifest = record?.manifest
        state = .restoring
        let restoreID = UUID()
        restorationID = restoreID
        session.getAllTasks { [weak self] tasks in
            Task { @MainActor [weak self] in
                guard let self, self.restorationID == restoreID else { return }
                guard self.currentTransferID == record?.transferID else { return }
                let file = record.map { UpdateDownloadPersistence.fileURL(relativePath: $0.relativePath) }
                let fileExists = file.map { FileManager.default.fileExists(atPath: $0.path) } ?? false
                let matching = record.flatMap { saved in
                    tasks.first { $0.taskDescription == saved.transferID
                        && $0.taskIdentifier == saved.taskIdentifier }
                }
                // This session identifier belongs exclusively to app updates.
                tasks.filter { fileExists || $0 !== matching }.forEach { $0.cancel() }
                guard case .restoring = self.state else { return }
                defer { if tasks.isEmpty { self.finishBackgroundEventsIfIdle() } }
                guard let record else { self.state = .idle; return }
                if fileExists, let file {
                    self.currentTaskIdentifier = nil
                    self.state = .downloaded(record.manifest, file)
                } else if let matching {
                    self.currentTaskIdentifier = matching.taskIdentifier
                    let expected = max(record.manifest.size, 1)
                    let fraction = min(max(Double(matching.countOfBytesReceived) / Double(expected), 0), 0.99)
                    self.state = .downloading(record.manifest, fraction)
                    if matching.state == .suspended { matching.resume() }
                } else {
                    self.state = .failed(record.manifest, "后台下载未完成，请重新下载")
                }
            }
        }
    }

    fileprivate func receivedFile(task: URLSessionDownloadTask, location: URL) {
        guard let id = task.taskDescription, id == currentTransferID,
              let record = UpdateDownloadPersistence.load(), record.transferID == id,
              record.isValid else { return }
        do {
            guard let http = task.response as? HTTPURLResponse else {
                throw UpdateError("下载没有收到 HTTP 响应")
            }
            guard http.statusCode == 200 else {
                throw UpdateError("下载失败：HTTP \(http.statusCode)，请重试")
            }
            let attributes = try FileManager.default.attributesOfItem(atPath: location.path)
            guard (attributes[.size] as? NSNumber)?.int64Value == record.manifest.size else {
                throw UpdateError("下载包大小不符，请重新检查更新")
            }
            let destination = UpdateDownloadPersistence.fileURL(relativePath: record.relativePath)
            try UpdateDownloadPersistence.prepareDirectory(destination.deletingLastPathComponent())
            if FileManager.default.fileExists(atPath: destination.path) {
                try FileManager.default.removeItem(at: destination)
            }
            try FileManager.default.moveItem(at: location, to: destination)
            didFinish(transferID: id, file: destination)
        } catch {
            let message = (error as? UpdateError)?.text ?? "无法保存安装包：\(error.localizedDescription)"
            currentTaskIdentifier = nil
            state = .failed(record.manifest, message)
        }
    }
}

private extension UpdateChecker.Phase {
    var isAvailable: Bool {
        if case .available = self { return true }
        return false
    }
}
