# yolov8n RK3588 NPU 模型

由 `yolov8n.pt` 导出（2026-08-21 在 62 板上导出，ultralytics 8.4.83 + rknn-toolkit2 2.3.2，fp16，imgsz 640）：

```bash
# 板上独立 venv（rknn-toolkit2 只有 Linux 包；onnxoptimizer 无 aarch64 wheel，跳过不影响导出）
python3 -m venv ~/rknn-export-venv && export PATH=~/rknn-export-venv/bin:$PATH
pip install --no-deps rknn-toolkit2==2.3.2
pip install "protobuf==3.20.3" "numpy<=1.26.4" "onnx==1.16.1" onnxruntime "torch==2.2.0" "torchvision==0.17.0" \
            opencv-python fast-histogram ruamel.yaml scipy tqdm psutil "ultralytics==8.4.83"
python scripts/export_yolo_rknn.py     # 不要直接用 ultralytics 裸导出,见下
```

运行时：生产 venv 装 `rknn-toolkit-lite2==2.3.2`，config `video.yolo.model: yolov8n_rknn_model`，
`processor.py` 零改动（ultralytics AutoBackend 识别 `*_rknn_model/` 目录）。

62 实测（1280×720 输入，50 帧均值）：CPU .pt 1167ms/帧·进程 CPU 246% → NPU 106ms/帧·112%，检出目标与类别一致。

## ⚠️ 必须用 `scripts/export_yolo_rknn.py` 导出（2026-08-21 实况事故）

ultralytics 裸 `export(format="rknn")` 出的 fp16 模型在 bus.jpg 上正常，**实况摄像头帧 box 通道出 inf**
（RKNN fp16 下 DFL 的 softmax 不减 max，背景 anchor 的 logits 让 exp 溢出 65504）→ NMS 出 NaN →
`plot()` 崩 `cannot convert float NaN to integer`。62 上 80 分钟 781 次异常、零检出。

修：导出时给 `DFL.forward` 的 softmax 前显式减每组 max（数学等价），`opset=17`。验证：3 张真实帧 inf=0、
与 CPU .pt 检出/类别一致；RTSP 实时流 300 帧零异常。

int8 量化（32 张现场帧校准）试过：inf 没了但**零检出**——box(0-640) 与分数(0-1) 同张量 8-bit 量化把分数压成 0，
要走 int8 得拆头（rknn_model_zoo 做法），收益不值，放弃。
