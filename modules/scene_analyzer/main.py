#!/usr/bin/env python3
"""
modules/scene_analyzer/main.py
视觉深思层 — 订阅 av/video/detect，拉 mjpeg snapshot，喂 ollama VLM (qwen2.5vl:3b)，
发场景语义到 av/video/scene_analysis。

设计契约：
  - 每个 camera 节流 throttle_seconds 一次（默认 10s）
  - RAM 守门：psutil 看 mem_avail < mem_min_mb 直接 skip 当帧（避免触发硬终止器）
  - 单 worker ThreadPool：Orin Nano 7.4G RAM 跑 qwen2.5vl:3b 不能并发
  - inflight=True 时直接 drop 后续 detect，不在 queue 堆积
  - 异常 / 超时全部 log warning + skip，绝不抛
  - 只在 Jetson 副本启用（main.py MANAGED_MODULES 不加它，main_jetson.py 加）

Topic:
  订阅 av/video/detect（payload：{camera, time, detections:[{class, confidence, bbox}]}）
  发布 av/video/scene_analysis（payload：{camera, time, detection_classes, scene,
       vlm_model, vlm_latency_ms, vlm_prompt_eval_ms, mem_avail_mb_before, source_host}）
"""
import base64
import logging
import signal
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import psutil
import requests
import yaml

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)


DEFAULTS = {
    "enabled": True,
    "vlm_model": "qwen2.5vl:3b",
    "ollama_url": "http://127.0.0.1:11434/api/generate",
    "mjpeg_base_url": "http://192.168.5.6:5051",
    # detect_topic 默认订关键帧 key_event（非每个 detect），减少 VLM 无效触发。
    # 5/14 起 keyframe_filter 模块独立上线 → scene_analyzer 自然只看关键帧。
    # 旧行为（每 detect 都看）可 yaml 设 detect_topic: av/video/detect 覆盖。
    "detect_topic": "av/video/key_event",
    "analysis_topic": "av/video/scene_analysis",
    "throttle_seconds": 10.0,
    "mem_min_mb": 400,
    "vlm_timeout_s": 120,
    "snapshot_timeout_s": 5,
    "snapshot_mode": "raw",
    "num_predict": 80,
    "prompt": "用一句话描述这张图里看到了什么，重点是人、物体、动作。",
    "host_label": "jetson",
    "diff_enabled": False,  # 开启后每次 inference 完再调 1 次纯文本 VLM 跟上一帧 scene 对比
    "diff_num_predict": 40,
    "diff_timeout_s": 30,
    "diff_prompt": "上一帧场景: {prev}\n本次场景: {curr}\n用一句话指出关键变化（人数/位置/动作/物品出现或消失）；若两段几乎相同输出 NO_CHANGE。",
    "dashboard_sse_url": None,  # 例: "http://192.168.5.5:5050"；非空时 POST 一份到 dashboard /mock/scene_analysis 让前端 SSE 也能拿到
    # keep-warm 防 ollama 默认 5min TTL unload，否则稀疏 detect 每次都冷启 70s。
    # keep_alive: ollama 字段 — 实际推理时附带，"10m" 表示推理后保活 10 分钟。
    # keep_warm_interval_s: opt-in 后台 ping，0 = 关；>0 表示每 N 秒发空请求触底，
    #   保活成本是 5.8GB VRAM 持续占用（Jetson Orin Nano 7.4G unified mem 极紧时
    #   可能挤压 audio_processor，需配合 mem_min_mb 守门），生产化默认开 60-180s。
    "keep_alive": "10m",
    "keep_warm_interval_s": 0,
}


class SceneAnalyzerModule(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        # scene_analyzer 自己的子配置；缺省全走 DEFAULTS
        sa = dict(DEFAULTS)
        sa.update(cfg.get("scene_analyzer", {}) or {})
        self._sa = sa

        streams = [{
            "topic": sa["analysis_topic"],
            "channel": "scene_analysis",
            "kind": "kv_table",
            "title": "视觉深思 · 场景分析",
        }]
        super().__init__("scene_analyzer", cfg, streams=streams)

        self._last_inference_ts: dict[str, float] = {}
        self._inflight_lock = threading.Lock()
        self._inflight = False
        self._last_scene_per_camera: dict[str, str] = {}
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vlm")
        self._stats = {
            "detect_received": 0,
            "throttled": 0,
            "inflight_skipped": 0,
            "mem_guard_skipped": 0,
            "snapshot_failed": 0,
            "vlm_failed": 0,
            "vlm_published": 0,
            "diff_published": 0,
            "diff_failed": 0,
            "keep_warm_pinged": 0,
            "keep_warm_failed": 0,
        }
        self._keep_warm_stop = threading.Event()
        self._keep_warm_thread: threading.Thread | None = None

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        if not sa["enabled"]:
            self.logger.info("scene_analyzer 配置 enabled=false，仅占位不工作")
            return
        self.subscribe(sa["detect_topic"])
        # G1: mjpeg_base_url 动态解析 — yaml 是 fallback；订 video_processor discovery 收到 ip 即覆盖。
        self._mjpeg_base_url = sa["mjpeg_base_url"]
        self.subscribe("av/system/discovery/video_processor")
        # G3a: dashboard 可下发 watch_camera 限定只看某一路 keyframe；None=全部（默认）。
        self._watch_camera: str | None = None
        self.subscribe("av/video/scene_analyzer/config")
        self.logger.info(
            f"订阅 {sa['detect_topic']} | VLM={sa['vlm_model']} | "
            f"节流={sa['throttle_seconds']}s | mem_min={sa['mem_min_mb']}MB | "
            f"keep_alive={sa['keep_alive']} | keep_warm_ping={sa['keep_warm_interval_s']}s"
        )
        if sa["keep_warm_interval_s"] > 0:
            self._keep_warm_thread = threading.Thread(
                target=self._keep_warm_loop, name="keep-warm", daemon=True
            )
            self._keep_warm_thread.start()

    def _keep_warm_loop(self) -> None:
        """opt-in 后台线程：定时发空请求（带 keep_alive）触底，让 ollama 不 unload 模型。

        触发节奏：每 keep_warm_interval_s 一次（典型 120-240s，小于 keep_alive 时长）。
        发送的请求是最小化的 — prompt 空 + num_predict 1，几乎零推理成本，但走 ollama
        load 路径让模型保持在 VRAM。

        副作用：模型常驻 VRAM ~5.8GB，Jetson Orin Nano 7.4G 上 audio_processor +
        系统 + buff 总占用接近上限。需配合 mem_guard 防 OOM 累加。
        """
        interval = self._sa["keep_warm_interval_s"]
        url = self._sa["ollama_url"]
        body = {
            "model": self._sa["vlm_model"],
            "prompt": "",  # 空 prompt，仅触发模型加载/保活
            "stream": False,
            "options": {"num_predict": 1},
            "keep_alive": self._sa["keep_alive"],
        }
        self.logger.info(f"keep-warm 线程启动：每 {interval}s ping 一次")
        while not self._keep_warm_stop.wait(interval):
            try:
                r = requests.post(url, json=body, timeout=15)
                if r.status_code == 200:
                    self._stats["keep_warm_pinged"] += 1
                else:
                    self._stats["keep_warm_failed"] += 1
                    self.logger.warning(f"keep-warm HTTP {r.status_code}")
            except Exception as e:
                self._stats["keep_warm_failed"] += 1
                self.logger.warning(f"keep-warm 异常：{e}")

    def _handle_message(self, topic: str, payload: dict) -> None:
        # G1: video_processor discovery → 更新 mjpeg_base_url
        if topic.startswith("av/system/discovery/"):
            self._on_video_discovery(payload)
            return
        # G3a: dashboard 下发 watch_camera 切换
        if topic == "av/video/scene_analyzer/config":
            inner = payload.get("payload", payload)  # 兼容 BaseModule 双层与 web/server.py 裸 payload
            self._watch_camera = inner.get("watch_camera") or None
            self.logger.info(f"watch_camera 更新 → {self._watch_camera or '全部'}")
            return
        if topic != self._sa["detect_topic"]:
            return
        if not self._sa["enabled"]:
            return
        self._stats["detect_received"] += 1
        # video_processor 发的 payload：{header, camera, time, detections}
        camera = payload.get("camera")
        det_time = payload.get("time") or time.time()
        detections = payload.get("detections") or []
        if not camera:
            return
        # G3a: 限定只看 watch_camera（在节流/计数之前 short-circuit，避免污染 stats）
        if self._watch_camera and camera != self._watch_camera:
            return
        classes = sorted({d.get("class") for d in detections if d.get("class")})
        # 节流
        now = time.time()
        last = self._last_inference_ts.get(camera, 0.0)
        if now - last < self._sa["throttle_seconds"]:
            self._stats["throttled"] += 1
            return
        # 单 worker，inflight 就丢；不排队（防 detect 高频堆积）
        with self._inflight_lock:
            if self._inflight:
                self._stats["inflight_skipped"] += 1
                return
            self._inflight = True
        # 抢占式更新 last_ts：避免同 camera 紧跟着多次进入
        self._last_inference_ts[camera] = now
        self._pool.submit(self._analyze, camera, det_time, classes)

    def _analyze(self, camera: str, det_time: float, classes: list) -> None:
        try:
            mem_avail_mb = psutil.virtual_memory().available // (1024 * 1024)
            if mem_avail_mb < self._sa["mem_min_mb"]:
                self._stats["mem_guard_skipped"] += 1
                self.logger.warning(
                    f"mem_avail={mem_avail_mb}MB < {self._sa['mem_min_mb']}MB，"
                    f"skip {camera}"
                )
                return
            t_snap0 = time.monotonic()
            jpg = self._fetch_snapshot(camera)
            t_snap_ms = (time.monotonic() - t_snap0) * 1000
            if jpg is None:
                self._stats["snapshot_failed"] += 1
                return
            img_b64 = base64.b64encode(jpg).decode("ascii")
            t_vlm0 = time.monotonic()
            result = self._call_vlm(img_b64)
            t_vlm_ms = (time.monotonic() - t_vlm0) * 1000
            if result is None:
                self._stats["vlm_failed"] += 1
                return
            scene = result.get("response", "").strip()
            if not scene:
                self._stats["vlm_failed"] += 1
                return
            # 可选：跨帧 diff（第二次 VLM 调用，纯文本对比；默认关）
            prev_scene = self._last_scene_per_camera.get(camera)
            diff_text = None
            diff_ms = 0
            if self._sa.get("diff_enabled") and prev_scene:
                t_diff0 = time.monotonic()
                diff_text = self._call_diff(prev_scene, scene)
                diff_ms = int((time.monotonic() - t_diff0) * 1000)
                if diff_text:
                    self._stats["diff_published"] += 1
                else:
                    self._stats["diff_failed"] += 1
            payload_out = {
                "camera": camera,
                "time": det_time,
                "detection_classes": classes,
                "scene": scene,
                "vlm_model": self._sa["vlm_model"],
                "vlm_latency_ms": int(t_vlm_ms),
                "vlm_load_ms": result.get("load_duration", 0) // 1_000_000,
                "vlm_prompt_eval_ms": result.get("prompt_eval_duration", 0) // 1_000_000,
                "vlm_eval_ms": result.get("eval_duration", 0) // 1_000_000,
                "vlm_eval_count": result.get("eval_count", 0),
                "snapshot_latency_ms": int(t_snap_ms),
                "mem_avail_mb_before": int(mem_avail_mb),
                "source_host": self._sa["host_label"],
            }
            if prev_scene is not None:
                payload_out["prev_scene"] = prev_scene
            if diff_text is not None:
                payload_out["diff"] = diff_text
                payload_out["diff_vlm_ms"] = diff_ms
            self._last_scene_per_camera[camera] = scene
            self.publish(self._sa["analysis_topic"], payload_out)
            self._stats["vlm_published"] += 1
            self._push_to_dashboard({**payload_out, "ts": time.time()})
            self.logger.info(
                f"[scene] {camera} cls={classes} | "
                f"VLM {int(t_vlm_ms)}ms | mem→{mem_avail_mb}MB | "
                f"\"{scene[:50]}{'...' if len(scene) > 50 else ''}\""
            )
        except Exception as e:
            self._stats["vlm_failed"] += 1
            self.logger.warning(f"_analyze 异常 camera={camera}: {e}")
        finally:
            with self._inflight_lock:
                self._inflight = False

    def _on_video_discovery(self, payload: dict) -> None:
        """G1: video_processor discovery 更新 mjpeg_base_url。
        用 payload.ip（BaseModule._get_local_ip 出口 IP）而非 endpoints[0].url（127.0.0.1 本机视角，scene_analyzer 不可达）。
        端口 5051 是 video_processor 固定 MJPEG 端口，hardcoded 即可。
        """
        ip = payload.get("ip")
        if ip and ip != "127.0.0.1":
            new_base = f"http://{ip}:5051"
            if new_base != self._mjpeg_base_url:
                self.logger.info(f"mjpeg_base_url 更新 {self._mjpeg_base_url} → {new_base}")
                self._mjpeg_base_url = new_base

    def _fetch_snapshot(self, camera: str) -> bytes | None:
        # G1: 用动态 _mjpeg_base_url（discovery 解析），不读 yaml 静态字段
        url = (
            f"{self._mjpeg_base_url}/snapshot/"
            f"{quote(camera)}?mode={self._sa['snapshot_mode']}"
        )
        try:
            r = requests.get(url, timeout=self._sa["snapshot_timeout_s"])
            if r.status_code != 200 or not r.content:
                self.logger.warning(
                    f"snapshot 失败 camera={camera} status={r.status_code} "
                    f"len={len(r.content)}"
                )
                return None
            return r.content
        except Exception as e:
            self.logger.warning(f"snapshot 异常 camera={camera}: {e}")
            return None

    def _call_vlm(self, img_b64: str) -> dict | None:
        body = {
            "model": self._sa["vlm_model"],
            "prompt": self._sa["prompt"],
            "images": [img_b64],
            "stream": False,
            "options": {"num_predict": self._sa["num_predict"]},
            "keep_alive": self._sa["keep_alive"],  # 推理后保活，覆盖 ollama 默认 5m TTL
        }
        try:
            r = requests.post(
                self._sa["ollama_url"],
                json=body,
                timeout=self._sa["vlm_timeout_s"],
            )
            if r.status_code != 200:
                self.logger.warning(
                    f"VLM HTTP {r.status_code}: {r.text[:200]}"
                )
                return None
            return r.json()
        except requests.Timeout:
            self.logger.warning(f"VLM 超时 {self._sa['vlm_timeout_s']}s")
            return None
        except Exception as e:
            self.logger.warning(f"VLM 异常: {e}")
            return None

    def _call_diff(self, prev_scene: str, curr_scene: str) -> str | None:
        """纯文本 VLM 调用，做前后帧 scene 对比；同 model（model 已暖）只是 prompt 不带图。"""
        prompt = self._sa["diff_prompt"].format(prev=prev_scene, curr=curr_scene)
        body = {
            "model": self._sa["vlm_model"],
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": self._sa["diff_num_predict"]},
            "keep_alive": self._sa["keep_alive"],
        }
        try:
            r = requests.post(
                self._sa["ollama_url"],
                json=body,
                timeout=self._sa["diff_timeout_s"],
            )
            if r.status_code != 200:
                self.logger.warning(f"diff VLM HTTP {r.status_code}")
                return None
            text = r.json().get("response", "").strip()
            return text or None
        except Exception as e:
            self.logger.warning(f"diff VLM 异常: {e}")
            return None

    def _push_to_dashboard(self, payload: dict) -> None:
        """可选：把场景事件直接 POST 到 dashboard 的 /mock/scene_analysis SSE 桥。
        默认关；配 dashboard_sse_url 后开。失败仅 warn，不影响主路径。
        """
        url = self._sa.get("dashboard_sse_url")
        if not url:
            return
        try:
            requests.post(
                f"{url.rstrip('/')}/mock/scene_analysis",
                json=payload, timeout=2,
            )
        except Exception as e:
            self.logger.warning(f"dashboard push 失败: {e}")

    def run(self) -> None:
        """主循环：心跳 + 每 60s 打一次统计行（便于跨夜 log 抓数据）。"""
        self.start()
        last_heartbeat = time.time()
        last_stats = time.time()
        try:
            while self._running.is_set():
                time.sleep(1)
                now = time.time()
                if now - last_heartbeat >= self.HEARTBEAT_INTERVAL and self._connected:
                    self._publish_discovery("heartbeat")
                    last_heartbeat = now
                if now - last_stats >= 60:
                    self.logger.info(f"[stats] {self._stats}")
                    last_stats = now
        except KeyboardInterrupt:
            self.logger.info("收到键盘中断信号")
        finally:
            self._keep_warm_stop.set()
            self._pool.shutdown(wait=False, cancel_futures=True)
            self.stop()


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    module = SceneAnalyzerModule(str(config_path))
    module.run()


if __name__ == "__main__":
    main()
