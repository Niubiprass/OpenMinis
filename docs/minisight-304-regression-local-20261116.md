# App304 / MiniSight0.8.44 安装后回归：本地0.8.45候选

## 状态与许可

- 基线：App `b0bec05b69dae0ed9ab57fda817f1e18b60d98de`，插件 `8d433c122f5735b4acf44fd66bc98e5f3f14b842`。本批仅在两树工作区修改，**未提交、推送、触发CI、生成IPA/DEB、安装、开麦或设备设置操作**。
- 实装304／0.8.44已经前一轮只读取证，不重复设备探测。用户后来明确“可以”批准这批本地改动；不能沿用上一批双端发布授权。插件候选升0.8.45，App内模块0.8.45-local.1，尚无新App build号。
- 用户拒绝的诊断及普通Quota/Audio日志未换命令重读。本批没有查询真实歌曲、签到或用户Key。

## 本地候选

### 名字状态

已证 installed companion 的 `allowed` 是数字0/1，App原来只收JSONBoolean，整份状态丢弃后被误报锁屏。生产桥调用共用 `MiniSightNameWakeState.h`，显式BOOL组包；真实Swift reader只兼容CFBoolean或严格整数CFNumber0/1，拒浮点、字符串及其它真值。缺失、坏包、过期、未来时间和revision不匹配走“桌宠状态未就绪”，不冒充已锁。可信锁屏/本机受保护数据不可用、OFF立即停，busy独立退让。

原有后台边界保留，不退成App前台：已有授权input的最多3秒被动交接仅丢检测帧，不新开麦、不跑关键词；可信锁屏、OFF、通话录屏或到期立即停。没有改变音频协调器、Speech、VoiceBridge或BackgroundKeepAlive源码。自然语音final保未发送草稿、手动语音和审批仍保留。

新原生往返：生产ObjC builder→Foundation JSON文件→完整生产Swift Remote/Policy；20组writer消息、真假/旧整数/错误类型/host-revision-clock/前后台/OFF/取消和3个行为变异。App独立CI使用同源头及生产桥调用摘录，不把缺兄弟仓库当通过，不把SB桥加入App Sources。

### 当前Key余额与消费后更新

外层按最后成功使用的可用Key，未有成功时用主Key；不再取全Key最低/求和，也不本地估算账单。成功通知去重，轮询/失败/冷却/主Key策略保持；按行owner隔离缓存，旧无身份v1摘要不当当前读数，读回保留真实observedAt和fetchedAt。

自动仅当前行：末次消费后2秒合并、每实例至少30秒、前台查询/后台dirty回前台补、15分钟兜底、429/退避。补齐：旧异步lookup不能覆盖新成功、自动key与row绑定、停用行手动读数与代表资格分离、单行失效不影响兄弟请求、撞在途明确deferred保dirty、旧owner晚失败不能抹新成功及持久指针、无消费记录时TTL不能永远向后延期。

新夹具抽取生产解析、缓存、resolver、consumed、runAutomatic、refreshRow、invalidateRow等；仅上下文/Keychain/UI/网络返回由合成替身提供。确定性暂停模拟旧lookup、新success、手动停用行、凭据更换、新owner成功后旧包返回、忙碌合并和延期；原生正例及4行为负例尚待获准CI。

### 音乐保存、恢复与停止

Resources统一用有界一字节shown读回，优先文件而非旧runtime ON，读回提供文件事务身份。显式hide立即关显示/音乐，异步保存必须真实读回才通知，失败反馈且旧ON不能解除隐藏；观察OFF后ON或新的原子ON才恢复，重启后的旧ON先锚定不强显示。

settings单在途合并、过期回包重读，资源完成尾再次重判renderer/style并保留queued completions；show/fade代次避免旧淡出藏新窗口。SB实际可见资格与App快照通路分开：App模式只在已选且当前前台时供快照，App既有visible-only消费者决定本地实际呈现；不强驻、不重复SB窗口。两端Monitor实现、BOOL与version1＋evidenceVersion1镜像一致；无同步歌词时只清词，不因取词失败无故关playing。私有接口判型、CF借用复制、真实单在途/退避保留。

新Foundation夹具字节摘录5个真实Tweak函数（含UserHide）＋3个真实资源writer，覆盖旧ON回包中隐藏、异步写回失败/通知、结构恢复/回调队列/重启后新ON。负例需撤两层epoch防线才真正制造不安全行为，未删生产冗余防线。便携C策略已执行，UIKit实际动画和Foundation原生仍未执行。

## 核验与仍未验证

本地定向源码、共享字节、可执行C规则、相邻服务商/Key/队列视频/签到/录屏/素材/聊天等回归；完整结果在 `workspace/minisight-304-local-20261116/checks/`。iSH没有AppleSwift/SDK，新native明确SKIP；严格必需native入口非零拒绝放行，工作流已登记，**没有运行CI**。

旧前台音频测试自身仍按82f9fb1前台API查`startRecording()`，在已发布304的后台API上就失败；该脚本及4个音频生产文件与304字节相同，失败单独保留于首轮报告/`AUDIO-PARITY.json`，不能称它通过，也不能为过旧测试撤销已获准后台能力。现行后台真实生产mock测试仍在CI必过。

19:28网易云歌词/律动失败的真机根因仍未知；后来shown0只证明后来状态，不能倒推当时。此候选覆盖已证源码链路缺口，不宣称已修好真机歌词、识别率、耗电、音乐蓝牙、切歌或AVPlayer。编译、验包、安装加载及功能验收分开，后续分别问推送与安装，注销/重启/开麦另问。
