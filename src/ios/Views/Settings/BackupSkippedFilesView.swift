import SwiftUI

/// The files a backup left out, and which conversation each came from.
///
/// The summary could only say "64 file(s)". That answers "how many" and never
/// "which ones" — so a user could not tell whether the cap had quietly dropped
/// something they cared about or a pile of incidental scratch files. Deciding
/// whether to raise the limit needs the names and the sizes.
///
/// Grouped by conversation because that is how the files are organised in the
/// user's head; a flat list of 500 filenames is not browsable.
struct BackupSkippedFilesView: View {
    let record: BackupHistory.Record

    private struct Group: Identifiable {
        let id: String
        let title: String
        let entries: [BackupHistory.SkippedEntry]
        var bytes: Int64 { entries.reduce(0) { $0 + $1.size } }
    }

    /// Conversations first (ordered by how much they contributed), then
    /// everything else. Sorting by total bytes puts the reason the package is
    /// incomplete at the top.
    private var groups: [Group] {
        var byKey: [String: [BackupHistory.SkippedEntry]] = [:]
        for e in record.skippedEntries {
            let parts = e.path.split(separator: "/")
            let key: String
            if parts.count > 1, parts[0] == "chats" {
                key = e.sessionTitle ?? String(parts[1])
            } else {
                key = parts.first.map(String.init) ?? "other"
            }
            byKey[key, default: []].append(e)
        }
        return byKey
            .map { Group(id: $0.key, title: $0.key,
                         entries: $0.value.sorted { $0.size > $1.size }) }
            .sorted { $0.bytes > $1.bytes }
    }

    private var shownCount: Int { record.skippedEntries.count }

    var body: some View {
        List {
            Section {

            ForEach(groups) { group in
                Section {
            }
        }
        .navigationTitle("Excluded Files")
        .navigationBarTitleDisplayMode(.inline)
    }
}
