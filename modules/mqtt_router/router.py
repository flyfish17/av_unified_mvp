#!/usr/bin/env python3
"""
modules/mqtt_router/router.py
AV统一系统 - MQTT消息路由器（纯消息路由，无业务逻辑）
路由规则从配置文件加载
"""
import json
import logging
import signal
import sys
import time
from pathlib import Path
from threading import Event

import yaml
import paho.mqtt.client as mqtt

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


class MQTTRouter:
    """
    纯消息路由：接收消息，按规则转发到目标主题

    路由规则配置格式 (system_config.yaml):
    ```yaml
    router:
      rules:
        - source_topic: "av/audio/event"
          target_topic: "av/llm/command"
          condition: "payload.payload.event_type == 'transcription'"
        - source_topic: "av/llm/event"
          target_topics: ["av/dashboard/display", "av/control/command"]
    ```
    """

    def __init__(self, config_path: str):
        self.cfg = self._load_config(config_path)
        self.router_cfg = self.cfg.get("router", {})

        mqtt_cfg = self.cfg.get("mqtt", {})
        self.broker = mqtt_cfg.get("broker", "127.0.0.1")
        self.port = mqtt_cfg.get("port", 1883)
        self.client_id = mqtt_cfg.get("client_id", "av_router")

        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._running = Event()
        self._msg_count = 0
        self._rules = self._compile_rules()

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _load_config(self, config_path: str) -> dict:
        """加载配置文件"""
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"配置文件不存在: {config_path}，使用默认配置")
            return {}
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _compile_rules(self) -> list:
        """
        编译路由规则

        返回格式:
        [{
            "source": "av/audio/event",
            "targets": ["av/llm/command"],
            "condition": callable or None
        }, ...]
        """
        rules = []
        for rule in self.router_cfg.get("rules", []):
            source = rule.get("source_topic", "")
            targets = rule.get("target_topics", [])
            if isinstance(targets, str):
                targets = [targets]
            condition_str = rule.get("condition")

            compiled_cond = None
            if condition_str:
                try:
                    # 将条件字符串编译为可执行函数
                    compiled_cond = self._compile_condition(condition_str)
                except Exception as e:
                    logger.error(f"条件编译失败: {condition_str}, {e}")

            rules.append({
                "source": source,
                "targets": targets,
                "condition": compiled_cond,
            })
            logger.info(f"路由规则: {source} -> {targets}")

        return rules

    @staticmethod
    def _compile_condition(condition_str: str):
        """
        将条件字符串编译为函数

        支持的变量:
            - payload: 完整消息字典
            - payload.payload.xxx: payload嵌套字段
            - payload.header.xxx: header嵌套字段

        示例:
            "payload.payload.event_type == 'transcription'"
        """
        # 提取字段访问
        import re

        def eval_condition(payload):
            try:
                return eval(condition_str, {"payload": payload})
            except Exception:
                return False

        return eval_condition

    def start(self):
        logger.info(f"MQTT Router 启动")
        logger.info(f"  Broker: {self.broker}:{self.port}")
        logger.info(f"  路由规则: {len(self._rules)} 条")

        self._client.connect(self.broker, self.port)
        self._client.loop_start()
        self._running.set()

        # 发布上线消息
        self._publish_discovery("online")

        logger.info("✓ Router 已启动，按 Ctrl+C 停止")
        try:
            while self._running.is_set():
                time.sleep(1)
                # 定期发布状态
                self._publish_status()
        except KeyboardInterrupt:
            self.stop()

    def stop(self):
        if not self._running.is_set():
            return
        logger.info("Router 正在停止...")
        self._running.clear()
        self._publish_discovery("offline")
        self._client.loop_stop()
        self._client.disconnect()
        logger.info("Router 已停止")

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        if reason_code == 0:
            logger.info("已连接到 MQTT Broker")
            # 订阅所有源主题
            for rule in self._rules:
                client.subscribe(rule["source"])
                logger.info(f"  订阅: {rule['source']}")
            # 也订阅系统主题
            client.subscribe("av/system/#")
        else:
            logger.warning(f"连接失败，reason_code={reason_code}")

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        logger.warning("MQTT 连接断开")

    def _on_message(self, client, userdata, msg):
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            topic = msg.topic
            self._msg_count += 1
            logger.debug(f"[{self._msg_count}] {topic}")

            # 执行路由
            self._route(topic, payload)

        except json.JSONDecodeError:
            logger.warning(f"消息解析失败: {msg.payload[:100]}")
        except Exception as e:
            logger.error(f"路由异常: {e}")

    def _route(self, topic: str, payload: dict):
        """根据路由规则转发消息"""
        for rule in self._rules:
            if rule["source"] != topic:
                continue

            # 检查条件
            if rule["condition"] is not None:
                try:
                    if not rule["condition"](payload):
                        continue
                except Exception as e:
                    logger.debug(f"条件不匹配: {e}")

            # 转发到所有目标
            for target in rule["targets"]:
                try:
                    # 添加路由元数据
                    enriched = {
                        **payload,
                        "metadata": {
                            **payload.get("metadata", {}),
                            "routed_by": "av_router",
                            "route_time": time.time(),
                        },
                    }
                    self._client.publish(target, json.dumps(enriched, ensure_ascii=False))
                    logger.debug(f"  → 路由到 {target}")
                except Exception as e:
                    logger.error(f"路由到 {target} 失败: {e}")

    def _publish_discovery(self, event_type: str):
        """发布发现消息"""
        from core.base_module import BaseModule

        ip = BaseModule._get_local_ip()
        self._client.publish(
            "av/system/discovery",
            json.dumps({
                "event": event_type,
                "client_id": self.client_id,
                "client_type": "router",
                "ip": ip,
                "timestamp": time.time(),
            }, ensure_ascii=False),
        )

    def _publish_status(self):
        """发布路由状态（心跳，每60秒）"""
        if not hasattr(self, "_last_status_time"):
            self._last_status_time = 0

        now = time.time()
        if now - self._last_status_time < 60:
            return
        self._last_status_time = now

        self._client.publish(
            f"av/router/status",
            json.dumps({
                "client_id": self.client_id,
                "status": "running",
                "msg_count": self._msg_count,
                "timestamp": now,
            }, ensure_ascii=False),
        )


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(1)

    router = MQTTRouter(str(config_path))
    router.start()


if __name__ == "__main__":
    main()
