# OpenMinis 本地联合修复状态

## 范围与授权
- 当前分组：OpenMinis App；接手会话 2D6BCAFE-300A-499F-8C5B-4365D77EA249。
- 基线：20f30388222f71debe9ab86f8ab06ee0ac90ff71（GitHub #205）。工作树：本目录；保留原 HANDOFF-STORAGE-DELETE-20261104.md。
- 用户已批准本地修：①应用内更新（自动检查、关于入口标记）②多 Key 顺序优先的欠费切换。
- 已确认样式：有新版＝红点＋“有更新”；实际新构建重开后＝灰色“已是最新”；下载中/跳安装器/失败不提前清除红点；未检查或检查失败不伪装最新。
- **未授权 commit/push/CI/安装/注销/重启/设备操作；未读取或输出 Key；未下载 IPA。**

## 本轮本地改动
更新（AboutView.swift / ContentView.swift / AppDelegate.swift / scripts/test_inapp_update_160652.py）
- 检查策略抽成 UpdateCheckSchedule：成功 24h 节流、失败 5min 重试；结果与构建号缓存，失败不再误报“已是最新”，也不再擦掉已发现的新版。
- 触发点：冷启动、回前台（SceneDelegate.sceneDidBecomeActive）、打开设置、打开关于页。
- 关于入口用 AboutUpdateBadge 独立观察，下载进度不再让整个设置列表重绘。
- 下载改为后台 URLSession（固定 session id + downloadTask 代理），元数据原子落盘，支持系统回收后恢复；完整性仍 SHA-256 + 大小校验后才交 TrollStore（需前台用户点按）。
- GitHub 请求补 User-Agent、no-cache，并按 403/404/5xx 显示真实原因，不再把所有非 200 说成“没有发布测试版”。

多 Key 顺序欠费切换（ProviderMultiKeys.swift / AgentProvider.swift / OpenAI·Anthropic·Gemini provider）
- 新增 ProviderServiceError：HTTP 与 SSE(HTTP 200 内) 的结构化错误正文都能到达分类器，429 不再一律当限流。
- 欠费关键词扩充（billing_hard_limit_reached、insufficient_user_quota、欠费…），并按分钟/秒限流与余额耗尽区分。
- 顺序优先下，只有 `.transient` 才同 Key 重试；欠费/失效/限流立即换下一把；同 Key 重试前重新校验 Key 是否仍启用/未被替换；余额耗尽只停用一段时间、不删除。
- 服务端 `rate_limit_exceeded`/`server_error` 保持“同模型重试”，不触发模型组回退（避免行为回退）。

## 本地检查（都已跑过）
- 新增/扩展静态回归：test_inapp_update_160652.py、test_multikey_quota_failover_20261105.py（已加入 CI 静态步骤）。
- 既有测试全绿：feature_compile(2 skipped)、photo_picker、attachment_preview、launch_icon、ask_card、export、quota、v64r_text_layout、model_refresh_authoritative、v64r_render_contracts、stream_text_fade_source、host_stable_shrink、scroll_deferred_identity、longtext_container_layout、multikey、multikey_persistence、multikey_freeze、four_features(17/17)。
- 括号平衡检查（自写 tokenizer 级）通过 9 个改动 Swift 文件；workflow YAML 可解析；git diff --check 干净。

## 未验证 / 未完成
- 未 Swift 编译、未 CI、未出 IPA、未安装、未真机验收。本机无 swiftc，tree-sitter 版本与现有语法库不兼容，只有括号级检查。
- 多 Key 结论基于源码与静态契约；**没有本次手机响应正文的证据**，不声称已定真机根因。
- 用户手机的旧存储删除功能仍待真机验收（本会话未安装、未点删）。
- 既有缺陷（非本轮引入）：`scripts/test_quota_multikey_perkey_160651.py` 指向不存在的 `/var/minis/shared/OpenMinis-160649`，也不在 CI 清单里。

## 另记：输入栏发送键残影（未修、未定因）
2026-11-05 录屏 video_582BB4FB：3.7–4.0s 发送键与麦克风被多画一份（偏左上约 35px、发虚、压在输入框内），4.1s 自行消失；发送本身正常。用户称偶发。两个候选：`.id(composerRebuildTick)` 自愈重建（AIChatView 4090/7328）、浮层随键盘重排（700-830）。区分需读当时 `[InputBarLayout]`／`[InputBarHealth][V30-KICK]` 日志，尚未读。手机装 build 203，与本轮改动无关。

