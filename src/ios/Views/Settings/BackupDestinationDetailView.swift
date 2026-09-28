// >>>IOS15PORTED>>>
import SwiftUI

private let logger = AppLogger(category: "Backup")

/// Details of one backup destination.
///
/// Reached by tapping a row in either destination list. Answers the questions a
/// row cannot: what exactly was configured, is it reachable right now, and what
/// is already stored there.
///
/// The password is deliberately NOT shown or offered for editing. It lives in
/// the Keychain and nothing needs to read it back — displaying it would create
/// a second place for it to leak from, to no benefit. Getting it wrong is
/// handled by removing the server and adding it again.
struct BackupDestinationDetailView: View {

    enum Target {
        case remote(RcloneRemoteStore.Remote)
        case folder(MountedFolderEntry)
    }

    let target: Target
    var onChanged: () -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var isTesting = false
    @State private var testResult: String?
    @State private var testOK = false
    @State private var packages: [RcloneTransfer.RemotePackage] = []
    @State private var isLoadingPackages = false
    /// Live copy of the remote, so edits are reflected without leaving.
    @State private var edited: RcloneRemoteStore.Remote?
    @State private var showRename = false
    @State private var draftName = ""
    @State private var showFolderBrowser = false
    @State private var showDeleteConfirm = false
    @State private var showConnectionEditor = false
    @State private var errorText: String?
    /// [T-backup-remote-delete] Package awaiting delete confirmation. Held as
    /// the item itself (not a bool) so the alert can name the file and the
    /// action cannot be applied to a different row if the list reloads.
    @State private var pendingDelete: RcloneTransfer.RemotePackage?
    @State private var isDeleting = false

    /// [T-backup-folder-delete] The folder equivalent of `pendingDelete`, and
    /// separate from it because the two lists hold different types — a server
    /// package is an `RcloneTransfer.RemotePackage` addressed through rclone,
    /// a folder one is a `FoundPackage` with a real file URL.
    @State private var pendingFolderDelete: BackupDestinations.FoundPackage?
    /// Packages in the folder destination. Loaded in a `.task` rather than
    /// computed in `body`: the listing enumerates a mounted directory, which
    /// on a NAS or a cloud provider is real I/O, and doing that inside a view
    /// body blocks the main thread on every redraw.
    @State private var folderPackages: [BackupDestinations.FoundPackage] = []

    var body: some View {
        Form {
            switch target {
            case .remote(let r): remoteSections(r)
            case .folder(let f): folderSections(f)
            }
        }
        .navigationTitle(title)
        .navigationBarTitleDisplayMode(.inline)
        // These MUST hang off the Form, not off a Section inside
        // remoteSections. That builder re-runs whenever the package list
        // finishes loading (isLoadingPackages / packages change), and a
        // presentation modifier attached to a view that gets rebuilt is torn
        // down with it — the sheet opened and then closed itself. Only
        // reproducible on FIRST entry, because that is when the load is still
        // in flight; afterwards the state had already settled.
        .alert("Rename Destination", isPresented: $showRename) {
        .sheet(isPresented: $showConnectionEditor) {
            if let r = activeRemote {
                RcloneConnectionEditor(remote: r) { updated in
                    showConnectionEditor = false
                    edited = updated
                    onChanged()
                }
            }
        }
        .sheet(isPresented: $showFolderBrowser) {
            if let r = activeRemote {
                RcloneFolderBrowser(remote: r) { newPath in
                    showFolderBrowser = false
                    applyPath(r, newPath)
                }
            }
        }
        .confirmationDialog("Remove this destination?",
        // [T-backup-remote-delete] Deleting the FILE, not the destination.
        // `item:` rather than a bool so the message can name the package —
        // a list of `backup-<date>-<hex>.minisbak` all look alike, and the
        // user has to see which one they are about to lose.
        .alert(item: $pendingDelete) { pkg in
            Alert(
                title: Text(AppLocalized("Delete this backup file?")),
                // Names the file, states its size, and says plainly that the
                // data is gone. A list of near-identical package names makes
                // the wrong-row mistake easy, and the size is the cheapest
                // way to notice that the file about to go is the big one.
                message: Text(String(
                    format: AppLocalized("“%1$@” (%2$@) will be permanently deleted from this server. There is no trash to recover it from, and any data only in this backup will be lost. This cannot be undone."),
                    pkg.displayName,
                    ByteCountFormatter.string(fromByteCount: pkg.size, countStyle: .file))),
                primaryButton: .destructive(Text(AppLocalized("Delete Backup"))) {
                    Task { await deletePackage(pkg) }
                },
                secondaryButton: .cancel(Text(AppLocalized("Cancel")))
            )
        }
        // [T-backup-folder-delete] Same treatment for a folder destination.
        // Worded for a folder rather than a server, because "deleted from this
        // server" would be wrong for a local or iCloud Drive directory.
        .alert(item: $pendingFolderDelete) { pkg in
            Alert(
                title: Text(AppLocalized("Delete this backup file?")),
                message: Text(String(
                    format: AppLocalized("“%1$@” (%2$@) will be permanently deleted from this folder. There is no trash to recover it from, and any data only in this backup will be lost. This cannot be undone."),
                    pkg.url.lastPathComponent,
                    ByteCountFormatter.string(fromByteCount: pkg.size, countStyle: .file))),
                primaryButton: .destructive(Text(AppLocalized("Delete Backup"))) {
                    Task { await deleteFolderPackage(pkg) }
                },
                secondaryButton: .cancel(Text(AppLocalized("Cancel")))
            )
        }
    }

    /// [T-backup-remote-delete] Remove one package from the server, then
    /// refresh so the list reflects the server rather than our assumption.
    private func deletePackage(_ pkg: RcloneTransfer.RemotePackage) async {
        guard let r = activeRemote else { return }
        isDeleting = true
        defer { isDeleting = false }
        do {
            RcloneRemoteStore.syncToRclone()
            try await Task.detached(priority: .utility) {
                try RcloneTransfer.deletePackage(pkg, from: r)
            }.value
            await loadPackages(r)
        } catch {
            // Surfaced, not swallowed: a failed delete that silently drops the
            // row would tell the user the file is gone when it is still there.
            errorText = error.localizedDescription
        }
    }

    /// [T-backup-folder-delete] List the packages in a folder destination.
    ///
    /// Detached because enumerating a mounted directory is real I/O — the
    /// folder may be a NAS or a cloud provider that has to be woken — and this
    /// used to run synchronously inside `body`, blocking the main thread on
    /// every redraw of the screen.
    private func loadFolderPackages(_ f: MountedFolderEntry) async {
        let id = f.id
        folderPackages = await Task.detached(priority: .userInitiated) {
            BackupDestinations.listPackages(folderId: id)
        }.value
    }

    /// [T-backup-folder-delete] Delete one package from a folder destination.
    ///
    /// Goes through `MountedFolderCoordinator.remove` rather than
    /// `FileManager.removeItem`: the file may live under a mount owned by a
    /// FileProvider, where an uncoordinated delete either fails or races the
    /// provider. `remove` also enforces the mount's writability, so a
    /// read-only destination reports an error instead of appearing to work.
    private func deleteFolderPackage(_ pkg: BackupDestinations.FoundPackage) async {
        guard case .folder(let f) = target else { return }
        isDeleting = true
        defer { isDeleting = false }
        do {
            let url = pkg.url
            try await Task.detached(priority: .utility) {
                try MountedFolderCoordinator.remove(at: url)
            }.value
            await loadFolderPackages(f)
        } catch {
            // Surfaced, not swallowed: a failed delete that silently drops the
            // row would tell the user the file is gone when it is still there.
            errorText = error.localizedDescription
        }
    }

    /// The remote as it currently stands — the edited copy once something has
    /// been changed, otherwise the one this view was opened with.
    private var activeRemote: RcloneRemoteStore.Remote? {
        if let edited { return edited }
        if case .remote(let r) = target { return r }
        return nil
    }

    private var title: String {
        switch target {
        case .remote(let r): return r.name
        case .folder(let f): return f.name
        }
    }

    // MARK: - Server

    @ViewBuilder
    private func remoteSections(_ r: RcloneRemoteStore.Remote) -> some View {
        let current = edited ?? r
        Section {
            Text("Tap the name or folder to change them, or edit the connection to change the address and password.")
        }

        if let errorText {
            Section {
                Text(errorText).font(.footnote).foregroundStyle(.red)
            }
        }

        Section {

        Section {
            // The gesture is invisible until tried, and what it does here is
            // irreversible — so it is stated rather than left to be
            // discovered by someone swiping to see what happens.
            if !packages.isEmpty {
                Text("Swipe a backup left to delete it. Deleted backup files cannot be recovered.")
            }
        }

        .task { await loadPackages(r) }
    }

    private func rename(_ r: RcloneRemoteStore.Remote) {
        errorText = nil
        do {
            edited = try RcloneRemoteStore.update(name: r.name, newName: draftName)
            onChanged()
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func applyPath(_ r: RcloneRemoteStore.Remote, _ path: String) {
        errorText = nil
        do {
            edited = try RcloneRemoteStore.update(name: r.name, newPath: path)
            onChanged()
            Task { await loadPackages(edited ?? r) }
        } catch {
            errorText = error.localizedDescription
        }
    }

    // MARK: - Folder

    @ViewBuilder
    private func folderSections(_ f: MountedFolderEntry) -> some View {
        Section {
            // Says where the folder really lives, since the same row could be
            // a local directory or a server mounted in Files.
            Text("Folders come from the Files app — on this iPhone, iCloud Drive, or a connected server.")
        }

        Section {
            // The gesture is invisible until tried, and what it does here is
            // irreversible — so it is stated rather than left to be
            // discovered by someone swiping to see what happens.
            if !folderPackages.isEmpty {
                Text("Swipe a backup left to delete it. Deleted backup files cannot be recovered.")
            }
        }
        .task(id: f.id) { await loadFolderPackages(f) }
    }

    // MARK: - Actions

    private func test(_ r: RcloneRemoteStore.Remote) async {
        isTesting = true
        testResult = nil
        defer { isTesting = false }
        RcloneRemoteStore.syncToRclone()
        do {
            _ = try await Task.detached(priority: .userInitiated) {
                try RcloneBridge.rpc("operations/list",
                                     ["fs": RcloneRemoteStore.fsSpec(for: r),
                                      "remote": r.path])
            }.value
            testOK = true
            testResult = AppLocalized("Connected.")
        } catch {
            testOK = false
            testResult = error.localizedDescription
        }
    }

    private func loadPackages(_ r: RcloneRemoteStore.Remote) async {
        isLoadingPackages = true
        defer { isLoadingPackages = false }
        RcloneRemoteStore.syncToRclone()
        packages = (try? await Task.detached(priority: .utility) {
            try RcloneTransfer.listPackages(remote: r)
        }.value) ?? []
    }

    private func detail(for p: RcloneTransfer.RemotePackage) -> String {
        let size = ByteCountFormatter.string(fromByteCount: p.size, countStyle: .file)
        var parts = [size]
        if let m = p.modified {
            parts.append(m.formatted(date: .abbreviated, time: .shortened))
        }
        return parts.joined(separator: " · ")
    }

    /// rclone's parameter names are terse; show the label the user actually saw
    /// when adding the server.
    private func fieldLabel(_ key: String, backend: String) -> String {
        RcloneBackendCatalog.backend(for: backend)?
            .fields.first { $0.key == key }?.label ?? key
    }

    /// Whether a stored param still corresponds to a field of this backend.
    ///
    /// Params outlive the form: removing a field leaves the key in every
    /// remote already saved with it. Those rows would otherwise render with
    /// the raw rclone key as their label and imply a live setting.
    private func isShownField(_ key: String, backend: String) -> Bool {
        RcloneBackendCatalog.backend(for: backend)?
            .fields.contains { $0.key == key } ?? true
    }
}

// MARK: - Folder browser (re-pointing an existing destination)

/// Browse a configured remote and pick a different backup folder.
///
/// The add-server flow has its own browser embedded in its step sequence;
/// this is the same job for a server that already exists, which is why it is
/// a standalone sheet rather than a reuse of that view — that one is bound to
/// the multi-step "connectedRemote" state and cannot be entered part-way.
struct RcloneFolderBrowser: View {
    let remote: RcloneRemoteStore.Remote
    /// Show files alongside folders.
    ///
    /// Off when choosing a DESTINATION: a backups directory on a NAS can hold
    /// hundreds of files, and every one of them is an un-tappable row pushing
    /// the folders the user is actually navigating off the screen. On when
    /// choosing a FILE (picking a package to restore), where the files are
    /// the point.
    var showsFiles: Bool = false
    var onPicked: (String) -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var currentDir = ""
    @State private var entries: [Entry] = []
    @State private var isListing = false
    @State private var errorText: String?
    @State private var showNewFolder = false
    @State private var newFolderName = ""

    struct Entry: Identifiable {
        var id: String { path }
        let name: String
        let path: String
        let isDir: Bool
    }

    var body: some View {
        NavigationView {
            Form {
                Section {

            }
            .backupHUD($errorText)
            .navigationTitle("Backup Folder")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save Here") { onPicked(currentDir) }
                        .disabled(isListing)
                }
            }
            .alert("New Folder", isPresented: $showNewFolder) {
            // Start where the destination currently points, so "change the
            // folder" begins from the folder in use rather than the root.
            .task { await list(remote.path) }
        }
    }

    /// Folders first; files only when the caller asked for them.
    private var visibleEntries: [Entry] {
        showsFiles ? entries : entries.filter(\.isDir)
    }

    private func list(_ dir: String) async {
        isListing = true
        errorText = nil
        defer { isListing = false }
        let r = remote
        do {
            let out = try await Task.detached(priority: .userInitiated) {
                try RcloneBridge.rpc("operations/list",
                                     ["fs": RcloneRemoteStore.fsSpec(for: r), "remote": dir])
            }.value
            entries = ((out["list"] as? [[String: Any]]) ?? []).compactMap { e in
                guard let name = e["Name"] as? String else { return nil }
                return Entry(name: name,
                             path: dir.isEmpty ? name : "\(dir)/\(name)",
                             isDir: (e["IsDir"] as? Bool) ?? false)
            }
            .sorted { $0.name.lowercased() < $1.name.lowercased() }
            currentDir = dir
        } catch {
            errorText = error.localizedDescription
        }
    }

    private func createFolder() async {
        let name = newFolderName.trimmingCharacters(in: .whitespaces)
        newFolderName = ""
        guard !name.isEmpty else { return }
        guard !name.contains("/") else {
            errorText = AppLocalized("A folder name can't contain “/”.")
            return
        }
        // The top level of an SMB remote is its list of SHARES, and a share
        // can't be created over the protocol — rclone's mkdir there reports
        // success and makes nothing, after which navigating "into" it shows an
        // empty folder that vanishes on the next listing. Say so instead.
        guard !(remote.backend == "smb" && currentDir.isEmpty) else {
            errorText = AppLocalized("New folders go inside a shared folder. Open one first, then add a folder in it.")
            return
        }
        let path = currentDir.isEmpty ? name : "\(currentDir)/\(name)"
        let r = remote
        do {
            _ = try await Task.detached(priority: .userInitiated) {
                try RcloneBridge.rpc("operations/mkdir", [
                    "fs": RcloneRemoteStore.fsSpec(for: r), "remote": path,
                ])
            }.value
            await list(path)
        } catch {
            errorText = error.localizedDescription
        }
    }
}

// MARK: - Connection editor

/// Edit an existing server's address and password.
///
/// Saving runs a connection test FIRST and refuses to persist values that
/// don't work. That is the whole reason editing was withheld at first: a
/// server whose host was changed to something wrong looks configured and then
/// fails at backup time, far from the edit that caused it. Testing before
/// saving removes the objection instead of removing the capability.
///
/// The password field starts empty and is only written when something is
/// typed — leaving it alone keeps the stored credential, which is what a user
/// changing only a hostname expects. Clearing it explicitly (via the toggle)
/// is how a server becomes anonymous.
struct RcloneConnectionEditor: View {
    let remote: RcloneRemoteStore.Remote
    var onSaved: (RcloneRemoteStore.Remote?) -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var values: [String: String] = [:]
    @State private var secret = ""
    @State private var clearSecret = false
    @State private var isTesting = false
    @State private var errorText: String?

    private var backend: RcloneBackendCatalog.Backend? {
        RcloneBackendCatalog.backend(for: remote.backend)
    }

    var body: some View {
        NavigationView {
            Form {
                if let b = backend {
                    Section {

                    if b.fields.contains(where: \.isSecret) {
                        Section {
                            Text(clearSecret
                                 ? "The stored password will be removed."
                                 : "Leave blank to keep the current password.")
                        }
                    }
                }

                if let errorText {
                    Section {
                        Text(errorText).font(.footnote).foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Edit Connection")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    if isTesting {
                        ProgressView()
                    } else {
                        Button("Save") { Task { await save() } }
                    }
                }
            }
            .onAppear { values = remote.params }
        }
    }

    private func binding(for key: String) -> Binding<String> {
        Binding(get: { values[key] ?? "" }, set: { values[key] = $0 })
    }

    /// Apply, then verify. On failure the previous configuration is put back,
    /// so a failed edit leaves a working destination rather than a broken one.
    private func save() async {
        isTesting = true
        errorText = nil
        defer { isTesting = false }

        let previousParams = remote.params
        do {
            let updated = try RcloneRemoteStore.update(
                name: remote.name,
                newParams: values,
                newSecret: clearSecret ? "" : (secret.isEmpty ? nil : secret))
            guard let updated else { dismiss(); return }

            _ = try await Task.detached(priority: .userInitiated) {
                try RcloneBridge.rpc("operations/list", [
                    "fs": RcloneRemoteStore.fsSpec(for: updated),
                    "remote": updated.path,
                ])
            }.value
            onSaved(updated)
            dismiss()
        } catch {
            // Roll the connection fields back; the secret is left as typed
            // because re-entering it is the more likely intent after a
            // failure, and it cannot be read back to restore anyway.
            _ = try? RcloneRemoteStore.update(name: remote.name, newParams: previousParams)
            errorText = AppLocalized("Couldn't connect with these settings, so they weren't saved. \(error.localizedDescription)")
        }
    }

    private func keyboardType(_ k: RcloneBackendCatalog.Field.KeyboardKind) -> UIKeyboardType {
        switch k {
        case .default: return .default
        case .url: return .URL
        case .numeric: return .numberPad
        case .email: return .emailAddress
        }
    }
}
