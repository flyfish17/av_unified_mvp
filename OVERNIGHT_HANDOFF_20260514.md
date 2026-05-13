# 晚间自主推进交接 — Jetson "深思层" 双路 MQTT 协同

> 接手对象：另一个 Claude Code 会话（用 `claude --dangerously-skip-permissions` 启动）
> 主线对话日期：2026-05-13 下午（5/13 全天 12 commits 跑 3588 阶段 3 第 2 层 NPU + fast-path + dispatcher，详见 DEVELOPMENT_PLAN.md §6 5/13 段）
> 任务总耗时：**≤ 6 小时**（硬约束）。中途随时可被 STOP sentinel / 用户 ctrl+C 终止。

## Mission（一句话）

**把 Jetson Orin Nano 接入阶段 3 的双路 MQTT 协同框架**：3588 漏斗 miss（fast-path 不命中 + NPU LLM 输出被 filter 拒 / 返回 null）时，把意图"升级"到 Jetson ollama `qwen3:8b` 处理，Jetson 处理后发回 `av/control`。验证 §1.5 "硬件矩阵"战略中**两套硬件协同**的可行性。

**直接产出**：明早一份 `OVERNIGHT_REPORT_20260514.md` 在 repo 根目录，告诉用户：
- 双路 MQTT 协议落地了没（escalate topic + Jetson 订阅 + 回写 av/control）
- 端到端实测：fast-path 命中率 / NPU 命中率 / Jetson 升级处理率 / 错误命令落地率
- Jetson `qwen3:8b` 在 7.4GB Orin Nano 上的实际延迟（首 token + 完成）+ RAM 余量
- 没跑通 → 详细失败链路 + 转回 ollama 兜底不浪费时间

## 先读这些（5 分钟接手）

| 文档 | 何用 |
|---|---|
| 本文 § Mission / § 约束 / § Milestone | 知道做什么 |
| `DEVELOPMENT_PLAN.md` §1.5 产品三形态 + §6 最新进度日志（2026-05-13 段） | 5/13 全天上下文 + 战略澄清 |
| `OVERNIGHT_REPORT_20260513.md` | 昨夜 NPU LLM 探索完整结论 + 数据 |
| `modules/llm_engine/engine.py` | fast-path + location filter + classify_intent 三层漏斗实现 |
| `modules/control_dispatcher/main.py` | av/control → 设备 dispatcher（echo_only，今晚不动） |
| `docs/deploy/3588-npu.md` | 3588 NPU 部署 SOP + 11 节 supervisor 启动 |

## 设备 + 网络

| 项 | 值 |
|---|---|
| 3588 SSH | `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6`（sudo NOPASSWD 已配） |
| Jetson SSH | `SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51` |
| Mac → HF mirror | `HF_ENDPOINT=https://hf-mirror.com` |
| 内网带宽 Mac↔3588↔Jetson | ~20 MB/s GbE |
| 3588 系统时钟 | **UTC**（不是北京时间） |
| Jetson 系统时钟 | **CST** 北京时间 |

## 当前活进程（不动，5/12-5/13 长跑稳定性样本）

| 设备 | PID | 进程 | uptime |
|---|---|---|---|
| 3588 | 1162126 | main.py supervisor (8 模块) | 5/13 ~03:00 起 |
| 3588 | 1166144 | audio_processor（happyme531 NPU ASR） | 5/13 重启过 |
| 3588 | 1182343 | rkllm_daemon（NPU LLM 1.5B） | 5/13 ~03:00 |
| 3588 | 1188869 | node-red | 5/13 ~14:07 |
| Jetson | 604725 | audio_processor（CUDA ASR） | 5/12 起 30h+ |

**任何 PID 死了 → 报告里写明 + 不主动重启**（除非完全无法继续 mission）。

## 工作目录约定

- **3588**：今晚主要改 `~/av_unified_mvp/`（git 已在 `sprint/liaohe-3588-night-poc-20260511`，5/13 12 commits 都在）
- **Jetson**：`~/av_unified_mvp/` **是 rsync 拷贝不是 git 仓库**，需要：
  - 选项 A：`cd ~ && git clone <repo> av_unified_mvp_jetson` 新建 git 副本，避免 conflict
  - 选项 B：进入老目录 `git init && git remote add origin ... && git fetch && git checkout sprint/liaohe-3588-night-poc-20260511`（保留老目录有风险）
  - **推荐 A**：干净路径不带 5/11 旧文件污染
- Mac 上：报告写 `OVERNIGHT_REPORT_20260514.md` 到仓库根目录但**先不 commit**，早上 user review 后决定

## 硬约束（不可越）

1. **不重启 audio_processor / sensevoice / rkllm_daemon / 3588 supervisor 1162126 / Node-RED** — 演示稳定性样本，5/13 全天调通的
2. **不动 3588 现有 8 模块代码**（除 `engine.py` 加 escalate 触发，**保持向后兼容** — escalate 触发条件配置化默认关）
3. **不动 git 分支结构** — `sprint/liaohe-3588-night-poc-20260511` 不动；如要实验改动先在 worktree 或本地 stash
4. **不 push** 任何 commit 到 origin（早上 review 后再决定）
5. **Jetson ollama 模型不重新 pull**（9 个已就位，避免国际链路耗时）
6. **不动 Jetson audio_processor PID 604725**（5/12 阶段 2 长跑样本）

## 硬终止触发器（任一即 abort + 写报告退出）

| 触发器 | 检测方式 |
|---|---|
| 用户 `/tmp/STOP_OVERNIGHT` 存在（3588 或 Jetson 都可放） | 每次 milestone 间检查 |
| 总耗时 > 6 小时（从 `started_at` 算） | 每次 milestone 间检查 |
| 3588 mem_avail < 2 GB | preconditions 监测 |
| Jetson mem_avail < 500 MB | Orin Nano 紧 |
| 3588 audio_processor / sensevoice / rkllm_daemon PID 死 | 说明影响到了 |
| 同一 milestone 连续失败 3 次 | iteration 自己记账 |

触发后：
- 写最后一份 `OVERNIGHT_REPORT_20260514.md`，说清在哪一步停的、为什么、有哪些数据
- 不再继续，安静退出

## Milestone 序列（self-paced）

每个 milestone 完成后立刻：① 追加进度到 `OVERNIGHT_REPORT_20260514.md` 草稿；② 检查 STOP / 时间预算；③ 决定要不要进下一个。

### M1 — Jetson git 副本 + sprint 分支同步（≤ 30 min）

```bash
# Jetson 上新建 git 副本（保留老 rsync 目录不动）
SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51 '
cd ~ && git clone https://github.com/flyfish17/av_unified_mvp.git av_unified_mvp_jetson 2>&1 | tail -5
cd ~/av_unified_mvp_jetson && git checkout sprint/liaohe-3588-night-poc-20260511 && git log --oneline -3
'
```

成功条件：jetson `~/av_unified_mvp_jetson/` 切到 `sprint/liaohe-3588-night-poc-20260511` 5/13 最新 commit。

如果国际链路慢（github.com 慢），改用 gh-proxy.com 镜像：`https://gh-proxy.com/https://github.com/...`。或者 Mac → Jetson rsync 也可（Mac 上是 git tracked 副本，rsync 时 `--exclude=.git` 然后到 Jetson 后 `git init` 接 remote）。

### M2 — Jetson llm_engine minimal supervisor（≤ 60 min）

不跑 audio_processor / video_processor（与 3588 重复占资源）。只跑：
- `llm_engine`（用 ollama backend，model_fast: qwen3:8b）
- `system_info`（监控用）
- `network_info`（监控用）
- `control_dispatcher`（如果 Jetson 也需要回写 av/control，看 M3 设计）

```bash
# Jetson 上需要装 av_unified_mvp 的 Python 依赖（5/12 已装过 funasr/torch CUDA，可能要加 flask/paho-mqtt）
SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51 '
cd ~/av_unified_mvp_jetson && \
pip3 install --user flask paho-mqtt PyYAML 2>&1 | tail -3 && \
python3 -c "import flask, paho.mqtt.client, yaml; print(\"deps OK\")"
'
```

system_config.yaml 要改：
- mqtt broker：**用 3588 的 `192.168.5.6:1883`**（统一总线，不在 Jetson 上起新 broker）
- llm.ollama.url: `http://127.0.0.1:11434/api/generate`（Jetson 本机）
- llm.ollama.model_fast: `qwen3:8b`
- llm.ollama.model_smart: `qwen3:8b`
- 不要 default_location（Jetson 是"深思层"，没物理位置默认）

成功条件：Jetson 上 `python3 main.py` 起来，3588 上 mosquitto_sub `av/system/discovery/llm_engine` 能看到 Jetson 副本上线（`ip: 192.168.5.51`）。

⚠️ **Jetson mem 紧**：qwen3:8b loaded ~5.5GB，Orin Nano 7.4GB 总内存 + audio_processor 占着，可能 OOM。**先测 ollama qwen3:1.7b 当 fallback**，确认 link 通了再升级模型。

### M3 — escalate 双路 MQTT 协议（≤ 90 min）

新 topic 设计：

```
av/llm/escalate              3588 触发"升级"，Jetson 订阅
  payload: {
    text: "用户原文",
    escalate_reason: "fast_path_miss" | "npu_returned_null" | "filter_rejected",
    original_cmd_attempt: "RDDepartment_xxx" 或 null,
    correlation_id: "...",
    source_host: "3588"
  }

av/control                   Jetson 处理后照旧发到这里，control_dispatcher 一视同仁
  payload: { cmd, original_text, ... } + header.source = "jetson_llm_engine"
```

3588 端 `engine.py` 改动（最小侵入）：
- `generate_command` 末段：fast-path miss + LLM null/rejected 时，**默认 echo_only** —— 现在改成"如果 cfg.llm.escalate_to_jetson == true"，发 `av/llm/escalate` 不调 LLM
- 默认 `escalate_to_jetson: false`（向后兼容），开关在 system_config 里
- 配置好了之后 3588 上设 `escalate_to_jetson: true`

Jetson 端 `llm_engine/main.py`：
- 订阅 `av/llm/escalate`
- `process_command` 改成走 ollama qwen3:8b（fast-path 也可以挂上但优先 LLM 因为 escalate 已经是"fast-path miss" case）
- 输出 cmd 经过同样的 whitelist + location filter（catalog 是同一份），通过后发 `av/control` + source 标 jetson

**关键**：3588 现有 fast-path 命中 + NPU LLM 命中的 case **不**触发 escalate（已经成功了），只有 miss 才转。

### M4 — 端到端 e2e test（≤ 45 min）

用同样 12 prompt set 跑（参照 5/13 综合压测）：
- 4 fast-path 命中（应在 3588 完成，0 escalate）
- 1 NPU 命中（应在 3588 完成）
- 2 location filter 拒 → **escalate 到 Jetson**
- 2 whitelist 拒 → **escalate 到 Jetson**
- 3 非命令（关键词层拦，不 escalate）

成功条件：4 个 escalate prompt 在 Jetson 上 qwen3:8b 输出 cmd_id，正确通过 catalog whitelist 落到 av/control + dispatcher 看到。

记录：每个 escalate prompt 的 e2e 时延（3588 收到 → MQTT 转 Jetson → qwen3:8b 推理 → 回 av/control）。预期 5-12s。

### M5 — 报告 + 结论（≤ 30 min）

写 `OVERNIGHT_REPORT_20260514.md`：
- 各 milestone 状态 + 数据
- 双路 MQTT 是否成立：是 / 否 / 部分
- 失败链路（如有）+ 下一步如何走
- Jetson `qwen3:8b` 在 Orin Nano 7.4G 的实际可用性数据：加载时间 / 首 token / 完成时延 / OOM 风险
- 阶段 3 第 3 层（深思）的下一步建议

不 commit、不 push。早上 user review 后决定。

## /loop 启动姿势

新会话第一条 prompt 建议：

```
/loop 读 OVERNIGHT_HANDOFF_20260514.md 然后开始 Jetson 双路 MQTT milestone 1
```

每个 iteration 结束时调 `ScheduleWakeup`（自我节奏）或 /loop dynamic mode，
`delaySeconds` 选 1200-1800（既等 ollama qwen3:8b 加载 / inference 也兼顾 prompt 缓存窗口）。
**别 sleep < 5 min**（浪费缓存窗口）。

## 启动检查清单（first iteration 时跑）

1. `cat OVERNIGHT_HANDOFF_20260514.md` — 完整读完本文
2. `cat DEVELOPMENT_PLAN.md | sed -n '/2026-05-13/,/^### /p'` — 看 5/13 进度
3. `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 'pgrep -af "main\.py|sensevoice|rkllm" | head -10'` — 3588 演示状态健康
4. `SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51 'pgrep -af audio_processor; free -h | head -2'` — Jetson 长跑样本 + 内存
5. `test -f /tmp/STOP_OVERNIGHT && echo abort || echo go` — STOP sentinel
6. 进入 M1。

## 早晨用户 review 流程

```bash
cd "/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"
cat OVERNIGHT_REPORT_20260514.md
# 决定：
#  - escalate 协议入仓？ → 一起 commit
#  - 双路 MQTT 路径开走？ → 阶段 3 升 sprint
#  - 失败转兜底? → 也清楚下一步
```

## 紧急 abort

```bash
ssh firefly@192.168.5.6 'touch /tmp/STOP_OVERNIGHT'
# 或
ssh jetson@192.168.5.51 'touch /tmp/STOP_OVERNIGHT'
```

Loop 下次 iteration 检测到立即收尾退出。

## 联系（如果新会话遇到困惑要问用户）

- **不要**自作主张超出本 mission：不改 video_processor / control_dispatcher 核心逻辑、不动 catalog、不 push、不 merge
- **可以**自主：Jetson 装依赖、配 yaml、写新 module、跑 ollama / 测量 / 改 3588 engine.py（小心 + 向后兼容）
- 遇到不可恢复错误：写完 partial report 退出，留给早晨 review。**不要重启 3588 长跑进程来"修复"**问题

## 写得不要太细 — 工程判断留给执行者

- M3 protocol design 大方向给了，具体 schema / 字段名可调
- M2 Jetson model 选择 1.7b vs 8b 看实际 mem，不强求 8b
- 时间不够时按优先级砍：M1+M2+M3+M4 是基线，M5 报告必写
- 6h 内 fold 不出来不是 task failure，先 partial deliver
