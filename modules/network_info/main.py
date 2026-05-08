#!/usr/bin/env python3
"""
modules/network_info/main.py
网络信息采集模块（R6） - 独立进程
每 PUBLISH_INTERVAL 秒推一次网卡 IP + 收发字节速率到 av/system/network
"""
import logging
import signal
import socket
import sys
import time
from pathlib import Path

import psutil
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

PUBLISH_INTERVAL = 10  # 秒


class NetworkInfoModule(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        streams = [{
            "topic": "av/system/network",
            "channel": "network",
            "kind": "kv_table",
            "title": "网络状态",
        }]
        super().__init__("network_info", cfg, streams=streams)

        # 上次的 net_io_counters 快照，用来算速率
        self._prev_io: dict[str, tuple[int, int, float]] = {}

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        pass

    @staticmethod
    def _ipv4_of(iface: str, addrs: list) -> str | None:
        for a in addrs:
            if a.family == socket.AF_INET:
                return a.address
        return None

    def _collect(self) -> dict:
        now = time.time()
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        io = psutil.net_io_counters(pernic=True)

        ifs = []
        for name, addr_list in addrs.items():
            if not stats.get(name) or not stats[name].isup:
                continue
            ip = self._ipv4_of(name, addr_list)
            if ip is None or ip.startswith("127."):
                continue
            cur = io.get(name)
            if not cur:
                continue
            sent_kbps = recv_kbps = 0.0
            prev = self._prev_io.get(name)
            if prev:
                p_sent, p_recv, p_ts = prev
                dt = max(now - p_ts, 0.001)
                sent_kbps = round((cur.bytes_sent - p_sent) / dt / 1024, 1)
                recv_kbps = round((cur.bytes_recv - p_recv) / dt / 1024, 1)
            self._prev_io[name] = (cur.bytes_sent, cur.bytes_recv, now)
            ifs.append({
                "name": name,
                "ip": ip,
                "speed_mbps": stats[name].speed,
                "sent_kbps": sent_kbps,
                "recv_kbps": recv_kbps,
            })
        return {"ts": now, "interfaces": ifs}

    def run(self) -> None:
        self.start()
        last_heartbeat = time.time()
        last_publish = 0.0
        try:
            while self._running.is_set():
                time.sleep(1)
                now = time.time()
                if now - last_publish >= PUBLISH_INTERVAL and self._connected:
                    self.publish("av/system/network", self._collect())
                    last_publish = now
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
    NetworkInfoModule(str(config_path)).run()


if __name__ == "__main__":
    main()
