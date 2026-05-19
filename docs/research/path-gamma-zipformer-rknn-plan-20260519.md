# 路径 γ · streaming-zipformer RK3588 NPU（实验分支）

**分支**：`experiment/path-gamma-zipformer-rknn-spike`
**日期**：2026-05-19
**触发**：5/19 路径 β 失败 + δ 阶段 0 不过线（3-6w 自转工时不可接受）后，agent 推荐 ready-to-use 的 sherpa-onnx 现成 RK3588 NPU 流式模型。

---

## 隔离原则（沿用 δ 标准）

| 隔离层 | 措施 |
|---|---|
| **Git** | `experiment/path-gamma-zipformer-rknn-spike` 独立分支，不合主线直到 spike + integration prototype 完成 |
| **代码** | spike 阶段不动主线 runtime；integration prototype 在 `modules/audio_processor/` 加 **新 backend 文件**（不动 processor_arm.py / processor.py）|
| **runtime** | 3588 上 supervisor + funasr CPU 全程不动；γ spike 在独立 venv + 独立目录 |
| **venv** | 复用 `/home/firefly/spike_venv_20260518/`（已装 sherpa-onnx 1.13.2，γ 不需要新包）|
| **实验文件** | `/home/firefly/spike_venv_20260518/models/zipformer-streaming/` + `spike_zipformer_streaming.py` |

---

## 现成资源（β spike 验证存在）

| 资源 | 路径 | 大小估 | 来源 |
|---|---|---|---|
| `sherpa-onnx-rk3588-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2` | sherpa-onnx asr-models release | ~60-100MB | k2-fsa/sherpa-onnx GitHub release |
| `sherpa-onnx-rk3588-streaming-zipformer-small-bilingual-zh-en-2023-02-16.tar.bz2` | 同上 | 更小 | small 版备选 |
| sherpa-onnx 1.13.2 (aarch64) | spike_venv 已装 | 16.5MB wheel | 复用 |
| onnxruntime + rknpu provider | 同 sherpa-onnx 依赖 | — | 复用 |

**关键差异 vs β**：γ 的模型**是真正的 RK3588 NPU 资产**（β spike 实测确认存在），不是误描述。

---

## 已知实测数据（agent 调研 bonus）

sherpa-onnx issue #2515 社区实测：
- RK3588 NPU 占用 < 30%
- CPU 70%
- 整体仍是 NPU + CPU 混合，但 NPU 真用上了
- 准确率：bilingual 模型 vs 中文专攻模型理论上有损失，需要 spike 实测对比

---

## 阶段拆解

### 阶段 0 · spike（gating，1-2d）

**目标**：验证 ready-to-use 的 RK3588 streaming-zipformer 在我们场景下的 4 项指标：

1. **NPU 真上**（不退回 CPU）— 看 `cat /sys/kernel/debug/rknpu/load` 或 dmesg
2. **partial 间隔** ≤ 800ms（zipformer 流式常见 300-600ms）
3. **CER 对比 funasr CPU sensevoice**：用 5/19 user 测过的"沉默成本/原生家庭"长句，CER 退化 ≤ 15%
4. **audio_processor 预期 CPU**：bilingual 模型 + NPU 加速，预期 < 70%（比 funasr CPU 100% 改善）
5. **bilingual 中英混排**：路径 β 的英文插入幻听是否复现

**Gating 标准**：
- NPU 加载 > 0 ✅ 必须
- partial 600-800ms 内 ✅ 必须
- CER 退化 ≤ 15% ✅ 必须（否则用户体感降级太大）
- CPU < 70% ⚠️ nice-to-have（即使等于 funasr 也不浪费 NPU）
- 中英混排稳定 ⚠️ nice-to-have

**4/5 过线进阶段 1**；CER 退化 >15% → 停手记入 LESSONS_LEARNED；NPU 不加载 → 转评估 rknn provider bug 工作量。

**工时**：1-2d
**产出**：`docs/research/spike-zipformer-rknn-3588-20260519.md`

### 阶段 1 · integration prototype（仍在分支，2d）

spike 过线后：
- 新建 `modules/audio_processor/processor_zipformer_streaming.py`（仿 processor_arm.py 接口，跑 sherpa-onnx OnlineRecognizer with RKNN provider）
- 改 `modules/audio_processor/main.py` 加 backend 分支 `AV_ASR_BACKEND=zipformer_streaming`（与 sensevoice / RKNN 并存）
- 改 `scripts/3588-demo-start.sh` 增加 γ 启动选项
- **不部署到主线 runtime**，仍是分支测试

**工时**：2d

### 阶段 2 · 流式 partial protocol + dashboard（仍在分支，1d）

- partial 发送频率：每 600ms 触发一次 `av/audio/partial`
- 是否原生标点？zipformer-bilingual 大概率无 ITN → 仍需 punctuator 旁路（但 punctuator 当前只处理 final 不处理 partial，需评估是否要做 partial 也加标点）
- dashboard.js partial replace-by-revision 改动（同 β 计划 §阶段 4）

**工时**：1d

### 阶段 3 · 真音频回归 + PR 决策（0.5d）

- 3588 上分支启动 supervisor，mic 实测 30 分钟
- CER / NPU / CPU / 温度数据
- partial 体感（"逐字蹦"是否到位）
- 决定是否 PR 合主线 vs 保留分支作为可选 backend

**工时**：0.5d

---

## 总工时

| 阶段 | 工时 |
|---|---|
| 0. spike（gating）| 1-2d |
| 1. integration prototype | 2d |
| 2. protocol + dashboard | 1d |
| 3. 真音频回归 + PR | 0.5d |
| **合计** | **~4.5-5.5d** |

---

## 风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | bilingual zipformer 中文准确率 <<sensevoice | spike CER 对比直接看，过不了线就转回 funasr CPU |
| R2 | 无 ITN 标点，punctuator 链路仍需要 | 不算红线，punctuator 已稳定 |
| R3 | NPU + CPU 混合占用峰值超过 funasr CPU | spike 阶段实测决定 |
| R4 | sherpa-onnx RKNN provider 流式 bug（issue #2515 提到的 ~7% NPU 利用之类的） | spike 阶段直接观测 NPU load |

---

## 主要差异 vs δ

| 维度 | δ（已冻结）| γ（启动）|
|---|---|---|
| 模型获取 | 自转 PyTorch → ONNX → RKNN，3-6w | 现成下载即用，0d |
| 算子支持 | NonZero/Einsum/Range 三红线 | 模型已编译，无算子风险 |
| 工时 | ~3-6w | ~4.5-5.5d |
| 多语言 | 中文专攻 | 中英 bilingual |
| ITN 标点 | 模型原生 | 走 punctuator 旁路（与当前一致）|
| 成功概率 | 低（社区零先例）| 高（sherpa-onnx 一等公民 + issue #2515 实测）|

---

## 当前进度

- [x] 切实验分支 `experiment/path-gamma-zipformer-rknn-spike`
- [x] 实施大纲（本文档）
- [ ] 阶段 0 spike（**当前**）
- [ ] 阶段 1+ 等阶段 0 过线
