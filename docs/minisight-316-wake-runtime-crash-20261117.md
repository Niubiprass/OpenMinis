# build316 桌宠开启闪退：私有运行库隔离（2026-11-17）

## 根因已证

用户已有三份 IPS。报告与正式发布局部提取的 Info.plist/主程序 UUID 完全一致：build316，`02d4f2b8-3a6b-35cb-8af0-f0c150e37dfd`。名字引擎调用 `SherpaOnnxCreateKeywordSpotter` 后进入 `Ort::Env`，空指针加24处崩溃。实际主程序的 `OrtGetApiBase` 绑定旧 VAD；名字组件请求 API28，旧 VAD 只支持1–20，返回空接口。不是余额故障，也不是桌宠进程同时崩溃。

没有再次复现或重启。设备版本查询被拒后未重试。仅下载正式发布的 Info/主程序/VAD三个ZIP条目，CRC和UUID通过，未下载完整 IPA。证据保存在 `shared/openminis/local-reviews/wake-ort-crash-20261117/`。

## 本地修复

- Sherpa与固定ORT1.28.2封装进真正的私有动态 `SherpaOnnxC.framework`；仅导出Sherpa C和专属预检接口，隐藏ORT/MLAS/内部C++。
- SPM不再把独立ORT静态库带入主程序。不降API版本，不裸force-load进主程序。
- 名字模型构造前检查兼容性。不兼容时正常报错，不调用会崩溃的构造器；不是永久关闭名字替代修复。
- 源构建、完整App、最终IPA解压各有严格门槛，检查最终绑定、嵌入产物指纹、旧VAD代码/数据section不变。
- 保留全部原版本、模型与许可证。旧VAD、手动语音、后台名字、OFF/锁屏/取消、歌词动作、额度消费及设置持久化不改。

## 结果分层

上一轮22普通入口/6严格入口及30便携例只是旧快照，独立审计确实复现B1函数加数/同槽覆盖与B2旧VAD依赖/实际导入/export地址漂移漏检，不能沿用旧矩阵。

B1真实补修并独立审查通过：父与审查代理各自实跑133便携例；独立自造Mach-O再做77次gate调用，39 ACCEPT/38 REJECT，原非零加数和同槽覆盖等反例被拒，合法独立槽/重复绑定/system weak正例保留。B2固定loader身份由真实build316旧VAD推导并钉住baseline，42项静态/便携矩阵及真实原库copy正例通过；真实依赖名、malloc实际链和OrtGetApiBase导出地址-4三个保持section库存不变的负例被拒。父将固定身份校验接到final app_gate且移除调用方自选基线；独立以真实旧VAD+合成App验证原例通过、三反例拒绝。

最新本地矩阵24普通入口全通过；7严格门槛按预期因缺Apple原生工具/完整产物拒绝。生产保护源码和PBX工程文件都与基线匹配，Release旧VAD strip阶段保留未改，不能将静态结论冒充Apple签名或运行证明。Apple复制/移除签名/重签、18 host dyld、完整iOS App/最终IPA和真机仍未运行/验证；最终本地文件指纹冻结及提交前门槛还未生成。

本地完成不等于CI成功；CI成功不等于iOS15.5真机验收。用户已批准本批本地修好检查后推送监控，不含安装、开麦、注销或重启，也不含完整IPA下载。
