# 3588 晚间长测交接 — 整机稳定性 + 演示场景烧机

> 接手对象：另一个 Claude Code 会话（独立于 Jetson 那个会话）
> 主线对话日期：2026-05-13（下午全栈 supervisor + 12 commits + 3 dashboard 小问题修复，详见 DEVELOPMENT_PLAN.md §6 5/13 段）
> 任务总耗时：**6-8 小时**长跑（硬上限 10h）。中途随时可被 STOP / 用户 ctrl+C 终止。

## Mission（一句话）

**3588 整机连续长跑烧机** — 把 5/13 全天搭好的全栈（8 模块 supervisor + Node-RED + 4 路视频 + NPU ASR + NPU LLM + 漏斗 4 层 + dispatcher）在真实负荷下连续跑 6 小时，**找出**：内存泄漏 / NPU 累积错误 / mjpeg 流卡死 / supervisor 重拉风暴 / dashboard SSE 断连 / 任何"演示中翻车"的隐患。

**直接产出**：明早一份 `OVERNIGHT_REPORT_3588_20260514.md`，告诉用户：
- 长跑实际通过了几小时（6h 全过 / 中断在哪个 milestone）
- 关键指标随时间漂移图：mem / load / NPU temp / mjpeg 帧率 / ASR final 频率 / LLM 错误率 / 进程重拉次数
- 发现的隐患清单（按严重度排）
- 演示稳定的"安全配置区间"建议

## 与 Jetson 那个会话不冲突

- Jetson 会话改 `~/av_unified_mvp_jetson/`（新 git clone 副本），不动 3588
- Jetson 会话可能改 3588 `engine.py` 加 escalate 触发条件（**默认关**），需要 `system_config.yaml` 显式打开才生效。本会话**不要打开** `escalate_to_jetson` 配置，让 5/13 漏斗 4 层独立验证
- 两个会话共用 MQTT broker（3588:1883），但订阅 topic 独立。互不干扰
- **触发器冲突避免**：本会话用 STOP sentinel `/tmp/STOP_3588`（不是 `/tmp/STOP_OVERNIGHT`，那个是 Jetson 会话用的）

## 先读这些（5 分钟接手）

| 文档 | 何用 |
|---|---|
| 本文 § Mission / 约束 / Milestone | 知道做什么 |
| `DEVELOPMENT_PLAN.md` §1.5 + §6 最新 5/13 段 | 5/13 全天战略 + 进展 |
| `OVERNIGHT_REPORT_20260513.md` | 昨夜 NPU LLM 探索基线数据（mem 1.75GB / 27 prompt × 3 round 无衰减） |
| `docs/deploy/3588-npu.md` § 11 | 全栈 supervisor 启动 SOP |

## 设备 + 网络

| 项 | 值 |
|---|---|
| 3588 SSH | `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6`（sudo NOPASSWD） |
| Mac 端报告写到 | `OVERNIGHT_REPORT_3588_20260514.md`（仓库根，**不 commit** 等早上 review） |
| 3588 主日志 | `/tmp/main_supervisor.log` |
| 3588 系统时钟 | **UTC**（不是北京时间） |

## 当前 3588 活进程（不动）

| PID | 进程 | 起始 |
|---|---|---|
| 1162126 | main.py supervisor (8 模块) | 5/13 ~03:00 |
| 1166144 | audio_processor (RKNN ASR) | 5/13 重启 |
| 1213242 | video_processor (4 路) | 5/13 ~15:02 重启拾起 4 路 |
| 1182343 | rkllm_daemon | 5/13 ~03:00 |
| 1188869 | node-red | 5/13 ~14:07 |

## 硬约束（不可越）

1. **不重启** 上面 5 个 PID，除非进程死了 / 内存爆。重启是采样观察的对象。
2. **不动代码**（任何 `.py` / `.js` / `.yaml`）除非修 bug，且修前先报告
3. **不 push** 任何 commit 到 origin
4. **不开启** `escalate_to_jetson`（让 Jetson 会话独立验证）
5. **不重新部署** ollama / NPU daemon / Node-RED flow
6. STOP sentinel：`/tmp/STOP_3588`（本会话用）
7. 总耗时 > 10h 硬终止

## 硬终止触发器（任一即 abort + 写报告退出）

| 触发器 | 检测 |
|---|---|
| `/tmp/STOP_3588` 存在 | 每个 milestone 间检查 |
| 3588 mem_avail < 1.5 GB | preconditions 监测 |
| 3588 load1m > 15（持续 5 分钟）| 5 核 ARM 过载 |
| supervisor 主 PID 1162126 死 | 影响演示框架 |
| NPU daemon (rkllm or sensevoice) 死 + 5 min 内 supervisor 没拉起 | 演示链路断 |
| dashboard :5050 不通 > 5 min | Flask 死 |
| 同一异常 log 刷屏 >100 条/分钟 | 错误风暴 |

触发后：写报告 + 退出。

## Milestone（self-paced，长跑为主）

每个 milestone 完成后**追加进度**到 `OVERNIGHT_REPORT_3588_20260514.md` + 检查 STOP / 时间 + 决定下一个。

### M1 — baseline snapshot（≤ 15 min）

T+0min：抓基线，所有指标存入报告：

```bash
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 '
echo "=== mem ===" && free -h | head -3
echo "=== load ===" && uptime
echo "=== 进程 top RSS ===" && ps -eo pid,rss,pcpu,etimes,cmd --sort=-rss | head -10
echo "=== NPU load ===" && cat /sys/kernel/debug/rknpu/load 2>/dev/null || echo "(需 sudo)"
echo "=== NPU temp ===" && cat /sys/class/thermal/thermal_zone*/temp 2>/dev/null | head -5
echo "=== mjpeg :5051 fps ===" && timeout 5 curl -s "http://127.0.0.1:5051/video_feed/USB罗技C920?mode=annotated" -o /dev/null -w "%{size_download} bytes / 5s\n"
echo "=== mosquitto retain ===" && mosquitto_sub -h 127.0.0.1 -t "av/system/discovery/+" -C 1 -W 2 -v 2>/dev/null | wc -l
echo "=== ollama list ===" && ollama list 2>/dev/null | head -5
'
```

成功条件：baseline 数据完整存到报告 M1 段。

### M2 — 周期监控（每 30 min 一次，6 小时共 12 次）

每 30 min 跑同 baseline 抓样：mem / load / 各进程 RSS / NPU temp / mjpeg fps（5s 抓）/ supervisor 重拉计数 / ASR ValueError 计数 / LLM hallucinate 计数 / dispatcher echo 计数。

```bash
# 抓 supervisor log 累积量
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 '
echo "=== T+${T}min ==="
free -h | grep Mem
uptime | tr -s " " | cut -d"," -f3-
echo "ASR ValueError:" $(grep -ac "ValueError: index can.t" /tmp/main_supervisor.log)
echo "NPU LLM hallucinate:" $(grep -ac "LLM hallucinate 拒绝" /tmp/main_supervisor.log)
echo "location hallucinate:" $(grep -ac "location hallucinate 拒绝" /tmp/main_supervisor.log)
echo "fast-path 命中:" $(grep -ac "⚡ fast-path 命中" /tmp/main_supervisor.log)
echo "dispatcher 下发:" $(grep -ac "➤ 下发" /tmp/main_supervisor.log)
echo "supervisor 重拉:" $(grep -ac "已退出，第" /tmp/main_supervisor.log)
'
```

**采样节奏**：30 min 内一次（用 ScheduleWakeup delaySeconds=1800）。期间无需阻塞 — 可以做 M3-M5 别的工作。

### M3 — 注入式负荷压测（≤ 90 min，T+1h-2h30 之间随时做）

模拟客户演示节奏的 **150 prompt 烧机**（30 个 fast-path + 30 NPU 命中 + 30 NPU 拒 + 30 非命令 + 30 罕见词组合，乱序穿插，间隔 0.5-3s 随机）。生成脚本到 `/tmp/burn_prompts.sh`，跑完记录：

- 总通过时间
- fast-path 命中率 / NPU 命中率 / 拒/拦截率
- dispatcher 落到 av/control 的总条数
- 期间最长 LLM 推理时延
- NPU daemon 是否中断（rkllm crash 触发率）

⚠️ 不要在已识别到的负荷高峰（M2 看 load>10）时压，避免误杀长跑数据。

### M4 — Node-RED 探活验证（≤ 15 min）

`http://127.0.0.1:1880` 探活 + dashboard 浏览器是否能从 LAN 拿到 iframe（用 curl HEAD 模拟，记 status code）。验证 5/13 修的 15s re-probe 是否在 supervisor 长时间运行后仍然工作。

### M5 — mjpeg 4 路稳定性 spot check（每 2h 一次）

各 source 的 `/video_feed/<name>?mode=annotated` 拉 30s 看：
- 收到字节数（健康每 30s ~3-5 MB）
- 连续性（没有 stall）
- 是否报 connection reset

T+2h、T+4h、T+6h 各做一次，对比退化情况。

### M6 — 异常处理（出现即触发）

观察到以下任一异常：
- mem_avail 减到 < 3 GB（30 min 内累计减 > 500 MB）→ 怀疑泄漏，dump `pmap -x <pid>` 各模块比对基线
- NPU daemon 死了 → 看 supervisor 是否拉起，记 down-time
- video_processor 357% CPU → 看是否升级到 500%+（YOLO 卡死回环）
- supervisor log 中 "Error" 暴增（>10/min）→ 截取上下文

写到报告"异常事件时间线"段。

### M7 — Final report（T+6h-8h 之间）

写 `OVERNIGHT_REPORT_3588_20260514.md`：

- 长跑实际跑了多久 / 终止原因
- 12 次周期采样表（M2 数据）：mem / load / 重拉 / 累积错误数
- M3 烧机压测结果 vs 5/13 baseline
- M4-M5 spot check 结果
- M6 异常事件时间线
- **"演示安全配置区间" 建议**：连续运行多久应主动重启 NPU daemon / supervisor / 视频源 enable 数；什么场景下要避免（如同时 4 路 RTSP + 4 路 husion FLV + 持续语音对话）
- 跟 5/13 baseline 的对比：哪些指标稳了，哪些漂了

不 commit、不 push。早上 user review。

## /loop 启动姿势

新会话第一条 prompt 建议：

```
/loop 读 OVERNIGHT_HANDOFF_3588_20260514.md 然后开始 3588 烧机 milestone 1
```

ScheduleWakeup 节奏：
- M2 周期采样：`delaySeconds=1800`（30 min）
- M5 mjpeg spot check：跟 M2 同节奏即可
- M3 烧机期间：完成后再回 30 min 节奏
- **不要 sleep < 300s**（5 min 内浪费 prompt 缓存窗口）

## 启动检查清单（first iteration 时跑）

1. `cat OVERNIGHT_HANDOFF_3588_20260514.md` — 完整读完本文
2. `cat DEVELOPMENT_PLAN.md | sed -n '/2026-05-13/,$p' | head -100` — 看 5/13 进度
3. `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 'pgrep -af "main\.py|sensevoice|rkllm|node-red" | grep -v grep'` — 5 个长跑进程健康
4. `test -f /tmp/STOP_3588 && echo abort || echo go` — STOP sentinel（注意是 Mac 本机的 /tmp，不是 3588）
5. `curl -sI -m 3 http://192.168.5.6:5050/ | head -1` — dashboard 可达
6. 进入 M1 baseline。

## 紧急 abort

用户随时：

```bash
# Mac 本机
touch /tmp/STOP_3588
```

Loop 下次 iteration 检测到立即收尾退出。

## 联系（如果新会话遇到困惑要问用户）

- **不要**自作主张超出本 mission：不改代码（包括 dashboard.js / engine.py / video_processor）、不 push、不 merge、不重启长跑进程"修复"问题
- **可以**自主：注入 mosquitto_pub / mosquitto_sub / curl 探活 / 抓日志 / `ps` `free` 等只读命令
- 遇到代码 bug 需要修：**写到报告"待修 bug"段，留给早上 user review**，不要当场 hot-patch
- 遇到不可恢复错误：写完 partial report 退出。**不要重启长跑进程来"修复"问题**

## 何时该提前结束（≠ abort）

- 6h 跑完 + 全程平稳 + 数据齐全 → 早结束 + 写 "稳定基线确立"报告
- 跑到 3h+ 已发现 critical 问题 + 收集到充分诊断数据 → 写报告早结束（不必继续浪费时间）
- 跑到 2h 还没发现任何问题 + 也没出过任何错 → 缩短到 4h 总长，剩下时间做 M3 烧机压测

## 输出风格

报告写得**简短 + 数据驱动**：每个 milestone 一段 + 一张表，不要写小作文。结论 1-2 句话点透。failure mode 名字明确（"5/13 ValueError quirk 加剧到 2/min" 而不是"ASR 不稳定"）。
