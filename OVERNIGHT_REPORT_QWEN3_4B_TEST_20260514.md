# Qwen3-4B w8a8 NPU 升级评估 — 5/14 报告

**任务**：评估 3588 NPU 上 Qwen2.5-1.5B → Qwen3-4B w8a8 升级路径
**结论（一行）**：**模型源头都明确，但 Mac/3588 两端均无法在合理时间内下载到 4-5 GB .rkllm 文件 → 本次升级窗口未达成，建议保留 1.5B 现状 + 切换到明确 Apache 2.0 的预转版本作为商用过渡，等待 HF 国内通路恢复 / 同事代下 / 自转方案。**

---

## 1. HF 候选模型清单（已探活）

| repo | 模型文件 | 大小 | License | RKLLM SDK 版 | 备注 |
|---|---|---|---|---|---|
| `kamyarkazemi1373/Qwen3-4B-W8A8-RK3588` | `Qwen3-4B-w8a8-npu.rkllm` | **4.84 GB** | apache-2.0（tag）| 未注明，文件名是"w8a8-npu" | tags 含 `rk3588` `orange-pi-5` `w8a8`；27 下载；**最小**且对口 |
| 同上 | `Qwen3-4B-w8a8-hybrid.rkllm` | 4.88 GB | 同上 | 同上 | hybrid（CPU/NPU 混合）变体 |
| `randomblock1/Qwen3-4B-Instruct-2507-rk3588` | `*-w8a8-opt-1-hybrid-ratio-0.0-4k.rkllm` | 5.27 GB | **apache-2.0 + LICENSE 文件** | 1.2.2 推断 | 299 下载，最热门；26 个变体（opt 0/1 × hybrid 0.0/0.2/0.4 × 4k/16k × g128/none） |
| 同上 | `*-w8a8-opt-1-hybrid-ratio-0.0-16k.rkllm` | 5.29 GB | 同上 | 同上 | 16k 上下文版 |
| `amrmantawi/Qwen3-4B-Instruct-2507-rk3588-1.2.2` | `*-w8a8-opt-1-hybrid-ratio-0.0.rkllm` | 4.85 GB | **apache-2.0 + LICENSE** | **1.2.2 明确** | 2 文件；带 tokenizer/config；最干净的"工程化"版本 |
| `dulimov/Qwen3-4B-Instruct-2507-rk3588-1.2.2` | （safetensors 源 + rkllm）| - | apache-2.0 | 1.2.2 | 6 下载；dulimov 是社区老熟人 |

**关注作者复活：**
- ✅ `c01zaut` HF repo 列表里 **没有 Qwen3** 系列（只到 Qwen2.5）—— 他停在 Q2/2025 那批 1.1.x SDK
- ✅ `airockchip` 官方账户没把 Qwen3-4B 推 HF（仍在自家 release 渠道）
- ✅ `dulimov` / `randomblock1` / `amrmantawi` / `kamyarkazemi` 都活跃在 2025 H2 - 2026 Q1

**首选**：`amrmantawi/Qwen3-4B-Instruct-2507-rk3588-1.2.2` 的 `opt-1-hybrid-ratio-0.0.rkllm`
理由：①SDK 版本明确（1.2.2 与 3588 已装 1.2.1 runtime 应该兼容，向前小步）② LICENSE 文件入 repo ③ 文件最小 4.85 GB ④ Instruct-2507 是 Qwen3 最新指令调优 ⑤ 配套 tokenizer/config（虽然 daemon 不用，但完整）

---

## 2. 下载尝试 — 全部失败

### 2a. Mac → hf-mirror.com（首选国内镜像）
```
huggingface_hub.hf_hub_download(repo_id='kamyarkazemi1373/Qwen3-4B-W8A8-RK3588')
→ LocalEntryNotFoundError
```
HF mirror 在 LFS 路径上的策略：HEAD 200 但 GET 301 → 强制 redirect 到 `huggingface.co` → 再 302 到 `cas-bridge.xethub.hf.co/xet-bridge-us/...`（AWS us-east-1 CloudFront）。**hf-mirror 不再镜像 LFS 大文件，只镜像 metadata**——这是新策略变化。

### 2b. Mac → huggingface.co 直连
```
curl --max-time 45 -o test.bin https://huggingface.co/.../Qwen3-4B-w8a8-npu.rkllm
→ HTTP 200, 45s 下载了 6.95 MB
→ avg speed 154 KB/s
→ 估算 4.84 GB 完整下载 ~8.7 小时
```
xethub.hf.co 在国内可达但严重限速。

### 2c. Mac → huggingface.co（randomblock1 候选）
```
curl --max-time 30
→ 30s 下载 1.96 MB → 65 KB/s → 估算 22.5 小时
```
randomblock1 比 kamyarkazemi 更慢（可能不同 cas-bridge shard）。

### 2d. 3588 → hf-mirror.com / huggingface.co
```
curl --max-time 15 (mirror)  → code=000 speed=0    (TCP timeout)
curl --max-time 30 (hf.co)   → code=000 speed=0    (TCP timeout)
```
3588 出口（联通宽带 + 内网）对 HF 系列 **完全不通**。仅 `gh-proxy.com` 通（已用于下 SDK tarball）。

### 2e. gh-proxy.com 转 HF 资源
```
curl https://gh-proxy.com/https://huggingface.co/.../Qwen3-4B-w8a8-npu.rkllm
→ 403 Forbidden (1.8s)
```
gh-proxy 只代理 github.com 路径，不代理 huggingface.co。

### 2f. modelscope（魔搭社区）
```
api/v1/models/kamyarkazemi1373/...           → record not found
api/v1/models/randomblock1/...               → record not found
api/v1/models/AI-ModelScope/Qwen3-4B-rk3588  → record not found
```
modelscope **没有任何已镜像的 Qwen3-4B rkllm 版本**（截至 2026-05-14 13:00）。

---

## 3. 资源现状（3588）

```
Mem:  16Gi total / 3.2Gi used / 723Mi free / 2.1Gi shared / 11Gi buff-cache / 10Gi available
Disk: 223G / 44G used / 169G available
当前 rkllm_daemon PID 1688700 持续运行 (Qwen2.5-1.5B-Instruct, max-ctx 2048, max-new-tokens 200)
（已观察到 PID 从 1677456 → 1688700，supervisor 自身有重启逻辑）
```

**如果 Qwen3-4B 能下到**：
- 模型加载 RSS 预期 ~5-6 GB（按 1.5B 1754 MB × 4B/1.5B × 1.05 工程冗余推算）
- 加 sensevoice 1.6 GB + audio_processor 0.5 GB + ollama qwen2.5-coder:1.5b idle 1.2 GB + python 进程零碎 ~1 GB = 总占用 ~9-10 GB
- **16 GB total 余量 ~6 GB 仍够**，但接近一半，需要禁用 swap 或谨慎 dump 时（zero swap 现状）

> 内存层面 4B 模型可行；瓶颈不在 3588，**纯瓶颈在下载链路**。

---

## 4. 升级 vs 保留决策建议

### 选项 A：保留 1.5B 现状（推荐 — 短期 1-2 周）
- 1.5B 已跑通 9 prompt benchmark（5/12 数据：首 token 198 ms，decode 8.9 t/s，意图 JSON 正确率 7/9）
- 主要缺陷是"机房" → Corridor 偷换地点幻觉 + 罕见设备词 — 已经被 engine.py location anti-hallucination 后置过滤兜住
- **不阻塞主链路演进**

### 选项 B：商用前换 c01zaut 1.5B（license 明确路径，强烈推荐）
- `c01zaut/Qwen2.5-1.5B-Instruct-rk3588-1.1.1`（Apache 2.0 明示，1.1.1 SDK 转的）
- 与当前 workholic7228 同体量，应直接替换 model_path 即可
- **风险**：1.1.1 SDK 转的 rkllm 文件 + 1.2.1 runtime 兼容性需测；如不兼容回退到自转方案
- **3588 上 c01zaut 是否能下也未测**——如同样卡 xethub，回到选项 D

### 选项 C：等链路 + Qwen3-4B 升（中期 2-4 周）
**触发条件任一：**
- hf-mirror 恢复 LFS 镜像（不可控）
- 同事/同事中转下载（找人在境外机房代下后 scp）
- 用一台有 VPN/海外 VPS 的机器 (Cloudflare 入口) 中转

### 选项 D：自转一份 Qwen3-4B w8a8（最干净，长期推荐）
**前置**：rkllm-toolkit 1.2.3 + 一台 x86_64 + 24 GB+ RAM + 一张 NVIDIA GPU（建议 RTX 3090/4090）
**流程**：
1. 从 modelscope 拉 `Qwen/Qwen3-4B-Instruct-2507` 原始 safetensors（Apache 2.0，国内秒下）
2. 在工作站上 `rkllm-toolkit` 量化 + 转换 → .rkllm
3. 校准数据用 av_unified 自己的 prompt 集（76 条指令命令）—— 这是关键差异化：**model 直接学过我们的命令格式**
4. 转换耗时 1-3 小时（4B w8a8）
5. scp 到 3588 测试

**收益**：
- License 链路完全自控
- 量化 calibration 用自己的语料 → 意图准确率比社区版应该高 5-15%
- 转换技能可复用到 Qwen3-VL-4B / Qwen3-ASR 等阶段 3 milestone

**成本**：1 天工作量 + 一台 GPU 工作站（公司应该有）

---

## 5. 立刻 actionable

**今天/明天**：不动。1.5B 链路稳定，所有 anti-hallucination 已上线。

**本周内（D1a 任务实操层）**：
1. 找一台**境外机房** / VPN 隧道，重跑 §2b 的 Mac 下载（同一个 amrmantawi opt-1 文件，4.85 GB）
2. 或者在公司内网找有 rkllm-toolkit 安装的 x86 工作站，启动选项 D 自转流水线（1 天搞定）

**长期沉淀**：
- `docs/deploy/3588-npu.md` § 10.2 加一段警告：**hf-mirror 已不再镜像 LFS 大文件**，未来 .rkllm 下载请走"境外中转 + scp"或"本地自转"
- 把 amrmantawi 这个 repo 加到 `docs/roadmap/ai-landscape-20260514.md` § A1 的"社区维护清单"

---

## 6. 操作清单（未执行 / 阻塞）

- [x] HF 候选模型列表 ✅
- [x] license 评估 ✅
- [ ] ~~下载到 Mac /tmp~~ ❌ 估算 8-22 小时，超窗口
- [ ] ~~scp 到 3588~~ ❌ 无文件
- [ ] ~~smoke_test.py --model qwen3-4b~~ ❌ 无文件
- [ ] ~~benchmark.py 9 prompt 对比~~ ❌ 无文件
- [ ] 内存余量评估 ✅（理论估算，无实测）
- [x] 不动主 daemon PID 1688700 ✅
- [x] 不改 modules/llm_engine/engine.py ✅
- [x] 不 commit ✅
- [x] 临时文件清理 ✅（/tmp/qwen3-4b-rkllm 已删除）

---

报告人：Claude（自动调研）
报告路径：`/tmp/qwen3_4b_npu_test_20260514.md`
