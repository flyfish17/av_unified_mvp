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
| P1.2 | `modules/speaker_tagger/` — silero-vad 切片 + CAM++ embedding + 聚类 | ⏳ 等 Phase B 数据 |
| P1.3b | 转写卡说话人 tag 显示（dashboard 改造）| ⏳ P1.2 后 |
| P1.4 | 纪要 UI 提示 + 触发体验优化 | ⏳ |
| P1.5 | 销售部署 README（`git checkout tag` 后 1 命令启动指南）| ⏳ |
| P1.6 | Jetson CUDA 语音验证报告（独立窗口完成）| ⏳ |
| P2.1a | video_processor YOLO 搬 NPU（`yolov8n_rknn_model`，config 一行切换）| ✅ 8/21 下午修复落地：DFL softmax fp16 溢出根因 → `scripts/export_yolo_rknn.py`；62 实况 15min 零异常、检出与 .pt 一致 |
| P2.1b | video_processor 捕获侧减压：5 路软解 + 逐帧 JPEG 预编码疑为 CPU 大头（62 瞬时 ~600%，.pt/rknn 无明显差别）— RTSP 走子码流 / JPEG 只在有 MJPEG 客户端时编 / rkmpp 硬解 | ⏳ 先量化三者占比再动 |
| P2.2 | 控制指令"离线"误判修复（dashboard.js 多 client_id 状态合并）| 接受 or 修 |

**不做 / 仅技术储备**：双工对讲（持续 GitHub 关注） · 知识库 + 问答（另立项目）

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

### 2026-08-18 — 门禁联动模块 door_access 落地（公司大门云眸远程开门）
- **本次推进**：新增 `modules/door_access/`（云眸 token 缓存刷新 + 远程开门 + 门口 person 检测去抖 → av/door/visitor）；supervisor 按 `door_access.enabled` 条件拉起并桥接 door SSE channel；dashboard 右上角访客弹窗（开门按钮 + 结果状态行）；配置样例入 example yaml
- **前置验证**（当日实测）：云眸 4 接口全链路通（token 7 天 / 事件查询 / 远程开门真开门，事件码 5/75 人脸过、5/21 开、5/22 关、3/1024 远程开、3/1029 心跳）；设备 E51574183 已绑 flyfish 账号；内网 ISAPI 备选路线卡在 isActivated=false + 无 admin 密码（192.168.2.88，DHCP 需改静态）
- **踩坑已修**：模块内 token 稳定 401 根因 = 子类 `self.client_id` 被 BaseModule.__init__ 覆盖成 MQTT client_id（属性名撞车，base_module.py:64）——改名 hik_client_id 后 token 预热 604795s 通过。**BaseModule 子类禁用 client_id/broker/port 等基类字段名**
- **未完成项**：① 门口摄像头尚未接入（camera_name=门口 待配真实源）；② 开门按钮无操作权限控制（内网任何人可开大门，上线前必须加）；③ 云眸消息通道 open_event_access 可替代轮询（注意 7 天不用自动停用）
- **下次接手所需上下文**：账号/秘钥/设备/事件码见 memory `door-access-hik-cloud`；测试配置样例 `config/system_config.example.yaml` door_access 段；协议原文 iCloud `设备协议/门禁开门协议.docx`

### 2026-08-21 — 纪要机 HDMI 开机信息屏（总部测试/演示环境 P0）
- **本次推进**：从 creator_om `deploy/hdmi-info/` 移植到本仓 `deploy/hdmi-info/`（`creator-asr-hdmi-info.sh` + `.desktop` + README），commit `95c8959`。文案改"CREATOR 转写纪要机 · 开机信息"；每个网口标注 DHCP/静态（nmcli ipv4.method）；服务判定三态（:5050 回 200=运行中 / 仅 av-demo active=启动中 / 未运行）；过滤 can0。**已装 5.6**（`/usr/local/bin` + `/etc/xdg/autostart`，autologin firefly 开机自动全屏），当前 HDMI-1 1080p 已在显示
- **验证**：5.6 实跑帧输出正确（eth1 192.168.5.6 DHCP 自动获取 / eth0 静态 .245 插线即活 / 网关 .1 / 运行中 http://192.168.5.6:5050）；未截屏（板上无 scrot/xwd），字号 `-fs 26` 需人眼目检
- **未完成项**：未并入 DECISIONS 第 9 条（布局弹窗灰置 + 客户视图按钮隐藏）的部署窗口——那两处前端小改仍待做
- **下次接手所需上下文**：5.6 安全重启手法见 memory `cr-dig7201-3588-meeting-asr`；信息屏立即重开命令见 `deploy/hdmi-info/README.md`

### 2026-08-21（下午）— 形态切换脚本 + YOLO 搬 NPU（62 实测）
- **背景判断**（用户探讨后定）：一台 3588 全功能、按重启切 meeting_asr/full 形态——机制早已具备，缺一条命令；两形态在 3588 上**互斥**（YOLO 占 CPU / NPU IOVA 4G），不做热切、不给前端按钮（防客户误切）。纪要外放：rkllm backend `llm.summary.url` 可配且热读（指向另一台 3588 NPU 零代码）；ollama 路径 `web/server.py:556` 硬编码 127.0.0.1，要外放 Mac Studio 需改读 config（未做）。外部进展：rkllm 1.3.0 支持 Qwen3.5（0.8B/2B/4B），IOVA 4G 无解（IOMMU v1 GFP_DMA32）。
- **切换脚本**：`scripts/switch-profile.sh full|meeting_asr|--status`（commit 3a9699f）。SIGKILL 老 supervisor/模块/rkllm daemon → `systemctl restart av-demo` → 等 :5050 200 + 模块数。`3588-demo-start.sh` EXPECTED_MODULES 改为按 config 推导（meeting_asr+net_multicast=6 / full=10）。5.6 上 `--status` 已验证；**full↔meeting_asr 实切未跑**（远程重启被权限拦，留用户执行）。
- **YOLO 搬 NPU（62）**：62 板上独立 venv 装 rknn-toolkit2 2.3.2（aarch64 wheel 可得；onnxoptimizer 无 wheel、源码编译失败，`--no-deps` 跳过不影响导出）→ `YOLO("yolov8n.pt").export(format="rknn", name="rk3588")` 32s 出 `yolov8n_rknn_model/`（7.9MB fp16）。**代码零改动**：`processor.py:103` `YOLO(path)` 走 ultralytics AutoBackend 识别 rknn 目录，运行时只需生产 venv 装 `rknn-toolkit-lite2==2.3.2`（ultralytics AutoUpdate 自动装了，已记入 requirements 注释）。
- **实测数字（62，1280×720，50 帧均值）**：CPU .pt 1167ms/帧·进程 CPU 246% → NPU **106ms/帧·112%**，检出 6 目标/类别一致；NPU Core0 33%。**但 video_processor 整进程稳态 441% → ~370%**，剩余大头 = 5 路 RTSP 软解 + 捕获线程逐帧 JPEG 预编码（`processor.py:53`），不是推理 → 立 P2.1b。
- **⚠️ 实况验证失败（13:10 发现，已回退）**：rknn 模型常驻 80 分钟内 781 次 `推理异常: cannot convert float NaN to integer`（本机摄像头 505 / 财务监控 194 / 分布式 73），**零有效检出**；bus.jpg 基准正常说明运行时链路通，问题在真实帧上 fp16 输出 NaN（疑点：USB 摄像头/RTSP 帧尺寸与 640 letterbox、fp16 溢出；下一步试 `int8=True` 量化导出 + 用真实帧做校准集、或固定 imgsz 预处理后再喂）。62 已回退 `yolov8n.pt`，异常归零。
- **数字更正**：前面"441%→370%"是 `ps` 生命周期均值，不是瞬时值；回退 .pt 后 `top` 瞬时同样 ~610%，**整进程 CPU 在 .pt/rknn 间无可比数据**。可靠的只有隔离基准（106 vs 1167 ms/帧）。模型入库 `yolov8n_rknn_model/` 保留作 POC 产物，**未过验收，别部署到 5.6**。
- **切换脚本补丁（用户实切暴露）**：切 full 后 `audio.source` 仍是 `net_multicast` → supervisor 去掉 audio_processor，全功能演示没有 C920 拾音。修：语音输入跟形态走（full=mic / meeting_asr=net_multicast），形态相同但 source 不符也执行，`--status` 显示语音输入与 USB 麦（commit b346df5）。**用户 8/21 在 5.6 实切验证完成**。
- **NaN 根因与修复（14:00-15:00，半天量内）**：离线用真实 RTSP 帧复现——推理不崩但原始输出 box 宽高通道含 **inf**（fp16 上限 65504，已见 45600），cls 通道干净 → 定位到 DFL 头 softmax 在 RKNN fp16 上不减 max、背景 anchor 的 exp 溢出 → NMS 出 NaN → `plot()` 崩。**修**：导出时 monkey-patch `DFL.forward` 在 softmax 前减每组 max（数学等价）+ `opset=17`（torch 2.2 ReduceMax 兼容）→ `scripts/export_yolo_rknn.py`。验证：3 张真实帧 inf=0、与 .pt 检出/类别一致；RTSP 300 帧 plot 零异常；同过滤条件（conf 0.5，person/phone/laptop）80 帧 .pt 与 rknn 各命中 40 person 完全一致；**62 实况 15min 零异常，NPU Core0 30%**。62 现常驻 rknn 模型，新模型 md5 e99a493f… 已入库覆盖。
- **int8 路线否决**：32 张现场帧校准量化后 inf 消失但零检出——box(0-640)/分数(0-1) 同张量 8-bit 把分数压 0；要走 int8 得拆头（rknn_model_zoo 做法），收益不值，记 README 不再试。
- **顺带发现（待查，与本次无关）**：生产日志全天 `[detect]` 全是 `(0 目标)`（.pt 与 rknn 相同），且 .pt 时段 75min 刷 26987 条心跳——`idle_detect_interval_s` 15s 节流疑似失效 + conf 0.5 下门口/财务几路是否真无人，下次看。
- **视频墙单路/四分屏互斥（15:00，用户拍板"默认一路，四屏与转写互斥"）**：纯前端 + config，后端零逻辑改动（复用 `/camera/<名>/enable|disable` 与 `av/audio/cmd`）。默认 `single`：只开 `video.meeting_camera`（缺省第一路），其余路 disable、画格收成 1 格（CSS `.video-wall.single`）；视频卡头部"⊞ 四分屏"按钮 → 转写在跑则确认框"将停止转写"→ audio disable → 前 4 路 enable；转写"启动"在四分屏下 → 确认框"切回单路"→ 先收单路再 audio enable。刷新回 single（不持久化，多路=显式动作）。会议摄像头名由 `web/server.py` 注入 `<body data-meeting-camera>`。
- **校验（Playwright 对 62 真机三步）**：初始 single/仅画格 1=本机摄像头；点四分屏 → 弹确认 → 请求序列 `av/audio/cmd disable` + 3 路 enable，按钮变"▭ 单路"；点转写启动 → 弹确认 → 3 路 disable + `audio enable`，回 single。in-flight 5s 去重后无重复请求。**负载：单路下 video_processor 48.7% CPU、整机 90% idle（5 路时 ~530-610%）**——"一路辅助转写 + 纪要并行"在一台 3588 上成立。
- **发言人区分（声纹）回流 + 声源选择 + 侧栏开关（16:00-16:15）**：
  - 背景：单麦发言人区分早在 `av_understanding_mac` 7/29-7/30 S1-S6 完成（CAM++ 逐句嵌入+在线聚类），但 **Mac Studio 本地 checkout 落后 GitHub 20 commit、且从未回流本仓**。今日 ff 本地并手工移植（两仓 processor.py 分叉 260 行，不能 cherry-pick）。
  - 移植内容：`modules/speaker_diarizer/`（原样）+ `modules/audio_processor/segments.py`（原样）+ processor.py 段 PCM 缓冲/`TranscriptEvent` 加 segment_id 等默认字段 + audio_processor main 接 SegmentSink（`speaker_diarizer.enabled` 才起）+ supervisor 按 config 拉起模块、订 `av/audio/diarization` 推 SSE + 前端 `applyDiarization`：final span 带 `data-segment-id`，结果晚到按 segment_id 回填；段无人→打标，段属别人→**从该 span 起切新段**、本地麦段指针跟过去，与话筒号分段同构（`.tx-spk` + `para.dataset.speaker`），纪要归属零改动。config example 加 `speaker_diarizer` 段。
  - 声源选择：`audio.active_source: mic|net_multicast`（两路同配时开机只一路转写），`net_audio_capture` 补 `av/audio/net_cmd {action: enable|disable}` + `running` 公告；转写卡 `<select data-tx-source>` 两模块都在线才显示，选谁 enable 谁 disable 另一个；停止按钮/四分屏停转写按当前声源发命令。
  - 侧栏：`body[data-app-profile=meeting_asr]` CSS 改为 `body.nav-hidden` 开关，顶栏"☰ 导航"，meeting_asr 默认收起、full 默认展开、localStorage 记忆。**至此界面差异全是开关，profile 只管起哪些模块。**
  - **62 验证**：venv 补装 funasr 1.3.1、CAM++ 模型（28MB）从 Mac 下载拷入；13 模块上线，CAM++ 就绪 8s。注入 8/20 会议录音 14 段（/mock/transcript + av/audio/segment）→ diarizer → SSE → 前端段标 S1，链路全通；mock S1/S2 晚到事件验证切段正确（S1 段句1-3 / S2 段句4-7，后到句接 S2）。☰ 开关正常；声源下拉在 62 单声源下正确隐藏。
  - **诚实边界**：① 14 段全归 S1——该录音是 8 路混音+远场，两两余弦全 ≥0.53，**不能判定分离好坏**；Mac 标定（异人 ≤0.28）是近讲样本，C920 近讲两人实测待做；② `net_audio_capture` enable/disable 代码走读、未实机（5.6 是总部测试机）；③ 声纹发言人（S1/S2）暂不支持点标签改名（话筒号路径支持），Mac S6 的改名广播未移植。
- **纪要线剩余 3 项回流（16:20-16:35）**：① 人名修复——Mac 8a3f6f6 的纯函数抽到 `core/asr_glossary.py`（core 共享层，audio_processor 与 net_audio_capture 8 路都用），`config/glossary.yaml`（人名/产品/术语→FunASR hotwords，json dict 协议）+ `config/asr_postprocess_rules.yaml`（final 英文缩写还原），单测移植 `tests/test_asr_glossary.py` 23 过（Mac、62 两地）；② 转写留档——`core/transcript_store.py` 原样 + 3588 补 mic_id/physical_id 字段，supervisor `_on_audio_command` append_text / `_on_audio_diarization` append_update（segment_id→id 映射），`GET /api/transcript/today[?format=txt]`；③ ws 自愈——`ws_giveup_after_s` 默认 120s 按断联时长放弃，替代 5 次≈30s。62 验证：启动日志 9 热词/8 规则；MQTT 注入 final+diarization → jsonl 两行 → API txt 输出 `S2：…`。**回流表纪要项全部 ✅，两线纪要软件能力对齐。**
- **未完成项**：① ollama url 读 config；② detect 心跳洪泛/零目标排查；③ P2.1b；④ 5.6 full 形态（lite2 + rknn 模型 + meeting_camera + speaker_diarizer 模型 + glossary）；⑤ C920 两人实测声纹分离；⑥ 声纹发言人改名（Mac S6）；⑦ .62 启动脚本"等 426"兜底随 ws 自愈可简化。
- **下次接手所需上下文**：62 导出 venv `~/rknn-export-venv`、产物 `~/yolo-rknn/`；pgrep 自匹配坑又踩一次（等待循环的 pgrep 模式匹配到自身、永不退出），见 memory `ssh-pkill-self-match-trap`。


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
