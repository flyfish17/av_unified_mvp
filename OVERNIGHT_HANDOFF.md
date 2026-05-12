# 晚间自主推进交接 — 3588 NPU LLM 探索

> 接手对象：新 Claude Code 会话（用 `claude --dangerously-skip-permissions` 启动）
> 主线对话日期：2026-05-12 白天，本文是 ~15:30 写的交接
> 任务总耗时：**≤ 6 小时**（硬约束）。中途随时可被 STOP sentinel 终止。

## Mission（一句话）

**探索 RK3588 NPU 跑大模型推理**（rknn-llm SDK + Qwen 1.5B 预转 RKLLM 模型），目标拿到 NPU LLM 真实性能数据，判断阶段 3 「两级漏斗 LLM 第二层」能否走 NPU 路径而不是 ollama CPU。

**直接产出**：明早一份 `OVERNIGHT_REPORT_20260513.md` 在 repo 根目录，告诉用户：
- NPU LLM 跑没跑通
- 跑通 → 性能数据（token/s、首 token 延迟、内存占用、CER） + 阶段 3 用 NPU 的具体建议
- 没跑通 → 详细失败链路 + 转 ollama CPU 不浪费时间

## 先读这些（5 分钟接手）

| 文档 | 何用 |
|---|---|
| 本文 § Mission / § 约束 / § Milestone | 知道做什么 |
| `NIGHT_REPORT_20260512.md` | 白天进度 + 3588 NPU ASR 已跑通的过程 |
| `docs/roadmap/liaohe-3588.md` | 整体路线图 — Mission 在阶段 3 的位置 |
| `docs/deploy/3588-npu.md` | NPU ASR 的部署 SOP — RKLLM 套用同款 daemon 模式 |
| `scripts/templates/sensevoice_rknn_daemon.py` | AGPL 子进程隔离样板，照抄 |
| 3588 上 `~/rkllm-poc/PRECONDITIONS.yaml` | 离线时的 baseline 快照，用于回滚比对 |

## 设备 + 网络

| 项 | 值 |
|---|---|
| 3588 SSH | `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6`（sudo NOPASSWD 已配，sudo -n 可直接用）|
| Jetson SSH | `SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51`（备用，本次基本用不到）|
| Mac → HF mirror | `HF_ENDPOINT=https://hf-mirror.com python3 -c "from huggingface_hub import snapshot_download; ..."` |
| 3588 → HF 主站 | **不通** |
| 3588 → HF mirror | **不通**（实测） |
| 3588 → modelscope.cn | **通** |
| 3588 → github.com | **通** |
| 3588 → gh-proxy.com | **通**（github 国内镜像，拉 release tarball 用）|
| 内网带宽 Mac↔3588 | ~20 MB/s（GbE）|
| 3588 系统时钟 | **UTC**（不是北京时间，log 戳要 +8h 看）|

## 工作目录约定

**只动 3588 上 `~/rkllm-poc/` 内的东西**：

```
~/rkllm-poc/
├─ STOP                    sentinel，若文件存在 → loop 立即终止（用户/loop 都可 touch）
├─ PRECONDITIONS.yaml      离线快照（baseline）
├─ artifacts/              下载的 SDK / 模型 / 二进制
├─ logs/
│  ├─ milestone_N.log     每个 milestone 详细日志
│  └─ progress.md          loop iteration 状态汇总（人类可读）
└─ daemon/                 你写的 RKLLM daemon 脚本（参照 SenseVoice daemon 模式）
```

Mac 上：所有改动写到 `/tmp/rkllm-overnight-*` 临时区，**不在 git 仓库内**。最后写报告 `OVERNIGHT_REPORT_20260513.md` 到仓库根目录但**先不 commit**，明早用户 review 后决定。

## 硬约束（不可越）

1. **不动 av_unified_mvp 仓库** — 不 commit、不 push、不 git pull、不改任何已有文件
2. **不动 3588 上以下目录** — `~/av_unified_mvp/`、`~/SenseVoiceSmall-RKNN2/`、`~/creator_ai_demo/`、`~/.node-red/`、`/etc/systemd/`、`/etc/`、`/usr/`、`/opt/`
3. **不重启 audio processor PID 974319 / RKNN daemon PID 974370** — 这俩是稳定性测试样本，长跑数据要保留
4. **不动 Jetson**（除非有显式需要做 Jetson 比对，且简单 SSH 读不改）
5. **不动 git 分支结构** — `sprint/liaohe-3588-night-poc-20260511` 不动；如要做实验性修改用本地 git stash 也别 commit

## 硬终止触发器（任一即 abort + 写报告退出）

| 触发器 | 检测方式 |
|---|---|
| 用户 `~/rkllm-poc/STOP` 存在 | 每次 iteration 开始检查 |
| 总耗时 > 6 小时（从 `started_at` 算） | 每次 iteration 开始检查 |
| 3588 mem_avail < 2 GB | snapshot 比对，省点防 OOM |
| 3588 disk_avail < 5 GB | snapshot 比对 |
| audio_processor PID 974319 死 | preconditions 监测；若已死说明我们影响到了 |
| RKNN daemon PID 974370 死 | 同上 |
| 同一 milestone 连续失败 3 次 | iteration 自己记账 |

触发后：
- 写最后一份 `OVERNIGHT_REPORT_20260513.md`，说清在哪一步停的、为什么、有哪些数据
- 不再继续，安静退出 /loop

## Milestone 序列（self-paced）

每个 milestone 完成后**立刻**追加进度到 `~/rkllm-poc/logs/progress.md` 和 Mac `OVERNIGHT_REPORT_20260513.md` 草稿。**完成一个就先停下、写完报告、再决定要不要进下一个**。

### M1 — RKLLM SDK 下载部署（≤ 60 min）

- 拉 `airockchip/rknn-llm` 最新 release，含：
  - `librkllmrt.so`（runtime lib for aarch64）
  - `rkllm_server` 二进制（可选）
  - Python 绑定 `rkllm-toolkit-lite`（或 `rkllm-toolkit` 完整版）
  - examples 目录（看 demo 用法）
- 国内拉 GitHub release：`https://gh-proxy.com/https://github.com/airockchip/rknn-llm/...`
- 装到 `~/rkllm-poc/artifacts/rknn-llm-<ver>/`，**不进 /usr/lib**
- 测：`ldd ./librkllmrt.so` + 简单 import 验证

成功条件：3588 上 `python3 -c "import rkllm_lite"` 或 SDK 内 demo 能 import

### M2 — 找 Qwen 1.5B 预转 RKLLM 模型（≤ 60 min）

候选搜索：
- HuggingFace（Mac 中转）：`Qwen2.5-1.5B-Instruct-RKLLM`、`Qwen2-1.5B-rkllm`、`SmolLM2-1.7B-rkllm` 等
- ModelScope（3588 直拉）：搜 `rkllm`、`rknn-llm`
- airockchip 官方 demo 自带模型（rknn-llm release 里可能有 example.rkllm）
- 备选：Qwen2.5-0.5B（更小，必然能跑）

成功条件：3588 上 `~/rkllm-poc/artifacts/<model>/*.rkllm` 文件落地（~1-3GB）

### M3 — Smoke test (≤ 30 min)

跑 SDK 自带 demo / 任意 prompt：
- 加载模型耗时
- 一句问候 → 拿到任意 NPU 推理 response
- 看 NPU 负载（`cat /sys/kernel/debug/rknpu/load` 需 sudo）

成功条件：拿到非空 response（不在乎质量）

### M4 — Benchmark（≤ 60 min）

5-10 个不同长度 prompt：
- 短 prompt（"你好"）
- 中 prompt（30 char 中文）
- 长 prompt（200 char 中文意图分类 prompt）

测量每个：
- 加载时间
- 首 token 延迟（time to first token）
- token/s
- 内存占用峰值（`ps -o rss`）
- NPU 占用率

对比 baseline：3588 上 ollama qwen2.5-coder:1.5b CPU 同样 prompts

成功条件：3 组以上完整数据，写入 `progress.md` 表格

### M5 — Daemon 子进程 wrapper（≤ 60 min，可选）

参照 `scripts/templates/sensevoice_rknn_daemon.py` 模式写 `rkllm_daemon.py`：
- stdin: `{"prompt": "...", "max_tokens": N}`
- stdout: `{"text": "...", "first_token_ms": ms, "total_ms": ms, "tokens": N}`
- 保持模型常驻，避免每次 fork 加载

成功条件：5 句 prompt 经 daemon 跑出 5 句 response，平均延迟有数据

### M6 — Intent classification preview（≤ 60 min，可选）

3 句中文设备指令 prompt 模板（不入仓）：
```
prompt: 你是设备控制助手。从用户指令中提取 device + action + room。
       用户指令："关闭餐桌灯光"
       JSON 输出：
```
看 NPU 1.5B 模型能不能正确解析。

成功条件：3/3 正确或写 deviation 报告

### M7 — Final Report

写 `OVERNIGHT_REPORT_20260513.md`：
- 各 milestone 状态 + 数据
- NPU LLM 能否用于阶段 3 第 2 层漏斗 — 明确建议（是 / 否 / 部分）
- 失败链路（如有）+ 下一步如何走
- 资源占用真实数据，帮助阶段 3 设计

## 报告写在哪

- **3588 实时**：`~/rkllm-poc/logs/progress.md`（追加式，每 milestone 一段）
- **Mac 终稿**：`OVERNIGHT_REPORT_20260513.md`（repo 根目录，**不 commit**，明早 review）

文件示例结构：

```markdown
# 晚间报告 2026-05-13 (北京)

## 启动时间
20:00 / Mac iter 1 启动 / preconditions: 见 ~/rkllm-poc/PRECONDITIONS.yaml

## Milestone 1 RKLLM SDK 下载
状态: ✅
时长: 27 min
关键: github release v1.2.1 通过 gh-proxy.com 拉成功，librkllmrt 2.1.0
落点: ~/rkllm-poc/artifacts/rknn-llm-v1.2.1/

## Milestone 2 模型获取
...

## 最终结论
（NPU LLM 能 / 不能 / 部分能用于阶段 3 漏斗第 2 层，理由 + 数据 + 建议）
```

## /loop 启动姿势

新会话第一条 prompt 建议：

```
/loop 读 OVERNIGHT_HANDOFF.md 然后开始 NPU LLM 探索 milestone 1
```

每个 iteration 结束时调用 `ScheduleWakeup`（自我节奏）或 /loop dynamic mode，
delaySeconds 选 1800-3600（既等模型 load / NPU inference 也兼顾 prompt 缓存窗口）。
**别 sleep < 5 min**（浪费缓存窗口）。

## 启动检查清单（first iteration 时跑）

1. `cat OVERNIGHT_HANDOFF.md` — 完整读完本文
2. `cat NIGHT_REPORT_20260512.md` — 看白天进度
3. `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 'cat ~/rkllm-poc/PRECONDITIONS.yaml'` — baseline
4. `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 'test -f ~/rkllm-poc/STOP && echo abort || echo go'` — abort sentinel 检查
5. `SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 'pgrep -af venv/bin/python.*main\.py && pgrep -af sensevoice_rknn_daemon'` — av 系统活
6. 进入 M1。

## 早晨用户 review 流程

```bash
cd "/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"
cat OVERNIGHT_REPORT_20260513.md
# 决定：
#  - 数据/产物入仓？ → 我们一起 commit
#  - NPU LLM 路径开走？ → 阶段 3 新 sprint
#  - 失败转 CPU? → 也清楚下一步
```

3588 上也可以查：
```bash
ssh firefly@192.168.5.6 'cat ~/rkllm-poc/logs/progress.md'
ssh firefly@192.168.5.6 'cat ~/rkllm-poc/PRECONDITIONS.yaml'  # 前置
ssh firefly@192.168.5.6 'du -sh ~/rkllm-poc/'                 # 占地
```

## 紧急 abort

用户随时：

```bash
ssh firefly@192.168.5.6 'touch ~/rkllm-poc/STOP'
```

Loop 下次 iteration 检测到立即收尾退出。

## 联系（如果新会话遇到困惑要问用户）

- **不要**自作主张做超出本 mission 范围的事（修 av_unified_mvp、改 git、push、merge、动 demo 等）
- **可以**自主下载、安装、跑模型、benchmark、写 daemon、对比数据 — 这些都在 `~/rkllm-poc/` 内
- 遇到不可恢复错误：写完 partial report 退出，留给早晨 review。**不要重启 ASR processor / daemon 来"修复"问题**
