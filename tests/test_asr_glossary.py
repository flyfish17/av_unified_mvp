"""
audio_processor 转写后处理 + 词表注入 测试（任务①②）

本项目无 pytest，直接 `python3 tests/test_asr_glossary.py` 跑断言。
覆盖：
- 任务②：apply_postprocess_rules 对全部英文缩写 case + 负样本（不该误替换）
- 任务①：glossary_to_hotwords / merge_hotwords 纯函数，及真实 config 装载链路
"""
import json
import sys
from pathlib import Path

# 让脚本能 import 到 core.asr_glossary
_REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO))

from core.asr_glossary import (  # noqa: E402
    apply_postprocess_rules,
    compile_postproc_rules,
    glossary_to_hotwords,
    merge_hotwords,
)

_PASS = 0
_FAIL = 0


def check(name, got, want):
    global _PASS, _FAIL
    if got == want:
        _PASS += 1
        print(f"  ✓ {name}")
    else:
        _FAIL += 1
        print(f"  ✗ {name}\n      got : {got!r}\n      want: {want!r}")


# ── 任务② 英文缩写后处理 ──────────────────────────────────────────
# 用真实 config 规则，确保规则文件本身也被测到
_RULES_YAML = _REPO / "config" / "asr_postprocess_rules.yaml"
import yaml  # noqa: E402

with open(_RULES_YAML, encoding="utf-8") as f:
    _rules = compile_postproc_rules(yaml.safe_load(f).get("abbrev_restore"))


def restore(text):
    return apply_postprocess_rules(text, _rules)


print("任务② 英文缩写还原：")
check("派ad → iPad", restore("派ad"), "iPad")
check("u sb → USB", restore("u sb"), "USB")
check("a pp → app", restore("a pp"), "app")
check("a i → AI", restore("a i"), "AI")
check("r eg → RAG", restore("r eg"), "RAG")
check("hh的 mi → HDMI", restore("hh的 mi"), "HDMI")
check("m i ni → mini", restore("m i ni"), "mini")
# spec 真机句：综合一段
check(
    "整句还原",
    restore("我用 派ad 通过 hh的 mi 接到 mini 上 跑 a i 转写 做 r eg 检索"),
    "我用 iPad 通过 HDMI 接到 mini 上 跑 AI 转写 做 RAG 检索",
)

print("任务② 负样本（不该误替换）：")
check("air 不变 AIr", restore("打开 air 模式"), "打开 air 模式")
check("纯中文不动", restore("把会议室的灯打开"), "把会议室的灯打开")
check("派对 不变 iPad对", restore("今晚有个派对"), "今晚有个派对")
check("空文本", restore(""), "")


# ── 任务① 词表注入纯函数 ──────────────────────────────────────────
print("任务① glossary → hotwords：")
g = glossary_to_hotwords({"people": ["韩苏宁", "李冰"], "products": ["Husion"], "terms": ["中控"]})
check("拍扁三段", g, {"韩苏宁": 20, "李冰": 20, "Husion": 20, "中控": 20})
check("空词跳过", glossary_to_hotwords({"people": ["", "  ", "李冰"]}), {"李冰": 20})
check("缺段不报错", glossary_to_hotwords({}), {})

print("任务① merge → FunASR json 字符串：")
check("空 config 仅 glossary", json.loads(merge_hotwords("", {"韩苏宁": 20})), {"韩苏宁": 20})
check("空+空 → 空串", merge_hotwords("", {}), "")
# config 已是 {词:权重} dict 串，优先级最高（覆盖同名）
merged = json.loads(merge_hotwords('{"韩苏宁": 50, "X": 30}', {"韩苏宁": 20, "李冰": 20}))
check("config dict 覆盖权重", merged, {"韩苏宁": 50, "李冰": 20, "X": 30})
# config 是纯词串退路
merged2 = json.loads(merge_hotwords("foo bar", {"韩苏宁": 20}))
check("config 纯词串退路", merged2, {"韩苏宁": 20, "foo": 20, "bar": 20})


# ── 任务① 真实 config 装载链路（plumbing）─────────────────────────
print("任务① 真实 config 装载链路：")
from modules.audio_processor.processor import AudioProcessor  # noqa: E402

# 只构造，不 start()，不碰麦克风/websocket
proc = AudioProcessor({"funasr": {"mode": "websocket_2pass", "hotwords": ""}})
hw = json.loads(proc.hotwords) if proc.hotwords else {}
check("glossary 人名进 hotwords", "韩苏宁" in hw and "李冰" in hw, True)
check("hotwords 是 JSON dict 串（非空格串）", isinstance(hw, dict), True)
check("postproc 规则已编译加载", len(proc._postproc_rules) > 0, True)
# 模拟 websocket 初始化 payload 的 hotwords 字段（对照 processor.py:_ws_session）
payload_hotwords = proc.hotwords
check("init payload hotwords 含 glossary 词", "韩苏宁" in payload_hotwords, True)

print(f"\n结果：{_PASS} passed, {_FAIL} failed")
sys.exit(1 if _FAIL else 0)
