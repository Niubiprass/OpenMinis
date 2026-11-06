import Foundation

/// Describes content shared into the app via the Share Extension or Open In.
/// The App Group's atomic JSON manifest is the transfer source of truth.
struct PendingShare: Codable, Equatable {
    let items: [Item]
    let timestamp: Date

    struct Item: Codable, Equatable {
        let kind: Kind
        /// Inline text/URL, or a basename (never a path) in ShareExtension/.
        let value: String
        /// Optional for old manifests. New transfers get stable per-item IDs so
        /// consuming/rolling back A cannot erase B, even when their text matches.
        let id: UUID?

        init(kind: Kind, value: String, id: UUID? = nil) {
            self.kind = kind
            self.value = value
            self.id = id
        }

        enum Kind: String, Codable {
            case inlineText
            case attachment
        }
    }

    var attachmentNames: [String] {
        items.filter { $0.kind == .attachment }.map(\.value)
    }

    func assigningItemIDs() -> PendingShare {
        PendingShare(items: items.map {
            Item(kind: $0.kind, value: $0.value, id: $0.id ?? UUID())
        }, timestamp: timestamp)
    }
}

/// Kept in an existing both-target file; no target-membership change required.
enum SharePipelineError: LocalizedError {
    case appGroupUnavailable
    case timedOut
    case cancelled
    case unsupported
    case provider(String)
    case fileIO(String)
    case manifest(String)

    var errorDescription: String? {
        switch self {
        case .appGroupUnavailable:
            return "无法访问共享 App Group。请检查 Minis 与分享扩展的签名/权限后重新分享。"
        case .timedOut:
            return "导入超时。请先在照片或文件 App 下载原文件，再重试分享。"
        case .cancelled:
            return "已取消导入。"
        case .unsupported:
            return "无法读取此分享内容；文件夹请先压缩，文件请从文件 App 重新分享。"
        case .provider(let detail):
            return "来源 App 未提供可读取内容：\(detail)。请下载原文件后重试。"
        case .fileIO(let detail):
            return "无法读取或保存文件：\(detail)。请检查文件权限与剩余空间后重试。"
        case .manifest(let detail):
            return "无法保存待分享记录：\(detail)。请检查共享权限与剩余空间，稍后重试。"
        }
    }
}

/// A continuation race, NOT a task-group race. Finishing never waits for a
/// provider, an unstructured Task.value, or its cancellation handler. A late
/// callback must claim the gate before doing I/O and discard its own staged
/// result if the deadline wins while it is copying.
final class ShareCompletion<Value>: @unchecked Sendable {
    private let lock = NSLock()
    private var completed = false
    private var callbackClaimed = false
    private var cancelled = false
    private var timedOut = false
    private var result: Value?
    private var waiter: CheckedContinuation<Value, Never>?
    private var timer: DispatchWorkItem?
    private var cancellation: (() -> Void)?

    var isFinished: Bool {
        lock.lock()
        defer { lock.unlock() }
        return completed
    }

    var didTimeOut: Bool {
        lock.lock()
        defer { lock.unlock() }
        return timedOut
    }

    func claimCallback() -> Bool {
        lock.lock()
        defer { lock.unlock() }
        guard !completed, !callbackClaimed else { return false }
        callbackClaimed = true
        return true
    }

    func setCancellation(_ action: @escaping () -> Void) {
        lock.lock()
        let cancelNow = completed && cancelled
        if !completed { cancellation = action }
        lock.unlock()
        // Progress.cancel() may itself invoke provider code. Never let it
        // extend the deadline or run under our state lock.
        if cancelNow { DispatchQueue.global(qos: .utility).async(execute: action) }
    }

    func armTimeout(after seconds: TimeInterval, returning value: Value) {
        let timeout = seconds.isFinite ? max(0, seconds) : 0
        let work = DispatchWorkItem { [weak self] in
            guard let self else { return }
            self.lock.lock()
            self.timedOut = true
            self.lock.unlock()
            self.finish(value, cancelling: true)
        }
        lock.lock()
        guard !completed else { lock.unlock(); return }
        timer = work
        lock.unlock()
        DispatchQueue.global(qos: .utility).asyncAfter(deadline: .now() + timeout, execute: work)
    }

    @discardableResult
    func finish(_ value: Value, cancelling: Bool = false) -> Bool {
        lock.lock()
        guard !completed else { lock.unlock(); return false }
        completed = true
        cancelled = cancelling
        result = value
        let continuation = waiter
        waiter = nil
        let pendingTimer = timer
        timer = nil
        let action = cancelling ? cancellation : nil
        cancellation = nil
        lock.unlock()
        pendingTimer?.cancel()
        continuation?.resume(returning: value)
        if let action { DispatchQueue.global(qos: .utility).async(execute: action) }
        return true
    }

    func wait() async -> Value {
        await withCheckedContinuation { continuation in
            lock.lock()
            if completed, let value = result {
                lock.unlock()
                continuation.resume(returning: value)
            } else {
                precondition(waiter == nil, "ShareCompletion has only one waiter")
                waiter = continuation
                lock.unlock()
            }
        }
    }
}
