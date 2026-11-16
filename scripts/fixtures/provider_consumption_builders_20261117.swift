enum FactoryError: Error { case noInstance, noCredentials, voiceOnlyProvider }
static func frozen(_ instance: ProviderInstance, _ override: String?) -> String {
    override ?? ProviderKeychainHelper.loadAPIKey(instanceId: instance.id) ?? ""
}
static func makeAnthropicProvider(instance: ProviderInstance, model: LLMModel, apiKeyOverride: String? = nil) -> AnthropicProvider {
    AnthropicProvider(apiKey: frozen(instance, apiKeyOverride), model: model)
}
static func makeGeminiProvider(instance: ProviderInstance, model: LLMModel, apiKeyOverride: String? = nil) async -> GeminiProvider {
    GeminiProvider(apiKey: frozen(instance, apiKeyOverride), model: model)
}
static func makeOpenAIProvider(instance: ProviderInstance, model: LLMModel, apiKeyOverride: String? = nil) -> OpenAIProvider {
    OpenAIProvider(apiKey: frozen(instance, apiKeyOverride), model: model)
}
static func makeOpenRouterProvider(instance: ProviderInstance, model: LLMModel, apiKeyOverride: String? = nil) -> OpenAIProvider {
    makeOpenAIProvider(instance: instance, model: model, apiKeyOverride: apiKeyOverride)
}
static func makeOpenAIResponsesProvider(instance: ProviderInstance, model: LLMModel, apiKeyOverride: String? = nil) -> OpenAIProvider {
    makeOpenAIProvider(instance: instance, model: model, apiKeyOverride: apiKeyOverride)
}
static func makeXAIProvider(instance: ProviderInstance, model: LLMModel, apiKeyOverride: String? = nil) -> OpenAIProvider {
    makeOpenAIProvider(instance: instance, model: model, apiKeyOverride: apiKeyOverride)
}
static func makeKimiProvider(instance: ProviderInstance, model: LLMModel, apiKeyOverride: String? = nil) -> OpenAIProvider {
    makeOpenAIProvider(instance: instance, model: model, apiKeyOverride: apiKeyOverride)
}
static func makeCopilotProvider(instance: ProviderInstance, model: LLMModel) -> OpenAIProvider {
    OpenAIProvider(apiKey: "synthetic-oauth", model: model)
}
static func makeAntigravityProvider(instance: ProviderInstance, model: LLMModel) async -> GeminiProvider {
    GeminiProvider(apiKey: "synthetic-oauth", model: model)
}
static func applyModelOverrides(_ provider: OpenAIProvider, entry: ModelEntry) -> OpenAIProvider { provider }
static func normalizeToOpenAI(_ provider: OpenAIProvider, instance: ProviderInstance) -> OpenAIProvider { provider }
