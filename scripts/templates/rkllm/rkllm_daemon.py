#!/usr/bin/env python3
"""
RKLLM inference daemon — long-running subprocess for av_unified_mvp stage 3.

Reads JSON-line requests from stdin, writes JSON-line responses to stdout.
Wraps librkllmrt.so via ctypes (no AGPL touched). Designed so a future
modules/llm_engine/rknn_backend.py can subprocess.Popen this daemon and talk
over stdin/stdout, mirroring the pattern used for SenseVoice RKNN ASR.

Protocol:
  Handshake (stdout):  {"ready": true, "load_ms": N, "rss_mb": N}
  Request  (stdin):    {"seq": N, "prompt": "...", "role": "user", "enable_thinking": false, "max_new_tokens": 200}
  Response (stdout):   {"seq": N, "text": "...", "first_token_ms": ms, "total_ms": ms,
                        "perf": {"prefill_time_ms":..., "prefill_tokens":..., "generate_time_ms":..., "generate_tokens":..., "memory_usage_mb":...}}
  Error    (stdout):   {"seq": N, "error": "msg"}
"""
import ctypes
import os
import sys
import time
import json
import logging
import threading
import resource

THIS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, THIS)

from smoke_test import (
    RKLLM_Handle_t, RKLLMParam, RKLLMInput, RKLLMInferParam,
    RKLLMResult, CALLBACK_TYPE,
    RKLLMInputType_PROMPT, RKLLMInferMode_GENERATE,
    LLMCallState_RKLLM_RUN_NORMAL,
    LLMCallState_RKLLM_RUN_FINISH,
    LLMCallState_RKLLM_RUN_ERROR,
)

logging.basicConfig(level=logging.WARNING, stream=sys.stderr,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# librkllmrt logs to stdout via printf — would clobber our JSON line protocol.
# We redirect fd 1 to stderr once init is done.
_real_stdout_fd = os.dup(1)
_real_stdout = os.fdopen(_real_stdout_fd, "w", buffering=1)

def _silence_stdout():
    """Redirect process-wide fd 1 to stderr so librkllmrt printf goes to stderr."""
    os.dup2(2, 1)
    sys.stdout = sys.stderr

def _say(obj):
    """Write one JSON line to the original stdout fd, then flush."""
    _real_stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    _real_stdout.flush()

# ----------------------------------------------------------------------------
# Inference state
# ----------------------------------------------------------------------------
class InferState:
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

STATE = InferState()

def callback_impl(result_ptr, userdata, state):
    try:
        if state == LLMCallState_RKLLM_RUN_NORMAL:
            if STATE.first_token_ms is None:
                STATE.first_token_ms = (time.monotonic() - STATE.start_ts) * 1000.0
            raw = result_ptr.contents.text
            if raw:
                STATE.text_chunks.append(raw.decode("utf-8", errors="replace"))
        elif state == LLMCallState_RKLLM_RUN_FINISH:
            p = result_ptr.contents.perf
            STATE.perf = {
                "prefill_time_ms": float(p.prefill_time_ms),
                "prefill_tokens": int(p.prefill_tokens),
                "generate_time_ms": float(p.generate_time_ms),
                "generate_tokens": int(p.generate_tokens),
                "memory_usage_mb": float(p.memory_usage_mb),
            }
            STATE.finish_event.set()
        elif state == LLMCallState_RKLLM_RUN_ERROR:
            STATE.error = "RKLLM_RUN_ERROR"
            STATE.finish_event.set()
    except Exception as e:
        STATE.error = f"callback_exception: {e!r}"
        STATE.finish_event.set()
    return 0

CALLBACK_FN = CALLBACK_TYPE(callback_impl)

def rss_mb():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0

# ----------------------------------------------------------------------------
# Init + run
# ----------------------------------------------------------------------------
def make_param(model_path, max_context_len=2048, max_new_tokens=512, platform="rk3588",
               top_k=1, top_p=0.9, temperature=0.8, repeat_penalty=1.1):
    p = RKLLMParam()
    p.model_path = model_path.encode("utf-8")
    p.max_context_len = max_context_len
    p.max_new_tokens = max_new_tokens
    p.skip_special_token = True
    p.n_keep = -1
    p.top_k = top_k
    p.top_p = top_p
    p.temperature = temperature
    p.repeat_penalty = repeat_penalty
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
    return p

def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=os.path.expanduser("~/rkllm-poc/artifacts/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"))
    ap.add_argument("--model", default=os.path.expanduser("~/rkllm-poc/artifacts/Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm"))
    ap.add_argument("--max-context-len", type=int, default=2048)
    ap.add_argument("--max-new-tokens", type=int, default=512)
    args = ap.parse_args()

    logging.info("loading lib %s", args.lib)
    lib = ctypes.CDLL(args.lib)
    lib.rkllm_init.argtypes = [ctypes.POINTER(RKLLM_Handle_t), ctypes.POINTER(RKLLMParam), CALLBACK_TYPE]
    lib.rkllm_init.restype = ctypes.c_int
    lib.rkllm_run.argtypes = [RKLLM_Handle_t, ctypes.POINTER(RKLLMInput), ctypes.POINTER(RKLLMInferParam), ctypes.c_void_p]
    lib.rkllm_run.restype = ctypes.c_int
    lib.rkllm_destroy.argtypes = [RKLLM_Handle_t]
    lib.rkllm_destroy.restype = ctypes.c_int

    # librkllmrt prints banner info to stdout during rkllm_init — silence fd 1
    # BEFORE init so it lands on stderr instead of corrupting the JSON-line
    # protocol on the original stdout (saved as _real_stdout_fd).
    _silence_stdout()

    param = make_param(args.model, args.max_context_len, args.max_new_tokens)
    handle = RKLLM_Handle_t()
    t0 = time.monotonic()
    rc = lib.rkllm_init(ctypes.byref(handle), ctypes.byref(param), CALLBACK_FN)
    load_ms = (time.monotonic()-t0)*1000.0
    if rc != 0:
        _say({"ready": False, "error": f"rkllm_init returned {rc}"})
        return 2

    _say({"ready": True, "load_ms": load_ms, "rss_mb": rss_mb()})

    # request loop — readline on the inherited python file object sys.stdin
    # (already a real fd, untouched by _silence_stdout which only swapped fd 1).
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        seq = 0
        try:
            req = json.loads(line)
            seq = req.get("seq", 0)
            prompt = req["prompt"]
            role = req.get("role", "user")
            enable_thinking = bool(req.get("enable_thinking", False))

            infer = RKLLMInferParam()
            ctypes.memset(ctypes.byref(infer), 0, ctypes.sizeof(RKLLMInferParam))
            infer.mode = RKLLMInferMode_GENERATE
            infer.lora_params = None
            infer.prompt_cache_params = None
            infer.keep_history = 0

            rin = RKLLMInput()
            rin.role = role.encode("utf-8")
            rin.enable_thinking = enable_thinking
            rin.input_type = RKLLMInputType_PROMPT
            rin.input_data.prompt_input = prompt.encode("utf-8")

            STATE.reset()
            rc = lib.rkllm_run(handle, ctypes.byref(rin), ctypes.byref(infer), None)
            if not STATE.finish_event.is_set():
                STATE.finish_event.wait(timeout=2.0)
            total_ms = (time.monotonic()-STATE.start_ts)*1000.0

            if STATE.error:
                _say({"seq": seq, "error": STATE.error, "rc": int(rc)})
            else:
                _say({
                    "seq": seq,
                    "text": "".join(STATE.text_chunks),
                    "first_token_ms": STATE.first_token_ms,
                    "total_ms": total_ms,
                    "rc": int(rc),
                    "perf": STATE.perf,
                })
        except Exception as e:
            _say({"seq": seq, "error": f"daemon_exception: {e!r}"})

    lib.rkllm_destroy(handle)
    return 0

if __name__ == "__main__":
    sys.exit(main())
