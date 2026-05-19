# 路径 δ · RKNN 自转 paraformer-streaming 可行性调研

**分支**：`experiment/rknn-paraformer-streaming-self-port`
**日期**：2026-05-19
**状态**：阶段 0 调研产出（纯 read-only，无代码/无装包/无 SSH）
**对应 plan**：`docs/research/path-delta-rknn-paraformer-streaming-plan-20260519.md`

---

## TL;DR

**结论：不建议立即推进路径 δ。Gating 4 项中 3 项不过线。**

| 维度 | 判定 |
|---|---|
| **rknn-toolkit2 算子支持** | **部分支持但有红线缺失** — NonZero/Einsum/Range 等 paraformer-streaming 必用算子明确 "Not Supported" |
| **社区先例** | **无成功先例** — FunASR issue #2286（2024-12 至 2026-05 仍 open）一年半多个开发者尝试，无一成功；happyme531 只做了 SenseVoice/F5-TTS，未触碰 paraformer |
| **PyTorch checkpoint 可获取** | **可获取**（funasr/paraformer-zh-streaming on HF + ModelScope iic 同款）— 唯一过线项 |
| **量化 + 动态 shape** | **复杂度极高** — Transformer PTQ int8 在 W8A8 下精度退化大；streaming chunk + KV cache 与 RKNN static shape 模式冲突 |

**工时修正估算**：从 plan 原 ~8.5-14d 修正为 **~3-6w（pessimistic）/ ≥2w 必触发阶段 3 强制 review**。NonZero 移除 + Range 重写 + 多 sub-model 拆分这种工作量，外加 PTQ 精度调优，远超原估。

**路径推荐**：
1. **优先 spike 路径 γ（sherpa-onnx 内置 rk3588-streaming-zipformer-bilingual-zh-en-2023-02-20）**，48h 内能拿到端到端 NPU partial 数据。**γ 是即用资产，δ 是研究项目，不在一个量级。**
2. **δ 暂保留实验分支不删，但降级为"长尾研究项"**，待 γ 实测有明确精度短板（如中文 CER 对比 sensevoice 退化 > 15%）才回头投入。
3. 即使 γ 实测可用，**δ 仍可作为"是否能拿掉 sensevoice CPU 路径，让 3588 在 NPU 跑 full streaming"的可选项**——但这是 v2 议题，不是本 sprint 议题。

---

## 6 个问题逐项答

### 1. rknn-toolkit2 算子支持度

**答：部分支持，但有红线缺失。**

参照 `rknn-toolkit2/doc/RKNNToolKit2_OP_Support-2.3.2.md`（最新 v2.3.2，airockchip 维护 fork）：

**Paraformer / paraformer-streaming 用到的算子对照**：

| 算子 | RKNN 2.3.2 状态 | 影响 |
|---|---|---|
| LayerNormalization | Supported | OK |
| MatMul / Gemm | Supported | OK |
| Conv (subsampling) | Supported | OK |
| Softmax | **batchsize: 1** 限制 | OK（推理 bs=1）|
| Slice | **batchsize: 1** 限制 | OK |
| Gather / Reshape / Transpose / Concat / Where / Sub / Add / Mul / Sqrt / Sigmoid / Tanh / Erf | Supported | OK |
| **NonZero** | **Not Supported** | **红线** — FunASR paraformer 已知出现（issue #2286）|
| **Einsum** | **Not Supported** | **红线** — transformer attention 常用，需手工 unfold 成 MatMul+Reshape |
| **Range** | **Not Supported** | **红线** — sequence/positional 生成常用，需常量化（rknn-toolkit2 issue #136 维护者 zen-xingle 明确 "please remove /Range op first"）|
| GroupNormalization | Not Supported | 影响小（paraformer 用 LN）|
| GatherND / ScatterElements / TopK / Reciprocal / ReduceL2 / Loop | Not Supported | 看导出图是否触发 |
| GRU | batchsize 1 only | FSMN 不依赖 GRU，OK |
| 动态 shape 输入 | 支持 multi-fix-shape（不是真动态）| 见 Q5 |

**Multi-Head Attention with cache**：RKNN 没有原生 MHA 算子，依赖底层 MatMul+Softmax+Reshape 实现。理论上能 expand 成基础算子，但 cache state 输入是 streaming 模型的核心难点（Q5 详）。

**FSMN layer**：FSMN 本质是 1-D conv + 残差，Conv1D 支持 OK。但 FunASR paraformer-streaming 实际还混入大量 transformer encoder（cif + attention decoder），不只是 FSMN。

**Decoder（CIF + cross-attention + linear projection）**：cif 用到累加 + 临界值判断 + masked select 类操作，**这正是 NonZero 触发的高危区**。

**结论**：核心矩阵运算算子全 OK，但 ASR 流式专用图结构（Range 生成 position id、NonZero 做 mask 提取、Einsum 做 attention）至少 3 个红线算子，必须改写 ONNX graph 才能跑。
**Gating 标准（缺失算子 ≤ 2 个且有 fallback）**：**不过线**（3 个红线 + decoder 子图重写复杂度未知）。

参考：
- `RKNNToolKit2_OP_Support-2.3.2.md`（已存 /tmp/rknn_op_support.md，HTTP 200，518 行）
- airockchip/rknn-toolkit2 issue #136 (Kracozebr 2024-08, zen-xingle 回复 "remove /Range op")
- modelscope/FunASR issue #2286 (lpu-bash 2025-09-25 报 NonZero 错误)

---

### 2. 社区先例

**答：无成功先例。**

**核心证据 — modelscope/FunASR issue #2286**（rk3588 部署 paraformer-zh-streaming + ct-punc + fsmn-vad）：
- 2024-12 开题（@happywch）→ 2026-05 仍 open
- 7 个评论，5 名独立开发者参与（baichuan1997、ggbsaber、lqx-all、lpu-bash、yowrhihoil）
- 全部卡在两个问题：(1) 动态输入 shape 怎么处理；(2) NonZero / Range 等不支持算子
- 2025-09 @lpu-bash 报错 `ValueError: The input 0 of NonZero('/NonZero') need to be constant!`
- 2026-05-12 @lpu-bash 最后一条："没有，没解决"

**核心证据 — modelscope/FunASR issue #2292**（FSMN-VAD on RK3588）：
- 2024-12 开题，转换报 `feats_length` 动态维度错误
- 唯一回复（@DakeQQ 2024-12-18）建议改用 `DakeQQ/Voice-Activity-Detection-VAD-ONNX` 端到端 ONNX 实现 — 说明连相对简单的 FSMN-VAD 都没人在 funasr 原图上跑通 RKNN

**happyme531（业界最知名 RK3588 移植者）**：HF 主页有 SenseVoiceSmall-RKNN2、F5-TTS-RKNN2、Stable-Diffusion-1.5-LCM、Florence-2 等，**没有 paraformer-rknn 仓库**。
- SenseVoice 的转换路径是 `lovemefan/SenseVoice-onnx` → RKNN（**起点是别人导好的 ONNX，不是 PyTorch ckpt**）
- SenseVoice 是 offline 整段输入（README 明确 "20 秒每秒"），不解决 streaming 难题

**csukuangfj/sherpa-onnx-rknn-models**（k2-fsa 官方维护的 RK3588 NPU 模型仓库）：
- streaming-asr/ 目录共 15 个文件，**全部是 zipformer**（rk3562/66/68/76/88 × {bilingual, en, small-bilingual}）
- 没有任何 streaming-paraformer-rknn 资产
- k2-fsa 团队会做却没做，最直接的市场信号

**Gating 标准（≥ 1 个社区成功先例）**：**不过线**。

参考：
- modelscope/FunASR#2286（/tmp/funasr_2286.json + comments）
- modelscope/FunASR#2292
- huggingface.co/csukuangfj/sherpa-onnx-rknn-models/tree/main/streaming-asr
- huggingface.co/happyme531

---

### 3. PyTorch checkpoint 可获取性

**答：可获取。**

- **HuggingFace**：`funasr/paraformer-zh-streaming`（功能镜像，PyTorch ckpt + config + tokens）
- **ModelScope**：`iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online`（damo 原始发布，PyTorch checkpoint，FunASR 直接加载）
- **FunASR 官方导出工具**：`funasr-export ++model=paraformer ++quantize=false` 可从 PyTorch 导出 ONNX（已被 funasr-onnx pip 包包装）

**注意**：FunASR streaming 子集和 offline 子集是不同模型（`-online` 后缀 vs `-pytorch` 后缀），streaming 版用了 chunk + look-ahead 的特殊训练配置。

**Gating 标准（PyTorch checkpoint 公开可下载）**：**过线**。

参考：
- huggingface.co/funasr/paraformer-zh-streaming
- modelscope/FunASR/wiki/paraformer
- pypi.org/project/funasr-onnx/

---

### 4. 量化复杂度与精度损失

**答：精度风险显著，且无可对照基准数据。**

**rknn-toolkit2 量化模式**：
- 默认 int8 PTQ（需要 dataset.txt 校准数据集）
- 支持 fp16（NPU 原生），但 happyme531 SenseVoice README 提示 fp16 推理有溢出 → 需在模型内插 scaling op
- 支持混合精度（hybrid_quantization API），但需要手工标记敏感层

**Transformer 系 ASR 量化精度参考**：
- arxiv 2103.16827（Integer-only Zero-shot Quantization for Efficient Speech Recognition）：QuartzNet/Conformer 等 INT8 WER 退化 < 1%，但前提是用了 outlier-aware 校准
- arxiv 2603.04308（Activation Outliers in Transformer Quantization）：W8A8 朴素 PTQ 对 transformer attention 退化显著，需要 SmoothQuant 类预处理
- happyme531 SenseVoice：**README 不公布 CER 数据**，仅有"20× 实时"性能指标 — 业界普遍现象，说明精度数据要么作者也没系统测、要么不好看

**Paraformer 特有风险**：
- CIF (Continuous Integrate-and-Fire) 模块用累加 + 阈值切分，对量化噪声特别敏感（连续累计的小 error 会跨 chunk 漂移）
- Streaming 版有 cache state，量化误差会跨 chunk 累积 — 比 offline 模型更脆弱

**Gating 无明确标准，但参考 plan §R2（int8 vs fp32 准确率掉 10%+）**：**风险高且不可预知**，最差情况需要 fp16 + 校准数据集迭代 1-2 周。

参考：
- happyme531/SenseVoiceSmall-RKNN2 README（fp16 推理 + 模型内 scaling）
- arxiv 2603.04308, 2103.16827

---

### 5. 动态 shape 问题

**答：可解但工程复杂度极高。**

**RKNN 的 "动态 shape" 真相**：
- 不是 PyTorch/ONNX 那种真正动态维度
- 是 multi-fix-shape — 预先列出 N 个固定 shape，运行时选最接近的
- 例：`dynamic_input=[[[1,300,80], [1]], [[1,400,80], [1]], [[1,500,80], [1]]]` —— 3 个候选

**streaming 模型的两个动态维度**：
- **chunk 输入长度**：通常固定（60ms / 600ms / 1.2s chunk），可枚举 1-2 个 shape
- **cache state shape**：transformer 的 KV cache 是 `[layers, heads, seq_len, head_dim]`，**seq_len 随 chunk index 单调增长**，这无法 multi-fix-shape 表达

**解决方案**（参考 sherpa-onnx 内置 zipformer-rk3588 的做法）：
- **拆 model**：encoder 跑 NPU（chunk 输入 + 固定 cache shape），decoder + joiner 跑 CPU
- **cache 固定 max_len + 滑窗**：cache state 永远是 max_len，超出部分滑窗丢弃（不是真增长）
- **外部 Python wrapper 管理 cache**

工程开销估算：
- 拆 model（encoder/decoder/joiner）：1-2d
- cache 滑窗逻辑设计 + 验证：2-3d
- 多 sub-model rknn build + runtime 串接：1-2d
- 与 funasr 原 streaming 数据流对齐验证：2-3d

**Gating 无明确标准**，参照 plan §阶段 3+4 估计：原 5-8d，**修正后 8-12d**（NonZero/Range 还要叠加 graph 改写）。

参考：
- rknpu2/doc/RKNN_Dynamic_Shape_Usage.md
- airockchip/rknn-toolkit2 issue #136
- sherpa-onnx 拆 encoder/decoder/joiner 的做法（k2-fsa repo）

---

### 6. 替代评估：路径 γ vs δ

**答：γ 是即用资产，δ 是研究项目，差一个量级。如果 γ 实测可用，δ 失去近期价值。**

**γ 优势（sherpa-onnx-rk3588-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2）**：
- 129 MB，**已经是 RKNN 格式**，下载即用
- k2-fsa csukuangfj 长期维护，2026 仍在更新
- sherpa-onnx C++ runtime + Python binding 已经成熟（不用我们写流式 wrapper）
- 双语 zh-en，正好覆盖 av_unified_mvp 中英混合场景

**γ 已知短板（sherpa-onnx issue #2515 实测数据）**：
- @yushanyong 2025-08 实测：用 NPU 跑 sherpa-onnx streaming-zipformer-bilingual，CPU 利用率 70%+，NPU 单核利用率 < 30%
- 维护者 csukuangfj 评论："cpu利用率还是太高了" — 暗示 NPU offload 不充分
- 即便如此，**比纯 CPU 跑（CPU 100%+）已节省大量算力**，对 3588 多任务有意义

**zipformer vs paraformer 准确率对比**：
- 中文 ASR：paraformer-large 在 AISHELL/wenetspeech 上 SOTA 之一（CER ~3-5%）
- zipformer-bilingual-zh-en：sherpa-onnx 社区使用广，CER 数据未公开严格基准，但用户反馈"够用"
- **没有直接论文/评测做 paraformer vs zipformer in RK3588 NPU 的对比** — 这本身就是 γ spike 阶段应实测的数据

**关键问题：γ 实测可用 → δ 是否还有意义？**

- **本 sprint 内**：γ 满足 → δ 应**冻结**，避免在不必要的研究上花 2-6w
- **长期**：如果 γ 实测在中文场景 CER 退化 > 15%（相对 sensevoice 当前 CPU 基线），δ 的"自转 paraformer"价值才回来 — 但那时也应优先看 happyme531 类边缘移植圈有没有新产出（半年内 ecosystem 进展快）

参考：
- sherpa-onnx issue #2515（NPU 实测 utilization）
- huggingface.co/csukuangfj/sherpa-onnx-rknn-models/tree/main/streaming-asr

---

## 综合判定（4 项 Gating）

| Gating | 标准 | 结果 |
|---|---|---|
| 1. 算子支持 | 缺失 ≤ 2 且有 fallback | **不过线**（NonZero + Einsum + Range 3 个红线，且 fallback 是 graph 重写工作量大）|
| 2. 社区成功先例 | ≥ 1 个 | **不过线**（FunASR #2286 一年半零成功）|
| 3. PyTorch ckpt 可获取 | 公开可下载 | **过线** |
| 4. 工时修正 ≤ 2w | 工时估算 ≤ 2w | **不过线**（修正为 3-6w）|

**4 项中 1 项过线，3 项不过线 → 阶段 0 gating 不通过。**

---

## 推荐下一步

1. **本周（5/19-5/25）立即 spike 路径 γ**
   - 拉 `sherpa-onnx-rk3588-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2` 到 3588
   - 在 `/home/firefly/gamma_spike_20260519/` 独立目录跑端到端 mic→partial→final
   - 主线 audio_processor 不动，只验证准确率 + CPU/NPU 资源占用
   - 工时 1-2d
   - 与当前 sensevoice CPU baseline 做 CER 对比（≥ 30 句样本）

2. **路径 δ 实验分支保留但冻结**
   - `experiment/rknn-paraformer-streaming-self-port` 不删，本调研报告作为冻结时点的认知锚
   - 触发解冻条件：(a) γ CER 退化 > 15% 或不可用；或 (b) 半年内社区出现 paraformer-RKNN 成功先例

3. **如果 γ 实测不达标**，再考虑 δ 之前先评估：
   - 路径 ε：jetson 5.0 nano（已有支线 prompt，CUDA 生态成熟，paraformer-streaming 原生跑得动）
   - 路径 ζ：3588 CPU 继续跑 sensevoice，调优 chunk + idle 参数压榨剩余算力

---

## 附：本调研所引证据来源

| 文件 / URL | 用途 |
|---|---|
| `https://github.com/airockchip/rknn-toolkit2/blob/master/doc/RKNNToolKit2_OP_Support-2.3.2.md` | RKNN 2.3.2 算子支持完整清单 |
| `https://github.com/modelscope/FunASR/issues/2286` | FunASR rk3588 部署主帖（一年半未解决）|
| `https://github.com/modelscope/FunASR/issues/2292` | FunASR FSMN-VAD rk3588 部署（动态 shape 卡死）|
| `https://github.com/airockchip/rknn-toolkit2/issues/136` | ASR encoder 转 RKNN Range op 不支持（维护者明确回复）|
| `https://github.com/k2-fsa/sherpa-onnx/issues/2515` | sherpa-onnx zipformer NPU 实测利用率数据 |
| `https://huggingface.co/csukuangfj/sherpa-onnx-rknn-models/tree/main/streaming-asr` | 官方 RKNN 流式模型库（全 zipformer，无 paraformer）|
| `https://huggingface.co/happyme531/SenseVoiceSmall-RKNN2` | 业界最强 RK3588 移植者作品，fp16 推理 + 无 paraformer 仓 |
| `https://huggingface.co/funasr/paraformer-zh-streaming` | paraformer-streaming PyTorch checkpoint 镜像 |
| `https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-paraformer/paraformer-models.html` | sherpa-onnx 文档：paraformer streaming 仅 ONNX，无 RKNN |
| `arxiv.org/pdf/2603.04308` | Transformer 量化精度退化研究 |
| `arxiv.org/pdf/2103.16827` | ASR 模型 INT8 PTQ 精度参考 |
