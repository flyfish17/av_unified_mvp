#!/usr/bin/env python3
"""
modules/net_audio_capture/main.py
会议主机组播音频接入模块（CR-DIG7201 P1）。

启动后：
  - 按 config audio.net_multicast 起 N 路 UDP 组播收包（224.1.1.11:1000-1007）
  - 每路独立 FunASR 2pass 会话（RMS 静音门，闲路不占 decoder）
  - partial → av/audio/partial，final → av/audio/command_punctuated
    payload 带 mic_id / speaker 字段（下游按需取用，不破坏现有订阅）
"""
import logging
import signal
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule
from modules.net_audio_capture.receiver import MicTranscriptEvent, UdpMicChannel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


class NetAudioCaptureModule(BaseModule):
    """会议主机 8 路话筒组播 → 分路转写。"""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        audio_cfg = cfg.get("audio", {})
        mc = audio_cfg.get("net_multicast", {}) or {}
        self._group = str(mc.get("group", "224.1.1.11"))
        self._base_port = int(mc.get("base_port", 1000))
        self._num_channels = int(mc.get("num_channels", 8))
        self._gate_threshold = float(mc.get("gate_threshold", 150.0))

        topics = cfg.get("mqtt", {}).get("topics", {})
        streams = [
            {
                "topic": topics.get("audio_partial", "av/audio/partial"),
                "channel": "transcript",
                "kind": "transcript_seq",
                "title": f"会议主机转写（{self._num_channels} 路组播）",
            },
        ]
        # 必须在 super().__init__ 之前设：BaseModule.__init__ 构造 LWT 时立即调
        # _discovery_payload，重写版会引用 self._channels（audio_processor 同款坑）
        self._channels: list[UdpMicChannel] = []
        super().__init__("net_audio_capture", cfg, streams=streams)
        self._topics = topics

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        pass  # 暂无入向控制；后续如需分路开关再加 av/audio/net_cmd

    def _discovery_payload(self, event: str) -> dict:
        payload = super()._discovery_payload(event)
        payload["channels"] = [ch.stats() for ch in self._channels]
        return payload

    def start(self) -> None:
        super().start()
        for i in range(self._num_channels):
            ch = UdpMicChannel(
                mic_id=i,
                group=self._group,
                port=self._base_port + i,
                funasr_cfg=funasr_cfg_of(self.cfg),
                callback=self._on_transcript,
                gate_threshold=self._gate_threshold,
            )
            ch.start()
            self._channels.append(ch)
        self.logger.info(
            f"{self._num_channels} 路组播接入已启动 "
            f"{self._group}:{self._base_port}-{self._base_port + self._num_channels - 1}"
        )

    def stop(self) -> None:
        for ch in self._channels:
            try:
                ch.stop()
            except Exception as e:
                self.logger.warning(f"mic{ch.mic_id} stop 异常: {e}")
        super().stop()

    # ── transcript → MQTT（对齐 audio_processor funasr_2pass 路径的 topic 契约）──

    def _on_transcript(self, ev: MicTranscriptEvent) -> None:
        speaker = f"话筒{ev.mic_id + 1}"
        inner = {
            "event_type": "transcription",
            "text": ev.text,
            "seq_id": ev.seq_id,
            "is_final": ev.is_final,
            "raw_mode": ev.raw_mode,
            "ts": ev.ts,
            "mic_id": ev.mic_id,
            "speaker": speaker,
        }
        if ev.is_final:
            self.logger.info(f"[{speaker} final] {ev.text}")
            # funasr 2pass offline 段已带 ITN 标点，与 audio_processor 同走 punctuated topic
            self.publish("av/audio/command_punctuated", {
                "topic_type": "event",
                "payload": {
                    **inner,
                    "event_type": "transcription_punctuated",
                    "text_original": ev.text,
                    "punct_latency_ms": 0.0,
                },
            })
        else:
            self.publish(self._topics.get("audio_partial", "av/audio/partial"), {
                "topic_type": "event",
                "payload": inner,
            })


def funasr_cfg_of(cfg: dict) -> dict:
    return (cfg.get("audio") or {}).get("funasr", {}) or {}


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    module = NetAudioCaptureModule(str(config_path))
    module.run()


if __name__ == "__main__":
    main()
