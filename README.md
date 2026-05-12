# av_unified_mvp

端侧"**理解 → 编排 → 执行**"统一系统 — 摄像头 + 麦克风 → 语义事件 → MQTT 总线 → Node-RED 编排 → 前端展示 / 设备执行。**优先离线运行**。

> 完整开发蓝本与回合日志：见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)（2200+ 行，按时间倒序）

## 文档地图（渐进披露）

| 阶段 | 文档 | 何时读 |
|---|---|---|
| 1 分钟概览 | 本文 § R28 能力总览 + § 架构 | 完全没接触过 |
| 5 分钟接手 | [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md) § 0 § 11 | 要接 sprint 任务 |
| 客户/路线图 | [docs/roadmap/liaohe-3588.md](./docs/roadmap/liaohe-3588.md) | 辽河 3588 sprint 现状 + 阶段 3/4 计划 |
| 平台部署 SOP | [docs/deploy/3588-npu.md](./docs/deploy/3588-npu.md) | RK3588 + NPU 路径落地（国产化主推）|
| | [docs/deploy/mac.md](./docs/deploy/mac.md) / [jetson.md](./docs/deploy/jetson.md) | 目前是占位 + 指向 DEVELOPMENT_PLAN 对应章节 |
| 日工作日志 | NIGHT_REPORT_yyyymmdd.md（按日）| 找昨天/今天具体踩坑细节 |

## R28-snapshot 能力总览（v1.1 → 当前）

| 维度 | 能力 |
|---|---|
| **感知** | YOLOv8 视频检测 + FunASR 2pass 流式转写（partial 边讲边出 + final 标点 ITN）+ 摄像头亮度采样 |
| **理解** | qwen3.5:9b LLM 意图翻译，prompt 自动从 device_catalog 生成（76 物理设备指令，支持笼统词灵活匹配 + 标点容错） |
| **编排** | Node-RED 60 节点（av/control ASCII 转发 + L3 规则 1/2 + 大屏 SVG 流转图）；用户可视化拖拽改 |
| **执行** | creator 中控 ASCII 短连接 TCP（76 物理设备：灯/空调/窗帘/场景），catalog driven |
| **跨品牌桥接** | husion HDC900 9 路 ws://flv 流自动接入；creator 分布式 v3.0 协议链路验证；不替代原厂家管理平台 |
| **UI** | GridStack 拖动 + 模块隐藏/重置布局；视频源 CRUD（IPC/分布式/USB 三类型表单）+ LAN 扫描一键填表；单聚合 SSE 解决 6-connection 限制 |
| **自动化** | L1 按钮即点即发；L2 语音"打开二楼餐桌空调" → 物理动作；L3 摄像头识人 → 开灯 + 5min 无人 → 关 / 13:00 + 大太阳 → 拉窗帘 1s |

## 架构

```
摄像头/麦克风
   │
   ▼
理解模块（独立进程）
  audio_processor   FunASR 2pass：partial + final + 标点 + 整句修正
  video_processor   YOLOv8
  llm_engine        意图分类 + 指令生成
   │
   ▼  MQTT pub
本地 mosquitto :1883
   │
   ├─▶ Node-RED :1880        场景规则编排（用户可拖拽）
   │
   ├─▶ Web :5050             Flask + 原生 JS，SSE 订阅事件流
   │
   └─▶ 设备执行              IR / Zigbee / HA
```

详见 [DEVELOPMENT_PLAN.md §2](./DEVELOPMENT_PLAN.md#2-目标架构六层)。

## 快速开始

### 一次性准备

```bash
pip install -r requirements.txt
brew install mosquitto                       # MQTT broker
npm install -g node-red                      # Node-RED 编排（可选，但推荐）
# Docker Desktop 自行装好并打开（funasr-2pass 容器需要）

# 复制配置模板（system_config.yaml 已 .gitignore，含敏感字段）
cp config/system_config.example.yaml config/system_config.yaml
# 编辑 config/system_config.yaml：
#   · video.sources 里的 RTSP 密码（占位符 ${IPC_PWD} 改成实际值）
#   · husion.host / id_ranges（如有 husion HDC900 设备）
```

**Husion 子网注意**：husion HDC900 内部分布式终端在 `192.168.150.x` 网段。直接改子网掩码 /16 会让默认网关失效不能上网，**推荐用 ifconfig alias** 给本机网卡追加一个 `.150.x` IP（不动原 /24 配置，互联网仍走原网关）：

```bash
# 看 Wi-Fi 对应的网卡名（mac 多数是 en1）
networksetup -listallhardwareports | grep -A 1 'Wi-Fi'

# 给 en1 加 alias（临时，重启失效）
sudo ifconfig en1 alias 192.168.150.250 netmask 255.255.255.0

# 验证两条路都通
ping -c 3 192.168.150.1   # husion 内部
ping -c 2 baidu.com       # 互联网

# 持久化（开机自动）：保存为 /Library/LaunchDaemons/local.husion-alias.plist
sudo tee /Library/LaunchDaemons/local.husion-alias.plist >/dev/null <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>local.husion-alias</string>
  <key>ProgramArguments</key>
  <array>
    <string>/sbin/ifconfig</string><string>en1</string><string>alias</string>
    <string>192.168.150.250</string><string>netmask</string><string>255.255.255.0</string>
  </array>
  <key>RunAtLoad</key><true/>
</dict>
</plist>
EOF
sudo launchctl bootstrap system /Library/LaunchDaemons/local.husion-alias.plist

# 撤销 alias 时
sudo ifconfig en1 -alias 192.168.150.250
```

如果 mac 不在 husion 内部物理段（alias 后 ping .150.x 不通），退到静态路由：`sudo route -n add -net 192.168.150.0/24 192.168.5.253`

### 启动（双击）

在 Finder 里双击：
- **`start.command`** — 起 mosquitto + funasr-2pass 容器 + 主程，并自动打开浏览器
- **`stop.command`** — 反向全部停掉

首次双击 `start.command` 会自动建 funasr 容器并下载模型（~3 GB / 5-10 min）；后续双击秒开。

启动后浏览器自动打开 **http://localhost:5050/**：
- 黄色虚线气泡 = `partial`（边说边出，无标点）
- 绿色实线气泡 = `final`（整句修正完成，**带标点**）

### 命令行启动（等价）

```bash
./start.command
# 或手动：
mosquitto -c /opt/homebrew/etc/mosquitto/mosquitto.conf -d
docker start funasr-2pass     # 首次需 docker run，见 start.command
python3 main.py
```

### Ollama（可选，做意图识别 / 指令生成）

```bash
ollama serve
ollama pull qwen2.5:7b
```

## 离线兜底

- **FunASR 容器连不上** → 自动降级到本地 SenseVoiceSmall（按句切段，无 partial，仍可出 final）
- **Ollama 连不上** → 跳过意图识别，仅展示 + MQTT 转发
- **摄像头/麦克风缺失** → 模块单独失败，不阻塞其他模块

## 模块独立运行

每个理解模块都可以独立启动（仅依赖 MQTT broker）：

```bash
python3 -m modules.audio_processor.main    # 仅语意理解
python3 -m modules.video_processor.main    # 仅视觉
python3 -m modules.llm_engine.main         # 仅 LLM
```

发布的 topic 见 [DEVELOPMENT_PLAN.md §4](./DEVELOPMENT_PLAN.md#4-mqtt-topic-协议)。

## Node-RED 编排

`node-red/flows.json` 是符合 §4 协议的最小示例，演示『语音 final → 关键词翻译 → av/control』。`flows_legacy_creator.json` 是早期 CREATOR 项目移植版本，仅作历史参考。

### 部署示例 flow

```bash
# 选项 A：从 UI 导入（推荐第一次）
node-red                                # 浏览器 http://localhost:1880
# 右上汉堡菜单 → Import → 粘贴 node-red/flows.json 内容 → Deploy

# 选项 B：直接替换（小心，会盖掉你已有 flow）
cp node-red/flows.json ~/.node-red/flows.json
node-red
```

部署后：
- 点击 **inject** 节点 `模拟: 『打开二楼餐桌空调』` → debug 侧边栏看 `av/control` 翻译结果
- 真实语音：`python3 -m modules.audio_processor.main` 后说话，flow 会捕到 `av/audio/command` 并翻译
- 旁路 `av/#` debug 节点持续输出总线全量

### 加新场景的最小步骤

1. **MQTT in** 节点订阅触发 topic（按 §4 协议）
2. **function** 节点提取 `msg.payload.payload.<field>` 做条件判断
3. **mqtt out** 节点发到 `av/control`，载荷 `{ target, action, params }`
4. 调试时挂 **debug** 节点看每段消息

复杂判断（多模态融合、LLM 决策）建议交给 `modules/llm_engine`，Node-RED 只做规则路由 + 设备调用。

## 目录

```
av_unified_mvp/
├── DEVELOPMENT_PLAN.md           开发蓝本 + 回合 1-29 进展（1700+ 行）
├── config/
│   ├── system_config.example.yaml  配置模板（首次复制为 system_config.yaml）
│   └── device_catalog.json         设备目录（76 条 ASCII 指令 + locations + device_types）
├── core/                          基础设施（MQTT bridge、base module、profile）
├── modules/                       理解 + 桥接模块（独立子进程，全 MQTT 通信）
│   ├── audio_processor/             FunASR 2pass 流式转写
│   ├── video_processor/             YOLOv8 + 多 RTSP 源 + MJPEG 服务 :5051
│   ├── llm_engine/                  qwen3.5:9b 意图翻译（catalog driven prompt）
│   ├── system_info/                 主机指标（CPU/MEM/磁盘/负载）→ av/system/host_stats
│   ├── network_info/                网卡 IP + 收发速率 → av/system/network
│   ├── network_scanner/             局域网扫描 → av/system/lan_scan/{cmd,progress,result}
│   └── husion_distributed/          husion HDC900 9 路设备发现 + flv 流透出
├── web/                           Flask SSE + 原生 JS 中控大屏
│   ├── server.py                    单聚合 SSE /events/__all__ + REST endpoints
│   ├── templates/dashboard.html     8 模块卡 + GridStack 拖动 + flv.js + hls.js
│   └── static/                      dashboard.js + lib (gridstack/hls/flv) + renderers
├── node-red/
│   ├── flows.json                   60 节点（av/control 转发 + L3 规则 + SVG 大屏）
│   └── settings.js
├── main.py                        supervisor 主程：拉起 7 个子模块 + web 桥接
├── start.command / stop.command   一键启动/停止（双击运行）
└── requirements.txt
```

## 故障排查

| 现象 | 排查 |
|---|---|
| funasr-2pass 容器 Exited (0) | 启动命令必须用 `bash -c "...; tail -F"` 包一层 |
| 浏览器无气泡 | `docker logs funasr-2pass | tail -30` 看模型是否就绪；查 `mosquitto_sub -h 127.0.0.1 -t 'av/#' -v` |
| MQTT 连接失败 | `brew services list` 看 mosquitto 状态 |
| Ollama 无响应 | `ollama list` 确认模型已下 |
| 摄像头打不开（macOS） | 系统设置 → 隐私 → 摄像头授权终端/Python |
| Ollama 调用 404（实际本地有模型） | 系统代理（Clash 等）劫了 127.0.0.1 流量。`engine.py` 已用 `Session(trust_env=False)` 绕过；如果还有问题 `unset http_proxy https_proxy` |
| L3 规则 1（人检测开灯）触发后没二次响应 | 这是 design：lit=true 后保持 5min，避免 spam。重启 node-red 或等 5min 无人自动关后再触发 |
| husion ws://flv 流播不动 | Mac 子网掩码改 /16（`255.255.0.0`）让 `192.168.150.x` 可达；或加路由 |
| docker pull funasr 慢 | 用 `docker save \| docker load` 从已有的 mac 流式同步（详见 DEV_PLAN 回合 26） |

更多见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)。

## 致谢

本仓库的 R1-R29 累积工作由 [Claude Code](https://claude.com/claude-code) (Anthropic) 协同完成。开发节奏 / 复盘 / 错误诊断方法论详见 DEVELOPMENT_PLAN.md。
