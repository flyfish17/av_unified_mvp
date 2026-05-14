# CREATOR AI 视听理解平台 · 销售 FAQ（10 条客户最常问）

> 用途：销售揣兜里、客户突然深问时翻这份。每条都有"短答 + 长答 + 数据出处"三段式。
> 数据 cite 5/14 实测报告，不夸大。标 `[user 后补]` 的请商务侧补齐。

---

## Q1 · 国产化吗？涉密客户能用吗？

**短答**：可以。RK3588（瑞芯微 NPU）走国产化主推；客户非涉密场景也支持 Jetson 或 Mac mini 海外硬件。

**长答**：
- **涉密路径**：RK3588 工业版（¥TBD，参考 ¥1500-3000），ASR + LLM 全部走 NPU，模型本地、网络可断、SoC 国产。5/14 烧机 5.3 小时 0 crash 验证过。
- **更高级别涉密**：可上 RK3588 Plus 16 GB 或昇腾 Atlas 200I DK A2，待客户需求触发再选。
- **非涉密性能**：Jetson Orin Nano 8 GB（CUDA 67 TOPS）。
- **客户驻场 / 演示池**：Mac mini M4 Pro。
- **三套硬件跑同一份代码**，客户切硬件无感，差异只在 env / config。

**出处**：`DEVELOPMENT_PLAN.md` §1.5 硬件矩阵 + §1.6 产品化硬件路线图

---

## Q2 · 模型本地跑还是云端？数据出不出本地？

**短答**：**全本地**。ASR、语义 LLM、视觉 VLM 都在端侧 NPU/CUDA 跑，不依赖外网。

**长答**：
- **语音转写**：FunASR 2pass（Docker 本地）+ 降级 SenseVoiceSmall（本地）
- **语义意图**：3588 NPU 跑 Qwen2.5-1.5B INT8（1.75 GB RAM）/ 兜底 Mac mini Qwen3-4B
- **视觉理解**：Jetson Orin Nano 跑 qwen2.5vl:3b VLM
- **数据流**：全部走本地 MQTT 总线（mosquitto :1883），客户网络隔离即可。
- **持久化**：可选本地 SQLite，按客户需求接 BI / 报警系统也只走 MQTT 出口。

**出处**：`DEVELOPMENT_PLAN.md` §2 目标架构六层 + §进度日志 2026-05-13 NPU 入仓

---

## Q3 · 准确率到底多少？

**短答**：分模块给数据，不给"99% 识别率"这种空话。

**长答**（按模块）：
- **ASR（SenseVoice INT8 量化）**：CER vs Mac baseline 差异 < 5%（5/12 实测），日语 case NPU 反而比 CUDA 更准
- **语义意图（Qwen3-4B + catalog driven prompt）**：8 case 测试 7/8 正确（87.5%），唯一漏是地点幻觉（"三楼厨房"），已加白名单后置过滤兜底，**不会发出不存在的指令**
- **3588 NPU LLM（Qwen2.5-1.5B INT8）**：首 token 198-274 ms，decode 8.9 tok/s，27 prompt × 3 round 0 衰减
- **视觉 open-vocab（YOLOv8-World）**：
  - 未戴安全帽：conf 0.31-0.36（跨硬件稳定）
  - 跌倒/站立姿态：0.67-0.80
  - 聚集打斗：0.41-0.81（注意单人前倾会误报，需 conf ≥ 0.40）
- **诚实说明**：化工"火、烟、防爆服"专项类目当前 4 张测试图无样本，**待客户真实场景图补充验证**

**出处**：`OVERNIGHT_REPORT_YOLOV8_WORLD_20260514.md` §1-2 + `DEVELOPMENT_PLAN.md` §进度日志 2026-05-08 / 2026-05-12

---

## Q4 · 跟讯飞 / 海康 / 大华 是什么关系？是直接竞争吗？

**短答**：我们不和他们一对一拼，我们做"上面那一层中间件"。

**长答**：
- **讯飞**：他们做语音转写 + 语义。我们的差异 = **跨设备执行 + 端侧延迟 + 不依赖云**。讯飞同款方案客户报价 50 万+，我们硬件 ¥TBD（参考硬件 5000-15000）+ 实施服务。
- **海康 / 大华 / 宇视**：他们做摄像头 + 视频墙拼控。我们的差异 = **跨品牌融合 + open-vocab 零训练识别 + 与语音/智能家居打通**。海康只识别 COCO 类，我们的 YOLOv8-World 客户说一个词就能识。
- **华为 / 绿米 / 小米智能家居**：他们做家居生态。我们的差异 = **接进指挥中心 + 与视频墙/语音联动**。
- **核心定位**：我们做"客户旧设备之上的中间件"，不替换客户设备 —— 这是销售时反复强调的点。

**出处**：`DEVELOPMENT_PLAN.md` §1.5 产品形态 C + §1.6 第三步

---

## Q5 · 训练数据要客户提供吗？

**短答**：**不需要**（核心卖点）。客户描述一句话，系统就能识别。

**长答**：
- **视觉识别**：YOLOv8-World 是 open-vocab 模型 + CLIP 文本编码器，客户给 prompt（如 "person without hardhat / safety vest / fire"）系统直接识别，**0 标注、0 训练**。
- **语义意图**：catalog 驱动 prompt，客户给设备清单（76 指令格式），系统自动生成意图分类规则。
- **手势识别**（增强项）：MediaPipe GestureRecognizer 自带 7 类手势开箱即用。
- **边界**：如果客户要识别"我们厂特有的某型号阀门状态"这种极细类目，open-vocab 可能不够稳 → 此时再走传统 YOLO 训练路径，但这是 second-pass，不是第一刀。

**出处**：`OVERNIGHT_REPORT_YOLOV8_WORLD_20260514.md` §4 演示价值 + `OVERNIGHT_REPORT_GESTURE_RESEARCH_20260514.md`

---

## Q6 · 集成时间多久？多久能上线？

**短答**：基础部署 2 小时起步，跨品牌融合 1-2 周。

**长答**：
- **基础包（单 3588 / 单 Mac mini）**：`bash scripts/3588-demo-start.sh` 一键启动，60 s 就绪 → 2 小时部署 + 1 天调试基本场景
- **增强包（+ Jetson 视觉深思）**：再加 1-2 天调 Jetson 视觉 prompt + 联调 MQTT 总线
- **完整包（+ 跨品牌融合）**：husion / 海康 / 智能家居接入 1-2 周（取决于客户旧系统认证复杂度）
- **客户实际现场**：3 台机器（airblue / 8GB Air / 老 Mac mini）5/11-5/12 实测全部跑通，包括 RAM 自适应 light/medium 套餐切换。

**出处**：`OVERNIGHT_REPORT_DEMO_PACKAGE_20260514.md` + `DEVELOPMENT_PLAN.md` §进度日志 2026-05-11–12

---

## Q7 · 一台机器跑得动多少路视频？性能上限在哪？

**短答**：3588 实测 4 路 720p YOLO 主路径推理稳定；5 路接近上限。

**长答**：
- **3588 CPU**：4 路 720p YOLOv8n 推理 CPU 占用约 400%（5 核 60% 利用），5 路接近上限
- **3588 NPU**：当前 NPU 只跑 ASR + LLM，未跑 YOLO；YOLO 主路径走 CPU
- **YOLOv8-World open-vocab**：3588 上 1.6-1.8 s/帧 → **必须事件触发（订 av/video/key_event），不每帧推理**
- **Jetson Orin Nano**：视觉深思 + VLM 走 CUDA，可与 3588 并行
- **客户多路场景**（10 路+）：建议算丰 SE9 (BM1684X) 32 TOPS 边缘盒，¥TBD（参考 5000-8000）
- **极限性能**：Jetson AGX Orin 32-64 GB，¥TBD（参考 12000-25000），可跑 70B 模型

**出处**：`DEVELOPMENT_PLAN.md` §1.5 硬件矩阵 + `OVERNIGHT_REPORT_YOLOV8_WORLD_20260514.md` §2.2

---

## Q8 · 售后 / SLA 怎么算？

**短答**：[user 后补 —— 商务侧定]

**长答框架**（待 user 填）：
- 远程监控覆盖范围（modules system_info / network_info 已是基础）
- 故障响应时间分级（4h / 24h / 7×24）
- 升级包频率 + 内容（模型更新 / 模块更新 / 安全补丁）
- 现场支持次数 / 上门 SLA
- 年度运维费率 [user 后补]
- 客户技术培训 [user 后补 频次 / 形式]

**技术侧能提供的可观测性**（销售可讲）：
- `modules/system_info` + `modules/network_info` 实时监控
- MQTT LWT（last will & testament）模块掉线即时告警
- supervisor 30 s 自动重拉（5/11-12 实测过 husion 不通仍重拉，是设计不是 bug）

**出处**：`DEVELOPMENT_PLAN.md` §1.5 产品形态 C 当前完成度

---

## Q9 · 数据存哪？万一被审计、被检查怎么办？

**短答**：全部本地，客户网络隔离，可审计可追溯。

**长答**：
- **MQTT 总线**：本地 mosquitto :1883，所有模块消息可全量录制
- **持久化**：可选 SQLite 本地存（按客户合规要求开关）
- **音视频**：转写文本可保存 / 不保存（客户选），原始音视频默认不保存
- **审计 trail**：dashboard 控制面板可看到每条指令的"语音 → 转写 → 意图 → 指令 → 设备响应"完整链路
- **网络隔离**：客户可把整套系统部署在物理隔离的内网，不需要任何外网连接（这是 3588 涉密路径的核心卖点）
- **GDPR / 等保 / 涉密合规**：技术上具备隔离能力，具体合规认证 [user 后补]

**出处**：`DEVELOPMENT_PLAN.md` §2 目标架构 + §4 MQTT topic 协议

---

## Q10 · 万一硬件坏了怎么换？硬件升级怎么办？

**短答**：模块解耦 + MQTT 总线，新硬件 rsync 仓库 + 改 config，约 30 分钟切换。

**长答**：
- **模块独立**：9 个模块都能 `python -m modules.<name>` 独立启动，硬件层透明
- **配置驱动**：`config/system_config.yaml` 决定模型路径、视频源、性能 profile —— 改 yaml 不改代码
- **5/11-12 实测**：3 台 Mac（airblue / 8GB Air / 老 Mac mini）部署，主要工作 = `rsync ~/.ollama/models/ ~/av_unified_mvp/`，约 30 min/台
- **start.command RAM 自适应**：<6 GB 拒绝启动 / <10 GB 自动改 config（profile=light + audio=local_offline + LLM=qwen3.5:2b-q4_K_M），改前自动备份 yaml
- **升级路径**：
  - 涉密客户：3588 工业版 → 3588 Plus 16 GB → 昇腾 Atlas 200I DK A2
  - 非涉密客户：Jetson Orin Nano → Jetson Orin NX 16 GB → Jetson AGX Orin 32-64 GB
  - 客户驻场：Mac mini → 升级 RAM / CPU 版本
- **硬件兜底原则**：客户场景定，不预设。如果某个硬件路径走不通，**换硬件不换代码**。

**出处**：`DEVELOPMENT_PLAN.md` §进度日志 2026-05-11–12 + §1.6 跨步演进准则

---

## 加分项 · 如果客户问起这些（不在 10 条主问之内，但常会冒出）

### Q11 · 你们价格能再降吗？
- 单 3588 国产批量价比方案：算能 BM1688 16 TOPS（¥TBD，参考 1500-2500），边缘盒子批量部署
- 但**别先降硬件**，先看场景能不能砍模块（如不需要视频就拿基础包）

### Q12 · 模型自己能不能换？
- 能。`config/system_config.yaml` 改 `model_fast / model_smart` 字段即可
- 5/8 已切过 qwen3.5:9b → qwen3.5:4b，省 4.2 GB RAM；5/13 NPU 切 Qwen2.5-1.5B INT8

### Q13 · 演示翻车了怎么办？
- 4.5 s 离线兜底已经写进 dashboard 浮球，**LLM 慢自动直发预设指令**
- 5 颗预设句式覆盖 5 个 location × 3 设备类（空调/灯/窗帘）
- 现场只要 mosquitto 活着，控制就不会断

### Q14 · 你们用什么开源？许可证有没有问题？
- FunASR / SenseVoice：Apache-2.0
- YOLOv8 / ultralytics：AGPL-3.0（注意：商用客户场景需走 ultralytics 商业许可或换 yolov8n.pt 自有改造版）
- RKNN / 瑞芯微：商业可用
- happyme531 SenseVoiceSmall-RKNN2：AGPL-3.0，**已隔离不入仓**
- Ollama / Qwen：Apache-2.0 / Qwen LICENSE
- **建议商务侧关注 ultralytics AGPL 商用许可** —— 这条值得明确

---

## 一行总结

**"我们不卖硬件、不卖模型 —— 卖的是把客户旧设备和新 AI 能力拉到一根总线上的中间件 + 服务。"**
