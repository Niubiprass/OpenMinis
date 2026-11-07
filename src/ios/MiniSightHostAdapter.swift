import Combine
import Foundation
import SwiftUI

/// The only MiniSight-owned file that references host application types.
/// When OpenMinis changes its lock/approval UI, adapt here; do not fork the core.
@MainActor
final class MiniSightHostState: ObservableObject {
    @Published private(set) var appIsLocked: Bool
    private var lockSubscription: AnyCancellable?

    init() {
        appIsLocked = SessionLockStore.shared.appIsLocked
        lockSubscription = SessionLockStore.shared.$appIsLocked
            .removeDuplicates()
            .receive(on: DispatchQueue.main)
            .sink { [weak self] value in self?.appIsLocked = value }
    }
}

enum MiniSightModule {
    static let version = "0.8.2-local.1"
    static let protocolVersion = 1
}

@MainActor
enum MiniSightHostAdapter {
    static func confirm(command: String) async -> Bool {
        await MCPApprovalDialog.confirm(command)
    }

    static func commandTitle(_ command: String) -> String {
        AIChatViewModel.describeMCPCommand(command).title
    }
}
