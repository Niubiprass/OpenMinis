import UIKit

/// The Share Extension's principal view controller.
class ShareViewController: UIViewController {

    /// Set to true once async processing + redirect is done, so viewDidAppear can dismiss.
    private var processingDone = false

    override func viewDidLoad() {
        super.viewDidLoad()
        view.backgroundColor = .clear
        NSLog("[ShareExt] viewDidLoad — starting processing")

        Task { @MainActor in
            let items = (extensionContext?.inputItems as? [NSExtensionItem]) ?? []
            NSLog("[ShareExt] inputItems count: %d", items.count)
    // ios15-port IOS15_SHARE_TIMEOUT
    // 之前 await 单个 NSItemProvider 时, 若它在 iOS 15 上不回调, 整个处理会
    // 永久挂住: 分享面板既没反应也不关闭, 主 App 也收不到 minis://share。
    // 现在: 每个 provider 5s 超时 + 整体 20s 兜底, 且处理在后台线程跑。
    // 关键顺序: 先把 PendingShare 写盘, 再唤主 App, 最后才 completeRequest ——
    // 旧实现超时后立刻 completeRequest, 会把仍在复制文件的扩展进程杀掉,
    // 结果就是"分享进来了但什么都没有"。
            let saved = await ShareViewModel.processAndSave(items)
            NSLog("[ShareExt] save() returned: %@", saved ? "true" : "false")

            if !saved {
                // A hung provider won the race; the pipeline is still running and
                // may still land its record. Poll briefly before tearing the
                // extension down, otherwise the copy is lost with the process.
                for _ in 0..<20 {
                    try? await Task.sleep(nanoseconds: 500_000_000)
                    if SharedContainerStore.loadPendingShare() != nil { break }
                }
                NSLog("[ShareExt] post-timeout wait finished, record=%@",
                      SharedContainerStore.loadPendingShare() != nil ? "present" : "absent")
            }

            // Verify what was saved
            if let pending = SharedContainerStore.loadPendingShare() {
                NSLog("[ShareExt] Verified pending share: %d items", pending.items.count)
                for (i, item) in pending.items.enumerated() {
                    NSLog("[ShareExt]   item[%d] kind=%@ value=%@", i, item.kind.rawValue, String(item.value.prefix(100)))
                }
            } else {
                NSLog("[ShareExt] WARNING: loadPendingShare returned nil after save!")
            }

            // Verify shared file directory
            if let dir = SharedContainerStore.sharedFileDirectory {
                let files = (try? FileManager.default.contentsOfDirectory(atPath: dir.path)) ?? []
                NSLog("[ShareExt] Shared file dir: %@ — files: %@", dir.path, files.description)
            } else {
                NSLog("[ShareExt] WARNING: sharedFileDirectory is nil!")
            }

            // Verify sharedDefaults accessible
            if let defaults = SharedContainerStore.sharedDefaults {
                let hasKey = defaults.data(forKey: "pendingShare") != nil
                NSLog("[ShareExt] sharedDefaults accessible, pendingShare key present: %@", hasKey ? "YES" : "NO")
            } else {
                NSLog("[ShareExt] WARNING: sharedDefaults is nil — App Group not configured?")
            }

            redirectToHostApp()

            // Mark done and dismiss — if viewDidAppear already ran, dismiss now
            processingDone = true
            NSLog("[ShareExt] Processing done, completing request")
            extensionContext?.completeRequest(returningItems: [])
        }
    }

    override func viewDidAppear(_ animated: Bool) {
        super.viewDidAppear(animated)
        // Only dismiss if async processing is already done.
        // If not done yet, the Task completion above will dismiss.
        if processingDone {
            NSLog("[ShareExt] viewDidAppear — processingDone, completing request")
            extensionContext?.completeRequest(returningItems: [])
        } else {
            NSLog("[ShareExt] viewDidAppear — processing still in progress, deferring dismiss")
        }
    }

    // MARK: - Redirect to main app

    private func redirectToHostApp() {
        guard let url = URL(string: "minis://share") else {
            NSLog("[ShareExt] ERROR: Failed to create minis://share URL")
            return
        }

        let selectorOpenURL = sel_registerName("openURL:")
        var responder: UIResponder? = self
        var found = false
        while responder != nil {
            if let application = responder as? UIApplication {
                NSLog("[ShareExt] Found UIApplication in responder chain, opening URL")
                if #available(iOS 18.0, *) {
                    application.open(url, options: [:], completionHandler: nil)
                } else {
                    application.perform(selectorOpenURL, with: url)
                }
                found = true
                break
            }
            responder = responder?.next
        }
        if !found {
            NSLog("[ShareExt] WARNING: UIApplication not found in responder chain!")
        }
    }
}
