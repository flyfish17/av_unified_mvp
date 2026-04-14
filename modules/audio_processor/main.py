#!/usr/bin/env python3
"""
modules/audio_processor/main.py
音频处理模块入口 - 独立进程
"""
import logging
import signal
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule
from modules.audio_processor.processor import AudioProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


class AudioModule(BaseModule):
    """音频处理模块"""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        super().__init__("audio_processor", cfg)

        # 创建处理器
        self.processor = AudioProcessor(cfg.get("audio", {}))
        self.processor.set_mqtt_publisher(self.publish)

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        """处理MQTT消息（音频模块目前不需要处理消息）"""
        pass


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    module = AudioModule(str(config_path))
    module.run()


if __name__ == "__main__":
    main()
