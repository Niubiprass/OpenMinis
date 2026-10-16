# 代理任务 · 审查 TextKit 守卫及崩溃隐患

- Session: `0E35F94B-FB4A-48E8-9A5A-BECCEDE6B42B`
- Exported entries: 57 / CLI reported 57
- Export source: minis-sessions-cli --full, paginated 100 per page.
- 这里是历史原话，包含错误判断、失败尝试及工具摘要；不得把旧结论当作当前事实。
- 这是纯文本记录备份，不是可直接导入 App 的数据库；CLI 不返回附件二进制或原始工具调用结构。

## 1. user · 2026-10-15 03:19
Message ID: `97B83413-98CB-4F9D-AA84-ADFD85F08CBB`

只读审查 /var/minis/workspace/OpenMinis 的iOS15运行时问题，重点 src/ios/Shared/NSTextContainerSetSizeGuard.m、UITextView/SwiftUI输入相关兼容修改，以及scripts/ios15_verify。用户请求修复适配iOS15，HEAD ce7a2298已经多次自动port。不运行样本、不修改文件、不涉及安全限制绕过。请定位能证实的运行时崩溃/线程安全/内存安全/恢复逻辑问题，区别关键词静态断言与真正正确性。给出2-5个真实问题文件行号与最小修复建议及验证方式，尽量能独立本地静态验证；勿返回长源文件。

## 2. assistant · 2026-10-15 03:19
Message ID: `E7CFF064-F65C-4057-AAB4-97D401F18E12`

检查仓库状态及 TextKit 守卫代码

## 3. user · 2026-10-15 03:19
Message ID: `CAEB64AF-12DE-49A6-8F82-6146DFA0A8A5`

[Tool result: ce7a229
scripts/ios15_verify/selfcheck_scope_v565.py
scripts/ios15_verify/reverse_v570.py
scripts/ios15_verify/reverse_v51.py
scripts/ios15_verify/ci_assert_v64.py
scripts/ios15_verify/ci_assert_v50.p]

## 4. assistant · 2026-10-15 03:20
Message ID: `C42D0949-895F-461C-B856-4680C1631063`

读取守卫后半段及输入兼容引用

## 5. user · 2026-10-15 03:20
Message ID: `7752E5EF-F54C-4B5E-B78F-0CB8D9A5E1E5`

[Tool result:    250	            // 又一处编译红(run#157/run#159 同类)。KVC 纯运行期查找, 无声明依赖。
   251	            CGFloat _w = 0;
   252	            @try {
   253	                NSValue *_wv = [(id)self valueForKey:@"size"];
 ]

## 6. assistant · 2026-10-15 03:20
Message ID: `19EC83B5-E71C-45AB-AB5E-C2981551E229`

检查重入熔断恢复及安装路径

## 7. user · 2026-10-15 03:20
Message ID: `D36C6B45-7C86-4CEF-9194-2FB1B5EBFB8A`

[Tool result: 775 src/ios/Shared/NSTextContainerSetSizeGuard.m
   380	    // 直接制造一轮新的裁字(比现在更隐蔽, 因为只在长文本出现)。
   381	    // 结论: 2000 不是"新风暴源"而是"真实上限", 221 次命中恰恰说明真实内容这么高。
   382	    // 风暴的真正解法是消掉哨兵**探测行为**, 而不是压低哨兵值的]

## 8. assistant · 2026-10-15 03:20
Message ID: `749BEC75-93C2-4BF5-B5A5-145187B51AE0`

核对持久熔断状态及输入控件范围

## 9. user · 2026-10-15 03:20
Message ID: `D6A4F6F1-3C91-4C96-A7E3-93ADED53B5F0`

[Tool result:    489	        // Different tick or different size — reset bookkeeping.
   490	        // [V75-PERSISTENT-STORM] 必须在覆盖 s->lastSize 之前算好 _sizeChanged:
   491	        // 它比的是「本次到达的尺寸」与「上一帧已记录的尺寸」是否不同。
 ]

## 10. user · 2026-10-15 03:20
Message ID: `183BE438-6F2E-451B-BE55-EB5AFBE2FA1F`

[Course correction from the delegating agent] 用户明确以160v64版本为基线，仅修打字跳字、闪屏、文字偶尔不显示。请优先研究v64守卫/字体渲染/输入路径，对比后续修改但不能默认移植最新大守卫。主agent即将拉git历史定位160v64，会通知路径。仍只读。

## 11. assistant · 2026-10-15 03:20
Message ID: `14389002-3C19-4C44-A1D7-A427E8EF043C`

定位输入框兼容逻辑与 v64 验证判据

## 12. user · 2026-10-15 03:20
Message ID: `11D616D4-5505-40AF-A74C-3413C1018749`

[Tool result: 533:    func updateUIViewController(_ controller: QLPreviewController, context: Context) {}
575:    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}
606:  ]

## 13. assistant · 2026-10-15 03:21
Message ID: `02A544BB-DBF7-421B-BA0C-94658A6D003D`

审阅输入测量光标同步及守卫调用方

## 14. user · 2026-10-15 03:21
Message ID: `22C8162E-5502-46D2-89C6-97CBFD744494`

[Tool result:    880	/// Async image tile for local cache URLs (InputAttachment).
   881	// MARK: - PastableTextView (paste image/file support)
   882
   883
   884	class PastableUITextView: UITextView, UIDropInt]

## 15. assistant · 2026-10-15 03:21
Message ID: `2ADD43E1-D29C-49E8-8F5B-DE2564134297`

读取布局测量与全局恢复判据关键行

## 16. user · 2026-10-15 03:21
Message ID: `3EED3A85-1720-45BD-AEF3-4ECD6FFEE101`

[Tool result:   1220
  1221	    /// [T-ios-composer-paste-truncation] Settle scrollability + content layout
  1222	    /// whenever the view's real geometry is known.
  1223	    ///
  1224	    /// The round-1 fix ]

## 17. user · 2026-10-15 03:21
Message ID: `7F8EC344-CBAA-4BDA-AE21-BAFA50DF098F`

[Course correction from the delegating agent] 用户追加先看所有仓库修复记录并GitHub参考类似项目。CI agent负责历史且独占git fetch；你不要fetch。继续读 TextKit/守卫v64相关及后续失败修复机制，给出不能再次照搬的副作用与根因线索。主agent做GitHub外部检索。暂不改源码。

## 18. assistant · 2026-10-15 03:21
Message ID: `EA39B6E5-7175-4FCC-82BF-BB554FCBDE9B`

查找 v64 记录并读取输入文字同步, 核查自动移植及后期验证是否绑定产物

## 19. user · 2026-10-15 03:21
Message ID: `4DCC3908-CDDF-42BE-881F-E54519BA2B17`

[Tool result: ./docs/ios15-port-research.md
./scripts/strip_ios15_incompatible_extensions.py
./scripts/ios15_fallback.py
./scripts/ios15_verify
./scripts/ios15_verify/ci_assert_v64.py
./scripts/ios15_verify/reverse]
[Tool result: 583:    # [IOS15-FIX-INPUT-FLICKER] 输入框打字闪屏根因: PastableUITextView 的
584:    # intrinsicContentSize 在每次查询时无条件改写 isScrollEnabled, 触发 UIKit 布局
585:    # 重入 (intrinsicContentSize → isScrollEnabled=… → lay]

## 20. user · 2026-10-15 04:23
Message ID: `1F6DDA2B-210B-4755-8C5E-DE1A972D8F07`

[This run was interrupted and has been resumed. The tool results above are still valid, but all live state is gone: browser tabs are closed, shell processes have ended, and anything unsaved is lost. Files in the workspace are still there. Continue from what the transcript already establishes — reopen pages or re-run commands when you need them, and do not assume anything is still open.]

## 21. assistant · 2026-10-15 04:24
Message ID: `D90200F3-F761-42A1-881A-22F2E33D3902`

检查已到位历史基线与字体输入记录

## 22. user · 2026-10-15 04:24
Message ID: `117CB7AB-5F86-4C39-B571-1623C4D8EC7C`

[Tool result: * main
  remotes/origin/HEAD -> origin/main
  remotes/origin/main
ce7a229 Auto-port OpenMinis to iOS 15 (scripts @ 972bfb0)
/var/minis/workspace/add-v64r-localization.py
/var/minis/workspace/v64-origi]

## 23. assistant · 2026-10-15 04:24
Message ID: `752FCE10-0836-449A-8C53-C5B078E6BDD5`

读取真实 v64 基线守卫与当前复核状态

## 24. user · 2026-10-15 04:24
Message ID: `3370FEEB-E8EF-4545-9569-D3068B19CF3C`

[Tool result: f017c76cae19053a86236112544c4185c9e94783
 M deps/build_rclone_ios.sh
 M src/ios/Agent/Chat/AIChatViewModel+Compaction.swift
 M src/ios/Agent/Chat/AIChatViewModel.swift
 M src/ios/Agent/Chat/ContextPol]

## 25. assistant · 2026-10-15 04:24
Message ID: `A53BC563-C296-4430-9EAC-9455AA14BC84`

读取 v64 守卫阈值和安装状态机, 核对 v64 字体淡入和测量代码调用

## 26. user · 2026-10-15 04:24
Message ID: `EA775AF2-F3C6-4EB1-AF4C-FC0389368EDC`

[Tool result:    136	    // 【v40 实测: 阈值维持 3000/2000 不动, 不能收紧】
   137	    // log8 看似"2000 成了最高频 x221"支持收紧, 但 FIRST-MEASURE 的 newH 实证
   138	    // **真实气泡最高 2002.3pt**, 且 setSize 里真实尺寸已出现 1994.3 / 1863.0 / 1799.0
   ]
[Tool result: 2561:            return renderCellInlines(children, baseFont: boldFont)
2563:            let result = NSMutableAttributedString(attributedString: renderCellInlines(children, baseFont: font))
2567:    ]

## 27. assistant · 2026-10-15 04:24
Message ID: `EDC60FBA-D9BC-4BF0-A54D-572F1811D7BA`

核实 v64 淡入回收和颜色恢复时序

## 28. user · 2026-10-15 04:24
Message ID: `0721FA22-E36F-4FF3-AC46-50E68334DFFF`

[Tool result:      1	//  TextFadeAnimator.swift
     2	//  Minis
     3	//
     4	//  Word-by-word fade-in animation for streaming Markdown output.
     5	//
     6	//  When the renderer appends new tokens to a mes]

## 29. assistant · 2026-10-15 04:25
Message ID: `47229719-82D3-4432-A74C-4FBD8AA5A0A0`

提取 v64 全量替换与淡入取消精确行号

## 30. user · 2026-10-15 04:25
Message ID: `84B5E61E-6DDA-42C9-8566-428639F47C39`

[Tool result:  10095	    /// happens today for any message that was never rendered. What the cache
 10096	    /// buys is attachment identity ACROSS coordinator recreations within one
 10097	    /// live message; a]

## 31. assistant · 2026-10-15 04:25
Message ID: `9B2D2416-6354-47B1-B817-7A06BEE3B403`

核实长文本容器追踪尺寸和测高上限, 确认输入高度反馈可达条件及字段初始化

## 32. user · 2026-10-15 04:25
Message ID: `9489B8AF-EADF-4459-92FA-1D6ED42A4E85`

[Tool result: 1552:        let contentHeight = measureCodeHeight()
1555:        let scrollHeight = min(contentHeight, maxCodeHeight)
1572:                      Double(height), Double(contentHeight), Double(maxCodeH]
[Tool result:   1422	    @Binding var isFocused: Bool
  1423	    @Binding var hasSelection: Bool
  1424	    @Binding var isScrollable: Bool
  1425	    /// [T-ios-composer-swipe-send-at-bottom] True when the compose]

## 33. assistant · 2026-10-15 04:25
Message ID: `9EAA4C04-8B30-48A3-869C-E7C3BA70EA96`

核对 v64 真实容器边界与静态判据覆盖, 核对后续守卫跨 tick 降频和恢复副作用

## 34. user · 2026-10-15 04:25
Message ID: `15203196-FA22-4C3A-9494-CD427494C02A`

[Tool result:   6575	    /// arrive after the cell has been briefly recycled out of window (scroll
  6576	    /// off-screen, then user immediately scrolls back). With the
  6577	    /// `window != nil` guard at th]
[Tool result:      1	//
     2	//  NSTextContainerSetSizeGuard.m
     3	//
     4
     5	#import "NSTextContainerSetSizeGuard.h"
     6	#import <UIKit/UIKit.h>
     7	#import <objc/runtime.h>
     8	#import <objc/]

## 35. assistant · 2026-10-15 04:26
Message ID: `4A29BC28-51AD-4D17-86A5-C8F26C3021A2`

提取淡入跨代颜色覆盖的最小证据链

## 36. user · 2026-10-15 04:26
Message ID: `F2AA00F0-942B-4BBF-97CD-757FC9431626`

[Tool result:  10158	            textView.textContainer.size = CGSize(width: fallbackW, height: .greatestFiniteMagnitude)
 10159	        }
 10160
 10161	        // [AttachHotPath] updateUIView entry — only log whe]

## 37. assistant · 2026-10-15 04:26
Message ID: `9885EE0F-C95C-4DF0-8D04-642ADBD55E92`

确认字体变化是否隔离旧淡入动画代次

## 38. user · 2026-10-15 04:26
Message ID: `C2391234-44DD-44BA-BA2C-2168C86A2FFB`

[Tool result:  10127	        textView.onReadAloud = onReadAloud
 10128	        textView.onSpeakText = onSpeakText
 10129	        #if DEBUG
 10130	        // [T-ios-markdown-rerender-burst] makeUIView creates a FRES]

## 39. assistant · 2026-10-15 04:26
Message ID: `D1B4FF55-E03A-4A9F-8F1D-F203CA4931C9`

验证 v64 熔断计数是否吞掉真实收尾几何

## 40. user · 2026-10-15 04:27
Message ID: `0D654B9C-74AB-4E9F-907A-19412F7D4295`

[Tool result: v64 same-tick alternation + final 358x41: forwarded= 161 final_real_size_forwarded= False last_forwarded= (390, 2000)
state reset-on-new-tick present: True
]

## 41. assistant · 2026-10-15 04:27
Message ID: `340ADE34-7634-4ADB-BBD0-8DBC6C40F1B9`

定位字体前缀比较和透明度恢复测试覆盖

## 42. user · 2026-10-15 04:27
Message ID: `9C153A1B-73C0-4D21-AD11-5FC867362786`

[Tool result:      1	#!/usr/bin/env python3
     2	"""Source-structure regressions for streaming text visibility (stdlib only).
     3
     4	Run: python3 scripts/test_stream_text_fade_source.py
     5	Negative co]

## 43. assistant · 2026-10-15 04:27
Message ID: `77BD30E6-DC23-4355-B303-9015CBC022F5`

读取 v64 容器实高上限及有限尺寸夹断证据

## 44. user · 2026-10-15 04:27
Message ID: `16DD5BB4-4B1E-40CE-89CE-10A250EFC18A`

[Tool result:   6581	    /// last image renders clipped or empty until the user exits + re-enters
  6582	    /// the chat. (T-multi-image-last d8a51f73.)
  6583	    private var pendingRefreshAfterWindowAttach = fal]

## 45. assistant · 2026-10-15 04:28
Message ID: `EE8EE9A1-1156-43B5-9C49-37C517FD23FD`

追踪输入光标意图是否被消费避免反复跳字

## 46. user · 2026-10-15 04:28
Message ID: `9A8679E5-2023-4EA7-B357-56D5F9B486F7`

[Tool result:   1726	        }
  1727	        tv.onPasteImage = onPasteImage
  1728	        tv.onPasteFile = onPasteFile
  1729	        tv.onPasteLongText = onPasteLongText
  1730	        tv.onReturnKey = onReturnK]

## 47. assistant · 2026-10-15 04:28
Message ID: `01F7C3BA-7E26-4848-B4DD-218291F4A3B7`

核查 mention 光标请求全调用路径

## 48. user · 2026-10-15 04:28
Message ID: `D9139577-6451-49BF-A471-BBE9664BB201`

[Tool result: src/ios/Agent/Chat/AIChatViewModel.swift:743:            if let p = pendingCaret, p == inputCaret {
src/ios/Agent/Chat/AIChatViewModel.swift:744:                pendingCaret = nil
src/ios/Agent/Chat/A]

## 49. assistant · 2026-10-15 04:29
Message ID: `E8EC96AC-88C4-401C-88BD-9FCD606A1DB8`

核对现有修复审查避免重复或误认根因

## 50. user · 2026-10-15 04:29
Message ID: `84F822F7-785B-498B-917A-5FD88F937C91`

[Tool result: # OpenMinis v64r 独立审查

- 基线：`f017c76`（用户 iOS 15 构建 160v64）；对象：本轮当前未提交 diff 及直接相关调用上下文。
- 方式：仅本地只读检查；未修改仓库文件、未联网、未读取密钥。仅按要求写本报告。
- 验证：`git diff --check` 通过；`python3 -B scripts/test_v64r_render_contract]

## 51. assistant · 2026-10-15 04:29
Message ID: `3C963B6D-1B38-4BB4-AD5D-FA1A6E893B39`

用纯模型验证前缀漏检与旧淡入跨代回写

## 52. user · 2026-10-15 04:29
Message ID: `96C9E628-234C-41DC-9B16-D78646FC9A4C`

[Tool result: prefixComparator expected=False actual= True allPositionsEqual= False
full-assign then old fade tick/cancel => ['black', 'black', 'red', 'red']
]

## 53. assistant · 2026-10-15 04:30
Message ID: `5914B495-26F2-4AE1-9535-F3C9B16B2AD6`

固定后续守卫恢复与全局历史副作用证据

## 54. user · 2026-10-15 04:30
Message ID: `738E1849-BF91-46F7-A101-739572ACAD69`

[Tool result:    330	                if (!(_prev > 1.0 && isfinite(_prev) &&
   331	                      _prev <= kMaxContainerHeight)) {
   332	                    // [V69-GLOBAL]④ 本容器无历史(**容器是新建的**, 这正是
   333	 ]

## 55. assistant · 2026-10-15 04:30
Message ID: `32AF05B2-3C2E-42D4-946E-7F8B984E1E42`

确认 v64 静态判据不写产物再只读执行

## 56. user · 2026-10-15 04:30
Message ID: `7FDA3B64-4F9E-4AE9-89CD-D3CF4D845A32`

[Tool result:

def _judge(t):
    """跑真判据。通过返回 None, 失败返回异常。"""
    try:
        fb.verify_deseed_v64(t)
        return None
    except Exception as e:
        return e


def main():
    base_arg = sys.argv[1] if ]

## 57. assistant · 2026-10-15 04:31
Message ID: `8B2B366F-72D8-4BF2-8536-10D89E18594F`

## 只读审查结论

基线已改为用户指定的 **160v64：`f017c76cae19053a86236112544c4185c9e94783`**。以下行号均来自该提交的 `git show HEAD:<文件>`，**不是当前正在修改的工作树**。后续 `ce7a229` 守卫仅用于对照，不建议整体回移。

未运行应用、未修改源码。确认 **4 项代码正确性问题**；其中前两项直接涉及文字闪现、颜色/透明度恢复，第三项是守卫吞掉真实收尾几何，第四项是潜在安装恢复错误。**没有足够证据把其中任何一项认定为现有 EXC_BAD_ACCESS 的直接原因。**

### 1. [P1] 全文替换未结束旧淡入世代，旧动画仍可覆盖新正文属性

**位置**
- `src/ios/Views/Chat/SelectableMarkdownView.swift:10594–10605`
- `src/ios/Views/Chat/TextFadeAnimator.swift:114、139–158、202–230`

**证据与影响**

全文替换分支直接执行 `textView.attributedText = attributed`，没有先 `cancelAll()`。随后对新增尾部继续调度动画，但 animator 的 `words` 仍保留旧内容的范围、颜色及时间。

`tick()` 只验证旧范围是否落在当前 storage 长度内，**不验证内容世代**。常见的 UITextView storage 内容原地替换情况下，旧范围仍合法，因此旧动画会向新正文回写旧颜色/低透明度。字体或 Markdown 样式变化但字符串仍为前缀增长，也可以进入这条路径。

这不是越界证明，而是**范围合法、内容身份已失效的恢复错误**：正文刚以正确颜色显示，又被旧动画改回去。不能据此断言永久丢字。

**最小修复**
- 全文赋值前结束旧动画，再赋值，再调度新尾部。
- iOS 15 若以稳定显示优先，可仅关闭该系统上的 alpha-0 淡入，不改解析器、字体或大守卫。
- 动画保留时，增加 storage 身份/内容世代检查；取消操作也不得向新世代恢复旧颜色。

**验证**
构造同一 storage：先淡入一段黑色文字，动画未完成时全文替换成同长度红字，再推进旧 tick/取消操作，最终必须全部保持红色。已用纯 Python 状态模型确认旧算法会把新正文前段改回黑色；模型不替代 UIKit 测试。

---

### 2. [P1] 字体前缀比较只检查旧属性段的起点，会漏掉段内样式差异

**位置**
- `src/ios/Views/Chat/SelectableMarkdownView.swift:10777–10802`
- 快速追加调用方：`10573–10590`

**证据与影响**

比较函数按 **newPrefix 的属性段**枚举，每段仅调用一次：

`oldPrefix.attributes(at: range.location, effectiveRange: nil)`

它没有遍历旧前缀在该段内部的属性边界。因此：

- 新前缀 `[0,6)` 全黑、同字体；
- 旧前缀 `[0,3)` 黑色同字体，`[3,6)` 红色或透明/不同字体；

当前函数会返回 **true**，虽然后半段明确不等。快速追加因此保留旧半段属性，吞掉本轮 renderer 希望恢复的样式。该问题不依赖某个字体名称，也不能通过单纯忽略 `foregroundColor` 修复——那会进一步吞掉真实颜色变化。

**最小修复**
按新旧两侧 `effectiveRange` 边界的并集逐段比较；每段仅允许已有的 `NSFont/NSOriginalFont` fallback 归一化，其他属性仍须严格相等。

**验证**
无需 UIKit 运行即可为上述区间算法写反例测试。我已执行纯模型，得到：

`expected=False，actual=True`

另需覆盖 CJK/emoji fallback、链接颜色变化、同字符串字体调整、旧段中间 alpha 为 0 等情况。**不能只测试比较函数是否含 `NSOriginalFont` 关键词。**

---

### 3. [P2] v64 熔断到硬上限后吞掉真实最终尺寸，没有保证尾沿补交

**位置**
- `src/ios/Shared/NSTextContainerSetSizeGuard.m:177–199、223–241`

**证据与影响**

同 tick 已熔断、`commitCount > 40*4` 时，任何不同尺寸也直接返回。没有保存最后一次请求，也没有安排下一 tick 补交。真实的最终宽度/高度修正和探测尺寸共用同一额度。

我按源代码顺序执行了状态模型：

1. 同 tick 交替请求 `390×2000 / 358×2000` 共 161 次；
2. 最后请求真实收尾尺寸 `358×41`。

结果：**161 次已转发；`358×41` 被丢弃；容器停在 `390×2000`。** 下一 tick 会重置预算，但前提是上游再次请求；代码没有保证它会重试。因此有“暂时稳定但文字仍按旧几何裁切”的恢复缺口。

**最小修复建议**
先不要移植后续跨 tick 永久熔断。若日志确认该形态，应保存被吞掉的最新几何，并保证一次有界的下一轮补交，或在明确的测量作用域区分探测和真实提交。**不要仅根据 `height >= 2000` 判断探测**，真实长内容并不具备这个上限。

**验证**
状态机测试必须断言“最后合法尺寸最终提交”，而不只断言“调用次数降下来”；覆盖同尺寸风暴、两尺寸交替、风暴后单次真实收尾、跨 tick 恢复。真实 UIKit 再检查不产生新的循环。

---

### 4. [P2，潜在问题] 非主线程首次安装会永久消耗 `dispatch_once`，所谓延迟重试实际不安装

**位置**
- `src/ios/Shared/NSTextContainerSetSizeGuard.m:255–262`
- 当前入口：`src/ios/MinisApp.swift:149–153`

**证据与影响**

主线程检查放在 `dispatch_once` 的 block 内。首次若在后台调用，它向主队列安排 `[NSTextContainerSetSizeGuard install]` 后返回；once token 已完成，主队列再次调用时 block 不再执行，swizzle 和 runloop observer 都不会安装。

这是确定的恢复逻辑错误；但**当前查到的启动入口预期在主线程，不能把它当作现有闪屏根因**。

**最小修复**
将非主线程转主队列的检查移到 `dispatch_once` 外；真正安装仍由 once 保护。

**验证**
独立单元测试先后台调用、清空主队列，再检查 IMP 已被替换且安装恰好一次；也测主线程首次调用及多次调用。只检查 `"deferring"` 日志不能证明重试有效。

---

## 输入路径：有明确副作用，但不能把静态关键词直接当根因

`ChatInputBar.swift:1162–1175` 的 `intrinsicContentSize` 查询中无条件写 `isScrollEnabled`；同文件 `1238–1265` 的 `layoutSubviews` 又测量、切换 scrolling、修改 inset。iOS 15 不会调用该 representable 的 iOS 16 `sizeThatFits` 重载，故 intrinsic 路径值得重点监测。

不过，**仅凭无条件 setter，不能证明系统对同值赋值必然重入或已造成闪屏**。后续版本加“值不同才写”是低风险止损，不是闭环正确性证明。更稳妥的方向是让 intrinsic 查询尽量只读，把滚动/inset 更新集中在明确的布局阶段；验证输入跨越 120pt、删除回短文本、拼音组合、字号切换，记录尺寸查询深度及 scrolling/inset 变化，而不是只搜 `INPUT-FLICKER` 标记。

## 后续守卫不能照搬的原因

对照 `ce7a229`，发现以下语义风险，应避免再次叠加：

- **V69 全局历史高度**：`NSTextContainerSetSizeGuard.m:330–339` 可将别的容器高度借给新容器；不具备消息、字体、宽度身份。
- **V74 单线程递归布尔锁**：同一线程的不同容器合法嵌套调用也会被视为重入，范围比“同容器递归”更大。
- **V75 尺寸变化清预算**：`489–511` 每次不同尺寸将 `commitCount` 清零，反而破坏 v64 为交替尺寸累计硬上限的设计。
- **V76–V80 非正尺寸修正/丢弃/限流**只改变下游次数，不证明上游几何收敛。尤其合法零尺寸与非正异常值不能无条件混为一类。
- v64 已把所有 `height >= 3000` 改成 2000（`144–154`）；不能继续收紧。“历史日志中最高只有某高度”不是全局正文高度契约。

## 静态验证结论的边界

实际只读运行了：

`python3 -B scripts/ios15_verify/ci_assert_v64.py .`

结果 **v64=OK，反向 10/10 拦截**，同时上述动画/区间比较/守卫收尾问题仍存在。

该 gate 的核心是 `MessageListInfrastructure.swift` 去播种/收敛形状和源码级反向变异；`ci_assert_v64.py:99–132` 不验证上述淡入世代、属性区间、输入布局或 TextKit 最终几何。它不是无用，但其绿色只能解释为**特定源码契约通过**，不能解释为“打字跳字、闪屏和文字不显示已经修复”。
