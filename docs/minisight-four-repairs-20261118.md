# MiniSight 0.8.47 — 四项本地补修

## 范围与授权
歌词不显示、名字无响应、注销/重启后整素材图背景重现、桌宠可移动范围变窄。最后一项明确是桌宠本体活动区，不是新增贴边气泡：应能接近屏幕四周，只防身体出屏。

用户已分别批准本地动手及“这几个问题修复了，就推送”，允许本批完整本地检查后的App/插件提交推送/CI。余额和10.58GB暂停，不读取用户设备数据；不包含安装、开麦、注销、重启或整IPA下载。

基线A `a9e3d7e833aa1377b0ef34a5fc97e704a950904d`（build323 CI发布通过，不是当前实装证明）；P `9fbc15d8669d91997c059c1ecedc6cf3e5a16070`（0.8.46双包CI/静态通过）。当前本地模块0.8.47-local.1 / 插件0.8.47，尚未本批CI或装机。

## 最小修改
- 图集：旧a1a3e8b/30c2a88移除UIImageView getter；eeaab13特效接入重新暴露整图。现去掉自定义getter，父层为空，专用restore按当前布局恢复裁切帧；同图重设/初始化/清单切换/停止失败都可恢复。合法动作海报不被图集比例误裁，旧静态/多宠物/图集保留。
- 移动：共用MSBodyCenterBounds，以完整身体/原重力包络+2pt边距限制中心；普通桌宠不永久预留安全区/气泡高度。实际旋转缩放四角用MSPetFitVisualTransform适配边缘，不缩活动区、不移命中层。胶囊/审批旧safe/headroom/按钮取消保留；普通文字尺寸/viewport恢复作为相邻保护，不能反过来压缩宠物范围。
- 歌词：Apple dyld-955 getSlide以__TEXT.vmaddr为基点，共享缓存fileoff不是单个dylib磁盘零偏移。双端MSMusicSymbol依此修，保代码/数据/读执行保护及原调用指针。无词不换歌名、只当前同步行、五播放器/严格匹配/隐私与锁屏准入不变。未证手机当时原因。
- 名字：正常授权UI inactive不当真正后台。新启用事务遇真后台/锁/保护数据/样式失效立即取消代次；正常inactive可保存意图但不伪造active采音。共用Speech权限函数只在入口、Speech await后、mic await后加3行取消检查。不能撤回已展示系统弹窗；原已授权后台输入、手动语音/草稿/手动发送、未知lock/screenOff与命中ACK保护保留。

## 检查
最终本地58入口符合预期：47普通exit0（36含native SKIP）、9strict明确缺Apple工具exit1拒放、2diffcheck通过。真实C边界449462+3个编译后运行断言负例；旧布局1600029（原1600001不删）及7相邻便携入口过。音乐16C+2compiled负例、显示24C+compiled负例、Atlas每端9source负例/13真实方法摘录、权限11+5source负例过。所有新原生正例/负例尚未Apple编译执行，不当原生通过。

初审发现权限inactive误拒、初次暂隐文字丢size及两阶段取消缺口；最新WAKE-AUDIT/BUBBLE-AUDIT已补。生产源保护和共用镜像通过，ORT/VAD/模型、Providers/Key/额度/签到、原音频协调器/VoiceBridge、Resources/Panel/导入原件/录屏/队列视频均不改。测试保存真实生产摘录，负例要求先编译成功再被指定运行断言拒绝，不用编译失败替代。

## 层级与未验
本地源码/便携已验，最终独立整合审查完成后才冻结推送；iOS15.5完整构建、Apple native、最终IPA/DEB验签载荷、安装加载和真机四项效果分别记录。歌词可用性、真实权限/识别/耗电/后台/所有素材冷启动/屏边视觉尚未真机证明，不能称用户症状已在手机修好。

证据长期目录：`shared/openminis/local-reviews/pet-four-repairs-20261118/`。推送后CI工具与准确run/head/attempt另存 `shared/openminis/releases/Minis-0.8.47-20261118/`。App不下载整IPA，发布以完整CI最终解包/签名及资产元数据归属核验；插件双DEB与Source.zip/SHA256SUMS按旧流程核验交付。安装/注销/重启仍需单独批准。
