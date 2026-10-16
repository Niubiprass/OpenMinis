// Explicit app-only dependency stubs. All UIKit/SwiftUI types are real.
// These expose identity/cache interfaces; they do NOT reproduce fitting logic.
enum MessageListItem: Hashable {
    case row(Int)
    var scrollDiagnosticID: Int {
        switch self { case .row(let value): return value }
    }
}
final class SelfSizingCell: UICollectionViewCell {
    var scrollDiagnosticID = 1
    var contentKey: String? = "probe"
    var cacheClearCount = 0
    func clearCachedHeight() { cacheClearCount += 1 }
    static func renderQualifiedKey(_ key: String, for cell: UIView) -> String { key }
}
final class MessageListLayout: UICollectionViewFlowLayout {
    var deferSelfSizing = false
    func isStreamingCell(_ index: Int) -> Bool { false }
    func invalidateHeight(at index: Int, discardPrecalc: Bool) {}
    func invalidateMemo(forKey key: String) {}
}
