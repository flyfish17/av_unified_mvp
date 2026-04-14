# AV统一系统 MVP

专业视听系统的端侧单体融合架构 - 最小可行版本

## 功能特性

- **视觉流**: OpenCV多路视频 + YOLOv8目标检测
- **语音流**: FunASR实时语音识别
- **决策引擎**: Ollama大模型意图识别 + 指令生成
- **通信层**: MQTT设备间通信 + 自动发现
- **Web界面**: Streamlit实时监控

## 快速开始

### 1. 安装依赖

```bash
cd av_unified_mvp
pip install -r requirements.txt
```

### 2. 安装MQTT Broker（本地）

```bash
# macOS
brew install mosquitto
brew services start mosquitto

# Ubuntu/Debian
sudo apt install mosquitto mosquitto-clients
sudo systemctl start mosquitto
```

### 3. 启动FunASR（如果还没启动）

```bash
docker run -d --name funasr-server \
  -p 10095:10095 \
  registry.cn-hangzhou.aliyuncs.com/funasr_repo/funasr:funasr-runtime-sdk-online-cpu-0.1.10
```

### 4. 启动Ollama（如果还没启动）

```bash
ollama serve
ollama pull qwen35-9b:latest
```

### 5. 修改配置

编辑 `config/system_config.yaml`：
- 修改摄像头URL（默认用本地USB摄像头）
- 修改MQTT client_id（每个盒子不同）
- 调整YOLO推理频率（默认2 FPS）

### 6. 运行主程序

```bash
python main.py
```

### 7. 打开Web界面（可选）

```bash
streamlit run ui/web_interface.py
```

访问 http://localhost:8501

## 架构说明

```
av_unified_mvp/
├── config/
│   └── system_config.yaml      # 统一配置
├── core/
│   ├── video_processor.py      # 视频流 + YOLO
│   ├── audio_processor.py      # 语音识别
│   ├── llm_engine.py           # 大模型决策
│   └── mqtt_bridge.py          # MQTT通信
├── ui/
│   └── web_interface.py        # Streamlit界面
├── main.py                     # 主程序入口
└── requirements.txt
```

## 工作流程

1. **视频流**: 摄像头 → OpenCV → YOLO推理 → 检测结果 → MQTT发布
2. **语音流**: 麦克风 → FunASR识别 → LLM意图分类 → 生成指令 → MQTT发布
3. **设备通信**: 各盒子通过MQTT互相发现和通信
4. **Web监控**: 实时显示所有MQTT消息流

## 性能优化

- YOLO推理频率可调（默认2 FPS，降低CPU负载）
- 只检测指定类别（person, cell phone, laptop）
- 多线程处理多路视频
- LLM请求加锁防止并发堆积

## 下一步：打包成单体应用

```bash
pip install pyinstaller
pyinstaller --onefile --add-data "config:config" main.py
```

生成的 `dist/main` 即为单体可执行文件。

## 硬件部署

将此程序部署到边缘计算盒子（RK3588/Jetson）：
1. 烧录Ubuntu ARM64
2. 安装Python + 依赖
3. 配置systemd开机自启
4. 内置mosquitto作为本地Broker
5. 配置mDNS（avahi）实现 `avbox1.local` 访问

## 故障排查

- **摄像头打不开**: 检查USB权限，或修改配置中的URL
- **MQTT连接失败**: 确认mosquitto已启动 `brew services list`
- **FunASR超时**: 检查Docker容器 `docker ps`
- **Ollama无响应**: 确认模型已下载 `ollama list`
