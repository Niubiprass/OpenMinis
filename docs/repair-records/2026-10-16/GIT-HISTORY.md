# Reachable commit history

## active repair tree

```text
3f0e87b0f373c363ac2919fb9406f0f62a1a01b9	2026-10-16T01:52:45+08:00	CI: align render contracts with host identity guard
1ef28f59481399195f004a7a95280db012abc296	2026-10-16T01:46:16+08:00	iOS15: isolate rendered heights and release stale row size
0960b075448a8879d37bdc16c9d53cd312624af0	2026-10-15T21:18:23+08:00	iOS15: release stable host shrink and invalidate stale cell heights (160646)
5da5b4a6ff4a138a03ec34dfcf595080bbaf6bbf	2026-10-15T19:58:06+08:00	CI: fix Repair5 IPA checksum filename
a58d63dd5c86552ee60095fdcd0863118db815b9	2026-10-15T19:32:23+08:00	iOS15: fix fast-scroll layout, thinking visibility, and auto-compaction
3e27786d8e8e0724fad03ad2f9c9894e5d1d4296	2026-10-15T17:46:00+08:00	Document device evidence, repair status and continuation workflow
```

## historical mirror (snapshot, may lag remote)

```text
0960b075448a8879d37bdc16c9d53cd312624af0	2026-10-15T21:18:23+08:00	iOS15: release stable host shrink and invalidate stale cell heights (160646)
5da5b4a6ff4a138a03ec34dfcf595080bbaf6bbf	2026-10-15T19:58:06+08:00	CI: fix Repair5 IPA checksum filename
a58d63dd5c86552ee60095fdcd0863118db815b9	2026-10-15T19:32:23+08:00	iOS15: fix fast-scroll layout, thinking visibility, and auto-compaction
3e27786d8e8e0724fad03ad2f9c9894e5d1d4296	2026-10-15T17:46:00+08:00	Document device evidence, repair status and continuation workflow
c4dfa8dacbada30bf91847d7c50b130998584781	2026-10-15T17:39:48+08:00	Refresh committed text and thinking block heights through coalesced layout batches
26e5bbcc84a2d725f1c2e34362da1b03e71ce9f8	2026-10-15T16:21:50+08:00	Keep working assistant live before queued users and reflow following rows
788ba153520524f28d7fecdf4dc950d7678a644d	2026-10-15T09:10:01+08:00	Repair measured iOS15 text-view surplus at scroll settle
a8ab70b646d8c5388873512042ac5dd5e85a30e2	2026-10-15T07:50:43+08:00	Fix V31 flip-lock rejecting first real shrink; align auto-compress settings icon
68728eab935b6a503f0f84ac188af6b92d808688	2026-10-15T06:30:47+08:00	Trigger iOS15 repair CI when package validator changes
51eb0f471fc80d77a6a96d5a4306915eeb30c942	2026-10-15T06:22:45+08:00	Document original VAD iOS 15.6 baseline and scope package check
806de794d22fb02681a54fbb18d40f20db431405	2026-10-15T05:40:32+08:00	Fix iOS15 compaction budget localized format compilation
bbee41ef0ea3ef91dfb6047cd0cefc6696762728	2026-10-15T05:21:08+08:00	Fix CI target deployment override while preserving v64 project settings
a091b0cb3267c6d40d3c158c5c561aa27788f91a	2026-10-15T05:06:40+08:00	Fix v64 iOS15 streaming hosts and add optional global compaction budget
ce7a2298de2cd999bdf8ad44c73dc8a67b908f58	2026-10-08T02:56:48Z	Auto-port OpenMinis to iOS 15 (scripts @ 972bfb0)
972bfb01e81de033667f7faf29031e33891eb2f0	2026-10-08T02:29:52Z	fix: reverse_v53 S14 双形态适配 v79 C 路(CI#37716701845 空测)
913dc3deccdd85eb51e851b3dc6817acc4e941d6	2026-10-08T02:10:02Z	V79: 流式 cell 豁免 A/C/broad/B-precalc, 走 live measure(治文字一下跳出) Co-authored-by: monkeycode-ai <[REDACTED_PRIVATE]> Co-authored-by: monkeycode-ai <[REDACTED_PRIVATE]>
76e95b2173408aa347759ea5a72c38587c7b69f8	2026-10-07T07:31:21+08:00	fix: 直出打包升级为 TrollStore 版 — dyld 体检剔除 iOS 15 不可启动扩展(_AppIntents_SwiftUI/minos>15.5, 83679f4f 同款) + entitlements ad-hoc 签名(App Group 容器) + 校验加 V80-THROTTLE 硬标记
6480b72bf11cb5d5a6634de6775077aa0846a383	2026-10-07T07:30:24+08:00	fix: V80 0x0 入口节流守卫 — V79 装机(PID 64281)278 万次修正转发(12万/s CoreText)⇒SIGKILL; 重入0x0在V74-REENT提前return使streak永不累加⇒gstreak风暴识别空转; 有几何且本tick已转发则return, 每tick每容器最多真转发1次
8cd89869b07b1d55179cc5ce2fdedd921f2a09d0	2026-10-07T03:23:55+08:00	fix: 直出 workflow push 触发时 inputs 为空, DEPLOY_TARGET/CONFIGURATION 用 env 兜底 (RClone 编译失败根因, run 37517672788)
bf1c9feb226722f65fbff43aad05a9b5d81ffe67	2026-10-07T03:16:03+08:00	v79: 守卫入口分流斩布局死循环 HANG(0x0 风暴识别前放行 V65 修正转发; 无历史兜底 1.0→24.0; V76 分流) — 触发直出 CI
71a9d95f9a186b8659aa6ded813ee3c39938b26b	2026-10-07T03:13:35+08:00	v79: 直出 workflow push 自动触发 + 硬标记 v76/v79
4b0832dc482af4610d760bbe70bfac9af5645227	2026-10-06T18:46:03Z	V78: 入口短路前移到 associated 分配之前(斩断 V77 每次 0x0 仍 new GuardState)
5dcaeb25ca3cf01a8157bfd9b2c82b96e100a9e7	2026-10-07T02:48:32+08:00	新增 iOS15 IPA 直出工作流：编译仓库当前 src/ios（含全部守卫），打包后对 IPA 二进制做 v65/v68/v69/v77 标记校验，缺失任一硬标记即标红
b3aeb1722bc126f0ae1c5d1d68b638f0b5d66f1e	2026-10-06T17:25:28Z	Auto-port OpenMinis to iOS 15 (scripts @ 9c86c01)
9c86c01300b0bc740b7bc196a946c5f89969325e	2026-10-06T16:50:37Z	V77: 入口短路前移到 valueForKey 之前(斩断 V76 重入先付 KVC 税)
d7a49f1582a692405f4272e3312726a42cba7c59	2026-10-06T14:54:28Z	Auto-port OpenMinis to iOS 15 (scripts @ a2dfb49)
a2dfb49e3f642928fe0217dd57a283de711e14cb	2026-10-06T18:08:43+08:00	V76-fix: 修正生成器使 auto-port 从根上产出 V76(终结版本混乱)
34373828ae62cb30709c4333bed40f2f16a7b021	2026-10-06T09:29:11Z	Auto-port OpenMinis to iOS 15 (scripts @ 8245ef7)
8245ef7131d6b20ad45c3486db7a09ee35e8c7aa	2026-10-06T16:52:33+08:00	V76: 选择模型卡死根治(二) — 非正尺寸直接短路斩断 layout 活锁
232670c9a5f00c17c7dd844a9ad7cb864c4f3f0d	2026-10-06T08:23:35Z	Auto-port OpenMinis to iOS 15 (scripts @ 51d31f4)
51d31f43b69591ab84127f1d0e9291dc7903b4ca	2026-10-06T15:49:54+08:00	V75: 选择模型卡死根治 — 同尺寸风暴跨 tick 持久熔断
6e3f962848b4e6d1fae50253a7422c0a7440ddc5	2026-10-06T06:56:51Z	Auto-port OpenMinis to iOS 15 (scripts @ 02f471a)
02f471a47eb1007f301d776bcaf8ce0d4e0eefd7	2026-10-06T14:35:30+08:00	V74: 启动即崩根治 — setSize: 递归哨兵斩断 gOriginalSetSize→layout→setSize 重入环
d805507e6d0a43d98151d82f40ae94abca3cef63	2026-10-06T05:53:16Z	Auto-port OpenMinis to iOS 15 (scripts @ c18f9d6)
c18f9d6f3ba8e446f6ff138652f5ad0b0049f8ba	2026-10-06T13:21:32+08:00	V73(v3, 通过 S15 反向): 非正风暴降频步长放大 64→4096, 保留 v68/v69 闸门
e538ddb5c326931df232d60a740fd3dd0fcb8378	2026-10-06T13:07:09+08:00	V73(corrected): 选择模型卡死根治改用自适应硬降频, 通过断言69 ⑨
ba468e47f49e582a2f628f11f0c1f858d2efe0f7	2026-10-06T12:55:26+08:00	V73: 选择模型卡死根治 — 非正尺寸风暴进程级全局熔断(取代 v68 降频 1/64)
9fedd26bb9ad60271fea16c1bbb9d71a2222f25b	2026-10-06T04:14:12Z	Auto-port OpenMinis to iOS 15 (scripts @ c637768)
c63776871dd463356e11db62616ccc4afa801a99	2026-10-06T11:45:53+08:00	fix(ios15): V72 —— 输入框打字闪屏(intrinsicContentSize 反馈环路守卫) + [Minis-Guard] build=V72 标记
d615fe2d27895d3650ee3079bdb1756047d87761	2026-10-06T03:18:54Z	Auto-port OpenMinis to iOS 15 (scripts @ a616283)
a616283460e469aedec2600fc4c28bcda0b5a924	2026-10-06T10:53:42+08:00	fix(guard): v71b 修 V71 版本标记里误用的 Swift 'Self' (ObjC 编译报错 use of undeclared identifier 'Self'); 改为只打印 build=V71 + pickerCap 说明, 不引用 picker 属性. picker cap 截断修复保持. 触发重建
0923fe0654944b1b7ff8dc2a5747a257421c609f	2026-10-06T10:22:01+08:00	fix(picker): v71 选择模型卡死根治 — cappedEntriesByInstance 非搜索态也截断到 maxSearchResults(上游仅搜索态截断, 非搜索态 return all 在 iOS15 List 逐行测高下触发 7000+ 模型 UIFoundation 8.5s 卡死 SIGKILL); + guard 一次性版本标记 [Minis-Guard] build=V71
90e9365533286c106c44a66376979d66189434d5	2026-10-06T01:57:42Z	Auto-port OpenMinis to iOS 15 (scripts @ c86d09c)
c86d09cd92f3c93c3d1309c362e8ecc9f5a89940	2026-10-06T09:32:58+08:00	fix(guard): v70 dedup 先转发收敛再跳过, 斩 CoreText re-entrant 卡死(选择模型 627k/tick 崩溃)
e9aa66281cb2589384512e606695f43610f1494f	2026-10-06T08:42:09+08:00	chore(ci): v69 哨兵触发 (10-06 00:42:08 UTC)
ba1ebf839a9397c9eab6dec9da61f154572ad94a	2026-10-06T07:48:43+08:00	chore(ci): v69 哨兵触发 (10-05 23:48:42 UTC)
43f788f91c027e3174d073b5ff247af0b756dc42	2026-10-06T07:38:26+08:00	chore(ci): v69 哨兵触发 (10-05 23:38:24 UTC)
4109b8199660d87770fa959b5aea71fbfcbe56ff	2026-10-06T07:35:26+08:00	chore(ci): 事故 resolved 后触发 v69 干净构建 (10-05 23:35:23 UTC)
18b127ee987edb06c3a205067b9a45b1df95066c	2026-10-06T06:42:09+08:00	chore(ci): Actions 事故恢复后重推触发第 3 次
85b78945459a2c667158aafdc61b043bd8011608	2026-10-06T06:31:47+08:00	chore(ci): Actions 事故恢复后重推触发第 2 次
095927f6d6b3f8cc26f14bf5c9e600b5b0aaa90f	2026-10-06T06:26:24+08:00	chore(ci): Actions 事故恢复后重推触发第 1 次
67b20c925a9479688320d4ae3c59cbf02c53e154	2026-10-06T06:23:51+08:00	chore(ci): 经 contents API 重推触发 CI (github.com 直连超时)
5547e17c2bdff3ac530c324a9f59ec5438ef4bd6	2026-10-06T06:18:01+08:00	chore(ci): Actions 事故恢复后重推触发第 2 次 (runner 未分配时重推)
03270674735827e63e70dbfe0a77fec4d265b861	2026-10-06T06:12:39+08:00	chore(ci): Actions 事故恢复后重推触发第 1 次 (runner 未分配时重推)
b510563d092a41ea5003208146a3419fe7158575	2026-10-06T06:10:14+08:00	chore(ci): Actions 恢复后重推 —— 记 on.push.paths 过滤导致空提交不触发
45634f2654c8ad5e6db1365e1371666d864dc48b	2026-10-06T06:07:06+08:00	chore(ci): Actions 已恢复 operational, 重推触发 CI (v69 打包)
b1d3f5265fd0c4ec4b1d584a5b025d1fc65f87e1	2026-10-06T05:34:32+08:00	fix(ios15): v69 —— 「点击选择模型就卡死」(容器工厂形态, per-container 计数全废)
d17d62552396f8e25cc945a7eff4cafcb8a60d77	2026-10-06T04:43:41+08:00	docs(ios15): 记 CI 两次 job 未启动(steps 为空、日志为空) —— 疑似 Actions 配额
922c2a5a07ae61df5559f999239fb9f5f3d54d86	2026-10-06T04:32:43+08:00	docs(ios15): 判据内记三份历史 IPA 的实跑结果(v66 报红是正确行为)
eb6883c5d8fffa7462820d6d29f230509ef10b0b	2026-10-06T04:30:32+08:00	fix(ios15): 断言72 判据只按 UTF-8 搜 ⇒ 假红(第十二次「验证手段骗了自己」)
adff1680c14f187105341997dcea1cf01b5f1a63	2026-10-06T03:57:24+08:00	docs(ios15): 判据脚本内记第十次假绿 —— 新判据自己掐死流水线 (§27)
2cc239e570a23bd2bbf3978cb37b6af91ee8afb2	2026-10-06T03:55:03+08:00	docs(ios15): §27 新判据必须先在本地全量门禁跑通再推
a5d62a0fa9c5b5f0c369b96fd8b0f3d5f101bc26	2026-10-06T03:48:35+08:00	chore: 重跑 CI (上一轮 723a98e 被 cancelled, 日志未落盘)
723a98e3eba1c57e07df21e4b45f4b2c54f7d56a	2026-10-06T03:31:54+08:00	fix(ios15): 断言72 判据自证模式 —— 修「新判据把流水线掐死」
ffe50e446d164bbbb556a0d892d2e43c0f9aa6c5	2026-10-06T03:10:08+08:00	test(ios15): 断言73 —— 编译前守卫源码指纹(把断言72 的根因一次分开)
8dd6346b16a32d8bf481efa347d0aeeb523b1338	2026-10-06T03:06:56+08:00	test(ios15): 断言72 —— 装机包里没有 v68(第九次「验证手段骗了自己」)
e72f6b6c4145b5828d7263979070c6e90922a7aa	2026-10-06T02:37:33+08:00	fix(ios15): v68 —— 拆掉非正尺寸守卫的活锁燃料与永久冻结
2f1ecc1fea0d304733e255407b6cad2ebf679b82	2026-10-06T01:17:07+08:00	v67b 收敛干净上游基线的解析: 11 处默认值收敛到 1 处(第十二次假绿的修法)
3e65f171d9315e5ade9ce043677973b364192b19	2026-10-05T09:53:16Z	Auto-port OpenMinis to iOS 15 (scripts @ 31b3e3a)
31b3e3a80610ad83a04c68cdf005a348a658aed1	2026-10-05T17:39:42+08:00	fix(v65装机): 抖/卡/闪退**三者是同一个根因** —— fabs(0.0)==0.0
ba482438d51631de005182c9f43cc0f1f8157b57	2026-10-05T09:13:13Z	Auto-port OpenMinis to iOS 15 (scripts @ f5d7c15)
f5d7c15381e07dfdedbb88f5fc793816ecf7978c	2026-10-05T16:58:54+08:00	fix(CI#162): 编译红的根因是**我自建的 clang 桩比真实 SDK 宽松**
2fc6ff90206a582ed43d2ba1bbcdfd0357787b24	2026-10-05T15:07:31+08:00	fix(CI#161): 修门禁抽取器 —— 坏的不是判据, 是把判据拉起来的那段代码
49f8007926533638a00eac888ad8e1a0fbc00d02	2026-10-05T14:17:21+08:00	v65 治守卫丢弃与误熔断: 卡字与抖动的真根因(累加那条线已治好)
f017c76cae19053a86236112544c4185c9e94783	2026-10-05T05:13:22Z	Auto-port OpenMinis to iOS 15 (scripts @ 650adb0)
650adb0e33908ba88f6d4a45e2d7163d6582a31b	2026-10-05T13:00:19+08:00	v64 切断 self-sizing 自我播种: 三十余版底层 bug 的真面目
abaa0577e0cf04cf5c8e7bfa70741b67eaf6744d	2026-10-05T12:39:20+08:00	v64 切断 self-sizing 自我播种: 三十余版底层 bug 的真面目
ef430c6a25c2c630f1855bffef298eb98b4010cd	2026-10-05T02:55:58Z	Auto-port OpenMinis to iOS 15 (scripts @ d71efef)
d71efefd2ef2ab955723688f41d907b0470fc076	2026-10-05T10:40:56+08:00	修 run#157 编译失败: 泛型类型里的 static 存储属性 —— 判据体系的第二个盲区
adefec75adf015bae764cab6319c8dbdf0464410	2026-10-05T09:51:00+08:00	修 run#156 失败: 空测被当成通过 —— 判据体系最危险的缺陷
ddec6f0aa258a6fbb9a106a30d81b9c57381f90a	2026-10-05T09:19:20+08:00	v63 几何基准: 给 62 版判据补一把绝对标尺 —— 「正常」终于有数字定义
60b45e6b5fd09db38465477975e213c9dfc694b5	2026-10-05T09:10:11+08:00	v63: 治工具卡片整屏狂跳 + 文字非流式突现 —— invalidate 唯一通道 + drift 兜底
1264324a9d8a5aa3eaa34ef141c4679e8ef35318	2026-10-05T08:05:44+08:00	v62: V62-SURPLUS 盈余镜像 —— 治「工具卡片间 ~250pt 空白终态留存」
bf5a253d1f3013866820ac960bb4ddfd6686e35f	2026-10-05T07:20:29+08:00	v61: 治整屏跳动/流式跳出 —— REUSE 就地更新 + MONO 高度单调锁
14f2d46c5c6db36fb7b7cfdf37308aa7e4c857aa	2026-10-04T22:54:35Z	Auto-port OpenMinis to iOS 15 (scripts @ 8f9fa84)
8f9fa8455406e6c0af60c843c480bf529ff24f3c	2026-10-05T06:39:20+08:00	v60.1: 修 v565 诊断段悬空 width 引用 —— CI 152 编译错误根因
d2afc09ccb7ff3a2de9fdee5ebe771180c646ccc	2026-10-05T06:17:06+08:00	v60: 采用 zhaoxiufei 3ccdff6 已验证方案 —— 宽跟随保留 + sane 推导链, 取代 v59 断源版
d86def047f3f1abab90bcbe030015dbf2b45331e	2026-10-04T21:50:31Z	Auto-port OpenMinis to iOS 15 (scripts @ 582455c)
582455c1d3ab12fe1aa705984cf768b0499bcb80	2026-10-05T05:28:09+08:00	v59: 关闭主视图容器宽跟随 —— v31~v58 全部失效的天花板
94e248ad2b8071c9729821584693cf02ce53e789	2026-10-05T04:49:55+08:00	v58: 纠偏后强制重排 —— v57.1 的位置已对, 缺的是「写完要排」
758b132dd57c519c5f4e2aeef44c32851d7f322a	2026-10-04T20:29:24Z	Auto-port OpenMinis to iOS 15 (scripts @ 2e8166e)
495ff38269cc080abfc50ee05754e4e7bb02c1bf	2026-10-05T04:15:53+08:00	ci: 补齐 TrollStore 构建链路
6a05352f812f22754c3b4d3f3cdeb6a5b2fd4079	2026-10-05T04:14:04+08:00	perf: 避免 iOS 15 回退路径每帧触发几何观察回调
2e8166eb1f13f5b6b945bd1eb0a4b76d33e48303	2026-10-04T20:05:27Z	v57.1: v57.0 纠偏**位置**错了 —— 排在 V43/V42MISS/V44 之后, 排版已按脏宽发生一次
f4b9a0493a9a70cdfab93ca18db4a6f9d9221320	2026-10-05T03:59:32+08:00	docs: 补充 iOS 15 适配改造说明
ca22ad8b0d53c73565681b08b8ed13a1986e5f5c	2026-10-05T03:58:43+08:00	feat: 将部署目标降至 iOS 15
277ae127b6651f3baad0604b6456fabe3400aa9e	2026-10-05T03:38:58+08:00	wip: 部署目标降至 iOS 15 + 新增 iOS15Compat 兼容层
6a3ad55e43b2395f79324140e6dc71ba1619de97	2026-10-04T19:03:43Z	Auto-port OpenMinis to iOS 15 (scripts @ 1cf548f)
1cf548f54867507e3f776150271f7accc2290130	2026-10-04T18:42:38Z	v57.0-CI: 补漏掉的第三处 polluted 硬编码判据 + 固化「本地全量门禁」
ee002bd56e4125117a80c34281042fa89f0ad1d0	2026-10-04T18:06:25Z	v57.0: 治每行右端被竖直切断 —— KVO 早退前纠正 textContainer 宽
144cfae08837e7ee51465ea00ca8c277dc5b085d	2026-10-04T17:11:49Z	Auto-port OpenMinis to iOS 15 (scripts @ c26e089)
c26e089256148987209312e0397e9b6f3da8d0e8	2026-10-04T16:47:42Z	v56.9: 治『那一行只剩上半 / 显示不完全』—— KVO 同值抑制把欠账帧永久跳过
ac22854793c83ce59f8128744cfb0c61f20ed7e8	2026-10-04T16:46:22Z	v56.9: 治『那一行只剩上半 / 显示不完全』—— KVO 同值抑制把欠账帧永久跳过
bd07a03567f9bd162b3f40515ba553208babcc74	2026-10-04T16:45:14Z	v56.8: 治消息流终端胶囊「卡一下才显示 / 卡一半一半显示」
73f0f7edf416299a08f9a90f8da0f9f22d13ffbc	2026-10-04T16:22:55Z	Auto-port OpenMinis to iOS 15 (scripts @ f37381a)
f37381a38bfe013ec52a0573cfb2e7957cf37e5b	2026-10-04T16:04:19Z	v56.8: 治消息流终端胶囊「卡一下才显示 / 卡一半一半显示」
ada10ea8f3ca5af9d8476e07e3a54caf75a84290	2026-10-04T15:46:36Z	v56.7: 修滑动卡字/掉帧 —— lastLines 每帧全量切分 + 资源监控 Timer 泄漏
d7bf7810a9b6bac98c263d09a724a5ca5542d1bc	2026-10-04T23:05:07+08:00	v56.6: 终端框高度下限不再按宽度乘 3/4 —— 治「空白过大」
27aac04c6405c8f2cafbad642dc6bfe2f6b93fe5	2026-10-04T14:45:05Z	Auto-port OpenMinis to iOS 15 (scripts @ b386092)
b386092a0021044966285ccdebf001e158e4d11e	2026-10-04T22:20:34+08:00	v56.5-CI: 给 v565 探针建 CI 断言链 —— 并让新门禁真的吃到干净上游
695f0d162bbd9622c8cf698f362362fe79fa629f	2026-10-04T21:54:55+08:00	v56.5: 给终端框加 [V565-CODEBLOCK] 探针 —— 先修一个认知错误
0f54d848a6aca3300d4d4bc906b9eaae8cadee5f	2026-10-04T13:41:48Z	Auto-port OpenMinis to iOS 15 (scripts @ 705b973)
705b9732085fbcecbdca4d36f20312ba039ad23e	2026-10-04T21:20:44+08:00	v56.4: 修 run#138 编译失败 + 建两道新门禁(语法/产物幂等)
cd650aa9acc4c9a76cf021b92f1e200be199abcb	2026-10-04T20:48:57+08:00	v56.3: 加 [V53-LINK] 探针 —— 定位「欠账从不上报」这个静默失败
6f2213af1c1f6480ffc18b81d69d3ad08d122174	2026-10-04T12:27:39Z	Auto-port OpenMinis to iOS 15 (scripts @ 2d6aad6)
2d6aad66a0f36984e04e24795035a96c90ca84ac	2026-10-04T20:06:01+08:00	v56.2: 紧急回滚 v56-B —— 装机实测主线程卡死 8.1s + CrashLoop 三连崩
e8717664f6b0f4d87488b29302bb5c7b2e650554	2026-10-04T11:56:34Z	Auto-port OpenMinis to iOS 15 (scripts @ df47cf0)
df47cf095ed3ae5fee35e5ffe4978ebe30cace20	2026-10-04T19:34:30+08:00	v56.1: 修 run#135 编译失败 + KVO 抑制改为真实可命中的闩锁 + 两处幂等补丁
a8b533ca057ac17c4ac13e77b5b731dbe45c5a42	2026-10-04T19:07:34+08:00	v56: 断高度拉锯(真凶) + 四处哨兵判据换口径 + _edgeTouch 认 origin.x≈16
02bf166b277ce671cc39b9e6c9487d0e4309b7e7	2026-10-04T02:31:15Z	Auto-port OpenMinis to iOS 15 (scripts @ 048496d)
048496dd6c283ebf738148fdccaecb72bc4269d5	2026-10-04T10:06:17+08:00	v55.2: 修 run#133 —— v55-C 锚点真因是「与 v54-C 同源」, 并推翻其被日志否证的病因假设
54a12719959c1ce44a5ef35a77b3baa7aa5d4888	2026-10-04T09:48:19+08:00	v55.1: 修 run#132 —— v55-C 锚点隐式依赖注册顺序
2315dac71efe01e4249a6ef42b7ca8aa2f01ee4c	2026-10-04T09:40:51+08:00	v55: 治v54 装机抓到的真凶 —— edge=0 导致 inset 没设上(卡一半) + 哨兵判据自我循环
9e3320f7876c33a21969732959dfdbf90c9d4ea8	2026-10-04T01:21:46Z	Auto-port OpenMinis to iOS 15 (scripts @ a490bb7)
a490bb7b42749f8894758461d86c47b769ce3f8f	2026-10-04T09:01:24+08:00	v54.1: 修 run#130 编译失败 —— _realW 作用域错误
3403c9426b8af39446f9a111934fb8c90b2830dc	2026-10-04T08:46:28+08:00	v54: 破 v53 的两处新死锁 + 消哨兵高度每帧往返(掉帧真凶)
bcdb613c843ae777ca60de212cd1bd492c6661ee	2026-10-04T00:24:33Z	Auto-port OpenMinis to iOS 15 (scripts @ 0bc1b1d)
0bc1b1d8f2d7a093bf49c2cfe6d8d1ade0fac975	2026-10-04T07:40:02+08:00	v53.2: 守卫脚本零依赖 + 修提示文案里的反引号(run#128)
e41a2ce553ec608f297fa6d1e3194b3d2e7e6073	2026-10-04T07:35:50+08:00	v53.1: 修 run#127 —— echo 文案里的反引号被 bash 当命令替换, 整个 run 块语法错
e60340a203b24bca5c9c85d099f14b9cb6a651b1	2026-10-04T07:29:23+08:00	v53: 治 cell 高度欠账永久凝固(C-2) + 破记忆位死锁(C-1) + 首段专项
948e919a9f13b633f6489a5739dae2cf9ff8e404	2026-10-04T07:24:50+08:00	probe cleanup
75d187238c0d27edd0e7ab0e8f52478a5cba05a8	2026-10-04T07:24:44+08:00	p
8005536360dfd4d0283f5cc686fe3886586e7e4a	2026-10-03T22:02:31Z	Auto-port OpenMinis to iOS 15 (scripts @ d9e5888)
d9e58888ddb3ce73f3f5deab52c3f7da696100af	2026-10-04T05:36:42+08:00	v52: 拦 375.7 瞬时污染宽(A+B) + 宽度来源探针(C) + 把 v38-A 从死代码救活(E)
f734a84d0b0b89f487a68a2d10df01ebb456f88e	2026-10-03T20:51:46Z	Auto-port OpenMinis to iOS 15 (scripts @ f68867b)
f68867bfc02d0b850011a223ad3425e8d2ab9092	2026-10-03T20:37:20Z	v51: 钉 textView 自身 frame 宽 + 把 V49 探针挪出补高 if
62399d9ae1e1225aab602c92ed0858d5b6c5f5cb	2026-10-03T19:35:43Z	Auto-port OpenMinis to iOS 15 (scripts @ 3c98e1e)
3c98e1e681a6787e8cfaa0069f46f6612a61ec71	2026-10-03T19:13:00Z	v50 修正: NSLog 变参传 Optional 导致编译失败 (run#123)
b48ba6abb746b7e53575c3a3552e94e5977d3518	2026-10-03T18:57:22Z	v50: 滑动时卡字/字在动 —— 宽度同源(A') + 滑动重排记忆(C)
8d957d5bb252f84476dba4bcbdea32bde9193114	2026-10-03T18:22:18Z	修正断言51 描述文案的数字漂移(boundW 族已删 / sab 11→12 条)
4fe8e0894e570c3b781030e1d5ab4c3e4c7c866a	2026-10-03T18:19:14Z	Auto-port OpenMinis to iOS 15 (scripts @ c34e72b)
c34e72b084f76ff54299b4f2a2d606616a434bcd	2026-10-03T17:56:54Z	v49: 删掉 fragW 字段 —— 两次编译错误都是"没查证就猜 API 名"
79dab992095079d26ac91efe9519af7f56b56611	2026-10-03T17:34:30Z	fix(v49 探针): NSTextContainer 没有 bounds —— 改用 lineFragmentWidth
4c1813861b26d3c5db65c8401e6146ced7ad1418	2026-10-03T17:14:59Z	fix(v47 判据): 标记计数提到段边界计算之前 + v47 反向接受产物路径
a1516d6954fa7567a7352301d784ab424bdc39e9	2026-10-03T17:01:35Z	fix(v48 判据): 段右界收到 v49 探针起点 + 加全版本回归关卡
d31410271faaec5ae3f52616fa74f6b21abed9b4	2026-10-03T16:43:34Z	v49: 【纯诊断】V49-WWRITER 探针 — 钉死「谁把 textContainer.size.width 推回 390」
d071f25c8b353acd6e0d482b4cffc6e278b8f958	2026-10-03T16:03:32Z	Auto-port OpenMinis to iOS 15 (scripts @ ec99e41)
ec99e418843e28833ff60f06666b721320776f43	2026-10-03T15:39:32Z	v48 修复: fallback 内嵌 v47 校验的段边界 —— 同一病根的第三份副本
3b74c84aed7fd5f925536ab60049fb8527bdebab	2026-10-03T15:37:11Z	v48 修复: 断言 49 文件化 —— 一份判据只能有一处实现
4b64352e82b76fc6fdb15fa11fbcd4964c16c830	2026-10-03T15:31:38Z	v48: 把 TextKit 容器宽一起钉回目标宽(log17 归因: v47 只治了一半)
0a87f64f360d24ea01ca398b48027706394a765e	2026-10-03T14:55:16Z	Auto-port OpenMinis to iOS 15 (scripts @ 3603c6e)
3603c6ef10f3a76f14dac0fcd5e0c59d643ae895	2026-10-03T14:36:28Z	v47: 统一测宽源 —— 治"终端框盖住上面的字"(log16 归因后定案)
4fdd30d4766d704a899c8112c7732bdb04c78b3b	2026-10-03T14:26:01Z	v47: 统一测宽源 —— 治"终端框盖住上面的字"(log16 归因后定案)
7a9b8763dba572cd11b83893ca8c88e8594f8158	2026-10-03T13:46:22Z	Auto-port OpenMinis to iOS 15 (scripts @ c3bb0f6)
c3bb0f6406fa23a2b02a90e188753c81dac00e53	2026-10-03T13:37:12Z	v46: 表格附件排版链归因诊断 (V46-ATTACH) — 治"终端框盖住上面的字/定时任务字一下有一下没有"
6cf73e4048834415b40e203f80b39cb2c09e3808	2026-10-03T13:01:30Z	v46: 表格附件排版链归因诊断 (V46-ATTACH) — 治"终端框盖住上面的字/定时任务字一下有一下没有"
0dfc0eaaa32298b461e07646d71ed00a00ec9edf	2026-10-03T12:25:25Z	Auto-port OpenMinis to iOS 15 (scripts @ 3f43171)
3f4317187fa0bdbdd9b65d1e65b130f6395c795d	2026-10-03T12:10:13Z	v45: 补高补到画字的那个视图上 — 治"下面一小片空白 + 字卡一半"
3b892e76fc46983fed1739f67e85db0b4ccf7fbe	2026-10-03T11:48:14Z	Auto-port OpenMinis to iOS 15 (scripts @ 07612b9)
07612b91b4439919857c2a7fdee094521a332de3	2026-10-03T11:26:34Z	v44 顺序回归判据加固(修run#37118226923 失败后的第二版测试)
c4a349f7108e6e3a56536d90782fe7bf7a30f49c	2026-10-03T11:14:06Z	v44 修复登记顺序 + 纯诊断 V44-TEXTFRAME
ff5f70ff3231f679638dc246b67761582dbadce0	2026-10-03T11:00:00Z	v44: 纯诊断 V44-TEXTFRAME — 治'终端框内容显示不全/字卡一半'的归因版
07ca6eb6207a4ab2fa1ebe14ac39d841dba7a861	2026-10-03T03:01:47Z	Auto-port OpenMinis to iOS 15 (scripts @ 262c5f8)
262c5f8f29305e364555171b8b07523df1c905f4	2026-10-03T10:36:45+08:00	v43: 测高宽度同源(治只有第一段卡字) + 涌入型全表重排节流(治终端框卡画面)
9c2257b778a635efa23098d7ed07d1486de66489	2026-10-03T01:30:58Z	Auto-port OpenMinis to iOS 15 (scripts @ dbb540d)
dbb540dd8ff3c7fc0f50f9907db1b7192a018a11	2026-10-03T01:06:30Z	v42 修复编译失败(run 37082710565): V42-GATE 裸 { } 被 Swift 吸成 trailing closure。真凶: GATE 注入点上���是 v18 补丁的注释+一个已结束语句, Swift 把 { 解析成那个表达式的 trailing closure, 于是块内 8 处裸引用全被要求显式 self., 并报 closure expression is unused。修法两条同时上: (1) 裸 { } 改 do { }(独立语句, 不可能被吸成 trailing closure); (2) 块内所有属性/方法引用加 self. 前缀, 赋值点同步加固。教训: 当时正向 45/45 全绿、反向 31/31 全抓、花括号平衡 depth=0 —— 所有静态检查都漏了, 只有 swiftc 抓得到。故新增: verify_v42 12 条编译防御判据(45->57), reverse_v42 补 5 条重现 sabotage(31->36), CI 断言 44 新增 _v42_compile, reverse_ci44 补 3 条(21->23)。验证: 四步流水线 exit0 x4, v42 正向 57/57, v42 反向 36/36, v41 正向 24/24(两代兼容), v41 反向 10/10, CI44 反向 23/23, 全文件花括号 depth=0 min=0。
b1315176f754fa8a31fedea7858bc975f349c8b1	2026-10-03T00:35:28Z	v42: 需求高度闩锁(带键精确缓存) + KVO兜底自测 + 120ms节流 — 治'最后一段字卡住'。v41实测(log10): KVO 94次触发里77次(82%) needH=0, 补齐条件 needH>1 直接跳过, superview 卡在1123.7/1006.0恒定不变(25次同值采样), 末行持续被裁。根因: ios15LastNeededH 唯一赋值点在 layoutSubviews 的三道门(!isScrollEnabled/findCollectionView/cvW>1)内部, KVO抢帧器不在这三道门里。修法: (A)闩锁带键缓存(长度/宽/hash) — 不用max, 因为UITextView复用展示更短的新文本时max会造出1600pt大片空白(v40症状); (B)KVO键不符时自测sizeThatFits, 绕过三道门; (C)自测限频120ms — 流式输出下len每帧都变, 不节流等于排版开销翻倍, 会加重'终端卡一下'。诊断: V42-GATE(三道门取值, 打在门之前)/V42-LATCH(缓存命中)/V42-THROTTLE(节流沿用)/V42-MISS(自测刷新)。验证: 四步流水线exit0 x4, v42正向45/45, v42反向31/31, v41正向24/24(两代兼容), v41反向10/10, CI断言44反向19/19, 全文件花括号平衡。断言43改为两代兼容(needle自动选self.ios15LastNeededH或_v42Need) — 不因v42换写法就删掉v41守卫。
82b3f083e8aeb804346f58dca870b91fec48cb69	2026-10-03T00:09:32Z	Auto-port OpenMinis to iOS 15 (scripts @ 2003d56)
2003d56a0fb9d91d88b0dece657d5cf3efcb1ca3	2026-10-02T23:50:26Z	v41: KVO 抢帧器补高度 — 治字只剩一半/终端框不接结果
5754a53a5ceab4ee575b63932af072b7aeaf42ac	2026-10-02T23:15:32Z	Auto-port OpenMinis to iOS 15 (scripts @ 5eefd25)
5eefd25dce167ba3569fd7e049ca8311d236aeeb	2026-10-02T22:56:01Z	v40: 高度补齐挪出 polluted 分支 — v39 修对了一半, 但补在了够不着的地方
e30a7e9d5f2e27a42966f884ac5191683641bed1	2026-10-02T22:33:19Z	Auto-port OpenMinis to iOS 15 (scripts @ 3b4a824)
3b4a8244160b75ddc4d312f513c2857891d83131	2026-10-02T22:12:08Z	v39: 帧同步补上高度 — v38 的诊断对了, 修法错了
08fbd3c3ae14f37cc38eb2200dc10636947f12cc	2026-10-02T21:48:36Z	Auto-port OpenMinis to iOS 15 (scripts @ f342113)
f342113f39b0b8ce8f0cef7446284d4a14624fab	2026-10-02T21:23:58Z	v38 修正2: 修run#98 的断言21 误报(断言锚定了补丁的旧实现形态)
a1ce47a2bba6b9d1af29126e2a38150bcf84caec	2026-10-02T21:19:16Z	v38 修正: 修run#97 的 YAML 解析失败(多行 python3 -c 破坏折叠标量)
b61ce533d23a058c5b022927d3edd33dca320f73	2026-10-02T21:17:58Z	v38: 三条独立病根同时修 (末行整段不显示 / 终端框卡顿 / 表格宽度泄漏)
18f26f8a7522647e8e86251f088f0998c608360d	2026-10-02T20:41:28Z	Auto-port OpenMinis to iOS 15 (scripts @ d15219a)
d15219a5577aa13ebbcf5b843849906ae29db65c	2026-10-02T20:10:55Z	修复 v37: attachmentBounds probe 宽全局钳位 (9 处泄漏 → superview 撑到 817/1077/100000, 每帧拉锯卡顿 + 末行裁切)
d8d039d9fe425a5420b81bfd937dff02049c295a	2026-10-02T20:10:51Z	修复 v37: attachmentBounds probe 宽全局钳位 (9 处泄漏 → superview 撑到 817/1077/100000, 每帧拉锯卡顿 + 末行裁切)
d2a54a0433066b587a2fa820cf9ca393e0ac40a1	2026-10-02T19:47:09Z	Auto-port OpenMinis to iOS 15 (scripts @ ca0617a)
ca0617a601c077ee3d36e1e3807b8b757fe38e36	2026-10-02T19:25:33Z	修复 v36: hosting 视图宽从写死屏宽(UIScreen 常量)改为与父等宽
7d6edebf6af60594c2bf92ac61fb93669e3c2707	2026-10-02T18:36:11Z	Auto-port OpenMinis to iOS 15 (scripts @ 8bf705a)
8bf705a36a0a4b4b94af55c857d2a1ef35085331	2026-10-03T02:13:43+08:00	修复 v35: hosting 视图/内容改回全屏宽(不再减 32) — 根治整体缩小/气泡不贴边/终端框折叠
64a80a1768c6edf5e5b8f63289940925174ccb82	2026-10-02T17:52:58Z	Auto-port OpenMinis to iOS 15 (scripts @ b3491e2)
b3491e28ee4573ba3562d7a5ffc426260b929edb	2026-10-03T01:31:09+08:00	修复 v34: 渲染宽回归 superview 基准 + 渲染/测高共享 contentW
41b05f7cc2c781486c0c4327f9608adef4d6ab9a	2026-10-03T00:26:49+08:00	修复 iOS15 包内 MinisFileProvider 每次被拉起就秒崩(12份 .ips 实证)
e94d9d537a40c0c6b1163d61b70d997dd05685a3	2026-10-03T00:15:40+08:00	工具: 新增本地 CI 模拟器(在推送前判定断言会不会红)
8804e6fe8381fc166268777773afd4d761a3d0eb	2026-10-02T16:09:41Z	Auto-port OpenMinis to iOS 15 (scripts @ 148e7cc)
148e7cc45bcd39814eb601fe94e5ad5d01737c7f	2026-10-02T23:53:58+08:00	iOS15修复v33.2: 修run#89 断言18 变红(断言18 自己grep 了 v33 刚改掉的那行)
62369b579ba1d6344f9a13a7f0dd58e2c65c5a7a	2026-10-02T23:38:10+08:00	iOS15修复v33.1: 修run#88 断言变红 + 堵住静默no-op
e708ef2278b248ae7821dbe62378f6cbb7e634a2	2026-10-02T23:06:15+08:00	iOS15修复v33: 渲染/测高/_realW2三处统一per-cell contentW(视图宽-内边距);v32硬编码cvW-32把气泡型326框撑到358致溢出裁字(log17 frame=326实为气泡型,终端框卡内容);三处同式→测宽==渲染宽,消除裁字/卡字/振荡
49b019d552b4b5944bf18277142dbe153d99a7e2	2026-10-02T13:37:13Z	Auto-port OpenMinis to iOS 15 (scripts @ 72a2b6d)
72a2b6d19b9a3ddbf67af7659c3eadea64499852	2026-10-02T21:06:41+08:00	iOS15修复v32: 渲染宽+测高宽钉死cvW-32,消除326↔358翻转(log15 tcW 326×132/358×115;宽度翻转→字忽隐忽现/不贴边,渲染358测高326→双引擎高度分歧1477↔1310振荡);附带修v31幂等剥离连return/}误删bug
bbd609025a45c95115ed05b0d547b137d3d0e2f7	2026-10-02T12:37:24Z	Auto-port OpenMinis to iOS 15 (scripts @ 9014f73)
9014f73936390cb5753777df880b24a3ac682b83	2026-10-02T19:56:41+08:00	iOS15修复v31: v30-A反振荡窗口过短(2s<<振荡周期~10s)致复发 → 改max-height反向锁,仅静止态拦截向下翻回(SwiftUI欠测),锁高边保底不裁字;流式/滚动期间放行保真实塌缩
7bfbec3069afa39013124b0dda54b05084b27881	2026-10-02T11:28:54Z	Auto-port OpenMinis to iOS 15 (scripts @ d1bdb2c)
d1bdb2ceac18272f55ad188731aa2239a1b80928	2026-10-02T19:03:31+08:00	iOS15修复v30: 双引擎测高反振荡(est=1176↔850 每帧翻转→列表跳动) + 流式测高节流(主线程被打满→STALLED/停止迟钝) + 输入栏假死自愈(STALLED就地重建composer,免退出重进)
a19189d2fd0f4f74d6a6d650f6797f76117f2ccb	2026-10-02T10:06:15Z	Auto-port OpenMinis to iOS 15 (scripts @ d128a4b)
d128a4b7bb27f720fccfee187ae905ef32a3955a	2026-10-02T17:42:45+08:00	iOS15修复v29: 修 CADisplayLink 停机bug + findCollectionView 死角 — 白块/裁字的抢帧防线存在两个漏洞
0d18342c69c827946be17fd7c39c391ed11dc5e4	2026-10-02T09:15:16Z	Auto-port OpenMinis to iOS 15 (scripts @ 53ba28b)
53ba28b3c6e28119c6c31a262a021301b243eff4	2026-10-02T16:46:41+08:00	iOS15修复v28: 双修表格白块(32768 probe污染sv) + 行尾裁字(抢宽后强制TextKit重排)
505929de4c8d309f11092f809ebc91857c554850	2026-10-02T03:44:44Z	Auto-port OpenMinis to iOS 15 (scripts @ 388f582)
388f58213dce3403d05bbe7196c5ab624d4453d1	2026-10-02T11:22:25+08:00	iOS15修复v27: 启用 cmark-gfm table 扩展 — 根治表格降级为巨型单行纯文本(跳字/半截字/表格乱码的真正病根)
83679f4f8636b0fa133b18fd684de81198044fee	2026-10-02T10:37:17+08:00	iOS15: 根治 AgentWidgetExtension dyld 启动崩溃 —— 编译后剔除引用 _AppIntents_SwiftUI 的 appex
eb2d3649f380d658972572669e95cd0fda2935b2	2026-10-02T02:29:28Z	Auto-port OpenMinis to iOS 15 (scripts @ 718f4b6)
718f4b6574b00eb5e4356cd8fadcab8c65eec8bb	2026-10-02T10:16:36+08:00	v26: 治横向裁切/不换行 — A) 渲染端测高改用 sizeThatFits, 不再把 textContainer 高炸到 100000 (v9 实证: 巨高容器引发连环 setSize 耗光守卫每 tick 40 次预算, 正确宽度修正 358x550.9 被连坐丢弃 48 次 -> 容器宽停旧值 -> 不换行); B) 守卫熔断收窄为仅丢同尺寸重复(自旋源), 不同尺寸修正有限放行(4x 硬上限防交替拉锯), 新 tick 才清零计数
7728aa220617ff0511c11fe0071dc6baef09f6e0	2026-10-02T01:35:36Z	Auto-port OpenMinis to iOS 15 (scripts @ abd1767)
abd1767a7ad946d619037125cdd2a4e0f07b9a22	2026-10-02T09:21:43+08:00	iOS15修复v25-fix2: 修正 v25 渲染端高度分支的 NSLayoutManager API 签名(iOS15 SDK 兼容)。
0fc621bab37642cd74f61c53f7fa08932b44760e	2026-10-02T09:02:09+08:00	iOS15修复v25-fix: 仅修正一处编译错误(不影响 v25 高度死锁修复逻辑)。
c4718345bd52487bfbd931bcb88600da127fdad6	2026-10-02T08:42:03+08:00	iOS15修复v25: 根因转向高度死锁 —— 根除末行半截字/整条不显示。v7/v8 日志实证: v22/v24 已把宽度彻底治好(idealW 全 358, 测量 w 全 358), 但半截字/字不显示/空白/闪字仍在。根因在高度, 不在宽度: (1)渲染端 textContainer.size.height 跟随 frame.height (UITextView 内部), 当 frame 初值偏小时反向截断 usedRect → 算出的需求高度永远 <= 小值 → 撑高不触发 → 内容按 358 重排需要更高却被底部裁断 = 末行半截字; (2)测量端 ios15FittingSize 的 host.view.sizeThatFits 在 SwiftUI 内容未布局时返回 0 (日志 56 次 out h=0.0) → cell 高度塌缩 → 整条消息不显示。v25 双管齐下: A. 渲染端高度分支临时放开 textContainer.size.height 到充足值, invalidateLayout+ensureLayout 后读 usedRect 得真实完整内容高, 据此撑高自身与 superview (无条件执行打破死锁); B. 测量端 sizeThatFits 前先 layoutIfNeeded, 仍 0 且有历史好值则回退, 防塌缩成 0。断言18 校验。
58d8464f5400136e912fcf9c262dc436fa830bf4	2026-10-02T00:25:31Z	Auto-port OpenMinis to iOS 15 (scripts @ b4737af)
b4737af041b9302d57d9f6f4a445160ee85fd4fa	2026-10-02T08:04:26+08:00	iOS15修复v24: hosting 视图硬钉宽度=可用宽+裁切溢出 —— 根治 730/100000 超宽气泡 (字不显示/空白/闪字)。v23 日志实测: idealW 已全为 358 (v22 maxWidth 生效), 但 sv0 仍出现 730/100000 宽帧 4 次、596/700/730 宽帧 51 次 —— 根因是表格/代码块等节点用 .fixedSize() 或自带横向滚动, 不理 frame(maxWidth:) 上限, 把 UIHostingController 的 view 撑成超宽; 原四边钉死约束又让 hosting view 跟随被污染的父宽 → 气泡超宽, 在 390pt 屏内居中后双侧裁字(字不显示)+ 右侧大片空白 + SwiftUI 每帧抢回=闪字。CADisplayLink(v23)只在绘制前抢 frame 治标。v24 改根: 不再四边钉死, 改为硬钉 hosting view 宽度=可用宽(max(屏宽-32,200))=358 + 左对齐 + clipsToBounds, SwiftUI 据此向 root 提议 358 → 所有子节点(含表格/代码块)按 358 排布, 超宽帧从根上不再产生, 内部溢出被裁在 358 内 → 气泡恒等于可用宽, 不裁字/不空白/不闪。断言17 校验。v22 maxWidth 与 v23 CADisplayLink 保留(有效部分)。
393f1ec74b1cca09a5d592a0d85d430157c716e9	2026-10-01T23:09:38Z	Auto-port OpenMinis to iOS 15 (scripts @ 38b4ced)
38b4ced135bc6a8c8b6a7075c6510acb7136ada7	2026-10-02T06:49:33+08:00	iOS15修复v23: CADisplayLink 帧同步修正 (让污染帧永远不出现在屏幕上) — v22 实测: frame(maxWidth:) 把 77% 理想宽压到 358(138次), 但表格/代码块等节点不理该上限, sv0 仍 (-49805,…,100000)14次、(-676,…,1742)28次、(-184.7,…,759.3)12次 → SwiftUI 侧继续压是打地鼠。换思路: 不再指望它不产生污染帧, 而是保证渲染的每一帧都是修正后的 —— CADisplayLink 回调发生在每帧绘制之前, 在此把 superview 的 x/宽拉回可用范围, 用户就永远看不到污染帧 (闪字的视觉根源); SwiftUI 停止写污染帧时自动停机, 不常驻耗电。容器宽/偏移等完整修正仍由 layoutSubviews 负责, v22 maxWidth 保留(有效部分)。断言16 校验。
e938c32f12058838c73e1de728d6a8498c8947f6	2026-10-01T22:17:03Z	Auto-port OpenMinis to iOS 15 (scripts @ 0d24464)
0d244642b5aeaef237f3a256ef23ffb1be92c7e2	2026-10-02T05:53:49+08:00	iOS15修复v22: SwiftUI 层治本 — v21 实测没打中: 日志 sv0 仍是 (-49805,…,100000)、(-261.7,…,913.3)、(-246.7,…,883.3), idealW 仍 100032/2378/945/915/726 → 证明超宽理想宽来自 **SwiftUI 内容树**(Text/表格在无限宽提议下不换行, 理想宽=单行宽), SwiftUI 依此把内容视图布局成宽~100000 并居中 → x=-49805。SwiftUI 内部子视图的摆放由 SwiftUI 布局引擎决定, UIKit 侧(含 v21 的 intrinsicContentSize 钳制)管不到。修法: 替身构造 UIHostingController 时给 rootView 加 frame(maxWidth: 屏宽-32), 内容理想宽被压到可用宽 → Text 正常换行、不再超宽/负 x → 污染帧根本不再产生, 抢帧拉锯(闪字)与高度错乱(空白/衔接不上)一并根除。maxWidth 仅为上限, 内容更窄按内容宽排布, 右对齐用户气泡不受影响。断言15 校验。
bd60ac937c58bf2049b08699da71dcd31242a760	2026-10-01T21:33:28Z	Auto-port OpenMinis to iOS 15 (scripts @ c0a6ac2)
c0a6ac2208ca5f6b8933120fd8d179556aba46be	2026-10-02T05:12:31+08:00	iOS15修复v21: 治本 —— 堵住 1e5 理想宽泄露 (闪字/空白/衔接不上的源头) — v20 日志 sv0 实证: SwiftUI 把气泡布局成 sv0=(-49805.0, 160.0, 100000.0, 461.67), 即宽 100000、居中后 x=-49805; idealW 实测 100032 = 1e5+32。链路: v4 把 textContainer 宽上限设为 1e5(防 CoreText 无限排版卡死) → UITextView.intrinsicContentSize 原样把容器宽当理想宽报给 SwiftUI → SwiftUI 按 100000 宽布局并居中 → 内容飞出屏幕外, 渲染端抢回/SwiftUI 每 tick 写回 = 拉锯闪字, 高度随之错乱 = 上下空白/衔接不上/部分字不显示。修法: override intrinsicContentSize 把对外报告的理想宽钳到真实可用宽(cvW-32), 1e5 不再进入布局, 污染帧从根本上不再产生 (抢帧与 KVO 降级为兜底)。注意: 不动 setSize 派生宽度(v9/v10 教训)。断言14 校验。
273cb0bb5921dcd0dc6af66272c4718d02c77f6b	2026-10-02T04:06:03+08:00	iOS15修复v20: 恢复默认沙盒内运行 (修启动闪退) — 实锤: v18(platform-application) 与 v19(仅no-sandbox) 两种形态 App 都启动即闪退打不开, TrollStore 检测页显示'沙盒外运行'已生效但仍起不来, 而 v17(沙盒内)可正常打开 → no-sandbox 与 Minis 启动逻辑(App Group 解包/shell 环境/数据目录假设)不兼容。UNSANDBOX 默认改为 0 (push 与手动 Run 都是), 保证能打开; 想实验沙盒外可手动 Run 选 1。KVO 抢帧保留 (不参与启动, 待验证防闪效果)。沙盒解除若要落地, 后续需针对性适配 App 启动逻辑, 不是加一个 entitlement 就能安全完成。
bfa1db779969386e58b6bf183a1bffe9beec81e3	2026-10-02T03:33:53+08:00	iOS15修复v19: 修 v18 启动闪退 —— v18 给主 App 注入 platform-application 导致 SpringBoard 以平台应用身份启动它, 普通侧载 App 不具备该启动条件 → 启动即退打不开。v19 只保留解除沙盒真正必需的那一个键 com.apple.private.security.no-sandbox (+低风险 skip-library-validation), 移除 platform-application / system-task-ports / memorystatus / get-task-allow; 并加 UNSANDBOX 开关: 手动 Run workflow 可选 1/0 (选 0 = 沙盒内运行的可用包, 不用改代码重跑), no-sandbox 硬校验也随之条件化。KVO 抢帧(v18 防闪)保留 —— 它只在聊天渲染时触发, 与启动无关。
84c2ab84f7a871ee73d6d0411b65055a87901faa	2026-10-01T19:19:31Z	Auto-port OpenMinis to iOS 15 (scripts @ 3b171a0)
3b171a09b3dc491d3fb8c5d955d605cfa7a9e275	2026-10-02T02:58:05+08:00	iOS15修复v18: KVO抢帧 + TrollStore无沙盒全套 — (1) 闪字根治: v17 日志实证测量端已钳 358(241次 w=358) 但 LEFT-CLIP-FIX 仍 52 次全 poll=true —— SwiftUI 内部超宽理想子元素(idealW 实测 100032/1787/665/517)在每个布局 tick 把 superview 写成污染帧, layoutSubviews 再修已晚(污染帧渲染出去一帧=闪)。v18 用 block-KVO 监听 superview.frame, 在写坏的同一调用栈内立刻改回(CA 提交前), 污染帧永远到不了屏幕; NSKeyValueObservation 自动失效无生命周期风险。(2) 沙盒解除(用户要求): 打包时向 Minis.entitlements 合并注入 platform-application + com.apple.private.security.no-sandbox + skip-library-validation + system-task-ports + memorystatus + get-task-allow, TrollStore 保留 → 沙盒外运行/全数据容器/全钥匙串; 打包步骤内置 no-sandbox 硬校验。(3) 断言13 校验 KVO 注入; FIX 日志升级 v18 并打印污染帧原始值(sv0) 供下一轮定位。
bd0707e5d8cb06cfe60da5d6fd5415ed68426ec9	2026-10-01T18:22:55Z	Auto-port OpenMinis to iOS 15 (scripts @ 5f82550)
5f825506dd0190301d53d8a537b2d213178c948f	2026-10-02T01:59:42+08:00	iOS15修复v17: 测量宽与渲染宽统一 — v16 日志+视频实证: ①LEFT-CLIP-FIX 105次全部 poll=true(污染态), v14 的 inset 适应从未触发, 高度撑高也 0 次触发(needH≤frameH 全部); ②卡住的 cell 高度 252 = 按 SwiftUI 污染宽 494 排出的文本高度, 渲染端 358 需 ~300+ → 末行拦腰裁断('上下一半一半'), 短消息则 252 里装 ~60pt 内容 → 上下大片空白; ③根因: ios15FittingSize 只拦哨兵/无限宽, 有限的理想宽 494/895 原样放行 → sizeThatFits(494) 偏小高度成为 cell 高度, 同时 SwiftUI 拿 idealW=494 布局出污染帧(拉锯闪的源头)。修法: 测量宽一律钳到 cvW-32(=358) 与渲染端 v14 修正宽一致 —— ios15FittingSize(MeasCapW15) + invalidateCellSizeIfNeeded(measCapW) + attachment containerWidth(capW15UAV) 三处; 测量==渲染 → cell 高度吻合, 污染帧消失 → 裁半/空白/衔接错位/拉锯闪烁同源根除。断言12 校验三处钳制。
261e7191c1621ee4cbc0aadbc3dac472a220dcc9	2026-10-01T17:33:16Z	Auto-port OpenMinis to iOS 15 (scripts @ 3f545c1)
3f545c152f8b3631017ca80382eeaf03de8b287a	2026-10-02T01:17:38+08:00	iOS15修复v16: 修构建失败 — v15 失败在断言11, 是我把 pbxproj 路径写错了 (fallback 以 ROOT=src/ios 运行, 实际路径 src/ios/Minis.xcodeproj/project.pbxproj, 断言却查了根目录 Minis.xcodeproj → grep: No such file; 日志第566行 EDIT ✅ 证明 AppIntents 弱链接补丁本身已生效)。路径补全 src/ios/ 前缀; 负向对照已验证: 补丁在则PASS/不在则FAIL。本版内容不变 = (1) AgentWidgetExtension dyld 崩溃修复: -weak_framework ActivityKit+AppIntents 写入 widget Debug/Release, (2) v14 老会话半截字+闪屏闪字修复: 贴边改 textContainerInset 内边距适应(不再与 SwiftUI 抢 frame 拉锯), 按 usedRect 撑高并记忆 ios15LastNeededH, 注入块内无 setNeedsLayout。
f8046d82bc0f11b3a6916b753db6b3786a92c221	2026-10-02T00:57:34+08:00	iOS15修复v15: 两件事 — (1) AgentWidgetExtension dyld 崩溃 (10份日志实证 Library not loaded: AppIntents.framework, iOS16+框架 iOS15.5 没有; 上次只弱链接了 ActivityKit, AppIntents 漏网) — fix_widget_activitykit 补全 -weak_framework ActivityKit + AppIntents 到 widget Debug/Release 双 config; 断言11新增校验。(2) 老会话半截字 + 闪屏闪字真修复 — v13 日志实证: SwiftUI 每个布局 pass 把 superview 拉回 390@0 而渲染端抢回 358@16, 49 次拉锯两态交替渲染 = 闪屏闪字; v14 贴边不再抢 frame, 改用 textContainerInset.left/right=16 内边距适应(SwiftUI 侧零改动 → 布局稳定消拉锯); 高度欠账(cell 只给 252pt, 286字符不够) 按 layoutManager.usedRect 撑高自身与气泡, ios15LastNeededH 记住需求高度抗 SwiftUI 重排回拉, 刻意不调 setNeedsLayout(闪字元凶); 断言10升级为 v14 标记(精确判定注入块内无 setNeedsLayout)
df40ce4697bb3da5c5420832c2593bf689706eb6	2026-10-01T16:29:50Z	Auto-port OpenMinis to iOS 15 (scripts @ 2539aae)
2539aae6a4a01c3a5dacc09e79df3342c08d8d0c	2026-10-02T00:04:45+08:00	iOS15修复v13: 根治 v12 四项残留 — ①贴边: 补 _edgeTouch 判定(x<=0.5且w>=cvW-1), 无记忆兜底从全宽390@0改为358@16(留16pt边距), 记忆只收带边距正常帧(防被污染成390@0) ②闪字/半截字/整行消失: 删 ensureLayout+setNeedsLayout 重排风暴, 换 invalidateIntrinsicContentSize(仅宽度真变时), 提示父布局按新宽重测高度; 断言10升级为 v13 标记
c225073a2875cac09ca5a8400051ff597ef0043a	2026-10-01T15:25:34Z	Auto-port OpenMinis to iOS 15 (scripts @ 545771c)
545771c4c5f3215a8b83fb702a72a5e84717eac9	2026-10-01T23:01:05+08:00	iOS15修复v12: 行首裁字真修复 (截图实证 superview 污染帧 494.33@-52/779.33@-194.67 被 SwiftUI 居中推出屏幕, 旧v2阈值 宽>2*cvW/x<-cvW 全部漏网) — IOS15-FIX-CLIP v3: 块首收紧判定(宽>cvW+1或x<-0.5)并还原最后正常帧(ios15LastSaneSVFrame, 精确恢复16pt边距), 在 _svW/_realW 之前执行; 断言10同步更新为 v3 标记
4b42050fa6a4150e7f787df24896194f98b6028c	2026-10-01T14:57:51Z	Auto-port OpenMinis to iOS 15 (scripts @ 328c7fe)
328c7fe3a1225bd23b13bd29e54ac87dacc557ed	2026-10-01T22:34:43+08:00	iOS15修复v11: 回退 v9/v9.1/v10 三版宽度钳制 (实测全部更差: 钳到屏宽390而真实可用宽358导致对齐更差; v9.1还破坏无限宽测量语义致单容器44131次死循环+508次10s卡死), 恢复已验证最好的 v8 行为
5f9dd47a7d5e20c8d206e9a5e2abaffe5d09813f	2026-10-01T14:24:13Z	Auto-port OpenMinis to iOS 15 (scripts @ ecb9888)
ecb9888e259ded877aef86b162fd206fa45b3dc1	2026-10-01T22:02:22+08:00	iOS15修复v10: 宽度钳制只针对离谱有限宽(647.3类, 上界2000), 放过无限宽测量(greatestFiniteMagnitude) — 修 v9.1 测量语义被破坏导致的同步死循环(单容器44131次/508次10s卡死)
88ecd5e66042b6190e76764743d25eafa1177262	2026-10-01T13:36:21Z	Auto-port OpenMinis to iOS 15 (scripts @ fe1287e)
fe1287e00253b44bc27adc281143218b0e7d6419	2026-10-01T21:11:20+08:00	iOS15修复v9.1: 修正 NSTextContainerSetSizeGuard 编译错误 — self 强转 NSTextContainer* 再取 widthTracksTextView (CI 实测 property not found on id)
7450df67d711adbd57d381a264e8f0d1f7c86748	2026-10-01T20:25:05+08:00	iOS15修复v9: 根除卡死+对齐 —— NSTextContainerSetSizeGuard.setSize 新增widthTracksTextView=true 正文容器宽度硬钳制(超屏宽直接钳回屏宽), 斩断647.3↔390 横跳风暴(CoreText 每秒上千次 setSize 主线程卡死 + 文字按 647 宽排版不对齐)。代码块容器(widthTracksTextView=false,宽10000横滚)不受影响。
35e5c601e705e28dcb84e625d9c40f88f4e4953c	2026-10-01T11:45:31Z	Auto-port OpenMinis to iOS 15 (scripts @ f4146fa)
f4146fa0867c238df91027cd6b727bcc88976e69	2026-10-01T19:26:12+08:00	iOS15修复v8: 老会话裁字真修复——superview失控帧钳制(1e7宽/x=-5e6归位, 不再把整块文本推出屏幕); 容器宽度上限1e7→1e5(防止CoreText近乎无限排版挂死); 断言10 回归防护。终结崩溃循环+字体裁切
a6ff231615f1b6483e1da178c125d2d78619189a	2026-10-01T10:53:53Z	Auto-port OpenMinis to iOS 15 (scripts @ fce4398)
fce4398940ab94bccbf8f8a9a33ef5b36a5f2719	2026-10-01T18:30:30+08:00	fix(v6): 修正左裁字注入块两处 Swift 编译错误 (ensureLayout(for:) 参数名 + 移除误加的游离闭包花括号), 重建可编译 IPA
539c2495e54ea68c55ddb3c91d12b455b440c28d	2026-10-01T18:04:40+08:00	iOS15修复v6: 老会话双边裁字修复(渲染端容器宽度钳回+强制TextKit重排, IOS15-FIX-CLIP) + 回复后大片空白修复(大幅收缩-100pt修正立即生效不再欠账, IOS15-FIX-BLANK) + 断言8/9 回归防护
782b672cf34514ffd984d1c02664608fc31736a6	2026-10-01T17:21:55+08:00	ci(ios15): 新增兜底回归断言(断言6/7 风暴熔断+1e5高度+codeTextView禁跟随) — 上游改锚点时构建立即变红, 防止卡死修复静默失效
13a6db9a5d821ccc4ee2a8f939851a4dd88962a0	2026-10-01T01:37:59Z	Auto-port OpenMinis to iOS 15 (scripts @ 1e9a0df)
1e9a0df98adc970f9ee0e5b7877766c2ff4b3fc2	2026-10-01T09:21:43+08:00	iOS15兜底v4: 1)NSTextContainerSetSizeGuard加风暴熔断(同容器同tick转发setSize>40次即锁定保留已提交几何)+容器高度上限1e7→1e5斩断CoreText fillLayoutHole 12s卡死 2)codeTextView关widthTracksTextView并固定容器宽消代码块589.3x17.3重排风暴 3)LEFT-CLIP-DIAG补superview原点诊断定位左裁字真因
39da4d17aa5db1cac0a5eb3339ca24b97b524875	2026-10-01T00:46:16Z	Auto-port OpenMinis to iOS 15 (scripts @ cb868fa)
cb868fa3ff8e934a402b31862dba89bb1c2cbf2c	2026-10-01T08:24:33+08:00	iOS15兜底v3: 1)reconcile上限500→2500(修643.7vs1198被拒→FIRST-MEASURE无限纠偏→DeferDebt自旋→setSize风暴→15s卡死) 2)FIRST-MEASURE纠偏只在文本比cell高时触发(修109↔100双向震荡) 3)LEFT-CLIP-DIAG左裁字诊断埋点
38385b4155d0f514d7ef2211b1cccc8a69f08a6a	2026-09-30T23:59:56Z	Auto-port OpenMinis to iOS 15 (scripts @ ee5c13e)
ee5c13e8ce55685e476321229cc454c6cc28a5f7	2026-10-01T07:43:21+08:00	iOS15兜底: 1)Widget 弱链接 ActivityKit(-weak_framework, 修 iOS15.5 dyld 崩) 2)SelectableMarkdownView 测量宽度钳到集合视图宽+宽度兜底消毒(斩 FIRST-MEASURE 死循环, 修发送新对话卡死) 3)MessageListInfrastructure preferredLayoutAttributesFitting 用 TextKit 实测高度兜底(修末行裁切/文字不对齐) 4)UIHostingConfiguration 替身按提议宽测量(修文字被裁) 5)PendingShare 双通道存储(修分享)
23f0f5daf9b1238c2fd2cf40eaf8c3b19a6a82d6	2026-09-30T22:49:09Z	Auto-port OpenMinis to iOS 15 (scripts @ 27148b1)
27148b13c888be571e245bf6ee0d2ef003de7182	2026-10-01T06:29:58+08:00	iOS15兜底: 1)Widget 弱链接 ActivityKit(-weak_framework, 修 iOS15.5 dyld 崩/崩溃日志) 2)SelectableMarkdownView 测量宽度钳到集合视图宽(修正文错位/裁切 不显示不对齐) 3)MessageListLayout 大幅缩小(>50pt)修正立即生效(消黑块) 4)UIHostingConfiguration 替身按提议宽测量(修文字被裁) 5)PendingShare 双通道存储(修分享)
4a659d36cea4f953c19129bdb3e65bcd24235b8f	2026-09-30T21:31:29Z	Auto-port OpenMinis to iOS 15 (scripts @ 78df094)
78df094309e0a7ac0c5330e7f8275f79c2328f2a	2026-10-01T05:13:02+08:00	iOS15兜底: 1)Widget 弱链接 ActivityKit(-weak_framework, 修 iOS15.5 dyld 崩/崩溃日志) 2)SelectableMarkdownView 测量宽度钳到集合视图宽(修正文错位/裁切 不显示不对齐) 3)MessageListLayout 大幅缩小(>50pt)修正立即生效(消黑块) 4)UIHostingConfiguration 替身按提议宽测量(修文字被裁) 5)PendingShare 双通道存储(修分享)
817909412ff7b9598dfc03c27bd027ac64c9b181	2026-09-30T20:43:00Z	Auto-port OpenMinis to iOS 15 (scripts @ 679927d)
679927dfad90a3f81975ef1ba4fb03b6a799c2f1	2026-10-01T04:22:53+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 根治: 1)把 UIKit 压缩尺寸哨兵(1.8e308)宽度换成集合视图真实宽(修文字被裁+黑块) 2)PendingShare 改双通道存储(修分享无数据) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
5fbde733ad455dc75a6aad9001f4049a663f2d6f	2026-09-30T19:45:23Z	Auto-port OpenMinis to iOS 15 (scripts @ f32bdcf)
f32bdcfab5930fe833d3ace00a7b2d19ffaa9f20	2026-10-01T03:24:19+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 根治: 1)把 UIKit 压缩尺寸哨兵(1.8e308)宽度换成集合视图真实宽(修文字被裁+黑块) 2)PendingShare 改双通道存储(修分享无数据) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
158c90089d8c05dbd0c0f3f3e78557556454e41c	2026-10-01T03:12:11+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 根治: 1)把 UIKit 压缩尺寸哨兵(1.8e308)宽度换成集合视图真实宽(修文字被裁+黑块) 2)PendingShare 改双通道存储(修分享无数据) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
cc33f97447d5724db30205a8f9c62da0a4084f5c	2026-10-01T02:56:08+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 根治: 1)把 UIKit 压缩尺寸哨兵(1.8e308)宽度换成集合视图真实宽(修文字被裁+黑块) 2)PendingShare 改双通道存储(修分享无数据) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
11c8c2ef87af5a13c0213177e5bda5b4b3e91a17	2026-10-01T02:52:43+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 根治: 1)把 UIKit 压缩尺寸哨兵(1.8e308)宽度换成集合视图真实宽(修文字被裁+黑块) 2)PendingShare 改双通道存储(修分享无数据) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
41f7d5454e2c97f87fbc2a185d02e85a8ba4f68c	2026-10-01T02:51:45+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 根治: 1)把 UIKit 压缩尺寸哨兵(1.8e308)宽度换成集合视图真实宽(修文字被裁+黑块) 2)PendingShare 改双通道存储(修分享无数据) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
0a14ca0e5dd09b4607549098e98003723ad9350d	2026-10-01T02:43:53+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 根治: 1)把 UIKit 压缩尺寸哨兵(1.8e308)宽度换成集合视图真实宽(修文字被裁+黑块) 2)PendingShare 改双通道存储(修分享无数据) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
295bddcfeb4af3d8b20a4d7569d1f6cf04c78a67	2026-09-30T18:29:27Z	Auto-port OpenMinis to iOS 15 (scripts @ 762aa1f)
762aa1f8a413b8800a63ebf5ed93987abb6c60b6	2026-10-01T02:06:47+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 三项合一: 1)测量前后诊断日志 2)打包对齐高部署目标扩展 MinimumOSVersion 3)分享扩展加 8s 超时兜底 + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
9614b22abc923b7eb6a9a9568dca90e08835561a	2026-10-01T02:02:40+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 诊断版 v2: 测量前后各打一行日志(抛异常也能拿到数据) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
4ba8a1f00e8e1b14d9393a5f92c214af20549db1	2026-10-01T01:55:46+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 诊断版: 替身测量打宽度日志(cellW_cvW_idealW) + 打包对齐高部署目标扩展 MinimumOSVersion 消除 iOS15 反复 dyld 崩溃
eb80f52dfa2c51b066df67dfef16dd49689798fe	2026-09-30T17:35:27Z	Auto-port OpenMinis to iOS 15 (scripts @ b311c43)
b311c43d6e2d0741abf4a895d5f917f72ab9ff4d	2026-10-01T01:13:57+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 修 v2.2: 上次实现调 host.view.systemLayoutSizeFitting 因四边约束反向测量导致无限递归栈溢出(EXC_BAD_ACCESS), 改为不经过布局引擎的 sizeThatFits + 递归保险
f8cf351eeea2c26b588a8260b45d95ebd9aa6721	2026-09-30T16:59:23Z	Auto-port OpenMinis to iOS 15 (scripts @ 2d76ffb)
2d76ffbbd672cd4461a01cd7b770697c625f1e0e	2026-10-01T00:36:51+08:00	运行时修复: UIHostingConfiguration 替身补 systemLayoutSizeFitting (按提议宽度测量) —— 修复消息单元格宽高算错: 文字左右被裁/单元格间黑块/内容不贴底
f2aa8620744549e225aec8262e3042a20e75419f	2026-10-01T00:21:28+08:00	打包修复: IPA 按各 target 的 .entitlements 做 fakesign 签名 (App Group/Keychain/iCloud 等), 并硬校验 group.com.openminis.app 必须写入 —— 补充: 扩展用 CFBundleIdentifier 末段匹配 entitlements, 修复 3 个扩展(MinisShare_AgentWidgetExtension_MinisFileProvider)拿不到 App Group
989a2032b81926e375ebec6327c26007a8c5f827	2026-09-30T16:11:26Z	Auto-port OpenMinis to iOS 15 (scripts @ 1cb5a85)
1cb5a8555427beb1d227b846114167e952044fc7	2026-10-01T00:00:02+08:00	打包修复: IPA 按各 target 的 .entitlements 做 fakesign 签名 (App Group/Keychain/iCloud 等), 并硬校验 group.com.openminis.app 必须写入 —— 修复 TrollStore 预览里无 App Group、共享容器不被创建的问题
a96c26dda8e442f3a912e416f266cb1ae13b8292	2026-09-30T23:55:31+08:00	运行时修复: onGeometryChange 改为 iOS15 回填而非删除 (修复 inputBarHeight 恒 0 → 最后一条消息被输入栏盖住/底部黑区) + 回归断言5
7267a56c4e879e3e4bb76cde24bcc687b50844e2	2026-09-30T15:01:29Z	Auto-port OpenMinis to iOS 15 (scripts @ 54e35d9)
54e35d954621c7829f5654134c1d62d7521ff16d	2026-09-30T22:36:02+08:00	构建修复: 同步 iSH/proot 子模块指针到上游 1.14 (修复 ISHKernel.m 未声明函数: ish_set_memory_status/ish_set_anon_page_limit/ish_guest_forks/path_cache_stats/ish_fork_rate_stats/ish_set_fork_rate_limit)
a24cd6ae4325e33e82fef0fa0cf8052ff3e3b8f5	2026-09-30T21:45:41+08:00	iOS15 移植: 修兼容层 PhotosPickerItem.supportedContentTypes [Any]->[UTType] (收尾 2 错)
89a8b618caf5ff91b35c0d47b15e02881ae8b9b2	2026-09-30T21:21:11+08:00	iOS15 移植: 拆分 AIChatView 1180 行 body 为 9 段, 根治类型检查超时
b40cba95336396e0d2db35b9a4162f7e1d6d336e	2026-09-30T20:56:42+08:00	iOS15 移植: 抽离全部 3 个大型 onChange 闭包 + 扩大 AIChatView 诊断
b32b020f3042ebe455eb2edd781b3be2f2f2f541	2026-09-30T20:42:31+08:00	iOS15 移植: 抽离超大 onChange(of: scenePhase) 闭包体, 解决 iOS17 SDK 重载歧义导致的类型检查超时 (收尾最后 1 错)
d3fc221db75619f4ce3c0e7477b2e94165f1faf3	2026-09-30T20:24:43+08:00	iOS15 移植: 兜底脚本 v2.1 — 撤 v2 误插的空 guard / LSR 通用化(兼容 String 污染) / 垫片加 @MainActor / FileProvider 三参 init / 补桩与守卫 (降级 Task.sleep(for:) 消除类型检查超时)
c551768f6808b195c1e5bfdc00502ac8c0989eca	2026-09-30T20:07:33+08:00	iOS15 移植: 兜底脚本 v2.1 — 撤 v2 误插的空 guard / LSR 通用化(兼容 String 污染) / 垫片加 @MainActor / FileProvider 三参 init / 补桩与守卫 (收尾 14 错)
603a054fb31117529d4c7b4bb02e98e95d3330b9	2026-09-30T19:38:27+08:00	iOS15 移植: 兜底脚本 v2 — 修 LSR 插值字面量 / 工具栏分支 / 深链垫片注入本文件 / 调用点守卫 (消除 32 个真实错误)
6f9e40245fac0c3c3303101497fd0ad614022294	2026-09-30T18:50:04+08:00	iOS15 移植: 新增 ios15_fallback.py 确定性兜底脚本, 替换 autofix 自动降级循环 (第三阶段)
35a0784ea5d422dc713c71ca034d41fd43be1792	2026-09-30T17:41:28+08:00	fix(ios15): 修复 1.14 编译失败的根因
8b5cf4f80e16cbfb964ae5c39b87b0c32dd5161b	2026-09-30T17:02:05+08:00	fix(ci): 移植流水线仅在编译成功后才回写 src/ios
86f70e7981a35b8a6e19621de063d9e56a8f5039	2026-09-30T17:00:48+08:00	revert(ios15): restore buildable src/ios (1.14 auto-port broke compile)
d0357542159ba2d23b4df472725d92803c33d32b	2026-09-30T16:20:50+08:00	ci(ios15): add upstream-version watcher (daily check + issue reminder)
471e85344e591e23dfa5f047e20812e3158ed9da	2026-09-30T08:15:39Z	Auto-port OpenMinis to iOS 15 (scripts @ 01cd217)
01cd21771400ca12d4880892ab497200f0b5f7c1	2026-09-30T16:13:41+08:00	ci(ios15): pin upstream to tag 1.14 + build-time self-checks for runtime fixes
7293e510e050751869848231d28f6c6063cb9eb7	2026-09-30T07:46:02Z	Auto-port OpenMinis to iOS 15 (scripts @ b0f3e7f)
b0f3e7fa41fcff22658cb95c69f18701ca04b054	2026-09-30T15:44:39+08:00	ci(ios15): wire runtime-fix patch into port pipeline (sync OpenMinis 1.14)
0d95df6d9530c1ce08a8eb477a8a90fa4d6450ea	2026-09-29T23:37:33+08:00	fix(ios15): lazify remaining tool-result chunk containers (shell/non-shell/diff) to stop gradual OOM as chunks grow
b4c0661d5631ebab4d1a2e6f3fd4c805d4030a6c	2026-09-29T23:13:48+08:00	Merge pull request #408 from OpenMinis/v1.14
f912bc9aba77d247e0b3b3073f1d29ef6e8f00db	2026-09-29T22:53:14+08:00	fix(ios15): correct UIDocumentPickerDelegate protocol name (was UIDocumentPickerViewControllerDelegate)
110b35f260310fa8cbc0d94601eb45e1ce169c81	2026-09-29T22:52:33+08:00	docs(ios): fix the item count in LOCALIZATION_STYLE and give a neutral reason for not round-tripping the catalog
960946adb2032b597350121f9c84e815f47afb4c	2026-09-29T22:43:15+08:00	feat(android): chat, agent, speech, settings and interface work through the 1.14 build
5b8fb60e386a4f8bd7282cbfe6af735ad5836e75	2026-09-29T22:43:14+08:00	feat(android,providers): provider, OAuth, thinking and storage work through the 1.14 build
2c567fd2fa115a6f9b227dbe88304619c912f33b	2026-09-29T22:43:13+08:00	feat(android,backup): backup and restore work through the 1.14 build
db903fc784893b87056c9db8091820bad7b7d58b	2026-09-29T22:42:53+08:00	feat(android,sandbox): advance proot and the sandbox / native-offload work to the 1.14 build
3683560434b041ac25e2645c597b9ab0d4835701	2026-09-29T22:40:05+08:00	chore(publish): comment cleanup, and keep process docs, one-off harnesses and dev tests out of the mirror
80975903948804bf04ecb8121a7d91ec5d5bdb49	2026-09-29T22:29:08+08:00	fix(ios15): merge PHPicker code into compiled iOS15Compat (stray file was never in pbxproj) + replace all remaining Material to kill black blocks
9de4b00dfb2e8178bcbbfed734cb01dc218ad1ec	2026-09-29T22:18:10+08:00	chore: strip user data, chat IDs and personal handles from comments and tests; complete third-party licences
3ebb4aa70bea1ab65688d7160a80629da1f1c947	2026-09-29T22:06:44+08:00	fix(ios15): replace iOS16+ NSItemProvider async loaders with iOS14+ callback variants in PHPicker bridge
7fde6b23a3a239b63f9b1a55034a2cc240ee4fb3	2026-09-29T21:50:51+08:00	fix(ios15): add import UIKit to PHPickerView (UIApplication/UIDocumentPicker needed by UIKitPickerPresenter)
5c2cf9fd507273bee8e688037e4d5d9653d78923	2026-09-29T21:38:27+08:00	fix(ios15): present photo & document pickers via UIKit (SwiftUI sheet/fileImporter silently dropped on 15+-modifier chain)
1bdae5577b04eef3f6fafbe44f40872ade2579f6	2026-09-29T21:37:30+08:00	docs(build): document the rclone and Metal Toolchain steps
7c4e3b93d23f66f64d7c5ae4ab85d39a81817d83	2026-09-29T21:03:42+08:00	build(ios,ish): pin iSH to the master merge of the 1.14 source
1d61d3417ae5b948df7b852b271ffe9ea5fdfc97	2026-09-29T21:02:37+08:00	fix(ios15): restore photo/video picker via PHPickerViewController (port stripped .photosPicker)
0ebaf469884f0eac6028dc62b31e7557f3021ee4	2026-09-29T20:58:42+08:00	chore(scripts): a mock fallback provider, and stricter locale batch checks
61e843a492ebaa7a4a79fc42de73ca25f2f9cbcc	2026-09-29T20:58:42+08:00	feat(ios): agent, chat, iCloud sync, intents and localization work through the 1.14 build
229f00554b5053f57b590d4c011a9c498277a4e1	2026-09-29T20:58:30+08:00	feat(ios,providers): provider, OAuth, thinking and voice work through the 1.14 build
12bd7ef72ec70eb1918053aa15bad0deafab746a	2026-09-29T20:58:24+08:00	feat(ios,backup): backup and restore fixes through the 1.14 build
ee2419c528a9aca37f2c621a4ed20adcacb73817	2026-09-29T20:58:13+08:00	build(ios,ish): advance iSH to the 1.14 build's commit, with the sandbox and native-offload work
fc0f69e9aabe49721cbd6021307f9005bf8add98	2026-09-29T20:47:29+08:00	fix(ios15): use LazyVStack for tool/file/chunked output to prevent OOM crash when opening large files
c4de1f2ab4669c770350650d96134e286d6e1e87	2026-09-29T20:00:18+08:00	fix(ios15): replace Material backgrounds with solid system colors in chat views
314442341bca36a7d125a800fdb864d3b0cd9d90	2026-09-29T19:48:31+08:00	TrollStore: fall back share transfer to app sandbox; support 'Open in Minis' for any file
c907c282fb012522ece35d96720f18d93c5cf59d	2026-09-29T17:51:42+08:00	fix: graceful App Group container fallback for TrollStore (no profile => containerURL nil crash)
f4c799509d7e1420eb58d1801845fdd3eb06fb5e	2026-09-29T17:21:09+08:00	fix: restore closure param names lost in extraction; PhotosPickerItem shim supportedContentTypes -> [UTType]; break up complex log interpolation
aa7c84afc6e6736cdb1d89ae8ed815d8cb664a75	2026-09-29T17:06:33+08:00	refactor: extract giant closures out of AIChatView.body to stay under Swift type-check budget (iOS15 target)
255a24feac02ab02ab24535bceee3207d0204112	2026-09-29T16:44:02+08:00	fix: iOS15 port round2 — move ToolbarContentBuilder conditionals into Group (buildIf is iOS16+), simplify AIChatView type-check-heavy flatMap
8e222a877fee265cb7e9d92b4acdeebcbe9b6da4	2026-09-29T16:23:25+08:00	fix: iOS15 port — availability guards for iOS16/17 APIs, LocalizedStringResource conversions, dedupe MinisShareLinkButton, fix AppDelegate return, split ToolbarContentBuilder if/else
8c88cbc108608fc970654374e6c88d2f5d7ac2a0	2026-09-29T15:41:10+08:00	fix: keep MinisFileProvider extension at iOS 16 (NSFileProvider iOS16-only APIs); restore UITests deployment to 15.0
e313c492fa8adc1eeec7b5b540b911a385d67211	2026-09-29T15:18:38+08:00	fix: build RClone.xcframework in ios15-build (install Go 1.25, run build_rclone_ios.sh)
ca997cc344f32626d7d30766a48cac6c79ef2515	2026-09-29T15:04:44+08:00	fix: install meson to PATH (drop --user) in ios15-build; add meson sanity check
9503e302a04f546314ad52c5760684ca097ae02f	2026-09-29T14:49:15+08:00	fix: install lld for iSH vdso cross-link (-fuse-ld=lld); set iOS15 default in ios15-build
e9bb9adf053d04f49c4843e2803f6517e13eb7ff	2026-09-29T14:31:05+08:00	fix: macOS runner PEP668 — pip install --break-system-packages meson
c449b11026323a22fc856856d1dc84b7d177dcc3	2026-09-29T14:25:23+08:00	Add iOS 15 TrollStore build support
87d7115fe49d98b7969ac8cac45a3a5fe075fffb	2026-09-28T22:38:51Z	Auto-port OpenMinis to iOS 15 (scripts @ 3e55b0f)
3e55b0fd3149f22567b6c0b3e2ea65382a2353ba	2026-09-29T06:37:20+08:00	Add files via upload
620831d3e175ed531fc2f83a21fcad6acaa6d071	2026-09-29T06:36:30+08:00	Delete scripts/ios15_port.py
d86c995a9f59f5b5d51e33d9ff1bef0a9e9175f7	2026-09-29T06:36:13+08:00	Delete scripts/ios15_port_v2.py
d9b231b3a5de93cac3d1f33f69f17f99f96b8206	2026-09-29T06:35:58+08:00	Delete scripts/fix_fileprovider_deployment.py
05ea4ecb18fdec9efe63430295b048568bff312f	2026-09-29T06:35:43+08:00	Delete scripts/autofix.py
f8531a4e97f0426697b0a24643046e212e435fe2	2026-09-29T06:35:00+08:00	Add files via upload
fbe81067b60b9e8b94195b43ba3c42bb421fbc37	2026-09-29T06:34:29+08:00	Delete .github/workflows/port-and-build.yml
a3a7f37b7c89d5d05f5ed8e46727b7be936a6d51	2026-09-28T22:14:08Z	ci: add cached iOS 15 build workflow with compiler-error diagnostics
3aa40306918dbf763e6e143a4010f1ff4a78c209	2026-09-28T21:36:46Z	Auto-port OpenMinis to iOS 15
85520e22339a6a603b5cd97ae75dd8b3024afbe3	2026-09-29T05:34:44+08:00	Add files via upload
99c53facf432203950fe8086ca65b629467cad99	2026-09-29T05:34:16+08:00	Delete .github/workflows/port-and-build.yml
5f3b3992ab510a2b6f1ba483d7c87e024ead5d71	2026-09-28T21:18:21Z	Auto-port OpenMinis to iOS 15
41c8174d377ee0b052e655bd5fd0aac44440aa4e	2026-09-29T05:16:03+08:00	Add files via upload
53d3f6cde6eeb901ea3a28671146b2e54e44a3ce	2026-09-29T05:15:19+08:00	Delete .github/workflows/port-and-build.yml
6685d1ed7fe3b2c0a2dc4d8f357758d9e45bae7d	2026-09-28T19:52:09Z	Auto-port OpenMinis to iOS 15
9609243790e20c74176c4706451c6af218431466	2026-09-28T19:15:35Z	Auto-port OpenMinis to iOS 15
10aedc57b275848307798b1f2af7b6e85eef473c	2026-09-28T18:36:11Z	Auto-port OpenMinis to iOS 15
8851989c50f3f1de9f8ee5f158218e35f7d41ba2	2026-09-29T02:34:13+08:00	Update port-and-build.yml
7e08eeaadb9d769d4d08f5f8b5a7cae331a12e30	2026-09-28T18:06:02Z	Auto-port OpenMinis to iOS 15
934cef530342dae42f22cc272493a69c623b9fc1	2026-09-29T02:03:36+08:00	Update port-and-build.yml
08e60a437180a075bc29a8300f8ee7736bcca195	2026-09-28T17:55:21Z	Auto-port OpenMinis to iOS 15
6813a57e5555babac92a52f3e4bfe6d350de1143	2026-09-28T17:45:08Z	Auto-port OpenMinis to iOS 15
d64f168d91cf67d1aba54f528975c2432b79f01c	2026-09-28T17:22:10Z	Auto-port OpenMinis to iOS 15
657d530bb94be2b5925bdaa7ffb2518dccdf823d	2026-09-28T16:46:42Z	Auto-port OpenMinis to iOS 15
ab3cec17f2046424b2454fd8e3f60271e6e891d9	2026-09-28T16:29:07Z	Auto-port OpenMinis to iOS 15
0b6fd92f1243e695d5a58ed0cd25dbca41bd56e3	2026-09-28T16:02:03Z	Auto-port OpenMinis to iOS 15
8bfc4226eed3f5d06e6ea6c974f51ca01c40f93b	2026-09-28T15:26:21Z	Auto-port OpenMinis to iOS 15
22aa38c5af65b916df68e921be717b5131a3590a	2026-09-28T15:01:48Z	Auto-port OpenMinis to iOS 15
a7a6a02438a0a8048a5cc892d20e27e6b0adc808	2026-09-28T22:59:54+08:00	Update port-and-build.yml
e4c79a5d6da6a3513ca1d51f420be4c1ac5bd57e	2026-09-28T22:35:19+08:00	Update port-and-build.yml
49ac177a00e26f749f980b76df4a9c863d598038	2026-09-28T21:36:33+08:00	Create fix_fileprovider_deployment.py
0afcf1aa71da4460c65c31bacd0545ef6cd30594	2026-09-28T21:30:58+08:00	Create port-and-build.yml
ce6a582b24728a8b6c59f111f802a1d5a0ec635f	2026-09-28T21:29:27+08:00	Delete .github/workflows/port-an-dbuild.yml
ceff96073c40c4bab98e6ea70928edbcd0b96583	2026-09-28T21:06:32+08:00	Update port-an-dbuild.yml
2d6642b1c119a537f791a1c8e31a56ddbc80e9b6	2026-09-28T20:48:11+08:00	Update port-an-dbuild.yml
f80bc8d990c9d1f7e1d2c8322a168b57989b48c8	2026-09-28T20:39:52+08:00	Update port-an-dbuild.yml
6e95825bd3a8758742a6f7f3bd46a4b3f61a5143	2026-09-28T20:35:45+08:00	Update port-an-dbuild.yml
05ab80f41540e7e3235e00d6ed0c1ae52214b62b	2026-09-28T20:34:54+08:00	Delete .github workflows directory
959a965c3e36559ddeb20a5d20e85482d5fddd59	2026-09-28T20:27:50+08:00	Update port-an-dbuild.yml
d737965c461abf82d5fcdb644029ac0eb6e700df	2026-09-28T12:09:33Z	Auto-port OpenMinis to iOS 15 (NavigationView + 去掉 presentationDetents)
42e9655b310228274a9db4c5e7084ef919fb9680	2026-09-28T20:05:02+08:00	Create port-an-dbuild.yml
4ec06ce7a608a0360abdff41958ef1f9dfc2ba56	2026-09-28T20:03:16+08:00	Create ios15_port.py
17ba9c3379c61b7cc4b72026b0ca4cbedf8a4f16	2026-09-28T19:22:22+08:00	Create build-ipa.yml
cd8b89bf087c1cd50996ce9d921e1fda06b51561	2026-09-28T19:18:11+08:00	Create audit- ios15.yml
4ef29002e88db1e20e462ec2ff46916e8a7dcb45	2026-09-02T02:19:16+08:00	Merge pull request #289 from OpenMinis/v1.13
7414c0d6e8ec52e51d158f622e4379654872e7b5	2026-09-02T02:14:03+08:00	build(ios,ish): track the iSH submodule on master
18bca81b09b4712fa54222eb84f98e3da66e590c	2026-09-02T02:06:55+08:00	chore(scripts): add the locale add/register/validate helpers
50a03d0abe5b30ae04d3799640edd24dc2cb3113	2026-09-02T02:06:34+08:00	feat(android): chat, markdown, theme and interface work through the 1.13 line
1773abc5514691282a8ea4f5319a836ea51c250f	2026-09-02T02:06:15+08:00	feat(android,providers): provider, thinking and storage work
7b00d5c5610d9de9239de195e92e4e97ebe4ec87	2026-09-02T02:06:01+08:00	feat(android,backup): backup & restore to folders and rclone remotes
a8d6ef6e1d5059036e8cdda13308afc7ae8db44f	2026-09-02T01:34:28+08:00	chore(ios,ish): track the iSH JIT-recovery test, point the submodule branch at the current line, ignore the rclone build artifacts
ada340b7a7147e31c599704c2248c25e152ec7d6	2026-09-02T01:33:56+08:00	feat(ios): chat, sync, usage, intents and interface work through the 1.13 build
421699de3703276ca042c96734f0cf6916829683	2026-09-02T01:33:29+08:00	feat(ios,providers): provider, voice, thinking and model-routing work through the 1.13 build
6c08b189c982a333a3559e18fea300427fa2a756	2026-09-02T01:33:02+08:00	feat(ios,backup): backup & restore to folders and rclone remotes, with a streaming package writer
2df21b6a68bd037c9a9b8c4c0a2e32ffc6c5cc17	2026-09-02T01:32:31+08:00	build(ios,ish): advance the iSH submodule to the 1.13 build's commit, and pick up the kernel/terminal fixes
09fc199928de0f26685e766c34e6d541c7a69e5a	2026-08-19T02:21:29+08:00	Merge pull request #243 from OpenMinis/v1.12
eaea780b9ef475797e8443589d218695637404c1	2026-08-19T02:15:56+08:00	docs(ios): drop dangling ICloudBackupManager references in comments
b4d7ff596891d04d5144b22645f21b05827b1ee3	2026-08-19T02:12:14+08:00	fix(android,file_read): report the real line range after truncation, with next_offset
ac462aea23ab92797b4c9d04aa8de472b8197cf8	2026-08-19T02:11:50+08:00	build(ios): hold back the iCloud backup/restore surface too
2a7965558fbb593c80cf000105c29536de73905c	2026-08-19T01:53:31+08:00	docs: drop the Chinese backup/group design docs from the mirror
1b3e8215324fca969bdb0e8d815f16029e5c490c	2026-08-19T01:42:33+08:00	build(android): hold back backup/restore, and fix the debug-skill inputs
112144adf832c60b8520dc8edea427b6918f82ae	2026-08-19T01:42:08+08:00	build(ios): advance the iSH submodule to a commit with ish_set_fork_guard
ab273cb2962850405e84567691333c0e7df70332	2026-08-19T01:06:44+08:00	feat(android,core): storage, providers, sandbox and diagnostics
995ac6abda098268d70d8c80db45ef1050115c45	2026-08-19T01:06:35+08:00	fix(android,speech): recognition and read-aloud reliability
935f02f5b0e63e7159b4ca5b3458a0dea10379b2	2026-08-19T01:06:25+08:00	feat(android,ui): chat, settings and session surfaces
8c8586d8928eb69a1a63ac998736435c9d19cdb4	2026-08-19T01:06:17+08:00	feat(android): backup and restore
2c6ca20f6d63e4c588ad10e5b0c80e6e9193a56d	2026-08-19T01:03:14+08:00	feat(core): storage, speech, sync and diagnostics through 13 Aug
b7af9e970c6ab7f9b005b0815c656ba437d54dad	2026-08-19T01:03:03+08:00	feat(ui): chat, agent loop and interface work through 13 Aug
df9cb59b1a5bb377d17f6b2ac70bf01b3a3216e0	2026-08-19T01:02:53+08:00	fix(sandbox): sandbox, native offloads and build inputs through 13 Aug
850cad1300528e2fa63c8b8dbc2abc6f288a2d48	2026-08-19T01:02:41+08:00	feat(providers): provider, sign-in and thinking-rule work through 13 Aug
9cf3a855fecd27bb5735b84cacbd56852a3ab8dd	2026-07-25T23:21:22+08:00	Merge pull request #91 from OpenMinis/v1.10
3b9015e28632cc6434e8739303f66c6b1c6fcbcd	2026-07-25T23:19:56+08:00	docs: state that this mirror does not accept pull requests
3bfca34e9be03e998c94b41448cb948e0fab31e0	2026-07-25T22:59:07+08:00	Merge pull request #90 from OpenMinis/v1.10
d9d4d5bc9db9723eeab842bb61be6c0d689b844c	2026-07-25T21:35:58+08:00	feat: open-source the Minis app
a1a4c5b87737b1fe64feb88d4c55f71892226476	2026-07-04T15:16:30Z	fix: update TestFlight link to correct URL
3208336309b4ebb95bf8b50f5240d854b69bd6c5	2026-04-26T17:20:07+08:00	Generalize platform messaging
82bab775b09a6e811dc9f93c2f325e8d5c4d94f9	2026-04-26T09:00:13Z	chore: remove old yml issue template
18edc9d4893f65c815c12a7a44ba892028f1d7e2	2026-04-26T09:00:11Z	chore: switch to markdown issue template for URL prefill support
6124bedce89202e070b3ba646412125f6889b00f	2026-04-26T08:53:30Z	chore: add Minis bug report issue template
03c5647800dbc718f9f4d679634ad1c4f5d03454	2026-04-25T22:52:14+08:00	Polish README copy
df38686a096d5ce1c00742b9932da8177798b08e	2026-04-25T22:51:14+08:00	Update Telegram group link
3ea6f6c3c037cdb6d081497256ecee0cdf4b58de	2026-04-25T22:36:07+08:00	Initial commit: add README
```
