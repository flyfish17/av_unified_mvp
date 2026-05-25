# ASR FunASR 2pass spike plan（5/25）

> **状态**：纯计划。**未切分支、未动代码、未上 3588**。8 成把握达到才推进实施。
> **关联**：[语音模块评估](../eval/asr-module-eval-20260525.md) · [出差报告](../../OUT_OF_OFFICE_REPORT_20260521.md)

## 0. TL;DR

3588 当前 ASR 走 `in-process AutoModel(SenseVoiceSmall) CPU offline`，长跑 4 天 RSS 涨到 6.1 GB、错字率显著高于 Mac 同时段 transcript、无 partial 流式体验。

Mac 版（av_understanding_mac）走 `funasr 2pass docker websocket server`，质量与体验明显更好。

**Spike 目标**：在 3588 上跑通 funasr docker server + 改 audio_processor 走 websocket 客户端，达到与 Mac 版同档质量 / 拿到 partial。

**Spike 不目标**：调优 / 生产化 / 替代当前 in-process 路径（in-process 保留，多 backend 并存可切换）。

---

## 1. 验收准则（要 8 成把握达到才进 3588 实施）

| 维度 | 当前 in-process | spike 目标 | 验证法 |
|---|---|---|---|
| **partial 延迟** | 无 | 1-3 s 出第一段 partial | dashboard 端测 + ws message log |
| **final 延迟** | 15-30 s | 5-10 s（与 Mac 持平） | 时间戳对比 |
| **错字率** | 长句中段经常乱字 | 与同时段 Mac transcript 持平（≤ 1 处/100 字） | 人工抽 5 段对比 |
| **段开头乱码** | 频繁（"提因为他..." / "切入..."）| 消失 | grep 100 段统计 |
| **audio_processor RSS 24h** | 涨 ~1 GB | 稳态（涨 < 100 MB） | sustain_watch 曲线 |
| **server 内存占用** | N/A | < 4 GB（3588 总 16 GB，余量保护 audio/video/openvocab） | docker stats |
| **server CPU 长期均值** | N/A | < 60% 8 核（即 < 4 核满负载等价） | docker stats + uptime |
| **回滚速度** | N/A | < 60 秒切回 in-process | git checkout + supervisor restart |

**8 成把握门槛**：上述 8 项中至少 6 项 spike 前能通过桌面调研 / 第三方验证 / 文档确认（不需要实测，但要有充足证据），剩下 2 项可接受"上 3588 实测"风险。

---

## 2. ARM64 funasr 镜像可行性 — 三方案对比

| 方案 | 来源 | 工作量 | 风险 | 验证可信度 |
|---|---|---|---|---|
| **A. 官方 funasr/funasr** | Docker Hub `funasr/funasr` | 0 | runtime SDK 标签**只有 amd64**，2pass 服务镜像无 arm64 manifest | 🔴 5/21 调研确认不可直接 pull |
| **B. 第三方 ARM64 build** | `yaming116/fun-asr`、`harryliu888/funasr-online-server` | 0（如有 arm64 tag） | 第三方维护，未审计；docker.io 当前 3588 上 registry 不通 | 🟡 需先用 Mac 测 pull / 看 manifest |
| **C. 自建 aarch64 镜像** | 基于 FunASR runtime 源码 + 多架构 buildx | 1-2 天 | 编译依赖（torch arm64 wheel / onnxruntime arm64 / ffmpeg）| 🟢 最稳但工作量大 |

**Spike 选择路径**：
1. **先 B**：用 Mac 拉 harryliu888/yaming116 镜像看 manifest 是否真有 arm64 layer；如有，scp tar 到 3588 `docker load`（绕过 docker.io 不通）
2. **B 不成走 C**：在 Mac 上 `docker buildx build --platform linux/arm64 -t local/funasr-arm64 .`，scp 到 3588

---

## 3. 3588 资源预估（基于 docs/deploy/3588-npu.md + 实测）

**当前 3588 内存占用快照（5/25）**：
| 进程 | RSS | 备注 |
|---|---|---|
| audio_processor (in-process SenseVoice) | 6.1 GB | **若切到 docker，这块会大幅缩** |
| video_processor + YOLO | ~1.1 GB | 不变 |
| openvocab_filter + YOLO-World | ~1.5 GB（已加载后估） | 不变 |
| llm_engine + RKLLM daemon | ~2 GB | 不变 |
| 其他模块合计 | ~0.5 GB | 不变 |
| node-red + mosquitto + ollama 等 | ~0.8 GB | 不变 |
| **已占用** | **~12 GB / 16 GB** | mem_avail 当前 ~8.8 GB（含 cache 可回收）|

**spike 后预估**：
| 进程 | RSS | 变化 |
|---|---|---|
| audio_processor (websocket client only) | ~150 MB | **省 ~6 GB** |
| funasr/funasr-runtime container (server + SenseVoiceSmall + LM) | 3-4 GB（参考社区 issue）| 新增 |
| **净变化** | **省 2-3 GB** | 内存更宽松 |

**CPU 预估**：
- 当前 audio_processor 5.2% 平均（in-process）
- funasr server 跑流式 ~60-80% 单 SenseVoice 推理流（8 核环境约 1 核满）
- 加 audio_processor 客户端 ~2-3%
- **总 CPU 占用约提升 50-60%**，3588 8 核可承受

---

## 4. audio_processor backend 切换设计

### 4.1 复用 Mac 版代码（最小改动）

Mac 版 `modules/audio_processor/processor.py` 已经实现了完整的 `websocket_2pass` mode（参考 docstring 第 3-4 行）：
```python
self.mode = str(funasr.get("mode", "websocket_2pass"))   # 'websocket_2pass' | 'local_offline'
self.url = funasr.get("url", "ws://127.0.0.1:10095")
self.chunk_size = list(funasr.get("chunk_size", [5, 10, 5]))
# ... _start_websocket_2pass() + _fallback_to_local_offline()
```

3588 端 `modules/audio_processor/processor_arm.py` 是另一个文件，独立实现 in-process 路径。

**切换方案**（最小破坏 / 多 backend 并存）：

```
modules/audio_processor/
├── main.py                  ← 入口，按 env AV_ASR_BACKEND 选 backend
├── processor.py             ← Mac 原版，websocket_2pass + local_offline fallback
├── processor_arm.py         ← 3588 当前版，in-process SenseVoice CPU
└── (新增) router.py         ← 简单 dispatcher：env=sense_voice_arm → processor_arm,
                                                env=funasr_ws_2pass → processor
```

main.py 已经通过 `AV_ASR_BACKEND` 环境变量切（demo-start.sh line ~110 设置），加一个分支即可。

**改动量**：~50 行（router + main.py 路由 + processor.py 微调适配 3588 mic 路径）。

### 4.2 supervisor 不动

`main.py` MANAGED_MODULES 不变，audio_processor 始终是同一个子进程。只是该子进程内部走哪条 backend 由 env 决定。

---

## 5. 回滚 plan（关键 — 你说"有结点能回滚就好"）

### 5.1 回滚锚点（commit tag）

实施前打 tag：
```bash
git tag pre-funasr-spike-20260525 4ea2e92    # 当前 sprint tip
git push origin pre-funasr-spike-20260525
```

### 5.2 回滚步骤（任一时刻可执行 ≤ 60s）

```bash
# 3588 上
cd /home/firefly/av_unified_mvp
git checkout pre-funasr-spike-20260525  -- modules/audio_processor/
pkill -TERM -f modules.audio_processor.main    # supervisor 自动重拉 in-process 版
docker stop funasr-server                       # 可选 — 释放镜像内存
```

audio_processor 重拉走默认 env `AV_ASR_BACKEND=sense_voice_arm` → 回到当前长跑路径。

### 5.3 双 backend 并存 graceful 切换

实施后两个 backend 都在仓库里，env 切换即可。**不删除 processor_arm.py**。

---

## 6. spike 阶段步骤（Mac 阶段 → 3588 阶段）

### Phase 1 — Mac 桌面调研（不上 3588）
| Step | 动作 | 验收 |
|---|---|---|
| 1.1 | Mac 上 `docker pull yaming116/fun-asr` / `harryliu888/funasr-online-server` | 看 manifest 有 arm64 layer，pull 成功 |
| 1.2 | Mac 跑起 server，测 `ws://localhost:10095` 能 connect | curl / ws 客户端验 |
| 1.3 | 写一个独立 ws client 脚本（不上 supervisor），录一段 30s wav 喂进去 | 拿到 partial + final |
| 1.4 | 用同一段 wav 对比 Mac 现有 audio_processor 跑出的 transcript 质量 | 错字率 / 标点 / partial 时长 |
| 1.5 | docker save 镜像到 tar，scp 到 3588 待用 | tar 文件就位 |

**Phase 1 出口**：8 成把握判定（验收准则 8 项至少 6 项通过桌面验证）

### Phase 2 — 3588 实施（一次窗口，可回滚）
| Step | 动作 | 验收 / 回滚 |
|---|---|---|
| 2.1 | 3588 `docker load < funasr-arm64.tar` | image ls 出现 |
| 2.2 | 起 server: `docker run -d --name funasr -p 10095:10095 -v ~/models:/models ...` | docker logs 正常 / curl ws |
| 2.3 | 测 server 资源：`docker stats funasr` 30 min | RSS < 4 GB, CPU < 80% |
| 2.4 | 切 audio_processor backend：`AV_ASR_BACKEND=funasr_ws_2pass` env，pkill 重拉 | dashboard 转写出字 + partial |
| 2.5 | 跑 30 min 对比试验：同段话同时喂两个 backend，对比 transcript | 错字 / 延迟 / 内存对比 |
| 2.6 | 若任一验收不通过 → 触发 §5.2 回滚 | 60s 内恢复 |

### Phase 3 — 长跑切换决策
- 若 Phase 2 全通过 → 长跑切到 funasr backend，sustain_watch 继续观察
- 若部分通过 → 保留 spike 数据，回滚到 in-process，写 lessons-learned 入仓
- 若全失败 → 回滚 + 标记 spike 失败 + 写架构升级备选方案（Whisper.cpp arm64 / Paraformer 重新评估）

---

## 7. 风险点 + 应对

| 风险 | 概率 | 影响 | 应对 |
|---|---|---|---|
| 第三方 ARM64 镜像质量未审计 | 中 | 中（可能含 backdoor / 性能差） | 优先官方 + 社区 star 高的 / 自建 兜底 |
| 3588 docker.io 不通拉不下镜像 | 高 | 低 | 走 Mac docker save → scp tar 路径 |
| docker server + audio_processor 双开内存挤压 video/openvocab | 中 | 中 | Phase 2.3 资源测；超阈值不上 |
| funasr ws partial 在 dashboard 渲染逻辑跟当前 final-only 不一致 | 高 | 低 | dashboard 端 transcript_seq.js 已实现 partial 渲染（Mac 版用过），仅需打通 channel |
| 当前 4 天长跑数据未结题就切换 → 失去 in-process 真实续航上限 | 中 | 中 | sustain_watch 继续跑到 OOM 或 1 周稳态才切；切换前快照数据 |
| Phase 2.4 切换瞬间 ASR 链路中断影响 dashboard 体验 | 高 | 低 | 选业务低峰窗口执行；提前告知 |

---

## 8. 8 成把握 checklist

实施前，下述至少 6 项必须 ✓：

- [ ] **第三方 ARM64 镜像找到 ≥ 1 个**（B 方案）或已成功自建（C 方案）
- [ ] **Mac 上跑 server 成功 + 测出 partial**（Phase 1.2-1.3）
- [ ] **错字率 / 延迟桌面对比 Mac 现有版本无明显回退**（Phase 1.4）
- [ ] **3588 上 docker server 资源预估 ≤ 当前 audio_processor 节省量**（避免净增内存）
- [ ] **回滚步骤被独立验证一次**（在 Mac 上模拟切回 in-process）
- [ ] **dashboard 端 partial channel 实测可渲染**（Mac 上跑通后看）
- [ ] **sustain_watch 5/25 起 ≥ 24h 数据** — 拿到 in-process 退化基线
- [ ] **当前 sprint 有 commit tag 锚点**（pre-funasr-spike-20260525）

✓ 6/8 → spike 可在 3588 上实施
✗ 5/8 或更少 → 拆任务再调研 / 重新评估

---

## 9. 时间盒（spike 不超过这个时间）

- Phase 1（Mac 调研）：**1 天**（含找镜像 + 跑通 + 桌面对比）
- 8 成 checklist 复核：**0.5 天**
- Phase 2（3588 实施 + 验证）：**0.5 天**（含回滚演练）
- 总盒：**2 天**

超时即结题写报告，回滚到 in-process。

---

## 10. 不在本 spike 范围

- ❌ 替换 SenseVoice 为其他模型（Whisper / Paraformer 等）
- ❌ NPU 路径（sense_voice_rknn 已知幻听，5/18 已结论）
- ❌ ct-punc 替换（独立 sprint）
- ❌ dashboard UX 重设（Node-RED A/D 是另条线）

---

**下一步**：你看完后定 yes/no/改。yes 我开始 Phase 1（Mac 上 docker pull 调研，**不动 3588**）。
