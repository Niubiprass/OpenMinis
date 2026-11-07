import Combine
import Foundation
import SwiftUI

/// Shared configuration store. A single revision covers one user edit, while
/// runtime delivery is retried with bounded delays instead of being dropped on
/// the first disk-cache hiccup.
@MainActor
final class MiniSightConfigStore: ObservableObject {
    static let shared = MiniSightConfigStore()

    @Published var style: Int { didSet { publish(MiniSightSettingKey.style) } }
    @Published var renderer: Int { didSet { publish(MiniSightSettingKey.renderer) } }
    @Published var mode: Int { didSet { publish(MiniSightSettingKey.mode) } }
    @Published var petSize: Double { didSet { publish(MiniSightSettingKey.petSize) } }
    @Published var gravity: Bool { didSet { publish(MiniSightSettingKey.gravity) } }
    @Published var gravityStrength: Double { didSet { publish(MiniSightSettingKey.gravityStrength) } }
    @Published var gravityShake: Bool { didSet { publish(MiniSightSettingKey.gravityShake) } }

    @Published var interaction: Bool { didSet { publish(MiniSightSettingKey.interaction) } }
    @Published var singleTap: MiniSightGesture { didSet { publish(MiniSightSettingKey.singleTap) } }
    @Published var doubleTap: MiniSightGesture { didSet { publish(MiniSightSettingKey.doubleTap) } }
    @Published var longPress: MiniSightGesture { didSet { publish(MiniSightSettingKey.longPress) } }

    @Published var activity: MiniSightActivity { didSet { publish(MiniSightSettingKey.activity) } }
    @Published var activityInterval: Double { didSet { publish(MiniSightSettingKey.activityInterval) } }
    @Published var frameLimit: Int { didSet { publish(MiniSightSettingKey.frameLimit) } }
    @Published var dragResponse: Bool { didSet { publish(MiniSightSettingKey.dragResponse) } }
    @Published var petSound: Bool { didSet { publish(MiniSightSettingKey.petSound) } }
    @Published var bottomGap: Double { didSet { publish(MiniSightSettingKey.bottomGap) } }

    @Published var tint: String { didSet { publish(MiniSightSettingKey.tint) } }
    @Published var costume: String { didSet { publish(MiniSightSettingKey.costume) } }
    @Published var supplier: String { didSet { publish(MiniSightSettingKey.supplier) } }
    @Published var downloadSource: String { didSet { publish(MiniSightSettingKey.downloadSource) } }
    @Published var darkMode: String { didSet { publish(MiniSightSettingKey.darkMode) } }

    @Published var persona: String { didSet { publish(MiniSightSettingKey.persona) } }
    @Published var nickname: String { didSet { publish(MiniSightSettingKey.nickname) } }
    @Published var aiAdjust: Bool { didSet { publish(MiniSightSettingKey.aiAdjust) } }
    @Published var proactive: Bool { didSet { publish(MiniSightSettingKey.proactive) } }
    @Published var proactiveInterval: Double { didSet { publish(MiniSightSettingKey.proactiveInterval) } }
    @Published var permissions: Set<MiniSightAIPermission>
    @Published private(set) var adjustments: [String]

    @Published var bubbleScale: Double { didSet { publish(MiniSightSettingKey.bubbleScale) } }
    @Published var textScale: Double { didSet { publish(MiniSightSettingKey.textScale) } }
    @Published var dwell: Double { didSet { publish(MiniSightSettingKey.dwell) } }
    @Published var returnKey: String { didSet { publish(MiniSightSettingKey.returnKey) } }
    @Published var voiceReply: Bool { didSet { publish(MiniSightSettingKey.voiceReply) } }
    @Published var voiceInput: Bool { didSet { publish(MiniSightSettingKey.voiceInput) } }
    @Published var snore: String { didSet { publish(MiniSightSettingKey.snore) } }

    @Published var quickButtons: Bool { didSet { publish(MiniSightSettingKey.quickButtons) } }
    @Published var quickPosition: String { didSet { publish(MiniSightSettingKey.quickPosition) } }
    @Published var quickOrder: [MiniSightQuickAction] { didSet { publish(MiniSightSettingKey.quickOrder) } }

    @Published var record: Bool { didSet { publish(MiniSightSettingKey.record) } }
    @Published var longPressRecord: Bool { didSet { publish(MiniSightSettingKey.longPressRecord) } }
    @Published var diagnostics: Bool { didSet { publish(MiniSightSettingKey.diagnostics) } }
    @Published var shown: Bool { didSet { publishShown() } }
    @Published private(set) var lastError: String?
    @Published private(set) var saveState = "已加载"

    private var loaded = false
    private var publishWork: DispatchWorkItem?
    private var publishGeneration = 0

    private init() {
        MiniSightConfig.installDefaults()
        let d = UserDefaults.standard
        style = MiniSightConfig.int(MiniSightSettingKey.style, 1)
        renderer = MiniSightConfig.int(MiniSightSettingKey.renderer, 0)
        mode = MiniSightConfig.int(MiniSightSettingKey.mode, 0)
        petSize = MiniSightConfig.double(MiniSightSettingKey.petSize, 96)
        gravity = MiniSightConfig.bool(MiniSightSettingKey.gravity, false)
        gravityStrength = MiniSightConfig.double(MiniSightSettingKey.gravityStrength, 1)
        gravityShake = MiniSightConfig.bool(MiniSightSettingKey.gravityShake, true)
        interaction = MiniSightConfig.bool(MiniSightSettingKey.interaction, true)
        singleTap = MiniSightConfig.gesture(MiniSightSettingKey.singleTap, .interact)
        doubleTap = MiniSightConfig.gesture(MiniSightSettingKey.doubleTap, .conversation)
        longPress = MiniSightConfig.gesture(MiniSightSettingKey.longPress, .menu)
        activity = MiniSightActivity(rawValue: MiniSightConfig.string(MiniSightSettingKey.activity, "lively")) ?? .lively
        activityInterval = MiniSightConfig.double(MiniSightSettingKey.activityInterval, 7)
        frameLimit = MiniSightConfig.int(MiniSightSettingKey.frameLimit, 0)
        dragResponse = MiniSightConfig.bool(MiniSightSettingKey.dragResponse, true)
        petSound = MiniSightConfig.bool(MiniSightSettingKey.petSound, false)
        bottomGap = MiniSightConfig.double(MiniSightSettingKey.bottomGap, 12)
        tint = MiniSightConfig.string(MiniSightSettingKey.tint, "natural")
        costume = MiniSightConfig.string(MiniSightSettingKey.costume, "")
        supplier = MiniSightConfig.string(MiniSightSettingKey.supplier, MiniSightSupplier.deepseek.rawValue)
        downloadSource = MiniSightConfig.string(MiniSightSettingKey.downloadSource, "")
        darkMode = MiniSightConfig.string(MiniSightSettingKey.darkMode, "system")
        persona = MiniSightConfig.string(MiniSightSettingKey.persona, "")
        nickname = MiniSightConfig.string(MiniSightSettingKey.nickname, "")
        aiAdjust = MiniSightConfig.bool(MiniSightSettingKey.aiAdjust, false)
        proactive = MiniSightConfig.bool(MiniSightSettingKey.proactive, false)
        proactiveInterval = MiniSightConfig.double(MiniSightSettingKey.proactiveInterval, 30)
        permissions = MiniSightConfig.permissionSet()
        adjustments = d.stringArray(forKey: MiniSightSettingKey.adjustments) ?? []
        bubbleScale = MiniSightConfig.double(MiniSightSettingKey.bubbleScale, 1)
        textScale = MiniSightConfig.double(MiniSightSettingKey.textScale, 1)
        dwell = MiniSightConfig.double(MiniSightSettingKey.dwell, 1)
        returnKey = MiniSightConfig.string(MiniSightSettingKey.returnKey, "send")
        voiceReply = MiniSightConfig.bool(MiniSightSettingKey.voiceReply, false)
        voiceInput = MiniSightConfig.bool(MiniSightSettingKey.voiceInput, false)
        snore = MiniSightConfig.string(MiniSightSettingKey.snore, "off")
        quickButtons = MiniSightConfig.bool(MiniSightSettingKey.quickButtons, true)
        quickPosition = MiniSightConfig.string(MiniSightSettingKey.quickPosition, "above")
        quickOrder = MiniSightConfig.quickOrder()
        record = MiniSightConfig.bool(MiniSightSettingKey.record, false)
        longPressRecord = MiniSightConfig.bool(MiniSightSettingKey.longPressRecord, true)
        diagnostics = MiniSightConfig.bool(MiniSightSettingKey.diagnostics, false)
        // `shown` has two consumers with different formats: the plist key for
        // settings and the plain "shown" file the SpringBoard runtime reads.
        // The file is authoritative; load it instead of the stale default.
        let fileShown = MiniSightPetFile.loadShown()
        shown = fileShown
        UserDefaults.standard.set(fileShown, forKey: MiniSightSettingKey.shown)
        loaded = true
        // Older installs have plist values but no runtime snapshot. Without
        // this, the plugin falls back to menu until the first settings edit.
        if !FileManager.default.fileExists(atPath: container.appendingPathComponent("Documents/MiniSight/runtime.json").path) {
            _ = writeSnapshot()
        }
    }

    private var container: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            .deletingLastPathComponent()
    }

    private func raw(_ key: String) -> Any {
        switch key {
        case MiniSightSettingKey.shown: return shown
        case MiniSightSettingKey.style: return style
        case MiniSightSettingKey.renderer: return renderer
        case MiniSightSettingKey.mode: return mode
        case MiniSightSettingKey.petSize: return petSize
        case MiniSightSettingKey.gravity: return gravity
        case MiniSightSettingKey.gravityStrength: return gravityStrength
        case MiniSightSettingKey.gravityShake: return gravityShake
        case MiniSightSettingKey.interaction: return interaction
        case MiniSightSettingKey.singleTap: return singleTap.rawValue
        case MiniSightSettingKey.doubleTap: return doubleTap.rawValue
        case MiniSightSettingKey.longPress: return longPress.rawValue
        case MiniSightSettingKey.activity: return activity.rawValue
        case MiniSightSettingKey.activityInterval: return activityInterval
        case MiniSightSettingKey.frameLimit: return frameLimit
        case MiniSightSettingKey.dragResponse: return dragResponse
        case MiniSightSettingKey.petSound: return petSound
        case MiniSightSettingKey.bottomGap: return bottomGap
        case MiniSightSettingKey.tint: return tint
        case MiniSightSettingKey.costume: return costume
        case MiniSightSettingKey.darkMode: return darkMode
        case MiniSightSettingKey.supplier: return supplier
        case MiniSightSettingKey.downloadSource: return downloadSource
        case MiniSightSettingKey.nickname: return nickname
        case MiniSightSettingKey.aiAdjust: return aiAdjust
        case MiniSightSettingKey.proactive: return proactive
        case MiniSightSettingKey.proactiveInterval: return proactiveInterval
        case MiniSightSettingKey.bubbleScale: return bubbleScale
        case MiniSightSettingKey.textScale: return textScale
        case MiniSightSettingKey.dwell: return dwell
        case MiniSightSettingKey.returnKey: return returnKey
        case MiniSightSettingKey.voiceReply: return voiceReply
        case MiniSightSettingKey.voiceInput: return voiceInput
        case MiniSightSettingKey.snore: return snore
        case MiniSightSettingKey.quickButtons: return quickButtons
        case MiniSightSettingKey.quickPosition: return quickPosition
        case MiniSightSettingKey.quickOrder: return quickOrder.map(\.rawValue).joined(separator: ",")
        case MiniSightSettingKey.record: return record
        case MiniSightSettingKey.longPressRecord: return longPressRecord
        case MiniSightSettingKey.diagnostics: return diagnostics
        case MiniSightSettingKey.aiPermissions: return MiniSightAIPermission.allCases.filter(permissions.contains).map(\.rawValue).joined(separator: ",")
        case MiniSightSettingKey.persona: return persona
        case MiniSightSettingKey.adjustments: return adjustments
        case MiniSightSettingKey.quickLines: return quickLines
        case MiniSightSettingKey.shownRevision: return UserDefaults.standard.string(forKey: key) ?? ""
        default: preconditionFailure("Unknown MiniSight transport key")
        }
    }

    /// The pet switch writes BOTH channels before notifying: the shown file is
    /// what the plugin/runtime actually reads, the plist is what the settings
    /// readback verifies. Without this the toggle only changed memory and the
    /// next scene-active refresh reverted it from the untouched file.
    private func publishShown() {
        guard loaded else { return }
        let on = shown
        do {
            try MiniSightPetFile.saveShown(on) {
                UserDefaults.standard.set(on, forKey: MiniSightSettingKey.shown)
            }
            publish(MiniSightSettingKey.shown)
        } catch {
            lastError = "桌宠显示状态没能保存，请重试。"
            saveState = "保存失败"
            let rev = UUID().uuidString
            MSDiagEvent("settings", "save", "failed",
                        ["setting": MiniSightSettingKey.shown, "source": "settings",
                         "revision": rev, "code": (error as NSError).code])
        }
    }

    /// The hide action in the pet menu writes only the file. Sync the switch
    /// when its page appears instead of showing an outdated ON state.
    func reloadShownFromFile() {
        let fileValue = MiniSightPetFile.loadShown()
        if shown != fileValue { shown = fileValue }
    }

    /// Defaults keep the App's local view; the atomic, verified runtime file is
    /// the delivery contract. CFPreferences' asynchronous flush is NOT an ACK.
    private func publish(_ key: String) {
        guard loaded else { return }
        let d = UserDefaults.standard
        d.set(raw(key), forKey: key)
        let revision = UUID().uuidString
        d.set(revision, forKey: MiniSightSettingKey.shownRevision)
        publishGeneration &+= 1
        saveState = "正在保存并核对…"
        // Never pass values: persona, nickname, quick lines, asset source and
        // custom costume names are free text, even when they look harmless.
        MSDiagEvent("settings", "save", "pending",
                    ["setting": key, "source": "settings", "revision": revision,
                     "generation": publishGeneration])
        deliver(generation: publishGeneration, revision: revision, attempt: 0)
    }

    private func deliver(generation: Int, revision: String, attempt: Int) {
        guard generation == publishGeneration else { return }
        let ok = self.writeSnapshot()
        MSDiagEvent("settings", "readback", ok ? "ok" : "failed",
                    ["source": "app", "revision": revision, "readback": ok,
                     "generation": generation, "count": attempt,
                     "reason": ok ? "snapshot_verified" : "snapshot_write_failed"])
        if ok {
            MSDiagEvent("settings", "publish", "ok",
                        ["source": "app", "revision": revision, "reason": "revision_visible"])
            lastError = nil
            saveState = "已保存并核对"
            return
        }
        MSDiagEvent("settings", "publish", "pending",
                    ["source": "app", "revision": revision, "reason": "revision_retry"])
        lastError = attempt < 4 ? "设置尚未完成落盘，正在重试。" : "设置保存失败，请重试。"
        saveState = attempt < 4 ? "等待磁盘确认…" : "保存失败"
        guard attempt < 4 else { return } // attempt >= 4: bounded retries exhausted
        let delay = DispatchTimeInterval.milliseconds([350, 700, 1200, 2000][attempt])
        DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
            self?.deliver(generation: generation, revision: revision, attempt: attempt + 1)
        }
    }

    @discardableResult
    func writeSnapshot() -> Bool {
        var values: [String: Any] = [:]
        for key in MiniSightConfig.all { values[key] = raw(key) }
        return MiniSightRuntimeSnapshot.write(container: container, rawValues: values)
    }

    func persistAll() {
        let d = UserDefaults.standard
        d.set(UUID().uuidString, forKey: MiniSightSettingKey.shownRevision)
        for key in MiniSightConfig.all { d.set(raw(key), forKey: key) }
        do {
            try MiniSightPetFile.saveShown(shown) { }
            publishGeneration &+= 1
            deliver(generation: publishGeneration,
                    revision: d.string(forKey: MiniSightSettingKey.shownRevision) ?? "", attempt: 0)
        } catch {
            lastError = "桌宠显示状态没能保存，请重试。"
            saveState = "保存失败"
        }
    }

    func setPermission(_ permission: MiniSightAIPermission, allowed: Bool) {
        if allowed { permissions.insert(permission) } else { permissions.remove(permission) }
        publish(MiniSightSettingKey.aiPermissions)
    }

    var quickLines: [String: String] {
        (UserDefaults.standard.dictionary(forKey: MiniSightSettingKey.quickLines) as? [String: String]) ?? [:]
    }

    func setQuickLine(_ text: String, for action: MiniSightQuickAction) {
        MiniSightConfig.setQuickLine(text, for: action)
        publish(MiniSightSettingKey.quickLines)
    }

    func moveQuick(from: Int, to: Int) {
        guard from >= 0, from < quickOrder.count, to >= 0, to < quickOrder.count, from != to else { return }
        var next = quickOrder
        let item = next.remove(at: from)
        next.insert(item, at: to)
        quickOrder = next
    }

    func noteAdjustment(_ text: String) {
        adjustments.insert(text, at: 0)
        if adjustments.count > 12 { adjustments.removeLast(adjustments.count - 12) }
        publish(MiniSightSettingKey.adjustments)
    }
}
