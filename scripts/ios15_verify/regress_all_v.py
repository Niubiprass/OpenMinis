#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""全版本判据回归 —— 加一版就把**所有历史版本**的判据重跑一遍。

【为什么需要它】run#37137912522 的失败暴露了一个结构性风险:
v49 本身四层判据全绿, 70/70 + scope + 9/9 + 14 条 sabotage 都过,
但 CI 红了 —— 因为 **v48 的判据被 v49 的新代码误伤**:
    core=OK pure=BAD 赋值4处 违规=[...] 旁路=False idem=OK
    ❌ v48 异常
根因: v48 判据的段右边界是下游的 `// [IOS15-FIX-RELC v28]` 标记, 而 v49
探针正好插在钉宽 if 与那个标记之间 ⇒ v49 的三行记忆位写入被算进了
v48 的写入白名单。

**这类故障本地看不见**: 我跑的是 v49 自己的四层判据 + 一条整链注入,
没有把 v48 的判据在同一份产物上重跑。而 CI 会跑全部 54 条断言。

⇒ 纪律: **每加一版, 必须在同一份产物上重跑所有历史版本的判据**。
   本文件就是这个纪律的载体, 也是 CI 的第一道关(不依赖 GitHub)。

【它跑什么】对同一份产物依次执行:
  · v41 ~ v48 的 CI 判据
  · v47 / v48 的反向测试( sabotage 全拦 + 基线不误伤)
  · v49 的四层(struct / scope / heavy / sab)
  · v50 的三层(core / scope / sab 16 条)
  · v51 的三层(core / scope / sab 12 条)
判据文件缺失时**直接判失败** —— 判据被删 = 加法保护消失。
产物文件缺失时**判 SKIP 并显式列出** —— 那是本地产物树不完整(环境问题),
不是代码回归, 但必须喊出来, 绝不能静默通过。

【两种传参约定】历史判据的 argv 并不统一, 传错就会得到假失败:
  · arg=root : 收产物根目录, 内部自己拼 src/ios/... 路径
               (v43 v44 v45 v46 v47 v48 v49 reverse_v47 reverse_v48)
  · arg=swift: 直接收 SelectableMarkdownView.swift 的文件路径
               (v41 v42 —— 它们 open(path) 直接读, 传目录会
                IsADirectoryError, 这就是本文件最初 3 项失败的真因)

用法: regress_all_v.py <产物根目录 或 SelectableMarkdownView.swift>
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"
MLL_REL = "src/ios/Agent/MessageList/MessageListLayout.swift"
# v53 起判据跨**两个** swift 文件: C2 的三条高度短路在 infra 里,
# 而 C1/CONSUMED/FIRST 在 markdown view 里。少这个文件时必须 SKIP 并
# 显式报出, 不能让判据在缺料的情况下「碰巧全绿」。
INFRA_REL = "src/ios/Agent/MessageList/MessageListInfrastructure.swift"
# v65 的判据对象是 ObjC 守卫(不是 swift), 单独一个传参约定。
GUARD_REL = "src/ios/Shared/NSTextContainerSetSizeGuard.m"

# 干净上游的 src/ios 路径(幂等门的基线)。CI 里拿不到 —— 那里 fallback
# 已经跑过, 产物是移植过的, 自己拷自己当基线等于永远绿。
# 所以本地必须显式指一份没被移植过的上游, 拿不到就 SKIP。
UPSTREAM_IOS = os.environ.get("OPENMINIS_UPSTREAM_IOS", "")

# (显示名, 脚本名, 传参约定, 额外需要的产物文件)
CHECKS = [
    ("v41 判据",         "verify_v41.py",         "swift", []),
    ("v42 判据",         "verify_v42.py",         "swift", []),
    ("v43 判据",         "verify_v43.py",         "root",  [MLL_REL]),
    ("v44 判据",         "verify_v44.py",         "root",  []),
    ("v45 判据",         "verify_v45.py",         "root",  []),
    ("v46 判据",         "verify_v46.py",         "root",  []),
    ("v47 判据",         "ci_assert_v47.py",      "root",  []),
    ("v48 判据",         "ci_assert_v48.py",      "root",  []),
    ("v49 判据(四层)",   "ci_assert_v49.py",      "root",  []),
    ("v47 反向",         "reverse_v47.py",        "root",  []),
    ("v48 反向(20 条)", "reverse_v48.py",        "root",  []),
    ("v49 重文本+8 sab", "reverse_v49_heavy.py",  "swift", []),
    ("v49 作用域+12 sab", "reverse_v49_scope.py",  "swift", []),
    ("v50 判据(三层)+18 sab", "ci_assert_v50.py",  "root",  []),
    ("v51 判据(三层)+12 sab", "ci_assert_v51.py",  "root",  []),
    ("v52 判据(三层)+15 sab", "ci_assert_v52.py",  "root",  []),
    ("v53 判据(三层)+14 sab", "ci_assert_v53.py",  "root",  [INFRA_REL]),
    ("Swift 插值语法",
     "check_swift_interp_syntax.py",                  "root",  []),
    # 幂等门要一份**干净上游**做基线(自己拷自己没意义, 那样永远绿);
    # 拿不到干净上游就 SKIP 并显式报出, 绝不假装通过。
    ("产物级幂等(连跑3遍)",
     "check_idempotent_reapply.py",                   "upstream", []),
    # v565 的 9 条反向: 覆盖范围/只读/零赋值/禁用项/节流/紧贴/回写存在性。
    # ★它是本项目第一条「覆盖范围」判据 —— v46 探针装错类却全绿的教训。
    ("v565 反向(9条含覆盖范围)",
     "reverse_v565.py",                              "upstream", []),
    # v565 的 CI 入口: core(覆盖范围+结构) + scope(编译级) + scope自证(7 条)。
    # ★scope 自证不是凑数 —— 它抓出了第一版 scope 的真洞:
    #   只数格式串槽位个数 ⇒ `%.1f` 改成 `%.0f` 槽位数不变, 直接漏过,
    #   而丢小数对 v565 是致命的(它存在的意义就是读小数高度账)。
    #   逐槽位类型对齐就是被这条逼出来的。
    ("v565 判据(四层含scope自证)",
     "ci_assert_v565.py",                            "root",  []),
    # v566 的 9 条 sabotage: **重复代码只改一处**是这个形态的真名字。
    # ★ToolLiveSheet.swift 里 `cardWidth * 3.0 / 4.0` 有三处(两处终端 + 一处
    #   file_edit diff 卡片), 调研只报了两处 —— 判据与 sabotage 各抓了一次。
    ("v566 反向(10条含范围失控)",
     "reverse_v566.py",                              "upstream", []),
    # ★v56.7 是**换实现**而不是加新逻辑, 最危险的形态是「优化掉了但行为变了」。
    #   判据若只查「新代码在」照样全绿 —— 所以这 12 条里有 4 条(S5~S8)专门
    #   破坏边界分支, 逼判据的**等价性自证**那一层必须真的会红。
    #   跨两个文件(ToolLiveSheet + AIChatView)⇒ 判据作用域也要跟着分半。
    ("v567 反向(12条含等价性与跨文件)",
        "reverse_v567.py",                              "upstream", []),
    ("v568 反向(9条含防假修复与覆盖失控)",
        "reverse_v568.py",                              "upstream", []),
    # ★mode 空: reverse_v569.py 自己按相对路径定位产物(SelectableMarkdownView
    #   被十几个历史版本反复改过, 从干净上游跑会丢掉全部历史改动),
    #   不接 argv 也不需要干净上游。
    ("v569 反向(8条含声明未接线与整行语义)",
        "reverse_v569.py",                              "", []),
    # ★v57.0 同理, mode 空。防的是**容差放大**与**顺序错**两种
    #   "判据全绿但症状原样复发"的形态(S6/S5)。
    ("v571 反向(12条含纠偏四处顺序/v570真实位置)",
        "reverse_v570.py",                              "", []),
    # ★★ v63: 本项目第一条「判据自己也要被反向测」的链。
    #   动机是 v60 的元教训「v31~v59 从未被真机验证」—— 30 余版形状判据
    #   全绿, 而装机日志里 V53-DEBT/V62-SURPLUS 出现 0 次、live 恒为 0。
    #   形状判据只能证明"代码在", 证明不了"代码在跑"; 所以 v63 另带探针,
    #   而 reverse_v63 守的是**判据本身会不会失灵**。
    #   它与 v53/v62 的反向测试有一处根本不同: judge 直接调注入脚本里的
    #   verify_*_v63(纪律第 8 条「同一逻辑只能一处实现」), 不另写副本 ——
    #   副本会被后人只改一处, 于是判据红了而反向测试还绿。
    ("v63 判据(三条真实判据含语法级)",
        "ci_assert_v63.py",                            "root",  []),
    # ★run#157 事故的产物: 语法级判据 + 3 条新 sabotage(S15/S16/S17)。
    #   v63 首版把 static 计数器放进泛型类型, 66 条断言全绿而编译 exit 65 ——
    #   判据体系当时只能验文本、验不了语法。S15 复现的正是那个真实错误。
    ("v63 反向(17条含泛型static语法)",
        "reverse_v63.py",                              "root",  []),
    # ★★ v64: 切断 self-sizing 的「自我播种」—— 单向累加的真正病因。
    #   装机实证(v63 版): [V63-PROBE] fast=1412 rebuild=0, live 非 0
    #   ⇒ invalidate 通道真的通了(三十余版第一次)。但几何判据尾部极差
    #   717pt(v62 时 436pt, 反而更大), 形态从「翻转」变成**单调累加**
    #   (delta 恒 +144~+205pt ≈ 170pt/拍)。
    #
    #   ★关键证据(决定了 v64 为什么推翻重做): 6 拍的时间戳
    #     11:07:52.403 / .586 / .778 / 53.170 / .382 / 53.981
    #     ⇒ 间隔 0.183/0.192/0.392/0.212/0.599s, 全在 1.58s 内,
    #       且 **est_{n+1} 严格等于 pref_n**。
    #   ⇒ 高度不是「被谁算大了」, 是**被自己上一轮的答案累加出来的**
    #     (H_{n+1} = H_n + 170)。
    #   根因: MessageListInfrastructure.swift 里 targetSize 声明了
    #   layoutFittingCompressedSize(压缩语义 = 从内容重算), 下一行却用
    #   super 刚返回的、已膨胀的 attrs.size.height 当测量初值 ⇒ iOS 16+
    #   SwiftUI 遵守压缩优先级无害, **iOS 15 不遵守, 播种值胜出**。
    #
    #   ★v64 初版(同宽幂等锁)已被这组时间戳证伪并整体推翻: 0.35s 时间窗
    #   拦不住 0.392/0.599s 那两拍; 且它是全局单例, 列表里多个同宽 cell
    #   会互相冻结 ⇒ 内容截断, 比抖动更糟。
    #
    #   ★本项目的第三次「判据全绿但药不治病」:
    #     run#156 空测当通过 / run#157 只验文本不验语法 / v64 初版只验标记在位
    #   所以反向 9 条全部改成**问实质**: 闸门在不在(S1) 算不算(S2)
    #   改不改写(S3) 会不会误杀真实增长(S4) 播种真不取上一轮(S5/S6/S7)
    #   顺序对不对(S8) 有没有 est 下限(S9)。S6 专门防「换个属性名继续取
    #   上一轮」—— 判据不能只逐字匹配一种写法。
    ("v64 判据(不播种+收敛闸+数据流)",
        "ci_assert_v64.py",                            "root",  []),
    ("v64 反向(10条含S6换名/S8顺序/S10标识符)",
        "reverse_v64.py",                              "root",  []),
    # ★★ v65 守卫 —— v64 装机后暴露的**真根因**, 与 v64 那条线无关。
    #   v64 装机实测: 累加确实治好了(13 对 FIRST-MEASURE 无自旋, +170/拍消失),
    #   但用户仍报闪屏/抖动/卡字。真因在 NSTextContainerSetSizeGuard:
    #     ① size=0.0x-8.0 ×43 / 0.0x-16.0 ×18 被守卫**丢弃** ⇒ TextKit
    #        容器尺寸一次没更新 ⇒ 排版停在上一帧 ⇒ 卡字(est=31.0 就是一行);
    #     ② size=358.0x19.0 ×39 / 358.0x41.0 ×46 是**真实行高**却被风暴
    #        熔断吞掉 ⇒ 排版作废 ⇒ 「打一个字母抖一下」。
    #   ⇒ 病在「丢弃」这一侧, 治法必须是「就地修正后转发」+「熔断只对哨兵」。
    #   反向 10 条里 S2(块内 return)/S5(门槛挪到自增之后)/S9(引用作用域外
    #   的局部 const)/S10(引用不存在的标识符)分别钉住 run#159 与本轮真实
    #   犯过的两类编译红。
    ("v65 守卫判据(5层含作用域自证)",
        "verify_guard_v65.py",                         "guard", []),
    ("v65 反向(10条含S2块内return/S5顺序/S9作用域/S10标识符)",
        "reverse_guard_v65.py",                        "root",  []),
    # ★★ v63 几何基准 —— 本项目**第一条有绝对基准**的判据。
    #   v1~v62 共 62 版判据全是**相对**的(「比 v61 好」「标记在位」),
    #   从来没有一份回答过「正常的工具卡片应该多高」。后果已实证:
    #     v53→v62 每版都「相对更好」, 而装机日志 V53-DEBT/V62-SURPLUS
    #     出现 0 次、live 恒 0 —— 相对更好可以一直成立而病一直没好。
    #   基准来自用户提供的真机正常画面(同源移植, iPhone @3x):
    #     11 张同形态卡片 36.3~37.0pt, **极差 0.7pt**, 间距 8~11pt
    #     ⇒ 正常 = 卡片等高 + 间距恒定 = 高度由内容**一次算定**
    #   它守的是「结果对不对」, 而 verify_*_v63 守「机制在不在」——
    #   ★机制在而结果不对正是 v53~v62 的死法, 两者都要在。
    ("v63 几何基准(绝对基准+定型稳定)",
        "verify_v63_geometry.py",                      "", []),
    # ★★ v58/v60/v61/v62 这四项**从未注册进本链**, 只在 workflow 里被单独调。
    #   后果: 它们的锚点腐化(如 v61 的 S1 因 v63 加了 config 判等而落空)
    #   在本地回归里**看不见** —— 本地 29/0/0 全绿, 而 CI run#156 就炸在
    #   v61 上。run#156 之后才补注册。
    # ★mode=upstream: 这几个自己跑完整链(不接产物 argv), 耗时
    #   v58 1.8s / v61 15s / v62 28s / v60 71s ≈ 合计 2 分钟, 可接受。
    # ★v59 不在此列: 它自 v60 起永久判红(要求 [V59-NOTRACK] 存在, 而 v60
    #   明确要求它**必须为 0 处**), 已归档到 retired/ 并写明原因。
    ("v58 反向(8条)",
        "reverse_v58.py",                              "upstream", []),
    ("v61 反向(5条含REUSE锚点双形态)",
        "reverse_v61.py",                              "upstream", []),
    ("v62 反向(7条含guard双形态)",
        "reverse_v62.py",                              "upstream", []),
    ("v60 反向(11条含v59退场)",
        "reverse_v60.py",                              "upstream", []),
]

# 最近四代(v50/v51/v52/v53)的判据与反向测试是当前承重墙, 必须全绿。
# v41~v46 同样在 CI 里跑, 但它们跨代演进(判据 needle 有兼容层),
# 且部分依赖两文件产物, 缺失时以 SKIP 形式显式报出。
# ★v52 也要进 MANDATORY: v53 是在 v52 产物上继续改的, 而 v53 的 C1/C2
#   直接改写了 v52-A 闸门与 v52-E 判据所在的代码路径 —— v52 判据一旦
#   失效, v53 的「基线无误伤」就没有意义了(它跑在同一份产物上)。
MANDATORY = {
    "v50 判据(三层)+18 sab", "v51 判据(三层)+12 sab",
    "v52 判据(三层)+15 sab", "v53 判据(三层)+14 sab",
    "v47 反向", "v48 反向(20 条)",
    "v49 重文本+8 sab", "v49 作用域+12 sab",
    "v47 判据", "v48 判据", "v49 判据(四层)",
    # ★v56.4: 这两项进 MANDATORY —— run#138 是「前面全绿、编译才炸」,
    #   而 fix_markdown_layout_reconcile 的重复注入是「CI 从不炸、
    #   因为 CI 永远只跑一遍」。它们都不能是可选项。
    "Swift 插值语法", "产物级幂等(连跑3遍)",
    "v565 反向(9条含覆盖范围)",
    # ★v56.5: v565 判据必须进 MANDATORY —— 它是**唯一**盯住终端框的判据。
    #   v46 那条对 CodeBlockAttachment 失明已经证明过一次「判据全绿但探针
    #   测不到东西」; 缺了这条, 终端框就又回到只能靠猜的状态。
    "v565 判据(四层含scope自证)",
    # ★v56.6: 终端框的空白过大是**唯一**还没有专门判据保护的症状,
    #   而它是本项目第一次在**非 Markdown** 路径上修东西。
    "v566 反向(10条含范围失控)",
    # ★v56.7 治的是「卡显示/卡字/掉帧」, 与 v56.6 的「空白过大」症状不重叠,
    #   但它**换掉了一个函数的实现** ⇒ 必须有等价性保护, 否则「优化变改行为」
    #   这类回归没有任何门禁能挡。
    "v567 反向(12条含等价性与跨文件)",
    # ★★ v56.8: 必须是 MANDATORY —— 这是本项目**第四次**「对象选错」的纠正版,
    #   而前三版的共同特征就是「判据全绿但测不到用户说的那个东西」。
    #   v568 判据盯的是「offset 目标有没有和布局量解耦」+「动画有没有被
    #   顺手删掉」两条 —— 后者防的是「为了不卡就把动画删了」这种假修复,
    #   那会让症状消失但产品行为被悄悄改掉, 且没有任何日志能暴露。
    "v568 反向(9条含防假修复与覆盖失控)",
    # ★★ v56.9 必须是 MANDATORY: 它是**装机日志直接定罪**的一处 ——
    #   95 条 [V56-KVO] 全是 skipSame、零条 fixed, 其中 13 条 svH<needH。
    #   而 [V45-TVHFIX] 的 debt 却是 0.0(补高链自称已补好)。
    #   ⇒ 「判据全绿 + 补高链自称成功」与「实际一行只剩上半」同时成立。
    #   这类「自证式绿灯」没有任何其他门禁能挡, 只有专门的反向测试能挡。
    "v569 反向(8条含声明未接线与整行语义)",
    #   v57.0 装机日志 + 录屏交叉定罪: V50-LAIDW regrabbed=1(75帧) 与
    #   V44-TEXTFRAME tvW=390.0(75帧) **完全同集合** ⇒ 纠正机制已触发,
    #   容器却仍是 390 ⇒ 病在判据只覆盖单向 + 写在 pass 末尾。
    #   S6(容差 1→32) 尤其关键: 358 vs 390 的差正好 32,
    #   阈值一旦放到 32 就等于没修, 而字符串判据仍会全绿。
    "v571 反向(12条含纠偏四处顺序/v570真实位置)",
    # ★★★ v63 两项都进 MANDATORY, 且是**本项目第一次把"判据自己"列为承重墙**。
    #   理由链(全部有装机证据, 不是推测):
    #     v62 装机日志: V53-DEBT / V62-SURPLUS 出现 **0 次**;
    #                   live= 唯一取值 {0}, debt= 唯一取值 {0.0};
    #                   idx=19 工具消息 1.5s 内 6 次 INVALIDATE 全 cached=true,
    #                   pref 798→903→1057→1205→1336→1518 一路追着 est 跑。
    #     ⇒ 代码全在, 从未执行, 而 26 条判据全绿。
    #     ⇒ 「形状判据全绿」这个信号本身已被证明**不可信**, 必须有东西盯着它。
    #   reverse_v63 的 judge 直接调 verify_*_v63, 所以它红 ⇒ 判据真的失效;
    #   若哪天有人把判据改松以让 CI 过, 这条会立刻红 —— 这正是它存在的意义。
    "v63 判据(两条真实判据)", "v63 反向(14条含探针与转义)",
    "v63 几何基准(绝对基准+定型稳定)",
}


def _resolve(target):
    """返回 (swift 路径, 产物根目录 或 None)。"""
    if os.path.isfile(target):
        # 直接给了 swift 文件 —— 根目录往上退两级(src/ios/Views/Chat -> src)
        root = os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.dirname(os.path.abspath(target)))))
        return os.path.abspath(target), root
    if os.path.isdir(target):
        sp = os.path.join(target, MD_REL)
        if os.path.exists(sp):
            return sp, os.path.abspath(target)
    return None, None


def main():
    if len(sys.argv) < 2:
        print("用法: regress_all_v.py <产物根目录 或 SelectableMarkdownView.swift>")
        return 2
    sp, root = _resolve(sys.argv[1])
    if not sp:
        print("❌ 找不到产物:", sys.argv[1])
        print("   需要 %s 或含它的产物根目录" % MD_REL)
        return 1
    print("产物: %s (%d 字节)" % (sp, os.path.getsize(sp)))
    print("根目录: %s\n" % root)

    fail, skip, ok, skipped_detail = [], [], 0, []

    for name, fn, mode, extra in CHECKS:
        p = os.path.join(HERE, fn)

        # 判据脚本缺失 = 加法保护消失, 无条件失败。
        if not os.path.exists(p):
            print("❌ %-22s 判据文件缺失(%s) —— 判据被删 = 加法保护消失" % (name, fn))
            fail.append(name)
            continue

        # 产物依赖缺失 = 本地树不完整, 判 SKIP, 但必须显式报出。
        missing = []
        if mode == "root" and not root:
            missing.append(MD_REL)
        elif mode == "root":
            missing += [r for r in extra if not os.path.exists(os.path.join(root, r))]
        elif mode == "swift" and not sp:
            missing.append(MD_REL)
        elif mode == "guard":
            if not root or not os.path.exists(os.path.join(root, GUARD_REL)):
                missing.append(GUARD_REL)
        elif mode == "upstream":
            if not UPSTREAM_IOS or not os.path.isdir(UPSTREAM_IOS):
                missing.append("干净上游 src/ios(设 OPENMINIS_UPSTREAM_IOS)")
        if missing:
            print("⏭  %-22s SKIP(产物缺 %s)" % (name, ", ".join(missing)))
            skip.append(name)
            skipped_detail.append((name, missing))
            continue

        argv = [sys.executable, p]
        if mode == "root":
            argv.append(root)
        elif mode == "swift":
            argv.append(sp)
        elif mode == "guard":
            argv.append(os.path.join(root, GUARD_REL))
        elif mode == "upstream":
            if fn == "reverse_v565.py":
                argv += [os.path.join(HERE, "..", "ios15_fallback.py"),
                         UPSTREAM_IOS]
            else:
                argv += [os.path.join(HERE, "..", "ios15_fallback.py"),
                         UPSTREAM_IOS, "3"]
        if fn == "reverse_v49_heavy.py":
            argv.append("--sab")
        elif fn == "ci_assert_v565.py":
            # ★必须降级为不跑 sab: ci_assert_v565 内部会调 reverse_v565.py,
            #   而本链里 reverse_v565.py 本身就是一项 —— 不加会跑两遍,
            #   时间翻倍(它要重跑 9 遍 fallback)。
            # ★v51 踩过递归的坑(进程树指数膨胀, CI 挂死), 这里是同一个坑的
            #   轻量版: 不是递归, 是重复。方向仍须单向: 链跑入口, 入口自己跑 sab。
            argv.append("--no-sab")

        # ★必须显式传 env: 部分历史判据(reverse_v62 等)内部会再调
        #   ios15_port_v2.py, 而那个脚本默认要从 codeload 重下上游 tarball。
        #   慢网下实测卡满 timeout=180(进程 CPU 0%、wchan=do_poll),
        #   整条回归就卡在那儿。有 OPENMINIS_UPSTREAM_IOS 时(全链验证一定会设)
        #   就把它当本地上游传下去, 让内层也跳过下载。
        #   ★不改默认行为: 没设这个变量时, 内层仍走真实下载。
        _env = dict(os.environ)
        if UPSTREAM_IOS:
            _env.setdefault("OPENMINIS_UPSTREAM_LOCAL",
                            os.path.dirname(os.path.dirname(UPSTREAM_IOS.rstrip("/"))))
        try:
            r = subprocess.run(argv, capture_output=True, text=True,
                               timeout=1800, env=_env)
        except subprocess.TimeoutExpired:
            print("❌ %-22s 超时" % name)
            fail.append(name)
            continue

        if r.returncode == 0:
            ok += 1
            lines = [l for l in (r.stdout or "").strip().split("\n") if l.strip()]
            print("✅ %-22s %s" % (name, (lines[-1] if lines else "")[:56]))
        elif r.returncode == 3:
            # 判据自己说"环境不全, 没检查" —— 绝不能算通过。
            # 【本轮实踩】ci_assert_v49 原先找不到 fallback 时 return 0,
            # 于是输出是 "✅ v49 判据(四层) v49=SKIP(...)" —— 假绿。
            lines = [l for l in (r.stdout + r.stderr).strip().split("\n") if l.strip()]
            reason = (lines[-1] if lines else "退出码 3")[:70]
            print("⏭  %-22s SKIP(%s)" % (name, reason))
            skip.append(name)
            skipped_detail.append((name, [reason]))
        else:
            print("❌ %-22s" % name)
            for l in (r.stdout + r.stderr).strip().split("\n"):
                if l.strip():
                    print("      " + l[:100])
            fail.append(name)

    print()
    print("─" * 62)
    print("全版本回归: %d 通过, %d 失败, %d 跳过" % (ok, len(fail), len(skip)))

    if skipped_detail:
        print()
        print("⏭ 跳过项(产物树不完整, **不是**代码回归, 但别当它不存在):")
        for name, missing in skipped_detail:
            print("   · %-22s 缺 %s" % (name, ", ".join(missing)))
        print("   补齐后重跑本脚本。CI 里这些判据是在完整 checkout 上跑的。")

    if fail:
        print()
        print("❌ 失败项: %s" % ", ".join(fail))
        print()
        print("★ 排查提示: 若失败的是**历史版本**判据, 多半是本版把新代码插进了")
        print("  那一版的判据区间。本轮 v48 就是这么被 v49 误伤的:")
        print("    v48 判据的段右边界原是 // [IOS15-FIX-RELC v28], 而 v49 探针")
        print("    正好插在钉宽 if 与该标记之间 ⇒ v49 的记忆位写入被算进 v48")
        print("    的白名单 ⇒ pure=BAD 赋值4处。修法: 该判据的右界改到本版")
        print("    探针起点。**同一右界若有多个副本, 必须一次全改**。")
        hard = [f for f in fail if f in MANDATORY]
        if hard:
            print()
            print("★ 其中 %s 属承重墙, 必须修。" % ", ".join(hard))
        return 1

    print("✅ 全部通过 —— 历史版本的加法保护都没被本版破坏")
    return 0


if __name__ == "__main__":
    sys.exit(main())