#!/usr/bin/env python3
"""
modules/openvocab_filter/main.py
开放词检测层 — 订 av/video/key_event（来自 keyframe_filter），
对当前 camera 拉 mjpeg snapshot，用 yolov8s-world.pt + CLIP text encoder
对一组业务 prompt（化工/安全场景：火 / 烟 / 未戴安全帽 / 跌倒 / 打架）做
open-vocab 检测；命中后发到 av/video/openvocab。

设计契约（基于 5/14 yolov8-world 实测，OVERNIGHT_REPORT_YOLOV8_WORLD_20260514.md）：
  - 3588 CPU 推理 ~1.6s/帧 — **绝不能每个 detect 都跑**，必须订 key_event 走事件触发
  - 单 worker ThreadPool；inflight_skip=True 时直接 drop 后续 key_event（不排队）
  - per-camera 节流 throttle_seconds 防同 camera 紧贴的 key 反复触发推理
  - RAM 守门：psutil mem_avail < mem_min_mb 直接 skip
  - conf_threshold 默认 0.40 — person+动词类 prompt（hugging/fighting）<0.40 几乎必误报
  - hits 长度 0 时不发 av/video/openvocab；只发"有命中"事件
  - 异常 / 超时全部 log warning + skip，绝不抛
  - 模型加载失败 / 路径不存在 → 模块只占位运行（enabled=False 路径），不影响 supervisor 10 模块全栈

Topic:
  订阅 av/video/key_event  payload: {camera, time, detections, key_reason, prev_summary}
  发布 av/video/openvocab  payload: {
      camera, ts, hits:[{class, conf, bbox:[x1,y1,x2,y2]}],
      key_reason, inference_ms, model, source_host
  }
"""
import logging
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import psutil
import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


DEFAULTS = {
    "enabled": True,
    # 5/21: 改持久路径 ~/models/yolov8s-world.pt（之前 /tmp tmpfs 每次重启即失）。
    # 仓库不带 weights（25MB），首次部署: 从 https://github.com/ultralytics/assets/releases/
    # 拉 yolov8s-world.pt 放到 ~/models/ 即可。Path.expanduser() 在加载时展开 ~。
    "model_path": "~/models/yolov8s-world.pt",
    # 化工/安全场景默认 5 类 prompt（演示用）
    "prompts": [
        "fire",
        "smoke",
        "person without hardhat",
        "person falling",
        "person fighting",
    ],
    # >=0.40 — person+动词 prompt 在 <0.40 误报严重（5/14 实测 hugging 0.81 但实际无人抱）
    "conf_threshold": 0.55,
    "mjpeg_base_url": "http://192.168.5.6:5051",
    "snapshot_timeout_s": 5,
    "snapshot_mode": "raw",
    "key_event_topic": "av/video/key_event",
    "openvocab_topic": "av/video/openvocab",
    # 单 worker；新 key 来时若 inflight 就跳（不排队，防 1.6s/帧推理堆积）
    "inflight_skip": True,
    # per-camera 节流；3588 1.6s/帧 + 节流 5s = 同 camera 最快 5s 一帧 open-vocab
    "throttle_seconds": 5.0,
    "mem_min_mb": 100,
    "host_label": "3588",
    # 推理超时（torch.no_grad + CPU 1.6s 正常 → 给 30s buffer）
    "inference_timeout_s": 30,
}


class OpenVocabFilterModule(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        ov = dict(DEFAULTS)
        ov.update(cfg.get("openvocab_filter", {}) or {})
        self._ov = ov

        streams = [{
            "topic": ov["openvocab_topic"],
            "channel": "openvocab",
            "kind": "kv_table",
            "title": "开放词检测",
        }]
        super().__init__("openvocab_filter", cfg, streams=streams)

        self._last_inference_ts: dict[str, float] = {}
        self._inflight_lock = threading.Lock()
        self._inflight = False
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ovworld")
        self._model = None  # yolov8-world 模型，lazy load
        self._model_load_failed = False
        self._stats = {
            "key_received": 0,
            "throttled": 0,
            "inflight_skipped": 0,
            "mem_guard_skipped": 0,
            "snapshot_failed": 0,
            "inference_failed": 0,
            "hits_published": 0,
            "empty_hits": 0,
        }

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        if not ov["enabled"]:
            self.logger.info("openvocab_filter 配置 enabled=false，仅占位不工作")
            return

        # lazy load 模型 — 首次 inference 才真正加载；启动期只校验路径
        model_path = Path(ov["model_path"]).expanduser()
        if not model_path.exists():
            self.logger.warning(
                f"openvocab_filter model_path 不存在: {model_path} — "
                f"模块仍订阅 key_event 但每次 inference 会 fail; "
                f"修复方法: 从 https://github.com/ultralytics/assets/releases/ "
                f"拉 yolov8s-world.pt 放到 {model_path}"
            )
            # 不 disable，保留订阅 — fail 路径会 stats 统计

        self.subscribe(ov["key_event_topic"])
        self.logger.info(
            f"订阅 {ov['key_event_topic']} | model={model_path.name} | "
            f"prompts={ov['prompts']} | conf>={ov['conf_threshold']} | "
            f"节流={ov['throttle_seconds']}s | mem_min={ov['mem_min_mb']}MB"
        )

    def _load_model_if_needed(self) -> bool:
        """lazy load yolov8-world 模型 + set_classes(prompts).

        首次调用时：
          1. import ultralytics (会 lazy 触发 torch / CLIP 加载)
          2. YOLO(model_path)
          3. set_classes(prompts) — 内部跑 CLIP text encoder 把 prompt 编码成 head 权重
        失败后置 _model_load_failed=True，后续 skip。
        """
        if self._model is not None:
            return True
        if self._model_load_failed:
            return False
        ov = self._ov
        model_path = Path(ov["model_path"]).expanduser()
        if not model_path.exists():
            self._model_load_failed = True
            self.logger.warning(f"模型路径不存在，放弃加载: {model_path}")
            return False
        try:
            t0 = time.monotonic()
            from ultralytics import YOLO  # 首次 import 含 torch / CLIP 装载，可能 5min
            model = YOLO(str(model_path))
            model.set_classes(list(ov["prompts"]))
            elapsed = (time.monotonic() - t0) * 1000
            self._model = model
            self.logger.info(
                f"yolov8-world 模型加载完成 ({elapsed:.0f}ms) | "
                f"prompts set: {ov['prompts']}"
            )
            return True
        except Exception as e:
            self._model_load_failed = True
            self.logger.warning(
                f"yolov8-world 模型加载失败 — open-vocab 路径不可用: {e}"
            )
            return False

    def _handle_message(self, topic: str, payload: dict) -> None:
        if topic != self._ov["key_event_topic"]:
            return
        if not self._ov["enabled"]:
            return
        self._stats["key_received"] += 1
        # BaseModule.publish 把 payload 字段平铺到顶层 + 一个 "header" key
        camera = payload.get("camera")
        det_time = payload.get("time") or time.time()
        key_reason = payload.get("key_reason", "")
        if not camera:
            return

        # per-camera 节流
        now = time.time()
        last = self._last_inference_ts.get(camera, 0.0)
        if now - last < self._ov["throttle_seconds"]:
            self._stats["throttled"] += 1
            return

        # 单 worker + inflight 互斥（不排队，新帧来时若处理中就丢）
        if self._ov["inflight_skip"]:
            with self._inflight_lock:
                if self._inflight:
                    self._stats["inflight_skipped"] += 1
                    return
                self._inflight = True

        self._last_inference_ts[camera] = now
        self._pool.submit(self._infer, camera, det_time, key_reason)

    def _infer(self, camera: str, det_time: float, key_reason: str) -> None:
        try:
            mem_avail_mb = psutil.virtual_memory().available // (1024 * 1024)
            if mem_avail_mb < self._ov["mem_min_mb"]:
                self._stats["mem_guard_skipped"] += 1
                self.logger.warning(
                    f"mem_avail={mem_avail_mb}MB < {self._ov['mem_min_mb']}MB，"
                    f"skip {camera}"
                )
                return

            if not self._load_model_if_needed():
                self._stats["inference_failed"] += 1
                return

            # 拉 snapshot 到 /tmp，路径喂给 ultralytics（避免内存里 decode 再 encode）
            snap_path = self._fetch_snapshot(camera)
            if snap_path is None:
                self._stats["snapshot_failed"] += 1
                return

            t_inf0 = time.monotonic()
            try:
                results = self._model(
                    str(snap_path),
                    conf=self._ov["conf_threshold"],
                    verbose=False,
                )
            except Exception as e:
                self._stats["inference_failed"] += 1
                self.logger.warning(f"yolov8-world 推理异常 camera={camera}: {e}")
                return
            inf_ms = int((time.monotonic() - t_inf0) * 1000)

            hits = self._extract_hits(results)
            if not hits:
                self._stats["empty_hits"] += 1
                self.logger.info(
                    f"[ov] {camera} reason={key_reason} | "
                    f"inf {inf_ms}ms | hits=0"
                )
                return

            payload_out = {
                "camera": camera,
                "ts": time.time(),
                "time": det_time,
                "hits": hits,
                "key_reason": key_reason,
                "inference_ms": inf_ms,
                "model": Path(self._ov["model_path"]).name,
                "source_host": self._ov["host_label"],
            }
            self.publish(self._ov["openvocab_topic"], payload_out)
            self._stats["hits_published"] += 1
            top = hits[0]
            self.logger.info(
                f"⚡ [ov] {camera} reason={key_reason} | "
                f"inf {inf_ms}ms | hits={len(hits)} top={top['class']}@{top['conf']:.2f}"
            )
        except Exception as e:
            self._stats["inference_failed"] += 1
            self.logger.warning(f"_infer 异常 camera={camera}: {e}")
        finally:
            if self._ov["inflight_skip"]:
                with self._inflight_lock:
                    self._inflight = False

    def _extract_hits(self, results) -> list[dict]:
        """ultralytics Results → 标准 hits list.

        results 形如 list[Results]，每个 Results.boxes.{xyxy, conf, cls}.
        cls index → self._model.names[idx] = prompt 字符串。
        """
        hits = []
        try:
            names = self._model.names if hasattr(self._model, "names") else {}
        except Exception:
            names = {}
        for r in results or []:
            boxes = getattr(r, "boxes", None)
            if boxes is None or len(boxes) == 0:
                continue
            try:
                xyxy = boxes.xyxy.cpu().numpy().tolist()
                conf = boxes.conf.cpu().numpy().tolist()
                cls = boxes.cls.cpu().numpy().astype(int).tolist()
            except Exception as e:
                self.logger.warning(f"boxes 解析失败: {e}")
                continue
            for bb, c, k in zip(xyxy, conf, cls):
                label = names.get(k, str(k)) if isinstance(names, dict) else (
                    names[k] if 0 <= k < len(names) else str(k)
                )
                hits.append({
                    "class": label,
                    "conf": float(c),
                    "bbox": [float(bb[0]), float(bb[1]), float(bb[2]), float(bb[3])],
                })
        # 按 conf 降序，方便消费方取 top-1
        hits.sort(key=lambda h: h["conf"], reverse=True)
        return hits

    def _fetch_snapshot(self, camera: str) -> Path | None:
        url = (
            f"{self._ov['mjpeg_base_url']}/snapshot/"
            f"{quote(camera)}?mode={self._ov['snapshot_mode']}"
        )
        try:
            r = requests.get(url, timeout=self._ov["snapshot_timeout_s"])
            if r.status_code != 200 or not r.content:
                self.logger.warning(
                    f"snapshot 失败 camera={camera} status={r.status_code} "
                    f"len={len(r.content)}"
                )
                return None
            # 写到 /tmp/openvocab_<camera>.jpg（每 camera 复用同一文件，节省 inode）
            safe = camera.replace("/", "_").replace(" ", "_")
            out = Path("/tmp") / f"openvocab_{safe}.jpg"
            out.write_bytes(r.content)
            return out
        except Exception as e:
            self.logger.warning(f"snapshot 异常 camera={camera}: {e}")
            return None

    def run(self) -> None:
        """主循环：心跳 + 每 60s 打一次统计行。"""
        self.start()
        last_heartbeat = time.time()
        last_stats = time.time()
        try:
            while self._running.is_set():
                time.sleep(1)
                now = time.time()
                if now - last_heartbeat >= self.HEARTBEAT_INTERVAL and self._connected:
                    self._publish_discovery("heartbeat")
                    last_heartbeat = now
                if now - last_stats >= 60:
                    self.logger.info(f"[stats] {self._stats}")
                    last_stats = now
        except KeyboardInterrupt:
            self.logger.info("收到键盘中断信号")
        finally:
            self._pool.shutdown(wait=False, cancel_futures=True)
            self.stop()


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    OpenVocabFilterModule(str(config_path)).run()


if __name__ == "__main__":
    main()
