#!/usr/bin/env python
# yolov8n.pt → yolov8n_rknn_model/ (RK3588 NPU, fp16)
# 在 RK3588 板上的导出 venv 里跑(rknn-toolkit2 只有 Linux 包,装法见 yolov8n_rknn_model/README.md):
#   cd ~/av_unified_mvp && ~/rknn-export-venv/bin/python scripts/export_yolo_rknn.py
#
# 为什么不直接 YOLO().export(format="rknn"):RKNN fp16 下 YOLOv8 DFL 的 softmax 不减 max,
# 实况帧背景 anchor 的 logits 让 exp 溢出 → box 通道 inf → NMS 出 NaN → processor plot() 崩。
# 这里 softmax 前显式减每组 max(数学等价),导出图里 exp 参数 <=0,fp16 永不溢出。opset 固定 17(torch 2.2 ReduceMax 兼容)。
import torch
from ultralytics import YOLO
from ultralytics.nn.modules import block
def dfl_forward_safe(self, x):
    b, _, a = x.shape
    t = x.view(b, 4, self.c1, a).transpose(2, 1)
    t = t - t.amax(1, keepdim=True)
    return self.conv(t.softmax(1)).view(b, 4, a)
block.DFL.forward = dfl_forward_safe
m = YOLO("yolov8n.pt")  # 仓库根目录(gitignore,板上有)
out = m.export(format="rknn", name="rk3588", imgsz=640, opset=17)
print("EXPORTED", out)
