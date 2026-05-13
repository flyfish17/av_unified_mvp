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
        # 运行时开关：用户可在 dashboard 顶栏 toggle ON/OFF。OFF 时收到 av/audio/command
        # 直接丢弃，不调 ollama 不发 av/llm/event。默认 ON 保留当前演示链路；改默认改
        # config llm.enabled_default。
        # 必须在 super().__init__ 之前设：BaseModule.__init__ 构造 LWT 时立即调
        # self._discovery_payload("offline")，子类重写版会引用 self.enabled。
        self.enabled = bool(cfg.get("llm", {}).get("enabled_default", True))

        super().__init__("llm_engine", cfg, streams=streams)

        # 创建引擎
        self.engine = LLMEngine(
            cfg.get("llm", {}),
            default_location=cfg.get("system", {}).get("default_location", ""),
        )
        self.engine.set_mqtt_publisher(self.publish)

        # 订阅音频定稿（主路径：audio_processor → av/audio/command → 意图识别）
        self.subscribe(cfg.get("mqtt", {}).get("topics", {}).get("audio_command", "av/audio/command"))
        # 向后兼容：允许直接向 av/llm/command 注入文本（测试 / 手动调用）
        self.subscribe("av/llm/command")
        # 运行时开关命令：dashboard toggle → POST /mqtt/publish av/llm/cmd {action: enable|disable}
        self.subscribe("av/llm/cmd")

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        self.logger.info(f"LLM Engine 初始化完成，Ollama: {self.engine.url}，意图判断: {'ON' if self.enabled else 'OFF'}")

    def _discovery_payload(self, event: str) -> dict:
        # 在公告里带 enabled，让前端 header toggle 实时同步当前状态
        payload = super()._discovery_payload(event)
        payload["enabled"] = self.enabled
        return payload

    def _handle_message(self, topic: str, payload: dict) -> None:
        """av/audio/command 和 av/llm/command 触发 process_command；av/llm/cmd 是开关。"""
        if topic == "av/llm/cmd":
            inner = payload.get("payload", payload) if isinstance(payload, dict) else {}
            action = inner.get("action") or (payload.get("action") if isinstance(payload, dict) else None)
            if action in ("enable", "disable"):
                new_state = (action == "enable")
                if new_state == self.enabled:
                    return
                self.enabled = new_state
                self.logger.info(f"意图判断 {'已开启' if new_state else '已关闭'}")
                self._publish_discovery("online")  # 让前端 toggle 立即同步
            return
        if "audio/command" in topic or "llm/command" in topic:
            # OFF 时直接丢弃（用户原则"不开就不动"）
            if not self.enabled:
                return
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
