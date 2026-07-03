**战略定位**：公司 AI 技术底座。
> 模块解耦 + 订阅制架构，让每次开发成果累积而非推倒重来。
> 客户只需要转写，装一个模块。需要视觉识别，插入另一个。需要全套，全部开。
> **开发强度降下来，落地速度提上去。**
>
> 三个层次（架构视角 = 产品形态，开发与客户视角统一表达）：
> **A · 单机自洽** · **B · 多机协同** · **C · 跨品牌、跨系统桥接**

# av_unified_mvp 开发计划

> 历史回合见 `ARCHIVE_2026Q2.md` · 踩坑教训 `LESSONS_LEARNED.md` · Jetson 角色 `JETSON_FINAL_20260515.md` · 接续指南 `~/.claude/plans/morning-resume-20260515-md-functional-quail.md`

---

## 0. 快速接手（5 分钟）

| 项 | 值 |
|---|---|
| **当前阶段** | **阶段二 · 3588 主线落地**（5/18 启动）|
| **当前主线** | 语音模块产品化（A 层 · 单机自洽） |
| **阶段一固化** | Git tag `v1.0-stage1-mac-validated`（Mac 验证解耦订阅制完成）|
| **销售获取** | `git checkout v1.0-stage1-mac-validated` → `./start.command`（>16GB Mac 即可）|
| **当前 sprint branch** | `sprint/liaohe-3588-night-poc-20260511` |
| **3588 边缘机** | `firefly@192.168.5.6`，仓库 `/home/firefly/av_unified_mvp/`，venv `/home/firefly/creator_ai_demo/venv/`（共享不动）|
| **Mac mini .193** | `openclawMiniOld`，跑 escalate llm_engine 兜底（B 层多机协同雏形）|
| **Jetson `.51`** | **独立支线**（视频深思 + 验证 CUDA 语音）；无 SSH，走 MQTT；单独 Claude 窗口 → `docs/handoffs/jetson-side-window-prompt.md` |
| **Dashboard** | `http://192.168.5.6:5050` |
| **下一步** | 见 §7.18 当前 sprint 看板 |

**5 分钟接手三步**：
1. 读本文 §1 + §3 + §7.18
2. 看 `LESSONS_LEARNED.md` 已知坑
3. 接续读 `~/.claude/plans/morning-resume-20260515-md-functional-quail.md`

---

## 1. 战略层次（架构 = 产品形态，一一对应）

开发节奏 **A → B → C 由简入繁**；客户验收按形态评级。同一份代码，三层兼容。

| 层次 | 架构（开发视角）| 产品形态（客户视角）| 当前完成度 |
|---|---|---|---|
| **A** · 单机自洽 | mqtt + 全模块同机 | 纯转写 + 语意执行（**辽河主线**）| 阶段一 ✅ Mac 验证；阶段二 🔵 3588 精进 |
| **B** · 多机协同 | broker + client 跨机订阅 | 视频分析输出（分布式监控盒）| 雏形：Mac mini escalate 兜底 ✅；多机分布 ⏸ |
| **C** · 跨品牌桥接 | adapter 层接厂商 SDK / REST | 利旧 + 运维（大客户整体交付）| husion 5 场景 ✅；其它 ⏸ |

**护城河**：A=端侧延迟 + 准确率 / B=分布式差异点 / C=模块化 + 协议契约 + 跨品牌发现

---

## 2. 硬件矩阵（5/15 修订）

| 硬件 | 场景定位 | 当前状态 |
|---|---|---|
| **Mac / Mac mini** | 阶段一固化机 / escalate 兜底（.193）| ✅ stage1 tag |
| **RK3588** | **阶段二主推**（涉密 / 国产化 / 一体机演示主力）| ✅ supervisor 11 模块稳定 |
| **Jetson Orin Nano** | **独立支线** — 视频深思 + CUDA 语音验证 | ⏸ 主线不投，支线持续 |

**硬件选型决策原则**：客户场景定，不预设。涉密走 3588，要 VLM 多路走 Mac mini，省钱走 Mac mini。**三套都跑同一份 av_unified_mvp 代码**，差异通过 env / config 切。

---

## 3. 两阶段开发框架

### 3.1 阶段一 ✅ 已完成（Mac 验证解耦订阅制）

- **固化形式**：Git tag `v1.0-stage1-mac-validated`（在 commit `5626b0c` 之上打）
- **销售部署**：`git checkout v1.0-stage1-mac-validated` → `./start.command`（>16GB Mac 即可）
- **交付物清单**：
  - 解耦订阅式架构（MQTT 总线 + supervisor + R1-R6 演进完成）
  - 10 模块独立可运行（audio / video / llm / keyframe / openvocab / husion / control / system_info / network_info / network_scanner）
  - Node-RED 编排（121 节点 5 tabs，含 `av/control → creator :8932` 桥）
  - Dashboard + 转写卡 + 纪要 + husion 5 场景一键演示
  - 销售材料 3 份（`docs/sales/`）
  - Mac mini .193 escalate 兜底（B 层多机协同雏形）
- **历史 Subagent 报告**：`docs/reports/2026-05/`（5/11-5/14 共 16 份）
- **历史接续文档**：`docs/handoffs/`（5/11-5/15 共 6 份 HANDOFF + RESUME）

### 3.2 阶段二 🔵 当前（3588 主线落地，语音模块产品化）

User 5/18 定调：「**当下代码作用发挥到最大并固化，找合适方式精进，不大拆大改**」

**前置 gating**：✅ 已完成 — GitHub 调研报告 `docs/research/asr-punctuation-diarization-20260518.md`

**P0.7 拍板结论（5/18 user 选）**：**新中间路径**（既非原路径 1 mock 版，也非路径 2 大改版）

| 维度 | 路径 1 原 mock | **✅ 新中间路径（拍板）** | 路径 2 大改 |
|---|---|---|---|
| 工时 | ~1d | **1.5-2d**（含 spike）| 5-8d |
| 标点 | LLM 后处理（云依赖） | **ct-punc int8 ONNX**（CPU 14ms / 句，离线） | 模型原生 ITN |
| 说话人 | silero-vad 顺序编号（一眼假） | **silero-vad + CAM++ ONNX embedding 段级聚类**（DER ~20%，真聚类）| pyannote 真 online（DER 13%）|
| 真 partial | ❌ | ❌（保留 sensevoice 不动）| ✅ paraformer-streaming 600ms |
| 撞 video CPU 红线 | 0 | 0（新增组件全 CPU ms 级 ONNX）| 高（叠 pyannote 几乎必爆）|
| 升级路径 | 必拆 | **平滑**（同在 sherpa-onnx 生态）| 已到顶 |
| ASR 模型变动 | 无 | **不动 sensevoice RKNN** | 必换 paraformer |

**新中间路径技术栈**：sherpa-onnx 1.13.2 (Apache-2.0) 一站式封装；新增 2 个独立 MQTT module（`punctuator/` + `speaker_tagger/`），audio_processor 零重构。

**P0.9 spike gating（立项前置）**：CAM++ ONNX 在 3588 大核 CPU 实测延迟无文档数据，**必须先 spike**。spike 任务：在 3588 跑 ct-punc int8（预期 < 30ms）+ CAM++ + sklearn 聚类对 60s 双人对话压测，看 CPU% / 段延迟 / DER 主观感受。过线才正式起 module。结果 → `docs/research/spike-campp-ctpunc-3588-20260518.md`。

**必备能力达成度（新路径下）**：

| 能力 | 当前 | 新路径达成度 | 真大改才能升级 |
|---|---|---|---|
| **逐字 partial** | ❌ | ❌（推迟到阶段三换 paraformer-streaming，平滑过渡）| 换 ASR 模型 |
| **标点** | ❌ | ✅ ct-punc 本地 ONNX（F1 工业级）| — |
| **整句修正** | ❌ | ⚠️ 暂不实现（依赖 partial → final 重判路径）| 接 paraformer streaming |
| **纪要** | ✅ 已有 | ✅ UI 提示 + 带标点显示 | — |
| **说话人初步**（可编辑）| ❌ | ✅ 段级真聚类（不是 mock）| 上 pyannote 升 13% DER |

### 3.3 后期规划（只技术储备，不实施）

- **双工对讲 + 语意执行**（边听边说）— GitHub 持续关注（pipecat / livekit / nemo agent toolkit 等）
- **知识库 + 问答** — 另立项目，**不在 av_unified_mvp**

### 3.4 Jetson 支线（独立工作流）

- **独立 Claude 窗口** + system prompt：`docs/handoffs/jetson-side-window-prompt.md`
- 主任务：
  1. 视频深思持续观察（偶发单路场景描述，无新投入）
  2. **验证 Jetson CUDA 上语音模块运转** — user 记得效果不错，需出报告
- 不污染主线 sprint branch；结果回报到 `docs/reports/2026-06+/`

---

## 4. 目标架构（六层）

```
1. 感知层 Capture     RTSP/USB 摄像头 | 麦克风
2. 理解层 Understand   audio_processor / video_processor / llm_engine / keyframe_filter / openvocab_filter / scene_analyzer
3. 总线层 Bus         mosquitto :1883 (3588)
4. 编排层 Orchestrate Node-RED :1880 (用户拖拽规则)
5. 展示层 Present     Flask + 原生 JS / SSE / summaries/ 纪要存档
6. 执行层 Act         control_dispatcher / husion adapter / web_browser (POC)
```

**设计原则**：
- 模块独立：`modules/<x>/main.py` 可独立 `python -m` 启动，仅依赖 MQTT
- 协议先行：MQTT topic schema 是合同，跨模块只看 schema，**不要 import 另一模块内部实现**
- 前端只订阅：浏览器端不直接 connect ASR/YOLO，只走 SSE/HTTP

---

## 5. MQTT topic 协议

### 数据流

| topic | 谁发 | 谁订 | 关键字段 |
|---|---|---|---|
| `av/audio/partial` | audio_processor | web/Node-RED | `text, seq_id, is_final=false, raw_mode` |
| `av/audio/command` | audio_processor | llm_engine/web/Node-RED | `text, seq_id, is_final=true` |
| `av/video/detect` | video_processor | keyframe_filter/web/Node-RED | `camera, time, detections[]`（**含空 detect 心跳** by `idle_detect_interval_s`）|
| `av/video/key_event` | keyframe_filter | scene_analyzer/openvocab_filter | `camera, reason, ...` |
| `av/video/scene_analysis` | scene_analyzer (Jetson) | dashboard | VLM 场景描述 |
| `av/video/openvocab` | openvocab_filter | dashboard | `hits[{class, conf}]` |
| `av/llm/event` | llm_engine | Node-RED/web | `event_type, original_text, intent, command` |
| `av/llm/escalate` | 3588 llm_engine | Jetson + Mac mini .193 | escalate 兜底 |
| `av/control` | Node-RED/llm_engine/web 按钮 | control_dispatcher / Node-RED `av/control (P0)` mqtt-in | `target, action, params` |
| `av/control/dispatched` | control_dispatcher | web | 执行结果回传 |

### 公告 / 系统

| topic | 协议 |
|---|---|
| `av/system/discovery/<module>` | retain=true，QoS=1，配 LWT。30s 心跳，崩溃 LWT offline |
| `av/system/host_stats` | CPU/内存/磁盘，每 5s（system_info）|
| `av/system/network` | 网卡/IP/收发速率，每 10s（network_info）|
| `av/system/lan_scan/{cmd,progress,result}` | UI ↔ network_scanner |

**变更协议时必须同步更新本节、`config/system_config.yaml` 的 `topics:` 与 Node-RED flows。**

---

## 6. 语音模块能力实测（5/18 更新）

| 能力 | Mac 端 | 3588 端 | 真实状态 |
|---|---|---|---|
| 转写 final | ✅ sensevoice | ✅ sensevoice RKNN | 工作正常 |
| 逐字 partial | ❌ | ❌ | 模型本身不出 |
| 标点（ITN）| ❌ | ❌ | 两端都 fallback 到 sensevoice（FunASR 2pass docker 未启）|
| 整句修正 | ❌ | ❌ | 代码无任何 mode 实现 |
| 纪要生成 | ✅ | ✅ | `web/server.py:286+` + `summaries/` 4 份 |
| 多说话人 | ❌ | ❌ | 未接 SOND/cam++/pyannote |
| LLM 意图 | ✅ qwen3.5:4b | ✅ NPU 1.5B + escalate 兜底 | 工作 |
| 控制下发 | ✅ | ✅ | `av/control → Node-RED → creator :8932` |
| Husion 5 场景 | ✅ | ✅ | dispatcher 内 husion REST adapter |

---

## 7. Sprint 看板

### 7.15 历史看板（5/15，全部 ✅）

P0：push 夜班 commit · 客户演示自检 · JETSON_FINAL 收尾 · DEVELOPMENT_PLAN 简化 · llm_engine 静默诊断
P1：Node-RED ENOENT 修 · web_browser 评估
P2：每机独立 broker / 语意扩展 / 知识库另立项目
不做区：Jetson 模型替换 / round-robin / NPU Qwen3-4B / MCP / yolov8-world 深耕 / YOLO26n / av/control Node-RED 外露

### 7.18 当前看板（5/18 新阶段启动）

| # | 任务 | 状态 |
|---|---|---|
| P0.1 | DEVELOPMENT_PLAN 重写 — 两阶段 + 战略定位 + §7.18 看板 + trade-off 表 | ✅ 本次 |
| P0.2 | 根目录 30+ md 整理到 `docs/handoffs/` + `docs/reports/2026-05/` | ✅ 本次 |
| P0.3 | `JETSON_FINAL_20260515.md` 措辞 "封板"→"独立支线" | ✅ 本次 |
| P0.4 | Git tag `v1.0-stage1-mac-validated` + push origin | ✅ 本次 |
| P0.5 | Jetson 独立窗口 system prompt → `docs/handoffs/jetson-side-window-prompt.md` | ✅ 本次 |
| P0.6 | 接续 plan 文件更新反映新两阶段 | ✅ 本次 |
| P0.7 | 必备能力实施方案 trade-off 拍板 → **新中间路径** | ✅ 5/18 |
| P0.8 | GitHub 调研报告（`docs/research/asr-punctuation-diarization-20260518.md`）| ✅ 5/18 |
| P0.9 | CAM++ + ct-punc 3588 spike — Phase A ✅ ct-punc 过线 / Phase B ⏸ 等双人录音 | 🟡 部分 |
| P1.1 | `modules/punctuator/` — ct-punc int8 ONNX 标点后处理（端到端 + 真音频 30+ 条已验） | ✅ 5/18 |
| **P1.3** | **Supervisor 订阅 punctuated topic + dashboard 重复 bug fix（streams=[]）** | ✅ 5/18 |
| **P1.2-pre** | **预研前置：先验 FunASR 自带分离 + sherpa-onnx 3588，再定 P1.2 是否自研**（见下"P1.2 预研前置"）| ⏳ 预研先行 |
| P1.2 | `modules/speaker_tagger/` — silero-vad 切片 + CAM++ embedding + 聚类（**可能被 P1.2-pre 降级为"升级+集成"**）| ⏳ 等预研 + Phase B 数据 |
| P1.3b | 转写卡说话人 tag 显示（dashboard 改造）| ⏳ P1.2 后 |
| P1.4 | 纪要 UI 提示 + 触发体验优化 | ⏳ |
| P1.5 | 销售部署 README（`git checkout tag` 后 1 命令启动指南）| ⏳ |
| P1.6 | Jetson CUDA 语音验证报告（独立窗口完成）| ⏳ |
| **P1.7** | **人名修复回流 3588 — SenseVoice hotword 接口预研先行**（见下"回流说明"）| ⏳ 预研先行 |
| **P1.8** | **英文缩写后处理移植 3588**（`apply_postprocess_rules` 搬进 `AudioProcessorARM` emit）| ⏳ 小改 |
| P2.1 | video_processor CPU 减压（config 调 inference_fps / jpeg_quality / 单路 ⏸）| 看是否影响语音 |
| P2.2 | 控制指令"离线"误判修复（dashboard.js 多 client_id 状态合并）| 接受 or 修 |

**不做 / 仅技术储备**：双工对讲（持续 GitHub 关注） · 知识库 + 问答（另立项目）

**P1.2 预研前置（2026-06-18 GitHub 调研后加 —— 别先自研聚类，先验现成）**：
- **动机**：2026-05 上游已变天。FunASR v1.3.3 / SenseVoice 已**内置说话人分离**（SenseVoice+VAD+CAM+++punc → 逐句 Speaker 0/1，无需外挂 pyannote）；sherpa-onnx 官方支持 **RK3588 / RK NPU / 昇腾 NPU** 的纯 ONNX 离线分离 + 现成 RK3588 SenseVoice 模型。P1.2 的"从零造 `speaker_tagger`（CAM++ 聚类）"很可能**缩水成"升级 + 集成"**。
- **预研 A — FunASR 自带分离**：把仓内 funasr 升到 ≥1.3.3，验 SenseVoice+VAD+CAM++ 逐句 Speaker 标签能否直接出；确认是否进流式 WebSocket 服务（vs 仅离线 AutoModel）。能用 → P1.2 直接砍掉，改"开关 + dashboard tag 显示（P1.3b）"。
- **预研 B — sherpa-onnx 在 3588**：用 sherpa-onnx 离线分离（pyannote 切分 + 3D-Speaker 声纹，全 ONNX）在 3588 实测 **rtf**；比自己把 pyannote 转 RKNN（task③ 判定为研究项目）省一个数量级。rtf 可接受 → 作 3588 离线分离底座。
- **判据**：A 或 B 任一过线，P1.2 不自研；都不行，才回退原 CAM++ 聚类自研方案。
- **gating**：技术储备性质，本期不实施；需 Phase B 双人录音（在 3588）做真机 rtf / 正确率实测。
- 调研来源见 Mac 演示仓 `docs/research_speaker_diarization_2026-06.md` 及本日 GitHub 调研（FunASR/SenseVoice、k2-fsa/sherpa-onnx、NVIDIA Sortformer）。

**P1.7/P1.8 回流说明（2026-06-18 从 Mac 演示仓 `av_understanding_mac` 的 ①② 回流）**：
- 源实现（Mac 演示线，已验证 23/23 单测通过）：`config/glossary.yaml`、`config/asr_postprocess_rules.yaml`、`modules/audio_processor/processor.py` 的 `_load_glossary()` / `apply_postprocess_rules()` / `_emit()` 切入。spec 修订记录见 `~/Documents/PKM/04-技/能力提高线/AI底座/演示就绪-3588转写硬伤修复-开发计划.md` 顶部。
- **关键落差**：3588 跑独立类 `AudioProcessorARM`（不继承 processor.py），且用 **SenseVoiceSmall（AutoModel CPU / RKNN NPU），非 FunASR websocket runtime**。
  - **P1.7 人名修复在 3588 不能照搬** —— Mac 侧 hotwords 走 FunASR runtime websocket 接口，3588 不吃。**先做 SenseVoice hotword 接口预研**：(a) `AutoModel.generate(hotword=...)` 是否支持 + 效果实测；(b) RKNN backend（`rknn_backend.py` / `SenseVoiceRKNNBackend`）是否支持热词，不支持则人名修复在 NPU 路径可能不可行，需退到 AutoModel CPU 路径或后处理纠错。预研产出结论后再定实施。
  - **P1.8 缩写后处理可直接移植** —— 纯文本规则函数与后端无关，把 `apply_postprocess_rules` + `config/asr_postprocess_rules.yaml` 搬进 `AudioProcessorARM` 构造 `TranscriptEvent`（processor_arm.py:339 一带）前对 final text 调一次即可，工作量小。
- **gating**：本期"3588 不混 Mac 演示"，P1.7/P1.8 待 Mac 演示过线后开工；真机验证需 2026-06-16 多人/含英文缩写录音（在 3588）。

**5/18 真音频回归已知现状（不在 P1.1/P1.3 范围）**：
- 冷启动丢字：点"开始转写"后头几句因 VAD RMS 阈值校准期被判 silence（`processor_arm.py` warmup 逻辑），后续连贯
- 无逐字 partial：sensevoice offline 模型能力上限，已在 §3.2 trade-off 表标记"必大改"才能升级

---

## 8. 工程纪律

### 8.1 大阶段启动 gating
- 大阶段切换 / 必备能力立项前 **必须**先做 GitHub 同类项目调研
- 报告 ≤ 1 天工时，保存 `docs/research/<topic>-<YYYYMMDD>.md`
- 没调研报告 → 不立项（防 5/14 YOLO26n 教训）

### 8.2 阶段固化原则
- tag 后 main / sprint 继续推进不影响 tag
- 销售可固定拉 tag 不被新 commit 影响
- 阶段间 tag 命名：`vX.Y-stageN-<one-word>`

### 8.3 实测优先于宣传
- landscape 调研要 reality check（5/14 YOLO26n 实测慢 5%，跟宣传 +43% 相反）
- 协议文档不可全信（厂家 PDF 错例多次），先抓真实流量

### 8.4 红线（不可越）
- 不动 `audio_processor` / sensevoice 长跑样本（user 在收集）
- 不动 `/home/firefly/creator_ai_demo/venv`（5.7G 共享 venv）
- 不 force push / 不动 `main` 分支
- 3588 上没 sudo 别试
- 不 SSH Jetson（无密码 + 红线）
- 不动 `:11434` Jetson ollama
- 不动 `:1880` 现有 Node-RED 部署 — 整理时先 cp 备份
- 不为子模块完美阻塞整体框架可运行性
- destructive 命令前先确认；不"防御性编程"吞错

---

## 9. 进度日志（近 10 天）

更早进度见 `ARCHIVE_2026Q2.md`。

### 2026-07-03（晚）— DNC 复刻 3588 funasr 引擎（脱 docker 化）+ 批量复刻 SOP

**背景**：user 验收发现 sense_voice 路线准确率/标点与 3588 差距大（引擎级差异），拍板放弃中间路线，把 3588 当前版本复刻到 DNC，目标批量复刻。

**本次推进（当晚走通，冷启动终验全绿）：**
- **docker 解锁判定定案**：DNC 内核 `CONFIG_BPF_SYSCALL is not set`（/proc/config.gz 实锤），runc 在 cgroup v2 设 device 规则必须 eBPF → 原生/cgroupfs/privileged 三姿势全部实测死。M1 全灭 → 按拍板走 **M3 脱 docker 化**（不动 U-Boot/内核）。
- **脱 docker 化落地**：阿里云拉 `funasr-runtime-sdk-online-cpu-0.1.12`（pull/create/export 不经过 runc，可用）→ `docker export` rootfs 到 `/opt/funasr-rootfs`（2.8G）→ 新单元 `deploy/systemd/funasr-server.service`（RootDirectory + MountAPIVFS + BindPaths 模型目录；**禁 Device* 指令**，会触发同一 BPF 报错；绕过 run_server_2pass.sh 直跑二进制——脚本会后台化 server 后退出，systemd 下会误判）。模型 1.7G modelscope 首跑自下。
- **引擎验收实锤**：rootfs 自带 client 喂 wav → 2pass-online 增量 partial 流 + 2pass-offline final 全标点分句时间戳（「…可以尝试重新生成，也可以稍微调节一下相应的住址。…不可以损害刷人的形象哦。」）。与 3588 逐字节同引擎。
- **切换**：av-demo 删 sense_voice 覆盖（回脚本默认 funasr_2pass）；nightly-restart 单元 DNC 适配三处 = 路径 sed / User=root / `AV_FUNASR_RESTART_CMD=systemctl restart funasr-server`（脚本已参数化，3588 默认 docker restart 不变）；**时区坑**：3588 板钟 UTC（20:23=北京 04:23）、DNC 板钟 CST → timer 改 04:23。
- **冷启动终验**：零人工 — funasr-server 自启 426 → av-demo 等 64s 就绪再拉 supervisor（防 5 次重连降级竞态）→ ws ESTAB → dashboard/node-red 200 → pulse 麦就位 45% → timer 在列。资源基线：funasr RSS 3.0G，整机 used 5G / avail 8G。
- **批量交付物**：`docs/deploy/dnc-replicate-install.md`（全离线资产包 ~14G 清单 + 金源导出命令 + A→Z 安装 + 板级参数表 + 验收清单 + 坑速查）。
- 手工 chroot 调试坑：需 `mount --bind /dev`（random_device 报错），服务本身 MountAPIVFS 不受影响。

**未完成 / 遗留：**
- 离线资产包物理归集（金源=本 DNC，命令在 SOP §1，user 定介质后执行）
- 麦克风 user 自理中；转写质量剩余差距主要看麦（引擎已同构）
- sense_voice 三处适配代码保留（backend-gated），route B 作降级链路随时可切

### 2026-07-03 — 湖森 DNC 麦克风转写收尾：转写窗 + node-red 面板 + 重启持久化

**本次推进（边界：不影响 3588，折腾只限 DNC；仓库改动均向后兼容、3588 默认行为不变）：**
- **转写窗断链根因修复**：sense_voice 离线路径 final 只发 `av/audio/command`，而 dashboard 转写 SSE 与 node-red 耳朵 topic 都吃 `av/audio/command_punctuated`，且 DNC/3588 模块清单均无 punctuator → 一直空窗。修法：`modules/audio_processor/main.py` 非 funasr 分支补发 punctuated 兼容 payload（与 funasr 分支同构）。**真实环境人声实锤验证通过**（DNC 抓包 4 条 source=audio_processor / raw_mode=sense_voice_rknn）。
- **逐字蹦渲染**：`web/static/renderers/transcript_seq.js` — final 落到无 partial 的空气泡时（sense_voice 离线特征）逐字定时显示 + 复用 `.tx-flash` 闪光，对齐 funasr 2pass 观感；funasr 路径行为不变。
- **`scripts/3588-demo-start.sh` 参数化**（默认值全保 3588 原行为）：`AV_ASR_BACKEND` 可覆盖（DNC=sense_voice_arm，内核缺 CGROUP_BPF 跑不了 funasr docker）、非 funasr 后端跳过 90s funasr 等待、`AV_PLAYBACK_CARD` 可配（DNC ES8388=2）、新增 `AV_MIC_PULSE_VOL` 开机固化 pulse 麦增益（pulse 独占声卡时 amixer 无效，7/1 DNC 实锤）。
- **DNC node-red 面板照搬 3588**：仓库 `node-red/` userDir + Mac rsync node_modules（135M，含 @flowfuse dashboard 2.0 + 经典 dashboard）；母亮遗留 user unit `node-red.service` 的 `--userDir` 指到仓库目录（原件备份 `.bak-20260703`），MQTT/creator 中控 TCP 均连通。
- **DNC systemd 自启**：`deploy/systemd/av-demo.service` sed firefly→proembed + DNC env（backend/增益/XDG_RUNTIME_DIR）落 `/etc/systemd/system/`，enable；mosquitto/docker/ollama 均已 enabled，proembed Linger=yes（pulse 开机可用）。
- 新事实：DNC 麦已换**真罗技 C920（046d:0892）**，pulse 40% 下 VAD 正常触发（旧杂牌 40% 触发不了、45% 才行）——增益按设备存于 pulse tdb，换麦后 45% 不再适用，现固化 40%。
- **🔴 开机竞态实锤（reboot#1 抓到）**：冷启动后 pulse default source 落到板载 `ES8388_Mic`（无麦）→ audio_processor 录全零（RMS 0.0000），且增益固化步骤把 40% 设给了错误的 source——这是 3588「6/9 重启录静音回归」的 pulse 版本。修复：demo-start.sh 增益固化步不信任 default source，显式扫 `pactl list sources` 找 USB 麦 → `set-default-source` + 定增益（等 USB 枚举最多 15s）。

**当日下午追加（user 实测反馈驱动，均已实测 + 入仓）：**
- 逐字蹦补漏：主转写面板走 dashboard.js 渲染路径，首轮只改了 transcript_seq.js → "整句蹦"。补同款逐字路径（`3592722`）。前端 JS 改动必须提醒 user 硬刷新浏览器。
- **仿 2pass partial**（`e36968e`）：user 要求对齐 3588 观感"灰词持续出、整句修正变实"。processor_arm 说话中每 `partial_interval_ms`(默认1200) 对已积累段重跑 SenseVoice（单次 ~370ms 实测），公共前缀 diff 发增量 av/audio/partial；final 整段替换自愈中途改写（实测「申公豹→申公道」正确修正）。设 0 关闭。3588 funasr 后端不走此文件。
- C920 还回 3588，DNC 换回杂牌 webcam（32e6:9221）→ 增益按 7/1 对它的标定调回 45%（av-demo env 同步）。user "打开 docker" 与转写无关（DNC docker 空、funasr 镜像已删），已澄清。
- **固化**：tag `dnc-sensevoice-partial-stable-20260703`（`e36968e`）；固化 reboot 终验全绿——冷启动零人工：backend/增益/default source/partial 全部与固化态一致，开机后真实语音即出 partial→final。

**未完成 / 遗留：**
- 转写质量粗（字面错误）不在本期：SenseVoice-RKNN 无 hotword 位，等瑞峰 4 问后定投入（demo 近讲 20-30cm + fast-path 句式）。
- DNC 上多插了一个 USB 音频设备（card5, 0x345f:0x2109）未启用；若是会议麦可考虑切采集源。

**下次接手所需上下文：**
- DNC=proembed@192.168.5.62（密码 xc），supervisor 由 av-demo.service 开机拉起，node-red 由 user unit 拉起（`systemctl --user status node-red`）。
- ssh 远程 pkill/pgrep -f 的 pattern 必须用 `[x]` 字符类防自匹配（本日踩 3 次：node-red、mosquitto_sub、pkill 杀掉带同串的远端 shell）。
- 湖森项目卡：`~/Documents/PKM/02-地/项目/湖森DNC视听理解落地/`（部署方案含 7/1 全 NPU gate 记录）。

### 2026-05-26 — ASR funasr 2pass D2 + 全链路端到端 + 全程实测调优

**本次推进（一天完成 ASR 重构 + 6 个 commit + 2 个 tag 上 GitHub）：**
- 晨：funasr 2pass docker arm64 镜像 save→scp→load 上 3588（3.0GB tar / 1.7GB 模型），server listen 10095 后 partial 1.71s / final 6.84s 实测通过 `funasr-2pass-d2-stable-20260526`
- 切 audio_processor backend = funasr_2pass ws 客户端：**ap RSS 6.3GB → 104MB（净省 6 GB），系统 mem_avail 1.6GB → 7.4GB**；supervisor 重启 9 模块 30s 不可用窗口
- 双标点 fix：funasr 自带 ITN 标点 + punctuator 二次加 punc → audio_processor 在 funasr backend 下直发 `av/audio/command_punctuated` 绕过 punctuator（commit `6544aca`）
- 副作用补：llm_engine 订阅 hardcoded `av/audio/command` 导致意图链路收不到 → 按 backend 智能切订阅 topic（commit `34e8443`）
- location filter 升级：支持 catalog `also_in` 共享路由（吧台窗帘 also_in=2FDiningTable 等）— `58103de`
- 后置 rewrite 实施：LLM 1.5B 偷换地点时强制纠回 default_location 等价 cmd — `3d459ff`
- **🚨 default_location + rewrite false positive 暴露**：user 跟同事聊"话筒维修返修工厂"被 LLM 误判 device_control 下发 `2FDiningTable_AirConditioner_TempDown` 真改空调 → 立即清空 default_location 进入 strict mode
- Jetson 视觉深思链路修通：scene_analyzer 从 `~/av_unified_mvp_jetson/` 起（不是 `~/av_unified_mvp/`，main_jetson.py 才管），qwen2.5vl-Q4_K_M VLM 首次 35s / 后续 11-15s 出场景描述，dashboard 视觉深思 panel 真数据出现
- 跨主机 escalate 链路实测：3588 拒（filter_rejected_whitelist）→ Mac mini ollama qwen3.5:4b 二次处理 → 回发 av/control 含 `escalated_from=3588`，correlation_id 正确传递
- node-red 3 个销售 demo flow cherry-pick from origin (`d3a254c`)
- dashboard 右下角 demo FAB 删除（外出演示对 mic 真说话不用按钮）— `5c767db`
- tag `funasr-d2-with-vlm-strict-20260526` 打在 `5c767db` 作为今日稳定究极点
- 全程 push GitHub 走 Mac LadderMac SOCKS5 9091（HTTP 9090 git SSL 不稳，3588 直连 push 卡死）

**已完成验收准则（spike plan 8 项）：**
- partial 延迟 1.71s ✓ / final 6.84s ✓ / RSS 切后 104MB ✓ / server RSS 3.44GB ✓ / 文本质量 ITN 标点准 ✓ / 段开头乱码消失 ✓
- 回滚演练未做（理论 < 60s，config 备份在 `~/av_unified_mvp/config/system_config.yaml.snapshot-20260526-stable`）

**未完成 / 已识别 backlog：**
- iCloud → `~/code/` 仓库迁移仍未做（icloud-git-hazard 5/21 实锤过 `.git/objects` 静默清空）
- LLM 误触发防护（入口 action-word gate / LLM 输出格式重设计为 `{device, action, location?}` 让 system 组装）— 解锁 default_location 安全恢复的前提
- ASR funasr `hotwords` 偏置为空，可加 `'餐桌 30 灯带 20 窗帘 20 吧台 30 工程部 30 会议室 20'` 改善 "财神→餐桌" 错字
- origin/sprint behind 8 commits 待处理（5/26 规则：丢 `eb93a26` `f08b2e3` `175f3ed` 三个语音相关；cherry-pick `58bc05b` 已做；其他 `4ea2e92` `aaa1e88` `82e9843` `c17ec53` 内容已实质包含或纯文档）
- Jetson VLM keep_alive 未常驻，每次冷加载 11-14s — ollama config 调
- 长跑 sustain：funasr backend 切换后 sustain_watch 自动跟新 ap_pid 4063857，RSS 漂移待 24h+ 复盘
- 演示包 + 销售材料 P0 之外的迭代

**下次接手所需上下文：**
- **stable tag**：`funasr-d2-with-vlm-strict-20260526` → `5c767db`（GitHub 有，git checkout 即回滚）
- **当前 feat 分支**：`feat/funasr-ws-backend-stable-20260526` tip `5c767db`，origin/sprint 不动
- **config 当前关键**：`system.default_location: ''`（strict mode 防 false positive）；切回不安全的 default_location=2FDiningTable 必须先做 action-word gate
- **Jetson scene_analyzer 启动方式**：`PYTHONPATH=/home/jetson/av_unified_mvp_jetson nohup python -m modules.scene_analyzer.main > /tmp/scene_analyzer.log 2>&1 &`
- **3588 supervisor 重启方式**：`AV_LLM_BACKEND=rknn AV_ASR_BACKEND=funasr_2pass setsid nohup python main.py >> /tmp/main_supervisor.log 2>&1 < /dev/null &`
- **memory 入口**：`project_funasr_d2_stable_20260526.md` 含完整命令 + 陷阱

---

### 2026-05-18 — 新阶段启动：两阶段框架定调 + 文档重构
- 战略定位写入第一行："AI 技术底座 + A/B/C 三层次（架构 = 形态对应）"
- §1.6 三步框架升级为 §3 两阶段框架
- 阶段一打 `v1.0-stage1-mac-validated` tag 固化（销售 >16GB Mac checkout 即用）
- 阶段二必备能力 trade-off 表写入：标点+纪要+说话人 mock 可不大改（~1d）；逐字 partial + 真整句修正 + 真说话人需大改
- Jetson 角色：5/15 "封板" → 5/18 "独立支线"（视频深思持续 + CUDA 语音验证）
- 根目录 30+ md 整理到 `docs/handoffs/` + `docs/reports/2026-05/`
- 新增 §8 工程纪律（GitHub 调研报告 gating）
- watcher 长测 763 samples / 62.7h 入仓 `data/longtest_20260515/`，零模块挂

### 2026-05-15 — Jetson 封板 + DEVELOPMENT_PLAN 拆分日
- 接收夜班 9.5h sustain 报告
- 3588 supervisor.log 5/15 00:54 后冻结根因 = Claude 授权弹窗
- 验证 llm_engine 健康（空房间静默 ≠ 死）
- 战略方向修订：研发收回 3588 单机主线；视觉深思已积累不再深入
- 修正：纪要生成已落地 / Mac mini .193 在用 / Jetson 跑 4 模块
- push `c60a666` + 写 `JETSON_FINAL_20260515.md`
- DEVELOPMENT_PLAN.md 简化拆分 200KB → 16KB + `LESSONS_LEARNED.md` + `ARCHIVE_2026Q2.md`

### 2026-05-14 — GTM 战略转向（25+ commits 一天）
- 演示包 + 销售内训材料 3 份
- web_browser husion 真接入 + 256 API endpoint
- control_dispatcher husion adapter + 5 场景
- 视觉三层链路：keyframe + openvocab + scene_analyzer
- commit 索引见 `ARCHIVE_2026Q2.md` §2

### 2026-05-13 — 阶段 3 漏斗第 2 层 NPU + 集成验证
- NPU LLM 1.5B 入仓 / av/control echo dispatcher / 3588 全栈起来

### 2026-05-12 — 3588 NPU 路径打通（国产化破局）
- 阶段 2 定调 / 三机部署收尾 / 默认地点解歧义

### 2026-05-11 — 双线推进 + start.command RAM 自适应
- Mac 假活 bug / Jetson Orin Nano 阶段 2 落地

### 2026-05-09 — LLM 切 qwen3.5:4b
- 内存省 4.2 GB + 反 hallucinate 兜底

---

## 10. 历史与归档指针

| 文件 | 内容 |
|---|---|
| `ARCHIVE_2026Q2.md` | 5/3-5/13 进度索引、5/14 commit 索引、R1-R6 演进、已废弃方向 |
| `LESSONS_LEARNED.md` | 踩坑 trap 速查、重大诊断教训、演示前 checklist、远期网络可观测性 |
| `JETSON_FINAL_20260515.md` | Jetson 角色文档（5/18 标注更新为"独立支线"）|
| `PLAN_R1_R6_subscription.md` | R1-R6 订阅式架构详细设计（仍有效）|
| `docs/handoffs/` | 历史接续文档（OVERNIGHT_HANDOFF + MORNING_RESUME 共 6 份）|
| `docs/handoffs/jetson-side-window-prompt.md` | Jetson 独立 Claude 窗口的 system prompt |
| `docs/reports/2026-05/` | 5/11-5/14 Subagent 报告（共 16 份 OVERNIGHT_REPORT + NIGHT_REPORT）|
| `docs/sales/` | 销售材料 3 份 |
| `docs/roadmap/` | landscape 调研 + liaohe-3588 路线图 |
| `docs/deploy/` | Mac / 3588-NPU / Jetson / 3588-demo-package 部署文档 |
| `summaries/*.json` | 会议纪要存档（5/9-5/11 共 4 份）|
| `scripts/longtest_watcher.sh` | 13 维度 5min 采样 watcher |
| `data/longtest_20260515/sample.jsonl` | 5/15-18 长测数据 763 samples / 62.7h |
| `~/.claude/plans/morning-resume-20260515-md-functional-quail.md` | /clear 接续指南 |

新归档（2026 Q3+）：另开 `ARCHIVE_2026Q3.md`，不再追加本文。
