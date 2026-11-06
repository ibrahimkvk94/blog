/* Kart ilişkisi düzenleyicisi (aSc düzeni): koşul, uygula, filtre (gruplu seçici pencereleri),
 * zaman haritası ve önem. Seçimler formdaki gizli alanlara yazılır; kaydetme editor.js'tedir. */
(function () {
  "use strict";
  const form = document.querySelector("[data-rel-editor]");
  if (!form) return;
  const $ = (sel, root) => (root || document).querySelector(sel);
  const $$ = (sel, root) => Array.from((root || document).querySelectorAll(sel));
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const norm = (t) => String(t || "").toLocaleLowerCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i");
  const data = JSON.parse($("#rel-data").textContent);
  const select = $("select[name=condition]", form);
  const list = (key) => (select.dataset[key] || "").split(" ");
  const help = JSON.parse(select.dataset.help || "{}");
  const sets = {
    n: list("usesN"), map: list("usesMap"), needsMap: list("needsMap"), paired: list("paired"),
    two: list("twoSided"), rooms: list("rooms"), student: list("student"), soft: list("softTarget"),
  };

  // ---- dizinler -------------------------------------------------------------------------------
  const subjects = new Map(data.subjects.map((s) => [s.id, s]));
  const lessons = new Map();
  data.subjects.forEach((s) => s.lessons.forEach((l) => lessons.set(l.id, Object.assign({ subject: s }, l))));
  const plain = { classes: data.classes, teachers: data.teachers, classrooms: data.rooms };
  const byId = {};
  Object.entries(plain).forEach(([k, rows]) => { byId[k] = new Map(rows.map((r) => [r.id, r])); });
  const kindBadge = (s) => s.kind === "U" ? '<span class="rel-kind u">Uygulama</span>' : s.kind === "T" ? '<span class="rel-kind t">Teori</span>' : "";
  const subjectLabel = (s) => (s.code ? s.code + " · " : "") + s.name;

  // ---- gizli değerler ---------------------------------------------------------------------------
  const values = (name) => $$('[data-rel-values="' + name + '"] input', form).map((i) => Number(i.value));
  function setValues(name, ids) {
    const box = $('[data-rel-values="' + name + '"]', form);
    box.innerHTML = ids.map((id) => '<input type="hidden" name="' + name + '" value="' + id + '">').join("");
  }
  const changed = () => form.dispatchEvent(new Event("change", { bubbles: true }));

  // ---- seçim özetleri (çipler) -------------------------------------------------------------------
  const MAX_CHIPS = 8;
  function chips(items, empty) {
    if (!items.length) return '<span class="rel-empty">' + esc(empty) + "</span>";
    const shown = items.slice(0, MAX_CHIPS).map((h) => '<span class="rel-chip">' + h + "</span>").join("");
    return shown + (items.length > MAX_CHIPS ? '<span class="rel-chip more">+' + (items.length - MAX_CHIPS) + "</span>" : "");
  }
  function lessonChips(side) {
    const sfx = side === "b" ? "_b" : "";
    const items = values("subjects" + sfx).map((id) => subjects.get(id)).filter(Boolean)
      .map((s) => "<b>" + esc(s.code || s.name) + "</b> " + esc(s.code ? s.name : "") + " " + kindBadge(s) + ' <small>tüm kısımlar</small>');
    values("lessons" + sfx).map((id) => lessons.get(id)).filter(Boolean)
      .forEach((l) => items.push("<b>" + esc(l.subject.code || l.subject.name) + "</b> " + kindBadge(l.subject) + " <small>" + esc(l.classes) + "</small>"));
    return items;
  }
  function renderChips() {
    $('[data-rel-chips="lessons"]').innerHTML = chips(lessonChips("a"), "Tüm dersler");
    $('[data-rel-chips="lessons_b"]').innerHTML = chips(lessonChips("b"), "Seçilmedi");
    [["classes", "Tüm sınıflar"], ["teachers", "Tüm öğretmenler"], ["classrooms", "Seçilmedi"]].forEach(([k, empty]) => {
      $('[data-rel-chips="' + k + '"]').innerHTML = chips(values(k).map((id) => byId[k].get(id)).filter(Boolean).map((r) => esc(r.name)), empty);
    });
    renderSummary();
  }

  // ---- koşul: arama, açıklama, görünürlük ------------------------------------------------------------
  const helpBox = $("[data-rel-help]");
  const search = $("[data-rel-condition-search]");
  search.addEventListener("input", () => {
    const q = norm(search.value.trim());
    let first = null;
    $$("option", select).forEach((o) => { const hit = !q || norm(o.textContent).includes(q); o.hidden = !hit; if (hit && !first) first = o; });
    $$("optgroup", select).forEach((g) => { g.hidden = ![...g.children].some((o) => !o.hidden); });
    if (q && first && select.selectedOptions[0] && select.selectedOptions[0].hidden) { select.value = first.value; update(); }
  });
  function update() {
    const c = select.value;
    helpBox.textContent = help[c] || "";
    const show = { n: sets.n.includes(c), soft: sets.soft.includes(c), apply: !sets.paired.includes(c) && !sets.student.includes(c),
      two: sets.two.includes(c), rooms: sets.rooms.includes(c), map: sets.map.includes(c), "map-b": sets.two.includes(c) && sets.map.includes(c) };
    $$("[data-rel-show]", form).forEach((el) => { el.hidden = !show[el.dataset.relShow]; });
    $("[data-rel-side-a]").textContent = show.two ? "Değiştir: Dersler A" : "Değiştir: Dersler";
    $("[data-rel-map-label]").innerHTML = "Zaman haritası" + (sets.needsMap.includes(c) ? ' <span class="req">*</span>' : ' <span class="subtle small">(boş = tüm saatler)</span>');
    $("[data-rel-filter-help]").textContent = sets.paired.includes(c)
      ? "Bu koşul seçilen dersleri her kısımda eşleştirir: iki ders ya da ders adı seçin (ör. TBE201 ve SBE201). Sınıf ya da öğretmen seçmezseniz o derslerin okutulduğu bütün kısımlara uygulanır; listede ilk görünen ders önce gelir."
      : "Seçilen ders kendi ders adını temsil eder: sınıf ya da öğretmen seçmezseniz kural o dersin okutulduğu bütün kısımlara uygulanır; seçerseniz yalnızca onlarla sınırlanır.";
    renderSummary();
  }
  select.addEventListener("change", update);
  form.addEventListener("change", (e) => { if (e.target.name === "param" || e.target.name === "importance" || e.target.name === "apply_to" || e.target.name === "card_length") renderSummary(); });
  form.addEventListener("input", (e) => { if (e.target.name === "param") renderSummary(); });

  // ---- canlı özet cümlesi ---------------------------------------------------------------------------
  function renderSummary() {
    const box = $("[data-rel-summary]");
    const c = select.value;
    const n = $("[name=param]", form).value || "N";
    let rule = (select.selectedOptions[0] ? select.selectedOptions[0].textContent : "").split(" · ")[0];
    rule = rule.replace(/\bN\b/g, n);
    const imp = $("[name=importance]:checked", form);
    const apply = $("[name=apply_to]:checked", form);
    const len = $("[name=card_length]:checked", form);
    const a = lessonChips("a");
    const target = a.length ? a.slice(0, 3).join(", ") + (a.length > 3 ? " +" + (a.length - 3) : "") : "tüm dersler";
    const cls = values("classes").length ? values("classes").length + " sınıf" : "";
    const tch = values("teachers").length ? values("teachers").length + " öğretmen" : "";
    box.innerHTML = '<span class="rel-imp-dot ' + esc(imp ? imp.value : "") + '"></span>' +
      "<span>" + (apply && !$('[data-rel-show="apply"]').hidden ? "<b>" + esc(apply.closest("label").querySelector("b").textContent) + ":</b> " : "") +
      target + (cls || tch ? " <small>(" + [cls, tch].filter(Boolean).join(", ") + ")</small>" : "") +
      (len && len.value ? " · <small>" + esc(len.closest("label").textContent.trim()) + " kartlar</small>" : "") +
      " → <b>" + esc(rule) + "</b>" + (sets.two.includes(c) ? " <small>(B: " + (lessonChips("b").slice(0, 2).join(", ") || "seçilmedi") + ")</small>" : "") + "</span>";
  }

  // ---- seçici penceresi --------------------------------------------------------------------------------
  const dlg = $("[data-rel-picker]");
  const listBox = $("[data-rp-list]", dlg);
  const searchBox = $("[data-rp-search]", dlg);
  const onlyBox = $("[data-rp-only]", dlg);
  let current = null;  // {kind, side, picked:{subjects:Set, lessons:Set} | Set}
  const TITLES = { lessons: "Dersler", lessons_b: "Dersler (B tarafı)", classes: "Sınıflar", teachers: "Öğretmenler", classrooms: "Derslikler" };
  const HINTS = {
    lessons: "Ders adının kutusu o adın tüm kısımlarını (sonradan eklenenler dahil) seçer; tek tek kısım da seçebilirsiniz. Rozet: Teori / Uygulama (U).",
    classes: "Grup başlığındaki kutu o bölümün tüm sınıflarını seçer.",
    teachers: "Grup başlığındaki kutu o bölümün tüm öğretmenlerini seçer (bölüm öğretmen kartından).",
    classrooms: "Grup başlığındaki kutu o binanın/önekin tüm dersliklerini seçer.",
  };

  function open(kind) {
    const lessonKind = kind === "lessons" || kind === "lessons_b";
    const sfx = kind === "lessons_b" ? "_b" : "";
    current = lessonKind
      ? { kind, lessonKind, sfx, subjects: new Set(values("subjects" + sfx)), lessons: new Set(values("lessons" + sfx)), open: new Set() }
      : { kind, lessonKind, items: new Set(values(kind)), open: new Set() };
    $("[data-rp-title]", dlg).textContent = TITLES[kind];
    $("[data-rp-hint]", dlg).textContent = HINTS[lessonKind ? "lessons" : kind];
    searchBox.value = "";
    onlyBox.checked = false;
    if (lessonKind) {  // seçili olanların grupları açık gelir
      current.lessons.forEach((id) => { const l = lessons.get(id); if (l) current.open.add(l.subject.id); });
    }
    render();
    dlg.showModal();
    searchBox.focus();
  }

  function render() {
    const q = norm(searchBox.value.trim());
    const only = onlyBox.checked;
    let html = "";
    if (current.lessonKind) {
      data.subjects.forEach((s) => {
        const whole = current.subjects.has(s.id);
        const headHit = !q || norm(s.code + " " + s.name).includes(q);
        let items = s.lessons.filter((l) => headHit || norm(l.classes + " " + l.teachers).includes(q));
        if (only) items = items.filter((l) => whole || current.lessons.has(l.id));
        if (!items.length && !(headHit && (!only || whole))) return;
        const picked = s.lessons.filter((l) => current.lessons.has(l.id)).length;
        const isOpen = current.open.has(s.id) || (q && !headHit) || (q && s.lessons.length <= 3);
        html += '<div class="rp-group' + (isOpen ? " open" : "") + '" data-subject="' + s.id + '">' +
          '<div class="rp-head"><label class="rp-check"><input type="checkbox" data-sub="' + s.id + '"' + (whole ? " checked" : "") + (!whole && picked ? ' data-partial="1"' : "") + "></label>" +
          '<button type="button" class="rp-toggle" data-toggle="' + s.id + '"><span class="rp-caret">▸</span><b>' + esc(s.code || "") + "</b> " + esc(s.name) + " " + kindBadge(s) +
          '<small>' + s.lessons.length + " kısım" + (picked && !whole ? " · " + picked + " seçili" : "") + (whole ? " · tümü" : "") + "</small></button></div>";
        html += '<div class="rp-items">' + items.map((l) =>
          '<label class="rp-item' + (whole ? " via" : "") + '"><input type="checkbox" data-lesson="' + l.id + '"' + (whole || current.lessons.has(l.id) ? " checked" : "") + (whole ? " disabled" : "") + ">" +
          "<span><b>" + esc(l.classes) + "</b><small>" + esc(l.teachers) + " · " + l.hours + " saat" + (l.blocks > 1 ? " (" + l.blocks + "'li blok)" : "") + "</small></span></label>").join("") + "</div></div>";
      });
    } else {
      const rows = plain[current.kind];
      const groups = new Map();
      rows.forEach((r) => {
        if (q && !norm(r.full + " " + r.name + " " + r.group).includes(q)) return;
        if (only && !current.items.has(r.id)) return;
        if (!groups.has(r.group)) groups.set(r.group, []);
        groups.get(r.group).push(r);
      });
      groups.forEach((items, name) => {
        const n = items.filter((r) => current.items.has(r.id)).length;
        html += '<div class="rp-group open flat"><div class="rp-head"><label class="rp-check"><input type="checkbox" data-grp="' + esc(name) + '"' + (n === items.length ? " checked" : n ? ' data-partial="1"' : "") + "></label>" +
          "<span class=\"rp-gname\"><b>" + esc(name) + "</b><small>" + items.length + (n ? " · " + n + " seçili" : "") + "</small></span></div>" +
          '<div class="rp-items grid">' + items.map((r) => '<label class="rp-item"><input type="checkbox" data-item="' + r.id + '"' + (current.items.has(r.id) ? " checked" : "") + "><span>" + esc(r.name) + (r.full && r.full !== r.name ? "<small>" + esc(r.full) + "</small>" : "") + "</span></label>").join("") + "</div></div>";
      });
    }
    listBox.innerHTML = html || '<p class="subtle" style="padding:16px">Eşleşen kayıt yok.</p>';
    $$("input[data-partial]", listBox).forEach((i) => { i.indeterminate = true; });
    count();
  }
  function count() {
    const n = current.lessonKind ? current.subjects.size + " ders adı, " + current.lessons.size + " kısım seçili" : current.items.size + " seçili";
    $("[data-rp-count]", dlg).textContent = n;
  }

  listBox.addEventListener("click", (e) => {
    const toggle = e.target.closest("[data-toggle]");
    if (toggle) {
      const id = Number(toggle.dataset.toggle);
      current.open.has(id) ? current.open.delete(id) : current.open.add(id);
      toggle.closest(".rp-group").classList.toggle("open");
    }
  });
  listBox.addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.sub) {
      const id = Number(t.dataset.sub);
      if (t.checked) { current.subjects.add(id); subjects.get(id).lessons.forEach((l) => current.lessons.delete(l.id)); }
      else current.subjects.delete(id);
      render();
    } else if (t.dataset.lesson) {
      const id = Number(t.dataset.lesson);
      t.checked ? current.lessons.add(id) : current.lessons.delete(id);
      render();
    } else if (t.dataset.grp != null && t.dataset.grp !== undefined && t.hasAttribute("data-grp")) {
      const rows = $$("input[data-item]", t.closest(".rp-group")).map((i) => Number(i.dataset.item));
      rows.forEach((id) => (t.checked ? current.items.add(id) : current.items.delete(id)));
      render();
    } else if (t.dataset.item) {
      const id = Number(t.dataset.item);
      t.checked ? current.items.add(id) : current.items.delete(id);
      render();
    }
  });
  searchBox.addEventListener("input", render);
  onlyBox.addEventListener("change", render);
  $("[data-rp-all]", dlg).addEventListener("click", () => {
    if (current.lessonKind) $$("input[data-lesson]:not(:disabled)", listBox).forEach((i) => current.lessons.add(Number(i.dataset.lesson)));
    else $$("input[data-item]", listBox).forEach((i) => current.items.add(Number(i.dataset.item)));
    render();
  });
  $("[data-rp-none]", dlg).addEventListener("click", () => {
    if (current.lessonKind) { current.subjects.clear(); current.lessons.clear(); } else current.items.clear();
    render();
  });
  $$("[data-rp-close]", dlg).forEach((b) => b.addEventListener("click", () => dlg.close()));
  $("[data-rp-ok]", dlg).addEventListener("click", () => {
    if (current.lessonKind) {
      setValues("subjects" + current.sfx, [...current.subjects]);
      setValues("lessons" + current.sfx, [...current.lessons]);
    } else setValues(current.kind, [...current.items]);
    dlg.close();
    renderChips();
    changed();
  });
  searchBox.addEventListener("keydown", (e) => { if (e.key === "Enter") e.preventDefault(); });
  $$("[data-rel-open]", form).forEach((b) => b.addEventListener("click", () => open(b.dataset.relOpen)));

  // ---- zaman haritaları ------------------------------------------------------------------------------
  const meta = JSON.parse($("#time-map-meta").textContent);
  $$("[data-time-map]", form).forEach((box) => {
    const input = $("input[type=hidden]", box);
    const grid = $(".avail-grid", box);
    const row = box.closest("[data-map-row]");
    let cells;
    try { cells = new Set(JSON.parse(input.value || "[]")); } catch (e) { cells = new Set(); }
    const all = [];
    meta.days.forEach((_, d) => meta.periods.forEach((_, p) => all.push(d + "-" + p)));
    const paint = () => {
      $$(".av-cell", grid).forEach((c) => {
        const on = cells.has(c.dataset.key);
        c.classList.toggle("map-on", on);
        c.setAttribute("aria-pressed", on ? "true" : "false");
      });
      input.value = JSON.stringify([...cells]);
      changed();
    };
    let html = '<table class="avail-table rel-map"><thead><tr><th></th>';
    meta.periods.forEach((p, j) => { html += '<th><button type="button" class="av-head" data-period="' + j + '">' + (j + 1) + "<small>" + esc(p.start) + "</small></button></th>"; });
    html += "</tr></thead><tbody>";
    meta.days.forEach((day, d) => {
      html += '<tr><th><button type="button" class="av-head av-day" data-day="' + d + '">' + esc(day) + "</button></th>";
      meta.periods.forEach((_, j) => { html += '<td><button type="button" class="av-cell map-cell" data-key="' + d + "-" + j + '" aria-label="' + esc(day) + " " + (j + 1) + '. saat"></button></td>'; });
      html += "</tr>";
    });
    grid.innerHTML = html + "</tbody></table>";
    // basılı tutup sürükleyerek boyama: ilk hücrenin tersine göre
    let painting = null;
    grid.addEventListener("pointerdown", (e) => {
      const cell = e.target.closest(".av-cell");
      if (!cell) return;
      e.preventDefault();
      painting = !cells.has(cell.dataset.key);
      painting ? cells.add(cell.dataset.key) : cells.delete(cell.dataset.key);
      paint();
    });
    grid.addEventListener("pointerover", (e) => {
      const cell = e.target.closest(".av-cell");
      if (painting === null || !cell) return;
      painting ? cells.add(cell.dataset.key) : cells.delete(cell.dataset.key);
      paint();
    });
    document.addEventListener("pointerup", () => { painting = null; });
    grid.addEventListener("click", (e) => {
      const head = e.target.closest(".av-head");
      if (!head) return;
      const keys = head.dataset.day != null ? meta.periods.map((_, j) => head.dataset.day + "-" + j) : meta.days.map((_, d) => d + "-" + head.dataset.period);
      const on = keys.every((k) => cells.has(k));
      keys.forEach((k) => (on ? cells.delete(k) : cells.add(k)));
      paint();
    });
    $("[data-map-all]", row).addEventListener("click", () => { all.forEach((k) => cells.add(k)); paint(); });
    $("[data-map-none]", row).addEventListener("click", () => { cells.clear(); paint(); });
    $("[data-map-invert]", row).addEventListener("click", () => { all.forEach((k) => (cells.has(k) ? cells.delete(k) : cells.add(k))); paint(); });
    $$(".av-cell", grid).forEach((c) => {
      const on = cells.has(c.dataset.key);
      c.classList.toggle("map-on", on);
    });
  });

  renderChips();
  update();
})();
