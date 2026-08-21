"""
speaker_diarizer 聚类逻辑单测（纯函数层，不加载模型）。

本项目无 pytest，直接 `python3 modules/speaker_diarizer/tests/test_diarizer.py` 跑断言。
覆盖 OnlineSpeakerClusterer：首段建簇 / 同人归簇 / 异人新建 / 短段跳过 /
非法嵌入 / 质心更新方向 / 短段置信度降档 / ID 不回改。
"""
import sys
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO))

from modules.speaker_diarizer.diarizer import (  # noqa: E402
    MIN_EMBED_S,
    OnlineSpeakerClusterer,
)

_PASS = 0
_FAIL = 0


def check(name, got, want):
    global _PASS, _FAIL
    if got == want:
        _PASS += 1
    else:
        _FAIL += 1
        print(f"FAIL {name}: got={got!r} want={want!r}")


def _unit(v):
    v = np.asarray(v, dtype=np.float32)
    return v / np.linalg.norm(v)


def main():
    # 三个几乎正交的方向，模拟三个说话人；同人嵌入 = 方向加小噪声
    rng = np.random.default_rng(7)
    dim = 192
    base = [_unit(rng.normal(size=dim)) for _ in range(3)]

    def emb_of(spk, noise=0.03):
        return _unit(base[spk] + rng.normal(scale=noise, size=dim))

    c = OnlineSpeakerClusterer(threshold=0.55)

    # 首段：新建 S1；新建簇无参照相似度，置信度为 None
    a = c.assign(emb_of(0), duration_s=3.0)
    check("first_new_id", a.speaker_id, "S1")
    check("first_is_new", a.is_new, True)
    check("first_conf", a.confidence, None)

    # 同人再来：归入 S1，不新建
    a = c.assign(emb_of(0), duration_s=2.0)
    check("same_spk_id", a.speaker_id, "S1")
    check("same_spk_not_new", a.is_new, False)
    check("same_spk_conf_high", a.confidence is not None and a.confidence > 0.8, True)

    # 异人：新建 S2
    a = c.assign(emb_of(1), duration_s=4.0)
    check("diff_spk_new_id", a.speaker_id, "S2")
    check("diff_spk_is_new", a.is_new, True)
    check("num_speakers_2", c.num_speakers, 2)

    # 第三人：新建 S3；且 S1/S2 的 ID 不因新簇出现而改变（不回改历史）
    a = c.assign(emb_of(2), duration_s=1.8)
    check("third_spk_new_id", a.speaker_id, "S3")
    a = c.assign(emb_of(0), duration_s=2.5)
    check("s1_stable_after_new_clusters", a.speaker_id, "S1")

    # 短段：<MIN_EMBED_S 不猜
    a = c.assign(emb_of(0), duration_s=MIN_EMBED_S - 0.1)
    check("short_seg_none", a.speaker_id, None)
    check("short_seg_conf_none", a.confidence, None)

    # 非法嵌入：None / 零向量
    check("none_emb", c.assign(None, duration_s=3.0).speaker_id, None)
    check("zero_emb", c.assign(np.zeros(dim), duration_s=3.0).speaker_id, None)

    # 0.5–1.5s 降档：同人短段置信度 < 同人长段
    long_conf = c.assign(emb_of(1), duration_s=3.0).confidence
    short_conf = c.assign(emb_of(1), duration_s=0.8).confidence
    check("low_conf_damped", short_conf < long_conf, True)

    # 短段（<NEW_SPK_MIN_S）不许开新簇：陌生方向 + 短时长 → None，且簇数不变
    n_before = c.num_speakers
    stranger = _unit(rng.normal(size=dim))
    a = c.assign(stranger, duration_s=0.9)
    check("short_no_spawn_none", a.speaker_id, None)
    check("short_no_spawn_count", c.num_speakers, n_before)
    # 同方向长段则允许开新簇
    a = c.assign(stranger, duration_s=2.0)
    check("long_can_spawn", a.is_new, True)

    # 短段归簇不更新质心
    c3 = OnlineSpeakerClusterer(threshold=0.55)
    c3.assign(base[0], duration_s=3.0)
    cent_before = c3._speakers[0].centroid.copy()
    c3.assign(emb_of(0), duration_s=0.8)
    check("short_seg_no_centroid_update", bool(np.array_equal(cent_before, c3._speakers[0].centroid)), True)

    # 质心更新方向：连续喂偏移样本后，与偏移方向相似度应上升
    c2 = OnlineSpeakerClusterer(threshold=0.55)
    drift = _unit(base[0] + 0.3 * base[1])
    c2.assign(base[0], duration_s=3.0)
    sim_before = float(np.dot(c2._speakers[0].centroid, drift))
    for _ in range(5):
        c2.assign(drift, duration_s=3.0)
    sim_after = float(np.dot(c2._speakers[0].centroid, drift))
    check("centroid_follows_updates", sim_after > sim_before, True)
    check("centroid_normalized", abs(float(np.linalg.norm(c2._speakers[0].centroid)) - 1.0) < 1e-5, True)

    print(f"\n{_PASS} passed, {_FAIL} failed")
    sys.exit(1 if _FAIL else 0)


if __name__ == "__main__":
    main()
