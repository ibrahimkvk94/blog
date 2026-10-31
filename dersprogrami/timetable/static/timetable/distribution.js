/* Ders dağıtım çizelgesi: ders adı × sınıf matrisi, öğretmen fırçası, toplu saat ve Excel'den yapıştırma. */
(function () {
  "use strict";
  const D = JSON.parse(document.getElementById("dist-data").textContent);
  const $ = (s) => document.querySelector(s);
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const csrf = () => (document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/) || [])[1] || document.querySelector("[name=csrfmiddlewaretoken]")?.value || "";
  const TEACHER = Object.fromEntries(D.teachers.map((t) => [t.id, t]));
  const key = (s, c) => s + "-" + c;

  const original = JSON.parse(JSON.stringify(D.cells));
  const cells = D.cells;
  const state = { grade: "all", brush: "", painting: false, editing: null };

  function toast(message, kind) {
    const t = document.createElement("div");
    t.className = "toast" + (kind === "error" ? " error" : "");
    t.textContent = message;
    $("#toasts").appendChild(t);
    setTimeout(() => t.remove(), 4200);
  }
  async function post(url, body) {
    const res = await fetch(url, { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json", "X-CSRFToken": csrf() }, body: JSON.stringify(body) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok || data.ok === false) throw new Error(data.message || "İşlem başarısız oldu.");
    return data;
  }

  // ---- değişiklik takibi -------------------------------------------------------------------
  const same = (a, b) => (a?.hours || 0) === (b?.hours || 0) && (a?.length || 1) === (b?.length || 1) && (a?.teacher ?? null) === (b?.teacher ?? null);
  const dirtyKeys = () => [...new Set([...Object.keys(cells), ...Object.keys(original)])].filter((k) => !same(cells[k], original[k]));
  function updateDirty() {
    const n = dirtyKeys().length;
    $("#dist-save").disabled = $("#dist-undo").disabled = n === 0;
    $("#dist-dirty").textContent = n ? "(" + n + ")" : "";
  }
  window.addEventListener("beforeunload", (e) => { if (dirtyKeys().length) { e.preventDefault(); e.returnValue = ""; } });

  // ---- çizim -------------------------------------------------------------------------------
  const visibleClasses = () => D.classes.filter((c) => state.grade === "all" || String(c.grade) === state.grade);

  function renderGrades() {
    const grades = [...new Set(D.classes.map((c) => c.grade).filter((g) => g != null))].sort((a, b) => a - b);
    const box = $("#dist-grades");
    box.innerHTML = '<button data-g="all" class="active">Tüm sınıflar</button>' + grades.map((g) => '<button data-g="' + g + '">' + g + ". sınıflar</button>").join("");
    box.addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      state.grade = b.dataset.g;
      box.querySelectorAll("button").forEach((x) => x.classList.toggle("active", x === b));
      renderTable();
    });
  }

  function cellHtml(subject, cls) {
    const k = key(subject.id, cls.id);
    const c = cells[k];
    const cx = D.complex[k];
    const t = c && c.teacher ? TEACHER[c.teacher] : null;
    const classes = ["dcell"];
    if (c && c.hours) classes.push("has");
    if (c && c.hours && !t) classes.push("no-teacher");
    if (!same(c, original[k])) classes.push("changed");
    if (state.brush && state.brush !== "none" && c && String(c.teacher) === state.brush) classes.push("mark");
    const outOfBranch = t && t.subjects && t.subjects.length && !t.subjects.includes(subject.id);
    if (c && c.hours && outOfBranch) classes.push("off-branch");
    const title = [subject.name + " · " + cls.name, c && c.hours ? c.hours + " saat" + (c.length > 1 ? " (" + c.length + "'li blok)" : "") : "ders yok", t ? t.name + (outOfBranch ? " (branş dışı)" : "") : c && c.hours ? "öğretmen yok" : "", cx ? "+" + cx + " saat gruplu/birleşik ders" : ""].filter(Boolean).join("\n");
    return '<button type="button" class="' + classes.join(" ") + '" style="--c:' + subject.color + '" data-k="' + k + '" title="' + esc(title) + '">' +
      (c && c.hours ? '<span class="h">' + c.hours + (c.length > 1 ? "<small>×" + c.length + "</small>" : "") + '</span><span class="t">' + esc(t ? t.short : "öğretmen yok") + "</span>" : '<span class="t">·</span>') +
      (cx ? '<span class="cx">+' + cx + "</span>" : "") + "</button>";
  }

  function classTotal(cls) {
    let sum = 0;
    D.subjects.forEach((s) => { const k = key(s.id, cls.id); sum += (cells[k]?.hours || 0) + (D.complex[k] || 0); });
    return sum;
  }

  function renderTable() {
    const classes = visibleClasses();
    let lastGrade = null;
    const gradeStart = classes.map((c) => { const start = c.grade !== lastGrade; lastGrade = c.grade; return start; });
    let html = '<thead><tr><th class="rowhead">Ders adı</th>' + classes.map((c, i) => '<th class="' + (gradeStart[i] ? "grade-start" : "") + '">' + esc(c.name) + "</th>").join("") + "<th>Toplam</th></tr></thead><tbody>";
    D.subjects.forEach((s) => {
      let total = 0;
      html += '<tr><th class="rowhead"><div class="nm"><span class="swatch" style="background:' + s.color + '"></span>' + esc(s.name) + '</div><div class="fill"><input class="input" type="number" min="0" max="20" placeholder="saat" data-fill="' + s.id + '" aria-label="' + esc(s.name) + ' için görünen tüm sınıflara saat"><button type="button" class="btn" data-fill-btn="' + s.id + '">Görünen sınıflara</button></div></th>';
      classes.forEach((c, i) => {
        total += cells[key(s.id, c.id)]?.hours || 0;
        html += '<td class="' + (gradeStart[i] ? "grade-start" : "") + '">' + cellHtml(s, c) + "</td>";
      });
      html += '<td class="total">' + (total || "") + "</td></tr>";
    });
    html += '</tbody><tfoot><tr><td class="rowhead">Sınıf toplamı / ' + D.capacity + "</td>" + classes.map((c, i) => { const t = classTotal(c); return '<td class="' + (gradeStart[i] ? "grade-start " : "") + (t > D.capacity ? "over-cap" : "") + '">' + t + "</td>"; }).join("") + "<td></td></tr></tfoot>";
    $("#dist-table").innerHTML = html;
    $("#dist-table").classList.toggle("brushing", !!state.brush);
    renderTeachers();
    updateDirty();
  }

  function teacherLoad(id) {
    let sum = TEACHER[id].fixed || 0;
    Object.values(cells).forEach((c) => { if (c && c.teacher === id) sum += c.hours || 0; });
    return sum;
  }
  function renderTeachers() {
    const q = ($("#dist-teacher-search").value || "").trim().toLocaleLowerCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i");
    $("#dist-teachers").innerHTML = D.teachers
      .filter((t) => !q || t.name.toLocaleLowerCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i").includes(q) || t.short.toLocaleLowerCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i").includes(q))
      .map((t) => {
        const load = teacherLoad(t.id);
        const cap = t.target || D.capacity;
        const pct = Math.min(100, Math.round((load / cap) * 100));
        const diff = t.target ? load - t.target : 0;
        const state_ = !t.target ? "" : diff === 0 ? " full" : diff > 0 ? " over" : " under";
        const value = t.target ? load + " / " + t.target + " saat" + (diff ? " (" + (diff > 0 ? "+" : "") + diff + ")" : " ✓") : load + " saat";
        return '<li data-t="' + t.id + '" class="' + (state.brush === String(t.id) ? "on" : "") + state_ + '" title="' + (t.target ? "Hedef yük: " + t.target + " saat" : "Hedef yük girilmemiş") + '"><span class="n">' + esc(t.name) + '</span><span class="v">' + value + "</span>" +
          '<div class="progress"><div style="width:' + pct + '%"></div></div></li>';
      }).join("") || '<li class="subtle">Öğretmen yok.</li>';
  }

  // ---- fırça ve düzenleme ------------------------------------------------------------------
  const brushSelect = $("#dist-brush");
  D.teachers.forEach((t) => brushSelect.insertAdjacentHTML("beforeend", '<option value="' + t.id + '">' + esc(t.name) + "</option>"));
  const popTeacher = $("#pop-teacher");
  D.teachers.forEach((t) => popTeacher.insertAdjacentHTML("beforeend", '<option value="' + t.id + '">' + esc(t.name) + "</option>"));

  function setBrush(value) {
    state.brush = value;
    brushSelect.value = value;
    closePop();
    renderTable();
  }
  brushSelect.addEventListener("change", () => setBrush(brushSelect.value));
  $("#dist-teachers").addEventListener("click", (e) => {
    const li = e.target.closest("li[data-t]");
    if (li) setBrush(state.brush === li.dataset.t ? "" : li.dataset.t);
  });
  $("#dist-teacher-search").addEventListener("input", renderTeachers);

  function paint(k) {
    const c = cells[k] ? { ...cells[k] } : { hours: 0, length: 1, teacher: null };
    if (state.brush === "none") c.teacher = null;
    else {
      c.teacher = Number(state.brush);
      const h = parseInt($("#dist-brush-hours").value || "0", 10);
      if (!c.hours && h > 0) c.hours = h;
      if (!c.hours) { toast("Bu hücrede ders saati yok. “Boş hücreye saat” alanına saat yazın ya da hücreyi düzenleyin.", "error"); return; }
    }
    cells[k] = c;
    const [s, cl] = k.split("-").map(Number);
    const btn = document.querySelector('.dcell[data-k="' + k + '"]');
    if (btn) btn.outerHTML = cellHtml(D.subjects.find((x) => x.id === s), D.classes.find((x) => x.id === cl));
  }

  const table = $("#dist-table");
  table.addEventListener("mousedown", (e) => {
    const cell = e.target.closest(".dcell");
    if (!cell || !state.brush) return;
    e.preventDefault();
    state.painting = true;
    paint(cell.dataset.k);
  });
  table.addEventListener("mouseover", (e) => {
    if (!state.painting) return;
    const cell = e.target.closest(".dcell");
    if (cell && !cell.classList.contains("mark")) paint(cell.dataset.k);
  });
  document.addEventListener("mouseup", () => { if (state.painting) { state.painting = false; renderTable(); } });

  table.addEventListener("click", (e) => {
    const fillBtn = e.target.closest("[data-fill-btn]");
    if (fillBtn) {
      const sid = Number(fillBtn.dataset.fillBtn);
      const hours = parseInt(document.querySelector('[data-fill="' + sid + '"]').value || "", 10);
      if (Number.isNaN(hours)) { toast("Önce saat yazın.", "error"); return; }
      visibleClasses().forEach((c) => { const k = key(sid, c.id); cells[k] = { ...(cells[k] || { length: 1, teacher: null }), hours }; });
      renderTable();
      return;
    }
    const cell = e.target.closest(".dcell");
    if (!cell || state.brush) return;
    openPop(cell);
  });

  // Hücre düzenleme penceresi
  const pop = $("#dist-pop");
  function openPop(cell) {
    const k = cell.dataset.k;
    const [s, cl] = k.split("-").map(Number);
    const c = cells[k] || { hours: 0, length: 1, teacher: null };
    state.editing = k;
    $("#dist-pop-title").textContent = D.subjects.find((x) => x.id === s).name + " · " + D.classes.find((x) => x.id === cl).name;
    $("#pop-hours").value = c.hours || "";
    $("#pop-length").value = String(c.length || 1);
    popTeacher.value = c.teacher ? String(c.teacher) : "";
    const r = cell.getBoundingClientRect();
    pop.hidden = false;
    pop.style.top = window.scrollY + r.bottom + 6 + "px";
    pop.style.left = Math.min(window.scrollX + r.left, window.scrollX + document.documentElement.clientWidth - pop.offsetWidth - 16) + "px";
    $("#pop-hours").focus();
    $("#pop-hours").select();
  }
  function closePop() { pop.hidden = true; state.editing = null; }
  function applyPop() {
    if (!state.editing) return;
    const hours = Math.max(0, parseInt($("#pop-hours").value || "0", 10) || 0);
    cells[state.editing] = { hours, length: Number($("#pop-length").value), teacher: popTeacher.value ? Number(popTeacher.value) : null };
    closePop();
    renderTable();
  }
  $("#pop-ok").addEventListener("click", applyPop);
  $("#pop-clear").addEventListener("click", () => { $("#pop-hours").value = ""; popTeacher.value = ""; applyPop(); });
  pop.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); applyPop(); } if (e.key === "Escape") closePop(); });
  document.addEventListener("mousedown", (e) => { if (!pop.hidden && !pop.contains(e.target) && !e.target.closest(".dcell")) closePop(); });
  document.body.appendChild(pop);

  // ---- kaydet / geri al --------------------------------------------------------------------
  $("#dist-undo").addEventListener("click", () => {
    Object.keys(cells).forEach((k) => delete cells[k]);
    Object.assign(cells, JSON.parse(JSON.stringify(original)));
    renderTable();
  });
  $("#dist-save").addEventListener("click", async () => {
    const payload = dirtyKeys().map((k) => {
      const [subject, cls] = k.split("-").map(Number);
      const c = cells[k] || { hours: 0 };
      return { subject, class: cls, hours: c.hours || 0, length: c.length || 1, teacher: c.teacher ?? null };
    });
    $("#dist-save").disabled = true;
    try {
      const r = await post(D.saveUrl, { cells: payload });
      Object.keys(original).forEach((k) => delete original[k]);
      Object.entries(cells).forEach(([k, c]) => { if (c && c.hours) original[k] = { ...c }; else delete cells[k]; });
      toast(r.message);
      renderTable();
    } catch (e) {
      toast(e.message, "error");
      updateDirty();
    }
  });

  // ---- Excel'den yapıştırma ----------------------------------------------------------------
  const pasteUrl = D.saveUrl.replace(/kaydet\/$/, "yapistir/");
  async function paste(apply) {
    const text = $("#dist-paste").value;
    if (!text.trim()) { toast("Önce Excel'den satırları yapıştırın.", "error"); return; }
    if (apply && dirtyKeys().length && !window.confirm("Kaydedilmemiş matris değişiklikleri kaybolacak. Devam edilsin mi?")) return;
    try {
      const r = await post(pasteUrl, { text, apply });
      if (r.applied) { window.onbeforeunload = null; Object.keys(cells).forEach((k) => delete cells[k]); Object.assign(cells, original); location.reload(); return; }
      const rows = r.rows || [];
      $("#dist-apply").disabled = r.errors > 0 || rows.length === 0;
      $("#dist-paste-result").innerHTML = rows.length
        ? (r.errors ? '<div class="alert alert-error">' + r.errors + " satırda hata var; düzeltip yeniden önizleyin.</div>" : '<div class="alert alert-success">' + rows.length + " satır aktarılmaya hazır. “Aktar” ile kaydedin.</div>") +
          '<div class="table-wrap"><table class="table paste-table"><thead><tr><th>#</th><th>Öğretmen</th><th>Ders</th><th>Sınıflar</th><th class="num">Saat</th><th>Durum</th></tr></thead><tbody>' +
          rows.map((x) => '<tr class="' + (x.errors.length ? "bad" : "") + '"><td class="subtle">' + x.line + "</td><td>" + esc(x.teacher || "—") + "</td><td>" + esc(x.subject) + "</td><td>" + esc(x.classes.join(", ")) + '</td><td class="num">' + esc(x.hours) + (x.length > 1 ? " (" + esc(x.length) + "'li)" : "") + "</td><td>" + esc(x.errors.length ? x.errors.join("; ") : x.notes.join(", ") || "hazır") + "</td></tr>").join("") +
          "</tbody></table></div>"
        : '<p class="subtle">Satır bulunamadı.</p>';
    } catch (e) {
      toast(e.message, "error");
    }
  }
  $("#dist-preview").addEventListener("click", () => paste(false));
  $("#dist-apply").addEventListener("click", () => paste(true));
  $("#dist-paste").addEventListener("input", () => { $("#dist-apply").disabled = true; });

  renderGrades();
  renderTable();
})();
