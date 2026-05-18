# YOLO26n 替代 YOLOv8n — 实测报告

**日期**：2026-05-14
**测试人**：Claude（自动）
**目标**：验证 docs/roadmap/ai-landscape-20260514.md §A3/D2a 中 "YOLO26 NMS-free + CPU 43% 提速 + open-vocab" 在我们当前栈上是否成立。

---

## 1. 环境与 ultralytics 状态

| 平台 | ultralytics 之前 | 升级后 | YOLO26n 加载 |
|---|---|---|---|
| Mac (Apple Silicon, Python 3.14) | 8.4.35（pinned in requirements.txt） | **8.4.50** | OK（自动从 ultralytics/assets v8.4.0 release 拉 5.3 MB） |
| 3588 (firefly@192.168.5.6, venv) | 8.4.49 | **8.4.50** | OK（scp 上来后） |

**关键观察**：
- ultralytics `8.4.50` **已包含 yolo26n.pt 权重**——`YOLO("yolo26n.pt")` 自动从 `github.com/ultralytics/assets/releases/download/v8.4.0/yolo26n.pt` 下载成功。
- 但加载后 `m.task == 'detect'`、`type(m) == YOLO`、`len(m.names) == 80`（仍是 COCO 80 类，不是新数据集）。所以 "YOLO26" 在 ultralytics 仓库里的发布方式更像 **"YOLOv8 的一个新 weight + 新 head"** 而不是独立的 API 大版本。

---

## 2. CPU 推理速度对比

测试图：`/tmp/bus.jpg`（810×1080，6 人/车/stop sign 标准 ultralytics 测试图）

### Mac (Apple Silicon, CPU 推理)

| 模型 | avg | min | max | boxes |
|---|---|---|---|---|
| YOLOv8n | 22.7 ms | 22.2 | 23.2 | 6 (bus + 4 person + stop sign) |
| YOLO26n | **23.8 ms** | 23.3 | 24.5 | 5 (bus + 4 person) |
| **diff** | **-5.0% (YOLO26 慢)** | — | — | — |

### 3588 (ARM Cortex-A76+A55, CPU 推理)

| 模型 | avg | min | max | boxes |
|---|---|---|---|---|
| YOLOv8n | 633 ms | 602 | 662 | 6 |
| YOLO26n | **664 ms** | 640 | 686 | 5 |
| **diff** | **-4.9% (YOLO26 慢)** | — | — | — |

**结论**：在 ultralytics 8.4.50 的 PyTorch CPU 路径上，YOLO26n **没有看到 43% 提速**，反而比 YOLOv8n 慢 ~5%。
**两点猜测**（未深查）：
1. roadmap 引用的 "43% 提速" 应该是 **NMS-free + 算子合并后端到端 ONNX/TensorRT 路径**，不是 PyTorch eager。我们这边都跑的 .pt，没走 export 优化。
2. 3588 上要拿到提速可能得 export 成 RKNN/ONNX 走 NPU，但 RKNN 端的算子支持矩阵又是另一个工程。

YOLO26n 漏检了 stop sign，但 bus/person 完全对齐，conf 没看出系统性差异。

---

## 3. Open-vocab 实测

### 3.1 YOLO26n 自带 open-vocab？— **不支持**

```python
m = YOLO("yolo26n.pt")
m.set_classes(['fire', 'smoke', 'person falling', ...])
# AttributeError: 'DetectionModel' object has no attribute 'set_classes'
```

YOLO26n 走的是 `DetectionModel` 类，**没有 `set_classes`**。roadmap 里说 "open-vocab" 在 ultralytics 8.4.50 这一版的 yolo26n.pt 上**还没接通**。

### 3.2 试 YOLO26 任务变体 — 全部 404

```
yolo26-world.pt: FileNotFoundError
yolo26-seg.pt:   FileNotFoundError
yolo26-cls.pt:   FileNotFoundError
yolo26-pose.pt:  FileNotFoundError
yolo26-obb.pt:   FileNotFoundError
```

ultralytics 8.4.50 的 assets release 里**只有 `yolo26n.pt`**（基础 detect 一个 weight），没发布 -world/-seg/-cls/-pose/-obb 系列。所以"五任务统一 + open-vocab"宣传暂时只在 paper/blog 层面，**仓库实现还在追**。

### 3.3 验证 open-vocab 思路 — 用 yolov8s-world 替代

为了证明"prompt 自定义类别"的产品价值能不能落，用同样的 prompts + ultralytics 已发布的 `yolov8s-world.pt`（26 MB + 自动装 CLIP 一次性 ~340 MB）跑 bus.jpg：

```
prompts = ['fire', 'smoke', 'person falling', 'person without hardhat', 'red helmet']

open-vocab boxes = 4
  -> person without hardhat (conf 0.48)
  -> person without hardhat (conf 0.43)
  -> person without hardhat (conf 0.39)
  -> person falling          (conf 0.27)
```

**5 个 prompt 中 2 个真实命中**（"person without hardhat" × 3、"person falling" × 1，对应公交站台 4 个站立者）：
- "fire" / "smoke" → 图里没有，未误报，正确。
- "person without hardhat" → 4 个人都没戴硬帽，但模型只画了 3 个 box，置信度都不高（0.39–0.48）。
- "person falling" → 1 个人姿态被错误识别为"摔倒"（conf 0.27，**低置信度误报**——人其实是站着的，但仿佛在伸手）。
- "red helmet" → 未触发。

**结论**：open-vocab 能用，**但置信度阈值要严**（≥0.5 才稳），prompts 表达精度对结果影响极大（"person without hardhat" 比 "no hardhat" 命中更好）。这条路径的价值在 D2a 描述的产品方向是真的，**只是要走 yolo*-world 这个分支，不是 yolo26n**。

---

## 4. 升级 video_processor 的 diff 建议

**当前**（`config/system_config.yaml:75`）：
```yaml
yolo:
  model: yolov8n.pt
```

### 4.1 仅换 weight（最低成本试验，1 行）

```yaml
# config/system_config.yaml
yolo:
  model: yolo26n.pt   # 替换。代码层 modules/video_processor/processor.py 的 YOLO(...) 不动
```

**收益**：零，**反而 CPU 慢 5%**。不建议立即合并。如果想留个开关、让以后跑 ONNX/TensorRT export 路径时一键切，可以做成 `model: yolov8n.pt` 默认 + `model_alt: yolo26n.pt` 注释行，**待 ultralytics 出 yolo26 ONNX/NPU 工程化路径后再试**。

### 4.2 走 open-vocab（产品逻辑级改动，**不建议本周做**）

如果真要把 "业主自定义识别目标" 做成产品功能，至少要：

1. `config/system_config.yaml` 加 `yolo.classes_prompts: ['fire', 'smoke', ...]` 字段；
2. `modules/video_processor/processor.py` 在 `YOLO(...)` 后调 `m.set_classes(prompts)`；
3. 模型从 `yolov8n.pt`（6.5 MB）换 `yolov8s-world.pt`（26 MB + CLIP 340 MB 首次拉取）——**对 3588 边缘部署是 5x 重量级跃迁**，要重新评估 4 路 FPS；
4. 把 `target_classes: [0, 67, 73]` 这种 COCO id 映射逻辑改成 prompt 字符串映射。

这是 D2a 描述的产品方向，**值得做，但不是 1 行 diff 能完成的——是一个独立 sprint**。

---

## 5. 风险评估 / breaking change

| 维度 | 风险 |
|---|---|
| API 兼容 | YOLO26n 的 `m(img)`、`m.names`、`r[0].boxes` 全部和 YOLOv8n 一致——**无 breaking change**。可以无脑换 weight。 |
| 类别空间 | YOLO26n 仍是 COCO 80 类，**和 YOLOv8n 一致**——`target_classes: [0, 67, 73]`（person/cell phone/laptop）继续有效。 |
| 速度 | PyTorch CPU 路径上 -5%（不达预期）。如果以后走 ONNX/RKNN export，需要重新 benchmark。 |
| 检测精度 | 单图测试 6 → 5 boxes，YOLO26n 漏掉 stop sign。**需要在我们的真实摄像头流上跑 1 天，不能只看 1 张图下判断**。 |
| Open-vocab | ultralytics 8.4.50 的 yolo26n.pt **不支持 set_classes**，roadmap 提到的能力暂时只能用 yolov8s-world 实现。 |
| 模型权重源 | ultralytics 自己的 assets release（GitHub）。**国内拉取偶尔慢**（5 MB 实测 9.4 s），首次部署需要预下载。 |

---

## 6. 给 user 的一句话结论

**YOLO26n 在 ultralytics 8.4.50 上"能加载、能跑、API 兼容"，但：**
- **没看到 CPU 提速**（Mac -5%、3588 -5%，PyTorch eager 路径上比 YOLOv8n 慢）；
- **不支持 open-vocab**（`set_classes` 缺失，仍是 COCO 80 类闭集）；
- **D2a 产品方向（业主自定义识别）真实可行，但要走 yolov8*-world 分支，不是 yolo26n**。

**建议**：
1. 短期：**不要换 yolov8n.pt → yolo26n.pt**，没有收益还略掉速度。
2. 中期（等 ultralytics 发 yolo26-world.pt + 5 任务系列、或我们试 ONNX export 路径）再回来重测。
3. D2a 产品功能值得开 sprint，但用 `yolov8s-world.pt`（已成熟）作为 v1，不指望 yolo26-world。

---

## 附：测试文件位置

- 测试模型：`/tmp/yolo26n.pt`（5.3 MB，可保留也可删）
- 测试图：`/tmp/bus.jpg`（137 KB）
- 测试脚本：`/tmp/yolo26_bench.py`、`/tmp/yolo26_openvocab2.py`、`/tmp/yolo_bench_3588.py`
- 副产物（Mac，未入仓）：`yolov8s-world.pt`（26 MB）+ ftfy/regex/wcwidth/clip 包（首次开 world 时被 ultralytics auto-installed，无害）
- 3588 副产物：`/tmp/{yolo26n.pt, yolov8n.pt, bus.jpg, yolo_bench_3588.py}`，可手动 `rm` 清理
- ultralytics 已升至 8.4.50（Mac 用户路径 + 3588 venv），**未改 requirements.txt 也未 commit**
