# 出差期间状态报告（5/21 启）

## TL;DR

| 项 | 状态 |
|---|---|
| 3588 supervisor | ✅ 跑起来了（02:46 被另一台 MBP 误关，本轮 03:15 重启） |
| openvocab_filter 视觉深思 | ✅ **修好** — 之前 100% fail 是 `/tmp/yolov8s-world.pt` 不在；下到 `~/models/` 持久路径并改 DEFAULTS |
| Jetson scene_analyzer | ⚠️ **半通** — 进程在跑，ollama 已重启，但 backend 配的是 `mtmd_cli` 不是 ollama，需要回来排查 |
| 本地 .git 损坏 | ✅ **修好** — iCloud 把 `.git/objects/` 清空了；重 clone 一份 .git swap 回来，与 origin 0/0 同步 |
| GitHub 同步 | ✅ commit `<本提交>` push 完成 |
| FunASR 2pass docker（音频 partial 体验） | ⚠️ 调研结论：**没那么容易**，详见下 |

---

## 1. openvocab_filter 修复（已完成）

### 根因
`modules/openvocab_filter/main.py` DEFAULTS hardcode 模型在 `/tmp/yolov8s-world.pt`，但 `/tmp` 是 tmpfs 每次重启即失，且仓库不带 25MB weights，自启动以来从未真正加载过模型，**100% inference_failed**。

### 改动
- DEFAULTS path → `~/models/yolov8s-world.pt`（加 `Path.expanduser()`）
- 启动 WARNING 提示从 ultralytics releases 拉模型
- 3588 上手动放好：`/home/firefly/models/yolov8s-world.pt`（md5 `545e0a36bd7ca480eb3bf21ca8085f95`）

### 验证（5/21 13:14 实测）
```
[ov] 1608门口 reason=idle_force_empty | inf 1840ms | hits=0
[ov] 办公室 reason=idle_force_empty | inf 1522ms | hits=0
stats: key_received=4, inference_failed=0, hits_published=0, empty_hits=2
```
- 推理 1.5-1.8s/帧（设计预期 ~1.6s/帧 CPU）✓
- inference_failed 从 100% 降到 0% ✓
- hits_published=0 是因为画面里没有"火/烟/未戴安全帽/跌倒/打架"这 5 类预设危险场景，不是 bug

---

## 2. Jetson scene_analyzer（部分通，需回来排查）

### 当前实测
- **设备**：`jetson@192.168.5.51`（hostname `yahboom`，43 天 uptime）
- **路径**：仓库在 `/home/jetson/av_unified_mvp_jetson/`（不是 `av_unified_mvp`）— 跟之前 memory 不一致
- **进程**：`main_jetson.py` PID 914484 + `scene_analyzer` PID 930566 在跑（启动于 5/18 patch 之后）
- **ollama**：服务被我 `systemctl start ollama` 重启了（之前 inactive 自 5/18 15:06，dead 3 天）
- **ollama models on disk**：`llava-phi3:3.8b` (~3GB)、`qwen3:1.7b` (~1.4GB)
- **scene_analyzer 实际不调 ollama**：Jetson 端 config `vlm_backend: mtmd_cli`，`vlm_model: qwen2.5vl-Q4_K_M`，走 llama.cpp 的 mtmd_cli binary，不是 ollama
- **MQTT `av/video/scene_analysis`**：没抓到事件（说明 mtmd_cli 那条路径也没在产事件）

### 回来要做
1. 查 `/home/jetson/av_unified_mvp_jetson/` 的 scene_analyzer 是哪个 fork（DEFAULTS 没有 `vlm_backend`，说明这一版有改动）
2. 看 mtmd_cli binary 在不在、qwen2.5vl-Q4_K_M GGUF 模型在不在
3. 看 main_jetson supervisor 日志（不在 `/tmp/jetson_supervisor.log`，那是 5/18 的）

---

## 3. 本地 .git 修复（已完成）

### 真相
不是"一个坏 ref"，是 **`.git/objects/` 整个被 iCloud Drive 清空** —
- 256 个子目录（00-ff）全存在但 0 字节
- 无 packed-refs，无 loose objects
- 所有 refs 写着 OID 但 fsck 报"invalid sha1 pointer"
- `git status` 还能用纯属假象（只读 index + refs 文本）

### 修法
1. 备份 working tree → `/tmp/av_unified_mvp-worktree-backup`
2. `git clone --branch sprint/...` via proxy → `/tmp/av_unified_mvp-fresh`（fresh `.git` 只含 origin 的真实 history）
3. `mv` iCloud 旧坏 `.git` → `/tmp/icloud-broken-git-backup`（保留以防万一）
4. `cp -a` fresh `.git` 进 iCloud repo
5. 验证：`git status` clean，`git rev-list --left-right --count HEAD...origin/...` = `0  0`，`git log` 工作

实际 working tree 内容跟 origin/sprint@`82e9843` 完全一致（早上看到的"ahead 3"是因为 `.git/refs/remotes/origin/...` ref 文本太旧；这 3 个 commit 实际早在 origin 上）—— 所以**没丢任何工作**。

### 隐患（你回来要处理）
**iCloud 跟 .git 历来不合**，这次 av_unified_mvp 坏过，下次可能再坏，也可能 av_understanding_mac、Hermes、lead_pipeline 任何一个仓库都会中招。建议你回来：

```bash
mkdir -p ~/code
mv "/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp" ~/code/
ln -s ~/code/av_unified_mvp "/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"
```
（symlink 让你的 iCloud 路径还能开，但实际存储在本地，iCloud 不再 touch `.git/`）

---

## 4. FunASR 2pass docker（B 方案）— 调研结论

你早上的判断"B 是初始方案，移植时一定有问题"基本对，但**真正的原因不是技术上做不到，是工程量比预想大**：

| 维度 | 情况 |
|---|---|
| 官方 funasr/funasr Docker Hub | Runtime SDK 标签（`funasr-runtime-sdk-cpu-*`）**只有 amd64**，没有现成 arm64 build |
| 多架构 base 镜像 | 只有 `20.04-py3.7`（Python base）有 linux/arm64（270MB）— 是底座不是 server |
| 第三方 ARM64 镜像 | `yaming116/fun-asr`、`harryliu888/funasr-online-server` 存在但未验证、不官方 |
| 3588 docker 网络 | 不通 docker.io registry（manifest inspect timeout）— 没配 docker proxy |
| 备选自建 | 从 FunASR runtime 源码 build aarch64 镜像 — 工作量 1-2 天 |

**实际可行路径（按工作量排）**：
1. **试 harryliu888/funasr-online-server arm64**（如果有 arm64 manifest）+ 给 3588 docker 配 proxy → 1-3h 验证
2. 自建 aarch64 镜像 from `funasr/runtime/` 源码 → 1-2 天
3. **接受现状**：3588 走 SenseVoice CPU offline，30s 段长延迟；演示场景下"准确度高于体验"可接受

你早上明说"音频暂不折腾"，所以本轮**没有动 audio_processor 任何配置**。Docker 这条路是中期 sprint 的事，不是这次能搞定的。

---

## 5. iCloud 隐患待办（不动，等你回来）

- `.git/objects/` 易被 iCloud evict — 见 §3 隐患
- 3588 上 `/home/firefly/creator_ai_demo/venv/` 5.7GB 仍未迁回仓库自洽 — memory 项早记录，不影响当前
- 3588 上 `system_config.yaml` 是 gitignored 本地配置，未来若有更多 module 配置漂移，可能需要起 `config/system_config.3588.yaml` 这种命名约定

---

## 6. 不确定 / 我没做的事

- ❌ 没动 `audio_processor`（你明说不折腾）
- ❌ 没在 3588 拉 docker（registry 不通 + 没你授权）
- ❌ 没深入 Jetson scene_analyzer 修复（mtmd_cli 路径陌生 + 你不在不敢动）
- ❌ 没把 iCloud 仓库迁移到 `~/code/`（destructive 等你回来）

---

## 7. 状态快照（可直接打开）

- 3588 dashboard：http://192.168.5.6:5050
- 3588 MJPEG：http://192.168.5.6:5051
- 3588 Node-RED：http://192.168.5.6:1880
- Jetson SSH：`SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51`
- 3588 SSH：`SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6`
- 本地仓库：`/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp`（与 origin sprint 0/0 同步）
