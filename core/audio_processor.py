"""
audio_processor.py
语音处理 - 使用 FunASR 本地模型（离线推理）
"""
import logging
import queue
import re
import threading
from typing import Callable

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


def _clean_tags(text: str) -> str:
    return re.sub(r"<\|[^|]+\|>", "", text).strip()


class AudioProcessor:
    def __init__(self, cfg: dict):
        funasr = cfg.get("funasr", {})
        self.sample_rate      = funasr.get("sample_rate", 16000)
        self.silence_threshold = funasr.get("silence_threshold", 0.008)
        self.silence_chunks   = funasr.get("silence_duration_ms", 600) // 50  # 50ms per chunk

        self._audio_queue = queue.Queue()
        self._stop_event  = threading.Event()
        self._callback: Callable[[str], None] | None = None
        self._model = None

    # ── 启动/停止 ─────────────────────────────────────────────────────

    def start(self, callback: Callable[[str], None] = None):
        """启动录音和识别线程"""
        self._callback = callback

        # 加载 FunASR 本地模型
        logger.info("加载 FunASR SenseVoiceSmall 模型...")
        import logging as funasr_log
        funasr_log.getLogger("funasr").setLevel(funasr_log.ERROR)

        from funasr import AutoModel
        self._model = AutoModel(
            model="iic/SenseVoiceSmall",
            trust_remote_code=True,
            disable_update=True
        )
        logger.info("FunASR 模型加载完成")

        threading.Thread(target=self._run, daemon=True).start()
        logger.info("音频处理器已启动")

    def stop(self):
        self._stop_event.set()

    # ── 内部逻辑 ──────────────────────────────────────────────────────

    def _audio_callback(self, indata, frames, time_info, status):
        samples = indata[:, 0].copy()
        rms = float(np.sqrt(np.mean(samples ** 2)))
        self._audio_queue.put((samples, rms))

    def _run(self):
        chunk_samples = int(self.sample_rate * 50 / 1000)  # 50ms
        stream = None

        try:
            stream = sd.InputStream(
                samplerate=self.sample_rate,
                channels=1,
                dtype="float32",
                blocksize=chunk_samples,
                callback=self._audio_callback,
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
                        if speech_count >= 3:  # 至少150ms有声音
                            audio_np = np.concatenate(audio_buffer)
                            try:
                                res = self._model.generate(input=audio_np, batch_size=1)
                                if res and len(res) > 0:
                                    text = _clean_tags(res[0].get("text", ""))
                                    if text and len(text) >= 2 and self._callback:
                                        self._callback(text)
                            except Exception as e:
                                logger.error(f"识别异常: {e}")

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

