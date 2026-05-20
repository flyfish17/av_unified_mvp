#!/usr/bin/env python3
"""
modules/punctuator/main.py — 中英混标点后处理模块

订 av/audio/command（audio_processor 发的 final，无标点），
调 sherpa-onnx ct-transformer int8 ONNX 加标点，
发 av/audio/command_punctuated（含原文 + 带标点版本，保留 seq_id 关联）。

设计目的：
  sensevoice / sensevoice-RKNN 转写不出 ITN 标点。LLM 后处理依赖云 + 引入第二条调用链，
  反工程。ct-punct int8 ONNX（72MB）在 RK3588 单核 CPU 上 9-99 字 final
  p95 4.9-37.9ms（spike-campp-ctpunc-3588-20260518.md），零侵入 video_processor。

Topic：
  订: av/audio/command           {payload: {text, seq_id, is_final, ts, raw_mode, ...}}
  发: av/audio/command_punctuated {payload: {text, text_original, seq_id, ts, latency_ms, ...}}

Module 与 audio_processor 完全解耦：不动 audio_processor 源码（红线），通过 MQTT 旁路。
依赖 sherpa-onnx 1.13.2（独立 venv，不污染 audio_processor 用的 creator_ai_demo/venv）。
"""
import logging
import os
import signal
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


DEFAULTS = {
    "enabled": True,
    "input_topic": "av/audio/command",
    "output_topic": "av/audio/command_punctuated",
    # ct-punc int8 ONNX 模型路径。5/20 迁出 spike_venv 到独立 ~/models/（清理 spike_venv 后正式生效）。
    # config 或 AV_PUNCT_MODEL env 可 override（如部署在非 firefly 用户机器要换 path）。
    "model": "/home/firefly/models/ct-punc-zh-en-vocab272727-int8/model.int8.onnx",
    "num_threads": 1,
    "provider": "cpu",
    # 短文本跳过阈值（少于此字符的不调模型，避免无意义的标点）
    "min_chars": 2,
}


class PunctuatorModule(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}

        pc = dict(DEFAULTS)
        pc.update(cfg.get("punctuator", {}) or {})
        # env 优先级最高 — 部署时 AV_PUNCT_MODEL=/path/to/model.int8.onnx 可临时切
        env_model = os.environ.get("AV_PUNCT_MODEL")
        if env_model:
            pc["model"] = env_model

        # input_topic 也读 mqtt.topics.audio_command 作为 fallback
        mqtt_topics = (cfg.get("mqtt") or {}).get("topics", {}) or {}
        if "punctuator" not in cfg and mqtt_topics.get("audio_command"):
            pc["input_topic"] = mqtt_topics["audio_command"]

        self._pc = pc

        # streams=[] 是刻意的：punctuator 不能声明 channel="transcript"，否则 dashboard.js
        # 会给 transcript channel 重复注册 handler（audio_processor + punctuator 各一个），
        # 每条 SSE event 触发 tickerForward 两次 → final 在转写卡里显示两遍（5/18 真机回归）。
        # discovery 上线消息仍发，dashboard 模块列表能看到 punctuator，但不重复绑 stream。
        super().__init__("punctuator", cfg, streams=[])

        self._stats = {
            "received": 0,
            "punctuated": 0,
            "skipped_short": 0,
            "skipped_not_final": 0,
            "skipped_empty": 0,
            "lat_p50_ms": 0.0,
            "lat_p95_ms": 0.0,
            "lat_max_ms": 0.0,
        }
        self._lat_window: list[float] = []

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        if not pc["enabled"]:
            self._punct = None
            self.logger.info("punctuator enabled=false，仅占位")
            return

        # 装 sherpa-onnx 时机：__init__ 里 load 一次（363ms 一次性，spike 实测）
        import sherpa_onnx
        model_path = pc["model"]
        if not Path(model_path).exists():
            raise FileNotFoundError(f"ct-punc 模型不存在: {model_path}")

        sherpa_cfg = sherpa_onnx.OfflinePunctuationConfig(
            model=sherpa_onnx.OfflinePunctuationModelConfig(
                ct_transformer=model_path,
                num_threads=pc["num_threads"],
                provider=pc["provider"],
            )
        )
        t0 = time.perf_counter()
        self._punct = sherpa_onnx.OfflinePunctuation(sherpa_cfg)
        load_ms = (time.perf_counter() - t0) * 1000
        self.logger.info(f"ct-punc 加载 OK（{load_ms:.0f}ms）model={model_path}")

        self.subscribe(pc["input_topic"])
        self.logger.info(
            f"订阅 {pc['input_topic']} → {pc['output_topic']} | "
            f"threads={pc['num_threads']} provider={pc['provider']} min_chars={pc['min_chars']}"
        )

    def _handle_message(self, topic: str, payload: dict) -> None:
        if topic != self._pc["input_topic"]:
            return
        if self._punct is None:
            return
        self._stats["received"] += 1

        inner = payload.get("payload", payload) if isinstance(payload, dict) else {}
        # 兼容直接平铺和嵌套两种 schema
        text = inner.get("text") or payload.get("text") or ""
        seq_id = inner.get("seq_id") if "seq_id" in inner else payload.get("seq_id")
        is_final = inner.get("is_final", payload.get("is_final", True))
        ts = inner.get("ts") or payload.get("ts") or time.time()
        raw_mode = inner.get("raw_mode") or payload.get("raw_mode") or ""

        if not is_final:
            self._stats["skipped_not_final"] += 1
            return
        text = text.strip()
        if not text:
            self._stats["skipped_empty"] += 1
            return
        if len(text) < self._pc["min_chars"]:
            # 太短直接透传不加标点
            self._stats["skipped_short"] += 1
            self._publish(text_punctuated=text, text_original=text, seq_id=seq_id,
                          ts=ts, raw_mode=raw_mode, latency_ms=0.0)
            return

        t0 = time.perf_counter()
        text_punctuated = self._punct.add_punctuation(text)
        latency_ms = (time.perf_counter() - t0) * 1000

        self._record_latency(latency_ms)
        self._stats["punctuated"] += 1
        self._publish(text_punctuated=text_punctuated, text_original=text, seq_id=seq_id,
                      ts=ts, raw_mode=raw_mode, latency_ms=latency_ms)
        self.logger.info(
            f"[punct] seq={seq_id} {len(text)}字 {latency_ms:.1f}ms | {text} → {text_punctuated}"
        )

    def _publish(self, *, text_punctuated: str, text_original: str, seq_id,
                 ts: float, raw_mode: str, latency_ms: float) -> None:
        payload = {
            "topic_type": "event",
            "payload": {
                "event_type": "transcription_punctuated",
                "text": text_punctuated,            # 主字段 = 带标点（前端默认显示）
                "text_original": text_original,     # 保留原文供对比
                "seq_id": seq_id,
                "is_final": True,
                "raw_mode": raw_mode,
                "ts": ts,
                "punct_latency_ms": round(latency_ms, 1),
            },
        }
        self.publish(self._pc["output_topic"], payload)

    def _record_latency(self, ms: float) -> None:
        self._lat_window.append(ms)
        if len(self._lat_window) > 200:
            self._lat_window = self._lat_window[-200:]
        s = sorted(self._lat_window)
        self._stats["lat_p50_ms"] = round(s[len(s)//2], 1)
        self._stats["lat_p95_ms"] = round(s[int(len(s)*0.95)], 1) if len(s) >= 20 else round(s[-1], 1)
        self._stats["lat_max_ms"] = round(s[-1], 1)

    def run(self) -> None:
        self.start()
        last_heartbeat = time.time()
        last_stats = time.time()
        try:
            while self._running.is_set():
                time.sleep(1)
                now = time.time()
                if now - last_heartbeat >= self.HEARTBEAT_INTERVAL and self._connected:
                    self._publish_discovery("heartbeat")
                    last_heartbeat = now
                if now - last_stats >= 60:
                    self.logger.info(f"[stats] {self._stats}")
                    last_stats = now
        except KeyboardInterrupt:
            self.logger.info("收到键盘中断信号")
        finally:
            self.stop()


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    PunctuatorModule(str(config_path)).run()


if __name__ == "__main__":
    main()
