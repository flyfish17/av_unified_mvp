# 主 Claude ↔ 终端 · 决策与推进同步（单一同步点）

> **终端每次开工先读此文件**拿最新决策，再动手。
> 主 Claude 写"已确认可推进"（终端直接执行）；产品/商业决策由用户拍板后主 Claude 誊录到此。
> 最新在上，带日期。这样决策不靠用户逐条口头转达 → 长程协作提速。

---

## 🧭 当前状态快照（清理上下文后，新会话从这里恢复全局）

**2026-07-30（纪要机线梳理 · 用户拍板：收尾后暂停等主机）**
- **结论：无 8 路主机的现在，纪要机功能已全部具备**，剩余全是"等真机"项。软件侧收口清单：
  - 转写链路：单麦 2pass 实时转写 + 讲解稿式分段 ✅ · 双倍转写已修（a1cf7ec，已部署+目检待确认）✅
  - 纪要：NPU 1.7B，2 万字 8.9min 结构化纪要（分段/要点/发言人归属）✅ · thinking 已关 ✅
  - 发言人区分：8 路 mic_id 硬分离已做（P3）✅（触发条件=组播音频，等主机）；CAM++ 软分离停在 POC，不进产品
  - 界面：卡片按 profile 显隐（d484373）✅ · 左侧导航整栏隐藏（1b057a7，终端 7/29）✅
  - 导出：原文 .txt ✅ · 原音 WAV（:5052）✅
- **进行中（唯一）**：终端·保存全音频——现 300s 环形 buffer（processor.py:96）改全程保存。3588 现场还是 300s，未落地。
- **✋ 已拍板：全音频落地并验证后，纪要机线 pause，等主机到货再启**。不再加新功能、不做可选优化（chunk 4000 等一并冻结）。
- **等主机后的实机测试清单（重启时从这里接）**：① 真机组播 8 路收包（P2 曾 30s 零包，需现场排查）② 发言人分段分色+纪要归属真机验证 ③ audio.source 切 [mic, net_multicast] ④ 长会全程音频导出 ⑤ 产品机成型 → 用户录视频 + 主 Claude 推广文件。
- mock 路径备用：`scripts/mock_meeting_audio.py --ch 0:a.wav --ch 2:b.wav`（无主机也能验发言人链路，需先开 net_multicast）。

**2026-07-29**
- **CR-DIG7201-A 纪要机**：开发(P0-a/P0-b/P1/P3)+ 落地 + 端到端验收**全部完成**。3588 已切 meeting_asr 常驻纪要机（6 模块、NPU 1.7B、2 万字 8.9min 高质量纪要带发言人）。
- **前端界面**：✅ 第 7 条完成（commit d484373）——meeting_asr 只显转写卡（含纪要+发言人功能），无关 10 张隐藏、GridStack 重排无空洞、full 零回归。客户界面已纯净。
- **双倍转写修复**：✅（commit a1cf7ec，已部署 3588 + 推 GitHub）——根因：audio_processor 与 net_audio_capture 都声明 channel=transcript，聚合 SSE dispatcher 对每个 handler 各调一次 tickerForward → 转写卡每句 append 两遍。改为每事件转发一次。3588 备份 `dashboard.js.bak-20260729`；Cache-Control: no-cache，浏览器普通刷新即生效。**待用户下次开 dashboard 刷新后目检确认单倍**。
- **进行中**：无（纪要机开发+落地+验收+界面全部收口）。剩 = 用户验收客户体验 + 等正确主机。
- **等硬件**：正确会议主机 ~3 天到 → 真机组播完整验证 → 产品机成型 → 用户录视频 + 主 Claude 配推广文件。
- **产品定位**：3588=纪要机 · 62 湖森 HDC=视听 demo · Mac Studio(M3U)=高算力/研发 · MacBook Pro(M1Pro 16G)=短会/验证机。
- **diarization**：POC 验证软件方案可用（vault [[POC-发言人区分-软件方案验证]] + GitHub av_understanding_mac poc 分支 0ec8777）。产品走 FunASR CAM++；用户回家 MacBook Pro 验 CAM++ 中文效果（短音频）。
- **恢复入口**：本文件（决策/完成/待办/约束）+ `PROGRESS_CR-DIG7201.md`（进度）+ `TASK_A_...md`（任务）+ `NPU部署指引...md`（NPU）。vault 全局见 [[02-地/项目/CREATOR总部-AI三方案产品化]] §六。
- **loop**：盯前端修复中（ScheduleWakeup prompt 自带背景；清理后若没自动续，`/loop` 重启即可，背景全在这些文件）。

---

## 🎉 已完成验收（2026-07-29）

- **3588 meeting_asr 纪要机端到端验收通过**（台账 1bc4926）：决策 1-6 全落地；6 模块常驻、dashboard 200、麦克风+FunASR 正常；2 万字 → NPU 1.7B **535s(8.9min)** 高质量纪要（7 段、8 要点、发言人归属、字段齐）。
- **关键优化：关掉 1.7B thinking**——qwen3 默认开，白烧 token；改 model_config.json 后 completion_tokens 295→8、单次 generate 26s→0.7s。**纳入部署清单**。
- 切换保住 funasr（SIGKILL 绕过 supervisor stop() 的 docker stop，funasr 全程 Up）。
- **卖点数据更新**：会后出纪要 = 15-30min 短会更快 · 2 万字(约 3h)长会 8.9min。对外表述可用"**会后 10 分钟内本地出结构化纪要**"。

## 💡 可选优化（主 Claude 拍板，终端确认后可推）

- **chunk 阈值 3500→4000**：压 2 万字长会 535s→~6min。**分析纠正**："护短会"理由不成立——短会（<7000 字）在 3500/4000 下分段数相同，**4000 无短会代价**；且 4000 字≈2756 token<4096 ctx（P0-b 已验证安全）。**前提**：终端确认短会分段数确实不变，则提 4000 纯赚长会提速。非必须（8.9min 对 3h 长会已可接受）。

## ✅ 已确认可推进（终端直接执行）

### 2026-07-30
8. **保存全音频**（进行中）：300s 环形 buffer → 全程保存，`/audio/export.wav` 能导整场。注意 3588 内存/磁盘约束：长会 16K 16bit ≈ 1.9MB/min（3h ≈ 350MB），**别全放内存，落盘增量写**。完成验证后：**提交 + 部署 3588 + 在本文件勾掉本条 → 纪要机线即刻 pause**（用户已拍板），不再接新活，等主机。
7. **前端卡片按 profile 显隐（客户体验，高优先）**：dashboard 卡片现为静态 12 张，meeting_asr 只关了后端模块、**前端仍显示全部**（视频/Node-RED控制/场景/湖森/快捷控制/局域网扫描/添加源等无关卡空着无数据）。**修**：前端读 `app_profile`，meeting_asr 下只显纪要相关卡（transcript/纪要/发言人分区），无关卡自动隐藏。**纯纪要产品出厂界面就该干净，不让客户手动关**——这是"标准2：设置类模块混入显示卡区分"的前端落地。修法：前端过滤 `data-module-id`（半天）。**客户验收前应弄干净。**
   - **meeting_asr 保留**：`overview-transcript`（转写）+ 纪要/发言人分区卡（P3 的分段+summary 弹窗）。
   - **meeting_asr 隐藏**：`overview-nodered`(控制) / `overview-video` / `overview-intent`(意图,llm_engine已不起) / `overview-scene` / `overview-husion` / `overview-openvocab` / `overview-quick-control` / `overview-lan-scan` / `overview-add-source` / `overview-online-stream`。
   - 实现建议：后端把 `app_profile` 注入模板或出 `/api/profile`，前端按 profile 白名单显隐；full profile 行为不变（零回归）。

### 2026-07-29
1. **3588 直接切 `meeting_asr` 常驻纪要机**（不切回，全功能 demo 改用 62 湖森 HDC）。**前提**：切前确认 62 demo 可用（用户已确认 62 运行正常），别 demo 空窗。
2. **模型定型 = C**：1.7B 全程先上线；**先调汇总 merge prompt 撑起 summary**（1.7B summary 偏薄），4B 混合作后续优化，不急。
3. **llm_engine = 不起**（纯纪要产品用不到意图控制，省 2GB IOVA，彻底解 4B 装载冲突）。
4. **systemd 自启 + `ip_unprivileged_port_start=1000` = 归产品化 SOP**，现在不装。
5. **端到端验证**：转写文本 → NPU 1.7B 纪要 6.2min 稳定；Mac 版补验全链路（音频→FunASR→纪要）。
6. **发言人分区**：有 8 路会议主机时用话筒号硬分离（P3 已做）；无 8 路时走 **FunASR CAM++** 软件 diarization（复用 NPU 链路，非 transcribe.cpp）。P1 收包留 CAM++ 接口余地，P3 别现在扩。

---

## ⏳ 待用户拍板（主 Claude 提炼，勿自行执行）

- 视频分析机（net-6000 `video_analysis` profile）立项时机——等方案③/李总样机。**立项时先验算力**（像纪要一样先摸 NPU/CPU 速度，别假设能跑）。
- MacBook Pro 纪要机定位——长会曾报错（弱机），建议定位"短会/移动"，长会用 Mac Studio 或 3588。待你确认。

---

## 📌 产品定位（已定，背景）

- **载体**：3588(.6)=纪要产品机 · 62 湖森 HDC=视听 demo · Mac Studio(M3U)=大场合高算力/研发 · MacBook Pro=轻量短会
- **四线**：快捷（纪要机✅ + 视频分析机待 + 评课推广已完成待项目）· 湖森（最小 demo，协议不清不推）· 601（运维完成为主不扩边界，功能留作 3588 模块复用）· demo 机（负载不了按需拉起功能/暂停部分，或 Mac Studio 全开）
- **框架复用铁律**：产品化 = **加 profile，不复制代码**；主干 av_unified_mvp 不动；算力受限处分档（NPU/CPU/Metal）

---

## ⚠️ 约束（常驻）

- NPU IOVA 域 ~4GB：4B 装不下、不能与 llm_engine(1.5B 占 2GB) 共存
- 勿满载对 NPU 发大请求（会 OOM 连累 ollama/视听）
- 3588 是生产机：动形态选窗口，`SIGSTOP/SIGCONT` 短命令、测完 `curl :5050` 验 200
- 开发细节不入 vault（在此仓）；成品 html 不入 vault（iCloud 成品仓）；单一事实源
