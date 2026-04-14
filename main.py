#!/usr/bin/env python3
"""
main.py
AV统一系统 - 主程序入口
"""
import logging
import signal
import sys
import time
from pathlib import Path

import yaml

# 添加core目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from core.audio_processor import AudioProcessor
from core.llm_engine import LLMEngine
from core.mqtt_bridge import MQTTBridge
from core.video_processor import VideoProcessor

# ── 日志配置 ──────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)


class AVUnifiedSystem:
    def __init__(self, config_path: str):
        # 加载配置
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        # 初始化各模块
        self.mqtt  = MQTTBridge(self.cfg.get("mqtt", {}))
        self.llm   = LLMEngine(self.cfg.get("llm", {}))
        self.video = VideoProcessor(self.cfg.get("video", {}))
        self.audio = AudioProcessor(self.cfg.get("audio", {}))

        self._running = False

    # ── 启动/停止 ─────────────────────────────────────────────────────

    def start(self):
        logger.info("=" * 60)
        logger.info("  AV统一系统启动中...")
        logger.info("=" * 60)

        # 1. 启动MQTT
        self.mqtt.start()
        time.sleep(1)

        # 2. 订阅MQTT主题（接收其他盒子的消息）
        topics = self.cfg.get("mqtt", {}).get("topics", {})
        self.mqtt.subscribe(topics.get("discovery", "av/discovery"), self._on_discovery)
        self.mqtt.subscribe(topics.get("control", "av/control"), self._on_control)

        # 3. 启动视频处理
        self.video.start(callback=self._on_video_event)

        # 4. 启动音频处理
        self.audio.start(callback=self._on_audio_text)

        self._running = True
        logger.info("✓ 系统已启动，按 Ctrl+C 停止\n")

        # 主循环（保持运行）
        try:
            while self._running:
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n收到停止信号")

        self.stop()

    def stop(self):
        logger.info("正在停止系统...")
        self.video.stop()
        self.audio.stop()
        logger.info("已退出")

    # ── 事件处理 ──────────────────────────────────────────────────────

    def _on_video_event(self, event):
        """视频检测事件回调"""
        logger.info(f"[视频] {event.camera_name} 检测到: {len(event.detections)} 个目标")

        # 发布到MQTT
        topics = self.cfg.get("mqtt", {}).get("topics", {})
        self.mqtt.publish(topics.get("video_detect", "av/video/detect"), {
            "camera": event.camera_name,
            "time": event.timestamp,
            "detections": event.detections
        })

        # LLM场景分析（可选，避免频繁调用）
        # cmd = self.llm.analyze_scene(event.detections, event.camera_name)
        # if cmd:
        #     logger.info(f"[LLM场景] 触发动作: {cmd}")
        #     self.mqtt.publish(topics.get("control", "av/control"), cmd)

    def _on_audio_text(self, text: str):
        """语音识别结果回调"""
        logger.info(f"[语音] {text}")

        # 发布到MQTT
        topics = self.cfg.get("mqtt", {}).get("topics", {})
        self.mqtt.publish(topics.get("audio_command", "av/audio/command"), {
            "text": text,
            "time": time.time()
        })

        # 意图识别
        if self.llm.classify_intent(text):
            logger.info("[LLM] 检测到控制意图")
            cmd = self.llm.generate_command(text)
            if cmd:
                logger.info(f"[LLM] 生成指令: {cmd}")
                self.mqtt.publish(topics.get("control", "av/control"), cmd)
        else:
            logger.info("[LLM] 非控制指令，忽略")

    def _on_discovery(self, topic: str, payload: dict):
        """设备发现消息"""
        if payload.get("event") == "online":
            logger.info(f"[发现] 设备上线: {payload.get('client_id')} @ {payload.get('ip')}")

    def _on_control(self, topic: str, payload: dict):
        """接收其他设备的控制指令"""
        logger.info(f"[控制] 收到指令: {payload}")
        # TODO: 这里可以对接硬件控制逻辑


# ── 入口 ──────────────────────────────────────────────────────────────

def main():
    config_path = Path(__file__).parent / "config" / "system_config.yaml"
    if not config_path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(1)

    system = AVUnifiedSystem(str(config_path))

    # 信号处理
    def handle_signal(sig, frame):
        system._running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    system.start()


if __name__ == "__main__":
    main()
