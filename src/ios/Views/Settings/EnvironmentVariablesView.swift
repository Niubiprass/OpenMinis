// >>>IOS15PORTED>>>
import SwiftUI
import UIKit

struct EnvironmentVariablesView: View {
    @StateObject private var store = EnvVarStore.shared
    @StateObject private var privacy = EnvVarPrivacyStore.shared
    @ObservedObject private var deepLink = DeepLinkCoordinator.shared
    @State private var searchText = ""
    @State private var showingAddSheet = false
    @State private var editingEntry: EnvVarEntry?
    @State private var revealedKeys: Set<String> = []
    @State private var copiedId: String?
    @State private var prefillKey = ""
    @State private var prefillValue = ""
    @State private var prefillNote = ""
    @State private var overwriteConfirm: OverwriteRequest?

    private struct OverwriteRequest: Identifiable {
        let id = UUID()
        let entryId: String
        let key: String
        let newValue: String
    }

    private var filteredEntries: [EnvVarEntry] {
        if searchText.isEmpty {
            return store.entries
        }
        return store.entries.filter { $0.key.localizedCaseInsensitiveContains(searchText) }
    }

    var body: some View {
        List {
            Section {

            if store.entries.isEmpty {
                Section {
                    VStack(spacing: 8) {
                        Image(systemName: "terminal")
                            .font(.largeTitle)
                            .foregroundStyle(.secondary)
                        Text("No Environment Variables")
                            .font(.headline)
                        Text("Add variables like API keys or tokens that will be available in the shell environment.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 20)
                }
            } else {
                ForEach(filteredEntries) { entry in
                    envVarRow(entry)
                }
                .onDelete(perform: deleteEntries)
            }
        }
        .listStyle(.insetGrouped)
        .searchable(text: $searchText, prompt: "Filter by name")
        .navigationTitle("Environment Variables")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarTrailing) {
                Button {
            }
        }
        .sheet(isPresented: $showingAddSheet) {
            EnvVarFormSheet(mode: .add, initialKey: prefillKey, initialValue: prefillValue, initialNote: prefillNote) { key, value, note in
                store.add(key: key, value: value, note: note)
            }
            .onDisappear {
                prefillKey = ""
                prefillValue = ""
                prefillNote = ""
            }
        }
        .onAppear {
            if let pending = deepLink.pendingEnvVarCreate {
                let normalizedKey = pending.key.trimmingCharacters(in: .whitespacesAndNewlines).uppercased()
                deepLink.pendingEnvVarCreate = nil
                if let existing = store.entries.first(where: { $0.key == normalizedKey }) {
                    let currentValue = store.value(forKey: existing.key) ?? ""
                    if !currentValue.isEmpty && currentValue != pending.value {
                        overwriteConfirm = OverwriteRequest(
                            entryId: existing.id,
                            key: existing.key,
                            newValue: pending.value
                        )
                    } else if currentValue.isEmpty {
                        store.update(id: existing.id, key: existing.key, value: pending.value)
                    }
                } else {
                    prefillKey = pending.key
                    prefillValue = pending.value
                    prefillNote = pending.note
                    showingAddSheet = true
                }
            }
        }
        .alert(
            AppLocalized("Replace existing value?"),
            isPresented: Binding(
                get: { overwriteConfirm != nil },
                set: { if !$0 { overwriteConfirm = nil } }
            ),
            presenting: overwriteConfirm
        ) { request in
        .sheet(item: $editingEntry) { entry in
            EnvVarFormSheet(
                mode: .edit,
                initialKey: entry.key,
                initialValue: store.value(forKey: entry.key) ?? "",
                initialNote: entry.note,
                onSave: { key, value, note in
                    store.update(id: entry.id, key: key, value: value, note: note)
                },
                onDelete: {
                    store.delete(id: entry.id)
                }
            )
        }
    }

    @ViewBuilder
    private func envVarRow(_ entry: EnvVarEntry) -> some View {
        let isRevealed = revealedKeys.contains(entry.id)
        let currentValue = store.value(forKey: entry.key) ?? ""

        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(entry.key)
                    .font(.system(.body, design: .monospaced))
                    .fontWeight(.medium)
                Text(isRevealed ? currentValue : String(repeating: "\u{2022}", count: min(currentValue.count, 20)))
                    .font(.system(.caption, design: .monospaced))
                    .foregroundStyle(.secondary)
                if !entry.note.isEmpty {
                    Text(entry.note)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .fixedSize(horizontal: false, vertical: true)
                }
            }

            Spacer()

            HStack(spacing: 10) {
                Button {
                .buttonStyle(.plain)

                Button {
                .buttonStyle(.plain)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture {
            editingEntry = entry
        }
    }

    private func deleteEntries(at offsets: IndexSet) {
        let entriesToDelete = offsets.map { filteredEntries[$0] }
        for entry in entriesToDelete {
            store.delete(id: entry.id)
        }
    }
}

// MARK: - Form Sheet

private struct EnvVarFormSheet: View {
    enum Mode { case add, edit }

    let mode: Mode
    var initialKey: String = ""
    var initialValue: String = ""
    var initialNote: String = ""
    let onSave: (String, String, String) -> Void
    var onDelete: (() -> Void)? = nil

    @Environment(\.dismiss) private var dismiss
    @State private var key = ""
    @State private var value = ""
    @State private var note = ""
    @State private var showingDeleteConfirm = false
    @FocusState private var focusedField: Field?

    private enum Field: Hashable { case key, value, note }

    private var isValid: Bool {
        EnvVarStore.isValidKey(key)
    }

    var body: some View {
        NavigationView {
            Form {
                Section {
                    if !key.isEmpty && !isValid {
                        Text("Must start with a letter and contain only letters, digits, and underscores.")
                            .foregroundStyle(.red)
                    }
                }

                Section("Value") {
                    TextField("Value", text: $value)
                        .font(.system(.body, design: .monospaced))
                        .autocorrectionDisabled()
                        .focused($focusedField, equals: .value)
                        .submitLabel(.next)
                        .onSubmit { focusedField = .note }
                }

                Section("Note") {
                    ZStack(alignment: .topLeading) {
                        if note.isEmpty {
                            Text("Describe what this variable is for (optional)")
                                .foregroundStyle(.secondary)
                                .padding(.horizontal, 4)
                                .padding(.vertical, 8)
                                .allowsHitTesting(false)
                        }
                        TextEditor(text: $note)
                            .frame(minHeight: 80)
                            .focused($focusedField, equals: .note)
                    }
                }

                if mode == .edit, onDelete != nil {
                    Section {
                        Button(role: .destructive) {
                    }
                }
            }
            .navigationTitle(mode == .add ? "Add Variable" : "Edit Variable")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button(mode == .add ? "Add" : "Save") {
                        onSave(key, value, note.trimmingCharacters(in: .whitespacesAndNewlines))
                        dismiss()
                    }
                    .disabled(!isValid)
                }
            }
        }
        .alert(
            AppLocalized("Delete this variable?"),
            isPresented: $showingDeleteConfirm
        ) {
            Button(AppLocalized("Delete"), role: .destructive) {
                onDelete?()
                dismiss()
            }
            Button(AppLocalized("Cancel"), role: .cancel) {}
        }
        .onAppear {
            key = initialKey
            value = initialValue
            note = initialNote
        }
        // Use .task instead of onAppear+DispatchQueue: the wait is cancellable
        // (sheet dismissed mid-animation cancels cleanly) and we can resign any
        // existing first responder in the parent view tree first — otherwise
        // the chat input / iSH terminal can keep firstResponder and iOS
        // suppresses the sheet's keyboard intermittently.
        .task {
            // Resign any first responder owned by the presenting view tree so
            // UIKit doesn't hand the keyboard back to it when the sheet's
            // TextField asks for focus.
            UIApplication.shared.sendAction(
                #selector(UIResponder.resignFirstResponder),
                to: nil, from: nil, for: nil
            )
            // Wait for the sheet's present/detent animation to settle before
            // requesting focus. 0.45s covers both .medium and .large detents
            // on slower devices; if the sheet is dismissed sooner, .task is
            // cancelled and focus is never set.
            try? await Task.sleep(nanoseconds: 450_000_000)
            if mode == .add {
                focusedField = .key
            }
        }
    }
}
