import Foundation

/// Walks a paginated model list to completion and hands back the rows of every
/// page. A response is only treated as complete when the API says so; a page
/// that advertises another cursor but gives us nothing to follow is an error,
/// not a short list. Callers only replace the visible list after this returns.
///
/// [T-model-refresh-count-is-not-completeness] Providers may return 2 models
/// today and 20 tomorrow; neither count means anything on its own.
struct ModelPage<Item> {
    let items: [Item]
    /// Cursor for the next page, nil on the last page.
    let next: URL?
    /// True when the response said more pages exist, even if no usable cursor
    /// could be built. A missing cursor then fails the whole refresh instead of
    /// quietly accepting page 1.
    let advertisedNext: Bool
}

enum ModelPagination {
    static let maxPages = 100

    /// - Parameter fetch: requests one page and returns its items plus cursor.
    static func collect<Item>(start: URL,
                              fetch: (URL) async throws -> ModelPage<Item>) async throws -> [Item] {
        var url = start
        var items: [Item] = []
        var visited = Set<String>()
        for _ in 0..<maxPages {
            visited.insert(url.absoluteString)
            let page = try await fetch(url)
            if page.advertisedNext {
                if page.items.isEmpty {
                    throw LLMError.providerError(message: "Model list ended early: the response advertised another page but contained no models")
                }
                guard let next = page.next else {
                    throw LLMError.providerError(message: "Model list is incomplete: the response advertised another page but gave no cursor")
                }
                let key = next.absoluteString
                if visited.contains(key) {
                    throw LLMError.providerError(message: "Model list pagination looped at \(key)")
                }
                url = next
                items.append(contentsOf: page.items)
                continue
            }
            items.append(contentsOf: page.items)
            return items
        }
        throw LLMError.providerError(message: "Model list exceeded \(maxPages) pages")
    }

    static func absolute(_ raw: Any?, relativeTo base: URL) -> URL? {
        guard let s = raw as? String else { return nil }
        let t = s.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !t.isEmpty else { return nil }
        return URL(string: t, relativeTo: base)?.absoluteURL
    }
}
