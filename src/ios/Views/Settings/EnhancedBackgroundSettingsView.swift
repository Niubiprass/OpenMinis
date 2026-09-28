import AVFoundation
import SwiftUI

struct EnhancedBackgroundSettingsView: View {
    @ObservedObject private var keepAlive = BackgroundKeepAliveManager.shared
    @ObservedObject private var deepLink = DeepLinkCoordinator.shared
    // Owns the preview synthesizer and routes its audio-session intent through
    // AudioSessionCoordinator (a SwiftUI struct can't be an AVSpeechSynthesizer
    // delegate, so the lifecycle lives in this reference-type helper).
    // [T-audio-session-preview]
    @StateObject private var previewPlayer = SpeechPreviewPlayer()
    /// [T-settings-focus-highlight] Focus directives consumed once from the
    /// deep-link coordinator (parsing lives in DeepLinkCoordinator). Each row
    /// asks `DeepLinkCoordinator.shouldFocus(_:current:in:)` whether to show its
    /// yellow border; because it reads the live toggle value the border clears
    /// reactively once the row reaches the expected state.
    @State private var focus: [String: Bool?] = [:]

    private func shouldFocus(_ key: String, current: Bool) -> Bool {
        DeepLinkCoordinator.shouldFocus(key, current: current, in: focus)
    }

    var body: some View {
        List {
            Section {

            // [T-ipad16-liveactivity-restore-crash] Hidden on devices where
            // Live Activities don't exist (iPad < iPadOS 17, iOS-on-Mac,
            // failed runtime probe) — the switch would do nothing there, and
            // GH#82 showed this device class is exactly where ActivityKit
            // must never be touched.
            if AgentLiveActivityManager.isLiveActivitySupported {
                Section {
            }

            Section {

            // [T-ios-live-activity-privacy-mode] Sits right after the two
            // surfaces it governs (Live Activity above, Task Notifications
            // directly above), since it redacts both.
            Section {

            Section {

            // MARK: - Speech Settings

            Section {

            Section {
                Text("Choose a specific voice for each language. Download more voices in Settings > Accessibility > Spoken Content > Voices.")
            }

            Section {
                Button("Reset to Defaults") {
                    keepAlive.resetSpeechSettings()
                }

                Button("Preview") {
                    previewSpeech()
                }
            }

            // MARK: - Other Settings

            Section {

            Section {
                Text("How long the app can keep working after moving to the background. Without any keep-alive mechanism, iOS suspends apps after roughly 30 seconds; enabling Location Tracking (and granting location permission) or Background Speak extends this for the duration of a task.")
            }
        }
        .navigationTitle("Background")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            // [T-settings-focus-highlight] One-shot consume of the parsed focus
            // directives (parsing + decision live in DeepLinkCoordinator). Held
            // locally so a later plain navigation doesn't re-arm the borders.
            let consumed = deepLink.consumeFocus()
            if !consumed.isEmpty { focus = consumed }
            // [T-ios-scene-create-watchdog-corelocation] This screen shows the
            // location-permission row, and the status is no longer read in the
            // manager's init (that IPC is what tripped the scene-create
            // watchdog). Refresh it here so the row is accurate even if this
            // view is somehow reached before setup() ran, and so it reflects a
            // permission the user changed in Settings.app while we were away.
            keepAlive.refreshLocationAuthStatus()
        }
    }

    // MARK: - Voice Picker

    @ViewBuilder
    private func voicePicker(label: String, language: String, selection: Binding<String>) -> some View {
        let voices = AVSpeechSynthesisVoice.speechVoices()
            .filter { $0.language.hasPrefix(language) }
            .sorted { $0.name < $1.name }

        Picker(label, selection: selection) {
            Text("System Default").tag("")
            ForEach(voices, id: \.identifier) { voice in
                Text(voiceDisplayName(voice)).tag(voice.identifier)
            }
        }
    }

    private func voiceDisplayName(_ voice: AVSpeechSynthesisVoice) -> String {
        // Same verbatim-Text caveat as locationStatusText: this is interpolated
        // into a String, so localize here rather than relying on Text lookup.
        let quality: String
        switch voice.quality {
        case .enhanced: quality = AppLocalized("Enhanced", comment: "Speech voice quality")
        case .premium: quality = AppLocalized("Premium", comment: "Speech voice quality")
        default: quality = ""
        }
        let suffix = quality.isEmpty ? "" : " (\(quality))"
        return "\(voice.name)\(suffix)"
    }

    // MARK: - Preview

    private func previewSpeech() {
        let text = keepAlive.speechVoiceZh.isEmpty && keepAlive.speechVoiceEn.isEmpty
            ? "Hello, this is a speech preview."
            : {
                // If a Chinese voice is set but not English, preview in Chinese
                if !keepAlive.speechVoiceZh.isEmpty && keepAlive.speechVoiceEn.isEmpty {
                    return "你好，这是语音预览。"
                }
                return "Hello, this is a speech preview."
            }()
        let utterance = AVSpeechUtterance(string: text)
        let lang = text.range(of: "\\p{Han}", options: .regularExpression) != nil ? "zh-CN" : "en-US"
        utterance.voice = keepAlive.voiceForLanguage(lang)
        utterance.rate = keepAlive.speechRate
        utterance.pitchMultiplier = keepAlive.speechPitch
        utterance.volume = keepAlive.speechVolume
        // Audio-session intent is declared through AudioSessionCoordinator inside
        // the player (begin on speak, end on didFinish/didCancel), matching the
        // real read-replies path instead of poking AVAudioSession directly.
        previewPlayer.speak(utterance)
    }

    // MARK: - Location Status

    /// [T-keepalive-survival-tier] Label for the extended tier naming the
    /// enabled keep-alive legs.
    private func extendedTierLabel(location: Bool, audio: Bool) -> String {
        switch (location, audio) {
        case (true, true): return AppLocalized("Extended (Location + Audio)", comment: "Keep-alive tier")
        case (true, false): return AppLocalized("Extended (Location)", comment: "Keep-alive tier")
        default: return AppLocalized("Extended (Audio)", comment: "Keep-alive tier")
        }
    }

    /// Localized location-permission status. These are consumed as
    /// `Text(locationStatusText)` — a String variable, which selects SwiftUI's
    /// VERBATIM initializer and performs no catalog lookup. So the localization
    /// has to happen here via `String(localized:)`; returning bare literals kept
    /// this row English in every language.
    private var locationStatusText: String {
        switch keepAlive.locationAuthStatus {
        case .notDetermined: return AppLocalized("Not Requested", comment: "Location permission status")
        case .restricted: return AppLocalized("Restricted", comment: "Location permission status")
        case .denied: return AppLocalized("Denied", comment: "Location permission status")
        case .authorizedWhenInUse: return AppLocalized("When In Use", comment: "Location permission status")
        case .authorizedAlways: return AppLocalized("Always", comment: "Location permission status")
        @unknown default: return AppLocalized("Unknown", comment: "Location permission status")
        }
    }

    private var locationStatusColor: Color {
        switch keepAlive.locationAuthStatus {
        case .authorizedAlways: return .green
        case .authorizedWhenInUse: return .orange
        case .denied, .restricted: return .red
        default: return .secondary
        }
    }
}

// MARK: - Focus highlight

private extension View {
    /// [T-settings-focus-highlight] Draw a yellow rounded-rect border around a
    /// row recommended by a `?focus=…` deep-link. The border fades out once
    /// `focused` flips to false (i.e. the user interacted with the row).
    @ViewBuilder
    func focusHighlight(_ focused: Bool) -> some View {
        self
            .overlay(
                RoundedRectangle(cornerRadius: 10, style: .continuous)
                    .stroke(Color.yellow, lineWidth: 2)
                    // Expand the border outward so it isn't cramped against the
                    // row text — more breathing room above/below in particular.
                    .padding(.horizontal, -10)
                    .padding(.vertical, -12)
                    .opacity(focused ? 1 : 0)
                    .allowsHitTesting(false)
            )
            .animation(.easeInOut(duration: 0.3), value: focused)
    }
}

/// Owns the settings "speech preview" synthesizer and balances its
/// AudioSessionCoordinator `.replyTTS` intent. A SwiftUI `View` struct can't be
/// an `AVSpeechSynthesizerDelegate`, so the begin/end lifecycle lives here.
/// [T-audio-session-preview]
@MainActor
final class SpeechPreviewPlayer: NSObject, ObservableObject, AVSpeechSynthesizerDelegate {
    private let synthesizer = AVSpeechSynthesizer()
    /// Whether we currently hold a `.replyTTS` intent — guards against a double
    /// `end` (re-tap fires didCancel for the old utterance after we've already
    /// begun a fresh intent) and against `end` without a matching `begin`.
    private var holdingIntent = false

    override init() {
        super.init()
        synthesizer.delegate = self
    }

    func speak(_ utterance: AVSpeechUtterance) {
        // Stop any in-progress preview first. This fires didCancel synchronously
        // on some OS versions, which would `end` the intent we're about to hold;
        // releasing it here first keeps begin/end balanced regardless of ordering.
        if synthesizer.isSpeaking {
            synthesizer.stopSpeaking(at: .immediate)
        }
        releaseIntent()
        AudioSessionCoordinator.shared.begin(.replyTTS)
        holdingIntent = true
        synthesizer.speak(utterance)
    }

    private func releaseIntent() {
        guard holdingIntent else { return }
        holdingIntent = false
        AudioSessionCoordinator.shared.end(.replyTTS)
    }

    // AVSpeechSynthesizer delivers delegate callbacks on the main thread; hop to
    // the MainActor to touch the (@MainActor) coordinator + our state.
    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                                       didFinish utterance: AVSpeechUtterance) {
        MainActor.assumeIsolated { releaseIntent() }
    }

    nonisolated func speechSynthesizer(_ synthesizer: AVSpeechSynthesizer,
                                       didCancel utterance: AVSpeechUtterance) {
        MainActor.assumeIsolated { releaseIntent() }
    }
}
