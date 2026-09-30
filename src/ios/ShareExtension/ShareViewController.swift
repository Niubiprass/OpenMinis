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
            let vm = ShareViewModel()
            let items = (extensionContext?.inputItems as? [NSExtensionItem]) ?? []
            NSLog("[ShareExt] inputItems count: %d", items.count)
    // ios15-port IOS15_SHARE_TIMEOUT
    // 之前 await 单个 NSItemProvider 时, 若它在 iOS 15 上不回调, 整个处理会
    // 永久挂住: 分享面板既没反应也不关闭, 主 App 也收不到 minis://share。
    // 这里加 8 秒超时: 超时也要继续走 redirectToHostApp + completeRequest,
    // 至少把主 App 唤起来。
            let saved = await withTaskGroup(of: Bool.self) { group -> Bool in
                group.addTask { @MainActor in
                    await vm.processExtensionItems(items)
                    return vm.save()
                }
                group.addTask {
                    try? await Task.sleep(nanoseconds: 8_000_000_000)
                    return false
                }
                let first = await group.next() ?? false
                group.cancelAll()
                return first
            }
            NSLog("[ShareExt] save() returned: %@", saved ? "true" : "false")

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
