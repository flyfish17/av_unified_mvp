#!/usr/bin/env python3
"""
modules/system_info/main.py
主机指标采集模块（R6） - 独立进程
每 PUBLISH_INTERVAL 秒推一次 CPU / 内存 / 磁盘 / 负载 到 av/system/host_stats
"""
import logging
import signal
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

PUBLISH_INTERVAL = 5  # 秒


class SystemInfoModule(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        streams = [{
            "topic": "av/system/host_stats",
            "channel": "host_stats",
            "kind": "kv_table",
            "title": "主机指标",
        }]
        super().__init__("system_info", cfg, streams=streams)

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        # 不订阅任何主题
        pass

    def _collect(self) -> dict:
        vm = psutil.virtual_memory()
        try:
            load1, load5, load15 = psutil.getloadavg()
        except (AttributeError, OSError):
            load1 = load5 = load15 = 0.0
        try:
            disk = psutil.disk_usage("/")
            disk_pct = disk.percent
        except Exception:
            disk_pct = 0.0
        return {
            "ts": time.time(),
            "cpu_percent": psutil.cpu_percent(interval=None),
            "cpu_count": psutil.cpu_count(),
            "mem_percent": vm.percent,
            "mem_used_gb": round(vm.used / 1024**3, 2),
            "mem_total_gb": round(vm.total / 1024**3, 2),
            "disk_percent": disk_pct,
            "load1": round(load1, 2),
            "load5": round(load5, 2),
            "load15": round(load15, 2),
        }

    def run(self) -> None:
        """覆盖 BaseModule.run：心跳 + 周期发布合并到一个循环。"""
        self.start()
        last_heartbeat = time.time()
        last_publish = 0.0
        # 第一次 cpu_percent 返回 0，先 prime 一下
        psutil.cpu_percent(interval=None)
        try:
            while self._running.is_set():
                time.sleep(1)
                now = time.time()
                if now - last_publish >= PUBLISH_INTERVAL and self._connected:
                    self.publish("av/system/host_stats", self._collect())
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
    SystemInfoModule(str(config_path)).run()


if __name__ == "__main__":
    main()
