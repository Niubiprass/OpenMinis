// >>>IOS15PORTED>>>
import SwiftUI

private let logger = AppLogger(category: "Backup")

/// Choose where backups go.
///
/// Replaces the earlier pair of buttons ("Add Folder…" / "Add Server…"), which
/// asked the user to pick a MECHANISM before they knew what was on offer — and
/// hid servers they had already configured behind the wrong one of the two.
///
/// This shows, in one place:
///   1. servers already set up — the common case is reusing one, not making
///      another
///   2. add a new server (SMB / WebDAV / SFTP / S3 / FTP)
///   3. add a local or Files-connected folder
///
/// Saved servers come first deliberately: someone who typed in a NAS address
/// once should not have to re-enter it to point a second backup at it.
struct BackupDestinationPicker: View {

    /// Called after anything is added or selected, so the caller can refresh.
    var onChanged: () -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var remotes: [RcloneRemoteStore.Remote] = []
    @State private var folders: [MountedFolderEntry] = []
    @State private var showAddServer = false
    @State private var showFolderPicker = false
    @State private var errorText: String?

    var body: some View {
        NavigationView {
            Form {
                if !remotes.isEmpty || !folders.isEmpty {
                    savedSection
                }
                addSection

                if let errorText {
                    Section {
                        Text(errorText)
                            .font(.footnote)
                            .foregroundStyle(.red)
                    }
                }
            }
            .navigationTitle("Backup Destination")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(isPresented: $showAddServer) {
                RcloneAddServerView {
                    reload()
                    onChanged()
                }
            }
            .sheet(isPresented: $showFolderPicker) {
                BackupFolderPicker { url in
                    do {
                        _ = try BackupDestinations.addDestination(pickedURL: url)
                        reload()
                        onChanged()
                    } catch {
                        errorText = error.localizedDescription
                    }
                }
            }
            .onAppear(perform: reload)
        }
    }

    // MARK: - Already configured

    private var savedSection: some View {
        Section {
            Text("Backups are copied to the enabled destinations. Tap for details, or swipe to remove.")
        }
    }

    // MARK: - Adding

    private var addSection: some View {
        Section {
    }

    // MARK: - Helpers

    private func icon(_ name: String, _ colour: Color) -> some View {
        Image(systemName: name)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(.white)
            .frame(width: 28, height: 28)
            .background(colour, in: Circle())
    }

    private func reload() {
        remotes = RcloneRemoteStore.remotes
        folders = BackupDestinations.eligibleFolders
        errorText = nil
    }
}
