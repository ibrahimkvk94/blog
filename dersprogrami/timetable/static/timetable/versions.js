/* Versiyonlar penceresi: liste, ön izleme (sınıf × gün/saat renk haritası), kaydetme ve geri dönme. */
(function () {
  "use strict";
  const cfgNode = document.getElementById("tt-config");
  const dialog = document.getElementById("versions-dialog");
  const button = document.getElementById("btn-versions");
  if (!cfgNode || !dialog || !button) return;
  const cfg = JSON.parse(cfgNode.textContent);
  const $ = (s) => dialog.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const csrf = () => { const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/); return m ? decodeURIComponent(m[1]) : ""; };
  const urlFor = (tpl, id) => tpl.replace("/0/", "/" + id + "/");
  let selected = null;

  async function api(url, body) {
    const res = await fetch(url, {
      method: body ? "POST" : "GET", credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.message || "İşlem başarısız oldu.");
    return data;
  }
  function toast(message, error) {
    const t = document.createElement("div");
    t.className = "toast" + (error ? " error" : "");
    t.textContent = message;
    document.getElementById("toasts").appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  async function load() {
    const data = await api(cfg.versionsUrl + ($("#versions-auto").checked ? "" : "?oto=0"));
    $("#versions-auto-count").textContent = data.auto_count;
    $("#versions-rows").innerHTML = data.versions.map((v, i) =>
      '<tr data-id="' + v.id + '" class="' + (v.auto ? "auto" : "") + '">' +
      "<td>" + v.number + (i === 0 ? ' <span class="pill ok">son</span>' : "") + "</td><td>" + esc(v.created) + "</td><td>" + esc(v.note) +
      "</td><td>" + esc(v.user || "–") + '</td><td class="num">' + (v.changes ? "~" + v.changes : "–") + "</td>" +
      '<td><button class="btn btn-sm" type="button">Aç</button></td></tr>').join("") ||
      '<tr><td colspan="6" class="subtle">Henüz versiyon yok.</td></tr>';
    $("#version-actions").hidden = true;
    selected = null;
    clearCanvas();
  }

  function clearCanvas() {
    const c = $("#version-canvas");
    c.getContext("2d").clearRect(0, 0, c.width, c.height);
  }

  async function preview(id) {
    const data = await api(urlFor(cfg.versionUrl, id));
    const canvas = $("#version-canvas");
    const cols = data.days.length * data.periods;
    const labelW = 46, headH = 14;
    const rowH = Math.max(5, Math.min(12, Math.floor(560 / Math.max(1, data.rows.length))));
    const cellW = (canvas.clientWidth || 300) > 0 ? ((300 - labelW) / cols) : 6;
    canvas.width = 300;
    canvas.height = headH + rowH * data.rows.length + 2;
    const g = canvas.getContext("2d");
    g.fillStyle = "#fff"; g.fillRect(0, 0, canvas.width, canvas.height);
    g.font = "9px sans-serif"; g.fillStyle = "#5b6474";
    data.days.forEach((d, i) => g.fillText(d.slice(0, 3), labelW + i * data.periods * cellW + 2, 10));
    data.rows.forEach((row, r) => {
      const y = headH + r * rowH;
      g.fillStyle = "#1c2230"; g.font = Math.min(9, rowH) + "px sans-serif";
      g.fillText(row.name.slice(0, 8), 1, y + rowH - 1);
      row.cells.forEach((color, i) => {
        g.fillStyle = color || (Math.floor(i / data.periods) % 2 ? "#eef0f4" : "#f6f7f9");
        g.fillRect(labelW + i * cellW, y, Math.max(1, cellW - 0.5), rowH - 1);
      });
    });
    g.strokeStyle = "#1c2230";
    for (let d = 1; d < data.days.length; d++) {
      const x = labelW + d * data.periods * cellW;
      g.beginPath(); g.moveTo(x, headH); g.lineTo(x, canvas.height); g.stroke();
    }
  }

  $("#versions-rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-id]");
    if (!tr) return;
    dialog.querySelectorAll("tr.on").forEach((r) => r.classList.remove("on"));
    tr.classList.add("on");
    selected = Number(tr.dataset.id);
    $("#version-actions").hidden = false;
    preview(selected).catch((err) => toast(err.message, true));
  });
  $("#versions-auto").addEventListener("change", load);
  $("#version-save").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const r = await api(cfg.versionsUrl, { note: e.target.note.value });
      e.target.note.value = "";
      toast(r.message);
      load();
    } catch (err) { toast(err.message, true); }
  });
  $("#version-actions").addEventListener("click", async (e) => {
    const b = e.target.closest("[data-vact]");
    if (!b || !selected) return;
    if (b.dataset.vact === "restore" && !window.confirm("Program bu versiyona döndürülsün mü? Mevcut hal önce otomatik kaydedilir.")) return;
    try {
      const r = await api(urlFor(cfg.versionUrl, selected), { action: b.dataset.vact });
      if (r.url) { location.href = r.url; return; }
      toast(r.message);
      location.reload();
    } catch (err) { toast(err.message, true); }
  });
  button.addEventListener("click", () => { dialog.showModal(); load().catch((err) => toast(err.message, true)); });
})();
