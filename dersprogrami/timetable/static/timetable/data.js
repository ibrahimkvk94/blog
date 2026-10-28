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

  // ---- sade seçici: seçenek çoksa yalnızca seçilenler görünür, eklemek için yazılır ---------
  // Kutunun kendi listesi (onay kutuları) aynen kalır; "Tümünü göster" ile açılabilir.
  const COMPACT_AFTER = 12;
  function compactChips(box) {
    const opts = $$(".chip-opt", box);
    const search = $(".chip-search", box);
    const list = $(".chip-list", box);
    if (opts.length <= COMPACT_AFTER || !search || !list) return;
    box.classList.add("compact");
    const picked = document.createElement("div");
    picked.className = "chip-picked";
    const drop = document.createElement("div");
    drop.className = "chip-drop";
    drop.hidden = true;
    const more = document.createElement("button");
    more.type = "button";
    more.className = "btn btn-ghost btn-sm chip-more";
    box.insertBefore(picked, search);
    search.after(drop);
    box.appendChild(more);
    search.placeholder = "Eklemek için yazın…";
    list.hidden = true;
    let items = [], active = 0;
    const input = (o) => o.querySelector("input");
    const label = (o) => o.querySelector("span").textContent;
    const setMore = () => { more.textContent = list.hidden ? "Tümünü göster (" + opts.length + ")" : "Listeyi gizle"; };
    setMore();
    more.addEventListener("click", () => { list.hidden = !list.hidden; setMore(); });

    const renderPicked = () => {
      const on = opts.filter((o) => input(o).checked);
      picked.innerHTML = on.length
        ? on.map((o) => '<span class="chip-pick">' + esc(label(o)) + '<button type="button" data-v="' + esc(input(o).value) + '" aria-label="Kaldır">×</button></span>').join("")
        : '<span class="subtle small">Seçilmedi</span>';
    };
    const set = (o, checked) => {
      input(o).checked = checked;
      input(o).dispatchEvent(new Event("change", { bubbles: true }));
    };
    const renderDrop = () => {
      const q = search.value.trim().toLocaleLowerCase("tr");
      const rank = box._rank;
      let pool = opts.filter((o) => !input(o).checked && !o.hidden && (!q || o.dataset.label.includes(q)));
      let ranked = pool.map((o) => ({ o, r: rank ? rank(input(o).value) : { score: 0, note: "" } }));
      if (!q) ranked = ranked.filter((x) => x.r.score > 0);  // boş aramada yalnızca öneriler
      ranked.sort((a, b) => b.r.score - a.r.score);
      items = ranked.slice(0, 12);
      active = 0;
      if (!items.length) {
        drop.style.top = search.offsetTop + search.offsetHeight + "px";
        drop.innerHTML = q ? '<div class="chip-drop-empty">Eşleşen yok.</div>' : "";
        drop.hidden = !q;
        return;
      }
      drop.style.top = search.offsetTop + search.offsetHeight + "px";
      drop.innerHTML = (q ? "" : '<div class="chip-drop-head">Öneriler</div>') + items.map((x, i) =>
        '<div class="chip-drop-item' + (i === 0 ? " on" : "") + '" data-i="' + i + '"><span>' + esc(label(x.o)) + "</span>" +
        (x.r.note ? '<small>' + esc(x.r.note) + "</small>" : "") + "</div>").join("") +
        (q && pool.length > items.length ? '<div class="chip-drop-empty">' + (pool.length - items.length) + " sonuç daha; aramayı daraltın.</div>" : "");
      drop.hidden = false;
    };
    const choose = (i) => {
      const x = items[i];
      if (!x) return;
      set(x.o, true);
      search.value = "";
      renderDrop();
      search.focus();
    };
    box._refresh = () => { renderPicked(); if (!drop.hidden) renderDrop(); };
    box.addEventListener("change", renderPicked);
    picked.addEventListener("click", (e) => {
      const b = e.target.closest("button[data-v]");
      if (!b) return;
      const o = opts.find((x) => input(x).value === b.dataset.v);
      if (o) set(o, false);
    });
    search.addEventListener("focus", renderDrop);
    search.addEventListener("input", renderDrop);
    search.addEventListener("blur", () => setTimeout(() => { drop.hidden = true; }, 150));
    search.addEventListener("keydown", (e) => {
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        if (!items.length) return;
        active = (active + (e.key === "ArrowDown" ? 1 : items.length - 1)) % items.length;
        $$(".chip-drop-item", drop).forEach((el, i) => el.classList.toggle("on", i === active));
      } else if (e.key === "Enter") {
        e.preventDefault();
        choose(active);
      } else if (e.key === "Escape") {
        drop.hidden = true;
      } else if (e.key === "Backspace" && !search.value) {
        const on = opts.filter((o) => input(o).checked);
        if (on.length) set(on[on.length - 1], false);
      }
    });
    drop.addEventListener("mousedown", (e) => {
      const el = e.target.closest(".chip-drop-item");
      if (el) { e.preventDefault(); choose(Number(el.dataset.i)); }
    });
    renderPicked();
  }
  $$("[data-chips]").forEach(compactChips);

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

    // Öğretmen önerisi: bu ders adını zaten okutanlar, sonra branşı uyanlar; yanında haftalık yük
    const hints = readJSON("teacher-hints");
    const teacherBox = $("input[name=teachers]", lessonForm)?.closest("[data-chips]");
    const subjectSel = $("select[name=subject]", lessonForm);
    if (hints && teacherBox && subjectSel) {
      teacherBox._rank = (id) => {
        const sid = subjectSel.value;
        const teaching = (hints.teaching[sid] || []).includes(Number(id));
        const branch = (hints.branch[sid] || []).includes(Number(id));
        const load = (hints.loads[id] || 0) + " saat";
        return { score: teaching ? 2 : branch ? 1 : 0, note: (teaching ? "bu dersi okutuyor · " : branch ? "branşı · " : "") + load };
      };
    }

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
  if (!select || select.closest("[data-rel-editor]")) return;  // yeni düzenleyici: relationship.js
  const row = (name) => document.querySelector("[name=" + name + "]")?.closest(".form-row");
  const list = (key) => (select.dataset[key] || "").split(" ");
  const help = JSON.parse(select.dataset.help);
  const usesN = list("usesN"), usesMap = list("usesMap"), needsMap = list("needsMap");
  const paired = list("paired"), twoSided = list("twoSided"), rooms = list("rooms");
  const student = list("student"), softTarget = list("softTarget");
  const note = document.createElement("div");
  note.className = "condition-help";
  select.closest(".form-row").appendChild(note);
  // Koşul arama: aSc numarası ya da sözcükle süz (ör. "#30", "boş saat").
  const search = document.createElement("input");
  search.type = "search";
  search.className = "input input-sm condition-search";
  search.placeholder = "Koşul ara: sözcük ya da aSc numarası (ör. #30)";
  select.parentNode.insertBefore(search, select);
  const norm = (t) => t.toLocaleLowerCase("tr");
  search.addEventListener("input", () => {
    const q = norm(search.value.trim());
    let first = null;
    select.querySelectorAll("option").forEach((o) => {
      const hit = !q || norm(o.textContent).includes(q);
      o.hidden = !hit;
      if (hit && !first) first = o;
    });
    select.querySelectorAll("optgroup").forEach((g) => { g.hidden = ![...g.children].some((o) => !o.hidden); });
    if (q && first && select.selectedOptions[0]?.hidden) { select.value = first.value; update(); }
  });

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
    show("param_max", softTarget.includes(c));
    show("apply_to", !paired.includes(c) && !student.includes(c));
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

/* Kayıt seçici: arama, küme seçimi, tümü/hiçbiri ve seçili sayısı. */
(function () {
  "use strict";
  document.querySelectorAll("[data-target-picker]").forEach((box) => {
    const items = [...box.querySelectorAll(".tp-item")];
    items.forEach((i) => { i.dataset.name = i.textContent.trim().toLocaleLowerCase("tr"); });
    const count = box.querySelector("[data-tp-count]");
    const summary = box.closest("details")?.querySelector("[data-copy-summary]");
    const update = () => {
      const n = items.filter((i) => i.querySelector("input").checked).length;
      count.textContent = n + " seçili";
      if (summary) { summary.hidden = !n; summary.textContent = n + " seçili"; }
    };
    const visible = () => items.filter((i) => !i.hidden);
    box.querySelector("[data-tp-search]").addEventListener("input", (e) => {
      const q = e.target.value.trim().toLocaleLowerCase("tr");
      items.forEach((i) => { i.hidden = q && !i.dataset.name.includes(q); });
    });
    const group = box.querySelector("[data-tp-group]");
    if (group) group.addEventListener("change", () => {
      items.forEach((i) => { if (i.dataset.group === group.value) i.querySelector("input").checked = true; });
      group.value = "";
      update();
    });
    box.querySelector("[data-tp-all]").addEventListener("click", () => { visible().forEach((i) => { i.querySelector("input").checked = true; }); update(); });
    box.querySelector("[data-tp-none]").addEventListener("click", () => { items.forEach((i) => { i.querySelector("input").checked = false; }); update(); });
    box.addEventListener("change", update);
    update();
  });
})();
