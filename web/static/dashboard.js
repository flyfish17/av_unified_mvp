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
  };
  const MODULE_GROUP = {
    // node_red 单独一组
    audio_processor: "ai", video_processor: "ai",
    llm_engine: "ai", supervisor: "ai",
    system_info: "sys", network_info: "sys",
    network_scanner: "tools",
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
        // 重新开始（如果之前停了）
        const ep = videoEndpointsCache.find(e => e.name === slot.sourceName);
        if (ep && ep.enabled) {
          const tileEl = document.getElementById("video-wall")?.querySelector(`[data-slot="${slot.idx}"]`);
          const img = tileEl?.querySelector(".tile-img");
          if (img && !slot._stopPoll) {
            startSnapshotPoll(slot, img, rewriteHost(ep.stream_url || ep.url));
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
    handlers.forEach(({ handler, module }) => {
      try { handler(cleanEv); } catch (err) { console.warn(err); }
      if (module) { try { tickerForward(module, ch, cleanEv); } catch (_) {} }
    });
  };

  // discovery 走聚合 SSE
  subscribeChannel("discovery", (ev) => {
    try { handleDiscovery(ev); } catch (err) { console.warn(err); }
  });

  function setHeaderStatus(text, cls) {
    const el = document.getElementById("header-status");
    if (el) { el.textContent = text; el.className = "pill " + cls; }
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
    if (name === "audio_processor" && typeof ev.running === "boolean") {
      setTxStopButtonState(ev.running);
    }
  }
  function setTxStopButtonState(running) {
    const btn = document.querySelector("[data-tx-stop]");
    if (!btn) return;
    btn.textContent = running ? "⏸ 停止" : "▶ 启动";
    btn.classList.toggle("stop", running);  // 红色仅在"停止"态（点击会停）
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
      videoEndpointsCache = (endpoints || []).filter(e => e.kind === "mjpeg");
      assignWallSlots();
      renderWall();
    }
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
  function assignWallSlots() {
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
    try { const u = new URL(url); u.hostname = window.location.hostname; return u.toString(); }
    catch (_) { return url; }
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
      // 实际画格
      tileEl.className = "tile" + (slot.zoomed ? " zoomed" : "");
      tileEl.innerHTML =
        `<img class="tile-img" alt="${escHtml(ep.name)}">` +
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
      const img = tileEl.querySelector(".tile-img");
      // 先停掉旧的轮询定时器
      if (slot._stopPoll) { slot._stopPoll(); slot._stopPoll = null; }
      if (ep.enabled) {
        // 用 stream_url（multipart MJPEG 长连），不再 snapshot 轮询；fallback 到 snapshot
        startSnapshotPoll(slot, img, rewriteHost(ep.stream_url || ep.url));
      } else {
        img.src = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
        img.style.opacity = "0.3";
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

  // 转写卡渲染：仿讯飞「讲解稿」观感 — 连续讲话合并到同一段落，停顿 >60s 才换段。
  // 段头只显示时间戳（说话人 diarization 当前没接，"说话人 1" 占位反而误导，等接
  // SOND/cam++ 后再加）。每段内部：.finals 累积所有定稿文字 + 末尾 .live 显示当前
  // partial（灰色斜体），final 时把 partial 文字并入 finals 并清空 live。
  // PARA_GAP_SEC：超过此时长没新 final 就开新段落。
  const PARA_GAP_SEC = 60;
  const _txState = { para: null, finalsText: "", lastFinalMs: 0 };
  function fmtClock(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }
  function pushOverviewTranscript(ev) {
    const card = document.querySelector('[data-overview="transcript"] .strip-card-body');
    if (!card) return;
    clearEmpty(card);
    pulseEl(card.closest(".strip-card"));

    const nowMs = Date.now();
    const stale = !_txState.para || !card.contains(_txState.para);
    const gapped = _txState.lastFinalMs > 0 &&
                   (nowMs - _txState.lastFinalMs) / 1000 > PARA_GAP_SEC;

    if (stale || gapped) {
      const para = document.createElement("div");
      para.className = "tx-para";
      para.innerHTML =
        `<div class="tx-meta"><span class="tx-ts">${fmtClock(ev.ts)}</span></div>` +
        `<div class="tx-text"><span class="finals"></span><span class="live"></span></div>`;
      card.appendChild(para);
      while (card.querySelectorAll(".tx-para").length > 50) card.firstChild.remove();
      _txState.para = para;
      _txState.finalsText = "";
      _txState.lastFinalMs = 0;
    }

    const finalsEl = _txState.para.querySelector(".finals");
    const liveEl   = _txState.para.querySelector(".live");
    if (ev.is_final) {
      _txState.finalsText += (ev.text || "");
      finalsEl.textContent = _txState.finalsText;
      liveEl.textContent = "";
      _txState.lastFinalMs = nowMs;
    } else {
      liveEl.textContent = ev.text || "";
    }
    card.scrollTop = card.scrollHeight;
  }
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
      // 1. 提取页面
      const rawPages = flows.filter(n => n.type === "ui-page" || n.type === "ui_tab");
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
      // 如果 5 秒内 selector 还没设 src，默认加载 /dashboard/ root（dashboard 2.0 入口）
      setTimeout(() => {
        if (frame.src === "about:blank" || !frame.src) {
          frame.src = `http://${window.location.hostname}:1880/dashboard/`;
        }
      }, 5000);
    } catch (_) {
      fallback.style.display = "flex";
      frame.style.display = "none";
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
      const wrap = getGridItem(m.id);
      const visible = wrap && wrap.style.display !== "none";
      const lbl = document.createElement("label");
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
      MODULES_META.forEach(m => showModule(m.id));
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
        nameIn.disabled = true;  // 不允许改 name（会破坏后端 endpoints 索引）
        nameIn.title = "edit 模式下不可改名（删除后重新添加）";
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
      try {
        const r = await fetch("/mqtt/publish", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ topic, payload: { name: editingName || name, url, enabled: true } }),
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

  // ── P0 快捷控制（creator 中控 ASCII 转发） ────────────────────────
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
  setupAddSourceForm();
  setupLanScan();
  setupQuickControl();
  setupSystemExit();
  setupIntentToggle();
  setupTranscriptActions();

  // ── 转写卡按钮（A3 导出原文 + A4 停止/启动） ────────────────────────
  function setupTranscriptActions() {
    const stopBtn   = document.querySelector("[data-tx-stop]");
    const exportBtn = document.querySelector("[data-tx-export-text]");
    const audioBtn  = document.querySelector("[data-tx-export-audio]");
    if (stopBtn) {
      stopBtn.onclick = async () => {
        // 当前态显示"停止" → 发 disable；显示"启动" → 发 enable
        const willDisable = stopBtn.textContent.includes("停止");
        stopBtn.disabled = true;
        try {
          await fetch("/mqtt/publish", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              topic: "av/audio/cmd",
              payload: { action: willDisable ? "disable" : "enable" }
            })
          });
        } catch (e) { console.warn("audio toggle 失败", e); }
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
          if (txt) lines.push(`[${ts}]\n${txt}\n`);
        });
        const blob = new Blob([lines.join("\n")], { type: "text/plain;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
        a.href = url; a.download = `transcript-${stamp}.txt`;
        document.body.appendChild(a); a.click();
        setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
      };
    }
    if (audioBtn) {
      // 导出原音：直连 audio_processor 嵌入式 HTTP :5052 拉 WAV（仿 video_processor 5051 风格，
      // 跨进程通信由 audio_processor 自带 server 处理，不走 main.py web/server 中转）
      audioBtn.onclick = () => {
        const url = `${location.protocol}//${location.hostname}:5052/audio/export.wav`;
        // 直接 navigation 触发下载（Content-Disposition 强制 attachment）
        const a = document.createElement("a");
        a.href = url;
        a.download = "";  // 让浏览器用服务端 filename
        document.body.appendChild(a); a.click();
        setTimeout(() => document.body.removeChild(a), 100);
      };
    }
    const sumBtn = document.querySelector("[data-tx-summary]");
    if (sumBtn) sumBtn.onclick = () => generateSummary(sumBtn);
  }

  // ── 纪要生成（C 档双路：弹窗即时翻阅 + summaries/ JSON 留档） ───────
  function gatherTranscriptText() {
    const card = document.querySelector('[data-overview="transcript"] .strip-card-body');
    if (!card) return { text: "", durationSec: 0 };
    const finals = card.querySelectorAll(".tx-para .finals");
    const parts = [];
    finals.forEach(el => {
      const t = el.textContent || "";
      if (t.trim()) parts.push(t);
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
    const modal = openSummaryModal({ loading: true });
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

  function openSummaryModal({ loading }) {
    closeSummaryModal();  // 防止重叠
    const modal = document.createElement("div");
    modal.className = "summary-modal";
    modal.innerHTML = `<div class="summary-card${loading ? " loading" : ""}">
      ${loading ? "✦ 正在生成纪要…<br><span style='font-size:11px'>（qwen3.5:4b · 约 5-15 秒）</span>" : ""}
    </div>`;
    modal.onclick = (e) => { if (e.target === modal) closeSummaryModal(); };
    document.body.appendChild(modal);
    return modal;
  }

  function closeSummaryModal() {
    document.querySelectorAll(".summary-modal").forEach(m => m.remove());
  }

  function escHtmlSafe(s) { return String(s == null ? "" : s).replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;"}[c])); }

  function renderSummary(modal, data) {
    const card = modal.querySelector(".summary-card");
    card.classList.remove("loading");
    const ptsHtml = (data.points || []).map(p => `<li>${escHtmlSafe(p)}</li>`).join("");
    const kwsHtml = (data.keywords || []).map(k => `<span class="kw">${escHtmlSafe(k)}</span>`).join("");
    const dur = data.duration_sec ? `${Math.round(data.duration_sec / 60)} 分钟 · ` : "";
    const fileMeta = data.file ? `已留档 summaries/${escHtmlSafe(data.file)}` : "";
    card.innerHTML = `
      <h2>${escHtmlSafe(data.title)}</h2>
      <div class="summary-meta">${dur}${data.id} · ${fileMeta}</div>
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
      try { await navigator.clipboard.writeText(md); flashBtn(card.querySelector("[data-sm-copy]"), "✓ 已复制"); }
      catch { alert("复制失败 — 浏览器可能未授权剪贴板权限"); }
    };
    card.querySelector("[data-sm-md]").onclick = () => {
      const blob = new Blob([md], { type: "text/markdown;charset=utf-8" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url; a.download = `summary-${data.id}.md`;
      document.body.appendChild(a); a.click();
      setTimeout(() => { document.body.removeChild(a); URL.revokeObjectURL(url); }, 100);
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
