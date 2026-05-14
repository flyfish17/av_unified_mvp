#!/usr/bin/env python3
"""
modules/control_dispatcher/main.py
av/control → 设备的最后一公里 dispatcher。

当前实现：echo-only — 订阅 av/control 拿到 cmd_id 后：
  1. catalog 反查得到 device/action/location 中文 label
  2. 发 av/control/dispatched，状态 echo_only（用于 dashboard 演示反馈）
  3. log 到本地 stdout

后续接真实设备时，把 _dispatch() 内 status="echo_only" 替换为：
  husion adapter (5/12 husion_distributed 已发现 9 设备) /
  Node-RED :1880/siri / 厂商 SDK / 直接 MQTT 设备 topic。

新增 stream：dashboard 自动新增"指令下发"面板订阅 av/control/dispatched。
"""
import json
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Optional

import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


def _build_cmd_lookup() -> dict:
    """{cmd_id: {device, action, location, device_label, action_label, location_label, **adapter_params}}

    一次性从 catalog 摊开，避免每条 av/control 都重读 catalog。
    adapter_params 透传 cmd 上的额外字段（如 husion 的 scene_name / rx_id）给 adapter。
    """
    catalog_path = Path(__file__).parent.parent.parent / "config" / "device_catalog.json"
    if not catalog_path.exists():
        return {}
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    loc_to_label = {l["id"]: l["label"] for l in catalog.get("locations", [])}
    device_types = catalog.get("device_types", {})
    out = {}
    for c in catalog.get("commands", []):
        cid = c.get("id")
        if not cid:
            continue
        dev = c.get("device", "")
        action = c.get("action", "")
        dev_meta = device_types.get(dev, {})
        # 透传 cmd 上除核心字段外的额外字段（adapter 用，如 scene_name / rx_id）
        extra = {k: v for k, v in c.items() if k not in ("id", "device", "action", "location", "label", "also_in")}
        out[cid] = {
            "device": dev,
            "action": action,
            "location": c.get("location", ""),
            "device_label": dev_meta.get("label", dev),
            "action_label": (dev_meta.get("actions_label") or {}).get(action, action),
            "location_label": loc_to_label.get(c.get("location", ""), c.get("location", "")),
            **extra,
        }
    return out


class ControlDispatcher(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        # 声明 stream → 让 dashboard 自动渲染"指令下发"面板
        streams = [{
            "topic": "av/control/dispatched",
            "channel": "control_dispatched",
            "kind": "kv_table",
            "title": "指令下发执行",
        }]
        super().__init__("control_dispatcher", cfg, streams=streams)

        self._lookup = _build_cmd_lookup()
        self.logger.info(f"cmd 反查表：{len(self._lookup)} 条")

        # 订阅控制总线
        self.subscribe(cfg.get("mqtt", {}).get("topics", {}).get("control", "av/control"))

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    def _handle_message(self, topic: str, payload: dict) -> None:
        if "control" not in topic:
            return
        inner = payload.get("payload", {}) or payload
        cmd_id = inner.get("cmd")
        if not cmd_id or not isinstance(cmd_id, str):
            return
        original_text = inner.get("original_text", "")
        corr_id = (payload.get("metadata") or {}).get("correlation_id")
        # 不消费自己 echo 的消息（防回环）
        if (payload.get("header") or {}).get("source") == self.name:
            return
        meta = self._lookup.get(cmd_id, {})
        self._dispatch(cmd_id, meta, original_text, corr_id)

    def _dispatch(self, cmd_id: str, meta: dict, original_text: str, corr_id) -> None:
        """按 cmd_id 前缀路由到不同 adapter。

        当前 adapter:
          - Husion_*  → husion REST API (web_browser.husion_switch_scene)
          - 其它       → echo_only (待接 Node-RED / 厂商 SDK)

        每个 adapter 调用结果转 status = ok / failed / echo_only，连同 latency_ms
        publish 到 av/control/dispatched 供 dashboard 显示。
        """
        device_label = meta.get("device_label", "?")
        action_label = meta.get("action_label", "?")
        location_label = meta.get("location_label", "?")
        target_human = f"[{location_label}] {device_label}{action_label}"

        # === Adapter 路由 ===
        status = "echo_only"
        adapter_latency_ms = None
        adapter_err = None
        if cmd_id.startswith("Husion_"):
            t0 = time.monotonic()
            try:
                status = self._adapt_husion(cmd_id, meta)
            except Exception as e:
                status = "failed"
                adapter_err = f"{type(e).__name__}: {e}"
                self.logger.warning(f"husion adapter 异常 {cmd_id}: {adapter_err}")
            adapter_latency_ms = int((time.monotonic() - t0) * 1000)

        marker = {"ok": "✓", "failed": "✗", "echo_only": "➤"}.get(status, "?")
        self.logger.info(
            f"{marker} 下发: {cmd_id}  ({target_human})  status={status}"
            + (f" {adapter_latency_ms}ms" if adapter_latency_ms is not None else "")
            + f"  原话: {original_text!r}"
        )

        # kv_table renderer 的 control kind classify：ev.target / ev.action 都有 → 渲染为
        # 「{original_text}」→ {target} · {action}
        payload = {
            "ts": time.time(),
            "cmd": cmd_id,
            "target": target_human,
            "action": action_label,
            "device": device_label,
            "location": location_label,
            "original_text": original_text,
            "status": status,
            "correlation_id": corr_id,
        }
        if adapter_latency_ms is not None:
            payload["adapter_latency_ms"] = adapter_latency_ms
        if adapter_err is not None:
            payload["error"] = adapter_err
        self.publish("av/control/dispatched", payload)

    def _adapt_husion(self, cmd_id: str, meta: dict) -> str:
        """husion REST adapter — 调 GET /api/wall/rx_scene 切场景。

        Returns: "ok" 成功 / "failed" 业务错（code != 0）；其它异常由 caller 捕获。
        """
        from modules.web_browser.main import husion_switch_scene
        scene_name = meta.get("scene_name")
        rx_id = meta.get("rx_id", "5008")
        if not scene_name:
            raise ValueError(f"catalog 中 {cmd_id} 缺 scene_name 字段")
        resp = husion_switch_scene(rx_id, scene_name, timeout=8.0)
        if resp.get("code") == 0:
            scenename = (resp.get("data") or [{}])[0].get("scenename", "")
            self.logger.info(f"  husion 切换成功: rx_id={rx_id} scene={scenename}")
            return "ok"
        raise RuntimeError(f"husion code={resp.get('code')} msg={resp.get('message')}")

    def run(self) -> None:
        self.start()
        last_heartbeat = time.time()
        try:
            while self._running.is_set():
                time.sleep(1)
                now = time.time()
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
    ControlDispatcher(str(config_path)).run()


if __name__ == "__main__":
    main()
