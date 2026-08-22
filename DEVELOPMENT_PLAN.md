**战略定位**：公司 AI 技术底座。
> 模块解耦 + 订阅制架构，让每次开发成果累积而非推倒重来。
> 客户只需要转写，装一个模块。需要视觉识别，插入另一个。需要全套，全部开。
> **开发强度降下来，落地速度提上去。**
>
> 三个层次（架构视角 = 产品形态，开发与客户视角统一表达）：
> **A · 单机自洽** · **B · 多机协同** · **C · 跨品牌、跨系统桥接**

# av_unified_mvp 开发计划

> 历史回合见 `ARCHIVE_2026Q2.md` · 踩坑教训 `LESSONS_LEARNED.md` · **每次开工先读 `docs/DECISIONS.md`**（主 Claude↔终端决策同步点）· 两线对照 `docs/回流表-Mac线与3588线-20260821.md`
> 2026-08-22 整体梳理：5 月期的阶段二路线/看板/日志已归档，本文只保留当前有效内容。

---

## 0. 快速接手（5 分钟）

| 项 | 值 |
|---|---|
| **仓库** | 3588 线 = 本仓（**只有 main**，形态分支已退役为 `archive/*` tag）；Mac 线 = 独立仓 `flyfish17/av_understanding_mac`（两线对照见回流表） |
| **5.6 firefly** | **纪要产品机**（交总部测试）：`app_profile: meeting_asr` + `audio.source: net_multicast`（会议主机 8 路组播，话筒号分发言人），6 模块；`/home/firefly/av_unified_mvp`，systemd `av-demo`；刷版本 = `git archive main` rsync（不碰 config/node-red/data）+ SIGKILL 安全重启 |
| **62 proembed** | **研发机 + 湖森视听 demo**：`full` + C920 单麦 + 单路视频 + NPU YOLO + 声纹发言人 + `brand: Husion湖森`；13 模块；`scripts/deploy-62.sh` 一键刷 HEAD |
| **Mac Studio** | 研发/高算力；Mac 线演示跑 av_understanding_mac |
| **形态切换** | `scripts/switch-profile.sh meeting_asr|full|--status`（重启切；语音输入随形态 C920/组播） |
| **界面差异** | 全是开关/配置：☰ 导航、布局弹窗、视频墙单路/四分屏（与转写互斥）、声源下拉、`brand:`；**profile 只管起哪些模块** |
| **入口** | `http://<ip>:5050`；全屏转写 `/bigscreen`；留档 `/api/transcript/today` |
| **下一步** | §7 当前看板（阶段三 跨系统信息共享 ①-⑥ + 遗留） |

**接手三步**：读 `docs/DECISIONS.md` → 本文 §7 → `LESSONS_LEARNED.md`。

---

## 1. 战略层次（架构 = 产品形态，一一对应）

开发节奏 **A → B → C 由简入繁**；客户验收按形态评级。同一份代码，三层兼容。

| 层次 | 架构（开发视角）| 产品形态（客户视角）| 当前完成度 |
|---|---|---|---|
| **A** · 单机自洽 | mqtt + 全模块同机 | 纯转写 + 语意执行（**辽河主线**）| 阶段一 ✅ Mac 验证；阶段二 🔵 3588 精进 |
| **B** · 多机协同 | broker + client 跨机订阅 | 视频分析输出（分布式监控盒）| 雏形：Mac mini escalate 兜底 ✅；多机分布 ⏸ |
| **C** · 跨品牌桥接 | adapter 层接厂商 SDK / REST | 利旧 + 运维（大客户整体交付）| husion 5 场景 ✅；其它 ⏸ |

**护城河**：A=端侧延迟 + 准确率 / B=分布式差异点 / C=模块化 + 协议契约 + 跨品牌发现

---

## 2. 硬件矩阵（8/22 修订）

| 硬件 | 定位 | 状态 |
|---|---|---|
| **RK3588 `.6`** | 纪要产品机（CR-DIG7201-A），总部测试 | ✅ meeting_asr 常驻；等正确会议主机后真机组播验收 |
| **RK3588 EVB `.62`（湖森 DNC）** | 研发机 + 湖森视听 demo | ✅ full，新功能在此验 |
| **Mac Studio M3U** | 高算力/研发；可作纪要外放目标（`llm.summary.url` 热读） | ✅ |
| **MacBook Pro M1Pro** | 轻量短会/验证 | — |
| **Jetson `.51`** | 独立支线（视频深思），主线不投 | ⏸ |
| **246 Debian + Home Assistant** | 绿米 Aqara 家居网关（李楠接通），待上总线 | ⏳ 本线 ① |
| **109/3576 creator_cc** | 中控替代盒（另仓）；空调 Modbus 双向、继电器查询帧已实测 | 供本线 ③ 回读 |

**约束**：3588 NPU IOVA ~4GB（多 LLM 只能外放/串行）；full 形态多路视频与纪要互斥（单路可并行，62 实测 video_processor 48.7% CPU）。同一份代码跑所有机，差异全在 config。

---

## 3. 阶段框架

### 3.1 阶段一 ✅ Mac 验证解耦订阅制（tag `v1.0-stage1-mac-validated`）
### 3.2 阶段二 ✅ 3588 主线落地（5/18–8/21）
已落地：FunASR 2pass 实时转写（3588 docker / 62 脱 docker rootfs）· 纪要分段合并（ollama / rkllm NPU 1.7B，2 万字 8.9min）· 发言人两路（会议主机话筒号 / CAM++ 声纹，前端同构、可改名）· 全音频落盘导出 · 人名热词 + 缩写还原 · 转写 JSONL 留档 · ws 断联自愈 · `app_profile` + 一键切换 · 视频墙单路/四分屏互斥 · YOLO NPU（DFL fp16 溢出已修）· HDMI 开机信息屏 · 品牌配置化 · 门禁联动。5/18 的"新中间路径"规划已被实际落地取代，原文归档。
### 3.3 阶段三 🔵 当前：跨模块 / 跨系统信息共享（8/22 立）
把总线上已有的数据互相喂、把孤岛（Node-RED 真状态、246 HA）接上总线。核实与接法见 `docs/探讨-跨模块跨系统信息共享-20260822.md`，看板见 §7。
### 3.4 只储备不实施
双工对讲 · 知识库问答（另立项目）· 实时翻译（等涉外客户）· `video_analysis` profile（等样机，先验算力）。

---

## 4. 目标架构（六层）

```
1. 感知层 Capture     RTSP/USB 摄像头 | 麦克风
2. 理解层 Understand   audio_processor / video_processor / llm_engine / keyframe_filter / openvocab_filter / scene_analyzer
3. 总线层 Bus         mosquitto :1883 (3588)
4. 编排层 Orchestrate Node-RED :1880 (用户拖拽规则)
5. 展示层 Present     Flask + 原生 JS / SSE / summaries/ 纪要存档
6. 执行层 Act         control_dispatcher / husion adapter / web_browser (POC)
```

**设计原则**：
- 模块独立：`modules/<x>/main.py` 可独立 `python -m` 启动，仅依赖 MQTT
- 协议先行：MQTT topic schema 是合同，跨模块只看 schema，**不要 import 另一模块内部实现**
- 前端只订阅：浏览器端不直接 connect ASR/YOLO，只走 SSE/HTTP

---

## 5. MQTT topic 协议

### 数据流

| topic | 谁发 | 谁订 | 关键字段 |
|---|---|---|---|
| `av/audio/partial` | audio_processor | web/Node-RED | `text, seq_id, is_final=false, raw_mode` |
| `av/audio/command` | audio_processor | llm_engine/web/Node-RED | `text, seq_id, is_final=true` |
| `av/video/detect` | video_processor | keyframe_filter/web/Node-RED | `camera, time, detections[]`（**含空 detect 心跳** by `idle_detect_interval_s`）|
| `av/video/key_event` | keyframe_filter | scene_analyzer/openvocab_filter | `camera, reason, ...` |
| `av/video/scene_analysis` | scene_analyzer (Jetson) | dashboard | VLM 场景描述 |
| `av/video/openvocab` | openvocab_filter | dashboard | `hits[{class, conf}]` |
| `av/llm/event` | llm_engine | Node-RED/web | `event_type, original_text, intent, command` |
| `av/llm/escalate` | 3588 llm_engine | 外放机 | escalate 兜底（雏形）|
| `av/control` | Node-RED/llm_engine/web 按钮 | control_dispatcher / Node-RED `av/control (P0)` mqtt-in | `target, action, params` |
| `av/control/dispatched` | control_dispatcher | web | 执行结果回传 |
| `av/audio/command_punctuated` | audio_processor(2pass) / net_audio_capture / punctuator | supervisor→SSE transcript、留档 | `text, seq_id, ts, segment_id`；组播路径另有 `mic_id/physical_id/speaker` |
| `av/audio/segment` | audio_processor（`speaker_diarizer.enabled`）| speaker_diarizer | `segment_id, audio_uri(file://), start_ms, end_ms` |
| `av/audio/diarization` | speaker_diarizer | supervisor→SSE diarization、留档 update | `segment_id, speaker_id(S<n>), confidence` |
| `av/audio/cmd` / `av/audio/net_cmd` | dashboard | audio_processor / net_audio_capture | `action: enable/disable`（声源切换）；net_cmd 另有 `cmd: set_mic_names` |
| `av/video/cmd/<名>` | dashboard `/camera/<名>/enable|disable` | video_processor | 单路启停 |
| `av/door/visitor` / `av/door/result` | door_access | web | 访客弹窗 / 开门结果 |
| `creator/telemetry/<deviceId>/<prop>` | **creator_om** collectors（同一 broker） | alerting；本线 ② Node-RED | `header{source}, value, status, ts` |
| （规划）`creator/state/<device>` | 本线 ③ state_poller | Node-RED 面板 / 语音 / 告警 | 真状态回读 |
| （规划）`homeassistant/<domain>/<entity>/state` | 246 HA MQTT Statestream | 三方 | 本线 ① |
| （规划）`av/audio/visual_speaker` | av_speaker_locator（Light-ASD） | 前端与声纹合并 | 本线 ⑥ |

### 公告 / 系统

| topic | 协议 |
|---|---|
| `av/system/discovery/<module>` | retain=true，QoS=1，配 LWT。30s 心跳，崩溃 LWT offline |
| `av/system/host_stats` | CPU/内存/磁盘，每 5s（system_info）|
| `av/system/network` | 网卡/IP/收发速率，每 10s（network_info）|
| `av/system/lan_scan/{cmd,progress,result}` | UI ↔ network_scanner |

**变更协议时必须同步更新本节、`config/system_config.yaml` 的 `topics:` 与 Node-RED flows。**

---

## 6. 语音链路能力现状（8/22）

| 能力 | 3588 线 | 备注 |
|---|---|---|
| 实时转写（partial + final，带标点）| ✅ FunASR 2pass ws | 单麦 / 8 路组播两路 |
| 发言人 · 话筒号 | ✅ physical_id + 命名表 + 就地改名 | 会议主机形态 |
| 发言人 · 声纹 | ✅ CAM++ 逐句嵌入 + 在线聚类，晚到切段，可改名 | 单麦形态；**C920 近讲两人实测待做** |
| 人名/术语热词、缩写还原 | ✅ `config/glossary.yaml` / `asr_postprocess_rules.yaml` | 两路共用 |
| 纪要 | ✅ 分段→合并，ollama / rkllm NPU | 外放：rkllm url 热读；ollama url 硬编码（遗留①）|
| 留档 | ✅ `data/transcripts/<日期>.jsonl` + `/api/transcript/today` | alias 同文件 |
| 原音导出 | ✅ `:5052`（mic / 组播 recorder）| |
| 视频辅助发言人 | ⏳ 本线 ⑥ | |

---

## 7. 当前看板（7.22 · 阶段三 跨系统信息共享）

> 每项做完在本表打勾并在 §9 记一条；阶段汇报按 ①②③ / ④⑤ / ⑥ 三批，不阻塞。

| # | 任务 | 前置 / 边界 | 量 | 状态 |
|---|---|---|---|---|
| ① | **246 HA 上总线**：HA MQTT Statestream → 我方 broker；反向 HA REST 控制节点 | 需 246 HA 登录（李楠）；**62 broker 现只监听回环**，开网段监听需你执行（命令见 §9 8/22）| 1.5h | ⏳ 两个外部前置：HA 登录 + broker 开监听 |
| ② | **面板在线/离线** | 事实源改为 `creator/device/discovery/+`（retain，含 ip/online）；面板设备无独立 IP，粒度=主机 .20 / PDU .21 | 半天 | ✅ 8/22 |
| ③ | **真状态回读** `modules/device_state`：空调 Modbus 03 只读 → `av/device/state/<key>` retain；面板 ac 行按真状态亮/显温度模式，读不到显"状态未知" | 代码+协议单测+面板联动 ✅；**真机待 211 网关恢复可达**（8/22 62/Mac 均 ping 不通）；继电器查询帧待抓样本 | 1–2 天 | 🟡 8/22 软件侧完成，等 211 |
| ④ | **OBS 字幕路**：`/bigscreen?overlay=1` + OBS 浏览器源 → HDMI 进分布式 TX | 随演示环境 P0 上屏 | 1 天 | ⏳ |
| ⑤ | **湖森 `/api/wall/subtitle` 抓样本** → 通则 husion_distributed 加辅模式 | 62 现场抓包 | 1 天 | ⏳ |
| ⑥ | **Light-ASD POC**：62 跑 demo 验帧率 → yolov8n-face rknn → `av/audio/visual_speaker` → 前端与声纹合并 | 等会议室机位；先验算力 | 2–3 天 | ⏳ |
| 可选 | DeepFilterNet 降噪 A/B（C920 远场） | 62 录音 | 半天 | ⏳ |

**遗留（不在本线，顺手清）**：① `web/server.py` ollama url 读 config ② detect 心跳洪泛/零目标排查 ③ P2.1b 捕获侧减压 ④ 5.6 若切 full：lite2 + rknn 模型 + meeting_camera + CAM++ 模型 ⑤ C920 两人声纹实测 ⑥ .62 启动脚本"等 426"兜底可简化 ⑦ Node-RED 面板标题"CREATOR · 演示中控"写死在 flows，不受 `brand:` 管。

---

## 8. 工程纪律

### 8.1 大阶段启动 gating
- 大阶段切换 / 必备能力立项前 **必须**先做 GitHub 同类项目调研
- 报告 ≤ 1 天工时，保存 `docs/research/<topic>-<YYYYMMDD>.md`
- 没调研报告 → 不立项（防 5/14 YOLO26n 教训）

### 8.2 阶段固化原则
- tag 后 main / sprint 继续推进不影响 tag
- 销售可固定拉 tag 不被新 commit 影响
- 阶段间 tag 命名：`vX.Y-stageN-<one-word>`

### 8.3 实测优先于宣传
- landscape 调研要 reality check（5/14 YOLO26n 实测慢 5%，跟宣传 +43% 相反）
- 协议文档不可全信（厂家 PDF 错例多次），先抓真实流量

### 8.4 红线（不可越）
- 不动 `/home/firefly/creator_ai_demo/venv`（5.7G 共享 venv）
- 不 force push；**只有 main 一个分支**，差异全在 config，不再开形态分支
- 3588 生产机动形态选窗口；5.6 重启走 SIGKILL 手法保 funasr
- 不 SSH Jetson（无密码 + 红线）
- 不动 `:11434` Jetson ollama
- `:1880` Node-RED 改 flows 先 cp 备份，走 admin API 热部署，改完快照回仓 `node-red/flows.json`
- 产品化 = 加 profile/config，不复制代码；品牌 = `brand:` 配置 + 素材
- 两仓互改后在对方仓 DEVELOPMENT_PLAN 记一行「待回流」（回流表纪律）
- 不为子模块完美阻塞整体框架可运行性
- destructive 命令前先确认；不"防御性编程"吞错

---

## 9. 进度日志（8 月起；更早见 `ARCHIVE_2026Q2.md`）

### 2026-08-22 — 阶段三立项 + 开发文件梳理 + ② 面板在线态
- **开发文件整体梳理**：5 月期 §3.2 路线/§6/§7 看板/5 月日志归档到 `ARCHIVE_2026Q2.md`；§0/§2/§3/§6 按现状重写；§5 topic 表补全（segment/diarization/cmd/creator 遥测/规划 topic）；§7 换成阶段三看板。
- **阶段三核实文档** `docs/探讨-跨模块跨系统信息共享-20260822.md`：246 = Debian + Home Assistant（:8123，李楠经 HA 接绿米）；62/5.6 broker 上 `creator/telemetry/*` 已与 `av/*` 同总线；空调 Modbus 03 查询帧、继电器 CR-POWER8-SPM 查询帧均已在 creator_cc 实测；Light-ASD（1.0M 参数）为视频辅助发言人候选。
- **① 前置核实**：62 mosquitto 2.0.11 只监听 127.0.0.1（无 conf.d 规则）。HA 要发进来需 `/etc/mosquitto/conf.d/lan.conf`：`listener 1883 0.0.0.0` + `allow_anonymous true`（内网演示；回滚=删文件重启 mosquitto），模块有自动重连、重启 broker 无需重启 av-demo。**开匿名网段监听被权限分类器拦，留用户执行**。
- **③ 真状态回读（软件侧完成，等真机）**：新模块 `modules/device_state/`（`modbus_ac.py` 纯协议：CRC16/查询帧/回包解析，只含功能码 03 读；`main.py` 10s 串行轮询 4 台 → `av/device/state/<key>` retain，读失败也发 `ok:false`）。`tests/test_modbus_ac.py` 8 过：**查询帧与 creator_cc 8/18 现场实测帧逐字节一致**（CRC 实现对上实物），假网关端到端。supervisor 按 `device_state.enabled` 拉起，expected_modules 两脚本同步。Node-RED：mqtt-in `av/device/state/+` → function（解 BaseModule 双层信封）→ 面板 `real{}`：ac 行按真状态亮、旁标 `21℃ · 制冷`，读不到显"状态未知"、真状态行 ico 加绿环。62 验证：module 对 211 轮询 → 4 台 `ok:false` → 面板四台"状态未知"；mosquitto_pub 模拟一条好状态 → "21℃ · 制冷"+亮（已清）。**211（USR-TCP232 空调网关）今日 62/Mac 均 ping 不通（8/18 通），真机验证等它回来**；继电器 CR-POWER8-SPM 查询帧待抓样本后加到同模块。62 现 14 模块含 device_state 常驻（轮询失败只记一次变化，不刷日志）。
- **② 面板在线/离线（62 Node-RED）**：校正事实——面板灯/窗帘/空调全部经 `fire('m')` 发给中控主机 .20，单灯无 IP，"在线"粒度只能到主机 .20 与 PDU .21。实现：mqtt-in `creator/device/discovery/+`（ping_collector retain 公告，含 ip/online）→ function 汇 `{online:{ip:bool}}` → 喂 `中控面板` ui-template（`watch: msg`）。头部"主机 .20 在线/离线"标、主机离线整面板锁定+横幅、PDU .21 离线 LED 行灰。Playwright 模拟 retain 翻转验证：锁定/PDU 灰/恢复解锁全对；flows 快照回仓。单灯真状态留给 ③。
### 2026-08-18 — 门禁联动模块 door_access 落地（公司大门云眸远程开门）
- **本次推进**：新增 `modules/door_access/`（云眸 token 缓存刷新 + 远程开门 + 门口 person 检测去抖 → av/door/visitor）；supervisor 按 `door_access.enabled` 条件拉起并桥接 door SSE channel；dashboard 右上角访客弹窗（开门按钮 + 结果状态行）；配置样例入 example yaml
- **前置验证**（当日实测）：云眸 4 接口全链路通（token 7 天 / 事件查询 / 远程开门真开门，事件码 5/75 人脸过、5/21 开、5/22 关、3/1024 远程开、3/1029 心跳）；设备 E51574183 已绑 flyfish 账号；内网 ISAPI 备选路线卡在 isActivated=false + 无 admin 密码（192.168.2.88，DHCP 需改静态）
- **踩坑已修**：模块内 token 稳定 401 根因 = 子类 `self.client_id` 被 BaseModule.__init__ 覆盖成 MQTT client_id（属性名撞车，base_module.py:64）——改名 hik_client_id 后 token 预热 604795s 通过。**BaseModule 子类禁用 client_id/broker/port 等基类字段名**
- **未完成项**：① 门口摄像头尚未接入（camera_name=门口 待配真实源）；② 开门按钮无操作权限控制（内网任何人可开大门，上线前必须加）；③ 云眸消息通道 open_event_access 可替代轮询（注意 7 天不用自动停用）
- **下次接手所需上下文**：账号/秘钥/设备/事件码见 memory `door-access-hik-cloud`；测试配置样例 `config/system_config.example.yaml` door_access 段；协议原文 iCloud `设备协议/门禁开门协议.docx`

### 2026-08-21 — 纪要机 HDMI 开机信息屏（总部测试/演示环境 P0）
- **本次推进**：从 creator_om `deploy/hdmi-info/` 移植到本仓 `deploy/hdmi-info/`（`creator-asr-hdmi-info.sh` + `.desktop` + README），commit `95c8959`。文案改"CREATOR 转写纪要机 · 开机信息"；每个网口标注 DHCP/静态（nmcli ipv4.method）；服务判定三态（:5050 回 200=运行中 / 仅 av-demo active=启动中 / 未运行）；过滤 can0。**已装 5.6**（`/usr/local/bin` + `/etc/xdg/autostart`，autologin firefly 开机自动全屏），当前 HDMI-1 1080p 已在显示
- **验证**：5.6 实跑帧输出正确（eth1 192.168.5.6 DHCP 自动获取 / eth0 静态 .245 插线即活 / 网关 .1 / 运行中 http://192.168.5.6:5050）；未截屏（板上无 scrot/xwd），字号 `-fs 26` 需人眼目检
- **未完成项**：未并入 DECISIONS 第 9 条（布局弹窗灰置 + 客户视图按钮隐藏）的部署窗口——那两处前端小改仍待做
- **下次接手所需上下文**：5.6 安全重启手法见 memory `cr-dig7201-3588-meeting-asr`；信息屏立即重开命令见 `deploy/hdmi-info/README.md`

### 2026-08-21（下午）— 形态切换脚本 + YOLO 搬 NPU（62 实测）
- **背景判断**（用户探讨后定）：一台 3588 全功能、按重启切 meeting_asr/full 形态——机制早已具备，缺一条命令；两形态在 3588 上**互斥**（YOLO 占 CPU / NPU IOVA 4G），不做热切、不给前端按钮（防客户误切）。纪要外放：rkllm backend `llm.summary.url` 可配且热读（指向另一台 3588 NPU 零代码）；ollama 路径 `web/server.py:556` 硬编码 127.0.0.1，要外放 Mac Studio 需改读 config（未做）。外部进展：rkllm 1.3.0 支持 Qwen3.5（0.8B/2B/4B），IOVA 4G 无解（IOMMU v1 GFP_DMA32）。
- **切换脚本**：`scripts/switch-profile.sh full|meeting_asr|--status`（commit 3a9699f）。SIGKILL 老 supervisor/模块/rkllm daemon → `systemctl restart av-demo` → 等 :5050 200 + 模块数。`3588-demo-start.sh` EXPECTED_MODULES 改为按 config 推导（meeting_asr+net_multicast=6 / full=10）。5.6 上 `--status` 已验证；**full↔meeting_asr 实切未跑**（远程重启被权限拦，留用户执行）。
- **YOLO 搬 NPU（62）**：62 板上独立 venv 装 rknn-toolkit2 2.3.2（aarch64 wheel 可得；onnxoptimizer 无 wheel、源码编译失败，`--no-deps` 跳过不影响导出）→ `YOLO("yolov8n.pt").export(format="rknn", name="rk3588")` 32s 出 `yolov8n_rknn_model/`（7.9MB fp16）。**代码零改动**：`processor.py:103` `YOLO(path)` 走 ultralytics AutoBackend 识别 rknn 目录，运行时只需生产 venv 装 `rknn-toolkit-lite2==2.3.2`（ultralytics AutoUpdate 自动装了，已记入 requirements 注释）。
- **实测数字（62，1280×720，50 帧均值）**：CPU .pt 1167ms/帧·进程 CPU 246% → NPU **106ms/帧·112%**，检出 6 目标/类别一致；NPU Core0 33%。**但 video_processor 整进程稳态 441% → ~370%**，剩余大头 = 5 路 RTSP 软解 + 捕获线程逐帧 JPEG 预编码（`processor.py:53`），不是推理 → 立 P2.1b。
- **⚠️ 实况验证失败（13:10 发现，已回退）**：rknn 模型常驻 80 分钟内 781 次 `推理异常: cannot convert float NaN to integer`（本机摄像头 505 / 财务监控 194 / 分布式 73），**零有效检出**；bus.jpg 基准正常说明运行时链路通，问题在真实帧上 fp16 输出 NaN（疑点：USB 摄像头/RTSP 帧尺寸与 640 letterbox、fp16 溢出；下一步试 `int8=True` 量化导出 + 用真实帧做校准集、或固定 imgsz 预处理后再喂）。62 已回退 `yolov8n.pt`，异常归零。
- **数字更正**：前面"441%→370%"是 `ps` 生命周期均值，不是瞬时值；回退 .pt 后 `top` 瞬时同样 ~610%，**整进程 CPU 在 .pt/rknn 间无可比数据**。可靠的只有隔离基准（106 vs 1167 ms/帧）。模型入库 `yolov8n_rknn_model/` 保留作 POC 产物，**未过验收，别部署到 5.6**。
- **切换脚本补丁（用户实切暴露）**：切 full 后 `audio.source` 仍是 `net_multicast` → supervisor 去掉 audio_processor，全功能演示没有 C920 拾音。修：语音输入跟形态走（full=mic / meeting_asr=net_multicast），形态相同但 source 不符也执行，`--status` 显示语音输入与 USB 麦（commit b346df5）。**用户 8/21 在 5.6 实切验证完成**。
- **NaN 根因与修复（14:00-15:00，半天量内）**：离线用真实 RTSP 帧复现——推理不崩但原始输出 box 宽高通道含 **inf**（fp16 上限 65504，已见 45600），cls 通道干净 → 定位到 DFL 头 softmax 在 RKNN fp16 上不减 max、背景 anchor 的 exp 溢出 → NMS 出 NaN → `plot()` 崩。**修**：导出时 monkey-patch `DFL.forward` 在 softmax 前减每组 max（数学等价）+ `opset=17`（torch 2.2 ReduceMax 兼容）→ `scripts/export_yolo_rknn.py`。验证：3 张真实帧 inf=0、与 .pt 检出/类别一致；RTSP 300 帧 plot 零异常；同过滤条件（conf 0.5，person/phone/laptop）80 帧 .pt 与 rknn 各命中 40 person 完全一致；**62 实况 15min 零异常，NPU Core0 30%**。62 现常驻 rknn 模型，新模型 md5 e99a493f… 已入库覆盖。
- **int8 路线否决**：32 张现场帧校准量化后 inf 消失但零检出——box(0-640)/分数(0-1) 同张量 8-bit 把分数压 0；要走 int8 得拆头（rknn_model_zoo 做法），收益不值，记 README 不再试。
- **顺带发现（待查，与本次无关）**：生产日志全天 `[detect]` 全是 `(0 目标)`（.pt 与 rknn 相同），且 .pt 时段 75min 刷 26987 条心跳——`idle_detect_interval_s` 15s 节流疑似失效 + conf 0.5 下门口/财务几路是否真无人，下次看。
- **视频墙单路/四分屏互斥（15:00，用户拍板"默认一路，四屏与转写互斥"）**：纯前端 + config，后端零逻辑改动（复用 `/camera/<名>/enable|disable` 与 `av/audio/cmd`）。默认 `single`：只开 `video.meeting_camera`（缺省第一路），其余路 disable、画格收成 1 格（CSS `.video-wall.single`）；视频卡头部"⊞ 四分屏"按钮 → 转写在跑则确认框"将停止转写"→ audio disable → 前 4 路 enable；转写"启动"在四分屏下 → 确认框"切回单路"→ 先收单路再 audio enable。刷新回 single（不持久化，多路=显式动作）。会议摄像头名由 `web/server.py` 注入 `<body data-meeting-camera>`。
- **校验（Playwright 对 62 真机三步）**：初始 single/仅画格 1=本机摄像头；点四分屏 → 弹确认 → 请求序列 `av/audio/cmd disable` + 3 路 enable，按钮变"▭ 单路"；点转写启动 → 弹确认 → 3 路 disable + `audio enable`，回 single。in-flight 5s 去重后无重复请求。**负载：单路下 video_processor 48.7% CPU、整机 90% idle（5 路时 ~530-610%）**——"一路辅助转写 + 纪要并行"在一台 3588 上成立。
- **发言人区分（声纹）回流 + 声源选择 + 侧栏开关（16:00-16:15）**：
  - 背景：单麦发言人区分早在 `av_understanding_mac` 7/29-7/30 S1-S6 完成（CAM++ 逐句嵌入+在线聚类），但 **Mac Studio 本地 checkout 落后 GitHub 20 commit、且从未回流本仓**。今日 ff 本地并手工移植（两仓 processor.py 分叉 260 行，不能 cherry-pick）。
  - 移植内容：`modules/speaker_diarizer/`（原样）+ `modules/audio_processor/segments.py`（原样）+ processor.py 段 PCM 缓冲/`TranscriptEvent` 加 segment_id 等默认字段 + audio_processor main 接 SegmentSink（`speaker_diarizer.enabled` 才起）+ supervisor 按 config 拉起模块、订 `av/audio/diarization` 推 SSE + 前端 `applyDiarization`：final span 带 `data-segment-id`，结果晚到按 segment_id 回填；段无人→打标，段属别人→**从该 span 起切新段**、本地麦段指针跟过去，与话筒号分段同构（`.tx-spk` + `para.dataset.speaker`），纪要归属零改动。config example 加 `speaker_diarizer` 段。
  - 声源选择：`audio.active_source: mic|net_multicast`（两路同配时开机只一路转写），`net_audio_capture` 补 `av/audio/net_cmd {action: enable|disable}` + `running` 公告；转写卡 `<select data-tx-source>` 两模块都在线才显示，选谁 enable 谁 disable 另一个；停止按钮/四分屏停转写按当前声源发命令。
  - 侧栏：`body[data-app-profile=meeting_asr]` CSS 改为 `body.nav-hidden` 开关，顶栏"☰ 导航"，meeting_asr 默认收起、full 默认展开、localStorage 记忆。**至此界面差异全是开关，profile 只管起哪些模块。**
  - **62 验证**：venv 补装 funasr 1.3.1、CAM++ 模型（28MB）从 Mac 下载拷入；13 模块上线，CAM++ 就绪 8s。注入 8/20 会议录音 14 段（/mock/transcript + av/audio/segment）→ diarizer → SSE → 前端段标 S1，链路全通；mock S1/S2 晚到事件验证切段正确（S1 段句1-3 / S2 段句4-7，后到句接 S2）。☰ 开关正常；声源下拉在 62 单声源下正确隐藏。
  - **诚实边界**：① 14 段全归 S1——该录音是 8 路混音+远场，两两余弦全 ≥0.53，**不能判定分离好坏**；Mac 标定（异人 ≤0.28）是近讲样本，C920 近讲两人实测待做；② `net_audio_capture` enable/disable 代码走读、未实机（5.6 是总部测试机）；③ 声纹发言人（S1/S2）暂不支持点标签改名（话筒号路径支持），Mac S6 的改名广播未移植。
- **纪要线剩余 3 项回流（16:20-16:35）**：① 人名修复——Mac 8a3f6f6 的纯函数抽到 `core/asr_glossary.py`（core 共享层，audio_processor 与 net_audio_capture 8 路都用），`config/glossary.yaml`（人名/产品/术语→FunASR hotwords，json dict 协议）+ `config/asr_postprocess_rules.yaml`（final 英文缩写还原），单测移植 `tests/test_asr_glossary.py` 23 过（Mac、62 两地）；② 转写留档——`core/transcript_store.py` 原样 + 3588 补 mic_id/physical_id 字段，supervisor `_on_audio_command` append_text / `_on_audio_diarization` append_update（segment_id→id 映射），`GET /api/transcript/today[?format=txt]`；③ ws 自愈——`ws_giveup_after_s` 默认 120s 按断联时长放弃，替代 5 次≈30s。62 验证：启动日志 9 热词/8 规则；MQTT 注入 final+diarization → jsonl 两行 → API txt 输出 `S2：…`。**回流表纪要项全部 ✅，两线纪要软件能力对齐。**
- **5.6 刷 HEAD（22:04，用户拍板）**：热词表先按总部测试场景定（余绍峰/郭敏/李玉琪 + 产品型号，9bd5bdc）；备份 `~/av_unified_mvp.bak-20260821-2204`（代码目录）→ `git archive HEAD` rsync（排除 node-red/data/logs/summaries/system_config.yaml）→ md5 三对 → SIGKILL 安全重启。刷后：meeting_asr 6/6、funasr running、8 路组播启动、**18 热词 + 8 规则已加载**、`/api/transcript/today` 200、☰ 已在。形态/界面/模块数不变，纪要机拿到热词+留档+ws 自愈三项稳定性改进。**5.6 可发总部。**
- **顶栏清理（22:30）**：核实后去掉「旧页 ↗」（/transcript 老单页，转写卡 + /bigscreen 覆盖，路由保留）与「客户视图」（一键演示脸，已被 ☰/布局弹窗/单路视频细粒度开关覆盖；连带删 CSS/JS/副标语 chip，`.cv-toggle` 改名 `.hdr-toggle`）。62 已部署（免重启），Playwright 核顶栏只剩 ☰/退出、无 JS 错误。Mac 仓同步去旧页（2be7d79）。5.6 未刷（下次窗口一并）。
- **品牌配置化（22:50，用户拍板"按建议改"）**：根因=7/14 湖森换装走 `husion-dnc` 分支 + 8/20 `deploy-62.sh` 刷 main 覆盖 `web/`（node-red 在排除名单所以幸存）→ 62 变成"Node-RED 湖森、其它 CREATOR"。改法：**品牌 = 配置 + 素材，不是分支**——config 顶层 `brand: {name, product, logo}`，`web/server.py _brand()` 注入 dashboard/bigscreen 模板，6 处品牌字样变量化；`web/static/brand/husion.png` 入库；`logo` 空 = 纯文字 CREATOR（离线渲染与原模板逐字一致，5.6/Mac 零变化）。62 config 写 `brand: Husion湖森/husion.png`，重启后顶栏/splash/bigscreen 均为湖森（截图核）。以后 `deploy-62.sh` 刷 HEAD 不碰 config，品牌天然保住。
  - **分支收口（23:10，用户拍板直接做）**：校正理解——Mac 线 = 独立仓 `av_understanding_mac`，3588 线 = 本仓；`demo-mac` 只是本仓 7/03 快照分支，与 Mac 仓无关。本仓 5 个非 main 分支全部退役为 tag 并删除：`archive/demo-mac-20260703`、`archive/stable-3588-20260610`、`archive/husion-dnc-20260715`、`archive/board-live-20260807`（活体快照 ahead 1）、`feat/cr-dig7201-asr`（ahead 0 已全并入，直接删）。**本仓只剩 main**。从 husion-dnc 搬到 main：`docs/deploy/dnc-replicate-install.md`（§8 复刻基准改为 main + 金源 config，§1 archive 改 main）、`docs/deploy/3588-new-machine-install.md`、`deploy/systemd/*` 4 个单元（firefly 路径版，62 实机 user 不同，作模板）。
- **未完成项**：① ollama url 读 config；② detect 心跳洪泛/零目标排查；③ P2.1b；④ 5.6 若切 full 形态要用 NPU YOLO/声纹：装 lite2 + rknn 模型 + meeting_camera + CAM++ 模型（现 meeting_asr 不需要）；⑤ C920 两人实测声纹分离；⑥ ~~声纹发言人改名~~（16:55 已做：点 S<n> 标签内联改名 → `/api/speaker/alias` 落 TranscriptStore alias 行 + SSE 广播，多页同步、后续同人句直接显真名、纪要导出自动用真名；62 Playwright 验证过）；⑦ .62 启动脚本"等 426"兜底随 ws 自愈可简化。
- **下次接手所需上下文**：62 导出 venv `~/rknn-export-venv`、产物 `~/yolo-rknn/`；pgrep 自匹配坑又踩一次（等待循环的 pgrep 模式匹配到自身、永不退出），见 memory `ssh-pkill-self-match-trap`。

- 战略定位写入第一行："AI 技术底座 + A/B/C 三层次（架构 = 形态对应）"
- §1.6 三步框架升级为 §3 两阶段框架
- 阶段一打 `v1.0-stage1-mac-validated` tag 固化（销售 >16GB Mac checkout 即用）
- 阶段二必备能力 trade-off 表写入：标点+纪要+说话人 mock 可不大改（~1d）；逐字 partial + 真整句修正 + 真说话人需大改
- Jetson 角色：5/15 "封板" → 5/18 "独立支线"（视频深思持续 + CUDA 语音验证）
- 根目录 30+ md 整理到 `docs/handoffs/` + `docs/reports/2026-05/`
- 新增 §8 工程纪律（GitHub 调研报告 gating）
- watcher 长测 763 samples / 62.7h 入仓 `data/longtest_20260515/`，零模块挂

## 10. 历史与归档指针

| 文件 | 内容 |
|---|---|
| `ARCHIVE_2026Q2.md` | 5/3-5/13 进度索引、R1-R6 演进、已废弃方向；**8/22 追加**：原 §3.2 5/18 路线、原 §6、原 §7 看板、5 月日志 |
| `docs/DECISIONS.md` | 主 Claude↔终端决策同步点（每次开工先读） |
| `docs/回流表-Mac线与3588线-20260821.md` | 两线能力对照 + 防脱节纪律 |
| `docs/探讨-跨模块跨系统信息共享-20260822.md` | 阶段三四方向核实与接法 |
| `docs/deploy/dnc-replicate-install.md` | 湖森复刻 SOP（基准 = main + 金源 config） |
| `LESSONS_LEARNED.md` | 踩坑 trap 速查、重大诊断教训、演示前 checklist、远期网络可观测性 |
| `JETSON_FINAL_20260515.md` | Jetson 角色文档（5/18 标注更新为"独立支线"）|
| `PLAN_R1_R6_subscription.md` | R1-R6 订阅式架构详细设计（仍有效）|
| `docs/handoffs/` | 历史接续文档（OVERNIGHT_HANDOFF + MORNING_RESUME 共 6 份）|
| `docs/reports/2026-05/` | 5/11-5/14 Subagent 报告（共 16 份 OVERNIGHT_REPORT + NIGHT_REPORT）|
| `docs/sales/` | 销售材料 3 份 |
| `docs/roadmap/` | landscape 调研 + liaohe-3588 路线图 |
| `docs/deploy/` | Mac / 3588-NPU / Jetson / 3588-demo-package 部署文档 |
| `summaries/*.json` | 会议纪要存档（5/9-5/11 共 4 份）|
| `scripts/longtest_watcher.sh` | 13 维度 5min 采样 watcher |
| `data/longtest_20260515/sample.jsonl` | 5/15-18 长测数据 763 samples / 62.7h |

新归档（2026 Q3+）：另开 `ARCHIVE_2026Q3.md`，不再追加本文。
