# 路径 γ zipformer RKNN — mic 真音 CER 回归测试（B 阶段 gating）

- **日期**: 2026-05-20 01:30 – 02:00（夜班）
- **分支**: `experiment/path-gamma-zipformer-rknn-spike`（基于 5/19 spike commit ad05be8）
- **决策权重**: B 阶段 0.5d gating —— 决定 γ 是否进阶段 1 integration prototype（2d）
- **3588**: firefly@192.168.5.6 / `/home/firefly/spike_venv_rknn_20260519/`

---

## 1. TL;DR

❌ **不过线**。

- **远场多人会议（aishell4_M 120s）**：γ zipformer 识别 30 字 / funasr SenseVoice 386 字 → **覆盖率仅 7.8%**，**CER 93.3%**（其中 deletion 356 个、sub 4、ins 0）—— **几乎完全失能**。
- **朗读中英教学（bundle 51s）**：γ zipformer 165 字 / funasr 131 字 → γ 反而比 funasr 更精确（funasr 把"星期三"错成"星种"、漏识别"FREQUENTLY"，γ 都对）；CER 62.6% 数值高但失真，因为 funasr reference 本身有错。
- **User 真实场景包含韩语**：punctuator log 5/18-5/19 共 440 条 final 中 11 条含韩语字符（2.5%），γ `zipformer-bilingual-zh-en` **模型本身不支持韩语**，user 一旦说韩语会直接哑火。
- **gating 阈值** "CER 退化 ≤ 15%" **远未达到**（远场会议 93% 退化）。
- **推荐**：**弃 γ 路径，转 D（仿 partial UX，funasr CPU 主线不动 + 前端 fake-streaming）**。

---

## 2. 测试方法

### 2.1 数据来源（受限说明）

任务原计划"从 audio_processor `/audio/export.wav` endpoint 拉真 mic ring buffer"，但 **5/20 凌晨 audio_processor 不在运行**（`ss -tlnp` 无 5052 端口、`ps` 无相关进程；仅 punctuator standalone PID 514224 在跑订阅 MQTT）。红线明确"不动 audio_processor / supervisor / 任何长跑进程"——这里采取严格解读：**不主动重启服务**（即使它已停止），改用现有 wav 做最佳 proxy。

使用 wav：

| ID | 文件 | 时长 | 性质 | 用途 |
|---|---|---|---|---|
| A | `aishell4_M_R003S01C01_first120s.wav` | 120s | 真实会议远场录音、多说话人（园长 / 教师 / 厨师 / 保安 / 招生）| 模拟 user 长 sustained 自发对话 + 远场拾音场景 |
| B | bundle: `mic_proxy_bundle_50s.wav`（5 个 sherpa-onnx test wav 拼接）| 51s | 中英教学朗读、近场 close-talk | γ 训练域 best-case |

User 真实场景的实际分布（从 punctuator log 5/18-5/19 共 440 条 final 抽样）：
- 中文为主自发对话（心理学 / 商务 / 家长聊天）
- 中英字母编号 / 短英文词混排（"k幺 m 那个项目"、"a i 识别"、"a m s 快速"、"ok"、"yeah"、"right"）
- **韩语短句**（"우에에서 물 다 되는 어"、"꼬워줘요"、"그니까"，11/440 = 2.5%）
- 远场拾音（Logitech webcam mic，非头戴麦）+ 偶发说话人重叠

aishell4_M wav 在"远场 + 多说话人 + 自发"三个维度都贴近 user 实际场景；bundle wav 是 γ 训练域 best-case 朗读 close-talk，用作上界。

### 2.2 推理路径

- **funasr CPU baseline**: `/home/firefly/creator_ai_demo/SenseVoiceSmall` + funasr 1.3.1 AutoModel offline；wav 整段一次喂入。Read-only execution（仅借用 venv，不动 venv 文件）。
- **γ zipformer RKNN**: `/home/firefly/spike_venv_rknn_20260519/` + `provider="rknn"`；模型 `/home/firefly/spike_venv_20260518/models/zipformer-streaming-rk3588/`（encoder/decoder/joiner.rknn）。两种喂法：
  - **streaming + endpoint**：仿 5/19 spike 实时喂、按 endpoint 切 final
  - **no-endpoint 一次喂完**：诊断"是不是 endpoint detection 配置导致 γ 假死"

### 2.3 CER 计算

`Levenshtein 距离 / reference 字符数`，norm 函数剥全部空格 + 中英文标点 + 统一英文小写（避免 funasr `monday` vs γ `MONDAY` 误判为 substitution）。把 sub / ins / del 分开统计，方便诊断错误类型。

代码：`/tmp/recompute_cer.py`（脚本含手写 Levenshtein DP + 回溯统计三种 op）。

### 2.4 reference 不是人工标注

**重要 caveat**：funasr SenseVoice 本身就是 hypothesis 而非 ground truth。CER 反映的是"γ 与 funasr 输出差异"，不是"γ 与真实文本差异"。所以：

- **当 CER 极高（93%）且主要是 deletion 时**：γ 输出比 funasr 短一个量级，即使 funasr 有错也无法解释这种量级差异 → 这是真实信号
- **当 CER 中等（62%）且 sub/ins 多于 del 时**：可能两边都对一部分但词序 / 大小写 / 空格不同 → 需手工逐句对照判断（见 §4）

---

## 3. CER 数据表

### 3.1 整体 CER

| 场景 | wav | hyp_chars (γ) | ref_chars (funasr) | CER | sub | ins | del | 主要错误类型 |
|---|---|---|---|---|---|---|---|---|
| 远场会议（A）| aishell4_M 120s | 30 | 386 | **93.3%** | 4 | 0 | 356 | 几乎全是 deletion |
| 朗读教学（B）| bundle 51s | 181 | 131 | **62.6%** | 32 | 50 | 0 | sub+ins 为主，无 deletion |

### 3.2 短句 / 长句分布（γ streaming + endpoint 模式）

| 场景 | final_count | 空 final | 短句 (<5 字) | 长句 (≥15 字) | 备注 |
|---|---|---|---|---|---|
| 远场会议（A）| 43 | 42 | 0 | 1 | **43 个 final 里 42 个空字符串** → endpoint 触发但模型无识别 |
| 朗读教学（B）| 8 | 2 | 0 | 4 | 正常分布 |

### 3.3 诊断：no-endpoint 一次喂完

| 场景 | hyp_chars | decode wall | 备注 |
|---|---|---|---|
| 远场会议（A）| **30**（与 streaming 模式完全相同）| 69.4s | **endpoint 不是问题**，γ 真的对该 wav 整段只识别出开头 30 字 |
| 朗读教学（B）| 165（vs streaming 181）| 30.8s | streaming 多出 16 字是 partial 残留重复，no-endpoint 更干净 |

**关键诊断结论**：γ zipformer 在远场会议场景下不是 endpoint 配置问题，是**模型本身对该 acoustic distribution 的建模能力直接失效**。可能成因：sherpa-onnx 公开 `zipformer-streaming-bilingual-zh-en` checkpoint 训练数据偏 close-talk 朗读 corpus（wenetspeech / aishell-1 read speech），对远场 + 多人重叠 + 自发语音 OOD。

---

## 4. 关键对照例子

### 4.1 远场会议（aishell4_M）—— γ 严重失能

| 时段 | funasr 识别 | γ zipformer 识别 |
|---|---|---|
| 0-10s（编号朗读）| 零零幺幼儿教幼儿校长零幺零教师零幺幺教师零幺二厨师零幺三保安 | 零零幺幺二教英二校长零幺零教师零幺幺教师零幺二厨师零幺三保安 |
| 10-30s（园长开会）| 零零幺四招生呃这次啊我要把大家伙都叫过来咱们把咱这个幼儿园啊这个从新在开一次会因为毕竟呃就是大半年也快过去了... | **（空）** |
| 30-60s（议程）| ...上这个也要接近这个这咱个要放假了呃呃我这边呢因为也进入冬天了咱把大家叫过来看看咱幼儿园还有什么安全啦... | **（空）** |
| 60-90s | ...你们幼儿师们对孩子这块的学习还有一些这个呃教育咱有没有要探讨的包括就是就是招生招生... | **（空）** |
| 90-120s | ...咱要招一批呃招生这块也工作量也不大但是也需要招一部因为咱们班级人员都还没有... | **（空）** |

γ 识别完全停在编号朗读那 5s（且把"幼儿教幼儿"幻听成"幺二教英二"），后续 115s 全部丢失。即使 funasr 输出"幼儿教幼儿校长"也是模糊不清，但**它识别出了 386 字**，覆盖了完整议程；γ 只产出 30 字编号。

### 4.2 朗读中英教学（bundle）—— 两者旗鼓相当，γ 略好

| funasr SenseVoice | γ zipformer RKNN | 实际 / 评价 |
|---|---|---|
| 昨天 monday today is today after tomorrow **星种叫与** always always | 昨天是 MONDAY TODAY IS LIBR TODAY AFTER TOMORROW**是星期三** | γ 正确识别"是星期三"，funasr 错成"星种叫与"；γ "LIBR" 是幻听（funasr 没有），互有胜负 |
| 什意思啊这个是平凡的啊是下来平的 | 这是第一种第二种叫 | 两者都在自由发挥，funasr 更接近"日常的"语意，γ 没看见这段 |
| yes 是一现时时写 | 是啊不记下来 **FREQUENTLY**频繁的 | γ 正确识别"FREQUENTLY"这种 less common 英文单词；funasr 漏 |
| on time 时 time 时他时交他的作业 | 嗯 **ON TIME**要准时 **IN TIME**是及时叫他总是准时教他的作业 | γ 完整保留"on time 准时 / in time 及时"对照教学逻辑；funasr 把 "in time" 漏成"time"两次重复 |
| 用一在时是没彩的述一实下一句话 | 那用一般现在时是没有什么感情色彩的陈述一个事实下一句话 | γ 完整、流畅、自然；funasr 严重缺字 |

**inspection 结论**：bundle 场景 γ 实际比 funasr 更准确（funasr 像缺帧丢字，γ 完整且语法连贯）。但 CER 数值 62.6% 反向，因为 reference 本身错得多。**这说明用 funasr 作 reference 计算 CER，对 γ 不公平也不准确**。

### 4.3 User 实际场景的韩语（致命）

User punctuator log 5/18-5/19 含韩语 final 示例：

| timestamp | funasr 识别 | γ zipformer 预期 |
|---|---|---|
| 03:19:12 | 좋 상해 | **不支持 → 输出乱码或空** |
| 03:32:35 | 응 뭐 얘기야 | **不支持** |
| 06:20:32 | 꼬워줘요 | **不支持** |

`zipformer-streaming-bilingual-zh-en` 的 tokens.txt 只覆盖中文 + 英文 BPE，**没有韩语字符**。user 一旦说韩语，γ 必哑火。

---

## 5. 综合判定 + 推荐

### 5.1 gating 判定

5/19 路径 γ 大纲 gating："CER 退化 ≤ 15% vs funasr CPU sensevoice"

| 维度 | 结果 | 是否过线 |
|---|---|---|
| NPU load (5/19 数据) | 4-14% | ✅ 远超 |
| partial 间隔 median | 597-675ms (5/19) | ✅ |
| **CER 退化（远场会议）** | **93.3% deletion** | ❌ |
| CER 退化（朗读 close-talk） | 数值 62.6% 但 γ 实际更好 | （口径不可靠） |
| 韩语支持 | **bilingual-zh-en 模型不含韩语 token** | ❌ |
| spike 进程 CPU < 70% | 51.9% p50 / 69.8% max | ✅ |

**判定：❌ 不过线**。最致命的两点：(1) 远场会议失能 (2) 韩语不支持。

### 5.2 推荐

**弃 γ zipformer RKNN 路径，转 D（仿 partial UX）**。

理由：
1. **γ 的核心收益（NPU offload、低 partial 延迟）已被验证（5/19）**，但**识别质量在 user 实际场景下不可用**（远场 + 韩语两个红线都踩了）
2. funasr SenseVoice CPU 主线**已经稳定且识别质量适配 user 场景**（覆盖中英韩 + 自发对话 + 远场较好）—— 不要为了追 partial 体验把主线换掉
3. **D 路径（fake-streaming partial UX）**用前端 / 中间层定时把 funasr 已识别的部分作为"假 partial"推给用户，user 体感上有 partial 滚动效果，但底层 ASR 不变 —— 把 γ 的"partial 延迟好"包装出来，**不引入识别质量退化**

**不推荐的替代**：
- 不要尝试 finetune γ zipformer：需要数据 + 训练 infra，**远超 0.5d/2d 的 sprint 工时预算**
- 不要切到 paraformer-streaming（路径 β）：5/19 spike 已证明它有"today day"幻听问题、且 CPU 路径无 NPU 收益
- 不要等"未来更好的 streaming 多语种 RKNN 模型"：sprint 节奏不允许 indefinite 等待

### 5.3 阶段 1 工时回收

原计划 γ 阶段 1 integration prototype 2d 工时 → 释放出来转 D 路径估时 ~1d（前端 / dashboard 假 partial 渲染层）+ 0.5d 其它 backlog。

---

## 6. 测试 artifact 落盘位置

3588 (`firefly@192.168.5.6`)：

```
/home/firefly/spike_venv_rknn_20260519/
├── spike_mic_cer_regression.py           # 本次 spike 主脚本（streaming + endpoint）
├── samples/
│   ├── mic_aishell4_M_120s.wav           # 远场会议 wav
│   └── mic_proxy_bundle_50s.wav          # 朗读中英教学 wav
└── reports/
    ├── funasr_baseline_aishell.json      # funasr ref（远场会议）
    ├── funasr_baseline_bundle.json       # funasr ref（朗读）
    ├── funasr_baseline_ref_aishell.txt   # 平文本 ref
    ├── funasr_baseline_ref_bundle.txt
    ├── gamma_zipformer.json              # γ streaming 远场会议
    ├── gamma_zipformer_bundle.json       # γ streaming 朗读
    ├── gamma_no_endpoint_aishell.json    # γ no-endpoint 诊断（远场）
    └── gamma_no_endpoint_bundle.json     # γ no-endpoint 诊断（朗读）
```

辅助脚本（3588 /tmp/）：
- `/tmp/run_funasr_baseline.py` — funasr SenseVoice CPU offline
- `/tmp/spike_no_endpoint.py` — γ no-endpoint 诊断
- `/tmp/recompute_cer.py` — CER 重算
- `/tmp/concat_test_wavs.py` — bundle wav 生成

---

## 7. 已知 caveat & follow-up

1. **没拉到 user 真实 mic ring buffer**：audio_processor 5/20 凌晨不在跑。本报告用 aishell4 远场 + bundle 朗读两端值做 proxy，结论强度受影响但**远场会议 93% deletion 这个量级差异不会因换 wav 而消失**，且**韩语不支持是模型 architecture 层面的硬限制**与 wav 选择无关。如需未来再核实，重启 audio_processor 跑 5min user 主动说话后拉 `/audio/export.wav` 即可。
2. **funasr SenseVoice 作 reference 在朗读场景失真**：朗读场景 γ 实际比 funasr 准。如真要 fair CER 评估需人工标注 ground truth（≥0.5d），本次决策不需要这个精度（远场会议的差异已经足够定调）。
3. **NPU 数据仍然 valid**：5/19 spike NPU load 4-14% / partial 597-675ms 数据没问题，路径 γ "运行时性能优秀但识别质量不足" 是确定结论，不是"路径 γ 全盘失败"。如果未来有领域适配的 zipformer-streaming-zh-en-ko-yue RKNN checkpoint，可以重新评估 γ。
