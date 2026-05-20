# Jetson 视觉深思固化 · 同步给 3588 开发线程

**作者**：jetson-side claude（5/19-20 推进）
**对象**：3588 sprint 开发线程
**branch**：`feat/dashboard-scene-20260519`（基于 `sprint/liaohe-3588-night-poc-20260511`）
**4 commits** · 5 文件 · +83/-2 行

---

## 一句话

**Jetson 视觉深思现在是 dashboard 一等公民**：mac 拉 feat branch + 启 main.py 后，浏览器 :5050 卡片实时显示 Jetson VLM 中文场景描述；前端 dropdown 可远程切换 Jetson 盯哪一路；Jetson 不再硬编码 3588 IP。

---

## 你（3588 dev）能直接利用什么

### 1. dashboard 卡片"视觉深思 · 场景分析"终于活了

**之前**：截图 1 卡片停在"等待 Jetson 视觉深思事件..."（main.py 没桥接 `av/video/scene_analysis` 到 SSE）
**现在**：3 commits 后桥通。在 USB罗技C920 镜头前任何变化 → 10-12s 后中文长描述行进卡片。

**如何用**：
```bash
git checkout feat/dashboard-scene-20260519   # 或合并 sprint 后 sprint
python3 main.py
# 浏览器 http://localhost:5050 → 视觉深思卡片实时刷新
```

### 2. 远程切换 Jetson 盯哪一路（新 mqtt API）

新增 mqtt config topic：
```
av/video/scene_analyzer/config {"watch_camera": "USB罗技C920"} → 只看这一路
av/video/scene_analyzer/config {"watch_camera": null}          → 全部 keyframe 都看
```

dashboard 前端已 wire 在卡片 header dropdown — 自动 populate `video_processor` discovery 上 enabled 的源。也可以脚本 / Node-RED 直接 publish 此 topic 控制。

**用例**：白天看大厅，下班切监控室。或者自动化：人脸识别确认人员离开后切走廊。

### 3. Jetson IP 自适应（G1）

之前 jetson scene_analyzer 硬编码 `mjpeg_base_url: http://192.168.5.6:5051`。**现在订阅 `av/system/discovery/video_processor`，从 `payload.ip` 动态构建 url**。

含义：3588 换 IP、或者 video_processor 切到其它机器跑 — Jetson scene_analyzer 30s 内自动跟上，不用改 yaml。

### 4. 5/18 起 VLM 速度 8× 改善（jetson-side branch 已部署到 Jetson runtime）

**注意**：这部分在 **`jetson-side-20260518` branch** 上（commit `c057660`），**不在本 feat branch**。但 Jetson 上跑的 scene_analyzer 已经合并了 mtmd_cli backend + 本次 G1+G3a 改动。

如果其它 mac 要本地跑 VLM（替代 ollama），需要 cherry-pick `c057660` 进 sprint + 同等部署 llama.cpp + GGUF 模型。当前仅 Jetson 用得上。

---

## 你（3588 dev）要避免的事

### ⚠️ 同时启 mac main.py + Jetson scene_analyzer 会触发 G1 race

如果 mac 启 main.py（拉起 mac 端 video_processor），mac vp 也会发 discovery 到 broker，**Jetson scene_analyzer 收到后会把 mjpeg_base_url 切到 mac IP**（plan §P5 风险，5/20 实测发生过）。

mac vp 上没有 USB罗技C920 这个 camera name → snapshot 拉到的图不一致 / 失败。

**短期 workaround**：
- 不同时启 mac main.py + Jetson scene_analyzer（同一 broker 上）
- 或者 mac main.py 关掉 mac video_processor（改 `MANAGED_MODULES` 注释 `modules.video_processor.main`）

**长期 fix**（未做，留 P5 follow-up）：scene_analyzer yaml 加 `trusted_vp_client_id: "av_3588_001"` whitelist，G1 只接受该 client 的 discovery。

### ⚠️ Jetson scene_analyzer 长跑后偶现 mtmd-cli SIGABRT 累积

5/20 实测：09:21 部署 G1 后跑 50min，期间 mac vp 干扰 → snapshot 拉假图喂 mtmd-cli → 16 次 SIGABRT。restart scene_analyzer 即清。

**临时手册**：观察 stats `vlm_failed` 连续增长且 `vlm_published` 不变时，`kill PID` 让 supervisor 重拉。

**长期 fix**：scene_analyzer 加 watchdog：连续 N 次 vlm_failed 自动 self-restart。**未做**。

### ⚠️ jetson-side branch 与 feat branch 在 scene_analyzer/main.py 双线改动

| Branch | 改动 |
|---|---|
| `jetson-side-20260518` | mtmd_cli backend (commit `c057660`)，~121 行 |
| `feat/dashboard-scene-20260519` | G1 IP 自适应 + G3a watch_camera filter，~21 行 |

两套改动**无重叠**（一改 `_call_vlm`，一改 `__init__/_handle_message`），`git apply` 实测 clean。但 merge sprint 时要注意：**两条 branch 都 merge 才完整**。

---

## 总改动清单（4 commits / 5 文件 / +83 行）

```
f319351 fix(mqtt_bridge): publish 加 wait_for_publish 消除 qos=0 race
aad2e1a docs(handoffs): 部署 SOP
f21311b feat(dashboard): scene_analyzer 桥接 SSE + 视频源选择器 + IP 自适应
[base: 215960d sprint HEAD]
```

| 文件 | 改动 |
|---|---|
| `main.py` (+8) | G2: subscribe `av/video/scene_analysis` + `_on_scene_analysis` SSE 桥 |
| `modules/scene_analyzer/main.py` (+33/-1) | G1 (IP 自适应) + G3a (watch_camera filter) |
| `web/templates/dashboard.html` (+5) | G3b: 卡片 header 加 `<select id="scene-watch-picker">` |
| `web/static/dashboard.js` (+29) | G3b: refreshSceneWatchPicker + setupSceneWatchPicker + hook |
| `core/mqtt_bridge.py` (+8/-1) | qos=0 race fix（与 G3 dropdown 操作可靠性相关）|

`docs/handoffs/feat-dashboard-scene-deploy-20260519.md` 是部署 SOP（Mac/Jetson 双端 + E2E 验证 + 回滚），102 行。

---

## 验证状态（5/20 10:16 实测）

| 项 | 状态 | 数据 |
|---|---|---|
| G1 IP 自适应 | ✅ | 09:55 video_processor restart 后 jetson 自动 fallback `→ http://192.168.5.6:5051` |
| G2 mac SSE 桥接 | ✅ | 60s SSE 收到 3 条 scene_analysis events |
| G3a watch_camera filter | ✅ | match keyframe published / mismatch dropped |
| G3b 前端 dropdown | ✅ 代码 | 当前 mac main.py 未跑，UI 视觉验证待 user 浏览器打开 |
| paho race fix | ✅ 代码 | 5/20 实测 3 POST 仅 1 通 → fix 后应 100% |
| Jetson runtime | ✅ | scene_analyzer PID 930564 ~4min uptime / VLM 10-12s/帧 stable |

---

## 你（3588 dev）下一步建议

### 选项 A · 立即合并 feat → sprint
```bash
git checkout sprint/liaohe-3588-night-poc-20260511
git merge feat/dashboard-scene-20260519
```
**收益**：所有 mac 拉 sprint 后 dashboard 卡片即活、qos race 修了。
**风险**：dashboard 卡片需要 jetson scene_analyzer publish `av/video/scene_analysis` 才有数据，sprint 上 ollama backend 单 mac 跑无 jetson 时卡片仍空。

### 选项 B · 先把 mtmd_cli backend (`c057660`) 也 cherry-pick 进来再合
```bash
# 在 feat branch 上
git cherry-pick c057660
# 然后 merge sprint
```
**收益**：mac 也能用 llama.cpp Q4_K_M 跑 VLM（需 mac 本地装 llama.cpp + GGUF 模型），完整 8× 速度优势主线化。
**工时**：cherry-pick 5min + 文档 + 各 mac 部署 30-60min。

### 选项 C · 推迟，feat branch 独立保留
保 sprint 干净 dev，feat branch 按需 checkout。jetson 端 runtime 已部署不受影响。

### 选项 D · 实施 P5 防御后再合
G1 加 `trusted_vp_client_id` 防 multi-vp race，避免 3588 dev 启 mac main.py 时干扰 Jetson。30-45min dev。

---

## 当前 Jetson 物理状态

- 5 模块在线：llm_engine / system_info / network_info / control_dispatcher / scene_analyzer（PID 930564）
- VLM：mtmd-cli Q4_K_M oneshot，10-12s/帧
- watch_camera：全部（默认）
- mjpeg_base_url：`http://192.168.5.6:5051`（3588 vp 跟踪中）
- mem：4.8GB available（充裕）
- ollama：systemd stopped（5/18 关掉，可恢复）
- audio_processor：不在 main_jetson modules（5/19 选项 X 关掉，硬件 limitation）

**Jetson 进入"应用固化"稳态**，不再做能力深化。后续只接维护 + bug fix。

---

## 联系

- worktree：`av_unified_mvp.feat-dashboard/`
- 完整决策路径见 `docs/reports/2026-06/jetson-*.md` 系列（5/18-20 全部 daily/night reports）
- plan 文件：`~/.claude/plans/refactored-sparking-manatee.md`
