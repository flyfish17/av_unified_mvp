# 逐字 Partial（流式 ASR）工作量评估

**日期**：2026-05-19
**触发**：5/19 user 测试 funasr CPU sensevoice 路径丢字消失 + 70 字长句完整后提出"只差逐词蹦就完美了，评估工作量"。
**背景**：DEVELOPMENT_PLAN.md §3.2 trade-off 表已标记"逐字 partial ❌ 无不大改路径（sensevoice 模型不出 partial），换模型 paraformer/funasr，**大改**"。

---

## 现状

- audio_processor 用 sensevoice（offline only） — VAD 切段后整段送 ASR，输出整句 final
- 5/19 路径：funasr CPU sensevoice，~1-3s/段 RTT，整段才上屏
- 客户演示痛点：长段说话时 dashboard 空白 1-3s，看起来"卡死"

## 三条路径方案矩阵

| # | 方案 | 改动量 | 模型替换 | 多语言保留 | 推荐 |
|---|---|---|---|---|---|
| **A** | 换 paraformer-streaming（替换 sensevoice）| 大改 | ✅ | ❌ 失多语言 | ⭐ 真 partial |
| B | sherpa-onnx streaming sense_voice（社区实验）| 中改 | 部分（fork）| ✅ | 不成熟 |
| **C** | 仿 partial（音量出现就推"…"占位，3s 内出 final 替换）| 小改 | 不换 | ✅ | UX 兜底 |

---

## 方案 A · paraformer-streaming（推荐做真 partial）

### 现成资源

- sherpa-onnx 内置 `rk3588-15s-paraformer-zh-streaming-2025-10-07`（RK3588 预编译，5/18 调研报告 §2 表里列过）
- chunk 配置 `[0, 10, 5]` 约 600ms 出 partial，原生支持 ITN 标点

### 工作量细分

| # | 任务 | 工时 | 红线 |
|---|---|---|---|
| A.1 | 在 spike_venv 跑 paraformer-streaming 单机 spike（中文识别准确率 / RTT / RK3588 CPU%）| 0.5d | 无 |
| A.2 | 写新 `processor_paraformer_streaming.py`（仿 processor_arm.py 结构，**不动现有 processor_arm.py**）| 1.5d | 触红线（动 audio_processor 目录）|
| A.3 | audio_processor/main.py 加 `AV_ASR_BACKEND=paraformer_streaming` 分支选择 | 0.5d | 同上 |
| A.4 | 改 MQTT publish 频率：partial 每 600ms 发一次 `av/audio/partial` | 0.5d | 协议层改动 |
| A.5 | punctuator 是否处理 partial 取决于是否要"逐字标点"（建议 partial 不加标点，final 时加；前端处理：partial 不走 punctuator topic）| 0.5d | — |
| A.6 | dashboard.js 调整：partial 进 `.live` 区域（已有 partial channel 渲染逻辑，5/12 之前已工作）| 0.5d | dashboard.js 已是 user 改过区域，需小心 |
| A.7 | 真音频回归 + 客户对比 demo（带 partial vs 不带）| 0.5d | — |
| **合计** | | **~4d** | |

### 关键风险

1. **失多语言支持** — paraformer-streaming 中文专攻，sensevoice 的粤/日/韩/英多语言能力丢。如客户场景含外语对话，必须保留 sensevoice 作为可切 backend
2. **3588 CPU 预算** — paraformer-streaming chunk 推理频率高（每 600ms 一次），sherpa-onnx 端 NPU 加速可控，但仍要实测 audio_processor CPU 是否超 funasr CPU 的 107%
3. **partial 抖动** — 流式输出会有 token revision（之前推过的字下一秒被修正），dashboard.js 现有 partial append 模式可能要改为 replace
4. **触红线**："不动 audio_processor"是阶段二红线，做这个等于松绑红线。需要 user 明确授权
5. **客户演示窗口** — 4d 工时含联调，紧急客户演示前不建议启动

---

## 方案 B · sherpa-onnx streaming sense_voice（不推荐）

社区有人 fork sensevoice 加 streaming 包装（如 [sherpa-onnx#1100](https://github.com/k2-fsa/sherpa-onnx/issues) 类似 issue），但：
- 不稳定，仍是离线模型 chunked 推理，partial 质量不如 paraformer-streaming
- 不在 sherpa-onnx 官方支持清单
- 工作量 ≈ 方案 A 但风险更高

跳过。

---

## 方案 C · 仿 partial UX 兜底（小改，建议先做）

**思路**：不真正出 partial 字，但让 dashboard 在"VAD 检测到说话开始 → final 上屏前"显示视觉占位（"…"动画 / 录音中 icon / 计时器），让用户感知"系统在听"，避免"卡死"错觉。

### 工作量细分

| # | 任务 | 工时 |
|---|---|---|
| C.1 | audio_processor 在 VAD speaking=True 时发一条 `av/audio/listening` 心跳（含估计的 final ETA）| 0.3d |
| C.2 | speaking=False 时发 `av/audio/listening_end` | 0.1d |
| C.3 | main.py supervisor 订阅 listening + 推 SSE | 0.2d |
| C.4 | dashboard.js 收 listening event → 转写卡显示 "…正在听（X.Xs）" 动画 | 0.5d |
| C.5 | 联调 + 视觉验证 | 0.2d |
| **合计** | | **~1.3d** |

### 收益

- **UX 立刻改善** — user 不再觉得"卡死"
- **零模型替换风险** — 多语言保留、ASR 准确率不变
- **不触动 audio_processor 核心 ASR 逻辑** — 只加一个旁路事件
- 可作为方案 A 的 **过渡 / 兜底**：方案 A 落地后此 listening 心跳仍可保留作为"VAD 接到声音 → 真 partial 出现"之间的 UX

### 缺点

- 不是真正的逐字 partial，懂行的客户能看出来"还是整句出"
- 但视觉上 90% 解决"卡死"的体感

---

## 推荐执行节奏

**短期（本 sprint，1-1.5d）**：**方案 C 仿 partial UX 兜底**
- 立刻动手，客户演示 1 周内能用
- 不触红线，工作量小
- 与现有 funasr CPU 路径完全兼容

**中期（下个 sprint，4d）**：**方案 A paraformer-streaming**（如客户明确要求真 partial 体验）
- 在 spike_venv 先 spike 1d 验证 RK3588 上的 CPU% + 中文准确率
- 通过后启动 1.5d 写新 backend module + 1d 协议改 + 1d 联调
- 保留 sensevoice 作为 ASR backend fallback，env 切换
- **不要替换 sensevoice，要并存**

**长期**：观察 happyme531 SenseVoiceSmall-RKNN2 上游修复（如有）— 一旦 RKNN 不再幻听单字，可重启用 RKNN 路径降 CPU 占用。

---

## 关键判断

**先做方案 C（仿 partial UX）**：性价比最高，UX 改善 90%，工作量 1.3d 不触红线。

**方案 A 等客户明确要求**：4d + 红线松绑成本不小，无明确客户拉动不主动启动。先把方案 C 上线 + 用真实客户反馈判断是否需要真 partial。

---

## 当前 5/19 funasr CPU 路径"可固化"判定

✅ **可固化为当前生产路径**：
- 70 字长句完整识别（测试两轮）
- 标点闭环工作正常
- "我想"幻听消除（D3 验证 D2 假设）
- punctuator + dashboard P1.3 链路稳定

⚠️ **trade-off**：
- audio_processor CPU 2%→107%（funasr CPU 推理代价）
- 单段 RTT 1-3s（用户体验比 RKNN 380ms 慢，但相比丢字是赢）
- 3588 总负载吃紧但稳定（video_processor 305-420% + audio 107% + 其它）

**固化方法**：见 `scripts/3588-demo-start.sh` 默认已切 `AV_RKNN_BACKEND=0`，env override 可切回 RKNN。
