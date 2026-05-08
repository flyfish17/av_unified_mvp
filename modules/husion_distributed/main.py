#!/usr/bin/env python3
"""
modules/husion_distributed/main.py
跨品牌桥接：Husion HDC900 一体机分布式终端发现 + 流地址透出

只做"主消费"模式 — 拉 husion 设备列表到 av_unified_mvp 前端展示，
不替代 husion 自带管理平台、不做视频墙拼接控制（那部分 husion 自己做得够好）。
辅模式（AI 分析结果反推为 husion 字幕）作下次扩展。

协议：TCP :6000 + JSON `{"cmd_header":"hscmd-...","cmd_body":{...}}`
PDF：产品系统通讯协议-A_V9.4.8_Husion v9.4.8

设备 ID 范围（白鲨 RX）：5001-6999；用户 HDC900 实测 5001-5009 共 9 路。
"""
import json
import logging
import signal
import socket
import sys
import threading
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

# 默认值（system_config.yaml 的 husion: 段可覆盖）
DEFAULT_HOST = "192.168.5.253"
DEFAULT_PORT = 6000
DEFAULT_ID_RANGES = [[5001, 5009]]   # [[start, end_inclusive], ...]
DEFAULT_POLL_INTERVAL = 30           # 秒
TCP_TIMEOUT = 4.0


def _tcp_query(host: str, port: int, payload: dict, timeout: float = TCP_TIMEOUT) -> dict:
    """husion TCP 短连接 + JSON 请求/响应。

    返回 parsed dict 或 None。响应没有长度前缀，靠"短时间无新数据"判定结束。
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        sock.sendall(json.dumps(payload).encode("utf-8"))
        chunks = []
        sock.settimeout(0.5)
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                d = sock.recv(8192)
                if not d:
                    break
                chunks.append(d)
            except socket.timeout:
                if chunks:
                    break
                continue
    finally:
        try:
            sock.close()
        except Exception:
            pass
    raw = b"".join(chunks).decode("utf-8", errors="replace")
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return None


class HusionDistributedModule(BaseModule):
    """husion HDC900 一体机分布式终端发现器。

    周期 poll → 更新 self.endpoints → 心跳广播 discovery，前端从 endpoints 拿流地址。
    """

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        h = (cfg.get("husion") or {})
        self.husion_host = h.get("host", DEFAULT_HOST)
        self.husion_port = int(h.get("port", DEFAULT_PORT))
        self.id_ranges = h.get("id_ranges", DEFAULT_ID_RANGES)
        self.poll_interval = float(h.get("poll_interval", DEFAULT_POLL_INTERVAL))

        # 启动时 endpoints 空，第一次 poll 后填充
        super().__init__("husion_distributed", cfg, streams=[], endpoints=[])

        self._poll_lock = threading.Lock()
        self._last_poll_ok = False
        self._last_poll_ts = 0.0

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        # 不订阅任何主题
        pass

    def _expand_ids(self) -> list[str]:
        ids: list[str] = []
        for r in self.id_ranges:
            if isinstance(r, (list, tuple)) and len(r) == 2:
                ids.extend(str(i) for i in range(int(r[0]), int(r[1]) + 1))
        return ids

    def _fetch_rx_devices(self) -> list[dict]:
        """拿白鲨 RX 设备清单（含 hls 流地址）"""
        ids = self._expand_ids()
        if not ids:
            return []
        body = {
            "cmd_header": "hscmd-get-rx-shark-config",
            "cmd_body": {
                "idList": ids,
                "name": "y", "id": "y", "ip": "y",
                "rtsp": "y", "hls": "y",
                "isSignal": "y", "online": "y",
            },
        }
        resp = _tcp_query(self.husion_host, self.husion_port, body)
        if not resp:
            return []
        params = ((resp.get("cmd_body") or {}).get("parameter")) or []
        return params if isinstance(params, list) else []

    def _device_to_endpoint(self, dev: dict) -> dict:
        """把 husion 设备数据转成 av_unified_mvp endpoint 形态（前端能渲染）。"""
        hls = dev.get("hls") or ""
        # husion 的 hls 字段实际是 ws://...flv（WebSocket-FLV，浏览器需 flv.js 库）
        stream_type = "flv" if "/live/" in hls and ".flv" in hls else (
            "hls" if hls.endswith(".m3u8") else "unknown"
        )
        rtsp = dev.get("rtsp") or ""
        return {
            "kind":         "husion_stream",
            "name":         dev.get("name") or f"husion-{dev.get('id', '')}",
            "device_id":    dev.get("id"),
            "device_ip":    dev.get("ip"),
            "host":         self.husion_host,
            "stream_url":   hls,
            "stream_type":  stream_type,
            "rtsp_url":     rtsp or None,
            "is_signal":    dev.get("isSignal") == "y",
            "online":       dev.get("online", ""),
            # 给前端"在线视频源"select 当 option label 用
            "label":        f"{dev.get('name','?')} [husion {dev.get('id','')}]"
                            f"{' · 无信号' if dev.get('isSignal') != 'y' else ''}",
            "enabled":      dev.get("isSignal") == "y",  # 默认只让有信号的能选
        }

    def _poll_once(self):
        with self._poll_lock:
            try:
                devices = self._fetch_rx_devices()
                eps = [self._device_to_endpoint(d) for d in devices]
                self.endpoints = eps
                self._last_poll_ok = True
                self._last_poll_ts = time.time()
                # 重新广播 discovery 让前端看到新 endpoints
                if self._connected:
                    self._publish_discovery("online")
                self.logger.info(
                    f"husion poll OK：{len(eps)} 设备（{sum(1 for e in eps if e['is_signal'])} 有信号）"
                )
            except Exception as e:
                self._last_poll_ok = False
                self.logger.warning(f"husion poll 失败 ({self.husion_host}:{self.husion_port})：{e}")

    def run(self) -> None:
        """覆盖 BaseModule.run：心跳 + 周期 poll husion 合一。"""
        self.start()
        self.logger.info(
            f"husion 配置：host={self.husion_host}:{self.husion_port} ranges={self.id_ranges} poll={self.poll_interval}s"
        )
        last_heartbeat = time.time()
        last_poll = 0.0
        try:
            while self._running.is_set():
                time.sleep(1)
                now = time.time()
                if now - last_poll >= self.poll_interval and self._connected:
                    self._poll_once()
                    last_poll = now
                if now - last_heartbeat >= self.HEARTBEAT_INTERVAL and self._connected:
                    self._publish_discovery("heartbeat")
                    last_heartbeat = now
        except KeyboardInterrupt:
            self.logger.info("收到键盘中断信号")
        finally:
            self.stop()


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    HusionDistributedModule(str(config_path)).run()


if __name__ == "__main__":
    main()
