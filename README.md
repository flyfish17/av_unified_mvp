# av_unified_mvp

端侧"理解 → 编排 → 执行"统一系统：摄像头 + 麦克风 → 语义事件 → MQTT 总线 → Node-RED 编排 → 前端展示 / 设备执行。优先**离线运行**。

> 完整开发蓝本与进展：见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)

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
brew install mosquitto       # MQTT broker
# Docker Desktop 自行装好并打开
```

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
├── DEVELOPMENT_PLAN.md   开发蓝本 + 进展 + 下次切入点
├── config/system_config.yaml
├── core/                 基础设施（MQTT bridge、base module）
├── modules/              理解模块（可独立运行）
│   ├── audio_processor/
│   ├── video_processor/
│   └── llm_engine/
├── web/                  Flask SSE + 原生 JS 演示页
├── node-red/
│   ├── flows.json              新协议示例：语音 → av/control
│   └── flows_legacy_creator.json  CREATOR 移植版本（仅历史参考）
├── ui/                   Streamlit 旧版面板（待迁移到 web/）
├── main.py               一体化入口（开发期方便）
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

更多见 [DEVELOPMENT_PLAN.md](./DEVELOPMENT_PLAN.md)。
