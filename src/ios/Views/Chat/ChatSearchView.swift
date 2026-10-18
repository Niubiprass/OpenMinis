import SwiftUI

/// [T-115-chat-search] In-chat message search (1.15 "聊天搜索").
///
/// Searches the CURRENT session's persisted messages via
/// `ChatStore.searchMessages` (SQLite LIKE, cross-keyword, snippet extraction —
/// all existing) and reports the chosen hit back to the chat view as a
/// `MessageSearchJump`; the chat view dismisses the sheet and the message list
/// scrolls to the message with a transient highlight.
struct ChatSearchView: View {
    let sessionId: String?
    let onSelect: (MessageSearchJump) -> Void

    @State private var query = ""
    @State private var hits: [Hit] = []
    @State private var searched = false
    @State private var searchTask: Task<Void, Never>?
    @Environment(\.dismiss) private var dismiss

    struct Hit: Identifiable {
        let id: UUID
        let role: String
        let createdAt: Date
        let snippet: String
    }

    var body: some View {
        NavigationView {
            VStack(spacing: 0) {
                searchField
                if query.isEmpty && hits.isEmpty {
                    emptyState
                } else if hits.isEmpty {
                    emptyState
                } else {
                    resultList
                }
            }
            .navigationTitle(AppLocalized("Search Messages"))
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button(AppLocalized("Done")) { dismiss() }
                }
            }
        }
        .navigationViewStyle(.stack)
    }

    // MARK: - Field

    private var searchField: some View {
        HStack(spacing: 8) {
            Image(systemName: "magnifyingglass")
                .foregroundColor(.secondary)
            TextField(AppLocalized("Search current chat…"), text: $query)
                .autocorrectionDisabled()
                .submitLabel(.search)
                .onSubmit { runSearch() }
                .onChange(of: query) { _ in runSearch() }
            if !query.isEmpty {
                Button {
                    query = ""
                    hits = []
                    searched = false
                } label: {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.secondary)
                }
            }
        }
        .padding(10)
        .background(Color(.tertiarySystemFill))
        .cornerRadius(10)
        .padding(.horizontal)
        .padding(.vertical, 10)
    }

    // MARK: - Search

    private func runSearch() {
        searchTask?.cancel()
        searched = true
        let keywords = query.split(separator: " ").map(String.init)
        let sid = sessionId
        guard !keywords.isEmpty else {
            hits = []
            return
        }
        let task = Task {
            let found = await ChatStore.shared.searchMessages(
                sessionIds: sid.map { [$0] },
                keywords: keywords,
                limit: 50
            )
            guard !Task.isCancelled else { return }
            let mapped = found.compactMap { r -> Hit? in
                guard let uuid = UUID(uuidString: r.messageId) else { return nil }
                return Hit(id: uuid, role: r.role, createdAt: r.createdAt, snippet: r.snippet)
            }
            hits = mapped
        }
        searchTask = task
    }

    // MARK: - List

    private var resultList: some View {
        List(hits) { hit in
            Button {
                onSelect(MessageSearchJump(
                    messageId: hit.id,
                    nonce: Int.random(in: 1...Int.max)
                ))
            } label: {
                row(hit)
            }
            .buttonStyle(.plain)
        }
        .listStyle(.insetGrouped)
    }

    private func row(_ hit: Hit) -> some View {
        let isUser = hit.role == "user"
        return HStack(alignment: .top, spacing: 10) {
            ZStack {
                RoundedRectangle(cornerRadius: 9)
                    .fill(isUser ? Color.blue : Color.purple)
                Text(isUser ? AppLocalized("Me") : "AI")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundColor(.white)
            }
            .frame(width: 30, height: 30)
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 3) {
                HStack(spacing: 8) {
                    Text(isUser ? AppLocalized("Me") : "Minis")
                        .font(.footnote.weight(.semibold))
                    Text(Self.timeText(hit.createdAt))
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
                highlightedSnippet(hit.snippet)
                    .font(.subheadline)
                    .foregroundColor(.primary)
                    .lineLimit(3)
            }
        }
        .padding(.vertical, 2)
    }

    /// Snippet with all query keywords tinted orange/bold.
    private func highlightedSnippet(_ snippet: String) -> Text {
        let keywords = query.split(separator: " ").map(String.init)
        guard let first = keywords.first, !first.isEmpty else {
            return Text(snippet)
        }
        var out = Text("")
        var rest = Substring(snippet)
        var guardRail = 0
        while let range = rest.range(of: first, options: [.caseInsensitive]) {
            guard guardRail < 40 else { break }
            guardRail += 1
            if range.lowerBound > rest.startIndex {
                out = out + Text(String(rest[rest.startIndex..<range.lowerBound]))
            }
            out = out + Text(String(rest[range])).foregroundColor(.orange).bold()
            rest = rest[range.upperBound...]
        }
        if !rest.isEmpty {
            out = out + Text(String(rest))
        }
        return out
    }

    // MARK: - Empty state

    private var emptyState: some View {
        VStack(spacing: 10) {
            Image(systemName: "magnifyingglass")
                .font(.largeTitle)
                .foregroundColor(.secondary)
            Text(searched
                 ? AppLocalized("No matching messages")
                 : AppLocalized("Search messages in this chat"))
                .font(.subheadline)
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
        .padding(.bottom, 60)
    }

    // MARK: - Time

    private static let hmFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "HH:mm"
        return f
    }()

    private static let mdhmFormatter: DateFormatter = {
        let f = DateFormatter()
        f.dateFormat = "M月d日 HH:mm"
        return f
    }()

    static func timeText(_ date: Date) -> String {
        let cal = Calendar.current
        let hm = hmFormatter.string(from: date)
        if cal.isDateInToday(date) { return AppLocalized("今天") + " " + hm }
        if cal.isDateInYesterday(date) { return AppLocalized("昨天") + " " + hm }
        return mdhmFormatter.string(from: date)
    }
}