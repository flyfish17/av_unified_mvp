# RK3588 客户演示包 SOP

> 把 av_unified_mvp 包装成"演示前 60s 一键就绪、客户友好"的演示包。
> 主入口：`http://192.168.5.6:5050`（dashboard，右下角"演示"浮球）。
> 配套 NPU 全栈 SOP 见 `3588-npu.md`（开发者向）。

## 适用场景

- 销售带板子到客户现场，桌面 / SSH 一键起整个系统
- 自然语言"开研发部空调"→ NPU RKLLM 198ms 首 token → av/control 控制设备
- 网络断了 / LLM 卡住时，浮球按钮直接走"离线兜底"路径让演示不翻车
- 无需 user 手动 export 任何 env，无需 user 看 9 个 Python 子进程

## 0. 前置条件（一次性，已部署可跳过）

```bash
# 3588 上跑一次（首次部署，参考 3588-npu.md § 1-11.1）
~/creator_ai_demo/venv/bin/pip install flask opencv-python-headless ultralytics
```

如果是新克隆的板子，需要先按 `3588-npu.md` § 2-10.3 把 SenseVoice + RKLLM 的模型和 daemon 部署到位：
- `~/SenseVoiceSmall-RKNN2/`（ASR 模型 + daemon）
- `~/rkllm-poc/artifacts/Qwen2.5-1.5B-Instruct_W8A8_RK3588.rkllm`（LLM 权重）
- `~/rkllm-poc/daemon/rkllm_daemon.py`（LLM daemon）
- `~/av_unified_mvp/`（仓库本体）
- `~/creator_ai_demo/venv/`（demo 自带 venv，已含 flask/opencv/torch 等）

## 1. 演示当天 — 启动

板子上电 → SSH 进去（或本机终端）：

```bash
bash ~/av_unified_mvp/scripts/3588-demo-start.sh
```

脚本会：
1. 自检：项目目录 / venv / NPU 设备节点 / 模型文件
2. 拉起外部服务：mosquitto / ollama / Node-RED（缺哪个起哪个）
3. 检测旧 supervisor：在跑则不重启（避免误杀），加 `--force` 才强制重启
4. 启 main.py supervisor，env：`AV_LLM_BACKEND=rknn` / `AV_ASR_BACKEND=sense_voice_arm` / `AV_RKNN_BACKEND=1`
5. 轮询 45s，等 dashboard :5050 200 + 9 个 module 子进程在线
6. 输出："演示就绪 → http://192.168.5.6:5050"

成功输出示例：
```
═══ 4. 演示就绪状态 ═══
  Dashboard HTTP   : 200
  Module 子进程    : 9 / 9
  RKLLM daemon     : 1234567
  SenseVoice daemon: 1234568

═══════════════════════════════════════════════
  ✓ 演示就绪
═══════════════════════════════════════════════
  主 dashboard : http://192.168.5.6:5050
  视频 MJPEG   : http://192.168.5.6:5051
  Node-RED     : http://192.168.5.6:1880
  日志         : tail -f /tmp/main_supervisor.log
```

### 1.1 可选参数

```bash
bash ~/av_unified_mvp/scripts/3588-demo-start.sh --status   # 只看状态不动手
bash ~/av_unified_mvp/scripts/3588-demo-start.sh --force    # 杀旧 supervisor 重启
bash ~/av_unified_mvp/scripts/3588-demo-start.sh -h         # 帮助
```

## 2. 演示当天 — 客户机浏览器打开

```
http://192.168.5.6:5050
```

页面右下角浮一颗 **「演示」黄色小球**，点开展示 5 颗预设句式按钮：

| # | 句式 | 期望 cmd |
|---|---|---|
| 1 | 把研发部空调打开 | `RDDepartment_AirConditioner_On` |
| 2 | 关闭吧台灯带 | `BarCounter_Light_Off` |
| 3 | 把二楼餐桌空调温度调高 | `2FDiningTable_AirConditioner_TempUp` |
| 4 | 拉开会议室1的窗帘 | `MeetingRoom1_Curtain_Open` |
| 5 | 把运营中心灯带打开 | `OperateCentre_Light_On` |

### 2.1 行为流程（点按钮发生什么）

```
[click 演示 1]
   │
   ▼
POST /mqtt/publish {topic: "av/llm/command", payload: {text: "把研发部空调打开", ...}}
   │
   ▼
llm_engine 收到 → NPU RKLLM 198ms 首 token → 输出 cmd JSON
   │
   ▼
av/llm/event command_generated  +  av/control payload.cmd=RDDepartment_AirConditioner_On
   │
   ▼
dashboard 控制面板高亮 + 浮球 toast "✓ 演示 1 命中"
```

### 2.2 离线兜底（演示翻车保险）

如果 4.5 秒内没收到 `av/control` 含期望 cmd（LLM 慢 / 地点偷换被 anti-hallucination 拒），浮球自动走兜底：

```
POST /mqtt/publish {topic: "av/control", payload: {cmd: "RDDepartment_AirConditioner_On", source: "demo_button_fallback"}}
```

dashboard 控制面板仍然看到命令落下 → 演示不停。

## 3. 演示当天 — 现场口语 ASR

客户对着 USB 麦说："开研发部空调"。链路：
- audio_processor 走 SenseVoice NPU daemon → 端到端 ~400ms 出文本
- llm_engine 拿文本 → NPU RKLLM ~3.5s 出 cmd
- dashboard 转写气泡 + 意图气泡 + 控制面板同步更新

要点提示给销售：
- 要明示地点（说"研发部""吧台"），别说"这里"
- NPU 1.5B 对"吧台→2FDiningTable""机房→Corridor"有偷换偏置 — 期望保护行为是拒绝（anti-hallucination filter）

## 4. 演示后 — 关停

浏览器右上角点 `⏻ 退出系统`（main.py 已实现 graceful shutdown，连带停 mosquitto / Node-RED / FunASR 容器）；
或 SSH：

```bash
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 'pkill -TERM -f "creator_ai_demo/venv/bin/python.*main.py"'
```

板子关机前最好走 graceful（让 RKLLM daemon 释放 1.7GB NPU 内存）：

```bash
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 'sudo shutdown -h now'
```

## 5. 故障排查

| 症状 | 排查 | 修法 |
|---|---|---|
| `bash scripts/3588-demo-start.sh` 直接报"项目目录不存在" | `$HOME/av_unified_mvp` 路径不对 | `AV_PROJECT_DIR=/your/path bash ...` |
| 脚本卡 "等待 dashboard 就绪" 45s 超时，HTTP=000 | Flask 启动失败 / 端口被占 | `ss -tlnp \| grep :5050`；或 `tail -50 /tmp/main_supervisor.log` |
| 模块数 < 9 长时间不上 | venv 缺包；或 NPU 设备节点不通 | `tail -50 /tmp/main_supervisor.log` 找 ImportError / 子进程崩溃日志 |
| 浮球按钮点了没反应 | dashboard 看不到 toast | 浏览器 F12 console，看 `/mqtt/publish` 是否 200 |
| 按钮一直 busy 4.5s 才回 | LLM 没产生预期 cmd（地点偷换） | 兜底已自动接管，看 dashboard 控制面板 |
| 浮球都不出现 | dashboard.html 未刷新 | 浏览器 Ctrl+Shift+R 强刷 |

## 6. 关联文件

- 启动脚本：`scripts/3588-demo-start.sh`
- dashboard 演示按钮：`web/templates/dashboard.html`（最末 `<script>` 块 `initDemoBar()`）
- 演示按钮列表配置（如要改预设句式）：dashboard.html 内 `const DEMOS = [...]`，5 行 → 客户化时直接改这里
- NPU 全栈 SOP（开发者向）：`docs/deploy/3588-npu.md` § 11
