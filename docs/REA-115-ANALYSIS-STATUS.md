# App Store 1.15：REA逆向分析状态

日期：2026-10-17。用户要求使用GitHub REA分析App Store 1.15以辅助完整功能复现。本记录不是功能完成或已反编译的声明。

## 已核实
- 官方REA来源：https://github.com/morluto/rea 。README说明原生分析输出伪代码、汇编、字符串、符号、调用及引用；不是原始Swift/SwiftUI源码恢复，也不能自动生成完整原Xcode工程。
- 已读官方Apple应用分析文档：https://github.com/morluto/rea/blob/main/docs/apple-application-analysis.md 。IPA清单/资源投影与原生函数反编译是不同步骤；不能拿清单当完整功能分析。
- 现有本地工作流`/var/minis/shared/theos-ci/.github/workflows/build-rea-analysis.yml`使用macOS、Node22、rea-agents及Ghidra，输入硬编码为Debs_v8.0.ipa，查询也针对上传流程；尚不是OpenMinis1.15任务，不能触发它并声称已分析1.15。
- 本轮对attachments/shared/mounts下候选IPA只读核对Info.plist（跳过.git、.Trash、node_modules、.theos、evidence目录）：8个IPA可读，其中仅2个Minis，二者均为com.openminis.app、版本1.14、build1、最低iOS15.5，未找到1.15 IPA。
- 两份旧Minis包位于挂载的File Provider Storage/OpenMinis相关修复/，文件名分别为Minis-iOS15.5.ipa和Minis-iOS15.5 2.ipa。未修改或安装。

## 当前路径（用户澄清后更正）
用户没有1.15安装包，设备为iOS15.5，不能要求用户先下载运行最低iOS16的App Store版。缺少iOS样本只阻塞“分析iOS1.15二进制”这条路径，不阻塞基于公开资料复现功能；不再把提供IPA当作用户的前置责任。

已自行取得官方公开Android参考产物：`OpenMinis/OpenMinis` release `0-beta-build33`的`MinisApp-1.15-beta.4-build33-arm64-v8a.apk`，发布于2026-10-09。保存于`/var/minis/shared/OpenMinis-115-reference/`。大小43,179,428字节，SHA256 `1b3f12d6ed11ca2f4f1a415cbbc6f8cc51ca0a900a16eec8d9f59822e1c3e1de`与官方release digest一致，ZIP CRC通过。只读解析AndroidManifest确认包名com.openminis.app、版本1.15-beta.4/build33。

`inspect_reference.py`和`static-inventory.json`保存静态清单及字符串线索。简单包名前缀匹配返回0，不能解释为没有应用代码（可能被优化/混淆）；字符串命中仅供后续定位，不能当作功能行为已验证。REA/JADX尚未运行，未反编译出实现。该Android beta不是iOS App Store 1.15，不能用其替代iOS二进制或声称恢复了Swift源码。

官方REA文档列明Android APK静态分析使用JADX和完整JDK；当前环境没有REA/Node/JDK/JADX，因此没有伪称已执行REA。公开参考包可用于共有功能研究，iOS专有行为仍需官方资料或未来取得真实样本支持。若以后取得iOS样本，再核对版本、构建号、主程序SHA256、架构与LC_ENCRYPTION_INFO；加密字节不能作为有效函数反编译结果。

在兼容REA/Ghidra环境下逐模块定位：提问确认卡、长图/PDF、聊天搜索、定时任务、供应商额度、连续工具折叠、数据管理与语音相关流程。保留函数地址、字符串交叉引用、伪代码和未知项，再对照公开1.14源码进行iOS15.5适配；结果标为反编译/重建，不标为官方原始源码。

不得将包、收据或账号信息提交到公开theos-ci仓库；云端传输和权限需单独确认。该路线不取消原同版分组技能/灵魂/独立记忆及管理功能范围，也不声称App Store1.15一定含有这些自定义分组功能。

## 本轮没有执行
没有对1.15运行REA（样本缺失）；没有进行解密、运行目标、手机MCP操作、安装、重启、Git提交/推送或触发Actions。没有改动OpenMinis生产源码、用户记忆或模型配置。
