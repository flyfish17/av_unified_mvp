# Jetson 长线交接 — 视觉深思层（形态 B 驱动）

> 接手对象：另一个 Claude Code 会话（全授权 /loop 模式）
> 主线对话：2026-05-13 15:50 CST
> 与并行会话：3588 烧机长测（`OVERNIGHT_HANDOFF_3588_20260514.md`）独立运行，互不冲突
> 任务总耗时：**6-8 小时**（硬上限 10h）；中途随时可被 STOP / 用户 ctrl+C 终止

## 战略定位（5/13 user 拍板）

Jetson Orin Nano 不再做"深思 LLM 层"（5/13 POC 已证 qwen3:8b OOM 不可行，1.7b 解题 0/4），转为 **形态 B "视觉深思层"** —— 接 3588 video_processor 的检测事件 + 拉 mjpeg 帧，用 qwen2.5vl:3b 多模态 VLM 跑场景分析，输出富语义事件到 av/video/scene_analysis。

这是 §1.5 形态 B "视频分析+分布式差异点输出" 的实际驱动力 —— 单机推理盒做不到的：
1. **多视角对比**：同区域多 camera 输出 diff
2. **时序差异**：前后帧场景变化
3. **行为模式识别**：YOLO bbox 之上的"在做什么"语义

## Mission（一句话）

**Jetson 跑 qwen2.5vl:3b 当"看着画面思考"的视觉深思层** —— 订阅 3588 video_processor 检测事件 + 拉 mjpeg snapshot，喂 VLM 输出场景语义到 av/video/scene_analysis，dashboard 新面板实时显示。

**直接产出**：明早 `OVERNIGHT_REPORT_JETSON_VLM_20260514.md`，告诉用户：
- VLM 通路成立 / 不成立
- qwen2.5vl:3b 在 Orin Nano 真实推理延迟 / RAM 峰值 / 失败模式
- 1-3 路 camera 持续分析的 sustainable 频率（避免 OOM 或抢 audio_processor 资源）
- 跟 5/13 形态 B "差异点"概念的差距 + 下一步

## 设备 + 网络

| 项 | 值 |
|---|---|
| Jetson SSH | `SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51` |
| 3588 SSH（只读监控）| `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6` |
| Mac mini SSH（只读监控）| `SSHPASS=123456 sshpass -e ssh openclawminiold@192.168.5.193` |
| MQTT broker（共用）| `192.168.5.6:1883` |
| 3588 mjpeg | `http://192.168.5.6:5051/snapshot/<camera>?mode=raw` |
| 3588 video sources | USB罗技C920 / 财务室 / 办公室 / test（5/13 user 加的 IPC） |
| Mac 当前 IP | `192.168.5.5`（en1） |
| Jetson 时钟 | CST 北京时间 |

## 先读这些（5 分钟接手）

| 文档 | 何用 |
|---|---|
| 本文 § Mission / 约束 / Milestone | 做什么 |
| `DEVELOPMENT_PLAN.md` §1.5 形态 B 段 | 战略澄清 — "差异点" 是核心护城河 |
| `OVERNIGHT_REPORT_20260514.md`（昨夜 Jetson POC） | Jetson 已知行为 + 5/13 escalate POC 结论 |
| `OVERNIGHT_REPORT_MACMINI_20260514.md` | Mac mini 深思层迁移结论（不冲突，但 broker 共用） |
| `main_jetson.py`（Mac 仓库根，也在 Jetson 副本里） | Jetson minimal supervisor 样板 |
| `modules/video_processor/main.py` | video_processor 发的 av/video/detect payload 结构 |

## 当前活进程（不动）

| 设备 | PID | 进程 | 说明 |
|---|---|---|---|
| Jetson | 604725 | audio_processor (CUDA ASR) | 5/12 起 30h+ 长跑样本，**绝对不动** |
| Jetson | 620547 | main_jetson.py supervisor | 5/13 晚启的旁路 |
| Jetson | 620550-552 | system_info / network_info / control_dispatcher | supervisor 子进程 |
| Jetson | 623671 | llm_engine（escalate_receiver=false） | 5/13 晚 escalate 关掉后孤独跑，**可保留或停**（保留无开销，停可让出客户端 connection） |
| 3588 | 1162126 | main.py supervisor + 8 模块 + Node-RED | 烧机会话在用，**不动** |
| Mac mini | 5/12 演示 supervisor + escalate receiver | 不动 |

## 硬约束（不可越）

1. **不重启** Jetson audio_processor PID 604725（5/12 起 30h+ 长跑稳定性样本）
2. **不动 3588 任何代码 / 进程** — 它在被 3588 烧机会话观测中
3. **不动 Mac mini 任何代码 / 进程** — 它的 escalate llm_engine 是独立长测样本
4. **不 push** 任何 commit 到 origin（早晨 review）
5. **不动** main.py / engine.py / llm_engine 等已有模块（你的工作在新模块 `modules/scene_analyzer/`）
6. STOP sentinel：`/tmp/STOP_JETSON_VLM`（Mac 本机）
7. 总耗时 > 10h 硬终止

## 硬终止触发器（任一即 abort + 写报告退出）

| 触发器 | 检测 |
|---|---|
| `/tmp/STOP_JETSON_VLM` 存在 | 每 milestone 间检查 |
| Jetson mem_avail < 300 MB（持续 30s）| **优先级 #1** — Orin Nano 7.4G 易爆 |
| Jetson audio_processor PID 604725 死 | 影响长跑样本，立即报告 + 退出 |
| 3588 任意 guard 进程死 | 跨设备影响，退出 |
| qwen2.5vl:3b ollama crash 连续 3 次 | VLM 不可用 |
| 总耗时 > 10h | 硬上限 |

触发后：写 partial report + 退出。**不重启任何 guard 进程**"修复"。

## Milestone 序列（self-paced）

每个 milestone 完成后**追加进度** + 检查 STOP / 时间预算 + 决定下一个。

### M1 — VLM 单帧通路 smoke（≤ 45 min）

验证 ollama qwen2.5vl:3b 在 Jetson 上能吃图像 + 返回文本。

```bash
# Jetson 拉 1 帧 from 3588 mjpeg
SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51 '
curl -s "http://192.168.5.6:5051/snapshot/USB罗技C920?mode=raw" -o /tmp/frame.jpg
ls -la /tmp/frame.jpg
file /tmp/frame.jpg
'

# 喂 ollama vision API
SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51 '
IMG_B64=$(base64 -w0 /tmp/frame.jpg)
curl -s http://127.0.0.1:11434/api/generate -d "{
  \"model\": \"qwen2.5vl:3b\",
  \"prompt\": \"用一句话描述这张图里看到了什么，重点是人/物/动作\",
  \"images\": [\"$IMG_B64\"],
  \"stream\": false
}" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get(\"response\", d))" | head -5
'
```

记录：
- 推理时延（首次冷启动 + 后续）
- RAM 占用（推理期间 free / wired）
- 输出质量（描述准确度）

成功条件：拿到非空文本，描述跟图像匹配。

⚠️ 如果 qwen2.5vl:3b 首次加载失败或 OOM → 试 `llava-phi3:3.8b` 或 `minicpm-v:8b`（要看 RAM 余量）作 fallback。VLM 选型本身是产出之一。

### M2 — `modules/scene_analyzer/` 新模块（≤ 90 min）

仓库内新模块，**只在 Jetson 副本启用**（main.py MANAGED_MODULES 不加它，main_jetson.py 加）。

```
modules/scene_analyzer/
  __init__.py
  main.py        # SceneAnalyzer(BaseModule) — 订 av/video/detect + 拉 mjpeg + VLM 推理
```

设计契约：
- 订阅 `av/video/detect`（来自 3588 video_processor）
- 节流策略：每个 camera 最多 N 秒一次推理（默认 N=10），避免 VLM 跟不上 detect 频率
- 拉 snapshot：`GET http://<3588_mjpeg_host>:5051/snapshot/<camera>?mode=raw`
- VLM call：本机 ollama qwen2.5vl:3b
- 发 av/video/scene_analysis：
  ```
  {
    "camera": "USB罗技C920",
    "time": ts,
    "detection_classes": ["person", ...],   // 来自原 detect 事件
    "scene": "...",                          // VLM 输出文本
    "vlm_model": "qwen2.5vl:3b",
    "vlm_latency_ms": N,
    "source_host": "jetson"
  }
  ```
- 声明 stream → dashboard 自动出 "视觉深思" 面板（kind=kv_table）

实现要点：
- 用 `requests` 调 ollama；图像 base64 在内存传，不写磁盘
- 节流用 `{camera: last_inference_ts}` dict
- VLM 调用放 ThreadPoolExecutor 避免阻塞 MQTT 回调
- 异常 / 超时 / OOM 都不抛，log warning + skip 这一帧

### M3 — Jetson 部署 + 接入主链路（≤ 30 min）

```bash
# rsync 仓库副本到 Jetson（含新 scene_analyzer）
# Mac:
SSHPASS=yahboom sshpass -e rsync -avz --exclude='.git' --exclude='__pycache__' \
  modules/scene_analyzer/ \
  jetson@192.168.5.51:/home/jetson/av_unified_mvp_jetson/modules/scene_analyzer/

# Jetson 改 main_jetson.py 加 scene_analyzer，重启 supervisor
SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51 '
sed -i ".bak" "s|modules.control_dispatcher.main|&\\n    \\\"modules.scene_analyzer.main\\\",|" main_jetson.py
pkill -f main_jetson.py
sleep 3
nohup python3 main_jetson.py > /tmp/jetson_supervisor.log 2>&1 &
sleep 8
pgrep -af "scene_analyzer" | grep -v grep
'
```

成功条件：3588 broker 看 `av/system/discovery/scene_analyzer` retain → 上线公告 + endpoints。

### M4 — e2e 验证（≤ 60 min）

让 3588 USB罗技C920 拍到一些场景（user 站到镜头前 / 桌面物品 / 走廊有人通过）：
- video_processor 触发 av/video/detect
- scene_analyzer 节流后拉 snapshot + VLM
- av/video/scene_analysis 发出
- 时延 / 质量 / 失败率记录

跑 20 min 真实场景采样。表格出：

| ts | camera | detect classes | VLM scene | latency_ms |
|---|---|---|---|---|

### M5 — dashboard 渲染（≤ 60 min）

加 SSE channel 处理 + 新面板 "视觉深思 · 场景分析"：

- 选 1：复用 kv_table renderer，scene_analyzer streams 声明 `kind: kv_table` + `channel: scene_analysis`
- 选 2：写专门的 scene_analysis.js renderer，左侧显示 snapshot + 右侧 VLM 文本

推荐选 1（最小改动），如果时间允许做选 2 加分。

改 dashboard.js：channel handler 加 `else if (channel === "scene_analysis")` → ticker forward / overview panel 推送。

文件改动写到 Jetson 副本和 Mac 副本（**不 push**）。

### M6 — 跨帧差异点（可选，≤ 90 min）

形态 B 真正护城河是 "diff"。最简：同 camera 前后两次 VLM 输出做对比（也用 VLM）：
- prompt: "前一帧场景：A；当前场景：B。两者关键变化用一句话总结，无变化输出 NO_CHANGE"
- 发新 topic `av/video/scene_diff` 含 changes 字段

跨视角差异（多 camera 同区域）留作 M7 范畴。

### M7 — 报告（≤ 30 min）

写 `OVERNIGHT_REPORT_JETSON_VLM_20260514.md`：
- VLM 通路成立性
- qwen2.5vl:3b on Orin Nano 真实数据：加载 / 首次推理 / 稳态推理 / RAM 峰值
- e2e 时延（detect → snapshot 拉取 → VLM → publish）
- 1-3 路 camera 持续分析的 sustainable 频率（节流间隔多少安全）
- 跟 §1.5 形态 B "差异点" 的差距 + 下一步建议
- M6 跨帧 diff 实测（如做了）
- 异常 / OOM / 失败模式

不 commit、不 push。早上 user review。

## /loop 启动姿势

```
/loop 读 OVERNIGHT_HANDOFF_JETSON_VLM_20260514.md 然后开始 milestone 1
```

`ScheduleWakeup` 节奏：
- VLM 测试期间 `delaySeconds=600`（10 min）
- 长 e2e 采样 `delaySeconds=1800`（30 min）
- M6 多模态对比 `delaySeconds=1200`（20 min）

## 启动检查清单（first iteration 跑）

1. `cat OVERNIGHT_HANDOFF_JETSON_VLM_20260514.md` — 完整读
2. `cat OVERNIGHT_REPORT_20260514.md` — 5/13 Jetson 深思层 POC 结论（避免重蹈）
3. `cat OVERNIGHT_REPORT_MACMINI_20260514.md` — Mac mini 现状（不能影响）
4. Jetson 健康：`SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51 'free -h | head -3; pgrep -af "audio_processor|main_jetson" | grep -v grep'`
5. `test -f /tmp/STOP_JETSON_VLM && echo abort || echo go`
6. 进入 M1。

## 紧急 abort

```bash
# Mac 本机
touch /tmp/STOP_JETSON_VLM
```

下次 iteration 检测到立即收尾。

## 联系（如果新会话遇到困惑要问用户）

- **不要**自作主张超出本 mission：不改 audio_processor / engine.py / video_processor / Mac mini 进程
- **可以**自主：写 scene_analyzer 新模块、改 main_jetson.py、改 Jetson 副本的 dashboard.js（不 push）、调 ollama VLM
- 遇到 OOM：**立即停 VLM 推理**，等 30s 看 RAM 恢复，再降级模型（3b → 1.7b 文本 or 跳过当帧）
- 遇到 audio_processor PID 604725 死：**不重启**，写报告 + 退出（这是长跑样本，重启就丢了）
- 遇到 video_processor 在 3588 死：写报告 + 等 3588 supervisor 自己拉，不远程干预

## 输出风格

报告**简短 + 数据驱动**：每 milestone 一段 + 一张表。结论 1-2 句话点透。failure mode 名字具体（"qwen2.5vl:3b 在含 4 人场景下 RAM peak 6.2G 触发 swap 200MB"，不是"VLM 不稳定"）。

## 推荐节奏

- T+0-45 min：M1 VLM 通路
- T+45min-2h15：M2 scene_analyzer + M3 部署
- T+2h15-3h15：M4 e2e 验证（含 20 min 真实采样）
- T+3h15-4h15：M5 dashboard 渲染
- T+4h15-5h45：M6 差异点（可选）
- T+5h45-6h15：M7 报告

6h 内做完 M1-M5 = 完成基础线。M6-M7 是加分。
