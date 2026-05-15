#!/usr/bin/env python3
"""
modules/keyframe_filter/main.py — 关键帧过滤器

订 av/video/detect（来自 video_processor，每秒 2 帧 YOLO 检测事件），
计算"是否为关键变化"，仅在 diff 显著时 publish av/video/key_event。

设计目的：
  Jetson scene_analyzer VLM 推理 70s/次，密集场景（人多 / 多 camera）
  下 2 fps × 4 路 = 8 detect/s 不能每个都喂给 VLM。本模块**减触发频率**
  从 8 Hz → ~0.1-0.5 Hz（仅人/物/动作变化时），让 VLM 负载可控。

不动 video_processor — 旁路独立模块，可关。

触发条件（任一）：
  1. 出现新 class（之前没的类首次出现，如 fire / smoke 等专门训练类）
  2. class 数量变化（人数 +1/-1）
  3. bbox 中心移位 > pos_jump_pixels（疑似跌倒 / 闯入 / 快速移动）
  4. 静止时间窗口结束（每 idle_seconds 内若有 detect 但无变化，每 N 秒
     强制发一次 key_event 给 VLM 看，避免漏报"静止异常"如躺人）

Topic：
  订: av/video/detect           {camera, time, detections: [{class, confidence, bbox}]}
  发: av/video/key_event        {camera, time, detections, key_reason, prev_summary}
"""
import logging
import signal
import sys
import time
from pathlib import Path

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
    "detect_topic": "av/video/detect",
    "key_topic": "av/video/key_event",
    # 触发条件
    "pos_jump_pixels": 120,       # bbox 中心位移阈值，>此值算"剧烈位移"
    "idle_seconds": 180,          # 静止窗口，超过这时间无 key 也强发一次（5/14 夜 sustain 选定：60→180 把 key 速率 3.6→1.2/min，匹配 Jetson VLM capacity；详见 OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md）
    # 工程
    "min_interval_s": 3.0,        # 同 camera 两次 key_event 最小间隔（防抖）
    "new_class_set": [],          # 用户自定义"新类即关键"白名单（如 ["fire","smoke"]）。空 = 所有 class 走通用规则
}


class KeyframeFilterModule(BaseModule):

    HEARTBEAT_INTERVAL = 30

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        kf = dict(DEFAULTS)
        kf.update(cfg.get("keyframe_filter", {}) or {})
        self._kf = kf

        streams = [{
            "topic": kf["key_topic"],
            "channel": "key_event",
            "kind": "kv_table",
            "title": "关键帧事件",
        }]
        super().__init__("keyframe_filter", cfg, streams=streams)

        # per-camera 状态：上次发 key 时的 detections 摘要 + 时间戳
        # {camera: {"class_counts": {class: N}, "centers": [(cls, x, y), ...], "last_key_ts": ts}}
        self._prev: dict[str, dict] = {}
        self._last_key_ts: dict[str, float] = {}
        self._stats = {
            "detect_received": 0,
            "key_published": 0,
            "skipped_no_change": 0,
            "skipped_min_interval": 0,
            "forced_idle": 0,
        }

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        if not kf["enabled"]:
            self.logger.info("keyframe_filter enabled=false，仅占位")
            return
        self.subscribe(kf["detect_topic"])
        self.logger.info(
            f"订阅 {kf['detect_topic']} → {kf['key_topic']} | "
            f"pos_jump={kf['pos_jump_pixels']}px | idle={kf['idle_seconds']}s | "
            f"min_interval={kf['min_interval_s']}s | new_class_set={kf['new_class_set']}"
        )

    def _handle_message(self, topic: str, payload: dict) -> None:
        if topic != self._kf["detect_topic"]:
            return
        if not self._kf["enabled"]:
            return
        self._stats["detect_received"] += 1

        inner = payload.get("payload", payload) if isinstance(payload, dict) else {}
        # video_processor 实际发的是顶层 payload（不嵌套），兼容两种
        camera = inner.get("camera") or payload.get("camera")
        detections = inner.get("detections") or payload.get("detections") or []
        det_time = inner.get("time") or payload.get("time") or time.time()
        if not camera:
            return
        # 空 detect 心跳 — 走 idle_force 路径（首次必发；之后按 idle_seconds 节流），
        # 让画面静态时 VLM 也能周期巡检（"画面整体是否正常 / 有无静止异常"）
        if not detections:
            now = time.time()
            last_key_ts = self._last_key_ts.get(camera, 0.0)
            if last_key_ts == 0 or (now - last_key_ts) > self._kf["idle_seconds"]:
                reason = "first_detect_empty" if last_key_ts == 0 else "idle_force_empty"
                self.publish(self._kf["key_topic"], {
                    "camera": camera,
                    "time": det_time,
                    "detections": [],
                    "key_reason": reason,
                    "prev_summary": (self._prev.get(camera) or {}).get("class_counts", {}),
                })
                self._last_key_ts[camera] = now
                self._stats["forced_idle"] += 1
                self._stats["key_published"] += 1
                self.logger.info(f"⚡ key_event camera={camera} reason={reason}")
            return

        # 当前帧摘要
        class_counts: dict[str, int] = {}
        centers: list[tuple[str, float, float]] = []
        for d in detections:
            cls = d.get("class", "?")
            class_counts[cls] = class_counts.get(cls, 0) + 1
            bbox = d.get("bbox") or [0, 0, 0, 0]
            # bbox 兼容 [x,y,w,h] 或 [x1,y1,x2,y2] — 都取近似中心
            if len(bbox) >= 4:
                cx = (bbox[0] + bbox[2]) / 2.0
                cy = (bbox[1] + bbox[3]) / 2.0
                centers.append((cls, cx, cy))

        prev = self._prev.get(camera)
        key_reason = self._diff_reason(prev, class_counts, centers)
        last_key_ts = self._last_key_ts.get(camera, 0.0)
        now = time.time()

        # 最小间隔防抖
        if key_reason and (now - last_key_ts) < self._kf["min_interval_s"]:
            self._stats["skipped_min_interval"] += 1
            self._prev[camera] = {"class_counts": class_counts, "centers": centers, "ts": det_time}
            return

        # idle 强发：很久没 key 也强发一次，让 VLM 巡检"静止异常"
        if not key_reason and (now - last_key_ts) > self._kf["idle_seconds"] and last_key_ts > 0:
            key_reason = "idle_force"
            self._stats["forced_idle"] += 1

        if not key_reason:
            self._stats["skipped_no_change"] += 1
            # 仍更新 prev（即使没发 key，下次 diff 基于这次）
            self._prev[camera] = {"class_counts": class_counts, "centers": centers, "ts": det_time}
            return

        # 发 key_event
        self.publish(self._kf["key_topic"], {
            "camera": camera,
            "time": det_time,
            "detections": detections,
            "key_reason": key_reason,
            "prev_summary": (prev or {}).get("class_counts", {}),
        })
        self._last_key_ts[camera] = now
        self._prev[camera] = {"class_counts": class_counts, "centers": centers, "ts": det_time}
        self._stats["key_published"] += 1
        self.logger.info(f"⚡ key_event camera={camera} reason={key_reason} classes={class_counts}")

    def _diff_reason(self, prev: dict | None, curr_counts: dict, curr_centers: list) -> str | None:
        """返回 None = 无变化；否则返回原因字符串。"""
        new_class_set = set(self._kf["new_class_set"])

        # 自定义 new_class 命中（如 fire/smoke）— 最高优先级
        if new_class_set:
            hit = set(curr_counts.keys()) & new_class_set
            if hit and (not prev or not (set(prev.get("class_counts", {}).keys()) & hit)):
                return f"new_class:{','.join(sorted(hit))}"

        if prev is None:
            # 第一次见这 camera 有 detect → 就是关键
            return "first_detect"

        prev_counts = prev.get("class_counts", {})
        prev_centers = prev.get("centers", [])

        # class 集合变化（出现 / 消失）
        if set(curr_counts.keys()) != set(prev_counts.keys()):
            return "class_set_changed"

        # 同 class 数量变化
        for cls, n in curr_counts.items():
            if prev_counts.get(cls, 0) != n:
                return f"count_changed:{cls}"

        # 同 class bbox 中心位移（取每 class 第一个 bbox 对比）
        jump = self._kf["pos_jump_pixels"]
        for cls, cx, cy in curr_centers:
            for pcls, px, py in prev_centers:
                if pcls != cls:
                    continue
                if abs(cx - px) > jump or abs(cy - py) > jump:
                    return f"pos_jump:{cls}"
                break

        return None

    def run(self) -> None:
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
            self.stop()


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)
    KeyframeFilterModule(str(config_path)).run()


if __name__ == "__main__":
    main()
