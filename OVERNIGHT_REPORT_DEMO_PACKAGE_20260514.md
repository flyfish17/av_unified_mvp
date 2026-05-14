# 演示包包装 · 5/14 晚 报告

> 给 3588 主推路径加"客户演示外壳"：一键启动脚本 + dashboard 浮球按钮 + SOP。
> **未 commit**，等 user review。

## 一句话总结

3588 板子上 `bash ~/av_unified_mvp/scripts/3588-demo-start.sh` → 60s 后浏览器 `:5050` 右下角浮球 → 5 颗预设句式按钮 → 点了走 LLM 路径，4.5s 没回话自动走"离线兜底" `av/control` 直发。9 核心模块代码 / main.py supervisor / 原有 dashboard 面板 0 改动。

## 改动清单

| 文件 | 类型 | 行 | 用途 |
|---|---|---:|---|
| `scripts/3588-demo-start.sh` | 新建（chmod +x）| 227 | 3588 一键启动；自检 deps → 拉外部服务 → 启 supervisor → 45s 探活 → 输出就绪 URL |
| `docs/deploy/3588-demo-package.md` | 新建 | 124 | 客户演示包 SOP，user/销售复制即用 |
| `web/templates/dashboard.html` | 修改 | +211（CSS 71 + JS+HTML 140） | 右下角"演示"浮球，5 颗预设按钮，POST `/mqtt/publish` → 4.5s 兜底逻辑 |
| `OVERNIGHT_REPORT_DEMO_PACKAGE_20260514.md` | 新建 | 本文 | 报告（不入 commit） |

### dashboard.html 改动锚点

- **CSS**（行 ~822 前）：`#demo-fab` / `#demo-fab-toggle` / `#demo-panel` / `.demo-btn` / `#demo-toast`，全部 ID 加 `demo-` 前缀避免与现有 ID 冲突
- **JS**（行 ~1376 前的最末 `<script>` 块）：`initDemoBar()` IIFE，挂 `document.body`，不改任何现有 DOM
- 现有 dashboard 视觉/功能 100% 保留（GridStack / Node-RED iframe / 视频墙 / 转写 / 意图气泡 / scene_analyzer / etc 全在）

## 演示行为流程

```
点"演示 1" → POST /mqtt/publish topic=av/llm/command payload={text:"把研发部空调打开",demo_no:1}
   │
   ├─ 主路径（NPU LLM 全链路）
   │     llm_engine → NPU RKLLM ~198ms 首 token → av/llm/event + av/control
   │     dashboard 控制面板高亮 + 浮球 toast "✓ 命中 RDDepartment_AirConditioner_On"
   │
   └─ 兜底（4.5s 没看到预期 cmd）
         浮球自动 POST /mqtt/publish topic=av/control payload={cmd:"RDDepartment_AirConditioner_On",source:"demo_button_fallback"}
         dashboard 控制面板仍然看到命令落下 → 演示不翻车
```

## 启动方式验证步骤（user 明天跑这套）

```bash
# 1. 把改动 rsync 到 3588（仅 3 个文件）
rsync -av scripts/3588-demo-start.sh           firefly@192.168.5.6:~/av_unified_mvp/scripts/
rsync -av docs/deploy/3588-demo-package.md     firefly@192.168.5.6:~/av_unified_mvp/docs/deploy/
rsync -av web/templates/dashboard.html         firefly@192.168.5.6:~/av_unified_mvp/web/templates/

# 2. 3588 上启动（首次跑 dry-run 看状态）
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 \
    'bash ~/av_unified_mvp/scripts/3588-demo-start.sh --status'

# 3. 老 supervisor 没问题就保持，看到 ✓ 演示就绪 即可；否则
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 \
    'bash ~/av_unified_mvp/scripts/3588-demo-start.sh --force'

# 4. 浏览器打开 http://192.168.5.6:5050
#    右下角应该看到一颗黄红渐变小球，写"演示"
#    点开 → 5 颗按钮 → 点"演示 1：把研发部空调打开"
#    期望：toast 显示"▸ 演示 1：「...」已发送" → 1-2s 后变"✓ 演示 1 命中 → RDDepartment_AirConditioner_On"
#    dashboard 控制面板（"控制指令"列）应高亮 RDDepartment_AirConditioner_On
```

注意：脚本本身没在 3588 上跑过验证（按硬约束："今天只验证文件存在 + 语法正确"），明天 user review 通过后才推。

## 离线兜底设计

- **场景 1：LLM 慢**：4.5s 没 av/control → 浮球自动发 av/control，cmd=预设 fallback id
- **场景 2：LLM 拒（地点偷换）**：NPU 1.5B 偶尔把"吧台"识别成"二楼餐桌"，被 anti-hallucination filter 拒 → 同样 4.5s 超时 → 兜底
- **场景 3：客户机网络断**：浏览器到板子是 LAN 直连，断了浏览器都打不开；如果 LAN 通但 ollama 死了，按钮经 LLM 失败 → 立即（不等 4.5s）走兜底
- **场景 4：mosquitto 死了**：`/mqtt/publish` 返 503 → 浮球 toast "失败 — 尝试离线兜底" → 兜底也失败 → 至少 user 看到红色提示，不会假"演示成功"

## 硬约束自查

| 约束 | 自查 |
|---|---|
| 不改 9 个核心模块代码 | ✓ `modules/` 0 改动 |
| 不改 main.py supervisor 逻辑 | ✓ 0 改动 |
| 不破坏现有 dashboard | ✓ 只在 `<head><style>` 末尾追加 71 行 CSS，在 `</body>` 前最末 `<script>` 块追加 140 行 JS+DOM；原有 GridStack / Node-RED iframe / 视频墙 / 转写 / 意图 / scene_analyzer 全在 |
| 不 push commit | ✓ 4 个文件未 stage（user `git status` 可看到 untracked / modified） |
| 不动 3588 supervisor 进程 | ✓ 没在 3588 跑脚本，没改运行树代码 |

## user review 通过后建议 commit 切分

3 个 commit 干净独立：

```bash
# commit 1: 3588 演示一键启动脚本
git add scripts/3588-demo-start.sh docs/deploy/3588-demo-package.md
git commit -m "feat(3588-demo): 一键启动脚本 + 客户演示 SOP

scripts/3588-demo-start.sh — 自检 deps → 拉外部服务 →
启 supervisor → 45s 探活 → 输出就绪 URL；不强制覆盖旧
supervisor（--force 才覆盖）。配套 docs/deploy/3588-demo-package.md。"

# commit 2: dashboard 客户化（演示浮球）
git add web/templates/dashboard.html
git commit -m "feat(dashboard): 右下角演示浮球 + 5 预设句式 + 离线兜底

销售点开浮球按钮 → POST /mqtt/publish av/llm/command 走 LLM
全链路；4.5s 没收到预期 av/control 时自动直发 av/control（兜底）
避免演示翻车。CSS/JS 加在 dashboard.html 末尾，不改既有面板。

预设 5 句式覆盖 5 个 location × 3 设备类（空调/灯/窗帘），
fallback cmd id 已对 config/device_catalog.json 验证存在。"

# commit 3（可选）: 报告留档
# 实际上报告不入 commit 是约定，照之前 OVERNIGHT_REPORT_*.md 走
```

## 已知风险 / 待 user 决策

1. **演示句式硬编**在 dashboard.html 的 `const DEMOS = [...]`。如果 user 想交给销售自定义，可以抽到 `config/demo_presets.json` 走 `/config/` 静态 + fetch — 但这是 v2 增量，本次未做（约束："不要把 dashboard 改伤"）
2. **fallback_cmd 与 device_catalog 同步**：5 条 fallback id 直接硬编。如果 user 改了 device_catalog（删了某条 id），按钮会发个无效 cmd。建议下次跟 device_catalog 联动校验
3. **浮球位置**：右下角 `right: 18px; bottom: 48px`，挡 ticker 上方一点点。如果 user 觉得挡了内容可以改 `left: 18px` 或 `bottom: 90px`（一行 CSS）
4. **离线兜底没绕 mosquitto**：仍走 `/mqtt/publish` → MQTT broker → control_dispatcher，如果 broker 死了仍然失败。要做"完全离线"需要前端假装发个 SSE — 不建议，会和真实控制混淆
5. **脚本没在 3588 实跑验证**：仅 mac 上 `bash -n` 想验证，但被 sandbox 拒；语法靠肉眼审。Risk：脚本细节 bug 明早 user 跑时会暴露，但都是单步自检+printf，挂了立刻能看到 stderr 修，不是远场问题。

## 文件锚点（mac 绝对路径）

```
/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp/scripts/3588-demo-start.sh
/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp/docs/deploy/3588-demo-package.md
/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp/web/templates/dashboard.html
/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp/OVERNIGHT_REPORT_DEMO_PACKAGE_20260514.md
```

3588 落地后路径（rsync 推后）：
```
firefly@192.168.5.6:~/av_unified_mvp/scripts/3588-demo-start.sh
firefly@192.168.5.6:~/av_unified_mvp/docs/deploy/3588-demo-package.md
firefly@192.168.5.6:~/av_unified_mvp/web/templates/dashboard.html
```
