**战略定位**：公司 AI 技术底座。
> 模块解耦 + 订阅制架构，让每次开发成果累积而非推倒重来。
> 客户只需要转写？装一个模块。需要视觉识别？插入另一个。需要全套？全部开。
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

**前置 gating**：GitHub 同类项目调研报告（见 §8 工程纪律）— 阶段二未启动前必须先做

**必备能力 / 不大改路径 trade-off**（关键决策）：

| 能力 | 当前 | 不大改路径 | 工时 | 必大改才能真正实现 |
|---|---|---|---|---|
| **逐字 partial** | ❌ | ❌ 无路径（sensevoice 模型不出 partial）| — | 换模型 paraformer/funasr，**大改** |
| **标点** | ❌ | ✅ LLM 后处理（独立 punctuator 模块或 audio_processor 内 post-process）| 0.5d | — |
| **整句修正** | ❌ | ⚠️ 短期窗口 LLM 重述（≠ 真 VAD 重判）| 1d，效果存疑 | 接 partial → final 重判路径，**大改** |
| **纪要** | ✅ 已有 | ✅ UI 提示 + 触发体验优化 | 0.1d | — |
| **说话人初步**（可编辑）| ❌ | ⚠️ silero-vad 切换 mock "说话人 1/2/3"（无真分离）| 0.5d | 接 pyannote / cam++，**中改** |

**"不大改可达"汇总**（合 ~1d）：标点 + 纪要 UI + 说话人 mock
**"必大改才有"清单**：逐字 partial · 真整句修正 · 真说话人分离

**待 user /clear 后拍板**：阶段二接受"不大改降级版"还是松绑红线？

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
| **P0.7** | **必备能力实施方案 trade-off 拍板**（接受"不大改降级"或松绑）| ⏳ user /clear 后 |
| **P0.8** | **GitHub 调研报告**（实时 ASR + 标点 + 说话人分离）阶段二 gating | ⏳ /clear 后 |
| P1.1 | 标点 LLM 后处理（独立 punctuator 或 audio_processor 内 post-process）| ⏳ P0.7 后 |
| P1.2 | 纪要 UI 提示 + 触发体验优化 | ⏳ |
| P1.3 | 说话人 silero-vad mock（顺序发言会议用） | ⏳ |
| P1.4 | 销售部署 README（`git checkout tag` 后 1 命令启动指南）| ⏳ |
| P1.5 | Jetson CUDA 语音验证报告（独立窗口完成）| ⏳ |
| P2.1 | video_processor CPU 减压（config 调 inference_fps / jpeg_quality / 单路 ⏸）| 看是否影响语音 |
| P2.2 | 控制指令"离线"误判修复（dashboard.js 多 client_id 状态合并）| 接受 or 修 |

**不做 / 仅技术储备**：双工对讲（持续 GitHub 关注） · 知识库 + 问答（另立项目）

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
