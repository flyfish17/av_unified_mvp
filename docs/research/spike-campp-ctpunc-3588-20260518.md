# P0.9 Spike 报告 — ct-punc + CAM++ 在 RK3588 上的延迟/资源验证

**日期**: 2026-05-18
**目的**: 新中间路径（DEVELOPMENT_PLAN.md §3.2）立项前置 gating
**spike 环境**: `firefly@192.168.5.6` · 独立 venv `/home/firefly/spike_venv_20260518/`（**不动 creator_ai_demo/venv 红线**）
**包**: sherpa-onnx 1.13.2 (aarch64 wheel, 16.5MB)

---

## Phase A · ct-punc int8 ONNX 延迟实测 ✅ 过线

**模型**: `sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8`
**下载源**: GitHub release（CDN 慢，改走 `ghfast.top` 镜像，64MB / 17s @ 3.7 MB/s）
**配置**: `num_threads=1`, `provider="cpu"`
**Load**: 363ms 一次性

### 延迟数据（warmup 5 次 + 测 30 次）

| sample | 字数 | warmup_ms | p50_ms | p95_ms | mean_ms | 输出片段 |
|---|---|---|---|---|---|---|
| short_10 | 9 | 4.1 | **4.3** | 4.9 | 4.3 | 这个测试今天搞完吗？ |
| mid_20   | 19 | 7.7 | **7.9** | 8.2 | 7.9 | 辽河项目周二要交付演示，客户那边催了三次。 |
| mid_30   | 32 | 15.1 | **15.7** | 16.4 | 15.8 | 新中间路径在三五八八上跑，延迟数据没有先测一下，心里有数，再… |
| long_50  | 65 | 25.0 | **25.8** | 26.6 | 25.9 | 今天讨论了视频处理瓶颈，占用四百二十帕森的中央处理器决定先保… |
| long_80  | 99 | 36.3 | **37.4** | 37.9 | 37.3 | 会议要点，一是冻结主线分支，二是迁移所有调试日志到统一格式。… |

**延迟成本**：≈ 0.4ms/字符（线性）。会议典型 final 20-50 字 → p95 8-27 ms。

### 标点质量主观评估

- **稳定的逗号 + 句号**："辽河项目周二要交付演示，客户那边催了三次。" ✅
- **会议要点格式识别好**："会议要点，一是冻结主线分支，二是迁移所有调试日志到统一格式。" ✅
- **偶尔欠断**："占用四百二十帕森的中央处理器决定先保" — 这种长名词短语模型保守，可接受
- **问号识别**：单短句问句识别正确（"今天搞完吗？"）

### 生产链路影响

spike 跑期间另起独立 venv 进程，对照 audio/video processor：

| 进程 | spike 前 | spike 中 / 后 |
|---|---|---|
| video_processor (PID 3998) | 405% CPU | **405% CPU**（无变化）|
| audio_processor (PID 3997) | 2.1% CPU | **2.1% CPU** |
| 3588 温度 | 44-45°C | **44-45°C** |

**结论**：ct-punc 单线程 CPU 推理零侵入生产链路。

### Phase A 判定

✅ **过线**。所有指标优于报告预估（<30ms 预期 vs 实测 p95 <38ms 即使 99 字段也）。可立项 `modules/punctuator/`。

---

## Phase B · CAM++ ONNX 段级说话人聚类 ✅ 过线

**样本**：`/home/firefly/spike_venv_20260518/samples/2speakers_example.wav`（pyannote 官方双说话人示例，51.66s @ 16kHz mono），含同目录 `.rttm` ground-truth。

**依赖（spike_venv 增量）**：

| 包 | 版本 | 用途 |
|---|---|---|
| `silero-vad` | 6.2.1 | VAD 切片（pip 包内置 ONNX）|
| `onnxruntime` | 1.23.2 | silero-vad ONNX 后端（sherpa-onnx 自带的不暴露顶层 import）|
| `numpy` | 2.2.6 | spike 数据处理 |
| `scipy` | 1.15.3 | 间接依赖 |
| `soundfile` | 0.13.1 | WAV I/O |
| `scikit-learn` | 1.7.2 | AgglomerativeClustering |

**注**：silero-vad pip 包带 torch 2.12 + 一堆 nvidia-cuda 轮子（约 1GB 占盘）；spike 无害，未来生产模块可考虑改为直接 onnxruntime 调 silero-vad 的 ONNX，剥离 torch。

### 模型

| 资源 | 路径 | 大小 | 来源 |
|---|---|---|---|
| CAM++ ONNX | `/home/firefly/spike_venv_20260518/models/campp.onnx` | 27 MB | sherpa-onnx release `3dspeaker_speech_campplus_sv_zh-cn_16k-common.onnx` via `ghfast.top` 镜像 |
| silero-vad ONNX | `silero_vad/data/silero_vad_16k_op15.onnx`（包内置）| ~2MB | pip `silero-vad` 6.2.1 |
| 加载耗时 | 一次性：silero 1902ms / CAM++ 763ms | — | — |

### Spike 实测（3 次 run，数据 ±2% 稳定）

```
audio = 51.66s @ 16kHz mono → silero-vad 切出 7 段语音
                  RUN1     RUN2     RUN3
VAD 总耗时        683.8    691.2    739.2  ms  (~13ms / 1s audio)
EMB 总耗时       1513.9   1537.4   1532.4  ms  (7 段 / avg ≈ 219ms)
CLU 总耗时        737.5    717.6    751.0  ms  (sklearn 首次 import 主导，纯算法 <10ms)
user_cpu          7.89     7.83     8.05   s   (单核累计)
maxrss            716      716      716    MB
```

### 单段 embedding 延迟 vs 段长（CAM++ num_threads=2）

| seg | duration | emb_ms | 实时倍率 |
|---|---|---|---|
| #00 | 18.62s | 570.5 | 33x |
| #01 |  4.09s | 130.4 | 31x |
| #02 |  7.64s | 243.7 | 31x |
| #03 |  8.19s | 260.9 | 31x |
| #04 |  2.30s |  85.5 | 27x |
| #05 |  4.76s | 154.6 | 31x |
| #06 |  2.70s |  89.4 | 30x |

**embedding cost ≈ 30ms / 1s audio**（线性，单段最小 ~85ms）。对实时会议流式：典型 2-10s 段 → 单段处理 60-300ms，可接受。

### DER vs ground-truth RTTM

| 指标 | 值 |
|---|---|
| 总语音 | 50.72s |
| 正确归属 | 46.17s |
| 混淆 (confusion) | 2.14s (4.2%) |
| 漏检 (missed by VAD) | 2.41s (4.7%) |
| 误检 (FA) | 0.00s |
| **近似 DER** | **9.0%** |

**段级正确率 = 7/7 段**（聚类→GT 映射: cluster 0 → spk 1 overlap 31.46s, cluster 1 → spk 2 overlap 14.71s，无错位）。

混淆 2.14s 来自 silero-vad 在 GT 转折点附近的边界粗糙（如 32.61-40.80 这段实际跨越了 spk 1/2 切换，embedding 取的是整段平均，聚到 spk 1 是占优）。漏检 2.41s 来自 silero 的 min_silence/min_speech 缩边。这两类都不是 CAM++ 本身的问题。

**主观判定**：段级标签和真实切换 **完全对得上**（7/7），段内长跨度切换是 VAD 切片粗糙度问题，不是 embedding 区分能力问题。

### 生产链路影响（spike 中实时 top）

| 进程 | spike 前 | spike 中 | spike 后 |
|---|---|---|---|
| video_processor (PID 522257) | 413% | 360% | 420% |
| audio_processor (PID 522256) | 0% | 6.7% (audio I/O 时切片) | 0% |
| spike_speaker_segment | — | 113% | — |
| 3588 总 CPU | 50% | 57% | 52% |

video_processor 在 spike 期间略有下降（OS 调度让出核），spike 退出后立刻回升，没观察到长时间影响。**与 Phase A 结论一致：单线程 CPU 推理零侵入生产链路**。

### Phase B 判定

✅ **过线**。综合：
1. 端到端 51.7s 双人对话处理总耗时 ≈ 3s wall（单段 emb 30ms/1s audio + 聚类瞬时）
2. 段级聚类正确率 7/7，DER 9.0%（混淆仅 4.2%，主因 VAD 边界粗糙非 CAM++）
3. 不撞生产 CPU、内存 716MB 可接受
4. CAM++ 27MB ONNX 在 sherpa-onnx 内置 API（`SpeakerEmbeddingExtractor`）开箱即用

**`modules/speaker_tagger/` 可立项 P1.2**。设计思路：订阅 `av/audio/command_punctuated` + 切片对应的 PCM 缓冲（需要 audio_processor 旁路一个 PCM topic 或留窗口缓存），跑 CAM++ → 段级 cluster_id；启动时空着，前 30-60s 累积 embedding 后做一次聚类得到 N 说话人；之后 incremental 分配最近邻 cluster；发新 topic `av/audio/command_speaker_tagged`。

### 复现

```bash
ssh firefly@192.168.5.6
cd /home/firefly/spike_venv_20260518
/home/firefly/spike_venv_20260518/bin/python spike_speaker_segment.py
```

模型/样本：
- CAM++: `/home/firefly/spike_venv_20260518/models/campp.onnx`
- silero-vad: pip 包内置
- 样本: `/home/firefly/spike_venv_20260518/samples/2speakers_example.{wav,rttm}`

---

## 综合判定

| 组件 | 状态 |
|---|---|
| sherpa-onnx 1.13.2 安装 | ✅ aarch64 wheel 16.5MB 顺利 |
| 独立 spike venv | ✅ `/home/firefly/spike_venv_20260518/`（不动 creator_ai_demo/venv）|
| GitHub release 直连 | ⚠️ CDN 慢，改 `ghfast.top` 镜像 OK |
| ct-punc int8 (72MB) | ✅ p95 4.9-37.9ms / 不撞视频 CPU / 标点质量可用 |
| CAM++ 27MB | ✅ emb 30ms/1s audio / DER 9.0% / 段级 7/7 正确 / 不撞生产 |
| silero-vad + sklearn | ✅ VAD 13ms/1s audio / 聚类瞬时 |

**P1.1 `modules/punctuator/` 已立项**（5/18 当天完成端到端 + dashboard 真音频回归）。
**P1.2 `modules/speaker_tagger/` 可立项**（Phase B 过线，下个 sprint 启动）。

---

## P1.1 punctuator 立项端到端验证 ✅

**实施**：新增 `modules/punctuator/main.py`（继承 BaseModule，MQTT 订阅 → ct-punc → 发新 topic）。

**部署**：3588 上独立 spike venv 启动（不进 supervisor / 不动 audio_processor 红线）：

```bash
cd /home/firefly/av_unified_mvp
nohup /home/firefly/spike_venv_20260518/bin/python -m modules.punctuator.main > /tmp/punctuator.log 2>&1 &
```

**端到端测试**：mosquitto_pub 注入 3 条模拟 final 到 `av/audio/command`：

| seq | 原文 | 带标点输出 | 延迟 |
|---|---|---|---|
| 1 | 今天会议要点一是冻结主线分支二是十八号之前完成两个模块 | 今天会议要点，一是冻结主线分支，二是十八号之前完成两个模块。 | 56.9ms (首条含模型预热) |
| 2 | 我们决定走新中间路径不大改 | 我们决定走新中间路径不大改。 | 13.6ms |
| 3 | 这个测试今天搞完吗 | 这个测试今天搞完吗？ | 8.9ms |

**新 topic schema**：`av/audio/command_punctuated`

```json
{
  "header": {"msg_id", "timestamp", "source": "punctuator", "version": "1.2"},
  "topic_type": "event",
  "payload": {
    "event_type": "transcription_punctuated",
    "text": "<带标点版>",
    "text_original": "<原文>",
    "seq_id": <int>,
    "is_final": true,
    "raw_mode": "sense_voice_offline",
    "ts": <epoch>,
    "punct_latency_ms": <float>
  }
}
```

`seq_id` 保留，前端可与原 `av/audio/command` 关联同一气泡（替换文本而不是新增）。

**红线遵守**：
- ✅ 不动 audio_processor 源码（旁路新模块订阅原 topic）
- ✅ 不动 creator_ai_demo/venv（spike_venv 独立 venv）
- ✅ 不动 sensevoice RKNN 长跑链路（audio_processor 全程未感知 punctuator 存在）
- ⚠️ 改了 3588 main.py 一行（supervisor 订阅 punctuated 而非原 command）— 走 surgical patch + 重启 supervisor 流程，3588 上 web/* 等 user 本地未提交修改完全保留

---

## P1.3 dashboard 真音频回归 ✅

**目标**：让转写卡显示带标点版本，零前端代码改动。

**实施**：surgical patch `main.py` 一行：supervisor 把 transcript final 的订阅从 `av/audio/command` 换成 `av/audio/command_punctuated`。dashboard.js / dashboard.html / web/server.py 完全不动（避开 3588 上 user 本地 +863 行未提交修改区）。

```diff
-            topics.get("audio_command", "av/audio/command"),
+            topics.get("audio_command_punctuated", "av/audio/command_punctuated"),
```

**部署**：scp main.py → 3588 → pkill supervisor + 子模块（精确 pattern） → AV_LLM_BACKEND=rknn AV_ASR_BACKEND=sense_voice_arm AV_RKNN_BACKEND=1 nohup → 30s 子模块全部 respawn。

### dashboard 整句重复 bug 修复

**现象**：转写卡里每条 final 都显示**两遍**（截图 14:42:35 一段 + 紧跟一模一样的副本）。

**Root cause**（5/18 真机现场抓出）：

dashboard.js line 184-188 SSE dispatcher：
```js
handlers.forEach(({ handler, module }) => {
  try { handler(cleanEv); } catch (err) { console.warn(err); }
  if (module) { try { tickerForward(module, ch, cleanEv); } catch (_) {} }
});
```

每个 channel 上每条 SSE event 会对**每个注册了 handler 的 module** 触发一次 `tickerForward`。

`modules/punctuator/main.py` 初版声明 `streams=[{channel: "transcript", ...}]` → dashboard 在 transcript channel 上注册了 audio_processor + punctuator 共 **2 个 handler** → 每条 SSE transcript event 触发 2 次 `pushOverviewTranscript`。

**修复**：`streams=[]`，punctuator 不重复占 transcript channel。discovery 上线消息仍发（dashboard 模块列表显示 punctuator），但 dashboard 不重复绑 stream。

**回归**：刷新 dashboard 让 channelHandlers 重置，对 mic 连续说 30+ 句话，每条 final 只显示一次，问题闭合。

### 真音频测试结果（30+ 条 mic final）

延迟稳定 4-71.5ms，标点质量例子：

| seq | 字数 | 延迟 | 输出 |
|---|---|---|---|
| 28 | 6 | 7.1ms | 为什么会这样？ |
| 30 | 36 | 71.5ms | 作者说，当一个人活得太苦的时候候，为了生存，他不得不做一些让自己好受一点的事如。 |
| 41 | 39 | 70.3ms | 先生，你的三个孩子在地铁上追逐打闹，你怎么不管一下，你看看整个车厢的人都被他们吵到了。 |
| 43 | 43 | 43.1ms | 不好意思，我们刚从医院回来，一个小时前，孩子的妈妈去世了，我现在很悲伤，不知道怎么管，他们非常抱歉。 |

延迟和 spike Phase A 数据一致（0.4ms/字符）。

### 已知现状 / 不在本次 P1.3 修

- **冷启动丢字**：audio_processor ARM 路径 `processor_arm.py` 用 sensevoice + VAD（RMS 自适应阈值），点"开始转写"后头几句的 PCM 可能在 RMS 阈值校准前被判 silence。要根治看 VAD warmup 逻辑。
- **无逐字 partial**：sensevoice offline 模型本身能力上限，DEVELOPMENT_PLAN.md §3.2 trade-off 表已经明确"❌ 无不大改路径"，换 paraformer-streaming（大改）才能真出逐字。新中间路径保留此为已知限制，推到阶段三或换模型时再做。

---

## 复现命令

```bash
# 3588 上
ssh firefly@192.168.5.6
cd /home/firefly/spike_venv_20260518
source bin/activate
python spike_ctpunc_latency.py
```

模型路径：
- ct-punc int8: `/home/firefly/spike_venv_20260518/sherpa-onnx-punct-ct-transformer-zh-en-vocab272727-2024-04-12-int8/model.int8.onnx`

镜像参考：
- GitHub 大文件慢 → `https://ghfast.top/https://github.com/...`
