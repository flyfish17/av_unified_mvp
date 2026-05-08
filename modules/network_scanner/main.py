#!/usr/bin/env python3
"""
modules/network_scanner/main.py
LAN 扫描模块（R6） - 独立进程
监听 av/system/lan_scan/cmd → 扫 /24 子网 → 进度 av/system/lan_scan/progress → 结果 av/system/lan_scan/result

cmd payload 字段（都可选）:
    subnet:     "192.168.5.0/24"   （默认用本机 /24）
    ports:      [22, 80, 443, 1883] （默认常见端口）
    timeout_ms: 200
"""
import ipaddress
import logging
import signal
import socket
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
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

DEFAULT_PORTS = [22, 80, 443, 1880, 1883, 5050, 8080, 8501, 11434]
DEFAULT_TIMEOUT_MS = 200
MAX_WORKERS = 64


class NetworkScannerModule(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        streams = [
            {
                "topic": "av/system/lan_scan/result",
                "channel": "lan_scan",
                "kind": "kv_table",
                "title": "LAN 扫描结果",
            },
            {
                "topic": "av/system/lan_scan/progress",
                "channel": "lan_scan",
                "kind": "kv_table",
                "title": "扫描进度",
            },
        ]
        # 推一个"启动扫描"控件给前端用
        endpoints = [{
            "kind": "scan_trigger",
            "topic": "av/system/lan_scan/cmd",
            "default_subnet": self._guess_default_subnet(),
            "ports": DEFAULT_PORTS,
            "timeout_ms": DEFAULT_TIMEOUT_MS,
        }]
        super().__init__("network_scanner", cfg, streams=streams, endpoints=endpoints)

        self._scan_lock = threading.Lock()
        self._scan_thread: threading.Thread | None = None

        self.subscribe("av/system/lan_scan/cmd")

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    # ── MQTT 入口 ────────────────────────────────────────────────────

    def _handle_message(self, topic: str, payload: dict) -> None:
        if "lan_scan/cmd" not in topic:
            return
        # 兼容直接 payload 或 BaseModule 包装的 {header, ...rest}
        body = payload.get("payload", payload) if isinstance(payload, dict) else {}
        # 如果是 BaseModule 包装，body 还是顶层字段，所以再看一层
        if not isinstance(body, dict):
            body = {}
        # 用户没传 subnet 等 → 直接传顶层
        subnet = body.get("subnet") or payload.get("subnet")
        ports = body.get("ports") or payload.get("ports") or DEFAULT_PORTS
        timeout_ms = body.get("timeout_ms") or payload.get("timeout_ms") or DEFAULT_TIMEOUT_MS

        if self._scan_thread and self._scan_thread.is_alive():
            self.logger.info("已有扫描在跑，忽略新指令")
            return

        self._scan_thread = threading.Thread(
            target=self._do_scan,
            args=(subnet, list(ports), int(timeout_ms)),
            daemon=True,
        )
        self._scan_thread.start()

    # ── 扫描实现 ─────────────────────────────────────────────────────

    @staticmethod
    def _guess_default_subnet() -> str:
        return NetworkScannerModule._local_subnet()

    @staticmethod
    def _local_subnet() -> str:
        """从本机非 lo 接口推断一个 /24 子网。"""
        try:
            for name, addrs in psutil.net_if_addrs().items():
                stats = psutil.net_if_stats().get(name)
                if not stats or not stats.isup:
                    continue
                for a in addrs:
                    if a.family == socket.AF_INET and not a.address.startswith("127."):
                        net = ipaddress.IPv4Network(f"{a.address}/24", strict=False)
                        return str(net)
        except Exception:
            pass
        return "192.168.1.0/24"

    @staticmethod
    def _probe(ip: str, ports: list[int], timeout: float) -> list[int]:
        """逐端口 TCP 连，返回开着的端口列表。"""
        open_ports = []
        for p in ports:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    s.settimeout(timeout)
                    if s.connect_ex((ip, p)) == 0:
                        open_ports.append(p)
            except OSError:
                pass
        return open_ports

    def _do_scan(self, subnet: str | None, ports: list[int], timeout_ms: int) -> None:
        with self._scan_lock:
            scan_id = uuid.uuid4().hex[:8]
            subnet_str = subnet or self._local_subnet()
            try:
                net = ipaddress.IPv4Network(subnet_str, strict=False)
            except ValueError as e:
                self.publish("av/system/lan_scan/result", {
                    "type": "error", "scan_id": scan_id, "error": str(e),
                })
                return

            hosts = [str(h) for h in net.hosts()]
            total = len(hosts)
            timeout = timeout_ms / 1000.0
            t0 = time.time()
            self.logger.info(f"开始扫描 {subnet_str} ({total} 主机, ports={ports}, timeout={timeout_ms}ms)")

            alive: list[dict] = []
            scanned = 0
            last_progress = 0
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
                futs = {pool.submit(self._probe, h, ports, timeout): h for h in hosts}
                for fut in as_completed(futs):
                    scanned += 1
                    ip = futs[fut]
                    try:
                        open_ports = fut.result()
                    except Exception:
                        open_ports = []
                    if open_ports:
                        alive.append({"ip": ip, "ports": open_ports})
                    # 每扫 25 台或 5%（哪个先到）发一次进度
                    if scanned - last_progress >= max(25, total // 20):
                        last_progress = scanned
                        self.publish("av/system/lan_scan/progress", {
                            "type": "progress",
                            "scan_id": scan_id,
                            "scanned": scanned,
                            "total": total,
                            "alive": len(alive),
                            "ts": time.time(),
                        })

            duration = round(time.time() - t0, 2)
            alive.sort(key=lambda x: tuple(int(p) for p in x["ip"].split(".")))
            self.publish("av/system/lan_scan/result", {
                "type": "result",
                "scan_id": scan_id,
                "subnet": subnet_str,
                "ports": ports,
                "scanned": scanned,
                "alive_hosts": alive,
                "duration_s": duration,
                "ts": time.time(),
            })
            self.logger.info(f"扫描完成 [{scan_id}] {len(alive)}/{total} 台存活，耗时 {duration}s")


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    NetworkScannerModule(str(config_path)).run()


if __name__ == "__main__":
    main()
