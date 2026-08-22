#!/usr/bin/env python3
"""
modules/device_state/main.py — 设备真状态回读（阶段三 ③）

只读轮询真设备，把"设备现在到底开没开"发到总线，Node-RED 面板/语音/告警三方共用；
面板只反映 state，不再自己翻转（架构定型见 docs/探讨-跨模块跨系统信息共享-20260822.md §2）。

当前实现：中央空调 ×4（Modbus 03 只读，经 USR-TCP232 网关）。继电器（灯/窗帘，CR-POWER8-SPM 查询帧）待抓样本后加。
发布：av/device/state/<key>  retain  {kind, label, on, mode, fan, temp, ok, ts}
      查询失败 → {ok:false, error} 同样发出（retain），让面板知道"读不到"而不是沿用旧值。
config:
  device_state:
    enabled: true
    interval: 10            # 秒，整轮周期（4 台串行，每台 ≤2s）
    ac_gateway: {host: 192.168.5.211, port: 82}
    ac: [{key: 2FDiningTable_AirConditioner, label: 二楼餐桌空调, base_reg: 0x9C5C}, ...]
"""
import logging
import signal
import sys
import time
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule
from modules.device_state.modbus_ac import read_ac

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%H:%M:%S")

DEFAULT_AC = [
    {"key": "2FDiningTable_AirConditioner", "label": "二楼餐桌空调", "base_reg": 0x9C5C},
    {"key": "RDDepartment_AirConditioner", "label": "研发部空调", "base_reg": 0x9CB7},
    {"key": "EngineRoom_AirConditioner", "label": "机房空调", "base_reg": 0x9D12},
    {"key": "OperateCentre_AirConditioner", "label": "运营中心空调", "base_reg": 0x9D6D},
]


class DeviceStateModule(BaseModule):
    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        ds = cfg.get("device_state") or {}
        self.interval = float(ds.get("interval", 10))
        gw = ds.get("ac_gateway") or {}
        self.gw_host = gw.get("host", "192.168.5.211")
        self.gw_port = int(gw.get("port", 82))
        self.acs = ds.get("ac") or DEFAULT_AC
        for a in self.acs:
            if isinstance(a.get("base_reg"), str):
                a["base_reg"] = int(a["base_reg"], 16)
        streams = [{"topic": "av/device/state/+", "channel": "device_state", "kind": "kv_table", "title": "设备真状态"}]
        super().__init__("device_state", cfg, streams=streams)
        self._last: dict = {}
        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        pass

    def _poll_once(self) -> None:
        for a in self.acs:
            key = a["key"]
            try:
                st = read_ac(self.gw_host, self.gw_port, a["base_reg"])
                payload = {"kind": "ac", "label": a["label"], "ok": True, "ts": time.time(), **st}
            except Exception as e:  # 读不到也要发：面板该显示"未知"，不是沿用旧值
                payload = {"kind": "ac", "label": a["label"], "ok": False, "error": str(e)[:120], "ts": time.time()}
            sig = (payload.get("ok"), payload.get("on"), payload.get("mode"), payload.get("fan"), payload.get("temp"))
            if self._last.get(key) != sig:
                self.logger.info(f"{a['label']}: {payload if payload['ok'] else '读取失败 ' + payload['error']}")
                self._last[key] = sig
            self.publish(f"av/device/state/{key}", payload, retain=True)
            time.sleep(0.3)  # RS485 半双工，给网关喘口气

    def run(self) -> None:
        self.start()
        self.logger.info(f"device_state 已启动：空调 ×{len(self.acs)} 经 {self.gw_host}:{self.gw_port}，每 {self.interval:.0f}s")
        last_poll = 0.0
        last_hb = time.time()
        try:
            while self._running.is_set():
                time.sleep(0.5)
                now = time.time()
                if self._connected and now - last_poll >= self.interval:
                    self._poll_once()
                    last_poll = now
                if now - last_hb >= self.HEARTBEAT_INTERVAL:
                    self._publish_discovery("heartbeat")
                    last_hb = now
        finally:
            self.stop()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=str(Path(__file__).parent.parent.parent / "config" / "system_config.yaml"))
    DeviceStateModule(ap.parse_args().config).run()
