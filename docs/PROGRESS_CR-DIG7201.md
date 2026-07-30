# CR-DIG7201-A 语音转写模块 · 进度台账（单一状态源）

> 终端每完成一阶段追加一行：`阶段X done @YYYY-MM-DD HH:MM  commit:<hash>  备注(含验收数据)`
> 主 Claude 读此文件 + `git log` 做阶段检测与推进；打回时在此写 fail 项。
> 分支：`feat/cr-dig7201-asr`（基于 stable-3588）。任务详情见 `../TASK_A_会议主机语音+纪要修复.md`。

---

## 阶段清单与状态

| 阶段 | 内容 | 状态 | 时间 | commit | 验收数据 |
|---|---|---|---|---|---|
| P0-a | 会议转写 profile + 纪要分段 | ✅ done | 2026-07-28 17:45 | ce2cb00 | 2万字 37.4min 完整纪要；短会 5.5min 无回归 |
| P0-b | 纪要上 NPU（rknn-llm） | ✅ done + 已上线 | 2026-07-29 14:15 | 84043af | 3588 切 meeting_asr 常驻纪要机；1.7B 全程端到端 2万字 535s 高质量纪要 |
| P1 | 组播收包离线验证（net_audio_capture + mock） | ✅ done | 2026-07-29 11:15 | 20e04a5 | Mac+3588 跨网 3 路全对；8 路满载数据见日志 |
| P2 | 会议主机真机联调（8 路话筒区分） | ⏸ 挂起：主机发错型号 | 2026-07-29 | | 工厂补正确主机；需求升级为多源选择器（见待决4） |
| P3 | 纪要按发言人分段 | ✅ done | 2026-07-29 11:35 | f83e62f | 纪要 3 要点正确标注发言人；dashboard 分色可视化通过 |

## 进度日志（追加式）

<!-- 终端在此追加，最新在上 -->

- **全音频落盘导出 done @2026-07-30  commit（processor.py+main.py）**（生产版，替代内存 5min ring）
  - 需求：导出原音要**整场会议全部**音频（原内存环形 buffer 只留最近 5min）。用户拍板：每场会一个文件、5G 上限滚动删最老。
  - 内存 ring → 磁盘落盘：采集边写 `data/audio/session-<ts>.pcm`，一场会（processor.start→stop）一个文件。不在内存存全量（几小时几百MB、5G=5G内存会 OOM）。5G 总上限滚动删最老会话（保当前，约 44h）。
  - 导出 `/audio/export.wav` 流式读磁盘加 WAV 头；WAV 4G(RIFF 32-bit)硬上限，超 4G(≈35h)按 `?part=N` 切片 + `X-Audio-Parts` 头——**每场会一文件<4G 正常不触发，纯超长防御**。ARM 路径 getattr 回退旧 buffer 不坏。前端零改动（已是 `<a download>` 原生流式下载）。
  - **验收（3588 真机，重启走 SIGKILL 保 funasr）**：会话文件线性增长 117s→3.67MB（32KB/s，**无 9.6MB=5min 封顶**）；导出 **163.5s 全程音频** 16kHz 单声道 WAV 正确、单片、filename 正确；单元测 WAV 往返 + 5G 滚动删最老保当前均过。
  - **磁盘**：3588 /home 151G 可用，5G 上限占比小。会话文件在 `data/audio/`（gitignore，重启保留）。
- **DECISIONS 第7条 前端卡片按 profile 显隐 done @2026-07-29 14:55  commit:d484373**（已上线生产）
  - server.py index 注入 app_profile（env>config>full）；dashboard.html body 承载；dashboard.js `applyProfileVisibility` 用 GridStack removeWidget 隐藏非白名单卡（无网格空洞）、不写 VISIBILITY_KEY（形态决定非用户偏好）。
  - meeting_asr 白名单=转写卡（纪要弹窗+发言人分段都在卡内）；隐藏其余 10 张（nodered/video/intent/scene/husion/openvocab/quick-control/lan-scan/add-source/online-stream）。full 零回归。
  - **Chrome 实测**：meeting_asr（5052）+ 生产 5050 主卡片区只剩转写卡界面干净；full（5051）Node-RED/视频墙等全卡保留。生产已部署重启（SIGKILL 保 funasr）。
  - ~~留观：左侧导航仍全显~~ → 已解决（下条，方案一）。
- **左侧导航整栏隐藏 done @2026-07-30  commit（dashboard.html 模板）**（第7条延伸，用户选方案一）
  - 纪要机是单页产品，左侧多视图导航整栏多余（含一排离线模块噪音）。纯 CSS：`body[data-app-profile=meeting_asr]` 改 grid 单列 + 去 nav 区域 + `nav{display:none}`，主区占满无左侧空白。复用 data-app-profile，零 JS。full 零回归。
  - **对比过方案二（过滤条目）**：方案一纯 CSS ~5 行 vs 方案二 JS ~15-25 行+维护 nav 白名单；单页产品不需多视图切换器 → 方案一更小更适合。
  - **部署**：仅改模板，TEMPLATES_AUTO_RELOAD 生效，scp 到生产刷新即见效，**无需重启 supervisor（零转写中断）**。生产 5050 已验证渲染新 CSS、200。
  - 注：本轮 Chrome extension 断连未截图，靠 curl 验证 HTML/CSS 就位 + 逻辑审查；视觉效果待浏览器刷新确认。

- **meeting_asr 常驻纪要机上线 done @2026-07-29 14:15  commit:84043af 4e2fa13**（DECISIONS 决策 1-5 执行完成）
  **切换动作（3588 生产，62 demo 已确认可用无空窗）**：
  - 代码：main.py meeting_asr 排除 llm_engine（省 2GB IOVA）；server.py chunk 阈值/大小可配（1.7B ctx 4096 保护）、merge+短路径 summary prompt 撑实（禁空话套话）；启动脚本 EXPECTED_MODULES 9→6。git archive 同步到生产 /home/firefly/av_unified_mvp（不动 gitignore 的 config）。
  - config：`app_profile: meeting_asr` + `llm.summary`{backend rkllm, model qwen3-1.7b, url/unload_url, chunk_threshold/size 3500}。原 config 已备份 .bak-cr7201-*。
  - **关 thinking**（关键）：`/home/firefly/models/Qwen3-1.7B/model_config.json` = capabilities:[instruct] + sampling.temperature 0.3。实测 completion_tokens 295→8、generate 26s→0.7s（qwen3 默认 thinking，`/no_think` 对该 server 无效，per-request temperature 也不生效，必须走 model_config.json）。
  - **切换手法**：SIGKILL 老 supervisor+module（绕过 supervisor.stop() 的 docker stop funasr，保住 funasr/mosquitto）→ systemctl restart av-demo（systemd 接管起 meeting_asr）。funasr Up 全程未掉。
  **验收**：6 模块（audio/system/network×2/scanner/husion/control，无 video/keyframe/openvocab/llm_engine）✅；dashboard 5050=200 ✅；audio_processor 麦克风+FunASR 正常 ✅；NPU 空闲无意图 daemon ✅；**端到端 2万字→NPU 1.7B 535s（8.9min）出高质量纪要**：7 段、摘要有实质内容（撑 summary 生效）、要点带发言人归属、8 要点 6 关键词字段齐、thinking=False ✅。
  **耗时说明**：535s > 决策5 基线 6.2min。主因 chunk 3500（防短会超 4k ctx）→ 7 段 + summary 撑长。**取舍**：3500 保短会（15-30min，纪要机最常见场景）ctx 安全余量；2万字≈3小时长会 8.9min 罕见且会后非实时可接受。想压速可把 chunk 提到 4000（P0-b 验证过 2756tok<4096 安全，减 1 段）——留作可选优化，未擅自改。
  **产品化 SOP 待补**（决策4，现未装）：① rkllm server systemd 自启（现 nohup，重启掉）；② `ip_unprivileged_port_start=1000`（组播 P2 用，runtime 设置重启失效）；③ model_config.json 关 thinking 纳入部署清单。
- 阶段P3 done @2026-07-29 11:35  commit:f83e62f（P2 被跳过原因见下条）
  ① 纪要发言人归属：带 [话筒N] 标签的 3 人对话 → 3 要点各自正确标注（预算明细→话筒1、安装协调→话筒2、验收标准→话筒3），Mac qwen3.5:4b 实测 ✅
  ② dashboard：mic_id 存在时按发言人切段 + 8 色板分色标签，本地麦行为不变；Chrome 可视化验证通过 ✅
  ③ 导出原文/生成纪要取文都带 [话筒N] 前缀
  注：dashboard 的 transcript handler 由模块 discovery 公告注册——独立 web 实例测试时需先注入 discovery mock（已踩坑记录）。
- 阶段P2 ⚠️ 阻塞 @2026-07-29：3588 上 8 端口被动探测 30s **零包**。会议主机（据 7-28 确认已上电走组播）当前没有发流到 3588 网段——需现场确认：① 主机语音输出是否开启；② 是否同网段/VLAN；③ 交换机 IGMP snooping 是否拦组播。接收端软件链路已由 P1 mock 全量验证（Mac→3588 跨网组播都通），主机一旦发流即可联调。探测脚本：`/tmp/cr7201/probe_multicast.py`。

- 阶段P1 done @2026-07-29 11:15  commit:20e04a5
  **验收实测**：
  ① Mac 本地 + **Mac→3588 跨网组播**：3 路不同 TTS wav → 3 路 final 全对、无串路、ITN 标点正常、mic_id/speaker/seq_id 正确（`seq_id=mic_id*10000+n` 防跨路冲突）✅
  ② 模块自身开销：8 路收包+降采样+静音门仅 **~28% 单核**（3588，很轻）✅
  ③ **并发上限（生产全开：视频+意图链在跑）**：3 路同时讲话正常；**8 路持续同时讲话不可持续**——funasr-wss 372% + ollama 233% → load 24+，decode 积压（85s 零新 final），停止后 ~4 分钟自行消化恢复，**5050 全程 200**。真实会议 RMS 静音门下同时活跃话筒通常 ≤3，可承受；meeting_asr 形态（视频关+意图关）余量更大，P2 复测。
  **两个系统性发现**：
  a) **测试 final 流进生产意图链**（av/audio/command_punctuated → llm_engine → ollama 每条 final 一次推理，实测 ollama 被打到 300%）→ meeting 产品必须断开意图链 = 待决项 2 的实测佐证。
  b) FunASR 2pass 的 final 靠 server 端 VAD 检出**尾部静音**结算——静音门关门/断流时必须补 ~1s 静音帧，否则永远没有 final（实测踩坑已修）。
  **部署注记**：协议端口 1000-1007 是特权端口，3588 已 `sysctl net.ipv4.ip_unprivileged_port_start=1000`（**runtime 设置，重启失效**，需入部署 SOP）；pgrep/pkill 防自匹配字符类会被"模式里含目标明文"绕过（`.mai[n]` 内含 capture 明文），远程清进程后用无模式 `ps|grep` 复核。

- 阶段P0-b done @2026-07-29 10:30  commit:d87be0c（后端切换代码）
  **部署（已装，用户授权）**：RKLLM-API-Server（GatekeeperZA）@ 3588 `:8000`，`/home/firefly/RKLLM-API-Server` + venv `/home/firefly/rkllm-server-venv`，librkllmrt 用板上已有 1.2.3（`RKLLM_LIB_PATH`，未动 /usr/lib、未装 systemd → **重启不自启，产品化时补**）。模型 `/home/firefly/models/`：qwen3-4b-16k（W8A8_G128 5.3G）、qwen3-1.7b（w8a8 2.4G，ctx 上限 4k）、qwen2.5-1.5b（旧 PoC）。
  **验收实测（video 冻结=meeting_asr 等效，已恢复）**：
  ① **1.7B 全程 NPU：2 万字 374.2s（6.2 分钟）**，6 段+汇总 7 请求零崩溃、8 要点 5 关键词、unload 自动执行 ✅（CPU P0-a 2245s 的 1/6）。目标 <3min 未达，如实回报：**4B 级 NPU prefill 实测 27 tok/s（G128）**，预研 130 tok/s 是 1B 级数字；1.7B prefill 93 tok/s、decode 5.6 tok/s。
  ② 质量：4B 分段提取最好（120组/270方言等细节全保）但全程 20min 级 + 长 prompt 偶发 SIGSEGV（1 次）→ **否决全程 4B**；qwen2.5-1.5b 质量掉档否决；**1.7B 要点保住数字/专名（54元/点、270余种），merge 出的 summary 偏空泛** → 改进方向：1.7B 分段+4B 汇总（est 9-10min）或 merge prompt 调优。
  ③ 16k ctx：4B 16k 可装载；1.7B 转换上限 4k，分段设计够用，但**短路径（≤8000字单次调用）在 4k ctx 会截断**（当前 rkllm 配置下短会应下调阈值或走 4B/ollama）。
  ④ **NPU 时序冲突实测确认（本阶段最重要发现）**：RK3588 NPU IOMMU IOVA 域 ~4GB；生产 llm_engine 的 1.5B 意图 daemon 常驻占 ~2GB → 4B 装载直接失败（`failed to allocate IOVA -12`，dmesg 实证），杀 daemon 后成功；1.7B(2.3G) 与 daemon 并存也贴顶。已实现纪要后自动 unload；**meeting_asr 产品形态 llm_engine 需切 ollama 或不起 → 待决**。
  **过程教训（重要，防复跑踩坑）**：/tmp/cr7201 测试实例代码陈旧导致两轮"e2e"实际跑在 ollama CPU 上（所谓"4B e2e 20min+第6段崩"= ollama 在内存压力下被断连，非 rkllm 崩）；**有效 NPU 数据以直连 :8000 的 Perf 日志为准**。部署/验证前先 `grep` 确认目标机代码版本。

- 阶段P0-a done @2026-07-28 17:45  commit:ce2cb00（主体 b5a885c）
  **验收实测（3588 真机，video_processor/openvocab SIGSTOP 冻结 = meeting_asr 等效，测完已 SIGCONT 恢复、5050 全程 200）**：
  ① 2 万字 `/tmp/dingna_transcript.txt` → **2245.3s（37.4 分钟）** 出完整纪要：6 段、8 要点、7 关键词、留档 summaries/ ✅ 无报错
  ② 短会回归：3000 字 → 327.2s（5.5 分钟）单次调用，字段齐 ✅
  ③ 目标"会后几分钟"CPU 上**达不到**，如实回报：瓶颈 = prefill 8-9 tok/s / decode 2.5-2.7 tok/s（冻结视频后 bench 实测，Mac 1640 tok/s 的 ~1/190）→ 印证 P0-b 上 NPU 是唯一根治
  ④ supervisor profile 装配验证（Mac）：meeting_asr=7 模块（去 video/keyframe/openvocab）、默认 full=10、非法值报错
  **过程要点**：qwen3.5:4b 输出多元素 JSON 数组系统性坏格式（首条后闭合数组，4 次中 3 次）→ LLM 输出整体改行格式+代码解析，Mac 3+1 次全绿零重试；timeout 公式按 3588 实测速率重定（4000 字段 605s）；`app_profile` 进 example config（system_config.yaml 本身 gitignore，产品机部署时本地打开 meeting_asr，Mac 本地配置已还原不影响 demo-mac）
  **P0-b 预备已并行完成**：板上发现 RKLLM SDK 1.2.3 + 上轮 PoC ctypes daemon（/home/firefly/rkllm-poc/，stdin/stdout JSON 协议可复用）；Qwen3-4B-rk3588 w8a8-opt1-16k（5.3GB）hf-mirror 断点续传下载中（Mac scratchpad）

- 2026-07-28 主 Claude：任务单 + 提示词就位，分支待建，等终端开工。已确认：分支 feat/cr-dig7201-asr from stable-3588；会议主机已上电走组播；3588=16G；测试素材 /tmp/dingna_transcript.txt 已在板上；NPU 预研完成（可行，路径见 TASK_A P0-b）。
- 2026-07-28 主 Claude：**NPU 部署指引已备** `docs/NPU部署指引_CR-DIG7201.md`（终端做 P0-b 时照此，已含三步部署 + 接口差异坑 + unload 解 NPU 争抢 + 必测项）。RKLLM v1.3.0 确认支持 qwen3.5；RKLLM-API-Server 提供 OpenAI 兼容 API + /v1/models/unload。

## ⚠️ 待决项

<!-- 卡点/需用户决策写这里 -->

1. **纪要模型定型**（P0-b ②）：A=1.7B 全程（6.2min，质量中，summary 偏薄）；B=1.7B 分段+4B 汇总（est 9-10min，质量高，4B 有偶发 SIGSEGV 风险）；C=先 A 上线、B 做后续优化。终端建议 **C**。
2. **meeting_asr 形态 llm_engine 去向**（P0-b ④，NPU IOVA 冲突）：意图识别切 ollama CPU（`AV_LLM_BACKEND=ollama`）还是 meeting 产品直接不起 llm_engine？纯转写产品用不到意图控制的话建议后者。
3. rkllm API server 未装 systemd（重启不自启）——产品化部署 SOP 时补，还是现在就装？
4. **音频多源选择器**（2026-07-29 用户提，P2 现场触发）：主机发错型号（发来的是别的设备，网上抓到的 224.1.1.32 RTP 流是硬盘录像机分布式盒子，与转写无关），工厂将补正确会议主机。需求升级：视听程序支持音频源可选——**网络组播抓包 / 线路输入(line-in) / USB**，像讯飞一样"扫描后列出、标出已连接的、选中连接"，≥2 源可选。工作量评估见下方专节，待用户拍板分阶段。
    - 硬件已核实（3588）：card0 ES8323 板载 line-in（空闲，留给主机模拟 Audio out）、card2 C920 USB 麦（生产在用）、网络组播（P1 net_audio_capture 已通）——三源齐备不冲突。

## 音频多源选择器 · 工作量评估（2026-07-29）

现有积木：audio_processor（本地 sounddevice 采集+FunASR，支持 start/stop）、net_audio_capture（P1 组播 8 路）、main.py `audio.source` 静态开关。目标增量 = 运行时"扫描→列表→选中→连接"。

| # | 工作项 | 人天 | 要点/风险 |
|---|---|---|---|
| 1 | 音频源枚举 API | 0.5-1 | 用 ALSA 层（/proc/asound/cards+arecord -l）比 sounddevice 可靠（实测 sounddevice 漏列 C920）；区分 USB(usb- 路径)/line-in(rockchip/es8388)；标注占用状态 |
| 2 | 源活性探测（"已连接"高亮） | 1-1.5 | line-in/USB 短录 0.5s 算 RMS；组播 join 抓 1-2s 看包（P2 probe 现成）；**被占用设备不能重开**，要读现有流 |
| 3 | 运行时切换采集源 | 1.5-2 | ⚠️最难。line-in↔USB 同进程切 device（小改）；本地↔组播跨进程（audio_processor vs net_audio_capture 两模块），需 supervisor 协调或统一"源管理器"抽象 |
| 4 | 前端选择 UI | 1 | dashboard 音频源面板：列表+类型图标+信号/已连接标记+选中；复用 discovery 面板风格 |
| 5 | 联调+边界 | 0.5-1 | USB 热插拔、切换时转写连续性、错误提示 |

**分阶段建议**：
- **阶段1 MVP（~3 天）**：枚举+前端选择+line-in/USB 运行时切+组播作固定选项。满足"≥2 源可选、能选中连接"。
- **阶段2 讯飞级（+2-3 天）**：活性探测自动高亮+实时电平条+统一源抽象（本地/组播无缝切）。
- 依赖：line-in 需正确主机到货 + 物理接线（主机 Audio out→3588 card0）才能端到端实测；软件可先用 USB/组播验证。
