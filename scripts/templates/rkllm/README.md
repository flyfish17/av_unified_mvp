# RKLLM templates for RK3588 NPU

阶段 3 漏斗第 2 层 NPU 后端的运行时脚本模板。被 `modules/llm_engine/rknn_backend.py` 通过 subprocess 拉起；本仓库不直接 import。

## 文件

| 文件 | 用途 |
|---|---|
| `rkllm_daemon.py` | 常驻 daemon（stdin/stdout JSON 协议），仓库内 `rknn_backend.py` subprocess 调用 |
| `smoke_test.py` | librkllmrt ctypes 绑定 + 单 prompt smoke（daemon 复用其 binding 定义） |
| `benchmark.py` | NPU N-prompt 性能测试 |
| `ollama_bench.py` | 同 prompt 跑 ollama CPU 做 baseline 对比 |
| `daemon_client_test.py` | daemon 压测客户端 |
| `prompts.json` | 9 prompt 测试集（short / medium / long_intent） |

## 部署到 3588

```bash
# 一次性同步
rsync -av scripts/templates/rkllm/ firefly@192.168.5.6:~/rkllm-poc/daemon/

# 模型 + SDK 不在仓库内，需单独准备：
#   ~/rkllm-poc/artifacts/rknn-llm/                          (Apache 2.0)
#   ~/rkllm-poc/artifacts/Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm
# 见 docs/deploy/3588-npu.md（待补 LLM 段）。
```

## 协议（daemon stdin/stdout JSON 行）

```
Handshake (stdout): {"ready": true, "load_ms": N, "rss_mb": N}
Request   (stdin):  {"seq": N, "prompt": "...", "role": "user", "enable_thinking": false, "max_new_tokens": 200}
Response  (stdout): {"seq": N, "text": "...", "first_token_ms": ms, "total_ms": ms,
                     "perf": {"prefill_time_ms":..., "generate_tokens":..., "memory_usage_mb":...}}
Error     (stdout): {"seq": N, "error": "..."}
```

## License

- `rknn-llm` SDK (librkllmrt) — **Apache 2.0**，商用可用
- 官方 Qwen2.5-1.5B-Instruct 权重（Alibaba） — **Apache 2.0**（Qwen 2.5 系列已换 Apache，与 1.5/2 系列的 Tongyi Qianwen 不同）
- HF 上 `workholic7228/Qwen2.5-1.5B-Instruct_W8A8_RK3588` 预转模型 — 页面 gated 401 未显式声明 license ⚠️ 法理上继承上游 Apache 2.0，但商用合规举证困难
- 备选预转：`c01zaut/Qwen2.5-1.5B-Instruct-RK3588-1.1.4` 显式 Apache 2.0（SDK 1.1.4 转，runtime 兼容性需测）
- 详见 `docs/deploy/3588-npu.md` § 10.9
