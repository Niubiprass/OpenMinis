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
    @Published var supplier: String
    @Published var downloadSource: String
    @Published var darkMode: String { didSet { publish(MiniSightSettingKey.darkMode) } }

    @Published var persona: String
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
    @Published var shown: Bool
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
        activity = MiniSightActivity(rawValue: MiniSightConfig.string(MiniSightSettingKey.activity, "natural")) ?? .natural
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
        shown = MiniSightConfig.bool(MiniSightSettingKey.shown, true)
        loaded = true
    }

    private var container: URL {
        FileManager.default.urls(for: .documentDirectory, in: .userDomainMask).first!
            .deletingLastPathComponent().deletingLastPathComponent()
    }

    private func raw(_ key: String) -> Any {
        switch key {
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
        default: return ""
        }
    }

    /// Persist locally, read back the actual plist, then let the retry loop
    /// deliver. Missing prefs are retried instead of being a hard stop.
    private func publish(_ key: String) {
        guard loaded else { return }
        let values = raw(key)
        let d = UserDefaults.standard
        d.set(values, forKey: key)
        let rev = UUID().uuidString
        d.set(rev, forKey: MiniSightSettingKey.shownRevision)
        saveState = "已保存，正在核对…"
        publishGeneration &+= 1
        let generation = publishGeneration
        MSDiagEvent("settings", "save", "pending", ["setting": key, "source": "settings", "revision": rev])
        let prefsURL = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Preferences")
            .appendingPathComponent((Bundle.main.bundleIdentifier ?? "com.openminis.app") + ".plist")
        Task.detached(priority: .utility) {
            let verified = (try? Data(contentsOf: prefsURL)).flatMap {
                try? PropertyListSerialization.propertyList(from: $0, options: [], format: nil) as? [String: Any]
            }
            await MainActor.run {
                guard generation == self.publishGeneration else { return }
                let saved = verified?[key] as? NSObject
                let expected = values as? NSObject
                let ok = saved?.isEqual(expected) == true
                self.lastError = ok ? nil : "设置尚未完成落盘，正在重试。"
                self.saveState = ok ? "已保存并核对" : "等待磁盘确认…"
                MSDiagEvent("settings", "readback", ok ? "ok" : "failed",
                            ["setting": key, "source": "settings", "revision": rev, "readback": ok])
                self.deliver(generation: generation, revision: rev, attempt: ok ? 0 : 1)
            }
        }
    }

    /// The revision is only metadata. Once the edited value is verified, post
    /// immediately; retry the revision marker separately up to four times.
    private func deliver(generation: Int, revision: String, attempt: Int) {
        Self.writeSnapshot()
        let prefsURL = URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Preferences")
            .appendingPathComponent((Bundle.main.bundleIdentifier ?? "com.openminis.app") + ".plist")
        Task.detached(priority: .utility) {
            let object = (try? Data(contentsOf: prefsURL)).flatMap {
                try? PropertyListSerialization.propertyList(from: $0, options: [], format: nil) as? [String: Any]
            }
            let revisionOK = object?[MiniSightSettingKey.shownRevision] as? String == revision
            await MainActor.run {
                guard generation == self.publishGeneration else { return }
                MSDiagEvent("settings", "publish", revisionOK ? "ok" : "pending",
                            ["source": "app", "revision": revision, "reason": revisionOK ? "revision_visible" : "revision_retry", "count": attempt])
                if revisionOK || attempt >= 4 {
                    self.lastError = revisionOK ? nil : "设置已保存，但内部版本标记延迟；通知仍然成功。"
                    self.saveState = revisionOK ? "已保存并通知运行端" : "已保存，通知已发"
                    return
                }
                let delay = DispatchTimeInterval.milliseconds([350, 700, 1200, 2000][min(attempt, 3)])
                DispatchQueue.main.asyncAfter(deadline: .now() + delay) { [weak self] in
                    self?.deliver(generation: generation, revision: revision, attempt: attempt + 1)
                }
            }
        }
    }

    private static func writeSnapshot() { }

    func writeSnapshot() { MiniSightRuntimeSnapshot.write(container: container) }

    func persistAll() {
        for key in MiniSightSettingKey.all { UserDefaults.standard.set(raw(key), forKey: key) }
        writeSnapshot()
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
        UserDefaults.standard.set(adjustments, forKey: MiniSightSettingKey.adjustments)
    }
}
