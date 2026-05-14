#!/usr/bin/env python3
"""
main.py
AV统一系统 - Supervisor 入口 (R2)

职责：
  1. profile 探测 + 打印启动信息
  2. 起 web/server.py（SSE 服务，4 路 channel）
  3. 起 MQTTBridge 旁路订阅：MQTT 各 topic → web SSE 桥接
  4. subprocess.Popen × 3 拉起独立模块（audio / video / llm）
  5. 主循环 poll()，崩溃指数退避重拉（5 次后告警继续重拉）
"""
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

# 让本机服务（ollama / mosquitto / funasr）请求绕开系统 HTTP 代理。
# 必须在 import requests 之前设。
os.environ.setdefault("NO_PROXY", "127.0.0.1,localhost,::1")
os.environ.setdefault("no_proxy", "127.0.0.1,localhost,::1")

# 离线友好：阻止 modelscope/funasr 库做远端探测。
# 必须在 import funasr/modelscope 之前设。
os.environ.setdefault("MODELSCOPE_DOMAIN", "")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import yaml

sys.path.insert(0, str(Path(__file__).parent))

from core.mqtt_bridge import MQTTBridge
from core.profile import PROFILES, announce, recommend_profile, total_ram_gb

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S"
)
logger = logging.getLogger(__name__)

# 受 supervisor 管理的独立模块
MANAGED_MODULES = [
    "modules.audio_processor.main",
    "modules.video_processor.main",
    "modules.llm_engine.main",
    # R6：系统/网络观测模块
    "modules.system_info.main",
    "modules.network_info.main",
    "modules.network_scanner.main",
    # 跨品牌桥接：husion HDC900 一体机分布式终端发现
    "modules.husion_distributed.main",
    # av/control → 设备 dispatcher（当前 echo_only，dashboard 反馈用；
    # 接真硬件后扩 husion / Node-RED / 厂商 adapter）
    "modules.control_dispatcher.main",
    # 关键帧过滤：av/video/detect → av/video/key_event，减少 Jetson VLM
    # 无效触发（密集场景从 8 Hz 降到 ~0.1-0.5 Hz）
    "modules.keyframe_filter.main",
    # 开放词检测：订 av/video/key_event → yolov8s-world (CLIP) → av/video/openvocab
    # 化工/安全场景 (火/烟/未戴安全帽/跌倒/打架) — 5/14 落地，3588 CPU ~1.6s/帧
    "modules.openvocab_filter.main",
]

MAX_RETRY_DELAY = 60   # 最大退避秒数
WARN_AFTER_FAILS = 5   # 连续失败几次后升级为 ERROR 告警


class AVSupervisor:
    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            self.cfg = yaml.safe_load(f)

        self._config_path = Path(config_path)
        # config_path = .../av_unified_mvp/config/system_config.yaml
        # project_root = .../av_unified_mvp/ （config/ 的上级）
        self._project_root = self._config_path.parent.parent

        self._apply_profile()

        self.mqtt = MQTTBridge(self.cfg.get("mqtt", {}))
        self._web_push = lambda *_: None

        # module → {proc, fail_count, retry_delay, next_retry, spawn_time}
        self._procs: dict = {}
        self._running = False

    def _apply_profile(self) -> None:
        sys_cfg = self.cfg.setdefault("system", {})
        # AV_PROFILE_OVERRIDE 由 start.command 在 docker 不可用时设为 light，强制覆盖
        override = os.environ.get("AV_PROFILE_OVERRIDE")
        active = override or sys_cfg.get("performance_profile") or recommend_profile(total_ram_gb())
        sys_cfg["performance_profile"] = active
        if active in PROFILES:
            p = PROFILES[active]
            audio_funasr = self.cfg.setdefault("audio", {}).setdefault("funasr", {})
            yolo = self.cfg.setdefault("video", {}).setdefault("yolo", {})
            if override:
                audio_funasr["mode"] = p["audio_mode"]
                yolo["model"] = p["video_model"]
                logger.info(f"profile 被 AV_PROFILE_OVERRIDE 临时切到 {active}（不写回 config）")
            else:
                audio_funasr.setdefault("mode", p["audio_mode"])
                yolo.setdefault("model", p["video_model"])
        announce(active)

    # ── 启动/停止 ─────────────────────────────────────────────────────

    def start(self):
        logger.info("=" * 60)
        logger.info("  AV统一系统 Supervisor 启动中...")
        logger.info("=" * 60)

        self._start_web()
        self._start_mqtt()
        self._spawn_all()

        self._running = True
        logger.info("✓ Supervisor 已启动，按 Ctrl+C 停止\n")

        try:
            while self._running:
                self._tick()
                time.sleep(1)
        except KeyboardInterrupt:
            logger.info("\n收到停止信号")

        self.stop()

    def stop(self):
        logger.info("正在停止 Supervisor...")
        self._running = False
        for module, state in self._procs.items():
            proc = state["proc"]
            if proc.poll() is None:
                logger.info(f"  终止 {module} (PID={proc.pid})...")
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()
        self.mqtt.stop()
        self._cleanup_external()
        logger.info("已退出")

    def _cleanup_external(self):
        """清理 start.command 拉起但不属于 supervisor 子进程的外部服务。

        Web 退出按钮触发 stop() 时，希望"完整清场"：mosquitto / Node-RED / FunASR
        都是 start.command 里 detached 起的，得在这里一并 kill，否则会留后台僵尸。
        每条独立 try，单条失败不影响其它清理。
        """
        for desc, cmd in [
            ("Node-RED", ["pkill", "-f", "node-red"]),
            ("mosquitto", ["pkill", "-x", "mosquitto"]),
            ("funasr-2pass", ["docker", "stop", "funasr-2pass"]),
        ]:
            try:
                subprocess.run(cmd, timeout=8, check=False,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                logger.info(f"  外部服务已停: {desc}")
            except Exception as e:
                logger.warning(f"  外部服务停止失败 {desc}: {e}")

    # ── Supervisor 主循环 ─────────────────────────────────────────────

    def _spawn(self, module: str) -> subprocess.Popen:
        """启动一个独立模块子进程，继承当前环境变量（含 AV_PROFILE_OVERRIDE）。"""
        proc = subprocess.Popen(
            [sys.executable, "-m", module],
            cwd=str(self._project_root),
            env=os.environ.copy(),
        )
        logger.info(f"[supervisor] 拉起 {module} (PID={proc.pid})")
        return proc

    def _spawn_all(self):
        now = time.time()
        for module in MANAGED_MODULES:
            proc = self._spawn(module)
            self._procs[module] = {
                "proc": proc,
                "fail_count": 0,
                "retry_delay": 1.0,
                "next_retry": now,
                "spawn_time": now,
            }

    def _tick(self):
        """每秒检查一次各模块是否存活，崩溃则退避重拉。"""
        now = time.time()
        for module, state in self._procs.items():
            if state["proc"].poll() is None:
                continue  # 还在跑

            if now < state["next_retry"]:
                continue  # 还在等退避

            # 运行超过 MAX_RETRY_DELAY 秒才崩溃，视为健康运行过，重置退避计数
            if now - state["spawn_time"] > MAX_RETRY_DELAY:
                state["fail_count"] = 0
                state["retry_delay"] = 1.0

            state["fail_count"] += 1
            fc = state["fail_count"]
            state["retry_delay"] = min(state["retry_delay"] * 2, MAX_RETRY_DELAY)
            state["next_retry"] = now + state["retry_delay"]

            if fc >= WARN_AFTER_FAILS:
                logger.error(
                    f"[supervisor] ⚠️  {module} 已连续失败 {fc} 次！"
                    f"下次 {state['retry_delay']:.0f}s 后重试"
                )
            else:
                logger.warning(
                    f"[supervisor] {module} 已退出，第 {fc} 次重拉"
                    f"（退避 {state['retry_delay']:.0f}s）"
                )

            proc = self._spawn(module)
            state["proc"] = proc
            state["spawn_time"] = now

    # ── Web SSE 服务 ────────────────────────────────────────────────────

    def _start_web(self):
        web_cfg = self.cfg.get("web", {})
        if not web_cfg.get("transcript_enabled", True):
            return
        try:
            from web.server import (
                push as web_push,
                run as run_web,
                set_mqtt_publisher,
                set_run_error_handler,
                set_shutdown_handler,
            )
        except ModuleNotFoundError as e:
            logger.warning(f"演示页未启动（缺依赖：{e}）")
            return

        self._web_push = web_push
        # 让 web 端的 /camera/<name>/(enable|disable) 能通过 MQTT 通知 video_processor
        set_mqtt_publisher(self.mqtt.publish)
        # POST /system/shutdown → 设 _running=False 让主循环退出，stop() 清子进程 + 外部服务
        set_shutdown_handler(lambda: setattr(self, "_running", False))
        # K4：Flask 启动失败（Address In Use 等）→ 让主循环退出，user 在终端看到清晰错误
        set_run_error_handler(self._on_web_run_error)
        host = web_cfg.get("host", "0.0.0.0")
        port = int(web_cfg.get("transcript_port", 5050))

        threading.Thread(
            target=run_web, kwargs={"host": host, "port": port}, daemon=True
        ).start()
        logger.info(f"演示页: http://{host}:{port}  (SSE 订阅制)")

        # Supervisor 自身宣告：向 discovery SSE 推控制流面板描述
        # 延迟 1s 等 SSE 注册好再推
        def _announce():
            time.sleep(1)
            self._announce_supervisor()
        threading.Thread(target=_announce, daemon=True).start()

    def _on_web_run_error(self, exc: Exception) -> None:
        """Flask daemon thread 抛错回调。立即让主循环退出（stop() 会清子进程 + 外部服务）。"""
        logger.error(f"⚠️  Web 启动失败 — supervisor 即将退出：{exc}")
        self._running = False

    def _announce_supervisor(self):
        """Supervisor 向 discovery SSE channel 推一条伪 discovery，使 UI 生成控制面板。"""
        self._web_push("discovery", {
            "module": "supervisor",
            "client_id": "supervisor",
            "ip": "127.0.0.1",
            "ts": time.time(),
            "event": "online",
            "heartbeat_interval": 3600,
            "version": "R2",
            "streams": [
                {"topic": "av/control", "channel": "control", "kind": "kv_table", "title": "控制指令"},
            ],
            "endpoints": [],
        })

    # ── MQTT 旁路（MQTT → web SSE 桥接，supervisor 专用） ────────────────

    def _start_mqtt(self):
        self.mqtt.start()
        time.sleep(1)
        topics = self.cfg.get("mqtt", {}).get("topics", {})

        # transcript channel：音频流式转写 + 定稿
        self.mqtt.subscribe(
            topics.get("audio_partial", "av/audio/partial"),
            self._on_audio_partial,
        )
        self.mqtt.subscribe(
            topics.get("audio_command", "av/audio/command"),
            self._on_audio_command,
        )
        # video channel：视频检测事件
        self.mqtt.subscribe(
            topics.get("video_detect", "av/video/detect"),
            self._on_video_detect,
        )
        # intent channel：意图识别 / 指令翻译
        self.mqtt.subscribe("av/llm/event", self._on_llm_event)
        # control channel：最终控制指令
        self.mqtt.subscribe(
            topics.get("control", "av/control"),
            self._on_control,
        )
        # discovery channel：模块上线/心跳/离线公告（通配符订阅，需 MQTTBridge 支持 #）
        self.mqtt.subscribe("av/system/discovery/#", self._on_discovery_mqtt)
        # R6：主机指标 / 网络 / LAN 扫描 → 各自 SSE channel
        self.mqtt.subscribe("av/system/host_stats", self._on_host_stats)
        self.mqtt.subscribe("av/system/network", self._on_network)
        self.mqtt.subscribe("av/system/lan_scan/+", self._on_lan_scan)
        # 5/14 Sub-7：open-vocab 检测命中 → openvocab SSE channel（dashboard timeline 面板）
        self.mqtt.subscribe("av/video/openvocab", self._on_openvocab)

    def _on_audio_partial(self, topic: str, payload: dict):
        """BaseModule 双层载荷 → 提取内层推到 transcript SSE"""
        inner = payload.get("payload", payload)
        self._web_push("transcript", inner)

    def _on_audio_command(self, topic: str, payload: dict):
        """final 转写 → transcript SSE（与 partial 复用同 seq_id 气泡）"""
        inner = payload.get("payload", payload)
        self._web_push("transcript", inner)

    def _on_video_detect(self, topic: str, payload: dict):
        """BaseModule publish 后字段在顶层（header + camera/time/detections）"""
        self._web_push("video", payload)

    def _on_llm_event(self, topic: str, payload: dict):
        """意图识别事件 → intent SSE（dashboard.js 能处理双层或单层）"""
        self._web_push("intent", payload)

    def _on_control(self, topic: str, payload: dict):
        """控制指令 → control SSE；兼容 Node-RED（平层）和 llm_engine（双层）两种格式"""
        logger.info(f"[控制] 收到指令: {payload}")
        inner = payload.get("payload", payload)
        source = (payload.get("header") or {}).get("source", "")
        ts = (payload.get("header") or {}).get("timestamp") or inner.get("ts")
        ev = {**inner}
        if source and "source" not in ev:
            ev["source"] = source
        if ts and "ts" not in ev:
            ev["ts"] = ts
        self._web_push("control", ev)

    def _on_host_stats(self, topic: str, payload: dict):
        """主机指标 → host_stats SSE channel"""
        self._web_push("host_stats", payload)

    def _on_network(self, topic: str, payload: dict):
        """网络状态 → network SSE channel"""
        self._web_push("network", payload)

    def _on_lan_scan(self, topic: str, payload: dict):
        """扫描进度 / 结果 → lan_scan SSE channel"""
        self._web_push("lan_scan", payload)

    def _on_openvocab(self, topic: str, payload: dict):
        """openvocab_filter 命中 → openvocab SSE channel（dashboard 化工安全 timeline 面板）。

        BaseModule.publish 把 payload 字段平铺到顶层（含 hits / camera / inference_ms 等），
        加一个 header key；前端 pushOverviewOpenvocab 直接读顶层即可。
        """
        self._web_push("openvocab", payload)

    def _on_discovery_mqtt(self, topic: str, payload: dict):
        """MQTT av/system/discovery/# → discovery SSE channel，驱动前端动态面板"""
        if not isinstance(payload, dict):
            return
        event = payload.get("event", "")
        module = payload.get("module", topic.split("/")[-1])
        if event == "online":
            logger.info(f"[发现] 模块上线: {module} @ {payload.get('ip')}")
        elif event == "offline":
            logger.info(f"[发现] 模块离线: {module}")
        self._web_push("discovery", payload)


# ── 入口 ─────────────────────────────────────────────────────────────────

def main():
    config_path = Path(__file__).parent / "config" / "system_config.yaml"
    if not config_path.exists():
        logger.error(f"配置文件不存在: {config_path}")
        sys.exit(1)

    supervisor = AVSupervisor(str(config_path))

    def handle_signal(sig, frame):
        supervisor._running = False

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    supervisor.start()


if __name__ == "__main__":
    main()
