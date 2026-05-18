# av_unified_mvp 开发计划

> 项目长期开发蓝本（精简版，2026-05-15 重写）。
> 历史回合详情见 `ARCHIVE_2026Q2.md` · 踩坑教训见 `LESSONS_LEARNED.md` · 夜班报告见 `OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md` · Jetson 收尾见 `JETSON_FINAL_20260515.md`。

---

## 0. 快速接手（5 分钟）

| 项 | 值 |
|---|---|
| **当前主线** | **3588 单机推进**（5/15 user 拍板战略收缩） |
| **主线方向** | 辽河场景「转写 → 语意理解执行 → 会议纪要 → 知识库+问答（另立项目）」 |
| **当前 sprint branch** | `sprint/liaohe-3588-night-poc-20260511` |
| **3588 边缘机** | `firefly@192.168.5.6`，仓库 `/home/firefly/av_unified_mvp/`，venv `/home/firefly/creator_ai_demo/venv/`（共享，不动） |
| **Jetson** | `nvidia@192.168.5.51`，无 SSH 权限，所有诊断走 MQTT；已封板见 `JETSON_FINAL_20260515.md` |
| **Mac mini .193** | `openclawMiniOld`，跑 escalate llm_engine 兜底（语音 Miss）|
| **Mac mini .249** | `openClawMini`（user 办公桌），跑 Hermes，**与本项目无关** |
| **启动入口** | `./start.command`（Mac）/ 3588 上 `main.py` supervisor 已常驻 |
| **Dashboard** | `http://192.168.5.6:5050` |
| **下一步** | 见 §5 当前 sprint 看板 |

**5 分钟接手三步**：
1. 读本文 §0 + §1.6 + §5
2. 看 `LESSONS_LEARNED.md` 当前已知坑
3. 看最新 `OVERNIGHT_*.md` / `MORNING_*.md` 接续文件确认上次状态

---

## 1. 产品定位

**端侧"理解 → 编排 → 执行"系统**：
- 摄像头 + 麦克风 → 模块化"理解层"输出语义事件
- 事件经 MQTT 总线流转，**Node-RED 负责场景规则编排**（用户可拖拽改）
- Flask + 原生 JS 前端订阅事件流做实时展示
- 所有组件**优先离线**，可在边缘盒子（RK3588/Jetson/Mac mini）独立运行

---

## 1.5 产品定型方向（2026-05-13）

**当前阶段**：3588 单机精进 + Jetson 收尾封板 + Mac mini escalate 备用。

### 硬件矩阵（5/15 修订）

| 硬件 | 场景定位 | 当前状态 |
|---|---|---|
| **Mac / Mac mini** | 开发主战场 + escalate 兜底（.193 在用） | ✅ |
| **RK3588** | **主线推进**（涉密 / 国产化 / 一体机演示主力） | ✅ supervisor 11 模块稳定 |
| **Jetson Orin Nano** | 视频解析（VLM 偶发偏向单路）；封板，不再投入 | ⏸ 见 `JETSON_FINAL_20260515.md` |

**硬件选型决策原则**：客户场景定，不预设。涉密走 3588，要 VLM 多路走 Mac mini，省钱走 Mac mini。**三套都跑同一份 av_unified_mvp 代码**，差异通过 env / config 切。

### 产品形态（三条定型方向）

| 形态 | 核心 | 当前完成度 |
|---|---|---|
| **A · 纯转写 + 语意执行** （**辽河数码主线**）| 讯飞同款实时转写 + 语义理解 → 设备控制；护城河 = 准确率 + 端侧延迟 + 设备桥接灵活 | ASR ✅ / NPU LLM 第 2 层 ✅ / 反幻觉 ✅ / dispatcher echo ✅ / husion 5 场景 ✅ / **会议纪要生成 ✅**（`web/server.py:286+` + `summaries/`）|
| **B · 视频分析输出** | 边缘盒子，分布式多路分析输出"差异点"；护城河 = 分布式 | YOLO 单路 ✅ / 多路 RTSP ✅ / yolov8-world open-vocab ✅ / scene_analyzer VLM ⚠️ Jetson 内存边界 / 分布式差异点 ⏸ |
| **C · 利旧桥接 + 运维** | 甲方利旧设备桥接 + 跨品牌编排 + SLA 运维；护城河 = 模块化 + 协议契约 + 可观测 | husion 桥接 ✅ / creator 中控 ✅ / 跨品牌发现 ✅ / 运维可观测面板 ✅ / SLA 流程 ⏸ |

---

## 1.6 三步演进框架（2026-05-14 拍板 / 2026-05-15 修订）

### 第一步 · 验证解耦式模块订阅制 ✅
MQTT 总线 + 模块独立 supervisor + dashboard SSE 自适应。完成时间 5/8 + 5/13。

### 第二步 · 找合适硬件落地 + 系统包装 🔵 当前
**5/15 修订**：从"三机分工 + 攻城略地"收缩到"3588 单机主线"。

| 设备 | 角色（修订后） | 当前部署 |
|---|---|---|
| **3588** | 主线推进 — 转写 / 语意 / 会议纪要 / husion / Node-RED / Dashboard 全部 | supervisor 11 模块稳定，9.5h 不死 |
| **Jetson** | 视频解析（偶发单路），不再投入 | 4 模块在线，封板 |
| **Mac mini .193** | escalate 兜底，按需 | 1 模块（llm_engine escalate） |

**架构原则修订**：每机独立运行 + 独立 MQTT broker，跨机走 IP 订阅（演进项，今天不动；当前仍单 broker 3588）。

### 第三步 · 旧系统中间件 / 利旧 / 跨品牌 ⏸
等主线 sprint 收口、第二步系统包装稳定后启动。三个候选子场景：A 涉密 HDMI 视觉识别 / B 浏览器模块（已有 POC）/ C 智能家居桥接。

---

## 2. 目标架构（六层）

```
┌─ 1. 感知层 Capture  RTSP/USB 摄像头 | 麦克风 ─────┐
└─────────┬───────────────┬──────────────────────────┘
          ▼               ▼
┌─ 2. 理解层 Understand（每个都是独立模块/进程）────┐
│  audio_processor   FunASR 2pass / sensevoice      │
│  video_processor   YOLO + 多路 RTSP + MJPEG       │
│  llm_engine        意图分类 + 指令生成 + escalate │
│  keyframe_filter   关键帧过滤（VLM 入口节流）     │
│  openvocab_filter  yolov8-world 开放词检测        │
│  scene_analyzer    Jetson VLM（偶发单路）         │
└─────────┬─────────────────────────────────────────┘
          ▼  MQTT publish
┌─ 3. 总线层 Bus  mosquitto :1883 (3588) ───────────┐
└─────────┬─────────────────────────────────────────┘
          ▼  pub/sub
┌─ 4. 编排层 Orchestrate  Node-RED :1880 ───────────┐
│  用户拖拽：condition → action                     │
└─────────┬───────────────────────┬──────────────────┘
          ▼                       ▼
┌─ 5. 展示层 Present ──┐   ┌─ 6. 执行层 Act ────────┐
│  Flask + 原生 JS     │   │  control_dispatcher    │
│  /events/transcript  │   │  husion adapter        │
│  /events/video       │   │  web_browser (POC)     │
│  /events/intent      │   │                        │
│  summaries/ 纪要存档 │   │                        │
└──────────────────────┘   └────────────────────────┘
```

**设计原则**：
- **模块独立**：`modules/<x>/main.py` 可独立 `python -m` 启动，仅依赖 MQTT
- **协议先行**：MQTT topic schema 是合同，跨模块协作只看 schema，**不要 import 另一个模块的内部实现**
- **前端只订阅**：浏览器端不直接 connect ASR/YOLO，只走 SSE/HTTP

---

## 3. MQTT topic 协议

### 数据流 topic

| topic | 谁发 | 谁订 | 关键字段 |
|---|---|---|---|
| `av/audio/partial` | audio_processor | web、Node-RED | `text, seq_id, is_final=false, raw_mode` |
| `av/audio/command` | audio_processor | llm_engine、web、Node-RED | `text, seq_id, is_final=true` |
| `av/video/detect` | video_processor | keyframe_filter、web、Node-RED | `camera, time, detections[]`（**含空 detect 心跳** by `idle_detect_interval_s`） |
| `av/video/key_event` | keyframe_filter | scene_analyzer、openvocab_filter | `camera, reason, ...` |
| `av/video/scene_analysis` | scene_analyzer (Jetson) | dashboard | VLM 场景描述 |
| `av/video/openvocab` | openvocab_filter | dashboard | `hits[{class, conf}]` |
| `av/llm/event` | llm_engine | Node-RED、web | `event_type, original_text, intent, command, confidence` |
| `av/llm/escalate` | 3588 llm_engine | Jetson + Mac mini .193 llm_engine | escalate 兜底 |
| `av/control` | Node-RED / llm_engine | control_dispatcher / web | `target, action, params` |
| `av/control/dispatched` | control_dispatcher | web | 执行结果回传 |

### 公告 / 系统 topic

| topic | 协议 |
|---|---|
| `av/system/discovery/<module>` | retain=true，QoS=1，配 LWT。30s 心跳，崩溃 LWT offline |
| `av/system/host_stats` | CPU / 内存 / 磁盘，每 5s（system_info） |
| `av/system/network` | 网卡 / IP / 收发速率，每 10s（network_info） |
| `av/system/lan_scan/{cmd,progress,result}` | UI ↔ network_scanner |

**变更协议时必须同步更新本节、`config/system_config.yaml` 的 `topics:` 与 Node-RED flows。**

---

## 4. 语意理解模块的能力

| 能力 | 实现 |
|---|---|
| 实时转写 | FunASR runtime 2pass（Mac）/ sensevoice ARM（3588） |
| 标点 | use_itn=true + punc_ct-transformer + thuduj12/fst_itn_zh |
| 流式 partial | online paraformer 边说边出 |
| 整句修正 | 句末 VAD 触发 offline paraformer 整段重判 |
| 意图分类 | NPU 1.5B（3588 主线）+ escalate 兜底（Jetson + Mac mini）|
| 指令生成 | catalog driven 76 指令 + 反幻觉（location 校验） |
| 会议纪要 | LLM 一次调用 → 结构化字段 → `summaries/<id>-<title>.json` 留档（`web/server.py:286+`） |

---

## 5. 当前 sprint 看板（2026-05-15）

### P0 · 今天必做

| # | 任务 | 状态 |
|---|---|---|
| P0.1 | push 夜班 commit `c60a666` 到 sprint branch | ✅ done |
| P0.2 | 客户演示自检（dashboard / husion / 转写 / openvocab / 视觉深思单路） | ✅ done |
| P0.3 | Jetson 收尾文档 `JETSON_FINAL_20260515.md` | ✅ done |
| P0.4 | DEVELOPMENT_PLAN.md 简化拆分（本次） | 🔵 进行中 |
| P0.5 | 3588 llm_engine + control_dispatcher 静默异常诊断 | ✅ done — 进程健康，单纯空房间静默 |

### P1 · 今天能做就做

| # | 任务 | 备注 |
|---|---|---|
| P1.6 | Node-RED 充分开发 — 纳入 supervisor + 修 ENOENT | 121 节点 / 5 tabs 资产丰富 |
| P1.7 | web_browser 能用性评估 — 切 dry_run=False 试真实 goto | husion POC 已落，通用框架待验 |

### P2 · 写入规划，不今天做

- 每机独立 MQTT broker 架构演进
- 主线"语意理解执行"扩展（如会议中检索投屏）
- 主线"知识库 + 问答"另立项目启动（**不在 av_unified_mvp**）
- 主线"会议纪要"产品化深化（多说话人分离 / 长会议分段 / 检索）

### 已评估"不做"区（不再重启）

| 项 | 评估工作量 | 不做理由 |
|---|---|---|
| Jetson VLM 模型替换 3b→1.5b | 0.5d | 视觉深思方向封板（`JETSON_FINAL_20260515.md`） |
| scene_analyzer per-camera round-robin | 0.5d | 同上 |
| NPU 升 Qwen3-4B w8a8 | 不可行 | hf-mirror 下载链路阻断 |
| MCP 协议接智能家居 | 1-2d | 偏离主线 |
| yolov8-world 进一步深耕 | TBD | 已落地，当积累 |
| YOLO26n 升级 | — | 5/14 Sub-2 实测慢 5% + open-vocab 缺失，否决 |
| av/control → Node-RED 外露桥接 | — | 5/14 原 P0，客户硬件未枚举；改"等客户 enroll 后扩 adapter" |

---

## 6. 近 10 天进度日志（2026-05-09 至 2026-05-18）

更早进度见 `ARCHIVE_2026Q2.md`。

### 2026-05-18 — 周一回归：状况盘点 + 语音模块交付标准 gap

- 夜班 watcher 跑 62.7h（763 samples）：**0 模块挂 / 0 respawn / 温度 47-49°C** — 稳定性 OK
- 4 个症状真因：
  - 视频检测页/视频墙无 detect 标签 = 空房间正常（YOLO `detections=[]`），非 bug
  - 控制指令"离线" = **dashboard 前端误判**（进程心跳 10s 一次正常，命令实际下发）；多 client_id (3588+Jetson) 状态合并显示异常
  - **转写无标点 + 无整句修正 = 模型本身无 ITN decoder + 代码无整句修正实现**（仅 mode 字段未落地）
- 资源画像：video_processor 420% CPU / 1.1 GB RSS（绝对头号），audio 2% CPU / 576 MB；其余 8 modules 共 ~200 MB
- 语音"交付标准" gap：实时 partial / 中文标点 / 整句修正 / 多说话人分离 — 当前 0；Mac & 3588 都 fallback 到 SenseVoiceSmall（FunASR 2pass 容器未启）
- 当日完成：停 video 链路降温验证 / 写 `scripts/longtest_watcher.sh` / 5/18 plan 已送 Ultraplan 远程精炼
- 收尾 commit：5/15 写的 4 文档（DEVELOPMENT_PLAN 拆分 + LESSONS_LEARNED + ARCHIVE_2026Q2 + JETSON_FINAL）+ scripts/longtest_watcher.sh + data/longtest_20260515/sample.jsonl 入仓

### 2026-05-15 — Jetson 封板 + DEVELOPMENT_PLAN 拆分日
- 接收夜班 Subagent 9.5h sustain 报告
- 3588 supervisor.log 5/15 00:54 后冻结 root cause = Claude 授权弹窗（user 早上点 yes 解除）
- 验证：3588 llm_engine + control_dispatcher 进程健康（S sleeping in do_select，socket ESTAB），夜里空房间静默不是死
- 战略方向修订：研发收回 3588 单机主线；视觉深思已积累不再深入；Jetson 今天收尾
- 修正：**纪要生成已落地**（`web/server.py:286+`，`summaries/` 已有 5/9-5/11 4 份）
- 修正：Mac mini .193 escalate llm_engine 仍在用（mqtt discovery enabled）
- 修正：Jetson 跑 4 模块（不只 VLM 节点）
- push `c60a666` 到 origin sprint branch（夜班调参归档）
- 写 `JETSON_FINAL_20260515.md` 封板 + 硬件价值评估
- DEVELOPMENT_PLAN.md 简化拆分（200KB → 主文件 ≤30KB + `LESSONS_LEARNED.md` + `ARCHIVE_2026Q2.md`）

### 2026-05-14 — GTM 战略转向（25+ commits 一天）
- 演示包：3588 一键启动 + 浮球 5+5 颗 + 客户视图开关 + LOGO splash
- 销售内训材料 3 份（pitch + 视频脚本 + FAQ）
- web_browser husion 真接入（256 API endpoint 索引 + Playwright 框架）
- control_dispatcher husion adapter + 5 场景，端到端语音切大屏
- 视觉三层链路：keyframe_filter + openvocab_filter(yolov8-world) + scene_analyzer(Jetson VLM)
- AI 先进项目跟踪机制 + landscape 调研归档
- 夜班 sprint：VLM sustain 8h handoff（→ 5/15 完成）
- commit 索引见 `ARCHIVE_2026Q2.md` §2

### 2026-05-13 — 阶段 3 漏斗第 2 层 NPU + 集成验证
- NPU LLM 1.5B 入仓 + 漏斗第 2 层完整路径
- av/control echo dispatcher
- 3588 全栈 supervisor 起来，dashboard LAN 可达

### 2026-05-12 — 3588 NPU 路径打通（国产化破局）
- 阶段 2 定调
- 下午：三机部署收尾 + 默认地点解歧义 + 小模型 prompt 加固

### 2026-05-11 — 双线推进 + start.command 加 RAM 自适应
- Mac 假活 bug 修复
- Jetson Orin Nano 阶段 2 落地

### 2026-05-09 — LLM 切 qwen3.5:4b
- 内存省 4.2 GB + 反 hallucinate 兜底

---

## 7. 红线（不可越）

- 不动 `audio_processor` / sensevoice 长跑样本（user 在收集）
- 不动 `/home/firefly/creator_ai_demo/venv`（5.7G 共享 venv 还在用）
- 不 force push / 不动 `main` 分支
- 3588 上没 sudo 别试
- 不 SSH Jetson（无密码 + 红线）
- 不动 `:11434` Jetson ollama
- 不动 `:1880` 现有 Node-RED flow 部署 — 整理时先 cp 备份 `flows.json`
- 不为子模块完美阻塞整体框架可运行性（CLAUDE.md 节奏原则）
- destructive 命令前先确认；不"防御性编程"吞错

---

## 8. 历史与归档指针

| 文件 | 内容 |
|---|---|
| `ARCHIVE_2026Q2.md` | 5/3-5/13 进度日志、5/14 commit 索引、R1-R6 演进、阶段二旧路径、已废弃方向 |
| `LESSONS_LEARNED.md` | 踩坑 trap 速查表、重大诊断教训、演示前 checklist、远期网络可观测性、AI 协作经验 |
| `OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md` | 5/14 夜班 9.5h VLM sustain 完整报告 |
| `OVERNIGHT_HANDOFF_VLM_SUSTAIN_20260514.md` | 5/14 夜班 handoff（已归档完成） |
| `JETSON_FINAL_20260515.md` | Jetson 角色封板 + 硬件价值评估 |
| `MORNING_RESUME_20260515.md` | 5/15 早晨接续文件（已 superseded by 本文 §5） |
| `PLAN_R1_R6_subscription.md` | R1-R6 订阅式架构详细设计（仍有效） |
| `docs/sales/` | 5/14 销售材料 3 份 |
| `docs/roadmap/` | landscape 调研 + liaohe-3588 路线图 |
| `summaries/*.json` | 会议纪要存档（5/9-5/11 共 4 份） |

新归档（2026 Q3+）：另开 `ARCHIVE_2026Q3.md`，不再追加到本文。
