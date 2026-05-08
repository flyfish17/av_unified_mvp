"""
modules/video_processor/processor.py
视频流处理 + YOLO 检测

支持两种输出方式（可同时启用）：
  - callback: start(callback=fn)，每个 DetectionEvent 推回主程序
  - MQTT:     set_mqtt_publisher(fn)，按 §4 协议发布到 av/video/detect
"""
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import cv2
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)


@dataclass
class DetectionEvent:
    """检测事件"""
    camera_name: str
    timestamp: float
    detections: list  # [{"class": "person", "confidence": 0.95, "bbox": [x,y,w,h]}]
    frame: np.ndarray  # 标注后的帧


class VideoProcessor:
    def __init__(self, cfg: dict):
        self.sources = cfg.get("sources", [])
        yolo_cfg = cfg.get("yolo", {})

        self.model_path = yolo_cfg.get("model", "yolov8n.pt")
        self.confidence = yolo_cfg.get("confidence", 0.5)
        self.inference_fps = yolo_cfg.get("inference_fps", 2)
        self.target_classes = set(yolo_cfg.get("target_classes", []))

        self._model = None
        self._threads = []
        self._stop_event = threading.Event()
        self._event_queue: queue.Queue = queue.Queue(maxsize=100)
        self._callback: Optional[Callable[[DetectionEvent], None]] = None
        self._mqtt_publisher: Optional[Callable[[str, dict], None]] = None
        # 双缓存：原始 vs 标注（YOLO bbox）
        self._latest_raw_frames: dict[str, np.ndarray] = {}
        self._latest_annotated_frames: dict[str, np.ndarray] = {}
        # 预编码 JPEG（http handler 直接返回 bytes，省去每次 imencode 开销）
        self._latest_raw_jpeg: dict[str, bytes] = {}
        self._latest_annotated_jpeg: dict[str, bytes] = {}
        # 推理队列：每路一个，maxsize=1，drop-old 策略，保证只推最新帧
        self._inference_queues: dict[str, queue.Queue] = {}
        self._frames_lock = threading.Lock()
        self._stream_stop_events: dict[str, threading.Event] = {}
        # 状态: "connecting" | "ok" | "error:<msg>" | "stopped"
        self._stream_status: dict[str, str] = {}
        # JPEG 质量
        self._jpeg_quality = yolo_cfg.get("jpeg_quality", 75)
        # L3.1：每路摄像头亮度上次发布时间（节流到 10s/次）
        self._last_brightness_publish: dict[str, float] = {}
        self._brightness_interval_s = float(yolo_cfg.get("brightness_interval_s", 10))

    # ── MQTT 集成 ─────────────────────────────────────────────────────

    def set_mqtt_publisher(self, publisher_fn: Callable[[str, dict], None]):
        """注入 MQTT publish 函数。签名 publisher(topic: str, payload: dict)"""
        self._mqtt_publisher = publisher_fn
        logger.info("MQTT publisher 已设置")

    def _publish_detection(self, camera_name: str, timestamp: float, detections: list):
        """按 §4 协议发布到 av/video/detect"""
        if self._mqtt_publisher is None:
            return
        self._mqtt_publisher("av/video/detect", {
            "camera": camera_name,
            "time": timestamp,
            "detections": detections,
        })

    # ── 启动/停止 ─────────────────────────────────────────────────────

    def start(self, callback: Callable[[DetectionEvent], None] = None):
        """启动所有视频流处理"""
        self._callback = callback

        logger.info(f"加载 YOLO 模型: {self.model_path}")
        try:
            self._model = YOLO(self.model_path)
        except Exception as e:
            # 模型加载失败不阻塞整个视频模块：raw MJPEG 流仍可用，仅停发 detection 事件
            self._model = None
            logger.error(f"YOLO 加载失败 ({self.model_path}): {e}；raw 流继续，detection 暂停")

        for src in self.sources:
            if not src.get("enabled", True):
                continue
            self._start_stream(src)

        logger.info(f"已启动 {len(self._threads)} 路视频流")

    def _start_stream(self, src: dict):
        """启动单路视频流线程"""
        name = src.get("name", "未命名")
        stop_ev = threading.Event()
        self._stream_stop_events[name] = stop_ev
        t = threading.Thread(
            target=self._process_stream,
            args=(src, stop_ev),
            daemon=True
        )
        t.start()
        self._threads.append(t)

    def reload_sources(self, new_sources: list):
        """热重载摄像头列表，不重启整个系统"""
        old_names = set(self._stream_stop_events.keys())
        new_enabled = {s["name"]: s for s in new_sources if s.get("enabled", True)}

        for name in list(old_names):
            if name not in new_enabled:
                logger.info(f"停止摄像头: {name}")
                self._stream_stop_events[name].set()
                del self._stream_stop_events[name]
                self._stream_status.pop(name, None)
                with self._frames_lock:
                    self._latest_raw_frames.pop(name, None)
                    self._latest_annotated_frames.pop(name, None)
                    self._latest_raw_jpeg.pop(name, None)
                    self._latest_annotated_jpeg.pop(name, None)
                self._inference_queues.pop(name, None)

        current_names = set(self._stream_stop_events.keys())

        for name, src in new_enabled.items():
            if name not in current_names:
                logger.info(f"新增摄像头: {name}")
                self._start_stream(src)

        self.sources = new_sources

    def get_stream_status(self) -> dict[str, str]:
        return dict(self._stream_status)

    def get_latest_frame(self, name: str, mode: str = "raw") -> np.ndarray | None:
        """获取指定摄像头的最新帧。mode=raw 是流畅原始帧；mode=annotated 是带 YOLO bbox 的帧"""
        with self._frames_lock:
            if mode == "annotated":
                return self._latest_annotated_frames.get(name) or self._latest_raw_frames.get(name)
            return self._latest_raw_frames.get(name)

    def get_latest_jpeg(self, name: str, mode: str = "raw") -> bytes | None:
        """直接拿预编码 JPEG bytes，避免每次 HTTP 请求都重新编码"""
        with self._frames_lock:
            if mode == "annotated":
                return self._latest_annotated_jpeg.get(name) or self._latest_raw_jpeg.get(name)
            return self._latest_raw_jpeg.get(name)

    def get_all_frames(self) -> dict[str, np.ndarray]:
        """获取所有摄像头最新原始帧"""
        with self._frames_lock:
            return dict(self._latest_raw_frames)

    def stop(self):
        self._stop_event.set()
        for ev in self._stream_stop_events.values():
            ev.set()
        for t in self._threads:
            t.join(timeout=2)

    # ── 视频流处理 ────────────────────────────────────────────────────

    def _open_capture(self, url: str) -> cv2.VideoCapture:
        """打开视频源，RTSP 自动用 ffmpeg+UDP 参数"""
        is_rtsp = isinstance(url, str) and url.lower().startswith("rtsp://")
        if is_rtsp:
            os.environ.setdefault(
                "OPENCV_FFMPEG_CAPTURE_OPTIONS",
                "rtsp_transport;udp|analyzeduration;2000000|probesize;2000000|fflags;+genpts+discardcorrupt",
            )
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        else:
            try:
                dev = int(url)
                # macOS AVFoundation 权限弹窗不能从后台线程触发。
                os.environ.setdefault("OPENCV_AVFOUNDATION_SKIP_AUTH", "1")
            except (ValueError, TypeError):
                dev = url
            cap = cv2.VideoCapture(dev)
        return cap

    def _encode_jpeg(self, frame: np.ndarray) -> bytes | None:
        try:
            ok, jpg = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, self._jpeg_quality])
            return jpg.tobytes() if ok else None
        except Exception:
            return None

    def _inference_worker(self, name: str, q: queue.Queue, stop_ev: threading.Event):
        """每路摄像头一个推理线程：从 q 拿最新帧 → YOLO → 缓存标注帧 / JPEG / 发布事件"""
        frame_interval = 1.0 / max(self.inference_fps, 0.5)
        last_run = 0.0
        while not stop_ev.is_set():
            try:
                frame = q.get(timeout=0.5)
            except queue.Empty:
                continue
            now = time.time()
            if now - last_run < frame_interval:
                continue  # 限速，避免推理速度过快堆积 GPU/CPU
            last_run = now
            if self._model is None:
                continue
            try:
                results = self._model(frame, verbose=False)[0]
                detections = self._parse_results(results)
                annotated = results.plot()
            except Exception as e:
                logger.error(f"推理异常 [{name}]: {e}")
                continue

            ann_jpeg = self._encode_jpeg(annotated)
            with self._frames_lock:
                self._latest_annotated_frames[name] = annotated
                if ann_jpeg:
                    self._latest_annotated_jpeg[name] = ann_jpeg

            if detections:
                self._publish_detection(name, now, detections)
                if self._callback:
                    try:
                        self._callback(DetectionEvent(
                            camera_name=name, timestamp=now,
                            detections=detections, frame=annotated,
                        ))
                    except Exception as e:
                        logger.error(f"callback 异常: {e}")

    def _process_stream(self, src: dict, stop_ev: threading.Event = None):
        name = src.get("name", "未命名")
        url = src.get("url", "0")
        if stop_ev is None:
            stop_ev = self._stop_event

        # 推理队列 + 推理线程：与 capture 解耦
        inference_q: queue.Queue = queue.Queue(maxsize=1)
        self._inference_queues[name] = inference_q
        inf_t = threading.Thread(
            target=self._inference_worker,
            args=(name, inference_q, stop_ev),
            daemon=True,
        )
        inf_t.start()

        self._stream_status[name] = "connecting"
        retry_delay = 3
        max_retry_delay = 30

        while not stop_ev.is_set():
            cap = self._open_capture(url)
            if not cap.isOpened():
                err = f"error:无法打开 {url[:40]}"
                self._stream_status[name] = err
                logger.error(f"无法打开摄像头: {name} ({url})，{retry_delay}s 后重试")
                for _ in range(retry_delay):
                    if stop_ev.is_set():
                        self._stream_status[name] = "stopped"
                        return
                    time.sleep(1)
                retry_delay = min(retry_delay * 2, max_retry_delay)
                continue

            self._stream_status[name] = "ok"
            retry_delay = 3
            logger.info(f"摄像头已连接: {name}")

            while not stop_ev.is_set():
                ret, frame = cap.read()
                if not ret:
                    self._stream_status[name] = "connecting"
                    logger.warning(f"读取帧失败: {name}，重连中")
                    cap.release()
                    break

                # 1. 始终缓存最新原始帧 + 预编码 JPEG（流畅模式下这就是输出）
                raw_jpeg = self._encode_jpeg(frame)
                with self._frames_lock:
                    self._latest_raw_frames[name] = frame
                    if raw_jpeg:
                        self._latest_raw_jpeg[name] = raw_jpeg

                # 2. 喂给推理线程；drop-old 策略，永远只推理最新帧
                try:
                    inference_q.put_nowait(frame)
                except queue.Full:
                    try: inference_q.get_nowait()
                    except queue.Empty: pass
                    try: inference_q.put_nowait(frame)
                    except queue.Full: pass

                # 3. 亮度采样（L3.1）：每 N 秒一次，给 Node-RED 环境自动化用
                now_ts = time.time()
                if now_ts - self._last_brightness_publish.get(name, 0) >= self._brightness_interval_s:
                    if self._mqtt_publisher:
                        try:
                            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                            brightness = float(gray.mean())  # 0-255
                            self._mqtt_publisher("av/env/brightness", {
                                "camera": name,
                                "brightness": round(brightness, 1),
                                "ts": now_ts,
                            })
                            self._last_brightness_publish[name] = now_ts
                        except Exception as e:
                            logger.debug(f"亮度采样失败 [{name}]: {e}")

            cap.release()

        self._stream_status[name] = "stopped"
        logger.info(f"摄像头已关闭: {name}")

    def _parse_results(self, results) -> list:
        """解析 YOLO 结果"""
        detections = []
        boxes = results.boxes

        for i in range(len(boxes)):
            cls_id = int(boxes.cls[i])
            conf = float(boxes.conf[i])

            if conf < self.confidence:
                continue
            if self.target_classes and cls_id not in self.target_classes:
                continue

            bbox = boxes.xyxy[i].tolist()
            detections.append({
                "class": results.names[cls_id],
                "class_id": cls_id,
                "confidence": round(conf, 2),
                "bbox": [int(x) for x in bbox],
            })

        return detections

    # ── 事件获取 ──────────────────────────────────────────────────────

    def get_event(self, timeout: float = 1.0) -> DetectionEvent | None:
        """从队列获取检测事件（阻塞）"""
        try:
            return self._event_queue.get(timeout=timeout)
        except queue.Empty:
            return None
