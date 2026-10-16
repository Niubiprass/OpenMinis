# 代理任务 · 完成本轮自动压缩与队列保护源码修复

- Session: `4B8A21E8-E4BC-4E9A-BA4E-7021B2F8EDFF`
- Exported entries: 84 / CLI reported 84
- Export source: minis-sessions-cli --full, paginated 100 per page.
- 这里是历史原话，包含错误判断、失败尝试及工具摘要；不得把旧结论当作当前事实。
- 这是纯文本记录备份，不是可直接导入 App 的数据库；CLI 不返回附件二进制或原始工具调用结构。

## 1. user · 2026-10-15 18:58
Message ID: `2538C7F0-5BB4-43BC-B569-6D500306C117`

当前轮OpenMinis修复必须同时修自动压缩，不是下一轮。项目/var/minis/workspace/OpenMinis-v64（可能无.git）。请实际审查并完成已有自动压缩未完成本地补丁，查ContextPolicy、摘要管理器、AIChatViewModel压缩与queue drain链。已知源码已有min(budget,window)，不要错误归因217600；SSL用户主动断网不能当未及时触发根因。重点修中文token预估count/4低估、分段递归previousSummary不丢、压缩失败结构化结果与队列保护/合理重试且不无限自动重试、软硬窗口触发。已有其他agent可能编辑布局文件，禁止动布局/ChatStore.swift，不覆盖其改动。允许修改压缩相关与AIChatViewModel必要部分，先读当前文件，保留现有补丁。补可运行回归测试，写docs当前状态，明确源码测试不等于Swift编译/真机。不要推送/构建/操作手机。返回实际改动、测试命令结果和遗留风险。

## 2. assistant · 2026-10-15 18:59
Message ID: `DD655C02-CA1F-4A0D-BCFB-0FFF9D3763CD`

列出OpenMinis源码文件

## 3. user · 2026-10-15 18:59
Message ID: `8F8474BE-6FB0-472E-B95F-C2E2EBD0406F`

[Tool result: //var/minis/workspace/OpenMinis-v64/.port-scripts-cache
//var/minis/workspace/OpenMinis-v64/TROLLSTORE.md
//var/minis/workspace/OpenMinis-v64/CONTEXT.md
//var/minis/workspace/OpenMinis-v64/BUILDING.md]

## 4. assistant · 2026-10-15 18:59
Message ID: `49715646-90D1-4687-BBA7-5CDCD412E4A7`

定位压缩实现与既有回归测试

## 5. user · 2026-10-15 18:59
Message ID: `58E4727B-AA6C-46F8-BE7D-1259A481C9E6`

[Tool result: /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift
/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+ISHCommand.swift
/var/minis/workspace/OpenM]

## 6. assistant · 2026-10-15 18:59
Message ID: `0889F1A0-DA57-4994-8647-C5ABC9562AEB`

读取上下文策略现有补丁

## 7. user · 2026-10-15 18:59
Message ID: `EDFBE431-192C-418B-B1F5-45617F885AB3`

[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/ContextPolicy.swift | 30195 bytes | 612 lines | showing lines 1-500 of 612]
import Foundation

/// Determines offload / compact / exhausted thres]

## 8. assistant · 2026-10-15 18:59
Message ID: `FE3755E2-FFB2-4D39-8CC1-2015096FD404`

定位摘要递归与队列执行链

## 9. user · 2026-10-15 18:59
Message ID: `367EF555-8325-4F48-A46E-7FE1316D60C7`

[Tool result: src/ios/Agent/Chat/AIChatViewModel+Compaction.swift
src/ios/MinisTests/Standalone/CompactMarkerSemanticsTests.swift
src/ios/MinisTests/Standalone/CompactionDecisionTests.swift
src/ios/MinisTests/Stand]

## 10. assistant · 2026-10-15 18:59
Message ID: `7A6ADA3C-1F78-4516-A27D-19DC558284EF`

读取压缩调用完整实现

## 11. user · 2026-10-15 18:59
Message ID: `23846DEC-2698-4652-8DE3-2F4BB2637B2E`

[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift | 106595 bytes | 1902 lines | showing lines 1-700 of 1902]
import Foundation

private let logger = AppLogger(cat]

## 12. assistant · 2026-10-15 18:59
Message ID: `CE423A29-DB1B-49E9-A9CD-E2E92DB277AE`

提取关键压缩状态与摘要管理位置

## 13. user · 2026-10-15 19:00
Message ID: `C2C1A234-34FA-4DE3-82C3-F2FF99A93728`

[Tool result: grep: src/ios/Agent/Chat/AIChatViewModel{,+Compaction}.swift: No such file or directory
src/ios/Agent/Chat/AIChatViewModel+Compaction.swift

[Command timed out after 30s — above is partial output capt]

## 14. assistant · 2026-10-15 19:00
Message ID: `97F6B35A-3D22-44F3-B16B-ED2D8ACB75BB`

定位压缩入口和摘要管理器调用

## 15. user · 2026-10-15 19:00
Message ID: `2D7977BC-D452-44D2-846C-BF799827943A`

[Tool result: src/ios/Agent/Chat/AIChatViewModel.swift:1241:    @Published var isCompacting = false
src/ios/Agent/Chat/AIChatViewModel.swift:1354:    /// automatic — every path goes through `compactBefore`) has ins]

## 16. assistant · 2026-10-15 19:00
Message ID: `D2211FEC-FA94-48C5-8157-F2A0850AF333`

读取压缩失败与重试入口, 读取压缩结果与提交保护, 读取递归分段与错误分类

## 17. user · 2026-10-15 19:00
Message ID: `585CDF3E-8F62-4630-81ED-354B2F6229F5`

[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift | 106595 bytes | 1902 lines | showing lines 340-549 of 1902]
    /// `.compactDivider` rows are deliberately NOT]
[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift | 106595 bytes | 1902 lines | showing lines 830-1119 of 1902]
        logger.info("[CtxMeter] reverted marker=\(]
[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift | 106595 bytes | 1902 lines | showing lines 1350-1504 of 1902]
                    // Cap tool results to avoid ]

## 18. assistant · 2026-10-15 19:00
Message ID: `97C8B390-9F63-41D6-9E00-C70E5CFC57E2`

读取队列drain防重入和消费顺序, 读取软硬窗口循环压缩决策, 读取压缩异常与持久化事务

## 19. user · 2026-10-15 19:00
Message ID: `D6ACBB9C-309F-4196-B6B5-6B4B4765E96E`

[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift | 499333 bytes | 8085 lines | showing lines 4965-5174 of 8085]
    /// — there is no idle-time consumer. `submitProgrammati]
[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift | 499333 bytes | 8085 lines | showing lines 6360-6519 of 8085]
            contextFixedTokens = ContextSizeMeter.estimateFi]
[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift | 106595 bytes | 1902 lines | showing lines 1090-1199 of 1902]
        } catch is CancellationError {
          ]

## 20. assistant · 2026-10-15 19:00
Message ID: `A999330F-52F9-4B31-AEB2-E6DC1D52E38A`

确认token估算与预发送保护缺口

## 21. user · 2026-10-15 19:00
Message ID: `2B9E8B6F-AE5F-477A-901C-2ADA570A40BD`

[Tool result: 43:        let result = policy.check(estimatedTokens: measured, contextWindow: contextWindow)
127:        let history = ContextSizeMeter.estimateTokens(effectiveAgentHistoryUncounted())
142:        la]

## 22. assistant · 2026-10-15 19:01
Message ID: `24285490-34F6-4654-8C54-7A24824475C3`

运行自动压缩源码回归测试

## 23. user · 2026-10-15 19:01
Message ID: `4057CFBA-0A7A-412E-BEE6-8D94A351B447`

[Tool result: Automatic compression source contracts: PASS (not device tests)
SKIP production Swift tests: no Swift here; mandatory on GitHub macOS
]

## 24. assistant · 2026-10-15 19:01
Message ID: `BDC78A28-0845-476E-9752-EDD1008F0202`

检查恢复入口和压缩成功交接

## 25. user · 2026-10-15 19:01
Message ID: `948CC6FD-2ECE-461E-B771-F862459D5E8D`

[Tool result: src/ios/Agent/Chat/AIChatViewModel.swift:2675:    // schedulePostCompactDrain() runs the post-compact queue drain on this
src/ios/Agent/Chat/AIChatViewModel.swift:2841:    func send(overrideText: Stri]

## 26. assistant · 2026-10-15 19:01
Message ID: `CCECE4CD-7AAF-44C5-B76B-C7028A315134`

审查摘要估算器与取消恢复队列

## 27. user · 2026-10-15 19:01
Message ID: `57B9055C-665C-4B0A-8172-E7C5E4A45266`

[Tool result:         autoRetryAttempt = 0
        autoRetryCountdown = 0
        if let sid = sessionId {
            logger.info("🔥 cache keep-alive: cancelling on user cancel — session=\(sid.prefix(8))")
       ]

## 28. assistant · 2026-10-15 19:01
Message ID: `20DC28C5-5009-4D39-8684-AA9088C132A1`

查找所有摘要管理器与低估公式

## 29. user · 2026-10-15 19:01
Message ID: `8DEF224D-B3B8-4692-9803-ACB67C16020E`

[Tool result: /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift
757     ///   - Generate new summary via LLM using `previousSummary = cachedLatestMarker?.summary`
980         //]

## 30. assistant · 2026-10-15 19:01
Message ID: `C44639A3-C59C-4F9F-9545-FBD4FB8E54B8`

确认队列尾递归与会话切换状态

## 31. user · 2026-10-15 19:01
Message ID: `CA87209E-6B94-407C-8EE3-34F566AD0CAD`

[Tool result: /var/minis/workspace/OpenMinis-v64/src/ios/MinisTests/Standalone/BgNotificationSummaryScopeTests.swift
        await Task.yield()
        if !Task.isCancelled && !self.userDidCancel && !self.promptQue]

## 32. assistant · 2026-10-15 19:02
Message ID: `DDA4C72C-BCB1-47E9-A65C-92A11D10F352`

读取手动重试压缩目标选择

## 33. user · 2026-10-15 19:02
Message ID: `4C04F429-E11B-411D-A188-F1AA478CA621`

[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift | 106595 bytes | 1902 lines | showing lines 560-593 of 1902]
    func compactAll() {
        guard !isProcessing]

## 34. assistant · 2026-10-15 19:02
Message ID: `72B958DB-4BB8-4085-8537-E1BF02B3A5B4`

新增压缩失败会话级队列闸门

## 35. user · 2026-10-15 19:02
Message ID: `6BD41A1E-E6CC-4340-8DD3-433509A4DC51`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 499771 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 36. assistant · 2026-10-15 19:02
Message ID: `A2F4F89D-705A-4C34-B6B4-4116BBF08EB7`

阻断失败后的自动空闲队列重启

## 37. user · 2026-10-15 19:02
Message ID: `94DC10AE-A558-4627-A40B-06D57731479C`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 499829 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 38. assistant · 2026-10-15 19:02
Message ID: `F6D712F6-4799-4455-9FF5-0FB1AE9D8ECC`

保护统一drain入口不消费失败队列

## 39. user · 2026-10-15 19:02
Message ID: `90B0B4CF-CEF1-41FE-B75E-2F3C5464CAA7`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 499902 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 40. assistant · 2026-10-15 19:02
Message ID: `07A2BDDB-96F2-4D69-8577-C8E270FFC6EF`

逐批消费前重查压缩闸门

## 41. user · 2026-10-15 19:02
Message ID: `DAFF0E49-CDEF-409A-8EB7-6AE38D9BA4E8`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 499978 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 42. assistant · 2026-10-15 19:02
Message ID: `3BEEDA7E-CA1C-4A03-BD99-A63C29F1002D`

关闭失败闸门时禁止尾递归空转

## 43. user · 2026-10-15 19:02
Message ID: `7AECC360-CAFD-4728-BE3E-694A956528AD`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 500021 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 44. assistant · 2026-10-15 19:03
Message ID: `72A776F8-D261-43DC-A616-FA80DDD04622`

保护循环内队列注入入口

## 45. user · 2026-10-15 19:03
Message ID: `F504DD77-1FFB-4B1F-AABE-7A42993DC199`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 500065 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 46. assistant · 2026-10-15 19:03
Message ID: `6A0B6CC9-CDBF-4070-9128-8B54F80EB331`

压缩开始即关闭队列防清理触发消费

## 47. user · 2026-10-15 19:03
Message ID: `4D1E46A4-AE94-4AD3-A4FD-5380AFBB530E`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift (1 replacement, 106808 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewMode]

## 48. assistant · 2026-10-15 19:03
Message ID: `9FEBF708-6DBE-414B-9722-8C86B7E6974B`

限定闸门覆盖实际摘要尝试

## 49. user · 2026-10-15 19:03
Message ID: `725003A0-EE46-47F1-8748-D726715F3E36`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift (1 replacement, 107251 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewMode]

## 50. assistant · 2026-10-15 19:03
Message ID: `28B922DB-1E13-4234-B8BE-33AB81566633`

保持无操作压缩不误锁队列

## 51. user · 2026-10-15 19:03
Message ID: `AA2B0947-6C74-4CA5-8B23-BA698EA6ADB8`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift (1 replacement, 107038 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewMode]

## 52. assistant · 2026-10-15 19:03
Message ID: `73AA916D-0A8A-45E5-BC17-877E45B54A20`

简化闸门仅由成功提交解锁

## 53. user · 2026-10-15 19:03
Message ID: `194939D8-8B4E-4B05-B959-E346E5B22750`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift (1 replacement, 106804 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewMode]

## 54. assistant · 2026-10-15 19:04
Message ID: `50608836-D5E4-4647-84D3-390837A947A9`

压缩成功提交后开放队列消费

## 55. user · 2026-10-15 19:04
Message ID: `4D05A398-EC30-4734-9AF3-1594B0888CEB`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift (1 replacement, 106850 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewMode]

## 56. assistant · 2026-10-15 19:04
Message ID: `E20DCC62-3863-4980-BEB4-0C6E58EE6699`

递归分段采用滚动摘要保留此前上下文

## 57. user · 2026-10-15 19:04
Message ID: `3A66B89E-5A2B-481C-A160-E1F40C1A2A5E`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift (1 replacement, 105482 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewMode]

## 58. assistant · 2026-10-15 19:04
Message ID: `922AB7AD-3DE1-4A60-BA5A-5394D20ABAFD`

提高中文非ASCII初次请求token安全估算

## 59. user · 2026-10-15 19:04
Message ID: `D539FA93-D094-4062-B1F2-B3B6FE01F422`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/ContextPolicy.swift (1 replacement, 30201 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/ContextPolicy.swift]

## 60. assistant · 2026-10-15 19:04
Message ID: `1DC01D95-5F28-48C4-8E94-64E60E6E0FB8`

取消压缩保留全部排队文本附件占位

## 61. user · 2026-10-15 19:04
Message ID: `10783D05-3B08-4C16-9B0B-523141F60F67`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 499867 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 62. assistant · 2026-10-15 19:05
Message ID: `1E5B6D8E-6850-41C7-B785-18A25068D674`

手动重试不把排队气泡作为历史锚点

## 63. user · 2026-10-15 19:05
Message ID: `20EC6552-1057-439A-B661-FF08EDAABAEE`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel+Compaction.swift (1 replacement, 105498 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewMode]

## 64. assistant · 2026-10-15 19:05
Message ID: `0786A273-8ACA-48E1-A405-F0F2B2C582A4`

循环压缩取消时维持队列保护

## 65. user · 2026-10-15 19:05
Message ID: `CADE288C-636F-4BB1-9C0C-7A7E2F85CFFE`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 499935 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 66. assistant · 2026-10-15 19:05
Message ID: `5030F2E4-473C-4C4D-A1C0-34BDCB2A6C91`

失败早退也统一关闭队列闸门

## 67. user · 2026-10-15 19:05
Message ID: `72DB82AF-90F9-474D-BDB8-CC973D3ADB98`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 500003 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 68. assistant · 2026-10-15 19:06
Message ID: `E0FB55E5-3145-4DA7-8CFE-87749277FE6A`

复核队列消费入口与模型重试边界

## 69. user · 2026-10-15 19:06
Message ID: `940D8EF6-C61E-4AC4-A344-F3C832F58FD6`

[Tool result: 904:                // in promptQueue until the user's next turn. Start one now.
907:                if !promptQueue.isEmpty && !userDidCancel {
1768:    @Published var promptQueue: [QueuedPrompt] = []

## 70. assistant · 2026-10-15 19:06
Message ID: `C3FAA6DA-3701-4276-A1F3-1AD159A8EBCF`

核查压缩失败后Resume可恢复性

## 71. user · 2026-10-15 19:06
Message ID: `30C86163-B923-42E8-A642-39E6FF9CE749`

[Tool result: [/var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift | 500003 bytes | 8093 lines | showing lines 3654-3753 of 8093]
            self.playCompletionHaptic()
            self.isP]

## 72. assistant · 2026-10-15 19:06
Message ID: `F5E7067C-F1F3-4693-976B-03F86E39DBE0`

Resume为失败压缩提供显式有限重试

## 73. user · 2026-10-15 19:06
Message ID: `DA510F0F-44D3-4E7A-B6FA-F5AA368C31EA`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift (1 replacement, 500255 bytes)
minis_url: minis://workspace/OpenMinis-v64/src/ios/Agent/Chat/AIChatViewModel.swift]

## 74. assistant · 2026-10-15 19:07
Message ID: `F164F91A-E77D-447E-867F-AF0A4B7CDB8A`

写入自动压缩当前状态文档

## 75. user · 2026-10-15 19:07
Message ID: `7CBF4AE5-7BB9-44DA-B617-38C169CCFBCF`

[Tool result: Wrote to /var/minis/workspace/OpenMinis-v64/docs/auto-compaction-current-status.md (2105 bytes)
minis_url: minis://workspace/OpenMinis-v64/docs/auto-compaction-current-status.md]

## 76. assistant · 2026-10-15 19:08
Message ID: `8BC64F68-00AA-452C-8320-D6953584F5F8`

运行压缩回归与脚本语法检查

## 77. user · 2026-10-15 19:08
Message ID: `1D336ABF-777C-4F88-8795-D64560BEC5AE`

[Tool result: Automatic compression source contracts: PASS (not device tests)
SKIP production Swift tests: no Swift here; mandatory on GitHub macOS
docs/source checks: PASS
]

## 78. assistant · 2026-10-15 19:08
Message ID: `9DA1C01C-12E4-4B37-A211-1DD30FC9FD89`

读取回归测试以补充本轮断言

## 79. user · 2026-10-15 19:08
Message ID: `CCFD5C57-E417-42BA-9011-97FAAF94C3DC`

[Tool result: [/var/minis/workspace/OpenMinis-v64/scripts/test_v64r_autocompress.py | 3592 bytes | 60 lines | showing lines 1-40 of 60]
from pathlib import Path
import os, re, shutil, subprocess, tempfile
root = Pa]

## 80. assistant · 2026-10-15 19:09
Message ID: `8F155E85-4732-488D-8D0A-843705C0702B`

补充队列闸门与中文估算回归断言

## 81. user · 2026-10-15 19:09
Message ID: `52E9680E-A91A-43E0-9C5B-9C429F82F5D0`

[Tool result: Edited /var/minis/workspace/OpenMinis-v64/scripts/test_v64r_autocompress.py (1 replacement, 3759 bytes)
minis_url: minis://workspace/OpenMinis-v64/scripts/test_v64r_autocompress.py]

## 82. assistant · 2026-10-15 19:09
Message ID: `C7E9473E-C763-4CC6-A6D5-05F72591ADE3`

运行增强后的自动压缩回归测试

## 83. user · 2026-10-15 19:09
Message ID: `18AE7F43-B293-4A3A-8459-71CC9098A5AE`

[Tool result: Automatic compression source contracts: PASS (not device tests)
SKIP production Swift tests: no Swift here; mandatory on GitHub macOS
]

## 84. assistant · 2026-10-15 19:10
Message ID: `58973271-01E4-48A9-8021-5C90A7F2055C`

已完成本轮自动压缩与队列保护源码修复，项目目录为 `/var/minis/workspace/OpenMinis-v64`。

实际改动：

- `src/ios/Agent/Chat/ContextPolicy.swift`
  - 保留既有 `min(budget, nativeWindow)` 逻辑，未将 `217600` 错误归因于模型原生窗口。
  - 保留软窗口、硬窗口和 `exhaustedOnly` 分支。
  - 将非 ASCII 字符的初次 token 估算从每个字符 `1.0` 调整为保守的 `1.5`，降低中文/日文上下文在首次 provider 校准前被低估的风险。
  - provider 返回真实 usage 后仍通过原有 calibration ratio 校准。

- `src/ios/Agent/Chat/AIChatViewModel+Compaction.swift`
  - 分段摘要递归不再丢失前面摘要：
    - 第一段生成 `summary1`。
    - 第二段递归调用时传入 `previousSummary: summary1`。
    - 使用滚动摘要结果作为最终摘要，避免未保护的第三次合并请求再次失败并丢弃前面结果。
  - 压缩开始后设置会话级 `compactionQueueBlockedSessionId`。
  - 只有 marker 成功提交后才解除队列闸门。
  - 压缩取消、失败或结构化失败结果均不会自动 drain 队列。
  - 手动压缩目标过滤排队中的 UI 消息，避免把尚未消费的排队气泡误作为压缩历史。
  - 保留现有分段重试上限、网络/取消/限流错误分类和模型 fallback；未将用户主动断网或 TLS/网络错误错误判定为“未及时触发压缩”。

- `src/ios/Agent/Chat/AIChatViewModel.swift`
  - 新增会话级队列保护状态：
    - `compactionQueueBlockedSessionId`
    - `isQueueBlockedByCompaction`
  - `startDrainIfIdle`、`drainQueuedPrompts`、drain 内部批处理、尾递归和循环内 queued prompt 注入均检查压缩闸门。
  - 压缩失败/取消后不会因 `isProcessing` 状态变化触发空闲 drain，也不会递归空转或无限自动重试。
  - 取消 `compact-and-send` 时保留全部排队 prompt、文本、附件和占位气泡，不再只恢复最后一条并删除前面的队列项。
  - `resume()` 在压缩失败闸门存在时转为一次显式 `compactAll()` 重试；自动 drain 不会重试。
  - in-loop 压缩失败和取消路径显式维持队列保护。

- `scripts/test_v64r_autocompress.py`
  - 增加源码合同断言：
    - 队列闸门存在并接入 drain。
    - 分段递归传递 `previousSummary: summary1`。
    - 中文 token 保守估算因子存在。
  - 原有软预算边界、native window、用户 cap、配置持久化和 no-progress 测试全部保留。

- 新增文档：
  - `docs/auto-compaction-current-status.md`
  - 记录本轮实现、测试边界、队列保护策略和遗留风险。

测试命令及结果：

```sh
cd /var/minis/workspace/OpenMinis-v64
python3 scripts/test_v64r_autocompress.py
```

结果：

```text
Automatic compression source contracts: PASS (not device tests)
SKIP production Swift tests: no Swift here; mandatory on GitHub macOS
```

另外执行：

```sh
python3 -m py_compile scripts/test_v64r_autocompress.py
```

结果：

```text
docs/source checks: PASS
```

未修改布局文件，未修改 `ChatStore.swift`，未覆盖其他 agent 的布局改动；未构建、未推送、未操作手机。

遗留风险：

- 当前 iSH 环境没有 Swift/Xcode，无法确认完整 Swift 编译、actor 隔离或实际 target 构建。
- 源码合同测试不等于 Swift 编译测试，也不等于真机 provider、断网、取消、队列并发和多模型 fallback 时序测试。
- 中文估算是保守近似，不是实际 tokenizer；首次 provider usage 返回前仍可能存在误差，但后续会按同一请求校准。
- 队列闸门依赖显式 Resume/Compact 操作恢复；真机仍需验证失败状态展示、排队气泡保留及成功 marker 提交后的 drain 时序。
- SSL/TLS 用户主动断网被保留为不可由切分修复的网络失败，不作为自动压缩未及时触发的根因。
