"""
CAM++ 在线聚类 · 真实录音评测（S2 验收脚本，需本地 campplus 模型缓存）。

用法：
  python3.10 modules/speaker_diarizer/tests/eval_real_audio.py <wav> <segments.json> [--sweep]

<wav>            16k 单声道 WAV 全程录音
<segments.json>  MOSS 参照分段 {num_speakers, segments: [[start,end,"S1"],...]}
--sweep          阈值扫描 0.25–0.60 步长 0.05（默认只跑标定值 0.35）

评测口径：
- 只评 ≥0.5s 的段（短段设计上跳过不猜）；重叠插话段截出来的音频本就混有主讲，
  标签对不上不算错，单独统计为 overlap 行仅供参考。
- num_speakers：聚出的人数 vs 参照人数。
- mapped accuracy：聚类 ID 与参照标签做贪心最优映射后的段级命中率
 （只统计非重叠段）。
- 同人跨段稳定性：参照同一说话人的段是否始终拿到同一聚类 ID。
"""
import json
import sys
import tempfile
import wave
from pathlib import Path

import numpy as np

_REPO = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_REPO))

from modules.speaker_diarizer.diarizer import (  # noqa: E402
    CamppEmbedder,
    OnlineSpeakerClusterer,
    find_local_model,
)


def load_segments(json_path):
    with open(json_path, encoding="utf-8") as f:
        data = json.load(f)
    segs = [
        {"start": s, "end": e, "ref": spk}
        for s, e, spk in data["segments"]
    ]
    segs.sort(key=lambda x: x["start"])
    return data["num_speakers"], segs


def mark_overlaps(segs):
    for i, a in enumerate(segs):
        a["overlap"] = any(
            j != i and b["start"] < a["end"] and a["start"] < b["end"]
            for j, b in enumerate(segs)
        )


def slice_wavs(wav_path, segs, out_dir):
    with wave.open(str(wav_path), "rb") as wf:
        assert wf.getframerate() == 16000 and wf.getnchannels() == 1, "需 16k 单声道"
        pcm = np.frombuffer(wf.readframes(wf.getnframes()), dtype=np.int16)
    for i, s in enumerate(segs):
        a, b = int(s["start"] * 16000), int(s["end"] * 16000)
        p = out_dir / f"seg-{i:03d}.wav"
        with wave.open(str(p), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16000)
            out.writeframes(pcm[a:b].tobytes())
        s["wav"] = p


def greedy_map(pairs):
    """(ref, hyp) 对 → ref→hyp 贪心最优映射（按共现次数降序认领）。"""
    from collections import Counter
    co = Counter(pairs)
    mapping, used = {}, set()
    for (ref, hyp), _ in co.most_common():
        if ref not in mapping and hyp not in used:
            mapping[ref] = hyp
            used.add(hyp)
    return mapping


def run(embedder, segs, threshold):
    clus = OnlineSpeakerClusterer(threshold=threshold)
    for s in segs:
        dur = s["end"] - s["start"]
        emb = embedder.embed_wav(s["wav"]) if dur >= 0.5 else None
        s["hyp"] = clus.assign(emb, dur).speaker_id
    scored = [s for s in segs if s["hyp"] is not None]
    clean = [s for s in scored if not s["overlap"]]
    mapping = greedy_map([(s["ref"], s["hyp"]) for s in clean])
    hit = sum(1 for s in clean if mapping.get(s["ref"]) == s["hyp"])
    # 同人跨段稳定性：每个参照说话人（非重叠段≥2）的多数 ID 占比
    stab = {}
    for s in clean:
        stab.setdefault(s["ref"], []).append(s["hyp"])
    stab_str = ", ".join(
        f"{ref}:{max(sum(1 for h in hs if h == m) for m in set(hs))}/{len(hs)}"
        for ref, hs in sorted(stab.items()) if len(hs) >= 2
    )
    ov = [s for s in scored if s["overlap"]]
    ov_hit = sum(1 for s in ov if mapping.get(s["ref"]) == s["hyp"])
    return {
        "threshold": threshold,
        "num_found": clus.num_speakers,
        "clean_acc": f"{hit}/{len(clean)}",
        "stability": stab_str,
        "overlap_ref": f"{ov_hit}/{len(ov)}",
    }


def main():
    wav_path, json_path = Path(sys.argv[1]), Path(sys.argv[2])
    sweep = "--sweep" in sys.argv
    model_dir = find_local_model()
    if model_dir is None:
        print("campplus 模型未缓存，先 snapshot_download")
        sys.exit(2)

    num_ref, segs = load_segments(json_path)
    mark_overlaps(segs)
    with tempfile.TemporaryDirectory() as td:
        slice_wavs(wav_path, segs, Path(td))
        embedder = CamppEmbedder(model_dir)
        thresholds = [round(0.25 + 0.05 * i, 2) for i in range(8)] if sweep else [0.35]
        print(f"参照人数={num_ref}  段数={len(segs)}  评测段(≥0.5s)见下")
        for t in thresholds:
            r = run(embedder, segs, t)
            print(
                f"thr={r['threshold']:.2f}  聚出={r['num_found']}人  "
                f"非重叠段命中={r['clean_acc']}  跨段稳定[{r['stability']}]  "
                f"重叠段参考={r['overlap_ref']}"
            )


if __name__ == "__main__":
    main()
