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
import datetime
import json
import logging
import os
import pathlib
import queue
import re
import threading
import time
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


# K4：Flask 启动失败（多见于 :5050 Address In Use）原本在 daemon thread 内 swallow，
# supervisor 不察觉 → user 看似启动成功但页面打不开。注入回调让错误冒到主循环。
_run_error_handler: Optional[Callable[[Exception], None]] = None


def set_run_error_handler(fn: Callable[[Exception], None]) -> None:
    """供 main.py 注入 web 启动失败回调（OSError / Address In Use 等）。"""
    global _run_error_handler
    _run_error_handler = fn

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


def _app_profile() -> str:
    """读当前应用形态 profile（环境变量优先，其次 config，缺省 full）。
    供前端按 profile 显隐卡片（CR-DIG7201 第7条：纯纪要产品出厂界面干净）。"""
    import os
    import yaml
    prof = os.environ.get("AV_APP_PROFILE")
    if prof:
        return prof
    p = _PROJECT_ROOT / "config" / "system_config.yaml"
    if p.exists():
        with open(p, encoding="utf-8") as f:
            cfg = yaml.safe_load(f) or {}
        return cfg.get("app_profile") or "full"
    return "full"


@_app.get("/")
def index():
    return _flask.render_template("dashboard.html", app_profile=_app_profile())


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


@_app.get("/api/husion/state")
def husion_state():
    """读 husion 9 设备 + 当前墙状态（合并）。

    每次请求 fresh fetch husion (3s login + 3s 内拿设备/墙)；不缓存（状态变化频繁）。
    成功返回 {ok, devices, wall, ts}；失败返回 {ok:false, error} 502。
    """
    from modules.web_browser.main import husion_login, husion_get
    try:
        token = husion_login(timeout=3)
        devices = husion_get("/api/get_all_equ", token, timeout=3).get("data") or []
        wall = husion_get("/api/wall/w?wall_id=1", token, timeout=3).get("data") or []
        return {"ok": True, "devices": devices, "wall": wall, "ts": time.time()}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 502


@_app.post("/api/husion/scene")
def husion_scene_switch():
    """触发 husion 切场景 — dashboard 按钮直调。

    body: {rx_id, scene_name}；返回 {ok, husion_resp}。
    """
    from modules.web_browser.main import husion_switch_scene
    body = _flask.request.get_json(force=True, silent=True) or {}
    rx_id = body.get("rx_id", "5008")
    scene = body.get("scene_name")
    if not scene:
        return {"ok": False, "error": "scene_name required"}, 400
    try:
        resp = husion_switch_scene(rx_id, scene, timeout=8)
        return {"ok": resp.get("code") == 0, "husion_resp": resp}
    except Exception as e:
        return {"ok": False, "error": str(e)}, 502


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


# ── 纪要生成（C 档：双路输出 — 弹窗 + JSON 留档知识库） ─────────────────
# 一次 LLM 调用拿结构化字段；写到 ${project}/summaries/<id>-<title>.json 留档；
# 同步返回给前端用于弹窗展示。
_PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
_SUMMARIES_DIR = _PROJECT_ROOT / "summaries"

# qwen3.5:4b 默认 thinking mode；末尾 /no_think 关掉（68bc510 已确认）
# 2026-07-28 CR-DIG7201 P0-a：输出从 JSON 改为行格式。实测 qwen3.5:4b 输出多元素
# JSON 数组系统性犯错（首条后即闭合数组 `"points":["a"],"b",...`，4 次里 3 次），
# 行格式 + 代码解析彻底绕开这一类失败。
_SUMMARY_PROMPT = """你是会议纪要助手。下面是一段语音转写文本，请生成一份结构化纪要。

严格按以下四个字段输出，不要 JSON、不要 markdown 代码块、不要其他内容：
标题：6-15 字，反映核心主题
摘要：80-150 字一段话。必须写出会议达成的具体结论、关键数字、决策事项和待办安排，
      像向没参会的人交代"这场会定了什么"。禁止写"会议围绕…展开讨论""就…进行了交流"
      这类空话套话——每句都要有实质信息。
要点：
- 每条一行以"- "开头，3-5 条，每条 10-30 字，覆盖讨论要点，保留具体人名/数字/结论
关键词：3-6 个名词性短语，用、分隔，便于后期检索

转写若带 [话筒N] 发言人标签，要点尽量注明发言人（谁提出、谁确认、谁负责）。

转写文本：
{transcript}

/no_think"""

# ── 长转写分段（CR-DIG7201 P0-a）────────────────────────────────────────
# 3588 CPU 跑 qwen3.5:4b 处理 2 万字实测 900s+ 超时（硬件天花板）。
# >阈值时切段：每段小 ctx 提要点 → 汇总段要点出最终纪要。
_SUMMARY_CHUNK_THRESHOLD = 8000   # 字；超过走分段路径
_SUMMARY_CHUNK_SIZE = 4000        # 每段目标字数
_SUMMARY_NUM_CTX = 7168           # 单段 / 短文本统一 ctx（4000 字 ≈ 2500-3000 token）


# ── 纪要 LLM 后端（CR-DIG7201 P0-b）────────────────────────────────────
# backend=ollama（默认，CPU）| rkllm（NPU，RKLLM-API-Server OpenAI 兼容）。
# 配置在 system_config.yaml 的 llm.summary 段，每次调用现读（改配置不用重启）。
def _summary_cfg() -> dict:
    import yaml
    p = _PROJECT_ROOT / "config" / "system_config.yaml"
    if not p.exists():
        return {}
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    return (cfg.get("llm") or {}).get("summary") or {}


def _rkllm_generate(prompt: str, timeout: int, num_predict: int, cfg: dict) -> str:
    """调 RKLLM-API-Server（OpenAI /v1/chat/completions，NPU）。
    与 ollama 的差异：chat 风格 messages 数组，回包取 choices[0].message.content。"""
    import requests
    s = requests.Session()
    s.trust_env = False
    r = s.post(
        cfg.get("url", "http://127.0.0.1:8000/v1/chat/completions"),
        json={
            "model": cfg.get("model", "qwen3-4b-16k"),
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "temperature": 0.3,
            "max_tokens": num_predict,
        },
        timeout=timeout,
    )
    r.raise_for_status()
    raw = (r.json().get("choices") or [{}])[0].get("message", {}).get("content", "")
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if not raw:
        raise ValueError("rkllm 返回空 content")
    return raw


def _rkllm_unload(cfg: dict) -> None:
    """纪要跑完释放 NPU 内存（会中 NPU 让给视觉）。失败只告警不影响已出纪要。"""
    url = cfg.get("unload_url")
    if not url:
        return
    import requests
    try:
        s = requests.Session()
        s.trust_env = False
        s.post(url, timeout=10)
        logger.info("rkllm 模型已 unload，NPU 内存释放")
    except Exception as e:
        logger.warning(f"rkllm unload 失败（NPU 内存未释放）：{e}")

_CHUNK_PROMPT = """你是会议纪要助手。下面是一场长会议转写的第 {idx}/{total} 部分，请提取本段讨论要点。

要求：3-6 条，每条 15-40 字，保留具体的人名、数字、结论和待办；不要泛泛而谈。
每条一行、以"- "开头；只输出要点行，不要 JSON、不要其他内容。
转写若带 [话筒N] 发言人标签，要点尽量注明发言人（谁提出、谁确认、谁负责）。

转写文本：
{transcript}

/no_think"""

_MERGE_PROMPT = """你是会议纪要助手。下面是一场长会议按时间顺序分段提取的要点清单，请汇总生成一份完整纪要。

严格按以下四个字段输出，不要 JSON、不要 markdown 代码块、不要其他内容：
标题：6-15 字，反映核心主题
摘要：80-150 字一段话。必须写出会议达成的具体结论、关键数字、决策事项和待办安排，
      像向没参会的人交代"这场会定了什么"。禁止写"会议围绕…展开讨论""就…进行了交流"
      这类空话套话——每句都要有实质信息。
要点：
- 每条一行以"- "开头，4-8 条，每条 10-30 字，合并重复、覆盖全程要点，保留具体人名/数字/结论
关键词：3-6 个名词性短语，用、分隔，便于后期检索

要点清单若带发言人（话筒N），汇总时保留发言人归属（谁提出、谁决策、谁负责）。

分段要点清单：
{points}

/no_think"""


def _parse_summary_fields(raw: str) -> dict:
    """解析行格式纪要输出（标题：/摘要：/要点行/关键词：）→ 与旧 JSON 同构的 dict。
    字段不全就抛错带原文片段，不静默。"""
    title, summary, points, keywords, mode = "", "", [], [], None
    for line in raw.splitlines():
        line = line.strip().lstrip("*# ")  # 容忍模型加 markdown 强调
        if not line:
            continue
        if line.startswith("标题"):
            title = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            mode = None
        elif line.startswith("摘要"):
            summary = line.split("：", 1)[-1].split(":", 1)[-1].strip()
            mode = "summary"
        elif line.startswith("关键词"):
            kws = line.split("：", 1)[-1].split(":", 1)[-1]
            keywords = [k.strip() for k in re.split(r"[、，,;；/|]", kws) if k.strip()]
            mode = None
        elif line.startswith("要点"):
            mode = "points"
        elif line[0] in "-•·":
            points.append(line.lstrip("-•·").strip())
        elif mode == "summary":
            summary += line  # 摘要偶尔换行续写
    if not title or not summary or not points:
        raise ValueError(
            f"纪要字段不全（title={bool(title)} summary={bool(summary)} "
            f"points={len(points)}）；原始：{raw[:200]}"
        )
    return {"title": title, "summary": summary, "points": points, "keywords": keywords}


def _parse_points(raw: str) -> list:
    """解析分段要点输出：每行以 -/•/· 开头算一条。"""
    pts = [ln.strip().lstrip("-•·").strip() for ln in raw.splitlines()
           if ln.strip() and ln.strip()[0] in "-•·"]
    pts = [p for p in pts if p]
    if not pts:
        raise ValueError(f"未提取到要点行；原始：{raw[:200]}")
    return pts


def _ollama_generate(prompt: str, model: str, timeout: int, num_predict: int = 800) -> str:
    """调 ollama /api/generate 一次，返回去掉 <think> 的文本。**不用 format=json**：
    实测 qwen3.5:4b + format=json 返回 response 字段为空（DEV PLAN 已记 qwen3
    thinking mode 坑 + format=json 复合问题）；prompt 末尾 `/no_think`，
    输出为行格式文本，由 _parse_summary_fields/_parse_points 解析。"""
    import requests
    s = requests.Session()
    s.trust_env = False  # 绕系统代理（DEV PLAN 已知坑）
    r = s.post(
        "http://127.0.0.1:11434/api/generate",
        json={
            "model": model,
            "prompt": prompt,  # prompt 内末尾已含 /no_think
            "stream": False,
            "think": False,
            "options": {
                "temperature": 0.3,
                "num_predict": num_predict,
                # 默认 ctx 4096 不够：8000 字 ≈ 5000+ token 会被静默截断头部
                "num_ctx": _SUMMARY_NUM_CTX,
            },
        },
        timeout=timeout,
    )
    r.raise_for_status()
    raw = (r.json() or {}).get("response", "")
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
    if not raw:
        raise ValueError("LLM 返回空（可能 /no_think 未生效或 model 不支持）")
    return raw


def _llm_generate(prompt: str, model: str, timeout: int, num_predict: int = 800) -> str:
    """按 llm.summary.backend 分发：rkllm（NPU）或 ollama（CPU，默认）。"""
    cfg = _summary_cfg()
    if cfg.get("backend") == "rkllm":
        return _rkllm_generate(prompt, timeout, num_predict, cfg)
    return _ollama_generate(prompt, model, timeout, num_predict)


def _generate_fields(prompt: str, model: str, timeout: int, num_predict: int = 800) -> dict:
    """_llm_generate + _parse_summary_fields，格式不全重试 1 次。
    小模型偶发漏字段，重跑一次通常就好；第二次仍失败则抛错让人看到，不静默。"""
    try:
        return _parse_summary_fields(_llm_generate(prompt, model, timeout, num_predict))
    except ValueError as e:
        logger.warning(f"summary LLM 输出格式不全，重试一次：{e}")
        return _parse_summary_fields(_llm_generate(prompt, model, timeout, num_predict))


def _dynamic_timeout(text_len: int, num_predict: int = 800) -> int:
    """按 3588 实测速率给 timeout（2026-07-28 video 冻结后 bench：
    prefill ~8 tok/s、decode ~2.5 tok/s，4000 字段实测 350s）。
    token≈字数×0.65；prefill 按 7 tok/s、decode 按 2.3 tok/s 留余量，+60s 装载/调度。"""
    return int(60 + text_len * 0.65 / 7 + num_predict / 2.3)


def _split_transcript(transcript: str, chunk_size: int = _SUMMARY_CHUNK_SIZE) -> list:
    """按字数切段，尽量在换行/句号处断开，避免拦腰截断一句话。"""
    chunks = []
    rest = transcript
    while len(rest) > chunk_size:
        cut = chunk_size
        # 在 [chunk_size*0.6, chunk_size] 窗口内找最后一个换行或句读
        window = rest[int(chunk_size * 0.6):chunk_size]
        for sep in ("\n", "。", "！", "？", "，"):
            pos = window.rfind(sep)
            if pos >= 0:
                cut = int(chunk_size * 0.6) + pos + 1
                break
        chunks.append(rest[:cut])
        rest = rest[cut:]
    if rest.strip():
        chunks.append(rest)
    return chunks


def _call_ollama_summary(transcript: str, model: str = "qwen3.5:4b") -> dict:
    """生成纪要。短文本（≤阈值）单次调用；长文本切段提要点→汇总。
    返回 dict 额外带 _chunks / _elapsed_sec 供上层记录耗时。

    阈值/分段大小可被 llm.summary.chunk_threshold_chars / chunk_size_chars 覆盖：
    NPU 上 1.7B 模型 ctx 仅 4096 token（≈2700 汉字），必须配小值（如 3500 字），
    否则 15-30 分钟的短会走单次调用就会超模型 ctx。默认值针对 ollama 大 ctx。"""
    t0 = time.time()
    cfg = _summary_cfg()
    threshold = int(cfg.get("chunk_threshold_chars") or _SUMMARY_CHUNK_THRESHOLD)
    chunk_size = int(cfg.get("chunk_size_chars") or _SUMMARY_CHUNK_SIZE)

    if len(transcript) <= threshold:
        prompt = _SUMMARY_PROMPT.format(transcript=transcript)
        result = _generate_fields(prompt, model, _dynamic_timeout(len(transcript)))
        result["_chunks"] = 1
        result["_elapsed_sec"] = round(time.time() - t0, 1)
        return result

    # 长文本：切段 → 每段提要点 → 汇总
    chunks = _split_transcript(transcript, chunk_size)
    total = len(chunks)
    logger.info(f"summary 分段：{len(transcript)} 字 → {total} 段")
    all_points = []
    for i, chunk in enumerate(chunks, 1):
        prompt = _CHUNK_PROMPT.format(idx=i, total=total, transcript=chunk)
        try:
            raw = _llm_generate(prompt, model, _dynamic_timeout(len(chunk), 400), num_predict=400)
            pts = _parse_points(raw)
        except Exception as e:
            # 明确报哪一段挂了，不静默吞（单段失败=纪要不完整，宁可整体失败让人看到）
            raise RuntimeError(f"分段 {i}/{total} 要点提取失败：{e}") from e
        all_points.extend(pts)
        logger.info(f"summary 分段 {i}/{total} 完成，累计要点 {len(all_points)} 条"
                    f"（{round(time.time() - t0)}s）")

    points_text = "\n".join(f"- {p}" for p in all_points)
    merge_prompt = _MERGE_PROMPT.format(points=points_text)
    result = _generate_fields(merge_prompt, model, _dynamic_timeout(len(points_text)))
    result["_chunks"] = total
    result["_elapsed_sec"] = round(time.time() - t0, 1)
    return result


@_app.post("/audio/summary")
def audio_summary():
    """生成纪要：调 ollama 获结构化 JSON → 写文件 + 返回前端弹窗。

    body: {transcript: "全文...", duration_sec: 180}
    """
    body = _flask.request.get_json(force=True, silent=True) or {}
    transcript = (body.get("transcript") or "").strip()
    if len(transcript) < 30:
        return {"ok": False, "error": "转写文本太短（需至少 30 字）"}, 400

    cfg = _summary_cfg()
    try:
        result = _call_ollama_summary(transcript)
    except Exception as e:
        logger.warning(f"summary LLM 调用失败：{e}")
        return {"ok": False, "error": f"LLM 调用失败：{e}"}, 502
    finally:
        # P0-b：NPU 后端跑完（无论成败）释放模型内存，会中 NPU 让给视觉
        if cfg.get("backend") == "rkllm":
            _rkllm_unload(cfg)

    now = datetime.datetime.now()
    summary = {
        "id": now.strftime("%Y%m%d-%H%M%S"),
        "ts": now.timestamp(),
        "duration_sec": int(body.get("duration_sec") or 0),
        "title": str(result.get("title") or "（无标题）")[:50],
        "summary": str(result.get("summary") or ""),
        "points": [str(x) for x in (result.get("points") or [])][:8],
        "keywords": [str(x) for x in (result.get("keywords") or [])][:10],
        "transcript": transcript,
        "model": cfg.get("model", "npu") if cfg.get("backend") == "rkllm" else "qwen3.5:4b",
        "version": "1.0",
        # CR-DIG7201 P0-a：分段数 + 生成耗时（验收记录 + 前端展示）
        "chunks": int(result.get("_chunks") or 1),
        "elapsed_sec": float(result.get("_elapsed_sec") or 0),
    }

    # B 路：留档到 summaries/<id>-<safe_title>.json（知识库源）
    try:
        _SUMMARIES_DIR.mkdir(exist_ok=True)
        safe_title = re.sub(r'[^\w一-龥\-]+', '_', summary["title"])[:30] or "untitled"
        fn = f"{summary['id']}-{safe_title}.json"
        with open(_SUMMARIES_DIR / fn, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        summary["file"] = fn
        logger.info(f"纪要已留档：summaries/{fn}")
    except Exception as e:
        logger.warning(f"summary 写文件失败：{e}")

    # A 路：返回给前端弹窗
    return {"ok": True, **summary}


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
    """在当前线程同步阻塞地起 Flask（main.py 会包一层 daemon 线程调用）。

    K4：Flask 启动失败（典型 OSError "Address already in use" :5050 被占）以前
    在 daemon thread 内 swallow，supervisor 看不到。改成抛错前先调 _run_error_handler
    通知主循环停机；user 在终端看到清晰 ERROR 而不是"启动成功但页面打不开"。

    5/14 加 retry：supervisor 重启时旧 socket TIME_WAIT 占着 5050 致 Flask 启动
    失败 → dashboard 翻车 user 找半天。3 次重试 × 8s 间隔，覆盖 TIME_WAIT 默认
    释放时间（Linux 60s 但 SO_REUSEADDR 通常更快）。
    """
    import time as _time
    max_retries = 3
    retry_delay_s = 8
    last_err = None
    for attempt in range(max_retries):
        if attempt > 0:
            logger.warning(f"Flask :{port} 第 {attempt + 1}/{max_retries} 次启动尝试...")
        else:
            logger.info(f"演示页: http://{host}:{port}  (SSE 订阅制，动态 channel)")
        try:
            _app.run(host=host, port=port, threaded=True, debug=False, use_reloader=False)
            return  # Flask 正常退出（外部停 / sigterm）
        except OSError as e:
            last_err = e
            logger.warning(f"Flask :{port} 启动失败 (attempt {attempt + 1}): {e}")
            if attempt + 1 < max_retries:
                logger.info(f"  → {retry_delay_s}s 后重试（等 TIME_WAIT 释放）")
                _time.sleep(retry_delay_s)
                continue
            # 3 次仍失败 → 通知 supervisor + 抛错
            logger.error(f"Flask :{port} {max_retries} 次重试均失败 — 放弃")
            logger.error(f"  → 检查：lsof -nP -iTCP:{port} -sTCP:LISTEN")
            logger.error(f"  → 或 pkill -f 'python3 main.py' 等 TIME_WAIT 完全释放")
            if _run_error_handler is not None:
                try:
                    _run_error_handler(e)
                except Exception:
                    pass
            raise
    if last_err is not None:
        raise last_err


if __name__ == "__main__":
    run(
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "5050")),
    )
