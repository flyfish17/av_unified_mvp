# CR-DIG7201-A 语音转写模块 · 进度台账（单一状态源）

> 终端每完成一阶段追加一行：`阶段X done @YYYY-MM-DD HH:MM  commit:<hash>  备注(含验收数据)`
> 主 Claude 读此文件 + `git log` 做阶段检测与推进；打回时在此写 fail 项。
> 分支：`feat/cr-dig7201-asr`（基于 stable-3588）。任务详情见 `../TASK_A_会议主机语音+纪要修复.md`。

---

## 阶段清单与状态

| 阶段 | 内容 | 状态 | 时间 | commit | 验收数据 |
|---|---|---|---|---|---|
| P0-a | 会议转写 profile + 纪要分段 | ✅ done | 2026-07-28 17:45 | ce2cb00 | 2万字 37.4min 完整纪要；短会 5.5min 无回归 |
| P0-b | 纪要上 NPU（rknn-llm） | ✅ done（模型定型待决） | 2026-07-29 10:30 | d87be0c | 1.7B 全程 NPU 2万字 374s=6.2min（CPU 的 1/6）；<3min 未达 |
| P1 | 组播收包离线验证（net_audio_capture + mock） | ⬜ 未开工 | | | |
| P2 | 会议主机真机联调（8 路话筒区分） | ⬜ 未开工 | | | |
| P3 | 纪要按发言人分段 | ⬜ 未开工 | | | |

## 进度日志（追加式）

<!-- 终端在此追加，最新在上 -->

- 阶段P0-b done @2026-07-29 10:30  commit:d87be0c（后端切换代码）
  **部署（已装，用户授权）**：RKLLM-API-Server（GatekeeperZA）@ 3588 `:8000`，`/home/firefly/RKLLM-API-Server` + venv `/home/firefly/rkllm-server-venv`，librkllmrt 用板上已有 1.2.3（`RKLLM_LIB_PATH`，未动 /usr/lib、未装 systemd → **重启不自启，产品化时补**）。模型 `/home/firefly/models/`：qwen3-4b-16k（W8A8_G128 5.3G）、qwen3-1.7b（w8a8 2.4G，ctx 上限 4k）、qwen2.5-1.5b（旧 PoC）。
  **验收实测（video 冻结=meeting_asr 等效，已恢复）**：
  ① **1.7B 全程 NPU：2 万字 374.2s（6.2 分钟）**，6 段+汇总 7 请求零崩溃、8 要点 5 关键词、unload 自动执行 ✅（CPU P0-a 2245s 的 1/6）。目标 <3min 未达，如实回报：**4B 级 NPU prefill 实测 27 tok/s（G128）**，预研 130 tok/s 是 1B 级数字；1.7B prefill 93 tok/s、decode 5.6 tok/s。
  ② 质量：4B 分段提取最好（120组/270方言等细节全保）但全程 20min 级 + 长 prompt 偶发 SIGSEGV（1 次）→ **否决全程 4B**；qwen2.5-1.5b 质量掉档否决；**1.7B 要点保住数字/专名（54元/点、270余种），merge 出的 summary 偏空泛** → 改进方向：1.7B 分段+4B 汇总（est 9-10min）或 merge prompt 调优。
  ③ 16k ctx：4B 16k 可装载；1.7B 转换上限 4k，分段设计够用，但**短路径（≤8000字单次调用）在 4k ctx 会截断**（当前 rkllm 配置下短会应下调阈值或走 4B/ollama）。
  ④ **NPU 时序冲突实测确认（本阶段最重要发现）**：RK3588 NPU IOMMU IOVA 域 ~4GB；生产 llm_engine 的 1.5B 意图 daemon 常驻占 ~2GB → 4B 装载直接失败（`failed to allocate IOVA -12`，dmesg 实证），杀 daemon 后成功；1.7B(2.3G) 与 daemon 并存也贴顶。已实现纪要后自动 unload；**meeting_asr 产品形态 llm_engine 需切 ollama 或不起 → 待决**。
  **过程教训（重要，防复跑踩坑）**：/tmp/cr7201 测试实例代码陈旧导致两轮"e2e"实际跑在 ollama CPU 上（所谓"4B e2e 20min+第6段崩"= ollama 在内存压力下被断连，非 rkllm 崩）；**有效 NPU 数据以直连 :8000 的 Perf 日志为准**。部署/验证前先 `grep` 确认目标机代码版本。

- 阶段P0-a done @2026-07-28 17:45  commit:ce2cb00（主体 b5a885c）
  **验收实测（3588 真机，video_processor/openvocab SIGSTOP 冻结 = meeting_asr 等效，测完已 SIGCONT 恢复、5050 全程 200）**：
  ① 2 万字 `/tmp/dingna_transcript.txt` → **2245.3s（37.4 分钟）** 出完整纪要：6 段、8 要点、7 关键词、留档 summaries/ ✅ 无报错
  ② 短会回归：3000 字 → 327.2s（5.5 分钟）单次调用，字段齐 ✅
  ③ 目标"会后几分钟"CPU 上**达不到**，如实回报：瓶颈 = prefill 8-9 tok/s / decode 2.5-2.7 tok/s（冻结视频后 bench 实测，Mac 1640 tok/s 的 ~1/190）→ 印证 P0-b 上 NPU 是唯一根治
  ④ supervisor profile 装配验证（Mac）：meeting_asr=7 模块（去 video/keyframe/openvocab）、默认 full=10、非法值报错
  **过程要点**：qwen3.5:4b 输出多元素 JSON 数组系统性坏格式（首条后闭合数组，4 次中 3 次）→ LLM 输出整体改行格式+代码解析，Mac 3+1 次全绿零重试；timeout 公式按 3588 实测速率重定（4000 字段 605s）；`app_profile` 进 example config（system_config.yaml 本身 gitignore，产品机部署时本地打开 meeting_asr，Mac 本地配置已还原不影响 demo-mac）
  **P0-b 预备已并行完成**：板上发现 RKLLM SDK 1.2.3 + 上轮 PoC ctypes daemon（/home/firefly/rkllm-poc/，stdin/stdout JSON 协议可复用）；Qwen3-4B-rk3588 w8a8-opt1-16k（5.3GB）hf-mirror 断点续传下载中（Mac scratchpad）

- 2026-07-28 主 Claude：任务单 + 提示词就位，分支待建，等终端开工。已确认：分支 feat/cr-dig7201-asr from stable-3588；会议主机已上电走组播；3588=16G；测试素材 /tmp/dingna_transcript.txt 已在板上；NPU 预研完成（可行，路径见 TASK_A P0-b）。
- 2026-07-28 主 Claude：**NPU 部署指引已备** `docs/NPU部署指引_CR-DIG7201.md`（终端做 P0-b 时照此，已含三步部署 + 接口差异坑 + unload 解 NPU 争抢 + 必测项）。RKLLM v1.3.0 确认支持 qwen3.5；RKLLM-API-Server 提供 OpenAI 兼容 API + /v1/models/unload。

## ⚠️ 待决项

<!-- 卡点/需用户决策写这里 -->

1. **纪要模型定型**（P0-b ②）：A=1.7B 全程（6.2min，质量中，summary 偏薄）；B=1.7B 分段+4B 汇总（est 9-10min，质量高，4B 有偶发 SIGSEGV 风险）；C=先 A 上线、B 做后续优化。终端建议 **C**。
2. **meeting_asr 形态 llm_engine 去向**（P0-b ④，NPU IOVA 冲突）：意图识别切 ollama CPU（`AV_LLM_BACKEND=ollama`）还是 meeting 产品直接不起 llm_engine？纯转写产品用不到意图控制的话建议后者。
3. rkllm API server 未装 systemd（重启不自启）——产品化部署 SOP 时补，还是现在就装？
