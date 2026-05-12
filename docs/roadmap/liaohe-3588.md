# 辽河数码 3588 整体方案 — Roadmap

> B 线（直接客户 / 低成本端侧）的首个落地标的。
> 完整原始 sprint plan 在 `~/.claude/plans/3588-demo-1-50-mac-3588-3588-2-3588-ai-streamed-riddle.md`（240 行，含 PoC 数据 + 详细任务清单）；本文是 **入仓的凝练版 + 阶段 2 收尾后的现状更新**。

## 0. 业务定位

- 客户感知核心：「**讯飞同款实时转写**」（讯飞本地部署 50 万 / 云端订阅几十元/月 + 调用次数限制）
- 我们的差异化护城河：**转写基础上叠加语义理解 + 物理执行**（讯飞做不到）
- 3588 是**载体试错**而不是目的：能跑通发挥 NPU 优势，跑不通立刻换硬件

**两条战略原则**（用户 5/11 当面确认）：
1. 客户需求第一，先做讯飞同款转写（去 50 万溢价），再加语义+执行差异化
2. 3588 既然在手就开发好，NPU 优势要发挥但不喧宾夺主于业务核心

## 1. 当前状态（截至 2026-05-12 阶段 2 收尾）

| 阶段 | 范围 | 状态 |
|---|---|---|
| 1 | Mac 讯飞观感 baseline（partial 逐字蹦 + 流式降噪 + final 定稿动画）| ✅ 完成 |
| 2 | 3588 端转写复刻 + 三阈值判定 | ✅ 完成（**NPU 路径过线**）|
| **3** | **3588 端语义理解 + 物理执行**（两级漏斗 LLM + Node-RED av/control 桥接）| **未启动** |
| 4 | 辽河方案落底文档 + 整机演示版本 | 未启动 |
| 二期 | 视觉 NPU（YOLO + L3 摄像头自动化）| 条件触发 |

### 阶段 2 三阈值实测（5/12）

| 阈值 | 要求 | Jetson CUDA | 3588 NPU (RKNN INT8) | 3588 CPU |
|---|---|---|---|---|
| #1 端到端 p95 | ≤ 1.5s | ~0.5s ✅ | **~0.4s ✅** | ❌ 短句 2-3s |
| #2 字错率 vs Mac | ≤ +15% | CER 0.0 ✅ | INT8 < 5% 损失 ✅ | CER 0.0 ✅ |
| #3 30min 稳定性 | 无 critical bug | 34d uptime ✅ | 20+ min daemon 容错 ✅（待长跑验证）| ❌ 假活 20h |

**判定**：3588 NPU 路径 + Jetson CUDA 路径**都过线**，下阶段以 3588 为主推。Jetson 留作"国际版"/"高端视觉版"。

### 当前 3588 上跑的东西（实测，不是猜）

**av_unified_mvp 自有模块**：
- `audio_processor` PID 974319（带 RKNN backend, daemon PID 974370）— **仅此一个模块**

**底层服务**（已在跑，av_unified_mvp 暂未消费）：
- `ollama serve` PID 856（qwen3.5:4b + qwen2.5-coder:1.5b 在本地）
- `mosquitto` PID 897（MQTT broker）
- `node-red` PID 894（厂商 demo 在用，av_unified_mvp 未导入 flows）

**厂商 creator_ai_demo 并行存在**（独立栈，不冲突）：
- `~/creator_ai_demo/pro_av_dashboard_NPU.py` + SenseVoice + start_demo_NPU.command
- `/app/modules/ObjectDetection-RKNN/objectdetection_fd_rknn_adapter.py` PID 2178

## 2. 阶段 3 — 3588 语义理解 + 物理执行（差异化护城河）

**目标**：客户说"打开二楼餐桌空调"全程在 3588 端完成（不依赖远端 Mac），跑通讯飞做不到的语义→执行闭环。

### 3.1 LLM 两级漏斗（半天）

复用厂商 `pro_av_dashboard_NPU.py` L122-139 策略，接入 av_unified_mvp catalog driven 架构：

- **Layer 1**：21+ 个正则关键词 0ms 命中（"打开/关闭/调亮/调暗/有点热/有点冷" 等），从 `config/device_catalog.json` 配置
- **Layer 2**：未命中走 ollama `qwen2.5-coder:1.5b` 兜底（已在 3588 本地）
- 配置：`config/system_config.yaml` 加 `llm.intent_strategy: funnel_two_layer`

**新发现（5/12 数据更新）**：3588 上 `qwen3.5:4b` CPU 单轮意图分类 7.5-12.8s/轮**不可用**（plan 原意）；但 NPU 路径已打通，**可探索 NPU 跑 Qwen 1.5B INT8 量化**（RKNN-toolkit2 转 RKLLM）。如成功 Layer 2 推理也走 NPU，端到端可压到 < 1s。这是阶段 3 加分项，不是 MVP。

### 3.2 Node-RED av/control 桥接（半天）

- 在 3588 Node-RED 导入 Mac 端 `node-red/flows.json` 60 节点
- `av/audio/command` → 关键词翻译 → `av/control`
- `av/control` → ASCII → TCP `192.168.5.20:8932` creator 中控（**待辽河现场设备清单确认**）
- 保留厂商 `/siri` HTTP in 节点向后兼容

### 3.3 husion 跨品牌桥接（按需）

辽河现场如有 husion HDC900，复用 Mac 端 `husion_distributed` 子进程（纯 TCP/JSON），网络 alias 改 3588 的 en0/eth0。

### 3.4 端到端演示（半天）

完整闭环：说话 → SenseVoice RKNN ASR → 两级漏斗意图 → MQTT → Node-RED → creator ASCII → 设备动作。录屏作辽河方案演示素材。

### 阶段 3 验收

- 5 句不同设备类型（空调/灯/窗帘/场景/查询）端到端 < 3s（含 LLM 兜底）
- 关键词命中率 > 80%
- 演示视频 5min 流畅

### 阶段 3 关键文件

- `modules/llm_engine/engine_arm.py`（新写，两级漏斗）
- `config/device_catalog.json`（加 `keyword_funnel` 字段）
- 3588 端 Node-RED `~/.node-red/flows.json`（导入我们 60 节点）

## 3. 阶段 4 — 辽河方案落底（0.5-1 天）

**目标**：给辽河两份文档 + 演示版本，方案实质落地。

### 4.1 技术架构文档（给辽河工程师）

含：六层架构图、3588 硬件配置、网络拓扑、MQTT topic schema、设备清单、部署步骤、运维手册（systemd 状态 / 日志位置 / 重启流程）

### 4.2 演示话术 / 业务价值文档（给辽河决策者）

含：vs 讯飞功能对比表（转写持平、语义+执行胜出）、价格优势（≤3K 硬件 vs 讯飞 50 万）、3 个典型场景脚本（会议室空调控制 / 灯光场景 / 窗帘自动化）

### 4.3 演示版本封装

3588 上 systemd `av_unified_mvp.service` 开机自启，浏览器访问 `http://192.168.5.6:5050` 直达；厂商 demo `:8501` 保留作 fallback。整机带 U 盘备份 + 一键恢复脚本。

### 阶段 4 验收

- 两份文档评审通过
- U 盘恢复脚本 + 整机带去辽河现场可在 30min 内部署完成

## 4. 二期：视觉 NPU（条件触发）

阶段 4 辽河首批演示通过后评估。

- `video_processor` 切 `rknn_toolkit_lite2` + `yolov5-small.rknn`（NPU 加速）
- C920 摄像头 `/dev/video20` → cv2 取流 → RKNN inference → MQTT `av/video/detect`
- L3 摄像头自动化（人来开灯 / 离开关灯）端到端

## 5. 总工期 + 节奏（5/12 调整后）

| 阶段 | 工时 | 累计 | 完成度 |
|---|---|---|---|
| 1. Mac 讯飞观感 baseline | 1.5d | 1.5d | ✅ |
| 2. 3588 转写复刻 + 退出判定 | 2d（含 NPU 路径打通 + 量产稳定性补足）| 3.5d | ✅ |
| 3. 3588 语义+执行差异化 | 1.5d | 5d | ⏳ 未启动 |
| 4. 辽河方案文档落底 | 1d | 6d | ⏳ 未启动 |
| 二期：视觉 NPU | 3-4d | (条件) | ⏳ |

**进入阶段 3 前的开放问题**：
1. 辽河现场设备清单 — creator 中控是否同款？husion 是否在场？
2. AGPL daemon 商业分发评估（happyme531 模型许可证；长期建议换 sherpa-onnx-rknn）
3. processor_arm.py 假活 bug 追根因（5/11 PID 60037 卡 do_select 20h，新代码未必复现但要观察）

## 6. 风险 / 退出条件（保持原 plan 设计）

三阈值任一**长期**触发 → 立即换硬件。短名单：

1. NVIDIA Jetson Orin Nano 16GB（约 4-5K，CUDA 生态成熟）— **已平行验证，过线**
2. 华为昇腾 Atlas 200I DK A2（信创合规，国产化加分）— 未试
3. Mac Mini M2 16GB（约 4K，避免移植成本但失去 ARM 国产化卖点）— 已用作 dev/demo

## 关联文档

- 完整原 sprint plan：`~/.claude/plans/3588-demo-1-50-mac-3588-3588-2-3588-ai-streamed-riddle.md`（240 行）
- 3588 NPU 部署 SOP：[`docs/deploy/3588-npu.md`](../deploy/3588-npu.md)
- 5/12 工作日志：[`../../NIGHT_REPORT_20260512.md`](../../NIGHT_REPORT_20260512.md)
- 整体开发蓝图：[`../../DEVELOPMENT_PLAN.md`](../../DEVELOPMENT_PLAN.md)
