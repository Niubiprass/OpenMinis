import Combine
import Foundation
import UIKit

/// Compatibility shell for the removed name-wake feature.
///
/// Legacy defaults are intentionally still readable by MiniSightConfigStore, but
/// this object has no audio session, microphone, timer, Darwin notification,
/// speech, model, or cross-process behavior. Ordinary ChatPanel voice input
/// continues to use MiniSightVoiceBridge directly.
@MainActor
final class MiniSightWakeController: NSObject, ObservableObject {
    static let shared = MiniSightWakeController()

    @Published private(set) var responseSequence = 0
    @Published private(set) var responseActive = false
    @Published private(set) var permissionPending = false
    @Published private(set) var status = "名字唤醒已停用；请点击语音按钮输入"
    private override init() { super.init() }

    var backgroundAudioIsLive: Bool { false }
    var isNameWakeDisabled: Bool { true }

    func install() {}
    func registerPetAnchor(_ view: UIView) {}
    func unregisterPetAnchor(_ view: UIView?) {}
    func setPetInteractionBusy(_ busy: Bool) {}
    func updatePresentation(foreground: Bool, shown: Bool, hasAsset: Bool, appLocked: Bool) {}
    func presentationDetached() {}
    func pollRemoteState() {}

    func requestEnabled(_ enabled: Bool) {
        UserDefaults.standard.set(false, forKey: MiniSightSettingKey.wakeEnabled)
        permissionPending = false
        responseActive = false
        status = "名字唤醒已停用；请点击语音按钮输入"
    }

    func retry() { requestEnabled(false) }
    func awaitsNameWakeReply(token: String) -> Bool { false }
    func claimNameWakeVoice(token: String, generation: Int) -> Bool { false }
    func nameWakeVoiceStarted(generation: Int) {}
    func nameWakeVoiceEnded(generation: Int) {}
    func cancelNameWake(generation: Int) {}
}
