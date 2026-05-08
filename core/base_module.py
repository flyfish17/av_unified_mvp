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
from typing import Callable, List, Optional

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

    VERSION = "1.2"
    DISCOVERY_PREFIX = "av/system/discovery"
    HEARTBEAT_INTERVAL = 30  # 默认心跳秒数；子类可重写

    def __init__(
        self,
        name: str,
        config: dict,
        mqtt_config_key: str = "mqtt",
        streams: Optional[list] = None,
        endpoints: Optional[list] = None,
    ):
        self.name = name
        self.cfg = config
        self.logger = logging.getLogger(name)

        # 公告内容：模块声明自己提供哪些 stream / endpoint，UI 据此选 renderer
        self.streams = streams or []
        self.endpoints = endpoints or []

        # MQTT配置
        mqtt_cfg = config.get(mqtt_config_key, {})
        self.broker = mqtt_cfg.get("broker", "127.0.0.1")
        self.port = mqtt_cfg.get("port", 1883)
        # 每个模块附加唯一后缀，避免和 supervisor / 兄弟模块共用 client_id
        # 否则 MQTT broker 会踢掉前一个连接，导致所有模块连/断风暴
        base_cid = mqtt_cfg.get("client_id", "av_box_001")
        self.client_id = f"{base_cid}_{name}_{uuid.uuid4().hex[:6]}"
        self._keepalive = mqtt_cfg.get("keepalive", 60)
        self._discovery_topic = f"{self.DISCOVERY_PREFIX}/{name}"

        # Paho MQTT v2 API
        self._client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        # LWT：模块崩溃 / 网络断 broker 自动发 offline，retain 让后开 UI 也能看到
        will_payload = json.dumps(
            self._discovery_payload("offline"),
            ensure_ascii=False,
        )
        self._client.will_set(
            self._discovery_topic, will_payload, qos=1, retain=True
        )

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

    def _discovery_payload(self, event: str) -> dict:
        """构造公告载荷。event ∈ {online, heartbeat, offline}。"""
        return {
            "module": self.name,
            "client_id": self.client_id,
            "ip": self._get_local_ip(),
            "ts": time.time(),
            "event": event,
            "heartbeat_interval": self.HEARTBEAT_INTERVAL,
            "version": self.VERSION,
            "streams": self.streams,
            "endpoints": self.endpoints,
        }

    def _publish_discovery(self, event: str) -> None:
        """
        发布公告到 av/system/discovery/<module>。
        retain=True 保证后开订阅的 UI 立即看到当前所有模块。
        """
        payload = self._discovery_payload(event)
        msg = json.dumps(payload, ensure_ascii=False)
        # 直接 client.publish 而非 self.publish，避免 BaseModule.publish 的 header 包装。
        # 公告本身就是 metadata，不该再套一层 header。
        self._client.publish(
            self._discovery_topic, msg, qos=1, retain=True
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
        """停止模块。优雅关闭时主动发 offline，覆盖 LWT 占位。"""
        self.logger.info(f"停止 {self.name}...")
        self._running.clear()
        try:
            self._publish_discovery("offline")
        except Exception as e:
            self.logger.warning(f"发布 offline 失败: {e}")
        self._client.loop_stop()
        self._client.disconnect()
        self.logger.info(f"{self.name} 已停止")

    def run(self) -> None:
        """
        启动并阻塞主线程，直到收到停止信号。
        每 HEARTBEAT_INTERVAL 秒重发一次 retain 公告，UI 用它判断模块是否活着。
        """
        self.start()
        last_heartbeat = time.time()
        try:
            while self._running.is_set():
                time.sleep(1)
                if time.time() - last_heartbeat >= self.HEARTBEAT_INTERVAL:
                    if self._connected:
                        self._publish_discovery("heartbeat")
                    last_heartbeat = time.time()
        except KeyboardInterrupt:
            self.logger.info("收到键盘中断信号")
        finally:
            self.stop()
