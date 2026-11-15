import SwiftUI
import UniformTypeIdentifiers
import WebKit

/// [T-provider-group-order] The first occurrence of each type in the persisted
/// instance array defines its section position on both provider screens.
/// Keep disabled and voice-only instances here so filtering cannot move a group.
enum ProviderGroupOrder {
    static func types(in instances: [ProviderInstance]) -> [ProviderType] {
        var seen = Set<ProviderType>()
        return instances.compactMap { instance in
            seen.insert(instance.providerType).inserted ? instance.providerType : nil
        }
    }

    /// Move whole groups while preserving the existing order within each group.
    static func instanceIDs(in instances: [ProviderInstance], orderedTypes: [ProviderType]) -> [String] {
        orderedTypes.flatMap { type in
            instances.filter { $0.providerType == type }.map(\.id)
        }
    }
}

/// [T-provider-group-drag-v3] One list row. A group row carries its title; the
/// first/last flags let the row background draw a separate rounded card.
struct ProviderListEntry: Identifiable {
    enum Row {
        case group(ProviderType)
        case instance(ProviderInstance)
    }

    let id: String
    let row: Row
    var isGroupTitle: Bool {
        if case .group = row { return true }
        return false
    }
    /// True only for a group's first / last PROVIDER row (title rows: false).
    let isFirstMember: Bool
    let isLastMember: Bool
}

/// Rounds only the given corners; `UnevenRoundedRectangle` is iOS 16+ and this
/// app still targets 15.5.
struct CardCornerShape: Shape {
    let top: CGFloat
    let bottom: CGFloat

    func path(in rect: CGRect) -> Path {
        let tl = min(top, rect.width / 2), tr = tl
        let bl = min(bottom, rect.width / 2), br = bl
        var path = Path()
        path.move(to: CGPoint(x: rect.minX + tl, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.maxX - tr, y: rect.minY))
        if tr > 0 { path.addArc(center: CGPoint(x: rect.maxX - tr, y: rect.minY + tr), radius: tr,
                                startAngle: .degrees(-90), endAngle: .degrees(0), clockwise: false) }
        path.addLine(to: CGPoint(x: rect.maxX, y: rect.maxY - br))
        if br > 0 { path.addArc(center: CGPoint(x: rect.maxX - br, y: rect.maxY - br), radius: br,
                                startAngle: .degrees(0), endAngle: .degrees(90), clockwise: false) }
        path.addLine(to: CGPoint(x: rect.minX + bl, y: rect.maxY))
        if bl > 0 { path.addArc(center: CGPoint(x: rect.minX + bl, y: rect.maxY - bl), radius: bl,
                                startAngle: .degrees(90), endAngle: .degrees(180), clockwise: false) }
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY + tl))
        if tl > 0 { path.addArc(center: CGPoint(x: rect.minX + tl, y: rect.minY + tl), radius: tl,
                                startAngle: .degrees(180), endAngle: .degrees(270), clockwise: false) }
        path.closeSubpath()
        return path
    }
}

/// Both browsing and sorting draw the same line at the cell's bottom edge.
/// A group's final member has no line; headers never use this view.
private struct ProviderRowSeparator: View {
    let isLastMember: Bool

    var body: some View {
        if !isLastMember {
            Rectangle()
                .fill(Color(UIColor.separator))
                .frame(height: 1 / UIScreen.main.scale)
                .padding(.leading, 16)
                .allowsHitTesting(false)
                .accessibilityHidden(true)
        }
    }
}

/// Lists all configured provider instances grouped by provider type.
/// Replaces the old ProvidersView for the new multi-instance model.
struct ProviderInstancesView: View {
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var editMode: EditMode = .inactive
    // Only the Edit/Done button changes the layout. SwiftUI can enter transient
    // edit mode for a row swipe; that must never change section structure.
    @State private var isSortingProviders = false
    @State private var showAddProvider = false
    @State private var showImportFile = false
    @State private var importMessage: String?
    @State private var showImportResult = false
    @State private var forceSyncToast: String?
    @AppStorage("cloudSync.v2.enabled") private var iCloudSyncEnabled: Bool = false
    /// [T-provider-group-swipe-actions] Swipe-to-edit target. Value-driven so
    /// the swipe opens the SAME detail screen the row's NavigationLink does,
    /// rather than a second editor that could drift from it.
    @State private var editingInstanceId: String?
    /// Swipe-to-delete target. Deletion goes through the existing confirmation
    /// alert — a provider carries API keys and every model entry under it, so
    /// it must never be a one-swipe irreversible act.
    @State private var pendingDeleteInstance: ProviderInstance?

    var body: some View {
        List {
            // [T-115-model-catalog] Read-only global catalog of every model
            // every configured provider lists. Outside the per-provider editing
            // flows on purpose: browsing cannot change anything.
            Section {
                NavigationLink {
                    ModelCatalogView()
                } label: {
                    Label("Model Catalog", systemImage: "books.vertical")
                }
            } footer: {
                Text("Browse every listed model — context window, output limits, reasoning and modalities. Read-only.")
            }
            // [T-mimo-shadow-voice] EVERY instance appears under its providerType
            // section now (no voice-only exclusion) — a mixed vendor like MiMo
            // shows its text models here AND a shadow voice row below ("dual
            // visibility"). Pure-voice vendors (ElevenLabs etc.) still appear here
            // too; they just have no usable text models, which is expected.
            // [T-provider-row-layout] Native browsing sections own their corner
            // clipping, including the system swipe buttons. Flatten only for
            // the explicitly requested title-row reorder handles, not a swipe.
            if isSortingProviders {
                Section {
                    ForEach(listRows) { entry in
                        rowContent(entry)
                            .padding(.bottom, entry.isLastMember ? 10 : 0)
                            .listRowSeparator(.hidden)
                            .listRowBackground(rowBackground(entry))
                    }
                    .onMove(perform: moveRows)
                }
                .listSectionSeparator(.hidden)
            } else {
                ForEach(ProviderGroupOrder.types(in: store.instances), id: \.self) { type in
                    let members = store.instances.filter { $0.providerType == type }
                    Section {
                        ForEach(members) { instance in
                            let isLastMember = instance.id == members.last?.id
                            providerLink(instance)
                                .listRowSeparator(.hidden)
                                .listRowBackground(
                                    Color(UIColor.secondarySystemGroupedBackground)
                                        .overlay(alignment: .bottom) {
                                            ProviderRowSeparator(isLastMember: isLastMember)
                                        }
                                )
                        }
                    } header: {
                        providerGroupTitle(type, count: members.count)
                    }
                    .listSectionSeparator(.hidden)
                }
            }
            // [T-mimo-shadow-voice] Voice Services = a read-only SHADOW view of any
            // instance that has audio-modality models, FOLDED by base URL so two
            // instances on the same host show one row (shares that instance's
            // credential/endpoint). Tapping opens the shadow detail (voice models
            // + a "disable this voice row" toggle).
            let shadows = store.shadowVoiceProviders()
            if !shadows.isEmpty {
                Section("Voice Services") {
                    if store.hasFoldedShadowDuplicates() {
                        // Non-destructive hint: same MiMo service configured twice.
                        HStack(alignment: .top, spacing: 8) {
                            Image(systemName: "info.circle")
                                .foregroundStyle(.secondary)
                            Text("A voice service is configured more than once. Voice is merged into a single row here; you can delete the extra provider above if you want.",
                                 comment: "Duplicate voice provider hint")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                        }
                    }
                    ForEach(shadows) { shadow in
                        NavigationLink {
                            ShadowVoiceProviderDetailView(instanceId: shadow.instanceId)
                        } label: {
                            ShadowVoiceRow(shadow: shadow)
                        }
                    }
                }
            }

            if store.instances.isEmpty {
                Section {
                    VStack(spacing: 8) {
                        Image(systemName: "key.slash")
                            .font(.system(size: 32))
                            .foregroundStyle(.quaternary)
                        Text("No providers configured")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                        Text("Add a provider to get started.")
                            .font(.caption)
                            .foregroundStyle(.tertiary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 20)
                }
            }
        }
        .listStyle(.insetGrouped)
        .navigationTitle("Providers")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button(isSortingProviders ? AppLocalized("Done") : AppLocalized("Edit")) {
                    isSortingProviders.toggle()
                    editMode = isSortingProviders ? .active : .inactive
                }
            }
            
            ToolbarItem(placement: .topBarTrailing) {
                Menu {
                    Button {
                        showAddProvider = true
                    } label: {
                        Label(AppLocalized("Add Provider"), systemImage: "plus")
                    }
                    Button {
                        showImportFile = true
                    } label: {
                        Label(AppLocalized("Import Provider"), systemImage: "square.and.arrow.down")
                    }
                    if #available(iOS 17.0, *), iCloudSyncEnabled {
                        Divider()
                        Button {
                            Task { await forceSyncProviders() }
                        } label: {
                            Label(AppLocalized("Force iCloud Sync"),
                                  systemImage: "arrow.triangle.2.circlepath.icloud")
                        }
                    }
                } label: {
                    Image(systemName: "plus")
                }
            }
        }
        .environment(\.editMode, $editMode)
        .sheet(isPresented: $showAddProvider) {
            NavigationStack {
                AddProviderView()
            }
        }
        .fileImporter(isPresented: $showImportFile, allowedContentTypes: [.json]) { result in
            switch result {
            case .success(let url):
                guard url.startAccessingSecurityScopedResource() else {
                    importMessage = AppLocalized("Cannot access the selected file.")
                    showImportResult = true
                    return
                }
                defer { url.stopAccessingSecurityScopedResource() }
                guard let data = try? Data(contentsOf: url),
                      let json = String(data: data, encoding: .utf8) else {
                    importMessage = AppLocalized("Failed to read file.")
                    showImportResult = true
                    return
                }
                if let label = store.importInstanceJSON(json) {
                    importMessage = AppLocalized("Imported provider \"\(label)\" successfully.")
                } else {
                    importMessage = AppLocalized("Invalid provider configuration file.")
                }
                showImportResult = true
            case .failure:
                break
            }
        }
        // [T-provider-group-swipe-actions] Swipe-Edit lands on the very screen
        // the row taps into, so there is one provider editor, not two.
        //
        // [T-swipe-edit-white-screen] The destination is built from the id
        // captured at push time, NOT re-read from `editingInstanceId` inside
        // the closure. The previous form guarded the destination with
        // `if let id = editingInstanceId, store.instances.contains(id)`, which
        // yielded NO content whenever that read came back empty during the
        // swipe's retraction — pushing an opaque blank screen the user was
        // stuck on. See SwipeEditDestination.swift for the full mechanism.
        //
        // The deleted-while-open case that guard was aiming at is handled by
        // ProviderInstanceDetailView itself, which is reached the same way by
        // the row tap and so must already tolerate a vanishing instance.
        .swipeEditDestination(item: $editingInstanceId) { id in
            ProviderInstanceDetailView(instanceId: id)
        }
        // Same wording and same call (`store.removeInstance`) as the Delete
        // button inside ProviderInstanceDetailView — the swipe is a shortcut to
        // the existing flow, not a second deletion path with its own semantics.
        .alert(
            AppLocalized("Delete Provider"),
            isPresented: Binding(
                get: { pendingDeleteInstance != nil },
                set: { if !$0 { pendingDeleteInstance = nil } }
            ),
            presenting: pendingDeleteInstance
        ) { instance in
            Button("Delete", role: .destructive) {
                store.removeInstance(instance.id)
                pendingDeleteInstance = nil
            }
            Button("Cancel", role: .cancel) { pendingDeleteInstance = nil }
        } message: { _ in
            Text("This will remove the provider and all its model entries. API keys will be deleted from the Keychain.")
        }
        .alert(AppLocalized("Import"), isPresented: $showImportResult) {
            Button("OK") {}
        } message: {
            if let msg = importMessage { Text(msg) }
        }
        .overlay(alignment: .top) {
            if let msg = forceSyncToast {
                Text(msg)
                    .font(.subheadline.weight(.medium))
                    .foregroundStyle(.white)
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(Color.accentColor, in: Capsule())
                    .padding(.top, 8)
                    .transition(.move(edge: .top).combined(with: .opacity))
            }
        }
        .animation(.spring(response: 0.3), value: forceSyncToast)
    }

    @available(iOS 17.0, *)
    private func forceSyncProviders() async {
        // [T-provider-forcesync-v3] markProvidersDirty now re-marks every v3
        // instance/entry/group/rule row (not just the v2 whole-file record that
        // v3 peers drop) and resets the pull-side full-history anchors.
        _ = await ForceSyncHelper.markProvidersDirty()
        await ForceSyncHelper.bidirectionalSync(recordTypes: [
            "ProviderConfig", "ProviderConfigV2",
            "ProviderInstanceV3", "ProviderModelEntryV3",
            "ProviderModelGroupV3", "ProviderThinkingRuleV3",
            "SubAgentV3",
        ])
        forceSyncToast = AppLocalized("Syncing providers via iCloud")
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) {
            forceSyncToast = nil
        }
    }

    // MARK: - [T-provider-group-drag-v3] Reordering

    /// Group title row, then that group's rows. Title rows carry the group's
    /// own count; the last row of a group ends its card.
    private var listRows: [ProviderListEntry] {
        let instances = store.instances
        var entries: [ProviderListEntry] = []
        for type in ProviderGroupOrder.types(in: instances) {
            let members = instances.filter { $0.providerType == type }
            guard !members.isEmpty else { continue }
            entries.append(ProviderListEntry(id: "group." + type.rawValue, row: .group(type),
                                             isFirstMember: false, isLastMember: false))
            for (index, member) in members.enumerated() {
                entries.append(ProviderListEntry(id: member.id, row: .instance(member),
                                                 isFirstMember: index == 0, isLastMember: index == members.count - 1))
            }
        }
        return entries
    }

    @ViewBuilder
    private func rowContent(_ entry: ProviderListEntry) -> some View {
        switch entry.row {
        case .group(let type):
            providerGroupTitle(type, count: store.instances.filter { $0.providerType == type }.count)
                .padding(.top, 12)
                .padding(.bottom, 6)
                .contentShape(Rectangle())
        case .instance(let instance):
            providerLink(instance)
        }
    }

    private func providerGroupTitle(_ type: ProviderType, count: Int) -> some View {
        HStack(spacing: 8) {
            Text(type.displayName)
                .font(.caption)
                .foregroundStyle(.secondary)
            Spacer(minLength: 0)
            Text("\(count)")
                .font(.caption2)
                .foregroundStyle(.tertiary)
        }
        .textCase(nil)
    }

    /// Same navigation, actions and deletion confirmation in both layouts.
    private func providerLink(_ instance: ProviderInstance) -> some View {
        NavigationLink {
            ProviderInstanceDetailView(instanceId: instance.id)
        } label: {
            InstanceRow(instance: instance)
        }
        .swipeActions(edge: .trailing, allowsFullSwipe: false) {
            Button(role: .destructive) {
                pendingDeleteInstance = instance
            } label: {
                Label("Delete", systemImage: "trash")
            }
            Button {
                editingInstanceId = instance.id
            } label: {
                Label("Edit", systemImage: "pencil")
            }
            .tint(.blue)
        }
    }

    /// The title row draws NOTHING — it must look like the old grey section
    /// header outside the card. Provider rows draw one card per group: only the
    /// group's first row rounds its top and its last row rounds the bottom, so
    /// the rows in between join seamlessly.
    @ViewBuilder
    private func rowBackground(_ entry: ProviderListEntry) -> some View {
        switch entry.row {
        case .group:
            Color.clear
        case .instance:
            CardCornerShape(top: entry.isFirstMember ? 12 : 0,
                            bottom: entry.isLastMember ? 12 : 0)
                .fill(Color(UIColor.secondarySystemGroupedBackground))
                .padding(.bottom, entry.isLastMember ? 10 : 0)
                // Here the line is at the CELL edge, outside the label's default
                // vertical insets. Never draw one under a title or group end.
                .overlay(alignment: .bottom) {
                    ProviderRowSeparator(isLastMember: entry.isLastMember)
                }
        }
    }

    /// Whole-group moves come from dragging a title row; provider drags only
    /// reorder inside their own group. Group order is read from title rows
    /// alone, so a provider row can never pin or lift a group.
    private func moveRows(from source: IndexSet, to destination: Int) {
        let instances = store.instances
        var rows = listRows.map(\.row)
        guard !source.isEmpty, source.allSatisfy({ rows.indices.contains($0) }),
              (0...rows.count).contains(destination) else { return }
        let moved = source.map { rows[$0] }
        let insertion = destination - source.filter { $0 < destination }.count
        for index in source.reversed() { rows.remove(at: index) }
        rows.insert(contentsOf: moved, at: insertion)

        var types: [ProviderType] = []
        var members: [ProviderType: [String]] = [:]
        for row in rows {
            switch row {
            case .group(let type):
                if !types.contains(type) { types.append(type) }
                if members[type] == nil { members[type] = [] }
            case .instance(let instance):
                members[instance.providerType, default: []].append(instance.id)
            }
        }
        for instance in instances where members[instance.providerType]?.contains(instance.id) != true {
            if !types.contains(instance.providerType) { types.append(instance.providerType) }
            members[instance.providerType, default: []].append(instance.id)
        }
        let ids = types.flatMap { members[$0] ?? [] }
        guard ids.count == instances.count,
              Set(ids) == Set(instances.map(\.id)),
              ids != instances.map(\.id) else { return }
        store.reorderInstances(ids)
    }
}

/// [T-ios-provider-row-keychain-in-body] Reuse the credential caches' 15s
/// backstop, but cache an off-main task as well as its result. A cold row must
/// never perform Keychain I/O from `body`. The router's Bool cache cannot supply
/// the masked subtitle or the row's provider-specific authentication semantics.
final class ProviderRowCredentialCache: @unchecked Sendable {
    static let shared = ProviderRowCredentialCache()
    static let didInvalidate = Notification.Name("ProviderRowCredentialCache.didInvalidate")

    /// Only immutable, Sendable inputs cross into the Keychain worker. Account
    /// selection is part of identity even though the existing row authenticates
    /// the instance's own slot, not any/active subscription account.
    struct Request: Hashable, Sendable {
        let instanceId: String
        let providerType: ProviderType
        let credentialType: ProviderCredential
        let allowsEmptyAPIKey: Bool
        let subscriptionAccountIds: [String]?
        let subscriptionActiveAccountId: String?
        let revision: UInt
        let generation: UInt
    }

    struct Display: Sendable {
        let isConfigured: Bool
        let summary: String
        var needsReauth = false
        static let loading = Display(isConfigured: false, summary: "…")
    }

    private struct Entry {
        let request: Request
        let id = UUID()
        let task: Task<Display, Never>
        let at: Date
    }

    private static let ttl: TimeInterval = 15
    private let lock = NSLock()
    private var entries: [String: Entry] = [:]
    // UI reads only already-completed, masked display values. No Keychain read
    // or token decoding is permitted on this synchronous lookup.
    private var completed: [String: (request: Request, display: Display)] = [:]
    private var invalidationGeneration: UInt = 0

    var generation: UInt {
        lock.lock()
        defer { lock.unlock() }
        return invalidationGeneration
    }

    /// Existing foreground and iCloud Keychain hooks call this. Notify visible
    /// rows too: a stored SwiftUI snapshot no longer re-probes on every redraw.
    func invalidateAll() {
        lock.lock()
        invalidationGeneration &+= 1
        entries.removeAll()
        completed.removeAll()
        lock.unlock()
        NotificationCenter.default.post(name: Self.didInvalidate, object: nil)
    }

    func cachedDisplay(for request: Request) -> Display? {
        lock.lock()
        defer { lock.unlock() }
        guard request.generation == invalidationGeneration,
              let cached = completed[request.instanceId], cached.request == request else { return nil }
        return cached.display
    }

    func value(for request: Request) async -> Display? {
        await value(for: request, probe: Self.probe)
    }

    // Probe injection lets the real cache be tested with deterministic delayed
    // responses without touching credentials or any server.
    func value(for request: Request,
               probe: @escaping @Sendable (Request) -> Display) async -> Display? {
        guard !Task.isCancelled, let entry = entry(for: request, probe: probe) else { return nil }
        let value = await entry.task.value
        guard !Task.isCancelled, rememberIfCurrent(value, entry: entry) else { return nil }
        return value
    }

    /// Synchronous lock scope, never held across an await or Keychain work.
    /// Keeping the task shares a cold probe across disappearing/reappearing rows;
    /// completion never writes into the dictionary, so old work cannot refill it.
    private func entry(for request: Request, probe: @escaping @Sendable (Request) -> Display) -> Entry? {
        lock.lock()
        defer { lock.unlock() }
        guard request.generation == invalidationGeneration else { return nil }
        let now = Date()
        if let existing = entries[request.instanceId] {
            guard existing.request.revision <= request.revision else { return nil }
            if existing.request == request, now.timeIntervalSince(existing.at) < Self.ttl {
                return existing
            }
        }
        let task = Task.detached(priority: .userInitiated) { probe(request) }
        let entry = Entry(request: request, task: task, at: now)
        entries[request.instanceId] = entry
        return entry
    }

    private func rememberIfCurrent(_ value: Display, entry: Entry) -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard entry.request.generation == invalidationGeneration,
              entries[entry.request.instanceId]?.id == entry.id else { return false }
        completed[entry.request.instanceId] = (entry.request, value)
        return true
    }

    private static func probe(_ request: Request) -> Display {
        switch request.credentialType {
        case .apiKey:
            let key = ProviderKeychainHelper.loadAPIKey(instanceId: request.instanceId)
            if key == nil, request.allowsEmptyAPIKey {
                return Display(isConfigured: true, summary: AppLocalized("No key required"))
            }
            return Display(isConfigured: key != nil, summary: key.map(maskKey) ?? AppLocalized("No API key"))
        case .oauth:
            let authed = probeOAuthAuthenticated(request)
            let needsReauth = (authed || request.providerType.isDomesticSubscription)
                && ProviderKeychainHelper.oauthNeedsReauth(instanceId: request.instanceId)
            return Display(isConfigured: authed && !needsReauth,
                           summary: needsReauth ? AppLocalized("Sign-in expired")
                               : authed ? AppLocalized("Authenticated") : AppLocalized("Not authenticated"),
                           needsReauth: needsReauth)
        }
    }

    /// These are the managers' local isAuthenticated predicates, not their login
    /// or refresh methods. Managers are MainActor-isolated; their Keychain reads
    /// and token decoding are not. Preserve the exact storage type and empty-token
    /// rules instead of invoking a manager (or the router's broader Bool probe).
    private static func probeOAuthAuthenticated(_ request: Request) -> Bool {
        let id = request.instanceId
        if request.providerType.isDomesticSubscription {
            guard !ProviderKeychainHelper.oauthNeedsReauth(instanceId: id),
                  let token = ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: SubscriptionTokenStorage.self),
                  token.provider == request.providerType.rawValue else { return false }
            return !token.accessToken.isEmpty
        }
        if ProviderKeychainHelper.loadOAuthString(instanceId: id, account: "manual-oauth-token") != nil {
            return true
        }
        switch request.providerType {
        case .anthropic: return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: ClaudeTokenStorage.self)?.accessToken != nil
        case .gemini: return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: GeminiTokenStorage.self)?.accessToken != nil
        case .openAI: return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: CodexTokenStorage.self)?.accessToken != nil
        case .antigravity: return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: AntigravityTokenStorage.self)?.accessToken != nil
        case .openRouter: return ProviderKeychainHelper.loadAPIKey(instanceId: id) != nil
        case .xAI: return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: XAITokenStorage.self)?.accessToken != nil
        case .kimiCode: return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: KimiTokenStorage.self)?.accessToken != nil
        case .githubCopilot: return ProviderKeychainHelper.loadOAuthToken(instanceId: id, as: CopilotTokenStorage.self)?.githubToken.isEmpty == false
        case .openAIResponses, .unsupported, .workBuddy, .traeCN: return false
        }
    }

    private static func maskKey(_ key: String) -> String {
        guard key.count > 8 else { return "****" }
        return String(key.prefix(6)) + "..." + String(key.suffix(4))
    }
}

private struct InstanceRow: View {
    let instance: ProviderInstance
    @ObservedObject private var store = ProviderConfigStore.shared
    @ObservedObject private var quotaService = ProviderQuotaService.shared

    @State private var credentialResult: (request: ProviderRowCredentialCache.Request,
                                           display: ProviderRowCredentialCache.Display)?
    @State private var credentialGeneration = ProviderRowCredentialCache.shared.generation

    private var credentialRequest: ProviderRowCredentialCache.Request {
        .init(instanceId: instance.id, providerType: instance.providerType,
              credentialType: instance.credentialType, allowsEmptyAPIKey: instance.allowsEmptyAPIKey,
              subscriptionAccountIds: instance.subscriptionAccountIds,
              subscriptionActiveAccountId: instance.subscriptionActiveAccountId,
              revision: store.authRevision, generation: credentialGeneration)
    }

    @MainActor
    private func currentRequestMatches(_ request: ProviderRowCredentialCache.Request) -> Bool {
        guard let current = store.instance(for: request.instanceId) else { return false }
        return current.id == instance.id && store.authRevision == request.revision
            && current.providerType == request.providerType
            && current.credentialType == request.credentialType
            && current.allowsEmptyAPIKey == request.allowsEmptyAPIKey
            && current.subscriptionAccountIds == request.subscriptionAccountIds
            && current.subscriptionActiveAccountId == request.subscriptionActiveAccountId
    }

    var body: some View {
        let request = credentialRequest
        let credentialDisplay = (credentialResult?.request == request ? credentialResult?.display : nil)
            ?? ProviderRowCredentialCache.shared.cachedDisplay(for: request) ?? .loading
        let modelCount = store.visibleEntryCount(for: instance.id)
        // [T-115-quota] Quota pill for this instance (nil = unsupported/unfetched).
        let quota = quotaService.cachedQuota(instanceId: instance.id)
        HStack(spacing: 12) {
            Circle()
                .fill(quota?.highlighted == true ? Color.yellow
                      : (credentialDisplay.needsReauth ? Color.red
                         : credentialDisplay.isConfigured && instance.isEnabled ? Color.green : Color(UIColor.quaternaryLabel)))
                .frame(width: 8, height: 8)

            VStack(alignment: .leading, spacing: 2) {
                Text(instance.label)
                    .font(.body.weight(.medium))
                HStack(spacing: 6) {
                    Text(instance.credentialType == .apiKey ? "API Key" : "OAuth")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Text("·")
                        .font(.caption)
                        .foregroundStyle(.quaternary)
                    Text(credentialDisplay.summary)
                        .font(.caption)
                        .foregroundStyle(credentialDisplay.needsReauth ? AnyShapeStyle(Color.red) : AnyShapeStyle(.secondary))
                        .lineLimit(1)
                }
                if modelCount > 0 {
                    Text(AppLocalized("\(modelCount) models"))
                        .font(.caption2)
                        .foregroundStyle(.tertiary)
                }
            }

            Spacer()

            if let quota {
                // [T-quota-newapi-balance] Green = a real remaining balance read
                // from New API; grey = month-to-date usage only (the site has no
                // balance API). Yellow still means "low", and only a real
                // balance can legitimately trigger it.
                let isBalance = quota.kind == .balance
                Text(quota.displayText)
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(
                        quota.highlighted ? Color.yellow : (isBalance ? Color.green : Color.secondary)
                    )
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(
                        quota.highlighted
                            ? Color.yellow.opacity(0.12)
                            : (isBalance ? Color.green.opacity(0.12) : Color(UIColor.quaternarySystemFill))
                    )
                    .clipShape(Capsule())
            }

            if !instance.isEnabled {
                Text("Disabled")
                    .font(.caption2.weight(.medium))
                    .foregroundStyle(.secondary)
                    .padding(.horizontal, 6)
                    .padding(.vertical, 2)
                    .background(Color(UIColor.quaternarySystemFill))
                    .clipShape(Capsule())
            }
        }
        .padding(.vertical, 2)
        .onReceive(NotificationCenter.default.publisher(for: ProviderRowCredentialCache.didInvalidate)
            .receive(on: DispatchQueue.main)) { _ in
                credentialGeneration = ProviderRowCredentialCache.shared.generation
        }
        .task(id: request) {
            let cache = ProviderRowCredentialCache.shared
            let latestGeneration = cache.generation
            guard request.generation == latestGeneration else {
                credentialGeneration = latestGeneration
                return
            }
            guard let display = await cache.value(for: request), !Task.isCancelled,
                  credentialRequest == request, cache.generation == request.generation,
                  currentRequestMatches(request) else { return }
            credentialResult = (request, display)
        }
        .onAppear {
            // Existing 15-minute foreground gate stays in the quota service.
            quotaService.refreshAllIfNeeded(instances: [instance])
        }
    }
}

// MARK: - Shadow Voice Row [T-mimo-shadow-voice]

/// A Voice Services row backed by another instance's audio-modality models.
private struct ShadowVoiceRow: View {
    let shadow: ProviderConfigStore.ShadowVoiceProvider

    var body: some View {
        HStack(spacing: 10) {
            Image(systemName: "waveform")
                .foregroundStyle(.secondary)
                .frame(width: 22)
            VStack(alignment: .leading, spacing: 2) {
                Text(shadow.displayName)
                    .font(.body)
                let asr = shadow.inputModels.count
                let tts = shadow.outputModels.count
                Text(voiceSummary(asr: asr, tts: tts))
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
            Spacer()
        }
        .padding(.vertical, 2)
    }

    private func voiceSummary(asr: Int, tts: Int) -> String {
        var parts: [String] = []
        if asr > 0 { parts.append(AppLocalized("\(asr) speech-to-text", comment: "ASR model count")) }
        if tts > 0 { parts.append(AppLocalized("\(tts) text-to-speech", comment: "TTS model count")) }
        return parts.joined(separator: " · ")
    }
}

// MARK: - [T-115-model-catalog] Read-only global model catalog

/// Read-only catalog of every model every configured provider lists
/// (FEATURES-WIP 160651 "模型目录"; App Store 1.15 "多模型自由选择 / 新增模型").
///
/// Deliberate v1 constraints:
///   - ZERO write paths: no selection, no overrides, no hiding, no group
///     membership, no refresh — browsing cannot disturb saved configs, model
///     groups, or provider routing. Entry is via Settings → Providers → Model
///     Catalog, nowhere near the model picker's own guarded toolbar.
///   - Metadata the provider does not report shows nothing (no fabricated
///     capabilities): context window / output tokens / reasoning / modality
///     badges appear only when the entry actually carries them.
///   - `sortedByReleaseRank` matches the picker's ordering so the catalog
///     reads consistently with the selection UI.
struct ModelCatalogView: View {
    private struct CatalogSection: Identifiable {
        let instance: ProviderInstance
        let entries: [ModelEntry]
        var id: String { instance.id }
    }

    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var query = ""

    private var sections: [CatalogSection] {
        let q = query.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        return store.instances.compactMap { instance in
            var entries = ProviderConfigStore.sortedByReleaseRank(store.entries(for: instance.id))
            if !q.isEmpty {
                entries = entries.filter { entry in
                    let m = entry.model
                    return m.id.lowercased().contains(q)
                        || m.displayName.lowercased().contains(q)
                }
            }
            return entries.isEmpty ? nil : CatalogSection(instance: instance, entries: entries)
        }
    }

    var body: some View {
        catalogList
            .searchable(text: $query, placement: .navigationBarDrawer(displayMode: .always), prompt: "Search models")
            .navigationTitle("Model Catalog")
            .navigationBarTitleDisplayMode(.inline)
    }

    /// [ci-fix-20261019] Split out of `body`: Swift 6.2 type-checks the whole
    /// List+ForEach+Section expression over its budget ("unable to type-check
    /// this expression in reasonable time"), so the list is built here and
    /// `body` only applies the navigation modifiers.
    private var catalogList: some View {
        List {
            ForEach(Array(sections.enumerated()), id: \.offset) { _, section in
                catalogSection(section)
            }
            if sections.isEmpty {
                Section {
                    Text(query.isEmpty ? "No models available" : "No matches")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 20)
                }
            }
        }
    }

    private func catalogSection(_ section: CatalogSection) -> some View {
        Section(section.instance.label) {
            ForEach(Array(section.entries.enumerated()), id: \.offset) { _, entry in
                catalogRow(entry)
            }
        }
    }

    private func catalogRow(_ entry: ModelEntry) -> some View {
        let m = entry.model
        return VStack(alignment: .leading, spacing: 4) {
            HStack(spacing: 6) {
                Text(m.displayName)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .lineLimit(1)
                if entry.isCustom {
                    meta("Custom", color: .blue)
                }
                if entry.isUnavailableFromProvider {
                    Text("Not listed by provider")
                        .font(.caption2)
                        .foregroundStyle(.red.opacity(0.8))
                }
            }
            Text(m.id)
                .font(.caption)
                .foregroundStyle(.secondary)
                .lineLimit(1)
            HStack(spacing: 6) {
                if let ctx = m.contextWindow {
                    meta(Self.formatTokens(ctx) + " context")
                }
                if let out = m.maxOutputTokens {
                    meta("up to " + Self.formatTokens(out) + " out")
                }
                if m.supportsReasoning == true {
                    meta("reasoning")
                }
                if let modality = m.modalityOverride {
                    ForEach(Self.modalityBadges(modality), id: \.self) { badge in
                        meta(badge)
                    }
                }
            }
        }
        .accessibilityElement(children: .combine)
    }

    private func meta(_ text: String, color: Color = .secondary) -> some View {
        Text(text)
            .font(.caption2)
            .foregroundStyle(color)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(Capsule().fill(color.opacity(0.12)))
    }

    static func formatTokens(_ n: Int) -> String {
        n >= 1024 ? "\(n / 1024)K" : "\(n)"
    }

    /// Explicit modality flags only — a model without an override shows no
    /// capability chips rather than a guess.
    static func modalityBadges(_ m: ModelModality) -> [String] {
        var out: [String] = []
        if m.contains(.imageInput) { out.append("vision") }
        if m.contains(.pdfInput) { out.append("PDF") }
        if m.contains(.audioInput) { out.append("audio in") }
        if m.contains(.audioOutput) { out.append("audio out") }
        if m.contains(.videoInput) { out.append("video in") }
        if m.contains(.imageOutput) { out.append("image out") }
        return out
    }
}

// MARK: - [T-quota-newapi-balance] In-app sign-in for a relay dashboard

/// Loads the relay's own site in a WKWebView that shares the app's persistent
/// cookie store (the same `WKWebsiteDataStore.default()` BrowserUse writes to).
///
/// Why this exists: New API / One API relays expose the real remaining balance
/// only at `GET {root}/api/user/self`, which accepts either a dashboard access
/// token or the site's login session. The token flow covers users willing to
/// copy one from the site's settings; this flow covers everyone else — sign in
/// once here and the balance service reuses the cookies.
///
/// Safari's cookies are NOT reachable: iOS sandboxes each app's WKWebView
/// store. That is deliberate, and it is why the sign-in happens in this sheet.
struct ProviderQuotaLoginView: View {
    let instance: ProviderInstance
    /// Called after the sheet closes so the caller can refetch the balance.
    var onFinished: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var isLoading = true
    @State private var failedReason: String?

    private var siteURL: URL? {
        // [T-quota-panel-host] The LOGIN page lives on the same host as the
        // balance, and both may differ from the API host. Reported 2026-10-21:
        // 「在 App 内登录该站点」 opened the API host and got a bare
        // 「403 Forbidden / openresty」 page — that host serves only
        // /v1/chat/completions, so no cookie could ever be captured there.
        // The panel address the user configured for balance wins.
        if let panel = ProviderQuotaService.panelBaseURL(instanceId: instance.id),
           let url = URL(string: panel) {
            return url
        }
        let raw = instance.effectiveCustomBaseURL ?? ""
        guard !raw.isEmpty, let parsed = URL(string: raw),
              let host = parsed.host, !host.isEmpty else { return nil }
        // [T-quota-login-root] A login page always lives at the SITE ROOT,
        // never under the API path. Deriving it from `apiRoot()` produced
        // `https://opencsg.com/aigateway` for a base URL of
        // `https://opencsg.com/aigateway/v1` — a 404, because only the API
        // lives there. Strip down to scheme + host + port.
        var comps = URLComponents()
        comps.scheme = parsed.scheme
        comps.host = host
        comps.port = parsed.port
        return comps.url
    }

    var body: some View {
        NavigationView {
            Group {
                if let url = siteURL {
                    QuotaLoginWebView(
                        url: url,
                        isLoading: $isLoading,
                        failedReason: $failedReason
                    )
                    .overlay {
                        if isLoading {
                            ProgressView()
                                .padding(20)
                                .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
                        }
                    }
                } else {
                    VStack(spacing: 10) {
                        Image(systemName: "link.badge.plus")
                            .font(.system(size: 34))
                            .foregroundStyle(.secondary)
                        Text("此供应商没有可登录的网址")
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .navigationTitle(Text("登录 \(instance.label)"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("取消") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("完成") {
                        onFinished()
                        dismiss()
                    }
                }
            }
            .safeAreaInset(edge: .bottom) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("登录后点「完成」，Minis 会用这个登录状态读取余额。")
                    Text("登录信息只保存在本机，不会上传。")
                        .foregroundStyle(.secondary)
                }
                .font(.caption2)
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(.regularMaterial)
            }
            .alert("网页打开失败", isPresented: Binding(
                get: { failedReason != nil },
                set: { if !$0 { failedReason = nil } }
            )) {
                Button("好") { failedReason = nil }
            } message: {
                Text(failedReason ?? "")
            }
        }
        .navigationViewStyle(.stack)
    }
}

private struct QuotaLoginWebView: UIViewRepresentable {
    let url: URL
    @Binding var isLoading: Bool
    @Binding var failedReason: String?

    func makeCoordinator() -> Coordinator { Coordinator(self) }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.allowsBackForwardNavigationGestures = true
        context.coordinator.host = webView
        webView.load(URLRequest(url: url))
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKNavigationDelegate {
        private let parent: QuotaLoginWebView
        weak var host: WKWebView?

        init(_ parent: QuotaLoginWebView) { self.parent = parent }

        func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
            parent.isLoading = false
            // Give a healthy SPA a moment to boot before calling it stuck.
            // [T-csp-recovery-diag] Log only. Showing the diagnostic JSON to
            // the user was wrong: it fired on perfectly healthy sites that the
            // heuristic misread, and a raw JSON blob is not an error message.
            DispatchQueue.main.asyncAfter(deadline: .now() + 2.0) { [weak webView] in
                guard let webView = webView else { return }
                CSPRecovery.diagnose(webView) { info in
                    NSLog("[CSPRecovery] still stuck: %@", info)
                }
            }
        }

        func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
            parent.isLoading = false
            // [T-csp-recovery-cancel] Re-rendering through loadHTMLString
            // cancels the in-flight navigation, which arrives here as
            // NSURLErrorCancelled (-999). That is us, not a failure — showing
            // it as "网页打开失败" made a working repair look broken.
            guard !CSPRecovery.isCancellation(error) else { return }
            parent.failedReason = error.localizedDescription
        }

        func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!, withError error: Error) {
            parent.isLoading = false
            guard !CSPRecovery.isCancellation(error) else { return }
            parent.failedReason = error.localizedDescription
        }
    }
}
