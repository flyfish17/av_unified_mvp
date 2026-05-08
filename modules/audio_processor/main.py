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
import logging
import signal
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule
from modules.audio_processor.processor import AudioProcessor, TranscriptEvent

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
        super().__init__("audio_processor", cfg, streams=streams)
        self._topics = topics
        self.processor = AudioProcessor(cfg.get("audio", {}))

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        # 语意理解模块当前不消费任何下行 topic
        pass

    def start(self) -> None:
        super().start()
        self.processor.start(callback=self._on_transcript)

    def stop(self) -> None:
        try:
            self.processor.stop()
        except Exception as e:
            self.logger.warning(f"AudioProcessor stop 异常: {e}")
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
