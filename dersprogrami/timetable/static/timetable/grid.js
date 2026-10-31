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
      headers: { "X-CSRFToken": csrf(), "Content-Type": "application/json", "X-Grid-Kind": state.kind },
    }, options || {}));
    let data = {};
    try { data = await res.json(); } catch (e) { /* boş yanıt */ }
    if (!res.ok || data.ok === false) {
      const err = new Error(data.message || "İşlem başarısız oldu.");
      err.data = data;
      err.status = res.status;
      throw err;
    }
    return data;
  }

  function toast(message, kind) {
    const t = el("div", "toast" + (kind === "error" ? " error" : ""), esc(message));
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }

  document.addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-toggle=dropdown]");
    if (!toggle && e.target.closest(".dropdown-form")) return;  // form menüsü içinde seçim yaparken açık kalır
    document.querySelectorAll(".dropdown.open").forEach((d) => { if (!toggle || d !== toggle.parentElement) d.classList.remove("open"); });
    if (toggle) toggle.parentElement.classList.toggle("open");
  });


  // Bugünün gün sırası (Pazartesi = 0).
  function todayIndex() {
    return (new Date().getDay() + 6) % 7;
  }

  function readJSON(text) {
    try { return JSON.parse(text) || {}; } catch (e) { return {}; }
  }

  // ---- durum ------------------------------------------------------------------------------
  const board = $("#tt-board");
  const scroller = $("#tt-scroll");
  const drawer = $("#drawer");
  // Kart paneli: ızgaranın yanına sabit / serbest (sürüklenir) / küçültülmüş; bkz. applyDrawerMode.
  const drawerMode = { dock: store("tt-drawer-dock") !== "0", min: store("tt-drawer-min") === "1", pos: null };
  try { drawerMode.pos = JSON.parse(store("tt-drawer-pos") || "null"); } catch (e) { drawerMode.pos = null; }
  const state = {
    // ?tur=ogretmen&ara=Ad ile açılabilir (kalite karnesinden satıra gitmek için)
    kind: (KIND_LABELS[new URLSearchParams(location.search).get("tur")] && new URLSearchParams(location.search).get("tur")) || store("tt-kind") || "sinif",
    zoom: store("tt-zoom") === null ? "fit" : store("tt-zoom"),
    data: null,
    cards: new Map(),
    selected: null,
    options: null,
    dragging: null,
    compare: "",
    preview: null,  // çözüm merkezi önizlemesi: {index, total, moves, ...}
    view: Object.assign({ title: "code", line: "auto", color: "subject", stripes: true }, readJSON(store("tt-view"))),
  };

  // ---- üretim sürüyor ekranı -------------------------------------------------------------
  // state'ten sonra olmalı: api() her isteğe state.kind ekler (önce çağrılırsa sorgu hiç gitmez).
  if (cfg.running) {
    let failures = 0;
    const poll = async () => {
      let s;
      try { s = await api(cfg.statusUrl); } catch (e) {
        failures += 1;
        if (failures >= 3) $("#run-text").textContent = "Üretim durumu alınamıyor (" + e.message + "); yeniden deneniyor…";
        setTimeout(poll, 3000);
        return;
      }
      failures = 0;
      if (s.status !== "running") { location.reload(); return; }
      const p = s.progress || {};
      const pct = Math.min(100, Math.round((s.elapsed / Math.max(1, s.time_limit)) * 100));
      $("#run-bar").style.width = pct + "%";
      $("#run-elapsed").textContent = Math.round(s.elapsed) + " sn";
      $("#run-solutions").textContent = p.solutions || 0;
      $("#run-objective").textContent = p.objective != null ? p.objective.toLocaleString("tr-TR") : "–";
      $("#run-text").textContent = p.phase === "diagnose"
        ? "Katı modda program bulunamadı; nedenini bulmak için kurallar esnetilerek en yakın taslak aranıyor…" + (p.solutions ? " (" + p.solutions + " taslak)" : "")
        : p.phase === "explain"
        ? "Bu kurallarla program mümkün değil; hangi kuralların çeliştiği aranıyor…"
        : p.phase === "repair"
        ? "Doğrudan arama tıkandı; önce her dersin yerleştiği yaklaşık bir program kuruluyor, sonra kurallara uyacak şekilde onarılıyor…"
        : p.phase === "feasible"
        ? "Geçerli bir program bulundu (" + p.elapsed + " sn); şimdi boşluklar ve tercihler iyileştiriliyor…"
        : p.solutions
        ? "Geçerli bir program bulundu; ceza puanı düşürülüyor. İstediğiniz an durdurup en iyisini alabilirsiniz."
        : "İlk geçerli program aranıyor…";
      setTimeout(poll, 1500);
    };
    poll();
    return;
  }
  if (!cfg.hasGrid) return;

  async function load() {
    try {
      state.data = await api(cfg.gridUrl + "?tur=" + state.kind + (state.compare ? "&karsilastir=" + state.compare : ""));
    } catch (e) {
      toast(e.message, "error");
      return;
    }
    if (state.preview) applyPreview(state.data);
    state.cards = new Map();
    state.data.cards.concat(state.data.unplaced).forEach((c) => state.cards.set(c.id, c));
    render();
    if (state.preview) drawPreview();
    if (state.selected && state.cards.has(state.selected)) select(state.selected);
    else clearSelection();
  }

  // ---- çizim ------------------------------------------------------------------------------
  function render() {
    const d = state.data;
    const P = d.periods.length;
    const D = d.days.length;
    board.className = "tt-board " + state.zoom + (state.view.stripes ? " stripes" : "");
    board.style.setProperty("--cols", P * D);
    // Satır başlığı en uzun ada göre daralır (aSc'deki gibi yalnızca kısa ad); ayrıntı ipucunda.
    const longest = d.rows.reduce((m, r) => Math.max(m, r.label.length), 4);
    const charW = state.zoom === "roomy" ? 8.2 : state.zoom === "" ? 7.8 : 7.2;
    board.style.setProperty("--label", Math.round(Math.min(170, Math.max(54, longest * charW + 18))) + "px");
    board.innerHTML = "";

    const head = el("div", "tt-head");
    const hr = el("div", "tt-head-row");
    const corner = el("div", "tt-corner", esc(KIND_LABELS[state.kind]));
    hr.appendChild(corner);
    d.days.forEach((name, i) => {
      const day = el("div", "tt-day" + (i % 2 ? " day-alt" : "") + (i === todayIndex() ? " today" : ""), esc(name));
      day.style.gridColumn = 2 + i * P + " / span " + P;
      day.style.gridRow = "1";
      hr.appendChild(day);
      d.periods.forEach((p, j) => {
        const start = (p.starts && p.starts[i]) || p.start || "";  // o güne özel saat
        const cell = el("div", "tt-period" + (j === 0 ? " day-start" : "") + (i % 2 ? " day-alt" : "") + (i === todayIndex() ? " today" : "") + (start !== (p.start || "") ? " day-time" : ""), "<b>" + (p.index + 1) + "</b>" + esc(start));
        cell.title = d.days[i] + ", " + (p.index + 1) + ". saat" + (start ? " · " + start : "");
        cell.dataset.day = i;
        cell.dataset.period = j;
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
    d.rows.forEach((row) => frag.appendChild(buildRow(row, byRow.get(row.id) || [])));
    board.appendChild(frag);
    applyFilter();
    fitDensity();
    renderTray();
    renderStats();
    renderViolations();
    renderHistory();
    renderCompare();
  }

  // Tek satırın çizimi: tam çizimde ve kart işleminden sonra yalnızca etkilenen satırlarda kullanılır.
  function buildRow(row, rowCards) {
    const d = state.data;
    const P = d.periods.length;
    const D = d.days.length;
    const cards = rowCards.slice().sort((a, b) => (a.day * P + a.period) - (b.day * P + b.period));
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
    label.title = row.label + (row.sub ? "\n" + row.sub : "") + "\nSağ tık: işlemler";
    label.dataset.row = row.id;
    rowEl.appendChild(label);
    for (let day = 0; day < D; day++) {
      for (let p = 0; p < P; p++) {
        const cell = el("div", "tt-cell" + (p === 0 ? " day-start" : "") + (day % 2 ? " day-alt" : "") + (day === todayIndex() ? " today" : ""));
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
      if (c.pv) { card.classList.add(c.pv); if (c.pv === "pv-ghost") { card.draggable = false; card.dataset.card = ""; } }
      card.style.gridColumn = 2 + c.day * P + c.period + " / span " + c.length;
      card.style.gridRow = overlaps ? String(lanes[i] + 1) : "1 / -1";
      rowEl.appendChild(card);
    });
    return rowEl;
  }

  // Kart işleminin yanıtındaki değişiklikleri uygular (yalnızca değişen kartlar gelir); tüm tablo
  // yeniden yüklenmez. Karşılaştırma ve önizlemede, ya da görünüm türü değiştiyse false döner.
  function applyDelta(delta) {
    const d = state.data;
    if (!delta || !d || state.compare || state.preview || delta.kind !== state.kind) return false;
    const P = d.periods.length;
    const incoming = new Map(delta.cards.map((c) => [c.id, c]));
    const affected = new Set();
    const keep = (list) => list.filter((c) => {
      if (!incoming.has(c.id)) return true;
      c.rows.forEach((r) => affected.add(r));
      return false;
    });
    d.cards = keep(d.cards);
    d.unplaced = keep(d.unplaced);
    delta.cards.forEach((c) => {
      c.rows.forEach((r) => affected.add(r));
      (c.day == null ? d.unplaced : d.cards).push(c);
      state.cards.set(c.id, c);
    });
    d.stats = delta.stats;
    d.violations = delta.violations;
    if (delta.history) d.history = delta.history;
    affected.forEach((id) => {
      const row = d.rows.find((r) => r.id === id);
      const old = board.querySelector('.tt-row[data-row="' + id + '"]');
      if (!row || !old) return;
      const placed = d.cards.filter((c) => c.rows.includes(id));
      const cells = new Set();
      placed.forEach((c) => { for (let i = 0; i < c.length; i++) cells.add(c.day * P + c.period + i); });
      const pending = state.kind === "derslik" ? 0 : d.unplaced.filter((c) => c.rows.includes(id)).reduce((n, c) => n + c.length, 0);
      row.sub = [row.base, cells.size + " saat" + (pending ? " · " + pending + " bekliyor" : "")].filter(Boolean).join(" · ");
      const fresh = buildRow(row, placed);
      fresh.className = old.className;  // süzgeç ve odak sınıfları korunur
      old.replaceWith(fresh);
    });
    renderTray();
    renderStats();
    renderViolations();
    renderHistory();
    return true;
  }

  // "Haftayı sığdır" görünümünde sütun daraldıkça kart yazıları küçülür.
  function fitDensity() {
    const fit = state.zoom === "fit";
    const cell = fit && board.querySelector(".tt-row .tt-cell");
    const width = cell ? cell.getBoundingClientRect().width : 99;
    board.classList.toggle("tight", fit && width < 46);
    board.classList.toggle("tiny", fit && width < 30);
  }
  window.addEventListener("resize", () => { if (state.data) fitDensity(); });

  function renderHistory() {
    const h = state.data.history || {};
    const undo = $("#btn-undo"), redo = $("#btn-redo");
    undo.disabled = !h.undo;
    redo.disabled = !h.redo;
    undo.title = h.undo ? "Geri al: " + h.undo + " (Ctrl+Z)" : "Geri alınacak işlem yok";
    redo.title = h.redo ? "Yinele: " + h.redo + " (Ctrl+Y)" : "Yinelenecek işlem yok";
  }

  // ---- çözüm merkezi önizlemesi ---------------------------------------------------------------
  // Taşınan kartlar yeni yerlerinde vurgulu, eski yerlerinde soluk "hayalet" olarak çizilir; okla bağlanır.
  function applyPreview(data) {
    const moves = new Map(state.preview.moves.map((m) => [m.card, m]));
    const ghosts = [];
    const moveCard = (c) => {
      const m = moves.get(c.id);
      if (!m) return c;
      if (m.from) ghosts.push({ ...c, day: m.from[0], period: m.from[1], pv: "pv-ghost" });
      return { ...c, day: m.to[0], period: m.to[1], pv: "pv-moved" };
    };
    const placed = data.cards.map(moveCard);
    const unplacedMoved = data.unplaced.filter((c) => moves.has(c.id)).map(moveCard);
    data.cards = placed.concat(unplacedMoved, ghosts);
    data.unplaced = data.unplaced.filter((c) => !moves.has(c.id));
    // Doğrulama listesi ve sayaçlar önerinin uygulanmış haline göre (sunucu hesaplar).
    if (state.preview.violations) data.violations = state.preview.violations;
    if (state.preview.stats) data.stats = state.preview.stats;
  }

  function drawPreview() {
    board.classList.add("previewing");
    const only = $("#pv-only").checked;
    const rows = new Set();
    board.querySelectorAll(".pv-moved, .pv-ghost").forEach((n) => rows.add(n.closest(".tt-row")));
    board.querySelectorAll(".tt-row").forEach((r) => r.classList.toggle("pv-hide", only && !rows.has(r)));
    board.querySelector("svg.pv-arrows")?.remove();
    const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
    svg.setAttribute("class", "pv-arrows");
    const base = board.getBoundingClientRect();
    svg.setAttribute("width", board.scrollWidth);
    svg.setAttribute("height", board.scrollHeight);
    svg.innerHTML = '<defs><marker id="pv-head" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z"/></marker></defs>';
    rows.forEach((row) => {
      row.querySelectorAll(".pv-ghost").forEach((g) => {
        const target = [...row.querySelectorAll(".pv-moved")].find((m) => m.title === g.title);
        if (!target) return;
        const a = g.getBoundingClientRect(), b = target.getBoundingClientRect();
        const x1 = a.left + a.width / 2 - base.left, y1 = a.top + a.height / 2 - base.top;
        const x2 = b.left + b.width / 2 - base.left, y2 = b.top + b.height / 2 - base.top;
        const bend = Math.min(40, Math.abs(x2 - x1) / 4 + 12);
        const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
        path.setAttribute("d", `M${x1} ${y1} C ${x1} ${y1 - bend}, ${x2} ${y2 - bend}, ${x2} ${y2}`);
        path.setAttribute("marker-end", "url(#pv-head)");
        svg.appendChild(path);
      });
    });
    board.appendChild(svg);
  }

  async function startPreview(index) {
    let res;
    try { res = await api(urlFor(cfg.previewUrl, index)); } catch (e) { toast(e.message, "error"); return; }
    state.preview = res;
    $("#preview-bar").hidden = false;
    $("#pv-label").textContent = "Öneri " + (res.index + 1) + "/" + res.total + " · " + res.label + " · " + res.count + " ders yer değiştiriyor" +
      (res.new_violations ? " · " + res.new_violations + " yeni ihlal" : "");
    $("#pv-moves").textContent = res.moves.map((m) => m.text).join("  ·  ");
    $("#pv-index").value = res.index;
    $("#pv-prev").disabled = res.index === 0;
    $("#pv-next").disabled = res.index >= res.total - 1;
    history.replaceState(null, "", "?onizleme=" + res.index);
    await load();
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

  // Kart görünümü: başlık, alt satır ve renk ölçütü kullanıcıya göre (tarayıcıda saklanır).
  const PALETTE = ["#dbeafe", "#dcfce7", "#fef3c7", "#fce7f3", "#e0e7ff", "#ccfbf1", "#fee2e2", "#ede9fe",
    "#fef9c3", "#cffafe", "#ffedd5", "#f3e8ff", "#d9f99d", "#e2e8f0", "#fbcfe8", "#bae6fd"];
  function hashColor(key) {
    let h = 0;
    for (const ch of String(key)) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
    return PALETTE[h % PALETTE.length];
  }
  function cardColor(c) {
    const v = state.view.color;
    if (v === "none") return "#eef0f4";
    if (v === "teacher") return c.teacher_ids.length ? hashColor("t" + c.teacher_ids[0]) : "#eef0f4";
    if (v === "class") return c.class_ids.length ? hashColor("c" + c.class_ids[0]) : "#eef0f4";
    if (v === "room") return c.room ? hashColor("r" + c.room) : "#eef0f4";
    return c.color;
  }
  function isDark(hex) {
    const m = /^#?([0-9a-f]{6})$/i.exec(hex || "");
    if (!m) return false;
    const n = parseInt(m[1], 16);
    return (0.299 * (n >> 16) + 0.587 * ((n >> 8) & 255) + 0.114 * (n & 255)) < 140;
  }
  function cardLine(c) {
    const v = state.view.line;
    if (v === "none") return "";
    if (v === "auto") return c.line2;
    return c[v] || "";
  }

  function cardEl(c) {
    const color = cardColor(c);
    const title = state.view.title === "name" ? c.subject_name : c.subject;
    const line = cardLine(c);
    const e = el("div", "tt-card" + (c.locked ? " locked" : "") + (isDark(color) ? " dark" : ""),
      '<div class="t">' + (c.locked ? LOCK_SVG : "") + "<span>" + esc(title) + "</span></div>" + (line ? '<div class="d">' + esc(line) + "</div>" : ""));
    e.style.setProperty("--c", color);
    e.title = c.title;
    e.dataset.card = c.id;
    e.draggable = !c.locked && cfg.canEdit;
    return e;
  }

  // ---- yerleşmeyen kartlar: ekranın altına sabit, süzülebilir ------------------------------
  const trayCtl = {
    q: $("#tray-q"), cls: $("#tray-class"), teacher: $("#tray-teacher"), length: $("#tray-length"),
    sort: $("#tray-sort"), row: $("#tray-row"), clear: $("#tray-clear"),
  };
  const split = (text) => (text || "").split(", ").filter(Boolean);
  const trLower = (t) => (t || "").toLocaleLowerCase("tr");

  function fillSelect(select, values, label) {
    const current = select.value;
    select.innerHTML = '<option value="">' + esc(label) + "</option>" +
      values.map((v) => '<option value="' + esc(v) + '"' + (String(v) === current ? " selected" : "") + ">" + esc(v) + "</option>").join("");
    if (current && !values.map(String).includes(current)) select.value = "";
  }

  function visibleRows() {
    return new Set([...board.querySelectorAll(".tt-row:not(.hidden)")].map((r) => r.dataset.row));
  }

  function renderTray() {
    const tray = $("#tray");
    const all = state.data.unplaced;
    const byText = (a, b) => a.localeCompare(b, "tr");
    fillSelect(trayCtl.cls, [...new Set(all.flatMap((c) => split(c.classes)))].sort(byText), "Tüm sınıflar");
    fillSelect(trayCtl.teacher, [...new Set(all.flatMap((c) => split(c.teachers)))].sort(byText), "Tüm öğretmenler");
    fillSelect(trayCtl.length, [...new Set(all.map((c) => c.length))].sort((a, b) => a - b).map((n) => n + " saat"), "Her uzunluk");
    const q = trLower(trayCtl.q.value.trim());
    const rows = trayCtl.row.checked ? visibleRows() : null;
    let shown = all.filter((c) =>
      (!q || trLower([c.subject, c.subject_name, c.classes, c.teachers, c.groups].join(" ")).includes(q)) &&
      (!trayCtl.cls.value || split(c.classes).includes(trayCtl.cls.value)) &&
      (!trayCtl.teacher.value || split(c.teachers).includes(trayCtl.teacher.value)) &&
      (!trayCtl.length.value || c.length + " saat" === trayCtl.length.value) &&
      (!rows || c.rows.some((r) => rows.has(String(r)))));
    const key = trayCtl.sort.value;
    shown = shown.slice().sort((a, b) => key === "length" ? b.length - a.length || byText(a.subject, b.subject)
      : key ? byText(a[key] || "", b[key] || "") || byText(a.subject, b.subject) : byText(a.subject, b.subject));
    tray.innerHTML = "";
    shown.forEach((c) => tray.appendChild(cardEl(c)));
    if (!all.length) tray.appendChild(el("div", "subtle small", "Tüm kartlar yerleşmiş."));
    else if (!shown.length) tray.appendChild(el("div", "subtle small", "Süzgece uyan kart yok."));
    const filtered = shown.length !== all.length;
    $("#tray-count").textContent = filtered ? shown.length + " / " + all.length : all.length;
    trayCtl.clear.hidden = !filtered && !trayCtl.q.value;
    $("#tray-panel").classList.toggle("empty", !all.length);
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
    if (state.preview) $("#violation-pill").insertAdjacentHTML("afterbegin", '<span class="pill">öneriye göre</span> ');
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
    board.querySelectorAll(".tt-cell[class*=opt-], .tt-period[class*=opt-]").forEach((c) => { c.className = c.className.replace(/\s?opt-\w+/g, ""); if (c.classList.contains("tt-cell")) c.removeAttribute("title"); });
    board.querySelectorAll(".tt-row.focus").forEach((r) => r.classList.remove("focus"));
    board.querySelectorAll(".tt-card.shift-target").forEach((c) => { c.classList.remove("shift-target"); delete c.dataset.shiftAt; });
  }

  function clearSelection() {
    state.selected = null;
    state.options = null;
    clearOptions();
    document.querySelectorAll(".tt-card.selected").forEach((c) => c.classList.remove("selected"));
    drawer.hidden = true;
    $("#tt-wrap").classList.remove("with-drawer");
    applyDrawerMode();
  }

  async function select(cardId) {
    if (state.preview) return;  // önizlemede düzenleme yok
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
    showDrawer(card, res.options, res.why);
  }

  // Seçili kartın satırında bir hücrenin üzerine gelince nedeni bilgi kartında yazılır (title gecikmesiz).
  board.addEventListener("mouseover", (e) => {
    if (!e.target.closest || !e.target.closest(".tt-row.focus")) return;
    const cell = cellAt(e.clientX, e.clientY);  // kartların altındaki hücre de bulunur
    const out = drawer.querySelector("[data-hover-reason]");
    if (!cell || !out || !state.options || !cell.closest(".tt-row.focus")) return;
    const o = state.options.get(cell.dataset.day + "-" + cell.dataset.period);
    const d = state.data;
    const where = d.days[cell.dataset.day] + " " + (Number(cell.dataset.period) + 1) + ". saat: ";
    const status = o ? o.status : "blocked";
    const text = o && o.reasons.length ? o.reasons.join(" · ") : status === "free" ? "uygun" : "kart buraya konamaz";
    out.className = "ru-hover st-" + status;
    out.textContent = where + text;
  });

  function paintOptions(card) {
    // Sütun başlıkları da kartın o saatteki durumunu gösterir (aSc 13.3): yeşil uygun, kırmızı çakışma, gri kapalı.
    board.querySelectorAll(".tt-period").forEach((cell) => {
      const o = state.options.get(cell.dataset.day + "-" + cell.dataset.period);
      cell.classList.add("opt-" + (o ? o.status : "blocked"));
    });
    card.rows.forEach((rowId) => {
      const row = board.querySelector('.tt-row[data-row="' + rowId + '"]');
      if (!row) return;
      row.classList.add("focus");
      row.querySelectorAll(".tt-cell").forEach((cell) => {
        const o = state.options.get(cell.dataset.day + "-" + cell.dataset.period);
        const status = o ? o.status : "blocked";
        cell.classList.add("opt-" + status);
        cell.title = o && o.reasons.length ? o.reasons.join("\n") : (status === "free" ? "Uygun" : "Kapalı: kart buraya konamaz");
      });
      // Yer açarak konulabilecek hücreleri kaplayan kartlar (sıradaki taşınacak kart adayları) yeşil çerçeveli
      row.querySelectorAll(".tt-card").forEach((node) => {
        const other = state.cards.get(Number(node.dataset.card));
        if (!other || other.id === card.id || other.day == null) return;
        for (let i = 0; i < other.length; i++) {
          const o = state.options.get(other.day + "-" + (other.period + i));
          if (o && o.status === "shift") { node.classList.add("shift-target"); node.dataset.shiftAt = o.day + "-" + o.period; break; }
        }
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

  function whyHtml(why) {
    if (!why || !why.length) return "";
    const rows = why.slice(0, 5).map((w) => {
      const parts = [];
      if (w.busy) parts.push(w.busy + " saatte dersi var");
      if (w.closed) parts.push(w.closed + " saatte müsait değil");
      return "<li><b>" + esc(w.who) + "</b>: " + parts.join(", ") + "</li>";
    }).join("");
    return '<div class="why-box"><div class="label" style="margin:0 0 4px">Neden kırmızı / gri?</div><ul>' + rows + "</ul>" +
      '<div class="ru-hover" data-hover-reason>Satırdaki bir hücrenin üzerine gelin: nedeni burada görünür.</div></div>';
  }

  function showDrawer(card, options, why) {
    const d = state.data;
    const where = card.day == null
      ? "Yerleşmedi"
      : d.days[card.day] + ", " + (card.period + 1) + (card.length > 1 ? "–" + (card.period + card.length) : "") + ". saat";
    const counts = { free: 0, warn: 0, shift: 0, conflict: 0 };
    (options || []).forEach((o) => { if (o.status in counts) counts[o.status]++; });
    drawer.innerHTML =
      '<div class="panel-head" data-drag><h2><span class="swatch" style="background:' + esc(card.color) + '"></span> ' + esc(card.subject_name) + "</h2>" +
      '<span class="drawer-tools">' +
      '<button class="btn btn-ghost btn-sm" data-act="dock" title="' + (drawerMode.dock ? "Serbest bırak (sürüklenebilir)" : "Izgaranın yanına sabitle") + '">' + (drawerMode.dock ? "⧉" : "⇥") + "</button>" +
      '<button class="btn btn-ghost btn-sm" data-act="min" title="' + (drawerMode.min ? "Büyüt" : "Küçült") + '">' + (drawerMode.min ? "▢" : "–") + "</button>" +
      '<button class="btn btn-ghost btn-sm" data-act="close" title="Kapat">✕</button></span></div>' +
      '<div class="panel-body"><dl class="kv">' +
      "<dt>Konum</dt><dd>" + esc(where) + "</dd>" +
      "<dt>Sınıf</dt><dd>" + esc(card.classes) + (card.groups ? " · " + esc(card.groups) : "") + "</dd>" +
      "<dt>Öğretmen</dt><dd>" + esc(card.teachers || "–") + "</dd>" +
      "<dt>Derslik</dt><dd>" + esc(card.room || "–") + "</dd>" +
      "<dt>Süre</dt><dd>" + card.length + " saat" + (card.length > 1 ? " (blok)" : "") + "</dd>" +
      "</dl>" +
      (options
        ? '<p class="small muted" style="margin:14px 0 6px">Uygun yer: <b>' + counts.free + "</b> · yer açarak: <b>" + counts.shift + "</b> · uyarılı: <b>" + counts.warn + "</b> · çakışmalı: <b>" + counts.conflict + "</b></p>" +
          whyHtml(why) +
          '<p class="small subtle" style="margin:0 0 14px">Taşımak için yeşil bir hücreye tıklayın ya da kartı sürükleyin. ⇄ işaretli yeşil hücrede oradaki ders yerinden çıkar ve sıradaki taşınacak kart olur.</p>'
        : '<p class="small subtle" style="margin:14px 0">Uygun hücreler hesaplanıyor…</p>') +
      '<div style="display:flex;gap:8px;flex-wrap:wrap">' +
      '<button class="btn btn-sm" data-act="lock">' + (card.locked ? "Kilidi aç" : "Kilitle") + "</button>" +
      (card.day != null && !card.locked ? '<button class="btn btn-sm btn-danger" data-act="unplace">Programdan çıkar</button>' : "") +
      "</div></div>";
    drawer.hidden = false;
    $("#tt-wrap").classList.add("with-drawer");
    applyDrawerMode();
  }

  // Kart paneli: ızgaranın yanına sabit (varsayılan; ızgara daralır, hiçbir gün örtülmez), serbest (sürüklenir,
  // yeri hatırlanır) ya da küçültülmüş (yalnızca başlık). Tercih tarayıcıda saklanır.

  function applyDrawerMode() {
    const docked = !drawer.hidden && drawerMode.dock && !drawerMode.min;
    $("#tt-wrap").classList.toggle("docked", docked);
    drawer.classList.toggle("min", drawerMode.min);
    drawer.classList.toggle("free", !docked);
    if (state.data) fitDensity();
    placeDrawer();
  }

  // Serbest panel seçilen kartın satırını örtmesin: satırın altına, yer yoksa üstüne konur. Kullanıcı sürüklediyse
  // bıraktığı yerde kalır; küçültülmüşse sağ altta durur.
  function placeDrawer() {
    if (drawer.hidden) return;
    if (!drawer.classList.contains("free")) { drawer.style.left = drawer.style.top = drawer.style.bottom = ""; return; }
    if (drawerMode.min) { drawer.style.left = drawer.style.top = ""; drawer.style.bottom = ""; return; }
    if (drawerMode.pos) {
      const w = drawer.offsetWidth, h = drawer.offsetHeight;
      drawer.style.left = Math.min(Math.max(0, drawerMode.pos.x), window.innerWidth - w) + "px";
      drawer.style.top = Math.min(Math.max(0, drawerMode.pos.y), Math.max(0, window.innerHeight - h)) + "px";
      drawer.style.bottom = "auto";
      return;
    }
    drawer.style.left = "";
    const cardNode = state.selected != null && board.querySelector('.tt-card.selected[data-card="' + state.selected + '"]');
    const row = cardNode && cardNode.closest(".tt-row");
    const margin = 8, h = drawer.offsetHeight, vh = window.innerHeight;
    let top;
    if (row) {
      const r = row.getBoundingClientRect();
      top = r.bottom + margin;
      if (top + h > vh - margin) top = r.top - h - margin;  // altta yer yok: satırın üstüne
      if (top < margin) top = Math.min(vh - h - margin, r.bottom + margin);  // ikisi de sığmıyorsa altta kalsın
    } else {
      top = vh - h - margin - ($("#tray-panel")?.offsetHeight || 0);  // bekleyenlerdeki kart: panelin üstü
    }
    drawer.style.top = Math.max(margin, top) + "px";
    drawer.style.bottom = "auto";
  }
  window.addEventListener("resize", placeDrawer);
  window.addEventListener("scroll", placeDrawer, { passive: true });
  $("#tt-scroll").addEventListener("scroll", placeDrawer, { passive: true });

  // ---- işlemler ---------------------------------------------------------------------------
  // İşlemden sonra: yanıtta değişen kartlar varsa yalnızca onlar güncellenir, yoksa tablo yeniden yüklenir.
  async function refresh(result) {
    if (result && applyDelta(result.delta)) {
      if (state.selected && state.cards.has(state.selected)) select(state.selected);
      else clearSelection();
      return;
    }
    await load();
  }

  async function run(promise, keepSelection) {
    let r = null;
    try {
      r = await promise;
      if (r.message) toast(r.message);
    } catch (e) {
      toast(e.message, "error");
    }
    if (!keepSelection) state.selected = null;
    await refresh(r);
  }

  const postMove = (id, day, period, mode) =>
    api(urlFor(cfg.moveUrl, id), { method: "POST", body: JSON.stringify({ day: Number(day), period: Number(period), mode }) });

  // Çakışmada kart doğrudan kaldırılmaz; kullanıcıya ne yapılacağı sorulur.
  const conflictDialog = $("#conflict-dialog");
  function askConflict(info, card, day, period) {
    return new Promise((resolve) => {
      const where = state.data.days[day] + " " + (period + 1) + ". saat";
      $("#conflict-intro").textContent = (card ? card.subject_name + " (" + card.classes + ")" : "Kart") + " → " + where + " şu kartlarla çakışıyor:";
      $("#conflict-items").innerHTML = info.conflicts.map((c) =>
        "<li><b>" + esc(c.lesson) + "</b>" + (c.locked ? ' <span class="pill">kilitli</span>' : "") +
        '<div class="subtle small">' + esc(c.resources.join(" · ")) + "</div></li>").join("");
      $("#conflict-displace").disabled = !info.can_displace;
      $("#conflict-displace").title = info.can_displace ? "" : "Kilitli kart kaldırılamaz";
      $("#conflict-swap").hidden = !info.can_swap;
      conflictDialog.onclose = () => resolve(conflictDialog.returnValue || "cancel");
      conflictDialog.returnValue = "";
      conflictDialog.showModal();
    });
  }

  async function moveCard(id, day, period) {
    if (!cfg.canEdit) { toast("Programı düzenleme yetkiniz yok.", "error"); return; }
    let r = null;
    const option = state.selected === id && state.options ? state.options.get(day + "-" + period) : null;
    if (option && option.status === "shift") {
      // Zincirleme taşıma: oradaki kart(lar) yerinden çıkar, ilki seçilir ve onun uygun yerleri yanar.
      try {
        r = await postMove(id, day, period, "displace");
      } catch (e) { toast(e.message, "error"); return; }
      const next = (r.displaced || [])[0];
      const moved = state.cards.get(next);
      toast(moved ? moved.subject_name + " (" + moved.classes + ") yerinden çıktı: şimdi onu yerleştirin. Bırakmak için Esc."
                  : r.message || "Kart taşındı.");
      state.selected = next || null;
      await refresh(r);
      return;
    }
    try {
      r = await postMove(id, day, period, "ask");
      if (r.message) toast(r.message);
    } catch (e) {
      if (e.status === 409 && e.data && e.data.ask) {
        const choice = await askConflict(e.data, state.cards.get(id), Number(day), Number(period));
        if (choice === "cancel") return;
        return run(postMove(id, day, period, choice));
      }
      toast(e.message, "error");
    }
    state.selected = null;
    await refresh(r);
  }
  const unplaceCard = (id) => run(api(urlFor(cfg.unplaceUrl, id), { method: "POST" }));

  drawer.addEventListener("click", (e) => {
    const act = e.target.closest("[data-act]");
    if (!act || !state.selected) return;
    const id = state.selected;
    if (act.dataset.act === "close") clearSelection();
    if (act.dataset.act === "dock" || act.dataset.act === "min") {
      const key = act.dataset.act;
      drawerMode[key] = !drawerMode[key];
      if (key === "dock" && !drawerMode.dock) drawerMode.pos = null;  // serbest bırakınca yine kartın yanına gelir
      store(key === "dock" ? "tt-drawer-dock" : "tt-drawer-min", drawerMode[key] ? "1" : "0");
      select(id);  // başlıktaki düğmeler yeni duruma göre çizilir
      return;
    }
    if (act.dataset.act === "lock") run(api(urlFor(cfg.lockUrl, id), { method: "POST" }), true);
    if (act.dataset.act === "unplace") unplaceCard(id);
  });

  // Serbest paneli başlığından sürükleme
  drawer.addEventListener("pointerdown", (e) => {
    const head = e.target.closest("[data-drag]");
    if (!head || e.target.closest("button") || !drawer.classList.contains("free") || drawerMode.min) return;
    const r = drawer.getBoundingClientRect(), dx = e.clientX - r.left, dy = e.clientY - r.top;
    head.setPointerCapture(e.pointerId);
    const move = (ev) => {
      drawerMode.pos = { x: ev.clientX - dx, y: ev.clientY - dy };
      placeDrawer();
    };
    const up = () => {
      head.removeEventListener("pointermove", move);
      head.removeEventListener("pointerup", up);
      if (drawerMode.pos) store("tt-drawer-pos", JSON.stringify(drawerMode.pos));
    };
    head.addEventListener("pointermove", move);
    head.addEventListener("pointerup", up);
  });

  function onCardOrCellClick(e) {
    const cardNode = e.target.closest(".tt-card");
    let option = optionAt(cellAt(e.clientX, e.clientY));
    const selected = state.selected;
    // Yer açarak hedef kart: tıklanan nokta değil, kartın üzerindeki "yer açarak" uygun başlangıç kullanılır
    if (selected && cardNode && cardNode.dataset.shiftAt && (!option || option.status === "conflict")) {
      option = state.options.get(cardNode.dataset.shiftAt);
    }
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
  ["input", "change"].forEach((ev) => $("#tray-filters").addEventListener(ev, () => state.data && renderTray()));
  trayCtl.clear.addEventListener("click", () => {
    ["q", "cls", "teacher", "length"].forEach((k) => { trayCtl[k].value = ""; });
    trayCtl.row.checked = false;
    renderTray();
  });
  $("#row-filter").addEventListener("input", () => { if (trayCtl.row.checked && state.data) renderTray(); });
  const trayToggle = $("#tray-toggle");
  const setTrayOpen = (open) => {
    $("#tray-panel").classList.toggle("collapsed", !open);
    trayToggle.setAttribute("aria-expanded", open ? "true" : "false");
    store("tt-tray", open ? "1" : "0");
  };
  trayToggle.addEventListener("click", () => setTrayOpen($("#tray-panel").classList.contains("collapsed")));
  // Tam ekranda tablo, alttaki panelin yüksekliği kadar kısalır; panel hep ekranda kalır.
  if (window.ResizeObserver) {
    new ResizeObserver(() => {
      document.documentElement.style.setProperty("--tray-h", $("#tray-panel").offsetHeight + "px");
    }).observe($("#tray-panel"));
  }
  setTrayOpen(store("tt-tray") !== "0");
  $("#tray").addEventListener("click", (e) => {
    const cardNode = e.target.closest(".tt-card");
    if (cardNode) select(Number(cardNode.dataset.card));
  });

  // Sürükle-bırak
  document.addEventListener("dragstart", (e) => {
    if (state.preview) { e.preventDefault(); return; }
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
    board.className = "tt-board " + state.zoom + (state.view.stripes ? " stripes" : "");
    fitDensity();
  });

  // Kart görünümü menüsü
  document.querySelectorAll("[data-view]").forEach((input) => {
    const key = input.dataset.view;
    if (input.type === "checkbox") input.checked = !!state.view[key];
    else input.value = state.view[key];
    input.addEventListener("change", () => {
      state.view[key] = input.type === "checkbox" ? input.checked : input.value;
      store("tt-view", JSON.stringify(state.view));
      if (state.data) render();
    });
  });

  // Tam ekran
  const focusBtn = $("#btn-focus");
  const setFocus = (on) => {
    document.documentElement.classList.toggle("focus-mode", on);
    focusBtn.textContent = on ? "✕ Tam ekrandan çık" : "⛶ Tam ekran";
    fitDensity();
  };
  focusBtn.addEventListener("click", () => {
    const on = !document.documentElement.classList.contains("focus-mode");
    setFocus(on);
    try {
      if (on && document.documentElement.requestFullscreen) document.documentElement.requestFullscreen().catch(() => {});
      if (!on && document.fullscreenElement) document.exitFullscreen();
    } catch (e) { /* tarayıcı tam ekranı desteklemiyorsa yalnızca menüler gizlenir */ }
  });
  document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement) setFocus(false); });
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

  // İhlalleri çöz: kesin ihlaller en az kartı oynatarak giderilir; süre seçilir (hızlı / az değişiklik).
  const resolveMenu = $("#resolve-menu");
  if (resolveMenu) {
    const resolveBtn = $("#btn-resolve"), label = $("[data-resolve-label]", resolveMenu);
    resolveMenu.addEventListener("click", async (e) => {
      const opt = e.target.closest("[data-resolve]");
      if (!opt) return;
      resolveMenu.classList.remove("open");
      const seconds = Number(opt.dataset.resolve);
      resolveBtn.disabled = true;
      label.innerHTML = '<span class="spinner"></span> İhlaller çözülüyor (~' + seconds + " sn)…";
      await run(api(cfg.resolveUrl, { method: "POST", body: JSON.stringify({ sure: seconds }) }));
      resolveBtn.disabled = false;
      label.textContent = "İhlalleri çöz";
    });
  }

  // ---- sağ tık menüleri (aSc 13.5, 13.7, 13.9) -------------------------------------------
  const ctx = $("#ctx-menu");
  const KIND_ENTITY = { sinif: "Sınıf", ogretmen: "Öğretmen", derslik: "Derslik" };
  function hideMenu() { ctx.hidden = true; ctx.innerHTML = ""; }

  // items: {label, action, disabled, hint, sub: [...], sep, head}
  function buildMenu(items) {
    const ul = el("ul", "ctx-list");
    items.forEach((it) => {
      if (it.sep) { ul.appendChild(el("li", "ctx-sep")); return; }
      if (it.head) { ul.appendChild(el("li", "ctx-head", esc(it.head))); return; }
      const li = el("li", "ctx-item" + (it.disabled ? " disabled" : "") + (it.sub ? " has-sub" : "") + (it.cls ? " " + it.cls : ""),
        "<span>" + esc(it.label) + "</span>" + (it.hint ? '<small>' + esc(it.hint) + "</small>" : "") + (it.sub ? "<b>›</b>" : ""));
      if (it.sub) li.appendChild(buildMenu(it.sub));
      else if (!it.disabled && it.action) li.addEventListener("click", (e) => { e.stopPropagation(); hideMenu(); it.action(); });
      ul.appendChild(li);
    });
    return ul;
  }

  function showMenu(x, y, items) {
    ctx.innerHTML = "";
    ctx.appendChild(buildMenu(items));
    ctx.hidden = false;
    const r = ctx.getBoundingClientRect();
    ctx.style.left = Math.min(x, window.innerWidth - r.width - 8) + "px";
    ctx.style.top = Math.min(y, window.innerHeight - r.height - 8) + "px";
    ctx.classList.toggle("flip", x > window.innerWidth - 2 * r.width - 20);
  }
  document.addEventListener("click", (e) => { if (!ctx.contains(e.target)) hideMenu(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") { hideMenu(); clearFind(); } });
  window.addEventListener("scroll", hideMenu, true);

  // "Bul": ilgili kartları vurgular
  function find(predicate, what) {
    const ids = new Set(state.data.cards.filter(predicate).map((c) => c.id));
    board.classList.add("finding");
    board.querySelectorAll(".tt-card").forEach((n) => n.classList.toggle("found", ids.has(Number(n.dataset.card))));
    toast(ids.size + " kart bulundu: " + what + " (Esc ile kapat)");
  }
  function clearFind() {
    board.classList.remove("finding");
    board.querySelectorAll(".tt-card.found").forEach((n) => n.classList.remove("found"));
  }

  // "Zaman tablosu": ilgili sınıf/öğretmen/dersliğin haftalık programı açılır pencerede
  const viewDialog = $("#view-dialog");
  function showTimetable(kind, id, title) {
    $("#view-title").textContent = title;
    $("#view-body").innerHTML = '<iframe class="view-frame" src="' + cfg.printUrl + "?tur=" + kind + "&id=" + id + '&gomulu=1"></iframe>';
    viewDialog.showModal();
  }
  function showInfo(card, info) {
    $("#view-title").textContent = card.subject_name + " – " + card.classes;
    $("#view-body").innerHTML = info.violations.length
      ? '<ul class="issues">' + info.violations.map((v) => '<li class="hard"><span class="dot"></span>' + esc(v) + "</li>").join("") + "</ul>"
      : '<p class="muted">Bu kartla ilgili kural ihlali yok.</p>';
    viewDialog.showModal();
  }
  function quickChange(card, info) {
    const current = new Set(info.teachers.map((t) => t.id));
    $("#view-title").textContent = "Hızlı değişiklik: " + info.label;
    $("#view-body").innerHTML = '<form id="quick-form"><label class="label">Öğretmen(ler)</label>' +
      '<select class="select" name="teachers" multiple size="10" style="width:100%">' +
      info.all_teachers.map((t) => '<option value="' + t.id + '"' + (current.has(t.id) ? " selected" : "") + ">" + esc(t.name) + "</option>").join("") +
      '</select><p class="subtle small">Ctrl ile birden çok seçin. Değişiklik bu dersin tüm kartlarına uygulanır.</p>' +
      '<div class="dialog-actions"><button class="btn btn-primary">Kaydet</button></div></form>';
    $("#quick-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const teachers = Array.from(e.target.teachers.selectedOptions).map((o) => Number(o.value));
      viewDialog.close();
      run(api(urlFor(cfg.quickUrl, card.id), { method: "POST", body: JSON.stringify({ teachers }) }), true);
    });
    viewDialog.showModal();
  }

  async function cardMenu(card, rowId, x, y) {
    select(card.id);
    showMenu(x, y, [{ head: card.subject + " (" + card.classes + ")" }, { label: "Yükleniyor…", disabled: true }]);
    let info;
    try { info = await api(urlFor(cfg.infoUrl, card.id)); } catch (e) { hideMenu(); toast(e.message, "error"); return; }
    const placed = card.day != null;
    const back = "?back=" + encodeURIComponent(location.pathname);
    const items = [
      { head: card.subject + " (" + card.classes + ")" },
      { label: "Kaldır", hint: "bekleyenlere al", disabled: !placed || card.locked, action: () => unplaceCard(card.id) },
      { label: "Çözüm merkezinde kaydır", hint: "en az değişiklikle", disabled: !placed || card.locked || !cfg.canEdit,
        action: () => { location.href = cfg.solutionUrl + "?tur=shift&kart=" + card.id; } },
      { label: card.locked ? "Kilidi aç" : "Kartı kilitle", action: () => run(api(urlFor(cfg.lockUrl, card.id), { method: "POST" }), true) },
      { label: "Bilgi", hint: info.violations.length ? info.violations.length + " ihlal" : "ihlal yok", action: () => showInfo(card, info) },
    ];
    if (rowId != null && placed) items.push({ label: "Satırı temizle", hint: "kilitsiz kartlar", action: () => rowAction(rowId, "clear") });
    items.push({ sep: true });
    if (placed) {
      items.push({
        label: "Derslik", sub: info.rooms.map((r) => ({
          label: (r.current ? "✓ " : r.occupied.length ? "✕ " : "   ") + r.name,
          hint: r.occupied.length ? "dolu: " + r.occupied[0] : "",
          disabled: r.current,
          action: () => run(api(urlFor(cfg.roomUrl, card.id), { method: "POST", body: JSON.stringify({ room: r.id }) }), true),
        })).concat([{ sep: true }, { label: "Dersliği boşalt", disabled: !card.room, action: () => run(api(urlFor(cfg.roomUrl, card.id), { method: "POST", body: JSON.stringify({ room: null }) }), true) }]),
      });
    }
    items.push({ label: "Dersi güncelle", action: () => { location.href = info.lesson_url + back; } });
    items.push({ label: "Hızlı değişiklik yap", hint: "öğretmen", action: () => quickChange(card, info) });
    items.push({ sep: true });
    items.push({
      label: "Bul", sub: [
        { label: "Bu dersin kartları", action: () => find((c) => c.lesson_id === card.lesson_id, info.label) },
        { label: "Ders adı: " + info.subject.name, action: () => find((c) => c.subject_id === info.subject.id, info.subject.name) },
      ].concat(info.teachers.map((t) => ({ label: "Öğretmen: " + t.name, action: () => find((c) => c.teacher_ids.includes(t.id), t.name) })))
        .concat(info.classes.map((k) => ({ label: "Sınıf: " + k.name, action: () => find((c) => c.class_ids.includes(k.id), k.name) }))),
    });
    items.push({
      label: "Zaman tablosu", sub: info.classes.map((k) => ({ label: "✓ " + k.name, action: () => showTimetable("sinif", k.id, k.name) }))
        .concat(info.teachers.map((t) => ({ label: "✓ " + t.name, action: () => showTimetable("ogretmen", t.id, t.name) })))
        .concat(info.rooms.filter((r) => r.current).map((r) => ({ label: "✓ " + r.name, action: () => showTimetable("derslik", r.id, r.name) }))),
    });
    items.push({
      label: "Düzenle / müsaitlik", sub: [{ label: "Ders adı: " + info.subject.name, action: () => { location.href = info.subject.url; } }]
        .concat(info.teachers.map((t) => ({ label: "Öğretmen: " + t.name, action: () => { location.href = t.url; } })))
        .concat(info.classes.map((k) => ({ label: "Sınıf: " + k.name, action: () => { location.href = k.url; } }))),
    });
    if (ctx.hidden) return; // kullanıcı bu arada kapattıysa
    showMenu(x, y, items);
  }

  const rowAction = (rowId, action) =>
    run(api(cfg.rowUrl, { method: "POST", body: JSON.stringify({ kind: state.kind, row: rowId, action }) }));

  function rowMenu(rowId, x, y) {
    const row = state.data.rows.find((r) => String(r.id) === String(rowId));
    if (!row) return;
    const param = state.kind === "sinif" ? "sinif" : state.kind === "ogretmen" ? "ogretmen" : null;
    showMenu(x, y, [
      { head: KIND_ENTITY[state.kind] + ": " + row.label },
      { label: "Zaman tablosu", action: () => showTimetable(state.kind, row.id, row.label) },
      { label: "Bilgileri / müsaitliği düzenle", action: () => { location.href = urlFor(cfg.entityUrl[state.kind], row.id); } },
      { label: "Dersleri", disabled: !param, action: () => { location.href = cfg.lessonsUrl + "?" + param + "=" + row.id; } },
      { sep: true },
      { label: "Satırı temizle", hint: "kilitsiz kartlar bekleyenlere", action: () => { if (confirm(row.label + " satırındaki kilitsiz kartlar kaldırılsın mı?")) rowAction(row.id, "clear"); } },
      { label: "Satırı kilitle", action: () => rowAction(row.id, "lock") },
      { label: "Satırın kilitlerini aç", action: () => rowAction(row.id, "unlock") },
      { sep: true },
      { label: "Yazdır", action: () => window.open(cfg.printUrl + "?tur=" + state.kind + "&id=" + row.id, "_blank") },
    ]);
  }

  async function cellMenu(rowId, day, period, x, y) {
    showMenu(x, y, [{ head: state.data.days[day] + " " + (period + 1) + ". saat" }, { label: "Yükleniyor…", disabled: true }]);
    let res;
    try {
      res = await api(cfg.cellUrl + "?tur=" + state.kind + "&satir=" + rowId + "&gun=" + day + "&saat=" + period);
    } catch (e) { hideMenu(); toast(e.message, "error"); return; }
    if (ctx.hidden) return;
    const items = [{ head: state.data.days[day] + " " + (period + 1) + ". saat – buraya konabilecek kartlar" }];
    if (!res.cards.length) items.push({ label: "Bu satırda buraya konabilecek bekleyen kart yok", disabled: true });
    res.cards.forEach((c) => items.push({
      label: c.lesson + (c.length > 1 ? " (" + c.length + " saat)" : ""),
      hint: c.status === "free" ? "uygun" : c.status === "warn" ? "uyarılı" : c.status === "shift" ? "yer açar" : "çakışma",
      cls: "st-" + c.status,
      action: () => moveCard(c.card, day, period),
    }));
    showMenu(x, y, items);
  }

  function onContext(e) {
    if (state.preview) { e.preventDefault(); return; }
    const cardNode = e.target.closest(".tt-card");
    const labelNode = e.target.closest(".tt-label");
    const rowNode = e.target.closest(".tt-row");
    if (cardNode) {
      e.preventDefault();
      const card = state.cards.get(Number(cardNode.dataset.card));
      if (card) cardMenu(card, rowNode ? rowNode.dataset.row : null, e.clientX, e.clientY);
      return;
    }
    if (labelNode) { e.preventDefault(); rowMenu(labelNode.dataset.row, e.clientX, e.clientY); return; }
    const cell = cellAt(e.clientX, e.clientY);
    if (cell && rowNode) { e.preventDefault(); cellMenu(rowNode.dataset.row, Number(cell.dataset.day), Number(cell.dataset.period), e.clientX, e.clientY); }
  }
  board.addEventListener("contextmenu", onContext);
  $("#tray").addEventListener("contextmenu", onContext);

  // Önizleme: ?onizleme=N ile açılır; önceki/sonraki öneri arasında gezilir.
  const previewParam = new URLSearchParams(location.search).get("onizleme");
  if (previewParam !== null && cfg.previewUrl) {
    $("#pv-prev").addEventListener("click", () => startPreview(state.preview.index - 1));
    $("#pv-next").addEventListener("click", () => startPreview(state.preview.index + 1));
    $("#pv-only").addEventListener("change", drawPreview);
    window.addEventListener("resize", () => { if (state.preview) drawPreview(); });
    startPreview(Number(previewParam) || 0);
  } else {
    const search = new URLSearchParams(location.search).get("ara");
    if (search) $("#row-filter").value = search;
    load();
  }
})();
