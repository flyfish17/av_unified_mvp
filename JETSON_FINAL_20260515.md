# Jetson Orin Nano 8G · 角色收尾与硬件价值评估

**日期**：2026-05-15
**前置数据**：`OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md`（9.5h sustain）
**决策（5/15）**：Jetson 角色封板，不再投入；本文档为终态归档。

**5/18 更新**：方向调整为 **独立支线**（非"主线投入" / 非"完全封板"）。
- 视频深思路径维持现状（偶发单路场景描述），不投新工程
- **新增任务**：验证 Jetson CUDA 上语音模块（sensevoice / FunASR）的实际表现，出报告 — user 记得效果不错，需实测确认
- 独立 Claude 窗口运作，使用 `docs/handoffs/jetson-side-window-prompt.md` 的 system prompt
- 不动主线 sprint branch，结果回报到 `docs/reports/2026-06+/`

下文 §1-§5 内容保留作为 5/15 时点状态参照。

---

## 1. 当前部署快照（2026-05-15 上午 mqtt discovery 实测）

| 模块 | 角色 | 实测状态 |
|---|---|---|
| `scene_analyzer` | VLM 推理（订阅 `av/video/key_event` → 发 `av/video/scene_analysis`） | ✅ 心跳活 |
| `llm_engine` | escalate 兜底（订阅 `av/llm/escalate`） | ✅ 心跳活，enabled |
| `control_dispatcher` | 指令下发（订阅 `av/control/cmd`） | ✅ 心跳活，但 3588 主线已用本地 dispatcher，Jetson 这份是冗余副本 |
| `system_info` | host_stats 心跳（`av/system/host_stats`） | ✅ 心跳活，mem=98% / cpu=58.8% |

外部依赖：
- ollama on `:11434`（VLM 模型 `qwen2.5vl:3b`），keep_alive=10m 配置但**实测没生效**
- mqtt client 跨机订阅 3588 broker `192.168.5.6:1883`

无 SSH 权限（红线），所有观察通过 MQTT 间接进行。

---

## 2. 视觉深思 9.5h 实测边界

完整数据见 `OVERNIGHT_REPORT_VLM_SUSTAIN_20260514.md`。摘要：

```
duration:        570.5 min (9.5h)
key_event 入:    747 (4 cam × 0.33/min, idle_seconds=180)
scene_analysis 出: 28 (0.05/min, drop rate 96.2%)
vlm_latency_ms:  p50=77550  p95=78291  p99=104166  max=104166
覆盖分布:        28 个全在 USB罗技C920 单路, 其余 3 路 9.5h 内 0 scene
Jetson mem:      min 97.1% / p50 98.1% / p95 98.3% / max 98.5%
3588 mem:        min 44.7% / p50 45.6% / max 46.2%（健康）
```

**Root cause**：Jetson 8G unified memory 被 `qwen2.5vl:3b` 模型 + ollama context + 系统占用顶到 ≥97%，scene_analyzer 的 `mem_min_mb=400` 守门触发 96% 推理被 drop。**这不是 keyframe 节流参数能解决的问题**。

**调参 commit `c60a666`**（idle_seconds 60→180 / conf_threshold 0.40→0.55）只降低了 3× 入口压力，没改变 drop 率本质。

---

## 3. 用户可感知的稳定能力（客户演示口径）

| 能力 | 稳定性 | 适合演示陈词 |
|---|---|---|
| **偶发单路场景描述**（USB罗技C920） | 黎明时段较高（实测 9.5h 中黎明 07:xx 突现 18 个事件，其它时段稀疏） | "对单路监控做不定时智能巡检，遇到值得描述的画面生成中文场景报告" — 不承诺连续覆盖 |
| **escalate llm_engine 兜底** | 持续在线（3588 本地 LLM 返回 null 时 escalate 到 Jetson） | 不直接演示，作为后台能力提及"复杂语义有备份链路" |
| **host_stats 心跳** | 30s 间隔，稳定 | dashboard 可见 Jetson 健康状态 |

**不演示**：
- 4 路并行场景描述（实测 75% 路径 9.5h 内 0 输出）
- 实时场景理解（latency 78s × 队列堆积 → 用户体感慢）
- 任何对 VLM 输出准确性的细节追问（模型规格太小）

---

## 4. 硬件价值评估

### 4.1 Jetson Orin Nano 8G 真实能力边界

**适合**：
- 单路 VLM 推理（量化后 3B 级别）
- 不占大量内存的边缘任务（mqtt 桥、转写中转、轻量控制）
- CUDA 加速的轻量 CV 任务（YOLO 等）

**不适合**：
- 多路并行 VLM（unified memory 8G 顶不住 4 路 work set）
- 7B+ 大模型推理（即便 q4 量化也接近内存上限）
- 长 context 对话（KV cache 撑爆 mem）
- 任何需要"内存有余量"的稳态服务

**根本约束**：unified memory 架构 + 8G 总量。模型一旦加载，几乎无释放窗口（`keep_alive` 实测无效）。

### 4.2 与替代载体的横向对比

| 载体 | VLM 适配 | 不占内存能力 | 国产化 | 价格段 |
|---|---|---|---|---|
| **Jetson Orin Nano 8G**（当前） | 单路勉强 / 多路不行 | 适合 | ❌ NVIDIA 美国 | ¥3.5k |
| **3588 NPU**（当前） | NPU 跑 1.5b 量化勉强 / 3b 以上不行 | 适合 | ✅ Rockchip | ¥1.5k |
| **Mac mini M2/M4**（推荐替代） | unified memory 16-32G，3b-7b VLM 流畅多路 | 适合 | ❌ Apple 美国 | ¥4-6k |
| **x86 + RTX 4060/4070 工作站** | VLM 多路充裕 | 重资产 | ❌ Intel+NVIDIA | ¥10k+ |

**结论**：
- 如果在意**国产化**：3588 NPU 是合理选择，VLM 路线本就不该走 Jetson（避免供应链依赖）
- 如果**不在意国产化**且追求 VLM 多路 / 大模型：**Mac mini 是性价比最高的边缘载体**（unified memory + Metal 加速 + 生态成熟）
- Jetson Orin Nano 8G 在 av_unified_mvp 这个场景里**位置尴尬**：不够大跑不动 multi-cam VLM，国产化又不算

### 4.3 Jetson 的"剩余价值"候选

如果不立刻下机，Jetson 可承担的不占内存任务（不需要再开发）：
- **escalate llm_engine 兜底**（当前在用）
- **mqtt 桥接**（跨子网中继）
- **node-red 二号节点**（备份 3588 上的 Node-RED）
- **纯语音转写中转**（如果未来需要 Jetson 上跑 sensevoice/whisper 量化版）

**这些都是"补位"角色，不是主线**。

---

## 5. 封板结论（5/15 → 5/18 更新为"独立支线"，见文首 5/18 更新）

1. **Jetson 在 av_unified_mvp 中的定位**：视频解析（VLM 偶发偏向单路），不投入新开发
2. **不做的事**：
   - VLM 模型替换 3b→1.5b（不解决 unified memory 根本问题，且 1.5b 输出质量下降不值）
   - scene_analyzer per-camera round-robin（治标不治本）
   - 任何让 Jetson 承担更多主线职责的改动
3. **保留的事**：
   - 偶发单路 VLM 推理（客户演示口径里的"智能巡检"）
   - escalate 兜底链路（3588 本地 LLM 失败时的 fallback）
   - 系统心跳（dashboard 多机健康展示）
4. **未来重启 Jetson 项的条件**：
   - 项目获得新硬件预算 → 直接换 Mac mini / 工作站，不在 Jetson 上加钱
   - 出现 Jetson 专属优化（如 TensorRT-LLM 让 3b 模型 mem 占用减半）→ 重评估

---

## 6. 已知坑（备查）

| 现象 | 原因 | 处置 |
|---|---|---|
| ollama `keep_alive=10m` 不生效 | 整夜 mem 稳态 98%，应周期性下降但没有。怀疑 ollama 进程层泄漏 or 参数传递有误 | 不深究，不在主线 |
| scene_analyzer 4 路只覆盖 1 路 | scene_analyzer 单 worker + throttle + inflight_skipped 丢路 | 不做 round-robin（dec.4.2） |
| 无 SSH 权限 | 没有 Jetson 密码（user 也不维护这个） | 所有诊断走 MQTT；如需 ssh 找 user 现场配合 |
| 3588 上 `control_dispatcher` 与 Jetson 上副本同存 | 历史架构（早期 dual 部署），现在 3588 主线主导 | 不动 Jetson 副本，不重复触发；后续解耦时统一回 3588 单点 |

---

**归档完成。后续 Jetson 相关动作走"补位"思路，不做主线投入。**
