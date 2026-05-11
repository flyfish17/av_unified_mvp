"""
processor_arm.py
ARM 端（RK3588）转写实现 — 仿 demo pro_av_dashboard_NPU.py 同款架构：

- FunASR AutoModel(SenseVoiceSmall) CPU 推理（**非流式**，按 VAD 分段送整段）
- 100Hz HP butter + 1.5x gain 降噪（与 Mac processor.py 一致）
- VAD 简化：rms > silence_threshold 进 speaking，连续 silence_chunks 静音后定段送 ASR

与 Mac processor.AudioProcessor 接口对齐：start(callback) / stop() / get_pcm_buffer() / sample_rate
无 2pass-online partial — 前端只收到 is_final=True 事件（raw_mode="sense_voice_offline"）。
前端 transcript_seq.js / dashboard.js 在 ARM 端表现为"段落级追加"而非"逐字蹦"。

Mic 设备选择：query_devices 找 C920 / Logitech 字串；找不到 fallback plughw:2,0（demo 同款）。
"""
import collections
import logging
import queue
import re
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import scipy.signal as signal
import sounddevice as sd

from modules.audio_processor.processor import TranscriptEvent

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<\|[^|]+\|>")


def _find_logitech_device() -> object:
    """优先 C920/Logitech USB mic，找不到 fallback ALSA plughw:2,0（demo 同款策略）。"""
    try:
        devices = sd.query_devices()
        for i, dev in enumerate(devices):
            name = dev.get("name", "")
            if ("C920" in name or "Logitech" in name) and dev.get("max_input_channels", 0) > 0:
                logger.info(f"[mic] 选中 USB 麦克风: {name} (index={i})")
                return i
    except Exception as e:
        logger.warning(f"[mic] query_devices 异常: {e}")
    logger.info("[mic] 未找到 Logitech，fallback plughw:2,0")
    return "plughw:2,0"


class AudioProcessorARM:
    """ARM 端转写引擎。接口与 Mac processor.AudioProcessor 对齐。"""

    def __init__(self, audio_cfg: dict):
        funasr_cfg = audio_cfg.get("funasr", {})
        self.sample_rate = int(funasr_cfg.get("sample_rate", 16000))
        self.chunk_ms = int(funasr_cfg.get("chunk_interval_ms", 60))
        self._frame_samples = int(self.sample_rate * self.chunk_ms / 1000)

        # VAD 参数
        self.silence_threshold = float(funasr_cfg.get("silence_threshold", 0.01))
        silence_ms = int(funasr_cfg.get("silence_duration_ms", 500))
        self.silence_chunks = max(1, silence_ms // self.chunk_ms)
        # 至少 0.3s 才送 ASR（防短促咳嗽噪声送进模型）
        self.min_speech_chunks = max(1, 300 // self.chunk_ms)
        # 最长 15s 强制定段（防长段失控）
        self.max_speech_chunks = 15000 // self.chunk_ms

        # 降噪流水线（与 Mac processor.py 一致）
        self._denoise_hp_sos = signal.butter(10, 100, btype='hp', fs=self.sample_rate, output='sos')
        self._denoise_hp_zi = np.zeros((self._denoise_hp_sos.shape[0], 2), dtype=np.float32)
        self._denoise_gain = float(funasr_cfg.get("denoise_gain", 1.5))

        # SenseVoiceSmall 模型（懒加载）
        self._model = None
        default_path = "/home/firefly/creator_ai_demo/SenseVoiceSmall"
        self._model_path = funasr_cfg.get("sense_voice_path", default_path)

        # mic 设备（可配置）
        self._mic_device = funasr_cfg.get("mic_device") or _find_logitech_device()

        # 运行状态
        self._stop_event = threading.Event()
        self._callback: Optional[Callable[[TranscriptEvent], None]] = None
        self._seq = 0
        self._stream: Optional[sd.InputStream] = None
        self._audio_q: "queue.Queue[tuple[np.ndarray, float]]" = queue.Queue(maxsize=256)
        self._worker_thread: Optional[threading.Thread] = None

        # PCM 环形 buffer（5min @ 16kHz int16 = 9.6MB）— 与 Mac 一致供 /audio/export.wav 用
        self._pcm_ring: collections.deque = collections.deque()
        self._pcm_ring_lock = threading.Lock()
        self._pcm_ring_total = 0
        self._pcm_ring_seconds = 300
        self._pcm_ring_max_bytes = self.sample_rate * 2 * self._pcm_ring_seconds

        # 诊断
        self._pcm_frames_received = 0
        # rms debug：每 N 帧 print 一次平均 rms，便于诊断"mic 是否收到声音"+"阈值是否合理"
        # 60ms/帧 × 50 = 3s 一行；rms 0.01 是 VAD speaking 阈值
        self._rms_debug_interval = 50
        self._rms_debug_buf: list = []

    # ── Public API ────────────────────────────────────────────────────

    def start(self, callback: Optional[Callable[[TranscriptEvent], None]] = None) -> None:
        self._callback = callback
        self._stop_event.clear()
        # worker 先起，准备好接队列再开 mic（避免 mic 帧涌入 + 队列还没 drain）
        self._worker_thread = threading.Thread(
            target=self._worker_loop, name="asr_worker", daemon=True
        )
        self._worker_thread.start()
        self._stream = sd.InputStream(
            device=self._mic_device,
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self._frame_samples,
            callback=self._on_audio_pcm,
            latency="low",
        )
        self._stream.start()
        logger.info(
            f"ARM 转写已启动: SenseVoiceSmall + VAD + 流式降噪 "
            f"({self.sample_rate}Hz, {self.chunk_ms}ms/帧, silence>{self.silence_chunks*self.chunk_ms}ms 定段)"
        )

    def stop(self) -> None:
        self._stop_event.set()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception as e:
                logger.warning(f"stream close 异常: {e}")
            self._stream = None
        if self._worker_thread is not None:
            self._worker_thread.join(timeout=3)
            self._worker_thread = None
        logger.info("ARM 转写已停止")

    def get_pcm_buffer(self) -> bytes:
        with self._pcm_ring_lock:
            return b"".join(self._pcm_ring)

    # ── Internals ─────────────────────────────────────────────────────

    def _load_model(self) -> None:
        if self._model is not None:
            return
        if not Path(self._model_path).exists():
            raise FileNotFoundError(
                f"SenseVoiceSmall 模型不存在: {self._model_path} "
                "（demo 的模型路径默认 /home/firefly/creator_ai_demo/SenseVoiceSmall，"
                "在 config audio.funasr.sense_voice_path 改）"
            )
        from funasr import AutoModel
        logger.info(f"加载 SenseVoiceSmall: {self._model_path}")
        t0 = time.time()
        self._model = AutoModel(
            model=self._model_path,
            trust_remote_code=True,
            disable_update=True,
            remote_rdonly=True,
        )
        logger.info(f"SenseVoiceSmall 加载完成（{time.time()-t0:.1f}s）")

    def _on_audio_pcm(self, indata: np.ndarray, frames: int, time_info, status):
        if status:
            logger.debug(f"audio status: {status}")
        self._pcm_frames_received += 1
        if self._pcm_frames_received == 1:
            logger.info(f"[mic] 第 1 帧 PCM 收到 ({frames} samples) — 麦克风正常")

        # 降噪流水线（与 Mac processor.py 同款）：HP filter + gain
        samples_f32 = indata[:, 0].astype(np.float32) / 32768.0
        filtered_f32, self._denoise_hp_zi = signal.sosfilt(
            self._denoise_hp_sos, samples_f32, zi=self._denoise_hp_zi
        )
        gained_f32 = filtered_f32 * self._denoise_gain
        rms = float(np.sqrt(np.mean(gained_f32 ** 2)))
        # rms debug：每 N 帧 print 一次 min/max/mean，看 mic 是否真在收声 + 阈值合理性
        self._rms_debug_buf.append(rms)
        if len(self._rms_debug_buf) >= self._rms_debug_interval:
            rms_arr = np.array(self._rms_debug_buf)
            logger.info(
                f"[rms] {self._rms_debug_interval}帧({self._rms_debug_interval*self.chunk_ms}ms): "
                f"min={rms_arr.min():.4f} mean={rms_arr.mean():.4f} max={rms_arr.max():.4f} "
                f"(阈值 {self.silence_threshold:.4f})"
            )
            self._rms_debug_buf = []

        # 环形 buffer（int16 字节）— 供 /audio/export.wav
        pcm_i16 = np.clip(gained_f32 * 32768.0, -32768.0, 32767.0).astype(np.int16)
        pcm_bytes = pcm_i16.tobytes()
        with self._pcm_ring_lock:
            self._pcm_ring.append(pcm_bytes)
            self._pcm_ring_total += len(pcm_bytes)
            while self._pcm_ring_total > self._pcm_ring_max_bytes and self._pcm_ring:
                self._pcm_ring_total -= len(self._pcm_ring.popleft())

        # 推 worker（float32 给 ASR）
        try:
            self._audio_q.put_nowait((gained_f32.copy(), rms))
        except queue.Full:
            # 丢最老一帧，留新帧
            try:
                self._audio_q.get_nowait()
                self._audio_q.put_nowait((gained_f32.copy(), rms))
            except (queue.Empty, queue.Full):
                pass

    def _worker_loop(self) -> None:
        try:
            self._load_model()
        except Exception as e:
            logger.error(f"模型加载失败，worker 退出: {e}")
            return

        buf = []
        speaking = False
        silence_count = 0
        speech_count = 0
        prev_samples = None  # 句头 50ms 提前包含，防吞首字（demo 同款）

        while not self._stop_event.is_set():
            try:
                samples, rms = self._audio_q.get(timeout=0.2)
            except queue.Empty:
                continue

            if rms > self.silence_threshold:
                if not speaking and prev_samples is not None:
                    buf.append(prev_samples)
                buf.append(samples)
                speech_count += 1
                silence_count = 0
                speaking = True
            elif speaking:
                buf.append(samples)
                silence_count += 1
                if silence_count >= self.silence_chunks or len(buf) >= self.max_speech_chunks:
                    if speech_count >= self.min_speech_chunks:
                        self._infer_segment(np.concatenate(buf))
                    buf = []
                    speaking = False
                    silence_count = 0
                    speech_count = 0

            if not speaking:
                prev_samples = samples

    def _infer_segment(self, audio_f32: np.ndarray) -> None:
        try:
            t0 = time.time()
            res = self._model.generate(input=audio_f32, batch_size=1)
            elapsed = time.time() - t0
            if not res or len(res) == 0:
                return
            text = _TAG_RE.sub("", res[0].get("text", "")).strip()
            if not text:
                return
            logger.info(f"[final] {text} ({elapsed*1000:.0f}ms, {len(audio_f32)/self.sample_rate:.1f}s 音频)")
            ev = TranscriptEvent(
                text=text,
                is_final=True,
                seq_id=self._seq,
                ts=time.time(),
                raw_mode="sense_voice_offline",
            )
            self._seq += 1
            if self._callback:
                try:
                    self._callback(ev)
                except Exception as e:
                    logger.error(f"callback 异常: {e}")
        except Exception as e:
            logger.error(f"识别异常 {type(e).__name__}: {e}")
