# CR-DIG7201-A 语音转写模块 · 进度台账（单一状态源）

> 终端每完成一阶段追加一行：`阶段X done @YYYY-MM-DD HH:MM  commit:<hash>  备注(含验收数据)`
> 主 Claude 读此文件 + `git log` 做阶段检测与推进；打回时在此写 fail 项。
> 分支：`feat/cr-dig7201-asr`（基于 stable-3588）。任务详情见 `../TASK_A_会议主机语音+纪要修复.md`。

---

## 阶段清单与状态

| 阶段 | 内容 | 状态 | 时间 | commit | 验收数据 |
|---|---|---|---|---|---|
| P0-a | 会议转写 profile + 纪要分段 | ✅ done | 2026-07-28 17:45 | ce2cb00 | 2万字 37.4min 完整纪要；短会 5.5min 无回归 |
| P0-b | 纪要上 NPU（rknn-llm） | ⬜ 未开工 | | | |
| P1 | 组播收包离线验证（net_audio_capture + mock） | ⬜ 未开工 | | | |
| P2 | 会议主机真机联调（8 路话筒区分） | ⬜ 未开工 | | | |
| P3 | 纪要按发言人分段 | ⬜ 未开工 | | | |

## 进度日志（追加式）

<!-- 终端在此追加，最新在上 -->

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
（暂无）
