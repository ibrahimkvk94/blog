/* Bildirimler: zil menüsü (okunmamış sayısı, son bildirimler) ve anlık bildirimler (toast).
 *
 * Sunucu 30 sn'de bir (ve sekmeye dönülünce) yoklanır. Görülen son bildirimin kimliği tarayıcıda saklanır; aynı
 * bildirim birden çok sekmede ya da sayfa yenilenince yeniden açılmaz. İlk açılışta eski bildirimler toast olmaz.
 */
(function () {
  "use strict";
  const script = document.currentScript;
  const listUrl = script.dataset.url, readUrl = script.dataset.read;
  const KEY = "ntf-last", POLL = 30000;
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || "";
  // Görülen son bildirimin kimliği; null = bu tarayıcıda hiç bakılmadı (o zaman eski bildirimler toast olmaz).
  const load = () => { try { const v = localStorage.getItem(KEY); return v === null ? null : Number(v); } catch (e) { return null; } };
  const save = (v) => { try { localStorage.setItem(KEY, String(v)); } catch (e) { /* yok */ } };
  let memory = load();  // localStorage kapalıysa bu sayfa için

  const root = document.querySelector("[data-ntf]");
  const panel = root && root.querySelector("[data-ntf-panel]");
  const items = root && root.querySelector("[data-ntf-items]");

  function setCount(n) {
    document.querySelectorAll("[data-ntf-count]").forEach((b) => { b.hidden = !n; b.textContent = n > 99 ? "99+" : String(n); });
  }

  function render(list) {
    if (!items) return;
    items.innerHTML = list.length ? list.map((n) =>
      '<a class="ntf-row ntf-' + esc(n.level) + (n.read ? "" : " unread") + '" href="' + esc(n.url || script.dataset.page || "#") + '" data-id="' + n.id + '">' +
      '<span class="ntf-dot"></span><span><b>' + esc(n.title) + "</b>" + (n.body ? "<small>" + esc(n.body) + "</small>" : "") +
      '<em>' + esc(n.time) + "</em></span></a>").join("") : '<div class="empty small">Bildirim yok.</div>';
  }

  function toast(n) {
    const wrap = document.getElementById("toasts");
    if (!wrap) return;
    const el = document.createElement("div");
    el.className = "toast ntf-toast ntf-" + n.level;
    el.innerHTML = '<span class="ntf-dot"></span><div><b>' + esc(n.title) + "</b>" + (n.body ? "<small>" + esc(n.body) + "</small>" : "") +
      '</div><button type="button" aria-label="Kapat">✕</button>';
    el.querySelector("button").addEventListener("click", (e) => { e.stopPropagation(); el.remove(); });
    if (n.url) { el.style.cursor = "pointer"; el.addEventListener("click", () => { location.href = n.url; }); }
    wrap.appendChild(el);
    setTimeout(() => el.remove(), n.level === "error" || n.level === "warning" ? 15000 : 8000);
  }

  async function poll() {
    const stored = load();
    const seen = stored === null ? memory : Math.max(stored, memory || 0);
    try {
      const r = await fetch(listUrl + (seen !== null ? "?sonra=" + seen : ""), { credentials: "same-origin", headers: { Accept: "application/json" } });
      if (!r.ok) return;
      const d = await r.json();
      setCount(d.unread);
      render(d.latest);
      if (seen !== null && d.new) d.new.forEach(toast);
      const next = Math.max(seen || 0, d.last_id || 0);
      if (seen === null || next > seen) { memory = next; save(next); }
    } catch (e) { /* sunucu yeniden başlıyor olabilir: sonraki yoklamada */ }
  }

  async function markRead(body) {
    try {
      const r = await fetch(readUrl, { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(body) });
      if (r.ok) setCount((await r.json()).unread);
    } catch (e) { /* yok */ }
  }

  if (root) {
    const toggle = root.querySelector("[data-ntf-toggle]");
    toggle.addEventListener("click", (e) => {
      e.stopPropagation();
      panel.hidden = !panel.hidden;
      toggle.setAttribute("aria-expanded", panel.hidden ? "false" : "true");
      if (!panel.hidden) poll();
    });
    root.querySelector("[data-ntf-all]").addEventListener("click", async () => { await markRead({ all: true }); poll(); });
    document.addEventListener("click", (e) => { if (!panel.hidden && !root.contains(e.target)) panel.hidden = true; });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") panel.hidden = true; });
  }

  poll();
  setInterval(() => { if (!document.hidden) poll(); }, POLL);
  document.addEventListener("visibilitychange", () => { if (!document.hidden) poll(); });
})();
