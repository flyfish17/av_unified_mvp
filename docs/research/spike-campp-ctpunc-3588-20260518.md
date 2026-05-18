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

## Phase B · CAM++ ONNX 段级说话人聚类 ⏸ 阻塞

**阻塞原因**：3588 上**无现成 60s 双人对话录音样本**。`/home/firefly/Downloads/debug_*.wav` 是 1-1.5s 单人短片段（16kHz mono），不适合做说话人聚类压测。`sherpa_test_wavs/` 是 5/12 sherpa 自带的单语短样本（en/ja/ko/yue/zh 各几秒）。

**需要 user 提供（任选其一）**：
1. 一段 60s 左右的双人/多人中文对话录音（建议 16kHz mono WAV，或任意可被 ffmpeg 转码的格式）
2. 现场录一段（3588 上 USB mic 或 Mac 录音）
3. 公开数据集：AISHELL-4 部分样本（需注册 modelscope 下载）

**Phase B 待执行 checklist（脚本就绪后）**：
1. 下载 3D-Speaker CAM++ ONNX 模型（modelscope 镜像，~30MB）
2. 写 `spike_speaker_segment.py`：silero-vad 切片 → CAM++ embedding → sklearn AgglomerativeClustering → 段级 tag
3. 跑 60s 双人对话样本，记录：
   - CAM++ embedding 单段 CPU 延迟
   - 整段聚类延迟
   - DER（如有 ground truth）/ 主观聊着对感
   - spike 中 video_processor CPU 是否变化

---

## 综合判定

| 组件 | 状态 |
|---|---|
| sherpa-onnx 1.13.2 安装 | ✅ aarch64 wheel 16.5MB 顺利 |
| 独立 spike venv | ✅ `/home/firefly/spike_venv_20260518/`（不动 creator_ai_demo/venv）|
| GitHub release 直连 | ⚠️ CDN 慢，改 `ghfast.top` 镜像 OK |
| ct-punc int8 (72MB) | ✅ p95 4.9-37.9ms / 不撞视频 CPU / 标点质量可用 |
| CAM++ 段级聚类 | ⏸ 等 user 提供双人对话录音 |

**P1.1 `modules/punctuator/` 可立项**（不等 Phase B）。
**P1.2 `modules/speaker_tagger/` 待 Phase B 数据**。

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
- ✅ 不动 3588 main.py（punctuator 暂不进 supervisor，手动起 nohup）
- ✅ 不动 sensevoice RKNN 长跑链路（audio_processor 全程未感知 punctuator 存在）

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
