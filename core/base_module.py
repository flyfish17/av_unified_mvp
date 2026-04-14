#!/usr/bin/env python3
"""
core/base_module.py
AV统一系统 - 模块基类
提供通用MQTT发布/订阅能力，所有独立模块继承此类
"""
import json
import logging
import socket
import time
import uuid
from abc import ABC, abstractmethod
from threading import Event, Thread
from typing import Callable, Optional

import paho.mqtt.client as mqtt


class BaseModule(ABC):
    """
    所有模块的基类

    使用方式:
        class MyModule(BaseModule):
            def __init__(self, config: dict):
                super().__init__("my_module", config)
                ...

            def _handle_message(self, topic: str, payload: dict):
                # 处理收到的MQTT消息
                pass

        module = MyModule(config)
        module.start()
    """

    VERSION = "1.1"

    def __init__(
        self,
        name: str,
        config: dict,
        mqtt_config_key: str = "mqtt",
    ):
        self.name = name
        self.cfg = config
        self.logger = logging.getLogger(name)

        # MQTT配置
        mqtt_cfg = config.get(mqtt_config_key, {})
        self.broker = mqtt_cfg.get("broker", "127.0.0.1")
        self.port = mqtt_cfg.get("port", 1883)
        self.client_id = mqtt_cfg.get("client_id", f"{name}_{uuid.uuid4().hex[:8]}")
        self._keepalive = mqtt_cfg.get("keepalive", 60)

        # Paho MQTT v2 API
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # 状态
        self._connected = False
        self._running = Event()
        self._subscriptions: dict[str, int] = {}
        self._msg_count = 0

    # ── 抽象方法 ──────────────────────────────────────────────────────

    @abstractmethod
    def _handle_message(self, topic: str, payload: dict) -> None:
        """
        子类实现：处理接收到的MQTT消息

        Args:
            topic: 消息主题
            payload: 消息内容（已解析的字典）
        """
        pass

    # ── MQTT回调 ──────────────────────────────────────────────────────

    def _on_connect(
        self,
        client,
        userdata,
        flags,
        reason_code: int,
        properties=None,
    ) -> None:
        if reason_code == 0:
            self._connected = True
            self.logger.info(f"已连接 MQTT Broker {self.broker}:{self.port}")
            # 重新订阅之前注册的主题
            for topic, qos in self._subscriptions.items():
                client.subscribe(topic, qos)
            # 发布上线消息
            self._publish_discovery("online")
        else:
            self.logger.warning(f"MQTT连接失败，reason_code={reason_code}")

    def _on_disconnect(
        self,
        client,
        userdata,
        flags,
        reason_code: int,
        properties=None,
    ) -> None:
        self._connected = False
        self.logger.warning("MQTT 连接断开")

    def _on_message(
        self,
        client,
        userdata,
        msg,
    ) -> None:
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
            self._msg_count += 1
            self.logger.debug(f"[{self._msg_count}] {msg.topic}: {payload.get('header', {}).get('msg_id', 'N/A')}")
            self._handle_message(msg.topic, payload)
        except json.JSONDecodeError:
            self.logger.warning(f"消息解析失败: {msg.payload[:100]}")
        except Exception as e:
            self.logger.error(f"消息处理异常: {e}")

    # ── 订阅/发布 ─────────────────────────────────────────────────────

    def subscribe(self, topic: str, qos: int = 0) -> None:
        """
        订阅MQTT主题

        Args:
            topic: 主题（支持通配符 + 和 #）
            qos: 服务质量等级（0, 1, 2）
        """
        self._subscriptions[topic] = qos
        if self._connected:
            self._client.subscribe(topic, qos)
            self.logger.info(f"订阅: {topic} (QoS={qos})")

    def publish(
        self,
        topic: str,
        payload: dict,
        qos: int = 0,
        retain: bool = False,
    ) -> None:
        """
        发布MQTT消息（自动封装header）

        Args:
            topic: 目标主题
            payload: 消息内容
            qos: 服务质量等级
            retain: 是否保留消息
        """
        if not self._connected:
            self.logger.warning("MQTT未连接，消息被丢弃")
            return

        enriched = {
            "header": {
                "msg_id": uuid.uuid4().hex,
                "timestamp": time.time(),
                "source": self.name,
                "version": self.VERSION,
            },
            **payload,
        }

        msg = json.dumps(enriched, ensure_ascii=False)
        result = self._client.publish(topic, msg, qos, retain)
        if result.rc != mqtt.MQTT_ERR_SUCCESS:
            self.logger.error(f"发布失败: {topic}, rc={result.rc}")
        else:
            self.logger.debug(f"发布: {topic}")

    def _publish_discovery(self, event_type: str) -> None:
        """
        发布设备发现消息

        Args:
            event_type: "online" 或 "offline"
        """
        ip = self._get_local_ip()
        self.publish(
            "av/system/discovery",
            {
                "event": event_type,
                "client_id": self.client_id,
                "module": self.name,
                "ip": ip,
                "timestamp": time.time(),
            },
        )

    def _publish_status(self) -> None:
        """发布自身状态心跳"""
        self.publish(
            f"av/{self.name}/status",
            {
                "topic_type": "status",
                "payload": {
                    "module": self.name,
                    "status": "running" if self._running.is_set() else "stopped",
                    "uptime_seconds": getattr(self, "_uptime_start", time.time()),
                    "msg_count": self._msg_count,
                },
            },
        )

    @staticmethod
    def _get_local_ip() -> str:
        """获取本机局域网IP"""
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    # ── 生命周期 ─────────────────────────────────────────────────────

    def start(self) -> None:
        """启动模块"""
        self.logger.info(f"启动 {self.name}...")
        self._running.set()
        self._uptime_start = time.time()
        self._client.connect(self.broker, self.port, keepalive=self._keepalive)
        self._client.loop_start()
        self.logger.info(f"{self.name} 已启动")

    def stop(self) -> None:
        """停止模块"""
        self.logger.info(f"停止 {self.name}...")
        self._running.clear()
        self._publish_discovery("offline")
        self._client.loop_stop()
        self._client.disconnect()
        self.logger.info(f"{self.name} 已停止")

    def run(self) -> None:
        """
        启动并阻塞主线程，直到收到停止信号

        使用方式:
            module = MyModule(config)
            module.run()
        """
        self.start()
        try:
            while self._running.is_set():
                time.sleep(1)
                # 定期发布状态（每60秒）
                if hasattr(self, "_uptime_start"):
                    if time.time() - getattr(self, "_last_status", 0) > 60:
                        self._publish_status()
                        self._last_status = time.time()
        except KeyboardInterrupt:
            self.logger.info("收到键盘中断信号")
        finally:
            self.stop()
