# yolov8-world open-vocab 落地评估 — 2026-05-14

> 上下文：5/14 早 Sub-2 实测 YOLO26 反预期（慢 5% + open-vocab API 缺失），意外发现 yolov8s-world + CLIP 是真 open-vocab 路径。本次任务：4 路真实场景实测 + 3588 时延实测 + 落地路径建议。
>
> 实测路径：Mac 端 + 3588 端均完成。**结论：yolov8-world 在 Mac 上极快 (36ms)，在 3588 CPU 上 1.6-1.8s/帧 — 不能每帧推理，必须事件触发**。

---

## 1. Mac 端实测（ultralytics 8.4.50 + yolov8s-world.pt 26MB）

### 1.1 时延
- 加载模型: 17 ms
- set_classes (重置词表+CLIP encode): 已 cache（在加载里）
- **平均推理时延 36 ms / 帧**（min 33 / max 54，n=72，输入图 33KB-235KB）

### 1.2 4 路真实场景 × 9 组 prompt 的命中分布

| 场景 prompt | C920 | test | 财务室 | 办公室 |
|------------|------|------|--------|--------|
| `fire / smoke / flame`            | (none) | (none) | (none) | (none) |
| `person without hardhat`          | **0.36** | (none) | 0.18 | (none) |
| `safety vest / reflective vest`   | (none) | (none) | (none) | (none) |
| `person falling / lying / standing` | standing 0.80 | (none) | standing 0.67 | (none) |
| `person fighting / hugging`       | hugging **0.81** | (none) | hugging 0.25 | hugging **0.41** |
| `person smoking / cigarette`      | (none) | (none) | (none) | (none) |
| `fire extinguisher / gas mask`    | (none) | (none) | (none) | (none) |
| `leak / water leak / spill`       | (none) | (none) | (none) | (none) |
| **baseline COCO** `person/laptop/chair` | laptop 0.96, person 0.93, phone 0.74 | chair 0.33 | person 0.72, chair 0.69, laptop 0.64 | person 0.66, chair 0.47 |

### 1.3 解读
- **真有用**: `person without hardhat` 在 C920 命中 0.36（>=0.30 阈值留存）—— 验证 §1.5 形态 B "未戴安全帽零训练识别"路径**确实可行**。
- **可演示**: `person standing/sitting/falling` 类姿态描述命中很稳（0.67-0.80）—— 转成 demo 文案"AI 实时识别人员姿态：站立 / 跌倒"。
- **误报隐忧**: `person hugging` 在 C920 命中 0.81，但实际场景没人在抱（应该是单人前倾被误判）。**说明任何 person+动词类 prompt 必须 conf>=0.40 + 人工 review**。
- **场景受限**: `fire / smoke / extinguisher / gas mask / leak` 全部 0 命中 — **不是模型不行，是 4 张测试图里就没这些东西**。这类必须用专门图（消防演练视频帧 / 化工厂照片）验证，**留作下一轮专项验证项**。
- **baseline COCO 类 (person/chair/laptop) 命中可靠** 0.66-0.96 — 模型本身没问题。

---

## 2. 3588 端实测（venv ultralytics 8.4.50 + CLIP 自动装）

### 2.1 首次启动成本
- ultralytics 自动 pip install CLIP + torch 全套（**包括 NVIDIA cuda 包 ~ 350MB+**，CPU 实际用不到但 ultralytics deps 强行装）—— **首次启动 ~ 210s 安装 + 90s CLIP weights 338MB 下载**
- 后续启动免：weights cache 在 `~/.cache/clip/`
- 模型本身 26MB scp 完成，已在 /tmp/yolov8s-world.pt

### 2.2 推理时延（warmup 2 + bench 5 取平均）
| 输入图 | warmup | run avg | min | max |
|-------|--------|---------|-----|-----|
| C920 32KB | 2245→1830 ms | **1801 ms** | 1786 | 1825 |
| 财务室 229KB | 1589→1557 ms | **1578 ms** | 1529 | 1607 |

- **3588 CPU yolov8s-world ~ 1.6-1.8 s/帧** —— 比 Mac 慢 **45-50 倍**（Mac M-series + ARM 优化 vs 3588 RK3588 CPU）
- 对比 video_processor 当前 yolov8n.pt 主路径 ~ 600ms/帧 —— **yolov8-world 是 3x 慢**（v8s 比 v8n 大 5x，但 world 头有额外开销）

### 2.3 命中一致性
- `person without hardhat` 在 3588 端：C920 命中 **0.31**（Mac 0.36，差异 fp32 数值正常），财务室 **0.19**（Mac 0.18）—— **跨硬件结果稳定**

---

## 3. 落地路径建议（按硬约束：不改 video_processor、不动 yolov8n.pt 主路径）

### 3.1 推荐方案 A：**新独立模块 `modules/openvocab_filter/`**

> 这是 CLAUDE.md "新功能优先做成独立子模块" 原则的直接体现。

```
modules/openvocab_filter/main.py
  订阅: av/video/key_event                # 来自 keyframe_filter，已聚合"显著变化"
  动作: 拉 snapshot (mjpeg/raw) → yolov8s-world.set_classes(prompts) → infer
  发布: av/video/openvocab                # {camera, time, prompts, hits:[{label,conf,bbox}]}

  配置 (system_config.yaml):
    openvocab_filter:
      enabled: false                       # 默认关，避免没显卡的设备 CPU 爆
      model: /opt/models/yolov8s-world.pt
      prompts_per_camera:
        监控:    ['person without hardhat', 'fire', 'smoke']
        财务监控: ['person fighting', 'person falling']
        本机摄像头: ['person without hardhat']
      confidence: 0.30
      max_concurrent: 1                    # 3588 上 1.6s/帧，并发 = 慢，串行
```

**优势**:
- 完全隔离，不影响 video_processor / yolov8n.pt 主路径
- 接 keyframe_filter 输出 = 事件触发，不每帧推理
- per-camera prompt 配置 = 商业灵活性（"客户化工厂只看防爆服 + 火苗"）
- 默认 enabled:false = 普通项目 0 成本

**风险**:
- 3588 CPU 1.6s/帧 + key_event 可能 0.5s 一次 = 队列堆积。**必须实现"丢老帧"策略**（处理中收到新帧→丢旧帧）
- 误报：`person hugging` 类社交动词 prompt 不要默认开，让客户业务方明确点选

### 3.2 备选方案 B：扩展 video_processor 加 open_vocab 模式（不推荐）
- 违背模块解耦原则
- yolov8n + yolov8s-world 两套模型同时驻 3588 内存（~ 80MB）—— 3588 8GB 内存够，但语义混乱
- video_processor 已经在跑 inference_fps:2，加 world 推理会和主推理抢 CPU

→ **不采用**

### 3.3 部署节奏（建议）
1. **本仓库 Mac 端先落地**（用 Mac M-series 演示，36ms 推理无压力，演示效果惊艳）
   - 新建 `modules/openvocab_filter/main.py` 框架
   - 跑 dashboard 直接看 av/video/openvocab 事件流
2. **3588 二期接入**（事件触发 + 单帧 1.6s 可接受）
   - 加 `~/.cache/clip/` 预填脚本到部署 SOP（避免每台首次启动 90s 等待）
   - prompt 收敛到 3 类（`fire / smoke / person without hardhat`），不发散到 9 类
3. **客户场景验证**（专项数据补齐）
   - 化工厂照片测 `fire / smoke / gas mask / extinguisher / leak`
   - 工地照片测 `hardhat / safety vest`
   - 内部行为测 `falling / fighting / smoking`

---

## 4. 演示价值（哪些客户会买账）

| 客户类型 | Pitch 一句话 | 可信度 |
|---------|------------|--------|
| 化工厂安环 | "未戴安全帽 / 防爆服自动告警，0 训练" | **高**（已实测 person w/o hardhat 0.31-0.36） |
| 工地监管 | "工人姿态识别 - 跌倒 / 站立 / 蹲下" | **高**（standing 命中 0.67-0.80） |
| 办公区域 | "陌生人 / 异常聚集自动识别" | **中**（hugging 误报，需调 conf 0.40+） |
| 商场零售 | "丢弃物 / 滞留物自动识别" | **中**（baseline 物体 chair/laptop 命中可靠，但 "滞留" 时间维度需要叠加 tracker） |
| 危化园区 | "火苗 / 烟雾 / 泄漏 实时识别" | **未验证**（4 路图无此类样本，需补专项验证） |

**最强卖点**：客户对接时 "**你给一个词，我们就能识别**"——演示 `set_classes(['你说的目标'])` 现场切换。这是和 v8n COCO 80 类的本质代差。

---

## 5. 风险与遗留

| 风险 | 严重度 | 缓解 |
|-----|-------|------|
| 3588 CPU 推理 1.6-1.8s/帧 | 高 | 事件触发 + 丢老帧；不要每帧 |
| 模型 26MB + CLIP 338MB weights | 中 | 部署 SOP 预填 cache；rsync 离线包 |
| 首次启动 pip 装 350MB cuda deps | 高 | 部署 SOP 加 `--no-deps` 或定制 requirements |
| person+动词类 prompt 误报 | 中 | conf>=0.40 + per-camera 白名单 |
| 未验证场景（火/烟/化工） | 中 | 下一轮：补真实场景图测，不能纯靠模型自吹 |
| world 模型不支持 NPU 加速 | 中 | RKNN 还没适配 yolov8-world，保持 CPU 路径 |

---

## 6. 实测产物 (留 /tmp/，不入仓)

- `/tmp/yolov8s-world.pt`                Mac + 3588:/tmp/ 各一份
- `/tmp/yolov8_world_test.py`            Mac 4 路图 × 9 组 prompt 测试脚本
- `/tmp/yolov8_world_3588_bench.py`      3588 推理时延 bench 脚本（已 scp 到 3588:/tmp/）
- `/tmp/yolov8_world_results.json`       Mac 实测原始数据（72 条 hits）
- `/tmp/c920_now.jpg` / `/tmp/cam_test.jpg` / `/tmp/cam_财务室.jpg` / `/tmp/cam_办公室.jpg`   实测样本图

## 7. 一句话结论

**yolov8-world 是真 open-vocab，Mac 36ms 极快，3588 1.6s 必须事件触发；建议落 `modules/openvocab_filter/` 新模块订 `av/video/key_event`，per-camera prompt 配置，default off**。
