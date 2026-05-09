"""
web/server.py
极简 Flask SSE 服务 —— 参考 woldmonitor 风格：
- 单文件、无状态、流式生成器、原生 JS
- 由 main.py 在线程内启动；也可独立运行 `python -m web.server`
- 动态多路 SSE：channel 按需注册，无白名单限制

    GET /                       主面板（订阅式动态生成 panels）
    GET /transcript             仅转写单页（旧接口，向后兼容）
    GET /events/<channel>       SSE 流；channel 任意字符串（不含 /）
    GET /events/discovery       模块公告流（驱动前端动态面板）
    POST /mock/<channel>        推一条 fake event；body 即 payload
"""
import json
import logging
import os
import queue
import threading
from collections import defaultdict
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

# 由 main.py 在启动后注入；用于 /camera/<name>/(enable|disable) → MQTT 发布
_mqtt_publish: Optional[Callable[[str, dict], None]] = None
# 由 main.py 注入；前端"退出系统"按钮 → POST /system/shutdown 触发 supervisor 优雅停机
_shutdown_handler: Optional[Callable[[], None]] = None


def set_mqtt_publisher(fn: Callable[[str, dict], None]) -> None:
    """供 main.py supervisor 注入 MQTTBridge.publish。"""
    global _mqtt_publish
    _mqtt_publish = fn


def set_shutdown_handler(fn: Callable[[], None]) -> None:
    """供 main.py supervisor 注入退出回调。"""
    global _shutdown_handler
    _shutdown_handler = fn

_flask_mod = None


def _get_flask():
    global _flask_mod
    if _flask_mod is not None:
        return _flask_mod
    import flask as _f
    _flask_mod = _f
    return _f


_flask = _get_flask()
_app = _flask.Flask(
    __name__,
    template_folder="templates",
    static_folder="static",
)
# 开发期方便：模板改了不用重启进程
_app.config["TEMPLATES_AUTO_RELOAD"] = True
_app.jinja_env.auto_reload = True

# channel → 订阅者队列列表（defaultdict：任意 channel 自动注册）
_subscribers: Dict[str, List["queue.Queue[dict]"]] = defaultdict(list)
# channel → 最近的"状态快照"（key → ev）；新订阅者连上时重放
# discovery 用 module 名做 key，其它用单一 "_latest" key
_latest_state: Dict[str, Dict[str, dict]] = defaultdict(dict)
_lock = threading.Lock()


def _state_key(channel: str, ev: dict) -> str:
    """决定该事件覆盖快照的哪个 key。discovery 按 module 区分，其它按 channel 单条。"""
    if channel == "discovery":
        return ev.get("module") or "_unknown"
    return "_latest"


def push(channel: str, ev: dict) -> None:
    """把事件推到指定 channel 的所有 SSE 订阅者；同时更新该 channel 的快照供新订阅者重放。

    聚合频道 `__all__`（前端单 SSE 优化）：所有非 hello 事件都额外推一份带 `__channel` 字段的副本，
    让前端单条 EventSource 按 `__channel` 字段 dispatch，避开浏览器同源 6 connection 限制。
    """
    with _lock:
        targets = list(_subscribers[channel])
        all_targets = list(_subscribers["__all__"])
        # 缓存最近状态：discovery 按模块名分；其它频道仅缓存最后一条
        if isinstance(ev, dict) and ev.get("type") != "hello":
            _latest_state[channel][_state_key(channel, ev)] = ev
    for q in targets:
        try:
            q.put_nowait(ev)
        except queue.Full:
            pass
    # 聚合频道：包一层 __channel 字段（hello 不参与，由 __all__ 自己的握手发）
    if all_targets and isinstance(ev, dict) and ev.get("type") != "hello":
        wrapped = {"__channel": channel, **ev}
        for q in all_targets:
            try:
                q.put_nowait(wrapped)
            except queue.Full:
                pass


def push_event(ev: dict) -> None:
    """向后兼容：旧调用方推转写到 transcript channel。"""
    push("transcript", ev)


@_app.get("/")
def index():
    return _flask.render_template("dashboard.html")


@_app.get("/config/device_catalog")
def device_catalog():
    """返回 config/device_catalog.json（前端 L1 快捷控制 + Node-RED 共用）。"""
    import os, pathlib
    p = pathlib.Path(__file__).parent.parent / "config" / "device_catalog.json"
    if not p.exists():
        return {"ok": False, "error": "device_catalog.json 缺失"}, 404
    return _flask.send_file(p, mimetype="application/json")


@_app.get("/distributed/husion/devices")
def husion_devices():
    """跨品牌桥接：返回 husion HDC900 实时设备列表（来自 discovery snapshot）。

    husion_distributed 子模块周期 poll husion TCP :6000 拿设备，
    publish 到 av/system/discovery/husion_distributed，本端点从快照取最新 endpoints。
    """
    snap = (_latest_state.get("discovery") or {}).get("husion_distributed")
    if not snap:
        return {"ok": True, "endpoints": [], "online": False}
    endpoints = snap.get("endpoints") or []
    return {
        "ok": True,
        "endpoints": endpoints,
        "online": snap.get("event") == "online",
        "ts": snap.get("ts"),
    }


@_app.get("/transcript")
def index_transcript():
    """旧单页面板，向后兼容。"""
    return _flask.render_template("transcript.html")


def _make_sse(channel: str):
    """SSE 生成器工厂。每个 channel 走相同的订阅/yield 协议。

    特殊频道 `__all__`：聚合所有 channel，订阅者一次拿全部最新快照（每条带 __channel 字段）。
    """
    def stream():
        q: "queue.Queue[dict]" = queue.Queue(maxsize=128)
        with _lock:
            _subscribers[channel].append(q)
            # 取该 channel 的最近快照副本，连上后立即重放，避免等下一次心跳
            if channel == "__all__":
                replay = []
                for ch, snap in _latest_state.items():
                    for ev in snap.values():
                        replay.append({"__channel": ch, **ev})
            else:
                replay = list(_latest_state.get(channel, {}).values())

        def gen():
            try:
                yield "data: " + json.dumps({"type": "hello", "channel": channel}) + "\n\n"
                # 重放快照（discovery 一次发完所有模块；其它频道单条）
                for ev in replay:
                    yield "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
                while True:
                    ev = q.get()
                    yield "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
            finally:
                with _lock:
                    if q in _subscribers[channel]:
                        _subscribers[channel].remove(q)

        return _flask.Response(
            _flask.stream_with_context(gen()),
            mimetype="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
                "Connection": "keep-alive",
            },
        )
    stream.__name__ = f"stream_{channel}"
    return stream


@_app.get("/events/<channel>")
def events(channel: str):
    """任意 channel 的 SSE 端点，不需要预先注册。"""
    return _make_sse(channel)()


@_app.post("/camera/<name>/<action>")
def camera_toggle(name: str, action: str):
    """前端可见性触发：发布 av/video/cmd/<name> 让 video_processor 启停摄像头。"""
    if action not in ("enable", "disable"):
        return {"ok": False, "error": "action must be enable|disable"}, 400
    if _mqtt_publish is None:
        return {"ok": False, "error": "mqtt publisher not injected"}, 503
    _mqtt_publish(f"av/video/cmd/{name}", {"action": action})
    return {"ok": True, "name": name, "action": action}


@_app.post("/mqtt/publish")
def mqtt_publish_proxy():
    """通用 MQTT 发布代理。前端 controls 触发时用。

    body: {"topic": "av/system/lan_scan/cmd", "payload": {...}}
    """
    if _mqtt_publish is None:
        return {"ok": False, "error": "mqtt publisher not injected"}, 503
    try:
        body = _flask.request.get_json(force=True, silent=False)
    except Exception as e:
        return {"ok": False, "error": f"bad json: {e}"}, 400
    topic = body.get("topic")
    payload = body.get("payload", {})
    if not topic or not isinstance(topic, str):
        return {"ok": False, "error": "topic required"}, 400
    # 安全：只允许 av/ 前缀，避免变成万能 MQTT 后门
    if not topic.startswith("av/"):
        return {"ok": False, "error": "topic must start with av/"}, 403
    _mqtt_publish(topic, payload)
    return {"ok": True, "topic": topic}


@_app.post("/system/shutdown")
def system_shutdown():
    """前端"退出系统"按钮：触发 supervisor 优雅停机，main.py.stop() 会清外部进程。

    回调在另一线程调用，让本响应能先返回给浏览器。
    """
    if _shutdown_handler is None:
        return {"ok": False, "error": "shutdown handler not injected"}, 503
    threading.Timer(0.1, _shutdown_handler).start()
    return {"ok": True, "msg": "shutting down"}


@_app.post("/mock/<channel>")
def mock(channel: str):
    """前端调样式用：直接把 request body 当 payload 推到 channel。"""
    try:
        ev = _flask.request.get_json(force=True, silent=False)
    except Exception as e:
        return {"ok": False, "error": f"bad json: {e}"}, 400
    push(channel, ev)
    return {"ok": True, "channel": channel}


def run(host: str = "0.0.0.0", port: int = 5050) -> None:
    """在当前线程同步阻塞地起 Flask（main.py 会包一层 daemon 线程调用）。"""
    logger.info(f"演示页: http://{host}:{port}  (SSE 订阅制，动态 channel)")
    _app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)


if __name__ == "__main__":
    run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5050")),
    )
