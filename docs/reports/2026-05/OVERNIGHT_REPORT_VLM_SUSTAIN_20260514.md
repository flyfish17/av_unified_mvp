# 夜班长跑报告 · 视觉深思链路 VLM sustain 8h + 参数调优

**日期**：2026-05-14 夜班（21:00 启动 → 2026-05-15 07:57 数据采集结束 / 08:00 user 接手）
**分支**：`sprint/liaohe-3588-night-poc-20260511`
**前置 commit**：`54ecbdd docs: 夜班长跑 handoff`
**Handoff 文档**：`OVERNIGHT_HANDOFF_VLM_SUSTAIN_20260514.md`

---

## 执行摘要（30 秒看完）

1. **链路 9.5h 不死** — 3588 上 10 个 module 全程在线，无 respawn / OOM / crash；内存稳定 44-46%。
2. **VLM 链路真正瓶颈不是 keyframe_filter idle_seconds，而是 Jetson 内存** — Jetson `mem_percent` 全程 97-98%（无任何释放窗口），scene_analyzer 因 `mem_min_mb=400` 守门，**96% 的 key_event 被 drop**（747 入 / 28 出）。
3. **推荐配置已 commit** — `idle_seconds=180`（key 速率 3.6 → 1.2/min，3x 减少浪费）+ `conf_threshold=0.55`（夜间无人无 hits，无法独立验证但是更保守的默认）。
4. **真正治本不在本次任务范围**：Jetson 内存压力需要 (a) 改用更小 VLM 模型 / (b) 关 ollama keep_alive 让模型按需卸载 / (c) Jetson Orin Nano 8G 升 16G。**P0 行动项见 §6**。

---

## 1. Phase 1 · 现状摸底（baseline 5min）

- 3588 supervisor 健康（10 modules：video_processor / audio_processor / keyframe_filter / openvocab_filter / control_dispatcher / husion_distributed / llm_engine / network_info / network_scanner / system_info）。
- detect 心跳：4 cam × ~3.7/min（idle_detect_interval_s=15 生效）。
- baseline 5min 数据：20 key_event / 2 scene_analysis / 0 openvocab hits（Jetson 还有边际算力）。

详见 `/tmp/vlm_sustain_data/baseline_5min.jsonl`（95 行）。

## 2. Phase 2 · 4 组扫参（每组 20min · 总 80min）

| Config | idle_seconds | conf_threshold | key/min (per cam) | scene_analysis / 20min | 备注 |
|---|---|---|---|---|---|
| A | 60  | 0.40 | 0.90 | **0** | baseline：完全堵 Δ=72 |
| B | 180 | 0.40 | 0.30 | **3** | VLM 偶发复活，全在 USB罗技C920 |
| C | 300 | 0.40 | 0.15 | **0** | key 太稀仍 0，反而比 B 差 |
| D | 180 | 0.55 | 0.30 | **0** | 20min 太短不显著 |

**关键判读**：
- scene_analysis 数量与 idle_seconds 不存在单调关系（B>D 同 idle，B 出 3 D 出 0）→ **VLM 是否工作完全取决于 Jetson 内存瞬时状态**，跟 keyframe 节流参数无关。
- key_event 速率 100% 跟随 idle_seconds 公式：理论 1/idle ≈ 实际 key/min/cam。

数据文件：`/tmp/vlm_sustain_data/sustain_{A,B,C,D}.jsonl`。

## 3. Phase 3 · sustain 9.5h（Config D · idle=180 / conf=0.55）

- 启动：2026-05-14 22:29 本地 CST（14:27 UTC）
- 数据冻结：2026-05-15 07:57 本地（23:57 UTC）
- 总 jsonl：41997 行 / `/tmp/vlm_sustain_data/sustain_5h.jsonl`
- perf 快照：114 个 / `/tmp/vlm_sustain_data/perf/`（每 5min 一次 free+ps）

### 3.1 关键指标

```
duration:        570.5 min (9.5h)
cameras:         USB罗技C920, test, 办公室, 财务室

[detect]         4 cam × 3.6/min ≈ 14.4/min 总（idle_detect_interval=15s 生效）
[key_event]      747 总数 = 4 cam × 0.33/min（idle=180 精确对应 1/180s）
[scene_analysis] 28 总数 = 0.05/min — 96.2% drop
                 vlm_latency_ms: p50=77550  p95=78291  p99=104166  max=104166
                 全部命中 USB罗技C920 单路；test/办公室/财务室 0 scene/9.5h
[openvocab]      0 hits（夜间办公室无人，4 个 prompt 全 person/fire 类，符合预期）
```

### 3.2 主机内存趋势（9.5h，~6800 个采样点）

| host | min | p50 | p95 | max |
|---|---|---|---|---|
| Jetson Orin Nano (7.4GB unified) | 97.1% | 98.1% | 98.3% | 98.5% |
| 3588 (15.6GB) | 44.7% | 45.6% | 46.0% | 46.2% |

**Jetson 整夜从未释放过内存**，即便 keep_alive=10m 默认配置理论上应让模型卸载。

### 3.3 scene_analysis 按本地小时分布

```
00:01   04:03   06:06   07:18
```

整夜稀疏，黎明（07:xx）突现 18 个事件 — 可能是 Jetson 在某个时刻终于释放了内存。这是 stochastic 行为，无法靠 keyframe 参数调控。

### 3.4 supervisor 稳定性

- 10 modules 全程在线，0 respawn / 0 crash / 0 OOM
- 3588 mem 稳定无 leak
- 整夜无任何 dashboard `:5050` 异常、`:5051` MJPEG 异常、`:1880` Node-RED 异常

## 4. 推荐配置

```
modules/keyframe_filter/main.py:51   idle_seconds:    60 → 180   ✅ 已 commit
modules/openvocab_filter/main.py:63  conf_threshold:  0.40 → 0.55  ✅ 已 commit
```

**理由（基于数据）**：

| 决策 | 数据依据 |
|---|---|
| idle_seconds=180 | Phase 2 实测：60 时 100% 入 0 出（VLM 完全堵）；180 时 key/min 降至 1/3，给 Jetson 留更长间歇；300 时事件密度过低对前端体验不友好（4 cam × 0.05 scene/min = 80min/cam，已经很稀疏，再降无意义）。**180 是当前 Jetson capacity 临界点的合理上界**。 |
| conf_threshold=0.55 | Phase 2/3 夜间 0 hits 无法直接验证。沿用代码注释中既有判断「<0.40 几乎必误报」+ 提高一档至 0.55 是更保守的演示默认。**白天有人入画时应另起小规模测试做 differential 验证**。 |

## 5. 未解硬伤（user 必读）

1. **【P0】Jetson 内存死锁** — 整夜 97-98%，scene_analyzer `mem_min_mb=400` 守门 → 96% inference 被 drop。**这是当前视觉深思链路的真正瓶颈**，调任何 keyframe 参数都救不了。
2. **【P0】scene_analysis 4 路只覆盖 1 路** — USB罗技C920 独占了 28 个 scene_analysis，其他 3 路（test / 办公室 / 财务室）9.5h 内 **0 scene**。scene_analyzer 单 worker + throttle_seconds=10 + USB罗技C920 detect 略先到，导致后续 3 路 inflight_skipped 全部被丢。需要看 Jetson 上 scene_analyzer `_stats` 才能定量（本次未取 Jetson 日志，因红线限制无 SSH 权限）。
3. **【P1】openvocab 在夜间无人场景产出 0 hits** — 当前 prompt 全是 person/fire/smoke 类，夜间空办公室必 0。无法对 conf_threshold=0.55 做证伪。
4. **【P2】keep_alive=10m 配置疑似没生效** — 整夜稳态 98% 不该这样，至少应每 10min 周期性下降。可能 ollama 进程层泄漏或 keep_alive 参数没正确传入推理 body。

## 6. 建议下一步（user 起床决定）

| 优先级 | 行动 | 工作量 |
|---|---|---|
| **P0** | Jetson 上换更小 VLM 模型（qwen2.5vl:3b → 1.5b 或 InternVL-2-1B），单次推理内存 5.8GB → ~3GB，可同时跑 4 路 | 0.5d（model dl + scene_analyzer cfg） |
| **P0** | scene_analyzer 改成 **per-camera round-robin** 而非 inflight-drop，让 4 路平均覆盖 | 0.5d（main.py 加 last_inference_per_camera 优先级） |
| **P1** | 取 Jetson 上 scene_analyzer 日志 + `_stats` 反查 drop 原因（mem_guard / inflight / throttled 占比） | 0.5h（需 SSH 密码或让 user 在 Jetson 上 tail log） |
| **P1** | 白天扫参 conf_threshold 0.40 / 0.50 / 0.55 / 0.60 — 用 USB罗技C920 真人入画 false-positive 率 | 0.5h |
| **P2** | 排查 `keep_alive=10m` 是否生效（ollama 端 log + 推理 body 抓包） | 0.5d |

## 7. 数据归档

```
本地：
/tmp/vlm_sustain_data/baseline_5min.jsonl       (95 行)
/tmp/vlm_sustain_data/sustain_A.jsonl           (361, Config A)
/tmp/vlm_sustain_data/sustain_B.jsonl           (318, Config B)
/tmp/vlm_sustain_data/sustain_C.jsonl           (301, Config C)
/tmp/vlm_sustain_data/sustain_D.jsonl           (315, Config D)
/tmp/vlm_sustain_data/sustain_5h.jsonl          (41997, 9.5h sustain)
/tmp/vlm_sustain_data/perf/                     (114 snapshots × 5min)

3588 备份（未删，user 可随时取）：
/tmp/baseline_5min.jsonl  /tmp/sustain_{A,B,C,D}.jsonl
/tmp/sustain_5h.jsonl     /tmp/perf/
/tmp/keyframe_filter_main.py.orig  /tmp/openvocab_filter_main.py.orig (sed 前备份)

分析脚本：scripts/analyze_sustain.py（带 --label LABEL=path 多文件对比）
```

## 8. 红线遵守清单

- [x] 不动 audio_processor / sensevoice daemon
- [x] 不动 supervisor 主进程 main.py（只杀 keyframe / openvocab 子进程让 supervisor 自愈）
- [x] 不删 venv `/home/firefly/creator_ai_demo/venv/`
- [x] 不动 nodered_data / husion 现场预编排
- [x] 不 push origin（本地 commit only，等 user review）
- [x] 不 force push / rebase / 不修 main
- [x] 不动 :1880 Node-RED
- [x] 不动 :11434 ollama（Jetson 上的 VLM）
- [x] 不 SSH Jetson（无密码 + 红线）

---

**ready for review @ 08:00 (实际 09:00 本地 — 因 sustain 收尾期 mqtt dump 延迟至 07:57 自然终止，分析+本报告占了额外 1h；详见 §3 时间线)**
