#!/usr/bin/env python3
"""
RKLLM benchmark - runs N prompts through one loaded model, captures per-prompt timings.

Output: JSON to stdout (and optional --out file). One model load, repeated rkllm_run.
"""
import ctypes
import os
import sys
import time
import json
import argparse
import threading
import resource

# Reuse the ctypes binding definitions from smoke_test.py
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from smoke_test import (
    RKLLM_Handle_t, RKLLMParam, RKLLMInput, RKLLMInferParam,
    RKLLMResult, CALLBACK_TYPE,
    RKLLMInputType_PROMPT, RKLLMInferMode_GENERATE,
    LLMCallState_RKLLM_RUN_NORMAL,
    LLMCallState_RKLLM_RUN_FINISH,
    LLMCallState_RKLLM_RUN_ERROR,
)

class Run:
    def __init__(self):
        self.start_ts = None
        self.first_token_ms = None
        self.text_chunks = []
        self.finish_event = threading.Event()
        self.perf = None
        self.error = None

    def reset(self):
        self.start_ts = time.monotonic()
        self.first_token_ms = None
        self.text_chunks = []
        self.finish_event.clear()
        self.perf = None
        self.error = None

RUN = Run()

def callback_impl(result_ptr, userdata, state):
    try:
        if state == LLMCallState_RKLLM_RUN_NORMAL:
            if RUN.first_token_ms is None:
                RUN.first_token_ms = (time.monotonic() - RUN.start_ts) * 1000.0
            raw = result_ptr.contents.text
            if raw:
                RUN.text_chunks.append(raw.decode("utf-8", errors="replace"))
        elif state == LLMCallState_RKLLM_RUN_FINISH:
            p = result_ptr.contents.perf
            RUN.perf = {
                "prefill_time_ms": float(p.prefill_time_ms),
                "prefill_tokens": int(p.prefill_tokens),
                "generate_time_ms": float(p.generate_time_ms),
                "generate_tokens": int(p.generate_tokens),
                "memory_usage_mb": float(p.memory_usage_mb),
            }
            RUN.finish_event.set()
        elif state == LLMCallState_RKLLM_RUN_ERROR:
            RUN.error = "RKLLM_RUN_ERROR"
            RUN.finish_event.set()
    except Exception as e:
        RUN.error = f"callback_exception: {e!r}"
        RUN.finish_event.set()
    return 0

CALLBACK_FN = CALLBACK_TYPE(callback_impl)

def init_model(lib, model_path, max_context_len=2048, max_new_tokens=512, platform="rk3588"):
    p = RKLLMParam()
    p.model_path = model_path.encode("utf-8")
    p.max_context_len = max_context_len
    p.max_new_tokens = max_new_tokens
    p.skip_special_token = True
    p.n_keep = -1
    p.top_k = 1
    p.top_p = 0.9
    p.temperature = 0.8
    p.repeat_penalty = 1.1
    p.frequency_penalty = 0.0
    p.presence_penalty = 0.0
    p.mirostat = 0
    p.mirostat_tau = 5.0
    p.mirostat_eta = 0.1
    p.is_async = False
    p.img_start = b""
    p.img_end = b""
    p.img_content = b""
    p.extend_param.base_domain_id = 0
    p.extend_param.embed_flash = 1
    p.extend_param.n_batch = 1
    p.extend_param.use_cross_attn = 0
    p.extend_param.enabled_cpus_num = 4
    if platform.lower() in ("rk3588","rk3576"):
        p.extend_param.enabled_cpus_mask = (1<<4)|(1<<5)|(1<<6)|(1<<7)
    else:
        p.extend_param.enabled_cpus_mask = (1<<0)|(1<<1)|(1<<2)|(1<<3)

    lib.rkllm_init.argtypes = [ctypes.POINTER(RKLLM_Handle_t), ctypes.POINTER(RKLLMParam), CALLBACK_TYPE]
    lib.rkllm_init.restype = ctypes.c_int
    lib.rkllm_run.argtypes = [RKLLM_Handle_t, ctypes.POINTER(RKLLMInput), ctypes.POINTER(RKLLMInferParam), ctypes.c_void_p]
    lib.rkllm_run.restype = ctypes.c_int
    lib.rkllm_destroy.argtypes = [RKLLM_Handle_t]
    lib.rkllm_destroy.restype = ctypes.c_int

    handle = RKLLM_Handle_t()
    t0 = time.monotonic()
    rc = lib.rkllm_init(ctypes.byref(handle), ctypes.byref(p), CALLBACK_FN)
    load_ms = (time.monotonic()-t0)*1000.0
    if rc != 0:
        raise RuntimeError(f"rkllm_init returned {rc}")
    return handle, load_ms

def run_prompt(lib, handle, prompt, role="user", enable_thinking=False):
    infer = RKLLMInferParam()
    ctypes.memset(ctypes.byref(infer), 0, ctypes.sizeof(RKLLMInferParam))
    infer.mode = RKLLMInferMode_GENERATE
    infer.lora_params = None
    infer.prompt_cache_params = None
    infer.keep_history = 0

    rin = RKLLMInput()
    rin.role = role.encode("utf-8")
    rin.enable_thinking = bool(enable_thinking)
    rin.input_type = RKLLMInputType_PROMPT
    rin.input_data.prompt_input = prompt.encode("utf-8")

    RUN.reset()
    rc = lib.rkllm_run(handle, ctypes.byref(rin), ctypes.byref(infer), None)
    if not RUN.finish_event.is_set():
        RUN.finish_event.wait(timeout=2.0)
    total_ms = (time.monotonic()-RUN.start_ts)*1000.0

    return {
        "rc": int(rc),
        "prompt": prompt,
        "prompt_len_chars": len(prompt),
        "response": "".join(RUN.text_chunks),
        "first_token_ms": RUN.first_token_ms,
        "total_ms": total_ms,
        "perf": RUN.perf,
        "error": RUN.error,
    }

def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0  # KB on linux → MB

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=os.path.expanduser("~/rkllm-poc/artifacts/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"))
    ap.add_argument("--model", default=os.path.expanduser("~/rkllm-poc/artifacts/Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm"))
    ap.add_argument("--prompts", required=True, help="JSON file with list of {id, group, prompt, max_new_tokens?}")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max-context-len", type=int, default=2048)
    ap.add_argument("--max-new-tokens", type=int, default=256)
    args = ap.parse_args()

    with open(args.prompts) as f:
        prompts = json.load(f)

    print(f"[*] loading lib...", file=sys.stderr)
    t_dl = time.monotonic()
    lib = ctypes.CDLL(args.lib)
    print(f"[*] dlopen: {(time.monotonic()-t_dl)*1000:.0f} ms", file=sys.stderr)

    print(f"[*] rkllm_init...", file=sys.stderr)
    handle, load_ms = init_model(
        lib, args.model,
        max_context_len=args.max_context_len,
        max_new_tokens=args.max_new_tokens,
    )
    print(f"[*] rkllm_init done in {load_ms:.0f} ms", file=sys.stderr)

    rss_after_load_mb = rss_mb()
    print(f"[*] rss after load: {rss_after_load_mb:.0f} MB", file=sys.stderr)

    results = []
    for i, p in enumerate(prompts):
        prompt = p["prompt"]
        print(f"[*] {i+1}/{len(prompts)} group={p.get('group')} id={p.get('id')} prompt={prompt[:40]!r}", file=sys.stderr)
        r = run_prompt(lib, handle, prompt)
        r["id"] = p.get("id")
        r["group"] = p.get("group")
        # rough tok/s for decode
        if r["perf"] and r["perf"]["generate_time_ms"] > 0:
            r["decode_tok_s"] = r["perf"]["generate_tokens"] / (r["perf"]["generate_time_ms"]/1000.0)
        else:
            r["decode_tok_s"] = None
        if r["perf"] and r["perf"]["prefill_time_ms"] > 0:
            r["prefill_tok_s"] = r["perf"]["prefill_tokens"] / (r["perf"]["prefill_time_ms"]/1000.0)
        else:
            r["prefill_tok_s"] = None
        results.append(r)
        # print one-line summary live
        if r["perf"]:
            print(f"    -> first={r['first_token_ms']:.0f}ms total={r['total_ms']:.0f}ms decode={r['decode_tok_s']:.2f} tok/s mem={r['perf']['memory_usage_mb']:.0f}MB", file=sys.stderr)
        else:
            print(f"    -> ERROR rc={r['rc']} err={r['error']}", file=sys.stderr)

    print(f"[*] rkllm_destroy...", file=sys.stderr)
    lib.rkllm_destroy(handle)

    out = {
        "load_ms": load_ms,
        "rss_after_load_mb": rss_after_load_mb,
        "rss_peak_mb": rss_mb(),
        "platform": "rk3588_npu",
        "results": results,
    }
    text = json.dumps(out, ensure_ascii=False, indent=2)
    if args.out:
        with open(args.out, "w") as f:
            f.write(text)
        print(f"[*] wrote {args.out}", file=sys.stderr)
    else:
        print(text)
    return 0 if not any(r["error"] for r in results) else 2

if __name__ == "__main__":
    sys.exit(main())
