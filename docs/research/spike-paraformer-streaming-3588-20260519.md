# spike · sherpa-onnx paraformer-streaming on RK3588 (路径 β 阶段 0 gating)

**日期**：2026-05-19
**性质**：实测 spike 报告（gating，不进阶段 1 前提条件）
**结论**：**❌ 不过线 — 三项核心 gating 失守，路径 β 应停在阶段 0**
**前置文档**：`docs/research/path-beta-paraformer-streaming-plan-20260519.md`

---

## TL;DR

1. **RK3588 NPU 版的 paraformer-streaming 不存在**。sherpa-onnx GitHub `asr-models` release 中所有 `sherpa-onnx-rk3588-paraformer-zh-*` 资产全是 **offline 固定窗口**（5s/10s/15s/20s/25s/30s），无 streaming 变体。唯一的 RK3588 streaming 中文 ASR 是 zipformer-bilingual（非 paraformer，且无 ITN）。5/18 P0.8 调研报告中"sherpa-onnx-rk3588-paraformer-zh-streaming-2025-10-07"**经核实并不存在**。
2. **回退到 CPU paraformer-streaming-bilingual-zh-en**：partial 600ms 工作正常，但 **NPU 0%**、**单核 CPU 30-60%**（threads=2）/ 84-118%（threads=4，吃 >1 核）、**无原生 ITN 标点**。
3. **承诺 vs 实测**：
   - "RK3588 NPU 跑 paraformer" → ❌ 模型不存在
   - "audio_processor CPU < 10%（3-5x NPU 加速）" → ❌ 仍是 CPU 推理，30%+ 单核
   - "模型原生输出标点（不需要 punctuator 旁路）" → ❌ paraformer-streaming-bilingual 不输出标点
4. **唯一过线项**：partial 间隔中位 ~600ms（符合 sherpa-onnx 文档），但这是单点过线，**不足以触发阶段 1**。

**建议**：放弃路径 β（paraformer-streaming），坚持当前 funasr CPU 路径 + 已稳态的 punctuator 旁路。如需更高级的 NPU 利用，单独评估路径 γ：RKNN 自转 paraformer streaming（成本 >1w 工时，超出本 sprint 范围）。

---

## 1. 模型来源核查（驳斥 5/18 P0.8 调研）

通过 GitHub API 取 `k2-fsa/sherpa-onnx` 的 `asr-models` release，**461** 个 asset，过滤 `rk3588` + `paraformer`：

| Asset | 时长上限 | 类型 |
|---|---|---|
| `sherpa-onnx-rk3588-5-seconds-paraformer-zh-2025-10-07.tar.bz2` | 5s | offline fixed-window |
| `sherpa-onnx-rk3588-10-seconds-paraformer-zh-2025-10-07.tar.bz2` | 10s | offline fixed-window |
| `sherpa-onnx-rk3588-15-seconds-paraformer-zh-2025-10-07.tar.bz2` | 15s | offline fixed-window |
| `sherpa-onnx-rk3588-20-seconds-paraformer-zh-2025-10-07.tar.bz2` | 20s | offline fixed-window |
| `sherpa-onnx-rk3588-25-seconds-paraformer-zh-2025-10-07.tar.bz2` | 25s | offline fixed-window |
| `sherpa-onnx-rk3588-30-seconds-paraformer-zh-2025-10-07.tar.bz2` | 30s | offline fixed-window |
| `sherpa-onnx-rk3588-{N}-seconds-paraformer-zh-2023-03-28.tar.bz2` | 5/10/.../30s | 旧版 offline |

**关键**：全部是 `N-seconds`（固定窗口，offline），**无 streaming 资产**。

`rk3588` + `streaming` 过滤命中 2 个：
- `sherpa-onnx-rk3588-streaming-zipformer-small-bilingual-zh-en-2023-02-16.tar.bz2`
- `sherpa-onnx-rk3588-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2`

→ RK3588 NPU 上的 streaming 中文 ASR **只有 zipformer**，不是 paraformer，且 zipformer-bilingual 也不带 ITN。

**结论**：5/18 P0.8 调研报告 §2 "sherpa-onnx-paraformer-zh-streaming RK3588 预编译模型"是**错误描述**（混淆了 `N-seconds offline` 与 `streaming` 两种模型类别）。

按本 spike 指令第 1 条 fallback：用 CPU `sherpa-onnx-streaming-paraformer-bilingual-zh-en`（onnxruntime CPU provider）验证流式逻辑。

---

## 2. 实测环境

| 维度 | 值 |
|---|---|
| 设备 | firefly@192.168.5.6（RK3588，Ubuntu 22.04，6.1.118 kernel）|
| 推理 venv | `/home/firefly/spike_venv_20260518/`（sherpa-onnx 1.13.2）|
| 模型路径 | `/home/firefly/spike_venv_20260518/models/sherpa-onnx-streaming-paraformer-bilingual-zh-en/` |
| 模型大小 | encoder.int8.onnx 158MB + decoder.int8.onnx 68MB |
| spike 脚本 | `/home/firefly/spike_venv_20260518/spike_paraformer_streaming.py` |
| 下载链路 | `ghfast.top` 镜像，1.05GB tarball ~3.5MB/s |
| 主仓状态 | supervisor 在跑（funasr CPU + video + punctuator），未中断 |

测试音频：
- `sherpa_test_wavs/zh.wav`（5.59s，短句）
- 官方 `test_wavs/0.wav`（10.05s，中英混）
- `/tmp/aishell_30s.wav`（ffmpeg 从 aishell4 切 30s 长样）

⚠️ user 5/19 实测的"沉默成本/原生家庭"音频未在 3588 上留存（funasr CPU 路径不落盘），无法做精确文本对比；改用上述公开音频做主观质量评估。

---

## 3. Gating 实测数据

### 3.1 partial 间隔 — ✅ 过线

| 样本 | 时长 | partial 数 | gap 中位 | gap max | gap 含义 |
|---|---|---|---|---|---|
| zh.wav | 5.59s | 7 | **591ms** | 626ms | 单段连续 |
| test_wavs/0.wav | 10.05s | 12 | **599ms** | 1241ms | 单段含中英混 |
| aishell_30s.wav | 30.0s | 35 | **614ms** | 4185ms | 3 段（endpoint reset 后首 partial 慢）|

**判定**：中位 591-614ms，符合 sherpa-onnx 文档 600ms 设计点。max 跳变都发生在 endpoint reset 之后的 first-partial 等待（含 ~1.2-1.5s 静音判定）— 这是正常 streaming 行为。

### 3.2 NPU 加载 — ❌ 不过线（决定性）

NPU 监控：`sudo -n cat /sys/kernel/debug/rknpu/load`（80 个 2s 间隔样本，覆盖 spike 全程）。

```
Core0:  0%, Core1:  0%, Core2:  0%   ← 全程不变
```

CPU paraformer-streaming **完全不使用 NPU**。这与 spike 假设、路径 β 计划"NPU 利用 0% → ✅"目标的**核心承诺直接冲突**。

### 3.3 audio_processor 预期 CPU% — ❌ 不过线

| 配置 | CPU 中位 (%) | CPU max (%) | 备注 |
|---|---|---|---|
| threads=2，zh.wav | 31.9 | 49.9 | 单核内 |
| threads=2，test_wavs/0.wav | 39.9 | 63.9 | 单核内 |
| threads=2，aishell_30s.wav | 37.9 | 57.9 | 单核内 |
| threads=4，zh.wav | **83.8** | **117.8** | 吃 >1 核 |

CPU 数据是 spike 单一进程的 `/proc/self/stat` 采样（与主仓 funasr 主进程隔离）。

对照 gating 目标 "audio_processor 预期 CPU < 30%（3-5x NPU 加速）"：
- 实测 30-60%（threads=2），最差 case 触线
- threads=4 直接突破 100%（多核没线性加速，ONNX 单 session 限制）
- **没有 NPU 加速来源**：CPU 占用只能维持在 ~30% 单核水平

对照当前 funasr CPU 路径（audio_processor 96% 单核）：paraformer-streaming CPU 32-40% 是改善（~2.5x），但**远未达到 NPU 加速预期的 <10%**。

### 3.4 中文准确率主观对比 — ❌ 不过线

**示例 1**（zh.wav，期望"开放时间早上九点至下午五点"）：
```
final: "菜放时间早上九点至下午五点"
       ^^^ 首字识别错（"菜放" vs "开放"）
       *** 没有标点
```

**示例 2**（test_wavs/0.wav，中英混）：
```
final: "昨天是 monday today day is 礼拜二 the day after tomorrow 是星期三"
                    ^^^^^^^^^ 插入重复"today day"
```

**示例 3**（aishell_30s.wav，幼儿园讲话）：
```
"零零幺一会儿叫一校长..."        ← "0011 给一个 1010 教师..."（数字串识别 OK）
"...重新的的开一次会..."         ← "重新的的" 字重复
"...大半年也呃快过去了..."       ← 插入语气词"呃"
全程无标点、无句号、无顿号
```

对照 sensevoice ARM（5/14 同测试 wav）：
- 准确率明显更高，无 hallucination 插入
- sensevoice ARM 有 ITN 标点

**判定**：paraformer-streaming-bilingual 准确率**低于** sensevoice ARM，不满足"不低于 sensevoice 90%"的 gating。**且无 ITN 标点**，破坏了路径 β"原生标点 / 不需要 punctuator 旁路"的核心卖点。

### 3.5 其它观察

| 维度 | 数据 |
|---|---|
| RTF（30s 样）| 1.006 — 几乎实时打平，无富余 |
| 内存 RSS peak | 330-374 MB |
| decode call RTT | 中位 73-112ms，max 169ms — 单 chunk 推理 100ms 级 |
| endpoint detection | 工作正常，VAD 内置触发 final |
| first-partial latency | 1.3-1.9s（chunk size 10 + lookahead 帧累积，符合 sherpa-onnx 文档）|

---

## 4. Gating 判定汇总

| # | gating 项 | 目标 | 实测 | 判定 |
|---|---|---|---|---|
| 1 | partial 间隔 | ≤ 800ms（接近 600ms）| 591-614ms 中位 | ✅ |
| 2 | 中文准确率 | 不低于 sensevoice 90% | 低于 sensevoice，含 hallucination + 无标点 | ❌ |
| 3 | NPU 加载 > 0 | 走 NPU 不退回 CPU | 全程 0%（模型本身不存在 NPU 版）| ❌ |
| 4 | audio_processor 预期 CPU | < 30% | 30-60%（threads=2），> 100%（threads=4）| ❌ |

**4 项 gating，1 过 3 失**。

**最终判定：❌ 不过线**。

---

## 5. 推荐下一步

**主推荐：放弃路径 β（paraformer-streaming）。**

理由：
1. 路径 β 的**核心价值假设**（NPU 利用 + CPU < 10% + 原生 ITN）**全部失守**。
2. 唯一过线项（partial 600ms）可在 **funasr CPU 2pass-online 路径**中通过调参达成（5/19 早上 funasr CPU 路径已稳态，且 user 已验证"丢字消失"）。
3. 当前 funasr CPU + punctuator 旁路链路已稳态，无理由为单一 partial 节奏（且降级了准确率 + 标点）破坏稳态。

**备选方案**（不推荐立即上）：

- **路径 γ：自转 paraformer-streaming → RKNN**（rknn-toolkit2，需 PyTorch checkpoint 转 RKNN op；模型作者社区暂无 streaming 版的 NPU port 公开案例）。工时 >1w，本 sprint 不启动。
- **路径 δ：streaming-zipformer-bilingual-zh-en RK3588（NPU）**。已有 RK3588 预编译。trade-off：(a) zipformer 非 paraformer，无 ITN；(b) 中文准确率需另行实测。如要 NPU 利用 + partial 节奏，可单开新 spike 评估；本次 spike 不做。
- **路径 ε：funasr 2pass-online**（CPU 路径加 partial 节奏）。改 audio_processor 现有 funasr 配置，让其内部 2pass 实时输出 partial。零外加依赖，零模型替换。最低风险。**最可能的实际落点**。

---

## 6. spike 副产物

留在 3588 的资源（user 后续可复用）：
- `/home/firefly/spike_venv_20260518/spike_paraformer_streaming.py` — 流式 spike 脚本（含 partial gap / RTF / CPU% / RSS / NPU-friendly 模板）
- `/home/firefly/spike_venv_20260518/models/sherpa-onnx-streaming-paraformer-bilingual-zh-en/` — 模型文件（226MB int8 主用 + 864MB fp32 备份）。如确认放弃路径 β，可 `rm -rf` 释放 ~1GB。
- `/tmp/aishell_30s.wav` — 30s 中文长样

无任何主仓代码改动，audio_processor / video_processor / supervisor / punctuator 进程未受影响（全程 spike 走独立 spike_venv 进程）。

---

## 7. 红线遵守自检

- ✅ 未动 `creator_ai_demo/venv`（spike 完全在 `spike_venv_20260518`）
- ✅ 未动 audio_processor / processor_arm.py / supervisor
- ✅ 未杀任何当前进程（supervisor 一直在跑 funasr CPU）
- ✅ destructive 操作仅 `rm paraformer-streaming.tar.bz2`（自有下载副本，无业务影响）
