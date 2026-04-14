"""
video_processor.py
视频流处理 + YOLO检测
"""
import logging
import os
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

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
    frame: np.ndarray  # 原始帧（可选）


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
        self._event_queue = queue.Queue(maxsize=100)
        self._callback = None
        self._latest_frames: dict[str, np.ndarray] = {}
        self._frames_lock = threading.Lock()
        self._stream_stop_events: dict[str, threading.Event] = {}
        # 状态: "connecting" | "ok" | "error:<msg>" | "stopped"
        self._stream_status: dict[str, str] = {}

    # ── 启动/停止 ─────────────────────────────────────────────────────

    def start(self, callback: Callable[[DetectionEvent], None] = None):
        """启动所有视频流处理"""
        self._callback = callback

        # 加载YOLO模型（只加载一次）
        logger.info(f"加载 YOLO 模型: {self.model_path}")
        self._model = YOLO(self.model_path)

        # 为每个摄像头启动独立线程
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

        # 停止已移除或禁用的流
        for name in list(old_names):  # list() 避免迭代中修改
            if name not in new_enabled:
                logger.info(f"停止摄像头: {name}")
                self._stream_stop_events[name].set()
                del self._stream_stop_events[name]
                self._stream_status.pop(name, None)
                with self._frames_lock:
                    self._latest_frames.pop(name, None)

        # 重新计算 old_names（已删除的不再算）
        current_names = set(self._stream_stop_events.keys())

        # 启动新增的流（或重启同名但被重新启用的流）
        for name, src in new_enabled.items():
            if name not in current_names:
                logger.info(f"新增摄像头: {name}")
                self._start_stream(src)

        self.sources = new_sources

    def get_stream_status(self) -> dict[str, str]:
        return dict(self._stream_status)

    def get_latest_frame(self, name: str) -> np.ndarray | None:
        """获取指定摄像头的最新帧（供UI显示）"""
        with self._frames_lock:
            return self._latest_frames.get(name)

    def get_all_frames(self) -> dict[str, np.ndarray]:
        """获取所有摄像头最新帧"""
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
        """打开视频源，RTSP自动用ffmpeg+UDP参数"""
        is_rtsp = isinstance(url, str) and url.lower().startswith("rtsp://")
        if is_rtsp:
            # 使用ffmpeg backend，UDP传输，减少延迟和丢包
            os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS",
                "rtsp_transport;udp|analyzeduration;2000000|probesize;2000000|fflags;+genpts+discardcorrupt")
            cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        else:
            # 本机摄像头：macOS用设备号int，Linux /dev/videoX也可直接传
            try:
                dev = int(url)
            except (ValueError, TypeError):
                dev = url
            cap = cv2.VideoCapture(dev)
        return cap

    def _process_stream(self, src: dict, stop_ev: threading.Event = None):
        name = src.get("name", "未命名")
        url  = src.get("url", "0")
        if stop_ev is None:
            stop_ev = self._stop_event

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
            retry_delay = 3  # 重置重试间隔
            logger.info(f"摄像头已连接: {name}")

            frame_interval = 1.0 / self.inference_fps
            last_inference = 0

            while not stop_ev.is_set():
                ret, frame = cap.read()
                if not ret:
                    self._stream_status[name] = "connecting"
                    logger.warning(f"读取帧失败: {name}，重连中")
                    cap.release()
                    break  # 回到外层循环重连

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
                        event = DetectionEvent(
                            camera_name=name,
                            timestamp=now,
                            detections=detections,
                            frame=annotated
                        )
                        if self._callback:
                            self._callback(event)
                        else:
                            try:
                                self._event_queue.put_nowait(event)
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

            # 过滤：置信度 + 目标类别
            if conf < self.confidence:
                continue
            if self.target_classes and cls_id not in self.target_classes:
                continue

            bbox = boxes.xyxy[i].tolist()  # [x1, y1, x2, y2]
            detections.append({
                "class": results.names[cls_id],
                "class_id": cls_id,
                "confidence": round(conf, 2),
                "bbox": [int(x) for x in bbox]
            })

        return detections

    # ── 事件获取 ──────────────────────────────────────────────────────

    def get_event(self, timeout: float = 1.0) -> DetectionEvent | None:
        """从队列获取检测事件（阻塞）"""
        try:
            return self._event_queue.get(timeout=timeout)
        except queue.Empty:
            return None
