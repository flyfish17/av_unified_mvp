#!/usr/bin/env python3
"""
modules/video_processor/main.py
视频处理模块入口 - 独立进程
R4: 自带 MJPEG HTTP 服务（端口 5051）
"""
import logging
import signal
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote

import yaml

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.base_module import BaseModule
from modules.video_processor.processor import VideoProcessor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)

MJPEG_PORT = 5051


class MjpegHandler(BaseHTTPRequestHandler):
    """每路摄像头作为 multipart/x-mixed-replace 流输出"""
    processor_ref: "VideoProcessor | None" = None  # 由 VideoModule 注入
    protocol_version = "HTTP/1.1"  # Chrome 在 HTTP/1.0 下偶尔不渲染 multipart

    def log_message(self, fmt, *args):
        pass  # 静默 access log

    def do_GET(self):
        full = self.path.lstrip("/")
        path, _, query = full.partition("?")
        parts = path.split("/", 1)
        # 解析 mode 参数 (raw|annotated)
        mode = "raw"
        for kv in query.split("&"):
            if kv.startswith("mode="):
                v = kv[5:]
                if v in ("raw", "annotated"):
                    mode = v
        if len(parts) == 2 and parts[0] == "video_feed":
            self._stream_mjpeg(unquote(parts[1]), mode)
        elif len(parts) == 2 and parts[0] == "snapshot":
            self._serve_snapshot(unquote(parts[1]), mode)
        else:
            self.send_error(404)

    def _serve_snapshot(self, name: str, mode: str = "raw"):
        """返回当前帧的单张 JPEG。前端 50ms 级轮询。"""
        proc = self.processor_ref
        # http.server 默认用 latin-1 解码 path，self.path 里中文字符可能是 latin-1 形式
        # （每字节一字符）。重新 encode latin-1 → bytes → decode utf-8 修正。
        try:
            name = name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        all_status = proc.get_stream_status() if proc else {}
        status = all_status.get(name)
        # 只有 stopped / 未知 才硬 503；error/connecting 仍尝试发最后缓存帧（缓解 macOS
        # AVFoundation 偶发断流：cap.read 失败 → status="connecting" → 重连失败 →
        # status="error:..." 持续 3-30s。原先严格白名单 ("connecting","ok") 让前端
        # 进入此区间一律 503 黑屏，但 _latest_raw_jpeg 仍缓存着最后一帧，发出去更友好。
        if status is None or status == "stopped":
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        # 直接拿预编码 JPEG bytes（capture 线程已编好），无 imencode 开销
        jpg = proc.get_latest_jpeg(name, mode=mode) if proc else None
        if jpg is None:
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(jpg)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        try:
            self.wfile.write(jpg)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _stream_mjpeg(self, name: str, mode: str = "raw"):
        import cv2
        proc = self.processor_ref
        try:
            name = name.encode("latin-1").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
        # 摄像头未启用 → 立即 503，避免发陈旧缓存帧
        status = (proc.get_stream_status() if proc else {}).get(name)
        if status is None or status == "stopped":
            self.send_response(503)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"camera disabled or not running")
            return
        self.send_response(200)
        self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")  # HTTP/1.1 流模式：服务端持续 push 直到客户端断
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        last_hash = None
        idle_count = 0
        try:
            while True:
                cur_status = (proc.get_stream_status() if proc else {}).get(name)
                # 状态变成 stopped 或被 reload 清掉 → 主动断流（合法的 EOF 信号）
                if cur_status not in ("connecting", "ok"):
                    break
                jpg = proc.get_latest_jpeg(name, mode=mode) if proc else None
                if jpg is None:
                    time.sleep(0.05)
                    continue
                cur_hash = id(jpg)
                is_new = cur_hash != last_hash
                if is_new:
                    last_hash = cur_hash
                    idle_count = 0
                else:
                    # 旧版逻辑：60 帧（~4s）相同就 break stream → Chrome 收到 multipart EOF
                    # 有概率不触发 onerror，img 卡死，4 路并发时 6-connection limit + 重连竞争
                    # 失败累积 → "陆续黑掉必须刷新"。改为：stale 时仍每秒推一帧旧 jpg 作为心跳
                    # 保活 multipart 长连。Chrome 收到 boundary 即触发 onload，前端 watchdog 永
                    # 不超时。client 主动断开会抛 BrokenPipeError 自然清理；status 真 stopped 才
                    # break。
                    idle_count += 1
                    if idle_count % 15 != 0:
                        time.sleep(1 / 15)
                        continue
                self.wfile.write(b"--frame\r\n")
                self.wfile.write(b"Content-Type: image/jpeg\r\n\r\n")
                self.wfile.write(jpg)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
                time.sleep(1 / 15)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


class VideoModule(BaseModule):
    """视频处理模块"""

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)

        # 保留原始 sources（含真实 camera URL），供 reload_sources 使用
        self._sources = list(cfg.get("video", {}).get("sources", []))

        topics = cfg.get("mqtt", {}).get("topics", {})
        streams = [
            {
                "topic": topics.get("video_detect", "av/video/detect"),
                "channel": "video",
                "kind": "kv_table",
                "title": "视频检测事件",
            },
        ]
        # endpoints 用于 UI 展示：指向本模块自带的视频服务（5051）
        # url             = raw 流畅模式（总览页 / 客户视图）
        # annotated_url   = 带 YOLO bbox（视频检测模块页 / 工程师调试）
        # stream_url      = multipart 直连（浏览器地址栏调试）
        def _ep(src, suffix=""):
            qn = quote(src.get("name", ""))
            return f"http://127.0.0.1:{MJPEG_PORT}/snapshot/{qn}{suffix}"
        endpoints = [
            {
                "kind": "mjpeg",
                "name": src.get("name"),
                "url":          _ep(src, "?mode=raw"),
                "annotated_url": _ep(src, "?mode=annotated"),
                "stream_url":   f"http://127.0.0.1:{MJPEG_PORT}/video_feed/{quote(src.get('name', ''))}",
                "enabled": src.get("enabled", False),
                "src_url": src.get("url"),  # 原始 url，给前端"编辑"功能反推字段
            }
            for src in self._sources
        ]
        super().__init__(
            "video_processor", cfg,
            streams=streams,
            endpoints=endpoints,
        )

        self.processor = VideoProcessor(cfg.get("video", {}))
        self.processor.set_mqtt_publisher(self.publish)
        # 关键：加载 YOLO 模型 + 启动已启用的流（无则是 no-op）
        # R2 重构遗留 bug：之前从未调用，导致 _model=None，启用摄像头后推理崩
        self.processor.start()

        self.subscribe("av/system/config/video_processor")
        self.subscribe("av/video/cmd/+")
        self.subscribe("av/video/source/add")     # 回合 27 P1.3：动态添加摄像头
        self.subscribe("av/video/source/update")  # 回合 27 P1.3：修改摄像头
        self.subscribe("av/video/source/remove")  # 回合 27 P1.3：删除摄像头

        signal.signal(signal.SIGINT, lambda s, f: self.stop())
        signal.signal(signal.SIGTERM, lambda s, f: self.stop())

        # 启动 MJPEG 服务
        MjpegHandler.processor_ref = self.processor
        self._mjpeg_server = ThreadingHTTPServer(("0.0.0.0", MJPEG_PORT), MjpegHandler)
        threading.Thread(target=self._mjpeg_server.serve_forever, daemon=True).start()
        self.logger.info(f"MJPEG 服务已启动: http://0.0.0.0:{MJPEG_PORT}")

    def _discovery_payload(self, event: str) -> dict:
        # 公告前同步真实 capture 状态到每个 endpoint：让前端能区分"未启用 / 连接中 / 在线 / 离线"
        # status 取值：ok / connecting / error / stopped；未启用的源 status 始终为 disabled
        try:
            stat = self.processor.get_stream_status()
        except Exception:
            stat = {}
        for ep in self.endpoints:
            name = ep.get("name")
            if not ep.get("enabled"):
                ep["status"] = "disabled"
                continue
            raw = stat.get(name)
            if raw is None:
                ep["status"] = "stopped"
            elif raw == "ok":
                ep["status"] = "ok"
            elif raw == "connecting":
                ep["status"] = "connecting"
            elif isinstance(raw, str) and raw.startswith("error"):
                ep["status"] = "error"
            else:
                ep["status"] = raw
        return super()._discovery_payload(event)

    def _handle_message(self, topic: str, payload: dict) -> None:
        if "config" in topic:
            self._reload_config(payload)
        elif "av/video/cmd/" in topic:
            camera_name = unquote(topic.split("/")[-1])
            action = payload.get("action") or (payload.get("payload") or {}).get("action")
            if action in ("enable", "disable"):
                self._toggle_camera(camera_name, action)
        elif "av/video/source/add" in topic:
            # 兼容裸 payload 与 BaseModule 包装载荷
            src = payload.get("payload", payload) if isinstance(payload, dict) else {}
            if src.get("name") and src.get("url") is not None:
                self._add_source(src)
        elif "av/video/source/update" in topic:
            src = payload.get("payload", payload) if isinstance(payload, dict) else {}
            if src.get("name") and src.get("url") is not None:
                self._update_source(src)
        elif "av/video/source/remove" in topic:
            body = payload.get("payload", payload) if isinstance(payload, dict) else {}
            name = body.get("name")
            if name:
                self._remove_source(name)

    def _reload_config(self, payload: dict) -> None:
        sources = payload.get("payload", {}).get("sources", [])
        if sources:
            self.logger.info("收到配置更新，热重载摄像头...")
            self.processor.reload_sources(sources)

    def _persist_sources(self) -> None:
        """把内存 self._sources 写回 config/system_config.yaml 的 video.sources（重启不丢）"""
        try:
            cfg_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
            if not cfg_path.exists():
                self.logger.warning(f"config 不存在，跳过持久化：{cfg_path}")
                return
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
            cfg.setdefault("video", {})["sources"] = self._sources
            tmp_path = cfg_path.with_suffix(".yaml.tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(cfg, f, allow_unicode=True, sort_keys=False)
            tmp_path.replace(cfg_path)  # 原子替换防部分写
            self.logger.info(f"已持久化 {len(self._sources)} 路源到 system_config.yaml")
        except Exception as e:
            self.logger.warning(f"持久化 sources 失败：{e}")

    def _add_source(self, src: dict) -> None:
        """动态追加摄像头（回合 27 P1.3）：append + reload + 重新公告 endpoints"""
        name = src.get("name")
        if any(s.get("name") == name for s in self._sources):
            self.logger.warning(f"摄像头 {name} 已存在，跳过添加")
            return
        src.setdefault("enabled", True)
        self._sources.append(src)
        qn = quote(str(name))
        self.endpoints.append({
            "kind": "mjpeg",
            "name": name,
            "url":          f"http://127.0.0.1:{MJPEG_PORT}/snapshot/{qn}?mode=raw",
            "annotated_url": f"http://127.0.0.1:{MJPEG_PORT}/snapshot/{qn}?mode=annotated",
            "stream_url":   f"http://127.0.0.1:{MJPEG_PORT}/video_feed/{qn}",
            "enabled":      src.get("enabled", True),
            "src_url":      src.get("url"),
        })
        self.processor.reload_sources(self._sources)
        self.logger.info(f"新增摄像头: {name} → {src.get('url')}")
        self._persist_sources()
        self._publish_discovery("online")

    def _update_source(self, src: dict) -> None:
        """修改现有摄像头 url（回合 27 P1.3）：按 name 找，原地改 url + reload"""
        name = src.get("name")
        target = next((s for s in self._sources if s.get("name") == name), None)
        if target is None:
            self.logger.warning(f"修改失败：未找到摄像头 {name}")
            return
        target["url"] = src["url"]
        if "enabled" in src:
            target["enabled"] = src["enabled"]
        # 同步 endpoints 的 src_url
        for ep in self.endpoints:
            if ep.get("name") == name:
                ep["src_url"] = src["url"]
                if "enabled" in src:
                    ep["enabled"] = src["enabled"]
        self.processor.reload_sources(self._sources)
        self.logger.info(f"修改摄像头: {name} → {src['url']}")
        self._persist_sources()
        self._publish_discovery("online")

    def _remove_source(self, name: str) -> None:
        """删除摄像头（回合 27 P1.3）：从 sources/endpoints 移除 + reload + 公告"""
        before = len(self._sources)
        self._sources = [s for s in self._sources if s.get("name") != name]
        if len(self._sources) == before:
            self.logger.warning(f"删除失败：未找到摄像头 {name}")
            return
        self.endpoints = [ep for ep in self.endpoints if ep.get("name") != name]
        self.processor.reload_sources(self._sources)
        self.logger.info(f"删除摄像头: {name}")
        self._persist_sources()
        self._publish_discovery("online")

    def _toggle_camera(self, name: str, action: str) -> None:
        """开启或关闭摄像头，并重新公告 endpoints 状态"""
        enable = action == "enable"
        found = False
        for src in self._sources:
            if src.get("name") == name:
                src["enabled"] = enable
                found = True
        for ep in self.endpoints:
            if ep.get("name") == name:
                ep["enabled"] = enable
        if not found:
            self.logger.warning(f"未找到摄像头: {name}")
            return
        self.processor.reload_sources(self._sources)
        self.logger.info(f"摄像头 {name} 已{'启用' if enable else '停用'}")
        self._persist_sources()
        self._publish_discovery("online")  # 推送更新后的 endpoints 到 UI


def main():
    config_path = Path(__file__).parent.parent.parent / "config" / "system_config.yaml"
    if not config_path.exists():
        print(f"配置文件不存在: {config_path}")
        sys.exit(1)

    module = VideoModule(str(config_path))
    module.run()


if __name__ == "__main__":
    main()
