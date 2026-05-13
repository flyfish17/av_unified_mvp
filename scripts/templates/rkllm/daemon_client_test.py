#!/usr/bin/env python3
"""
Client-side stress test for rkllm_daemon.py:
  - Spawns the daemon
  - Waits for {"ready": true}
  - Sends N prompts, reads N responses
  - Reports per-prompt timings + total throughput
"""
import json
import subprocess
import sys
import time
import os
import argparse

THIS = os.path.dirname(os.path.abspath(__file__))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--daemon", default=os.path.join(THIS, "rkllm_daemon.py"))
    ap.add_argument("--prompts", required=True)
    ap.add_argument("--repeat", type=int, default=1, help="run the prompt list this many times")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    with open(args.prompts) as f:
        base_prompts = json.load(f)

    prompts = []
    for r in range(args.repeat):
        for p in base_prompts:
            prompts.append({**p, "round": r})

    print(f"[*] spawning daemon: {args.daemon}", file=sys.stderr)
    proc = subprocess.Popen(
        [sys.executable, "-u", args.daemon],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr,
        text=True,
        bufsize=1,
    )

    # wait for ready
    t_spawn = time.monotonic()
    ready_line = proc.stdout.readline()
    ready = json.loads(ready_line)
    spawn_to_ready_ms = (time.monotonic()-t_spawn)*1000.0
    print(f"[*] ready in {spawn_to_ready_ms:.0f}ms (daemon reported load_ms={ready.get('load_ms')})", file=sys.stderr)
    if not ready.get("ready"):
        print(f"[!] daemon not ready: {ready_line}", file=sys.stderr)
        return 2

    results = []
    t_all_start = time.monotonic()

    for i, p in enumerate(prompts):
        req = {
            "seq": i + 1,
            "prompt": p["prompt"],
            "role": p.get("role", "user"),
            "enable_thinking": p.get("enable_thinking", False),
        }
        proc.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
        proc.stdin.flush()
        line = proc.stdout.readline()
        if not line:
            print(f"[!] daemon closed stdout at prompt {i}", file=sys.stderr)
            break
        resp = json.loads(line)
        resp["client_id"] = p.get("id")
        resp["client_group"] = p.get("group")
        resp["client_round"] = p.get("round")
        resp["client_prompt"] = p["prompt"]
        results.append(resp)
        if resp.get("perf"):
            tps = (resp["perf"]["generate_tokens"] / (resp["perf"]["generate_time_ms"]/1000.0)) if resp["perf"]["generate_time_ms"] > 0 else 0.0
            print(f"[{i+1}/{len(prompts)}] r{p.get('round')} {p.get('id'):>3} first={resp['first_token_ms']:.0f}ms total={resp['total_ms']:.0f}ms decode={tps:.2f} tok/s gentok={resp['perf']['generate_tokens']}", file=sys.stderr)
        else:
            print(f"[{i+1}/{len(prompts)}] err={resp.get('error')}", file=sys.stderr)

    elapsed = time.monotonic()-t_all_start
    print(f"[*] all done in {elapsed:.1f}s ({len(results)} prompts)", file=sys.stderr)
    print(f"[*] closing daemon stdin...", file=sys.stderr)
    proc.stdin.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.terminate()

    out = {
        "daemon_load_ms": ready.get("load_ms"),
        "daemon_rss_mb": ready.get("rss_mb"),
        "spawn_to_ready_ms": spawn_to_ready_ms,
        "total_elapsed_s": elapsed,
        "n_prompts": len(prompts),
        "n_responses": len(results),
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
