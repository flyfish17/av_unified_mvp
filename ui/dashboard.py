#!/usr/bin/env python3
"""
dashboard.py
AV统一系统 - Streamlit 监控界面（完整版）
"""
import base64
import csv
import gc
import json
import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import streamlit as st
import yaml

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

def scan_lan_rtsp(timeout: float = 0.3) -> list:
    """扫描局域网内开放554端口的主机"""
    # 用 UDP 连接技巧获取真实 LAN IP（macOS gethostbyname 常返回 127.0.0.1）
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
    except Exception:
        local_ip = "192.168.5.1"
    prefix = ".".join(local_ip.split(".")[:3])

    def check(ip):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(timeout)
            ok = s.connect_ex((ip, 554)) == 0
            s.close()
            return ip if ok else None
        except Exception:
            return None

    hosts = [f"{prefix}.{i}" for i in range(1, 255)]
    found = []
    with ThreadPoolExecutor(max_workers=64) as ex:
        futures = {ex.submit(check, ip): ip for ip in hosts}
        for fut in as_completed(futures):
            r = fut.result()
            if r:
                found.append(r)
    return sorted(found)

# 添加core目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from modules.audio_processor.processor import AudioProcessor
from modules.llm_engine.engine import LLMEngine
from modules.video_processor.processor import VideoProcessor
from core.mqtt_bridge import MQTTBridge

# ── 配置 ──────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="AV统一系统", page_icon="🎬",
    layout="wide", initial_sidebar_state="expanded",
)

st.markdown("""
<style>
[data-testid="stAppViewContainer"]{background:#0f1117;color:#e2e8f0}
[data-testid="stHeader"]{background:transparent}
.block-container{padding-top:1.5rem}
div[data-testid="stButton"] button{border-radius:8px;font-weight:600}
div[data-testid="stRadio"] > label{display:none}
div[data-testid="stRadio"] > div{gap:8px;display:flex;justify-content:center;}
div[data-testid="stRadio"] label {background: transparent !important;border: 1px solid #555555 !important;border-radius: 4px;padding: 10px 24px;transition: all 0.3s;cursor: pointer;}
div[data-testid="stRadio"] label p, div[data-testid="stRadio"] label span {color: #555555 !important;font-weight: 500;}
div[data-testid="stRadio"] label:has(input:checked) {background: transparent !important;border: 1px solid #cccccc !important;}
div[data-testid="stRadio"] label:has(input:checked) p, div[data-testid="stRadio"] label:has(input:checked) span {color: #ffffff !important;}
</style>""", unsafe_allow_html=True)

# ── 初始化 ────────────────────────────────────────────────────────────

@st.cache_resource
def init_system():
    config_path = Path(__file__).parent.parent / "config" / "system_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    state = {
        "lock": threading.Lock(),
        "transcripts": [],
        "detections": [],
        "mqtt_messages": [],
        "cmd_log": [],        # 指令执行日志
        "video_stats": {},    # {camera_name: {last_time, count, fps_ts}}
        "recording": False,
        "system_log": [],
    }

    mqtt = MQTTBridge(cfg.get("mqtt", {}))
    llm = LLMEngine(cfg.get("llm", {}))

    # MQTT 消息回调
    topics = cfg.get("mqtt", {}).get("topics", {})

    def on_msg(topic, payload):
        with state["lock"]:
            state["mqtt_messages"].append({
                "topic": topic,
                "payload": payload,
                "time": datetime.now().strftime("%H:%M:%S")
            })
            if len(state["mqtt_messages"]) > 100:
                state["mqtt_messages"].pop(0)

    for topic in topics.values():
        mqtt.subscribe(topic, on_msg)

    mqtt.start()

    # 启动视频处理器
    video = VideoProcessor(cfg.get("video", {}))

    def on_video_event(event):
        with state["lock"]:
            state["detections"].append({
                "time": datetime.now().strftime("%H:%M:%S"),
                "camera": event.camera_name,
                "count": len(event.detections),
                "items": event.detections
            })
            if len(state["detections"]) > 200:
                state["detections"].pop(0)
            # 更新视频统计
            stats = state["video_stats"].setdefault(event.camera_name, {"count": 0, "last_time": "", "last_labels": []})
            stats["count"] = len(event.detections)
            stats["last_time"] = datetime.now().strftime("%H:%M:%S")
            stats["last_labels"] = list({d["class"] for d in event.detections})
        topics_cfg = cfg.get("mqtt", {}).get("topics", {})
        mqtt.publish(topics_cfg.get("video_detect", "av/video/detect"), {
            "camera": event.camera_name,
            "time": event.timestamp,
            "detections": event.detections
        })

    video.start(callback=on_video_event)

    return cfg, state, mqtt, llm, video

cfg, state, mqtt, llm, video = init_system()

# ── 音频处理回调 ──────────────────────────────────────────────────────

def on_audio_text(ev):
    if hasattr(ev, "is_final") and not ev.is_final:
        return
    text = ev.text if hasattr(ev, "text") else str(ev)
    entry = {
        "time": datetime.now().strftime("%H:%M:%S"),
        "text": text,
        "is_command": False,
        "cmd": None,
        "status": "pending"   # pending / sent / ignored / error
    }
    with state["lock"]:
        state["transcripts"].append(entry)
        idx = len(state["transcripts"]) - 1

    def classify():
        keywords = ["打开", "关闭", "调亮", "调暗", "切换", "播放", "暂停", "音量", "调节", "升高", "降低"]
        is_kw = any(kw in text for kw in keywords)

        if is_kw or llm.classify_intent(text):
            raw_response = llm._ask(llm.model_fast, llm.COMMAND_PROMPT + text)
            cmd = llm._parse_json(raw_response)
            with state["lock"]:
                state["transcripts"][idx]["is_command"] = True
                state["transcripts"][idx]["cmd"] = cmd
                state["transcripts"][idx]["status"] = "sent" if cmd else "no_cmd"
                state["system_log"].append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": "LLM",
                    "msg": f"指令生成 | 输入: {text[:30]} | 原始: {raw_response[:80]} | 解析: {cmd}"
                })
                if len(state["system_log"]) > 200:
                    state["system_log"].pop(0)
            if cmd:
                topics_cfg = cfg.get("mqtt", {}).get("topics", {})
                mqtt.publish(topics_cfg.get("control", "av/control"), cmd)
                with state["lock"]:
                    state["cmd_log"].append({
                        "time": datetime.now().strftime("%H:%M:%S"),
                        "source": "语音",
                        "text": text,
                        "cmd": cmd,
                        "status": "已发送"
                    })
                    if len(state["cmd_log"]) > 50:
                        state["cmd_log"].pop(0)
        else:
            with state["lock"]:
                state["transcripts"][idx]["status"] = "ignored"
                state["system_log"].append({
                    "time": datetime.now().strftime("%H:%M:%S"),
                    "level": "INFO",
                    "msg": f"非指令: {text[:40]}"
                })

    threading.Thread(target=classify, daemon=True).start()

# ── 设备指令表（从CSV加载）────────────────────────────────────────────

@st.cache_resource
def load_device_commands():
    csv_path = Path(__file__).parent.parent / "config" / "devices.csv"
    cmds = []
    with open(csv_path, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            name = row.get("中控功能", "").strip()
            cmd  = row.get("接收指令（ASCII）", "").strip()
            loc  = row.get("地点", "").strip()
            dev  = row.get("设备", "").strip().lstrip()
            if name and cmd:
                cmds.append({"name": name, "cmd": cmd, "location": loc, "type": dev})
    return cmds

DEVICE_COMMANDS = load_device_commands()

# ── 侧边栏：摄像头管理 ────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent.parent / "config" / "system_config.yaml"

def save_sources(sources: list):
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        full_cfg = yaml.safe_load(f)
    full_cfg.setdefault("video", {})["sources"] = sources
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        yaml.dump(full_cfg, f, allow_unicode=True, default_flow_style=False)

with st.sidebar:
    st.markdown("### 摄像头管理")

    sources = list(video.sources)  # 从VideoProcessor读，不从cfg缓存读

    # 显示现有摄像头（只读展示，修改通过直接编辑URL）
    for i, src in enumerate(sources):
        with st.expander(f"{src.get('name', f'摄像头{i+1}')}", expanded=False):
            st.caption(f"URL: {src.get('url', '')}")
            st.caption(f"状态: {'启用' if src.get('enabled', True) else '禁用'}")
            col_en, col_del = st.columns(2)
            with col_en:
                if st.button("禁用" if src.get("enabled", True) else "启用", key=f"tog_{i}"):
                    new_list = list(sources)
                    new_list[i] = {**src, "enabled": not src.get("enabled", True)}
                    video.reload_sources(new_list)
                    save_sources(new_list)
                    st.rerun()
            with col_del:
                if st.button("删除", key=f"del_{i}", type="secondary"):
                    new_list = [s for j, s in enumerate(sources) if j != i]
                    video.reload_sources(new_list)
                    save_sources(new_list)
                    st.rerun()

    st.divider()

    # 添加新摄像头 — 用 session_state 缓存输入，避免 rerun 时丢失
    st.markdown("**添加摄像头**")

    # pending 中转：填入按钮在 widget 渲染后触发，需在下一轮渲染前把值转移到 widget key
    for _pk, _wk in [("cam_type_pending", "cam_type"),
                     ("ipc_ip_pending",   "ipc_ip"),
                     ("dist_ip_pending",  "dist_ip")]:
        if _pk in st.session_state:
            st.session_state[_wk] = st.session_state.pop(_pk)

    cam_type = st.selectbox("类型", ["IPC（带认证）", "分布式（无认证）", "本机摄像头"], key="cam_type")

    if cam_type == "IPC（带认证）":
        c1, c2 = st.columns([3, 1])
        ipc_ip   = c1.text_input("IP地址", key="ipc_ip", placeholder="192.168.5.181")
        ipc_port = c2.text_input("端口", key="ipc_port", value="554")
        c3, c4   = st.columns(2)
        ipc_user = c3.text_input("用户名", key="ipc_user", value="admin")
        ipc_pwd  = c4.text_input("密码", key="ipc_pwd", type="password")
        ipc_ch   = st.text_input("通道号", key="ipc_ch", placeholder="801  (如 801、1101)")
        new_url  = (f"rtsp://{ipc_user}:{ipc_pwd}@{ipc_ip}:{ipc_port}"
                    f"/Streaming/Channels/{ipc_ch}") if ipc_ip and ipc_ch else ""

    elif cam_type == "分布式（无认证）":
        c1, c2   = st.columns([3, 1])
        dist_ip   = c1.text_input("IP地址", key="dist_ip", placeholder="192.168.5.31")
        dist_port = c2.text_input("端口", key="dist_port", value="554")
        dist_path = st.text_input("通道路径", key="dist_path", placeholder="live/chn2")
        new_url   = (f"rtsp://{dist_ip}:{dist_port}/{dist_path}"
                     ) if dist_ip and dist_path else ""

    else:
        dev_no  = st.text_input("设备号", key="local_dev", value="0")
        st.caption("0=内置摄像头，1=第二个USB摄像头")
        new_url = dev_no

    new_name = st.text_input("摄像头名称", key="new_name", placeholder="如：大厅摄像头")
    if new_url:
        st.caption(f"`{new_url}`")

    if st.button("添加并启动", type="primary", use_container_width=True):
        if new_url:
            new_src  = {"name": new_name or f"摄像头{len(sources)+1}", "url": new_url, "enabled": True}
            new_list = list(video.sources) + [new_src]
            video.reload_sources(new_list)
            save_sources(new_list)
            with state["lock"]:
                state["system_log"].append({"time": datetime.now().strftime("%H:%M:%S"),
                    "level": "INFO", "msg": f"添加摄像头: {new_src['name']} → {new_url}"})
            st.success(f"已添加: {new_src['name']}")
            st.rerun()
        else:
            st.error("请填写 IP 和通道路径")

    st.divider()

    # 局域网扫描
    st.markdown("**局域网扫描 (554端口)**")
    if st.button("🔍 扫描", use_container_width=True):
        with st.spinner("扫描中，约10秒..."):
            found = scan_lan_rtsp()
        st.session_state["lan_scan"] = found

    if "lan_scan" in st.session_state:
        results = st.session_state["lan_scan"]
        if results:
            sel_ip = st.selectbox(f"发现 {len(results)} 台", results, key="lan_sel")
            st.caption(f"`{sel_ip}`")
            c_use1, c_use2 = st.columns(2)
            if c_use1.button("→ IPC", use_container_width=True, key="fill_ipc"):
                st.session_state["cam_type_pending"] = "IPC（带认证）"
                st.session_state["ipc_ip_pending"] = sel_ip
                st.rerun()
            if c_use2.button("→ 分布式", use_container_width=True, key="fill_dist"):
                st.session_state["cam_type_pending"] = "分布式（无认证）"
                st.session_state["dist_ip_pending"] = sel_ip
                st.rerun()
        else:
            st.caption("未发现开放554端口的设备")

    st.divider()

    # 退出系统
    st.markdown("**⚠️ 系统**")
    if st.button("⏻ 退出系统", type="secondary", use_container_width=True):
        # 停止音频处理器
        if "audio_processor" in st.session_state:
            try:
                st.session_state.audio_processor.stop()
            except Exception:
                pass
            del st.session_state.audio_processor

        # 停止视频处理器
        try:
            video.stop()
        except Exception:
            pass

        # 停止MQTT
        try:
            mqtt.stop()
        except Exception:
            pass

        # 清理状态
        with state["lock"]:
            state["transcripts"] = []
            state["detections"] = []
            state["mqtt_messages"] = []
            state["cmd_log"] = []
            state["system_log"] = []
            state["video_stats"] = {}

        # 清理缓存
        st.cache_resource.clear()

        # 强制垃圾回收
        gc.collect()

        st.success("系统已停止，所有资源已清理")
        time.sleep(1)
        st.stop()


# ── UI 主界面 ─────────────────────────────────────────────────────────

st.markdown("""
<div style="text-align:center;margin-bottom:8px">
    <span style="font-size:1.8rem;font-weight:500;color:#00d4ff;text-shadow:0 0 20px rgba(0,212,255,0.8),0 0 40px rgba(0,212,255,0.4);letter-spacing:4px">CREATOR</span>
</div>
""", unsafe_allow_html=True)

st.markdown("## 🎬 Ai视听理解")

# 状态栏 — 紧凑指示灯条
_mqtt_ok = mqtt.connected
_llm_ok  = llm.is_available()
_cid     = cfg.get("mqtt", {}).get("client_id", "未知")
_msgs    = len(state["mqtt_messages"])
st.markdown(
    f'<div style="background:#1a1d2e;border-radius:8px;padding:5px 16px;'
    f'display:flex;gap:24px;align-items:center;font-size:0.8rem;color:#cbd5e1;margin-bottom:8px">'
    f'<span><span style="color:{"#22c55e" if _mqtt_ok else "#f87171"}">●</span> MQTT</span>'
    f'<span><span style="color:{"#22c55e" if _llm_ok else "#f59e0b"}">●</span>'
    f' LLM {"就绪" if _llm_ok else "离线"}</span>'
    f'<span style="color:#64748b">ID: {_cid}</span>'
    f'<span style="color:#64748b">消息: {_msgs}</span>'
    f'</div>',
    unsafe_allow_html=True
)

st.divider()

# ═══════════════════════════════════════════════════════════════════════
# 区块1: Node-RED 控制面板 (顶部，像浏览器地址栏一样可填URL)
# ═══════════════════════════════════════════════════════════════════════
st.markdown("### 🖥️ Ai数字孪生")

# URL输入框（类似浏览器地址栏）
nodered_cols = st.columns([6, 1])
with nodered_cols[0]:
    nodered_url_input = st.text_input(
        "Node-RED 地址",
        value="http://localhost:1880/dashboard/creator-dash",
        placeholder="http://localhost:1880/dashboard/creator-dash",
        label_visibility="collapsed",
    )
with nodered_cols[1]:
    st.markdown("")  # 占位
    open_btn = st.button("🌐", help="在浏览器新标签页打开")

if open_btn and nodered_url_input:
    import webbrowser
    webbrowser.open_new_tab(nodered_url_input)

# iframe嵌入Node-RED
if nodered_url_input:
    st.markdown(
        f'<iframe src="{nodered_url_input}" width="100%" height="320" '
        f'style="border:1px solid #2d3748;border-radius:8px;"></iframe>',
        unsafe_allow_html=True
    )
st.caption("编辑流程: http://localhost:1880 | 如需登录先在浏览器打开完成认证")

st.divider()

# ═══════════════════════════════════════════════════════════════════════
# 区块2: 视频监控墙 (中部)
# ═══════════════════════════════════════════════════════════════════════
st.markdown("### 📹 视觉分析")

active_sources = [s for s in video.sources if s.get("enabled", True)]
if active_sources:
    frames = video.get_all_frames()
    stream_status = video.get_stream_status()
    with state["lock"]:
        vstats = dict(state["video_stats"])
    n_cols = 3 if len(active_sources) > 4 else (2 if len(active_sources) > 1 else 1)
    vcols = st.columns(n_cols)
    for i, src in enumerate(active_sources):
        name   = src.get("name", f"摄像头{i+1}")
        url    = src.get("url", "")
        status = stream_status.get(name, "connecting")
        s      = vstats.get(name, {})
        count  = s.get("count", 0)
        last_t = s.get("last_time", "—")
        labels = "、".join(s.get("last_labels", []) or "无")
        dot_color, status_txt = (
            ("#22c55e", "在线") if status == "ok" or frames.get(name) is not None
            else ("#f87171", "失败") if status.startswith("error")
            else ("#f59e0b", "连接中")
        )
        status_bar = (
            f'<div style="border-top:1px solid #2d3748;padding:4px 8px;font-size:0.72rem;'
            f'color:#94a3b8;background:#1a1d2e;display:flex;gap:12px;align-items:center">'
            f'<span style="color:{dot_color}">● {status_txt}</span>'
            f'<span>检测 <b style="color:#e2e8f0">{count}</b> {labels}</span>'
            f'<span style="margin-left:auto">{last_t}</span></div>'
        )
        with vcols[i % n_cols]:
            frame = frames.get(name)
            if frame is not None:
                _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                b64 = base64.b64encode(buf).decode()
                st.markdown(
                    f'<div style="border:1px solid #2d3748;border-radius:8px;overflow:hidden;margin-bottom:4px">'
                    f'<div style="font-size:0.72rem;color:#94a3b8;padding:2px 8px;background:#1a1d2e">{name}</div>'
                    f'<img src="data:image/jpeg;base64,{b64}" style="width:100%;display:block">'
                    f'{status_bar}</div>',
                    unsafe_allow_html=True
                )
            elif status.startswith("error"):
                err_msg = status.replace("error:", "")
                st.markdown(
                    f'<div style="border:1px solid #7f1d1d;border-radius:8px;overflow:hidden;margin-bottom:4px">'
                    f'<div style="background:#2d1515;padding:30px 12px;text-align:center">'
                    f'<div style="color:#f87171;font-weight:600">{name}</div>'
                    f'<div style="color:#fca5a5;font-size:0.75rem;margin-top:6px">连接失败</div>'
                    f'<div style="color:#64748b;font-size:0.7rem;margin-top:4px;word-break:break-all">{err_msg}</div>'
                    f'</div>{status_bar}</div>',
                    unsafe_allow_html=True
                )
            else:
                st.markdown(
                    f'<div style="border:1px dashed #444;border-radius:8px;overflow:hidden;margin-bottom:4px">'
                    f'<div style="background:#1e2030;padding:30px 12px;text-align:center">'
                    f'<div style="color:#94a3b8">{name}</div>'
                    f'<div style="color:#60a5fa;font-size:0.75rem;margin-top:6px">⟳ 连接中...</div>'
                    f'<div style="color:#475569;font-size:0.7rem;margin-top:4px;word-break:break-all">{url[:50]}</div>'
                    f'</div>{status_bar}</div>',
                    unsafe_allow_html=True
                )
else:
    st.info("暂无启用摄像头")

st.divider()

# ═══════════════════════════════════════════════════════════════════════
# 区块3: 语音控制 + 语义理解 (底部)
# ═══════════════════════════════════════════════════════════════════════
st.markdown("### 🕹️ 语意理解")

# 主内容区：左侧语义理解 + 右侧日志
left, right = st.columns([3, 2], gap="large")

with left:
    # 模式选择 + 标题合并
    if "mode" not in st.session_state:
        st.session_state.mode = "control"

    mode_col, rec_col1, rec_col2 = st.columns([2, 1, 1])
    with mode_col:
        mode = st.radio(
            "模式",
            ["🕹️ 语音控制", "📝 会议记录"],
            index=0 if st.session_state.mode == "control" else 1,
            horizontal=True,
            key="mode_radio",
            label_visibility="collapsed"
        )
        st.session_state.mode = "control" if "控制" in mode else "meeting"

    with rec_col1:
        if not state["recording"]:
            if st.button("▶ 开始录音", type="primary", use_container_width=True):
                state["recording"] = True
                if "audio_processor" not in st.session_state:
                    audio = AudioProcessor(cfg.get("audio", {}))
                    audio.start(callback=on_audio_text)
                    st.session_state.audio_processor = audio
                st.rerun()
        else:
            if st.button("⏹ 停止录音", type="secondary", use_container_width=True):
                state["recording"] = False
                if "audio_processor" in st.session_state:
                    st.session_state.audio_processor.stop()
                st.rerun()

    with rec_col2:
        if state["recording"]:
            st.markdown('<p style="color:#22c55e;text-align:center;margin-top:8px">● 录音中</p>', unsafe_allow_html=True)

    st.markdown("### 🧠 语意理解记录")

    # 转写记录
    with state["lock"]:
        transcripts = list(state["transcripts"])

    if transcripts:
        export_col, clear_col = st.columns([1, 1])
        with export_col:
            lines = []
            for e in transcripts:
                tag = "[指令]" if e["is_command"] else "[对话]"
                line = f"[{e['time']}] {tag} {e['text']}"
                if e.get("cmd"):
                    line += f"\n  → {json.dumps(e['cmd'], ensure_ascii=False)}"
                lines.append(line)
            st.download_button(
                "📥 导出记录",
                data="\n".join(lines),
                file_name=f"语意理解_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
                mime="text/plain",
                use_container_width=True
            )
        with clear_col:
            if st.button("🗑 清空", use_container_width=True):
                with state["lock"]:
                    state["transcripts"] = []
                st.rerun()

        st.caption(f"共 {len(transcripts)} 条")
        with st.container(height=380):
            for entry in reversed(transcripts[-50:]):
                icon = "⚡" if entry["is_command"] else "💬"
                bg = "#2d1f3d" if entry["is_command"] else "#1e2030"
                status = entry.get("status", "pending")
                cmd = entry.get("cmd")
                if status == "sent":
                    tag = '<span style="color:#22c55e;font-size:0.7rem">✓ 已发送</span>'
                elif status == "no_cmd":
                    tag = '<span style="color:#f59e0b;font-size:0.7rem">⚠ 未生成指令</span>'
                elif status == "ignored":
                    tag = '<span style="color:#64748b;font-size:0.7rem">— 非指令</span>'
                elif status == "pending":
                    tag = '<span style="color:#60a5fa;font-size:0.7rem">… 识别中</span>'
                else:
                    tag = ""
                cmd_html = ""
                if cmd:
                    cmd_html = (f'<div style="margin-top:4px;font-size:0.75rem;color:#94a3b8;'
                                f'background:#0f1117;padding:4px 6px;border-radius:4px;font-family:monospace">'
                                f'{json.dumps(cmd, ensure_ascii=False)}</div>')
                st.markdown(
                    f'<div style="background:{bg};padding:8px;border-radius:6px;margin-bottom:6px">'
                    f'<span style="color:#64748b;font-size:0.75rem">{entry["time"]}</span> {icon} {tag}<br>'
                    f'<span style="color:#e2e8f0">{entry["text"]}</span>'
                    f'{cmd_html}</div>',
                    unsafe_allow_html=True
                )
    else:
        st.info("等待语音输入...")

with right:
    # 右侧 Tab：指令日志 / MQTT流 / 系统日志
    tab_cmd, tab_mqtt, tab_log = st.tabs(["⚡ 指令日志", "📡 MQTT流", "🔧 系统日志"])

    with tab_cmd:
        with state["lock"]:
            cmd_log = list(state["cmd_log"])
        if cmd_log:
            with st.container(height=360):
                for entry in reversed(cmd_log):
                    st.markdown(
                        f'<div style="background:#1a2035;padding:8px;border-radius:6px;margin-bottom:6px">'
                        f'<span style="color:#64748b;font-size:0.75rem">{entry["time"]}</span> '
                        f'<span style="color:#60a5fa;font-size:0.75rem">[{entry["source"]}]</span> '
                        f'<span style="color:#22c55e;font-size:0.75rem">{entry["status"]}</span><br>'
                        f'<span style="color:#e2e8f0">{entry["text"]}</span><br>'
                        f'<span style="color:#94a3b8;font-size:0.75rem;font-family:monospace">'
                        f'{json.dumps(entry["cmd"], ensure_ascii=False)}</span></div>',
                        unsafe_allow_html=True
                    )
            if st.button("清空日志", use_container_width=True):
                with state["lock"]:
                    state["cmd_log"] = []
                st.rerun()
        else:
            st.info("暂无指令记录")

    with tab_mqtt:
        with state["lock"]:
            messages = list(state["mqtt_messages"])
        if messages:
            with st.container(height=360):
                for msg in reversed(messages[-15:]):
                    topic = msg["topic"]
                    payload = msg["payload"]
                    if "video" in topic:
                        st.info(f"**[视频]** {topic}\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```")
                    elif "audio" in topic:
                        st.success(f"**[语音]** {topic}\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```")
                    elif "control" in topic:
                        st.warning(f"**[控制]** {topic}\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```")
                    else:
                        st.text(f"[{msg['time']}] {topic}: {payload}")
        else:
            st.info("等待MQTT消息...")

    with tab_log:
        with state["lock"]:
            syslog = list(state["system_log"])
        if syslog:
            if st.button("清空日志", key="clear_syslog", use_container_width=True):
                with state["lock"]:
                    state["system_log"] = []
                st.rerun()
            with st.container(height=320):
                for entry in reversed(syslog[-100:]):
                    level = entry.get("level", "INFO")
                    color = {"LLM": "#60a5fa", "ERROR": "#f87171", "WARN": "#f59e0b"}.get(level, "#94a3b8")
                    st.markdown(
                        f'<div style="font-size:0.75rem;padding:3px 0;border-bottom:1px solid #1e2030">'
                        f'<span style="color:#64748b">{entry["time"]}</span> '
                        f'<span style="color:{color};font-weight:600">[{level}]</span> '
                        f'<span style="color:#e2e8f0">{entry["msg"]}</span></div>',
                        unsafe_allow_html=True
                    )
        else:
            st.info("暂无日志")


# 自动刷新（录音中或有视频流时）
has_video = bool([s for s in video.sources if s.get("enabled", True)])
if state["recording"] or has_video:
    time.sleep(0.5)
    st.rerun()
