# feat/dashboard-scene-20260519 部署 SOP

**Commit**：`f21311b` (4 files / +75)
**Branch**：`feat/dashboard-scene-20260519`（基于 sprint）

---

## A · Mac 端（dashboard 主线消费）

```bash
cd /Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp
git fetch origin
git checkout feat/dashboard-scene-20260519  # 或 merge 进 sprint 后 checkout sprint
./start.command  # 或 python3 main.py
```

打开 `http://localhost:5050`，"视觉深思 · 场景分析" 卡片：
- header 多出 dropdown（默认"全部"）
- 拿东西在 Jetson 旁 USB罗技C920 镜头前晃 → ~10s 后卡片出现 scene 行

---

## B · Jetson 端（scene_analyzer G1+G3a 改动）

⚠️ Jetson 上 `~/av_unified_mvp_jetson/modules/scene_analyzer/main.py` 含 **jetson-side 5/18 mtmd_cli backend 改动**（121 行新增），feat branch 上的 scene_analyzer 是 ollama 版。**不要 git pull 覆盖**。

### B.1 patch 方式（推荐，5min）

把 feat branch G1+G3a 改动手动 patch 到 jetson 上的 scene_analyzer/main.py，保留 mtmd_cli backend：

```bash
# Mac 端先 diff feat 与 sprint 的 scene_analyzer 改动
cd /Users/yumacs/.../av_unified_mvp.feat-dashboard
git diff sprint/liaohe-3588-night-poc-20260511..HEAD -- modules/scene_analyzer/main.py > /tmp/scene_feat.patch

# scp patch + Jetson 上 git apply（与 mtmd_cli 改动无冲突，行号都在 __init__ + _handle_message + _fetch_snapshot）
sshpass -p yahboom scp /tmp/scene_feat.patch jetson@192.168.5.51:/tmp/
sshpass -p yahboom ssh jetson@192.168.5.51 \
  'cd ~/av_unified_mvp_jetson && git apply --check /tmp/scene_feat.patch && git apply /tmp/scene_feat.patch'
```

若 `git apply --check` 报冲突（mtmd_cli 改动也碰 __init__），改用 manual edit：
- L126 (`self.subscribe(sa["detect_topic"])`) 后加 G1+G3a 6 行
- _handle_message 顶部加 2 个 topic 分支
- _fetch_snapshot 改 mjpeg_base_url 字段
- 新加 `_on_video_discovery` 方法

### B.2 重启 supervisor

```bash
sshpass -p yahboom ssh jetson@192.168.5.51 'kill $(pgrep -f "main_jetson.py" | head -1); sleep 4; cd ~/av_unified_mvp_jetson && setsid nohup python3 main_jetson.py > /tmp/jetson_supervisor.log 2>&1 < /dev/null & disown'
```

### B.3 验证 G1

```bash
sshpass -p yahboom ssh jetson@192.168.5.51 'grep "mjpeg_base_url 更新" /tmp/jetson_supervisor.log | tail -3'
```

期望：startup 后几秒内出现 `mjpeg_base_url 更新 http://192.168.5.6:5051 → http://192.168.5.X:5051`（X 是 video_processor 真实 IP；当前 3588=.6 fallback 就一致，可能不打 log）。

### B.4 验证 G3a watch_camera

Mac 端 dashboard dropdown 选 "USB罗技C920"，jetson log 应出 `watch_camera 更新 → USB罗技C920`。换回"全部"：`watch_camera 更新 → 全部`。

---

## C · 端到端验证清单

| # | 步骤 | 期望 |
|---|---|---|
| 1 | mac mqtt sub baseline | `mosquitto_sub -h 192.168.5.6 -t av/video/scene_analysis -v` 仍能收到 raw JSON |
| 2 | dashboard 卡片 SSE | 触发 keyframe → 卡片"等待..."消失，出现 scene 行 |
| 3 | dropdown populate | dropdown 显示当前 enabled 源（默认 USB罗技C920 一个）|
| 4 | watch_camera filter | 选某路 → 只看那路；选"全部"恢复 |
| 5 | discovery heartbeat 不报错 | jetson log 不出现重复 `mjpeg_base_url 更新`（同值不打）|
| 6 | scene_analyzer 6h 稳定 | uptime >6h 不崩 |

---

## D · 回滚

```bash
# Mac
git checkout sprint/liaohe-3588-night-poc-20260511
./start.command

# Jetson
sshpass -p yahboom ssh jetson@192.168.5.51 'cd ~/av_unified_mvp_jetson && git checkout modules/scene_analyzer/main.py'
# 再叠 mtmd_cli backend 手动 patch 回来（从 jetson-side branch c057660 commit）
```

---

## E · 后续 merge 决策

feat work 完 user review 后：
- **merge to sprint**：`git checkout sprint && git merge feat/dashboard-scene-20260519` — 所有 mac 拉 sprint 后受益
- **不 merge**：保 feat branch 独立，按需 cherry-pick
- **同时 merge jetson-side mtmd_cli backend 进 sprint**：另起 PR `feat/scene-mtmd-cli-backend`，把 c057660 cherry-pick 进 sprint（让 mtmd_cli 也是主线能力）

推荐：先 merge feat 进 sprint（dashboard 改动），mtmd_cli backend 单独 PR 再 merge（避免一次性大改动）。
