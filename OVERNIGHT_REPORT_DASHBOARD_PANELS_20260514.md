# Dashboard 双面板落地报告 · 2026-05-14

## 任务摘要

dashboard 加 2 个新面板：husion 9 设备 + 5 场景按钮、open-vocab 命中 timeline。

## 改的文件清单

| 文件 | 变更 | 行数变化 |
|---|---|---|
| `web/server.py` | + `time` 全局 import；+ 2 个 Flask route（`GET /api/husion/state`, `POST /api/husion/scene`）；现有路由 0 改动。 | 16863 → 18320 bytes（+38 行） |
| `main.py` | + `av/video/openvocab` MQTT 订阅；+ `_on_openvocab()` handler 桥到 SSE channel `openvocab`。 | 16185 → 16773 bytes（+10 行） |
| `web/templates/dashboard.html` | + 2 个 `grid-stack-item` 槽（`overview-husion` gs-x=0/y=42/w=6/h=5、`overview-openvocab` gs-x=6/y=42/w=6/h=5）；+ `.husion-scene-btn` / `.husion-dev-*` CSS 块。 | 69921 → 79486 bytes（+ ~9.5KB） |
| `web/static/dashboard.js` | + `MODULES_META` 加 2 项；+ `pushOverviewOpenvocab()`；+ `setupHusionPanel()`（10s 轮询 + 5 场景按钮 click）；+ `tickerForward` 加 `openvocab` 分支；+ `setupHusionPanel()` 接入 init 序列。 | 79787 → 89481 bytes（+9.7KB） |

原文件已备份到 3588 上 `~/av_unified_mvp/_backup_dashboard_panels/*.1778740650`。

## API 测试结果

### 1) `GET /api/husion/state` → 200 OK

```json
{
  "ok": true,
  "devices": [9 个],   // id 5001-5009, online="1G-M"（链路速率字符串，非 1/0 boolean）
  "wall": [],          // wall_id=1 当前无窗口（测试时无投屏）
  "ts": 1778740937.9
}
```

9 个设备全部返回，含 id/name/ip/dev_type/online/hls 字段。

**注意**：`online` 字段实际是字符串 `"1G-M"` / `"100M-F"` 等链路速率，**不是** 1/0 / boolean。已在 `setupHusionPanel()` `renderDevices()` 中改容错：非空且非 `"offline"`/`"0"` 即视为 online。

### 2) `POST /api/husion/scene`

切 5008 到 `单屏`：

```json
{"ok": true, "husion_resp": {"code": 0, "message": "Success", "data": [{"mode": "1x1", "scenename": "单屏", "switchList": [...1...]}]}}
```

切 5008 到 `四分屏`：

```json
{"ok": true, "husion_resp": {"code": 0, "message": "Success", "data": [{"mode": "2x2", "scenename": "四分屏", "switchList": [...4...]}]}}
```

测试后已恢复到 `单屏`。

### 3) `av/video/openvocab` MQTT → SSE bridge

`mosquitto_pub -t 'av/video/openvocab' -m '{...hits...}'` → `curl /events/openvocab` 立即拿到事件：

```
data: {"type": "hello", "channel": "openvocab"}
data: {"header": {"source": "test"}, "camera": "mock-cam-fire", "hits": [{"class": "未戴安全帽", "conf": 0.91, ...}], "inference_ms": 1240, ...}
```

`openvocab_filter` 模块 discovery snapshot 含 `streams: [{channel: "openvocab", kind: "kv_table"}]` → dashboard 自动订阅该 channel → `tickerForward → pushOverviewOpenvocab` 渲染。

`/mock/openvocab` POST 与真实 MQTT publish 两条链路均验证通过。

## 验证步骤记录

1. scp 4 文件到 3588 `/tmp/dashboard_upload/` → 备份原版到 `~/av_unified_mvp/_backup_dashboard_panels/` → 覆盖到目标路径
2. `pkill -TERM -f '^.*python main\.py$' && sleep 4 && nohup main.py …` 重启 supervisor
3. **第一次重启**：旧 Flask 进程的 5050 socket 仍 TIME_WAIT，新 Flask 启动失败（log 见 `Address already in use`，Werkzeug 把 OSError 吞了，`server.run()` 的 3 次重试块未触发 → bug 待修，见下文 TODO）。
4. **第二次重启**：手动 `pkill` → `sleep 5` 看到 5050 已释放 → 重启 supervisor → `ss -tlnp | grep 5050` 看到 listener → `curl /` 返回 200
5. 测 2 个 API + 2 条 SSE 链路（mock + MQTT），全部通过

## 已知 bug / TODO

1. **server.py `run()` 的 Flask 启动失败 retry 不工作（先前坑被这次踩到）**：Werkzeug `app.run()` 在端口冲突时不会抛 OSError，而是 print to stderr 后 return 0。`for attempt in range(max_retries)` 块只能捕获真正 raise 的 OSError，所以 Werkzeug 这条路径没被覆盖。建议改成显式 `socket.bind()` 预检 + retry，或换 `werkzeug.serving.make_server()` 显式建 socket。**当前缓解**：supervisor 重启间隔确保 ≥ 5 秒（已实测 5050 在 5s 内释放）。

2. **husion `online` 字段语义**：实际是链路速率字符串（`"1G-M"`），不是 boolean。前端已容错；但更可靠的 online 判断需要看 `wall` 中的 tx_id 列表（设备真有信号才会被 wall 引用）+ husion 其他 endpoint。`/api/get_all_display` 返回的字段可能更准，未深入。

3. **wall=[] 是当前状态而非 bug**：测试时 wall_id=1 上没投屏；切 `单屏` / `四分屏` 后 wall 才有窗口。dashboard 上 `[墙上]` 标签会在下次 10s 刷新时出现。

4. **未截屏验证 UI 渲染**：本地 Mac 上没装 Playwright；HTML 含 `gs-id="overview-husion"` 和 `gs-id="overview-openvocab"` 槽位（grep 验证），CSS 也注入完成（17 个 marker），但实际像素位置 / 拖拽 / 按钮颜色需 user 浏览器 force reload 后目检。

5. **`overview-openvocab` 与 `overview-scene` 视觉重叠**：scene 用 `data-overview="scene" .strip-card-body`，openvocab 用 `data-overview="openvocab" .strip-card-body`，模板槽位独立。但因 GridStack 持久化 layout（`av_overview_layout` 在 localStorage），**老用户首次刷新可能看不到新槽位**（旧布局没有它们）→ 需 user 在 dashboard 点 ⚙ 布局 → 全部显示，或 reset 布局。

6. **未 commit**：按硬约束保留 4 文件 modified 状态，user 验证 OK 后再 commit。

## 硬约束遵守情况

- 未动 `modules/web_browser/openvocab_filter/keyframe_filter` 等核心模块代码 ✓
- 未动现有 dashboard 面板的任何 grid-stack-item ✓
- `web/server.py` 仅新增 2 个 route + 1 个 import，原有 router 0 字节变化 ✓
- 用户指定的 supervisor 重启命令格式严格遵守 ✓
- 未 commit ✓

## 最终结论

dashboard 双面板落地 ✓，/api/husion 通 ✓，openvocab channel 显示 ✓
