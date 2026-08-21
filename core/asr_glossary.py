"""
core/asr_glossary.py — ASR 人名/术语修复（回流自 av_understanding_mac 8a3f6f6，2026-06-18 任务①②）

两件事，都是纯函数 + 两个 yaml 文件，audio_processor（本机麦）与 net_audio_capture（会议主机 8 路）共用：
  ① config/glossary.yaml  → FunASR hotwords（热词，FST 加权，不改模型）。硬伤：人名归零（韩苏宁→韩淑宁）。
  ② config/asr_postprocess_rules.yaml → final 文本正则后处理，还原被拆字母的英文缩写（HDMI/USB/iPad…）。
文件不存在 → 原行为不变（向后兼容）；文件格式错 → 让 yaml 报错，不吞。
hotwords 协议：最终是 json.dumps({词: 权重})，不是空格串（funasr_wss_client.py:99）。
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
GLOSSARY_DEFAULT_WEIGHT = 20
_MULTISPACE_RE = re.compile(r"[ \t]{2,}")


def glossary_to_hotwords(glossary: dict, default_weight: int = GLOSSARY_DEFAULT_WEIGHT) -> dict:
    """glossary.yaml 的 people/products/terms 各段拍扁成 {词: 权重}。保持顺序，空词跳过，重复后者覆盖。"""
    words: dict = {}
    for section in ("people", "products", "terms"):
        for w in (glossary.get(section) or []):
            w = str(w).strip()
            if w:
                words[w] = default_weight
    return words


def merge_hotwords(existing: str, glossary_words: dict) -> str:
    """合并 glossary 与 config 已有 hotwords（config 优先级最高），输出 json.dumps 字符串；空 → ""。"""
    merged = dict(glossary_words)
    existing = (existing or "").strip()
    if existing:
        try:
            cfg = json.loads(existing)
        except (ValueError, TypeError):
            cfg = None
        if isinstance(cfg, dict):
            for k, v in cfg.items():
                merged[str(k)] = int(v)
        else:  # 退路：空白分隔纯词串
            for w in existing.split():
                merged[w] = GLOSSARY_DEFAULT_WEIGHT
    return json.dumps(merged, ensure_ascii=False) if merged else ""


def load_hotwords(existing: str, path: Path | None = None) -> str:
    """读 config/glossary.yaml 合并进 existing；文件不存在返回 existing 原样。"""
    path = path or (CONFIG_DIR / "glossary.yaml")
    if not path.exists():
        return existing
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    words = glossary_to_hotwords(data)
    logger.info(f"loaded {len(words)} hotwords from {path.name}")
    return merge_hotwords(existing, words)


def compile_postproc_rules(rules: list) -> list:
    """abbrev_restore 列表 → [(compiled_pattern, replace)]，顺序保持（先长后短）。"""
    return [(re.compile(r["pattern"]), r["replace"]) for r in (rules or [])]


def load_postproc_rules(path: Path | None = None) -> list:
    """读 config/asr_postprocess_rules.yaml 并编译；文件不存在返回 []。"""
    path = path or (CONFIG_DIR / "asr_postprocess_rules.yaml")
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    compiled = compile_postproc_rules(data.get("abbrev_restore"))
    logger.info(f"loaded {len(compiled)} ASR postprocess rules from {path.name}")
    return compiled


def apply_postprocess_rules(text: str, compiled_rules: list) -> str:
    """只对 final 文本用（partial 高频抖动会闪屏）。"""
    for pat, repl in compiled_rules:
        text = pat.sub(repl, text)
    return _MULTISPACE_RE.sub(" ", text).strip()
