# 真正待发送队列：本地视频预览（2026-11-16）

## 范围
聊天区虚线排队消息（红 ×）的 `QueuedAttachmentPreview`，不是底部 composer。保留既有底部视频修复、图片/文档/已发送附件及发送/撤回代码；未处理粘贴元数据遮挡或图片环境旁支。

## 实际接线
`ChatInputBar.swift` 的排队 `.video` 改为带播放三角的 `Button`，仅 ready/file URL 可点。
`ChatMessageViews.swift` 将附件及消息 ID 交给 `OpenQueuedVideoAction`。
`CollectionViewMessageListV3.swift` 在独立 `UIHostingConfiguration` 显式注入动作并捕获所属 session；桥接再次核对当前 VM、真实排队消息 ID、附件 ID/ready/cacheURL。
`FileAttachmentPreview.swift` 的 `FileAttachmentPresenter.openQueuedVideo(_:sessionId:)` 复用 `openVideo(_:queuedLease:)`，仍由 cell 外稳定 `SheetOverlayView` 的 `MinisVideoFullscreenPlayer` 呈现。没有 cell 视频 sheet。

## 文件与竞态
点击时只进行一次非阻塞、拒绝末级符号链接的只读 open，先固定 inode，避免队列随后 unlink 使预览失效。detached 任务执行 fstat 普通文件/非空校验，最大 512 MiB，以 256 KiB 分块复制到独立临时目录；不在主线程读/复制整段视频，不依赖跨卷硬链接。
副本租约同时由 immutable cover payload 持有，原队列 drain/撤回删除缓存不影响播放；cancel/reset、切换 session、替换 VM、列表 teardown 取消复制并更新请求 token，旧完成回调不会开启新会话的播放器。播放器消失后租约析构，在 utility 队列删除其专属目录；失败/取消在 worker 内清理半成品。打开操作本身不发送、不撤回、不删除队列或更改已读。日志仅固定 `stage=...`，无路径、URL 或错误对象。

## 测试与限制
- `python3 scripts/test_queued_video_preview_20261116.py`：6 项源码/夹具契约通过，1 项原生测试 SKIP。
- 新 Swift fixture `scripts/fixtures/queued_video_preview_20261116.swift`：runner 提取真实 InputAttachment、保留源、完整 FileAttachmentPresenter 和实际 V3 桥接，仅 mock 平台依赖；覆盖交接、当前队列/会话校验、取消/替代、drain/unlink、租约关闭、缺失/空/目录/FIFO/符号链接/超限文件。
- 原 `test_attachment_preview_160651.py` 的 14 项全部通过，未改原断言；send/share 静态守卫通过。
- `--require-native` 在 iSH 返回 1（失败关闭），用于后续 macOS 主机；本机没有 Swift，不能宣称已执行原生 fixture、已编译 iOS 或已验证实际视频解码/播放。
- `git diff --check` 通过。未触碰 AIChatView/PBX、既有其他 dirty 改动；未运行 CI、push、安装、设备播放/麦克风或改环境。
