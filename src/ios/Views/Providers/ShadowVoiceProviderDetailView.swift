// >>>IOS15PORTED>>>
import SwiftUI

// MARK: - Shadow Voice Provider detail [T-mimo-shadow-voice]
//
// A read-only mirror of a Chat/OpenAI instance's voice capability, shown in
// Voice Services. It does NOT own credentials or a base URL — those come from
// the underlying instance (edit them in that instance's detail page). This view
// lists the instance's audio-modality models (ASR / TTS) and offers a per-user
// toggle to hide this shadow row from Voice Services.

struct ShadowVoiceProviderDetailView: View {
    let instanceId: String
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var quickTestEntry: ModelEntry?

    private var instance: ProviderInstance? { store.instance(for: instanceId) }
    private var shadow: ProviderConfigStore.ShadowVoiceProvider? {
        store.shadowVoiceProviders().first { $0.instanceId == instanceId }
    }

    var body: some View {
        List {
            Section {

            if let asr = shadow?.inputModels, !asr.isEmpty {
                Section(AppLocalized("Speech to Text", comment: "ASR section")) {
                    ForEach(asr) { entry in
                        modelRow(entry, systemImage: "waveform.and.mic", color: .purple)
                    }
                }
            }

            if let tts = shadow?.outputModels, !tts.isEmpty {
                Section(AppLocalized("Text to Speech", comment: "TTS section")) {
                    ForEach(tts) { entry in
                        modelRow(entry, systemImage: "speaker.wave.2.fill", color: .green)
                    }
                }
            }

            Section {
        }
        .navigationTitle(shadow?.displayName ?? instance?.label ?? AppLocalized("Voice Service"))
        .navigationBarTitleDisplayMode(.inline)
        .sheet(item: $quickTestEntry) { entry in
            // [T-quicktest-stale-session] Fresh identity per model — see
            // UnifiedModelPicker: swipe-dismiss could reuse the previous
            // sheet identity and its stale TestSession.
            ModelQuickTestSheet(entry: entry)
                .id(entry.id)
        }
    }

    private func styledIcon(_ systemName: String, color: Color) -> some View {
        Image(systemName: systemName)
            .font(.system(size: 9))
            .foregroundStyle(.white)
            .frame(width: 21, height: 21)
            .background(color, in: Circle())
    }

    private func modelRow(_ entry: ModelEntry, systemImage: String, color: Color) -> some View {
        Button {
    }
}
