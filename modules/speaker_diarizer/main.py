#!/usr/bin/env python3
"""
modules/speaker_diarizer/main.py
发言人区分模块的独立进程入口。

订阅 av/audio/segment（final 段 WAV 已由 audio_processor 落盘）
  → CAM++ 嵌入 + 在线聚类（diarizer.py）
  → 发布 av/audio/diarization：{segment_id, seq_id, speaker_id, confidence, ts}

speaker_id 不写回 final 事件（转写不等分离，解耦原则）；
消费端（dashboard / web 前端）按 segment_id join。
"""
import logging
import queue
import signal
import sys
import threading
import wave
from pathlib import Path
from urllib.parse import unquote, urlparse

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule
from modules.speaker_diarizer.diarizer import (
    CAMPP_MODEL_ID,
    CamppEmbedder,
    OnlineSpeakerClusterer,
    find_local_model,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def _uri_to_path(audio_uri: str) -> Path | None:
    try:
        parsed = urlparse(audio_uri)
        if parsed.scheme == "file":
            return Path(unquote(parsed.path))
        if not parsed.scheme:  # 裸路径兼容
            return Path(audio_uri)
    except Exception:
        pass
    return None


def _wav_duration_s(path: Path) -> float:
    """段时长以 WAV 实际帧数为准（事件里 start/end_ms 是近似边界，含静音水分）。"""
    with wave.open(str(path), "rb") as wf:
        return wf.getnframes() / float(wf.getframerate() or 16000)


class SpeakerDiarizerModule(BaseModule):

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        sd_cfg = cfg.get("speaker_diarizer", {}) or {}
        topics = cfg.get("mqtt", {}).get("topics", {})
        self._segment_topic = topics.get("audio_segment", "av/audio/segment")
        self._diar_topic = topics.get("audio_diarization", "av/audio/diarization")

        self.enabled = bool(sd_cfg.get("enabled", True)) and sd_cfg.get("mode", "campp_embed") == "campp_embed"
        self.allow_download = bool(sd_cfg.get("allow_download", False))
        self.spk_model = sd_cfg.get("spk_model", CAMPP_MODEL_ID)
        self.threshold = float(sd_cfg.get("threshold", 0.35))

        # channel 必须独立（diarization）：若声明 transcript，dashboard 会为本模块
        # 再挂一个 transcript 订阅，同一转写事件双 handler → 总览卡文本渲染两遍
        streams = [{
            "topic": self._diar_topic,
            "channel": "diarization",
            "kind": "kv_table",
            "title": "发言人区分",
        }]
        super().__init__("speaker_diarizer", cfg, streams=streams)

        # 段事件 → 单 worker 串行消费（嵌入 ~0.5s/段；聚类器非线程安全，靠单 worker 保证串行）
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=100)
        self._embedder: CamppEmbedder | None = None
        self._clusterer = OnlineSpeakerClusterer(threshold=self.threshold)

        if self.enabled:
            self.subscribe(self._segment_topic)

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    # ── MQTT in ──────────────────────────────────────────────────────

    def _handle_message(self, topic: str, payload: dict) -> None:
        if topic != self._segment_topic:
            return
        inner = payload.get("payload", payload) if isinstance(payload, dict) else {}
        if inner.get("event_type") != "audio_segment":
            return
        try:
            self._queue.put_nowait(inner)
        except queue.Full:
            # 积压时丢最旧的段：实时会议里迟到 100 段的标签已无意义
            try:
                self._queue.get_nowait()
                self._queue.put_nowait(inner)
                self.logger.warning("diarization 队列满，丢弃最旧段")
            except queue.Empty:
                pass

    # ── worker ───────────────────────────────────────────────────────

    def _init_embedder(self) -> bool:
        model_dir = find_local_model(self.spk_model)
        if model_dir is None:
            if not self.allow_download:
                self.logger.error(
                    f"campplus 模型未缓存且 allow_download=false，模块禁用。"
                    f"有网机执行一次：python3.10 -c \"from modelscope import snapshot_download; "
                    f"snapshot_download('{self.spk_model}')\""
                )
                return False
            model_dir = self.spk_model  # 交给 funasr 联网拉取
            self.logger.warning(f"本地无 {self.spk_model} 缓存，将联网首次下载")
        try:
            self._embedder = CamppEmbedder(Path(model_dir))
            self.logger.info(f"CAM++ 就绪（threshold={self.threshold}）: {model_dir}")
            return True
        except Exception as e:
            self.logger.error(f"CAM++ 加载失败，模块禁用: {e}")
            return False

    def _worker(self) -> None:
        if not self._init_embedder():
            return
        while self._running.is_set():
            try:
                seg = self._queue.get(timeout=1.0)
            except queue.Empty:
                continue
            try:
                self._process_segment(seg)
            except Exception as e:
                self.logger.error(f"处理段失败 {seg.get('segment_id')}: {e}")

    def _process_segment(self, seg: dict) -> None:
        path = _uri_to_path(seg.get("audio_uri") or "")
        if path is None or not path.exists():
            self.logger.warning(f"段音频不存在: {seg.get('audio_uri')}")
            return
        try:
            duration = _wav_duration_s(path)
        except Exception as e:
            self.logger.warning(f"读 WAV 失败 {path}: {e}")
            return
        emb = self._embedder.embed_wav(path) if duration >= 0.5 else None
        a = self._clusterer.assign(emb, duration)
        if a.is_new:
            self.logger.info(f"新说话人 {a.speaker_id}（累计 {self._clusterer.num_speakers} 人）")
        self.publish(self._diar_topic, {
            "topic_type": "event",
            "payload": {
                "event_type": "speaker_diarization",
                "segment_id": seg.get("segment_id"),
                "seq_id": seg.get("seq_id"),
                "speaker_id": a.speaker_id,
                "speaker_confidence": a.confidence,
                "num_speakers": self._clusterer.num_speakers,
                "duration_s": round(duration, 2),
                "ts": seg.get("ts"),
            },
        })

    # ── 生命周期 ─────────────────────────────────────────────────────

    def start(self) -> None:
        super().start()
        if not self.enabled:
            self.logger.warning("speaker_diarizer 未启用（enabled=false 或 mode 非 campp_embed），空转仅心跳")
            return
        threading.Thread(target=self._worker, daemon=True, name="diarizer-worker").start()


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    SpeakerDiarizerModule(str(config_path)).run()


if __name__ == "__main__":
    main()
