import Foundation

/// The switch grants background-name intent, not system microphone permission.
/// Foreground/renderer choose WHERE the response appears; they do not disable
/// an already-authorized real audio source when the user opens another app.
enum MiniSightWakePolicy {
    struct Context: Equatable {
        var enabled: Bool
        var foreground: Bool
        var unlocked: Bool
        var shown: Bool
        var petStyle: Bool
        var appRenderer: Bool
        var hasAsset: Bool
        var permissionGranted: Bool
        var audioAvailable: Bool
        var recordingOrCall: Bool
        var chatVisible: Bool
        var now: TimeInterval
        var cooldownUntil: TimeInterval
        var armed = false
        var companionRequired = false
        var companionReady = false
    }
    enum Decision: Equatable {
        case disabled, inactive, locked, hidden, companion, missingAsset, permission, busy, cooldown, listen
        var message: String {
            switch self {
            case .disabled: return "名字唤醒已关闭"
            case .inactive: return "请在 App 内开启并允许名字监听"
            case .locked: return "锁定时暂停名字监听"
            case .hidden: return "桌宠隐藏时暂停名字监听"
            case .companion: return "正在等越狱插件确认当前屏幕，未收到确认时不会唤醒"
            case .missingAsset: return "先导入并启用桌宠素材"
            case .permission: return "请主动开启并允许麦克风和语音权限"
            case .busy: return "通话、录屏或其他语音占用时暂时退让"
            case .cooldown: return "刚刚回应，正在稍作等待"
            case .listen: return "正在本机等你喊名字，离开 App 后继续"
            }
        }
    }
    static func safetyDecision(_ c: Context) -> Decision? {
        if !c.enabled { return .disabled }
        if !c.armed { return .inactive }
        if !c.unlocked { return .locked }
        if !c.shown || !c.petStyle { return .hidden }
        if c.companionRequired && !c.companionReady { return .companion }
        if !c.hasAsset { return .missingAsset }
        if !c.permissionGranted { return .permission }
        if !c.audioAvailable || c.recordingOrCall { return .busy }
        if !c.now.isFinite || !c.cooldownUntil.isFinite { return .cooldown }
        return nil
    }
    static func decision(_ c: Context) -> Decision {
        if let stopped = safetyDecision(c) { return stopped }
        if c.chatVisible { return .busy }
        if c.now < c.cooldownUntil { return .cooldown }
        return .listen
    }
    static func validHit(active: UUID?, incoming: UUID, isListening: Bool, decision: Decision) -> Bool {
        active == incoming && isListening && decision == .listen
    }
    static func permitsContinuation(foreground: Bool, unlocked: Bool, shown: Bool,
                                    enabled: Bool, cancelled: Bool) -> Bool {
        // Foreground is kept as call-site context only. The companion/current
        // response checks below fence background continuations separately.
        _ = foreground
        return unlocked && shown && enabled && !cancelled
    }
    static func remoteReplyCurrent(now: Double, clock: Double, token: String,
                                   expectedToken: String, host: String, expectedHost: String,
                                   revision: String, expectedRevision: String) -> Bool {
        now.isFinite && clock.isFinite && now >= clock && now - clock <= 3 &&
            token == expectedToken && host == expectedHost && revision == expectedRevision
    }
}
