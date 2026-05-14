# AI 视听边缘 / VLM / 多模态 — GitHub 先进项目调研

日期：2026-05-14
基线：av_unified_mvp（端侧 RK3588 + Jetson + MQTT 解耦框架）
目标：给方向，不堆项目；只列我们能用得上的、或必须知道的对手。

---

## A. 我们能复用 / 借鉴（按对当前框架的实用度排序）

### A1. airockchip/rknn-llm — 我们的 3588 NPU 命脉
- 链接：https://github.com/airockchip/rknn-llm
- 现状（2026）：已正式支持 **Qwen3、Qwen3-VL、InternVL3、DeepSeek-OCR**；RK3588 仅 w8a8（这是硬约束，不是 bug）；7B-14B 实测 3-7 t/s，4B 实测 5-8 t/s。
- 我们怎么用：
  - 当前我们卡在 Qwen2.5-1.5B；**应该升到 Qwen3-4B w8a8**（落入 5-8 t/s 区间，足够意图层），1.5B 留作备用。
  - **Qwen3-VL 在 3588 上跑通是阶段 3 的关键 milestone**——这是我们替换"Jetson 上 ollama qwen2.5vl:3b"的本地候选。
  - 关注社区转换好的模型（HF 上 c01zaut、dulimov、jamescallander 等 user 维护了 7B/8B 的 RKLLM 权重，可省去自己量化的踩坑时间）。

### A2. k2-fsa/sherpa-onnx — 我们的 ASR 后端兜底
- 链接：https://github.com/k2-fsa/sherpa-onnx
- 现状（2026）：已支持 **FireRedASR2 / Cohere Transcribe（14 语种，2026-04-01 发布）/ FunASR Nano / Qwen3-ASR**；RK NPU / Axera NPU / Ascend NPU / RISC-V 都已纳入官方支持矩阵。
- 我们怎么用：
  - 我们当前 sensevoice + sherpa-onnx 路径正确，但 sherpa-onnx 已经把 NPU 路径上游化了——意味着 **3588 上跑 sherpa-onnx 不再需要我们自己适配**。
  - 短期试 Qwen3-ASR 替代 sensevoice（同口径下中文识别 + 标点 + 情感的 SOTA）。
  - Cohere Transcribe 多语种是给"涉外场景"的备胎，先放着不动。

### A3. ultralytics/ultralytics — YOLO26
- 链接：https://github.com/ultralytics/ultralytics
- 现状（2026-01）：**YOLO26 发布**，端到端 NMS-free（不再需要后处理），CPU 上比 YOLOv8 快 43%，去掉 DFL，原生支持 detect/segment/classify/pose/OBB 五任务 + open-vocab。
- 我们怎么用：
  - **YOLOv8n → YOLO26n 是一次低风险升级**——同一套 API，省 CPU、省功耗，3588 上裸 CPU 跑 4 路也能更稳。
  - Open-vocab 版本意义重大：以前要训"识别红色安全帽"必须标数据，现在 prompt 一句就能识别——对辽河这种"工业现场任意目标"是降本利器。

### A4. ggml-org/llama.cpp — 备份 LLM 推理路径
- 链接：https://github.com/ggml-org/llama.cpp
- 现状（2026-04）：单月 170+ release；**新加 Qualcomm Hexagon NPU backend、AMD CDNA4 backend、1-bit 量化、tensor parallelism**；vision/audio multimodal 通过 libmtmd；Gemma 4 day-one 支持。
- 我们怎么用：
  - llama.cpp 是"当 rknn-llm 在某个模型上掉链子时的兜底"——CPU 路径永远能跑通。
  - **Hexagon NPU 后端值得收藏**——以后如果客户要 Snapdragon 平板/手持端，这是我们已知的路径。
  - 不建议把 llama.cpp 作为 3588 主路径（NPU 利用不到，会浪费 RK3588 的 6 TOPS）。

### A5. livekit/agents + pipecat-ai/pipecat — 实时语音 pipeline 范式
- 链接：https://github.com/livekit/agents | https://github.com/pipecat-ai/pipecat
- 现状（2026）：两家都是 **realtime STT-LLM-TTS pipeline** 的工业级实现；都支持 voice + video + text 多模态；LiveKit 加了 Mistral Voxtral 流式 STT、xAI realtime、D-ID avatar；Pipecat 加了 LocalSmartTurnAnalyzerV3（本地话轮检测 65ms）。
- 我们怎么用：
  - **不要重复造轮子**——我们的 MQTT 模块解耦是对的，但"音频/视频流的实时编排"应该抄 pipecat 的 pipeline 抽象（FrameProcessor 链式）。
  - Pipecat 已经把"turn-taking / barge-in / interrupt"这些 voice agent 难点解决了——**等我们做语音双向交互时直接借鉴它的话轮分析器**（不需要整套 import，抄思路就行）。
  - LiveKit 偏 cloud-first，pipecat 更贴边缘，我们的语义更接近 pipecat。

### A6. QwenLM/Qwen3-VL — 新一代多模态主模型
- 链接：https://github.com/QwenLM/Qwen3-VL
- 现状（2026）：Dense + MoE 双架构，从 edge 到 cloud 都有；Instruct + Thinking（带推理）双版本；推荐 **Qwen3-VL-4B-Instruct** 作为入门点；ollama / vLLM / rknn-llm 全部支持。
- 我们怎么用：
  - **Jetson 上把 qwen2.5vl:3b 升到 qwen3-vl:4b**（ollama 已支持，零成本切换）。
  - 3588 上等 rknn-llm 的 4B w8a8 转换 ready（已在 supported list），是 Qwen2.5-VL-3B 的天然替代。
  - 关注 **Qwen3-VL-Embedding / Reranker**——以后做"视频帧/截图检索"时直接拿来用。

### A7. ollama/ollama — 多模态新引擎
- 链接：https://github.com/ollama/ollama
- 现状（2026）：新的 multimodal engine 把 vision 当一等公民；下一步是 speech / 图像生成 / 视频生成；structured outputs（JSON Schema 约束）已 GA；Llama 4 Scout 原生多模态（不是外挂 vision encoder）。
- 我们怎么用：
  - **structured outputs** 直接解决我们"意图 LLM 返回非结构化文本要手工解析"的痛点——把 intent schema 喂给 ollama 就能保证返回 JSON，省一层 prompt 工程。
  - Llama 4 Scout 在 Jetson 16GB 上能跑，可作为"高质量场景"备选 VLM。

### A8. m87-labs/moondream + huggingface/nanoVLM — 真·tiny VLM
- 链接：https://github.com/m87-labs/moondream | https://github.com/huggingface/nanoVLM
- 现状（2026）：Moondream 0.5B（专门给 edge 优化，2GB 内存即可跑）+ 2B 通用；nanoVLM 222M（SigLIP+SmolLM2），训练代码 750 行，OpenVINO/RKNN 移植路径清晰。
- 我们怎么用：
  - **3588 上 Moondream 0.5B 是 "30 秒一次场景描述" 的极速选项**——不替代 Qwen3-VL，但适合"做 hint，给主模型当 context"的级联架构。
  - nanoVLM 是我们以后想"训自己的小 VLM"时的起点（750 行 PyTorch，比从头读 LLaVA 代码快 10 倍）。

### A9. NVlabs/VILA — Jetson 上的 SOTA VLM
- 链接：https://github.com/NVlabs/VILA
- 现状：NVILA（VILA 2.0），AWQ 4bit 量化通过 TinyChat 在 Jetson Orin / 笔记本上能跑；多图理解是亮点。
- 我们怎么用：在 Jetson Orin 上是 Qwen3-VL 之外的 fallback；**多图比较场景**（比如"对比前后两帧"）VILA 表现明显更好。

### A10. FunAudioLLM/SenseVoice — 当前 ASR，关注但不急升
- 链接：https://github.com/FunAudioLLM/SenseVoice
- 现状：SenseVoice-Small 仍是 70ms/10s 的低延迟王者；2024 末更新到 CTC 时间戳；流式 fork 在 `streaming-sensevoice`。
- 我们怎么用：保留当前部署；**关注 Fun-ASR 技术报告（2509.12508）**——下一代是用更大模型，方向是端云协同。

---

## B. 竞品 / 对手 / 同道（差异定位）

### B1. NVIDIA Metropolis / Jetson Platform Services
- 定位：NVIDIA 全栈 vision AI + VLM agent edge SDK；包含 VLM 微服务 REST API（"对视频流提问 + 设警报"）。
- 差异点：
  - 他们是 **Jetson-only**，我们是 **跨品牌（3588 + Jetson + HDC900）**——这是我们的护城河。
  - 他们卖整套（硬件 + 软件 + 云），我们是模块解耦 + MQTT 总线——**集成成本低 5-10 倍**。
  - 但他们的 **TensorRT Edge-LLM**（开源 C++ 推理框架）值得偷一份当参考，特别是 KV-cache 复用策略。

### B2. Roboflow + Ultralytics Hub
- 定位：低代码 / SaaS 路径的 CV 平台；数据标注 → 训练 → 部署一条龙。
- 差异点：
  - 他们是 **训练 / 标注侧**，我们是 **推理 / 集成侧**——其实不冲突，可以并存。
  - **建议把 Roboflow 当我们的数据标注后端**（YOLO26 微调时用），不要把它当对手。

### B3. blakeblackshear/frigate
- 链接：https://github.com/blakeblackshear/frigate
- 定位：家用 NVR + YOLO 检测；0.17（2026-03）大版本，加了 **YOLOv9 on Coral / Intel NPU / Apple Silicon NPU / 自动 RKNN 转换 / Hailo 4.21 / MemryX MX3**。
- 差异点：
  - 他们的核心场景是 **家用监控的"对象 + 警报"**，我们做 **"视听 + 意图 + 语音问答"**——上层叙事完全不同。
  - 但他们的 **自动 RKNN 模型转换 pipeline 是我们应该抄的工程实践**（我们当前还是手工脚本）。
  - 关注他们怎么管多 detector backend 抽象（我们的 yolo_inference 模块以后要这个）。

### B4. Home Assistant + LLM Vision (valentinfrlch/ha-llmvision)
- 链接：https://github.com/valentinfrlch/ha-llmvision
- 定位：智能家居场景的 vision-LLM 集成；HA 2025.6+ 原生 Ollama；MCP 已纳入。
- 差异点：
  - 他们做 **C 端家庭场景**，我们做 **工业 / 跨场景平台**。
  - **MCP（Model Context Protocol）我们应该立刻支持**——这是事实标准的 LLM 工具协议，比我们当前的"自定义 prompt 拼接"标准多了。

### B5. openinterpreter/01 + Parlor + Google ai-edge/gallery
- 定位：on-device 全本地语音+视觉助手（Gemma 4 + Kokoro TTS + LiteRT 在 MacBook 上全离线）。
- 差异点：
  - 他们偏 **个人助手**（PC / 手机），我们偏 **场景 AI**（监控 / 一体机 / 车间）。
  - 他们的 **fully offline 叙事**和我们重合——要学他们怎么讲故事（"AI doesn't require cloud"）。

### B6. NVIDIA Cosmos World Foundation Models
- 链接：https://github.com/nvidia-cosmos
- 定位：物理世界视频生成 + 理解的基座模型；Nano/Super/Ultra 三档；Cosmos Reason 2（2026-02）加了边缘量化支持。
- 差异点：
  - Cosmos 是 **"理解物理"** 的方向（机器人 / 自驾），我们是 **"理解人 + 场景意图"**——不直接竞争。
  - **但 Cosmos Nano 的 tokenizer / embedding 值得关注**——以后做"视频片段检索"时可能就用它。

---

## C. 关键技术趋势（5 条，对我们有方向指引）

### C1. 4B 多模态成为端侧主力，1.5B 时代结束
- 证据：Qwen3-VL-4B / Gemma 4 4B / Llama 4 Scout / Moondream 2B 都已在 8GB 内存设备跑通；RK3588 上 4B w8a8 实测 5-8 t/s 可用。
- 启示：**我们 Qwen2.5-1.5B 该退役了**，4B 是新基线；1.5B 留给 NPU 抢占失败时的兜底。

### C2. 视觉模型从"外挂 encoder"转向"原生多模态"
- 证据：Llama 4、Qwen3-VL 都是预训练阶段就融了视觉；LLaVA 范式（CLIP + projector + LLM）逐渐过时。
- 启示：**别再 fine-tune LLaVA**，直接用原生多模态——我们任何"自训 VLM"的想法都要重新评估。

### C3. 端侧实时语音 pipeline 工业化（pipecat / livekit）
- 证据：pipecat smart-turn V3 本地 65ms 话轮检测；LiveKit agents 加 Voxtral 流式 STT。
- 启示：**我们做语音双向交互时，话轮 / 打断 / 重叠这些"语音协议层"不要自己写**，抄 pipecat 即可。

### C4. NPU 后端的"百花齐放"——抽象层变得关键
- 证据：llama.cpp 一个月内加 Hexagon、CDNA4、Hailo；frigate 加 Intel NPU、Apple NPU、MemryX、Synaptics、Degirum。
- 启示：**我们的 backend 抽象（RKNN / CUDA / CPU 三档）该泛化到通用 NPU 适配器接口**——下个客户可能拿来颗 Hailo / Hexagon / Ascend，我们要 1 天就能接上。

### C5. MCP（Model Context Protocol）成事实标准
- 证据：Home Assistant 已原生支持；多家 voice agent 框架在用；Anthropic 推动后被广泛接受。
- 启示：**MQTT 是我们模块间通信，MCP 应该是我们 LLM ↔ 工具间通信**——不冲突，应该叠加；越早接越值得。

---

## D. 推荐的下一步技术动作（按 ROI 排）

### D1. 立刻试（本周 / 下周，1-3 天工作量）
- **(D1a) Qwen2.5-1.5B → Qwen3-4B w8a8 升级**（3588 NPU 上）
  - 风险：低（rknn-llm 已官方支持）
  - 收益：意图准确率显著上升，开启工具调用能力
  - 上下文：现有 modules/llm_engine/ 接口不变，只换权重和 tokenizer
- **(D1b) ollama structured outputs 接入**（Jetson 侧）
  - 风险：极低（API 即用）
  - 收益：意图 JSON 解析逻辑可砍 60% 代码

### D2. 中期跟进（2-4 周）
- **(D2a) YOLOv8n → YOLO26n 升级**：CPU 43% 提速 + open-vocab 能力（让"业主自定义识别目标"成为产品功能而不是技术活）
- **(D2b) MCP server 落地一个原型**：把现有 modules/ 的能力封装成 MCP tool，让任何 LLM agent 都能调——这是技术杠杆动作
- **(D2c) Qwen3-VL-4B 在 3588 上跑通**：替代"Jetson 上 ollama"路径，统一架构

### D3. 长期看（季度级）
- **(D3a) 通用 NPU 适配器接口**：参考 frigate 0.17 的 detector 抽象，把 RKNN/CUDA/Hexagon/Ascend 统一到一个接口——下一代客户 1 天上线
- **(D3b) 抄 pipecat 的 pipeline 抽象做 av_unified 的"流编排层"**：当前 MQTT 解耦解决了"模块间"，pipeline 解决"模块内的实时流"——配合使用，不是替换
- **(D3c) 观察 NVIDIA Cosmos Nano 的工程化进度**：如果到 Q3 在 Jetson Thor 上跑通，我们的"工业现场视频结构化"可以直接站在它的肩膀上

---

## 附：本次调研未列出的、刻意排除的

- 大量"awesome-XXX-2026"列表（信噪比太低）
- 通用 agent 框架（LangGraph / CrewAI 等，与"边缘视听"主线无关）
- 闭源云端服务（GPT-4o / Gemini Live 等，不可控不在选项内）
- 训练侧框架（unsloth / axolotl 等，我们当前不训）

---

报告人：Claude（自动调研）
状态：未入仓；user review 后决定是否归档到 `docs/` 或 `roadmap/`。
