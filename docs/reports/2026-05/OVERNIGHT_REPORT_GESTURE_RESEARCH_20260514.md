# 手势识别 — 化工厂危化场景演示亮点 调研报告

**日期**：2026-05-14
**调研人**：Claude (Opus 4.7)
**项目**：av_unified_mvp · 辽河化工演示
**结论先行**：**推荐 MediaPipe GestureRecognizer · 工作量 ~6-10 小时 · 演示亮点值得做（建议作为"锦上添花"演示亮点，不阻塞主线）**

---

## Step 1 · 主流方案对比（2026 视角）

| 候选 | 模型大小 | 推理速度（ARM CPU） | 接入难度 | 准确率 / 默认手势 | 评价 |
|---|---|---|---|---|---|
| **MediaPipe GestureRecognizer**（首选） | ~8 MB task bundle（4 个 TFLite 子模型：palm detect + landmark + embedding + classifier） | RPi4 ~8–14 FPS（单手 CPU），RPi5 / 3588 CPU 预估 15–25 FPS | **★★ 低**：`pip install mediapipe`，10 行 Python 跑通 | 默认 7 类：Closed_Fist / Open_Palm / Pointing_Up / Thumb_Down / Thumb_Up / Victory / ILoveYou + Unknown；调用 95%+ 准确率 | **演示首选**。开箱即用，7 类够撑销售话术 |
| MediaPipe Hands（仅 landmark） | ~6 MB | RPi4 ~14 FPS | ★★ 低 | 只给 21 个 3D 关键点，**没有分类**，需自己写规则或训分类器 | 不建议（多此一举，GestureRecognizer 已经封装好） |
| Ultralytics YOLO11 Pose | ~10 MB (n)–50 MB (m) | RKNN 后 3588 NPU 可 30+ FPS；CPU 慢 | ★★★ 中：可走 RKNN；但需要 hand-pose 数据训练 | 主流是 person pose（17 点），hand pose 需自定义训练，**没有现成 gesture 标签** | 不适合演示（手势分类要自己来） |
| OpenPose | 200+ MB（VGG backbone） | 慢，已被淘汰 | ★★★★ 高 | 老牌但陈旧 | **淘汰**，2026 没人用 |
| HaGRID 数据集 + 自训练 | 视模型 | 视模型 | ★★★★★ 高（要标注、训练、调参） | 18 类工业手势 | 适合做产品级；演示阶段成本太高 |
| Qwen3-VL 看图描述手势 | 4B/8B = 4–16 GB | 3588 NPU 远跑不动 8B；只能走云端 API | ★★ 接入低，但**延迟 1–3 秒** | 通用 VLM 看得懂，但语义不稳定 | **不适合实时演示**（卡顿，且烧 token） |
| **混合**：MediaPipe + Qwen3-VL 二级判定 | — | — | ★★★ | — | 后期产品级可考虑：MediaPipe 做帧级快筛，Qwen3-VL 做语义增强 |

**3588 NPU 兼容性**：MediaPipe 可走两条路径——
1. **CPU（Cortex-A76 ×4 + A55 ×4）**：直接 pip 装，无须移植，预估 15–25 FPS 单手，**演示足够**。
2. **NPU**：需把 4 个 TFLite 拆出来用 RKNN Toolkit 2 逐个转 `.rknn`，社区已有现成方案（`Etafy-Dol/mediapipe-rockchip` 已支持 RK3588）。**演示阶段不必走这条**，留作产品化阶段。

---

## Step 2 · 化工 / 危化场景需求贴合度（2026）

### 真实痛点（搜索佐证）

1. **戴手套操作触屏**：化工操作员常戴丁腈/耐酸碱手套，电容屏识别率差。MediaPipe 看的是手的轮廓与骨架，**戴手套照样能识别**（这是个真实加分点）。
2. **防爆区禁止靠近触屏**：Class I Div 1 / Zone 1 区域，HMI 必须 explosion-proof 外壳或正压吹扫。**非接触手势控制 = 让操作员站在安全区操控大屏**，是合规上的实际需求（不是 PPT 噱头）。
3. **指挥中心大屏 3–5m 距离指挥**：领导/调度员从远端比划，控制大屏切换画面/确认报警 → 比走过去点鼠标更"有派头"。
4. **健康卫生 / 防交叉污染**：后疫情时代继续是软性需求。
5. **DCS 报警与视频联动延迟 >90s 的痛点**：手势识别 → MQTT → 联动确认，可在演示中表演"举手 V 字 → 报警确认"的 demo。

### 同行业现状（差异化机会）

- 海康/大华/宇视的指挥中心方案**主流仍是触屏 + 鼠标 + 视频墙拼控**，没看到手势控制成熟产品。
- 工业 HMI 领域（Pepperl-Fuchs / R.Stahl / Advantech）**正在探索手势/语音/AR**，但还没有标准化产品。
- **窗口期**：手势识别在化工指挥中心是"前沿但不超前"，演示能立住"我们做的是未来 2–3 年的方案"的姿态。

---

## Step 3 · 工作量估算（接入 av_unified_mvp）

参照 `modules/video_processor/`（408 + 366 行）和 `modules/scene_analyzer/`（393 行）的现有模板复刻。

| 任务 | 工作量 | 备注 |
|---|---|---|
| `pip install mediapipe` + 下载 `gesture_recognizer.task` 模型 | 0.2h | macOS arm64 / Linux arm64 都有官方 wheel（0.10.35 已支持 macOS 11+ ARM64） |
| 新模块 `modules/gesture_recognizer/main.py`（订阅视频帧 / 发布手势事件） | 2–3h | 复刻 `scene_analyzer/main.py` 骨架：MQTT 订 `av/video/raw_frame`（或单独拉 MJPEG/RTSP），发 `av/gesture/event` | 
| 手势 → 控制命令映射（如 Open_Palm = 切换画面 / Victory = 确认报警 / Closed_Fist = 静音） | 1h | 在 dashboard 或 `control_dispatcher` 加 mapping |
| Dashboard 显示当前手势（"现在识别到：✌️ Victory"） | 1–2h | 加一个 WebSocket / 静态卡片 |
| 演示脚本 + 联调（演示走位 / 灯光 / 摄像头角度） | 2h | C920 USB cam + 3588 跑 |
| 文档 / 自检 / 异常路径（无手 / 多手 / 弱光） | 1h | 加一个 `if no hand detected: idle` |
| **合计** | **~7–9 小时** | 一个晚上 + 半天能跑通 demo |

**关键依赖与风险**：
- MediaPipe **无 GPU 依赖**，pure CPU 就能跑，部署零阻力。
- macOS arm64 已有官方 wheel（0.10.35 / 2026-04-27）；Linux arm64 同样有。
- **风险**：3588 上 Python wheel 是否带 XNNPACK 加速取决于发布版本，最坏情况退化到 ~10 FPS，对演示仍可接受。
- **不踩坑提醒**：MQTT 走 raw frame 体积大；建议本模块独立拉 MJPEG / 直接 OpenCV 抓 C920，跟 video_processor 解耦并行。

---

## Step 4 · 演示亮点价值评估

| 维度 | 评分 | 说明 |
|---|---|---|
| 客户体感"高级感" | ★★★★★ | 客户 / 评委亲自上场挥手互动，比看 PPT 强 10 倍 |
| 差异化（行业内罕见） | ★★★★ | 海康/大华没做；化工 HMI 厂在探索但无成品 |
| 实用性（真痛点 vs 噱头） | ★★★ | 戴手套 + 防爆区距离操作是真痛点，但客户买单更多是"未来感"而非"硬刚需" |
| 工作量 ROI | ★★★★★ | <10 小时投入换一个"全场最炸"演示点，超划算 |
| 演示鲁棒性 | ★★★★ | MediaPipe 7 类手势在静态背景下识别稳定；建议演示时背景纯净 + 光源充足 |
| 与现有架构耦合度 | ★★★★★ | 完全独立子模块，订视频帧、发 MQTT 事件，零侵入 |

**建议销售话术**（1–2 句）：
> "在化工指挥中心，操作员戴着耐酸碱手套、站在防爆区外 3 米——传统触屏失灵，鼠标够不着。我们的 AV 平台让一个手势就能确认报警、切换大屏、调取现场画面，这是为危化品场景量身定做的非接触式指挥。"

或更短的演示开场白：
> "戴手套照样操作大屏，3 米外伸手就能切画面——这是为化工指挥中心做的非接触控制。"

---

## Step 5 · 结论与下一步建议

### 推荐方案
- **首选**：MediaPipe GestureRecognizer（CPU 跑，task bundle 现成 7 类手势）
- **备选**：MediaPipe Hands + 自定义规则（如果需要演示自定义手势，比如"OK 圈"= 确认）
- **后期产品化**：HaGRID 数据集自训练 + RKNN 转换走 3588 NPU（不是现在的事）
- **不推荐**：Qwen3-VL（实时性不够），YOLO Pose（手势分类缺失），OpenPose（已淘汰）

### 化工场景贴合度
**中高**：戴手套操作 + 防爆区距离指挥 + 健康卫生 = 三条真实痛点；行业内无成熟竞品，差异化窗口期。

### 工作量
**~7–9 小时**（一个晚上跑通 PoC，半天联调演示）。零额外硬件，零架构改动，完全独立子模块。

### 演示亮点价值
**值得做**。客户体感和销售话术杠杆都很强；ROI 极高（<10h 投入 vs "全场最炸"演示点）。

### 下一步建议
1. **暂缓不做**：本轮 3588 sprint 主线是 LLM/NPU，不要被手势分心。
2. **下一个迭代窗口接入**：等 3588 LLM POC 收口后，单独开 0.5–1 天窗口做 gesture POC。
3. **演示编排**：销售演示时把 gesture demo 放在"AI 多模态融合"章节，配合 VLM 场景识别一起出场。
4. **不要在 CLAUDE.md 推荐先做**：保留 MQTT 解耦原则，写新模块 `modules/gesture_recognizer/`，不动既有代码。

---

## 关键参考链接

- [MediaPipe Gesture Recognizer Python 文档](https://ai.google.dev/edge/mediapipe/solutions/vision/gesture_recognizer/python)
- [mediapipe PyPI（0.10.35，2026-04-27，已支持 macOS arm64 / Windows arm64）](https://pypi.org/project/mediapipe/)
- [MediaPipe → RKNN 部署指南（ZedIoT，RK3566/3588 通用）](https://zediot.com/blog/mediapipe-gesture-recognition-rknn-rk3566/)
- [Etafy-Dol/mediapipe-rockchip（RK3588 移植）](https://github.com/Etafy-Dol/mediapipe-rockchip)
- [Raspberry Pi 5 MediaPipe 实测](https://medium.com/@clarencechng/practical-computer-vision-using-mediapipe-on-raspberry-pi-5-43ad6277a825)
- [Improving Gesture Recognition with MediaPipe and YOLO-Pose（2025 ISPRS）](https://isprs-archives.copernicus.org/articles/XLVIII-2-W9-2025/13/2025/isprs-archives-XLVIII-2-W9-2025-13-2025.pdf)
- [工业 HMI 防爆区现状（Control Design）](https://www.controldesign.com/displays/hmi/article/11315844/options-for-hmis-in-explosive-atmospheres)
