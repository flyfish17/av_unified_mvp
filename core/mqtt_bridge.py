"""
mqtt_bridge.py
MQTT通信层（main.py supervisor 用，不发公告——公告由 BaseModule 子类发）
"""
import json
import logging
import socket
import threading
import time
import uuid

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


class MQTTBridge:
    def __init__(self, cfg: dict):
        self.broker   = cfg.get("broker", "127.0.0.1")
        self.port     = cfg.get("port", 1883)
        # supervisor 自身的 MQTT client，无条件附加唯一后缀，与子模块（base_module.py）保持一致，
        # 防止 cfg 里 client_id=av_box_001 时和子模块共用同名被 broker 互踢
        base_cid = cfg.get("client_id", "av_box_001")
        self.client_id = f"{base_cid}_supervisor_{uuid.uuid4().hex[:6]}"
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
        # 注：旧 av/discovery 公告已废弃。统一公告走 BaseModule 的 av/system/discovery/<module>。
        # main.py supervisor 自身不是模块，不需要发公告。

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
            # 精确匹配 + 通配符（# 和 +）模式匹配
            callbacks = []
            for pattern, cbs in self._subscribers.items():
                if self._topic_matches(pattern, topic):
                    callbacks.extend(cbs)
        for cb in callbacks:
            try:
                cb(topic, payload)
            except Exception as e:
                logger.error(f"MQTT回调异常 [{topic}]: {e}")

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """MQTT 通配符匹配（# 和 +）"""
        if pattern == topic:
            return True
        pp, tp = pattern.split("/"), topic.split("/")
        return MQTTBridge._parts_match(pp, tp)

    @staticmethod
    def _parts_match(pp: list, tp: list) -> bool:
        if pp and pp[0] == "#":
            return True
        if not pp and not tp:
            return True
        if not pp or not tp:
            return False
        if pp[0] == "+" or pp[0] == tp[0]:
            return MQTTBridge._parts_match(pp[1:], tp[1:])
        return False

    # ── 发布/订阅 ─────────────────────────────────────────────────────

    def publish(self, topic: str, payload: dict | str, qos: int = 0):
        if not self._connected:
            return
        data = json.dumps(payload, ensure_ascii=False) if isinstance(payload, dict) else payload
        info = self._client.publish(topic, data, qos=qos)
        # qos=0 fire-and-forget 在 Flask 多线程并发时 paho sender 线程偶有 race 让 msg
        # 不到达 socket（5/20 实测：3 POST 仅 1 通）。wait_for_publish 让调用方 thread 等到
        # paho 完成 socket write 再返回——qos=0 时只 block 微秒级，但消除间歇 silent drop。
        try:
            info.wait_for_publish(timeout=2)
        except (RuntimeError, ValueError):
            pass

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
