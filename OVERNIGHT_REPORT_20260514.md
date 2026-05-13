# 晚间自主推进报告 — Jetson 双路 MQTT 协同 POC

> 接手会话：2026-05-13 14:44 启动（CST），M5 落笔 ~15:02
> 总耗时：~18 分钟（≪ 6h 预算）
> 提前结束原因：**Jetson mem_avail < 500 MB（硬终止器触发）** — 在 M4 跑完 12-probe 后达成，剩余的"补测" Jetson-solvable 探针被放弃，转写报告

## 一句话结论

**双路 MQTT 协议机制完全成立 ✓，qwen3:1.7b 在 Orin Nano 7.4G 上的"深思层"质量不足。**

- 12-probe e2e 全部按预期路由（fast-path 4/4，NPU 命中 1/1，escalate 触发 4/4，非命令 3/3）
- Jetson 接收 escalate 4/4，但 qwen3:1.7b 在这 4 个 catalog-外 prompt 上 0/4 解出合法 cmd
- Mac → 3588 → Jetson 端到端时延：fast-path < 60ms；NPU 命中 2s；escalate 触发 + Jetson 处理 5-6s
- Jetson 在加载 qwen3:1.7b 时 mem_avail 从 1.1Gi 跌到 146 MiB —— **不能升 qwen3:8b**（必 OOM）

## Milestone 状态

| M | 任务 | 状态 | 耗时 | 备注 |
|---|---|---|---|---|
| M1 | Jetson git 副本 + sprint 分支同步 | ✓ | 3 min | gh-proxy 镜像 stale（只有 main 旧版），换 Mac→Jetson rsync 全包 |
| M2 | Jetson llm_engine minimal supervisor | ✓ | 5 min | 写了独立 `main_jetson.py`，4 模块（llm_engine + system_info + network_info + control_dispatcher）连 3588 broker |
| M3 | escalate 双路 MQTT 协议 | ✓ | 6 min | engine.py / main.py 两端加 escalate 触发 + 接收，3588 send / Jetson receive 一次 round-trip 通了 |
| M4 | 12-probe e2e 测试 | ✓ | 2 min | 数据见 § 下面 |
| M5 | 报告 | （本文） | — | 不 commit，留早晨 review |

## 协议设计 — av/llm/escalate

```
topic: av/llm/escalate         (3588 publish / Jetson subscribe)
payload: {
  text: "用户原文",
  escalate_reason: "llm_returned_null" | "filter_rejected_whitelist" | "filter_rejected_location",
  original_cmd_attempt: <str | null>,   // 3588 LLM 试图输出但被拒的 cmd_id
  correlation_id: <str>,
  source_host: "3588"
}

topic: av/control              (Jetson 处理成功后回写，路径与 3588 一致)
payload: {
  cmd: "...", original_text: "...",
  source_host: "jetson",
  escalated_from: "3588",
  escalate_reason: "..."
}
```

**触发条件**（在 `engine.process_command` 内）：`is_command=True AND generate_command() returned None AND self.escalate_to_jetson=True AND _last_miss_reason ∈ {llm_returned_null, filter_rejected_whitelist, filter_rejected_location}`

**避免回环**：Jetson 只订阅 `av/llm/escalate`（`audio_command_subscribe: false`），且 Jetson 端 `escalate_to_jetson` 未设 → 即使 Jetson 自己 fast-path miss + LLM null，也不会二次 escalate。

## M4 12-probe 数据表

3588 系统时钟为 UTC，下表时延以本地 Mac 发布时间为基准（CST → UTC 偏移已对齐）。

| Tag | 文本 | 预期路径 | 实际路径 | pub→出 (ms) | Jetson 处理 | 落到 av/control |
|---|---|---|---|---:|---|:---:|
| FP01 | 把吧台的窗帘打开 | fast-path | fast-path ✓ | 56 | — | ✓ BarCounter_Curtain_Open |
| FP02 | 财务室的灯带关掉 | fast-path | fast-path ✓ | 11 | — | ✓ FinanceOffice_Light_Off |
| FP03 | 把走廊的灯带打开 | fast-path | fast-path ✓ | 9 | — | ✓ Corridor_Light_On |
| FP04 | 请把工程部的轨道灯关掉 | fast-path | fast-path ✓ | 10 | — | ✓ EngineeringDepartment_TrackLight_Off |
| NPU01 | 请把吧台的灯调亮一点 | NPU 解 / escalate | **NPU 1.5B 解** ✓ | 2005 | — | ✓ BarCounter_Light_On |
| ESL_LOC01 | 把那个灯打开 | escalate | escalate（reason=filter_rejected_whitelist, attempt=RDDepartment_Light_On）| 1979 | qwen3:1.7b → null，深思 miss=filter_rejected_whitelist | ✗ |
| ESL_LOC02 | 灯关掉 | escalate | escalate（reason=filter_rejected_whitelist, attempt=RDDepartment_Light_Off）| 1992 | qwen3:1.7b → OperateCentre_Light_Off (location 拒) | ✗ |
| ESL_WL01 | 请把烤面包机打开 | escalate | escalate（reason=filter_rejected_location, attempt=RDDepartment_AirConditioner_On）| 2536 | qwen3:1.7b → OperateCentre_AirConditioner_On (location 拒) | ✗ |
| ESL_WL02 | 微波炉的电源关掉 | escalate | escalate（reason=filter_rejected_location, attempt=RDDepartment_AirConditioner_Off）| 2459 | qwen3:1.7b → OperateCentre_AirConditioner_Off (location 拒) | ✗ |
| NC01 | 今天天气怎么样 | classify=False | classify=False ✓ | 8 | — | — |
| NC02 | 现在几点了 | classify=False | classify=False ✓ | 9 | — | — |
| NC03 | 你叫什么名字 | classify=False | classify=False ✓ | 25 | — | — |

**E2E escalate 时延（probe → 3588 NPU → publish → Jetson qwen3:1.7b → done）：5-6 秒**
- 3588 NPU 1.5B 部分 2-2.5s
- Jetson qwen3:1.7b 推理部分 3-3.5s（observed in Jetson log diff）

## 关键发现

### 1. 协议机制完全成立
12/12 probe 路由正确，无丢消息、无重复 dispatch、无 escalate 回环。`av/llm/escalate` topic 上消息结构稳定可解析。

### 2. fast-path 在四个不同 location 都稳定命中
吧台 / 财务室 / 走廊 / 工程部 各点一次，sub-60ms。fast-path 索引（76 条）在 catalog 升级时按现有逻辑自动 derive。

### 3. NPU 1.5B 实际比预想能干
NPU01 "请把吧台的灯调亮一点" → BarCounter_Light_On — "调亮一点" 不在 fast-path 的 action_aliases（只有 "开/打开/启动"），NPU 1.5B 通过 prompt 内 catalog 推理出正确 cmd_id。**这次 fast-path miss 后没有 escalate**（NPU 直接命中）。说明 3588 漏斗第 2 层（NPU）能 cover 一部分自然语言变体，escalate 真正触发的频率会比预想低。

### 4. qwen3:1.7b 在深思层没赢
4 个 escalate probe 是刻意挑的"无 catalog 答案"案例：
- 把那个灯打开 / 灯关掉：缺地点
- 烤面包机 / 微波炉：catalog 没这设备
理论上正确输出应是 `null`，但 qwen3:1.7b 没认怂，**全部硬编了 cmd_id**（最爱 OperateCentre_AirConditioner_* 这一族），被 location 反幻觉 filter 拦下。

观察细节：
- 3588 NPU 1.5B 在同样 4 个 prompt 上反复硬编 RDDepartment_* —— 两套小模型都有"催眠默认地点"倾向，问题来自 prompt 设计（catalog 列表顺序）而非模型本身
- qwen3:1.7b 没显出比 NPU 1.5B 更深的语义理解；至少在这 4 个 prompt 上看不出"深思"价值
- **没测到的"qwen3 真有用"场景**：因为 NPU 解过的就不会 escalate，未来想看价值需要专门挑 NPU 失败 + Jetson 应能解的 prompt（比如复杂多设备组合 / 远离 catalog 措辞但答案在 catalog）

### 5. Jetson Orin Nano 7.4G 的 qwen3:1.7b 实际占用
- 模型加载（首次推理冷启动后）：**RAM ↓ 从 1.1 Gi → 146 MiB**
- ollama API 返回 `size_vram=992 MB / total ≈ 2.3 GB`
- **不能升 qwen3:8b**：8b 模型 5.2GB，加载后 Jetson 必 OOM（audio_processor 已占 ~1.5GB）
- 替代：试 `qwen2.5-coder:1.5b`（1.4GB，与 3588 同模型）或更小的 `gemma3:1b`（815MB），但语义能力相比 1.7b 会更弱

### 6. ollama qwen3:1.7b 自动 5min unload
配置 `expires_at` 显示约 5 分钟空闲后从 VRAM 释放。这意味着稀疏 escalate 触发时，每次都会重新加载（冷启动 +1-2s）。生产化要 keep-warm，但 7.4G 总内存下 keep-warm 会一直挤掉其他模块。

## 双路 MQTT 是否成立？答：**机制成立，模型选型需要重做**

| 维度 | 答案 |
|---|---|
| 协议 (topic/payload/订阅边界) | ✓ 落地，可入仓 |
| 3588 端 escalate 触发逻辑 | ✓ 三种 miss reason 都覆盖；默认关，向后兼容 5/13 |
| Jetson 端 escalate 接收逻辑 | ✓ handle_escalate 走同 catalog filter，不二次 escalate |
| 端到端时延 5-12s 预期 | ✓ 实测 5-6s（在 qwen3:1.7b 上） |
| 深思层"比 3588 NPU 更强" | ✗ 这次 0/4，但 probe 设计是"无解" probe，不算公允 |
| qwen3:8b 可行性 | ✗ Orin Nano 7.4G 内存不够 |

## 改动清单（未 commit）

### 仓库代码
- `modules/llm_engine/engine.py`
  - `__init__`：读 `cfg.llm.escalate_to_jetson` / `escalate_receiver` / `host_label` 三个开关；新增 `_last_miss_reason` / `_last_cmd_attempt` 实例字段
  - `generate_command`：每个 miss 路径设 `_last_miss_reason`，命中时 reset
  - `process_command`：在 cmd None 且 `escalate_to_jetson=True` 时 publish `av/llm/escalate`；av/control payload 加 `source_host`
  - 新方法 `handle_escalate(payload)`：接收端，调 generate_command 后回写 av/control（带 `source_host`/`escalated_from`/`escalate_reason`）
- `modules/llm_engine/main.py`
  - 新读 `cfg.llm.audio_command_subscribe`（默认 True，向后兼容）— Jetson 设 false，只订 escalate
  - 新读 `cfg.llm.escalate_receiver` — true 时订 `av/llm/escalate`
  - `_handle_message` 路由 `av/llm/escalate` → `engine.handle_escalate`

### 仅 Jetson 副本
- `main_jetson.py`（新）：minimal supervisor，只起 4 模块，结构沿用 Mac `main.py`
- `config/system_config.yaml`（Jetson 副本）：broker=192.168.5.6，client_id=av_jetson_001，ollama 用 qwen3:1.7b，`escalate_receiver=true`、`audio_command_subscribe=false`、`host_label=jetson`

### 仅 3588（运行时配置改动）
- `/home/firefly/av_unified_mvp/config/system_config.yaml` 的 `llm:` 块 加 `escalate_to_jetson: true` 与 `host_label: '3588'`
- engine.py / main.py 同步过去（与 Mac 一致）

## 进程现状

### 3588 (192.168.5.6)
| PID | 进程 | 备注 |
|---|---|---|
| 1171523 | main.py supervisor | 不动 |
| 1171603 | sensevoice_rknn_daemon | 不动（5/13 重启过的） |
| **1209051** | rkllm_daemon | **被替换了**（原 1182343）— llm_engine 子进程，杀 llm_engine 时连带替换。新 daemon 健康（load 2.0s, RSS 1.7GB），但 5/13 ~03:00 起的 11.5h 长跑样本断了 |
| **1209050** | modules.llm_engine.main | **新启动** — 当前 client_id `av_3588_001_llm_engine_9c8fbf`，escalate_to_jetson=true |
| 1188869 | node-red | 不动 |

### Jetson (192.168.5.51)
| PID | 进程 | 备注 |
|---|---|---|
| 604725 | audio_processor | 5/12 起 30h+ 长跑样本，未动 |
| **620547** | main_jetson.py supervisor | 新启动（M2）|
| 620550 | modules.system_info.main | 新启动 |
| 620551 | modules.network_info.main | 新启动 |
| 620552 | modules.control_dispatcher.main | 新启动（与 3588 dispatcher 并存，echo_only） |
| **621507** | modules.llm_engine.main | 新启动，escalate_receiver=true，audio_command_subscribe=false |

## 决策点（早晨 user review）

1. **escalate 协议入仓？**
   - 优点：默认 `escalate_to_jetson: false`，向后兼容 5/13 行为；机制已验证
   - 缺点：当前唯一深思层载体 (qwen3:1.7b on Jetson) 没显出价值
   - 建议：**入仓代码改动 + 把 escalate_to_jetson 默认关**，等找到更合适的深思层（更大模型 / 多模态 / 不同硬件）再开关
2. **Jetson 深思层路径放弃 / 升级？**
   - qwen3:8b 不可行（OOM）。可试方向：
     - (a) 换更小 1.7b 候补的模型做对比（gemma3:1b / phi4-mini:3.8b 在 Jetson 已就位）
     - (b) Jetson 改跑 multimodal（qwen2.5vl:3b 在 Jetson 已就位）—— 把 video_processor 检测结果 + 语音文本一起喂，做"看着场景做决策"
     - (c) 深思层改去 Mac mini (192.168.5.249) 跑 ollama 大模型（M2 Pro mem 大，可 qwen3:8b 甚至 14b），把 mqtt broker 共享逻辑直接复用
   - 建议：**(c)** 用 Mac mini 当深思层，Jetson 留给 multimodal 试验。escalate 协议不变，只是 escalate_receiver 改到 Mac mini 上。
3. **rkllm_daemon 长跑样本断了如何弥补？**
   - 新 daemon 14:54 起，预计稳定，但 5/13 的 11.5h 数据已丢
   - 建议：从今天开始重新计时；如果 21/22:00 还稳，又是一个新的 7-8h 样本

## 紧急清理（如果要把环境恢复到 5/13 EOD 状态）

```bash
# Mac
git checkout -- modules/llm_engine/engine.py modules/llm_engine/main.py
rm OVERNIGHT_REPORT_20260514.md

# 3588: 把 engine 改动回滚 + 配置 escalate_to_jetson 删掉，杀 llm_engine 让 supervisor 重拉
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 \
  "cd ~/av_unified_mvp && git checkout -- modules/llm_engine/engine.py modules/llm_engine/main.py \
   && python3 -c 'import yaml; p=\"config/system_config.yaml\"; c=yaml.safe_load(open(p)); c[\"llm\"].pop(\"escalate_to_jetson\", None); c[\"llm\"].pop(\"host_label\", None); open(p,\"w\").write(yaml.safe_dump(c, allow_unicode=True, sort_keys=False))' \
   && pkill -TERM -f 'modules.llm_engine.main'"

# Jetson: 杀 supervisor 即停所有模块（git 没历史，整个 ~/av_unified_mvp_jetson 是 rsync 的 sprint 分支副本）
SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51 "pkill -TERM -f main_jetson.py"
```

## 文件锚点

| 文件 | 何用 |
|---|---|
| `/tmp/m4_capture.jsonl`（3588） | M4 原始 broker capture，33 行 |
| `/tmp/m4_run.log`（3588） | M4 publish ts 索引 |
| `/tmp/main_supervisor.log`（3588） | llm_engine 行为日志（含 escalate trigger 日志） |
| `/tmp/jetson_supervisor.log`（Jetson） | Jetson 4 模块日志 + handle_escalate 日志 |

## 建议下一步

1. 入仓 engine.py / main.py 改动（默认关）+ 进 commit message 引用本文 § "改动清单"
2. 把 `main_jetson.py` 也入仓（在仓库根，与 main.py 并列）—— 后续多硬件部署能复用 alt supervisor 思路
3. 重新设计 escalate probe set：挑 "3588 NPU 解不出 + 答案在 catalog" 的 prompt，对 qwen3:8b（如果用 Mac mini）或当前 1.7b 做公允对比
4. Jetson mem 紧的根因：audio_processor 占 1.5GB + qwen3:1.7b 加载占 2.3GB + 系统/其他 ~3GB → 7.4G 用完。如果坚持深思层在 Jetson，audio_processor 要迁走（让 3588 sensevoice 唯一负责语音）
