"""
audio_processor.py
语音处理
- websocket_2pass: FunASR runtime 流式 2pass，支持 partial/final
- local_offline: 本地 SenseVoiceSmall，按静音切段后输出 final
"""
import asyncio
import collections
import json
import logging
import queue
import re
import threading
import time
from dataclasses import dataclass
from functools import partial
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<\|[^|]+\|>")
_websockets_mod = None


@dataclass
class TranscriptEvent:
    text: str
    is_final: bool
    seq_id: int
    ts: float
    raw_mode: str


def _clean_tags(text: str) -> str:
    return _TAG_RE.sub("", text).strip()


def _get_websockets():
    global _websockets_mod
    if _websockets_mod is not None:
        return _websockets_mod
    import websockets as _ws
    _websockets_mod = _ws
    return _ws


class AudioProcessor:
    def __init__(self, cfg: dict):
        funasr = cfg.get("funasr", {})

        self.mode = str(funasr.get("mode", "websocket_2pass"))
        self.url = funasr.get("url", "ws://127.0.0.1:10095")
        self.sample_rate = int(funasr.get("sample_rate", 16000))

        # websocket_2pass 参数
        self.chunk_size = list(funasr.get("chunk_size", [5, 10, 5]))
        self.chunk_interval = int(funasr.get("chunk_interval", 10))
        self.chunk_ms = int(funasr.get("chunk_interval_ms", 60))
        self.hotwords = str(funasr.get("hotwords", ""))
        self.use_itn = bool(funasr.get("use_itn", True))
        self._frame_samples = int(self.sample_rate * self.chunk_ms / 1000)
        self._send_q: "queue.Queue[Optional[bytes]]" = queue.Queue(maxsize=64)
        self._loop_thread: Optional[threading.Thread] = None
        self._stream: Optional[sd.InputStream] = None

        # local_offline 参数
        self.silence_threshold = float(funasr.get("silence_threshold", 0.008))
        self.silence_chunks = int(funasr.get("silence_duration_ms", 600)) // 50
        self._audio_queue: "queue.Queue[tuple[np.ndarray, float]]" = queue.Queue()
        self._model = None

        self._stop_event = threading.Event()
        self._callback: Optional[Callable[[TranscriptEvent], None]] = None
        self._seq = 0
        self._last_partial = ""
        # 诊断：PCM 帧计数（macOS 静默拒绝麦克风时 sd.InputStream 假成功但 callback 永不触发）
        self._pcm_frames_received = 0
        self._mic_self_check_done = False

        # PCM 环形缓冲：留最近 N 秒原音，前端"导出原音"按钮调 get_pcm_buffer 打包 WAV。
        # int16 mono @ sample_rate × N 秒 × 2 byte ≈ 9.6MB（5min @ 16kHz），可接受。
        # 不持久化磁盘（演示场景），supervisor 重启就丢；如客户要长录改 _pcm_ring_seconds。
        self._pcm_ring_seconds = 300
        self._pcm_ring_max_bytes = self.sample_rate * 2 * self._pcm_ring_seconds
        self._pcm_ring: "collections.deque[bytes]" = collections.deque()
        self._pcm_ring_total = 0
        self._pcm_ring_lock = threading.Lock()

    # ── 启动/停止 ─────────────────────────────────────────────────────

    def start(self, callback: Optional[Callable[[TranscriptEvent], None]] = None):
        self._callback = callback
        if self.mode == "local_offline":
            self._start_local_offline()
            return
        if self.mode == "websocket_2pass":
            self._start_websocket_2pass()
            return
        raise ValueError(f"未知音频模式: {self.mode}")

    def _fallback_to_local_offline(self, reason: str):
        """WS 不可用时自动降级到本地 SenseVoiceSmall，保证转写仍可用（无 partial）。"""
        if self.mode == "local_offline":
            return
        logger.warning(f"FunASR WS 不可用，降级到 local_offline：{reason}")
        self.mode = "local_offline"
        self._stop_event.clear()
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None
        self._start_local_offline()

    def stop(self):
        self._stop_event.set()
        try:
            self._send_q.put_nowait(None)
        except queue.Full:
            pass
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
        logger.info("音频处理器已停止")

    # ── websocket_2pass ───────────────────────────────────────────────

    def _start_websocket_2pass(self):
        try:
            _get_websockets()
        except ModuleNotFoundError:
            self._fallback_to_local_offline("缺少 websockets 包")
            return

        self._stream = sd.InputStream(
            samplerate=self.sample_rate,
            channels=1,
            dtype="int16",
            blocksize=self._frame_samples,
            callback=self._on_audio_pcm,
            latency="low",
        )
        self._stream.start()
        logger.info(f"录音流已启动 ({self.sample_rate}Hz, {self.chunk_ms}ms/帧)")

        self._loop_thread = threading.Thread(target=self._run_ws_loop, daemon=True)
        self._loop_thread.start()
        logger.info(f"FunASR 2pass 客户端已启动 (url={self.url})")

        # 启动 5 秒后自检：若 0 帧 → macOS 静默拒绝麦克风（典型：终端无授权 / 设备被独占）
        threading.Thread(target=self._mic_self_check, daemon=True).start()

    def _mic_self_check(self):
        """sd.InputStream.start() 在 macOS 上对未授权进程会静默成功但 callback 永不触发。
        启动后等 5s 看 _pcm_frames_received，0 → 报警 + 推 mqtt 状态给前端显示。
        """
        if self._mic_self_check_done:
            return
        self._mic_self_check_done = True
        time.sleep(5)
        frames = self._pcm_frames_received
        expected = int(5 * 1000 / max(self.chunk_ms, 1))  # 5s 应有 ~83 帧
        if frames < max(5, expected // 4):
            logger.error(
                f"[mic] 启动 5s 仅收到 {frames} 帧（应 ~{expected}） — "
                "macOS 麦克风没真正交付 PCM。可能原因：终端无麦克风权限 / 默认设备被独占 / 设备 disconnected。"
                "排查：系统设置→隐私→麦克风 / sd.query_devices()"
            )
            # 推一条诊断状态到 MQTT，前端可显示
            if self._callback is not None:
                try:
                    self._callback(TranscriptEvent(
                        text="[mic] 5s 未收到 PCM — 检查麦克风权限或设备占用",
                        is_final=True, seq_id=-1, ts=time.time(), raw_mode="mic_warning",
                    ))
                except Exception:
                    pass
        else:
            logger.info(f"[mic] 自检通过：5s 收到 {frames} 帧")

    def _on_audio_pcm(self, indata: np.ndarray, frames: int, time_info, status):
        if status:
            logger.debug(f"audio status: {status}")
        self._pcm_frames_received += 1
        if self._pcm_frames_received == 1:
            logger.info(f"[mic] 第 1 帧 PCM 已收到 ({frames} samples) — 麦克风正常工作")
        pcm = indata[:, 0].tobytes()
        # 写环形 buffer（旁路 tee，不影响 send_q 流向 FunASR）
        with self._pcm_ring_lock:
            self._pcm_ring.append(pcm)
            self._pcm_ring_total += len(pcm)
            while self._pcm_ring_total > self._pcm_ring_max_bytes and self._pcm_ring:
                self._pcm_ring_total -= len(self._pcm_ring.popleft())
        try:
            self._send_q.put_nowait(pcm)
        except queue.Full:
            try:
                self._send_q.get_nowait()
                self._send_q.put_nowait(pcm)
            except (queue.Empty, queue.Full):
                pass

    def get_pcm_buffer(self) -> bytes:
        """返回当前环形 buffer 的 PCM 字节流（int16 mono @ sample_rate）。"""
        with self._pcm_ring_lock:
            return b"".join(self._pcm_ring)

    def _run_ws_loop(self):
        try:
            asyncio.run(self._supervise_ws())
        except Exception as e:
            logger.error(f"FunASR asyncio 线程退出: {e}")

    async def _supervise_ws(self):
        backoff = 1.0
        attempts = 0
        while not self._stop_event.is_set():
            try:
                await self._ws_session()
                backoff = 1.0
                attempts = 0
            except Exception as e:
                if self._stop_event.is_set():
                    return
                attempts += 1
                # 连续 5 次都连不上（≈30s），降级到本地离线，避免一直空转。
                if attempts >= 5:
                    self._fallback_to_local_offline(f"连续 {attempts} 次重连失败：{e}")
                    return
                logger.warning(f"FunASR WS 异常: {e}，{backoff:.1f}s 后重连")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 10.0)

    async def _ws_session(self):
        ws_lib = _get_websockets()
        async with ws_lib.connect(
            self.url,
            max_size=10 * 1024 * 1024,
            ping_interval=20,
            ping_timeout=20,
        ) as ws:
            logger.info(f"FunASR 已连接 {self.url}")
            await ws.send(json.dumps({
                "mode": "2pass",
                "chunk_size": self.chunk_size,
                "chunk_interval": self.chunk_interval,
                "audio_fs": self.sample_rate,
                "wav_name": "mic",
                "wav_format": "pcm",
                "is_speaking": True,
                "hotwords": self.hotwords,
                "itn": self.use_itn,
            }, ensure_ascii=False))

            send_task = asyncio.create_task(self._send_loop(ws))
            recv_task = asyncio.create_task(self._recv_loop(ws))
            done, pending = await asyncio.wait(
                {send_task, recv_task},
                return_when=asyncio.FIRST_EXCEPTION,
            )
            for task in pending:
                task.cancel()
            for task in done:
                exc = task.exception()
                if exc is not None:
                    raise exc

    async def _send_loop(self, ws):
        loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            try:
                pcm = await loop.run_in_executor(
                    None, partial(self._send_q.get, True, 0.5)
                )
            except queue.Empty:
                continue
            if pcm is None:
                try:
                    await ws.send(json.dumps({"is_speaking": False}))
                except Exception:
                    pass
                return
            await ws.send(pcm)

    async def _recv_loop(self, ws):
        async for raw in ws:
            if isinstance(raw, (bytes, bytearray)):
                continue
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            text = _clean_tags(msg.get("text", ""))
            if not text:
                continue

            raw_mode = str(msg.get("mode", ""))
            is_final = raw_mode.endswith("offline")

            if not is_final:
                if text == self._last_partial:
                    continue
                self._last_partial = text

            ev = TranscriptEvent(
                text=text,
                is_final=is_final,
                seq_id=self._seq,
                ts=time.time(),
                raw_mode=raw_mode or ("final" if is_final else "partial"),
            )

            if is_final:
                self._seq += 1
                self._last_partial = ""

            self._emit(ev)

    # ── local_offline ─────────────────────────────────────────────────

    def _start_local_offline(self):
        logger.info("加载 FunASR SenseVoiceSmall 模型...")
        import logging as funasr_log
        funasr_log.getLogger("funasr").setLevel(funasr_log.ERROR)

        # 本地缓存命中时直接用绝对路径，绕开 funasr 1.3.x 即使 disable_update=True 仍会做的
        # modelscope hub 探测（探测在离线/无网状态下会把进程拖崩）。
        from pathlib import Path
        from funasr import AutoModel
        cached = Path.home() / ".cache/modelscope/hub/models/iic/SenseVoiceSmall"
        model_id = str(cached) if (cached / "model.pt").exists() else "iic/SenseVoiceSmall"
        if model_id == str(cached):
            logger.info(f"使用本地缓存模型: {cached}")
        else:
            logger.warning("本地无 SenseVoiceSmall 缓存，将从 modelscope 首次下载（需联网）")
        self._model = AutoModel(
            model=model_id,
            trust_remote_code=True,
            disable_update=True,
        )
        logger.info("FunASR 模型加载完成")

        threading.Thread(target=self._run_local_offline, daemon=True).start()
        logger.info("音频处理器已启动 (mode=local_offline)")

    def _on_audio_float(self, indata, frames, time_info, status):
        samples = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(samples ** 2)))
        self._audio_queue.put((samples, rms))

    def _run_local_offline(self):
        chunk_samples = int(self.sample_rate * 50 / 1000)
        stream = None

        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=chunk_samples,
                callback=self._on_audio_float,
                latency="low",
            )
            stream.start()
            logger.info("录音流已启动")

            audio_buffer = []
            speaking = False
            silence_count = 0
            speech_count = 0

            while not self._stop_event.is_set():
                try:
                    samples, rms = self._audio_queue.get(timeout=0.1)
                except queue.Empty:
                    continue

                is_speech = rms > self.silence_threshold

                if is_speech:
                    silence_count = 0
                    speech_count += 1
                    speaking = True
                    audio_buffer.append(samples)
                elif speaking:
                    audio_buffer.append(samples)
                    silence_count += 1

                    if silence_count >= self.silence_chunks:
                        if speech_count >= 3:
                            self._recognize_offline(np.concatenate(audio_buffer))

                        speaking = False
                        speech_count = 0
                        silence_count = 0
                        audio_buffer = []

        except Exception as e:
            logger.error(f"音频设备错误: {e}")
        finally:
            if stream is not None:
                stream.stop()
                stream.close()
            logger.info("录音流已关闭")

    def _recognize_offline(self, audio_np: np.ndarray):
        try:
            res = self._model.generate(input=audio_np, batch_size=1)
            if not res:
                return
            text = _clean_tags(res[0].get("text", ""))
            if not text or len(text) < 2:
                return
            ev = TranscriptEvent(
                text=text,
                is_final=True,
                seq_id=self._seq,
                ts=time.time(),
                raw_mode="offline",
            )
            self._seq += 1
            self._emit(ev)
        except Exception as e:
            logger.error(f"识别异常: {e}")

    def _emit(self, ev: TranscriptEvent):
        if self._callback is None:
            return
        try:
            self._callback(ev)
        except Exception as e:
            logger.error(f"transcript 回调异常: {e}")
