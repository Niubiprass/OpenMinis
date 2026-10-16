# 160648 宿主高度收敛与深度思考折叠

候选源码修复，尚未证明真机通过。

## 对比160646→160647

`1ef28f5` 新增 rendered-height 发布；每次 installRoot 都抹去 publishedRenderSample，且 changed 直接比较含 revision/generation 的整个 sample。同一内容仅重装 root，即使真实高度未变，也再次清布局高度缓存。这是源码可确认的重复失效路径。

真机160647短syslog观察到同一行反复 `INVALIDATE idx=145 delta=132 est=200 → pref=68 cached=false`，以及ReflowGap 24/s。日志支持存在不收敛；有限时窗与录像尚不足将全部跳动唯一归因到此函数。

## 窄修复

- 同item同宽重装root保留已发布几何；revision/generation仍拒绝旧回调。
- 发布按identity、宽、高和0.5pt阈值去重，修正同高度不断清缓存的链。
- 模型展开/折叠作为独立形状事件，绕过历史浏览3秒内容节流；主队列幂等合并。
- 新shape要求新context自然高度；同item跨root保留收缩失效债，跨identity清理。
- 宿主几何更新通过coordinator单次锚点事务，避免和layout同时补偿。拖动期间延后到settle消费。
- 不修改已正常的“Minis正在思考…”等待提示，不撤销a091b0c文字淡入/属性前缀修复。

## 回归与边界

`test_host_shrink_release.py`：6项，本地5通过、真实Swift1项因无Swift跳过。CI要求V64R_REQUIRE_SWIFT=1失败闭锁；提取生产state、几何去重、apply/shape生命周期函数用Foundation替身执行。覆盖200次同高度revision、真实尺寸/identity/width变化、shape债、会话清理和锚点所有权。

现有host12、scroll12、render7等源码/模型回归通过。不是UIKit渲染测试，编译与真机滚动/折叠验收仍必须独立进行。
