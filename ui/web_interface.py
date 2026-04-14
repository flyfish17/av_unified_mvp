"""
web_interface.py
Streamlit Web界面 - 实时监控
"""
import json
import sys
from pathlib import Path

import streamlit as st
import yaml

# 添加core目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.mqtt_bridge import MQTTBridge

st.set_page_config(page_title="AV统一系统", layout="wide")

# ── 初始化 ────────────────────────────────────────────────────────────

@st.cache_resource
def init_mqtt():
    config_path = Path(__file__).parent.parent / "config" / "system_config.yaml"
    with open(config_path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)

    mqtt = MQTTBridge(cfg.get("mqtt", {}))
    mqtt.start()

    # 订阅所有主题
    topics = cfg.get("mqtt", {}).get("topics", {})

    def on_msg(topic, payload):
        if "messages" not in st.session_state:
            st.session_state.messages = []
        st.session_state.messages.append({
            "topic": topic,
            "payload": payload,
            "time": payload.get("time", "")
        })
        # 只保留最近100条
        if len(st.session_state.messages) > 100:
            st.session_state.messages.pop(0)

    for topic in topics.values():
        mqtt.subscribe(topic, on_msg)

    return mqtt, cfg

mqtt, cfg = init_mqtt()

if "messages" not in st.session_state:
    st.session_state.messages = []

# ── 界面 ──────────────────────────────────────────────────────────────

st.title("🎬 AV统一系统监控")

col1, col2, col3 = st.columns(3)

with col1:
    st.metric("MQTT状态", "✓ 已连接" if mqtt.connected else "✗ 断开")

with col2:
    st.metric("设备ID", cfg.get("mqtt", {}).get("client_id", "未知"))

with col3:
    st.metric("消息数", len(st.session_state.messages))

st.divider()

# ── 实时消息流 ────────────────────────────────────────────────────────

st.subheader("📡 实时消息流")

# 自动刷新
st_autorefresh = st.empty()
with st_autorefresh:
    if st.button("🔄 刷新", key="refresh"):
        st.rerun()

# 显示最近消息
if st.session_state.messages:
    for msg in reversed(st.session_state.messages[-20:]):  # 最近20条
        topic = msg["topic"]
        payload = msg["payload"]

        # 根据主题类型显示不同颜色
        if "video" in topic:
            st.info(f"**[视频]** {topic}\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```")
        elif "audio" in topic:
            st.success(f"**[语音]** {topic}\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```")
        elif "control" in topic:
            st.warning(f"**[控制]** {topic}\n```json\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n```")
        else:
            st.text(f"[{topic}] {payload}")
else:
    st.info("等待消息...")

st.divider()

# ── 手动发送控制指令 ──────────────────────────────────────────────────

st.subheader("🎮 手动控制")

with st.form("control_form"):
    device = st.selectbox("设备", ["灯光", "空调", "窗帘", "大屏", "音量"])
    action = st.selectbox("动作", ["开", "关", "调节"])
    value  = st.text_input("参数（可选）", "")

    if st.form_submit_button("发送"):
        cmd = {
            "device": device,
            "action": action,
            "value": value,
            "source": "web_manual"
        }
        topics = cfg.get("mqtt", {}).get("topics", {})
        mqtt.publish(topics.get("control", "av/control"), cmd)
        st.success(f"已发送: {cmd}")
