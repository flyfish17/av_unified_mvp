#!/usr/bin/env python3
"""
modules/audio_processor/main.py
语意理解模块的独立进程入口。

启动后：
  - 连接本地 MQTT broker
  - 启动 FunASR 2pass 转写（不可用时自动降级到 SenseVoiceSmall 本地）
  - partial → av/audio/partial
  - final   → av/audio/command
"""
import io
import logging
import os
import signal
import sys
import threading
import wave
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule

# Backend 切换：默认 funasr_2pass（Mac），AV_ASR_BACKEND=sense_voice_arm 切 ARM 路径（3588）
_ASR_BACKEND = os.environ.get("AV_ASR_BACKEND", "funasr_2pass").strip()
if _ASR_BACKEND == "sense_voice_arm":
    from modules.audio_processor.processor_arm import AudioProcessorARM as AudioProcessor
    from modules.audio_processor.processor import TranscriptEvent  # 共享 dataclass
    logging.getLogger(__name__).info("使用 ARM 路径：SenseVoiceSmall + VAD 分段 + 流式降噪")
else:
    from modules.audio_processor.processor import AudioProcessor, TranscriptEvent

AUDIO_HTTP_PORT = 5052


class _AudioExportHandler(BaseHTTPRequestHandler):
    """嵌入式 HTTP，前端"导出原音"按钮直连 :5052 拉 WAV（仿 video_processor 5051 风格）。

    路径：GET /audio/export.wav  → 当前 PCM 环形 buffer 打 WAV 包返回
    """
    processor_ref: "AudioProcessor | None" = None  # 由 AudioModule 注入
    sample_rate: int = 16000

    def log_message(self, fmt, *args):
        pass  # 静默 access log

    def do_GET(self):
        if self.path.startswith("/audio/export.wav"):
            return self._serve_wav()
        self.send_error(404)

    def _serve_wav(self):
        proc = self.processor_ref
        if proc is None:
            self.send_response(503)
            self.send_header("Content-Length", "0"); self.end_headers()
            return
        pcm = proc.get_pcm_buffer()
        if not pcm:
            self.send_response(204)
            self.send_header("Content-Length", "0"); self.end_headers()
            return
        buf = io.BytesIO()
        with wave.open(buf, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)  # int16
            wf.setframerate(self.sample_rate)
            wf.writeframes(pcm)
        wav_bytes = buf.getvalue()
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.send_response(200)
        self.send_header("Content-Type", "audio/wav")
        self.send_header("Content-Length", str(len(wav_bytes)))
        self.send_header("Content-Disposition", f'attachment; filename="audio-{stamp}.wav"')
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(wav_bytes)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


class AudioModule(BaseModule):
    """语意理解模块（独立进程版）。"""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        topics = cfg.get("mqtt", {}).get("topics", {})
        streams = [
            {
                "topic": topics.get("audio_partial", "av/audio/partial"),
                "channel": "transcript",
                "kind": "transcript_seq",
                "title": "实时转写（流式）",
            },
            {
                "topic": topics.get("audio_command", "av/audio/command"),
                "channel": "transcript",
                "kind": "transcript_seq",
                "title": "已定稿（含标点）",
            },
        ]
        # 运行时麦克风开关：dashboard "停止" 按钮 → POST /mqtt/publish av/audio/cmd
        # 默认 ON（开机后立即转写）。disable 时 processor.stop() 释放 mic + WS；enable 重启。
        # 必须在 super().__init__ 之前设：BaseModule.__init__ 构造 LWT 时立即调
        # self._discovery_payload("offline")，子类重写版会引用 self.running。
        self.running = True

        super().__init__("audio_processor", cfg, streams=streams)
        self._topics = topics
        self.processor = AudioProcessor(cfg.get("audio", {}))
        self.subscribe("av/audio/cmd")

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _discovery_payload(self, event: str) -> dict:
        # 公告里带 running 状态供前端 toggle 同步
        payload = super()._discovery_payload(event)
        payload["running"] = self.running
        return payload

    def _handle_message(self, topic: str, payload: dict) -> None:
        if topic == "av/audio/cmd":
            inner = payload.get("payload", payload) if isinstance(payload, dict) else {}
            action = inner.get("action") or (payload.get("action") if isinstance(payload, dict) else None)
            if action == "disable" and self.running:
                self.logger.info("收到 disable，停止麦克风采集 + 转写")
                try:
                    self.processor.stop()
                except Exception as e:
                    self.logger.warning(f"processor.stop 异常: {e}")
                self.running = False
                self._publish_discovery("online")
            elif action == "enable" and not self.running:
                self.logger.info("收到 enable，恢复麦克风采集 + 转写")
                try:
                    self.processor.start(callback=self._on_transcript)
                except Exception as e:
                    self.logger.warning(f"processor.start 异常: {e}")
                    return
                self.running = True
                self._publish_discovery("online")

    def start(self) -> None:
        super().start()
        self.processor.start(callback=self._on_transcript)
        # 启嵌入式 HTTP（5052）— 前端"导出原音"按钮直连此端口
        # 与 video_processor 5051 同样思路；start() 时启避免 __init__ 阶段还没装好 processor
        _AudioExportHandler.processor_ref = self.processor
        _AudioExportHandler.sample_rate = self.processor.sample_rate
        try:
            self._http_server = ThreadingHTTPServer(("0.0.0.0", AUDIO_HTTP_PORT), _AudioExportHandler)
            threading.Thread(target=self._http_server.serve_forever, daemon=True).start()
            self.logger.info(f"音频导出 HTTP 已启动: http://0.0.0.0:{AUDIO_HTTP_PORT}/audio/export.wav")
        except Exception as e:
            self.logger.warning(f"音频导出 HTTP 启动失败 :{AUDIO_HTTP_PORT} → {e}")
            self._http_server = None

    def stop(self) -> None:
        try:
            self.processor.stop()
        except Exception as e:
            self.logger.warning(f"AudioProcessor stop 异常: {e}")
        # 关嵌入式 HTTP，避免 supervisor 重拉子进程时 5052 残留导致 EADDRINUSE
        srv = getattr(self, "_http_server", None)
        if srv is not None:
            try:
                srv.shutdown()
                srv.server_close()
            except Exception:
                pass
        super().stop()

    # ── transcript → MQTT ────────────────────────────────────────────

    def _on_transcript(self, ev: TranscriptEvent) -> None:
        payload = {
            "topic_type": "event",
            "payload": {
                "event_type": "transcription",
                "text": ev.text,
                "seq_id": ev.seq_id,
                "is_final": ev.is_final,
                "raw_mode": ev.raw_mode,
                "ts": ev.ts,
            },
        }
        if ev.is_final:
            self.logger.info(f"[final] {ev.text}")
            self.publish(self._topics.get("audio_command", "av/audio/command"), payload)
        else:
            self.publish(self._topics.get("audio_partial", "av/audio/partial"), payload)


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    module = AudioModule(str(config_path))
    module.run()


if __name__ == "__main__":
    main()
