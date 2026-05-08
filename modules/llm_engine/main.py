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

        streams = [
            {
                "topic": "av/llm/event",
                "channel": "intent",
                "kind": "kv_table",
                "title": "意图识别 / 指令翻译",
            },
        ]
        super().__init__("llm_engine", cfg, streams=streams)

        # 创建引擎
        self.engine = LLMEngine(cfg.get("llm", {}))
        self.engine.set_mqtt_publisher(self.publish)

        # 订阅音频定稿（主路径：audio_processor → av/audio/command → 意图识别）
        self.subscribe(cfg.get("mqtt", {}).get("topics", {}).get("audio_command", "av/audio/command"))
        # 向后兼容：允许直接向 av/llm/command 注入文本（测试 / 手动调用）
        self.subscribe("av/llm/command")

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        self.logger.info(f"LLM Engine 初始化完成，Ollama: {self.engine.url}")

    def _handle_message(self, topic: str, payload: dict) -> None:
        """处理MQTT消息。av/audio/command 和 av/llm/command 都触发 process_command。"""
        if "audio/command" in topic or "llm/command" in topic:
            # av/audio/command 只含 final，但做一次防御性检查
            inner = payload.get("payload", {}) or {}
            if inner.get("is_final") is False:
                return
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
