# 路径 β · paraformer-streaming RKNN 实施计划（B 计划）

**日期**：2026-05-19
**性质**：实施计划（不动代码）
**触发**：User 5/19 测试 funasr CPU 路径丢字消失后判断"NPU 闲置 = 没充分发挥硬件能力"，要求"开 B 计划，只做计划"。

---

## 目标

一次性解决 4 个问题：

| # | 问题 | 当前状态 | β 后 |
|---|---|---|---|
| 1 | **NPU 利用** | 0%（funasr CPU 路径绕过 NPU）| ✅ RK3588 NPU 跑 paraformer-streaming |
| 2 | **audio_processor CPU 占用** | 107% (CPU 推理代价大)| 预期 < 10% |
| 3 | **逐字 partial（"逐词蹦"）** | ❌ 整段 final，1-3s RTT 体感"卡死" | ✅ 600ms chunk partial，逐字蹦 |
| 4 | **标点（ITN）** | ⚠️ 走 punctuator 旁路（额外 10-50ms 延迟 + 多一个模块）| ✅ 模型原生输出标点 |

**额外效果**：dashboard 转写卡 UX 接近商业 ASR 产品（讯飞 / 阿里）水平。

---

## 现成资源（5/18 P0.8 调研报告 §2 已确认）

| 资源 | 路径/来源 | 大小 | License | 状态 |
|---|---|---|---|---|
| **sherpa-onnx-paraformer-zh-streaming RK3588 预编译模型** | sherpa-onnx GitHub release `sherpa-onnx-rk3588-paraformer-zh-streaming-2025-10-07` | ~80MB | MIT | sherpa-onnx 一等公民 |
| 流式 chunk 配置 | `[0, 10, 5]` → 600ms 出 partial | — | — | sherpa-onnx 默认 |
| sherpa-onnx 1.13.2 | 已装在 `/home/firefly/spike_venv_20260518/` | 16.5MB wheel | Apache-2.0 | 复用 |
| 原生 ITN 标点 | paraformer 模型自带 | — | — | 不需要 punctuator 旁路 |

**关键判断**：所有依赖**spike_venv 已就绪**，不需要装新包，只需拉模型。

---

## 红线评估

| 红线 | 是否触动 | 缓解 |
|---|---|---|
| 不动 audio_processor 长跑稳态 | ⚠️ 部分触动 | 新建 `processor_paraformer_streaming.py` 旁路实现，**不改 processor_arm.py**，用 `AV_ASR_BACKEND=paraformer_streaming` env 切换 |
| 不动 sensevoice RKNN 长跑链路 | ✅ 不触动 | RKNN backend 保留，env 控制选择 |
| 不动 creator_ai_demo/venv | ⚠️ paraformer 模型可放 spike_venv 但 processor 跑在 audio_processor 进程内（用 creator_ai_demo/venv 的 python） | 选项：(a) sherpa-onnx 装到 creator_ai_demo/venv（破红线）；(b) processor_paraformer_streaming 跑在独立 spike_venv sidecar 进程，audio_processor 通过 IPC 调（复杂）|
| 不动 3588 main.py | ✅ 不触动 | audio_processor 是 spawn 进程，env 由 main.py 传递；只需 `AV_ASR_BACKEND` env 多支持一个值 |

**核心 trade-off**：要让 paraformer-streaming 跑在 audio_processor 进程内（最干净），就要把 sherpa-onnx 装到 creator_ai_demo/venv，**触红线 1 次**。备选方案是独立 sidecar 进程（复杂、IPC 开销）。

**推荐**：装到 creator_ai_demo/venv。理由：
- sherpa-onnx 是 Apache-2.0 自包含 wheel，引入新依赖风险可控
- audio_processor 现已用 funasr（更重 + 同样大依赖链），加一个 sherpa-onnx 不破坏稳定性
- 备份当前 venv state，失败可回滚（pip freeze → requirements_pre_beta.txt）

---

## 实施分解（5 阶段 + 验证 + 回滚）

### 阶段 0 · spike 验证（gating，不过线不进阶段 1）

**任务**：在 `/home/firefly/spike_venv_20260518/` 跑 sherpa-onnx paraformer-streaming，对 mic 实时音频压测。

**Spike 项**：
1. 下载模型到 `~/spike_venv_20260518/models/paraformer-streaming-rk3588/`
2. 写 `spike_paraformer_streaming.py`：sherpa-onnx OnlineRecognizer + 一段已知中文音频，看 partial 频率、RTT、内存
3. 测中文准确率 vs sensevoice（用 5/19 早上 user 录的"沉默成本/原生家庭/匮乏"段对比）
4. 测 3588 NPU 占用（看 `cat /sys/kernel/debug/rknpu/load` 或类似），确认是否真上 NPU
5. 测 audio_processor CPU 预期（独立进程跑 streaming inference + IPC 模拟）

**Gating 标准**：
- partial 间隔 ≤ 800ms（接近 sherpa-onnx 文档 600ms）
- 中文准确率不低于 sensevoice 90%
- NPU 加载 > 0（确认走 NPU 不退回 CPU）
- audio_processor 预期 CPU < 30%（粗算 100% / 3-5x NPU 加速）

**工时**：0.5d
**产出**：`docs/research/spike-paraformer-streaming-3588-20260519.md`（Phase A 类似结构）

### 阶段 1 · 装 sherpa-onnx 到 creator_ai_demo/venv（红线触动 1）

**前置**：
- 备份 venv：`/home/firefly/creator_ai_demo/venv/bin/pip freeze > ~/requirements_pre_beta_20260519.txt`
- 备份 site-packages 体积：`du -sh ~/creator_ai_demo/venv/`

**动作**：
- `~/creator_ai_demo/venv/bin/pip install sherpa-onnx==1.13.2`
- 验证：`~/creator_ai_demo/venv/bin/python -c "import sherpa_onnx; print(sherpa_onnx.__version__)"`
- 验证既有依赖未被升级：`~/creator_ai_demo/venv/bin/pip check`

**风险**：sherpa-onnx 引入 onnxruntime 等可能升级 numpy/scipy；funasr 对 numpy 版本敏感
**缓解**：装前 `pip freeze` 对比装后；若 numpy/scipy 升级，pin 回原版本

**工时**：0.2d
**回滚**：`pip uninstall sherpa-onnx` + `pip install -r ~/requirements_pre_beta_20260519.txt --force-reinstall`

### 阶段 2 · 写 `modules/audio_processor/processor_paraformer_streaming.py`

**新文件**（不改 processor_arm.py）：仿 processor_arm.py 结构，但用 `sherpa_onnx.OnlineRecognizer`：

```python
# 伪代码骨架
class AudioProcessorParaformerStreaming:
    def __init__(self, audio_cfg):
        self.recognizer = sherpa_onnx.OnlineRecognizer.from_paraformer(
            tokens=..., encoder=..., decoder=...,
            num_threads=1, provider="cpu",  # NPU 通过 rknpu_provider
            sample_rate=16000,
            feature_dim=80,
            decoding_method="greedy_search",
            chunk_size=10,  # 5/18 调研 [0, 10, 5]
            ...
        )
        self.stream = self.recognizer.create_stream()
        # mic / pcm 拉取同 processor_arm.py
    
    def start(self, callback):
        # 启 InputStream（同 processor_arm 复用 _find_logitech_device）
        # callback 用 PartialEvent / FinalEvent 两种
    
    def _worker_loop(self):
        # 每 60ms 帧累积 0.5s → stream.accept_waveform(samples)
        # 调 recognizer.decode_streams([self.stream])
        # text = self.stream.result.text
        # is_endpoint = self.recognizer.is_endpoint(self.stream)
        # if text 变化：发 partial（带 is_final=False）
        # if is_endpoint：发 final（带 is_final=True），reset stream
```

**关键点**：
- partial 频率：每 decode 一次（~600ms）触发一条 partial（如果 text 有变化）
- final 触发：sherpa-onnx 的 endpoint detection（VAD 内置）
- text revision 处理：partial 文本可能在下一个 chunk 被修正，前端需要 replace 不 append

**modules/audio_processor/main.py 改动**：line 30-36 加 backend 分支：

```python
if _ASR_BACKEND == "paraformer_streaming":
    from modules.audio_processor.processor_paraformer_streaming import (
        AudioProcessorParaformerStreaming as AudioProcessor
    )
elif _ASR_BACKEND == "sense_voice_arm":
    from modules.audio_processor.processor_arm import AudioProcessorARM as AudioProcessor
else:
    from modules.audio_processor.processor import AudioProcessor
```

**工时**：1.5d
**风险**：sherpa-onnx OnlineRecognizer API 与文档可能有小出入，spike 阶段已蹚过；text revision 边界 case 需调

### 阶段 3 · 改 protocol（partial 高频上屏）

**当前**：
- `av/audio/partial`（partial）发送频率：FunASR 2pass-online 不定期；sensevoice ARM 不发 partial
- `av/audio/command`（final）：整段触发一次

**β 后**：
- `av/audio/partial`：每 600ms partial（含 text 累积 + 可能的 revision）
- `av/audio/command`：endpoint 触发的 final（带 ITN 标点）

**协议字段**：
- partial payload 加 `revision: int`（递增 ID）让前端识别"同一段的 partial 修正"
- final payload 不变，但 `text` 已含标点（不需要 punctuator 旁路；punctuator 可保留作 sensevoice 路径用）

**punctuator 处理**：
- env `AV_ASR_BACKEND=paraformer_streaming` 时，punctuator 可关（paraformer 自带标点）
- env 切回 `sense_voice_arm` 时 punctuator 自动接管（已订阅 `av/audio/command`）

**工时**：0.5d

### 阶段 4 · 改 dashboard.js partial 显示逻辑（5/12 之前已存在但未使用）

dashboard.js 现有 partial channel 渲染：
- line 870-880 `else if (ev.text)` 分支处理非 final partial：`appendChild(span)` 到 `.live`
- 现状是 append 模式，FunASR 2pass-online 的"非累积"partial 增量

**β 改动**：
- partial 改 **replace by revision_id** 模式：同 revision_id 的 partial 替换 `.live` 内容
- final 时 `.live` 清空 + `.finals` append（与现有逻辑一致）

**风险**：dashboard.js 是 user 本地 +370 行修改区，需 surgical patch 不冲突
**工时**：1d

### 阶段 5 · supervisor 启动 env + 测试

**改 `scripts/3588-demo-start.sh`**：增加新选项

```bash
# Default: funasr CPU (5/19 stable)
# AV_ASR_BACKEND=sense_voice_arm AV_RKNN_BACKEND=0  ← 现在
# β: paraformer-streaming RKNN
# AV_ASR_BACKEND=paraformer_streaming  ← β 新选项
```

**测试 plan**：
- 单元：spike_paraformer_streaming.py 重跑 + audio 多语种回归（粤/日/韩 用 sensevoice fallback）
- 集成：mic 实时压测 30 分钟，观察 NPU 占用、CPU 占用、温度、partial 延迟稳定性、dashboard "逐字蹦"体感
- 回归：对 mic 重复 5/19 用过的"原生家庭/沉默成本/匮乏"等长句，对比 funasr CPU 路径准确率
- 长跑：6h sustain（仿 5/14 VLM sustain 模式），看是否稳定不退化

**工时**：1d

### 总工时

| 阶段 | 工时 |
|---|---|
| 0. spike 验证（gating）| 0.5d |
| 1. pip install + 备份 | 0.2d |
| 2. processor_paraformer_streaming.py | 1.5d |
| 3. protocol partial 频率 | 0.5d |
| 4. dashboard.js partial replace | 1.0d |
| 5. supervisor env + 测试 | 1.0d |
| **合计** | **4.7d** |

---

## 回滚预案（每阶段独立可回滚）

| 失败点 | 回滚方式 |
|---|---|
| 阶段 0 spike 不过线 | 不进阶段 1，保留 funasr CPU 路径 |
| 阶段 1 pip install 破坏 venv | `pip install -r ~/requirements_pre_beta_20260519.txt --force-reinstall` |
| 阶段 2 paraformer 跑不通 | `AV_ASR_BACKEND=sense_voice_arm` 切回，不删 processor_paraformer_streaming.py（保留代码继续 debug）|
| 阶段 4 dashboard.js patch 失败 | git checkout 该文件回到 5891a31 |
| 整体失败 | `git checkout v1.1-funasr-cpu-stable-20260519` + `bash scripts/3588-demo-start.sh --force` |

**最快回滚**：`AV_ASR_BACKEND=sense_voice_arm AV_RKNN_BACKEND=0 bash scripts/3588-demo-start.sh --force`（30 秒切回 funasr CPU）

---

## 多语言保留方案

paraformer 中文专攻。多语言场景的处理：

**双 backend 共存 + env 切换**：
- 默认 `AV_ASR_BACKEND=paraformer_streaming`（中文主战场，含 partial）
- 客户场景需要粤/日/韩/英 → `AV_ASR_BACKEND=sense_voice_arm AV_RKNN_BACKEND=0`（funasr CPU sensevoice）
- 切换无需重新部署，只需 supervisor 重启

**长期**：未来如出现支持 partial 的多语言流式 ASR（sense-voice streaming 上游 / 或 whisper-streaming RK3588 port），再做第三 backend 接入。

---

## 关键里程碑（5d 计划，按工作日计）

- Day 1 上午：阶段 0 spike + 报告
- Day 1 下午：阶段 1 pip install + 验证
- Day 2-3：阶段 2 写 processor_paraformer_streaming.py
- Day 3 下午：阶段 3 protocol 改
- Day 4：阶段 4 dashboard.js patch + 联调
- Day 5：阶段 5 supervisor + 测试 + 长跑

---

## User 拍板请求

本计划提交给 user，待拍板：
1. **是否启动路径 β**？（投入 ~5d）
2. **触红线点 "sherpa-onnx 装到 creator_ai_demo/venv"** 是否授权？（备选方案 sidecar 进程复杂度大幅上升）
3. 中期 / 客户演示前哪个时间窗口启动？
