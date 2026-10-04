#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""v58 scope 层自证 —— 证明 scope_check() 真的会红。

跑法: selfcheck_scope_v58.py <产物根目录 或 SelectableMarkdownView.swift>

【为什么必须有这个文件】
  scope 层是 v58 **新写**的判据层, 没有任何历史包袱。但「新写」不等于「可信」——
  v46 的教训是: 一条永远全绿的判据, 和没有判据是同一个东西。
  v565 也吃过一次亏: 它 scope 层第一版只数槽位个数, 把 `%.1f` 改成 `%.0f`
  直接漏过(槽位数不变), 逼得后来补了逐槽位类型对齐。

  所以纪律是: **新写的判据层必须先反向测试, 才允许进 CI 当看守。**
  只数 5 条, 因为 scope 层只查 5 件事(见下)。每条都对应一个真实编译错
  或一个真实的"探针白写"形态。

五条:
  SA1 删掉一个实参        ⇒ 槽位数 != 实参数 ⇒ 编译错
  SA2 把 %.1f 改成 %.0f  ⇒ 槽位数不变但精度丢失(专打"只数个数"的弱判据)
  SA3 节流阈值改成 0      ⇒ 每帧打日志 ⇒ 诊断本身成为掉帧源
  SA4 节流阈值改成 0.01  ⇒ 同上, 只是更隐蔽(0.05 这种"看起来很小"的值)
  SA5 删掉 CACurrentMediaTime ⇒ 节流器失效(判据要能发现)

基线必须不误伤 —— 这也是自证的一部分: 判据红了但基线也红, 等于没判据。
"""
import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import importlib.util

spec = importlib.util.spec_from_file_location(
    "ci58", os.path.join(HERE, "ci_assert_v58.py"))
ci58 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ci58)

MD_REL = "src/ios/Views/Chat/SelectableMarkdownView.swift"


def load(target):
    md = ci58.resolve(target)
    if md is None:
        raise SystemExit("找不到产物: %s" % MD_REL)
    return io.open(md, encoding="utf-8").read()


# ----------------------------------------------------------------------
def sa1_drop_arg(x):
    """删掉 tcW 那行实参 ⇒ 槽位 6 个、实参 5 个 ⇒ 编译错。"""
    m = re.search(r'\n\s*self\.textContainer\.size\.width,(?=\n\s*self\.)', x)
    if not m:
        return x, '锚点缺失'
    return x[:m.start()] + x[m.end():], '删一个实参'


def sa2_precision(x):
    """把某个 %.1f 改成 %.0f —— 槽位数不变, 弱判据会漏过。"""
    if '[V58-REFLOW]' not in x:
        return x, '锚点缺失'
    i = x.find('NSLog("[V58-REFLOW]')
    j = x.find('%.1f', i)
    if j < 0 or j - i > 400:
        return x, '锚点缺失'
    return x[:j] + '%.0f' + x[j + 4:], '精度改 %.0f'


def sa3_throttle_zero(x):
    m = re.search(r'(_v58Now - _V58Log\.last > )([0-9.]+)', x)
    if not m:
        return x, '锚点缺失'
    return x[:m.start(2)] + '0' + x[m.end(2):], '节流阈值=0'


def sa4_throttle_tiny(x):
    m = re.search(r'(_v58Now - _V58Log\.last > )([0-9.]+)', x)
    if not m:
        return x, '锚点缺失'
    return x[:m.start(2)] + '0.01' + x[m.end(2):], '节流阈值=0.01'


def sa5_no_cmt(x):
    return x.replace('CACurrentMediaTime()', 'CFAbsoluteTime()'), \
        '换掉 CACurrentMediaTime'


SAB = [
    ('SA1 删一个实参', sa1_drop_arg),
    ('SA2 %.1f 改 %.0f', sa2_precision),
    ('SA3 节流阈值=0', sa3_throttle_zero),
    ('SA4 节流阈值=0.01', sa4_throttle_tiny),
    ('SA5 换掉 CACurrentMediaTime', sa5_no_cmt),
]


def main():
    if len(sys.argv) < 2:
        print("用法: selfcheck_scope_v58.py <产物根目录 或 .swift 路径>")
        return 3
    base = load(sys.argv[1])

    bad = ci58.scope_check(base)
    if bad:
        print("❌ 基线就红 —— scope 层在正确产物上报了 %d 条:" % len(bad))
        for b in bad:
            print("     · %s" % b)
        print("⇒ 判据对正确产物误报, 等于没有判据。")
        return 1
    print("✅ 基线通过")

    caught = leaked = 0
    for name, fn in SAB:
        mut, desc = fn(base)
        if mut == base:
            print("  ⚠ %-24s 注入未生效(锚点缺失), 本条无效" % name)
            leaked += 1
            continue
        if ci58.scope_check(mut):
            caught += 1
            print("  ✅ %-24s 拦下 (%s)" % (name, desc))
        else:
            leaked += 1
            print("  ❌ %-24s 漏过 (%s) ⇒ 这条检查拦不住任何东西" % (name, desc))

    print("scope 自证: %d 拦下, %d 漏过" % (caught, leaked))
    return 0 if leaked == 0 else 1


if __name__ == '__main__':
    sys.exit(main())
