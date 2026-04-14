"""
mqtt_bridge.py
MQTT通信层 + 设备发现（mDNS广播）
"""
import json
import logging
import socket
import threading
import time
from datetime import datetime

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTBridge:
    def __init__(self, cfg: dict):
        self.broker   = cfg.get("broker", "127.0.0.1")
        self.port     = cfg.get("port", 1883)
        self.client_id = cfg.get("client_id", "av_box_001")
        self.topics   = cfg.get("topics", {})

        self._client  = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=self.client_id)
        self._client.on_connect    = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message    = self._on_message

        self._connected   = False
        self._subscribers = {}  # topic -> [callback]
        self._lock        = threading.Lock()
        self._running     = True

    # ── 连接管理 ──────────────────────────────────────────────────────

    def start(self):
        """启动MQTT，失败时每5秒重试"""
        threading.Thread(target=self._connect_loop, daemon=True).start()

    def _connect_loop(self):
        while self._running:
            try:
                self._client.connect(self.broker, self.port, keepalive=60)
                self._client.loop_start()
                logger.info(f"MQTT 已连接 {self.broker}:{self.port}")
                return
            except Exception as e:
                if self._running:
                    logger.warning(f"MQTT 连接失败: {e}，5秒后重试")
                    time.sleep(5)

    def stop(self):
        """停止MQTT连接"""
        self._running = False
        try:
            self._client.loop_stop()
            self._client.disconnect()
        except Exception:
            pass
        self._connected = False
        logger.info("MQTT 已停止")

    def _on_connect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = True
        # 重连后重新订阅
        for topic in self._subscribers:
            client.subscribe(topic)
        # 广播设备上线
        self.publish(self.topics.get("discovery", "av/discovery"), {
            "event":     "online",
            "client_id": self.client_id,
            "ip":        self._local_ip(),
            "time":      datetime.now().isoformat(),
        })

    def _on_disconnect(self, client, userdata, flags, reason_code, properties=None):
        self._connected = False
        logger.warning("MQTT 断开，等待自动重连")

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode())
        except Exception:
            payload = msg.payload.decode()

        with self._lock:
            callbacks = self._subscribers.get(topic, [])
        for cb in callbacks:
            try:
                cb(topic, payload)
            except Exception as e:
                logger.error(f"MQTT回调异常 [{topic}]: {e}")

    # ── 发布/订阅 ─────────────────────────────────────────────────────

    def publish(self, topic: str, payload: dict | str, qos: int = 0):
        if not self._connected:
            return
        data = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload
        self._client.publish(topic, data, qos=qos)

    def subscribe(self, topic: str, callback):
        with self._lock:
            self._subscribers.setdefault(topic, []).append(callback)
        if self._connected:
            self._client.subscribe(topic)

    # ── 工具 ──────────────────────────────────────────────────────────

    @staticmethod
    def _local_ip() -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            ip = s.getsockname()[0]
            s.close()
            return ip
        except Exception:
            return "127.0.0.1"

    @property
    def connected(self) -> bool:
        return self._connected
