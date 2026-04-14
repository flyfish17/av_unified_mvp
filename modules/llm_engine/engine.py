#!/usr/bin/env python3
"""
modules/llm_engine/engine.py
LLM处理模块 - 独立进程版本
订阅av/llm/command，通过MQTT发布LLM响应
"""
import json
import logging
import re
import time
from typing import Optional

import requests

logger = logging.getLogger(__name__)


class LLMEngine:
    """
    LLM处理模块

    重构后支持MQTT模式：
    - 订阅 av/llm/command (接收音频转写文本)
    - 发布 av/llm/event (发送LLM响应)
    """

    def __init__(self, cfg: dict):
        self.llm_cfg = cfg.get("llm", {})
        ollama = self.llm_cfg.get("ollama", {})

        self.url = ollama.get("url", "http://127.0.0.1:11434/api/generate")
        self.model_fast = ollama.get("model_fast", "qwen3.5:9b")
        self.model_smart = ollama.get("model_smart", "qwen3.5:9b")
        self.timeout = ollama.get("timeout", 30)

        # 设备控制指令关键词
        self.control_keywords = [
            "打开", "关闭", "启动", "停止", "调高", "调低",
            "开", "关", "亮", "暗", "热", "冷", "空调", "灯光",
            "窗帘", "门", "窗", "电视", "音响", "电源",
        ]

    def set_mqtt_publisher(self, publisher_fn):
        """设置MQTT发布函数"""
        self._mqtt_publisher = publisher_fn
        logger.info("MQTT publisher 已设置")

    def _publish_event(self, event_type: str, original_text: str,
                       intent: dict = None, command: dict = None,
                       confidence: float = 0.0, correlation_id: str = None) -> None:
        """通过MQTT发布LLM响应事件"""
        if self._mqtt_publisher is None:
            logger.debug("MQTT publisher 未设置，跳过发布")
            return

        payload = {
            "topic_type": "event",
            "payload": {
                "event_type": event_type,
                "original_text": original_text,
                "intent": intent or {},
                "command": command,
                "confidence": confidence,
            },
            "metadata": {
                "correlation_id": correlation_id,
            },
        }

        self._mqtt_publisher("av/llm/event", payload)
        logger.debug(f"发布LLM事件: {event_type}")

    # ── 原有接口 ──────────────────────────────────────────────────────

    def is_available(self) -> bool:
        """检查Ollama是否在线"""
        try:
            r = requests.get(self.url.replace("/api/generate", "/api/tags"), timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def classify_intent(self, text: str) -> bool:
        """判断是否设备控制意图"""
        return any(kw in text for kw in self.control_keywords)

    def _extract_entities(self, text: str) -> dict:
        """简单实体提取"""
        entities = {}
        locations = ["客厅", "卧室", "厨房", "卫生间", "二楼", "一楼", "机房", "会议室"]
        for loc in locations:
            if loc in text:
                entities["location"] = loc
                break
        return entities

    def generate_command(self, text: str) -> Optional[dict]:
        """从语音生成控制指令"""
        prompt = self._build_command_prompt(text)
        raw = self._ask(self.model_fast, prompt)
        if not raw:
            return None
        parsed = self._parse_json(raw)
        if parsed:
            return parsed.get("commands") or parsed.get("command") or parsed
        return None

    def analyze_scene(self, detections: list, camera_name: str) -> Optional[dict]:
        """根据视频检测结果分析场景"""
        if not detections:
            return None
        prompt = f"摄像头 {camera_name} 检测到: {detections}，请分析是否需要触发告警或自动化动作。"
        raw = self._ask(self.model_smart, prompt)
        if raw:
            return self._parse_json(raw)
        return None

    # ── MQTT消息处理 ──────────────────────────────────────────────────

    def process_command(self, payload: dict) -> None:
        """
        处理MQTT收到的指令

        payload格式:
        {
            "payload": {
                "text": "打开灯光",
                "event_type": "transcription"
            },
            "header": {
                "msg_id": "xxx"
            }
        }
        """
        try:
            audio_event = payload.get("payload", {})
            text = audio_event.get("text", "")
            correlation_id = payload.get("header", {}).get("msg_id")

            if not text:
                return

            logger.info(f"收到文本: {text}")

            # 意图识别
            is_command = self.classify_intent(text)

            if is_command:
                # 生成指令
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
            else:
                self._publish_event(
                    event_type="intent_classified",
                    original_text=text,
                    intent={
                        "is_command": False,
                    },
                    confidence=0.9,
                    correlation_id=correlation_id,
                )

        except Exception as e:
            logger.error(f"处理异常: {e}")

    # ── 内部方法 ──────────────────────────────────────────────────────

    def _build_command_prompt(self, text: str) -> str:
        return f"""你是底层音视频中控指令翻译器。禁止任何思考、推理或废话。无需解释原因。直接输出JSON！

【可用指令字典】：
[二楼餐桌] 空调开: 2FDiningTable_AirConditioner_On, 空调关: 2FDiningTable_AirConditioner_Off, 温度+: 2FDiningTable_AirConditioner_TempUp, 温度-: 2FDiningTable_AirConditioner_TempDown, 灯带1开/关: DiningTable_Light1_On/Off
[机房] 空调开: EngineRoom_AirConditioner_On, 空调关: EngineRoom_AirConditioner_Off
[会议室1] 窗帘开: MeetingRoom1_Curtain_Open

用户输入：{text}
系统输出："""

    def _ask(self, model: str, prompt: str, think: bool = False) -> str:
        """调用Ollama API"""
        try:
            req = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "think": think,
            }
            r = requests.post(self.url, json=req, timeout=self.timeout)
            r.raise_for_status()
            raw = r.text

            # 去掉思考链标签（qwen3 思考链）
            try:
                return re.sub(r"<think>.*?
</think>", "", raw, flags=re.S).strip()
            except Exception:
                return raw

        except Exception as e:
            logger.error(f"LLM请求失败: {e}")
            return ""

    @staticmethod
    def _parse_json(text: str) -> Optional[dict]:
        """多策略JSON提取"""
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
        logger.warning(f"JSON解析失败，原始内容: {text[:100]}")
        return None
