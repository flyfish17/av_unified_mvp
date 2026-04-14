#!/usr/bin/env python3
"""
modules/audio_processor/processor.py
语音处理模块 - 独立进程版本
通过MQTT发布转写事件，同时保留原有callback接口
"""
import logging
import queue
import re
import threading
import time
from typing import Callable, Optional

import numpy as np
import sounddevice as sd

logger = logging.getLogger(__name__)


def _clean_tags(text: str) -> str:
    return re.sub(r"<\|[^|]+\|>", "", text).strip()


class AudioProcessor:
    """
    音频处理模块

    重构后支持两种模式:
    1. callback模式 (向后兼容): start(callback=func)
    2. MQTT模式: set_mqtt_publisher(publish_func)
    """

    def __init__(self, cfg: dict):
        funasr = cfg.get("funasr", {})
        self.sample_rate = funasr.get("sample_rate", 16000)
        self.silence_threshold = funasr.get("silence_threshold", 0.008)
        self.silence_chunks = funasr.get("silence_duration_ms", 600) // 50

        self._audio_queue = queue.Queue()
        self._stop_event = threading.Event()
        self._callback: Optional[Callable] = None
        self._mqtt_publisher: Optional[Callable] = None
        self._model = None

    # ── MQTT集成 ──────────────────────────────────────────────────────

    def set_mqtt_publisher(self, publisher_fn: Callable[[str, dict], None]):
        """设置MQTT发布函数"""
        self._mqtt_publisher = publisher_fn
        logger.info("MQTT publisher 已设置")

    def _publish_transcription(self, text: str, confidence: float = 0.9) -> None:
        """通过MQTT发布转写事件"""
        if self._mqtt_publisher is None:
            logger.debug("MQTT publisher 未设置，跳过发布")
            return

        payload = {
            "topic_type": "event",
            "payload": {
                "event_type": "transcription",
                "text": text,
                "language": "zh",
                "confidence": confidence,
                "duration_ms": len(text) * 50,  # 估算
            },
        }

        self._mqtt_publisher("av/audio/event", payload)
        logger.debug(f"发布语音转写事件: {text[:30]}...")

    # ── 原有接口（向后兼容）───────────────────────────────────────────

    def start(self, callback: Callable = None):
        """启动录音和识别线程"""
        self._callback = callback

        logger.info("加载 FunASR SenseVoiceSmall 模型...")
        import logging as funasr_log

        funasr_log.getLogger("funasr").setLevel(funasr_log.ERROR)

        from funasr import AutoModel

        self._model = AutoModel(
            model="iic/SenseVoiceSmall",
            trust_remote_code=True,
            disable_update=True,
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
                                res = self._model.generate(input=audio_np, batch_size_s=1)
                                if res and len(res) > 0:
                                    text = _clean_tags(res[0].get("text", ""))
                                    if text and len(text) >= 2:
                                        # 通过MQTT发布
                                        self._publish_transcription(text)
                                        # 保留callback调用（向后兼容）
                                        if self._callback:
                                            try:
                                                self._callback(text)
                                            except Exception as e:
                                                logger.error(f"callback异常: {e}")
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
