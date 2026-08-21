// dashboard.js — 中控大屏（左导航 + 主舞台 + 底部 ticker）
// 单条 SSE `/events/__all__` 聚合所有 channel，按 __channel 字段 dispatch。
// 老的"每 channel 一条 SSE"会让浏览器同源 6 connection 上限被 SSE 占满，
// 导致 POST /camera/.../enable 排队甚至失发。合并后 :5050 仅占 1 长连接。
(function () {
  "use strict";

  const stage = document.getElementById("stage");
  const navEl = document.getElementById("nav");

  // ── 模块分类（左导航分组用）────────────────────────────────────────────
  const MODULE_TITLES = {
    audio_processor: "语意理解",
    video_processor: "视频检测",
    llm_engine:      "意图 / LLM",
    supervisor:      "控制指令",
    system_info:     "主机指标",
    network_info:    "网络状态",
    network_scanner: "LAN 扫描",
    scene_analyzer:  "视觉深思",
  };
  const MODULE_GROUP = {
    // node_red 单独一组
    audio_processor: "ai", video_processor: "ai",
    llm_engine: "ai", supervisor: "ai",
    system_info: "sys", network_info: "sys",
    network_scanner: "tools",
    scene_analyzer:  "ai",
  };
  const GROUP_DEF = [
    { id: "fixed",     title: "" },                          // 总览 / Node-RED
    { id: "ai",        title: "AI 流" },
    { id: "sys",       title: "系统" },
    { id: "tools",     title: "工具" },
    { id: "other",     title: "其它" },
  ];

  // module_name → { meta, viewEl, sources, lastSeen, heartbeatInterval, navEl, endpointRenderers }
  const modules = new Map();
  // 视频墙：4 个画格的状态
  const wallSlots = [
    { idx: 0, sourceName: null, status: "empty", lastDetect: null, lastDetectTs: 0 },
    { idx: 1, sourceName: null, status: "empty", lastDetect: null, lastDetectTs: 0 },
    { idx: 2, sourceName: null, status: "empty", lastDetect: null, lastDetectTs: 0 },
    { idx: 3, sourceName: null, status: "empty", lastDetect: null, lastDetectTs: 0 },
  ];
  // 当前 video_processor endpoints 缓存（slot 选源用）
  let videoEndpointsCache = [];
  // viewId → DOM section
  const views = new Map();
  // 已注册的特殊 view（总览/Node-RED）
  views.set("__overview", document.querySelector('[data-view-id="__overview"]'));
  views.set("__nodered",  document.querySelector('[data-view-id="__nodered"]'));

  let currentView = "__overview";
  let nodeRedLoaded = false;
  const overviewBuffers = {
    transcript: [], video: [], host_stats: null, network: null, intent: [], control: [],
  };

  // ── 左导航：先放固定项 ─────────────────────────────────────────────────
  function buildNavSkeleton() {
    GROUP_DEF.forEach(g => {
      const groupDiv = document.createElement("div");
      groupDiv.className = "nav-group";
      groupDiv.dataset.groupId = g.id;
      if (g.title) {
        const t = document.createElement("div");
        t.className = "nav-group-title";
        t.textContent = g.title;
        groupDiv.appendChild(t);
      }
      navEl.appendChild(groupDiv);
    });
    // 用同形图标，避免"实/空方块"被误读成 checkbox 选中态
    addNavItem({ id: "__overview", title: "总览", icon: "▢", group: "fixed" });
    addNavItem({ id: "__nodered",  title: "Node-RED", icon: "▢", group: "fixed" });
    setActive("__overview");
  }

  function getGroupBody(groupId) {
    return navEl.querySelector(`.nav-group[data-group-id="${groupId}"]`);
  }

  function addNavItem({ id, title, icon, group, sub, parent, badge }) {
    const groupBody = getGroupBody(group) || getGroupBody("other");
    const item = document.createElement("div");
    item.className = "nav-item" + (sub ? " sub" : "");
    item.dataset.viewId = id;
    item.innerHTML =
      `<span class="ico">${icon || ""}</span>` +
      `<span class="lbl">${escHtml(title)}</span>` +
      `<span class="badge">${escHtml(badge || "")}</span>`;
    item.addEventListener("click", () => setActive(id));
    // 子项插在 parent 之后
    if (sub && parent) {
      const parentEl = navEl.querySelector(`.nav-item[data-view-id="${parent}"]`);
      if (parentEl) {
        parentEl.parentNode.insertBefore(item, parentEl.nextSibling);
        return item;
      }
    }
    groupBody.appendChild(item);
    return item;
  }

  function setActive(viewId) {
    const prev = currentView;
    currentView = viewId;
    navEl.querySelectorAll(".nav-item").forEach(el => {
      el.classList.toggle("active", el.dataset.viewId === viewId);
    });
    views.forEach((sec, id) => sec.classList.toggle("active", id === viewId));
    if (viewId === "__nodered" && !nodeRedLoaded) loadNodeRed();
    // 切视图时通知所有 polling 暂停/恢复
    onViewChanged(prev, viewId);
  }

  // 视图切换 → 哪些 polling 该跑、哪些该停
  function onViewChanged(prev, next) {
    // 总览的视频墙：只在总览 active 时跑
    const overviewActive = (next === "__overview");
    wallSlots.forEach(slot => {
      if (overviewActive && slot.sourceName) {
        // 重新开始（如果之前停了），按 kind 分流
        const ep = videoEndpointsCache.find(e => e.name === slot.sourceName);
        if (ep && ep.enabled) {
          const tileEl = document.getElementById("video-wall")?.querySelector(`[data-slot="${slot.idx}"]`);
          const media = tileEl?.querySelector(".tile-img");
          if (media && !slot._stopPoll) {
            if (ep.kind === "husion_stream") {
              startFlvStream(slot, media, rewriteHost(ep.stream_url || ep.url));
            } else {
              // 5/14 改：grid raw 流畅模式，检测靠 detect overlay badge 叠加
              startSnapshotPoll(slot, media, rewriteHost(ep.stream_url || ep.url));
            }
          }
        }
      } else if (!overviewActive && slot._stopPoll) {
        slot._stopPoll();
        slot._stopPoll = null;
      }
    });
    // 模块视图（视频检测里的 mjpeg renderer）：通过事件通知
    document.dispatchEvent(new CustomEvent("dashboard:view-change", { detail: { prev, next } }));
  }
  // 暴露给其它脚本（e.g. mjpeg renderer 监听切换）
  window.__currentViewId = () => currentView;

  // ── 单条聚合 SSE：channel→handlers 注册表 + 一条 EventSource ──────────
  // 后端 /events/__all__ 把所有 channel 事件包成 { __channel, ...ev } 推过来；
  // 前端按 __channel 字段 dispatch 到注册的 handler。
  const channelHandlers = new Map();   // channel -> Set<{ handler, module }>
  function subscribeChannel(ch, handler, module) {
    if (!channelHandlers.has(ch)) channelHandlers.set(ch, new Set());
    const item = { handler, module: module || null };
    channelHandlers.get(ch).add(item);
    return item;
  }
  function unsubscribeChannel(ch, item) {
    const set = channelHandlers.get(ch);
    if (set) set.delete(item);
  }

  const sse = new EventSource("/events/__all__");
  sse.onopen  = () => setHeaderStatus("已连接", "ok");
  sse.onerror = () => setHeaderStatus("断开 · 自动重连", "error");
  sse.onmessage = (e) => {
    let ev;
    try { ev = JSON.parse(e.data); } catch (err) { return; }
    if (!ev || ev.type === "hello") return;
    const ch = ev.__channel;
    if (!ch) return;
    // 把 __channel 字段剥掉再交给 renderer，避免污染原事件结构
    const cleanEv = { ...ev };
    delete cleanEv.__channel;
    const handlers = channelHandlers.get(ch);
    if (!handlers) return;
    // 7/29 双倍转写修复：tickerForward 每条事件只转发一次，不随 handler 数放大。
    // audio_processor 与 net_audio_capture 都声明 channel="transcript"（P1 起），
    // 两个模块各注册一个 handler → 旧代码对每个 handler 都调 tickerForward
    // → 总览转写卡每句 append 两遍。tickerForward 内部只按 channel 分发，
    // module 参数仅作存在性判断，转发一次即为正确语义（punctuator 注释同款坑）。
    let forwarded = false;
    handlers.forEach(({ handler, module }) => {
      try { handler(cleanEv); } catch (err) { console.warn(err); }
      if (module && !forwarded) {
        forwarded = true;
        try { tickerForward(module, ch, cleanEv); } catch (_) {}
      }
    });
  };

  // discovery 走聚合 SSE
  subscribeChannel("discovery", (ev) => {
    try { handleDiscovery(ev); } catch (err) { console.warn(err); }
  });

  // 5/20 D 仿 partial UX：listening 心跳 SSE channel 主动订阅
  // audio_processor VAD speaking 触发 state=start → 启动 "...正在听 X.Xs" 计时器
  // silence 触发 state=end → 清除占位（一般之后会跟一条 final 上屏）
  // 不通过 module discovery 注册（避免被 tickerForward 二次调用造成混乱）
  subscribeChannel("listening", (ev) => {
    try { handleListening(ev); } catch (err) { console.warn(err); }
  });

  // 门禁联动：door channel（supervisor 桥接 av/door/visitor + av/door/result）
  // visitor → 右上角弹窗（开门按钮）；result → 弹窗内状态行更新
  subscribeChannel("door", (ev) => {
    try { handleDoorEvent(ev); } catch (err) { console.warn(err); }
  });

  let _doorPopupTimer = null;
  function handleDoorEvent(ev) {
    if (ev.event === "visitor") showDoorPopup(ev);
    else if (ev.event === "result") showDoorResult(ev);
  }

  function showDoorPopup(ev) {
    // SSE 快照重放会把最后一条 visitor 推给新开/刷新的页面；
    // 超过 60s（与弹窗自动收起时长一致）的陈旧事件丢弃，人早走了
    if (ev.ts && Date.now() / 1000 - ev.ts > 60) return;
    let popup = document.getElementById("door-popup");
    if (!popup) {
      popup = document.createElement("div");
      popup.id = "door-popup";
      popup.className = "door-popup";
      popup.innerHTML = `
        <h3>🚪 门口有人</h3>
        <div class="door-meta"></div>
        <div class="door-status"></div>
        <div class="door-actions">
          <button class="door-open-btn">开门</button>
          <button class="door-dismiss-btn">忽略</button>
        </div>`;
      popup.querySelector(".door-open-btn").onclick = doorOpen;
      popup.querySelector(".door-dismiss-btn").onclick = closeDoorPopup;
      document.body.appendChild(popup);
    }
    const t = new Date((ev.ts || Date.now() / 1000) * 1000);
    popup.querySelector(".door-meta").textContent =
      `${ev.camera || "?"} · ${ev.person_count || 1} 人 · ${t.toLocaleTimeString()}`;
    // 无人操作 60s 自动收起；期间再次触发（冷却后又有人）重置计时
    clearTimeout(_doorPopupTimer);
    _doorPopupTimer = setTimeout(closeDoorPopup, 60000);
  }

  function closeDoorPopup() {
    clearTimeout(_doorPopupTimer);
    const popup = document.getElementById("door-popup");
    if (popup) popup.remove();
  }

  async function doorOpen() {
    const popup = document.getElementById("door-popup");
    if (!popup) return;
    const btn = popup.querySelector(".door-open-btn");
    const st = popup.querySelector(".door-status");
    btn.disabled = true; btn.textContent = "开门中…";
    st.className = "door-status"; st.textContent = "";
    try {
      const r = await fetch("/mqtt/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: "av/door/cmd", payload: { action: "open" } }),
      });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      // 实际结果由 av/door/result 经 door channel 回推 → showDoorResult
    } catch (e) {
      st.className = "door-status err"; st.textContent = `发送失败: ${e}`;
      btn.disabled = false; btn.textContent = "开门";
    }
  }

  function showDoorResult(ev) {
    const popup = document.getElementById("door-popup");
    if (!popup) return;
    const btn = popup.querySelector(".door-open-btn");
    const st = popup.querySelector(".door-status");
    if (ev.ok) {
      st.className = "door-status ok";
      st.textContent = `✓ 已开门（${ev.latency_ms}ms，门 10 秒后自动上锁）`;
      btn.textContent = "已开门";
      clearTimeout(_doorPopupTimer);
      _doorPopupTimer = setTimeout(closeDoorPopup, 5000);
    } else {
      st.className = "door-status err";
      st.textContent = `✗ 开门失败: ${ev.message || ev.code}`;
      btn.disabled = false; btn.textContent = "重试开门";
    }
  }

  function setHeaderStatus(text, cls) {
    const el = document.getElementById("header-status");
    if (el) { el.textContent = text; el.className = "pill " + cls; }
  }

  // 5/21 转写卡 badge 三态联动：
  //   audio_processor.running=false  → "已停止" .error（disable 或进程 stuck 兜底）
  //   running=true + listening start → "正在听" .ok
  //   running=true + listening end   → "等待" 默认
  // 5/20 audio_processor 5.5GB stuck 事件暴露：disable 路径不发 listening end，
  // 必须用 running 状态兜底；listening start 在 stopped 态被忽略避免抢回。
  let _txRunning = true;  // 默认 audio_processor 在跑（与后端 default 一致）
  function setTranscriptBadge(text, cls) {
    const badge = document.getElementById("overview-transcript-badge");
    if (!badge) return;
    badge.textContent = text;
    badge.className = "module-badge" + (cls ? " " + cls : "");
  }
  function handleListening(ev) {
    if (!ev || !ev.state) return;
    if (!_txRunning) return;  // stopped 态忽略 listening 事件
    if (ev.state === "start") setTranscriptBadge("正在听", "ok");
    else if (ev.state === "end") setTranscriptBadge("等待", "");
  }

  function handleDiscovery(ev) {
    if (ev.type === "hello") return;
    const name = ev.module;
    if (!name) return;
    if (!modules.has(name)) createModuleView(name, ev);
    updateModule(name, ev);
    refreshModulesPill();
    // llm_engine 的 enabled 字段反向同步顶栏意图判断 toggle
    if (name === "llm_engine" && typeof ev.enabled === "boolean") {
      setIntentToggleState(ev.enabled);
    }
    if ((name === "audio_processor" || name === "net_audio_capture") && typeof ev.running === "boolean") {
      _srcRunning[name === "audio_processor" ? "mic" : "net_multicast"] = ev.running;
      refreshTxSource();
    }
  }
  // ── 声源（本机麦 / 会议主机）：两模块都在线时转写卡出下拉；停止按钮按当前声源发命令 ──
  const _srcRunning = { mic: null, net_multicast: null };   // null=模块不在
  const SRC_TOPIC = { mic: "av/audio/cmd", net_multicast: "av/audio/net_cmd" };
  function activeSource() {
    if (_srcRunning.mic) return "mic";
    if (_srcRunning.net_multicast) return "net_multicast";
    // 都没在跑：按"在线的那个"给停止按钮一个目标
    return _srcRunning.mic !== null ? "mic" : (_srcRunning.net_multicast !== null ? "net_multicast" : "mic");
  }
  function refreshTxSource() {
    const sel = document.querySelector("[data-tx-source]");
    const both = _srcRunning.mic !== null && _srcRunning.net_multicast !== null;
    if (sel) {
      sel.hidden = !both;
      if (both && document.activeElement !== sel) sel.value = activeSource();
    }
    setTxStopButtonState(!!(_srcRunning.mic || _srcRunning.net_multicast));
  }
  async function publishSourceCmd(src, action) {
    try {
      await fetch("/mqtt/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: SRC_TOPIC[src], payload: { action } }),
      });
    } catch (e) { console.warn("source cmd 失败", src, action, e); }
  }
  function setTxStopButtonState(running) {
    _txRunning = running;
    const btn = document.querySelector("[data-tx-stop]");
    if (btn) {
      btn.textContent = running ? "⏸ 停止" : "▶ 启动";
      btn.classList.toggle("stop", running);  // 红色仅在"停止"态（点击会停）
    }
    // running=false 时 badge 强制回 "已停止"（disable 不发 listening end 的兜底）
    // running=true 时回到默认 "等待"，等下一个 listening start 翻成 "正在听"
    if (!running) setTranscriptBadge("已停止", "error");
    else setTranscriptBadge("等待", "");
  }
  function setIntentToggleState(on) {
    // 意图判断开关在意图卡 module-header（A8 从 body 底挪到 header；按钮少不值得占一行）
    const btn = document.querySelector("[data-intent-toggle]");
    if (!btn) return;
    btn.classList.toggle("on",  !!on);
    btn.classList.toggle("off", !on);
    btn.textContent = on ? "⚡ 判别中" : "▶ 已暂停";
    btn.title = on ? "意图判别中（点击暂停 — 仍转写但不调 LLM）"
                   : "意图判别已暂停（点击启用）";
  }

  function refreshModulesPill() {
    const total = modules.size;
    let online = 0;
    modules.forEach(s => { if (!s.viewEl.classList.contains("offline")) online++; });
    const pill = document.getElementById("modules-pill");
    pill.textContent = `模块 ${online}/${total}`;
    pill.className = "pill " + (online === total ? "ok" : (online > 0 ? "warn" : "error"));
  }

  // ── 创建模块对应的 view + nav 项 ──────────────────────────────────────
  function createModuleView(name, meta) {
    const streams   = meta.streams   || [];
    const endpoints = meta.endpoints || [];
    const channels  = [...new Set(streams.map(s => s.channel).filter(Boolean))];
    const title     = MODULE_TITLES[name] || streams[0]?.title || name;
    const topicLabel = streams.map(s => s.topic).join(", ") || "";

    // view 容器
    const section = document.createElement("section");
    section.className = "view";
    section.dataset.viewId = name;
    section.innerHTML = `
      <div class="view-head">
        <h2>${escHtml(title)}</h2>
        <span class="topic">${escHtml(topicLabel)}</span>
        <span style="flex:1"></span>
        <span class="pill warn" data-status>等待数据…</span>
      </div>
      <div class="view-body" data-feed></div>`;
    stage.appendChild(section);
    views.set(name, section);

    const feed = section.querySelector("[data-feed]");
    const sources = {};

    function makeSub(extraClass) {
      const div = document.createElement("div");
      div.className = "feed-sub " + (extraClass || "");
      div.style.cssText = "display:flex;flex-direction:column;gap:6px;";
      feed.appendChild(div);
      return div;
    }

    // endpoints 子容器在前（视频/控件 在上，事件流在下）
    const endpointKinds = [...new Set(endpoints.map(e => e.kind).filter(Boolean))];
    const endpointRenderers = {};
    endpointKinds.forEach(kind => {
      const fn = window.Renderers[kind];
      if (!fn) return;
      const sub = makeSub("ep-" + kind);
      const r = fn(sub);
      endpointRenderers[kind] = r;
      if (typeof r.setEndpoints === "function") {
        r.setEndpoints(endpoints.filter(e => e.kind === kind));
      }
    });

    // streams：每个 channel 注册到聚合 SSE dispatcher（不再单独建 EventSource）
    channels.forEach(ch => {
      const kind = (streams.find(s => s.channel === ch) || {}).kind || "fallback";
      const fn = window.Renderers[kind] || window.Renderers.fallback;
      const sub = makeSub("stream-" + kind);
      const render = fn(sub);
      const sub_item = subscribeChannel(ch, render, name);
      sources[ch] = { unsubscribe: () => unsubscribeChannel(ch, sub_item) };
    });

    // 左导航项
    const groupId = MODULE_GROUP[name] || "other";
    const navItem = addNavItem({
      id: name,
      title,
      icon: "·",
      group: groupId,
    });

    modules.set(name, {
      meta, viewEl: section, navEl: navItem,
      sources, endpointRenderers,
      lastSeen: Date.now(),
      heartbeatInterval: (meta.heartbeat_interval || 30) * 1000,
    });
  }

  function updateModule(name, ev) {
    const state = modules.get(name);
    if (!state) return;
    state.lastSeen = Date.now();
    state.heartbeatInterval = (ev.heartbeat_interval || 30) * 1000;

    if (ev.event === "offline") markOffline(name, "模块已离线");
    else                        markOnline(name);

    // endpoints 可能变化（用户切了某路摄像头），重新喂给对应 renderer
    const endpoints = ev.endpoints || [];
    if (state.endpointRenderers && endpoints.length) {
      Object.entries(state.endpointRenderers).forEach(([kind, r]) => {
        if (typeof r.setEndpoints === "function") {
          r.setEndpoints(endpoints.filter(e => e.kind === kind));
        }
      });
    }

    // 视频墙：根据 video_processor endpoints 自动分配/刷新画格
    if (name === "video_processor") {
      // 视频墙接 husion_stream（FLV WebSocket）+ mjpeg（HTTP multipart）两种 endpoint。
      // mjpeg 走 startSnapshotPoll <img>，husion_stream 走 startFlvStream <video>+flv.js。
      videoEndpointsCache = (endpoints || []).filter(
        e => e.kind === "mjpeg" || e.kind === "husion_stream"
      );
      applyWallMode();  // 含 enforceSingleMode + assignWallSlots + renderWall
      refreshSceneWatchPicker();
    }
  }

  // G3b: 视觉深思卡片 dropdown 同步 enabled 源列表（每次 video_processor discovery heartbeat 30s 触发）
  function refreshSceneWatchPicker() {
    const sel = document.getElementById("scene-watch-picker");
    if (!sel) return;
    const current = sel.value;
    const enabled = (videoEndpointsCache || []).filter(e => e.enabled);
    sel.innerHTML = `<option value="">全部</option>` +
      enabled.map(e => `<option value="${escHtml(e.name)}">${escHtml(e.name)}</option>`).join("");
    if (current && enabled.some(e => e.name === current)) sel.value = current;
  }

  // 单个 slot 签名：只反映该 slot 自己关心的状态。
  // 旧版用全局 wallSignature（含全部 endpoints enabled），任一路启停就让全 4 路 sig 变 →
  // renderWall 全量重建 DOM → 4 路 multipart MJPEG 同时被打断（Chrome 立即重连有缓存怪行为，
  // 实测"不刷新不恢复"全黑）。改成 per-slot sig 后，只有真正变化的 tile 重建，其它三路保持流不动。
  function slotSignature(slot, ep) {
    if (!ep) return `_:${slot.zoomed ? "Z" : ""}`;
    return `${ep.name}:${ep.enabled ? "+" : "-"}:${ep.status || ""}:${slot.zoomed ? "Z" : ""}`;
  }

  // ── 视频墙逻辑 ───────────────────────────────────────────────────────
  // 默认把前 4 路源依次分到 4 个画格；用户切源会覆盖默认
  // ── 视频墙模式：single(默认,只开会议室一路,CPU 让给转写) / quad(四分屏,需停转写) ──
  // 规则只在前端 + config(video.meeting_camera)，后端零改动：复用 /camera/<名>/enable|disable 与 av/audio/cmd。
  // 刷新页面回到 single（保守：多路是显式动作，不持久化）。
  let wallMode = "single";
  function meetingCameraName() {
    const cfg = document.body.dataset.meetingCamera || "";
    if (cfg && videoEndpointsCache.find(e => e.name === cfg)) return cfg;
    return videoEndpointsCache[0]?.name || null;
  }
  // in-flight 去重：endpoints 公告是异步回放的，enforceSingleMode 会在状态落定前被触发多次，
  // 同一路同一动作 5s 内只发一次（后端本身幂等，这里只是别刷日志）。
  const _cameraCmdSent = new Map();
  async function cameraCmd(name, action) {
    const k = `${name}:${action}`, now = Date.now();
    if ((_cameraCmdSent.get(k) || 0) > now - 5000) return;
    _cameraCmdSent.set(k, now);
    try { await fetch(`/camera/${encodeURIComponent(name)}/${action}`, { method: "POST" }); }
    catch (e) { console.warn(`camera ${action} 失败`, name, e); }
  }
  // single：除会议摄像头外全部 disable；会议摄像头若停用则 enable。幂等，endpoints 每次更新都会再跑一遍。
  function enforceSingleMode() {
    if (wallMode !== "single") return;
    const keep = meetingCameraName();
    videoEndpointsCache.forEach(ep => {
      if (ep.name === keep) { if (!ep.enabled) cameraCmd(ep.name, "enable"); }
      else if (ep.enabled) cameraCmd(ep.name, "disable");
    });
  }
  function applyWallMode() {
    const wall = document.getElementById("video-wall");
    const btn  = document.querySelector("[data-wall-mode]");
    if (wall) wall.classList.toggle("single", wallMode === "single");
    if (btn)  btn.textContent = wallMode === "single" ? "⊞ 四分屏" : "▭ 单路";
    enforceSingleMode();
    assignWallSlots();
    renderWall();
  }
  async function setWallMode(mode) {
    if (mode === wallMode) return;
    if (mode === "quad" && _txRunning) {
      if (!confirm("切到四分屏会停止实时转写（多路解码会抢走 FunASR 的 CPU）。\n继续？")) return;
      await publishSourceCmd(activeSource(), "disable");
    }
    wallMode = mode;
    if (mode === "quad") {
      // 四分屏 = 前 4 路全开（用户再按需 ⏸ 单路）
      videoEndpointsCache.slice(0, 4).forEach(ep => { if (!ep.enabled) cameraCmd(ep.name, "enable"); });
    }
    applyWallMode();
  }

  function assignWallSlots() {
    if (wallMode === "single") {
      wallSlots[0].sourceName = meetingCameraName();
      wallSlots[0].userPicked = false;
      return;
    }
    wallSlots.forEach((slot, i) => {
      // 用户没明确指定时，自动分配前 4 路
      if (!slot.userPicked) {
        slot.sourceName = videoEndpointsCache[i]?.name || null;
      } else {
        // 用户指定的源若不存在了，回退到 null
        if (slot.sourceName && !videoEndpointsCache.find(e => e.name === slot.sourceName)) {
          slot.sourceName = null;
          slot.userPicked = false;
        }
      }
    });
  }

  function rewriteHost(url) {
    // 只对 127.0.0.1 / localhost 这种回环 host 重写到浏览器当前 host（MJPEG 后端写死 127.0.0.1）。
    // husion FLV 等 URL 用真实内网 IP（192.168.150.X，依赖客户端 ifconfig alias 或同段路由），
    // 不能被改写成 dashboard host，否则浏览器连不通。
    try {
      const u = new URL(url);
      if (u.hostname === "127.0.0.1" || u.hostname === "localhost" || u.hostname === "::1") {
        u.hostname = window.location.hostname;
      }
      return u.toString();
    } catch (_) { return url; }
  }

  // 视频墙改用 multipart MJPEG 流（/video_feed/）——浏览器原生持续接收，无 polling 竞态。
  // 旧 snapshot polling 实测在 Chrome 偶发"第二次 onload 不触发"，img 静帧。multipart 模式
  // 浏览器收到每个 boundary 帧都重绘 img，5051 端 watchdog 自带断流，更稳。
  const STREAM_WATCHDOG_MS = 8000;  // 8 秒收不到 onload（multipart 子帧）就重连
  function startSnapshotPoll(slot, img, baseUrl) {
    // baseUrl 期望是 stream_url（/video_feed/...）；如果是 snapshot URL 也兼容，但效果同旧轮询
    let stopped = false;
    let firstLogged = false;
    let watchdog = null;
    function clear() {
      stopped = true;
      if (watchdog) { clearTimeout(watchdog); watchdog = null; }
      img.onload = null; img.onerror = null;
      img.src = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
    }
    function bumpWatchdog() {
      if (watchdog) clearTimeout(watchdog);
      watchdog = setTimeout(() => {
        if (stopped) return;
        if (currentView !== "__overview" || document.hidden) { clear(); slot._stopPoll = null; return; }
        // 流卡了 / 摄像头偶发断 → 重连
        connect();
      }, STREAM_WATCHDOG_MS);
    }
    function connect() {
      if (stopped) return;
      if (currentView !== "__overview" || document.hidden) { clear(); slot._stopPoll = null; return; }
      img.onload = () => {
        if (stopped) return;
        // multipart 每帧都 fire 一次 onload；重置 watchdog
        if (!firstLogged) {
          console.info(`[wall slot ${slot.idx}] ✓ stream ${img.naturalWidth}x${img.naturalHeight}`);
          firstLogged = true;
        }
        bumpWatchdog();
      };
      img.onerror = () => {
        if (stopped) return;
        setTimeout(connect, 1500);
      };
      // cache-busting：仅在初次或重连时加 t=，避免浏览器复用挂死的旧 socket
      img.src = baseUrl + (baseUrl.includes("?") ? "&" : "?") + "t=" + Date.now();
      bumpWatchdog();
    }
    img.style.opacity = "1";
    slot._stopPoll = clear;
    connect();
  }

  // husion FLV WebSocket 流：用 flv.js 起 player attach 到 <video>；销毁时清理 player + media。
  // 与 startSnapshotPoll 接口对齐（slot._stopPoll 是 cleanup）。
  function startFlvStream(slot, videoEl, url) {
    if (!window.flvjs || !window.flvjs.isSupported()) {
      console.warn(`[wall slot ${slot.idx}] flv.js 不可用，无法播 husion 流`);
      videoEl.style.opacity = "0.3";
      return;
    }
    let player = null;
    let stopped = false;
    function clear() {
      stopped = true;
      if (player) {
        try { player.pause(); player.unload(); player.detachMediaElement(); player.destroy(); }
        catch (_) {}
        player = null;
      }
      try { videoEl.pause(); } catch (_) {}
      videoEl.removeAttribute("src");
      try { videoEl.load(); } catch (_) {}
    }
    function connect() {
      if (stopped) return;
      if (currentView !== "__overview" || document.hidden) {
        clear(); slot._stopPoll = null;
        return;
      }
      player = window.flvjs.createPlayer(
        { type: "flv", url: url, isLive: true, cors: true },
        { enableStashBuffer: false, stashInitialSize: 128 }
      );
      player.attachMediaElement(videoEl);
      player.load();
      player.play().catch(() => {});
      player.on(window.flvjs.Events.ERROR, (errType, errDetail) => {
        if (stopped) return;
        console.warn(`[wall slot ${slot.idx}] FLV err`, errType, errDetail);
        // 错误 → 销毁老 player + 1.5s 后重连
        try { player.destroy(); } catch (_) {}
        player = null;
        setTimeout(connect, 1500);
      });
    }
    videoEl.style.opacity = "1";
    slot._stopPoll = clear;
    connect();
  }

  // tab 重新可见时，如果当前在总览，让 wall slots 重启
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden && currentView === "__overview") {
      onViewChanged(currentView, currentView);  // 触发所有 slot 重启
    }
  });

  function renderWall() {
    const wall = document.getElementById("video-wall");
    if (!wall) return;
    wallSlots.forEach(slot => {
      const tileEl = wall.querySelector(`[data-slot="${slot.idx}"]`);
      if (!tileEl) return;
      const ep = slot.sourceName ? videoEndpointsCache.find(e => e.name === slot.sourceName) : null;
      // per-slot 缓存比较：状态没变就跳过此 tile，保留它的 multipart 流
      const sig = slotSignature(slot, ep);
      if (tileEl.dataset.sig === sig) return;
      tileEl.dataset.sig = sig;
      if (!ep) {
        tileEl.className = "tile empty";
        tileEl.innerHTML =
          `画格 ${slot.idx + 1}<br>` +
          `<small style="color:var(--dim);margin-top:6px;display:block">` +
          (videoEndpointsCache.length === 0 ? "等待 video_processor 上线…" : "未指定源") +
          `</small>` + buildPickerHtml(slot);
        wirePicker(tileEl, slot);
        return;
      }
      // 实际画格 — kind=husion_stream 用 <video class="tile-img"> 走 flv.js；mjpeg 用 <img>
      tileEl.className = "tile" + (slot.zoomed ? " zoomed" : "");
      const mediaEl = (ep.kind === "husion_stream")
        ? `<video class="tile-img" muted playsinline autoplay style="object-fit:cover;width:100%;height:100%"></video>`
        : `<img class="tile-img" alt="${escHtml(ep.name)}">`;
      tileEl.innerHTML =
        mediaEl +
        `<div class="tile-head">` +
          `<span class="tile-name">${escHtml(ep.name)}</span>` +
          (() => {
            // 真实状态：disabled(未启用) / stopped / connecting / ok / error
            const st = ep.status || (ep.enabled ? "stopped" : "disabled");
            const map = {
              ok:         { cls: "ok",       text: "在线" },
              connecting: { cls: "warn",     text: "连接中" },
              error:      { cls: "error",    text: "离线" },
              stopped:    { cls: "error",    text: "离线" },
              disabled:   { cls: "",         text: "已停用" },
            };
            const m = map[st] || map.stopped;
            return `<span class="tile-status ${m.cls}" data-status>${m.text}</span>`;
          })() +
          `<span class="tile-spacer"></span>` +
          (ep.enabled ? (() => {
            // 本机摄像头独占 macOS camera，停用按钮加红色 ring + tooltip
            const isLocal = /^\d+$/.test(String(ep.src_url || ""));
            const tip = isLocal
              ? "停用本机摄像头（释放 macOS camera 占用）"
              : "停用此摄像头";
            const cls = isLocal ? "tile-disable-btn local" : "tile-disable-btn";
            return `<button class="${cls}" data-disable title="${tip}">⏸</button>`;
          })() : "") +
          `<button class="tile-edit-btn" data-edit title="编辑此源">✎</button>` +
          `<button class="tile-delete-btn" data-delete title="删除此源">✕</button>` +
          buildPickerHtml(slot) +
        `</div>` +
        `<div class="tile-detect hidden" data-detect></div>` +
        // 中央"启用"大按钮：仅在停用时显示。独立 layer，不受 tile-foot 的 pointer-events 影响
        (ep.enabled ? "" :
          `<button data-enable class="tile-enable-btn">▶ 启用 ${escHtml(ep.name)}</button>`) +
        `<div class="tile-foot">` +
          `<span class="key">SRC</span><span class="val">${escHtml(ep.name)}</span>` +
          `<span class="spacer"></span>` +
          (ep.enabled ? `<span class="key">点击放大</span>` : `<span class="key" style="color:var(--warn)">未启用</span>`) +
        `</div>`;
      const media = tileEl.querySelector(".tile-img");
      // 先停掉旧的轮询定时器（mjpeg watchdog 或 flv.js player）
      if (slot._stopPoll) { slot._stopPoll(); slot._stopPoll = null; }
      if (ep.enabled) {
        if (ep.kind === "husion_stream") {
          // husion FLV：ws://... URL 走 flv.js；host 重写为浏览器当前 host（5/12 host alias 假设）
          startFlvStream(slot, media, rewriteHost(ep.stream_url || ep.url));
        } else {
          // 5/14 用户反馈：grid 用原始流畅 raw 流（不要 burn-in bbox 让画面不流畅）。
          // 检测信号通过 detect overlay badge（text-only, "person×2 phone×1"）叠加显示。
          startSnapshotPoll(slot, media, rewriteHost(ep.stream_url || ep.url));
        }
      } else if (ep.kind === "husion_stream") {
        media.style.opacity = "0.3";
      } else {
        media.src = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
        media.style.opacity = "0.3";
      }
      wirePicker(tileEl, slot);
      // 启用按钮
      const enableBtn = tileEl.querySelector("[data-enable]");
      if (enableBtn) {
        enableBtn.onclick = (e) => {
          e.stopPropagation();
          fetch(`/camera/${encodeURIComponent(slot.sourceName)}/enable`, { method: "POST" })
            .catch(err => console.warn("enable failed", err));
        };
      }
      // 编辑 / 删除按钮（P1.3）
      const editBtn = tileEl.querySelector("[data-edit]");
      if (editBtn) {
        editBtn.onclick = (e) => {
          e.stopPropagation();
          window.__videoSourceForm?.enterEditMode(ep);
        };
      }
      const delBtn = tileEl.querySelector("[data-delete]");
      if (delBtn) {
        delBtn.onclick = (e) => {
          e.stopPropagation();
          window.__videoSourceForm?.confirmDelete(ep.name);
        };
      }
      const disableBtn = tileEl.querySelector("[data-disable]");
      if (disableBtn) {
        disableBtn.onclick = (e) => {
          e.stopPropagation();
          fetch(`/camera/${encodeURIComponent(ep.name)}/disable`, { method: "POST" })
            .catch(err => console.warn("disable failed", err));
        };
      }
      // 整格点击 = 放大切换（避开 picker / 按钮的事件）
      tileEl.onclick = (e) => {
        if (e.target.closest("select,button,input")) return;
        toggleZoom(slot);
      };
    });
  }

  function buildPickerHtml(slot) {
    const opts = videoEndpointsCache.map(e =>
      `<option value="${escHtml(e.name)}"${e.name === slot.sourceName ? " selected" : ""}>` +
      escHtml(e.name + (e.enabled ? "" : " (停)")) + `</option>`
    ).join("");
    return `<select class="tile-source-picker" data-picker>` +
      `<option value=""${slot.sourceName ? "" : " selected"}>— 选源 —</option>` +
      opts + `</select>`;
  }

  function wirePicker(tileEl, slot) {
    const picker = tileEl.querySelector("[data-picker]");
    if (!picker) return;
    picker.onchange = (e) => {
      e.stopPropagation();
      slot.sourceName = picker.value || null;
      slot.userPicked = true;
      renderWall();
    };
    picker.onclick = (e) => e.stopPropagation();
  }

  function toggleZoom(slot) {
    const wall = document.getElementById("video-wall");
    const wasZoomed = slot.zoomed;
    wallSlots.forEach(s => s.zoomed = false);
    if (!wasZoomed) slot.zoomed = true;
    wall.classList.toggle("zoomed", !wasZoomed);
    renderWall();
  }

  // 视频检测事件 → overlay 到对应画格 + 画格闪光
  function pushDetectionOverlay(camera, detections) {
    const counts = {};
    for (const d of (detections || [])) counts[d.class] = (counts[d.class] || 0) + 1;
    const summary = Object.entries(counts).map(([k, v]) => `${k}×${v}`).join(" ");
    if (!summary) return;
    const slot = wallSlots.find(s => s.sourceName === camera);
    if (!slot) return;
    slot.lastDetect = summary;
    slot.lastDetectTs = Date.now();
    const wall = document.getElementById("video-wall");
    const tileEl = wall?.querySelector(`[data-slot="${slot.idx}"]`);
    const detectEl = tileEl?.querySelector("[data-detect]");
    if (detectEl) {
      detectEl.textContent = "● " + summary;
      detectEl.classList.remove("hidden");
      clearTimeout(slot._detectFade);
      slot._detectFade = setTimeout(() => detectEl.classList.add("hidden"), 4000);
    }
    pulseEl(tileEl);
  }

  function markOnline(name) {
    const s = modules.get(name); if (!s) return;
    s.viewEl.classList.remove("offline");
    s.navEl.classList.remove("offline");
    s.navEl.querySelector(".badge").textContent = "在线";
    s.navEl.querySelector(".badge").style.color = "var(--final)";
    setModuleStatus(name, "在线", "ok");
  }
  function markOffline(name, reason) {
    const s = modules.get(name); if (!s) return;
    s.viewEl.classList.add("offline");
    s.navEl.classList.add("offline");
    s.navEl.querySelector(".badge").textContent = "离线";
    s.navEl.querySelector(".badge").style.color = "var(--warn)";
    setModuleStatus(name, reason || "已离线", "error");
  }
  function setModuleStatus(name, text, cls) {
    const s = modules.get(name); if (!s) return;
    const el = s.viewEl.querySelector("[data-status]");
    if (el) { el.textContent = text; el.className = "pill " + cls; }
  }

  // 失活检测
  setInterval(() => {
    const now = Date.now();
    modules.forEach((s, name) => {
      const threshold = s.heartbeatInterval * 2.3;
      if (now - s.lastSeen > threshold && !s.viewEl.classList.contains("offline")) {
        const secs = Math.round((now - s.lastSeen) / 1000);
        markOffline(name, `已离线 ${secs}s`);
        refreshModulesPill();
      }
    });
  }, 5000);

  // ── 总览 + ticker：把 SSE 事件转发到固定槽位 ──────────────────────────
  function tickerForward(module, channel, data) {
    if (data.type === "hello") return;
    if (channel === "transcript") {
      const inner = data;
      const text = (inner.text || "").trim();
      if (!text) return;
      setTickerTranscript(text, inner.is_final);
      pushOverviewTranscript(inner);
    } else if (channel === "intent") {
      const body = data.payload || data;
      if (body.original_text) {
        const cmd = body.command ? `→ ${JSON.stringify(body.command)}` : (body.intent?.is_command === false ? "(非控制)" : "");
        setTickerIntent(`${body.original_text} ${cmd}`);
        pushOverviewIntent(body);
      }
    } else if (channel === "control") {
      pushOverviewIntent(data);
    } else if (channel === "host_stats") {
      setTickerHost(data);
      pushOverviewHost(data);
    } else if (channel === "network") {
      setTickerNet(data);
      pushOverviewHost(data);
    } else if (channel === "video") {
      pushOverviewVideo(data);
    } else if (channel === "scene_analysis") {
      setTickerScene(data);
      pushOverviewScene(data);
    } else if (channel === "openvocab") {
      pushOverviewOpenvocab(data);
    }
  }

  function setTickerTranscript(text, isFinal) {
    const el = document.getElementById("ticker-transcript");
    if (!el) return;
    el.textContent = (text.length > 80 ? text.slice(0, 78) + "…" : text);
    el.style.color = isFinal ? "var(--final)" : "var(--live)";
  }
  function setTickerIntent(text) {
    const el = document.getElementById("ticker-intent");
    if (!el) return;
    el.textContent = (text.length > 60 ? text.slice(0, 58) + "…" : text);
    el.style.color = "var(--accent)";
  }
  function setTickerHost(d) {
    document.getElementById("ticker-cpu").textContent = `${d.cpu_percent?.toFixed(1)}%`;
    document.getElementById("ticker-mem").textContent = `${d.mem_percent?.toFixed(1)}%`;
  }
  function setTickerNet(d) {
    const main = (d.interfaces || []).find(i => i.sent_kbps > 0 || i.recv_kbps > 0) || (d.interfaces || [])[0];
    if (!main) return;
    document.getElementById("ticker-net").textContent = `↑${main.sent_kbps} ↓${main.recv_kbps} KB/s`;
  }
  function setTickerScene(d) {
    const el = document.getElementById("ticker-scene");
    if (!el) return;
    const cam = d.camera || "?";
    const scene = (d.scene || "").trim();
    const short = scene.length > 50 ? scene.slice(0, 48) + "…" : scene;
    el.textContent = `${cam}: ${short}`;
    el.style.color = "var(--accent)";
  }
  function pushOverviewScene(ev) {
    const card = document.querySelector('[data-overview="scene"] .strip-card-body');
    if (!card) return;
    clearEmpty(card);
    pulseEl(card.closest(".strip-card"));
    const row = document.createElement("div");
    row.className = "row final";
    const cls = (ev.detection_classes || []).join(",") || "—";
    const lat = ev.vlm_latency_ms ? `${ev.vlm_latency_ms}ms` : "?";
    row.innerHTML = `<div><b>${escHtml(ev.camera || "?")}</b> [${escHtml(cls)}]</div>` +
                    `<div style="margin-top:2px;line-height:1.4">${escHtml(ev.scene || "")}</div>` +
                    `<div class="meta" style="margin-top:2px;opacity:.7">${lat}</div>`;
    card.appendChild(row);
    while (card.querySelectorAll(".row").length > 6) card.firstChild.remove();
    card.scrollTop = card.scrollHeight;
  }
  function pushOverviewOpenvocab(ev) {
    // openvocab_filter 命中 timeline：每行 camera + hits + 推理耗时。
    // payload (modules/openvocab_filter/main.py _infer): {camera, ts, hits:[{class, conf, bbox}], inference_ms, key_reason, ...}
    const card = document.querySelector('[data-overview="openvocab"] .strip-card-body');
    if (!card) return;
    clearEmpty(card);
    pulseEl(card.closest(".strip-card"));
    const row = document.createElement("div");
    row.className = "row final";
    const hits = (ev.hits || []).map(h => `${h.class}(${Math.round((h.conf || 0) * 100)}%)`).join(", ") || "—";
    const reason = ev.key_reason ? ` · ${ev.key_reason}` : "";
    row.innerHTML = `<div><b>${escHtml(ev.camera || "?")}</b> [${escHtml(hits)}]</div>` +
                    `<div class="meta" style="margin-top:2px;opacity:.7">${ev.inference_ms || "?"}ms${escHtml(reason)}</div>`;
    card.appendChild(row);
    while (card.querySelectorAll(".row").length > 6) card.firstChild.remove();
    card.scrollTop = card.scrollHeight;
    // badge → 命中数
    const badge = document.getElementById("overview-openvocab-badge");
    if (badge) {
      badge.textContent = `${(ev.hits || []).length} 命中`;
      badge.style.color = "var(--live)";
    }
  }

  // 转写卡渲染：仿讯飞「讲解稿」观感 — 连续讲话合并到同一段落。
  // 三条换段触发（按优先级）：
  //   1. 静音 >60s（PARA_GAP_SEC）— 主题切换；最强信号
  //   2. 累积 >=250 字 且 当前句以句末标点收尾（。！？!?）— 篇幅自然分段
  //   3. 累积 >=400 字（HARD_LIMIT）— 硬切兜底，防一段几千字
  // 段头只显时间戳（diarization 没接前不显示"说话人 1"占位避免误导）。
  // 段内：.finals 累积定稿 + 末尾 .live 显 partial（灰），final 时并入 finals 清空 live。
  const PARA_GAP_SEC = 60;
  const PARA_SOFT_LIMIT = 250;
  const PARA_HARD_LIMIT = 400;
  const PARA_ENDS_PUNCT = /[。！？!?]\s*$/;
  // CR-DIG7201 P3：会议主机多路话筒（payload 带 mic_id/speaker）按发言人分段分色；
  // 本地麦（无 mic_id）行为不变
  const MIC_COLORS = ["#e6a23c", "#4fc3f7", "#81c784", "#f48fb1",
                      "#ba68c8", "#ffd54f", "#4db6ac", "#ff8a65"];
  const _txStates = new Map();  // spkKey(""=本地麦) → { para, finalsText, lastFinalMs }
  function fmtClock(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }
  function pushOverviewTranscript(ev) {
    const card = document.querySelector('[data-overview="transcript"] .strip-card-body');
    if (!card) return;
    // 5/21 user 抱怨"上翻历史会被拽回底部" — 在所有 DOM 修改前 capture user 是否仍在底部，
    // 只有在底部附近才 auto-follow，user 上翻时尊重 scroll 位置不动。
    const atBottom = card.scrollHeight - card.scrollTop - card.clientHeight < 50;
    clearEmpty(card);
    pulseEl(card.closest(".strip-card"));

    const nowMs = Date.now();
    // CR-DIG7201 转写体验（2026-08-07）：per-speaker 段指针 — 多路话筒碎 final
    // 交错到达时各归各段（同话筒 60s 内追加回自己最近的段，即使段不在 DOM 末尾），
    // 替代原"发言人一切换就开新段"→ 消除单词级小段穿插。本地麦（无 mic_id）空键，行为不变。
    // 2026-08-20 错乱修复：归段 key 必须用物理路 mic_id，不能用显示名——
    // 两路改成同名后名字 key 会撞车，不同话筒内容混进同一段，段标签的
    // mic_id 与段内内容错位 → 点标签改名改到错误的路（实测事故）。
    const hasMic = ev.mic_id !== undefined && ev.mic_id !== null;
    // 发言人身份 = 包头物理话筒 ID（2026-08-20：主机动态重分配话筒→端口，
    // 端口路号会对调，ID 才跟话筒实体走）；旧事件无 physical_id 回退端口路号。
    const physId = (ev.physical_id !== undefined && ev.physical_id !== null && ev.physical_id >= 0)
      ? ev.physical_id : null;
    // 显示名统一按当前命名表（/api/mic/names，key=物理ID），payload 旧 speaker
    // 只作兜底，SSE 重放的历史事件不再显示当时旧名。
    const spk = hasMic
      ? ((physId !== null && (window.__micNames || {})[String(physId)])
         || ev.speaker || `话筒${physId !== null ? physId : ev.mic_id + 1}`)
      : null;
    const stKey = physId !== null ? `p${physId}` : (hasMic ? `mic${ev.mic_id}` : "");
    let st = _txStates.get(stKey);
    if (!st) { st = { para: null, finalsText: "", lastFinalMs: 0 }; _txStates.set(stKey, st); }
    const stale = !st.para || !card.contains(st.para);
    const gapped = st.lastFinalMs > 0 &&
                   (nowMs - st.lastFinalMs) / 1000 > PARA_GAP_SEC;

    if (stale || gapped) {
      const para = document.createElement("div");
      para.className = "tx-para";
      const colorIdx = (physId !== null ? physId : (ev.mic_id ?? 0)) % 8;
      const spkHtml = spk
        ? `<span class="tx-spk" data-phys-id="${physId !== null ? physId : ""}" title="点击改名"` +
          ` style="color:${MIC_COLORS[colorIdx]};font-weight:600;cursor:pointer">${escHtml(spk)}</span> · `
        : "";
      para.innerHTML =
        `<div class="tx-meta">${spkHtml}<span class="tx-ts">${fmtClock(ev.ts)}</span></div>` +
        `<div class="tx-text"><span class="finals"></span><span class="live"></span></div>`;
      para.dataset.speaker = spk || "";
      card.appendChild(para);
      while (card.querySelectorAll(".tx-para").length > 50) card.firstChild.remove();
      st.para = para;
      st.finalsText = "";
      st.lastFinalMs = 0;
    }

    // 每次事件顺手把段标签刷成当前显示名（消除首屏命名表未加载的 race，
    // 以及改名后既有段落的名字漂移）；正在内联编辑时不覆盖
    const spkEl0 = st.para.querySelector(".tx-spk");
    if (spkEl0 && spk && !spkEl0.querySelector("input")) spkEl0.textContent = spk;

    const finalsEl = st.para.querySelector(".finals");
    const liveEl   = st.para.querySelector(".live");
    if (ev.is_final) {
      let chunk = ev.text || "";
      // 段首悬空标点清理：上游碎 final 常以逗号/句号开头，归段后落段首扎眼（2026-08-07）
      if (chunk && !st.finalsText) chunk = chunk.replace(/^[，。、；：！？,.;:!?\s]+/, "");
      if (chunk) {
        // final 定稿：包成 tx-final-flash span 追加（绿色短闪 0.5s fade 回主色）
        // 不再 finalsEl.textContent = 全文（会刷掉前面 span 的动画），改 appendChild
        const span = document.createElement("span");
        span.className = "tx-final-flash";
        span.textContent = chunk;
        if (ev.segment_id) span.dataset.segmentId = ev.segment_id;  // 声纹 diarization 晚到按此回填
        finalsEl.appendChild(span);
      }
      st.finalsText += chunk;
      liveEl.textContent = "";
      st.lastFinalMs = nowMs;
      // 篇幅自然分段：本段已饱和 → 标记下次 final 开新段
      const len = st.finalsText.length;
      const endedClean = PARA_ENDS_PUNCT.test(st.finalsText);
      if (len >= PARA_HARD_LIMIT || (len >= PARA_SOFT_LIMIT && endedClean)) {
        st.para = null;
      }
    } else if (ev.text) {
      // partial 增量 append：FunASR 2pass-online 每条 ev.text 是一段新词（非累积）
      // 包成 flash span 追加到 .live，触发逐字蹦橙黄闪光
      const span = document.createElement("span");
      span.className = "tx-flash";
      span.textContent = ev.text;
      liveEl.appendChild(span);
    }
    if (atBottom) card.scrollTop = card.scrollHeight;
  }
  // ── 声纹发言人回填（speaker_diarizer，回流自 av_understanding_mac S3-S5）──
  // 结果比 final 晚几秒到：按 segment_id 找到 span → 段还没发言人就给段打标；段已是别的
  // 发言人则把该 span 及其后的 span 切出成新段、本地麦段指针跟过去。最终效果与会议主机
  // 话筒号分段同构：.tx-spk 标签 + para.dataset.speaker，纪要归属零改动。
  // 本地麦键 ""（无 mic_id）才会收到 diarization；话筒号路径不发 segment。
  window.__spkAliases = window.__spkAliases || {};   // S<n> → 真名（当天）
  const spkLabel = (spk) => (window.__spkAliases[spk] || spk);
  function applyDiarization(ev) {
    if (ev.alias) {  // 改名广播：刷新所有该发言人的标签（纪要导出读标签文本，自动用真名）
      const { speaker_id: sid, name } = ev.alias;
      if (name) window.__spkAliases[sid] = name; else delete window.__spkAliases[sid];
      document.querySelectorAll(`.tx-spk[data-spk-id="${CSS.escape(sid)}"]`)
        .forEach(el => { if (!el.querySelector("input")) el.textContent = spkLabel(sid); });
      return;
    }
    const spk = ev.speaker_id, segId = ev.segment_id;
    if (!spk || !segId) return;  // 短段/嵌入失败 speaker_id=null：不猜
    const card = document.querySelector('[data-overview="transcript"] .strip-card-body');
    const span = card && card.querySelector(`.tx-final-flash[data-segment-id="${CSS.escape(segId)}"]`);
    if (!span) return;
    const para = span.closest(".tx-para");
    if (!para) return;
    const n = parseInt(String(spk).replace(/^S/, ""), 10);
    const color = MIC_COLORS[(Number.isFinite(n) ? n - 1 : 0) % MIC_COLORS.length];
    const cur = para.dataset.speaker || "";
    if (!cur) {
      // 整段尚无发言人：打标（段内之前的句子视为同一人——近似，首句前无更早信息）
      para.dataset.speaker = spk;
      const meta = para.querySelector(".tx-meta");
      if (meta && !meta.querySelector(".tx-spk")) {
        meta.insertAdjacentHTML("afterbegin",
          `<span class="tx-spk" data-voice="1" data-spk-id="${escHtml(spk)}" title="点击改名" style="color:${color};font-weight:600;cursor:pointer">${escHtml(spkLabel(spk))}</span> · `);
      }
      return;
    }
    if (cur === spk) return;
    // 段已属别人：从该 span 起切出新段
    const finalsEl = span.parentElement;
    const moving = [];
    for (let el = span; el; el = el.nextSibling) moving.push(el);
    const np = document.createElement("div");
    np.className = "tx-para";
    np.dataset.speaker = spk;
    np.innerHTML =
      `<div class="tx-meta"><span class="tx-spk" data-voice="1" data-spk-id="${escHtml(spk)}" title="点击改名" style="color:${color};font-weight:600;cursor:pointer">${escHtml(spkLabel(spk))}</span> · ` +
      `<span class="tx-ts">${fmtClock(ev.ts)}</span></div>` +
      `<div class="tx-text"><span class="finals"></span><span class="live"></span></div>`;
    const nf = np.querySelector(".finals");
    moving.forEach(el => nf.appendChild(el));
    // 正在输入的 partial 也跟过去（它属于最新发言）
    const oldLive = para.querySelector(".live"), newLive = np.querySelector(".live");
    if (oldLive && newLive) { while (oldLive.firstChild) newLive.appendChild(oldLive.firstChild); }
    para.after(np);
    const st = _txStates.get("");
    if (st && st.para === para) { st.para = np; st.finalsText = nf.textContent; }
    if (finalsEl && !finalsEl.textContent && !para.querySelector(".live")?.textContent) para.remove();
  }
  subscribeChannel("diarization", applyDiarization);

  function pushOverviewIntent(body) {
    const card = document.querySelector('[data-overview="intent"] .strip-card-body');
    if (!card) return;
    clearEmpty(card);
    pulseEl(card.closest(".strip-card"));
    const row = document.createElement("div");
    row.className = "row final";
    if (body.original_text) {
      const cmd = body.command ? ` → ${escHtml(JSON.stringify(body.command))}` : "";
      row.innerHTML = `<div>「${escHtml(body.original_text)}」${cmd}</div>`;
    } else if (body.target || body.action) {
      const cmd = [body.target, body.action].filter(Boolean).join(" · ");
      row.innerHTML = `<div>${escHtml(cmd)}</div>`;
    } else return;
    card.appendChild(row);
    while (card.querySelectorAll(".row").length > 4) card.firstChild.remove();
    card.scrollTop = card.scrollHeight;
  }
  function pushOverviewVideo(ev) {
    // 视频检测：浮窗在画格上而非卡片下，转发给 wall
    pushDetectionOverlay(ev.camera, ev.detections);
  }
  function pushOverviewHost(_ev) { /* 已迁移到 footer ticker，no-op */ }
  function clearEmpty(card) {
    const e = card.querySelector(".strip-empty, .overview-empty");
    if (e) e.remove();
  }

  // ── Node-RED iframe + 子页检测 ───────────────────────────────────────
  // 总览的 Node-RED hero 和 Node-RED 模块视图共用此逻辑
  let nodeRedPages = [];  // [{id, name, type}]
  let nodeRedNavAdded = false;  // 子项只加一次（init + setActive 都会触发本函数）
  // dashboard 2.0 (@flowfuse/node-red-dashboard) 是否真正挂载到 /dashboard/。
  // 5/20 客户演示发现黑框 "Cannot GET /dashboard/" 根因：3588 上 flows.json 含 ui-page 节点，
  // 但 plugin 没装到 userDir node_modules（/home/firefly/av_unified_mvp/node-red/）—— 启动日志
  // 长期 "Waiting for missing types: ui-base ui-page ..."。此 flag 探一次 /dashboard/，
  // 不可达就把 ui-page 从 selector 选项过滤掉、兜底 src 改用 /ui/（dashboard 1.x 正常服务）。
  let nodeRedDashboard2Reachable = null;  // null=未探, true/false=结果
  async function probeDashboard2() {
    if (nodeRedDashboard2Reachable !== null) return nodeRedDashboard2Reachable;
    try {
      // 用 GET 而非 HEAD：Node-RED express 对未注册路由有时 HEAD 返回 200 但 GET 404
      const r = await fetch(`http://${window.location.hostname}:1880/dashboard/`,
        { method: "GET", signal: AbortSignal.timeout(2000), cache: "no-store" });
      nodeRedDashboard2Reachable = r.ok;  // 200=true, 404=false
    } catch (_) {
      nodeRedDashboard2Reachable = false;  // 网络错或超时也按未挂载处理
    }
    return nodeRedDashboard2Reachable;
  }
  async function loadNodeRed() {
    const url = `http://${window.location.hostname}:1880/`;
    const frame = document.getElementById("nodered-frame");
    const fallback = document.getElementById("nodered-fallback");
    try {
      await fetch(url, { method: "HEAD", mode: "no-cors", signal: AbortSignal.timeout(2000) });
      frame.src = url;
      nodeRedLoaded = true;
      fallback.style.display = "none";
      frame.style.display = "block";
      detectNodeRedPages();
    } catch (_) {
      fallback.style.display = "block";
      frame.style.display = "none";
    }
  }
  async function detectNodeRedPages() {
    try {
      const r = await fetch(`http://${window.location.hostname}:1880/flows`, { signal: AbortSignal.timeout(3000) });
      if (!r.ok) return;
      const flows = await r.json();
      // 探 dashboard 2.0 实际是否挂载（plugin 没装时 /dashboard/ 是 404 "Cannot GET /dashboard/"）
      const d2ok = await probeDashboard2();
      // 1. 提取页面（dashboard 2.0 未挂载时丢弃 ui-page，避免 selector 默认选中后 iframe 404 黑框）
      const rawPages = flows.filter(n =>
        (n.type === "ui-page" && d2ok) || n.type === "ui_tab"
      );
      // 2. 数每页有多少 widget（用 group→page 链）
      const groupToPage = {};
      flows.filter(n => n.type === "ui-group" || n.type === "ui_group").forEach(g => {
        const parent = g.page || g.tab || g.parent;
        if (parent) groupToPage[g.id] = parent;
      });
      const widgetCount = {};
      flows.forEach(n => {
        const t = n.type || "";
        if (!t.startsWith("ui") || ["ui-base","ui_base","ui-theme","ui-page","ui_tab","ui-group","ui_group","ui-link"].includes(t)) return;
        const pid = groupToPage[n.group];
        if (pid) widgetCount[pid] = (widgetCount[pid] || 0) + 1;
      });
      nodeRedPages = rawPages.map(p => ({
        id: p.id, name: p.name || p.id, type: p.type,
        widgets: widgetCount[p.id] || 0,
        order: typeof p.order === "number" ? p.order : 999,
      }));

      // 给左导航的 Node-RED 项加子项（≥ 2 页时，只加一次）
      if (!nodeRedNavAdded && nodeRedPages.length >= 2) {
        nodeRedPages.forEach(p => {
          const subId = "__nodered_" + p.id;
          const item = addNavItem({
            id: subId, title: p.name, icon: "›",
            group: "fixed", sub: true, parent: "__nodered",
          });
          item.addEventListener("click", () => {
            navigateNodeRed(p, "nodered-frame");
            setActive("__nodered");
          });
        });
        nodeRedNavAdded = true;
      }
      // 给总览页的 Node-RED hero 填充选择器
      buildOverviewNodeRedSelector();
    } catch (_) { /* Node-RED 未起 */ }
  }

  function pageUrlPath(p) {
    const slug = encodeURIComponent((p.name || p.id).replace(/\s+/g, "-"));
    // dashboard 2.0 (ui-page) SPA HTML 没设 <base href>，资源用相对路径 ./assets/...。
    // iframe URL 若是 /dashboard/page/<slug>（无尾斜杠），浏览器把目录解析为 /dashboard/page/，
    // 资源就请求到 /dashboard/page/assets/... → 不存在 → SPA fallback 返回 text/html → MIME 错。
    // 只用 /dashboard/（带尾斜杠）SPA 入口；vue-router 启动后默认首页（多 page 时 SPA 自带导航）。
    return p.type === "ui-page" ? "/dashboard/" : `/ui/#!/${slug}`;
  }
  function navigateNodeRed(page, frameId) {
    const f = document.getElementById(frameId);
    if (!f) return;
    f.src = `http://${window.location.hostname}:1880${pageUrlPath(page)}`;
  }

  // 总览页 Node-RED 区：先探活，再交给 selector 加载具体页
  let _noderedReprobeTimer = null;
  async function loadOverviewNodeRed() {
    const url = `http://${window.location.hostname}:1880/`;
    const frame = document.getElementById("overview-nodered-frame");
    const fallback = document.getElementById("overview-nodered-fallback");
    if (!frame) return;
    try {
      await fetch(url, { method: "HEAD", mode: "no-cors", signal: AbortSignal.timeout(2000) });
      fallback.style.display = "none";
      frame.style.display = "block";
      // 不抢先设 src 了；让 buildOverviewNodeRedSelector 决定加载哪页
      // 如果 5 秒内 selector 还没设 src，按 dashboard 2.0 是否可达兜底（不可达就用 1.x /ui/）
      setTimeout(async () => {
        if (frame.src === "about:blank" || !frame.src) {
          const d2 = await probeDashboard2();
          const path = d2 ? "/dashboard/" : "/ui/";
          frame.src = `http://${window.location.hostname}:1880${path}`;
        }
      }, 5000);
      // 探活成功 — 停掉 re-probe 定时器
      if (_noderedReprobeTimer) { clearInterval(_noderedReprobeTimer); _noderedReprobeTimer = null; }
      // 同时拉一次 flows 填左导航子项 + 总览页选源（之前 init 时探不到导致 nav 缺）
      detectNodeRedPages();
    } catch (_) {
      fallback.style.display = "flex";
      frame.style.display = "none";
      // dashboard 早于 Node-RED 启动是常态（user 先开浏览器再 ./start.command），
      // 启动 15s 周期 re-probe 直到探活成功（成功后 timer 自停）。
      if (!_noderedReprobeTimer) {
        _noderedReprobeTimer = setInterval(loadOverviewNodeRed, 15000);
      }
    }
  }

  function buildOverviewNodeRedSelector() {
    const sel = document.getElementById("nodered-page-select");
    const frame = document.getElementById("overview-nodered-frame");
    if (!sel || !nodeRedPages.length) return;
    sel.innerHTML = "";
    // 排序规则：先按 page.order（Node-RED 用户在 flows.json 设的优先级，数字小者前）；
    // 同 order 时 dashboard 2.0 (ui-page) 优先；最后才用 widgets 数兜底。
    // 让"AI 看板"这种新版 dashboard 2.0 主页可以稳定排第一。
    const order = [...nodeRedPages].sort((a, b) =>
      (a.order - b.order)
      || ((a.type === "ui-page") === (b.type === "ui-page") ? 0 : (a.type === "ui-page" ? -1 : 1))
      || (b.widgets - a.widgets)
    );
    order.forEach(p => {
      const opt = document.createElement("option");
      opt.value = p.id;
      const tag = p.type === "ui-page" ? "[2.0]" : "[1.x]";
      opt.textContent = `${tag} ${p.name}  (${p.widgets} 件)`;
      opt.dataset.type = p.type;
      sel.appendChild(opt);
    });
    sel.onchange = () => {
      const p = nodeRedPages.find(x => x.id === sel.value);
      if (p) navigateNodeRed(p, "overview-nodered-frame");
    };
    // 默认载入 widgets 最多的页
    const first = order[0];
    if (first && frame) {
      sel.value = first.id;
      navigateNodeRed(first, "overview-nodered-frame");
    }
  }

  // ── 活动闪动：模块卡片收到事件时短暂闪光 ──────────────────────────────
  function pulseEl(el) {
    if (!el) return;
    el.classList.remove("pulse");
    void el.offsetWidth;  // 强制 reflow，重启动画
    el.classList.add("pulse");
  }

  function escHtml(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // ── GridStack 总览布局（回合 27 P1.1）+ 可见性 toggle（回合 27 P1.2）──
  // 用 .drag-handle 作把手；min-w/min-h 在 HTML 的 gs-min-w/gs-min-h；
  // 拖完/调完尺寸 → save 到 localStorage["av_overview_layout"]，刷新即恢复。
  const LAYOUT_KEY = "av_overview_layout";
  const VISIBILITY_KEY = "av_overview_visibility";
  const MODULES_META = [
    { id: "overview-nodered",       title: "Node-RED 中控" },
    { id: "overview-video",         title: "视频墙" },
    { id: "overview-transcript",    title: "语意理解 · 转写" },
    { id: "overview-intent",        title: "意图 / 控制流" },
    { id: "overview-scene",         title: "视觉深思 · 场景分析" },
    { id: "overview-husion",        title: "husion 视频墙控制" },
    { id: "overview-openvocab",     title: "开放词检测" },
    { id: "overview-online-stream", title: "在线视频源" },
    { id: "overview-add-source",    title: "添加视频源" },
    { id: "overview-lan-scan",      title: "LAN 扫描" },
    { id: "overview-quick-control", title: "快捷控制（中控）" },
  ];
  const hiddenCardPos = {};  // 隐藏期间记位置，重显时还原
  function initOverviewGrid() {
    if (typeof GridStack === "undefined") {
      console.warn("[grid] gridstack lib 未加载，总览仍可用但不能拖动");
      return;
    }
    const grid = GridStack.init({
      column: 12,
      cellHeight: 70,
      margin: 5,
      handle: ".drag-handle",
      resizable: { handles: "se,sw,e,s,w" },  // 角 + 四边可拉
      float: false,
      animate: true,
      minRow: 1,
    }, "#modules-stack");
    // restore（addRemove=false 不删 HTML 默认 widget，只覆盖位置/尺寸）
    try {
      const saved = localStorage.getItem(LAYOUT_KEY);
      if (saved) grid.load(JSON.parse(saved), false);
    } catch (e) { console.warn("[grid] layout restore failed", e); }
    // persist
    grid.on("change added removed resizestop dragstop", () => {
      try {
        localStorage.setItem(LAYOUT_KEY, JSON.stringify(grid.save(false)));
      } catch (e) {}
    });
    window.__overviewGrid = grid;
  }

  // ── P1.2 可见性 toggle ─────────────────────────────────────────────
  function loadVisibility() {
    try { return JSON.parse(localStorage.getItem(VISIBILITY_KEY) || "{}"); }
    catch (e) { return {}; }
  }
  function saveVisibility(s) {
    try { localStorage.setItem(VISIBILITY_KEY, JSON.stringify(s)); } catch (e) {}
  }
  function getGridItem(id) {
    return document.querySelector(`.grid-stack-item[gs-id="${id}"]`);
  }
  function hideModule(id) {
    const grid = window.__overviewGrid;
    const wrap = getGridItem(id);
    if (!grid || !wrap || wrap.style.display === "none") return;
    const node = wrap.gridstackNode;
    if (node) hiddenCardPos[id] = { x: node.x, y: node.y, w: node.w, h: node.h };
    grid.removeWidget(wrap, false);  // false = 不删 DOM
    wrap.style.display = "none";
    const s = loadVisibility(); s[id] = false; saveVisibility(s);
  }
  function showModule(id) {
    if (isProfileHidden(id)) return;  // 形态隐藏的模块不给开回（防布局弹窗/show-all 绕过）
    const grid = window.__overviewGrid;
    const wrap = getGridItem(id);
    if (!grid || !wrap) return;
    if (wrap.style.display !== "none") return;
    wrap.style.display = "";
    grid.makeWidget(wrap);
    const pos = hiddenCardPos[id];
    if (pos) { grid.update(wrap, pos); delete hiddenCardPos[id]; }
    const s = loadVisibility(); s[id] = true; saveVisibility(s);
  }
  function toggleModule(id) {
    const wrap = getGridItem(id);
    if (!wrap) return;
    if (wrap.style.display === "none") showModule(id);
    else hideModule(id);
    buildLayoutPopupBody();
  }
  function injectHideButtons() {
    MODULES_META.forEach(m => {
      const card = document.querySelector(`.module-card[data-module-id="${m.id}"]`);
      if (!card) return;
      const actions = card.querySelector(".module-actions");
      if (!actions || actions.querySelector(".module-hide-btn")) return;
      const btn = document.createElement("button");
      btn.className = "module-hide-btn";
      btn.title = "隐藏此模块（可在 ⚙ 布局 找回）";
      btn.textContent = "×";
      btn.onclick = (e) => { e.stopPropagation(); hideModule(m.id); buildLayoutPopupBody(); };
      actions.appendChild(btn);
    });
  }
  function buildLayoutPopupBody() {
    const body = document.getElementById("layout-popup-body");
    if (!body) return;
    body.innerHTML = "";
    MODULES_META.forEach(m => {
      const lbl = document.createElement("label");
      if (isProfileHidden(m.id)) {
        // 形态隐藏：灰置不可点（形态决定非用户偏好，不给开回的入口）
        lbl.innerHTML = `<input type="checkbox" disabled> ${escHtml(m.title)}`;
        lbl.style.opacity = "0.35";
        lbl.style.cursor = "not-allowed";
        lbl.title = "当前产品形态不含此模块";
        body.appendChild(lbl);
        return;
      }
      const wrap = getGridItem(m.id);
      const visible = wrap && wrap.style.display !== "none";
      lbl.innerHTML = `<input type="checkbox" ${visible ? "checked" : ""}> ${escHtml(m.title)}`;
      lbl.querySelector("input").onchange = () => toggleModule(m.id);
      body.appendChild(lbl);
    });
  }
  function setupLayoutPopup() {
    const btn = document.getElementById("overview-layout-btn");
    const popup = document.getElementById("overview-layout-popup");
    if (!btn || !popup) return;
    btn.onclick = (e) => {
      e.stopPropagation();
      const showing = popup.style.display !== "none";
      popup.style.display = showing ? "none" : "block";
      if (!showing) buildLayoutPopupBody();
    };
    document.addEventListener("click", (e) => {
      if (!popup.contains(e.target) && e.target !== btn) popup.style.display = "none";
    });
    document.getElementById("layout-show-all").onclick = (e) => {
      e.stopPropagation();
      MODULES_META.forEach(m => { if (!isProfileHidden(m.id)) showModule(m.id); });
      buildLayoutPopupBody();
    };
    document.getElementById("layout-reset").onclick = (e) => {
      e.stopPropagation();
      if (!confirm("重置布局会清除拖动+尺寸+显示状态，恢复默认。继续？")) return;
      localStorage.removeItem(LAYOUT_KEY);
      localStorage.removeItem(VISIBILITY_KEY);
      location.reload();
    };
  }
  function applyVisibility() {
    const s = loadVisibility();
    MODULES_META.forEach(m => { if (s[m.id] === false) hideModule(m.id); });
  }

  // ── 话筒就地改名（2026-08-20 用户需求：点转写里的"话筒N"标签直接改）──────
  // 点击 .tx-spk → 内联输入框 → Enter/失焦提交 POST /api/mic/rename（后端写
  // data/mic_names.json 持久化 + MQTT 热更新采集模块，不断流）→ 本页同话筒
  // 标签全部刷新；Esc 取消；提交空值 = 恢复默认"话筒N"。
  // ── 服务器附件下载（2026-08-20）：HTTP 站点上 blob+download 的下载被
  // Chrome 安全挂起成"未确认 xxx.crdownload"，改 form POST /api/download
  // 走 Content-Disposition 附件下载。textarea 而非 input——input value 提交
  // 时换行会被浏览器规范化剥离。
  function serverDownload(filename, content) {
    const f = document.createElement("form");
    f.method = "POST"; f.action = "/api/download"; f.style.display = "none";
    const fn = document.createElement("input");
    fn.type = "hidden"; fn.name = "filename"; fn.value = filename;
    const ta = document.createElement("textarea");
    ta.name = "content"; ta.value = content;
    f.appendChild(fn); f.appendChild(ta);
    document.body.appendChild(f);
    f.submit();
    setTimeout(() => document.body.removeChild(f), 1000);
  }

  // 复制文本：navigator.clipboard 在 HTTP 非安全上下文不可用（Chrome 限
  // HTTPS/localhost，2026-08-20 用户实测"复制失败"），降级 execCommand("copy")
  async function copyText(text) {
    if (navigator.clipboard && window.isSecureContext) {
      try { await navigator.clipboard.writeText(text); return true; } catch (_) {}
    }
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.cssText = "position:fixed;left:-9999px;top:0";
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    let ok = false;
    try { ok = document.execCommand("copy"); } catch (_) {}
    document.body.removeChild(ta);
    return ok;
  }

  function setupMicRename() {
    const card = document.querySelector('[data-overview="transcript"] .strip-card-body');
    if (!card) return;
    // 加载当前命名表（合并层）——所有显示名以此为准
    window.__micNames = window.__micNames || {};
    fetch("/api/mic/names").then(r => r.json())
      .then(res => { if (res && res.ok) window.__micNames = res.mic_names || {}; })
      .catch(() => {});
    fetch("/api/speaker/aliases").then(r => r.json())
      .then(res => { if (res && res.ok) window.__spkAliases = res.aliases || {}; })
      .catch(() => {});
    card.addEventListener("click", (e) => {
      const spkEl = e.target.closest(".tx-spk");
      if (!spkEl || spkEl.querySelector("input")) return;
      // 两种可改名标签：物理话筒 ID（会议主机）/ 声纹编号 S<n>（本机麦）
      const isVoice = !!spkEl.dataset.spkId;
      if (!isVoice && !spkEl.dataset.physId) return;
      const physId = isVoice ? null : parseInt(spkEl.dataset.physId, 10);
      const spkId = isVoice ? spkEl.dataset.spkId : null;
      const old = spkEl.textContent;
      const input = document.createElement("input");
      input.value = old;
      input.maxLength = 16;
      input.style.cssText = "width:96px;background:transparent;border:1px solid currentColor;" +
                            "color:inherit;font:inherit;border-radius:3px;padding:0 4px";
      spkEl.textContent = "";
      spkEl.appendChild(input);
      input.focus();
      input.select();
      let done = false;
      const finish = (commit) => {
        if (done) return;
        done = true;
        const name = input.value.trim();
        spkEl.textContent = old;  // 先复原旧名，提交成功后统一刷新
        if (!commit || name === old) return;
        if (isVoice) {
          // 声纹发言人：落当天别名表 + SSE 广播，applyDiarization 收到 alias 统一刷新
          fetch("/api/speaker/alias", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ speaker_id: spkId, name: name === spkId ? "" : name }),
          }).catch(() => {});
          return;
        }
        fetch("/api/mic/rename", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ physical_id: physId, name }),
        }).then(r => r.json()).then(res => {
          if (!res || !res.ok) return;
          window.__micNames = res.mic_names || window.__micNames;  // 同步命名表
          const label = (window.__micNames || {})[String(physId)] || `话筒${physId}`;
          document.querySelectorAll(`.tx-spk[data-phys-id="${physId}"]`)
            .forEach(el => { if (!el.querySelector("input")) el.textContent = label; });
        }).catch(() => {});
      };
      input.onkeydown = (ev2) => {
        if (ev2.key === "Enter") finish(true);
        else if (ev2.key === "Escape") finish(false);
      };
      input.onblur = () => finish(true);
    });
  }

  // CR-DIG7201 第7条：按 app_profile 隐藏无关卡，纯纪要产品出厂界面就该干净。
  // full 零回归；meeting_asr 只留纪要相关卡（转写卡——纪要走卡内"生成纪要"按钮弹窗，
  // 发言人分段也在转写卡内）。用 removeWidget 让 GridStack 重排无空洞；
  // 不写 VISIBILITY_KEY —— 这是形态决定非用户偏好，切回 full 自然全显、也不污染用户手动偏好。
  const PROFILE_KEEP = {
    meeting_asr: new Set(["overview-transcript"]),
  };
  // 模块是否被当前 profile 形态隐藏（形态决定，非用户偏好，用户不可开回）
  function isProfileHidden(id) {
    const keep = PROFILE_KEEP[document.body.dataset.appProfile || "full"];
    return !!keep && !keep.has(id);
  }
  function applyProfileVisibility() {
    const prof = document.body.dataset.appProfile || "full";
    const keep = PROFILE_KEEP[prof];
    if (!keep) return;  // full 或未知 profile 不动
    // 纪要机形态下顶栏"旧页"链接与"客户视图"开关无意义（客户视图是 full demo 的
    // 演示脸切换，此形态卡已被 profile 移除，点了只会乱版）——2026-08-20 用户拍板去掉
    const cvBtn = document.getElementById("cv-toggle");
    if (cvBtn) cvBtn.style.display = "none";
    const legacy = document.querySelector('a[href="/transcript"]');
    if (legacy && legacy.parentElement) legacy.parentElement.style.display = "none";
    const grid = window.__overviewGrid;
    MODULES_META.forEach(m => {
      if (keep.has(m.id)) return;
      const wrap = getGridItem(m.id);
      if (wrap && wrap.style.display !== "none") {
        if (grid) grid.removeWidget(wrap, false);  // false = 不删 DOM，只移出网格
        wrap.style.display = "none";
      }
    });
  }

  // ── 客户视图开关（顶栏 toggle · 默认关）──────────────────────────
  // 进入客户视图：备份当前可见性偏好，仅显示 CUSTOMER_VIEW_MODULES 列出的模块
  // 退出客户视图：把备份的可见性偏好写回，并按其重新 apply
  const CUSTOMER_VIEW_KEY = "customer_view";
  const CV_VISIBILITY_BACKUP_KEY = "av_overview_visibility__cv_backup";
  // 任务定义的客户视图保留集（husion / openvocab 若 future 加入 MODULES_META 也会自动尊重）
  const CUSTOMER_VIEW_MODULES = new Set([
    "overview-video",
    "overview-intent",
    "overview-quick-control",
    "overview-online-stream",
    "overview-husion",
    "overview-openvocab",
  ]);

  function setCustomerView(on) {
    document.body.classList.toggle("customer-view", on);
    const btn = document.getElementById("cv-toggle");
    const lbl = document.getElementById("cv-toggle-label");
    if (btn) btn.classList.toggle("on", !!on);
    if (lbl) lbl.textContent = on ? "客户视图 · 开" : "客户视图";

    if (on) {
      // 备份用户原可见性偏好（仅在尚未备份时；防止反复 toggle 把 CV 强制态当成原始）
      if (localStorage.getItem(CV_VISIBILITY_BACKUP_KEY) === null) {
        localStorage.setItem(
          CV_VISIBILITY_BACKUP_KEY,
          localStorage.getItem(VISIBILITY_KEY) || "{}"
        );
      }
      MODULES_META.forEach(m => {
        if (CUSTOMER_VIEW_MODULES.has(m.id)) showModule(m.id);
        else hideModule(m.id);
      });
    } else {
      // 还原：先把备份写回 VISIBILITY_KEY，再 showAll 清干净 + applyVisibility 重放
      const backup = localStorage.getItem(CV_VISIBILITY_BACKUP_KEY);
      if (backup !== null) {
        try { localStorage.setItem(VISIBILITY_KEY, backup); } catch (_) {}
        localStorage.removeItem(CV_VISIBILITY_BACKUP_KEY);
      }
      MODULES_META.forEach(m => showModule(m.id));  // 重置为全显
      applyVisibility();                             // 然后按用户偏好再隐藏
    }
    localStorage.setItem(CUSTOMER_VIEW_KEY, on ? "1" : "0");
    // 刷新布局 popup（如果开着）
    buildLayoutPopupBody();
  }

  function setupCustomerViewToggle() {
    const btn = document.getElementById("cv-toggle");
    if (!btn) return;
    btn.addEventListener("click", () => {
      const on = !document.body.classList.contains("customer-view");
      setCustomerView(on);
    });
    // 首次加载：按 localStorage 还原
    const saved = localStorage.getItem(CUSTOMER_VIEW_KEY);
    if (saved === "1") setCustomerView(true);
  }

  // 给页面 / 调试暴露
  window.setCustomerView = setCustomerView;

  // ── P1.3 添加 / 修改 / 删除视频源 ─────────────────────────────────
  // url 反推：rtsp://user:pwd@ip:port/Streaming/Channels/N → IPC；rtsp://ip:port/path → 分布式；纯数字 → 本机
  function parseSourceUrl(url) {
    if (!url) return null;
    let m = url.match(/^rtsp:\/\/([^:]+):([^@]*)@([^:/]+):(\d+)\/Streaming\/Channels\/(\d+)/);
    if (m) return { type: "ipc", user: m[1], pwd: m[2], ip: m[3], port: m[4], ch: m[5] };
    m = url.match(/^rtsp:\/\/([^:/]+)(?::(\d+))?\/(.+)$/);
    if (m) return { type: "dist", ip: m[1], port: m[2] || "554", path: m[3] };
    if (/^\d+$/.test(url)) return { type: "local", dev: url };
    return null;
  }

  function setupAddSourceForm() {
    const typeSel = document.getElementById("src-type");
    const fields  = document.querySelectorAll(".src-fields");
    const preview = document.getElementById("src-url-preview");
    const nameIn  = document.getElementById("src-name");
    const btn     = document.getElementById("src-add-btn");
    const cancelBtn = document.getElementById("src-cancel-edit");
    const msg     = document.getElementById("src-add-msg");
    if (!typeSel || !btn) return;

    let mode = "add";        // "add" | "edit"
    let editingName = null;  // edit 模式下原 name（前端不改 name 仅改 url）

    function val(id) { const e = document.getElementById(id); return e ? e.value.trim() : ""; }
    function setVal(id, v) { const e = document.getElementById(id); if (e) e.value = v == null ? "" : v; }

    function refreshFields() {
      fields.forEach(f => f.style.display = (f.dataset.fields === typeSel.value) ? "flex" : "none");
      refreshPreview();
    }
    function buildUrl() {
      const t = typeSel.value;
      if (t === "ipc") {
        const ip = val("src-ipc-ip"), port = val("src-ipc-port") || "554";
        const user = val("src-ipc-user"), pwd = document.getElementById("src-ipc-pwd").value;
        const ch = val("src-ipc-ch");
        return (ip && ch) ? `rtsp://${user}:${pwd}@${ip}:${port}/Streaming/Channels/${ch}` : "";
      } else if (t === "dist") {
        const ip = val("src-dist-ip"), port = val("src-dist-port") || "554";
        const path = val("src-dist-path").replace(/^\//, "");
        return (ip && path) ? `rtsp://${ip}:${port}/${path}` : "";
      } else {
        return val("src-local-dev") || "0";
      }
    }
    function refreshPreview() {
      const u = buildUrl();
      preview.textContent = u || "—";
      return u;
    }

    function clearForm() {
      ["src-name", "src-ipc-ip", "src-ipc-pwd", "src-ipc-ch",
       "src-dist-ip", "src-dist-path"].forEach(id => setVal(id, ""));
      setVal("src-ipc-port", "554"); setVal("src-ipc-user", "admin");
      setVal("src-dist-port", "554"); setVal("src-local-dev", "0");
      typeSel.value = "ipc"; refreshFields();
    }
    function setMode(newMode, name) {
      mode = newMode;
      editingName = (newMode === "edit") ? name : null;
      if (newMode === "edit") {
        btn.textContent = `保存修改（${name}）`;
        cancelBtn.style.display = "";
        // 5/13 改：允许 rename — 后端 _update_source 已支持 old_name 协议
        nameIn.disabled = false;
        nameIn.title = "可改名；保存时若新名与已有摄像头冲突将失败";
      } else {
        btn.textContent = "添加并启动";
        cancelBtn.style.display = "none";
        nameIn.disabled = false;
        nameIn.title = "";
      }
    }
    // 由 video tile 的 ✎ 按钮调用
    function enterEditMode(ep) {
      const parsed = parseSourceUrl(ep.src_url);
      if (!parsed) {
        msg.textContent = `无法解析 url: ${ep.src_url || "（空）"}`; msg.className = "msg err";
        return;
      }
      typeSel.value = parsed.type; refreshFields();
      setVal("src-name", ep.name);
      if (parsed.type === "ipc") {
        setVal("src-ipc-ip", parsed.ip); setVal("src-ipc-port", parsed.port);
        setVal("src-ipc-user", parsed.user); setVal("src-ipc-pwd", parsed.pwd);
        setVal("src-ipc-ch", parsed.ch);
      } else if (parsed.type === "dist") {
        setVal("src-dist-ip", parsed.ip); setVal("src-dist-port", parsed.port);
        setVal("src-dist-path", parsed.path);
      } else {
        setVal("src-local-dev", parsed.dev);
      }
      refreshPreview();
      setMode("edit", ep.name);
      msg.textContent = `编辑中: ${ep.name}（改完点保存修改）`; msg.className = "msg";
      // 滚到表单
      const card = document.querySelector('.module-card[data-module-id="overview-add-source"]');
      if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
    }
    function confirmDelete(name) {
      if (!confirm(`确认删除摄像头 "${name}"？\n\n该路视频会从视频墙立即消失，重新添加可恢复。`)) return;
      fetch("/mqtt/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic: "av/video/source/remove", payload: { name } }),
      }).then(r => r.json()).then(j => {
        msg.textContent = j.ok ? `✓ 已删除 ${name}` : `删除失败: ${j.error || "未知"}`;
        msg.className = "msg " + (j.ok ? "ok" : "err");
      }).catch(e => {
        msg.textContent = `网络错误: ${e.message}`; msg.className = "msg err";
      });
    }

    typeSel.onchange = refreshFields;
    document.querySelectorAll(".add-source-form input").forEach(i => i.addEventListener("input", refreshPreview));
    cancelBtn.onclick = () => { clearForm(); setMode("add"); msg.textContent = ""; msg.className = "msg"; };

    btn.onclick = async () => {
      const url = refreshPreview();
      const name = nameIn.value.trim();
      if (!url || url === "—") { msg.textContent = "请填写完整字段"; msg.className = "msg err"; return; }
      if (!name) { msg.textContent = "请填写摄像头名称"; msg.className = "msg err"; return; }
      const topic = (mode === "edit") ? "av/video/source/update" : "av/video/source/add";
      msg.textContent = (mode === "edit" ? "保存中…" : "添加中…"); msg.className = "msg";
      // edit 模式带 old_name 让后端按旧名查找；name 字段是新名（可能与旧名同）。
      // add 模式 old_name 缺省，后端忽略。
      const payload = (mode === "edit")
        ? { old_name: editingName, name, url, enabled: true }
        : { name, url, enabled: true };
      try {
        const r = await fetch("/mqtt/publish", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ topic, payload }),
        });
        const j = await r.json();
        if (j.ok) {
          msg.textContent = mode === "edit" ? `✓ 已修改 ${name}` : `✓ 已添加 ${name}（视频墙立即出图）`;
          msg.className = "msg ok";
          if (mode === "edit") { clearForm(); setMode("add"); }
          else nameIn.value = "";
        } else {
          msg.textContent = `失败: ${j.error || "未知"}`; msg.className = "msg err";
        }
      } catch (e) {
        msg.textContent = `网络错误: ${e.message}`; msg.className = "msg err";
      }
    };

    // 由 LAN 扫描的 →IPC / →分布式 按钮调用：清空 + 切到 add 模式 + 预填 IP
    function fillFromLanScan(ip, type) {
      clearForm(); setMode("add");
      typeSel.value = type; refreshFields();
      if (type === "ipc") {
        setVal("src-ipc-ip", ip); setVal("src-ipc-port", "554");
        setVal("src-name", `IPC-${ip.split(".").pop()}`);
      } else if (type === "dist") {
        setVal("src-dist-ip", ip); setVal("src-dist-port", "554");
        setVal("src-name", `分布式-${ip.split(".").pop()}`);
      }
      refreshPreview();
      msg.textContent = `已预填 ${ip}（${type === "ipc" ? "请补通道号 + 密码" : "请补路径"}）`;
      msg.className = "msg";
      const card = document.querySelector('.module-card[data-module-id="overview-add-source"]');
      if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
      setTimeout(() => {
        const focusId = type === "ipc" ? "src-ipc-ch" : "src-dist-path";
        document.getElementById(focusId)?.focus();
      }, 400);
    }

    refreshFields();
    // 暴露给 renderWall 内的 ✎/✕ 按钮 + LAN 扫描的 → IPC/→ 分布式 按钮使用
    window.__videoSourceForm = { enterEditMode, confirmDelete, fillFromLanScan };
  }

  // ── 初始化 ───────────────────────────────────────────────────────────
  buildNavSkeleton();
  refreshModulesPill();
  // 默认页是总览，立即加载 Node-RED hero（异步）
  loadOverviewNodeRed();
  detectNodeRedPages();
  // ── P1.4 LAN 扫描卡 ────────────────────────────────────────────────
  function setupLanScan() {
    const subnetIn = document.getElementById("lan-scan-subnet");
    const btn      = document.getElementById("lan-scan-btn");
    const badge    = document.getElementById("lan-scan-badge");
    const progEl   = document.getElementById("lan-scan-progress");
    const barFill  = document.getElementById("lan-scan-bar");
    const progText = document.getElementById("lan-scan-progress-text");
    const results  = document.getElementById("lan-scan-results");
    if (!btn) return;

    function setScanning(yes) {
      btn.disabled = yes;
      btn.textContent = yes ? "扫描中…" : "▶ 扫描";
      progEl.style.display = yes ? "flex" : "none";
      badge.textContent = yes ? "扫描中" : "就绪";
      badge.className = "module-badge" + (yes ? " warn" : "");
    }

    btn.onclick = () => {
      const subnet = subnetIn.value.trim();
      setScanning(true);
      barFill.style.width = "0%";
      progText.textContent = "启动…";
      results.innerHTML = '<div class="lan-scan-empty">扫描中，请稍候…</div>';
      fetch("/mqtt/publish", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: "av/system/lan_scan/cmd",
          payload: subnet ? { subnet } : {},
        }),
      }).catch(e => {
        progText.textContent = `网络错误: ${e.message}`;
        setScanning(false);
      });
    };

    subscribeChannel("lan_scan", (ev) => {
      if (ev.type === "progress") {
        const pct = Math.round(ev.scanned * 100 / Math.max(ev.total, 1));
        barFill.style.width = pct + "%";
        progText.textContent = `${ev.scanned}/${ev.total} · 存活 ${ev.alive}`;
      } else if (ev.type === "result") {
        setScanning(false);
        barFill.style.width = "100%";
        progText.textContent = `✓ 完成 · ${ev.alive_hosts.length} 台 · ${ev.duration_s}s`;
        renderScanResults(ev);
      } else if (ev.type === "error") {
        setScanning(false);
        progText.textContent = `✗ ${ev.error}`;
        results.innerHTML = `<div class="lan-scan-empty" style="color:var(--warn)">扫描失败：${escHtml(ev.error || "未知")}</div>`;
      }
    });

    function renderScanResults(ev) {
      if (!ev.alive_hosts || !ev.alive_hosts.length) {
        results.innerHTML = `<div class="lan-scan-empty">未发现存活主机（子网 ${escHtml(ev.subnet)}）</div>`;
        return;
      }
      let html = '<table><thead><tr><th style="width:140px">IP</th><th>开放端口</th><th style="width:200px">操作</th></tr></thead><tbody>';
      for (const h of ev.alive_hosts) {
        const ports = h.ports || [];
        const has554 = ports.includes(554);
        const portsHtml = ports.map(p =>
          p === 554 ? `<span class="port-rtsp">${p} RTSP</span>` : String(p)
        ).join(", ");
        const actions = has554
          ? `<div class="actions">` +
            `<button data-fill="ipc" data-ip="${escHtml(h.ip)}">→ IPC</button>` +
            `<button data-fill="dist" data-ip="${escHtml(h.ip)}">→ 分布式</button>` +
            `</div>`
          : '<span class="no-rtsp">— 无 RTSP —</span>';
        html += `<tr><td class="ip">${escHtml(h.ip)}</td><td class="ports">${portsHtml}</td><td>${actions}</td></tr>`;
      }
      html += "</tbody></table>";
      results.innerHTML = html;
      results.querySelectorAll("[data-fill]").forEach(el => {
        el.onclick = () => {
          window.__videoSourceForm?.fillFromLanScan(el.dataset.ip, el.dataset.fill);
        };
      });
    }
  }

  // ── 5/14 Sub-7 husion 视频墙控制面板 ──────────────────────────────
  // 10s 轮询 /api/husion/state；前台可见才拉，避免 idle tab 一直打 husion。
  // 9 设备列表（id 5001-5009：name + ip + dev_type + online）+ 5 个场景按钮（rx_id=5008）。
  function setupHusionPanel() {
    // meeting_asr 纪要版无 husion 场景：卡片已隐藏，轮询也不起（避免 /api/husion/state 持续 502）
    if ((document.body.dataset.appProfile || "full") === "meeting_asr") return;
    const card = document.querySelector('[data-overview="husion"]');
    if (!card) return;
    const devEl   = card.querySelector("#husion-devices");
    const sceneEl = card.querySelector("#husion-scenes");
    const badge   = document.getElementById("overview-husion-badge");
    if (!devEl || !sceneEl) return;

    function setBadge(text, color) {
      if (!badge) return;
      badge.textContent = text;
      badge.style.color = color || "";
    }

    async function refresh() {
      if (document.hidden) return;
      try {
        const r = await fetch("/api/husion/state", { cache: "no-store" });
        if (!r.ok) {
          setBadge(`${r.status}`, "var(--warn,#f57c00)");
          devEl.innerHTML = `<div style="color:var(--warn);font-size:11px">husion 不可达 (HTTP ${r.status})</div>`;
          return;
        }
        const data = await r.json();
        if (!data.ok) {
          setBadge("错误", "var(--warn,#f57c00)");
          devEl.innerHTML = `<div style="color:var(--warn);font-size:11px">${escHtml(data.error || "未知错误")}</div>`;
          return;
        }
        renderDevices(data.devices || [], data.wall || []);
      } catch (e) {
        setBadge("离线", "var(--dim)");
        devEl.innerHTML = `<div style="color:var(--dim);font-size:11px">${escHtml(String(e))}</div>`;
      }
    }

    function renderDevices(devices, wall) {
      // husion get_all_equ data 字段大致：id, name, ip, dev_type, online (0/1), hls...
      // 容错：字段缺失时回退到 "?".
      if (!Array.isArray(devices) || devices.length === 0) {
        devEl.innerHTML = `<div style="color:var(--dim);font-size:11px">无设备</div>`;
        setBadge("0/0", "var(--dim)");
        return;
      }
      // wall 是 list[{wall_id, win_id, tx_id, tx_name, ...}]
      const wallTx = new Set();
      (wall || []).forEach(w => { if (w.tx_id) wallTx.add(String(w.tx_id)); });

      const html = devices.map(d => {
        const id   = String(d.id || d.equ_id || "");
        const name = d.name || d.equ_name || "(无名)";
        const ip   = d.ip || "";
        const type = d.dev_type || d.type || "";
        // online 字段实际格式（5/14 验证）："1G-M" / "100M-F" 链路速率代表 online；
        // 空串 / "offline" / 0 / false 表示离线。容错多种历史格式。
        const onRaw = d.online != null ? d.online : d.state;
        const online = onRaw === 1 || onRaw === true || onRaw === "1" || onRaw === "online" ||
                       (typeof onRaw === "string" && onRaw !== "" && onRaw !== "offline" && onRaw !== "0");
        const onWall = wallTx.has(id) ? " <span class=\"husion-dev-type\" style=\"color:var(--accent)\">[墙上]</span>" : "";
        return `<div class="husion-dev-row">` +
          `<span class="husion-dev-dot ${online ? "on" : "off"}" title="${online ? "online" : "offline"}"></span>` +
          `<span class="husion-dev-name" title="${escHtml(name)}">${escHtml(name)}</span>` +
          `<span class="husion-dev-ip">${escHtml(ip)}</span>` +
          `<span class="husion-dev-type">${escHtml(type)}</span>${onWall}` +
          `</div>`;
      }).join("");
      devEl.innerHTML = html;

      const onlineCount = devices.filter(d => {
        const o = d.online != null ? d.online : d.state;
        return o === 1 || o === "1" || o === true || o === "online";
      }).length;
      setBadge(`${onlineCount}/${devices.length}`, onlineCount === devices.length ? "var(--ok,#4caf50)" : "var(--accent-2)");
    }

    // 场景按钮点击 → POST /api/husion/scene
    sceneEl.querySelectorAll(".husion-scene-btn").forEach(btn => {
      btn.onclick = async () => {
        const scene = btn.dataset.scene;
        const rxId  = btn.dataset.rx || "5008";
        if (!scene) return;
        const orig = btn.textContent;
        btn.disabled = true;
        btn.textContent = "切换中…";
        try {
          const r = await fetch("/api/husion/scene", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ rx_id: rxId, scene_name: scene }),
          });
          const data = await r.json().catch(() => ({}));
          if (r.ok && data.ok) {
            btn.textContent = "✓ " + orig;
            setBadge(`切到 ${scene}`, "var(--ok,#4caf50)");
            // 切完后立刻刷一次状态（墙窗口变了）
            setTimeout(refresh, 600);
          } else {
            btn.textContent = "✗ " + orig;
            setBadge(`失败: ${(data.error || data.husion_resp?.message || "")}`.slice(0, 30), "var(--warn,#f57c00)");
            console.warn("[husion] 切场景失败", data);
          }
        } catch (e) {
          btn.textContent = "✗ " + orig;
          setBadge("网络错误", "var(--warn,#f57c00)");
          console.warn("[husion] fetch 异常", e);
        } finally {
          setTimeout(() => { btn.disabled = false; btn.textContent = orig; }, 1500);
        }
      };
    });

    refresh();
    setInterval(refresh, 10000);
  }

  // ── P0 快捷控制（creator 中控 ASCII 转发） ────────────────────────
  // G3b: 视觉深思 dropdown onchange → 下发 watch_camera 给 scene_analyzer（mqtt config topic）
  function setupSceneWatchPicker() {
    const sel = document.getElementById("scene-watch-picker");
    if (!sel) return;
    sel.onchange = () => {
      fetch("/mqtt/publish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic: "av/video/scene_analyzer/config",
          payload: { watch_camera: sel.value || null },
        }),
      }).catch(e => console.warn("scene watch_camera publish 失败", e));
    };
  }

  async function setupQuickControl() {
    const locSel    = document.getElementById("quick-ctrl-location");
    const buttonsEl = document.getElementById("quick-ctrl-buttons");
    const badge     = document.getElementById("quick-ctrl-badge");
    if (!locSel || !buttonsEl) return;

    let catalog = null;
    try {
      const r = await fetch("/config/device_catalog");
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      catalog = await r.json();
    } catch (e) {
      buttonsEl.innerHTML = `<div style="color:var(--warn);padding:10px">设备目录加载失败：${escHtml(e.message)}</div>`;
      return;
    }

    // 地点 dropdown（按 category 分组排序：default/main/meeting/common/service/feature）
    const order = ["default", "main", "meeting", "common", "service", "feature"];
    const sortedLocs = [...catalog.locations].sort((a, b) =>
      (order.indexOf(a.category) - order.indexOf(b.category)) ||
      a.label.localeCompare(b.label, "zh-CN")
    );
    locSel.innerHTML = "";
    sortedLocs.forEach(loc => {
      const opt = document.createElement("option");
      opt.value = loc.id;
      opt.textContent = loc.label;
      if (loc.id === catalog.default_location) opt.selected = true;
      locSel.appendChild(opt);
    });

    function btnExtraClass(devKey, action) {
      // 视觉提示：温度+ / Off / Close 用警示色；温度- / On 用冷色；其它默认
      if (action === "Off" || action === "Close" || action === "TempUp") return "ctrl-btn-warn";
      if (action === "On" || action === "Open" || action === "TempDown") return "ctrl-btn-cool";
      return "";
    }

    function renderForLocation(locId) {
      const loc = catalog.locations.find(l => l.id === locId);
      // 复式跃层等场景：command 可声明 also_in: ["2FDiningTable", ...] 让多个逻辑空间共享
      const cmds = catalog.commands.filter(c =>
        c.location === locId ||
        (Array.isArray(c.also_in) && c.also_in.includes(locId))
      );
      if (!cmds.length) {
        buttonsEl.innerHTML = `<div style="color:var(--dim);padding:10px;text-align:center">${escHtml(loc?.label || locId)} 没有可用指令</div>`;
        return;
      }
      // 按 device 分组（保 CSV 出现顺序）
      const groups = {};
      const order = [];
      cmds.forEach(c => {
        if (!(c.device in groups)) { groups[c.device] = []; order.push(c.device); }
        groups[c.device].push(c);
      });
      let html = "";
      order.forEach(dev => {
        const meta = (catalog.device_types || {})[dev] || { label: dev, icon: "" };
        html += `<div class="ctrl-group">`;
        html += `<div class="ctrl-group-label">${meta.icon || ""} ${escHtml(meta.label || dev)}</div>`;
        html += `<div class="ctrl-group-buttons">`;
        groups[dev].forEach(c => {
          const actLbl = (meta.actions_label && meta.actions_label[c.action]) || c.action;
          const cls = btnExtraClass(dev, c.action);
          html += `<button class="ctrl-btn ${cls}" data-cmd="${escHtml(c.id)}" title="${escHtml(c.label)} → ${escHtml(c.id)}">${escHtml(actLbl)}</button>`;
        });
        html += `</div></div>`;
      });
      buttonsEl.innerHTML = html;
      buttonsEl.querySelectorAll(".ctrl-btn").forEach(b => {
        b.onclick = () => sendControlCommand(b.dataset.cmd, b);
      });
    }

    async function sendControlCommand(cmd, btn) {
      badge.textContent = "发送…"; badge.className = "module-badge warn";
      try {
        const r = await fetch("/mqtt/publish", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ topic: "av/control", payload: { cmd } }),
        });
        const j = await r.json();
        if (j.ok) {
          badge.textContent = `✓ ${cmd}`; badge.className = "module-badge ok";
        } else {
          badge.textContent = `✗ ${j.error || "失败"}`; badge.className = "module-badge error";
        }
      } catch (e) {
        badge.textContent = `✗ ${e.message}`; badge.className = "module-badge error";
      }
      setTimeout(() => { badge.textContent = "就绪"; badge.className = "module-badge"; }, 2500);
    }

    locSel.onchange = () => renderForLocation(locSel.value);
    renderForLocation(locSel.value || catalog.default_location);
  }

  initOverviewGrid();
  injectHideButtons();
  setupLayoutPopup();
  applyVisibility();
  applyProfileVisibility();  // CR-DIG7201 第7条：按 app_profile 隐藏无关卡（meeting_asr 只留纪要）
  setupCustomerViewToggle();
  setupAddSourceForm();
  setupLanScan();
  setupQuickControl();
  setupHusionPanel();
  setupMicRename();  // 话筒就地改名（点转写里的话筒标签）
  setupSceneWatchPicker();
  setupSystemExit();
  setupIntentToggle();
  setupTranscriptActions();
  (() => {
    const b = document.querySelector("[data-wall-mode]");
    if (b) b.onclick = () => setWallMode(wallMode === "single" ? "quad" : "single");
    // 声源下拉：选谁就 enable 谁、disable 另一个（两路同转写会把文本混在一起）
    const sel = document.querySelector("[data-tx-source]");
    if (sel) sel.onchange = async () => {
      const want = sel.value, other = want === "mic" ? "net_multicast" : "mic";
      sel.disabled = true;
      try {
        if (_srcRunning[other]) await publishSourceCmd(other, "disable");
        if (!_srcRunning[want]) await publishSourceCmd(want, "enable");
      } finally { sel.disabled = false; }
    };
    // 左侧导航 ☰：meeting_asr 默认收起、full 默认展开；用户切换记 localStorage
    const nt = document.getElementById("nav-toggle");
    const prof = document.body.dataset.appProfile || "full";
    let navHidden;
    try { navHidden = localStorage.getItem("nav_hidden"); } catch (_) { navHidden = null; }
    const hidden = navHidden === null ? prof === "meeting_asr" : navHidden === "1";
    document.body.classList.toggle("nav-hidden", hidden);
    if (nt) {
      nt.classList.toggle("on", !hidden);
      nt.onclick = () => {
        const h = !document.body.classList.contains("nav-hidden");
        document.body.classList.toggle("nav-hidden", h);
        nt.classList.toggle("on", !h);
        try { localStorage.setItem("nav_hidden", h ? "1" : "0"); } catch (_) {}
      };
    }
  })();

  // ── 转写卡按钮（A3 导出原文 + A4 停止/启动） ────────────────────────
  function setupTranscriptActions() {
    const stopBtn   = document.querySelector("[data-tx-stop]");
    const exportBtn = document.querySelector("[data-tx-export-text]");
    const audioBtn  = document.querySelector("[data-tx-export-audio]");
    if (stopBtn) {
      stopBtn.onclick = async () => {
        // 当前态显示"停止" → 发 disable；显示"启动" → 发 enable
        const willDisable = stopBtn.textContent.includes("停止");
        if (!willDisable && wallMode === "quad") {
          if (!confirm("启动转写会把视频墙切回单路（只保留会议室摄像头，其余路停用释放 CPU）。\n继续？")) return;
          wallMode = "single";
          applyWallMode();
        }
        stopBtn.disabled = true;
        try { await publishSourceCmd(activeSource(), willDisable ? "disable" : "enable"); }
        finally { stopBtn.disabled = false; }
      };
    }
    if (exportBtn) {
      exportBtn.onclick = () => {
        const card = document.querySelector('[data-overview="transcript"] .strip-card-body');
        if (!card) return;
        const paras = card.querySelectorAll(".tx-para");
        if (paras.length === 0) {
          alert("当前没有转写内容");
          return;
        }
        const lines = [];
        paras.forEach(p => {
          const ts = p.querySelector(".tx-ts")?.textContent || "";
          // 只导出已定稿（.finals），未定稿的 .live 不算
          const txt = p.querySelector(".finals")?.textContent || "";
          // 发言人取标签实时文本（改名后全局刷新过），不用 dataset.speaker
          // 旧名快照——否则导出文件里是改名前的名字（2026-08-20 用户实测）
          const spk = p.querySelector(".tx-spk")?.textContent || p.dataset.speaker || "";
          if (txt) lines.push(`[${ts}]${spk ? ` [${spk}]` : ""}\n${txt}\n`);
        });
        const d0 = new Date();
        const p0 = n => String(n).padStart(2, "0");
        const txStamp = `${d0.getFullYear()}${p0(d0.getMonth() + 1)}${p0(d0.getDate())}-${p0(d0.getHours())}${p0(d0.getMinutes())}`;
        serverDownload(`transcript-${txStamp}.txt`, lines.join("\n"));
      };
    }
    if (audioBtn) {
      // 导出原音：直连 audio_processor 嵌入式 HTTP :5052 拉 WAV（仿 video_processor 5051 风格，
      // 跨进程通信由 audio_processor 自带 server 处理，不走 main.py web/server 中转）
      audioBtn.onclick = () => {
        const url = `${location.protocol}//${location.hostname}:5052/audio/export.wav`;
        // 先探测 5052 是否有服务：纪要机形态（audio.source=net_multicast）下
        // audio_processor 不起、组播路径的原音导出未实现，直接跳转会落到浏览器
        // 拒绝页（2026-08-20 用户实测）。探活通过才触发下载。
        fetch(url, { method: "HEAD", mode: "no-cors" }).then(() => {
          const a = document.createElement("a");
          a.href = url;
          a.download = "";  // 让浏览器用服务端 filename
          document.body.appendChild(a); a.click();
          setTimeout(() => document.body.removeChild(a), 100);
        }).catch(() => {
          alert("当前形态暂不支持导出原音：\n会议主机组播路径（纪要机）的整场录音导出尚未实现，已立项待排期。\n转写文字请用「导出原文」。");
        });
      };
    }
    const sumBtn = document.querySelector("[data-tx-summary]");
    if (sumBtn) sumBtn.onclick = () => generateSummary(sumBtn);
  }

  // ── 纪要生成（C 档双路：弹窗即时翻阅 + summaries/ JSON 留档） ───────
  function gatherTranscriptText() {
    const card = document.querySelector('[data-overview="transcript"] .strip-card-body');
    if (!card) return { text: "", durationSec: 0 };
    const parts = [];
    card.querySelectorAll(".tx-para").forEach(p => {
      const t = p.querySelector(".finals")?.textContent || "";
      if (!t.trim()) return;
      // P3：多路话筒段带发言人前缀，纪要 LLM 据此区分谁说了什么。
      // 取标签实时文本（当前名），不用 dataset.speaker 旧名快照——纪要里
      // 的发言人归属才与改名后界面一致
      const spk = p.querySelector(".tx-spk")?.textContent || p.dataset.speaker || "";
      parts.push(spk ? `[${spk}] ${t}` : t);
    });
    // 用第一段时间戳估算时长（仅用于元数据，不影响 LLM 调用）
    const firstTsEl = card.querySelector(".tx-para .tx-ts");
    let durationSec = 0;
    if (firstTsEl) {
      const m = firstTsEl.textContent.match(/(\d+):(\d+):(\d+)/);
      if (m) {
        const start = (+m[1]) * 3600 + (+m[2]) * 60 + (+m[3]);
        const now = new Date();
        const end = now.getHours() * 3600 + now.getMinutes() * 60 + now.getSeconds();
        durationSec = Math.max(0, end - start);
      }
    }
    return { text: parts.join("\n"), durationSec };
  }

  async function generateSummary(btn) {
    const { text, durationSec } = gatherTranscriptText();
    if (text.length < 30) {
      alert("当前转写内容太少，至少需要 30 字才能生成纪要");
      return;
    }
    const modal = openSummaryModal({ loading: true, charCount: text.length });
    btn.disabled = true;
    try {
      const r = await fetch("/audio/summary", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ transcript: text, duration_sec: durationSec })
      });
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) {
        renderSummaryError(modal, data.error || `HTTP ${r.status}`);
        return;
      }
      renderSummary(modal, data);
    } catch (e) {
      renderSummaryError(modal, String(e));
    } finally {
      btn.disabled = false;
    }
  }

  let summaryTimerId = null;

  function openSummaryModal({ loading, charCount }) {
    closeSummaryModal();  // 防止重叠
    const modal = document.createElement("div");
    modal.className = "summary-modal";
    // 长转写走后端分段（>8000 字）。3588 CPU 实测吞吐 ≈ 600 字/分钟（prefill 8 tok/s），
    // 按此给"最长约 X 分钟"上限；Mac 等强机会远快于估计，措辞留余地
    const isLong = (charCount || 0) > 8000;
    const estMin = Math.max(1, Math.ceil((charCount || 0) / 600));
    const hint = isLong
      ? `长会议 ${charCount} 字分段生成中，本机 CPU 推理最长约 ${estMin} 分钟`
      : `qwen3.5:4b · 视设备算力数秒到数分钟`;
    modal.innerHTML = `<div class="summary-card${loading ? " loading" : ""}">
      ${loading ? `✦ 正在生成纪要…<br><span style='font-size:11px'>（${hint} · 已用时 <span data-sm-elapsed>0</span>s）</span>` : ""}
    </div>`;
    modal.onclick = (e) => { if (e.target === modal) closeSummaryModal(); };
    document.body.appendChild(modal);
    if (loading) {
      const t0 = Date.now();
      summaryTimerId = setInterval(() => {
        const el = modal.querySelector("[data-sm-elapsed]");
        if (!el) { clearInterval(summaryTimerId); summaryTimerId = null; return; }
        el.textContent = Math.round((Date.now() - t0) / 1000);
      }, 1000);
    }
    return modal;
  }

  function closeSummaryModal() {
    if (summaryTimerId) { clearInterval(summaryTimerId); summaryTimerId = null; }
    document.querySelectorAll(".summary-modal").forEach(m => m.remove());
  }

  function escHtmlSafe(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }

  function renderSummary(modal, data) {
    const card = modal.querySelector(".summary-card");
    card.classList.remove("loading");
    const ptsHtml = (data.points || []).map(p => `<li>${escHtmlSafe(p)}</li>`).join("");
    const kwsHtml = (data.keywords || []).map(k => `<span class="kw">${escHtmlSafe(k)}</span>`).join("");
    const dur = data.duration_sec ? `${Math.round(data.duration_sec / 60)} 分钟 · ` : "";
    const gen = data.elapsed_sec
      ? `生成 ${Math.round(data.elapsed_sec)}s${data.chunks > 1 ? `（${data.chunks} 段）` : ""} · `
      : "";
    const fileMeta = data.file ? `已留档 summaries/${escHtmlSafe(data.file)}` : "";
    card.innerHTML = `
      <h2>${escHtmlSafe(data.title)}</h2>
      <div class="summary-meta">${dur}${gen}${data.id} · ${fileMeta}</div>
      <p class="sm-summary">${escHtmlSafe(data.summary)}</p>
      <h3>关键点</h3>
      <ul class="sm-points">${ptsHtml}</ul>
      <h3>关键词</h3>
      <div class="sm-keywords">${kwsHtml}</div>
      <div class="summary-actions">
        <button data-sm-copy>📋 复制 Markdown</button>
        <button data-sm-md>💾 下载 .md</button>
        <button data-sm-close class="close">关闭</button>
      </div>
    `;
    const md = summaryToMarkdown(data);
    card.querySelector("[data-sm-copy]").onclick = async () => {
      const ok = await copyText(md);
      if (ok) flashBtn(card.querySelector("[data-sm-copy]"), "✓ 已复制");
      else alert("复制失败 — 请改用「下载 .md」");
    };
    card.querySelector("[data-sm-md]").onclick = () => {
      // 文件名 = 时间 + 纪要标题（清洗非法字符），方便后期利用；
      // 走服务器附件下载（blob 在 HTTP 站点被 Chrome 挂起 .crdownload）
      const d = new Date();
      const pad = n => String(n).padStart(2, "0");
      const stamp = `${d.getFullYear()}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`;
      const title = String(data.title || "未命名").replace(/[\\/:*?"<>|\n\r]/g, "_").slice(0, 40);
      serverDownload(`纪要-${stamp}-${title}.md`, md);
    };
    card.querySelector("[data-sm-close]").onclick = closeSummaryModal;
  }

  function renderSummaryError(modal, msg) {
    const card = modal.querySelector(".summary-card");
    card.classList.remove("loading");
    card.innerHTML = `
      <h2>纪要生成失败</h2>
      <div class="summary-error">${escHtmlSafe(msg)}</div>
      <div class="summary-actions">
        <button data-sm-close class="close">关闭</button>
      </div>`;
    card.querySelector("[data-sm-close]").onclick = closeSummaryModal;
  }

  function flashBtn(btn, msg) {
    const old = btn.textContent;
    btn.textContent = msg;
    setTimeout(() => { btn.textContent = old; }, 1200);
  }

  function summaryToMarkdown(d) {
    const points = (d.points || []).map(p => `- ${p}`).join("\n");
    const keywords = (d.keywords || []).join(" · ");
    return `# ${d.title}\n\n` +
           `**${d.id}** · ${d.duration_sec ? Math.round(d.duration_sec/60) + ' 分钟' : ''}\n\n` +
           `## 摘要\n${d.summary}\n\n` +
           `## 关键点\n${points}\n\n` +
           `## 关键词\n${keywords}\n\n` +
           `---\n\n## 转写全文\n${d.transcript || ''}\n`;
  }

  // ── 意图判断 toggle（在意图卡 module-body 底部按钮条） ─────────────
  // 点击 → POST /mqtt/publish av/llm/cmd {action} → llm_engine 切状态 → 重发 discovery →
  // handleDiscovery 看到 enabled 字段变化 → setIntentToggleState 更新 UI。
  // UI 不在点击时立即 toggle 类（防止网络失败 / llm_engine 未连而出现状态飘移）。
  function setupIntentToggle() {
    const btn = document.querySelector("[data-intent-toggle]");
    if (!btn) return;
    btn.onclick = async () => {
      const willEnable = !btn.classList.contains("on");
      btn.disabled = true;
      try {
        const r = await fetch("/mqtt/publish", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            topic: "av/llm/cmd",
            payload: { action: willEnable ? "enable" : "disable" }
          })
        });
        if (!r.ok) console.warn("意图判断切换失败", r.status);
      } catch (e) { console.warn("意图判断切换异常", e); }
      finally { btn.disabled = false; }
    };
  }

  // ── 退出系统按钮 ─────────────────────────────────────────────────────
  // 触发 supervisor 优雅停机：杀子进程 → 停 mosquitto / Node-RED / FunASR docker。
  // 后端先返回 200，0.1s 后才设 _running=False，所以 UI 能及时显示遮罩。
  function setupSystemExit() {
    const btn = document.getElementById("btn-system-exit");
    if (!btn) return;
    btn.onclick = async () => {
      if (!confirm("确定退出系统？\n\n将停止：\n  · main.py 及所有子模块\n  · mosquitto / Node-RED / FunASR")) return;
      btn.disabled = true;
      btn.textContent = "退出中…";
      let shutdownOk = true;
      try {
        const r = await fetch("/system/shutdown", { method: "POST" });
        // 端点不存在 / 后端未注入 handler → 不要假装成功，否则会出现"显示退出但进程仍在跑"
        if (!r.ok && r.status !== 0) {
          shutdownOk = false;
          alert(`退出失败：HTTP ${r.status}\n可能是 main.py 未重启加载新代码。\n请到终端 Ctrl+C 后双击 start.command。`);
          btn.disabled = false;
          btn.textContent = "⏻ 退出系统";
          return;
        }
      } catch (_) { /* 后端关停时连接断开属正常，shutdownOk 保持 true */ }
      // 全屏遮罩：避免用户继续操作
      const mask = document.createElement("div");
      mask.style.cssText =
        "position:fixed;inset:0;background:rgba(10,14,20,0.92);z-index:99999;" +
        "display:flex;align-items:center;justify-content:center;flex-direction:column;" +
        "color:var(--text);font-size:16px;gap:14px;";
      mask.innerHTML =
        "<div style='font-size:36px'>⏻</div>" +
        "<div>系统正在退出…</div>" +
        "<div style='font-size:12px;color:var(--dim)'>关闭浏览器即可。如需重启 → 双击 start.command</div>";
      document.body.appendChild(mask);
    };
  }
})();
