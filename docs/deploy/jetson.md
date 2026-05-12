# Jetson Orin Nano 部署 SOP

> **状态**：占位文档。Jetson 是 3588 的硬件平行验证 + 高视觉版备选，完整 PoC 经验在 `DEVELOPMENT_PLAN.md` § 2026-05-11 双线推进。

## Jetson 实测数据（5/11–5/12）

| 项 | 数据 |
|---|---|
| 平台 | Jetson Orin Nano，JetPack 6.1，CUDA 12.6 |
| SSH | `jetson@192.168.5.51`（密码 yahboom）|
| RAM | 7.4 GB unified + 11 GB swap |
| SenseVoiceSmall 加载（device=cuda）| **3.9s** |
| SenseVoiceSmall 5 wav CER eval avg_rtf | **0.045**（CUDA fp16，单条 263-269 ms 极稳）|
| SenseVoiceSmall 端到端实测 | ~500ms（含 VAD + MQTT）|
| 内存运行余量 | 1.94 GB（紧张）+ 6.4 GB swap 在用 |
| uptime | 34 天 23h（5/12 重启了一次用上 quirk filter）|
| ollama 模型库 | 9 个 / 30GB（含视觉 4 个：llava-phi3:3.8b、qwen2.5vl:3b、minicpm-v:8b、gemma3:4b 等）|

## 当前已有的 Jetson 知识在哪

1. **PoC 一路踩坑**：`DEVELOPMENT_PLAN.md` § 2026-05-11 双线推进 — CUDA 驱动 12.6 vs torch 2.11+cu130 不兼容、torchaudio ABI 与 NVIDIA torch 不合、源编 USE_CUDA=0 绕开 CUDA CTC decoder 缺 `<cfloat>` 头等
2. **关键修法**：卸装 user-level torch + nvidia/*（释放 3GB），自动激活 `/usr/local/lib/python3.10/dist-packages/torch 2.5.0a0+nv24.08`；源编 torchaudio v2.5.0 走 `USE_CUDA=0`；源码 tarball 走 `gh-proxy.com` CN 代理拉 GitHub
3. **processor_arm.py 多平台自适应**：commit `4b79332` — mic 加 WebCamera/USB Audio 名匹配（Yahboom OEM）、模型路径默认按主机自适应（3588 路径不存在 → `~/models/SenseVoiceSmall`）、AutoModel device 自动（torch.cuda 真就 GPU）
4. **quirk filter 同源**：5/12 把 3588 的 `min_text_chars=2` 过滤同步到 Jetson — 同一份 `processor_arm.py` 同款代码
5. **完整角色定位**：[`../roadmap/liaohe-3588.md`](../roadmap/liaohe-3588.md) § 风险/退出条件 — Jetson 是 3588 不过阈值时的备选 #1，现已平行验证过线

## 何时单独抽这份 SOP

视觉 NPU 二期启动时（用 Jetson CUDA 跑视觉模型 / VLM 演示）— 那时 Jetson 不再只是"3588 备选"，而成"高端视觉版"独立角色，SOP 需要独立。
