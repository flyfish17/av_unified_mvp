"""
core/profile.py
性能档位（profile）：根据硬件能力选择 ASR/视频/解码线程数。
仿 woldmonitor 风格——启动时给用户硬件提示，让用户知道当前选择与可选项。
"""
from __future__ import annotations

import logging
import os
import platform

logger = logging.getLogger(__name__)


PROFILES = {
    "light": {
        "label": "轻档",
        "audio_mode": "local_offline",
        "audio_extra_ram_mb": 500,
        "audio_features": "仅 final（按句切段），含标点 ITN，无 partial",
        "video_model": "yolov8n.pt",
        "needs_docker": False,
        "good_for": "RK3588 / Jetson Nano / 4-8 GB 内存",
    },
    "medium": {
        "label": "中档（推荐）",
        "audio_mode": "websocket_2pass",
        "audio_extra_ram_mb": 1000,
        "audio_features": "partial + final + 标点 + 整句修正（无 ngram LM）",
        "video_model": "yolov8n.pt",
        "needs_docker": True,
        "good_for": "M1 / M2 / 12-16 GB Mac、低配 NUC",
    },
    "heavy": {
        "label": "重档",
        "audio_mode": "websocket_2pass",
        "audio_extra_ram_mb": 2200,
        "audio_features": "partial + final + 标点 + 整句修正 + ngram LM 重打分",
        "video_model": "yolov8s.pt",
        "needs_docker": True,
        "good_for": "M2 Pro / 32 GB+ / 高配 NUC",
    },
}


def total_ram_gb() -> float:
    """返回本机总内存 (GB)。失败返回 0."""
    try:
        if platform.system() == "Darwin":
            with os.popen("sysctl -n hw.memsize") as f:
                return int(f.read().strip()) / 1024**3
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemTotal"):
                    return int(line.split()[1]) / 1024**2
    except Exception:
        pass
    return 0.0


def recommend_profile(ram_gb: float) -> str:
    if ram_gb < 6:
        return "light"
    if ram_gb < 24:
        return "medium"
    return "heavy"


def announce(active: str) -> None:
    """启动时打印当前档位 + 硬件 + 推荐项。"""
    if active not in PROFILES:
        logger.warning(f"未知 performance_profile={active}，按 medium 处理")
        active = "medium"

    p = PROFILES[active]
    ram = total_ram_gb()
    rec = recommend_profile(ram)

    logger.info("─" * 60)
    logger.info(f"性能档位: {active} ({p['label']})")
    logger.info(f"  ASR     : {p['audio_mode']}  约 {p['audio_extra_ram_mb']} MB RAM")
    logger.info(f"  能力    : {p['audio_features']}")
    logger.info(f"  视频    : YOLO {p['video_model']}")
    logger.info(f"  依赖    : {'Docker (FunASR runtime)' if p['needs_docker'] else '纯 Python，无 Docker'}")
    logger.info(f"  适合于  : {p['good_for']}")
    logger.info(f"硬件    : {ram:.1f} GB RAM, {os.cpu_count()} CPU 核心")
    if rec != active:
        rp = PROFILES[rec]
        logger.info(f"提示    : 本机更适合「{rec}」档（{rp['label']}）。改 config/system_config.yaml 的 system.performance_profile 切换")
    logger.info("─" * 60)
