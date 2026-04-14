#!/usr/bin/env python3
"""
ui/dashboard.py
AV统一系统 - Streamlit 监控界面（重构后：纯MQTT订阅展示）

重构说明：
- 移除了VideoProcessor/AudioProcessor/LLMEngine的创建和直接调用
- 改为纯MQTT订阅接收各模块的事件
- 仅负责状态展示和手动控制指令发送
"""
import base64
import csv
import gc
import json
import socket
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import streamlit as st
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.mqtt_bridge import MQTTBridge

# ── 配置 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AV统一系统",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#0f1117;color:#e2e8f0}
[data-testid="stHeader"]{background:transparent}
.block-container{padding-top:1.5rem}
div[data-testid="stButton"] button{border-radius:8px;font-weight:600}
.module-status {display:flex;gap:24px;align-items:center;font-size:0.8rem;color:#cbd5e1;margin-bottom:8px}
.module-dot {display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px}
.dot-green {background:#22c55e;box-shadow:0 0 6px #22c55e}
.dot-red {background:#f87171;box-shadow:0 0 6px #f87171}
.dot-yellow {background:#f59e0b;box-shadow:0 0 6px #f59e0b}
</style>""", unsafe_allow_html=True)

# ── 控制主机配置 ──────────────────────────────────────────────────────
CTRL_HOST = "192.168.5.20"
CTRL_PORT = 8932


def send_tcp_command(cmd_str: str) -> tuple:
    """发送TCP字符串指令到中控主机"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(5)
        s.connect((CTRL_HOST, CTRL_PORT))
        s.sendall(cmd_str.encode("utf-8"))
        s.close()
        return True, "已发送"
    except Exception as e:
        return False, str(e)


# ── 设备指令表加载 ─────────────────────────────────────────────────────

@st.cache_resource
def load_device_commands():
    csv_path = Path(__file__).parent.parent / "config" / "devices.csv"
    cmds = []
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row.get("中控功能", "").strip()
                cmd = row.get("接收指令（ASCII）", "").strip()
                loc = row.get("地点", "").strip()
                dev = row.get("设备", "").strip().lstrip()
                if name and cmd:
                    cmds.append({"name": name, "cmd": cmd, "location": loc, "type": dev})
    except FileNotFoundError:
        pass
    return cmds


DEVICE_COMMANDS = load_device_commands()


# ── 初始化系统 ────────────────────────────────────────────────────────

@st.cache_resource
def init_system():
    config_path = Path(__file__).parent.parent / "config" / "system_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    state = {
        "lock": threading.Lock(),
        "mqtt_messages": [],
        "video_events": [],     # av/video/event
        "audio_events": [],     # av/audio/event
        "llm_events": [],       # av/llm/event
        "control_events": [],   # av/control/command
        "cmd_log": [],
        "system_log": [],
        "module_status": {},    # av/{module}/status
        "discovery": {},        # av/system/discovery
    }

    mqtt = MQTTBridge(cfg.get("mqtt", {}))

    # 定义MQTT消息处理
    def handle_discovery(topic, payload):
        with state["lock"]:
            client_id = payload.get("client_id", "unknown")
            state["discovery"][client_id] = {
                "event": payload.get("event"),
                "ip": payload.get("ip"),
                "module": payload.get("module"),
                "time": datetime.now().strftime("%H:%M:%S"),
            }
            state["system_log"].append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": "INFO",
                "msg": f"设备{'上线' if payload.get('event') == 'online' else '下线'}: {client_id} ({payload.get('ip')})"
            })

    def handle_video_event(topic, payload):
        with state["lock"]:
            state["video_events"].append({
                "topic": topic,
                "payload": payload,
                "time": datetime.now().strftime("%H:%M:%S"),
            })
            if len(state["video_events"]) > 200:
                state["video_events"].pop(0)
            # 添加到系统日志
            p = payload.get("payload", {})
            camera = p.get("camera", {}).get("name", "unknown")
            count = p.get("detection_count", 0)
            detections = p.get("detections", [])
            labels = list({d.get("class") for d in detections}) if detections else []
            state["system_log"].append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": "VIDEO",
                "msg": f"视频检测 | {camera} | {count}个目标 | {labels}"
            })

    def handle_audio_event(topic, payload):
        with state["lock"]:
            state["audio_events"].append({
                "topic": topic,
                "payload": payload,
                "time": datetime.now().strftime("%H:%M:%S"),
            })
            if len(state["audio_events"]) > 100:
                state["audio_events"].pop(0)
            p = payload.get("payload", {})
            state["system_log"].append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "level": "AUDIO",
                "msg": f"语音转写: {p.get('text', '')[:50]}"
            })

    def handle_llm_event(topic, payload):
        with state["lock"]:
            state["llm_events"].append({
                "topic": topic,
                "payload": payload,
                "time": datetime.now().strftime("%H:%M:%S"),
            })
            if len(state["llm_events"]) > 100:
                state["llm_events"].pop(0)
            p = payload.get("payload", {})
            event_type = p.get("event_type", "")
            if event_type == "command_generated":
                cmd = p.get("command", {})
                state["system_log"].append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": "LLM",
                    "msg": f"指令生成: {p.get('original_text', '')[:30]} → {cmd}"
                })

    def handle_control_command(topic, payload):
        with state["lock"]:
            state["control_events"].append({
                "topic": topic,
                "payload": payload,
                "time": datetime.now().strftime("%H:%M:%S"),
            })
            if len(state["control_events"]) > 100:
                state["control_events"].pop(0)

    def handle_module_status(topic, payload):
        with state["lock"]:
            source = payload.get("header", {}).get("source", "unknown")
            state["module_status"][source] = payload.get("payload", {})

    def handle_generic(topic, payload):
        with state["lock"]:
            state["mqtt_messages"].append({
                "topic": topic,
                "payload": payload,
                "time": datetime.now().strftime("%H:%M:%S")
            })
            if len(state["mqtt_messages"]) > 100:
                state["mqtt_messages"].pop(0)

    # 订阅所有重要主题
    subscriptions = [
        ("av/system/discovery", handle_discovery),
        ("av/video/event", handle_video_event),
        ("av/audio/event", handle_audio_event),
        ("av/llm/event", handle_llm_event),
        ("av/control/command", handle_control_command),
        ("av/dashboard/display", handle_generic),
        ("av/+/status", handle_module_status),
    ]

    for topic, handler in subscriptions:
        mqtt.subscribe(topic, handler)

    mqtt.start()

    return cfg, state, mqtt


cfg, state, mqtt = init_system()


# ── 侧边栏 ────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("### 系统状态")

    with state["lock"]:
        discovery = dict(state["discovery"])
        module_status = dict(state["module_status"])

    # MQTT连接状态
    mqtt_ok = mqtt.connected
    st.markdown(f"""
    <div class="module-status">
        <span class="module-dot {'dot-green' if mqtt_ok else 'dot-red'}"></span>
        MQTT {('已连接' if mqtt_ok else '断开')}
    </div>
    """, unsafe_allow_html=True)

    # 在线模块
    st.markdown("**在线模块**")
    online_modules = [
        (name, info) for name, info in discovery.items()
        if info.get("event") == "online"
    ]
    if online_modules:
        for name, info in online_modules:
            st.markdown(f"- {info.get('module', name)} ({info.get('ip', '')})")
    else:
        st.caption("暂无模块在线")

    # 模块状态详情
    if module_status:
        st.markdown("**模块详情**")
        for module, status in module_status.items():
            status_val = status.get("status", "unknown")
            dot_class = "dot-green" if status_val == "running" else "dot-yellow"
            st.markdown(f"""
            <div style="font-size:0.8rem;margin:4px 0">
                <span class="module-dot {dot_class}"></span>
                <b>{module}</b>: {status_val}
            </div>
            """, unsafe_allow_html=True)

    st.divider()

    # 手动控制
    st.markdown("### 🎮 手动控制")

    all_locations = sorted(set(d["location"] for d in DEVICE_COMMANDS if d["location"]))
    all_types = sorted(set(d["type"].strip() for d in DEVICE_COMMANDS if d["type"].strip()))

    fc1, fc2 = st.columns(2)
    sel_loc = fc1.selectbox("位置", ["全部"] + all_locations, key="ctrl_loc")
    sel_type = fc2.selectbox("设备类型", ["全部"] + all_types, key="ctrl_type")

    filtered = [
        d for d in DEVICE_COMMANDS
        if (sel_loc == "全部" or d["location"] == sel_loc)
        and (sel_type == "全部" or d["type"].strip() == sel_type)
    ]

    if filtered:
        cmd_options = [f"{d['name']}" for d in filtered]
        sel_name = st.selectbox("指令", cmd_options, key="ctrl_cmd")
        sel_dev = next((d for d in filtered if d["name"] == sel_name), None)

        if sel_dev:
            st.caption(f"指令码: `{sel_dev['cmd']}` → {CTRL_HOST}:{CTRL_PORT}")
            if st.button("发送指令", type="primary", use_container_width=True):
                # 通过MQTT发送控制指令
                mqtt.publish("av/dashboard/command", {
                    "command_type": "device_control",
                    "source": "dashboard",
                    "command": {
                        "device": sel_dev["name"],
                        "cmd": sel_dev["cmd"],
                        "target": f"{CTRL_HOST}:{CTRL_PORT}",
                    }
                })
                # 同时通过TCP发送
                ok, msg = send_tcp_command(sel_dev["cmd"])
                status_str = "已发送" if ok else f"失败:{msg}"
                with state["lock"]:
                    state["cmd_log"].append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "source": "手动",
                        "text": sel_dev["name"],
                        "cmd": {"cmd": sel_dev["cmd"], "target": f"{CTRL_HOST}:{CTRL_PORT}"},
                        "status": status_str
                    })
                if ok:
                    st.success(f"✓ {sel_dev['name']}")
                else:
                    st.error(f"✗ TCP失败: {msg}")
    else:
        st.info("无匹配指令")

    st.divider()

    # 退出按钮
    if st.button("⏻ 断开连接", type="secondary", use_container_width=True):
        try:
            mqtt.stop()
        except Exception:
            pass
        st.cache_resource.clear()
        gc.collect()
        st.success("已断开")
        st.stop()


# ── 主界面 ────────────────────────────────────────────────────────────

st.markdown("""
<div style="text-align:center;margin-bottom:8px">
    <span style="font-size:1.8rem;font-weight:500;color:#00d4ff;text-shadow:0 0 20px rgba(0,212,255,0.8),0 0 40px rgba(0,212,255,0.4);letter-spacing:4px">CREATOR</span>
</div>
""", unsafe_allow_html=True)

st.markdown("## 🎬 Ai视听理解 (分布式架构)")

# 状态栏
_mqtt_ok = mqtt.connected
_cid = cfg.get("mqtt", {}).get("client_id", "未知")
with state["lock"]:
    _msg_count = len(state["mqtt_messages"])
    _video_count = len(state["video_events"])
    _audio_count = len(state["audio_events"])

st.markdown(f"""
<div class="module-status" style="background:#1a1d2e;border-radius:8px;padding:8px 16px">
    <span><span class="module-dot {'dot-green' if _mqtt_ok else 'dot-red'}"></span>MQTT {'已连接' if _mqtt_ok else '断开'}</span>
    <span><span class="module-dot dot-green"></span>系统正常</span>
    <span style="color:#64748b">ID: {_cid}</span>
    <span style="color:#64748b">视频事件: {_video_count}</span>
    <span style="color:#64748b">语音事件: {_audio_count}</span>
</div>
""", unsafe_allow_html=True)

st.divider()

# 主内容区
left, right = st.columns([3, 2], gap="large")

with left:
    st.markdown("### 📹 视频检测事件")

    with state["lock"]:
        video_events = list(state["video_events"])

    if video_events:
        cols = st.columns(3)
        for i, event in enumerate(reversed(video_events[-9:])):
            with cols[i % 3]:
                payload = event.get("payload", {})
                p = payload.get("payload", {})
                camera = p.get("camera", {}).get("name", "unknown")
                detections = p.get("detections", [])
                count = p.get("detection_count", 0)
                labels = list({d.get("class") for d in detections}) if detections else []

                st.markdown(f"""
                <div style="background:#1a2035;padding:10px;border-radius:8px;margin-bottom:8px">
                    <div style="color:#60a5fa;font-weight:600">{camera}</div>
                    <div style="color:#64748b;font-size:0.75rem">{event['time']}</div>
                    <div style="margin-top:4px">
                        <span style="color:#22c55e;font-size:1.2rem;font-weight:bold">{count}</span>
                        <span style="color:#94a3b8">个目标</span>
                    </div>
                    <div style="color:#94a3b8;font-size:0.75rem;margin-top:4px">
                        {', '.join(labels) if labels else '无'}
                    </div>
                </div>
                """, unsafe_allow_html=True)
    else:
        st.info("等待视频检测事件...")

    st.divider()

    # 语音转写
    st.markdown("### 🎤 语音转写")

    with state["lock"]:
        audio_events = list(state["audio_events"])

    if audio_events:
        for event in reversed(audio_events[-20:]):
            payload = event.get("payload", {})
            p = payload.get("payload", {})
            text = p.get("text", "")
            confidence = p.get("confidence", 0)

            st.markdown(f"""
            <div style="background:#1e2030;padding:8px;border-radius:6px;margin-bottom:6px">
                <span style="color:#64748b;font-size:0.75rem">{event['time']}</span>
                <span style="color:#60a5fa;font-size:0.75rem">置信:{confidence:.0%}</span>
                <div style="color:#e2e8f0;margin-top:4px">{text}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("等待语音输入...")

with right:
    tab_cmd, tab_llm, tab_log = st.tabs(["⚡ 指令日志", "🧠 LLM响应", "🔧 系统日志"])

    with tab_cmd:
        with state["lock"]:
            cmd_log = list(state["cmd_log"])

        if cmd_log:
            for entry in reversed(cmd_log):
                st.markdown(f"""
                <div style="background:#1a2035;padding:8px;border-radius:6px;margin-bottom:6px">
                    <span style="color:#64748b;font-size:0.75rem">{entry["time"]}</span>
                    <span style="color:#60a5fa;font-size:0.75rem">[{entry["source"]}]</span>
                    <span style="color:#22c55e;font-size:0.75rem">{entry["status"]}</span>
                    <div style="color:#e2e8f0">{entry["text"]}</div>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("暂无指令记录")

    with tab_llm:
        with state["lock"]:
            llm_events = list(state["llm_events"])

        if llm_events:
            for event in reversed(llm_events[-20:]):
                payload = event.get("payload", {})
                p = payload.get("payload", {})
                event_type = p.get("event_type", "")
                original_text = p.get("original_text", "")
                command = p.get("command")

                st.markdown(f"""
                <div style="background:#1a2035;padding:8px;border-radius:6px;margin-bottom:6px">
                    <span style="color:#64748b;font-size:0.75rem">{event['time']}</span>
                    <span style="color:#60a5fa;font-size:0.75rem">[{event_type}]</span>
                    <div style="color:#e2e8f0;margin-top:4px">{original_text}</div>
                    {f'<div style="color:#22c55e;font-size:0.75rem;font-family:monospace;margin-top:4px">{json.dumps(command, ensure_ascii=False)}</div>' if command else ''}
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("等待LLM响应...")

    with tab_log:
        with state["lock"]:
            syslog = list(state["system_log"])

        if syslog:
            for entry in reversed(syslog[-50:]):
                level = entry.get("level", "INFO")
                color = {"LLM": "#60a5fa", "VIDEO": "#22c55e", "AUDIO": "#f59e0b", "ERROR": "#f87171"}.get(level, "#94a3b8")
                st.markdown(f"""
                <div style="font-size:0.75rem;padding:2px 0;border-bottom:1px solid #1e2030">
                    <span style="color:#64748b">{entry["time"]}</span>
                    <span style="color:{color};font-weight:600">[{level}]</span>
                    <span style="color:#e2e8f0">{entry["msg"]}</span>
                </div>
                """, unsafe_allow_html=True)
        else:
            st.info("暂无日志")

# 自动刷新
time.sleep(0.5)
st.rerun()
