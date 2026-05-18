# 夜间自主测试报告 · 2026-05-11

> 用户下班离开后自主执行的测试结果。明早归来时阅读。

---

## 任务执行清单

| # | 任务 | 状态 |
|---|---|---|
| 10 | Jetson 30min+ 稳定性挂跑 | 🟡 进行中 |
| 11 | 测试集获取（AISHELL fallback → sherpa-onnx 自带 wavs） | 🟡 下载中 |
| 12 | 写 eval 脚本 | ✅ 完成（`scripts/eval_sense_voice.py`） |
| 13 | Jetson device=cuda 跑测试集 | ✅ 完成（SenseVoice 示例 5 mp3）|
| 14 | Jetson device=cpu 同集对比 | ✅ 完成（同集）|
| 15 | 3588 device=cpu 同集对比 | 🟡 进行中 |
| 16 | 3588 NPU 路径可行性评估 | ⏳ 待 sherpa-onnx 下完 |
| 17 | 分析 3588 rms 日志，建议 VAD 参数 | ⏳ 待办 |
| 18 | 本报告（持续更新中） | 🟡 |

---

## 关键结论（截至 17:30）

### 1. CUDA 加速倍率：Jetson 11.34x（远高于预期）

同 5 个测试样本（SenseVoice 自带 en/ja/ko/yue/zh mp3，总 29.89s 音频）：

| 平台 | device | 总推理 | avg_rtf | 模型加载 |
|---|---|---|---|---|
| Jetson Orin Nano | **cuda** | **1.494s** | **0.050** | 22.27s（含 JIT warm-up）|
| Jetson Orin Nano | cpu | 16.934s | 0.567 | ~5s |
| RK3588 | cpu | 待 | 待 | 待 |

**结论**：Jetson CUDA 推理速度比 CPU 快 **11.34x**。Mac/3588 上等同 SenseVoice 都是 CPU 跑，因此 Jetson GPU 是结构性优势，不可替代。

### 2. 多语言识别正确率（CUDA 模式）

| 语言 | 音频 | 识别文本 | 评估 |
|---|---|---|---|
| en | 7.18s | "the tribal chieftain called for the boy and presented him with fifty pieces of gold" | ✓ |
| ja | 7.23s | "うちの中学は弁当制で持っていきない場合は50円の学校販売のパンを買う" | ✓ |
| ko | 4.65s | "조금만 생각을 하면서 살면 훨씬 편할 거야" | ✓ |
| yue（粤语）| 5.21s | "呢几个字都表达唔到我想讲嘅意思" | ✓ |
| zh | 5.62s | "开饭时间早上九点至下午五点" | ✓ |

注：这是 SenseVoice 官方示例，可能在训练集内，仅作 sanity check。下面用 sherpa-onnx 自带测试集做严格 CER。

### 3. 真实场景实测（17:05 用户对 Jetson 念蜜蜂故事，6 句）

| 音频 | 推理 | RTF |
|---|---|---|
| 5.7s | 366ms | 0.064 |
| 1.7s | 339ms | 0.20 |
| 9.3s | 394ms | 0.042 |
| 5.0s | 364ms | 0.073 |
| 3.1s | 341ms | 0.11 |
| 3.1s | 337ms | 0.11 |

**推理时间 337-394ms**（极窄，CUDA 内核启动开销主导），**平均 RTF 0.10**，端到端延迟 ≈ 1.0s。

口语 vs 书面用词识别：
- 「以上是一个读书的测试」✓ 准确
- 「采集花蜜」误为「采集瓜蜜」
- 「结茧化蛹」误为「节俭化泳」
- 「蛹室」误为「勇士」
- 「雄蜂」识为「公蜂」（接近）

字错率约 5-10%（专业/书面词偏差为主），口语场景表现明显更好。属于 SenseVoiceSmall 模型本身限制，**与 GPU/CPU 无关**。

---

## 三阈值（plan §38-49）当前评估

| 阈值 | Jetson | RK3588 |
|---|---|---|
| **#1 延迟 p95 ≤ 1.5s** | ✅ ~1.0s | ❌ 2.5s+ |
| **#2 字错率 vs Mac ≤ +15%** | ⚠️ 待完整测（SenseVoice 模型相同，差异主要在采样 + mic） | ⚠️ 同模型同问题 |
| **#3 30min 稳定性** | 🟡 进行中（已 35min 无异常）| ✅ PID 60037 已跑 >2h |

---

## 下面要做（夜间继续）

1. ⏳ sherpa-onnx-sense-voice tarball 下完（1.05 GB ≈ 5min）→ 用 bundled wavs 做 CER 基准
2. ⏳ 3588 device=cpu 同集对比（命中后填表）
3. ⏳ 3588 NPU 路径：sherpa-onnx-rknn / RKNN-toolkit2 转换可行性评估
4. ⏳ 分析 3588 PID 60037 的 /tmp/asr_arm.log，给 VAD 参数调优建议

---

## 增量 commit（夜间未 push）

进展会持续 commit 到 `sprint/liaohe-3588` 本地。明早 push 与否你定。
