# openvocab_filter 落地报告 — 2026-05-14

> 任务：在 av_unified_mvp 落地 `modules/openvocab_filter/` 新模块（yolov8-world open-vocab 检测），订 keyframe_filter 输出的 `av/video/key_event`，对当前 camera 拉 snapshot 跑 yolov8s-world，命中后发 `av/video/openvocab`。
>
> 结论：**落地 ✓ — 10 模块全在，e2e 推理通路打通 (3588 实测 inference 2033ms)，hits=0（当前 camera 内容无 fire/smoke/未戴安全帽/跌倒/打架，符合预期）**

---

## 1. 新模块文件清单

| 文件 | 行数 | 说明 |
|------|------|------|
| `modules/openvocab_filter/__init__.py` | 0 | 空（与既有模块约定一致） |
| `modules/openvocab_filter/main.py` | 366 | 完整模块（BaseModule 子类 + lazy load + 单 worker + inflight 互斥 + 节流 + mem 守门 + stats 60s） |

修改文件：
- `main.py`：MANAGED_MODULES 末尾 +1 行 `"modules.openvocab_filter.main"`（10 模块全栈）

---

## 2. 关键设计点

- **订** `av/video/key_event`（来自 keyframe_filter，密集场景 ~0.1-0.5 Hz）
- **发** `av/video/openvocab`，**仅 hits.len > 0 时发**（empty_hits 路径只 stats + info log）
- **模型 lazy load**：首次 inference 才 import ultralytics + YOLO + set_classes（避免占用 supervisor 启动期）
- **3 重串行保护**：
  1. per-camera throttle 5s（默认）
  2. inflight_skip=True 单 worker 互斥（新 key 来时若 inflight 直接 drop，不排队）
  3. ThreadPoolExecutor(max_workers=1)
- **conf >= 0.40 默认**：person+动词 prompt（hugging/fighting）<0.40 几乎必误报，5/14 OVERNIGHT_REPORT 实测结论
- **mem 守门**：mem_avail < 100 MB skip（3588 8GB 上不太可能触发，但保留兜底）
- **失败 fallback**：模型路径不存在 / 加载失败 → `_model_load_failed=True` 后续 skip，模块本身仍 alive（不会被 supervisor 反复重拉）
- **discovery stream**：`kind: kv_table` `channel: openvocab` `title: 开放词检测`（dashboard 可订）

---

## 3. 3588 部署后健康检查

| 检查项 | 结果 |
|--------|------|
| 10 模块全部 alive | ✓ (audio_processor / video_processor / llm_engine / system_info / network_info / network_scanner / husion_distributed / control_dispatcher / keyframe_filter / **openvocab_filter**) |
| openvocab_filter MQTT 连接 | ✓ `已连接 MQTT Broker 127.0.0.1:1883` |
| 模块 discovery online | ✓ `[发现] 模块上线: openvocab_filter @ 192.168.5.6` |
| 启动 stats 行 60s 节奏 | ✓（已打印多条 [stats] 行） |

---

## 4. e2e 实测一次（detect → key_event → openvocab）

注入合成 `av/video/detect`（camera=USB罗技C920, class=person, conf=0.9, bbox=[100,100,300,400]）:

```
06:14:54 [stats] key_received=1   ← keyframe_filter first_detect 触发
06:14:55 yolov8-world 模型加载完成 (11512ms) | prompts set: [...]
                                  ← 首次 lazy load，CLIP cache 已存（5/14 早 Sub-2 已下过）
06:14:58 [ov] USB罗技C920 reason=first_detect | inf 2033ms | hits=0
                                  ← yolov8-world CPU 推理 2.03s，hits=0 (当前办公室无 fire/smoke/...)
```

**关键时延**：
- 模型 lazy load: **11.5s**（CLIP cache 命中，避开了首次 5min 下 weights 的等待）
- 单次推理: **2033 ms** （与 5/14 OVERNIGHT_REPORT bench 1.6-1.8s 同量级，略偏高可能因首推未 warmup）
- 节流 5s + inflight skip：同 camera 最快 5s 一次推理上限，符合 1.6s/帧的硬约束

**hits=0 解读**：办公室 USB-C920 当前画面无火/烟/施工/跌倒/打架 → empty_hits++ 是正确路径，不发 av/video/openvocab。

---

## 5. 失败模式 (设计已 cover)

| 失败模式 | 行为 |
|---------|------|
| `model_path` 不存在 | 启动期 warning 但继续订 key_event；首次 inference 时 `_load_model_if_needed` 检测 → `_model_load_failed=True` → stats `inference_failed++`，**模块不退出** |
| ultralytics import 失败 / CLIP 装失败 | 同上，`_load_model_if_needed` try/except 兜底，置 `_model_load_failed=True` |
| snapshot 拉取超时 / 404 | `_fetch_snapshot` warning + 返回 None → stats `snapshot_failed++`，跳本次 |
| 推理异常 | try/except 兜底，stats `inference_failed++` |
| mem 不足 | 进入 `_infer` 第一步 psutil 检查，stats `mem_guard_skipped++` |
| inflight 时新 key 到 | stats `inflight_skipped++`，不排队（防 1.6s/帧的队列堆积） |

---

## 6. 部署 SOP（一句话）

> 部署到一台新 3588：scp `yolov8s-world.pt` (26MB) 到 `/tmp/`；首次启动模块 lazy load 时 ultralytics 会自动下 CLIP weights ~338MB 到 `~/.cache/clip/`，**耗时约 5 分钟，仅首次**；后续启动 ~11s（CLIP cache 命中）。

如果首次启动慢不可接受，部署 SOP 可预填 `~/.cache/clip/` 目录。

---

## 7. 接下来（不在本次范围）

- 化工/工地真实场景图验证 fire / smoke / extinguisher / gas mask（5/14 OVERNIGHT_REPORT §5 未验证项）
- per-camera prompt 配置（system_config.yaml 加 `openvocab_filter.prompts_per_camera`，可商业灵活配置）
- dashboard 接 `av/video/openvocab` 显示命中告警（演示页面"未戴安全帽/跌倒/火焰"）
- RKNN 适配 yolov8-world（5/14 OVERNIGHT_REPORT §5 标注 world 模型 RKNN 还没适配，保持 CPU 路径）
