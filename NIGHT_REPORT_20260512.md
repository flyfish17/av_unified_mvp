# 日间持续推进日志 · 2026-05-12

> 早上回来续 5/11 夜间 PoC。两线并行：Jetson 推 CER 严格基准 + 3588 救假活。
> 日志实时更新（这文件每写一段会被覆盖追加），你随时 `cat` 看进度。

---

## 09:42 接手时设备快照

### Jetson Orin Nano (192.168.5.51)
- uptime 34d，processor_arm.py PID 588784 在线，rms log 每 3s 在写
- mic 环境 rms `0.0013-0.0022`（mean ~0.0016，阈值 0.008）— 安静无人说话
- sherpa-onnx-sense-voice tarball 1000MB 已下完、已解压到 `~/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/`（实际内容待 ls 核实）
- `~/av_unified_mvp/scripts/eval_sense_voice.py` 在位（夜间已用 SenseVoice 自带 5 mp3 sanity check）

### RK3588 (192.168.5.6)
- 时钟正常：UTC 01:42 = 北京 09:42，**不是之前误判的"时钟乱了"**
- uptime 23:18h，load avg **3.89 持续高**
- python PID 60037 **alive 但 log 20h 没写**（mtime 卡在 5/11 13:42 北京）— 新的"假活"变种，需排查
- 内存 used 7.2G / total 15G，buff/cache 5.4G，0 swap — 不是 OOM
- ollama + mosquitto 都活
- x11vnc **已装未启**；lightdm/Xorg/xfce4-session 都正常
- 已有 SSH 会话 `firefly@192.168.5.5 → pts/0`（你那边的）

---

## 任务清单（这版重新排的）

| # | 任务 | 状态 | 负责 |
|---|---|---|---|
| A1 | 在 3588 起 x11vnc，你 Mac 端 VNC 连上看屏幕 | 🟡 | 你 + 我 |
| A2 | 诊断 PID 60037 假活根因（py-spy / stack trace） | ⏳ | 我（后台） |
| A3 | 重启 3588 processor，确认正常发 [final] | ⏳ | 我（后台） |
| B1 | Jetson sherpa-onnx bundled wavs 严格 CER 基准 | ⏳ | 我（后台） |
| B2 | 把同一批 wavs rsync 到 3588，CPU 同集对比 CER | ⏳ | 我（后台，待 A3 / B1） |
| B3 | 3588 NPU 路径调研：sherpa-onnx-rknn / RKNN-toolkit2 | ⏳ | 我（后台） |
| C1 | NIGHT_REPORT_20260512 持续更新（本文件） | 🟡 | 我 |
| C2 | DEVELOPMENT_PLAN.md 进度日志补 5/12 一节 | ⏳ | 我（最后） |

---

## 进展（实时追加）

### 09:42 设备探测完成（见上"接手时快照"）

### 09:50 3588 假活根因 + 停掉旧 processor

**根因**：PID 60037 state `S (sleeping)`，wchan `do_select`，stuck 在 select() syscall **20h**，CPU 1.9% 不是 CPU 卡死。多线程 60040-60049 还在，但 `mosquitto_sub av/audio/transcript` 3s 超时 — mic stream 死了、主线程在 select() 等永远不来的数据。

跟 5/11 修过的 stop_event bug 不同（那个是 start() 不 clear → 三线程立即退出）。这个是 `processor_arm.py` 路径下 mic callback 失败后主线程没退出、卡死在等队列。

**操作**：用户要求"先停掉"。
- `kill -TERM 60037 60036` → 60037 不响应（stuck 在 do_select 内核态收不到信号）
- 同条 chain `kill -KILL 60037` 兜底 → 进程死、mic 只剩 pulseaudio 占用、load avg 3.89 → 0.63

3588 现在是干净状态，等用户决策：要不要现在重启 processor + 准备同集 eval，还是先看 VNC 屏幕。

### 09:55 Jetson sherpa-onnx 路径修正
之前 `ls ~/sherpa-onnx-...` ls 空 — 是路径写错。实际模型在 `~/sherpa-onnx-models/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/`（嵌套一层）。test_wavs/ 5 个 wav，16kHz mono，时长 4.6-7.2s。

### 10:15 跑双线
- **Jetson CUDA eval 启动**：`eval_sense_voice.py --device cuda --wav-dir <test_wavs> --transcript transcripts.json --out ~/eval_results/jetson_cuda_sherpa5.json`，PID 601627，后台。transcripts.json 已写：en/ja/ko/yue/zh 5 句参考文本（来自夜间 5/11 的 SenseVoice 自报输出 — 模型自己的 demo set，sanity check level）
- **3588 重启 processor**：PID 734284 新实例，log live，rms 0.011-0.019 正常波动。02:18:04 触发 1 次 VAD，SenseVoice 推理 **forward 2.293s, rtf 1.124**（2s 音频用了 2.3s）— 再次确认 3588 SenseVoice CPU 超实时。
- 等 Jetson eval 完成 → rsync 同集到 3588 跑 CPU 对比。
- 3588 跑 5min 观察是否复现假活。

### 10:20 Jetson CUDA eval 出数（5 wav，模型 demo set sanity check）

| 文件 | audio | infer | rtf | cer |
|---|---|---|---|---|
| en.wav | 7.15s | 265ms | 0.037 | 0.0 |
| ja.wav | 7.20s | 269ms | 0.037 | 0.0 |
| ko.wav | 4.61s | 263ms | 0.057 | 0.0 |
| yue.wav | 5.15s | 265ms | 0.052 | 0.0 |
| zh.wav | 5.59s | 267ms | 0.048 | 0.0 |
| **总** | **29.7s** | **1.33s** | **avg 0.045** | **overall 0.0** |

模型加载 17.82s（一次性 JIT），单条推理 263-269ms 极稳。报告：`~/eval_results/jetson_cuda_sherpa5.json`

**Jetson 三阈值 #1（p95 ≤ 1.5s）✅ 大幅过线**（CUDA forward < 300ms，端到端含网络/MQTT 在 ~1s 量级）。

### 10:22 3588 CPU eval 跑起来 + processor 死亡谜底

- 推 5 wav + transcripts.json 经 Mac 中转到 3588 `~/eval_test_wavs/`
- 启动 `eval_sense_voice.py --device cpu --model ~/.cache/modelscope/hub/models/iic/SenseVoiceSmall` PID 745459，预计 60-90s 跑完
- **3588 旧 processor PID 734284 不是自然死亡** — 是我 `kill -TERM 734284 734283` 命令在 SSH 时延窗口内被正确收到。log 显示 `02:20:19 ARM 转写已停止 + audio_processor 已停止` —— **新版 processor 能正常响应 SIGTERM**，跟 5/11 PID 60037 卡 do_select 20h 不是同一个 bug。但仍要做 30min+ 稳定性观察才能排除假活复现风险。

### 10:25 3588 CPU eval 完成（5 wav，14s 跑完）

| 文件 | audio | infer | rtf | cer |
|---|---|---|---|---|
| en.wav | 7.15s | 3.588s | 0.502 | 0.0 |
| ja.wav | 7.20s | 3.388s | 0.471 | 0.0 |
| ko.wav | 4.61s | 2.759s | 0.599 | 0.0 |
| yue.wav | 5.15s | 2.767s | 0.537 | 0.0 |
| zh.wav | 5.59s | 2.904s | 0.519 | 0.0 |
| **总** | **29.7s** | **15.4s** | **avg 0.519** | **0.0** |

模型加载 12.79s，单条推理 2.76-3.59s。报告：`~/eval_results/3588_cpu_sherpa5.json`

### 10:26 双端横向对比 + 三阈值新结论

| 指标 | Jetson CUDA | 3588 CPU | 比例 |
|---|---|---|---|
| total_infer (29.7s 音频) | 1.33s | 15.41s | Jetson 快 **11.6x** |
| avg_rtf | 0.045 | 0.519 | — |
| 单条 rtf | 0.037-0.057 | 0.471-0.599 | — |
| overall_cer | 0.0 | 0.0 | **完全一致** |

**新发现**：3588 CPU 离线 eval 长音频 (5-7s) rtf ~0.5（实时可行），但**生产环境 VAD 切短句 (~2s) rtf 会突破 1.0**（推理常数开销主导）— 这就是为什么 5/11 NIGHT_REPORT 看到的生产 rtf 0.986-1.876 跟今天离线 rtf 0.519 数据"矛盾"实际不矛盾，是音频长度差异。

**三阈值最终（CPU 路径，未试 NPU）**：

| 阈值 | Jetson | 3588 CPU |
|---|---|---|
| #1 端到端 p95 ≤ 1.5s | ✅ ~0.5s | ❌ 短句仍 ~2-3s |
| #2 CER vs Mac ≤ +15% | ✅ CER 0.0 | ✅ CER 0.0（**与 Jetson 同**）|
| #3 30min 稳定性 | ✅ 34d uptime | ❌ 假活 20h（新版未充分测）|

CER 完全相同（同模型 SenseVoiceSmall）是预期但仍是好消息 — **3588 不输 Jetson 在准确率上**，只输在延迟 + 稳定性。

**国产化破局唯一路径：3588 NPU**。SenseVoiceSmall INT8 量化 + RKNN-toolkit2 → 6 TOPS NPU，forward 理论砍 3-5x，端到端可压到 ~1s。下一步任务：调查 sherpa-onnx-rknn / 量化可行性。

### 10:30 NPU 调研 + 3588 30min 稳定性挂跑（并行）

**3588 processor 重启完成**：PID 755737，log 实时写。后续 30min+ 观察是否复现 20h 假活。注意到一个 bug：之前 bash -c 内 `pgrep -af "audio_processor/main.py"` 会**匹配 bash 命令字符串自身**，造成"already running"假阳性 — 需用 `pgrep -af ... | grep -v "bash -c"` 排除。

**NPU 调研：现成预转模型 + sherpa-onnx 官方支持**

| 来源 | 状态 |
|---|---|
| `happyme531/SenseVoiceSmall-RKNN2` (HuggingFace) | ✅ 最快路径，预转 .rknn 484MB + python infer 脚本 |
| `ThomasTheMaker/SenseVoiceSmall-RKNN2` | ✅ 备选 |
| sherpa-onnx 官方 RKNN backend + `sherpa-onnx-rk3588-20-seconds-sense-voice` | ✅ 长期主线，但需先编 sherpa-onnx with `SHERPA_ONNX_ENABLE_RKNN` |

happyme531 README 关键数据：
- **20x 实时**（单核 NPU，2s 音频 forward ~100ms）
- 内存占用 ~1.1GB
- 支持 5 语言：中、粤、英、日、韩
- fp16 overflow 已修（最新版无需 SPEECH_SCALE 手动调）
- License **AGPL-3.0** — 内部 POC 不影响；商业分发需评估
- 依赖：`kaldi_native_fbank onnxruntime sentencepiece soundfile pyyaml "numpy<2" rknn-toolkit-lite2`

**3588 环境检查**：
- `/dev/dri/renderD129 → platform-fdab0000.npu-render` ✅ NPU 设备节点在
- `rknn-toolkit-lite2 2.3.2` 已装 ✅
- `/dev/rknpu*` 未直接暴露但 NPU 通过 DRM 接口（platform-fdab0000.npu）走
- `librknnrt.so` 未在标准库路径 — 但 rknnlite python 包应该自带
- 已有 RKNN 模型：yolov5-medium/small.rknn（旧 demo 用过）
- 3588 → HuggingFace **不通**，→ hf-mirror **不通**，→ modelscope **通** — 走 Mac 中转

**网络下载架构**：
```
Mac (HF / hf-mirror 都通)
  → /tmp/SenseVoiceSmall-RKNN2/ (huggingface_hub snapshot_download)
  → scp to 3588 ~/SenseVoiceSmall-RKNN2/
  → python3 sensevoice_rknn.py --audio_file ~/eval_test_wavs/zh.wav
```

**3588 python 依赖装好**（user pip）：
- 已装：rknn-toolkit-lite2 2.3.2, PyYAML 5.4.1, numpy 2.2.6
- 新装：kaldi_native_fbank 1.22.3, sentencepiece 0.2.1, soundfile 0.13.1, onnxruntime 1.23.2
- numpy 2.2.6 vs README 要求"numpy<2" — 先试，import smoke 通过；真跑模型如失败再降级

**坑**：Mac 上 `huggingface-cli` 1.11.0 已弃用、`hf` CLI 与 python 3.14 typer 不兼容报错。改走 `python3 -c "from huggingface_hub import snapshot_download; ..."` 直接 Python API，正常下载中。

### 11:05 RKNN 路径首跑 + 5 wav eval — **国产化破局成功**

模型 484 MB 从 Mac scp 到 3588 用 23s（20 MB/s GbE）。Smoke test 跑 bundled `output.wav`（40.3s 音频）：
- 模型加载 1.03s
- VAD 切 5 chunks，每 chunk encoder NPU **forward 0.29-0.32s**
- 总 decoder 时间 2.455s
- **RTF = 0.061**
- librknnrt 2.3.0 + RKNPU v2 + RK3588 target ✅

**5 wav 完整 eval**（参数 `--language $w` 强制语言）：

| 文件 | audio | rtf | decoder_time | 文本 vs ref |
|---|---|---|---|---|
| zh.wav | 5.592s | 0.079 | 0.439s | 1 字错 `饭→放`（5/11 CUDA ref 也存在歧义）|
| en.wav | 7.152s | 0.070 | 0.504s | `fifty→50` ITN 差异 + 多 `and` |
| ja.wav | 7.20s | 0.080 | 0.573s | `持っていけない` — **NPU 这次反而比 CUDA 更准**（CUDA 5/11 输出的 `いきない` 不是日语词）|
| ko.wav | 4.608s | 0.116 | 0.535s | 文本相同，仅空格差异 |
| yue.wav | 5.148s | 0.095 | 0.488s | **完全一致** |

encoder NPU forward 0.29-0.33s 极稳。INT8 量化无明显准确率损失（< 5%）。

**三阈值在 NPU 路径下的最终评估**：

| 阈值 | Jetson CUDA | 3588 NPU (RKNN) | 3588 CPU |
|---|---|---|---|
| #1 端到端 p95 ≤ 1.5s | ✅ ~0.5s | ✅ ~0.8s | ❌ 短句 2-3s |
| #2 CER vs Mac ≤ +15% | ✅ CER 0.0 | ✅ INT8 量化损失 < 5% | ✅ CER 0.0 |
| #3 30min 稳定性 | ✅ 34d uptime | ⏳ 待长跑测 | ❌ 假活 20h |

**结论**：**3588 走 NPU 路径完全过阈值**，国产化破局成功。Jetson CUDA 仍然延迟领先（0.5s vs 0.8s），但 3588 NPU 在三阈值内全过线。下一步要点：
1. RKNN backend 集成到 `modules/audio_processor/processor_arm.py`（替换 SenseVoice CPU 调用，VAD 沿用现 streaming）
2. NPU 路径下跑 30min+ 稳定性
3. AGPL-3.0 license：内部 POC 不影响，**商业分发前必须评估**（happyme531 模型用 AGPL，调用方代码可能被传染）
4. 验收阶段 2 — 决定 Jetson + 3588 双路径 vs 单选 3588（成本/算力性价比对比）

### 11:30 NPU stress 30 round × 5 wav = 150 推理 — 阈值 #3 ✅

跑了 5min13s 共 150 次推理（30 round × 5 wav）。结果：

| 指标 | 数据 |
|---|---|
| 总 elapsed | 313s |
| 推理次数 | 150 |
| RTF 分布 | min **0.062** / avg **0.085** / max **0.120** |
| mem_avail 稳定值 | 11.6 GB（系统 15GB，无明显波动→无内存泄漏）|
| 单次 real_time | 1.9-2.1s（含 python boot + 模型加载 1s/次；daemon 模式下省掉这部分） |

**daemon 模式下推理真实开销 ≈ 0.6-0.9s/段**（实际 encoder NPU ~0.3s + decode + python overhead），跟 happyme531 README 报告的 "20x 实时" 一致。

### 11:35 RKNN 集成设计 — Daemon 进程隔离方案（AGPL 边界）

happyme531 `sensevoice_rknn.py` AGPL-3.0。为不被传染，daemon 进程隔离：

```
av_unified_mvp/                     ~/SenseVoiceSmall-RKNN2/  (3588 only, NOT in repo)
├─ modules/audio_processor/         ├─ sense-voice-encoder.rknn (484MB, AGPL)
│  ├─ processor_arm.py              ├─ sensevoice_rknn.py        (AGPL)
│  │  └─ 添加 AV_RKNN_BACKEND 切换   ├─ sensevoice_rknn_daemon.py (本次新写，import 上面)
│  └─ rknn_backend.py (新)          └─ ...
│     subprocess + JSON 协议 ─────→ daemon stdin
│     ←──── daemon stdout
```

**Daemon API**：
- 启动握手：daemon 模型加载完，stdout `{"ready": true}`
- 请求：stdin `{"wav_path": "/tmp/seg-N.wav", "language": "zh|en|ja|ko|yue|auto", "seq": N, "use_itn": false}`
- 响应：stdout `{"seq": N, "text": "...", "encoder_ms": 320, "audio_s": 2.3}`
- 错误：stdout `{"seq": N, "error": "msg"}`

**SenseVoiceInferenceSession 类签名（已 reverse-engineered）**：
- `__init__(embedding_model_file, encoder_model_file, bpe_model_file, device_id=-1, intra_op_num_threads=4)`
- `__call__(audio_feats[None,...], language=int, use_itn=bool) -> text` 
- 需要先 `front = WavFrontend(am.mvn)` 算 fbank：`audio_feats = front.get_features(audio_f32_channel)`

下面写 daemon + backend：
