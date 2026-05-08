# av_unified_mvp 订阅式 UI + 模块库 实施计划

## Context

当前 `/Users/yzj/Developer/av_unified_mvp` 经 P0–P3 + Bug A/B 后，已具备：MQTT 总线、3 个理解模块（audio/video/llm）可独立运行、4 路 SSE 多频道前端、Node-RED 协议示例 flow。

**但用户视角验收时（回合 14）暴露三层差距**：

1. 当前 dashboard 是**事件流调试视图**，不是面向最终用户的产品 UI
2. 视频区只有文本，没有真实画面（且配置默认所有摄像头 `enabled=false`）
3. Node-RED 没有入口，用户从浏览器找不到"怎么编排"

用户已明确方向：**类 woldmonitor 的订阅制是灵魂，UI 让用户从 MQTT 公告里挑数据；模块要乐高积木式可拆装；最终用户是普通用户**。

本计划把当前架构（70% 已为订阅式准备）的"硬编码 4 区"剥掉，改成"模块公告→UI 自动生成区域"的订阅式架构，并补足 MJPEG 视频画面、Node-RED iframe 嵌入、3 个新订阅模块（系统信息 / 网络信息 / 局域网扫描）。同时把 main.py 从"内嵌+独立"双轨制重构为纯 supervisor，彻底执行"协议是合同"。

执行原则：每阶段都能 demo，避免最后一次性发现走偏；总工期 4.5 天分 6 阶段切片。

---

## 关键决策（已与用户确认）

| 决策 | 选择 | 理由 |
|---|---|---|
| Node-RED 嵌入 | iframe 嵌编辑器（A） | 让用户能在面板里直接拖规则，"creator 中控编程"风格 |
| main.py 架构 | **退化为纯 supervisor** | 模块真正独立、客户裁剪友好（"只要语音转写"一条命令）；消除 `_on_audio_event` 直接调 `self.llm` 的总线后门 |
| renderer 粒度 | **极简 3 种** | `transcript_seq` / `kv_table` / `mjpeg`；其它 fallback 成 JSON dump，UI 工作量减半 |
| 公告失活策略 | 灰显保留 + "已离线"标记（B） | 用户能看到曾经存在过的模块，不是消失 |
| 视频技术 | MJPEG `<img src>`，复用内存帧 | woldmonitor 风格；不开第二条 RTSP；按需启用解码 |
| 554 扫描复用 | 重写为 asyncio | 上版同步阻塞 30s+，并发 254 路压到 ~3s |

---

## 统一公告协议（R1 敲定）

**topic**：`av/system/discovery/<module>` （retain=true，QoS=1，配 LWT will message）

**载荷 schema**：
```json
{
  "module": "audio_processor",
  "client_id": "av_box_001",
  "ip": "192.168.x.x",
  "ts": 1746348000.0,
  "event": "online | heartbeat | offline",
  "heartbeat_interval": 30,
  "streams": [
    {"topic": "av/audio/partial", "kind": "transcript_seq", "title": "实时转写"},
    {"topic": "av/audio/command", "kind": "transcript_seq", "title": "已定稿"}
  ],
  "endpoints": [
    {"kind": "mjpeg", "url": "http://host:5050/video_feed/<camera_name>"}
  ]
}
```

**关键设计**：
- 模块只声明数据**形状**（kind），不声明渲染细节（颜色、位置）。UI 维护 `kind → renderer` 映射表
- `heartbeat_interval` 让模块自报心跳频率；UI 用 `2.3 × interval` 当失活阈值（容忍一次丢失）
- LWT 防止"僵尸 retain 消息"——模块崩溃时 broker 自动发 `event=offline`，UI 灰显
- 废弃 `core/mqtt_bridge.py:69` 的 `av/discovery` 单层旧版；`DEVELOPMENT_PLAN.md` §4 协议表同步改

---

## 阶段切片（每阶段都能 demo）

### R1 — 公告协议统一 + LWT（0.5 天）

**改动**：
- `core/base_module.py:185-202`：`_publish_discovery` 改新 schema；`__init__` 注册 LWT；`run()` 周期发 `event=heartbeat`
- `core/mqtt_bridge.py:69`：删旧 `av/discovery` 发布逻辑
- `DEVELOPMENT_PLAN.md` §4：协议表更新为新 schema
- 三个模块的 `modules/<x>/main.py`：在 `__init__` 里组装 `streams[]` / `endpoints[]` 传给 BaseModule

**验收**：`mosquitto_sub -t 'av/system/discovery/#' -v` 看到 audio/video/llm 三个模块都按新 schema 发出。kill 掉 audio_processor 进程，broker 立即推送 `event=offline`。

### R2 — main.py supervisor 化（1 天）

**改动**：
- `main.py`：删 `from modules.<x>.<y> import ...`；删 `_on_audio_event` / `_on_video_event` 等直调代码
- `main.py` 改成 supervisor 主循环：`subprocess.Popen([sys.executable, "-m", "modules.audio_processor.main"])` 等三个；周期 `poll()`，returncode 非 None 自动重拉（指数退避，5 次失败后告警）
- `main.py` 仍负责：profile 探测、起 web/server.py、起旁路 control 订阅（仅推到 web）
- 各 `modules/<x>/main.py`：完整自治（已基本到位，补统一 logging 配置）

**验收**：`python3 main.py` 启动后 `pgrep -f modules\\.` 看到 3 个独立 Python 进程；kill 掉其中一个，2 秒内 main.py 拉起新的；web/dashboard 短暂灰显该模块然后恢复。

### R3 — UI 动态化（1 天）

**改动**：
- `web/server.py`：删 `CHANNELS = (...)` 白名单；`push(channel, ev)` 接到陌生 channel 自动注册；新增 `/discovery` SSE 端点订阅 `av/system/discovery/#` 推前端
- `web/templates/dashboard.html`：删 4 个写死 `<section>`，留空 `<main id="grid">`；CSS grid 改 `repeat(auto-fit, minmax(420px, 1fr))` 自适应
- `web/static/dashboard.js`：删 `factories` 字典；改为 `modules: Map<name, ModuleState>`；订阅 `/discovery` 驱动 panel 增删；按 `streams[].kind` 选 renderer
- 新增 `web/static/renderers/` 目录：`transcript_seq.js` / `kv_table.js` / `mjpeg.js` 三个 renderer 模块；UNKNOWN kind fallback 成 JSON dump
- 失活灰显：`lastSeen + 2.3 × heartbeat_interval` 内没消息 → panel 加 `.offline` class（CSS opacity 0.4 + 标签"已离线 NN 秒前"）

**验收**：浏览器打开 dashboard，看到 audio/video/llm 三个 panel 按公告自动生成，不再依赖前端代码硬编码；kill audio_processor 进程，对应 panel 70 秒内变灰显示"已离线"；恢复后立即变绿。

### R4 — MJPEG 视频画面（0.5 天）

**改动**：
- `web/server.py` 新增 `/video_feed/<camera_name>` 端点：复用 `modules/video_processor/processor.py:127` 的 `get_latest_frame(name)`，`cv2.imencode('.jpg', frame)` 后 multipart yield；移植自 `/Users/yzj/Developer/woldmonitor/app.py:43-86`
- `web/server.py` 新增 `POST /camera/<name>/enable` 与 `/disable`：通过 MQTT topic `av/video/cmd/<name>` 发给 video_processor，调 `reload_sources` 启停
- `web/static/renderers/mjpeg.js`：`<img>` 挂载时调 `enable`、卸载时 5 秒 debounce 后 `disable`（避免快速切窗口频繁启停）
- `modules/video_processor/main.py`：订阅 `av/video/cmd/+`，处理 enable/disable 命令
- 多路布局：依赖 R3 的 `auto-fit` grid，1/2/3/4 路自然成 1×1/1×2/2×2 网格

**验收**：`config/system_config.yaml` 把"本机摄像头" `enabled=true` 改回；浏览器看到画面；浏览器 tab 切走 → video_processor 日志显示 disable 该路；切回 → enable，2 秒内画面恢复。

### R5 — Node-RED iframe 嵌入（0.5 天）

**改动**：
- 新增 `node-red/settings.js`：`httpAdminMiddleware` 注入 `res.removeHeader('X-Frame-Options')` + `res.setHeader('Content-Security-Policy', "frame-ancestors http://localhost:5050")`
- `start.command`：在 mosquitto/funasr 起完后，`node-red --userDir <repo>/node-red --port 1880 --settings <repo>/node-red/settings.js` 后台拉起；端口被占用则探测 1881/1882
- `node-red/.gitignore`：`flows_cred.json` 加进去（含加密 key，泄漏后 RCE 风险）
- `web/templates/dashboard.html`：顶部加 tab 条："实时面板 / 编程（Node-RED）/ 模块状态"；编程 tab 是 `<iframe src="http://localhost:1880" style="width:100%;height:80vh">`
- `dashboard.js`：tab 切走时 `iframe.src = ""` 卸载，避免后台占资源

**验收**：浏览器 dashboard 顶部 "编程" tab 能正常加载 Node-RED 编辑器；拖一个 inject 节点 + 一个 debug 节点连起来 deploy；切到"实时面板" tab 后 iframe 卸载（DevTools 看 iframe src 为空）；切回时重新加载 + flows 仍在。

### R6 — 三个新订阅模块（1 天）

**新增 `modules/system_info/`**：
- `main.py`：继承 BaseModule，5 秒一次发 `av/system/host_stats`；公告 `streams=[{topic, kind:"kv_table", title:"本机信息"}]`
- 用 `psutil.cpu_percent / virtual_memory / disk_usage`；约 50 行代码

**新增 `modules/network_info/`**：
- `main.py`：10 秒一次发 `av/system/network`；网卡列表 / IP / 收发速率（`psutil.net_io_counters` 差分）
- 公告同样是 kv_table；约 60 行代码

**新增 `modules/network_scanner/`**：
- `main.py`：订阅 `av/system/lan_scan/cmd`，触发时用 asyncio 并发扫 254 路 ×554 端口
- 进度流式发 `av/system/lan_scan/progress`，结果一次性发 `av/system/lan_scan/result`
- 公告 `streams=[{topic:".../result", kind:"kv_table", title:"局域网 IPC"}]` + 一个 inline 触发按钮（在 kv_table renderer 里加可选 `cmd_topic` 字段触发）
- 替换上版 GitHub flyfish17 同步 socket 实现；约 80 行代码（含 asyncio）

**验收**：启动 main.py，dashboard 自动多出 3 个 panel；本机信息 panel 显示 CPU/内存/磁盘；网络信息 panel 显示网卡 + 速率；局域网 IPC panel 有"扫描"按钮，点击后进度条 → 3 秒后显示扫到的 IPC 列表。**这是订阅式架构的最终验收：UI 完全没改代码，新模块就长出来了。**

---

## 关键文件清单

**待修改**：
- `/Users/yzj/Developer/av_unified_mvp/main.py`（R2 supervisor 化）
- `/Users/yzj/Developer/av_unified_mvp/core/base_module.py`（R1 协议 + LWT）
- `/Users/yzj/Developer/av_unified_mvp/core/mqtt_bridge.py`（R1 删旧 discovery）
- `/Users/yzj/Developer/av_unified_mvp/web/server.py`（R3 动态频道、R4 MJPEG 端点）
- `/Users/yzj/Developer/av_unified_mvp/web/templates/dashboard.html`（R3 删硬编码、R5 加 tab）
- `/Users/yzj/Developer/av_unified_mvp/web/static/dashboard.js`（R3 重写）
- `/Users/yzj/Developer/av_unified_mvp/modules/video_processor/main.py`（R4 订阅启停命令）
- `/Users/yzj/Developer/av_unified_mvp/modules/audio_processor/main.py`、`llm_engine/main.py`（R1 补 streams 公告）
- `/Users/yzj/Developer/av_unified_mvp/start.command`（R5 拉 Node-RED）
- `/Users/yzj/Developer/av_unified_mvp/DEVELOPMENT_PLAN.md`（R1 §4 协议表 + 进展回合）

**新增**：
- `web/static/renderers/transcript_seq.js`
- `web/static/renderers/kv_table.js`
- `web/static/renderers/mjpeg.js`
- `node-red/settings.js`
- `node-red/.gitignore`
- `modules/system_info/{__init__.py, main.py}`
- `modules/network_info/{__init__.py, main.py}`
- `modules/network_scanner/{__init__.py, main.py}`

---

## 可复用的现有资产

- `core/base_module.py:19` — BaseModule 基类，所有新模块继承
- `core/base_module.py:148` — `publish(topic, payload)` 自动加 header 包装
- `web/server.py:79` — `_make_sse(channel)` 工厂，R3 改成动态注册
- `modules/video_processor/processor.py:127` — `get_latest_frame(name)` 返回 numpy 帧，R4 直接 `cv2.imencode`
- `modules/video_processor/processor.py:101` — `reload_sources(new_sources)` 热重载，R4 用它实现 enable/disable
- `/Users/yzj/Developer/woldmonitor/app.py:43-86` — `gen_mjpeg()` multipart yield 模板，R4 移植
- 上版 `flyfish17/av_unified_mvp` 的 dashboard.py 中 554 扫描逻辑 — R6 重写为 asyncio 并发版本

---

## 端到端验证

每阶段独立验证标准已在切片中给出。**最终联调**（R6 后）：

1. 关 Docker（用户主动）→ `./start.command` 自动切 light 档（Bug B 已修）
2. dashboard 打开 `http://localhost:5050`：看到 audio / video / llm / system_info / network_info / network_scanner / Node-RED tab 共 6 panel + 1 编程 tab，无任何写死代码
3. 对麦克风说"打开二楼餐桌空调"：transcript panel 出 partial→final 气泡；intent panel 出 command_failed（ollama 没起）；编程 tab 切到 Node-RED 看 flow function 节点 warn 输出翻译结果到 av/control
4. 摄像头 enable 一路 → MJPEG 画面出现；再 enable 三路 → 自动 2×2 布局
5. 点 network_scanner panel 的"扫描"按钮 → 3 秒内列出局域网 IPC
6. kill `modules.audio_processor.main` 进程：transcript panel 灰显"已离线"；2 秒后 supervisor 重拉，恢复绿色
7. `mosquitto_sub -t 'av/system/discovery/#' -v`：看到所有模块周期 heartbeat + LWT offline 行为正确

---

## 挑剔食客视角（已并入计划）

1. **MQTT retain 配 LWT**（R1 必做）：避免僵尸 retain 消息把"已离线"模块伪装成在线
2. **renderer 类型表先 3 种封顶**：避免过度设计；scrollback_log / chart_timeseries / iframe 用到再加
3. **MJPEG 复用内存帧**（R4）：不开第二条 RTSP，CPU 不翻倍
4. **不照抄 woldmonitor 轮询**：我们已有 SSE，事件类数据走 SSE，画面走独立 `<img>`，分工明确
5. **flows_cred.json 必须 gitignore**（R5）：含加密 key 泄漏 = Node-RED 任意 RCE
6. **554 扫描用 asyncio**（R6）：上版 30s 阻塞用户原话要避免

---

## 工期与风险

- **总计 4.5 天**（R1×0.5 + R2×1 + R3×1 + R4×0.5 + R5×0.5 + R6×1）
- **风险点**：
  - R2 supervisor 改造可能暴露子模块独立时的隐藏依赖（如 modules/audio_processor/main.py 是否所有路径都补全）—— 改前先 `python3 -m modules.audio_processor.main` 跑通，再改 main.py
  - Node-RED iframe 的 X-Frame-Options 在不同 Node-RED 版本表现不一致 —— 备用方案：tab 切到"编程"时直接 `window.open('http://localhost:1880')` 新窗口
  - MJPEG 在 Safari 上对 multipart/x-mixed-replace 兼容性偶尔抽风 —— 用户主用 Chrome，先不管
- **每阶段单独验收，任意阶段发现走偏可立即中止，已完成阶段可独立保留价值**
