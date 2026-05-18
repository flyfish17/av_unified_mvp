# 踩坑经验与诊断教训

> 从 av_unified_mvp 项目中沉淀的实战经验。新加坑请追加，按"症状 → 根因 → 处置"格式。
> 完整历史回合详情见 `ARCHIVE_2026Q2.md` 与 git log。

---

## 1. 关键 trap 速查表

| 类别 | 症状 | 根因 | 处置 |
|---|---|---|---|
| **协议** | creator PDF 写 HTTP :23282 是错的 | PDF 是旧版本，厂家文档不可全信 | **先抓真实流量样本对照**（TCP :12121 + 密码 `123456` 是事实） |
| **协议** | husion `hscmd-get-tx-*` idList=[] 返回空 | 必须传具体 idList | 显式传 RX 5001-6999 列表 |
| **网络** | husion `.150.x` 网段不可达 | 改 `/16` 子网会断办公网 | `sudo ifconfig en1 alias 192.168.150.250 netmask 255.255.255.0`（保留 `/24`） |
| **网络** | RTSP 长时间连不上 / 卡顿 | AV 设备组播洪泛 + 办公交换机无 IGMP Snooping | VLAN 隔离 + 交换机开 IGMP Snooping（细节见 §6 网络可观测性） |
| **重启** | kill main.py 后立刻重启撞 :5050 TIME_WAIT | TIME_WAIT 60s 端口占用 | `until ! lsof -i :5050 -sTCP:LISTEN; do sleep 1; done` 后再启 |
| **重启 (深坑)** | Flask 5050 retry 没生效 | werkzeug 用 `print + sys.exit` 绕过 `OSError`，常规 try/except 接不住 | task #54 待修；测试需 socket.bind 验证；当前演示靠 supervisor 自动重启兜底 |
| **代理** | requests 调 `127.0.0.1` 走系统代理（Clash）→ 404 | Python requests 默认读 env `HTTP_PROXY` | `requests.Session(); s.trust_env = False` |
| **Node-RED** | function 节点 setTimeout / context state 重启不 reset | flow context 重启后不清 | 用 `flow.set/get` + `initialize` 字段；timer 在 `finalize` 清 |
| **Git** | iCloud 路径偶发 `.git/index.lock write timed out` | iCloud 同步与 git lock 冲突 | `rm .git/index.lock` 后重 add；长跑用 worktree 出 iCloud |
| **Creator** | admin 单 session 限制，多端 login 后续返 code=3 | 协议限制 | 同 token 串起来或让出旧 session |
| **rsync** | 改 3588 上代码同步到错路径 | 5/14 同步到 `/home/firefly/creator_ai_demo/modules/` 但 supervisor 跑 `/home/firefly/av_unified_mvp/modules/` 浪费 30min | 同步前 `readlink /proc/<supervisor_pid>/cwd` 确认 cwd |
| **3588 sudo** | 没有 sudo 权限 | user 维护权限，没给 root | 写脚本前用 `cat /etc/passwd \| head -5` 等 noop 命令验证；需要 sudo 的事走 user 现场 |
| **Jetson SSH** | 没有 Jetson 密码 | 无密码、user 也不维护 | 所有诊断走 MQTT；需要现场 ssh 找 user |
| **Claude 授权** | 3588 supervisor.log 在 5/15 00:54 后整夜冻结 | 不是技术故障 — 是 Claude Code 弹了授权弹窗等 user 早上点 yes，期间所有 Bash 子命令 stuck | 看 ssh session 输出冻结 → 先排查是否有 pending 授权再排查代码 |
| **shell** | `timeout` 命令不可用 | macOS 默认没有 GNU coreutils 的 `timeout` | 用 `gtimeout`（brew install coreutils）或 `mosquitto_sub -W` 等内置超时；3588 上 Linux 自带 |
| **诊断顺序** | mqtt sub 看不到 topic 数据就以为模块死了 | 5s timeout 太短 + 空房间没新消息 + retain msg 已被覆盖 | 看 `/proc/<pid>/status` 进程状态 + socket fd ESTAB + `wchan` 阻塞点；网络流量层比应用层更可信 |

---

## 2. 重大诊断教训

### 2.1 协议文档 ≠ 真实流量（多次踩到）
- creator PDF :23282 是错的 → 实际 :12121
- husion `hscmd-get-tx-*` 文档没说 idList 必须显式传
- ollama keep_alive=10m 文档说会卸载 → Jetson 实测整夜 mem 98% 没释放

**铁律：协议文档（厂家 PDF）不可全信，先抓真实流量样本对照。**

### 2.2 Jetson 内存死锁（5/14 夜班定位）
**症状**：4 路 VLM 链路 9.5h 96.2% drop，scene_analysis 全部命中单路。
**根因**：Jetson Orin Nano 8G unified memory 被 qwen2.5vl:3b + ollama context 顶到 ≥97%，scene_analyzer `mem_min_mb=400` 守门触发批量 drop。
**关键发现**：调任何 keyframe 节流参数（idle_seconds / conf_threshold）都救不了；是硬件容量根本性不够。
**结论**：不在 Jetson 上加钱，换 Mac mini / 工作站；详见 `JETSON_FINAL_20260515.md`。

### 2.3 5/14 三层视觉链路的"饿死"事件
**症状**：keyframe_filter / openvocab_filter / scene_analyzer 静态画面下零输出。
**根因**：video_processor 在 YOLO 无目标时静默不 publish，整条链路下游饿死。
**修法**：commit `6ecec51` — 无目标也按 `idle_detect_interval_s` (默认 15s) publish 空 detect 当心跳。
**教训**：MQTT 解耦架构里**任何模块的"无事不发"语义都要在协议层显式定义**，否则下游订阅方判断不出"安静"与"挂了"。

### 2.4 "进程在跑 ≠ 模块在工作"（5/15 llm_engine 静默事件）
**症状**：3588 上 llm_engine + control_dispatcher 进程 etime 19h 但 mqtt discovery 看不到心跳。
**误判**：以为进程死了 / 僵尸。
**真相**：State=S sleeping in `do_select`，socket fd 4 → 1883 mqtt + fd 3 → 11434 ollama 都 ESTAB；只是夜里没人说话 = 没 av/audio/command 触发 = 没 INFO log。
**教训**：模块"安静"≠"死"；判定顺序应是 `/proc/PID/status` + `socket fd ESTAB` + `mqtt traffic 长 sub`，不是单纯看应用层 log 是否更新。

### 2.5 YOLO26n 升级（5/14 Sub-2 实测）的"宣传 vs 实测"
**宣传**：43% 提速 + open-vocab。
**实测**：慢 5% + open-vocab API 缺失。
**结论**：换 yolov8-world + CLIP（Sub-5 实测 person without hardhat conf 0.36 / falling 0.67-0.80）。
**教训**：landscape 调研的宣传数据要 reality check 实测才能采纳。

---

## 3. 演示前 checklist（继承 5/8 客户现场版）

1. **🔴 Ollama 服务**：`curl -s http://127.0.0.1:11434/api/tags`（3588 + Jetson + Mac mini .193 三处都验）
2. **🔴 误识别**：闲聊话被 LLM 命中 cmd（catalog 关键词触发太宽）。建议演示限定话术；根治需收紧关键词或卡 Ollama 必过
3. **🟡 启动方式**：`./start.command` 前台，不要 nohup 后台（mosquitto 在 sleep 后死过）
4. **🟡 视频源**：到客户网段后再逐个点确认；首次启动 30s 内 badge 显示"连接中"是正常窗口
5. **🟡 summaries/**：3588 上首次部署没有历史纪要文件，演示纪要功能需现场触发或预先 scp 示例
6. **🟡 视觉深思**：Jetson VLM 96% drop 是已知边界，演示陈词用"偶发智能巡检"，不承诺连续覆盖

---

## 4. 远期方向：网络可观测性子系统（5/7 沉淀）

**业务定位**
AV / 控制类设备与客户办公网混合部署是高频痛点。客户报"卡了 / 掉了"时定位手段缺乏，讯飞类 AI 厂商不做这块 — 这是 av_unified_mvp 在"AI 理解"之外的第二条差异化护城河：从"AV 集成商"→"AV 系统运维商"。

**故障根因（速查）**
1. AV 设备网络行为特殊：大量组播（mDNS / SSDP / IGMP / Dante / SDVoE 单路 6-10 Gbps）；时序敏感（PTP <1μs，抖动 <10ms）；持续高流量
2. 办公网"噪声"：DHCP 池小 / IP 抢占；交换机不开 IGMP Snooping → 组播全口洪泛（卡顿/花屏首发原因）；防火墙默认拦多播
3. 协议设计假设专网：无 QoS、无带宽控制；海康/大华 SDK 端口（8000 / 37777）权限模型粗

**集成层改良（推给客户 IT）**
- VLAN 隔离（AV / 控制 / 摄像头 / 办公分开），L3 路由 + ACL
- 交换机：**IGMP Snooping + 每 VLAN 一个 querier**（治 90% 卡顿）、QoS DSCP、Storm Control、BPDU Guard
- 设备：静态 IP / DHCP MAC 绑定、关跨 VLAN 发现协议、改默认密码

**项目可落地路径**
- 持续探活模块 `modules/network_health/`：每 30s ping + SNMP 拉交换机端口流量/丢包/CRC；事件 `av/network/health/<host>`
- 告警关联：摄像头 LWT offline → 联查相邻交换机端口 link flap / 丢包暴增
- 抓包模式（远期）：边缘盒子按需 tcpdump 60s，自动分析组播洪泛 / mDNS 风暴

**MVP 工作量**：ping 心跳 + dashboard 曲线 1d；+ SNMP 1-2d；+ 告警关联 2-3d；+ 抓包 1w
**优先级**：P5 远期，主线 sprint 收口后评估

---

## 5. AI / Claude 协作的几个经验

- **destructive 命令前必须先确认** — user 不喜欢自作主张的"清理"
- **不要"防御性编程"** — 出问题就报错让 user 看到，别 try/except 吞掉
- **诊断先抓证据**：日志 / 抓包 / lsof / mqtt sniff，不要先猜
- **三行相似 > 一个早产抽象** — 不为子模块完美阻塞整体框架
- **协议先行**：MQTT topic schema 是合同，跨模块协作只看 schema，**不要 import 另一个模块的内部实现**
