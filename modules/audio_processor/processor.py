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
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import scipy.signal as signal
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
    # 发言人区分（回流自 av_understanding_mac S3）：final 段的近似 PCM + 段 ID，
    # 由 main.py SegmentSink 落盘并发 av/audio/segment 给 speaker_diarizer。
    # 默认值保证其它构造点（mic_warning / local_offline）不用改。
    segment_id: str = ""
    start_ms: int = 0
    end_ms: int = 0
    pcm_bytes: bytes | None = None


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

        # 降噪前处理流水线（流式适配版）：
        # - 100Hz 10阶 Butterworth 高通：去 50/60Hz 电源嗡 + 空调低频共振 + 风噪 buffeting
        # - 1.5x 增益：弱声场补偿（demo 3588 同款）
        # sosfilt running state 跨 chunk 续帧，避免每 60ms 段头出现 filter transient 咔嗒声。
        # noisereduce 谱减法是 offline 段处理（demo 用 1.2s VAD 切段），不适合我们的流式架构。
        self._denoise_hp_sos = signal.butter(10, 100, btype='hp', fs=self.sample_rate, output='sos')
        self._denoise_hp_zi = np.zeros((self._denoise_hp_sos.shape[0], 2), dtype=np.float32)
        self._denoise_gain = 1.5

        # local_offline 参数
        self.silence_threshold = float(funasr.get("silence_threshold", 0.008))
        self.silence_chunks = int(funasr.get("silence_duration_ms", 600)) // 50
        self._audio_queue: "queue.Queue[tuple[np.ndarray, float]]" = queue.Queue()
        self._model = None

        self._stop_event = threading.Event()
        self._callback: Optional[Callable[[TranscriptEvent], None]] = None
        self._seq = 0
        # 段 PCM 缓冲：上一条 final → 本条 final 之间的 PCM 作为该 final 的近似音频段
        # （FunASR 2pass 不回传原始音频边界；近似段对声纹嵌入够用，见 mac 仓 S2 标定）
        self._segment_pcm_chunks: list[bytes] = []
        self._segment_start_ts = time.time()
        self._segment_lock = threading.Lock()
        self._last_partial = ""
        # 诊断：PCM 帧计数（macOS 静默拒绝麦克风时 sd.InputStream 假成功但 callback 永不触发）
        self._pcm_frames_received = 0
        self._mic_self_check_done = False

        # 全音频落盘（CR-DIG7201 生产版）：采集边写盘，一场会（start→stop）一个文件。
        # 不在内存存全量——几小时会议几百 MB、5G 上限=5G 内存，3588 会 OOM。
        # 磁盘 data/audio/session-<ts>.pcm 持久化，5G 总上限滚动删最老会话文件。
        # 导出时（get_session_path）加 WAV 头返回；单场 >4G（WAV 上限）由 web 层切片。
        self._audio_dir = Path(__file__).resolve().parents[2] / "data" / "audio"
        self._audio_dir.mkdir(parents=True, exist_ok=True)
        self._audio_total_cap = 5 * 1024 ** 3   # 5G 总上限（约 44 小时 @16kHz）
        self._session_file = None               # 当前会话文件句柄（写入中）
        self._session_path: Optional[Path] = None
        self._session_lock = threading.Lock()

    # ── 启动/停止 ─────────────────────────────────────────────────────

    def start(self, callback: Optional[Callable[[TranscriptEvent], None]] = None, listening_callback=None):
        self._callback = callback
        # 重置 stop_event + 上次会话残留 state，防 disable→enable 时新 ws/watchdog/send 线程
        # 一启动就因 _stop_event 仍 set 而即时退出（5/11 销售来访 15:05 enable 后 6.5min 静默假活的根因）。
        self._stop_event.clear()
        # send_q 在 stop() 时 put 了 None 哨兵 + 可能还有未发的 PCM；不 drain 重启第一个被
        # _send_loop 取走的就是 None → 发 is_speaking:false 给 funasr → server 视为流结束。
        while True:
            try:
                self._send_q.get_nowait()
            except queue.Empty:
                break
        self._pcm_frames_received = 0
        self._mic_self_check_done = False
        self._last_partial = ""
        # 全音频落盘：一次 start（开机/点开始）= 一场会，开新会话文件
        self._open_session_file()
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
        # 全音频落盘：一场会结束，关会话文件（下次 start 开新场）
        self._close_session_file()
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

        # 持续 watchdog：sd.InputStream 长时间运行后偶现 callback 假死（sounddevice 已知坑），
        # 表现是进程仍在但 _pcm_frames_received 不再增。30s 不增 → 主动 os._exit(1) 让
        # supervisor 重拉子进程恢复。修复用户实测"时间稍长后语音转写停止；刷新不能解决；
        # 重启后好用"的静默挂死现象（5/9 真实场景观察）。
        threading.Thread(target=self._mic_watchdog, daemon=True, name="mic_watchdog").start()

    def _mic_watchdog(self):
        """每 5s 巡检 PCM 帧计数；30s 不增 → mic stream 假死，os._exit 让 supervisor 重拉。"""
        # 启动初期跳过，等 mic 真正就位
        time.sleep(15)
        last_count = self._pcm_frames_received
        last_change = time.time()
        while not self._stop_event.is_set():
            cur = self._pcm_frames_received
            if cur != last_count:
                last_count = cur
                last_change = time.time()
            else:
                idle_sec = time.time() - last_change
                if idle_sec > 30:
                    import os
                    logger.error(
                        f"⚠️ mic watchdog: PCM 帧计数 {idle_sec:.0f}s 无变化 (count={cur})；"
                        f"麦克风 stream 假死，退出让 supervisor 重拉子进程恢复"
                    )
                    os._exit(1)
            time.sleep(5)

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
        # 降噪流水线：HP 滤波（去低频嗡/风噪/电源嗡）+ 1.5x 增益。
        # 流式 sosfilt 续 state，跨 chunk 无 transient；不替代 FunASR 内部 VAD/特征。
        samples_f32 = indata[:, 0].astype(np.float32) / 32768.0
        filtered_f32, self._denoise_hp_zi = signal.sosfilt(
            self._denoise_hp_sos, samples_f32, zi=self._denoise_hp_zi
        )
        gained_f32 = filtered_f32 * self._denoise_gain
        pcm_i16 = np.clip(gained_f32 * 32768.0, -32768.0, 32767.0).astype(np.int16)
        pcm = pcm_i16.tobytes()
        # 写会话文件（旁路 tee，不影响 send_q 流向 FunASR）。全音频落盘不吞异常，
        # 写盘失败（磁盘满等）直接报错让人看到（转写不受影响，仍走 send_q）。
        with self._session_lock:
            if self._session_file is not None:
                self._session_file.write(pcm)
        with self._segment_lock:
            self._segment_pcm_chunks.append(pcm)
        try:
            self._send_q.put_nowait(pcm)
        except queue.Full:
            try:
                self._send_q.get_nowait()
                self._send_q.put_nowait(pcm)
            except (queue.Empty, queue.Full):
                pass

    # ── 全音频会话文件（CR-DIG7201 生产版）─────────────────────────────
    def _open_session_file(self):
        """开新会话文件（一场会 = start→stop）。开新前先按 5G 上限滚动腾空间。"""
        with self._session_lock:
            if self._session_file is not None:
                return
            self._enforce_disk_cap()
            stamp = time.strftime("%Y%m%d-%H%M%S")
            self._session_path = self._audio_dir / f"session-{stamp}.pcm"
            self._session_file = open(self._session_path, "wb")
            self._session_t0 = time.time()  # 段事件 start_ms/end_ms 的零点
            logger.info(f"音频落盘会话开始: {self._session_path}")

    def _close_session_file(self):
        with self._session_lock:
            if self._session_file is not None:
                try:
                    self._session_file.close()
                except Exception as e:
                    logger.warning(f"关闭会话文件失败: {e}")
                self._session_file = None

    def _enforce_disk_cap(self):
        """所有会话文件总和超 5G → 删最老（保留当前会话，至少留 1 个）。"""
        files = sorted(self._audio_dir.glob("session-*.pcm"),
                       key=lambda p: p.stat().st_mtime)
        total = sum(p.stat().st_size for p in files)
        while total > self._audio_total_cap and len(files) > 1:
            oldest = files.pop(0)
            sz = oldest.stat().st_size
            try:
                oldest.unlink()
                total -= sz
                logger.info(f"5G 上限滚动删除最老会话: {oldest.name}")
            except Exception as e:
                logger.warning(f"滚动删除失败 {oldest.name}: {e}")
                break

    def get_session_path(self) -> Optional[str]:
        """返回当前会话文件路径（供 web 层加 WAV 头导出）。先 flush 保证已写数据可读。"""
        with self._session_lock:
            if self._session_file is not None:
                try:
                    self._session_file.flush()
                except Exception:
                    pass
            return str(self._session_path) if self._session_path else None

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

    def _close_pcm_segment(self) -> tuple[bytes, int, int]:
        """取出当前 utterance 的近似 PCM 段并重置缓冲；返回 (pcm, start_ms, end_ms)（相对本次 start）。"""
        now = time.time()
        with self._segment_lock:
            pcm = b"".join(self._segment_pcm_chunks)
            start_ts = self._segment_start_ts
            self._segment_pcm_chunks = []
            self._segment_start_ts = now
        t0 = getattr(self, "_session_t0", None) or start_ts
        return pcm, max(0, int((start_ts - t0) * 1000)), max(0, int((now - t0) * 1000))

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

            segment_id = f"aud-{self._seq:06d}"
            pcm_bytes, start_ms, end_ms = self._close_pcm_segment() if is_final else (None, 0, 0)
            ev = TranscriptEvent(
                text=text,
                is_final=is_final,
                seq_id=self._seq,
                ts=time.time(),
                raw_mode=raw_mode or ("final" if is_final else "partial"),
                segment_id=segment_id,
                start_ms=start_ms,
                end_ms=end_ms,
                pcm_bytes=pcm_bytes,
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
