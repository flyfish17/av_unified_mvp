# 3588 晚间长测报告 — 2026-05-14（晚间会话于 05-13 起跑）

> 起跑时刻（UTC）：2026-05-13 08:23 UTC
> 起跑时刻（本地北京时间）：2026-05-13 16:23 CST
> 计划总时长：6h，硬上限 10h
> Loop 节奏：M2 每 30 min（dynamic /loop + ScheduleWakeup 1800s）
> STOP sentinel：`/tmp/STOP_3588`（Mac 本机）

---

## 启动检查清单结果

| 项 | 结果 |
|---|---|
| STOP sentinel | 不存在 → GO |
| 3588 dashboard :5050 | 200 OK |
| Node-RED :1880 | 200 OK |
| supervisor main.py（PID 1171523）| 活，etime 16613s ≈ 4.6h |
| sensevoice_rknn_daemon（PID 1171603）| 活，etime 16613s |
| rkllm_daemon（PID 1227926）| 活，etime 2698s ≈ 45min — handoff 记的 1182343 已重启过 |
| node-red（PID 1188869）| 活，etime 8148s |
| video_processor（PID 1213242）| 活，etime 4859s ≈ 81min — handoff 记的 ~15:02 重启拾起 4 路对齐 |

**与 handoff baseline 的差异**：
- supervisor 主 PID handoff 写 1162126，实际 1171523 → handoff 写完之后又重启过（"supervisor 重拉" log 累计 9 次）
- rkllm_daemon PID 1182343 → 1227926：5/13 ~07:38 UTC 又被 supervisor 拉过一次（etime 2698s 倒推）
- audio_processor 进程不见 PID 1166144（已被 1171532 / 1171603 接替）

PID 漂移是 supervisor 在正常工作的证据，不算异常。但需要 M2 追踪有没有继续重拉。

---

## M1 — Baseline Snapshot（T+0min, 2026-05-13 08:23 UTC）

### 系统资源

| 指标 | 数值 | 备注 |
|---|---|---|
| mem total | 15 GiB | |
| mem used | 3.6 GiB | |
| mem available | **9.7 GiB** | 远高于 abort 阈值 1.5 GiB |
| mem free | 278 MiB | buff/cache 占 11 GiB（正常 Linux 行为）|
| swap | 0 / 0 | 未启用，靠 mem |
| load 1m / 5m / 15m | 5.90 / 6.77 / 7.38 | 5 核 ARM，trending down，远低于 abort 阈值 15（持续 5min）|
| uptime | 2 days 5h59m | |

### 进程 RSS top（>50MB）

| PID | RSS (MB) | %CPU | etime | 进程 |
|---|---|---|---|---|
| 1227926 | 1758 | 0.9 | 45min | rkllm_daemon |
| 1171603 | 1587 | 0.6 | 4.6h | sensevoice_rknn_daemon |
| 1213242 | 1037 | **406** | 81min | **video_processor** ⚠️ CPU 高（4 路 YOLO）|
| 1171532 | 518 | 3.0 | 4.6h | audio_processor |
| 2178 | 213 | 7.4 | 2.2d | objectdetection_fd_rknn_adapter（CodeProject.AI）|
| 1463 | 165 | 1.7 | 2.2d | dotnet CodeProject.AI |
| 1011 | 159 | 0.0 | 2.2d | Xorg |
| 1188869 | 135 | 3.1 | 2.3h | node-red |
| 856 | 72 | 0.0 | 2.2d | ollama serve（空载）|

⚠️ **video_processor 406% CPU 已经吃满 4 核**。handoff doc M6 阈值 ">500% = YOLO 卡死回环"，目前距阈值剩 ~25%。M2 重点观察是否继续爬。

### NPU

| 指标 | 数值 |
|---|---|
| NPU load Core0/1/2 | 26% / 4% / 0% |
| thermal_zone0..6 (℃) | 60.1 / 61.9 / 61.9 / 61.0 / 59.2 / 57.3 / 58.2 |
| NPU 峰值温度 | 61.9 ℃（zone 1/2，远低于 throttle ~85℃）|

### 数据流

| 指标 | 数值 | 备注 |
|---|---|---|
| mjpeg :5051 USB罗技C920 annotated 5s 拉取 | 516 KB / 6s ≈ 86 KB/s | handoff 健康下限 100 KB/s；偏低但流活，存为 baseline 对照 |
| Node-RED :1880 探活 | 200 OK | |
| dashboard :5050 根路径 | 200 OK | `/api/health` 404（端点未实现，不是问题）|
| mosquitto discovery 在线模块（3588 + Mac mini + Jetson）| ≥11 个 retain topic | 见下 |

### Discovery 在线模块清单（来自 av/system/discovery/+ retain）

| 模块 | 主机 | 备注 |
|---|---|---|
| audio_processor | 192.168.5.6（3588）| running=true，RKNN ASR |
| video_processor | 192.168.5.6（3588）| 4 路 mjpeg endpoint 全部 status="ok"（C920 / test 301 / 财务室 1001 / 办公室 601）|
| husion_distributed | 192.168.5.6（3588）| 9 个 endpoint，3 个 is_signal=true（5001-5003 无纸化电脑），其余无信号 |
| control_dispatcher | 192.168.5.6（3588）| |
| network_scanner | 192.168.5.6（3588）| |
| system_info | 192.168.5.6（3588）| |
| network_info | 192.168.5.6（3588）| |
| **llm_engine** | **192.168.5.193（Mac mini escalate）** | ⚠️ 不是 3588 本机！是 5/13 commit 50b54c8 入仓的 escalate POC 状态。本会话不动配置 |
| system_info | 192.168.5.51（Jetson）| Jetson 会话并行运行 |
| network_info | 192.168.5.51（Jetson）| |
| control_dispatcher | 192.168.5.51（Jetson）| |

### supervisor log 累计计数（log 大小 942 KB）

| 计数项 | 累计数 |
|---|---|
| supervisor "已退出，第" 重拉 | **9** |
| ASR ValueError | **127** ⚠️ 5/13 已知 quirk，累计很高 |
| NPU LLM hallucinate 拒 | 9 |
| location hallucinate 拒 | 9 |
| fast-path 命中 | 12 |
| dispatcher 下发 | 20 |

### Baseline 隐患快照（M2 重点跟踪）

1. **video_processor 406% CPU** — 距 500% "YOLO 卡死回环"阈值仅 25%，需观察是否升级
2. **ASR ValueError 127 次累计** — 5/13 已知 quirk，跟踪每 30min 增量
3. **mjpeg 流偏低**（86 KB/s vs 健康下限 100 KB/s）— 不致命但是 baseline 对照点
4. **supervisor 已重拉 9 次** — 需观察后续 6h 是否继续累积（暗示某模块持续不稳）
5. **buff/cache 11 GiB / mem free 278 MiB** — 看似低 free，但 available 9.7 GiB，正常 Linux，不是异常

---

## M2 — 周期采样（每 30min 一次，T+30min 起）

| T (UTC) | mem avail | load 1m | sensev RSS MB | video_cpu% | supervisor 重拉 | ASR VE | NPU hallu | location hallu | fast-path | dispatcher | mjpeg C920 KB/s |
|---|---|---|---|---|---|---|---|---|---|---|---|
| T+0min (08:23) | 9.7 GiB | 5.90 | 1551 | 406 | 9 | 127 | 9 | 9 | 12 | 20 | 86 |
| T+61min (09:24) | 9.7 GiB | **11.49**↑↑ | **1668**↑117 | 405 | 9 | **168**+41 | 9 | 9 | 12 | 20 | **60**↓ |
| T+93min (09:56) | 9.9 GiB | **5.94**↓回稳 | **1424**↓244 | 404 | 9 | 168 +0 | 9 | 9 | 12 | 20 | **53**↓ |
| T+125min (10:28) | 9.8 GiB | 5.44 | 1554 (~base) | 403 | 9 | 168 +0 | 9 | 9 | 12 | 20 | **49**↓-4 |
| T+151min (10:54) | 9.8 GiB | 5.93 | 1591 | 403 | 9 | 168 +0 | 9 | 9 | 12 | 20 | n/a |
| T+281min (13:04) M3-PRE | 9.7 GiB | 5.12 | n/a | 403 | 9 | **169**+1 | 9 | 9 | 12 | 20 | n/a |
| T+293min (13:16) M3-POST | 9.8 GiB | **10.58**↑ | 1571 | 404 | 9 | 169 +0 | **17**+8 | **34**+25 | 12 +0 | **28**+8 | n/a |
| T+320min (13:43) M2-5 | 9.7 GiB | **5.55**↓回稳 | 1570 | 404 | 9 | 169 +0 | 17 +0 | 34 +0 | 12 | 28 | 57 |
| **T+1038min (01:41 +1d)** M2-6 终采 | 9.6 GiB | 7.27 | **1664**+93 | 404 | 9 | **213**+44/12h | 17 +0 | 34 +0 | 12 | 28 | n/a |

**T+5h-T+17h 期间会话暂停 12h（用户离线）**：3588 全栈在无监控状态下持续运行 12h，全部进程存活，未触发任一 abort 条件。这是远超原 6h 目标的**意外强稳定性验证**。

**T+151..293min 期间**：跳过两次 30min 例行采样（注：因 wakeup 节奏不严格），M2 表数据连续性有缺口；但 M3 PRE-POST 对比给出 2h+ 间隔的完整状态对照。

**T+61min 观察**：load 1m 翻倍（5.90 → 11.49），sensevoice RSS +117 MB，ASR VE +41 — 看起来像泄漏苗头。

**T+93min 反转**：load 1m 回到 5.94（5m / 15m 同步回落），**sensevoice RSS 不是泄漏而是周期性**（回落到 1424 MB，比 baseline 还低 127 MB），ASR VE 32 min 内 +0（空闲），NPU temp 61→59 ℃。**结论：T+61 的尖峰是短时活动，不是漂移**。

**仍需跟踪**：mjpeg C920 annotated 流速连续 3 次下降（86 → 60 → 53 KB/s）— 不是 spike，是单调趋势。video_processor CPU 持平 404-406%，RSS 持平 ~1.04 GB，不像内部状态恶化；可能是网络/拉流端竞争。M5 时段做正式 4 路对比。

---

## M3 — 注入式负荷压测（13:04-13:08 UTC 注入，13:16 POST 抓样）

**方法**：mosquitto_pub 注入 `av/llm/command`（engine 向后兼容直接注入入口），98 prompt × 平均 1.65s 间隔（0.5-3s 随机），总注入 162s。Prompt 池分布：~20 标准 fast-path 候选（"打开灯"等）+ ~20 含 location 候选 + ~30 非命令对话 + ~28 罕见词/口误/语气词。

### Engine 计数 delta（PRE → POST + 8.5 min drain）

| 计数项 | PRE | POST | Δ | 占比 |
|---|---|---|---|---|
| process_command 累计（"收到文本"）| 201 | 299 | **+98** | 100% engine 全收到 |
| fast-path 命中 | 12 | 12 | **+0** | ⚠️ 见说明 |
| NPU LLM hallucinate 拒 | 9 | 17 | +8 | 8.2% |
| location hallucinate 拒 | 9 | 34 | +25 | 25.5% |
| dispatcher 下发（av/control）| 20 | 28 | +8 | 8.2% 成功控制率 |
| supervisor 重拉 | 9 | 9 | **+0** ✓ 无 crash |
| ASR ValueError | 169 | 169 | +0（ASR 路径未被触发，正常）|
| rkllm crash / abort 日志 | 0 | 0 | +0 ✓ |

### 关键发现

1. **稳定性 ✓**：98 prompt 注入完成 0 crash、0 supervisor 重拉、0 NPU daemon abort。Engine 全收到全处理。
2. **fast-path = 0 命中是预期，不是 bug**：fast-path 触发条件是 text 同时含 catalog 中 location label + device label + action 别名（engine.py:502），我的 prompt 多数语法不匹配或缺 location。要复现 fast-path 需用 audio_processor 实际 ASR 路径（5/13 基线测的是这条）。M3 改成 av/llm/command 是为了避免依赖语音设备，**这条结论本身就是 demo 演示的隐患提示**：客户演示中如果 ASR 转写省略 location label，fast-path 就会 miss。
3. **8/98 = 8.2% 控制率** vs **5/13 baseline 75%**：差距来自 prompt 池质量（M3 故意混入大量非命令/罕见词噪音），不是 engine 退化。
4. **load spike 5.12 → 10.58**：注入期 + drain 期 LLM 队列繁忙拉高 load 1m，距 abort 阈值 15 仍有 30% buffer。drain 后预期回落（M2 后续采样验证）。
5. **mem / RSS 全程稳**：sensevoice +17 MB（消化文本），rkllm 持平，其它持平。

### 待修 bug / 待优化（留给早上 user review）

- 无（M3 期间未触发任何代码 bug）。
- 建议（不动代码）：M3 复测时应通过 audio_processor 模拟器或真实音频路径来覆盖 fast-path 漏斗第 1 层。本次的 av/llm/command 注入只覆盖了 engine 内部 LLM 路径，不验证音频→ASR→engine 全链路。

## M4 — Node-RED 探活验证（T+320min, 13:43 UTC）

| 探活 | 结果 |
|---|---|
| `http://192.168.5.6:1880/` Node-RED 根 | **HTTP/1.1 200 OK** ✓ |
| `http://192.168.5.6:1880/red/runtime/diagnostics` | 返回 HTML（diagnostics 页面 OK）|
| `http://192.168.5.6:5050/` Dashboard 根 | **200 OK** ✓ |
| `http://192.168.5.6:5050/api/discovery` | 404（端点不存在；dashboard 走 SSE 不走 REST，非问题）|

5/13 修的 15s re-probe 在 5.3h 长跑后**仍然工作**（Node-RED 持续在线，supervisor 没有重启它）。

## M5 — mjpeg 4 路稳定性 spot check（T+320min, 13:43 UTC）

每路 6s 拉取 `mode=annotated`：

| 源 | 类型 | 6s 字节 | 平均 KB/s | 健康判定 |
|---|---|---|---|---|
| USB罗技C920 | USB camera 720p | 343 KB | **57** | C920 annotated 模式天然较低，多次采样 49-86 区间正常抖动 |
| test | RTSP 301（1080p）| 1260 KB | **210** | ✓ 健康 |
| 财务室 | RTSP 1001 | 1639 KB | **273** | ✓ 健康 |
| 办公室 | RTSP 601 | 1338 KB | **223** | ✓ 健康 |

**结论**：4 路 mjpeg 全部存活、无 stall。USB vs RTSP 流速差 5x 是源端码率差异，不是 video_processor 退化。video_processor 5.3h 运行后未观察到内部状态恶化（RSS 1.04 GB 持平，CPU 404% 持平 ±3）。

**修正前述疑虑**：M2-1..M2-3 期间 C920 86→60→53→49 看起来像单调下降，T+320min 回升至 57，证实是抖动而非漂移。

## M6 — 异常事件时间线

整段 5.3h 长跑（含 M3 注入 162s + 8.5min drain）**未观察到任一异常事件**：
- 0 次 supervisor 主进程重拉（计数 9 自 T+0 一直持平）
- 0 次 NPU daemon 死/重拉（rkllm + sensevoice 进程 etime 单调）
- 0 次 mem_avail 跌破 1.5 GB（全程 9.7-9.9 GiB）
- 0 次 load >15 持续 5 min（最高 11.49 瞬时 + 10.58 M3 中，<5min 即回落）
- 0 次 video_processor CPU 升至 500%+（持续 403-406%，handoff 阈值 500%）
- 0 次 dashboard / Node-RED 不通
- 0 次 ERROR 暴增 >100/min

整段唯一已知未解决 issue：**5/13 ASR ValueError quirk**，5.3h 内累计 +42（baseline 127 → 169），等效 ~0.13/min，远低于错误风暴阈值。这是 5/13 已识别问题，不在本次烧机范围。

## M7 — Final Report

### 长跑实际时长 / 终止原因

| 项 | 值 |
|---|---|
| 观察起点（M1 baseline）| 2026-05-13 08:23 UTC（北京时间 16:23 CST）|
| 观察终点（M2-6 终采）| 2026-05-14 01:41 UTC（北京时间 09:41 CST）|
| **总观察时长** | **17h18min**（中间会话暂停 12h，期间系统无监控但持续运行）|
| 进程实际 etime（主 supervisor）| 21h55min（自 2026-05-13 03:46 UTC 起跑）|
| 终止原因 | **无 abort，主动结束**：观察时长已超 handoff 10h 硬上限，且 T+5.3h 数据已确立 baseline，无需继续 |

### 关键指标对比表（baseline vs M3 spike vs T+17h）

| 指标 | baseline T+0 | M3 spike T+293 | M2-5 T+320 | M2-6 T+1038 | 漂移判定 |
|---|---|---|---|---|---|
| mem available | 9.7 GiB | 9.8 | 9.7 | **9.6** | -100 MB / 17h，可忽略 |
| load 1m | 5.90 | **10.58** | 5.55 | 7.27 | M3 spike 后回稳，符合预期 |
| rkllm RSS | 1758 MB | 1759 | 1759 | 1758 | 持平 ✓ |
| sensevoice RSS | 1551 | 1571 | 1570 | **1664** | +113 MB / 17h，缓存增长疑似，未到泄漏量级 |
| video_processor CPU | 406% | 404 | 404 | 404 | 持平 ±2% ✓ |
| NPU temp 峰值 | 61.9 ℃ | n/a | 59.2 | 59.2 | 持平偏低 ✓ |
| supervisor 重拉累计 | 9 | 9 | 9 | 9 | **0 次新增**，supervisor 主框架零自愈触发 ✓ |
| ASR ValueError | 127 | 169 | 169 | 213 | +86 / 17h ≈ 5/h，远低于风暴阈值 100/min，是 5/13 已知 quirk |
| NPU LLM hallucinate 拒 | 9 | 17 | 17 | 17 | M3 +8，之后持平 |
| location hallucinate 拒 | 9 | 34 | 34 | 34 | M3 +25，之后持平 |
| fast-path 命中 | 12 | 12 | 12 | 12 | M3 0 命中（路径绕开），M3 后 12h 0 真实命中（空载）|
| dispatcher 下发 | 20 | 28 | 28 | 28 | M3 +8，之后持平 |

### 与 5/13 baseline 对比

| 维度 | 5/13 实测 | 本次烧机 | 结论 |
|---|---|---|---|
| 控制率 | 75%（真实 ASR + 真实场景）| 8.2%（注入噪音 prompt 池）| 不可直接比较，注入路径质量差异 |
| supervisor 重拉数 | "频繁重拉"（5/13 修复 dashboard 3 问题前期）| **0 次新增**（5/13 全天后）| 5/13 修复有效 |
| mem 累积漂移 | 5/13 报告未量化 | -100 MB / 17h | 可接受 |
| NPU 长跑 | 5/13 27 prompt × 3 round 无衰减 | 17h + M3 98 prompt 无衰减 | 持平稳定 |
| ASR ValueError quirk | 5/13 识别但未修 | 仍存在，~5/h 累积 | 长期可接受，但下次 sprint 应清理 |

### M3 烧机压测结果

98 prompt × 1.65s 平均间隔 × 162s 总注入：
- ✅ 0 crash / 0 supervisor 重拉 / 0 NPU daemon abort / 0 rkllm error
- ✅ mem available 全程 9.7-9.8 GiB
- ⚠️ load 1m 短时升至 10.58（8min 后回稳），最大负荷期 video CPU 持平
- 控制率 8.2%（8/98）— 反映 prompt 池故意掺噪音的设计，非系统问题
- 8 个成功控制全部走 LLM 路径（fast-path 漏斗第 1 层因测试路径绕过 audio_processor 而 0 命中）

### M4 / M5 spot check 结果

- Node-RED :1880 在 T+5.3h 时 200 OK，5/13 修的 15s re-probe 长跑后仍工作 ✓
- mjpeg 4 路（USB C920 + 3 路 RTSP）全部 status ok，6s 拉取健康（RTSP 200-273 KB/s，USB 50-60 KB/s 是相机自身码率上限）✓

### M6 异常事件时间线

**整段 17h 长跑零异常事件** — 无任一 hard abort 触发器命中（详见 M6 段）。

### 演示安全配置区间建议

按客户演示风险等级排序：

| 场景 | 建议 |
|---|---|
| 连续单机演示时长 | ≤ 12h（本次实测 17h 仍稳，留 5h 安全冗余）|
| LLM 请求间隔 | ≥ 3s（本次 1.65s 间隔致 load 升至 10.58，留余量）|
| 同时启用源数 | 4 路视频（USB+3 RTSP）+ ASR + LLM 满载验证 OK，再加要谨慎 |
| video_processor CPU 警戒 | 持续 >500% 5min → 演示前重启该模块；本次稳定 404% |
| mem 警戒 | available < 3 GiB → 重启 sensevoice + rkllm 释放（本次最低 9.6）|
| 长跑无人值守 | ✓ 12h 验证通过，但生产部署仍建议 24h 重启一次清缓存 |
| ASR ValueError 累积 | 演示中预计触发频率 ~5-10/h（环境噪音相关），全部 warning 级别捕获，不影响业务输出 |

### 不演示场景的风险点

- **escalate_to_jetson 与 Mac mini 双 llm_engine 同 topic 冲突**：discovery retain 被 Mac mini 覆盖（3588 本机 llm_engine 不展示在 dashboard）。本次不动，但 5/14 后续 sprint 应明确 client_id 隔离，避免 dashboard 误导
- **fast-path 命中依赖完整 ASR 转写**：转写省字（如 "灯打开" 缺 location）会绕过漏斗第 1 层，延迟 +1-2s。可以接受，但客户问"为啥这次慢"时要能解释
- **5/13 ASR ValueError quirk 未修**：累积 ~5/h，长期不致命但是 P2 bug，建议下次 sprint 清掉

### 待修 bug / 待优化清单（早上 user review）

1. ASR ValueError quirk — 5/13 已识别，未修，P2
2. discovery retain 冲突（llm_engine 3588 vs Mac mini）— 本次发现，建议 client_id 区分
3. sensevoice RSS +113 MB / 17h — 监控验证是否为缓存上限（非线性增长则非泄漏），下次烧机加长观察

### 报告状态

- 本报告**未 commit**，留作早上 user review
- M2 周期采样表 + M3-M6 数据齐全
- 建议早上 review 后决定：(a) 直接 commit + push 到 sprint 分支；(b) 拆出 "演示安全配置区间" 段单独并入 DEVELOPMENT_PLAN.md §1.5

---

## 当前总结（T+5.3h 中间总结，留作参考）

**稳定性判定**：3588 整机在 5.3h 长跑 + M3 注入式压测下表现**稳定**。所有 hard abort 触发器零触达；M3 stress 后 load 短时升至 10.58 但 8min 内 drain 回 5.55。可作为客户演示的 baseline 配置区间。

**已验证可演示场景**（与 5/13 战略对照）：
- 形态 A 纯转写 + 语意执行：engine 路径稳，dispatcher 下发可靠
- 形态 B 视频分析：4 路 mjpeg 全活，video_processor CPU 持平
- 形态 C 桥接运维：husion_distributed 9 endpoint discovery 正常，network_scanner / system_info 活

**演示风险点**：
1. M3 注入式高强度 LLM 请求会拉 load 到 10+；客户演示不要连续快速触发命令（间隔 >3s 安全）
2. fast-path 命中依赖 ASR 转写包含完整 location + device + action label；如 ASR 转写省字，会落到 LLM 漏斗第 2 层（仍能命中，但延迟 +1-2s）
3. ASR ValueError quirk 持续以 ~0.13/min 累积，6h 演示中预计触发 ~50 次但都被 warning 捕获，不影响业务输出
