import SwiftUI

/// Onboarding step 2: pick one or more models from all configured providers and create a "Default Models" group.
struct OnboardingModelSelectionView: View {
    @ObservedObject private var store = ProviderConfigStore.shared
    @Environment(\.dismiss) private var dismiss

    @State private var selectedModelEntryIds: [String] = []
    @State private var searchText: String = ""

    /// All visible model entries across all enabled instances.
    private var allEntries: [ModelEntry] {
        store.instances
            .filter(\.isEnabled)
            .flatMap { store.visibleEntries(for: $0.id) }
    }

    var body: some View {
        List {
            if allEntries.isEmpty {
                Section {
                    Text("Fetching model list from your provider…")
                }
            } else {
                // Group entries by provider instance
                let instanceIds = store.instances.filter(\.isEnabled).map(\.id)
                ForEach(instanceIds, id: \.self) { instanceId in
                    let entries = store.visibleEntries(for: instanceId).filter { entry in
                        searchText.isEmpty || entry.model.displayName.localizedCaseInsensitiveContains(searchText)
                    }
                    if !entries.isEmpty, let instance = store.instance(for: instanceId) {
                        Section {
                    }
                }

            }
        }
        .searchable(text: $searchText, prompt: "Filter models")
        .navigationTitle("Select Models")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button("Skip") { dismiss() }
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button("Next") { createGroupAndDismiss() }
                    .disabled(selectedModelEntryIds.isEmpty)
            }
        }
    }

    @ViewBuilder
    private func modelRow(entry: ModelEntry) -> some View {
        let selectionIndex = selectedModelEntryIds.firstIndex(of: entry.id)
        let isSelected = selectionIndex != nil

        Button {
    }

    private func createGroupAndDismiss() {
        let group = ModelGroup(
            name: "Default Models",
            memberEntryIds: selectedModelEntryIds,
            strategy: .fallback
        )
        store.addGroup(group)
        if store.defaultPrimaryGroupId == nil {
            store.defaultPrimaryGroupId = group.id
        }
        dismiss()
    }
}
