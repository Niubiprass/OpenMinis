# build308模型选择卡死：本地候选与扩查

## 授权和状态

用户已回退上一版，并批准“修的同时检查一下还有没有其他问题”。本轮只获本地修复与检查；未提交、推送、CI、安装、设备、开麦、注销或重启。HEAD仍5fb44c26a4b79265f435068a614f04d14a7b567e。

三份IPS匹配build308的执行文件UUID。主线程cachedQuota等待余额NSLock，后台store在持锁的UserDefaults.set中等待。304相同保存点先释放锁；本批回归已证。系统下游私有等待链未完整符号化，不宣称具体闭环死锁对象全明。

## 本地候选

- UI共享锁只保护内存快照、epoch/ticket、owner/successAt和版本；存储与JSON及投影移到锁外。
- 行保存、当前Key指针、定向删除及失效屏障共用utility串行writer。锁内只更新不可变待写任务；实际系统存储不能拖住UI锁。
- 冷恢复在锁外读取，提交前复查epoch/version/identity/successAt，不让旧磁盘值覆盖新内存。
- 普通失效保留有效v2持久余额；reset仅有序屏障，不全扫设置删盘。新successAt防同owner旧请求删除新成功。
- 保留当前成功Key/default main、2秒消费合并、30秒自动门槛、15分钟前台兜底、disabled行手动查询、轮转统计。没有修改Factory、音频、插件或ProviderPricingService。

真实生产摘录存储夹具覆盖暂停保存时主队列读取非空余额、真实通知回调、FIFO/current/row、定向删除、失效后有效恢复、迟到磁盘数据和取消。重新把保存搬回UI锁的静态负控已拒绝；原生行为负控尚未运行。

## 验证分层

- quota来源和锁隔离守卫8项PASS；3项Swift/Apple原生夹具无工具SKIP。
- V64R_REQUIRE_SWIFT=1退出1，3项缺工具FAIL：严格拒绝放行，不是假成功。
- 父最终重跑29个相邻入口exit0；其中16个入口包含原生SKIP，不是29项全部原生通过。
- 旧音频入口仍3失败、4错误、1跳过，属于API/预期漂移；保留测试不降低门槛，不能据此断言当前音频已坏。
- Python语法及git diff --check通过；未CI、未安装、未真机验收。

## 额外问题：仅查证，未扩大修改

两份独立审阅发现以下源码条件缺陷，非三份IPS根因，未真机证明：

1. 普通未启用轮询的单Key成功没有消费事件，不能保证消费后自动刷新；成功时间在通知端才取，乱序回调可使代表退回较早实际成功Key。
2. 配置失效取消调度后，dirty在特定重新解析路径没有补调度；详情持有旧快照，未跟随revision/阈值且缺UI generation。
3. 显示状态文件缺失或非法时App回退ON而配套关闭，显示不一致；无关设置页退出保存旧ON可覆盖菜单隐藏。
4. 名字生产者将屏幕未知或熄屏混入可信锁定，可错误提示锁定原因；停止监听本身仍安全，不可放宽锁屏保护。

额外修复须先确认范围；双端问题不能仅改App假称完成。推送、安装仍分别另问。

长期证据：`/var/minis/shared/openminis/local-reviews/model-picker-watchdog-20261117/`下FINDINGS、QUOTA-LOCAL-REPAIR、ADJACENT-QUOTA-REVIEW、ADJACENT-NAME-MUSIC-REVIEW、other-issues-summary与adjacent-checks/RESULTS.json。

---

## 2026-11-17 本批额外修复及独立推送授权（最新）

上面的“额外问题未修改/未获推送许可”是首轮历史状态。用户随后批准一起本地修复，并另外明确“推送”。最新授权覆盖本批 App/插件完成检查后的提交、推送和 GitHub CI；不覆盖设备操作、安装、注销、重启、开麦或完整 IPA 下载。

本批基线 App `5fb44c26a4b79265f435068a614f04d14a7b567e`，插件 `fd321d3a374cfce99aafb652830b9d63ad998f6d`；插件候选 `0.8.46`，App 模块 `0.8.46-local.1`。

### 已冻结生产修复

- 余额保留首轮内存锁/有序 writer 候选。失效后只恢复已有 dirty，重新验证当前 owner 与 epoch 后有限补查；后台不查询、真实 running 不重启。未落盘最新 current 仅作内存验证候选，不倒退旧磁盘 main。
- 详情使用一个后台投影 worker 和一个可替换 pending；revision/阈值只重投影不查账。手动、登录、外部刷新共用 generation，取消/切换/配置变化拒旧结果；凭据与 quotaRows 投影不进入 UI 存储锁。
- 普通 Agent 单 Key/空环仅在干净耗尽后报告真实 main 消费，无额外 lease/轮换/重试。发送前冻结实际凭据单向身份和实例 epoch，完成时冻结 Date；迟到事件不重新采样。多 Key 统计时间采用 max，失败/冷却/次数保留。
- LLM 工厂返回原具体 provider 和独立消费 reporter，保留 OpenAI 图片/raw 类型分流。QuickTest/Offload 在真实成功边界报告；失败、取消、非2xx不报，认证覆盖不误归主 Key。
- 两端 shown 复用严格单字节、有身份的保存/读回实现；缺失/非法一致关闭。无关设置退出不写 cached shown；被动读回不产生写事务，晚 ON 不复活菜单 hide。
- 名字 schema2 分离可信锁、屏幕已知和熄屏事实。可信锁/熄屏硬停，未知安全关闭但不伪装 locked；旧请求/result schema1兼容和原 token/revision/busy/聊天审批门槛保留。
- ProviderPricing 整类字节保持基线。宠物/面板/音乐生产不整覆盖两端平台差异，音频生产不为迁就旧测试而改。

### 验证和状态

四任务真实final已到齐并冻结；最终34个普通回归入口全部exit0，其中21入口含native SKIP。6个required入口均缺Swift/Apple SDK非零硬拒，不算原生运行。新增消费、详情、shown/name与适配后旧音频入口已登记strict CI，现行后台音频/native/iOS门槛仍保留。最终回归发现两项旧测试假设漂移，仅把“按钮内三个detached”升级为真正有界后台worker/快照读取，把“退出写cached ON”升级为权威被动读回/晚ON身份围栏；4个临时缺陷负控均被新断言拒绝，生产没有为迁就旧测试倒改。

共享State/20新fixture/2音频镜像同SHA，Resources有意保留平台差异；Pricing整类字节与基线一致，实际插件Tweak/Pet除版本外不变，Panel/Music与App音频同基线。两端diffcheck通过。插件新shown门槛普通模式通过、native严格缺工具拒绝；音频源码镜像仅App可运行，插件根错误调用日志不是有效门槛或通过证据。

当前尚未 stage/commit/push/CI。收口报告与准确矩阵会在提交前补齐；CI、安装加载、真机功能验收分别报告。真机锁屏、页面生命周期、Default 通知等待、音乐/蓝牙及后台音频效果均未验。

本批证据另见同长期目录下 `CONSUMPTION-REPAIR.md`、`QUOTA-DETAIL-REPAIR.md`、`SHOWN-NAME-REPAIR.md`、`AUDIO-GATE-REPAIR.md`、`FROZEN-INTEGRATION.json` 与 `extra-repair-checks/RESULTS.json`。
