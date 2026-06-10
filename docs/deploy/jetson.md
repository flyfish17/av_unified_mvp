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

---

## 视觉深思 scene_analyzer 部署 SOP（2026-06-10）

dashboard「视觉深思·场景分析」= `scene_analyzer` 模块，跑在 Jetson：订中控(3588) broker 的 `av/video/key_event` → 拉 3588 mjpeg snapshot(5051) → 喂本机 ollama VLM → 发 `av/video/scene_analysis` 回 3588 broker。**模型 = `qwen3.5:0.8b`**（多模态 0.8B，GPU ~5s/张，中文准确）。

### 部署位置
- 代码：`~/av_scene/`（`core/` + `modules/scene_analyzer/` + `config/`，从仓库 rsync；**非 git**）
- 启动器：`~/av_scene/run.sh`（= `scripts/jetson-scene-analyzer-run.sh`）
- config：`~/av_scene/config/system_config.yaml`（= `scripts/templates/jetson-scene-analyzer.config.yaml`，broker 指 **192.168.5.6** 不是本机）
- 自启：crontab `@reboot /home/jetson/av_scene/run.sh`（jetson 用户，无需 sudo）

### 一次性搭建步骤
1. **rsync 代码**：本机仓库 `core/` + `modules/scene_analyzer/` → Jetson `~/av_scene/`（带 `modules/__init__.py`）。
2. **config**：用模板，broker=192.168.5.6。
3. **ollama 需 ≥0.30**（qwen3.5 要新版，旧版拉报 412）。Jetson 自己下慢(~100KB/s)，**走本机下包 scp 法**：
   - 本机 `curl https://ollama.com/download/ollama-linux-arm64.tar.zst` + `...-jetpack6.tar.zst`（JetPack 6=jetpack6）。
   - scp 到 Jetson(~20MB/s)，干净装：`systemctl stop ollama` → `rm -rf /usr/local/lib/ollama` → `zstd -d <pkg | tar -xf - -C /usr/local`（两个包都解）→ `systemctl start ollama`。
4. **模型**：本机 `ollama pull qwen3.5:0.8b` 后，把 4 个 blob + manifest 从 `~/.ollama/models` 复制到 Jetson `/usr/share/ollama/.ollama/models`（`chown ollama:ollama`），免 Jetson 慢拉。
5. **crontab**：`( crontab -l; echo "@reboot /home/jetson/av_scene/run.sh" ) | crontab -`。
6. 跑 `bash ~/av_scene/run.sh`，看 `/tmp/sa.log`。

### 两个代码级修复（已在仓库 `modules/scene_analyzer/main.py`，commit ddc23eb）
- **think:false**：qwen3.5 默认开 thinking，会把 num_predict 吃光→空响应。`_call_vlm` 等加 `"think": False`（`/no_think` prompt 后缀无效）。
- **下采样**：qwen3.5 动态分辨率对 1080p IP 摄像头 prompt_eval 38s。`_analyze` 送 VLM 前 PIL 缩到 max 768px → ~5s。

### 坑
- **broker-wait 必须**：crontab @reboot 早于网络 up，scene_analyzer 连 broker 报 `OSError 101 Network unreachable` 崩溃（不重试）。run.sh 用 `bash /dev/tcp` 等 broker:1883 可达再起。两次真实重启验证 OK。
- **pkill -f 自杀**：外层命令 `pkill -f scene_analyzer.main`/`run.sh` 会匹配杀掉运行命令的 ssh shell 自己；`pgrep -f X` 也会把自己算进去（误报实例数）。重启用脚本内部 pkill 或按 PID。
- **网络**：Jetson 有线千兆本身没问题；出差时本机经远程/VPN 访问内网 ssh 频繁掉，长命令必须 setsid detached + 结果落文件轮询。
- SSH `jetson@192.168.5.51`（密码 yahboom）。

> llava-phi3:3.8b（~7-15s）作 qwen3.5 出问题时的 fallback 留在本地。
