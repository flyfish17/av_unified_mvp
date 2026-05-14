// renderer: kv_table
// 通用键值对 / JSON 事件流。
// - 离散事件（控制 / 意图 / 视频检测 / 扫描结果）：每条 append 一行
// - 状态事件（主机指标 / 网络 / 扫描进度）：固定一行原地更新
window.Renderers = window.Renderers || {};

window.Renderers.kv_table = function makeKvTableRenderer(feed) {
  const MAX_ROWS = 50;
  // stateful 行：key → DOM row。源自 ev.header.source 或事件特征
  const stickyRows = new Map();

  function fmtTime(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  function trim() {
    // 只 trim 非 sticky 行
    const rows = [...feed.children].filter(c => !c.dataset.sticky);
    while (rows.length > MAX_ROWS) {
      const r = rows.shift();
      r.remove();
    }
  }

  function escHtml(s) {
    return String(s).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
  }

  // ── 事件分类 ────────────────────────────────────────────────────
  function classify(ev) {
    const src = (ev.header || {}).source;
    if (src === "system_info" || ev.cpu_percent !== undefined) return { kind: "host_stats", sticky: "host_stats" };
    if (src === "network_info" || ev.interfaces) return { kind: "network", sticky: "network" };
    if (ev.type === "progress" && ev.scan_id) return { kind: "scan_progress", sticky: "scan_progress" };
    if (ev.type === "result" && ev.alive_hosts) return { kind: "scan_result", sticky: null };
    if (ev.target || ev.action) return { kind: "control", sticky: null };
    if (ev.scene) return { kind: "scene", sticky: null };
    const body = ev.payload || ev;
    if (body.original_text) return { kind: "intent", sticky: null };
    if (ev.detections || ev.camera) return { kind: "video", sticky: null };
    return { kind: "fallback", sticky: null };
  }

  // ── 各形状的格式化 ──────────────────────────────────────────────
  function fmtHostStats(ev) {
    const used = ev.mem_used_gb, total = ev.mem_total_gb;
    return `<div><b>CPU</b> ${ev.cpu_percent?.toFixed(1)}% · ` +
      `<b>MEM</b> ${ev.mem_percent?.toFixed(1)}% (${used}/${total} GB) · ` +
      `<b>DISK</b> ${ev.disk_percent?.toFixed(1)}% · ` +
      `<b>LOAD</b> ${ev.load1}/${ev.load5}/${ev.load15}</div>`;
  }

  function fmtNetwork(ev) {
    const lines = (ev.interfaces || []).map(i =>
      `  <b>${escHtml(i.name)}</b>  ${escHtml(i.ip)}` +
      `  ↑${i.sent_kbps} ↓${i.recv_kbps} KB/s`
    );
    return `<div>${lines.join("<br>") || "—"}</div>`;
  }

  function fmtScanProgress(ev) {
    const pct = Math.round(ev.scanned * 100 / Math.max(ev.total, 1));
    return `<div>⏳ 扫描中 ${ev.scanned}/${ev.total} (${pct}%) · ${ev.alive} 在线 · scan=<code>${ev.scan_id}</code></div>`;
  }

  function fmtScanResult(ev) {
    const hosts = (ev.alive_hosts || []).map(h =>
      `  <b>${escHtml(h.ip)}</b>  ports=[${(h.ports || []).join(", ")}]`
    );
    return `<div>✓ ${escHtml(ev.subnet)} · ${ev.scanned} 主机, ` +
      `<b>${ev.alive_hosts.length}</b> 在线 · ${ev.duration_s}s</div>` +
      (hosts.length ? `<div style="margin-top:4px;line-height:1.6">${hosts.join("<br>")}</div>` : "");
  }

  function fmtControl(ev) {
    const cmd = [ev.target, ev.action].filter(Boolean).join(" · ");
    return ev.original_text ? `「${escHtml(ev.original_text)}」→ ${escHtml(cmd)}` : escHtml(cmd);
  }

  function fmtIntent(ev) {
    const body = ev.payload || ev;
    let suffix = "";
    if (body.command) suffix = ` → ${escHtml(JSON.stringify(body.command))}`;
    else if (body.intent?.is_command === false) suffix = " (非控制意图)";
    return `「${escHtml(body.original_text)}」${suffix}`;
  }

  function fmtVideo(ev) {
    const counts = {};
    for (const d of (ev.detections || [])) counts[d.class] = (counts[d.class] || 0) + 1;
    const summary = Object.entries(counts).map(([k, v]) => `${k}×${v}`).join("  ") || "—";
    return `${escHtml(ev.camera || "?")}: ${summary}`;
  }

  function fmtScene(ev) {
    const cls = (ev.detection_classes || []).join(", ") || "—";
    const lat = ev.vlm_latency_ms ? `${ev.vlm_latency_ms}ms` : "?";
    const mem = ev.mem_avail_mb_before ? `${ev.mem_avail_mb_before}MB` : "?";
    const tag = ev.vlm_load_ms && ev.vlm_load_ms > 1000 ? "❄️冷" : "🔥暖";
    return (
      `<div><b>${escHtml(ev.camera || "?")}</b> <span class="meta">[${escHtml(cls)}]</span></div>` +
      `<div style="margin-top:2px;line-height:1.5">${escHtml(ev.scene || "")}</div>` +
      `<div class="meta" style="margin-top:2px">${tag} ${lat} · mem ${mem} · ${escHtml(ev.vlm_model || "")}</div>`
    );
  }

  function fmtFallback(ev) {
    const s = JSON.stringify(ev);
    return s.length > 120 ? escHtml(s.slice(0, 117)) + "…" : escHtml(s);
  }

  function bodyHtml(kind, ev) {
    switch (kind) {
      case "host_stats":    return fmtHostStats(ev);
      case "network":       return fmtNetwork(ev);
      case "scan_progress": return fmtScanProgress(ev);
      case "scan_result":   return fmtScanResult(ev);
      case "control":       return fmtControl(ev);
      case "intent":        return fmtIntent(ev);
      case "video":         return fmtVideo(ev);
      case "scene":         return fmtScene(ev);
      default:              return fmtFallback(ev);
    }
  }

  function rowClassFor(kind) {
    if (kind === "control" || kind === "scan_result") return "final";
    return "";
  }

  return function render(ev) {
    if (ev.type === "hello") return;
    const ts = ev.ts || (ev.header || {}).timestamp;
    const cls = classify(ev);
    const html = `${bodyHtml(cls.kind, ev)}<div class="meta">${fmtTime(ts)}</div>`;

    if (cls.sticky) {
      let row = stickyRows.get(cls.sticky);
      if (!row) {
        row = document.createElement("div");
        row.className = "row " + rowClassFor(cls.kind);
        row.dataset.sticky = cls.sticky;
        // sticky 放在最顶端（视觉上常驻状态）
        feed.insertBefore(row, feed.firstChild);
        stickyRows.set(cls.sticky, row);
      }
      row.innerHTML = html;
    } else {
      const row = document.createElement("div");
      row.className = "row " + rowClassFor(cls.kind);
      row.innerHTML = html;
      feed.appendChild(row);
      trim();
      feed.scrollTop = feed.scrollHeight;
    }
  };
};

// fallback: 未知 kind 用 JSON dump
window.Renderers.fallback = function makeFallbackRenderer(feed) {
  const MAX_ROWS = 50;
  return function render(ev) {
    if (ev.type === "hello") return;
    const row = document.createElement("div");
    row.className = "row";
    row.textContent = JSON.stringify(ev, null, 2).slice(0, 300);
    feed.appendChild(row);
    while (feed.children.length > MAX_ROWS) feed.removeChild(feed.firstChild);
    feed.scrollTop = feed.scrollHeight;
  };
};
