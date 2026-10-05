#!/bin/bash
# ============================================================
# v63/v64 全链验证 —— 从干净上游到判据全绿, 一条命令跑完
#
# 为什么要这个脚本(踩过的坑):
#   移植是**三阶段**的, 少跑一阶段会得出错误结论:
#     ① ios15_port.py       改写 16 个 .swift(纯 API 降级)
#     ② ios15_port_v2.py    **生成 iOS15Compat.swift 兼容层**
#     ③ ios15_fallback.py   注入 v21~v64 全部补丁
#   v63 的 ① 落在 iOS15Compat.swift 上, 而那个文件是②生成的 ——
#   只跑③ 会静默 SKIP(edit() 对缺文件直接 return), 看起来"成功"实则没注入。
#   verify-discipline 第 6 条: 判据没跑就等于没人看守, 比红更危险。
#
# 用法: bash scripts/verify_v63.sh
# ============================================================
set -u
REPO="$(cd "$(dirname "$0")/.." && pwd)"
WORK="${WORK:-/tmp/v63verify}"
UPSTREAM="${UPSTREAM:-/tmp/up_1_14/src/ios}"

echo "════ 0. 前置检查 ════"
if [ ! -d "$UPSTREAM" ]; then
  echo "✗ 缺干净上游: $UPSTREAM"
  echo "  获取: cd /tmp && curl -sL -o up114.tar.gz \\"
  echo "    https://codeload.github.com/OpenMinis/OpenMinis/tar.gz/3fe0f6c3c1ffe31a2f692abc39652eb4932df94b \\"
  echo "    && mkdir -p up_1_14 && tar -xzf up114.tar.gz -C up_1_14 --strip-components=1"
  exit 1
fi
# 干净度: 不得含任何注入标记(否则是"看起来干净"的树, 纪律附则明确点名过)
if grep -rq "IOS15-FIX\|V53-DEBT\|V62-SURPLUS\|V63-" "$UPSTREAM" 2>/dev/null; then
  echo "✗ 上游不干净(含注入标记) —— 拿已注入的树当基线会让幂等测试假绿"
  exit 1
fi
echo "✓ 干净上游就绪: $UPSTREAM"

echo
echo "════ 1. 阶段① ios15_port.py ════"
rm -rf "$WORK"
# 必须复制 tarball 的**仓库根**(阶段②要看到 .xcodeproj / Minis.xcodeproj 才能注入工程)
cp -a "$(dirname "$UPSTREAM")/.." "$WORK" 2>/dev/null || cp -a /tmp/up_1_14 "$WORK"
if [ ! -d "$WORK/src/ios" ]; then
  echo "✗ 产物树结构不对: $WORK/src/ios 不存在"
  echo "  UPSTREAM 应指向 <仓库根>/src/ios, 当前: $UPSTREAM"
  exit 1
fi
python3 "$REPO/scripts/ios15_port.py" "$WORK/src/ios" 2>&1 | tail -2 || exit 1

echo
echo "════ 2. 阶段② ios15_port_v2.py (生成兼容层) ════"
# ★复用本地上游: 阶段② 默认会从 codeload 重下 tag 1.14 的 tarball。慢网下
#   实测会挂在 socket 上卡满 timeout=180(进程 CPU 0%、wchan=do_poll),
#   本地全链每轮重下一次纯属浪费。上游是固定 tag, 一天内不会变。
#   ★CI 不设这个变量 —— 那里必须走真实下载, 那是"确保拿到上游原版"的唯一保障。
( cd "$WORK" && OPENMINIS_UPSTREAM_LOCAL="${OPENMINIS_UPSTREAM_LOCAL:-$(dirname "$(dirname "$UPSTREAM")")}" \
  python3 "$REPO/scripts/ios15_port_v2.py" 2>&1 | tail -3 ) || exit 1
if [ ! -f "$WORK/src/ios/iOS15Compat.swift" ]; then
  echo "✗ iOS15Compat.swift 未生成 —— 阶段③ 会静默 SKIP 掉全部 hosting 层注入"
  exit 1
fi
echo "✓ iOS15Compat.swift 已生成 ($(wc -l < "$WORK/src/ios/iOS15Compat.swift") 行)"

echo
echo "════ 3. 阶段③ ios15_fallback.py (v21~v64) ════"
python3 "$REPO/scripts/ios15_fallback.py" "$WORK/src/ios" 2>&1 | tail -2 || exit 1

echo
echo "════ 4. v63/v64 落点核对(缺任一项即为静默 SKIP) ════"
MISS=0
check() {  # check <文件> <标记> <说明>
  if grep -q "$2" "$WORK/src/ios/$1" 2>/dev/null; then
    echo "  ✓ $3"
  else
    echo "  ✗ 缺 $3  ← 注入未生效"; MISS=1
  fi
}
check iOS15Compat.swift                        "V63-PROBE"   "V63-PROBE 探针(hosting 层)"
check iOS15Compat.swift                        "V63-CFG"     "V63-CFG  世代号/身份判等"
check iOS15Compat.swift                        "V63-UPDATE"  "V63-UPDATE invalidate"
check Views/Chat/SelectableMarkdownView.swift  "V63-INTSIZE" "V63-INTSIZE 高度上报恢复"
check Views/Chat/SelectableMarkdownView.swift  "V63-UNCYCLE" "V63-UNCYCLE 打破循环依赖"
[ "$MISS" -eq 0 ] || { echo "✗ v63 未完整注入"; exit 1; }

# ---- v64 落点核对(缺任一项即为静默 SKIP) ----
MISS=0
check Agent/MessageList/MessageListInfrastructure.swift "V64-DESEED"   "V64-DESEED   切断自我播种"
check Agent/MessageList/MessageListInfrastructure.swift "V64-CONVERGE" "V64-CONVERGE 收敛闸"
[ "$MISS" -eq 0 ] || { echo "✗ v64 未完整注入"; exit 1; }

echo
echo "════ 5. v63 判据链(CI 入口 core+probe, 内含 reverse_v63 的 17 条 sab) ════"
python3 "$REPO/scripts/ios15_verify/ci_assert_v63.py" "$WORK" 2>&1 | sed 's/^/  /' || exit 1
echo
echo "════ 5-v64. v64 判据链(切断自我播种, 内含 reverse_v64 的 9 条 sab) ════"
# ★为什么单独一节而不是并进 5: v64 改的是**另一个文件**的**另一个函数**
#   (SelfSizingCell.preferredLayoutAttributesFitting), 与 v63 的三处落点
#   (hosting 层 invalidate / config 判等 / 高度上报)无交集。混在一处会让
#   "v63 绿了"被误读成"整链绿了" —— run#157 就是这么全绿而编译红的。
python3 "$REPO/scripts/ios15_verify/ci_assert_v64.py" "$WORK" 2>&1 | sed 's/^/  /' || exit 1
echo
echo "════ 5b. 内置判据直调(verify_*_v63/v64, 不经 CI 包装) ════"
# ★W 必须由调用方传入: 硬编码 /tmp/v63verify 会让「在别的 WORK 下跑」时
#   读到上一轮的旧产物 —— 那正是 verify-discipline 点名过的「看起来跑过、
#   实际验的是旧东西」。run#156 的空测就是这类。
cd "$REPO" && W="$WORK/src/ios/" python3 - <<'PYEOF' || exit 1
import sys, os
sys.path.insert(0, "scripts")
import importlib.util
spec = importlib.util.spec_from_file_location("fb", "scripts/ios15_fallback.py")
fb = importlib.util.module_from_spec(spec)
try:
    spec.loader.exec_module(fb)
except SystemExit:
    pass
W = os.environ.get("W", "/tmp/v63verify/src/ios/")
compat = open(W + "iOS15Compat.swift", encoding="utf-8").read()
md = open(W + "Views/Chat/SelectableMarkdownView.swift", encoding="utf-8").read()
infra = open(W + "Agent/MessageList/MessageListInfrastructure.swift", encoding="utf-8").read()
ok = True
# ★第三条 verify_swift_static_v63 是 run#157 的直接产物(语法级判据):
#   v63 首版把 static 计数器放进泛型类型, 前两条判据全绿而编译 exit 65。
for name, fn, args in (("verify_intrinsic_gate_v63", fb.verify_intrinsic_gate_v63, (compat, md)),
                       ("verify_uncouple_v63",      fb.verify_uncouple_v63,      (md,)),
                       ("verify_swift_static_v63",  fb.verify_swift_static_v63,  (compat,)),
                       ("verify_deseed_v64",        fb.verify_deseed_v64,        (infra,))):
    try:
        fn(*args); print("  ✅ %s" % name)
    except Exception as e:
        ok = False; print("  ❌ %s\n     %s" % (name, e))
sys.exit(0 if ok else 1)
PYEOF

echo
echo "════ 6. 全版本回归(含 v63/v64) ════"
# 判据需要从产物树里找到 scripts/ios15_fallback.py(v53 判据的 sab 层要读它)
mkdir -p "$WORK/scripts" && cp "$REPO/scripts/ios15_fallback.py" "$WORK/scripts/"
cd "$REPO" && OPENMINIS_UPSTREAM_IOS="$UPSTREAM" \
  python3 scripts/ios15_verify/regress_all_v.py "$WORK" 2>&1 | tail -20

echo
echo "════ 7. 幂等(连跑两遍产物应逐字节相同) ════"
cd "$REPO" && python3 - "$WORK" <<'PYEOF'
import hashlib, os, shutil, subprocess, sys
W = sys.argv[1]
def snap(root):
    out = {}
    for d, _, fs in os.walk(os.path.join(root, "src/ios")):
        for f in fs:
            if f.endswith((".swift", ".m", ".h")):
                p = os.path.join(d, f)
                out[os.path.relpath(p, root)] = hashlib.sha256(open(p,'rb').read()).hexdigest()
    return out
a = snap(W)
subprocess.run([sys.executable, "scripts/ios15_fallback.py", os.path.join(W, "src/ios")],
               capture_output=True)
b = snap(W)
if a == b:
    print("  ✅ 幂等: %d 个文件逐字节相同" % len(a))
else:
    diff = [k for k in a if a.get(k) != b.get(k)]
    print("  ❌ 非幂等, %d 个文件变了: %s" % (len(diff), diff[:5]))
    sys.exit(1)
PYEOF

echo
echo "════════════════════════════════"
echo "✅ v63 全链验证通过"
echo ""
echo "⚠️  v60 的教训: \"v31~v59 从未被真机验证\"。"
echo "    判据全绿 ≠ 病治好。装机后请确认日志里出现:"
echo "      [V63-PROBE] fast=N rebuild=M   (N>0 说明快速路径在跑)"
echo "      live=N  (N>0 才说明真实测量放行了 —— v62 装机时恒为 0)"
echo "════════════════════════════════"
