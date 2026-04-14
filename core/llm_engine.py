"""
llm_engine.py
大模型决策引擎 - 意图识别 + 指令生成
"""
import json
import logging
import re
import threading
from datetime import datetime

import requests

logger = logging.getLogger(__name__)

INTENT_PROMPT = (
    "你是一个意图分类器。判断用户的话是否在控制会议室设备"
    "（空调、灯光、窗帘、大屏、音量等）或查询设备状态。"
    "只回答 YES 或 NO，不要输出任何其他内容。"
)

COMMAND_PROMPT = (
    "你是一个智能会议室控制助手。根据用户指令，生成JSON格式的控制命令。\n"
    "严格只输出一行JSON，格式：{\"action\": \"动作\", \"device\": \"设备\", \"value\": \"参数\"}\n"
    "action可选：开/关/调节/调亮/调暗/切换\n"
    "device可选：灯光/空调/窗帘/大屏/音量\n"
    "不要输出任何解释文字，只输出JSON。\n"
    "用户指令："
)

SCENE_PROMPT = (
    "你是一个视听系统分析助手。根据摄像头检测到的场景信息，"
    "判断是否需要自动调整设备（如人员离开关灯、人员增多调大音量等）。"
    "如需调整，输出JSON控制命令；无需调整输出 null。\n"
    "场景信息："
)


class LLMEngine:
    # 暴露给 dashboard 直接调用
    COMMAND_PROMPT = COMMAND_PROMPT

    def __init__(self, cfg: dict):
        ollama = cfg.get("ollama", {})
        self.url         = ollama.get("url", "http://127.0.0.1:11434/api/generate")
        self.model_fast  = ollama.get("model_fast", "qwen3.5:9b")
        self.model_smart = ollama.get("model_smart", "qwen3.5:9b")
        self.timeout     = ollama.get("timeout", 30)
        self._lock       = threading.Lock()

    # ── 对外接口 ──────────────────────────────────────────────────────

    def classify_intent(self, text: str) -> bool:
        """判断语音是否是设备控制意图"""
        result = self._ask(self.model_fast, INTENT_PROMPT + "\n用户：" + text)
        return result.strip().upper().startswith("YES")

    def generate_command(self, text: str) -> dict | None:
        """从语音生成控制指令"""
        result = self._ask(self.model_fast, COMMAND_PROMPT + text)
        return self._parse_json(result)

    def analyze_scene(self, detections: list, camera_name: str) -> dict | None:
        """根据视觉检测结果分析场景，决定是否触发动作"""
        scene_desc = f"摄像头[{camera_name}]检测到: {json.dumps(detections, ensure_ascii=False)}"
        result = self._ask(self.model_smart, SCENE_PROMPT + scene_desc)
        if result.strip().lower() == "null":
            return None
        return self._parse_json(result)

    def is_available(self) -> bool:
        try:
            r = requests.get(
                self.url.replace("/api/generate", "/api/tags"),
                timeout=3
            )
            return r.status_code == 200
        except Exception:
            return False

    # ── 内部 ──────────────────────────────────────────────────────────

    def _ask(self, model: str, prompt: str, think: bool = False) -> str:
        with self._lock:
            try:
                resp = requests.post(
                    self.url,
                    json={"model": model, "prompt": prompt, "stream": False,
                          "think": think,
                          "options": {"temperature": 0.0, "num_predict": 200}},
                    timeout=self.timeout
                )
                data = resp.json()
                raw = data.get("response", "").strip()
                # 去除 <think>...</think> 标签（qwen3 思考链）
                return re.sub(r"<think>.*?</think>", "", raw, flags=re.S).strip()
            except Exception as e:
                logger.error(f"LLM请求失败: {e}")
                return ""

    @staticmethod
    def _parse_json(text: str) -> dict | None:
        """多策略JSON提取，兼容模型各种输出格式"""
        if not text:
            return None
        # 去掉 markdown 代码块
        text = re.sub(r"```(?:json)?", "", text).strip()
        try:
            start = text.find("{")
            end   = text.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(text[start:end])
        except Exception:
            pass
        # 尝试整行匹配
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    return json.loads(line)
                except Exception:
                    pass
        logger.warning(f"JSON解析失败，原始内容: {text[:100]}")
        return None
