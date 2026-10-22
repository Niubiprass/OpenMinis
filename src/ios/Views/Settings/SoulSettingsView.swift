import SwiftUI
import PhotosUI
import UIKit
import UniformTypeIdentifiers

/// Settings page for SOUL.md — Minis's persistent personality file.
/// Lives between Skills and Memory in the Agent Runtime section.
struct SoulSettingsView: View {
    @State private var name: String = SoulMetadata.default.name
    /// Raw emoji value loaded from SOUL.md. Not user-editable; preserved
    /// verbatim on save so we don't rewrite a value the user (or another
    /// device) may have set in the file. UI always shows `displayEmoji`.
    @State private var rawEmoji: String = SoulMetadata.default.emoji
    /// [T-soul-custom-icon] The user's identity icon: an emoji, a
    /// `data:image/png;base64,…` URI, or empty for the default sparkle.
    @State private var icon: String = SoulMetadata.default.icon
    @State private var showIconOptions = false
    @State private var showEmojiPrompt = false
    @State private var emojiDraft = ""
    /// [T-soul-icon-photo-ios15] Presenter for the icon photo picker.
    ///
    /// `.photosPicker` / `PhotosPickerItem` are iOS 16+, and this port floors at
    /// 15 — the port stripped the modifier but LEFT the bindings behind, so
    /// 「选择图片…」 set a flag that nothing ever read: tapping it did literally
    /// nothing (reported 2026-10-20). A retrained PHPickerViewController is the
    /// same picker iOS 15 can actually show, and it is the pattern the chat
    /// composer already uses.
    @StateObject private var iconPhotoPicker = SoulIconPhotoPicker()
    @State private var iconError: String? = nil
    @State private var style: String = SoulMetadata.default.style
    @State private var lang: String = SoulMetadata.default.lang
    @State private var bodyText: String = ""
    @State private var saveError: String? = nil
    @State private var didJustSave: Bool = false
    @State private var showRestoreConfirm: Bool = false
    @State private var showForceSyncDone: Bool = false
    @StateObject private var loadedRef = LoadedFileRef()
    /// Mirrors `SyncV2Bootstrap.isEnabled` so the Force iCloud Sync row
    /// shows / hides reactively when the user toggles iCloud sync in
    /// Settings. Same pattern as SkillDetailView (#440 / 3a4fe546).
    @AppStorage("cloudSync.v2.enabled") private var iCloudSyncEnabled: Bool = false
    @ObservedObject private var personaStore = PersonaStore.shared

    private static var langOptions: [(label: String, value: String)] {
        [
            (AppLocalized("Auto"), "auto"),
            (AppLocalized("Chinese"), "zh"),
            (AppLocalized("English"), "en"),
        ]
    }

    var body: some View {
        Form {
            Section {
                NavigationLink {
                    PersonaListView()
                } label: {
                    HStack {
                        Label(AppLocalized("人格列表"), systemImage: "person.2")
                        Spacer()
                        Text("\(personaStore.personas.count) 个")
                            .foregroundStyle(.secondary)
                    }
                }
                Toggle(AppLocalized("新建会话默认空白"), isOn: $personaStore.blankByDefault)
            } header: {
                Text(AppLocalized("人格"))
            } footer: {
                Text(AppLocalized("默认空白：新会话不注入人格；想用哪个人格，再在会话里选。关掉则继续用全局 SOUL.md。"))
            }

            Section {
                previewCard
            }

            Section(AppLocalized("Identity")) {
                LabeledContent(AppLocalized("Name")) {
                    TextField("Minis", text: $name)
                        .multilineTextAlignment(.trailing)
                        .textInputAutocapitalization(.words)
                        .submitLabel(.done)
                }
                LabeledContent(AppLocalized("Style")) {
                    TextField(AppLocalized("e.g. Warm, direct, opinionated"), text: $style)
                        .multilineTextAlignment(.trailing)
                }
                // [T-soul-language-sticks] Was a `Picker`. On this iOS 15 build
                // the selection did not stick: choosing 中文 left the row showing
                // 自动 (reported 2026-10-20 with a screen recording). A `Menu` with
                // explicit buttons is the same affordance — value on the right,
                // chevron, one tap — but the write path is a plain assignment, so
                // there is no Picker tag matching to get wrong on an older
                // SwiftUI. The label mirrors the current value, which is also how
                // the Picker looked.
                Menu {
                    ForEach(Self.langOptions, id: \.value) { opt in
                        Button {
                            lang = opt.value
                        } label: {
                            if lang == opt.value {
                                Label(opt.label, systemImage: "checkmark")
                            } else {
                                Text(opt.label)
                            }
                        }
                    }
                } label: {
                    HStack {
                        Text(AppLocalized("Language"))
                            .foregroundStyle(.primary)
                        Spacer()
                        Text(Self.langOptions.first { $0.value == lang }?.label ?? lang)
                            .foregroundStyle(.secondary)
                    }
                }
            }

            Section {
                personalityEditor
            } header: {
                Text(AppLocalized("Personality Prompt"))
            } footer: {
                bodyLengthFooter
            }

            Section {
                Button(role: .destructive) {
                    showRestoreConfirm = true
                } label: {
                    Label(AppLocalized("Restore Default"), systemImage: "arrow.uturn.backward")
                }

                // Force iCloud Sync — re-marks SOUL.md dirty and asks
                // SyncCore to send immediately. Same gating predicate
                // as SkillDetailView (47fd61ef / 3a4fe546): hidden
                // entirely when the user has iCloud sync off, since
                // the action would no-op on a disabled engine.
                if #available(iOS 17.0, *), iCloudSyncEnabled {
                    Button {
                        Task { await forceSyncSoul() }
                    } label: {
                        HStack {
                            Label(AppLocalized("Force iCloud Sync"), systemImage: "icloud.and.arrow.up")
                            Spacer()
                            if showForceSyncDone {
                                Text(AppLocalized("Queued"))
                                    .foregroundStyle(.green)
                                    .font(.caption)
                            }
                        }
                    }
                }
            }

            if let saveError {
                Section {
                    Text(saveError)
                        .font(.footnote)
                        .foregroundStyle(.red)
                }
            }
        }
        .navigationTitle(AppLocalized("Soul"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button(AppLocalized("Save")) { save() }
                    .disabled(!isDirty || isBodyOverLimit)
            }
        }
        // [T-soul-language-sticks] `reload()` used to run on EVERY appear. The
        // Language row pushes a child list on this iOS build, and coming back
        // from it re-appeared the page → reload from disk → the choice the user
        // had just made (not saved yet) was thrown away. Load once per view
        // lifetime; a later sync is what updates the page, not a re-appear.
        .onAppear { if !loadedRef.didLoad { reload() } }
        // Using .alert (not .confirmationDialog) so the dialog stays
        // centered on iPad / Mac. confirmationDialog without a source
        // rect renders as a popover anchored to the screen's top edge
        // on regular-width size classes.
        .alert(
            AppLocalized("Restore Default"),
            isPresented: $showRestoreConfirm
        ) {
            Button(AppLocalized("Restore Default"), role: .destructive, action: restoreDefault)
            Button(AppLocalized("Cancel"), role: .cancel) {}
        } message: {
            Text(AppLocalized("Restore default SOUL.md? Your current personality will be replaced."))
        }
        .modifier(SoulIconEditing(
            icon: $icon,
            showEmojiPrompt: $showEmojiPrompt,
            emojiDraft: $emojiDraft,
            iconError: $iconError
        ))
        .overlay(alignment: .bottom) {
            if didJustSave {
                Text(AppLocalized("Saved"))
                    .font(.footnote.weight(.medium))
                    .padding(.horizontal, 14).padding(.vertical, 8)
                    .background(Color.green.opacity(0.85), in: Capsule())
                    .foregroundStyle(.white)
                    .padding(.bottom, 24)
                    .transition(.opacity)
            }
        }
    }

    // MARK: - Subviews

    // Standard Form row — the insetGrouped section provides the rounded
    // card chrome automatically, so we only render content here. Matches
    // the visual width of every other section on the page.
    private var previewCard: some View {
        HStack(alignment: .center, spacing: 12) {
            // [T-soul-custom-icon] Tappable, and it has to LOOK tappable: a
            // bare glyph sitting on the card reads as decoration, and the
            // pencil badge alone was too easy to miss. A filled circle gives
            // the icon a defined edge and a hit area the eye can find, which
            // is the same treatment the category badges elsewhere in Settings
            // use. It doubles as a backdrop for transparent PNG icons, whose
            // whole point is having no background of their own.
            Button {
                showIconOptions = true
            } label: {
                // Inset inside the 52pt button so the grey disc stays visible
                // as a ring even when the icon is an image, which otherwise
                // fills the whole frame and hides the affordance entirely.
                SoulIconView(icon: icon, size: SoulIconImage.renderPoints)
                    .frame(width: 44, height: 44)
                    .frame(width: 52, height: 52)
                    .background(Circle().fill(Color.secondary.opacity(0.12)))
                    .overlay(
                        Circle().strokeBorder(Color.secondary.opacity(0.18), lineWidth: 0.5)
                    )
                    // The badge sits INSIDE the circle's bounds rather than
                    // straddling its edge. Overhanging it (even with padding)
                    // gets clipped to a sliver by the enclosing Button label,
                    // which is what made the pencil hard to see.
                    //
                    // Drawn as an explicit filled Circle + pencil glyph rather
                    // than `pencil.circle.fill` with .palette: that symbol's
                    // "circle" layer is the BACKGROUND, so on the white card it
                    // rendered as an invisible disc with a bare diagonal stroke
                    // floating over it. Compositing it ourselves also lets the
                    // badge keep a contrasting ring against a dark icon image.
                    .overlay(alignment: .bottomTrailing) {
                        Image(systemName: "pencil")
                            .font(.system(size: 9, weight: .semibold))
                            .foregroundStyle(Color.white)
                            .frame(width: 18, height: 18)
                            .background(Circle().fill(Color.accentColor))
                            .overlay(Circle().strokeBorder(Color(.systemBackground), lineWidth: 1.5))
                            .offset(x: 1, y: 1)
                    }
            }
            .buttonStyle(.plain)
            .accessibilityLabel(AppLocalized("Change icon"))
            // [T-soul-custom-icon] Attached to the BUTTON, not to the whole
            // page. A confirmationDialog anchors its popover to the view it
            // is attached to, so hanging it off the Form (as this first did)
            // pointed the arrow at the middle of the page — visibly at the
            // Style row — instead of at the icon the user tapped. Only the
            // dialog needs the anchor; the alerts and the photo picker are
            // centered/full-screen and stay at page level.
            .confirmationDialog(AppLocalized("Change icon"), isPresented: $showIconOptions) {
                Button(AppLocalized("Choose Emoji…")) {
                    emojiDraft = (icon.isEmpty || SoulIconImage.isDataURI(icon)) ? "" : icon
                    showEmojiPrompt = true
                }
                Button(AppLocalized("Choose Image…")) { presentIconPhotoPicker() }
                if !icon.isEmpty {
                    Button(AppLocalized("Use Default"), role: .destructive) { icon = "" }
                }
                Button(AppLocalized("Cancel"), role: .cancel) {}
            } message: {
                // [T-soul-icon-opaque-rounded] Any image works. This used to
                // demand a transparent PNG, which stopped being true when the
                // alpha-channel rejection was dropped (fe2f3ae8b) — the icon is
                // drawn with rounded corners, so an opaque photo reads as a
                // normal avatar. `SoulIconImage.RejectionReason` now has one
                // case, `unreadable`, and nothing checks for transparency.
                Text(AppLocalized("Any image works. It's cropped to a square and shown with rounded corners."))
            }
            VStack(alignment: .leading, spacing: 2) {
                Text(name.isEmpty ? "Minis" : name)
                    .font(.title3.weight(.semibold))
                if !style.trimmingCharacters(in: .whitespaces).isEmpty {
                    Text(style)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            Spacer(minLength: 0)
        }
        .padding(.vertical, 4)
    }

    private var personalityEditor: some View {
        ZStack(alignment: .topLeading) {
            TextEditor(text: $bodyText)
                .frame(minHeight: 220)
                .font(.system(.body, design: .monospaced))
            // SwiftUI's TextEditor has no native placeholder. We render
            // a greyed hint on top when the body is empty + not being
            // typed into. allowsHitTesting(false) so taps fall through
            // to the editor below.
            if bodyText.isEmpty {
                Text(AppLocalized("Describe the personality and voice you want for your agent"))
                    .font(.system(.body, design: .monospaced))
                    .foregroundStyle(.tertiary)
                    .padding(.top, 8)
                    .padding(.leading, 5)
                    .allowsHitTesting(false)
            }
        }
    }

    /// Footer under the personality editor. Renders a green count when the
    /// body is within budget and a red over-limit message when it isn't.
    /// Save is disabled in the over-limit branch.
    private var bodyLengthFooter: some View {
        let check = SoulStore.isOverLimit(bodyText)
        return HStack(spacing: 6) {
            if check.isOverLimit {
                Image(systemName: "exclamationmark.triangle.fill")
                    .foregroundStyle(.red)
            }
            switch check {
            case .ok:
                Text(soulBodyCountText(bodyText))
                    .foregroundStyle(.secondary)
            case .overLimit(let count, let cap):
                Text(AppLocalized("Over limit: \(count) / \(cap) tokens. Each CJK character and each Latin word counts as one."))
                    .foregroundStyle(.red)
            }
        }
        .font(.footnote)
    }

    /// Counter shown when the body is within budget.
    private func soulBodyCountText(_ body: String) -> String {
        let count = SoulStore.tokenCount(body)
        return AppLocalized("\(count) / \(SoulStore.bodyTokenLimit) tokens")
    }

    private var isBodyOverLimit: Bool {
        SoulStore.isOverLimit(bodyText).isOverLimit
    }

    // MARK: - Persistence

    private var currentFile: SoulFile {
        SoulFile(
            metadata: SoulMetadata(
                name: name.trimmingCharacters(in: .whitespacesAndNewlines),
                // Round-trip the on-disk emoji untouched — UI no longer
                // edits this field, but a SOUL.md authored elsewhere
                // (other device / hand-edit) should not have its emoji
                // rewritten on save.
                emoji: rawEmoji,
                style: style,
                lang: lang,
                icon: icon
            ),
            body: bodyText
        )
    }

    private var isDirty: Bool {
        currentFile != loadedRef.value
    }

    /// Validate and normalize a picked photo into the stored form.
    ///
    /// [T-soul-icon-opaque-rounded] Opaque images are accepted: transparency was
    /// a presentation concern and moved to `SoulIconView`, which clips every
    /// image to a rounded rectangle. Only an undecodable image is refused here,
    /// so this path and the `minis-config` path apply exactly the same rule.
    private func applyPickedImage(_ image: UIImage) {
        switch SoulIconImage.encode(image) {
        case .success(let uri):
            icon = uri
        case .failure:
            iconError = AppLocalized("That image couldn't be read.")
        }
    }

    /// Open the system image picker for the identity icon.
    ///
    /// PHPicker (not UIImagePickerController): it needs no photo-library usage
    /// description and runs out of process, so a pick cannot hand the app a
    /// library-scale memory spike. `UIKitPickerPresenter` is the same presenter
    /// the chat composer uses — it waits for the menu/dialog to finish
    /// dismissing before presenting, otherwise iOS drops the presentation.
    private func presentIconPhotoPicker() {
        var config = PHPickerConfiguration(photoLibrary: .shared())
        config.filter = .images
        config.selectionLimit = 1
        config.preferredAssetRepresentationMode = .current
        let picker = PHPickerViewController(configuration: config)
        iconPhotoPicker.onPicked = { image in
            applyPickedImage(image)
        }
        picker.delegate = iconPhotoPicker
        UIKitPickerPresenter.present(picker)
    }

    private func reload() {
        let file = SoulStore.load() ?? SoulFile(metadata: .default, body: "")
        name = file.metadata.name
        rawEmoji = file.metadata.emoji
        icon = file.metadata.icon
        style = file.metadata.style
        lang = file.metadata.lang
        bodyText = file.body
        loadedRef.value = file
        loadedRef.didLoad = true
        saveError = nil
    }

    private func save() {
        do {
            let f = currentFile
            try SoulStore.save(f)
            loadedRef.value = f
            saveError = nil
            withAnimation { didJustSave = true }
            DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                withAnimation { didJustSave = false }
            }
        } catch {
            saveError = "Save failed: \(error.localizedDescription)"
        }
    }

    /// Bidirectional Soul sync: push local SOUL.md up and pull the
    /// latest remote SoulV2 down. Mirrors `ProviderInstancesView`'s
    /// Force iCloud Sync entry (which uses the same `bidirectionalSync`
    /// helper). iOS-17 gated because the v2 sync surface is.
    @available(iOS 17.0, *)
    @MainActor
    private func forceSyncSoul() async {
        // 1. Re-mark local SOUL.md dirty (if present) so the upload
        //    side ships our copy.
        _ = await ForceSyncHelper.markSoulDirty()
        // 2. Run a full sendNow + fullFetchAndReconcile cycle so any
        //    peer-newer SoulV2 lands and the merger overwrites local
        //    via SoulStore.applyRemoteContent (LWW by mtime).
        await ForceSyncHelper.bidirectionalSync(recordTypes: ["SoulV2"])
        // 3. Re-read the on-disk file in case the merger just replaced
        //    it with a peer's newer copy — otherwise the form stays
        //    showing the pre-sync values.
        reload()
        showForceSyncDone = true
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { showForceSyncDone = false }
    }

    private func restoreDefault() {
        let parsed = SoulMDParser.parse(SoulStore.defaultContent)
        name = parsed.metadata.name
        rawEmoji = parsed.metadata.emoji
        style = parsed.metadata.style
        lang = parsed.metadata.lang
        bodyText = parsed.body
        save()
    }

    private final class LoadedFileRef: ObservableObject {
        var value: SoulFile = SoulFile(metadata: .default, body: "")
        /// True once the on-disk file has been read into the form. Guards the
        /// one-time load so a re-appear cannot wipe unsaved edits.
        var didLoad = false
    }
}

private extension Character {
    /// True for characters that are genuinely emoji.
    ///
    /// `isEmoji` alone is not enough: Unicode gives ASCII digits and `#`/`*`
    /// the Emoji property (they are the bases of keycap sequences like 1️⃣), so
    /// a bare "1" would pass. The rule below accepts a scalar only when it
    /// either defaults to emoji presentation, or is part of a multi-scalar
    /// cluster (a keycap, flag or ZWJ sequence), which is what excludes plain
    /// digits and letters while keeping 1️⃣ and 🇯🇵.
    var isEmojiGlyph: Bool {
        guard let first = unicodeScalars.first else { return false }
        if unicodeScalars.count > 1 {
            return unicodeScalars.contains { $0.properties.isEmoji }
        }
        return first.properties.isEmojiPresentation
    }
}

/// [T-soul-custom-icon] Emoji picker for the Soul identity icon: two rows of
/// suggestions plus a free-form field.
///
/// The suggestions are all **Unicode 6.0 (2010)** characters — the original
/// emoji block that every platform has shipped for over a decade. That matters
/// because this value syncs: an icon set on iOS is read by the Android build
/// and rendered with the system font there. Newer additions (🫡 U+1FAE1, 2021;
/// 🩻 2022) render as a blank box on anything that has not updated its font,
/// which would look like data loss rather than a style choice. Skin-toned and
/// ZWJ-sequence emoji are avoided for the same reason.
///
/// Chosen for "an agent's face": expressive enough to read as a persona at
/// 18pt in the chat header, and visually distinct from each other at that size.
private struct SoulEmojiPickerSheet: View {
    @Binding var draft: String
    let onPick: (String) -> Void
    @Environment(\.dismiss) private var dismiss

    private static let suggestions: [[String]] = [
        ["✨", "🤖", "🐱", "🦊", "🐧", "🦉", "🌟", "⚡"],
        ["🧠", "💡", "🔮", "🚀", "🌊", "🍀", "🎯", "🐳"],
    ]

    var body: some View {
        NavigationStack {
            VStack(spacing: 20) {
                // Live preview at the size the chat header actually uses, so
                // the user judges the glyph at its real scale rather than at
                // whatever the field happens to render.
                // Same circular treatment as the settings card, so the preview
                // shows what the icon will actually look like in place.
                SoulIconView(icon: draft, size: SoulIconImage.renderPoints)
                    .frame(width: 52, height: 52)
                    .background(Circle().fill(Color.secondary.opacity(0.12)))
                    .padding(.top, 8)

                ForEach(Array(Self.suggestions.enumerated()), id: \.offset) { _, row in
                    HStack(spacing: 10) {
                        ForEach(row, id: \.self) { emoji in
                            Button {
                                // Tap fills the field AND becomes the value —
                                // "点击和自动填入".
                                draft = emoji
                            } label: {
                                Text(emoji)
                                    .font(.system(size: 28))
                                    .frame(width: 38, height: 38)
                                    .background(
                                        Circle().fill(draft == emoji
                                                      ? Color.accentColor.opacity(0.22)
                                                      : Color.secondary.opacity(0.10))
                                    )
                            }
                            .buttonStyle(.plain)
                        }
                    }
                }

                TextField("✨", text: $draft)
                    .font(.system(size: 28))
                    .multilineTextAlignment(.center)
                    .frame(height: 52)
                    .background(Color.secondary.opacity(0.10), in: RoundedRectangle(cornerRadius: 10))
                    // Every keystroke is normalized to a single emoji: typing
                    // a second one REPLACES the first, and non-emoji input is
                    // dropped outright rather than rejected later with an
                    // error the user has to read.
                    .onChange(of: draft) { newValue in
                        let cleaned = Self.normalize(newValue, previous: draft)
                        if cleaned != newValue { draft = cleaned }
                    }

                Text(AppLocalized("Tap a suggestion or type one emoji. These render the same on iOS and Android."))
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)

                Spacer(minLength: 0)
            }
            .padding(.horizontal, 20)
            .navigationTitle(AppLocalized("Choose Emoji"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(AppLocalized("Cancel")) { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(AppLocalized("Set")) {
                        onPick(draft)
                        dismiss()
                    }
                    .disabled(draft.isEmpty)
                }
            }
        }
    }

    /// Keep at most one emoji, preferring whatever the user just added.
    ///
    /// Works on `Character` (grapheme clusters) so a flag or ZWJ sequence —
    /// several scalars rendering as one glyph — survives as a single unit
    /// instead of being sliced apart.
    static func normalize(_ input: String, previous: String) -> String {
        let emoji = input.filter(\.isEmojiGlyph)
        guard let last = emoji.last else { return "" }
        // Taking the LAST emoji is what makes a second keystroke replace the
        // first rather than being ignored.
        return String(last)
    }
}

/// One-shot PHPicker delegate for the Soul icon.
///
/// Lives in a `@StateObject` on the page rather than a struct-local variable:
/// `PHPickerViewController.delegate` is weak, so a temporary would be gone by
/// the time the user finishes picking and the callback would never arrive.
private final class SoulIconPhotoPicker: NSObject, ObservableObject, PHPickerViewControllerDelegate {
    var onPicked: ((UIImage) -> Void)?

    func picker(_ picker: PHPickerViewController, didFinishPicking results: [PHPickerResult]) {
        picker.dismiss(animated: true)
        guard let provider = results.first?.itemProvider,
              provider.canLoadObject(ofClass: UIImage.self) else { return }
        provider.loadObject(ofClass: UIImage.self) { [weak self] object, _ in
            guard let image = object as? UIImage else { return }
            // The picker calls back on a background queue; the icon is view
            // state, so it must be written on the main actor.
            DispatchQueue.main.async { self?.onPicked?(image) }
        }
    }
}

/// [T-soul-custom-icon] The icon picker's presentation chain, lifted out of
/// `SoulSettingsView.body`.
///
/// Not a style choice: inlining these four presentation modifiers pushed the
/// `body` expression past what the type-checker will solve ("unable to
/// type-check this expression in reasonable time"). A ViewModifier gives the
/// solver a fresh, small expression to work on.
private struct SoulIconEditing: ViewModifier {
    @Binding var icon: String
    @Binding var showEmojiPrompt: Bool
    @Binding var emojiDraft: String
    @Binding var iconError: String?

    func body(content: Content) -> some View {
        content
            // A sheet, not an alert: an alert body only takes text fields and
            // buttons, so the suggestion grid could not live in one.
            .sheet(isPresented: $showEmojiPrompt) {
                SoulEmojiPickerSheet(draft: $emojiDraft) { chosen in
                    icon = chosen
                }
            }
            .alert(AppLocalized("Can't use that image"),
                   isPresented: Binding(get: { iconError != nil },
                                        set: { if !$0 { iconError = nil } })) {
                Button(AppLocalized("OK"), role: .cancel) { iconError = nil }
            } message: {
                Text(iconError ?? "")
            }
    }

    /// Accept exactly one emoji.
    ///
    /// Counting `Character`s (grapheme clusters), not scalars, so a flag or a
    /// skin-toned/ZWJ emoji — several scalars rendering as one glyph — counts
    /// as one. Empty input clears back to the default rather than storing a
    /// blank.
    private func applyEmojiDraft() {
        let trimmed = emojiDraft.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { icon = ""; return }
        guard trimmed.count == 1 else {
            iconError = AppLocalized("Please enter exactly one emoji.")
            return
        }
        icon = trimmed
    }


}
// MARK: - [T-persona-library] Persona list / editor

private struct PersonaListView: View {
    @ObservedObject private var store = PersonaStore.shared
    @State private var editing: AgentPersona?
    @State private var creating = false
    @State private var share: MemoryShareItem?

    var body: some View {
        List {
            if store.personas.isEmpty {
                Section {
                    Button {
                        creating = true
                    } label: {
                        Label(AppLocalized("新建人格"), systemImage: "plus.circle.fill")
                    }
                } footer: {
                    Text(AppLocalized("还没有人格；点这里新建，或点右上角 +。"))
                }
            } else {
                ForEach(store.personas) { persona in
                    Button {
                        editing = persona
                    } label: {
                        HStack(spacing: 10) {
                            Text(persona.icon.isEmpty ? "🙂" : persona.icon)
                                .font(.system(size: 22))
                                .frame(width: 34, height: 34)
                                .background(Color.secondary.opacity(0.12), in: Circle())
                            VStack(alignment: .leading, spacing: 2) {
                                Text(persona.name)
                                let subtitle = persona.style.isEmpty
                                    ? AppLocalized("未设置风格") : persona.style
                                Text(subtitle)
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                            Spacer()
                            Image(systemName: "chevron.right")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.tertiary)
                        }
                    }
                    .buttonStyle(.plain)
                }
                .onDelete { offsets in
                    let ids = offsets.map { store.personas[$0].id }
                    for id in ids { store.delete(id: id) }
                }
            }
        }
        .navigationTitle(AppLocalized("人格"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .navigationBarTrailing) {
                Button {
                    exportPersonas()
                } label: {
                    Image(systemName: "square.and.arrow.up")
                }
                .disabled(store.personas.isEmpty)
                Button {
                    creating = true
                } label: {
                    Image(systemName: "plus")
                }
            }
        }
        .sheet(item: $share) { MinisShareSheet(url: $0.url) }
        .sheet(isPresented: $creating) {
            PersonaEditorView(persona: nil)
        }
        .sheet(item: $editing) { persona in
            PersonaEditorView(persona: persona)
        }
    }

    private func exportPersonas() {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
        guard let data = try? encoder.encode(store.personas) else { return }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("personas-\(UUID().uuidString).json")
        do {
            try data.write(to: url, options: .atomic)
            share = MemoryShareItem(url: url)
        } catch {
            // Export is best-effort; the list stays usable.
        }
    }
}

private struct PersonaEditorView: View {
    let persona: AgentPersona?

    @ObservedObject private var store = PersonaStore.shared
    @Environment(\.dismiss) private var dismiss
    @State private var name = ""
    @State private var style = ""
    @State private var lang = "auto"
    @State private var bodyText = ""
    @State private var loaded = false

    private var isOverLimit: Bool {
        SoulStore.isOverLimit(bodyText).isOverLimit
    }

    private var langLabel: String {
        switch lang {
        case "zh": return AppLocalized("Chinese")
        case "en": return AppLocalized("English")
        default: return AppLocalized("Auto")
        }
    }

    var body: some View {
        NavigationView {
            Form {
                Section(AppLocalized("标识")) {
                    TextField(AppLocalized("名称"), text: $name)
                    TextField(AppLocalized("风格"), text: $style)
                    Menu {
                        Button(AppLocalized("Auto")) { lang = "auto" }
                        Button(AppLocalized("Chinese")) { lang = "zh" }
                        Button(AppLocalized("English")) { lang = "en" }
                    } label: {
                        HStack {
                            Text(AppLocalized("语言"))
                            Spacer()
                            Text(langLabel).foregroundStyle(.secondary)
                        }
                    }
                }

                Section {
                    TextEditor(text: $bodyText)
                        .frame(minHeight: 180)
                } header: {
                    Text(AppLocalized("人格提示词"))
                } footer: {
                    if isOverLimit {
                        Text(AppLocalized("提示词超过 2000 tokens，请缩短。"))
                            .foregroundStyle(.red)
                    } else {
                        Text(AppLocalized("只写说话方式、立场和语气；不要写“你是某某”的身份句。"))
                    }
                }
            }
            .navigationTitle(persona == nil
                             ? AppLocalized("新建人格")
                             : AppLocalized("编辑人格"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppLocalized("取消")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(AppLocalized("保存")) { save() }
                        .disabled(name.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || isOverLimit)
                }
            }
            .onAppear {
                guard !loaded else { return }
                loaded = true
                if let persona {
                    name = persona.name
                    style = persona.style
                    lang = persona.lang
                    bodyText = persona.body
                }
            }
        }
        .navigationViewStyle(.stack)
    }

    private func save() {
        let trimmed = name.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmed.isEmpty else { return }
        if var value = persona {
            value.name = trimmed
            value.style = style
            value.lang = lang
            value.body = bodyText
            store.update(value)
        } else {
            var value = store.add(name: trimmed)
            value.style = style
            value.lang = lang
            value.body = bodyText
            store.update(value)
        }
        dismiss()
    }
}
// MARK: - [T-persona-memory-share] Shared memory inbox

struct SharedMemoryListView: View {
    @ObservedObject private var store = SharedMemoryStore.shared
    @ObservedObject private var personaStore = PersonaStore.shared
    @State private var showCompose = false
    @State private var share: MemoryShareItem?
    @State private var showJSONPicker = false
    @State private var pendingImport: Data?
    @State private var showTargetPicker = false

    var body: some View {
        List {
            if store.records.isEmpty {
                Text(AppLocalized("还没有共享记忆。在人格记忆里点分享，选另一个人格。"))
                    .foregroundStyle(.secondary)
            } else {
                ForEach(store.records) { record in
                    NavigationLink {
                        SharedMemoryDetailView(record: record)
                    } label: {
                        VStack(alignment: .leading, spacing: 3) {
                            Text(record.title)
                            Text(AppLocalizedFormat("来自 %@ · 给 %@ · 只读",
                                                     record.sourcePersonaName,
                                                     record.targetPersonaName))
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                }
                .onDelete { offsets in
                    let ids = offsets.map { store.records[$0].id }
                    for id in ids { store.delete(id: id) }
                }
            }
        }
        .navigationTitle(AppLocalized("共享给我"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItemGroup(placement: .primaryAction) {
                Button {
                    showCompose = true
                } label: {
                    Image(systemName: "plus")
                }
                .accessibilityLabel("粘贴或导入共享记忆")

                Menu {
                    Button {
                        if let url = store.exportArchive() {
                            share = MemoryShareItem(url: url)
                        } else {
                            ShareFeedbackToast.show("没有可导出的共享记忆")
                        }
                    } label: {
                        Label(AppLocalized("导出共享记录 JSON"), systemImage: "square.and.arrow.up")
                    }
                    Button {
                        if personaStore.personas.isEmpty {
                            ShareFeedbackToast.show("先新建一个人格，才能导入")
                        } else {
                            showJSONPicker = true
                        }
                    } label: {
                        Label(AppLocalized("导入共享记录 JSON"), systemImage: "square.and.arrow.down")
                    }
                } label: {
                    Image(systemName: "ellipsis.circle")
                }
            }
        }
        .sheet(isPresented: $showCompose) {
            SharedMemoryComposeSheet()
        }
        .sheet(item: $share) { MinisShareSheet(url: $0.url) }
        .fileImporter(isPresented: $showJSONPicker,
                      allowedContentTypes: [.json],
                      allowsMultipleSelection: false) { result in
            switch result {
            case .success(let urls):
                guard let url = urls.first else { return }
                let scoped = url.startAccessingSecurityScopedResource()
                defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                do {
                    pendingImport = try Data(contentsOf: url)
                    showTargetPicker = true
                } catch {
                    ShareFeedbackToast.show(error.localizedDescription)
                }
            case .failure(let error):
                ShareFeedbackToast.show(error.localizedDescription)
            }
        }
        .confirmationDialog(AppLocalized("导入给哪个人格？"),
                            isPresented: $showTargetPicker,
                            titleVisibility: .visible) {
            ForEach(personaStore.personas) { persona in
                Button(persona.name) {
                    guard let data = pendingImport else { return }
                    let count = store.importArchive(data, target: persona)
                    pendingImport = nil
                    ShareFeedbackToast.show(count > 0
                                            ? AppLocalizedFormat("已导入 %lld 条", Int64(count))
                                            : AppLocalized("没有可导入的记录"))
                }
            }
            Button(AppLocalized("取消"), role: .cancel) { pendingImport = nil }
        } message: {
            Text(AppLocalized("记录会复制到选中的本地人格；不会覆盖已有记录。"))
        }
    }
}

/// External entry for the local shared-memory inbox. There is no network
/// service behind 「共享给我」; this sheet is where text pasted from another
/// app, or a Markdown file, becomes a read-only record for a chosen persona.
struct SharedMemoryComposeSheet: View {
    @ObservedObject private var store = SharedMemoryStore.shared
    @ObservedObject private var personaStore = PersonaStore.shared
    @Environment(\.dismiss) private var dismiss
    @State private var title = ""
    @State private var sourceName = "外部导入"
    @State private var content = ""
    @State private var targetId = ""
    @State private var showFilePicker = false
    @State private var error: String?

    private var target: AgentPersona? {
        personaStore.personas.first { $0.id == targetId }
    }

    private var canSave: Bool {
        target != nil
            && !content.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    var body: some View {
        NavigationView {
            Form {
                Section {
                    TextField(AppLocalized("标题"), text: $title)
                    TextField(AppLocalized("来源名称"), text: $sourceName)
                    if personaStore.personas.isEmpty {
                        Text(AppLocalized("还没有人格；先到人格页新建一个。"))
                            .foregroundStyle(.secondary)
                    } else {
                        Picker(AppLocalized("给哪个人格"), selection: $targetId) {
                            ForEach(personaStore.personas) { persona in
                                Text(persona.name).tag(persona.id)
                            }
                        }
                    }
                } footer: {
                    Text(AppLocalized("「共享给我」是本地收件箱，不会联网；粘贴或导入后，只有目标人格能复制到自己的记忆。"))
                }

                Section {
                    TextEditor(text: $content)
                        .frame(minHeight: 180)
                    Button {
                        showFilePicker = true
                    } label: {
                        Label(AppLocalized("从文件导入 Markdown"), systemImage: "doc.badge.plus")
                    }
                } header: {
                    Text(AppLocalized("内容"))
                } footer: {
                    if let error {
                        Text(error).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle(AppLocalized("导入共享记忆"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppLocalized("取消")) { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(AppLocalized("保存")) { save() }
                        .disabled(!canSave)
                }
            }
            .onAppear {
                if targetId.isEmpty { targetId = personaStore.personas.first?.id ?? "" }
            }
            .fileImporter(isPresented: $showFilePicker,
                          allowedContentTypes: [.plainText, .data],
                          allowsMultipleSelection: false) { result in
                switch result {
                case .success(let urls):
                    guard let url = urls.first else { return }
                    let scoped = url.startAccessingSecurityScopedResource()
                    defer { if scoped { url.stopAccessingSecurityScopedResource() } }
                    do {
                        let text = try String(contentsOf: url, encoding: .utf8)
                        content = text
                        if title.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
                            title = url.deletingPathExtension().lastPathComponent
                        }
                        error = nil
                    } catch {
                        self.error = error.localizedDescription
                    }
                case .failure(let error):
                    self.error = error.localizedDescription
                }
            }
        }
        .navigationViewStyle(.stack)
    }

    private func save() {
        guard let target else { return }
        let trimmedTitle = title.trimmingCharacters(in: .whitespacesAndNewlines)
        let trimmedContent = content.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedTitle.isEmpty, !trimmedContent.isEmpty else { return }
        let source = AgentPersona(name: sourceName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                                  ? AppLocalized("外部导入") : sourceName)
        store.share(source: source, target: target, title: trimmedTitle, content: trimmedContent)
        ShareFeedbackToast.show(AppLocalizedFormat("已导入给 %@", target.name))
        dismiss()
    }
}

struct SharedMemoryDetailView: View {
    let record: SharedMemoryRecord
    @ObservedObject private var store = SharedMemoryStore.shared
    @State private var share: MemoryShareItem?
    @State private var message: String?

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 10) {
                Label(AppLocalizedFormat("只读 · 来自 %@", record.sourcePersonaName),
                      systemImage: "lock")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(record.title).font(.headline)
                Text(record.content)
                    .font(.system(.caption, design: .monospaced))
                    .textSelection(.enabled)
                Button {
                    if store.copyToTarget(record) {
                        message = AppLocalized("已复制到你的人格记忆")
                    } else {
                        message = AppLocalized("复制失败，人格可能已被删除")
                    }
                } label: {
                    Label(AppLocalizedFormat("复制到我的记忆（%@）", record.targetPersonaName),
                          systemImage: "doc.on.doc")
                }
                .buttonStyle(.borderedProminent)
                if let message {
                    Text(message).font(.caption).foregroundStyle(.secondary)
                }
                Text(AppLocalized("共享内容是只读快照；复制后才会进入你自己的人格记忆，之后可以编辑。"))
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding()
        }
        .navigationTitle(AppLocalized("共享记忆"))
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .primaryAction) {
                Button {
                    // PDF, not Markdown: a shared snapshot should not look
                    // like an editable memory file. The recipient can still
                    // copy text into their own memory explicitly.
                    if let url = SharedMemoryPDFExporter.export(record) {
                        share = MemoryShareItem(url: url)
                    }
                } label: {
                    Image(systemName: "square.and.arrow.up")
                }
            }
        }
        .sheet(item: $share) { MinisShareSheet(url: $0.url) }
    }
}

/// [T-shared-memory-readonly] Renders a shared persona-memory snapshot as a
/// paginated PDF. The source Markdown is still available to the sender, but
/// the shared artifact is a document rather than an editable `.md`.
enum SharedMemoryPDFExporter {
    static func export(_ record: SharedMemoryRecord) -> URL? {
        let page = CGRect(x: 0, y: 0, width: 612, height: 792)
        let renderer = UIGraphicsPDFRenderer(bounds: page)
        let data = renderer.pdfData { context in
            let margin: CGFloat = 40
            let width = page.width - margin * 2
            var y: CGFloat = margin

            func beginPage() {
                context.beginPage()
                y = margin
            }

            beginPage()
            let titleAttrs: [NSAttributedString.Key: Any] = [
                .font: UIFont.boldSystemFont(ofSize: 18),
                .foregroundColor: UIColor.label
            ]
            let metaAttrs: [NSAttributedString.Key: Any] = [
                .font: UIFont.systemFont(ofSize: 10),
                .foregroundColor: UIColor.secondaryLabel
            ]
            let bodyAttrs: [NSAttributedString.Key: Any] = [
                .font: UIFont.systemFont(ofSize: 11),
                .foregroundColor: UIColor.label
            ]

            (record.title as NSString).draw(
                with: CGRect(x: margin, y: y, width: width, height: 26),
                options: [.usesLineFragmentOrigin, .usesFontLeading],
                attributes: titleAttrs, context: nil)
            y += 28
            let meta = "只读快照 · 来自 \(record.sourcePersonaName) · 给 \(record.targetPersonaName) · \(dateText(record.sharedAt))"
            (meta as NSString).draw(
                with: CGRect(x: margin, y: y, width: width, height: 16),
                options: [.usesLineFragmentOrigin, .usesFontLeading],
                attributes: metaAttrs, context: nil)
            y += 24

            for rawLine in record.content.components(separatedBy: .newlines) {
                let line = rawLine.isEmpty ? " " : rawLine
                let bounding = (line as NSString).boundingRect(
                    with: CGSize(width: width, height: .greatestFiniteMagnitude),
                    options: [.usesLineFragmentOrigin, .usesFontLeading],
                    attributes: bodyAttrs, context: nil)
                if y + bounding.height > page.height - margin {
                    beginPage()
                }
                (line as NSString).draw(
                    with: CGRect(x: margin, y: y, width: width, height: bounding.height),
                    options: [.usesLineFragmentOrigin, .usesFontLeading],
                    attributes: bodyAttrs, context: nil)
                y += bounding.height
            }
        }
        let url = FileManager.default.temporaryDirectory
            .appendingPathComponent("shared-memory-\(record.id.prefix(8)).pdf")
        do {
            try data.write(to: url, options: .atomic)
            return url
        } catch {
            return nil
        }
    }

    private static func dateText(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.locale = Locale(identifier: "zh_Hans_CN")
        formatter.dateFormat = "yyyy-MM-dd HH:mm"
        return formatter.string(from: date)
    }
}

struct PersonaShareSheet: View {
    let source: AgentPersona
    let title: String
    let content: String
    @ObservedObject private var store = PersonaStore.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationView {
            List {
                if store.personas.filter({ $0.id != source.id }).isEmpty {
                    Text(AppLocalized("先新建另一个人格，才能分享。"))
                        .foregroundStyle(.secondary)
                } else {
                    ForEach(store.personas.filter { $0.id != source.id }) { target in
                        Button {
                            SharedMemoryStore.shared.share(source: source, target: target,
                                                            title: title, content: content)
                            ShareFeedbackToast.show(AppLocalizedFormat("已分享给 %@", target.name))
                            dismiss()
                        } label: {
                            HStack(spacing: 10) {
                                Text(target.icon.isEmpty ? "🙂" : target.icon)
                                VStack(alignment: .leading, spacing: 2) {
                                    Text(target.name)
                                    Text(target.style.isEmpty ? AppLocalized("未设置风格") : target.style)
                                        .font(.caption).foregroundStyle(.secondary)
                                }
                            }
                        }
                        .buttonStyle(.plain)
                    }
                }
            }
            .navigationTitle(AppLocalized("分享给其他人格"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button(AppLocalized("取消")) { dismiss() }
                }
            }
        }
        .navigationViewStyle(.stack)
    }
}
