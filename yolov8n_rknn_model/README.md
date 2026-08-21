# yolov8n RK3588 NPU 模型

由 `yolov8n.pt` 导出（2026-08-21 在 62 板上导出，ultralytics 8.4.83 + rknn-toolkit2 2.3.2，fp16，imgsz 640）：

```bash
# 板上独立 venv（rknn-toolkit2 只有 Linux 包；onnxoptimizer 无 aarch64 wheel，跳过不影响导出）
python3 -m venv ~/rknn-export-venv && export PATH=~/rknn-export-venv/bin:$PATH
pip install --no-deps rknn-toolkit2==2.3.2
pip install "protobuf==3.20.3" "numpy<=1.26.4" "onnx==1.16.1" onnxruntime "torch==2.2.0" "torchvision==0.17.0" \
            opencv-python fast-histogram ruamel.yaml scipy tqdm psutil "ultralytics==8.4.83"
python -c 'from ultralytics import YOLO; YOLO("yolov8n.pt").export(format="rknn", name="rk3588", imgsz=640)'
```

运行时：生产 venv 装 `rknn-toolkit-lite2==2.3.2`，config `video.yolo.model: yolov8n_rknn_model`，
`processor.py` 零改动（ultralytics AutoBackend 识别 `*_rknn_model/` 目录）。

62 实测（1280×720 输入，50 帧均值）：CPU .pt 1167ms/帧·进程 CPU 246% → NPU 106ms/帧·112%，检出目标与类别一致。
