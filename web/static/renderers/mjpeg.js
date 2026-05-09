// renderer: mjpeg  (R4)
// 不消费 SSE 事件流；从 discovery 公告 endpoints[] 读取每路摄像头 URL 渲染 <img>。
// dashboard.js 在 createPanel 时调用 renderer.setEndpoints(endpoints)。
window.Renderers = window.Renderers || {};

window.Renderers.mjpeg = function makeMjpegRenderer(feed) {
  // name → { wrap, img, label, enabled, url }
  const cards = new Map();

  function ensureCard(ep) {
    const name = ep.name || "(unnamed)";
    let c = cards.get(name);
    if (!c) {
      const wrap = document.createElement("div");
      wrap.className = "mjpeg-card";
      wrap.style.cssText =
        "display:flex;flex-direction:column;background:var(--panel);" +
        "border:1px solid var(--line);border-radius:8px;overflow:hidden;";

      const head = document.createElement("div");
      head.style.cssText =
        "padding:4px 8px;font-size:11px;color:var(--dim);display:flex;" +
        "align-items:center;gap:8px;border-bottom:1px solid var(--line);" +
        "font-family:ui-monospace,monospace;";

      const label = document.createElement("span");
      label.style.flex = "1";
      label.textContent = name;

      const btn = document.createElement("button");
      btn.style.cssText =
        "font-size:12px;padding:4px 14px;border-radius:4px;cursor:pointer;" +
        "background:var(--accent);color:#0d1117;border:0;font-weight:600;";
      btn.onclick = () => {
        const action = c.enabled ? "disable" : "enable";
        fetch(`/camera/${encodeURIComponent(name)}/${action}`, { method: "POST" })
          .catch(err => console.warn("camera toggle failed", err));
      };

      // 本机摄像头：卡边框红 + 头部背景红，远距离一眼看到该停
      const isLocal = /^\d+$/.test(String(ep.src_url || ""));
      if (isLocal) {
        wrap.style.border = "1px solid var(--warn)";
        head.style.background = "rgba(248,81,73,0.10)";
      }

      head.appendChild(label);
      head.appendChild(btn);

      const img = document.createElement("img");
      img.alt = name;
      img.style.cssText = "width:100%;display:block;background:#000;min-height:160px;";

      const errBox = document.createElement("div");
      errBox.style.cssText =
        "display:none;padding:12px;font-size:11px;color:var(--warn);" +
        "background:#1a0e10;text-align:center;line-height:1.6;";
      errBox.innerHTML =
        "⚠ 摄像头无法读取帧<br>" +
        "<span style='color:var(--dim)'>" +
        "本机摄像头：检查 macOS 系统设置 → 隐私 → 相机 给 Terminal 授权<br>" +
        "RTSP：网络/账号/路径不通" +
        "</span>";

      // multipart 流偶尔会触发 error，要等"长时间没成功 load"才显示错误
      let loadOk = false;
      let errTimer = null;
      img.addEventListener("load", () => {
        loadOk = true;
        errBox.style.display = "none";
        if (errTimer) { clearTimeout(errTimer); errTimer = null; }
      });
      img.addEventListener("error", () => {
        if (!c.enabled || loadOk) return;
        if (errTimer) return;
        errTimer = setTimeout(() => {
          if (!loadOk && c.enabled) errBox.style.display = "block";
          errTimer = null;
        }, 5000);
      });
      // 启用时先重置标志（applyEnabled 会调）
      img._resetLoadFlag = () => { loadOk = false; };

      wrap.appendChild(head);
      wrap.appendChild(img);
      wrap.appendChild(errBox);
      feed.appendChild(wrap);
      c = { wrap, img, label, btn, errBox, enabled: false, url: ep.url, isLocal };
      cards.set(name, c);
    }
    return c;
  }

  // 仅在 mjpeg 卡片可见（即所在 view active）时轮询
  function isCardVisible(c) {
    // 走 DOM offsetParent 判断；display:none 时 offsetParent 为 null
    return c.img && c.img.offsetParent !== null && !document.hidden;
  }

  const TRANSPARENT = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";

  function startPoll(c) {
    if (c._stopPoll) return;
    let stopped = false;
    let firstOk = false;
    let watchdog = null;
    function clear() {
      stopped = true;
      if (watchdog) { clearTimeout(watchdog); watchdog = null; }
      c.img.onload = null; c.img.onerror = null;
      c.img.src = TRANSPARENT;
    }
    function tick() {
      if (stopped) return;
      if (!isCardVisible(c)) { clear(); c._stopPoll = null; return; }
      const url = c.url + (c.url.includes("?") ? "&" : "?") + "t=" + Date.now();
      watchdog = setTimeout(() => {
        if (stopped) return;
        c.img.src = TRANSPARENT;
        setTimeout(tick, 500);
      }, 3000);
      c.img.onload = () => {
        if (watchdog) { clearTimeout(watchdog); watchdog = null; }
        if (!firstOk) {
          firstOk = true;
          if (c.errBox) c.errBox.style.display = "none";
        }
        setTimeout(tick, 200);  // 视频检测页 5 fps（YOLO 上限本来就 2fps）
      };
      c.img.onerror = () => {
        if (watchdog) { clearTimeout(watchdog); watchdog = null; }
        if (stopped) return;
        if (!firstOk && c.errBox) c.errBox.style.display = "block";
        setTimeout(tick, 1000);
      };
      c.img.src = url;
    }
    c._stopPoll = clear;
    tick();
  }

  // 监听 dashboard 视图切换 → 视图变可见时把所有 enabled 卡的 poll 重启
  document.addEventListener("dashboard:view-change", () => {
    setTimeout(() => {
      cards.forEach(c => {
        if (c.enabled && !c._stopPoll && isCardVisible(c)) startPoll(c);
      });
    }, 30);
  });
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
      cards.forEach(c => {
        if (c.enabled && !c._stopPoll && isCardVisible(c)) startPoll(c);
      });
    }
  });
  function stopPoll(c) {
    if (c._stopPoll) { c._stopPoll(); c._stopPoll = null; }
  }

  function applyEnabled(c, enabled) {
    if (enabled === c.enabled) return;
    c.enabled = enabled;
    if (enabled) {
      c.img.style.opacity = "1";
      const tag = c.isLocal ? "（本机·占 camera）" : "";
      c.label.textContent = c.img.alt + " · 在线" + tag;
      c.btn.textContent = c.isLocal ? "⏹ 停用本机" : "停用";
      c.btn.title = c.isLocal ? "停用本机摄像头（释放 macOS camera 占用）" : "";
      c.btn.style.background = "var(--warn)";
      c.btn.style.color = "#fff";
      startPoll(c);
    } else {
      stopPoll(c);
      c.img.src = "data:image/gif;base64,R0lGODlhAQABAAAAACH5BAEKAAEALAAAAAABAAEAAAICTAEAOw==";
      c.img.style.opacity = "0.4";
      c.label.textContent = c.img.alt + " · 已停用";
      c.btn.textContent = "启用";
      c.btn.style.background = "var(--accent)";
      c.btn.style.color = "#0d1117";
      if (c.errBox) c.errBox.style.display = "none";
    }
  }

  // 把后端给的 url（写死 127.0.0.1）改成当前页面 hostname，方便 LAN 访问
  function rewriteHost(url) {
    try {
      const u = new URL(url);
      u.hostname = window.location.hostname;
      return u.toString();
    } catch (_) { return url; }
  }

  // 暴露给 dashboard.js 调用
  function setEndpoints(endpoints) {
    const seen = new Set();
    for (const ep of endpoints || []) {
      if (ep.kind !== "mjpeg" || !ep.name) continue;
      seen.add(ep.name);
      // 视频检测模块（工程师调试视图）默认走 annotated_url（带 YOLO bbox）
      const useUrl = ep.annotated_url || ep.url;
      const c = ensureCard({ ...ep, url: rewriteHost(useUrl) });
      c.url = rewriteHost(useUrl);
      applyEnabled(c, !!ep.enabled);
    }
    // 移除已不存在的卡
    cards.forEach((c, name) => {
      if (!seen.has(name)) {
        c.wrap.remove();
        cards.delete(name);
      }
    });
  }

  // 普通的 SSE event 渲染：mjpeg 不订阅事件流，但保留接口避免崩
  const renderFn = function (_ev) { /* no-op */ };
  renderFn.setEndpoints = setEndpoints;
  return renderFn;
};
