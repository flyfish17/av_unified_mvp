# av_unified_mvp 开发计划与进展

> 本文是项目长期开发蓝本。每次开发结束后请更新「进展」与「下次切入点」两节，
> 保证下一次（人或 AI）能 5 分钟内重新接手。

---

## 0. 快速接手（AI / 新人读这里就能开始）

| 项 | 值 |
|---|---|
| 项目目录 | `/Users/yzj/Developer/av_unified_mvp` |
| iCloud 源目录（同步终点） | `/Users/yzj/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp/` |
| 启动入口 | `./start.command`（双击 or `bash`），自动起 mosquitto + funasr-2pass + Node-RED + main.py + 浏览器 |
| 浏览器地址 | `http://localhost:5050`（dashboard）, `http://localhost:1880`（Node-RED） |
| **当前主线** | **R1–R6 订阅式架构演进**（见 §10），总工期 4.5 天 |
| **当前进度** | **阶段一 ✅** + **巩固冲刺 K1-K5+K8 ✅** + **辽河 3588 sprint 进行中**（2026-05-11 启动，分支 `sprint/liaohe-3588`，回滚锚点 tag `pre-liaohe-sprint-2026-05-11`）。阶段 1 Mac 讯飞观感 baseline ✅ 完成（1.1 partial 逐字蹦 + 1.2 流式降噪 + 1.3 final 定稿动画）。**下一步进阶段 2：3588 端转写复刻 + 三阈值判定**。完整 plan 文件：`~/.claude/plans/3588-demo-1-50-mac-3588-3588-2-3588-ai-streamed-riddle.md` |
| 下一步具体动作 | 见 §11 下次切入点 |
| 已完成历史 | P0 离线 / P1 模块统一 / P2 Node-RED / P3 拆 SSE / Bug A/B / 联调 — 详见 §5 简报 |
| 计划文件 | `./PLAN_R1_R6_subscription.md`（R1-R6 详细设计，跟随项目同步） |

**5 分钟接手三步**：
1. 读本文 §0 + §10 进度表 + §11 切入点
2. 看 `./PLAN_R1_R6_subscription.md` 当前阶段详细设计（含每阶段验收标准、关键文件清单、风险预案）
3. 看 §6 最新一条进展确认上次"做完了什么"，然后从 §11 切入点的命令开干

---

## 1. 产品定位

**端侧"理解 → 编排 → 执行"系统**：

- 摄像头 + 麦克风 → 模块化的"理解层"输出语义事件（看到什么、听到什么）
- 事件经 MQTT 总线流转，**Node-RED 负责场景规则编排**（用户可拖拽改）
- Flask + 原生 JS 前端订阅事件流做实时展示
- 所有组件**优先离线**，可在边缘盒子（RK3588/Jetson/Mac mini）独立运行

参考前端订阅风格：`/Users/yzj/Developer/woldmonitor`（单文件 Flask + MJPEG/SSE 长连接 + 原生 JS）

---

## 2. 目标架构（六层）

```
┌─ 1. 感知层 Capture ──────────────────────────────┐
│  RTSP/USB 摄像头   |   麦克风                    │
└─────────┬───────────────┬────────────────────────┘
          ▼               ▼
┌─ 2. 理解层 Understand（每个都是独立模块/进程）─┐
│  modules/audio_processor   语意：FunASR 2pass    │
│                            partial+final+ITN+修正│
│  modules/video_processor   视觉：YOLO（+VLM 可选）│
│  modules/llm_engine        意图：分类 + 指令生成 │
└─────────┬─────────────────────────────────────────┘
          ▼  MQTT publish
┌─ 3. 总线层 Bus ──────────────────────────────────┐
│  本地 mosquitto :1883                            │
│  topic 协议见 §4                                 │
└─────────┬─────────────────────────────────────────┘
          ▼  pub/sub
┌─ 4. 编排层 Orchestrate ──────────────────────────┐
│  Node-RED :1880                                  │
│  用户拖拽：condition → action                    │
│  HTTP in/out、function 节点对外开放              │
└─────────┬───────────────────────┬─────────────────┘
          ▼                       ▼
┌─ 5. 展示层 Present ──┐   ┌─ 6. 执行层 Act ───────┐
│  Flask + 原生 JS     │   │  设备桥接 / HA / IR    │
│  /events/transcript  │   │  订阅 av/control       │
│  /events/video       │   │                        │
│  /events/intent      │   │                        │
└──────────────────────┘   └────────────────────────┘
```

设计原则：
- **模块独立**：`modules/<x>/main.py` 可独立 `python -m` 启动，仅依赖 MQTT
- **协议先行**：MQTT topic schema 是合同，跨模块协作只看 schema
- **前端只订阅**：浏览器端不直接 connect ASR/YOLO，只走 SSE/HTTP

---

## 3. 语意理解模块的能力（已升级）

| 能力 | 实现 |
|---|---|
| 实时转写 | FunASR runtime 2pass（Docker），mode="2pass" |
| 标点 | use_itn=true + punc_ct-transformer + thuduj12/fst_itn_zh |
| 流式 partial | online paraformer 边说边出，`raw_mode=2pass-online` |
| 整句修正 | 句末 VAD 触发 offline paraformer 整段重判，`raw_mode=2pass-offline`，前端复用同 `seq_id` 气泡覆盖 |
| 兜底降级 | WS 5 次连不上 → 自动切 SenseVoiceSmall 本地（无 partial） |
| 模块独立 | `modules/audio_processor/main.py` 通过 MQTT 发布事件，可独立运行 |

**事件载荷规范**（`TranscriptEvent` → MQTT/SSE）：
```json
{
  "text": "打开二楼餐桌空调",
  "is_final": true,
  "seq_id": 42,
  "ts": 1712345678.91,
  "raw_mode": "2pass-offline"
}
```

---

## 4. MQTT topic 协议（R1 后版本）

### 数据流 topic

| topic | 谁发 | 谁订 | 关键字段 |
|---|---|---|---|
| `av/audio/partial` | audio_processor | web、Node-RED | `text, seq_id, is_final=false, raw_mode` |
| `av/audio/command` | audio_processor | llm_engine、web、Node-RED | `text, seq_id, is_final=true` |
| `av/video/detect` | video_processor | web、Node-RED | `camera, time, detections[]` |
| `av/video/cmd/<camera>` | web 控件 | video_processor | `enable=true/false`（R4 上线，按需启停摄像头解码） |
| `av/llm/event` | llm_engine | Node-RED、web | `event_type, original_text, intent, command, confidence` |
| `av/control` | Node-RED / llm_engine | 设备 / web `_on_control` | `target, action, params, original_text` |

### 公告 / 系统 topic（R1 统一）

| topic | 谁发 | 谁订 | 协议 |
|---|---|---|---|
| `av/system/discovery/<module>` | 所有 BaseModule 子类 | UI / 监控 | retain=true，QoS=1，配 LWT。载荷见下 |
| `av/system/host_stats` | system_info（R6） | UI | CPU / 内存 / 磁盘，每 5s |
| `av/system/network` | network_info（R6） | UI | 网卡 / IP / 收发速率，每 10s |
| `av/system/lan_scan/{cmd,progress,result}` | UI ↔ network_scanner（R6） | 互相 | 触发 / 进度 / 结果 |

**公告载荷 schema**（`av/system/discovery/<module>`）：
```json
{
  "module": "audio_processor",
  "client_id": "av_box_001",
  "ip": "192.168.x.x",
  "ts": 1746348000.0,
  "event": "online | heartbeat | offline",
  "heartbeat_interval": 30,
  "version": "1.2",
  "streams": [
    {"topic": "av/audio/partial", "kind": "transcript_seq", "title": "实时转写"}
  ],
  "endpoints": [
    {"kind": "mjpeg", "name": "本机摄像头", "url": "http://host:5050/video_feed/本机摄像头"}
  ]
}
```

- **kind 类型表**（R3 实现 3 种，其它 fallback JSON）：`transcript_seq` / `kv_table` / `mjpeg`
- **失活判定**：UI 用 `lastSeen + 2.3 × heartbeat_interval` 内未收到任何消息 → 灰显，不删除
- **LWT 行为**：模块崩溃 / 强杀 → broker 自动发 `event=offline` retain，新订阅立即看到
- 旧 `av/discovery` 单层协议已废弃（R1 移除）

变更协议时**必须**同步更新本节、`config/system_config.yaml` 的 `topics:` 与 Node-RED flows。

---

## 5. 开发任务（按优先级）

### P0 — 严格离线（必须先完成）
- [x] 起本地 mosquitto，`config/system_config.yaml` `mqtt.broker` 改为 `127.0.0.1`
- [x] 全链路自动化已通：MQTT/SSE/WS/YOLO 全部正常（见 §6 2026-05-03 #2）
- [x] 真实"拔网测试"通过：关 Wi-Fi 后说『打开二楼餐桌空调』→ FunASR 11 partial + 5 final 正常出（含 2pass-online/offline 切换）→ MQTT 总线正常，无任何外网域名访问失败。详见 §6 回合 10
- [x] 关掉模型在线检查：`start.command` 的 `docker run` 加 `-e MODELSCOPE_DOMAIN=`；旧容器自检 + 提示重建（见 §6 回合 9）。**注意**：`run_server_2pass.sh` 用 `parse_options.sh` 严格解析参数，`--disable-update` 不在白名单会让脚本 `exit 1`，所以只走 env 变量这一条路

### P1 — 模块统一（修正架构偏离）
- [x] **把 `core/audio_processor.py` 的 2pass 实现搬到 `modules/audio_processor/processor.py`**
- [x] `main.py` 改为 `from modules.audio_processor.processor import AudioProcessor`
- [x] 删 `core/audio_processor.py`（保留 `core/base_module.py`、`core/mqtt_bridge.py` 等基础设施）
- [x] `modules/audio_processor/main.py` 启动后通过 MQTT 发 `av/audio/partial` + `av/audio/command`
- [x] `core/video_processor.py` vs `modules/video_processor/processor.py` 双份合并到 modules/，删 core 副本
- [x] `core/llm_engine.py` vs `modules/llm_engine/engine.py` 双份合并到 modules/，删 core 副本

### P2 — Node-RED 编排
- [x] 旧 `flows.json`（763 行 CREATOR 移植版）归档为 `flows_legacy_creator.json`，topic（`creator/control/voice`、`audio_intent` 等）完全不合 §4
- [x] 新建最小骨架 `flows.json`：`av/audio/command` → 关键词翻译 → `av/control`，含 inject 模拟节点 + `av/#` 旁路 debug
- [x] README 加「Node-RED 编排」一节：导入步骤 + 加新场景的 4 步最小流程
- [x] 端到端验证：用 `node-red --userDir /tmp/av_nr_test --port 1881` 起隔离实例（不动用户 ~/.node-red），mosquitto_pub 模拟 5 条 final → mosquitto_sub 旁路 av/control 全部通过（见 §6 回合 8）
- [ ] 接 IR / HA / Zigbee 设备桥（属于 P4）

### P3 — 前端订阅面板（仿 woldmonitor 风格扩展）
- [x] `web/server.py` 拆多路 SSE：通用 `push(channel, ev)` + `_make_sse(channel)` 工厂注册 4 路（`/events/transcript|video|intent|control`），保留 `push_event` 别名向后兼容
- [x] 单页面板四区域分别订阅：`web/templates/dashboard.html`（CSS grid 2x2）+ `web/static/dashboard.js`（每区独立 EventSource，每区独立渲染器）；`/transcript` 路径保留旧单页兼容
- [x] lazy import：`web/server.py` 通过 `_get_flask()` 延迟加载 flask；缺非 web 依赖（cv2 等）由 `main.py` 在视频/音频模块各自的 try/except 拦截，与 web 无关
- [x] mock 数据端点：`POST /mock/<channel>` 直接把 body 当 payload 推到对应 channel

### P4 — 执行层 & 场景化
- [ ] `_on_control` 桩接真实设备（IR/Zigbee/HA）
- [ ] 场景全部沉到 Node-RED，主程不写业务

---

## 6. 进展（按时间倒序）

### 2026-05-08 (回合 29) — L3 摄像头自动化 + P0 二阶段（分布式协议）+ husion 跨品牌桥接 + r28-snapshot 上传

#### 用户方向再校准（关键）

- 业务护城河 = 理解 → 执行（讯飞没有的）。L3 摄像头识别 + 环境感知是项目最完整差异化。
- 跨品牌桥接定位："**主**消费 + **辅**贡献，**不替代原厂家管理平台**"。讯飞做转写、creator/husion 做分布式视频管理；我们只做"语音控制底层物理 + AI 视听理解的桥梁"。
- 当前阶段不过度复杂化，能体现跨品牌跨系统桥接就用。
- 二楼餐桌定位：**复式跃层** — 吧台窗帘 + 餐桌灯带 1/2 与二楼餐桌空调物理上是同一个空间，靠 catalog `also_in: ["2FDiningTable"]` 字段共享。

#### ✅ L3 摄像头识别 + 环境自动化（Node-RED 编排）

**L3.1 video_processor 加 av/env/brightness 周期发布**
- `modules/video_processor/processor.py` capture loop 每 10s 算一次 `cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean()`，publish 到 `av/env/brightness` payload `{camera, brightness, ts}`（0-255 数值）。

**L3.2 Node-RED 规则 1 — 人检测 → 灯带 2 + 5min 无人自动关**
- mqtt-in `av/video/detect` → function 状态机（边沿触发：lit=false → ON + 重置 5min off timer；持续 person 不 spam；setTimeout 在 5min 无新检测后自动发 OFF）→ mqtt-out `av/control`
- function 节点 `initialize` 字段在部署/重启时 reset `flow.l3_rule1_lit=false` + 清 timer，避免 state stuck
- 实测：cold start 后第一帧 person 来即 fire `DiningTable_Light2_On` 到 av/control，物理灯亮

**L3.3 Node-RED 规则 2 — 13:00 + 大太阳 → 拉窗帘 1s**
- mqtt-in `av/env/brightness` → function 缓存 `flow.l3_brightness`
- inject (cron `0 13 * * *`) → function 检查 brightness > 180 + 5 分钟内有效数据 → 输出双 msg：[立即 close, delay 1s 后 stop] → mqtt-out `av/control`
- 行为："关帘 1 秒"= 发 `BarCounter_Curtain_Close` 然后 1 秒发 `_Stop`，电机走 1 秒部分合帘（不完全关）

**Node-RED flows 节点共 60 个**（48 + 12 新增），脚本 `/tmp/add_l3_flows.py` 幂等可重跑。

#### ✅ 顺手三项（回合 28 遗留清理）

1. **engine.py 移除 `self._lock`**：连续语音输入会导致 4+ 分钟卡死的根因。ollama serve 自带请求队列，外部 lock 多余。删除 `with self._lock:` 解锁后，多次调用并发交给 ollama 自己排。
2. **video_processor 写回 yaml 持久化**：`_add_source / _update_source / _remove_source / _toggle_camera` 末尾调 `_persist_sources()`，原子替换写 `config/system_config.yaml` 的 `video.sources`。重启 main.py 后动态加的源不再丢。
3. **classify_intent 关键词从 catalog derive**：原 `CONTROL_KEYWORDS` 硬编码 19 词（"打开/关闭/灯光/空调"等），引擎 `_build_keywords_from_catalog()` 从 `device_catalog.json` 的 `device_types.label` + `actions_label` + `locations.label` 自动 derive，启动时拉到 49 个关键词（含"筒灯/虚光/发光字/轨道灯/二楼餐桌/会议室1"等以前漏的）。新加 catalog 指令零代码生效。

#### ✅ P0 第二阶段：分布式协议解析 + 实测（user D-激进授权范围）

**Creator 分布式网关 v3.0**（HTTP :23282 + token + JSON）
- 14 个 endpoints 协议解析（getToken/openWindow/switchSrc/cleanScreen/callPlan/queryVersion/deviceStatus/allDeviceState/setAudio/closeAudio 等）
- 网络扫描定位：12 台开 :23282（.15/.16/.31-.45/.234/.235）；只有 `.16` 是有效网关（其它 502 Bad Gateway，是被网关代理的节点）
- 实测：getToken admin/123 返回 token，queryVersion 返回 V3.2.0；allDeviceState 返回 device 数组（mock 示例 IP，可能 .16 是测试网关未注册真实拓扑）
- 主功能定位：**视频墙拼接 + 切源 + 预案** — 与 creator 中控（192.168.5.20:8932 ASCII 物理控制）完全两类协议
- 模块代码本回合**未实现**（先验证协议链路通，等业务需求明确再写完整 modules/creator_distributed）

**Husion 白鲨 v9.4.8 协议**（TCP :6000 + JSON `hscmd-*`）
- 39 个 hscmd-* 接口（涵盖设备列表/切换信号/视频墙窗口/字幕/预案/串口转发/USB 同步等）
- 网络扫描：.253 单台开 :6000 = HDC900 9 路一体机（9 个分布式盒子合一，外部一个 IP）
- 实测：`hscmd-get-rx-shark-config` + `idList=[5001..5009]` 返回 9 设备完整数据：name/id/ip/hls(`ws://...flv`)/isSignal/online。3 路有信号（无纸化电脑 1/2/3），其它 6 路无信号
- 协议要点：必须传具体 idList（空数组返回空 cmd_body）；hls 字段是 ws://flv（WebSocket-FLV，需 flv.js 库播放，不是 RTSP）
- 关键现象：husion 内部分布式网段是 192.168.150.x，外部访问需把子网掩码改成 `255.255.0.0`（/16）让 192.168.5.x 主机能直连 .150.x（用户实测）

#### ✅ husion 跨品牌桥接（A 方案，1h ship）

按用户原话"主消费 + 辅贡献，不替代"，先做"主"：从 husion 拉 9 路设备到 av_unified_mvp 视频源池。

- **新模块 `modules/husion_distributed/`**：
  - BaseModule 子类，30s poll `hscmd-get-rx-shark-config` 拿设备列表
  - 转成 endpoints `[{kind: "husion_stream", name, device_id, stream_url, stream_type: "flv", is_signal, online, label}]`
  - 重新发布 discovery 让前端实时刷新
  - 命名陷阱：`self.port` 跟 BaseModule 的 `self.port`(mqtt) 冲突 → 改名 `self.husion_port`
- **`web/server.py` 加 `GET /distributed/husion/devices`**：从 discovery snapshot 返回最新 endpoints
- **`web/static/lib/flv.min.js`**（141KB 离线）+ `dashboard.html` 引入
- **在线视频源卡升级**：select 自动多出 `optgroup label="🌐 Husion HDC900（9 路·跨品牌桥接）"`，9 个 option（带信号状态色）；play(url) 按协议分流（`ws://flv` → flv.js / `m3u8` → hls.js / 其它 → native）；30s 自动 refresh husion 列表
- **用户实测**：列表正常 + 选有信号源 → flv.js 立即播放 ✅（前提：Mac Studio 子网掩码改 /16 让 .150.x 可达）

#### ✅ r28-snapshot 上传 GitHub（开发固化）

- `.gitignore` 加：node_modules / .config.* / .lock / .bak / .claude / config/system_config.yaml（含 RTSP 密码）
- 留 `config/system_config.example.yaml`（密码改占位 `${IPC_PWD}`）作模板
- 新建分支 `r28-snapshot`，commit b1a5074：**55 files / +9382 / -1969 行**
- push 到 `origin/r28-snapshot`，**main 不动**保留 v1.1 干净
- PR 链接：https://github.com/flyfish17/av_unified_mvp/pull/new/r28-snapshot

#### 📋 文件改动清单（回合 29）

```
modules/video_processor/processor.py      ← 加亮度采样
modules/video_processor/main.py           ← 加 _persist_sources，写回 yaml
modules/llm_engine/engine.py              ← 移除 _lock + classify_intent catalog derive + Session(trust_env=False)
modules/husion_distributed/{__init__.py,main.py}  ← 新模块（TCP poll + flv 流发现）
main.py                                    ← MANAGED_MODULES 加 husion_distributed
config/system_config.yaml                 ← 加 husion 段；2FDiningTable also_in；移出 git
config/system_config.example.yaml         ← 新增（脱敏模板）
config/device_catalog.json                ← BarCounter_Curtain + DiningTable_Light1/2 加 also_in: ["2FDiningTable"]
node-red/flows.json                       ← +12 节点（L3 规则 1/2 + 亮度缓存 + cron 13:00）
web/server.py                             ← +GET /distributed/husion/devices
web/static/lib/flv.min.js                 ← 新增（141KB 离线）
web/templates/dashboard.html              ← 在线视频源卡升级支持 flv + husion 自动注入
.gitignore                                 ← 加 node_modules/.config/.bak/.claude/system_config.yaml
DEVELOPMENT_PLAN.md                       ← 本节
/tmp/add_l3_flows.py                      ← 幂等脚本（L3.2/3 节点插入）
```

#### 🟢 当前完整能力（用户验收的"质的飞跃"）

| 维度 | 能力 |
|---|---|
| 感知 | YOLO 视频检测 + FunASR 2pass 流式转写（含 partial/final/标点 ITN） + 摄像头亮度采样 |
| 理解 | qwen3.5:9b LLM 意图翻译（catalog driven prompt 76 指令 + 笼统词灵活匹配） |
| 编排 | Node-RED 60 节点（av/control 转发 + L3 规则 1/2 + 大屏 SVG 流转图） |
| 执行 | creator 中控 ASCII（76 物理设备指令） + Node-RED 短连接 TCP |
| 桥接 | husion HDC900 9 路设备发现 + flv.js 浏览器播放 + ws://flv 跨品牌融合 |
| UI | GridStack 拖动 + 8 模块卡 + 视频源 CRUD + LAN 扫描一键填表 + 单聚合 SSE |
| 自动化 | 人检测 → 开灯 + 5min 无人 → 关 / 时间 + 亮度 → 拉窗帘 1s |

#### ✅ husion 网络方案（用户实测确定 — 替代之前 README 里"改 /16"的错方案）

之前 README 写"改子网掩码为 255.255.0.0（/16）"让 mac 能直连 .150.x — **错的**：mac GUI 改子网时默认网关被清掉，会断网。

**正确方案：保留原 /24 + ifconfig alias 给网卡追加第二 IP**

```bash
# Wi-Fi 通常是 en1（networksetup -listallhardwareports 确认）
sudo ifconfig en1 alias 192.168.150.250 netmask 255.255.255.0
ping -c 3 192.168.150.1   # husion 内部，应通
ping -c 2 baidu.com        # 互联网，仍通（默认网关 .5.1 不变）
```

**用户在 Mac Studio 实测通过**：alias 加完后 ping .150.x 通 + 互联网正常 + 浏览器播 husion ws://flv 流流畅。

持久化 LaunchDaemon plist 写进 README（开机自动加 alias）。

**为什么 alias 比 /16 干净**：
- /16 让 mac 把整个 192.168.0.0/16 当本地直连 → 默认网关 .5.1 在 GUI 改时被一起清掉 → 互联网走不通
- alias 是给同一物理网卡追加第二个 IP/子网 → 原 /24 配置 + 网关完全保留 → 互联网照常 + 多了一条 .150.x 直连路径

#### 🔍 Creator 分布式协议二次评估（用户提示真实路径后）

**第一次评估走错路**：按 PDF v3.0 协议文档用 HTTP :23282 + admin/123 测 .16 网关，14 endpoint 协议层通但是 mock 数据（设备列表是 192.168.1.10/.11 文档示例 IP）；真实业务 endpoint（openWindow/switchSrc 等）全部 code=3。

**用户截图给真实路径**：**TCP :12121 + JSON + 密码 `123456`**（不是 PDF 写的 :23282 / :123）：
```
13:32:35 → {"cmd":"login","user":"admin","password":"123456"}
13:32:35 ← {"cmd":"login","code":0,"token":"a66abb..."}
```
用户在该路径下手动测通了 openWindow / switchSrc。

**Claude 端再测**：连续 3 次 login 都返回 `code=3`。怀疑：admin 用户单 session 限制，user 的 TCP 调试工具仍占着 session 锁；或者 server 拒绝特定来源的并发登录。

**结论**：
- 协议路径正确（PDF 文档不全或版本不一致）
- 真实生产凭据：admin / 123456 / TCP :12121
- 实测被 user 工具阻塞，**driver 实施暂停**，等 user 自己再测过 / 让出 session 后再启动

#### 🔬 Creator 分布式协议 三次测试（user 让出 session 后做的纯只读探查）

User 给关键 hint：先 `logout` 释放 session 再 `login`，**token 不变**（admin 永久 token `a66abb5684c45962d887564f08346e8d`）。

| 测试 | 请求 | 响应 | 结论 |
|---|---|---|---|
| logout | `{"cmd":"logout","token":"a66abb5684..."}` | `{"cmd":"logout","code":0}` | ✅ 释放 session |
| login | `{"cmd":"login","user":"admin","password":"123456"}` | `{"cmd":"login","code":0,"token":"a66abb5684..."}` | ✅ token 与 user 提示一致**完全不变** |
| queryVersion | `{"cmd":"queryVersion","token":...}` | `{"cmd":"closeAudio","code":0,"version":"V3.2.0"}` | ✅ code 0，⚠️ **响应 cmd 字段是 closeAudio 不是 queryVersion**（server 端 bug，不影响 version 解析） |
| allDeviceState onoff=1 | `{"cmd":"allDeviceState","token":...,"onoff":1}` | `{"cmd":"allDeviceState","code":0,"device":["192.168.1.10","192.168.1.11"]}` | ⚠️ 仍是 PDF 示例 mock IP |
| allDeviceState onoff=0 | 同上 onoff=0 | 同上 2 台 | 同上 |
| deviceStatus 192.168.1.10 | `{"cmd":"deviceStatus","token":...,"deviceIp":"192.168.1.10"}` | `{"cmd":"deviceStatus","code":0,"deviceIp":"192.168.1.10","hdmi":0,"onoff":0}` | ⚠️ 离线 + 无 HDMI 信号 |

**核心结论**：
1. ✅ **协议链路 100% 通**：logout / login / queryVersion / allDeviceState / deviceStatus 都返 code=0
2. ✅ **token 永久不变**：admin 的 token 是 `a66abb5684c45962d887564f08346e8d`，driver 实现可以**不用每次拿新 token**（除非重启 server）
3. ❌ **.16 这台 server 没注册真实分布式拓扑**：返回的 192.168.1.10 / .11 是 PDF 文档示例 IP，物理上离线
4. 🔶 **真实业务网关在哪**：user 截图当时测通的 openWindow / switchSrc 应该不是发到 .16，而是**别的网关**或**正确的 srcDevIp/outputIp 不是 .1.10/.11**

**Sprint B 启动前置（user 提供以下任一即可）**：
- 真实生产网关 IP（如果不是 .16）+ 凭据
- user 截图当时测过的 `srcDevIp` 和 `outputIp` 实际值（多半是某个真实拓扑设备的 IP）
- 或者：user 在 .16 网关 admin 后台**注册分布式拓扑**让 allDeviceState 返真实设备

#### 🔬 Creator 分布式协议第 4 次测试（user 给真实拓扑后纯只读）

User 截图给 admin 配置界面真实拓扑（全部在 192.168.5.x 网段）：

| 角色 | IP | 角色 | IP |
|---|---|---|---|
| LED 拼接屏 001 | 192.168.5.234 | 销售部电视 | 192.168.5.18 |
| LED 拼接屏 002 | 192.168.5.235 | 采集卡 | 192.168.5.15 |
| 技术部电视 | 192.168.5.12 | 研发部电视 | 192.168.5.13 |
| 运营中心左显示器 | 192.168.5.17 | 运营中心右显示器 | 192.168.5.16（也是协议 server） |

**实测**：
1. **deviceStatus 8 个真实 IP**：全返 `code:0, onoff:0, hdmi:0`（不是 user 截图里的"在线"状态）
2. **探 9 个候选 IP 的 :12121**：只有 192.168.5.16 接受协议（其它 connection refused），**确认 .16 是唯一协议 server**
3. **allDeviceState** 仍返 PDF 示例 mock IP（192.168.1.10/.11），不返真实拓扑

**矛盾分析**：
- .16 协议接口接受真实 IP 的 deviceStatus 查询（不报"未知设备"），说明 IP 是合法
- 但 onoff/hdmi 都返 0 + allDeviceState 不返真实列表 — **server 端跑的是默认 / 测试 namespace**，不是 user 截图的 admin 视图同一份数据
- user 截图当时测通的 openWindow / switchSrc 应该**确实可以工作**（因为 IP 合法），只是 read APIs 返的是无效默认值

**启示**：
- 协议**写操作**可能正常（只是 read APIs 不可信）
- Sprint B driver 实施时**不能依赖 deviceStatus / allDeviceState 做拓扑发现**，要么从 user 提供的静态 catalog 拿真实 IP，要么扫局域网定位
- 真实可用的**最小验证**只能通过**发 openWindow** + 物理观察确认（写操作有副作用，需 user 在场授权）

**Sprint B 实施建议**（更新）：
1. driver 不做拓扑自动发现，从 `config/system_config.yaml` 的 `creator_distributed.devices` 段读真实 IP 列表（user 维护）
2. 或者从 catalog 加段，与 76 中控指令统一管理
3. 实测开窗 / 切源 / 调预案 / 清屏 — 等 user 在场观察一次后启用

**如果开始做 modules/creator_distributed**：
- 仿 husion_distributed 模式：BaseModule + TCP poll + 暴露 endpoints
- 关键 endpoint：login / queryVersion / allDeviceState / openWindow / switchSrc / cleanScreen / callPlan
- 注意 token 持久化（PDF 说永久，但实测 a66abb... token 已过期 — 需要每次 login 拿新）
- 注意 single-session：admin 一个 token 同时只允许一处用？要做"如果 code=3 重 login"机制

#### 🟡 已知遗留 / 下次顺手

- **husion 辅模式（事件回传）**：用户原话"把视频结果『有人』等推回就好" — **不是**字幕推到墙，而是结构化事件回传给 husion 系统作数据源；husion 那侧接收方式未明（订阅 av/video/detect？webhook？专用 endpoint？），等需求确认再做
- **creator 分布式完整 driver**：协议路径已找到（TCP :12121），实施待 user 测试确认 session 行为后启动
- **L3.3 cron 13:00 实际验证**：等到下午 1 点自然触发才能确认（亮度数据已实测在缓存）
- **鲲景观/走廊灯 D-激进实测**：未触发，需要 creator 中控连接稳定 + 在场观察

---

### 2026-05-07 (回合 28) — P0 端到端：语音 → 意图 → creator 中控 → 物理设备（L1 + L2 全通）

#### 业务背景

护城河 = 理解 + 执行（讯飞没有的）。本回合把"端到端 demo"从 mock 推到真实硬件——客户业务现场 creator 中控主机 192.168.5.20:8932 + 76 条 ASCII 指令（CSV 来源）。

#### ✅ 设备目录（catalog 即真相）

`config/device_catalog.json`：把 CSV 转成结构化 JSON。
- host: { ip 192.168.5.20, port 8932, protocol tcp }
- 16 个 locations（按 category 分组：default/main/meeting/common/service/feature）
- 13 个 device_types（含中文 label + icon + actions_label 字典）
- 76 条 commands，每条 { id, location, device, action, label }

**复式跃层支持**：command 可声明 `also_in: ["2FDiningTable"]` 让多地点共享。回合内已加：
- `BarCounter_Curtain_*` (3 条窗帘) → `2FDiningTable`
- `DiningTable_Light1/2_On/Off` (4 条灯带) → `2FDiningTable`

`web/server.py` 新增 `GET /config/device_catalog` 端点（实时 send_file，无需重启）。

#### ✅ Node-RED av/control → ASCII → TCP 转发链路

`/tmp/add_av_control_flow.py` 幂等脚本插入 3 个新节点到 flows.json：
- `mqtt in` 订阅 `av/control`
- `function` 解析三种 payload（cmd / command / location+device+action）拼 ASCII
- `tcp out` 独立短连接节点（`end: true`，跟用户实测 `(echo -n; sleep 0.3)|nc 192.168.5.20 8932` 行为完全一致 — 关键发现：creator 接受**纯 ASCII 无 CRLF + 连接关闭即解析**）

旧 tcp out 节点（长连接，给 ollama 翻译链用）保持不动，避免破坏其他 flows。

#### ✅ L1 前端「快捷控制」模块卡（第 8 卡）

总览页加新模块卡：
- 地点 dropdown（默认二楼餐桌）
- 选地点 → 渲染该地点所有 commands，按 device 分组
- 视觉提示：On/Open/TempDown 用冷色（accent-2），Off/Close/TempUp 用暖色（live）
- 点按钮 → POST `/mqtt/publish` av/control `{cmd}`，badge 即时反馈

#### ✅ L2 语音控制：catalog 驱动 LLM prompt + 容错三件套

`modules/llm_engine/engine.py`：
- 新增 `_build_command_prompt_from_catalog()`：启动时读 catalog，按 location 分组（含 also_in）自动生成 76 条全量 prompt 字典
- prompt 加 **灵活匹配规则**：笼统"灯/灯光"按优先级 Light > Light1 > TrackLight > Downlight 选默认；标点忽略；TempUp/Down 同义词
- `generate_command()` 输入侧 **去中文标点**（FunASR ITN 加的句号/逗号对严格匹配是噪声）
- `generate_command()` 输出侧 **规范化** `{cmd: "ASCII"}` 单一字段（兼容旧 LLM 各种格式）
- HTTP Session **`trust_env=False`**：完全绕过 http_proxy/https_proxy 环境变量（关键 — Clash 等代理曾导致 127.0.0.1:11434 也被劫走 → 404）

config 改：`model_fast/smart` 从 `gemma-4-e4b-it-mxfp8`（本地 ollama 没有）改成 `qwen3.5:9b`（本地实测 1.8s 出 JSON）。

#### 📋 文件改动清单（回合 28）

```
config/device_catalog.json                        ← 新建（76 条 + locations + device_types）
config/system_config.yaml                         ← model_fast/smart 改 qwen3.5:9b
web/server.py                                     ← +GET /config/device_catalog
web/templates/dashboard.html                      ← 第 8 卡 + 表单 CSS（约 50 行）
web/static/dashboard.js                           ← +setupQuickControl + MODULES_META 加 8 卡
modules/llm_engine/engine.py                      ← prompt 自动生成 + 去标点 + Session trust_env=False + 输出规范化
modules/video_processor/main.py                   ← 已有 add/update/remove（回合 27）
node-red/flows.json                               ← +3 节点（mqtt in + function + 短连接 tcp out）
node-red/flows.json.bak.before-p0                 ← 回合 28 前备份
/tmp/add_av_control_flow.py                       ← 幂等脚本（含 function code + tcp out end:true）
DEVELOPMENT_PLAN.md                               ← 本节
```

#### 🟢 验收

注入 6 条带各种噪声的样本，LLM 命中率 6/6：
```
✅ 「。关闭餐桌灯」      → DiningTable_Light1_Off
✅ 「，打开运营中心灯光」 → OperateCentre_Light_On
✅ 「。关闭餐桌灯，带」   → DiningTable_Light1_Off
✅ 「打开二楼餐桌灯光」   → DiningTable_Light1_On    （also_in 共享）
✅ 「打开二楼餐桌灯带2」  → DiningTable_Light2_On
✅ 「。关闭。二楼餐桌空调」→ 2FDiningTable_AirConditioner_Off
```
用户原话："窗帘、空调指令正确"+"灯光类（已修后）可以"+ 物理设备实测对应响应。

#### 🔍 排错过程留痕（防下次踩同样坑）

- creator 接受字节格式 = `echo -n CMD | nc IP PORT`（无 CRLF、连接关闭即解析）。第一次加 `\r\n` + 长连接 tcp out 不动作。换 `end: true` 短连接 + 不加任何分隔符立即工作
- ollama 调用 404：先怀疑模型名（看本地 tags 列表，gemma-4-e4b-it-mxfp8 不存在）→ 改 qwen3.5:9b → 仍 404 → 加诊断 log 发现实际 model 字段是 gemma → 是 config 里写错没换。换 qwen3.5:9b 后复活
- Clash 代理把 127.0.0.1 流量也劫走（NO_PROXY 在某些 requests 版本不可靠）→ Session(trust_env=False) 彻底解决
- FunASR 2pass 自动加的中文标点（如"。关闭餐桌灯"前导句号）让严格匹配 prompt 误伤 → 去标点预处理 + prompt 加"忽略标点"提示双保险

#### 🟡 已知遗留（顺手清单）

- **engine.py `self._lock` 死锁**：第一次实测时一波连续语音让 lock 卡死 4 分钟（kill+supervisor 重拉才恢复）。原意图防 ollama 并发请求，但 ollama serve 自带请求队列，外部锁多余。下次顺手移除 `with self._lock:`
- **配置不持久化**（沿自回合 27）：动态加的视频源、动态加的设备 also_in 都不写回 yaml；重启 main.py 时 `_add_source` 等丢失（但 catalog.json 是文件，always 加载）
- **classify_intent 关键词列表**：写死在 engine.py（"打开/关闭/启动/..."），未来可从 catalog 自动 derive

---

### 2026-05-07 (回合 27) — P1 整体 UI 用户可调（4 子项全部用户验收）

#### 用户校正方向（关键）

回合 26 收尾后用户重新明确：
- **护城河 = 理解 → 执行**（讯飞没有的），不为对标讯飞而东施效颦
- 整体 UI 用户可调是底层支持，需先做
- 转写两类应用：①语意理解后执行动作（当前主线）②纯语音转写（场景 B 可独立）
- 参考 World Monitor v2.8.0 截图：**借鉴**模块拖动/min size/网格/列表切换 等 UX 概念；**不照搬**「管理频道」弹窗（调性不符 — 我们是工业 AV 中控不是内容聚合）
- 上一版 GitHub `flyfish17/av_unified_mvp` 有可用代码（视频添加 / LAN 扫描），回填进来

#### ✅ P1.1 GridStack 拖动 + 布局 persist

引入 gridstack 11.x（离线 82KB JS + 4KB CSS 到 `web/static/lib/`）。5 个总览模块卡（Node-RED / 视频墙 / 转写 / 意图 / 在线视频源）适配 grid-stack-item，gs-min-w/h 防"碎"（视频墙/Node-RED min 6×4，文字卡 min 4×3）。`change/added/removed/resizestop/dragstop` 事件 → `localStorage["av_overview_layout"]`。`grid.load(saved, false)` 启动 restore（false=不删默认 widget 仅覆盖位置）。

`web/templates/dashboard.html`：删旧 hardcode min/max-height，gridstack 用 cellHeight×gs-h 控制；加 `.grid-stack-item-content` override 让 .module-card 占满。

#### ✅ P1.2 模块可见性 + 重置布局

仿 World Monitor 顶部"图层 checkbox"思路。两条入口：
- **module-header 注入"× 隐藏"按钮**（JS 自动给所有 .module-card .module-actions 加，避免改 5 处 HTML）
- **总览页 view-head 加"⚙ 布局"popup**：列出所有模块 checkbox + "全部显示" + "⟲ 重置布局"按钮（confirm + 清两个 localStorage key + reload）

实现：`grid.removeWidget(el, false)` 隐藏（保留 DOM 不删），`grid.makeWidget(el)` 显示；`hiddenCardPos[id]` 内存记位置在重显时用 `grid.update(el, pos)` 还原。

#### ✅ P1.3 视频源 add / edit / remove（仿上一版 + 新协议）

**后端**（`modules/video_processor/main.py`）：3 个新 MQTT 订阅：
- `av/video/source/add` → `_add_source(src)`：append + reload + 重新公告
- `av/video/source/update` → `_update_source(src)`：按 name 找，原地改 url + reload + 重新公告
- `av/video/source/remove` → `_remove_source(name)`：从 sources/endpoints 移除 + reload + 公告

discovery endpoints[] 加 `src_url` 字段（原始 RTSP/USB url），让前端编辑时能反推字段。

**前端**：第 6 个总览模块卡"添加视频源"，三类型表单（IPC 带认证 / 分布式 / 本机 USB）+ URL 自动拼接预览：
- IPC：`rtsp://user:pwd@ip:port/Streaming/Channels/N`
- 分布式：`rtsp://ip:port/path`
- 本机：USB device 号

视频墙画格 header 加 ✎ 编辑 + ✕ 删除按钮：
- ✎ → `parseSourceUrl(ep.src_url)` 反推类型 + 字段填表 + 滚到表单 + name 输入框灰禁用（编辑期间不允许改 name 防破坏 endpoints 索引；要改名就删除后重添）+ 按钮文案变"保存修改（XXX）"+ 显示"取消"按钮
- ✕ → confirm + POST `av/video/source/remove`

提交时按 `formMode` 切 topic（`add` / `update`），edit 完成后 clearForm + 切回 add。

**已知 trade-off**：`_add_source` 等只 append 到内存 `self._sources`，**不写回 `config/system_config.yaml`**。重启 main.py 后新加/修改的源会丢，原 yaml 4 路恢复。如需"重启不丢"，加几行 yaml.dump 即可（下次需求确认后再做）。

#### ✅ P1.4 LAN 扫描 UI 增强

**后端不动**：现有 `modules/network_scanner` + `av/system/lan_scan/{cmd,progress,result}` 协议已完备。

**前端**：第 7 个总览模块卡"LAN 扫描"：
- 子网输入（留空自动用本机 /24）+ ▶ 扫描按钮
- 实时进度条（订阅 lan_scan channel 拿 progress 事件）
- 结果表格：IP / 开放端口（554 高亮蓝绿色"RTSP"标签）/ 操作按钮
- **核心 UX**：扫到开 554 的 IP → 行末显示"→ IPC" "→ 分布式"按钮，点击调 `window.__videoSourceForm.fillFromLanScan(ip, type)` 自动切到"添加视频源"卡 + 类型对应 + IP/端口/默认名称预填 + 焦点跳到下一待填字段（IPC 通道号 / 分布式路径）

跨卡通信用 `window.__videoSourceForm` 暴露 + dispatcher（不破坏 dashboard.js IIFE 封装）。

#### 📋 文件改动清单（回合 27）

```
web/static/lib/gridstack-all.min.js  ← 新增（82KB）
web/static/lib/gridstack.min.css     ← 新增（4KB）
web/templates/dashboard.html         ← grid-stack 重构 + 7 模块 + 表单 + popup + 大量 CSS
web/static/dashboard.js              ← +400 行（GridStack init + 可见性 + 表单 + LAN 扫描 dispatcher）
modules/video_processor/main.py      ← +60 行（add/update/remove 三协议 handler）
DEVELOPMENT_PLAN.md                  ← 本节
```

#### 🟢 用户验收

P1.1 / P1.2 / P1.3 add / P1.3 edit-remove / P1.4 各自验收"全部正常 / OK"。

#### 🟡 已知 trade-off / 遗留

- 配置不持久化（重启 main.py 丢失新加的源）— 用户未确认是否要写回 yaml
- 视频墙画格 4 路上限（World Monitor 那种 tab 分类 + 网格/列表切换的 P1.5 暂不做，等真实场景超 4 路再上）
- LAN 扫描端口固定（22/80/443/554/1883/8080），未来可加端口选择器

---

### 2026-05-07 (回合 26) — Mac Studio 装 funasr-2pass + 麦克风自检 patch + 诊断方法论复盘

#### 🔥 用户业务背景（首次明确写下）

竞品对标：**讯飞实时转写本地化**（客户截图：边说边出 partial 标点 + 整句修整）。讯飞本地部署报价 50 万；订阅版几十元但要联网、有调用次数。**国产化空间**：RK3588 / 华为昇腾 / 飞腾等国产硬件本地部署 = 痛点也是机会。FunASR（阿里达摩院开源 + ModelScope 国产托管 + Apache 2.0）是这条路最关键的国产链路。**av_unified_mvp 作为视听理解类项目的技术底座，必须在转写端达到讯飞同款观感**。

#### 🐞 用户报告的 bug

启动后转写卡在"等待麦克风输入…"，状态栏显示麦克风刚有指示又消失，前端无气泡。

#### 我的诊断错误（复盘 — 重要）

**第一次反应**：直接猜「macOS 麦克风权限」，让用户去系统设置授权。

**用户驳回**：「我已经有授权，从昨天到上版之前一直好用」+ 提示「上版之前都好，你说没动语音这部分，那解耦架构怎么会有连带影响」。

**第二次反应**：又怀疑回合 25 SSE 改动反向影响 audio_processor。

**用户再次点醒**：解耦架构的承诺是「模块互不影响」。**UI/SSE 改动反向断开 audio→MQTT 发布在物理上不可能**。如果 MQTT 拿 0 事件 = 100% audio 内部问题。

**正确诊断路径**（应该一开始就走）：
1. `mosquitto_sub -t 'av/audio/#'` → 8s 抽样 0 条 → 证实 audio 没发出 partial/final
2. `docker ps -a` → 发现 `funasr-2pass` 容器**不存在**，跑的是 `funasr-server`（错误名）
3. `docker images` → 镜像是 `funasr-runtime-sdk-cpu-0.4.6`（**offline-only**），不是 `online-cpu-0.1.12`（**2pass 流式**）

**真正根因**：用户机器上 funasr-2pass 容器只有 MacBook Pro 上有；Mac Studio 上跑的是某次测试遗留的 offline-only 旧镜像，名字也叫 funasr-server。ws 握手成功（同 :10095），但协议不匹配，audio 卡在 `await ws.recv()` 永远拿不到 partial/final。

**教训**：
- 客观证据 > 猜测。MQTT 0 事件已经把范围锁死到 audio 进程内部，不需要再绕到 web/SSE 层
- 解耦架构是个**反向证据**：UI 改动不影响 audio 链路 = 一旦 audio 输出 0，问题必然在 audio 内部或上游（mic/funasr）

#### ✅ 修法 A：从 MBP 流式同步 funasr 2pass 到 Mac Studio

| 步 | 操作 | 用时 |
|---|---|---|
| 1 | ssh-keygen + ssh-copy-id 用 expect 自动免密（首次） | 10s |
| 2 | `kill main.py` + `docker rm -f funasr-server` 清理旧环境 | 5s |
| 3 | 流式拷镜像：`ssh yzj@MBP 'docker save'` ｜ `docker load` （3.15GB） | 326s |
| 4 | rsync 模型卷：`rsync -av -P yzj@MBP:~/funasr-runtime-resources/models/ ~/funasr-runtime-resources/models/` （1.6GB） | 199s（与步 3 部分并行） |
| 5 | docker run 创建 funasr-2pass 容器（用 start.command 那段完整命令，挂载本地 models 卷） | 几秒 |
| 6 | 等容器内 `funasr-wss-serv` ready（VAD + paraformer online/offline + punc + ITN 全部加载） | ~120s |
| 7 | 重启 main.py，audio_processor 自动连新 :10095 | 即时 |

**总耗时 ~9 分钟**，比 `docker pull` 阿里云镜像 + 首次模型下载快 3-5 倍。

**注意点**：
- macOS 自带 rsync 是 2.6.9，不认 `--info=progress2`，要用 `-P`
- ssh 非交互 shell 不加载 PATH，要 `ssh ... 'zsh -lc "docker ..."'` 才能找到 docker

#### ✅ 修法 B：audio_processor 加麦克风 PCM 帧自检（顺手做的诊断 patch）

`modules/audio_processor/processor.py`：
- 加 `self._pcm_frames_received` 计数器，在 `_on_audio_pcm` callback 里 `++`；第 1 帧到达时 logger.info 一次（"麦克风正常工作"）
- 启动 5s 后跑 `_mic_self_check`：若收到的帧数 < 期望 1/4（应 ~83 帧 / 5s @ 60ms/帧），logger.error + 推一条 mic_warning TranscriptEvent 到前端

效果：未来任何用户首次跑（macOS 权限未配 / 设备被占 / sd 设备失效），main.py.log 里会立即出 `[mic] 启动 5s 仅收到 0 帧 — macOS 麦克风没真正交付 PCM`，前端转写卡也能显示警告，不再静默。

#### ✅ 验证（用户验收）

```
11:47:19 FunASR 已连接 ws://127.0.0.1:10095
11:47:19 [mic] 第 1 帧 PCM 已收到 (960 samples)
11:47:21 [final] 那个合作的
11:47:22 [final] 我早知道
...
11:47:24 [mic] 自检通过：5s 收到 83 帧
```
转写实时出，标点 + ITN 工作。**用户原话「当前任务完美完成」**。

#### 📋 文件改动清单（回合 26）

```
modules/audio_processor/processor.py   ← _pcm_frames_received + _mic_self_check（永久诊断）
~/funasr-runtime-resources/models/     ← 新增（1.7GB，paraformer + punc + ITN）
docker images: funasr-runtime-sdk-online-cpu-0.1.12  ← 从 MBP 流式导入（3.15GB）
docker container: funasr-2pass         ← 新建，挂载本地 models 卷，restart unless-stopped
DEVELOPMENT_PLAN.md                    ← 本节
```

#### 🟡 顺手发现的小坑（写下来下次别再踩）

- **kill main.py 后立即重启会撞 :5050 TIME_WAIT**。我两次踩坑：第一次 `sleep 3` 不够，新 Flask 启动时 socket 还没释放，daemon 线程内 swallow 了 `Address already in use` 但 supervisor 没察觉，main.py 进程在跑但 web 没 listen。第二次改成 `until ! lsof -i :5050 -sTCP:LISTEN; do sleep 1; done` + `sleep 3` 兜底。**未来 fix**：`web/server.py` 启动失败要把异常传播给 supervisor（不要让 daemon thread 静默吞）；或者 Flask 启动加 `SO_REUSEADDR/SO_REUSEPORT`
- **start.command 的 `trap cleanup EXIT`** 把 Node-RED 跟 main.py 生命周期绑死，重启 main.py 时 Node-RED 也被带走（回合 25 已记录）

---

### 2026-05-07 (回合 25) — SSE 多路合并到单 /events/__all__（修视频墙启用无响应根因）+ 左导航视觉强化

#### 🔥 用户反馈与诊断

启动后用户验收发现 3 个 UI 问题，第一个是"刷新与强制刷新都不会把视频墙中的视频启用，直接按启用更没反应，但另开窗口就会显示"。用户原话："这是所有UI的基础，模型订阅制也应该能体现轻量、加载迅速的优点。"

直接原因（从 main.py log 反推）：
- 09:35:46 用户刚启动后点了 3 路 enable，全部 200 OK 立即处理；
- **09:36:20 截图时刻点了"监控"启用 → 49s 后（09:37:09）后端才收到，且**连续收到 3 条同样 POST**——浏览器把 POST 排队 + 用户多次点击导致重复发；
- 后端链路完全 OK，卡的是浏览器到 :5050 的 HTTP 通道。

根因：dashboard.js 给 discovery + 每模块每个 stream channel 各开一条独立 `EventSource`，**总数 = 1 (discovery) + 5 (transcript/video/intent/control/network) = 6 条 SSE 长连接到同 origin :5050**——**正好打满 HTTP/1.1 浏览器对单 origin 6 connection 上限**。后果：
1. POST `/camera/<n>/enable` 没空闲 connection，浏览器队列里挂着；
2. 已有 SSE 长连接进入 stale 状态（事件可能不再 flush 到客户端 buffer）；
3. "另开窗口就显示"：新窗口建 SSE 时 Chrome 优先调度新连接，加上 retain 快照立即重放。

#### ✅ 修法 A：SSE 合并到聚合频道 `/events/__all__`

后端（`web/server.py`）：
- `push()`：除原 channel queue 外，把 `{"__channel": ch, ...ev}` 包装副本推到 `__all__` queue（hello 跳过）；
- `_make_sse("__all__")`：重放快照时遍历所有 channel 的 `_latest_state`，每条都包 `__channel` 字段；
- 旧 `/events/<channel>` 端点保留（向后兼容、调试方便）。

前端（`web/static/dashboard.js`）：
- 加 `channelHandlers: Map<channel, Set<{handler, module}>>` + `subscribeChannel(ch, handler, module)`；
- 单 `EventSource("/events/__all__")`，`onmessage` 解析 `__channel` 字段后剥离 → 按表 dispatch 到 handler；ticker forward 也合并进去；
- 替换原 `new EventSource("/events/discovery")`（line 141）和 channels.forEach 里的 `new EventSource(/events/<ch>)`（line 225）；
- 移除 per-module SSE onopen/onerror 状态切换：单 SSE 模式下连接状态是全局的，由顶部 `header-status` pill 反映；模块视图状态完全靠 discovery 心跳 + offline LWT 驱动（已有逻辑）。

效果：`:5050` 上只占 1 个长连接，剩 5 个空闲。点"启用"立即发出 POST，UI 即时响应；新增多少模块都不再受 6-connection 限制。

curl smoke test 验证：
```
$ curl -N http://127.0.0.1:5050/events/__all__
data: {"type": "hello", "channel": "__all__"}
data: {"__channel": "discovery", "module": "supervisor", ...}
data: {"__channel": "discovery", "module": "llm_engine", ...}
data: {"__channel": "discovery", "module": "audio_processor", ...}
data: {"__channel": "discovery", "module": "video_processor", ...}
```
hello 后立即重放所有 4 个模块的 discovery 快照，每条带 `__channel` 字段 ✅

#### ✅ 修法 B：左导航视觉去歧义

用户反馈："总览前一直有选定方块，选择 Node-RED 时也不变，背景正常显示当前选择"。

诊断：`addNavItem({title: "总览", icon: "▣"})` vs `{title: "Node-RED", icon: "▢"}`——`▣ vs ▢` 视觉太像 checkbox 的"已选/未选"，把选中态信号绑死在图标上，跟真正的 active CSS（background + 左 accent border）抢戏。

修法：
- `web/static/dashboard.js`：把"总览"图标 `▣ → ▢`，与 Node-RED 一致；
- `web/templates/dashboard.html`：`.nav-item.active` 背景从 `var(--panel-2)` 改为 `linear-gradient(90deg, rgba(88,166,255,0.18), rgba(88,166,255,0.04))`（accent 蓝色半透明），加 `font-weight:600`；active 时图标透明度 1.0 + 染 accent 色。选中态完全靠背景对比度表达。

#### 🟡 暂缓（用户认可放着）

- **HLS 加载慢**：用户用梯子但 Apple BipBop m3u8 仍慢。和梯子无关，是源端 + hls.js parse master/variant 双层 playlist 开销。等问题 1 修好后用国内公共源（如 CGTN）替换。

#### 📋 文件改动清单（回合 25）

```
web/server.py                          ← push() 多写 __all__；_make_sse 处理 __all__ 重放全 channel
web/static/dashboard.js                ← channelHandlers + subscribeChannel + 单 EventSource；总览 icon ▣→▢
web/templates/dashboard.html           ← .nav-item.active 背景换 accent 渐变 + font-weight + ico 染色
DEVELOPMENT_PLAN.md                    ← 本节 + §0 进度 + §11 切入点
```

#### 🟢 用户验收（回合 25 收尾）

用户实测全通（除一项次要外）：
- ✅ B. 启用按钮即时响应（核心修复，POST 不再排队）
- ✅ C. 左导航选中态：accent 渐变背景 + 加粗 + ico 染色，切换清晰
- ✅ D. 视频墙启用后即时出图，不需要再开新窗口
- 🟡 Node-RED iframe：第一次刷新时 Node-RED 没起来——root cause：`start.command` 的 `trap cleanup EXIT` 在 main.py 退出时会顺带 kill `NR_PID`，重启 main.py 间接把 Node-RED 也带走了。重新 `nohup node-red ...` 后恢复 OK。
- 🟡 E. HLS Apple BipBop 仍慢（与梯子无关，源端开销）— 暂缓

#### 📝 遗留小注（下次顺手优化）

`start.command` 的 `trap cleanup EXIT` 把 Node-RED 跟 main.py 生命周期绑死。优点是用户 ⌘+C 时干净退出；缺点是只重启 Python supervisor 时 Node-RED 也被带走（冷启代价 ~30-50s）。下次接手可考虑：
- 方案 A：trap 里加条件 — 只在收到 INT/TERM（用户主动）时清理 NR_PID，EXIT 不动它
- 方案 B：把 Node-RED 启动从 start.command 拆出来，独立脚本 `start_node_red.command` + 用 launchd / pm2 守护
- 方案 C：保持现状（生命周期绑死的简单性 > 重启灵活性），下次只是知道这事

---

### 2026-05-07 (回合 24) — supervisor MQTT client_id 唯一化（修 enable 偶发丢失）

承接回合 22/23 顺手发现的遗留问题（POST `/camera/<n>/<a>` 偶发 MQTT 断开重连，enable 命令偶尔丢）。

#### 多 agent 效率快评（用户问）

- 本回合任务：单文件 + 单段改动 + 文档同步，10 分钟内完成。
- worktree/多窗口协同启动成本（建分支 + 双窗口上下文同步 + 合并）远大于本任务收益。
- 当前主机走 iCloud 路径（含中文+空格），worktree metadata 锁冲突仍是已知风险（详见回合 23 调研）。
- **决策：本回合单 agent 直接做，多窗口协同试点延后到 Mac Studio（§11 已写预案）。**

#### ✅ 修复 supervisor MQTT client_id

诊断：
- `core/base_module.py:64` 早已给子模块加 `_{name}_{uuid}` 后缀（回合 17 改）；
- 但 `core/mqtt_bridge.py:20` 默认值是 `av_box_001`，且 `config/system_config.yaml:21` cfg 也写了 `client_id: av_box_001`，supervisor 用的就是这个 base 名；
- supervisor 子模块可能在某时刻短暂前缀冲撞（mosquitto v2 的同 client_id 互踢策略 + paho 自动重连），表现为"按钮要点两次"。

修法（`core/mqtt_bridge.py`）：参考 base_module 的"无条件追加唯一后缀"模式，不走 `or` 兜底（cfg 里有非空值时 or 短路无效）：

```python
base_cid = cfg.get("client_id", "av_box_001")
self.client_id = f"{base_cid}_supervisor_{uuid.uuid4().hex[:6]}"
```

效果：
- supervisor → `av_box_001_supervisor_<6hex>`
- 子模块（base_module）→ `av_box_001_<name>_<6hex>`
- 互不撞名，broker 不再互踢。

副作用面：
- `ui/web_interface.py / ui/dashboard.py / ui/dashboard_refactored.py`（Streamlit legacy，非主线启动路径）也走 MQTTBridge → 名字现在带 `_supervisor_` 后缀，仅是命名口味问题，不冲突。
- `modules/mqtt_router/router.py` 是另一独立 MQTT client，自管 `av_router` client_id，不走 MQTTBridge，不受影响。

#### 🟡 验证（待用户启动后测）

```bash
# 启动 mosquitto + main.py 后，UI 反复点 enable/disable
grep "MQTT 断开" main.py.log    # 期望 0 条
mosquitto_sub -h 127.0.0.1 -t '$SYS/broker/log/N' -v   # 不应出现 client_id 重复登录
```

#### ✅ 顺手清两个 R 计划之外的遗留

##### 1. start.command Node-RED 启动 timeout 8s → 120s

回合 19 提的待办，一直没修。iCloud 路径冷启动 palette + flows 实测 ~50s，原 8s（16×0.5s）几乎必超时报 warn。改 240×0.5s=120s，启动早 ready 仍 break，不浪费时间。warn 文案也改成"进程可能仍在加载"避免误导。

##### 2. YOLO 加载容错（modules/video_processor/processor.py:87）

原代码 `self._model = YOLO(self.model_path)` 无 try/except，模型文件缺失/下载失败直接 raise，整个 video_processor 进程挂掉，连不依赖 YOLO 的 raw MJPEG 流也没了。

改为 try/except：失败时 `self._model = None` + error 日志；推理线程的 `if self._model is None: continue`（行 207）已就位，detection 事件停发但 raw 流照常。符合 §11 "可选方向"明确改进项："模型 None bug（不影响 MJPEG 流，但检测事件出不来）"。

#### 📋 文件改动清单（回合 24）

```
core/mqtt_bridge.py                    ← client_id = base_cid + _supervisor_ + 6hex 后缀
start.command                          ← Node-RED timeout 8s → 120s
modules/video_processor/processor.py   ← YOLO 加载 try/except 容错
DEVELOPMENT_PLAN.md                    ← 本节 + §0 当前进度 + §11 切入点更新
```

---

### 2026-05-06 (回合 23) — 多窗口 Claude 协同工具调研（未动手）

用户问当前 GitHub 上有效的多窗口 Claude Code 协同协调工具，本回合只做调研 + 计划，**没有执行任何改动**。

#### 调研结论（按推荐度）

1. **官方 Agent Teams + git worktree** — 零依赖，能立即跑。开关 `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1`（v2.1.32+）。worktree 让多个 Claude 实例各自独立工作目录、共享 `.git`。社区共识 2026 年单人 4–8 个并行 worktree 是稳态。
2. **smtg-ai/claude-squad** — 终端党首选，自动 tmux + worktree 管理多 agent 会话。
3. **kbwo/ccmanager** — 多家 agent（Claude/Gemini/Codex/Cursor 等）通用会话管理器。
4. **constellagent**（macOS 原生）/ **clideck**（Web）— GUI 党可选。
5. 重型编排（ruflo / maestro-orchestrate）暂不需要 —— 当前是人工分发任务，不是无人值守流水线。

#### 本仓库特别适配点

项目本就是 MQTT 解耦的多子模块底座，并行边界天然清晰（`modules/audio_processor`、`modules/video_processor`、`modules/llm_engine`、`modules/network_*`、`modules/system_info`、`web/`、`node-red/`），多窗口分工冲突面小。

#### 关键约束（明天动手前必看）

- **iCloud 路径坑**：仓库在 `~/Library/Mobile Documents/.../av_unified_mvp`，路径含中文+空格。worktree 的工作目录**必须放 iCloud 外**（如 `~/dev/`），否则双重同步 + 文件锁概率冲突。`.git/worktrees/<name>/gitdir` 仍在 iCloud 里，可接受。
- **同分支冲突**：同一个分支不能在两个 worktree 同时 checkout，新 worktree 必须切新分支（`-b`）。
- **git index 锁**：两个窗口同时跑 git 命令偶发 `index.lock` 冲突；约定每个窗口只在自己的 worktree 内 git 操作。
- **共享文件冲突**：worktree 隔离的是工作目录，不是逻辑边界。两个窗口改同一个文件时合并阶段才暴露，所以分工按 `modules/*` 子目录划。

#### 用户决定

不在当前 iCloud 主机上做实验，明天到公司 Mac Studio 上接手时启用。具体步骤见 §11 「明日另起：多窗口协同试点（Mac Studio）」。

#### 📋 文件改动清单（回合 23）

```
DEVELOPMENT_PLAN.md   ← 本节 + §11 明日另起小节
```

---

### 2026-05-06 (回合 23) — C+D 完成 / 视频墙改 multipart / E1+E2 合并完成

#### ✅ C+D. 总览页 vertical stack 重构

- `web/templates/dashboard.html`：删 `.overview-wrap` 三段式 grid，新建 `.modules-stack`（flex column）+ `.module-card`（统一 header/body）
- 每个 `.module-card` 标准结构：`drag-handle ⋮⋮ + module-title(主+sub) + module-badge + module-actions(右对齐)`，`data-module-id` 为后续 GridStack 拖动持久化做准备
- 5 个总览模块：Node-RED 中控 / 视频墙 / 转写 / 在线视频源（新增）/ 意图
- 模块视图（discovery 动态生成的 panel）保留旧样式，本次未改动

#### ✅ 视频墙从 snapshot polling 改 multipart 流

回合 22 修了视频 503 后，本回合用户反馈"出图就黑"+"放大缩小才更新一次"。诊断：

1. snapshot polling watchdog 触发后把 `img.src = transparent_gif`，**transparent gif 也会触发 onload** → 又排一次 setTimeout(tick) → 与 watchdog 自己排的 tick 形成**多 tick 并发** → onload/onerror 互相覆盖
2. 加 `reqId` 序号守卫 + watchdog 不再动 src 后，"出一图就静帧"——浏览器对相同 base URL 的连续请求疑似有节流，第二次 onload 不触发
3. **决定换 multipart MJPEG 流**：`img.src = stream_url`（`/video_feed/<name>?mode=raw`）一次设置，浏览器原生持续接收每帧，每个 boundary 触发一次 onload → 流畅播放
4. 8 秒 watchdog 检测断流，自动重连（macOS USB 摄像头偶发卡顿时恢复）
5. 验证：用户实测流畅播放 ✅

回合 18 当初选 snapshot 是因 multipart 在 Chrome 偶不稳定；现在 video_processor 加了 `Connection: close` + 状态机断流（回合 18 内）+ latin-1 编码修复（回合 22）+ 客户端 watchdog 重连，multipart 是更稳的方案。

#### ✅ E1+E2 合并：在线视频源 module-card

- 下载 `hls.min.js` v1.5（415 KB）到 `web/static/lib/`，离线可用
- 总览页新增 `data-module-id="overview-online-stream"` 模块卡：`<video controls muted playsinline>` + 源下拉 + 停止按钮
- 加载逻辑（dashboard.html 内 inline script）：Safari 走原生 HLS；Chrome 走 hls.js；MANIFEST_PARSED 自动播放；fatal 错误显示 badge
- 测试源（仅 1 个，最稳）：**Apple BipBop**（`devstreaming-cdn.apple.com/.../master.m3u8`）— HLS 官方测试流，无 token 无反爬
- 后续可加：CGTN / DW News / Euronews 等公开 m3u8（select 里加 option 即可）
- ~~F. 抖音/视频号~~ 仍标暂缓

#### 📋 文件改动清单（回合 23）

```
web/templates/dashboard.html       ← vertical stack + 5 模块卡 + hls.js 引入 + 在线源逻辑
web/static/dashboard.js            ← 视频墙改 multipart 流（startSnapshotPoll 改写）
web/static/lib/hls.min.js          ← 新增（离线 415 KB）
DEVELOPMENT_PLAN.md                ← 本节
```

#### 🟢 今晚收尾后状态

- A 语音闪动防抖 ✅
- B 视频黑框 latin-1 编码 ✅
- C+D 界面 vertical stack + 模块标题栏 ✅
- 视频墙 multipart 流 ✅
- E1+E2 在线视频源（HLS） ✅
- F 抖音/视频号 — 暂缓
- G GridStack 实际拖动 — 远期（结构 ready）

#### 🟡 已知遗留（下次接手）

- main.py 的 MQTTBridge 用默认 `client_id=av_box_001`，没像 BaseModule 那样加唯一后缀 → POST `/camera/<n>/<a>` 时偶发 MQTT 短暂断开重连，enable 命令偶尔丢（用户要点两次）。修：`core/mqtt_bridge.py:20` 改成 `f"supervisor_{uuid.uuid4().hex[:6]}"`

---

### 2026-05-06 (回合 22) — B 完成（视频 503 真根因：URL 中文 latin-1 错码）

#### ✅ B. 视频黑框修复（`modules/video_processor/main.py`）

**真根因**（追了 4 步才定位）：
1. 第一步：`curl -s "http://127.0.0.1:5051/snapshot/本机摄像头?mode=raw"` 返回 HTTP 503
2. 第二步：检查 status 状态机 → 推测 cap.read 失败导致 status="error:..." 不在白名单 → **改 503 触发条件为 stopped/None**（保留，对 macOS 偶发断流仍有用）
3. 第三步：改完仍 503，检查发现 disocvery 公告 enabled=true、processor.py 日志 "摄像头已连接"→ status 应当是 "ok"
4. 第四步：临时加 stderr debug → `[DEBUG] name='æ\x9c¬...' status=None all_keys=['本机摄像头']`
5. **定位**：Python `http.server` 默认用 **latin-1 解码请求行**，self.path 里 UTF-8 字节序列被当 latin-1 字符直接保留（每字节一字符），urlparse.unquote 不动；dict 查不到中文 key → 503
6. **修法**：在 `_serve_snapshot` 和 `_stream_mjpeg` 里做 `name = name.encode("latin-1").decode("utf-8")` 修正
7. 验证：5 次 snapshot 连续 200 OK，每张 ~114KB，1920×1080 JPEG ✅

#### 🟡 顺手发现

- POST `/camera/<name>/<action>` 触发 main.py 的 MQTT 短暂断开重连（`core.mqtt_bridge: MQTT 断开`），enable 命令偶尔丢失
- 怀疑：main.py 的 `MQTTBridge` 默认 client_id="av_box_001"，**没用唯一后缀**（回合 17 只修了 `core/base_module.py` 的子模块 client_id）
- 影响：用户点 UI 启停按钮时第一次可能不响应，需要再点一次
- **下次接手修**：`core/mqtt_bridge.py:20` 改成 `f"supervisor_{uuid.uuid4().hex[:6]}"` 或读 config 里独立 supervisor key

#### 📋 文件改动清单（回合 22）

```
modules/video_processor/main.py        ← latin-1→utf-8 编码修复 + 503 触发条件收窄
DEVELOPMENT_PLAN.md                    ← 本节
```

---

### 2026-05-06 (回合 21) — A 完成；C/D 进入主线；F 暂缓

回合 20 后用户验收新发现 + 新主线方向：

#### ✅ 已完成

- **A. 语音闪动防抖**（`node-red/flows.json` 大脑函数 `5f260...`）
  - 原 `setTimeout(reset, 3000)` 每条 audio msg 都启动新 timer，多 timer 排队 → audio.detected 在 true/false 间快速切换 → SVG"只一闪就停"
  - 改为 **clearTimeout 防抖 + 2s 保持**：`context.set('audio_reset_timer', ...)`，每次新 msg `clearTimeout(old)` + 启动新 timer；连续语音保持点亮，停顿 >2s 才熄
  - 工具脚本：`/tmp/edit_brain_fn.py`

#### 📋 当前主线（用户钦定 = §11 优先级）

按 **A → C+D → E1 → E2 → B** 顺序（B 是 bug 但优先级在结构定型之后）：

| 项 | 工期 | 状态 | 内容 |
|---|---|---|---|
| **A** | 10min | ✅ | 语音闪动防抖（本回合） |
| **C+D** | 1.5h | 🟡 主线 | 界面改 vertical stack（上下滑动）+ 每模块统一 header（标题/状态 badge/操作区/drag-handle 占位）+ data-module-id；GridStack 实际功能不做，结构 ready 即可 |
| **E1** | 1h | 🟡 待办 | 引入 hls.js（CDN 或 npm），新增 `web/static/renderers/hls_stream.js`；测 ≥2 公共源（央视 CCTV-13 国际频道 m3u8 / 海外 EarthCam 公开 webcam） |
| **E2** | 1h | 🟡 待办 | "分布式"卡片保留作内部 RTSP（家中跳过）；新增"在线源"卡片，下拉切换 HLS 源（订阅模型先 frontend hardcode，足够测试） |
| **B** | 15min | 🟡 bug | 视频黑框：raw 模式 `?mode=raw` 返回 HTTP 503（30 字节文本），但 `modules/video_processor/processor.py` 日志显示摄像头已启用。诊断：raw mode 的 `_get_latest_frame` 取的是 raw 缓存 dict，可能 capture 线程偶尔丢帧、或 mjpeg.js polling 200ms 命中率低。具体看 `modules/video_processor/main.py:64,95`（503 路径）+ `processor.py` 的 raw_frames 写入时序 |
| **G** | 半天 | ⚪ 远期 | GridStack/Muuri 实际拖动 + localStorage 持久化；C+D 结构 ready 后再说 |

#### 🚫 暂缓（标注）

- **F. 抖音 / 视频号 / 海上平台直播 接入**：反爬严密，需第三方 stream-extractor（yt-dlp / streamlink + token 服务）+ 持续维护代理。**暂不做**。等 E1/E2 用央视等公开 HLS 跑通后，仅当业务真有需要再考虑独立子项。

#### 🟢 现状（用户验收）

- 2.0 大屏 hero iframe 显示正常（vue/echarts/mermaid 资源已加载，SVG 流转图在动）
- 视觉/听觉/AI大脑/FSP矩阵 4 区联动正确，颜色/连接线流动符合设计
- 语音持续输入时 audio 区维持点亮（A 修复后效果明天验证更稳）

---

### 2026-05-06 (回合 20) — flows.json 大瘦身 + 接入真实 MQTT + iframe 黑屏修复

#### ✅ 已完成

1. **flows.json 从 120 节点 → 48 节点**（备份 `node-red/flows_creator_full.json.bak`）
   - 保留：`[2.0] CREATOR InfoComm 展台大屏`（唯一 2.0 page）+ `[1.x] 指挥中心控制端`
   - 删除：`[2.0] 二号采油站监控中心` + `[1.x] 智慧工地 AI 监控` + 三个调试 tab（AI 工业监控 Demo / AI 四画面监控中心 / MQTT）
   - 删除掉所有 ffmpeg `/tmp/rtsp_*.jpg` 抓帧节点 + 4 路 3588 推理 HTTP 节点 + 二号采油站 widget
   - 工具脚本：`/tmp/edit_flows.py`（保留以备追溯，包含完整删除规则）
   - Node-RED 启动时间从 50+s → 11s（节点少了文件 IO 也少）

2. **大屏 SVG 接入真实 MQTT**
   - 改 `mqtt-in 08c2a415b6fccbec`：topic `audio_intent` → `av/audio/command`，broker 统一到 `2b41081ef4cf12c5`
   - 改 vision 解析 function `9d80c752862d56a0`：从读 `payload.predictions`（CodeProject.AI 格式）改为读 `payload.detections`（§4 协议）
   - 新增 `mqtt-in av_video_detect_in_001` 订阅 `av/video/detect` → 喂 vision 解析
   - 大脑 function `5f260125557286a5` 不动（原本设计就完美：vision 来 → fsp_active=true，audio 来 → 3s 后自动 reset）
   - 验证：`mosquitto_pub` 注入 `av/video/detect`（2 person）和 `av/audio/command` 后，SVG 视觉/听觉/矩阵区联动正确（见 `dashboard_2.0_twin` widget）

3. **iframe 黑屏根因 + 修复**（最重要的发现）
   - DevTools Console 报错 `Failed to load module script: Expected JavaScript or Wasm but got text/html`
   - 涉及 `index-XXX.js` / `vue-vendor-XXX.js` / `mermaid-XXX.js` / `echarts-XXX.js`
   - **根因**：dashboard 2.0 的 SPA HTML 没声明 `<base href>`，资源用相对路径 `./assets/index-XXX.js`
     - iframe URL = `/dashboard/page/<slug>`（无尾斜杠）→ 浏览器把目录解析为 `/dashboard/page/`
     - 资源 URL = `/dashboard/page/assets/index-XXX.js` → Node-RED 路由不到 → SPA fallback 返回 HTML index → MIME=text/html → 浏览器拒绝当 module 解析
     - 单独打开 `http://localhost:1880/dashboard/`（带尾斜杠）正常，因为目录解析为 `/dashboard/`，资源 URL = `/dashboard/assets/...` ✅
   - **修法**：`web/static/dashboard.js` 的 `pageUrlPath()` 对 `ui-page` 类型直接返回 `/dashboard/`（不带 page/slug）；让 SPA 自带导航处理多页（当前只有 1 个 2.0 page 无所谓）
   - 这同时**推翻了回合 19 的"X-Frame 兜底"假设**——X-Frame 早就修了，真正的卡点是 SPA base href

#### 📋 文件改动清单（回合 20）

```
node-red/flows.json                   ← 120 → 48 节点
node-red/flows_creator_full.json.bak  ← 完整原始备份
web/static/dashboard.js               ← pageUrlPath() 对 ui-page 返回 /dashboard/
DEVELOPMENT_PLAN.md                   ← 本节
```

#### 🟡 后续

- 控制端 (`[1.x] 指挥中心控制端`) 保留原 ollama 翻译链，为公司接真实设备做准备；当前家中没设备所以 tcp-out 192.168.5.20:8932 会连接失败（不影响其他流）
- 当 dashboard 2.0 加多个 ui-page 时，pageUrlPath 还需要在 SPA 内部用 vue-router/postMessage 跳转（先不做，等加第 2 个 page 时再说）

---

### 2026-05-06 (回合 19) — 回合 18 收尾：左导航去重 + Node-RED iframe 头扩展

延续回合 18 遗留问题，做最小化修复：

#### ✅ 已完成

1. **左导航 Node-RED 子项重复修复**（`web/static/dashboard.js`）
   - 根因确认：`detectNodeRedPages()` 在 init（行 764）+ 首次点击 Node-RED 项触发 `loadNodeRed()`（行 633）各调一次 → `addNavItem` 没去重逻辑 → 子页加两遍
   - 修法：加模块级 `nodeRedNavAdded` once 标志，仅保护"加子项"代码块；selector 重建逻辑保留以便未来 Node-RED 流变化时刷新
   - 文件改动：`dashboard.js:622-624`（声明）`dashboard.js:665-679`（守卫）

2. **`node-red/settings.js` X-Frame 假设被实测推翻 → 已回滚**
   - 原以为 `httpAdminMiddleware` 只对 `/admin/*` 生效，准备加 `httpNodeMiddleware` + `ui.middleware` 兜底
   - 实测（curl -I）：原版单 `httpAdminMiddleware` 在 Node-RED v4 实际对 `/`、`/ui/`、`/dashboard/` 全部生效，三条路径**都有 `Content-Security-Policy: frame-ancestors *`，都没有 `X-Frame-Options`**
   - 结论：iframe 黑屏的根因**不是** X-Frame；可能是 dashboard SPA 的 vue-router base、跨端口 fetch 鉴权、或 flows.json 里 widgets 依赖外部资源（rtsp/3588 推理）渲染异常
   - settings.js 已回滚到回合 17 的版本，避免无意义代码膨胀

3. **start.command Node-RED 启动超时太短**（待修）
   - 现 8 秒 timeout（16 × 0.5s），但 iCloud 路径上首次冷启动加载 palette + flows 实测要 50+ 秒
   - 现象：start.command 报"Node-RED 启动超时"但其实进程还在加载，~50s 后会自动起来
   - 修法（明日）：把 timeout 拉到 120 秒；或改为后台监控 1880 端口 ready 才算就绪

#### 🟡 待用户验证（需启动服务才能测）

启动 mosquitto + node-red + main.py 后，按这个顺序检查：

```bash
# 步骤 1：直接看 dashboard 路径有没有 X-Frame-Options
curl -I http://127.0.0.1:1880/ui/      # dashboard 1.x，期望无 X-Frame，有 frame-ancestors *
curl -I http://127.0.0.1:1880/dashboard/  # dashboard 2.0，期望同上
# 如果 1.x 已修但 2.0 仍带 X-Frame，需要进一步查 @flowfuse 配置

# 步骤 2：浏览器单独打开（不在 iframe 里）看页面渲染是否正常
open "http://127.0.0.1:1880/dashboard/"
open "http://127.0.0.1:1880/ui/"
# 若 widgets 显示但全是"待机"状态 → 是 flows.json 依赖外部资源（rtsp://192.168.5.31, 127.0.0.1:32168）
#                                     的问题，不是 iframe 隔离问题，需要走"修复路径 A"建专属流
# 若直接打开都空白 → flows.json 本身渲染挂了

# 步骤 3：dashboard 大屏内（5050），点左导航 Node-RED 多次切换，验证子项不再重复
```

#### 📋 文件改动清单（回合 19）

```
web/static/dashboard.js       ← 左导航 once 守卫
node-red/settings.js          ← 改后又回滚（X-Frame 兜底证明无必要）
DEVELOPMENT_PLAN.md           ← 本节 + 修正 X-Frame 错误假设
```

#### 📝 下次接手要做

如果上述"步骤 1"显示 dashboard 2.0 还是带 `X-Frame-Options`：
- 找 `node-red/node_modules/@flowfuse/node-red-dashboard/` 的中间件挂载点
- 或转用反向代理思路：让 web/server.py（5050）反代 1880 的 dashboard，**同源访问就完全绕开 iframe 跨端口问题**
- 或彻底改设计走"修复路径 B"：hero 不嵌 Node-RED，自绘 SVG 流转图

如果"步骤 2"显示原 flows.json 的 widgets 渲染挂了：
- 走"修复路径 A"：在 Node-RED UI 手建一个 av 系统专属页（mqtt-in `av/system/discovery/#` + ui-text 显示模块在线数；mqtt-in `av/audio/command` + ui-text 显示最新转写）
- 或者直接编写最小 flows.json 给项目专用，把 `node-red/flows.json` 替换；保留现有文件备份为 `flows_creator_full.json`

---

### 2026-05-06 (回合 18) — UI 大改：World Monitor 风格 + Node-RED 置顶 + 视频墙

R6 之后用户提出新方向：参考 [World Monitor](https://github.com/eliehab/world-monitor) 的 Infocomm 展台大屏风格，**Node-RED 面板置顶为中央焦点**，下方视频墙 + 转写/意图条带。同时彻底解决 MJPEG 在 Chrome 渲染的兼容性问题。

#### ✅ 已完成

**布局重构（dashboard.html / dashboard.js / 多个 renderer）**
- 顶部：品牌 + 状态 + 时钟（World Monitor 头部风格）
- **左导航**：discovery 驱动，按 `AI 流 / 系统 / 工具` 自动分组；模块在线/离线 badge；Node-RED 项展开后列出所有 dashboard 子页
- **总览主区**：上 Node-RED hero + 中视频墙 (2×2) + 下转写/意图紧凑卡
- **底部 ticker**：常驻 5 槽（转写/意图/CPU/MEM/NET）
- 模块视图各自独立，左导航点击切换
- **CSS 闪光反馈**：转写/意图/视频检测事件到达时对应卡片/画格 0.8s 蓝光脉冲

**视频流：从 multipart MJPEG 改为 snapshot polling**
- 借鉴上版 (flyfish17/av_unified_mvp 的 Streamlit dashboard.py) 的"页面级轮询"思路；进化为"img.onload 链式拉取单帧 JPEG"（只是没有 multipart 兼容性陷阱）
- video_processor 推理与采集**解耦为独立线程**：
  - capture 线程：30fps 采集 + 直接预编码 raw JPEG → 缓存
  - inference 线程：异步消费队列（drop-old），跑 YOLO，输出 annotated JPEG → 缓存
  - HTTP handler：直接返回缓存 JPEG bytes，无 imencode 开销
- snapshot 双模式：`?mode=raw`（30fps 流畅，无 bbox，给客户）/ `?mode=annotated`（2fps，带 bbox，给工程师）
- HTTP/1.1 + Connection:close + 状态机断流：camera 停用立即 503，无陈旧帧滞留
- 实测：raw 30fps，annotated 2.3fps（YOLO 受限），bandwidth 350-700 KB/s

**性能 / 鲁棒性优化**
- 视图切换/tab 后台 → polling 立即停（避免 4 路并发轮询堆积浏览器连接队列）
- 200ms 节奏（5fps/路），3 秒 watchdog 防卡死
- 停轮询时显式释放 img.src（透明 GIF 占位），避免破图图标
- web/server.py 加 SSE 重放缓存：新订阅者立即拿到所有模块快照（不再等 30s 心跳）
- BaseModule 修 client_id 唯一（之前所有模块共用 `av_box_001`，broker 互踢导致连接风暴）

**Node-RED 集成**
- 复制用户 `/Users/yumacs/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/Creator_AI语音转写_Air/flows.json` 到项目内 `node-red/flows.json`
- 装 `node-red-dashboard` 1.x + `@flowfuse/node-red-dashboard` 2.0（用户级 npm prefix `~/.npm-global`）
- 删 ui-chat 节点（新版 @flowfuse 1.30.2 已废弃）
- Node-RED v4.1.8 跑在 :1880，flows 正常加载，4 个 dashboard 页：
  - `[2.0] 二号采油站监控中心` (8 widgets)
  - `[2.0] CREATOR InfoComm 展台大屏` (1 widget)
  - `[1.x] 智慧工地 AI 监控` (8 widgets)
  - `[1.x] 指挥中心控制端` (4 widgets)
- iframe headers OK：`X-Frame-Options` 已移除，`CSP frame-ancestors *` 已设

**参考资料归档**
- 上版仓库：`~/Documents/_ref_repos/av_unified_mvp_old/`（独立目录，不与当前项目重叠）

#### 🟡 进行中 / 遗留问题（明日继续）

1. **Node-RED hero iframe 显示空白（黑/白背景，无内容）** —— 主要问题
   - dashboard 1.x `/ui` 和 2.0 `/dashboard/` HTTP 都返回 200 OK
   - iframe 加载了 dashboard SPA 框架（看到主题色：1.x 白色，2.0 黑色），但页面内容（widgets）没渲染
   - 可能原因：① Vue Router 在 iframe 内基础路径未正确解析 ② 跨端口（5050 vs 1880）+ iframe 的某种安全限制 ③ 用户原 flows.json 的页面 widgets 大量依赖外部资源（rtsp_01.jpg / 3588 推理服务器）不存在 → 渲染异常
   - **诊断方向（明日做）**：浏览器单独打开 `http://localhost:1880/dashboard/` 看是否正常 → 若正常则 iframe 隔离问题；若也空白则 flows 本身依赖问题
   - **绕行方案**：在 av_unified_mvp 项目里建一个**专属** Node-RED 流（mqtt-in `av/system/discovery/#` + `av/audio/command` + `av/video/detect` → 几个 ui-text/ui-chart widget），作为系统总览专用页

2. **左导航 Node-RED 子项被加了两次** —— 截图可见每个子页出现两遍
   - 原因：`detectNodeRedPages()` 在 init 时调用一次，setActive("__nodered") 时通过 `loadNodeRed()` 又调一次
   - 修复方向：detectNodeRedPages 加 once 守卫；或 addNavItem 检查重复

3. **Node-RED dashboard 2.0 ui-chat 不再存在**
   - 已从 flows.json 移除该节点；如果用户原 flow 在该节点上有依赖，需要在 Node-RED 编辑器里手动重连

4. **YOLO 在 video_processor 的初始 imageio 警告**
   - 不影响功能，但日志噪音，明日清理

5. **模块拖动重排**
   - 已 defer，整体框架定型再做

#### 📋 文件改动清单（回合 18）

```
modules/video_processor/main.py        ← MJPEG 服务双端点 + HTTP/1.1
modules/video_processor/processor.py   ← 推理独立线程 + raw/annotated 双缓存 + 预编码 JPEG
core/base_module.py                    ← client_id 唯一化
web/server.py                          ← SSE 重放缓存 + /mqtt/publish 通用代理
web/templates/dashboard.html           ← 全新布局：左导航 + 总览(NR hero + 视频墙 + 条带) + ticker + 闪光动画
web/static/dashboard.js                ← discovery 驱动导航 / 视频墙 / Node-RED 多页 / 视图感知 polling 暂停
web/static/renderers/mjpeg.js          ← snapshot 轮询 + 视图感知
web/static/renderers/kv_table.js       ← host_stats / network / lan_scan 摘要化 + sticky 行
web/static/renderers/scan_trigger.js   ← LAN 扫描触发控件（新增）
web/static/mjpeg-test.html             ← 调试用（可删）
node-red/flows.json                    ← 替换为用户的 Creator_AI语音转写_Air/flows.json
node-red/package.json                  ← 加 dashboard 1.x + 2.0 依赖
node-red/settings.js                   ← iframe 友好 + flows.json 入口
start.command                          ← npm-global PATH + Node-RED 拉起 + 退出清理
DEVELOPMENT_PLAN.md                    ← 本次更新
```

### 2026-05-06 (回合 17 续2) — R6 三个新订阅模块完成

R6 是订阅式架构的"试金石"——验证 R1-R3 搭的协议（discovery + streams + 动态 SSE channel）是否做到了"加模块前端零改动"。结果：✅ 三个新模块加进 `MANAGED_MODULES` 即在 UI 上自动出现 panel。

- ✅ **`modules/system_info/main.py`**：每 5s 推 `av/system/host_stats`（CPU% / 核数 / 内存 GB / 磁盘 / load1/5/15）；用 `psutil.cpu_percent(interval=None)` 非阻塞采样，`getloadavg()` 在 macOS 可用
- ✅ **`modules/network_info/main.py`**：每 10s 推 `av/system/network`（每个 up 网卡的 IP / 速率 Mbps / 当前发收 KB/s）；维护 `_prev_io` 快照用 `bytes_sent/recv` 增量算速率
- ✅ **`modules/network_scanner/main.py`**：监听 `av/system/lan_scan/cmd`，并发 64 线程 TCP `connect_ex()` 探活，进度推 `lan_scan/progress`，结果推 `lan_scan/result`；默认子网由 `psutil.net_if_addrs()` 推 `/24`
- ✅ **`main.py`**：`MANAGED_MODULES` 加 3 行；MQTT 旁路新增 3 个订阅（`av/system/host_stats` → `host_stats` SSE / `av/system/network` → `network` SSE / `av/system/lan_scan/+` → `lan_scan` SSE）

#### 验收记录（实测数据）

```
6/6 模块 spawn 成功
av/system/host_stats: cpu 5.6%, mem 36%, load 2.87 (5s 一次稳定)
av/system/network:    en0=192.168.5.119@1Gbps, en1=192.168.5.5@WiFi, ... (10s 一次)
av/system/lan_scan/cmd → /28 14 主机 → 0.45s 完成 → 找到 .1/.2/.5 三台
SSE /events/host_stats、/events/network 均收到事件（curl -N 验证）
```

#### 前端零改动验证

`web/static/dashboard.js` 没改一行；`createPanel()` 直接读 discovery 公告里的 streams[].kind = "kv_table"，挂上现有的 kv_table renderer。这就是 R3 协议设计的目的：UI 是 schema-driven 的，模块自报家门即可上线。

### 2026-05-06 (回合 17 续) — R5 Node-RED iframe 嵌入（代码完成）

- ✅ **`node-red/settings.js`** 新建：`httpAdminMiddleware` 移除 `X-Frame-Options` + 设 `frame-ancestors *`；`flowFile: flows.json` 与现有 flows 同步；关 projects 弹窗
- ✅ **`web/templates/dashboard.html`**：顶栏新增 `class="tab"` 切换条（实时面板 / 编程 (Node-RED)）；两个 `<main class="page">` 用 display:none/active 切换；`<iframe id="node-red-frame">` 懒加载（首次切到该 tab 才探测 :1880 + 注入 src，不可达则显示 fallback 提示）
- ✅ **`web/server.py`**：开发期 `TEMPLATES_AUTO_RELOAD=True`，模板改了无需重启 main.py
- ✅ **`start.command`**：在 main.py 之前可选拉起 `node-red --userDir ./node-red --port 1880`（已在跑则跳过；命令不存在仅 warn）；`trap cleanup EXIT INT TERM` 退出时收尾
- 🟡 **顺手修了 pre-existing bug**：`core/base_module.py` 所有模块共用 `client_id=av_box_001` → broker 互相踢 → 启动后连接风暴。改为 `f"{base_cid}_{name}_{uuid_hex}"`，每模块唯一
- ✅ **端到端验证通过**：用 `npm config set prefix ~/.npm-global && npm i -g node-red` 装到用户级 prefix（避免 sudo）；start.command 已加 `[ -d "$HOME/.npm-global/bin" ] && export PATH=...`；node-red v4.1.8 启动后：
  - 加载我们的 `node-red/settings.js` ✓
  - 加载项目 `node-red/flows.json`（含原 mqtt-broker 节点，自动连 127.0.0.1:1883）✓
  - `curl -I http://127.0.0.1:1880/` 返回 `Content-Security-Policy: frame-ancestors *`，无 `X-Frame-Options` ✓
  - dashboard 编程 tab 的 fetch HEAD 探测会成功，iframe 可加载

### 2026-05-06 (回合 17) — R4 MJPEG 视频画面完成

**架构选择**：因 R2 已把 video_processor 拆成独立子进程，无法再与 web/server.py 共享内存帧；改方案是 video_processor 自带 HTTP 服务（端口 5051），UI `<img>` 直接拉取，无需经过 web/server.py 代理。

- ✅ **`modules/video_processor/main.py`**：内嵌 `ThreadingHTTPServer` 监听 `0.0.0.0:5051`，提供 `GET /video_feed/<name>`，从 `VideoProcessor.get_latest_frame()` 拿帧 → `cv2.imencode('.jpg', q=75)` → `multipart/x-mixed-replace`，约 15 fps；`endpoints[]` 写实际 URL（`http://127.0.0.1:5051/video_feed/<name>`），前端会按 `window.location.hostname` 改写
- ✅ **`av/video/cmd/+` 处理**：`_handle_message` 解析 `payload.action ∈ {enable, disable}`，更新 `_sources` 与 `endpoints` 的 `enabled` 字段，调 `processor.reload_sources()`，再 `_publish_discovery("online")` 让 UI 收到新状态
- ✅ **`web/server.py`**：新增 `set_mqtt_publisher(fn)` 模块级注入；新增 `POST /camera/<name>/<action>` 端点，把动作发到 `av/video/cmd/<name>`
- ✅ **`main.py`**：`_start_web()` 中注入 `set_mqtt_publisher(self.mqtt.publish)`，让 web 端能反向触达 MQTT
- ✅ **`web/static/renderers/mjpeg.js`** 完全重写：从 discovery `endpoints[]` 读出每路摄像头，渲染成卡片（含启用/停用按钮）；URL 经 `rewriteHost()` 改成 `window.location.hostname` 解决 LAN 访问；`setEndpoints()` 暴露给 dashboard.js
- ✅ **`web/static/dashboard.js`**：`createPanel()` 现在为每个 renderer 分配独立子容器（避免 kv_table 的 `trim()` 误删 mjpeg 卡片）；`updateModule()` 在每次 discovery 更新时重新喂 `setEndpoints`，所以用户点启停后画面/按钮文字立即反应
- 🟡 **未做**：visibilitychange 自动启停（计划里说切 tab 停解码）。当前用户主动点按钮，足够 R4 验收；若后续要节能可叠加

#### 验收方式

```bash
# 不改 system_config.yaml 也行，所有摄像头默认 enabled=false
python3 main.py
# 浏览器打开 http://localhost:5050 → video_processor panel 列出 4 张卡，状态"已停用"
# 点"启用" → MJPEG 画面流入；点"停用" → 画面停止，CPU 下降
# mosquitto_sub -t 'av/video/cmd/#' -v 可看到对应启停消息
```

### 2026-05-06 (回合 16) — R2 + R3 完成

#### R3：UI 动态化
- ✅ **`core/mqtt_bridge.py`**：加 `_topic_matches()` + `_parts_match()` 静态方法，`_on_message` 改为遍历所有 pattern 做通配符匹配（`#` 和 `+`），支持 `av/system/discovery/#` 订阅
- ✅ **`main.py`**：新增 `av/system/discovery/#` MQTT 订阅 → `_on_discovery_mqtt()` → push 到 `"discovery"` SSE channel；新增 `_announce_supervisor()` —— web 启动 1s 后推伪 discovery 让前端生成控制面板
- ✅ **三个模块 `main.py`** 的 `streams[]` 加 `channel` 字段（audio→`transcript`, video→`video`, llm→`intent`），UI 据此知道订阅哪个 SSE channel
- ✅ **`web/server.py`**：删 `CHANNELS` 白名单；`push()` 改为 defaultdict 自动注册任意 channel；`for _ch in CHANNELS: add_url_rule` 改为单条 `@_app.get("/events/<channel>")`，任意 channel 均可访问
- ✅ **新建 `web/static/renderers/`**：`transcript_seq.js`（气泡 partial→final）/ `kv_table.js`（通用摘要行 + fallback JSON dump）/ `mjpeg.js`（R4 占位）；用 `window.Renderers.*` 命名空间，无需打包工具
- ✅ **`web/static/dashboard.js` 完全重写**：订阅 `/events/discovery` → `handleDiscovery()` 动态创建/更新 panel；`modules: Map` 追踪状态；`setInterval(5s)` 超 `2.3×heartbeat_interval` → `.offline` 灰显；`_announce_supervisor` 生成的 control panel 自动出现
- ✅ **`web/templates/dashboard.html` 完全重写**：删 4 个写死 `<section>`；`<main id="grid">` + CSS `repeat(auto-fit, minmax(420px, 1fr))`；加 `.panel.offline` 透明度 + `::after "已离线"` 样式；先加载 3 个 renderer 脚本再加载 dashboard.js
- 📌 **完整验收**（需 mosquitto + 完整 yzj 机器）：启动 `python main.py`，浏览器看到 3+1 个 panel 自动生成（无硬编码）；kill audio_processor 进程 → 70s 内 panel 灰显；重启后变绿
- 📌 **R4 mjpeg.js** 目前仅占位（显示"视频流 R4 启用"）；视频摄像头默认 `enabled=false`，待 R4 补 `/video_feed/<camera>` 端点

#### R2：main.py supervisor 化
- ✅ **main.py 完全重写为 AVSupervisor**：删除所有 `from modules.<x>.<y> import` 直接调用；改成 `subprocess.Popen × 3` 拉起独立模块
- ✅ **supervisor 主循环 `_tick()`**：每秒 `poll()`，崩溃后指数退避重拉（1s→2s→4s→...→60s）；5 次连续失败升级 ERROR 告警；运行超过 60s 后崩溃重置退避计数
- ✅ **MQTT→SSE 桥接**：main.py 订阅 5 路 topic（audio/partial, audio/command, video/detect, llm/event, control）→ 分别推到 4 个 web SSE channel；兼容 BaseModule 双层载荷和 Node-RED 平层载荷两种格式
- ✅ **`modules/llm_engine/main.py`**：新增订阅 `av/audio/command`（主路径），保留 `av/llm/command`（向后兼容）；`_handle_message` 过滤掉 `is_final=False` 的 partial
- ✅ **`modules/llm_engine/engine.py`**：`process_command()` 在生成命令后同时发布 `av/llm/event` 和 `av/control`（无需 Node-RED 中转，两者并存不冲突）
- ✅ **`generate_command()` 修复**：LLM 输出 `{"command": "DeviceName_Action"}` 时，之前直接返回字符串导致 `{**cmd}` 崩溃；现在拆分为 `{"target": "DeviceName", "action": "Action", "command": "..."}` 或 `{"command": "..."}` 兜底
- ✅ **cwd bug 修复**：`_project_root` 原来取 `config_path.parent`（= `config/` 目录）导致子进程找不到 `modules` 包；改为 `config_path.parent.parent`（= 项目根）
- ✅ **端到端功能验证**（mosquitto 未运行环境下）：子进程成功找到模块包、进入 MQTT connect 阶段才因 broker 不可用崩溃（非代码错误）；supervisor 退避日志正确；SIGTERM 干净退出
- 📌 **完整 R2 验收**（需 mosquitto 运行）：`mosquitto -c /opt/homebrew/etc/mosquitto/mosquitto.conf -d` 起 broker 后，`pgrep -af "modules\\."`应看到 3 个独立 Python；kill 任一个后 2s 内 supervisor 重拉
- 📌 flask 未安装到当前机器（yumacs），web SSE 在 yumacs 上无法启动；回到 yzj 机器正常

### 2026-05-05 (回合 15) — R1 公告协议统一 + LWT
- ✅ **新公告 schema**：`av/system/discovery/<module>` retain=true，QoS=1，含 `streams[]` / `endpoints[]` / `heartbeat_interval` / `event=online|heartbeat|offline`
- ✅ **LWT (last will)**：模块崩溃 / 强杀 → broker 自动发 `event=offline` retain，覆盖 online；后开订阅立即看到正确状态
- ✅ **30s 心跳**：BaseModule.run() 周期发 retain heartbeat，新订阅永远拿得到当前状态
- ✅ **三个 in-process 模块补 streams**：audio（transcript_seq×2）、video（kv_table + mjpeg endpoints[]）、llm（kv_table）
- ✅ 删 `core/mqtt_bridge.py:69` 旧 `av/discovery` 单层公告
- ✅ §4 协议表更新到 R1 版（旧版废弃 + 新 schema 文档化）
- ✅ **端到端验证**：`python3 -m modules.audio_processor.main` → mosquitto_sub 看到 online → 30s 后 heartbeat → kill -9 强杀 → broker 立即 LWT offline → 新 sub 起来直接看到 retained offline
- 📌 已知遗憾：LWT 的时间戳是模块启动时 frozen 的，不反映真实崩溃时间；UI 用 lastSeen + 2.3×interval 阈值判活，offline 事件作为附加信号

### 2026-05-04 (回合 14) — 用户视角验收 + 方向重新校准
- 用户作为最终用户启动 dashboard，看到三层差距：
  1. 当前面板是事件流调试视图，不是产品 UI
  2. 视频区只有文本无画面，且配置默认所有摄像头 `enabled=false`
  3. Node-RED 没有入口，从浏览器找不到怎么编排
- 用户拍板方向：**最终用户是普通用户**；类 woldmonitor 订阅制是灵魂；UI 中可选择 MQTT 公告的数据并显示；模块要乐高积木式可拆装
- 用户给出 5 个决策（Node-RED 嵌 A=iframe / 沿用当前架构 / 视频参考 woldmonitor / 公告失活 B=灰显保留 / 首批新模块清单）
- 启动 Plan 模式：3 个 Explore 调研（当前项目、woldmonitor、上版 GitHub）+ 1 个 Plan agent 综合设计 + 2 个 AskUserQuestion 拍板（main.py 改 supervisor + renderer 极简 3 种）
- 产出：`/Users/yzj/.claude/plans/1-node-red-a-creator-2-3-world-monitor-piped-wadler.md` R1-R6 实施计划，4.5 天
- 关键判断：当前架构 70% 已为订阅式准备好（SSE 多频道 + BaseModule discovery + 模块独立），不是跑偏，是补完

### 2026-05-04 (回合 13) — 已完成部分端到端联调（真 mic + Node-RED + 浏览器）
- **背景**：用户在家场景没有公司 IR 设备（命令字典里的 `2FDiningTable_AirConditioner` 等），只有 Aqara 家居 → 跳过 P4 真实接入，做联调
- **启动顺序**：mosquitto + funasr-2pass(medium 档) + Node-RED 隔离实例(`/tmp/av_nr_test`, port 1881) + main.py + 旁路 sub，4s 内全就绪
- **真实链路**：用户说『打开二楼餐桌空调』→ FunASR 6 partial + 2 final → MQTT av/audio/command → Node-RED function → 翻译 av/control → main.py._on_control → web SSE control 区两行绿色 ✅
- 🐛 **联调暴露真 bug：flows.json function 节点 schema 假设错误**
  - 现象：真实说话后 av/audio/command 计数 2 条，但 av/control 0 条；Node-RED 没任何 `[skip]` warn → function 根本没收到数据
  - 根因：function 节点写的是 `msg.payload.payload.text`（参考 BaseModule.publish 双层包装），但 `main.py` 走 `core/mqtt_bridge.MQTTBridge.publish` 直发裸 dict，字段在根级 `msg.payload.text` → function `body.is_final !== true` 永远 true 直接 return null
  - 修法：function 改成 `const body = raw.payload || raw`，**两种 schema 都兼容**（独立模块 / 集中主程都能跑）；correlation_id 也加了 `rt-<Date.now()>` fallback 兜底
  - **教训**：P2 端到端验证那次用 mosquitto_pub 手造的是双层载荷，跟主程实际发的不一致，所以那次"5/5 通过"其实只验证了 schema 一种分支；联调真主程才把另一条分支测出来。今后类似端到端测试要**用主程实际产物**，不要手造
- ✅ 修完后用 mosquitto_pub 重发 3 条真实 schema final（避免让用户再说一次）：『打开二楼餐桌空调』→ `2FDiningTable_AirConditioner / On`、『关闭机房空调』→ `EngineRoom_AirConditioner / Off`、『今天天气不错』→ `[skip] 非控制意图`，全部预期
- ✅ 浏览器 dashboard 用户肉眼确认 control 区两行绿色
- 📌 ollama 在用户机器上未启 → main.py 自带的 LLM 翻译路径会 ERROR（预期内，关键词意图照常工作）；Node-RED function 走的是关键词翻译，不依赖 ollama，端到端可用

### 2026-05-04 (回合 12) — Bug A + Bug B 修复
- ✅ **Bug A：本地兜底真离线**
  - 根因：`modules/audio_processor/processor.py` 的 `_start_local_offline` 用 `model="iic/SenseVoiceSmall"` 这种 hub-id 形式调 `funasr.AutoModel`。即使传了 `disable_update=True`，funasr 1.3.x 仍会去 `modelscope.cn` 探测/下载（disable_update 只控版本检查，不控 download 探测）；离线状态下这一探测会让 loky pool 崩，进而把 `main.py` 整个拖崩
  - 修法：本地缓存命中时改用绝对路径 `~/.cache/modelscope/hub/models/iic/SenseVoiceSmall`，funasr 看到绝对路径就完全不会去 hub 探测
  - 加固：`main.py` 顶部 `os.environ.setdefault` 给 `MODELSCOPE_DOMAIN=`、`HF_HUB_OFFLINE=1`、`TRANSFORMERS_OFFLINE=1` 三个离线环境变量（必须在 import funasr 之前）
  - 验证：`AV_PROFILE_OVERRIDE=light python3 main.py` → 8s 内 `使用本地缓存模型: ~/.cache/modelscope/.../SenseVoiceSmall` + `FunASR 模型加载完成`，零 modelscope 探测，9s 后进程仍在跑
- ✅ **Bug B：docker 不可用时优雅降级到 light**
  - 根因：用户为节省内存主动关 Docker Desktop。原 `start.command` 在 `docker info` 失败时直接 `die`（read 等回车后 exit 1），用户体验差
  - 修法：`docker info` 失败时改 `warn + export AV_PROFILE_OVERRIDE=light + PROFILE=light`，跳过容器分支继续启动；不写回 `config/system_config.yaml`（避免 silently 改用户配置）
  - 联动改 `main.py._apply_profile`：识别 `AV_PROFILE_OVERRIDE`，**强制覆盖**（不是 setdefault）`audio.funasr.mode` 与 `video.yolo.model`，否则 config 里写死的 `mode: websocket_2pass` 会让 main.py 仍按 medium 行为去连不存在的 docker
  - 验证：用 fake `docker` 命令（PATH 注入 `exit 1` 脚本）跑 start.command 关键判断块，最终 `PROFILE=light  AV_PROFILE_OVERRIDE=light`，跳过容器分支
- 📌 组合证据闭合：start.command 切档（Bug B 静态验证）+ main.py 拿到 OVERRIDE 后走本地路径（Bug A 端到端验证）= 关 Docker 后双击 `start.command` 仍能用，且离线不崩

### 2026-05-04 (回合 11) — P3：拆多路 SSE + 单页四区面板
- ✅ `web/server.py` 重构：`_subscribers` 改为 `dict[channel, list[Queue]]`；通用 `push(channel, ev)` + `_make_sse(channel)` 工厂；4 路端点（transcript/video/intent/control）；保留 `push_event` 别名兼容旧调用
- ✅ 新增 `POST /mock/<channel>`：body 即 payload 直接推到对应 channel；前端能脱离主程独立调样式
- ✅ 前端：`dashboard.html`（CSS grid 2x2）+ `dashboard.js`（每区独立 `EventSource` + 独立渲染器）：
  - transcript 区复用 partial→final 气泡（seq_id 复用同气泡，黄虚线 → 绿实线）
  - video 区折叠 detections 为 `class×N` 摘要
  - intent 区命中显示 `→ {target,action}` 绿框，未命中显示 `(非控制意图)` 灰框
  - control 区显示 `target · action · params` + `original_text` 元数据
  - `/transcript` 旧单页路由保留向后兼容
- ✅ `main.py` 接入：
  - `_web_push` 从 `Optional[Callable[[dict], None]]` 改为永远可调用的 `lambda *_: None`，启动后被 `web.server.push` 替换
  - `_on_audio_event` 推 `transcript`，意图分类后推 `intent`，命中翻译后推 `control`
  - `_on_video_event` 推 `video`
  - `_on_control` 推 `control`（接收外部 MQTT 控制指令时也显示在面板）
- ✅ 端到端验证：
  - 4 路 SSE hello 自检通过
  - 4 路 `POST /mock/*` 全部返回 `{ok:true, channel}`
  - 开 SSE 长连 + 注入假事件 → 实时收到（curl + 浏览器双重验证；浏览器面板 4 区域更新逐项确认）
  - 静态资源 200 OK：`/`(5321B) `/transcript`(2608B) `/static/dashboard.js`(4953B) `/static/transcript.js`(2082B)

### 2026-05-04 (回合 10) — P0 真实拔网测试通过
- ✅ 流程：先把 main.py + 旁路 `mosquitto_sub -t 'av/#'` 在 wifi 在线下跑起来等"全部就绪"（5s 内：MQTT/FunASR-WS/录音流/web 5050 全到位），然后关 Wi-Fi，再对麦克风说一句『打开二楼餐桌空调』
- ✅ 关 wifi 后 30s 观察期内：
  - `av/audio/partial` × 11（含"打开"、"二楼餐"、"桌空"、"调"等流式片段，`raw_mode=2pass-online`）
  - `av/audio/command` × 5（含"打开二楼"、"餐桌空调"、"。打开二楼餐桌，空调"，`raw_mode=2pass-offline`）
  - main.py 关键词意图识别命中 `[LLM] 检测到控制意图`
- ✅ **零外网请求失败**：日志里没有 modelscope / huggingface / aliyun 等任何外网域名访问 —— `MODELSCOPE_DOMAIN=` 配合 funasr 模型已下载完整，离线启动/运行无对外探测
- ⚠️ 唯一 ERROR：`HTTPConnection(host='127.0.0.1', port=11434) Connection refused` —— 是 ollama 服务**本来就没启**，不是断网导致；证明 `modules/llm_engine` 在 ollama 不可用时优雅降级（关键词分类不挂）
- ✅ Web SSE：浏览器在 wifi 关闭状态下仍能正常访问 `http://localhost:5050/` 取 transcript.js 和 SSE 流（127.0.0.1 不走外网）

### 2026-05-04 (回合 9) — P0 收尾：funasr 容器关掉 modelscope 在线探测
- ✅ `start.command` 的 `docker run` 加 `-e MODELSCOPE_DOMAIN=`：阻止 funasr 二进制内调 modelscope SDK 时的版本探测，避免离线启动时 DNS/HTTP 卡顿
- ⚠️ **走过的坑**：原计划同时加 `--disable-update true` 双保险，但 `docker exec funasr-2pass cat /workspace/FunASR/runtime/run_server_2pass.sh` 看清楚后发现脚本用 `parse_options.sh` 严格解析参数，未识别项会 `exit 1`，加上反而**会破坏启动**。只保留 env 变量这一条路
- ✅ `start.command` 加旧容器自检：`docker inspect ... | grep MODELSCOPE_DOMAIN=`，缺失时 warn 提示用户 `docker rm -f funasr-2pass && 再次双击` 重建（模型缓存挂在 `~/funasr-runtime-resources/models` volume，重建不丢）
- ✅ 实际重建验证：`docker rm -f funasr-2pass` → 用新参数 `docker run` → 1s 端口监听 + ~50s 模型加载完毕 + supervisor 跟踪 PID 35 + `printenv MODELSCOPE_DOMAIN` 显示空字符串生效
- 📌 **P0 还差**：真实拔网测试（需要主动断 wifi/网线，用户手动配合）

### 2026-05-04 (回合 8) — P2 端到端验证
- ✅ 在隔离实例 `node-red --userDir /tmp/av_nr_test --port 1881` 起 Node-RED（不动用户 `~/.node-red/flows.json`）
- ✅ Node-RED 2s 内启动 + 部署 flow + 连上 broker `node_red_av@mqtt://127.0.0.1:1883`
- ✅ 5 条 mosquitto_pub 模拟 `av/audio/command` final 全部通过：

  | 输入文本 | 期望 | 实际 av/control |
  |---|---|---|
  | 打开二楼餐桌空调 | 2FDiningTable_AirConditioner / On | ✅ |
  | 关闭机房空调 | EngineRoom_AirConditioner / Off | ✅ |
  | 打开窗帘 | MeetingRoom1_Curtain / Open | ✅ |
  | 餐桌灯关一下 | DiningTable_Light1 / Off | ✅ |
  | 聊聊天气 | 应过滤 | ✅ function 节点 warn `[skip] 非控制意图` |

- ✅ `correlation_id` 从 `header.msg_id` 正确透传到 `av/control` 载荷
- ✅ 验证完关闭 Node-RED 实例，用户的 `~/.node-red/flows.json` 未受影响

### 2026-05-04 (回合 7) — P2 起步：Node-RED flow 对齐 §4
- ✅ **独立模块端到端验证**：`python3 -m modules.audio_processor.main` 1s 内 MQTT/FunASR/录音三件全到位；70s 观察期内 `mosquitto_sub -t 'av/#'` 收到 discovery 上线广播 + 60s 心跳 + 真实人声触发的 partial/final（"小天"、"，他想"），seq_id 复用、raw_mode online↔offline 切换符合 §3
- ✅ **flows.json 重写**：旧 CREATOR 版本 763 行（订阅 `creator/control/voice` / `audio_intent` 等历史 topic，function 节点里塞着已被 `modules/llm_engine` 取代的 systemPrompt）→ 归档为 `flows_legacy_creator.json`，删除完全重复的 `flows_template.json`
- ✅ **新 flows.json**（10 节点最小骨架）：
  - `mqtt in av/audio/command` + `inject` 模拟节点 → `function 提取文本+过滤` → `function 翻译为指令` → `mqtt out av/control` + `debug`
  - 旁路：`mqtt in av/#` → `debug 总线观察`
  - 翻译 function 与 `modules/llm_engine.COMMAND_PROMPT` 的命令字典对齐（2FDiningTable_AirConditioner / EngineRoom_AirConditioner / MeetingRoom1_Curtain / DiningTable_Light1）
- ✅ **README 加「Node-RED 编排」一节**：导入步骤（UI / cp 两条路径）+ 加新场景的 4 步骨架（MQTT in → function → mqtt out → debug）
- 📌 **未做**：没把新 flow 部署到用户的 `~/.node-red/flows.json`（那是他活跃的 CREATOR 工作环境，避免误伤）；端到端真实 Node-RED 跑一次留给用户手动 import

### 2026-05-04 (回合 6) — P1 收尾：video / llm 模块去重
- ✅ **video_processor 合并**：以 `core/` 版的清爽风格为基础（顶部统一 `import threading/queue/os`、`@dataclass DetectionEvent` 模块级定义），并入 `modules/` 版的 `set_mqtt_publisher()` 钩子。callback 与 MQTT publisher 可同时启用，互不冲突。
  - 修复：原 `modules/` 版本把 `DetectionEvent` 写在 `_process_stream` 循环里每次回调都重定义类，性能/类型混乱
  - 修复：原 `modules/` 版用了 `__import__("threading").Event()` 这种丑陋 inline import
  - 协议对齐：`_publish_detection` 发到 `av/video/detect`（§4），载荷 `{camera, time, detections}`，与 main.py 当前格式一致
- ✅ **llm_engine 合并**：以 `modules/` 版的"关键词分类 + 项目命令字典 prompt + process_command"为功能基础。
  - 修复 bug 1：`_ask` 用 `resp.json()["response"]` 而非 `r.text`（modules 版直接拿 raw HTTP body 当响应内容是错的）
  - 修复 bug 2：构造函数 `cfg.get("ollama")`，main.py 传入的本就是 `llm` 子字典，原 modules 版又 `.get("llm")` 一层导致永远拿不到 ollama 配置
  - 加锁：恢复 `_lock` 保护并发 ollama 请求（来自 core 版）
  - 兼容：保留 `LLMEngine.COMMAND_PROMPT` 类属性（含项目命令字典），`ui/dashboard.py:192` 的 `llm.COMMAND_PROMPT + text` 拼接仍可工作
- ✅ 删 `core/video_processor.py`、`core/llm_engine.py`；`main.py` 与 `ui/dashboard.py` 的 import 路径全部切到 `modules.<x>.<y>`
- ✅ 冒烟通过：MQTT 已连 1883、YOLO 模型加载、`modules.video_processor.processor` / `modules.audio_processor.processor` / `core.mqtt_bridge` 全部正常启动（FunASR 10095 警告与 docker 未启相关，非本次回归）
- 📁 目录现状：`core/` 仅剩 `base_module.py`、`mqtt_bridge.py`、`profile.py` —— 都是基础设施，没有业务双份了

### 2026-05-03 (回合 5) — 稳定性修复
- 🐛 **现象**：转写运行几分钟后停止，但容器/main.py/MQTT/视频流全部健康
- 🔍 **根因三层**：
  - L1：`funasr-wss-server-2pass` 0.1.12 本身处理某段音频时段错误（已知 bug）
  - L2：之前用 `bash -c "...; tail -F"` 让 server crash 后容器还活着 → `--restart unless-stopped` 失效
  - L3：宿主机 `nc -z 10095` 假成功（docker-proxy 接 SYN），但容器内 WS 连立即被 reset
- ✅ **L2 修法**：start.command 容器入口换成 supervisor 模式
  - `pgrep -x funasr-wss-serv`（注意 `/proc/PID/comm` 截断到 15 字符）轮询 server PID
  - `while kill -0 $SERVER_PID; do sleep 5; done` 陪跑直到 server 死
  - server 死 → 容器 `exit 1` → docker `--restart` 自动拉起 → 完整恢复 ~60s（模型重新加载）
- ✅ **压测验证**：`docker exec funasr-2pass kill -SEGV 35` 模拟 crash → 容器 T+3s 自动重启 → 60s 后服务完全恢复
- ✅ **L3 已存在**：客户端 `websockets` 库 `ping_interval=20, ping_timeout=20` 自动检测僵尸连接 → 触发 `_supervise_ws` 重连计数 → 连续 5 次失败降级 `local_offline`

### 2026-05-03 (回合 4)
- ✅ 性能档位抽象 `core/profile.py`（light / medium / heavy）：
  - `light`：本地 SenseVoiceSmall，**无需 Docker**，~500 MB；适合 RK3588
  - `medium`：FunASR 2pass 无 LM，~1 GB；适合 M1 / 16 GB Mac（当前）
  - `heavy`：FunASR 2pass + LM，~2.2 GB；适合 32 GB+
- ✅ `config/system_config.yaml` 加 `system.performance_profile`，留空时按内存自动推荐
- ✅ `main.py` 启动时打印当前档位 + 硬件 + 推荐项（仿 woldmonitor 风格软提示）
- ✅ `start.command` 探测 profile，light 档跳过 docker；docker 不可用时给出"切 light 档"建议
- ✅ Docker 可选化结论：**仅 medium/heavy 档需要**，light 档完全不需要

### 2026-05-03 (回合 3)
- ✅ 内存优化：funasr 容器从 **3.22 GiB → 911 MB**（降 71%）
  - 关掉 ngram LM（`--lm-dir ""`）省 ~900 MB
  - decoder 线程 8 → 4 省 ~250 MB
  - 加 `--memory=2.5g` 硬上限 + `--restart unless-stopped` 开机自启
- ✅ 双击启动：`start.command` / `stop.command`（可执行 .command 文件，Finder 双击即跑）
  - start：自动检测/启动 mosquitto、容器（不存在时建）、main.py、自动打开浏览器
  - stop：反向全部停掉
- ✅ 删旧 `start.sh`，README 改为"双击启动"为主路径

### 2026-05-03 (回合 2)
- ✅ FunASR 2pass 模型全部下完并加载（VAD / online paraformer / offline paraformer / punc realtime / itn / lm），监听 10095
- ✅ 本地 mosquitto 起来：`mosquitto -c /opt/homebrew/etc/mosquitto/mosquitto.conf -d`，`brew services` 因镜像问题失败，改用直接启动
- ✅ `config/system_config.yaml` broker 改 `127.0.0.1`
- ✅ 模块统一：`core/audio_processor.py` 删除，2pass 实现搬到 `modules/audio_processor/processor.py`，`main.py` import 改路径
- ✅ `modules/audio_processor/main.py` 重写：通过 MQTT 发 `av/audio/partial` / `av/audio/command`，可独立 `python3 -m modules.audio_processor.main` 启动
- ✅ 全链路自动化验证通过：
  - `MQTT 已连接 127.0.0.1:1883` ✅
  - `FunASR 已连接 ws://127.0.0.1:10095` ✅
  - SSE `/events/transcript` 收到 `{"type":"hello"}` 与真实 partial 事件（`raw_mode=2pass-online`）✅
  - `mosquitto_sub -t 'av/#'` 持续收到 `av/video/detect` ✅

### 2026-05-03 (回合 1)
- ✅ 升级语意理解：FunASR 2pass + partial/final/标点/整句修正
- ✅ 新增 `web/` Flask SSE 演示页（`/events/transcript`），原生 JS 前端
- ✅ `main.py` 适配 `TranscriptEvent`：partial 仅 SSE 展示，final 才走 LLM
- ✅ 加 WS 不可用 → `local_offline` 自动降级
- ✅ 测试项目（`/Users/yzj/Developer/av_unified_mvp`）→ 源项目（iCloud）业务代码同步
- ✅ 启动 `funasr-2pass` Docker 容器（修正了脚本后台启动 → 容器立即退出的问题：用 `bash -c "...; tail -F"` 让主进程不退）

---

## 7. 下次切入点（请直接从这里开始）

P0 / P1 / P2 / P3 全部完成。**下一步：P4（执行层桥接真实设备）+ 已发现的 2 个独立 bug 修复**：

### 启动顺序（已通过验证）
```bash
# 1. mosquitto（如未起）
mosquitto -c /opt/homebrew/etc/mosquitto/mosquitto.conf -d

# 2. funasr-2pass 容器（如未起）
docker start funasr-2pass    # 容器已存在，直接 start

# 3. 主程序
cd /Users/yzj/Developer/av_unified_mvp
python3 main.py
# 浏览器: http://localhost:5050

# 4. 旁路观察 MQTT
mosquitto_sub -h 127.0.0.1 -t 'av/#' -v
```

### 待办（小尾巴，主线在 §10 R 计划）

1. **P4 真实设备接入**（受限于环境，回合 14 后改为 R 计划主线之外的延期项）：用户家中只有 Aqara，跟项目命令字典（公司 IR）不匹配；等回公司或决定做家庭 demo 再启
2. **P2 真实部署**（可选）：把 `node-red/flows.json` import 到用户自己的 `~/.node-red/`（手动 UI 导入或备份后 cp）
3. **dashboard.py 真用一次或删掉**：回合 6 顺手把 import 切到 `modules/<x>.<y>`，但没跑过 `streamlit run ui/dashboard.py`；R 计划完成后决定保留还是删

---

## 8. 关键路径

| 路径 | 用途 |
|---|---|
| `/Users/yzj/Developer/av_unified_mvp/` | **测试项目**（开发改这里） |
| `/Users/yzj/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp/` | **源项目**（rsync 同步目标） |
| `~/funasr-runtime-resources/models/` | FunASR 模型缓存（首次下载约 2-3 GB，之后离线可用） |
| `/Users/yzj/Developer/woldmonitor/` | 前端订阅风格参考 |

同步命令（测试 → 源，排除 git/缓存/模型/密钥文件）：
```bash
rsync -av --delete \
  --exclude='.git/' --exclude='__pycache__/' --exclude='*.pyc' \
  --exclude='yolov8n.pt' --exclude='*KEY*.txt' \
  /Users/yzj/Developer/av_unified_mvp/ \
  "/Users/yzj/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp/"
```

---

## 9. 安全提醒

iCloud 源项目目录下原本有两个文件名直接含真实 API key 的 .txt（一份 Anthropic、一份 OpenRouter `sk-or-v1-` 开头的 key）。

**2026-05-05 处理**：
- 文件名已 redact 成 `ANTHROPIC_API_KEY=__REDACTED__chatlog_20260409.txt` / `OPENAI_API_KEY=__REDACTED__chatlog_20260409.txt`
- 文件内容首部加了安全注释说明，含吊销链接和建议
- 文件内容本身就是 Claude Code 会话日志（无 key），保留作历史参考
- **但 key 本身仍可能有效**（文件名 redact 不等于吊销）：明天上班第一件事去 console.anthropic.com / openrouter.ai/keys 撤销 + 看账单

---

## 10. 当前主线：订阅式架构演进（R1–R6）

回合 14 用户视角验收暴露三层差距：dashboard 是开发者调试视图不是产品；视频区只有文本无画面；Node-RED 找不到入口。用户拍板方向：「类 woldmonitor 的订阅制是灵魂，UI 让用户从 MQTT 公告里挑数据；模块要乐高积木式可拆装；最终用户是普通用户」。

详细设计：`./PLAN_R1_R6_subscription.md`（跟随项目同步，另一台机器也能读）

### 进度表

| 阶段 | 内容 | 工期 | 状态 | 验收 |
|---|---|---|---|---|
| **R1** | 公告协议统一 + LWT（`av/system/discovery/<module>` retain，30s 心跳，崩溃 LWT offline） | 0.5 天 | ✅ **完成**（回合 15） | mosquitto_sub 看到 online/heartbeat/offline 三态正确切换 |
| **R2** | main.py 退化为 supervisor（subprocess.Popen 拉三个独立进程，崩溃指数退避重拉） | 1 天 | ✅ **完成**（回合 16） | pgrep 看到 3 个独立 Python；kill 后 2s 自动重拉 |
| **R3** | UI 动态化：删硬编码 4 区，订阅 av/system/discovery/# 自动长出 panel；3 种 renderer（transcript_seq / kv_table / mjpeg）；失活灰显 | 1 天 | ✅ **完成**（回合 16） | 关 audio_processor，dashboard 70s 后灰显「已离线」 |
| **R4** | MJPEG 视频画面（video_processor 自带 5051 端口 HTTP 服务 + 按需 enable/disable） | 0.5 天 | ✅ **完成**（回合 17） | 浏览器多路 MJPEG 卡片；点"启用"出画面，点"停用"关闭 |
| **R5** | Node-RED iframe 嵌入（settings.js 解 X-Frame + start.command 自动起 1880） | 0.5 天 | ✅ **完成**（回合 17） | dashboard 顶部「编程」tab 加载 Node-RED 编辑器 |
| **R6** | 三个新订阅模块（system_info / network_info / network_scanner） | 1 天 | ✅ **完成**（回合 17） | 启动后 UI 自动多 3 个 panel，**前端零代码改动** |

### 关键决策（回合 15 用户拍板）

- Node-RED 嵌入 = iframe 嵌编辑器（"creator 中控编程"风格）
- main.py 架构 = 纯 supervisor（消除 `_on_audio_event → self.llm` 后门，模块真正独立）
- renderer 粒度 = 极简 3 种（transcript_seq / kv_table / mjpeg）
- 公告失活 = 灰显保留 + "已离线"标记（不删除）
- 视频技术 = MJPEG `<img src>`，复用内存帧，按需启用解码
- 554 LAN 扫描 = asyncio 重写（上版同步阻塞 30s+ → 并发压到 ~3s）

---

## 11. 下次切入点（请直接从这里开始）

> **阶段一完成宣告**（2026-05-08 r28-snapshot push 上 GitHub）。明天起转入**阶段二：子模块精进 sprint**。

### 5 分钟接手三步

1. `git clone -b r28-snapshot https://github.com/flyfish17/av_unified_mvp.git`，`cp config/system_config.example.yaml config/system_config.yaml` 改 RTSP 密码 + husion host
2. `sudo ifconfig en1 alias 192.168.150.250 netmask 255.255.255.0`（husion 网络，详见 README）+ `./start.command`
3. 看下方「阶段二精进路径」决定明天推哪个 Sprint

---

### 阶段一完成情况（不再回头）

**P0 三层闭环**
- ✅ L1 按钮：总览"快捷控制"卡按地点分组 → POST `/mqtt/publish` av/control → Node-RED 短连 → creator 中控（76 指令）
- ✅ L2 语音：FunASR 2pass → qwen3.5:9b（catalog driven prompt + 标点容错 + 笼统词灵活匹配）→ av/control
- ✅ L3 自动化：YOLO `person` → 开 `DiningTable_Light2` + 5min 无人自动关 / cron 13:00 + 亮度阈值 → 拉窗帘 1s

**跨品牌桥接**
- ✅ creator 中控 ASCII（TCP :8932 短连接 + 标点容错）
- ✅ husion HDC900 9 路 ws://flv 流注入视频墙（前端 flv.js + ifconfig alias 网络）
- 🔶 creator 分布式 driver（协议探明 TCP :12121 + 密码 `123456`，等 user 让 session 后实施 30-60min）
- 📋 husion 辅模式事件回传（接收方式待 user 明确）

---

### 各子模块成熟度（5 = 可深化精进 / 1 = 待启动）

| 子模块 | 成熟度 | 现状 |
|---|---|---|
| audio_processor | ⭐⭐⭐⭐⭐ | FunASR 2pass + ITN + 降级 + mic 自检 |
| video_processor | ⭐⭐⭐⭐ | YOLO + 多源 + MJPEG :5051 + 亮度采样 + CRUD + 持久化 |
| llm_engine | ⭐⭐⭐⭐ | catalog driven 76 指令 + classify_intent 自动 derive + Session 代理修复 |
| system_info / network_info / network_scanner | ⭐⭐⭐⭐ | CPU/MEM/网卡/速率/端口扫描 + 一键填表 |
| husion_distributed | ⭐⭐⭐ | TCP poll + flv 流注入视频墙（主消费） |
| creator_distributed | ⭐ | 协议探明，待启动 |

**基础设施**：MQTT 总线 + LWT discovery / 单聚合 SSE / Node-RED 60 节点 / catalog driven / GridStack UI 全可调 — 全部 ✅

---

### 阶段二精进路径（按业务价值 / 工时 / 风险排序）

#### 第一梯队（客户演示直接受益 · 总计 2-3 天）

| Sprint | 子模块 | 工时 | 演示价值 |
|---|---|---|---|
| **A. partial 逐词追加渲染** ✅ | audio_processor + 前端 transcript_seq.js | 半天 | 转写"逐字蹦"对标讯飞观感（commit ea4216b 2af83e2 f154ea9，2026-05-11 完成） |
| **B. creator 分布式 driver** | modules/creator_distributed（待启） | 1h | 视频墙开窗/切源/预案完整桥接 — **前提**：user 让出 :12121 session |
| **C. husion 辅模式 — 事件回传** | husion_distributed 扩展 | 1-2h | "AI 检测结果反馈给原厂家"完整闭环 — **前提**：user 确认 husion 那侧接收方式 |

#### 第二梯队（能力深化 · 单 sprint 半天到 2 天）

| Sprint | 子模块 | 工时 |
|---|---|---|
| D. 跨摄像头人员追踪 re-id | video_processor | 1-2 天 |
| E. VLM 视频帧描述 | video_processor + llm_engine | 1 天 |
| F. 检测事件持久化（SQLite / Parquet 时序） | 新 modules/storage 或 video_processor | 半天 |
| G. 多 LLM 路由（fast / smart / cloud 策略） | llm_engine | 半天 |
| H. 多说话人分离（cam++ / SOND） | audio_processor | 1 天 |

#### 第三梯队（战略 / 工程）

| Sprint | 工时 |
|---|---|
| I. 国产化预研（FunASR / YOLO / ollama 在 RK3588 / 信创 Linux） | 1-2 天 |
| J. start.command 鲁棒性 + 配置中心 web UI（catalog 在线编辑） | 半天 |
| K. Flask 启动失败异常传播（不再 swallow `Address In Use`） | 30 min |

---

### 推荐第一周节奏

**Day 1（明天）**
- 上午：**Sprint A** partial 逐词追加（半天，纯前端 + audio_processor 改动小）
- 下午：等 user 让出 creator session → **Sprint B** creator 分布式 driver（1h）
- 备：如 user 没让 session，做 **K** Flask 异常传播（30min 顺手）

**Day 2-3**
- **Sprint C** husion 辅模式（前提：user 确认接收接口；不行就先做 D）
- 整合演示 + 汇报

**Day 4-5**
- 进入第二梯队（D / E 二选一）

---

### 关键 trap / 防踩坑（沿自回合 1-29 的实战）

| 类别 | trap | 应对 |
|---|---|---|
| 协议 | creator PDF 写 HTTP :23282 是错的 / 旧版 | 先抓真实流量（TCP :12121 + 123456 是事实） |
| 网络 | husion .150.x 不可达；改 /16 子网会断网 | `sudo ifconfig en1 alias 192.168.150.250 netmask 255.255.255.0`（README 完整步骤） |
| 重启 | kill main.py 后立即重启会撞 :5050 TIME_WAIT | `until ! lsof -i :5050 -sTCP:LISTEN; do sleep 1; done` 后再启 |
| 代理 | requests 调 127.0.0.1 走系统代理（Clash 等）→ 404 | `requests.Session(); s.trust_env = False` |
| Node-RED | function 节点 setTimeout / context state 重启不 reset | 用 `flow.set/get` + `initialize` 字段；timer 在 `finalize` 清 |
| Git | iCloud 路径偶发 `.git/index.lock write timed out` | `rm .git/index.lock` 后重 add |
| supervisor | Flask daemon thread 内 swallow `Address In Use` 不传播 | Sprint K 待修；目前手动 grep log |
| Husion | TCP `hscmd-get-tx-*` idList=[] 返回空 | 必须传具体 idList（白鲨 RX 5001-6999） |
| Creator | admin 单 session 限制，多端 login 后续返 code=3 | 用同 token 串起来；或 让出旧 session |

---

### 历史下次优先项（保留参考）

#### 1. 转写体验对标讯飞（业务最高优 · 半天-1 天）

客户对标的核心是**视觉节奏**：partial 文字逐词跳出（不是整段闪现）+ 句末标点定稿瞬间气泡变色。需要做的小改进：

- **partial 重叠去重 + 平滑覆盖**：FunASR 2pass online paraformer 的 partial 经常前缀重叠（"我觉得" → "我觉得这" → "我觉得这个"），当前 transcript_seq.js 用同 seq_id 整体替换，体验是"一行字突然变长"——讯飞那种"逐词追加"的视觉感更舒服。需要做 diff-and-append 渲染（保留旧前缀字符位置，只 append 新增字符 + CSS 闪光）
- **final 覆盖动画**：从 live (橙色) 到 final (绿色 + 标点) 的过渡用 0.3s fade，强化"定稿"瞬间的客户感知
- **多说话人区分**（讯飞截图里有"说话人 1"标签）：FunASR 2pass 不带说话人分离（speaker diarization），需要单独接 SOND 或 cam++ 模型；**先列着，第二期再上**

定位：`modules/audio_processor/processor.py` `_emit_partial`/`_emit_final` + `web/static/renderers/transcript_seq.js`

#### 2. 转写卡 enable/disable 按钮（回合 26 答应过没做）

当前 audio_processor 跟随 main.py 拉起就一直跑。用户提议给一个开关（隐私/省电/调试）：
- `web/server.py` 加 POST `/audio/<action>` → MQTT `av/audio/cmd`
- audio_processor.main 订阅 cmd，按 action 调 processor.start/stop
- 前端转写卡 header 加按钮（仿视频墙模式）
- 默认 enable（用户说"系统负担不大可以直接启动"）

#### 3. start.command 鲁棒性（回合 25/26 累积的小坑）

- `trap cleanup EXIT` 解耦 Node-RED：方案 A/B/C 任选（详见回合 25 遗留小注）
- `web/server.py` 启动失败异常传播：daemon thread 不再 swallow `Address already in use`，让 supervisor abort 退出（避免"进程在跑但 web 没 listen"的暧昧状态）
- start.command 的 funasr 容器名校验放宽：发现旧容器名（`funasr-server` 等）+ 错误镜像版本时主动提示重建，不只检查 MODELSCOPE_DOMAIN

#### 4. 国产化路径预研（远期但战略 · 1-2 天）

业务定位明确后，技术底座要为 RK3588 / 国产服务器部署做准备：
- FunASR 在 RK3588 (ARM) 上的可用 runtime 调研：现 docker 镜像是 x86_64 + linux/arm64 双架构？要不要换 funasr CPU runtime 直接装？
- ModelScope SDK 在国产 Linux（统信 UOS / 麒麟）的兼容性
- YOLO ultralytics 替换为国产替代（PaddlePaddle / MMDetection）的探索

#### 5. 验证 client_id 唯一化（回合 24，附加）

```bash
grep "MQTT 断开" /tmp/main_av.log    # 期望 0 条
```

#### 6. 其它小优化（按需）

#### 3. GridStack / Muuri 实际拖动持久化（半天 · 远期）

定位：`modules/audio_processor/processor.py` `_emit_partial`/`_emit_final` 对 `web/static/renderers/transcript_seq.js` 的 seq_id 合并。FunASR 2pass partial 重叠去重 + final 覆盖逻辑可能漏前缀。

#### 6.1 GridStack / Muuri 实际拖动持久化（半天 · 远期）

回合 23 已把每个总览模块卡装上 `data-module-id` 和 `.drag-handle` 占位。下一步：
- 引入 `gridstack.js` 或 `muuri`（CDN 或本地 lib）
- 用 `data-module-id` 作 grid item key
- 拖动结束写 `localStorage.setItem('overview-layout', JSON.stringify(positions))`
- 启动时 restore 顺序

#### 5. 在线视频源补更多公共 m3u8（30 min · 按需）

`web/templates/dashboard.html` 的 `<select id="online-stream-select">` 加 option：
- CGTN 直播（国内可用）：需查最新 m3u8
- DW News / Euronews（World Monitor 用过的）
- 央视 CCTV-13 国际频道

记录：抖音 / 视频号 / 海上平台直播仍标暂缓（反爬严密，独立子项）。

#### 6. 视频墙画格 4 路自动占满（小优化）

当前 video_processor `config/system_config.yaml` 配 4 路源（本机/监控/分布式/财务监控），但只有"本机摄像头" 是 USB 真源。监控/分布式/财务都是占位。下次接手可：
- 把"分布式"改成 demo RTSP 公开源（如 `rtsp://demo:demo@ipvmdemo.dyndns.org:5541/onvif-media/media.amp`）
- 或允许在线视频源（HLS）也作为视频墙的一格

### 明日另起：多窗口协同试点（Mac Studio）

**目标**：在公司 Mac Studio 上把多窗口 Claude Code 协同工作流跑通，评估是否纳入日常节奏。**与上面 P1–P4 主线并行，不阻塞。**

#### 前置（一次性，30 分钟内）

```bash
# 1. 确认 iCloud Drive 已把仓库同步到 Mac Studio
ls -d "$HOME/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"

# 2. 进入仓库，确认无未提交的危险改动（其它窗口正在用，先 pull / status）
REPO="$HOME/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"
git -C "$REPO" status
git -C "$REPO" branch --show-current   # 应为 main

# 3. 在 iCloud 之外开 worktree 根目录（避免双重同步）
mkdir -p ~/dev
```

#### Step A — 用 git worktree 起两个并行工作目录

```bash
REPO="$HOME/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"

# worktree 1：试点子任务 A（建议挑独立模块，例如 network_scanner 或 system_info 调优）
git -C "$REPO" worktree add -b experiment/wt-a ~/dev/av_mvp.wt-a main

# worktree 2：试点子任务 B（另一独立模块，例如 video_processor 的 YOLO 修复）
git -C "$REPO" worktree add -b experiment/wt-b ~/dev/av_mvp.wt-b main

# 验证
git -C "$REPO" worktree list
```

#### Step B — 各开一个 Claude Code 窗口

- 窗口 1：`cd ~/dev/av_mvp.wt-a && claude`
- 窗口 2：`cd ~/dev/av_mvp.wt-b && claude`
- 主窗口（iCloud 原路径）继续做主线 P1（如 Node-RED hero / 落字修复）

**分工铁律**：每个窗口只动自己 worktree 下的文件；任务边界按 `modules/<name>/` 子目录切。需要跨模块协调的，回主窗口做。

#### Step C — 评估痛点，决定是否升级到 claude-squad

跑 1–2 小时，记录：
- 切窗口频率？是否难以追踪每个 agent 状态？
- iCloud 同步路径有无异常（`.git/worktrees/<name>/gitdir` 是否被 iCloud 锁过）？
- 两个 worktree 各自 commit 时是否出现 `index.lock` 冲突？

**若痛点明显**，再装：
```bash
# claude-squad（首选，自动 tmux + worktree）
brew install tmux
brew install smtg-ai/tap/claude-squad   # 若 tap 不存在则查 README

# 或 ccmanager
npm i -g @kbwo/ccmanager
```

**若不痛**，直接用 worktree + 多终端窗口的裸方案，不引依赖。

#### Step D — 验证完后清理

```bash
REPO="$HOME/Library/Mobile Documents/com~apple~CloudDocs/工作/Ai探索/b研发/av_unified_mvp"

# 把试点分支的有效改动 cherry-pick 回 main（如果有）
# git -C "$REPO" checkout main
# git -C "$REPO" cherry-pick <commit>

# 删 worktree + 临时分支
git -C "$REPO" worktree remove ~/dev/av_mvp.wt-a
git -C "$REPO" worktree remove ~/dev/av_mvp.wt-b
git -C "$REPO" branch -D experiment/wt-a experiment/wt-b
```

#### 成功标准

- 两个并行窗口分别完成一个非 trivial 子任务（不只是 README 改字）
- 没有触发 git index 死锁、iCloud 文件冲突、误改对方 worktree
- 能清晰回答："是否值得长期用？"

#### 失败兜底

- 若 iCloud 路径上 git worktree metadata 被 iCloud 锁（`.git/worktrees/*/locked` 异常），方案改为：把仓库**整体迁出 iCloud**到 `~/dev/av_unified_mvp/`，iCloud 只用于备份非工作副本。这是较大决策，本次不做，先观察。

### 启动顺序（已通过验证）

```bash
# 1. mosquitto（如未起）
mosquitto -c /opt/homebrew/etc/mosquitto/mosquitto.conf -d

# 2. funasr-2pass 容器（如未起）
docker start funasr-2pass

# 3. 主程（现为 supervisor，拉 3 个独立子进程）
cd /Users/yzj/Developer/av_unified_mvp
python3 main.py
# 浏览器: http://localhost:5050

# 4. 旁路观察 MQTT
mosquitto_sub -h 127.0.0.1 -t 'av/#' -v

# R2 验收：3 个子进程
pgrep -af "modules\\.(audio|video|llm)" | wc -l   # 应该 3

# R4 验收：MJPEG 启停
# UI 点"启用" → 画面出来；mosquitto_sub -t 'av/video/cmd/#' -v 看 enable 消息
```

### R5 端到端验收（代码已完成，等本机装 node-red）

```bash
npm i -g node-red          # 一次性
./start.command            # 自动起 mosquitto + Node-RED + main.py
# 浏览器 http://localhost:5050
# 顶部"编程 (Node-RED)" tab → iframe 加载 Node-RED 编辑器
# 在 Node-RED 拖 mqtt-in 监听 av/control 验证消息能收到
```

### R6 已完成的快速回顾

3 个新模块代码均位于 `modules/{system_info,network_info,network_scanner}/main.py`，结构与现有模块一致（继承 BaseModule，声明 streams，处理消息）。验证命令：

```bash
# 周期消息
mosquitto_sub -h 127.0.0.1 -t 'av/system/host_stats' -v
mosquitto_sub -h 127.0.0.1 -t 'av/system/network' -v

# LAN 扫描（小范围测）
mosquitto_pub -h 127.0.0.1 -t 'av/system/lan_scan/cmd' \
    -m '{"subnet":"192.168.5.0/28","ports":[80,5050],"timeout_ms":150}'
mosquitto_sub -h 127.0.0.1 -t 'av/system/lan_scan/+' -v
```

### 后续可选方向（R 计划之外）

- **YOLO 加载修复**：`modules/video_processor/processor.py` 的模型 None bug（不影响 MJPEG 流，但检测事件出不来）
- **FunASR docker 自动启动**：`docker start funasr-2pass` 写进 start.command（已写但需要 Docker 运行）
- **端到端语音→意图→控制 闭环测试**：用麦说"打开会议室空调"，验证 transcript→intent→control 全链路
- **R5 自定义 Node-RED flow**：现 `node-red/flows.json` 是回合 13 的 legacy；可改写成订阅 av/system/* 做日志/告警

### R2+R3+R4 已完成的关键变更

- `main.py`：纯 supervisor + discovery 订阅 + supervisor 宣告 + `set_mqtt_publisher` 注入
- `core/mqtt_bridge.py`：支持 MQTT 通配符（# 和 +）
- `web/server.py`：动态 channel（无白名单）+ `POST /camera/<name>/<action>`
- `web/static/renderers/`：3 个 renderer 文件（mjpeg 已实现）
- `web/static/dashboard.js`：discovery 驱动，动态面板 + 失活灰显 + endpoints 子容器
- `web/templates/dashboard.html`：auto-fit grid，删硬编码 panel
- `modules/video_processor/main.py`：内嵌 5051 端口 MJPEG 服务 + `av/video/cmd/+` 启停

---

## 远期方向 / 候选模块（候选池，不在当前主线）

### 网络可观测性子系统（2026-05-07 提出）

**业务定位**
AV / 控制类设备与客户办公网混合部署是高频痛点。客户报"卡了 / 掉了"时定位手段缺乏，讯飞类 AI 厂商不会做这块——这是 av_unified_mvp 在"AI 理解"之外的第二条差异化护城河，从"AV 集成商"升级到"AV 系统运维商"。

**故障根因（速查）**
1. AV 设备网络行为特殊：大量组播（mDNS / SSDP / IGMP / Dante / SDVoE，单路 6-10 Gbps）；时序敏感（PTP <1μs，抖动 <10ms）；持续高流量
2. 办公网"噪声"：DHCP 池小 / IP 抢占；办公交换机不开 IGMP snooping 导致组播全口洪泛（卡顿/花屏首发原因）；防火墙默认拦多播
3. 协议设计假设专网：无 QoS、无带宽控制；海康/大华 SDK 端口（8000 / 37777）权限模型粗

**集成层改良（推给客户的 IT）**
- 网络：VLAN 隔离（AV / 控制 / 摄像头 / 办公分开），L3 路由 + ACL
- 交换机：**IGMP Snooping + 每 VLAN 一个 querier**（治 90% 卡顿）、QoS DSCP、Storm Control、BPDU Guard
- 设备：静态 IP / DHCP MAC 绑定、关跨 VLAN 发现协议、改默认密码

**项目可落地（拉到 av_unified_mvp 里做）**
1. **持续探活模块** `modules/network_health/`：配置关键设备清单（IP + 角色），每 30s ping + 选配 SNMP 拉交换机端口流量/丢包/CRC；事件走 `av/network/health/<host>`；dashboard 出实时曲线 + 告警 badge
2. **告警关联**：摄像头 LWT offline 时联查"过去 5 分钟相邻交换机端口 link flap / 丢包暴增"，结论挂在事件上
3. **抓包模式**（远期）：边缘盒子按需启动 tcpdump 60s，自动分析组播洪泛 / mDNS 风暴

**前置 / 工作量**
- 现有 `modules/network_scanner` 已是 asyncio 并发扫描，可作 baseline
- SNMP：pysnmp（纯 python）或调外部 snmpget；优先 v2c。落地前要跟客户 IT 沟通开 SNMP
- MVP（ping 心跳 + dashboard 曲线）：1 天 ｜ + SNMP：1-2 天 ｜ + 告警关联：2-3 天 ｜ + 抓包：1 周

**优先级 P5（远期）**
当前主线 P0 第二阶段（creator/husion 分布式直连）和 L3 摄像头识别自动化更紧；本方向作为差异化护城河第二条，建议下一个版本评估，不抢当期工期。

---

## 进度日志

### 2026-05-07 演示前打磨（晚）

**推进**
- 演示前 UI 文案：顶部 logo →「Ai 视听信息理解 [CREATOR]」；Node-RED 卡副标题 →「av/* 编排」；编辑流程链接 → 图标 ↗；Node-RED 默认页 → 「AI 看板」；在线视频源候选改 3 个用户实测可播（Bitmovin Sintel / Red Bull TV / Apple BipBop）
- 视频墙 badge 误判修复：`video_processor.VideoModule._discovery_payload` 公告前同步 `processor.get_stream_status()` 到每个 endpoint 的 `status` 字段；`web/static/dashboard.js` 按 ok/connecting/error/disabled 5 态渲染。解决「摄像头 RTSP 连不上但显示在线」
- Node-RED 默认页排序改按 `page.order`（修 widgets-多者优先的旧逻辑），防止 1.x 「指挥中心控制端」(4 widgets) 挤掉 2.0 「AI 看板」(1 widget)
- GitHub 比对（flyfish17/av_unified_mvp）：那版没有"大按钮 / 触摸屏"代码（之前印象有误）；本地版相比已是单进程 → 订阅式 supervisor 架构跃迁，不需要回拉

**演示前必过 checklist（5/8 客户现场）**
1. 🔴 **Ollama 在演示机起着没**（家里实测 `Ollama服务不可用` → LLM 翻译降级到 catalog 关键词硬命中）：`curl -s http://127.0.0.1:11434/api/tags`
2. 🔴 **误识别 bug**：闲聊话被命中成 cmd（如"每次将网络挂上塑料管…" → `DiningTable_Light2_On`）。catalog 49 个关键词触发太宽。建议演示限定话术；如要根治需收紧关键词或卡 Ollama 必过
3. 🟡 **启动方式**：双击 `./start.command`（终端前台），不要 nohup 后台 — 今晚 mosquitto 中途死过一次原因不明（疑似 macOS sleep / nohup daemon 链路）
4. 🟡 视频源到公司网段后再逐个点确认；视频墙首次启动 30s 内 badge 显示"连接中"是正常窗口期（首条 discovery 公告时 RTSP 还在连）

**下次接手上下文**
- 工作目录：iCloud 路径；Developer 副本今晚已 rsync 同步（无 --delete，新增/覆盖；不删 Developer 旧多余文件）。两边主代码一致
- 后台已关：mosquitto / Node-RED / main.py 全家；funasr-2pass 容器 still up（`--restart unless-stopped`，无害）
- 客户现场资料：`obsidian/98-收件箱/沈飞谈判纲要_腾尔会务系统.md`
- 本次涉及文件：`modules/video_processor/main.py` `web/static/dashboard.js` `web/templates/dashboard.html` `node-red/flows.json`

### 2026-05-07 远期方向沉淀：网络可观测性

讨论 AV / 控制设备与客户办公网混合部署的常见故障：根因（组播洪泛 / 时序敏感 / 协议假设专网）、集成层改良（VLAN + IGMP Snooping + QoS）、项目可落地路径（network_health 模块 + LWT 关联 + 抓包模式）。详见同文件「## 远期方向 / 候选模块 → 网络可观测性子系统」一节。

附：今晚顺手扫到家里 192.168.3.2 / 3.3 / 3.32 三台都是海康设备（OUI `ec:97:e0`），仅 8000 SDK 开，RTSP 全关 → 可作"客户场景常见状态"参考样本。

### 2026-05-08 LLM 切 qwen3.5:4b：内存省 4.2 GB + 反 hallucinate 兜底

**触发**
家里 16G MacBook Pro 长期 swap 4 GB+，Activity Monitor 看到 ollama 单进程占 7.67 GB（qwen3.5:9b 模型 + KV cache 常驻）。结合"评估 8G/16G MacBook Air 与 RK3588 能否跑"的目标，先把 LLM 模型规模降下来才有得谈。

**测试方法（不重启 av）**
独立脚本 `/tmp/test_llm_models.py`：复用 `engine._build_command_prompt_from_catalog()` 真实 76 指令 prompt，8 个 case 覆盖（精准命中、笼统词、标点容错、闲聊陷阱"塑料管"、不存在地点"三楼厨房"），直接调 `127.0.0.1:11434/api/generate`，stream=true 拿 TTFT。

**三模型横评（qwen3.5:0.8b / qwen3.5:4b / gemma4:e4b）**

| 模型 | RAM | 加载 | TTFT | total | 正确率 |
|---|---|---|---|---|---|
| qwen3.5:0.8b | 2.14 GB | 2.9s | 929ms | 1260ms | 5/8（"打开"被错认成 TempUp、地点 hallucinate，演示翻车） |
| **qwen3.5:4b** | **3.50 GB** | 4.9s | **216ms** | **652ms** | **7/8**（唯一漏：三楼厨房 hallucinate） |
| gemma4:e4b | 10.52 GB | 9.8s | 404ms | 789ms | 8/8（但 RAM 比 9b 还大） |
| (qwen3.5:9b baseline) | 7.67 GB | — | — | — | 实测有"塑料管"误命中 |

颠覆预期：**gemma4:e4b 比 9b 更费内存**（10.52 vs 7.67 GB，因 Gemma 3n 完整权重 ~9.6 GB 全装入）。如目标省内存，e4b 是最差选择。

**4b 下载与 import（ollama hub 直拉 33 B/s 不可用）**
```bash
modelscope download --model Qwen/Qwen3-4B-GGUF \
    --include 'Qwen3-4B-Q4_K_M.gguf' \
    --local_dir ~/models/qwen3-4b-gguf      # ~28 MB/s，2.3 GB 86s 下完
echo 'FROM /Users/yzj/models/qwen3-4b-gguf/Qwen3-4B-Q4_K_M.gguf
PARAMETER stop "<|im_end|>"
PARAMETER stop "<|im_start|>"
PARAMETER stop "<|endoftext|>"' > /tmp/Modelfile_qwen3_4b
ollama create qwen3.5:4b -f /tmp/Modelfile_qwen3_4b
```
**两处必加 stop tokens 才能正常停**（modelscope GGUF metadata 不被 ollama 自动识别为 stop），否则模型出完 JSON 后会循环重复直到 num_predict 用完。

**4b 引入两个新坑（本次一并处理）**
1. **qwen3 默认 thinking mode**，`think:false` API 参数对自定义 import 的模型无效 → `engine._ask` 在 prompt 末尾追加 ` /no_think`（Qwen3 官方硬关开关）。配合现有 `re.sub(r"<think>.*?</think>", "", raw)` 剥离空 think 标签
2. **小模型 hallucinate 编造**：实测"打开三楼厨房空调"→ `3FDiningTable_AirConditioner_On`（catalog 里没有但格式贴切，creator 网关会丢但污染 dashboard）。双重防御：(a) catalog prompt 加规则 6"cmd 必须从字典精确逐字选取，禁止编造"；(b) `generate_command` 出口加 catalog 76 个 cmd id 白名单后置过滤，不在白名单 → null + warning 日志

**端到端验证（mosquitto_pub 注入 5 case）**
```
打开二楼餐桌空调          → av/control: 2FDiningTable_AirConditioner_On  ✓
关闭吧台灯带              → av/control: BarCounter_Light_Off            ✓
把会议室1的灯打开          → av/control: MeetingRoom1_Light_On           ✓
这个塑料管什么时候挂上去的 → 不发布（关键词前置 + 反 hallucinate prompt）  ✓
打开三楼厨房空调          → 不发布（白名单拒绝 + WARNING 日志）         ✓
```
"塑料管误命中" 顺手修了。端到端延迟 ~1s（含 MQTT + LLM + JSON 解析；纯 LLM 652ms）。

**收益对比 baseline 9b**

| 维度 | 切前 (9b) | 切后 (4b + /no_think + 白名单) |
|---|---|---|
| ollama RAM | 7.67 GB | 3.50 GB（**省 4.2 GB**） |
| 整机 av 全栈占用 | ~9.5 GB | ~5.3 GB |
| 端到端延迟 | ~1.5s | ~1s |
| 闲聊误命中 | 偶发 | 消除 |
| hallucinate 指令 | 可能发出 | 直接拒绝 |
| 16G MBA / RK3588 16G | 边缘 | 舒适 |
| 8G MBA / RK3588 8G | 不可行 | 边缘可行 |

**oMLX / Ollama MLX 方向调研结论（不切）**
- ollama 0.19+ 已集成 MLX 后端（Apple 官方框架），prefill 1.6×、decode 2× 提速，主支持 Qwen3.5 + Gemma 4
- **但 MLX 不解决内存压力**：同模型权重 → 同 RAM。本次省 4.2 GB 是换模型规模带来的，与后端无关
- oMLX（github.com/jundot/omlx）是独立 MLX 推理服务，OpenAI 兼容 API（不是 ollama 兼容），切换需改 `engine.py` 30-50 行 + 抽 backend 开关。当前没有切换驱动力，搁置

**下次接手上下文**
- `system_config.yaml` 在 .gitignore 内，**生产侧需手动改** `model_fast/model_smart` 到 `qwen3.5:4b`（example.yaml 已同步可参考）
- `qwen3.5:4b` 不是 ollama hub 同名拉取的，而是从 modelscope 下 `Qwen/Qwen3-4B-GGUF` 的 Q4_K_M + 本地 `ollama create` 而来的（直拉 ollama hub 33 B/s 实测不可用）。生产机部署时同样走 modelscope 路径，Modelfile 必须加 3 个 stop tokens
- 本次涉及文件：`modules/llm_engine/engine.py`（白名单 + /no_think + prompt 规则 6）、`config/system_config.example.yaml`（同步模型名）。`config/system_config.yaml` 本地已改但 .gitignore 不入库
- av 全栈仍在跑（mosquitto / Node-RED / main.py / funasr-2pass）；ollama 已加载 qwen3.5:4b（3.5 GB）

### 2026-05-11 双线推进 — Mac 假活 bug 修复 + Jetson Orin Nano 阶段 2 落地

**Mac 主线修复**（commit 5418467）

5/11 上午真销售来访 22min（导出到 `~/Downloads/summary-20260511-150528.md`，业务价值充分讨论）。15:04:25 user 按"停止"导出转写，15:05:05 重新启用，**之后 6.5min 一行 [final] 都没出**；15:11/15:52 又试两轮 disable/enable 仍 0 finals（127→0 落差铁证）。

根因：`modules/audio_processor/processor.py:130 stop()` 设 `_stop_event`，但 `start()` **不 clear** → 新 `_supervise_ws` / `_send_loop` / `_mic_watchdog` 三线程一启动就因 `while not _stop_event.is_set()` 立即退出，mic 跑着但 WS 没人接 = 完美"假活"。日志上 `录音流已启动` + `FunASR 2pass 客户端已启动` 两行 print 误导成功假象。

修法（`processor.py:104 start()` 入口加 13 行）：
- `_stop_event.clear()`
- drain `_send_q`（不 drain 重启第一帧取到 stop() 塞的 None 哨兵 → 给 funasr 发 `is_speaking:false` 视为流结束）
- 重置 `_pcm_frames_received` / `_mic_self_check_done` / `_last_partial`

验证：SIGTERM PID 4229 → supervisor 重拉 PID 5454 加载新代码 → 16:06:21 [final] 复活。

横向影响：`processor_arm.py` 已正确 clear（commit 0dd9b1a），不影响 ARM 路径。

**Jetson Orin Nano 阶段 2 落地**（commit 4b79332，硬件备选短名单 #1 平行验证）

辽河 3588 sprint 退出条件设计的"路径错就换硬件"原则下，Jetson Orin Nano（`jetson@192.168.5.51`，JetPack 6.1 / CUDA 12.6 / 7.4G RAM）作平行测试。

PoC 一路踩坑：
1. **CUDA 不可用**：旧用户级 `torch 2.11.0+cu130` 是 pip 直拉的通用 wheel（带 nvidia_cublas-13.1 等 CUDA 13 deps），driver 12.6 不向后兼容 CUDA 13 → 假装可用实际崩。
2. **NVIDIA JP6.1 wheel index 只有 torch 一个 wheel**，无 torchaudio/torchvision 预编译。
3. **PyPI torchaudio 全版本 ABI 不兼容** NVIDIA torch（`undefined symbol _ZNK5torch8autograd4Node4nameEv` — NVIDIA 用自定义 gcc/ABI 编译）。
4. 首轮源编 torchaudio v2.5.0 `BUILD_SOX=0 USE_FFMPEG=0` 卡在 CUDA CTC decoder `.cu` 缺 `<cfloat>` 头致 `FLT_MAX` 未定义（CUDA 12.6 + g++ 11 已知坑）。

修法：
- 卸装 user-level torch + nvidia/* 系列（释放 3G），自动激活 `/usr/local/lib/python3.10/dist-packages/torch 2.5.0a0+nv24.08`（系统 dist 已自带 NVIDIA wheel，user-level 错装的把它掩盖了）
- 源编 torchaudio v2.5.0 走 `USE_CUDA=0`（funasr 用 `torchaudio.compliance.kaldi` CPU 算 fbank，不需要 torchaudio 自带 CUDA 内核；模型推理本身仍走 GPU）— 装到 `~/.local/.../torchaudio-2.5.0a0-py3.10-linux-aarch64.egg`
- 源码 tarball 走 `gh-proxy.com` CN 代理拉 github

`processor_arm.py` 三处增量（commit 4b79332）：
- mic 识别加 `WebCamera` / `USB Audio` 名匹配（Jetson 接的是 Yahboom OEM 摄像头麦克风）
- 模型路径默认按主机自适应（3588 路径不存在 → `~/models/SenseVoiceSmall`）
- `AutoModel(device=cuda|cpu)` 自动 — `torch.cuda.is_available()` 真就走 GPU

实测：
- SenseVoiceSmall 加载 `device=cuda` **3.9s**（vs 3588 CPU 5-10s）
- mic 第 1 帧 PCM 正常，环境 rms base 0.0013-0.0020（比 3588 的 0.011-0.018 低一个数量级 — Yahboom mic 增益小）
- VAD 阈值 0.008（config 默认）暂时合理但靠 mic 远点说话可能触发不了
- MQTT discovery `running:true` 在 IP 192.168.5.51 心跳正常
- modelscope 下 SenseVoiceSmall 30s @ 33 MB/s

**两台 NPU 当前状态**

| 项 | 3588 (192.168.5.6) | Jetson (192.168.5.51) |
|---|---|---|
| 算力 | RK3588 8核 ARM + NPU（demo 没用） | Orin Nano CUDA 12.6 |
| RAM | 16G | 7.4G + 11G swap |
| Python torch stack | demo venv 自带（CPU 跑 SenseVoice） | torch 2.5+nv24.08 + 源编 torchaudio + funasr 1.3.1 全栈 GPU |
| SenseVoiceSmall 加载 | 5-10s CPU | **3.9s CUDA** |
| 推理 RTF | 0.8-1.9（接近 1） | 待测（GPU 应 <0.3） |
| 当前实例 PID | 60037（已跑 >2h） | 588595（新跑，CUDA 模式） |
| av_unified_mvp 仓库 | `~/av_unified_mvp/` ✅ | `~/av_unified_mvp/` ✅（Mac rsync） |

**未完成 / 下次切入点**

1. **用户对着 Jetson 麦克风说话** — 测 5-10 句 [final] 输出 + 实际 RTF + GPU 利用率（`tegrastats`）+ 与 3588 端到端对比
2. **三阈值正式验收**（plan 文件 §38-49）：延迟 p95 ≤ 1.5s / 字错率 vs Mac 增加 ≤ 15% / 30min 稳定性
3. **如果 Jetson 过阈值** → 选 Jetson 走阶段 3 差异化护城河（两级漏斗 LLM + av/control 桥接）；如果 3588 也勉强能过 → 二选一看综合性价比
4. **阶段 4 辽河方案落底文档**（条件触发，等阶段 2-3 出数据）

**下次接手所需上下文**

- SSH：`SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6`（3588） / `SSHPASS=yahboom sshpass -e ssh jetson@192.168.5.51`（Jetson）
- Jetson 当前 ASR log：`/tmp/asr_jetson.log`，监 `[final]`
- 3588 当前 ASR log：`/tmp/asr_arm.log`，PID 60037 已跑 >2h（rms+VAD+少量 final）
- Mac av 全栈在跑（新 audio_processor PID 5454 已加补丁）
- 完整 plan 文件：`~/.claude/plans/3588-demo-1-50-mac-3588-3588-2-3588-ai-streamed-riddle.md`
- Jetson 端 torchaudio 是 user-site `.egg`（不是 .whl），如要重装 `pip3 uninstall -y torchaudio` 不会清干净，需手动 rm `.egg` 文件 + 改 `easy-install.pth`

