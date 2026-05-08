#!/usr/bin/env python3
"""
modules/llm_engine/engine.py
LLM 决策引擎 - 意图识别 + 项目指令字典翻译

支持两种调用方式：
  - 直接调用: classify_intent / generate_command / analyze_scene（主程模式）
  - MQTT:    set_mqtt_publisher() + process_command()（独立模块订阅 av/llm/command）
"""
import json
import logging
import re
import threading
from pathlib import Path
from typing import Callable, Optional

import requests

logger = logging.getLogger(__name__)


# 兜底 prompt（catalog 加载失败时用）
COMMAND_PROMPT_FALLBACK = (
    "你是底层音视频中控指令翻译器。禁止任何思考、推理或废话。无需解释原因。"
    "直接输出 JSON：{\"cmd\": \"指令字符串\"}\n\n"
    "【可用指令字典】：\n"
    "[二楼餐桌] 空调开: 2FDiningTable_AirConditioner_On, 空调关: 2FDiningTable_AirConditioner_Off, "
    "温度+: 2FDiningTable_AirConditioner_TempUp, 温度-: 2FDiningTable_AirConditioner_TempDown\n\n"
    "用户输入："
)


def _build_command_prompt_from_catalog() -> str:
    """从 config/device_catalog.json 自动生成完整 76 条指令的 prompt。

    回合 28 P0 L2：catalog 即真相源，新加指令零代码改动 LLM prompt 同步。
    包含 also_in 共享指令（如吧台窗帘也展示在二楼餐桌）。
    """
    try:
        catalog_path = Path(__file__).parent.parent.parent / "config" / "device_catalog.json"
        if not catalog_path.exists():
            logger.warning("device_catalog.json 不存在，prompt 用 fallback 版（仅二楼餐桌空调）")
            return COMMAND_PROMPT_FALLBACK
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        loc_to_label = {l["id"]: l["label"] for l in catalog["locations"]}
        device_types = catalog.get("device_types", {})

        # 按 location 分组（含 also_in 共享）
        groups: dict[str, list[tuple[str, str]]] = {}
        for c in catalog["commands"]:
            cmd_id = c["id"]
            dev = c.get("device", "")
            action = c.get("action", "")
            dev_meta = device_types.get(dev, {})
            dev_lbl = dev_meta.get("label", dev)
            act_lbl = (dev_meta.get("actions_label") or {}).get(action, action)
            short = f"{dev_lbl}{act_lbl}"
            for loc_id in [c["location"]] + (c.get("also_in") or []):
                groups.setdefault(loc_id, []).append((cmd_id, short))

        # 拼成"[地点] 设备动作: 指令名, ..."的可读列表
        lines = []
        for loc_id, items in groups.items():
            label = loc_to_label.get(loc_id, loc_id)
            line = f"[{label}] " + ", ".join(f"{s}: {cid}" for cid, s in items)
            lines.append(line)
        dict_block = "\n".join(lines)

        prompt = (
            "你是底层音视频中控指令翻译器。"
            "禁止任何思考、推理或废话。无需解释原因。"
            "直接输出 JSON：{\"cmd\": \"指令字符串\"}\n\n"
            "【匹配规则】\n"
            "1. 精确说设备名（灯带1/轨道灯/筒灯/虚光/发光字灯/空调/窗帘）按字面匹配\n"
            "2. 用户笼统说\"灯\"或\"灯光\"未指定细分时，按以下优先级在该地点选一个：\n"
            "   灯带(Light) > 灯带1(Light1) > 轨道灯(TrackLight) > 筒灯(Downlight)\n"
            "3. \"温度高/调高\"= TempUp，\"温度低/调低\"= TempDown\n"
            "4. 忽略输入中的标点、语气词、重复\n"
            "5. 仅当该地点 + 设备真无任何匹配项才输出 {\"cmd\": null}\n\n"
            "【可用指令字典】：\n"
            + dict_block
            + "\n\n用户输入："
        )
        logger.info(f"prompt 已从 catalog 生成：{len(catalog['commands'])} 条指令，{len(groups)} 个地点")
        return prompt
    except Exception as e:
        logger.error(f"加载 catalog 生成 prompt 失败，回退到 fallback：{e}")
        return COMMAND_PROMPT_FALLBACK


# 模块级常量（保留兼容旧 import 方）：先用 fallback，LLMEngine 实例化时会覆盖 self.command_prompt
COMMAND_PROMPT = COMMAND_PROMPT_FALLBACK

SCENE_PROMPT = (
    "你是一个视听系统分析助手。根据摄像头检测到的场景信息，"
    "判断是否需要自动调整设备（如人员离开关灯、人员增多调大音量等）。"
    "如需调整，输出JSON控制命令；无需调整输出 null。\n"
    "场景信息："
)

# 端侧小模型 LLM 意图分类不稳，先用关键词过滤
# 基础动词（不依赖 catalog）：打开/关闭/启停/调高低 + 单字开关亮暗冷热
_BASE_KEYWORDS = {
    "打开", "关闭", "启动", "停止", "切换", "调高", "调低",
    "开", "关", "亮", "暗", "热", "冷", "拉", "合",
}


def _build_keywords_from_catalog() -> set:
    """从 catalog 的 device_types.label + actions_label + locations.label 自动 derive 关键词。

    避免漏：CSV 里有的词（"筒灯"、"虚光"、"发光字"、"轨道灯"）自动进入触发集，
    用户说"打开筒灯"才能进 LLM 翻译，否则会被 classify_intent 拦下。
    """
    keywords = set(_BASE_KEYWORDS)
    try:
        catalog_path = Path(__file__).parent.parent.parent / "config" / "device_catalog.json"
        if catalog_path.exists():
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            for dt in (catalog.get("device_types") or {}).values():
                lbl = (dt.get("label") or "").strip()
                if lbl:
                    keywords.add(lbl)
                for act_lbl in (dt.get("actions_label") or {}).values():
                    if act_lbl and len(act_lbl) >= 1:
                        keywords.add(act_lbl)
            for loc in catalog.get("locations") or []:
                lbl = (loc.get("label") or "").strip()
                if lbl and len(lbl) >= 2 and not lbl.startswith("_"):
                    keywords.add(lbl)
    except Exception as e:
        logger.warning(f"keywords 从 catalog derive 失败，用基础集：{e}")
    return keywords


# 模块级（保留兼容）：实例 init 时会重新 build 一份
CONTROL_KEYWORDS = list(_build_keywords_from_catalog())


class LLMEngine:
    # 暴露给 dashboard 直接拼接：llm.COMMAND_PROMPT + text
    COMMAND_PROMPT = COMMAND_PROMPT

    def __init__(self, cfg: dict):
        ollama = cfg.get("ollama", {})
        self.url = ollama.get("url", "http://127.0.0.1:11434/api/generate")
        self.model_fast = ollama.get("model_fast", "qwen3.5:9b")
        self.model_smart = ollama.get("model_smart", "qwen3.5:9b")
        self.timeout = ollama.get("timeout", 30)
        # 不加 threading.Lock：ollama serve 自带请求队列，外部锁多余且在某次连续语音输入时
        # 触发死锁让整个 llm_engine 卡 4+ 分钟（回合 28 实测）。多个 _ask 并发由 ollama 自己排。
        self._mqtt_publisher: Optional[Callable[[str, dict], None]] = None
        # 实例化时从 catalog 重建 prompt + 关键词集
        self.command_prompt = _build_command_prompt_from_catalog()
        self._keywords = _build_keywords_from_catalog()
        logger.info(f"control 关键词集（catalog derive）：{len(self._keywords)} 个")
        # ollama 必走本机直连：trust_env=False 完全忽略 http_proxy/https_proxy 环境变量，
        # 防 Clash 等系统代理把 127.0.0.1 流量也劫走（NO_PROXY 在某些 requests 版本不可靠）。
        self._http = requests.Session()
        self._http.trust_env = False

    # ── MQTT 集成 ─────────────────────────────────────────────────────

    def set_mqtt_publisher(self, publisher_fn: Callable[[str, dict], None]):
        """注入 MQTT publish 函数。签名 publisher(topic: str, payload: dict)"""
        self._mqtt_publisher = publisher_fn
        logger.info("MQTT publisher 已设置")

    def _publish_event(self, *, event_type: str, original_text: str,
                       intent: dict = None, command: dict = None,
                       confidence: float = 0.0,
                       correlation_id: str = None) -> None:
        """按 §4 协议发布到 av/llm/event"""
        if self._mqtt_publisher is None:
            return
        self._mqtt_publisher("av/llm/event", {
            "topic_type": "event",
            "payload": {
                "event_type": event_type,
                "original_text": original_text,
                "intent": intent or {},
                "command": command,
                "confidence": confidence,
            },
            "metadata": {"correlation_id": correlation_id},
        })

    def process_command(self, payload: dict) -> None:
        """
        订阅 av/audio/command 或 av/llm/command 后调用：
        解析 → 意图 → 翻译 → 发布 av/llm/event（+命中时同时发 av/control）
        """
        try:
            audio_event = payload.get("payload", {}) or payload
            text = audio_event.get("text", "")
            correlation_id = (payload.get("header") or {}).get("msg_id")

            if not text:
                return

            logger.info(f"收到文本: {text}")
            is_command = self.classify_intent(text)

            if is_command:
                cmd = self.generate_command(text)
                self._publish_event(
                    event_type="command_generated",
                    original_text=text,
                    intent={
                        "is_command": True,
                        "intent_type": "device_control",
                        "entities": self._extract_entities(text),
                    },
                    command=cmd,
                    confidence=0.88,
                    correlation_id=correlation_id,
                )
                # 直接发 av/control，无需 Node-RED 中转（Node-RED 可并行订阅，不冲突）
                if cmd and self._mqtt_publisher:
                    self._mqtt_publisher("av/control", {
                        "topic_type": "event",
                        "payload": {**cmd, "original_text": text},
                        "metadata": {"correlation_id": correlation_id},
                    })
            else:
                self._publish_event(
                    event_type="intent_classified",
                    original_text=text,
                    intent={"is_command": False},
                    confidence=0.9,
                    correlation_id=correlation_id,
                )
        except Exception as e:
            logger.error(f"process_command 异常: {e}")

    # ── 对外接口 ──────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """检查 Ollama 是否在线"""
        try:
            r = self._http.get(
                self.url.replace("/api/generate", "/api/tags"),
                timeout=3,
            )
            return r.status_code == 200
        except Exception:
            return False

    def classify_intent(self, text: str) -> bool:
        """是否设备控制意图（端侧关键词判断，关键词从 catalog derive）"""
        return any(kw in text for kw in self._keywords)

    # FunASR ITN 自动加的中文标点对严格匹配 prompt 是噪声，喂给 LLM 前先去掉
    _PUNCT_RE = re.compile(r"[，。！？、；：「」『』“”‘’（）()\s　]+")

    def generate_command(self, text: str) -> Optional[dict]:
        """从语音文本生成控制指令，规范化返回 {cmd: "ASCII_STRING"} 或 None。

        兼容 LLM 多种输出形式：
          - {"cmd": "X"}      （目标格式）
          - {"command": "X"}  （旧 prompt 格式）
          - {"commands": [...] | "X"}
          - "X"  （裸字符串）
        """
        # 去标点 + 空白：提升 LLM 对 FunASR ITN 加标点的鲁棒
        text_clean = self._PUNCT_RE.sub("", text or "")
        if not text_clean:
            return None
        prompt = self.command_prompt + text_clean + "\n系统输出："
        raw = self._ask(self.model_fast, prompt)
        parsed = self._parse_json(raw)
        cmd_str: Optional[str] = None
        if isinstance(parsed, dict):
            for k in ("cmd", "command", "commands"):
                v = parsed.get(k)
                if v:
                    cmd_str = v if isinstance(v, str) else (v[0] if isinstance(v, list) and v else None)
                    break
        elif isinstance(parsed, str):
            cmd_str = parsed
        if not cmd_str or not isinstance(cmd_str, str):
            return None
        cmd_str = cmd_str.strip()
        if not cmd_str or cmd_str.lower() == "null":
            return None
        return {"cmd": cmd_str}

    def analyze_scene(self, detections: list, camera_name: str) -> Optional[dict]:
        """根据视觉检测结果分析场景，决定是否触发动作"""
        if not detections:
            return None
        scene_desc = f"摄像头[{camera_name}]检测到: {json.dumps(detections, ensure_ascii=False)}"
        result = self._ask(self.model_smart, SCENE_PROMPT + scene_desc)
        if result.strip().lower() == "null":
            return None
        return self._parse_json(result)

    def _extract_entities(self, text: str) -> dict:
        """简单实体提取（位置）"""
        entities = {}
        locations = ["客厅", "卧室", "厨房", "卫生间", "二楼", "一楼", "机房", "会议室"]
        for loc in locations:
            if loc in text:
                entities["location"] = loc
                break
        return entities

    # ── 内部 ──────────────────────────────────────────────────────────

    def _ask(self, model: str, prompt: str, think: bool = False) -> str:
        """调用 Ollama API。返回去除 <think> 标签后的 response 字段。

        显式 proxies={...:None}：避免系统代理（Clash 等）把 127.0.0.1 流量也劫走，
        那种情况 requests 会拿到代理 404，不会到本机 ollama。
        """
        try:
            logger.debug(f"[ask] url={self.url} model={model} trust_env={self._http.trust_env}")
            resp = self._http.post(
                self.url,
                json={
                    "model": model,
                    "prompt": prompt,
                    "stream": False,
                    "think": think,
                    "options": {"temperature": 0.0, "num_predict": 200},
                },
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            raw = data.get("response", "").strip()
            # qwen3 思考链
            return re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
        except Exception as e:
            logger.error(f"LLM 请求失败: {e}")
            return ""

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """多策略 JSON 提取，兼容模型各种输出格式"""
        if not text:
            return None
        text = re.sub(r"```(?:json)?", "", text).strip()
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            pass
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except Exception:
                    pass
        logger.warning(f"JSON 解析失败，原始内容: {text[:100]}")
        return None
