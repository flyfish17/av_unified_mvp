#!/usr/bin/env python3
"""Same 9-prompt benchmark, but using local ollama CPU as baseline.

Reads prompts.json (same schema as RKLLM benchmark). Output: same JSON schema.
"""
import json
import time
import urllib.request
import urllib.error
import argparse
import sys
import subprocess

def query_ollama(model, prompt, max_tokens=200, host="http://localhost:11434"):
    body = {
        "model": model,
        "prompt": prompt,
        "stream": True,
        "options": {
            "temperature": 0.8,
            "top_k": 1,
            "top_p": 0.9,
            "num_predict": max_tokens,
        },
    }
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{host}/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t_start = time.monotonic()
    first_token_ms = None
    text_chunks = []
    final = None
    with urllib.request.urlopen(req, timeout=180) as resp:
        for line in resp:
            if not line:
                continue
            obj = json.loads(line)
            if obj.get("response"):
                if first_token_ms is None:
                    first_token_ms = (time.monotonic() - t_start) * 1000.0
                text_chunks.append(obj["response"])
            if obj.get("done"):
                final = obj
                break
    total_ms = (time.monotonic() - t_start) * 1000.0
    out = {
        "prompt": prompt,
        "prompt_len_chars": len(prompt),
        "response": "".join(text_chunks),
        "first_token_ms": first_token_ms,
        "total_ms": total_ms,
        "perf": None,
        "error": None,
    }
    if final:
        # ollama returns durations in nanoseconds
        prompt_eval_count = final.get("prompt_eval_count", 0)
        prompt_eval_duration_ns = final.get("prompt_eval_duration", 0)
        eval_count = final.get("eval_count", 0)
        eval_duration_ns = final.get("eval_duration", 0)
        load_duration_ns = final.get("load_duration", 0)
        out["perf"] = {
            "prefill_time_ms": prompt_eval_duration_ns / 1e6,
            "prefill_tokens": prompt_eval_count,
            "generate_time_ms": eval_duration_ns / 1e6,
            "generate_tokens": eval_count,
            "load_duration_ms": load_duration_ns / 1e6,
            "memory_usage_mb": None,  # ollama doesn't expose this in API
        }
        if eval_duration_ns > 0:
            out["decode_tok_s"] = eval_count / (eval_duration_ns / 1e9)
        else:
            out["decode_tok_s"] = None
        if prompt_eval_duration_ns > 0:
            out["prefill_tok_s"] = prompt_eval_count / (prompt_eval_duration_ns / 1e9)
        else:
            out["prefill_tok_s"] = None
    return out

def ollama_ps_rss_mb():
    """Best-effort: read ollama serve RSS by pgrep + ps."""
    try:
        pid = subprocess.check_output(["pgrep", "-f", "ollama serve"]).decode().strip().split("\n")[0]
        rss_kb = int(subprocess.check_output(["ps", "-o", "rss=", "-p", pid]).decode().strip())
        return rss_kb / 1024.0
    except Exception:
        return None

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="qwen2.5-coder:1.5b")
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-new-tokens", type=int, default=200)
    args = ap.parse_args()

    with open(args.prompts) as f:
        prompts = json.load(f)

    print(f"[*] model={args.model}, n_prompts={len(prompts)}", file=sys.stderr)
    # Warmup load so the first prompt doesn't pay model-load cost
    print(f"[*] warmup (load model)...", file=sys.stderr)
    warm = query_ollama(args.model, "ping", max_tokens=1)
    print(f"[*]   warmup total={warm['total_ms']:.0f}ms first_tok={warm['first_token_ms']}", file=sys.stderr)

    rss_after_load = ollama_ps_rss_mb()
    print(f"[*] ollama rss after warmup: {rss_after_load} MB", file=sys.stderr)

    results = []
    for i, p in enumerate(prompts):
        prompt = p["prompt"]
        print(f"[*] {i+1}/{len(prompts)} group={p.get('group')} id={p.get('id')} prompt={prompt[:40]!r}", file=sys.stderr)
        try:
            r = query_ollama(args.model, prompt, max_tokens=args.max_new_tokens)
        except Exception as e:
            r = {"error": f"{e!r}", "prompt": prompt, "perf": None}
        r["id"] = p.get("id")
        r["group"] = p.get("group")
        results.append(r)
        if r.get("perf"):
            print(f"    -> first={r['first_token_ms']:.0f}ms total={r['total_ms']:.0f}ms decode={r['decode_tok_s']:.2f} tok/s", file=sys.stderr)
        else:
            print(f"    -> ERROR {r.get('error')}", file=sys.stderr)

    out = {
        "platform": "rk3588_ollama_cpu",
        "model": args.model,
        "ollama_rss_after_warmup_mb": rss_after_load,
        "ollama_rss_post_bench_mb": ollama_ps_rss_mb(),
        "results": results,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"[*] wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0

if __name__ == "__main__":
    sys.exit(main())
