#!/usr/bin/env python3
"""断言 74 —— v69「容器工厂」形态风暴的**语义级**判据。

============================================================================
为什么这一个判据必须是"跑程序", 不能是"查文本"
============================================================================
v66~v68 连续三版, 每一版的判据都是**文本/结构**判据:
  · v66 ⑦层:   "nonPositiveStreak 会不会被清零?"      → 恒真 → 假绿
  · v68 判据:  "累加语句是否在 per-tick 门槛之外?"      → 是   → 真绿(但只治了一半)
  · v68 ②层:   "降频语句在不在、游标在不在?"            → 都在 → 假绿
而 2026-10-06 2.log 装机实测: 196 万次调用, DOWNFREQ **0** 次。
语句全在、结构全对, 行为却是"一次没减"。

★ 根因不是"语句写得对不对", 而是"**语句挂的那个对象活得够不够久**":
  SwiftUI measure 候选项时每次新建一个 NSTextContainer ⇒ GuardState 每次全新
  ⇒ streak 恒 1、skipTick 恒 0、lastGoodHeight 恒 0 ⇒ 三道闸门一道都开不了。

★ 文本判据**永远**问不出这一类问题 —— 这是本项目**第十三次**
  「验证手段骗了自己」。要问"活得够不够久", 判据就必须**真的跑一遍循环**,
  在"容器每次重建"的输入下数出转发次数。

============================================================================
本判据做什么
============================================================================
把守卫在非正尺寸路径上的控制流抽成一个**独立的 C 程序**, 用装机日志实测的
输入(1,957,633 次 setSize, 每次容器全新, orig=0x0)跑两遍:

  分支 A —— v68 逻辑(全 per-container):  期望 **全部转发**(≈196 万)
            ↑ 这不是"随便写的期望值", 它必须与装机日志吻合:
              日志 FIXED-NONPOSITIVE 61156 条 ×32 ≈ 1,957,056, 且
              DOWNFREQ=0 / storm-breaker=0 ⇒ 一次没拦住。
            ★ 若 A 分支不再输出 196 万, 说明**模拟与真机不一致**, 判据失效。

  分支 B —— v69 逻辑(加进程级计数):      期望 **≈3 万**(1/64 降频)
            ↑ 401 + (N-401)/64

同时验证 lastGoodHeight 的**自锁**:
  分支 A 的 GOODH 会把守卫自己修正出来的 1.0 记成"真实高度"
    ⇒ 下一轮取到的历史恒为 1.0 ⇒ 与日志 `-> 326.0x1.0` 吻合(自锁成立)
  分支 B 的 GOODH 只在**原始**尺寸为正时才记录
    ⇒ 一旦进程里出现过真实高度(如聊天页的 16.0), 修正值就是 16.0 而不是 1.0

============================================================================
用法
============================================================================
    python3 assert_v69_global_storm.py            # 跑判据
    python3 assert_v69_global_storm.py --selftest  # 跑自证(含坏样本)
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile

# ---------- 装机日志实测常量 (minis-2026-10-06 2.log, PID 32470) ----------
N_CALLS = 1_957_633          # 日志末条 total=1957633
LOG_FIXED_LINES = 61_156     # FIXED-NONPOSITIVE 条数(每 32 打 1)
LOG_STRIDE = 32
LOG_DOWNFREQ = 0             # NONPOSITIVE-DOWNFREQ
LOG_STORMBREAKER = 0         # storm-breaker SKIP
LOG_STREAK_MAX = 1           # 22 条 STREAK 全部 streak=1

# v68/v69 常量(必须与源码逐字对齐)
K_HARD_LIMIT = 400
K_GLOBAL_LIMIT = 400
K_SKIP_STRIDE = 64
K_GOOD_RUN_RESET = 128

# 模拟里"上游曾经排过版的真实高度"(聊天页实测 358x16.0)
REAL_HEIGHT = 16.0
FALLBACK_HEIGHT = 1.0


C_SRC = r"""
#include <stdio.h>
#include <math.h>

/* ---- 与源码对齐的常量 ---- */
static const long K_HARD_LIMIT      = %(hard)d;
static const long K_GLOBAL_LIMIT    = %(glim)d;
static const long K_SKIP_STRIDE     = %(stride)d;
static const long K_GOOD_RUN_RESET  = %(goodrun)d;
static const long K_STORM_LIMIT     = 40;

/* ---- per-container 状态(每次循环重建 = 全 0, 模拟"容器工厂") ---- */
typedef struct {
    long  commitCount;
    long  nonPositiveStreak;
    long  nonPositiveSkipTick;
    double lastGoodHeight;
    int   initialized;
    int   stormed;
} GState;

static void reset_state(GState *s) {
    /* [_NSTextContainerGuardState new] ⇒ 全 0 / NO */
    s->commitCount = 0;
    s->nonPositiveStreak = 0;
    s->nonPositiveSkipTick = 0;
    s->lastGoodHeight = 0.0;
    s->initialized = 0;
    s->stormed = 0;
}

/* =========================================================================
   分支 A —— v68: 全部计数 per-container
   ========================================================================= */
static void run_v68(long n, int have_real_history,
                    long *out_fwd, double *out_last_fixed_h,
                    long *out_storm, long *out_downfreq) {
    long fwd = 0, storm = 0, downfreq = 0;
    double g_last_good = 0.0;   /* 进程级"曾见过的真实高度"(仅用于喂历史) */
    double last_fixed_h = 0.0;

    for (long i = 0; i < n; i++) {
        GState s; reset_state(&s);          /* ★容器每次都是新的 */
        double orig_w = 0.0, orig_h = 0.0;
        double new_h = 0.0, new_w = 326.0;

        /* ---- 非正高度修正段 ---- */
        double ah = fabs(new_h);
        if (!(ah > 1.0)) {
            double prev = s.lastGoodHeight;                 /* 恒 0 */
            ah = (prev > 1.0 && isfinite(prev)) ? prev : 1.0;
        }
        new_h = ah;
        last_fixed_h = new_h;

        /* ---- 风暴预算 / streak ---- */
        if (new_h >= 2000.0) {
            s.commitCount += 1;
            if (s.commitCount > K_STORM_LIMIT) { s.stormed = 1; storm++; }
        } else if (orig_h <= 0.0 || orig_w <= 0.0) {
            s.commitCount += 1;
            if (s.commitCount > K_STORM_LIMIT) { s.stormed = 1; storm++; }
            s.nonPositiveStreak += 1;                        /* 恒 = 1 */
        }

        /* ---- v68 降频闸门(per-container) ---- */
        if (s.nonPositiveStreak > K_HARD_LIMIT) {
            downfreq++;
            s.nonPositiveSkipTick += 1;                      /* 恒 1 */
            if (s.nonPositiveSkipTick < K_SKIP_STRIDE) { continue; }  /* drop */
            s.nonPositiveSkipTick = 0;
        }

        /* ---- v68 GOODH: 只看 newSize.height > 0 ⇒ 把 1.0 记成"真实高度" ---- */
        if (new_h > 0.0 && isfinite(new_h) && new_h <= 1e5) {
            s.lastGoodHeight = new_h;
            g_last_good = new_h;
        }
        fwd++;                                               /* 真转发 */
    }
    *out_fwd = fwd; *out_last_fixed_h = last_fixed_h;
    *out_storm = storm; *out_downfreq = downfreq;
    (void)g_last_good; (void)have_real_history;
}

/* =========================================================================
   分支 B —— v69: 进程级计数 + 全局游标 + 全局历史兜底 + 自愈退出
   ========================================================================= */
static void run_v69(long n, int have_real_history,
                    long *out_fwd, double *out_last_fixed_h,
                    long *out_storm, long *out_downfreq,
                    long *out_gstreak) {
    long fwd = 0, storm = 0, downfreq = 0;
    long g_streak = 0, g_skip = 0, g_good_run = 0;
    double g_last_good = have_real_history ? %(real).1f : 0.0;
    double last_fixed_h = 0.0;

    for (long i = 0; i < n; i++) {
        GState s; reset_state(&s);          /* ★容器仍然每次都是新的 */
        double orig_w = 0.0, orig_h = 0.0;
        double new_h = 0.0, new_w = 326.0;

        /* ---- 非正高度修正段(加进程级兜底) ---- */
        double ah = fabs(new_h);
        if (!(ah > 1.0)) {
            double prev = s.lastGoodHeight;                  /* 恒 0 */
            if (!(prev > 1.0 && isfinite(prev))) {
                prev = g_last_good;                          /* ★进程级兜底 */
            }
            ah = (prev > 1.0 && isfinite(prev)) ? prev : 1.0;
        }
        new_h = ah;
        last_fixed_h = new_h;

        /* ---- 风暴预算 / streak ---- */
        if (new_h >= 2000.0) {
            s.commitCount += 1;
            if (s.commitCount > K_STORM_LIMIT) { s.stormed = 1; storm++; }
        } else if (orig_h <= 0.0 || orig_w <= 0.0) {
            s.commitCount += 1;
            if (s.commitCount > K_STORM_LIMIT) { s.stormed = 1; storm++; }
            s.nonPositiveStreak += 1;
            g_streak += 1;                                   /* ★进程级累加 */
            g_good_run = 0;
        } else if (orig_h > 0.0 && orig_w > 0.0) {
            g_good_run += 1;                                 /* ★自愈退出 */
            if (g_good_run >= K_GOOD_RUN_RESET) { g_streak = 0; g_good_run = 0; }
        }

        /* ---- v69 降频闸门(per-container OR 全局) ---- */
        if ((s.nonPositiveStreak > K_HARD_LIMIT) || (g_streak > K_GLOBAL_LIMIT)) {
            downfreq++;
            g_skip += 1;                                     /* ★全局游标 */
            if (g_skip < K_SKIP_STRIDE) { continue; }        /* drop */
            g_skip = 0;
        }

        /* ---- v69 GOODH: 只有**原始**尺寸为正才记 ⇒ 1.0 不会被记成历史 ---- */
        if (new_h > 0.0 && isfinite(new_h) && new_h <= 1e5 &&
            new_h < 2000.0 && orig_h > 0.0 && orig_w > 0.0) {
            s.lastGoodHeight = new_h;
            g_last_good = new_h;
        }
        fwd++;
    }
    *out_fwd = fwd; *out_last_fixed_h = last_fixed_h;
    *out_storm = storm; *out_downfreq = downfreq; *out_gstreak = g_streak;
}

int main(void) {
    long n = %(n)ldL;
    long a_fwd, a_storm, a_df; double a_h;
    long b_fwd, b_storm, b_df, b_gs; double b_h;

    run_v68(n, 0, &a_fwd, &a_h, &a_storm, &a_df);
    run_v69(n, 1, &b_fwd, &b_h, &b_storm, &b_df, &b_gs);

    printf("V68 forward=%%ld lastFixedH=%%.1f storm=%%ld downfreq=%%ld\n",
           a_fwd, a_h, a_storm, a_df);
    printf("V69 forward=%%ld lastFixedH=%%.1f storm=%%ld downfreq=%%ld gstreak=%%ld\n",
           b_fwd, b_h, b_storm, b_df, b_gs);
    return 0;
}
""" % {
    "hard": K_HARD_LIMIT, "glim": K_GLOBAL_LIMIT, "stride": K_SKIP_STRIDE,
    "goodrun": K_GOOD_RUN_RESET, "real": REAL_HEIGHT, "n": N_CALLS,
}


def _run_c() -> dict:
    """编译并运行 C 模拟, 返回解析后的结果。"""
    with tempfile.TemporaryDirectory() as d:
        src = os.path.join(d, "sim.c")
        exe = os.path.join(d, "sim")
        with open(src, "w") as f:
            f.write(C_SRC)
        cp = subprocess.run(["cc", "-O2", "-o", exe, src, "-lm"],
                            capture_output=True, text=True)
        if cp.returncode != 0:
            raise AssertionError("C 模拟编译失败:\n" + cp.stderr)
        rp = subprocess.run([exe], capture_output=True, text=True)
        if rp.returncode != 0:
            raise AssertionError("C 模拟运行失败:\n" + rp.stderr)
        out = {}
        for line in rp.stdout.strip().splitlines():
            parts = line.split()
            tag = parts[0]
            kv = {}
            for p in parts[1:]:
                if "=" in p:
                    k, v = p.split("=", 1)
                    kv[k] = v
            out[tag] = kv
        return out


def check() -> int:
    fail = []
    r = _run_c()
    v68 = r["V68"]
    v69 = r["V69"]

    a_fwd = int(v68["forward"])
    a_h = float(v68["lastFixedH"])
    a_df = int(v68["downfreq"])
    b_fwd = int(v69["forward"])
    b_h = float(v69["lastFixedH"])
    b_df = int(v69["downfreq"])

    # ---- 断言 1: v68 分支必须与**装机日志**吻合(证明模拟没跑偏) ----
    if a_fwd != N_CALLS:
        fail.append(
            f"模拟与真机不一致: v68 分支转发 {a_fwd} 次, 应等于日志实测 "
            f"{N_CALLS} 次(DOWNFREQ=0 意味一次没拦住)。"
            f"若这里不等, 说明模拟的控制流与源码不一致, 本判据全部结论作废。")
    if a_df != LOG_DOWNFREQ:
        fail.append(f"v68 分支 downfreq={a_df}, 日志实测 {LOG_DOWNFREQ}")

    # ---- 断言 2: v68 的修正值恒为 1.0(与日志 -> 326.0x1.0 吻合) ----
    if abs(a_h - FALLBACK_HEIGHT) > 1e-9:
        fail.append(
            f"v68 修正值应为裸 {FALLBACK_HEIGHT} (日志实测 326.0x1.0), 实得 {a_h}")

    # ---- 断言 3: v69 必须把转发压到 1/64 量级 ----
    expected = K_GLOBAL_LIMIT + 1 + (N_CALLS - K_GLOBAL_LIMIT - 1) // K_SKIP_STRIDE
    if not (b_fwd <= expected * 1.05 and b_fwd >= expected * 0.5):
        fail.append(
            f"v69 降频无效: 转发 {b_fwd} 次, 期望约 {expected} 次(1/{K_SKIP_STRIDE})")

    # ---- 断言 4: v69 削减比例必须达到两个数量级 ----
    ratio = a_fwd / max(b_fwd, 1)
    if ratio < 50:
        fail.append(f"v69 削减不足: 仅降到 1/{ratio:.1f}, 要求至少 1/50")

    # ---- 断言 5: v69 的修正值必须用上真实高度, 而不是裸 1.0 ----
    if abs(b_h - REAL_HEIGHT) > 1e-9:
        fail.append(
            f"v69 修正值应回填真实高度 {REAL_HEIGHT}, 实得 {b_h}。"
            f"若仍是 {FALLBACK_HEIGHT}, 说明进程级历史兜底没生效 —— "
            f"上游拿到 1.0 和拿到 0.0 同样排不出东西, 活锁一圈没断。")

    # ---- 断言 6: v69 的降频闸门必须真的开过 ----
    if b_df <= 0:
        fail.append("v69 downfreq=0 —— 闸门又没开(与 v68 装机同病)")

    print(f"[断言74] v68 分支: 转发 {a_fwd} 次, 修正值 {a_h}, downfreq {a_df} "
          f"  ← 必须等于装机日志(模拟可信性自检)")
    print(f"[断言74] v69 分支: 转发 {b_fwd} 次, 修正值 {b_h}, downfreq {b_df}")
    print(f"[断言74] 削减: {a_fwd} → {b_fwd} (1/{ratio:.0f})")

    if fail:
        for m in fail:
            print(f"[断言74] ❌ {m}")
        return 1
    print("[断言74] ✅ 全部通过")
    return 0


def selftest() -> int:
    """自证: 判据必须能**报红**, 否则它自己就是假的。

    坏样本 = 把 v69 的全局计数去掉(退回 v68 逻辑), 期望判据报红。
    """
    global C_SRC
    orig = C_SRC
    bad = C_SRC.replace("g_streak += 1;                                   /* ★进程级累加 */",
                        "/* 坏样本: 全局累加被删 */")
    bad = bad.replace("(g_streak > K_GLOBAL_LIMIT)", "(0)")
    if bad == orig:
        print("[自证] ❌ 坏样本构造失败(替换未命中) —— 判据自身不可信")
        return 1
    C_SRC = bad
    rc = check()
    C_SRC = orig
    if rc == 0:
        print("[自证] ❌ 坏样本竟然全绿 —— 判据没有鉴别力")
        return 1
    print("[自证] ✅ 坏样本正确报红")

    # 好样本复跑必须为 0
    rc2 = check()
    if rc2 != 0:
        print("[自证] ❌ 恢复后仍报红")
        return 1
    print("[自证] ✅ 好样本复跑全绿")
    return 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    sys.exit(check())
