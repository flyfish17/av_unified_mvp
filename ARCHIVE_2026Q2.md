# 2026 Q2 归档索引

> 历史进度日志、调研报告、Subagent 产出的索引文件。
> 详细回合内容、命令片段、文件改动清单走 `git log -p <hash>` 与原始 Subagent 报告。
> 当前主线请看 `DEVELOPMENT_PLAN.md`，踩坑教训看 `LESSONS_LEARNED.md`。

---

## 1. 关键时间节点

| 日期 | 节点 | 关键 commit / 产出 |
|---|---|---|
| 2026-05-03 | 全链路通：MQTT/SSE/WS/YOLO 走通 | （见 §6 回合 10） |
| 2026-05-07 (回合 26) | Mac Studio 装 funasr-2pass + 麦克风自检 + 诊断方法论复盘 | |
| 2026-05-07 (回合 27) | P1 整体 UI 用户可调 — GridStack 拖动 + 模块可见性 + 视频源 CRUD + LAN 扫描增强 | |
| 2026-05-07 (回合 28) | P0 端到端：语音 → 意图 → creator 中控 → 物理设备（L1 + L2 全通）| |
| 2026-05-07 演示前打磨 | UI 文案、视频墙 badge、Node-RED 默认页排序 | |
| 2026-05-08 (回合 29) | L3 摄像头自动化 + P0 二阶段（分布式协议）+ husion 跨品牌桥接 + r28-snapshot 上传 | |
| 2026-05-08 | LLM 切 qwen3.5:4b — 内存省 4.2 GB + 反 hallucinate 兜底 | |
| 2026-05-11 | Mac 假活 bug 修复 + Jetson Orin Nano 阶段 2 落地（双线推进） | |
| 2026-05-11–12 | 多端部署 + start.command 加 RAM 自适应 | |
| 2026-05-12 | **3588 NPU 路径打通，国产化破局完成**（阶段 2 定调） | |
| 2026-05-12 下午 | 三机部署收尾 + 默认地点解歧义 + 小模型 prompt 加固 | |
| 2026-05-13 | 阶段 3 漏斗第 2 层 NPU 后端入仓 + 集成验证 | |
| 2026-05-14 | **GTM 战略转向 + 三形态全链路落地**（25+ commits 一天）| 见下方 commit 索引 |
| 2026-05-14 夜班 | VLM sustain 9.5h 实验 + 调参 + 报告 | `OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md` · `c60a666` |
| 2026-05-15 | Jetson 角色封板 + DEVELOPMENT_PLAN 简化拆分 | `JETSON_FINAL_20260515.md` |

---

## 2. 5/14 GTM 战略转向 — 25+ commits 索引

按主线分类（commit 全文见 `git log --pretty=format:"%h %s" <branch>`）：

### 演示包 / 销售
- `0ef01e1` `0ae5dac` 3588 演示一键启动 + 浮球 5+5 颗
- `48bb4c1` 客户视图开关 + LOGO splash + openvocab SSE 桥 + husion API
- `c95c403` 销售内训材料 3 份（pitch + 视频脚本 + FAQ）
- `a0d12cd` 视频墙 raw 流畅模式（user 反馈不要 burn-in bbox）

### 浏览器 / 跨品牌融合
- `d4ed9d5` web_browser Playwright POC 框架
- `c67f114` web_browser husion 真登录 + 256 API 索引 + hls 直拉
- `97fcc86` web_browser `_husion_switch_scene` 真接入
- `5687a5f` control_dispatcher husion adapter + catalog 5 场景

### 视觉深度理解三层链路
- `f070527` keyframe_filter（关键帧过滤）
- `5571c7b` openvocab_filter（yolov8-world open-vocab 第三层）
- 引用提及 `587f230` scene_analyzer Jetson VLM

### 看板 / 文档
- `9f1bdcc` AI 先进项目跟踪机制（`docs/roadmap/ai-landscape-20260514.md`）
- `8022a5d` plan §11 sprint 看板重排 P0/P1/P2
- `019253f` Flask 启动 3 次 retry × 8s（**5/14 后期发现没生效** — werkzeug print+sys.exit 绕过 OSError，task #54 真修）
- `a353a8d` husion online 字段容错（"1G-M" 视为 online）
- `ed0298a` Sub-5 yolov8-world open-vocab 实测报告
- `7b56260` 3 份 Subagent 5/14 报告入仓

### Subagent 5/14 报告（原文留仓）
- Sub-1 NPU Qwen3-4B w8a8 下载试验（hf-mirror 154KB/s × 8.7h 放弃）
- Sub-2 YOLO26n 实测（慢 5% + open-vocab API 缺失，否决）
- Sub-3 通用 husion adapter 化（part of `5687a5f`）
- Sub-4 手势识别 MediaPipe 调研（7-9h 工时，⏸ sprint 收口后）
- Sub-5 yolov8-world + CLIP 实测命中报告
- Sub-7 dashboard husion + openvocab 主面板（part of `48bb4c1`）

---

## 3. R1-R6 订阅式架构演进（回合 14-17，5/3-5/6）

完整设计文档：`./PLAN_R1_R6_subscription.md`

| 阶段 | 内容 | 状态 |
|---|---|---|
| R1 | 公告协议统一 + LWT（`av/system/discovery/<module>` retain，30s 心跳，崩溃 LWT offline） | ✅ |
| R2 | main.py 退化为 supervisor（subprocess.Popen 拉独立进程，崩溃指数退避重拉） | ✅ |
| R3 | UI 动态化：订阅 `av/system/discovery/#` 自动长出 panel；3 种 renderer（transcript_seq / kv_table / mjpeg）；失活灰显 | ✅ |
| R4 | MJPEG 视频画面（video_processor 自带 5051 端口 + 按需 enable/disable） | ✅ |
| R5 | Node-RED iframe 嵌入（settings.js 解 X-Frame + start.command 自动起 1880） | ✅ |
| R6 | 三个新订阅模块（system_info / network_info / network_scanner） | ✅ |

**关键决策**：Node-RED 嵌入 = iframe 编辑器；main.py = 纯 supervisor（消除 `_on_audio_event → self.llm` 后门）；renderer 极简 3 种；公告失活灰显保留不删；视频走 MJPEG `<img src>` 按需启用；554 LAN 扫描 asyncio 重写（30s+ → ~3s）

---

## 4. 阶段二精进路径（5/12 之前规划，部分已完成）

### 第一梯队（客户演示直接受益）
- **A. partial 逐词追加渲染** ✅（`ea4216b 2af83e2 f154ea9`，2026-05-11）
- **B. creator 分布式 driver** ⏸（协议探明 TCP :12121 + 123456，等 user 让 session）
- **C. husion 辅模式 — 事件回传** ⏸（前提：user 确认 husion 接收方式）

### 第二梯队（能力深化）
- D. 跨摄像头 re-id（1-2d）
- E. VLM 视频帧描述 — **已并入 5/14 scene_analyzer 落地**
- F. 检测事件持久化（半天）
- G. 多 LLM 路由（半天）— **已并入 5/14 escalate 兜底**
- H. 多说话人分离 cam++ / SOND（1d）

### 第三梯队（战略 / 工程）
- I. 国产化预研（FunASR / YOLO / ollama on RK3588）— **已完成，5/12 阶段 2 NPU 路径打通**
- J. start.command 鲁棒性 + 配置中心 web UI（半天）
- K. Flask 启动失败异常传播（30min）— **已修但未生效**，task #54

---

## 5. 历史下次优先项（不再激活）

1. 转写体验对标讯飞（partial 逐词追加）— **已完成 5/11**
2. 转写卡 enable/disable 按钮（回合 26 答应过）— 未做
3. start.command 鲁棒性（回合 25/26 累积小坑）— 部分修
4. 国产化路径预研 — **5/12 完成 NPU 路径**

---

## 6. 旧版 §6 进展（5/3-5/12 回合详情）

完整内容在 git history：
- 回合 1-10：项目初始化 + P0 全链路自动化通
- 回合 11-13：FunASR 2pass / R1-R6 设计
- 回合 14-17：R1-R6 订阅式架构演进
- 回合 18-25：阶段一收口 + 巩固冲刺 K1-K8
- 回合 26：Mac Studio 装 funasr-2pass + 麦克风自检 + 诊断方法论复盘
- 回合 27：P1 整体 UI 用户可调（4 子项）
- 回合 28：P0 端到端语音 → creator 中控
- 回合 29：L3 摄像头自动化 + P0 二阶段（分布式协议）+ husion 跨品牌桥接 + r28-snapshot 上传

要重读详情：`git log --all --pretty=format:'%h %ad %s' --date=short` 找日期，然后 `git show <hash>`。

---

## 7. 已废弃方向

| 项 | 原计划 | 否决原因 |
|---|---|---|
| ~~YOLO26n 升级~~ | landscape 宣传 43% 提速 + open-vocab | 5/14 Sub-2 实测慢 5% + API 缺失；改 yolov8-world |
| ~~av/control → Node-RED 外露桥接~~ | 5/14 原 P0 | 客户硬件未枚举；改"等客户 enroll 后扩 dispatcher adapter" |
| ~~NPU 升 Qwen3-4B w8a8~~ | 替代当前 1.5B | 5/14 Sub-1 hf-mirror 下载链路阻断 8.7h 放弃 |
| ~~Jetson VLM 模型替换 3b→1.5b~~ | 夜班 Subagent 推荐 | 5/15 user 拍板视觉深思方向封板，Jetson 不再投入 |
| ~~scene_analyzer per-camera round-robin~~ | 夜班 Subagent 推荐 | 同上 |
| ~~MCP 协议接智能家居~~ | landscape D2c | 5/15 偏离主线，不做 |

---

**归档原则**：本文不再追加新内容；2026 Q3 新归档另开 `ARCHIVE_2026Q3.md`。

## 归档于 2026-08-22（DEVELOPMENT_PLAN 整体梳理）

### 原 §3.2 阶段二 5/18 路线（已被 funasr 2pass + CAM++ speaker_diarizer + rkllm 纪要实际落地取代）

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

### 原 §6 语音能力实测（5/18 快照，已过时）

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

### 原 §7 Sprint 看板（7.15 / 7.18）

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

### 原 §9 进度日志（5 月条目）

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
