# ASR / 标点 / 说话人分离 调研

**日期**: 2026-05-18
**作者**: research agent (Opus 4.7)
**信息边界**: 已知信息截至 2026-01；2026 上半年具体 release 细节有缺口，下文凡涉及 2026-Q2 状态均标记 "未核实"。
**服务对象**: av_unified_mvp 语音模块产品化路径决策（路径 1 不大改 vs 路径 2 大改）

---

## 1. TL;DR

推荐 **新中间路径 = "路径 1 + 一个核心补强"**：保留 sensevoice RKNN 作为 final（已稳态），用 **sherpa-onnx 的 ct-punc ONNX 模型**做服务端 CPU 标点后处理（不是 LLM），同时用 **silero-vad v6 + 阿里 CAM++ ONNX embedding**做一个轻量的"段级聚类"说话人标签（不是真 online diarization）。理由：(1) sherpa-onnx 一站式 Apache-2.0 项目同时覆盖 RK3588 NPU 流式 ASR、ct-punc 标点、pyannote/3D-Speaker 嵌入式 diarization，已经把整条链路工程化了，避免我们 N 个 docker 重组；(2) 标点用 ct-punc ONNX (CPU 14ms/句，int8 72MB) 远比 LLM 后处理可靠且可离线，不必为此引入 LLM 依赖；(3) 真 online diarization 在 video_processor 已 405% CPU 的情况下不可行，CAM++ (7.2M 参) 段级聚类是当前算力下唯一合理近似。Paraformer-streaming 真 partial 留作阶段三的可选升级，本阶段不动 ASR 模型。

---

## 2. 项目对照表

| 项目 | License | Stars/活跃度 | 最近 release | 中文支持 | 实时延迟 | RK3588 NPU | 生产可用度 |
|---|---|---|---|---|---|---|---|
| **sherpa-onnx** (k2-fsa) | Apache-2.0 | 高，多语言 binding | v1.13.2 (2026-05) | ✅ paraformer/sensevoice | streaming chunk 600ms | ✅ 一等公民，已有 RK3588 paraformer-zh / sensevoice 预编译 | **高**（边缘首选） |
| **FunASR** (modelscope) | MIT | 高 | Fun-ASR-Nano-2512 (2025-12) | ✅ paraformer-zh-streaming, ct-punc | streaming 配 chunk=[0,10,5] 约 600ms | 通过 sherpa-onnx 间接支持；FunASR 直跑需 docker，ARM64 image 自 2024-03 起有 | 中（docker 重，3588 上不推荐直跑） |
| **SenseVoice** (FunAudioLLM) | MIT | 高 | RKNN port: happyme531/ThomasTheMaker | ✅ 中粤英日韩 | offline only, **不出 partial / 不出标点 / 不出 ITN** | ✅ RKNN 已实测 20x RT (3588 单核, ~1.1GB) | 高（项目已用） |
| **Paraformer-streaming** | MIT (FunASR) | 同 FunASR | funasr/paraformer-zh-streaming | ✅ 真 partial + ITN/标点 | 600ms chunk | sherpa-onnx 有 rk3588-15s-paraformer-zh-2025-10-07 预编译 | 高（路径 2 主选） |
| **Whisper turbo / faster-whisper** | MIT | 极高 | large-v3-turbo (2024-10), v4 (2026) | 中文可，但 turbo 对粤/泰有降级；非主打 | 0.45s mean latency (WhisperKit) | 无主流 RKNN 端口（仅有非官方实验） | 中（中文场景不及 paraformer） |
| **pyannote-audio** | MIT (模型 gated) | 高 | **v4.0.4 (2026-02-07)** | 通用（AISHELL-4 benchmark） | RTF≈0.025 on V100 GPU；CPU 慢 | ❌ 无 RKNN port；PyTorch only | 高（GPU 服务端），边缘端不可用 |
| **pyannote (sherpa-onnx ONNX port)** | Apache-2.0 (代码) / model license | sherpa-onnx 内置 | sherpa-onnx-pyannote-segmentation-3-0 | 通用 | ONNX CPU 可跑 | 暂无 RKNN，但 ONNX CPU 可在 3588 大核跑 | 中（CPU 预算够才行） |
| **3D-Speaker** (modelscope) | Apache-2.0 | 中 | ICASSP 2025 paper，main 持续提交 | ✅ 中文专攻 | CAM++ 7.2M 参，ERes2NetV2 17.8M | ❌ 无 RKNN；有 ONNX runtime (2024-04) | 中（embedding 模块可用） |
| **silero-vad** | MIT | 极高 | **v6.0 (2025-08-25)** | 语言无关 | streaming 30ms 窗口 | ONNX 直跑 CPU 极轻 | 高（VAD 标准件） |
| **NeMo Parakeet/Canary** | NVIDIA OSS | 极高 | Parakeet-TDT-0.6B-v3 / Canary-1B-v2 (2025-09) | Canary v2 25 种欧语为主，**中文非主线** | streaming 支持 | ❌ NVIDIA 生态，3588 不适用 | 不适用 |
| **ct-punc / CT-Transformer** | MIT (FunASR) | 中 | 2024-04 ONNX 模型；sherpa-onnx 持续打包 | ✅ 中英混标点 | CPU int8 ~14ms/句 (281MB→72MB int8) | sherpa-onnx 内嵌，CPU 跑即可 | **高**（标点首选） |
| **WeNet / icefall** | Apache-2.0 | 中 | 仍在更新；Zipformer wenetspeech-streaming | ✅ | streaming 可调 | 通过 sherpa-onnx 走 | 中（不如直接用 sherpa-onnx 封装） |

---

## 3. 中文标点路径深度评估

| 方案 | 准确率 | 延迟 | 资源 | 工程成本 | 离线可用 |
|---|---|---|---|---|---|
| **A. ct-punc ONNX 后处理**（sherpa-onnx 打包） | F1 业界第一梯队（CT-Transformer 原论文 Interspeech） | int8 14ms / 句 (CPU 单线程) | 72MB 模型，跑 CPU | **低**：起一个 Python 进程订阅 final → 调 sherpa-onnx → 发标点后版本；可直接独立 module | ✅ |
| **B. LLM 后处理**（OpenAI / Qwen / 本地小 LLM） | Qwen-2.5-72b 在粤语标点 F1=73.6（Interspeech 2025）；中文普通话更高但**仍受 prompt 鲁棒性影响** (arxiv 2508.11383) | 网络/本地 LLM 调用 200ms-2s | API 成本或 GPU 占用 | 中：需 prompt 模板调优 + 容错；引入外部依赖 | ❌（如调云端） |
| **C. 升级 ASR 到 paraformer-streaming**（带 ITN） | 模型原生输出标点，F1 通常 > ct-punc 后处理 | 整体 partial 600ms | 与现 sensevoice 相当（sherpa-onnx 有 rk3588 预编译） | 高：换模型、改 audio_processor、retire sensevoice 链路 | ✅ |

**结论**：本阶段选 **A**。理由：ct-punc 是工业级 transformer 蒸馏专用模型，准确率稳定、毫秒级、可离线、和 LLM 后处理对比"避免引入第二条云依赖链路"。LLM 后处理只适合"我们已经在用 LLM 总结纪要"的链路里顺手做，不该单独为标点拉起 LLM 服务。

参考：[sherpa-onnx 标点模型清单](https://k2-fsa.github.io/sherpa/onnx/punctuation/pretrained_models.html) | [CT-Transformer-punctuation](https://github.com/lovemefan/CT-Transformer-punctuation) | [Cantonese Punctuation Restoration using LLM Annotated Data, Interspeech 2025](https://www.isca-archive.org/interspeech_2025/suen25_interspeech.pdf)

---

## 4. 说话人分离路径深度评估

| 方案 | 真实欺骗性 / 准确率 | 资源 | 工程成本 | 适合本项目? |
|---|---|---|---|---|
| **A. silero-vad 切片 + 顺序编号 1/2/3** | 单人讲话场景近似可用；**2 人同时讲或交替快说会爆**（VAD 不分 ID，只看有无人声）；用户能很快看穿 | 极低（30ms ONNX 推理） | 0.5d | 仅 demo/PoC，不上生产 |
| **B. silero-vad 切片 + CAM++ ONNX embedding + 在线聚类** | 段级 DER 在干净录音 15-25%（3D-Speaker 自报）；overlap 不处理 | CAM++ 7.2M 参 + embedding cluster，单段 < 100ms CPU | 1-2d（关键：cluster 阈值调参 + history 状态机） | **推荐**（本阶段最优近似） |
| **C. pyannote-audio 4.0** | Community-1 OSS DER ~13.3%（AMI 等通用数据）；商用 Precision-2 11.2% | PyTorch only；CPU RTF 慢，3588 CPU 不堪重负；GPU offload 需远程服务 | 中 2-3d（含 docker 化 + token gated 模型）；**或上云做** | 路径 2 后期或上云时再上 |
| **D. pyannote ONNX (sherpa-onnx 封装)** | 与 pyannote 同水准，但 sherpa-onnx 内 issue 提到过 offset-by-one 等坑 | ONNX CPU；3588 大核可跑但要测 | 中 2d | 备选；可作为 B 不够时再升 |

**关键事实**：
- **silero-vad v6 (2025-08)** 主打 16% 噪声场景错误下降，但**它不是 diarization**，独自做 "speaker 1/2/3" 只能在严格轮替对话场景骗一下。
- **3D-Speaker CAM++** 是阿里 200k 中文 speakers 训的，中文专攻，ONNX runtime 自 2024-04 起官方支持，参数仅 7.2M，是边缘端 embedding 唯一务实选项。
- **pyannote 4.0 (2026-02-07)** 模型本体 PyTorch，且**模型在 HuggingFace 是 gated**（需 accept license），离线部署要预下载，给 3588 增加重负担。

**结论**：本阶段选 **B**。silero-vad 已经在路径 1 里；加 CAM++ ONNX embedding 是 +0.5~1d 工时，DER 不会比 pyannote 好但**在 3588 算力预算内**。pyannote 留作未来上"云端 + 边缘"双链路时启用。

参考：[3D-Speaker GitHub](https://github.com/modelscope/3D-Speaker) | [pyannote-audio 4.0 changelog](https://www.pyannote.ai/changelog) | [silero-vad v6 release](https://github.com/snakers4/silero-vad/releases) | [Benchmarking Diarization Models, arxiv 2509.26177](https://arxiv.org/html/2509.26177v1)

---

## 5. 路径 1 / 路径 2 工时与风险对照

| 维度 | 路径 1（原方案，纯 mock） | **新中间路径（推荐）** | 路径 2（FunASR 2pass + pyannote） |
|---|---|---|---|
| 工时 | ~1d | **1.5-2d** | 5-8d |
| 标点能力 | LLM 后处理（依赖云/本地 LLM） | **ct-punc ONNX 本地**（F1 高、毫秒级、离线） | 模型原生 ITN（最佳） |
| 说话人 | silero-vad 顺序编号（用户能看穿） | **silero-vad + CAM++ embedding 聚类**（段级 DER ~20%，可用） | pyannote 真 online（DER 13%，需 GPU 或 3588 大核重负载） |
| 真 partial | ❌ | ❌（保留 sensevoice 不出 partial） | ✅ paraformer-streaming 600ms chunk |
| 视频侧风险 | 0 | 0（CAM++ + ct-punc 都跑 CPU，且都是 ms 级） | 高：3588 已 405% CPU；再上 pyannote + 2pass docker 大概率挤爆 |
| 可演示性 | 标点和说话人都"假" | **标点真，说话人段级真** | 全真 |
| 后续升级路径 | 必拆 | **平滑**：同样在 sherpa-onnx 体系内，未来换 paraformer-streaming 只换 ASR module 即可 | 已经到顶，要再上就上云 |

**最大风险点**：
- 路径 2 的 FunASR 2pass docker 在 3588 ARM 上**没有官方 image**（FunASR 仅声明 ARM64 server 场景，未提 RKNN），且 video_processor 已吃满 4 核，再叠 pyannote 几乎肯定 OOM 或 thermal throttle。
- 新中间路径的最大不确定项是 **CAM++ ONNX 在 3588 大核 CPU 实测延迟**——文档没有 3588 数据，建议第一天先跑一个 spike 测一段 30s 多人对话录音，CPU% 和段延迟过线再继续。

---

## 6. 推荐路径与理由

### 推荐：**新中间路径**（路径 1 + ct-punc 真标点 + CAM++ 段级说话人聚类）

1. **不撞 video_processor 算力红线**：所有新增组件（silero-vad / CAM++ embedding / ct-punc）都是 CPU ms 级 ONNX，单条 final 处理整体 < 50ms，不挤 NPU、不抢 video_processor 的核。
2. **当下代码作用最大化**：sensevoice RKNN 链路完全不动，audio_processor 不重构；新增两个独立 module（`punctuator/`, `speaker_tagger/`）通过 MQTT 订阅 final 事件，完全符合 CLAUDE.md 的"解耦订阅"架构原则。
3. **平滑升级到路径 2**：当未来真要上 partial 或真 diarization 时，因为整条链路已经在 sherpa-onnx 生态里，只需把 sensevoice 换成 paraformer-streaming（sherpa-onnx 已有 rk3588 预编译模型），diarization 把 CAM++ 换成 pyannote ONNX 即可，无需推倒重来。

### 不推荐路径 1 原 mock 方案
- silero-vad 顺序编号 "说话人 1/2/3" 在实际多人会议第一次播放就会被识破，等于零客户价值。
- LLM 后处理标点是反工程：明明有 72MB 的 ct-punc 工业模型可用，引入 LLM 既增加延迟也增加云依赖。

### 不推荐路径 2
- 当下 video_processor 已 405% CPU，再叠 pyannote + 2pass 几乎肯定踩边缘机散热墙；
- ASR 模型更换是大改，本 sprint "不大拆大改" 的红线不能碰；
- ROI 不如先把标点+段级说话人做到产品 demo 可用，留出时间打磨业务交互。

---

## 7. 参考链接

### 核心 repo
- [sherpa-onnx](https://github.com/k2-fsa/sherpa-onnx) — Apache-2.0，v1.13.2 (2026-05)，**边缘 NPU 一站式首选**
- [FunASR](https://github.com/modelscope/FunASR) — MIT，Fun-ASR-Nano-2512 (2025-12)
- [SenseVoice](https://github.com/FunAudioLLM/SenseVoice) — 项目已用
- [SenseVoiceSmall-RKNN2 (happyme531)](https://huggingface.co/happyme531/SenseVoiceSmall-RKNN2) — RK3588 ~20x RT, 1.1GB
- [SenseVoiceSmall-RKNN2 (ThomasTheMaker)](https://huggingface.co/ThomasTheMaker/SenseVoiceSmall-RKNN2)
- [pyannote-audio](https://github.com/pyannote/pyannote-audio) — MIT 代码，模型 gated；v4.0.4 (2026-02-07)
- [3D-Speaker](https://github.com/modelscope/3D-Speaker) — Apache-2.0，CAM++ / ERes2NetV2，ICASSP 2025
- [silero-vad](https://github.com/snakers4/silero-vad) — MIT，v6.0 (2025-08-25)
- [CT-Transformer-punctuation](https://github.com/lovemefan/CT-Transformer-punctuation) — 中英混标点 ONNX
- [funasr/paraformer-zh-streaming](https://huggingface.co/funasr/paraformer-zh-streaming) — 真 partial + ITN

### 关键文档/benchmark
- [sherpa-onnx 标点模型清单](https://k2-fsa.github.io/sherpa/onnx/punctuation/pretrained_models.html) — ct-punc int8 72MB / CPU 14ms
- [sherpa-onnx 在线 paraformer 模型](https://k2-fsa.github.io/sherpa/onnx/pretrained_models/online-paraformer/index.html)
- [sherpa-onnx speaker diarization](https://k2-fsa.github.io/sherpa/onnx/speaker-diarization/index.html)
- [Fun-ASR Technical Report (arxiv 2509.12508)](https://arxiv.org/html/2509.12508v3) — paraformer streaming chunk [0,10,5] 600ms 配置
- [3D-Speaker-Toolkit paper (arxiv 2403.19971)](https://arxiv.org/html/2403.19971v3) — CAM++ vs ERes2NetV2 对比
- [Benchmarking Diarization Models (arxiv 2509.26177, 2025)](https://arxiv.org/html/2509.26177v1) — pyannote 11.2% DER，DiariZen 13.3% DER
- [Cantonese Punctuation Restoration LLM benchmark, Interspeech 2025](https://www.isca-archive.org/interspeech_2025/suen25_interspeech.pdf) — Qwen-2.5-72b F1 73.6
- [light-weight punctuation CNN-BiLSTM](https://www.researchgate.net/publication/382364031) — 比 CT-Transformer 小 40x，快 2.5x（可选未来再轻量化）
- [pyannote.ai changelog](https://www.pyannote.ai/changelog) — 4.0 / community-1 / precision-2

### 下一步建议（spike 任务）
1. 在 3588 上 `pip install sherpa-onnx`，跑 ct-punc int8 模型，对一段已转写文本压测，看单 final（约 30 字）延迟。预计 < 30ms。
2. 在 3588 大核上跑 CAM++ ONNX embedding 提取 + sklearn AgglomerativeClustering，对一段 60s 双人对话做段级聚类，看 CPU%、延迟、DER 直观感受。
3. 评估通过后启动 2 个 MQTT module：`modules/punctuator/`（订阅 `asr/final`，发 `asr/final_punctuated`），`modules/speaker_tagger/`（订阅 `audio/raw_segment`，发 `speaker/segment_label`）。Dashboard 显示带标点 + 说话人 tag 的 transcript。
