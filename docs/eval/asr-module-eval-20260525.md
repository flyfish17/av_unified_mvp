# ASR 语音模块评估报告（5/25）

> **范围**：3588 上 audio_processor 模块（含 in-process SenseVoiceSmall CPU offline 路径）。
> **参照系**：Mac av_understanding_mac 仓库 audio_processor（FunASR 2pass docker websocket 路径）。
> **数据源**：本仓库 5/14 ~ 5/25 supervisor.log、sustain_watch 采样、Mac/3588 实录 transcript 各一份。
> **关联**：[funasr 2pass spike plan](../plans/asr-funasr-2pass-spike-plan-20260525.md)

## 0. 一句话结论

3588 当前 ASR **勉强可演示 / 不可生产**。架构是主因（5/6 限制来自移植时简化），硬件是次因。**funasr 2pass 是可解路径**，详见 spike plan。

---

## 1. 当前架构

```
Mic（C920 USB）
   ↓ sounddevice 60ms/帧 @ 16kHz
audio_processor (Python, in-process)
   ├─ 100Hz HP butter + 1.5x gain 降噪
   ├─ VAD: rms > 0.012 进 speaking, silence > 600ms 切段
   └─ FunASR AutoModel(SenseVoiceSmall) CPU 整段推理
       ↓
       publish av/audio/final (raw_mode="sense_voice_offline")
       ↓
   punctuator 模块（独立进程，ct-punc-zh-en-vocab272727-int8 ONNX）
       ↓
       publish av/audio/command_punctuated
       ↓
   llm_engine / dashboard 消费
```

**关键代码**：`modules/audio_processor/processor_arm.py`（文件 docstring 第 4-12 行明确"非流式 / 按 VAD 分段送整段 / 无 partial"）

## 2. 性能指标（实测）

### 2.1 长跑稳定性

| 数据点 | 时间 | RSS | etime | CPU 均值 |
|---|---|---|---|---|
| 启动后 7h | 5/20 08:19 | 3.47 GB | 7h | 131% |
| 启动后 22h | 5/21 03:14 | 进程已停（user 操作）| — | — |
| 重启后 4 天 | 5/25 13:30 | **6.1 GB** | 4d 0h 47m | 5.2% |

**结论**：
- **RSS 持续涨**，疑似 SenseVoice CPU 推理累积或 ct-punc 缓存未释放
- 速率 ≈ 1 GB / 2 天
- 4 天没崩，但按当前曲线 6-8 天会触发 OOM 或 supervisor kill
- CPU 平均低（5%）但段内推理峰值 100%+（单核满）

### 2.2 ASR 出字间隔（5/25 实测）

| 间隔范围 | 出现次数（5/25 当天）|
|---|---|
| < 1 min | ~30% |
| 1-5 min | ~50% |
| 5-15 min | ~15% |
| > 15 min | ~5%（疑似 VAD 卡或环境太静）|

**说明**：
- 间隔不稳定 — VAD 简陋 + 环境噪音 RMS 刚过阈值 → 段切不出来
- 无 partial → dashboard 上经常 10+ 秒"在听"但无字
- 用户感知像"卡住"，实际是后端在等 VAD 切段

### 2.3 延迟构成（最近 5 句 final 实测）

| 推理耗时 | 音频段长 | 推理 / 音频比 | 用户感知延迟 |
|---|---|---|---|
| 18.1 s | 42.2 s | 43% | ~60 s |
| 8.8 s | 16.9 s | 52% | ~26 s |
| 8.0 s | 15.2 s | 52% | ~23 s |
| 7.8 s | 15.1 s | 52% | ~23 s |
| 7.8 s | 15.1 s | 52% | ~23 s |

**结论**：
- SenseVoice CPU @ RK3588 = 音频长度 × 50%（合理速率）
- **延迟主要来自 VAD 累积段长，不是推理速度**
- silence 600ms 太宽松，连贯讲话切不出短段

## 3. Mac vs 3588 录音质量对比

数据：用户同时段同人讲话，两端各录一份 transcript。
- Mac 文件：`transcript-2026-05-25T04-29-35.txt`（约 1 小时）
- 3588 文件：`transcript-2026-05-25T04-53-58.txt`（约 2 小时多）

### 3.1 量化对比

| 维度 | Mac (FunASR 2pass) | 3588 (SenseVoice in-process) | 评级 |
|---|---|---|---|
| 段落数 | 28 | 33 | 相当 |
| 段平均长度 | 长（500-2000 字常见）| 短-中为主 | Mac ↑↑ |
| 错字率（人工抽 5 段） | < 1 处 / 100 字 | 5-8 处 / 100 字 | 🔴 3588 ↓↓ |
| 标点规范度 | 高（句号 / 问号 / 逗号搭配自然） | 低（"，"连用，缺句号） | 🔴 |
| 长句完整性 | 长句一气呵成 | 长句中段经常乱字 | 🔴 |
| 段开头乱码 | 无 | 频繁（"提因为他..."/"切入..."/"是的，点切入..."）| 🔴 |
| 数字 / 专有名词 | "万象城"/"百分之十几" 正常 | "万" 多变阿拉伯"10000"+"万象汇 b 管" 混乱 | 🔴 |
| 段间稳定性 | 时间间隔均匀（多 1-2 min）| 间隔差异大（2-14 min 混杂） | 🔴 |

### 3.2 典型样本（同时段同话）

**Mac**（11:31:26 起首段）：
> 就不影响，应该说有呃有影响，他老旧就是对人脸识别不准呗。对，完了，而且他的点可能相对少点，然后这一个走廊可能就一个嗯，就假如这个50 米花，那你越早你越粗糙的话，你的数据就越不准，就这么点事儿。嗯，对，那这个是他也知道。...

**3588**（11:24:42）：
> 告诉你这个本地端口是们的谓放标签检业相关集面界面个热力了块，研究一下个控他安全啥顾虑，各部门运营和能了，今是运营和那个物业属安防块概给，而他也需要这个东西了。一个监控做了一个人的是数据统计人，只是他想做一个热力的一个分布分布统计数量的人统计一个事...

**差异不是模型本身（都用 SenseVoiceSmall）**，是 funasr server 链路自带 N-gram LM 纠错 + 流式 chunk endpointing + 2pass refine 这些后处理；3588 全裸 in-process 推理输出没纠错。

---

## 4. 架构 vs 硬件 — 主因分析

| 限制因素 | 类型 | 是否硬件限制 | 是否可改 | 优先级 |
|---|---|---|---|---|
| 无 LM 后端纠错 | 架构 | 否 | 可改：funasr 2pass 自带 N-gram LM | 🔴 高 |
| 无 partial 流式 | 架构 | 否 | 可改：funasr 2pass websocket | 🔴 高 |
| VAD 简陋（仅 RMS + silence）| 架构 | 否 | 可改：funasr server endpointing | 🟡 中 |
| 整段送 offline 模型 | 架构 | 否 | 可改：funasr 流式 chunk | 🟡 中 |
| in-process 模型驻留 → 内存泄漏 | 架构 | 否 | 改 server 路径后内存释放更可控 | 🟡 中 |
| RK3588 CPU 推理 ~50% 音频速度 | 硬件 | 是 | 难短期突破 | 🟢 低（可接受） |
| RKNN port 幻听 | 硬件 + 模型移植 | 部分 | 5/18 已确认不通，不再追 | 🟢 不动 |

**结论**：**5/6 限制源自移植时简化的架构选择，不是 RK3588 算力不足**。
- 5/13 早期决定走 NPU 路径（sense_voice_rknn），完全绕过 docker server 路径
- 5/18 RKNN port 出幻听后切回 in-process CPU
- 沿用 demo `pro_av_dashboard_NPU.py` in-process 写法，省力但失去 LM / partial / 流式 endpointing 这些 server 路径专属能力

详细架构升级方案见 [funasr 2pass spike plan](../plans/asr-funasr-2pass-spike-plan-20260525.md)。

---

## 5. 可演示边界 — 给销售的诚实手册

| 场景 | 现在能做 | 现在做不了 |
|---|---|---|
| "说一句开灯/关灯" 指令演示 | ✅ 15-30s 后出字 + 意图解析 | partial 流式（讯飞同款"边说边跳字"）|
| 演示 dashboard 转写卡 | ✅ 字会落下来 | "落得快"/"实时"的体感 |
| 会议纪要（30 分钟+） | ⚠️ 出，但错字多 / 段落乱跳 | 高质量纪要直接交付客户 |
| 长讲话 demo 给客户看 | ❌ 长句乱字会暴露质量 | 同上 |
| 短句指令演示给销售客户 | ✅ 可控 | — |
| 实时翻译 / 字幕 | ❌ 不行（延迟 + 错字） | 同上 |
| 24h+ 长跑不重启 | ❌ 不行（内存涨）| 加 watchdog 周期重启可绕 |

**销售话术建议**：
- ✅ 强调："系统能听、能理解、能动作 — 听完动作是核心，体验不是讯飞同款"
- ❌ 避免："实时转写"/"会议纪要"/"流式对话"（讯飞同款体验当前做不到）

---

## 6. 长跑数据（待 sustain_watch 持续观察）

`~/sustain_watch_20260525/` (5/25 启) 持续采样，目标拿到：
- 在哪个 etime 触发 OOM 或 supervisor kill
- RSS 增长曲线是否线性
- final 间隔是否随 etime 退化（5/20 实测 7h 后 16h 无 final 的退化模式是否重现）

报告将在 sustain_watch 跑满 7 天 / 触发崩溃后补充更新到本文件 § 6.x。

---

## 7. 建议（按时间窗口）

### 7.1 本周（不动 audio_processor）
- 让 sustain_watch 跑 7 天，拿到 in-process 续航上限基线
- ASR spike 计划走桌面调研阶段（在 Mac 上 docker pull / 测 partial）
- 销售对外用 audio_processor "停止再开启" workaround，配合短句指令演示

### 7.2 下周（视 spike 8 成把握）
- 8 成达到 → 选窗口期在 3588 上 spike，对比验证
- 8 成不达到 → 不动，继续等数据

### 7.3 长期
- 若 funasr 路径通：双 backend 并存，env 切换；演示用 funasr，长跑用 in-process（避免 docker 长跑未知问题）
- 若 funasr 路径全不通：备选 Whisper.cpp arm64 / Paraformer 重新评估（另起 sprint）

---

## 8. 不在本评估范围

- ❌ 意图理解 / LLM 后处理（独立模块评估）
- ❌ ct-punc 替换（独立 sprint）
- ❌ Mic 硬件升级（C920 USB → 阵列 mic 之类）
- ❌ NPU 路径深入（已结论）
