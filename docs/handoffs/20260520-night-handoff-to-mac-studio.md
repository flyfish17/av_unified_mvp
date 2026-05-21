# 5/20 晚 handoff — Mac Studio 明天接手 3588 用

> 写于：MacBook Pro（家里，IP 192.168.3.136），21:30~22:30
> 目的：把今晚在 MacBook Pro 上做的"演示线立分支"动作传到 Mac Studio，让明天 3588 工作不被搅。

---

## 今日核心动作（三件事）

### 1. 摸清三方版本对照
- 本地 sprint 分支 `sprint/liaohe-3588-night-poc-20260511` 领先 `origin/main` **101 commit**，分布：
  - **67 commit Mac 演示线**（dashboard 客户视图 / husion / openvocab / scene_analyzer / punctuator / listening 三态）
  - **26 commit 3588/Jetson 支线**（RKLLM / RKNN backend / ct-punc int8 / paraformer spike，β/γ/δ 路径**均不过线**）
  - **8 commit 跨界**（scene_analyzer SSE 桥 / punctuator 双端共用 / llm-engine escalate 双路）
- airblue 上 `/Users/airblue/av_unified_mvp/main.py` = 15582 字节 / 5/9 13:25 = **commit `3b5bdbe`** ("feat: 巩固冲刺 K1-K5 — 部署摩擦点 + 可观测性")，**60h 长测无问题**。
- airblue 路径不是 git 仓库，是独立拷贝快照。

### 2. 拉出演示线基线分支 `mac-stable-foundation`
```
mac-stable-foundation @ 3b5bdbe (5/9)
└─ tag: mac-foundation-baseline-20260509
```
- 锚定 airblue 已验证版本（同字节数）
- 含 8 个 Mac 演示需要的模块：audio_processor / husion_distributed / llm_engine / mqtt_router / network_info / network_scanner / system_info / video_processor
- 不含 sprint 期间的销售包装（客户视图开关、husion 5 颗演示卡、openvocab、scene_analyzer、punctuator、listening 三态）
- **未推 origin**（待用户确认 push）

### 3. 清掉 5 个游魂 `__pycache__` 目录
- 切到 5/9 commit 后，`modules/{control_dispatcher,keyframe_filter,openvocab_filter,scene_analyzer,web_browser}/__pycache__/` 残留（git 不跟踪、不影响运行，仅噪音）
- 已 `rm -rf` 清掉，恢复 8 个干净模块条目

---

## 当前 git 状态（明天 Mac Studio iCloud 同步后的预期态）

| 分支 | HEAD | 与 origin 关系 | 含义 |
|---|---|---|---|
| `main` | 7344b88 v1.1 | 同步 | 远古固化版（演示用不了，太老） |
| `mac-stable-foundation` | 3b5bdbe (5/9) | **本地独有**（未 push） | ★ 演示线基线 |
| `sprint/liaohe-3588-night-poc-20260511` | eb93a26 | **本地 ↑1**（未 push） | 3588 工作分支 |
| `jetson-side-20260518` | b792f21 | 同步 | Jetson 支线 |
| `feat/dashboard-scene-20260519` | 30dceeb | 同步 | dashboard 场景化（已 merge 进 sprint） |
| `experiment/path-d-listening-ux` | 6d2c5fc | 同步 | listening UX 实验 |
| `experiment/path-gamma-zipformer-rknn-spike` | 0a2fd02 | 同步 | γ 路径（结论：不过线） |
| `experiment/rknn-paraformer-streaming-self-port` | 957a590 | 同步 | δ 路径（结论：不过线） |
| `experiment/node-red-polish` | f121730 | 本地 ↑2 | Node-RED 销售演示脚本 |
| `r28-snapshot` | 0456a5b | 同步 | 转写卡分段（参考用） |

**Tag**：`mac-foundation-baseline-20260509` 指向 `3b5bdbe`（仅本地，未 push）

**工作区未跟踪**：
- `docs/research/lan-observability-poc-20260520.md`（5/20 LAN 可观测性 POC 调研文档，未决定纳入哪条分支）
- `docs/handoffs/20260520-night-handoff-to-mac-studio.md`（本文件）

---

## 明天 Mac Studio 接手指南

### 前提：iCloud 同步问题
iCloud 同步整个 `av_unified_mvp/`（包括 `.git/`）。**iCloud 不是为 git 设计的同步通道**，存在小概率索引漂移。明早开工前先确认：
```bash
cd "/Users/yzj/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"
git status               # 期望: 当前分支 mac-stable-foundation，工作区 clean（仅两个 docs untracked）
git branch --show-current # 期望: mac-stable-foundation
git tag | grep mac-found  # 期望: mac-foundation-baseline-20260509
git log --oneline -3      # 期望首条: 3b5bdbe feat: 巩固冲刺 K1-K5 ...
```
若分支或 tag 没同步过来，说明 iCloud 漂移，从 GitHub 重拉。

### 继续 3588 工作（明天主线）
```bash
git checkout sprint/liaohe-3588-night-poc-20260511
# 这是 5/20 晚结束时的最新点，含未推的 commit eb93a26
# 继续推进 3588 NPU / D experiment / partial UX 等工作
```

### 演示需要时（一键切回 demo 线）
```bash
git checkout mac-stable-foundation
./start.command
# 跑通 6 项验证清单（见下方）后即可演示
```

### 待办（明早决定）

1. **是否 push `mac-stable-foundation` 到 origin？**
   - 推：明天 MacBook Pro 端能拉到这条分支、Mac Studio iCloud 漂移也有 fallback
   - 不推：暂时只在 iCloud 里活着，风险低但 Mac Studio 拿不到第二份
   - **推荐**：明早开工后用户确认即推

2. **是否 push sprint 上的 `eb93a26`（listening 链路 + badge 三态 + scroll 不拽回）？**
   - 是 5/20 晚最后那个 commit，未推 origin
   - **推荐**：跟 mac-stable-foundation 一起推

3. **是否把 `docs/research/lan-observability-poc-20260520.md` 纳入 sprint 分支跟踪？**
   - 是 5/20 白天的调研文档，已存在但 untracked
   - **推荐**：明天切到 sprint 后 `git add` + commit 进 sprint

4. **是否在 Mac Studio 上落"双 clone"方案？**
   - 即 `~/dev/av_demo`（mac-stable-foundation）+ `~/dev/av_3588`（sprint），物理隔离两条线
   - 适合 Mac Studio 同时跑 3588 工作 + 偶尔切演示
   - **推荐**：用一阵子 iCloud 切分支模式，碰到痛点再上双 clone

---

## mac-stable-foundation 验证清单（明天首次启动时跑）

启动：`./start.command`，逐项核对：

- [ ] 启动脚本顺利出 mosquitto / funasr-2pass / ollama / main.py 全部进程
- [ ] dashboard 浏览器窗口在 http://localhost:5050 出来
- [ ] 摄像头画面进 dashboard（视频通路通）
- [ ] 说一句话能转写出来（音频通路通）
- [ ] 触发一个能让 LLM 响应的语音（"切到运动模式"或类似），看 LLM 出结果（推理通路通）
- [ ] MQTT topics 在 dashboard 各 channel 都有数据流（桥接通路通）
- [ ] `config/system_config.yaml` 里 hostname / 摄像头 RTSP / husion ID 等都对得上当前网络环境

如果某项断了：先在 mac-stable-foundation 上修，**不要回退到 sprint 找"现成实现"**。这条线就是要"airblue 5/9 验证态" + 必要补丁，避免把 sprint 的销售糖累积进来。

---

## 演示剧本（敲定）

**演示**（5/9 已 60h 验证）：
- 视频识别（YOLOv8n + VLM 关键帧触发）
- 音频 ASR（funasr-2pass，Mac CPU 版）
- LLM 推理（ollama qwen2.5）
- MQTT 串通（modules 间解耦订阅）
- Dashboard 基础展示

**不演示**（5/14 之后的销售包装，未在 airblue 验证）：
- ❌ 客户视图开关 + LOGO splash
- ❌ husion 5 颗演示卡（跨品牌中控）
- ❌ openvocab 词条触发切场景
- ❌ scene_analyzer 视觉深思层
- ❌ listening 三态 badge

理由：客户买的是底座能力，演示糖客户问得深再切 sprint 分支补；演示主线追求"60h 不崩"。

---

## 相关 plan 文件位置

完整对比分析与决策过程：
`/Users/yzj/.claude/plans/macbook-pro-3588-3588-airblue-60-3588-m-quiet-minsky.md`

不在仓库里，仅 MacBook Pro 本地（Mac Studio 上没有）。

---

## airblue 状态（不动）

- 家网段 IP 已从 memory 中的 `192.168.3.128` 更正为 **`192.168.3.138`**（2026-05-20 实测）
- `/Users/airblue/av_unified_mvp/` 仍跑 5/9 版本 PID 15221（21:44 起，预计跑到次日）
- 60h 长测中，不动它
- airblue 上还跑着 NousResearch Hermes Agent（独立项目，跟 av_unified_mvp 互不干扰）
