#!/usr/bin/env python3
"""
modules/llm_engine/engine.py
LLM 决策引擎 - 意图识别 + 项目指令字典翻译

支持两种调用方式：
  - 直接调用: classify_intent / generate_command / analyze_scene（主程模式）
  - MQTT:    set_mqtt_publisher() + process_command()（独立模块订阅 av/llm/command）

后端：默认 ollama HTTP；3588 等 NPU 设备可设 env `AV_LLM_BACKEND=rknn` 或
config `llm.backend: rknn` 走 RKLLM daemon（仅 generate_command 走 NPU；
analyze_scene 仍走 ollama smart 模型）。
"""
import json
import logging
import os
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


def _build_command_prompt_from_catalog(default_location_id: str = "") -> str:
    """从 config/device_catalog.json 自动生成完整 76 条指令的 prompt。

    回合 28 P0 L2：catalog 即真相源，新加指令零代码改动 LLM prompt 同步。
    包含 also_in 共享指令（如吧台窗帘也展示在二楼餐桌）。

    default_location_id：本机所处默认位置 ID（来自 system_config.yaml 的 system.default_location）。
    用户语音未明示地点时（如"打开窗帘"），LLM 优先选该位置下的指令，避免歧义命中错位置。
    """
    try:
        catalog_path = Path(__file__).parent.parent.parent / "config" / "device_catalog.json"
        if not catalog_path.exists():
            logger.warning("device_catalog.json 不存在，prompt 用 fallback 版（仅二楼餐桌空调）")
            return COMMAND_PROMPT_FALLBACK
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        loc_to_label = {l["id"]: l["label"] for l in catalog["locations"]}
        device_types = catalog.get("device_types", {})
        default_location_label = loc_to_label.get(default_location_id, "")

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

        # 拼成"[地点] CMD_ID(设备动作), ..."的可读列表
        # cmd_id 放前面避免 2b 小模型把人类可读 label 误认作 cmd 输出（实测 "窗帘合" hallucinate 被白名单拒）
        lines = []
        for loc_id, items in groups.items():
            label = loc_to_label.get(loc_id, loc_id)
            line = f"[{label}] " + ", ".join(f"{cid}({s})" for cid, s in items)
            lines.append(line)
        dict_block = "\n".join(lines)

        default_loc_rule = (
            f"7. 用户未明示地点时（如\"打开窗帘\"\"开灯\"），默认本机所在的 [{default_location_label}]，"
            f"该位置存在匹配项时直接选它，不要随机命中其他地点\n"
            if default_location_label
            else ""
        )
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
            "5. 仅当该地点 + 设备真无任何匹配项才输出 {\"cmd\": null}\n"
            "6. cmd 字段的值**必须是下方字典里每条括号前的大写英文ID**（如 RDDepartment_Curtain_Open）；"
            "**禁止输出括号内的中文名**（如 \"窗帘开\"），中文名仅供你理解\n"
            + default_loc_rule
            + "\n【输出示例】\n"
            "用户：\"打开窗帘\"  → {\"cmd\": \"RDDepartment_Curtain_Open\"}\n"
            "用户：\"关空调\"   → {\"cmd\": \"RDDepartment_AirConditioner_Off\"}\n"
            "用户：\"播放音乐\" → {\"cmd\": null}\n"
            "\n【可用指令字典（格式：CMD_ID(中文)）】：\n"
            + dict_block
            + "\n\n用户输入："
        )
        loc_info = f"，默认地点=[{default_location_label}]" if default_location_label else ""
        logger.info(f"prompt 已从 catalog 生成：{len(catalog['commands'])} 条指令，{len(groups)} 个地点{loc_info}")
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


def _build_cmd_whitelist_from_catalog() -> set:
    """所有合法 cmd id，用于反 hallucinate 后置过滤（小模型会编造类似但不存在的 id）。"""
    try:
        catalog_path = Path(__file__).parent.parent.parent / "config" / "device_catalog.json"
        if catalog_path.exists():
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            return {c["id"] for c in catalog.get("commands", []) if c.get("id")}
    except Exception as e:
        logger.warning(f"cmd 白名单加载失败：{e}")
    return set()


def _build_location_lookup_from_catalog() -> dict:
    """{location_id: location_label}，用于地点 anti-hallucination 后置过滤。

    NPU 1.5B 实测会"偷换地点"：用户说"机房发光字灯"模型输出 `Corridor_LuminousWordLight_Off`
    （设备对，地点错），cmd_id 在白名单内不被拦 → 错命令真落到 av/control。
    用此映射做后置校验：cmd 前缀 location 的 label 必须出现在原始 text 中
    （或等于本机 default_location），否则拒绝。
    """
    try:
        catalog_path = Path(__file__).parent.parent.parent / "config" / "device_catalog.json"
        if catalog_path.exists():
            catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
            return {l["id"]: l["label"] for l in catalog.get("locations", []) if l.get("id")}
    except Exception as e:
        logger.warning(f"location lookup 加载失败：{e}")
    return {}


def _build_fastpath_index_from_catalog() -> list:
    """漏斗第 1 层 fast-path 索引：[(cmd_id, location_label, device_label, action_labels[])]

    每条 cmd 展平为元组，generate_command 阶段用 O(N) 扫描判断"原文是否同时包含三件套
    label"。N=76 / 早期，可接受；后续 catalog 长起来再换 Trie 或 token-set index。

    action_labels 用列表是因为一个 action（如 On）多别名（"打开"/"开"/"启动"），
    catalog 当前未直接给同义词表，所以 action_labels = [actions_label[action]] + 同 action
    族的小辅助词（"打开"="开"等），见函数内 _ACTION_ALIASES。

    跳过 also_in（共享指令）；only 走 primary location，否则一条 cmd 多个 (loc, ...)
    会导致 fast-path 在原文同时含 2 地点时歧义命中。
    """
    # action 同义词（小、保守、确定不歧义）。避免泛同义词污染。
    _ACTION_ALIASES = {
        "开": ("开", "打开", "启动"),
        "关": ("关", "关闭", "停"),
        "合": ("合", "关闭", "拉合", "拉上"),
        "停": ("停", "停止"),
        "温度+": ("调高", "升高", "升温"),
        "温度-": ("调低", "降低", "降温"),
        "开始": ("开始", "启动"),
        "结束": ("结束", "停止", "关掉"),
    }
    index: list = []
    try:
        catalog_path = Path(__file__).parent.parent.parent / "config" / "device_catalog.json"
        if not catalog_path.exists():
            return index
        catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
        loc_to_label = {l["id"]: l["label"] for l in catalog.get("locations", [])}
        device_types = catalog.get("device_types", {})
        for c in catalog.get("commands", []):
            cid = c.get("id")
            if not cid:
                continue
            loc_id = c.get("location", "")
            loc_label = loc_to_label.get(loc_id, "")
            if not loc_label or loc_label.startswith("_"):
                continue  # _global 等不参与 fast-path
            dev = c.get("device", "")
            dev_meta = device_types.get(dev, {})
            dev_label = dev_meta.get("label", "")
            if not dev_label:
                continue
            action = c.get("action", "")
            action_label = (dev_meta.get("actions_label") or {}).get(action, action)
            if not action_label:
                continue
            # 去 label 内空白：catalog 偶有 "灯带 1" 这种含空格 label，用户文本不会带空格。
            # text 在 generate_command 已用 _PUNCT_RE 去标点空白，所以这里 label 也跟着去。
            loc_label_norm = loc_label.replace(" ", "")
            dev_label_norm = dev_label.replace(" ", "")
            aliases = tuple(a.replace(" ", "") for a in _ACTION_ALIASES.get(action_label, (action_label,)))
            index.append((cid, loc_label_norm, dev_label_norm, aliases))
    except Exception as e:
        logger.warning(f"fast-path 索引加载失败：{e}")
    return index


class LLMEngine:
    # 暴露给 dashboard 直接拼接：llm.COMMAND_PROMPT + text
    COMMAND_PROMPT = COMMAND_PROMPT

    def __init__(self, cfg: dict, default_location: str = ""):
        ollama = cfg.get("ollama", {})
        self.url = ollama.get("url", "http://127.0.0.1:11434/api/generate")
        self.model_fast = ollama.get("model_fast", "qwen3.5:4b")
        self.model_smart = ollama.get("model_smart", "qwen3.5:4b")
        self.timeout = ollama.get("timeout", 30)
        # 阶段 3 第 3 层（深思）escalate 协议字段：5/14 双路 MQTT POC
        # escalate_to_jetson: 当 fast-path miss + LLM/filter 都没拿到合法 cmd 时，
        #   把意图升级到 Jetson 深思层。默认关，向后兼容（3588 现有 5/13 行为不变）。
        # escalate_receiver: Jetson 端开关，订阅 av/llm/escalate 并跑深思。
        # host_label: 写到 escalate / av/control payload 区分来源（3588 / jetson）。
        self.escalate_to_jetson = bool(cfg.get("escalate_to_jetson", False))
        self.escalate_receiver = bool(cfg.get("escalate_receiver", False))
        self.host_label = cfg.get("host_label", "unknown")
        self._last_miss_reason: Optional[str] = None
        self._last_cmd_attempt: Optional[str] = None
        # 不加 threading.Lock：ollama serve 自带请求队列，外部锁多余且在某次连续语音输入时
        # 触发死锁让整个 llm_engine 卡 4+ 分钟（回合 28 实测）。多个 _ask 并发由 ollama 自己排。
        self._mqtt_publisher: Optional[Callable[[str, dict], None]] = None
        # 实例化时从 catalog 重建 prompt + 关键词集，default_location 注入 prompt 解歧义
        self.command_prompt = _build_command_prompt_from_catalog(default_location)
        self._keywords = _build_keywords_from_catalog()
        self._cmd_whitelist = _build_cmd_whitelist_from_catalog()
        self._location_lookup = _build_location_lookup_from_catalog()
        self._fastpath_index = _build_fastpath_index_from_catalog()
        self._default_location_id = default_location
        logger.info(f"control 关键词集（catalog derive）：{len(self._keywords)} 个")
        logger.info(f"cmd 白名单（catalog derive）：{len(self._cmd_whitelist)} 个")
        logger.info(f"location 集（地点反幻觉过滤）：{len(self._location_lookup)} 个，default={default_location or '<未设>'}")
        logger.info(f"fast-path 索引（漏斗第 1 层）：{len(self._fastpath_index)} 条")
        # ollama 必走本机直连：trust_env=False 完全忽略 http_proxy/https_proxy 环境变量，
        # 防 Clash 等系统代理把 127.0.0.1 流量也劫走（NO_PROXY 在某些 requests 版本不可靠）。
        self._http = requests.Session()
        self._http.trust_env = False
        # 后端选择：env 优先 cfg 其次；rknn 启动失败回退 ollama 不阻塞。
        backend = (os.environ.get("AV_LLM_BACKEND") or cfg.get("backend") or "ollama").lower()
        self._rknn = None
        self.backend = "ollama"
        if backend == "rknn":
            try:
                from modules.llm_engine.rknn_backend import RKLLMBackend
                rknn_cfg = cfg.get("rknn", {})
                self._rknn = RKLLMBackend(
                    daemon_dir=rknn_cfg.get("daemon_dir"),
                    model_path=rknn_cfg.get("model_path"),
                    lib_path=rknn_cfg.get("lib_path"),
                    max_context_len=rknn_cfg.get("max_context_len", 2048),
                    max_new_tokens=rknn_cfg.get("max_new_tokens", 200),
                )
                ack = self._rknn.start()
                self.backend = "rknn"
                logger.info(f"LLM 后端: rknn (NPU)，daemon ack={ack}")
            except Exception as e:
                logger.error(f"RKLLM 后端启动失败，回退 ollama：{e}")
                self._rknn = None
                self.backend = "ollama"
        if self.backend == "ollama":
            logger.info(f"LLM 后端: ollama @ {self.url}，fast={self.model_fast} smart={self.model_smart}")

    def close(self):
        """模块退出时清理 NPU daemon。ollama 无 state 无需 close。"""
        if self._rknn is not None:
            try:
                self._rknn.stop()
            except Exception as e:
                logger.warning(f"关闭 RKLLM daemon 异常：{e}")
            self._rknn = None

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
                        "payload": {**cmd, "original_text": text, "source_host": self.host_label},
                        "metadata": {"correlation_id": correlation_id},
                    })
                elif (cmd is None
                        and self.escalate_to_jetson
                        and self._mqtt_publisher
                        and self._last_miss_reason in (
                            "llm_returned_null",
                            "filter_rejected_whitelist",
                            "filter_rejected_location",
                        )):
                    # 阶段 3 第 3 层 escalate：本层失败 → 升级到深思层
                    self._mqtt_publisher("av/llm/escalate", {
                        "text": text,
                        "escalate_reason": self._last_miss_reason,
                        "original_cmd_attempt": self._last_cmd_attempt,
                        "correlation_id": correlation_id,
                        "source_host": self.host_label,
                    })
                    logger.info(
                        f"⤴ escalate → Jetson：reason={self._last_miss_reason} text={text!r}"
                    )
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

    def handle_escalate(self, payload: dict) -> None:
        """阶段 3 第 3 层（深思）接收 av/llm/escalate 调用。

        与 process_command 不同：
          - 不发 av/llm/event（已由源端发过 command_generated/None）
          - 不二次 escalate（这一层就是终点）
          - 输出到 av/control 时透传 escalated_from / escalate_reason
        """
        try:
            inner = payload.get("payload") if isinstance(payload, dict) else None
            if not isinstance(inner, dict):
                inner = payload if isinstance(payload, dict) else {}
            text = inner.get("text", "")
            correlation_id = inner.get("correlation_id") or (
                (payload.get("header") or {}).get("msg_id") if isinstance(payload, dict) else None
            )
            escalate_reason = inner.get("escalate_reason", "unknown")
            source_host = inner.get("source_host", "unknown")
            if not text:
                return
            logger.info(f"⤴ 收到 escalate from {source_host}: reason={escalate_reason} text={text!r}")
            cmd = self.generate_command(text)
            if cmd and self._mqtt_publisher:
                self._mqtt_publisher("av/control", {
                    "topic_type": "event",
                    "payload": {
                        **cmd,
                        "original_text": text,
                        "source_host": self.host_label,
                        "escalated_from": source_host,
                        "escalate_reason": escalate_reason,
                    },
                    "metadata": {"correlation_id": correlation_id},
                })
                logger.info(f"⤴↻ escalate 处理成功：{cmd['cmd']} ← {text!r}")
            else:
                logger.warning(
                    f"⤴✗ escalate 深思失败：{text!r} miss={self._last_miss_reason}"
                )
        except Exception as e:
            logger.error(f"handle_escalate 异常: {e}")

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
        self._last_cmd_attempt = None
        if not text_clean:
            self._last_miss_reason = "empty_text"
            return None
        # 漏斗第 1 层 fast-path：原文同时含 location label + device label + action 别名 →
        # 直接命中 cmd_id 0ms 返回，绕过 NPU/ollama。
        # 仅当唯一命中时走，多歧义命中则回落 LLM 让模型权衡。
        fp_hit = self._fastpath_match(text_clean)
        if fp_hit:
            self._last_miss_reason = None
            logger.info(f"⚡ fast-path 命中：{fp_hit} ← {text!r}")
            return {"cmd": fp_hit}
        prompt = self.command_prompt + text_clean + "\n系统输出："
        raw = self._ask_fast(prompt)
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
            self._last_miss_reason = "llm_returned_null"
            return None
        cmd_str = cmd_str.strip()
        if not cmd_str or cmd_str.lower() == "null":
            self._last_miss_reason = "llm_returned_null"
            return None
        if self._cmd_whitelist and cmd_str not in self._cmd_whitelist:
            logger.warning(f"LLM hallucinate 拒绝：{cmd_str!r} 不在 catalog 白名单（{len(self._cmd_whitelist)} 项）")
            self._last_cmd_attempt = cmd_str
            self._last_miss_reason = "filter_rejected_whitelist"
            return None
        # 地点反幻觉：cmd 前缀的 location label 必须出现在用户原文中，或等于本机 default_location。
        # 缘由：NPU 1.5B 实测会"偷换地点"（说"机房"输出 Corridor_xxx，cmd_id 合法但地点错），
        # 白名单不拦但执行就是错命令。最长前缀匹配避开 "DiningTable" vs "2FDiningTable" 歧义。
        if self._location_lookup:
            matches = [lid for lid in self._location_lookup if cmd_str.startswith(lid + "_")]
            if matches:
                loc_id = max(matches, key=len)
                loc_label = self._location_lookup.get(loc_id, "")
                # _global 是合法的全局指令前缀，不需要在 text 出现
                if loc_id != "_global" and loc_id != self._default_location_id \
                        and loc_label and loc_label not in text:
                    logger.warning(
                        f"location hallucinate 拒绝：cmd={cmd_str!r} 但原文 {text!r} "
                        f"不含地点'{loc_label}'，也非 default_location"
                    )
                    self._last_cmd_attempt = cmd_str
                    self._last_miss_reason = "filter_rejected_location"
                    return None
        self._last_miss_reason = None
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

    def _fastpath_match(self, text: str) -> Optional[str]:
        """fast-path 唯一命中返回 cmd_id；歧义 / 不命中返回 None 让上层走 LLM。

        三件套都要 substring 包含：location label + device label + 任一 action alias。
        多条命中按优先级：location label 更长（更具体）的优先（"二楼餐桌" > "餐桌"）；
        同位置同设备多 action 命中（如 "开窗帘关吧台灯" 复合）回 None 走 LLM。
        """
        hits = []
        for cid, loc_label, dev_label, action_aliases in self._fastpath_index:
            if loc_label not in text:
                continue
            if dev_label not in text:
                continue
            if not any(a in text for a in action_aliases):
                continue
            hits.append((cid, loc_label))
        if not hits:
            return None
        # 同 cmd_id 命中多次（aliases 重叠）去重
        unique = {cid for cid, _ in hits}
        if len(unique) == 1:
            return next(iter(unique))
        # 多 cmd_id 命中：取 location label 最长的（"二楼餐桌" > "餐桌"避免歧义）。
        # 若长度也相同（不同 loc 同 device 同 action 命中）说明真歧义 → 回落 LLM。
        max_loc_len = max(len(loc) for _, loc in hits)
        finalists = [cid for cid, loc in hits if len(loc) == max_loc_len]
        if len(set(finalists)) == 1:
            return finalists[0]
        return None

    def _ask_fast(self, prompt: str) -> str:
        """generate_command 的后端路由：rknn 走 NPU daemon，否则 ollama fast 模型。

        NPU daemon 死掉会自动回退 ollama（不让 NPU 故障阻塞主链路）。
        """
        if self.backend == "rknn" and self._rknn is not None:
            if self._rknn.is_alive():
                return self._rknn.ask(prompt)
            logger.warning("RKLLM daemon 已死，本次回退 ollama")
        return self._ask(self.model_fast, prompt)

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
                    "prompt": prompt + " /no_think",
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
