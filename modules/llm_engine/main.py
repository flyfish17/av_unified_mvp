#!/usr/bin/env python3
"""
modules/llm_engine/main.py
LLM处理模块入口 - 独立进程
"""
import logging
import signal
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule
from modules.llm_engine.engine import LLMEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


class LLMModule(BaseModule):
    """LLM处理模块"""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        super().__init__("llm_engine", cfg)

        # 创建引擎
        self.engine = LLMEngine(cfg.get("llm", {}))
        self.engine.set_mqtt_publisher(self.publish)

        # 订阅处理指令
        self.subscribe("av/llm/command")

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        self.logger.info(f"LLM Engine 初始化完成，Ollama: {self.engine.url}")

    def _handle_message(self, topic: str, payload: dict) -> None:
        """处理MQTT消息"""
        if topic == "av/llm/command":
            self.engine.process_command(payload)


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    module = LLMModule(str(config_path))

    # 检查Ollama是否可用
    if not module.engine.is_available():
        module.logger.warning("Ollama服务不可用，模块将继续启动")

    module.run()


if __name__ == "__main__":
    main()
