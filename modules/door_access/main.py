#!/usr/bin/env python3
"""
modules/door_access/main.py
门禁联动模块 — 公司大门（海康 DS-K1T341M @云眸平台）

链路：
  av/video/detect（门口摄像头 person）→ 冷却去抖 → av/door/visitor → dashboard 弹窗
  dashboard 开门按钮 → POST /mqtt/publish → av/door/cmd {action: open}
    → 本模块调云眸远程开门 → av/door/result → dashboard toast

云眸 API（协议：设备协议/门禁开门协议.docx，2026-08-18 全链路实测通过）：
  token POST /oauth/token（client_credentials，实测 expires_in 7 天）
  开门  POST /api/v1/open/accessControl/remoteControl/actions/open
备选路线：设备本地 ISAPI（192.168.2.88，不绕外网）— 当前卡在 isActivated=false
无 admin 密码，见 memory door-access-hik-cloud。

配置（system_config.yaml）：
  door_access:
    enabled: true
    client_id: xxx
    client_secret: xxx
    device_serial: E51574183
    door_id: "1"
    camera_name: 门口          # av/video/detect 的 camera 字段等于此值才触发弹窗
    person_confidence: 0.6     # person 置信度门槛
    visitor_cooldown_s: 30     # 弹窗冷却：人在门口停留不连环弹
"""
import logging
import signal
import sys
import time
from pathlib import Path

import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

HIK_CLOUD_BASE = "https://api2.hik-cloud.com"
# token 剩余有效期低于此值就换新（实测 token 7 天，提前 1 小时足够）
TOKEN_REFRESH_MARGIN_S = 3600
HTTP_TIMEOUT_S = 10


class DoorAccessModule(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        da = cfg.get("door_access", {})
        missing = [k for k in ("client_id", "client_secret", "device_serial") if not da.get(k)]
        if missing:
            raise ValueError(f"door_access 配置缺少必填项: {missing}（system_config.yaml）")

        # 注意：不能叫 self.client_id — BaseModule.__init__ 会把它覆盖成 MQTT client_id
        self.hik_client_id = da["client_id"]
        self.hik_client_secret = da["client_secret"]
        self.device_serial = da["device_serial"]
        self.door_id = str(da.get("door_id", "1"))
        self.camera_name = da.get("camera_name", "门口")
        self.person_confidence = float(da.get("person_confidence", 0.6))
        self.visitor_cooldown_s = float(da.get("visitor_cooldown_s", 30))

        streams = [{
            "topic": "av/door/visitor",
            "channel": "door",
            "kind": "event",
            "title": "门禁联动",
        }]
        super().__init__("door_access", cfg, streams=streams)

        # 云眸是国内 API，不走环境变量里的境外代理（LadderMac http_proxy），直连
        self._http = requests.Session()
        self._http.trust_env = False

        self._token: str | None = None
        self._token_expiry = 0.0
        self._last_visitor_ts = 0.0

        self.subscribe("av/video/detect")
        self.subscribe("av/door/cmd")

        # 启动即预热 token：秘钥/网络有问题启动时就暴露，而不是等第一次开门才炸
        try:
            self._get_token()
        except requests.RequestException as e:
            self.logger.error(f"启动预热 token 失败（开门时会重试）: {e}")

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

    # ── 云眸 API ─────────────────────────────────────────────────────

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expiry - TOKEN_REFRESH_MARGIN_S:
            return self._token
        r = self._http.post(
            f"{HIK_CLOUD_BASE}/oauth/token",
            data={
                "client_id": self.hik_client_id,
                "client_secret": self.hik_client_secret,
                "grant_type": "client_credentials",
                "scope": "app",
            },
            timeout=HTTP_TIMEOUT_S,
        )
        if r.status_code != 200:
            raise requests.RequestException(
                f"云眸 token HTTP {r.status_code}: {r.text[:200]}"
            )
        body = r.json()
        if "access_token" not in body:
            raise requests.RequestException(f"云眸 token 响应异常: {body}")
        self._token = body["access_token"]
        self._token_expiry = time.time() + float(body["expires_in"])
        self.logger.info(f"云眸 token 已更新，有效期 {body['expires_in']}s")
        return self._token

    def _open_door(self) -> dict:
        """调云眸远程开门，返回平台响应 {code, message}。HTTP/网络层错误直接抛。"""
        r = self._http.post(
            f"{HIK_CLOUD_BASE}/api/v1/open/accessControl/remoteControl/actions/open",
            headers={"Authorization": f"Bearer {self._get_token()}"},
            json={
                "deviceSerial": self.device_serial,
                "cmd": "open",
                "doorId": self.door_id,
            },
            timeout=HTTP_TIMEOUT_S,
        )
        if r.status_code != 200:
            raise requests.RequestException(
                f"云眸开门 HTTP {r.status_code}: {r.text[:200]}"
            )
        return r.json()

    # ── MQTT 消息处理 ────────────────────────────────────────────────

    def _handle_message(self, topic: str, payload: dict) -> None:
        if topic == "av/video/detect":
            self._on_detect(payload)
        elif topic == "av/door/cmd":
            self._on_cmd(payload)

    def _on_detect(self, payload: dict) -> None:
        if payload.get("camera") != self.camera_name:
            return
        persons = [
            d for d in payload.get("detections", [])
            if d.get("class") == "person" and d.get("confidence", 0) >= self.person_confidence
        ]
        if not persons:
            return
        now = time.time()
        if now - self._last_visitor_ts < self.visitor_cooldown_s:
            return
        self._last_visitor_ts = now
        self.logger.info(f"门口来访：{len(persons)} 人（camera={self.camera_name}）")
        self.publish("av/door/visitor", {
            "event": "visitor",
            "camera": self.camera_name,
            "person_count": len(persons),
            "max_confidence": max(d["confidence"] for d in persons),
            "ts": now,
        })

    def _on_cmd(self, payload: dict) -> None:
        action = payload.get("action") or payload.get("payload", {}).get("action")
        if action != "open":
            return
        t0 = time.time()
        try:
            try:
                resp = self._open_door()
            except requests.RequestException as e:
                # 云眸 oauth/token 端点实测偶发 401（同秘钥数秒后即恢复）。
                # 开门是时敏操作：作废缓存 token 立即重试一次
                self.logger.warning(f"开门请求失败，作废 token 重试一次: {e}")
                self._token = None
                resp = self._open_door()
            ok = resp.get("code") == 200
            code, message = resp.get("code"), resp.get("message", "")
        except requests.RequestException as e:
            # 网络/云端故障要上屏让操作者看到，不是吞掉
            ok, code, message = False, -1, f"云眸请求失败: {e}"
            self.logger.error(message)
        latency_ms = round((time.time() - t0) * 1000)
        self.logger.info(f"开门结果 ok={ok} code={code} {message}（{latency_ms}ms）")
        self.publish("av/door/result", {
            "event": "result",
            "ok": ok,
            "code": code,
            "message": message,
            "latency_ms": latency_ms,
        })


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if len(sys.argv) > 1:
        config_path = Path(sys.argv[1])
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    DoorAccessModule(str(config_path)).run()


if __name__ == "__main__":
    main()
