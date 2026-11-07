import Combine
import Foundation

/// One canonical interpretation of the MiniSight defaults. App pages and
/// runtime only read typed values from here; no view owns a second copy.
enum MiniSightSettingKey {
    static let style = "minisight.style"
    static let renderer = "minisight.renderer"
    static let mode = "minisight.mode"
    static let petSize = "minisight.petSize"
    static let gravity = "minisight.gravity"
    static let gravityStrength = "minisight.gravity.strength"
    static let gravityShake = "minisight.gravity.shake"

    static let interaction = "minisight.interaction"
    static let singleTap = "minisight.gesture.single"
    static let doubleTap = "minisight.gesture.double"
    static let longPress = "minisight.gesture.long"

    static let activity = "minisight.activity"
    static let activityInterval = "minisight.activity.interval"
    static let frameLimit = "minisight.frameLimit"
    static let dragResponse = "minisight.dragResponse"
    static let petSound = "minisight.petSound"
    static let bottomGap = "minisight.bottomGap"

    static let tint = "minisight.pet.tint"
    static let costume = "minisight.pet.costume"
    static let supplier = "minisight.ai.supplier"
    static let downloadSource = "minisight.asset.source"
    static let darkMode = "minisight.darkMode"

    static let persona = "minisight.ai.persona"
    static let nickname = "minisight.ai.nickname"
    static let aiAdjust = "minisight.ai.adjust"
    static let aiPermissions = "minisight.ai.permissions"
    static let adjustments = "minisight.ai.adjustments"
    static let proactive = "minisight.proactive"
    static let proactiveInterval = "minisight.proactive.interval"

    static let bubbleScale = "minisight.dialogue.scale"
    static let textScale = "minisight.dialogue.textScale"
    static let dwell = "minisight.dialogue.dwell"
    static let returnKey = "minisight.dialogue.return"
    static let voiceReply = "minisight.voice.reply"
    static let voiceInput = "minisight.voice.input"
    static let snore = "minisight.voice.snore"

    static let quickButtons = "minisight.quick.enabled"
    static let quickPosition = "minisight.quick.position"
    static let quickLines = "minisight.quick.lines"
    static let quickOrder = "minisight.quick.order"

    static let record = "minisight.record"
    static let longPressRecord = "minisight.longPress"
    static let diagnostics = "minisight.diagnostics"
    static let shown = "minisight.shown"
    static let shownRevision = "minisight.settings.revision"
    static var all: [String] { MiniSightConfig.all }
}

enum MiniSightGesture: String, CaseIterable {
    case none, interact, input, voice, menu, record, conversation
    var title: String {
        switch self {
        case .none: return "无操作"
        case .interact: return "点击互动"
        case .input: return "输入条"
        case .voice: return "语音输入"
        case .menu: return "功能菜单"
        case .record: return "录屏"
        case .conversation: return "对话记录"
        }
    }
}

enum MiniSightActivity: String, CaseIterable { case lively, quiet, off
    var title: String {
        switch self {
        case .lively: return "活泼"
        case .quiet: return "安静"
        case .off: return "关闭（保留呼吸与眨眼）"
        }
    }
}

enum MiniSightSupplier: String, CaseIterable {
    case deepseek, deepseekHarness, custom, chatgpt, claude, gemini, qwen, kimi, minimax
    var title: String {
        switch self {
        case .deepseek: return "DeepSeek"
        case .deepseekHarness: return "DeepSeek Harness"
        case .custom: return "自定义（手填链接）"
        case .chatgpt: return "ChatGPT"
        case .claude: return "Claude"
        case .gemini: return "Gemini"
        case .qwen: return "千问"
        case .kimi: return "Kimi"
        case .minimax: return "MiniMax"
        }
    }
    /// Real default endpoints; the user can still edit the URL by hand.
    var endpoint: String? {
        switch self {
        case .deepseek: return "https://api.deepseek.com/v1"
        case .chatgpt: return "https://api.openai.com/v1"
        case .claude: return nil // native Anthropic is not OpenAI-compatible
        case .gemini: return "https://generativelanguage.googleapis.com/v1beta/openai"
        case .qwen: return "https://dashscope.aliyuncs.com/compatible-mode/v1"
        case .kimi: return "https://api.moonshot.cn/v1"
        case .minimax: return "https://api.minimax.chat/v1"
        case .deepseekHarness, .custom: return nil
        }
    }
}

enum MiniSightQuickAction: String, CaseIterable {
    case greet, wave, jump, pat, walk
    var title: String {
        switch self {
        case .greet: return "打招呼"
        case .wave: return "挥挥手"
        case .jump: return "跳一下"
        case .pat: return "摸摸"
        case .walk: return "走一下"
        }
    }
    var defaultLine: String {
        switch self {
        case .greet: return "你回来啦。"
        case .wave: return "我在这里。"
        case .jump: return "跳一下！"
        case .pat: return "举高高。"
        case .walk: return "出去走走。"
        }
    }
}

enum MiniSightAIPermission: String, CaseIterable {
    case walk, wave, jump, rest, appearance, sound, petSize, bubbleScale, textScale, darkMode, quickButtons, nickname
    var title: String {
        switch self {
        case .walk: return "走一下"
        case .wave: return "挥手"
        case .jump: return "跳跃"
        case .rest: return "休息 / 入睡"
        case .appearance: return "配色与服装"
        case .sound: return "声音"
        case .petSize: return "角色大小"
        case .bubbleScale: return "气泡大小"
        case .textScale: return "文字大小"
        case .darkMode: return "深浅色模式"
        case .quickButtons: return "快捷按钮"
        case .nickname: return "用户称呼"
        }
    }
}

/// Raw defaults access used by the ObjC bridge and the App. Absent values must
/// keep the old behavior: pet + plugin + call mode.
enum MiniSightConfig {
    // Exactly 45 transport keys, including the transaction revision. The legacy
    // boolean minisight.longPress must NEVER alias minisight.gesture.long.
    static let runtimeFields: [String: String] = [
        MiniSightSettingKey.style: "style", MiniSightSettingKey.renderer: "renderer",
        MiniSightSettingKey.mode: "mode", MiniSightSettingKey.petSize: "petSize",
        MiniSightSettingKey.gravity: "gravity", MiniSightSettingKey.gravityStrength: "gravityStrength",
        MiniSightSettingKey.gravityShake: "gravityShake", MiniSightSettingKey.interaction: "interaction",
        MiniSightSettingKey.singleTap: "singleTap", MiniSightSettingKey.doubleTap: "doubleTap",
        MiniSightSettingKey.longPress: "longPress", MiniSightSettingKey.activity: "activity",
        MiniSightSettingKey.activityInterval: "activityInterval", MiniSightSettingKey.frameLimit: "frameLimit",
        MiniSightSettingKey.dragResponse: "dragResponse", MiniSightSettingKey.petSound: "sound",
        MiniSightSettingKey.bottomGap: "bottomGap", MiniSightSettingKey.tint: "tint",
        MiniSightSettingKey.costume: "costume", MiniSightSettingKey.supplier: "supplier",
        MiniSightSettingKey.downloadSource: "downloadSource", MiniSightSettingKey.darkMode: "darkMode",
        MiniSightSettingKey.persona: "persona", MiniSightSettingKey.nickname: "nickname",
        MiniSightSettingKey.aiAdjust: "aiAdjust", MiniSightSettingKey.aiPermissions: "aiPermissions",
        MiniSightSettingKey.adjustments: "adjustments", MiniSightSettingKey.proactive: "proactive",
        MiniSightSettingKey.proactiveInterval: "proactiveInterval", MiniSightSettingKey.bubbleScale: "bubbleScale",
        MiniSightSettingKey.textScale: "textScale", MiniSightSettingKey.dwell: "dwell",
        MiniSightSettingKey.returnKey: "returnKey", MiniSightSettingKey.voiceReply: "voiceReply",
        MiniSightSettingKey.voiceInput: "voiceInput", MiniSightSettingKey.snore: "snore",
        MiniSightSettingKey.quickButtons: "quick", MiniSightSettingKey.quickPosition: "quickPosition",
        MiniSightSettingKey.quickLines: "quickLines", MiniSightSettingKey.quickOrder: "quickOrder",
        MiniSightSettingKey.record: "record", MiniSightSettingKey.longPressRecord: "longPressRecord",
        MiniSightSettingKey.diagnostics: "diagnostics", MiniSightSettingKey.shown: "shown",
        MiniSightSettingKey.shownRevision: "revision",
    ]
    static let all = runtimeFields.keys.sorted()
    static let initial: [String: Any] = [
        MiniSightSettingKey.style: 1,
            MiniSightSettingKey.renderer: 0,
            MiniSightSettingKey.gravity: false,
            MiniSightSettingKey.costume: "",
            MiniSightSettingKey.downloadSource: "",
            MiniSightSettingKey.persona: "",
            MiniSightSettingKey.nickname: "",
            MiniSightSettingKey.adjustments: [String](),
            MiniSightSettingKey.shown: true,
            MiniSightSettingKey.shownRevision: "",
            MiniSightSettingKey.mode: 0,
            MiniSightSettingKey.petSize: 96.0,
            MiniSightSettingKey.gravityStrength: 1.0,
            MiniSightSettingKey.gravityShake: true,
            MiniSightSettingKey.interaction: true,
            MiniSightSettingKey.singleTap: MiniSightGesture.interact.rawValue,
            MiniSightSettingKey.doubleTap: MiniSightGesture.voice.rawValue,
            MiniSightSettingKey.longPress: MiniSightGesture.menu.rawValue,
            MiniSightSettingKey.activity: MiniSightActivity.lively.rawValue,
            MiniSightSettingKey.activityInterval: 7.0,
            MiniSightSettingKey.frameLimit: 0,
            MiniSightSettingKey.dragResponse: true,
            MiniSightSettingKey.petSound: false,
            MiniSightSettingKey.bottomGap: 12.0,
            MiniSightSettingKey.tint: "natural",
            MiniSightSettingKey.supplier: MiniSightSupplier.deepseek.rawValue,
            MiniSightSettingKey.darkMode: "system",
            MiniSightSettingKey.aiAdjust: false,
            MiniSightSettingKey.aiPermissions: "",
            MiniSightSettingKey.proactive: false,
            MiniSightSettingKey.proactiveInterval: 30.0,
            MiniSightSettingKey.bubbleScale: 1.0,
            MiniSightSettingKey.textScale: 1.0,
            MiniSightSettingKey.dwell: 1.0,
            MiniSightSettingKey.returnKey: "send",
            MiniSightSettingKey.voiceReply: false,
            MiniSightSettingKey.voiceInput: false,
            MiniSightSettingKey.snore: "off",
            MiniSightSettingKey.quickButtons: true,
            MiniSightSettingKey.quickPosition: "above",
            MiniSightSettingKey.quickLines: [:],
            MiniSightSettingKey.quickOrder: MiniSightQuickAction.allCases.map(\.rawValue),
            MiniSightSettingKey.record: false,
            MiniSightSettingKey.longPressRecord: true,
            MiniSightSettingKey.diagnostics: false,
    ]

    static func installDefaults() {
        let defaults = UserDefaults.standard
        for (key, value) in initial where defaults.object(forKey: key) == nil {
            defaults.set(value, forKey: key)
        }
    }

    static func int(_ key: String, _ fallback: Int) -> Int {
        guard UserDefaults.standard.object(forKey: key) != nil else { return fallback }
        return UserDefaults.standard.integer(forKey: key)
    }
    static func bool(_ key: String, _ fallback: Bool) -> Bool {
        guard UserDefaults.standard.object(forKey: key) != nil else { return fallback }
        return UserDefaults.standard.bool(forKey: key)
    }
    static func double(_ key: String, _ fallback: Double) -> Double {
        let value = UserDefaults.standard.double(forKey: key)
        return value.isFinite ? value : fallback
    }
    static func string(_ key: String, _ fallback: String) -> String {
        UserDefaults.standard.string(forKey: key) ?? fallback
    }
    static func gesture(_ key: String, _ fallback: MiniSightGesture) -> MiniSightGesture {
        MiniSightGesture(rawValue: string(key, fallback.rawValue)) ?? fallback
    }
    static func permissionSet() -> Set<MiniSightAIPermission> {
        if UserDefaults.standard.object(forKey: MiniSightSettingKey.aiPermissions) == nil {
            return Set(MiniSightAIPermission.allCases)
        }
        let raw = string(MiniSightSettingKey.aiPermissions, "")
        return Set(raw.split(separator: ",").compactMap { MiniSightAIPermission(rawValue: String($0)) })
    }
    static func setPermission(_ permission: MiniSightAIPermission, allowed: Bool) {
        var set = permissionSet()
        if allowed { set.insert(permission) } else { set.remove(permission) }
        UserDefaults.standard.set(MiniSightAIPermission.allCases.filter(set.contains).map(\.rawValue).joined(separator: ","),
                                  forKey: MiniSightSettingKey.aiPermissions)
    }

    static func quickOrder() -> [MiniSightQuickAction] {
        let raw = string(MiniSightSettingKey.quickOrder, "").split(separator: ",")
            .compactMap { MiniSightQuickAction(rawValue: String($0)) }
        return raw.isEmpty ? MiniSightQuickAction.allCases : raw
    }
    static func quickLine(_ action: MiniSightQuickAction) -> String {
        let object = UserDefaults.standard.dictionary(forKey: MiniSightSettingKey.quickLines)
        let custom = (object?[action.rawValue] as? String)?.trimmingCharacters(in: .whitespacesAndNewlines) ?? ""
        return custom.isEmpty ? action.defaultLine : custom
    }
    static func setQuickLine(_ text: String, for action: MiniSightQuickAction) {
        var object = UserDefaults.standard.dictionary(forKey: MiniSightSettingKey.quickLines) ?? [:]
        let clean = String(text.trimmingCharacters(in: .whitespacesAndNewlines).prefix(120))
        if clean.isEmpty { object.removeValue(forKey: action.rawValue) } else { object[action.rawValue] = clean }
        UserDefaults.standard.set(object, forKey: MiniSightSettingKey.quickLines)
    }
}

/// Local runtime transport of the 45 allowlisted settings, never credentials.
/// User strings belong in this file but must never be passed to diagnostics.
enum MiniSightRuntimeSnapshot {
    @discardableResult
    static func write(container: URL) -> Bool {
        var rawValues: [String: Any] = [:]
        for key in MiniSightConfig.all {
            rawValues[key] = UserDefaults.standard.object(forKey: key) ?? MiniSightConfig.initial[key]
        }
        return write(container: container, rawValues: rawValues)
    }

    @discardableResult
    static func write(container: URL, rawValues: [String: Any]) -> Bool {
        guard MiniSightConfig.runtimeFields.count == 45,
              MiniSightConfig.all.allSatisfy({ rawValues[$0] != nil }) else { return false }
        var canonical: [String: Any] = [:]
        var values: [String: Any] = ["version": 2]
        // Mutable dictionaries avoid duplicate-literal SIGTRAP. One mapping is
        // shared by legacy runtime aliases and the canonical preferences bag.
        for (key, field) in MiniSightConfig.runtimeFields {
            guard let value = rawValues[key] else { return false }
            canonical[key] = value
            values[field] = value
        }
        values["preferences"] = canonical
        let url = container.appendingPathComponent("Documents/MiniSight/runtime.json")
        do {
            let data = try JSONSerialization.data(withJSONObject: values, options: [.sortedKeys])
            guard !data.isEmpty else { return false }
            try FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
            try data.write(to: url, options: .atomic)
            let readback = try Data(contentsOf: url)
            guard !readback.isEmpty,
                  let decoded = try JSONSerialization.jsonObject(with: readback) as? [String: Any],
                  NSDictionary(dictionary: decoded).isEqual(to: values) else { return false }
            // Consumers cannot observe a notification before the complete file.
            CFNotificationCenterPostNotification(CFNotificationCenterGetDarwinNotifyCenter(),
                CFNotificationName("com.openminis.minisight.settings" as CFString), nil, nil, true)
            MSDiagEvent("settings", "publish", "ok",
                        ["source": "app", "reason": "runtime_snapshot", "chars": data.count])
            return true
        } catch {
            MSDiagEvent("settings", "publish", "failed",
                        ["source": "app", "reason": "runtime_snapshot", "code": (error as NSError).code])
            return false
        }
    }
}
