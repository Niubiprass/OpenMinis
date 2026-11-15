// Only service/model dependencies are stubbed. All modified SwiftUI view and
// cache declarations are extracted verbatim from production by the runner.
import SwiftUI
import UIKit
import Combine

struct ProviderInstance: Identifiable, Sendable {
    let id: String
    let label: String
    let providerType: ProviderType
    let credentialType: ProviderCredential
    let allowsEmptyAPIKey: Bool
    let isEnabled: Bool
    var subscriptionAccountIds: [String]? = nil
    var subscriptionActiveAccountId: String? = nil
}
struct ModelEntry { let providerInstanceId: String; let isHidden: Bool }
struct ProviderConfig { var modelEntries: [ModelEntry] }
@MainActor final class ProviderConfigStore: ObservableObject {
    static let shared = ProviderConfigStore()
    @Published var instances: [ProviderInstance] = []
    @Published var authRevision: UInt = 0
    var config = ProviderConfig(modelEntries: [])
    var reorderedIDs: [String] = []
    func reorderInstances(_ ids: [String]) { reorderedIDs = ids }
    func instance(for id: String) -> ProviderInstance? { instances.first { $0.id == id } }
    // COUNT_METHOD
}
final class ProviderQuotaService: ObservableObject {
    static let shared = ProviderQuotaService()
    @Published var revision = 0
    struct QuotaInfo {
        let displayText: String
        let highlighted: Bool
        enum Kind { case used, balance }
        let kind: Kind
    }
    func cachedQuota(instanceId: String) -> QuotaInfo? { nil }
    func refreshAllIfNeeded(instances: [ProviderInstance]) {}
}
struct ProviderInstanceDetailView: View {
    let instanceId: String
    var body: some View { Text(instanceId) }
}
