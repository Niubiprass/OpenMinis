# 160644 真机回归：未通过

2026-10-15 18:11–18:17，用户自行安装后授权操作。设备get_app_info核对160644，PID51447。

独立会话ADA98F51-EC00-4A6A-B04D-AABF94B05E31，模型GPT6.1 Sol，生成40段中文，同时排队Q160644。持久化回复2804字符，含40段和END160644；排队回答正常完成。UI最终只到第22段（rect45pt），后面紧接排队用户；退出重进仍不能恢复。全文accessibility容器高2007pt，外层宿主日志2058pt。9轮累计上下滑动，未发现新Minis crash，PID未变。思考等待标签出现过，但当前模型thinking关闭，不能认定已验证真实reasoning内容。

证据目录workspace/test-160644/，包括persisted.json、live-1/live-2/live-bottom、final-before、reenter-settled、stress-end、crash-after、layout-log、freeze-log。

日志18:13:24–30持续V64R-TEXT-BATCH refreshed=1 processing=true，同时V64-CONVERGE hold est2058 recomputed2058 tk2007；说明新增刷新信号确实到达但高度未增长，不能再以信号缺失作为唯一根因。2007是否硬上限尚未证明。布局子代理64E1DAC1正在检查源码。未自动安装/注销/重启、未改模型或全局设置。已返回原工作会话72422CEC。

搜索闪退与自动压缩补丁未包含在手机160644，不能记为已验证。
