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
