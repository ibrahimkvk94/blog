/* Veri giriş ekranları: çip seçimi, müsaitlik ızgarası, bölünme düzenleyici, ders saatleri,
 * sınıf ders tablosu ve silme onayı. */
(function () {
  "use strict";
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const readJSON = (id) => { const el = document.getElementById(id); return el ? JSON.parse(el.textContent) : null; };

  // ---- silme onayı ------------------------------------------------------------------------
  $$("form[data-confirm]").forEach((form) => {
    form.addEventListener("submit", (e) => { if (!window.confirm(form.dataset.confirm)) e.preventDefault(); });
  });

  // ---- çip seçimi -------------------------------------------------------------------------
  function syncChip(label) {
    label.classList.toggle("on", label.querySelector("input").checked);
  }
  $$("[data-chips]").forEach((box) => {
    $$(".chip-opt", box).forEach(syncChip);
    box.addEventListener("change", (e) => { const l = e.target.closest(".chip-opt"); if (l) syncChip(l); });
    const search = $(".chip-search", box);
    if (search) {
      search.addEventListener("input", () => {
        const q = search.value.trim().toLocaleLowerCase("tr");
        $$(".chip-opt", box).forEach((l) => { l.classList.toggle("filtered", !!q && !l.dataset.label.includes(q)); });
      });
      search.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
    }
  });

  // ---- ders formu: grupları seçili sınıflara göre süz, kart önizlemesi ---------------------
  const lessonForm = $("#lesson-form");
  if (lessonForm) {
    const classBox = $("input[name=classes]", lessonForm)?.closest("[data-chips]");
    const groupWrap = $("[data-groups-field]", lessonForm);
    const filterGroups = () => {
      const selected = new Set($$("input[name=classes]:checked", lessonForm).map((i) => i.value));
      let visible = 0;
      $$(".chip-opt[data-class]", groupWrap).forEach((l) => {
        const show = selected.has(l.dataset.class);
        l.hidden = !show;
        if (!show && l.querySelector("input").checked) { l.querySelector("input").checked = false; syncChip(l); }
        if (show) visible++;
      });
      groupWrap.hidden = visible === 0;
    };
    if (classBox && groupWrap) { classBox.addEventListener("change", filterGroups); filterGroups(); }

    const preview = $("[data-card-preview]", lessonForm);
    const hours = $("input[name=periods_per_week]", lessonForm);
    const length = $("select[name=card_length]", lessonForm);
    const split = $("input[name=split]", lessonForm);
    const parseSplit = (text) => {
      text = (text || "").trim();
      if (!text) return [];
      const parts = /^\d+$/.test(text) ? text.split("") : text.split(/[+, ]+/).filter(Boolean);
      const values = parts.map(Number);
      return values.every((v) => Number.isInteger(v) && v > 0) ? values : [];
    };
    const renderPreview = () => {
      const h = Math.max(0, parseInt(hours.value || "0", 10));
      const l = Math.max(1, parseInt(length.value || "1", 10));
      let parts = parseSplit(split && split.value);
      let note = "";
      if (parts.length && parts.reduce((a, b) => a + b, 0) !== h) {
        note = ' <span class="error small">Dağılım toplamı haftalık saate eşit değil.</span>';
        parts = [];
      }
      if (!parts.length) {
        for (let i = 0; i < Math.floor(h / l); i++) parts.push(l);
        for (let i = 0; i < h % l; i++) parts.push(1);
      }
      parts.sort((a, b) => b - a);
      preview.innerHTML = parts.length
        ? '<span class="subtle small">Kartlar:</span> ' + parts.map((n) => '<span class="mini-card" style="width:' + (18 * n + 6 * (n - 1)) + 'px">' + n + "</span>").join("") + note
        : note;
    };
    if (preview && hours && length) {
      hours.addEventListener("input", renderPreview);
      length.addEventListener("change", renderPreview);
      if (split) split.addEventListener("input", renderPreview);
      renderPreview();
    }
  }

  // ---- müsaitlik ızgarası ------------------------------------------------------------------
  const availBox = $("[data-availability]");
  if (availBox) {
    const data = readJSON("availability-data");
    const states = Object.assign({}, data.states);
    const input = $("input[name=availability]", availBox);
    const grid = $(".avail-grid", availBox);
    const NEXT = { "": "no", no: "maybe", maybe: "" };
    const save = () => { input.value = JSON.stringify(states); };
    const paint = () => {
      $$(".av-cell", grid).forEach((c) => {
        const s = states[c.dataset.key] || "";
        c.className = "av-cell" + (s ? " av-" + s : "");
        c.textContent = s === "no" ? "✕" : s === "maybe" ? "?" : "";
        c.setAttribute("aria-label", c.dataset.label + ": " + (s === "no" ? "yasak" : s === "maybe" ? "koşullu" : "uygun"));
      });
      save();
    };
    const setMany = (keys) => {
      const allNo = keys.every((k) => states[k] === "no");
      keys.forEach((k) => { if (allNo) delete states[k]; else states[k] = "no"; });
      paint();
    };
    let html = '<table class="avail-table"><thead><tr><th></th>';
    data.periods.forEach((p, j) => { html += '<th><button type="button" class="av-head" data-period="' + j + '">' + (j + 1) + "<small>" + esc(p.start) + "</small></button></th>"; });
    html += "</tr></thead><tbody>";
    data.days.forEach((day, d) => {
      html += '<tr><th><button type="button" class="av-head av-day" data-day="' + d + '">' + esc(day) + "</button></th>";
      data.periods.forEach((p, j) => { html += '<td><button type="button" class="av-cell" data-key="' + d + "-" + j + '" data-label="' + esc(day) + " " + (j + 1) + '. saat"></button></td>'; });
      html += "</tr>";
    });
    html += "</tbody></table>";
    grid.innerHTML = html;
    grid.addEventListener("click", (e) => {
      const cell = e.target.closest(".av-cell");
      if (cell) {
        const next = NEXT[states[cell.dataset.key] || ""];
        if (next) states[cell.dataset.key] = next; else delete states[cell.dataset.key];
        paint();
        return;
      }
      const head = e.target.closest(".av-head");
      if (!head) return;
      if (head.dataset.day != null) setMany(data.periods.map((_, j) => head.dataset.day + "-" + j));
      else setMany(data.days.map((_, d) => d + "-" + head.dataset.period));
    });
    paint();
  }

  // ---- bölünme düzenleyici -----------------------------------------------------------------
  const divBox = $("[data-divisions]");
  if (divBox) {
    const rows = readJSON("divisions-data") || [];
    const input = $("input[name=divisions]", divBox);
    const list = $(".division-list", divBox);
    const serialize = () => {
      const out = $$(".division-row", list).map((row) => {
        const known = JSON.parse(row.dataset.groups || "[]");
        const names = $("[data-groups]", row).value.split(",").map((s) => s.trim()).filter(Boolean);
        return {
          id: row.dataset.id ? Number(row.dataset.id) : null,
          name: $("[data-name]", row).value.trim(),
          groups: names.map((n) => ({ id: (known.find((g) => g.name === n) || {}).id || null, name: n })),
        };
      });
      input.value = JSON.stringify(out);
    };
    const addRow = (div) => {
      const row = document.createElement("div");
      row.className = "division-row";
      row.dataset.id = div.id || "";
      row.dataset.groups = JSON.stringify(div.groups || []);
      row.innerHTML =
        '<input class="input" data-name placeholder="Bölünme adı (ör. Yabancı dil 2)" value="' + esc(div.name || "") + '" aria-label="Bölünme adı">' +
        '<input class="input" data-groups placeholder="Gruplar, virgülle (ör. Almanca, Fransızca)" value="' + esc((div.groups || []).map((g) => g.name).join(", ")) + '" aria-label="Gruplar">' +
        '<button type="button" class="btn btn-sm btn-danger" data-remove>Kaldır</button>';
      list.appendChild(row);
    };
    rows.forEach(addRow);
    if (!rows.length) list.innerHTML = "";
    $("[data-add-division]").addEventListener("click", () => { addRow({}); serialize(); });
    list.addEventListener("click", (e) => { if (e.target.closest("[data-remove]")) { e.target.closest(".division-row").remove(); serialize(); } });
    list.addEventListener("input", serialize);
    serialize();
    divBox.closest("form").addEventListener("submit", serialize);
  }

  // ---- ders saatleri: satır ekle -----------------------------------------------------------
  const addPeriod = $("[data-add-period]");
  if (addPeriod) {
    addPeriod.addEventListener("click", () => {
      const total = $("#id_periods-TOTAL_FORMS");
      const index = Number(total.value);
      const tpl = $("#period-template").innerHTML.replace(/__prefix__/g, index);
      $("[data-period-rows]").insertAdjacentHTML("beforeend", tpl);
      total.value = index + 1;
    });
  }

  // ---- sınıf ders tablosu: toplam ve kopyalama ----------------------------------------------
  const quick = $("#class-lessons");
  if (quick) {
    const capacity = Number(quick.dataset.capacity);
    const other = Number(quick.dataset.otherHours || 0);
    const total = () => {
      let sum = other;
      $$("[data-hours]", quick).forEach((i) => {
        const n = parseInt(i.value || "0", 10) || 0;
        sum += n;
        i.closest("tr").classList.toggle("has-hours", n > 0);
      });
      $("[data-total]").textContent = sum;
      $("[data-total-pill]").className = "pill " + (sum > capacity ? "failed" : sum === capacity ? "ok" : "");
    };
    quick.addEventListener("input", total);
    total();
    const copy = $("[data-copy-from]", quick);
    const source = readJSON("copy-source") || {};
    if (copy) {
      copy.addEventListener("change", () => {
        const lessons = source[copy.value] || {};
        $$("tr[data-subject]", quick).forEach((tr) => {
          const item = lessons[tr.dataset.subject];
          $("[data-hours]", tr).value = item ? item[0] : "";
          $("[data-length]", tr).value = item ? String(item[1]) : "1";
        });
        total();
        copy.value = "";
      });
    }
  }
})();

/* Kart ilişkisi formu: koşula göre ilgili alanları göster, koşulun açıklamasını yaz,
   zaman haritalarını (işaretli gün×saat hücreleri) düzenle. */
(function () {
  "use strict";
  const select = document.querySelector("select[name=condition][data-help]");
  if (!select) return;
  const row = (name) => document.querySelector("[name=" + name + "]")?.closest(".form-row");
  const list = (key) => (select.dataset[key] || "").split(" ");
  const help = JSON.parse(select.dataset.help);
  const usesN = list("usesN"), usesMap = list("usesMap"), needsMap = list("needsMap");
  const paired = list("paired"), twoSided = list("twoSided"), rooms = list("rooms");
  const note = document.createElement("div");
  note.className = "condition-help";
  select.closest(".form-row").appendChild(note);

  // ---- zaman haritası ızgaraları
  const metaNode = document.getElementById("time-map-meta");
  const meta = metaNode ? JSON.parse(metaNode.textContent) : { days: [], periods: [] };
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  document.querySelectorAll("[data-time-map]").forEach((box) => {
    const input = box.querySelector("input[type=hidden]");
    const grid = box.querySelector(".avail-grid");
    let cells;
    try { cells = new Set(JSON.parse(input.value || "[]")); } catch (e) { cells = new Set(); }
    const save = () => { input.value = JSON.stringify([...cells]); };
    const paint = () => {
      grid.querySelectorAll(".av-cell").forEach((c) => {
        const on = cells.has(c.dataset.key);
        c.className = "av-cell map-cell" + (on ? " map-on" : "");
        c.textContent = on ? "✓" : "";
        c.setAttribute("aria-pressed", on ? "true" : "false");
      });
      save();
    };
    const toggleMany = (keys) => {
      const all = keys.every((k) => cells.has(k));
      keys.forEach((k) => (all ? cells.delete(k) : cells.add(k)));
      paint();
    };
    let html = '<table class="avail-table"><thead><tr><th></th>';
    meta.periods.forEach((p, j) => { html += '<th><button type="button" class="av-head" data-period="' + j + '">' + (j + 1) + "<small>" + esc(p.start) + "</small></button></th>"; });
    html += "</tr></thead><tbody>";
    meta.days.forEach((day, d) => {
      html += '<tr><th><button type="button" class="av-head av-day" data-day="' + d + '">' + esc(day) + "</button></th>";
      meta.periods.forEach((p, j) => { html += '<td><button type="button" class="av-cell" data-key="' + d + "-" + j + '" aria-label="' + esc(day) + " " + (j + 1) + '. saat"></button></td>'; });
      html += "</tr>";
    });
    grid.innerHTML = html + "</tbody></table>";
    grid.addEventListener("click", (e) => {
      const cell = e.target.closest(".av-cell");
      if (cell) { const k = cell.dataset.key; cells.has(k) ? cells.delete(k) : cells.add(k); paint(); return; }
      const head = e.target.closest(".av-head");
      if (!head) return;
      if (head.dataset.day != null) toggleMany(meta.periods.map((_, j) => head.dataset.day + "-" + j));
      else toggleMany(meta.days.map((_, d) => d + "-" + head.dataset.period));
    });
    paint();
  });

  const update = () => {
    const c = select.value;
    note.textContent = help[c] || "";
    const show = (name, on) => { const r = row(name); if (r) r.hidden = !on; };
    const mapRow = (name, on) => { const r = document.querySelector('[data-map-row="' + name + '"]'); if (r) r.hidden = !on; };
    show("param", usesN.includes(c));
    show("apply_to", !paired.includes(c));
    show("subjects_b", twoSided.includes(c));
    show("lessons_b", twoSided.includes(c));
    show("classrooms", rooms.includes(c));
    mapRow("time_map", usesMap.includes(c));
    mapRow("time_map_b", twoSided.includes(c) && usesMap.includes(c));
    const label = document.querySelector('[data-map-row="time_map"] .label');
    if (label) label.innerHTML = "Zaman haritası" + (needsMap.includes(c) ? ' <span class="req">*</span>' : ' <span class="subtle small">(boş = tüm saatler)</span>');
    const lessons = row("lessons");
    if (lessons) lessons.classList.toggle("emphasis", paired.includes(c));
  };
  select.addEventListener("change", update);
  update();
})();
