"""
modules/audio_processor/segments.py
final 段音频落盘 + av/audio/segment 事件构造/发布。

AudioModule（MQTT 模块进程）与 streamlit dashboard（直连 AudioProcessor 旁路）
共用此逻辑，保证两条运行路径发出的 segment 事件同构，speaker_diarizer 只认一种协议。
"""
from __future__ import annotations

import logging
import wave
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

DEFAULT_SEGMENT_TOPIC = "av/audio/segment"


class SegmentSink:
    """把 final TranscriptEvent 的 PCM 写成 WAV 并发布 segment 事件。

    publish: callable(topic: str, payload: dict)。
      AudioModule 传 self.publish（BaseModule 自动加 header），
      dashboard 传 MQTTBridge.publish（无 header）——消费端按 payload.payload 取内层，两者兼容。
    """

    def __init__(
        self,
        audio_cfg: dict,
        project_root: Path,
        sample_rate: int,
        publish: Callable[[str, dict], None],
        topic: str = DEFAULT_SEGMENT_TOPIC,
    ):
        segment_cfg = (audio_cfg or {}).get("segments", {}) or {}
        seg_dir = Path(segment_cfg.get("dir", "runtime/audio_segments"))
        if not seg_dir.is_absolute():
            seg_dir = Path(project_root) / seg_dir
        seg_dir.mkdir(parents=True, exist_ok=True)
        self.segment_dir = seg_dir
        self.max_files = int(segment_cfg.get("max_files", 300))
        self.sample_rate = int(sample_rate)
        self._publish = publish
        self._topic = topic

    def _segment_path(self, ev) -> Path:
        safe_id = "".join(
            ch for ch in (ev.segment_id or f"aud-{ev.seq_id:06d}") if ch.isalnum() or ch in "-_"
        )
        return self.segment_dir / f"{safe_id}.wav"

    def _write_wav(self, ev) -> Optional[str]:
        pcm = ev.pcm_bytes or b""
        if not pcm:
            return None
        path = self._segment_path(ev)
        try:
            with wave.open(str(path), "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(self.sample_rate)
                wf.writeframes(pcm)
            self._prune()
            return path.resolve().as_uri()
        except Exception as e:
            logger.warning(f"写音频片段失败 {path}: {e}")
            return None

    def _prune(self) -> None:
        if self.max_files <= 0:
            return
        try:
            files = sorted(
                self.segment_dir.glob("*.wav"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            for old in files[self.max_files:]:
                old.unlink(missing_ok=True)
        except Exception as e:
            logger.debug(f"清理音频片段失败: {e}")

    def handle_final(self, ev) -> Optional[str]:
        """落盘 + 发布。返回 audio_uri（file://…），无 PCM 或写失败返回 None。"""
        audio_uri = self._write_wav(ev)
        if not audio_uri:
            return None
        self._publish(self._topic, {
            "topic_type": "event",
            "payload": {
                "event_type": "audio_segment",
                "segment_id": ev.segment_id,
                "seq_id": ev.seq_id,
                "text": ev.text,
                "start_ms": ev.start_ms,
                "end_ms": ev.end_ms,
                "audio_uri": audio_uri,
                "sample_rate": self.sample_rate,
                "channels": 1,
                "format": "wav",
                "ts": ev.ts,
            },
        })
        return audio_uri
