#!/usr/bin/env python3
"""
main_jetson.py — Jetson 深思层 minimal supervisor
只起 4 个模块（不跑 audio/video/husion/network_scanner，与 3588 重复占资源）：
  - llm_engine        ollama qwen3 后端，M3 后接 av/llm/escalate
  - system_info       本机监控
  - network_info      网络/带宽观测
  - control_dispatcher 让 Jetson 也能把 cmd 回写 av/control（M3 用）
不动 main.py — 那是 Mac/3588 的入口；Jetson 用本文件启。
"""
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import yaml
sys.path.insert(0, str(Path(__file__).parent))
from core.mqtt_bridge import MQTTBridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

JETSON_MANAGED_MODULES = [
    "modules.llm_engine.main",
    "modules.system_info.main",
    "modules.network_info.main",
    "modules.control_dispatcher.main",
]

MAX_RETRY_DELAY = 60
WARN_AFTER_FAILS = 5


class JetsonSupervisor:
    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)
        self._config_path = Path(config_path)
        self._project_root = self._config_path.parent.parent
        self.mqtt = MQTTBridge(self.cfg.get("mqtt", {}))
        self._procs: dict = {}
        self._running = False

    def start(self):
        logger.info("=" * 60)
        logger.info("  Jetson 深思层 Supervisor 启动中 (4 modules)")
        logger.info("=" * 60)
        try:
            self.mqtt.start()
            logger.info("[supervisor] MQTTBridge started")
        except Exception as e:
            logger.warning(f"[supervisor] MQTTBridge start 失败 {e}（不阻塞模块）")
        self._spawn_all()
        self._running = True
        logger.info("OK Jetson Supervisor 已启动")
        try:
            while self._running:
                self._tick()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("收到停止信号")
        self.stop()

    def stop(self):
        self._running = False
        for module, state in self._procs.items():
            proc = state["proc"]
            if proc.poll() is None:
                logger.info(f"  终止 {module} (PID={proc.pid})")
                proc.terminate()
                try: proc.wait(timeout=5)
                except subprocess.TimeoutExpired: proc.kill()
        try: self.mqtt.stop()
        except Exception: pass

    def _spawn(self, module: str) -> subprocess.Popen:
        proc = subprocess.Popen(
            [sys.executable, "-m", module],
            cwd=str(self._project_root),
            env=os.environ.copy(),
        )
        logger.info(f"[supervisor] 拉起 {module} (PID={proc.pid})")
        return proc

    def _spawn_all(self):
        now = time.time()
        for module in JETSON_MANAGED_MODULES:
            proc = self._spawn(module)
            self._procs[module] = {
                "proc": proc, "fail_count": 0, "retry_delay": 1.0,
                "next_retry": now, "spawn_time": now,
            }

    def _tick(self):
        now = time.time()
        for module, state in self._procs.items():
            if state["proc"].poll() is None:
                continue
            if now < state["next_retry"]:
                continue
            if now - state["spawn_time"] > MAX_RETRY_DELAY:
                state["fail_count"] = 0
                state["retry_delay"] = 1.0
            state["fail_count"] += 1
            if state["fail_count"] >= WARN_AFTER_FAILS:
                logger.error(f"[supervisor] {module} 连续 {state['fail_count']} 次崩溃")
            else:
                logger.warning(f"[supervisor] {module} 退出，{state['retry_delay']:.0f}s 后重拉")
            proc = self._spawn(module)
            state["proc"] = proc
            state["spawn_time"] = now
            state["retry_delay"] = min(state["retry_delay"] * 2, MAX_RETRY_DELAY)
            state["next_retry"] = now + state["retry_delay"]


def main():
    config_path = Path(__file__).parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    sup = JetsonSupervisor(str(config_path))
    sup.start()


if __name__ == "__main__":
    main()
