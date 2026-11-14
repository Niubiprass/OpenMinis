import SwiftUI
import UIKit
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

// BEGIN PROVIDER_GROUP_DRAG_POLICY_PURE
/// Rectangles are in the scroll view's content coordinates, ordered top to bottom.
struct ProviderGroupDragRange {
    let minY: Double
    let maxY: Double
}

enum ProviderGroupDragPolicy {
    /// Final insertion slot among the OTHER groups (0 = first, count - 1 = last).
    /// Comparing with complete groups, rather than a narrow header drop target,
    /// also accepts release over a card, its trailing space, or either list end.
    static func destination(at y: Double, ranges: [ProviderGroupDragRange], sourceIndex: Int) -> Int? {
        guard y.isFinite, ranges.indices.contains(sourceIndex),
              ranges.allSatisfy({ $0.minY.isFinite && $0.maxY.isFinite && $0.maxY > $0.minY }) else { return nil }
        for index in ranges.indices.dropFirst() {
            guard ranges[index].minY >= ranges[index - 1].maxY else { return nil }
        }
        return ranges.enumerated().filter { $0.offset != sourceIndex }
            .prefix { y >= ($0.element.minY + $0.element.maxY) / 2 }.count
    }

    /// `destination` is the final slot AFTER removal, not an index needing a
    /// direction-dependent adjustment. Top, bottom and adjacent swaps all use
    /// this one definition. No change or invalid data never schedules a save.
    static func reordered<T: Hashable>(_ order: [T], moving source: T, to destination: Int) -> [T]? {
        guard Set(order).count == order.count, let from = order.firstIndex(of: source),
              order.indices.contains(destination) else { return nil }
        var result = order
        result.remove(at: from)
        result.insert(source, at: destination)
        return result == order ? nil : result
    }
}
// END PROVIDER_GROUP_DRAG_POLICY_PURE

/// Lists all configured provider instances grouped by provider type.
/// Replaces the old ProvidersView for the new multi-instance model.
struct ProviderInstancesView: View {
    @ObservedObject private var store = ProviderConfigStore.shared
    @State private var editMode: EditMode = .inactive
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
    @StateObject private var groupDrag = ProviderGroupDragBridge()

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
            // Original Section headers and grouped cards stay native. Only
            // header long-press handling is bridged; row onMove is unchanged.
            ForEach(ProviderGroupOrder.types(in: store.instances), id: \.self) { type in
                groupSection(type)
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
        .navigationTitle("Providers")
        .navigationBarTitleDisplayMode(.inline)
        .toolbar {

                ToolbarItem(placement: .topBarLeading) {
                    EditButton()
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
        .onAppear { configureGroupDrag() }
        .onChange(of: editMode) { _ in configureGroupDrag() }
        .onChange(of: store.instances.map(\.id)) { _ in configureGroupDrag() }
        .onDisappear { groupDrag.stop() }
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

    // MARK: - Whole-group reordering; original Section UI is unchanged

    /// The bridge only commits on a real release. A background switch, leaving
    /// the page, cancelled gesture or an intervening sync leaves order alone.
    private func configureGroupDrag() {
        let types = ProviderGroupOrder.types(in: store.instances)
        let members = types.map { type in
            store.instances.filter { $0.providerType == type }.map(\.id)
        }
        groupDrag.configure(enabled: editMode == .active, order: types, members: members) {
            [weak store = store] expected, expectedMembers, source, destination in
            guard let store else { return }
            let instances = store.instances
            let current = ProviderGroupOrder.types(in: instances)
            let currentMembers = current.map { type in
                instances.filter { $0.providerType == type }.map(\.id)
            }
            guard current == expected, currentMembers == expectedMembers,
                  let ordered = ProviderGroupDragPolicy.reordered(current, moving: source, to: destination)
            else { return }
            let ids = ProviderGroupOrder.instanceIDs(in: instances, orderedTypes: ordered)
            guard ids.count == instances.count, Set(ids) == Set(instances.map(\.id)) else { return }
            store.reorderInstances(ids)
            AppLogger(category: "ProviderGroupDrag").info("saved order=\(ordered.map(\.rawValue).joined(separator: ","))")
        }
    }

    @ViewBuilder
    private func groupSection(_ type: ProviderType) -> some View {
        let members = store.instances.filter { $0.providerType == type }
        if !members.isEmpty {
            Section {
                ForEach(members) { instance in
                    NavigationLink {
                        ProviderInstanceDetailView(instanceId: instance.id)
                    } label: {
                        InstanceRow(instance: instance)
                    }
                    // [T-provider-group-swipe-actions] Swipe actions and
                    // `.onMove` coexist: UIKit routes a horizontal drag to the
                    // row's swipe actions and a vertical one to the reorder
                    // engine, and in edit mode the handles take over entirely.
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
                .onMove { source, destination in
                    moveInstances(in: type, from: source, to: destination)
                }
            } header: {
                HStack(spacing: 8) {
                    Text(type.displayName)
                    Spacer(minLength: 0)
                    Text("\(members.count)")
                        .foregroundStyle(.tertiary)
                }
                .frame(maxWidth: .infinity)
                .background(ProviderGroupDragAnchor(type: type, bridge: groupDrag))
            }
        }
    }

    /// Providers inside one group only ever move among themselves.
    private func moveInstances(in type: ProviderType, from source: IndexSet, to destination: Int) {
        let all = store.instances
        let members = all.filter { $0.providerType == type }
        var ordered = members
        ordered.move(fromOffsets: source, toOffset: destination)
        var iterator = ordered.makeIterator()
        let ids = all.map { instance -> String in
            guard instance.providerType == type else { return instance.id }
            return iterator.next()?.id ?? instance.id
        }
        guard ids != all.map(\.id) else { return }
        store.reorderInstances(ids)
    }
}

/*
Adapted long-press/auto-scroll technique from SwiftReorder.
Copyright (c) 2016 Adam Shin

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE.
*/
// BEGIN PROVIDER_GROUP_DRAG_UIKIT
// MARK: - Whole-section dragging (preserves the native List/Section renderer)

/// A zero-size background view: never adds a row, icon, padding or hit-test area.
/// It locates the existing header and scroll view; the recognizer lives on the
/// scroll view so the gesture continues after the finger leaves the header.
private struct ProviderGroupDragAnchor: UIViewRepresentable {
    let type: ProviderType
    let bridge: ProviderGroupDragBridge

    func makeUIView(context: Context) -> ProviderGroupDragProbe {
        ProviderGroupDragProbe(type: type, bridge: bridge)
    }
    func updateUIView(_ view: ProviderGroupDragProbe, context: Context) {
        if view.type != type { view.bridge?.unregister(view) }
        view.type = type
        view.connect(to: bridge)
    }
    static func dismantleUIView(_ view: ProviderGroupDragProbe, coordinator: ()) { view.disconnect() }
}

private final class ProviderGroupDragProbe: UIView {
    var type: ProviderType
    weak var bridge: ProviderGroupDragBridge?

    init(type: ProviderType, bridge: ProviderGroupDragBridge) {
        self.type = type
        self.bridge = bridge
        super.init(frame: .zero)
        isUserInteractionEnabled = false
        backgroundColor = .clear
    }
    required init?(coder: NSCoder) { fatalError("init(coder:) has not been implemented") }
    override func didMoveToWindow() {
        super.didMoveToWindow()
        if window != nil { bridge?.register(self) } else { bridge?.unregister(self) }
    }
    override func layoutSubviews() {
        super.layoutSubviews()
        if window != nil { bridge?.register(self) }
    }
    func connect(to next: ProviderGroupDragBridge) {
        if bridge !== next { disconnect(); bridge = next }
        if window != nil { next.register(self) }
    }
    func disconnect() { bridge?.unregister(self); bridge = nil }
}

/// Long-press / snapshot / edge scrolling adapted from Adam Shin's MIT-licensed
/// SwiftReorder (9553a0d805c68d2bdd1bc6e5385cf1d5e9c44a4c).
/// Unlike its row-reorder integration, this bridge never takes List's delegate,
/// data source or reorder controls; SwiftUI continues rendering every Section.
private final class ProviderGroupDragBridge: NSObject, ObservableObject, UIGestureRecognizerDelegate {
    private let logger = AppLogger(category: "ProviderGroupDrag")
    private weak var scrollView: UIScrollView?
    private var probes: [ProviderType: ProviderGroupDragProbe] = [:]
    private var order: [ProviderType] = []
    private var members: [[String]] = []
    private var enabled = false
    private var move: (([ProviderType], [[String]], ProviderType, Int) -> Void)?
    private lazy var press: UILongPressGestureRecognizer = {
        let recognizer = UILongPressGestureRecognizer(target: self, action: #selector(handlePress(_:)))
        recognizer.minimumPressDuration = 0.3
        recognizer.allowableMovement = 10
        recognizer.cancelsTouchesInView = true
        recognizer.delegate = self
        recognizer.isEnabled = false
        return recognizer
    }()
    private var source: ProviderType?
    private var originalOrder: [ProviderType] = []
    private var originalMembers: [[String]] = []
    private var ranges: [CGRect] = []
    private var sectionBase: Int?
    private var resettingPress = false
    private var destination: Int?
    private var floating: UIView?
    private var insertionLine: UIView?
    private var originMask: UIView?
    private var snapshotStartFrame: CGRect = .zero
    private var fingerStart: CGPoint = .zero
    private var lastFinger: CGPoint = .zero
    private var oldBounces: Bool?
    private var displayLink: CADisplayLink?
    private var displayLinkTarget: ProviderGroupDragDisplayTarget?
    private var resignObserver: NSObjectProtocol?

    func configure(enabled: Bool, order: [ProviderType], members: [[String]],
                   move: @escaping ([ProviderType], [[String]], ProviderType, Int) -> Void) {
        if source != nil && (!enabled || order != self.order || members != self.members) {
            finish(commit: false)
            resetPress()
        }
        self.enabled = enabled
        self.order = order
        self.members = members
        self.move = move
        press.isEnabled = enabled
    }
    func stop() {
        finish(commit: false)
        enabled = false
        press.isEnabled = false
    }
    func register(_ probe: ProviderGroupDragProbe) {
        probes[probe.type] = probe
        var ancestor = probe.superview
        while let view = ancestor {
            if let scroll = view as? UIScrollView { attach(to: scroll); break }
            ancestor = view.superview
        }
    }
    func unregister(_ probe: ProviderGroupDragProbe) {
        if probes[probe.type] === probe { probes[probe.type] = nil }
    }
    private func attach(to scroll: UIScrollView) {
        guard scrollView !== scroll else { return }
        finish(commit: false)
        scrollView?.removeGestureRecognizer(press)
        scrollView = scroll
        scroll.addGestureRecognizer(press)
        // Only a press starting INSIDE a group title may delay scroll. Row
        // handles, horizontal swipes and normal scroll remain List's gestures.
        scroll.panGestureRecognizer.require(toFail: press)
        if resignObserver == nil {
            resignObserver = NotificationCenter.default.addObserver(
                forName: UIApplication.willResignActiveNotification, object: nil, queue: .main
            ) { [weak self] _ in
                self?.finish(commit: false)
                self?.resetPress()
            }
        }
    }
    private func headerRect(_ probe: ProviderGroupDragProbe, in scroll: UIScrollView) -> CGRect {
        var rect = probe.convert(probe.bounds, to: scroll)
        // Probe locates the header; UIKit supplies its full vertical hit area,
        // including the native section's padding. Nothing alters its layout.
        if let section = sectionIndex(containing: rect.midY) {
            if let table = scroll as? UITableView { rect = table.rectForHeader(inSection: section) }
            else if let collection = scroll as? UICollectionView,
                    let attributes = collection.collectionViewLayout.layoutAttributesForSupplementaryView(
                        ofKind: UICollectionView.elementKindSectionHeader,
                        at: IndexPath(item: 0, section: section)) { rect = attributes.frame }
        }
        rect.origin.x = 0
        rect.size.width = scroll.bounds.width
        return rect
    }
    private func group(at point: CGPoint) -> ProviderType? {
        guard let scroll = scrollView else { return nil }
        return order.first { type in
            guard let probe = probes[type], probe.window != nil else { return false }
            let rect = headerRect(probe, in: scroll)
            return rect.height > 0 && rect.contains(point)
        }
    }
    func gestureRecognizer(_ gestureRecognizer: UIGestureRecognizer, shouldReceive touch: UITouch) -> Bool {
        guard enabled, UIApplication.shared.applicationState == .active,
              let scroll = scrollView else { return false }
        return group(at: touch.location(in: scroll)) != nil
    }
    func gestureRecognizerShouldBegin(_ gestureRecognizer: UIGestureRecognizer) -> Bool {
        guard enabled, let scroll = scrollView,
              let type = group(at: gestureRecognizer.location(in: scroll)),
              let index = order.firstIndex(of: type), let probe = probes[type],
              let section = sectionIndex(containing: headerRect(probe, in: scroll).midY),
              let measured = measureSections(base: section - index) else { return false }
        return ProviderGroupDragPolicy.destination(at: Double(gestureRecognizer.location(in: scroll).y),
            ranges: measured.0.map { .init(minY: Double($0.minY), maxY: Double($0.maxY)) }, sourceIndex: index) != nil
    }
    private func resetPress() {
        guard !resettingPress else { return }
        resettingPress = true
        press.isEnabled = false
        press.isEnabled = enabled
        resettingPress = false
    }
    @objc private func handlePress(_ recognizer: UILongPressGestureRecognizer) {
        guard !resettingPress else { return }
        switch recognizer.state {
        case .began: begin(at: recognizer.location(in: scrollView))
        case .changed: update()
        case .ended: update(); finish(commit: true)
        case .cancelled, .failed: finish(commit: false)
        default: break
        }
    }

    /// UIKit knows the native header/section layout for off-screen groups too.
    private func sectionIndex(containing y: CGFloat) -> Int? {
        if let table = scrollView as? UITableView {
            return (0..<table.numberOfSections).first {
                let rect = table.rectForHeader(inSection: $0)
                return rect.height > 0 && rect.minY <= y && y <= rect.maxY
            }
        }
        if let collection = scrollView as? UICollectionView {
            for section in 0..<collection.numberOfSections {
                if let rect = collection.collectionViewLayout.layoutAttributesForSupplementaryView(
                    ofKind: UICollectionView.elementKindSectionHeader,
                    at: IndexPath(item: 0, section: section))?.frame,
                   rect.height > 0 && rect.minY <= y && y <= rect.maxY { return section }
            }
        }
        return nil
    }
    private func measureSections(base: Int) -> ([CGRect], [CGRect])? {
        guard base >= 0 else { return nil }
        if let table = scrollView as? UITableView {
            guard base + order.count <= table.numberOfSections else { return nil }
            return (order.indices.map { table.rect(forSection: base + $0) },
                    order.indices.map { table.rectForHeader(inSection: base + $0) })
        }
        if let collection = scrollView as? UICollectionView {
            guard base + order.count <= collection.numberOfSections else { return nil }
            var sections: [CGRect] = [], headers: [CGRect] = []
            for section in base..<(base + order.count) {
                var rect = CGRect.null
                let path = IndexPath(item: 0, section: section)
                let header = collection.collectionViewLayout.layoutAttributesForSupplementaryView(
                    ofKind: UICollectionView.elementKindSectionHeader, at: path)?.frame ?? .zero
                if header.height > 0 { rect = rect.union(header) }
                for item in 0..<collection.numberOfItems(inSection: section) {
                    if let frame = collection.collectionViewLayout.layoutAttributesForItem(
                        at: IndexPath(item: item, section: section))?.frame { rect = rect.union(frame) }
                }
                guard !rect.isNull, rect.height > 0 else { return nil }
                sections.append(rect); headers.append(header)
            }
            return (sections, headers)
        }
        return nil
    }
    /// Native pixels only: never scroll or materialise off-screen rows merely
    /// to build a preview (row appearance can otherwise issue quota requests).
    /// Keep the complete section size, with its visible pixels at their original
    /// offsets. The list viewport clips a tall group; the committed move still
    /// includes every member of it, including all off-screen providers.
    private func snapshotSection(base: Int, sourceIndex: Int) -> UIView? {
        guard let scroll = scrollView, let measured = measureSections(base: base),
              measured.0.indices.contains(sourceIndex) else { return nil }
        let complete = measured.0[sourceIndex]
        let viewport = scroll.bounds.inset(by: scroll.adjustedContentInset)
        let visible = complete.intersection(viewport)
        guard !visible.isNull, visible.height > 0,
              let pixels = scroll.resizableSnapshotView(from: visible,
                  afterScreenUpdates: false, withCapInsets: .zero) else { return nil }
        let snapshot = UIView(frame: CGRect(origin: .zero, size: complete.size))
        snapshot.backgroundColor = .clear
        snapshot.isUserInteractionEnabled = false
        pixels.frame = visible.offsetBy(dx: -complete.minX, dy: -complete.minY)
        snapshot.addSubview(pixels)
        return snapshot
    }
    private func begin(at point: CGPoint) {
        guard enabled, let scroll = scrollView, let host = scroll.superview,
              let type = group(at: point), let sourceIndex = order.firstIndex(of: type),
              let probe = probes[type] else { resetPress(); return }
        scroll.layoutIfNeeded()
        guard let section = sectionIndex(containing: headerRect(probe, in: scroll).midY),
              let measured = measureSections(base: section - sourceIndex),
              measured.0.count == order.count,
              ProviderGroupDragPolicy.destination(at: Double(point.y), ranges: measured.0.map {
                  .init(minY: Double($0.minY), maxY: Double($0.maxY))
              }, sourceIndex: sourceIndex) != nil else {
            logger.warning("begin skipped: section geometry unavailable; no order changed")
            resetPress()
            return
        }
        let base = section - sourceIndex
        guard let snapshot = snapshotSection(base: base, sourceIndex: sourceIndex),
              let refreshed = measureSections(base: base),
              refreshed.0.count == order.count else {
            logger.warning("begin skipped: section snapshot unavailable; no order changed")
            resetPress()
            return
        }
        let visible = scroll.bounds.inset(by: scroll.adjustedContentInset)
        let completeSource = refreshed.0[sourceIndex]
        source = type
        originalOrder = order
        originalMembers = members
        ranges = refreshed.0
        sectionBase = base
        destination = sourceIndex
        let mask = UIView(frame: completeSource)
        mask.isUserInteractionEnabled = false
        mask.backgroundColor = (scroll.backgroundColor ?? .systemGroupedBackground).withAlphaComponent(0.6)
        scroll.addSubview(mask)
        originMask = mask
        // This overlay is present only during a drag and clips at the list's
        // viewport; the unchanged native section renderer stays beneath it.
        let canvas = UIView(frame: scroll.convert(visible, to: host))
        canvas.isUserInteractionEnabled = false
        canvas.clipsToBounds = true
        canvas.backgroundColor = .clear
        host.addSubview(canvas)
        let start = scroll.convert(completeSource, to: canvas)
        snapshot.frame = start
        snapshot.layer.shadowColor = UIColor.black.cgColor
        snapshot.layer.shadowOpacity = 0.28
        snapshot.layer.shadowRadius = 8
        snapshot.layer.shadowOffset = CGSize(width: 0, height: 4)
        canvas.addSubview(snapshot)
        floating = canvas
        snapshotStartFrame = start
        fingerStart = press.location(in: canvas)
        lastFinger = fingerStart
        let line = UIView(frame: .zero)
        line.isUserInteractionEnabled = false
        line.backgroundColor = .systemBlue
        line.layer.cornerRadius = 1
        scroll.addSubview(line)
        insertionLine = line
        oldBounces = scroll.bounces
        scroll.bounces = false
        UISelectionFeedbackGenerator().selectionChanged()
        logger.info("begin group=\(type.rawValue) index=\(sourceIndex) groups=\(order.count)")
        let target = ProviderGroupDragDisplayTarget(owner: self)
        let link = CADisplayLink(target: target, selector: #selector(ProviderGroupDragDisplayTarget.tick(_:)))
        displayLinkTarget = target
        displayLink = link
        link.add(to: .main, forMode: .common)
        update()
    }
    private func update() {
        guard let scroll = scrollView, let canvas = floating, let type = source,
              let sourceIndex = originalOrder.firstIndex(of: type) else { return }
        // Automatic cell-height estimation changes as we scroll. Re-read actual
        // native rectangles before EVERY destination decision and the release.
        scroll.layoutIfNeeded()
        guard let base = sectionBase, let measured = measureSections(base: base),
              measured.0.count == originalOrder.count else {
            finish(commit: false); resetPress(); return
        }
        ranges = measured.0
        originMask?.frame = ranges[sourceIndex]
        lastFinger = press.location(in: canvas)
        if let snapshot = canvas.subviews.first {
            snapshot.frame.origin.y = snapshotStartFrame.minY + lastFinger.y - fingerStart.y
        }
        let contentY = press.location(in: scroll).y
        let next = ProviderGroupDragPolicy.destination(at: Double(contentY), ranges: ranges.map {
            .init(minY: Double($0.minY), maxY: Double($0.maxY))
        }, sourceIndex: sourceIndex)
        if next != destination {
            destination = next
            UISelectionFeedbackGenerator().selectionChanged()
        }
        guard let next else {
            finish(commit: false); resetPress(); return
        }
        let other = originalOrder.indices.filter { $0 != sourceIndex }
        let y: CGFloat
        if next == sourceIndex { y = ranges[sourceIndex].minY }
        else if next < other.count { y = ranges[other[next]].minY }
        else { y = ranges[other.last ?? sourceIndex].maxY }
        insertionLine?.frame = CGRect(x: 16, y: y - 1, width: max(0, scroll.bounds.width - 32), height: 2)
        insertionLine?.isHidden = false
    }
    func autoScroll(_ link: CADisplayLink) {
        guard source != nil, let scroll = scrollView, let canvas = floating else { return }
        let point = press.location(in: canvas)
        let edge: CGFloat = 48
        let distance: CGFloat
        if point.y < edge { distance = -min(1, (edge - point.y) / edge) }
        else if point.y > canvas.bounds.height - edge {
            distance = min(1, (point.y - canvas.bounds.height + edge) / edge)
        } else { distance = 0 }
        let dt = min(max(link.targetTimestamp - link.timestamp, 0), 0.05)
        let minY = -scroll.adjustedContentInset.top
        let maxY = max(minY, scroll.contentSize.height - scroll.bounds.height + scroll.adjustedContentInset.bottom)
        let newY = min(max(scroll.contentOffset.y + distance * 320 * CGFloat(dt), minY), maxY)
        if abs(newY - scroll.contentOffset.y) > 0.01 {
            scroll.setContentOffset(CGPoint(x: scroll.contentOffset.x, y: newY), animated: false)
        }
        update()
    }
    private func finish(commit: Bool) {
        let type = source, next = destination, expected = originalOrder, expectedMembers = originalMembers
        source = nil
        destination = nil
        displayLink?.invalidate(); displayLink = nil; displayLinkTarget = nil
        floating?.removeFromSuperview(); floating = nil
        insertionLine?.removeFromSuperview(); insertionLine = nil
        originMask?.removeFromSuperview(); originMask = nil
        if let bounces = oldBounces { scrollView?.bounces = bounces }
        oldBounces = nil
        ranges = []; sectionBase = nil; originalOrder = []; originalMembers = []
        guard let type else { return }
        if commit, enabled, UIApplication.shared.applicationState == .active, let next,
           expected == order, expectedMembers == members {
            logger.info("release group=\(type.rawValue) from=\(expected.firstIndex(of: type) ?? -1) to=\(next)")
            move?(expected, expectedMembers, type, next)
        } else {
            logger.info("cancel group=\(type.rawValue); no order saved")
        }
    }
    deinit {
        displayLink?.invalidate()
        floating?.removeFromSuperview()
        insertionLine?.removeFromSuperview()
        originMask?.removeFromSuperview()
        if let bounces = oldBounces { scrollView?.bounces = bounces }
        if let scroll = scrollView { scroll.removeGestureRecognizer(press) }
        if let observer = resignObserver { NotificationCenter.default.removeObserver(observer) }
    }
}

/// CADisplayLink retains its target; use a weak proxy so it cannot keep a
/// closed provider screen alive after cancellation/dismantling.
private final class ProviderGroupDragDisplayTarget: NSObject {
    weak var owner: ProviderGroupDragBridge?
    init(owner: ProviderGroupDragBridge) { self.owner = owner }
    @objc func tick(_ link: CADisplayLink) { owner?.autoScroll(link) }
}
// END PROVIDER_GROUP_DRAG_UIKIT

/// [T-ios-provider-row-keychain-in-body] Per-row credential display state, resolved
/// ONCE per (instance, authRevision) instead of on every SwiftUI body evaluation.
///
/// `isConfigured` and `credentialSummary` were each reading Keychain directly from
/// `body`. Every `SecItemCopyMatching` is a synchronous XPC round-trip to
/// `securityd`, so one body pass over N provider rows cost 2N blocking IPCs on the
/// MAIN THREAD — a real user log shows 110 `caller=isConfigured` +
/// 110 `caller=credentialSummary` reads in a single session (655 Keychain reads
/// overall). A crash report from that same session caught the main thread parked
/// inside `SecItemCopyMatching` under `InstanceRow.body`.
///
/// This is the same hazard `ProviderCredentialCache`
/// ([T-new-session-hang-credential-cache]) already exists for; the row simply
/// bypassed it. A separate cache is used rather than `hasAnyCredential` because
/// the row needs strictly more than a Bool — it renders the MASKED KEY, and its
/// OAuth notion of "authenticated" is per-provider-manager, not the router's
/// any-credential test. Reusing `hasAnyCredential` here would silently change
/// what the row displays.
///
/// Keying on `authRevision` (bumped by `notifyAuthChanged` on every credential
/// write/delete) makes invalidation exact: the UI still updates immediately after
/// the user adds or removes a key. The TTL is only a backstop for credential
/// changes that happen outside the app (Keychain iCloud sync).
final class ProviderRowCredentialCache: @unchecked Sendable {
    static let shared = ProviderRowCredentialCache()

    struct Display {
        let isConfigured: Bool
        let summary: String
        /// [T-oauth-keep-credentials] OAuth credential kept but its refresh was
        /// rejected — row renders red until the user signs in again.
        var needsReauth = false
    }

    /// Backstop only — `authRevision` is the primary invalidation signal.
    private static let ttl: TimeInterval = 15

    private let lock = NSLock()
    private var entries: [String: (value: Display, revision: UInt, at: Date)] = [:]

    private init() {}

    /// Drop everything. Called from the SAME places that clear
    /// `ProviderCredentialCache`, because those events (Keychain iCloud
    /// `view-change`, app foreground) change credentials WITHOUT bumping
    /// `authRevision` — so the revision key alone would not notice them.
    func invalidateAll() {
        lock.lock()
        entries.removeAll()
        lock.unlock()
    }

    func value(for instanceId: String, revision: UInt, probe: () -> Display) -> Display {
        let now = Date()
        lock.lock()
        if let e = entries[instanceId], e.revision == revision,
           now.timeIntervalSince(e.at) < Self.ttl {
            lock.unlock()
            return e.value
        }
        lock.unlock()

        // Probe runs OUTSIDE the lock — it does Keychain XPC and must not
        // serialize concurrent probes for different instances.
        let fresh = probe()

        lock.lock()
        entries[instanceId] = (fresh, revision, now)
        lock.unlock()
        return fresh
    }
}

private struct InstanceRow: View {
    let instance: ProviderInstance
    @ObservedObject private var store = ProviderConfigStore.shared
    @ObservedObject private var quotaService = ProviderQuotaService.shared

    /// Both display properties come from one cached probe, so a body pass costs
    /// zero Keychain round-trips once warm.
    private var credentialDisplay: ProviderRowCredentialCache.Display {
        ProviderRowCredentialCache.shared.value(for: instance.id, revision: store.authRevision) {
            let configured: Bool
            let summary: String
            var needsReauth = false
            switch instance.credentialType {
            case .apiKey:
                // Single Keychain read serves BOTH the dot and the masked subtitle;
                // previously these were two independent reads of the same item.
                let key = ProviderKeychainHelper.loadAPIKey(instanceId: instance.id)
                // [T-empty-key-compat-endpoints] A keyless third-party
                // compatible endpoint is configured-by-definition; say so
                // instead of the alarming "No API key".
                if key == nil, instance.allowsEmptyAPIKey {
                    configured = true
                    summary = AppLocalized("No key required")
                } else {
                    configured = key != nil
                    summary = key.map(Self.maskKey) ?? AppLocalized("No API key")
                }
            case .oauth:
                let authed = Self.probeOAuthAuthenticated(instance)
                needsReauth = (authed || instance.providerType.isDomesticSubscription)
                    && ProviderKeychainHelper.oauthNeedsReauth(instanceId: instance.id)
                configured = authed && !needsReauth
                summary = needsReauth ? AppLocalized("Sign-in expired")
                    : authed ? AppLocalized("Authenticated")
                    : AppLocalized("Not authenticated")
            }
            return .init(isConfigured: configured, summary: summary, needsReauth: needsReauth)
        }
    }

    private var isConfigured: Bool { credentialDisplay.isConfigured }

    private var credentialSummary: String { credentialDisplay.summary }

    /// The uncached OAuth probe. `static` so the cache closure can call it without
    /// capturing `self` (the row is a short-lived struct; the cache outlives it).
    private static func probeOAuthAuthenticated(_ instance: ProviderInstance) -> Bool {
        if instance.providerType.isDomesticSubscription {
            return SubscriptionOAuthManager.shared.isAuthenticated(instanceId: instance.id, type: instance.providerType)
        }
        // Manual OAuth token is always considered authenticated
        if ProviderKeychainHelper.loadOAuthString(instanceId: instance.id, account: "manual-oauth-token") != nil {
            return true
        }
        switch instance.providerType {
        case .anthropic: return ClaudeOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .gemini: return GeminiOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .openAI: return CodexOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .antigravity: return AntigravityOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .openRouter: return OpenRouterOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .openAIResponses: return false // API key only
        case .xAI: return XAIOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .kimiCode: return KimiOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .githubCopilot: return CopilotOAuthManager.shared.isAuthenticated(instanceId: instance.id)
        case .workBuddy, .traeCN:
            return SubscriptionOAuthManager.shared.isAuthenticated(instanceId: instance.id, type: instance.providerType)
        case .unsupported: return false // synced from newer build
        }
    }

    private var modelCount: Int {
        store.visibleEntries(for: instance.id).count
    }

    var body: some View {
        let _ = store.authRevision  // subscribe to OAuth state changes
        // [T-115-quota] Quota pill for this instance (nil = unsupported/unfetched).
        let quota = quotaService.cachedQuota(instanceId: instance.id)
        HStack(spacing: 12) {
            Circle()
                .fill(quota?.highlighted == true ? Color.yellow
                      : (credentialDisplay.needsReauth ? Color.red
                         : isConfigured && instance.isEnabled ? Color.green : Color(UIColor.quaternaryLabel)))
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
                    Text(credentialSummary)
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
        .onAppear {
            // [T-115-quota] Fetch the instance quota once per row appearance
            // (cached 5 min; UI updates via quotaService.revision).
            quotaService.refreshAllIfNeeded(instances: [instance])
        }
    }

    /// `static` (was an instance method) so the credential-cache probe closure can
    /// call it without capturing `self`. Pure function — no behaviour change.
    private static func maskKey(_ key: String) -> String {
        guard key.count > 8 else { return "****" }
        return String(key.prefix(6)) + "..." + String(key.suffix(4))
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
