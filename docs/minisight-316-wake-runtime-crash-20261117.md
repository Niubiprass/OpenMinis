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

首次实际CI build317/run44090041391在Mac上完成253个依赖编译并链接后，于新framework的Mach-O binding gate失败，错误为 `actual bind address outside file-backed segment`；依赖产物/source gate没有完成，后续原生行为/App编译/签名/IPA全未执行。父核对Apple dyld-955 `MachOAnalyzer.cpp:1917-1983, 2008+` 后确认传统bind地址依法以可写VM segment/vmsize校验，运行时将地址写入映像；此前checker额外以filesize拒绝属假拒。已本地窄修：传统bind按vmaddress记录覆盖冲突，区分file_backed；VM-only零填充事件被追踪，但关键函数binding gate仍必须有真实file-backed八字节槽。Apple dyld type1 pointer bind还要求initprot可写且不可执行，checker已显式门禁；chained fixup仍保持文件槽约束。新增BSS正反例及RW/非执行权限负例后134便携binding用例通过。修正后provenance source contract、真实旧VAD 42项、B2真实旧库/合成App接线正反例和相邻功能检查均通过；最新完整本地矩阵24普通入口通过、7严格缺工具/产物按预期拒绝。新修正尚未推送/重新进入CI。

生产保护源码和PBX工程文件都与基线匹配，Release旧VAD strip阶段保留未改。仍未运行Apple nm/otool/18 host dyld、VAD copy/remove/re-sign、完整iOS App/最终IPA及真机。故不能宣称Apple原生、App编译、打包签名或真机结果通过。


本地完成不等于CI成功；CI成功不等于iOS15.5真机验收。用户已批准本批本地修好检查后推送监控，不含安装、开麦、注销或重启，也不含完整IPA下载。
