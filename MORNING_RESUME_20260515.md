# 明早接手 · 2026-05-15 08:00

> 在新 Claude 窗口（clear 之后）发：`读 MORNING_RESUME_20260515.md 然后告诉我夜班结果 + 今天该做什么`

## 0. 30 秒回忆

5/14 修了视觉深思链路（commit `6ecec51`）让 video_processor 在静态画面时也发空 detect 心跳触发 Jetson VLM 巡检。修完留了一个**预测的硬伤**：4 路 × 60s idle 触发节奏 vs Jetson VLM 78s/次 = 5.2× 过载。夜班全授权 Subagent 已交接跑 8h sustain 验证 + 推荐参数，handoff 在 `OVERNIGHT_HANDOFF_VLM_SUSTAIN_20260514.md`。

## 1. 第一动作（看夜班产出）

```bash
cd "/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"

# A. 夜班报告是否产出
ls -la OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md 2>&1

# B. 夜班是否 commit
git log --oneline -10

# C. 3588 supervisor 还在不在
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 "ps -ef | grep modules\. | grep -v grep | wc -l; tail -10 /tmp/main_supervisor.log"

# D. dashboard 还能打开吗
curl -s -o /dev/null -w "%{http_code}" http://192.168.5.6:5050/
```

## 2. 三种情况分支

| 夜班状态 | 怎么做 |
|---|---|
| ✅ 跑完 + 报告完整 | 读报告执行摘要 → 决定是否采纳推荐参数 → push 全部 commit |
| 🟡 跑一半中断 | 看最后一个 commit / log，决定补跑 or 跳过参数调优直接整理今天能用的数据 |
| ❌ 整个挂了 / supervisor 死 | 先恢复服务（不要慌：handoff 里 root cause 应该在报告里），再考虑调参 |

## 3. 5/15 主线候选（按优先级）

| 优先级 | 任务 | 工时 |
|---|---|---|
| P0 | 夜班结果落地（调参 + push）| 30 min - 1h |
| P1 | task #54 Flask 5050 真修（make_server）| 20-30 min |
| P1 | 跟销售对齐演示包效果反馈 | 看 user 安排 |
| P2 | venv 从 creator_ai_demo/ 迁到 av_unified_mvp/（需停服务）| 1-2h |
| P2 | 客户硬件 enroll 准备（销售出门后才会知道客户现场什么硬件）| TBD |

## 4. 不变的红线

- 不动 audio_processor / sensevoice 长跑样本
- 不动 /home/firefly/creator_ai_demo/venv（5.7G 还在用）
- 不 force push / 不动 main 分支
- 3588 上没 sudo 别试

## 5. 关键文件 / 位置

| 资源 | 位置 |
|---|---|
| 夜班 handoff | `OVERNIGHT_HANDOFF_VLM_SUSTAIN_20260514.md` |
| 夜班报告（待生成）| `OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md` |
| 5/14 关键 commit | `6ecec51` heartbeat fix · `54ecbdd` handoff |
| 当前 branch | `sprint/liaohe-3588-night-poc-20260511` |
| 3588 supervisor log | `/tmp/main_supervisor.log` |
| 3588 仓库 | `/home/firefly/av_unified_mvp/` |
| Jetson IP | `192.168.5.51`（不是 .13） |
