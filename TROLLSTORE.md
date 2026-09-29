# OpenMinis · 只用手机就能做 iOS 15 的 TrollStore（巨魔）安装包

> **核心结论先说**：你**不需要 Mac、不需要电脑**。OpenMinis 仓库自带 GitHub Actions 云端编译流水线（云端 macOS 自带 Xcode + iOS SDK）。你只要在**手机浏览器**里 fork 仓库 → 点一下运行 → 下载 IPA，全程用手机完成。本沙箱（Linux）也无法替你编译出 IPA，但云端可以。

---

## 0. 这个包能 / 不能做什么

- ✅ 在 **iOS 15.0 – 16.6.1**（以及 iOS 17.0）设备上，通过 TrollStore 永久安装、免签名、免越狱。
- ✅ 核心能力完整：自带多模型、设备内 Alpine Linux 沙盒（iSH）、设备集成、浏览器自动化、Skills、记忆。
- ⚠️ 部分 **iOS 16+ 专属功能在 iOS 15 上会降级**（项目已内置 `iOS15Compat.swift` 兼容层：`NavigationStack`/`NavigationSplitView`/`ShareLink`/`PhotosPickerItem`/`UIHostingConfiguration` 等会自动用 iOS 15 等价实现）。
- ⚠️ **iCloud / CloudKit 同步** 在侧载下不可用（需要开发者账号的 container 授权）。
- ⚠️ **NFC** 相关功能已移除（NFC 是 Apple 受限能力，侧载会导致安装失败）。

> TrollStore 自身支持范围：TrollStore 2 支持 iOS 15.0–16.6.1 与 iOS 17.0。请先确认你的设备系统版本在支持列表内，并已在手机上装好 TrollStore（如用 TrollInstallerX 安装）。

---

## 1. 仓库已为你做好的改动（无需你再改）

| 改动 | 文件 | 说明 |
|------|------|------|
| Deployment Target → **15.0** | `src/ios/Minis.xcodeproj/project.pbxproj` | 主 App、扩展、测试 target 全部降到 15.0（覆盖最宽机型） |
| TrollStore 专用 entitlements | `src/ios/Minis-TrollStore.entitlements` | 保留 HealthKit/HomeKit/WeatherKit/app-groups/iCloud；**新增 JIT 三件套**；**移除** NFC 与受限的 health-records |
| 构建脚本 | `scripts/build_trollstore_ipa.sh` | 一键：子模块 → 原生依赖 → 归档 → ldid 伪签名 → 打包 IPA |
| 云端工作流 ×3 | `.github/workflows/*.yml` | 用 GitHub 免费 macOS runner 在云端编译，产物直接下载 |

> 为什么需要 `allow-jit`：**iSH 沙盒用 ARM64 JIT 在设备内跑 Linux**。TrollStore 侧载的 App 默认没有 JIT 权限，必须声明这些 entitlement，安装后还要在 TrollStore 里对该 App 点 **Enable JIT**，否则沙盒起不来。

---

## 2. 纯手机操作步骤（不需要任何电脑）

> 前提：手机已装好 **TrollStore**；有一个 **GitHub 账号**（免费的就行，fork 公开仓库后 Actions 免费且不限时长）。建议用手机浏览器（Safari/Chrome）打开 `github.com`，必要时开「桌面版网站」更好点。

### 第 1 步：Fork 仓库
1. 手机浏览器打开 `https://github.com/Niubiprass/OpenMinis`
2. 点右上角 **Fork** → 确认（默认公开，Actions 才免费）→ 等几秒完成。

### 第 2 步：开启 Actions
1. 进入你 fork 的仓库（`github.com/<你的用户名>/OpenMinis`）。
2. 点顶部 **Settings → Actions → General**，在「Workflow permissions」选 **Read and write permissions**（仅本仓库），保存。
3. 点顶部 **Actions** 标签，若提示「enable」就点开。

### 第 3 步：一键触发编译（重点）
仓库里有 3 个工作流，手机端推荐用 **`OpenMinis IPA`**（最稳，跑在 `macos-latest`）：

1. 在 **Actions** 页点 **`OpenMinis IPA`** 工作流。
2. 点 **Run workflow**（右侧或右上）。
3. 展开选项，把 **`build_ipa`** 勾选为 `true`（这一项默认是 false，只跑"扫描"不编译；必须勾上才会真正编译）。
4. 点绿色 **Run workflow** 提交。

> 备选：若 `OpenMinis IPA` 因「iOS 26 SDK API」报错，改用 **`Build OpenMinis IPA (iOS 15)`**，在 `deployment_target` 输入框填 `15.0` 后运行（它需要较新的 Xcode runner）。第三个 **`Build OpenMinis TrollStore IPA`** 会额外注入 TrollStore entitlements，可二选一。

### 第 4 步：等待并下载
1. 编译约 **30–60 分钟**（首次要源码构建 LAME/FFmpeg/iSH/Alpine，最慢）。可关掉网页，过会儿回来看。
2. 完成后状态变绿，点进该次运行 → 底部 **Artifacts** 区域会出现 `Minis-iOS15.5-ipa`（或 `OpenMinis-TrollStore`）→ 点它下载 `.ipa`。
3. 手机下载的是个 zip，解压得到 `Minis.ipa`。

### 第 5 步：装进 TrollStore
1. 把 `Minis.ipa` 存到手机「文件」App。
2. 长按或用 **TrollStore → 安装 IPA** 选中它，等待安装完成。
3. 在 TrollStore 应用列表里对 **Minis** 点 **Enable JIT**（App 被系统杀掉重开可能要再点一次；可配 JIT 自动助手）。
4. 打开 Minis，按 README 配置模型 API Key 即可使用。

---

## 3. 三个工作流怎么选

| 工作流 | Runner | 特点 | 推荐度 |
|--------|--------|------|--------|
| **`OpenMinis IPA`** | `macos-latest` | 最稳，勾 `build_ipa` 即编译，产出未签名 IPA，TrollStore 可直接装 | ⭐⭐⭐ 首选 |
| `Build OpenMinis IPA (iOS 15)` | `macos-26` | 可填 `deployment_target`，需较新 Xcode；上面的不行时试它 | ⭐⭐ 备选 |
| `Build OpenMinis TrollStore IPA` | `macos-15` | 额外注入 TrollStore entitlements（含 JIT、去 NFC） | ⭐⭐ 备选 |

> 三个工作流产出的都是**未签名 IPA**，TrollStore 靠 CoreTrust 漏洞安装，无需你提供任何签名证书。

---

## 4. 排查

- **沙盒起不来 / 命令无输出**：几乎都是 JIT 没启用。回 TrollStore 给 Minis 点 **Enable JIT** 再开。
- **工作流红掉、报 “call to iOS 16.x API requires @available”**：个别 iOS 16 API 还没被兼容层覆盖。把 **Artifacts → build-diagnostics** 里的报错发我，我帮你加 `@available(iOS 16, *)` 守卫或复用 `iOS15Compat.swift` 替身，改完重跑。
- **装完打开闪退**：检查是否误带受限 entitlement（NFC、health-records、carplay）。用 `Minis-TrollStore.entitlements` 的那条工作流已剔除。
- **CloudKit 同步失败**：预期内（侧载无 container 授权），不影响其余功能。
- **等了很久没出 Artifact**：先看运行日志卡在哪一步；原生依赖首次构建很慢，耐心等满 30–60 分钟。若超时，可在工作流里把 `timeout-minutes` 调大后重跑。

---

## 5. 法律 / 许可

- OpenMinis 为 **GPLv3**，在自有设备上用 TrollStore 侧载开源软件是其常见用途。
- TrollStore 利用 CoreTrust 漏洞实现永久签名；本指南仅用于构建/安装该开源 App，**不用于破解或分发任何付费/加密应用**。
- 若需 iCloud 同步、NFC 等受限能力，请用**自有 Apple 开发者账号**正常签名打包，而非 TrollStore 侧载。
