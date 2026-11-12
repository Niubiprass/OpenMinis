import SwiftUI
import KWWKAI

/// iOS 15 compatible. Consent precedes even the first auth-state request.
struct SubscriptionLoginSheet: View {
    let instanceId: String
    let providerType: ProviderType
    let onComplete: (Bool) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var running = false
    @State private var task: Task<Void, Never>?
    @State private var errorText: String?
    @State private var finished = false
    @State private var acceptedRisk = false

    var body: some View {
        NavigationView {
            List {
                Section {
                    Text(providerType.displayName).font(.title2)
                    Text("这是非官方客户端适配，服务商可能限制第三方调用或调整登录接口。登录成功不代表额度充足，也不代表所有模型都可调用。")
                    Text("登录凭据保存在系统钥匙串；关闭登录窗口或点击取消会停止本次登录。取消不会移除原来已经保存的账号。")
                }
                if providerType == .traeCN {
                    Section(header: Text("请先确认账号信息发往哪里")) {
                        Text("此 Trae 适配来自你提供的源码。登录与续期使用 www.trae.cn / api.trae.cn，但聊天和模型列表使用 trae-api-cn.mchost.guru。这个地址不是 trae.cn 域名，我们尚未验证它是否由 Trae 官方控制。")
                        Text("如果继续并使用聊天，这个服务地址会收到你的访问凭据、聊天内容和工具定义。不要在不能信任该地址时登录或使用此适配。")
                        Toggle("我已核对并愿意使用这个服务地址", isOn: $acceptedRisk)
                            .disabled(running)
                    }
                } else {
                    Section {
                        Text("使用国内 WorkBuddy / CodeBuddy 账号，订阅和积分由服务商按你的账号计算；不支持国际版账号。")
                        Toggle("我了解非官方接入风险并继续", isOn: $acceptedRisk)
                            .disabled(running)
                    }
                }
                Section {
                    if running {
                        ProgressView("等待浏览器登录完成…")
                        Text("请在浏览器完成登录。最长等待五分钟；不需要把密码或 Token 发给 AI。")
                    } else {
                        Button("打开官方登录页") { start() }
                            .disabled(!acceptedRisk)
                    }
                    if let errorText { Text(errorText).foregroundColor(.red) }
                    Button("取消", role: .cancel) { cancel() }
                }
            }
            .navigationTitle("登录 \(providerType.displayName)")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar { ToolbarItem(placement: .cancellationAction) { Button("取消") { cancel() } } }
        }
        .navigationViewStyle(.stack)
        .interactiveDismissDisabled(running)
        .onDisappear {
            task?.cancel()
            SubscriptionOAuthManager.shared.cancelLogin(instanceId: instanceId)
            if !finished { finished = true; onComplete(false) }
        }
    }

    @MainActor private func start() {
        guard acceptedRisk, !running, !finished else { return }
        running = true
        errorText = nil
        task = Task { @MainActor in
            do {
                try await SubscriptionOAuthManager.shared.login(instanceId: instanceId, type: providerType)
                try Task.checkCancellation()
                guard !finished else { return }
                finished = true
                running = false
                onComplete(true)
                dismiss()
            } catch {
                running = false
                if error is CancellationError || (error as? OAuthLoginError) == .cancelled {
                    errorText = "登录已取消，可以重新开始。"
                } else if (error as? OAuthLoginError) == .timedOut {
                    errorText = "登录等待超时，请重新开始。"
                } else if let local = error as? SubscriptionProviderError {
                    errorText = local.localizedDescription
                } else {
                    // Never put provider raw JSON, URLs, access/refresh tokens
                    // or callback parameters into the sign-in card.
                    errorText = "登录未完成。请检查网络、账号地区及订阅状态后重试。"
                }
            }
        }
    }

    @MainActor private func cancel() {
        task?.cancel()
        SubscriptionOAuthManager.shared.cancelLogin(instanceId: instanceId)
        guard !finished else { return }
        finished = true
        onComplete(false)
        dismiss()
    }
}
