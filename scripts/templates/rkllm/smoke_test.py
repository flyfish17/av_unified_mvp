#!/usr/bin/env python3
"""
RKLLM smoke test - loads .rkllm model on RK3588 NPU and runs a single prompt.

Bindings extracted from rknn-llm v1.2.3 examples/rkllm_server_demo/rkllm_server/flask_server.py.
This wrapper is a minimal subset (no lora / prompt_cache / tools / multimodal).
"""
import ctypes
import os
import sys
import time
import argparse
import threading

# -----------------------------------------------------------------------------
# ctypes bindings
# -----------------------------------------------------------------------------
RKLLM_Handle_t = ctypes.c_void_p

LLMCallState_RKLLM_RUN_NORMAL  = 0
LLMCallState_RKLLM_RUN_WAITING = 1
LLMCallState_RKLLM_RUN_FINISH  = 2
LLMCallState_RKLLM_RUN_ERROR   = 3

RKLLMInputType_PROMPT = 0
RKLLMInferMode_GENERATE = 0


class RKLLMExtendParam(ctypes.Structure):
    _fields_ = [
        ("base_domain_id", ctypes.c_int32),
        ("embed_flash", ctypes.c_int8),
        ("enabled_cpus_num", ctypes.c_int8),
        ("enabled_cpus_mask", ctypes.c_uint32),
        ("n_batch", ctypes.c_uint8),
        ("use_cross_attn", ctypes.c_int8),
        ("reserved", ctypes.c_uint8 * 104),
    ]


class RKLLMParam(ctypes.Structure):
    _fields_ = [
        ("model_path", ctypes.c_char_p),
        ("max_context_len", ctypes.c_int32),
        ("max_new_tokens", ctypes.c_int32),
        ("top_k", ctypes.c_int32),
        ("n_keep", ctypes.c_int32),
        ("top_p", ctypes.c_float),
        ("temperature", ctypes.c_float),
        ("repeat_penalty", ctypes.c_float),
        ("frequency_penalty", ctypes.c_float),
        ("presence_penalty", ctypes.c_float),
        ("mirostat", ctypes.c_int32),
        ("mirostat_tau", ctypes.c_float),
        ("mirostat_eta", ctypes.c_float),
        ("skip_special_token", ctypes.c_bool),
        ("is_async", ctypes.c_bool),
        ("img_start", ctypes.c_char_p),
        ("img_end", ctypes.c_char_p),
        ("img_content", ctypes.c_char_p),
        ("extend_param", RKLLMExtendParam),
    ]


class RKLLMEmbedInput(ctypes.Structure):
    _fields_ = [("embed", ctypes.POINTER(ctypes.c_float)), ("n_tokens", ctypes.c_size_t)]


class RKLLMTokenInput(ctypes.Structure):
    _fields_ = [("input_ids", ctypes.POINTER(ctypes.c_int32)), ("n_tokens", ctypes.c_size_t)]


class RKLLMMultiModalInput(ctypes.Structure):
    _fields_ = [
        ("prompt", ctypes.c_char_p),
        ("image_embed", ctypes.POINTER(ctypes.c_float)),
        ("n_image_tokens", ctypes.c_size_t),
        ("n_image", ctypes.c_size_t),
        ("image_width", ctypes.c_size_t),
        ("image_height", ctypes.c_size_t),
    ]


class RKLLMInputUnion(ctypes.Union):
    _fields_ = [
        ("prompt_input", ctypes.c_char_p),
        ("embed_input", RKLLMEmbedInput),
        ("token_input", RKLLMTokenInput),
        ("multimodal_input", RKLLMMultiModalInput),
    ]


class RKLLMInput(ctypes.Structure):
    _fields_ = [
        ("role", ctypes.c_char_p),
        ("enable_thinking", ctypes.c_bool),
        ("input_type", ctypes.c_int),
        ("input_data", RKLLMInputUnion),
    ]


class RKLLMLoraParam(ctypes.Structure):
    _fields_ = [("lora_adapter_name", ctypes.c_char_p)]


class RKLLMPromptCacheParam(ctypes.Structure):
    _fields_ = [("save_prompt_cache", ctypes.c_int), ("prompt_cache_path", ctypes.c_char_p)]


class RKLLMInferParam(ctypes.Structure):
    _fields_ = [
        ("mode", ctypes.c_int),
        ("lora_params", ctypes.POINTER(RKLLMLoraParam)),
        ("prompt_cache_params", ctypes.POINTER(RKLLMPromptCacheParam)),
        ("keep_history", ctypes.c_int),
    ]


class RKLLMResultLastHiddenLayer(ctypes.Structure):
    _fields_ = [
        ("hidden_states", ctypes.POINTER(ctypes.c_float)),
        ("embd_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class RKLLMResultLogits(ctypes.Structure):
    _fields_ = [
        ("logits", ctypes.POINTER(ctypes.c_float)),
        ("vocab_size", ctypes.c_int),
        ("num_tokens", ctypes.c_int),
    ]


class RKLLMPerfStat(ctypes.Structure):
    _fields_ = [
        ("prefill_time_ms", ctypes.c_float),
        ("prefill_tokens", ctypes.c_int),
        ("generate_time_ms", ctypes.c_float),
        ("generate_tokens", ctypes.c_int),
        ("memory_usage_mb", ctypes.c_float),
    ]


class RKLLMResult(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_char_p),
        ("token_id", ctypes.c_int),
        ("last_hidden_layer", RKLLMResultLastHiddenLayer),
        ("logits", RKLLMResultLogits),
        ("perf", RKLLMPerfStat),
    ]


CALLBACK_TYPE = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(RKLLMResult), ctypes.c_void_p, ctypes.c_int)


# -----------------------------------------------------------------------------
# Streaming receiver
# -----------------------------------------------------------------------------
class Stream:
    def __init__(self):
        self.text_chunks = []
        self.first_token_ms = None
        self.finish_event = threading.Event()
        self.start_ts = None
        self.error = None
        self.perf = None  # snapshot RKLLMPerfStat copy

    def reset(self, start_ts):
        self.text_chunks = []
        self.first_token_ms = None
        self.finish_event.clear()
        self.start_ts = start_ts
        self.error = None
        self.perf = None


STREAM = Stream()


def callback_impl(result_ptr, userdata, state):
    try:
        if state == LLMCallState_RKLLM_RUN_NORMAL:
            if STREAM.first_token_ms is None:
                STREAM.first_token_ms = (time.monotonic() - STREAM.start_ts) * 1000.0
            raw = result_ptr.contents.text
            if raw:
                STREAM.text_chunks.append(raw.decode("utf-8", errors="replace"))
        elif state == LLMCallState_RKLLM_RUN_FINISH:
            perf = result_ptr.contents.perf
            # copy fields out of the ctypes struct before it gets freed
            STREAM.perf = {
                "prefill_time_ms": perf.prefill_time_ms,
                "prefill_tokens": perf.prefill_tokens,
                "generate_time_ms": perf.generate_time_ms,
                "generate_tokens": perf.generate_tokens,
                "memory_usage_mb": perf.memory_usage_mb,
            }
            STREAM.finish_event.set()
        elif state == LLMCallState_RKLLM_RUN_ERROR:
            STREAM.error = "RKLLM_RUN_ERROR"
            STREAM.finish_event.set()
    except Exception as e:
        STREAM.error = f"callback_exception: {e}"
        STREAM.finish_event.set()
    return 0


CALLBACK_FN = CALLBACK_TYPE(callback_impl)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lib", default=os.path.expanduser("~/rkllm-poc/artifacts/rknn-llm/rkllm-runtime/Linux/librkllm_api/aarch64/librkllmrt.so"))
    ap.add_argument("--model", default=os.path.expanduser("~/rkllm-poc/artifacts/Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm"))
    ap.add_argument("--prompt", default="你好")
    ap.add_argument("--max-new-tokens", type=int, default=64)
    ap.add_argument("--max-context-len", type=int, default=512)
    ap.add_argument("--platform", default="rk3588")
    ap.add_argument("--enable-thinking", action="store_true")
    args = ap.parse_args()

    print(f"[*] lib  : {args.lib}")
    print(f"[*] model: {args.model}")
    print(f"[*] prompt: {args.prompt!r}")

    t_load_start = time.monotonic()
    lib = ctypes.CDLL(args.lib)
    print(f"[*] dlopen: {(time.monotonic()-t_load_start)*1000:.1f} ms")

    param = RKLLMParam()
    param.model_path = args.model.encode("utf-8")
    param.max_context_len = args.max_context_len
    param.max_new_tokens = args.max_new_tokens
    param.skip_special_token = True
    param.n_keep = -1
    param.top_k = 1
    param.top_p = 0.9
    param.temperature = 0.8
    param.repeat_penalty = 1.1
    param.frequency_penalty = 0.0
    param.presence_penalty = 0.0
    param.mirostat = 0
    param.mirostat_tau = 5.0
    param.mirostat_eta = 0.1
    param.is_async = False
    param.img_start = b""
    param.img_end = b""
    param.img_content = b""
    param.extend_param.base_domain_id = 0
    param.extend_param.embed_flash = 1
    param.extend_param.n_batch = 1
    param.extend_param.use_cross_attn = 0
    param.extend_param.enabled_cpus_num = 4
    if args.platform.lower() in ("rk3588", "rk3576"):
        # big cores 4-7
        param.extend_param.enabled_cpus_mask = (1 << 4) | (1 << 5) | (1 << 6) | (1 << 7)
    else:
        param.extend_param.enabled_cpus_mask = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3)

    lib.rkllm_init.argtypes = [ctypes.POINTER(RKLLM_Handle_t), ctypes.POINTER(RKLLMParam), CALLBACK_TYPE]
    lib.rkllm_init.restype = ctypes.c_int

    lib.rkllm_run.argtypes = [RKLLM_Handle_t, ctypes.POINTER(RKLLMInput), ctypes.POINTER(RKLLMInferParam), ctypes.c_void_p]
    lib.rkllm_run.restype = ctypes.c_int

    lib.rkllm_destroy.argtypes = [RKLLM_Handle_t]
    lib.rkllm_destroy.restype = ctypes.c_int

    handle = RKLLM_Handle_t()
    print("[*] rkllm_init ...")
    t_init_start = time.monotonic()
    rc = lib.rkllm_init(ctypes.byref(handle), ctypes.byref(param), CALLBACK_FN)
    t_init_ms = (time.monotonic() - t_init_start) * 1000.0
    if rc != 0:
        print(f"[!] rkllm_init returned {rc}")
        return 1
    print(f"[*] rkllm_init: {t_init_ms:.0f} ms")

    infer = RKLLMInferParam()
    ctypes.memset(ctypes.byref(infer), 0, ctypes.sizeof(RKLLMInferParam))
    infer.mode = RKLLMInferMode_GENERATE
    infer.lora_params = None
    infer.prompt_cache_params = None
    infer.keep_history = 0

    rkllm_input = RKLLMInput()
    rkllm_input.role = b"user"
    rkllm_input.enable_thinking = bool(args.enable_thinking)
    rkllm_input.input_type = RKLLMInputType_PROMPT
    rkllm_input.input_data.prompt_input = args.prompt.encode("utf-8")

    print(f"[*] rkllm_run prompt={args.prompt!r} ...")
    STREAM.reset(time.monotonic())
    rc = lib.rkllm_run(handle, ctypes.byref(rkllm_input), ctypes.byref(infer), None)
    # rkllm_run is sync; callback events all delivered by now and finish_event set.
    total_ms = (time.monotonic() - STREAM.start_ts) * 1000.0
    if rc != 0:
        print(f"[!] rkllm_run returned {rc}")
    if not STREAM.finish_event.is_set():
        # safety: wait a moment in case any callback is pending
        STREAM.finish_event.wait(timeout=2.0)

    full_text = "".join(STREAM.text_chunks)
    print("-" * 60)
    print("RESPONSE:")
    print(full_text)
    print("-" * 60)
    print(f"first_token_ms : {STREAM.first_token_ms}")
    print(f"total_ms       : {total_ms:.1f}")
    if STREAM.perf:
        p = STREAM.perf
        tps = (p["generate_tokens"] / (p["generate_time_ms"]/1000.0)) if p["generate_time_ms"] > 0 else 0.0
        print(f"perf.prefill   : {p['prefill_time_ms']:.1f} ms / {p['prefill_tokens']} tokens")
        print(f"perf.generate  : {p['generate_time_ms']:.1f} ms / {p['generate_tokens']} tokens  ({tps:.2f} tok/s)")
        print(f"perf.memory_mb : {p['memory_usage_mb']:.1f}")
    if STREAM.error:
        print(f"error          : {STREAM.error}")

    print("[*] rkllm_destroy ...")
    lib.rkllm_destroy(handle)
    return 0 if not STREAM.error else 2


if __name__ == "__main__":
    sys.exit(main())
