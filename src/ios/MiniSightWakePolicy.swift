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
        var companionLocked = false
        var companionBusy = false

        mutating func updateCompanion(fresh: Bool, unlocked: Bool?, allowed: Bool?, busy: Bool?) {
            // Missing/invalid/stale IPC is absence of proof, NOT a lock fact.
            companionLocked = fresh && unlocked == false
            companionReady = fresh && allowed == true
            companionBusy = fresh && busy == true
        }
    }
    enum Decision: Equatable {
        case disabled, inactive, locked, hidden, companion, missingAsset, permission, busy, cooldown, listen
        var message: String {
            switch self {
            case .disabled: return "名字唤醒已关闭"
            case .inactive: return "请在 App 内开启并允许名字监听"
            case .locked: return "锁定时暂停名字监听"
            case .hidden: return "桌宠隐藏时暂停名字监听"
            case .companion: return "桌宠状态未就绪，名字监听已暂停"
            case .missingAsset: return "先导入并启用桌宠素材"
            case .permission: return "请主动开启并允许麦克风和语音权限"
            case .busy: return "桌宠忙碌、通话、录屏或其他语音占用时暂时退让"
            case .cooldown: return "刚刚回应，正在稍作等待"
            case .listen: return "正在本机等你喊名字，离开 App 后继续"
            }
        }
    }
    static func safetyDecision(_ c: Context) -> Decision? {
        if !c.enabled { return .disabled }
        if !c.armed { return .inactive }
        if !c.unlocked || (c.companionRequired && c.companionLocked) { return .locked }
        if !c.shown || !c.petStyle { return .hidden }
        if c.companionRequired && !c.companionReady {
            return c.companionBusy ? .busy : .companion
        }
        if !c.hasAsset { return .missingAsset }
        if !c.permissionGranted { return .permission }
        if !c.audioAvailable || c.recordingOrCall { return .busy }
        if !c.now.isFinite || !c.cooldownUntil.isFinite { return .cooldown }
        return nil
    }
    static func mayHoldCompanionTransition(_ c: Context, inputRunning: Bool,
                                          existingAsset: Bool, deadline: Double) -> Bool {
        // This never opens new audio or runs keyword recognition. Retain only
        // the already-authorized input for the old bounded three-second handoff.
        inputRunning && existingAsset && c.enabled && c.armed && c.unlocked &&
            !c.companionLocked && c.shown && c.petStyle && c.permissionGranted &&
            c.audioAvailable && !c.recordingOrCall && c.now.isFinite && deadline.isFinite &&
            c.now < deadline && deadline - c.now <= 3
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
