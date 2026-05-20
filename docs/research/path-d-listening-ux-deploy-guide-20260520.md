# 路径 D · 仿 partial UX 兜底 — 部署 + 验证指南

**分支**：`experiment/path-d-listening-ux`
**日期**：2026-05-20
**用户体验目标**：客户对 mic 说话时，dashboard 转写卡显示 "…正在听 X.Xs"动态占位（每 200ms 刷新），整段 final 上屏前**不再出现"卡死"错觉**。

---

## 用户视角（最高优先）

| 用户感知项 | 改前 | 改后 |
|---|---|---|
| 说完话到 final 上屏 | 1-3s 空白，"卡死"错觉 | 全程显示 "…正在听 0.3s → 1.0s → 2.1s..." 计时占位 |
| 真逐字蹦 | ❌ | ❌（这是兜底，不是真 partial）|
| 标点正确 | ✅ | ✅ 不变 |
| 不丢字 | ✅ | ✅ 不变 |

**不是真 partial**（懂技术的客户能看出来），但 90% 销售演示价值——客户大概率不会拿秒表测真 partial。

---

## 4 处 surgical patch

| 文件 | 改动 | 风险 |
|---|---|---|
| `modules/audio_processor/processor_arm.py` | 加 `_listening_callback` 字段（默认 None）+ `start(listening_callback=...)` + `_worker_loop` VAD speaking/silence 状态转换调 callback | 低（callback 默认 None，不传入时 0 行为变化）|
| `modules/audio_processor/main.py` | `start()` 传 `listening_callback=self._on_listening` + `_on_listening()` 函数 publish 到 `av/audio/listening` | 低（新增 MQTT publish，不改 transcript 链路）|
| `main.py` supervisor | `_start_mqtt` 加订阅 `av/audio/listening` + `_on_audio_listening()` push SSE channel "listening" | 低（新增 channel，不影响其它）|
| `web/static/dashboard.js` | 主动 `subscribeChannel("listening", handleListening)`（不通过 module discovery 注册避免 tickerForward 二次调用）+ `handleListening` 函数实现计时器 | **中**（3588 上 dashboard.js 有 user 本地 +370 行修改未提交，本 patch 不会冲突核心区，但合并要小心）|

---

## 部署到 3588（user 择时执行）

### 前置确认

3588 上的 3 个相关文件**都有 user 本地未提交修改**：

```bash
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 \
  "cd /home/firefly/av_unified_mvp && git status --short web/static/dashboard.js main.py modules/audio_processor/main.py"
# 预期：
# M main.py
# M web/static/dashboard.js
# (modules/audio_processor/main.py 上次 5/19 D3 时 scp 过新版同步过 md5 匹配 git tracked，需复测)
```

**不能直接 scp 这 4 个文件覆盖 3588**——会丢 user 本地修改。

### 方案 A（推荐）：人工 cherry-pick + 重启

User 自己在 3588 上 cherry-pick D 分支的 commit 到 working tree：

```bash
ssh firefly@192.168.5.6
cd /home/firefly/av_unified_mvp
git fetch origin experiment/path-d-listening-ux

# 看 D 分支差异
git diff sprint/liaohe-3588-night-poc-20260511...origin/experiment/path-d-listening-ux \
  -- modules/audio_processor/processor_arm.py \
     modules/audio_processor/main.py \
     main.py \
     web/static/dashboard.js

# 如果 diff 干净（不撞 user 本地修改），人工 apply：
git checkout origin/experiment/path-d-listening-ux -- \
  modules/audio_processor/processor_arm.py \
  modules/audio_processor/main.py

# main.py 和 dashboard.js 有 user 本地修改，需要 merge（用 vim/diff 工具）
# 或直接 git checkout origin/experiment/path-d-listening-ux -- main.py web/static/dashboard.js
# 但这会丢 user 本地修改

# 重启 supervisor
bash scripts/3588-demo-start.sh --force
```

### 方案 B：完整切到 D 分支测试

```bash
ssh firefly@192.168.5.6
cd /home/firefly/av_unified_mvp
git stash   # 保 user 本地修改
git checkout experiment/path-d-listening-ux
bash scripts/3588-demo-start.sh --force
# 测完
git checkout sprint/liaohe-3588-night-poc-20260511
git stash pop
bash scripts/3588-demo-start.sh --force
```

**注**：方案 B 期间 user 本地修改临时不可见，dashboard.js +370 行扩展（husion 控制面板等）也不可见。仅测试 D 用，**不能演示客户**。

### 方案 C（保守）：本机 Mac 5050 测

User 在 Mac 上拉 D 分支 + 跑 `start.command`，用 Mac mic 测试 D 效果，与 3588 隔离。最安全但需要 Mac 上 mosquitto + funasr docker 配置（user 之前 stage1 有这些）。

---

## 验证步骤

部署完后：

1. 打开 `http://192.168.5.6:5050`（或本机 5050）
2. 对 mic 慢慢说一句话（如"今天我们讨论一下沉默成本"约 3 秒）
3. **预期看到**：
   - 说话开始约 200ms 后，转写卡末尾出现淡蓝色斜体 "**…正在听 0.2s**"
   - 计时器每 200ms 刷新："…正在听 0.4s → 0.6s → 1.0s → ..."
   - 说完话后 silence ≥ 600ms，"正在听 X.Xs" 占位消失
   - punctuator 处理 + final 带标点上屏（同现状）
4. 监控 punctuator log（已 monitor 跑着）继续按 [punct] 序列

---

## 回滚

D 不动主线 git 也不动 v1.1-funasr-cpu-stable tag。回滚一行：

```bash
git checkout sprint/liaohe-3588-night-poc-20260511   # 切回主线
bash scripts/3588-demo-start.sh --force              # 重启 = 恢复无 listening 行为
```

---

## 投入产出（按 user 5/20 规则 3）

**投入**：
- 时间：~1.5h 实际（4 处 surgical patch，无新依赖）vs 预估 1.3d（含 dashboard CSS 调优 + 联调）
- 影响范围：
  - 主线代码：processor_arm.py / audio_processor/main.py / main.py / dashboard.js 各加 10-30 行
  - 红线触动：⚠️ audio_processor 改动（但只加 callback hook，不改 ASR 逻辑）
  - 不动：punctuator / video / llm / husion / mqtt_bridge / config

**产出**：
- 用户能看到："…正在听 X.Xs" 视觉占位，客户说话期间 dashboard 不再"卡死"
- 客户演示价值：销售可以指着说"系统在听，正在思考"，1-3s 等待变得**有反馈**
- 不解决：真逐字 partial（sensevoice offline 限制）、NPU 利用（funasr CPU 仍占 100%）

---

## 当前状态

- [x] D 分支 4 处 patch 实施完成
- [x] 部署 + 验证指南（本文档）
- [ ] Commit + push（**下一步**）
- [ ] User 择时 cherry-pick / 完整切分支测试 / Mac 本机测
- [ ] 测试通过后决策：merge 主线 sprint / 保留分支随时启用 / 弃
