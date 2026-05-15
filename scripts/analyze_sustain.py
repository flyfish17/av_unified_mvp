#!/usr/bin/env python3
"""解析 mosquitto_sub -v 输出的 jsonl，统计视觉深思链路指标。

用法:
    scripts/analyze_sustain.py <file1.jsonl> [file2.jsonl ...]
    scripts/analyze_sustain.py --label A=baseline.jsonl --label B=config_b.jsonl

输入格式（mosquitto_sub -v）：每行 "<topic> <json_payload>"
关心 topic:
    av/video/detect          → {camera, time, detections[]}
    av/video/key_event       → {camera, time, reason, ...}
    av/video/scene_analysis  → {camera, vlm_latency_ms, snapshot_latency_ms, ...}
    av/video/openvocab       → {camera, hits[{class, conf}], inference_ms, key_reason}
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from pathlib import Path


def parse_jsonl(path: Path):
    """yield (topic, payload_dict) tuples; skip malformed lines."""
    bad = 0
    total = 0
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            total += 1
            sp = line.find(" ")
            if sp < 0:
                bad += 1
                continue
            topic, raw = line[:sp], line[sp + 1 :]
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                bad += 1
                continue
            yield topic, payload
    if bad:
        print(f"  [warn] {path.name}: {bad}/{total} malformed lines skipped", file=sys.stderr)


def pct(values, p):
    if not values:
        return None
    s = sorted(values)
    k = int(round((p / 100.0) * (len(s) - 1)))
    return s[k]


def analyze_one(label: str, path: Path) -> dict:
    detect_per_cam = Counter()
    detect_empty_per_cam = Counter()
    key_per_cam = Counter()
    key_reason = Counter()
    scene_per_cam = Counter()
    vlm_latency_ms = []
    snapshot_latency_ms = []
    openvocab_hits_per_cam = Counter()
    openvocab_hits_per_class = Counter()
    openvocab_conf = defaultdict(list)  # class → list of conf
    openvocab_inf_ms = []
    cameras = set()

    first_ts = None
    last_ts = None

    for topic, payload in parse_jsonl(path):
        ts = (payload.get("header") or {}).get("timestamp") or payload.get("ts") or payload.get("time")
        if ts:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        cam = payload.get("camera", "?")
        cameras.add(cam)

        if topic == "av/video/detect":
            detect_per_cam[cam] += 1
            if not payload.get("detections"):
                detect_empty_per_cam[cam] += 1
        elif topic == "av/video/key_event":
            key_per_cam[cam] += 1
            key_reason[payload.get("key_reason") or payload.get("reason") or "?"] += 1
        elif topic == "av/video/scene_analysis":
            scene_per_cam[cam] += 1
            if "vlm_latency_ms" in payload:
                vlm_latency_ms.append(payload["vlm_latency_ms"])
            if "snapshot_latency_ms" in payload:
                snapshot_latency_ms.append(payload["snapshot_latency_ms"])
        elif topic == "av/video/openvocab":
            hits = payload.get("hits") or []
            openvocab_hits_per_cam[cam] += len(hits)
            for h in hits:
                cls = h.get("class", "?")
                cnf = h.get("conf")
                openvocab_hits_per_class[cls] += 1
                if cnf is not None:
                    openvocab_conf[cls].append(float(cnf))
            if "inference_ms" in payload:
                openvocab_inf_ms.append(payload["inference_ms"])

    duration_s = (last_ts - first_ts) if (first_ts and last_ts) else 0

    return {
        "label": label,
        "path": str(path),
        "duration_s": duration_s,
        "cameras": sorted(cameras),
        "detect_per_cam": dict(detect_per_cam),
        "detect_empty_per_cam": dict(detect_empty_per_cam),
        "key_per_cam": dict(key_per_cam),
        "key_reason": dict(key_reason),
        "scene_per_cam": dict(scene_per_cam),
        "vlm_n": len(vlm_latency_ms),
        "vlm_p50": pct(vlm_latency_ms, 50),
        "vlm_p95": pct(vlm_latency_ms, 95),
        "vlm_p99": pct(vlm_latency_ms, 99),
        "vlm_max": max(vlm_latency_ms) if vlm_latency_ms else None,
        "vlm_mean": int(statistics.mean(vlm_latency_ms)) if vlm_latency_ms else None,
        "snapshot_p50": pct(snapshot_latency_ms, 50),
        "snapshot_p95": pct(snapshot_latency_ms, 95),
        "openvocab_hits_per_cam": dict(openvocab_hits_per_cam),
        "openvocab_hits_per_class": dict(openvocab_hits_per_class),
        "openvocab_conf_summary": {
            cls: {
                "n": len(v),
                "min": round(min(v), 3),
                "p50": round(pct(v, 50), 3),
                "p95": round(pct(v, 95), 3),
                "max": round(max(v), 3),
                "mean": round(statistics.mean(v), 3),
            }
            for cls, v in openvocab_conf.items()
        },
        "openvocab_inf_p50": pct(openvocab_inf_ms, 50),
        "openvocab_inf_p95": pct(openvocab_inf_ms, 95),
    }


def fmt_report(reports: list[dict]) -> str:
    out = []
    for r in reports:
        dur_min = r["duration_s"] / 60 if r["duration_s"] else 0
        out.append(f"\n=== {r['label']} ({Path(r['path']).name}) ===")
        out.append(f"duration: {dur_min:.1f} min ({r['duration_s']:.0f} s)")
        out.append(f"cameras: {', '.join(r['cameras'])}")
        out.append("")
        out.append("[detect]")
        for cam, n in sorted(r["detect_per_cam"].items()):
            empty = r["detect_empty_per_cam"].get(cam, 0)
            rate = n / dur_min if dur_min > 0 else 0
            out.append(f"  {cam}: {n} ({empty} empty) — {rate:.1f}/min")
        out.append("")
        out.append("[key_event]")
        for cam, n in sorted(r["key_per_cam"].items()):
            rate = n / dur_min if dur_min > 0 else 0
            out.append(f"  {cam}: {n} — {rate:.2f}/min")
        out.append(f"  reasons: {r['key_reason']}")
        out.append("")
        out.append("[scene_analysis · VLM]")
        out.append(f"  count: {r['vlm_n']}")
        if r["vlm_n"]:
            out.append(
                f"  vlm_latency_ms: p50={r['vlm_p50']}  p95={r['vlm_p95']}  p99={r['vlm_p99']}  max={r['vlm_max']}  mean={r['vlm_mean']}"
            )
            out.append(f"  snapshot_ms: p50={r['snapshot_p50']}  p95={r['snapshot_p95']}")
        for cam, n in sorted(r["scene_per_cam"].items()):
            rate = n / dur_min if dur_min > 0 else 0
            out.append(f"  {cam}: {n} — {rate:.2f}/min")
        out.append("")
        out.append("[openvocab]")
        out.append(
            f"  inference_ms: p50={r['openvocab_inf_p50']}  p95={r['openvocab_inf_p95']}"
        )
        out.append(f"  hits/class: {r['openvocab_hits_per_class']}")
        for cls, s in sorted(r["openvocab_conf_summary"].items()):
            out.append(
                f"    {cls}: n={s['n']}  min={s['min']}  p50={s['p50']}  p95={s['p95']}  max={s['max']}  mean={s['mean']}"
            )
        out.append("")
        # 队列堆积粗估：key_event 数 - scene_analysis 数 ＝ VLM 队列净累积
        total_key = sum(r["key_per_cam"].values())
        total_scene = sum(r["scene_per_cam"].values())
        out.append(
            f"[vlm queue diff] key_event={total_key}  scene_analysis={total_scene}  Δ={total_key - total_scene}"
        )
    return "\n".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("inputs", nargs="*", help="jsonl files (positional)")
    p.add_argument("--label", action="append", default=[], help="LABEL=path.jsonl")
    p.add_argument("--json", action="store_true", help="emit json instead of human report")
    args = p.parse_args()

    targets = []
    for spec in args.label:
        if "=" not in spec:
            p.error(f"--label needs LABEL=path, got {spec!r}")
        lbl, path = spec.split("=", 1)
        targets.append((lbl, Path(path)))
    for path in args.inputs:
        targets.append((Path(path).stem, Path(path)))

    if not targets:
        p.error("no input files")

    reports = [analyze_one(lbl, path) for lbl, path in targets]
    if args.json:
        json.dump(reports, sys.stdout, indent=2, ensure_ascii=False)
    else:
        print(fmt_report(reports))


if __name__ == "__main__":
    main()
