"""
会议原音会话录制 + 导出 HTTP（:5052）— net_multicast（会议主机组播）路径。

背景（2026-08-20 用户实测踩空后拍板补齐）：原"导出原音" :5052 服务在
audio_processor（本地麦路径），纪要机形态（audio.source=net_multicast）下
audio_processor 不起，按钮落到浏览器拒绝页。本文件给组播路径补齐同一能力。

- 输入：各路 UdpMicChannel **gate 之后**的 16k int16 PCM——gate 天然过滤
  静音（含 1.8s hangover），录下来的是"有声拼接"，无会议时零写盘。
- 混音：固定节拍（100ms tick）把本 tick 各路到达的 PCM 相加钳位。多数时刻
  只有一路开门；插话重叠时正确叠加。增量 append 写
  data/recordings/session-<启动时间戳>.pcm（裸 PCM，导出时现拼 WAV 头流式返回，
  遵守"别全放内存"约束：3h 有声 ≈ 350MB 全在盘上）。
- 导出：GET :5052/audio/export.wav（?part=N 支持 >4G 切片）。handler 抄自
  audio_processor._AudioExportHandler 的文件路径——不跨模块 import（那边
  模块级会拉起 torch/funasr 重依赖）；两处相似 > 早产抽象。
- 清理：启动时 recordings 目录只保留最近 5 个会话文件（板上磁盘 157G 富余，
  gate 后写量 = 有声时长 × 32KB/s，非约束）。
"""
import logging
import math
import os
import struct
import threading
import time
from collections import deque
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import numpy as np

logger = logging.getLogger("net_audio_capture")

EXPORT_HTTP_PORT = 5052
RECORD_DIR = Path("data/recordings")
KEEP_SESSIONS = 5            # 启动清理：连本次共保留最近 5 个会话文件
TICK_S = 0.1                 # 混音节拍 100ms
QUEUE_MAX_S = 1.0            # 单路积压上限（秒），超出丢最老数据防漂移堆积


class SessionRecorder:
    """gate 后 PCM 混音落盘。feed() 线程安全（各路 recv 线程调用）。"""

    def __init__(self, num_channels: int, sample_rate: int = 16000):
        self._n = num_channels
        self._rate = sample_rate
        self._tick_samples = int(TICK_S * sample_rate)
        self._queues = [deque() for _ in range(num_channels)]  # 每项 np.int16 数组
        self._qlen = [0] * num_channels                        # 各路积压样本数
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        RECORD_DIR.mkdir(parents=True, exist_ok=True)
        self._cleanup_old()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.path = RECORD_DIR / f"session-{stamp}.pcm"
        self._fh = open(self.path, "ab")
        self.written_bytes = 0

    # ── UdpMicChannel gate 后调用（recv 线程）─────────────────────────
    def feed(self, mic_id: int, pcm16: np.ndarray) -> None:
        if self._stop.is_set() or len(pcm16) == 0 or not (0 <= mic_id < self._n):
            return
        with self._lock:
            q = self._queues[mic_id]
            q.append(pcm16)
            self._qlen[mic_id] += len(pcm16)
            # 积压保护：突发/漂移下丢最老数据，保时间轴不失真
            max_samples = int(QUEUE_MAX_S * self._rate)
            while self._qlen[mic_id] > max_samples and q:
                dropped = q.popleft()
                self._qlen[mic_id] -= len(dropped)

    def get_session_path(self) -> str:
        return str(self.path)

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._mix_loop, name="session-recorder", daemon=True
        )
        self._thread.start()
        logger.info(f"会话录制已启动 → {self.path}（gate 后有声混音，静音不写盘）")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            self._fh.close()
        except Exception:
            pass

    def _mix_loop(self) -> None:
        while not self._stop.is_set():
            time.sleep(TICK_S)
            mixed: Optional[np.ndarray] = None
            max_len = 0
            with self._lock:
                for i in range(self._n):
                    take = self._tick_samples
                    parts = []
                    q = self._queues[i]
                    while take > 0 and q:
                        seg = q.popleft()
                        if len(seg) > take:
                            q.appendleft(seg[take:])
                            seg = seg[:take]
                        parts.append(seg)
                        take -= len(seg)
                    if not parts:
                        continue
                    lane = np.concatenate(parts).astype(np.int32)
                    self._qlen[i] -= len(lane)
                    if mixed is None:
                        mixed = np.zeros(self._tick_samples, dtype=np.int32)
                    mixed[: len(lane)] += lane
                    max_len = max(max_len, len(lane))
            if mixed is None or max_len == 0:
                continue  # 本 tick 全路无声（gate 关闭）→ 不写盘，录声音不录空气
            out = np.clip(mixed[:max_len], -32768, 32767).astype(np.int16)
            try:
                self._fh.write(out.tobytes())
                self._fh.flush()
                self.written_bytes += out.nbytes
            except Exception as e:
                logger.warning(f"录音写盘失败: {e}")

    @staticmethod
    def _cleanup_old() -> None:
        try:
            files = sorted(
                RECORD_DIR.glob("session-*.pcm"), key=os.path.getmtime, reverse=True
            )
            for f in files[KEEP_SESSIONS - 1:]:
                f.unlink()
                logger.info(f"清理旧会话录音: {f.name}")
        except OSError as e:
            logger.warning(f"旧录音清理失败: {e}")


class _ExportHandler(BaseHTTPRequestHandler):
    """GET /audio/export.wav → 会话 PCM 文件流式加 WAV 头返回（?part=N 切片）。"""

    recorder_ref: "SessionRecorder | None" = None  # 由模块 start() 注入
    sample_rate: int = 16000
    _WAV_PART_MAX = 4 * 1024 ** 3 - 4096  # RIFF 32-bit size 上限，留头部余量

    def log_message(self, fmt, *args):
        pass  # 静默 access log

    def do_HEAD(self):
        # 前端"导出原音"按钮先 HEAD 探活再触发下载
        self.send_response(200 if self.recorder_ref is not None else 503)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if self.path.startswith("/audio/export.wav"):
            return self._serve_wav()
        self.send_error(404)

    def _serve_wav(self):
        rec = self.recorder_ref
        path = rec.get_session_path() if rec is not None else None
        size = os.path.getsize(path) if path and os.path.exists(path) else 0
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        if size == 0:
            # 尚无有声内容：返回 0 秒空 WAV（下载成功但为空），比 404 体验顺
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", "44")
            self.send_header(
                "Content-Disposition", f'attachment; filename="audio-{stamp}-empty.wav"'
            )
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                self.wfile.write(self._wav_header(self.sample_rate, 0))
            except (BrokenPipeError, ConnectionResetError, OSError):
                pass
            return
        qs = parse_qs(urlparse(self.path).query)
        try:
            part = int(qs.get("part", ["0"])[0])
        except ValueError:
            part = 0
        parts = max(1, math.ceil(size / self._WAV_PART_MAX))
        if part < 0 or part >= parts:
            self.send_response(416)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        offset = part * self._WAV_PART_MAX
        data_len = min(self._WAV_PART_MAX, size - offset)
        suffix = f"-part{part + 1}of{parts}" if parts > 1 else ""
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(44 + data_len))
        self.send_header(
            "Content-Disposition", f'attachment; filename="audio-{stamp}{suffix}.wav"'
        )
        self.send_header("X-Audio-Parts", str(parts))  # 前端据此循环下多片
        self.send_header("Access-Control-Expose-Headers", "X-Audio-Parts")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(self._wav_header(self.sample_rate, data_len))
            with open(path, "rb") as f:
                f.seek(offset)
                remaining = data_len
                while remaining > 0:
                    chunk = f.read(min(1 << 20, remaining))  # 1MB/次
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    remaining -= len(chunk)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    @staticmethod
    def _wav_header(rate: int, data_len: int) -> bytes:
        """44 字节 WAV 头（int16 mono）。流式用，不能用 wave 模块（需 seekable）。"""
        return struct.pack(
            "<4sI4s4sIHHIIHH4sI",
            b"RIFF", 36 + data_len, b"WAVE",
            b"fmt ", 16, 1, 1, rate, rate * 2, 2, 16,
            b"data", data_len,
        )


def start_export_http(recorder: SessionRecorder) -> Optional[ThreadingHTTPServer]:
    """启 :5052 导出服务。绑定失败（如与 audio_processor 共存形态端口被占）
    只 warning 不崩——录制照常，导出走占用方。"""
    _ExportHandler.recorder_ref = recorder
    _ExportHandler.sample_rate = recorder._rate
    try:
        srv = ThreadingHTTPServer(("0.0.0.0", EXPORT_HTTP_PORT), _ExportHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        logger.info(
            f"原音导出 HTTP 已启动: http://0.0.0.0:{EXPORT_HTTP_PORT}/audio/export.wav"
        )
        return srv
    except Exception as e:
        logger.warning(f"原音导出 HTTP 启动失败 :{EXPORT_HTTP_PORT} → {e}")
        return None
