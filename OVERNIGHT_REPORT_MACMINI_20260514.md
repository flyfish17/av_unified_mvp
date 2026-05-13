# Mac mini 深思层迁移报告 — 替代 Jetson 当 escalate_receiver

> 时间：2026-05-13 15:30-15:45 CST
> 触发：Jetson POC（OVERNIGHT_REPORT_20260514.md）暴露 qwen3:8b OOM 不可行 + qwen3:1.7b 深思 0/4
> User 拍板：方案 A — escalate 协议入仓 + 深思层迁 Mac mini

## 部署快照

| 项 | Mac mini 5.193 |
|---|---|
| 硬件 | M1 Macmini9,1, 16 GB RAM, macOS 26.3 |
| 用户 | openclawminiold |
| 工作目录 | `~/av_unified_mvp_escalate/`（rsync 自 Mac 本机，独立于 5/12 演示在的 `~/av_unified_mvp/`） |
| python | `/usr/bin/python3` (3.9.6) + `pip3 install --user flask paho-mqtt PyYAML requests` |
| ollama | `/Applications/Ollama.app` PID 19633，5/12 起跑着 |
| ollama 模型 | qwen3.5:2b-q4_K_M（1.9G）+ **qwen3.5:4b**（3.4G）现成；**未 pull qwen3:8b**（国际链路慢，4b 已够用） |
| escalate llm_engine PID | 独立进程，连 3588 broker（192.168.5.6:1883），client_id=av_macmini_escalate_001 |

## 关键 config（mini `~/av_unified_mvp_escalate/config/system_config.yaml`）

```yaml
mqtt:
  broker: 192.168.5.6     # 共用 3588 broker
  port: 1883
  client_id: av_macmini_escalate_001
llm:
  ollama:
    url: http://127.0.0.1:11434/api/generate
    model_fast: qwen3.5:4b
    model_smart: qwen3.5:4b
    timeout: 60
  escalate_receiver: true       # 订阅 av/llm/escalate
  audio_command_subscribe: false # 不订 av/audio/command（避免和 3588 重复处理）
  host_label: macmini
  enabled_default: true
```

## e2e 对比 — qwen3.5:4b vs Jetson qwen3:1.7b

同 4 escalate probe（OVERNIGHT 报告 M4 的"无解" probe set）：

| # | text | Jetson 1.7b | Mac mini 4b |
|---|---|---|---|
| 1 | 把那个灯打开 | hallucinate `RDDepartment_Light_On` → whitelist 拒 ✗ | hallucinate `RDDepartment_Curtain_Open` → location 拒 ✗ |
| 2 | 灯关掉 | `OperateCentre_Light_Off` → location 拒 ✗ | `RDDepartment_Light_Off` → whitelist 拒 ✗ |
| 3 | 请把烤面包机打开 | hallucinate `OperateCentre_AirConditioner_On` → location 拒 ✗ | **`null` ✓ 正确判** |
| 4 | 微波炉的电源关掉 | hallucinate `OperateCentre_AirConditioner_Off` → location 拒 ✗ | **`null` ✓ 正确判** |

**总分**：1.7b 0/4 / 4b 2/4 — qwen3.5:4b 在 "catalog-外设备" 上正确输出 null，**比 1.7b 质的进步**。

剩余 2 个未解（"那个灯"/"灯关掉"）是**无地点笼统命令**：理论上 mini 无 default_location 时模型应回 null，但 4b 仍硬编 — **被 filter 拦下，错命令落地率 0%**。这是符合预期的安全防护，不算 4b 失败。

## 性能

- escalate publish → mini 接收：< 200ms（MQTT 跨段 5.6→5.193）
- ollama qwen3.5:4b 推理：8-10s（vs Jetson 1.7b 3-3.5s）—— **慢但准**
- e2e 端到端：~ 10-12s（vs Jetson 5-6s）

## 资源占用（Mac mini，与 5/12 演示并行）

| 状态 | free | inactive | wired | swap |
|---|---|---|---|---|
| 5/13 escalate 部署前 | ~1.4 GB | ~? | ~? | 不明 |
| 4b 加载后稳态 | 75 MB | 1.9 GB | 7.5 GB | ~? |

ollama ps：`qwen3.5:4b loaded 5.8 GB 100% GPU`，同 5/12 演示共用一个 ollama 实例 — 同模型不重复加载，**两个 client 复用一份 RAM**。RAM 紧但稳，未触发 swap 爆炸。

## 决策跟踪

- ✅ escalate 协议入仓（commit `50b54c8`，user review 通过）
- ✅ Jetson `escalate_receiver: false` 关掉
- ✅ 3588 `escalate_to_jetson: true` 重开（topic 统一是 `av/llm/escalate`，name 当前 misleading 但语义对）
- ✅ Mac mini 5.193 部署 escalate-receiver-only 旁路进程
- ✅ e2e 4 probe 对比，4b 比 1.7b 进步

## 后续 follow-up

1. **`escalate_to_jetson` 字段名改 `escalate_enabled`**（中性命名）— 避免 misleading。涉及 engine.py / main.py / yaml 三处。明天做。
2. **公允 escalate probe set** — 当前 4 probe 都是"无解" case，不能体现"深思层比 NPU 更强"。重新设计：挑 3588 NPU 解不出 + 答案在 catalog 的 prompt，跑 mini 4b 看真实价值。
3. **mini 部署持久化**：当前是 ssh nohup 启的，重启会丢。写到 mini 上 LaunchAgent 或 mini 本机 supervisor 加入这个 escalate 进程
4. **qwen3:8b 拉？** — Mac mini RAM 16G 跑 5.8G 4b 已紧。8b loaded ~10G + audio_processor 1.5G + 5/12 supervisor 7 模块 ≈ 13G 接近上限；可能需要专门服务器（或后续上 Mac Studio 等大 RAM 机器）
5. **3588 长跑样本断点**：今天 rkllm_daemon 被重启两次（escalate 配置改 + Jetson POC），5/13 原 11.5h 长跑数据丢；今晚烧机重计时

## 进程现状（5/13 15:45 CST）

### 3588 (192.168.5.6)
- 1162126 main.py supervisor
- 1166144 audio_processor
- **1227925 llm_engine**（最新，escalate_to_jetson=true）
- rkllm_daemon（被 1227925 子进程拉起的新 PID）
- 1213242 video_processor (4 路)
- 1188869 node-red

### Jetson (192.168.5.51)
- 604725 audio_processor（5/12 起 30h+，未动）
- 620547 main_jetson.py supervisor
- 620550-552 system_info / network_info / control_dispatcher
- **623671 llm_engine**（escalate_receiver=false）

### Mac mini (192.168.5.193)
- 5/12 演示 supervisor（PID 20225 main.py + 7 模块，未动）
- ollama Ollama.app PID 19633
- **新增 escalate llm_engine**（旁路进程，连 3588 broker）

## 紧急回滚

```bash
# Mac mini 停 escalate
SSHPASS=123456 sshpass -e ssh openclawminiold@192.168.5.193 \
  "pkill -f 'av_unified_mvp_escalate.*llm_engine'"

# 3588 关 escalate_to_jetson + 重启 llm_engine
SSHPASS=firefly sshpass -e ssh firefly@192.168.5.6 \
  "cd ~/av_unified_mvp && python3 -c '
import yaml; p=\"config/system_config.yaml\"; c=yaml.safe_load(open(p))
c[\"llm\"][\"escalate_to_jetson\"]=False
open(p,\"w\").write(yaml.safe_dump(c, allow_unicode=True, sort_keys=False))
' && pkill -TERM -f modules.llm_engine"
```
