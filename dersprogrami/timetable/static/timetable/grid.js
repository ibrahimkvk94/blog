/* Ana program görünümü: satırlar sınıf/öğretmen/derslik, sütunlar gün × saat.
 * Kartlar sürüklenerek ya da tıklanıp hedef hücreye tıklanarak taşınır. */
(function () {
  "use strict";

  const cfg = JSON.parse(document.getElementById("tt-config").textContent);
  const LOCK_SVG = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round"><rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/></svg>';
  const KIND_LABELS = { sinif: "Sınıf", ogretmen: "Öğretmen", derslik: "Derslik" };

  // ---- yardımcılar ------------------------------------------------------------------------
  const $ = (sel, root) => (root || document).querySelector(sel);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html != null) e.innerHTML = html; return e; };
  const urlFor = (tpl, id) => tpl.replace("/0/", "/" + id + "/");

  function store(key, value) {
    try { if (value === undefined) return localStorage.getItem(key); localStorage.setItem(key, value); } catch (e) { return null; }
    return null;
  }

  function csrf() {
    const m = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function api(url, options) {
    const res = await fetch(url, Object.assign({
      credentials: "same-origin",
      headers: { "X-CSRFToken": csrf(), "Content-Type": "application/json" },
    }, options || {}));
    let data = {};
    try { data = await res.json(); } catch (e) { /* boş yanıt */ }
    if (!res.ok || data.ok === false) throw new Error(data.message || "İşlem başarısız oldu.");
    return data;
  }

  function toast(message, kind) {
    const t = el("div", "toast" + (kind === "error" ? " error" : ""), esc(message));
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  document.addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-toggle=dropdown]");
    document.querySelectorAll(".dropdown.open").forEach((d) => { if (!toggle || d !== toggle.parentElement) d.classList.remove("open"); });
    if (toggle) toggle.parentElement.classList.toggle("open");
  });

  // ---- üretim sürüyor ekranı ----------------------------------------------------------------
  if (cfg.running) {
    const poll = async () => {
      let s;
      try { s = await api(cfg.statusUrl); } catch (e) { setTimeout(poll, 3000); return; }
      if (s.status !== "running") { location.reload(); return; }
      const p = s.progress || {};
      const pct = Math.min(100, Math.round((s.elapsed / Math.max(1, s.time_limit)) * 100));
      $("#run-bar").style.width = pct + "%";
      $("#run-elapsed").textContent = Math.round(s.elapsed) + " sn";
      $("#run-solutions").textContent = p.solutions || 0;
      $("#run-objective").textContent = p.objective != null ? p.objective.toLocaleString("tr-TR") : "–";
      $("#run-text").textContent = p.phase === "explain"
        ? "Bu kurallarla program mümkün değil; hangi kuralların çeliştiği aranıyor…"
        : p.solutions
        ? "Geçerli bir program bulundu; ceza puanı düşürülüyor. İstediğiniz an durdurup en iyisini alabilirsiniz."
        : "İlk geçerli program aranıyor…";
      setTimeout(poll, 1500);
    };
    poll();
    return;
  }
  if (!cfg.hasGrid) return;

  // ---- durum ------------------------------------------------------------------------------
  const board = $("#tt-board");
  const scroller = $("#tt-scroll");
  const drawer = $("#drawer");
  const state = {
    kind: store("tt-kind") || "sinif",
    zoom: store("tt-zoom") || "",
    data: null,
    cards: new Map(),
    selected: null,
    options: null,
    dragging: null,
    compare: "",
  };

  async function load() {
    try {
      state.data = await api(cfg.gridUrl + "?tur=" + state.kind + (state.compare ? "&karsilastir=" + state.compare : ""));
    } catch (e) {
      toast(e.message, "error");
      return;
    }
    state.cards = new Map();
    state.data.cards.concat(state.data.unplaced).forEach((c) => state.cards.set(c.id, c));
    render();
    if (state.selected && state.cards.has(state.selected)) select(state.selected);
    else clearSelection();
  }

  // ---- çizim ------------------------------------------------------------------------------
  function render() {
    const d = state.data;
    const P = d.periods.length;
    const D = d.days.length;
    board.className = "tt-board " + state.zoom;
    board.style.setProperty("--cols", P * D);
    board.innerHTML = "";

    const head = el("div", "tt-head");
    const hr = el("div", "tt-head-row");
    const corner = el("div", "tt-corner", esc(KIND_LABELS[state.kind]));
    hr.appendChild(corner);
    d.days.forEach((name, i) => {
      const day = el("div", "tt-day", esc(name));
      day.style.gridColumn = 2 + i * P + " / span " + P;
      day.style.gridRow = "1";
      hr.appendChild(day);
      d.periods.forEach((p, j) => {
        const cell = el("div", "tt-period" + (j === 0 ? " day-start" : ""), "<b>" + (p.index + 1) + "</b>" + esc(p.start || ""));
        cell.style.gridColumn = String(2 + i * P + j);
        cell.style.gridRow = "2";
        hr.appendChild(cell);
      });
    });
    head.appendChild(hr);
    board.appendChild(head);

    const byRow = new Map();
    d.cards.forEach((c) => c.rows.forEach((r) => {
      if (!byRow.has(r)) byRow.set(r, []);
      byRow.get(r).push(c);
    }));

    const frag = document.createDocumentFragment();
    d.rows.forEach((row) => {
      const cards = (byRow.get(row.id) || []).slice().sort((a, b) => (a.day * P + a.period) - (b.day * P + b.period));
      const laneEnds = [];
      const lanes = cards.map((c) => {
        const start = c.day * P + c.period;
        let lane = laneEnds.findIndex((end) => end <= start);
        if (lane === -1) { lane = laneEnds.length; laneEnds.push(0); }
        laneEnds[lane] = start + c.length;
        return lane;
      });
      const rowEl = el("div", "tt-row");
      rowEl.dataset.row = row.id;
      rowEl.dataset.search = (row.label + " " + (row.sub || "")).toLocaleLowerCase("tr");
      rowEl.style.setProperty("--lanes", Math.max(1, laneEnds.length));
      const label = el("div", "tt-label", '<span class="n">' + esc(row.label) + '</span><span class="s">' + esc(row.sub || "") + "</span>");
      label.title = row.label;
      rowEl.appendChild(label);
      for (let day = 0; day < D; day++) {
        for (let p = 0; p < P; p++) {
          const cell = el("div", "tt-cell" + (p === 0 ? " day-start" : ""));
          cell.style.gridColumn = String(2 + day * P + p);
          cell.dataset.day = day;
          cell.dataset.period = p;
          rowEl.appendChild(cell);
        }
      }
      // Aynı anda başka kartla çakışmayan kart satır yüksekliğinin tamamını kaplar; yalnızca
      // aynı saatteki grup dersleri şeritlere bölünür.
      const span = (c) => [c.day * P + c.period, c.day * P + c.period + c.length];
      cards.forEach((c, i) => {
        const [s, e] = span(c);
        const overlaps = cards.some((o, j) => j !== i && span(o)[0] < e && s < span(o)[1]);
        const card = cardEl(c);
        card.style.gridColumn = 2 + c.day * P + c.period + " / span " + c.length;
        card.style.gridRow = overlaps ? String(lanes[i] + 1) : "1 / -1";
        rowEl.appendChild(card);
      });
      frag.appendChild(rowEl);
    });
    board.appendChild(frag);
    applyFilter();
    renderTray();
    renderStats();
    renderViolations();
    renderHistory();
    renderCompare();
  }

  function renderHistory() {
    const h = state.data.history || {};
    const undo = $("#btn-undo"), redo = $("#btn-redo");
    undo.disabled = !h.undo;
    redo.disabled = !h.redo;
    undo.title = h.undo ? "Geri al: " + h.undo + " (Ctrl+Z)" : "Geri alınacak işlem yok";
    redo.title = h.redo ? "Yinele: " + h.redo + " (Ctrl+Y)" : "Yinelenecek işlem yok";
  }

  function renderCompare() {
    const c = state.data.compare;
    const panel = $("#compare-panel");
    board.classList.toggle("comparing", !!c);
    if (!panel) return;
    panel.hidden = !c;
    if (!c) return;
    const changed = new Set(c.changed);
    document.querySelectorAll(".tt-card").forEach((n) => n.classList.toggle("changed", changed.has(Number(n.dataset.card))));
    $("#compare-summary").textContent = c.summary + " · " + c.name;
    $("#compare-rows").innerHTML = c.rows.length
      ? c.rows.map((r) => "<tr><td>" + esc(r.lesson) + "</td><td>" + esc(r.before) + "</td><td>" + esc(r.after) + "</td></tr>").join("")
      : '<tr><td colspan="3" class="subtle">İki sürüm aynı.</td></tr>';
  }

  function cardEl(c) {
    const e = el("div", "tt-card" + (c.locked ? " locked" : ""),
      '<div class="t">' + (c.locked ? LOCK_SVG : "") + "<span>" + esc(c.subject) + '</span></div><div class="d">' + esc(c.line2) + "</div>");
    e.style.setProperty("--c", c.color);
    e.title = c.title;
    e.dataset.card = c.id;
    e.draggable = !c.locked;
    return e;
  }

  function renderTray() {
    const tray = $("#tray");
    tray.innerHTML = "";
    state.data.unplaced.forEach((c) => tray.appendChild(cardEl(c)));
    if (!state.data.unplaced.length) tray.appendChild(el("div", "subtle small", "Tüm kartlar yerleşmiş."));
    $("#tray-count").textContent = state.data.unplaced.length;
  }

  function renderStats() {
    const s = state.data.stats;
    const chips = [
      ["Kart", s.placed + " / " + (s.placed + s.unplaced)],
      ["Bekleyen", s.unplaced, s.unplaced > 0],
      ["Öğretmen boşluğu", s.teacher_gaps],
      ["Sınıf boşluğu", s.class_gaps, s.class_gaps > 0],
      ["İhlal", state.data.violations.length, state.data.violations.some((v) => v.level === "hard")],
    ];
    $("#stats").innerHTML = chips.map(([k, v, bad]) => '<span class="chip' + (bad ? " bad" : "") + '">' + esc(k) + " <b>" + esc(v) + "</b></span>").join("");
  }

  function renderViolations() {
    const list = $("#violations");
    const v = state.data.violations;
    $("#violation-pill").innerHTML = v.length
      ? '<span class="pill ' + (v.some((x) => x.level === "hard") ? "failed" : "warn") + '">' + v.length + " ihlal</span>"
      : '<span class="pill ok">Kural ihlali yok</span>';
    list.innerHTML = v.length
      ? v.map((x) => '<li class="' + x.level + '"><span class="dot"></span>' + esc(x.message) + "</li>").join("")
      : '<li class="subtle">Program tüm kuralları sağlıyor.</li>';
  }

  function applyFilter() {
    const q = ($("#row-filter").value || "").trim().toLocaleLowerCase("tr");
    board.querySelectorAll(".tt-row").forEach((r) => r.classList.toggle("hidden", q && !r.dataset.search.includes(q)));
  }

  // ---- seçim ve seçenekler ----------------------------------------------------------------
  function clearOptions() {
    board.querySelectorAll(".tt-cell[class*=opt-]").forEach((c) => { c.className = c.className.replace(/\s?opt-\w+/g, ""); c.removeAttribute("title"); });
    board.querySelectorAll(".tt-row.focus").forEach((r) => r.classList.remove("focus"));
  }

  function clearSelection() {
    state.selected = null;
    state.options = null;
    clearOptions();
    document.querySelectorAll(".tt-card.selected").forEach((c) => c.classList.remove("selected"));
    drawer.hidden = true;
    $("#tt-wrap").classList.remove("with-drawer");
  }

  async function select(cardId) {
    const card = state.cards.get(cardId);
    if (!card) return;
    state.selected = cardId;
    document.querySelectorAll(".tt-card.selected").forEach((c) => c.classList.remove("selected"));
    document.querySelectorAll('.tt-card[data-card="' + cardId + '"]').forEach((c) => c.classList.add("selected"));
    showDrawer(card, null);
    clearOptions();
    let res;
    try { res = await api(urlFor(cfg.optionsUrl, cardId)); } catch (e) { toast(e.message, "error"); return; }
    if (state.selected !== cardId) return;
    state.options = new Map(res.options.map((o) => [o.day + "-" + o.period, o]));
    paintOptions(card);
    showDrawer(card, res.options);
  }

  function paintOptions(card) {
    card.rows.forEach((rowId) => {
      const row = board.querySelector('.tt-row[data-row="' + rowId + '"]');
      if (!row) return;
      row.classList.add("focus");
      row.querySelectorAll(".tt-cell").forEach((cell) => {
        const o = state.options.get(cell.dataset.day + "-" + cell.dataset.period);
        const status = o ? o.status : "blocked";
        cell.classList.add("opt-" + status);
        cell.title = o && o.reasons.length ? o.reasons.join("\n") : (status === "free" ? "Uygun" : "Kart buraya sığmıyor");
      });
    });
  }

  function optionAt(cell) {
    if (!cell || !state.options || !state.selected) return null;
    const card = state.cards.get(state.selected);
    const row = cell.closest(".tt-row");
    if (!row || !card.rows.map(String).includes(row.dataset.row)) return null;
    const o = state.options.get(cell.dataset.day + "-" + cell.dataset.period);
    return o && o.status !== "blocked" ? o : null;
  }

  function cellAt(x, y) {
    return document.elementsFromPoint(x, y).find((e) => e.classList && e.classList.contains("tt-cell")) || null;
  }

  function showDrawer(card, options) {
    const d = state.data;
    const where = card.day == null
      ? "Yerleşmedi"
      : d.days[card.day] + ", " + (card.period + 1) + (card.length > 1 ? "–" + (card.period + card.length) : "") + ". saat";
    const counts = { free: 0, warn: 0, conflict: 0 };
    (options || []).forEach((o) => { if (o.status in counts) counts[o.status]++; });
    drawer.innerHTML =
      '<div class="panel-head"><h2><span class="swatch" style="background:' + esc(card.color) + '"></span> ' + esc(card.subject_name) + "</h2>" +
      '<button class="btn btn-ghost btn-sm" data-act="close" title="Kapat">✕</button></div>' +
      '<div class="panel-body"><dl class="kv">' +
      "<dt>Konum</dt><dd>" + esc(where) + "</dd>" +
      "<dt>Sınıf</dt><dd>" + esc(card.classes) + (card.groups ? " · " + esc(card.groups) : "") + "</dd>" +
      "<dt>Öğretmen</dt><dd>" + esc(card.teachers || "–") + "</dd>" +
      "<dt>Derslik</dt><dd>" + esc(card.room || "–") + "</dd>" +
      "<dt>Süre</dt><dd>" + card.length + " saat" + (card.length > 1 ? " (blok)" : "") + "</dd>" +
      "</dl>" +
      (options
        ? '<p class="small muted" style="margin:14px 0 6px">Uygun yer: <b>' + counts.free + "</b> · uyarılı: <b>" + counts.warn + "</b> · çakışmalı: <b>" + counts.conflict + "</b></p>" +
          '<p class="small subtle" style="margin:0 0 14px">Taşımak için ızgarada renklendirilmiş bir hücreye tıklayın ya da kartı sürükleyin.</p>'
        : '<p class="small subtle" style="margin:14px 0">Uygun hücreler hesaplanıyor…</p>') +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<button class="btn btn-sm" data-act="lock">' + (card.locked ? "Kilidi aç" : "Kilitle") + "</button>" +
      (card.day != null && !card.locked ? '<button class="btn btn-sm btn-danger" data-act="unplace">Programdan çıkar</button>' : "") +
      "</div></div>";
    drawer.hidden = false;
    $("#tt-wrap").classList.add("with-drawer");
  }

  // ---- işlemler ---------------------------------------------------------------------------
  async function run(promise, keepSelection) {
    try {
      const r = await promise;
      if (r.message) toast(r.message);
    } catch (e) {
      toast(e.message, "error");
    }
    if (!keepSelection) state.selected = null;
    await load();
  }

  const moveCard = (id, day, period) =>
    run(api(urlFor(cfg.moveUrl, id), { method: "POST", body: JSON.stringify({ day: Number(day), period: Number(period) }) }));
  const unplaceCard = (id) => run(api(urlFor(cfg.unplaceUrl, id), { method: "POST" }));

  drawer.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]");
    if (!act || !state.selected) return;
    const id = state.selected;
    if (act.dataset.act === "close") clearSelection();
    if (act.dataset.act === "lock") run(api(urlFor(cfg.lockUrl, id), { method: "POST" }), true);
    if (act.dataset.act === "unplace") unplaceCard(id);
  });

  function onCardOrCellClick(e) {
    const cardNode = e.target.closest(".tt-card");
    const option = optionAt(cellAt(e.clientX, e.clientY));
    const selected = state.selected;
    if (selected && option && (!cardNode || Number(cardNode.dataset.card) !== selected)) {
      moveCard(selected, option.day, option.period);
      return;
    }
    if (cardNode) {
      const id = Number(cardNode.dataset.card);
      if (id === selected) clearSelection();
      else select(id);
    }
  }
  board.addEventListener("click", onCardOrCellClick);
  $("#tray").addEventListener("click", (e) => {
    const cardNode = e.target.closest(".tt-card");
    if (cardNode) select(Number(cardNode.dataset.card));
  });

  // Sürükle-bırak
  document.addEventListener("dragstart", (e) => {
    const cardNode = e.target.closest && e.target.closest(".tt-card");
    if (!cardNode) return;
    const id = Number(cardNode.dataset.card);
    state.dragging = id;
    e.dataTransfer.setData("text/plain", String(id));
    e.dataTransfer.effectAllowed = "move";
    cardNode.classList.add("dragging");
    if (state.selected !== id) select(id);
  });
  document.addEventListener("dragend", (e) => {
    state.dragging = null;
    document.querySelectorAll(".dragging, .drop-over").forEach((n) => n.classList.remove("dragging", "drop-over"));
  });
  let lastOver = null;
  board.addEventListener("dragover", (e) => {
    if (state.dragging == null) return;
    const cell = cellAt(e.clientX, e.clientY);
    if (lastOver && lastOver !== cell) lastOver.classList.remove("drop-over");
    if (optionAt(cell)) {
      e.preventDefault();
      e.dataTransfer.dropEffect = "move";
      cell.classList.add("drop-over");
      lastOver = cell;
    }
  });
  board.addEventListener("drop", (e) => {
    const option = optionAt(cellAt(e.clientX, e.clientY));
    if (state.dragging == null || !option) return;
    e.preventDefault();
    moveCard(state.dragging, option.day, option.period);
  });
  const tray = $("#tray");
  tray.addEventListener("dragover", (e) => {
    const card = state.cards.get(state.dragging);
    if (!card || card.day == null) return;
    e.preventDefault();
    tray.classList.add("drop-over");
  });
  tray.addEventListener("dragleave", () => tray.classList.remove("drop-over"));
  tray.addEventListener("drop", (e) => {
    e.preventDefault();
    tray.classList.remove("drop-over");
    if (state.dragging != null) unplaceCard(state.dragging);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") clearSelection();
    if (!(e.ctrlKey || e.metaKey) || /INPUT|SELECT|TEXTAREA/.test(document.activeElement.tagName)) return;
    const key = e.key.toLowerCase();
    if (key === "z" && !e.shiftKey && !$("#btn-undo").disabled) { e.preventDefault(); historyStep(cfg.undoUrl); }
    if ((key === "y" || (key === "z" && e.shiftKey)) && !$("#btn-redo").disabled) { e.preventDefault(); historyStep(cfg.redoUrl); }
  });

  // Geri al / yinele
  const historyStep = (url) => run(api(url, { method: "POST" }));
  $("#btn-undo").addEventListener("click", () => historyStep(cfg.undoUrl));
  $("#btn-redo").addEventListener("click", () => historyStep(cfg.redoUrl));

  // Toplu işlemler
  const bulk = (body) => run(api(cfg.bulkUrl, { method: "POST", body: JSON.stringify(body) }));
  const dialog = $("#swap-dialog");
  function askSwap(action) {
    const isDay = action === "swap_days";
    const labels = isDay ? cfg.days : Array.from({ length: cfg.periodCount }, (_, i) => (i + 1) + ". saat");
    const options = labels.map((l, i) => '<option value="' + i + '">' + esc(l) + "</option>").join("");
    $("#swap-a").innerHTML = options;
    $("#swap-b").innerHTML = options;
    $("#swap-b").value = "1";
    $("#swap-title").textContent = isDay ? "İki günü yer değiştir" : "İki ders saatini yer değiştir";
    $("#swap-help").textContent = isDay
      ? "Seçilen iki günün tüm kartları (kilitliler dahil) yer değiştirir. Müsaitlik ihlalleri doğrulamada görünür."
      : "Bu iki saatteki tek saatlik kartlar yer değiştirir; bu saatlere taşan blok kartlar yerinde kalır.";
    dialog.onclose = () => {
      if (dialog.returnValue === "ok") bulk({ action, a: $("#swap-a").value, b: $("#swap-b").value });
    };
    dialog.returnValue = "";
    dialog.showModal();
  }
  const opsMenu = $("#ops-menu");
  if (opsMenu) {
    opsMenu.addEventListener("click", (e) => {
      const b = e.target.closest("[data-op]");
      if (!b) return;
      opsMenu.classList.remove("open");
      const op = b.dataset.op;
      if (op === "swap_days" || op === "swap_periods") askSwap(op);
      else if (op === "unplace_unlocked") {
        if (window.confirm("Kilitsiz tüm kartlar programdan çıkarılsın mı? Geri al ile geri getirebilirsiniz.")) bulk({ action: op });
      } else bulk({ action: op });
    });
  }

  // Karşılaştırma
  const compareSelect = $("#compare-select");
  if (compareSelect) {
    compareSelect.addEventListener("change", () => { state.compare = compareSelect.value; load(); });
    $("#compare-close").addEventListener("click", () => { state.compare = ""; compareSelect.value = ""; load(); });
  }

  // Araç çubuğu
  function setActive(group, attr, value) {
    group.querySelectorAll("button").forEach((b) => b.classList.toggle("active", b.dataset[attr] === value));
  }
  const kindSwitch = $("#kind-switch");
  setActive(kindSwitch, "kind", state.kind);
  kindSwitch.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.kind = b.dataset.kind;
    store("tt-kind", state.kind);
    setActive(kindSwitch, "kind", state.kind);
    clearSelection();
    scroller.scrollTo({ top: 0 });
    load();
  });
  const zoomSwitch = $("#zoom-switch");
  setActive(zoomSwitch, "zoom", state.zoom);
  zoomSwitch.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    state.zoom = b.dataset.zoom;
    store("tt-zoom", state.zoom);
    setActive(zoomSwitch, "zoom", state.zoom);
    board.className = "tt-board " + state.zoom;
  });
  $("#row-filter").addEventListener("input", applyFilter);

  const repairBtn = $("#btn-repair");
  if (repairBtn) {
    repairBtn.addEventListener("click", async () => {
      repairBtn.disabled = true;
      repairBtn.innerHTML = '<span class="spinner"></span> Yerleştiriliyor…';
      await run(api(cfg.repairUrl, { method: "POST" }));
      repairBtn.disabled = false;
      repairBtn.textContent = "Bekleyenleri yerleştir";
    });
  }

  load();
})();
