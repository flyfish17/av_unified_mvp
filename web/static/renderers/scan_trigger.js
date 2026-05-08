// renderer: scan_trigger
// 由 network_scanner 通过 endpoints[{kind:"scan_trigger", topic, default_subnet}] 触发；
// 渲染一个输入框 + 启动按钮，点击后 POST /mqtt/publish。
window.Renderers = window.Renderers || {};

window.Renderers.scan_trigger = function makeScanTriggerRenderer(feed) {
  const cards = new Map(); // topic → control row

  function ensureCard(ep) {
    const key = ep.topic;
    let c = cards.get(key);
    if (c) return c;
    const wrap = document.createElement("div");
    wrap.className = "row";
    wrap.style.cssText = "display:flex;gap:8px;align-items:center;flex-wrap:wrap;";

    const label = document.createElement("span");
    label.style.cssText = "font-size:11px;color:var(--dim);";
    label.textContent = "扫描子网";

    const input = document.createElement("input");
    input.type = "text";
    input.placeholder = ep.default_subnet || "192.168.1.0/24";
    input.value = ep.default_subnet || "";
    input.style.cssText =
      "flex:1;min-width:140px;font-size:12px;padding:4px 8px;" +
      "border:1px solid var(--line);background:var(--bg);" +
      "color:var(--text);border-radius:4px;font-family:ui-monospace,monospace;";

    const btn = document.createElement("button");
    btn.textContent = "启动扫描";
    btn.style.cssText =
      "font-size:12px;padding:4px 14px;border-radius:4px;cursor:pointer;" +
      "background:var(--accent);color:#0d1117;border:0;font-weight:600;";

    const status = document.createElement("span");
    status.style.cssText = "font-size:11px;color:var(--dim);";

    btn.onclick = async () => {
      const subnet = input.value.trim() || ep.default_subnet;
      btn.disabled = true;
      btn.style.opacity = "0.5";
      status.textContent = "发送中…";
      try {
        const r = await fetch("/mqtt/publish", {
          method: "POST",
          headers: {"Content-Type": "application/json"},
          body: JSON.stringify({
            topic: ep.topic,
            payload: {subnet, ports: ep.ports, timeout_ms: ep.timeout_ms},
          }),
        });
        const j = await r.json();
        status.textContent = j.ok ? "✓ 已触发，看下方结果…" : `✗ ${j.error}`;
      } catch (err) {
        status.textContent = "✗ " + err.message;
      } finally {
        setTimeout(() => { btn.disabled = false; btn.style.opacity = "1"; status.textContent = ""; }, 3000);
      }
    };

    wrap.appendChild(label);
    wrap.appendChild(input);
    wrap.appendChild(btn);
    wrap.appendChild(status);
    feed.appendChild(wrap);
    c = { wrap, input };
    cards.set(key, c);
    return c;
  }

  function setEndpoints(endpoints) {
    for (const ep of endpoints || []) {
      if (ep.kind !== "scan_trigger" || !ep.topic) continue;
      ensureCard(ep);
    }
  }

  const renderFn = function (_ev) { /* 不订阅 SSE */ };
  renderFn.setEndpoints = setEndpoints;
  return renderFn;
};
