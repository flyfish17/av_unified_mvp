# RKNN Backend 幻听 "我" 根因诊断 (D2)

**日期**：2026-05-18
**触发**：5/18 真音频回归发现 dashboard 上整段语音丢字（"渴望的不是花本身..." 等），即使 VAD 阈值 Step A 调到 0.012 仍丢。

---

## 根因（三层）

### 层 1：happyme531 SenseVoiceSmall-RKNN2 静态 shape 限制

`~/SenseVoiceSmall-RKNN2/sensevoice_rknn.py:29`

```python
RKNN_INPUT_LEN = 171   # 静态 shape，编译时固定
```

`SenseVoiceInferenceSession.__call__` 强行 pad input 到 171 帧：

```python
input_content = np.pad(
    input_content,
    ((0, 0), (0, RKNN_INPUT_LEN - input_content.shape[1]), (0, 0))
)
```

`RKNN_INPUT_LEN - input_content.shape[1]` 在长 audio 下为负 → **`ValueError: index can't contain negative values`**（08:19:55 log 实锤）。

`WavFrontend` 默认 `lfr_m=7, lfr_n=6`（每 LFR 帧 = 60ms 音频），171 帧扣掉 4 帧 query token = 167 speech 帧 ≈ **10s 音频上限**。

### 层 2：模型固有"我/i/아"幻听（你 5/12 自己记录的）

`modules/audio_processor/processor_arm.py:67-72`

```python
# happyme531 RKNN 模型在低音量段会幻听单字（"我"/"i"/"아"），
# 1-char 输出几乎都是噪声，丢弃。Mac/Jetson funasr CPU 路径也共用此过滤，
# 即使他们幻听少 — 单字结果对下游意图识别也没用。
```

这是已知的 RKNN port 缺陷：**低音量/无意义/混 silence 的输入下，encoder + CTC decode 出来 mostly blank，filter 后剩单字"我"**（推测原因：blank 之外最高概率 token 在 sensevoice vocab 早期 index，恰好对应"我"）。

### 层 3：Step A VAD 阈值 0.012 的副作用

Step A 把 `silence_threshold` 从 0.02 → 0.012 后：
- 漏触发减少（解决"间隔后说话丢字"，✅）
- **误触发增加**：环境噪音 max 0.014-0.018 段也触发 speaking → 累积几百 ms 噪音 → 送 RKNN → 幻听"我" → `[final-drop]` 丢弃

证据：08:17-08:20 共 10 次 `[final-drop] '我'`，含 6.2s 长段（08:20:23）。Step A 前同期窗口 final-drop 频率明显更低（log 已 rotate 拿不到，但 user 之前报告丢字现象 Step A 后**未消失反而看似更多**）。

---

## 修复方案矩阵

| # | 方案 | 改动 | 红线 | 性质 |
|---|---|---|---|---|
| **R1** | `min_audio_s` 守门：< 0.8s 不送 ASR | ~3 行 `processor_arm.py` | 触 audio_processor 红线 | 减少幻听喂送（治标）|
| **R2** | 切回 funasr CPU sensevoice（`AV_RKNN_BACKEND=0`）+ 重启 supervisor | env 改 + 重启 | destructive 重启 | 验证 + 临时根治（D3）|
| **R3** | silero-vad ONNX 替代 RMS VAD | 较大 `processor_arm.py` | 红线 | 中期根治（Speaker_tagger 复用）|
| **R4** | rknn_backend.py 长 audio chunked inference + 结果 concat | ~30 行 `rknn_backend.py` | 红线 + happyme531 边界要谨慎 | 治本但复杂 |
| **R5** | Step A 阈值回退到 0.014-0.016 中庸值 | 1 行 config | 无 | 平衡（不根治）|
| **R6** | min_text_chars 改为基于 audio_s 的"幻听检测"（> 2s 音频 + ≤ 2 字输出 → 标 hallucination 单独 log）| ~5 行 `processor_arm.py` | 红线 | 观测改善（不根治）|

---

## 推荐执行节奏

**短期（< 1d）**：R2 (D3) 验证锅
- 改 supervisor 启动 env `AV_RKNN_BACKEND=0`，切回 funasr CPU sensevoice
- 重启 supervisor，user 真音频再测一遍
- 如果丢字消失/明显减少 → 锅在 RKNN port，确认根因
- 如果仍丢 → 锅在 VAD 阈值/audio_processor 链路，需要 R3
- 注意：funasr CPU 在 3588 上估计 RTT 1-3s/段（比 RKNN 380ms 慢 3-8x），用户体验**变差但可接受 verify 用**

**中期（1-2d）**：R1 + R5 联合
- R1 守门 < 0.8s 不送 ASR
- R5 阈值调 0.014（中庸）
- 期望：减少幻听喂送 + 不会过度漏触
- R1 改 processor_arm.py 算 patch，请 user 显式 Y

**长期（≥ 3d，新中间路径下一段）**：R3 silero-vad 替代 RMS
- 装 silero-vad ONNX 到 audio_processor 用 venv 或独立 sidecar 模式
- 替换 RMS VAD 决策
- speaker_tagger 也要用 silero-vad，复用模型

**不推荐**：
- R4：happyme531 daemon 边界要谨慎（AGPL-3.0），且复杂
- R6：纯观测，不根治

---

## 关键判断

**Step A 0.012 不要回滚**。它解决了真正的"长间隔后说话漏触发"（已验证）。Step A 的副作用是揭露了 **RKNN backend 在边缘 audio 输入下的稳定性问题**——这是早就存在的缺陷，Step A 只是放大了它。

修复方向应该是 **R1+R5 短中期 + R3 长期** 而不是回退 Step A。
