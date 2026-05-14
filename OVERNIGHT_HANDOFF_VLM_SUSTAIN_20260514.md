# 夜班长跑交接 · 视觉深思链路 sustain 8h + 参数调优

**日期**：2026-05-14 夜班
**前置 commit**：`6ecec51 fix(vision): 空 detect heartbeat`
**branch**：`sprint/liaohe-3588-night-poc-20260511`
**预计工时**：8 小时（傍晚启动 → 早 8 点 user 接手）
**全授权窗口**：以下指令复制到全授权 Claude 窗口直接跑。

---

## 任务背景

5/14 白天定位并修复"视觉深思无输出" — 根因是 `video_processor` 在 YOLO 无目标时静默不 publish，整条 `detect → keyframe_filter → scene_analyzer → openvocab_filter` 链路饿死。

修法已 commit `6ecec51`：
- `modules/video_processor/processor.py:240-252` — 无目标也按 `idle_detect_interval_s` (默认 **15s**) publish 空 detect
- `modules/keyframe_filter/main.py:115-138` — 空 detect 走 `first_detect_empty` / `idle_force_empty` 路径，按 `idle_seconds` (默认 **60s**) per-camera 节流

实测链路通了（Jetson VLM 出场景描述、yolov8-world 出 hits）但**留下一个硬伤**：

```
当前 4 摄像头 × 60s idle = 4 个 key_event / 分钟 = 4 个 VLM 请求 / 分钟
Jetson VLM 78s/次推理（qwen2.5vl:3b vision encoder fixed cost）
→ 单位时间需要 4 × 78 = 312s VLM 算力 / 60s 实际 = 5.2× 超载
→ 几分钟内 scene_analyzer 推理队列必然堆积；最终 OOM 或漏帧
```

这个不长跑看不出来。

## 任务目标

**主目标**：跑 8h sustain 验证视觉深思链路在 4 路摄像头满载下的实际稳定性，给出 `keyframe_filter idle_seconds` / `openvocab conf_threshold` 的**经数据验证的推荐值**。

**次目标**（不冲突就做）：
1. 实测 Jetson VLM 队列堆积 / 漏帧 / OOM 是否真发生
2. openvocab `person without hardhat` / `fire` / `smoke` / `falling` 误报率（confidence 分布）
3. 凌晨低噪时段做 1-2 次扫参（A/B/C/D），白天高噪时段做 5h sustain
4. 早晨产出 `OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md` 报告 + 在 `DEVELOPMENT_PLAN.md §6` 加一条进度日志

## 关键基础设施（不假设你知道）

| 资源 | 路径 / IP |
|---|---|
| 3588 SSH | `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6` |
| Jetson SSH | `nvidia@192.168.5.51`（密码未知；不需要 SSH，所有动作通过 MQTT 完成） |
| 3588 supervisor cwd | `/home/firefly/av_unified_mvp/` |
| 3588 venv（共享） | `/home/firefly/creator_ai_demo/venv/`（**只读，不动**） |
| supervisor log | `/tmp/main_supervisor.log` |
| MQTT broker | `127.0.0.1:1883` (3588 上的 mosquitto) |
| 关键 topics | `av/video/detect` `av/video/key_event` `av/video/scene_analysis` `av/video/openvocab` |
| Dashboard | `http://192.168.5.6:5050` |
| MJPEG snapshot | `http://192.168.5.6:5051/snapshot/<camera_name>?mode=raw` |
| 改动文件 | `modules/keyframe_filter/main.py` (DEFAULTS.idle_seconds) + `modules/video_processor/processor.py` (idle_detect_interval_s) + `modules/openvocab_filter/main.py` (conf_threshold) |

**rsync 陷阱**：往 3588 同步代码**必须**目标 `/home/firefly/av_unified_mvp/modules/`，不是 `/home/firefly/creator_ai_demo/modules/`（5/14 踩过这个坑，浪费 30 分钟）。

## 红线 / 绝对不动

1. **不杀 audio_processor / sensevoice daemon**：长跑稳定性样本，user 在收集
2. **不动 supervisor 主进程 main.py**（PID 在 `/tmp/main_supervisor.log` 启动行可见），可以杀子进程让 supervisor 自愈
3. **不删 venv** `/home/firefly/creator_ai_demo/venv/`
4. **不动 nodered_data**、husion 现场预编排
5. **不 push origin**（commit 在本地，user 早上 review 再 push）
6. **不 force push / rebase / 不修 main 分支**
7. **不动 :1880 Node-RED**（5/14 早重启过，flow 正在用）
8. **不动 :11434 ollama on Jetson**（VLM 在用）
9. **3588 上没 sudo 别试**

## 执行计划

### Phase 1 · 现状摸底（0-15min）

```bash
# 1. 当前 git 状态
cd "/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"
git log --oneline -5
git status

# 2. 3588 supervisor 健康
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 "
  ps -ef | grep -E 'modules\.' | grep -v grep | wc -l   # 期望 10 个
  tail -30 /tmp/main_supervisor.log
"

# 3. 当前 stats baseline（5 分钟采样）
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 "
  timeout 300 mosquitto_sub -h 127.0.0.1 -v \
    -t 'av/video/detect' -t 'av/video/key_event' \
    -t 'av/video/scene_analysis' -t 'av/video/openvocab' \
    | tee /tmp/baseline_5min.jsonl
" > /tmp/local_baseline.jsonl
```

数据落 `/tmp/local_baseline.jsonl` + 3588 `/tmp/baseline_5min.jsonl` 双备份。算出：
- detect publish 速率 / camera
- key_event 速率 / 总数 / reason 分布
- scene_analysis 数 / VLM 平均 latency / max latency
- openvocab hits 数 / 命中类 / confidence 分布

### Phase 2 · 扫参（90 min · 凌晨 23:00-00:30 低噪时段）

依次跑 4 组 config 各 **20 min**，每组之间停 1 min 让 mosquitto 流量清空。

配置维度（改这两个文件的 DEFAULTS，**只改默认值不改逻辑**）：

| Config | keyframe_filter.idle_seconds | openvocab_filter.conf_threshold | 假设 |
|---|---|---|---|
| A (baseline) | 60  | 0.40 | 现状 — 预测 VLM 严重过载 |
| B | 180 | 0.40 | 4 路 / 3min = 1.3 req/min < 0.77 req/min Jetson 上限 ✓ |
| C | 300 | 0.40 | 更保守，看 idle 信号是否过稀 |
| D | 180 | 0.55 | C threshold + 高 conf openvocab，看误报降多少 |

每组结束 dump:
```
mosquitto_sub -h 127.0.0.1 -v -t 'av/video/+' > /tmp/sustain_<config>.jsonl &
```

修改参数 → rsync 到 `/home/firefly/av_unified_mvp/modules/` → kill 对应子进程 → supervisor 自愈：
```
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 "
  pkill -f 'modules\.keyframe_filter\.main'
  pkill -f 'modules\.openvocab_filter\.main'
  sleep 4
  ps -ef | grep -E 'keyframe|openvocab' | grep -v grep
"
```

不改 video_processor（重启代价大，4 路 RTSP 重连 + YOLO load 30s）。

### Phase 3 · sustain 5h（00:30 - 05:30）

根据 Phase 2 数据选**最优 config**（看 scene_analyzer 是否堆积、openvocab 误报率），跑 5 小时。

并行收集：
- 每 5 分钟一次 `ps aux` 内存/CPU 快照 → `/tmp/perf_<ts>.txt`
- 全量 mqtt dump → `/tmp/sustain_5h.jsonl`
- supervisor log tail → `/tmp/sustain_5h.log`

### Phase 4 · 数据分析（05:30 - 07:00）

写 Python 脚本（落 `scripts/analyze_sustain.py`）解析 jsonl：
- VLM latency p50/p95/p99/max
- scene_analyzer 队列堆积估算（key_event 数 vs scene_analysis 数的 diff over time）
- openvocab confidence 分布直方图 / 每类命中数
- detect 心跳是否漏（4 路应 ~4 / 15s）
- supervisor 是否触发过 respawn（pgrep 历史 PID 对比）

### Phase 5 · 出报告 + 推参（07:00 - 08:00）

写 `OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md`，包含：

1. **执行摘要**（user 30 秒看完）：链路是否通了 8h / 是否堆积 / 推荐参数
2. **数据**：4 个 config 对比表 + 5h sustain 关键指标
3. **推荐配置**：
   ```
   keyframe_filter.idle_seconds = <推荐值>
   openvocab_filter.conf_threshold = <推荐值>
   理由：<基于哪条数据>
   ```
4. **未解问题**：列出 sustain 中冒出但本夜没解的（如 OOM / VLM 长尾 / 等）
5. **建议下一步**：1-3 条 actionable item，user 起床决定

最后：
```
git add modules/keyframe_filter/main.py modules/openvocab_filter/main.py OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md scripts/analyze_sustain.py
git commit -m "perf(vision): VLM sustain 8h 调优 — idle_seconds X→Y / conf_threshold X→Y

详见 OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

**不 push**，等 user 早上 review。

## 出错时怎么办

| 症状 | 应对 |
|---|---|
| supervisor 整体死了 | 不要 force 重启；先 `tail -200 /tmp/main_supervisor.log` 看死因，写到报告 |
| Jetson VLM 一段时间不响应 | 不要 ssh Jetson 重启（user 没给密码）；在报告里记下窗口 + supervisor log 时间戳 |
| dashboard `:5050` 打不开 | task #52 的老问题；停止本次任务，先记到报告，让 user 早上接手 |
| ssh 3588 失败 | 重试 3 次仍不行就停。**不要**尝试硬重启 3588 |
| 你修改的参数让链路完全没输出 | 立刻 revert 到 Config A baseline；revert 步骤记报告 |
| 凌晨 4 点链路看似全停 | 极可能是 RTSP 摄像头夜间无信号 — 看 USB罗技C920 还在就 OK |

## 验收标准

- [ ] 4 个 config × 20 min 扫参完整数据落盘
- [ ] 5h sustain 数据完整
- [ ] VLM latency p50/p95/max 三个数字落地
- [ ] openvocab 各类 confidence 分布给出
- [ ] 推荐参数 + 1-2 条事实依据
- [ ] git 有 commit（**不 push**）
- [ ] 报告在 `OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md` 末尾签 "ready for review @ 08:00"

完成后输出一条「ready」给 user，停止主动操作，等 user 来看。

---

**最后**：如果中途发现这个任务的前提（VLM 过载预测）根本不成立（比如 Jetson scene_analyzer 已经有自己的 throttle / drop 机制），那就是 phase 1 摸底就发现的事 — 立刻停下来报告，不要硬跑 8h。
