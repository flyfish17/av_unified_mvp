#!/usr/bin/env python3
"""
eval_sense_voice.py — SenseVoiceSmall 离线推理 benchmark + 可选 CER。

用法：
  python3 eval_sense_voice.py --wav-dir ~/eval_data --device cuda \
      --model ~/models/SenseVoiceSmall --transcript transcripts.json

参数：
  --wav-dir       WAV/MP3 目录，递归找
  --device        cuda | cpu
  --model         SenseVoiceSmall 模型路径
  --transcript    可选 JSON，{文件名: 标准转写}，若提供输出 CER
  --out           输出 JSON 报告（含每条结果 + 总 RTF + CER）

输出：
  逐条 + 总览：音频时长 / 推理时长 / RTF / 文本（/ CER if transcript）
"""
import argparse
import json
import re
import sys
import time
from pathlib import Path

_TAG_RE = re.compile(r"<\|[^|]+\|>")


def char_error_rate(hyp: str, ref: str) -> float:
    """Levenshtein 距离 / ref 字符数。两边都剥空白和标点（与 ASR 输出对齐）。"""
    norm = lambda s: re.sub(r"[\s,.!?;:'\"，。！？；：、""'']+", "", s)
    h, r = norm(hyp), norm(ref)
    if not r:
        return 0.0 if not h else 1.0
    m, n = len(h), len(r)
    dp = [[0] * (n + 1) for _ in range(m + 1)]
    for i in range(m + 1):
        dp[i][0] = i
    for j in range(n + 1):
        dp[0][j] = j
    for i in range(1, m + 1):
        for j in range(1, n + 1):
            if h[i - 1] == r[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                dp[i][j] = 1 + min(dp[i - 1][j], dp[i][j - 1], dp[i - 1][j - 1])
    return dp[m][n] / n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav-dir", required=True)
    ap.add_argument("--device", default="cuda", choices=["cuda", "cpu"])
    ap.add_argument("--model", required=True)
    ap.add_argument("--transcript", default=None,
                    help="可选 JSON：{filename_stem: ref_text}")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    wav_dir = Path(args.wav_dir).expanduser()
    wavs = sorted([
        p for p in wav_dir.rglob("*")
        if p.suffix.lower() in (".wav", ".mp3", ".flac", ".m4a") and "._" not in p.name
    ])
    if not wavs:
        print(f"no wavs in {wav_dir}", file=sys.stderr)
        sys.exit(1)

    refs = {}
    if args.transcript:
        with open(args.transcript) as f:
            refs = json.load(f)

    print(f"[eval] device={args.device} model={args.model} wavs={len(wavs)}")
    t_load_0 = time.time()
    from funasr import AutoModel
    model = AutoModel(
        model=args.model,
        trust_remote_code=True,
        disable_update=True,
        remote_rdonly=True,
        device=args.device,
    )
    t_load = time.time() - t_load_0
    print(f"[eval] model loaded in {t_load:.2f}s")

    # warm-up：CUDA 第一次推理含 kernel JIT 编译，跳过避免污染 RTF
    if wavs and args.device == "cuda":
        try:
            model.generate(input=str(wavs[0]), batch_size=1)
            print("[eval] warm-up done")
        except Exception as e:
            print(f"[eval] warm-up err: {e}")

    results = []
    sum_audio_s = 0.0
    sum_infer_s = 0.0
    sum_cer_n = 0
    sum_cer_d = 0
    for i, wav in enumerate(wavs):
        try:
            # 量音频时长（用 soundfile 或 wave 都行；funasr.generate 内部会重采样）
            try:
                import soundfile as sf
                info = sf.info(str(wav))
                audio_s = info.frames / info.samplerate
            except Exception:
                # mp3 等格式 soundfile 不一定支持，fallback 用 ffprobe 估计
                audio_s = 0.0

            t0 = time.time()
            res = model.generate(input=str(wav), batch_size=1)
            infer_s = time.time() - t0
            text = _TAG_RE.sub("", res[0].get("text", "")).strip() if res else ""

            rec = {
                "file": wav.name,
                "audio_s": round(audio_s, 2),
                "infer_s": round(infer_s, 3),
                "rtf": round(infer_s / audio_s, 3) if audio_s > 0 else None,
                "text": text,
            }
            if refs:
                stem = wav.stem
                ref = refs.get(stem, refs.get(wav.name, ""))
                if ref:
                    cer = char_error_rate(text, ref)
                    rec["ref"] = ref
                    rec["cer"] = round(cer, 4)
                    # 总 CER 用字符数加权
                    norm = lambda s: re.sub(r"[\s,.!?;:'\"，。！？；：、""'']+", "", s)
                    sum_cer_n += int(cer * len(norm(ref)))
                    sum_cer_d += len(norm(ref))
            results.append(rec)
            sum_audio_s += audio_s
            sum_infer_s += infer_s
            print(f"  [{i+1}/{len(wavs)}] {wav.name}  audio={audio_s:.1f}s  infer={infer_s*1000:.0f}ms  rtf={rec['rtf']}  cer={rec.get('cer','-')}")
        except Exception as e:
            print(f"  [{i+1}/{len(wavs)}] ERROR {wav.name}: {e}")
            results.append({"file": wav.name, "error": str(e)})

    summary = {
        "device": args.device,
        "model": args.model,
        "wavs": len(wavs),
        "total_audio_s": round(sum_audio_s, 2),
        "total_infer_s": round(sum_infer_s, 3),
        "avg_rtf": round(sum_infer_s / sum_audio_s, 3) if sum_audio_s > 0 else None,
        "load_s": round(t_load, 2),
        "results": results,
    }
    if sum_cer_d > 0:
        summary["overall_cer"] = round(sum_cer_n / sum_cer_d, 4)
    Path(args.out).write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\n[eval] avg_rtf={summary['avg_rtf']} total_audio_s={summary['total_audio_s']} total_infer_s={summary['total_infer_s']}")
    if "overall_cer" in summary:
        print(f"[eval] overall_cer={summary['overall_cer']}")
    print(f"[eval] report → {args.out}")


if __name__ == "__main__":
    main()
