// transcript.js —— 订阅 /events/transcript，实时绘制 partial → final
// 风格参考 woldmonitor/static/monitor.js：原生 JS，setInterval/EventSource 自驱

(function () {
  const feedEl = document.getElementById("feed");
  const statusEl = document.getElementById("status");

  // 同一句的 partial 持续刷新同一个 .bubble.live；定稿后凝固为 .bubble.final
  let liveBySeq = new Map(); // seq_id -> HTMLElement

  function setStatus(text, cls) {
    statusEl.textContent = text;
    statusEl.className = "status " + cls;
  }

  function fmtTime(ts) {
    const d = new Date(ts * 1000);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
  }

  function ensureBubble(seq) {
    let el = liveBySeq.get(seq);
    if (el) return el;
    el = document.createElement("div");
    el.className = "bubble live";
    el.innerHTML = `<div class="text"></div><div class="meta"></div>`;
    feedEl.appendChild(el);
    liveBySeq.set(seq, el);
    feedEl.scrollTop = feedEl.scrollHeight;
    return el;
  }

  function applyEvent(ev) {
    if (ev.type === "hello") return;

    const el = ensureBubble(ev.seq_id);
    el.querySelector(".text").textContent = ev.text;
    el.querySelector(".meta").textContent =
      `seq=${ev.seq_id} · ${fmtTime(ev.ts)} · ${ev.raw_mode || (ev.is_final ? "final" : "partial")}`;

    if (ev.is_final) {
      el.classList.remove("live");
      el.classList.add("final");
      liveBySeq.delete(ev.seq_id);
    }
    feedEl.scrollTop = feedEl.scrollHeight;
  }

  function connect() {
    setStatus("连接中…", "warn");
    const es = new EventSource("/events/transcript");

    es.onopen = () => setStatus("已连接", "ok");
    es.onerror = () => {
      setStatus("已断开 · 自动重连", "warn");
      // EventSource 自带重连
    };
    es.onmessage = (e) => {
      try {
        applyEvent(JSON.parse(e.data));
      } catch (err) {
        console.warn("bad SSE payload", e.data, err);
      }
    };
  }

  connect();
})();
