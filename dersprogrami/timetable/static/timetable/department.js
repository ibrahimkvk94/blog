// Bölüm ders dağılımı: ders başına öğretmen + kısım satırları, kısım toplamı denetimi ve öğretmen yükleri (canlı).
(function () {
  const form = document.getElementById("dp-form");
  if (!form) return;
  const teachers = JSON.parse(document.getElementById("dp-teachers").textContent);
  const names = Object.fromEntries(teachers.map((t) => [String(t.id), t.name]));

  function fill(select) {
    const value = select.dataset.value || select.value;
    const groups = {};
    teachers.forEach((t) => { (groups[t.group] = groups[t.group] || []).push(t); });
    select.innerHTML = '<option value="">— öğretmen seçin —</option>' + Object.entries(groups).map(([g, list]) =>
      '<optgroup label="' + g + '">' + list.map((t) => '<option value="' + t.id + '">' + t.name.replace(/</g, "&lt;") + "</option>").join("") + "</optgroup>").join("");
    select.value = value;
  }

  function update() {
    const inside = {};
    let problems = 0;
    form.querySelectorAll(".dp-subject").forEach((section) => {
      const sections = +section.dataset.sections, hours = +section.dataset.hours;
      let total = 0;
      const seen = new Set();
      section.querySelectorAll(".dp-row").forEach((row) => {
        const t = row.querySelector("select").value, n = +row.querySelector("input").value || 0;
        row.querySelector(".dp-hours").textContent = n ? n * hours + " saat" : "";
        row.classList.toggle("dup", !!t && seen.has(t));
        if (t) { seen.add(t); total += n; inside[t] = (inside[t] || 0) + n * hours; }
      });
      const state = section.querySelector("[data-dp-state]");
      const ok = total === sections && sections > 0;
      state.className = "pill " + (ok ? "ok" : total > sections ? "error" : "warn");
      state.textContent = ok ? sections + "/" + sections + " kısım" : total > sections ? total + "/" + sections + " · " + (total - sections) + " fazla" : total + "/" + sections + " · " + (sections - total) + " eksik";
      if (!ok) problems += 1;
    });
    const body = form.querySelector(".dp-loads tbody");
    Object.keys(inside).forEach((t) => {
      if (!body.querySelector('[data-dp-load="' + t + '"]')) {
        const tr = document.createElement("tr");
        tr.dataset.dpLoad = t; tr.dataset.outside = "0"; tr.dataset.target = "";
        tr.innerHTML = "<td></td><td class='num' data-in></td><td class='num'>0</td><td class='num'><b data-total></b></td>";
        tr.firstChild.textContent = names[t] || t;
        body.appendChild(tr);
      }
    });
    body.querySelectorAll("tr").forEach((tr) => {
      const n = inside[tr.dataset.dpLoad] || 0, total = n + (+tr.dataset.outside || 0);
      tr.querySelector("[data-in]").textContent = n;
      tr.querySelector("[data-total]").textContent = total;
      tr.classList.toggle("over", !!tr.dataset.target && total > +tr.dataset.target);
    });
    const summary = form.querySelector("[data-dp-summary]");
    if (summary) summary.textContent = problems ? problems + " derste kısım toplamı tutmuyor; yine de gönderebilirsiniz, program sorumlusu görür." : "Bütün derslerin kısımları dağıtıldı.";
  }

  function addRow(subject, teacherId, count) {
    const rows = form.querySelector('[data-dp-rows="' + subject + '"]');
    const existing = [...rows.querySelectorAll("select")].find((s) => s.value === String(teacherId));
    if (existing) { existing.closest(".dp-row").querySelector("input").focus(); return; }
    const row = document.createElement("div");
    row.className = "dp-row";
    row.innerHTML = '<select class="select select-sm" name="t-' + subject + '"></select>' +
      '<input class="input input-sm" type="number" min="0" name="n-' + subject + '" value="' + (count || 1) + '" aria-label="Kısım">' +
      '<span class="dp-hours"></span><button type="button" class="btn btn-sm btn-ghost" data-dp-remove aria-label="Satırı sil">✕</button>';
    rows.appendChild(row);
    const select = row.querySelector("select");
    if (teacherId) select.dataset.value = teacherId;
    fill(select);
    (teacherId ? row.querySelector("input") : select).focus();
    update();
  }

  // Başka bölümden ya da yeni öğretmen: aramalı, bölümlere göre gruplu seçim penceresi
  const picker = document.getElementById("dp-picker");
  let pickFor = null;
  const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  function renderPicker() {
    const q = picker.querySelector("[data-dp-search]").value.trim().toLocaleLowerCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i");
    const groups = {};
    teachers.forEach((t) => {
      if (q && !(t.name + " " + t.group).toLocaleLowerCase("tr").normalize("NFD").replace(/[\u0300-\u036f]/g, "").replace(/ı/g, "i").includes(q)) return;
      (groups[t.group] = groups[t.group] || []).push(t);
    });
    const html = Object.entries(groups).map(([g, list]) => '<div class="dp-group"><h3>' + esc(g) + "</h3>" +
      list.map((t) => '<button type="button" data-dp-choose="' + t.id + '"><span>' + esc(t.name) + "</span><small>" + t.load + " saat" +
        (t.target ? " / " + t.target : "") + "</small></button>").join("") + "</div>").join("");
    picker.querySelector("[data-dp-list]").innerHTML = html || '<p class="subtle small">Eşleşen öğretmen yok. Aşağıdan yeni öğretmen tanımlayabilirsiniz.</p>';
  }
  if (picker) {
    picker.querySelector("[data-dp-search]").addEventListener("input", renderPicker);
    picker.addEventListener("click", (e) => {
      const b = e.target.closest("[data-dp-choose]");
      if (b) { picker.close(); addRow(pickFor, b.dataset.dpChoose); }
    });
    picker.querySelector("[data-dp-new-save]").addEventListener("click", async () => {
      const name = picker.querySelector("[data-dp-new-name]").value.trim();
      if (!name) { picker.querySelector("[data-dp-new-name]").focus(); return; }
      const data = new FormData();
      data.append("action", "new_teacher");
      data.append("name", name);
      data.append("short", picker.querySelector("[data-dp-new-short]").value);
      data.append("email", picker.querySelector("[data-dp-new-email]").value);
      data.append("csrfmiddlewaretoken", form.querySelector("[name=csrfmiddlewaretoken]").value);
      const res = await fetch(location.pathname, { method: "POST", body: data, headers: { "X-Requested-With": "fetch" } });
      const r = await res.json().catch(() => ({ ok: false, message: "Kaydedilemedi." }));
      if (!r.ok) { alert(r.message); return; }
      if (!teachers.some((t) => t.id === r.id)) teachers.unshift({ id: r.id, name: r.name, group: r.group, load: r.load });
      names[String(r.id)] = r.name;
      form.querySelectorAll(".dp-row select").forEach((s) => { s.dataset.value = s.value; fill(s); });
      picker.querySelectorAll(".dp-new-form input").forEach((i) => { i.value = ""; });
      picker.close();
      addRow(pickFor, r.id);
    });
  }

  form.querySelectorAll(".dp-row select").forEach(fill);
  form.addEventListener("input", update);
  form.addEventListener("change", update);
  form.addEventListener("click", (e) => {
    const add = e.target.closest("[data-dp-add]");
    if (add) addRow(add.dataset.dpAdd);
    const pick = e.target.closest("[data-dp-pick]");
    if (pick && picker) {
      pickFor = pick.dataset.dpPick;
      picker.querySelector("[data-dp-picker-title]").textContent = pick.dataset.dpTitle;
      picker.querySelector("[data-dp-search]").value = "";
      renderPicker();
      picker.showModal();
      picker.querySelector("[data-dp-search]").focus();
    }
    const remove = e.target.closest("[data-dp-remove]");
    if (remove) { remove.closest(".dp-row").remove(); update(); }
  });
  update();
})();
