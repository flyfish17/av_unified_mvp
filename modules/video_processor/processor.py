#!/usr/bin/env python3
"""
modules/video_processor/processor.py
视频处理模块 - 独立进程版本
通过MQTT发布检测事件，同时保留原有callback接口
"""
import logging
import time
from typing import Callable, Optional

import cv2
import numpy as np
from ultralytics import YOLO

logger = logging.getLogger(__name__)


class VideoProcessor:
    """
    视频处理模块

    重构后支持两种模式:
    1. callback模式 (向后兼容): start(callback=func)
    2. MQTT模式: set_mqtt_publisher(publish_func)
    """

    def __init__(self, cfg: dict):
        self.sources = cfg.get("sources", [])
        yolo_cfg = cfg.get("yolo", {})

        self.model_path = yolo_cfg.get("model", "yolov8n.pt")
        self.confidence = yolo_cfg.get("confidence", 0.5)
        self.inference_fps = yolo_cfg.get("inference_fps", 2)
        self.target_classes = set(yolo_cfg.get("target_classes", []))

        self._model = None
        self._threads = []
        self._stop_event = __import__("threading").Event()
        self._event_queue = __import__("queue").Queue(maxsize=100)
        self._callback = None
        self._mqtt_publisher: Optional[Callable] = None
        self._latest_frames = {}
        self._frames_lock = __import__("threading").Lock()
        self._stream_stop_events = {}
        self._stream_status = {}

    # ── MQTT集成 ──────────────────────────────────────────────────────

    def set_mqtt_publisher(self, publisher_fn: Callable[[str, dict], None]):
        """
        设置MQTT发布函数

        Args:
            publisher_fn: 签名 publish_func(topic: str, payload: dict)
        """
        self._mqtt_publisher = publisher_fn
        logger.info("MQTT publisher 已设置")

    def _publish_detection(self, camera_name: str, timestamp: float, detections: list):
        """通过MQTT发布检测事件"""
        if self._mqtt_publisher is None:
            logger.debug("MQTT publisher 未设置，跳过发布")
            return

        # 查找摄像头URL
        source_url = ""
        for src in self.sources:
            if src.get("name") == camera_name:
                source_url = src.get("url", "")
                break

        payload = {
            "topic_type": "event",
            "payload": {
                "event_type": "detection",
                "camera": {
                    "name": camera_name,
                    "source": source_url,
                },
                "timestamp": timestamp,
                "detections": detections,
                "detection_count": len(detections),
            },
        }

        self._mqtt_publisher("av/video/event", payload)
        logger.debug(f"发布视频检测事件: {camera_name}, {len(detections)} 个目标")

    # ── 原有接口（向后兼容）───────────────────────────────────────────

    def start(self, callback: Callable = None):
        """启动所有视频流处理"""
        self._callback = callback

        logger.info(f"加载 YOLO 模型: {self.model_path}")
        self._model = YOLO(self.model_path)

        for src in self.sources:
            if not src.get("enabled", True):
                continue
            self._start_stream(src)

        logger.info(f"已启动 {len(self._threads)} 路视频流")

    def _start_stream(self, src: dict):
        name = src.get("name", "未命名")
        stop_ev = __import__("threading").Event()
        self._stream_stop_events[name] = stop_ev
        t = __import__("threading").Thread(
            target=self._process_stream,
            args=(src, stop_ev),
            daemon=True,
        )
        t.start()
        self._threads.append(t)

    def reload_sources(self, new_sources: list):
        """热重载摄像头列表"""
        old_names = set(self._stream_stop_events.keys())
        new_enabled = {s["name"]: s for s in new_sources if s.get("enabled", True)}

        for name in list(old_names):
            if name not in new_enabled:
                logger.info(f"停止摄像头: {name}")
                self._stream_stop_events[name].set()
                del self._stream_stop_events[name]
                self._stream_status.pop(name, None)
                with self._frames_lock:
                    self._latest_frames.pop(name, None)

        current_names = set(self._stream_stop_events.keys())

        for name, src in new_enabled.items():
            if name not in current_names:
                logger.info(f"新增摄像头: {name}")
                self._start_stream(src)

        self.sources = new_sources

    def get_stream_status(self) -> dict:
        return dict(self._stream_status)

    def get_latest_frame(self, name: str) -> np.ndarray | None:
        with self._frames_lock:
            return self._latest_frames.get(name)

    def get_all_frames(self) -> dict:
        with self._frames_lock:
            return dict(self._latest_frames)

    def stop(self):
        self._stop_event.set()
        for ev in self._stream_stop_events.values():
            ev.set()
        for t in self._threads:
            t.join(timeout=2)

    # ── 视频流处理 ────────────────────────────────────────────────────

    def _open_capture(self, url: str) -> cv2.VideoCapture:
        """打开视频源"""
        import os as _os

        is_rtsp = isinstance(url, str) and url.lower().startswith("rtsp://")
        if is_rtsp:
            _os.environ.setdefault(
                "OPENCV_FFMPEG_CAPTURE_OPTIONS",
                "rtsp_transport;udp|analyzeduration;2000000|probesize;2000000|fflags;+genpts+discardcorrupt",
            )
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        else:
            try:
                dev = int(url)
            except (ValueError, TypeError):
                dev = url
            cap = cv2.VideoCapture(dev)
        return cap

    def _process_stream(self, src: dict, stop_ev):
        import queue

        name = src.get("name", "未命名")
        url = src.get("url", "0")

        self._stream_status[name] = "connecting"
        retry_delay = 3
        max_retry_delay = 30

        while not stop_ev.is_set():
            cap = self._open_capture(url)
            if not cap.isOpened():
                err = f"error:无法打开 {url[:40]}"
                self._stream_status[name] = err
                logger.error(f"无法打开摄像头: {name} ({url})，{retry_delay}s后重试")
                for _ in range(retry_delay):
                    if stop_ev.is_set():
                        return
                    time.sleep(1)
                retry_delay = min(retry_delay * 2, max_retry_delay)
                continue

            self._stream_status[name] = "ok"
            retry_delay = 3
            logger.info(f"摄像头已连接: {name}")

            frame_interval = 1.0 / self.inference_fps
            last_inference = 0

            while not stop_ev.is_set():
                ret, frame = cap.read()
                if not ret:
                    self._stream_status[name] = "connecting"
                    logger.warning(f"读取帧失败: {name}，重连中")
                    cap.release()
                    break

                now = time.time()
                if now - last_inference < frame_interval:
                    with self._frames_lock:
                        if name not in self._latest_frames:
                            self._latest_frames[name] = frame.copy()
                    continue

                last_inference = now

                try:
                    results = self._model(frame, verbose=False)[0]
                    detections = self._parse_results(results)
                    annotated = results.plot()
                    with self._frames_lock:
                        self._latest_frames[name] = annotated

                    if detections:
                        # 通过MQTT发布
                        self._publish_detection(name, now, detections)

                        # 保留callback调用（向后兼容）
                        if self._callback:
                            from dataclasses import dataclass

                            @dataclass
                            class DetectionEvent:
                                camera_name: str
                                timestamp: float
                                detections: list
                                frame: np.ndarray

                            event = DetectionEvent(
                                camera_name=name,
                                timestamp=now,
                                detections=detections,
                                frame=annotated,
                            )
                            try:
                                self._callback(event)
                            except Exception as e:
                                logger.error(f"callback异常: {e}")
                        else:
                            try:
                                self._event_queue.put_nowait((name, now, detections))
                            except queue.Full:
                                pass
                except Exception as e:
                    logger.error(f"推理异常 [{name}]: {e}")
                    with self._frames_lock:
                        self._latest_frames[name] = frame.copy()

            cap.release()

        self._stream_status[name] = "stopped"
        logger.info(f"摄像头已关闭: {name}")

    def _parse_results(self, results) -> list:
        """解析YOLO结果"""
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

    def get_event(self, timeout: float = 1.0):
        """从队列获取检测事件（阻塞）"""
        try:
            return self._event_queue.get(timeout=timeout)
        except __import__("queue").Empty:
            return None
