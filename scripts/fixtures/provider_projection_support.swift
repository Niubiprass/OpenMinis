// Test-only field shapes; production projection/cache/count/accessors are
// extracted verbatim by test_provider_list_20261115.py (no Python model).
import Foundation
#if canImport(Combine)
import Combine
#else
@propertyWrapper struct Published<Value> { var wrappedValue: Value }
#endif
struct ProviderInstance { let id: String }
struct ProjectionBaseModel {
    let id: String
    let isVoiceCandidate: Bool
    let isVoiceInputCandidate: Bool
    let isVoiceOutputCandidate: Bool
}
struct ProjectionOverrides { var name: String? = nil }
struct ModelEntry {
    let providerInstanceId: String
    let baseModel: ProjectionBaseModel
    var isHidden: Bool = false
    var userModifiedAt: Date? = nil
    var overrides = ProjectionOverrides()
}
struct ProviderConfig {
    var instances: [ProviderInstance] = []
    var modelEntries: [ModelEntry] = []
    static let empty = ProviderConfig()
}
