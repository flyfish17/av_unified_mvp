# 路径 δ · RKNN 自转 paraformer streaming（实验分支）

**分支**：`experiment/rknn-paraformer-streaming-self-port`
**日期**：2026-05-19
**触发**：5/19 路径 β spike 不过线（RK3588 NPU 上 paraformer-streaming 模型不存在）后，user 决定单独实验"自转 paraformer-streaming 到 RKNN"。

---

## 隔离原则（user 5/19 授权前提）

> "前提是不影响当前功能代码；给你最大授权进行"

| 隔离层 | 措施 |
|---|---|
| **Git** | 独立分支 `experiment/rknn-paraformer-streaming-self-port`，不合并主线直到验证可行 |
| **代码** | 不动 `modules/audio_processor/processor_arm.py` / `main.py` / 任何主线 runtime 代码 |
| **runtime** | 3588 上 supervisor + funasr CPU 路径**全程不动**，实验在独立目录跑 |
| **venv** | 不动 `creator_ai_demo/venv` / `spike_venv_20260518`；δ 用独立 venv `/home/firefly/delta_venv_20260519/`（rknn-toolkit 装这里）|
| **3588 文件** | 实验文件统一放 `/home/firefly/delta_experiment/`，与生产路径完全隔离 |
| **回滚** | 分支废弃 → 主线零影响；3588 实验文件可独立删除 |

---

## 阶段拆解

### 阶段 0 · 可行性调研（gating）

**目标**：确定 rknn-toolkit + FunASR paraformer-streaming 转换是否技术可行 + 工时估算更准确。

**调研项**：
1. **rknn-toolkit 支持度**：rknn-toolkit2 当前版本（2.3.2 已在 SenseVoiceSmall-RKNN2 用过）是否支持 paraformer 用的核心算子（FSMN / Multi-head Self-Attention / LayerNorm 等）
2. **社区先例**：是否有人成功转过 FunASR paraformer 系列模型到 RKNN？GitHub issue / 中文社区帖子核查
3. **paraformer-streaming PyTorch 模型可获取性**：FunASR 是否公开 streaming 子集的 PyTorch checkpoint（不只是 ONNX/ ModelScope SavedModel）
4. **量化复杂度**：rknn-toolkit 需要量化校准数据集（int8 PTQ）。预估校准复杂度 + 准确率损失风险
5. **动态 shape 处理**：streaming 模型的 chunk-based 输入是变长 vs RKNN 是 static shape — 怎么处理？（参考 SenseVoiceSmall-RKNN2 的 RKNN_INPUT_LEN=171 pad 模式）
6. **替代方案比对**：路径 γ（sherpa-onnx 内置 streaming-zipformer-bilingual RK3588 NPU）已经是 ready-to-use，准确率主观对比缺数据。是否值得**先 spike γ** 而非自转 δ？

**Gating 标准**：
- rknn-toolkit 支持 paraformer 核心算子 ≥ 80%（缺失算子 ≤ 2 个且有 fallback 方案）
- 有 ≥ 1 个社区成功先例（或 happyme531 类高质量未公开 fork）
- PyTorch checkpoint 公开可下载
- 整体工时估算修正后 ≤ 2w（如 >2w 应转向路径 γ 或放弃）

**工时**：0.5-1d（agent 主导调研，read-only）
**产出**：`docs/research/path-delta-rknn-paraformer-feasibility-20260519.md`

### 阶段 1 · 工具链 setup（gating 后）

- 3588 上 `python3 -m venv /home/firefly/delta_venv_20260519/`
- 装 rknn-toolkit2 + torch + funasr（实验 venv，不污染 creator_ai_demo/venv）
- 验证 rknn-toolkit 基本 demo（如 mobilenet 转换示例）能跑

**工时**：0.5d

### 阶段 2 · 模型获取 + ONNX 中间格式导出

- 从 FunASR / ModelScope 拉 paraformer-streaming PyTorch checkpoint
- PyTorch → ONNX 导出（已有标准流程）
- ONNX 验证：CPU onnxruntime 跑通流式推理

**工时**：1-2d

### 阶段 3 · ONNX → RKNN 转换 + 量化

- 准备量化校准数据集（用 av_unified_mvp 5/19 真音频 PCM 缓冲？或公开数据 AISHELL-1 子集）
- rknn-toolkit ONNX 加载 + int8 PTQ
- 算子兼容性问题逐个解决（如 attention 子图替换、layernorm 实现等）
- 转 RKNN model + 验证 shape

**工时**：3-5d（最大不确定项）

### 阶段 4 · 3588 NPU 流式推理 wrapper

- 仿 sherpa-onnx OnlineRecognizer 写 Python wrapper（输入 chunk + cache → 输出 partial text）
- 处理 streaming 模型的 attention state cache + chunk overlap
- 准确率对比：用 sensevoice CPU final 作为 golden，新模型 partial 收敛到 final 后对比

**工时**：2-3d

### 阶段 5 · integration prototype（仍在实验分支）

- 写 `experiment/processor_paraformer_rknn.py` （独立文件，不进 modules/）
- 仿 processor_arm 接口跑端到端 mic→partial→final
- 与主线 punctuator + dashboard 链路兼容性验证

**工时**：1-2d

### 阶段 6 · 主线 merge 决策

- 数据齐全后 PR review
- 通过 → 合入 sprint 主线作为新 backend（与 sensevoice CPU 并存，env 切换）
- 不通过 → 分支保留作历史，记入 LESSONS_LEARNED

**工时**：0.5d

---

## 总工时

| 阶段 | 工时 |
|---|---|
| 0. 可行性调研 | 0.5-1d |
| 1. 工具链 setup | 0.5d |
| 2. ONNX 中间格式 | 1-2d |
| 3. RKNN 转换 + 量化 | **3-5d**（最大不确定）|
| 4. 流式推理 wrapper | 2-3d |
| 5. integration prototype | 1-2d |
| 6. merge 决策 | 0.5d |
| **合计** | **~8.5-14d**（~2 周）|

---

## 主要风险

| # | 风险 | 缓解 |
|---|---|---|
| R1 | rknn-toolkit 不支持 paraformer 关键算子 | 阶段 0 gating；不过则转路径 γ |
| R2 | 量化精度损失大（int8 vs fp32 准确率掉 10%+）| 量化校准数据增量、混合精度（关键层保 fp16）|
| R3 | streaming 动态 shape 无法表达为 static RKNN | pad + 多 shape 输入，仿 SenseVoiceSmall-RKNN2 模式 |
| R4 | NPU 加速比不如预期（< 3x CPU）| 实测后再决定是否值得 |
| R5 | 工时超 2w 无产出 | 阶段 3 卡 1w 强制 review，转向路径 γ 或放弃 |

---

## 与主线接口

实验**完全独立**：
- 3588 上的 `audio_processor` 仍跑 funasr CPU sensevoice（v1.1-funasr-cpu-stable）
- δ 实验跑在 `/home/firefly/delta_experiment/`，独立 mic 测试或离线 wav 文件
- 不通过 MQTT 接入主线（避免污染 transcript / partial topic）
- 验证完毕后再走"主线集成"流程（阶段 5/6）

---

## 当前进度

- [x] 切实验分支 `experiment/rknn-paraformer-streaming-self-port`
- [x] 实施大纲（本文档）
- [ ] 阶段 0 可行性调研（**当前**）
- [ ] 阶段 1+ 等阶段 0 过线再启
