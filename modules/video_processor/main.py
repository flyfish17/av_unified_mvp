#!/usr/bin/env python3
"""
modules/video_processor/main.py
视频处理模块入口 - 独立进程
"""
import logging
import signal
import sys
from pathlib import Path

import yaml

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule
from modules.video_processor.processor import VideoProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


class VideoModule(BaseModule):
    """视频处理模块"""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        super().__init__("video_processor", cfg)

        # 创建处理器
        self.processor = VideoProcessor(cfg.get("video", {}))
        self.processor.set_mqtt_publisher(self.publish)

        # 订阅配置更新主题
        self.subscribe("av/system/config/video_processor")

        # 信号处理
        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        """处理MQTT消息"""
        if "config" in topic:
            self._reload_config(payload)

    def _reload_config(self, payload: dict) -> None:
        """热重载配置"""
        sources = payload.get("payload", {}).get("sources", [])
        if sources:
            self.logger.info("收到配置更新，热重载摄像头...")
            self.processor.reload_sources(sources)


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    module = VideoModule(str(config_path))
    module.run()


if __name__ == "__main__":
    main()
