# MiniSight App + 附件修复状态（2026-11-08）

- 阶段：本地改码与静态检查完成，准备推送 CI。未安装、未注销、未重启。
- 基线：`Niubiprass/OpenMinis` / `ios15-160652-four-features` / `f6e65c8`。本轮在其上追加。
- 保留 245 已有修复：附件暂存改 Application Support、失效附件容错、DSML 工具解析、更新下载暂存。

## 本轮范围

1. 视频附件先解析成真实 `file://` 再交给 AVPlayer；播放器保留第二层兜底。修 17:57 黑屏 0:00。
2. 12:13 的 8×9 图集恢复单角色动作：渲染按 `列/8、状态行/9` 取单帧，不再切 64×81 碎片；整图静态照片仍整张显示。
3. 旧记录一次性迁移：245 把照片写成 v3、把图集当 72 外格；现按尺寸纠正为整图（1）或动画图集（3）。
4. 删除设置里的配色入口；插件不再叠加染色。
5. 删除 AI 页人设输入区（底层字段保留供连接保存）。
6. WAV `fmt` 块长度改为 16（原来误用 `frames*2=2800`），检查初始化/播放失败并可重试。
7. 设置全部实时：App 手势改读设置；插件每 0.5s 盯 revision/shown，大小与显隐即时应用。
8. 动作节奏按参考优化：拖动锁一个跑步动作到松手，摇晃不重置帧；徂移/跳跃才响，点击不再响。
9. 设置页缩略图翻正，不改存储方向；气泡改为随字数变大的面板，最长 42% 屏高后滚动。
10. 测试：视频必须 `isFileURL` 且经 session 解析；图集动画/整图断言；可解析 WAV 头；实时设置与拖动断言。

## 证据

- `python3 scripts/test_minisight_local_repairs_20261107.py` PASS
- `python3 scripts/test_attachment_preview_160651.py` 14/14 OK
- `python3 scripts/test_minisight_blip_wav.py` PASS
- `python3 scripts/test_minisight_settings_contract.py` 45/45
- CI 前置脚本批量运行通过；本地无 swiftc
- 真机素材分类复算：768×936 透明 PNG 为 57 帧，新的比例判定走 layout 3

## 未验证

- 未 Swift 编译、未 CI、未安装、未真机。
- 视频黑屏修复只到代码链；未读 AVPlayerItem 运行时 error。
- 动画帧是否完整、音效是否可闻、配色/人设是否真正消失，都要装机后看。
- 插件端 `MSLoadAtlas` 已区分照片/图集透明处理，但未编译。

## 授权

- 用户 2026-11-08：“赶紧修复，然后推送” = 修完允许推送。安装/注销/重启另问。
