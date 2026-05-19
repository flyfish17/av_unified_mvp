# RK3588 离线语音 · NPU 利用 & 逐词输出 调研报告

> 调研日期：2026-05-19
> 背景：当前 `audio_processor` 使用 SenseVoice RKNN，CPU 支撑不丢字但无逐词输出，NPU 未充分利用

---

## TL;DR（结论先行）

| 问题 | 根因 | 结论 |
|---|---|---|
| **无逐词输出** | SenseVoice 架构上是非流式模型，无论 NPU/CPU 都不能出 partial | 必须换模型架构 |
| **NPU 未充分利用** | sherpa-onnx RKNN provider 对流式模型存在已知 bug，会大量回落到 CPU | 流式模型 NPU 利用率只有 ~7%，**但 CPU RTF=0.1 已够用** |
| **两个问题独立** | 解决逐词输出不需要解决 NPU 利用率 | 可独立推进 |

---

## 1. 现状诊断

### 1.1 SenseVoice 架构限制（逐词输出不可能的原因）

SenseVoice-Small 是 **全序列编码器（encoder-only / full-context）** 架构：
- 编码器一次读取完整音频帧（固定长度，如 20s 窗口）
- 解码器在编码结束后同时生成所有 token
- **没有"左上下文 + 增量解码"机制**

这意味着：
- 无论跑在 CPU 还是 NPU，SenseVoice 只能在说完一句话后输出整句
- **逐字/逐词输出在 SenseVoice 架构层面不支持，非调参/优化问题**
- 当前 RKNN 模型命名中的 "20-seconds" 也证实了这一点：它处理的是最长 20s 的完整片段

### 1.2 NPU 利用率 Bug（已知缺陷）

sherpa-onnx 上存在两个相关 GitHub Issue：

**Issue #2447（RK3576，Android 14）**  
- 现象：应用运行时 CPU 使用率 ~56%，NPU 占用率仅 ~7%
- 根因：RKNN provider 对流式模型没有有效调度到 NPU，默默回落到 CPU
- 状态：**未关闭，无官方修复**

**Issue #2515（RK3588，Linux）**  
- 测试：streaming-zipformer-small 双语模型，18s 音频
- CPU 结果：总耗时 6.5s，**RTF = 0.1**（10x 实时）
- NPU 结果：总耗时 4.1s，**RTF = 0.18**（5.5x 实时）
- 悖论：NPU 总耗时更短（因为模型加载快），但**推理 RTF 反而更差**
- 原因：NPU 推理本身比 CPU 慢，模型加载快掩盖了推理慢的问题
- 状态：**未关闭**

**结论**：在流式 ASR 场景，RK3588 RKNN provider 的 NPU 加速目前对推理性能无正向作用，甚至拖慢。**CPU RTF=0.1 对实时流式已完全够用。**

---

## 2. 能真正做到逐词输出的方案

### 2.1 流式模型架构说明

逐词出需要**流式（streaming）架构**：
- 编码器有左右上下文窗口（chunk-based）
- 每处理一个 chunk（通常 20-640ms）就能输出到目前为止识别的 token
- 代表：**Zipformer-Transducer**、**Paraformer-Streaming（CIF）**、**Conformer-RNN-T**

### 2.2 当前 sherpa-onnx 生态中 RK3588 可用的流式 RKNN 模型

来源：`csukuangfj/sherpa-onnx-rknn-models` HuggingFace 仓库

| 模型 | 大小 | 语言 | 支持流式？ | 备注 |
|---|---|---|---|---|
| `sherpa-onnx-rk3588-streaming-zipformer-small-bilingual-zh-en-2023-02-16` | **~50MB** | 中/英 | ✅ 真流式 | 小模型，CPU RTF~0.1 |
| `sherpa-onnx-rk3588-streaming-zipformer-bilingual-zh-en-2023-02-20` | **~130MB** | 中/英 | ✅ 真流式 | 大模型，精度更好 |
| `sherpa-onnx-rk3588-20-seconds-sense-voice-zh-en-ja-ko-yue` | ~170MB | 多语言 | ❌ 非流式 | 当前在用，无逐词 |
| `sherpa-onnx-rk3588-15-seconds-paraformer-zh-2025-10-07` | 未知 | 中文 | ❌ 非流式 | 离线 paraformer，也无逐词 |

**注**：paraformer-streaming（在线流式 paraformer）在 **v1.12.15** 已导出到 RKNN，但目前文档和模型仓库中无对应 `rk3588-streaming-paraformer` 模型，可能仍在整备中。

### 2.3 sherpa-onnx RKNN 关键版本演进

| 版本 | RKNN 相关内容 |
|---|---|
| v1.11.0 | 首次支持 RKNN Zipformer CTC + Transducer modified beam search |
| v1.12.1 | **Fix rknn for multi-threads**（多线程 bug 修复） |
| v1.12.15 | Export Paraformer to RKNN（离线 paraformer） |
| v1.12.20 | **Avoid calling rknn_dup_context()** （context 复制优化，减少内存/延迟开销） |
| v1.13.2（最新） | 当前最新版，含 RKNN AAR；无重大 RKNN 流式修复记录 |

---

## 3. 各路径评估

### 路径 A：保持 SenseVoice RKNN + 接 streaming-zipformer CPU 做 partial

| 维度 | 评估 |
|---|---|
| 逐词输出 | ✅ zipformer 出 partial，sensevoice 出 final |
| 计算开销 | ⚠️ 双模型同时跑，zipformer CPU + sensevoice NPU |
| NPU 利用 | ✅ sensevoice 用 NPU（20x realtime），zipformer 用 CPU（RTF 0.1） |
| 精度 | ✅ final 用 sensevoice 保精度，partial 用 zipformer 给用户预览 |
| 工时 | 中（需接入 sherpa-onnx 流式 API + 改 audio_processor）|
| 与现有架构兼容 | 中（需新增 sherpa-onnx 依赖） |

### 路径 B：完全切换到 streaming-zipformer RKNN

| 维度 | 评估 |
|---|---|
| 逐词输出 | ✅ 真流式，chunk 级输出 |
| 计算开销 | ✅ 单模型，CPU RTF=0.1 够用 |
| NPU 利用 | ❌ 已知 NPU provider bug，NPU ~7%，CPU 跑 |
| 精度 | ⚠️ 比 sensevoice 差，无多语言/情绪检测 |
| 迁移成本 | 高（当前 sensevoice 已调优，需重新调 VAD/阈值/格式） |
| 与 DEVELOPMENT_PLAN 一致性 | ✅ Plan §3.2 已预定"阶段三换 paraformer-streaming，平滑过渡" |

### 路径 C：等待 streaming-paraformer RKNN 模型就绪

| 维度 | 评估 |
|---|---|
| 逐词输出 | ✅ paraformer-streaming 架构支持流式 |
| 精度 | ✅ 比 zipformer 好（中文），接近 sensevoice |
| 可用时间 | ❓ v1.12.15 已有 export 代码，但无对应 rk3588 模型文件 |
| 等待成本 | 不确定，社区进度无法掌控 |
| 推荐 | 作为"关注项"，不作为当前实施依赖 |

---

## 4. NPU 三核分配现状

RK3588 有 3 个 NPU 核，每核 2 TOPS，合计 6 TOPS。

- **SenseVoice RKNN**：单核跑 20x realtime，可用 3 核并发处理 3 路音频
- **Streaming-Zipformer RKNN**：单核 RTF=0.18（比 CPU 0.1 还慢），多核并发无益
- **LLM（rknn-llm）**：当前跑 1.5B 模型已用 NPU，与 ASR 竞争资源

当前 3588 NPU 使用情况：
- 1 核：sensevoice（ASR final）
- 1~2 核：rknn-llm（1.5B LLM）
- 1 核：剩余可用

**如果加 streaming-zipformer，建议在 CPU 跑，不争 NPU 资源。**

---

## 5. 推荐行动

### 近期（阶段二 P1 范围内）

**建议：不动当前 sensevoice，做 CPU 流式 partial 的 spike**

- 在 3588 上用 sherpa-onnx streaming-zipformer-small（CPU 模式，非 RKNN）做 spike
- 验证：RTF、partial 出字延迟、与现有 VAD 的兼容性
- 如果 CPU 占用不超过 30%（当前 video_processor 压力下），可作为独立 partial MQTT module 接入
- **不动 audio_processor**，新增 `modules/partial_asr/` 模块

### 中期（阶段三）

- 跟进 sherpa-onnx RKNN issue #2447/#2515 修复进度
- 跟进 `rk3588-streaming-paraformer` 模型是否上线
- 届时可平滑替换（sherpa-onnx 生态内）

---

## 6. 关键参考链接

- [sherpa-onnx · GitHub](https://github.com/k2-fsa/sherpa-onnx)
- [Issue #2515 · RK3588 NPU 推理比 CPU 慢](https://github.com/k2-fsa/sherpa-onnx/issues/2515)
- [Issue #2447 · High CPU/Low NPU on RK3576](https://github.com/k2-fsa/sherpa-onnx/issues/2447)
- [Issue #3154 · RKNN streaming zipformer segfault](https://github.com/k2-fsa/sherpa-onnx/issues/3154)
- [csukuangfj/sherpa-onnx-rknn-models · HuggingFace（streaming-asr 目录）](https://huggingface.co/csukuangfj/sherpa-onnx-rknn-models/tree/f56f1d5c88e0e17fe62f22cb73bcab0e5bb19a68/streaming-asr)
- [SenseVoiceSmall-RKNN2 · ThomasTheMaker HuggingFace](https://huggingface.co/ThomasTheMaker/SenseVoiceSmall-RKNN2)
- [sherpa-onnx CHANGELOG.md](https://github.com/k2-fsa/sherpa-onnx/blob/master/CHANGELOG.md)
- [Radxa Rock5 NPU 模型实测论坛](https://forum.radxa.com/t/run-these-advanced-ai-models-right-now-on-your-rock-5-board-with-npu-acceleration/24989)
- [sherpa-onnx RKNN Documentation](https://k2-fsa.github.io/sherpa/onnx/rknn/index.html)
- [DeepWiki NPU Support Architecture](https://deepwiki.com/k2-fsa/sherpa-onnx/7.2-npu-support-(embedded-accelerators))

---

*报告生成：2026-05-19 · 调研耗时 ~40min · 保存路径：`docs/research/rk3588-npu-streaming-asr-20260519.md`*
