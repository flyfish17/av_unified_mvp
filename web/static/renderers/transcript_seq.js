// renderer: transcript_seq
// 每条 partial 显示为黄虚线气泡，final 时变绿实线并锁定。
// 同一 seq_id 的事件复用同一气泡。
// FunASR 2pass-online 协议：每条 partial 是**增量片段**（一小段新词），不是累积全文。
//   所以 partial 直接 append 到气泡内（包成 .tx-flash span 触发逐字蹦闪光）。
//   2pass-offline final 给的是 canonical 整段文本（含 ITN/修正），用它整段替换 partial 累积。
window.Renderers = window.Renderers || {};

window.Renderers.transcript_seq = function makeTranscriptSeqRenderer(feed) {
  const liveBySeq = new Map();
  const MAX_BUBBLES = 60;

  function fmtTime(ts) {
    const d = ts ? new Date(ts * 1000) : new Date();
    const p = n => String(n).padStart(2, "0");
    return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  }

  function trim() {
    while (feed.children.length > MAX_BUBBLES) feed.removeChild(feed.firstChild);
  }

  return function render(ev) {
    if (ev.type === "hello") return;
    let el = liveBySeq.get(ev.seq_id);
    if (!el) {
      el = document.createElement("div");
      el.className = "bubble live";
      el.innerHTML = `<div class="text"></div><div class="meta"></div>`;
      feed.appendChild(el);
      liveBySeq.set(ev.seq_id, el);
      trim();
    }

    const textEl = el.querySelector(".text");
    const newText = ev.text || "";

    if (ev.is_final) {
      // final 整段定稿（FunASR 2pass-offline canonical 文本），清掉所有 flash span
      textEl.textContent = newText;
    } else if (newText) {
      // partial 增量 append：每条事件 = 一段新词，包成 flash span 触发逐字蹦闪光
      const span = document.createElement("span");
      span.className = "tx-flash";
      span.textContent = newText;
      textEl.appendChild(span);
    }

    el.querySelector(".meta").textContent =
      `seq=${ev.seq_id} · ${fmtTime(ev.ts)} · ${ev.raw_mode || (ev.is_final ? "final" : "partial")}`;
    if (ev.is_final) {
      el.classList.remove("live");
      el.classList.add("final");
      liveBySeq.delete(ev.seq_id);
    }
    feed.scrollTop = feed.scrollHeight;
  };
};
