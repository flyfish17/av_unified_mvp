# 任务 A · 会议主机语音（发言人区分转写）+ 纪要 >1h bug 修复

> 2026-07-28 下发。执行方：终端 AI。规划/验收：主 Claude。
> 上游总计划见 `~/.claude/plans/三协议接入-20260728.md`。本单是 A 线可执行细化。
> **铁律**：以视听理解程序为主干，只新增模块 + 配置开关，不改动已验收的主链路行为；全部在 3588 可跑。

---

## 〇、目标（两件，可分先后）

1. **修纪要 >1h bug**（现象已复现：会议超 1 小时生成纪要报错。客户来访都用，优先）。
2. **会议主机语音接入**：订 8 路话筒组播音频 → 复用 FunASR 转写链路 → 转写/纪要带发言人（话筒号）标签。这是任务2"网络包可区分话筒编号"的落点。

---

## 一、协议事实（原厂 doc 已抓，字段级确定）

会议主机语音独立输出协议：
- **UDP 组播** `224.1.1.11`，8 路话筒 = 8 个目标端口 **1000-1007**（1000=第1路 … 1007=第8路）。源端口 100。
- 音频：**48000 采样率 / 16bit / 单声道 PCM**。
- 数据包格式：`ID高8 + ID低8 + ID高8 + ID低8`（4 字节包头，2 个重复的 16bit ID）+ **320 个 16bit sample**（即 640 字节 PCM 负载）。
- 参考：加入组播组 `JoinMulticastGroup(224.1.1.11)`，各端口独立收包。

> 注意：包头 ID 与端口号都可标识话筒；以端口号为准（1000+N），ID 做交叉校验。

---

## 二、现状锚点（改这些，别新开轮子）

- FunASR 转写链路：`modules/audio_processor/processor.py` — `websocket_2pass` 连 `ws://127.0.0.1:10095`（`processor.py:55-66`）；PCM 帧队列 `_send_q`（`:66`），采样率默认 16000（`:57`）。
- 转写结果发布：`modules/audio_processor/main.py` — partial → `av/audio/partial`（`:105/:253`）；final → `av/audio/command`（`:233`）。payload 是 dict，**新增 `speaker`/`mic_id` 字段即可，不破坏现有订阅**。
- ARM/Mac 后端切换：`AV_ASR_BACKEND` 环境变量（`main.py:29-31`），sense_voice_arm = 3588。
- 纪要生成：`web/server.py` — `_call_ollama_summary`（`:323`，**`timeout=60` 写死、`num_predict=800`、无 `num_ctx`**）；入口 `audio_summary`（`:350`）；前端 `web/static/dashboard.js:1974`。
- 配置：`config/system_config.yaml`（audio/funasr、video.sources 都在这）。

---

## 三、分阶段任务 + 验收门槛

### ⚠️ 实测结论（2026-07-28 主 Claude 在 3588 真机跑丁娜 2 万字真实转写）
- 原样 `/audio/summary`（20325 字）→ **HTTP 502，60.1s 超时**（`Read timed out (read timeout=60)`）。根因直接项 = `server.py:323` `timeout=60` 写死。
- 全量 + `timeout=900` + `num_ctx=24576` → **900 秒仍未返回**。**"只改 timeout/num_ctx" 被实测否定**。
- 更本质：① 该机同开视频检测，`video_processor`(YOLO) 吃满 4 核，ollama 抢不到 CPU；② `ollama /api/ps` 显示 `size_vram: 0` = 纪要 `qwen3.5:4b` **纯 CPU 跑**，RK3588 CPU 处理 2 万字长文本本就慢。
- **三处对照实测（隔离硬件/程序/模型，2026-07-28）**：Mac M3 Ultra 96G / 同模型 qwen3.5:4b / 同 2 万字 → **11.9s 出优质纪要**（prompt_eval **1640 tok/s**）；3588#6 满载/4b → 900s+ 超时；湖森 DNC#62 / RK3588 / 7b → 900s 超时。**铁证：瓶颈 = RK3588 CPU 硬件，程序+prompt+模型全对**（Mac 印证）。差距约百倍。对比文档：iCloud `丁娜/纪要算力对比测试-20260728.md`。
- **用户已定路线（2026-07-28）：先做 P0-a（关视频 profile + 分段）作可交付底线；中期 P0-b（纪要上 NPU）。** P0-b 是产品级实时纪要的**唯一自洽解**（单机涉密不能外放）；P0-a 分段只把 CPU 慢缓解到分钟级，非根治。

### P0-a · 会议转写 profile + 纪要分段（先做，产品可交付底线）
1. **profile 化**：CR-DIG7201-A 是纯会议转写产品，`config/system_config.yaml` 加 `app_profile: meeting_asr`；main 按 profile 选 MANAGED_MODULES 子集——`meeting_asr` **不起** video_processor / openvocab_filter / keyframe_filter / scene_analyzer（视频链路整条关掉），4 核全给 FunASR + 纪要。这就是"不同应用只开对应模块"的落地。
2. **纪要分段**：`server.py` `_call_ollama_summary` 改造——转写 >阈值（如 8000 字）时切段（每段 ~4000 字），每段小 ctx（`num_ctx: 7168`）提要点 → 汇总成 title/summary/points/keywords。简单 for，不做框架。`timeout` 按段动态。前端加"生成中"等待态。
- **验收门槛（务必在 `meeting_asr` profile 下测，视频链路关闭）**：① 2 万字真实转写（用 `/tmp/dingna_transcript.txt`，已在 3588）→ 出完整纪要不报错、字段齐；② 记录总耗时（目标"会后几分钟内"，非实时可接受，达不到则回报数字）；③ 短会议无回归；④ 失败报明确错误不静默吞。

### P0-b · 纪要上 NPU（预研已完成 2026-07-28，结论：可行值得押，给出确定路径）
**预研结论（联网查证，见附录）**：
- 模型支持 ✓：RKLLM 官方支持 **qwen3.5**（3588 现用模型）；`Qwen3-4B-Instruct-2507-rk3588` 有现成转换版（**4k / 16k context 两版**）。
- 性能估算：NPU prefill **~130 tok/s** → 2 万字（12.6k token）约 **1.5-2 分钟**出纪要（CPU 是 900s+ 出不来）。从"不可用"到"会后 1-2 分钟"，产品可用。
- 部署 ✓：RKLLM 有 **OpenAI 兼容 API server**（RKLLM-API-Server），改 URL 即可接入。
- 量化：RK3588 仅支持 **W8A8**，4B 约 4-5GB（16G 够）。

**实操三步**：
1. 拉 `randomblock1/Qwen3-4B-Instruct-2507-rk3588`（16k 版），或 RKLLM Toolkit v1.2.3 自转 qwen3.5:4b（W8A8）。
2. 起 RKLLM-API-Server（OpenAI 兼容）；`web/server.py` `_call_ollama_summary` 加配置项 `summary_backend: ollama|rkllm` + `summary_url`，指向它。
3. 实测：`/tmp/dingna_transcript.txt`（2 万字，已在 3588）→ 记录真实 prefill 耗时 + 纪要质量，对比 Mac 基线（Mac 输出见 iCloud `丁娜/纪要算力对比测试-20260728.md`）。
- **验收门槛**：① NPU 真实出纪要耗时（目标 <3min）；② 质量对比 Mac 基线可接受；③ 与 P0-a 的 CPU 分段对比给结论；④ NPU 与 scene_analyzer 若都用 NPU，确认会中/会后时序不冲突。
- **风险**：W8A8 质量待实测；16k context 对超长会议勉强（超长仍分段）；130 tok/s 是理论值需实测 4B。

> **NPU 预研附录（2026-07-28 联网）**：prefill ~130 tok/s（3 NPU 核 fp16，多源一致）；1.5B decode 19.55 tok/s。RKLLM 支持 qwen3.5/gemma4/smollm3，Toolkit v1.2.3 targeting RK3588 3 核。源：tinycomputers.io RK3588-NPU-benchmark · sergiiob.dev 14-model · HF randomblock1/Qwen3-4B-rk3588 · github airockchip/rknn-llm · Radxa RKLLM docs。

> **3588 运维铁律（本轮踩坑）**：3588 是生产演示机，动模块（临时腾 CPU 等）用 `SIGSTOP/SIGCONT` 冻结/恢复、**且必须独立短命令**，不要把"停→测→恢复"串进一条长 ssh —— 长 ssh 被 timeout 中断会把模块留在冻结态。测完 `curl :5050` 验证 200。

### P1 · 组播收包离线验证（1 天，不等硬件）
1. 新模块 `modules/net_audio_capture/`（BaseModule 血统，与现有模块同构）：8 路端口各起 UDP 收包线程，解包取 640 字节 PCM 负载，按 mic_id 分路。
2. 写一个 mock 发包脚本 `scripts/mock_meeting_audio.py`：把任意 wav 切成 320-sample 包，按协议格式往 224.1.1.11:1000-1007 发，模拟多路话筒。
3. 每路 48K→16K 重采样后，复用 `processor.py` 的 FunASR 发送链路（抽出可复用的 feed 接口，或每路起一个 2pass 会话——按 3588 资源定，先单路验证再扩）。
- **验收门槛**：mock 脚本灌 2-3 路不同 wav → 各路转写文本正确、`av/audio/partial` payload 带正确 `mic_id`；3588 上 CPU/内存可承受（记录并发路数上限）。

### P2 · 真机联调（等会议主机上电，0.5 天）
1. 会议主机接入台架同网段，确认能收到 224.1.1.11 组播（`tcpdump`/`mosquitto` 侧证）。
2. 三方现场发言 → 各归到对应话筒号。
- **验收门槛**：真实三方发言，转写按话筒分段正确；丢包/静音路不干扰其他路。

### P3 · 纪要按发言人分段（0.5 天）
1. 转写落库带 speaker；`_SUMMARY_PROMPT` 增发言人维度（谁提出什么/谁决策），或纪要按发言人归并要点。
2. dashboard 转写卡按话筒号分色/分栏。
- **验收门槛**：一段多话筒会议 → 纪要能区分发言人贡献；导图/要点合理。

### profile 开关（贯穿）
`config/system_config.yaml` 加 `audio.source: mic | net_multicast`（可共存则列表），main 按开关决定起 `audio_processor`（本地麦）还是 `net_audio_capture`（组播）或两者。默认不改现状（mic）。**不同应用只打开对应模块 = 靠这个开关，不改主干代码。**

---

## 四、不做 / 边界

- 不改已验收的本地麦克风转写链路行为（P1 复用其 FunASR 发送，不重写）。
- 不做发言人声纹识别（话筒号已足够区分，声纹是另一量级，不在本单）。
- 组播收包只做收（转写用），不做回放/录制持久化（除非另提）。
- 分支：**`feat/cr-dig7201-asr`，从 `stable-3588` 开**（已定 2026-07-28）。CR-DIG7201-A = 快捷会议 7 系列语音转写模块，用 3588 硬件 + 视听框架 + 转写模块；不碰 demo-mac / main / husion-dnc 三红线。

---

## 五、已确认条件（2026-07-28）

1. 定位：CR-DIG7201-A（快捷会议 7 系列）语音转写模块，3588 硬件 + 视听框架 + 转写模块。
2. 分支：`feat/cr-dig7201-asr` from `stable-3588`。
3. 会议主机**已上电、走组播**（P2 可随时联调）。
4. 3588 = 16G，IP 192.168.5.6，`firefly@192.168.5.6` 可 ssh（生产机，视听+运维在跑，勿停）。
5. 纪要算力路线：P0-a（关视频 profile + 分段）先做，P0-b（NPU）中期。
6. 测试素材：2 万字真实转写已在 3588 `/tmp/dingna_transcript.txt`。
