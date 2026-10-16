# 160646 文字显示回归定点调查

日期：2026-10-15。唯一有效树：`/var/minis/workspace/OpenMinis-push`；HEAD `0960b075448a8879d37bdc16c9d53cd312624af0`。范围仅为160645→160646宿主/正文测量链；只读生产代码，仅新增本报告。未操作手机、未构建/运行测试、未push/触发CI。下列行号均指该树当前文件。

## 1. 当前证据与结论

- 用户明确报告160646仍卡字；新截图 `photo_B1AB5B3C.jpg` 与裁剪图 `photo_C4509C3F.jpg` 应纳入失败证据，不能继续沿用“纯文本正常”的阶段性反馈。
- 实读 `/var/minis/workspace/test-160646/photo_B1AB5B3C-ocr.json`：上方旧答复只识别出“上集局限已保存，160646”等碎片及若干低置信片段；下方较新答复可识别多行完整文字。这是同图不同区域的识别差异，不是字体大小、缩放、行高或裁剪根因的测量；没有由图片映射到稳定item/block UUID的证据。裁剪图的卡字报告也不能单独证明上述机制。
- `DEVICE-160646-FIRST-PASS.md:3–10` 是此前设备初测：部分手势无效、布局日志缺失、旧PID日志不可用；思考展开有局部几何响应，不等于正文通过。`REPAIR-HISTORY-EVIDENCE-AUDIT.md:9–11` 的历史文字改善判断必须受最新用户失败反馈限定，不能作为160646文字验收结论。
- **已证实代码风险面**：160646把原本直出的 `sizeThatFits` 接入带强制布局、递归fallback和高水位/稳定收缩的统一入口；收缩确认没有独立正文完整性校验，且宿主与cell存在真实裁剪边界。因此存在“稳定但欠测的raw被接受→父宿主变矮→正文被裁”的可检验路径。
- **未证实因果**：没有当前异常item的raw/accepted/TextKit/父帧时序，尚不能断言该路径已在截图发生，更不能断言所有卡字始于0960b07。正文文件没有在此提交中被直接改动，也不排除既有绘制/布局问题被新时序暴露。

## 2. 差异定位：只看会影响正文的链

相对160645产物提交 `5da5b4a`，`git diff 0960b07^ 0960b07` 的生产Swift变化仅三处：

| 变化 | 真实代码位置 | 能证明什么 / 不能证明什么 |
|---|---|---|
| 三个拟合入口统一 | `src/ios/iOS15Compat.swift:488–512,550–575` | `sizeThatFits` 原先直接调host求fit并ceil；现在同两个system fitting入口一起进入 `ios15FittingSize`。新增调用面会执行 `layoutIfNeeded`，递归时返回本地bounds高；原size入口的ceil也不再在此执行。不能仅凭差异断言小数高度造成截图卡字。 |
| 拟合前按实宽更新root | 同文件 `559–565` | 宽变超过0.5时在测量中重赋root并失效intrinsic；保留完整内容身份及全宽，不是显式缩放。新增布局/重入时序值得记录。 |
| 接受稳定低raw | 同文件 `576–619,625–644` | 合法正raw、差值>8、两次差≤1且间隔≥80ms，在非流式/非拖动/非defer、身份匹配时可降低mono及lastGood。只证明时间稳定，不证明文字全文排完。 |
| 延迟重试/外层缓存清理 | 同文件 `408–445`；`MessageListInfrastructure.swift:865–870` | 120ms重试受身份/revision保护；消费后清cell计算高/seed、layout height/precalc/memo。该入口没有先核对正文末行/usedRect。 |
| 去掉super-fit ceiling | `src/ios/Agent/MessageList/MessageListInfrastructure.swift:749–779` | 移除旧V64-CONVERGE向super高回夹；仍保留TextKit floor条件。对无TextKit工具/思考增长是必要修复方向，不能为了文字问题直接恢复通用ceiling。 |
| 停稳顺序与锚点 | `src/ios/Agent/MessageList/CollectionViewMessageListV3.swift:5865–5925` | 开defer后先消费宿主收缩，再消费Markdown deferred correction，再apply deferred/layout；按item补offset。顺序确实允许宿主先依据raw决策；尚无证据说明它在正文纠正之前已经展示了坏帧。锚点改的是列表offset，不是字号或字形缩放。 |

## 3. 父高能否影响raw、是否存在裁剪链

### A. 裁剪链存在：已由代码证实，触发条件未证实

`iOS15Compat.swift:694–702`：`host.view.clipsToBounds = true`，host四边约束钉住宿主，包含bottom约束。`MessageListInfrastructure.swift:64–73`：cell的contentView也裁剪。低accepted高若被布局采纳，上层可裁掉仍需更高的正文；仅把Markdown直接父视图撑高不保证越过host/cell裁剪。

`SelectableMarkdownView.swift:5593–5597,5653–5657` 仍按 `ios15LastNeededH` 补直接父frame；`:8982–9008` 在布局中重新测needH。该既有“撑父帧”路径与宿主受约束高度是不同层的真相。它们可能出现争夺/反复纠偏，但本轮没有逐帧证据，不能把注释内旧日志当本次运行。

### B. raw尚不能称“脱离父高的权威全文高度”

`iOS15Compat.swift:554–555`：`isMeasuring`重入或host缺失时返回 `bounds.height`。`:569–574` 在当前钉父host上先layout，再问host.view无限高fit，失败才问height=0。无限高proposal不等于已证明iOS15 SwiftUI忽略现存父帧；重入回bounds是明确存在的反馈支路。

**具体弱点（代码成立，运行未捕获）**：外层只凭返回raw有限且>1便标记fresh（`:582–592`）；没有传播“内层曾走bounds fallback”的来源标志。若外层host fit间接依赖此重入结果且给出稳定正值，现有确认无法辨别它与真正全文测量。不能跳过“是否实际重入、是否影响结果”两步就宣布根因。

**反向约束**：正文 `SelectableMarkdownView.swift:5484–5498` 本身以无限高调用super fit，`:5501–5506` 上报intrinsic高度，`:9463` 重新测正文；cell `MessageListInfrastructure.swift:749–764` 汇总已有 `lastComputedHeight`，较大且差<2500时抬高fit。故不能简单说“传入父高就必然截字”。须验证该floor是否新鲜、是否覆盖该block、是否已赶上收缩；不能默认lastComputedHeight永远权威或永远无效。

### C. 另一个需定点验证的一致性边界

`ios15FittingSize:605–609` 可在普通外部拟合中直接接受收缩；外层cache清理只写在 `consumeIOS15PendingStableShrink:418–428`，且需消费前后mono确实下降。普通拟合先接受后，candidate已清零，消费入口会早退。外部cell测量可能自行写回正确高，所以这不是已证明的缓存bug；但必须检查它与120ms消费路径的cache/precalc/memo最终值一致，防止宿主矮了而外层仍留旧空白，或再次套回不匹配几何。

## 4. 最小可验证方案（建议，不是已执行结果）

只做一组固定正文、同身份同宽的Apple/UIKit定点实验，先不改接受策略。复用截图对应旧答复的原文（在外部授权设备按block ID定位，不凭OCR重建），并加一个无附件中英多行对照。固定内容hash/属性hash、字号、Dynamic Type、collection宽、身份，分别走首次进入、离屏返回、滚动停稳。不要以网络重生成不同答案作A/B。

1. **同一条关联记录**：记录完整item/block ID、host实例与revision、入口及isMeasuring深度、raw是否来自fallback、测量前后host/包装层/cell bounds与frame、mono/candidate/时间/accepted、tracking/defer/streaming；同步记录正文container宽高、usedRect/最后glyph底边、lastComputedHeight及其内容/宽度指纹、textView/祖先clip与屏幕坐标、cell/cache/precalc/memo最终高。只记几何/指纹，避免输出整段私人正文。
2. **定点判别父高污染**：在Apple环境离屏测试夹具中，保持同root身份/内容/宽，分别给父高H和较小h，调用三个拟合入口；捕获重入来源和raw、正文最后行几何。保持正常全宽、padding、compressed拟合不变。若raw随父高变且低于独立正文末行需要值，才能确认“raw父高依赖”；若raw不变而仅显示边界变，则优先查裁剪/布局采纳而非raw测量。
3. **接受时刻判别**：在生产同路径的调试夹具中，观察低raw连续两次后是否接受，并在同帧/下一帧比对正文末glyph与host、cell裁剪边界；分别触发普通拟合直接接受与120ms消费接受。随后才决定是否需“正文证据未就绪时暂缓该次收缩”这类窄门禁；不能先恢复永久max高或给所有工具框套TextKit门禁。
4. **最小消融，仅在独立测试夹具**：只抑制该固定非流式正文的stable-shrink接受一次，其他三项160646变化保持；若消失，再单独替换父高/重入来源验证机制。消融只说明某路径必要性，不自动证明根因，更不是发布补丁。不要直接整包回滚160645，其设备框布局已有失败记录。

**判定矩阵**：

- 接受前独立正文末glyph需求>raw，接受后越过clip边界且画面同帧缺字：支持欠测收缩→裁剪。
- 祖先几何足够、末glyph完整，仍有局部透明/残留：转向绘制/属性/失效；检查颜色及布局generation，不动字号猜测。
- 不发生收缩仍卡字：否定“仅稳定收缩导致全部症状”，继续围绕该block的既有正文纠偏查证，不扩成全仓审计。
- 仅OCR变好或日志无HOLD：均不能判通过。需原文逐行可见、末标记完整、连续画面无消失/闪动，同时无旧高空白、邻行重叠与停稳跳变。

现有 `scripts/test_host_stable_shrink.py` 只是Python状态oracle和源码字符串契约；它从参数接收raw，完全未验证UIKit父高/host重入/正文glyph及clip。脚本中的历史高度序列不是真机新证据。本轮仅阅读，未重跑并冒充160646验证。

## 5. 不得回退的契约与放行底线

1. **保留iOS15即时可见与fade生命周期**：`SelectableMarkdownView.swift:10203–10208` 每次update取消alpha任务，`:10659–10673` 替换storage前cancel且仅iOS16+安排新fade；`TextFadeAnimator.swift:167–182` 恢复旧storage颜色并清任务。不得为修空白重新播iOS15 alpha，不得先换storage再取消旧range。
2. **保留属性前缀完整比较**：`SelectableMarkdownView.swift:10634–10647,10845起` 的比较helper不得降为只比字符或采样run起点；新旧属性run边界都要覆盖。160646没有改这些文件，不代表可以停止验这些行为。
3. **保留完整身份和全宽**：`iOS15Compat.swift:525–547,647–683` 的同完整身份复用、宽度重测、内容自有padding不得改成截短ID、每token换graph或二次扣32pt。revision只保护异步任务，不替代内容身份。
4. **保留防自播种与真实增长**：`MessageListInfrastructure.swift:553,608–619` 的compressed/zero-height及fittingSizeLevel不能改成上次cell高；不得恢复通用super-fit ceiling来遮住新问题，也不得关闭TextKit intrinsic高度或恢复3000→2000限高。
5. **保留裁剪与收缩问题的双边约束**：不能全局关clipsToBounds让文字溢出邻卡“看似恢复”，不能永久禁止收缩重新制造空白；工具/思考无TextKit仍须能正常增减。候选窄门禁必须有内容/身份/宽度/渲染就绪证据，并在证据齐后重试释放。
6. 放行至少覆盖：固定旧正文离屏返回及快滑停稳、逐token/停止/最终token后idle、前后台/复用；同时验文字不碎片化、不消失、不闪屏及工具/思考展开收起、无持续旧高空白。以上全是待做计划，不把旧测试或源码断言写作新运行成功。

结论：目前定位到**稳定收缩信任raw的新增决策，与已有父高约束/双层裁剪之间的接口**，不是已确定根因。先用同身份几何及glyph闭环区分“稳定欠测”“父裁剪”“绘制未刷新”，再做最窄修复；不能以修空白为理由牺牲已建立的文字保护。

## 6. 新增独立输入框回归：跳字（补充调查）

### 6.1 证据边界与版本归属

用户最新明确反馈：**当前160646输入框也在跳字**，不只是输出正文卡字/缺字。输入框必须单列未通过；不能以正文宿主调查代替输入框调查，也不能继续把此前“打字闪屏消失”当当前验收结果。当前采集仍未拿到有效布局日志，未获得可关联的输入框geometry/markedText/selection时序；“跳字”尚不能细分为光标跳、组合文字被覆盖或输入区域几何跳动。

`git diff 0960b07^ 0960b07 -- src/ios/Views/Chat/ChatInputBar.swift` 为空；父提交与当前文件SHA-256均为 `f162023e56f8d65deb095dbcea12a80037cbadc0204d6bcaca5c5dd1466e0d59`。以下输入侧风险是**160645已经存在的基线代码**，不是本轮新增setter或selection改动。源码相同也不证明运行时不受新的列表布局时序间接影响。

输入组件实际是 `PastableUITextView`（`ChatInputBar.swift:884`）及 `PastableTextView: UIViewRepresentable`（`:1420`），由 `AIChatView.swift:3529–3534,3598–3604` 创建并绑定输入/焦点/selection/滚动状态；`:3614–3624` 在普通模式用vertical fixedSize，手动调高模式用固定frame，再加padding。这条挂载路径不是消息cell的 `_HostingContentCellView`。0960b07改动的宿主稳定收缩、cell缓存及列表settle链**没有直接包裹或修改该输入控件**；尚未建立列表layout→composer重测/重绘的间接因果时序。

### 6.2 intrinsic / layoutSubviews / setter：确有基线不一致

- `ChatInputBar.swift:1162–1175`：intrinsic查询先用当前bounds宽测fit，**`:1169` 无条件赋值 `isScrollEnabled = size.height > maxHeight`**，再返回pinned或受maxHeight限制的高度。宽≤0有兜底，但宽>0不等于当前就是稳定排版宽。
- `:1238–1247`：layoutSubviews却有明确同值保护，仅滚动开关真正改变才赋值并invalidate intrinsic。`:1260–1274` 还会依据当前bounds/usedRect调整bottom inset，滚动时ensureLayout并校正contentSize。存在多条几何写入路径，需区分setter调用与实际值改变。
- `:1710–1713` 的程序性写入后滚动开关也有同值保护。因此“当前输入框所有setter均有保护”不准确；至少intrinsic入口没有。
- `:1600–1634` 的representable sizeThatFits也在`:1621`无条件写滚动开关，但函数明确标记iOS16+（`:1590–1599`，前面还有重复availability）。不能把它算作iOS15当前实际执行证据。iOS15更应优先抓取intrinsic与layoutSubviews。

**能证实**：测量getter存在写scroll状态的副作用、不同入口的保护不一致。**不能证实**：UIKit同值setter在本次实际触发了重入/offset变化，更不能据静态代码直接宣布它是用户跳字根因。历史main V72不在当前修复链的结论仍有效；不搬整套生成器，不以历史补丁标题代替运行验证。

### 6.3 markedText与selection同步：保护存在，但不覆盖所有写点

- `ChatInputBar.swift:1660`：仅当UI文本与binding不同，且无markedText或目标为空时，才写`tv.text`；`:1675–1682` 空目标情况下允许unmark后清空；`:1695–1696` 清空时reset selection。这保护普通非空binding更新不覆盖正在组合的IME，但空binding是有意例外。
- `:1735–1742`：desiredCaret写selection有UTF-16长度clamp和同值检查，**没有markedTextRange门禁**，也不在上述文本赋值条件内部。若组合期间恰有pendingCaret，仍可能移selection；本次没有pendingCaret实际非nil的证据，不能称已发生。
- `AIChatView.swift:3598` 传入`vm.pendingCaret`；`AIChatViewModel.swift:743–750` 在inputCaret匹配后清pendingCaret，故不能仅见desiredCaret代码就断言它永久重复执行。
- `ChatInputBar.swift:2208–2245`：didChange直接回写binding、invalidate intrinsic，并主动layout后发布滚动状态与caret；`:2308–2310` didChangeSelection直接发布selection/caret。两者没有统一的markedText抑制，但发布本身不等于破坏组合；需要上游消费时序证明。
- `:2274–2277` 对IME期间Return有保护，不能为治跳字删除；`:1667–1674` 注释仍声称会arm `skipNextProgrammaticChange`，但`:2209–2218` 已明确说明旧swallow机制被删除，当前写点也未设置该flag。应以实码为准，不能据旧注释重新加入吞下一键机制。

这些均属独立基线隐患/边界，不是0960b07新增。现阶段应并列保留“滚动/高度副作用”“markedText期间selection请求”“上游binding写入”三类可检验解释，而非提前指定一个。

### 6.4 输入框最小验证与不回退约束（未执行）

1. 在Apple/UIKit独立夹具固定字体、净宽、键盘与输入内容，先测composer独立存在，再在列表静止/停稳布局期间对照；不修改消息宿主策略来混淆输入结论。用中英组合输入、跨行及maxHeight阈值前后、移动光标/选区、mention插入、发送清空分别复现。
2. 关联记录intrinsic/layoutSubviews进入退出及深度、fit/bounds/usedRect、isScrollEnabled调用前后值、inset/contentSize/contentOffset、marked范围/selectedRange、binding长度/hash、desiredCaret及焦点状态。保留毫秒时序和画面，不记录用户原文。若只重复setter而无实际offset/selection/geometry变化，不能判它造成跳字。
3. 若geometry/offset跳而文本与selection稳定，优先查测量副作用；若marked期间selectedRange在desiredCaret路径改变，且同帧组合字/光标异常，支持selection干扰；若binding先变后走text赋值/unmark，则追溯具体上游写入。未抓到这些闭环前，不指定根因。
4. 只在测试夹具做单变量对照：intrinsic setter加同值门禁，或IME期间暂存程序性caret请求，分别验证，不把二者合成“万能修复”。保护有意清空、mention完成后光标移动、粘贴全文可达与maxHeight滚动。不得恢复吞下一键flag，不得禁止所有重测/滚动来掩盖跳动，不得牺牲中文组合输入与selection交互。

补充结论：**当前输出正文和输入框均未通过**。0960b07能直接定位到的是消息宿主链；输入框已定位到独立基线的intrinsic副作用与IME/selection边界，但没有本轮有效布局日志，无法确认二者是否共享触发时序或分别存在独立根因。
