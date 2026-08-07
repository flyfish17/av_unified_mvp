# P0-b NPU 部署指引（给终端，2026-07-28 主 Claude 联网整理）

> 目的：把纪要 LLM 从 3588 CPU（900s 超时）迁到 NPU。路径已查通，终端照此做，以实际 SDK/README 为准，**先跑通小模型再上 4B**。

---

## 前提 / 版本
- **RKLLM v1.3.0**（最新）已支持 **qwen3.5**（v1.2.3 起）。RK3588 三 NPU 核，仅 **W8A8** 量化。
- 两阶段：PC 端 `rkllm-toolkit` 转换 → 板上 `RKLLM Runtime` 推理。
- 官方：`github.com/airockchip/rknn-llm`（SDK + rkllm_model_zoo 预转换库，fetch code: rkllm）。

## ⭐ 优先复用：3588 已有 rkllm-poc（2026-07-28 主 Claude ssh 实查）
`~/rkllm-poc` 是既有 NPU LLM POC，**NPU 调用链路已跑通，别从零装**：
- **现成资产**：`daemon/rkllm_daemon.py` 用 ctypes 调 `librkllmrt`（`rkllm_init`/`rkllm_run`）；`artifacts/Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm` 已验证可加载推理；接口 = stdin/stdout JSON（`{prompt,max_new_tokens}`）。环境/驱动/ctypes 绑定都现成。
- **P0-b 要补的三个缺口**：① 模型 1.5B → **4B**（纪要质量，转/拉 Qwen3-4B W8A8）；② `max_context_len 2048` → **16k**（纪要长输入，2 万字≈12.6k token）；③ stdin/stdout → **HTTP**（av `_call_ollama_summary` 接入）。
- **复用路径（省掉环境搭建）**：保留 daemon 的 rkllm 调用核 → 换 4B-16k 模型 → 套一层 HTTP（自己加 Flask，或把 poc 调用核塞进 RKLLM-API-Server 的 server 框架）。
- ⚠️ daemon（PID 2975，7/27 起）在跑，动它前先确认有无依赖；扩 context 到 16k 要**实测 NPU 内存**（4B W8A8 + 16k KV cache，16G 够不够）。

## 🚨 下载卡点解决 + 最快验证路（2026-07-29 主 Claude 联网查证）
**当前卡点**：4B .rkllm 从 HF/hf-mirror 下载中断（Mac 缓存 2.9G / 5.3GB，无活跃下载进程）。代码侧 P0-b 已完成（commit d87be0c 后端可切 rkllm），**只差模型到位**。

**解法（按推荐序）**：
1. **⭐ 最快验证路（不等 4B）**：板上现成 `Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm` 直接跑通 NPU 纪要链路（rkllm-poc daemon），用**短样本**（<2000 token，配现 context 2048）测 prefill/decode tok/s，外推 2 万字 → **先拿到"NPU 能否 ~2min"的答案**，回答产品卖点问题；4B 质量后补。（注：1.5B daemon PID 2975 在跑，测速可复用其 stdin/stdout 协议。）
2. **换国内源拉 4B**：modelscope（魔搭）拉**原始 Qwen3-4B 权重**（国内快）→ 本地 `rkllm-toolkit v1.2.1b1` 自转 W8A8：`export_rkllm.py --target-platform rk3588 --num_npu_core 3 --quantized_dtype w8a8 --max-context-len 16384`（**16k 必须转换时指定**）。可能比等 HF 下现成 .rkllm 快。
3. **续传/换现成 .rkllm**：HF `kamyarkazemi1373/Qwen3-4B-W8A8-RK3588` 或 `randomblock1/Qwen3-4B-Instruct-2507-rk3588`（16k 版）——都是转好的，续传或换镜像。
- 参考：CSDN/博客园/魔乐社区有完整 Qwen3-4B RK3588 转换流程（中文）；RKLLM Toolkit v1.2.1b1 确认支持 Qwen3-0.6B/1.7B/4B。

## ⚠️ 内存约束实测（2026-07-29 主 Claude 触发 OOM 发现）
主 Claude 测 NPU `qwen3-4b-16k` 出**全量 2 万字**(12.6k token)纪要 → **253s 连接断 + 触发 OOM killer 杀 ollama**（已 systemd 自愈，生产无损）。
- **根因**：16G 内存下 NPU(4B-16k ~5GB 模型 + 16k KV) + ollama(qwen3.5:4b ~5.7GB) + 视听(video/FunASR) **三者同跑内存不足**。
- **P0-b 必做的内存管理**：换 NPU 后**下线 ollama**（`systemctl stop ollama`，省 5.7GB）+ `meeting_asr` profile 关视频链路；NPU 纪要跑完调 `/v1/models/unload` 释放。**三者不能同时占内存**。
- **全量 vs 分段**：即使 NPU，全量 12.6k token 的 KV cache 也吃内存；先在"停 ollama + 关视频"的**干净环境**测全量能否成，不成则 NPU 也走分段。
- **待终端**：干净环境（停 ollama + 关视频）下测 NPU 4B 出纪要**真实耗时/tok/s**——这才是 CR-DIG7201 卖点的准数。
- ⚠️ **教训**：勿在生产满载时对 NPU 发大请求（会 OOM 连累 ollama/视听）。

## 三步（若不复用 poc、从零走官方，参考）

### ① 拿模型（二选一）
- **省事**：拉现成 `randomblock1/Qwen3-4B-Instruct-2507-rk3588`（**选 16k context 版**，覆盖 2 万字会议≈12.6k token）。
- **自转**：PC 端 rkllm-toolkit 把 qwen3.5:4b 转 `qwen3.5-4b_w8a8_rk3588.rkllm`（Python 3.10/3.11）。先用官方 0.8b 示例跑通流程再转 4B。

### ② 起 OpenAI 兼容 server
用 `GatekeeperZA/RKLLM-API-Server`（现成、OpenAI 兼容、有 unload）：
```bash
git clone https://github.com/GatekeeperZA/RKLLM-API-Server.git && cd RKLLM-API-Server
./setup.sh                       # 自动装依赖+RKLLM运行时+systemd
mkdir -p ~/models/Qwen3-4B-16k   # 放 .rkllm，文件名带 -16k 让 server 自动识别 context
# 起服务（单 worker，NPU 一次一模型）：
gunicorn -w 1 -k gthread --threads 4 --timeout 300 -b 0.0.0.0:8000 api:app
```
- 依赖：RKNPU 驱动 ≥0.9.6、RKLLM runtime v1.2.0+、`librkllmrt.so` 装进 /usr/lib。
- 端点：`/v1/chat/completions`、`/v1/models`、`/v1/models/unload`、`/health`。

### ③ 接入 av（`web/server.py`）
- `_call_ollama_summary` 加配置项 `summary_backend: ollama|rkllm` + `summary_url`。
- ⚠️ **接口差异坑**：ollama 用 `/api/generate`（completion 风格，`prompt` 字段）；RKLLM-API-Server 是 `/v1/chat/completions`（chat 风格，`messages` 数组）。接 rkllm 时把 prompt 包成 `messages:[{role:user,content:PROMPT}]`，解析 `choices[0].message.content`。
- `_extract_json` 容错逻辑复用（rkllm 输出同样要提 JSON）。

---

## 两个关键利好（查证发现）
1. **`/v1/models/unload` 解决 NPU 争抢**：纪要是会后跑 → 跑完调 unload 释放 NPU 内存 → 会中 NPU 还给 scene_analyzer VLM。**时序错开 + 显式卸载**，之前担心的"纪要与视频抢 NPU"有解。
2. **KV cache 增量**：多轮后续 ~50ms；纪要是单次长 prompt，主要吃 prefill（~130 tok/s），一次约 1.5-2min。

## 终端必须实测的（验收数据）
1. NPU 真实 prefill 耗时：`/tmp/dingna_transcript.txt`（2 万字）→ 记录出纪要总耗时（目标 <3min，估算 ~2min）。
2. **纪要质量对比 Mac 基线**（W8A8 vs Mac Q4，看有无明显退化）：基线见 iCloud `丁娜/纪要算力对比测试-20260728.md`。
3. 16k context 对 2 万字是否够（12.6k token 输入 + prompt + 输出，贴顶就要分段）。
4. NPU 内存占用（4B W8A8 约 4-5GB，16G 够）+ unload 后释放是否干净。

## 资源
- airockchip/rknn-llm（SDK/model_zoo/官方 server 示例）
- GatekeeperZA/RKLLM-API-Server（OpenAI 兼容 server）
- HF: randomblock1/Qwen3-4B-Instruct-2507-rk3588（现成 4k/16k）
- Radxa RKLLM Usage 文档
